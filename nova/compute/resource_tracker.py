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

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import utils

resource_tracker_opts = [
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

    def __init__(self, claim_id, memory_mb, disk_gb, timeout, *args, **kwargs):
        self.claim_id = claim_id
        self.memory_mb = memory_mb
        self.disk_gb = disk_gb
        self.timeout = timeout
        self.expire_ts = timeutils.utcnow_ts() + timeout

    def apply_claim(self, resources):
        """Adjust the resources required from available resources.

        :param resources: Should be a dictionary-like object that
                          has fields like a compute node
        """
        return self._apply(resources)

    def undo_claim(self, resources):
        return self._apply(resources, sign=-1)

    def is_expired(self):
        """Determine if this adjustment is old enough that we can assume it's
        no longer needed.
        """
        return timeutils.utcnow_ts() > self.expire_ts

    def _apply(self, resources, sign=1):
        values = {}
        values['memory_mb_used'] = (resources['memory_mb_used'] + sign *
                                   self.memory_mb)
        values['free_ram_mb'] = (resources['free_ram_mb'] - sign *
                                   self.memory_mb)
        values['local_gb_used'] = (resources['local_gb_used'] + sign *
                                  self.disk_gb)
        values['free_disk_gb'] = (resources['free_disk_gb'] - sign *
                                  self.disk_gb)

        return values

    def __str__(self):
        return "[Claim %d: %d MB memory, %d GB disk]" % (self.claim_id,
                self.memory_mb, self.disk_gb)


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

    def resource_claim(self, context, *args, **kwargs):
        claim = self.begin_resource_claim(context, *args, **kwargs)
        return ResourceContextManager(context, claim, self)

    def instance_resource_claim(self, context, instance_ref, *args, **kwargs):
        claim = self.begin_instance_resource_claim(context, instance_ref,
                *args, **kwargs)
        return ResourceContextManager(context, claim, self)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def begin_instance_resource_claim(self, context, instance_ref, *args,
            **kwargs):
        """Method to begin a resource claim for a new instance."""
        memory_mb = instance_ref['memory_mb']
        disk_gb = instance_ref['root_gb'] + instance_ref['ephemeral_gb']

        claim = self._do_begin_resource_claim(context, memory_mb, disk_gb,
                *args, **kwargs)
        if claim:
            # also update load stats related to new instances firing up -
            values = self._create_load_stats(context, instance_ref)
            self.compute_node = self._update(context, values)
        return claim

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def begin_resource_claim(self, context, memory_mb, disk_gb,
        memory_mb_limit=None, timeout=None, *args, **kwargs):
        """Indicate that some resources are needed for an upcoming compute
        host operation.

        This should be called any time the compute node is about to perform
        an operation that will consume resources.

        :param memory_mb: security context
        :param memory_mb: Memory in MB to be claimed
        :param root_gb: Disk in GB to be claimed
        :param memory_mb_limit: Memory in MB that is the maximum to allocate on
                        this node.  May exceed installed physical memory if
                        oversubscription is the desired behavior.
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

        return self._do_begin_resource_claim(context, memory_mb, disk_gb,
                memory_mb_limit, timeout, *args, **kwargs)

    def _do_begin_resource_claim(self, context, memory_mb, disk_gb,
        memory_mb_limit=None, timeout=None, *args, **kwargs):

        if self.disabled:
            return

        if not timeout:
            timeout = FLAGS.claim_timeout_seconds

        memory_mb = abs(memory_mb)
        disk_gb = abs(disk_gb)

        msg = _("Attempting claim: memory %(memory_mb)d MB, disk %(disk_gb)d "
                "GB, mem limit %(memory_mb_limit)s") % locals()
        LOG.audit(msg)

        if not memory_mb_limit:
            # default to total memory:
            memory_mb_limit = self.compute_node['memory_mb']

        free_ram_mb = memory_mb_limit - self.compute_node['memory_mb_used']

        # Installed memory and usage info:
        msg = _("Total memory: %(total_mem)d MB, used: %(used_mem)d MB, free: "
                "%(free_mem)d") % dict(
                        total_mem=self.compute_node['memory_mb'],
                        used_mem=self.compute_node['memory_mb_used'],
                        free_mem=self.compute_node['local_gb_used'])
        LOG.audit(msg)

        # Oversubscribed memory policy info:
        msg = _("Limit: %(memory_mb_limit)d MB, free: %(free_ram_mb)d") % \
                locals()
        LOG.audit(msg)

        if memory_mb > free_ram_mb:
            msg = _("Unable to claim resources.  Free memory %(free_ram_mb)d "
                    "MB < requested memory %(memory_mb)d MB") % locals()
            LOG.info(msg)
            return None

        if disk_gb > self.compute_node['free_disk_gb']:
            msg = _("Unable to claim resources.  Free disk %(free_disk_gb)d GB"
                    " < requested disk %(disk_gb)d GB") % dict(
                            free_disk_gb=self.compute_node['free_disk_gb'],
                            disk_gb=disk_gb)
            LOG.info(msg)
            return None

        claim_id = self._get_next_id()
        c = Claim(claim_id, memory_mb, disk_gb, timeout, *args, **kwargs)

        # adjust compute node usage values and save so scheduler will see it:
        values = c.apply_claim(self.compute_node)
        self.compute_node = self._update(context, values)

        # keep track of this claim until we know whether the compute operation
        # was successful/completed:
        self.claims[claim_id] = c
        return c

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
            LOG.info(_("Can't find claim %d.  It may have been 'finished' "
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
            values = claim.undo_claim(self.compute_node)
            self.compute_node = self._update(context, values)
        else:
            # can't find the claim.  this may mean the claim already timed
            # out or it was already explicitly finished/aborted.
            LOG.info(_("Claim %d not found.  It either timed out or was "
                        "already explicitly finished/aborted"), claim.claim_id)

    @property
    def disabled(self):
        return self.compute_node is None

    def free_resources(self, context):
        """A compute operation finished freeing up resources.  Update compute
        model to reflect updated resource usage.

        (The hypervisor may not immediately 'GC' all resources, so ask directly
        to see what's available to update the compute node model.)
        """
        self.update_available_resource(context.elevated())

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_available_resource(self, context):
        """Override in-memory calculations of compute node resource usage based
        on data audited from the hypervisor layer.

        Add in resource claims in progress to account for operations that have
        declared a need for resources, but not necessarily retrieved them from
        the hypervisor layer yet.
        """
        # ask hypervisor for its view of resource availability &
        # usage:
        resources = self.driver.get_available_resource()
        if not resources:
            # The virt driver does not support this function
            LOG.warn(_("Virt driver does not support "
                "'get_available_resource'  Compute tracking is disabled."))
            self.compute_node = None
            self.claims = {}
            return

        # Confirm resources dictionary contains expected keys:
        self._verify_resources(resources)

        resources['free_ram_mb'] = resources['memory_mb'] - \
                                   resources['memory_mb_used']
        resources['free_disk_gb'] = resources['local_gb'] - \
                                    resources['local_gb_used']

        LOG.audit(_("free_ram_mb: %s") % resources['free_ram_mb'])
        LOG.audit(_("free_disk_gb: %s") % resources['free_disk_gb'])
        # Apply resource claims representing in-progress operations to
        # 'resources'. This may over-estimate the amount of resources in use,
        # at least until the next time 'update_available_resource' runs.
        self._apply_claims(resources)

        # also generate all load stats:
        values = self._create_load_stats(context)
        resources.update(values)

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
            self.compute_node = self._create(context, resources)
            LOG.info(_('Compute_service record created for %s ') % self.host)

        else:
            # just update the record:
            self.compute_node = self._update(context, resources,
                    prune_stats=True)
            LOG.info(_('Compute_service record updated for %s ') % self.host)

    @utils.synchronized(COMPUTE_RESOURCE_SEMAPHORE)
    def update_load_stats_for_instance(self, context, old_ref, instance_ref):
        """Update workload stats for the local compute host."""

        if self.disabled:
            return

        values = {}
        self.stats.update_stats_for_instance(old_ref, instance_ref)
        values['stats'] = self.stats

        values['current_workload'] = self.stats.calculate_workload()
        values['running_vms'] = self.stats.num_instances
        values['vcpus_used'] = self.stats.num_vcpus_used

        self.compute_node = self._update(context.elevated(), values)

    def _apply_claims(self, resources):
        """Apply in-progress resource claims to the 'resources' dict from the
        virt layer
        """
        for claim_id in self.claims.keys():
            c = self.claims[claim_id]
            if c.is_expired():
                # if this claim is expired, just expunge it
                LOG.info(_("Expiring resource claim %d"), claim_id)
                self.claims.pop(claim_id)
            else:
                values = c.apply_claim(resources)
                resources.update(values)

    def _create(self, context, values):
        """Create the compute node in the DB"""
        # initialize load stats from existing instances:
        compute_node = db.compute_node_create(context, values)
        return compute_node

    def _create_load_stats(self, context, instance=None):
        """For each existing instance generate load stats for the compute
        node record.
        """
        values = {}

        if instance:
            instances = [instance]
        else:
            self.stats.clear()  # re-generating all, so clear old stats

            # grab all instances that are not yet DELETED
            filters = {'host': self.host, 'deleted': False}
            instances = db.instance_get_all_by_filters(context, filters)

        for instance in instances:
            self.stats.add_stats_for_instance(instance)

        values['current_workload'] = self.stats.calculate_workload()
        values['running_vms'] = self.stats.num_instances
        values['vcpus_used'] = self.stats.num_vcpus_used
        values['stats'] = self.stats
        return values

    def _get_next_id(self):
        next_id = self.next_claim_id
        self.next_claim_id += 1
        return next_id

    def _get_service(self, context):
        try:
            return db.service_get_all_compute_by_host(context,
                    self.host)[0]
        except exception.NotFound:
            LOG.warn(_("No service record for host %s"), self.host)

    def _update(self, context, values, prune_stats=False):
        """Persist the compute node updates to the DB"""
        return db.compute_node_update(context, self.compute_node['id'],
                values, prune_stats)

    def _verify_resources(self, resources):
        resource_keys = ["vcpus", "memory_mb", "local_gb", "cpu_info",
                         "vcpus_used", "memory_mb_used", "local_gb_used"]

        missing_keys = [k for k in resource_keys if k not in resources]
        if missing_keys:
            reason = _("Missing keys: %s") % missing_keys
            raise exception.InvalidInput(reason=reason)
