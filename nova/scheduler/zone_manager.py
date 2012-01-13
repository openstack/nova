# Copyright (c) 2011 Openstack, LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
ZoneManager oversees all communications with child Zones.
"""

import datetime
import traceback
import UserDict

from eventlet import greenpool
from novaclient import v1_1 as novaclient

from nova import db
from nova import flags
from nova import log as logging
from nova import utils

FLAGS = flags.FLAGS
flags.DEFINE_integer('zone_db_check_interval', 60,
        'Seconds between getting fresh zone info from db.')
flags.DEFINE_integer('zone_failures_to_offline', 3,
        'Number of consecutive errors before marking zone offline')
flags.DEFINE_integer('reserved_host_disk_mb', 0,
        'Amount of disk in MB to reserve for host/dom0')
flags.DEFINE_integer('reserved_host_memory_mb', 512,
        'Amount of memory in MB to reserve for host/dom0')


class ZoneState(object):
    """Holds the state of all connected child zones."""
    def __init__(self):
        self.is_active = True
        self.name = None
        self.capabilities = None
        self.attempt = 0
        self.last_seen = datetime.datetime.min
        self.last_exception = None
        self.last_exception_time = None

    def update_credentials(self, zone):
        """Update zone credentials from db"""
        self.zone_id = zone.id
        self.name = zone.name
        self.api_url = zone.api_url
        self.username = zone.username
        self.password = zone.password
        self.weight_offset = zone.weight_offset
        self.weight_scale = zone.weight_scale

    def update_metadata(self, zone_metadata):
        """Update zone metadata after successful communications with
           child zone."""
        self.last_seen = utils.utcnow()
        self.attempt = 0
        self.capabilities = ", ".join(["%s=%s" % (k, v)
                        for k, v in zone_metadata.iteritems() if k != 'name'])
        self.is_active = True

    def to_dict(self):
        return dict(name=self.name, capabilities=self.capabilities,
                    is_active=self.is_active, api_url=self.api_url,
                    id=self.zone_id, weight_scale=self.weight_scale,
                    weight_offset=self.weight_offset)

    def log_error(self, exception):
        """Something went wrong. Check to see if zone should be
           marked as offline."""
        self.last_exception = exception
        self.last_exception_time = utils.utcnow()
        api_url = self.api_url
        logging.warning(_("'%(exception)s' error talking to "
                          "zone %(api_url)s") % locals())

        max_errors = FLAGS.zone_failures_to_offline
        self.attempt += 1
        if self.attempt >= max_errors:
            self.is_active = False
            logging.error(_("No answer from zone %(api_url)s "
                            "after %(max_errors)d "
                            "attempts. Marking inactive.") % locals())


def _call_novaclient(zone):
    """Call novaclient. Broken out for testing purposes. Note that
    we have to use the admin credentials for this since there is no
    available context."""
    client = novaclient.Client(zone.username, zone.password, None,
                               zone.api_url, region_name=zone.name)
    return client.zones.info()._info


def _poll_zone(zone):
    """Eventlet worker to poll a zone."""
    name = zone.name
    url = zone.api_url
    logging.debug(_("Polling zone: %(name)s @ %(url)s") % locals())
    try:
        zone.update_metadata(_call_novaclient(zone))
    except Exception, e:
        zone.log_error(traceback.format_exc())


class ReadOnlyDict(UserDict.IterableUserDict):
    """A read-only dict."""
    def __init__(self, source=None):
        self.update(source)

    def __setitem__(self, key, item):
        raise TypeError

    def __delitem__(self, key):
        raise TypeError

    def clear(self):
        raise TypeError

    def pop(self, key, *args):
        raise TypeError

    def popitem(self):
        raise TypeError

    def update(self, source=None):
        if source is None:
            return
        elif isinstance(source, UserDict.UserDict):
            self.data = source.data
        elif isinstance(source, dict):
            self.data = source
        else:
            raise TypeError


class HostInfo(object):
    """Mutable and immutable information on hosts tracked
    by the ZoneManager. This is an attempt to remove the
    ad-hoc data structures previously used and lock down
    access."""

    def __init__(self, host, caps=None, free_ram_mb=0, free_disk_gb=0):
        self.host = host

        # Read-only capability dicts
        self.compute = None
        self.volume = None
        self.network = None

        if caps:
            self.compute = ReadOnlyDict(caps.get('compute', None))
            self.volume = ReadOnlyDict(caps.get('volume', None))
            self.network = ReadOnlyDict(caps.get('network', None))

        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.free_ram_mb = free_ram_mb
        self.free_disk_gb = free_disk_gb

    def consume_resources(self, disk_gb, ram_mb):
        """Consume some of the mutable resources."""
        self.free_disk_gb -= disk_gb
        self.free_ram_mb -= ram_mb

    def __repr__(self):
        return "%s ram:%s disk:%s" % \
                    (self.host, self.free_ram_mb, self.free_disk_gb)


class ZoneManager(object):
    """Keeps the zone states updated."""
    def __init__(self):
        self.last_zone_db_check = datetime.datetime.min
        self.zone_states = {}  # { <zone_id> : ZoneState }
        self.service_states = {}  # { <host> : { <service> : { cap k : v }}}
        self.green_pool = greenpool.GreenPool()

    def get_zone_list(self):
        """Return the list of zones we know about."""
        return [zone.to_dict() for zone in self.zone_states.values()]

    def get_host_list(self):
        """Returns a list of dicts for each host that the Zone Manager
        knows about. Each dict contains the host_name and the service
        for that host.
        """
        all_hosts = self.service_states.keys()
        ret = []
        for host in self.service_states:
            for svc in self.service_states[host]:
                ret.append({"service": svc, "host_name": host})
        return ret

    def _compute_node_get_all(self, context):
        """Broken out for testing."""
        return db.compute_node_get_all(context)

    def _instance_get_all(self, context):
        """Broken out for testing."""
        return db.instance_get_all(context)

    def get_all_host_data(self, context):
        """Returns a dict of all the hosts the ZoneManager
        knows about. Also, each of the consumable resources in HostInfo
        are pre-populated and adjusted based on data in the db.

        For example:
        {'192.168.1.100': HostInfo(), ...}

        Note: this can be very slow with a lot of instances.
        InstanceType table isn't required since a copy is stored
        with the instance (in case the InstanceType changed since the
        instance was created)."""

        # Make a compute node dict with the bare essential metrics.
        compute_nodes = self._compute_node_get_all(context)
        host_info_map = {}
        for compute in compute_nodes:
            all_disk = compute['local_gb']
            all_ram = compute['memory_mb']
            service = compute['service']
            if not service:
                logging.warn(_("No service for compute ID %s") % compute['id'])
                continue

            host = service['host']
            caps = self.service_states.get(host, None)
            host_info = HostInfo(host, caps=caps,
                    free_disk_gb=all_disk, free_ram_mb=all_ram)
            # Reserve resources for host/dom0
            host_info.consume_resources(FLAGS.reserved_host_disk_mb * 1024,
                    FLAGS.reserved_host_memory_mb)
            host_info_map[host] = host_info

        # "Consume" resources from the host the instance resides on.
        instances = self._instance_get_all(context)
        for instance in instances:
            host = instance['host']
            if not host:
                continue
            host_info = host_info_map.get(host, None)
            if not host_info:
                continue
            disk = instance['local_gb']
            ram = instance['memory_mb']
            host_info.consume_resources(disk, ram)

        return host_info_map

    def get_zone_capabilities(self, context):
        """Roll up all the individual host info to generic 'service'
           capabilities. Each capability is aggregated into
           <cap>_min and <cap>_max values."""
        hosts_dict = self.service_states

        # TODO(sandy) - be smarter about fabricating this structure.
        # But it's likely to change once we understand what the Best-Match
        # code will need better.
        combined = {}  # { <service>_<cap> : (min, max), ... }
        stale_host_services = {}  # { host1 : [svc1, svc2], host2 :[svc1]}
        for host, host_dict in hosts_dict.iteritems():
            for service_name, service_dict in host_dict.iteritems():
                if not service_dict.get("enabled", True):
                    # Service is disabled; do no include it
                    continue

                #Check if the service capabilities became stale
                if self.host_service_caps_stale(host, service_name):
                    if host not in stale_host_services:
                        stale_host_services[host] = []  # Adding host key once
                    stale_host_services[host].append(service_name)
                    continue
                for cap, value in service_dict.iteritems():
                    if cap == "timestamp":  # Timestamp is not needed
                        continue
                    key = "%s_%s" % (service_name, cap)
                    min_value, max_value = combined.get(key, (value, value))
                    min_value = min(min_value, value)
                    max_value = max(max_value, value)
                    combined[key] = (min_value, max_value)

        # Delete the expired host services
        self.delete_expired_host_services(stale_host_services)
        return combined

    def _refresh_from_db(self, context):
        """Make our zone state map match the db."""
        # Add/update existing zones ...
        zones = db.zone_get_all(context)
        existing = self.zone_states.keys()
        db_keys = []
        for zone in zones:
            db_keys.append(zone.id)
            if zone.id not in existing:
                self.zone_states[zone.id] = ZoneState()
            self.zone_states[zone.id].update_credentials(zone)

        # Cleanup zones removed from db ...
        keys = self.zone_states.keys()  # since we're deleting
        for zone_id in keys:
            if zone_id not in db_keys:
                del self.zone_states[zone_id]

    def _poll_zones(self, context):
        """Try to connect to each child zone and get update."""
        self.green_pool.imap(_poll_zone, self.zone_states.values())

    def ping(self, context):
        """Ping should be called periodically to update zone status."""
        diff = utils.utcnow() - self.last_zone_db_check
        if diff.seconds >= FLAGS.zone_db_check_interval:
            logging.debug(_("Updating zone cache from db."))
            self.last_zone_db_check = utils.utcnow()
            self._refresh_from_db(context)
        self._poll_zones(context)

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        logging.debug(_("Received %(service_name)s service update from "
                "%(host)s.") % locals())
        service_caps = self.service_states.get(host, {})
        capabilities["timestamp"] = utils.utcnow()  # Reported time
        service_caps[service_name] = capabilities
        self.service_states[host] = service_caps

    def host_service_caps_stale(self, host, service):
        """Check if host service capabilites are not recent enough."""
        allowed_time_diff = FLAGS.periodic_interval * 3
        caps = self.service_states[host][service]
        if (utils.utcnow() - caps["timestamp"]) <= \
            datetime.timedelta(seconds=allowed_time_diff):
            return False
        return True

    def delete_expired_host_services(self, host_services_dict):
        """Delete all the inactive host services information."""
        for host, services in host_services_dict.iteritems():
            service_caps = self.service_states[host]
            for service in services:
                del service_caps[service]
                if len(service_caps) == 0:  # Delete host if no services
                    del self.service_states[host]
