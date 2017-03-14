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

import fixtures
import mock

from nova import context
from nova.image import glance
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
import nova.tests.unit.image.fake
from nova.tests.unit import utils
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.tests import uuidsentinel
from nova.virt import fake
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops


class ConfigDriveTestCase(test.NoDBTestCase):

    REQUIRES_LOCKING = True

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(driver.VMwareVCDriver, '_register_openstack_extension')
    def setUp(self, mock_register, mock_service):
        super(ConfigDriveTestCase, self).setUp()
        vm_util.vm_refs_cache_reset()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        self.flags(cluster_name='test_cluster',
                   host_ip='testhostname',
                   host_username='test_username',
                   host_password='test_pass',
                   use_linked_clone=False, group='vmware')
        self.flags(enabled=False, group='vnc')
        vmwareapi_fake.reset()
        stubs.set_stubs(self)
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.conn = driver.VMwareVCDriver(fake.FakeVirtAPI)
        self.network_info = utils.get_test_network_info()
        self.node_name = self.conn._nodename
        image_ref = nova.tests.unit.image.fake.get_valid_image_id()
        instance_values = {
            'vm_state': 'building',
            'project_id': 'fake',
            'user_id': 'fake',
            'name': '1',
            'kernel_id': '1',
            'ramdisk_id': '1',
            'mac_addresses': [{'address': 'de:ad:be:ef:be:ef'}],
            'memory_mb': 8192,
            'flavor': objects.Flavor(vcpus=4, extra_specs={}),
            'instance_type_id': 0,
            'vcpus': 4,
            'root_gb': 80,
            'image_ref': image_ref,
            'host': 'fake_host',
            'task_state': 'scheduling',
            'reservation_id': 'r-3t8muvr0',
            'id': 1,
            'uuid': uuidsentinel.foo,
            'node': self.node_name,
            'metadata': [],
            'expected_attrs': ['system_metadata'],
        }
        self.test_instance = fake_instance.fake_instance_obj(self.context,
                                                             **instance_values)
        self.test_instance.flavor = objects.Flavor(vcpus=4, memory_mb=8192,
                                                   root_gb=80,
                                                   ephemeral_gb=0, swap=0,
                                                   extra_specs={})

        (image_service, image_id) = glance.get_remote_image_service(context,
                                    image_ref)
        metadata = image_service.show(context, image_id)
        self.image = objects.ImageMeta.from_dict({
            'id': image_ref,
            'disk_format': 'vmdk',
            'size': int(metadata['size']),
        })

        class FakeInstanceMetadata(object):
            def __init__(self, instance, content=None, extra_md=None,
                         network_info=None, request_context=None):
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
        self.stub_out('nova.virt.configdrive.ConfigDriveBuilder.make_drive',
                      fake_make_drive)

        def fake_upload_iso_to_datastore(iso_path, instance, **kwargs):
            pass
        self.stub_out('nova.virt.vmwareapi.images.upload_iso_to_datastore',
                       fake_upload_iso_to_datastore)

    def tearDown(self):
        super(ConfigDriveTestCase, self).tearDown()
        vmwareapi_fake.cleanup()
        nova.tests.unit.image.fake.FakeImageService_reset()

    @mock.patch.object(vmops.VMwareVMOps, '_get_instance_metadata',
                       return_value='fake_metadata')
    def _spawn_vm(self, fake_get_instance_meta,
                  injected_files=None, admin_password=None,
                  block_device_info=None):

        injected_files = injected_files or []
        self.conn.spawn(self.context, self.test_instance, self.image,
                        injected_files=injected_files,
                        admin_password=admin_password,
                        network_info=self.network_info,
                        block_device_info=block_device_info)

    @mock.patch.object(vmops.VMwareVMOps, '_create_config_drive',
                                 return_value=('[ds1] fake.iso'))
    @mock.patch.object(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
    def test_create_vm_with_config_drive_verify_method_invocation(self,
                            mock_attach_cdrom, mock_create_config_drive):
        self.test_instance.config_drive = 'True'
        self._spawn_vm()
        mock_create_config_drive.assert_called_once_with(mock.ANY,
                                                         self.test_instance,
                                                         mock.ANY,
                                                         mock.ANY,
                                                         mock.ANY,
                                                         mock.ANY,
                                                         mock.ANY,
                                                         mock.ANY,
                                                         mock.ANY)
        mock_attach_cdrom.assert_called_once_with(mock.ANY, mock.ANY,
                                                  mock.ANY, mock.ANY)

    @mock.patch.object(vmops.VMwareVMOps, '_create_config_drive',
                       return_value=('[ds1] fake.iso'))
    @mock.patch.object(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
    def test_create_vm_without_config_drive(self, mock_attach_cdrom,
                                            mock_create_config_drive):
        self.test_instance.config_drive = None
        self._spawn_vm()
        mock_create_config_drive.assert_not_called()
        mock_attach_cdrom.assert_not_called()

    def test_create_vm_with_config_drive(self):
        self.test_instance.config_drive = 'True'
        self._spawn_vm()
