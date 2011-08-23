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
import thread
import traceback

from novaclient import v1_1 as novaclient

from eventlet import greenpool

from nova import db
from nova import flags
from nova import log as logging
from nova import utils

FLAGS = flags.FLAGS
flags.DEFINE_integer('zone_db_check_interval', 60,
                    'Seconds between getting fresh zone info from db.')
flags.DEFINE_integer('zone_failures_to_offline', 3,
             'Number of consecutive errors before marking zone offline')


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
        self.api_url = zone.api_url
        self.username = zone.username
        self.password = zone.password

    def update_metadata(self, zone_metadata):
        """Update zone metadata after successful communications with
           child zone."""
        self.last_seen = utils.utcnow()
        self.attempt = 0
        self.name = zone_metadata.get("name", "n/a")
        self.capabilities = ", ".join(["%s=%s" % (k, v)
                        for k, v in zone_metadata.iteritems() if k != 'name'])
        self.is_active = True

    def to_dict(self):
        return dict(name=self.name, capabilities=self.capabilities,
                    is_active=self.is_active, api_url=self.api_url,
                    id=self.zone_id)

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
    """Call novaclient. Broken out for testing purposes."""
    client = novaclient.Client(zone.username, zone.password, None,
                               zone.api_url)
    return client.zones.info()._info


def _poll_zone(zone):
    """Eventlet worker to poll a zone."""
    logging.debug(_("Polling zone: %s") % zone.api_url)
    try:
        zone.update_metadata(_call_novaclient(zone))
    except Exception, e:
        zone.log_error(traceback.format_exc())


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

    def ping(self, context=None):
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
