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
Manage hosts in the current zone.
"""

import datetime
import types
import UserDict

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import utils


host_manager_opts = [
    cfg.IntOpt('reserved_host_disk_mb',
               default=0,
               help='Amount of disk in MB to reserve for host/dom0'),
    cfg.IntOpt('reserved_host_memory_mb',
               default=512,
               help='Amount of memory in MB to reserve for host/dom0'),
    cfg.ListOpt('default_host_filters',
                default=[
                  'AvailabilityZoneFilter',
                  'RamFilter',
                  'ComputeFilter'
                  ],
                help='Which filters to use for filtering hosts when not '
                     'specified in the request.'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(host_manager_opts)

LOG = logging.getLogger(__name__)


class ReadOnlyDict(UserDict.IterableUserDict):
    """A read-only dict."""
    def __init__(self, source=None):
        self.data = {}
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
        elif isinstance(source, type({})):
            self.data = source
        else:
            raise TypeError


class HostState(object):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def __init__(self, host, topic, capabilities=None, service=None):
        self.host = host
        self.topic = topic

        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities.get(topic, None))
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)
        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_total = 0
        self.vcpus_used = 0

    def update_from_compute_node(self, compute):
        """Update information about a host from its compute_node info."""
        all_disk_mb = compute['local_gb'] * 1024
        all_ram_mb = compute['memory_mb']
        vcpus_total = compute['vcpus']
        if FLAGS.reserved_host_disk_mb > 0:
            all_disk_mb -= FLAGS.reserved_host_disk_mb
        if FLAGS.reserved_host_memory_mb > 0:
            all_ram_mb -= FLAGS.reserved_host_memory_mb
        self.free_ram_mb = all_ram_mb
        self.free_disk_mb = all_disk_mb
        self.vcpus_total = vcpus_total

    def consume_from_instance(self, instance):
        """Update information about a host from instance info."""
        disk_mb = (instance['root_gb'] + instance['ephemeral_gb']) * 1024
        ram_mb = instance['memory_mb']
        vcpus = instance['vcpus']
        self.free_ram_mb -= ram_mb
        self.free_disk_mb -= disk_mb
        self.vcpus_used += vcpus

    def passes_filters(self, filter_fns, filter_properties):
        """Return whether or not this host passes filters."""

        if self.host in filter_properties.get('ignore_hosts', []):
            return False
        force_hosts = filter_properties.get('force_hosts', [])
        if force_hosts:
            return self.host in force_hosts
        for filter_fn in filter_fns:
            if not filter_fn(self, filter_properties):
                return False
        return True

    def __repr__(self):
        return ("host '%s': free_ram_mb:%s free_disk_mb:%s" %
                (self.host, self.free_ram_mb, self.free_disk_mb))


class HostManager(object):
    """Base HostManager class."""

    # Can be overriden in a subclass
    host_state_cls = HostState

    def __init__(self):
        self.service_states = {}  # { <host> : { <service> : { cap k : v }}}
        self.filter_classes = self._get_filter_classes()

    def _get_filter_classes(self):
        """Get the list of possible filter classes"""
        # Imported here to avoid circular imports
        from nova.scheduler import filters

        def get_itm(nm):
            return getattr(filters, nm)

        return [get_itm(itm) for itm in dir(filters)
                if (type(get_itm(itm)) is types.TypeType)
                and issubclass(get_itm(itm), filters.AbstractHostFilter)
                and get_itm(itm) is not filters.AbstractHostFilter]

    def _choose_host_filters(self, filters):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if filters is None:
            filters = FLAGS.default_host_filters
        if not isinstance(filters, (list, tuple)):
            filters = [filters]
        good_filters = []
        bad_filters = []
        for filter_name in filters:
            found_class = False
            for cls in self.filter_classes:
                if cls.__name__ == filter_name:
                    found_class = True
                    filter_instance = cls()
                    # Get the filter function
                    filter_func = getattr(filter_instance,
                            'host_passes', None)
                    if filter_func:
                        good_filters.append(filter_func)
                    break
            if not found_class:
                bad_filters.append(filter_name)
        if bad_filters:
            msg = ", ".join(bad_filters)
            raise exception.SchedulerHostFilterNotFound(filter_name=msg)
        return good_filters

    def filter_hosts(self, hosts, filter_properties, filters=None):
        """Filter hosts and return only ones passing all filters"""
        filtered_hosts = []
        filter_fns = self._choose_host_filters(filters)
        for host in hosts:
            if host.passes_filters(filter_fns, filter_properties):
                filtered_hosts.append(host)
        return filtered_hosts

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

    def get_service_capabilities(self):
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

                # Check if the service capabilities became stale
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

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        LOG.debug(_("Received %(service_name)s service update from "
                    "%(host)s.") % locals())
        service_caps = self.service_states.get(host, {})
        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = utils.utcnow()  # Reported time
        service_caps[service_name] = capab_copy
        self.service_states[host] = service_caps

    def host_service_caps_stale(self, host, service):
        """Check if host service capabilites are not recent enough."""
        allowed_time_diff = FLAGS.periodic_interval * 3
        caps = self.service_states[host][service]
        if ((utils.utcnow() - caps["timestamp"]) <=
            datetime.timedelta(seconds=allowed_time_diff)):
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

    def get_all_host_states(self, context, topic):
        """Returns a dict of all the hosts the HostManager
        knows about. Also, each of the consumable resources in HostState
        are pre-populated and adjusted based on data in the db.

        For example:
        {'192.168.1.100': HostState(), ...}

        Note: this can be very slow with a lot of instances.
        InstanceType table isn't required since a copy is stored
        with the instance (in case the InstanceType changed since the
        instance was created)."""

        if topic != 'compute':
            raise NotImplementedError(_(
                "host_manager only implemented for 'compute'"))

        host_state_map = {}

        # Make a compute node dict with the bare essential metrics.
        compute_nodes = db.compute_node_get_all(context)
        for compute in compute_nodes:
            service = compute['service']
            if not service:
                LOG.warn(_("No service for compute ID %s") % compute['id'])
                continue
            host = service['host']
            capabilities = self.service_states.get(host, None)
            host_state = self.host_state_cls(host, topic,
                    capabilities=capabilities,
                    service=dict(service.iteritems()))
            host_state.update_from_compute_node(compute)
            host_state_map[host] = host_state

        # "Consume" resources from the host the instance resides on.
        instances = db.instance_get_all(context)
        for instance in instances:
            host = instance['host']
            if not host:
                continue
            host_state = host_state_map.get(host, None)
            if not host_state:
                continue
            host_state.consume_from_instance(instance)
        return host_state_map
