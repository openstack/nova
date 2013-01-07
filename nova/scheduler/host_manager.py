# Copyright (c) 2011 OpenStack, LLC.
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

import UserDict

from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova.scheduler import filters

host_manager_opts = [
    cfg.MultiStrOpt('scheduler_available_filters',
            default=['nova.scheduler.filters.standard_filters'],
            help='Filter classes available to the scheduler which may '
                    'be specified more than once.  An entry of '
                    '"nova.scheduler.filters.standard_filters" '
                    'maps to all filters included with nova.'),
    cfg.ListOpt('scheduler_default_filters',
                default=[
                  'RetryFilter',
                  'AvailabilityZoneFilter',
                  'RamFilter',
                  'ComputeFilter',
                  'ComputeCapabilitiesFilter',
                  'ImagePropertiesFilter'
                  ],
                help='Which filter class names to use for filtering hosts '
                      'when not specified in the request.'),
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
        self.update_capabilities(topic, capabilities, service)

        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.total_usable_disk_gb = 0
        self.disk_mb_used = 0
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_total = 0
        self.vcpus_used = 0

        # Resource oversubscription values for the compute host:
        self.limits = {}

        self.updated = None

    def update_capabilities(self, topic, capabilities=None, service=None):
        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities.get(topic, None))
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)

    def update_from_compute_node(self, compute):
        """Update information about a host from its compute_node info."""
        if (self.updated and compute['updated_at']
            and self.updated > compute['updated_at']):
            return
        all_ram_mb = compute['memory_mb']

        # Assume virtual size is all consumed by instances if use qcow2 disk.
        least = compute.get('disk_available_least')
        free_disk_mb = least if least is not None else compute['free_disk_gb']
        free_disk_mb *= 1024

        self.disk_mb_used = compute['local_gb_used'] * 1024

        #NOTE(jogo) free_ram_mb can be negative
        self.free_ram_mb = compute['free_ram_mb']
        self.total_usable_ram_mb = all_ram_mb
        self.total_usable_disk_gb = compute['local_gb']
        self.free_disk_mb = free_disk_mb
        self.vcpus_total = compute['vcpus']
        self.vcpus_used = compute['vcpus_used']
        self.updated = compute['updated_at']

    def consume_from_instance(self, instance):
        """Incrementally update host state from an instance"""
        disk_mb = (instance['root_gb'] + instance['ephemeral_gb']) * 1024
        ram_mb = instance['memory_mb']
        vcpus = instance['vcpus']
        self.free_ram_mb -= ram_mb
        self.free_disk_mb -= disk_mb
        self.vcpus_used += vcpus
        self.updated = timeutils.utcnow()

    def passes_filters(self, filter_fns, filter_properties):
        """Return whether or not this host passes filters."""

        if self.host in filter_properties.get('ignore_hosts', []):
            LOG.debug(_('Host filter fails for ignored host %(host)s'),
                      {'host': self.host})
            return False

        force_hosts = filter_properties.get('force_hosts', [])
        if force_hosts:
            if not self.host in force_hosts:
                LOG.debug(_('Host filter fails for non-forced host %(host)s'),
                          {'host': self.host})
            return self.host in force_hosts

        for filter_fn in filter_fns:
            if not filter_fn(self, filter_properties):
                LOG.debug(_('Host filter function %(func)s failed for '
                            '%(host)s'),
                          {'func': repr(filter_fn),
                           'host': self.host})
                return False

        LOG.debug(_('Host filter passes for %(host)s'), {'host': self.host})
        return True

    def __repr__(self):
        return ("host '%s': free_ram_mb:%s free_disk_mb:%s" %
                (self.host, self.free_ram_mb, self.free_disk_mb))


class HostManager(object):
    """Base HostManager class."""

    # Can be overridden in a subclass
    host_state_cls = HostState

    def __init__(self):
        self.service_states = {}  # { <host> : { <service> : { cap k : v }}}
        self.host_state_map = {}
        self.filter_classes = filters.get_filter_classes(
                FLAGS.scheduler_available_filters)

    def _choose_host_filters(self, filters):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if filters is None:
            filters = FLAGS.scheduler_default_filters
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

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        LOG.debug(_("Received %(service_name)s service update from "
                    "%(host)s.") % locals())
        service_caps = self.service_states.get(host, {})
        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = timeutils.utcnow()  # Reported time
        service_caps[service_name] = capab_copy
        self.service_states[host] = service_caps

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

        # Get resource usage across the available compute nodes:
        compute_nodes = db.compute_node_get_all(context)
        for compute in compute_nodes:
            service = compute['service']
            if not service:
                LOG.warn(_("No service for compute ID %s") % compute['id'])
                continue
            host = service['host']
            capabilities = self.service_states.get(host, None)
            host_state = self.host_state_map.get(host)
            if host_state:
                host_state.update_capabilities(topic, capabilities,
                                               dict(service.iteritems()))
            else:
                host_state = self.host_state_cls(host, topic,
                        capabilities=capabilities,
                        service=dict(service.iteritems()))
                self.host_state_map[host] = host_state
            host_state.update_from_compute_node(compute)

        return self.host_state_map
