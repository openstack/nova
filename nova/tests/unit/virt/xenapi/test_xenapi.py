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
import copy
import functools
import os
import re

import mock
from os_xenapi.client import host_management
from os_xenapi.client import session
from os_xenapi.client import XenAPI
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import importutils
from oslo_utils import uuidutils
import testtools

from nova.compute import api as compute_api
from nova.compute import manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import crypto
from nova.db import api as db
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import base
from nova.objects import fields as obj_fields
from nova import test
from nova.tests import fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.db import fakes as db_fakes
from nova.tests.unit import fake_diagnostics
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.tests.unit import fake_processutils
import nova.tests.unit.image.fake as fake_image
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_aggregate
from nova.tests.unit.objects import test_diagnostics
from nova.tests.unit import utils as test_utils
from nova.tests.unit.virt.xenapi import stubs
from nova.virt import fake
from nova.virt.xenapi import agent
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import host
from nova.virt.xenapi.image import glance
from nova.virt.xenapi import pool
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volume_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

IMAGE_MACHINE = uuids.image_ref
IMAGE_KERNEL = uuids.image_kernel_id
IMAGE_RAMDISK = uuids.image_ramdisk_id
IMAGE_RAW = uuids.image_raw
IMAGE_VHD = uuids.image_vhd
IMAGE_ISO = uuids.image_iso
IMAGE_IPXE_ISO = uuids.image_ipxe_iso
IMAGE_FROM_VOLUME = uuids.image_from_volume

IMAGE_FIXTURES = {
    IMAGE_MACHINE: {
        'image_meta': {'name': 'fakemachine', 'size': 0,
                       'disk_format': 'ami',
                       'container_format': 'ami',
                       'id': 'fake-image'},
    },
    IMAGE_KERNEL: {
        'image_meta': {'name': 'fakekernel', 'size': 0,
                       'disk_format': 'aki',
                       'container_format': 'aki',
                       'id': 'fake-kernel'},
    },
    IMAGE_RAMDISK: {
        'image_meta': {'name': 'fakeramdisk', 'size': 0,
                       'disk_format': 'ari',
                       'container_format': 'ari',
                       'id': 'fake-ramdisk'},
    },
    IMAGE_RAW: {
        'image_meta': {'name': 'fakeraw', 'size': 0,
                       'disk_format': 'raw',
                       'container_format': 'bare',
                       'id': 'fake-image-raw'},
    },
    IMAGE_VHD: {
        'image_meta': {'name': 'fakevhd', 'size': 0,
                       'disk_format': 'vhd',
                       'container_format': 'ovf',
                       'id': 'fake-image-vhd'},
    },
    IMAGE_ISO: {
        'image_meta': {'name': 'fakeiso', 'size': 0,
                       'disk_format': 'iso',
                       'container_format': 'bare',
                       'id': 'fake-image-iso'},
    },
    IMAGE_IPXE_ISO: {
        'image_meta': {'name': 'fake_ipxe_iso', 'size': 0,
                       'disk_format': 'iso',
                       'container_format': 'bare',
                       'id': 'fake-image-pxe',
                       'properties': {'ipxe_boot': 'true'}},
    },
    IMAGE_FROM_VOLUME: {
        'image_meta': {'name': 'fake_ipxe_iso',
                       'id': 'fake-image-volume',
                       'properties': {'foo': 'bar'}},
    },
}


def get_session():
    return xenapi_fake.SessionBase('http://localhost', 'root', 'test_pass')


def set_image_fixtures():
    image_service = fake_image.FakeImageService()
    image_service.images.clear()
    for image_id, image_meta in IMAGE_FIXTURES.items():
        image_meta = image_meta['image_meta']
        image_meta['id'] = image_id
        image_service.create(None, image_meta)


def get_fake_device_info():
    # FIXME: 'sr_uuid', 'introduce_sr_keys', sr_type and vdi_uuid
    # can be removed from the dict when LP bug #1087308 is fixed
    fake_vdi_ref = xenapi_fake.create_vdi('fake-vdi', None)
    fake_vdi_uuid = xenapi_fake.get_record('VDI', fake_vdi_ref)['uuid']
    fake = {'block_device_mapping':
              [{'connection_info': {'driver_volume_type': 'iscsi',
                                    'data': {'sr_uuid': 'falseSR',
                                             'introduce_sr_keys': ['sr_type'],
                                             'sr_type': 'iscsi',
                                             'vdi_uuid': fake_vdi_uuid,
                                             'target_discovered': False,
                                             'target_iqn': 'foo_iqn:foo_volid',
                                             'target_portal': 'localhost:3260',
                                             'volume_id': 'foo_volid',
                                             'target_lun': 1,
                                             'auth_password': 'my-p@55w0rd',
                                             'auth_username': 'johndoe',
                                             'auth_method': u'CHAP'}, },
                'mount_device': 'vda',
                'delete_on_termination': False}, ],
            'root_device_name': '/dev/sda',
            'ephemerals': [],
            'swap': None, }
    return fake


def stub_vm_utils_with_vdi_attached(function):
    """vm_utils.with_vdi_attached needs to be stubbed out because it
    calls down to the filesystem to attach a vdi. This provides a
    decorator to handle that.
    """
    @functools.wraps(function)
    def decorated_function(self, *args, **kwargs):
        @contextlib.contextmanager
        def fake_vdi_attached(*args, **kwargs):
            fake_dev = 'fakedev'
            yield fake_dev

        def fake_image_download(*args, **kwargs):
            pass

        orig_vdi_attached = vm_utils.vdi_attached
        orig_image_download = fake_image._FakeImageService.download
        try:
            vm_utils.vdi_attached = fake_vdi_attached
            fake_image._FakeImageService.download = fake_image_download
            return function(self, *args, **kwargs)
        finally:
            fake_image._FakeImageService.download = orig_image_download
            vm_utils.vdi_attached = orig_vdi_attached

    return decorated_function


def create_instance_with_system_metadata(context, instance_values):
    inst = objects.Instance(context=context,
                            system_metadata={})
    for k, v in instance_values.items():
        setattr(inst, k, v)
    inst.flavor = objects.Flavor.get_by_id(context,
                                           instance_values['instance_type_id'])
    inst.old_flavor = None
    inst.new_flavor = None
    inst.create()
    inst.pci_devices = objects.PciDeviceList(objects=[])

    return inst


class XenAPIVolumeTestCase(stubs.XenAPITestBaseNoDB):
    """Unit tests for Volume operations."""
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')

        self.instance = fake_instance.fake_db_instance(name='foo')

    @classmethod
    def _make_connection_info(cls):
        target_iqn = 'iqn.2010-10.org.openstack:volume-00000001'
        return {'driver_volume_type': 'iscsi',
                'data': {'volume_id': 1,
                         'target_iqn': target_iqn,
                         'target_portal': '127.0.0.1:3260,fake',
                         'target_lun': None,
                         'auth_method': 'CHAP',
                         'auth_username': 'username',
                         'auth_password': 'password'}}

    def test_attach_volume(self):
        # This shows how to test Ops classes' methods.
        stubs.stubout_session(self, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vm = xenapi_fake.create_vm(self.instance['name'], 'Running')
        conn_info = self._make_connection_info()
        self.assertIsNone(
            conn.attach_volume(None, conn_info, self.instance, '/dev/sdc'))

        # check that the VM has a VBD attached to it
        # Get XenAPI record for VBD
        vbds = xenapi_fake.get_all('VBD')
        vbd = xenapi_fake.get_record('VBD', vbds[0])
        vm_ref = vbd['VM']
        self.assertEqual(vm_ref, vm)

    def test_attach_volume_raise_exception(self):
        # This shows how to test when exceptions are raised.
        stubs.stubout_session(self, stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        xenapi_fake.create_vm(self.instance['name'], 'Running')
        self.assertRaises(exception.VolumeDriverNotFound,
                          conn.attach_volume,
                          None, {'driver_volume_type': 'nonexist'},
                          self.instance, '/dev/sdc')


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIVMTestCase(stubs.XenAPITestBase,
                       test_diagnostics.DiagnosticsComparisonMixin):
    """Unit tests for VM operations."""
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.network = importutils.import_object(CONF.network_manager)
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')
        self.flags(instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        db_fakes.stub_out_db_instance_api(self)
        xenapi_fake.create_network('fake', 'fake_br1')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.stubout_get_this_vm_uuid()
        self.stub_out_vm_methods()
        fake_processutils.stub_out_processutils_execute(self)
        self.user_id = 'fake'
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.conn._session.is_local_connection = False

        fake_image.stub_out_image_service(self)
        set_image_fixtures()
        self.stubout_image_service_download()
        self.stubout_stream_disk()

        self.stub_out('nova.virt.xenapi.vmops.VMOps._inject_instance_metadata',
                      lambda self, instance, vm: None)

        def fake_safe_copy_vdi(session, sr_ref, instance, vdi_to_copy_ref):
            name_label = "fakenamelabel"
            disk_type = "fakedisktype"
            virtual_size = 777
            return vm_utils.create_vdi(
                    session, sr_ref, instance, name_label, disk_type,
                    virtual_size)
        self.stub_out('nova.virt.xenapi.vm_utils._safe_copy_vdi',
                      fake_safe_copy_vdi)

        def fake_unpause_and_wait(self, vm_ref, instance, power_on):
            self._update_last_dom_id(vm_ref)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._unpause_and_wait',
                       fake_unpause_and_wait)

    def tearDown(self):
        fake_image.FakeImageService_reset()
        super(XenAPIVMTestCase, self).tearDown()

    def stubout_firewall_driver(self):
        self.stub_out('nova.virt.firewall.IptablesFirewallDriver.'
                      'prepare_instance_filter', lambda *args: None)
        self.stub_out('nova.virt.firewall.IptablesFirewallDriver.'
                      'instance_filter_exists', lambda *args: None)

    def stubout_instance_snapshot(self):
        self.stub_out('nova.virt.xenapi.vm_utils._fetch_image',
                      lambda context, session, instance, name_label,
                      image, type, image_handler: {
                          'root': dict(uuid=stubs._make_fake_vdi(),
                                       file=None),
                          'kernel': dict(uuid=stubs._make_fake_vdi(),
                                         file=None),
                          'ramdisk': dict(uuid=stubs._make_fake_vdi(),
                                          file=None)})
        self.stub_out('nova.virt.xenapi.vm_utils._wait_for_vhd_coalesce',
                      lambda *args: ("fakeparent", "fakebase"))

    def stubout_image_service_download(self):
        self.stub_out('nova.tests.unit.image.fake._FakeImageService.download',
                      lambda *args, **kwargs: None)

    def stubout_stream_disk(self):
        self.stub_out('nova.virt.xenapi.vm_utils._stream_disk',
                      lambda *args, **kwargs: None)

    def stubout_is_snapshot(self):
        """Always returns true

            xenapi fake driver does not create vmrefs for snapshots.
        """
        self.stub_out('nova.virt.xenapi.vm_utils.is_snapshot',
                      lambda *args: True)

    def stubout_fetch_disk_image(self, raise_failure=False):
        """Simulates a failure in fetch image_glance_disk."""

        def _fake_fetch_disk_image(context, session, instance, name_label,
                                   image, image_type):
            if raise_failure:
                raise XenAPI.Failure("Test Exception raised by "
                                     "fake fetch_image_glance_disk")
            elif image_type == vm_utils.ImageType.KERNEL:
                filename = "kernel"
            elif image_type == vm_utils.ImageType.RAMDISK:
                filename = "ramdisk"
            else:
                filename = "unknown"

            vdi_type = vm_utils.ImageType.to_string(image_type)
            return {vdi_type: dict(uuid=None, file=filename)}

        self.stub_out('nova.virt.xenapi.vm_utils._fetch_disk_image',
                      _fake_fetch_disk_image)

    def stubout_create_vm(self):
        """Simulates a failure in create_vm."""

        def f(*args):
            raise XenAPI.Failure("Test Exception raised by fake create_vm")
        self.stub_out('nova.virt.xenapi.vm_utils.create_vm', f)

    def stubout_attach_disks(self):
        """Simulates a failure in _attach_disks."""

        def f(*args):
            raise XenAPI.Failure("Test Exception raised by fake _attach_disks")
        self.stub_out('nova.virt.xenapi.vmops.VMOps._attach_disks', f)

    def stub_out_vm_methods(self):
        self.stub_out('nova.virt.xenapi.vmops.VMOps._acquire_bootlock',
                      lambda self, vm: None)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._release_bootlock',
                      lambda self, vm: None)
        self.stub_out('nova.virt.xenapi.vm_utils.generate_ephemeral',
                      lambda *args: None)
        self.stub_out('nova.virt.xenapi.vm_utils._wait_for_device',
                      lambda session, dev, dom0, max_seconds: None)

    def test_init_host(self):
        session = get_session()
        vm = vm_utils._get_this_vm_ref(session)
        # Local root disk
        vdi0 = xenapi_fake.create_vdi('compute', None)
        vbd0 = xenapi_fake.create_vbd(vm, vdi0)
        # Instance VDI
        vdi1 = xenapi_fake.create_vdi('instance-aaaa', None,
                other_config={'nova_instance_uuid': 'aaaa'})
        xenapi_fake.create_vbd(vm, vdi1)
        # Only looks like instance VDI
        vdi2 = xenapi_fake.create_vdi('instance-bbbb', None)
        vbd2 = xenapi_fake.create_vbd(vm, vdi2)

        self.conn.init_host(None)
        self.assertEqual(set(xenapi_fake.get_all('VBD')), set([vbd0, vbd2]))

    @mock.patch.object(objects.Instance, 'name',
                       new=mock.PropertyMock(return_value='foo'))
    @mock.patch.object(vm_utils, 'lookup', return_value=True)
    def test_instance_exists(self, mock_lookup):
        instance = objects.Instance(uuid=uuids.instance)
        self.assertTrue(self.conn.instance_exists(instance))
        mock_lookup.assert_called_once_with(mock.ANY, 'foo')

    @mock.patch.object(objects.Instance, 'name',
                       new=mock.PropertyMock(return_value='bar'))
    @mock.patch.object(vm_utils, 'lookup', return_value=None)
    def test_instance_not_exists(self, mock_lookup):
        instance = objects.Instance(uuid=uuids.instance)
        self.assertFalse(self.conn.instance_exists(instance))
        mock_lookup.assert_called_once_with(mock.ANY, 'bar')

    def test_list_instances_0(self):
        instances = self.conn.list_instances()
        self.assertEqual(instances, [])

    def test_list_instance_uuids_0(self):
        instance_uuids = self.conn.list_instance_uuids()
        self.assertEqual(instance_uuids, [])

    def test_list_instance_uuids(self):
        uuids = []
        for x in range(1, 4):
            instance = self._create_instance()
            uuids.append(instance['uuid'])
        instance_uuids = self.conn.list_instance_uuids()
        self.assertEqual(len(uuids), len(instance_uuids))
        self.assertEqual(set(uuids), set(instance_uuids))

    def test_get_rrd_server(self):
        self.flags(connection_url='myscheme://myaddress/',
                   group='xenserver')
        server_info = vm_utils._get_rrd_server()
        self.assertEqual(server_info[0], 'myscheme')
        self.assertEqual(server_info[1], 'myaddress')

    expected_raw_diagnostics = {
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

    @mock.patch.object(vm_utils, '_get_rrd')
    def test_get_diagnostics(self, mock_get_rrd):
        def fake_get_rrd(host, vm_uuid):
            path = os.path.dirname(os.path.realpath(__file__))
            with open(os.path.join(path, 'vm_rrd.xml')) as f:
                return re.sub(r'\s', '', f.read())
        mock_get_rrd.side_effect = fake_get_rrd

        expected = self.expected_raw_diagnostics
        instance = self._create_instance()
        actual = self.conn.get_diagnostics(instance)
        self.assertThat(actual, matchers.DictMatches(expected))

    def test_get_instance_diagnostics(self):
        expected = fake_diagnostics.fake_diagnostics_obj(
            config_drive=False,
            state='running',
            driver='xenapi',
            cpu_details=[{'id': 0, 'utilisation': 11},
                         {'id': 1, 'utilisation': 22},
                         {'id': 2, 'utilisation': 33},
                         {'id': 3, 'utilisation': 44}],
            nic_details=[{'mac_address': 'DE:AD:BE:EF:00:01',
                          'rx_rate': 50,
                          'tx_rate': 100}],
            disk_details=[{'read_bytes': 50, 'write_bytes': 100}],
            memory_details={'maximum': 8192, 'used': 3072})

        instance = self._create_instance(obj=True)
        actual = self.conn.get_instance_diagnostics(instance)

        self.assertDiagnosticsEqual(expected, actual)

    def _test_get_instance_diagnostics_failure(self, **kwargs):
        instance = self._create_instance(obj=True)

        with mock.patch.object(xenapi_fake.SessionBase, 'VM_query_data_source',
                               **kwargs):
            actual = self.conn.get_instance_diagnostics(instance)

        expected = fake_diagnostics.fake_diagnostics_obj(
                config_drive=False,
                state='running',
                driver='xenapi',
                cpu_details=[{'id': 0}, {'id': 1}, {'id': 2}, {'id': 3}],
                nic_details=[{'mac_address': 'DE:AD:BE:EF:00:01'}],
                disk_details=[{}],
                memory_details={'maximum': None, 'used': None})

        self.assertDiagnosticsEqual(expected, actual)

    def test_get_instance_diagnostics_xenapi_exception(self):
        self._test_get_instance_diagnostics_failure(
                side_effect=XenAPI.Failure(''))

    def test_get_instance_diagnostics_nan_value(self):
        self._test_get_instance_diagnostics_failure(
                return_value=float('NaN'))

    def test_get_vnc_console(self):
        instance = self._create_instance(obj=True)
        session = get_session()
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vm_ref = vm_utils.lookup(session, instance['name'])

        console = conn.get_vnc_console(self.context, instance)

        # Note(sulo): We don't care about session id in test
        # they will always differ so strip that out
        actual_path = console.internal_access_path.split('&')[0]
        expected_path = "/console?ref=%s" % str(vm_ref)

        self.assertEqual(expected_path, actual_path)

    def test_get_vnc_console_for_rescue(self):
        instance = self._create_instance(obj=True)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        rescue_vm = xenapi_fake.create_vm(instance['name'] + '-rescue',
                                          'Running')
        # Set instance state to rescued
        instance['vm_state'] = 'rescued'

        console = conn.get_vnc_console(self.context, instance)

        # Note(sulo): We don't care about session id in test
        # they will always differ so strip that out
        actual_path = console.internal_access_path.split('&')[0]
        expected_path = "/console?ref=%s" % str(rescue_vm)

        self.assertEqual(expected_path, actual_path)

    def test_get_vnc_console_instance_not_ready(self):
        instance = self._create_instance(obj=True, spawn=False)
        instance.vm_state = 'building'

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.InstanceNotFound,
                          conn.get_vnc_console, self.context, instance)

    def test_get_vnc_console_rescue_not_ready(self):
        instance = self._create_instance(obj=True, spawn=False)
        instance.vm_state = 'rescued'

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.InstanceNotReady,
                          conn.get_vnc_console, self.context, instance)

    @mock.patch.object(vm_utils, 'create_vbd')
    def test_instance_snapshot_fails_with_no_primary_vdi(
            self, mock_create_vbd):
        def create_bad_vbd(session, vm_ref, vdi_ref, userdevice,
                           vbd_type='disk', read_only=False, bootable=False,
                           osvol=False):
            vbd_rec = {'VM': vm_ref,
               'VDI': vdi_ref,
               'userdevice': 'fake',
               'currently_attached': False}
            vbd_ref = xenapi_fake._create_object('VBD', vbd_rec)
            xenapi_fake.after_VBD_create(vbd_ref, vbd_rec)
            return vbd_ref

        mock_create_vbd.side_effect = create_bad_vbd
        self.stubout_instance_snapshot()
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        self.stubout_firewall_driver()
        instance = self._create_instance()

        image_id = "my_snapshot_id"
        self.assertRaises(exception.NovaException, self.conn.snapshot,
                          self.context, instance, image_id,
                          lambda *args, **kwargs: None)

    @mock.patch.object(glance.GlanceStore, 'upload_image')
    def test_instance_snapshot(self, mock_upload_image):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)
        image_id = "my_snapshot_id"

        self.stubout_instance_snapshot()
        self.stubout_is_snapshot()
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        self.stubout_firewall_driver()

        instance = self._create_instance()

        self.fake_upload_called = False

        def fake_image_upload(ctx, session, inst, img_id, vdi_uuids):
            self.fake_upload_called = True
            self.assertEqual(ctx, self.context)
            self.assertEqual(inst, instance)
            self.assertIsInstance(vdi_uuids, list)
            self.assertEqual(img_id, image_id)

        mock_upload_image.side_effect = fake_image_upload

        self.conn.snapshot(self.context, instance, image_id,
                           func_call_matcher.call)

        # Ensure VM was torn down
        vm_labels = []
        for vm_ref in xenapi_fake.get_all('VM'):
            vm_rec = xenapi_fake.get_record('VM', vm_ref)
            if not vm_rec["is_control_domain"]:
                vm_labels.append(vm_rec["name_label"])

        self.assertEqual(vm_labels, [instance['name']])

        # Ensure VBDs were torn down
        vbd_labels = []
        for vbd_ref in xenapi_fake.get_all('VBD'):
            vbd_rec = xenapi_fake.get_record('VBD', vbd_ref)
            vbd_labels.append(vbd_rec["vm_name_label"])

        self.assertEqual(vbd_labels, [instance['name']])

        # Ensure task states changed in correct order
        self.assertIsNone(func_call_matcher.match())

        # Ensure VDIs were torn down
        for vdi_ref in xenapi_fake.get_all('VDI'):
            vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
            name_label = vdi_rec["name_label"]
            self.assertFalse(name_label.endswith('snapshot'))

        self.assertTrue(self.fake_upload_called)

    def create_vm_record(self, conn, os_type, name):
        instances = conn.list_instances()
        self.assertEqual(instances, [name])

        # Get Nova record for VM
        vm_info = conn.get_info({'name': name})
        # Get XenAPI record for VM
        vms = [rec for rec
               in xenapi_fake.get_all_records('VM').values()
               if not rec['is_control_domain']]
        vm = vms[0]
        self.vm_info = vm_info
        self.vm = vm

    def check_vm_record(self, conn, instance_type_id, check_injection):
        flavor = objects.Flavor.get_by_id(self.context, instance_type_id)
        mem_kib = int(flavor['memory_mb']) << 10
        mem_bytes = str(mem_kib << 10)
        vcpus = flavor['vcpus']
        vcpu_weight = flavor['vcpu_weight']

        self.assertEqual(self.vm['memory_static_max'], mem_bytes)
        self.assertEqual(self.vm['memory_dynamic_max'], mem_bytes)
        self.assertEqual(self.vm['memory_dynamic_min'], mem_bytes)
        self.assertEqual(self.vm['VCPUs_max'], str(vcpus))
        self.assertEqual(self.vm['VCPUs_at_startup'], str(vcpus))
        if vcpu_weight is None:
            self.assertEqual(self.vm['VCPUs_params'], {})
        else:
            self.assertEqual(self.vm['VCPUs_params'],
                             {'weight': str(vcpu_weight), 'cap': '0'})

        # Check that the VM is running according to Nova
        self.assertEqual(self.vm_info.state, power_state.RUNNING)

        # Check that the VM is running according to XenAPI.
        self.assertEqual(self.vm['power_state'], 'Running')

        if check_injection:
            xenstore_data = self.vm['xenstore_data']
            self.assertNotIn('vm-data/hostname', xenstore_data)
            key = 'vm-data/networking/DEADBEEF0001'
            xenstore_value = xenstore_data[key]
            tcpip_data = ast.literal_eval(xenstore_value)
            self.assertJsonEqual({'broadcast': '192.168.1.255',
                              'dns': ['192.168.1.4', '192.168.1.3'],
                              'gateway': '192.168.1.1',
                              'gateway_v6': '2001:db8:0:1::1',
                              'ip6s': [{'enabled': '1',
                                        'ip': '2001:db8:0:1:dcad:beff:feef:1',
                                        'netmask': 64,
                                        'gateway': '2001:db8:0:1::1'}],
                              'ips': [{'enabled': '1',
                                       'ip': '192.168.1.100',
                                       'netmask': '255.255.255.0',
                                       'gateway': '192.168.1.1'},
                                      {'enabled': '1',
                                       'ip': '192.168.1.101',
                                       'netmask': '255.255.255.0',
                                       'gateway': '192.168.1.1'}],
                              'label': 'test1',
                              'mac': 'DE:AD:BE:EF:00:01'}, tcpip_data)

    def check_vm_params_for_windows(self):
        self.assertEqual(self.vm['platform']['nx'], 'true')
        self.assertEqual(self.vm['HVM_boot_params'], {'order': 'dc'})
        self.assertEqual(self.vm['HVM_boot_policy'], 'BIOS order')

        # check that these are not set
        self.assertEqual(self.vm['PV_args'], '')
        self.assertEqual(self.vm['PV_bootloader'], '')
        self.assertEqual(self.vm['PV_kernel'], '')
        self.assertEqual(self.vm['PV_ramdisk'], '')

    def check_vm_params_for_linux(self):
        self.assertEqual(self.vm['platform']['nx'], 'false')
        self.assertEqual(self.vm['PV_args'], '')
        self.assertEqual(self.vm['PV_bootloader'], 'pygrub')

        # check that these are not set
        self.assertEqual(self.vm['PV_kernel'], '')
        self.assertEqual(self.vm['PV_ramdisk'], '')
        self.assertEqual(self.vm['HVM_boot_params'], {})
        self.assertEqual(self.vm['HVM_boot_policy'], '')

    def check_vm_params_for_linux_with_external_kernel(self):
        self.assertEqual(self.vm['platform']['nx'], 'false')
        self.assertEqual(self.vm['PV_args'], 'root=/dev/xvda1')
        self.assertNotEqual(self.vm['PV_kernel'], '')
        self.assertNotEqual(self.vm['PV_ramdisk'], '')

        # check that these are not set
        self.assertEqual(self.vm['HVM_boot_params'], {})
        self.assertEqual(self.vm['HVM_boot_policy'], '')

    def _list_vdis(self):
        session = get_session()
        return session.call_xenapi('VDI.get_all')

    def _list_vms(self):
        session = get_session()
        return session.call_xenapi('VM.get_all')

    def _check_vdis(self, start_list, end_list):
        for vdi_ref in end_list:
            if vdi_ref not in start_list:
                vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
                # If the cache is turned on then the base disk will be
                # there even after the cleanup
                if 'other_config' in vdi_rec:
                    if 'image-id' not in vdi_rec['other_config']:
                        self.fail('Found unexpected VDI:%s' % vdi_ref)
                else:
                    self.fail('Found unexpected VDI:%s' % vdi_ref)

    @mock.patch.object(vmops.VMOps, '_inject_instance_metadata')
    def _test_spawn(self, image_ref, kernel_id, ramdisk_id,
                    mock_inject_instance_metadata,
                    instance_type_id="3", os_type="linux",
                    hostname="test", architecture="x86-64", instance_id=1,
                    injected_files=None, check_injection=False,
                    create_record=True, empty_dns=False,
                    block_device_info=None,
                    key_data=None):
        if injected_files is None:
            injected_files = []

        if create_record:
            flavor = objects.Flavor.get_by_id(self.context,
                                              instance_type_id)
            instance = objects.Instance(context=self.context)
            instance.project_id = self.project_id
            instance.user_id = self.user_id
            instance.image_ref = image_ref
            instance.kernel_id = kernel_id
            instance.ramdisk_id = ramdisk_id
            instance.root_gb = flavor.root_gb
            instance.ephemeral_gb = flavor.ephemeral_gb
            instance.instance_type_id = instance_type_id
            instance.os_type = os_type
            instance.hostname = hostname
            instance.key_data = key_data
            instance.architecture = architecture
            instance.system_metadata = {}

            instance.flavor = flavor
            instance.create()
        else:
            instance = objects.Instance.get_by_id(self.context, instance_id,
                                                  expected_attrs=['flavor'])

        network_info = fake_network.fake_get_instance_nw_info(self)
        if empty_dns:
            # NOTE(tr3buchet): this is a terrible way to do this...
            network_info[0]['network']['subnets'][0]['dns'] = []

        image_meta = objects.ImageMeta.from_dict(
            IMAGE_FIXTURES[image_ref]["image_meta"])
        self.conn.spawn(self.context, instance, image_meta, injected_files,
                        'herp', {}, network_info, block_device_info)
        self.create_vm_record(self.conn, os_type, instance['name'])
        self.check_vm_record(self.conn, instance_type_id, check_injection)
        self.assertEqual(instance['os_type'], os_type)
        self.assertEqual(instance['architecture'], architecture)

    @mock.patch.object(session.XenAPISession, 'call_plugin_serialized')
    @mock.patch.object(vm_utils, 'get_sr_path', return_value='/sr/path')
    def test_spawn_ipxe_iso_success(self, mock_get_sr_path,
                                    mock_call_plugin_serialized):
        self.flags(ipxe_network_name='test1',
                   ipxe_boot_menu_url='http://boot.example.com',
                   ipxe_mkisofs_cmd='/root/mkisofs',
                   group='xenserver')

        self._test_spawn(IMAGE_IPXE_ISO, None, None)

        mock_get_sr_path.assert_called_once_with(mock.ANY)
        mock_call_plugin_serialized.assert_has_calls([
            mock.call('ipxe.py', 'inject', '/sr/path', mock.ANY,
                      'http://boot.example.com', '192.168.1.100',
                      '255.255.255.0', '192.168.1.1', '192.168.1.3',
                      '/root/mkisofs'),
            mock.call('partition_utils.py', 'make_partition',
                      'fakedev', '2048', '-')])

    @mock.patch.object(session.XenAPISession, 'call_plugin_serialized')
    def test_spawn_ipxe_iso_no_network_name(self, mock_call_plugin_serialized):
        self.flags(ipxe_network_name=None,
                   ipxe_boot_menu_url='http://boot.example.com',
                   group='xenserver')

        self._test_spawn(IMAGE_IPXE_ISO, None, None)
        self._check_call_plugin_serialized(mock_call_plugin_serialized)

    @mock.patch.object(session.XenAPISession, 'call_plugin_serialized')
    def test_spawn_ipxe_iso_no_boot_menu_url(
            self, mock_call_plugin_serialized):
        self.flags(ipxe_network_name='test1',
                   ipxe_boot_menu_url=None,
                   group='xenserver')

        self._test_spawn(IMAGE_IPXE_ISO, None, None)
        self._check_call_plugin_serialized(mock_call_plugin_serialized)

    def _check_call_plugin_serialized(self, mock_call_plugin_serialized):
        vifs = xenapi_fake.get_all_records('VIF')
        iface_id = vifs[list(vifs)[0]]['other_config']['neutron-port-id']

        def _get_qbr_name(iface_id):
            return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

        def _get_veth_pair_names(iface_id):
            return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                    ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

        def _get_patch_port_pair_names(iface_id):
            return (("vif%s" % iface_id)[:network_model.NIC_NAME_LEN],
                    ("tap%s" % iface_id)[:network_model.NIC_NAME_LEN])

        # ipxe inject shouldn't be called
        call1 = mock.call('partition_utils.py', 'make_partition', 'fakedev',
                          '2048', '-')
        linux_br_name = _get_qbr_name(iface_id)
        qvb_name, qvo_name = _get_veth_pair_names(iface_id)
        patch_port1, tap_name = _get_patch_port_pair_names(iface_id)

        args = {'cmd': 'ip_link_get_dev',
                'args': {'device_name': linux_br_name}
                }
        call2 = mock.call('xenhost.py', 'network_config', args)

        args = {'cmd': 'ip_link_get_dev',
                'args': {'device_name': qvo_name}
                }
        call3 = mock.call('xenhost.py', 'network_config', args)

        args = {'cmd': 'ip_link_get_dev',
                'args': {'device_name': tap_name}
                }
        call4 = mock.call('xenhost.py', 'network_config', args)
        mock_call_plugin_serialized.assert_has_calls([call1,
                                                      call2,
                                                      call3,
                                                      call4])

    @mock.patch.object(session.XenAPISession, 'call_plugin_serialized')
    def test_spawn_ipxe_iso_unknown_network_name(
            self, mock_call_plugin_serialized):
        self.flags(ipxe_network_name='test2',
                   ipxe_boot_menu_url='http://boot.example.com',
                   group='xenserver')

        self._test_spawn(IMAGE_IPXE_ISO, None, None)
        self._check_call_plugin_serialized(mock_call_plugin_serialized)

    def test_spawn_empty_dns(self):
        # Test spawning with an empty dns list.
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         empty_dns=True)
        self.check_vm_params_for_linux()

    def test_spawn_not_enough_memory(self):
        self.assertRaises(exception.InsufficientFreeMemory, self._test_spawn,
                          IMAGE_MACHINE, IMAGE_KERNEL,
                          IMAGE_RAMDISK, instance_type_id="4")  # m1.xlarge

    def test_spawn_fail_cleanup_1(self):
        """Simulates an error while downloading an image.

        Verifies that the VM and VDIs created are properly cleaned up.
        """
        vdi_recs_start = self._list_vdis()
        start_vms = self._list_vms()
        self.stubout_fetch_disk_image(raise_failure=True)
        self.assertRaises(XenAPI.Failure, self._test_spawn,
                          IMAGE_MACHINE, IMAGE_KERNEL, IMAGE_RAMDISK)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        end_vms = self._list_vms()
        self._check_vdis(vdi_recs_start, vdi_recs_end)
        # No additional VMs should be found.
        self.assertEqual(start_vms, end_vms)

    def test_spawn_fail_cleanup_2(self):
        """Simulates an error while creating VM record.

        Verifies that the VM and VDIs created are properly cleaned up.
        """
        vdi_recs_start = self._list_vdis()
        start_vms = self._list_vms()
        self.stubout_create_vm()
        self.assertRaises(XenAPI.Failure, self._test_spawn,
                          IMAGE_MACHINE, IMAGE_KERNEL, IMAGE_RAMDISK)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        end_vms = self._list_vms()
        self._check_vdis(vdi_recs_start, vdi_recs_end)
        # No additional VMs should be found.
        self.assertEqual(start_vms, end_vms)

    def test_spawn_fail_cleanup_3(self):
        """Simulates an error while attaching disks.

        Verifies that the VM and VDIs created are properly cleaned up.
        """
        self.stubout_attach_disks()
        vdi_recs_start = self._list_vdis()
        start_vms = self._list_vms()
        self.assertRaises(XenAPI.Failure, self._test_spawn,
                          IMAGE_MACHINE, IMAGE_KERNEL, IMAGE_RAMDISK)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        end_vms = self._list_vms()
        self._check_vdis(vdi_recs_start, vdi_recs_end)
        # No additional VMs should be found.
        self.assertEqual(start_vms, end_vms)

    def test_spawn_raw_glance(self):
        self._test_spawn(IMAGE_RAW, None, None, os_type=None)
        self.check_vm_params_for_windows()

    def test_spawn_vhd_glance_linux(self):
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")
        self.check_vm_params_for_linux()

    @mock.patch('nova.privsep.fs.mkfs')
    def test_spawn_vhd_glance_windows(self, fake_mkfs):
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="windows", architecture="i386",
                         instance_type_id=5)
        self.check_vm_params_for_windows()

    def test_spawn_iso_glance(self):
        self._test_spawn(IMAGE_ISO, None, None,
                         os_type="windows", architecture="i386")
        self.check_vm_params_for_windows()

    @mock.patch.object(vm_utils, '_fetch_disk_image')
    def test_spawn_glance(self, mock_fetch_disk_image):

        def fake_fetch_disk_image(context, session, instance, name_label,
                                  image_id, image_type):
            sr_ref = vm_utils.safe_find_sr(session)
            image_type_str = vm_utils.ImageType.to_string(image_type)
            vdi_ref = vm_utils.create_vdi(session, sr_ref, instance,
                name_label, image_type_str, "20")
            vdi_role = vm_utils.ImageType.get_role(image_type)
            vdi_uuid = session.call_xenapi("VDI.get_uuid", vdi_ref)
            return {vdi_role: dict(uuid=vdi_uuid, file=None)}
        mock_fetch_disk_image.side_effect = fake_fetch_disk_image

        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK)
        self.check_vm_params_for_linux_with_external_kernel()

    def test_spawn_boot_from_volume_no_glance_image_meta(self):
        dev_info = get_fake_device_info()
        self._test_spawn(IMAGE_FROM_VOLUME, None, None,
                         block_device_info=dev_info)

    def test_spawn_boot_from_volume_with_image_meta(self):
        dev_info = get_fake_device_info()
        self._test_spawn(IMAGE_VHD, None, None,
                         block_device_info=dev_info)

    @testtools.skipIf(test_utils.is_osx(),
                      'IPv6 pretty-printing broken on OSX, see bug 1409135')
    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'writefile')
    @mock.patch.object(nova.privsep.path, 'makedirs')
    @mock.patch.object(nova.privsep.path, 'chown')
    @mock.patch.object(nova.privsep.path, 'chmod')
    @mock.patch.object(nova.privsep.fs, 'mount', return_value=(None, None))
    @mock.patch.object(nova.privsep.fs, 'umount')
    def test_spawn_netinject_file(self, umount, mount, chmod, chown, mkdir,
                                  write_file, read_link):
        self.flags(flat_injected=True)
        db_fakes.stub_out_db_instance_api(self, injected=True)

        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK,
                         check_injection=True)
        read_link.assert_called()
        mkdir.assert_called()
        chown.assert_called()
        chmod.assert_called()
        write_file.assert_called()

    @testtools.skipIf(test_utils.is_osx(),
                      'IPv6 pretty-printing broken on OSX, see bug 1409135')
    def test_spawn_netinject_xenstore(self):
        db_fakes.stub_out_db_instance_api(self, injected=True)

        self._tee_executed = False

        def _mount_handler(cmd, *ignore_args, **ignore_kwargs):
            # When mounting, create real files under the mountpoint to simulate
            # files in the mounted filesystem

            # mount point will be the last item of the command list
            self._tmpdir = cmd[len(cmd) - 1]
            LOG.debug('Creating files in %s to simulate guest agent',
                      self._tmpdir)
            os.makedirs(os.path.join(self._tmpdir, 'usr', 'sbin'))
            # Touch the file using open
            open(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'), 'w').close()
            return '', ''

        def _umount_handler(cmd, *ignore_args, **ignore_kwargs):
            # Umount would normally make files in the mounted filesystem
            # disappear, so do that here
            LOG.debug('Removing simulated guest agent files in %s',
                      self._tmpdir)
            os.remove(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'))
            os.rmdir(os.path.join(self._tmpdir, 'usr', 'sbin'))
            os.rmdir(os.path.join(self._tmpdir, 'usr'))
            return '', ''

        def _tee_handler(cmd, *ignore_args, **ignore_kwargs):
            self._tee_executed = True
            return '', ''

        fake_processutils.fake_execute_set_repliers([
            (r'mount', _mount_handler),
            (r'umount', _umount_handler),
            (r'tee.*interfaces', _tee_handler)])
        self._test_spawn(IMAGE_MACHINE, IMAGE_KERNEL,
                         IMAGE_RAMDISK, check_injection=True)

        # tee must not run in this case, where an injection-capable
        # guest agent is detected
        self.assertFalse(self._tee_executed)

    @mock.patch.object(vmops.VMOps, '_inject_auto_disk_config')
    def test_spawn_injects_auto_disk_config_to_xenstore(
            self, mock_inject_auto_disk_config):
        instance = self._create_instance(spawn=False, obj=True)
        image_meta = objects.ImageMeta.from_dict(
            IMAGE_FIXTURES[IMAGE_MACHINE]["image_meta"])
        self.conn.spawn(self.context, instance, image_meta, [], 'herp', {}, '')

        mock_inject_auto_disk_config.assert_called_once_with(instance,
                                                             mock.ANY)

    @mock.patch.object(vmops.VMOps, '_create_vifs')
    @mock.patch('nova.privsep.linux_net.add_bridge', return_value=('', ''))
    @mock.patch('nova.privsep.linux_net.set_device_mtu')
    @mock.patch('nova.privsep.linux_net.set_device_enabled')
    @mock.patch('nova.privsep.linux_net.set_device_macaddr')
    @mock.patch('nova.privsep.linux_net.change_ip')
    @mock.patch('nova.privsep.linux_net.address_command_deprecated')
    @mock.patch('nova.privsep.linux_net.ipv4_forwarding_check',
                return_value=False)
    @mock.patch('nova.privsep.linux_net._enable_ipv4_forwarding_inner')
    @mock.patch('nova.privsep.linux_net.add_vlan')
    @mock.patch('nova.privsep.linux_net.iptables_get_rules',
                return_value=('', ''))
    @mock.patch('nova.privsep.linux_net.iptables_set_rules',
                return_value=('', ''))
    @mock.patch('nova.privsep.linux_net.bridge_setfd')
    @mock.patch('nova.privsep.linux_net.bridge_disable_stp')
    @mock.patch('nova.privsep.linux_net.bridge_add_interface',
                return_value=('', ''))
    def test_spawn_vlanmanager(self, mock_bridge_add_interface,
                               mock_bridge_disable_stp,
                               mock_bridge_setfd,
                               mock_iptables_set_rules,
                               mock_iptables_get_rules,
                               mock_add_vlan, mock_forwarding_enable,
                               mock_forwarding_check,
                               mock_address_command_horrid,
                               mock_change_ip, mock_set_macaddr,
                               mock_set_enabled, mock_set_mtu, mock_add_bridge,
                               mock_create_vifs):
        self.flags(network_manager='nova.network.manager.VlanManager',
                   vlan_interface='fake0')
        # Reset network table
        xenapi_fake.reset_table('network')
        # Instance 2 will use vlan network (see db/fakes.py)
        ctxt = self.context.elevated()
        inst2 = self._create_instance(False, obj=True)
        networks = self.network.db.network_get_all(ctxt)
        with mock.patch('nova.objects.network.Network._from_db_object'):
            for network in networks:
                self.network.set_network_host(ctxt, network)

        self.network.allocate_for_instance(ctxt,
                          instance_id=inst2.id,
                          instance_uuid=inst2.uuid,
                          host=CONF.host,
                          vpn=None,
                          rxtx_factor=3,
                          project_id=self.project_id,
                          macs=None)
        self._test_spawn(IMAGE_MACHINE,
                         IMAGE_KERNEL,
                         IMAGE_RAMDISK,
                         instance_id=inst2.id,
                         create_record=False)
        # TODO(salvatore-orlando): a complete test here would require
        # a check for making sure the bridge for the VM's VIF is
        # consistent with bridge specified in nova db

    def test_spawn_with_network_qos(self):
        self._create_instance()
        for vif_ref in xenapi_fake.get_all('VIF'):
            vif_rec = xenapi_fake.get_record('VIF', vif_ref)
            self.assertEqual(vif_rec['qos_algorithm_type'], '')
            self.assertEqual(vif_rec['qos_algorithm_params'], {})

    @mock.patch.object(crypto, 'ssh_encrypt_text')
    @mock.patch.object(stubs.FakeSessionForVMTests,
                       '_plugin_agent_inject_file')
    def test_spawn_ssh_key_injection(self, mock_plugin_agent_inject_file,
                                     mock_ssh_encrypt_text):
        # Test spawning with key_data on an instance.  Should use
        # agent file injection.
        self.flags(use_agent_default=True,
                   group='xenserver')
        actual_injected_files = []

        def fake_inject_file(method, args):
            path = base64.b64decode(args['b64_path'])
            contents = base64.b64decode(args['b64_contents'])
            actual_injected_files.append((path, contents))
            return jsonutils.dumps({'returncode': '0', 'message': 'success'})
        mock_plugin_agent_inject_file.side_effect = fake_inject_file

        def fake_encrypt_text(sshkey, new_pass):
            self.assertEqual("ssh-rsa fake_keydata", sshkey)
            return "fake"
        mock_ssh_encrypt_text.side_effect = fake_encrypt_text

        expected_data = (b'\n# The following ssh key was injected by '
                         b'Nova\nssh-rsa fake_keydata\n')

        injected_files = [(b'/root/.ssh/authorized_keys', expected_data)]
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         key_data='ssh-rsa fake_keydata')
        self.assertEqual(actual_injected_files, injected_files)

    @mock.patch.object(crypto, 'ssh_encrypt_text',
                       side_effect=NotImplementedError("Should not be called"))
    @mock.patch.object(stubs.FakeSessionForVMTests,
                       '_plugin_agent_inject_file')
    def test_spawn_ssh_key_injection_non_rsa(
            self, mock_plugin_agent_inject_file, mock_ssh_encrypt_text):
        # Test spawning with key_data on an instance.  Should use
        # agent file injection.
        self.flags(use_agent_default=True,
                   group='xenserver')
        actual_injected_files = []

        def fake_inject_file(method, args):
            path = base64.b64decode(args['b64_path'])
            contents = base64.b64decode(args['b64_contents'])
            actual_injected_files.append((path, contents))
            return jsonutils.dumps({'returncode': '0', 'message': 'success'})
        mock_plugin_agent_inject_file.side_effect = fake_inject_file

        expected_data = (b'\n# The following ssh key was injected by '
                         b'Nova\nssh-dsa fake_keydata\n')

        injected_files = [(b'/root/.ssh/authorized_keys', expected_data)]
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         key_data='ssh-dsa fake_keydata')
        self.assertEqual(actual_injected_files, injected_files)

    @mock.patch.object(stubs.FakeSessionForVMTests,
                       '_plugin_agent_inject_file')
    def test_spawn_injected_files(self, mock_plugin_agent_inject_file):
        # Test spawning with injected_files.
        self.flags(use_agent_default=True,
                   group='xenserver')
        actual_injected_files = []

        def fake_inject_file(method, args):
            path = base64.b64decode(args['b64_path'])
            contents = base64.b64decode(args['b64_contents'])
            actual_injected_files.append((path, contents))
            return jsonutils.dumps({'returncode': '0', 'message': 'success'})
        mock_plugin_agent_inject_file.side_effect = fake_inject_file

        injected_files = [(b'/tmp/foo', b'foobar')]
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         injected_files=injected_files)
        self.check_vm_params_for_linux()
        self.assertEqual(actual_injected_files, injected_files)

    @mock.patch('nova.db.api.agent_build_get_by_triple')
    def test_spawn_agent_upgrade(self, mock_get):
        self.flags(use_agent_default=True,
                   group='xenserver')

        mock_get.return_value = {"version": "1.1.0", "architecture": "x86-64",
                                 "hypervisor": "xen", "os": "windows",
                                 "url": "url", "md5hash": "asdf",
                                 'created_at': None, 'updated_at': None,
                                 'deleted_at': None, 'deleted': False,
                                 'id': 1}

        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")

    @mock.patch('nova.db.api.agent_build_get_by_triple')
    def test_spawn_agent_upgrade_fails_silently(self, mock_get):
        mock_get.return_value = {"version": "1.1.0", "architecture": "x86-64",
                                 "hypervisor": "xen", "os": "windows",
                                 "url": "url", "md5hash": "asdf",
                                 'created_at': None, 'updated_at': None,
                                 'deleted_at': None, 'deleted': False,
                                 'id': 1}

        self._test_spawn_fails_silently_with(exception.AgentError,
                method="_plugin_agent_agentupdate", failure="fake_error")

    @mock.patch.object(stubs.FakeSessionForVMTests,
                       '_plugin_agent_resetnetwork')
    def test_spawn_with_resetnetwork_alternative_returncode(
            self, mock_plugin_agent_resetnetwork):
        self.flags(use_agent_default=True,
                   group='xenserver')

        def fake_resetnetwork(method, args):
            # NOTE(johngarbutt): as returned by FreeBSD and Gentoo
            return jsonutils.dumps({'returncode': '500',
                                    'message': 'success'})
        mock_plugin_agent_resetnetwork.side_effect = fake_resetnetwork

        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")
        self.assertTrue(mock_plugin_agent_resetnetwork.called)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def _test_spawn_fails_silently_with(self, expected_exception_cls,
                                        mock_add_instance_fault_from_exc,
                                        method="_plugin_agent_version",
                                        failure=None, value=None):
        self.flags(use_agent_default=True,
                   agent_version_timeout=0,
                   group='xenserver')

        def fake_agent_call(method, args):
            if failure:
                raise XenAPI.Failure([failure])
            else:
                return value

        with mock.patch.object(stubs.FakeSessionForVMTests, method,
                               side_effect=fake_agent_call):
            self._test_spawn(IMAGE_VHD, None, None,
                             os_type="linux", architecture="x86-64")
            mock_add_instance_fault_from_exc.assert_called_once_with(
                mock.ANY, mock.ANY, test.MatchType(expected_exception_cls),
                exc_info=mock.ANY)

    def test_spawn_fails_silently_with_agent_timeout(self):
        self._test_spawn_fails_silently_with(exception.AgentTimeout,
                                             failure="TIMEOUT:fake")

    def test_spawn_fails_silently_with_agent_not_implemented(self):
        self._test_spawn_fails_silently_with(exception.AgentNotImplemented,
                                             failure="NOT IMPLEMENTED:fake")

    def test_spawn_fails_silently_with_agent_error(self):
        self._test_spawn_fails_silently_with(exception.AgentError,
                                             failure="fake_error")

    def test_spawn_fails_silently_with_agent_bad_return(self):
        error = jsonutils.dumps({'returncode': -1, 'message': 'fake'})
        self._test_spawn_fails_silently_with(exception.AgentError,
                                             value=error)

    def test_spawn_sets_last_dom_id(self):
        self._test_spawn(IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")
        self.assertEqual(self.vm['domid'],
                         self.vm['other_config']['last_dom_id'])

    def test_rescue(self):
        instance = self._create_instance(spawn=False, obj=True)
        xenapi_fake.create_vm(instance['name'], 'Running')

        session = get_session()
        vm_ref = vm_utils.lookup(session, instance['name'])

        swap_vdi_ref = xenapi_fake.create_vdi('swap', None)
        root_vdi_ref = xenapi_fake.create_vdi('root', None)
        eph1_vdi_ref = xenapi_fake.create_vdi('eph', None)
        eph2_vdi_ref = xenapi_fake.create_vdi('eph', None)
        vol_vdi_ref = xenapi_fake.create_vdi('volume', None)

        xenapi_fake.create_vbd(vm_ref, swap_vdi_ref, userdevice=2)
        xenapi_fake.create_vbd(vm_ref, root_vdi_ref, userdevice=0)
        xenapi_fake.create_vbd(vm_ref, eph1_vdi_ref, userdevice=4)
        xenapi_fake.create_vbd(vm_ref, eph2_vdi_ref, userdevice=5)
        xenapi_fake.create_vbd(vm_ref, vol_vdi_ref, userdevice=6,
                               other_config={'osvol': True})

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        image_meta = objects.ImageMeta.from_dict(
            {'id': IMAGE_VHD,
             'disk_format': 'vhd',
             'properties': {'vm_mode': 'xen'}})
        conn.rescue(self.context, instance, [], image_meta, '')

        vm = xenapi_fake.get_record('VM', vm_ref)
        rescue_name = "%s-rescue" % vm["name_label"]
        rescue_ref = vm_utils.lookup(session, rescue_name)
        rescue_vm = xenapi_fake.get_record('VM', rescue_ref)

        vdi_refs = {}
        for vbd_ref in rescue_vm['VBDs']:
            vbd = xenapi_fake.get_record('VBD', vbd_ref)
            vdi_refs[vbd['VDI']] = vbd['userdevice']

        self.assertEqual('1', vdi_refs[root_vdi_ref])
        self.assertEqual('2', vdi_refs[swap_vdi_ref])
        self.assertEqual('4', vdi_refs[eph1_vdi_ref])
        self.assertEqual('5', vdi_refs[eph2_vdi_ref])
        self.assertNotIn(vol_vdi_ref, vdi_refs)

    def test_rescue_preserve_disk_on_failure(self):
        # test that the original disk is preserved if rescue setup fails
        # bug #1227898
        instance = self._create_instance(obj=True)
        session = get_session()
        image_meta = objects.ImageMeta.from_dict(
            {'id': IMAGE_VHD,
             'disk_format': 'vhd',
             'properties': {'vm_mode': 'xen'}})
        vm_ref = vm_utils.lookup(session, instance['name'])
        vdi_ref, vdi_rec = vm_utils.get_vdi_for_vm_safely(session, vm_ref)

        # raise an error in the spawn setup process and trigger the
        # undo manager logic:
        with mock.patch.object(
                self.conn._vmops, '_start',
                side_effect=test.TestingException('Start Error')):
            self.assertRaises(test.TestingException, self.conn.rescue,
                              self.context, instance, [], image_meta, '')

            # confirm original disk still exists:
            vdi_ref2, vdi_rec2 = vm_utils.get_vdi_for_vm_safely(session,
                                                                vm_ref)
            self.assertEqual(vdi_ref, vdi_ref2)
            self.assertEqual(vdi_rec['uuid'], vdi_rec2['uuid'])

    def test_unrescue(self):
        instance = self._create_instance(obj=True)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        # Unrescue expects the original instance to be powered off
        conn.power_off(instance)
        xenapi_fake.create_vm(instance['name'] + '-rescue', 'Running')
        conn.unrescue(instance, None)

    def test_unrescue_not_in_rescue(self):
        instance = self._create_instance(obj=True)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        # Ensure that it will not unrescue a non-rescued instance.
        self.assertRaises(exception.InstanceNotInRescueMode, conn.unrescue,
                          instance, None)

    def test_finish_revert_migration(self):
        instance = self._create_instance()

        class VMOpsMock(object):

            def __init__(self):
                self.finish_revert_migration_called = False

            def finish_revert_migration(self, context, instance, block_info,
                                        power_on):
                self.finish_revert_migration_called = True

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        conn._vmops = VMOpsMock()
        conn.finish_revert_migration(self.context, instance, None, None)
        self.assertTrue(conn._vmops.finish_revert_migration_called)

    def test_reboot_hard(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        conn.reboot(self.context, instance, None, "HARD")

    @mock.patch.object(compute_api.API, 'reboot')
    def test_poll_rebooting_instances(self, mock_reboot):
        instance = self._create_instance()
        instances = [instance]
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        conn.poll_rebooting_instances(60, instances)

        mock_reboot.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_reboot_soft(self):
        instance = self._create_instance()
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        conn.reboot(self.context, instance, None, "SOFT")

    def test_reboot_halted(self):
        session = get_session()
        instance = self._create_instance(spawn=False)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        xenapi_fake.create_vm(instance['name'], 'Halted')
        conn.reboot(self.context, instance, None, "SOFT")
        vm_ref = vm_utils.lookup(session, instance['name'])
        vm = xenapi_fake.get_record('VM', vm_ref)
        self.assertEqual(vm['power_state'], 'Running')

    def test_reboot_unknown_state(self):
        instance = self._create_instance(spawn=False)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        xenapi_fake.create_vm(instance['name'], 'Unknown')
        self.assertRaises(XenAPI.Failure, conn.reboot, self.context,
                          instance, None, "SOFT")

    def test_reboot_rescued(self):
        instance = self._create_instance()
        instance['vm_state'] = vm_states.RESCUED
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        real_result = vm_utils.lookup(conn._session, instance['name'])

        with mock.patch.object(vm_utils, 'lookup',
                               return_value=real_result) as mock_lookup:
            conn.reboot(self.context, instance, None, "SOFT")
            mock_lookup.assert_called_once_with(conn._session,
                                                instance['name'], True)

    def test_get_console_output_succeeds(self):
        def fake_get_console_output(instance):
            self.assertEqual("instance", instance)
            return "console_log"

        with mock.patch.object(self.conn._vmops, 'get_console_output',
                               side_effect=fake_get_console_output):
            self.assertEqual(
                self.conn.get_console_output('context', "instance"),
                "console_log")

    def _test_maintenance_mode(self, find_host, find_aggregate):
        real_call_xenapi = self.conn._session.call_xenapi
        instance = self._create_instance(spawn=True)
        api_calls = {}

        # Record all the xenapi calls, and return a fake list of hosts
        # for the host.get_all call
        def fake_call_xenapi(self, method, *args):
            api_calls[method] = args
            if method == 'host.get_all':
                return ['foo', 'bar', 'baz']
            return real_call_xenapi(method, *args)
        self.stub_out('os_xenapi.client.session.XenAPISession.call_xenapi',
                      fake_call_xenapi)

        def fake_aggregate_get(context, host, key):
            if find_aggregate:
                return [test_aggregate.fake_aggregate]
            else:
                return []
        self.stub_out('nova.objects.aggregate._get_by_host_from_db',
                      fake_aggregate_get)

        def fake_host_find(context, session, src, dst):
            if find_host:
                return 'bar'
            else:
                raise exception.NoValidHost("I saw this one coming...")
        self.stub_out('nova.virt.xenapi.host._host_find', fake_host_find)

        result = self.conn.host_maintenance_mode('bar', 'on_maintenance')
        self.assertEqual(result, 'on_maintenance')

        # We expect the VM.pool_migrate call to have been called to
        # migrate our instance to the 'bar' host
        vm_ref = vm_utils.lookup(self.conn._session, instance['name'])
        host_ref = "foo"
        expected = (vm_ref, host_ref, {"live": "true"})
        self.assertEqual(api_calls.get('VM.pool_migrate'), expected)

        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], task_states.MIGRATING)

    def test_maintenance_mode(self):
        self._test_maintenance_mode(True, True)

    def test_maintenance_mode_no_host(self):
        self.assertRaises(exception.NoValidHost,
                          self._test_maintenance_mode, False, True)

    def test_maintenance_mode_no_aggregate(self):
        self.assertRaises(exception.NotFound,
                          self._test_maintenance_mode, True, False)

    @mock.patch.object(db, 'instance_get_all_by_host')
    def test_uuid_find(self, mock_instance_get_all_by_host):
        fake_inst = fake_instance.fake_db_instance(id=123)
        fake_inst2 = fake_instance.fake_db_instance(id=456)
        mock_instance_get_all_by_host.return_value = [fake_inst, fake_inst2]
        expected_name = CONF.instance_name_template % fake_inst['id']

        inst_uuid = host._uuid_find(self.context, fake_inst['host'],
                                    expected_name)

        self.assertEqual(inst_uuid, fake_inst['uuid'])
        mock_instance_get_all_by_host.assert_called_once_with(
            self.context, fake_inst['host'], columns_to_join=None)

    def test_per_instance_usage_running(self):
        instance = self._create_instance(spawn=True)
        flavor = objects.Flavor.get_by_id(self.context, 3)

        expected = {instance['uuid']: {'memory_mb': flavor['memory_mb'],
                                       'uuid': instance['uuid']}}
        actual = self.conn.get_per_instance_usage()
        self.assertEqual(expected, actual)

        # Paused instances still consume resources:
        self.conn.pause(instance)
        actual = self.conn.get_per_instance_usage()
        self.assertEqual(expected, actual)

    def test_per_instance_usage_suspended(self):
        # Suspended instances do not consume memory:
        instance = self._create_instance(spawn=True)
        self.conn.suspend(self.context, instance)
        actual = self.conn.get_per_instance_usage()
        self.assertEqual({}, actual)

    def test_per_instance_usage_halted(self):
        instance = self._create_instance(spawn=True, obj=True)
        self.conn.power_off(instance)
        actual = self.conn.get_per_instance_usage()
        self.assertEqual({}, actual)

    def _create_instance(self, spawn=True, obj=False, **attrs):
        """Creates and spawns a test instance."""
        instance_values = {
            'uuid': uuidutils.generate_uuid(),
            'display_name': 'host-',
            'project_id': self.project_id,
            'user_id': self.user_id,
            'image_ref': IMAGE_MACHINE,
            'kernel_id': IMAGE_KERNEL,
            'ramdisk_id': IMAGE_RAMDISK,
            'root_gb': 80,
            'ephemeral_gb': 0,
            'instance_type_id': '3',  # m1.large
            'os_type': 'linux',
            'vm_mode': 'hvm',
            'architecture': 'x86-64'}
        instance_values.update(attrs)

        instance = create_instance_with_system_metadata(self.context,
                                                        instance_values)
        network_info = fake_network.fake_get_instance_nw_info(self)
        image_meta = objects.ImageMeta.from_dict(
            {'id': uuids.image_id,
             'disk_format': 'vhd'})
        if spawn:
            self.conn.spawn(self.context, instance, image_meta, [], 'herp',
                            {}, network_info)
        if obj:
            return instance
        return base.obj_to_primitive(instance)

    @mock.patch.object(vm_utils, 'destroy_kernel_ramdisk')
    @mock.patch.object(vm_utils, 'lookup_kernel_ramdisk',
                       return_value=('kernel', 'ramdisk'))
    def test_destroy_clean_up_kernel_and_ramdisk(
            self, mock_lookup_kernel_ramdisk, mock_destroy_kernel_ramdisk):
        def fake_destroy_kernel_ramdisk(session, instance, kernel, ramdisk):
            self.assertEqual("kernel", kernel)
            self.assertEqual("ramdisk", ramdisk)

        mock_destroy_kernel_ramdisk.side_effect = fake_destroy_kernel_ramdisk

        instance = self._create_instance(spawn=True, obj=True)
        network_info = fake_network.fake_get_instance_nw_info(self)
        self.conn.destroy(self.context, instance, network_info)

        vm_ref = vm_utils.lookup(self.conn._session, instance['name'])
        self.assertIsNone(vm_ref)
        self.assertTrue(mock_destroy_kernel_ramdisk.called)


class XenAPIDiffieHellmanTestCase(test.NoDBTestCase):
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
        self.assertEqual(alice_shared, bob_shared)

    def _test_encryption(self, message):
        enc = self.alice.encrypt(message)
        self.assertFalse(enc.endswith('\n'))
        dec = self.bob.decrypt(enc)
        self.assertEqual(dec, message)

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
        self._test_encryption(''.join(['abcd' for i in range(1024)]))


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIMigrateInstance(stubs.XenAPITestBase):
    """Unit test for verifying migration-related actions."""

    REQUIRES_LOCKING = True

    def setUp(self):
        super(XenAPIMigrateInstance, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        db_fakes.stub_out_db_instance_api(self)
        xenapi_fake.create_network('fake', 'fake_br1')
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.instance_values = {
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': IMAGE_MACHINE,
                  'kernel_id': None,
                  'ramdisk_id': None,
                  'root_gb': 80,
                  'ephemeral_gb': 0,
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

        fake_processutils.stub_out_processutils_execute(self)
        self.stub_out_migration_methods()
        self.stubout_get_this_vm_uuid()

        def fake_inject_instance_metadata(self, instance, vm):
            pass
        self.stub_out('nova.virt.xenapi.vmops.VMOps._inject_instance_metadata',
                       fake_inject_instance_metadata)

        def fake_unpause_and_wait(self, vm_ref, instance, power_on):
            pass
        self.stub_out('nova.virt.xenapi.vmops.VMOps._unpause_and_wait',
                       fake_unpause_and_wait)

    def stub_out_migration_methods(self):
        fakesr = xenapi_fake.create_sr()

        def fake_import_all_migrated_disks(session, instance,
                                           import_root=True):
            vdi_ref = xenapi_fake.create_vdi(instance['name'], fakesr)
            vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
            vdi_rec['other_config']['nova_disk_type'] = 'root'
            return {"root": {'uuid': vdi_rec['uuid'], 'ref': vdi_ref},
                    "ephemerals": {}}

        def fake_get_vdi(session, vm_ref, userdevice='0'):
            vdi_ref_parent = xenapi_fake.create_vdi('derp-parent', fakesr)
            vdi_rec_parent = xenapi_fake.get_record('VDI', vdi_ref_parent)
            vdi_ref = fake.create_vdi('derp', fakesr,
                    sm_config={'vhd-parent': vdi_rec_parent['uuid']})
            vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
            return vdi_ref, vdi_rec

        self.stub_out('nova.virt.xenapi.vmops.VMOps._destroy',
                      lambda *args, **kwargs: None)
        self.stub_out('nova.virt.xenapi.vmops.VMOps.'
                      '_wait_for_instance_to_start',
                      lambda self, *args: None)
        self.stub_out('nova.virt.xenapi.vm_utils.import_all_migrated_disks',
                      fake_import_all_migrated_disks)
        self.stub_out('nova.virt.xenapi.vm_utils.scan_default_sr',
                      lambda session, *args: fakesr)
        self.stub_out('nova.virt.xenapi.vm_utils.get_vdi_for_vm_safely',
                      fake_get_vdi)
        self.stub_out('nova.virt.xenapi.vm_utils.get_sr_path',
                      lambda *args: 'fake')
        self.stub_out('nova.virt.xenapi.vm_utils.generate_ephemeral',
                      lambda *args: None)

    def _create_instance(self, **kw):
        values = self.instance_values.copy()
        values.update(kw)
        instance = objects.Instance(context=self.context, **values)
        instance.flavor = objects.Flavor(root_gb=80,
                                         ephemeral_gb=0)
        instance.create()
        return instance

    @mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_up')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(vm_utils, 'lookup')
    @mock.patch.object(volume_utils, 'is_booted_from_volume')
    def test_migrate_disk_and_power_off(self, mock_boot_from_volume,
                                        mock_lookup, mock_sr_path,
                                        mock_migrate):
        instance = self._create_instance()
        xenapi_fake.create_vm(instance['name'], 'Running')
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=80,
                                             ephemeral_gb=0)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        mock_boot_from_volume.return_value = True
        mock_lookup.return_value = 'fake_vm_ref'
        mock_sr_path.return_value = 'fake_sr_path'
        conn.migrate_disk_and_power_off(self.context, instance,
                                        '127.0.0.1', flavor, None)
        mock_lookup.assert_called_once_with(conn._session, instance['name'],
                                            False)
        mock_sr_path.assert_called_once_with(conn._session)
        mock_migrate.assert_called_once_with(self.context, instance,
                                             '127.0.0.1', 'fake_vm_ref',
                                             'fake_sr_path')

    def test_migrate_disk_and_power_off_passes_exceptions(self):
        instance = self._create_instance()
        xenapi_fake.create_vm(instance['name'], 'Running')
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=80,
                                             ephemeral_gb=0)

        def fake_raise(*args, **kwargs):
            raise exception.MigrationError(reason='test failure')
        self.stub_out(
            'nova.virt.xenapi.vmops.VMOps._migrate_disk_resizing_up',
            fake_raise)

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.MigrationError,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          '127.0.0.1', flavor, None)

    def test_migrate_disk_and_power_off_throws_on_zero_gb_resize_down(self):
        instance = self._create_instance()
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=0,
                                             ephemeral_gb=0)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.ResizeError,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          'fake_dest', flavor, None)

    @mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_up')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(vm_utils, 'lookup')
    @mock.patch.object(volume_utils, 'is_booted_from_volume')
    def test_migrate_disk_and_power_off_with_zero_gb_old_and_new_works(
            self, mock_boot_from_volume, mock_lookup, mock_sr_path,
            mock_migrate):
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=0,
                                             ephemeral_gb=0)
        instance = self._create_instance(root_gb=0, ephemeral_gb=0)
        instance.flavor.root_gb = 0
        instance.flavor.ephemeral_gb = 0
        xenapi_fake.create_vm(instance['name'], 'Running')
        mock_boot_from_volume.return_value = True
        mock_lookup.return_value = 'fake_vm_ref'
        mock_sr_path.return_value = 'fake_sr_path'
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        conn.migrate_disk_and_power_off(self.context, instance,
                                        '127.0.0.1', flavor, None)
        mock_lookup.assert_called_once_with(conn._session, instance['name'],
                                            False)
        mock_sr_path.assert_called_once_with(conn._session)
        mock_migrate.assert_called_once_with(self.context, instance,
                                             '127.0.0.1', 'fake_vm_ref',
                                             'fake_sr_path')

    def _test_revert_migrate(self, power_on):
        instance = create_instance_with_system_metadata(self.context,
                                                        self.instance_values)
        self.called = False
        self.fake_vm_start_called = False
        self.fake_finish_revert_migration_called = False
        context = 'fake_context'

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        def fake_finish_revert_migration(*args, **kwargs):
            self.fake_finish_revert_migration_called = True

        self.stub_out(
            'nova.tests.unit.virt.xenapi.stubs.FakeSessionForVMTests'
            '.VDI_resize_online', fake_vdi_resize)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._start', fake_vm_start)
        self.stub_out('nova.virt.xenapi.vmops.VMOps.finish_revert_migration',
                      fake_finish_revert_migration)
        stubs.stubout_session(self, stubs.FakeSessionForVMTests,
                              product_version=(4, 0, 0),
                              product_brand='XenServer')

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        network_info = fake_network.fake_get_instance_nw_info(self)
        image_meta = objects.ImageMeta.from_dict(
            {'id': instance['image_ref'], 'disk_format': 'vhd'})
        base = xenapi_fake.create_vdi('hurr', 'fake')
        base_uuid = xenapi_fake.get_record('VDI', base)['uuid']
        cow = xenapi_fake.create_vdi('durr', 'fake')
        cow_uuid = xenapi_fake.get_record('VDI', cow)['uuid']
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy=base_uuid, cow=cow_uuid),
                              network_info, image_meta, resize_instance=True,
                              block_device_info=None, power_on=power_on)
        self.assertTrue(self.called)
        self.assertEqual(self.fake_vm_start_called, power_on)

        conn.finish_revert_migration(context, instance, network_info,
                                     self.migration)
        self.assertTrue(self.fake_finish_revert_migration_called)

    def test_revert_migrate_power_on(self):
        self._test_revert_migrate(True)

    def test_revert_migrate_power_off(self):
        self._test_revert_migrate(False)

    def _test_finish_migrate(self, power_on):
        instance = create_instance_with_system_metadata(self.context,
                                                        self.instance_values)
        self.called = False
        self.fake_vm_start_called = False

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        self.stub_out('nova.virt.xenapi.vmops.VMOps._start', fake_vm_start)
        self.stub_out('nova.tests.unit.virt.xenapi.stubs'
                      '.FakeSessionForVMTests.VDI_resize_online',
                      fake_vdi_resize)
        stubs.stubout_session(self, stubs.FakeSessionForVMTests,
                              product_version=(4, 0, 0),
                              product_brand='XenServer')

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        network_info = fake_network.fake_get_instance_nw_info(self)
        image_meta = objects.ImageMeta.from_dict(
            {'id': instance['image_ref'], 'disk_format': 'vhd'})
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True,
                              block_device_info=None, power_on=power_on)
        self.assertTrue(self.called)
        self.assertEqual(self.fake_vm_start_called, power_on)

    def test_finish_migrate_power_on(self):
        self._test_finish_migrate(True)

    def test_finish_migrate_power_off(self):
        self._test_finish_migrate(False)

    def test_finish_migrate_no_local_storage(self):
        values = copy.copy(self.instance_values)
        values["root_gb"] = 0
        values["ephemeral_gb"] = 0
        instance = create_instance_with_system_metadata(self.context, values)
        instance.flavor.root_gb = 0
        instance.flavor.ephemeral_gb = 0

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stub_out('nova.tests.unit.virt.xenapi.stubs'
                      '.FakeSessionForVMTests.VDI_resize_online',
                      fake_vdi_resize)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        network_info = fake_network.fake_get_instance_nw_info(self)
        image_meta = objects.ImageMeta.from_dict(
            {'id': instance['image_ref'], 'disk_format': 'vhd'})
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)

    def test_finish_migrate_no_resize_vdi(self):
        instance = create_instance_with_system_metadata(self.context,
                                                        self.instance_values)

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stub_out('nova.tests.unit.virt.xenapi.stubs'
                      '.FakeSessionForVMTests.VDI_resize_online',
                      fake_vdi_resize)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        network_info = fake_network.fake_get_instance_nw_info(self)
        # Resize instance would be determined by the compute call
        image_meta = objects.ImageMeta.from_dict(
            {'id': instance['image_ref'], 'disk_format': 'vhd'})
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=False)

    @stub_vm_utils_with_vdi_attached
    def test_migrate_too_many_partitions_no_resize_down(self):
        instance = self._create_instance()
        xenapi_fake.create_vm(instance['name'], 'Running')
        flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        def fake_get_partitions(partition):
            return [(1, 2, 3, 4, "", ""), (1, 2, 3, 4, "", "")]

        self.stub_out('nova.virt.xenapi.vm_utils._get_partitions',
                      fake_get_partitions)

        self.assertRaises(exception.InstanceFaultRollback,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          '127.0.0.1', flavor, None)

    @stub_vm_utils_with_vdi_attached
    def test_migrate_bad_fs_type_no_resize_down(self):
        instance = self._create_instance()
        xenapi_fake.create_vm(instance['name'], 'Running')
        flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        def fake_get_partitions(partition):
            return [(1, 2, 3, "ext2", "", "boot")]

        self.stub_out('nova.virt.xenapi.vm_utils._get_partitions',
                      fake_get_partitions)

        self.assertRaises(exception.InstanceFaultRollback,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          '127.0.0.1', flavor, None)

    @mock.patch.object(vmops.VMOps, '_resize_ensure_vm_is_shutdown')
    @mock.patch.object(vmops.VMOps, '_apply_orig_vm_name_label')
    @mock.patch.object(vm_utils, 'resize_disk')
    @mock.patch.object(vm_utils, 'migrate_vhd')
    @mock.patch.object(vm_utils, 'destroy_vdi')
    @mock.patch.object(vm_utils, 'get_vdi_for_vm_safely')
    @mock.patch.object(vmops.VMOps, '_restore_orig_vm_and_cleanup_orphan')
    def test_migrate_rollback_when_resize_down_fs_fails(self, mock_restore,
                                                        mock_get_vdi,
                                                        mock_destroy,
                                                        mock_migrate,
                                                        mock_disk,
                                                        mock_label,
                                                        mock_resize):
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vmops = conn._vmops
        instance = objects.Instance(context=self.context,
                                    auto_disk_config=True,
                                    uuid=uuids.instance)
        instance.obj_reset_changes()
        vm_ref = "vm_ref"
        dest = "dest"
        flavor = "type"
        sr_path = "sr_path"

        vmops._resize_ensure_vm_is_shutdown(instance, vm_ref)
        vmops._apply_orig_vm_name_label(instance, vm_ref)
        old_vdi_ref = "old_ref"
        mock_get_vdi.return_value = (old_vdi_ref, None)
        new_vdi_ref = "new_ref"
        new_vdi_uuid = "new_uuid"
        mock_disk.return_value = (new_vdi_ref, new_vdi_uuid)
        mock_migrate.side_effect = exception.ResizeError(reason="asdf")
        vm_utils.destroy_vdi(vmops._session, new_vdi_ref)
        vmops._restore_orig_vm_and_cleanup_orphan(instance)

        with mock.patch.object(instance, 'save') as mock_save:
            self.assertRaises(exception.InstanceFaultRollback,
                              vmops._migrate_disk_resizing_down, self.context,
                              instance, dest, flavor, vm_ref, sr_path)
            self.assertEqual(3, mock_save.call_count)
            self.assertEqual(60.0, instance.progress)

        mock_resize.assert_any_call(instance, vm_ref)
        mock_label.assert_any_call(instance, vm_ref)
        mock_get_vdi.assert_called_once_with(vmops._session, vm_ref)
        mock_disk.assert_called_once_with(vmops._session, instance,
                                          old_vdi_ref, flavor)
        mock_migrate.assert_called_once_with(vmops._session, instance,
                                             new_vdi_uuid, dest, sr_path, 0)
        mock_destroy.assert_any_call(vmops._session, new_vdi_ref)
        mock_restore.assert_any_call(instance)

    @mock.patch.object(vm_utils, 'is_vm_shutdown')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_resize_ensure_vm_is_shutdown_cleanly(self, mock_hard, mock_clean,
                                                  mock_shutdown):
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vmops = conn._vmops
        fake_instance = {'uuid': 'uuid'}

        mock_shutdown.return_value = False
        mock_clean.return_value = False

        vmops._resize_ensure_vm_is_shutdown(fake_instance, "ref")
        mock_shutdown.assert_called_once_with(vmops._session, "ref")
        mock_clean.assert_called_once_with(vmops._session, fake_instance,
                                           "ref")

    @mock.patch.object(vm_utils, 'is_vm_shutdown')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_resize_ensure_vm_is_shutdown_forced(self, mock_hard, mock_clean,
                                                 mock_shutdown):
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vmops = conn._vmops
        fake_instance = {'uuid': 'uuid'}

        mock_shutdown.return_value = False
        mock_clean.return_value = False
        mock_hard.return_value = True

        vmops._resize_ensure_vm_is_shutdown(fake_instance, "ref")
        mock_shutdown.assert_called_once_with(vmops._session, "ref")
        mock_clean.assert_called_once_with(vmops._session, fake_instance,
                                           "ref")
        mock_hard.assert_called_once_with(vmops._session, fake_instance,
                                          "ref")

    @mock.patch.object(vm_utils, 'is_vm_shutdown')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_resize_ensure_vm_is_shutdown_fails(self, mock_hard, mock_clean,
                                                 mock_shutdown):
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vmops = conn._vmops
        fake_instance = {'uuid': 'uuid'}

        mock_shutdown.return_value = False
        mock_clean.return_value = False
        mock_hard.return_value = False

        self.assertRaises(exception.ResizeError,
            vmops._resize_ensure_vm_is_shutdown, fake_instance, "ref")
        mock_shutdown.assert_called_once_with(vmops._session, "ref")
        mock_clean.assert_called_once_with(vmops._session, fake_instance,
                                           "ref")
        mock_hard.assert_called_once_with(vmops._session, fake_instance,
                                          "ref")

    @mock.patch.object(vm_utils, 'is_vm_shutdown')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_resize_ensure_vm_is_shutdown_already_shutdown(self, mock_hard,
                                                           mock_clean,
                                                           mock_shutdown):
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        vmops = conn._vmops
        fake_instance = {'uuid': 'uuid'}

        mock_shutdown.return_value = True

        vmops._resize_ensure_vm_is_shutdown(fake_instance, "ref")
        mock_shutdown.assert_called_once_with(vmops._session, "ref")


class XenAPIImageTypeTestCase(test.NoDBTestCase):
    """Test ImageType class."""

    def test_to_string(self):
        # Can convert from type id to type string.
        self.assertEqual(
            vm_utils.ImageType.to_string(vm_utils.ImageType.KERNEL),
            vm_utils.ImageType.KERNEL_STR)

    def _assert_role(self, expected_role, image_type_id):
        self.assertEqual(
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


class XenAPIDetermineDiskImageTestCase(test.NoDBTestCase):
    """Unit tests for code that detects the ImageType."""
    def assert_disk_type(self, image_meta, expected_disk_type):
        actual = vm_utils.determine_disk_image_type(image_meta)
        self.assertEqual(expected_disk_type, actual)

    def test_machine(self):
        image_meta = objects.ImageMeta.from_dict(
            {'disk_format': 'ami'})
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK)

    def test_raw(self):
        image_meta = objects.ImageMeta.from_dict(
            {'disk_format': 'raw'})
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_RAW)

    def test_vhd(self):
        image_meta = objects.ImageMeta.from_dict(
            {'disk_format': 'vhd'})
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_VHD)


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIHostTestCase(stubs.XenAPITestBase):
    """Tests HostState, which holds metrics from XenServer that get
    reported back to the Schedulers.
    """

    def setUp(self):
        super(XenAPIHostTestCase, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.context = context.get_admin_context()
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.instance = fake_instance.fake_db_instance(name='foo')
        self.useFixture(fixtures.SingleCellSimple())

    def test_host_state(self):
        stats = self.conn.host_state.get_host_stats(False)
        # Values from fake.create_local_srs (ext SR)
        self.assertEqual(stats['disk_total'], 40000)
        self.assertEqual(stats['disk_used'], 0)
        # Values from fake._plugin_xenhost_host_data
        self.assertEqual(stats['host_memory_total'], 10)
        self.assertEqual(stats['host_memory_overhead'], 20)
        self.assertEqual(stats['host_memory_free'], 30)
        self.assertEqual(stats['host_memory_free_computed'], 40)
        self.assertEqual(stats['hypervisor_hostname'], 'fake-xenhost')
        self.assertEqual(stats['host_cpu_info']['cpu_count'], 4)
        self.assertThat({
            'vendor': 'GenuineIntel',
            'model': 'Intel(R) Xeon(R) CPU           X3430  @ 2.40GHz',
            'topology': {
                'sockets': 1,
                'cores': 4,
                'threads': 1,
            },
            'features': [
                'fpu', 'de', 'tsc', 'msr', 'pae', 'mce',
                'cx8', 'apic', 'sep', 'mtrr', 'mca',
                'cmov', 'pat', 'clflush', 'acpi', 'mmx',
                'fxsr', 'sse', 'sse2', 'ss', 'ht',
                'nx', 'constant_tsc', 'nonstop_tsc',
                'aperfmperf', 'pni', 'vmx', 'est', 'ssse3',
                'sse4_1', 'sse4_2', 'popcnt', 'hypervisor',
                'ida', 'tpr_shadow', 'vnmi', 'flexpriority',
                'ept', 'vpid',
            ]},
            matchers.DictMatches(stats['cpu_model']))
        # No VMs running
        self.assertEqual(stats['vcpus_used'], 0)

    def test_host_state_vcpus_used(self):
        stats = self.conn.host_state.get_host_stats(True)
        self.assertEqual(stats['vcpus_used'], 0)
        xenapi_fake.create_vm(self.instance['name'], 'Running')
        stats = self.conn.host_state.get_host_stats(True)
        self.assertEqual(stats['vcpus_used'], 4)

    def test_pci_passthrough_devices(self):
        stats = self.conn.host_state.get_host_stats(False)
        self.assertEqual(len(stats['pci_passthrough_devices']), 2)

    def test_host_state_missing_sr(self):
        # Must trigger construction of 'host_state' property
        # before introducing the stub which raises the error
        hs = self.conn.host_state

        with mock.patch.object(
                vm_utils, 'safe_find_sr',
                side_effect=exception.StorageRepositoryNotFound('not there')):
            self.assertRaises(exception.StorageRepositoryNotFound,
                              hs.get_host_stats,
                              refresh=True)

    def _test_host_action(self, method, action, expected=None):
        result = method('host', action)
        if not expected:
            expected = action
        self.assertEqual(result, expected)

    def _test_host_action_no_param(self, method, action, expected=None):
        result = method(action)
        if not expected:
            expected = action
        self.assertEqual(result, expected)

    def test_host_reboot(self):
        self._test_host_action_no_param(self.conn.host_power_action, 'reboot')

    def test_host_shutdown(self):
        self._test_host_action_no_param(self.conn.host_power_action,
            'shutdown')

    def test_host_startup(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_power_action, 'startup')

    def test_host_maintenance_on(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               True, 'on_maintenance')

    def test_host_maintenance_off(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               False, 'off_maintenance')

    def test_set_enable_host_enable(self):
        _create_service_entries(self.context, values={'nova': ['fake-mini']})
        self._test_host_action_no_param(self.conn.set_host_enabled,
                                        True, 'enabled')
        service = db.service_get_by_host_and_binary(self.context, 'fake-mini',
                                                    'nova-compute')
        self.assertFalse(service.disabled)

    def test_set_enable_host_disable(self):
        _create_service_entries(self.context, values={'nova': ['fake-mini']})
        self._test_host_action_no_param(self.conn.set_host_enabled,
                                        False, 'disabled')
        service = db.service_get_by_host_and_binary(self.context, 'fake-mini',
                                                    'nova-compute')
        self.assertTrue(service.disabled)

    def test_get_host_uptime(self):
        result = self.conn.get_host_uptime()
        self.assertEqual(result, 'fake uptime')

    def test_supported_instances_is_included_in_host_state(self):
        stats = self.conn.host_state.get_host_stats(False)
        self.assertIn('supported_instances', stats)

    @mock.patch.object(host, 'to_supported_instances',
                       return_value='SOMERETURNVALUE')
    def test_supported_instances_is_calculated_by_to_supported_instances(
            self, mock_to_supported_instances):
        stats = self.conn.host_state.get_host_stats(False)
        self.assertEqual("SOMERETURNVALUE", stats['supported_instances'])
        mock_to_supported_instances.assert_called_once_with(
            ['xen-3.0-x86_64', 'xen-3.0-x86_32p', 'hvm-3.0-x86_32',
             'hvm-3.0-x86_32p', 'hvm-3.0-x86_64'])

    @mock.patch.object(host.HostState, 'get_disk_used')
    @mock.patch.object(host.HostState, '_get_passthrough_devices')
    @mock.patch.object(host.HostState, '_get_vgpu_stats')
    @mock.patch.object(jsonutils, 'loads')
    @mock.patch.object(vm_utils, 'list_vms')
    @mock.patch.object(vm_utils, 'scan_default_sr')
    @mock.patch.object(host_management, 'get_host_data')
    def test_update_stats_caches_hostname(self, mock_host_data, mock_scan_sr,
                                          mock_list_vms, mock_loads,
                                          mock_vgpus_stats,
                                          mock_devices, mock_dis_used):
        data = {'disk_total': 0,
                'disk_used': 0,
                'disk_available': 0,
                'supported_instances': 0,
                'host_capabilities': [],
                'host_hostname': 'foo',
                'vcpus_used': 0,
                }
        sr_rec = {
            'physical_size': 0,
            'physical_utilisation': 0,
            'virtual_allocation': 0,
            }
        mock_loads.return_value = data
        mock_host_data.return_value = data
        mock_scan_sr.return_value = 'ref'
        mock_list_vms.return_value = []
        mock_devices.return_value = "dev1"
        mock_dis_used.return_value = (0, 0)
        self.conn._session = mock.Mock()
        with mock.patch.object(self.conn._session.SR, 'get_record') \
                as mock_record:
            mock_record.return_value = sr_rec
            stats = self.conn.host_state.get_host_stats(refresh=True)
            self.assertEqual('foo', stats['hypervisor_hostname'])
            self.assertEqual(2, mock_loads.call_count)
            self.assertEqual(2, mock_host_data.call_count)
            self.assertEqual(2, mock_scan_sr.call_count)
            self.assertEqual(2, mock_devices.call_count)
            self.assertEqual(2, mock_vgpus_stats.call_count)
            mock_loads.assert_called_with(data)
            mock_host_data.assert_called_with(self.conn._session)
            mock_scan_sr.assert_called_with(self.conn._session)
            mock_devices.assert_called_with()
            mock_vgpus_stats.assert_called_with()


@mock.patch.object(host.HostState, 'update_status')
class XenAPIHostStateTestCase(stubs.XenAPITestBaseNoDB):

    def _test_get_disk_used(self, vdis, attached_vbds):
        session = mock.MagicMock()
        host_state = host.HostState(session)

        sr_ref = 'sr_ref'

        session.SR.get_VDIs.return_value = vdis.keys()
        session.VDI.get_virtual_size.side_effect = \
            lambda vdi_ref: vdis[vdi_ref]['virtual_size']
        session.VDI.get_physical_utilisation.side_effect = \
            lambda vdi_ref: vdis[vdi_ref]['physical_utilisation']
        session.VDI.get_VBDs.side_effect = \
            lambda vdi_ref: vdis[vdi_ref]['VBDs']
        session.VBD.get_currently_attached.side_effect = \
            lambda vbd_ref: vbd_ref in attached_vbds

        disk_used = host_state.get_disk_used(sr_ref)
        session.SR.get_VDIs.assert_called_once_with(sr_ref)
        return disk_used

    def test_get_disk_used_virtual(self, mock_update_status):
        # Both VDIs are attached
        attached_vbds = ['vbd_1', 'vbd_2']
        vdis = {
            'vdi_1': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_1']},
            'vdi_2': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_2']}
        }
        disk_used = self._test_get_disk_used(vdis, attached_vbds)
        self.assertEqual((200, 2), disk_used)

    def test_get_disk_used_physical(self, mock_update_status):
        # Neither VDIs are attached
        attached_vbds = []
        vdis = {
            'vdi_1': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_1']},
            'vdi_2': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_2']}
        }
        disk_used = self._test_get_disk_used(vdis, attached_vbds)
        self.assertEqual((2, 2), disk_used)

    def test_get_disk_used_both(self, mock_update_status):
        # One VDI is attached
        attached_vbds = ['vbd_1']
        vdis = {
            'vdi_1': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_1']},
            'vdi_2': {'physical_utilisation': 1,
                      'virtual_size': 100,
                      'VBDs': ['vbd_2']}
        }
        disk_used = self._test_get_disk_used(vdis, attached_vbds)
        self.assertEqual((101, 2), disk_used)


class ToSupportedInstancesTestCase(test.NoDBTestCase):
    def test_default_return_value(self):
        self.assertEqual([],
            host.to_supported_instances(None))

    def test_return_value(self):
        self.assertEqual(
            [(obj_fields.Architecture.X86_64, obj_fields.HVType.XEN, 'xen')],
            host.to_supported_instances([u'xen-3.0-x86_64']))

    def test_invalid_values_do_not_break(self):
        self.assertEqual(
            [(obj_fields.Architecture.X86_64, obj_fields.HVType.XEN, 'xen')],
            host.to_supported_instances([u'xen-3.0-x86_64', 'spam']))

    def test_multiple_values(self):
        self.assertEqual(
            [
                (obj_fields.Architecture.X86_64, obj_fields.HVType.XEN, 'xen'),
                (obj_fields.Architecture.I686, obj_fields.HVType.XEN, 'hvm')
            ],
            host.to_supported_instances([u'xen-3.0-x86_64', 'hvm-3.0-x86_32'])
        )


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIAutoDiskConfigTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(XenAPIAutoDiskConfigTestCase, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': IMAGE_MACHINE,
                  'kernel_id': IMAGE_KERNEL,
                  'ramdisk_id': IMAGE_RAMDISK,
                  'root_gb': 80,
                  'ephemeral_gb': 0,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        self.stub_out('nova.virt.xenapi.vm_utils.create_vbd',
                      lambda session, vm_ref, vdi_ref, userdevice,
                      bootable, osvol: None)

    @mock.patch.object(vm_utils, '_resize_part_and_fs')
    def assertIsPartitionCalled(self, called, mock_resize_part_and_fs):
        context.RequestContext(self.user_id, self.project_id)
        session = get_session()

        disk_image_type = vm_utils.ImageType.DISK_VHD
        instance = create_instance_with_system_metadata(self.context,
                                                        self.instance_values)
        vm_ref = xenapi_fake.create_vm(instance['name'], 'Halted')
        vdi_ref = xenapi_fake.create_vdi(instance['name'], 'fake')

        vdi_uuid = session.call_xenapi('VDI.get_record', vdi_ref)['uuid']
        vdis = {'root': {'uuid': vdi_uuid, 'ref': vdi_ref}}
        image_meta = objects.ImageMeta.from_dict(
            {'id': uuids.image_id,
             'disk_format': 'vhd',
             'properties': {'vm_mode': 'xen'}})

        self.conn._vmops._attach_disks(self.context, instance, image_meta,
                vm_ref, instance['name'], vdis, disk_image_type,
                "fake_nw_inf")

        if called:
            mock_resize_part_and_fs.assert_called()
        else:
            mock_resize_part_and_fs.assert_not_called()

    def test_instance_not_auto_disk_config(self):
        """Should not partition unless instance is marked as
        auto_disk_config.
        """
        self.instance_values['auto_disk_config'] = False
        self.assertIsPartitionCalled(False)

    @stub_vm_utils_with_vdi_attached
    @mock.patch.object(vm_utils, '_get_partitions',
                       return_value=[(1, 0, 100, 'ext4', "", ""),
                                     (2, 100, 200, 'ext4' "", "")])
    def test_instance_auto_disk_config_fails_safe_two_partitions(
            self, mock_get_partitions):
        # Should not partition unless fail safes pass.
        self.instance_values['auto_disk_config'] = True

        self.assertIsPartitionCalled(False)
        mock_get_partitions.assert_called_once_with('fakedev')

    @stub_vm_utils_with_vdi_attached
    @mock.patch.object(vm_utils, '_get_partitions',
                       return_value=[(2, 100, 200, 'ext4', "", "")])
    def test_instance_auto_disk_config_fails_safe_badly_numbered(
            self, mock_get_partitions):
        # Should not partition unless fail safes pass.
        self.instance_values['auto_disk_config'] = True
        self.assertIsPartitionCalled(False)
        mock_get_partitions.assert_called_once_with('fakedev')

    @stub_vm_utils_with_vdi_attached
    @mock.patch.object(vm_utils, '_get_partitions',
                       return_value=[(1, 100, 200, 'asdf', "", "")])
    def test_instance_auto_disk_config_fails_safe_bad_fstype(
            self, mock_get_partitions):
        # Should not partition unless fail safes pass.
        self.instance_values['auto_disk_config'] = True
        self.assertIsPartitionCalled(False)
        mock_get_partitions.assert_called_once_with('fakedev')

    @stub_vm_utils_with_vdi_attached
    @mock.patch.object(vm_utils, '_get_partitions',
                       return_value=[(1, 0, 100, 'ext4', "", "boot")])
    def test_instance_auto_disk_config_passes_fail_safes(
            self, mock_get_partitions):
        """Should partition if instance is marked as auto_disk_config=True and
        virt-layer specific fail-safe checks pass.
        """
        self.instance_values['auto_disk_config'] = True
        self.assertIsPartitionCalled(True)
        mock_get_partitions.assert_called_once_with('fakedev')


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIGenerateLocal(stubs.XenAPITestBase):
    """Test generating of local disks, like swap and ephemeral."""
    def setUp(self):
        super(XenAPIGenerateLocal, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        db_fakes.stub_out_db_instance_api(self)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': IMAGE_MACHINE,
                  'kernel_id': IMAGE_KERNEL,
                  'ramdisk_id': IMAGE_RAMDISK,
                  'root_gb': 80,
                  'ephemeral_gb': 0,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        def fake_create_vbd(session, vm_ref, vdi_ref, userdevice,
                            vbd_type='disk', read_only=False, bootable=True,
                            osvol=False, empty=False, unpluggable=True):
            return session.call_xenapi('VBD.create', {'VM': vm_ref,
                                                      'VDI': vdi_ref})

        self.stub_out('nova.virt.xenapi.vm_utils.create_vbd', fake_create_vbd)

    def assertCalled(self, instance,
                     disk_image_type=vm_utils.ImageType.DISK_VHD):
        context.RequestContext(self.user_id, self.project_id)
        session = get_session()

        vm_ref = xenapi_fake.create_vm(instance['name'], 'Halted')
        vdi_ref = xenapi_fake.create_vdi(instance['name'], 'fake')

        vdi_uuid = session.call_xenapi('VDI.get_record', vdi_ref)['uuid']

        vdi_key = 'root'
        if disk_image_type == vm_utils.ImageType.DISK_ISO:
            vdi_key = 'iso'
        vdis = {vdi_key: {'uuid': vdi_uuid, 'ref': vdi_ref}}
        image_meta = objects.ImageMeta.from_dict(
            {'id': uuids.image_id,
             'disk_format': 'vhd',
             'properties': {'vm_mode': 'xen'}})
        self.conn._vmops._attach_disks(self.context, instance, image_meta,
                    vm_ref, instance['name'], vdis, disk_image_type,
                    "fake_nw_inf")

    @mock.patch.object(vm_utils, 'generate_swap')
    def test_generate_swap(self, mock_generate_swap):
        # Test swap disk generation.
        instance_values = dict(self.instance_values, instance_type_id=5)
        instance = create_instance_with_system_metadata(self.context,
                                                        instance_values)
        self.assertCalled(instance)
        self.assertTrue(mock_generate_swap.called)

    @mock.patch.object(vm_utils, 'generate_ephemeral')
    def test_generate_ephemeral(self, mock_generate_ephemeral):
        # Test ephemeral disk generation.
        instance_values = dict(self.instance_values, instance_type_id=4)
        instance = create_instance_with_system_metadata(self.context,
                                                        instance_values)
        self.assertCalled(instance)
        self.assertTrue(mock_generate_ephemeral.called)

    @mock.patch.object(
        uuidutils, 'generate_uuid',
        new=mock.Mock(return_value='98e2a239-5a96-4a72-840f-2c3836482461'))
    @mock.patch.object(vm_utils, 'generate_iso_blank_root_disk')
    @mock.patch.object(vm_utils, 'generate_ephemeral')
    def test_generate_iso_blank_root_disk(
            self, mock_generate_ephemeral, mock_generate_iso_blank_root_disk):
        instance_values = dict(self.instance_values, instance_type_id=4)
        instance_values.pop('kernel_id')
        instance_values.pop('ramdisk_id')
        instance = create_instance_with_system_metadata(self.context,
                                                        instance_values)
        self.assertCalled(instance, vm_utils.ImageType.DISK_ISO)
        mock_generate_ephemeral.assert_called_once_with(
            test.MatchType(session.XenAPISession),
            instance, '98e2a239-5a96-4a72-840f-2c3836482461', '4',
            'instance-00000001', 160)
        self.assertTrue(mock_generate_iso_blank_root_disk.called)


class XenAPIBWCountersTestCase(stubs.XenAPITestBaseNoDB):
    FAKE_VMS = {'test1:ref': dict(name_label='test1',
                                   other_config=dict(nova_uuid='hash'),
                                   domid='12',
                                   _vifmap={'0': "a:b:c:d...",
                                           '1': "e:f:12:q..."}),
                'test2:ref': dict(name_label='test2',
                                   other_config=dict(nova_uuid='hash'),
                                   domid='42',
                                   _vifmap={'0': "a:3:c:d...",
                                           '1': "e:f:42:q..."}),
               }

    def setUp(self):
        super(XenAPIBWCountersTestCase, self).setUp()
        self.stub_out('nova.virt.xenapi.vm_utils.list_vms',
                      XenAPIBWCountersTestCase._fake_list_vms)
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        def _fake_get_vif_device_map(self, vm_rec):
            return vm_rec['_vifmap']

        self.stub_out('nova.virt.xenapi.vmops.VMOps._get_vif_device_map',
                      _fake_get_vif_device_map)

    @classmethod
    def _fake_list_vms(cls, session):
        return cls.FAKE_VMS.items()

    @staticmethod
    def _fake_fetch_bandwidth_mt(session):
        return {}

    @mock.patch.object(vm_utils, 'fetch_bandwidth',
                       return_value={
                           '42': {'0': {'bw_in': 21024, 'bw_out': 22048},
                                  '1': {'bw_in': 231337, 'bw_out': 221212121}},
                           '12':
                                 {'0': {'bw_in': 1024, 'bw_out': 2048},
                                  '1': {'bw_in': 31337, 'bw_out': 21212121}}})
    def test_get_all_bw_counters(self, mock_fetch_bandwidth):
        instances = [dict(name='test1', uuid='1-2-3'),
                     dict(name='test2', uuid='4-5-6')]
        result = self.conn.get_all_bw_counters(instances)
        self.assertEqual(4, len(result))
        self.assertIn(dict(uuid='1-2-3',
                           mac_address="a:b:c:d...",
                           bw_in=1024,
                           bw_out=2048), result)
        self.assertIn(dict(uuid='1-2-3',
                           mac_address="e:f:12:q...",
                           bw_in=31337,
                           bw_out=21212121), result)

        self.assertIn(dict(uuid='4-5-6',
                           mac_address="a:3:c:d...",
                           bw_in=21024,
                           bw_out=22048), result)
        self.assertIn(dict(uuid='4-5-6',
                           mac_address="e:f:42:q...",
                           bw_in=231337,
                           bw_out=221212121), result)
        mock_fetch_bandwidth.assert_called_once_with(
            test.MatchType(session.XenAPISession))

    @mock.patch.object(vm_utils, 'fetch_bandwidth',
                       new=mock.Mock(return_value={}))
    def test_get_all_bw_counters_in_failure_case(self):
        """Test that get_all_bw_conters returns an empty list when
        no data returned from Xenserver.  c.f. bug #910045.
        """
        instances = [dict(name='instance-0001', uuid='1-2-3-4-5')]
        result = self.conn.get_all_bw_counters(instances)
        self.assertEqual(result, [])


# TODO(salvatore-orlando): this class and
# nova.tests.unit.virt.test_libvirt.IPTablesFirewallDriverTestCase
# share a lot of code.  Consider abstracting common code in a base
# class for firewall driver testing.
#
# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIDom0IptablesFirewallTestCase(stubs.XenAPITestBase):

    REQUIRES_LOCKING = True

    _in_rules = [
      '# Generated by iptables-save v1.4.10 on Sat Feb 19 00:03:19 2011',
      '*nat',
      ':PREROUTING ACCEPT [1170:189210]',
      ':INPUT ACCEPT [844:71028]',
      ':OUTPUT ACCEPT [5149:405186]',
      ':POSTROUTING ACCEPT [5063:386098]',
      '# Completed on Mon Dec  6 11:54:13 2010',
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*mangle',
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
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.user_id = 'mappin'
        self.project_id = 'fake'
        stubs.stubout_session(self, stubs.FakeSessionForFirewallTests,
                              test_case=self)
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.network = importutils.import_object(CONF.network_manager)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
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
        in_rules = [l for l in self._in_rules if not l.startswith('#')]
        for rule in in_rules:
            if 'nova' not in rule:
                self.assertIn(rule, self._out_rules,
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

        regex = re.compile(r'\[0\:0\] -A .* -j ACCEPT -p icmp'
                           ' -s 192.168.11.0/24')
        match_rules = [rule for rule in self._out_rules if regex.match(rule)]
        self.assertGreater(len(match_rules), 0,
                           "ICMP acceptance rule wasn't added")

        regex = re.compile(r'\[0\:0\] -A .* -j ACCEPT -p icmp -m icmp'
                           ' --icmp-type 8 -s 192.168.11.0/24')
        match_rules = [rule for rule in self._out_rules if regex.match(rule)]
        self.assertGreater(len(match_rules), 0,
                           "ICMP Echo Request acceptance rule wasn't added")

        regex = re.compile(r'\[0\:0\] -A .* -j ACCEPT -p tcp --dport 80:81'
                           ' -s 192.168.10.0/24')
        match_rules = [rule for rule in self._out_rules if regex.match(rule)]
        self.assertGreater(len(match_rules), 0,
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

        network_model = fake_network.fake_get_instance_nw_info(self, 1)

        self.stub_out('nova.objects.Instance.get_network_info',
                      lambda instance: network_model)

        self.fw.prepare_instance_filter(instance_ref, network_model)
        self.fw.apply_instance_filter(instance_ref, network_model)

        self._validate_security_group()
        # Extra test for TCP acceptance rules
        for ip in network_model.fixed_ips():
            if ip['version'] != 4:
                continue
            regex = re.compile(r'\[0\:0\] -A .* -j ACCEPT -p tcp'
                               ' --dport 80:81 -s %s' % ip['address'])
            match_rules = [rule for rule in self._out_rules
                           if regex.match(rule)]
            self.assertGreater(len(match_rules), 0,
                               "TCP port 80/81 acceptance rule wasn't added")

        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_filters_for_instance_with_ip_v6(self):
        self.flags(use_ipv6=True)
        network_info = fake_network.fake_get_instance_nw_info(self, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEqual(len(rulesv4), 2)
        self.assertEqual(len(rulesv6), 1)

    def test_filters_for_instance_without_ip_v6(self):
        self.flags(use_ipv6=False)
        network_info = fake_network.fake_get_instance_nw_info(self, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEqual(len(rulesv4), 2)
        self.assertEqual(len(rulesv6), 0)

    def test_multinic_iptables(self):
        ipv4_rules_per_addr = 1
        ipv4_addr_per_network = 2
        ipv6_rules_per_addr = 1
        ipv6_addr_per_network = 1
        networks_count = 5
        instance_ref = self._create_instance_ref()
        _get_instance_nw_info = fake_network.fake_get_instance_nw_info
        network_info = _get_instance_nw_info(self,
                                             networks_count,
                                             ipv4_addr_per_network)
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
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
        self.assertEqual(ipv4_network_rules, rules)
        self.assertEqual(ipv6_network_rules,
                  ipv6_rules_per_addr * ipv6_addr_per_network * networks_count)

    def test_do_refresh_security_group_rules(self):
        admin_ctxt = context.get_admin_context()
        instance_ref = self._create_instance_ref()
        network_info = fake_network.fake_get_instance_nw_info(self, 1, 1)
        secgroup = self._create_test_security_group()
        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.instance_info[instance_ref['id']] = (instance_ref,
                                                     network_info)
        self._validate_security_group()
        # add a rule to the security group
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'udp',
                                       'from_port': 200,
                                       'to_port': 299,
                                       'cidr': '192.168.99.0/24'})
        # validate the extra rule
        self.fw.refresh_security_group_rules(secgroup)
        regex = re.compile(r'\[0\:0\] -A .* -j ACCEPT -p udp --dport 200:299'
                           ' -s 192.168.99.0/24')
        match_rules = [rule for rule in self._out_rules if regex.match(rule)]
        self.assertGreater(len(match_rules), 0,
                           "Rules were not updated properly. "
                           "The rule for UDP acceptance is missing")


class XenAPISRSelectionTestCase(stubs.XenAPITestBaseNoDB):
    """Unit tests for testing we find the right SR."""
    def test_safe_find_sr_raise_exception(self):
        # Ensure StorageRepositoryNotFound is raise when wrong filter.
        self.flags(sr_matching_filter='yadayadayada', group='xenserver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        session = get_session()
        self.assertRaises(exception.StorageRepositoryNotFound,
                          vm_utils.safe_find_sr, session)

    def test_safe_find_sr_local_storage(self):
        # Ensure the default local-storage is found.
        self.flags(sr_matching_filter='other-config:i18n-key=local-storage',
                   group='xenserver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        session = get_session()
        # This test is only guaranteed if there is one host in the pool
        self.assertEqual(len(xenapi_fake.get_all('host')), 1)
        host_ref = xenapi_fake.get_all('host')[0]
        pbd_refs = xenapi_fake.get_all('PBD')
        for pbd_ref in pbd_refs:
            pbd_rec = xenapi_fake.get_record('PBD', pbd_ref)
            if pbd_rec['host'] != host_ref:
                continue
            sr_rec = xenapi_fake.get_record('SR', pbd_rec['SR'])
            if sr_rec['other_config']['i18n-key'] == 'local-storage':
                local_sr = pbd_rec['SR']
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_by_other_criteria(self):
        # Ensure the SR is found when using a different filter.
        self.flags(sr_matching_filter='other-config:my_fake_sr=true',
                   group='xenserver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        session = get_session()
        host_ref = xenapi_fake.get_all('host')[0]
        local_sr = xenapi_fake.create_sr(name_label='Fake Storage',
                                         type='lvm',
                                         other_config={'my_fake_sr': 'true'},
                                         host_ref=host_ref)
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_default(self):
        # Ensure the default SR is found regardless of other-config.
        self.flags(sr_matching_filter='default-sr:true',
                   group='xenserver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        session = get_session()
        pool_ref = session.call_xenapi('pool.get_all')[0]
        expected = vm_utils.safe_find_sr(session)
        self.assertEqual(session.call_xenapi('pool.get_default_SR', pool_ref),
                         expected)


def _create_service_entries(context, values={'avail_zone1': ['fake_host1',
                                                         'fake_host2'],
                                         'avail_zone2': ['fake_host3'], }):
    for hosts in values.values():
        for service_host in hosts:
            db.service_create(context,
                              {'host': service_host,
                               'binary': 'nova-compute',
                               'topic': 'compute',
                               'report_count': 0})
    return values


# FIXME(sirp): convert this to use XenAPITestBaseNoDB
class XenAPIAggregateTestCase(stubs.XenAPITestBase):
    """Unit tests for aggregate operations."""
    def setUp(self):
        super(XenAPIAggregateTestCase, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_username='test_user',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   host='host',
                   compute_driver='xenapi.XenAPIDriver',
                   default_availability_zone='avail_zone1')
        host_ref = xenapi_fake.get_all('host')[0]
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.context = context.get_admin_context()
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.compute = manager.ComputeManager()
        self.api = compute_api.AggregateAPI()
        values = {'name': 'test_aggr',
                  'metadata': {'availability_zone': 'test_zone',
                  pool_states.POOL_FLAG: 'XenAPI'}}
        self.aggr = objects.Aggregate(context=self.context, id=1,
                                      **values)
        self.fake_metadata = {pool_states.POOL_FLAG: 'XenAPI',
                              'master_compute': 'host',
                              'availability_zone': 'fake_zone',
                              pool_states.KEY: pool_states.ACTIVE,
                              'host': xenapi_fake.get_record('host',
                                                             host_ref)['uuid']}
        self.useFixture(fixtures.SingleCellSimple())

    @mock.patch('nova.virt.xenapi.pool.ResourcePool.add_to_aggregate')
    def test_pool_add_to_aggregate_called_by_driver(
            self, mock_add_to_aggregate):
        def pool_add_to_aggregate(context, aggregate, host, slave_info=None):
            self.assertEqual("CONTEXT", context)
            self.assertEqual("AGGREGATE", aggregate)
            self.assertEqual("HOST", host)
            self.assertEqual("SLAVEINFO", slave_info)
        mock_add_to_aggregate.side_effect = pool_add_to_aggregate

        self.conn.add_to_aggregate("CONTEXT", "AGGREGATE", "HOST",
                                   slave_info="SLAVEINFO")

        self.assertTrue(mock_add_to_aggregate.called)

    @mock.patch('nova.virt.xenapi.pool.ResourcePool.remove_from_aggregate')
    def test_pool_remove_from_aggregate_called_by_driver(
            self, mock_remove_from_aggregate):
        def pool_remove_from_aggregate(context, aggregate, host,
                                       slave_info=None):
            self.assertEqual("CONTEXT", context)
            self.assertEqual("AGGREGATE", aggregate)
            self.assertEqual("HOST", host)
            self.assertEqual("SLAVEINFO", slave_info)
        mock_remove_from_aggregate.side_effect = pool_remove_from_aggregate
        self.conn.remove_from_aggregate("CONTEXT", "AGGREGATE", "HOST",
                                        slave_info="SLAVEINFO")

        self.assertTrue(mock_remove_from_aggregate.called)

    @mock.patch('nova.virt.xenapi.pool.ResourcePool._init_pool')
    def test_add_to_aggregate_for_first_host_sets_metadata(
            self, mock_init_pool):
        aggregate = self._aggregate_setup()
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        result = objects.Aggregate.get_by_id(self.context, aggregate.id)
        self.assertTrue(mock_init_pool.called)
        self.assertThat(self.fake_metadata,
                        matchers.DictMatches(result.metadata))

    @mock.patch('nova.virt.xenapi.pool.ResourcePool._join_slave')
    def test_join_slave(self, mock_join_slave):
        # Ensure join_slave gets called when the request gets to master.
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host2",
                                         dict(compute_uuid='fake_uuid',
                                         url='fake_url',
                                         user='fake_user',
                                         passwd='fake_pass',
                                         xenhost_uuid='fake_uuid'))
        self.assertTrue(mock_join_slave.called)

    @mock.patch.object(xenapi_fake.SessionBase, 'pool_set_name_label')
    def test_add_to_aggregate_first_host(self, mock_pool_set_name_label):
        self.conn._session.call_xenapi("pool.create", {"name": "asdf"})

        metadata = {'availability_zone': 'fake_zone',
                    pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.CREATED}

        aggregate = objects.Aggregate(context=self.context)
        aggregate.name = 'fake_aggregate'
        aggregate.metadata = dict(metadata)
        aggregate.create()
        aggregate.add_host('host')
        self.assertEqual(["host"], aggregate.hosts)
        self.assertEqual(metadata, aggregate.metadata)

        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        self.assertTrue(mock_pool_set_name_label.called)

    @mock.patch('nova.virt.xenapi.pool.ResourcePool.remove_from_aggregate')
    def test_remove_from_aggregate_called(self, mock_remove_from_aggregate):
        self.conn.remove_from_aggregate(None, None, None)
        self.assertTrue(mock_remove_from_aggregate.called)

    def test_remove_from_empty_aggregate(self):
        result = self._aggregate_setup()
        self.assertRaises(exception.InvalidAggregateActionDelete,
                          self.conn._pool.remove_from_aggregate,
                          self.context, result, "test_host")

    @mock.patch('nova.virt.xenapi.pool.ResourcePool._eject_slave')
    def test_remove_slave(self, mock_eject_slave):
        # Ensure eject slave gets called.
        self.fake_metadata['host2'] = 'fake_host2_uuid'
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                metadata=self.fake_metadata, aggr_state=pool_states.ACTIVE)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host2")
        self.assertTrue(mock_eject_slave.called)

    @mock.patch('nova.virt.xenapi.pool.ResourcePool._clear_pool')
    def test_remove_master_solo(self, mock_clear_pool):
        # Ensure metadata are cleared after removal.
        aggregate = self._aggregate_setup(metadata=self.fake_metadata)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host")
        result = objects.Aggregate.get_by_id(self.context, aggregate.id)
        self.assertTrue(mock_clear_pool.called)
        self.assertThat({'availability_zone': 'fake_zone',
                pool_states.POOL_FLAG: 'XenAPI',
                pool_states.KEY: pool_states.ACTIVE},
                matchers.DictMatches(result.metadata))

    def test_remote_master_non_empty_pool(self):
        # Ensure AggregateError is raised if removing the master.
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)

        self.assertRaises(exception.InvalidAggregateActionDelete,
                          self.conn._pool.remove_from_aggregate,
                          self.context, aggregate, "host")

    def _aggregate_setup(self, aggr_name='fake_aggregate',
                         aggr_zone='fake_zone',
                         aggr_state=pool_states.CREATED,
                         hosts=['host'], metadata=None):
        aggregate = objects.Aggregate(context=self.context)
        aggregate.name = aggr_name
        aggregate.metadata = {'availability_zone': aggr_zone,
                              pool_states.POOL_FLAG: 'XenAPI',
                              pool_states.KEY: aggr_state,
                              }
        if metadata:
            aggregate.metadata.update(metadata)
        aggregate.create()
        for aggregate_host in hosts:
            aggregate.add_host(aggregate_host)
        return aggregate

    def test_add_host_to_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateActionAdd is raised when adding host while
        aggregate is not ready.
        """
        aggregate = self._aggregate_setup(aggr_state=pool_states.CHANGING)
        ex = self.assertRaises(exception.InvalidAggregateActionAdd,
                               self.conn.add_to_aggregate, self.context,
                               aggregate, 'host')
        self.assertIn('setup in progress', str(ex))

    def test_add_host_to_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateActionAdd is raised when aggregate is
        deleted.
        """
        aggregate = self._aggregate_setup(aggr_state=pool_states.DISMISSED)
        ex = self.assertRaises(exception.InvalidAggregateActionAdd,
                               self.conn.add_to_aggregate, self.context,
                               aggregate, 'fake_host')
        self.assertIn('aggregate deleted', str(ex))

    def test_add_host_to_aggregate_invalid_error_status(self):
        """Ensure InvalidAggregateActionAdd is raised when aggregate is
        in error.
        """
        aggregate = self._aggregate_setup(aggr_state=pool_states.ERROR)
        ex = self.assertRaises(exception.InvalidAggregateActionAdd,
                               self.conn.add_to_aggregate, self.context,
                               aggregate, 'fake_host')
        self.assertIn('aggregate in error', str(ex))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_remove_host')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    def test_remove_host_from_aggregate_error(
            self, mock_add_host, mock_remove_host):
        # Ensure we can remove a host from an aggregate even if in error.
        values = _create_service_entries(self.context)
        fake_zone = list(values.keys())[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        # let's mock the fact that the aggregate is ready!
        metadata = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.ACTIVE}
        self.api.update_aggregate_metadata(self.context,
                                           aggr.id,
                                           metadata)
        for aggregate_host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr.id, aggregate_host)
        # let's mock the fact that the aggregate is in error!
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr.id,
                                                       values[fake_zone][0])
        self.assertEqual(len(aggr.hosts) - 1, len(expected.hosts))
        self.assertEqual(expected.metadata[pool_states.KEY],
                         pool_states.ACTIVE)

    def test_remove_host_from_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateActionDelete is raised when aggregate is
        deleted.
        """
        aggregate = self._aggregate_setup(aggr_state=pool_states.DISMISSED)
        self.assertRaises(exception.InvalidAggregateActionDelete,
                          self.conn.remove_from_aggregate, self.context,
                          aggregate, 'fake_host')

    def test_remove_host_from_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateActionDelete is raised when aggregate is
        changing.
        """
        aggregate = self._aggregate_setup(aggr_state=pool_states.CHANGING)
        self.assertRaises(exception.InvalidAggregateActionDelete,
                          self.conn.remove_from_aggregate, self.context,
                          aggregate, 'fake_host')

    @mock.patch('nova.virt.xenapi.driver.XenAPIDriver.add_to_aggregate',
                new=mock.Mock(
                    side_effect=exception.AggregateError(
                        aggregate_id='', action='', reason='')))
    @mock.patch('nova.compute.utils.notify_about_aggregate_action',
                new=mock.Mock())
    def test_add_aggregate_host_raise_err(self):
        # Ensure the undo operation works correctly on add.
        metadata = {pool_states.POOL_FLAG: "XenAPI",
                    pool_states.KEY: pool_states.ACTIVE}
        self.aggr.metadata = metadata
        self.aggr.hosts = ['fake_host']

        self.assertRaises(exception.AggregateError,
                          self.compute.add_aggregate_host,
                          self.context, host="fake_host",
                          aggregate=self.aggr,
                          slave_info=None)
        self.assertEqual(self.aggr.metadata[pool_states.KEY],
                pool_states.ERROR)
        self.assertEqual(self.aggr.hosts, ['fake_host'])


class MockComputeAPI(object):
    def __init__(self):
        self._mock_calls = []

    def add_aggregate_host(self, ctxt, aggregate,
                                     host_param, host, slave_info):
        self._mock_calls.append((
            self.add_aggregate_host, ctxt, aggregate,
            host_param, host, slave_info))

    def remove_aggregate_host(self, ctxt, host, aggregate_id, host_param,
                              slave_info):
        self._mock_calls.append((
            self.remove_aggregate_host, ctxt, host, aggregate_id,
            host_param, slave_info))


class StubDependencies(object):
    """Stub dependencies for ResourcePool."""

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
    """A ResourcePool, use stub dependencies."""


class HypervisorPoolTestCase(test.NoDBTestCase):

    fake_aggregate = {
        'id': 98,
        'hosts': [],
        'metadata': {
            'master_compute': 'master',
            pool_states.POOL_FLAG: '',
            pool_states.KEY: ''
            }
        }
    fake_aggregate = objects.Aggregate(**fake_aggregate)

    def test_slave_asks_master_to_add_slave_to_pool(self):
        slave = ResourcePoolWithStubs()

        slave.add_to_aggregate("CONTEXT", self.fake_aggregate, "slave")

        self.assertIn(
            (slave.compute_rpcapi.add_aggregate_host,
            "CONTEXT", "slave", self.fake_aggregate,
            "master", "SLAVE_INFO"),
            slave.compute_rpcapi._mock_calls)

    def test_slave_asks_master_to_remove_slave_from_pool(self):
        slave = ResourcePoolWithStubs()

        slave.remove_from_aggregate("CONTEXT", self.fake_aggregate, "slave")

        self.assertIn(
            (slave.compute_rpcapi.remove_aggregate_host,
             "CONTEXT", "slave", 98, "master", "SLAVE_INFO"),
            slave.compute_rpcapi._mock_calls)


class SwapXapiHostTestCase(test.NoDBTestCase):

    def test_swapping(self):
        self.assertEqual(
            "http://otherserver:8765/somepath",
            pool.swap_xapi_host(
                "http://someserver:8765/somepath", 'otherserver'))

    def test_no_port(self):
        self.assertEqual(
            "http://otherserver/somepath",
            pool.swap_xapi_host(
                "http://someserver/somepath", 'otherserver'))

    def test_no_path(self):
        self.assertEqual(
            "http://otherserver",
            pool.swap_xapi_host(
                "http://someserver", 'otherserver'))


class XenAPILiveMigrateTestCase(stubs.XenAPITestBaseNoDB):
    """Unit tests for live_migration."""
    def setUp(self):
        super(XenAPILiveMigrateTestCase, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   host='host')
        db_fakes.stub_out_db_instance_api(self)
        self.context = context.get_admin_context()

    @mock.patch.object(vmops.VMOps, 'live_migrate')
    def test_live_migration_calls_vmops(self, mock_live_migrate):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.conn.live_migration(None, None, None, None, None)
        self.assertTrue(mock_live_migrate.called)

    def test_pre_live_migration(self):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        with mock.patch.object(self.conn._vmops, "pre_live_migration") as pre:
            pre.return_value = True

            result = self.conn.pre_live_migration(
                    "ctx", "inst", "bdi", "nw", "di", "data")

            self.assertTrue(result)
            pre.assert_called_with("ctx", "inst", "bdi", "nw", "di", "data")

    @mock.patch('nova.virt.firewall.IptablesFirewallDriver.'
                'apply_instance_filter')
    @mock.patch('nova.virt.firewall.IptablesFirewallDriver.'
                'prepare_instance_filter')
    @mock.patch('nova.virt.firewall.IptablesFirewallDriver.'
                'setup_basic_filtering')
    @mock.patch.object(vm_utils, 'create_kernel_and_ramdisk',
                       return_value=('fake-kernel-file', 'fake-ramdisk-file'))
    @mock.patch.object(vm_utils, 'strip_base_mirror_from_vdis')
    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    @mock.patch.object(vmops.VMOps, '_post_start_actions')
    def test_post_live_migration_at_destination(
            self, mock_post_action, mock_get_vm_opaque_ref,
            mock_strip_base_mirror_from_vdis, mock_create_kernel_and_ramdisk,
            mock_setup_basic_filtering, mock_prepare_instance_filter,
            mock_apply_instance_filter):
        # ensure method is present
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        fake_instance = {"name": "fake-name"}
        fake_network_info = "network_info"

        self.conn.post_live_migration_at_destination(
            self.context, fake_instance, fake_network_info, None)
        self.assertTrue(mock_get_vm_opaque_ref.called)
        self.assertTrue(mock_strip_base_mirror_from_vdis.called)
        mock_post_action.assert_called_once_with(fake_instance)
        mock_create_kernel_and_ramdisk.assert_called_once_with(
            self.context, self.conn._session, fake_instance,
            fake_instance['name'])
        mock_setup_basic_filtering.assert_called_once_with(fake_instance,
                                                           fake_network_info)
        mock_prepare_instance_filter.assert_called_once_with(fake_instance,
                                                             fake_network_info)
        mock_apply_instance_filter.assert_called_once_with(fake_instance,
                                                           fake_network_info)

    @mock.patch.object(vm_utils, 'host_in_this_pool')
    def test_check_can_live_migrate_destination_with_block_migration(
            self,
            mock_same_pool):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        fake_instance = objects.Instance(host="fake_host")

        self.stub_out('nova.virt.xenapi.vm_utils.safe_find_sr',
                      lambda _x: 'asdf')
        with mock.patch.object(self.conn._vmops._session, "host_ref") as \
                fake_host_ref, mock.patch.object(
                    self.conn._vmops, '_get_network_ref') as \
                fake_get_network_ref, mock.patch.object(
                    self.conn._vmops, '_get_host_opaque_ref'):
            fake_host_ref.return_value = 'fake_host_ref'
            fake_get_network_ref.return_value = 'fake_network_ref'
            expected = {'block_migration': True,
                        'is_volume_backed': False,
                        'migrate_send_data': {'value': 'fake_migrate_data'},
                        'destination_sr_ref': 'asdf',
                        'vif_uuid_map': {'': 'fake_network_ref'}}
            result = self.conn.check_can_live_migrate_destination(
                self.context,
                fake_instance,
                {}, {},
                True, False)
            result.is_volume_backed = False
            self.assertEqual(expected,
                             result.obj_to_primitive()['nova_object.data'])

    def test_check_live_migrate_destination_verifies_ip(self):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        fake_instance = objects.Instance(host="fake_host")

        for pif_ref in xenapi_fake.get_all('PIF'):
            pif_rec = xenapi_fake.get_record('PIF', pif_ref)
            pif_rec['IP'] = ''
            pif_rec['IPv6'] = ''

        self.stub_out('nova.virt.xenapi.vm_utils.safe_find_sr',
                      lambda _x: 'asdf')

        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_destination,
                          self.context, fake_instance,
                          {}, {},
                          True, False)

    def test_check_can_live_migrate_destination_block_migration_fails(self):

        fake_instance = objects.Instance(host="fake_host")

        stubs.stubout_session(self, stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_destination,
                          self.context, fake_instance,
                          {}, {},
                          True, False)

    def _add_default_live_migrate_stubs(self, conn):
        @classmethod
        def fake_generate_vdi_map(cls, destination_sr_ref, _vm_ref):
            pass

        @classmethod
        def fake_get_iscsi_srs(cls, destination_sr_ref, _vm_ref):
            return []

        @classmethod
        def fake_get_vm_opaque_ref(cls, instance):
            return "fake_vm"

        def fake_lookup_kernel_ramdisk(session, vm):
            return ("fake_PV_kernel", "fake_PV_ramdisk")

        @classmethod
        def fake_generate_vif_map(cls, vif_uuid_map):
            return {'vif_ref1': 'dest_net_ref'}

        self.stub_out('nova.virt.xenapi.vmops.VMOps._generate_vdi_map',
                      fake_generate_vdi_map)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._get_iscsi_srs',
                      fake_get_iscsi_srs)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._get_vm_opaque_ref',
                      fake_get_vm_opaque_ref)
        self.stub_out('nova.virt.xenapi.vm_utils.lookup_kernel_ramdisk',
                      fake_lookup_kernel_ramdisk)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._generate_vif_network_map',
                      fake_generate_vif_map)

    def test_check_can_live_migrate_source_with_block_migrate(self):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        dest_check_data = objects.XenapiLiveMigrateData(
            block_migration=True, is_volume_backed=False,
            destination_sr_ref=None, migrate_send_data={'key': 'value'})
        result = self.conn.check_can_live_migrate_source(self.context,
                                                         {'host': 'host'},
                                                         dest_check_data)
        self.assertEqual(dest_check_data, result)

    def test_check_can_live_migrate_source_with_block_migrate_iscsi(self):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)
        dest_check_data = objects.XenapiLiveMigrateData(
            block_migration=True,
            is_volume_backed=True,
            destination_sr_ref=None,
            migrate_send_data={'key': 'value'})
        result = self.conn.check_can_live_migrate_source(self.context,
                                                         {'host': 'host'},
                                                         dest_check_data)
        self.assertEqual(dest_check_data, result)

    @mock.patch.object(session.XenAPISession, 'is_xsm_sr_check_relaxed',
                       return_value=False)
    def test_check_can_live_migrate_source_with_block_iscsi_fails(
            self, mock_is_xsm_sr_check_relaxed):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        with mock.patch.object(vmops.VMOps, '_get_iscsi_srs',
                               return_value=['sr_ref']):
            self.assertRaises(exception.MigrationError,
                              self.conn.check_can_live_migrate_source,
                              self.context, {'host': 'host'},
                              {})
        mock_is_xsm_sr_check_relaxed.assert_called_once_with()

    def test_check_can_live_migrate_source_with_block_migrate_fails(self):
        stubs.stubout_session(self, stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        dest_check_data = objects.XenapiLiveMigrateData(
            block_migration=True, is_volume_backed=True,
            migrate_send_data={'key': 'value'}, destination_sr_ref=None)
        self.assertRaises(exception.MigrationError,
                          self.conn.check_can_live_migrate_source,
                          self.context,
                          {'host': 'host'},
                          dest_check_data)

    @mock.patch.object(vm_utils, 'host_in_this_pool')
    def test_check_can_live_migrate_works(self,
                                          mock_host_in_this_pool):
        # The dest host is in the same pool with the src host, do no block
        # live migrate
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        mock_host_in_this_pool.side_effect = [True, True]
        with mock.patch.object(self.conn._vmops, "_get_host_opaque_ref") as \
                fake_get_host_opaque_ref, \
                mock.patch.object(self.conn._vmops, '_get_network_ref') as \
                fake_get_network_ref, \
                mock.patch.object(self.conn._vmops._session, 'get_rec') as \
                fake_get_rec:
            fake_host_ref = 'fake_host_ref'
            fake_get_host_opaque_ref.return_value = fake_host_ref
            fake_network_ref = 'fake_network_ref'
            fake_get_network_ref.return_value = fake_network_ref
            fake_get_rec.return_value = {'shared': True}
            fake_host_name = 'fake_host'
            instance = objects.Instance(host=fake_host_name)

            # Set block_migration to None to enable pool check, then do pooled
            # live migrate
            dest_check_data = self.conn.check_can_live_migrate_destination(
                self.context, instance, 'fake_src_compute_info',
                'fake_dst_compute_info', None, None)
            self.assertFalse(dest_check_data.block_migration)
            self.assertEqual(dest_check_data.vif_uuid_map,
                             {'': fake_network_ref})
            fake_get_host_opaque_ref.assert_called_once_with(fake_host_name)
            mock_host_in_this_pool.assert_called_once_with(
                self.conn._vmops._session, fake_host_ref)
            fake_get_network_ref.assert_called_once()

    @mock.patch.object(vm_utils, 'host_in_this_pool')
    def test_check_can_live_migrate_fails(self, mock_host_in_this_pool):
        # Caller asks for no block live migrate while the dest host is not in
        # the same pool with the src host, raise exception
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        mock_host_in_this_pool.return_value = False
        with mock.patch.object(self.conn._vmops, "_get_host_opaque_ref") as \
                fake_get_host_opaque_ref, \
                mock.patch.object(self.conn._vmops, '_get_network_ref') as \
                fake_get_network_ref:
            fake_host_ref = 'fake_host_ref'
            fake_get_host_opaque_ref.return_value = fake_host_ref
            fake_network_ref = 'fake_network_ref'
            fake_get_network_ref.return_value = fake_network_ref
            fake_host_name = 'fake_host'
            instance = objects.Instance(host=fake_host_name)

            # Set block_migration to False to do pooled live migrate
            self.assertRaises(exception.MigrationPreCheckError,
                              self.conn.check_can_live_migrate_destination,
                              self.context, instance, 'fake_src_compute_info',
                              'fake_dst_compute_info', False, None)

            fake_get_host_opaque_ref.assert_called_once_with(fake_host_name)
            mock_host_in_this_pool.assert_called_once_with(
                self.conn._vmops._session, fake_host_ref)
            fake_get_network_ref.assert_not_called()

    @mock.patch.object(vmops.VMOps, '_get_host_opaque_ref',
                       return_value='fake_host')
    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref',
                       return_value='fake_vm')
    @mock.patch.object(vm_utils, 'lookup_kernel_ramdisk',
                       return_value=('kernel', 'ramdisk'))
    def test_live_migration(self, mock_lookup_kernel_ramdisk,
                            mock_get_vm_opaque_ref, mock_get_host_opaque_ref):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        def post_method(context, instance, destination_hostname,
                        block_migration, migrate_data):
            post_method.called = True
        migrate_data = objects.XenapiLiveMigrateData(
            destination_sr_ref="foo",
            migrate_send_data={"bar": "baz"},
            block_migration=False)

        fake_instance = mock.Mock()
        self.conn.live_migration(self.context, fake_instance, 'fake-dest',
                                 post_method, None, None, migrate_data)

        self.assertTrue(post_method.called, "post_method was not called")
        mock_lookup_kernel_ramdisk.assert_called_once_with(
            self.conn._session, 'fake_vm')
        mock_get_vm_opaque_ref.assert_called_once_with(fake_instance)
        mock_get_host_opaque_ref.assert_called_once_with('fake-dest')

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref',
                       return_value='fake_vm')
    def test_live_migration_on_failure(self, mock_get_vm_opaque_ref):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        def recover_method(context, instance, destination_hostname,
                           migrate_data=None):
            self.assertIsNotNone(migrate_data, 'migrate_data should be passed')
            recover_method.called = True
        migrate_data = objects.XenapiLiveMigrateData(
            destination_sr_ref="foo",
            migrate_send_data={"bar": "baz"},
            block_migration=False)
        fake_instance = mock.Mock()

        with mock.patch.object(session.XenAPISession, 'call_xenapi',
                               side_effect=NotImplementedError()):
            self.assertRaises(NotImplementedError, self.conn.live_migration,
                              self.context, fake_instance, 'fake-dest', None,
                              recover_method, None, migrate_data)
            self.assertTrue(recover_method.called,
                            "recover_method was not called")
        mock_get_vm_opaque_ref.assert_called_once_with(fake_instance)

    def test_live_migration_calls_post_migration(self):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        def post_method(context, instance, destination_hostname,
                        block_migration, migrate_data):
            post_method.called = True

        # pass block_migration = True and migrate data
        migrate_data = objects.XenapiLiveMigrateData(
            destination_sr_ref="foo",
            migrate_send_data={"bar": "baz"},
            block_migration=True)
        self.conn.live_migration(self.conn, None, None, post_method, None,
                                 True, migrate_data)
        self.assertTrue(post_method.called, "post_method.called")

    @mock.patch.object(volume_utils, 'forget_sr')
    def test_live_migration_block_cleans_srs(self, mock_forget_sr):
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        def post_method(context, instance, destination_hostname,
                        block_migration, migrate_data):
            post_method.called = True

        migrate_data = objects.XenapiLiveMigrateData(
            destination_sr_ref="foo",
            migrate_send_data={"bar": "baz"},
            block_migration=True)

        with mock.patch.object(vmops.VMOps, '_get_iscsi_srs',
                               return_value=['sr_ref']):
            self.conn.live_migration(self.conn, None, None, post_method, None,
                                     True, migrate_data)

            self.assertTrue(post_method.called, "post_method was not called")
            self.assertTrue(mock_forget_sr.called, "forget_sr was not called")

    def test_live_migration_with_block_migration_fails_migrate_send(self):
        stubs.stubout_session(self, stubs.FakeSessionForFailedMigrateTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(self.conn)

        def recover_method(context, instance, destination_hostname,
                           migrate_data=None):
            self.assertIsNotNone(migrate_data, 'migrate_data should be passed')
            recover_method.called = True
        # pass block_migration = True and migrate data
        migrate_data = objects.XenapiLiveMigrateData(
            destination_sr_ref='foo',
            migrate_send_data={'bar': 'baz'},
            block_migration=True)
        self.assertRaises(exception.MigrationError,
                          self.conn.live_migration, self.conn,
                          None, None, None, recover_method, True, migrate_data)
        self.assertTrue(recover_method.called, "recover_method.called")

    def test_live_migrate_block_migration_xapi_call_parameters(self):

        fake_vdi_map = object()

        class Session(xenapi_fake.SessionBase):
            def VM_migrate_send(self_, session, vmref, migrate_data, islive,
                                vdi_map, vif_map, options):
                self.assertEqual({'SOMEDATA': 'SOMEVAL'}, migrate_data)
                self.assertEqual(fake_vdi_map, vdi_map)

        stubs.stubout_session(self, Session)

        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self._add_default_live_migrate_stubs(conn)

        def fake_generate_vdi_map(self, destination_sr_ref, _vm_ref):
            return fake_vdi_map

        self.stub_out('nova.virt.xenapi.vmops.VMOps._generate_vdi_map',
                      fake_generate_vdi_map)

        def dummy_callback(*args, **kwargs):
            pass

        migrate_data = objects.XenapiLiveMigrateData(
            migrate_send_data={'SOMEDATA': 'SOMEVAL'},
            destination_sr_ref='TARGET_SR_OPAQUE_REF',
            block_migration=True)
        conn.live_migration(
            self.context, instance=dict(name='ignore'), dest=None,
            post_method=dummy_callback, recover_method=dummy_callback,
            block_migration="SOMEDATA",
            migrate_data=migrate_data)

    @mock.patch.object(vmops.VMOps, '_get_host_opaque_ref',
                       return_value='fake_ref')
    def test_live_migrate_pool_migration_xapi_call_parameters(
            self, mock_get_host_opaque_ref):

        class Session(xenapi_fake.SessionBase):
            def VM_pool_migrate(self_, session, vm_ref, host_ref, options):
                self.assertEqual("fake_ref", host_ref)
                self.assertEqual({"live": "true"}, options)
                raise IOError()

        stubs.stubout_session(self, Session)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        self._add_default_live_migrate_stubs(conn)

        def dummy_callback(*args, **kwargs):
            pass

        migrate_data = objects.XenapiLiveMigrateData(
            migrate_send_data={'foo': 'bar'},
            destination_sr_ref='foo',
            block_migration=False)
        self.assertRaises(IOError, conn.live_migration,
            self.context, instance=dict(name='ignore'), dest='fake-dest',
            post_method=dummy_callback, recover_method=dummy_callback,
            block_migration=False, migrate_data=migrate_data)
        mock_get_host_opaque_ref.assert_called_once_with('fake-dest')

    @mock.patch.object(vm_utils, 'get_instance_vdis_for_sr')
    @mock.patch.object(vm_utils, 'safe_find_sr')
    def test_generate_vdi_map(self, mock_safe_find_sr,
                              mock_get_instance_vdis_for_sr):
        stubs.stubout_session(self, xenapi_fake.SessionBase)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        vm_ref = "fake_vm_ref"
        mock_safe_find_sr.return_value = 'source_sr_ref'

        mock_get_instance_vdis_for_sr.return_value = ['vdi0', 'vdi1']

        result = conn._vmops._generate_vdi_map("dest_sr_ref", vm_ref)

        self.assertEqual({"vdi0": "dest_sr_ref",
                          "vdi1": "dest_sr_ref"}, result)
        mock_safe_find_sr.assert_called_once_with(conn._session)
        mock_get_instance_vdis_for_sr.assert_called_once_with(
            conn._session, vm_ref, 'source_sr_ref')

    @mock.patch.object(vmops.VMOps, "_delete_networks_and_bridges")
    def test_rollback_live_migration_at_destination(self, mock_delete_network):
        stubs.stubout_session(self, xenapi_fake.SessionBase)
        conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)
        network_info = ["fake_vif1"]
        with mock.patch.object(conn, "destroy") as mock_destroy:
            conn.rollback_live_migration_at_destination("context",
                    "instance", network_info, {'block_device_mapping': []})
            self.assertFalse(mock_destroy.called)
            self.assertTrue(mock_delete_network.called)


class XenAPIInjectMetadataTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(XenAPIInjectMetadataTestCase, self).setUp()
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')
        self.flags(firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self, stubs.FakeSessionForVMTests)
        self.conn = xenapi_conn.XenAPIDriver(fake.FakeVirtAPI(), False)

        self.xenstore = dict(persist={}, ephem={})

        self.called_fake_get_vm_opaque_ref = False

        def fake_get_vm_opaque_ref(inst, instance):
            self.called_fake_get_vm_opaque_ref = True
            if instance["uuid"] == "not_found":
                raise exception.NotFound
            self.assertEqual(instance, {'uuid': 'fake'})
            return 'vm_ref'

        def fake_add_to_param_xenstore(inst, vm_ref, key, val):
            self.assertEqual(vm_ref, 'vm_ref')
            self.xenstore['persist'][key] = val

        def fake_remove_from_param_xenstore(inst, vm_ref, key):
            self.assertEqual(vm_ref, 'vm_ref')
            if key in self.xenstore['persist']:
                del self.xenstore['persist'][key]

        def fake_write_to_xenstore(inst, instance, path, value, vm_ref=None):
            self.assertEqual(instance, {'uuid': 'fake'})
            self.assertEqual(vm_ref, 'vm_ref')
            self.xenstore['ephem'][path] = jsonutils.dumps(value)

        def fake_delete_from_xenstore(inst, instance, path, vm_ref=None):
            self.assertEqual(instance, {'uuid': 'fake'})
            self.assertEqual(vm_ref, 'vm_ref')
            if path in self.xenstore['ephem']:
                del self.xenstore['ephem'][path]

        self.stub_out('nova.virt.xenapi.vmops.VMOps._get_vm_opaque_ref',
                      fake_get_vm_opaque_ref)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._add_to_param_xenstore',
                      fake_add_to_param_xenstore)
        self.stub_out('nova.virt.xenapi.vmops.VMOps.'
                      '_remove_from_param_xenstore',
                      fake_remove_from_param_xenstore)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._write_to_xenstore',
                      fake_write_to_xenstore)
        self.stub_out('nova.virt.xenapi.vmops.VMOps._delete_from_xenstore',
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
                                         {'key': 'sys_c', 'value': 3}],
                        uuid='fake')
        self.conn._vmops._inject_instance_metadata(instance, 'vm_ref')

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
        instance = {'uuid': 'fake'}
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

        self.conn._vmops.change_instance_metadata(instance, diff)

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
        instance = {'uuid': 'fake'}
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

        self.conn._vmops.change_instance_metadata(instance, diff)

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
        instance = {'uuid': 'fake'}
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

        self.conn._vmops.change_instance_metadata(instance, diff)

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

    def test_change_instance_metadata_not_found(self):
        instance = {'uuid': 'not_found'}
        self.conn._vmops.change_instance_metadata(instance, "fake_diff")
        self.assertTrue(self.called_fake_get_vm_opaque_ref)


class XenAPIFakeTestCase(test.NoDBTestCase):
    def test_query_matches(self):
        record = {'a': '1', 'b': '2', 'c_d': '3'}

        tests = {'field "a"="1"': True,
                 'field "b"="2"': True,
                 'field "b"="4"': False,
                 'not field "b"="4"': True,
                 'field "a"="1" and field "b"="4"': False,
                 'field "a"="1" or field "b"="4"': True,
                 'field "c__d"="3"': True,
                 'field \'b\'=\'2\'': True,
                 }

        for query in tests.keys():
            expected = tests[query]
            fail_msg = "for test '%s'" % query
            self.assertEqual(xenapi_fake._query_matches(record, query),
                             expected, fail_msg)

    def test_query_bad_format(self):
        record = {'a': '1', 'b': '2', 'c': '3'}

        tests = ['"a"="1" or "b"="4"',
                 'a=1',
                 ]

        for query in tests:
            fail_msg = "for test '%s'" % query
            self.assertFalse(xenapi_fake._query_matches(record, query),
                             fail_msg)
