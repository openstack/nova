# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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


import contextlib
import fixtures
import mox

from nova.compute import flavors
from nova import exception
from nova import test
from nova import utils
from nova.virt.xenapi import vm_utils


@contextlib.contextmanager
def contextified(result):
    yield result


def _fake_noop(*args, **kwargs):
    return


class LookupTestCase(test.TestCase):

    def setUp(self):
        super(LookupTestCase, self).setUp()
        self.session = self.mox.CreateMockAnything('Fake Session')
        self.name_label = 'my_vm'

    def _do_mock(self, result):
        self.session.call_xenapi(
            "VM.get_by_name_label", self.name_label).AndReturn(result)
        self.mox.ReplayAll()

    def test_normal(self):
        self._do_mock(['x'])
        result = vm_utils.lookup(self.session, self.name_label)
        self.assertEqual('x', result)

    def test_no_result(self):
        self._do_mock([])
        result = vm_utils.lookup(self.session, self.name_label)
        self.assertEqual(None, result)

    def test_too_many(self):
        self._do_mock(['a', 'b'])
        self.assertRaises(exception.InstanceExists,
                          vm_utils.lookup,
                          self.session, self.name_label)

    def test_rescue_none(self):
        self.session.call_xenapi(
            "VM.get_by_name_label", self.name_label + '-rescue').AndReturn([])
        self._do_mock(['x'])
        result = vm_utils.lookup(self.session, self.name_label,
                                 check_rescue=True)
        self.assertEqual('x', result)

    def test_rescue_found(self):
        self.session.call_xenapi(
            "VM.get_by_name_label",
            self.name_label + '-rescue').AndReturn(['y'])
        self.mox.ReplayAll()
        result = vm_utils.lookup(self.session, self.name_label,
                                 check_rescue=True)
        self.assertEqual('y', result)

    def test_rescue_too_many(self):
        self.session.call_xenapi(
            "VM.get_by_name_label",
            self.name_label + '-rescue').AndReturn(['a', 'b', 'c'])
        self.mox.ReplayAll()
        self.assertRaises(exception.InstanceExists,
                          vm_utils.lookup,
                          self.session, self.name_label,
                          check_rescue=True)


class GenerateConfigDriveTestCase(test.TestCase):
    def test_no_admin_pass(self):
        # This is here to avoid masking errors, it shouldn't be used normally
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.xenapi.vm_utils.destroy_vdi', _fake_noop))

        # Mocks
        instance = {}

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr('session').AndReturn('sr_ref')

        self.mox.StubOutWithMock(vm_utils, 'create_vdi')
        vm_utils.create_vdi('session', 'sr_ref', instance, 'config-2',
                            'configdrive',
                            64 * 1024 * 1024).AndReturn('vdi_ref')

        self.mox.StubOutWithMock(vm_utils, 'vdi_attached_here')
        vm_utils.vdi_attached_here(
            'session', 'vdi_ref', read_only=False).AndReturn(
                contextified('mounted_dev'))

        class FakeInstanceMetadata(object):
            def __init__(self, instance, content=None, extra_md=None):
                pass

            def metadata_for_config_drive(self):
                return []

        self.useFixture(fixtures.MonkeyPatch(
                'nova.api.metadata.base.InstanceMetadata',
                FakeInstanceMetadata))

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('genisoimage', '-o', mox.IgnoreArg(), '-ldots',
                      '-allow-lowercase', '-allow-multidot', '-l',
                      '-publisher', mox.IgnoreArg(), '-quiet',
                      '-J', '-r', '-V', 'config-2', mox.IgnoreArg(),
                      attempts=1, run_as_root=False).AndReturn(None)
        utils.execute('dd', mox.IgnoreArg(), mox.IgnoreArg(),
                      run_as_root=True).AndReturn(None)

        self.mox.StubOutWithMock(vm_utils, 'create_vbd')
        vm_utils.create_vbd('session', 'vm_ref', 'vdi_ref', mox.IgnoreArg(),
                            bootable=False, read_only=True).AndReturn(None)

        self.mox.ReplayAll()

        # And the actual call we're testing
        vm_utils.generate_configdrive('session', instance, 'vm_ref',
                                      'userdevice')


class XenAPIGetUUID(test.TestCase):
    def test_get_this_vm_uuid_new_kernel(self):
        self.mox.StubOutWithMock(vm_utils, '_get_sys_hypervisor_uuid')

        vm_utils._get_sys_hypervisor_uuid().AndReturn(
            '2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f')

        self.mox.ReplayAll()
        self.assertEquals('2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f',
                          vm_utils.get_this_vm_uuid())
        self.mox.VerifyAll()

    def test_get_this_vm_uuid_old_kernel_reboot(self):
        self.mox.StubOutWithMock(vm_utils, '_get_sys_hypervisor_uuid')
        self.mox.StubOutWithMock(utils, 'execute')

        vm_utils._get_sys_hypervisor_uuid().AndRaise(
            IOError(13, 'Permission denied'))
        utils.execute('xenstore-read', 'domid', run_as_root=True).AndReturn(
            ('27', ''))
        utils.execute('xenstore-read', '/local/domain/27/vm',
                      run_as_root=True).AndReturn(
            ('/vm/2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f', ''))

        self.mox.ReplayAll()
        self.assertEquals('2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f',
                          vm_utils.get_this_vm_uuid())
        self.mox.VerifyAll()


class FakeSession():
    def call_xenapi(self, *args):
        pass


class FetchVhdImageTestCase(test.TestCase):
    def _apply_stubouts(self):
        self.mox.StubOutWithMock(vm_utils, '_make_uuid_stack')
        self.mox.StubOutWithMock(vm_utils, 'get_sr_path')
        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        self.mox.StubOutWithMock(vm_utils, '_add_bittorrent_params')
        self.mox.StubOutWithMock(vm_utils, '_generate_glance_callback')
        self.mox.StubOutWithMock(vm_utils,
            '_fetch_using_dom0_plugin_with_retry')
        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        self.mox.StubOutWithMock(vm_utils, '_scan_sr')
        self.mox.StubOutWithMock(vm_utils, '_check_vdi_size')
        self.mox.StubOutWithMock(vm_utils, 'destroy_vdi')

    def _common_params_setup(self, uses_bittorrent):
        self.context = "context"
        self.session = FakeSession()
        self.instance = {"uuid": "uuid"}
        self.image_id = "image_id"
        self.uuid_stack = ["uuid_stack"]
        self.sr_path = "sr_path"
        self.params = {'image_id': self.image_id,
            'uuid_stack': self.uuid_stack, 'sr_path': self.sr_path}
        self.vdis = {'root': {'uuid': 'vdi'}}

        vm_utils._make_uuid_stack().AndReturn(self.uuid_stack)
        vm_utils.get_sr_path(self.session).AndReturn(self.sr_path)
        vm_utils._image_uses_bittorrent(self.context,
            self.instance).AndReturn(uses_bittorrent)

    def test_fetch_vhd_image_works_with_glance(self):
        self._apply_stubouts()
        self._common_params_setup(False)

        vm_utils._generate_glance_callback(self.context).AndReturn("dummy")

        vm_utils._fetch_using_dom0_plugin_with_retry(self.context,
            self.session, self.image_id, "glance", self.params,
            callback="dummy").AndReturn(self.vdis)

        vm_utils.safe_find_sr(self.session).AndReturn("sr")
        vm_utils._scan_sr(self.session, "sr")
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                                 "vdi")

        self.mox.ReplayAll()

        self.assertEqual("vdi", vm_utils._fetch_vhd_image(self.context,
            self.session, self.instance, self.image_id)['root']['uuid'])

        self.mox.VerifyAll()

    def test_fetch_vhd_image_works_with_bittorrent(self):
        self._apply_stubouts()
        self._common_params_setup(True)

        vm_utils._add_bittorrent_params(self.params)

        vm_utils._fetch_using_dom0_plugin_with_retry(self.context,
            self.session, self.image_id, "bittorrent", self.params,
            callback=None).AndReturn(self.vdis)

        vm_utils.safe_find_sr(self.session).AndReturn("sr")
        vm_utils._scan_sr(self.session, "sr")
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                                 "vdi")

        self.mox.ReplayAll()

        self.assertEqual("vdi", vm_utils._fetch_vhd_image(self.context,
            self.session, self.instance, self.image_id)['root']['uuid'])

        self.mox.VerifyAll()

    def test_fetch_vhd_image_cleans_up_vdi_on_fail(self):
        self._apply_stubouts()
        self._common_params_setup(True)
        self.mox.StubOutWithMock(self.session, 'call_xenapi')

        vm_utils._add_bittorrent_params(self.params)

        vm_utils._fetch_using_dom0_plugin_with_retry(self.context,
            self.session, self.image_id, "bittorrent", self.params,
            callback=None).AndReturn(self.vdis)

        vm_utils.safe_find_sr(self.session).AndReturn("sr")
        vm_utils._scan_sr(self.session, "sr")
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                "vdi").AndRaise(exception.InstanceTypeDiskTooSmall)

        self.session.call_xenapi("VDI.get_by_uuid", "vdi").AndReturn("ref")
        vm_utils.destroy_vdi(self.session, "ref")

        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
                vm_utils._fetch_vhd_image, self.context, self.session,
                self.instance, self.image_id)

        self.mox.VerifyAll()


class ResizeHelpersTestCase(test.TestCase):
    def test_get_min_sectors(self):
        self.mox.StubOutWithMock(utils, 'execute')

        utils.execute('resize2fs', '-P', "fakepath",
            run_as_root=True).AndReturn(("size is: 42", ""))

        self.mox.ReplayAll()

        result = vm_utils._get_min_sectors("fakepath")
        self.assertEquals(42 * 4096 / 512, result)

    def test_repair_filesystem(self):
        self.mox.StubOutWithMock(utils, 'execute')

        utils.execute('e2fsck', '-f', "-y", "fakepath",
            run_as_root=True, check_exit_code=[0, 1, 2]).AndReturn(
                ("size is: 42", ""))

        self.mox.ReplayAll()

        vm_utils._repair_filesystem("fakepath")

    def _call_tune2fs_remove_journal(self, path):
        utils.execute("tune2fs", "-O ^has_journal", path, run_as_root=True)

    def _call_tune2fs_add_journal(self, path):
        utils.execute("tune2fs", "-j", path, run_as_root=True)

    def _call_parted(self, path, start, end):
        utils.execute('parted', '--script', path, 'rm', '1',
            run_as_root=True)
        utils.execute('parted', '--script', path, 'mkpart',
            'primary', '%ds' % start, '%ds' % end, run_as_root=True)

    def test_resize_part_and_fs_down_succeeds(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(vm_utils, "_get_min_sectors")

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        vm_utils._get_min_sectors(partition_path).AndReturn(9)
        utils.execute("resize2fs", partition_path, "10s", run_as_root=True)
        self._call_parted(dev_path, 0, 9)
        self._call_tune2fs_add_journal(partition_path)

        self.mox.ReplayAll()

        vm_utils._resize_part_and_fs("fake", 0, 20, 10)

    def test_resize_part_and_fs_down_fails_disk_too_big(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(vm_utils, "_get_min_sectors")

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        vm_utils._get_min_sectors(partition_path).AndReturn(10)

        self.mox.ReplayAll()

        self.assertRaises(exception.ResizeError,
            vm_utils._resize_part_and_fs, "fake", 0, 20, 10)

    def test_resize_part_and_fs_up_succeeds(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        self._call_parted(dev_path, 0, 29)
        utils.execute("resize2fs", partition_path, run_as_root=True)
        self._call_tune2fs_add_journal(partition_path)

        self.mox.ReplayAll()

        vm_utils._resize_part_and_fs("fake", 0, 20, 30)


class CheckVDISizeTestCase(test.TestCase):
    def setUp(self):
        super(CheckVDISizeTestCase, self).setUp()
        self.context = 'fakecontext'
        self.session = 'fakesession'
        self.instance = dict(uuid='fakeinstance')
        self.vdi_uuid = 'fakeuuid'

    def test_not_too_large(self):
        self.mox.StubOutWithMock(flavors, 'extract_instance_type')
        flavors.extract_instance_type(self.instance).AndReturn(
                dict(root_gb=1))

        self.mox.StubOutWithMock(vm_utils, '_get_vdi_chain_size')
        vm_utils._get_vdi_chain_size(self.session,
                self.vdi_uuid).AndReturn(1073741824)

        self.mox.ReplayAll()

        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                self.vdi_uuid)

    def test_too_large(self):
        self.mox.StubOutWithMock(flavors, 'extract_instance_type')
        flavors.extract_instance_type(self.instance).AndReturn(
                dict(root_gb=1))

        self.mox.StubOutWithMock(vm_utils, '_get_vdi_chain_size')
        vm_utils._get_vdi_chain_size(self.session,
                self.vdi_uuid).AndReturn(1073741825)

        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
                vm_utils._check_vdi_size, self.context, self.session,
                self.instance, self.vdi_uuid)

    def test_zero_root_gb_disables_check(self):
        self.mox.StubOutWithMock(flavors, 'extract_instance_type')
        flavors.extract_instance_type(self.instance).AndReturn(
                dict(root_gb=0))

        self.mox.ReplayAll()

        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                self.vdi_uuid)
