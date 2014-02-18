# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011 University of Southern California / ISI
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

"""Tests for the base baremetal driver class."""

import mock
import mox
from oslo.config import cfg

from nova.compute import power_state
from nova.compute import task_states
from nova import db as main_db
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.image import fake as fake_image
from nova.tests import utils
from nova.tests.virt.baremetal.db import base as bm_db_base
from nova.tests.virt.baremetal.db import utils as bm_db_utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import db
from nova.virt.baremetal import driver as bm_driver
from nova.virt.baremetal import fake
from nova.virt import fake as fake_virt


CONF = cfg.CONF

COMMON_FLAGS = dict(
    firewall_driver='nova.virt.baremetal.fake.FakeFirewallDriver',
    host='test_host',
)

BAREMETAL_FLAGS = dict(
    driver='nova.virt.baremetal.fake.FakeDriver',
    flavor_extra_specs=['cpu_arch:test', 'test_spec:test_value'],
    power_manager='nova.virt.baremetal.fake.FakePowerManager',
    vif_driver='nova.virt.baremetal.fake.FakeVifDriver',
    volume_driver='nova.virt.baremetal.fake.FakeVolumeDriver',
    group='baremetal',
)


class BareMetalDriverNoDBTestCase(test.NoDBTestCase):

    def setUp(self):
        super(BareMetalDriverNoDBTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)
        self.driver = bm_driver.BareMetalDriver(None)

    def test_validate_driver_loading(self):
        self.assertIsInstance(self.driver.driver, fake.FakeDriver)
        self.assertIsInstance(self.driver.vif_driver, fake.FakeVifDriver)
        self.assertIsInstance(self.driver.volume_driver, fake.FakeVolumeDriver)
        self.assertIsInstance(self.driver.firewall_driver,
                              fake.FakeFirewallDriver)

    def test_driver_capabilities(self):
        self.assertTrue(self.driver.capabilities['has_imagecache'])
        self.assertFalse(self.driver.capabilities['supports_recreate'])


class BareMetalDriverWithDBTestCase(bm_db_base.BMDBTestCase):

    def setUp(self):
        super(BareMetalDriverWithDBTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)

        fake_image.stub_out_image_service(self.stubs)
        self.context = utils.get_test_admin_context()
        self.driver = bm_driver.BareMetalDriver(fake_virt.FakeVirtAPI())
        self.addCleanup(fake_image.FakeImageService_reset)

    def _create_node(self, node_info=None, nic_info=None, ephemeral=True):
        result = {}
        if node_info is None:
            node_info = bm_db_utils.new_bm_node(
                            id=123,
                            service_host='test_host',
                            cpus=2,
                            memory_mb=2048,
                        )
        if nic_info is None:
            nic_info = [
                    {'address': '01:23:45:67:89:01', 'datapath_id': '0x1',
                        'port_no': 1},
                    {'address': '01:23:45:67:89:02', 'datapath_id': '0x2',
                        'port_no': 2},
                ]
        result['node_info'] = node_info
        result['nic_info'] = nic_info
        result['node'] = db.bm_node_create(self.context, node_info)

        for nic in nic_info:
            db.bm_interface_create(
                                    self.context,
                                    result['node']['id'],
                                    nic['address'],
                                    nic['datapath_id'],
                                    nic['port_no'],
                )
        if ephemeral:
            result['instance'] = utils.get_test_instance()
        else:
            flavor = utils.get_test_flavor(options={'ephemeral_gb': 0})
            result['instance'] = utils.get_test_instance(flavor=flavor)
        result['instance']['node'] = result['node']['uuid']
        result['spawn_params'] = dict(
                admin_password='test_pass',
                block_device_info=None,
                context=self.context,
                image_meta=utils.get_test_image_info(
                                None, result['instance']),
                injected_files=[('/fake/path', 'hello world')],
                instance=result['instance'],
                network_info=utils.get_test_network_info(),
            )
        result['destroy_params'] = dict(
                context=self.context,
                instance=result['instance'],
                network_info=result['spawn_params']['network_info'],
                block_device_info=result['spawn_params']['block_device_info'],
            )

        instance = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), result['instance'])
        instance.node = result['node']['uuid']

        result['rebuild_params'] = dict(
            context=self.context,
            instance=instance,
            image_meta=utils.get_test_image_info(None, result['instance']),
            injected_files=[('/fake/path', 'hello world')],
            admin_password='test_pass',
            bdms={},
            detach_block_devices=self.mox.CreateMockAnything(),
            attach_block_devices=self.mox.CreateMockAnything(),
            network_info=result['spawn_params']['network_info'],
            block_device_info=result['spawn_params']['block_device_info'],
        )

        return result

    def test_get_host_stats(self):
        node = self._create_node()
        stats = self.driver.get_host_stats()
        self.assertIsInstance(stats, list)
        self.assertEqual(len(stats), 1)
        stats = stats[0]
        self.assertEqual(stats['cpu_arch'], 'test')
        self.assertEqual(stats['test_spec'], 'test_value')
        self.assertEqual(stats['hypervisor_type'], 'baremetal')
        self.assertEqual(stats['hypervisor_hostname'], node['node']['uuid'])
        self.assertEqual(stats['host'], 'test_host')
        self.assertEqual(stats['vcpus'], 2)
        self.assertEqual(stats['host_memory_total'], 2048)

    def test_spawn_ok(self):
        node = self._create_node()
        self.driver.spawn(**node['spawn_params'])
        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.ACTIVE)
        self.assertEqual(row['instance_uuid'], node['instance']['uuid'])
        self.assertEqual(row['instance_name'], node['instance']['hostname'])
        instance = main_db.instance_get_by_uuid(self.context,
                node['instance']['uuid'])
        self.assertEqual(instance['default_ephemeral_device'], '/dev/sda1')

    def test_spawn_no_ephemeral_ok(self):
        node = self._create_node(ephemeral=False)
        self.driver.spawn(**node['spawn_params'])
        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.ACTIVE)
        self.assertEqual(row['instance_uuid'], node['instance']['uuid'])
        self.assertEqual(row['instance_name'], node['instance']['hostname'])
        instance = main_db.instance_get_by_uuid(self.context,
                node['instance']['uuid'])
        self.assertIsNone(instance['default_ephemeral_device'])

    def _test_rebuild(self, ephemeral):
        node = self._create_node(ephemeral=ephemeral)
        self.driver.spawn(**node['spawn_params'])
        after_spawn = db.bm_node_get(self.context, node['node']['id'])

        instance = node['rebuild_params']['instance']
        instance.task_state = task_states.REBUILDING
        instance.save(expected_task_state=[None])
        self.driver.rebuild(preserve_ephemeral=ephemeral,
                            **node['rebuild_params'])
        after_rebuild = db.bm_node_get(self.context, node['node']['id'])

        self.assertEqual(after_rebuild['task_state'], baremetal_states.ACTIVE)
        self.assertEqual(after_rebuild['preserve_ephemeral'], ephemeral)
        self.assertEqual(after_spawn['instance_uuid'],
                         after_rebuild['instance_uuid'])

    def test_rebuild_ok(self):
        self._test_rebuild(ephemeral=False)

    def test_rebuild_preserve_ephemeral(self):
        self._test_rebuild(ephemeral=True)

    def test_macs_from_nic_for_instance(self):
        node = self._create_node()
        expected = set([nic['address'] for nic in node['nic_info']])
        self.assertEqual(
            expected, self.driver.macs_for_instance(node['instance']))

    def test_macs_for_instance_after_spawn(self):
        node = self._create_node()
        self.driver.spawn(**node['spawn_params'])

        expected = set([nic['address'] for nic in node['nic_info']])
        self.assertEqual(
            expected, self.driver.macs_for_instance(node['instance']))

    def test_macs_for_instance(self):
        node = self._create_node()
        expected = set(['01:23:45:67:89:01', '01:23:45:67:89:02'])
        self.assertEqual(
            expected, self.driver.macs_for_instance(node['instance']))

    def test_macs_for_instance_no_interfaces(self):
        # Nodes cannot boot with no MACs, so we raise an error if that happens.
        node = self._create_node(nic_info=[])
        self.assertRaises(exception.NovaException,
            self.driver.macs_for_instance, node['instance'])

    def test_spawn_node_already_associated(self):
        node = self._create_node()
        db.bm_node_update(self.context, node['node']['id'],
                {'instance_uuid': '1234-5678'})

        self.assertRaises(exception.NovaException,
                self.driver.spawn, **node['spawn_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertIsNone(row['task_state'])

    def test_spawn_node_in_use(self):
        node = self._create_node()

        self.driver.spawn(**node['spawn_params'])
        self.assertRaises(exception.NovaException,
                self.driver.spawn, **node['spawn_params'])

    def test_spawn_node_not_found(self):
        node = self._create_node()
        db.bm_node_update(self.context, node['node']['id'],
                {'uuid': 'hide-this-node'})

        self.assertRaises(exception.NovaException,
                self.driver.spawn, **node['spawn_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertIsNone(row['task_state'])

    def test_spawn_fails(self):
        node = self._create_node()

        self.mox.StubOutWithMock(fake.FakePowerManager, 'activate_node')
        fake.FakePowerManager.activate_node().AndRaise(test.TestingException)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                self.driver.spawn, **node['spawn_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.DELETED)

    def test_spawn_prepared(self):
        node = self._create_node()

        def update_2prepared(context, node, instance, state):
            row = db.bm_node_get(context, node['id'])
            self.assertEqual(row['task_state'], baremetal_states.BUILDING)
            db.bm_node_update(
                context, node['id'],
                {'task_state': baremetal_states.PREPARED})

        self.mox.StubOutWithMock(fake.FakeDriver, 'activate_node')
        self.mox.StubOutWithMock(bm_driver, '_update_state')

        bm_driver._update_state(
            self.context,
            mox.IsA(node['node']),
            node['instance'],
            baremetal_states.PREPARED).WithSideEffects(update_2prepared)
        fake.FakeDriver.activate_node(
            self.context,
            mox.IsA(node['node']),
            node['instance']).AndRaise(test.TestingException)
        bm_driver._update_state(
            self.context,
            mox.IsA(node['node']),
            node['instance'],
            baremetal_states.ERROR).AndRaise(test.TestingException)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.driver.spawn, **node['spawn_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.PREPARED)

    def test_spawn_fails_to_cleanup(self):
        node = self._create_node()

        self.mox.StubOutWithMock(fake.FakePowerManager, 'activate_node')
        self.mox.StubOutWithMock(fake.FakePowerManager, 'deactivate_node')
        fake.FakePowerManager.deactivate_node().AndReturn(None)
        fake.FakePowerManager.activate_node().AndRaise(test.TestingException)
        fake.FakePowerManager.deactivate_node().AndRaise(test.TestingException)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                self.driver.spawn, **node['spawn_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.ERROR)

    def test_spawn_destroy_images_on_deploy(self):
        node = self._create_node()
        self.driver.driver.destroy_images = mock.MagicMock()
        self.driver.spawn(**node['spawn_params'])
        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.ACTIVE)
        self.assertEqual(row['instance_uuid'], node['instance']['uuid'])
        self.assertEqual(row['instance_name'], node['instance']['hostname'])
        instance = main_db.instance_get_by_uuid(self.context,
                node['instance']['uuid'])
        self.assertIsNotNone(instance)
        self.assertEqual(1, self.driver.driver.destroy_images.call_count)

    def test_destroy_ok(self):
        node = self._create_node()
        self.driver.spawn(**node['spawn_params'])
        self.driver.destroy(**node['destroy_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.DELETED)
        self.assertIsNone(row['instance_uuid'])
        self.assertIsNone(row['instance_name'])

    def test_destroy_fails(self):
        node = self._create_node()

        self.mox.StubOutWithMock(fake.FakePowerManager, 'deactivate_node')
        fake.FakePowerManager.deactivate_node().AndReturn(None)
        fake.FakePowerManager.deactivate_node().AndRaise(test.TestingException)
        self.mox.ReplayAll()

        self.driver.spawn(**node['spawn_params'])
        self.assertRaises(test.TestingException,
                self.driver.destroy, **node['destroy_params'])

        row = db.bm_node_get(self.context, node['node']['id'])
        self.assertEqual(row['task_state'], baremetal_states.ERROR)
        self.assertEqual(row['instance_uuid'], node['instance']['uuid'])

    def test_get_available_resources(self):
        node = self._create_node()

        resources = self.driver.get_available_resource(node['node']['uuid'])
        self.assertEqual(resources['memory_mb'],
                         node['node_info']['memory_mb'])
        self.assertEqual(resources['memory_mb_used'], 0)
        self.assertEqual(resources['supported_instances'],
                '[["test", "baremetal", "baremetal"]]')
        self.assertEqual(resources['stats'],
                         '{"cpu_arch": "test", "baremetal_driver": '
                         '"nova.virt.baremetal.fake.FakeDriver", '
                         '"test_spec": "test_value"}')

        self.driver.spawn(**node['spawn_params'])
        resources = self.driver.get_available_resource(node['node']['uuid'])
        self.assertEqual(resources['memory_mb_used'],
                         node['node_info']['memory_mb'])

        self.driver.destroy(**node['destroy_params'])
        resources = self.driver.get_available_resource(node['node']['uuid'])
        self.assertEqual(resources['memory_mb_used'], 0)
        stats = jsonutils.loads(resources['stats'])
        self.assertEqual(stats['test_spec'], 'test_value')

    def test_get_available_nodes(self):
        self.assertEqual(0, len(self.driver.get_available_nodes()))
        self.assertEqual(0, len(self.driver.get_available_nodes(refresh=True)))

        node1 = self._create_node()
        self.assertEqual(1, len(self.driver.get_available_nodes()))

        node1['instance']['hostname'] = 'test-host-1'
        self.driver.spawn(**node1['spawn_params'])
        self.assertEqual(1, len(self.driver.get_available_nodes()))
        self.assertEqual([node1['node']['uuid']],
                         self.driver.get_available_nodes())

    def test_list_instances(self):
        self.assertEqual([], self.driver.list_instances())

        node1 = self._create_node()
        self.assertEqual([], self.driver.list_instances())

        node_info = bm_db_utils.new_bm_node(
                        id=456,
                        service_host='test_host',
                        cpus=2,
                        memory_mb=2048,
                    )
        nic_info = [
                {'address': 'cc:cc:cc', 'datapath_id': '0x1',
                    'port_no': 1},
                {'address': 'dd:dd:dd', 'datapath_id': '0x2',
                    'port_no': 2},
            ]
        node2 = self._create_node(node_info=node_info, nic_info=nic_info)
        self.assertEqual([], self.driver.list_instances())

        node1['instance']['hostname'] = 'test-host-1'
        node2['instance']['hostname'] = 'test-host-2'

        self.driver.spawn(**node1['spawn_params'])
        self.assertEqual(['test-host-1'],
                self.driver.list_instances())

        self.driver.spawn(**node2['spawn_params'])
        self.assertEqual(['test-host-1', 'test-host-2'],
                self.driver.list_instances())

        self.driver.destroy(**node1['destroy_params'])
        self.assertEqual(['test-host-2'],
                self.driver.list_instances())

        self.driver.destroy(**node2['destroy_params'])
        self.assertEqual([], self.driver.list_instances())

    def test_get_info_no_such_node(self):
        node = self._create_node()
        self.assertRaises(exception.InstanceNotFound,
                self.driver.get_info,
                node['instance'])

    def test_get_info_ok(self):
        node = self._create_node()
        db.bm_node_associate_and_update(self.context, node['node']['uuid'],
                {'instance_uuid': node['instance']['uuid'],
                 'instance_name': node['instance']['hostname'],
                 'task_state': baremetal_states.ACTIVE})
        res = self.driver.get_info(node['instance'])
        self.assertEqual(res['state'], power_state.RUNNING)

    def test_get_info_with_defunct_pm(self):
        # test fix for bug 1178378
        node = self._create_node()
        db.bm_node_associate_and_update(self.context, node['node']['uuid'],
                {'instance_uuid': node['instance']['uuid'],
                 'instance_name': node['instance']['hostname'],
                 'task_state': baremetal_states.ACTIVE})

        # fake the power manager and don't get a power state
        self.mox.StubOutWithMock(fake.FakePowerManager, 'is_power_on')
        fake.FakePowerManager.is_power_on().AndReturn(None)
        self.mox.ReplayAll()

        res = self.driver.get_info(node['instance'])
        # prior to the fix, returned power_state was SHUTDOWN
        self.assertEqual(res['state'], power_state.NOSTATE)
        self.mox.VerifyAll()

    def test_attach_volume(self):
        connection_info = {'_fake_connection_info': None}
        instance = utils.get_test_instance()
        mountpoint = '/dev/sdd'
        self.mox.StubOutWithMock(self.driver.volume_driver, 'attach_volume')
        self.driver.volume_driver.attach_volume(connection_info,
                                                instance,
                                                mountpoint)
        self.mox.ReplayAll()
        self.driver.attach_volume(None, connection_info, instance, mountpoint)

    def test_detach_volume(self):
        connection_info = {'_fake_connection_info': None}
        instance = utils.get_test_instance()
        mountpoint = '/dev/sdd'
        self.mox.StubOutWithMock(self.driver.volume_driver, 'detach_volume')
        self.driver.volume_driver.detach_volume(connection_info,
                                                instance,
                                                mountpoint)
        self.mox.ReplayAll()
        self.driver.detach_volume(connection_info, instance, mountpoint)

    def test_attach_block_devices(self):
        connection_info_1 = {'_fake_connection_info_1': None}
        connection_info_2 = {'_fake_connection_info_2': None}
        block_device_mapping = [{'connection_info': connection_info_1,
                                 'mount_device': '/dev/sde'},
                                {'connection_info': connection_info_2,
                                 'mount_device': '/dev/sdf'}]
        block_device_info = {'block_device_mapping': block_device_mapping}
        instance = utils.get_test_instance()

        self.mox.StubOutWithMock(self.driver, 'attach_volume')
        self.driver.attach_volume(None, connection_info_1, instance,
                                  '/dev/sde')
        self.driver.attach_volume(None, connection_info_2, instance,
                                  '/dev/sdf')
        self.mox.ReplayAll()
        self.driver._attach_block_devices(instance, block_device_info)

    def test_detach_block_devices(self):
        connection_info_1 = {'_fake_connection_info_1': None}
        connection_info_2 = {'_fake_connection_info_2': None}
        block_device_mapping = [{'connection_info': connection_info_1,
                                 'mount_device': '/dev/sde'},
                                {'connection_info': connection_info_2,
                                 'mount_device': '/dev/sdf'}]
        block_device_info = {'block_device_mapping': block_device_mapping}
        instance = utils.get_test_instance()

        self.mox.StubOutWithMock(self.driver, 'detach_volume')
        self.driver.detach_volume(connection_info_1, instance, '/dev/sde')
        self.driver.detach_volume(connection_info_2, instance, '/dev/sdf')
        self.mox.ReplayAll()
        self.driver._detach_block_devices(instance, block_device_info)
