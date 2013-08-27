# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright (c) 2011-2013 University of Southern California / ISI
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

"""Tests for baremetal tilera driver."""

import os

from oslo.config import cfg

from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.tests.image import fake as fake_image
from nova.tests import utils
from nova.tests.virt.baremetal.db import base as bm_db_base
from nova.tests.virt.baremetal.db import utils as bm_db_utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import db
from nova.virt.baremetal import tilera
from nova.virt.baremetal import utils as bm_utils
from nova.virt.disk import api as disk_api
from nova.virt import fake as fake_virt

CONF = cfg.CONF

COMMON_FLAGS = dict(
    firewall_driver='nova.virt.baremetal.fake.FakeFirewallDriver',
    host='test_host',
)

BAREMETAL_FLAGS = dict(
    driver='nova.virt.baremetal.tilera.Tilera',
    instance_type_extra_specs=['cpu_arch:test', 'test_spec:test_value'],
    power_manager='nova.virt.baremetal.fake.FakePowerManager',
    vif_driver='nova.virt.baremetal.fake.FakeVifDriver',
    volume_driver='nova.virt.baremetal.fake.FakeVolumeDriver',
    group='baremetal',
)


class BareMetalTileraTestCase(bm_db_base.BMDBTestCase):

    def setUp(self):
        super(BareMetalTileraTestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)
        self.driver = tilera.Tilera(fake_virt.FakeVirtAPI())

        fake_image.stub_out_image_service(self.stubs)
        self.addCleanup(fake_image.FakeImageService_reset)
        self.context = utils.get_test_admin_context()
        self.test_block_device_info = None,
        self.instance = utils.get_test_instance()
        self.test_network_info = utils.get_test_network_info()
        self.node_info = bm_db_utils.new_bm_node(
                service_host='test_host',
                cpus=4,
                memory_mb=2048,
            )
        self.nic_info = [
                {'address': '22:22:22:22:22:22', 'datapath_id': '0x1',
                    'port_no': 1},
                {'address': '33:33:33:33:33:33', 'datapath_id': '0x2',
                    'port_no': 2},
            ]

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
        self.instance['node'] = self.node['id']
        self.spawn_params = dict(
                admin_password='test_pass',
                block_device_info=self.test_block_device_info,
                context=self.context,
                image_meta=utils.get_test_image_info(None,
                                                        self.instance),
                injected_files=[('/fake/path', 'hello world')],
                instance=self.instance,
                network_info=self.test_network_info,
            )


class TileraClassMethodsTestCase(BareMetalTileraTestCase):

    def test_build_network_config(self):
        net = utils.get_test_network_info(1)
        config = tilera.build_network_config(net)
        self.assertIn('eth0', config)
        self.assertNotIn('eth1', config)

        net = utils.get_test_network_info(2)
        config = tilera.build_network_config(net)
        self.assertIn('eth0', config)
        self.assertIn('eth1', config)

    def test_build_network_config_dhcp(self):
        self.flags(
                net_config_template='$pybasedir/nova/virt/baremetal/'
                                    'net-dhcp.ubuntu.template',
                group='baremetal',
            )
        net = utils.get_test_network_info()
        net[0]['network']['subnets'][0]['ips'][0]['address'] = '1.2.3.4'
        config = tilera.build_network_config(net)
        self.assertIn('iface eth0 inet dhcp', config)
        self.assertNotIn('address 1.2.3.4', config)

    def test_build_network_config_static(self):
        self.flags(
                net_config_template='$pybasedir/nova/virt/baremetal/'
                                    'net-static.ubuntu.template',
                group='baremetal',
            )
        net = utils.get_test_network_info()
        net[0]['network']['subnets'][0]['ips'][0]['address'] = '1.2.3.4'
        config = tilera.build_network_config(net)
        self.assertIn('iface eth0 inet static', config)
        self.assertIn('address 1.2.3.4', config)

    def test_image_dir_path(self):
        self.assertEqual(
                tilera.get_image_dir_path(self.instance),
                os.path.join(CONF.instances_path, 'instance-00000001'))

    def test_image_file_path(self):
        self.assertEqual(
                tilera.get_image_file_path(self.instance),
                os.path.join(
                    CONF.instances_path, 'instance-00000001', 'disk'))

    def test_tilera_nfs_path(self):
        self._create_node()
        self.node['id'] = '123'
        tilera_nfs_dir = "fs_" + self.node['id']
        self.assertEqual(
                tilera.get_tilera_nfs_path(self.node['id']),
                os.path.join(CONF.baremetal.tftp_root,
                    tilera_nfs_dir))

    def test_get_partition_sizes(self):
        # default "kinda.big" instance
        sizes = tilera.get_partition_sizes(self.instance)
        self.assertEqual(sizes[0], 40960)
        self.assertEqual(sizes[1], 1024)

    def test_swap_not_zero(self):
        # override swap to 0
        instance_type = utils.get_test_instance_type(self.context)
        instance_type['swap'] = 0
        self.instance = utils.get_test_instance(self.context, instance_type)

        sizes = tilera.get_partition_sizes(self.instance)
        self.assertEqual(sizes[0], 40960)
        self.assertEqual(sizes[1], 1)

    def test_get_tftp_image_info(self):
        # Tilera case needs only kernel_id.
        self.instance['kernel_id'] = 'aaaa'
        self.instance['uuid'] = 'fake-uuid'

        # Here, we confirm both that kernel_id was set
        # and that the proper paths are getting set for all of them
        base = os.path.join(CONF.baremetal.tftp_root, self.instance['uuid'])
        res = tilera.get_tftp_image_info(self.instance)
        expected = {
                'kernel': ['aaaa', os.path.join(base, 'kernel')],
                }
        self.assertEqual(res, expected)


class TileraPrivateMethodsTestCase(BareMetalTileraTestCase):

    def test_collect_mac_addresses(self):
        self._create_node()
        address_list = [nic['address'] for nic in self.nic_info]
        address_list.sort()
        macs = self.driver._collect_mac_addresses(self.context, self.node)
        self.assertEqual(macs, address_list)

    def test_cache_tftp_images(self):
        self.instance['kernel_id'] = 'aaaa'
        image_info = tilera.get_tftp_image_info(self.instance)

        self.mox.StubOutWithMock(os, 'makedirs')
        self.mox.StubOutWithMock(os.path, 'exists')
        os.makedirs(os.path.join(CONF.baremetal.tftp_root,
                                 self.instance['uuid'])).AndReturn(True)
        for uuid, path in [image_info[label] for label in image_info]:
            os.path.exists(path).AndReturn(True)
        self.mox.ReplayAll()

        self.driver._cache_tftp_images(
                self.context, self.instance, image_info)
        self.mox.VerifyAll()

    def test_cache_image(self):
        self.mox.StubOutWithMock(os, 'makedirs')
        self.mox.StubOutWithMock(os.path, 'exists')
        os.makedirs(tilera.get_image_dir_path(self.instance)).\
                AndReturn(True)
        os.path.exists(tilera.get_image_file_path(self.instance)).\
                AndReturn(True)
        self.mox.ReplayAll()

        image_meta = utils.get_test_image_info(
                self.context, self.instance)
        self.driver._cache_image(
                self.context, self.instance, image_meta)
        self.mox.VerifyAll()

    def test_inject_into_image(self):
        self._create_node()
        files = []
        self.instance['hostname'] = 'fake hostname'
        files.append(('/etc/hostname', 'fake hostname'))
        self.instance['key_data'] = 'fake ssh key'
        net_info = utils.get_test_network_info(1)
        net = tilera.build_network_config(net_info)
        admin_password = 'fake password'

        self.mox.StubOutWithMock(disk_api, 'inject_data')
        disk_api.inject_data(
                admin_password=admin_password,
                image=tilera.get_image_file_path(self.instance),
                key='fake ssh key',
                metadata=None,
                partition=None,
                net=net,
                files=files,
            ).AndReturn(True)
        self.mox.ReplayAll()

        self.driver._inject_into_image(
                self.context, self.node, self.instance,
                network_info=net_info,
                admin_password=admin_password,
                injected_files=None)
        self.mox.VerifyAll()


class TileraPublicMethodsTestCase(BareMetalTileraTestCase):

    def test_cache_images(self):
        self._create_node()
        self.mox.StubOutWithMock(tilera, "get_tftp_image_info")
        self.mox.StubOutWithMock(self.driver, "_cache_tftp_images")
        self.mox.StubOutWithMock(self.driver, "_cache_image")
        self.mox.StubOutWithMock(self.driver, "_inject_into_image")

        tilera.get_tftp_image_info(self.instance).AndReturn([])
        self.driver._cache_tftp_images(self.context, self.instance, [])
        self.driver._cache_image(self.context, self.instance, [])
        self.driver._inject_into_image(self.context, self.node, self.instance,
                self.test_network_info, None, '')
        self.mox.ReplayAll()

        self.driver.cache_images(
                self.context, self.node, self.instance,
                admin_password='',
                image_meta=[],
                injected_files=None,
                network_info=self.test_network_info,
            )
        self.mox.VerifyAll()

    def test_destroy_images(self):
        self._create_node()
        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        self.mox.StubOutWithMock(bm_utils, 'rmtree_without_raise')

        bm_utils.unlink_without_raise(tilera.get_image_file_path(
                 self.instance))
        bm_utils.rmtree_without_raise(tilera.get_image_dir_path(self.instance))
        self.mox.ReplayAll()

        self.driver.destroy_images(self.context, self.node, self.instance)
        self.mox.VerifyAll()

    def test_activate_bootloader_passes_details(self):
        self._create_node()
        image_info = {
                'kernel': [None, 'cccc'],
            }
        self.instance['uuid'] = 'fake-uuid'
        iqn = "iqn-%s" % self.instance['uuid']
        tilera_config = 'this is a fake tilera config'
        self.instance['uuid'] = 'fake-uuid'
        tilera_path = tilera.get_tilera_nfs_path(self.instance)
        image_path = tilera.get_image_file_path(self.instance)

        self.mox.StubOutWithMock(tilera, 'get_tftp_image_info')
        self.mox.StubOutWithMock(tilera, 'get_partition_sizes')

        tilera.get_tftp_image_info(self.instance).AndReturn(image_info)
        tilera.get_partition_sizes(self.instance).AndReturn((0, 0))

        self.mox.ReplayAll()

        self.driver.activate_bootloader(self.context, self.node, self.instance,
                                        network_info=self.test_network_info)

        self.mox.VerifyAll()

    def test_activate_and_deactivate_bootloader(self):
        self._create_node()
        self.instance['uuid'] = 'fake-uuid'
        tilera_path = tilera.get_tilera_nfs_path(self.instance)
        image_path = tilera.get_image_file_path(self.instance)

        self.mox.ReplayAll()

        # activate and deactivate the bootloader
        # and check the deployment task_state in the database
        row = db.bm_node_get(self.context, 1)
        self.assertTrue(row['deploy_key'] is None)

        self.driver.activate_bootloader(self.context, self.node, self.instance,
                                        network_info=self.test_network_info)
        row = db.bm_node_get(self.context, 1)
        self.assertTrue(row['deploy_key'] is not None)

        self.driver.deactivate_bootloader(self.context, self.node,
                                            self.instance)
        row = db.bm_node_get(self.context, 1)
        self.assertTrue(row['deploy_key'] is None)

        self.mox.VerifyAll()

    def test_deactivate_bootloader_for_nonexistent_instance(self):
        self._create_node()
        self.node['id'] = 'fake-node-id'

        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        self.mox.StubOutWithMock(bm_utils, 'rmtree_without_raise')
        self.mox.StubOutWithMock(tilera, 'get_tftp_image_info')
        self.mox.StubOutWithMock(self.driver, '_collect_mac_addresses')

        tilera_path = tilera.get_tilera_nfs_path(self.node['id'])

        tilera.get_tftp_image_info(self.instance).\
                AndRaise(exception.NovaException)
        self.driver._collect_mac_addresses(self.context, self.node).\
                AndRaise(db_exc.DBError)
        self.mox.ReplayAll()

        self.driver.deactivate_bootloader(
            self.context, self.node, self.instance)
        self.mox.VerifyAll()

    def test_activate_node(self):
        self._create_node()
        self.instance['uuid'] = 'fake-uuid'

        db.bm_node_update(self.context, 1,
                {'task_state': baremetal_states.DEPLOYING,
                 'instance_uuid': 'fake-uuid'})

        # test DEPLOYDONE
        db.bm_node_update(self.context, 1,
                {'task_state': baremetal_states.DEPLOYDONE})
        self.driver.activate_node(self.context, self.node, self.instance)

        # test no deploy -- state is just ACTIVE
        db.bm_node_update(self.context, 1,
                {'task_state': baremetal_states.ACTIVE})
        self.driver.activate_node(self.context, self.node, self.instance)

        # test node gone
        db.bm_node_destroy(self.context, 1)
        self.assertRaises(exception.InstanceDeployFailure,
                self.driver.activate_node,
                self.context, self.node, self.instance)
