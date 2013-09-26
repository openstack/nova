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

"""Tests for compute resource tracking."""

import re
import uuid

from oslo.config import cfg

from nova.compute import flavors
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova.objects import base as obj_base
from nova.objects import migration as migration_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import test
from nova.tests.objects import test_migration
from nova.virt import driver


FAKE_VIRT_MEMORY_MB = 5
FAKE_VIRT_MEMORY_OVERHEAD = 1
FAKE_VIRT_LOCAL_GB = 6
FAKE_VIRT_VCPUS = 1
CONF = cfg.CONF


class UnsupportedVirtDriver(driver.ComputeDriver):
    """Pretend version of a lame virt driver."""

    def __init__(self):
        super(UnsupportedVirtDriver, self).__init__(None)

    def get_host_ip_addr(self):
        return '127.0.0.1'

    def get_available_resource(self, nodename):
        # no support for getting resource usage info
        return {}


class FakeVirtDriver(driver.ComputeDriver):

    def __init__(self, pci_support=False):
        super(FakeVirtDriver, self).__init__(None)
        self.memory_mb = FAKE_VIRT_MEMORY_MB
        self.local_gb = FAKE_VIRT_LOCAL_GB
        self.vcpus = FAKE_VIRT_VCPUS

        self.memory_mb_used = 0
        self.local_gb_used = 0
        self.pci_support = pci_support

    def get_host_ip_addr(self):
        return '127.0.0.1'

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
        if self.pci_support:
            d['pci_passthrough_devices'] = jsonutils.dumps([{
                    'label': 'forza-napoli',
                    'dev_type': 'foo',
                    'compute_node_id': 1,
                    'address': '0000:00:00.1',
                    'product_id': 'p1',
                    'vendor_id': 'v1',
                    'status': 'available',
                    'extra_k1': 'v1'}])
        return d

    def estimate_instance_overhead(self, instance_info):
        mem = instance_info['memory_mb']  # make sure memory value is present
        overhead = {
            'memory_mb': FAKE_VIRT_MEMORY_OVERHEAD
        }
        return overhead  # just return a constant value for testing


class BaseTestCase(test.TestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()

        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        self.context = context.get_admin_context()

        self.flags(use_local=True, group='conductor')
        self.conductor = self.start_service('conductor',
                                            manager=CONF.conductor.manager)

        self._instances = {}
        self._instance_types = {}

        self.stubs.Set(self.conductor.db,
                       'instance_get_all_by_host_and_node',
                       self._fake_instance_get_all_by_host_and_node)
        self.stubs.Set(self.conductor.db,
                       'instance_update_and_get_original',
                       self._fake_instance_update_and_get_original)
        self.stubs.Set(self.conductor.db,
                       'flavor_get', self._fake_flavor_get)

        self.host = 'fakehost'

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

    def _fake_instance_system_metadata(self, instance_type, prefix=''):
        sys_meta = []
        for key in flavors.system_metadata_flavor_props.keys():
            sys_meta.append({'key': '%sinstance_type_%s' % (prefix, key),
                             'value': instance_type[key]})
        return sys_meta

    def _fake_instance(self, stash=True, **kwargs):

        # Default to an instance ready to resize to or from the same
        # instance_type
        itype = self._fake_flavor_create()
        sys_meta = self._fake_instance_system_metadata(itype)

        if stash:
            # stash instance types in system metadata.
            sys_meta = (sys_meta +
                        self._fake_instance_system_metadata(itype, 'new_') +
                        self._fake_instance_system_metadata(itype, 'old_'))

        instance_uuid = str(uuid.uuid1())
        instance = {
            'uuid': instance_uuid,
            'vm_state': vm_states.RESIZED,
            'task_state': None,
            'memory_mb': 2,
            'root_gb': 3,
            'ephemeral_gb': 1,
            'os_type': 'Linux',
            'project_id': '123456',
            'vcpus': 1,
            'host': None,
            'node': None,
            'instance_type_id': 1,
            'launched_on': None,
            'system_metadata': sys_meta,
            'availability_zone': None,
            'vm_mode': None,
            'reservation_id': None,
            'display_name': None,
            'default_swap_device': None,
            'power_state': None,
            'scheduled_at': None,
            'access_ip_v6': None,
            'access_ip_v4': None,
            'key_name': None,
            'updated_at': None,
            'cell_name': None,
            'locked': None,
            'locked_by': None,
            'launch_index': None,
            'architecture': None,
            'auto_disk_config': None,
            'terminated_at': None,
            'ramdisk_id': None,
            'user_data': None,
            'cleaned': None,
            'deleted_at': None,
            'id': 333,
            'disable_terminate': None,
            'hostname': None,
            'display_description': None,
            'key_data': None,
            'deleted': None,
            'default_ephemeral_device': None,
            'progress': None,
            'launched_at': None,
            'config_drive': None,
            'kernel_id': None,
            'user_id': None,
            'shutdown_terminate': None,
            'created_at': None,
            'image_ref': None,
            'root_device_name': None,
        }
        instance.update(kwargs)

        self._instances[instance_uuid] = instance
        return instance

    def _fake_flavor_create(self, **kwargs):
        instance_type = {
            'id': 1,
            'name': 'fakeitype',
            'memory_mb': FAKE_VIRT_MEMORY_MB,
            'vcpus': FAKE_VIRT_VCPUS,
            'root_gb': FAKE_VIRT_LOCAL_GB / 2,
            'ephemeral_gb': FAKE_VIRT_LOCAL_GB / 2,
            'swap': 0,
            'rxtx_factor': 1.0,
            'vcpu_weight': 1,
            'flavorid': 'fakeflavor'
        }
        instance_type.update(**kwargs)

        id_ = instance_type['id']
        self._instance_types[id_] = instance_type
        return instance_type

    def _fake_instance_get_all_by_host_and_node(self, context, host, nodename):
        return [i for i in self._instances.values() if i['host'] == host]

    def _fake_flavor_get(self, ctxt, id_):
        return self._instance_types[id_]

    def _fake_instance_update_and_get_original(self, context, instance_uuid,
            values):
        instance = self._instances[instance_uuid]
        instance.update(values)
        # the test doesn't care what the original instance values are, it's
        # only used in the subsequent notification:
        return (instance, instance)

    def _driver(self):
        return FakeVirtDriver()

    def _tracker(self, host=None):

        if host is None:
            host = self.host

        node = "fakenode"

        driver = self._driver()

        tracker = resource_tracker.ResourceTracker(host, driver, node)
        return tracker


class UnsupportedDriverTestCase(BaseTestCase):
    """Resource tracking should be disabled when the virt driver doesn't
    support it.
    """
    def setUp(self):
        super(UnsupportedDriverTestCase, self).setUp()
        self.tracker = self._tracker()
        # seed tracker with data:
        self.tracker.update_available_resource(self.context)

    def _driver(self):
        return UnsupportedVirtDriver()

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

    def test_disabled_resize_claim(self):
        instance = self._fake_instance()
        instance_type = self._fake_flavor_create()
        claim = self.tracker.resize_claim(self.context, instance,
                instance_type)
        self.assertEqual(0, claim.memory_mb)
        self.assertEqual(instance['uuid'], claim.migration['instance_uuid'])
        self.assertEqual(instance_type['id'],
                claim.migration['new_instance_type_id'])

    def test_disabled_resize_context_claim(self):
        instance = self._fake_instance()
        instance_type = self._fake_flavor_create()
        with self.tracker.resize_claim(self.context, instance, instance_type) \
                                       as claim:
            self.assertEqual(0, claim.memory_mb)


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

        self.stubs.Set(db, 'service_get_by_compute_host',
                self._fake_service_get_by_compute_host)
        self.stubs.Set(db, 'compute_node_create',
                self._fake_create_compute_node)

    def _fake_create_compute_node(self, context, values):
        self.created = True
        return self._create_compute_node()

    def _fake_service_get_by_compute_host(self, ctx, host):
        # return a service with no joined compute
        service = self._create_service()
        return service

    def test_create_compute_node(self):
        self.tracker.update_available_resource(self.context)
        self.assertTrue(self.created)

    def test_enabled(self):
        self.tracker.update_available_resource(self.context)
        self.assertFalse(self.tracker.disabled)


class BaseTrackerTestCase(BaseTestCase):

    def setUp(self):
        # setup plumbing for a working resource tracker with required
        # database models and a compatible compute driver:
        super(BaseTrackerTestCase, self).setUp()

        self.updated = False
        self.deleted = False

        self.tracker = self._tracker()
        self._migrations = {}

        self.stubs.Set(db, 'service_get_by_compute_host',
                self._fake_service_get_by_compute_host)
        self.stubs.Set(db, 'compute_node_update',
                self._fake_compute_node_update)
        self.stubs.Set(db, 'compute_node_delete',
                self._fake_compute_node_delete)
        self.stubs.Set(db, 'migration_update',
                self._fake_migration_update)
        self.stubs.Set(db, 'migration_get_in_progress_by_host_and_node',
                self._fake_migration_get_in_progress_by_host_and_node)

        self.tracker.update_available_resource(self.context)
        self.limits = self._limits()

    def _fake_service_get_by_compute_host(self, ctx, host):
        self.compute = self._create_compute_node()
        self.service = self._create_service(host, compute=self.compute)
        return self.service

    def _fake_compute_node_update(self, ctx, compute_node_id, values,
            prune_stats=False):
        self.updated = True
        values['stats'] = [{"key": "num_instances", "value": "1"}]

        self.compute.update(values)
        return self.compute

    def _fake_compute_node_delete(self, ctx, compute_node_id):
        self.deleted = True
        self.compute.update({'deleted': 1})
        return self.compute

    def _fake_migration_get_in_progress_by_host_and_node(self, ctxt, host,
                                                         node):
        status = ['confirmed', 'reverted']
        migrations = []

        for migration in self._migrations.values():
            migration = obj_base.obj_to_primitive(migration)
            if migration['status'] in status:
                continue

            uuid = migration['instance_uuid']
            migration['instance'] = self._instances[uuid]
            migrations.append(migration)

        return migrations

    def _fake_migration_update(self, ctxt, migration_id, values):
        # cheat and assume there's only 1 migration present
        migration = self._migrations.values()[0]
        migration.update(values)
        return migration

    def _limits(self, memory_mb=FAKE_VIRT_MEMORY_MB +
            FAKE_VIRT_MEMORY_OVERHEAD, disk_gb=FAKE_VIRT_LOCAL_GB,
            vcpus=FAKE_VIRT_VCPUS):
        """Create limits dictionary used for oversubscribing resources."""

        return {
            'memory_mb': memory_mb,
            'disk_gb': disk_gb,
            'vcpu': vcpus
        }

    def _assert(self, value, field, tracker=None):

        if tracker is None:
            tracker = self.tracker

        if field not in tracker.compute_node:
            raise test.TestingException(
                "'%(field)s' not in compute node." % {'field': field})
        x = tracker.compute_node[field]

        self.assertEqual(value, x)


class TrackerTestCase(BaseTrackerTestCase):

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

    def test_init(self):
        self._assert(FAKE_VIRT_MEMORY_MB, 'memory_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus')
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')
        self._assert(0, 'running_vms')
        self._assert(FAKE_VIRT_MEMORY_MB, 'free_ram_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'free_disk_gb')
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])
        self._assert('{}', 'pci_stats')


class TrackerPciStatsTestCase(BaseTrackerTestCase):

    def test_update_compute_node(self):
        self.assertFalse(self.tracker.disabled)
        self.assertTrue(self.updated)

    def test_init(self):
        self._assert(FAKE_VIRT_MEMORY_MB, 'memory_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus')
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')
        self._assert(0, 'running_vms')
        self._assert(FAKE_VIRT_MEMORY_MB, 'free_ram_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'free_disk_gb')
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])
        expected = """[{"count": 1,
                        "vendor_id": "v1",
                        "product_id": "p1",
                        "extra_info": {"extra_k1": "v1"}}]"""
        expected = re.sub(r'\s+', '', expected)
        pci = re.sub(r'\s+', '', self.tracker.compute_node['pci_stats'])
        self.assertEqual(expected, pci)

    def _driver(self):
        return FakeVirtDriver(pci_support=True)


class InstanceClaimTestCase(BaseTrackerTestCase):

    def test_update_usage_only_for_tracked(self):
        instance = self._fake_instance(memory_mb=3, root_gb=1, ephemeral_gb=1,
                task_state=None)
        self.tracker.update_usage(self.context, instance)

        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'current_workload')

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertNotEqual(0, claim.memory_mb)
        self._assert(3 + FAKE_VIRT_MEMORY_OVERHEAD, 'memory_mb_used')
        self._assert(2, 'local_gb_used')

        # now update should actually take effect
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)

        self._assert(3 + FAKE_VIRT_MEMORY_OVERHEAD, 'memory_mb_used')
        self._assert(2, 'local_gb_used')
        self._assert(1, 'current_workload')

    def test_claim_and_audit(self):
        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem, root_gb=claim_disk,
                ephemeral_gb=0)

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)

        self.assertEqual(5, self.compute["memory_mb"])
        self.assertEqual(claim_mem + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute["memory_mb_used"])
        self.assertEqual(5 - claim_mem - FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute["free_ram_mb"])

        self.assertEqual(6, self.compute["local_gb"])
        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(6 - claim_disk, self.compute["free_disk_gb"])

        # 1st pretend that the compute operation finished and claimed the
        # desired resources from the virt layer
        driver = self.tracker.driver
        driver.memory_mb_used = claim_mem
        driver.local_gb_used = claim_disk

        self.tracker.update_available_resource(self.context)

        # confirm tracker is adding in host_ip
        self.assertTrue(self.compute.get('host_ip') is not None)

        # confirm that resource usage is derived from instance usages,
        # not virt layer:
        self.assertEqual(claim_mem + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute['memory_mb_used'])
        self.assertEqual(5 - claim_mem - FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute['free_ram_mb'])

        self.assertEqual(claim_disk, self.compute['local_gb_used'])
        self.assertEqual(6 - claim_disk, self.compute['free_disk_gb'])

    def test_claim_and_abort(self):
        claim_mem = 3
        claim_disk = 2
        instance = self._fake_instance(memory_mb=claim_mem,
                root_gb=claim_disk, ephemeral_gb=0)
        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertNotEqual(None, claim)

        self.assertEqual(claim_mem + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute["memory_mb_used"])
        self.assertEqual(5 - claim_mem - FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute["free_ram_mb"])

        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(6 - claim_disk, self.compute["free_disk_gb"])

        claim.abort()

        self.assertEqual(0, self.compute["memory_mb_used"])
        self.assertEqual(5, self.compute["free_ram_mb"])

        self.assertEqual(0, self.compute["local_gb_used"])
        self.assertEqual(6, self.compute["free_disk_gb"])

    def test_instance_claim_with_oversubscription(self):
        memory_mb = FAKE_VIRT_MEMORY_MB * 2
        root_gb = ephemeral_gb = FAKE_VIRT_LOCAL_GB
        vcpus = FAKE_VIRT_VCPUS * 2

        limits = {'memory_mb': memory_mb + FAKE_VIRT_MEMORY_OVERHEAD,
                  'disk_gb': root_gb * 2,
                  'vcpu': vcpus}
        instance = self._fake_instance(memory_mb=memory_mb,
                root_gb=root_gb, ephemeral_gb=ephemeral_gb)

        self.tracker.instance_claim(self.context, instance, limits)
        self.assertEqual(memory_mb + FAKE_VIRT_MEMORY_OVERHEAD,
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

        self.assertEqual(2 + 2 * FAKE_VIRT_MEMORY_OVERHEAD,
                         self.tracker.compute_node['memory_mb_used'])
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
            self.assertEqual(1 + FAKE_VIRT_MEMORY_OVERHEAD,
                             self.tracker.compute_node['memory_mb_used'])
            self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
            self.assertEqual(1 + FAKE_VIRT_MEMORY_OVERHEAD,
                             self.compute['memory_mb_used'])
            self.assertEqual(2, self.compute['local_gb_used'])

        # after exiting claim context, build is marked as finished.  usage
        # totals should be same:
        self.tracker.update_available_resource(self.context)
        self.assertEqual(1 + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2, self.tracker.compute_node['local_gb_used'])
        self.assertEqual(1 + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute['memory_mb_used'])
        self.assertEqual(2, self.compute['local_gb_used'])

    def test_update_load_stats_for_instance(self):

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

    def test_skip_deleted_instances(self):
        # ensure that the audit process skips instances that have vm_state
        # DELETED, but the DB record is not yet deleted.
        self._fake_instance(vm_state=vm_states.DELETED, host=self.host)
        self.tracker.update_available_resource(self.context)

        self.assertEqual(0, self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(0, self.tracker.compute_node['local_gb_used'])


class ResizeClaimTestCase(BaseTrackerTestCase):

    def setUp(self):
        super(ResizeClaimTestCase, self).setUp()

        def _fake_migration_create(mig_self, ctxt):
            self._migrations[mig_self.instance_uuid] = mig_self
            mig_self.obj_reset_changes()

        self.stubs.Set(migration_obj.Migration, 'create',
                       _fake_migration_create)

        self.instance = self._fake_instance()
        self.instance_type = self._fake_flavor_create()

    def _fake_migration_create(self, context, values=None):
        instance_uuid = str(uuid.uuid1())
        mig_dict = test_migration.fake_db_migration()
        mig_dict.update({
            'id': 1,
            'source_compute': 'host1',
            'source_node': 'fakenode',
            'dest_compute': 'host2',
            'dest_node': 'fakenode',
            'dest_host': '127.0.0.1',
            'old_instance_type_id': 1,
            'new_instance_type_id': 2,
            'instance_uuid': instance_uuid,
            'status': 'pre-migrating',
            'updated_at': timeutils.utcnow()
            })
        if values:
            mig_dict.update(values)

        migration = migration_obj.Migration()
        migration.update(mig_dict)
        # This hits the stub in setUp()
        migration.create('fake')

    def test_claim(self):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, self.limits)
        self._assert(FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')
        self.assertEqual(1, len(self.tracker.tracked_migrations))

    def test_abort(self):
        try:
            with self.tracker.resize_claim(self.context, self.instance,
                    self.instance_type, self.limits):
                raise test.TestingException("abort")
        except test.TestingException:
            pass

        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')
        self.assertEqual(0, len(self.tracker.tracked_migrations))

    def test_additive_claims(self):

        limits = self._limits(FAKE_VIRT_MEMORY_MB * 2 +
                                FAKE_VIRT_MEMORY_OVERHEAD * 2,
                              FAKE_VIRT_LOCAL_GB * 2,
                              FAKE_VIRT_VCPUS * 2)
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, limits)
        instance2 = self._fake_instance()
        self.tracker.resize_claim(self.context, instance2, self.instance_type,
                limits)

        self._assert(2 * FAKE_VIRT_MEMORY_MB + 2 * FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used')
        self._assert(2 * FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(2 * FAKE_VIRT_VCPUS, 'vcpus_used')

    def test_claim_and_audit(self):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, self.limits)

        self.tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')

    def test_same_host(self):
        self.limits['vcpu'] = 3

        src_type = self._fake_flavor_create(id=2, memory_mb=1,
                root_gb=1, ephemeral_gb=0, vcpus=1)
        dest_type = self._fake_flavor_create(id=2, memory_mb=2,
                root_gb=2, ephemeral_gb=1, vcpus=2)

        # make an instance of src_type:
        instance = self._fake_instance(memory_mb=1, root_gb=1, ephemeral_gb=0,
                vcpus=1, instance_type_id=2)
        instance['system_metadata'] = self._fake_instance_system_metadata(
            dest_type)
        self.tracker.instance_claim(self.context, instance, self.limits)

        # resize to dest_type:
        claim = self.tracker.resize_claim(self.context, instance,
                dest_type, self.limits)

        self._assert(3 + FAKE_VIRT_MEMORY_OVERHEAD * 2, 'memory_mb_used')
        self._assert(4, 'local_gb_used')
        self._assert(3, 'vcpus_used')

        self.tracker.update_available_resource(self.context)
        claim.abort()

        # only the original instance should remain, not the migration:
        self._assert(1 + FAKE_VIRT_MEMORY_OVERHEAD, 'memory_mb_used')
        self._assert(1, 'local_gb_used')
        self._assert(1, 'vcpus_used')
        self.assertEqual(1, len(self.tracker.tracked_instances))
        self.assertEqual(0, len(self.tracker.tracked_migrations))

    def test_revert(self):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, self.limits)
        self.tracker.drop_resize_claim(self.instance)

        self.assertEqual(0, len(self.tracker.tracked_instances))
        self.assertEqual(0, len(self.tracker.tracked_migrations))
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')

    def test_revert_reserve_source(self):
        # if a revert has started at the API and audit runs on
        # the source compute before the instance flips back to source,
        # resources should still be held at the source based on the
        # migration:
        dest = "desthost"
        dest_tracker = self._tracker(host=dest)
        dest_tracker.update_available_resource(self.context)

        self.instance = self._fake_instance(memory_mb=FAKE_VIRT_MEMORY_MB,
                root_gb=FAKE_VIRT_LOCAL_GB, ephemeral_gb=0,
                vcpus=FAKE_VIRT_VCPUS, instance_type_id=1)

        values = {'source_compute': self.host, 'dest_compute': dest,
                  'old_instance_type_id': 1, 'new_instance_type_id': 1,
                  'status': 'post-migrating',
                  'instance_uuid': self.instance['uuid']}
        migration = self._fake_migration_create(self.context, values)

        # attach an instance to the destination host tracker:
        dest_tracker.instance_claim(self.context, self.instance)

        self._assert(FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used', tracker=dest_tracker)
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used',
                     tracker=dest_tracker)
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used',
                     tracker=dest_tracker)

        # audit and recheck to confirm migration doesn't get double counted
        # on dest:
        dest_tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used', tracker=dest_tracker)
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used',
                     tracker=dest_tracker)
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used',
                     tracker=dest_tracker)

        # apply the migration to the source host tracker:
        self.tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')

        # flag the instance and migration as reverting and re-audit:
        self.instance['vm_state'] = vm_states.RESIZED
        self.instance['task_state'] = task_states.RESIZE_REVERTING
        self.tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_MB + 1, 'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')

    def test_resize_filter(self):
        instance = self._fake_instance(vm_state=vm_states.ACTIVE,
                task_state=task_states.SUSPENDING)
        self.assertFalse(self.tracker._instance_in_resize_state(instance))

        instance = self._fake_instance(vm_state=vm_states.RESIZED,
                task_state=task_states.SUSPENDING)
        self.assertTrue(self.tracker._instance_in_resize_state(instance))

        instance = self._fake_instance(vm_state=vm_states.ACTIVE,
                task_state=task_states.RESIZE_MIGRATING)
        self.assertTrue(self.tracker._instance_in_resize_state(instance))

    def test_dupe_filter(self):
        self._fake_flavor_create(id=2, memory_mb=1, root_gb=1,
                ephemeral_gb=1, vcpus=1)

        instance = self._fake_instance(host=self.host)

        values = {'source_compute': self.host, 'dest_compute': self.host,
                  'instance_uuid': instance['uuid'], 'new_instance_type_id': 2}
        self._fake_migration_create(self.context, values)
        self._fake_migration_create(self.context, values)

        self.tracker.update_available_resource(self.context)
        self.assertEqual(1, len(self.tracker.tracked_migrations))

    def test_set_instance_host_and_node(self):
        instance = self._fake_instance()
        self.assertEqual(None, instance['host'])
        self.assertEqual(None, instance['launched_on'])
        self.assertEqual(None, instance['node'])

        claim = self.tracker.instance_claim(self.context, instance)
        self.assertNotEqual(0, claim.memory_mb)

        self.assertEqual('fakehost', instance['host'])
        self.assertEqual('fakehost', instance['launched_on'])
        self.assertEqual('fakenode', instance['node'])


class NoInstanceTypesInSysMetadata(ResizeClaimTestCase):
    """Make sure we handle the case where the following are true:
    1) Compute node C gets upgraded to code that looks for instance types in
       system metadata. AND
    2) C already has instances in the process of migrating that do not have
       stashed instance types.

    bug 1164110
    """
    def setUp(self):
        super(NoInstanceTypesInSysMetadata, self).setUp()
        self.instance = self._fake_instance(stash=False)


class OrphanTestCase(BaseTrackerTestCase):
    def _driver(self):
        class OrphanVirtDriver(FakeVirtDriver):
            def get_per_instance_usage(self):
                return {
                    '1-2-3-4-5': {'memory_mb': 4, 'uuid': '1-2-3-4-5'},
                    '2-3-4-5-6': {'memory_mb': 4, 'uuid': '2-3-4-5-6'},

                }

        return OrphanVirtDriver()

    def test_usage(self):
        # 2 instances, 4 mb each, plus overhead
        self.assertEqual(8 + 2 * FAKE_VIRT_MEMORY_OVERHEAD,
                self.tracker.compute_node['memory_mb_used'])

    def test_find(self):
        # create one legit instance and verify the 2 orphans remain
        self._fake_instance()
        orphans = self.tracker._find_orphaned_instances()

        self.assertEqual(2, len(orphans))
