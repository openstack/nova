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
Claim objects for use with resource tracking.
"""

from oslo_log import log as logging

from nova import exception
from nova.i18n import _
from nova import objects
from nova.virt import hardware


LOG = logging.getLogger(__name__)


class NopClaim(object):
    """For use with compute drivers that do not support resource tracking."""

    def __init__(self, *args, **kwargs):
        self.migration = kwargs.pop('migration', None)
        self.claimed_numa_topology = None

    @property
    def disk_gb(self):
        return 0

    @property
    def memory_mb(self):
        return 0

    @property
    def vcpus(self):
        return 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.abort()

    def abort(self):
        pass

    def __str__(self):
        return "[Claim: %d MB memory, %d GB disk]" % (self.memory_mb,
                self.disk_gb)


class Claim(NopClaim):
    """A declaration that a compute host operation will require free resources.
    Claims serve as marker objects that resources are being held until the
    update_available_resource audit process runs to do a full reconciliation
    of resource usage.

    This information will be used to help keep the local compute hosts's
    ComputeNode model in sync to aid the scheduler in making efficient / more
    correct decisions with respect to host selection.
    """

    def __init__(self, context, instance, nodename, tracker, resources,
                 pci_requests, overhead=None, limits=None):
        super(Claim, self).__init__()
        # Stash a copy of the instance at the current point of time
        self.instance = instance.obj_clone()
        self.nodename = nodename
        self._numa_topology_loaded = False
        self.tracker = tracker
        self._pci_requests = pci_requests

        if not overhead:
            overhead = {'memory_mb': 0,
                        'disk_gb': 0}

        self.overhead = overhead
        self.context = context

        # Check claim at constructor to avoid mess code
        # Raise exception ComputeResourcesUnavailable if claim failed
        self._claim_test(resources, limits)

    @property
    def disk_gb(self):
        return (self.instance.flavor.root_gb +
                self.instance.flavor.ephemeral_gb +
                self.overhead.get('disk_gb', 0))

    @property
    def memory_mb(self):
        return self.instance.flavor.memory_mb + self.overhead['memory_mb']

    @property
    def vcpus(self):
        return self.instance.flavor.vcpus

    @property
    def numa_topology(self):
        if self._numa_topology_loaded:
            return self._numa_topology
        else:
            self._numa_topology = self.instance.numa_topology
            return self._numa_topology

    def abort(self):
        """Compute operation requiring claimed resources has failed or
        been aborted.
        """
        LOG.debug("Aborting claim: %s", self, instance=self.instance)
        self.tracker.abort_instance_claim(self.context, self.instance,
                                          self.nodename)

    def _claim_test(self, resources, limits=None):
        """Test if this claim can be satisfied given available resources and
        optional oversubscription limits

        This should be called before the compute node actually consumes the
        resources required to execute the claim.

        :param resources: available local compute node resources
        :returns: Return true if resources are available to claim.
        """
        if not limits:
            limits = {}

        # If an individual limit is None, the resource will be considered
        # unlimited:
        memory_mb_limit = limits.get('memory_mb')
        disk_gb_limit = limits.get('disk_gb')
        vcpus_limit = limits.get('vcpu')
        numa_topology_limit = limits.get('numa_topology')

        LOG.info("Attempting claim on node %(node)s: "
                 "memory %(memory_mb)d MB, "
                 "disk %(disk_gb)d GB, vcpus %(vcpus)d CPU",
                 {'node': self.nodename, 'memory_mb': self.memory_mb,
                  'disk_gb': self.disk_gb, 'vcpus': self.vcpus},
                 instance=self.instance)

        reasons = [self._test_memory(resources, memory_mb_limit),
                   self._test_disk(resources, disk_gb_limit),
                   self._test_vcpus(resources, vcpus_limit),
                   self._test_numa_topology(resources, numa_topology_limit),
                   self._test_pci()]
        reasons = [r for r in reasons if r is not None]
        if len(reasons) > 0:
            raise exception.ComputeResourcesUnavailable(reason=
                    "; ".join(reasons))

        LOG.info('Claim successful on node %s', self.nodename,
                 instance=self.instance)

    def _test_memory(self, resources, limit):
        type_ = _("memory")
        unit = "MB"
        total = resources.memory_mb
        used = resources.memory_mb_used
        requested = self.memory_mb

        return self._test(type_, unit, total, used, requested, limit)

    def _test_disk(self, resources, limit):
        type_ = _("disk")
        unit = "GB"
        total = resources.local_gb
        used = resources.local_gb_used
        requested = self.disk_gb

        return self._test(type_, unit, total, used, requested, limit)

    def _test_vcpus(self, resources, limit):
        type_ = _("vcpu")
        unit = "VCPU"
        total = resources.vcpus
        used = resources.vcpus_used
        requested = self.vcpus

        return self._test(type_, unit, total, used, requested, limit)

    def _test_pci(self):
        pci_requests = self._pci_requests
        if pci_requests.requests:
            stats = self.tracker.pci_tracker.stats
            if not stats.support_requests(pci_requests.requests):
                return _('Claim pci failed')

    def _test_numa_topology(self, resources, limit):
        host_topology = (resources.numa_topology
                         if 'numa_topology' in resources else None)
        requested_topology = self.numa_topology
        if host_topology:
            host_topology = objects.NUMATopology.obj_from_db_obj(
                    host_topology)
            pci_requests = self._pci_requests
            pci_stats = None
            if pci_requests.requests:
                pci_stats = self.tracker.pci_tracker.stats

            instance_topology = (
                    hardware.numa_fit_instance_to_host(
                        host_topology, requested_topology,
                        limits=limit,
                        pci_requests=pci_requests.requests,
                        pci_stats=pci_stats))

            if requested_topology and not instance_topology:
                if pci_requests.requests:
                    return (_("Requested instance NUMA topology together with "
                              "requested PCI devices cannot fit the given "
                              "host NUMA topology"))
                else:
                    return (_("Requested instance NUMA topology cannot fit "
                              "the given host NUMA topology"))
            elif instance_topology:
                self.claimed_numa_topology = instance_topology

    def _test(self, type_, unit, total, used, requested, limit):
        """Test if the given type of resource needed for a claim can be safely
        allocated.
        """
        LOG.info('Total %(type)s: %(total)d %(unit)s, used: %(used).02f '
                 '%(unit)s',
                  {'type': type_, 'total': total, 'unit': unit, 'used': used},
                  instance=self.instance)

        if limit is None:
            # treat resource as unlimited:
            LOG.info('%(type)s limit not specified, defaulting to unlimited',
                     {'type': type_}, instance=self.instance)
            return

        free = limit - used

        # Oversubscribed resource policy info:
        LOG.info('%(type)s limit: %(limit).02f %(unit)s, '
                 'free: %(free).02f %(unit)s',
                  {'type': type_, 'limit': limit, 'free': free, 'unit': unit},
                  instance=self.instance)

        if requested > free:
            return (_('Free %(type)s %(free).02f '
                      '%(unit)s < requested %(requested)d %(unit)s') %
                      {'type': type_, 'free': free, 'unit': unit,
                       'requested': requested})


class MoveClaim(Claim):
    """Claim used for holding resources for an incoming move operation.

    Move can be either a migrate/resize, live-migrate or an evacuate operation.
    """
    def __init__(self, context, instance, nodename, instance_type, image_meta,
                 tracker, resources, pci_requests, overhead=None, limits=None):
        self.context = context
        self.instance_type = instance_type
        if isinstance(image_meta, dict):
            image_meta = objects.ImageMeta.from_dict(image_meta)
        self.image_meta = image_meta
        super(MoveClaim, self).__init__(context, instance, nodename, tracker,
                                        resources, pci_requests,
                                        overhead=overhead, limits=limits)
        self.migration = None

    @property
    def disk_gb(self):
        return (self.instance_type.root_gb +
                self.instance_type.ephemeral_gb +
                self.overhead.get('disk_gb', 0))

    @property
    def memory_mb(self):
        return self.instance_type.memory_mb + self.overhead['memory_mb']

    @property
    def vcpus(self):
        return self.instance_type.vcpus

    @property
    def numa_topology(self):
        return hardware.numa_get_constraints(self.instance_type,
                                             self.image_meta)

    def abort(self):
        """Compute operation requiring claimed resources has failed or
        been aborted.
        """
        LOG.debug("Aborting claim: %s", self, instance=self.instance)
        self.tracker.drop_move_claim(
            self.context,
            self.instance, self.nodename,
            instance_type=self.instance_type)
        self.instance.drop_migration_context()
