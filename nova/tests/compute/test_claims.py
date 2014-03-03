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

"""Tests for resource tracker claims."""

import re
import uuid

from nova.compute import claims
from nova import exception
from nova.openstack.common import jsonutils
from nova.pci import pci_manager
from nova import test


class DummyTracker(object):
    icalled = False
    rcalled = False
    pci_tracker = pci_manager.PciDevTracker()

    def abort_instance_claim(self, *args, **kwargs):
        self.icalled = True

    def drop_resize_claim(self, *args, **kwargs):
        self.rcalled = True

    def new_pci_tracker(self):
        self.pci_tracker = pci_manager.PciDevTracker()


class ClaimTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ClaimTestCase, self).setUp()
        self.resources = self._fake_resources()
        self.tracker = DummyTracker()

    def _claim(self, limits=None, overhead=None, **kwargs):
        instance = self._fake_instance(**kwargs)
        if overhead is None:
            overhead = {'memory_mb': 0}
        return claims.Claim(instance, self.tracker, self.resources,
                            overhead=overhead, limits=limits)

    def _fake_instance(self, **kwargs):
        instance = {
            'uuid': str(uuid.uuid1()),
            'memory_mb': 1024,
            'root_gb': 10,
            'ephemeral_gb': 5,
            'vcpus': 1,
            'system_metadata': {}
        }
        instance.update(**kwargs)
        return instance

    def _fake_instance_type(self, **kwargs):
        instance_type = {
            'id': 1,
            'name': 'fakeitype',
            'memory_mb': 1,
            'vcpus': 1,
            'root_gb': 1,
            'ephemeral_gb': 2
        }
        instance_type.update(**kwargs)
        return instance_type

    def _fake_resources(self, values=None):
        resources = {
            'memory_mb': 2048,
            'memory_mb_used': 0,
            'free_ram_mb': 2048,
            'local_gb': 20,
            'local_gb_used': 0,
            'free_disk_gb': 20,
            'vcpus': 2,
            'vcpus_used': 0
        }
        if values:
            resources.update(values)
        return resources

    # TODO(lxsli): Remove once Py2.6 is deprecated
    def assertRaisesRegexp(self, re_obj, e, fn, *a, **kw):
        try:
            fn(*a, **kw)
            self.fail("Expected exception not raised")
        except e as ee:
            self.assertTrue(re.search(re_obj, str(ee)))

    def test_cpu_unlimited(self):
        claim = self._claim(vcpus=100000)

    def test_memory_unlimited(self):
        claim = self._claim(memory_mb=99999999)

    def test_disk_unlimited_root(self):
        claim = self._claim(root_gb=999999)

    def test_disk_unlimited_ephemeral(self):
        claim = self._claim(ephemeral_gb=999999)

    def test_cpu_oversubscription(self):
        limits = {'vcpu': 16}
        claim = self._claim(limits, vcpus=8)

    def test_memory_with_overhead(self):
        overhead = {'memory_mb': 8}
        limits = {'memory_mb': 2048}
        claim = self._claim(memory_mb=2040, limits=limits,
                            overhead=overhead)

    def test_memory_with_overhead_insufficient(self):
        overhead = {'memory_mb': 9}
        limits = {'memory_mb': 2048}

        self.assertRaises(exception.ComputeResourcesUnavailable,
                          self._claim, limits=limits, overhead=overhead,
                          memory_mb=2040)

    def test_cpu_insufficient(self):
        limits = {'vcpu': 16}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                          self._claim, limits=limits, vcpus=17)

    def test_memory_oversubscription(self):
        limits = {'memory_mb': 8192}
        claim = self._claim(memory_mb=4096)

    def test_memory_insufficient(self):
        limits = {'memory_mb': 8192}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                          self._claim, limits=limits, memory_mb=16384)

    def test_disk_oversubscription(self):
        limits = {'disk_gb': 60}
        claim = self._claim(root_gb=10, ephemeral_gb=40,
                            limits=limits)

    def test_disk_insufficient(self):
        limits = {'disk_gb': 45}
        self.assertRaisesRegexp(re.compile("disk", re.IGNORECASE),
                exception.ComputeResourcesUnavailable,
                self._claim, limits=limits, root_gb=10, ephemeral_gb=40)

    def test_disk_and_memory_insufficient(self):
        limits = {'disk_gb': 45, 'memory_mb': 8192}
        self.assertRaisesRegexp(re.compile("memory.*disk", re.IGNORECASE),
                exception.ComputeResourcesUnavailable,
                self._claim, limits=limits, root_gb=10, ephemeral_gb=40,
                memory_mb=16384)

    def test_disk_and_cpu_insufficient(self):
        limits = {'disk_gb': 45, 'vcpu': 16}
        self.assertRaisesRegexp(re.compile("disk.*vcpus", re.IGNORECASE),
                exception.ComputeResourcesUnavailable,
                self._claim, limits=limits, root_gb=10, ephemeral_gb=40,
                vcpus=17)

    def test_disk_and_cpu_and_memory_insufficient(self):
        limits = {'disk_gb': 45, 'vcpu': 16, 'memory_mb': 8192}
        pat = "memory.*disk.*vcpus"
        self.assertRaisesRegexp(re.compile(pat, re.IGNORECASE),
                exception.ComputeResourcesUnavailable,
                self._claim, limits=limits, root_gb=10, ephemeral_gb=40,
                vcpus=17, memory_mb=16384)

    def test_pci_pass(self):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker.set_hvdevs([dev_dict])
        claim = self._claim()
        self._set_pci_request(claim)
        claim._test_pci()

    def _set_pci_request(self, claim):
        request = [{'count': 1,
                       'spec': [{'vendor_id': 'v', 'product_id': 'p'}],
                      }]

        claim.instance.update(
            system_metadata={'pci_requests': jsonutils.dumps(request)})

    def test_pci_fail(self):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v1',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker.set_hvdevs([dev_dict])
        claim = self._claim()
        self._set_pci_request(claim)
        self.assertEqual("Claim pci failed.", claim._test_pci())

    def test_pci_pass_no_requests(self):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker.set_hvdevs([dev_dict])
        claim = self._claim()
        self._set_pci_request(claim)
        claim._test_pci()

    def test_abort(self):
        claim = self._abort()
        self.assertTrue(claim.tracker.icalled)

    def _abort(self):
        claim = None
        try:
            with self._claim(memory_mb=4096) as claim:
                raise test.TestingException("abort")
        except test.TestingException:
            pass

        return claim


class ResizeClaimTestCase(ClaimTestCase):

    def setUp(self):
        super(ResizeClaimTestCase, self).setUp()
        self.instance = self._fake_instance()

    def _claim(self, limits=None, overhead=None, **kwargs):
        instance_type = self._fake_instance_type(**kwargs)
        if overhead is None:
            overhead = {'memory_mb': 0}
        return claims.ResizeClaim(self.instance, instance_type, self.tracker,
                                  self.resources, overhead=overhead,
                                  limits=limits)

    def _set_pci_request(self, claim):
        request = [{'count': 1,
                       'spec': [{'vendor_id': 'v', 'product_id': 'p'}],
                      }]
        claim.instance.update(
            system_metadata={'new_pci_requests': jsonutils.dumps(request)})

    def test_abort(self):
        claim = self._abort()
        self.assertTrue(claim.tracker.rcalled)
