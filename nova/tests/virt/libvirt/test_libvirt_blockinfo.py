# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from nova import block_device
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova import test
import nova.tests.image.fake
from nova.virt.libvirt import blockinfo


class LibvirtBlockInfoTest(test.TestCase):

    def setUp(self):
        super(LibvirtBlockInfoTest, self).setUp()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.get_admin_context()
        instance_type = db.instance_type_get(self.context, 2)
        sys_meta = flavors.save_flavor_info({}, instance_type)
        nova.tests.image.fake.stub_out_image_service(self.stubs)
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
                'system_metadata': sys_meta}

    def test_volume_in_mapping(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'num': 0,
                       'virtual_name': 'ephemeral0',
                       'device_name': '/dev/sdc1',
                       'size': 1},
                      {'num': 2,
                       'virtual_name': 'ephemeral2',
                       'device_name': '/dev/sdd',
                       'size': 1}]
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
            self.assertEquals(
                block_device.volume_in_mapping(device_name,
                                               block_device_info),
                true_or_false)

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
        self.assertEqual(dev, 'sdb')

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'scsi',
                                                   last_device=True)
        self.assertEqual(dev, 'sdz')

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'virtio')
        self.assertEqual(dev, 'vda')

    def test_get_next_disk_dev(self):
        mapping = {}
        mapping['disk.local'] = blockinfo.get_next_disk_info(mapping,
                                                             'virtio')
        self.assertEqual(mapping['disk.local'],
                         {'dev': 'vda', 'bus': 'virtio', 'type': 'disk'})

        mapping['disk.swap'] = blockinfo.get_next_disk_info(mapping,
                                                            'virtio')
        self.assertEqual(mapping['disk.swap'],
                         {'dev': 'vdb', 'bus': 'virtio', 'type': 'disk'})

        mapping['disk.config'] = blockinfo.get_next_disk_info(mapping,
                                                              'ide',
                                                              'cdrom',
                                                              True)
        self.assertEqual(mapping['disk.config'],
                         {'dev': 'hdd', 'bus': 'ide', 'type': 'cdrom'})

    def test_get_disk_mapping_simple(self):
        # The simplest possible disk mapping setup, all defaults

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_simple_rootdev(self):
        # A simple disk mapping setup, but with custom root device name

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        block_device_info = {
            'root_device_name': '/dev/sda'
            }

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'scsi', 'dev': 'sda', 'type': 'disk'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'scsi', 'dev': 'sda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_rescue(self):
        # A simple disk mapping setup, but in rescue mode

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             rescue=True)

        expect = {
            'disk.rescue': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_lxc(self):
        # A simple disk mapping setup, but for lxc

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("lxc", instance_ref,
                                             "lxc", "lxc",
                                             None)
        expect = {
            'disk': {'bus': 'lxc', 'dev': None, 'type': 'disk'},
            'root': {'bus': 'lxc', 'dev': None, 'type': 'disk'}
        }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_simple_iso(self):
        # A simple disk mapping setup, but with a ISO for root device

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        image_meta = {'disk_format': 'iso'}

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             None,
                                             image_meta)

        expect = {
            'disk': {'bus': 'ide', 'dev': 'hda', 'type': 'cdrom'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'ide', 'dev': 'hda', 'type': 'cdrom'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_simple_swap(self):
        # A simple disk mapping setup, but with a swap device added

        user_context = context.RequestContext(self.user_id, self.project_id)
        self.test_instance['system_metadata']['instance_type_swap'] = 5
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_simple_configdrive(self):
        # A simple disk mapping setup, but with configdrive added

        self.flags(force_config_drive=True)

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': 'virtio', 'dev': 'vdz', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_ephemeral(self):
        # A disk mapping with ephemeral devices
        user_context = context.RequestContext(self.user_id, self.project_id)
        self.test_instance['system_metadata']['instance_type_swap'] = 5
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'ephemerals': [
                {'num': 0, 'virtual_name': 'ephemeral0',
                 'device_name': '/dev/vdb', 'size': 10},
                {'num': 1, 'virtual_name': 'ephemeral1',
                 'device_name': '/dev/vdc', 'size': 10},
                {'num': 2, 'virtual_name': 'ephemeral2',
                 'device_name': '/dev/vdd', 'size': 10},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.eph1': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'disk.eph2': {'bus': 'virtio', 'dev': 'vdd', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vde', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_custom_swap(self):
        # A disk mapping with a swap device at position vdb. This
        # should cause disk.local to be removed
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'swap': {'device_name': '/dev/vdb',
                     'swap_size': 10},
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_blockdev_root(self):
        # A disk mapping with a blockdev replacing the default root
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_blockdev_eph(self):
        # A disk mapping with a blockdev replacing the ephemeral device
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_blockdev_many(self):
        # A disk mapping with a blockdev replacing all devices
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdc",
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            '/dev/vdc': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_mapping_complex(self):
        # The strangest possible disk mapping setup
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'root_device_name': '/dev/vdf',
            'swap': {'device_name': '/dev/vdy',
                     'swap_size': 10},
            'ephemerals': [
                {'num': 0, 'virtual_name': 'ephemeral0',
                 'device_name': '/dev/vdb', 'size': 10},
                {'num': 1, 'virtual_name': 'ephemeral1',
                 'device_name': '/dev/vdc', 'size': 10},
                ],
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vdf', 'type': 'disk'},
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.eph1': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdy', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vdf', 'type': 'disk'}
            }
        self.assertEqual(mapping, expect)

    def test_get_disk_bus(self):
        bus = blockinfo.get_disk_bus_for_device_type('kvm')
        self.assertEqual(bus, 'virtio')

        bus = blockinfo.get_disk_bus_for_device_type('kvm',
                                                     device_type='cdrom')
        self.assertEqual(bus, 'ide')

        image_meta = {'properties': {'hw_disk_bus': 'scsi'}}
        bus = blockinfo.get_disk_bus_for_device_type('kvm',
                                                     image_meta)
        self.assertEqual(bus, 'scsi')

        image_meta = {'properties': {'hw_disk_bus': 'usb',
                                     'hw_cdrom_bus': 'scsi'}}
        bus = blockinfo.get_disk_bus_for_device_type('kvm',
                                                     image_meta,
                                                     device_type='cdrom')
        self.assertEqual(bus, 'scsi')

        bus = blockinfo.get_disk_bus_for_device_type('kvm',
                                                     image_meta)
        self.assertEqual(bus, 'usb')

        image_meta = {'properties': {'hw_disk_bus': 'xen'}}
        self.assertRaises(exception.UnsupportedHardware,
                          blockinfo.get_disk_bus_for_device_type,
                          'kvm',
                          image_meta)
