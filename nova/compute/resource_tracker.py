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

from oslo.config import cfg

from nova.compute import claims
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
from nova import conductor
from nova import context
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.objects import migration as migration_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.pci import pci_manager
from nova import utils

resource_tracker_opts = [
    cfg.IntOpt('reserved_host_disk_mb', default=0,
               help='Amount of disk in MB to reserve for the host'),
    cfg.IntOpt('reserved_host_memory_mb', default=512,
               help='Amount of memory in MB to reserve for the host'),
    cfg.StrOpt('compute_stats_class',
               default='nova.compute.stats.Stats',
               help='Class that will manage stats for the local compute host')
]

CONF = cfg.CONF
CONF.register_opts(resource_tracker_opts)

LOG = logging.getLogger(__name__)
COMPUTE_RESOURCE_SEMAPHORE = "compute_resources"

CONF.import_opt('my_ip', 'nova.netconf')


class ResourceTracker(object):
    """Compute helper class for keeping track of resource usage as instances
    are built and destroyed.
    """

    def __init__(self, host, driver, nodename):
        self.host = host
        self.driver = driver
        self.pci_tracker = None
        self.nodename = nodename
        self.compute_node = None
        self.stats = importutils.import_object(CONF.compute_stats_class)
        self.tracked_instances = {}
        self.tracked_migrations = {}
        self.conductor_api = conductor.API()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def instance_claim(self, context, instance_ref, limits=None):
        """Indicate that some resources are needed for an upcoming compute
        instance build operation.

        This should be called before the compute node is about to perform
        an instance build operation that will consume additional resources.

        :param context: security context
        :param instance_ref: instance to reserve resources for
        :param limits: Dict of oversubscription limits for memory, disk,
                       and CPUs.
        :returns: A Claim ticket representing the reserved resources.  It can
                  be used to revert the resource usage if an error occurs
                  during the instance build.
        """
        if self.disabled:
            # compute_driver doesn't support resource tracking, just
            # set the 'host' and node fields and continue the build:
            self._set_instance_host_and_node(context, instance_ref)
            return claims.NopClaim()

        # sanity checks:
        if instance_ref['host']:
            LOG.warning(_("Host field should not be set on the instance until "
                          "resources have been claimed."),
                          instance=instance_ref)

        if instance_ref['node']:
            LOG.warning(_("Node field should not be set on the instance "
                          "until resources have been claimed."),
                          instance=instance_ref)

        # get memory overhead required to build this instance:
        overhead = self.driver.estimate_instance_overhead(instance_ref)
        LOG.debug(_("Memory overhead for %(flavor)d MB instance; %(overhead)d "
                    "MB"), {'flavor': instance_ref['memory_mb'],
                            'overhead': overhead['memory_mb']})

        claim = claims.Claim(instance_ref, self, overhead=overhead)

        if claim.test(self.compute_node, limits):

            self._set_instance_host_and_node(context, instance_ref)

            # Mark resources in-use and update stats
            self._update_usage_from_instance(self.compute_node, instance_ref)

            # persist changes to the compute node:
            self._update(context, self.compute_node)

            return claim

        else:
            raise exception.ComputeResourcesUnavailable()

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def resize_claim(self, context, instance, instance_type, limits=None):
        """Indicate that resources are needed for a resize operation to this
        compute host.
        :param context: security context
        :param instance: instance object to reserve resources for
        :param instance_type: new instance_type being resized to
        :param limits: Dict of oversubscription limits for memory, disk,
                       and CPUs.
        :returns: A Claim ticket representing the reserved resources.  This
                  should be turned into finalize  a resource claim or free
                  resources after the compute operation is finished.
        """
        if self.disabled:
            # compute_driver doesn't support resource tracking, just
            # generate the migration record and continue the resize:
            migration = self._create_migration(context, instance,
                                               instance_type)
            return claims.NopClaim(migration=migration)

        # get memory overhead required to build this instance:
        overhead = self.driver.estimate_instance_overhead(instance_type)
        LOG.debug(_("Memory overhead for %(flavor)d MB instance; %(overhead)d "
                    "MB"), {'flavor': instance_type['memory_mb'],
                            'overhead': overhead['memory_mb']})

        instance_ref = obj_base.obj_to_primitive(instance)
        claim = claims.ResizeClaim(instance_ref, instance_type, self,
                                   overhead=overhead)

        if claim.test(self.compute_node, limits):

            migration = self._create_migration(context, instance_ref,
                                               instance_type)
            claim.migration = migration

            # Mark the resources in-use for the resize landing on this
            # compute host:
            self._update_usage_from_migration(context, instance_ref,
                                              self.compute_node, migration)
            elevated = context.elevated()
            self._update(elevated, self.compute_node)

            return claim

        else:
            raise exception.ComputeResourcesUnavailable()

    def _create_migration(self, context, instance, instance_type):
        """Create a migration record for the upcoming resize.  This should
        be done while the COMPUTE_RESOURCES_SEMAPHORE is held so the resource
        claim will not be lost if the audit process starts.
        """
        old_instance_type = flavors.extract_flavor(instance)
        migration = migration_obj.Migration()
        migration.dest_compute = self.host
        migration.dest_node = self.nodename
        migration.dest_host = self.driver.get_host_ip_addr()
        migration.old_instance_type_id = old_instance_type['id']
        migration.new_instance_type_id = instance_type['id']
        migration.status = 'pre-migrating'
        migration.instance_uuid = instance['uuid']
        migration.source_compute = instance['host']
        migration.source_node = instance['node']
        migration.create(context.elevated())
        return migration

    def _set_instance_host_and_node(self, context, instance_ref):
        """Tag the instance as belonging to this host.  This should be done
        while the COMPUTE_RESOURCES_SEMPAHORE is held so the resource claim
        will not be lost if the audit process starts.
        """
        values = {'host': self.host, 'node': self.nodename,
                  'launched_on': self.host}
        self.conductor_api.instance_update(context, instance_ref['uuid'],
                                           **values)
        instance_ref['host'] = self.host
        instance_ref['launched_on'] = self.host
        instance_ref['node'] = self.nodename

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def abort_instance_claim(self, instance):
        """Remove usage from the given instance."""
        # flag the instance as deleted to revert the resource usage
        # and associated stats:
        instance['vm_state'] = vm_states.DELETED
        self._update_usage_from_instance(self.compute_node, instance)

        ctxt = context.get_admin_context()
        self._update(ctxt, self.compute_node)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def drop_resize_claim(self, instance, instance_type=None, prefix='new_'):
        """Remove usage for an incoming/outgoing migration."""
        if instance['uuid'] in self.tracked_migrations:
            migration, itype = self.tracked_migrations.pop(instance['uuid'])

            if not instance_type:
                ctxt = context.get_admin_context()
                instance_type = self._get_instance_type(ctxt, instance, prefix)

            if instance_type['id'] == itype['id']:
                self.stats.update_stats_for_migration(itype, sign=-1)
                if self.pci_tracker:
                    self.pci_tracker.update_pci_for_migration(instance,
                                                              sign=-1)
                self._update_usage(self.compute_node, itype, sign=-1)
                self.compute_node['stats'] = self.stats

                ctxt = context.get_admin_context()
                self._update(ctxt, self.compute_node)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_usage(self, context, instance):
        """Update the resource usage and stats after a change in an
        instance
        """
        if self.disabled:
            return

        uuid = instance['uuid']

        # don't update usage for this instance unless it submitted a resource
        # claim first:
        if uuid in self.tracked_instances:
            self._update_usage_from_instance(self.compute_node, instance)
            self._update(context.elevated(), self.compute_node)

    @property
    def disabled(self):
        return self.compute_node is None

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_available_resource(self, context):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.
        """
        LOG.audit(_("Auditing locally available compute resources"))
        resources = self.driver.get_available_resource(self.nodename)

        if not resources:
            # The virt driver does not support this function
            LOG.audit(_("Virt driver does not support "
                 "'get_available_resource'  Compute tracking is disabled."))
            self.compute_node = None
            return
        resources['host_ip'] = CONF.my_ip

        self._verify_resources(resources)

        self._report_hypervisor_resource_view(resources)

        if 'pci_passthrough_devices' in resources:
            if not self.pci_tracker:
                self.pci_tracker = pci_manager.PciDevTracker()
            self.pci_tracker.set_hvdevs(jsonutils.loads(resources.pop(
                'pci_passthrough_devices')))

        # Grab all instances assigned to this node:
        instances = instance_obj.InstanceList.get_by_host_and_node(
            context, self.host, self.nodename)

        # Now calculate usage based on instance utilization:
        self._update_usage_from_instances(resources, instances)

        # Grab all in-progress migrations:
        capi = self.conductor_api
        migrations = capi.migration_get_in_progress_by_host_and_node(context,
                self.host, self.nodename)

        self._update_usage_from_migrations(context, resources, migrations)

        # Detect and account for orphaned instances that may exist on the
        # hypervisor, but are not in the DB:
        orphans = self._find_orphaned_instances()
        self._update_usage_from_orphans(resources, orphans)

        # NOTE(yjiang5): Because pci device tracker status is not cleared in
        # this periodic task, and also because the resource tracker is not
        # notified when instances are deleted, we need remove all usages
        # from deleted instances.
        if self.pci_tracker:
            self.pci_tracker.clean_usage(instances, migrations, orphans)
            resources['pci_stats'] = jsonutils.dumps(self.pci_tracker.stats)
        else:
            resources['pci_stats'] = jsonutils.dumps({})

        self._report_final_resource_view(resources)

        self._sync_compute_node(context, resources)

    def _sync_compute_node(self, context, resources):
        """Create or update the compute node DB record."""
        if not self.compute_node:
            # we need a copy of the ComputeNode record:
            service = self._get_service(context)
            if not service:
                # no service record, disable resource
                return

            compute_node_refs = service['compute_node']
            if compute_node_refs:
                for cn in compute_node_refs:
                    if cn.get('hypervisor_hostname') == self.nodename:
                        self.compute_node = cn
                        if self.pci_tracker:
                            self.pci_tracker.set_compute_node_id(cn['id'])
                        break

        if not self.compute_node:
            # Need to create the ComputeNode record:
            resources['service_id'] = service['id']
            self._create(context, resources)
            if self.pci_tracker:
                self.pci_tracker.set_compute_node_id(self.compute_node['id'])
            LOG.info(_('Compute_service record created for %(host)s:%(node)s')
                    % {'host': self.host, 'node': self.nodename})

        else:
            # just update the record:
            self._update(context, resources, prune_stats=True)
            LOG.info(_('Compute_service record updated for %(host)s:%(node)s')
                    % {'host': self.host, 'node': self.nodename})

    def _create(self, context, values):
        """Create the compute node in the DB."""
        # initialize load stats from existing instances:
        self.compute_node = self.conductor_api.compute_node_create(context,
                                                                   values)

    def _get_service(self, context):
        try:
            return self.conductor_api.service_get_by_compute_host(context,
                                                                  self.host)
        except exception.NotFound:
            LOG.warn(_("No service record for host %s"), self.host)

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
        free_ram_mb = resources['memory_mb'] - resources['memory_mb_used']
        free_disk_gb = resources['local_gb'] - resources['local_gb_used']

        LOG.debug(_("Hypervisor: free ram (MB): %s") % free_ram_mb)
        LOG.debug(_("Hypervisor: free disk (GB): %s") % free_disk_gb)

        vcpus = resources['vcpus']
        if vcpus:
            free_vcpus = vcpus - resources['vcpus_used']
            LOG.debug(_("Hypervisor: free VCPUs: %s") % free_vcpus)
        else:
            LOG.debug(_("Hypervisor: VCPU information unavailable"))

        if 'pci_passthrough_devices' in resources and \
                resources['pci_passthrough_devices']:
            LOG.debug(_("Hypervisor: assignable PCI devices: %s") %
                resources['pci_passthrough_devices'])
        else:
            LOG.debug(_("Hypervisor: no assignable PCI devices"))

    def _report_final_resource_view(self, resources):
        """Report final calculate of free memory, disk, CPUs, and PCI devices,
        including instance calculations and in-progress resource claims. These
        values will be exposed via the compute node table to the scheduler.
        """
        LOG.audit(_("Free ram (MB): %s") % resources['free_ram_mb'])
        LOG.audit(_("Free disk (GB): %s") % resources['free_disk_gb'])

        vcpus = resources['vcpus']
        if vcpus:
            free_vcpus = vcpus - resources['vcpus_used']
            LOG.audit(_("Free VCPUS: %s") % free_vcpus)
        else:
            LOG.audit(_("Free VCPU information unavailable"))

        if 'pci_devices' in resources:
            LOG.audit(_("Free PCI devices: %s") % resources['pci_devices'])

    def _update(self, context, values, prune_stats=False):
        """Persist the compute node updates to the DB."""
        if "service" in self.compute_node:
            del self.compute_node['service']
        self.compute_node = self.conductor_api.compute_node_update(
            context, self.compute_node, values, prune_stats)
        if self.pci_tracker:
            self.pci_tracker.save(context)

    def _update_usage(self, resources, usage, sign=1):
        mem_usage = usage['memory_mb']

        overhead = self.driver.estimate_instance_overhead(usage)
        mem_usage += overhead['memory_mb']

        resources['memory_mb_used'] += sign * mem_usage
        resources['local_gb_used'] += sign * usage.get('root_gb', 0)
        resources['local_gb_used'] += sign * usage.get('ephemeral_gb', 0)

        # free ram and disk may be negative, depending on policy:
        resources['free_ram_mb'] = (resources['memory_mb'] -
                                    resources['memory_mb_used'])
        resources['free_disk_gb'] = (resources['local_gb'] -
                                     resources['local_gb_used'])

        resources['running_vms'] = self.stats.num_instances
        resources['vcpus_used'] = self.stats.num_vcpus_used

    def _update_usage_from_migration(self, context, instance, resources,
                                     migration):
        """Update usage for a single migration.  The record may
        represent an incoming or outbound migration.
        """
        uuid = migration['instance_uuid']
        LOG.audit(_("Updating from migration %s") % uuid)

        incoming = (migration['dest_compute'] == self.host and
                    migration['dest_node'] == self.nodename)
        outbound = (migration['source_compute'] == self.host and
                    migration['source_node'] == self.nodename)
        same_node = (incoming and outbound)

        record = self.tracked_instances.get(uuid, None)
        itype = None

        if same_node:
            # same node resize. record usage for whichever instance type the
            # instance is *not* in:
            if (instance['instance_type_id'] ==
                    migration['old_instance_type_id']):
                itype = self._get_instance_type(context, instance, 'new_',
                        migration['new_instance_type_id'])
            else:
                # instance record already has new flavor, hold space for a
                # possible revert to the old instance type:
                itype = self._get_instance_type(context, instance, 'old_',
                        migration['old_instance_type_id'])

        elif incoming and not record:
            # instance has not yet migrated here:
            itype = self._get_instance_type(context, instance, 'new_',
                    migration['new_instance_type_id'])

        elif outbound and not record:
            # instance migrated, but record usage for a possible revert:
            itype = self._get_instance_type(context, instance, 'old_',
                    migration['old_instance_type_id'])

        if itype:
            self.stats.update_stats_for_migration(itype)
            if self.pci_tracker:
                self.pci_tracker.update_pci_for_migration(instance)
            self._update_usage(resources, itype)
            resources['stats'] = self.stats
            if self.pci_tracker:
                resources['pci_stats'] = jsonutils.dumps(
                        self.pci_tracker.stats)
            else:
                resources['pci_stats'] = jsonutils.dumps({})
            self.tracked_migrations[uuid] = (migration, itype)

    def _update_usage_from_migrations(self, context, resources, migrations):

        self.tracked_migrations.clear()

        filtered = {}

        # do some defensive filtering against bad migrations records in the
        # database:
        for migration in migrations:

            instance = migration['instance']

            if not instance:
                # migration referencing deleted instance
                continue

            uuid = instance['uuid']

            # skip migration if instance isn't in a resize state:
            if not self._instance_in_resize_state(instance):
                LOG.warn(_("Instance not resizing, skipping migration."),
                         instance_uuid=uuid)
                continue

            # filter to most recently updated migration for each instance:
            m = filtered.get(uuid, None)
            if not m or migration['updated_at'] >= m['updated_at']:
                filtered[uuid] = migration

        for migration in filtered.values():
            instance = migration['instance']
            try:
                self._update_usage_from_migration(context, instance, resources,
                                                  migration)
            except exception.InstanceTypeNotFound:
                LOG.warn(_("InstanceType could not be found, skipping "
                           "migration."), instance_uuid=uuid)
                continue

    def _update_usage_from_instance(self, resources, instance):
        """Update usage for a single instance."""

        uuid = instance['uuid']
        is_new_instance = uuid not in self.tracked_instances
        is_deleted_instance = instance['vm_state'] == vm_states.DELETED

        if is_new_instance:
            self.tracked_instances[uuid] = obj_base.obj_to_primitive(instance)
            sign = 1

        if is_deleted_instance:
            self.tracked_instances.pop(uuid)
            sign = -1

        self.stats.update_stats_for_instance(instance)

        if self.pci_tracker:
            self.pci_tracker.update_pci_for_instance(instance)

        # if it's a new or deleted instance:
        if is_new_instance or is_deleted_instance:
            # new instance, update compute node resource usage:
            self._update_usage(resources, instance, sign=sign)

        resources['current_workload'] = self.stats.calculate_workload()
        resources['stats'] = self.stats
        if self.pci_tracker:
            resources['pci_stats'] = jsonutils.dumps(self.pci_tracker.stats)
        else:
            resources['pci_stats'] = jsonutils.dumps({})

    def _update_usage_from_instances(self, resources, instances):
        """Calculate resource usage based on instance utilization.  This is
        different than the hypervisor's view as it will account for all
        instances assigned to the local compute host, even if they are not
        currently powered on.
        """
        self.tracked_instances.clear()

        # purge old stats
        self.stats.clear()

        # set some intiial values, reserve room for host/hypervisor:
        resources['local_gb_used'] = CONF.reserved_host_disk_mb / 1024
        resources['memory_mb_used'] = CONF.reserved_host_memory_mb
        resources['vcpus_used'] = 0
        resources['free_ram_mb'] = (resources['memory_mb'] -
                                    resources['memory_mb_used'])
        resources['free_disk_gb'] = (resources['local_gb'] -
                                     resources['local_gb_used'])
        resources['current_workload'] = 0
        resources['running_vms'] = 0

        for instance in instances:
            if instance['vm_state'] == vm_states.DELETED:
                continue
            else:
                self._update_usage_from_instance(resources, instance)

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

    def _update_usage_from_orphans(self, resources, orphans):
        """Include orphaned instances in usage."""
        for orphan in orphans:
            memory_mb = orphan['memory_mb']

            LOG.warn(_("Detected running orphan instance: %(uuid)s (consuming "
                       "%(memory_mb)s MB memory)"),
                     {'uuid': orphan['uuid'], 'memory_mb': memory_mb})

            # just record memory usage for the orphan
            usage = {'memory_mb': memory_mb}
            self._update_usage(resources, usage)

    def _verify_resources(self, resources):
        resource_keys = ["vcpus", "memory_mb", "local_gb", "cpu_info",
                         "vcpus_used", "memory_mb_used", "local_gb_used"]

        missing_keys = [k for k in resource_keys if k not in resources]
        if missing_keys:
            reason = _("Missing keys: %s") % missing_keys
            raise exception.InvalidInput(reason=reason)

    def _instance_in_resize_state(self, instance):
        vm = instance['vm_state']
        task = instance['task_state']

        if vm == vm_states.RESIZED:
            return True

        if (vm == vm_states.ACTIVE and task in [task_states.RESIZE_PREP,
                task_states.RESIZE_MIGRATING, task_states.RESIZE_MIGRATED,
                task_states.RESIZE_FINISH]):
            return True

        return False

    def _get_instance_type(self, context, instance, prefix,
            instance_type_id=None):
        """Get the instance type from sys metadata if it's stashed.  If not,
        fall back to fetching it via the conductor API.

        See bug 1164110
        """
        if not instance_type_id:
            instance_type_id = instance['instance_type_id']

        try:
            return flavors.extract_flavor(instance, prefix)
        except KeyError:
            return self.conductor_api.instance_type_get(context,
                    instance_type_id)
