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
                 pci_requests, migration=None, limits=None):
        super(Claim, self).__init__(migration=migration)
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
                 tracker, resources, pci_requests, migration, limits=None):
        self.context = context
        self.instance_type = instance_type
        if isinstance(image_meta, dict):
            image_meta = objects.ImageMeta.from_dict(image_meta)
        self.image_meta = image_meta
        super(MoveClaim, self).__init__(context, instance, nodename, tracker,
                                        resources, pci_requests,
                                        migration=migration, limits=limits)

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

    def _test_pci(self):
        """Test whether this host can accept this claim's PCI requests. For
        live migration, only Neutron SRIOV PCI requests are supported. Any
        other type of PCI device would need to be removed and re-added for live
        migration to work, and there is currently no support for that. For cold
        migration, all types of PCI requests are supported, so we just call up
        to normal Claim's _test_pci().
        """
        if self.migration.migration_type != 'live-migration':
            return super(MoveClaim, self)._test_pci()
        elif self._pci_requests.requests:
            for pci_request in self._pci_requests.requests:
                if (pci_request.source !=
                        objects.InstancePCIRequest.NEUTRON_PORT):
                    return (_('Non-VIF related PCI requests are not '
                              'supported for live migration.'))
            # TODO(artom) At this point, once we've made sure we only have
            # NEUTRON_PORT (aka SRIOV) PCI requests, we should check whether
            # the host can support them, like Claim._test_pci() does. However,
            # SRIOV live migration is currently being handled separately - see
            # for example _claim_pci_for_instance_vifs() in the compute
            # manager. So we do nothing here to avoid stepping on that code's
            # toes, but ideally MoveClaim would be used for all live migration
            # resource claims.

    def _test_live_migration_page_size(self):
        """Tests that the current page size and the requested page size are the
        same.

        Must be called after _test_numa_topology() to make sure
        self.claimed_numa_topology is set.

        This only applies for live migrations when the hw:mem_page_size
        extra spec has been set to a non-numeric value (like 'large'). That
        would in theory allow an instance to live migrate from a host with a 1M
        page size to a host with a 2M page size, for example. This is not
        something we want to support, so fail the claim if the page sizes are
        different.
        """
        if (self.migration.migration_type == 'live-migration' and
                self.instance.numa_topology and
                # NOTE(artom) We only support a single page size across all
                # cells, checking cell 0 is sufficient.
                self.claimed_numa_topology.cells[0].pagesize !=
                self.instance.numa_topology.cells[0].pagesize):
            return (_('Requested page size is different from current '
                      'page size.'))

    def _test_numa_topology(self, resources, limit):
        """Test whether this host can accept the instance's NUMA topology. The
        _test methods return None on success, and a string-like Message _()
        object explaining the reason on failure. So we call up to the normal
        Claim's _test_numa_topology(), and if we get nothing back we test the
        page size.
        """
        numa_test_failure = super(MoveClaim,
                                  self)._test_numa_topology(resources, limit)
        if numa_test_failure:
            return numa_test_failure
        return self._test_live_migration_page_size()
