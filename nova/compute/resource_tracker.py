# Copyright (c) 2012 OpenStack, LLC.
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

from nova.compute import claims
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import notifications
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import lockutils
from nova.openstack.common import log as logging
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

FLAGS = flags.FLAGS
FLAGS.register_opts(resource_tracker_opts)

LOG = logging.getLogger(__name__)
COMPUTE_RESOURCE_SEMAPHORE = claims.COMPUTE_RESOURCE_SEMAPHORE


class ResourceTracker(object):
    """Compute helper class for keeping track of resource usage as instances
    are built and destroyed.
    """

    def __init__(self, host, driver, nodename):
        self.host = host
        self.driver = driver
        self.nodename = nodename
        self.compute_node = None
        self.stats = importutils.import_object(FLAGS.compute_stats_class)
        self.tracked_instances = {}

    @lockutils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, 'nova-')
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
            # set the 'host' field and continue the build:
            instance_ref = self._set_instance_host(context,
                    instance_ref['uuid'])
            return claims.NopClaim()

        # sanity check:
        if instance_ref['host']:
            LOG.warning(_("Host field should be not be set on the instance "
                          "until resources have been claimed."),
                          instance=instance_ref)

        claim = claims.Claim(instance_ref, self)

        if claim.test(self.compute_node, limits):

            instance_ref = self._set_instance_host(context,
                    instance_ref['uuid'])

            # Mark resources in-use and update stats
            self._update_usage_from_instance(self.compute_node, instance_ref)

            # persist changes to the compute node:
            self._update(context, self.compute_node)

            return claim

        else:
            raise exception.ComputeResourcesUnavailable()

    def _set_instance_host(self, context, instance_uuid):
        """Tag the instance as belonging to this host.  This should be done
        while the COMPUTE_RESOURCES_SEMPAHORE is being held so the resource
        claim will not be lost if the audit process starts.
        """
        values = {'host': self.host, 'launched_on': self.host}
        (old_ref, instance_ref) = db.instance_update_and_get_original(context,
                instance_uuid, values)
        notifications.send_update(context, old_ref, instance_ref)
        return instance_ref

    def abort_instance_claim(self, instance):
        """Remove usage from the given instance"""
        # flag the instance as deleted to revert the resource usage
        # and associated stats:
        instance['vm_state'] = vm_states.DELETED
        self._update_usage_from_instance(self.compute_node, instance)

        ctxt = context.get_admin_context()
        self._update(ctxt, self.compute_node)

    @lockutils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, 'nova-')
    def update_usage(self, context, instance):
        """Update the resource usage and stats after a change in an
        instance
        """
        if self.disabled:
            return

        # don't update usage for this instance unless it submitted a resource
        # claim first:
        uuid = instance['uuid']
        if uuid in self.tracked_instances:
            self._update_usage_from_instance(self.compute_node, instance)
            self._update(context.elevated(), self.compute_node)

    @property
    def disabled(self):
        return self.compute_node is None

    @lockutils.synchronized(COMPUTE_RESOURCE_SEMAPHORE, 'nova-')
    def update_available_resource(self, context):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.
        """
        resources = self.driver.get_available_resource(self.nodename)
        if not resources:
            # The virt driver does not support this function
            LOG.audit(_("Virt driver does not support "
                "'get_available_resource'  Compute tracking is disabled."))
            self.compute_node = None
            return

        self._verify_resources(resources)

        self._report_hypervisor_resource_view(resources)

        # Grab all instances assigned to this node:
        instances = db.instance_get_all_by_host_and_node(context, self.host,
                                                         self.nodename)

        # Now calculate usage based on instance utilization:
        self._update_usage_from_instances(resources, instances)
        self._report_final_resource_view(resources)

        self._sync_compute_node(context, resources)

    def _sync_compute_node(self, context, resources):
        """Create or update the compute node DB record"""
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
                        break

        if not self.compute_node:
            # Need to create the ComputeNode record:
            resources['service_id'] = service['id']
            self._create(context, resources)
            LOG.info(_('Compute_service record created for %s ') % self.host)

        else:
            # just update the record:
            self._update(context, resources, prune_stats=True)
            LOG.info(_('Compute_service record updated for %s ') % self.host)

    def _create(self, context, values):
        """Create the compute node in the DB"""
        # initialize load stats from existing instances:
        compute_node = db.compute_node_create(context, values)
        self.compute_node = dict(compute_node)

    def _get_service(self, context):
        try:
            return db.service_get_all_compute_by_host(context,
                    self.host)[0]
        except exception.NotFound:
            LOG.warn(_("No service record for host %s"), self.host)

    def _report_hypervisor_resource_view(self, resources):
        """Log the hypervisor's view of free memory in and free disk.
        This is just a snapshot of resource usage recorded by the
        virt driver.
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

    def _report_final_resource_view(self, resources):
        """Report final calculate of free memory and free disk including
        instance calculations and in-progress resource claims.  These
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

    def _update(self, context, values, prune_stats=False):
        """Persist the compute node updates to the DB"""
        compute_node = db.compute_node_update(context,
                self.compute_node['id'], values, prune_stats)
        self.compute_node = dict(compute_node)

    def _update_usage_from_instance(self, resources, instance):
        """Update usage for a single instance."""

        uuid = instance['uuid']
        is_new_instance = uuid not in self.tracked_instances
        is_deleted_instance = instance['vm_state'] == vm_states.DELETED

        if is_new_instance:
            self.tracked_instances[uuid] = 1
            sign = 1

        if is_deleted_instance:
            self.tracked_instances.pop(uuid)
            sign = -1

        self.stats.update_stats_for_instance(instance)

        # if it's a new or deleted instance:
        if is_new_instance or is_deleted_instance:
            # new instance, update compute node resource usage:
            resources['memory_mb_used'] += sign * instance['memory_mb']
            resources['local_gb_used'] += sign * instance['root_gb']
            resources['local_gb_used'] += sign * instance['ephemeral_gb']

            # free ram and disk may be negative, depending on policy:
            resources['free_ram_mb'] = (resources['memory_mb'] -
                                        resources['memory_mb_used'])
            resources['free_disk_gb'] = (resources['local_gb'] -
                                         resources['local_gb_used'])

            resources['running_vms'] = self.stats.num_instances
            resources['vcpus_used'] = self.stats.num_vcpus_used

        resources['current_workload'] = self.stats.calculate_workload()
        resources['stats'] = self.stats

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
        resources['local_gb_used'] = FLAGS.reserved_host_disk_mb / 1024
        resources['memory_mb_used'] = FLAGS.reserved_host_memory_mb
        resources['vcpus_used'] = 0
        resources['free_ram_mb'] = (resources['memory_mb'] -
                                    resources['memory_mb_used'])
        resources['free_disk_gb'] = (resources['local_gb'] -
                                     resources['local_gb_used'])
        resources['current_workload'] = 0
        resources['running_vms'] = 0

        for instance in instances:
            self._update_usage_from_instance(resources, instance)

    def _verify_resources(self, resources):
        resource_keys = ["vcpus", "memory_mb", "local_gb", "cpu_info",
                         "vcpus_used", "memory_mb_used", "local_gb_used"]

        missing_keys = [k for k in resource_keys if k not in resources]
        if missing_keys:
            reason = _("Missing keys: %s") % missing_keys
            raise exception.InvalidInput(reason=reason)
