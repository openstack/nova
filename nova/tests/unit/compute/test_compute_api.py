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

"""Unit tests for compute API."""

import contextlib
import datetime

import ddt
import iso8601
import mock
from mox3 import mox
from oslo_messaging import exceptions as oslo_exceptions
from oslo_serialization import jsonutils
from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils
from oslo_utils import uuidutils

from nova.compute import api as compute_api
from nova.compute import cells_api as compute_cells_api
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova import context
from nova import db
from nova import exception
from nova.network.neutronv2 import api as neutron_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import fields as fields_obj
from nova.objects import quotas as quotas_obj
from nova.objects import security_group as secgroup_obj
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_build_request
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_volume
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_flavor
from nova.tests.unit.objects import test_migration
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.volume import cinder


FAKE_IMAGE_REF = 'fake-image-ref'
NODENAME = 'fakenode1'
SHELVED_IMAGE = 'fake-shelved-image'
SHELVED_IMAGE_NOT_FOUND = 'fake-shelved-image-notfound'
SHELVED_IMAGE_NOT_AUTHORIZED = 'fake-shelved-image-not-authorized'
SHELVED_IMAGE_EXCEPTION = 'fake-shelved-image-exception'
COMPUTE_VERSION_NEW_ATTACH_FLOW = \
    compute_api.CINDER_V3_ATTACH_MIN_COMPUTE_VERSION
COMPUTE_VERSION_OLD_ATTACH_FLOW = \
    compute_api.CINDER_V3_ATTACH_MIN_COMPUTE_VERSION - 1


@ddt.ddt
class _ComputeAPIUnitTestMixIn(object):
    def setUp(self):
        super(_ComputeAPIUnitTestMixIn, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.compute_api = compute_api.API()
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def _get_vm_states(self, exclude_states=None):
        vm_state = set([vm_states.ACTIVE, vm_states.BUILDING, vm_states.PAUSED,
                    vm_states.SUSPENDED, vm_states.RESCUED, vm_states.STOPPED,
                    vm_states.RESIZED, vm_states.SOFT_DELETED,
                    vm_states.DELETED, vm_states.ERROR, vm_states.SHELVED,
                    vm_states.SHELVED_OFFLOADED])
        if not exclude_states:
            exclude_states = set()
        return vm_state - exclude_states

    def _create_flavor(self, **updates):
        flavor = {'id': 1,
                  'flavorid': 1,
                  'name': 'm1.tiny',
                  'memory_mb': 512,
                  'vcpus': 1,
                  'vcpu_weight': None,
                  'root_gb': 1,
                  'ephemeral_gb': 0,
                  'rxtx_factor': 1,
                  'swap': 0,
                  'deleted': 0,
                  'disabled': False,
                  'is_public': True,
                  'deleted_at': None,
                  'created_at': datetime.datetime(2012, 1, 19, 18,
                                                  49, 30, 877329),
                  'updated_at': None,
                  'description': None
                 }
        if updates:
            flavor.update(updates)
        return objects.Flavor._from_db_object(self.context, objects.Flavor(),
                                              flavor)

    def _create_instance_obj(self, params=None, flavor=None):
        """Create a test instance."""
        if not params:
            params = {}

        if flavor is None:
            flavor = self._create_flavor()

        now = timeutils.utcnow()

        instance = objects.Instance()
        instance.metadata = {}
        instance.metadata.update(params.pop('metadata', {}))
        instance.system_metadata = params.pop('system_metadata', {})
        instance._context = self.context
        instance.id = 1
        instance.uuid = uuidutils.generate_uuid()
        instance.cell_name = 'api!child'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.image_ref = FAKE_IMAGE_REF
        instance.reservation_id = 'r-fakeres'
        instance.user_id = self.user_id
        instance.project_id = self.project_id
        instance.host = 'fake_host'
        instance.node = NODENAME
        instance.instance_type_id = flavor.id
        instance.ami_launch_index = 0
        instance.memory_mb = 0
        instance.vcpus = 0
        instance.root_gb = 0
        instance.ephemeral_gb = 0
        instance.architecture = fields_obj.Architecture.X86_64
        instance.os_type = 'Linux'
        instance.locked = False
        instance.created_at = now
        instance.updated_at = now
        instance.launched_at = now
        instance.disable_terminate = False
        instance.info_cache = objects.InstanceInfoCache()
        instance.flavor = flavor
        instance.old_flavor = instance.new_flavor = None

        if params:
            instance.update(params)
        instance.obj_reset_changes()
        return instance

    def _create_keypair_obj(self, instance):
        """Create a test keypair."""
        keypair = objects.KeyPair()
        keypair.id = 1
        keypair.name = 'fake_key'
        keypair.user_id = instance.user_id
        keypair.fingerprint = 'fake'
        keypair.public_key = 'fake key'
        keypair.type = 'ssh'
        return keypair

    def _obj_to_list_obj(self, list_obj, obj):
        list_obj.objects = []
        list_obj.objects.append(obj)
        list_obj._context = self.context
        list_obj.obj_reset_changes()
        return list_obj

    @mock.patch('nova.objects.Quotas.check_deltas')
    @mock.patch('nova.conductor.conductor_api.ComputeTaskAPI.build_instances')
    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch('nova.compute.api.API._check_requested_networks')
    @mock.patch('nova.objects.Quotas.limit_check')
    @mock.patch('nova.compute.api.API._get_image')
    @mock.patch('nova.compute.api.API._provision_instances')
    def test_create_with_networks_max_count_none(self, provision_instances,
                                                 get_image, check_limit,
                                                 check_requested_networks,
                                                 record_action_start,
                                                 build_instances,
                                                 check_deltas):
        # Make sure max_count is checked for None, as Python3 doesn't allow
        # comparison between NoneType and Integer, something that's allowed in
        # Python 2.
        provision_instances.return_value = []
        get_image.return_value = (None, {})
        check_requested_networks.return_value = 1

        instance_type = self._create_flavor()

        port = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '10.0.0.1'
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(address=address,
                                            port_id=port)])

        with mock.patch.object(self.compute_api.network_api,
                               'create_pci_requests_for_sriov_ports'):
            self.compute_api.create(self.context, instance_type, 'image_id',
                                    requested_networks=requested_networks,
                                    max_count=None)

    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    def test_create_quota_exceeded_messages(self, mock_limit_check_pu,
                                            mock_limit_check, mock_count):
        image_href = "image_href"
        image_id = 0
        instance_type = self._create_flavor()

        quotas = {'instances': 1, 'cores': 1, 'ram': 1}
        quota_exception = exception.OverQuota(quotas=quotas,
            usages={'instances': 1, 'cores': 1, 'ram': 1},
            overs=['instances'])

        proj_count = {'instances': 1, 'cores': 1, 'ram': 1}
        user_count = proj_count.copy()
        mock_count.return_value = {'project': proj_count, 'user': user_count}
        # instances/cores/ram quota
        mock_limit_check_pu.side_effect = quota_exception

        # We don't care about network validation in this test.
        self.compute_api.network_api.validate_networks = (
            mock.Mock(return_value=40))
        with mock.patch.object(self.compute_api, '_get_image',
                               return_value=(image_id, {})) as mock_get_image:
            for min_count, message in [(20, '20-40'), (40, '40')]:
                try:
                    self.compute_api.create(self.context, instance_type,
                                            "image_href", min_count=min_count,
                                            max_count=40)
                except exception.TooManyInstances as e:
                    self.assertEqual(message, e.kwargs['req'])
                else:
                    self.fail("Exception not raised")
            mock_get_image.assert_called_with(self.context, image_href)
            self.assertEqual(2, mock_get_image.call_count)
            self.assertEqual(2, mock_limit_check_pu.call_count)

    def _test_create_max_net_count(self, max_net_count, min_count, max_count):
        with test.nested(
            mock.patch.object(self.compute_api, '_get_image',
                              return_value=(None, {})),
            mock.patch.object(self.compute_api, '_check_auto_disk_config'),
            mock.patch.object(self.compute_api,
                              '_validate_and_build_base_options',
                              return_value=({}, max_net_count, None,
                                            ['default']))
        ) as (
            get_image,
            check_auto_disk_config,
            validate_and_build_base_options
        ):
            self.assertRaises(exception.PortLimitExceeded,
                self.compute_api.create, self.context, 'fake_flavor',
                'image_id', min_count=min_count, max_count=max_count)

    def test_max_net_count_zero(self):
        # Test when max_net_count is zero.
        max_net_count = 0
        min_count = 2
        max_count = 3
        self._test_create_max_net_count(max_net_count, min_count, max_count)

    def test_max_net_count_less_than_min_count(self):
        # Test when max_net_count is nonzero but less than min_count.
        max_net_count = 1
        min_count = 2
        max_count = 3
        self._test_create_max_net_count(max_net_count, min_count, max_count)

    def test_specified_port_and_multiple_instances_neutronv2(self):
        # Tests that if port is specified there is only one instance booting
        # (i.e max_count == 1) as we can't share the same port across multiple
        # instances.
        self.flags(use_neutron=True)
        port = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '10.0.0.1'
        min_count = 1
        max_count = 2
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(address=address,
                                            port_id=port)])

        self.assertRaises(exception.MultiplePortsNotApplicable,
            self.compute_api.create, self.context, 'fake_flavor', 'image_id',
            min_count=min_count, max_count=max_count,
            requested_networks=requested_networks)

    def _test_specified_ip_and_multiple_instances_helper(self,
                                                         requested_networks):
        # Tests that if ip is specified there is only one instance booting
        # (i.e max_count == 1)
        min_count = 1
        max_count = 2
        self.assertRaises(exception.InvalidFixedIpAndMaxCountRequest,
            self.compute_api.create, self.context, "fake_flavor", 'image_id',
            min_count=min_count, max_count=max_count,
            requested_networks=requested_networks)

    def test_specified_ip_and_multiple_instances(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '10.0.0.1'
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=network,
                                            address=address)])
        self._test_specified_ip_and_multiple_instances_helper(
            requested_networks)

    def test_specified_ip_and_multiple_instances_neutronv2(self):
        self.flags(use_neutron=True)
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '10.0.0.1'
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=network,
                                            address=address)])
        self._test_specified_ip_and_multiple_instances_helper(
            requested_networks)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    def test_create_volume_bdm_call_reserve_dev_name(self, mock_reserve):
        bdm = objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'id': 1,
                 'volume_id': 1,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                 'boot_index': 1,
                 }))
        mock_reserve.return_value = bdm
        instance = self._create_instance_obj()
        volume = {'id': '1', 'multiattach': False}
        result = self.compute_api._create_volume_bdm(self.context,
                                                     instance,
                                                     'vda',
                                                     volume,
                                                     None,
                                                     None)
        self.assertTrue(mock_reserve.called)
        self.assertEqual(result, bdm)

    @mock.patch.object(objects.BlockDeviceMapping, 'create')
    def test_create_volume_bdm_local_creation(self, bdm_create):
        instance = self._create_instance_obj()
        volume_id = 'fake-vol-id'
        bdm = objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'instance_uuid': instance.uuid,
                 'volume_id': volume_id,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                 'boot_index': None,
                 'disk_bus': None,
                 'device_type': None
                 }))
        result = self.compute_api._create_volume_bdm(self.context,
                                                     instance,
                                                     '/dev/vda',
                                                     {'id': volume_id},
                                                     None,
                                                     None,
                                                     is_local_creation=True)
        self.assertEqual(result.instance_uuid, bdm.instance_uuid)
        self.assertIsNone(result.device_name)
        self.assertEqual(result.volume_id, bdm.volume_id)
        self.assertTrue(bdm_create.called)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume(self, mock_attach, mock_get_min_ver, mock_reserve,
                           mock_record):
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            self.compute_api.attach_volume(
                self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.reserve_volume.assert_called_once_with(self.context,
                                                              volume['id'])
            mock_attach.assert_called_once_with(self.context,
                                                instance, fake_bdm)
            mock_record.assert_called_once_with(
                self.context, instance, instance_actions.ATTACH_VOLUME)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_tagged_volume_attach(self, mock_attach, mock_get_min_ver,
                                  mock_reserve, mock_record):
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            self.compute_api.attach_volume(
                self.context, instance, volume['id'], tag='foo')
            mock_reserve.assert_called_once_with(self.context, instance, None,
                                                 volume['id'],
                                                 device_type=None,
                                                 disk_bus=None, tag='foo',
                                                 multiattach=False)
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.reserve_volume.assert_called_once_with(self.context,
                                                              volume['id'])
            mock_attach.assert_called_once_with(self.context,
                                                instance, fake_bdm)
            mock_record.assert_called_once_with(
                self.context, instance, instance_actions.ATTACH_VOLUME)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch('nova.volume.cinder.is_microversion_supported')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume_new_flow(self, mock_attach, mock_bdm,
                                    mock_cinder_mv_supported, mock_get_min_ver,
                                    mock_reserve, mock_record):
        mock_bdm.side_effect = exception.VolumeBDMNotFound(
                                          volume_id='fake-volume-id')
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            mock_v_api.attachment_create.return_value = \
                {'id': uuids.attachment_id}
            self.compute_api.attach_volume(
                self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.attachment_create.assert_called_once_with(self.context,
                                                                 volume['id'],
                                                                 instance.uuid)
            mock_attach.assert_called_once_with(self.context,
                                                instance, fake_bdm)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch('nova.volume.cinder.is_microversion_supported')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_tagged_volume_attach_new_flow(self, mock_attach, mock_bdm,
                                           mock_cinder_mv_supported,
                                           mock_get_min_ver,
                                           mock_reserve, mock_record):
        mock_bdm.side_effect = exception.VolumeBDMNotFound(
                                          volume_id='fake-volume-id')
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            mock_v_api.attachment_create.return_value = \
                {'id': uuids.attachment_id}
            self.compute_api.attach_volume(
                self.context, instance, volume['id'], tag='foo')
            mock_reserve.assert_called_once_with(self.context, instance, None,
                                                 volume['id'],
                                                 device_type=None,
                                                 disk_bus=None, tag='foo',
                                                 multiattach=False)
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.attachment_create.assert_called_once_with(
                self.context, volume['id'], instance.uuid)
            mock_attach.assert_called_once_with(self.context,
                                                instance, fake_bdm)

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    @mock.patch('nova.volume.cinder.API.get')
    def test_attach_volume_shelved_instance(self, mock_get, mock_get_min_ver):
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)
        mock_get.return_value = volume
        self.assertRaises(exception.VolumeTaggedAttachToShelvedNotSupported,
                          self.compute_api.attach_volume, self.context,
                          instance, volume['id'], tag='foo')

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume_reserve_fails(self, mock_attach,
                                         mock_get_min_ver, mock_reserve):
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            mock_v_api.reserve_volume.side_effect = test.TestingException()
            self.assertRaises(test.TestingException,
                              self.compute_api.attach_volume,
                              self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.reserve_volume.assert_called_once_with(self.context,
                                                              volume['id'])
            self.assertEqual(0, mock_attach.call_count)
            fake_bdm.destroy.assert_called_once_with()

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch('nova.volume.cinder.is_microversion_supported')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume_attachment_create_fails(self, mock_attach, mock_bdm,
                                                   mock_cinder_mv_supported,
                                                   mock_get_min_ver,
                                                   mock_reserve):
        mock_bdm.side_effect = exception.VolumeBDMNotFound(
                                          volume_id='fake-volume-id')
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        fake_bdm = mock.MagicMock(spec=objects.BlockDeviceMapping)
        mock_reserve.return_value = fake_bdm

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            mock_v_api.attachment_create.side_effect = test.TestingException()
            self.assertRaises(test.TestingException,
                              self.compute_api.attach_volume,
                              self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_v_api.attachment_create.assert_called_once_with(
                self.context, volume['id'], instance.uuid)
            self.assertEqual(0, mock_attach.call_count)
            fake_bdm.destroy.assert_called_once_with()

    def test_suspend(self):
        # Ensure instance can be suspended.
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertIsNone(instance.task_state)

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(rpcapi, 'suspend_instance')
        ) as (mock_inst_save, mock_record_action, mock_suspend_instance):
            self.compute_api.suspend(self.context, instance)
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)
            self.assertEqual(task_states.SUSPENDING, instance.task_state)
            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_record_action.assert_called_once_with(
                self.context, instance, instance_actions.SUSPEND)
            mock_suspend_instance.assert_called_once_with(self.context,
                                                          instance)

    def _test_suspend_fails(self, vm_state):
        params = dict(vm_state=vm_state)
        instance = self._create_instance_obj(params=params)
        self.assertIsNone(instance.task_state)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.suspend,
                          self.context, instance)

    def test_suspend_fails_invalid_states(self):
        invalid_vm_states = self._get_vm_states(set([vm_states.ACTIVE]))
        for state in invalid_vm_states:
            self._test_suspend_fails(state)

    def test_resume(self):
        # Ensure instance can be resumed (if suspended).
        instance = self._create_instance_obj(
                params=dict(vm_state=vm_states.SUSPENDED))
        self.assertEqual(instance.vm_state, vm_states.SUSPENDED)
        self.assertIsNone(instance.task_state)

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(rpcapi, 'resume_instance')
        ) as (mock_inst_save, mock_record_action, mock_resume_instance):
            self.compute_api.resume(self.context, instance)
            self.assertEqual(vm_states.SUSPENDED, instance.vm_state)
            self.assertEqual(task_states.RESUMING,
                             instance.task_state)
            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_record_action.assert_called_once_with(
                self.context, instance, instance_actions.RESUME)
            mock_resume_instance.assert_called_once_with(self.context,
                                                         instance)

    def test_start(self):
        params = dict(vm_state=vm_states.STOPPED)
        instance = self._create_instance_obj(params=params)

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(rpcapi, 'start_instance')
        ) as (mock_inst_save, mock_record_action, mock_start_instance):
            self.compute_api.start(self.context, instance)
            self.assertEqual(task_states.POWERING_ON,
                            instance.task_state)
            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_record_action.assert_called_once_with(
                self.context, instance, instance_actions.START)
            mock_start_instance.assert_called_once_with(self.context,
                                                        instance)

    def test_start_invalid_state(self):
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.start,
                          self.context, instance)

    def test_start_no_host(self):
        params = dict(vm_state=vm_states.STOPPED, host='')
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.start,
                          self.context, instance)

    def _test_stop(self, vm_state, force=False, clean_shutdown=True):
        # Make sure 'progress' gets reset
        params = dict(task_state=None, progress=99, vm_state=vm_state)
        instance = self._create_instance_obj(params=params)

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(rpcapi, 'stop_instance')
        ) as (mock_inst_save, mock_record_action, mock_stop_instance):
            if force:
                self.compute_api.force_stop(self.context, instance,
                                            clean_shutdown=clean_shutdown)
            else:
                self.compute_api.stop(self.context, instance,
                                      clean_shutdown=clean_shutdown)
            self.assertEqual(task_states.POWERING_OFF,
                             instance.task_state)
            self.assertEqual(0, instance.progress)

            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_record_action.assert_called_once_with(
                self.context, instance, instance_actions.STOP)
            mock_stop_instance.assert_called_once_with(
                self.context, instance, do_cast=True,
                clean_shutdown=clean_shutdown)

    def test_stop(self):
        self._test_stop(vm_states.ACTIVE)

    def test_stop_stopped_instance_with_bypass(self):
        self._test_stop(vm_states.STOPPED, force=True)

    def test_stop_forced_shutdown(self):
        self._test_stop(vm_states.ACTIVE, force=True)

    def test_stop_without_clean_shutdown(self):
        self._test_stop(vm_states.ACTIVE,
                       clean_shutdown=False)

    def test_stop_forced_without_clean_shutdown(self):
        self._test_stop(vm_states.ACTIVE, force=True,
                        clean_shutdown=False)

    def _test_stop_invalid_state(self, vm_state):
        params = dict(vm_state=vm_state)
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.stop,
                          self.context, instance)

    def test_stop_fails_invalid_states(self):
        invalid_vm_states = self._get_vm_states(set([vm_states.ACTIVE,
                                                     vm_states.ERROR]))
        for state in invalid_vm_states:
            self._test_stop_invalid_state(state)

    def test_stop_a_stopped_inst(self):
        params = {'vm_state': vm_states.STOPPED}
        instance = self._create_instance_obj(params=params)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.stop,
                          self.context, instance)

    def test_stop_no_host(self):
        params = {'host': ''}
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.stop,
                          self.context, instance)

    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.trigger_crash_dump')
    def test_trigger_crash_dump(self,
                                trigger_crash_dump,
                                _record_action_start):
        instance = self._create_instance_obj()

        self.compute_api.trigger_crash_dump(self.context, instance)

        _record_action_start.assert_called_once_with(self.context, instance,
            instance_actions.TRIGGER_CRASH_DUMP)

        if self.cell_type == 'api':
            # cell api has not been implemented.
            pass
        else:
            trigger_crash_dump.assert_called_once_with(self.context, instance)

        self.assertIsNone(instance.task_state)

    def test_trigger_crash_dump_invalid_state(self):
        params = dict(vm_state=vm_states.STOPPED)
        instance = self._create_instance_obj(params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.trigger_crash_dump,
                          self.context, instance)

    def test_trigger_crash_dump_no_host(self):
        params = dict(host='')
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.trigger_crash_dump,
                          self.context, instance)

    def test_trigger_crash_dump_locked(self):
        params = dict(locked=True)
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceIsLocked,
                          self.compute_api.trigger_crash_dump,
                          self.context, instance)

    def _test_reboot_type(self, vm_state, reboot_type, task_state=None):
        # Ensure instance can be soft rebooted.
        inst = self._create_instance_obj()
        inst.vm_state = vm_state
        inst.task_state = task_state

        expected_task_state = [None]
        if reboot_type == 'HARD':
            expected_task_state.extend([task_states.REBOOTING,
                                        task_states.REBOOT_PENDING,
                                        task_states.REBOOT_STARTED,
                                        task_states.REBOOTING_HARD,
                                        task_states.RESUMING,
                                        task_states.UNPAUSING,
                                        task_states.SUSPENDING])

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        with test.nested(
            mock.patch.object(self.context, 'elevated'),
            mock.patch.object(inst, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(rpcapi, 'reboot_instance')
        ) as (mock_elevated, mock_inst_save,
              mock_record_action, mock_reboot_instance):
            self.compute_api.reboot(self.context, inst, reboot_type)

            mock_inst_save.assert_called_once_with(
                expected_task_state=expected_task_state)
            mock_record_action.assert_called_once_with(
                self.context, inst, instance_actions.REBOOT)
            mock_reboot_instance.assert_called_once_with(
                self.context, instance=inst,
                block_device_info=None, reboot_type=reboot_type)

    def _test_reboot_type_fails(self, reboot_type, **updates):
        inst = self._create_instance_obj()
        inst.update(updates)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.reboot,
                          self.context, inst, reboot_type)

    def test_reboot_hard_active(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD')

    def test_reboot_hard_error(self):
        self._test_reboot_type(vm_states.ERROR, 'HARD')

    def test_reboot_hard_rebooting(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD',
                               task_state=task_states.REBOOTING)

    def test_reboot_hard_reboot_started(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD',
                               task_state=task_states.REBOOT_STARTED)

    def test_reboot_hard_reboot_pending(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD',
                               task_state=task_states.REBOOT_PENDING)

    def test_reboot_hard_rescued(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.RESCUED)

    def test_reboot_hard_resuming(self):
        self._test_reboot_type(vm_states.ACTIVE,
                               'HARD', task_state=task_states.RESUMING)

    def test_reboot_hard_pausing(self):
        self._test_reboot_type(vm_states.ACTIVE,
                               'HARD', task_state=task_states.PAUSING)

    def test_reboot_hard_unpausing(self):
        self._test_reboot_type(vm_states.ACTIVE,
                               'HARD', task_state=task_states.UNPAUSING)

    def test_reboot_hard_suspending(self):
        self._test_reboot_type(vm_states.ACTIVE,
                               'HARD', task_state=task_states.SUSPENDING)

    def test_reboot_hard_error_not_launched(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.ERROR,
                                     launched_at=None)

    def test_reboot_soft(self):
        self._test_reboot_type(vm_states.ACTIVE, 'SOFT')

    def test_reboot_soft_error(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.ERROR)

    def test_reboot_soft_paused(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.PAUSED)

    def test_reboot_soft_stopped(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.STOPPED)

    def test_reboot_soft_suspended(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.SUSPENDED)

    def test_reboot_soft_rebooting(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.REBOOTING)

    def test_reboot_soft_rebooting_hard(self):
        self._test_reboot_type_fails('SOFT',
                                     task_state=task_states.REBOOTING_HARD)

    def test_reboot_soft_reboot_started(self):
        self._test_reboot_type_fails('SOFT',
                                     task_state=task_states.REBOOT_STARTED)

    def test_reboot_soft_reboot_pending(self):
        self._test_reboot_type_fails('SOFT',
                                     task_state=task_states.REBOOT_PENDING)

    def test_reboot_soft_rescued(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.RESCUED)

    def test_reboot_soft_error_not_launched(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.ERROR,
                                     launched_at=None)

    def test_reboot_soft_resuming(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.RESUMING)

    def test_reboot_soft_pausing(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.PAUSING)

    def test_reboot_soft_unpausing(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.UNPAUSING)

    def test_reboot_soft_suspending(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.SUSPENDING)

    def _test_delete_resizing_part(self, inst, deltas):
        old_flavor = inst.old_flavor
        deltas['cores'] = -old_flavor.vcpus
        deltas['ram'] = -old_flavor.memory_mb

    def _test_delete_resized_part(self, inst):
        migration = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())

        self.mox.StubOutWithMock(objects.Migration,
                                 'get_by_instance_and_status')

        self.context.elevated().AndReturn(self.context)
        objects.Migration.get_by_instance_and_status(
            self.context, inst.uuid, 'finished').AndReturn(migration)
        self.compute_api._record_action_start(
            self.context, inst, instance_actions.CONFIRM_RESIZE)
        self.compute_api.compute_rpcapi.confirm_resize(
            self.context, inst, migration,
            migration['source_compute'], cast=False)

    def _test_delete_shelved_part(self, inst):
        image_api = self.compute_api.image_api
        self.mox.StubOutWithMock(image_api, 'delete')

        snapshot_id = inst.system_metadata.get('shelved_image_id')
        if snapshot_id == SHELVED_IMAGE:
            image_api.delete(self.context, snapshot_id).AndReturn(True)
        elif snapshot_id == SHELVED_IMAGE_NOT_FOUND:
            image_api.delete(self.context, snapshot_id).AndRaise(
                exception.ImageNotFound(image_id=snapshot_id))
        elif snapshot_id == SHELVED_IMAGE_NOT_AUTHORIZED:
            image_api.delete(self.context, snapshot_id).AndRaise(
                exception.ImageNotAuthorized(image_id=snapshot_id))
        elif snapshot_id == SHELVED_IMAGE_EXCEPTION:
            image_api.delete(self.context, snapshot_id).AndRaise(
                test.TestingException("Unexpected error"))

    def _test_downed_host_part(self, inst, updates, delete_time, delete_type):
        if 'soft' in delete_type:
            compute_utils.notify_about_instance_usage(
                self.compute_api.notifier, self.context, inst,
                'delete.start')
        else:
            compute_utils.notify_about_instance_usage(
                self.compute_api.notifier, self.context, inst,
                '%s.start' % delete_type)
        self.context.elevated().AndReturn(self.context)
        self.compute_api.network_api.deallocate_for_instance(
            self.context, inst)
        state = ('soft' in delete_type and vm_states.SOFT_DELETED or
                 vm_states.DELETED)
        updates.update({'vm_state': state,
                        'task_state': None,
                        'terminated_at': delete_time})
        inst.save()

        updates.update({'deleted_at': delete_time,
                        'deleted': True})
        fake_inst = fake_instance.fake_db_instance(**updates)
        self.compute_api._local_cleanup_bdm_volumes([], inst, self.context)
        db.instance_destroy(self.context, inst.uuid,
                            constraint=None).AndReturn(fake_inst)
        if 'soft' in delete_type:
            compute_utils.notify_about_instance_usage(
                self.compute_api.notifier,
                self.context, inst, 'delete.end',
                system_metadata=inst.system_metadata)
        else:
            compute_utils.notify_about_instance_usage(
                self.compute_api.notifier,
                self.context, inst, '%s.end' % delete_type,
                system_metadata=inst.system_metadata)
        cell = objects.CellMapping(uuid=uuids.cell,
                                   transport_url='fake://',
                                   database_connection='fake://')
        im = objects.InstanceMapping(cell_mapping=cell)
        objects.InstanceMapping.get_by_instance_uuid(
            self.context, inst.uuid).AndReturn(im)

    def _test_delete(self, delete_type, **attrs):
        inst = self._create_instance_obj()
        inst.update(attrs)
        inst._context = self.context
        deltas = {'instances': -1,
                  'cores': -inst.flavor.vcpus,
                  'ram': -inst.flavor.memory_mb}
        delete_time = datetime.datetime(1955, 11, 5, 9, 30,
                                        tzinfo=iso8601.UTC)
        self.useFixture(utils_fixture.TimeFixture(delete_time))
        task_state = (delete_type == 'soft_delete' and
                      task_states.SOFT_DELETING or task_states.DELETING)
        updates = {'progress': 0, 'task_state': task_state}
        if delete_type == 'soft_delete':
            updates['deleted_at'] = delete_time
        self.mox.StubOutWithMock(inst, 'save')
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(objects.Service, 'get_by_compute_host')
        self.mox.StubOutWithMock(self.compute_api.servicegroup_api,
                                 'service_is_up')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(self.compute_api.network_api,
                                 'deallocate_for_instance')
        self.mox.StubOutWithMock(db, 'instance_system_metadata_get')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'confirm_resize')
        self.mox.StubOutWithMock(self.compute_api.consoleauth_rpcapi,
                                 'delete_tokens_for_instance')
        self.mox.StubOutWithMock(objects.InstanceMapping,
                                 'get_by_instance_uuid')

        if (inst.vm_state in
            (vm_states.SHELVED, vm_states.SHELVED_OFFLOADED)):
            self._test_delete_shelved_part(inst)

        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'terminate_instance')
        self.mox.StubOutWithMock(rpcapi, 'soft_delete_instance')

        objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, inst.uuid).AndReturn([])
        inst.save()
        if inst.task_state == task_states.RESIZE_FINISH:
            self._test_delete_resizing_part(inst, deltas)

        # NOTE(comstud): This is getting messy.  But what we are wanting
        # to test is:
        # If cells is enabled and we're the API cell:
        #   * Cast to cells_rpcapi.<method>
        # Otherwise:
        #   * Check for downed host
        #   * If downed host:
        #     * Clean up instance, destroying it, sending notifications.
        #       (Tested in _test_downed_host_part())
        #   * If not downed host:
        #     * Record the action start.
        #     * Cast to compute_rpcapi.<method>

        cast = True
        if self.cell_type != 'api':
            if inst.vm_state == vm_states.RESIZED:
                self._test_delete_resized_part(inst)
            if inst.host is not None:
                self.context.elevated().AndReturn(self.context)
                objects.Service.get_by_compute_host(self.context,
                        inst.host).AndReturn(objects.Service())
                self.compute_api.servicegroup_api.service_is_up(
                        mox.IsA(objects.Service)).AndReturn(
                                inst.host != 'down-host')

            if inst.host == 'down-host' or inst.host is None:
                self._test_downed_host_part(inst, updates, delete_time,
                                            delete_type)
                cast = False

        if cast:
            if self.cell_type != 'api':
                self.compute_api._record_action_start(self.context, inst,
                                                      instance_actions.DELETE)
            if delete_type == 'soft_delete':
                rpcapi.soft_delete_instance(self.context, inst)
            elif delete_type in ['delete', 'force_delete']:
                rpcapi.terminate_instance(self.context, inst, [],
                                          delete_type=delete_type)

        if self.cell_type is None or self.cell_type == 'api':
            self.compute_api.consoleauth_rpcapi.delete_tokens_for_instance(
                self.context, inst.uuid)

        self.mox.ReplayAll()

        getattr(self.compute_api, delete_type)(self.context, inst)
        for k, v in updates.items():
            self.assertEqual(inst[k], v)

        self.mox.UnsetStubs()

    def test_delete(self):
        self._test_delete('delete')

    def test_delete_if_not_launched(self):
        self._test_delete('delete', launched_at=None)

    def test_delete_in_resizing(self):
        old_flavor = objects.Flavor(vcpus=1, memory_mb=512, extra_specs={})
        self._test_delete('delete',
                          task_state=task_states.RESIZE_FINISH,
                          old_flavor=old_flavor)

    def test_delete_in_resized(self):
        self._test_delete('delete', vm_state=vm_states.RESIZED)

    def test_delete_shelved(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE}
        self._test_delete('delete',
                          vm_state=vm_states.SHELVED,
                          system_metadata=fake_sys_meta)

    def test_delete_shelved_offloaded(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE}
        self._test_delete('delete',
                          vm_state=vm_states.SHELVED_OFFLOADED,
                          system_metadata=fake_sys_meta)

    def test_delete_shelved_image_not_found(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE_NOT_FOUND}
        self._test_delete('delete',
                          vm_state=vm_states.SHELVED_OFFLOADED,
                          system_metadata=fake_sys_meta)

    def test_delete_shelved_image_not_authorized(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE_NOT_AUTHORIZED}
        self._test_delete('delete',
                          vm_state=vm_states.SHELVED_OFFLOADED,
                          system_metadata=fake_sys_meta)

    def test_delete_shelved_exception(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE_EXCEPTION}
        self._test_delete('delete',
                          vm_state=vm_states.SHELVED,
                          system_metadata=fake_sys_meta)

    def test_delete_with_down_host(self):
        self._test_delete('delete', host='down-host')

    def test_delete_soft_with_down_host(self):
        self._test_delete('soft_delete', host='down-host')

    def test_delete_soft(self):
        self._test_delete('soft_delete')

    def test_delete_forced(self):
        fake_sys_meta = {'shelved_image_id': SHELVED_IMAGE}
        for vm_state in self._get_vm_states():
            if vm_state in (vm_states.SHELVED, vm_states.SHELVED_OFFLOADED):
                self._test_delete('force_delete',
                                  vm_state=vm_state,
                                  system_metadata=fake_sys_meta)
            self._test_delete('force_delete', vm_state=vm_state)

    @mock.patch('nova.compute.api.API._delete_while_booting',
                return_value=False)
    @mock.patch('nova.compute.api.API._lookup_instance')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch('nova.compute.api.API._local_delete')
    def test_delete_error_state_with_no_host(
            self, mock_local_delete, mock_service_get, _mock_notify,
            _mock_save, mock_bdm_get, mock_lookup, _mock_del_booting):
        # Instance in error state with no host should be a local delete
        # for non API cells
        inst = self._create_instance_obj(params=dict(vm_state=vm_states.ERROR,
                                                     host=None))
        mock_lookup.return_value = None, inst
        with mock.patch.object(self.compute_api.compute_rpcapi,
                               'terminate_instance') as mock_terminate:
            self.compute_api.delete(self.context, inst)
            if self.cell_type == 'api':
                mock_terminate.assert_called_once_with(
                        self.context, inst, mock_bdm_get.return_value,
                        delete_type='delete')
                mock_local_delete.assert_not_called()
            else:
                mock_local_delete.assert_called_once_with(
                        self.context, inst, mock_bdm_get.return_value,
                        'delete', self.compute_api._do_delete)
                mock_terminate.assert_not_called()
        mock_service_get.assert_not_called()

    @mock.patch('nova.compute.api.API._delete_while_booting',
                return_value=False)
    @mock.patch('nova.compute.api.API._lookup_instance')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.servicegroup.api.API.service_is_up', return_value=True)
    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch('nova.compute.api.API._local_delete')
    def test_delete_error_state_with_host_set(
            self, mock_local_delete, _mock_record, mock_service_up,
            mock_elevated, mock_service_get, _mock_notify, _mock_save,
            mock_bdm_get, mock_lookup, _mock_del_booting):
        # Instance in error state with host set should be a non-local delete
        # for non API cells if the service is up
        inst = self._create_instance_obj(params=dict(vm_state=vm_states.ERROR,
                                                     host='fake-host'))
        mock_lookup.return_value = inst
        with mock.patch.object(self.compute_api.compute_rpcapi,
                               'terminate_instance') as mock_terminate:
            self.compute_api.delete(self.context, inst)
            if self.cell_type == 'api':
                mock_terminate.assert_called_once_with(
                        self.context, inst, mock_bdm_get.return_value,
                        delete_type='delete')
                mock_local_delete.assert_not_called()
                mock_service_get.assert_not_called()
            else:
                mock_service_get.assert_called_once_with(
                        mock_elevated.return_value, 'fake-host')
                mock_service_up.assert_called_once_with(
                        mock_service_get.return_value)
                mock_terminate.assert_called_once_with(
                        self.context, inst, mock_bdm_get.return_value,
                        delete_type='delete')
                mock_local_delete.assert_not_called()

    def test_delete_fast_if_host_not_set(self):
        self.useFixture(fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()
        inst.host = ''
        updates = {'progress': 0, 'task_state': task_states.DELETING}

        self.mox.StubOutWithMock(objects.BuildRequest,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(inst, 'save')
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')

        self.mox.StubOutWithMock(db, 'constraint')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(self.compute_api, '_lookup_instance')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'terminate_instance')

        self.compute_api._lookup_instance(self.context,
                                          inst.uuid).AndReturn((None, inst))
        objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, inst.uuid).AndReturn(
                objects.BlockDeviceMappingList())
        objects.BuildRequest.get_by_instance_uuid(
            self.context, inst.uuid).AndRaise(
                exception.BuildRequestNotFound(uuid=inst.uuid))
        inst.save()

        if self.cell_type == 'api':
            rpcapi.terminate_instance(
                    self.context, inst,
                    mox.IsA(objects.BlockDeviceMappingList),
                    delete_type='delete')
        else:
            compute_utils.notify_about_instance_usage(
                    self.compute_api.notifier, self.context,
                    inst, 'delete.start')
            db.constraint(host=mox.IgnoreArg()).AndReturn('constraint')
            delete_time = datetime.datetime(1955, 11, 5, 9, 30,
                                            tzinfo=iso8601.UTC)
            updates['deleted_at'] = delete_time
            updates['deleted'] = True
            fake_inst = fake_instance.fake_db_instance(**updates)
            db.instance_destroy(self.context, inst.uuid,
                                constraint='constraint').AndReturn(fake_inst)
            compute_utils.notify_about_instance_usage(
                    self.compute_api.notifier, self.context,
                    inst, 'delete.end', system_metadata={})

        self.mox.ReplayAll()

        self.compute_api.delete(self.context, inst)
        for k, v in updates.items():
            self.assertEqual(inst[k], v)

    def _fake_do_delete(context, instance, bdms,
                        rservations=None, local=False):
        pass

    def test_local_delete_with_deleted_volume(self):
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 42, 'volume_id': 'volume_id',
                 'source_type': 'volume', 'destination_type': 'volume',
                 'delete_on_termination': False}))]

        inst = self._create_instance_obj()
        inst._context = self.context

        self.mox.StubOutWithMock(inst, 'destroy')
        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(self.compute_api.network_api,
                                 'deallocate_for_instance')
        self.mox.StubOutWithMock(db, 'instance_system_metadata_get')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute_api.volume_api,
                                 'detach')
        self.mox.StubOutWithMock(objects.BlockDeviceMapping, 'destroy')

        compute_utils.notify_about_instance_usage(
                    self.compute_api.notifier, self.context,
                    inst, 'delete.start')
        self.context.elevated().MultipleTimes().AndReturn(self.context)
        if self.cell_type != 'api':
            self.compute_api.network_api.deallocate_for_instance(
                        self.context, inst)

        self.compute_api.volume_api.detach(
            mox.IgnoreArg(), 'volume_id', inst.uuid).\
               AndRaise(exception.VolumeNotFound('volume_id'))
        bdms[0].destroy()

        inst.destroy()
        compute_utils.notify_about_instance_usage(
                    self.compute_api.notifier, self.context,
                    inst, 'delete.end',
                    system_metadata=inst.system_metadata)

        self.mox.ReplayAll()
        self.compute_api._local_delete(self.context, inst, bdms,
                                       'delete',
                                       self._fake_do_delete)

    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    def test_local_cleanup_bdm_volumes_stashed_connector(self, mock_destroy):
        """Tests that we call volume_api.terminate_connection when we found
        a stashed connector in the bdm.connection_info dict.
        """
        inst = self._create_instance_obj()
        # create two fake bdms, one is a volume and one isn't, both will be
        # destroyed but we only cleanup the volume bdm in cinder
        conn_info = {'connector': {'host': inst.host}}
        vol_bdm = objects.BlockDeviceMapping(self.context, id=1,
                                             instance_uuid=inst.uuid,
                                             volume_id=uuids.volume_id,
                                             source_type='volume',
                                             destination_type='volume',
                                             delete_on_termination=True,
                                             connection_info=jsonutils.dumps(
                                                conn_info
                                             ),
                                             attachment_id=None,)
        loc_bdm = objects.BlockDeviceMapping(self.context, id=2,
                                             instance_uuid=inst.uuid,
                                             volume_id=uuids.volume_id2,
                                             source_type='blank',
                                             destination_type='local')
        bdms = objects.BlockDeviceMappingList(objects=[vol_bdm, loc_bdm])

        @mock.patch.object(self.compute_api.volume_api, 'terminate_connection')
        @mock.patch.object(self.compute_api.volume_api, 'detach')
        @mock.patch.object(self.compute_api.volume_api, 'delete')
        @mock.patch.object(self.context, 'elevated', return_value=self.context)
        def do_test(self, mock_elevated, mock_delete,
                    mock_detach, mock_terminate):
            self.compute_api._local_cleanup_bdm_volumes(
                bdms, inst, self.context)
            mock_terminate.assert_called_once_with(
                self.context, uuids.volume_id, conn_info['connector'])
            mock_detach.assert_called_once_with(
                self.context, uuids.volume_id, inst.uuid)
            mock_delete.assert_called_once_with(self.context, uuids.volume_id)
            self.assertEqual(2, mock_destroy.call_count)

        do_test(self)

    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    def test_local_cleanup_bdm_volumes_with_attach_id(self, mock_destroy):
        """Tests that we call volume_api.attachment_delete when we have an
        attachment_id in the bdm.
        """
        instance = self._create_instance_obj()
        conn_info = {'connector': {'host': instance.host}}
        vol_bdm = objects.BlockDeviceMapping(
            self.context,
            id=1,
            instance_uuid=instance.uuid,
            volume_id=uuids.volume_id,
            source_type='volume',
            destination_type='volume',
            delete_on_termination=True,
            connection_info=jsonutils.dumps(conn_info),
            attachment_id=uuids.attachment_id)
        bdms = objects.BlockDeviceMappingList(objects=[vol_bdm])

        @mock.patch.object(self.compute_api.volume_api, 'delete')
        @mock.patch.object(self.compute_api.volume_api, 'attachment_delete')
        @mock.patch.object(self.context, 'elevated', return_value=self.context)
        def do_test(self, mock_elevated, mock_attach_delete, mock_delete):
            self.compute_api._local_cleanup_bdm_volumes(
                bdms, instance, self.context)

            mock_attach_delete.assert_called_once_with(
                self.context, vol_bdm.attachment_id)
            mock_delete.assert_called_once_with(
                self.context, vol_bdm.volume_id)
            mock_destroy.assert_called_once_with()
        do_test(self)

    def test_get_stashed_volume_connector_none(self):
        inst = self._create_instance_obj()
        # connection_info isn't set
        bdm = objects.BlockDeviceMapping(self.context)
        self.assertIsNone(
            self.compute_api._get_stashed_volume_connector(bdm, inst))
        # connection_info is None
        bdm.connection_info = None
        self.assertIsNone(
            self.compute_api._get_stashed_volume_connector(bdm, inst))
        # connector is not set in connection_info
        bdm.connection_info = jsonutils.dumps({})
        self.assertIsNone(
            self.compute_api._get_stashed_volume_connector(bdm, inst))
        # connector is set but different host
        conn_info = {'connector': {'host': 'other_host'}}
        bdm.connection_info = jsonutils.dumps(conn_info)
        self.assertIsNone(
            self.compute_api._get_stashed_volume_connector(bdm, inst))

    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    def test_local_cleanup_bdm_volumes_stashed_connector_host_none(
            self, mock_destroy):
        """Tests that we call volume_api.terminate_connection when we found
        a stashed connector in the bdm.connection_info dict.

        This tests the case where:

            1) the instance host is None
            2) the instance vm_state is one where we expect host to be None

        We allow a mismatch of the host in this situation if the instance is
        in a state where we expect its host to have been set to None, such
        as ERROR or SHELVED_OFFLOADED.
        """
        params = dict(host=None, vm_state=vm_states.ERROR)
        inst = self._create_instance_obj(params=params)
        conn_info = {'connector': {'host': 'orig-host'}}
        vol_bdm = objects.BlockDeviceMapping(self.context, id=1,
                                             instance_uuid=inst.uuid,
                                             volume_id=uuids.volume_id,
                                             source_type='volume',
                                             destination_type='volume',
                                             delete_on_termination=True,
                                             connection_info=jsonutils.dumps(
                                                conn_info),
                                             attachment_id=None)
        bdms = objects.BlockDeviceMappingList(objects=[vol_bdm])

        @mock.patch.object(self.compute_api.volume_api, 'terminate_connection')
        @mock.patch.object(self.compute_api.volume_api, 'detach')
        @mock.patch.object(self.compute_api.volume_api, 'delete')
        @mock.patch.object(self.context, 'elevated', return_value=self.context)
        def do_test(self, mock_elevated, mock_delete,
                    mock_detach, mock_terminate):
            self.compute_api._local_cleanup_bdm_volumes(
                bdms, inst, self.context)
            mock_terminate.assert_called_once_with(
                self.context, uuids.volume_id, conn_info['connector'])
            mock_detach.assert_called_once_with(
                self.context, uuids.volume_id, inst.uuid)
            mock_delete.assert_called_once_with(self.context, uuids.volume_id)
            mock_destroy.assert_called_once_with()

        do_test(self)

    def test_local_delete_without_info_cache(self):
        inst = self._create_instance_obj()

        with test.nested(
            mock.patch.object(inst, 'destroy'),
            mock.patch.object(self.context, 'elevated'),
            mock.patch.object(self.compute_api.network_api,
                              'deallocate_for_instance'),
            mock.patch.object(db, 'instance_system_metadata_get'),
            mock.patch.object(compute_utils,
                              'notify_about_instance_usage')
        ) as (
            inst_destroy, context_elevated, net_api_deallocate_for_instance,
            db_instance_system_metadata_get, notify_about_instance_usage
        ):

            compute_utils.notify_about_instance_usage(
                        self.compute_api.notifier, self.context,
                        inst, 'delete.start')
            self.context.elevated().MultipleTimes().AndReturn(self.context)
            if self.cell_type != 'api':
                self.compute_api.network_api.deallocate_for_instance(
                            self.context, inst)

            inst.destroy()
            compute_utils.notify_about_instance_usage(
                        self.compute_api.notifier, self.context,
                        inst, 'delete.end',
                        system_metadata=inst.system_metadata)
            inst.info_cache = None
            self.compute_api._local_delete(self.context, inst, [],
                                           'delete',
                                           self._fake_do_delete)

    def test_delete_disabled(self):
        inst = self._create_instance_obj()
        inst.disable_terminate = True
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.ReplayAll()
        self.compute_api.delete(self.context, inst)

    def test_delete_soft_rollback(self):
        inst = self._create_instance_obj()
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(inst, 'save')

        delete_time = datetime.datetime(1955, 11, 5)
        self.useFixture(utils_fixture.TimeFixture(delete_time))

        objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, inst.uuid).AndReturn(
                objects.BlockDeviceMappingList())
        inst.save().AndRaise(test.TestingException)

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.compute_api.soft_delete, self.context, inst)

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_attempt_delete_of_buildrequest_success(self, mock_get_by_inst):
        build_req_mock = mock.MagicMock()
        mock_get_by_inst.return_value = build_req_mock

        inst = self._create_instance_obj()
        self.assertTrue(
            self.compute_api._attempt_delete_of_buildrequest(self.context,
                                                             inst))
        self.assertTrue(build_req_mock.destroy.called)

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_attempt_delete_of_buildrequest_not_found(self, mock_get_by_inst):
        mock_get_by_inst.side_effect = exception.BuildRequestNotFound(
                                                                uuid='fake')

        inst = self._create_instance_obj()
        self.assertFalse(
            self.compute_api._attempt_delete_of_buildrequest(self.context,
                                                             inst))

    def test_attempt_delete_of_buildrequest_already_deleted(self):
        inst = self._create_instance_obj()
        build_req_mock = mock.MagicMock()
        build_req_mock.destroy.side_effect = exception.BuildRequestNotFound(
                                                                uuid='fake')
        with mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid',
                               return_value=build_req_mock):
            self.assertFalse(
                self.compute_api._attempt_delete_of_buildrequest(self.context,
                                                                 inst))
            self.assertTrue(build_req_mock.destroy.called)

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=0)
    def test_delete_while_booting_low_service_version(self,
            mock_get_service_version):
        inst = self._create_instance_obj()
        with mock.patch.object(self.compute_api,
                   '_attempt_delete_of_buildrequest') as mock_attempt_delete:
            self.assertFalse(
                self.compute_api._delete_while_booting(self.context, inst))
            self.assertTrue(mock_attempt_delete.called)
        mock_get_service_version.assert_called_once_with(self.context,
                                                         'nova-osapi_compute')

    def test_delete_while_booting_buildreq_not_deleted(self):
        self.useFixture(fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()
        with mock.patch.object(self.compute_api,
                               '_attempt_delete_of_buildrequest',
                               return_value=False):
            self.assertFalse(
                self.compute_api._delete_while_booting(self.context, inst))

    def test_delete_while_booting_buildreq_deleted_instance_none(self):
        self.useFixture(fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()

        @mock.patch.object(self.compute_api, '_attempt_delete_of_buildrequest',
                           return_value=True)
        @mock.patch.object(self.compute_api, '_lookup_instance',
                           return_value=(None, None))
        def test(mock_lookup, mock_attempt):
            self.assertTrue(
                self.compute_api._delete_while_booting(self.context,
                                                       inst))

        test()

    def test_delete_while_booting_buildreq_deleted_instance_not_found(self):
        self.useFixture(fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()

        @mock.patch.object(self.compute_api, '_attempt_delete_of_buildrequest',
                           return_value=True)
        @mock.patch.object(self.compute_api, '_lookup_instance',
                           side_effect=exception.InstanceNotFound(
                               instance_id='fake'))
        def test(mock_lookup, mock_attempt):
            self.assertTrue(
                self.compute_api._delete_while_booting(self.context,
                                                       inst))

        test()

    @mock.patch('nova.compute.utils.notify_about_instance_delete')
    @mock.patch('nova.objects.Instance.destroy')
    def test_delete_instance_from_cell0(self, destroy_mock, notify_mock):
        """Tests the case that the instance does not have a host and was not
        deleted while building, so conductor put it into cell0 so the API has
        to delete the instance from cell0.
        """
        instance = self._create_instance_obj({'host': None})
        cell0 = objects.CellMapping(uuid=objects.CellMapping.CELL0_UUID)

        with test.nested(
            mock.patch.object(self.compute_api, '_delete_while_booting',
                              return_value=False),
            mock.patch.object(self.compute_api, '_lookup_instance',
                              return_value=(cell0, instance)),
        ) as (
            _delete_while_booting, _lookup_instance,
        ):
            self.compute_api._delete(
                self.context, instance, 'delete', mock.NonCallableMock())
            _delete_while_booting.assert_called_once_with(
                self.context, instance)
            _lookup_instance.assert_called_once_with(
                self.context, instance.uuid)
            notify_mock.assert_called_once_with(
                self.compute_api.notifier, self.context, instance)
            destroy_mock.assert_called_once_with()

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       side_effect=exception.InstanceMappingNotFound(
                           uuid='fake'))
    def test_lookup_instance_mapping_none(self, mock_map_get,
                                          mock_target_cell):
        instance = self._create_instance_obj()
        with mock.patch.object(objects.Instance, 'get_by_uuid',
                               return_value=instance) as mock_inst_get:

            cell, ret_instance = self.compute_api._lookup_instance(
                self.context, instance.uuid)
            self.assertEqual((None, instance), (cell, ret_instance))
            mock_inst_get.assert_called_once_with(self.context, instance.uuid)
            self.assertFalse(mock_target_cell.called)

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       return_value=objects.InstanceMapping(cell_mapping=None))
    def test_lookup_instance_cell_mapping_none(self, mock_map_get,
                                          mock_target_cell):
        instance = self._create_instance_obj()
        with mock.patch.object(objects.Instance, 'get_by_uuid',
                               return_value=instance) as mock_inst_get:

            cell, ret_instance = self.compute_api._lookup_instance(
                self.context, instance.uuid)
            self.assertEqual((None, instance), (cell, ret_instance))
            mock_inst_get.assert_called_once_with(self.context, instance.uuid)
            self.assertFalse(mock_target_cell.called)

    @mock.patch.object(context, 'target_cell')
    def test_lookup_instance_cell_mapping(self, mock_target_cell):
        instance = self._create_instance_obj()
        mock_target_cell.return_value.__enter__.return_value = self.context

        inst_map = objects.InstanceMapping(
            cell_mapping=objects.CellMapping(database_connection='',
                                             transport_url='none'))

        @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                           return_value=inst_map)
        @mock.patch.object(objects.Instance, 'get_by_uuid',
                           return_value=instance)
        def test(mock_inst_get, mock_map_get):
            cell, ret_instance = self.compute_api._lookup_instance(
                self.context, instance.uuid)
            expected_cell = (self.cell_type is None and
                             inst_map.cell_mapping or None)
            self.assertEqual((expected_cell, instance),
                             (cell, ret_instance))
            mock_inst_get.assert_called_once_with(self.context, instance.uuid)
            if self.cell_type is None:
                mock_target_cell.assert_called_once_with(self.context,
                                                         inst_map.cell_mapping)
            else:
                self.assertFalse(mock_target_cell.called)

        test()

    def _test_confirm_resize(self, mig_ref_passed=False):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_mig = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(objects.Migration,
                                 'get_by_instance_and_status')
        self.mox.StubOutWithMock(fake_mig, 'save')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'confirm_resize')

        self.context.elevated().AndReturn(self.context)
        if not mig_ref_passed:
            objects.Migration.get_by_instance_and_status(
                    self.context, fake_inst['uuid'], 'finished').AndReturn(
                            fake_mig)

        def _check_mig(expected_task_state=None):
            self.assertEqual('confirming', fake_mig.status)

        fake_mig.save().WithSideEffects(_check_mig)

        self.compute_api._record_action_start(self.context, fake_inst,
                                              'confirmResize')

        self.compute_api.compute_rpcapi.confirm_resize(
                self.context, fake_inst, fake_mig, 'compute-source')

        self.mox.ReplayAll()

        if mig_ref_passed:
            self.compute_api.confirm_resize(self.context, fake_inst,
                                            migration=fake_mig)
        else:
            self.compute_api.confirm_resize(self.context, fake_inst)

    def test_confirm_resize(self):
        self._test_confirm_resize()

    def test_confirm_resize_with_migration_ref(self):
        self._test_confirm_resize(mig_ref_passed=True)

    @mock.patch('nova.objects.Quotas.check_deltas')
    @mock.patch('nova.objects.Migration.get_by_instance_and_status')
    @mock.patch('nova.context.RequestContext.elevated')
    def _test_revert_resize(self, mock_elevated, mock_get_migration,
                            mock_check):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_inst.old_flavor = fake_inst.flavor
        fake_mig = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())

        mock_elevated.return_value = self.context
        mock_get_migration.return_value = fake_mig

        def _check_state(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_REVERTING,
                             fake_inst.task_state)

        def _check_mig(expected_task_state=None):
            self.assertEqual('reverting', fake_mig.status)

        with test.nested(
            mock.patch.object(fake_inst, 'save', side_effect=_check_state),
            mock.patch.object(fake_mig, 'save', side_effect=_check_mig),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi, 'revert_resize')
        ) as (mock_inst_save, mock_mig_save, mock_record_action,
              mock_revert_resize):
            self.compute_api.revert_resize(self.context, fake_inst)

            mock_elevated.assert_called_once_with()
            mock_get_migration.assert_called_once_with(
                self.context, fake_inst['uuid'], 'finished')
            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_mig_save.assert_called_once_with()
            mock_record_action.assert_called_once_with(self.context, fake_inst,
                                                       'revertResize')
            mock_revert_resize.assert_called_once_with(
                self.context, fake_inst, fake_mig, 'compute-dest')

    def test_revert_resize(self):
        self._test_revert_resize()

    @mock.patch('nova.objects.Quotas.check_deltas')
    @mock.patch('nova.objects.Migration.get_by_instance_and_status')
    @mock.patch('nova.context.RequestContext.elevated')
    def test_revert_resize_concurrent_fail(self, mock_elevated,
                                           mock_get_migration, mock_check):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_inst.old_flavor = fake_inst.flavor
        fake_mig = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())

        mock_elevated.return_value = self.context
        mock_get_migration.return_value = fake_mig

        exc = exception.UnexpectedTaskStateError(
            instance_uuid=fake_inst['uuid'],
            actual={'task_state': task_states.RESIZE_REVERTING},
            expected={'task_state': [None]})

        with mock.patch.object(
                fake_inst, 'save', side_effect=exc) as mock_inst_save:
            self.assertRaises(exception.UnexpectedTaskStateError,
                          self.compute_api.revert_resize,
                          self.context,
                          fake_inst)

            mock_elevated.assert_called_once_with()
            mock_get_migration.assert_called_once_with(
                self.context, fake_inst['uuid'], 'finished')
            mock_inst_save.assert_called_once_with(expected_task_state=[None])

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def _test_resize(self, mock_get_all_by_host,
                     mock_get_by_instance_uuid,
                     flavor_id_passed=True,
                     same_host=False, allow_same_host=False,
                     project_id=None,
                     extra_kwargs=None,
                     same_flavor=False,
                     clean_shutdown=True,
                     host_name=None,
                     request_spec=True,
                     requested_destination=False):
        if extra_kwargs is None:
            extra_kwargs = {}

        self.flags(allow_resize_to_same_host=allow_same_host)

        params = {}
        if project_id is not None:
            # To test instance w/ different project id than context (admin)
            params['project_id'] = project_id
        fake_inst = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        self.mox.StubOutWithMock(compute_utils, 'upsize_quota_delta')
        self.mox.StubOutWithMock(fake_inst, 'save')
        self.mox.StubOutWithMock(quotas_obj.Quotas, 'count_as_dict')
        self.mox.StubOutWithMock(quotas_obj.Quotas,
                                 'limit_check_project_and_user')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        if host_name:
            mock_get_all_by_host.return_value = [objects.ComputeNode(
                host=host_name, hypervisor_hostname='hypervisor_host')]

        current_flavor = fake_inst.get_flavor()
        if flavor_id_passed:
            new_flavor = self._create_flavor(id=200, flavorid='new-flavor-id',
                                name='new_flavor', disabled=False)
            if same_flavor:
                new_flavor.id = current_flavor.id
            flavors.get_flavor_by_flavor_id(
                    'new-flavor-id',
                    read_deleted='no').AndReturn(new_flavor)
        else:
            new_flavor = current_flavor

        if (self.cell_type == 'compute' or
                not (flavor_id_passed and same_flavor)):
            project_id, user_id = quotas_obj.ids_from_instance(self.context,
                                                               fake_inst)
            if flavor_id_passed:
                compute_utils.upsize_quota_delta(
                    self.context, mox.IsA(objects.Flavor),
                    mox.IsA(objects.Flavor)).AndReturn({'cores': 0, 'ram': 0})

                proj_count = {'instances': 1, 'cores': current_flavor.vcpus,
                              'ram': current_flavor.memory_mb}
                user_count = proj_count.copy()
                # mox.IgnoreArg() might be 'instances', 'cores', or 'ram'
                # depending on how the deltas dict is iterated in check_deltas
                quotas_obj.Quotas.count_as_dict(self.context, mox.IgnoreArg(),
                                                project_id,
                                                user_id=user_id).AndReturn(
                                                    {'project': proj_count,
                                                     'user': user_count})
                # The current and new flavor have the same cores/ram
                req_cores = current_flavor.vcpus
                req_ram = current_flavor.memory_mb
                values = {'cores': req_cores, 'ram': req_ram}
                quotas_obj.Quotas.limit_check_project_and_user(
                    self.context, user_values=values, project_values=values,
                    project_id=project_id, user_id=user_id)

            def _check_state(expected_task_state=None):
                self.assertEqual(task_states.RESIZE_PREP,
                                 fake_inst.task_state)
                self.assertEqual(fake_inst.progress, 0)
                for key, value in extra_kwargs.items():
                    self.assertEqual(value, getattr(fake_inst, key))

            fake_inst.save(expected_task_state=[None]).WithSideEffects(
                    _check_state)

            if allow_same_host:
                filter_properties = {'ignore_hosts': []}
            else:
                filter_properties = {'ignore_hosts': [fake_inst['host']]}

            if self.cell_type == 'api':
                mig = objects.Migration()

                def _get_migration(context=None):
                    return mig

                def _check_mig():
                    self.assertEqual(fake_inst.uuid, mig.instance_uuid)
                    self.assertEqual(current_flavor.id,
                                     mig.old_instance_type_id)
                    self.assertEqual(new_flavor.id,
                                     mig.new_instance_type_id)
                    self.assertEqual('finished', mig.status)
                    if new_flavor.id != current_flavor.id:
                        self.assertEqual('resize', mig.migration_type)
                    else:
                        self.assertEqual('migration', mig.migration_type)

                self.stubs.Set(objects, 'Migration', _get_migration)
                self.mox.StubOutWithMock(self.context, 'elevated')
                self.mox.StubOutWithMock(mig, 'create')

                self.context.elevated().AndReturn(self.context)
                mig.create().WithSideEffects(_check_mig)

            if flavor_id_passed:
                self.compute_api._record_action_start(self.context, fake_inst,
                                                      'resize')
            else:
                self.compute_api._record_action_start(self.context, fake_inst,
                                                      'migrate')

            if request_spec:
                fake_spec = objects.RequestSpec()
                if requested_destination:
                    cell1 = objects.CellMapping(uuid=uuids.cell1, name='cell1')
                    fake_spec.requested_destination = objects.Destination(
                        host='dummy_host', node='dummy_node', cell=cell1)
                mock_get_by_instance_uuid.return_value = fake_spec
            else:
                mock_get_by_instance_uuid.side_effect = (
                    exception.RequestSpecNotFound(instance_uuid=fake_inst.id))
                fake_spec = None

            scheduler_hint = {'filter_properties': filter_properties}

            self.compute_api.compute_task_api.resize_instance(
                    self.context, fake_inst, extra_kwargs,
                    scheduler_hint=scheduler_hint,
                    flavor=mox.IsA(objects.Flavor),
                    clean_shutdown=clean_shutdown,
                    request_spec=fake_spec)

        self.mox.ReplayAll()

        if flavor_id_passed:
            self.compute_api.resize(self.context, fake_inst,
                                    flavor_id='new-flavor-id',
                                    clean_shutdown=clean_shutdown,
                                    host_name=host_name,
                                    **extra_kwargs)
        else:
            self.compute_api.resize(self.context, fake_inst,
                                    clean_shutdown=clean_shutdown,
                                    host_name=host_name,
                                    **extra_kwargs)

        if request_spec:
            if allow_same_host:
                self.assertEqual([], fake_spec.ignore_hosts)
            else:
                self.assertEqual([fake_inst['host']], fake_spec.ignore_hosts)

            if host_name is None:
                self.assertIsNone(fake_spec.requested_destination)
            else:
                self.assertIn('host', fake_spec.requested_destination)
                self.assertEqual(host_name,
                                 fake_spec.requested_destination.host)
                self.assertIn('node', fake_spec.requested_destination)
                self.assertEqual('hypervisor_host',
                                 fake_spec.requested_destination.node)

    def _test_migrate(self, *args, **kwargs):
        self._test_resize(*args, flavor_id_passed=False, **kwargs)

    def test_resize(self):
        self._test_resize()

    def test_resize_with_kwargs(self):
        self._test_resize(extra_kwargs=dict(cow='moo'))

    def test_resize_same_host_and_allowed(self):
        self._test_resize(same_host=True, allow_same_host=True)

    def test_resize_same_host_and_not_allowed(self):
        self._test_resize(same_host=True, allow_same_host=False)

    def test_resize_different_project_id(self):
        self._test_resize(project_id='different')

    def test_resize_forced_shutdown(self):
        self._test_resize(clean_shutdown=False)

    @mock.patch('nova.compute.flavors.get_flavor_by_flavor_id')
    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    def test_resize_quota_check(self, mock_check, mock_count, mock_get):
        self.flags(cores=1, group='quota')
        self.flags(ram=2048, group='quota')
        proj_count = {'instances': 1, 'cores': 1, 'ram': 1024}
        user_count = proj_count.copy()
        mock_count.return_value = {'project': proj_count,
                                   'user': user_count}

        cur_flavor = objects.Flavor(id=1, name='foo', vcpus=1, memory_mb=512,
                                    root_gb=10, disabled=False)
        fake_inst = self._create_instance_obj()
        fake_inst.flavor = cur_flavor
        new_flavor = objects.Flavor(id=2, name='bar', vcpus=1, memory_mb=2048,
                                    root_gb=10, disabled=False)
        mock_get.return_value = new_flavor
        mock_check.side_effect = exception.OverQuota(
                overs=['ram'], quotas={'cores': 1, 'ram': 2048},
                usages={'instances': 1, 'cores': 1, 'ram': 2048},
                headroom={'ram': 2048})

        self.assertRaises(exception.TooManyInstances, self.compute_api.resize,
                          self.context, fake_inst, flavor_id='new')
        mock_check.assert_called_once_with(
                self.context,
                user_values={'cores': 1, 'ram': 2560},
                project_values={'cores': 1, 'ram': 2560},
                project_id=fake_inst.project_id, user_id=fake_inst.user_id)

    def test_migrate(self):
        self._test_migrate()

    def test_migrate_with_kwargs(self):
        self._test_migrate(extra_kwargs=dict(cow='moo'))

    def test_migrate_same_host_and_allowed(self):
        self._test_migrate(same_host=True, allow_same_host=True)

    def test_migrate_same_host_and_not_allowed(self):
        self._test_migrate(same_host=True, allow_same_host=False)

    def test_migrate_different_project_id(self):
        self._test_migrate(project_id='different')

    def test_migrate_request_spec_not_found(self):
        self._test_migrate(request_spec=False)

    @mock.patch.object(objects.Migration, 'create')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
                       return_value=[objects.ComputeNode(
                           host='target_host',
                           hypervisor_hostname='hypervisor_host')])
    def test_migrate_request_spec_not_found_with_target_host(
            self, mock_get_all_by_host, mock_get_by_instance_uuid, mock_save,
            mock_action_start, mock_migration_create):
        fake_inst = self._create_instance_obj()
        mock_get_by_instance_uuid.side_effect = (
            exception.RequestSpecNotFound(instance_uuid=fake_inst.uuid))
        self.assertRaises(exception.CannotMigrateWithTargetHost,
                          self.compute_api.resize, self.context,
                          fake_inst, host_name='target_host')
        mock_get_all_by_host.assert_called_once_with(
            self.context, 'target_host', True)
        mock_get_by_instance_uuid.assert_called_once_with(self.context,
                                                          fake_inst.uuid)
        mock_save.assert_called_once_with(expected_task_state=[None])
        mock_action_start.assert_called_once_with(
            self.context, fake_inst.uuid, instance_actions.MIGRATE,
            want_result=False)
        if self.cell_type == 'api':
            mock_migration_create.assert_called_once_with()

    def test_migrate_with_requested_destination(self):
        # RequestSpec has requested_destination
        self._test_migrate(requested_destination=True)

    def test_migrate_with_host_name(self):
        self._test_migrate(host_name='target_host')

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
                       side_effect=exception.ComputeHostNotFound(
                           host='nonexistent_host'))
    def test_migrate_nonexistent_host(self, mock_get_all_by_host):
        fake_inst = self._create_instance_obj()
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, host_name='nonexistent_host')

    def test_migrate_to_same_host(self):
        fake_inst = self._create_instance_obj()
        self.assertRaises(exception.CannotMigrateToSameHost,
                          self.compute_api.resize, self.context,
                          fake_inst, host_name='fake_host')

    def test_resize_invalid_flavor_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        # Should never reach these.
        self.mox.StubOutWithMock(quotas_obj.Quotas, 'count_as_dict')
        self.mox.StubOutWithMock(quotas_obj.Quotas,
                                 'limit_check_project_and_user')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = self._create_instance_obj()
        exc = exception.FlavorNotFound(flavor_id='flavor-id')

        flavors.get_flavor_by_flavor_id('flavor-id',
                                        read_deleted='no').AndRaise(exc)

        self.mox.ReplayAll()

        with mock.patch.object(fake_inst, 'save') as mock_save:
            self.assertRaises(exception.FlavorNotFound,
                              self.compute_api.resize, self.context,
                              fake_inst, flavor_id='flavor-id')
            self.assertFalse(mock_save.called)

    def test_resize_disabled_flavor_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        # Should never reach these.
        self.mox.StubOutWithMock(quotas_obj.Quotas, 'count_as_dict')
        self.mox.StubOutWithMock(quotas_obj.Quotas,
                                 'limit_check_project_and_user')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', disabled=True)

        flavors.get_flavor_by_flavor_id(
                'flavor-id', read_deleted='no').AndReturn(fake_flavor)

        self.mox.ReplayAll()

        with mock.patch.object(fake_inst, 'save') as mock_save:
            self.assertRaises(exception.FlavorNotFound,
                              self.compute_api.resize, self.context,
                              fake_inst, flavor_id='flavor-id')
            self.assertFalse(mock_save.called)

    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_to_zero_disk_flavor_fails(self, get_flavor_by_flavor_id):
        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', root_gb=0)

        get_flavor_by_flavor_id.return_value = fake_flavor

        with mock.patch.object(compute_utils, 'is_volume_backed_instance',
                               return_value=False):
            self.assertRaises(exception.CannotResizeDisk,
                              self.compute_api.resize, self.context,
                              fake_inst, flavor_id='flavor-id')

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch('nova.compute.api.API._resize_cells_support')
    @mock.patch('nova.conductor.conductor_api.ComputeTaskAPI.resize_instance')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_to_zero_disk_flavor_volume_backed(self,
                                                      get_flavor_by_flavor_id,
                                                      resize_instance_mock,
                                                      cells_support_mock,
                                                      record_mock,
                                                      get_by_inst):
        params = dict(image_ref='')
        fake_inst = self._create_instance_obj(params=params)

        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                                          name='foo', root_gb=0)

        get_flavor_by_flavor_id.return_value = fake_flavor

        @mock.patch.object(compute_utils, 'is_volume_backed_instance',
                           return_value=True)
        @mock.patch.object(fake_inst, 'save')
        def do_test(mock_save, mock_volume):
            self.compute_api.resize(self.context, fake_inst,
                                    flavor_id='flavor-id')
            mock_volume.assert_called_once_with(self.context, fake_inst)

        do_test()

    def test_resize_quota_exceeds_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        self.mox.StubOutWithMock(compute_utils, 'upsize_quota_delta')
        self.mox.StubOutWithMock(quotas_obj.Quotas, 'count_as_dict')
        self.mox.StubOutWithMock(quotas_obj.Quotas,
                                 'limit_check_project_and_user')
        # Should never reach these.
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', disabled=False)
        flavors.get_flavor_by_flavor_id(
                'flavor-id', read_deleted='no').AndReturn(fake_flavor)
        deltas = dict(cores=0)
        compute_utils.upsize_quota_delta(
            self.context, mox.IsA(objects.Flavor),
            mox.IsA(objects.Flavor)).AndReturn(deltas)
        quotas = {'cores': 0}
        overs = ['cores']
        over_quota_args = dict(quotas=quotas,
                               usages={'instances': 1, 'cores': 1, 'ram': 512},
                               overs=overs)

        proj_count = {'instances': 1, 'cores': fake_inst.flavor.vcpus,
                      'ram': fake_inst.flavor.memory_mb}
        user_count = proj_count.copy()
        # mox.IgnoreArg() might be 'instances', 'cores', or 'ram'
        # depending on how the deltas dict is iterated in check_deltas
        quotas_obj.Quotas.count_as_dict(self.context, mox.IgnoreArg(),
                                        fake_inst.project_id,
                                        user_id=fake_inst.user_id).AndReturn(
                                            {'project': proj_count,
                                             'user': user_count})
        req_cores = fake_inst.flavor.vcpus
        req_ram = fake_inst.flavor.memory_mb
        values = {'cores': req_cores, 'ram': req_ram}
        quotas_obj.Quotas.limit_check_project_and_user(
            self.context, user_values=values, project_values=values,
            project_id=fake_inst.project_id,
            user_id=fake_inst.user_id).AndRaise(
                exception.OverQuota(**over_quota_args))

        self.mox.ReplayAll()

        with mock.patch.object(fake_inst, 'save') as mock_save:
            self.assertRaises(exception.TooManyInstances,
                              self.compute_api.resize, self.context,
                              fake_inst, flavor_id='flavor-id')
            self.assertFalse(mock_save.called)

    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    @mock.patch.object(compute_utils, 'upsize_quota_delta')
    @mock.patch.object(quotas_obj.Quotas, 'count_as_dict')
    @mock.patch.object(quotas_obj.Quotas, 'limit_check_project_and_user')
    def test_resize_quota_exceeds_fails_instance(self, mock_check, mock_count,
                                                 mock_upsize, mock_flavor):
        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', disabled=False)
        mock_flavor.return_value = fake_flavor
        deltas = dict(cores=1, ram=1)
        mock_upsize.return_value = deltas
        quotas = {'instances': 1, 'cores': -1, 'ram': -1}
        overs = ['ram']
        over_quota_args = dict(quotas=quotas,
                               usages={'instances': 1, 'cores': 1, 'ram': 512},
                               overs=overs)
        mock_check.side_effect = exception.OverQuota(**over_quota_args)

        with mock.patch.object(fake_inst, 'save') as mock_save:
            self.assertRaises(exception.TooManyInstances,
                              self.compute_api.resize, self.context,
                              fake_inst, flavor_id='flavor-id')
            self.assertFalse(mock_save.called)

    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    @mock.patch.object(objects.Quotas, 'count_as_dict')
    @mock.patch.object(objects.Quotas, 'limit_check_project_and_user')
    def test_resize_instance_quota_exceeds_with_multiple_resources(
            self, mock_check, mock_count, mock_get_flavor):
        quotas = {'cores': 1, 'ram': 512}
        overs = ['cores', 'ram']
        over_quota_args = dict(quotas=quotas,
                               usages={'instances': 1, 'cores': 1, 'ram': 512},
                               overs=overs)

        proj_count = {'instances': 1, 'cores': 1, 'ram': 512}
        user_count = proj_count.copy()
        mock_count.return_value = {'project': proj_count, 'user': user_count}
        mock_check.side_effect = exception.OverQuota(**over_quota_args)
        mock_get_flavor.return_value = self._create_flavor(id=333,
                                                           vcpus=3,
                                                           memory_mb=1536)
        try:
            self.compute_api.resize(self.context, self._create_instance_obj(),
                                    'fake_flavor_id')
        except exception.TooManyInstances as e:
            self.assertEqual('cores, ram', e.kwargs['overs'])
            self.assertEqual('2, 1024', e.kwargs['req'])
            self.assertEqual('1, 512', e.kwargs['used'])
            self.assertEqual('1, 512', e.kwargs['allowed'])
            mock_get_flavor.assert_called_once_with('fake_flavor_id',
                                                    read_deleted="no")
        else:
            self.fail("Exception not raised")

    def test_pause(self):
        # Ensure instance can be paused.
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertIsNone(instance.task_state)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'pause_instance')

        instance.save(expected_task_state=[None])
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.PAUSE)
        rpcapi.pause_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.pause(self.context, instance)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertEqual(task_states.PAUSING,
                         instance.task_state)

    def _test_pause_fails(self, vm_state):
        params = dict(vm_state=vm_state)
        instance = self._create_instance_obj(params=params)
        self.assertIsNone(instance.task_state)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.pause,
                          self.context, instance)

    def test_pause_fails_invalid_states(self):
        invalid_vm_states = self._get_vm_states(set([vm_states.ACTIVE]))
        for state in invalid_vm_states:
            self._test_pause_fails(state)

    def test_unpause(self):
        # Ensure instance can be unpaused.
        params = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=params)
        self.assertEqual(instance.vm_state, vm_states.PAUSED)
        self.assertIsNone(instance.task_state)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        if self.cell_type == 'api':
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'unpause_instance')

        instance.save(expected_task_state=[None])
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.UNPAUSE)
        rpcapi.unpause_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.unpause(self.context, instance)
        self.assertEqual(vm_states.PAUSED, instance.vm_state)
        self.assertEqual(task_states.UNPAUSING, instance.task_state)

    def test_get_diagnostics_none_host(self):
        instance = self._create_instance_obj()
        instance.host = None
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_diagnostics,
                          self.context, instance)

    def test_get_instance_diagnostics_none_host(self):
        instance = self._create_instance_obj()
        instance.host = None
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_instance_diagnostics,
                          self.context, instance)

    def test_live_migrate_active_vm_state(self):
        instance = self._create_instance_obj()
        self._live_migrate_instance(instance)

    def test_live_migrate_paused_vm_state(self):
        paused_state = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=paused_state)
        self._live_migrate_instance(instance)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    @mock.patch.object(objects.Instance, 'save')
    def test_live_migrate_messaging_timeout(self, _save, _action, get_spec,
                                            add_instance_fault_from_exc):
        instance = self._create_instance_obj()
        if self.cell_type == 'api':
            api = self.compute_api.cells_rpcapi
        else:
            api = conductor.api.ComputeTaskAPI

        with mock.patch.object(api, 'live_migrate_instance',
                               side_effect=oslo_exceptions.MessagingTimeout):
            self.assertRaises(oslo_exceptions.MessagingTimeout,
                              self.compute_api.live_migrate,
                              self.context, instance,
                              host_name='fake_dest_host',
                              block_migration=True, disk_over_commit=True)
            add_instance_fault_from_exc.assert_called_once_with(
                self.context,
                instance,
                mock.ANY)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    def _live_migrate_instance(self, instance, _save, _action, get_spec):
        # TODO(gilliard): This logic is upside-down (different
        # behaviour depending on which class this method is mixed-into. Once
        # we have cellsv2 we can remove this kind of logic from this test
        if self.cell_type == 'api':
            api = self.compute_api.cells_rpcapi
        else:
            api = conductor.api.ComputeTaskAPI
        fake_spec = objects.RequestSpec()
        get_spec.return_value = fake_spec
        with mock.patch.object(api, 'live_migrate_instance') as task:
            self.compute_api.live_migrate(self.context, instance,
                                          block_migration=True,
                                          disk_over_commit=True,
                                          host_name='fake_dest_host')
            self.assertEqual(task_states.MIGRATING, instance.task_state)
            task.assert_called_once_with(self.context, instance,
                                         'fake_dest_host',
                                         block_migration=True,
                                         disk_over_commit=True,
                                         request_spec=fake_spec,
                                         async=False)

    def _get_volumes_for_test_swap_volume(self):
        volumes = {}
        volumes[uuids.old_volume] = {
            'id': uuids.old_volume,
            'display_name': 'old_volume',
            'attach_status': 'attached',
            'size': 5,
            'status': 'in-use',
            'multiattach': False,
            'attachments': {uuids.vol_instance: {'attachment_id': 'fakeid'}}}
        volumes[uuids.new_volume] = {
            'id': uuids.new_volume,
            'display_name': 'new_volume',
            'attach_status': 'detached',
            'size': 5,
            'status': 'available',
            'multiattach': False}

        return volumes

    def _get_instance_for_test_swap_volume(self):
        return fake_instance.fake_instance_obj(None, **{
                   'vm_state': vm_states.ACTIVE,
                   'launched_at': timeutils.utcnow(),
                   'locked': False,
                   'availability_zone': 'fake_az',
                   'uuid': uuids.vol_instance,
                   'task_state': None})

    def _test_swap_volume_for_precheck_with_exception(
            self, exc, instance_update=None, volume_update=None):
        volumes = self._get_volumes_for_test_swap_volume()
        instance = self._get_instance_for_test_swap_volume()
        if instance_update:
            instance.update(instance_update)
        if volume_update:
            volumes[volume_update['target']].update(volume_update['value'])

        self.assertRaises(exc, self.compute_api.swap_volume, self.context,
                          instance, volumes[uuids.old_volume],
                          volumes[uuids.new_volume])
        self.assertEqual('in-use', volumes[uuids.old_volume]['status'])
        self.assertEqual('available', volumes[uuids.new_volume]['status'])

    def test_swap_volume_with_invalid_server_state(self):
        # Should fail if VM state is not valid
        self._test_swap_volume_for_precheck_with_exception(
            exception.InstanceInvalidState,
            instance_update={'vm_state': vm_states.BUILDING})
        self._test_swap_volume_for_precheck_with_exception(
            exception.InstanceInvalidState,
            instance_update={'vm_state': vm_states.STOPPED})
        self._test_swap_volume_for_precheck_with_exception(
            exception.InstanceInvalidState,
            instance_update={'vm_state': vm_states.SUSPENDED})

    def test_swap_volume_with_another_server_volume(self):
        # Should fail if old volume's instance_uuid is not that of the instance
        self._test_swap_volume_for_precheck_with_exception(
            exception.InvalidVolume,
            volume_update={
                'target': uuids.old_volume,
                'value': {
                    'attachments': {
                        uuids.vol_instance_2: {'attachment_id': 'fakeid'}}}})

    def test_swap_volume_with_new_volume_attached(self):
        # Should fail if new volume is attached
        self._test_swap_volume_for_precheck_with_exception(
            exception.InvalidVolume,
            volume_update={'target': uuids.new_volume,
                           'value': {'attach_status': 'attached'}})

    def test_swap_volume_with_smaller_new_volume(self):
        # Should fail if new volume is smaller than the old volume
        self._test_swap_volume_for_precheck_with_exception(
            exception.InvalidVolume,
            volume_update={'target': uuids.new_volume,
                           'value': {'size': 4}})

    def test_swap_volume_with_swap_volume_error(self):
        self._test_swap_volume(expected_exception=AttributeError)

    def test_swap_volume_volume_api_usage(self):
        self._test_swap_volume()

    def test_swap_volume_volume_api_usage_new_attach_flow(self):
        self._test_swap_volume(attachment_id=uuids.attachment_id)

    def test_swap_volume_with_swap_volume_error_new_attach_flow(self):
        self._test_swap_volume(expected_exception=AttributeError,
                               attachment_id=uuids.attachment_id)

    def test_swap_volume_new_vol_already_attached_new_flow(self):
        self._test_swap_volume(attachment_id=uuids.attachment_id,
                               volume_already_attached=True)

    def _test_swap_volume(self, expected_exception=None, attachment_id=None,
                          volume_already_attached=False):
        volumes = self._get_volumes_for_test_swap_volume()
        instance = self._get_instance_for_test_swap_volume()

        def fake_vol_api_begin_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            volumes[volume_id]['status'] = 'detaching'

        def fake_vol_api_roll_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'detaching':
                volumes[volume_id]['status'] = 'in-use'

        def fake_vol_api_reserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            self.assertEqual('available', volumes[volume_id]['status'])
            volumes[volume_id]['status'] = 'attaching'

        def fake_vol_api_unreserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'attaching':
                volumes[volume_id]['status'] = 'available'

        def fake_vol_api_attachment_create(context, volume_id, instance_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            self.assertEqual('available', volumes[volume_id]['status'])
            volumes[volume_id]['status'] = 'reserved'
            return {'id': uuids.attachment_id}

        def fake_vol_api_attachment_delete(context, attachment_id):
            self.assertTrue(uuidutils.is_uuid_like(attachment_id))
            if volumes[uuids.new_volume]['status'] == 'reserved':
                volumes[uuids.new_volume]['status'] = 'available'

        def fake_volume_is_attached(context, instance, volume_id):
            if volume_already_attached:
                raise exception.InvalidVolume(reason='Volume already attached')
            else:
                pass

        @mock.patch.object(compute_api.API, '_record_action_start')
        @mock.patch.object(self.compute_api.compute_rpcapi, 'swap_volume',
                           return_value=True)
        @mock.patch.object(self.compute_api.volume_api, 'unreserve_volume',
                           side_effect=fake_vol_api_unreserve)
        @mock.patch.object(self.compute_api.volume_api, 'attachment_delete',
                           side_effect=fake_vol_api_attachment_delete)
        @mock.patch.object(self.compute_api.volume_api, 'reserve_volume',
                           side_effect=fake_vol_api_reserve)
        @mock.patch.object(self.compute_api,
                           '_check_volume_already_attached_to_instance',
                           side_effect=fake_volume_is_attached)
        @mock.patch.object(self.compute_api.volume_api, 'attachment_create',
                           side_effect=fake_vol_api_attachment_create)
        @mock.patch.object(self.compute_api.volume_api, 'roll_detaching',
                           side_effect=fake_vol_api_roll_detaching)
        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance')
        @mock.patch.object(self.compute_api.volume_api, 'begin_detaching',
                           side_effect=fake_vol_api_begin_detaching)
        def _do_test(mock_begin_detaching, mock_get_by_volume_and_instance,
                     mock_roll_detaching, mock_attachment_create,
                     mock_check_volume_attached, mock_reserve_volume,
                     mock_attachment_delete, mock_unreserve_volume,
                     mock_swap_volume, mock_record):
            bdm = objects.BlockDeviceMapping(
                        **fake_block_device.FakeDbBlockDeviceDict(
                        {'no_device': False, 'volume_id': '1', 'boot_index': 0,
                         'connection_info': 'inf', 'device_name': '/dev/vda',
                         'source_type': 'volume', 'destination_type': 'volume',
                         'tag': None, 'attachment_id': attachment_id},
                        anon=True))
            mock_get_by_volume_and_instance.return_value = bdm
            if expected_exception:
                mock_swap_volume.side_effect = AttributeError()
                self.assertRaises(expected_exception,
                                  self.compute_api.swap_volume, self.context,
                                  instance, volumes[uuids.old_volume],
                                  volumes[uuids.new_volume])
                self.assertEqual('in-use', volumes[uuids.old_volume]['status'])
                self.assertEqual('available',
                                 volumes[uuids.new_volume]['status'])
                # Make assertions about what was called if there was or was not
                # a Cinder 3.44 style attachment provided.
                if attachment_id is None:
                    # Old style attachment, so unreserve was called and
                    # attachment_delete was not called.
                    mock_unreserve_volume.assert_called_once_with(
                        self.context, uuids.new_volume)
                    mock_attachment_delete.assert_not_called()
                else:
                    # New style attachment, so unreserve was not called and
                    # attachment_delete was called.
                    mock_unreserve_volume.assert_not_called()
                    mock_attachment_delete.assert_called_once_with(
                        self.context, attachment_id)

                # Assert the call to the rpcapi.
                mock_swap_volume.assert_called_once_with(
                    self.context, instance=instance,
                    old_volume_id=uuids.old_volume,
                    new_volume_id=uuids.new_volume,
                    new_attachment_id=attachment_id)
                mock_record.assert_called_once_with(
                    self.context, instance, instance_actions.SWAP_VOLUME)
            elif volume_already_attached:
                self.assertRaises(exception.InvalidVolume,
                                  self.compute_api.swap_volume, self.context,
                                  instance, volumes[uuids.old_volume],
                                  volumes[uuids.new_volume])
                self.assertEqual('in-use', volumes[uuids.old_volume]['status'])
                self.assertEqual('available',
                                 volumes[uuids.new_volume]['status'])
                mock_check_volume_attached.assert_called_once_with(
                    self.context, instance, uuids.new_volume)
                mock_roll_detaching.assert_called_once_with(self.context,
                                                            uuids.old_volume)
            else:
                self.compute_api.swap_volume(self.context, instance,
                                             volumes[uuids.old_volume],
                                             volumes[uuids.new_volume])
                # Make assertions about what was called if there was or was not
                # a Cinder 3.44 style attachment provided.
                if attachment_id is None:
                    # Old style attachment, so reserve was called and
                    # attachment_create was not called.
                    mock_reserve_volume.assert_called_once_with(
                        self.context, uuids.new_volume)
                    mock_attachment_create.assert_not_called()
                    mock_check_volume_attached.assert_not_called()
                else:
                    # New style attachment, so reserve was not called and
                    # attachment_create was called.
                    mock_reserve_volume.assert_not_called()
                    mock_check_volume_attached.assert_called_once_with(
                        self.context, instance, uuids.new_volume)
                    mock_attachment_create.assert_called_once_with(
                        self.context, uuids.new_volume, instance.uuid)

                # Assert the call to the rpcapi.
                mock_swap_volume.assert_called_once_with(
                    self.context, instance=instance,
                    old_volume_id=uuids.old_volume,
                    new_volume_id=uuids.new_volume,
                    new_attachment_id=attachment_id)
                mock_record.assert_called_once_with(
                     self.context, instance, instance_actions.SWAP_VOLUME)

        _do_test()

    @mock.patch.object(compute_api.API, '_record_action_start')
    def _test_snapshot_and_backup(self, mock_record, is_snapshot=True,
                                  with_base_ref=False, min_ram=None,
                                  min_disk=None,
                                  create_fails=False,
                                  instance_vm_state=vm_states.ACTIVE):
        params = dict(locked=True)
        instance = self._create_instance_obj(params=params)
        instance.vm_state = instance_vm_state

        # Test non-inheritable properties, 'user_id' should also not be
        # carried from sys_meta into image property...since it should be set
        # explicitly by _create_image() in compute api.
        fake_image_meta = {
            'is_public': True,
            'name': 'base-name',
            'disk_format': 'fake',
            'container_format': 'fake',
            'properties': {
                'user_id': 'meow',
                'foo': 'bar',
                'blah': 'bug?',
                'cache_in_nova': 'dropped',
                'bittorrent': 'dropped',
                'img_signature_hash_method': 'dropped',
                'img_signature': 'dropped',
                'img_signature_key_type': 'dropped',
                'img_signature_certificate_uuid': 'dropped'
            },
        }
        image_type = is_snapshot and 'snapshot' or 'backup'
        sent_meta = {
            'is_public': False,
            'name': 'fake-name',
            'disk_format': 'fake',
            'container_format': 'fake',
            'properties': {
                'user_id': self.context.user_id,
                'instance_uuid': instance.uuid,
                'image_type': image_type,
                'foo': 'bar',
                'blah': 'bug?',
                'cow': 'moo',
                'cat': 'meow',
            },

        }
        if is_snapshot:
            if min_ram is not None:
                fake_image_meta['min_ram'] = min_ram
                sent_meta['min_ram'] = min_ram
            if min_disk is not None:
                fake_image_meta['min_disk'] = min_disk
                sent_meta['min_disk'] = min_disk
            sent_meta.pop('disk_format', None)
            sent_meta.pop('container_format', None)
        else:
            sent_meta['properties']['backup_type'] = 'fake-backup-type'

        extra_props = dict(cow='moo', cat='meow')

        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(self.compute_api.image_api,
                                 'create')
        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'snapshot_instance')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'backup_instance')

        if not is_snapshot:
            self.mox.StubOutWithMock(compute_utils,
                'is_volume_backed_instance')

            compute_utils.is_volume_backed_instance(self.context,
                instance).AndReturn(False)

        utils.get_image_from_system_metadata(
            instance.system_metadata).AndReturn(fake_image_meta)

        fake_image = dict(id='fake-image-id')
        mock_method = self.compute_api.image_api.create(
                self.context, sent_meta)
        if create_fails:
            mock_method.AndRaise(test.TestingException())
        else:
            mock_method.AndReturn(fake_image)

        def check_state(expected_task_state=None):
            expected_state = (is_snapshot and
                              task_states.IMAGE_SNAPSHOT_PENDING or
                              task_states.IMAGE_BACKUP)
            self.assertEqual(expected_state, instance.task_state)

        if not create_fails:
            instance.save(expected_task_state=[None]).WithSideEffects(
                    check_state)
            if is_snapshot:
                self.compute_api.compute_rpcapi.snapshot_instance(
                        self.context, instance, fake_image['id'])
            else:
                self.compute_api.compute_rpcapi.backup_instance(
                        self.context, instance, fake_image['id'],
                        'fake-backup-type', 'fake-rotation')

        self.mox.ReplayAll()

        got_exc = False
        try:
            if is_snapshot:
                res = self.compute_api.snapshot(self.context, instance,
                                          'fake-name',
                                          extra_properties=extra_props)
                mock_record.assert_called_once_with(
                    self.context, instance, instance_actions.CREATE_IMAGE)
            else:
                res = self.compute_api.backup(self.context, instance,
                                        'fake-name',
                                        'fake-backup-type',
                                        'fake-rotation',
                                        extra_properties=extra_props)
                mock_record.assert_called_once_with(self.context,
                                                    instance,
                                                    instance_actions.BACKUP)
            self.assertEqual(fake_image, res)
        except test.TestingException:
            got_exc = True
        self.assertEqual(create_fails, got_exc)
        self.mox.UnsetStubs()

    def test_snapshot(self):
        self._test_snapshot_and_backup()

    def test_snapshot_fails(self):
        self._test_snapshot_and_backup(create_fails=True)

    def test_snapshot_invalid_state(self):
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
                          self.context, instance, 'fake-name')
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_BACKUP
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
                          self.context, instance, 'fake-name')
        instance.vm_state = vm_states.BUILDING
        instance.task_state = None
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
                          self.context, instance, 'fake-name')

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_create_image')
    @mock.patch.object(compute_rpcapi.ComputeAPI,
                       'snapshot_instance')
    def test_vm_deleting_while_creating_snapshot(self,
                                                snapshot_instance,
                                                _create_image, save):
        instance = self._create_instance_obj()
        save.side_effect = exception.UnexpectedDeletingTaskStateError(
            "Exception")
        _create_image.return_value = dict(id='fake-image-id')
        with mock.patch.object(self.compute_api.image_api,
                               'delete') as image_delete:
            self.assertRaises(exception.InstanceInvalidState,
                              self.compute_api.snapshot,
                              self.context,
                              instance, 'fake-image')
            image_delete.assert_called_once_with(self.context,
                                                 'fake-image-id')

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_create_image')
    @mock.patch.object(compute_rpcapi.ComputeAPI,
                       'snapshot_instance')
    def test_vm_deleted_while_creating_snapshot(self,
                                                snapshot_instance,
                                                _create_image, save):
        instance = self._create_instance_obj()
        save.side_effect = exception.InstanceNotFound(
            "Exception")
        _create_image.return_value = dict(id='fake-image-id')
        with mock.patch.object(self.compute_api.image_api,
                               'delete') as image_delete:
            self.assertRaises(exception.InstanceInvalidState,
                              self.compute_api.snapshot,
                              self.context,
                              instance, 'fake-image')
            image_delete.assert_called_once_with(self.context,
                                                 'fake-image-id')

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_create_image')
    @mock.patch.object(compute_rpcapi.ComputeAPI,
                       'snapshot_instance')
    def test_vm_deleted_while_snapshot_and_snapshot_delete_failed(self,
                                                        snapshot_instance,
                                                        _create_image, save):
        instance = self._create_instance_obj()
        save.side_effect = exception.InstanceNotFound(instance_id='fake')
        _create_image.return_value = dict(id='fake-image-id')
        with mock.patch.object(self.compute_api.image_api,
                               'delete') as image_delete:
            image_delete.side_effect = test.TestingException()
            self.assertRaises(exception.InstanceInvalidState,
                              self.compute_api.snapshot,
                              self.context,
                              instance, 'fake-image')
            image_delete.assert_called_once_with(self.context,
                                                 'fake-image-id')

    def test_snapshot_with_base_image_ref(self):
        self._test_snapshot_and_backup(with_base_ref=True)

    def test_snapshot_min_ram(self):
        self._test_snapshot_and_backup(min_ram=42)

    def test_snapshot_min_disk(self):
        self._test_snapshot_and_backup(min_disk=42)

    def test_backup(self):
        for state in [vm_states.ACTIVE, vm_states.STOPPED,
                      vm_states.PAUSED, vm_states.SUSPENDED]:
            self._test_snapshot_and_backup(is_snapshot=False,
                                           instance_vm_state=state)

    def test_backup_fails(self):
        self._test_snapshot_and_backup(is_snapshot=False, create_fails=True)

    def test_backup_invalid_state(self):
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.backup,
                          self.context, instance, 'fake-name',
                          'fake', 'fake')
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_BACKUP
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.backup,
                          self.context, instance, 'fake-name',
                          'fake', 'fake')
        instance.vm_state = vm_states.BUILDING
        instance.task_state = None
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.backup,
                          self.context, instance, 'fake-name',
                          'fake', 'fake')

    def test_backup_with_base_image_ref(self):
        self._test_snapshot_and_backup(is_snapshot=False,
                                       with_base_ref=True)

    def test_backup_volume_backed_instance(self):
        instance = self._create_instance_obj()

        with mock.patch.object(compute_utils, 'is_volume_backed_instance',
                               return_value=True) as mock_is_volume_backed:
            self.assertRaises(exception.InvalidRequest,
                              self.compute_api.backup, self.context,
                              instance, 'fake-name', 'weekly',
                              3, extra_properties={})
            mock_is_volume_backed.assert_called_once_with(self.context,
                                                          instance)

    def _test_snapshot_volume_backed(self, quiesce_required, quiesce_fails,
                                     vm_state=vm_states.ACTIVE):
        fake_sys_meta = {'image_min_ram': '11',
                         'image_min_disk': '22',
                         'image_container_format': 'ami',
                         'image_disk_format': 'ami',
                         'image_ram_disk': 'fake_ram_disk_id',
                         'image_bdm_v2': 'True',
                         'image_block_device_mapping': '[]',
                         'image_mappings': '[]',
                         'image_cache_in_nova': 'True'}
        if quiesce_required:
            fake_sys_meta['image_os_require_quiesce'] = 'yes'
        params = dict(locked=True, vm_state=vm_state,
                      system_metadata=fake_sys_meta)
        instance = self._create_instance_obj(params=params)
        instance['root_device_name'] = 'vda'

        instance_bdms = []

        expect_meta = {
            'name': 'test-snapshot',
            'properties': {'root_device_name': 'vda',
                           'ram_disk': 'fake_ram_disk_id'},
            'size': 0,
            'min_disk': '22',
            'is_public': False,
            'min_ram': '11',
        }
        if quiesce_required:
            expect_meta['properties']['os_require_quiesce'] = 'yes'

        quiesced = [False, False]
        quiesce_expected = not quiesce_fails and vm_state == vm_states.ACTIVE

        @classmethod
        def fake_bdm_list_get_by_instance_uuid(cls, context, instance_uuid):
            return obj_base.obj_make_list(context, cls(),
                    objects.BlockDeviceMapping, instance_bdms)

        def fake_image_create(context, image_meta, data=None):
            self.assertThat(image_meta, matchers.DictMatches(expect_meta))

        def fake_volume_get(context, volume_id):
            return {'id': volume_id, 'display_description': ''}

        def fake_volume_create_snapshot(context, volume_id, name, description):
            return {'id': '%s-snapshot' % volume_id}

        def fake_quiesce_instance(context, instance):
            if quiesce_fails:
                raise exception.InstanceQuiesceNotSupported(
                    instance_id=instance['uuid'], reason='test')
            quiesced[0] = True

        def fake_unquiesce_instance(context, instance, mapping=None):
            quiesced[1] = True

        self.stub_out('nova.objects.BlockDeviceMappingList'
                      '.get_by_instance_uuid',
                      fake_bdm_list_get_by_instance_uuid)
        self.stubs.Set(self.compute_api.image_api, 'create',
                       fake_image_create)
        self.stubs.Set(self.compute_api.volume_api, 'get',
                       fake_volume_get)
        self.stubs.Set(self.compute_api.volume_api, 'create_snapshot_force',
                       fake_volume_create_snapshot)
        self.stubs.Set(self.compute_api.compute_rpcapi, 'quiesce_instance',
                       fake_quiesce_instance)
        self.stubs.Set(self.compute_api.compute_rpcapi, 'unquiesce_instance',
                       fake_unquiesce_instance)
        fake_image.stub_out_image_service(self)

        with test.nested(
                mock.patch.object(compute_api.API, '_record_action_start'),
                mock.patch.object(compute_utils, 'EventReporter')) as (
            mock_record, mock_event):
            # No block devices defined
            self.compute_api.snapshot_volume_backed(
                self.context, instance, 'test-snapshot')

        mock_record.assert_called_once_with(self.context,
                                            instance,
                                            instance_actions.CREATE_IMAGE)
        mock_event.assert_called_once_with(self.context,
                                           'api_snapshot_instance',
                                           instance.uuid)

        bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'no_device': False, 'volume_id': '1', 'boot_index': 0,
                 'connection_info': 'inf', 'device_name': '/dev/vda',
                 'source_type': 'volume', 'destination_type': 'volume',
                 'tag': None})
        instance_bdms.append(bdm)

        expect_meta['properties']['bdm_v2'] = True
        expect_meta['properties']['block_device_mapping'] = []
        expect_meta['properties']['block_device_mapping'].append(
            {'guest_format': None, 'boot_index': 0, 'no_device': None,
             'image_id': None, 'volume_id': None, 'disk_bus': None,
             'volume_size': None, 'source_type': 'snapshot',
             'device_type': None, 'snapshot_id': '1-snapshot',
             'device_name': '/dev/vda',
             'destination_type': 'volume', 'delete_on_termination': False,
             'tag': None})

        with test.nested(
                mock.patch.object(compute_api.API, '_record_action_start'),
                mock.patch.object(compute_utils, 'EventReporter')) as (
                mock_record, mock_event):
            # All the db_only fields and the volume ones are removed
            self.compute_api.snapshot_volume_backed(
                self.context, instance, 'test-snapshot')

        self.assertEqual(quiesce_expected, quiesced[0])
        self.assertEqual(quiesce_expected, quiesced[1])

        mock_record.assert_called_once_with(self.context,
                                            instance,
                                            instance_actions.CREATE_IMAGE)
        mock_event.assert_called_once_with(self.context,
                                           'api_snapshot_instance',
                                           instance.uuid)

        instance.system_metadata['image_mappings'] = jsonutils.dumps(
            [{'virtual': 'ami', 'device': 'vda'},
             {'device': 'vda', 'virtual': 'ephemeral0'},
             {'device': 'vdb', 'virtual': 'swap'},
             {'device': 'vdc', 'virtual': 'ephemeral1'}])[:255]
        instance.system_metadata['image_block_device_mapping'] = (
            jsonutils.dumps(
                [{'source_type': 'snapshot', 'destination_type': 'volume',
                  'guest_format': None, 'device_type': 'disk', 'boot_index': 1,
                  'disk_bus': 'ide', 'device_name': '/dev/vdf',
                  'delete_on_termination': True, 'snapshot_id': 'snapshot-2',
                  'volume_id': None, 'volume_size': 100, 'image_id': None,
                  'no_device': None}])[:255])

        bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'no_device': False, 'volume_id': None, 'boot_index': -1,
                 'connection_info': 'inf', 'device_name': '/dev/vdh',
                 'source_type': 'blank', 'destination_type': 'local',
                 'guest_format': 'swap', 'delete_on_termination': True,
                 'tag': None})
        instance_bdms.append(bdm)
        expect_meta['properties']['block_device_mapping'].append(
            {'guest_format': 'swap', 'boot_index': -1, 'no_device': False,
             'image_id': None, 'volume_id': None, 'disk_bus': None,
             'volume_size': None, 'source_type': 'blank',
             'device_type': None, 'snapshot_id': None,
             'device_name': '/dev/vdh',
             'destination_type': 'local', 'delete_on_termination': True,
             'tag': None})

        quiesced = [False, False]

        with test.nested(
                mock.patch.object(compute_api.API, '_record_action_start'),
                mock.patch.object(compute_utils, 'EventReporter')) as (
                mock_record, mock_event):
            # Check that the mappings from the image properties are not
            # included
            self.compute_api.snapshot_volume_backed(
                self.context, instance, 'test-snapshot')

        self.assertEqual(quiesce_expected, quiesced[0])
        self.assertEqual(quiesce_expected, quiesced[1])

        mock_record.assert_called_once_with(self.context,
                                            instance,
                                            instance_actions.CREATE_IMAGE)
        mock_event.assert_called_once_with(self.context,
                                           'api_snapshot_instance',
                                           instance.uuid)

    def test_snapshot_volume_backed(self):
        self._test_snapshot_volume_backed(False, False)

    def test_snapshot_volume_backed_with_quiesce(self):
        self._test_snapshot_volume_backed(True, False)

    def test_snapshot_volume_backed_with_quiesce_skipped(self):
        self._test_snapshot_volume_backed(False, True)

    def test_snapshot_volume_backed_with_quiesce_exception(self):
        self.assertRaises(exception.NovaException,
                          self._test_snapshot_volume_backed, True, True)

    def test_snapshot_volume_backed_with_quiesce_stopped(self):
        self._test_snapshot_volume_backed(True, True,
                                          vm_state=vm_states.STOPPED)

    def test_snapshot_volume_backed_with_quiesce_suspended(self):
        self._test_snapshot_volume_backed(True, True,
                                          vm_state=vm_states.SUSPENDED)

    def test_snapshot_volume_backed_with_suspended(self):
        self._test_snapshot_volume_backed(False, True,
                                          vm_state=vm_states.SUSPENDED)

    @mock.patch.object(context, 'set_target_cell')
    @mock.patch.object(objects.BlockDeviceMapping, 'get_by_volume')
    def test_get_bdm_by_volume_id(self, mock_get_by_volume,
                                  mock_target_cell):
        fake_cells = [mock.sentinel.cell0, mock.sentinel.cell1]

        mock_get_by_volume.side_effect = [
            exception.VolumeBDMNotFound(volume_id=mock.sentinel.volume_id),
            mock.sentinel.bdm]

        with mock.patch.object(compute_api, 'CELLS', fake_cells):
            bdm = self.compute_api._get_bdm_by_volume_id(
                self.context, mock.sentinel.volume_id,
                mock.sentinel.expected_attrs)

        self.assertEqual(mock.sentinel.bdm, bdm)

        mock_target_cell.assert_has_calls([
            mock.call(self.context, cell) for cell in fake_cells])
        mock_get_by_volume.assert_has_calls(
            [mock.call(self.context,
                       mock.sentinel.volume_id,
                       expected_attrs=mock.sentinel.expected_attrs)] * 2)

    @mock.patch.object(context, 'set_target_cell')
    @mock.patch.object(objects.BlockDeviceMapping, 'get_by_volume')
    def test_get_missing_bdm_by_volume_id(self, mock_get_by_volume,
                                          mock_target_cell):
        fake_cells = [mock.sentinel.cell0, mock.sentinel.cell1]

        mock_get_by_volume.side_effect = exception.VolumeBDMNotFound(
            volume_id=mock.sentinel.volume_id)

        with mock.patch.object(compute_api, 'CELLS', fake_cells):
            self.assertRaises(
                exception.VolumeBDMNotFound,
                self.compute_api._get_bdm_by_volume_id,
                self.context, mock.sentinel.volume_id,
                mock.sentinel.expected_attrs)

    def test_volume_snapshot_create(self):
        volume_id = '1'
        create_info = {'id': 'eyedee'}
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
                    'id': 123,
                    'device_name': '/dev/sda2',
                    'source_type': 'volume',
                    'destination_type': 'volume',
                    'connection_info': "{'fake': 'connection_info'}",
                    'volume_id': 1,
                    'boot_index': -1})
        fake_bdm['instance'] = fake_instance.fake_db_instance(
            launched_at=timeutils.utcnow(),
            vm_state=vm_states.ACTIVE)
        fake_bdm['instance_uuid'] = fake_bdm['instance']['uuid']
        fake_bdm = objects.BlockDeviceMapping._from_db_object(
                self.context, objects.BlockDeviceMapping(),
                fake_bdm, expected_attrs=['instance'])

        self.mox.StubOutWithMock(self.compute_api,
                                 '_get_bdm_by_volume_id')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                'volume_snapshot_create')

        self.compute_api._get_bdm_by_volume_id(
                self.context, volume_id,
                expected_attrs=['instance']).AndReturn(fake_bdm)
        self.compute_api.compute_rpcapi.volume_snapshot_create(self.context,
                fake_bdm['instance'], volume_id, create_info)

        self.mox.ReplayAll()

        snapshot = self.compute_api.volume_snapshot_create(self.context,
                volume_id, create_info)

        expected_snapshot = {
            'snapshot': {
                'id': create_info['id'],
                'volumeId': volume_id,
            },
        }
        self.assertEqual(snapshot, expected_snapshot)

    @mock.patch.object(
        objects.BlockDeviceMapping, 'get_by_volume',
        return_value=objects.BlockDeviceMapping(
            instance=objects.Instance(
                launched_at=timeutils.utcnow(), uuid=uuids.instance_uuid,
                vm_state=vm_states.ACTIVE, task_state=task_states.SHELVING,
                host='fake_host')))
    def test_volume_snapshot_create_shelving(self, bdm_get_by_volume):
        """Tests a negative scenario where the instance task_state is not
        accepted for creating a guest-assisted volume snapshot.
        """
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.volume_snapshot_create,
                          self.context, mock.sentinel.volume_id,
                          mock.sentinel.create_info)

    @mock.patch.object(
        objects.BlockDeviceMapping, 'get_by_volume',
        return_value=objects.BlockDeviceMapping(
            instance=objects.Instance(
                launched_at=timeutils.utcnow(), uuid=uuids.instance_uuid,
                vm_state=vm_states.SHELVED_OFFLOADED, task_state=None,
                host=None)))
    def test_volume_snapshot_create_shelved_offloaded(self, bdm_get_by_volume):
        """Tests a negative scenario where the instance is shelved offloaded
        so we don't have a host to cast to for the guest-assisted snapshot.
        """
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.volume_snapshot_create,
                          self.context, mock.sentinel.volume_id,
                          mock.sentinel.create_info)

    def test_volume_snapshot_delete(self):
        volume_id = '1'
        snapshot_id = '2'
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
                    'id': 123,
                    'device_name': '/dev/sda2',
                    'source_type': 'volume',
                    'destination_type': 'volume',
                    'connection_info': "{'fake': 'connection_info'}",
                    'volume_id': 1,
                    'boot_index': -1})
        fake_bdm['instance'] = fake_instance.fake_db_instance(
            launched_at=timeutils.utcnow(),
            vm_state=vm_states.STOPPED)
        fake_bdm['instance_uuid'] = fake_bdm['instance']['uuid']
        fake_bdm = objects.BlockDeviceMapping._from_db_object(
                self.context, objects.BlockDeviceMapping(),
                fake_bdm, expected_attrs=['instance'])

        self.mox.StubOutWithMock(self.compute_api,
                                 '_get_bdm_by_volume_id')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                'volume_snapshot_delete')

        self.compute_api._get_bdm_by_volume_id(
                self.context, volume_id,
                expected_attrs=['instance']).AndReturn(fake_bdm)
        self.compute_api.compute_rpcapi.volume_snapshot_delete(self.context,
                fake_bdm['instance'], volume_id, snapshot_id, {})

        self.mox.ReplayAll()

        self.compute_api.volume_snapshot_delete(self.context, volume_id,
                snapshot_id, {})

    @mock.patch.object(
        objects.BlockDeviceMapping, 'get_by_volume',
        return_value=objects.BlockDeviceMapping(
            instance=objects.Instance(
                launched_at=timeutils.utcnow(), uuid=uuids.instance_uuid,
                vm_state=vm_states.ACTIVE, task_state=task_states.SHELVING,
                host='fake_host')))
    def test_volume_snapshot_delete_shelving(self, bdm_get_by_volume):
        """Tests a negative scenario where the instance is shelving and the
        task_state is set so we can't perform the guest-assisted snapshot.
        """
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.volume_snapshot_delete,
                          self.context, mock.sentinel.volume_id,
                          mock.sentinel.snapshot_id, mock.sentinel.delete_info)

    @mock.patch.object(
        objects.BlockDeviceMapping, 'get_by_volume',
        return_value=objects.BlockDeviceMapping(
            instance=objects.Instance(
                launched_at=timeutils.utcnow(), uuid=uuids.instance_uuid,
                vm_state=vm_states.SHELVED_OFFLOADED, task_state=None,
                host=None)))
    def test_volume_snapshot_delete_shelved_offloaded(self, bdm_get_by_volume):
        """Tests a negative scenario where the instance is shelved offloaded
        so there is no host to cast to for the guest-assisted snapshot delete.
        """
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.volume_snapshot_delete,
                          self.context, mock.sentinel.volume_id,
                          mock.sentinel.snapshot_id, mock.sentinel.delete_info)

    def _test_boot_volume_bootable(self, is_bootable=False):
        def get_vol_data(*args, **kwargs):
            return {'bootable': is_bootable}
        block_device_mapping = [{
            'id': 1,
            'device_name': 'vda',
            'no_device': None,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': '1',
            'delete_on_termination': False,
        }]

        expected_meta = {'min_disk': 0, 'min_ram': 0, 'properties': {},
                         'size': 0, 'status': 'active'}

        with mock.patch.object(self.compute_api.volume_api, 'get',
                               side_effect=get_vol_data):
            if not is_bootable:
                self.assertRaises(exception.InvalidBDMVolumeNotBootable,
                                  self.compute_api._get_bdm_image_metadata,
                                  self.context, block_device_mapping)
            else:
                meta = self.compute_api._get_bdm_image_metadata(self.context,
                                    block_device_mapping)
                self.assertEqual(expected_meta, meta)

    def test_boot_volume_non_bootable(self):
        self._test_boot_volume_bootable(False)

    def test_boot_volume_bootable(self):
        self._test_boot_volume_bootable(True)

    def test_boot_volume_basic_property(self):
        block_device_mapping = [{
            'id': 1,
            'device_name': 'vda',
            'no_device': None,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': '1',
            'delete_on_termination': False,
        }]
        fake_volume = {"volume_image_metadata":
                       {"min_ram": 256, "min_disk": 128, "foo": "bar"}}
        with mock.patch.object(self.compute_api.volume_api, 'get',
                               return_value=fake_volume):
            meta = self.compute_api._get_bdm_image_metadata(
                self.context, block_device_mapping)
            self.assertEqual(256, meta['min_ram'])
            self.assertEqual(128, meta['min_disk'])
            self.assertEqual('active', meta['status'])
            self.assertEqual('bar', meta['properties']['foo'])

    def test_boot_volume_snapshot_basic_property(self):
        block_device_mapping = [{
            'id': 1,
            'device_name': 'vda',
            'no_device': None,
            'virtual_name': None,
            'snapshot_id': '2',
            'volume_id': None,
            'delete_on_termination': False,
        }]
        fake_volume = {"volume_image_metadata":
                       {"min_ram": 256, "min_disk": 128, "foo": "bar"}}
        fake_snapshot = {"volume_id": "1"}
        with test.nested(
                mock.patch.object(self.compute_api.volume_api, 'get',
                    return_value=fake_volume),
                mock.patch.object(self.compute_api.volume_api, 'get_snapshot',
                    return_value=fake_snapshot)) as (
                            volume_get, volume_get_snapshot):
            meta = self.compute_api._get_bdm_image_metadata(
                self.context, block_device_mapping)
            self.assertEqual(256, meta['min_ram'])
            self.assertEqual(128, meta['min_disk'])
            self.assertEqual('active', meta['status'])
            self.assertEqual('bar', meta['properties']['foo'])
            volume_get_snapshot.assert_called_once_with(self.context,
                    block_device_mapping[0]['snapshot_id'])
            volume_get.assert_called_once_with(self.context,
                    fake_snapshot['volume_id'])

    def _create_instance_with_disabled_disk_config(self, object=False):
        sys_meta = {"image_auto_disk_config": "Disabled"}
        params = {"system_metadata": sys_meta}
        instance = self._create_instance_obj(params=params)
        if object:
            return instance
        return obj_base.obj_to_primitive(instance)

    def _setup_fake_image_with_disabled_disk_config(self):
        self.fake_image = {
            'id': 1,
            'name': 'fake_name',
            'status': 'active',
            'properties': {"auto_disk_config": "Disabled"},
        }

        def fake_show(obj, context, image_id, **kwargs):
            return self.fake_image
        fake_image.stub_out_image_service(self)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        return self.fake_image['id']

    def test_resize_with_disabled_auto_disk_config_fails(self):
        fake_inst = self._create_instance_with_disabled_disk_config(
            object=True)

        self.assertRaises(exception.AutoDiskConfigDisabledByImage,
                          self.compute_api.resize,
                          self.context, fake_inst,
                          auto_disk_config=True)

    def test_create_with_disabled_auto_disk_config_fails(self):
        image_id = self._setup_fake_image_with_disabled_disk_config()

        self.assertRaises(exception.AutoDiskConfigDisabledByImage,
            self.compute_api.create, self.context,
            "fake_flavor", image_id, auto_disk_config=True)

    def test_rebuild_with_disabled_auto_disk_config_fails(self):
        fake_inst = self._create_instance_with_disabled_disk_config(
            object=True)
        image_id = self._setup_fake_image_with_disabled_disk_config()
        self.assertRaises(exception.AutoDiskConfigDisabledByImage,
                          self.compute_api.rebuild,
                          self.context,
                          fake_inst,
                          image_id,
                          "new password",
                          auto_disk_config=True)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild(self, _record_action_start,
            _checks_for_create_and_rebuild, _check_auto_disk_config,
            _get_image, bdm_get_by_instance_uuid, get_flavor, instance_save,
            req_spec_get_by_inst_uuid):
        orig_system_metadata = {}
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                image_ref='foo',
                expected_attrs=['system_metadata'])
        get_flavor.return_value = test_flavor.fake_flavor
        flavor = instance.get_flavor()
        image_href = 'foo'
        image = {
            "min_ram": 10, "min_disk": 1,
            "properties": {
                'architecture': fields_obj.Architecture.X86_64}}
        admin_pass = ''
        files_to_inject = []
        bdms = objects.BlockDeviceMappingList()

        _get_image.return_value = (None, image)
        bdm_get_by_instance_uuid.return_value = bdms

        fake_spec = objects.RequestSpec()
        req_spec_get_by_inst_uuid.return_value = fake_spec

        with mock.patch.object(self.compute_api.compute_task_api,
                'rebuild_instance') as rebuild_instance:
            self.compute_api.rebuild(self.context, instance, image_href,
                    admin_pass, files_to_inject)

            rebuild_instance.assert_called_once_with(self.context,
                    instance=instance, new_pass=admin_pass,
                    injected_files=files_to_inject, image_ref=image_href,
                    orig_image_ref=image_href,
                    orig_sys_metadata=orig_system_metadata, bdms=bdms,
                    preserve_ephemeral=False, host=instance.host,
                    request_spec=fake_spec, kwargs={})

        _check_auto_disk_config.assert_called_once_with(image=image)
        _checks_for_create_and_rebuild.assert_called_once_with(self.context,
                None, image, flavor, {}, [], None)
        self.assertNotEqual(orig_system_metadata, instance.system_metadata)
        bdm_get_by_instance_uuid.assert_called_once_with(
            self.context, instance.uuid)

    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_change_image(self, _record_action_start,
            _checks_for_create_and_rebuild, _check_auto_disk_config,
            _get_image, bdm_get_by_instance_uuid, get_flavor, instance_save,
            req_spec_get_by_inst_uuid, req_spec_save):
        orig_system_metadata = {}
        get_flavor.return_value = test_flavor.fake_flavor
        orig_image_href = 'orig_image'
        orig_image = {
            "min_ram": 10, "min_disk": 1,
            "properties": {'architecture': fields_obj.Architecture.X86_64,
                           'vm_mode': 'hvm'}}
        new_image_href = 'new_image'
        new_image = {
            "min_ram": 10, "min_disk": 1,
             "properties": {'architecture': fields_obj.Architecture.X86_64,
                           'vm_mode': 'xen'}}
        admin_pass = ''
        files_to_inject = []
        bdms = objects.BlockDeviceMappingList()

        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                expected_attrs=['system_metadata'],
                image_ref=orig_image_href,
                node='node',
                vm_mode=fields_obj.VMMode.HVM)
        flavor = instance.get_flavor()

        def get_image(context, image_href):
            if image_href == new_image_href:
                return (None, new_image)
            if image_href == orig_image_href:
                return (None, orig_image)
        _get_image.side_effect = get_image
        bdm_get_by_instance_uuid.return_value = bdms

        fake_spec = objects.RequestSpec(id=1)
        req_spec_get_by_inst_uuid.return_value = fake_spec

        with mock.patch.object(self.compute_api.compute_task_api,
                'rebuild_instance') as rebuild_instance:
            self.compute_api.rebuild(self.context, instance, new_image_href,
                    admin_pass, files_to_inject)

            rebuild_instance.assert_called_once_with(self.context,
                    instance=instance, new_pass=admin_pass,
                    injected_files=files_to_inject, image_ref=new_image_href,
                    orig_image_ref=orig_image_href,
                    orig_sys_metadata=orig_system_metadata, bdms=bdms,
                    preserve_ephemeral=False, host=None,
                    request_spec=fake_spec, kwargs={})
            # assert the request spec was modified so the scheduler picks
            # the existing instance host/node
            req_spec_save.assert_called_once_with()
            self.assertIn('_nova_check_type', fake_spec.scheduler_hints)
            self.assertEqual('rebuild',
                             fake_spec.scheduler_hints['_nova_check_type'][0])

        _check_auto_disk_config.assert_called_once_with(image=new_image)
        _checks_for_create_and_rebuild.assert_called_once_with(self.context,
                None, new_image, flavor, {}, [], None)
        self.assertEqual(fields_obj.VMMode.XEN, instance.vm_mode)

    @mock.patch.object(objects.KeyPair, 'get_by_name')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_change_keypair(self, _record_action_start,
            _checks_for_create_and_rebuild, _check_auto_disk_config,
            _get_image, bdm_get_by_instance_uuid, get_flavor, instance_save,
            req_spec_get_by_inst_uuid, mock_get_keypair):
        orig_system_metadata = {}
        orig_key_name = 'orig_key_name'
        orig_key_data = 'orig_key_data_XXX'
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                image_ref='foo',
                expected_attrs=['system_metadata'],
                key_name=orig_key_name,
                key_data=orig_key_data)
        get_flavor.return_value = test_flavor.fake_flavor
        flavor = instance.get_flavor()
        image_href = 'foo'
        image = {
            "min_ram": 10, "min_disk": 1,
            "properties": {'architecture': fields_obj.Architecture.X86_64,
                           'vm_mode': 'hvm'}}
        admin_pass = ''
        files_to_inject = []
        bdms = objects.BlockDeviceMappingList()

        _get_image.return_value = (None, image)
        bdm_get_by_instance_uuid.return_value = bdms

        fake_spec = objects.RequestSpec()
        req_spec_get_by_inst_uuid.return_value = fake_spec

        keypair = self._create_keypair_obj(instance)
        mock_get_keypair.return_value = keypair
        with mock.patch.object(self.compute_api.compute_task_api,
                'rebuild_instance') as rebuild_instance:
            self.compute_api.rebuild(self.context, instance, image_href,
                    admin_pass, files_to_inject, key_name=keypair.name)

            rebuild_instance.assert_called_once_with(self.context,
                    instance=instance, new_pass=admin_pass,
                    injected_files=files_to_inject, image_ref=image_href,
                    orig_image_ref=image_href,
                    orig_sys_metadata=orig_system_metadata, bdms=bdms,
                    preserve_ephemeral=False, host=instance.host,
                    request_spec=fake_spec, kwargs={})

        _check_auto_disk_config.assert_called_once_with(image=image)
        _checks_for_create_and_rebuild.assert_called_once_with(self.context,
                None, image, flavor, {}, [], None)
        self.assertNotEqual(orig_key_name, instance.key_name)
        self.assertNotEqual(orig_key_data, instance.key_data)

    def _test_check_injected_file_quota_onset_file_limit_exceeded(self,
                                                                  side_effect):
        injected_files = [
            {
                "path": "/etc/banner.txt",
                "contents": "foo"
            }
        ]
        with mock.patch('nova.objects.Quotas.limit_check',
                        side_effect=side_effect):
            self.compute_api._check_injected_file_quota(
                self.context, injected_files)

    def test_check_injected_file_quota_onset_file_limit_exceeded(self):
        # This is the first call to limit_check.
        side_effect = exception.OverQuota(overs='injected_files')
        self.assertRaises(exception.OnsetFileLimitExceeded,
            self._test_check_injected_file_quota_onset_file_limit_exceeded,
            side_effect)

    def test_check_injected_file_quota_onset_file_path_limit(self):
        # This is the second call to limit_check.
        side_effect = (mock.DEFAULT,
                       exception.OverQuota(overs='injected_file_path_bytes',
                                    quotas={'injected_file_path_bytes': 255}))
        self.assertRaises(exception.OnsetFilePathLimitExceeded,
            self._test_check_injected_file_quota_onset_file_limit_exceeded,
            side_effect)

    def test_check_injected_file_quota_onset_file_content_limit(self):
        # This is the second call to limit_check but with different overs.
        side_effect = (mock.DEFAULT,
            exception.OverQuota(overs='injected_file_content_bytes',
                                quotas={'injected_file_content_bytes': 10240}))
        self.assertRaises(exception.OnsetFileContentLimitExceeded,
            self._test_check_injected_file_quota_onset_file_limit_exceeded,
            side_effect)

    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.InstanceAction.action_start')
    def test_restore_by_admin(self, action_start, instance_save,
                              quota_check, quota_count):
        admin_context = context.RequestContext('admin_user',
                                               'admin_project',
                                               True)
        proj_count = {'instances': 1, 'cores': 1, 'ram': 512}
        user_count = proj_count.copy()
        quota_count.return_value = {'project': proj_count, 'user': user_count}
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.SOFT_DELETED
        instance.task_state = None
        instance.save()
        with mock.patch.object(self.compute_api, 'compute_rpcapi') as rpc:
            self.compute_api.restore(admin_context, instance)
            rpc.restore_instance.assert_called_once_with(admin_context,
                                                         instance)
        self.assertEqual(instance.task_state, task_states.RESTORING)
        # mock.ANY might be 'instances', 'cores', or 'ram' depending on how the
        # deltas dict is iterated in check_deltas
        quota_count.assert_called_once_with(admin_context, mock.ANY,
                                            instance.project_id,
                                            user_id=instance.user_id)
        quota_check.assert_called_once_with(
            admin_context,
            user_values={'instances': 2,
                         'cores': 1 + instance.flavor.vcpus,
                         'ram': 512 + instance.flavor.memory_mb},
            project_values={'instances': 2,
                            'cores': 1 + instance.flavor.vcpus,
                            'ram': 512 + instance.flavor.memory_mb},
            project_id=instance.project_id, user_id=instance.user_id)

    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.InstanceAction.action_start')
    def test_restore_by_instance_owner(self, action_start, instance_save,
                                       quota_check, quota_count):
        proj_count = {'instances': 1, 'cores': 1, 'ram': 512}
        user_count = proj_count.copy()
        quota_count.return_value = {'project': proj_count, 'user': user_count}
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.SOFT_DELETED
        instance.task_state = None
        instance.save()
        with mock.patch.object(self.compute_api, 'compute_rpcapi') as rpc:
            self.compute_api.restore(self.context, instance)
            rpc.restore_instance.assert_called_once_with(self.context,
                                                         instance)
        self.assertEqual(instance.project_id, self.context.project_id)
        self.assertEqual(instance.task_state, task_states.RESTORING)
        # mock.ANY might be 'instances', 'cores', or 'ram' depending on how the
        # deltas dict is iterated in check_deltas
        quota_count.assert_called_once_with(self.context, mock.ANY,
                                            instance.project_id,
                                            user_id=instance.user_id)
        quota_check.assert_called_once_with(
            self.context,
            user_values={'instances': 2,
                         'cores': 1 + instance.flavor.vcpus,
                         'ram': 512 + instance.flavor.memory_mb},
            project_values={'instances': 2,
                            'cores': 1 + instance.flavor.vcpus,
                            'ram': 512 + instance.flavor.memory_mb},
            project_id=instance.project_id, user_id=instance.user_id)

    @mock.patch.object(objects.InstanceAction, 'action_start')
    def test_external_instance_event(self, mock_action_start):
        instances = [
            objects.Instance(uuid=uuids.instance_1, host='host1',
                             migration_context=None),
            objects.Instance(uuid=uuids.instance_2, host='host1',
                             migration_context=None),
            objects.Instance(uuid=uuids.instance_3, host='host2',
                             migration_context=None),
            objects.Instance(uuid=uuids.instance_4, host='host2',
                             migration_context=None),
            ]
        # Create a single cell context and associate it with all instances
        mapping = objects.InstanceMapping.get_by_instance_uuid(
                self.context, instances[0].uuid)
        with context.target_cell(self.context, mapping.cell_mapping) as cc:
            cell_context = cc
        for instance in instances:
                instance._context = cell_context

        volume_id = uuidutils.generate_uuid()
        events = [
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_1,
                name='network-changed'),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_2,
                name='network-changed'),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_3,
                name='network-changed'),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_4,
                name='volume-extended',
                tag=volume_id),
            ]
        self.compute_api.compute_rpcapi = mock.MagicMock()
        self.compute_api.external_instance_event(self.context,
                                                 instances, events)
        method = self.compute_api.compute_rpcapi.external_instance_event
        method.assert_any_call(cell_context, instances[0:2], events[0:2],
                               host='host1')
        method.assert_any_call(cell_context, instances[2:], events[2:],
                               host='host2')
        mock_action_start.assert_called_once_with(
            self.context, uuids.instance_4, instance_actions.EXTEND_VOLUME,
            want_result=False)
        self.assertEqual(2, method.call_count)

    def test_external_instance_event_evacuating_instance(self):
        # Since we're patching the db's migration_get(), use a dict here so
        # that we can validate the id is making its way correctly to the db api
        migrations = {}
        migrations[42] = {'id': 42, 'source_compute': 'host1',
                          'dest_compute': 'host2', 'source_node': None,
                          'dest_node': None, 'dest_host': None,
                          'old_instance_type_id': None,
                          'new_instance_type_id': None,
                          'uuid': uuids.migration,
                          'instance_uuid': uuids.instance_2, 'status': None,
                          'migration_type': 'evacuation', 'memory_total': None,
                          'memory_processed': None, 'memory_remaining': None,
                          'disk_total': None, 'disk_processed': None,
                          'disk_remaining': None, 'deleted': False,
                          'hidden': False, 'created_at': None,
                          'updated_at': None, 'deleted_at': None}

        def migration_get(context, id):
            return migrations[id]

        instances = [
            objects.Instance(uuid=uuids.instance_1, host='host1',
                             migration_context=None),
            objects.Instance(uuid=uuids.instance_2, host='host1',
                             migration_context=objects.MigrationContext(
                                 migration_id=42)),
            objects.Instance(uuid=uuids.instance_3, host='host2',
                             migration_context=None)
            ]

        # Create a single cell context and associate it with all instances
        mapping = objects.InstanceMapping.get_by_instance_uuid(
                self.context, instances[0].uuid)
        with context.target_cell(self.context, mapping.cell_mapping) as cc:
            cell_context = cc
        for instance in instances:
                instance._context = cell_context

        events = [
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_1,
                name='network-changed'),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_2,
                name='network-changed'),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_3,
                name='network-changed'),
            ]

        with mock.patch('nova.db.sqlalchemy.api.migration_get', migration_get):
            self.compute_api.compute_rpcapi = mock.MagicMock()
            self.compute_api.external_instance_event(self.context,
                                                     instances, events)
            method = self.compute_api.compute_rpcapi.external_instance_event
            method.assert_any_call(cell_context, instances[0:2], events[0:2],
                                   host='host1')
            method.assert_any_call(cell_context, instances[1:], events[1:],
                                   host='host2')
            self.assertEqual(2, method.call_count)

    def test_volume_ops_invalid_task_state(self):
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        instance.task_state = 'Any'
        volume_id = uuidutils.generate_uuid()
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.attach_volume,
                          self.context, instance, volume_id)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.detach_volume,
                          self.context, instance, volume_id)

        new_volume_id = uuidutils.generate_uuid()
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.swap_volume,
                          self.context, instance,
                          volume_id, new_volume_id)

    @mock.patch.object(cinder.API, 'get',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    def test_get_bdm_image_metadata_with_cinder_down(self, mock_get):
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'id': 1,
                 'volume_id': 1,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                 }))]
        self.assertRaises(exception.CinderConnectionFailed,
                          self.compute_api._get_bdm_image_metadata,
                          self.context,
                          bdms, legacy_bdm=True)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get')
    @mock.patch.object(cinder.API, 'reserve_volume')
    def test_validate_bdm_returns_attachment_id(self, mock_reserve_volume,
                                                mock_get, mock_get_min_ver,
                                                mock_get_min_ver_all):
        # Tests that bdm validation *always* returns an attachment_id even if
        # it's None.
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()
        volume_id = 'e856840e-9f5b-4894-8bde-58c6e29ac1e8'
        volume_info = {'status': 'available',
                       'attach_status': 'detached',
                       'id': volume_id,
                       'multiattach': False}
        mock_get.return_value = volume_info

        # NOTE(mnaser): We use the AnonFakeDbBlockDeviceDict to make sure that
        #               the attachment_id field does not get any defaults to
        #               properly test this function.
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.AnonFakeDbBlockDeviceDict(
                {
                 'boot_index': 0,
                 'volume_id': volume_id,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                }))]
        self.compute_api._validate_bdm(self.context, instance, instance_type,
                                       bdms)
        self.assertIsNone(bdms[0].attachment_id)

        mock_get.assert_called_once_with(self.context, volume_id)
        mock_reserve_volume.assert_called_once_with(
            self.context, volume_id)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get')
    @mock.patch.object(cinder.API, 'reserve_volume',
                       side_effect=exception.InvalidInput(reason='error'))
    def test_validate_bdm_with_error_volume(self, mock_reserve_volume,
                                            mock_get, mock_get_min_ver,
                                            mock_get_min_ver_all):
        # Tests that an InvalidInput exception raised from
        # volume_api.reserve_volume due to the volume status not being
        # 'available' results in _validate_bdm re-raising InvalidVolume.
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()
        volume_id = 'e856840e-9f5b-4894-8bde-58c6e29ac1e8'
        volume_info = {'status': 'error',
                       'attach_status': 'detached',
                       'id': volume_id,
                       'multiattach': False}
        mock_get.return_value = volume_info
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'boot_index': 0,
                 'volume_id': volume_id,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                }))]

        self.assertRaises(exception.InvalidVolume,
                          self.compute_api._validate_bdm,
                          self.context,
                          instance, instance_type, bdms)

        mock_get.assert_called_once_with(self.context, volume_id)
        mock_reserve_volume.assert_called_once_with(
            self.context, volume_id)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get_snapshot',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    @mock.patch.object(cinder.API, 'get',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    def test_validate_bdm_with_cinder_down(self, mock_get, mock_get_snapshot,
                                           mock_get_min_ver):
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()
        bdm = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'id': 1,
                 'volume_id': 1,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                 'boot_index': 0,
                 }))]
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'id': 1,
                 'snapshot_id': 1,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                 'boot_index': 0,
                 }))]
        self.assertRaises(exception.CinderConnectionFailed,
                          self.compute_api._validate_bdm,
                          self.context,
                          instance, instance_type, bdm)
        self.assertRaises(exception.CinderConnectionFailed,
                          self.compute_api._validate_bdm,
                          self.context,
                          instance, instance_type, bdms)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(cinder.API, 'get')
    @mock.patch.object(cinder.API, 'attachment_create',
                       side_effect=exception.InvalidInput(reason='error'))
    def test_validate_bdm_with_error_volume_new_flow(self, mock_attach_create,
                                                     mock_get,
                                                     mock_get_min_ver,
                                                     mock_get_min_ver_all):
        # Tests that an InvalidInput exception raised from
        # volume_api.attachment_create due to the volume status not being
        # 'available' results in _validate_bdm re-raising InvalidVolume.
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()
        volume_id = 'e856840e-9f5b-4894-8bde-58c6e29ac1e8'
        volume_info = {'status': 'error',
                       'attach_status': 'detached',
                       'id': volume_id, 'multiattach': False}
        mock_get.return_value = volume_info
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {
                 'boot_index': 0,
                 'volume_id': volume_id,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_name': 'vda',
                }))]

        self.assertRaises(exception.InvalidVolume,
                          self.compute_api._validate_bdm,
                          self.context,
                          instance, instance_type, bdms)

        mock_get.assert_called_once_with(self.context, volume_id)
        mock_attach_create.assert_called_once_with(
            self.context, volume_id, instance.uuid)

    def _test_provision_instances_with_cinder_error(self,
                                                    expected_exception):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects.Instance, 'create')
        @mock.patch.object(self.compute_api.security_group_api,
                'ensure_default')
        @mock.patch.object(self.compute_api, '_create_block_device_mapping')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        def do_test(
                mock_req_spec_from_components, _mock_create_bdm,
                _mock_ensure_default, _mock_create, mock_check_num_inst_quota):
            req_spec_mock = mock.MagicMock()

            mock_check_num_inst_quota.return_value = 1
            mock_req_spec_from_components.return_value = req_spec_mock

            ctxt = context.RequestContext('fake-user', 'fake-project')
            flavor = self._create_flavor()
            min_count = max_count = 1
            boot_meta = {
                'id': 'fake-image-id',
                'properties': {'mappings': []},
                'status': 'fake-status',
                'location': 'far-away'}
            base_options = {'image_ref': 'fake-ref',
                            'display_name': 'fake-name',
                            'project_id': 'fake-project',
                            'availability_zone': None,
                            'metadata': {},
                            'access_ip_v4': None,
                            'access_ip_v6': None,
                            'config_drive': None,
                            'key_name': None,
                            'reservation_id': None,
                            'kernel_id': None,
                            'ramdisk_id': None,
                            'root_device_name': None,
                            'user_data': None,
                            'numa_topology': None,
                            'pci_requests': None}
            security_groups = {}
            block_device_mapping = [objects.BlockDeviceMapping(
                    **fake_block_device.FakeDbBlockDeviceDict(
                    {
                     'id': 1,
                     'volume_id': 1,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'device_name': 'vda',
                     'boot_index': 0,
                     }))]
            shutdown_terminate = True
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}

            self.assertRaises(expected_exception,
                              self.compute_api._provision_instances, ctxt,
                              flavor, min_count, max_count, base_options,
                              boot_meta, security_groups, block_device_mapping,
                              shutdown_terminate, instance_group,
                              check_server_group_quota, filter_properties,
                              None, objects.TagList())

        do_test()

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    def test_provision_instances_with_cinder_down(self, mock_get,
                                                  mock_get_min_ver):
        self._test_provision_instances_with_cinder_error(
            expected_exception=exception.CinderConnectionFailed)

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=17)
    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get',
                       return_value={'id': '1', 'multiattach': False})
    @mock.patch.object(cinder.API, 'check_availability_zone')
    @mock.patch.object(cinder.API, 'reserve_volume',
                       side_effect=exception.InvalidInput(reason='error'))
    def test_provision_instances_with_error_volume(self,
                                                   mock_cinder_check_av_zone,
                                                   mock_reserve_volume,
                                                   mock_get,
                                                   mock_get_min_ver_cells,
                                                   mock_get_min_ver):
        self._test_provision_instances_with_cinder_error(
            expected_exception=exception.InvalidVolume)

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(cinder.API, 'get',
                       return_value={'id': '1', 'multiattach': False})
    @mock.patch.object(cinder.API, 'check_availability_zone')
    @mock.patch.object(cinder.API, 'attachment_create',
                       side_effect=exception.InvalidInput(reason='error'))
    def test_provision_instances_with_error_volume_new_flow(self,
        mock_cinder_check_av_zone, mock_attach_create, mock_get,
        mock_get_min_ver_cells, mock_get_min_ver):
        self._test_provision_instances_with_cinder_error(
            expected_exception=exception.InvalidVolume)

    @mock.patch('nova.objects.RequestSpec.from_components')
    @mock.patch('nova.objects.BuildRequest')
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.objects.InstanceMapping.create')
    def test_provision_instances_with_keypair(self, mock_im, mock_instance,
                                              mock_br, mock_rs):
        fake_keypair = objects.KeyPair(name='test')

        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(self.compute_api, 'security_group_api')
        @mock.patch.object(self.compute_api,
                           'create_db_entry_for_new_instance')
        @mock.patch.object(self.compute_api,
                           '_bdm_validate_set_size_and_instance')
        @mock.patch.object(self.compute_api, '_create_block_device_mapping')
        def do_test(mock_cbdm, mock_bdm_v, mock_cdb, mock_sg, mock_cniq):
            mock_cniq.return_value = 1
            self.compute_api._provision_instances(self.context,
                                                  mock.sentinel.flavor,
                                                  1, 1, mock.MagicMock(),
                                                  {}, None,
                                                  None, None, None, {}, None,
                                                  fake_keypair,
                                                  objects.TagList())
            self.assertEqual(
                'test',
                mock_instance.return_value.keypairs.objects[0].name)
            self.compute_api._provision_instances(self.context,
                                                  mock.sentinel.flavor,
                                                  1, 1, mock.MagicMock(),
                                                  {}, None,
                                                  None, None, None, {}, None,
                                                  None, objects.TagList())
            self.assertEqual(
                0,
                len(mock_instance.return_value.keypairs.objects))

        do_test()

    def test_provision_instances_creates_build_request(self):
        @mock.patch.object(objects.Instance, 'create')
        @mock.patch.object(self.compute_api, 'volume_api')
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(self.compute_api.security_group_api,
                'ensure_default')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch.object(objects.BuildRequest, 'create')
        @mock.patch.object(objects.InstanceMapping, 'create')
        @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                return_value=17)
        @mock.patch.object(objects.Service, 'get_minimum_version',
                return_value=17)
        def do_test(mock_get_min_ver, mock_get_min_ver_cells,
                    _mock_inst_mapping_create, mock_build_req,
                    mock_req_spec_from_components, _mock_ensure_default,
                    mock_check_num_inst_quota, mock_volume, mock_inst_create):

            min_count = 1
            max_count = 2
            mock_check_num_inst_quota.return_value = 2

            ctxt = context.RequestContext('fake-user', 'fake-project')
            flavor = self._create_flavor()
            boot_meta = {
                'id': 'fake-image-id',
                'properties': {'mappings': []},
                'status': 'fake-status',
                'location': 'far-away'}
            base_options = {'image_ref': 'fake-ref',
                            'display_name': 'fake-name',
                            'project_id': 'fake-project',
                            'availability_zone': None,
                            'metadata': {},
                            'access_ip_v4': None,
                            'access_ip_v6': None,
                            'config_drive': None,
                            'key_name': None,
                            'reservation_id': None,
                            'kernel_id': None,
                            'ramdisk_id': None,
                            'root_device_name': None,
                            'user_data': None,
                            'numa_topology': None,
                            'pci_requests': None}
            security_groups = {}
            block_device_mappings = objects.BlockDeviceMappingList(
                objects=[objects.BlockDeviceMapping(
                    **fake_block_device.FakeDbBlockDeviceDict(
                    {
                     'id': 1,
                     'volume_id': 1,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'device_name': 'vda',
                     'boot_index': 0,
                     }))])
            mock_volume.get.return_value = {'id': '1', 'multiattach': False}
            instance_tags = objects.TagList(objects=[objects.Tag(tag='tag')])
            shutdown_terminate = True
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}

            instances_to_build = self.compute_api._provision_instances(
                    ctxt, flavor,
                    min_count, max_count, base_options, boot_meta,
                    security_groups, block_device_mappings, shutdown_terminate,
                    instance_group, check_server_group_quota,
                    filter_properties, None, instance_tags)

            for rs, br, im in instances_to_build:
                self.assertIsInstance(br.instance, objects.Instance)
                self.assertTrue(uuidutils.is_uuid_like(br.instance.uuid))
                self.assertEqual(base_options['project_id'],
                                 br.instance.project_id)
                self.assertEqual(1, br.block_device_mappings[0].id)
                self.assertEqual(br.instance.uuid, br.tags[0].resource_id)
                br.create.assert_called_with()

        do_test()

    def test_provision_instances_creates_instance_mapping(self):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects.Instance, 'create', new=mock.MagicMock())
        @mock.patch.object(self.compute_api.security_group_api,
                'ensure_default', new=mock.MagicMock())
        @mock.patch.object(self.compute_api, '_validate_bdm',
                new=mock.MagicMock())
        @mock.patch.object(self.compute_api, '_create_block_device_mapping',
                new=mock.MagicMock())
        @mock.patch.object(objects.RequestSpec, 'from_components',
                mock.MagicMock())
        @mock.patch.object(objects.BuildRequest, 'create',
                new=mock.MagicMock())
        @mock.patch('nova.objects.InstanceMapping')
        def do_test(mock_inst_mapping, mock_check_num_inst_quota):
            inst_mapping_mock = mock.MagicMock()

            mock_check_num_inst_quota.return_value = 1
            mock_inst_mapping.return_value = inst_mapping_mock

            ctxt = context.RequestContext('fake-user', 'fake-project')
            flavor = self._create_flavor()
            min_count = max_count = 1
            boot_meta = {
                'id': 'fake-image-id',
                'properties': {'mappings': []},
                'status': 'fake-status',
                'location': 'far-away'}
            base_options = {'image_ref': 'fake-ref',
                            'display_name': 'fake-name',
                            'project_id': 'fake-project',
                            'availability_zone': None,
                            'metadata': {},
                            'access_ip_v4': None,
                            'access_ip_v6': None,
                            'config_drive': None,
                            'key_name': None,
                            'reservation_id': None,
                            'kernel_id': None,
                            'ramdisk_id': None,
                            'root_device_name': None,
                            'user_data': None,
                            'numa_topology': None,
                            'pci_requests': None}
            security_groups = {}
            block_device_mapping = objects.BlockDeviceMappingList(
                objects=[objects.BlockDeviceMapping(
                    **fake_block_device.FakeDbBlockDeviceDict(
                    {
                     'id': 1,
                     'volume_id': 1,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'device_name': 'vda',
                     'boot_index': 0,
                     }))])
            shutdown_terminate = True
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}

            instances_to_build = (
                self.compute_api._provision_instances(ctxt, flavor,
                    min_count, max_count, base_options, boot_meta,
                    security_groups, block_device_mapping, shutdown_terminate,
                    instance_group, check_server_group_quota,
                    filter_properties, None, objects.TagList()))
            rs, br, im = instances_to_build[0]
            self.assertTrue(uuidutils.is_uuid_like(br.instance.uuid))
            self.assertEqual(br.instance_uuid, im.instance_uuid)

            self.assertEqual(br.instance.uuid,
                             inst_mapping_mock.instance_uuid)
            self.assertIsNone(inst_mapping_mock.cell_mapping)
            self.assertEqual(ctxt.project_id, inst_mapping_mock.project_id)
        do_test()

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=17)
    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=17)
    @mock.patch.object(cinder.API, 'get',
                       return_value={'id': '1', 'multiattach': False})
    @mock.patch.object(cinder.API, 'check_availability_zone',)
    @mock.patch.object(cinder.API, 'reserve_volume',
                   side_effect=(None, exception.InvalidInput(reason='error')))
    def test_provision_instances_cleans_up_when_volume_invalid(self,
            _mock_cinder_reserve_volume,
            _mock_cinder_check_availability_zone, _mock_cinder_get,
            _mock_get_min_ver_cells, _mock_get_min_ver):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects, 'Instance')
        @mock.patch.object(self.compute_api.security_group_api,
                'ensure_default')
        @mock.patch.object(self.compute_api, '_create_block_device_mapping')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch.object(objects, 'BuildRequest')
        @mock.patch.object(objects, 'InstanceMapping')
        def do_test(mock_inst_mapping, mock_build_req,
                mock_req_spec_from_components, _mock_create_bdm,
                _mock_ensure_default, mock_inst, mock_check_num_inst_quota):

            min_count = 1
            max_count = 2
            mock_check_num_inst_quota.return_value = 2
            req_spec_mock = mock.MagicMock()
            mock_req_spec_from_components.return_value = req_spec_mock
            inst_mocks = [mock.MagicMock() for i in range(max_count)]
            for inst_mock in inst_mocks:
                inst_mock.project_id = 'fake-project'
            mock_inst.side_effect = inst_mocks
            build_req_mocks = [mock.MagicMock() for i in range(max_count)]
            mock_build_req.side_effect = build_req_mocks
            inst_map_mocks = [mock.MagicMock() for i in range(max_count)]
            mock_inst_mapping.side_effect = inst_map_mocks

            ctxt = context.RequestContext('fake-user', 'fake-project')
            flavor = self._create_flavor()
            boot_meta = {
                'id': 'fake-image-id',
                'properties': {'mappings': []},
                'status': 'fake-status',
                'location': 'far-away'}
            base_options = {'image_ref': 'fake-ref',
                            'display_name': 'fake-name',
                            'project_id': 'fake-project',
                            'availability_zone': None,
                            'metadata': {},
                            'access_ip_v4': None,
                            'access_ip_v6': None,
                            'config_drive': None,
                            'key_name': None,
                            'reservation_id': None,
                            'kernel_id': None,
                            'ramdisk_id': None,
                            'root_device_name': None,
                            'user_data': None,
                            'numa_topology': None,
                            'pci_requests': None}
            security_groups = {}
            block_device_mapping = objects.BlockDeviceMappingList(
                objects=[objects.BlockDeviceMapping(
                    **fake_block_device.FakeDbBlockDeviceDict(
                    {
                     'id': 1,
                     'volume_id': 1,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'device_name': 'vda',
                     'boot_index': 0,
                     }))])
            shutdown_terminate = True
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}
            tags = objects.TagList()
            self.assertRaises(exception.InvalidVolume,
                              self.compute_api._provision_instances, ctxt,
                              flavor, min_count, max_count, base_options,
                              boot_meta, security_groups, block_device_mapping,
                              shutdown_terminate, instance_group,
                              check_server_group_quota, filter_properties,
                              None, tags)
            # First instance, build_req, mapping is created and destroyed
            self.assertTrue(build_req_mocks[0].create.called)
            self.assertTrue(build_req_mocks[0].destroy.called)
            self.assertTrue(inst_map_mocks[0].create.called)
            self.assertTrue(inst_map_mocks[0].destroy.called)
            # Second instance, build_req, mapping is not created nor destroyed
            self.assertFalse(inst_mocks[1].create.called)
            self.assertFalse(inst_mocks[1].destroy.called)
            self.assertFalse(build_req_mocks[1].destroy.called)
            self.assertFalse(inst_map_mocks[1].destroy.called)

        do_test()

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(objects.service, 'get_minimum_version_all_cells',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(cinder.API, 'get',
                       return_value={'id': '1', 'multiattach': False})
    @mock.patch.object(cinder.API, 'check_availability_zone',)
    @mock.patch.object(cinder.API, 'attachment_create',
                       side_effect=[{'id': uuids.attachment_id},
                                    exception.InvalidInput(reason='error')])
    @mock.patch.object(objects.BlockDeviceMapping, 'save')
    def test_provision_instances_cleans_up_when_volume_invalid_new_flow(self,
            _mock_bdm, _mock_cinder_attach_create,
            _mock_cinder_check_availability_zone, _mock_cinder_get,
            _mock_get_min_ver_cells, _mock_get_min_ver):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects, 'Instance')
        @mock.patch.object(self.compute_api.security_group_api,
                'ensure_default')
        @mock.patch.object(self.compute_api, '_create_block_device_mapping')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch.object(objects, 'BuildRequest')
        @mock.patch.object(objects, 'InstanceMapping')
        def do_test(mock_inst_mapping, mock_build_req,
                mock_req_spec_from_components, _mock_create_bdm,
                _mock_ensure_default, mock_inst, mock_check_num_inst_quota):

            min_count = 1
            max_count = 2
            mock_check_num_inst_quota.return_value = 2
            req_spec_mock = mock.MagicMock()
            mock_req_spec_from_components.return_value = req_spec_mock
            inst_mocks = [mock.MagicMock() for i in range(max_count)]
            for inst_mock in inst_mocks:
                inst_mock.project_id = 'fake-project'
            mock_inst.side_effect = inst_mocks
            build_req_mocks = [mock.MagicMock() for i in range(max_count)]
            mock_build_req.side_effect = build_req_mocks
            inst_map_mocks = [mock.MagicMock() for i in range(max_count)]
            mock_inst_mapping.side_effect = inst_map_mocks

            ctxt = context.RequestContext('fake-user', 'fake-project')
            flavor = self._create_flavor()
            boot_meta = {
                'id': 'fake-image-id',
                'properties': {'mappings': []},
                'status': 'fake-status',
                'location': 'far-away'}
            base_options = {'image_ref': 'fake-ref',
                            'display_name': 'fake-name',
                            'project_id': 'fake-project',
                            'availability_zone': None,
                            'metadata': {},
                            'access_ip_v4': None,
                            'access_ip_v6': None,
                            'config_drive': None,
                            'key_name': None,
                            'reservation_id': None,
                            'kernel_id': None,
                            'ramdisk_id': None,
                            'root_device_name': None,
                            'user_data': None,
                            'numa_topology': None,
                            'pci_requests': None}
            security_groups = {}
            block_device_mapping = objects.BlockDeviceMappingList(
                objects=[objects.BlockDeviceMapping(
                    **fake_block_device.FakeDbBlockDeviceDict(
                    {
                     'id': 1,
                     'volume_id': 1,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'device_name': 'vda',
                     'boot_index': 0,
                     }))])
            shutdown_terminate = True
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}
            tags = objects.TagList()
            self.assertRaises(exception.InvalidVolume,
                              self.compute_api._provision_instances, ctxt,
                              flavor, min_count, max_count, base_options,
                              boot_meta, security_groups, block_device_mapping,
                              shutdown_terminate, instance_group,
                              check_server_group_quota, filter_properties,
                              None, tags)
            # First instance, build_req, mapping is created and destroyed
            self.assertTrue(build_req_mocks[0].create.called)
            self.assertTrue(build_req_mocks[0].destroy.called)
            self.assertTrue(inst_map_mocks[0].create.called)
            self.assertTrue(inst_map_mocks[0].destroy.called)
            # Second instance, build_req, mapping is not created nor destroyed
            self.assertFalse(inst_mocks[1].create.called)
            self.assertFalse(inst_mocks[1].destroy.called)
            self.assertFalse(build_req_mocks[1].destroy.called)
            self.assertFalse(inst_map_mocks[1].destroy.called)

        do_test()

    def test_provision_instances_creates_reqspec_with_secgroups(self):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(self.compute_api, 'security_group_api')
        @mock.patch.object(compute_api, 'objects')
        @mock.patch.object(self.compute_api, '_create_block_device_mapping',
                           new=mock.MagicMock())
        @mock.patch.object(self.compute_api,
                           'create_db_entry_for_new_instance',
                           new=mock.MagicMock())
        @mock.patch.object(self.compute_api,
                           '_bdm_validate_set_size_and_instance',
                           new=mock.MagicMock())
        def test(mock_objects, mock_secgroup, mock_cniq):
            ctxt = context.RequestContext('fake-user', 'fake-project')
            mock_cniq.return_value = 1
            self.compute_api._provision_instances(ctxt, None, None, None,
                                                  mock.MagicMock(), None, None,
                                                  [], None, None, None, None,
                                                  None, objects.TagList())
            secgroups = mock_secgroup.populate_security_groups.return_value
            mock_objects.RequestSpec.from_components.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, mock.ANY, mock.ANY, mock.ANY,
                mock.ANY, mock.ANY, mock.ANY,
                security_groups=secgroups)
        test()

    def _test_rescue(self, vm_state=vm_states.ACTIVE, rescue_password=None,
                     rescue_image=None, clean_shutdown=True):
        instance = self._create_instance_obj(params={'vm_state': vm_state})
        bdms = []
        with test.nested(
            mock.patch.object(objects.BlockDeviceMappingList,
                              'get_by_instance_uuid', return_value=bdms),
            mock.patch.object(compute_utils, 'is_volume_backed_instance',
                              return_value=False),
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'rescue_instance')
        ) as (
            bdm_get_by_instance_uuid, volume_backed_inst, instance_save,
            record_action_start, rpcapi_rescue_instance
        ):
            self.compute_api.rescue(self.context, instance,
                                    rescue_password=rescue_password,
                                    rescue_image_ref=rescue_image,
                                    clean_shutdown=clean_shutdown)
            # assert field values set on the instance object
            self.assertEqual(task_states.RESCUING, instance.task_state)
            # assert our mock calls
            bdm_get_by_instance_uuid.assert_called_once_with(
                self.context, instance.uuid)
            volume_backed_inst.assert_called_once_with(
                self.context, instance, bdms)
            instance_save.assert_called_once_with(expected_task_state=[None])
            record_action_start.assert_called_once_with(
                self.context, instance, instance_actions.RESCUE)
            rpcapi_rescue_instance.assert_called_once_with(
                self.context, instance=instance,
                rescue_password=rescue_password,
                rescue_image_ref=rescue_image,
                clean_shutdown=clean_shutdown)

    def test_rescue_active(self):
        self._test_rescue()

    def test_rescue_stopped(self):
        self._test_rescue(vm_state=vm_states.STOPPED)

    def test_rescue_error(self):
        self._test_rescue(vm_state=vm_states.ERROR)

    def test_rescue_with_password(self):
        self._test_rescue(rescue_password='fake-password')

    def test_rescue_with_image(self):
        self._test_rescue(rescue_image='fake-image')

    def test_rescue_forced_shutdown(self):
        self._test_rescue(clean_shutdown=False)

    def test_unrescue(self):
        instance = self._create_instance_obj(
            params={'vm_state': vm_states.RESCUED})
        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'unrescue_instance')
        ) as (
            instance_save, record_action_start, rpcapi_unrescue_instance
        ):
            self.compute_api.unrescue(self.context, instance)
            # assert field values set on the instance object
            self.assertEqual(task_states.UNRESCUING, instance.task_state)
            # assert our mock calls
            instance_save.assert_called_once_with(expected_task_state=[None])
            record_action_start.assert_called_once_with(
                self.context, instance, instance_actions.UNRESCUE)
            rpcapi_unrescue_instance.assert_called_once_with(
                self.context, instance=instance)

    def test_set_admin_password_invalid_state(self):
        # Tests that InstanceInvalidState is raised when not ACTIVE.
        instance = self._create_instance_obj({'vm_state': vm_states.STOPPED})
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.set_admin_password,
                          self.context, instance)

    def test_set_admin_password(self):
        # Ensure instance can have its admin password set.
        instance = self._create_instance_obj()

        @mock.patch.object(objects.Instance, 'save')
        @mock.patch.object(self.compute_api, '_record_action_start')
        @mock.patch.object(self.compute_api.compute_rpcapi,
                           'set_admin_password')
        def do_test(compute_rpcapi_mock, record_mock, instance_save_mock):
            # call the API
            self.compute_api.set_admin_password(self.context, instance)
            # make our assertions
            instance_save_mock.assert_called_once_with(
                expected_task_state=[None])
            record_mock.assert_called_once_with(
                self.context, instance, instance_actions.CHANGE_PASSWORD)
            compute_rpcapi_mock.assert_called_once_with(
                self.context, instance=instance, new_pass=None)

        do_test()

    def _test_attach_interface_invalid_state(self, state):
        instance = self._create_instance_obj(
            params={'vm_state': state})
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.attach_interface,
                          self.context, instance, '', '', '', [])

    def test_attach_interface_invalid_state(self):
        for state in [vm_states.BUILDING, vm_states.DELETED,
                      vm_states.ERROR, vm_states.RESCUED,
                      vm_states.RESIZED, vm_states.SOFT_DELETED,
                      vm_states.SUSPENDED, vm_states.SHELVED,
                      vm_states.SHELVED_OFFLOADED]:
            self._test_attach_interface_invalid_state(state)

    def _test_detach_interface_invalid_state(self, state):
        instance = self._create_instance_obj(
            params={'vm_state': state})
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.detach_interface,
                          self.context, instance, '', '', '', [])

    def test_detach_interface_invalid_state(self):
        for state in [vm_states.BUILDING, vm_states.DELETED,
                      vm_states.ERROR, vm_states.RESCUED,
                      vm_states.RESIZED, vm_states.SOFT_DELETED,
                      vm_states.SUSPENDED, vm_states.SHELVED,
                      vm_states.SHELVED_OFFLOADED]:
            self._test_detach_interface_invalid_state(state)

    def _test_check_and_transform_bdm(self, block_device_mapping):
        instance_type = self._create_flavor()
        base_options = {'uuid': uuids.bdm_instance,
                        'image_ref': 'fake_image_ref',
                        'metadata': {}}
        image_meta = {'status': 'active',
                      'name': 'image_name',
                      'deleted': False,
                      'container_format': 'bare',
                      'id': 'image_id'}
        legacy_bdm = False
        block_device_mapping = block_device_mapping
        self.assertRaises(exception.InvalidRequest,
                          self.compute_api._check_and_transform_bdm,
                          self.context, base_options, instance_type,
                          image_meta, 1, 1, block_device_mapping, legacy_bdm)

    def test_check_and_transform_bdm_source_volume(self):
        block_device_mapping = [{'boot_index': 0,
                                 'device_name': None,
                                 'image_id': 'image_id',
                                 'source_type': 'image'},
                                {'device_name': '/dev/vda',
                                 'source_type': 'volume',
                                 'destination_type': 'volume',
                                 'device_type': None,
                                 'volume_id': 'volume_id'}]
        self._test_check_and_transform_bdm(block_device_mapping)

    def test_check_and_transform_bdm_source_snapshot(self):
        block_device_mapping = [{'boot_index': 0,
                                 'device_name': None,
                                 'image_id': 'image_id',
                                 'source_type': 'image'},
                                {'device_name': '/dev/vda',
                                 'source_type': 'snapshot',
                                 'destination_type': 'volume',
                                 'device_type': None,
                                 'volume_id': 'volume_id'}]
        self._test_check_and_transform_bdm(block_device_mapping)

    def test_bdm_validate_set_size_and_instance(self):
        swap_size = 42
        ephemeral_size = 24
        instance = self._create_instance_obj()
        instance_type = self._create_flavor(swap=swap_size,
                                            ephemeral_gb=ephemeral_size)
        block_device_mapping = [
                {'device_name': '/dev/sda1',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
                 'delete_on_termination': False,
                 'boot_index': 0},
                {'device_name': '/dev/sdb2',
                 'source_type': 'blank', 'destination_type': 'local',
                 'guest_format': 'swap', 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'source_type': 'blank', 'destination_type': 'local',
                 'guest_format': 'ext3', 'delete_on_termination': False}]

        block_device_mapping = (
                block_device_obj.block_device_make_list_from_dicts(
                    self.context,
                    map(fake_block_device.AnonFakeDbBlockDeviceDict,
                        block_device_mapping)))

        with mock.patch.object(self.compute_api, '_validate_bdm'):
            bdms = self.compute_api._bdm_validate_set_size_and_instance(
                self.context, instance, instance_type, block_device_mapping)

        expected = [{'device_name': '/dev/sda1',
                     'source_type': 'snapshot', 'destination_type': 'volume',
                     'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
                     'delete_on_termination': False,
                     'boot_index': 0},
                    {'device_name': '/dev/sdb2',
                     'source_type': 'blank', 'destination_type': 'local',
                     'guest_format': 'swap', 'delete_on_termination': False},
                    {'device_name': '/dev/sdb3',
                     'source_type': 'blank', 'destination_type': 'local',
                     'delete_on_termination': False}]
        # Check that the bdm matches what was asked for and that instance_uuid
        # and volume_size are set properly.
        for exp, bdm in zip(expected, bdms):
            self.assertEqual(exp['device_name'], bdm.device_name)
            self.assertEqual(exp['destination_type'], bdm.destination_type)
            self.assertEqual(exp['source_type'], bdm.source_type)
            self.assertEqual(exp['delete_on_termination'],
                             bdm.delete_on_termination)
            self.assertEqual(instance.uuid, bdm.instance_uuid)
        self.assertEqual(swap_size, bdms[1].volume_size)
        self.assertEqual(ephemeral_size, bdms[2].volume_size)

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch('nova.compute.instance_list.get_instance_objects_sorted')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_tenant_to_project_conversion(self, mock_cell_map_get, mock_get,
                                          mock_buildreq_get):
        mock_cell_map_get.side_effect = exception.CellMappingNotFound(
                                                                uuid='fake')
        mock_get.return_value = objects.InstanceList(objects=[])
        api = compute_api.API()
        api.get_all(self.context, search_opts={'tenant_id': 'foo'})
        filters = mock_get.call_args_list[0][0][1]
        self.assertEqual({'project_id': 'foo'}, filters)

    def test_populate_instance_names_host_name(self):
        params = dict(display_name="vm1")
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 1)
        self.assertEqual('vm1', instance.hostname)

    def test_populate_instance_names_host_name_is_empty(self):
        params = dict(display_name=u'\u865a\u62df\u673a\u662f\u4e2d\u6587')
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 1)
        self.assertEqual('Server-%s' % instance.uuid, instance.hostname)

    def test_populate_instance_names_host_name_multi(self):
        params = dict(display_name="vm")
        instance = self._create_instance_obj(params=params)
        with mock.patch.object(instance, 'save'):
            self.compute_api._apply_instance_name_template(self.context,
                                                           instance, 1)
            self.assertEqual('vm-2', instance.hostname)

    def test_populate_instance_names_host_name_is_empty_multi(self):
        params = dict(display_name=u'\u865a\u62df\u673a\u662f\u4e2d\u6587')
        instance = self._create_instance_obj(params=params)
        with mock.patch.object(instance, 'save'):
            self.compute_api._apply_instance_name_template(self.context,
                                                           instance, 1)
            self.assertEqual('Server-%s' % instance.uuid, instance.hostname)

    def test_host_statuses(self):
        instances = [
            objects.Instance(uuid=uuids.instance_1, host='host1', services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host1',
                             disabled=True, forced_down=True,
                             binary='nova-compute'))),
            objects.Instance(uuid=uuids.instance_2, host='host2', services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host2',
                             disabled=True, forced_down=False,
                             binary='nova-compute'))),
            objects.Instance(uuid=uuids.instance_3, host='host3', services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host3',
                             disabled=False, last_seen_up=timeutils.utcnow()
                             - datetime.timedelta(minutes=5),
                             forced_down=False, binary='nova-compute'))),
            objects.Instance(uuid=uuids.instance_4, host='host4', services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host4',
                             disabled=False, last_seen_up=timeutils.utcnow(),
                             forced_down=False, binary='nova-compute'))),
            objects.Instance(uuid=uuids.instance_5, host='host5', services=
                             objects.ServiceList()),
            objects.Instance(uuid=uuids.instance_6, host=None, services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host6',
                             disabled=True, forced_down=False,
                             binary='nova-compute'))),
            objects.Instance(uuid=uuids.instance_7, host='host2', services=
                             self._obj_to_list_obj(objects.ServiceList(
                             self.context), objects.Service(id=0, host='host2',
                             disabled=True, forced_down=False,
                             binary='nova-compute')))
            ]

        host_statuses = self.compute_api.get_instances_host_statuses(
                        instances)
        expect_statuses = {uuids.instance_1: fields_obj.HostStatus.DOWN,
                           uuids.instance_2: fields_obj.HostStatus.MAINTENANCE,
                           uuids.instance_3: fields_obj.HostStatus.UNKNOWN,
                           uuids.instance_4: fields_obj.HostStatus.UP,
                           uuids.instance_5: fields_obj.HostStatus.NONE,
                           uuids.instance_6: fields_obj.HostStatus.NONE,
                           uuids.instance_7: fields_obj.HostStatus.MAINTENANCE}
        for instance in instances:
            self.assertEqual(expect_statuses[instance.uuid],
                             host_statuses[instance.uuid])

    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    def test_live_migrate_force_complete_succeeded(
            self, action_start, get_by_id_and_instance):

        if self.cell_type == 'api':
            # cell api has not been implemented.
            return
        rpcapi = self.compute_api.compute_rpcapi

        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING

        migration = objects.Migration()
        migration.id = 0
        migration.status = 'running'
        get_by_id_and_instance.return_value = migration

        with mock.patch.object(
                rpcapi, 'live_migration_force_complete') as lm_force_complete:
            self.compute_api.live_migrate_force_complete(
                self.context, instance, migration)

            lm_force_complete.assert_called_once_with(self.context,
                                                      instance,
                                                      migration)
            action_start.assert_called_once_with(
                self.context, instance.uuid, 'live_migration_force_complete',
                want_result=False)

    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    def test_live_migrate_force_complete_invalid_migration_state(
            self, get_by_id_and_instance):
        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING

        migration = objects.Migration()
        migration.id = 0
        migration.status = 'error'
        get_by_id_and_instance.return_value = migration

        self.assertRaises(exception.InvalidMigrationState,
                          self.compute_api.live_migrate_force_complete,
                          self.context, instance, migration.id)

    def test_live_migrate_force_complete_invalid_vm_state(self):
        instance = self._create_instance_obj()
        instance.task_state = None

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.live_migrate_force_complete,
                          self.context, instance, '1')

    def _get_migration(self, migration_id, status, migration_type):
        migration = objects.Migration()
        migration.id = migration_id
        migration.status = status
        migration.migration_type = migration_type
        return migration

    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'live_migration_abort')
    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    def test_live_migrate_abort_succeeded(self,
                                          mock_get_migration,
                                          mock_lm_abort,
                                          mock_rec_action):
        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING
        migration = self._get_migration(21, 'running', 'live-migration')
        mock_get_migration.return_value = migration

        self.compute_api.live_migrate_abort(self.context,
                                            instance,
                                            migration.id)
        mock_rec_action.assert_called_once_with(self.context,
                                    instance,
                                    instance_actions.LIVE_MIGRATION_CANCEL)
        mock_lm_abort.called_once_with(self.context, instance, migration.id)

    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    def test_live_migration_abort_wrong_migration_status(self,
                                                         mock_get_migration):
        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING
        migration = self._get_migration(21, 'completed', 'live-migration')
        mock_get_migration.return_value = migration

        self.assertRaises(exception.InvalidMigrationState,
                          self.compute_api.live_migrate_abort,
                          self.context,
                          instance,
                          migration.id)

    def test_check_requested_networks_no_requested_networks(self):
        # When there are no requested_networks we call validate_networks on
        # the network API and return the results.
        with mock.patch.object(self.compute_api.network_api,
                               'validate_networks', return_value=3):
            count = self.compute_api._check_requested_networks(
                self.context, None, 5)
        self.assertEqual(3, count)

    def test_check_requested_networks_no_allocate(self):
        # When requested_networks is the single 'none' case for no allocation,
        # we don't validate networks and return the count passed in.
        requested_networks = (
            objects.NetworkRequestList(
                objects=[objects.NetworkRequest(network_id='none')]))
        with mock.patch.object(self.compute_api.network_api,
                               'validate_networks') as validate:
            count = self.compute_api._check_requested_networks(
                self.context, requested_networks, 5)
        self.assertEqual(5, count)
        self.assertFalse(validate.called)

    def test_check_requested_networks_auto_allocate(self):
        # When requested_networks is the single 'auto' case for allocation,
        # we validate networks and return the results.
        requested_networks = (
            objects.NetworkRequestList(
                objects=[objects.NetworkRequest(network_id='auto')]))
        with mock.patch.object(self.compute_api.network_api,
                               'validate_networks', return_value=4):
            count = self.compute_api._check_requested_networks(
                self.context, requested_networks, 5)
        self.assertEqual(4, count)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
            side_effect=exception.InstanceMappingNotFound(uuid='fake'))
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_no_mapping(self, mock_get_inst, mock_get_build_req,
            mock_get_inst_map):

        self.useFixture(fixtures.AllServicesCurrent())
        if self.cell_type is None:
            # No Mapping means NotFound
            self.assertRaises(exception.InstanceNotFound,
                              self.compute_api.get, self.context,
                              uuids.inst_uuid)
        else:
            self.compute_api.get(self.context, uuids.inst_uuid)
            mock_get_build_req.assert_not_called()
            mock_get_inst.assert_called_once_with(self.context,
                                                  uuids.inst_uuid,
                                                  expected_attrs=[
                                                      'metadata',
                                                      'system_metadata',
                                                      'security_groups',
                                                      'info_cache'])

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=15)
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_not_in_cell(self, mock_get_inst, mock_get_build_req,
                mock_get_inst_map, mock_get_min_service):
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        mock_get_inst_map.return_value = objects.InstanceMapping(
                cell_mapping=None)
        mock_get_build_req.return_value = build_req_obj
        instance = build_req_obj.instance
        mock_get_inst.return_value = instance

        inst_from_build_req = self.compute_api.get(self.context, instance.uuid)
        if self.cell_type is None:
            mock_get_inst_map.assert_called_once_with(self.context,
                                                      instance.uuid)
            mock_get_build_req.assert_called_once_with(self.context,
                                                       instance.uuid)
        else:
            mock_get_inst.assert_called_once_with(
                self.context, instance.uuid,
                expected_attrs=['metadata', 'system_metadata',
                                'security_groups', 'info_cache'])
        self.assertEqual(instance, inst_from_build_req)
        mock_get_min_service.assert_called_once_with(self.context,
                                                     'nova-osapi_compute')

    @mock.patch.object(context, 'set_target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_not_in_cell_buildreq_deleted_inst_in_cell(
            self, mock_get_inst, mock_get_build_req, mock_get_inst_map,
            mock_target_cell):
        # This test checks the following scenario:
        # The instance is not mapped to a cell, so it should be retrieved from
        # a BuildRequest object. However the BuildRequest does not exist
        # because the instance was put in a cell and mapped while while
        # attempting to get the BuildRequest. So pull the instance from the
        # cell.
        self.useFixture(fixtures.AllServicesCurrent())
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        instance = build_req_obj.instance
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping())

        mock_get_inst_map.side_effect = [
            objects.InstanceMapping(cell_mapping=None), inst_map]
        mock_get_build_req.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_get_inst.return_value = instance

        inst_from_get = self.compute_api.get(self.context, instance.uuid)

        inst_map_calls = [mock.call(self.context, instance.uuid),
                          mock.call(self.context, instance.uuid)]
        if self.cell_type is None:
            mock_get_inst_map.assert_has_calls(inst_map_calls)
            self.assertEqual(2, mock_get_inst_map.call_count)
            mock_get_build_req.assert_called_once_with(self.context,
                                                       instance.uuid)
            mock_target_cell.assert_called_once_with(self.context,
                                                 inst_map.cell_mapping)
        mock_get_inst.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=[
                                                  'metadata',
                                                  'system_metadata',
                                                  'security_groups',
                                                  'info_cache'])
        self.assertEqual(instance, inst_from_get)

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_not_in_cell_buildreq_deleted_inst_still_not_in_cell(
            self, mock_get_inst, mock_get_build_req, mock_get_inst_map,
            mock_target_cell):
        # This test checks the following scenario:
        # The instance is not mapped to a cell, so it should be retrieved from
        # a BuildRequest object. However the BuildRequest does not exist which
        # means it should now be possible to find the instance in a cell db.
        # But the instance is not mapped which means the cellsv2 migration has
        # not occurred in this scenario, so the instance is pulled from the
        # configured Nova db.

        # TODO(alaski): The tested case will eventually be an error condition.
        # But until we force cellsv2 migrations we need this to work.
        self.useFixture(fixtures.AllServicesCurrent())
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        instance = build_req_obj.instance

        mock_get_inst_map.side_effect = [
            objects.InstanceMapping(cell_mapping=None),
            objects.InstanceMapping(cell_mapping=None)]
        mock_get_build_req.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_get_inst.return_value = instance

        if self.cell_type is None:
            self.assertRaises(exception.InstanceNotFound,
                              self.compute_api.get,
                              self.context, instance.uuid)
        else:
            inst_from_get = self.compute_api.get(self.context, instance.uuid)

            mock_get_inst.assert_called_once_with(self.context,
                                                  instance.uuid,
                                                  expected_attrs=[
                                                      'metadata',
                                                      'system_metadata',
                                                      'security_groups',
                                                      'info_cache'])
            self.assertEqual(instance, inst_from_get)

    @mock.patch.object(context, 'set_target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_in_cell(self, mock_get_inst, mock_get_build_req,
            mock_get_inst_map, mock_target_cell):
        self.useFixture(fixtures.AllServicesCurrent())
        # This just checks that the instance is looked up normally and not
        # synthesized from a BuildRequest object. Verification of pulling the
        # instance from the proper cell will be added when that capability is.
        instance = self._create_instance_obj()
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping())
        mock_get_inst_map.return_value = inst_map
        mock_get_build_req.return_value = build_req_obj
        mock_get_inst.return_value = instance

        returned_inst = self.compute_api.get(self.context, instance.uuid)
        mock_get_build_req.assert_not_called()
        if self.cell_type is None:
            mock_get_inst_map.assert_called_once_with(self.context,
                                                      instance.uuid)
            mock_target_cell.assert_called_once_with(self.context,
                                                     inst_map.cell_mapping)
        else:
            self.assertFalse(mock_get_inst_map.called)
            self.assertFalse(mock_target_cell.called)
        self.assertEqual(instance, returned_inst)
        mock_get_inst.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=[
                                                  'metadata',
                                                  'system_metadata',
                                                  'security_groups',
                                                  'info_cache'])

    def _list_of_instances(self, length=1):
        instances = []
        for i in range(length):
            instances.append(
                fake_instance.fake_instance_obj(self.context, objects.Instance,
                                                uuid=uuidutils.generate_uuid())
            )
        return instances

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_includes_build_requests(self, mock_cell_mapping_get,
                                             mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, None, None,
                fields, ['baz'], ['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_includes_build_requests_filter_dupes(self,
            mock_cell_mapping_get, mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            # Insert one of the build_req_instances here so it shows up twice
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=build_req_instances[:1] + cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, None, None,
                fields, ['baz'], ['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_build_requests_decrement_limit(self,
                                                    mock_cell_mapping_get,
                                                    mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=10, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, 8, None,
                fields, ['baz'], ['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_get_all_includes_build_request_cell0(self, mock_cm_get_all,
                                    mock_cell_mapping_get,
                                    mock_buildreq_get, mock_target_cell):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.side_effect = [objects.InstanceList(
                                             self.context,
                                             objects=cell_instances)]

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            if self.cell_type is None:
                for cm in mock_cm_get_all.return_value:
                    mock_target_cell.assert_any_call(self.context, cm)
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                mock.ANY, {'foo': 'bar'},
                8, None,
                fields, ['baz'], ['desc'])
            for i, instance in enumerate(build_req_instances +
                                         cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_update_existing_instance_not_in_cell(self, mock_instmap_get,
                                                  mock_buildreq_get):
        mock_instmap_get.side_effect = exception.InstanceMappingNotFound(
            uuid='fake')
        self.useFixture(fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Just making sure that the instance has been created
        self.assertIsNotNone(instance.id)
        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(instance, 'save') as mock_inst_save:
            returned_instance = self.compute_api.update_instance(
                self.context, instance, updates)
        mock_buildreq_get.assert_not_called()
        self.assertEqual('foo_updated', returned_instance.display_name)
        mock_inst_save.assert_called_once_with()

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_update_existing_instance_in_cell(self, mock_instmap_get,
                                              mock_target_cell,
                                              mock_buildreq_get):
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping())
        mock_instmap_get.return_value = inst_map
        self.useFixture(fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Just making sure that the instance has been created
        self.assertIsNotNone(instance.id)
        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(instance, 'save') as mock_inst_save:
            returned_instance = self.compute_api.update_instance(
                self.context, instance, updates)
        if self.cell_type is None:
            mock_target_cell.assert_called_once_with(self.context,
                                                     inst_map.cell_mapping)
        mock_buildreq_get.assert_not_called()
        self.assertEqual('foo_updated', returned_instance.display_name)
        mock_inst_save.assert_called_once_with()

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_update_future_instance_with_buildreq(self, mock_buildreq_get):

        # This test checks that a new instance which is not yet peristed in
        # DB can be found by looking up the BuildRequest object so we can
        # update it.

        build_req_obj = fake_build_request.fake_req_obj(self.context)
        mock_buildreq_get.return_value = build_req_obj
        self.useFixture(fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Fake the fact that the instance is not yet persisted in DB
        del instance.id

        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(build_req_obj, 'save') as mock_buildreq_save:
            returned_instance = self.compute_api.update_instance(
                self.context, instance, updates)

        mock_buildreq_get.assert_called_once_with(self.context, instance.uuid)
        self.assertEqual(build_req_obj.instance, returned_instance)
        mock_buildreq_save.assert_called_once_with()
        self.assertEqual('foo_updated', returned_instance.display_name)

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_update_instance_in_cell_in_transition_state(self,
                                                         mock_buildreq_get,
                                                         mock_instmap_get,
                                                         mock_inst_get,
                                                         mock_target_cell):

        # This test is for covering the following case:
        #  - when we lookup the instance initially, that one is not yet mapped
        #    to a cell and consequently we retrieve it from the BuildRequest
        #  - when we update the instance, that one could have been mapped
        #    meanwhile and the BuildRequest was deleted
        #  - if the instance is mapped, lookup the cell DB to find the instance

        self.useFixture(fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Fake the fact that the instance is not yet persisted in DB
        del instance.id

        mock_buildreq_get.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping())
        mock_instmap_get.return_value = inst_map
        mock_inst_get.return_value = instance

        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(instance, 'save') as mock_inst_save:
            returned_instance = self.compute_api.update_instance(
                self.context, instance, updates)

        mock_buildreq_get.assert_called_once_with(self.context, instance.uuid)
        mock_target_cell.assert_called_once_with(self.context,
                                                 inst_map.cell_mapping)
        mock_inst_save.assert_called_once_with()
        self.assertEqual('foo_updated', returned_instance.display_name)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_update_instance_not_in_cell_in_transition_state(self,
                                                             mock_buildreq_get,
                                                             mock_instmap_get,
                                                             mock_inst_get):

        # This test is for covering the following case:
        #  - when we lookup the instance initially, that one is not yet mapped
        #    to a cell and consequently we retrieve it from the BuildRequest
        #  - when we update the instance, that one could have been mapped
        #    meanwhile and the BuildRequest was deleted
        #  - if the instance is not mapped, lookup the API DB to find whether
        #    the instance was deleted, or if the cellv2 migration is not done

        self.useFixture(fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Fake the fact that the instance is not yet persisted in DB
        del instance.id

        mock_buildreq_get.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_instmap_get.side_effect = exception.InstanceMappingNotFound(
            uuid='fake')
        mock_inst_get.return_value = instance

        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(instance, 'save') as mock_inst_save:
            returned_instance = self.compute_api.update_instance(
                self.context, instance, updates)

        mock_buildreq_get.assert_called_once_with(self.context, instance.uuid)
        mock_inst_save.assert_called_once_with()
        self.assertEqual('foo_updated', returned_instance.display_name)

        # Let's do a quick verification on the same unittest to see what
        # happens if the instance was deleted meanwhile.
        mock_inst_get.side_effect = exception.InstanceNotFound(
            instance_id=instance.uuid)
        self.assertRaises(exception.InstanceNotFound,
                          self.compute_api.update_instance,
                          self.context, instance, updates)

    def test_populate_instance_for_create_neutron_secgroups(self):
        """Tests that a list of security groups passed in do not actually get
        stored on with the instance when using neutron.
        """
        self.flags(use_neutron=True)
        flavor = self._create_flavor()
        params = {'display_name': 'fake-instance'}
        instance = self._create_instance_obj(params, flavor)
        security_groups = objects.SecurityGroupList()
        security_groups.objects = [
            secgroup_obj.SecurityGroup(uuid=uuids.secgroup_id)
        ]
        instance = self.compute_api._populate_instance_for_create(
            self.context, instance, {}, 0, security_groups, flavor, 1,
            False)
        self.assertEqual(0, len(instance.security_groups))


class ComputeAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIUnitTestCase, self).setUp()
        self.compute_api = compute_api.API()
        self.cell_type = None

    def test_resize_same_flavor_fails(self):
        self.assertRaises(exception.CannotResizeToSameFlavor,
                          self._test_resize, same_flavor=True)

    def test_find_service_in_cell_error_case(self):
        self.assertRaises(exception.NovaException,
                          compute_api._find_service_in_cell, self.context)

    @mock.patch('nova.objects.Service.get_by_id')
    def test_find_service_in_cell_targets(self, mock_get_service):
        mock_get_service.side_effect = [exception.NotFound(),
                                        mock.sentinel.service]
        compute_api.CELLS = [mock.sentinel.cell0, mock.sentinel.cell1]

        @contextlib.contextmanager
        def fake_target(context, cell):
            yield 'context-for-%s' % cell

        with mock.patch('nova.context.target_cell') as mock_target:
            mock_target.side_effect = fake_target
            s = compute_api._find_service_in_cell(self.context, service_id=123)
            self.assertEqual(mock.sentinel.service, s)
            cells = [call[0][0]
                     for call in mock_get_service.call_args_list]
            self.assertEqual(['context-for-%s' % c for c in compute_api.CELLS],
                             cells)

    def test_validate_and_build_base_options_translate_neutron_secgroup(self):
        """Tests that _check_requested_secgroups will return a uuid for a
        requested Neutron security group and that will be returned from
        _validate_and_build_base_options
        """
        instance_type = objects.Flavor(**test_flavor.fake_flavor)
        boot_meta = metadata = {}
        kernel_id = ramdisk_id = key_name = key_data = user_data = \
            access_ip_v4 = access_ip_v6 = config_drive = \
                auto_disk_config = reservation_id = None
        # This tests that 'default' is unchanged, but 'fake-security-group'
        # will be translated to a uuid for Neutron.
        requested_secgroups = ['default', 'fake-security-group']
        # This will short-circuit _check_requested_networks
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='none')])
        max_count = 1
        with mock.patch.object(
                self.compute_api.security_group_api, 'get',
                return_value={'id': uuids.secgroup_uuid}) as scget:
            base_options, max_network_count, key_pair, security_groups = (
                self.compute_api._validate_and_build_base_options(
                    self.context, instance_type, boot_meta, uuids.image_href,
                    mock.sentinel.image_id, kernel_id, ramdisk_id,
                    'fake-display-name', 'fake-description', key_name,
                    key_data, requested_secgroups, 'fake-az', user_data,
                    metadata, access_ip_v4, access_ip_v6, requested_networks,
                    config_drive, auto_disk_config, reservation_id, max_count
                )
            )
        # Assert the neutron security group API get method was called once
        # and only for the non-default security group name.
        scget.assert_called_once_with(self.context, 'fake-security-group')
        # Assert we translated the non-default secgroup name to uuid.
        self.assertItemsEqual(['default', uuids.secgroup_uuid],
                              security_groups)

    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_interface')
    def test_tagged_interface_attach(self, mock_attach, mock_record):
        instance = self._create_instance_obj()
        self.compute_api.attach_interface(self.context, instance, None, None,
                                          None, tag='foo')
        mock_attach.assert_called_with(self.context, instance=instance,
                                       network_id=None, port_id=None,
                                       requested_ip=None, tag='foo')
        mock_record.assert_called_once_with(
            self.context, instance, instance_actions.ATTACH_INTERFACE)

    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'detach_interface')
    def test_detach_interface(self, mock_detach, mock_record):
        instance = self._create_instance_obj()
        self.compute_api.detach_interface(self.context, instance, None)
        mock_detach.assert_called_with(self.context, instance=instance,
                                       port_id=None)
        mock_record.assert_called_once_with(
            self.context, instance, instance_actions.DETACH_INTERFACE)

    def test_check_attach_and_reserve_volume_multiattach_old_version(self):
        """Tests that _check_attach_and_reserve_volume fails if trying
        to use a multiattach volume with a microversion<2.60.
        """
        instance = self._create_instance_obj()
        volume = {'id': uuids.volumeid, 'multiattach': True}
        bdm = objects.BlockDeviceMapping(volume_id=uuids.volumeid,
                                         instance_uuid=instance.uuid)
        self.assertRaises(exception.MultiattachNotSupportedOldMicroversion,
                          self.compute_api._check_attach_and_reserve_volume,
                          self.context, volume, instance, bdm,
                          supports_multiattach=False)

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=compute_api.MIN_COMPUTE_MULTIATTACH - 1)
    def test_check_attach_and_reserve_volume_multiattach_new_inst_old_compute(
            self, get_min_version):
        """Tests that _check_attach_and_reserve_volume fails if trying
        to use a multiattach volume to create a new instance but the computes
        are not all upgraded yet.
        """
        instance = self._create_instance_obj()
        delattr(instance, 'id')
        volume = {'id': uuids.volumeid, 'multiattach': True}
        bdm = objects.BlockDeviceMapping(volume_id=uuids.volumeid,
                                         instance_uuid=instance.uuid)
        self.assertRaises(exception.MultiattachSupportNotYetAvailable,
                          self.compute_api._check_attach_and_reserve_volume,
                          self.context, volume, instance, bdm,
                          supports_multiattach=True)

    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=compute_api.MIN_COMPUTE_MULTIATTACH)
    @mock.patch('nova.volume.cinder.API.get',
                return_value={'id': uuids.volumeid, 'multiattach': True})
    @mock.patch('nova.volume.cinder.is_microversion_supported',
                return_value=None)
    def test_attach_volume_shelved_offloaded_fails(
            self, is_microversion_supported, volume_get, get_min_version):
        """Tests that trying to attach a multiattach volume to a shelved
        offloaded instance fails because it's not supported.
        """
        instance = self._create_instance_obj(
            params={'vm_state': vm_states.SHELVED_OFFLOADED})
        with mock.patch.object(
                self.compute_api, '_check_volume_already_attached_to_instance',
                return_value=None):
            self.assertRaises(exception.MultiattachToShelvedNotSupported,
                              self.compute_api.attach_volume,
                              self.context, instance, uuids.volumeid)

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    def test_get_all_ip_filter_use_neutron(self, mock_buildreq_get,
                                           mock_list_port, mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            self.compute_api.get_all(
                self.context, search_opts={'ip': 'fake'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_called_once_with(
                self.context, fixed_ips='ip_address_substr=fake',
                fields=['device_id'])
            mock_buildreq_get.assert_called_once_with(
                self.context, {'ip': 'fake', 'uuid': ['fake_device_id']},
                limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip': 'fake', 'uuid': ['fake_device_id']},
                None, None, fields, ['baz'], ['desc'])

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    def test_get_all_ip6_filter_use_neutron(self, mock_buildreq_get,
                                            mock_list_port, mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            self.compute_api.get_all(
                self.context, search_opts={'ip6': 'fake'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_called_once_with(
                self.context, fixed_ips='ip_address_substr=fake',
                fields=['device_id'])
            mock_buildreq_get.assert_called_once_with(
                self.context, {'ip6': 'fake', 'uuid': ['fake_device_id']},
                limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip6': 'fake', 'uuid': ['fake_device_id']},
                None, None, fields, ['baz'], ['desc'])

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    def test_get_all_ip_and_ip6_filter_use_neutron(self, mock_buildreq_get,
                                                   mock_list_port,
                                                   mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            self.compute_api.get_all(
                self.context, search_opts={'ip': 'fake1', 'ip6': 'fake2'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_has_calls([
                mock.call(
                    self.context, fixed_ips='ip_address_substr=fake1',
                    fields=['device_id']),
                mock.call(
                    self.context, fixed_ips='ip_address_substr=fake2',
                    fields=['device_id'])
            ])
            mock_buildreq_get.assert_called_once_with(
                self.context, {'ip': 'fake1', 'ip6': 'fake2',
                               'uuid': ['fake_device_id', 'fake_device_id']},
                limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip': 'fake1', 'ip6': 'fake2',
                               'uuid': ['fake_device_id', 'fake_device_id']},
                None, None, fields, ['baz'], ['desc'])

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    def test_get_all_ip6_filter_use_neutron_exc(self, mock_list_port,
                                                mock_check_ext):
        mock_check_ext.return_value = True
        mock_list_port.side_effect = exception.InternalError('fake')

        instances = self.compute_api.get_all(
            self.context, search_opts={'ip6': 'fake'},
            limit=None, marker='fake-marker', sort_keys=['baz'],
            sort_dirs=['desc'])
        mock_list_port.assert_called_once_with(
            self.context, fixed_ips='ip_address_substr=fake',
            fields=['device_id'])
        self.assertEqual([], instances.objects)

    @mock.patch('nova.compute.api.API._delete_while_booting',
                return_value=False)
    @mock.patch('nova.compute.api.API._lookup_instance')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_utils, 'notify_about_instance_usage')
    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    @mock.patch.object(objects.Instance, 'destroy')
    def _test_delete_volume_backed_instance(
            self, vm_state, mock_instance_destroy, bdm_destroy,
            notify_about_instance_usage, mock_save, mock_elevated,
            bdm_get_by_instance_uuid, mock_lookup, _mock_del_booting):
        volume_id = uuidutils.generate_uuid()
        conn_info = {'connector': {'host': 'orig-host'}}
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 42, 'volume_id': volume_id,
                 'source_type': 'volume', 'destination_type': 'volume',
                 'delete_on_termination': False,
                 'connection_info': jsonutils.dumps(conn_info)}))]

        bdm_get_by_instance_uuid.return_value = bdms
        mock_elevated.return_value = self.context

        params = {'host': None, 'vm_state': vm_state}
        inst = self._create_instance_obj(params=params)
        mock_lookup.return_value = None, inst
        connector = conn_info['connector']

        with mock.patch.object(self.compute_api.network_api,
                               'deallocate_for_instance') as mock_deallocate, \
             mock.patch.object(self.compute_api.volume_api,
                              'terminate_connection') as mock_terminate_conn, \
             mock.patch.object(self.compute_api.volume_api,
                              'detach') as mock_detach:
                self.compute_api.delete(self.context, inst)

        mock_deallocate.assert_called_once_with(self.context, inst)
        mock_detach.assert_called_once_with(self.context, volume_id,
                                            inst.uuid)
        mock_terminate_conn.assert_called_once_with(self.context,
                                                    volume_id, connector)
        bdm_destroy.assert_called_once_with()

    def test_delete_volume_backed_instance_in_error(self):
        self._test_delete_volume_backed_instance(vm_states.ERROR)

    def test_delete_volume_backed_instance_in_shelved_offloaded(self):
        self._test_delete_volume_backed_instance(vm_states.SHELVED_OFFLOADED)


class Cellsv1DeprecatedTestMixIn(object):
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_includes_build_requests(self, mock_cell_mapping_get,
                                             mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch.object(self.compute_api,
                               '_get_instances_by_filters') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker=None,
                fields=fields, sort_keys=['baz'], sort_dirs=['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_includes_build_requests_filter_dupes(self,
            mock_cell_mapping_get, mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch.object(self.compute_api,
                               '_get_instances_by_filters') as mock_inst_get:
            # Insert one of the build_req_instances here so it shows up twice
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=build_req_instances[:1] + cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=None, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=None, marker=None,
                fields=fields, sort_keys=['baz'], sort_dirs=['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_all_build_requests_decrement_limit(self,
                                                    mock_cell_mapping_get,
                                                    mock_buildreq_get):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell_instances = self._list_of_instances(2)

        with mock.patch.object(self.compute_api,
                               '_get_instances_by_filters') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances)

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_buildreq_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=10, marker='fake-marker',
                sort_keys=['baz'], sort_dirs=['desc'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'foo': 'bar'}, limit=8, marker=None,
                fields=fields, sort_keys=['baz'], sort_dirs=['desc'])
            for i, instance in enumerate(build_req_instances + cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_get_all_includes_build_request_cell0(self, mock_cm_get_all,
                                    mock_cell_mapping_get,
                                    mock_buildreq_get, mock_target_cell):

        build_req_instances = self._list_of_instances(2)
        build_reqs = [objects.BuildRequest(self.context, instance=instance)
                      for instance in build_req_instances]
        mock_buildreq_get.return_value = objects.BuildRequestList(self.context,
            objects=build_reqs)

        cell0_instances = self._list_of_instances(2)
        cell_instances = self._list_of_instances(2)

        cell_mapping = objects.CellMapping(uuid=objects.CellMapping.CELL0_UUID,
                                           name='0')
        mock_cell_mapping_get.return_value = cell_mapping
        mock_cm_get_all.return_value = [
            cell_mapping,
            objects.CellMapping(uuid=uuids.cell1, name='1'),
        ]
        cctxt = mock_target_cell.return_value.__enter__.return_value

        with mock.patch.object(self.compute_api,
                               '_get_instances_by_filters') as mock_inst_get:
            mock_inst_get.side_effect = [objects.InstanceList(
                                             self.context,
                                             objects=cell0_instances),
                                         objects.InstanceList(
                                             self.context,
                                             objects=cell_instances)]

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            if self.cell_type is None:
                for cm in mock_cm_get_all.return_value:
                    mock_target_cell.assert_any_call(self.context, cm)
            fields = ['metadata', 'info_cache', 'security_groups']
            inst_get_calls = [mock.call(cctxt, {'foo': 'bar'},
                                        limit=8, marker=None,
                                        fields=fields, sort_keys=['baz'],
                                        sort_dirs=['desc']),
                              mock.call(mock.ANY, {'foo': 'bar'},
                                        limit=6, marker=None,
                                        fields=fields, sort_keys=['baz'],
                                        sort_dirs=['desc'])
                              ]
            self.assertEqual(2, mock_inst_get.call_count)
            mock_inst_get.assert_has_calls(inst_get_calls)
            for i, instance in enumerate(build_req_instances +
                                         cell0_instances +
                                         cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(compute_api.API, '_get_instances_by_filters')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_tenant_to_project_conversion(self, mock_cell_map_get, mock_get,
                                          mock_buildreq_get):
        mock_cell_map_get.side_effect = exception.CellMappingNotFound(
                                                                uuid='fake')
        mock_get.return_value = objects.InstanceList(objects=[])
        api = compute_api.API()
        api.get_all(self.context, search_opts={'tenant_id': 'foo'})
        filters = mock_get.call_args_list[0][0][1]
        self.assertEqual({'project_id': 'foo'}, filters)

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters',
                       side_effect=exception.MarkerNotFound(
                           marker=uuids.marker))
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_get_all_cell0_marker_not_found(self, mock_cm_get_all,
                                            mock_cell_mapping_get,
                                            mock_buildreq_get,
                                            mock_target_cell):
        """Tests that we handle a MarkerNotFound raised from the cell0 database
        and continue looking for instances from the normal cell database.
        """

        cell_instances = self._list_of_instances(2)

        cell_mapping = objects.CellMapping(uuid=objects.CellMapping.CELL0_UUID,
                                           name='0')
        mock_cell_mapping_get.return_value = cell_mapping
        mock_cm_get_all.return_value = [
            cell_mapping,
            objects.CellMapping(uuid=uuids.cell1, name='1'),
        ]
        marker = uuids.marker
        cctxt = mock_target_cell.return_value.__enter__.return_value

        with mock.patch.object(self.compute_api,
                               '_get_instances_by_filters') as mock_inst_get:
            # simulate calling _get_instances_by_filters twice, once for cell0
            # which raises a MarkerNotFound and once from the cell DB which
            # returns two instances
            mock_inst_get.side_effect = [
                exception.MarkerNotFound(marker=marker),
                objects.InstanceList(self.context, objects=cell_instances)]

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker=marker, sort_keys=['baz'],
                sort_dirs=['desc'])

            if self.cell_type is None:
                for cm in mock_cm_get_all.return_value:
                    mock_target_cell.assert_any_call(self.context, cm)
            fields = ['metadata', 'info_cache', 'security_groups']
            inst_get_calls = [mock.call(cctxt, {'foo': 'bar'},
                                        limit=10, marker=marker,
                                        fields=fields, sort_keys=['baz'],
                                        sort_dirs=['desc']),
                              mock.call(mock.ANY, {'foo': 'bar'},
                                        limit=10, marker=marker,
                                        fields=fields, sort_keys=['baz'],
                                        sort_dirs=['desc'])
                              ]
            self.assertEqual(2, mock_inst_get.call_count)
            mock_inst_get.assert_has_calls(inst_get_calls)
            for i, instance in enumerate(cell_instances):
                self.assertEqual(instance, instances[i])


class ComputeAPIAPICellUnitTestCase(Cellsv1DeprecatedTestMixIn,
                                    _ComputeAPIUnitTestMixIn,
                                    test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIAPICellUnitTestCase, self).setUp()
        self.flags(cell_type='api', enable=True, group='cells')
        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.cell_type = 'api'

    def test_resize_same_flavor_fails(self):
        self.assertRaises(exception.CannotResizeToSameFlavor,
                          self._test_resize, same_flavor=True)

    @mock.patch.object(compute_cells_api, 'ComputeRPCAPIRedirect')
    def test_create_volume_bdm_call_reserve_dev_name(self, mock_reserve):
        instance = self._create_instance_obj()
        # In the cells rpcapi there isn't the call for the
        # reserve_block_device_name so the volume_bdm returned
        # by the _create_volume_bdm is None
        volume = {'id': '1', 'multiattach': False}
        result = self.compute_api._create_volume_bdm(self.context,
                                                     instance,
                                                     'vda',
                                                     volume,
                                                     None,
                                                     None)
        self.assertIsNone(result, None)

    @mock.patch.object(compute_cells_api.ComputeCellsAPI, '_call_to_cells')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    def test_attach_volume(self, mock_get_min_ver, mock_attach):
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))
        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            self.compute_api.attach_volume(
                self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_attach.assert_called_once_with(self.context, instance,
                                                'attach_volume', volume['id'],
                                                None, None, None)

    @mock.patch.object(compute_cells_api.ComputeCellsAPI, '_call_to_cells')
    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(cinder, 'is_microversion_supported')
    @mock.patch.object(objects.BlockDeviceMapping,
                              'get_by_volume_and_instance')
    def test_attach_volume_new_flow(self, mock_no_bdm,
                                    mock_cinder_mv_supported,
                                    mock_get_min_ver, mock_attach):
        mock_no_bdm.side_effect = exception.VolumeBDMNotFound(
                                        volume_id='test-vol')
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)

        mock_volume_api = mock.patch.object(self.compute_api, 'volume_api',
                                            mock.MagicMock(spec=cinder.API))

        with mock_volume_api as mock_v_api:
            mock_v_api.get.return_value = volume
            self.compute_api.attach_volume(
                self.context, instance, volume['id'])
            mock_v_api.check_availability_zone.assert_called_once_with(
                self.context, volume, instance=instance)
            mock_attach.assert_called_once_with(self.context, instance,
                                                'attach_volume', volume['id'],
                                                None, None, None)

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
    @mock.patch('nova.volume.cinder.API.get')
    def test_tagged_volume_attach(self, mock_vol_get, mock_get_min_ver):
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)
        mock_vol_get.return_value = volume
        self.assertRaises(exception.VolumeTaggedAttachNotSupported,
                          self.compute_api.attach_volume, self.context,
                          instance, volume['id'], tag='foo')

    @mock.patch.object(objects.Service, 'get_minimum_version',
                       return_value=COMPUTE_VERSION_NEW_ATTACH_FLOW)
    @mock.patch.object(cinder, 'is_microversion_supported')
    @mock.patch.object(objects.BlockDeviceMapping,
                              'get_by_volume_and_instance')
    @mock.patch('nova.volume.cinder.API.get')
    def test_tagged_volume_attach_new_flow(self, mock_get_vol, mock_no_bdm,
                                           mock_cinder_mv_supported,
                                           mock_get_min_ver):
        mock_no_bdm.side_effect = exception.VolumeBDMNotFound(
                                        volume_id='test-vol')
        instance = self._create_instance_obj()
        volume = fake_volume.fake_volume(1, 'test-vol', 'test-vol',
                                         None, None, None, None, None)
        mock_get_vol.return_value = volume
        self.assertRaises(exception.VolumeTaggedAttachNotSupported,
                          self.compute_api.attach_volume, self.context,
                          instance, volume['id'], tag='foo')

    def test_create_with_networks_max_count_none(self):
        self.skipTest("This test does not test any rpcapi.")

    def test_attach_volume_reserve_fails(self):
        self.skipTest("Reserve is never done in the API cell.")

    def test_attach_volume_attachment_create_fails(self):
        self.skipTest("Reserve is never done in the API cell.")

    def test_check_requested_networks_no_requested_networks(self):
        # The API cell just returns the number of instances passed in since the
        # actual validation happens in the child (compute) cell.
        self.assertEqual(
            2, self.compute_api._check_requested_networks(
                self.context, None, 2))

    def test_check_requested_networks_auto_allocate(self):
        # The API cell just returns the number of instances passed in since the
        # actual validation happens in the child (compute) cell.
        requested_networks = (
            objects.NetworkRequestList(
                objects=[objects.NetworkRequest(network_id='auto')]))
        count = self.compute_api._check_requested_networks(
            self.context, requested_networks, 5)
        self.assertEqual(5, count)

    def test_attach_volume_with_multiattach_volume_fails(self):
        """Tests that the cells v1 API doesn't support attaching multiattach
        volumes.
        """
        instance = objects.Instance(cell_name='foo')
        volume = {'multiattach': True}
        device = disk_bus = disk_type = None
        self.assertRaises(exception.MultiattachSupportNotYetAvailable,
                          self.compute_api._attach_volume, self.context,
                          instance, volume, device, disk_bus, disk_type)


class ComputeAPIComputeCellUnitTestCase(Cellsv1DeprecatedTestMixIn,
                                        _ComputeAPIUnitTestMixIn,
                                        test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIComputeCellUnitTestCase, self).setUp()
        self.flags(cell_type='compute', enable=True, group='cells')
        self.compute_api = compute_api.API()
        self.cell_type = 'compute'

    def test_resize_same_flavor_passes(self):
        self._test_resize(same_flavor=True)


class DiffDictTestCase(test.NoDBTestCase):
    """Unit tests for _diff_dict()."""

    def test_no_change(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=2, c=3)
        diff = compute_api._diff_dict(old, new)

        self.assertEqual(diff, {})

    def test_new_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=2, c=3, d=4)
        diff = compute_api._diff_dict(old, new)

        self.assertEqual(diff, dict(d=['+', 4]))

    def test_changed_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=4, c=3)
        diff = compute_api._diff_dict(old, new)

        self.assertEqual(diff, dict(b=['+', 4]))

    def test_removed_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, c=3)
        diff = compute_api._diff_dict(old, new)

        self.assertEqual(diff, dict(b=['-']))


class SecurityGroupAPITest(test.NoDBTestCase):
    def setUp(self):
        super(SecurityGroupAPITest, self).setUp()
        self.secgroup_api = compute_api.SecurityGroupAPI()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def test_get_instance_security_groups(self):
        groups = objects.SecurityGroupList()
        groups.objects = [objects.SecurityGroup(name='foo'),
                          objects.SecurityGroup(name='bar')]
        instance = objects.Instance(security_groups=groups)
        names = self.secgroup_api.get_instance_security_groups(self.context,
                                                               instance)
        self.assertEqual(sorted([{'name': 'bar'}, {'name': 'foo'}], key=str),
                         sorted(names, key=str))

    @mock.patch('nova.objects.security_group.make_secgroup_list')
    def test_populate_security_groups(self, mock_msl):
        r = self.secgroup_api.populate_security_groups([mock.sentinel.group])
        mock_msl.assert_called_once_with([mock.sentinel.group])
        self.assertEqual(r, mock_msl.return_value)
