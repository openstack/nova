# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Tests for compute resource tracking"""

import copy

from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.openstack.common import timeutils
from nova import test
from nova.virt import driver


class FakeContext(object):
    def __init__(self, is_admin=False):
        self.is_admin = is_admin

    def elevated(self):
        return FakeContext(is_admin=True)


class UnsupportedVirtDriver(driver.ComputeDriver):
    """Pretend version of a lame virt driver"""
    def get_available_resource(self):
        # no support for getting resource usage info
        return {}


class FakeVirtDriver(driver.ComputeDriver):

    def __init__(self):
        self.memory_mb = 5
        self.local_gb = 6
        self.vcpus = 1

        self.memory_mb_used = 0
        self.local_gb_used = 0

    def get_available_resource(self):
        d = {
            'vcpus': self.vcpus,
            'memory_mb': self.memory_mb,
            'local_gb': self.local_gb,
            'vcpus_used': 0,
            'memory_mb_used': self.memory_mb_used,
            'local_gb_used': self.local_gb_used,
            'hypervisor_type': 'fake',
            'hypervisor_version': 0,
            'hypervisor_hostname': 'fakehost',
            'cpu_info': '',
        }
        return d


class BaseTestCase(test.TestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()

        self.context = FakeContext()

        self.instance_ref = {
            "memory_mb": 1,
            "root_gb": 1,
            "ephemeral_gb": 1,
            "vm_state": vm_states.BUILDING,
            "task_state": None,
            "os_type": "Linux",
            "project_id": "1234",
            "vcpus": 1,
            "uuid": "12-34-56-78-90",
        }

        self.stubs.Set(db, 'instance_get_all_by_filters',
                self._fake_instance_get_all_by_filters)

    def _create_compute_node(self, values=None):
        compute = {
            "id": 1,
            "service_id": 1,
            "vcpus": 1,
            "memory_mb": 1,
            "local_gb": 1,
            "vcpus_used": 1,
            "memory_mb_used": 1,
            "local_gb_used": 1,
            "free_ram_mb": 1,
            "free_disk_gb": 1,
            "current_workload": 1,
            "running_vms": 0,
            "cpu_info": None,
            "stats": [{"key": "num_instances", "value": "1"}]
        }
        if values:
            compute.update(values)
        return compute

    def _create_service(self, host="fakehost", compute=None):
        if compute:
            compute = [compute]

        service = {
            "id": 1,
            "host": host,
            "binary": "nova-compute",
            "topic": "compute",
            "compute_node": compute,
        }
        return service

    def _fake_instance_get_all_by_filters(self, ctx, filters, **kwargs):
        return []

    def _tracker(self, unsupported=False):
        host = "fakehost"

        if unsupported:
            driver = UnsupportedVirtDriver()
        else:
            driver = FakeVirtDriver()

        tracker = resource_tracker.ResourceTracker(host, driver)
        return tracker


class UnsupportedDriverTestCase(BaseTestCase):
    """Resource tracking should be disabled when the virt driver doesn't
    support it.
    """
    def setUp(self):
        super(UnsupportedDriverTestCase, self).setUp()
        self.tracker = self._tracker(unsupported=True)
        # seed tracker with data:
        self.tracker.update_available_resource(self.context)

    def testDisabled(self):
        # disabled = no compute node stats
        self.assertTrue(self.tracker.disabled)
        self.assertEqual(None, self.tracker.compute_node)

    def testDisabledClaim(self):
        # basic claim:
        claim = self.tracker.begin_resource_claim(self.context, 1, 1)
        self.assertEqual(None, claim)

    def testDisabledContextClaim(self):
        # basic context manager variation:
        with self.tracker.resource_claim(self.context, 1, 1):
            pass
        self.assertEqual(0, len(self.tracker.claims))

    def testDisabledInstanceClaim(self):
        # instance variation:
        claim = self.tracker.begin_instance_resource_claim(self.context,
                self.instance_ref)
        self.assertEqual(None, claim)

    def testDisabledInstanceContextClaim(self):
        # instance context manager variation:
        with self.tracker.instance_resource_claim(self.context,
                self.instance_ref):
            pass
        self.assertEqual(0, len(self.tracker.claims))

    def testDisabledFinishClaim(self):
        self.assertEqual(None, self.tracker.finish_resource_claim(None))

    def testDisabledAbortClaim(self):
        self.assertEqual(None, self.tracker.abort_resource_claim(self.context,
            None))

    def testDisabledFreeResources(self):
        self.tracker.free_resources(self.context)
        self.assertTrue(self.tracker.disabled)
        self.assertEqual(None, self.tracker.compute_node)


class MissingServiceTestCase(BaseTestCase):
    def setUp(self):
        super(MissingServiceTestCase, self).setUp()
        self.context = FakeContext(is_admin=True)
        self.tracker = self._tracker()

    def testMissingService(self):
        """No service record in DB."""
        self.tracker.update_available_resource(self.context)
        self.assertTrue(self.tracker.disabled)


class MissingComputeNodeTestCase(BaseTestCase):
    def setUp(self):
        super(MissingComputeNodeTestCase, self).setUp()
        self.tracker = self._tracker()

        self.stubs.Set(db, 'service_get_all_compute_by_host',
                self._fake_service_get_all_compute_by_host)
        self.stubs.Set(db, 'compute_node_create',
                self._fake_create_compute_node)

    def _fake_create_compute_node(self, context, values):
        self.created = True
        return self._create_compute_node()

    def _fake_service_get_all_compute_by_host(self, ctx, host):
        # return a service with no joined compute
        service = self._create_service()
        return [service]

    def testCreatedComputeNode(self):
        self.tracker.update_available_resource(self.context)
        self.assertTrue(self.created)

    def testEnabled(self):
        self.tracker.update_available_resource(self.context)
        self.assertFalse(self.tracker.disabled)


class ResourceTestCase(BaseTestCase):
    def setUp(self):
        super(ResourceTestCase, self).setUp()
        self.tracker = self._tracker()
        self.stubs.Set(db, 'service_get_all_compute_by_host',
                self._fake_service_get_all_compute_by_host)
        self.stubs.Set(db, 'compute_node_update',
                self._fake_compute_node_update)

        self.tracker.update_available_resource(self.context)

    def _fake_service_get_all_compute_by_host(self, ctx, host):
        self.compute = self._create_compute_node()
        self.service = self._create_service(host, compute=self.compute)
        return [self.service]

    def _fake_compute_node_update(self, ctx, compute_node_id, values,
            prune_stats=False):
        self.updated = True
        values['stats'] = [{"key": "num_instances", "value": "1"}]
        self.compute.update(values)
        return self.compute

    def testFreeRamResourceValue(self):
        driver = FakeVirtDriver()
        mem_free = driver.memory_mb - driver.memory_mb_used
        self.assertEqual(mem_free, self.tracker.compute_node['free_ram_mb'])

    def testFreeDiskResourceValue(self):
        driver = FakeVirtDriver()
        mem_free = driver.local_gb - driver.local_gb_used
        self.assertEqual(mem_free, self.tracker.compute_node['free_disk_gb'])

    def testUpdateComputeNode(self):
        self.assertFalse(self.tracker.disabled)
        self.assertTrue(self.updated)

    def testInsufficientMemoryClaim(self):
        """Exceed memory limit of 5MB"""
        claim = self.tracker.begin_resource_claim(self.context, memory_mb=2,
                disk_gb=0)
        self.assertNotEqual(None, claim)

        claim = self.tracker.begin_resource_claim(self.context, memory_mb=3,
                disk_gb=0)
        self.assertNotEqual(None, claim)

        claim = self.tracker.begin_resource_claim(self.context, memory_mb=1,
                disk_gb=0)
        self.assertEqual(None, claim)

    def testInsufficientMemoryClaimWithOversubscription(self):
        """Exceed oversubscribed memory limit of 10MB"""
        claim = self.tracker.begin_resource_claim(self.context, memory_mb=10,
                disk_gb=0, memory_mb_limit=10)
        self.assertNotEqual(None, claim)

        claim = self.tracker.begin_resource_claim(self.context, memory_mb=1,
                disk_gb=0, memory_mb_limit=10)
        self.assertEqual(None, claim)

    def testInsufficientDiskClaim(self):
        """Exceed disk limit of 5GB"""
        claim = self.tracker.begin_resource_claim(self.context, memory_mb=0,
                disk_gb=2)
        self.assertNotEqual(None, claim)

        claim = self.tracker.begin_resource_claim(self.context, memory_mb=0,
                disk_gb=3)
        self.assertNotEqual(None, claim)

        claim = self.tracker.begin_resource_claim(self.context, memory_mb=0,
                disk_gb=5)
        self.assertEqual(None, claim)

    def testClaimAndFinish(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        claim = self.tracker.begin_resource_claim(self.context, claim_mem,
                claim_disk)

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(claim_mem, self.compute["memory_mb_used"])
        self.assertEqual(5 - claim_mem, self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(6 - claim_disk, self.compute["free_disk_gb"])

        # 1st pretend that the compute operation finished and claimed the
        # desired resources from the virt layer
        driver = self.tracker.driver
        driver.memory_mb_used = claim_mem
        driver.local_gb_used = claim_disk

        # 2nd update compute node from the virt layer.  because the claim is
        # in-progress (unfinished), the audit will actually mark the resources
        # as unsubscribed:
        self.tracker.update_available_resource(self.context)

        self.assertEqual(2 * claim_mem,
                self.compute['memory_mb_used'])
        self.assertEqual(5 - (2 * claim_mem),
                self.compute['free_ram_mb'])

        self.assertEqual(2 * claim_disk,
                self.compute['local_gb_used'])
        self.assertEqual(6 - (2 * claim_disk),
                self.compute['free_disk_gb'])

        # Finally, finish the claimm and update from the virt layer again.
        # Resource usage will be consistent again:
        self.tracker.finish_resource_claim(claim)
        self.tracker.update_available_resource(self.context)

        self.assertEqual(claim_mem,
                self.compute['memory_mb_used'])
        self.assertEqual(5 - claim_mem,
                self.compute['free_ram_mb'])

        self.assertEqual(claim_disk,
                self.compute['local_gb_used'])
        self.assertEqual(6 - claim_disk,
                self.compute['free_disk_gb'])

    def testClaimAndAbort(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        claim = self.tracker.begin_resource_claim(self.context, claim_mem,
                claim_disk)

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(claim_mem, self.compute["memory_mb_used"])
        self.assertEqual(5 - claim_mem, self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(6 - claim_disk, self.compute["free_disk_gb"])

        self.tracker.abort_resource_claim(self.context, claim)

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(0, self.compute["memory_mb_used"])
        self.assertEqual(5, self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(0, self.compute["local_gb_used"])
        self.assertEqual(6, self.compute["free_disk_gb"])

    def testExpiredClaims(self):
        """Test that old claims get cleaned up automatically if not finished
        or aborted explicitly.
        """
        claim = self.tracker.begin_resource_claim(self.context, memory_mb=2,
                disk_gb=2)
        claim.expire_ts = timeutils.utcnow_ts() - 1
        self.assertTrue(claim.is_expired())

        # and an unexpired claim
        claim2 = self.tracker.begin_resource_claim(self.context, memory_mb=1,
                disk_gb=1)

        self.assertEqual(2, len(self.tracker.claims))
        self.assertEqual(2 + 1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2 + 1, self.tracker.compute_node['local_gb_used'])

        # expired claims get expunged when audit runs:
        self.tracker.update_available_resource(self.context)

        self.assertEqual(1, len(self.tracker.claims))
        self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(1, self.tracker.compute_node['local_gb_used'])

        # and just call finish & abort to ensure expired claims do not cause
        # any other explosions:
        self.tracker.abort_resource_claim(self.context, claim)
        self.tracker.finish_resource_claim(claim)

    def testInstanceClaim(self):
        self.tracker.begin_instance_resource_claim(self.context,
                self.instance_ref)
        self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])

    def testContextClaim(self):
        with self.tracker.resource_claim(self.context, memory_mb=1, disk_gb=1):
            # <insert exciting things that utilize resources>
            self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
            self.assertEqual(1, self.tracker.compute_node['local_gb_used'])
            self.assertEqual(1, self.compute['memory_mb_used'])
            self.assertEqual(1, self.compute['local_gb_used'])

        self.tracker.update_available_resource(self.context)
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.compute['memory_mb_used'])
        self.assertEqual(0, self.compute['local_gb_used'])

    def testContextClaimWithException(self):
        try:
            with self.tracker.resource_claim(self.context, memory_mb=1,
                    disk_gb=1):
                # <insert exciting things that utilize resources>
                raise Exception("THE SKY IS FALLING")
        except Exception:
            pass

        self.tracker.update_available_resource(self.context)
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.compute['memory_mb_used'])
        self.assertEqual(0, self.compute['local_gb_used'])

    def testInstanceContextClaim(self):
        with self.tracker.instance_resource_claim(self.context,
                self.instance_ref):
            # <insert exciting things that utilize resources>
            self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
            self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
            self.assertEqual(1, self.compute['memory_mb_used'])
            self.assertEqual(2, self.compute['local_gb_used'])

        self.tracker.update_available_resource(self.context)
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.compute['memory_mb_used'])
        self.assertEqual(0, self.compute['local_gb_used'])

    def testUpdateLoadStatsForInstance(self):
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

        self.instance_ref['task_state'] = task_states.SCHEDULING
        with self.tracker.instance_resource_claim(self.context,
                self.instance_ref):
            pass

        self.assertEqual(1, self.tracker.compute_node['current_workload'])

        self.instance_ref['vm_state'] = vm_states.ACTIVE
        self.instance_ref['task_state'] = None

        self.tracker.update_load_stats_for_instance(self.context,
                self.instance_ref)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])
