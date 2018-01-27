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
import functools
import time
try:
    from collections import UserDict as IterableUserDict   # Python 3
except ImportError:
    from UserDict import IterableUserDict                  # Python 2


import iso8601
from oslo_log import log as logging
from oslo_utils import timeutils
import six

import nova.conf
from nova import context as context_module
from nova import exception
from nova.i18n import _LI, _LW
from nova import objects
from nova.pci import stats as pci_stats
from nova.scheduler import filters
from nova.scheduler import weights
from nova import utils
from nova.virt import hardware


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)
HOST_INSTANCE_SEMAPHORE = "host_instance"


class ReadOnlyDict(IterableUserDict):
    """A read-only dict."""
    def __init__(self, source=None):
        self.data = {}
        if source:
            self.data.update(source)

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

    def update(self):
        raise TypeError()


@utils.expects_func_args('self', 'spec_obj')
def set_update_time_on_success(function):
    """Set updated time of HostState when consuming succeed."""

    @functools.wraps(function)
    def decorated_function(self, spec_obj):
        return_value = None
        try:
            return_value = function(self, spec_obj)
        except Exception as e:
            # Ignores exception raised from consume_from_request() so that
            # booting instance would fail in the resource claim of compute
            # node, other suitable node may be chosen during scheduling retry.
            LOG.warning(_LW("Selected host: %(host)s failed to consume from "
                            "instance. Error: %(error)s"),
                        {'host': self.host, 'error': e})
        else:
            now = timeutils.utcnow()
            # NOTE(sbauza): Objects are UTC tz-aware by default
            self.updated = now.replace(tzinfo=iso8601.UTC)
        return return_value

    return decorated_function


class HostState(object):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def __init__(self, host, node, cell_uuid):
        self.host = host
        self.nodename = node
        self.uuid = None
        self._lock_name = (host, node)

        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.total_usable_ram_mb = 0
        self.total_usable_disk_gb = 0
        self.disk_mb_used = 0
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_total = 0
        self.vcpus_used = 0
        self.pci_stats = None
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
        self.metrics = None

        # List of aggregates the host belongs to
        self.aggregates = []

        # Instances on this host
        self.instances = {}

        # Allocation ratios for this host
        self.ram_allocation_ratio = None
        self.cpu_allocation_ratio = None
        self.disk_allocation_ratio = None

        # Host cell (v2) membership
        self.cell_uuid = cell_uuid

        self.updated = None

    def update(self, compute=None, service=None, aggregates=None,
            inst_dict=None):
        """Update all information about a host."""

        @utils.synchronized(self._lock_name)
        def _locked_update(self, compute, service, aggregates, inst_dict):
            # Scheduler API is inherently multi-threaded as every incoming RPC
            # message will be dispatched in it's own green thread. So the
            # shared host state should be updated in a consistent way to make
            # sure its data is valid under concurrent write operations.
            if compute is not None:
                LOG.debug("Update host state from compute node: %s", compute)
                self._update_from_compute_node(compute)
            if aggregates is not None:
                LOG.debug("Update host state with aggregates: %s", aggregates)
                self.aggregates = aggregates
            if service is not None:
                LOG.debug("Update host state with service dict: %s", service)
                self.service = ReadOnlyDict(service)
            if inst_dict is not None:
                LOG.debug("Update host state with instances: %s", inst_dict)
                self.instances = inst_dict

        return _locked_update(self, compute, service, aggregates, inst_dict)

    def _update_from_compute_node(self, compute):
        """Update information about a host from a ComputeNode object."""
        # NOTE(jichenjc): if the compute record is just created but not updated
        # some field such as free_disk_gb can be None
        if 'free_disk_gb' not in compute or compute.free_disk_gb is None:
            LOG.debug('Ignoring compute node %s as its usage has not been '
                      'updated yet.', compute.uuid)
            return

        if (self.updated and compute.updated_at
                and self.updated > compute.updated_at):
            return
        all_ram_mb = compute.memory_mb

        self.uuid = compute.uuid

        # Assume virtual size is all consumed by instances if use qcow2 disk.
        free_gb = compute.free_disk_gb
        least_gb = compute.disk_available_least
        if least_gb is not None:
            if least_gb > free_gb:
                # can occur when an instance in database is not on host
                LOG.warning(_LW("Host %(hostname)s has more disk space than "
                                "database expected "
                                "(%(physical)s GB > %(database)s GB)"),
                            {'physical': least_gb, 'database': free_gb,
                             'hostname': compute.hypervisor_hostname})
            free_gb = min(least_gb, free_gb)
        free_disk_mb = free_gb * 1024

        self.disk_mb_used = compute.local_gb_used * 1024

        # NOTE(jogo) free_ram_mb can be negative
        self.free_ram_mb = compute.free_ram_mb
        self.total_usable_ram_mb = all_ram_mb
        self.total_usable_disk_gb = compute.local_gb
        self.free_disk_mb = free_disk_mb
        self.vcpus_total = compute.vcpus
        self.vcpus_used = compute.vcpus_used
        self.updated = compute.updated_at
        self.numa_topology = compute.numa_topology
        self.pci_stats = pci_stats.PciDeviceStats(
            stats=compute.pci_device_pools)

        # All virt drivers report host_ip
        self.host_ip = compute.host_ip
        self.hypervisor_type = compute.hypervisor_type
        self.hypervisor_version = compute.hypervisor_version
        self.hypervisor_hostname = compute.hypervisor_hostname
        self.cpu_info = compute.cpu_info
        if compute.supported_hv_specs:
            self.supported_instances = [spec.to_list() for spec
                                        in compute.supported_hv_specs]
        else:
            self.supported_instances = []

        # Don't store stats directly in host_state to make sure these don't
        # overwrite any values, or get overwritten themselves. Store in self so
        # filters can schedule with them.
        self.stats = compute.stats or {}

        # Track number of instances on host
        self.num_instances = int(self.stats.get('num_instances', 0))

        self.num_io_ops = int(self.stats.get('io_workload', 0))

        # update metrics
        self.metrics = objects.MonitorMetricList.from_json(compute.metrics)

        # update allocation ratios given by the ComputeNode object
        self.cpu_allocation_ratio = compute.cpu_allocation_ratio
        self.ram_allocation_ratio = compute.ram_allocation_ratio
        self.disk_allocation_ratio = compute.disk_allocation_ratio

    def consume_from_request(self, spec_obj):
        """Incrementally update host state from a RequestSpec object."""

        @utils.synchronized(self._lock_name)
        @set_update_time_on_success
        def _locked(self, spec_obj):
            # Scheduler API is inherently multi-threaded as every incoming RPC
            # message will be dispatched in its own green thread. So the
            # shared host state should be consumed in a consistent way to make
            # sure its data is valid under concurrent write operations.
            self._locked_consume_from_request(spec_obj)

        return _locked(self, spec_obj)

    def _locked_consume_from_request(self, spec_obj):
        disk_mb = (spec_obj.root_gb +
                   spec_obj.ephemeral_gb) * 1024
        ram_mb = spec_obj.memory_mb
        vcpus = spec_obj.vcpus
        self.free_ram_mb -= ram_mb
        self.free_disk_mb -= disk_mb
        self.vcpus_used += vcpus

        # Track number of instances on host
        self.num_instances += 1

        pci_requests = spec_obj.pci_requests
        if pci_requests and self.pci_stats:
            pci_requests = pci_requests.requests
        else:
            pci_requests = None

        # Calculate the numa usage
        host_numa_topology, _fmt = hardware.host_topology_and_format_from_host(
                                self)
        instance_numa_topology = spec_obj.numa_topology
        if host_numa_topology and instance_numa_topology:
            spec_obj.numa_topology = hardware.numa_fit_instance_to_host(
                host_numa_topology, instance_numa_topology,
                limits=self.limits.get('numa_topology'),
                pci_requests=pci_requests, pci_stats=self.pci_stats)
        if pci_requests:
            instance_cells = None
            if spec_obj.numa_topology:
                instance_cells = spec_obj.numa_topology.cells
            self.pci_stats.apply_requests(pci_requests, instance_cells)

        # NOTE(sbauza): Yeah, that's crap. We should get rid of all of those
        # NUMA helpers because now we're 100% sure that spec_obj.numa_topology
        # is an InstanceNUMATopology object. Unfortunately, since
        # HostState.host_numa_topology is still limbo between an NUMATopology
        # object (when updated by consume_from_request), a ComputeNode object
        # (when updated by update_from_compute_node), we need to keep the call
        # to get_host_numa_usage_from_instance until it's fixed (and use a
        # temporary orphaned Instance object as a proxy)
        instance = objects.Instance(numa_topology=spec_obj.numa_topology)

        self.numa_topology = hardware.get_host_numa_usage_from_instance(
                self, instance)

        # NOTE(sbauza): By considering all cases when the scheduler is called
        # and when consume_from_request() is run, we can safely say that there
        # is always an IO operation because we want to move the instance
        self.num_io_ops += 1

    def __repr__(self):
        return ("(%(host)s, %(node)s) ram: %(free_ram)sMB "
                "disk: %(free_disk)sMB io_ops: %(num_io_ops)s "
                "instances: %(num_instances)s" %
                {'host': self.host, 'node': self.nodename,
                 'free_ram': self.free_ram_mb, 'free_disk': self.free_disk_mb,
                 'num_io_ops': self.num_io_ops,
                 'num_instances': self.num_instances})


class HostManager(object):
    """Base HostManager class."""

    # Can be overridden in a subclass
    def host_state_cls(self, host, node, cell, **kwargs):
        return HostState(host, node, cell)

    def __init__(self):
        self.cells = None
        self.filter_handler = filters.HostFilterHandler()
        filter_classes = self.filter_handler.get_matching_classes(
                CONF.filter_scheduler.available_filters)
        self.filter_cls_map = {cls.__name__: cls for cls in filter_classes}
        self.filter_obj_map = {}
        self.enabled_filters = self._choose_host_filters(self._load_filters())
        self.weight_handler = weights.HostWeightHandler()
        weigher_classes = self.weight_handler.get_matching_classes(
                CONF.filter_scheduler.weight_classes)
        self.weighers = [cls() for cls in weigher_classes]
        # Dict of aggregates keyed by their ID
        self.aggs_by_id = {}
        # Dict of set of aggregate IDs keyed by the name of the host belonging
        # to those aggregates
        self.host_aggregates_map = collections.defaultdict(set)
        self._init_aggregates()
        self.track_instance_changes = (
                CONF.filter_scheduler.track_instance_changes)
        # Dict of instances and status, keyed by host
        self._instance_info = {}
        if self.track_instance_changes:
            self._init_instance_info()

    def _load_filters(self):
        return CONF.filter_scheduler.enabled_filters

    def _init_aggregates(self):
        elevated = context_module.get_admin_context()
        aggs = objects.AggregateList.get_all(elevated)
        for agg in aggs:
            self.aggs_by_id[agg.id] = agg
            for host in agg.hosts:
                self.host_aggregates_map[host].add(agg.id)

    def update_aggregates(self, aggregates):
        """Updates internal HostManager information about aggregates."""
        if isinstance(aggregates, (list, objects.AggregateList)):
            for agg in aggregates:
                self._update_aggregate(agg)
        else:
            self._update_aggregate(aggregates)

    def _update_aggregate(self, aggregate):
        self.aggs_by_id[aggregate.id] = aggregate
        for host in aggregate.hosts:
            self.host_aggregates_map[host].add(aggregate.id)
        # Refreshing the mapping dict to remove all hosts that are no longer
        # part of the aggregate
        for host in self.host_aggregates_map:
            if (aggregate.id in self.host_aggregates_map[host]
                    and host not in aggregate.hosts):
                self.host_aggregates_map[host].remove(aggregate.id)

    def delete_aggregate(self, aggregate):
        """Deletes internal HostManager information about a specific aggregate.
        """
        if aggregate.id in self.aggs_by_id:
            del self.aggs_by_id[aggregate.id]
        for host in self.host_aggregates_map:
            if aggregate.id in self.host_aggregates_map[host]:
                self.host_aggregates_map[host].remove(aggregate.id)

    def _init_instance_info(self, computes_by_cell=None):
        """Creates the initial view of instances for all hosts.

        As this initial population of instance information may take some time,
        we don't wish to block the scheduler's startup while this completes.
        The async method allows us to simply mock out the _init_instance_info()
        method in tests.

        :param compute_nodes: a list of nodes to populate instances info for
        if is None, compute_nodes will be looked up in database
        """

        def _async_init_instance_info(computes_by_cell):
            context = context_module.RequestContext()
            self._load_cells(context)
            LOG.debug("START:_async_init_instance_info")
            self._instance_info = {}

            count = 0
            if not computes_by_cell:
                computes_by_cell = {}
                for cell in self.cells:
                    with context_module.target_cell(context, cell) as cctxt:
                        cell_cns = objects.ComputeNodeList.get_all(
                            cctxt).objects
                        computes_by_cell[cell] = cell_cns
                        count += len(cell_cns)

            LOG.debug("Total number of compute nodes: %s", count)

            for cell, compute_nodes in computes_by_cell.items():
                # Break the queries into batches of 10 to reduce the total
                # number of calls to the DB.
                batch_size = 10
                start_node = 0
                end_node = batch_size
                while start_node <= len(compute_nodes):
                    curr_nodes = compute_nodes[start_node:end_node]
                    start_node += batch_size
                    end_node += batch_size
                    filters = {"host": [curr_node.host
                                        for curr_node in curr_nodes],
                               "deleted": False}
                    with context_module.target_cell(context, cell) as cctxt:
                        result = objects.InstanceList.get_by_filters(
                            cctxt.elevated(), filters)
                    instances = result.objects
                    LOG.debug("Adding %s instances for hosts %s-%s",
                              len(instances), start_node, end_node)
                    for instance in instances:
                        host = instance.host
                        if host not in self._instance_info:
                            self._instance_info[host] = {"instances": {},
                                                         "updated": False}
                        inst_dict = self._instance_info[host]
                        inst_dict["instances"][instance.uuid] = instance
                    # Call sleep() to cooperatively yield
                    time.sleep(0)
                LOG.debug("END:_async_init_instance_info")

        # Run this async so that we don't block the scheduler start-up
        utils.spawn_n(_async_init_instance_info, computes_by_cell)

    def _choose_host_filters(self, filter_cls_names):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
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

    def get_filtered_hosts(self, hosts, spec_obj, index=0):
        """Filter hosts and return only ones passing all filters."""

        def _strip_ignore_hosts(host_map, hosts_to_ignore):
            ignored_hosts = []
            for host in hosts_to_ignore:
                for (hostname, nodename) in list(host_map.keys()):
                    if host.lower() == hostname.lower():
                        del host_map[(hostname, nodename)]
                        ignored_hosts.append(host)
            ignored_hosts_str = ', '.join(ignored_hosts)
            LOG.info(_LI('Host filter ignoring hosts: %s'), ignored_hosts_str)

        def _match_forced_hosts(host_map, hosts_to_force):
            forced_hosts = []
            lowered_hosts_to_force = [host.lower() for host in hosts_to_force]
            for (hostname, nodename) in list(host_map.keys()):
                if hostname.lower() not in lowered_hosts_to_force:
                    del host_map[(hostname, nodename)]
                else:
                    forced_hosts.append(hostname)
            if host_map:
                forced_hosts_str = ', '.join(forced_hosts)
                msg = _LI('Host filter forcing available hosts to %s')
            else:
                forced_hosts_str = ', '.join(hosts_to_force)
                msg = _LI("No hosts matched due to not matching "
                          "'force_hosts' value of '%s'")
            LOG.info(msg, forced_hosts_str)

        def _match_forced_nodes(host_map, nodes_to_force):
            forced_nodes = []
            for (hostname, nodename) in list(host_map.keys()):
                if nodename not in nodes_to_force:
                    del host_map[(hostname, nodename)]
                else:
                    forced_nodes.append(nodename)
            if host_map:
                forced_nodes_str = ', '.join(forced_nodes)
                msg = _LI('Host filter forcing available nodes to %s')
            else:
                forced_nodes_str = ', '.join(nodes_to_force)
                msg = _LI("No nodes matched due to not matching "
                          "'force_nodes' value of '%s'")
            LOG.info(msg, forced_nodes_str)

        def _get_hosts_matching_request(hosts, requested_destination):
            (host, node) = (requested_destination.host,
                            requested_destination.node)
            requested_nodes = [x for x in hosts
                               if x.host == host and x.nodename == node]
            if requested_nodes:
                LOG.info(_LI('Host filter only checking host %(host)s and '
                             'node %(node)s'), {'host': host, 'node': node})
            else:
                # NOTE(sbauza): The API level should prevent the user from
                # providing a wrong destination but let's make sure a wrong
                # destination doesn't trample the scheduler still.
                LOG.info(_LI('No hosts matched due to not matching requested '
                             'destination (%(host)s, %(node)s)'),
                         {'host': host, 'node': node})
            return iter(requested_nodes)

        ignore_hosts = spec_obj.ignore_hosts or []
        force_hosts = spec_obj.force_hosts or []
        force_nodes = spec_obj.force_nodes or []
        requested_node = spec_obj.requested_destination

        if requested_node is not None and 'host' in requested_node:
            # NOTE(sbauza): Reduce a potentially long set of hosts as much as
            # possible to any requested destination nodes before passing the
            # list to the filters
            hosts = _get_hosts_matching_request(hosts, requested_node)
        if ignore_hosts or force_hosts or force_nodes:
            # NOTE(deva): we can't assume "host" is unique because
            #             one host may have many nodes.
            name_to_cls_map = {(x.host, x.nodename): x for x in hosts}
            if ignore_hosts:
                _strip_ignore_hosts(name_to_cls_map, ignore_hosts)
                if not name_to_cls_map:
                    return []
            # NOTE(deva): allow force_hosts and force_nodes independently
            if force_hosts:
                _match_forced_hosts(name_to_cls_map, force_hosts)
            if force_nodes:
                _match_forced_nodes(name_to_cls_map, force_nodes)
            check_type = ('scheduler_hints' in spec_obj and
                          spec_obj.scheduler_hints.get('_nova_check_type'))
            if not check_type and (force_hosts or force_nodes):
                # NOTE(deva,dansmith): Skip filters when forcing host or node
                # unless we've declared the internal check type flag, in which
                # case we're asking for a specific host and for filtering to
                # be done.
                if name_to_cls_map:
                    return name_to_cls_map.values()
                else:
                    return []
            hosts = six.itervalues(name_to_cls_map)

        return self.filter_handler.get_filtered_objects(self.enabled_filters,
                hosts, spec_obj, index)

    def get_weighed_hosts(self, hosts, spec_obj):
        """Weigh the hosts."""
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, spec_obj)

    def _get_computes_for_cells(self, context, cells, compute_uuids=None):
        """Get a tuple of compute node and service information.

        :param context: request context
        :param cells: list of CellMapping objects
        :param compute_uuids: list of ComputeNode UUIDs. If this is None, all
            compute nodes from each specified cell will be returned, otherwise
            only the ComputeNode objects with a UUID in the list of UUIDs in
            any given cell is returned. If this is an empty list, the returned
            compute_nodes tuple item will be an empty dict.

        Returns a tuple (compute_nodes, services) where:
         - compute_nodes is cell-uuid keyed dict of compute node lists
         - services is a dict of services indexed by hostname
        """

        compute_nodes = collections.defaultdict(list)
        services = {}
        for cell in cells:
            LOG.debug('Getting compute nodes and services for cell %(cell)s',
                      {'cell': cell.identity})
            with context_module.target_cell(context, cell) as cctxt:
                if compute_uuids is None:
                    compute_nodes[cell.uuid].extend(
                        objects.ComputeNodeList.get_all(cctxt))
                else:
                    compute_nodes[cell.uuid].extend(
                        objects.ComputeNodeList.get_all_by_uuids(
                            cctxt, compute_uuids))
                services.update(
                    {service.host: service
                     for service in objects.ServiceList.get_by_binary(
                             cctxt, 'nova-compute',
                             include_disabled=True)})
        return compute_nodes, services

    def _load_cells(self, context):
        if not self.cells:
            # NOTE(danms): global list of cells cached forever right now
            self.cells = objects.CellMappingList.get_all(context)
            LOG.debug('Found %(count)i cells: %(cells)s',
                      {'count': len(self.cells),
                       'cells': ', '.join([c.uuid for c in self.cells])})

    def get_host_states_by_uuids(self, context, compute_uuids, spec_obj):

        self._load_cells(context)
        if (spec_obj and 'requested_destination' in spec_obj and
                spec_obj.requested_destination and
                'cell' in spec_obj.requested_destination):
            only_cell = spec_obj.requested_destination.cell
        else:
            only_cell = None

        if only_cell:
            cells = [only_cell]
        else:
            cells = self.cells

        compute_nodes, services = self._get_computes_for_cells(
            context, cells, compute_uuids=compute_uuids)
        return self._get_host_states(context, compute_nodes, services)

    def get_all_host_states(self, context):
        """Returns a generator of HostStates that represents all the hosts
        the HostManager knows about. Also, each of the consumable resources
        in HostState are pre-populated and adjusted based on data in the db.
        """
        self._load_cells(context)
        compute_nodes, services = self._get_computes_for_cells(context,
                                                               self.cells)
        return self._get_host_states(context, compute_nodes, services)

    def _get_host_states(self, context, compute_nodes, services):
        """Returns a generator over HostStates given a list of computes.

        Also updates the HostStates internal mapping for the HostManager.
        """
        # Get resource usage across the available compute nodes:
        host_state_map = {}
        seen_nodes = set()
        for cell_uuid, computes in compute_nodes.items():
            for compute in computes:
                service = services.get(compute.host)

                if not service:
                    LOG.warning(_LW(
                        "No compute service record found for host %(host)s"),
                        {'host': compute.host})
                    continue
                host = compute.host
                node = compute.hypervisor_hostname
                state_key = (host, node)
                host_state = host_state_map.get(state_key)
                if not host_state:
                    host_state = self.host_state_cls(host, node,
                                                     cell_uuid,
                                                     compute=compute)
                    host_state_map[state_key] = host_state
                # We force to update the aggregates info each time a
                # new request comes in, because some changes on the
                # aggregates could have been happening after setting
                # this field for the first time
                host_state.update(compute,
                                  dict(service),
                                  self._get_aggregates_info(host),
                                  self._get_instance_info(context, compute))

                seen_nodes.add(state_key)

        return (host_state_map[host] for host in seen_nodes)

    def _get_aggregates_info(self, host):
        return [self.aggs_by_id[agg_id] for agg_id in
                self.host_aggregates_map[host]]

    def _get_instances_by_host(self, context, host_name):
        try:
            hm = objects.HostMapping.get_by_host(context, host_name)
        except exception.HostMappingNotFound:
            # It's possible to hit this when the compute service first starts
            # up and casts to update_instance_info with an empty list but
            # before the host is mapped in the API database.
            LOG.info('Host mapping not found for host %s. Not tracking '
                     'instance info for this host.', host_name)
            return {}
        with context_module.target_cell(context, hm.cell_mapping) as cctxt:
            inst_list = objects.InstanceList.get_by_host(cctxt, host_name)
            return {inst.uuid: inst for inst in inst_list}

    def _get_instance_info(self, context, compute):
        """Gets the host instance info from the compute host.

        Some older compute nodes may not be sending instance change updates to
        the Scheduler; other sites may disable this feature for performance
        reasons. In either of these cases, there will either be no information
        for the host, or the 'updated' value for that host dict will be False.
        In those cases, we need to grab the current InstanceList instead of
        relying on the version in _instance_info.
        """
        host_name = compute.host
        host_info = self._instance_info.get(host_name)
        if host_info and host_info.get("updated"):
            inst_dict = host_info["instances"]
        else:
            # Host is running old version, or updates aren't flowing.
            inst_dict = self._get_instances_by_host(context, host_name)
        return inst_dict

    def _recreate_instance_info(self, context, host_name):
        """Get the InstanceList for the specified host, and store it in the
        _instance_info dict.
        """
        inst_dict = self._get_instances_by_host(context, host_name)
        host_info = self._instance_info[host_name] = {}
        host_info["instances"] = inst_dict
        host_info["updated"] = False

    @utils.synchronized(HOST_INSTANCE_SEMAPHORE)
    def update_instance_info(self, context, host_name, instance_info):
        """Receives an InstanceList object from a compute node.

        This method receives information from a compute node when it starts up,
        or when its instances have changed, and updates its view of hosts and
        instances with it.
        """
        host_info = self._instance_info.get(host_name)
        if host_info:
            inst_dict = host_info.get("instances")
            for instance in instance_info.objects:
                # Overwrite the entry (if any) with the new info.
                inst_dict[instance.uuid] = instance
            host_info["updated"] = True
        else:
            instances = instance_info.objects
            if len(instances) > 1:
                # This is a host sending its full instance list, so use it.
                host_info = self._instance_info[host_name] = {}
                host_info["instances"] = {instance.uuid: instance
                                          for instance in instances}
                host_info["updated"] = True
            else:
                self._recreate_instance_info(context, host_name)
                LOG.info(_LI("Received an update from an unknown host '%s'. "
                             "Re-created its InstanceList."), host_name)

    @utils.synchronized(HOST_INSTANCE_SEMAPHORE)
    def delete_instance_info(self, context, host_name, instance_uuid):
        """Receives the UUID from a compute node when one of its instances is
        terminated.

        The instance in the local view of the host's instances is removed.
        """
        host_info = self._instance_info.get(host_name)
        if host_info:
            inst_dict = host_info["instances"]
            # Remove the existing Instance object, if any
            inst_dict.pop(instance_uuid, None)
            host_info["updated"] = True
        else:
            self._recreate_instance_info(context, host_name)
            LOG.info(_LI("Received a delete update from an unknown host '%s'. "
                         "Re-created its InstanceList."), host_name)

    @utils.synchronized(HOST_INSTANCE_SEMAPHORE)
    def sync_instance_info(self, context, host_name, instance_uuids):
        """Receives the uuids of the instances on a host.

        This method is periodically called by the compute nodes, which send a
        list of all the UUID values for the instances on that node. This is
        used by the scheduler's HostManager to detect when its view of the
        compute node's instances is out of sync.
        """
        host_info = self._instance_info.get(host_name)
        if host_info:
            local_set = set(host_info["instances"].keys())
            compute_set = set(instance_uuids)
            if not local_set == compute_set:
                self._recreate_instance_info(context, host_name)
                LOG.info(_LI("The instance sync for host '%s' did not match. "
                             "Re-created its InstanceList."), host_name)
                return
            host_info["updated"] = True
            LOG.info(_LI("Successfully synced instances from host '%s'."),
                     host_name)
        else:
            self._recreate_instance_info(context, host_name)
            LOG.info(_LI("Received a sync request from an unknown host '%s'. "
                         "Re-created its InstanceList."), host_name)
