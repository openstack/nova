# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for metadata service."""

import copy
import hashlib
import hmac
import os
import re

try:  # python 2
    import pickle
except ImportError:  # python 3
    import cPickle as pickle

from keystoneauth1 import exceptions as ks_exceptions
from keystoneauth1 import session
import mock
from oslo_config import cfg
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils.fixture import uuidsentinel as uuids
import requests
import six
import webob

from nova.api.metadata import base
from nova.api.metadata import handler
from nova.api.metadata import password
from nova.api.metadata import vendordata_dynamic
from nova import block_device
from nova import context
from nova import exception
from nova.network import model as network_model
from nova.network import neutron as neutronapi
from nova import objects
from nova.objects import instance_numa as numa
from nova.objects import virt_device_metadata as metadata_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_network
from nova.tests.unit import fake_requests
from nova import utils
from nova.virt import netutils

CONF = cfg.CONF

USER_DATA_STRING = (b"This is an encoded string")
ENCODE_USER_DATA_STRING = base64.encode_as_text(USER_DATA_STRING)
FAKE_SEED = '7qtD24mpMR2'


def fake_inst_obj(context):
    inst = objects.Instance(
        context=context,
        id=1,
        user_id='fake_user',
        uuid='b65cee2f-8c69-4aeb-be2f-f79742548fc2',
        project_id='test',
        key_name="key",
        key_data="ssh-rsa AAAAB3Nzai....N3NtHw== someuser@somehost",
        host='test',
        launch_index=1,
        reservation_id='r-xxxxxxxx',
        user_data=ENCODE_USER_DATA_STRING,
        image_ref=uuids.image_ref,
        kernel_id=None,
        ramdisk_id=None,
        vcpus=1,
        fixed_ips=[],
        root_device_name='/dev/sda1',
        hostname='test',
        display_name='my_displayname',
        metadata={},
        device_metadata=fake_metadata_objects(),
        default_ephemeral_device=None,
        default_swap_device=None,
        system_metadata={},
        security_groups=objects.SecurityGroupList(),
        availability_zone='fake-az')
    inst.keypairs = objects.KeyPairList(objects=[
            fake_keypair_obj(inst.key_name, inst.key_data)])

    nwinfo = network_model.NetworkInfo([])
    inst.info_cache = objects.InstanceInfoCache(context=context,
                                                instance_uuid=inst.uuid,
                                                network_info=nwinfo)
    inst.flavor = objects.Flavor.get_by_name(context, 'm1.small')
    return inst


def fake_keypair_obj(name, data):
    return objects.KeyPair(name=name,
                           type='fake_type',
                           public_key=data)


def fake_InstanceMetadata(testcase, inst_data, address=None,
                          sgroups=None, content=None, extra_md=None,
                          network_info=None, network_metadata=None):
    content = content or []
    extra_md = extra_md or {}
    if sgroups is None:
        sgroups = [{'name': 'default'}]

    fakes.stub_out_secgroup_api(testcase, security_groups=sgroups)
    return base.InstanceMetadata(inst_data, address=address,
        content=content, extra_md=extra_md,
        network_info=network_info, network_metadata=network_metadata)


def fake_request(testcase, mdinst, relpath, address="127.0.0.1",
                 fake_get_metadata=None, headers=None,
                 fake_get_metadata_by_instance_id=None, app=None):

    def get_metadata_by_remote_address(self, address):
        return mdinst

    if app is None:
        app = handler.MetadataRequestHandler()

    if fake_get_metadata is None:
        fake_get_metadata = get_metadata_by_remote_address

    if testcase:
        testcase.stub_out(
            '%(module)s.%(class)s.get_metadata_by_remote_address' %
            {'module': app.__module__,
             'class': app.__class__.__name__},
            fake_get_metadata)

        if fake_get_metadata_by_instance_id:
            testcase.stub_out(
                '%(module)s.%(class)s.get_metadata_by_instance_id' %
                {'module': app.__module__,
                 'class': app.__class__.__name__},
                fake_get_metadata_by_instance_id)

    request = webob.Request.blank(relpath)
    request.remote_addr = address

    if headers is not None:
        request.headers.update(headers)

    response = request.get_response(app)
    return response


def fake_metadata_objects():
    nic_obj = metadata_obj.NetworkInterfaceMetadata(
        bus=metadata_obj.PCIDeviceBus(address='0000:00:01.0'),
        mac='00:00:00:00:00:00',
        tags=['foo']
    )
    nic_vf_trusted_obj = metadata_obj.NetworkInterfaceMetadata(
        bus=metadata_obj.PCIDeviceBus(address='0000:00:02.0'),
        mac='00:11:22:33:44:55',
        vf_trusted=True,
        tags=['trusted']
    )
    nic_vlans_obj = metadata_obj.NetworkInterfaceMetadata(
        bus=metadata_obj.PCIDeviceBus(address='0000:80:01.0'),
        mac='e3:a0:d0:12:c5:10',
        vlan=1000,
    )
    ide_disk_obj = metadata_obj.DiskMetadata(
        bus=metadata_obj.IDEDeviceBus(address='0:0'),
        serial='disk-vol-2352423',
        path='/dev/sda',
        tags=['baz'],
    )
    scsi_disk_obj = metadata_obj.DiskMetadata(
        bus=metadata_obj.SCSIDeviceBus(address='05c8:021e:04a7:011b'),
        serial='disk-vol-2352423',
        path='/dev/sda',
        tags=['baz'],
    )
    usb_disk_obj = metadata_obj.DiskMetadata(
        bus=metadata_obj.USBDeviceBus(address='05c8:021e'),
        serial='disk-vol-2352423',
        path='/dev/sda',
        tags=['baz'],
    )
    fake_device_obj = metadata_obj.DeviceMetadata()
    device_with_fake_bus_obj = metadata_obj.NetworkInterfaceMetadata(
        bus=metadata_obj.DeviceBus(),
        mac='00:00:00:00:00:00',
        tags=['foo']
    )
    mdlist = metadata_obj.InstanceDeviceMetadata(
        instance_uuid='b65cee2f-8c69-4aeb-be2f-f79742548fc2',
        devices=[nic_obj, ide_disk_obj, scsi_disk_obj, usb_disk_obj,
                 fake_device_obj, device_with_fake_bus_obj, nic_vlans_obj,
                 nic_vf_trusted_obj])
    return mdlist


def fake_metadata_dicts(include_vlan=False, include_vf_trusted=False):
    nic_meta = {
        'type': 'nic',
        'bus': 'pci',
        'address': '0000:00:01.0',
        'mac': '00:00:00:00:00:00',
        'tags': ['foo'],
    }
    vlan_nic_meta = {
        'type': 'nic',
        'bus': 'pci',
        'address': '0000:80:01.0',
        'mac': 'e3:a0:d0:12:c5:10',
        'vlan': 1000,
    }
    vf_trusted_nic_meta = {
        'type': 'nic',
        'bus': 'pci',
        'address': '0000:00:02.0',
        'mac': '00:11:22:33:44:55',
        'tags': ['trusted'],
    }
    ide_disk_meta = {
        'type': 'disk',
        'bus': 'ide',
        'address': '0:0',
        'serial': 'disk-vol-2352423',
        'path': '/dev/sda',
        'tags': ['baz'],
    }

    scsi_disk_meta = copy.copy(ide_disk_meta)
    scsi_disk_meta['bus'] = 'scsi'
    scsi_disk_meta['address'] = '05c8:021e:04a7:011b'

    usb_disk_meta = copy.copy(ide_disk_meta)
    usb_disk_meta['bus'] = 'usb'
    usb_disk_meta['address'] = '05c8:021e'

    dicts = [nic_meta, ide_disk_meta, scsi_disk_meta, usb_disk_meta,
             vf_trusted_nic_meta]
    if include_vlan:
        # NOTE(artom) Yeah, the order is important.
        dicts.insert(len(dicts) - 1, vlan_nic_meta)
    if include_vf_trusted:
        nic_meta['vf_trusted'] = False
        vlan_nic_meta['vf_trusted'] = False
        vf_trusted_nic_meta['vf_trusted'] = True
    return dicts


class MetadataTestCase(test.TestCase):
    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.keypair = fake_keypair_obj(self.instance.key_name,
                                        self.instance.key_data)
        fakes.stub_out_secgroup_api(self)

    def test_can_pickle_metadata(self):
        # Make sure that InstanceMetadata is possible to pickle. This is
        # required for memcache backend to work correctly.
        md = fake_InstanceMetadata(self, self.instance.obj_clone())
        pickle.dumps(md, protocol=0)

    def test_user_data(self):
        inst = self.instance.obj_clone()
        inst['user_data'] = base64.encode_as_text("happy")
        md = fake_InstanceMetadata(self, inst)
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04')['user-data'], b"happy")

    def test_no_user_data(self):
        inst = self.instance.obj_clone()
        inst.user_data = None
        md = fake_InstanceMetadata(self, inst)
        obj = object()
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04').get('user-data', obj),
            obj)

    def test_security_groups(self):
        inst = self.instance.obj_clone()
        sgroups = [{'name': name} for name in ('default', 'other')]
        expected = ['default', 'other']

        md = fake_InstanceMetadata(self, inst, sgroups=sgroups)
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['security-groups'], expected)

    def test_local_hostname(self):
        self.flags(dhcp_domain=None, group='api')
        md = fake_InstanceMetadata(self, self.instance.obj_clone())
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-hostname'],
            self.instance['hostname'])

    def test_local_hostname_fqdn(self):
        self.flags(dhcp_domain='fakedomain', group='api')
        md = fake_InstanceMetadata(self, self.instance.obj_clone())
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual('%s.fakedomain' % self.instance['hostname'],
                         data['meta-data']['local-hostname'])

    def test_format_instance_mapping(self):
        # Make sure that _format_instance_mappings works.
        instance_ref0 = objects.Instance(**{'id': 0,
                         'uuid': 'e5fe5518-0288-4fa3-b0c4-c79764101b85',
                         'root_device_name': None,
                         'default_ephemeral_device': None,
                         'default_swap_device': None,
                         'context': self.context})
        instance_ref1 = objects.Instance(**{'id': 0,
                         'uuid': 'b65cee2f-8c69-4aeb-be2f-f79742548fc2',
                         'root_device_name': '/dev/sda1',
                         'default_ephemeral_device': None,
                         'default_swap_device': None,
                         'context': self.context})

        def fake_bdm_get(ctxt, uuid):
            return [fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': 87654321,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': None,
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'})]

        self.stub_out('nova.db.api.block_device_mapping_get_all_by_instance',
                      fake_bdm_get)

        expected = {'ami': 'sda1',
                    'root': '/dev/sda1',
                    'ephemeral0': '/dev/sdb',
                    'swap': '/dev/sdc',
                    'ebs0': '/dev/sdh'}

        self.assertEqual(
            base._format_instance_mapping(instance_ref0),
            block_device._DEFAULT_MAPPINGS)
        self.assertEqual(
            base._format_instance_mapping(instance_ref1),
            expected)

    def test_pubkey(self):
        md = fake_InstanceMetadata(self, self.instance.obj_clone())
        pubkey_ent = md.lookup("/2009-04-04/meta-data/public-keys")

        self.assertEqual(base.ec2_md_print(pubkey_ent),
            "0=%s" % self.instance['key_name'])
        self.assertEqual(base.ec2_md_print(pubkey_ent['0']['openssh-key']),
            self.instance['key_data'])

    def test_image_type_ramdisk(self):
        inst = self.instance.obj_clone()
        inst['ramdisk_id'] = uuids.ramdisk_id
        md = fake_InstanceMetadata(self, inst)
        data = md.lookup("/latest/meta-data/ramdisk-id")

        self.assertIsNotNone(data)
        self.assertTrue(re.match('ari-[0-9a-f]{8}', data))

    def test_image_type_kernel(self):
        inst = self.instance.obj_clone()
        inst['kernel_id'] = uuids.kernel_id
        md = fake_InstanceMetadata(self, inst)
        data = md.lookup("/2009-04-04/meta-data/kernel-id")

        self.assertTrue(re.match('aki-[0-9a-f]{8}', data))

        self.assertEqual(
            md.lookup("/ec2/2009-04-04/meta-data/kernel-id"), data)

    def test_image_type_no_kernel_raises(self):
        inst = self.instance.obj_clone()
        md = fake_InstanceMetadata(self, inst)
        self.assertRaises(base.InvalidMetadataPath,
            md.lookup, "/2009-04-04/meta-data/kernel-id")

    def test_instance_is_sanitized(self):
        inst = self.instance.obj_clone()
        # The instance already has some fake device_metadata stored on it,
        # and we want to test to see it gets lazy-loaded, so save off the
        # original attribute value and delete the attribute from the instance,
        # then we can assert it gets loaded up later.
        original_device_meta = inst.device_metadata
        delattr(inst, 'device_metadata')

        def fake_obj_load_attr(attrname):
            if attrname == 'device_metadata':
                inst.device_metadata = original_device_meta
            elif attrname == 'ec2_ids':
                inst.ec2_ids = objects.EC2Ids()
            elif attrname == 'numa_topology':
                inst.numa_topology = None
            else:
                self.fail('Unexpected instance lazy-load: %s' % attrname)

        inst._will_not_pass = True
        with mock.patch.object(
                inst, 'obj_load_attr',
                side_effect=fake_obj_load_attr) as mock_obj_load_attr:
            md = fake_InstanceMetadata(self, inst)
        self.assertFalse(hasattr(md.instance, '_will_not_pass'))
        self.assertEqual(3, mock_obj_load_attr.call_count)
        mock_obj_load_attr.assert_has_calls(
            [mock.call('device_metadata'),
             mock.call('ec2_ids'),
             mock.call('numa_topology')],
            any_order=True)
        self.assertIs(original_device_meta, inst.device_metadata)

    def test_check_version(self):
        inst = self.instance.obj_clone()
        md = fake_InstanceMetadata(self, inst)

        self.assertTrue(md._check_version('1.0', '2009-04-04'))
        self.assertFalse(md._check_version('2009-04-04', '1.0'))

        self.assertFalse(md._check_version('2009-04-04', '2008-09-01'))
        self.assertTrue(md._check_version('2008-09-01', '2009-04-04'))

        self.assertTrue(md._check_version('2009-04-04', '2009-04-04'))

    @mock.patch('nova.virt.netutils.get_injected_network_template')
    def test_InstanceMetadata_uses_passed_network_info(self, mock_get):
        network_info = []
        mock_get.return_value = False

        base.InstanceMetadata(fake_inst_obj(self.context),
                              network_info=network_info)
        mock_get.assert_called_once_with(network_info)

    @mock.patch.object(netutils, "get_network_metadata", autospec=True)
    def test_InstanceMetadata_gets_network_metadata(self, mock_netutils):
        network_data = {'links': [], 'networks': [], 'services': []}
        mock_netutils.return_value = network_data

        md = base.InstanceMetadata(fake_inst_obj(self.context))
        self.assertEqual(network_data, md.network_metadata)

    def test_InstanceMetadata_invoke_metadata_for_config_drive(self):
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        inst_md = base.InstanceMetadata(inst)
        expected_paths = [
            'ec2/2009-04-04/user-data',
            'ec2/2009-04-04/meta-data.json',
            'ec2/latest/user-data',
            'ec2/latest/meta-data.json',
            'openstack/2012-08-10/meta_data.json',
            'openstack/2012-08-10/user_data',
            'openstack/2013-04-04/meta_data.json',
            'openstack/2013-04-04/user_data',
            'openstack/2013-10-17/meta_data.json',
            'openstack/2013-10-17/user_data',
            'openstack/2013-10-17/vendor_data.json',
            'openstack/2015-10-15/meta_data.json',
            'openstack/2015-10-15/user_data',
            'openstack/2015-10-15/vendor_data.json',
            'openstack/2015-10-15/network_data.json',
            'openstack/2016-06-30/meta_data.json',
            'openstack/2016-06-30/user_data',
            'openstack/2016-06-30/vendor_data.json',
            'openstack/2016-06-30/network_data.json',
            'openstack/2016-10-06/meta_data.json',
            'openstack/2016-10-06/user_data',
            'openstack/2016-10-06/vendor_data.json',
            'openstack/2016-10-06/network_data.json',
            'openstack/2016-10-06/vendor_data2.json',
            'openstack/2017-02-22/meta_data.json',
            'openstack/2017-02-22/user_data',
            'openstack/2017-02-22/vendor_data.json',
            'openstack/2017-02-22/network_data.json',
            'openstack/2017-02-22/vendor_data2.json',
            'openstack/2018-08-27/meta_data.json',
            'openstack/2018-08-27/user_data',
            'openstack/2018-08-27/vendor_data.json',
            'openstack/2018-08-27/network_data.json',
            'openstack/2018-08-27/vendor_data2.json',
            'openstack/2020-10-14/meta_data.json',
            'openstack/2020-10-14/user_data',
            'openstack/2020-10-14/vendor_data.json',
            'openstack/2020-10-14/network_data.json',
            'openstack/2020-10-14/vendor_data2.json',
            'openstack/latest/meta_data.json',
            'openstack/latest/user_data',
            'openstack/latest/vendor_data.json',
            'openstack/latest/network_data.json',
            'openstack/latest/vendor_data2.json',
        ]
        actual_paths = []
        for (path, value) in inst_md.metadata_for_config_drive():
            actual_paths.append(path)
            self.assertIsNotNone(path)
        self.assertEqual(expected_paths, actual_paths)

    @mock.patch('nova.virt.netutils.get_injected_network_template')
    def test_InstanceMetadata_queries_network_API_when_needed(self, mock_get):
        network_info_from_api = []

        mock_get.return_value = False
        base.InstanceMetadata(fake_inst_obj(self.context))
        mock_get.assert_called_once_with(network_info_from_api)

    def test_local_ipv4(self):
        nw_info = fake_network.fake_get_instance_nw_info(self)
        expected_local = "192.168.1.100"
        md = fake_InstanceMetadata(self, self.instance,
                                   network_info=nw_info, address="fake")
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(expected_local, data['meta-data']['local-ipv4'])

    def test_local_ipv4_from_nw_info(self):
        nw_info = fake_network.fake_get_instance_nw_info(self)
        expected_local = "192.168.1.100"
        md = fake_InstanceMetadata(self, self.instance,
                                   network_info=nw_info)
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-ipv4'], expected_local)

    def test_local_ipv4_from_address(self):
        expected_local = "fake"
        md = fake_InstanceMetadata(self, self.instance,
                                   network_info=[], address="fake")
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-ipv4'], expected_local)

    @mock.patch('oslo_serialization.base64.encode_as_text',
                return_value=FAKE_SEED)
    @mock.patch.object(jsonutils, 'dump_as_bytes')
    def _test_as_json_with_options(self, mock_json_dump_as_bytes,
                          mock_base64,
                          os_version=base.GRIZZLY):
        instance = self.instance
        keypair = self.keypair
        md = fake_InstanceMetadata(self, instance)

        expected_metadata = {
            'uuid': md.uuid,
            'hostname': md._get_hostname(),
            'name': instance.display_name,
            'launch_index': instance.launch_index,
            'availability_zone': md.availability_zone,
        }
        if md.launch_metadata:
            expected_metadata['meta'] = md.launch_metadata
        if md.files:
            expected_metadata['files'] = md.files
        if md.extra_md:
            expected_metadata['extra_md'] = md.extra_md
        if md.network_config:
            expected_metadata['network_config'] = md.network_config
        if instance.key_name:
            expected_metadata['public_keys'] = {
                keypair.name: keypair.public_key
            }
            expected_metadata['keys'] = [{'type': keypair.type,
                                          'data': keypair.public_key,
                                          'name': keypair.name}]
        if md._check_os_version(base.GRIZZLY, os_version):
            expected_metadata['random_seed'] = FAKE_SEED
        if md._check_os_version(base.LIBERTY, os_version):
            expected_metadata['project_id'] = instance.project_id
        if md._check_os_version(base.NEWTON_ONE, os_version):
            expose_vlan = md._check_os_version(base.OCATA, os_version)
            expected_metadata['devices'] = fake_metadata_dicts(expose_vlan)
        if md._check_os_version(base.OCATA, os_version):
            expose_trusted = md._check_os_version(base.ROCKY, os_version)
            expected_metadata['devices'] = fake_metadata_dicts(
                True, expose_trusted)
        if md._check_os_version(base.VICTORIA, os_version):
            expected_metadata['dedicated_cpus'] = []
        md._metadata_as_json(os_version, 'non useless path parameter')
        self.assertEqual(md.md_mimetype, base.MIME_TYPE_APPLICATION_JSON)
        mock_json_dump_as_bytes.assert_called_once_with(expected_metadata)

    def test_as_json(self):
        for os_version in base.OPENSTACK_VERSIONS:
            self._test_as_json_with_options(os_version=os_version)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_metadata_as_json_deleted_keypair(self, mock_inst_get_by_uuid):
        """Tests that we handle missing instance keypairs.
        """
        instance = self.instance.obj_clone()
        # we want to make sure that key_name is set but not keypairs so it has
        # to be lazy-loaded from the database
        delattr(instance, 'keypairs')
        mock_inst_get_by_uuid.return_value = instance
        md = fake_InstanceMetadata(self, instance)
        meta = md._metadata_as_json(base.OPENSTACK_VERSIONS[-1], path=None)
        meta = jsonutils.loads(meta)
        self.assertNotIn('keys', meta)
        self.assertNotIn('public_keys', meta)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_metadata_as_json_numatopology(self, mock_inst_get_by_uuid):
        """Ensure instance dedicated CPUs is properly listed."""
        fake_topo = numa.InstanceNUMATopology(cells=[
            numa.InstanceNUMACell(id=0, memory=1024, pagesize=4,
                                  cpuset=set([2]), pcpuset=set([0, 1])),
            numa.InstanceNUMACell(id=1, memory=2048, pagesize=4,
                                  cpuset=set([5]), pcpuset=set([3, 4])),
        ])
        instance = self.instance.obj_clone()

        mock_inst_get_by_uuid.return_value = instance
        md = fake_InstanceMetadata(self, instance)
        meta = md._metadata_as_json(base.OPENSTACK_VERSIONS[-1], path=None)
        meta = jsonutils.loads(meta)
        self.assertEqual([], meta['dedicated_cpus'])

        instance.numa_topology = fake_topo
        mock_inst_get_by_uuid.return_value = instance
        md = fake_InstanceMetadata(self, instance)
        meta = md._metadata_as_json(base.OPENSTACK_VERSIONS[-1], path=None)
        meta = jsonutils.loads(meta)
        self.assertEqual([0, 1, 3, 4], meta['dedicated_cpus'])


class OpenStackMetadataTestCase(test.TestCase):
    def setUp(self):
        super(OpenStackMetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)

    def test_empty_device_metadata(self):
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        inst.device_metadata = None
        mdinst = fake_InstanceMetadata(self, inst)
        mdjson = mdinst.lookup("/openstack/latest/meta_data.json")
        mddict = jsonutils.loads(mdjson)
        self.assertEqual([], mddict['devices'])

    def test_device_metadata(self):
        # Because we handle a list of devices, we have only one test and in it
        # include the various devices types that we have to test, as well as a
        # couple of fake device types and bus types that should be silently
        # ignored
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)
        mdjson = mdinst.lookup("/openstack/latest/meta_data.json")
        mddict = jsonutils.loads(mdjson)
        self.assertEqual(fake_metadata_dicts(True, True), mddict['devices'])

    def test_top_level_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        result = mdinst.lookup("/openstack")

        # trailing / should not affect anything
        self.assertEqual(result, mdinst.lookup("/openstack/"))

        # the 'content' should not show up in directory listing
        self.assertNotIn(base.CONTENT_DIR, result)
        self.assertIn('2012-08-10', result)
        self.assertIn('latest', result)

    def test_version_content_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        listing = mdinst.lookup("/openstack/2012-08-10")
        self.assertIn("meta_data.json", listing)

    def test_returns_apis_supported_in_liberty_version(self):
        mdinst = fake_InstanceMetadata(self, self.instance)
        liberty_supported_apis = mdinst.lookup("/openstack/2015-10-15")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME, base.PASS_NAME,
                          base.VD_JSON_NAME, base.NW_JSON_NAME],
                         liberty_supported_apis)

    def test_returns_apis_supported_in_havana_version(self):
        mdinst = fake_InstanceMetadata(self, self.instance)
        havana_supported_apis = mdinst.lookup("/openstack/2013-10-17")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME, base.PASS_NAME,
                          base.VD_JSON_NAME], havana_supported_apis)

    def test_returns_apis_supported_in_folsom_version(self):
        mdinst = fake_InstanceMetadata(self, self.instance)
        folsom_supported_apis = mdinst.lookup("/openstack/2012-08-10")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME],
                         folsom_supported_apis)

    def test_returns_apis_supported_in_grizzly_version(self):
        mdinst = fake_InstanceMetadata(self, self.instance)
        grizzly_supported_apis = mdinst.lookup("/openstack/2013-04-04")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME, base.PASS_NAME],
                         grizzly_supported_apis)

    def test_metadata_json(self):
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        content = [
            ('/etc/my.conf', "content of my.conf"),
            ('/root/hello', "content of /root/hello"),
        ]

        mdinst = fake_InstanceMetadata(self, inst,
            content=content)
        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mdjson = mdinst.lookup("/openstack/latest/meta_data.json")

        mddict = jsonutils.loads(mdjson)

        self.assertEqual(mddict['uuid'], self.instance['uuid'])
        self.assertIn('files', mddict)

        self.assertIn('public_keys', mddict)
        self.assertEqual(mddict['public_keys'][self.instance['key_name']],
            self.instance['key_data'])

        self.assertIn('launch_index', mddict)
        self.assertEqual(mddict['launch_index'], self.instance['launch_index'])

        # verify that each of the things we put in content
        # resulted in an entry in 'files', that their content
        # there is as expected, and that /content lists them.
        for (path, content) in content:
            fent = [f for f in mddict['files'] if f['path'] == path]
            self.assertEqual(1, len(fent))
            fent = fent[0]
            found = mdinst.lookup("/openstack%s" % fent['content_path'])
            self.assertEqual(found, content)

    def test_x509_keypair(self):
        inst = self.instance.obj_clone()
        expected = {'name': self.instance['key_name'],
                    'type': 'x509',
                    'data': 'public_key'}
        inst.keypairs[0].name = expected['name']
        inst.keypairs[0].type = expected['type']
        inst.keypairs[0].public_key = expected['data']
        mdinst = fake_InstanceMetadata(self, inst)

        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        self.assertEqual([expected], mddict['keys'])

    def test_extra_md(self):
        # make sure extra_md makes it through to metadata
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        extra = {'foo': 'bar', 'mylist': [1, 2, 3],
                 'mydict': {"one": 1, "two": 2}}
        mdinst = fake_InstanceMetadata(self, inst, extra_md=extra)

        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        for key, val in extra.items():
            self.assertEqual(mddict[key], val)

    def test_password(self):
        # make sure extra_md makes it through to metadata
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        result = mdinst.lookup("/openstack/latest/password")
        self.assertEqual(result, password.handle_password)

    def test_userdata(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        userdata_found = mdinst.lookup("/openstack/2012-08-10/user_data")
        self.assertEqual(USER_DATA_STRING, userdata_found)

        # since we had user-data in this instance, it should be in listing
        self.assertIn('user_data', mdinst.lookup("/openstack/2012-08-10"))

        inst.user_data = None
        mdinst = fake_InstanceMetadata(self, inst)

        # since this instance had no user-data it should not be there.
        self.assertNotIn('user_data', mdinst.lookup("/openstack/2012-08-10"))

        self.assertRaises(base.InvalidMetadataPath,
            mdinst.lookup, "/openstack/2012-08-10/user_data")

    def test_random_seed(self):
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        # verify that 2013-04-04 has the 'random' field
        mdjson = mdinst.lookup("/openstack/2013-04-04/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        self.assertIn("random_seed", mddict)
        self.assertEqual(len(base64.decode_as_bytes(mddict["random_seed"])),
                         512)

        # verify that older version do not have it
        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        self.assertNotIn("random_seed", jsonutils.loads(mdjson))

    def test_project_id(self):
        fakes.stub_out_key_pair_funcs(self)
        mdinst = fake_InstanceMetadata(self, self.instance)

        # verify that 2015-10-15 has the 'project_id' field
        mdjson = mdinst.lookup("/openstack/2015-10-15/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        self.assertIn("project_id", mddict)
        self.assertEqual(mddict["project_id"], self.instance.project_id)

        # verify that older version do not have it
        mdjson = mdinst.lookup("/openstack/2013-10-17/meta_data.json")
        self.assertNotIn("project_id", jsonutils.loads(mdjson))

    def test_no_dashes_in_metadata(self):
        # top level entries in meta_data should not contain '-' in their name
        fakes.stub_out_key_pair_funcs(self)
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)
        mdjson = jsonutils.loads(
            mdinst.lookup("/openstack/latest/meta_data.json"))

        self.assertEqual([], [k for k in mdjson.keys() if k.find("-") != -1])

    def test_vendor_data_presence(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        # verify that 2013-10-17 has the vendor_data.json file
        result = mdinst.lookup("/openstack/2013-10-17")
        self.assertIn('vendor_data.json', result)

        # verify that older version do not have it
        result = mdinst.lookup("/openstack/2013-04-04")
        self.assertNotIn('vendor_data.json', result)

        # verify that 2016-10-06 has the vendor_data2.json file
        result = mdinst.lookup("/openstack/2016-10-06")
        self.assertIn('vendor_data2.json', result)
        # assert that we never created a ksa session for dynamic vendordata if
        # we didn't make a request
        self.assertIsNone(mdinst.vendordata_providers['DynamicJSON'].session)

    def _test_vendordata2_response_inner(self, request_mock, response_code,
                                         include_rest_result=True):
        content = None
        if include_rest_result:
            content = '{"color": "blue"}'
        fake_response = fake_requests.FakeResponse(response_code,
                                                   content=content)
        request_mock.return_value = fake_response

        with utils.tempdir() as tmpdir:
            jsonfile = os.path.join(tmpdir, 'test.json')
            with open(jsonfile, 'w') as f:
                f.write(jsonutils.dumps({'ldap': '10.0.0.1',
                                         'ad': '10.0.0.2'}))

            self.flags(vendordata_providers=['StaticJSON', 'DynamicJSON'],
                       vendordata_jsonfile_path=jsonfile,
                       vendordata_dynamic_targets=[
                           'web@http://fake.com/foobar'],
                       group='api'
                       )

            inst = self.instance.obj_clone()
            mdinst = fake_InstanceMetadata(self, inst)

            # verify that 2013-10-17 has the vendor_data.json file
            vdpath = "/openstack/2013-10-17/vendor_data.json"
            vd = jsonutils.loads(mdinst.lookup(vdpath))
            self.assertEqual('10.0.0.1', vd.get('ldap'))
            self.assertEqual('10.0.0.2', vd.get('ad'))

            # verify that 2016-10-06 works as well
            vdpath = "/openstack/2016-10-06/vendor_data.json"
            vd = jsonutils.loads(mdinst.lookup(vdpath))
            self.assertEqual('10.0.0.1', vd.get('ldap'))
            self.assertEqual('10.0.0.2', vd.get('ad'))

            # verify the new format as well
            vdpath = "/openstack/2016-10-06/vendor_data2.json"
            with mock.patch(
                    'nova.api.metadata.vendordata_dynamic.LOG.warning') as wrn:
                vd = jsonutils.loads(mdinst.lookup(vdpath))
                # We don't have vendordata_dynamic_auth credentials configured
                # so we expect to see a warning logged about making an insecure
                # connection.
                warning_calls = wrn.call_args_list
                self.assertEqual(1, len(warning_calls))
                # Verify the warning message is the one we expect which is the
                # first and only arg to the first and only call to the warning.
                self.assertIn('Passing insecure dynamic vendordata requests',
                              six.text_type(warning_calls[0][0]))
            self.assertEqual('10.0.0.1', vd['static'].get('ldap'))
            self.assertEqual('10.0.0.2', vd['static'].get('ad'))

            if include_rest_result:
                self.assertEqual('blue', vd['web'].get('color'))
            else:
                self.assertEqual({}, vd['web'])

    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_ok(self, request_mock):
        self._test_vendordata2_response_inner(request_mock,
                                              requests.codes.OK)

    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_created(self, request_mock):
        self._test_vendordata2_response_inner(request_mock,
                                              requests.codes.CREATED)

    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_accepted(self, request_mock):
        self._test_vendordata2_response_inner(request_mock,
                                              requests.codes.ACCEPTED)

    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_no_content(self, request_mock):
        # Make it a failure if no content was returned and we don't handle it.
        self.flags(vendordata_dynamic_failure_fatal=True, group='api')
        self._test_vendordata2_response_inner(request_mock,
                                              requests.codes.NO_CONTENT,
                                              include_rest_result=False)

    def _test_vendordata2_response_inner_exceptional(
            self, request_mock, log_mock, exc):
        request_mock.side_effect = exc('Ta da!')

        with utils.tempdir() as tmpdir:
            jsonfile = os.path.join(tmpdir, 'test.json')
            with open(jsonfile, 'w') as f:
                f.write(jsonutils.dumps({'ldap': '10.0.0.1',
                                         'ad': '10.0.0.2'}))

            self.flags(vendordata_providers=['StaticJSON', 'DynamicJSON'],
                       vendordata_jsonfile_path=jsonfile,
                       vendordata_dynamic_targets=[
                           'web@http://fake.com/foobar'],
                       group='api'
                       )

            inst = self.instance.obj_clone()
            mdinst = fake_InstanceMetadata(self, inst)

            # verify the new format as well
            vdpath = "/openstack/2016-10-06/vendor_data2.json"
            vd = jsonutils.loads(mdinst.lookup(vdpath))
            self.assertEqual('10.0.0.1', vd['static'].get('ldap'))
            self.assertEqual('10.0.0.2', vd['static'].get('ad'))

            # and exception should result in nothing being added, but no error
            self.assertEqual({}, vd['web'])
            self.assertTrue(log_mock.called)

    @mock.patch.object(vendordata_dynamic.LOG, 'warning')
    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_type_error(self, request_mock,
                                                         log_mock):
        self._test_vendordata2_response_inner_exceptional(
                request_mock, log_mock, TypeError)

    @mock.patch.object(vendordata_dynamic.LOG, 'warning')
    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_value_error(self, request_mock,
                                                          log_mock):
        self._test_vendordata2_response_inner_exceptional(
                request_mock, log_mock, ValueError)

    @mock.patch.object(vendordata_dynamic.LOG, 'warning')
    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_request_error(self,
                                                            request_mock,
                                                            log_mock):
        self._test_vendordata2_response_inner_exceptional(
                request_mock, log_mock, ks_exceptions.BadRequest)

    @mock.patch.object(vendordata_dynamic.LOG, 'warning')
    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_ssl_error(self,
                                                        request_mock,
                                                        log_mock):
        self._test_vendordata2_response_inner_exceptional(
                request_mock, log_mock, ks_exceptions.SSLError)

    @mock.patch.object(vendordata_dynamic.LOG, 'warning')
    @mock.patch.object(session.Session, 'request')
    def test_vendor_data_response_vendordata2_ssl_error_fatal(self,
                                                              request_mock,
                                                              log_mock):
        self.flags(vendordata_dynamic_failure_fatal=True, group='api')
        self.assertRaises(ks_exceptions.SSLError,
                          self._test_vendordata2_response_inner_exceptional,
                          request_mock, log_mock, ks_exceptions.SSLError)

    def test_network_data_presence(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self, inst)

        # verify that 2015-10-15 has the network_data.json file
        result = mdinst.lookup("/openstack/2015-10-15")
        self.assertIn('network_data.json', result)

        # verify that older version do not have it
        result = mdinst.lookup("/openstack/2013-10-17")
        self.assertNotIn('network_data.json', result)

    def test_network_data_response(self):
        inst = self.instance.obj_clone()

        nw_data = {
            "links": [{"ethernet_mac_address": "aa:aa:aa:aa:aa:aa",
                       "id": "nic0", "type": "ethernet", "vif_id": 1,
                       "mtu": 1500}],
            "networks": [{"id": "network0", "ip_address": "10.10.0.2",
                          "link": "nic0", "netmask": "255.255.255.0",
                          "network_id":
                          "00000000-0000-0000-0000-000000000000",
                          "routes": [], "type": "ipv4"}],
            "services": [{'address': '1.2.3.4', 'type': 'dns'}]}

        mdinst = fake_InstanceMetadata(self, inst,
                                       network_metadata=nw_data)

        # verify that 2015-10-15 has the network_data.json file
        nwpath = "/openstack/2015-10-15/network_data.json"
        nw = jsonutils.loads(mdinst.lookup(nwpath))

        # check the other expected values
        for k, v in nw_data.items():
            self.assertEqual(nw[k], v)


class MetadataHandlerTestCase(test.TestCase):
    """Test that metadata is returning proper values."""

    def setUp(self):
        super(MetadataHandlerTestCase, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.mdinst = fake_InstanceMetadata(self, self.instance,
            address=None, sgroups=None)

    def test_callable(self):

        def verify(req, meta_data):
            self.assertIsInstance(meta_data, CallableMD)
            return "foo"

        class CallableMD(object):
            def lookup(self, path_info):
                return verify

        response = fake_request(self, CallableMD(), "/bar")
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.text, "foo")

    def test_root(self):
        expected = "\n".join(base.VERSIONS) + "\nlatest"
        response = fake_request(self, self.mdinst, "/")
        self.assertEqual(response.text, expected)

        response = fake_request(self, self.mdinst, "/foo/../")
        self.assertEqual(response.text, expected)

    def test_root_metadata_proxy_enabled(self):
        self.flags(service_metadata_proxy=True,
                   group='neutron')

        expected = "\n".join(base.VERSIONS) + "\nlatest"
        response = fake_request(self, self.mdinst, "/")
        self.assertEqual(response.text, expected)

        response = fake_request(self, self.mdinst, "/foo/../")
        self.assertEqual(response.text, expected)

    def test_version_root(self):
        response = fake_request(self, self.mdinst, "/2009-04-04")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.text, 'meta-data/\nuser-data')

        response = fake_request(self, self.mdinst, "/9999-99-99")
        self.assertEqual(response.status_int, 404)

    def test_json_data(self):
        fakes.stub_out_key_pair_funcs(self)
        response = fake_request(self, self.mdinst,
                                "/openstack/latest/meta_data.json")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("application/json"))

        response = fake_request(self, self.mdinst,
                                "/openstack/latest/vendor_data.json")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("application/json"))

    @mock.patch('nova.network.neutron.API')
    def test_user_data_non_existing_fixed_address(self, mock_network_api):
        mock_network_api.return_value.get_fixed_ip_by_address.side_effect = (
            exception.NotFound())
        response = fake_request(None, self.mdinst, "/2009-04-04/user-data",
                                "127.1.1.1")
        self.assertEqual(response.status_int, 404)

    def test_fixed_address_none(self):
        response = fake_request(None, self.mdinst,
                                relpath="/2009-04-04/user-data", address=None)
        self.assertEqual(response.status_int, 500)

    def test_invalid_path_is_404(self):
        response = fake_request(self, self.mdinst,
                                relpath="/2009-04-04/user-data-invalid")
        self.assertEqual(response.status_int, 404)

    def test_user_data_with_use_forwarded_header(self):
        expected_addr = "192.192.192.2"

        def fake_get_metadata(self_gm, address):
            if address == expected_addr:
                return self.mdinst
            else:
                raise Exception("Expected addr of %s, got %s" %
                                (expected_addr, address))

        self.flags(use_forwarded_for=True, group='api')
        response = fake_request(self, self.mdinst,
                                relpath="/2009-04-04/user-data",
                                address="168.168.168.1",
                                fake_get_metadata=fake_get_metadata,
                                headers={'X-Forwarded-For': expected_addr})

        self.assertEqual(response.status_int, 200)
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.body,
                         base64.decode_as_bytes(self.instance['user_data']))

        response = fake_request(self, self.mdinst,
                                relpath="/2009-04-04/user-data",
                                address="168.168.168.1",
                                fake_get_metadata=fake_get_metadata,
                                headers=None)
        self.assertEqual(response.status_int, 500)

    @mock.patch('oslo_utils.secretutils.constant_time_compare')
    def test_by_instance_id_uses_constant_time_compare(self, mock_compare):
        mock_compare.side_effect = test.TestingException

        req = webob.Request.blank('/')
        hnd = handler.MetadataRequestHandler()

        req.headers['X-Instance-ID'] = 'fake-inst'
        req.headers['X-Instance-ID-Signature'] = 'fake-sig'
        req.headers['X-Tenant-ID'] = 'fake-proj'

        self.assertRaises(test.TestingException,
                          hnd._handle_instance_id_request, req)

        self.assertEqual(1, mock_compare.call_count)

    def _fake_x_get_metadata(self, self_app, instance_id, remote_address):
        if remote_address is None:
            raise Exception('Expected X-Forwared-For header')

        if encodeutils.to_utf8(instance_id) == self.expected_instance_id:
            return self.mdinst

        # raise the exception to aid with 500 response code test
        raise Exception("Expected instance_id of %r, got %r" %
                        (self.expected_instance_id, instance_id))

    def test_user_data_with_neutron_instance_id(self):
        self.expected_instance_id = b'a-b-c-d'

        signed = hmac.new(
            encodeutils.to_utf8(CONF.neutron.metadata_proxy_shared_secret),
            self.expected_instance_id,
            hashlib.sha256).hexdigest()

        # try a request with service disabled
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            headers={'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})
        self.assertEqual(response.status_int, 200)

        # now enable the service
        self.flags(service_metadata_proxy=True,
                   group='neutron')
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 200)
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.body,
                         base64.decode_as_bytes(self.instance['user_data']))

        # mismatched signature
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': ''})

        self.assertEqual(response.status_int, 403)

        # missing X-Tenant-ID from request
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 400)

        # mismatched X-Tenant-ID
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'FAKE',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 404)

        # without X-Forwarded-For
        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 500)

        # unexpected Instance-ID
        signed = hmac.new(
            encodeutils.to_utf8(CONF.neutron.metadata_proxy_shared_secret),
           b'z-z-z-z',
           hashlib.sha256).hexdigest()

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'z-z-z-z',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})
        self.assertEqual(response.status_int, 500)

    def test_get_metadata(self):
        def _test_metadata_path(relpath):
            # recursively confirm a http 200 from all meta-data elements
            # available at relpath.
            response = fake_request(self, self.mdinst,
                                    relpath=relpath)
            for item in response.text.split('\n'):
                if 'public-keys' in relpath:
                    # meta-data/public-keys/0=keyname refers to
                    # meta-data/public-keys/0
                    item = item.split('=')[0]
                if item.endswith('/'):
                    path = relpath + '/' + item
                    _test_metadata_path(path)
                    continue

                path = relpath + '/' + item
                response = fake_request(self, self.mdinst, relpath=path)
                self.assertEqual(response.status_int, 200, message=path)

        _test_metadata_path('/2009-04-04/meta-data')

    def _metadata_handler_with_instance_id(self, hnd):
        expected_instance_id = b'a-b-c-d'

        signed = hmac.new(
            encodeutils.to_utf8(CONF.neutron.metadata_proxy_shared_secret),
            expected_instance_id,
            hashlib.sha256).hexdigest()

        self.flags(service_metadata_proxy=True, group='neutron')
        response = fake_request(
            None, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata=False,
            app=hnd,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(200, response.status_int)
        self.assertEqual(base64.decode_as_bytes(self.instance['user_data']),
                         response.body)

    @mock.patch.object(base, 'get_metadata_by_instance_id')
    def test_metadata_handler_with_instance_id(self, get_by_uuid):
        # test twice to ensure that the cache works
        get_by_uuid.return_value = self.mdinst
        self.flags(metadata_cache_expiration=15, group='api')
        hnd = handler.MetadataRequestHandler()
        self._metadata_handler_with_instance_id(hnd)
        self._metadata_handler_with_instance_id(hnd)
        self.assertEqual(1, get_by_uuid.call_count)

    @mock.patch.object(base, 'get_metadata_by_instance_id')
    def test_metadata_handler_with_instance_id_no_cache(self, get_by_uuid):
        # test twice to ensure that disabling the cache works
        get_by_uuid.return_value = self.mdinst
        self.flags(metadata_cache_expiration=0, group='api')
        hnd = handler.MetadataRequestHandler()
        self._metadata_handler_with_instance_id(hnd)
        self._metadata_handler_with_instance_id(hnd)
        self.assertEqual(2, get_by_uuid.call_count)

    def _metadata_handler_with_remote_address(self, hnd):
        response = fake_request(
            None, self.mdinst,
            fake_get_metadata=False,
            app=hnd,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2")
        self.assertEqual(200, response.status_int)
        self.assertEqual(base64.decode_as_bytes(self.instance.user_data),
                         response.body)

    @mock.patch.object(base, 'get_metadata_by_address')
    def test_metadata_handler_with_remote_address(self, get_by_uuid):
        # test twice to ensure that the cache works
        get_by_uuid.return_value = self.mdinst
        self.flags(metadata_cache_expiration=15, group='api')
        hnd = handler.MetadataRequestHandler()
        self._metadata_handler_with_remote_address(hnd)
        self._metadata_handler_with_remote_address(hnd)
        self.assertEqual(1, get_by_uuid.call_count)

    @mock.patch.object(base, 'get_metadata_by_address')
    def test_metadata_handler_with_remote_address_no_cache(self, get_by_uuid):
        # test twice to ensure that disabling the cache works
        get_by_uuid.return_value = self.mdinst
        self.flags(metadata_cache_expiration=0, group='api')
        hnd = handler.MetadataRequestHandler()
        self._metadata_handler_with_remote_address(hnd)
        self._metadata_handler_with_remote_address(hnd)
        self.assertEqual(2, get_by_uuid.call_count)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy(self, mock_get_client):

        self.flags(service_metadata_proxy=True, group='neutron')

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id})

        self.assertEqual(200, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy_many_networks(self, mock_get_client):

        def fake_list_ports(context, fixed_ips, network_id, fields):
            if 'f-f-f-f' in network_id:
                return {'ports':
                            [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
            return {'ports': []}

        self.flags(service_metadata_proxy=True, group='neutron')
        handler.MAX_QUERY_NETWORKS = 10

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        mock_client = mock_get_client.return_value
        subnet_list = [{'network_id': 'f-f-f-' + chr(c)}
                       for c in range(ord('a'), ord('z'))]
        mock_client.list_subnets.return_value = {
            'subnets': subnet_list}

        with mock.patch.object(
                mock_client, 'list_ports',
                side_effect=fake_list_ports) as mock_list_ports:

            response = fake_request(
                self, self.mdinst,
                relpath="/2009-04-04/user-data",
                address="192.192.192.2",
                fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
                headers={'X-Forwarded-For': '192.192.192.2',
                         'X-Metadata-Provider': proxy_lb_id})

            self.assertEqual(3, mock_list_ports.call_count)

        self.assertEqual(200, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def _metadata_handler_with_provider_id(self, hnd, mock_get_client):
        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            app=hnd,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id})

        self.assertEqual(200, response.status_int)
        self.assertEqual(base64.decode_as_bytes(self.instance['user_data']),
                         response.body)

    @mock.patch.object(base, 'get_metadata_by_instance_id')
    def _test__handler_with_provider_id(self,
                                        expected_calls,
                                        get_by_uuid):
        get_by_uuid.return_value = self.mdinst
        hnd = handler.MetadataRequestHandler()
        with mock.patch.object(hnd, '_get_instance_id_from_lb',
                               return_value=('a-b-c-d',
                                             'test')) as _get_id_from_lb:
            self._metadata_handler_with_provider_id(hnd)
            self._metadata_handler_with_provider_id(hnd)
            self.assertEqual(expected_calls, _get_id_from_lb.call_count)

    def test_metadata_handler_with_provider_id(self):
        self.flags(service_metadata_proxy=True, group='neutron')
        self.flags(metadata_cache_expiration=15, group='api')
        self._test__handler_with_provider_id(1)

    def test_metadata_handler_with_provider_id_no_cache(self):
        self.flags(service_metadata_proxy=True, group='neutron')
        self.flags(metadata_cache_expiration=0, group='api')
        self._test__handler_with_provider_id(2)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy_chain(self, mock_get_client):

        self.flags(service_metadata_proxy=True, group='neutron')

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        def fake_list_ports(ctx, **kwargs):
            if kwargs.get('fixed_ips') == 'ip_address=192.192.192.2':
                return {
                    'ports': [{
                        'device_id': 'a-b-c-d',
                        'tenant_id': 'test'}]}
            else:
                return {'ports':
                        []}

        mock_client = mock_get_client.return_value
        mock_client.list_ports.side_effect = fake_list_ports
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="10.10.10.10",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2, 10.10.10.10',
                     'X-Metadata-Provider': proxy_lb_id})

        self.assertEqual(200, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy_signed(self, mock_get_client):

        shared_secret = "testing1234"
        self.flags(
            metadata_proxy_shared_secret=shared_secret,
            service_metadata_proxy=True, group='neutron')

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        signature = hmac.new(
            encodeutils.to_utf8(shared_secret),
            encodeutils.to_utf8(proxy_lb_id),
            hashlib.sha256).hexdigest()

        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id,
                     'X-Metadata-Provider-Signature': signature})

        self.assertEqual(200, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy_not_signed(self, mock_get_client):

        shared_secret = "testing1234"
        self.flags(
            metadata_proxy_shared_secret=shared_secret,
            service_metadata_proxy=True, group='neutron')

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id})
        self.assertEqual(403, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_proxy_signed_fail(self, mock_get_client):

        shared_secret = "testing1234"
        bad_secret = "testing3468"
        self.flags(
            metadata_proxy_shared_secret=shared_secret,
            service_metadata_proxy=True, group='neutron')

        self.expected_instance_id = b'a-b-c-d'

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'

        signature = hmac.new(
            encodeutils.to_utf8(bad_secret),
            encodeutils.to_utf8(proxy_lb_id),
            hashlib.sha256).hexdigest()

        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id,
                     'X-Metadata-Provider-Signature': signature})
        self.assertEqual(403, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_net_not_found(self, mock_get_client):

        self.flags(service_metadata_proxy=True, group='neutron')

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'
        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': []}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id})
        self.assertEqual(400, response.status_int)

    def _test_metadata_lb_incorrect_port_count(self, mock_get_client, ports):

        self.flags(service_metadata_proxy=True, group='neutron')

        # with X-Metadata-Provider
        proxy_lb_id = 'edge-x'
        mock_client = mock_get_client.return_value
        mock_client.list_ports.return_value = {'ports': ports}
        mock_client.list_ports.return_value = {
            'ports': [{'device_id': 'a-b-c-d', 'tenant_id': 'test'},
                      {'device_id': 'x-y-z', 'tenant_id': 'test'}]}
        mock_client.list_subnets.return_value = {
            'subnets': [{'network_id': 'f-f-f-f'}]}

        response = fake_request(
            self, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=self._fake_x_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Metadata-Provider': proxy_lb_id})
        self.assertEqual(400, response.status_int)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_lb_too_many_ports(self, mock_get_client):
        self._test_metadata_lb_incorrect_port_count(
            mock_get_client,
            [{'device_id': 'a-b-c-d', 'tenant_id': 'test'},
             {'device_id': 'x-y-z', 'tenant_id': 'test'}])

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_metadata_no_ports_found(self, mock_get_client):
        self._test_metadata_lb_incorrect_port_count(
            mock_get_client, [])

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch('nova.network.neutron.API.get_fixed_ip_by_address')
    def test_get_metadata_by_address(self, mock_get_fip, mock_get_context):
        mock_get_context.return_value = 'CONTEXT'
        mock_get_fip.return_value = {'instance_uuid': 'bar'}

        with mock.patch.object(base, 'get_metadata_by_instance_id') as gmd:
            base.get_metadata_by_address('foo')

        mock_get_fip.assert_called_once_with('CONTEXT', 'foo')
        gmd.assert_called_once_with('bar', 'foo', 'CONTEXT')

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_metadata_by_instance_id(self, mock_uuid, mock_context):
        inst = objects.Instance()
        mock_uuid.return_value = inst
        ctxt = context.RequestContext()

        with mock.patch.object(base, 'InstanceMetadata') as imd:
            base.get_metadata_by_instance_id('foo', 'bar', ctxt=ctxt)

        self.assertFalse(mock_context.called, "get_admin_context() should not"
                         "have been called, the context was given")
        mock_uuid.assert_called_once_with(ctxt, 'foo',
            expected_attrs=['ec2_ids', 'flavor', 'info_cache', 'metadata',
                            'system_metadata', 'security_groups', 'keypairs',
                            'device_metadata', 'numa_topology'])
        imd.assert_called_once_with(inst, 'bar')

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_metadata_by_instance_id_null_context(self,
            mock_uuid, mock_context):
        inst = objects.Instance()
        mock_uuid.return_value = inst
        mock_context.return_value = context.RequestContext()

        with mock.patch.object(base, 'InstanceMetadata') as imd:
            base.get_metadata_by_instance_id('foo', 'bar')

        mock_context.assert_called_once_with()
        mock_uuid.assert_called_once_with(mock_context.return_value, 'foo',
            expected_attrs=['ec2_ids', 'flavor', 'info_cache', 'metadata',
                            'system_metadata', 'security_groups', 'keypairs',
                            'device_metadata', 'numa_topology'])
        imd.assert_called_once_with(inst, 'bar')

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_get_metadata_by_instance_id_with_cell_mapping(self, mock_get_im,
                                                           mock_get_inst):
        ctxt = context.RequestContext()
        inst = objects.Instance()
        im = objects.InstanceMapping(cell_mapping=objects.CellMapping())
        mock_get_inst.return_value = inst
        mock_get_im.return_value = im

        with mock.patch.object(base, 'InstanceMetadata') as imd:
            with mock.patch('nova.context.target_cell') as mock_tc:
                base.get_metadata_by_instance_id('foo', 'bar', ctxt=ctxt)
                mock_tc.assert_called_once_with(ctxt, im.cell_mapping)

        mock_get_im.assert_called_once_with(ctxt, 'foo')
        imd.assert_called_once_with(inst, 'bar')

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_get_metadata_by_instance_id_with_local_meta(self, mock_get_im,
                                                         mock_get_inst):
        # Test that if local_metadata_per_cell is set to True, we don't
        # query API DB for instance mapping.
        self.flags(local_metadata_per_cell=True, group='api')
        ctxt = context.RequestContext()
        inst = objects.Instance()
        mock_get_inst.return_value = inst

        with mock.patch.object(base, 'InstanceMetadata') as imd:
            base.get_metadata_by_instance_id('foo', 'bar', ctxt=ctxt)

        mock_get_im.assert_not_called()
        imd.assert_called_once_with(inst, 'bar')


class MetadataPasswordTestCase(test.TestCase):
    def setUp(self):
        super(MetadataPasswordTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.mdinst = fake_InstanceMetadata(self, self.instance,
            address=None, sgroups=None)

    def test_get_password(self):
        request = webob.Request.blank('')
        self.mdinst.password = 'foo'
        result = password.handle_password(request, self.mdinst)
        self.assertEqual(result, 'foo')

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       return_value=objects.InstanceMapping(cell_mapping=None))
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_set_password_instance_not_found(self, get_by_uuid, get_mapping):
        """Tests that a 400 is returned if the instance can not be found."""
        get_by_uuid.side_effect = exception.InstanceNotFound(
            instance_id=self.instance.uuid)
        request = webob.Request.blank('')
        request.method = 'POST'
        request.val = b'foo'
        request.content_length = len(request.body)
        self.assertRaises(webob.exc.HTTPBadRequest, password.handle_password,
                          request, self.mdinst)

    def test_bad_method(self):
        request = webob.Request.blank('')
        request.method = 'PUT'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          password.handle_password, request, self.mdinst)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    def _try_set_password(self, get_by_uuid, get_mapping, val=b'bar',
                          use_local_meta=False):
        if use_local_meta:
            self.flags(local_metadata_per_cell=True, group='api')
        request = webob.Request.blank('')
        request.method = 'POST'
        request.body = val
        get_mapping.return_value = objects.InstanceMapping(cell_mapping=None)
        get_by_uuid.return_value = self.instance

        with mock.patch.object(self.instance, 'save') as save:
            password.handle_password(request, self.mdinst)
            save.assert_called_once_with()

        self.assertIn('password_0', self.instance.system_metadata)
        if use_local_meta:
            get_mapping.assert_not_called()
        else:
            get_mapping.assert_called_once_with(mock.ANY, self.instance.uuid)

    def test_set_password(self):
        self.mdinst.password = ''
        self._try_set_password()

    def test_set_password_local_meta(self):
        self.mdinst.password = ''
        self._try_set_password(use_local_meta=True)

    def test_conflict(self):
        self.mdinst.password = 'foo'
        self.assertRaises(webob.exc.HTTPConflict,
                          self._try_set_password)

    def test_too_large(self):
        self.mdinst.password = ''
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._try_set_password,
                          val=(b'a' * (password.MAX_SIZE + 1)))
