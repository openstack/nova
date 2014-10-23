# Copyright (c) 2011 OpenStack Foundation
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

import collections
import UserDict

from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import timeutils

from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.i18n import _, _LI, _LW
from nova.openstack.common import log as logging
from nova.pci import stats as pci_stats
from nova.scheduler import filters
from nova.scheduler import weights
from nova.virt import hardware

host_manager_opts = [
    cfg.MultiStrOpt('scheduler_available_filters',
            default=['nova.scheduler.filters.all_filters'],
            help='Filter classes available to the scheduler which may '
                    'be specified more than once.  An entry of '
                    '"nova.scheduler.filters.all_filters" '
                    'maps to all filters included with nova.'),
    cfg.ListOpt('scheduler_default_filters',
                default=[
                  'RetryFilter',
                  'AvailabilityZoneFilter',
                  'RamFilter',
                  'ComputeFilter',
                  'ComputeCapabilitiesFilter',
                  'ImagePropertiesFilter',
                  'ServerGroupAntiAffinityFilter',
                  'ServerGroupAffinityFilter',
                  ],
                help='Which filter class names to use for filtering hosts '
                      'when not specified in the request.'),
    cfg.ListOpt('scheduler_weight_classes',
                default=['nova.scheduler.weights.all_weighers'],
                help='Which weight class names to use for weighing hosts'),
    ]

CONF = cfg.CONF
CONF.register_opts(host_manager_opts)

LOG = logging.getLogger(__name__)


class ReadOnlyDict(UserDict.IterableUserDict):
    """A read-only dict."""
    def __init__(self, source=None):
        self.data = {}
        self.update(source)

    def __setitem__(self, key, item):
        raise TypeError()

    def __delitem__(self, key):
        raise TypeError()

    def clear(self):
        raise TypeError()

    def pop(self, key, *args):
        raise TypeError()

    def popitem(self):
        raise TypeError()

    def update(self, source=None):
        if source is None:
            return
        elif isinstance(source, UserDict.UserDict):
            self.data = source.data
        elif isinstance(source, type({})):
            self.data = source
        else:
            raise TypeError()


# Representation of a single metric value from a compute node.
MetricItem = collections.namedtuple(
             'MetricItem', ['value', 'timestamp', 'source'])


class HostState(object):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def __init__(self, host, node, compute=None):
        self.host = host
        self.nodename = node

        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.total_usable_ram_mb = 0
        self.total_usable_disk_gb = 0
        self.disk_mb_used = 0
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_total = 0
        self.vcpus_used = 0
        self.numa_topology = None

        # Additional host information from the compute node stats:
        self.num_instances = 0
        self.num_io_ops = 0

        # Other information
        self.host_ip = None
        self.hypervisor_type = None
        self.hypervisor_version = None
        self.hypervisor_hostname = None
        self.cpu_info = None
        self.supported_instances = None

        # Resource oversubscription values for the compute host:
        self.limits = {}

        # Generic metrics from compute nodes
        self.metrics = {}

        self.updated = None
        if compute:
            self.update_from_compute_node(compute)

    def update_service(self, service):
        self.service = ReadOnlyDict(service)

    def _update_metrics_from_compute_node(self, compute):
        # NOTE(llu): The 'or []' is to avoid json decode failure of None
        #            returned from compute.get, because DB schema allows
        #            NULL in the metrics column
        metrics = compute.get('metrics', []) or []
        if metrics:
            metrics = jsonutils.loads(metrics)
        for metric in metrics:
            # 'name', 'value', 'timestamp' and 'source' are all required
            # to be valid keys, just let KeyError happen if any one of
            # them is missing. But we also require 'name' to be True.
            name = metric['name']
            item = MetricItem(value=metric['value'],
                              timestamp=metric['timestamp'],
                              source=metric['source'])
            if name:
                self.metrics[name] = item
            else:
                LOG.warning(_LW("Metric name unknown of %r"), item)

    def update_from_compute_node(self, compute):
        """Update information about a host from its compute_node info."""
        if (self.updated and compute['updated_at']
                and self.updated > compute['updated_at']):
            return
        all_ram_mb = compute['memory_mb']

        # Assume virtual size is all consumed by instances if use qcow2 disk.
        free_gb = compute['free_disk_gb']
        least_gb = compute.get('disk_available_least')
        if least_gb is not None:
            if least_gb > free_gb:
                # can occur when an instance in database is not on host
                LOG.warning(_LW("Host %(hostname)s has more disk space than "
                                "database expected "
                                "(%(physical)sgb > %(database)sgb)"),
                            {'physical': least_gb, 'database': free_gb,
                             'hostname': compute['hypervisor_hostname']})
            free_gb = min(least_gb, free_gb)
        free_disk_mb = free_gb * 1024

        self.disk_mb_used = compute['local_gb_used'] * 1024

        # NOTE(jogo) free_ram_mb can be negative
        self.free_ram_mb = compute['free_ram_mb']
        self.total_usable_ram_mb = all_ram_mb
        self.total_usable_disk_gb = compute['local_gb']
        self.free_disk_mb = free_disk_mb
        self.vcpus_total = compute['vcpus']
        self.vcpus_used = compute['vcpus_used']
        self.updated = compute['updated_at']
        self.numa_topology = compute['numa_topology']
        if 'pci_stats' in compute:
            self.pci_stats = pci_stats.PciDeviceStats(compute['pci_stats'])
        else:
            self.pci_stats = None

        # All virt drivers report host_ip
        self.host_ip = compute['host_ip']
        self.hypervisor_type = compute.get('hypervisor_type')
        self.hypervisor_version = compute.get('hypervisor_version')
        self.hypervisor_hostname = compute.get('hypervisor_hostname')
        self.cpu_info = compute.get('cpu_info')
        if compute.get('supported_instances'):
            self.supported_instances = jsonutils.loads(
                    compute.get('supported_instances'))

        # Don't store stats directly in host_state to make sure these don't
        # overwrite any values, or get overwritten themselves. Store in self so
        # filters can schedule with them.
        stats = compute.get('stats', None) or '{}'
        self.stats = jsonutils.loads(stats)

        # Track number of instances on host
        self.num_instances = int(self.stats.get('num_instances', 0))

        self.num_io_ops = int(self.stats.get('io_workload', 0))

        # update metrics
        self._update_metrics_from_compute_node(compute)

    def consume_from_instance(self, instance):
        """Incrementally update host state from an instance."""
        disk_mb = (instance['root_gb'] + instance['ephemeral_gb']) * 1024
        ram_mb = instance['memory_mb']
        vcpus = instance['vcpus']
        self.free_ram_mb -= ram_mb
        self.free_disk_mb -= disk_mb
        self.vcpus_used += vcpus
        self.updated = timeutils.utcnow()

        # Track number of instances on host
        self.num_instances += 1

        pci_requests = instance.get('pci_requests')
        # NOTE(danms): Instance here is still a dict, which is converted from
        # an object. Thus, it has a .pci_requests field, which gets converted
        # to a primitive early on, and is thus a dict here. Convert this when
        # we get an object all the way to this path.
        if pci_requests and pci_requests['requests'] and self.pci_stats:
            self.pci_stats.apply_requests(pci_requests.requests)

        # Calculate the numa usage
        updated_numa_topology = hardware.get_host_numa_usage_from_instance(
                self, instance)
        self.numa_topology = updated_numa_topology

        vm_state = instance.get('vm_state', vm_states.BUILDING)
        task_state = instance.get('task_state')
        if vm_state == vm_states.BUILDING or task_state in [
                task_states.RESIZE_MIGRATING, task_states.REBUILDING,
                task_states.RESIZE_PREP, task_states.IMAGE_SNAPSHOT,
                task_states.IMAGE_BACKUP, task_states.UNSHELVING,
                task_states.RESCUING]:
            self.num_io_ops += 1

    def __repr__(self):
        return ("(%s, %s) ram:%s disk:%s io_ops:%s instances:%s" %
                (self.host, self.nodename, self.free_ram_mb, self.free_disk_mb,
                 self.num_io_ops, self.num_instances))


class HostManager(object):
    """Base HostManager class."""

    # Can be overridden in a subclass
    def host_state_cls(self, host, node, **kwargs):
        return HostState(host, node, **kwargs)

    def __init__(self):
        self.host_state_map = {}
        self.filter_handler = filters.HostFilterHandler()
        filter_classes = self.filter_handler.get_matching_classes(
                CONF.scheduler_available_filters)
        self.filter_cls_map = dict(
                (cls.__name__, cls) for cls in filter_classes)
        self.filter_obj_map = {}
        self.weight_handler = weights.HostWeightHandler()
        weigher_classes = self.weight_handler.get_matching_classes(
                CONF.scheduler_weight_classes)
        self.weighers = [cls() for cls in weigher_classes]

    def _choose_host_filters(self, filter_cls_names):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if filter_cls_names is None:
            filter_cls_names = CONF.scheduler_default_filters
        if not isinstance(filter_cls_names, (list, tuple)):
            filter_cls_names = [filter_cls_names]

        good_filters = []
        bad_filters = []
        for filter_name in filter_cls_names:
            if filter_name not in self.filter_obj_map:
                if filter_name not in self.filter_cls_map:
                    bad_filters.append(filter_name)
                    continue
                filter_cls = self.filter_cls_map[filter_name]
                self.filter_obj_map[filter_name] = filter_cls()
            good_filters.append(self.filter_obj_map[filter_name])
        if bad_filters:
            msg = ", ".join(bad_filters)
            raise exception.SchedulerHostFilterNotFound(filter_name=msg)
        return good_filters

    def get_filtered_hosts(self, hosts, filter_properties,
            filter_class_names=None, index=0):
        """Filter hosts and return only ones passing all filters."""

        def _strip_ignore_hosts(host_map, hosts_to_ignore):
            ignored_hosts = []
            for host in hosts_to_ignore:
                for (hostname, nodename) in host_map.keys():
                    if host == hostname:
                        del host_map[(hostname, nodename)]
                        ignored_hosts.append(host)
            ignored_hosts_str = ', '.join(ignored_hosts)
            msg = _('Host filter ignoring hosts: %s')
            LOG.audit(msg % ignored_hosts_str)

        def _match_forced_hosts(host_map, hosts_to_force):
            forced_hosts = []
            for (hostname, nodename) in host_map.keys():
                if hostname not in hosts_to_force:
                    del host_map[(hostname, nodename)]
                else:
                    forced_hosts.append(hostname)
            if host_map:
                forced_hosts_str = ', '.join(forced_hosts)
                msg = _('Host filter forcing available hosts to %s')
            else:
                forced_hosts_str = ', '.join(hosts_to_force)
                msg = _("No hosts matched due to not matching "
                        "'force_hosts' value of '%s'")
            LOG.audit(msg % forced_hosts_str)

        def _match_forced_nodes(host_map, nodes_to_force):
            forced_nodes = []
            for (hostname, nodename) in host_map.keys():
                if nodename not in nodes_to_force:
                    del host_map[(hostname, nodename)]
                else:
                    forced_nodes.append(nodename)
            if host_map:
                forced_nodes_str = ', '.join(forced_nodes)
                msg = _('Host filter forcing available nodes to %s')
            else:
                forced_nodes_str = ', '.join(nodes_to_force)
                msg = _("No nodes matched due to not matching "
                        "'force_nodes' value of '%s'")
            LOG.audit(msg % forced_nodes_str)

        filters = self._choose_host_filters(filter_class_names)
        ignore_hosts = filter_properties.get('ignore_hosts', [])
        force_hosts = filter_properties.get('force_hosts', [])
        force_nodes = filter_properties.get('force_nodes', [])

        if ignore_hosts or force_hosts or force_nodes:
            # NOTE(deva): we can't assume "host" is unique because
            #             one host may have many nodes.
            name_to_cls_map = dict([((x.host, x.nodename), x) for x in hosts])
            if ignore_hosts:
                _strip_ignore_hosts(name_to_cls_map, ignore_hosts)
                if not name_to_cls_map:
                    return []
            # NOTE(deva): allow force_hosts and force_nodes independently
            if force_hosts:
                _match_forced_hosts(name_to_cls_map, force_hosts)
            if force_nodes:
                _match_forced_nodes(name_to_cls_map, force_nodes)
            if force_hosts or force_nodes:
                # NOTE(deva): Skip filters when forcing host or node
                if name_to_cls_map:
                    return name_to_cls_map.values()
            hosts = name_to_cls_map.itervalues()

        return self.filter_handler.get_filtered_objects(filters,
                hosts, filter_properties, index)

    def get_weighed_hosts(self, hosts, weight_properties):
        """Weigh the hosts."""
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)

    def get_all_host_states(self, context):
        """Returns a list of HostStates that represents all the hosts
        the HostManager knows about. Also, each of the consumable resources
        in HostState are pre-populated and adjusted based on data in the db.
        """

        # Get resource usage across the available compute nodes:
        compute_nodes = db.compute_node_get_all(context)
        seen_nodes = set()
        for compute in compute_nodes:
            service = compute['service']
            if not service:
                LOG.warning(_LW("No service for compute ID %s"), compute['id'])
                continue
            host = service['host']
            node = compute.get('hypervisor_hostname')
            state_key = (host, node)
            host_state = self.host_state_map.get(state_key)
            if host_state:
                host_state.update_from_compute_node(compute)
            else:
                host_state = self.host_state_cls(host, node, compute=compute)
                self.host_state_map[state_key] = host_state
            host_state.update_service(dict(service.iteritems()))
            seen_nodes.add(state_key)

        # remove compute nodes from host_state_map if they are not active
        dead_nodes = set(self.host_state_map.keys()) - seen_nodes
        for state_key in dead_nodes:
            host, node = state_key
            LOG.info(_LI("Removing dead compute node %(host)s:%(node)s "
                         "from scheduler"), {'host': host, 'node': node})
            del self.host_state_map[state_key]

        return self.host_state_map.itervalues()
