# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from oslo.config import cfg

from nova import exception
from nova import test
from nova.tests.baremetal.db import base as bm_db_base
from nova.tests.baremetal.db import utils as bm_db_utils
from nova.tests.image import fake as fake_image
from nova.tests import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import db
from nova.virt.baremetal import driver as bm_driver
from nova.virt.baremetal import fake


CONF = cfg.CONF

COMMON_FLAGS = dict(
    firewall_driver='nova.virt.baremetal.fake.FakeFirewallDriver',
    host='test_host',
)

BAREMETAL_FLAGS = dict(
    driver='nova.virt.baremetal.fake.FakeDriver',
    instance_type_extra_specs=['cpu_arch:test', 'test_spec:test_value'],
    power_manager='nova.virt.baremetal.fake.FakePowerManager',
    vif_driver='nova.virt.baremetal.fake.FakeVifDriver',
    volume_driver='nova.virt.baremetal.fake.FakeVolumeDriver',
    group='baremetal',
)


class BareMetalDriverNoDBTestCase(test.TestCase):

    def setUp(self):
        super(BareMetalDriverNoDBTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)
        self.driver = bm_driver.BareMetalDriver(None)

    def test_validate_driver_loading(self):
        self.assertTrue(isinstance(self.driver.driver,
                                    fake.FakeDriver))
        self.assertTrue(isinstance(self.driver.vif_driver,
                                    fake.FakeVifDriver))
        self.assertTrue(isinstance(self.driver.volume_driver,
                                    fake.FakeVolumeDriver))
        self.assertTrue(isinstance(self.driver.firewall_driver,
                                    fake.FakeFirewallDriver))


class BareMetalDriverWithDBTestCase(bm_db_base.BMDBTestCase):

    def setUp(self):
        super(BareMetalDriverWithDBTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)

        fake_image.stub_out_image_service(self.stubs)
        self.context = utils.get_test_admin_context()
        self.driver = bm_driver.BareMetalDriver(None)
        self.node_info = bm_db_utils.new_bm_node(
                id=123,
                service_host='test_host',
                cpus=2,
                memory_mb=2048,
            )
        self.nic_info = [
                {'address': '01:23:45:67:89:01', 'datapath_id': '0x1',
                    'port_no': 1},
                {'address': '01:23:45:67:89:02', 'datapath_id': '0x2',
                    'port_no': 2},
            ]
        self.addCleanup(fake_image.FakeImageService_reset)

    def _create_node(self):
        self.node = db.bm_node_create(self.context, self.node_info)
        for nic in self.nic_info:
            db.bm_interface_create(
                                    self.context,
                                    self.node['id'],
                                    nic['address'],
                                    nic['datapath_id'],
                                    nic['port_no'],
                )
        self.test_instance = utils.get_test_instance()
        self.test_instance['node'] = self.node['id']
        self.spawn_params = dict(
                admin_password='test_pass',
                block_device_info=None,
                context=self.context,
                image_meta=utils.get_test_image_info(None,
                                                        self.test_instance),
                injected_files=[('/fake/path', 'hello world')],
                instance=self.test_instance,
                network_info=utils.get_test_network_info(),
            )

    def test_get_host_stats(self):
        self._create_node()
        stats = self.driver.get_host_stats()
        self.assertTrue(isinstance(stats, list))
        self.assertEqual(len(stats), 1)
        stats = stats[0]
        self.assertEqual(stats['cpu_arch'], 'test')
        self.assertEqual(stats['test_spec'], 'test_value')
        self.assertEqual(stats['hypervisor_type'], 'baremetal')
        self.assertEqual(stats['hypervisor_hostname'], '123')
        self.assertEqual(stats['host'], 'test_host')
        self.assertEqual(stats['vcpus'], 2)
        self.assertEqual(stats['host_memory_total'], 2048)

    def test_spawn_ok(self):
        self._create_node()
        self.driver.spawn(**self.spawn_params)
        row = db.bm_node_get(self.context, self.node['id'])
        self.assertEqual(row['task_state'], baremetal_states.ACTIVE)

    def test_macs_for_instance(self):
        self._create_node()
        expected = set(['01:23:45:67:89:01', '01:23:45:67:89:02'])
        self.assertEqual(
            expected, self.driver.macs_for_instance(self.test_instance))

    def test_macs_for_instance_no_interfaces(self):
        # Nodes cannot boot with no MACs, so we raise an error if that happens.
        self.nic_info = []
        self._create_node()
        self.assertRaises(exception.NovaException,
            self.driver.macs_for_instance, self.test_instance)

    def test_spawn_node_in_use(self):
        self._create_node()
        db.bm_node_update(self.context, self.node['id'],
                {'instance_uuid': '1234-5678'})

        self.assertRaises(exception.NovaException,
                self.driver.spawn, **self.spawn_params)

        row = db.bm_node_get(self.context, self.node['id'])
        self.assertEqual(row['task_state'], None)

    def test_spawn_node_not_found(self):
        self._create_node()
        db.bm_node_update(self.context, self.node['id'],
                {'id': 9876})

        self.assertRaises(exception.NovaException,
                self.driver.spawn, **self.spawn_params)

        row = db.bm_node_get(self.context, 9876)
        self.assertEqual(row['task_state'], None)

    def test_spawn_fails(self):
        self._create_node()

        self.mox.StubOutWithMock(fake.FakePowerManager, 'activate_node')
        fake.FakePowerManager.activate_node().AndRaise(test.TestingException)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                self.driver.spawn, **self.spawn_params)

        row = db.bm_node_get(self.context, self.node['id'])
        self.assertEqual(row['task_state'], baremetal_states.ERROR)
