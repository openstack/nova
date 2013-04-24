# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import uuid

from nova.compute import claims
from nova import test


class DummyTracker(object):
    icalled = False
    rcalled = False

    def abort_instance_claim(self, *args, **kwargs):
        self.icalled = True

    def drop_resize_claim(self, *args, **kwargs):
        self.rcalled = True


class ClaimTestCase(test.TestCase):

    def setUp(self):
        super(ClaimTestCase, self).setUp()
        self.resources = self._fake_resources()
        self.tracker = DummyTracker()

    def _claim(self, **kwargs):
        instance = self._fake_instance(**kwargs)
        return claims.Claim(instance, self.tracker)

    def _fake_instance(self, **kwargs):
        instance = {
            'uuid': str(uuid.uuid1()),
            'memory_mb': 1024,
            'root_gb': 10,
            'ephemeral_gb': 5,
            'vcpus': 1
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

    def test_cpu_unlimited(self):
        claim = self._claim(vcpus=100000)
        self.assertTrue(claim.test(self.resources))

    def test_memory_unlimited(self):
        claim = self._claim(memory_mb=99999999)
        self.assertTrue(claim.test(self.resources))

    def test_disk_unlimited_root(self):
        claim = self._claim(root_gb=999999)
        self.assertTrue(claim.test(self.resources))

    def test_disk_unlimited_ephemeral(self):
        claim = self._claim(ephemeral_gb=999999)
        self.assertTrue(claim.test(self.resources))

    def test_cpu_oversubscription(self):
        claim = self._claim(vcpus=8)
        limits = {'vcpu': 16}
        self.assertTrue(claim.test(self.resources, limits))

    def test_cpu_insufficient(self):
        claim = self._claim(vcpus=17)
        limits = {'vcpu': 16}
        self.assertFalse(claim.test(self.resources, limits))

    def test_memory_oversubscription(self):
        claim = self._claim(memory_mb=4096)
        limits = {'memory_mb': 8192}
        self.assertTrue(claim.test(self.resources, limits))

    def test_memory_insufficient(self):
        claim = self._claim(memory_mb=16384)
        limits = {'memory_mb': 8192}
        self.assertFalse(claim.test(self.resources, limits))

    def test_disk_oversubscription(self):
        claim = self._claim(root_gb=10, ephemeral_gb=40)
        limits = {'disk_gb': 60}
        self.assertTrue(claim.test(self.resources, limits))

    def test_disk_insufficient(self):
        claim = self._claim(root_gb=10, ephemeral_gb=40)
        limits = {'disk_gb': 45}
        self.assertFalse(claim.test(self.resources, limits))

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

    def _claim(self, **kwargs):
        instance_type = self._fake_instance_type(**kwargs)
        return claims.ResizeClaim(self.instance, instance_type, self.tracker)

    def test_abort(self):
        claim = self._abort()
        self.assertTrue(claim.tracker.rcalled)
