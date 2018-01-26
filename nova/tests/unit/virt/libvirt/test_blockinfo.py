#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
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

import copy

import fixtures
import mock

from nova import block_device
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova import test
from nova.tests.unit import fake_block_device
import nova.tests.unit.image.fake
from nova.tests.unit.virt import fakelibosinfo
from nova.tests import uuidsentinel as uuids
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.virt.libvirt import blockinfo


class LibvirtBlockInfoTest(test.NoDBTestCase):

    def setUp(self):
        super(LibvirtBlockInfoTest, self).setUp()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.get_admin_context()
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.test_instance = {
            'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
            'memory_kb': '1024000',
            'basepath': '/some/path',
            'bridge_name': 'br100',
            'vcpus': 2,
            'project_id': 'fake',
            'bridge': 'br101',
            'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
            'root_gb': 10,
            'ephemeral_gb': 20,
            'instance_type_id': 2,  # m1.tiny
            'config_drive': None,
            'system_metadata': {},
        }
        self.test_image_meta = {
            'disk_format': 'raw',
        }

        flavor = objects.Flavor(memory_mb=128,
                                root_gb=0,
                                name='m1.micro',
                                ephemeral_gb=0,
                                vcpus=1,
                                swap=0,
                                rxtx_factor=1.0,
                                flavorid='1',
                                vcpu_weight=None,
                                id=2)
        self.test_instance['flavor'] = flavor
        self.test_instance['old_flavor'] = None
        self.test_instance['new_flavor'] = None

    def test_volume_in_mapping(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'device_type': 'disk', 'guest_format': 'ext4',
                       'device_name': '/dev/sdc1', 'size': 10},
                      {'disk_bus': 'ide', 'guest_format': None,
                       'device_name': '/dev/sdd', 'size': 10}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'},
                                {'mount_device': '/dev/sdf',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        def _assert_volume_in_mapping(device_name, true_or_false):
            self.assertEqual(
                true_or_false,
                block_device.volume_in_mapping(device_name,
                                               block_device_info))

        _assert_volume_in_mapping('sda', False)
        _assert_volume_in_mapping('sdb', True)
        _assert_volume_in_mapping('sdc1', True)
        _assert_volume_in_mapping('sdd', True)
        _assert_volume_in_mapping('sde', True)
        _assert_volume_in_mapping('sdf', True)
        _assert_volume_in_mapping('sdg', False)
        _assert_volume_in_mapping('sdh1', False)

    def test_find_disk_dev(self):
        mapping = {
            "disk.local": {
                'dev': 'sda',
                'bus': 'scsi',
                'type': 'disk',
                },
            "disk.swap": {
                'dev': 'sdc',
                'bus': 'scsi',
                'type': 'disk',
                },
            }

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'scsi')
        self.assertEqual('sdb', dev)

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'virtio')
        self.assertEqual('vda', dev)

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'fdc')
        self.assertEqual('fda', dev)

    @mock.patch('nova.virt.libvirt.blockinfo.has_disk_dev', return_value=True)
    def test_find_disk_dev_for_disk_bus_no_free_error(self, has_disk_dev_mock):
        # Tests that an exception is raised when all devices for a given prefix
        # are already reserved.
        mapping = {
            'disk': {
                'bus': 'ide',
                'dev': 'hda',
                'type': 'cdrom',
                'boot_index': '1',
            }
        }
        self.assertRaises(exception.NovaException,
                          blockinfo.find_disk_dev_for_disk_bus,
                          mapping, 'ide')

    def test_get_next_disk_dev(self):
        mapping = {}
        mapping['disk.local'] = blockinfo.get_next_disk_info(mapping,
                                                             'virtio')
        self.assertEqual({'dev': 'vda', 'bus': 'virtio', 'type': 'disk'},
                         mapping['disk.local'])

        mapping['disk.swap'] = blockinfo.get_next_disk_info(mapping,
                                                            'virtio')
        self.assertEqual({'dev': 'vdb', 'bus': 'virtio', 'type': 'disk'},
                         mapping['disk.swap'])

        mapping['disk.config'] = blockinfo.get_next_disk_info(mapping,
                                                              'ide',
                                                              'cdrom')
        self.assertEqual({'dev': 'hda', 'bus': 'ide', 'type': 'cdrom'},
                         mapping['disk.config'])

    def test_get_next_disk_dev_boot_index(self):
        info = blockinfo.get_next_disk_info({}, 'virtio', boot_index=-1)
        self.assertEqual({'dev': 'vda', 'bus': 'virtio', 'type': 'disk'}, info)

        info = blockinfo.get_next_disk_info({}, 'virtio', boot_index=2)
        self.assertEqual({'dev': 'vda', 'bus': 'virtio',
                          'type': 'disk', 'boot_index': '2'},
                         info)

    def test_get_disk_mapping_simple(self):
        # The simplest possible disk mapping setup, all defaults

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        with mock.patch.object(instance_ref, 'get_flavor',
                               return_value=instance_ref.flavor) as get_flavor:
            mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                                 "virtio", "ide",
                                                 image_meta)
        # Since there was no block_device_info passed to get_disk_mapping we
        # expect to get the swap info from the flavor in the instance.
        get_flavor.assert_called_once_with()

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_rootdev(self):
        # A simple disk mapping setup, but with custom root device name

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        block_device_info = {
            'root_device_name': '/dev/sda'
            }

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            'disk': {'bus': 'scsi', 'dev': 'sda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'scsi', 'dev': 'sda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_rescue(self):
        # A simple disk mapping setup, but in rescue mode

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             rescue=True)

        expect = {
            'disk.rescue': {'bus': 'virtio', 'dev': 'vda',
                            'type': 'disk', 'boot_index': '1'},
            'disk': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_rescue_with_config(self):
        # A simple disk mapping setup, but in rescue mode with a config drive

        test_instance_with_config = self.test_instance
        test_instance_with_config['config_drive'] = True
        instance_ref = objects.Instance(**test_instance_with_config)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             rescue=True)

        expect_disk_config_rescue = {
            'bus': 'ide', 'dev': 'hda', 'type': 'cdrom'}
        if blockinfo.libvirt_utils.get_arch({}) == 'aarch64':
            expect_disk_config_rescue['bus'] = 'scsi'
            expect_disk_config_rescue['dev'] = 'sda'
        expect = {
            'disk.rescue': {'bus': 'virtio', 'dev': 'vda',
                            'type': 'disk', 'boot_index': '1'},
            'disk': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config.rescue': expect_disk_config_rescue,
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_lxc(self):
        # A simple disk mapping setup, but for lxc

        self.test_instance['ephemeral_gb'] = 0
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("lxc", instance_ref,
                                             "lxc", "lxc",
                                             image_meta)
        expect = {
            'disk': {'bus': 'lxc', 'dev': None,
                     'type': 'disk', 'boot_index': '1'},
            'root': {'bus': 'lxc', 'dev': None,
                     'type': 'disk', 'boot_index': '1'},
        }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_iso(self):
        # A simple disk mapping setup, but with a ISO for root device

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict({'disk_format': 'iso'})

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta)

        expect = {
            'disk': {'bus': 'ide', 'dev': 'hda',
                     'type': 'cdrom', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'ide', 'dev': 'hda',
                     'type': 'cdrom', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_swap(self):
        # A simple disk mapping setup, but with a swap device added

        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.flavor.swap = 5
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_volumes_swap(self):
        # A disk mapping setup with volumes attached, then a swap device added

        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.root_device_name = '/dev/vda'
        instance_ref.ephemeral_gb = 0

        block_dev_info = {'swap': None, 'root_device_name': u'/dev/vda',
            'ephemerals': [],
            'block_device_mapping': [{'boot_index': None,
                                      'mount_device': u'/dev/vdb',
                                      'connection_info': {},
                                      'disk_bus': None,
                                      'device_type': None},
                                     {'boot_index': 0,
                                      'mount_device': u'/dev/vda',
                                      'connection_info': {},
                                      'disk_bus': u'virtio',
                                      'device_type': u'disk'}]}
        instance_ref.flavor.swap = 5
        image_meta = {}

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info=block_dev_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_configdrive(self):
        # A simple disk mapping setup, but with configdrive added
        # It's necessary to check if the architecture is power, because
        # power doesn't have support to ide, and so libvirt translate
        # all ide calls to scsi

        self.flags(force_config_drive=True)

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta)

        # Pick the first drive letter on the bus that is available
        # as the config drive. Delete the last device hardcode as
        # the config drive here.

        bus_ppc = ("scsi", "sda")
        bus_aarch64 = ("scsi", "sda")
        expect_bus = {"ppc": bus_ppc, "ppc64": bus_ppc,
                        "ppc64le": bus_ppc, "aarch64": bus_aarch64}

        bus, dev = expect_bus.get(blockinfo.libvirt_utils.get_arch({}),
                                  ("ide", "hda"))

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': bus, 'dev': dev, 'type': 'cdrom'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }

        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_cdrom_configdrive(self):
        # A simple disk mapping setup, with configdrive added as cdrom
        # It's necessary to check if the architecture is power, because
        # power doesn't have support to ide, and so libvirt translate
        # all ide calls to scsi

        self.flags(force_config_drive=True)
        self.flags(config_drive_format='iso9660')

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta)

        bus_ppc = ("scsi", "sda")
        bus_aarch64 = ("scsi", "sda")
        expect_bus = {"ppc": bus_ppc, "ppc64": bus_ppc,
                        "ppc64le": bus_ppc, "aarch64": bus_aarch64}

        bus, dev = expect_bus.get(blockinfo.libvirt_utils.get_arch({}),
                                  ("ide", "hda"))

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': bus, 'dev': dev, 'type': 'cdrom'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }

        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_disk_configdrive(self):
        # A simple disk mapping setup, with configdrive added as disk

        self.flags(force_config_drive=True)
        self.flags(config_drive_format='vfat')

        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_ephemeral(self):
        # A disk mapping with ephemeral devices
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.flavor.swap = 5
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'ephemerals': [
                {'device_type': 'disk', 'guest_format': 'ext4',
                 'device_name': '/dev/vdb', 'size': 10},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 10},
                {'device_type': 'floppy',
                 'device_name': '/dev/vdd', 'size': 10},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                          'type': 'disk', 'format': 'ext4'},
            'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
            'disk.eph2': {'bus': 'virtio', 'dev': 'vdd', 'type': 'floppy'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vde', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_custom_swap(self):
        # A disk mapping with a swap device at position vdb. This
        # should cause disk.local to be removed
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'swap': {'device_name': '/dev/vdb',
                     'swap_size': 10},
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_root(self):
        # A disk mapping with a blockdev replacing the default root
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 0,
                 'device_type': 'disk',
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_root_on_spawn(self):
        # A disk mapping with a blockdev initializing the default root
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = {}

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': None,
                 'mount_device': None,
                 'boot_index': 0,
                 'device_type': None,
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_eph(self):
        # A disk mapping with a blockdev replacing the ephemeral device
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'boot_index': -1,
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_many(self):
        # A disk mapping with a blockdev replacing all devices
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 0,
                 'disk_bus': 'scsi',
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'boot_index': -1,
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdc",
                 'boot_index': -1,
                 'device_type': 'cdrom',
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'scsi', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            '/dev/vdc': {'bus': 'virtio', 'dev': 'vdc', 'type': 'cdrom'},
            'root': {'bus': 'scsi', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_complex(self):
        # The strangest possible disk mapping setup
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'root_device_name': '/dev/vdf',
            'swap': {'device_name': '/dev/vdy',
                     'swap_size': 10},
            'ephemerals': [
                {'device_type': 'disk', 'guest_format': 'ext4',
                 'device_name': '/dev/vdb', 'size': 10},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 10},
                ],
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 1,
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             image_meta,
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vdf',
                     'type': 'disk', 'boot_index': '1'},
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '2'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                          'type': 'disk', 'format': 'ext4'},
            'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdy', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vdf',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_updates_original(self):
        instance_ref = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)

        block_device_info = {
            'root_device_name': '/dev/vda',
            'swap': {'device_name': '/dev/vdb',
                     'device_type': 'really_lame_type',
                     'swap_size': 10},
            'ephemerals': [{'disk_bus': 'no_such_bus',
                            'device_type': 'yeah_right',
                            'device_name': '/dev/vdc', 'size': 10}],
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': None,
                 'device_type': 'lawnmower',
                 'delete_on_termination': True}]
            }
        expected_swap = {'device_name': '/dev/vdb', 'disk_bus': 'virtio',
                         'device_type': 'disk', 'swap_size': 10}
        expected_ephemeral = {'disk_bus': 'virtio',
                              'device_type': 'disk',
                              'device_name': '/dev/vdc', 'size': 10}
        expected_bdm = {'connection_info': "fake",
                        'mount_device': '/dev/vdd',
                        'device_type': 'disk',
                        'disk_bus': 'virtio',
                        'delete_on_termination': True}

        with mock.patch.object(instance_ref, 'get_flavor') as get_flavor_mock:
            blockinfo.get_disk_mapping("kvm", instance_ref,
                                       "virtio", "ide",
                                       image_meta,
                                       block_device_info)
        # we should have gotten the swap info from block_device_info rather
        # than the flavor information on the instance
        self.assertFalse(get_flavor_mock.called)

        self.assertEqual(expected_swap, block_device_info['swap'])
        self.assertEqual(expected_ephemeral,
                         block_device_info['ephemerals'][0])
        self.assertEqual(expected_bdm,
                         block_device_info['block_device_mapping'][0])

    def test_get_disk_bus(self):
        instance = objects.Instance(**self.test_instance)
        expected = (
                (obj_fields.Architecture.X86_64, 'disk', 'virtio'),
                (obj_fields.Architecture.X86_64, 'cdrom', 'ide'),
                (obj_fields.Architecture.X86_64, 'floppy', 'fdc'),
                (obj_fields.Architecture.PPC, 'disk', 'virtio'),
                (obj_fields.Architecture.PPC, 'cdrom', 'scsi'),
                (obj_fields.Architecture.PPC64, 'disk', 'virtio'),
                (obj_fields.Architecture.PPC64, 'cdrom', 'scsi'),
                (obj_fields.Architecture.PPCLE, 'disk', 'virtio'),
                (obj_fields.Architecture.PPCLE, 'cdrom', 'scsi'),
                (obj_fields.Architecture.PPC64LE, 'disk', 'virtio'),
                (obj_fields.Architecture.PPC64LE, 'cdrom', 'scsi'),
                (obj_fields.Architecture.S390, 'disk', 'virtio'),
                (obj_fields.Architecture.S390, 'cdrom', 'scsi'),
                (obj_fields.Architecture.S390X, 'disk', 'virtio'),
                (obj_fields.Architecture.S390X, 'cdrom', 'scsi'),
                (obj_fields.Architecture.AARCH64, 'disk', 'virtio'),
                (obj_fields.Architecture.AARCH64, 'cdrom', 'scsi')
                )
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        for guestarch, dev, res in expected:
            with mock.patch.object(blockinfo.libvirt_utils,
                                   'get_arch',
                                   return_value=guestarch):
                bus = blockinfo.get_disk_bus_for_device_type(
                    instance, 'kvm', image_meta, dev)
                self.assertEqual(res, bus)

        expected = (
                ('kvm', 'scsi', None, 'disk', 'scsi'),
                ('kvm', None, 'scsi', 'cdrom', 'scsi'),
                ('kvm', 'usb', None, 'disk', 'usb'),
                ('parallels', 'scsi', None, 'disk', 'scsi'),
                ('parallels', None, None, 'disk', 'scsi'),
                ('parallels', None, 'ide', 'cdrom', 'ide'),
                ('parallels', None, None, 'cdrom', 'ide')
                )
        for hv, dbus, cbus, dev, res in expected:
            props = {}
            if dbus is not None:
                props['hw_disk_bus'] = dbus
            if cbus is not None:
                props['hw_cdrom_bus'] = cbus
            image_meta = objects.ImageMeta.from_dict(
                {'properties': props})
            bus = blockinfo.get_disk_bus_for_device_type(
                instance, hv, image_meta, device_type=dev)
            self.assertEqual(res, bus)

        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'hw_disk_bus': 'xen'}})
        self.assertRaises(exception.UnsupportedHardware,
                          blockinfo.get_disk_bus_for_device_type,
                          instance, 'kvm', image_meta)

    def test_get_disk_bus_with_osinfo(self):
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.osinfo.libosinfo',
            fakelibosinfo))
        instance = objects.Instance(**self.test_instance)
        image_meta = {'properties': {'os_name': 'fedora22'}}
        image_meta = objects.ImageMeta.from_dict(image_meta)
        bus = blockinfo.get_disk_bus_for_device_type(instance,
                                                     'kvm', image_meta)
        self.assertEqual('virtio', bus)

    def test_success_get_disk_bus_for_disk_dev(self):
        expected = (
                ('ide', ("kvm", "hda")),
                ('scsi', ("kvm", "sdf")),
                ('virtio', ("kvm", "vds")),
                ('fdc', ("kvm", "fdc")),
                ('uml', ("kvm", "ubd")),
                ('xen', ("xen", "sdf")),
                ('xen', ("xen", "xvdb"))
                )
        for res, args in expected:
            self.assertEqual(res, blockinfo.get_disk_bus_for_disk_dev(*args))

    def test_fail_get_disk_bus_for_disk_dev_unsupported_virt_type(self):
        instance = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        self.assertRaises(exception.UnsupportedVirtType,
                          blockinfo.get_disk_bus_for_device_type,
                          instance, 'kvm1', image_meta)

    def test_fail_get_disk_bus_for_disk_dev(self):
        self.assertRaises(exception.NovaException,
                blockinfo.get_disk_bus_for_disk_dev, 'inv', 'val')

    def test_get_config_drive_type_default(self):
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('cdrom', config_drive_type)

    def test_get_config_drive_type_cdrom(self):
        self.flags(config_drive_format='iso9660')
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('cdrom', config_drive_type)

    def test_get_config_drive_type_disk(self):
        self.flags(config_drive_format='vfat')
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('disk', config_drive_type)

    def test_get_info_from_bdm(self):
        instance = objects.Instance(**self.test_instance)
        bdms = [{'device_name': '/dev/vds', 'device_type': 'disk',
                 'disk_bus': 'usb', 'swap_size': 4},
                {'device_type': 'disk', 'guest_format': 'ext4',
                 'device_name': '/dev/vdb', 'size': 2},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 3},
                {'connection_info': "fake",
                 'mount_device': "/dev/sdr",
                 'disk_bus': 'lame_bus',
                 'device_type': 'cdrom',
                 'boot_index': 0,
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdo",
                 'disk_bus': 'scsi',
                 'boot_index': 1,
                 'device_type': 'lame_type',
                 'delete_on_termination': True},
                {'disk_bus': 'sata', 'guest_format': None,
                 'device_name': '/dev/sda', 'size': 3}]
        expected = [{'dev': 'vds', 'type': 'disk', 'bus': 'usb'},
                    {'dev': 'vdb', 'type': 'disk',
                     'bus': 'virtio', 'format': 'ext4'},
                    {'dev': 'vdc', 'type': 'disk', 'bus': 'ide'},
                    {'dev': 'sdr', 'type': 'cdrom',
                     'bus': 'scsi', 'boot_index': '1'},
                    {'dev': 'vdo', 'type': 'disk',
                     'bus': 'scsi', 'boot_index': '2'},
                    {'dev': 'sda', 'type': 'disk', 'bus': 'sata'}]

        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        for bdm, expected in zip(bdms, expected):
            self.assertEqual(expected,
                             blockinfo.get_info_from_bdm(instance,
                                                         'kvm',
                                                         image_meta,
                                                         bdm))

        # Test that passed bus and type are considered
        bdm = {'device_name': '/dev/vda'}
        expected = {'dev': 'vda', 'type': 'disk', 'bus': 'ide'}
        self.assertEqual(
            expected, blockinfo.get_info_from_bdm(instance,
                                                  'kvm',
                                                  image_meta,
                                                  bdm,
                                                  disk_bus='ide',
                                                  dev_type='disk'))

        # Test that lame bus values are defaulted properly
        bdm = {'disk_bus': 'lame_bus', 'device_type': 'cdrom'}
        with mock.patch.object(blockinfo,
                               'get_disk_bus_for_device_type',
                               return_value='ide') as get_bus:
            blockinfo.get_info_from_bdm(instance,
                                        'kvm',
                                        image_meta,
                                        bdm)
            get_bus.assert_called_once_with(instance, 'kvm',
                                            image_meta, 'cdrom')

        # Test that missing device is defaulted as expected
        bdm = {'disk_bus': 'ide', 'device_type': 'cdrom'}
        expected = {'dev': 'vdd', 'type': 'cdrom', 'bus': 'ide'}
        mapping = {'root': {'dev': 'vda'}}
        with mock.patch.object(blockinfo,
                               'find_disk_dev_for_disk_bus',
                               return_value='vdd') as find_dev:
            got = blockinfo.get_info_from_bdm(
                instance,
                'kvm',
                image_meta,
                bdm,
                mapping,
                assigned_devices=['vdb', 'vdc'])
            find_dev.assert_called_once_with(
                {'root': {'dev': 'vda'},
                 'vdb': {'dev': 'vdb'},
                 'vdc': {'dev': 'vdc'}}, 'ide')
            self.assertEqual(expected, got)

    def test_get_device_name(self):
        bdm_obj = objects.BlockDeviceMapping(self.context,
            **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 3, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vda',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake-volume-id-1',
                 'boot_index': 0}))
        self.assertEqual('/dev/vda', blockinfo.get_device_name(bdm_obj))

        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm_obj)
        self.assertEqual('/dev/vda', blockinfo.get_device_name(driver_bdm))

        bdm_obj.device_name = None
        self.assertIsNone(blockinfo.get_device_name(bdm_obj))

        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm_obj)
        self.assertIsNone(blockinfo.get_device_name(driver_bdm))

    @mock.patch('nova.virt.libvirt.blockinfo.find_disk_dev_for_disk_bus',
                return_value='vda')
    @mock.patch('nova.virt.libvirt.blockinfo.get_disk_bus_for_disk_dev',
                return_value='virtio')
    def test_get_root_info_no_bdm(self, mock_get_bus, mock_find_dev):
        instance = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        blockinfo.get_root_info(instance, 'kvm', image_meta, None,
                                'virtio', 'ide')
        mock_find_dev.assert_called_once_with({}, 'virtio')

        blockinfo.get_root_info(instance, 'kvm', image_meta, None,
                                'virtio', 'ide', root_device_name='/dev/vda')
        mock_get_bus.assert_called_once_with('kvm', '/dev/vda')

    @mock.patch('nova.virt.libvirt.blockinfo.find_disk_dev_for_disk_bus',
                return_value='vda')
    @mock.patch('nova.virt.libvirt.blockinfo.get_disk_bus_for_disk_dev',
                return_value='virtio')
    def test_get_root_info_no_bdm_empty_image_meta(self, mock_get_bus,
                                                   mock_find_dev):
        # The evacuate operation passes image_ref=None to the compute node for
        # rebuild which then defaults image_meta to {}, so we don't have any
        # attributes in the ImageMeta object passed to get_root_info and we
        # need to make sure we don't try lazy-loading anything.
        instance = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict({})
        blockinfo.get_root_info(instance, 'kvm', image_meta, None,
                                'virtio', 'ide')
        mock_find_dev.assert_called_once_with({}, 'virtio')

        blockinfo.get_root_info(instance, 'kvm', image_meta, None,
                                'virtio', 'ide', root_device_name='/dev/vda')
        mock_get_bus.assert_called_once_with('kvm', '/dev/vda')

    @mock.patch('nova.virt.libvirt.blockinfo.get_info_from_bdm')
    def test_get_root_info_bdm(self, mock_get_info):
        instance = objects.Instance(**self.test_instance)
        image_meta = objects.ImageMeta.from_dict(self.test_image_meta)
        root_bdm = {'mount_device': '/dev/vda',
                    'disk_bus': 'scsi',
                    'device_type': 'disk'}
        # No root_device_name
        blockinfo.get_root_info(instance, 'kvm', image_meta, root_bdm,
                                'virtio', 'ide')
        mock_get_info.assert_called_once_with(instance, 'kvm', image_meta,
                                              root_bdm, {}, 'virtio')
        mock_get_info.reset_mock()
        # Both device names
        blockinfo.get_root_info(instance, 'kvm', image_meta, root_bdm,
                                'virtio', 'ide', root_device_name='sda')
        mock_get_info.assert_called_once_with(instance, 'kvm', image_meta,
                                              root_bdm, {}, 'virtio')
        mock_get_info.reset_mock()
        # Missing device names
        del root_bdm['mount_device']
        blockinfo.get_root_info(instance, 'kvm', image_meta, root_bdm,
                                'virtio', 'ide', root_device_name='sda')
        mock_get_info.assert_called_once_with(instance, 'kvm',
                                              image_meta,
                                              {'device_name': 'sda',
                                               'disk_bus': 'scsi',
                                               'device_type': 'disk'},
                                              {}, 'virtio')
        mock_get_info.reset_mock()
        # xen with incompatible root_device_name/disk_bus combination
        root_bdm['disk_bus'] = 'xen'
        blockinfo.get_root_info(instance, 'xen', image_meta, root_bdm,
                                'xen', 'ide', root_device_name='sda')
        mock_get_info.assert_called_once_with(instance, 'xen', image_meta,
                                              {'device_name': 'xvda',
                                               'disk_bus': 'xen',
                                               'device_type': 'disk'},
                                              {}, 'xen')

    def test_get_boot_order_simple(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))

    def test_get_boot_order_complex(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
                'disk': {'bus': 'virtio', 'dev': 'vdf',
                         'type': 'disk', 'boot_index': '1'},
                '/dev/hda': {'bus': 'ide', 'dev': 'hda',
                             'type': 'cdrom', 'boot_index': '3'},
                '/dev/fda': {'bus': 'fdc', 'dev': 'fda',
                             'type': 'floppy', 'boot_index': '2'},
                'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                              'type': 'disk', 'format': 'ext4'},
                'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
                'disk.swap': {'bus': 'virtio', 'dev': 'vdy', 'type': 'disk'},
                'root': {'bus': 'virtio', 'dev': 'vdf',
                         'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd', 'fd', 'cdrom']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))

    def test_get_boot_order_overlapping(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
            '/dev/vda': {'bus': 'scsi', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb',
                         'type': 'disk', 'boot_index': '2'},
            '/dev/vdc': {'bus': 'virtio', 'dev': 'vdc',
                         'type': 'cdrom', 'boot_index': '3'},
            'root': {'bus': 'scsi', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd', 'cdrom']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))


class DefaultDeviceNamesTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DefaultDeviceNamesTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.instance = objects.Instance(
                uuid='32dfcb37-5af1-552b-357c-be8c3aa38310',
                memory_kb='1024000',
                basepath='/some/path',
                bridge_name='br100',
                vcpus=2,
                project_id='fake',
                bridge='br101',
                image_ref='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                root_gb=10,
                ephemeral_gb=20,
                instance_type_id=2,
                config_drive=False,
                root_device_name = '/dev/vda',
                system_metadata={})
        self.image_meta = objects.ImageMeta(
            disk_format='raw',
            properties=objects.ImageMetaProps())

        self.virt_type = 'kvm'
        self.flavor = objects.Flavor(swap=4)
        self.patchers = []
        self.patchers.append(mock.patch.object(self.instance, 'get_flavor',
                                               return_value=self.flavor))
        self.patchers.append(mock.patch(
                'nova.objects.block_device.BlockDeviceMapping.save'))
        for patcher in self.patchers:
            patcher.start()

        self.ephemerals = [objects.BlockDeviceMapping(
            self.context, **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vdb',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'delete_on_termination': True,
                 'guest_format': None,
                 'volume_size': 1,
                 'boot_index': -1}))]

        self.swap = [objects.BlockDeviceMapping(
            self.context, **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 2, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vdc',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'delete_on_termination': True,
                 'guest_format': 'swap',
                 'volume_size': 1,
                 'boot_index': -1}))]

        self.block_device_mapping = [
            objects.BlockDeviceMapping(self.context,
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 3, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vda',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'volume_id': 'fake-volume-id-1',
                 'boot_index': 0})),
            objects.BlockDeviceMapping(self.context,
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 4, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vdd',
                 'source_type': 'snapshot',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'destination_type': 'volume',
                 'snapshot_id': 'fake-snapshot-id-1',
                 'boot_index': -1})),
            objects.BlockDeviceMapping(self.context,
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 5, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/vde',
                 'source_type': 'blank',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'destination_type': 'volume',
                 'boot_index': -1}))]

    def tearDown(self):
        super(DefaultDeviceNamesTestCase, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    def _test_default_device_names(self, eph, swap, bdm):
        bdms = eph + swap + bdm
        bdi = driver.get_block_device_info(self.instance, bdms)
        blockinfo.default_device_names(self.virt_type,
                                       self.context,
                                       self.instance,
                                       bdi,
                                       self.image_meta)

    def test_only_block_device_mapping(self):
        # Test no-op
        original_bdm = copy.deepcopy(self.block_device_mapping)
        self._test_default_device_names([], [], self.block_device_mapping)
        for original, defaulted in zip(
                original_bdm, self.block_device_mapping):
            self.assertEqual(original.device_name, defaulted.device_name)

        # Assert it defaults the missing one as expected
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names([], [], self.block_device_mapping)
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vde',
                         self.block_device_mapping[2]['device_name'])

    def test_with_ephemerals(self):
        # Test ephemeral gets assigned
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])

        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vde',
                         self.block_device_mapping[2]['device_name'])

    def test_with_swap(self):
        # Test swap only
        self.swap[0]['device_name'] = None
        self._test_default_device_names([], self.swap, [])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test swap and block_device_mapping
        self.swap[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names([], self.swap,
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vde',
                         self.block_device_mapping[2]['device_name'])

    def test_all_together(self):
        # Test swap missing
        self.swap[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test swap and eph missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test all missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vde',
                         self.block_device_mapping[2]['device_name'])
