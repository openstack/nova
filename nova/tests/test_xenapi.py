# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2010 Citrix Systems, Inc.
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

"""Test suite for XenAPI."""

import ast
import base64
import contextlib
import cPickle as pickle
import functools
import os
import re

from nova.compute import api as compute_api
from nova.compute import instance_types
from nova.compute import power_state
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test
from nova.tests.db import fakes as db_fakes
from nova.tests import fake_network
from nova.tests import fake_utils
import nova.tests.image.fake as fake_image
from nova.tests.xenapi import stubs
from nova.virt.xenapi import agent
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import host
from nova.virt.xenapi import pool
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volume_utils

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS

IMAGE_MACHINE = '1'
IMAGE_KERNEL = '2'
IMAGE_RAMDISK = '3'
IMAGE_RAW = '4'
IMAGE_VHD = '5'
IMAGE_ISO = '6'

IMAGE_FIXTURES = {
    IMAGE_MACHINE: {
        'image_meta': {'name': 'fakemachine', 'size': 0,
                       'disk_format': 'ami',
                       'container_format': 'ami'},
    },
    IMAGE_KERNEL: {
        'image_meta': {'name': 'fakekernel', 'size': 0,
                       'disk_format': 'aki',
                       'container_format': 'aki'},
    },
    IMAGE_RAMDISK: {
        'image_meta': {'name': 'fakeramdisk', 'size': 0,
                       'disk_format': 'ari',
                       'container_format': 'ari'},
    },
    IMAGE_RAW: {
        'image_meta': {'name': 'fakeraw', 'size': 0,
                       'disk_format': 'raw',
                       'container_format': 'bare'},
    },
    IMAGE_VHD: {
        'image_meta': {'name': 'fakevhd', 'size': 0,
                       'disk_format': 'vhd',
                       'container_format': 'ovf'},
    },
    IMAGE_ISO: {
        'image_meta': {'name': 'fakeiso', 'size': 0,
                       'disk_format': 'iso',
                       'container_format': 'bare'},
    },
}


def set_image_fixtures():
    image_service = fake_image.FakeImageService()
    image_service.images.clear()
    for image_id, image_meta in IMAGE_FIXTURES.items():
        image_meta = image_meta['image_meta']
        image_meta['id'] = image_id
        image_service.create(None, image_meta)


def stub_vm_utils_with_vdi_attached_here(function, should_return=True):
    """
    vm_utils.with_vdi_attached_here needs to be stubbed out because it
    calls down to the filesystem to attach a vdi. This provides a
    decorator to handle that.
    """
    @functools.wraps(function)
    def decorated_function(self, *args, **kwargs):
        @contextlib.contextmanager
        def fake_vdi_attached_here(*args, **kwargs):
            fake_dev = 'fakedev'
            yield fake_dev

        def fake_image_download(*args, **kwargs):
            pass

        def fake_is_vdi_pv(*args, **kwargs):
            return should_return

        orig_vdi_attached_here = vm_utils.vdi_attached_here
        orig_image_download = fake_image._FakeImageService.download
        orig_is_vdi_pv = vm_utils._is_vdi_pv
        try:
            vm_utils.vdi_attached_here = fake_vdi_attached_here
            fake_image._FakeImageService.download = fake_image_download
            vm_utils._is_vdi_pv = fake_is_vdi_pv
            return function(self, *args, **kwargs)
        finally:
            vm_utils._is_vdi_pv = orig_is_vdi_pv
            fake_image._FakeImageService.download = orig_image_download
            vm_utils.vdi_attached_here = orig_vdi_attached_here

    return decorated_function


class XenAPIVolumeTestCase(stubs.XenAPITestBase):
    """Unit tests for Volume operations."""
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.flags(disable_process_locking=True,
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')
        db_fakes.stub_out_db_instance_api(self.stubs)
        self.instance_values = {'id': 1,
                  'project_id': self.user_id,
                  'user_id': 'fake',
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

    def _create_volume(self, size=0):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['host'] = 'localhost'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(self.context, vol)

    @staticmethod
    def _make_info():
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'volume_id': 1,
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                'target_portal': '127.0.0.1:3260,fake',
                'target_lun': None,
                'auth_method': 'CHAP',
                'auth_method': 'fake',
                'auth_method': 'fake',
            }
        }

    def test_mountpoint_to_number(self):
        cases = {
            'sda': 0,
            'sdp': 15,
            'hda': 0,
            'hdp': 15,
            'vda': 0,
            'xvda': 0,
            '0': 0,
            '10': 10,
            'vdq': -1,
            'sdq': -1,
            'hdq': -1,
            'xvdq': -1,
        }

        for (input, expected) in cases.iteritems():
            actual = volume_utils.mountpoint_to_number(input)
            self.assertEqual(actual, expected,
                    '%s yielded %s, not %s' % (input, actual, expected))

    def test_parse_volume_info_raise_exception(self):
        """This shows how to test helper classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        vol = self._create_volume()
        # oops, wrong mount point!
        self.assertRaises(volume_utils.StorageError,
                          volume_utils.parse_volume_info,
                          self._make_info(),
                          'dev/sd'
                          )
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        """This shows how to test Ops classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.XenAPIDriver(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.instance_values)
        vm = xenapi_fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(self._make_info(),
                                    instance.name, '/dev/sdc')

        # check that the VM has a VBD attached to it
        # Get XenAPI record for VBD
        vbds = xenapi_fake.get_all('VBD')
        vbd = xenapi_fake.get_record('VBD', vbds[0])
        vm_ref = vbd['VM']
        self.assertEqual(vm_ref, vm)

    def test_attach_volume_raise_exception(self):
        """This shows how to test when exceptions are raised."""
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.XenAPIDriver(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.instance_values)
        xenapi_fake.create_vm(instance.name, 'Running')
        self.assertRaises(exception.VolumeDriverNotFound,
                          conn.attach_volume,
                          {'driver_volume_type': 'nonexist'},
                          instance.name,
                          '/dev/sdc')


class XenAPIVMTestCase(stubs.XenAPITestBase):
    """Unit tests for VM operations."""
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.network = importutils.import_object(FLAGS.network_manager)
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',)
        xenapi_fake.create_local_srs()
        xenapi_fake.create_local_pifs()
        db_fakes.stub_out_db_instance_api(self.stubs)
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        stubs.stubout_is_vdi_pv(self.stubs)
        stubs.stub_out_vm_methods(self.stubs)
        fake_utils.stub_out_utils_execute(self.stubs)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.conn = xenapi_conn.XenAPIDriver(False)

        fake_image.stub_out_image_service(self.stubs)
        set_image_fixtures()
        stubs.stubout_image_service_download(self.stubs)
        stubs.stubout_stream_disk(self.stubs)

        def fake_inject_instance_metadata(self, instance, vm):
            pass
        self.stubs.Set(vmops.VMOps, 'inject_instance_metadata',
                       fake_inject_instance_metadata)

        def fake_safe_copy_vdi(session, sr_ref, instance, vdi_to_copy_ref):
            name_label = "fakenamelabel"
            disk_type = "fakedisktype"
            virtual_size = 777
            return vm_utils.create_vdi(
                    session, sr_ref, instance, name_label, disk_type,
                    virtual_size)
        self.stubs.Set(vm_utils, '_safe_copy_vdi', fake_safe_copy_vdi)

    def tearDown(self):
        super(XenAPIVMTestCase, self).tearDown()
        fake_image.FakeImageService_reset()

    def test_init_host(self):
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        vm = vm_utils._get_this_vm_ref(session)
        # Local root disk
        vdi0 = xenapi_fake.create_vdi('compute', None)
        vbd0 = xenapi_fake.create_vbd(vm, vdi0)
        # Instance VDI
        vdi1 = xenapi_fake.create_vdi('instance-aaaa', None,
                other_config={'nova_instance_uuid': 'aaaa'})
        vbd1 = xenapi_fake.create_vbd(vm, vdi1)
        # Only looks like instance VDI
        vdi2 = xenapi_fake.create_vdi('instance-bbbb', None)
        vbd2 = xenapi_fake.create_vbd(vm, vdi2)

        self.conn.init_host(None)
        self.assertEquals(set(xenapi_fake.get_all('VBD')), set([vbd0, vbd2]))

    def test_list_instances_0(self):
        instances = self.conn.list_instances()
        self.assertEquals(instances, [])

    def test_get_rrd_server(self):
        self.flags(xenapi_connection_url='myscheme://myaddress/')
        server_info = vm_utils._get_rrd_server()
        self.assertEqual(server_info[0], 'myscheme')
        self.assertEqual(server_info[1], 'myaddress')

    def test_get_diagnostics(self):
        def fake_get_rrd(host, vm_uuid):
            with open('xenapi/vm_rrd.xml') as f:
                return re.sub(r'\s', '', f.read())
        self.stubs.Set(vm_utils, '_get_rrd', fake_get_rrd)

        fake_diagnostics = {
            'vbd_xvdb_write': '0.0',
            'memory_target': '4294967296.0000',
            'memory_internal_free': '1415564.0000',
            'memory': '4294967296.0000',
            'vbd_xvda_write': '0.0',
            'cpu0': '0.0042',
            'vif_0_tx': '287.4134',
            'vbd_xvda_read': '0.0',
            'vif_0_rx': '1816.0144',
            'vif_2_rx': '0.0',
            'vif_2_tx': '0.0',
            'vbd_xvdb_read': '0.0',
            'last_update': '1328795567',
        }
        instance = self._create_instance()
        expected = self.conn.get_diagnostics(instance)
        self.assertDictMatch(fake_diagnostics, expected)

    def test_instance_snapshot_fails_with_no_primary_vdi(self):
        def create_bad_vbd(session, vm_ref, vdi_ref, userdevice,
                           vbd_type='disk', read_only=False, bootable=False):
            vbd_rec = {'VM': vm_ref,
               'VDI': vdi_ref,
               'userdevice': 'fake',
               'currently_attached': False}
            vbd_ref = xenapi_fake._create_object('VBD', vbd_rec)
            xenapi_fake.after_VBD_create(vbd_ref, vbd_rec)
            return vbd_ref

        self.stubs.Set(vm_utils, 'create_vbd', create_bad_vbd)
        stubs.stubout_instance_snapshot(self.stubs)
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        instance = self._create_instance()

        image_id = "my_snapshot_id"
        self.assertRaises(exception.NovaException, self.conn.snapshot,
                          self.context, instance, image_id)

    def test_instance_snapshot(self):
        stubs.stubout_instance_snapshot(self.stubs)
        stubs.stubout_is_snapshot(self.stubs)
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        instance = self._create_instance()

        image_id = "my_snapshot_id"
        self.conn.snapshot(self.context, instance, image_id)

        # Ensure VM was torn down
        vm_labels = []
        for vm_ref in xenapi_fake.get_all('VM'):
            vm_rec = xenapi_fake.get_record('VM', vm_ref)
            if not vm_rec["is_control_domain"]:
                vm_labels.append(vm_rec["name_label"])

        self.assertEquals(vm_labels, [instance.name])

        # Ensure VBDs were torn down
        vbd_labels = []
        for vbd_ref in xenapi_fake.get_all('VBD'):
            vbd_rec = xenapi_fake.get_record('VBD', vbd_ref)
            vbd_labels.append(vbd_rec["vm_name_label"])

        self.assertEquals(vbd_labels, [instance.name])

        # Ensure VDIs were torn down
        for vdi_ref in xenapi_fake.get_all('VDI'):
            vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
            name_label = vdi_rec["name_label"]
            self.assert_(not name_label.endswith('snapshot'))

    def create_vm_record(self, conn, os_type, name):
        instances = conn.list_instances()
        self.assertEquals(instances, [name])

        # Get Nova record for VM
        vm_info = conn.get_info({'name': name})
        # Get XenAPI record for VM
        vms = [rec for ref, rec
               in xenapi_fake.get_all_records('VM').iteritems()
               if not rec['is_control_domain']]
        vm = vms[0]
        self.vm_info = vm_info
        self.vm = vm

    def check_vm_record(self, conn, check_injection=False):
        # Check that m1.large above turned into the right thing.
        instance_type = db.instance_type_get_by_name(conn, 'm1.large')
        mem_kib = long(instance_type['memory_mb']) << 10
        mem_bytes = str(mem_kib << 10)
        vcpus = instance_type['vcpus']
        self.assertEquals(self.vm_info['max_mem'], mem_kib)
        self.assertEquals(self.vm_info['mem'], mem_kib)
        self.assertEquals(self.vm['memory_static_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_min'], mem_bytes)
        self.assertEquals(self.vm['VCPUs_max'], str(vcpus))
        self.assertEquals(self.vm['VCPUs_at_startup'], str(vcpus))

        # Check that the VM is running according to Nova
        self.assertEquals(self.vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to XenAPI.
        self.assertEquals(self.vm['power_state'], 'Running')

        if check_injection:
            xenstore_data = self.vm['xenstore_data']
            self.assertEquals(xenstore_data['vm-data/hostname'], 'test')
            key = 'vm-data/networking/DEADBEEF0001'
            xenstore_value = xenstore_data[key]
            tcpip_data = ast.literal_eval(xenstore_value)
            self.assertEquals(tcpip_data,
                              {'broadcast': '192.168.1.255',
                               'dns': ['192.168.1.4', '192.168.1.3'],
                               'gateway': '192.168.1.1',
                               'gateway_v6': 'fe80::def',
                               'ip6s': [{'enabled': '1',
                                         'ip': '2001:db8:0:1::1',
                                         'netmask': 64,
                                         'gateway': 'fe80::def'}],
                               'ips': [{'enabled': '1',
                                        'ip': '192.168.1.100',
                                        'netmask': '255.255.255.0',
                                        'gateway': '192.168.1.1'},
                                       {'enabled': '1',
                                        'ip': '192.168.1.101',
                                        'netmask': '255.255.255.0',
                                        'gateway': '192.168.1.1'}],
                               'label': 'test1',
                               'mac': 'DE:AD:BE:EF:00:01'})

    def check_vm_params_for_windows(self):
        self.assertEquals(self.vm['platform']['nx'], 'true')
        self.assertEquals(self.vm['HVM_boot_params'], {'order': 'dc'})
        self.assertEquals(self.vm['HVM_boot_policy'], 'BIOS order')

        # check that these are not set
        self.assertEquals(self.vm['PV_args'], '')
        self.assertEquals(self.vm['PV_bootloader'], '')
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')

    def check_vm_params_for_linux(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], '')
        self.assertEquals(self.vm['PV_bootloader'], 'pygrub')

        # check that these are not set
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def check_vm_params_for_linux_with_external_kernel(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], 'root=/dev/xvda1')
        self.assertNotEquals(self.vm['PV_kernel'], '')
        self.assertNotEquals(self.vm['PV_ramdisk'], '')

        # check that these are not set
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def _list_vdis(self):
        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password
        session = xenapi_conn.XenAPISession(url, username, password)
        return session.call_xenapi('VDI.get_all')

    def _check_vdis(self, start_list, end_list):
        for vdi_ref in end_list:
            if not vdi_ref in start_list:
                vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
                # If the cache is turned on then the base disk will be
                # there even after the cleanup
                if 'other_config' in vdi_rec:
                    if 'image-id' not in vdi_rec['other_config']:
                        self.fail('Found unexpected VDI:%s' % vdi_ref)
                else:
                    self.fail('Found unexpected VDI:%s' % vdi_ref)

    def _test_spawn(self, image_ref, kernel_id, ramdisk_id,
                    instance_type_id="3", os_type="linux",
                    hostname="test", architecture="x86-64", instance_id=1,
                    injected_files=None, check_injection=False,
                    create_record=True, empty_dns=False):
        if injected_files is None:
            injected_files = []

        # Fake out inject_instance_metadata
        def fake_inject_instance_metadata(self, instance, vm):
            pass
        self.stubs.Set(vmops.VMOps, 'inject_instance_metadata',
                       fake_inject_instance_metadata)

        if create_record:
            instance_values = {'id': instance_id,
                      'project_id': self.project_id,
                      'user_id': self.user_id,
                      'image_ref': image_ref,
                      'kernel_id': kernel_id,
                      'ramdisk_id': ramdisk_id,
                      'root_gb': 20,
                      'instance_type_id': instance_type_id,
                      'os_type': os_type,
                      'hostname': hostname,
                      'architecture': architecture}
            instance = db.instance_create(self.context, instance_values)
        else:
            instance = db.instance_get(self.context, instance_id)

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        if empty_dns:
            # NOTE(tr3buchet): this is a terrible way to do this...
            network_info[0]['network']['subnets'][0]['dns'] = []

        image_meta = {'id': IMAGE_VHD,
                      'disk_format': 'vhd'}
        self.conn.spawn(self.context, instance, image_meta, injected_files,
                        'herp', network_info)
        self.create_vm_record(self.conn, os_type, instance['name'])
        self.check_vm_record(self.conn, check_injection)
        self.assertTrue(instance.os_type)
        self.assertTrue(instance.architecture)

    def test_spawn_empty_dns(self):
        """Test spawning with an empty dns list"""
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         empty_dns=True)
        self.check_vm_params_for_linux()

    def test_spawn_not_enough_memory(self):
        self.assertRaises(exception.InsufficientFreeMemory,
                          self._test_spawn,
                          1, 2, 3, "4")  # m1.xlarge

    def test_spawn_fail_cleanup_1(self):
        """Simulates an error while downloading an image.

        Verifies that VDIs created are properly cleaned up.

        """
        vdi_recs_start = self._list_vdis()
        stubs.stubout_fetch_disk_image(self.stubs, raise_failure=True)
        self.assertRaises(xenapi_fake.Failure,
                          self._test_spawn, 1, 2, 3)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        self._check_vdis(vdi_recs_start, vdi_recs_end)

    def test_spawn_fail_cleanup_2(self):
        """Simulates an error while creating VM record.

        It verifies that VDIs created are properly cleaned up.

        """
        vdi_recs_start = self._list_vdis()
        stubs.stubout_create_vm(self.stubs)
        self.assertRaises(xenapi_fake.Failure,
                          self._test_spawn, 1, 2, 3)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        self._check_vdis(vdi_recs_start, vdi_recs_end)

    @stub_vm_utils_with_vdi_attached_here
    def test_spawn_raw_glance(self):
        self._test_spawn(IMAGE_RAW, None, None)
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_linux(self):
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_swapdisk(self):
        # Change the default host_call_plugin to one that'll return
        # a swap disk
        orig_func = stubs.FakeSessionForVMTests.host_call_plugin
        _host_call_plugin = stubs.FakeSessionForVMTests.host_call_plugin_swap
        stubs.FakeSessionForVMTests.host_call_plugin = _host_call_plugin
        # Stubbing out firewall driver as previous stub sets a particular
        # stub for async plugin calls
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        try:
            # We'll steal the above glance linux test
            self.test_spawn_vhd_glance_linux()
        finally:
            # Make sure to put this back
            stubs.FakeSessionForVMTests.host_call_plugin = orig_func

        # We should have 2 VBDs.
        self.assertEqual(len(self.vm['VBDs']), 2)
        # Now test that we have 1.
        self.tearDown()
        self.setUp()
        self.test_spawn_vhd_glance_linux()
        self.assertEqual(len(self.vm['VBDs']), 1)

    def test_spawn_vhd_glance_windows(self):
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="windows", architecture="i386")
        self.check_vm_params_for_windows()

    def test_spawn_iso_glance(self):
        self._test_spawn(IMAGE_ISO, None, None,
                         os_type="windows", architecture="i386")
        self.check_vm_params_for_windows()

    def test_spawn_glance(self):
        stubs.stubout_fetch_disk_image(self.stubs)
        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK)
        self.check_vm_params_for_linux_with_external_kernel()

    def test_spawn_netinject_file(self):
        self.flags(flat_injected=True)
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _tee_handler(cmd, **kwargs):
            input = kwargs.get('process_input', None)
            self.assertNotEqual(input, None)
            config = [line.strip() for line in input.split("\n")]
            # Find the start of eth0 configuration and check it
            index = config.index('auto eth0')
            self.assertEquals(config[index + 1:index + 8], [
                'iface eth0 inet static',
                'address 192.168.1.100',
                'netmask 255.255.255.0',
                'broadcast 192.168.1.255',
                'gateway 192.168.1.1',
                'dns-nameservers 192.168.1.3 192.168.1.4',
                ''])
            self._tee_executed = True
            return '', ''

        def _readlink_handler(cmd_parts, **kwargs):
            return os.path.realpath(cmd_parts[2]), ''

        fake_utils.fake_execute_set_repliers([
            # Capture the tee .../etc/network/interfaces command
            (r'tee.*interfaces', _tee_handler),
            (r'readlink -nm.*', _readlink_handler),
        ])
        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK,
                         check_injection=True)
        self.assertTrue(self._tee_executed)

    def test_spawn_netinject_xenstore(self):
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _mount_handler(cmd, *ignore_args, **ignore_kwargs):
            # When mounting, create real files under the mountpoint to simulate
            # files in the mounted filesystem

            # mount point will be the last item of the command list
            self._tmpdir = cmd[len(cmd) - 1]
            LOG.debug(_('Creating files in %s to simulate guest agent'),
                      self._tmpdir)
            os.makedirs(os.path.join(self._tmpdir, 'usr', 'sbin'))
            # Touch the file using open
            open(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'), 'w').close()
            return '', ''

        def _umount_handler(cmd, *ignore_args, **ignore_kwargs):
            # Umount would normall make files in the m,ounted filesystem
            # disappear, so do that here
            LOG.debug(_('Removing simulated guest agent files in %s'),
                      self._tmpdir)
            os.remove(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'))
            os.rmdir(os.path.join(self._tmpdir, 'usr', 'sbin'))
            os.rmdir(os.path.join(self._tmpdir, 'usr'))
            return '', ''

        def _tee_handler(cmd, *ignore_args, **ignore_kwargs):
            self._tee_executed = True
            return '', ''

        fake_utils.fake_execute_set_repliers([
            (r'mount', _mount_handler),
            (r'umount', _umount_handler),
            (r'tee.*interfaces', _tee_handler)])
        self._test_spawn(1, 2, 3, check_injection=True)

        # tee must not run in this case, where an injection-capable
        # guest agent is detected
        self.assertFalse(self._tee_executed)

    def test_spawn_vlanmanager(self):
        self.flags(network_manager='nova.network.manager.VlanManager',
                   vlan_interface='fake0')

        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(vmops.VMOps, '_create_vifs', dummy)
        # Reset network table
        xenapi_fake.reset_table('network')
        # Instance id = 2 will use vlan network (see db/fakes.py)
        ctxt = self.context.elevated()
        instance = self._create_instance(2, False)
        networks = self.network.db.network_get_all(ctxt)
        for network in networks:
            self.network.set_network_host(ctxt, network)

        self.network.allocate_for_instance(ctxt,
                          instance_id=2,
                          instance_uuid='00000000-0000-0000-0000-000000000002',
                          host=FLAGS.host,
                          vpn=None,
                          rxtx_factor=3,
                          project_id=self.project_id)
        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK,
                         instance_id=2,
                         create_record=False)
        # TODO(salvatore-orlando): a complete test here would require
        # a check for making sure the bridge for the VM's VIF is
        # consistent with bridge specified in nova db

    def test_spawn_with_network_qos(self):
        self._create_instance()
        for vif_ref in xenapi_fake.get_all('VIF'):
            vif_rec = xenapi_fake.get_record('VIF', vif_ref)
            self.assertEquals(vif_rec['qos_algorithm_type'], 'ratelimit')
            self.assertEquals(vif_rec['qos_algorithm_params']['kbps'],
                              str(3 * 10 * 1024))

    def test_spawn_injected_files(self):
        """Test spawning with injected_files"""
        actual_injected_files = []

        def fake_inject_file(self, method, args):
            path = base64.b64decode(args['b64_path'])
            contents = base64.b64decode(args['b64_contents'])
            actual_injected_files.append((path, contents))
            return jsonutils.dumps({'returncode': '0', 'message': 'success'})
        self.stubs.Set(stubs.FakeSessionForVMTests,
                       '_plugin_agent_inject_file', fake_inject_file)

        injected_files = [('/tmp/foo', 'foobar')]
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         injected_files=injected_files)
        self.check_vm_params_for_linux()
        self.assertEquals(actual_injected_files, injected_files)

    def test_rescue(self):
        instance = self._create_instance()
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        vm_ref = vm_utils.lookup(session, instance.name)

        swap_vdi_ref = xenapi_fake.create_vdi('swap', None)
        root_vdi_ref = xenapi_fake.create_vdi('root', None)

        xenapi_fake.create_vbd(vm_ref, swap_vdi_ref, userdevice=1)
        xenapi_fake.create_vbd(vm_ref, root_vdi_ref, userdevice=0)

        conn = xenapi_conn.XenAPIDriver(False)
        image_meta = {'id': IMAGE_VHD,
                      'disk_format': 'vhd'}
        conn.rescue(self.context, instance, [], image_meta, '')

        vm = xenapi_fake.get_record('VM', vm_ref)
        rescue_name = "%s-rescue" % vm["name_label"]
        rescue_ref = vm_utils.lookup(session, rescue_name)
        rescue_vm = xenapi_fake.get_record('VM', rescue_ref)

        vdi_uuids = []
        for vbd_uuid in rescue_vm["VBDs"]:
            vdi_uuids.append(xenapi_fake.get_record('VBD', vbd_uuid)["VDI"])
        self.assertTrue("swap" not in vdi_uuids)

    def test_unrescue(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(False)
        # Unrescue expects the original instance to be powered off
        conn.power_off(instance)
        rescue_vm = xenapi_fake.create_vm(instance.name + '-rescue', 'Running')
        conn.unrescue(instance, None)

    def test_unrescue_not_in_rescue(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(False)
        # Ensure that it will not unrescue a non-rescued instance.
        self.assertRaises(exception.InstanceNotInRescueMode, conn.unrescue,
                          instance, None)

    def test_finish_revert_migration(self):
        instance = self._create_instance()

        class VMOpsMock():

            def __init__(self):
                self.finish_revert_migration_called = False

            def finish_revert_migration(self, instance):
                self.finish_revert_migration_called = True

        conn = xenapi_conn.XenAPIDriver(False)
        conn._vmops = VMOpsMock()
        conn.finish_revert_migration(instance, None)
        self.assertTrue(conn._vmops.finish_revert_migration_called)

    def test_reboot_hard(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(False)
        conn.reboot(instance, None, "HARD")

    def test_reboot_soft(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(False)
        conn.reboot(instance, None, "SOFT")

    def test_reboot_halted(self):
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        instance = self._create_instance(spawn=False)
        conn = xenapi_conn.XenAPIDriver(False)
        xenapi_fake.create_vm(instance.name, 'Halted')
        conn.reboot(instance, None, "SOFT")
        vm_ref = vm_utils.lookup(session, instance.name)
        vm = xenapi_fake.get_record('VM', vm_ref)
        self.assertEquals(vm['power_state'], 'Running')

    def test_reboot_unknown_state(self):
        instance = self._create_instance(spawn=False)
        conn = xenapi_conn.XenAPIDriver(False)
        xenapi_fake.create_vm(instance.name, 'Unknown')
        self.assertRaises(xenapi_fake.Failure, conn.reboot, instance,
                None, "SOFT")

    def _create_instance(self, instance_id=1, spawn=True):
        """Creates and spawns a test instance."""
        instance_values = {
            'id': instance_id,
            'uuid': '00000000-0000-0000-0000-00000000000%d' % instance_id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'image_ref': 1,
            'kernel_id': 2,
            'ramdisk_id': 3,
            'root_gb': 20,
            'instance_type_id': '3',  # m1.large
            'os_type': 'linux',
            'vm_mode': 'hvm',
            'architecture': 'x86-64'}
        instance = db.instance_create(self.context, instance_values)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        image_meta = {'id': IMAGE_VHD,
                      'disk_format': 'vhd'}
        if spawn:
            self.conn.spawn(self.context, instance, image_meta, [], 'herp',
                            network_info)
        return instance


class XenAPIDiffieHellmanTestCase(test.TestCase):
    """Unit tests for Diffie-Hellman code."""
    def setUp(self):
        super(XenAPIDiffieHellmanTestCase, self).setUp()
        self.alice = agent.SimpleDH()
        self.bob = agent.SimpleDH()

    def test_shared(self):
        alice_pub = self.alice.get_public()
        bob_pub = self.bob.get_public()
        alice_shared = self.alice.compute_shared(bob_pub)
        bob_shared = self.bob.compute_shared(alice_pub)
        self.assertEquals(alice_shared, bob_shared)

    def _test_encryption(self, message):
        enc = self.alice.encrypt(message)
        self.assertFalse(enc.endswith('\n'))
        dec = self.bob.decrypt(enc)
        self.assertEquals(dec, message)

    def test_encrypt_simple_message(self):
        self._test_encryption('This is a simple message.')

    def test_encrypt_message_with_newlines_at_end(self):
        self._test_encryption('This message has a newline at the end.\n')

    def test_encrypt_many_newlines_at_end(self):
        self._test_encryption('Message with lotsa newlines.\n\n\n')

    def test_encrypt_newlines_inside_message(self):
        self._test_encryption('Message\nwith\ninterior\nnewlines.')

    def test_encrypt_with_leading_newlines(self):
        self._test_encryption('\n\nMessage with leading newlines.')

    def test_encrypt_really_long_message(self):
        self._test_encryption(''.join(['abcd' for i in xrange(1024)]))


class XenAPIMigrateInstance(stubs.XenAPITestBase):
    """Unit test for verifying migration-related actions."""

    def setUp(self):
        super(XenAPIMigrateInstance, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        db_fakes.stub_out_db_instance_api(self.stubs)
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': None,
                  'ramdisk_id': None,
                  'root_gb': 5,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        migration_values = {
            'source_compute': 'nova-compute',
            'dest_compute': 'nova-compute',
            'dest_host': '10.127.5.114',
            'status': 'post-migrating',
            'instance_uuid': '15f23e6a-cc6e-4d22-b651-d9bdaac316f7',
            'old_instance_type_id': 5,
            'new_instance_type_id': 1
        }
        self.migration = db.migration_create(
            context.get_admin_context(), migration_values)

        fake_utils.stub_out_utils_execute(self.stubs)
        stubs.stub_out_migration_methods(self.stubs)
        stubs.stubout_get_this_vm_uuid(self.stubs)

        def fake_inject_instance_metadata(self, instance, vm):
            pass
        self.stubs.Set(vmops.VMOps, 'inject_instance_metadata',
                       fake_inject_instance_metadata)

    def test_resize_xenserver_6(self):
        instance = db.instance_create(self.context, self.instance_values)
        called = {'resize': False}

        def fake_vdi_resize(*args, **kwargs):
            called['resize'] = True

        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize", fake_vdi_resize)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests,
                              product_version=(6, 0, 0),
                              product_brand='XenServer')
        conn = xenapi_conn.XenAPIDriver(False)
        vdi_ref = xenapi_fake.create_vdi('hurr', 'fake')
        vdi_uuid = xenapi_fake.get_record('VDI', vdi_ref)['uuid']
        conn._vmops._resize_instance(instance,
                                     {'uuid': vdi_uuid, 'ref': vdi_ref})
        self.assertEqual(called['resize'], True)

    def test_resize_xcp(self):
        instance = db.instance_create(self.context, self.instance_values)
        called = {'resize': False}

        def fake_vdi_resize(*args, **kwargs):
            called['resize'] = True

        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize", fake_vdi_resize)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests,
                              product_version=(1, 4, 99),
                              product_brand='XCP')
        conn = xenapi_conn.XenAPIDriver(False)
        vdi_ref = xenapi_fake.create_vdi('hurr', 'fake')
        vdi_uuid = xenapi_fake.get_record('VDI', vdi_ref)['uuid']
        conn._vmops._resize_instance(instance,
                                     {'uuid': vdi_uuid, 'ref': vdi_ref})
        self.assertEqual(called['resize'], True)

    def test_migrate_disk_and_power_off(self):
        instance = db.instance_create(self.context, self.instance_values)
        xenapi_fake.create_vm(instance.name, 'Running')
        instance_type = db.instance_type_get_by_name(self.context, 'm1.large')
        conn = xenapi_conn.XenAPIDriver(False)
        conn.migrate_disk_and_power_off(self.context, instance,
                                        '127.0.0.1', instance_type, None)

    def test_migrate_disk_and_power_off_passes_exceptions(self):
        instance = db.instance_create(self.context, self.instance_values)
        xenapi_fake.create_vm(instance.name, 'Running')
        instance_type = db.instance_type_get_by_name(self.context, 'm1.large')

        def fake_raise(*args, **kwargs):
            raise exception.MigrationError(reason='test failure')
        self.stubs.Set(vmops.VMOps, "_migrate_vhd", fake_raise)

        conn = xenapi_conn.XenAPIDriver(False)
        self.assertRaises(exception.MigrationError,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          '127.0.0.1', instance_type, None)

    def test_revert_migrate(self):
        instance = db.instance_create(self.context, self.instance_values)
        self.called = False
        self.fake_vm_start_called = False
        self.fake_finish_revert_migration_called = False

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        def fake_finish_revert_migration(*args, **kwargs):
            self.fake_finish_revert_migration_called = True

        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize_online", fake_vdi_resize)
        self.stubs.Set(vmops.VMOps, '_start', fake_vm_start)
        self.stubs.Set(vmops.VMOps, 'finish_revert_migration',
                       fake_finish_revert_migration)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests,
                              product_version=(4, 0, 0),
                              product_brand='XenServer')

        conn = xenapi_conn.XenAPIDriver(False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        base = xenapi_fake.create_vdi('hurr', 'fake')
        base_uuid = xenapi_fake.get_record('VDI', base)['uuid']
        cow = xenapi_fake.create_vdi('durr', 'fake')
        cow_uuid = xenapi_fake.get_record('VDI', cow)['uuid']
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy=base_uuid, cow=cow_uuid),
                              network_info, image_meta, resize_instance=True)
        self.assertEqual(self.called, True)
        self.assertEqual(self.fake_vm_start_called, True)

        conn.finish_revert_migration(instance, network_info)
        self.assertEqual(self.fake_finish_revert_migration_called, True)

    def test_finish_migrate(self):
        instance = db.instance_create(self.context, self.instance_values)
        self.called = False
        self.fake_vm_start_called = False

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        self.stubs.Set(vmops.VMOps, '_start', fake_vm_start)
        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize_online", fake_vdi_resize)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests,
                              product_version=(4, 0, 0),
                              product_brand='XenServer')

        conn = xenapi_conn.XenAPIDriver(False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)
        self.assertEqual(self.called, True)
        self.assertEqual(self.fake_vm_start_called, True)

    def test_finish_migrate_no_local_storage(self):
        tiny_type = instance_types.get_instance_type_by_name('m1.tiny')
        tiny_type_id = tiny_type['id']
        self.instance_values.update({'instance_type_id': tiny_type_id,
                                     'root_gb': 0})
        instance = db.instance_create(self.context, self.instance_values)

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize_online", fake_vdi_resize)
        conn = xenapi_conn.XenAPIDriver(False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)

    def test_finish_migrate_no_resize_vdi(self):
        instance = db.instance_create(self.context, self.instance_values)

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stubs.Set(stubs.FakeSessionForVMTests,
                       "VDI_resize_online", fake_vdi_resize)
        conn = xenapi_conn.XenAPIDriver(False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        # Resize instance would be determined by the compute call
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=False)


class XenAPIImageTypeTestCase(test.TestCase):
    """Test ImageType class."""

    def test_to_string(self):
        """Can convert from type id to type string."""
        self.assertEquals(
            vm_utils.ImageType.to_string(vm_utils.ImageType.KERNEL),
            vm_utils.ImageType.KERNEL_STR)

    def _assert_role(self, expected_role, image_type_id):
        self.assertEquals(
            expected_role,
            vm_utils.ImageType.get_role(image_type_id))

    def test_get_image_role_kernel(self):
        self._assert_role('kernel', vm_utils.ImageType.KERNEL)

    def test_get_image_role_ramdisk(self):
        self._assert_role('ramdisk', vm_utils.ImageType.RAMDISK)

    def test_get_image_role_disk(self):
        self._assert_role('root', vm_utils.ImageType.DISK)

    def test_get_image_role_disk_raw(self):
        self._assert_role('root', vm_utils.ImageType.DISK_RAW)

    def test_get_image_role_disk_vhd(self):
        self._assert_role('root', vm_utils.ImageType.DISK_VHD)


class XenAPIDetermineDiskImageTestCase(test.TestCase):
    """Unit tests for code that detects the ImageType."""
    def assert_disk_type(self, image_meta, expected_disk_type):
        actual = vm_utils.determine_disk_image_type(image_meta)
        self.assertEqual(expected_disk_type, actual)

    def test_machine(self):
        image_meta = {'id': 'a', 'disk_format': 'ami'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK)

    def test_raw(self):
        image_meta = {'id': 'a', 'disk_format': 'raw'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_RAW)

    def test_vhd(self):
        image_meta = {'id': 'a', 'disk_format': 'vhd'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_VHD)


class CompareVersionTestCase(test.TestCase):
    def test_less_than(self):
        """Test that cmp_version compares a as less than b"""
        self.assertTrue(vmops.cmp_version('1.2.3.4', '1.2.3.5') < 0)

    def test_greater_than(self):
        """Test that cmp_version compares a as greater than b"""
        self.assertTrue(vmops.cmp_version('1.2.3.5', '1.2.3.4') > 0)

    def test_equal(self):
        """Test that cmp_version compares a as equal to b"""
        self.assertTrue(vmops.cmp_version('1.2.3.4', '1.2.3.4') == 0)

    def test_non_lexical(self):
        """Test that cmp_version compares non-lexically"""
        self.assertTrue(vmops.cmp_version('1.2.3.10', '1.2.3.4') > 0)

    def test_length(self):
        """Test that cmp_version compares by length as last resort"""
        self.assertTrue(vmops.cmp_version('1.2.3', '1.2.3.4') < 0)


class XenAPIHostTestCase(stubs.XenAPITestBase):
    """Tests HostState, which holds metrics from XenServer that get
    reported back to the Schedulers."""

    def setUp(self):
        super(XenAPIHostTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        xenapi_fake.create_local_srs()
        self.conn = xenapi_conn.XenAPIDriver(False)

    def test_host_state(self):
        stats = self.conn.get_host_stats()
        self.assertEquals(stats['disk_total'], 40000)
        self.assertEquals(stats['disk_used'], 20000)
        self.assertEquals(stats['host_memory_total'], 10)
        self.assertEquals(stats['host_memory_overhead'], 20)
        self.assertEquals(stats['host_memory_free'], 30)
        self.assertEquals(stats['host_memory_free_computed'], 40)

    def _test_host_action(self, method, action, expected=None):
        result = method('host', action)
        if not expected:
            expected = action
        self.assertEqual(result, expected)

    def test_host_reboot(self):
        self._test_host_action(self.conn.host_power_action, 'reboot')

    def test_host_shutdown(self):
        self._test_host_action(self.conn.host_power_action, 'shutdown')

    def test_host_startup(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_power_action, 'host', 'startup')

    def test_host_maintenance_on(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               True, 'on_maintenance')

    def test_host_maintenance_off(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               False, 'off_maintenance')

    def test_set_enable_host_enable(self):
        self._test_host_action(self.conn.set_host_enabled, True, 'enabled')

    def test_set_enable_host_disable(self):
        self._test_host_action(self.conn.set_host_enabled, False, 'disabled')

    def test_get_host_uptime(self):
        result = self.conn.get_host_uptime('host')
        self.assertEqual(result, 'fake uptime')

    def test_supported_instances_is_included_in_host_state(self):
        stats = self.conn.get_host_stats()
        self.assertTrue('supported_instances' in stats)

    def test_supported_instances_is_calculated_by_to_supported_instances(self):

        def to_supported_instances(somedata):
            self.assertEquals(None, somedata)
            return "SOMERETURNVALUE"
        self.stubs.Set(host, 'to_supported_instances', to_supported_instances)

        stats = self.conn.get_host_stats()
        self.assertEquals("SOMERETURNVALUE", stats['supported_instances'])


class ToSupportedInstancesTestCase(test.TestCase):
    def test_default_return_value(self):
        self.assertEquals([],
            host.to_supported_instances(None))

    def test_return_value(self):
        self.assertEquals([('x86_64', 'xapi', 'xen')],
             host.to_supported_instances([u'xen-3.0-x86_64']))

    def test_invalid_values_do_not_break(self):
        self.assertEquals([('x86_64', 'xapi', 'xen')],
             host.to_supported_instances([u'xen-3.0-x86_64', 'spam']))

    def test_multiple_values(self):
        self.assertEquals(
            [
                ('x86_64', 'xapi', 'xen'),
                ('x86_32', 'xapi', 'hvm')
            ],
            host.to_supported_instances([u'xen-3.0-x86_64', 'hvm-3.0-x86_32'])
        )


class XenAPIAutoDiskConfigTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(XenAPIAutoDiskConfigTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        def fake_create_vbd(session, vm_ref, vdi_ref, userdevice,
                            vbd_type='disk', read_only=False, bootable=True):
            pass

        self.stubs.Set(vm_utils, 'create_vbd', fake_create_vbd)

    def assertIsPartitionCalled(self, called):
        marker = {"partition_called": False}

        def fake_resize_part_and_fs(dev, start, old, new):
            marker["partition_called"] = True
        self.stubs.Set(vm_utils, "_resize_part_and_fs",
                       fake_resize_part_and_fs)

        ctx = context.RequestContext(self.user_id, self.project_id)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')

        disk_image_type = vm_utils.ImageType.DISK_VHD
        instance = db.instance_create(self.context, self.instance_values)
        vm_ref = xenapi_fake.create_vm(instance['name'], 'Halted')
        vdi_ref = xenapi_fake.create_vdi(instance['name'], 'fake')

        vdi_uuid = session.call_xenapi('VDI.get_record', vdi_ref)['uuid']
        vdis = {'root': {'uuid': vdi_uuid, 'ref': vdi_ref}}

        self.conn._vmops._attach_disks(instance, vm_ref, instance['name'],
                                       disk_image_type, vdis)

        self.assertEqual(marker["partition_called"], called)

    def test_instance_not_auto_disk_config(self):
        """Should not partition unless instance is marked as
        auto_disk_config.
        """
        self.instance_values['auto_disk_config'] = False
        self.assertIsPartitionCalled(False)

    @stub_vm_utils_with_vdi_attached_here
    def test_instance_auto_disk_config_doesnt_pass_fail_safes(self):
        """Should not partition unless fail safes pass"""
        self.instance_values['auto_disk_config'] = True

        def fake_get_partitions(dev):
            return [(1, 0, 100, 'ext4'), (2, 100, 200, 'ext4')]
        self.stubs.Set(vm_utils, "_get_partitions",
                       fake_get_partitions)

        self.assertIsPartitionCalled(False)

    @stub_vm_utils_with_vdi_attached_here
    def test_instance_auto_disk_config_passes_fail_safes(self):
        """Should partition if instance is marked as auto_disk_config=True and
        virt-layer specific fail-safe checks pass.
        """
        self.instance_values['auto_disk_config'] = True

        def fake_get_partitions(dev):
            return [(1, 0, 100, 'ext4')]
        self.stubs.Set(vm_utils, "_get_partitions",
                       fake_get_partitions)

        self.assertIsPartitionCalled(True)


class XenAPIGenerateLocal(stubs.XenAPITestBase):
    """Test generating of local disks, like swap and ephemeral"""
    def setUp(self):
        super(XenAPIGenerateLocal, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   xenapi_generate_swap=True,
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        db_fakes.stub_out_db_instance_api(self.stubs)
        self.conn = xenapi_conn.XenAPIDriver(False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        def fake_create_vbd(session, vm_ref, vdi_ref, userdevice,
                            vbd_type='disk', read_only=False, bootable=True):
            pass

        self.stubs.Set(vm_utils, 'create_vbd', fake_create_vbd)

    def assertCalled(self, instance):
        ctx = context.RequestContext(self.user_id, self.project_id)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')

        disk_image_type = vm_utils.ImageType.DISK_VHD
        vm_ref = xenapi_fake.create_vm(instance['name'], 'Halted')
        vdi_ref = xenapi_fake.create_vdi(instance['name'], 'fake')

        vdi_uuid = session.call_xenapi('VDI.get_record', vdi_ref)['uuid']
        vdis = {'root': {'uuid': vdi_uuid, 'ref': vdi_ref}}

        self.called = False
        self.conn._vmops._attach_disks(instance, vm_ref, instance['name'],
                                       disk_image_type, vdis)
        self.assertTrue(self.called)

    def test_generate_swap(self):
        """Test swap disk generation."""
        instance = db.instance_create(self.context, self.instance_values)
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'instance_type_id': 5})

        def fake_generate_swap(*args, **kwargs):
            self.called = True
        self.stubs.Set(vm_utils, 'generate_swap', fake_generate_swap)

        self.assertCalled(instance)

    def test_generate_ephemeral(self):
        """Test ephemeral disk generation."""
        instance = db.instance_create(self.context, self.instance_values)
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'instance_type_id': 4})

        def fake_generate_ephemeral(*args):
            self.called = True
        self.stubs.Set(vm_utils, 'generate_ephemeral', fake_generate_ephemeral)

        self.assertCalled(instance)


class XenAPIBWUsageTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(XenAPIBWUsageTestCase, self).setUp()
        self.stubs.Set(vm_utils, 'compile_metrics',
                       XenAPIBWUsageTestCase._fake_compile_metrics)
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

    @classmethod
    def _fake_compile_metrics(cls, start_time, stop_time=None):
        raise exception.CouldNotFetchMetrics()

    def test_get_all_bw_usage_in_failure_case(self):
        """Test that get_all_bw_usage returns an empty list when metrics
        compilation failed.  c.f. bug #910045.
        """
        class testinstance(object):
            def __init__(self):
                self.name = "instance-0001"
                self.uuid = "1-2-3-4-5"

        result = self.conn.get_all_bw_usage([testinstance()],
                                            timeutils.utcnow())
        self.assertEqual(result, [])


# TODO(salvatore-orlando): this class and
# nova.tests.test_libvirt.IPTablesFirewallDriverTestCase share a lot of code.
# Consider abstracting common code in a base class for firewall driver testing.
class XenAPIDom0IptablesFirewallTestCase(stubs.XenAPITestBase):

    _in_nat_rules = [
      '# Generated by iptables-save v1.4.10 on Sat Feb 19 00:03:19 2011',
      '*nat',
      ':PREROUTING ACCEPT [1170:189210]',
      ':INPUT ACCEPT [844:71028]',
      ':OUTPUT ACCEPT [5149:405186]',
      ':POSTROUTING ACCEPT [5063:386098]',
    ]

    _in_filter_rules = [
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*filter',
      ':INPUT ACCEPT [969615:281627771]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [915599:63811649]',
      ':nova-block-ipv4 - [0:0]',
      '[0:0] -A INPUT -i virbr0 -p tcp -m tcp --dport 67 -j ACCEPT ',
      '[0:0] -A FORWARD -d 192.168.122.0/24 -o virbr0 -m state --state RELATED'
      ',ESTABLISHED -j ACCEPT ',
      '[0:0] -A FORWARD -s 192.168.122.0/24 -i virbr0 -j ACCEPT ',
      '[0:0] -A FORWARD -i virbr0 -o virbr0 -j ACCEPT ',
      '[0:0] -A FORWARD -o virbr0 -j REJECT '
      '--reject-with icmp-port-unreachable ',
      '[0:0] -A FORWARD -i virbr0 -j REJECT '
      '--reject-with icmp-port-unreachable ',
      'COMMIT',
      '# Completed on Mon Dec  6 11:54:13 2010',
    ]

    _in6_filter_rules = [
      '# Generated by ip6tables-save v1.4.4 on Tue Jan 18 23:47:56 2011',
      '*filter',
      ':INPUT ACCEPT [349155:75810423]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [349256:75777230]',
      'COMMIT',
      '# Completed on Tue Jan 18 23:47:56 2011',
    ]

    def setUp(self):
        super(XenAPIDom0IptablesFirewallTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        xenapi_fake.create_local_srs()
        xenapi_fake.create_local_pifs()
        self.user_id = 'mappin'
        self.project_id = 'fake'
        stubs.stubout_session(self.stubs, stubs.FakeSessionForFirewallTests,
                              test_case=self)
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.network = importutils.import_object(FLAGS.network_manager)
        self.conn = xenapi_conn.XenAPIDriver(False)
        self.fw = self.conn._vmops.firewall_driver

    def _create_instance_ref(self):
        return db.instance_create(self.context,
                                  {'user_id': self.user_id,
                                   'project_id': self.project_id,
                                   'instance_type_id': 1})

    def _create_test_security_group(self):
        admin_ctxt = context.get_admin_context()
        secgroup = db.security_group_create(admin_ctxt,
                                {'user_id': self.user_id,
                                 'project_id': self.project_id,
                                 'name': 'testgroup',
                                 'description': 'test group'})
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': -1,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': 8,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'cidr': '192.168.10.0/24'})
        return secgroup

    def _validate_security_group(self):
        in_rules = filter(lambda l: not l.startswith('#'),
                          self._in_filter_rules)
        for rule in in_rules:
            if not 'nova' in rule:
                self.assertTrue(rule in self._out_rules,
                                'Rule went missing: %s' % rule)

        instance_chain = None
        for rule in self._out_rules:
            # This is pretty crude, but it'll do for now
            # last two octets change
            if re.search('-d 192.168.[0-9]{1,3}.[0-9]{1,3} -j', rule):
                instance_chain = rule.split(' ')[-1]
                break
        self.assertTrue(instance_chain, "The instance chain wasn't added")
        security_group_chain = None
        for rule in self._out_rules:
            # This is pretty crude, but it'll do for now
            if '-A %s -j' % instance_chain in rule:
                security_group_chain = rule.split(' ')[-1]
                break
        self.assertTrue(security_group_chain,
                        "The security group chain wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p icmp'
                           ' -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "ICMP acceptance rule wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p icmp -m icmp'
                           ' --icmp-type 8 -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "ICMP Echo Request acceptance rule wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p tcp --dport 80:81'
                           ' -s 192.168.10.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")

    def test_static_filters(self):
        instance_ref = self._create_instance_ref()
        src_instance_ref = self._create_instance_ref()
        admin_ctxt = context.get_admin_context()
        secgroup = self._create_test_security_group()

        src_secgroup = db.security_group_create(admin_ctxt,
                                                {'user_id': self.user_id,
                                                 'project_id': self.project_id,
                                                 'name': 'testsourcegroup',
                                                 'description': 'src group'})
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'group_id': src_secgroup['id']})

        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        db.instance_add_security_group(admin_ctxt, src_instance_ref['uuid'],
                                       src_secgroup['id'])
        instance_ref = db.instance_get(admin_ctxt, instance_ref['id'])
        src_instance_ref = db.instance_get(admin_ctxt, src_instance_ref['id'])

        network_model = fake_network.fake_get_instance_nw_info(self.stubs,
                                                      1, spectacular=True)

        from nova.compute import utils as compute_utils
        self.stubs.Set(compute_utils, 'get_nw_info_for_instance',
                       lambda instance: network_model)

        network_info = network_model.legacy()
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)

        self._validate_security_group()
        # Extra test for TCP acceptance rules
        for ip in network_model.fixed_ips():
            if ip['version'] != 4:
                continue
            regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p tcp'
                               ' --dport 80:81 -s %s' % ip['address'])
            self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                            "TCP port 80/81 acceptance rule wasn't added")

        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_filters_for_instance_with_ip_v6(self):
        self.flags(use_ipv6=True)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 1)

    def test_filters_for_instance_without_ip_v6(self):
        self.flags(use_ipv6=False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 0)

    def test_multinic_iptables(self):
        ipv4_rules_per_addr = 1
        ipv4_addr_per_network = 2
        ipv6_rules_per_addr = 1
        ipv6_addr_per_network = 1
        networks_count = 5
        instance_ref = self._create_instance_ref()
        _get_instance_nw_info = fake_network.fake_get_instance_nw_info
        network_info = _get_instance_nw_info(self.stubs,
                                             networks_count,
                                             ipv4_addr_per_network)
        ipv4_len = len(self.fw.iptables.ipv4['filter'].rules)
        ipv6_len = len(self.fw.iptables.ipv6['filter'].rules)
        inst_ipv4, inst_ipv6 = self.fw.instance_rules(instance_ref,
                                                      network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        ipv4 = self.fw.iptables.ipv4['filter'].rules
        ipv6 = self.fw.iptables.ipv6['filter'].rules
        ipv4_network_rules = len(ipv4) - len(inst_ipv4) - ipv4_len
        ipv6_network_rules = len(ipv6) - len(inst_ipv6) - ipv6_len
        # Extra rules are for the DHCP request
        rules = (ipv4_rules_per_addr * ipv4_addr_per_network *
                 networks_count) + 2
        self.assertEquals(ipv4_network_rules, rules)
        self.assertEquals(ipv6_network_rules,
                  ipv6_rules_per_addr * ipv6_addr_per_network * networks_count)

    def test_do_refresh_security_group_rules(self):
        admin_ctxt = context.get_admin_context()
        instance_ref = self._create_instance_ref()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)
        secgroup = self._create_test_security_group()
        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.instances[instance_ref['id']] = instance_ref
        self._validate_security_group()
        # add a rule to the security group
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'udp',
                                       'from_port': 200,
                                       'to_port': 299,
                                       'cidr': '192.168.99.0/24'})
        #validate the extra rule
        self.fw.refresh_security_group_rules(secgroup)
        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p udp --dport 200:299'
                           ' -s 192.168.99.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "Rules were not updated properly."
                        "The rule for UDP acceptance is missing")

    def test_provider_firewall_rules(self):
        # setup basic instance data
        instance_ref = self._create_instance_ref()
        # FRAGILE: as in libvirt tests
        # peeks at how the firewall names chains
        chain_name = 'inst-%s' % instance_ref['id']

        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.assertTrue('provider' in self.fw.iptables.ipv4['filter'].chains)
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(0, len(rules))

        admin_ctxt = context.get_admin_context()
        # add a rule and send the update message, check for 1 rule
        provider_fw0 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'tcp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))

        # Add another, refresh, and make sure number of rules goes to two
        provider_fw1 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'udp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(2, len(rules))

        # create the instance filter and make sure it has a jump rule
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)
        inst_rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                           if rule.chain == chain_name]
        jump_rules = [rule for rule in inst_rules if '-j' in rule.rule]
        provjump_rules = []
        # IptablesTable doesn't make rules unique internally
        for rule in jump_rules:
            if 'provider' in rule.rule and rule not in provjump_rules:
                provjump_rules.append(rule)
        self.assertEqual(1, len(provjump_rules))

        # remove a rule from the db, cast to compute to refresh rule
        db.provider_fw_rule_destroy(admin_ctxt, provider_fw1['id'])
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))


class XenAPISRSelectionTestCase(stubs.XenAPITestBase):
    """Unit tests for testing we find the right SR."""
    def test_safe_find_sr_raise_exception(self):
        """Ensure StorageRepositoryNotFound is raise when wrong filter."""
        self.flags(sr_matching_filter='yadayadayada')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        self.assertRaises(exception.StorageRepositoryNotFound,
                          vm_utils.safe_find_sr, session)

    def test_safe_find_sr_local_storage(self):
        """Ensure the default local-storage is found."""
        self.flags(sr_matching_filter='other-config:i18n-key=local-storage')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        host_ref = xenapi_fake.get_all('host')[0]
        local_sr = xenapi_fake.create_sr(
                              name_label='Fake Storage',
                              type='lvm',
                              other_config={'i18n-original-value-name_label':
                                            'Local storage',
                                            'i18n-key': 'local-storage'},
                              host_ref=host_ref)
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_by_other_criteria(self):
        """Ensure the SR is found when using a different filter."""
        self.flags(sr_matching_filter='other-config:my_fake_sr=true')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        host_ref = xenapi_fake.get_all('host')[0]
        local_sr = xenapi_fake.create_sr(name_label='Fake Storage',
                                         type='lvm',
                                         other_config={'my_fake_sr': 'true'},
                                         host_ref=host_ref)
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_default(self):
        """Ensure the default SR is found regardless of other-config."""
        self.flags(sr_matching_filter='default-sr:true')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        pool_ref = xenapi_fake.create_pool('')
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(session.call_xenapi('pool.get_default_SR', pool_ref),
                         expected)


def _create_service_entries(context, values={'avail_zone1': ['fake_host1',
                                                         'fake_host2'],
                                         'avail_zone2': ['fake_host3'], }):
    for avail_zone, hosts in values.iteritems():
        for host in hosts:
            db.service_create(context,
                              {'host': host,
                               'binary': 'nova-compute',
                               'topic': 'compute',
                               'report_count': 0,
                               'availability_zone': avail_zone})
    return values


class XenAPIAggregateTestCase(stubs.XenAPITestBase):
    """Unit tests for aggregate operations."""
    def setUp(self):
        super(XenAPIAggregateTestCase, self).setUp()
        self.flags(xenapi_connection_url='http://test_url',
                   xenapi_connection_username='test_user',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   host='host',
                   connection_type='xenapi',
                   compute_driver='nova.virt.xenapi.driver.XenAPIDriver')
        host_ref = xenapi_fake.get_all('host')[0]
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.context = context.get_admin_context()
        self.conn = xenapi_conn.XenAPIDriver(False)
        self.compute = importutils.import_object(FLAGS.compute_manager)
        self.api = compute_api.AggregateAPI()
        values = {'name': 'test_aggr',
                  'availability_zone': 'test_zone',
                  'metadata': {pool_states.POOL_FLAG: 'XenAPI'}}
        self.aggr = db.aggregate_create(self.context, values)
        self.fake_metadata = {pool_states.POOL_FLAG: 'XenAPI',
                              'master_compute': 'host',
                              pool_states.KEY: pool_states.ACTIVE,
                              'host': xenapi_fake.get_record('host',
                                                             host_ref)['uuid']}

    def test_pool_add_to_aggregate_called_by_driver(self):

        calls = []

        def pool_add_to_aggregate(context, aggregate, host, slave_info=None):
            self.assertEquals("CONTEXT", context)
            self.assertEquals("AGGREGATE", aggregate)
            self.assertEquals("HOST", host)
            self.assertEquals("SLAVEINFO", slave_info)
            calls.append(pool_add_to_aggregate)
        self.stubs.Set(self.conn._pool,
                       "add_to_aggregate",
                       pool_add_to_aggregate)

        self.conn.add_to_aggregate("CONTEXT", "AGGREGATE", "HOST",
                                   slave_info="SLAVEINFO")

        self.assertTrue(pool_add_to_aggregate in calls)

    def test_pool_remove_from_aggregate_called_by_driver(self):

        calls = []

        def pool_remove_from_aggregate(context, aggregate, host,
                                       slave_info=None):
            self.assertEquals("CONTEXT", context)
            self.assertEquals("AGGREGATE", aggregate)
            self.assertEquals("HOST", host)
            self.assertEquals("SLAVEINFO", slave_info)
            calls.append(pool_remove_from_aggregate)
        self.stubs.Set(self.conn._pool,
                       "remove_from_aggregate",
                       pool_remove_from_aggregate)

        self.conn.remove_from_aggregate("CONTEXT", "AGGREGATE", "HOST",
                                        slave_info="SLAVEINFO")

        self.assertTrue(pool_remove_from_aggregate in calls)

    def test_add_to_aggregate_for_first_host_sets_metadata(self):
        def fake_init_pool(id, name):
            fake_init_pool.called = True
        self.stubs.Set(self.conn._pool, "_init_pool", fake_init_pool)

        aggregate = self._aggregate_setup()
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        result = db.aggregate_get(self.context, aggregate.id)
        self.assertTrue(fake_init_pool.called)
        self.assertDictMatch(self.fake_metadata, result.metadetails)

    def test_join_slave(self):
        """Ensure join_slave gets called when the request gets to master."""
        def fake_join_slave(id, compute_uuid, host, url, user, password):
            fake_join_slave.called = True
        self.stubs.Set(self.conn._pool, "_join_slave", fake_join_slave)

        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host2",
                                         dict(compute_uuid='fake_uuid',
                                         url='fake_url',
                                         user='fake_user',
                                         passwd='fake_pass',
                                         xenhost_uuid='fake_uuid'))
        self.assertTrue(fake_join_slave.called)

    def test_add_to_aggregate_first_host(self):
        def fake_pool_set_name_label(self, session, pool_ref, name):
            fake_pool_set_name_label.called = True
        self.stubs.Set(xenapi_fake.SessionBase, "pool_set_name_label",
                       fake_pool_set_name_label)
        self.conn._session.call_xenapi("pool.create", {"name": "asdf"})

        values = {"name": 'fake_aggregate',
                  "availability_zone": 'fake_zone'}
        result = db.aggregate_create(self.context, values)
        metadata = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.CREATED}
        db.aggregate_metadata_add(self.context, result.id, metadata)

        db.aggregate_host_add(self.context, result.id, "host")
        aggregate = db.aggregate_get(self.context, result.id)
        self.assertEqual(["host"], aggregate.hosts)
        self.assertEqual(metadata, aggregate.metadetails)

        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        self.assertTrue(fake_pool_set_name_label.called)

    def test_remove_from_aggregate_called(self):
        def fake_remove_from_aggregate(context, aggregate, host):
            fake_remove_from_aggregate.called = True
        self.stubs.Set(self.conn._pool,
                       "remove_from_aggregate",
                       fake_remove_from_aggregate)

        self.conn.remove_from_aggregate(None, None, None)
        self.assertTrue(fake_remove_from_aggregate.called)

    def test_remove_from_empty_aggregate(self):
        result = self._aggregate_setup()
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn._pool.remove_from_aggregate,
                          self.context, result, "test_host")

    def test_remove_slave(self):
        """Ensure eject slave gets called."""
        def fake_eject_slave(id, compute_uuid, host_uuid):
            fake_eject_slave.called = True
        self.stubs.Set(self.conn._pool, "_eject_slave", fake_eject_slave)

        self.fake_metadata['host2'] = 'fake_host2_uuid'
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                metadata=self.fake_metadata, aggr_state=pool_states.ACTIVE)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host2")
        self.assertTrue(fake_eject_slave.called)

    def test_remove_master_solo(self):
        """Ensure metadata are cleared after removal."""
        def fake_clear_pool(id):
            fake_clear_pool.called = True
        self.stubs.Set(self.conn._pool, "_clear_pool", fake_clear_pool)

        aggregate = self._aggregate_setup(metadata=self.fake_metadata)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host")
        result = db.aggregate_get(self.context, aggregate.id)
        self.assertTrue(fake_clear_pool.called)
        self.assertDictMatch({pool_states.POOL_FLAG: 'XenAPI',
                pool_states.KEY: pool_states.ACTIVE}, result.metadetails)

    def test_remote_master_non_empty_pool(self):
        """Ensure AggregateError is raised if removing the master."""
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)

        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn._pool.remove_from_aggregate,
                          self.context, aggregate, "host")

    def _aggregate_setup(self, aggr_name='fake_aggregate',
                         aggr_zone='fake_zone',
                         aggr_state=pool_states.CREATED,
                         hosts=['host'], metadata=None):
        values = {"name": aggr_name,
                  "availability_zone": aggr_zone}
        result = db.aggregate_create(self.context, values)
        pool_flag = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: aggr_state}
        db.aggregate_metadata_add(self.context, result.id, pool_flag)

        for host in hosts:
            db.aggregate_host_add(self.context, result.id, host)
        if metadata:
            db.aggregate_metadata_add(self.context, result.id, metadata)
        return db.aggregate_get(self.context, result.id)

    def test_add_host_to_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateAction is raised when adding host while
        aggregate is not ready."""
        aggregate = self._aggregate_setup(aggr_state=pool_states.CHANGING)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn.add_to_aggregate, self.context,
                          aggregate, 'host')

    def test_add_host_to_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        deleted."""
        aggregate = self._aggregate_setup(aggr_state=pool_states.DISMISSED)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn.add_to_aggregate, self.context,
                          aggregate, 'fake_host')

    def test_add_host_to_aggregate_invalid_error_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        in error."""
        aggregate = self._aggregate_setup(aggr_state=pool_states.ERROR)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn.add_to_aggregate, self.context,
                          aggregate, 'fake_host')

    def test_remove_host_from_aggregate_error(self):
        """Ensure we can remove a host from an aggregate even if in error."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        # let's mock the fact that the aggregate is ready!
        metadata = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.ACTIVE}
        db.aggregate_metadata_add(self.context, aggr['id'], metadata)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        # let's mock the fact that the aggregate is in error!
        status = {'operational_state': pool_states.ERROR}
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr['id'],
                                                       values[fake_zone][0])
        self.assertEqual(len(aggr['hosts']) - 1, len(expected['hosts']))
        self.assertEqual(expected['metadata'][pool_states.KEY],
                         pool_states.ACTIVE)

    def test_remove_host_from_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        deleted."""
        aggregate = self._aggregate_setup(aggr_state=pool_states.DISMISSED)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn.remove_from_aggregate, self.context,
                          aggregate, 'fake_host')

    def test_remove_host_from_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        changing."""
        aggregate = self._aggregate_setup(aggr_state=pool_states.CHANGING)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn.remove_from_aggregate, self.context,
                          aggregate, 'fake_host')

    def test_add_aggregate_host_raise_err(self):
        """Ensure the undo operation works correctly on add."""
        def fake_driver_add_to_aggregate(context, aggregate, host, **_ignore):
            raise exception.AggregateError
        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       fake_driver_add_to_aggregate)
        metadata = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.ACTIVE}
        db.aggregate_metadata_add(self.context, self.aggr.id, metadata)
        db.aggregate_host_add(self.context, self.aggr.id, 'fake_host')

        self.assertRaises(exception.AggregateError,
                          self.compute.add_aggregate_host,
                          self.context, self.aggr.id, "fake_host")
        excepted = db.aggregate_get(self.context, self.aggr.id)
        self.assertEqual(excepted.metadetails[pool_states.KEY],
                pool_states.ERROR)
        self.assertEqual(excepted.hosts, [])


class Aggregate(object):
    def __init__(self, id=None, hosts=None):
        self.id = id
        self.hosts = hosts or []


class MockComputeAPI(object):
    def __init__(self):
        self._mock_calls = []

    def add_aggregate_host(self, ctxt, aggregate_id,
                                     host_param, host, slave_info):
        self._mock_calls.append((
            self.add_aggregate_host, ctxt, aggregate_id,
            host_param, host, slave_info))

    def remove_aggregate_host(self, ctxt, aggregate_id, host_param,
                              host, slave_info):
        self._mock_calls.append((
            self.remove_aggregate_host, ctxt, aggregate_id,
            host_param, host, slave_info))


class StubDependencies(object):
    """Stub dependencies for ResourcePool"""

    def __init__(self):
        self.compute_rpcapi = MockComputeAPI()

    def _is_hv_pool(self, *_ignore):
        return True

    def _get_metadata(self, *_ignore):
        return {
            pool_states.KEY: {},
            'master_compute': 'master'
        }

    def _create_slave_info(self, *ignore):
        return "SLAVE_INFO"


class ResourcePoolWithStubs(StubDependencies, pool.ResourcePool):
    """ A ResourcePool, use stub dependencies """


class HypervisorPoolTestCase(test.TestCase):

    def test_slave_asks_master_to_add_slave_to_pool(self):
        slave = ResourcePoolWithStubs()
        aggregate = Aggregate(id=98, hosts=[])

        slave.add_to_aggregate("CONTEXT", aggregate, "slave")

        self.assertIn(
            (slave.compute_rpcapi.add_aggregate_host,
            "CONTEXT", 98, "slave", "master", "SLAVE_INFO"),
            slave.compute_rpcapi._mock_calls)

    def test_slave_asks_master_to_remove_slave_from_pool(self):
        slave = ResourcePoolWithStubs()
        aggregate = Aggregate(id=98, hosts=[])

        slave.remove_from_aggregate("CONTEXT", aggregate, "slave")

        self.assertIn(
            (slave.compute_rpcapi.remove_aggregate_host,
            "CONTEXT", 98, "slave", "master", "SLAVE_INFO"),
            slave.compute_rpcapi._mock_calls)


class SwapXapiHostTestCase(test.TestCase):

    def test_swapping(self):
        self.assertEquals(
            "http://otherserver:8765/somepath",
            pool.swap_xapi_host(
                "http://someserver:8765/somepath", 'otherserver'))

    def test_no_port(self):
        self.assertEquals(
            "http://otherserver/somepath",
            pool.swap_xapi_host(
                "http://someserver/somepath", 'otherserver'))

    def test_no_path(self):
        self.assertEquals(
            "http://otherserver",
            pool.swap_xapi_host(
                "http://someserver", 'otherserver'))


class VmUtilsTestCase(test.TestCase):
    """Unit tests for xenapi utils."""

    def test_upload_image(self):
        """Ensure image properties include instance system metadata
           as well as few local settings."""

        def fake_instance_system_metadata_get(context, uuid):
            return dict(image_a=1, image_b=2, image_c='c', d='d')

        def fake_get_sr_path(session):
            return "foo"

        class FakeInstance(dict):
            def __init__(self):
                super(FakeInstance, self).__init__({
                        'auto_disk_config': 'auto disk config',
                        'os_type': 'os type'})

            def __missing__(self, item):
                return "whatever"

        class FakeSession(object):
            def call_plugin(session_self, service, command, kwargs):
                self.kwargs = kwargs

            def call_plugin_serialized(session_self, service, command, *args,
                            **kwargs):
                self.kwargs = kwargs

        def fake_dumps(thing):
            return thing

        self.stubs.Set(db, "instance_system_metadata_get",
                                             fake_instance_system_metadata_get)
        self.stubs.Set(vm_utils, "get_sr_path", fake_get_sr_path)
        self.stubs.Set(pickle, "dumps", fake_dumps)

        ctx = context.get_admin_context()

        instance = FakeInstance()
        session = FakeSession()
        vm_utils.upload_image(ctx, session, instance, "vmi uuids", "image id")

        actual = self.kwargs['properties']
        expected = dict(a=1, b=2, c='c', d='d',
                        auto_disk_config='auto disk config',
                        os_type='os type')
        self.assertEquals(expected, actual)


class XenAPILiveMigrateTestCase(stubs.XenAPITestBase):
    """Unit tests for live_migration."""
    def setUp(self):
        super(XenAPILiveMigrateTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   host='host')
        db_fakes.stub_out_db_instance_api(self.stubs)
        self.context = context.get_admin_context()
        xenapi_fake.create_local_pifs()

    def test_live_migration_calls_vmops(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_live_migrate(context, instance_ref, dest, post_method,
                              recover_method, block_migration, migrate_data):
            fake_live_migrate.called = True

        self.stubs.Set(self.conn._vmops, "live_migrate", fake_live_migrate)

        self.conn.live_migration(None, None, None, None, None)
        self.assertTrue(fake_live_migrate.called)

    def test_pre_live_migration(self):
        # ensure method is present
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)
        self.conn.pre_live_migration(None, None, None, None)

    def test_post_live_migration_at_destination(self):
        # ensure method is present
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)
        self.conn.post_live_migration_at_destination(None, None, None, None)

    def test_check_can_live_migrate_destination_with_block_migration(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        self.stubs.Set(vm_utils, "safe_find_sr", lambda _x: "asdf")

        expected = {'block_migration': True,
                    'migrate_data': {
                        'migrate_send_data': "fake_migrate_data",
                        'destination_sr_ref': 'asdf'
                        }
                    }
        result = self.conn.check_can_live_migrate_destination(self.context,
                              {'host': 'host'}, True, False)
        self.assertEqual(expected, result)

    def test_check_can_live_migrate_destination_block_migration_fails(self):
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(False)
        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_destination,
                          self.context, {'host': 'host'}, True, False)

    def test_check_can_live_migrate_source_with_block_migrate(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_generate_vdi_map(destination_sr_ref, _vm_ref):
            pass

        self.stubs.Set(self.conn._vmops, "_generate_vdi_map",
                       fake_generate_vdi_map)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"

        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)
        dest_check_data = {'block_migration': True,
                           'migrate_data': {
                            'destination_sr_ref': None,
                            'migrate_send_data': None
                           }}
        self.assertNotRaises(None,
                             self.conn.check_can_live_migrate_source,
                             self.context,
                             {'host': 'host'},
                             dest_check_data)

    def test_check_can_live_migrate_source_with_block_migrate_fails(self):
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_generate_vdi_map(destination_sr_ref, _vm_ref):
            pass

        self.stubs.Set(self.conn._vmops, "_generate_vdi_map",
                       fake_generate_vdi_map)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"

        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        dest_check_data = {'block_migration': True,
                           'migrate_data': {
                            'destination_sr_ref': None,
                            'migrate_send_data': None
                           }}
        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_source,
                          self.context,
                          {'host': 'host'},
                          dest_check_data)

    def test_check_can_live_migrate_works(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        class fake_aggregate:
            def __init__(self):
                self.metadetails = {"host": "test_host_uuid"}

        def fake_aggregate_get_by_host(context, host, key=None):
            self.assertEqual(FLAGS.host, host)
            return [fake_aggregate()]

        self.stubs.Set(db, "aggregate_get_by_host",
                fake_aggregate_get_by_host)
        self.conn.check_can_live_migrate_destination(self.context,
                {'host': 'host'}, False, False)

    def test_check_can_live_migrate_fails(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        class fake_aggregate:
            def __init__(self):
                self.metadetails = {"dest_other": "test_host_uuid"}

        def fake_aggregate_get_by_host(context, host, key=None):
            self.assertEqual(FLAGS.host, host)
            return [fake_aggregate()]

        self.stubs.Set(db, "aggregate_get_by_host",
                      fake_aggregate_get_by_host)
        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_destination,
                          self.context, {'host': 'host'}, None, None)

    def test_live_migration(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"
        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def fake_get_host_opaque_ref(context, destination_hostname):
            return "fake_host"
        self.stubs.Set(self.conn._vmops, "_get_host_opaque_ref",
                       fake_get_host_opaque_ref)

        def post_method(context, instance, destination_hostname,
                        block_migration):
            post_method.called = True

        self.conn.live_migration(self.conn, None, None, post_method, None)

        self.assertTrue(post_method.called, "post_method.called")

    def test_live_migration_on_failure(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"
        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def fake_get_host_opaque_ref(context, destination_hostname):
            return "fake_host"
        self.stubs.Set(self.conn._vmops, "_get_host_opaque_ref",
                       fake_get_host_opaque_ref)

        def fake_call_xenapi(*args):
            raise NotImplementedError()
        self.stubs.Set(self.conn._vmops._session, "call_xenapi",
                       fake_call_xenapi)

        def recover_method(context, instance, destination_hostname,
                        block_migration):
            recover_method.called = True

        self.assertRaises(NotImplementedError, self.conn.live_migration,
                          self.conn, None, None, None, recover_method)
        self.assertTrue(recover_method.called, "recover_method.called")

    def test_live_migration_calls_post_migration(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_generate_vdi_map(destination_sr_ref, _vm_ref):
            pass

        self.stubs.Set(self.conn._vmops, "_generate_vdi_map",
                       fake_generate_vdi_map)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"

        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def post_method(context, instance, destination_hostname,
                        block_migration):
            post_method.called = True

        # pass block_migration = True and migrate data
        migrate_data = {"destination_sr_ref": "foo",
                        "migrate_send_data": "bar"}
        self.conn.live_migration(self.conn, None, None, post_method, None,
                                 True, migrate_data)
        self.assertTrue(post_method.called, "post_method.called")

    def test_live_migration_with_block_migration_raises_invalid_param(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"
        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def recover_method(context, instance, destination_hostname,
                           block_migration):
            recover_method.called = True
        # pass block_migration = True and no migrate data
        self.assertRaises(exception.InvalidParameterValue,
                          self.conn.live_migration, self.conn,
                          None, None, None, recover_method, True, None)
        self.assertTrue(recover_method.called, "recover_method.called")

    def test_live_migration_with_block_migration_fails_migrate_send(self):
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"
        self.stubs.Set(self.conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def fake_generate_vdi_map(destination_sr_ref, _vm_ref):
            pass
        self.stubs.Set(self.conn._vmops, "_generate_vdi_map",
                       fake_generate_vdi_map)

        def recover_method(context, instance, destination_hostname,
                           block_migration):
            recover_method.called = True
        # pass block_migration = True and migrate data
        migrate_data = dict(destination_sr_ref='foo', migrate_send_data='bar')
        self.assertRaises(exception.MigrationError,
                          self.conn.live_migration, self.conn,
                          None, None, None, recover_method, True, migrate_data)
        self.assertTrue(recover_method.called, "recover_method.called")

    def test_live_migrate_block_migration_xapi_call_parameters(self):

        fake_vdi_map = object()

        class Session(xenapi_fake.SessionBase):
            def VM_migrate_send(self_, session, vmref, migrate_data, islive,
                                vdi_map, vif_map, options):
                self.assertEquals('SOMEDATA', migrate_data)
                self.assertEquals(fake_vdi_map, vdi_map)

        stubs.stubout_session(self.stubs, Session)

        conn = xenapi_conn.XenAPIDriver(False)

        def fake_get_vm_opaque_ref(instance):
            return "fake_vm"

        self.stubs.Set(conn._vmops, "_get_vm_opaque_ref",
                       fake_get_vm_opaque_ref)

        def fake_generate_vdi_map(destination_sr_ref, _vm_ref):
            return fake_vdi_map

        self.stubs.Set(conn._vmops, "_generate_vdi_map",
                       fake_generate_vdi_map)

        def dummy_callback(*args, **kwargs):
            pass

        conn.live_migration(
            self.context, instance_ref=dict(name='ignore'), dest=None,
            post_method=dummy_callback, recover_method=dummy_callback,
            block_migration="SOMEDATA",
            migrate_data=dict(migrate_send_data='SOMEDATA',
                              destination_sr_ref="TARGET_SR_OPAQUE_REF"))

    def test_generate_vdi_map(self):
        stubs.stubout_session(self.stubs, xenapi_fake.SessionBase)
        conn = xenapi_conn.XenAPIDriver(False)

        vm_ref = "fake_vm_ref"

        def fake_find_sr(_session):
            self.assertEquals(conn._session, _session)
            return "source_sr_ref"
        self.stubs.Set(vm_utils, "safe_find_sr", fake_find_sr)

        def fake_get_instance_vdis_for_sr(_session, _vm_ref, _sr_ref):
            self.assertEquals(conn._session, _session)
            self.assertEquals(vm_ref, _vm_ref)
            self.assertEquals("source_sr_ref", _sr_ref)
            return ["vdi0", "vdi1"]

        self.stubs.Set(vm_utils, "get_instance_vdis_for_sr",
                       fake_get_instance_vdis_for_sr)

        result = conn._vmops._generate_vdi_map("dest_sr_ref", vm_ref)

        self.assertEquals({"vdi0": "dest_sr_ref",
                           "vdi1": "dest_sr_ref"}, result)


class XenAPIInjectMetadataTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(XenAPIInjectMetadataTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(False)

        self.xenstore = dict(persist={}, ephem={})

        def fake_get_vm_opaque_ref(inst, instance):
            self.assertEqual(instance, 'instance')
            return 'vm_ref'

        def fake_add_to_param_xenstore(inst, vm_ref, key, val):
            self.assertEqual(vm_ref, 'vm_ref')
            self.xenstore['persist'][key] = val

        def fake_remove_from_param_xenstore(inst, vm_ref, key):
            self.assertEqual(vm_ref, 'vm_ref')
            if key in self.xenstore['persist']:
                del self.xenstore['persist'][key]

        def fake_write_to_xenstore(inst, instance, path, value, vm_ref=None):
            self.assertEqual(instance, 'instance')
            self.assertEqual(vm_ref, 'vm_ref')
            self.xenstore['ephem'][path] = jsonutils.dumps(value)

        def fake_delete_from_xenstore(inst, instance, path, vm_ref=None):
            self.assertEqual(instance, 'instance')
            self.assertEqual(vm_ref, 'vm_ref')
            if path in self.xenstore['ephem']:
                del self.xenstore['ephem'][path]

        self.stubs.Set(vmops.VMOps, '_get_vm_opaque_ref',
                       fake_get_vm_opaque_ref)
        self.stubs.Set(vmops.VMOps, '_add_to_param_xenstore',
                       fake_add_to_param_xenstore)
        self.stubs.Set(vmops.VMOps, '_remove_from_param_xenstore',
                       fake_remove_from_param_xenstore)
        self.stubs.Set(vmops.VMOps, '_write_to_xenstore',
                       fake_write_to_xenstore)
        self.stubs.Set(vmops.VMOps, '_delete_from_xenstore',
                       fake_delete_from_xenstore)

    def test_inject_instance_metadata(self):

        # Add some system_metadata to ensure it doesn't get added
        # to xenstore
        instance = dict(metadata=[{'key': 'a', 'value': 1},
                                  {'key': 'b', 'value': 2},
                                  {'key': 'c', 'value': 3},
                                  # Check xenstore key sanitizing
                                  {'key': 'hi.there', 'value': 4},
                                  {'key': 'hi!t.e/e', 'value': 5}],
                                  # Check xenstore key sanitizing
                        system_metadata=[{'key': 'sys_a', 'value': 1},
                                         {'key': 'sys_b', 'value': 2},
                                         {'key': 'sys_c', 'value': 3}])
        self.conn._vmops.inject_instance_metadata(instance, 'vm_ref')

        self.assertEqual(self.xenstore, {
                'persist': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/b': '2',
                    'vm-data/user-metadata/c': '3',
                    'vm-data/user-metadata/hi_there': '4',
                    'vm-data/user-metadata/hi_t_e_e': '5',
                    },
                'ephem': {},
                })

    def test_change_instance_metadata_add(self):
        # Test XenStore key sanitizing here, too.
        diff = {'test.key': ['+', 4]}
        self.xenstore = {
            'persist': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            'ephem': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            }

        self.conn._vmops.change_instance_metadata('instance', diff)

        self.assertEqual(self.xenstore, {
                'persist': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/b': '2',
                    'vm-data/user-metadata/c': '3',
                    'vm-data/user-metadata/test_key': '4',
                    },
                'ephem': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/b': '2',
                    'vm-data/user-metadata/c': '3',
                    'vm-data/user-metadata/test_key': '4',
                    },
                })

    def test_change_instance_metadata_update(self):
        diff = dict(b=['+', 4])
        self.xenstore = {
            'persist': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            'ephem': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            }

        self.conn._vmops.change_instance_metadata('instance', diff)

        self.assertEqual(self.xenstore, {
                'persist': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/b': '4',
                    'vm-data/user-metadata/c': '3',
                    },
                'ephem': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/b': '4',
                    'vm-data/user-metadata/c': '3',
                    },
                })

    def test_change_instance_metadata_delete(self):
        diff = dict(b=['-'])
        self.xenstore = {
            'persist': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            'ephem': {
                'vm-data/user-metadata/a': '1',
                'vm-data/user-metadata/b': '2',
                'vm-data/user-metadata/c': '3',
                },
            }

        self.conn._vmops.change_instance_metadata('instance', diff)

        self.assertEqual(self.xenstore, {
                'persist': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/c': '3',
                    },
                'ephem': {
                    'vm-data/user-metadata/a': '1',
                    'vm-data/user-metadata/c': '3',
                    },
                })


class VMOpsTestCase(test.TestCase):
    def _get_mock_session(self, product_brand, product_version):
        class Mock(object):
            pass

        mock_session = Mock()
        mock_session.product_brand = product_brand
        mock_session.product_version = product_version

        return mock_session

    def test_check_resize_func_name_defaults_to_VDI_resize(self):
        session = self._get_mock_session(None, None)
        ops = vmops.VMOps(session)

        self.assertEquals(
            'VDI.resize',
            ops.check_resize_func_name())


class XenAPISessionTestCase(test.TestCase):
    def _get_mock_xapisession(self, software_version):
        class XcpXapiSession(xenapi_conn.XenAPISession):
            def __init__(_ignore):
                "Skip the superclass's dirty init"

            def _get_software_version(_ignore):
                return software_version

        return XcpXapiSession()

    def test_get_product_version_product_brand_does_not_fail(self):
        session = self._get_mock_xapisession({
                    'build_number': '0',
                    'date': '2012-08-03',
                    'hostname': 'komainu',
                    'linux': '3.2.0-27-generic',
                    'network_backend': 'bridge',
                    'platform_name': 'XCP_Kronos',
                    'platform_version': '1.6.0',
                    'xapi': '1.3',
                    'xen': '4.1.2',
                    'xencenter_max': '1.10',
                    'xencenter_min': '1.10'
                })

        self.assertEquals(
            (None, None),
            session._get_product_version_and_brand()
        )

    def test_get_product_version_product_brand_xs_6(self):
        session = self._get_mock_xapisession({
                    'product_brand': 'XenServer',
                    'product_version': '6.0.50'
                })

        self.assertEquals(
            ((6, 0, 50), 'XenServer'),
            session._get_product_version_and_brand()
        )
