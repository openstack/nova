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

from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.pci import pci_request


LOG = logging.getLogger(__name__)


class NopClaim(object):
    """For use with compute drivers that do not support resource tracking."""

    def __init__(self, migration=None):
        self.migration = migration

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
        return "[Claim: %d MB memory, %d GB disk, %d VCPUS]" % (self.memory_mb,
                self.disk_gb, self.vcpus)


class Claim(NopClaim):
    """A declaration that a compute host operation will require free resources.
    Claims serve as marker objects that resources are being held until the
    update_available_resource audit process runs to do a full reconciliation
    of resource usage.

    This information will be used to help keep the local compute hosts's
    ComputeNode model in sync to aid the scheduler in making efficient / more
    correct decisions with respect to host selection.
    """

    def __init__(self, instance, tracker, overhead=None):
        super(Claim, self).__init__()
        # Stash a copy of the instance at the current point of time
        if isinstance(instance, instance_obj.Instance):
            self.instance = instance.obj_clone()
        else:
            # This does not use copy.deepcopy() because it could be
            # a sqlalchemy model, and it's best to make sure we have
            # the primitive form.
            self.instance = jsonutils.to_primitive(instance)
        self.tracker = tracker

        if not overhead:
            overhead = {'memory_mb': 0}

        self.overhead = overhead

    @property
    def disk_gb(self):
        return self.instance['root_gb'] + self.instance['ephemeral_gb']

    @property
    def memory_mb(self):
        return self.instance['memory_mb'] + self.overhead['memory_mb']

    @property
    def vcpus(self):
        return self.instance['vcpus']

    def abort(self):
        """Compute operation requiring claimed resources has failed or
        been aborted.
        """
        LOG.debug(_("Aborting claim: %s") % self, instance=self.instance)
        self.tracker.abort_instance_claim(self.instance)

    def test(self, resources, limits=None):
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
        vcpu_limit = limits.get('vcpu')

        msg = _("Attempting claim: memory %(memory_mb)d MB, disk %(disk_gb)d "
                "GB, VCPUs %(vcpus)d")
        params = {'memory_mb': self.memory_mb, 'disk_gb': self.disk_gb,
                  'vcpus': self.vcpus}
        LOG.audit(msg % params, instance=self.instance)

        # Test for resources:
        can_claim = (self._test_memory(resources, memory_mb_limit) and
                     self._test_disk(resources, disk_gb_limit) and
                     self._test_cpu(resources, vcpu_limit) and
                     self._test_pci())

        if can_claim:
            LOG.audit(_("Claim successful"), instance=self.instance)
        else:
            LOG.audit(_("Claim failed"), instance=self.instance)

        return can_claim

    def _test_memory(self, resources, limit):
        type_ = _("Memory")
        unit = "MB"
        total = resources['memory_mb']
        used = resources['memory_mb_used']
        requested = self.memory_mb

        return self._test(type_, unit, total, used, requested, limit)

    def _test_disk(self, resources, limit):
        type_ = _("Disk")
        unit = "GB"
        total = resources['local_gb']
        used = resources['local_gb_used']
        requested = self.disk_gb

        return self._test(type_, unit, total, used, requested, limit)

    def _test_pci(self):
        pci_requests = pci_request.get_instance_pci_requests(self.instance)
        if not pci_requests:
            return True
        return self.tracker.pci_tracker.stats.support_requests(pci_requests)

    def _test_cpu(self, resources, limit):
        type_ = _("CPU")
        unit = "VCPUs"
        total = resources['vcpus']
        used = resources['vcpus_used']
        requested = self.vcpus

        return self._test(type_, unit, total, used, requested, limit)

    def _test(self, type_, unit, total, used, requested, limit):
        """Test if the given type of resource needed for a claim can be safely
        allocated.
        """
        LOG.audit(_('Total %(type)s: %(total)d %(unit)s, used: %(used).02f '
                    '%(unit)s'),
                  {'type': type_, 'total': total, 'unit': unit, 'used': used},
                  instance=self.instance)

        if limit is None:
            # treat resource as unlimited:
            LOG.audit(_('%(type)s limit not specified, defaulting to '
                        'unlimited'), {'type': type_}, instance=self.instance)
            return True

        free = limit - used

        # Oversubscribed resource policy info:
        LOG.audit(_('%(type)s limit: %(limit).02f %(unit)s, free: %(free).02f '
                    '%(unit)s'),
                  {'type': type_, 'limit': limit, 'free': free, 'unit': unit},
                  instance=self.instance)

        can_claim = requested <= free

        if not can_claim:
            LOG.info(_('Unable to claim resources.  Free %(type)s %(free).02f '
                       '%(unit)s < requested %(requested)d %(unit)s'),
                     {'type': type_, 'free': free, 'unit': unit,
                      'requested': requested},
                     instance=self.instance)

        return can_claim


class ResizeClaim(Claim):
    """Claim used for holding resources for an incoming resize/migration
    operation.
    """
    def __init__(self, instance, instance_type, tracker, overhead=None):
        super(ResizeClaim, self).__init__(instance, tracker, overhead=overhead)
        self.instance_type = instance_type
        self.migration = None

    @property
    def disk_gb(self):
        return (self.instance_type['root_gb'] +
                self.instance_type['ephemeral_gb'])

    @property
    def memory_mb(self):
        return self.instance_type['memory_mb'] + self.overhead['memory_mb']

    @property
    def vcpus(self):
        return self.instance_type['vcpus']

    def _test_pci(self):
        pci_requests = pci_request.get_instance_pci_requests(
            self.instance, 'new_')
        if not pci_requests:
            return True

        return self.tracker.pci_tracker.stats.support_requests(pci_requests)

    def abort(self):
        """Compute operation requiring claimed resources has failed or
        been aborted.
        """
        LOG.debug(_("Aborting claim: %s") % self, instance=self.instance)
        self.tracker.drop_resize_claim(self.instance, self.instance_type)
