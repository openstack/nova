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

from nova.compute import vm_states
from nova import db
from nova import exception
from nova import flags
from nova import notifications
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import utils

resource_tracker_opts = [
    cfg.IntOpt('reserved_host_disk_mb', default=0,
               help='Amount of disk in MB to reserve for the host'),
    cfg.IntOpt('reserved_host_memory_mb', default=512,
               help='Amount of memory in MB to reserve for the host'),
    cfg.IntOpt('claim_timeout_seconds', default=600,
               help='How long, in seconds, before a resource claim times out'),
    cfg.StrOpt('compute_stats_class',
               default='nova.compute.stats.Stats',
               help='Class that will manage stats for the local compute host')
]

FLAGS = flags.FLAGS
FLAGS.register_opts(resource_tracker_opts)

LOG = logging.getLogger(__name__)
COMPUTE_RESOURCE_SEMAPHORE = "compute_resources"


class Claim(object):
    """A declaration that a compute host operation will require free resources.

    This information will be used to help keep the local compute hosts's
    ComputeNode model in sync to aid the scheduler in making efficient / more
    correct decisions with respect to host selection.
    """

    def __init__(self, instance, timeout):
        self.instance = jsonutils.to_primitive(instance)
        self.timeout = timeout
        self.expire_ts = timeutils.utcnow_ts() + timeout

    def is_expired(self):
        """Determine if this adjustment is old enough that we can assume it's
        no longer needed.
        """
        return timeutils.utcnow_ts() > self.expire_ts

    @property
    def claim_id(self):
        return self.instance['uuid']

    @property
    def disk_gb(self):
        return self.instance['root_gb'] + self.instance['ephemeral_gb']

    @property
    def memory_mb(self):
        return self.instance['memory_mb']

    @property
    def vcpus(self):
        return self.instance['vcpus']

    def __str__(self):
        return "[Claim %s: %d MB memory, %d GB disk, %d VCPUS]" % \
                    (self.claim_id, self.memory_mb, self.disk_gb, self.vcpus)


class ResourceContextManager(object):
    def __init__(self, context, claim, tracker):
        self.context = context
        self.claim = claim
        self.tracker = tracker

    def __enter__(self):
        if not self.claim and not self.tracker.disabled:
            # insufficient resources to complete request
            raise exception.ComputeResourcesUnavailable()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.claim:
            return

        if exc_type is None:
            self.tracker.finish_resource_claim(self.claim)
        else:
            self.tracker.abort_resource_claim(self.context, self.claim)


class ResourceTracker(object):
    """Compute helper class for keeping track of resource usage as instances
    are built and destroyed.
    """

    def __init__(self, host, driver):
        self.host = host
        self.driver = driver
        self.compute_node = None
        self.next_claim_id = 1
        self.claims = {}
        self.stats = importutils.import_object(FLAGS.compute_stats_class)
        self.tracked_instances = {}

    def resource_claim(self, context, instance_ref, limits=None):
        claim = self.begin_resource_claim(context, instance_ref, limits)
        return ResourceContextManager(context, claim, self)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def begin_resource_claim(self, context, instance_ref, limits=None,
                             timeout=None):
        """Indicate that some resources are needed for an upcoming compute
        instance build operation.

        This should be called before the compute node is about to perform
        an instance build operation that will consume additional resources.

        :param context: security context
        :param instance_ref: instance to reserve resources for
        :param limits: Dict of oversubscription limits for memory, disk,
                       and CPUs.
        :param timeout: How long, in seconds, the operation that requires
                        these resources should take to actually allocate what
                        it needs from the hypervisor.  If the timeout is
                        exceeded, the new resource claim will assume caller
                        before releasing the resources.
        :returns: An integer 'claim ticket'.  This should be turned into
                  finalize  a resource claim or free resources after the
                  compute operation is finished. Returns None if the claim
                  failed.
        """
        if self.disabled:
            # compute_driver doesn't support resource tracking, just
            # set the 'host' field and continue the build:
            self._set_instance_host(context, instance_ref)
            return

        # sanity check:
        if instance_ref['host']:
            LOG.warning(_("Host field should not be set on the instance until "
                          "resources have been claimed."),
                          instance=instance_ref)

        if not limits:
            limits = {}

        if not timeout:
            timeout = FLAGS.claim_timeout_seconds

        # If an individual limit is None, the resource will be considered
        # unlimited:
        memory_mb_limit = limits.get('memory_mb')
        disk_gb_limit = limits.get('disk_gb')
        vcpu_limit = limits.get('vcpu')

        memory_mb = instance_ref['memory_mb']
        disk_gb = instance_ref['root_gb'] + instance_ref['ephemeral_gb']
        vcpus = instance_ref['vcpus']

        msg = _("Attempting claim: memory %(memory_mb)d MB, disk %(disk_gb)d "
                "GB, VCPUs %(vcpus)d") % locals()
        LOG.audit(msg)

        # Test for resources:
        if not self._can_claim_memory(memory_mb, memory_mb_limit):
            return

        if not self._can_claim_disk(disk_gb, disk_gb_limit):
            return

        if not self._can_claim_cpu(vcpus, vcpu_limit):
            return

        self._set_instance_host(context, instance_ref)

        # keep track of this claim until we know whether the compute operation
        # was successful/completed:
        claim = Claim(instance_ref, timeout)
        self.claims[claim.claim_id] = claim

        # Mark resources in-use and update stats
        self._update_usage_from_instance(self.compute_node, instance_ref)

        # persist changes to the compute node:
        self._update(context, self.compute_node)
        return claim

    def _set_instance_host(self, context, instance_ref):
        """Tag the instance as belonging to this host.  This should be done
        while the COMPUTE_RESOURCES_SEMPAHORE is being held so the resource
        claim will not be lost if the audit process starts.
        """
        values = {'host': self.host, 'launched_on': self.host}
        (old_ref, new_ref) = db.instance_update_and_get_original(context,
                instance_ref['uuid'], values)
        notifications.send_update(context, old_ref, new_ref)
        instance_ref['host'] = self.host
        instance_ref['launched_on'] = self.host

    def _can_claim_memory(self, memory_mb, memory_mb_limit):
        """Test if memory needed for a claim can be safely allocated"""
        # Installed memory and usage info:
        msg = _("Total memory: %(total_mem)d MB, used: %(used_mem)d MB, free: "
                "%(free_mem)d MB") % dict(
                        total_mem=self.compute_node['memory_mb'],
                        used_mem=self.compute_node['memory_mb_used'],
                        free_mem=self.compute_node['free_ram_mb'])
        LOG.audit(msg)

        if memory_mb_limit is None:
            # treat memory as unlimited:
            LOG.audit(_("Memory limit not specified, defaulting to unlimited"))
            return True

        free_ram_mb = memory_mb_limit - self.compute_node['memory_mb_used']

        # Oversubscribed memory policy info:
        msg = _("Memory limit: %(memory_mb_limit)d MB, free: "
                "%(free_ram_mb)d MB") % locals()
        LOG.audit(msg)

        can_claim_mem = memory_mb <= free_ram_mb

        if not can_claim_mem:
            msg = _("Unable to claim resources.  Free memory %(free_ram_mb)d "
                    "MB < requested memory %(memory_mb)d MB") % locals()
            LOG.info(msg)

        return can_claim_mem

    def _can_claim_disk(self, disk_gb, disk_gb_limit):
        """Test if disk space needed can be safely allocated"""
        # Installed disk and usage info:
        msg = _("Total disk: %(total_disk)d GB, used: %(used_disk)d GB, free: "
                "%(free_disk)d GB") % dict(
                        total_disk=self.compute_node['local_gb'],
                        used_disk=self.compute_node['local_gb_used'],
                        free_disk=self.compute_node['free_disk_gb'])
        LOG.audit(msg)

        if disk_gb_limit is None:
            # treat disk as unlimited:
            LOG.audit(_("Disk limit not specified, defaulting to unlimited"))
            return True

        free_disk_gb = disk_gb_limit - self.compute_node['local_gb_used']

        # Oversubscribed disk policy info:
        msg = _("Disk limit: %(disk_gb_limit)d GB, free: "
                "%(free_disk_gb)d GB") % locals()
        LOG.audit(msg)

        can_claim_disk = disk_gb <= free_disk_gb
        if not can_claim_disk:
            msg = _("Unable to claim resources.  Free disk %(free_disk_gb)d GB"
                    " < requested disk %(disk_gb)d GB") % dict(
                            free_disk_gb=self.compute_node['free_disk_gb'],
                            disk_gb=disk_gb)
            LOG.info(msg)

        return can_claim_disk

    def _can_claim_cpu(self, vcpus, vcpu_limit):
        """Test if CPUs can be safely allocated according to given policy."""

        msg = _("Total VCPUs: %(total_vcpus)d, used: %(used_vcpus)d") \
                % dict(total_vcpus=self.compute_node['vcpus'],
                       used_vcpus=self.compute_node['vcpus_used'])
        LOG.audit(msg)

        if vcpu_limit is None:
            # treat cpu as unlimited:
            LOG.audit(_("VCPU limit not specified, defaulting to unlimited"))
            return True

        # Oversubscribed disk policy info:
        msg = _("CPU limit: %(vcpu_limit)d") % locals()
        LOG.audit(msg)

        free_vcpus = vcpu_limit - self.compute_node['vcpus_used']
        can_claim_cpu = vcpus <= free_vcpus

        if not can_claim_cpu:
            msg = _("Unable to claim resources.  Free CPU %(free_vcpus)d < "
                    "requested CPU %(vcpus)d") % locals()
            LOG.info(msg)

        return can_claim_cpu

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def finish_resource_claim(self, claim):
        """Indicate that the compute operation that previously claimed the
        resources identified by 'claim' has now completed and the resources
        have been allocated at the virt layer.

        Calling this keeps the available resource data more accurate and
        timely than letting the claim timeout elapse and waiting for
        update_available_resource to reflect the changed usage data.

        :param claim: A claim indicating a set of resources that were
                      previously claimed.
        """
        if self.disabled:
            return

        if self.claims.pop(claim.claim_id, None):
            LOG.info(_("Finishing claim: %s") % claim)
        else:
            LOG.info(_("Can't find claim %s.  It may have been 'finished' "
                       "twice, or it has already timed out."), claim.claim_id)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def abort_resource_claim(self, context, claim):
        """Indicate that the operation that claimed the resources identified by
        'claim_id' has either failed or been aborted and the resources are no
        longer needed.

        :param claim: A claim ticket indicating a set of resources that were
                      previously claimed.
        """
        if self.disabled:
            return

        # un-claim the resources:
        if self.claims.pop(claim.claim_id, None):
            LOG.info(_("Aborting claim: %s") % claim)
            # flag the instance as deleted to revert the resource usage
            # and associated stats:
            claim.instance['vm_state'] = vm_states.DELETED
            self._update_usage_from_instance(self.compute_node, claim.instance)
            self._update(context, self.compute_node)

        else:
            # can't find the claim.  this may mean the claim already timed
            # out or it was already explicitly finished/aborted.
            LOG.audit(_("Claim %s not found.  It either timed out or was "
                        "already explicitly finished/aborted"), claim.claim_id)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
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

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_available_resource(self, context):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.
        """
        resources = self.driver.get_available_resource()
        if not resources:
            # The virt driver does not support this function
            LOG.audit(_("Virt driver does not support "
                "'get_available_resource'  Compute tracking is disabled."))
            self.compute_node = None
            self.claims = {}
            return

        self._verify_resources(resources)

        self._report_hypervisor_resource_view(resources)

        self._purge_expired_claims()

        # Grab all instances assigned to this host:
        instances = db.instance_get_all_by_host(context, self.host)

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

            compute_node_ref = service['compute_node']
            if compute_node_ref:
                self.compute_node = compute_node_ref[0]

        if not self.compute_node:
            # Need to create the ComputeNode record:
            resources['service_id'] = service['id']
            self._create(context, resources)
            LOG.info(_('Compute_service record created for %s ') % self.host)

        else:
            # just update the record:
            self._update(context, resources, prune_stats=True)
            LOG.info(_('Compute_service record updated for %s ') % self.host)

    def _purge_expired_claims(self):
        """Purge expired resource claims"""
        for claim_id in self.claims.keys():
            c = self.claims[claim_id]
            if c.is_expired():
                # if this claim is expired, just expunge it.
                # it is assumed that the instance will eventually get built
                # successfully.
                LOG.audit(_("Expiring resource claim %s"), claim_id)
                self.claims.pop(claim_id)

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

        if instance['vm_state'] == vm_states.DELETED:
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
