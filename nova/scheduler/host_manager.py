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

from nova.compute import task_states
from nova.compute import vm_states
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

        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities.get(topic, None))
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)
        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.total_usable_disk_gb = 0
        self.disk_mb_used = 0
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_total = 0
        self.vcpus_used = 0
        # Valid vm types on this host: 'pv', 'hvm' or 'all'
        if 'allowed_vm_type' in self.capabilities:
            self.allowed_vm_type = self.capabilities['allowed_vm_type']
        else:
            self.allowed_vm_type = 'all'

        # Additional host information from the compute node stats:
        self.vm_states = {}
        self.task_states = {}
        self.num_instances = 0
        self.num_instances_by_project = {}
        self.num_instances_by_os_type = {}
        self.num_io_ops = 0

        # Resource oversubscription values for the compute host:
        self.limits = {}

    def update_from_compute_node(self, compute):
        """Update information about a host from its compute_node info."""
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

        stats = compute.get('stats', [])
        statmap = self._statmap(stats)

        # Track number of instances on host
        self.num_instances = int(statmap.get('num_instances', 0))

        # Track number of instances by project_id
        project_id_keys = [k for k in statmap.keys() if
                k.startswith("num_proj_")]
        for key in project_id_keys:
            project_id = key[9:]
            self.num_instances_by_project[project_id] = int(statmap[key])

        # Track number of instances in certain vm_states
        vm_state_keys = [k for k in statmap.keys() if k.startswith("num_vm_")]
        for key in vm_state_keys:
            vm_state = key[7:]
            self.vm_states[vm_state] = int(statmap[key])

        # Track number of instances in certain task_states
        task_state_keys = [k for k in statmap.keys() if
                k.startswith("num_task_")]
        for key in task_state_keys:
            task_state = key[9:]
            self.task_states[task_state] = int(statmap[key])

        # Track number of instances by host_type
        os_keys = [k for k in statmap.keys() if k.startswith("num_os_type_")]
        for key in os_keys:
            os = key[12:]
            self.num_instances_by_os_type[os] = int(statmap[key])

        self.num_io_ops = int(statmap.get('io_workload', 0))

    def consume_from_instance(self, instance):
        """Incrementally update host state from an instance"""
        disk_mb = (instance['root_gb'] + instance['ephemeral_gb']) * 1024
        ram_mb = instance['memory_mb']
        vcpus = instance['vcpus']
        self.free_ram_mb -= ram_mb
        self.free_disk_mb -= disk_mb
        self.vcpus_used += vcpus

        # Track number of instances on host
        self.num_instances += 1

        # Track number of instances by project_id
        project_id = instance.get('project_id')
        if project_id not in self.num_instances_by_project:
            self.num_instances_by_project[project_id] = 0
        self.num_instances_by_project[project_id] += 1

        # Track number of instances in certain vm_states
        vm_state = instance.get('vm_state', vm_states.BUILDING)
        if vm_state not in self.vm_states:
            self.vm_states[vm_state] = 0
        self.vm_states[vm_state] += 1

        # Track number of instances in certain task_states
        task_state = instance.get('task_state')
        if task_state not in self.task_states:
            self.task_states[task_state] = 0
        self.task_states[task_state] += 1

        # Track number of instances by host_type
        os_type = instance.get('os_type')
        if os_type not in self.num_instances_by_os_type:
            self.num_instances_by_os_type[os_type] = 0
        self.num_instances_by_os_type[os_type] += 1

        vm_state = instance.get('vm_state', vm_states.BUILDING)
        task_state = instance.get('task_state')
        if vm_state == vm_states.BUILDING or task_state in [
                task_states.RESIZE_MIGRATING, task_states.REBUILDING,
                task_states.RESIZE_PREP, task_states.IMAGE_SNAPSHOT,
                task_states.IMAGE_BACKUP]:
            self.num_io_ops += 1

    def _statmap(self, stats):
        return dict((st['key'], st['value']) for st in stats)

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
        return ("%s ram:%s disk:%s io_ops:%s instances:%s vm_type:%s" %
                (self.host, self.free_ram_mb, self.free_disk_mb,
                 self.num_io_ops, self.num_instances, self.allowed_vm_type))


class HostManager(object):
    """Base HostManager class."""

    # Can be overridden in a subclass
    host_state_cls = HostState

    def __init__(self):
        self.service_states = {}  # { <host> : { <service> : { cap k : v }}}
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

        host_state_map = {}

        # Get resource usage across the available compute nodes:
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

        return host_state_map
