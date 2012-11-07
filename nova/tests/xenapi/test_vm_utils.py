import mox
from nova import context
from nova import db
from nova import exception
from nova.tests.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils
import unittest


class GetInstanceForVdisForSrTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(GetInstanceForVdisForSrTestCase, self).setUp()
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',)

    def test_get_instance_vdis_for_sr(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        vdi_1 = fake.create_vdi('vdiname1', sr_ref)
        vdi_2 = fake.create_vdi('vdiname2', sr_ref)

        for vdi_ref in [vdi_1, vdi_2]:
            fake.create_vbd(vm_ref, vdi_ref)

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEquals([vdi_1, vdi_2], result)

    def test_get_instance_vdis_for_sr_no_vbd(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEquals([], result)

    def test_get_vdis_for_boot_from_vol(self):
        dev_params = {'sr_uuid': 'falseSR',
                      'name_label': 'fake_storage',
                      'name_description': 'test purposes',
                      'server': 'myserver',
                      'serverpath': '/local/scratch/myname',
                      'sr_type': 'nfs',
                      'introduce_sr_keys': ['server', 'serverpath', 'sr_type'],
                      'vdi_uuid': 'falseVDI'}
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = vm_utils.get_vdis_for_boot_from_vol(driver._session,
                                                     dev_params)
        self.assertEquals(result['root']['uuid'], 'falseVDI')

    def test_get_vdis_for_boot_from_vol_failure(self):
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        def bad_introduce_sr(session, sr_uuid, label, sr_params):
            return None

        self.stubs.Set(volume_utils, 'introduce_sr', bad_introduce_sr)
        dev_params = {'sr_uuid': 'falseSR',
                      'name_label': 'fake_storage',
                      'name_description': 'test purposes',
                      'server': 'myserver',
                      'serverpath': '/local/scratch/myname',
                      'sr_type': 'nfs',
                      'introduce_sr_keys': ['server', 'serverpath', 'sr_type'],
                      'vdi_uuid': 'falseVDI'}
        self.assertRaises(exception.NovaException,
                          vm_utils.get_vdis_for_boot_from_vol,
                          driver._session, dev_params)


class VMRefOrRaiseVMFoundTestCase(unittest.TestCase):

    def test_lookup_call(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn('ignored')

        mock.ReplayAll()
        vm_utils.vm_ref_or_raise('session', 'somename')
        mock.VerifyAll()

    def test_return_value(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn('vmref')

        mock.ReplayAll()
        self.assertEquals(
            'vmref', vm_utils.vm_ref_or_raise('session', 'somename'))
        mock.VerifyAll()


class VMRefOrRaiseVMNotFoundTestCase(unittest.TestCase):

    def test_exception_raised(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        self.assertRaises(
            exception.InstanceNotFound,
            lambda: vm_utils.vm_ref_or_raise('session', 'somename')
        )
        mock.VerifyAll()

    def test_exception_msg_contains_vm_name(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        try:
            vm_utils.vm_ref_or_raise('session', 'somename')
        except exception.InstanceNotFound as e:
            self.assertTrue(
                'somename' in str(e))
        mock.VerifyAll()


class BittorrentTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(BittorrentTestCase, self).setUp()
        self.context = context.get_admin_context()

    def test_image_uses_bittorrent(self):
        sys_meta = {'image_bittorrent': True}
        instance = db.instance_create(self.context,
                                      {'system_metadata': sys_meta})
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.flags(xenapi_torrent_images='some')
        self.assertTrue(vm_utils._image_uses_bittorrent(self.context,
                                                        instance))

    def _test_create_image(self, cache_type):
        sys_meta = {'image_cache_in_nova': True}
        instance = db.instance_create(self.context,
                                      {'system_metadata': sys_meta})
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.flags(cache_images=cache_type)

        was = {'called': None}

        def fake_create_cached_image(*args):
            was['called'] = 'some'
            return {}
        self.stubs.Set(vm_utils, '_create_cached_image',
                       fake_create_cached_image)

        def fake_fetch_image(*args):
            was['called'] = 'none'
            return {}
        self.stubs.Set(vm_utils, '_fetch_image',
                       fake_fetch_image)

        vm_utils._create_image(self.context, None, instance,
                               'foo', 'bar', 'baz')

        self.assertEqual(was['called'], cache_type)

    def test_create_image_cached(self):
        self._test_create_image('some')

    def test_create_image_uncached(self):
        self._test_create_image('none')
