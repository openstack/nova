# Copyright (c) 2012 OpenStack Foundation
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
Track resources like memory and disk for a compute host.  Provides the
scheduler with useful information about availability through the ComputeNode
model.
"""
import collections
import copy
import retrying

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.compute import claims
from nova.compute import monitors
from nova.compute import stats as compute_stats
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova.objects import migration as migration_obj
from nova.pci import manager as pci_manager
from nova.pci import request as pci_request
from nova import rc_fields as fields
from nova import rpc
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import utils
from nova.virt import hardware

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)
COMPUTE_RESOURCE_SEMAPHORE = "compute_resources"


def _instance_in_resize_state(instance):
    """Returns True if the instance is in one of the resizing states.

    :param instance: `nova.objects.Instance` object
    """
    vm = instance.vm_state
    task = instance.task_state

    if vm == vm_states.RESIZED:
        return True

    if (vm in [vm_states.ACTIVE, vm_states.STOPPED]
            and task in (
                task_states.resizing_states + task_states.rebuild_states)):
        return True

    return False


def _is_trackable_migration(migration):
    # Only look at resize/migrate migration and evacuation records
    # NOTE(danms): RT should probably examine live migration
    # records as well and do something smart. However, ignore
    # those for now to avoid them being included in below calculations.
    return migration.migration_type in ('resize', 'migration',
                                        'evacuation')


def _normalize_inventory_from_cn_obj(inv_data, cn):
    """Helper function that injects various information from a compute node
    object into the inventory dict returned from the virt driver's
    get_inventory() method. This function allows us to marry information like
    *_allocation_ratio and reserved memory amounts that are in the
    compute_nodes DB table and that the virt driver doesn't know about with the
    information the virt driver *does* know about.

    Note that if the supplied inv_data contains allocation_ratio, reserved or
    other fields, we DO NOT override the value with that of the compute node.
    This is to ensure that the virt driver is the single source of truth
    regarding inventory information. For instance, the Ironic virt driver will
    always return a very specific inventory with allocation_ratios pinned to
    1.0.

    :param inv_data: Dict, keyed by resource class, of inventory information
                     returned from virt driver's get_inventory() method
    :param compute_node: `objects.ComputeNode` describing the compute node
    """
    if fields.ResourceClass.VCPU in inv_data:
        cpu_inv = inv_data[fields.ResourceClass.VCPU]
        if 'allocation_ratio' not in cpu_inv:
            cpu_inv['allocation_ratio'] = cn.cpu_allocation_ratio
        if 'reserved' not in cpu_inv:
            cpu_inv['reserved'] = CONF.reserved_host_cpus

    if fields.ResourceClass.MEMORY_MB in inv_data:
        mem_inv = inv_data[fields.ResourceClass.MEMORY_MB]
        if 'allocation_ratio' not in mem_inv:
            mem_inv['allocation_ratio'] = cn.ram_allocation_ratio
        if 'reserved' not in mem_inv:
            mem_inv['reserved'] = CONF.reserved_host_memory_mb

    if fields.ResourceClass.DISK_GB in inv_data:
        disk_inv = inv_data[fields.ResourceClass.DISK_GB]
        if 'allocation_ratio' not in disk_inv:
            disk_inv['allocation_ratio'] = cn.disk_allocation_ratio
        if 'reserved' not in disk_inv:
            # TODO(johngarbutt) We should either move to reserved_host_disk_gb
            # or start tracking DISK_MB.
            reserved_mb = CONF.reserved_host_disk_mb
            reserved_gb = compute_utils.convert_mb_to_ceil_gb(reserved_mb)
            disk_inv['reserved'] = reserved_gb


class ResourceTracker(object):
    """Compute helper class for keeping track of resource usage as instances
    are built and destroyed.
    """

    def __init__(self, host, driver):
        self.host = host
        self.driver = driver
        self.pci_tracker = None
        # Dict of objects.ComputeNode objects, keyed by nodename
        self.compute_nodes = {}
        # Dict of Stats objects, keyed by nodename
        self.stats = collections.defaultdict(compute_stats.Stats)
        self.tracked_instances = {}
        self.tracked_migrations = {}
        self.is_bfv = {}  # dict, keyed by instance uuid, to is_bfv boolean
        monitor_handler = monitors.MonitorHandler(self)
        self.monitors = monitor_handler.monitors
        self.old_resources = collections.defaultdict(objects.ComputeNode)
        self.scheduler_client = scheduler_client.SchedulerClient()
        self.reportclient = self.scheduler_client.reportclient
        self.ram_allocation_ratio = CONF.ram_allocation_ratio
        self.cpu_allocation_ratio = CONF.cpu_allocation_ratio
        self.disk_allocation_ratio = CONF.disk_allocation_ratio

    def get_node_uuid(self, nodename):
        try:
            return self.compute_nodes[nodename].uuid
        except KeyError:
            raise exception.ComputeHostNotFound(host=nodename)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def instance_claim(self, context, instance, nodename, limits=None):
        """Indicate that some resources are needed for an upcoming compute
        instance build operation.

        This should be called before the compute node is about to perform
        an instance build operation that will consume additional resources.

        :param context: security context
        :param instance: instance to reserve resources for.
        :type instance: nova.objects.instance.Instance object
        :param nodename: The Ironic nodename selected by the scheduler
        :param limits: Dict of oversubscription limits for memory, disk,
                       and CPUs.
        :returns: A Claim ticket representing the reserved resources.  It can
                  be used to revert the resource usage if an error occurs
                  during the instance build.
        """
        if self.disabled(nodename):
            # instance_claim() was called before update_available_resource()
            # (which ensures that a compute node exists for nodename). We
            # shouldn't get here but in case we do, just set the instance's
            # host and nodename attribute (probably incorrect) and return a
            # NoopClaim.
            # TODO(jaypipes): Remove all the disabled junk from the resource
            # tracker. Servicegroup API-level active-checking belongs in the
            # nova-compute manager.
            self._set_instance_host_and_node(instance, nodename)
            return claims.NopClaim()

        # sanity checks:
        if instance.host:
            LOG.warning("Host field should not be set on the instance "
                        "until resources have been claimed.",
                        instance=instance)

        if instance.node:
            LOG.warning("Node field should not be set on the instance "
                        "until resources have been claimed.",
                        instance=instance)

        # get the overhead required to build this instance:
        overhead = self.driver.estimate_instance_overhead(instance)
        LOG.debug("Memory overhead for %(flavor)d MB instance; %(overhead)d "
                  "MB", {'flavor': instance.flavor.memory_mb,
                         'overhead': overhead['memory_mb']})
        LOG.debug("Disk overhead for %(flavor)d GB instance; %(overhead)d "
                  "GB", {'flavor': instance.flavor.root_gb,
                         'overhead': overhead.get('disk_gb', 0)})
        LOG.debug("CPU overhead for %(flavor)d vCPUs instance; %(overhead)d "
                  "vCPU(s)", {'flavor': instance.flavor.vcpus,
                              'overhead': overhead.get('vcpus', 0)})

        cn = self.compute_nodes[nodename]
        pci_requests = objects.InstancePCIRequests.get_by_instance_uuid(
            context, instance.uuid)
        claim = claims.Claim(context, instance, nodename, self, cn,
                             pci_requests, overhead=overhead, limits=limits)

        # self._set_instance_host_and_node() will save instance to the DB
        # so set instance.numa_topology first.  We need to make sure
        # that numa_topology is saved while under COMPUTE_RESOURCE_SEMAPHORE
        # so that the resource audit knows about any cpus we've pinned.
        instance_numa_topology = claim.claimed_numa_topology
        instance.numa_topology = instance_numa_topology
        self._set_instance_host_and_node(instance, nodename)

        if self.pci_tracker:
            # NOTE(jaypipes): ComputeNode.pci_device_pools is set below
            # in _update_usage_from_instance().
            self.pci_tracker.claim_instance(context, pci_requests,
                                            instance_numa_topology)

        # Mark resources in-use and update stats
        self._update_usage_from_instance(context, instance, nodename)

        elevated = context.elevated()
        # persist changes to the compute node:
        self._update(elevated, cn)

        return claim

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def rebuild_claim(self, context, instance, nodename, limits=None,
                      image_meta=None, migration=None):
        """Create a claim for a rebuild operation."""
        instance_type = instance.flavor
        return self._move_claim(context, instance, instance_type, nodename,
                                migration, move_type='evacuation',
                                limits=limits, image_meta=image_meta)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def resize_claim(self, context, instance, instance_type, nodename,
                     migration, image_meta=None, limits=None):
        """Create a claim for a resize or cold-migration move."""
        return self._move_claim(context, instance, instance_type, nodename,
                                migration, image_meta=image_meta,
                                limits=limits)

    def _move_claim(self, context, instance, new_instance_type, nodename,
                    migration, move_type=None, image_meta=None, limits=None):
        """Indicate that resources are needed for a move to this host.

        Move can be either a migrate/resize, live-migrate or an
        evacuate/rebuild operation.

        :param context: security context
        :param instance: instance object to reserve resources for
        :param new_instance_type: new instance_type being resized to
        :param nodename: The Ironic nodename selected by the scheduler
        :param image_meta: instance image metadata
        :param move_type: move type - can be one of 'migration', 'resize',
                         'live-migration', 'evacuate'
        :param limits: Dict of oversubscription limits for memory, disk,
        and CPUs
        :param migration: A migration object if one was already created
                          elsewhere for this operation (otherwise None)
        :returns: A Claim ticket representing the reserved resources.  This
        should be turned into finalize  a resource claim or free
        resources after the compute operation is finished.
        """
        image_meta = image_meta or {}
        if migration:
            self._claim_existing_migration(migration, nodename)
        else:
            migration = self._create_migration(context, instance,
                                               new_instance_type,
                                               nodename, move_type)

        if self.disabled(nodename):
            # compute_driver doesn't support resource tracking, just
            # generate the migration record and continue the resize:
            return claims.NopClaim(migration=migration)

        # get memory overhead required to build this instance:
        overhead = self.driver.estimate_instance_overhead(new_instance_type)
        LOG.debug("Memory overhead for %(flavor)d MB instance; %(overhead)d "
                  "MB", {'flavor': new_instance_type.memory_mb,
                          'overhead': overhead['memory_mb']})
        LOG.debug("Disk overhead for %(flavor)d GB instance; %(overhead)d "
                  "GB", {'flavor': instance.flavor.root_gb,
                         'overhead': overhead.get('disk_gb', 0)})
        LOG.debug("CPU overhead for %(flavor)d vCPUs instance; %(overhead)d "
                  "vCPU(s)", {'flavor': instance.flavor.vcpus,
                              'overhead': overhead.get('vcpus', 0)})

        cn = self.compute_nodes[nodename]

        # TODO(moshele): we are recreating the pci requests even if
        # there was no change on resize. This will cause allocating
        # the old/new pci device in the resize phase. In the future
        # we would like to optimise this.
        new_pci_requests = pci_request.get_pci_requests_from_flavor(
            new_instance_type)
        new_pci_requests.instance_uuid = instance.uuid
        # PCI requests come from two sources: instance flavor and
        # SR-IOV ports. SR-IOV ports pci_request don't have an alias_name.
        # On resize merge the SR-IOV ports pci_requests with the new
        # instance flavor pci_requests.
        if instance.pci_requests:
            for request in instance.pci_requests.requests:
                if request.alias_name is None:
                    new_pci_requests.requests.append(request)
        claim = claims.MoveClaim(context, instance, nodename,
                                 new_instance_type, image_meta, self, cn,
                                 new_pci_requests, overhead=overhead,
                                 limits=limits)

        claim.migration = migration
        claimed_pci_devices_objs = []
        if self.pci_tracker:
            # NOTE(jaypipes): ComputeNode.pci_device_pools is set below
            # in _update_usage_from_instance().
            claimed_pci_devices_objs = self.pci_tracker.claim_instance(
                    context, new_pci_requests, claim.claimed_numa_topology)
        claimed_pci_devices = objects.PciDeviceList(
                objects=claimed_pci_devices_objs)

        # TODO(jaypipes): Move claimed_numa_topology out of the Claim's
        # constructor flow so the Claim constructor only tests whether
        # resources can be claimed, not consume the resources directly.
        mig_context = objects.MigrationContext(
            context=context, instance_uuid=instance.uuid,
            migration_id=migration.id,
            old_numa_topology=instance.numa_topology,
            new_numa_topology=claim.claimed_numa_topology,
            old_pci_devices=instance.pci_devices,
            new_pci_devices=claimed_pci_devices,
            old_pci_requests=instance.pci_requests,
            new_pci_requests=new_pci_requests)
        instance.migration_context = mig_context
        instance.save()

        # Mark the resources in-use for the resize landing on this
        # compute host:
        self._update_usage_from_migration(context, instance, migration,
                                          nodename)
        elevated = context.elevated()
        self._update(elevated, cn)

        return claim

    def _create_migration(self, context, instance, new_instance_type,
                          nodename, move_type=None):
        """Create a migration record for the upcoming resize.  This should
        be done while the COMPUTE_RESOURCES_SEMAPHORE is held so the resource
        claim will not be lost if the audit process starts.
        """
        migration = objects.Migration(context=context.elevated())
        migration.dest_compute = self.host
        migration.dest_node = nodename
        migration.dest_host = self.driver.get_host_ip_addr()
        migration.old_instance_type_id = instance.flavor.id
        migration.new_instance_type_id = new_instance_type.id
        migration.status = 'pre-migrating'
        migration.instance_uuid = instance.uuid
        migration.source_compute = instance.host
        migration.source_node = instance.node
        if move_type:
            migration.migration_type = move_type
        else:
            migration.migration_type = migration_obj.determine_migration_type(
                migration)
        migration.create()
        return migration

    def _claim_existing_migration(self, migration, nodename):
        """Make an existing migration record count for resource tracking.

        If a migration record was created already before the request made
        it to this compute host, only set up the migration so it's included in
        resource tracking. This should be done while the
        COMPUTE_RESOURCES_SEMAPHORE is held.
        """
        migration.dest_compute = self.host
        migration.dest_node = nodename
        migration.dest_host = self.driver.get_host_ip_addr()
        migration.status = 'pre-migrating'
        migration.save()

    def _set_instance_host_and_node(self, instance, nodename):
        """Tag the instance as belonging to this host.  This should be done
        while the COMPUTE_RESOURCES_SEMAPHORE is held so the resource claim
        will not be lost if the audit process starts.
        """
        instance.host = self.host
        instance.launched_on = self.host
        instance.node = nodename
        instance.save()

    def _unset_instance_host_and_node(self, instance):
        """Untag the instance so it no longer belongs to the host.

        This should be done while the COMPUTE_RESOURCES_SEMAPHORE is held so
        the resource claim will not be lost if the audit process starts.
        """
        instance.host = None
        instance.node = None
        instance.save()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def abort_instance_claim(self, context, instance, nodename):
        """Remove usage from the given instance."""
        self._update_usage_from_instance(context, instance, nodename,
                                         is_removed=True)

        instance.clear_numa_topology()
        self._unset_instance_host_and_node(instance)

        self._update(context.elevated(), self.compute_nodes[nodename])

    def _drop_pci_devices(self, instance, nodename, prefix):
        if self.pci_tracker:
            # free old/new allocated pci devices
            pci_devices = self._get_migration_context_resource(
                'pci_devices', instance, prefix=prefix)
            if pci_devices:
                for pci_device in pci_devices:
                    self.pci_tracker.free_device(pci_device, instance)

                dev_pools_obj = self.pci_tracker.stats.to_device_pools_obj()
                self.compute_nodes[nodename].pci_device_pools = dev_pools_obj

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def drop_move_claim(self, context, instance, nodename,
                        instance_type=None, prefix='new_'):
        # Remove usage for an incoming/outgoing migration on the destination
        # node.
        if instance['uuid'] in self.tracked_migrations:
            migration = self.tracked_migrations.pop(instance['uuid'])

            if not instance_type:
                ctxt = context.elevated()
                instance_type = self._get_instance_type(ctxt, instance, prefix,
                                                        migration)

            if instance_type is not None:
                numa_topology = self._get_migration_context_resource(
                    'numa_topology', instance, prefix=prefix)
                usage = self._get_usage_dict(
                        instance_type, instance, numa_topology=numa_topology)
                self._drop_pci_devices(instance, nodename, prefix)
                self._update_usage(usage, nodename, sign=-1)

                ctxt = context.elevated()
                self._update(ctxt, self.compute_nodes[nodename])
        # Remove usage for an instance that is not tracked in migrations (such
        # as on the source node after a migration).
        # NOTE(lbeliveau): On resize on the same node, the instance is
        # included in both tracked_migrations and tracked_instances.
        elif (instance['uuid'] in self.tracked_instances):
            self.tracked_instances.pop(instance['uuid'])
            self._drop_pci_devices(instance, nodename, prefix)
            # TODO(lbeliveau): Validate if numa needs the same treatment.

            ctxt = context.elevated()
            self._update(ctxt, self.compute_nodes[nodename])

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_usage(self, context, instance, nodename):
        """Update the resource usage and stats after a change in an
        instance
        """
        if self.disabled(nodename):
            return

        uuid = instance['uuid']

        # don't update usage for this instance unless it submitted a resource
        # claim first:
        if uuid in self.tracked_instances:
            self._update_usage_from_instance(context, instance, nodename)
            self._update(context.elevated(), self.compute_nodes[nodename])

    def disabled(self, nodename):
        return (nodename not in self.compute_nodes or
                not self.driver.node_is_available(nodename))

    def _check_for_nodes_rebalance(self, context, resources, nodename):
        """Check if nodes rebalance has happened.

        The ironic driver maintains a hash ring mapping bare metal nodes
        to compute nodes. If a compute dies, the hash ring is rebuilt, and
        some of its bare metal nodes (more precisely, those not in ACTIVE
        state) are assigned to other computes.

        This method checks for this condition and adjusts the database
        accordingly.

        :param context: security context
        :param resources: initial values
        :param nodename: node name
        :returns: True if a suitable compute node record was found, else False
        """
        if not self.driver.rebalances_nodes:
            return False

        # Its possible ironic just did a node re-balance, so let's
        # check if there is a compute node that already has the correct
        # hypervisor_hostname. We can re-use that rather than create a
        # new one and have to move existing placement allocations
        cn_candidates = objects.ComputeNodeList.get_by_hypervisor(
            context, nodename)

        if len(cn_candidates) == 1:
            cn = cn_candidates[0]
            LOG.info("ComputeNode %(name)s moving from %(old)s to %(new)s",
                     {"name": nodename, "old": cn.host, "new": self.host})
            cn.host = self.host
            self.compute_nodes[nodename] = cn
            self._copy_resources(cn, resources)
            self._setup_pci_tracker(context, cn, resources)
            self._update(context, cn)
            return True
        elif len(cn_candidates) > 1:
            LOG.error(
                "Found more than one ComputeNode for nodename %s. "
                "Please clean up the orphaned ComputeNode records in your DB.",
                nodename)

        return False

    def _init_compute_node(self, context, resources):
        """Initialize the compute node if it does not already exist.

        The resource tracker will be inoperable if compute_node
        is not defined. The compute_node will remain undefined if
        we fail to create it or if there is no associated service
        registered.

        If this method has to create a compute node it needs initial
        values - these come from resources.

        :param context: security context
        :param resources: initial values
        """
        nodename = resources['hypervisor_hostname']

        # if there is already a compute node just use resources
        # to initialize
        if nodename in self.compute_nodes:
            cn = self.compute_nodes[nodename]
            self._copy_resources(cn, resources)
            self._setup_pci_tracker(context, cn, resources)
            return

        # now try to get the compute node record from the
        # database. If we get one we use resources to initialize
        cn = self._get_compute_node(context, nodename)
        if cn:
            self.compute_nodes[nodename] = cn
            self._copy_resources(cn, resources)
            self._setup_pci_tracker(context, cn, resources)
            return

        if self._check_for_nodes_rebalance(context, resources, nodename):
            return

        # there was no local copy and none in the database
        # so we need to create a new compute node. This needs
        # to be initialized with resource values.
        cn = objects.ComputeNode(context)
        cn.host = self.host
        self._copy_resources(cn, resources)
        self.compute_nodes[nodename] = cn
        cn.create()
        LOG.info('Compute node record created for '
                 '%(host)s:%(node)s with uuid: %(uuid)s',
                 {'host': self.host, 'node': nodename, 'uuid': cn.uuid})

        self._setup_pci_tracker(context, cn, resources)

    def _setup_pci_tracker(self, context, compute_node, resources):
        if not self.pci_tracker:
            n_id = compute_node.id
            self.pci_tracker = pci_manager.PciDevTracker(context, node_id=n_id)
            if 'pci_passthrough_devices' in resources:
                dev_json = resources.pop('pci_passthrough_devices')
                self.pci_tracker.update_devices_from_hypervisor_resources(
                        dev_json)

            dev_pools_obj = self.pci_tracker.stats.to_device_pools_obj()
            compute_node.pci_device_pools = dev_pools_obj

    def _copy_resources(self, compute_node, resources):
        """Copy resource values to supplied compute_node."""
        nodename = resources['hypervisor_hostname']
        stats = self.stats[nodename]
        # purge old stats and init with anything passed in by the driver
        # NOTE(danms): Preserve 'failed_builds' across the stats clearing,
        # as that is not part of resources
        # TODO(danms): Stop doing this when we get a column to store this
        # directly
        prev_failed_builds = stats.get('failed_builds', 0)
        stats.clear()
        stats['failed_builds'] = prev_failed_builds
        stats.digest_stats(resources.get('stats'))
        compute_node.stats = stats

        # Update the allocation ratios for the related ComputeNode object
        # but only if the configured values are not the default 0.0; the
        # ComputeNode._from_db_object method takes care of providing default
        # allocation ratios when the config is left at the 0.0 default, so
        # we'll really end up with something like a
        # ComputeNode.cpu_allocation_ratio of 16.0, not 0.0. We want to avoid
        # resetting the ComputeNode fields to 0.0 because that will make
        # the _resource_change method think something changed when really it
        # didn't.
        # TODO(mriedem): Will this break any scenarios where an operator is
        # trying to *reset* the allocation ratios by changing config from
        # non-0.0 back to 0.0? Maybe we should only do this if the fields on
        # the ComputeNode object are not already set. For example, let's say
        # the cpu_allocation_ratio config was 1.0 and then the operator wants
        # to get back to the default (16.0 via the facade), and to do that they
        # change the config back to 0.0 (or just unset the config option).
        # Should we support that or treat these config options as "sticky" in
        # that once you start setting them, you can't go back to the implied
        # defaults by unsetting or resetting to 0.0? Sort of like how
        # per-tenant quota is sticky once you change it in the API.
        for res in ('cpu', 'disk', 'ram'):
            attr = '%s_allocation_ratio' % res
            conf_alloc_ratio = getattr(self, attr)
            if conf_alloc_ratio != 0.0:
                setattr(compute_node, attr, conf_alloc_ratio)

        # now copy rest to compute_node
        compute_node.update_from_virt_driver(resources)

    def remove_node(self, nodename):
        """Handle node removal/rebalance.

        Clean up any stored data about a compute node no longer
        managed by this host.
        """
        self.stats.pop(nodename, None)
        self.compute_nodes.pop(nodename, None)
        self.old_resources.pop(nodename, None)

    def _get_host_metrics(self, context, nodename):
        """Get the metrics from monitors and
        notify information to message bus.
        """
        metrics = objects.MonitorMetricList()
        metrics_info = {}
        for monitor in self.monitors:
            try:
                monitor.populate_metrics(metrics)
            except NotImplementedError:
                LOG.debug("The compute driver doesn't support host "
                          "metrics for  %(mon)s", {'mon': monitor})
            except Exception as exc:
                LOG.warning("Cannot get the metrics from %(mon)s; "
                            "error: %(exc)s",
                            {'mon': monitor, 'exc': exc})
        # TODO(jaypipes): Remove this when compute_node.metrics doesn't need
        # to be populated as a JSONified string.
        metric_list = metrics.to_list()
        if len(metric_list):
            metrics_info['nodename'] = nodename
            metrics_info['metrics'] = metric_list
            metrics_info['host'] = self.host
            metrics_info['host_ip'] = CONF.my_ip
            notifier = rpc.get_notifier(service='compute', host=nodename)
            notifier.info(context, 'compute.metrics.update', metrics_info)
            compute_utils.notify_about_metrics_update(
                context, self.host, CONF.my_ip, nodename, metrics)
        return metric_list

    def update_available_resource(self, context, nodename):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.

        :param nodename: Temporary parameter representing the Ironic resource
                         node. This parameter will be removed once Ironic
                         baremetal resource nodes are handled like any other
                         resource in the system.
        """
        LOG.debug("Auditing locally available compute resources for "
                  "%(host)s (node: %(node)s)",
                 {'node': nodename,
                  'host': self.host})
        resources = self.driver.get_available_resource(nodename)
        # NOTE(jaypipes): The resources['hypervisor_hostname'] field now
        # contains a non-None value, even for non-Ironic nova-compute hosts. It
        # is this value that will be populated in the compute_nodes table.
        resources['host_ip'] = CONF.my_ip

        # We want the 'cpu_info' to be None from the POV of the
        # virt driver, but the DB requires it to be non-null so
        # just force it to empty string
        if "cpu_info" not in resources or resources["cpu_info"] is None:
            resources["cpu_info"] = ''

        self._verify_resources(resources)

        self._report_hypervisor_resource_view(resources)

        self._update_available_resource(context, resources)

    def _pair_instances_to_migrations(self, migrations, instance_by_uuid):
        for migration in migrations:
            try:
                migration.instance = instance_by_uuid[migration.instance_uuid]
            except KeyError:
                # NOTE(danms): If this happens, we don't set it here, and
                # let the code either fail or lazy-load the instance later
                # which is what happened before we added this optimization.
                # NOTE(tdurakov) this situation is possible for resize/cold
                # migration when migration is finished but haven't yet
                # confirmed/reverted in that case instance already changed host
                # to destination and no matching happens
                LOG.debug('Migration for instance %(uuid)s refers to '
                              'another host\'s instance!',
                          {'uuid': migration.instance_uuid})

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def _update_available_resource(self, context, resources):

        # initialize the compute node object, creating it
        # if it does not already exist.
        self._init_compute_node(context, resources)

        nodename = resources['hypervisor_hostname']

        # if we could not init the compute node the tracker will be
        # disabled and we should quit now
        if self.disabled(nodename):
            return

        # Grab all instances assigned to this node:
        instances = objects.InstanceList.get_by_host_and_node(
            context, self.host, nodename,
            expected_attrs=['system_metadata',
                            'numa_topology',
                            'flavor', 'migration_context'])

        # Now calculate usage based on instance utilization:
        instance_by_uuid = self._update_usage_from_instances(
            context, instances, nodename)

        # Grab all in-progress migrations:
        migrations = objects.MigrationList.get_in_progress_by_host_and_node(
                context, self.host, nodename)

        self._pair_instances_to_migrations(migrations, instance_by_uuid)
        self._update_usage_from_migrations(context, migrations, nodename)

        self._remove_deleted_instances_allocations(
            context, self.compute_nodes[nodename], migrations,
            instance_by_uuid)

        # Detect and account for orphaned instances that may exist on the
        # hypervisor, but are not in the DB:
        orphans = self._find_orphaned_instances()
        self._update_usage_from_orphans(orphans, nodename)

        cn = self.compute_nodes[nodename]

        # NOTE(yjiang5): Because pci device tracker status is not cleared in
        # this periodic task, and also because the resource tracker is not
        # notified when instances are deleted, we need remove all usages
        # from deleted instances.
        self.pci_tracker.clean_usage(instances, migrations, orphans)
        dev_pools_obj = self.pci_tracker.stats.to_device_pools_obj()
        cn.pci_device_pools = dev_pools_obj

        self._report_final_resource_view(nodename)

        metrics = self._get_host_metrics(context, nodename)
        # TODO(pmurray): metrics should not be a json string in ComputeNode,
        # but it is. This should be changed in ComputeNode
        cn.metrics = jsonutils.dumps(metrics)

        # update the compute_node
        self._update(context, cn)
        LOG.debug('Compute_service record updated for %(host)s:%(node)s',
                  {'host': self.host, 'node': nodename})

    def _get_compute_node(self, context, nodename):
        """Returns compute node for the host and nodename."""
        try:
            return objects.ComputeNode.get_by_host_and_nodename(
                context, self.host, nodename)
        except exception.NotFound:
            LOG.warning("No compute node record for %(host)s:%(node)s",
                        {'host': self.host, 'node': nodename})

    def _report_hypervisor_resource_view(self, resources):
        """Log the hypervisor's view of free resources.

        This is just a snapshot of resource usage recorded by the
        virt driver.

        The following resources are logged:
            - free memory
            - free disk
            - free CPUs
            - assignable PCI devices
        """
        nodename = resources['hypervisor_hostname']
        free_ram_mb = resources['memory_mb'] - resources['memory_mb_used']
        free_disk_gb = resources['local_gb'] - resources['local_gb_used']
        vcpus = resources['vcpus']
        if vcpus:
            free_vcpus = vcpus - resources['vcpus_used']
        else:
            free_vcpus = 'unknown'

        pci_devices = resources.get('pci_passthrough_devices')

        LOG.debug("Hypervisor/Node resource view: "
                  "name=%(node)s "
                  "free_ram=%(free_ram)sMB "
                  "free_disk=%(free_disk)sGB "
                  "free_vcpus=%(free_vcpus)s "
                  "pci_devices=%(pci_devices)s",
                  {'node': nodename,
                   'free_ram': free_ram_mb,
                   'free_disk': free_disk_gb,
                   'free_vcpus': free_vcpus,
                   'pci_devices': pci_devices})

    def _report_final_resource_view(self, nodename):
        """Report final calculate of physical memory, used virtual memory,
        disk, usable vCPUs, used virtual CPUs and PCI devices,
        including instance calculations and in-progress resource claims. These
        values will be exposed via the compute node table to the scheduler.
        """
        cn = self.compute_nodes[nodename]
        vcpus = cn.vcpus
        if vcpus:
            tcpu = vcpus
            ucpu = cn.vcpus_used
            LOG.debug("Total usable vcpus: %(tcpu)s, "
                      "total allocated vcpus: %(ucpu)s",
                      {'tcpu': vcpus,
                       'ucpu': ucpu})
        else:
            tcpu = 0
            ucpu = 0
        pci_stats = (list(cn.pci_device_pools) if
            cn.pci_device_pools else [])
        LOG.info("Final resource view: "
                 "name=%(node)s "
                 "phys_ram=%(phys_ram)sMB "
                 "used_ram=%(used_ram)sMB "
                 "phys_disk=%(phys_disk)sGB "
                 "used_disk=%(used_disk)sGB "
                 "total_vcpus=%(total_vcpus)s "
                 "used_vcpus=%(used_vcpus)s "
                 "pci_stats=%(pci_stats)s",
                 {'node': nodename,
                  'phys_ram': cn.memory_mb,
                  'used_ram': cn.memory_mb_used,
                  'phys_disk': cn.local_gb,
                  'used_disk': cn.local_gb_used,
                  'total_vcpus': tcpu,
                  'used_vcpus': ucpu,
                  'pci_stats': pci_stats})

    def _resource_change(self, compute_node):
        """Check to see if any resources have changed."""
        nodename = compute_node.hypervisor_hostname
        old_compute = self.old_resources[nodename]
        if not obj_base.obj_equal_prims(
                compute_node, old_compute, ['updated_at']):
            self.old_resources[nodename] = copy.deepcopy(compute_node)
            return True
        return False

    def _update_to_placement(self, context, compute_node):
        """Send resource and inventory changes to placement."""
        # NOTE(jianghuaw): Some resources(e.g. VGPU) are not saved in the
        # object of compute_node; instead the inventory data for these
        # resource is reported by driver's get_inventory(). So even there
        # is no resource change for compute_node as above, we need proceed
        # to get inventory and use scheduler_client interfaces to update
        # inventory to placement. It's scheduler_client's responsibility to
        # ensure the update request to placement only happens when inventory
        # is changed.
        nodename = compute_node.hypervisor_hostname
        # Persist the stats to the Scheduler
        # First try update_provider_tree
        # Retrieve the provider tree associated with this compute node.  If
        # it doesn't exist yet, this will create it with a (single, root)
        # provider corresponding to the compute node.
        reportclient = self.scheduler_client.reportclient
        prov_tree = reportclient.get_provider_tree_and_ensure_root(
            context, compute_node.uuid, name=compute_node.hypervisor_hostname)
        # Let the virt driver rearrange the provider tree and set/update
        # the inventory, traits, and aggregates throughout.
        try:
            self.driver.update_provider_tree(prov_tree, nodename)
            # We need to normalize inventory data for the compute node provider
            # (inject allocation ratio and reserved amounts from the
            # compute_node record if not set by the virt driver) because the
            # virt driver does not and will not have access to the compute_node
            inv_data = prov_tree.data(nodename).inventory
            # TODO(mriedem): Stop calling _normalize_inventory_from_cn_obj when
            # a virt driver implements update_provider_tree() since we expect
            # the driver to manage the allocation ratios and reserved resource
            # amounts.
            _normalize_inventory_from_cn_obj(inv_data, compute_node)
            prov_tree.update_inventory(nodename, inv_data)
            # Flush any changes.
            reportclient.update_from_provider_tree(context, prov_tree)
        except NotImplementedError:
            # update_provider_tree isn't implemented yet - try get_inventory
            try:
                inv_data = self.driver.get_inventory(nodename)
                _normalize_inventory_from_cn_obj(inv_data, compute_node)
                self.scheduler_client.set_inventory_for_provider(
                    context,
                    compute_node.uuid,
                    compute_node.hypervisor_hostname,
                    inv_data,
                )
            except NotImplementedError:
                # Eventually all virt drivers will return an inventory dict in
                # the format that the placement API expects and we'll be able
                # to remove this code branch
                self.scheduler_client.update_compute_node(context,
                                                          compute_node)

    @retrying.retry(stop_max_attempt_number=4,
                    retry_on_exception=lambda e: isinstance(
                        e, exception.ResourceProviderUpdateConflict))
    def _update(self, context, compute_node):
        """Update partial stats locally and populate them to Scheduler."""
        if self._resource_change(compute_node):
            # If the compute_node's resource changed, update to DB.
            # NOTE(jianghuaw): Once we completely move to use get_inventory()
            # for all resource provider's inv data. We can remove this check.
            # At the moment we still need this check and save compute_node.
            compute_node.save()

        self._update_to_placement(context, compute_node)

        if self.pci_tracker:
            self.pci_tracker.save(context)

    def _update_usage(self, usage, nodename, sign=1):
        mem_usage = usage['memory_mb']
        disk_usage = usage.get('root_gb', 0)
        vcpus_usage = usage.get('vcpus', 0)

        overhead = self.driver.estimate_instance_overhead(usage)
        mem_usage += overhead['memory_mb']
        disk_usage += overhead.get('disk_gb', 0)
        vcpus_usage += overhead.get('vcpus', 0)

        cn = self.compute_nodes[nodename]
        cn.memory_mb_used += sign * mem_usage
        cn.local_gb_used += sign * disk_usage
        cn.local_gb_used += sign * usage.get('ephemeral_gb', 0)
        cn.local_gb_used += sign * usage.get('swap', 0) / 1024
        cn.vcpus_used += sign * vcpus_usage

        # free ram and disk may be negative, depending on policy:
        cn.free_ram_mb = cn.memory_mb - cn.memory_mb_used
        cn.free_disk_gb = cn.local_gb - cn.local_gb_used

        stats = self.stats[nodename]
        cn.running_vms = stats.num_instances

        # Calculate the numa usage
        free = sign == -1
        updated_numa_topology = hardware.get_host_numa_usage_from_instance(
                cn, usage, free)
        cn.numa_topology = updated_numa_topology

    def _get_migration_context_resource(self, resource, instance,
                                        prefix='new_'):
        migration_context = instance.migration_context
        resource = prefix + resource
        if migration_context and resource in migration_context:
            return getattr(migration_context, resource)
        return None

    def _update_usage_from_migration(self, context, instance, migration,
                                     nodename):
        """Update usage for a single migration.  The record may
        represent an incoming or outbound migration.
        """
        if not _is_trackable_migration(migration):
            return

        uuid = migration.instance_uuid
        LOG.info("Updating resource usage from migration", instance_uuid=uuid)

        incoming = (migration.dest_compute == self.host and
                    migration.dest_node == nodename)
        outbound = (migration.source_compute == self.host and
                    migration.source_node == nodename)
        same_node = (incoming and outbound)

        record = self.tracked_instances.get(uuid, None)
        itype = None
        numa_topology = None
        sign = 0
        if same_node:
            # Same node resize. Record usage for the 'new_' resources.  This
            # is executed on resize_claim().
            if (instance['instance_type_id'] ==
                    migration.old_instance_type_id):
                itype = self._get_instance_type(context, instance, 'new_',
                        migration)
                numa_topology = self._get_migration_context_resource(
                    'numa_topology', instance)
                # Allocate pci device(s) for the instance.
                sign = 1
            else:
                # The instance is already set to the new flavor (this is done
                # by the compute manager on finish_resize()), hold space for a
                # possible revert to the 'old_' resources.
                # NOTE(lbeliveau): When the periodic audit timer gets
                # triggered, the compute usage gets reset.  The usage for an
                # instance that is migrated to the new flavor but not yet
                # confirmed/reverted will first get accounted for by
                # _update_usage_from_instances().  This method will then be
                # called, and we need to account for the '_old' resources
                # (just in case).
                itype = self._get_instance_type(context, instance, 'old_',
                        migration)
                numa_topology = self._get_migration_context_resource(
                    'numa_topology', instance, prefix='old_')

        elif incoming and not record:
            # instance has not yet migrated here:
            itype = self._get_instance_type(context, instance, 'new_',
                    migration)
            numa_topology = self._get_migration_context_resource(
                'numa_topology', instance)
            # Allocate pci device(s) for the instance.
            sign = 1

        elif outbound and not record:
            # instance migrated, but record usage for a possible revert:
            itype = self._get_instance_type(context, instance, 'old_',
                    migration)
            numa_topology = self._get_migration_context_resource(
                'numa_topology', instance, prefix='old_')

        if itype:
            cn = self.compute_nodes[nodename]
            usage = self._get_usage_dict(
                        itype, instance, numa_topology=numa_topology)
            if self.pci_tracker and sign:
                self.pci_tracker.update_pci_for_instance(
                    context, instance, sign=sign)
            self._update_usage(usage, nodename)
            if self.pci_tracker:
                obj = self.pci_tracker.stats.to_device_pools_obj()
                cn.pci_device_pools = obj
            else:
                obj = objects.PciDevicePoolList()
                cn.pci_device_pools = obj
            self.tracked_migrations[uuid] = migration

    def _update_usage_from_migrations(self, context, migrations, nodename):
        filtered = {}
        instances = {}
        self.tracked_migrations.clear()

        # do some defensive filtering against bad migrations records in the
        # database:
        for migration in migrations:
            uuid = migration.instance_uuid

            try:
                if uuid not in instances:
                    instances[uuid] = migration.instance
            except exception.InstanceNotFound as e:
                # migration referencing deleted instance
                LOG.debug('Migration instance not found: %s', e)
                continue

            # skip migration if instance isn't in a resize state:
            if not _instance_in_resize_state(instances[uuid]):
                LOG.warning("Instance not resizing, skipping migration.",
                            instance_uuid=uuid)
                continue

            # filter to most recently updated migration for each instance:
            other_migration = filtered.get(uuid, None)
            # NOTE(claudiub): In Python 3, you cannot compare NoneTypes.
            if other_migration:
                om = other_migration
                other_time = om.updated_at or om.created_at
                migration_time = migration.updated_at or migration.created_at
                if migration_time > other_time:
                    filtered[uuid] = migration
            else:
                filtered[uuid] = migration

        for migration in filtered.values():
            instance = instances[migration.instance_uuid]
            # Skip migration (and mark it as error) if it doesn't match the
            # instance migration id.
            # This can happen if we have a stale migration record.
            # We want to proceed if instance.migration_context is None
            if (instance.migration_context is not None and
                    instance.migration_context.migration_id != migration.id):
                LOG.info("Current instance migration %(im)s doesn't match "
                             "migration %(m)s, marking migration as error. "
                             "This can occur if a previous migration for this "
                             "instance did not complete.",
                    {'im': instance.migration_context.migration_id,
                     'm': migration.id})
                migration.status = "error"
                migration.save()
                continue

            try:
                self._update_usage_from_migration(context, instance, migration,
                                                  nodename)
            except exception.FlavorNotFound:
                LOG.warning("Flavor could not be found, skipping migration.",
                            instance_uuid=instance.uuid)
                continue

    def _update_usage_from_instance(self, context, instance, nodename,
            is_removed=False, require_allocation_refresh=False):
        """Update usage for a single instance."""

        uuid = instance['uuid']
        is_new_instance = uuid not in self.tracked_instances
        # NOTE(sfinucan): Both brand new instances as well as instances that
        # are being unshelved will have is_new_instance == True
        is_removed_instance = not is_new_instance and (is_removed or
            instance['vm_state'] in vm_states.ALLOW_RESOURCE_REMOVAL)

        if is_new_instance:
            self.tracked_instances[uuid] = obj_base.obj_to_primitive(instance)
            sign = 1

        if is_removed_instance:
            self.tracked_instances.pop(uuid)
            sign = -1

        cn = self.compute_nodes[nodename]
        stats = self.stats[nodename]
        stats.update_stats_for_instance(instance, is_removed_instance)
        cn.stats = stats

        # if it's a new or deleted instance:
        if is_new_instance or is_removed_instance:
            if self.pci_tracker:
                self.pci_tracker.update_pci_for_instance(context,
                                                         instance,
                                                         sign=sign)
            if require_allocation_refresh:
                LOG.debug("Auto-correcting allocations.")
                self.reportclient.update_instance_allocation(context, cn,
                                                             instance, sign)
            # new instance, update compute node resource usage:
            self._update_usage(self._get_usage_dict(instance, instance),
                               nodename, sign=sign)

        # Stop tracking removed instances in the is_bfv cache. This needs to
        # happen *after* calling _get_usage_dict() since that relies on the
        # is_bfv cache.
        if is_removed_instance and uuid in self.is_bfv:
            del self.is_bfv[uuid]

        cn.current_workload = stats.calculate_workload()
        if self.pci_tracker:
            obj = self.pci_tracker.stats.to_device_pools_obj()
            cn.pci_device_pools = obj
        else:
            cn.pci_device_pools = objects.PciDevicePoolList()

    def _update_usage_from_instances(self, context, instances, nodename):
        """Calculate resource usage based on instance utilization.  This is
        different than the hypervisor's view as it will account for all
        instances assigned to the local compute host, even if they are not
        currently powered on.
        """
        self.tracked_instances.clear()

        cn = self.compute_nodes[nodename]
        # set some initial values, reserve room for host/hypervisor:
        cn.local_gb_used = CONF.reserved_host_disk_mb / 1024
        cn.memory_mb_used = CONF.reserved_host_memory_mb
        cn.vcpus_used = CONF.reserved_host_cpus
        cn.free_ram_mb = (cn.memory_mb - cn.memory_mb_used)
        cn.free_disk_gb = (cn.local_gb - cn.local_gb_used)
        cn.current_workload = 0
        cn.running_vms = 0

        # NOTE(jaypipes): In Pike, we need to be tolerant of Ocata compute
        # nodes that overwrite placement allocations to look like what the
        # resource tracker *thinks* is correct. When an instance is
        # migrated from an Ocata compute node to a Pike compute node, the
        # Pike scheduler will have created a "doubled-up" allocation that
        # contains allocated resources against both the source and
        # destination hosts. The Ocata source compute host, during its
        # update_available_resource() periodic call will find the instance
        # in its list of known instances and will call
        # update_instance_allocation() in the report client. That call will
        # pull the allocations for the instance UUID which will contain
        # both the source and destination host providers in the allocation
        # set. Seeing that this is different from what the Ocata source
        # host thinks it should be and will overwrite the allocation to
        # only be an allocation against itself.
        #
        # And therefore, here we need to have Pike compute hosts
        # "correct" the improper healing that the Ocata source host did
        # during its periodic interval. When the instance is fully migrated
        # to the Pike compute host, the Ocata compute host will find an
        # allocation that refers to itself for an instance it no longer
        # controls and will *delete* all allocations that refer to that
        # instance UUID, assuming that the instance has been deleted. We
        # need the destination Pike compute host to recreate that
        # allocation to refer to its own resource provider UUID.
        #
        # For Pike compute nodes that migrate to either a Pike compute host
        # or a Queens compute host, we do NOT want the Pike compute host to
        # be "healing" allocation information. Instead, we rely on the Pike
        # scheduler to properly create allocations during scheduling.
        #
        # Pike compute hosts may still rework an
        # allocation for an instance in a move operation during
        # confirm_resize() on the source host which will remove the
        # source resource provider from any allocation for an
        # instance.
        #
        # In Queens and beyond, the scheduler will understand when
        # a move operation has been requested and instead of
        # creating a doubled-up allocation that contains both the
        # source and destination host, the scheduler will take the
        # original allocation (against the source host) and change
        # the consumer ID of that allocation to be the migration
        # UUID and not the instance UUID. The scheduler will
        # allocate the resources for the destination host to the
        # instance UUID.

        # Some drivers (ironic) still need the allocations to be
        # fixed up, as they transition the way their inventory is reported.
        require_allocation_refresh = self.driver.requires_allocation_refresh

        if require_allocation_refresh:
            msg_allocation_refresh = (
                "Compute driver requires allocation refresh. "
                "Will auto-correct allocations to handle "
                "Ocata-style assumptions.")
        else:
            msg_allocation_refresh = (
                "Compute driver doesn't require allocation refresh and we're "
                "on a compute host in a deployment that only has compute "
                "hosts with Nova versions >=16 (Pike). Skipping "
                "auto-correction of allocations.")

        instance_by_uuid = {}
        for instance in instances:
            if instance.vm_state not in vm_states.ALLOW_RESOURCE_REMOVAL:
                if msg_allocation_refresh:
                    LOG.debug(msg_allocation_refresh)
                    msg_allocation_refresh = False

                self._update_usage_from_instance(context, instance, nodename,
                    require_allocation_refresh=require_allocation_refresh)
            instance_by_uuid[instance.uuid] = instance
        return instance_by_uuid

    def _remove_deleted_instances_allocations(self, context, cn,
                                              migrations, instance_by_uuid):
        migration_uuids = [migration.uuid for migration in migrations
                           if 'uuid' in migration]
        # NOTE(jaypipes): All of this code sucks. It's basically dealing with
        # all the corner cases in move, local delete, unshelve and rebuild
        # operations for when allocations should be deleted when things didn't
        # happen according to the normal flow of events where the scheduler
        # always creates allocations for an instance
        known_instances = set(self.tracked_instances.keys())
        allocations = self.reportclient.get_allocations_for_resource_provider(
                context, cn.uuid) or {}
        read_deleted_context = context.elevated(read_deleted='yes')
        for consumer_uuid, alloc in allocations.items():
            if consumer_uuid in known_instances:
                LOG.debug("Instance %s actively managed on this compute host "
                          "and has allocations in placement: %s.",
                          consumer_uuid, alloc)
                continue
            if consumer_uuid in migration_uuids:
                LOG.debug("Migration %s is active on this compute host "
                          "and has allocations in placement: %s.",
                          consumer_uuid, alloc)
                continue

            # We know these are instances now, so proceed
            instance_uuid = consumer_uuid
            instance = instance_by_uuid.get(instance_uuid)
            if not instance:
                try:
                    instance = objects.Instance.get_by_uuid(
                        read_deleted_context, consumer_uuid,
                        expected_attrs=[])
                except exception.InstanceNotFound:
                    # The instance isn't even in the database. Either the
                    # scheduler _just_ created an allocation for it and we're
                    # racing with the creation in the cell database, or the
                    #  instance was deleted and fully archived before we got a
                    # chance to run this. The former is far more likely than
                    # the latter. Avoid deleting allocations for a building
                    # instance here.
                    LOG.info("Instance %(uuid)s has allocations against this "
                             "compute host but is not found in the database.",
                             {'uuid': instance_uuid},
                             exc_info=False)
                    continue

            if instance.deleted:
                # The instance is gone, so we definitely want to remove
                # allocations associated with it.
                # NOTE(jaypipes): This will not be true if/when we support
                # cross-cell migrations...
                LOG.debug("Instance %s has been deleted (perhaps locally). "
                          "Deleting allocations that remained for this "
                          "instance against this compute host: %s.",
                          instance_uuid, alloc)
                self.reportclient.delete_allocation_for_instance(context,
                                                                 instance_uuid)
                continue
            if not instance.host:
                # Allocations related to instances being scheduled should not
                # be deleted if we already wrote the allocation previously.
                LOG.debug("Instance %s has been scheduled to this compute "
                          "host, the scheduler has made an allocation "
                          "against this compute node but the instance has "
                          "yet to start. Skipping heal of allocation: %s.",
                          instance_uuid, alloc)
                continue
            if (instance.host == cn.host and
                    instance.node == cn.hypervisor_hostname):
                # The instance is supposed to be on this compute host but is
                # not in the list of actively managed instances.
                LOG.warning("Instance %s is not being actively managed by "
                            "this compute host but has allocations "
                            "referencing this compute host: %s. Skipping "
                            "heal of allocation because we do not know "
                            "what to do.", instance_uuid, alloc)
                continue
            if instance.host != cn.host:
                # The instance has been moved to another host either via a
                # migration, evacuation or unshelve in between the time when we
                # ran InstanceList.get_by_host_and_node(), added those
                # instances to RT.tracked_instances and the above
                # Instance.get_by_uuid() call. We SHOULD attempt to remove any
                # allocations that reference this compute host if the VM is in
                # a stable terminal state (i.e. it isn't in a state of waiting
                # for resize to confirm/revert), however if the destination
                # host is an Ocata compute host, it will delete the allocation
                # that contains this source compute host information anyway and
                # recreate an allocation that only refers to itself. So we
                # don't need to do anything in that case. Just log the
                # situation here for information but don't attempt to delete or
                # change the allocation.
                LOG.warning("Instance %s has been moved to another host "
                            "%s(%s). There are allocations remaining against "
                            "the source host that might need to be removed: "
                            "%s.",
                            instance_uuid, instance.host, instance.node, alloc)

    def delete_allocation_for_evacuated_instance(self, context, instance, node,
                                                 node_type='source'):
        self._delete_allocation_for_moved_instance(
            context, instance, node, 'evacuated', node_type)

    def delete_allocation_for_migrated_instance(self, context, instance, node):
        self._delete_allocation_for_moved_instance(context, instance, node,
                                                   'migrated')

    def _delete_allocation_for_moved_instance(
            self, context, instance, node, move_type, node_type='source'):
        # Clean up the instance allocation from this node in placement
        cn_uuid = self.compute_nodes[node].uuid
        if not scheduler_utils.remove_allocation_from_compute(
                context, instance, cn_uuid, self.reportclient):
            LOG.error("Failed to clean allocation of %s "
                      "instance on the %s node %s",
                      move_type, node_type, cn_uuid, instance=instance)

    def delete_allocation_for_failed_resize(self, context, instance, node,
                                            flavor):
        """Delete instance allocations for the node during a failed resize

        :param context: The request context.
        :param instance: The instance being resized/migrated.
        :param node: The node provider on which the instance should have
            allocations to remove. If this is a resize to the same host, then
            the new_flavor resources are subtracted from the single allocation.
        :param flavor: This is the new_flavor during a resize.
        """
        cn = self.compute_nodes[node]
        if not scheduler_utils.remove_allocation_from_compute(
                context, instance, cn.uuid, self.reportclient, flavor):
            if instance.instance_type_id == flavor.id:
                operation = 'migration'
            else:
                operation = 'resize'
            LOG.error('Failed to clean allocation after a failed '
                      '%(operation)s on node %(node)s',
                      {'operation': operation, 'node': cn.uuid},
                      instance=instance)

    def _find_orphaned_instances(self):
        """Given the set of instances and migrations already account for
        by resource tracker, sanity check the hypervisor to determine
        if there are any "orphaned" instances left hanging around.

        Orphans could be consuming memory and should be accounted for in
        usage calculations to guard against potential out of memory
        errors.
        """
        uuids1 = frozenset(self.tracked_instances.keys())
        uuids2 = frozenset(self.tracked_migrations.keys())
        uuids = uuids1 | uuids2

        usage = self.driver.get_per_instance_usage()
        vuuids = frozenset(usage.keys())

        orphan_uuids = vuuids - uuids
        orphans = [usage[uuid] for uuid in orphan_uuids]

        return orphans

    def _update_usage_from_orphans(self, orphans, nodename):
        """Include orphaned instances in usage."""
        for orphan in orphans:
            memory_mb = orphan['memory_mb']

            LOG.warning("Detected running orphan instance: %(uuid)s "
                        "(consuming %(memory_mb)s MB memory)",
                        {'uuid': orphan['uuid'], 'memory_mb': memory_mb})

            # just record memory usage for the orphan
            usage = {'memory_mb': memory_mb}
            self._update_usage(usage, nodename)

    def delete_allocation_for_shelve_offloaded_instance(self, context,
                                                        instance):
        self.reportclient.delete_allocation_for_instance(context,
                                                         instance.uuid)

    def _verify_resources(self, resources):
        resource_keys = ["vcpus", "memory_mb", "local_gb", "cpu_info",
                         "vcpus_used", "memory_mb_used", "local_gb_used",
                         "numa_topology"]

        missing_keys = [k for k in resource_keys if k not in resources]
        if missing_keys:
            reason = _("Missing keys: %s") % missing_keys
            raise exception.InvalidInput(reason=reason)

    def _get_instance_type(self, context, instance, prefix, migration):
        """Get the instance type from instance."""
        stashed_flavors = migration.migration_type in ('resize',)
        if stashed_flavors:
            return getattr(instance, '%sflavor' % prefix)
        else:
            # NOTE(ndipanov): Certain migration types (all but resize)
            # do not change flavors so there is no need to stash
            # them. In that case - just get the instance flavor.
            return instance.flavor

    def _get_usage_dict(self, object_or_dict, instance, **updates):
        """Make a usage dict _update methods expect.

        Accepts a dict or an Instance or Flavor object, and a set of updates.
        Converts the object to a dict and applies the updates.

        :param object_or_dict: instance or flavor as an object or just a dict
        :param instance: nova.objects.Instance for the related operation; this
                         is needed to determine if the instance is
                         volume-backed
        :param updates: key-value pairs to update the passed object.
                        Currently only considers 'numa_topology', all other
                        keys are ignored.

        :returns: a dict with all the information from object_or_dict updated
                  with updates
        """

        def _is_bfv():
            # Check to see if we have the is_bfv value cached.
            if instance.uuid in self.is_bfv:
                is_bfv = self.is_bfv[instance.uuid]
            else:
                is_bfv = compute_utils.is_volume_backed_instance(
                    instance._context, instance)
                self.is_bfv[instance.uuid] = is_bfv
            return is_bfv

        usage = {}
        if isinstance(object_or_dict, objects.Instance):
            is_bfv = _is_bfv()
            usage = {'memory_mb': object_or_dict.flavor.memory_mb,
                     'swap': object_or_dict.flavor.swap,
                     'vcpus': object_or_dict.flavor.vcpus,
                     'root_gb': (0 if is_bfv else
                                 object_or_dict.flavor.root_gb),
                     'ephemeral_gb': object_or_dict.flavor.ephemeral_gb,
                     'numa_topology': object_or_dict.numa_topology}
        elif isinstance(object_or_dict, objects.Flavor):
            usage = obj_base.obj_to_primitive(object_or_dict)
            if _is_bfv():
                usage['root_gb'] = 0
        else:
            usage.update(object_or_dict)

        for key in ('numa_topology',):
            if key in updates:
                usage[key] = updates[key]
        return usage

    def build_failed(self, nodename):
        """Increments the failed_builds stats for the given node."""
        self.stats[nodename].build_failed()

    def build_succeeded(self, nodename):
        """Resets the failed_builds stats for the given node."""
        self.stats[nodename].build_succeeded()
