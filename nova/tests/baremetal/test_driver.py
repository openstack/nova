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

"""
Tests for baremetal driver.
"""

from nova import exception
from nova.openstack.common import cfg
from nova.tests.baremetal.db import base
from nova.tests.baremetal.db import utils
from nova.tests.image import fake as fake_image
from nova.tests import test_virt_drivers
from nova.tests import utils as test_utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import db
from nova.virt.baremetal import driver as bm_driver
from nova.virt.baremetal import volume_driver
from nova.virt.firewall import NoopFirewallDriver


CONF = cfg.CONF


class FakeVifDriver(object):

    def plug(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        pass

FakeFirewallDriver = NoopFirewallDriver


class FakeVolumeDriver(volume_driver.VolumeDriver):
    def __init__(self, virtapi):
        super(FakeVolumeDriver, self).__init__(virtapi)
        self._initiator = "testtesttest"


NODE = utils.new_bm_node(cpus=2, memory_mb=4096, service_host="host1")
NICS = [
       {'address': '01:23:45:67:89:01', 'datapath_id': '0x1', 'port_no': 1, },
       {'address': '01:23:45:67:89:02', 'datapath_id': '0x2', 'port_no': 2, },
        ]


def class_path(class_):
    return class_.__module__ + '.' + class_.__name__


COMMON_FLAGS = dict(
    baremetal_sql_connection='sqlite:///:memory:',
    baremetal_driver='nova.virt.baremetal.fake.Fake',
    power_manager='nova.virt.baremetal.fake.FakePowerManager',
    baremetal_vif_driver=class_path(FakeVifDriver),
    firewall_driver=class_path(FakeFirewallDriver),
    baremetal_volume_driver=class_path(FakeVolumeDriver),
    instance_type_extra_specs=['cpu_arch:test'],
    host=NODE['service_host'],
)


def _create_baremetal_stuff():
    context = test_utils.get_test_admin_context()
    node = db.bm_node_create(context, NODE)
    for nic in NICS:
        db.bm_interface_create(context,
                               node['id'],
                               nic['address'],
                               nic['datapath_id'],
                               nic['port_no'])
    return node


class BaremetalDriverSpawnTestCase(base.Database):

    def setUp(self):
        super(BaremetalDriverSpawnTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        fake_image.stub_out_image_service(self.stubs)

        self.node = _create_baremetal_stuff()
        self.node_id = self.node['id']

        self.context = test_utils.get_test_admin_context()
        self.instance = test_utils.get_test_instance()
        self.network_info = test_utils.get_test_network_info()
        self.block_device_info = None
        self.image_meta = test_utils.get_test_image_info(None, self.instance)
        self.driver = bm_driver.BareMetalDriver(None)
        self.kwargs = dict(
                context=self.context,
                instance=self.instance,
                image_meta=self.image_meta,
                injected_files=[('/foo', 'bar'), ('/abc', 'xyz')],
                admin_password='testpass',
                network_info=self.network_info,
                block_device_info=self.block_device_info)
        self.addCleanup(fake_image.FakeImageService_reset)

    def test_ok(self):
        self.instance['node'] = str(self.node_id)
        self.driver.spawn(**self.kwargs)
        node = db.bm_node_get(self.context, self.node_id)
        self.assertEqual(node['instance_uuid'], self.instance['uuid'])
        self.assertEqual(node['task_state'], baremetal_states.ACTIVE)

    def test_without_node(self):
        self.assertRaises(
                exception.NovaException,
                self.driver.spawn,
                **self.kwargs)

    def test_node_not_found(self):
        self.instance['node'] = "123456789"
        self.assertRaises(
                exception.InstanceNotFound,
                self.driver.spawn,
                **self.kwargs)

    def test_node_in_use(self):
        self.instance['node'] = str(self.node_id)
        db.bm_node_update(self.context, self.node_id,
                          {'instance_uuid': 'something'})
        self.assertRaises(
                exception.NovaException,
                self.driver.spawn,
                **self.kwargs)


class BaremetalDriverTestCase(test_virt_drivers._VirtDriverTestCase,
                              base.Database):

    def setUp(self):
        super(BaremetalDriverTestCase, self).setUp()
        self.driver_module = 'nova.virt.baremetal.BareMetalDriver'
        self.flags(**COMMON_FLAGS)
        self.node = _create_baremetal_stuff()
        self.node_id = self.node['id']
        fake_image.stub_out_image_service(self.stubs)
        self.addCleanup(fake_image.FakeImageService_reset)

    def _get_running_instance(self):
        instance_ref = test_utils.get_test_instance()
        instance_ref['node'] = str(self.node_id)
        network_info = test_utils.get_test_network_info()
        image_info = test_utils.get_test_image_info(None, instance_ref)
        self.connection.spawn(self.ctxt, instance_ref, image_info,
                              [], 'herp', network_info=network_info)
        return instance_ref, network_info

    def test_loading_baremetal_drivers(self):
        from nova.virt.baremetal import fake
        drv = bm_driver.BareMetalDriver(None)
        self.assertTrue(isinstance(drv.baremetal_nodes, fake.Fake))
        self.assertTrue(isinstance(drv._vif_driver, FakeVifDriver))
        self.assertTrue(isinstance(drv._firewall_driver, FakeFirewallDriver))
        self.assertTrue(isinstance(drv._volume_driver, FakeVolumeDriver))

    def test_get_host_stats(self):
        self.flags(instance_type_extra_specs=['cpu_arch:x86_64',
                                              'x:123',
                                              'y:456', ])
        drv = bm_driver.BareMetalDriver(None)
        cap_list = drv.get_host_stats()
        self.assertTrue(isinstance(cap_list, list))
        self.assertEqual(len(cap_list), 1)
        cap = cap_list[0]
        self.assertEqual(cap['cpu_arch'], 'x86_64')
        self.assertEqual(cap['x'], '123')
        self.assertEqual(cap['y'], '456')
        self.assertEqual(cap['hypervisor_type'], 'baremetal')
        self.assertEqual(cap['baremetal_driver'],
                         'nova.virt.baremetal.fake.Fake')
