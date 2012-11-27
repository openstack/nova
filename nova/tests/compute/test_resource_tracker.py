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

import uuid

from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test
from nova.virt import driver

LOG = logging.getLogger(__name__)


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

        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        self.context = context.RequestContext('fake', 'fake')

        self._instances = {}
        self.stubs.Set(db, 'instance_get_all_by_host',
                       lambda c, h: self._instances.values())
        self.stubs.Set(db, 'instance_update_and_get_original',
                       self._fake_instance_update_and_get_original)

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

    def _fake_instance(self, *args, **kwargs):

        instance_uuid = str(uuid.uuid1())
        instance = {
            'uuid': instance_uuid,
            'vm_state': vm_states.BUILDING,
            'task_state': None,
            'memory_mb': 2,
            'root_gb': 3,
            'ephemeral_gb': 1,
            'os_type': 'Linux',
            'project_id': '123456',
            'vcpus': 1,
            'host': None,
            'launched_on': None,
        }
        instance.update(kwargs)

        self._instances[instance_uuid] = instance
        return instance

    def _fake_instance_update_and_get_original(self, context, instance_uuid,
            values):
        instance = self._instances[instance_uuid]
        instance.update(values)
        # the test doesn't care what the original instance values are, it's
        # only used in the subsequent notification:
        return (instance, instance)

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
        instance = self._fake_instance()
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertEqual(None, claim)

    def testDisabledInstanceClaim(self):
        # instance variation:
        instance = self._fake_instance()
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertEqual(None, claim)

    def testDisabledInstanceContextClaim(self):
        # instance context manager variation:
        instance = self._fake_instance()
        with self.tracker.resource_claim(self.context, instance):
            pass
        self.assertEqual(0, len(self.tracker.claims))

    def testDisabledFinishClaim(self):
        self.assertEqual(None, self.tracker.finish_resource_claim(None))

    def testDisabledAbortClaim(self):
        self.assertEqual(None, self.tracker.abort_resource_claim(self.context,
            None))

    def testDisabledUpdateUsage(self):
        instance = self._fake_instance(host='fakehost', memory_mb=5,
                root_gb=10)
        self.tracker.update_usage(self.context, instance)


class MissingServiceTestCase(BaseTestCase):
    def setUp(self):
        super(MissingServiceTestCase, self).setUp()
        self.context = context.get_admin_context()
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

    def testUpdateUseOnlyForTracked(self):
        """Only update usage is a previous claim has added instance to
        list of tracked instances.
        """
        instance = self._fake_instance(memory_mb=3, root_gb=1, ephemeral_gb=1,
                task_state=None)
        self.tracker.update_usage(self.context, instance)

        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)
        self.assertEqual(3, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])

        # now update should actually take effect
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)

        self.assertEqual(3, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(1, self.tracker.compute_node['current_workload'])

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

    def testCpuUnlimited(self):
        """Test default of unlimited CPU"""
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1,
                                       vcpus=100000)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)
        self.assertEqual(100000, self.tracker.compute_node['vcpus_used'])

    def testCpuOversubscription(self):
        """Test client-supplied oversubscription of CPU"""
        self.assertEqual(1, self.tracker.compute_node['vcpus'])

        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1,
                                       vcpus=3)
        limits = {'vcpu': 5}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertNotEqual(None, claim)
        self.assertEqual(3, self.tracker.compute_node['vcpus_used'])

    def testMemoryOversubscription(self):
        """Test client-supplied oversubscription of memory"""
        instance = self._fake_instance(memory_mb=8, root_gb=1, ephemeral_gb=1)
        limits = {'memory_mb': 8}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertNotEqual(None, claim)
        self.assertEqual(8, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])

    def testDiskOversubscription(self):
        """Test client-supplied oversubscription of disk space"""
        instance = self._fake_instance(memory_mb=1, root_gb=10, ephemeral_gb=1)
        limits = {'disk_gb': 12}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertNotEqual(None, claim)
        self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(11, self.tracker.compute_node['local_gb_used'])

    def testUnlimitedMemoryClaim(self):
        """Test default of unlimited memory"""
        instance = self._fake_instance(memory_mb=200000000000, root_gb=1,
                                       ephemeral_gb=1)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)
        self.assertEqual(200000000000,
                         self.tracker.compute_node['memory_mb_used'])

    def testInsufficientMemoryClaimWithOversubscription(self):
        """Exceed oversubscribed memory limit of 10MB"""
        instance = self._fake_instance(memory_mb=10, root_gb=0,
                ephemeral_gb=0)
        limits = {'memory_mb': 10}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertNotEqual(None, claim)

        instance = self._fake_instance(memory_mb=1, root_gb=0,
                ephemeral_gb=0)
        limits = {'memory_mb': 10}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertEqual(None, claim)

    def testUnlimitDiskClaim(self):
        """Test default of unlimited disk space"""
        instance = self._fake_instance(memory_mb=0, root_gb=200000000,
                                       ephemeral_gb=0)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)
        self.assertEqual(200000000, self.tracker.compute_node['local_gb_used'])

    def testInsufficientDiskClaimWithOversubscription(self):
        """Exceed oversubscribed disk limit of 10GB"""
        instance = self._fake_instance(memory_mb=1, root_gb=4,
                ephemeral_gb=5)  # 9 GB
        limits = {'disk_gb': 10}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertNotEqual(None, claim)

        instance = self._fake_instance(memory_mb=1, root_gb=1,
                ephemeral_gb=1)  # 2 GB
        limits = {'disk_gb': 10}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertEqual(None, claim)

    def testInsufficientCpuClaim(self):
        instance = self._fake_instance(memory_mb=0, root_gb=0,
                ephemeral_gb=0, vcpus=1)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])

        instance = self._fake_instance(memory_mb=0, root_gb=0,
                ephemeral_gb=0, vcpus=1)

        limits = {'vcpu': 1}
        claim = self.tracker.begin_resource_claim(self.context, instance,
                limits)
        self.assertEqual(None, claim)

    def testClaimAndFinish(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem, root_gb=claim_disk,
                ephemeral_gb=0)
        claim = self.tracker.begin_resource_claim(self.context, instance)

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

        self.tracker.update_available_resource(self.context)

        # confirm that resource usage is derived from instance usages,
        # not virt layer:
        self.assertEqual(claim_mem, self.compute['memory_mb_used'])
        self.assertEqual(5 - claim_mem, self.compute['free_ram_mb'])

        self.assertEqual(claim_disk, self.compute['local_gb_used'])
        self.assertEqual(6 - claim_disk, self.compute['free_disk_gb'])

        # Finally, finish the claimm and update from the virt layer again.
        # Resource usage will be consistent again:
        self.tracker.finish_resource_claim(claim)
        self.tracker.update_available_resource(self.context)

        self.assertEqual(claim_mem, self.compute['memory_mb_used'])
        self.assertEqual(5 - claim_mem, self.compute['free_ram_mb'])

        self.assertEqual(claim_disk, self.compute['local_gb_used'])
        self.assertEqual(6 - claim_disk, self.compute['free_disk_gb'])

    def testClaimAndAbort(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem,
                root_gb=claim_disk, ephemeral_gb=0)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        self.assertNotEqual(None, claim)

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
        instance = self._fake_instance(memory_mb=2, root_gb=2, ephemeral_gb=0)
        claim = self.tracker.begin_resource_claim(self.context, instance)
        claim.expire_ts = timeutils.utcnow_ts() - 1
        self.assertTrue(claim.is_expired())

        # and an unexpired claim
        instance2 = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=0)
        claim2 = self.tracker.begin_resource_claim(self.context, instance2)

        self.assertEqual(2, len(self.tracker.claims))
        self.assertEqual(2 + 1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2 + 1, self.tracker.compute_node['local_gb_used'])

        # expired claims get expunged when audit runs:
        self.tracker.update_available_resource(self.context)

        self.assertEqual(1, len(self.tracker.claims))
        self.assertEqual(2, len(self.tracker.tracked_instances))

        # the expired claim's instance is assumed to still exist, so the
        # resources should be counted:
        self.assertEqual(2 + 1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2 + 1, self.tracker.compute_node['local_gb_used'])

        # this abort should do nothing because the claim was purged due to
        # expiration:
        self.tracker.abort_resource_claim(self.context, claim)

        # call finish on claim2:
        self.tracker.finish_resource_claim(claim2)

        # should have usage from both instances:
        self.assertEqual(1 + 2, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(1 + 2, self.tracker.compute_node['local_gb_used'])

    def testInstanceClaim(self):
        instance = self._fake_instance(memory_mb=1, root_gb=0, ephemeral_gb=2)
        self.tracker.begin_resource_claim(self.context, instance)
        self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])

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
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1)
        with self.tracker.resource_claim(self.context, instance):
            # <insert exciting things that utilize resources>
            self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
            self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
            self.assertEqual(1, self.compute['memory_mb_used'])
            self.assertEqual(2, self.compute['local_gb_used'])

        # after exiting claim context, build is marked as finished.  usage
        # totals should be same:
        self.tracker.update_available_resource(self.context)
        self.assertEqual(1, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(1, self.compute['memory_mb_used'])
        self.assertEqual(2, self.compute['local_gb_used'])

    def testUpdateLoadStatsForInstance(self):
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

        instance = self._fake_instance(task_state=task_states.SCHEDULING)
        with self.tracker.resource_claim(self.context, instance):
            pass

        self.assertEqual(1, self.tracker.compute_node['current_workload'])

        instance['vm_state'] = vm_states.ACTIVE
        instance['task_state'] = None
        instance['host'] = 'fakehost'

        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

    def testCpuStats(self):
        limits = {'disk_gb': 100, 'memory_mb': 100}
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        instance = self._fake_instance(vcpus=1)

        # should not do anything until a claim is made:
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        with self.tracker.resource_claim(self.context, instance, limits):
            pass
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])

        # instance state can change without modifying vcpus in use:
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])

        instance = self._fake_instance(vcpus=10)
        with self.tracker.resource_claim(self.context, instance, limits):
            pass
        self.assertEqual(11, self.tracker.compute_node['vcpus_used'])

        instance['vm_state'] = vm_states.DELETED
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])
