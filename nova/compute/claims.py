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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.abort()

    def abort(self):
        pass


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
                 pci_requests, limits=None):
        super(Claim, self).__init__()
        # Stash a copy of the instance at the current point of time
        self.instance = instance.obj_clone()
        self.nodename = nodename
        self.tracker = tracker
        self._pci_requests = pci_requests
        self.context = context

        # Check claim at constructor to avoid mess code
        # Raise exception ComputeResourcesUnavailable if claim failed
        self._claim_test(resources, limits)

    @property
    def numa_topology(self):
        return self.instance.numa_topology

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
        :param limits: Optional limits to test, either dict or
            objects.SchedulerLimits
        :raises: exception.ComputeResourcesUnavailable if any resource claim
            fails
        """
        if not limits:
            limits = {}

        if isinstance(limits, objects.SchedulerLimits):
            limits = limits.to_dict()

        # If an individual limit is None, the resource will be considered
        # unlimited:
        numa_topology_limit = limits.get('numa_topology')

        reasons = [self._test_numa_topology(resources, numa_topology_limit),
                   self._test_pci()]
        reasons = [r for r in reasons if r is not None]
        if len(reasons) > 0:
            raise exception.ComputeResourcesUnavailable(reason=
                    "; ".join(reasons))

        LOG.info('Claim successful on node %s', self.nodename,
                 instance=self.instance)

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


class MoveClaim(Claim):
    """Claim used for holding resources for an incoming move operation.

    Move can be either a migrate/resize, live-migrate or an evacuate operation.
    """
    def __init__(self, context, instance, nodename, instance_type, image_meta,
                 tracker, resources, pci_requests, limits=None):
        self.context = context
        self.instance_type = instance_type
        if isinstance(image_meta, dict):
            image_meta = objects.ImageMeta.from_dict(image_meta)
        self.image_meta = image_meta
        super(MoveClaim, self).__init__(context, instance, nodename, tracker,
                                        resources, pci_requests,
                                        limits=limits)
        self.migration = None

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
