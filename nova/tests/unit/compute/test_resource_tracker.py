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

import uuid

import mock
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import timeutils

from nova.compute import flavors
from nova.compute import resource_tracker
from nova.compute import resources
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import objects
from nova.objects import base as obj_base
from nova import rpc
from nova import test
from nova.tests.unit.compute.monitors import test_monitors
from nova.tests.unit.objects import test_migration
from nova.tests.unit.pci import fakes as pci_fakes
from nova.virt import driver
from nova.virt import hardware


FAKE_VIRT_MEMORY_MB = 5
FAKE_VIRT_MEMORY_OVERHEAD = 1
FAKE_VIRT_MEMORY_WITH_OVERHEAD = (
        FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD)
FAKE_VIRT_NUMA_TOPOLOGY = objects.NUMATopology(
        cells=[objects.NUMACell(id=0, cpuset=set([1, 2]), memory=3072,
                                cpu_usage=0, memory_usage=0, mempages=[]),
               objects.NUMACell(id=1, cpuset=set([3, 4]), memory=3072,
                                cpu_usage=0, memory_usage=0, mempages=[])])
FAKE_VIRT_NUMA_TOPOLOGY_OVERHEAD = hardware.VirtNUMALimitTopology(
        cells=[hardware.VirtNUMATopologyCellLimit(
                    0, set([1, 2]), 3072, 4, 10240),
               hardware.VirtNUMATopologyCellLimit(
                    1, set([3, 4]), 3072, 4, 10240)])
ROOT_GB = 5
EPHEMERAL_GB = 1
FAKE_VIRT_LOCAL_GB = ROOT_GB + EPHEMERAL_GB
FAKE_VIRT_VCPUS = 1
FAKE_VIRT_STATS = {'virt_stat': 10}
FAKE_VIRT_STATS_JSON = jsonutils.dumps(FAKE_VIRT_STATS)
RESOURCE_NAMES = ['vcpu']
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

    def __init__(self, pci_support=False, stats=None,
                 numa_topology=FAKE_VIRT_NUMA_TOPOLOGY):
        super(FakeVirtDriver, self).__init__(None)
        self.memory_mb = FAKE_VIRT_MEMORY_MB
        self.local_gb = FAKE_VIRT_LOCAL_GB
        self.vcpus = FAKE_VIRT_VCPUS
        self.numa_topology = numa_topology

        self.memory_mb_used = 0
        self.local_gb_used = 0
        self.pci_support = pci_support
        self.pci_devices = [
            {
                'label': 'label_8086_0443',
                'dev_type': 'type-VF',
                'compute_node_id': 1,
                'address': '0000:00:01.1',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1'
            },
            {
                'label': 'label_8086_0443',
                'dev_type': 'type-VF',
                'compute_node_id': 1,
                'address': '0000:00:01.2',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1'
            },
            {
                'label': 'label_8086_0443',
                'dev_type': 'type-PF',
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1'
            },
            {
                'label': 'label_8086_0123',
                'dev_type': 'type-PCI',
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '0123',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1'
            },
            {
                'label': 'label_8086_7891',
                'dev_type': 'type-VF',
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '7891',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1'
            },
        ] if self.pci_support else []
        self.pci_stats = [
            {
                'count': 2,
                'vendor_id': '8086',
                'product_id': '0443'
            },
            {
                'count': 1,
                'vendor_id': '8086',
                'product_id': '7891'
            },
        ] if self.pci_support else []
        if stats is not None:
            self.stats = stats

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
            'numa_topology': (
                self.numa_topology._to_json() if self.numa_topology else None),
        }
        if self.pci_support:
            d['pci_passthrough_devices'] = jsonutils.dumps(self.pci_devices)
        if hasattr(self, 'stats'):
            d['stats'] = self.stats
        return d

    def estimate_instance_overhead(self, instance_info):
        instance_info['memory_mb']  # make sure memory value is present
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

        self.flags(pci_passthrough_whitelist=[
            '{"vendor_id": "8086", "product_id": "0443"}',
            '{"vendor_id": "8086", "product_id": "7891"}'])
        self.flags(use_local=True, group='conductor')
        self.conductor = self.start_service('conductor',
                                            manager=CONF.conductor.manager)

        self._instances = {}
        self._numa_topologies = {}
        self._instance_types = {}

        self.stubs.Set(self.conductor.db,
                       'instance_get_all_by_host_and_node',
                       self._fake_instance_get_all_by_host_and_node)
        self.stubs.Set(db, 'instance_extra_get_by_instance_uuid',
                       self._fake_instance_extra_get_by_instance_uuid)
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
            "host": "fakehost",
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
            "numa_topology": None,
            "stats": {
                "num_instances": "1",
            },
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

    def _fake_instance(self, stash=True, flavor=None, **kwargs):

        # Default to an instance ready to resize to or from the same
        # instance_type
        flavor = flavor or self._fake_flavor_create()
        sys_meta = self._fake_instance_system_metadata(flavor)

        if stash:
            # stash instance types in system metadata.
            sys_meta = (sys_meta +
                        self._fake_instance_system_metadata(flavor, 'new_') +
                        self._fake_instance_system_metadata(flavor, 'old_'))

        instance_uuid = str(uuid.uuid1())
        instance = {
            'uuid': instance_uuid,
            'vm_state': vm_states.RESIZED,
            'task_state': None,
            'ephemeral_key_uuid': None,
            'os_type': 'Linux',
            'project_id': '123456',
            'host': None,
            'node': None,
            'instance_type_id': flavor['id'],
            'memory_mb': flavor['memory_mb'],
            'vcpus': flavor['vcpus'],
            'root_gb': flavor['root_gb'],
            'ephemeral_gb': flavor['ephemeral_gb'],
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
        extra = {
            'id': 1, 'created_at': None, 'updated_at': None,
            'deleted_at': None, 'deleted': None,
            'instance_uuid': instance['uuid'],
            'numa_topology': None,
            'pci_requests': None,
        }

        numa_topology = kwargs.pop('numa_topology', None)
        if numa_topology:
            extra['numa_topology'] = numa_topology._to_json()

        instance.update(kwargs)
        instance['extra'] = extra

        self._instances[instance_uuid] = instance
        self._numa_topologies[instance_uuid] = extra
        return instance

    def _fake_flavor_create(self, **kwargs):
        instance_type = {
            'id': 1,
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            'disabled': False,
            'is_public': True,
            'name': 'fakeitype',
            'memory_mb': FAKE_VIRT_MEMORY_MB,
            'vcpus': FAKE_VIRT_VCPUS,
            'root_gb': ROOT_GB,
            'ephemeral_gb': EPHEMERAL_GB,
            'swap': 0,
            'rxtx_factor': 1.0,
            'vcpu_weight': 1,
            'flavorid': 'fakeflavor',
            'extra_specs': {},
        }
        instance_type.update(**kwargs)

        id_ = instance_type['id']
        self._instance_types[id_] = instance_type
        return instance_type

    def _fake_instance_get_all_by_host_and_node(self, context, host, nodename,
                                                columns_to_join=None):
        return [i for i in self._instances.values() if i['host'] == host]

    def _fake_instance_extra_get_by_instance_uuid(self, context,
                                                  instance_uuid, columns=None):
        return self._numa_topologies.get(instance_uuid)

    def _fake_flavor_get(self, ctxt, id_):
        return self._instance_types[id_]

    def _fake_instance_update_and_get_original(self, context, instance_uuid,
                                               values, columns_to_join=None):
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
        tracker.ext_resources_handler = \
            resources.ResourceHandler(RESOURCE_NAMES, True)
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
        self.assertIsNone(self.tracker.compute_node)

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
        self.tracker.scheduler_client.update_resource_stats = mock.Mock()

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
        self.update_call_count = 0

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

        # Note that this must be called before the call to _init_tracker()
        patcher = pci_fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)

        self._init_tracker()
        self.limits = self._limits()

    def _fake_service_get_by_compute_host(self, ctx, host):
        self.compute = self._create_compute_node()
        self.service = self._create_service(host, compute=self.compute)
        return self.service

    def _fake_compute_node_update(self, ctx, compute_node_id, values,
            prune_stats=False):
        self.update_call_count += 1
        self.updated = True
        self.compute.update(values)
        return self.compute

    def _fake_compute_node_delete(self, ctx, compute_node_id):
        self.deleted = True
        self.compute.update({'deleted': 1})
        return self.compute

    def _fake_migration_get_in_progress_by_host_and_node(self, ctxt, host,
                                                         node):
        status = ['confirmed', 'reverted', 'error']
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

    def _init_tracker(self):
        self.tracker.update_available_resource(self.context)

    def _limits(self, memory_mb=FAKE_VIRT_MEMORY_WITH_OVERHEAD,
            disk_gb=FAKE_VIRT_LOCAL_GB,
            vcpus=FAKE_VIRT_VCPUS,
            numa_topology=FAKE_VIRT_NUMA_TOPOLOGY_OVERHEAD):
        """Create limits dictionary used for oversubscribing resources."""

        return {
            'memory_mb': memory_mb,
            'disk_gb': disk_gb,
            'vcpu': vcpus,
            'numa_topology': numa_topology.to_json() if numa_topology else None
        }

    def assertEqualNUMAHostTopology(self, expected, got):
        attrs = ('cpuset', 'memory', 'id', 'cpu_usage', 'memory_usage')
        if None in (expected, got):
            if expected != got:
                raise AssertionError("Topologies don't match. Expected: "
                                     "%(expected)s, but got: %(got)s" %
                                     {'expected': expected, 'got': got})
            else:
                return

        if len(expected) != len(got):
            raise AssertionError("Topologies don't match due to different "
                                 "number of cells. Expected: "
                                 "%(expected)s, but got: %(got)s" %
                                 {'expected': expected, 'got': got})
        for exp_cell, got_cell in zip(expected.cells, got.cells):
            for attr in attrs:
                if getattr(exp_cell, attr) != getattr(got_cell, attr):
                    raise AssertionError("Topologies don't match. Expected: "
                                         "%(expected)s, but got: %(got)s" %
                                         {'expected': expected, 'got': got})

    def _assert(self, value, field, tracker=None):

        if tracker is None:
            tracker = self.tracker

        if field not in tracker.compute_node:
            raise test.TestingException(
                "'%(field)s' not in compute node." % {'field': field})
        x = tracker.compute_node[field]

        if field == 'numa_topology':
            self.assertEqualNUMAHostTopology(
                    value, objects.NUMATopology.obj_from_db_obj(x))
        else:
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
        driver = self._driver()
        self._assert(FAKE_VIRT_MEMORY_MB, 'memory_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus')
        self._assert(FAKE_VIRT_NUMA_TOPOLOGY, 'numa_topology')
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')
        self._assert(0, 'running_vms')
        self._assert(FAKE_VIRT_MEMORY_MB, 'free_ram_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'free_disk_gb')
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])
        self.assertEqual(driver.pci_stats,
            jsonutils.loads(self.tracker.compute_node['pci_stats']))


class SchedulerClientTrackerTestCase(BaseTrackerTestCase):

    def setUp(self):
        super(SchedulerClientTrackerTestCase, self).setUp()
        self.tracker.scheduler_client.update_resource_stats = mock.Mock()

    def test_create_resource(self):
        self.tracker._write_ext_resources = mock.Mock()
        self.tracker.conductor_api.compute_node_create = mock.Mock(
            return_value=dict(id=1))
        values = {'stats': {}, 'foo': 'bar', 'baz_count': 0}
        self.tracker._create(self.context, values)

        expected = {'stats': '{}', 'foo': 'bar', 'baz_count': 0,
                    'id': 1}
        self.tracker.scheduler_client.update_resource_stats.\
            assert_called_once_with(self.context,
                                    ("fakehost", "fakenode"),
                                    expected)

    def test_update_resource(self):
        self.tracker._write_ext_resources = mock.Mock()
        values = {'stats': {}, 'foo': 'bar', 'baz_count': 0}
        self.tracker._update(self.context, values)

        expected = {'stats': '{}', 'foo': 'bar', 'baz_count': 0,
                    'id': 1}
        self.tracker.scheduler_client.update_resource_stats.\
            assert_called_once_with(self.context,
                                    ("fakehost", "fakenode"),
                                    expected)


class TrackerPciStatsTestCase(BaseTrackerTestCase):

    def test_update_compute_node(self):
        self.assertFalse(self.tracker.disabled)
        self.assertTrue(self.updated)

    def test_init(self):
        driver = self._driver()
        self._assert(FAKE_VIRT_MEMORY_MB, 'memory_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus')
        self._assert(FAKE_VIRT_NUMA_TOPOLOGY, 'numa_topology')
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')
        self._assert(0, 'running_vms')
        self._assert(FAKE_VIRT_MEMORY_MB, 'free_ram_mb')
        self._assert(FAKE_VIRT_LOCAL_GB, 'free_disk_gb')
        self.assertFalse(self.tracker.disabled)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])
        self.assertEqual(driver.pci_stats,
            jsonutils.loads(self.tracker.compute_node['pci_stats']))

    def _driver(self):
        return FakeVirtDriver(pci_support=True)


class TrackerExtraResourcesTestCase(BaseTrackerTestCase):

    def setUp(self):
        super(TrackerExtraResourcesTestCase, self).setUp()
        self.driver = self._driver()

    def _driver(self):
        return FakeVirtDriver()

    def test_set_empty_ext_resources(self):
        resources = self.driver.get_available_resource(self.tracker.nodename)
        self.assertNotIn('stats', resources)
        self.tracker._write_ext_resources(resources)
        self.assertIn('stats', resources)

    def test_set_extra_resources(self):
        def fake_write_resources(resources):
            resources['stats']['resA'] = '123'
            resources['stats']['resB'] = 12

        self.stubs.Set(self.tracker.ext_resources_handler,
                       'write_resources',
                       fake_write_resources)

        resources = self.driver.get_available_resource(self.tracker.nodename)
        self.tracker._write_ext_resources(resources)

        expected = {"resA": "123", "resB": 12}
        self.assertEqual(sorted(expected),
                         sorted(resources['stats']))


class InstanceClaimTestCase(BaseTrackerTestCase):
    def _instance_topology(self, mem):
        mem = mem * 1024
        return objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(
                id=0, cpuset=set([1]), memory=mem),
                   objects.InstanceNUMACell(
                       id=1, cpuset=set([3]), memory=mem)])

    def _claim_topology(self, mem, cpus=1):
        if self.tracker.driver.numa_topology is None:
            return None
        mem = mem * 1024
        return objects.NUMATopology(
            cells=[objects.NUMACell(
                       id=0, cpuset=set([1, 2]), memory=3072, cpu_usage=cpus,
                       memory_usage=mem, mempages=[]),
                   objects.NUMACell(
                       id=1, cpuset=set([3, 4]), memory=3072, cpu_usage=cpus,
                       memory_usage=mem, mempages=[])])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_update_usage_only_for_tracked(self, mock_get):
        flavor = self._fake_flavor_create()
        claim_mem = flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD
        claim_gb = flavor['root_gb'] + flavor['ephemeral_gb']
        claim_topology = self._claim_topology(claim_mem / 2)

        instance_topology = self._instance_topology(claim_mem / 2)

        instance = self._fake_instance(
                flavor=flavor, task_state=None,
                numa_topology=instance_topology)
        self.tracker.update_usage(self.context, instance)

        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'current_workload')
        self._assert(FAKE_VIRT_NUMA_TOPOLOGY, 'numa_topology')

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertNotEqual(0, claim.memory_mb)
        self._assert(claim_mem, 'memory_mb_used')
        self._assert(claim_gb, 'local_gb_used')
        self._assert(claim_topology, 'numa_topology')

        # now update should actually take effect
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)

        self._assert(claim_mem, 'memory_mb_used')
        self._assert(claim_gb, 'local_gb_used')
        self._assert(claim_topology, 'numa_topology')
        self._assert(1, 'current_workload')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_claim_and_audit(self, mock_get):
        claim_mem = 3
        claim_mem_total = 3 + FAKE_VIRT_MEMORY_OVERHEAD
        claim_disk = 2
        claim_topology = self._claim_topology(claim_mem_total / 2)

        instance_topology = self._instance_topology(claim_mem_total / 2)
        instance = self._fake_instance(memory_mb=claim_mem, root_gb=claim_disk,
                ephemeral_gb=0, numa_topology=instance_topology)

        self.tracker.instance_claim(self.context, instance, self.limits)

        self.assertEqual(FAKE_VIRT_MEMORY_MB, self.compute["memory_mb"])
        self.assertEqual(claim_mem_total, self.compute["memory_mb_used"])
        self.assertEqual(FAKE_VIRT_MEMORY_MB - claim_mem_total,
                         self.compute["free_ram_mb"])
        self.assertEqualNUMAHostTopology(
                claim_topology, objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

        self.assertEqual(FAKE_VIRT_LOCAL_GB, self.compute["local_gb"])
        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(FAKE_VIRT_LOCAL_GB - claim_disk,
                         self.compute["free_disk_gb"])

        # 1st pretend that the compute operation finished and claimed the
        # desired resources from the virt layer
        driver = self.tracker.driver
        driver.memory_mb_used = claim_mem
        driver.local_gb_used = claim_disk

        self.tracker.update_available_resource(self.context)

        # confirm tracker is adding in host_ip
        self.assertIsNotNone(self.compute.get('host_ip'))

        # confirm that resource usage is derived from instance usages,
        # not virt layer:
        self.assertEqual(claim_mem_total, self.compute['memory_mb_used'])
        self.assertEqual(FAKE_VIRT_MEMORY_MB - claim_mem_total,
                         self.compute['free_ram_mb'])
        self.assertEqualNUMAHostTopology(
                claim_topology, objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

        self.assertEqual(claim_disk, self.compute['local_gb_used'])
        self.assertEqual(FAKE_VIRT_LOCAL_GB - claim_disk,
                         self.compute['free_disk_gb'])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_claim_and_abort(self, mock_get):
        claim_mem = 3
        claim_mem_total = 3 + FAKE_VIRT_MEMORY_OVERHEAD
        claim_disk = 2
        claim_topology = self._claim_topology(claim_mem_total / 2)

        instance_topology = self._instance_topology(claim_mem_total / 2)
        instance = self._fake_instance(memory_mb=claim_mem,
                root_gb=claim_disk, ephemeral_gb=0,
                numa_topology=instance_topology)

        claim = self.tracker.instance_claim(self.context, instance,
                self.limits)
        self.assertIsNotNone(claim)

        self.assertEqual(claim_mem_total, self.compute["memory_mb_used"])
        self.assertEqual(FAKE_VIRT_MEMORY_MB - claim_mem_total,
                         self.compute["free_ram_mb"])
        self.assertEqualNUMAHostTopology(
                claim_topology, objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

        self.assertEqual(claim_disk, self.compute["local_gb_used"])
        self.assertEqual(FAKE_VIRT_LOCAL_GB - claim_disk,
                         self.compute["free_disk_gb"])

        claim.abort()

        self.assertEqual(0, self.compute["memory_mb_used"])
        self.assertEqual(FAKE_VIRT_MEMORY_MB, self.compute["free_ram_mb"])
        self.assertEqualNUMAHostTopology(
                FAKE_VIRT_NUMA_TOPOLOGY,
                objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

        self.assertEqual(0, self.compute["local_gb_used"])
        self.assertEqual(FAKE_VIRT_LOCAL_GB, self.compute["free_disk_gb"])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_instance_claim_with_oversubscription(self, mock_get):
        memory_mb = FAKE_VIRT_MEMORY_MB * 2
        root_gb = ephemeral_gb = FAKE_VIRT_LOCAL_GB
        vcpus = FAKE_VIRT_VCPUS * 2
        claim_topology = self._claim_topology(3)
        instance_topology = self._instance_topology(3)

        limits = {'memory_mb': memory_mb + FAKE_VIRT_MEMORY_OVERHEAD,
                  'disk_gb': root_gb * 2,
                  'vcpu': vcpus,
                  'numa_topology': FAKE_VIRT_NUMA_TOPOLOGY_OVERHEAD.to_json()}

        instance = self._fake_instance(memory_mb=memory_mb,
                root_gb=root_gb, ephemeral_gb=ephemeral_gb,
                numa_topology=instance_topology)

        self.tracker.instance_claim(self.context, instance, limits)
        self.assertEqual(memory_mb + FAKE_VIRT_MEMORY_OVERHEAD,
                self.tracker.compute_node['memory_mb_used'])
        self.assertEqualNUMAHostTopology(
                claim_topology,
                objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))
        self.assertEqual(root_gb * 2,
                self.tracker.compute_node['local_gb_used'])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_additive_claims(self, mock_get):
        self.limits['vcpu'] = 2
        claim_topology = self._claim_topology(2, cpus=2)

        flavor = self._fake_flavor_create(
                memory_mb=1, root_gb=1, ephemeral_gb=0)
        instance_topology = self._instance_topology(1)
        instance = self._fake_instance(
                flavor=flavor, numa_topology=instance_topology)
        with self.tracker.instance_claim(self.context, instance, self.limits):
            pass
        instance = self._fake_instance(
                flavor=flavor, numa_topology=instance_topology)
        with self.tracker.instance_claim(self.context, instance, self.limits):
            pass

        self.assertEqual(2 * (flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD),
                self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(2 * (flavor['root_gb'] + flavor['ephemeral_gb']),
                self.tracker.compute_node['local_gb_used'])
        self.assertEqual(2 * flavor['vcpus'],
                self.tracker.compute_node['vcpus_used'])

        self.assertEqualNUMAHostTopology(
                claim_topology,
                objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_context_claim_with_exception(self, mock_get):
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
        self.assertEqualNUMAHostTopology(
                FAKE_VIRT_NUMA_TOPOLOGY,
                objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_instance_context_claim(self, mock_get):
        flavor = self._fake_flavor_create(
                memory_mb=1, root_gb=2, ephemeral_gb=3)
        claim_topology = self._claim_topology(1)

        instance_topology = self._instance_topology(1)
        instance = self._fake_instance(
                flavor=flavor, numa_topology=instance_topology)
        with self.tracker.instance_claim(self.context, instance):
            # <insert exciting things that utilize resources>
            self.assertEqual(flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD,
                             self.tracker.compute_node['memory_mb_used'])
            self.assertEqual(flavor['root_gb'] + flavor['ephemeral_gb'],
                             self.tracker.compute_node['local_gb_used'])
            self.assertEqual(flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD,
                             self.compute['memory_mb_used'])
            self.assertEqualNUMAHostTopology(
                    claim_topology,
                    objects.NUMATopology.obj_from_db_obj(
                        self.compute['numa_topology']))
            self.assertEqual(flavor['root_gb'] + flavor['ephemeral_gb'],
                             self.compute['local_gb_used'])

        # after exiting claim context, build is marked as finished.  usage
        # totals should be same:
        self.tracker.update_available_resource(self.context)
        self.assertEqual(flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.tracker.compute_node['memory_mb_used'])
        self.assertEqual(flavor['root_gb'] + flavor['ephemeral_gb'],
                         self.tracker.compute_node['local_gb_used'])
        self.assertEqual(flavor['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD,
                         self.compute['memory_mb_used'])
        self.assertEqualNUMAHostTopology(
                claim_topology,
                objects.NUMATopology.obj_from_db_obj(
                    self.compute['numa_topology']))
        self.assertEqual(flavor['root_gb'] + flavor['ephemeral_gb'],
                         self.compute['local_gb_used'])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_update_load_stats_for_instance(self, mock_get):
        instance = self._fake_instance(task_state=task_states.SCHEDULING)
        with self.tracker.instance_claim(self.context, instance):
            pass

        self.assertEqual(1, self.tracker.compute_node['current_workload'])

        instance['vm_state'] = vm_states.ACTIVE
        instance['task_state'] = None
        instance['host'] = 'fakehost'

        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['current_workload'])

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_cpu_stats(self, mock_get):
        limits = {'disk_gb': 100, 'memory_mb': 100}
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        vcpus = 1
        instance = self._fake_instance(vcpus=vcpus)

        # should not do anything until a claim is made:
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(0, self.tracker.compute_node['vcpus_used'])

        with self.tracker.instance_claim(self.context, instance, limits):
            pass
        self.assertEqual(vcpus, self.tracker.compute_node['vcpus_used'])

        # instance state can change without modifying vcpus in use:
        instance['task_state'] = task_states.SCHEDULING
        self.tracker.update_usage(self.context, instance)
        self.assertEqual(vcpus, self.tracker.compute_node['vcpus_used'])

        add_vcpus = 10
        vcpus += add_vcpus
        instance = self._fake_instance(vcpus=add_vcpus)
        with self.tracker.instance_claim(self.context, instance, limits):
            pass
        self.assertEqual(vcpus, self.tracker.compute_node['vcpus_used'])

        instance['vm_state'] = vm_states.DELETED
        self.tracker.update_usage(self.context, instance)
        vcpus -= add_vcpus
        self.assertEqual(vcpus, self.tracker.compute_node['vcpus_used'])

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

        def _fake_migration_create(mig_self):
            self._migrations[mig_self.instance_uuid] = mig_self
            mig_self.obj_reset_changes()

        self.stubs.Set(objects.Migration, 'create',
                       _fake_migration_create)

        self.instance = self._fake_instance()
        self.instance_type = self._fake_flavor_create()

    def _fake_migration_create(self, values=None):
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

        migration = objects.Migration(context='fake')
        migration.update(mig_dict)
        # This hits the stub in setUp()
        migration.create()

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_claim(self, mock_get):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, self.limits)
        self._assert(FAKE_VIRT_MEMORY_WITH_OVERHEAD, 'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')
        self.assertEqual(1, len(self.tracker.tracked_migrations))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_abort(self, mock_get):
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

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_additive_claims(self, mock_get):

        limits = self._limits(
              2 * FAKE_VIRT_MEMORY_WITH_OVERHEAD,
              2 * FAKE_VIRT_LOCAL_GB,
              2 * FAKE_VIRT_VCPUS)
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, limits)
        instance2 = self._fake_instance()
        self.tracker.resize_claim(self.context, instance2, self.instance_type,
                limits)

        self._assert(2 * FAKE_VIRT_MEMORY_WITH_OVERHEAD, 'memory_mb_used')
        self._assert(2 * FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(2 * FAKE_VIRT_VCPUS, 'vcpus_used')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_claim_and_audit(self, mock_get):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, self.limits)

        self.tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_WITH_OVERHEAD, 'memory_mb_used')
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_same_host(self, mock_get):
        self.limits['vcpu'] = 3

        src_dict = {
            'memory_mb': 1, 'root_gb': 1, 'ephemeral_gb': 0, 'vcpus': 1}
        dest_dict = dict((k, v + 1) for (k, v) in src_dict.iteritems())
        src_type = self._fake_flavor_create(
                id=10, name="srcflavor", **src_dict)
        dest_type = self._fake_flavor_create(
                id=11, name="destflavor", **dest_dict)

        # make an instance of src_type:
        instance = self._fake_instance(flavor=src_type)
        instance['system_metadata'] = self._fake_instance_system_metadata(
            dest_type)
        self.tracker.instance_claim(self.context, instance, self.limits)

        # resize to dest_type:
        claim = self.tracker.resize_claim(self.context, instance,
                dest_type, self.limits)

        self._assert(src_dict['memory_mb'] + dest_dict['memory_mb']
                   + 2 * FAKE_VIRT_MEMORY_OVERHEAD, 'memory_mb_used')
        self._assert(src_dict['root_gb'] + src_dict['ephemeral_gb']
                   + dest_dict['root_gb'] + dest_dict['ephemeral_gb'],
                   'local_gb_used')
        self._assert(src_dict['vcpus'] + dest_dict['vcpus'], 'vcpus_used')

        self.tracker.update_available_resource(self.context)
        claim.abort()

        # only the original instance should remain, not the migration:
        self._assert(src_dict['memory_mb'] + FAKE_VIRT_MEMORY_OVERHEAD,
                     'memory_mb_used')
        self._assert(src_dict['root_gb'] + src_dict['ephemeral_gb'],
                     'local_gb_used')
        self._assert(src_dict['vcpus'], 'vcpus_used')
        self.assertEqual(1, len(self.tracker.tracked_instances))
        self.assertEqual(0, len(self.tracker.tracked_migrations))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_revert(self, mock_get):
        self.tracker.resize_claim(self.context, self.instance,
                self.instance_type, {}, self.limits)
        self.tracker.drop_resize_claim(self.context, self.instance)

        self.assertEqual(0, len(self.tracker.tracked_instances))
        self.assertEqual(0, len(self.tracker.tracked_migrations))
        self._assert(0, 'memory_mb_used')
        self._assert(0, 'local_gb_used')
        self._assert(0, 'vcpus_used')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_revert_reserve_source(self, mock_get):
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
        self._fake_migration_create(values)

        # attach an instance to the destination host tracker:
        dest_tracker.instance_claim(self.context, self.instance)

        self._assert(FAKE_VIRT_MEMORY_WITH_OVERHEAD,
                     'memory_mb_used', tracker=dest_tracker)
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used',
                     tracker=dest_tracker)
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used',
                     tracker=dest_tracker)

        # audit and recheck to confirm migration doesn't get double counted
        # on dest:
        dest_tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_WITH_OVERHEAD,
                     'memory_mb_used', tracker=dest_tracker)
        self._assert(FAKE_VIRT_LOCAL_GB, 'local_gb_used',
                     tracker=dest_tracker)
        self._assert(FAKE_VIRT_VCPUS, 'vcpus_used',
                     tracker=dest_tracker)

        # apply the migration to the source host tracker:
        self.tracker.update_available_resource(self.context)

        self._assert(FAKE_VIRT_MEMORY_WITH_OVERHEAD, 'memory_mb_used')
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

        states = [task_states.RESIZE_PREP, task_states.RESIZE_MIGRATING,
                  task_states.RESIZE_MIGRATED, task_states.RESIZE_FINISH]
        for vm_state in [vm_states.ACTIVE, vm_states.STOPPED]:
            for task_state in states:
                instance = self._fake_instance(vm_state=vm_state,
                                               task_state=task_state)
                result = self.tracker._instance_in_resize_state(instance)
                self.assertTrue(result)

    def test_dupe_filter(self):
        instance = self._fake_instance(host=self.host)

        values = {'source_compute': self.host, 'dest_compute': self.host,
                  'instance_uuid': instance['uuid'], 'new_instance_type_id': 2}
        self._fake_flavor_create(id=2)
        self._fake_migration_create(values)
        self._fake_migration_create(values)

        self.tracker.update_available_resource(self.context)
        self.assertEqual(1, len(self.tracker.tracked_migrations))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_set_instance_host_and_node(self, mock_get):
        instance = self._fake_instance()
        self.assertIsNone(instance['host'])
        self.assertIsNone(instance['launched_on'])
        self.assertIsNone(instance['node'])

        claim = self.tracker.instance_claim(self.context, instance)
        self.assertNotEqual(0, claim.memory_mb)

        self.assertEqual('fakehost', instance['host'])
        self.assertEqual('fakehost', instance['launched_on'])
        self.assertEqual('fakenode', instance['node'])


class NoInstanceTypesInSysMetadata(ResizeClaimTestCase):
    """Make sure we handle the case where the following are true:

    #) Compute node C gets upgraded to code that looks for instance types in
       system metadata. AND
    #) C already has instances in the process of migrating that do not have
       stashed instance types.

    bug 1164110
    """
    def setUp(self):
        super(NoInstanceTypesInSysMetadata, self).setUp()
        self.instance = self._fake_instance(stash=False)

    def test_get_instance_type_stash_false(self):
        with (mock.patch.object(objects.Flavor, 'get_by_id',
                                return_value=self.instance_type)):
            flavor = self.tracker._get_instance_type(self.context,
                                                     self.instance, "new_")
            self.assertEqual(self.instance_type, flavor)


class OrphanTestCase(BaseTrackerTestCase):
    def _driver(self):
        class OrphanVirtDriver(FakeVirtDriver):
            def get_per_instance_usage(self):
                return {
                    '1-2-3-4-5': {'memory_mb': FAKE_VIRT_MEMORY_MB,
                                  'uuid': '1-2-3-4-5'},
                    '2-3-4-5-6': {'memory_mb': FAKE_VIRT_MEMORY_MB,
                                  'uuid': '2-3-4-5-6'},
                }

        return OrphanVirtDriver()

    def test_usage(self):
        self.assertEqual(2 * FAKE_VIRT_MEMORY_WITH_OVERHEAD,
                self.tracker.compute_node['memory_mb_used'])

    def test_find(self):
        # create one legit instance and verify the 2 orphans remain
        self._fake_instance()
        orphans = self.tracker._find_orphaned_instances()

        self.assertEqual(2, len(orphans))


class ComputeMonitorTestCase(BaseTestCase):
    def setUp(self):
        super(ComputeMonitorTestCase, self).setUp()
        fake_monitors = [
            'nova.tests.unit.compute.monitors.test_monitors.FakeMonitorClass1',
            'nova.tests.unit.compute.monitors.test_monitors.FakeMonitorClass2']
        self.flags(compute_available_monitors=fake_monitors)
        self.tracker = self._tracker()
        self.node_name = 'nodename'
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.info = {}
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def test_get_host_metrics_none(self):
        self.flags(compute_monitors=['FakeMontorClass1', 'FakeMonitorClass4'])
        self.tracker.monitors = []
        metrics = self.tracker._get_host_metrics(self.context,
                                                 self.node_name)
        self.assertEqual(len(metrics), 0)

    def test_get_host_metrics_one_failed(self):
        self.flags(compute_monitors=['FakeMonitorClass1', 'FakeMonitorClass4'])
        class1 = test_monitors.FakeMonitorClass1(self.tracker)
        class4 = test_monitors.FakeMonitorClass4(self.tracker)
        self.tracker.monitors = [class1, class4]
        metrics = self.tracker._get_host_metrics(self.context,
                                                 self.node_name)
        self.assertTrue(len(metrics) > 0)

    @mock.patch.object(resource_tracker.LOG, 'warning')
    def test_get_host_metrics_exception(self, mock_LOG_warning):
        self.flags(compute_monitors=['FakeMontorClass1'])
        class1 = test_monitors.FakeMonitorClass1(self.tracker)
        self.tracker.monitors = [class1]
        with mock.patch.object(class1, 'get_metrics',
                               side_effect=test.TestingException()):
            metrics = self.tracker._get_host_metrics(self.context,
                                                     self.node_name)
            mock_LOG_warning.assert_called_once_with(
                u'Cannot get the metrics from %s.', class1)
            self.assertEqual(0, len(metrics))

    def test_get_host_metrics(self):
        self.flags(compute_monitors=['FakeMonitorClass1', 'FakeMonitorClass2'])
        class1 = test_monitors.FakeMonitorClass1(self.tracker)
        class2 = test_monitors.FakeMonitorClass2(self.tracker)
        self.tracker.monitors = [class1, class2]

        mock_notifier = mock.Mock()

        with mock.patch.object(rpc, 'get_notifier',
                               return_value=mock_notifier) as mock_get:
            metrics = self.tracker._get_host_metrics(self.context,
                                                     self.node_name)
            mock_get.assert_called_once_with(service='compute',
                                             host=self.node_name)

        expected_metrics = [{
                    'timestamp': 1232,
                    'name': 'key1',
                    'value': 2600,
                    'source': 'libvirt'
                }, {
                    'name': 'key2',
                    'source': 'libvirt',
                    'timestamp': 123,
                    'value': 1600
                }]

        payload = {
            'metrics': expected_metrics,
            'host': self.tracker.host,
            'host_ip': CONF.my_ip,
            'nodename': self.node_name
        }

        mock_notifier.info.assert_called_once_with(
            self.context, 'compute.metrics.update', payload)

        self.assertEqual(metrics, expected_metrics)


class TrackerPeriodicTestCase(BaseTrackerTestCase):

    def test_periodic_status_update(self):
        # verify update called on instantiation
        self.assertEqual(1, self.update_call_count)

        # verify update not called if no change to resources
        self.tracker.update_available_resource(self.context)
        self.assertEqual(1, self.update_call_count)

        # verify update is called when resources change
        driver = self.tracker.driver
        driver.memory_mb += 1
        self.tracker.update_available_resource(self.context)
        self.assertEqual(2, self.update_call_count)

    def test_update_available_resource_calls_locked_inner(self):
        @mock.patch.object(self.tracker, 'driver')
        @mock.patch.object(self.tracker,
                           '_update_available_resource')
        @mock.patch.object(self.tracker, '_verify_resources')
        @mock.patch.object(self.tracker, '_report_hypervisor_resource_view')
        def _test(mock_rhrv, mock_vr, mock_uar, mock_driver):
            resources = {'there is someone in my head': 'but it\'s not me'}
            mock_driver.get_available_resource.return_value = resources
            self.tracker.update_available_resource(self.context)
            mock_uar.assert_called_once_with(self.context, resources)

        _test()


class StatsDictTestCase(BaseTrackerTestCase):
    """Test stats handling for a virt driver that provides
    stats as a dictionary.
    """
    def _driver(self):
        return FakeVirtDriver(stats=FAKE_VIRT_STATS)

    def _get_stats(self):
        return jsonutils.loads(self.tracker.compute_node['stats'])

    def test_virt_stats(self):
        # start with virt driver stats
        stats = self._get_stats()
        self.assertEqual(FAKE_VIRT_STATS, stats)

        # adding an instance should keep virt driver stats
        self._fake_instance(vm_state=vm_states.ACTIVE, host=self.host)
        self.tracker.update_available_resource(self.context)

        stats = self._get_stats()
        expected_stats = {}
        expected_stats.update(FAKE_VIRT_STATS)
        expected_stats.update(self.tracker.stats)
        self.assertEqual(expected_stats, stats)

        # removing the instances should keep only virt driver stats
        self._instances = {}
        self.tracker.update_available_resource(self.context)

        stats = self._get_stats()
        self.assertEqual(FAKE_VIRT_STATS, stats)


class StatsJsonTestCase(BaseTrackerTestCase):
    """Test stats handling for a virt driver that provides
    stats as a json string.
    """
    def _driver(self):
        return FakeVirtDriver(stats=FAKE_VIRT_STATS_JSON)

    def _get_stats(self):
        return jsonutils.loads(self.tracker.compute_node['stats'])

    def test_virt_stats(self):
        # start with virt driver stats
        stats = self._get_stats()
        self.assertEqual(FAKE_VIRT_STATS, stats)

        # adding an instance should keep virt driver stats
        # and add rt stats
        self._fake_instance(vm_state=vm_states.ACTIVE, host=self.host)
        self.tracker.update_available_resource(self.context)

        stats = self._get_stats()
        expected_stats = {}
        expected_stats.update(FAKE_VIRT_STATS)
        expected_stats.update(self.tracker.stats)
        self.assertEqual(expected_stats, stats)

        # removing the instances should keep only virt driver stats
        self._instances = {}
        self.tracker.update_available_resource(self.context)
        stats = self._get_stats()
        self.assertEqual(FAKE_VIRT_STATS, stats)


class StatsInvalidJsonTestCase(BaseTrackerTestCase):
    """Test stats handling for a virt driver that provides
    an invalid type for stats.
    """
    def _driver(self):
        return FakeVirtDriver(stats='this is not json')

    def _init_tracker(self):
        # do not do initial update in setup
        pass

    def test_virt_stats(self):
        # should throw exception for string that does not parse as json
        self.assertRaises(ValueError,
                          self.tracker.update_available_resource,
                          context=self.context)


class StatsInvalidTypeTestCase(BaseTrackerTestCase):
    """Test stats handling for a virt driver that provides
    an invalid type for stats.
    """
    def _driver(self):
        return FakeVirtDriver(stats=10)

    def _init_tracker(self):
        # do not do initial update in setup
        pass

    def test_virt_stats(self):
        # should throw exception for incorrect stats value type
        self.assertRaises(ValueError,
                          self.tracker.update_available_resource,
                          context=self.context)
