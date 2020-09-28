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

from keystoneauth1 import exceptions as ks_exc
import os_traits
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
import retrying

from nova.compute import claims
from nova.compute import monitors
from nova.compute import provider_config
from nova.compute import stats as compute_stats
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova.objects import migration as migration_obj
from nova.pci import manager as pci_manager
from nova.pci import request as pci_request
from nova import rpc
from nova.scheduler.client import report
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

    if vm in [vm_states.ACTIVE, vm_states.STOPPED] and task in (
            task_states.resizing_states + task_states.rebuild_states):
        return True

    return False


def _instance_is_live_migrating(instance):
    vm = instance.vm_state
    task = instance.task_state
    if task == task_states.MIGRATING and vm in [vm_states.ACTIVE,
                                                vm_states.PAUSED]:
        return True
    return False


class ResourceTracker(object):
    """Compute helper class for keeping track of resource usage as instances
    are built and destroyed.
    """

    def __init__(self, host, driver, reportclient=None):
        self.host = host
        self.driver = driver
        self.pci_tracker = None
        # Dict of objects.ComputeNode objects, keyed by nodename
        self.compute_nodes = {}
        # Dict of Stats objects, keyed by nodename
        self.stats = collections.defaultdict(compute_stats.Stats)
        # Set of UUIDs of instances tracked on this host.
        self.tracked_instances = set()
        self.tracked_migrations = {}
        self.is_bfv = {}  # dict, keyed by instance uuid, to is_bfv boolean
        monitor_handler = monitors.MonitorHandler(self)
        self.monitors = monitor_handler.monitors
        self.old_resources = collections.defaultdict(objects.ComputeNode)
        self.reportclient = reportclient or report.SchedulerReportClient()
        self.ram_allocation_ratio = CONF.ram_allocation_ratio
        self.cpu_allocation_ratio = CONF.cpu_allocation_ratio
        self.disk_allocation_ratio = CONF.disk_allocation_ratio
        self.provider_tree = None
        # Dict of assigned_resources, keyed by resource provider uuid
        # the value is a dict again, keyed by resource class
        # and value of this sub-dict is a set of Resource obj
        self.assigned_resources = collections.defaultdict(
            lambda: collections.defaultdict(set))
        # Retrieves dict of provider config data. This can fail with
        # nova.exception.ProviderConfigException if invalid or conflicting
        # data exists in the provider config files.
        self.provider_configs = provider_config.get_provider_configs(
            CONF.compute.provider_config_location)
        # Set of ids for providers identified in provider config files that
        # are not found on the provider tree. These are tracked to facilitate
        # smarter logging.
        self.absent_providers = set()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def instance_claim(self, context, instance, nodename, allocations,
                       limits=None):
        """Indicate that some resources are needed for an upcoming compute
        instance build operation.

        This should be called before the compute node is about to perform
        an instance build operation that will consume additional resources.

        :param context: security context
        :param instance: instance to reserve resources for.
        :type instance: nova.objects.instance.Instance object
        :param nodename: The Ironic nodename selected by the scheduler
        :param allocations: The placement allocation records for the instance.
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

        cn = self.compute_nodes[nodename]
        pci_requests = instance.pci_requests
        claim = claims.Claim(context, instance, nodename, self, cn,
                             pci_requests, limits=limits)

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

        claimed_resources = self._claim_resources(allocations)
        instance.resources = claimed_resources

        # Mark resources in-use and update stats
        self._update_usage_from_instance(context, instance, nodename)

        elevated = context.elevated()
        # persist changes to the compute node:
        self._update(elevated, cn)

        return claim

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def rebuild_claim(self, context, instance, nodename, allocations,
                      limits=None, image_meta=None, migration=None):
        """Create a claim for a rebuild operation."""
        instance_type = instance.flavor
        return self._move_claim(
            context, instance, instance_type, nodename, migration, allocations,
            move_type=fields.MigrationType.EVACUATION,
            image_meta=image_meta, limits=limits)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def resize_claim(self, context, instance, instance_type, nodename,
                     migration, allocations, image_meta=None, limits=None):
        """Create a claim for a resize or cold-migration move.

        Note that this code assumes ``instance.new_flavor`` is set when
        resizing with a new flavor.
        """
        return self._move_claim(context, instance, instance_type, nodename,
                                migration, allocations, image_meta=image_meta,
                                limits=limits)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def live_migration_claim(self, context, instance, nodename, migration,
                             limits, allocs):
        """Builds a MoveClaim for a live migration.

        :param context: The request context.
        :param instance: The instance being live migrated.
        :param nodename: The nodename of the destination host.
        :param migration: The Migration object associated with this live
                          migration.
        :param limits: A SchedulerLimits object from when the scheduler
                       selected the destination host.
        :param allocs: The placement allocation records for the instance.
        :returns: A MoveClaim for this live migration.
        """
        # Flavor and image cannot change during a live migration.
        instance_type = instance.flavor
        image_meta = instance.image_meta
        return self._move_claim(
            context, instance, instance_type, nodename, migration, allocs,
            move_type=fields.MigrationType.LIVE_MIGRATION,
            image_meta=image_meta, limits=limits,
        )

    def _move_claim(self, context, instance, new_instance_type, nodename,
                    migration, allocations, move_type=None,
                    image_meta=None, limits=None):
        """Indicate that resources are needed for a move to this host.

        Move can be either a migrate/resize, live-migrate or an
        evacuate/rebuild operation.

        :param context: security context
        :param instance: instance object to reserve resources for
        :param new_instance_type: new instance_type being resized to
        :param nodename: The Ironic nodename selected by the scheduler
        :param migration: A migration object if one was already created
                          elsewhere for this operation (otherwise None)
        :param allocations: the placement allocation records.
        :param move_type: move type - can be one of 'migration', 'resize',
                         'live-migration', 'evacuate'
        :param image_meta: instance image metadata
        :param limits: Dict of oversubscription limits for memory, disk,
        and CPUs
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

        cn = self.compute_nodes[nodename]

        # TODO(moshele): we are recreating the pci requests even if
        # there was no change on resize. This will cause allocating
        # the old/new pci device in the resize phase. In the future
        # we would like to optimise this.
        new_pci_requests = pci_request.get_pci_requests_from_flavor(
            new_instance_type)
        new_pci_requests.instance_uuid = instance.uuid
        # On resize merge the SR-IOV ports pci_requests
        # with the new instance flavor pci_requests.
        if instance.pci_requests:
            for request in instance.pci_requests.requests:
                if request.source == objects.InstancePCIRequest.NEUTRON_PORT:
                    new_pci_requests.requests.append(request)
        claim = claims.MoveClaim(context, instance, nodename,
                                 new_instance_type, image_meta, self, cn,
                                 new_pci_requests, migration, limits=limits)

        claimed_pci_devices_objs = []
        # TODO(artom) The second part of this condition should not be
        # necessary, but since SRIOV live migration is currently handled
        # elsewhere - see for example _claim_pci_for_instance_vifs() in the
        # compute manager - we don't do any PCI claims if this is a live
        # migration to avoid stepping on that code's toes. Ideally,
        # MoveClaim/this method would be used for all live migration resource
        # claims.
        if self.pci_tracker and not migration.is_live_migration:
            # NOTE(jaypipes): ComputeNode.pci_device_pools is set below
            # in _update_usage_from_instance().
            claimed_pci_devices_objs = self.pci_tracker.claim_instance(
                    context, new_pci_requests, claim.claimed_numa_topology)
        claimed_pci_devices = objects.PciDeviceList(
                objects=claimed_pci_devices_objs)

        claimed_resources = self._claim_resources(allocations)
        old_resources = instance.resources

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
            new_pci_requests=new_pci_requests,
            old_resources=old_resources,
            new_resources=claimed_resources)

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
        # NOTE(artom) Migration objects for live migrations are created with
        # status 'accepted' by the conductor in live_migrate_instance() and do
        # not have a 'pre-migrating' status.
        if not migration.is_live_migration:
            migration.status = 'pre-migrating'
        migration.save()

    def _claim_resources(self, allocations):
        """Claim resources according to assigned resources from allocations
        and available resources in provider tree
        """
        if not allocations:
            return None
        claimed_resources = []
        for rp_uuid, alloc_dict in allocations.items():
            try:
                provider_data = self.provider_tree.data(rp_uuid)
            except ValueError:
                # If an instance is in evacuating, it will hold new and old
                # allocations, but the provider UUIDs in old allocations won't
                # exist in the current provider tree, so skip it.
                LOG.debug("Skip claiming resources of provider %(rp_uuid)s, "
                          "since the provider UUIDs are not in provider tree.",
                          {'rp_uuid': rp_uuid})
                continue
            for rc, amount in alloc_dict['resources'].items():
                if rc not in provider_data.resources:
                    # This means we don't use provider_data.resources to
                    # assign this kind of resource class, such as 'VCPU' for
                    # now, otherwise the provider_data.resources will be
                    # populated with this resource class when updating
                    # provider tree.
                    continue
                assigned = self.assigned_resources[rp_uuid][rc]
                free = provider_data.resources[rc] - assigned
                if amount > len(free):
                    reason = (_("Needed %(amount)d units of resource class "
                                "%(rc)s, but %(avail)d are available.") %
                                {'amount': amount,
                                 'rc': rc,
                                 'avail': len(free)})
                    raise exception.ComputeResourcesUnavailable(reason=reason)
                for i in range(amount):
                    claimed_resources.append(free.pop())

        if claimed_resources:
            self._add_assigned_resources(claimed_resources)
            return objects.ResourceList(objects=claimed_resources)

    def _populate_assigned_resources(self, context, instance_by_uuid):
        """Populate self.assigned_resources organized by resource class and
        reource provider uuid, which is as following format:
        {
        $RP_UUID: {
            $RESOURCE_CLASS: [objects.Resource, ...],
            $RESOURCE_CLASS: [...]},
        ...}
        """
        resources = []

        # Get resources assigned to migrations
        for mig in self.tracked_migrations.values():
            mig_ctx = mig.instance.migration_context
            # We might have a migration whose instance hasn't arrived here yet.
            # Ignore it.
            if not mig_ctx:
                continue
            if mig.source_compute == self.host and 'old_resources' in mig_ctx:
                resources.extend(mig_ctx.old_resources or [])
            if mig.dest_compute == self.host and 'new_resources' in mig_ctx:
                resources.extend(mig_ctx.new_resources or [])

        # Get resources assigned to instances
        for uuid in self.tracked_instances:
            resources.extend(instance_by_uuid[uuid].resources or [])

        self.assigned_resources.clear()
        self._add_assigned_resources(resources)

    def _check_resources(self, context):
        """Check if there are assigned resources not found in provider tree"""
        notfound = set()
        for rp_uuid in self.assigned_resources:
            provider_data = self.provider_tree.data(rp_uuid)
            for rc, assigned in self.assigned_resources[rp_uuid].items():
                notfound |= (assigned - provider_data.resources[rc])

        if not notfound:
            return

        # This only happens when assigned resources are removed
        # from the configuration and the compute service is SIGHUP'd
        # or restarted.
        resources = [(res.identifier, res.resource_class) for res in notfound]
        reason = _("The following resources are assigned to instances, "
                   "but were not listed in the configuration: %s "
                   "Please check if this will influence your instances, "
                   "and restore your configuration if necessary") % resources
        raise exception.AssignedResourceNotFound(reason=reason)

    def _release_assigned_resources(self, resources):
        """Remove resources from self.assigned_resources."""
        if not resources:
            return
        for resource in resources:
            rp_uuid = resource.provider_uuid
            rc = resource.resource_class
            try:
                self.assigned_resources[rp_uuid][rc].remove(resource)
            except KeyError:
                LOG.warning("Release resource %(rc)s: %(id)s of provider "
                            "%(rp_uuid)s, not tracked in "
                            "ResourceTracker.assigned_resources.",
                            {'rc': rc, 'id': resource.identifier,
                             'rp_uuid': rp_uuid})

    def _add_assigned_resources(self, resources):
        """Add resources to self.assigned_resources"""
        if not resources:
            return
        for resource in resources:
            rp_uuid = resource.provider_uuid
            rc = resource.resource_class
            self.assigned_resources[rp_uuid][rc].add(resource)

    def _set_instance_host_and_node(self, instance, nodename):
        """Tag the instance as belonging to this host.  This should be done
        while the COMPUTE_RESOURCES_SEMAPHORE is held so the resource claim
        will not be lost if the audit process starts.
        """
        # NOTE(mriedem): ComputeManager._nil_out_instance_obj_host_and_node is
        # somewhat tightly coupled to the fields set in this method so if this
        # method changes that method might need to be updated.
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

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
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

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def drop_move_claim_at_source(self, context, instance, migration):
        """Drop a move claim after confirming a resize or cold migration."""
        migration.status = 'confirmed'
        migration.save()

        self._drop_move_claim(
            context, instance, migration.source_node, instance.old_flavor,
            prefix='old_')

        # NOTE(stephenfin): Unsetting this is unnecessary for cross-cell
        # resize, since the source and dest instance objects are different and
        # the source instance will be deleted soon. It's easier to just do it
        # though.
        instance.drop_migration_context()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def drop_move_claim_at_dest(self, context, instance, migration):
        """Drop a move claim after reverting a resize or cold migration."""

        # NOTE(stephenfin): This runs on the destination, before we return to
        # the source and resume the instance there. As such, the migration
        # isn't really really reverted yet, but this status is what we use to
        # indicate that we no longer needs to account for usage on this host
        migration.status = 'reverted'
        migration.save()

        self._drop_move_claim(
            context, instance, migration.dest_node, instance.new_flavor,
            prefix='new_')

        instance.revert_migration_context()
        instance.save(expected_task_state=[task_states.RESIZE_REVERTING])

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def drop_move_claim(self, context, instance, nodename,
                        instance_type=None, prefix='new_'):
        self._drop_move_claim(
            context, instance, nodename, instance_type, prefix='new_')

    def _drop_move_claim(
        self, context, instance, nodename, instance_type=None, prefix='new_',
    ):
        """Remove usage for an incoming/outgoing migration.

        :param context: Security context.
        :param instance: The instance whose usage is to be removed.
        :param nodename: Host on which to remove usage. If the migration
                         completed successfully, this is normally the source.
                         If it did not complete successfully (failed or
                         reverted), this is normally the destination.
        :param instance_type: The flavor that determines the usage to remove.
                              If the migration completed successfully, this is
                              the old flavor to be removed from the source. If
                              the migration did not complete successfully, this
                              is the new flavor to be removed from the
                              destination.
        :param prefix: Prefix to use when accessing migration context
                       attributes. 'old_' or 'new_', with 'new_' being the
                       default.
        """
        # Remove usage for an instance that is tracked in migrations, such as
        # on the dest node during revert resize.
        if instance['uuid'] in self.tracked_migrations:
            migration = self.tracked_migrations.pop(instance['uuid'])
            if not instance_type:
                instance_type = self._get_instance_type(instance, prefix,
                                                        migration)
        # Remove usage for an instance that is not tracked in migrations (such
        # as on the source node after a migration).
        # NOTE(lbeliveau): On resize on the same node, the instance is
        # included in both tracked_migrations and tracked_instances.
        elif instance['uuid'] in self.tracked_instances:
            self.tracked_instances.remove(instance['uuid'])

        if instance_type is not None:
            numa_topology = self._get_migration_context_resource(
                'numa_topology', instance, prefix=prefix)
            usage = self._get_usage_dict(
                    instance_type, instance, numa_topology=numa_topology)
            self._drop_pci_devices(instance, nodename, prefix)
            resources = self._get_migration_context_resource(
                'resources', instance, prefix=prefix)
            self._release_assigned_resources(resources)
            self._update_usage(usage, nodename, sign=-1)

            ctxt = context.elevated()
            self._update(ctxt, self.compute_nodes[nodename])

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
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
        :returns: True if a new compute_nodes table record was created,
            False otherwise
        """
        nodename = resources['hypervisor_hostname']

        # if there is already a compute node just use resources
        # to initialize
        if nodename in self.compute_nodes:
            cn = self.compute_nodes[nodename]
            self._copy_resources(cn, resources)
            self._setup_pci_tracker(context, cn, resources)
            return False

        # now try to get the compute node record from the
        # database. If we get one we use resources to initialize
        cn = self._get_compute_node(context, nodename)
        if cn:
            self.compute_nodes[nodename] = cn
            self._copy_resources(cn, resources)
            self._setup_pci_tracker(context, cn, resources)
            return False

        if self._check_for_nodes_rebalance(context, resources, nodename):
            return False

        # there was no local copy and none in the database
        # so we need to create a new compute node. This needs
        # to be initialized with resource values.
        cn = objects.ComputeNode(context)
        cn.host = self.host
        self._copy_resources(cn, resources, initial=True)
        cn.create()
        # Only map the ComputeNode into compute_nodes if create() was OK
        # because if create() fails, on the next run through here nodename
        # would be in compute_nodes and we won't try to create again (because
        # of the logic above).
        self.compute_nodes[nodename] = cn
        LOG.info('Compute node record created for '
                 '%(host)s:%(node)s with uuid: %(uuid)s',
                 {'host': self.host, 'node': nodename, 'uuid': cn.uuid})

        self._setup_pci_tracker(context, cn, resources)
        return True

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

    def _copy_resources(self, compute_node, resources, initial=False):
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
        # but only if the configured values are not the default; the
        # ComputeNode._from_db_object method takes care of providing default
        # allocation ratios when the config is left at the default, so
        # we'll really end up with something like a
        # ComputeNode.cpu_allocation_ratio of 16.0. We want to avoid
        # resetting the ComputeNode fields to None because that will make
        # the _resource_change method think something changed when really it
        # didn't.
        # NOTE(yikun): The CONF.initial_(cpu|ram|disk)_allocation_ratio would
        # be used when we initialize the compute node object, that means the
        # ComputeNode.(cpu|ram|disk)_allocation_ratio will be set to
        # CONF.initial_(cpu|ram|disk)_allocation_ratio when initial flag is
        # True.
        for res in ('cpu', 'disk', 'ram'):
            attr = '%s_allocation_ratio' % res
            if initial:
                conf_alloc_ratio = getattr(CONF, 'initial_%s' % attr)
            else:
                conf_alloc_ratio = getattr(self, attr)
            # NOTE(yikun): In Stein version, we change the default value of
            # (cpu|ram|disk)_allocation_ratio from 0.0 to None, but we still
            # should allow 0.0 to keep compatibility, and this 0.0 condition
            # will be removed in the next version (T version).
            if conf_alloc_ratio not in (0.0, None):
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

    def update_available_resource(self, context, nodename, startup=False):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.

        :param nodename: Temporary parameter representing the Ironic resource
                         node. This parameter will be removed once Ironic
                         baremetal resource nodes are handled like any other
                         resource in the system.
        :param startup: Boolean indicating whether we're running this on
                        on startup (True) or periodic (False).
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

        self._update_available_resource(context, resources, startup=startup)

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

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def _update_available_resource(self, context, resources, startup=False):

        # initialize the compute node object, creating it
        # if it does not already exist.
        is_new_compute_node = self._init_compute_node(context, resources)

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
                            'flavor', 'migration_context',
                            'resources'])

        # Now calculate usage based on instance utilization:
        instance_by_uuid = self._update_usage_from_instances(
            context, instances, nodename)

        # Grab all in-progress migrations and error migrations:
        migrations = objects.MigrationList.get_in_progress_and_error(
            context, self.host, nodename)

        self._pair_instances_to_migrations(migrations, instance_by_uuid)
        self._update_usage_from_migrations(context, migrations, nodename)

        # A new compute node means there won't be a resource provider yet since
        # that would be created via the _update() call below, and if there is
        # no resource provider then there are no allocations against it.
        if not is_new_compute_node:
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

        # Update assigned resources to self.assigned_resources
        self._populate_assigned_resources(context, instance_by_uuid)

        # update the compute_node
        self._update(context, cn, startup=startup)
        LOG.debug('Compute_service record updated for %(host)s:%(node)s',
                  {'host': self.host, 'node': nodename})

        # Check if there is any resource assigned but not found
        # in provider tree
        if startup:
            self._check_resources(context)

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
        LOG.debug("Final resource view: "
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

    def _sync_compute_service_disabled_trait(self, context, traits):
        """Synchronize the COMPUTE_STATUS_DISABLED trait on the node provider.

        Determines if the COMPUTE_STATUS_DISABLED trait should be added to
        or removed from the provider's set of traits based on the related
        nova-compute service disabled status.

        :param context: RequestContext for cell database access
        :param traits: set of traits for the compute node resource provider;
            this is modified by reference
        """
        trait = os_traits.COMPUTE_STATUS_DISABLED
        try:
            service = objects.Service.get_by_compute_host(context, self.host)
            if service.disabled:
                # The service is disabled so make sure the trait is reported.
                traits.add(trait)
            else:
                # The service is not disabled so do not report the trait.
                traits.discard(trait)
        except exception.NotFound:
            # This should not happen but handle it gracefully. The scheduler
            # should ignore this node if the compute service record is gone.
            LOG.error('Unable to find services table record for nova-compute '
                      'host %s', self.host)

    def _get_traits(self, context, nodename, provider_tree):
        """Synchronizes internal and external traits for the node provider.

        This works in conjunction with the ComptueDriver.update_provider_tree
        flow and is used to synchronize traits reported by the compute driver,
        traits based on information in the ComputeNode record, and traits set
        externally using the placement REST API.

        :param context: RequestContext for cell database access
        :param nodename: ComputeNode.hypervisor_hostname for the compute node
            resource provider whose traits are being synchronized; the node
            must be in the ProviderTree.
        :param provider_tree: ProviderTree being updated
        """
        # Get the traits from the ProviderTree which will be the set
        # of virt-owned traits plus any externally defined traits set
        # on the provider that aren't owned by the virt driver.
        traits = provider_tree.data(nodename).traits

        # Now get the driver's capabilities and add any supported
        # traits that are missing, and remove any existing set traits
        # that are not currently supported.
        for trait, supported in self.driver.capabilities_as_traits().items():
            if supported:
                traits.add(trait)
            elif trait in traits:
                traits.remove(trait)

        # Always mark the compute node. This lets other processes (possibly
        # unrelated to nova or even OpenStack) find and distinguish these
        # providers easily.
        traits.add(os_traits.COMPUTE_NODE)

        self._sync_compute_service_disabled_trait(context, traits)

        return list(traits)

    @retrying.retry(stop_max_attempt_number=4,
                    retry_on_exception=lambda e: isinstance(
                        e, exception.ResourceProviderUpdateConflict))
    def _update_to_placement(self, context, compute_node, startup):
        """Send resource and inventory changes to placement."""
        # NOTE(jianghuaw): Some resources(e.g. VGPU) are not saved in the
        # object of compute_node; instead the inventory data for these
        # resource is reported by driver's update_provider_tree(). So even if
        # there is no resource change for compute_node, we need proceed
        # to get inventory and use report client interfaces to update
        # inventory to placement. It's report client's responsibility to
        # ensure the update request to placement only happens when inventory
        # is changed.
        nodename = compute_node.hypervisor_hostname
        # Persist the stats to the Scheduler
        # Retrieve the provider tree associated with this compute node.  If
        # it doesn't exist yet, this will create it with a (single, root)
        # provider corresponding to the compute node.
        prov_tree = self.reportclient.get_provider_tree_and_ensure_root(
            context, compute_node.uuid, name=compute_node.hypervisor_hostname)
        # Let the virt driver rearrange the provider tree and set/update
        # the inventory, traits, and aggregates throughout.
        allocs = None
        try:
            self.driver.update_provider_tree(prov_tree, nodename)
        except exception.ReshapeNeeded:
            if not startup:
                # This isn't supposed to happen during periodic, so raise
                # it up; the compute manager will treat it specially.
                raise
            LOG.info("Performing resource provider inventory and "
                     "allocation data migration during compute service "
                     "startup or fast-forward upgrade.")
            allocs = self.reportclient.get_allocations_for_provider_tree(
                context, nodename)
            self.driver.update_provider_tree(prov_tree, nodename,
                                             allocations=allocs)

        # Inject driver capabilities traits into the provider
        # tree.  We need to determine the traits that the virt
        # driver owns - so those that come from the tree itself
        # (via the virt driver) plus the compute capabilities
        # traits, and then merge those with the traits set
        # externally that the driver does not own - and remove any
        # set on the provider externally that the virt owns but
        # aren't in the current list of supported traits.  For
        # example, let's say we reported multiattach support as a
        # trait at t1 and then at t2 it's not, so we need to
        # remove it.  But at both t1 and t2 there is a
        # CUSTOM_VENDOR_TRAIT_X which we can't touch because it
        # was set externally on the provider.
        # We also want to sync the COMPUTE_STATUS_DISABLED trait based
        # on the related nova-compute service's disabled status.
        traits = self._get_traits(
            context, nodename, provider_tree=prov_tree)
        prov_tree.update_traits(nodename, traits)

        self.provider_tree = prov_tree

        # This merges in changes from the provider config files loaded in init
        self._merge_provider_configs(self.provider_configs, prov_tree)

        # Flush any changes. If we processed ReshapeNeeded above, allocs is not
        # None, and this will hit placement's POST /reshaper route.
        self.reportclient.update_from_provider_tree(context, prov_tree,
                                                    allocations=allocs)

    def _update(self, context, compute_node, startup=False):
        """Update partial stats locally and populate them to Scheduler."""
        # _resource_change will update self.old_resources if it detects changes
        # but we want to restore those if compute_node.save() fails.
        nodename = compute_node.hypervisor_hostname
        old_compute = self.old_resources[nodename]
        if self._resource_change(compute_node):
            # If the compute_node's resource changed, update to DB. Note that
            # _update_to_placement below does not supersede the need to do this
            # because there are stats-related fields in the ComputeNode object
            # which could have changed and still need to be reported to the
            # scheduler filters/weighers (which could be out of tree as well).
            try:
                compute_node.save()
            except Exception:
                # Restore the previous state in self.old_resources so that on
                # the next trip through here _resource_change does not have
                # stale data to compare.
                with excutils.save_and_reraise_exception(logger=LOG):
                    self.old_resources[nodename] = old_compute

        self._update_to_placement(context, compute_node, startup)

        if self.pci_tracker:
            self.pci_tracker.save(context)

    def _update_usage(self, usage, nodename, sign=1):
        # TODO(stephenfin): We don't use the CPU, RAM and disk fields for much
        # except 'Aggregate(Core|Ram|Disk)Filter', the 'os-hypervisors' API,
        # and perhaps some out-of-tree filters. Once the in-tree stuff is
        # removed or updated to use information from placement, we can think
        # about dropping the fields from the 'ComputeNode' object entirely
        mem_usage = usage['memory_mb']
        disk_usage = usage.get('root_gb', 0)
        vcpus_usage = usage.get('vcpus', 0)

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

        # calculate the NUMA usage, assuming the instance is actually using
        # NUMA, of course
        if cn.numa_topology and usage.get('numa_topology'):
            instance_numa_topology = usage.get('numa_topology')
            # the ComputeNode.numa_topology field is a StringField, so
            # deserialize
            host_numa_topology = objects.NUMATopology.obj_from_db_obj(
                cn.numa_topology)

            free = sign == -1

            # ...and reserialize once we save it back
            cn.numa_topology = hardware.numa_usage_from_instance_numa(
                host_numa_topology, instance_numa_topology, free)._to_json()

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
        uuid = migration.instance_uuid
        LOG.info("Updating resource usage from migration %s", migration.uuid,
                 instance_uuid=uuid)

        incoming = (migration.dest_compute == self.host and
                    migration.dest_node == nodename)
        outbound = (migration.source_compute == self.host and
                    migration.source_node == nodename)
        same_node = (incoming and outbound)

        tracked = uuid in self.tracked_instances
        itype = None
        numa_topology = None
        sign = 0
        if same_node:
            # Same node resize. Record usage for the 'new_' resources.  This
            # is executed on resize_claim().
            if (instance['instance_type_id'] ==
                    migration.old_instance_type_id):
                itype = self._get_instance_type(instance, 'new_', migration)
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
                itype = self._get_instance_type(instance, 'old_', migration)
                numa_topology = self._get_migration_context_resource(
                    'numa_topology', instance, prefix='old_')

        elif incoming and not tracked:
            # instance has not yet migrated here:
            itype = self._get_instance_type(instance, 'new_', migration)
            numa_topology = self._get_migration_context_resource(
                'numa_topology', instance)
            # Allocate pci device(s) for the instance.
            sign = 1
            LOG.debug('Starting to track incoming migration %s with flavor %s',
                      migration.uuid, itype.flavorid, instance=instance)

        elif outbound and not tracked:
            # instance migrated, but record usage for a possible revert:
            itype = self._get_instance_type(instance, 'old_', migration)
            numa_topology = self._get_migration_context_resource(
                'numa_topology', instance, prefix='old_')
            # We could be racing with confirm_resize setting the
            # instance.old_flavor field to None before the migration status
            # is "confirmed" so if we did not find the flavor in the outgoing
            # resized instance we won't track it.
            if itype:
                LOG.debug('Starting to track outgoing migration %s with '
                          'flavor %s', migration.uuid, itype.flavorid,
                          instance=instance)

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
                    # Track migrating instance even if it is deleted but still
                    # has database record. This kind of instance might be
                    # deleted during unfinished migrating but exist in the
                    # hypervisor.
                    migration._context = context.elevated(read_deleted='yes')
                    instances[uuid] = migration.instance
            except exception.InstanceNotFound as e:
                # migration referencing deleted instance
                LOG.debug('Migration instance not found: %s', e)
                continue

            # Skip migation if instance is neither in a resize state nor is
            # live-migrating.
            if (not _instance_in_resize_state(instances[uuid]) and not
                    _instance_is_live_migrating(instances[uuid])):
                LOG.debug('Skipping migration as instance is neither '
                          'resizing nor live-migrating.', instance_uuid=uuid)
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
            is_removed=False):
        """Update usage for a single instance."""

        uuid = instance['uuid']
        is_new_instance = uuid not in self.tracked_instances
        # NOTE(sfinucan): Both brand new instances as well as instances that
        # are being unshelved will have is_new_instance == True
        is_removed_instance = not is_new_instance and (is_removed or
            instance['vm_state'] in vm_states.ALLOW_RESOURCE_REMOVAL)

        if is_new_instance:
            self.tracked_instances.add(uuid)
            sign = 1

        if is_removed_instance:
            self.tracked_instances.remove(uuid)
            self._release_assigned_resources(instance.resources)
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

        instance_by_uuid = {}
        for instance in instances:
            if instance.vm_state not in vm_states.ALLOW_RESOURCE_REMOVAL:
                self._update_usage_from_instance(context, instance, nodename)
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
        try:
            # pai: report.ProviderAllocInfo namedtuple
            pai = self.reportclient.get_allocations_for_resource_provider(
                context, cn.uuid)
        except (exception.ResourceProviderAllocationRetrievalFailed,
                ks_exc.ClientException) as e:
            LOG.error("Skipping removal of allocations for deleted instances: "
                      "%s", e)
            return
        allocations = pai.allocations
        if not allocations:
            # The main loop below would short-circuit anyway, but this saves us
            # the (potentially expensive) context.elevated construction below.
            return
        read_deleted_context = context.elevated(read_deleted='yes')
        for consumer_uuid, alloc in allocations.items():
            if consumer_uuid in self.tracked_instances:
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

            # NOTE(mriedem): A cross-cell migration will work with instance
            # records across two cells once the migration is confirmed/reverted
            # one of them will be deleted but the instance still exists in the
            # other cell. Before the instance is destroyed from the old cell
            # though it is marked hidden=True so if we find a deleted hidden
            # instance with allocations against this compute node we just
            # ignore it since the migration operation will handle cleaning up
            # those allocations.
            if instance.deleted and not instance.hidden:
                # The instance is gone, so we definitely want to remove
                # allocations associated with it.
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
                # not in the list of actively managed instances. This could be
                # because we are racing with an instance_claim call during
                # initial build or unshelve where the instance host/node is set
                # before the instance is added to tracked_instances. If the
                # task_state is set, then consider things in motion and log at
                # debug level instead of warning.
                if instance.task_state:
                    LOG.debug('Instance with task_state "%s" is not being '
                              'actively managed by this compute host but has '
                              'allocations referencing this compute node '
                              '(%s): %s. Skipping heal of allocations during '
                              'the task state transition.',
                              instance.task_state, cn.uuid, alloc,
                              instance=instance)
                else:
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
        # Clean up the instance allocation from this node in placement
        cn_uuid = self.compute_nodes[node].uuid
        if not self.reportclient.remove_provider_tree_from_instance_allocation(
                context, instance.uuid, cn_uuid):
            LOG.error("Failed to clean allocation of evacuated "
                      "instance on the %s node %s",
                      node_type, cn_uuid, instance=instance)

    def _find_orphaned_instances(self):
        """Given the set of instances and migrations already account for
        by resource tracker, sanity check the hypervisor to determine
        if there are any "orphaned" instances left hanging around.

        Orphans could be consuming memory and should be accounted for in
        usage calculations to guard against potential out of memory
        errors.
        """
        uuids1 = frozenset(self.tracked_instances)
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

    def _get_instance_type(self, instance, prefix, migration):
        """Get the instance type from instance."""
        if migration.is_resize:
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

    def _merge_provider_configs(self, provider_configs, provider_tree):
        """Takes a provider tree and merges any provider configs. Any
        providers in the update that are not present in the tree are logged
        and ignored. Providers identified by both $COMPUTE_NODE and explicit
        UUID/NAME will only be updated with the additional inventories and
        traits in the explicit provider config entry.

        :param provider_configs: The provider configs to merge
        :param provider_tree: The provider tree to be updated in place
        """
        processed_providers = {}
        provider_custom_traits = {}
        for uuid_or_name, provider_data in provider_configs.items():
            additional_traits = provider_data.get(
                "traits", {}).get("additional", [])
            additional_inventories = provider_data.get(
                "inventories", {}).get("additional", [])

            # This is just used to make log entries more useful
            source_file_name = provider_data['__source_file']

            # In most cases this will contain a single provider except in
            # the case of UUID=$COMPUTE_NODE, it may contain multiple.
            providers_to_update = self._get_providers_to_update(
                uuid_or_name, provider_tree, source_file_name)

            for provider in providers_to_update:
                # $COMPUTE_NODE is used to define a "default" rule to apply
                # to all your compute nodes, but then override it for
                # specific ones.
                #
                # If this is for UUID=$COMPUTE_NODE, check if provider is also
                # explicitly identified. If it is, skip updating it with the
                # $COMPUTE_NODE entry data.
                if uuid_or_name == "$COMPUTE_NODE":
                    if any(_pid in provider_configs
                           for _pid in [provider.name, provider.uuid]):
                        continue

                # for each provider specified by name or uuid check that
                # we have not already processed it to prevent duplicate
                # declarations of the same provider.
                current_uuid = provider.uuid
                if current_uuid in processed_providers:
                    raise ValueError(_(
                        "Provider config '%(source_file_name)s' conflicts "
                        "with provider config '%(processed_providers)s'. "
                        "The same provider is specified using both name "
                        "'%(uuid_or_name)s' and uuid '%(current_uuid)s'.") % {
                            'source_file_name': source_file_name,
                            'processed_providers':
                                processed_providers[current_uuid],
                            'uuid_or_name': uuid_or_name,
                            'current_uuid': current_uuid
                        }
                    )

                # NOTE(sean-k-mooney): since each provider should be processed
                # at most once if a provider has custom traits they were
                # set either in previous iteration, the virt driver or via the
                # the placement api. As a result we must ignore them when
                # checking for duplicate traits so we construct a set of the
                # existing custom traits.
                if current_uuid not in provider_custom_traits:
                    provider_custom_traits[current_uuid] = {
                        trait for trait in provider.traits
                        if trait.startswith('CUSTOM')
                    }
                existing_custom_traits = provider_custom_traits[current_uuid]

                if additional_traits:
                    intersect = set(provider.traits) & set(additional_traits)
                    intersect -= existing_custom_traits
                    if intersect:
                        invalid = ','.join(intersect)
                        raise ValueError(_(
                            "Provider config '%(source_file_name)s' attempts "
                            "to define a trait that is owned by the "
                            "virt driver or specified via the placment api. "
                            "Invalid traits '%(invalid)s' must be removed "
                            "from '%(source_file_name)s'.") % {
                                'source_file_name': source_file_name,
                                'invalid': invalid
                            }
                        )
                    provider_tree.add_traits(provider.uuid, *additional_traits)

                if additional_inventories:
                    merged_inventory = provider.inventory
                    intersect = (merged_inventory.keys() &
                                 {rc for inv_dict in additional_inventories
                                  for rc in inv_dict})
                    if intersect:
                        raise ValueError(_(
                            "Provider config '%(source_file_name)s' attempts "
                            "to define an inventory that is owned by the "
                            "virt driver. Invalid inventories '%(invalid)s' "
                            "must be removed from '%(source_file_name)s'.") % {
                                'source_file_name': source_file_name,
                                'invalid': ','.join(intersect)
                            }
                        )
                    for inventory in additional_inventories:
                        merged_inventory.update(inventory)

                    provider_tree.update_inventory(
                        provider.uuid, merged_inventory)

                processed_providers[current_uuid] = source_file_name

    def _get_providers_to_update(self, uuid_or_name, provider_tree,
                                 source_file):
        """Identifies the providers to be updated.
        Intended only to be consumed by _merge_provider_configs()

        :param provider: Provider config data
        :param provider_tree: Provider tree to get providers from
        :param source_file: Provider config file containing the inventories

        :returns: list of ProviderData
        """
        # $COMPUTE_NODE is used to define a "default" rule to apply
        # to all your compute nodes, but then override it for
        # specific ones.
        if uuid_or_name == "$COMPUTE_NODE":
            return [root.data() for root in provider_tree.roots
                    if os_traits.COMPUTE_NODE in root.traits]

        try:
            providers_to_update = [provider_tree.data(uuid_or_name)]
            # Remove the provider from absent provider list if present
            # so we can re-warn if the provider disappears again later
            self.absent_providers.discard(uuid_or_name)
        except ValueError:
            providers_to_update = []
            if uuid_or_name not in self.absent_providers:
                LOG.warning(
                    "Provider '%(uuid_or_name)s' specified in provider "
                    "config file '%(source_file)s' does not exist in the "
                    "ProviderTree and will be ignored.",
                    {"uuid_or_name": uuid_or_name,
                     "source_file": source_file})
                self.absent_providers.add(uuid_or_name)

        return providers_to_update

    def build_failed(self, nodename):
        """Increments the failed_builds stats for the given node."""
        self.stats[nodename].build_failed()

    def build_succeeded(self, nodename):
        """Resets the failed_builds stats for the given node."""
        self.stats[nodename].build_succeeded()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def claim_pci_devices(
        self, context, pci_requests, instance_numa_topology=None
    ):
        """Claim instance PCI resources

        :param context: security context
        :param pci_requests: a list of nova.objects.InstancePCIRequests
        :param instance_numa_topology: an InstanceNumaTopology object used to
            ensure PCI devices are aligned with the NUMA topology of the
            instance
        :returns: a list of nova.objects.PciDevice objects
        """
        result = self.pci_tracker.claim_instance(
            context, pci_requests, instance_numa_topology)
        self.pci_tracker.save(context)
        return result

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def unclaim_pci_devices(self, context, pci_device, instance):
        """Deallocate PCI devices

        :param context: security context
        :param pci_device: the objects.PciDevice describing the PCI device to
            be freed
        :param instance: the objects.Instance the PCI resources are freed from
        """
        self.pci_tracker.free_device(pci_device, instance)
        self.pci_tracker.save(context)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def allocate_pci_devices_for_instance(self, context, instance):
        """Allocate instance claimed PCI resources

        :param context: security context
        :param instance: instance object
        """
        self.pci_tracker.allocate_instance(instance)
        self.pci_tracker.save(context)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def free_pci_device_allocations_for_instance(self, context, instance):
        """Free instance allocated PCI resources

        :param context: security context
        :param instance: instance object
        """
        self.pci_tracker.free_instance_allocations(context, instance)
        self.pci_tracker.save(context)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def free_pci_device_claims_for_instance(self, context, instance):
        """Free instance claimed PCI resources

        :param context: security context
        :param instance: instance object
        """
        self.pci_tracker.free_instance_claims(context, instance)
        self.pci_tracker.save(context)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, fair=True)
    def finish_evacuation(self, instance, node, migration):
        instance.apply_migration_context()
        # NOTE (ndipanov): This save will now update the host and node
        # attributes making sure that next RT pass is consistent since
        # it will be based on the instance and not the migration DB
        # entry.
        instance.host = self.host
        instance.node = node
        instance.save()
        instance.drop_migration_context()

        # NOTE (ndipanov): Mark the migration as done only after we
        # mark the instance as belonging to this host.
        if migration:
            migration.status = 'done'
            migration.save()
