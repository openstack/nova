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


import uuid

from twisted.internet import defer
from twisted.internet import threads

from nova import db
from nova import context
from nova import flags
from nova import test
from nova import utils
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils

FLAGS = flags.FLAGS


class XenAPIVolumeTestCase(test.TrialTestCase):

    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        FLAGS.xenapi_use_fake_session = True
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

    def test_create_iscsi_storage_raise_no_exception(self):
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.late_import(FLAGS)
        vol = self._create_volume()
        info = yield helper.parse_volume_info(vol['ec2_id'], '/dev/sdc')
        label = 'SR-%s' % vol['ec2_id']
        description = 'Test-SR'
        sr_ref = helper.create_iscsi_storage_blocking(session,
                                                      info,
                                                      label,
                                                      description)
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = FakeInstance(1, 'fake', 'fake', 1, 2, 3,
                                'm1.large', 'aa:bb:cc:dd:ee:ff')
        fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(instance.name, volume['ec2_id'],
                                    '/dev/sdc')

        def check(_):
            # check that
            # 1. the SR has been created
            # 2. the instance has a VBD attached to it
            pass

        result.addCallback(check)
        return result

    def tearDown(self):
        super(XenAPIVolumeTestCase, self).tearDown()


class XenAPIVMTestCase(test.TrialTestCase):

    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)
        FLAGS.xenapi_use_fake_session = True
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        fake.reset()
        fake.create_network('fake', FLAGS.flat_network_bridge)

    def test_list_instances_0(self):
        conn = xenapi_conn.get_connection(False)
        instances = conn.list_instances()
        self.assertEquals(instances, [])
    test_list_instances_0.skip = "E"

    def test_spawn(self):
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
