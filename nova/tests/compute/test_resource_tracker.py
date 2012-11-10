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


FAKE_VIRT_MEMORY_MB = 5
FAKE_VIRT_LOCAL_GB = 6
FAKE_VIRT_VCPUS = 1


class UnsupportedVirtDriver(driver.ComputeDriver):
    """Pretend version of a lame virt driver"""
    def __init__(self):
        super(UnsupportedVirtDriver, self).__init__(None)

    def get_available_resource(self, nodename):
        # no support for getting resource usage info
        return {}


class FakeVirtDriver(driver.ComputeDriver):

    def __init__(self):
        super(FakeVirtDriver, self).__init__(None)
        self.memory_mb = FAKE_VIRT_MEMORY_MB
        self.local_gb = FAKE_VIRT_LOCAL_GB
        self.vcpus = FAKE_VIRT_VCPUS

        self.memory_mb_used = 0
        self.local_gb_used = 0

    def get_available_resource(self, nodename):
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
        self.stubs.Set(db, 'instance_get_all_by_host_and_node',
                       lambda c, h, n: self._instances.values())
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
            "stats": [{"key": "num_instances", "value": "1"}],
           "hypervisor_hostname": "fakenode",
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
        node = "fakenode"

        if unsupported:
            driver = UnsupportedVirtDriver()
        else:
            driver = FakeVirtDriver()

        tracker = resource_tracker.ResourceTracker(host, driver, node)
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

    def test_disabled(self):
        # disabled = no compute node stats
        self.assertTrue(self.tracker.disabled)
        self.assertEqual(None, self.tracker.compute_node)

    def test_disabled_claim(self):
        # basic claim:
        instance = self._fake_instance()
        claim = self.tracker.instance_claim(self.context, instance)
        self.assertEqual(0, claim.memory_mb)

    def test_disabled_instance_claim(self):
        # instance variation:
        instance = self._fake_instance()
        claim = self.tracker.instance_claim(self.context, instance)
        self.assertEqual(0, claim.memory_mb)

    def test_disabled_instance_context_claim(self):
        # instance context manager variation:
        instance = self._fake_instance()
        claim = self.tracker.instance_claim(self.context, instance)
        with self.tracker.instance_claim(self.context, instance) as claim:
            self.assertEqual(0, claim.memory_mb)

    def test_disabled_updated_usage(self):
        instance = self._fake_instance(host='fakehost', memory_mb=5,
                root_gb=10)
        self.tracker.update_usage(self.context, instance)


class MissingServiceTestCase(BaseTestCase):
    def setUp(self):
        super(MissingServiceTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.tracker = self._tracker()

    def test_missing_service(self):
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

    def test_create_compute_node(self):
        self.tracker.update_available_resource(self.context)
        self.assertTrue(self.created)

    def test_enabled(self):
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
        self.limits = self._basic_limits()

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

    def _basic_limits(self):
        """Get basic limits, no oversubscription"""
        return {
            'memory_mb': FAKE_VIRT_MEMORY_MB * 2,
            'disk_gb': FAKE_VIRT_LOCAL_GB,
            'vcpu': FAKE_VIRT_VCPUS,
        }

    def test_update_usage_only_for_tracked(self):
        instance = self._fake_instance(memory_mb=3, root_gb=1, ephemeral_gb=1,
                task_state=None)
        self.tracker.update_usage(self.context, instance)

        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertNotEqual(0, claim.memory_mb)
        self.assertEqual(3, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])

        # now update should actually take effect
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)

        self.assertEqual(3, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(1, self.tracker.compute_node['current_workload'])

    def test_free_ram_resource_value(self):
        driver = FakeVirtDriver()
        mem_free = driver.memory_mb - driver.memory_mb_used
        self.assertEqual(mem_free, self.tracker.compute_node['free_ram_mb'])

    def test_free_disk_resource_value(self):
        driver = FakeVirtDriver()
        mem_free = driver.local_gb - driver.local_gb_used
        self.assertEqual(mem_free, self.tracker.compute_node['free_disk_gb'])

    def test_update_compute_node(self):
        self.assertFalse(self.tracker.disabled)
        self.assertTrue(self.updated)

    def test_claim_and_audit(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem, root_gb=claim_disk,
                ephemeral_gb=0)

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)

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

    def test_claim_and_abort(self):
        self.assertEqual(5, self.tracker.compute_node['memory_mb'])
        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])

        self.assertEqual(6, self.tracker.compute_node['local_gb'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])

        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem,
                root_gb=claim_disk, ephemeral_gb=0)
        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertNotEqual(None, claim)

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(claim_mem, self.compute["memory_mb_used"])
        self.assertEqual(5 - claim_mem, self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(6 - claim_disk, self.compute["free_disk_gb"])

        claim.abort()

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(0, self.compute["memory_mb_used"])
        self.assertEqual(5, self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(0, self.compute["local_gb_used"])
        self.assertEqual(6, self.compute["free_disk_gb"])

    def test_instance_claim_with_oversubscription(self):
        memory_mb = FAKE_VIRT_MEMORY_MB * 2
        root_gb = ephemeral_gb = FAKE_VIRT_LOCAL_GB
        vcpus = FAKE_VIRT_VCPUS * 2

        limits = {'memory_mb': memory_mb, 'disk_gb': root_gb * 2,
                  'vcpu': vcpus}
        instance = self._fake_instance(memory_mb=memory_mb,
                root_gb=root_gb, ephemeral_gb=ephemeral_gb)

        self.tracker.instance_claim(self.context, instance, limits)
        self.assertEqual(memory_mb,
                self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(root_gb * 2,
                self.tracker.compute_node['local_gb_used'])

    def test_additive_claims(self):
        self.limits['vcpu'] = 2

        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1,
                vcpus=1)
        with self.tracker.instance_claim(self.context, instance, self.limits):
            pass
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1,
                vcpus=1)
        with self.tracker.instance_claim(self.context, instance, self.limits):
            pass

        self.assertEqual(2, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(4, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(2, self.tracker.compute_node['vcpus_used'])

    def test_context_claim_with_exception(self):
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1)
        try:
            with self.tracker.instance_claim(self.context, instance):
                # <insert exciting things that utilize resources>
                raise test.TestingException()
        except test.TestingException:
            pass

        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(0, self.compute['memory_mb_used'])
        self.assertEqual(0, self.compute['local_gb_used'])

    def test_instance_context_claim(self):
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=1)
        with self.tracker.instance_claim(self.context, instance):
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

    def test_update_load_stats_for_instance(self):
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

        instance = self._fake_instance(task_state=task_states.SCHEDULING)
        with self.tracker.instance_claim(self.context, instance):
            pass

        self.assertEqual(1, self.tracker.compute_node['current_workload'])

        instance['vm_state'] = vm_states.ACTIVE
        instance['task_state'] = None
        instance['host'] = 'fakehost'

        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

    def test_cpu_stats(self):
        limits = {'disk_gb': 100, 'memory_mb': 100}
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        instance = self._fake_instance(vcpus=1)

        # should not do anything until a claim is made:
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        with self.tracker.instance_claim(self.context, instance, limits):
            pass
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])

        # instance state can change without modifying vcpus in use:
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])

        instance = self._fake_instance(vcpus=10)
        with self.tracker.instance_claim(self.context, instance, limits):
            pass
        self.assertEqual(11, self.tracker.compute_node['vcpus_used'])

        instance['vm_state'] = vm_states.DELETED
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(1, self.tracker.compute_node['vcpus_used'])
