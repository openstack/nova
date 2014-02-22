# Copyright 2013 IBM Corp.
# Copyright 2011 OpenStack Foundation
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
import mox

from nova import context
from nova import test
import nova.tests.image.fake
from nova.tests import utils
from nova.tests.virt.vmwareapi import stubs
from nova.virt import fake
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import vmware_images


class ConfigDriveTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ConfigDriveTestCase, self).setUp()
        vm_util.vm_refs_cache_reset()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        cluster_name = 'test_cluster'
        self.flags(cluster_name=[cluster_name],
                   host_ip='test_url',
                   host_username='test_username',
                   host_password='test_pass',
                   use_linked_clone=False, group='vmware')
        self.flags(vnc_enabled=False)
        vmwareapi_fake.reset(vc=True)
        stubs.set_stubs(self.stubs)
        nova.tests.image.fake.stub_out_image_service(self.stubs)
        self.conn = driver.VMwareVCDriver(fake.FakeVirtAPI)
        self.network_info = utils.get_test_network_info()
        self.image = {
            'id': 'c1c8ce3d-c2e0-4247-890c-ccf5cc1c004c',
            'disk_format': 'vhd',
            'size': 512,
        }
        self.node_name = '%s(%s)' % (self.conn.dict_mors.keys()[0],
                                     cluster_name)
        self.test_instance = {'node': 'test_url',
                              'vm_state': 'building',
                              'project_id': 'fake',
                              'user_id': 'fake',
                              'name': '1',
                              'kernel_id': '1',
                              'ramdisk_id': '1',
                              'mac_addresses': [
                                  {'address': 'de:ad:be:ef:be:ef'}
                              ],
                              'memory_mb': 8192,
                              'flavor': 'm1.large',
                              'vcpus': 4,
                              'root_gb': 80,
                              'image_ref': '1',
                              'host': 'fake_host',
                              'task_state':
                                  'scheduling',
                              'reservation_id': 'r-3t8muvr0',
                              'id': 1,
                              'uuid': 'fake-uuid',
                              'node': self.node_name,
                              'metadata': []}

        class FakeInstanceMetadata(object):
            def __init__(self, instance, content=None, extra_md=None):
                pass

            def metadata_for_config_drive(self):
                return []

        self.useFixture(fixtures.MonkeyPatch(
                'nova.api.metadata.base.InstanceMetadata',
                FakeInstanceMetadata))

        def fake_make_drive(_self, _path):
            pass
        # We can't actually make a config drive v2 because ensure_tree has
        # been faked out
        self.stubs.Set(nova.virt.configdrive.ConfigDriveBuilder,
                       'make_drive', fake_make_drive)

        def fake_upload_iso_to_datastore(iso_path, instance, **kwargs):
            pass
        self.stubs.Set(vmware_images,
                       'upload_iso_to_datastore',
                       fake_upload_iso_to_datastore)

    def tearDown(self):
        super(ConfigDriveTestCase, self).tearDown()
        vmwareapi_fake.cleanup()
        nova.tests.image.fake.FakeImageService_reset()

    def test_create_vm_with_config_drive_verify_method_invocation(self):
        self.instance = copy.deepcopy(self.test_instance)
        self.instance['config_drive'] = True
        self.mox.StubOutWithMock(vmops.VMwareVMOps, '_create_config_drive')
        self.mox.StubOutWithMock(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
        self.conn._vmops._create_config_drive(self.instance,
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg())
        self.conn._vmops._attach_cdrom_to_vm(mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg())
        self.mox.ReplayAll()
        # if spawn does not call the _create_config_drive or
        # _attach_cdrom_to_vm call with the correct set of parameters
        # then mox's VerifyAll will throw a Expected methods never called
        # Exception
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)

    def test_create_vm_without_config_drive(self):
        self.instance = copy.deepcopy(self.test_instance)
        self.instance['config_drive'] = False
        self.mox.StubOutWithMock(vmops.VMwareVMOps, '_create_config_drive')
        self.mox.StubOutWithMock(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
        self.mox.ReplayAll()
        # if spawn ends up calling _create_config_drive or
        # _attach_cdrom_to_vm then mox will log a Unexpected method call
        # exception
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)

    def test_create_vm_with_config_drive(self):
        self.instance = copy.deepcopy(self.test_instance)
        self.instance['config_drive'] = True
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)
