# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Tests for baremetal pxe driver."""

import os

import mox

from oslo.config import cfg
from testtools import matchers

from nova import exception
from nova.objects import flavor as flavor_obj
from nova.openstack.common.db import exception as db_exc
from nova.tests.image import fake as fake_image
from nova.tests import utils
from nova.tests.virt.baremetal.db import base as bm_db_base
from nova.tests.virt.baremetal.db import utils as bm_db_utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import db
from nova.virt.baremetal import pxe
from nova.virt.baremetal import utils as bm_utils
from nova.virt.disk import api as disk_api
from nova.virt import fake as fake_virt

CONF = cfg.CONF

COMMON_FLAGS = dict(
    firewall_driver='nova.virt.baremetal.fake.FakeFirewallDriver',
    host='test_host',
)

BAREMETAL_FLAGS = dict(
    driver='nova.virt.baremetal.pxe.PXE',
    flavor_extra_specs=['cpu_arch:test', 'test_spec:test_value'],
    power_manager='nova.virt.baremetal.fake.FakePowerManager',
    vif_driver='nova.virt.baremetal.fake.FakeVifDriver',
    volume_driver='nova.virt.baremetal.fake.FakeVolumeDriver',
    group='baremetal',
)


class BareMetalPXETestCase(bm_db_base.BMDBTestCase):

    def setUp(self):
        super(BareMetalPXETestCase, self).setUp()
        self.flags(**COMMON_FLAGS)
        self.flags(**BAREMETAL_FLAGS)
        self.driver = pxe.PXE(fake_virt.FakeVirtAPI())

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
        # File injection is off by default, but we should continue to test it
        # until it is removed.
        CONF.set_override('use_file_injection', True, 'baremetal')
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


class PXEClassMethodsTestCase(BareMetalPXETestCase):

    def test_build_pxe_config(self):
        args = {
                'deployment_id': 'aaa',
                'deployment_key': 'bbb',
                'deployment_iscsi_iqn': 'ccc',
                'deployment_aki_path': 'ddd',
                'deployment_ari_path': 'eee',
                'aki_path': 'fff',
                'ari_path': 'ggg',
                'network_info': self.test_network_info,
            }
        config = pxe.build_pxe_config(**args)
        self.assertThat(config, matchers.StartsWith('default deploy'))

        # deploy bits are in the deploy section
        start = config.index('label deploy')
        end = config.index('label boot')
        self.assertThat(config[start:end], matchers.MatchesAll(
            matchers.Contains('kernel ddd'),
            matchers.Contains('initrd=eee'),
            matchers.Contains('deployment_id=aaa'),
            matchers.Contains('deployment_key=bbb'),
            matchers.Contains('iscsi_target_iqn=ccc'),
            matchers.Not(matchers.Contains('kernel fff')),
            ))

        # boot bits are in the boot section
        start = config.index('label boot')
        self.assertThat(config[start:], matchers.MatchesAll(
            matchers.Contains('kernel fff'),
            matchers.Contains('initrd=ggg'),
            matchers.Not(matchers.Contains('kernel ddd')),
            ))

    def test_build_pxe_network_config(self):
        self.flags(
                pxe_network_config=True,
                group='baremetal',
            )
        net = utils.get_test_network_info(1)
        config = pxe.build_pxe_network_config(net)
        self.assertIn('eth0:off', config)
        self.assertNotIn('eth1', config)

        net = utils.get_test_network_info(2)
        config = pxe.build_pxe_network_config(net)
        self.assertIn('eth0:off', config)
        self.assertIn('eth1:off', config)

    def test_build_network_config(self):
        net = utils.get_test_network_info(1)
        config = pxe.build_network_config(net)
        self.assertIn('eth0', config)
        self.assertNotIn('eth1', config)

        net = utils.get_test_network_info(2)
        config = pxe.build_network_config(net)
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
        config = pxe.build_network_config(net)
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
        config = pxe.build_network_config(net)
        self.assertIn('iface eth0 inet static', config)
        self.assertIn('address 1.2.3.4', config)

    def test_build_network_config_static_parameters(self):
        self.flags(use_ipv6=True)
        self.flags(
                net_config_template='$pybasedir/nova/virt/baremetal/'
                                    'net-static.ubuntu.template',
                group='baremetal'
            )

        net = utils.get_test_network_info()
        net[0]['network']['subnets'][0]['cidr'] = '10.1.1.0/24'
        net[0]['network']['subnets'][0]['gateway']['address'] = '10.1.1.1'
        net[0]['network']['subnets'][0]['dns'][0]['address'] = '10.1.1.2'
        net[0]['network']['subnets'][0]['dns'][1]['address'] = '10.1.1.3'

        net[0]['network']['subnets'][1]['cidr'] = 'fc00::/7'
        net[0]['network']['subnets'][1]['ips'][0]['address'] = 'fc00::1'
        net[0]['network']['subnets'][1]['gateway']['address'] = 'fc00::2'
        config = pxe.build_network_config(net)

        self.assertIn('iface eth0 inet static', config)
        self.assertIn('gateway 10.1.1.1', config)
        self.assertIn('dns-nameservers 10.1.1.2 10.1.1.3', config)

        self.assertIn('iface eth0 inet6 static', config)
        self.assertIn('address fc00::1', config)
        self.assertIn('netmask 7', config)
        self.assertIn('gateway fc00::2', config)

    def test_image_dir_path(self):
        self.assertEqual(
                os.path.join(CONF.instances_path, 'instance-00000001'),
                pxe.get_image_dir_path(self.instance))

    def test_image_file_path(self):
        self.assertEqual(
                os.path.join(
                    CONF.instances_path, 'instance-00000001', 'disk'),
                pxe.get_image_file_path(self.instance))

    def test_pxe_config_file_path(self):
        self.instance['uuid'] = 'aaaa-bbbb-cccc'
        self.assertEqual(
                os.path.join(CONF.baremetal.tftp_root,
                    'aaaa-bbbb-cccc', 'config'),
                pxe.get_pxe_config_file_path(self.instance))

    def test_pxe_mac_path(self):
        self.assertEqual(
                os.path.join(CONF.baremetal.tftp_root,
                    'pxelinux.cfg', '01-23-45-67-89-ab'),
                pxe.get_pxe_mac_path('23:45:67:89:AB'))

    def test_get_instance_deploy_ids(self):
        self.instance['extra_specs'] = {
                'baremetal:deploy_kernel_id': 'aaaa',
                'baremetal:deploy_ramdisk_id': 'bbbb',
                }
        self.flags(deploy_kernel="fail", group='baremetal')
        self.flags(deploy_ramdisk="fail", group='baremetal')

        self.assertEqual('aaaa', pxe.get_deploy_aki_id(self.instance))
        self.assertEqual('bbbb', pxe.get_deploy_ari_id(self.instance))

    def test_get_default_deploy_ids(self):
        self.instance['extra_specs'] = {}
        self.flags(deploy_kernel="aaaa", group='baremetal')
        self.flags(deploy_ramdisk="bbbb", group='baremetal')

        self.assertEqual('aaaa', pxe.get_deploy_aki_id(self.instance))
        self.assertEqual('bbbb', pxe.get_deploy_ari_id(self.instance))

    def test_get_partition_sizes(self):
        # default "kinda.big" instance
        sizes = pxe.get_partition_sizes(self.instance)
        self.assertEqual(40960, sizes[0])
        self.assertEqual(1024, sizes[1])

    def test_swap_not_zero(self):
        # override swap to 0
        flavor = utils.get_test_flavor(self.context)
        flavor['swap'] = 0
        self.instance = utils.get_test_instance(self.context, flavor)

        sizes = pxe.get_partition_sizes(self.instance)
        self.assertEqual(40960, sizes[0])
        self.assertEqual(1, sizes[1])

    def test_get_tftp_image_info(self):
        flavor = utils.get_test_flavor()
        # Raises an exception when options are neither specified
        # on the instance nor in configuration file
        CONF.baremetal.deploy_kernel = None
        CONF.baremetal.deploy_ramdisk = None
        self.assertRaises(exception.NovaException,
                pxe.get_tftp_image_info,
                self.instance, flavor)

        # Test that other non-true values also raise an exception
        CONF.baremetal.deploy_kernel = ""
        CONF.baremetal.deploy_ramdisk = ""
        self.assertRaises(exception.NovaException,
                pxe.get_tftp_image_info,
                self.instance, flavor)

        # Even if the instance includes kernel_id and ramdisk_id,
        # we still need deploy_kernel_id and deploy_ramdisk_id.
        # If those aren't present in instance[], and not specified in
        # config file, then we raise an exception.
        self.instance['kernel_id'] = 'aaaa'
        self.instance['ramdisk_id'] = 'bbbb'
        self.assertRaises(exception.NovaException,
                pxe.get_tftp_image_info,
                self.instance, flavor)

        # If an instance doesn't specify deploy_kernel_id or deploy_ramdisk_id,
        # but defaults are set in the config file, we should use those.

        # Here, we confirm both that all four values were set
        # and that the proper paths are getting set for all of them
        CONF.baremetal.deploy_kernel = 'cccc'
        CONF.baremetal.deploy_ramdisk = 'dddd'
        base = os.path.join(CONF.baremetal.tftp_root, self.instance['uuid'])
        res = pxe.get_tftp_image_info(self.instance, flavor)
        expected = {
                'kernel': ['aaaa', os.path.join(base, 'kernel')],
                'ramdisk': ['bbbb', os.path.join(base, 'ramdisk')],
                'deploy_kernel': ['cccc', os.path.join(base, 'deploy_kernel')],
                'deploy_ramdisk': ['dddd',
                                    os.path.join(base, 'deploy_ramdisk')],
                }
        self.assertEqual(expected, res)

        # If deploy_kernel_id and deploy_ramdisk_id are specified on
        # image extra_specs, this should override any default configuration.
        # Note that it is passed on the 'instance' object, despite being
        # inherited from the flavor_extra_specs table.
        extra_specs = {
                'baremetal:deploy_kernel_id': 'eeee',
                'baremetal:deploy_ramdisk_id': 'ffff',
            }
        flavor['extra_specs'] = extra_specs
        res = pxe.get_tftp_image_info(self.instance, flavor)
        self.assertEqual('eeee', res['deploy_kernel'][0])
        self.assertEqual('ffff', res['deploy_ramdisk'][0])

        # However, if invalid values are passed on the image extra_specs,
        # this should still raise an exception.
        extra_specs = {
                'baremetal:deploy_kernel_id': '',
                'baremetal:deploy_ramdisk_id': '',
            }
        flavor['extra_specs'] = extra_specs
        self.assertRaises(exception.NovaException,
                pxe.get_tftp_image_info,
                self.instance, flavor)


class PXEPrivateMethodsTestCase(BareMetalPXETestCase):

    def test_collect_mac_addresses(self):
        self._create_node()
        address_list = [nic['address'] for nic in self.nic_info]
        address_list.sort()
        macs = self.driver._collect_mac_addresses(self.context, self.node)
        self.assertEqual(address_list, macs)

    def test_cache_tftp_images(self):
        self.instance['kernel_id'] = 'aaaa'
        self.instance['ramdisk_id'] = 'bbbb'
        flavor = utils.get_test_flavor()
        extra_specs = {
                'baremetal:deploy_kernel_id': 'cccc',
                'baremetal:deploy_ramdisk_id': 'dddd',
            }
        flavor['extra_specs'] = extra_specs
        image_info = pxe.get_tftp_image_info(self.instance, flavor)

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
        self.mox.StubOutWithMock(os, 'unlink')
        self.mox.StubOutWithMock(os.path, 'exists')
        os.makedirs(pxe.get_image_dir_path(self.instance)).AndReturn(True)
        disk_path = os.path.join(
            pxe.get_image_dir_path(self.instance), 'disk')
        os.unlink(disk_path).AndReturn(None)
        os.path.exists(disk_path).AndReturn(True)
        os.path.exists(pxe.get_image_file_path(self.instance)).\
                AndReturn(True)
        self.mox.ReplayAll()

        image_meta = utils.get_test_image_info(
                self.context, self.instance)
        self.driver._cache_image(
                self.context, self.instance, image_meta)
        self.mox.VerifyAll()

    def test_inject_into_image(self):
        # NOTE(deva): we could also test this method by stubbing
        #             nova.virt.disk.api._inject_*_into_fs
        self._create_node()
        files = []
        self.instance['hostname'] = 'fake hostname'
        files.append(('/etc/hostname', 'fake hostname'))
        self.instance['key_data'] = 'fake ssh key'
        net_info = utils.get_test_network_info(1)
        net = pxe.build_network_config(net_info)
        admin_password = 'fake password'

        self.mox.StubOutWithMock(disk_api, 'inject_data')
        disk_api.inject_data(
                admin_password=admin_password,
                image=pxe.get_image_file_path(self.instance),
                key='fake ssh key',
                metadata=None,
                partition=None,
                net=net,
                files=files,    # this is what we're really testing
            ).AndReturn(True)
        self.mox.ReplayAll()

        self.driver._inject_into_image(
                self.context, self.node, self.instance,
                network_info=net_info,
                admin_password=admin_password,
                injected_files=None)
        self.mox.VerifyAll()


class PXEPublicMethodsTestCase(BareMetalPXETestCase):

    def test_cache_images(self):
        self._create_node()
        self.mox.StubOutWithMock(flavor_obj.Flavor, 'get_by_id')
        self.mox.StubOutWithMock(pxe, "get_tftp_image_info")
        self.mox.StubOutWithMock(self.driver, "_cache_tftp_images")
        self.mox.StubOutWithMock(self.driver, "_cache_image")
        self.mox.StubOutWithMock(self.driver, "_inject_into_image")

        flavor_obj.Flavor.get_by_id(self.context,
                                    self.instance['instance_type_id']
                                    ).AndReturn({})
        pxe.get_tftp_image_info(self.instance, {}).AndReturn([])
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

        bm_utils.unlink_without_raise(pxe.get_image_file_path(self.instance))
        bm_utils.rmtree_without_raise(pxe.get_image_dir_path(self.instance))
        self.mox.ReplayAll()

        self.driver.destroy_images(self.context, self.node, self.instance)
        self.mox.VerifyAll()

    def test_dhcp_options_for_instance(self):
        self._create_node()
        self.mox.ReplayAll()
        expected = [{'opt_name': 'bootfile-name',
                     'opt_value': CONF.baremetal.pxe_bootfile_name},
                    {'opt_name': 'server-ip-address', 'opt_value': CONF.my_ip},
                    {'opt_name': 'tftp-server', 'opt_value': CONF.my_ip}]
        res = self.driver.dhcp_options_for_instance(self.instance)
        self.assertEqual(expected.sort(), res.sort())
        self.mox.VerifyAll()

    def test_activate_bootloader_passes_details(self):
        self._create_node()
        macs = [nic['address'] for nic in self.nic_info]
        macs.sort()
        image_info = {
                'deploy_kernel': [None, 'aaaa'],
                'deploy_ramdisk': [None, 'bbbb'],
                'kernel': [None, 'cccc'],
                'ramdisk': [None, 'dddd'],
            }
        self.instance['uuid'] = 'fake-uuid'
        iqn = "iqn-%s" % self.instance['uuid']
        pxe_config = 'this is a fake pxe config'
        pxe_path = pxe.get_pxe_config_file_path(self.instance)
        image_path = pxe.get_image_file_path(self.instance)

        self.mox.StubOutWithMock(flavor_obj.Flavor, 'get_by_id')
        self.mox.StubOutWithMock(pxe, 'get_tftp_image_info')
        self.mox.StubOutWithMock(pxe, 'get_partition_sizes')
        self.mox.StubOutWithMock(bm_utils, 'random_alnum')
        self.mox.StubOutWithMock(pxe, 'build_pxe_config')
        self.mox.StubOutWithMock(bm_utils, 'write_to_file')
        self.mox.StubOutWithMock(bm_utils, 'create_link_without_raise')

        flavor_obj.Flavor.get_by_id(self.context,
                                    self.instance['instance_type_id']
                                    ).AndReturn({})
        pxe.get_tftp_image_info(self.instance, {}).AndReturn(image_info)
        pxe.get_partition_sizes(self.instance).AndReturn((0, 0, 0))
        bm_utils.random_alnum(32).AndReturn('alnum')
        pxe.build_pxe_config(
                self.node['id'], 'alnum', iqn,
                'aaaa', 'bbbb', 'cccc', 'dddd',
                self.test_network_info).AndReturn(pxe_config)
        bm_utils.write_to_file(pxe_path, pxe_config)
        for mac in macs:
            bm_utils.create_link_without_raise(
                    pxe_path, pxe.get_pxe_mac_path(mac))

        self.mox.ReplayAll()

        self.driver.activate_bootloader(self.context, self.node, self.instance,
                                        network_info=self.test_network_info)

        self.mox.VerifyAll()

    def test_activate_and_deactivate_bootloader(self):
        self._create_node()
        flavor = flavor_obj.Flavor(
            context=self.context,
            extra_specs={
                'baremetal:deploy_kernel_id': 'eeee',
                'baremetal:deploy_ramdisk_id': 'ffff',
                })
        self.instance['uuid'] = 'fake-uuid'

        self.mox.StubOutWithMock(flavor_obj.Flavor, 'get_by_id')
        self.mox.StubOutWithMock(bm_utils, 'write_to_file')
        self.mox.StubOutWithMock(bm_utils, 'create_link_without_raise')
        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        self.mox.StubOutWithMock(bm_utils, 'rmtree_without_raise')

        flavor_obj.Flavor.get_by_id(
            self.context, self.instance['instance_type_id']).AndReturn(
                flavor)

        # create the config file
        bm_utils.write_to_file(mox.StrContains('fake-uuid'),
                               mox.StrContains(CONF.baremetal.tftp_root))
        # unlink and link the 2 interfaces
        for i in range(2):
            bm_utils.unlink_without_raise(mox.Or(
                    mox.StrContains('fake-uuid'),
                    mox.StrContains(CONF.baremetal.tftp_root)))
            bm_utils.create_link_without_raise(
                    mox.StrContains('fake-uuid'),
                    mox.StrContains(CONF.baremetal.tftp_root))
        # unlink all 2 interfaces, 4 images, and the config file
        for i in range(7):
            bm_utils.unlink_without_raise(mox.Or(
                    mox.StrContains('fake-uuid'),
                    mox.StrContains(CONF.baremetal.tftp_root)))
        bm_utils.rmtree_without_raise(mox.StrContains('fake-uuid'))

        self.mox.ReplayAll()

        # activate and deactivate the bootloader
        # and check the deployment task_state in the database
        row = db.bm_node_get(self.context, 1)
        self.assertIsNone(row['deploy_key'])

        self.driver.activate_bootloader(self.context, self.node, self.instance,
                                        network_info=self.test_network_info)
        row = db.bm_node_get(self.context, 1)
        self.assertIsNotNone(row['deploy_key'])

        self.driver.deactivate_bootloader(self.context, self.node,
                                            self.instance)
        row = db.bm_node_get(self.context, 1)
        self.assertIsNone(row['deploy_key'])

        self.mox.VerifyAll()

    def test_deactivate_bootloader_for_nonexistent_instance(self):
        self._create_node()
        self.instance['uuid'] = 'fake-uuid'
        pxe_path = pxe.get_pxe_config_file_path(self.instance)

        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        self.mox.StubOutWithMock(bm_utils, 'rmtree_without_raise')
        self.mox.StubOutWithMock(pxe, 'get_tftp_image_info')
        self.mox.StubOutWithMock(self.driver, '_collect_mac_addresses')

        extra_specs = dict(extra_specs={
            'baremetal:deploy_ramdisk_id': 'ignore',
            'baremetal:deploy_kernel_id': 'ignore'})
        pxe.get_tftp_image_info(self.instance, extra_specs).\
                AndRaise(exception.NovaException)
        bm_utils.unlink_without_raise(pxe_path)
        self.driver._collect_mac_addresses(self.context, self.node).\
                AndRaise(db_exc.DBError)
        bm_utils.rmtree_without_raise(
                os.path.join(CONF.baremetal.tftp_root, 'fake-uuid'))
        self.mox.ReplayAll()

        self.driver.deactivate_bootloader(
            self.context, self.node, self.instance)
        self.mox.VerifyAll()

    def test_activate_node(self):
        self._create_node()
        self.instance['uuid'] = 'fake-uuid'
        self.flags(pxe_deploy_timeout=1, group='baremetal')

        db.bm_node_update(self.context, 1,
                {'task_state': baremetal_states.DEPLOYING,
                 'instance_uuid': 'fake-uuid'})

        # test timeout
        self.assertRaises(exception.InstanceDeployFailure,
                self.driver.activate_node,
                self.context, self.node, self.instance)

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
