# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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


import stubout
import uuid

from twisted.internet import defer
from twisted.internet import threads

from nova import db
from nova import context
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volumeops
from boto.ec2.volume import Volume

FLAGS = flags.FLAGS


def stubout_session(stubs, cls):
    def fake_import(self):
        fake_module = 'nova.virt.xenapi.fake'
        from_list = ['fake']
        return __import__(fake_module, globals(), locals(), from_list, -1)

    stubs.Set(xenapi_conn.XenAPISession, '_create_session',
                       lambda s, url: cls(url))
    stubs.Set(xenapi_conn.XenAPISession, 'get_imported_xenapi',
                       fake_import)


class XenAPIVolumeTestCase(test.TrialTestCase):
    """
    Unit tests for VM operations
    """
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        FLAGS.target_host = '127.0.0.1'
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        fake.reset()

    def _create_volume(self, size='0'):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['host'] = 'localhost'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(context.get_admin_context(), vol)

    def test_create_iscsi_storage(self):
        """ This shows how to test helper classes' methods """
        stubout_session(self.stubs, FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.XenAPI = session.get_imported_xenapi()
        vol = self._create_volume()
        info = yield helper.parse_volume_info(vol['ec2_id'], '/dev/sdc')
        label = 'SR-%s' % vol['ec2_id']
        description = 'Test-SR'
        sr_ref = helper.create_iscsi_storage_blocking(session,
                                                      info,
                                                      label,
                                                      description)
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_parse_volume_info_raise_exception(self):
        """ This shows how to test helper classes' methods """
        stubout_session(self.stubs, FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.XenAPI = session.get_imported_xenapi()
        vol = self._create_volume()
        # oops, wrong mount point!
        info = helper.parse_volume_info(vol['ec2_id'], '/dev/sd')

        def check(exc):
            self.assertIsInstance(exc.value, volume_utils.StorageError)

        info.addErrback(check)
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        """ This shows how to test Ops classes' methods """
        stubout_session(self.stubs, FakeSessionForVolumeTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = FakeInstance(1, 'fake', 'fake', 1, 2, 3,
                                'm1.large', 'aa:bb:cc:dd:ee:ff')
        fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(instance.name, volume['ec2_id'],
                                    '/dev/sdc')

        def check(_):
            # check that the VM has a VBD attached to it
            # Get XenAPI reference for the VM
            vms = fake.get_all('VM')
            # Get XenAPI record for VBD
            vbds = fake.get_all('VBD')
            vbd = fake.get_record('VBD', vbds[0])
            vm_ref = vbd['VM']
            self.assertEqual(vm_ref, vms[0])

        result.addCallback(check)
        return result

    def test_attach_volume_raise_exception(self):
        """ This shows how to test when exceptions are raised """
        stubout_session(self.stubs, FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = FakeInstance(1, 'fake', 'fake', 1, 2, 3,
                                'm1.large', 'aa:bb:cc:dd:ee:ff')
        fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(instance.name, volume['ec2_id'],
                                    '/dev/sdc')

        def check(exc):
            if exc:
                pass
            else:
                self.fail('Oops, no exception has been raised!')

        result.addErrback(check)
        return result

    def tearDown(self):
        super(XenAPIVolumeTestCase, self).tearDown()
        self.stubs.UnsetAll()


class XenAPIVMTestCase(test.TrialTestCase):
    """
    Unit tests for VM operations
    """
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)
        self.stubs = stubout.StubOutForTesting()
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        fake.reset()
        fake.create_network('fake', FLAGS.flat_network_bridge)

    def test_list_instances_0(self):
        stubout_session(self.stubs, FakeSessionForVMTests)
        conn = xenapi_conn.get_connection(False)
        instances = conn.list_instances()
        self.assertEquals(instances, [])

    def test_spawn(self):
        stubout_session(self.stubs, FakeSessionForVMTests)
        conn = xenapi_conn.get_connection(False)
        instance = FakeInstance(1, self.project.id, self.user.id, 1, 2, 3,
                                'm1.large', 'aa:bb:cc:dd:ee:ff')
        result = conn.spawn(instance)

        def check(_):
            instances = conn.list_instances()
            self.assertEquals(instances, [1])

            # Get Nova record for VM
            vm_info = conn.get_info(1)

            # Get XenAPI record for VM
            vms = fake.get_all('VM')
            vm = fake.get_record('VM', vms[0])

            # Check that m1.large above turned into the right thing.
            instance_type = instance_types.INSTANCE_TYPES['m1.large']
            mem_kib = long(instance_type['memory_mb']) << 10
            mem_bytes = str(mem_kib << 10)
            vcpus = instance_type['vcpus']
            self.assertEquals(vm_info['max_mem'], mem_kib)
            self.assertEquals(vm_info['mem'], mem_kib)
            self.assertEquals(vm['memory_static_max'], mem_bytes)
            self.assertEquals(vm['memory_dynamic_max'], mem_bytes)
            self.assertEquals(vm['memory_dynamic_min'], mem_bytes)
            self.assertEquals(vm['VCPUs_max'], str(vcpus))
            self.assertEquals(vm['VCPUs_at_startup'], str(vcpus))

            # Check that the VM is running according to Nova
            self.assertEquals(vm_info['state'], power_state.RUNNING)

            # Check that the VM is running according to XenAPI.
            self.assertEquals(vm['power_state'], 'Running')

        result.addCallback(check)
        return result

    def tearDown(self):
        super(XenAPIVMTestCase, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        self.stubs.UnsetAll()


class FakeInstance():
    def __init__(self, name, project_id, user_id, image_id, kernel_id,
                 ramdisk_id, instance_type, mac_address):
        self.name = name
        self.project_id = project_id
        self.user_id = user_id
        self.image_id = image_id
        self.kernel_id = kernel_id
        self.ramdisk_id = ramdisk_id
        self.instance_type = instance_type
        self.mac_address = mac_address


class FakeSessionForVMTests(fake.SessionBase):
    def __init__(self, uri):
        super(FakeSessionForVMTests, self).__init__(uri)

    def network_get_all_records_where(self, _1, _2):
        return self.xenapi.network.get_all_records()

    def host_call_plugin(self, _1, _2, _3, _4, _5):
        return ''

    def VM_start(self, _1, ref, _2, _3):
        vm = fake.get_record('VM', ref)
        if vm['power_state'] != 'Halted':
            raise fake.Failure(['VM_BAD_POWER_STATE', ref, 'Halted',
                                  vm['power_state']])
        vm['power_state'] = 'Running'


class FakeSessionForVolumeTests(fake.SessionBase):
    def __init__(self, uri):
        super(FakeSessionForVolumeTests, self).__init__(uri)

    def VBD_plug(self, _1, _2):
        #FIXME(armando):make proper plug
        pass

    def PBD_unplug(self, _1, _2):
        #FIXME(armando):make proper unplug
        pass

    def SR_forget(self, _1, _2):
        #FIXME(armando):make proper forget
        pass

    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        #FIXME(armando):make proper introduce
        valid_vdi = False
        refs = fake.get_all('VDI')
        for ref in refs:
            rec = fake.get_record('VDI', ref)
            if rec['uuid'] == uuid:
                valid_vdi = True
        if not valid_vdi:
            raise fake.Failure([['INVALID_VDI', 'session', self._session]])


class FakeSessionForVolumeFailedTests(FakeSessionForVolumeTests):
    def __init__(self, uri):
        super(FakeSessionForVolumeFailedTests, self).__init__(uri)

    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        # test failure
        raise fake.Failure([['INVALID_VDI', 'session', self._session]])

    def VBD_plug(self, _1, _2):
        # test failure
        raise fake.Failure([['INVALID_VBD', 'session', self._session]])
