from nova import exception
from nova.tests.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils


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
