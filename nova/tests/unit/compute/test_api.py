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
import fixtures
import iso8601
import mock
import os_traits as ot
from oslo_messaging import exceptions as oslo_exceptions
from oslo_serialization import jsonutils
from oslo_utils import fixture as utils_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six

from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
import nova.conf
from nova import context
from nova.db import api as db
from nova import exception
from nova.image import glance as image_api
from nova.network import constants
from nova.network import model
from nova.network import neutron as neutron_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import fields as fields_obj
from nova.objects import image_meta as image_meta_obj
from nova.objects import quotas as quotas_obj
from nova.objects import security_group as secgroup_obj
from nova.servicegroup import api as servicegroup_api
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_build_request
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_request_spec
from nova.tests.unit import fake_volume
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_flavor
from nova.tests.unit.objects import test_migration
from nova import utils
from nova.volume import cinder


CONF = nova.conf.CONF

FAKE_IMAGE_REF = 'fake-image-ref'
NODENAME = 'fakenode1'
SHELVED_IMAGE = 'fake-shelved-image'
SHELVED_IMAGE_NOT_FOUND = 'fake-shelved-image-notfound'
SHELVED_IMAGE_NOT_AUTHORIZED = 'fake-shelved-image-not-authorized'
SHELVED_IMAGE_EXCEPTION = 'fake-shelved-image-exception'


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

        expected_attrs = None
        if 'extra_specs' in updates and updates['extra_specs']:
            expected_attrs = ['extra_specs']

        return objects.Flavor._from_db_object(
            self.context, objects.Flavor(extra_specs={}), flavor,
            expected_attrs=expected_attrs)

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
        instance.numa_topology = None

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
                               'create_resource_requests',
                               return_value=(None, [])):
            self.compute_api.create(self.context, instance_type, 'image_id',
                                    requested_networks=requested_networks,
                                    max_count=None)

    @mock.patch('nova.objects.Quotas.get_all_by_project_and_user',
                new=mock.MagicMock())
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

    @mock.patch('nova.objects.Quotas.limit_check')
    def test_create_volume_backed_instance_with_trusted_certs(self,
                                                              check_limit):
        # Creating an instance with no image_ref specified will result in
        # creating a volume-backed instance
        self.assertRaises(exception.CertificateValidationFailed,
                          self.compute_api.create, self.context,
                          instance_type=self._create_flavor(), image_href=None,
                          trusted_certs=['test-cert-1', 'test-cert-2'])

    @mock.patch('nova.objects.Quotas.limit_check')
    def test_create_volume_backed_instance_with_conf_trusted_certs(
            self, check_limit):
        self.flags(verify_glance_signatures=True, group='glance')
        self.flags(enable_certificate_validation=True, group='glance')
        self.flags(default_trusted_certificate_ids=['certs'], group='glance')
        # Creating an instance with no image_ref specified will result in
        # creating a volume-backed instance
        self.assertRaises(exception.CertificateValidationFailed,
                          self.compute_api.create, self.context,
                          instance_type=self._create_flavor(),
                          image_href=None)

    def _test_create_max_net_count(self, max_net_count, min_count, max_count):
        with test.nested(
            mock.patch.object(self.compute_api, '_get_image',
                              return_value=(None, {})),
            mock.patch.object(self.compute_api, '_check_auto_disk_config'),
            mock.patch.object(self.compute_api,
                              '_validate_and_build_base_options',
                              return_value=({}, max_net_count, None,
                                            ['default'], None))
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

    def test_specified_port_and_multiple_instances(self):
        # Tests that if port is specified there is only one instance booting
        # (i.e max_count == 1) as we can't share the same port across multiple
        # instances.
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

    # TODO(huaqiang): Remove in Wallaby
    @mock.patch('nova.compute.api.API._check_requested_networks',
                new=mock.Mock(return_value=1))
    @mock.patch('nova.virt.hardware.get_pci_numa_policy_constraint',
                return_value=None)
    def test_create_mixed_instance_compute_version_fail(self, mock_pci):
        """Ensure a 'MixedInstanceNotSupportByComputeService' exception raises
        when all 'nova-compute' nodes have not been upgraded to or after
        Victoria.
        """
        extra_specs = {
            "hw:cpu_policy": "mixed",
            "hw:cpu_dedicated_mask": "^3"
        }
        flavor = self._create_flavor(vcpus=4, extra_specs=extra_specs)

        self.assertRaises(exception.MixedInstanceNotSupportByComputeService,
                          self.compute_api.create, self.context, flavor,
                          image_href=None)
        # Ensure the exception is raised right after the call of
        # '_validate_and_build_base_options's since
        # 'get_pci_numa_policy_constraint' is only called in this method.
        mock_pci.assert_called_once()

    @mock.patch('nova.objects.BlockDeviceMapping.save')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    def test_create_volume_bdm_call_reserve_dev_name(self, mock_reserve,
                                                     mock_bdm_save):
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
        mock_bdm_save.assert_called_once_with()

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
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume_new_flow(self, mock_attach, mock_bdm,
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
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_tagged_volume_attach_new_flow(self, mock_attach, mock_bdm,
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

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'reserve_block_device_name')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'attach_volume')
    def test_attach_volume_attachment_create_fails(self, mock_attach, mock_bdm,
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
            expected_task_state = task_states.ALLOW_REBOOT

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

    def _set_delete_shelved_part(self, inst, mock_image_delete):
        snapshot_id = inst.system_metadata.get('shelved_image_id')
        if snapshot_id == SHELVED_IMAGE:
            mock_image_delete.return_value = True
        elif snapshot_id == SHELVED_IMAGE_NOT_FOUND:
            mock_image_delete.side_effect = exception.ImageNotFound(
                image_id=snapshot_id)
        elif snapshot_id == SHELVED_IMAGE_NOT_AUTHORIZED:
            mock_image_delete.side_effect = exception.ImageNotAuthorized(
                image_id=snapshot_id)
        elif snapshot_id == SHELVED_IMAGE_EXCEPTION:
            mock_image_delete.side_effect = test.TestingException(
                "Unexpected error")

        return snapshot_id

    @mock.patch.object(compute_utils,
                       'notify_about_instance_action')
    @mock.patch.object(objects.Migration, 'get_by_instance_and_status')
    @mock.patch.object(image_api.API, 'delete')
    @mock.patch.object(objects.InstanceMapping, 'save')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(compute_utils,
                       'notify_about_instance_usage')
    @mock.patch.object(db, 'instance_destroy')
    @mock.patch.object(db, 'instance_system_metadata_get')
    @mock.patch.object(neutron_api.API, 'deallocate_for_instance')
    @mock.patch.object(db, 'instance_update_and_get_original')
    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(servicegroup_api.API, 'service_is_up')
    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(context.RequestContext, 'elevated')
    @mock.patch.object(objects.BlockDeviceMappingList,
                       'get_by_instance_uuid', return_value=[])
    @mock.patch.object(objects.Instance, 'save')
    def _test_delete(self, delete_type, mock_save, mock_bdm_get, mock_elevated,
                     mock_get_cn, mock_up, mock_record, mock_inst_update,
                     mock_deallocate, mock_inst_meta, mock_inst_destroy,
                     mock_notify_legacy, mock_get_inst,
                     mock_save_im, mock_image_delete, mock_mig_get,
                     mock_notify, **attrs):
        expected_save_calls = [mock.call()]
        expected_record_calls = []
        expected_elevated_calls = []
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
        rpcapi = self.compute_api.compute_rpcapi
        mock_confirm = self.useFixture(
            fixtures.MockPatchObject(rpcapi, 'confirm_resize')).mock

        def _reset_task_state(context, instance, migration, src_host,
                              cast=False):
            inst.update({'task_state': None})

        # After confirm resize action, instance task_state is reset to None
        mock_confirm.side_effect = _reset_task_state

        is_shelved = inst.vm_state in (vm_states.SHELVED,
                                       vm_states.SHELVED_OFFLOADED)
        if is_shelved:
            snapshot_id = self._set_delete_shelved_part(inst,
                                                        mock_image_delete)

        mock_terminate = self.useFixture(
            fixtures.MockPatchObject(rpcapi, 'terminate_instance')).mock
        mock_soft_delete = self.useFixture(
            fixtures.MockPatchObject(rpcapi, 'soft_delete_instance')).mock

        if inst.task_state == task_states.RESIZE_FINISH:
            self._test_delete_resizing_part(inst, deltas)

        # NOTE(comstud): This is getting messy.  But what we are wanting
        # to test is:
        # * Check for downed host
        # * If downed host:
        #   * Clean up instance, destroying it, sending notifications.
        #     (Tested in _test_downed_host_part())
        # * If not downed host:
        #   * Record the action start.
        #   * Cast to compute_rpcapi.<method>

        cast = True
        is_downed_host = inst.host == 'down-host' or inst.host is None
        if inst.vm_state == vm_states.RESIZED:
            migration = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())
            mock_elevated.return_value = self.context
            expected_elevated_calls.append(mock.call())
            mock_mig_get.return_value = migration
            expected_record_calls.append(
                mock.call(self.context, inst,
                          instance_actions.CONFIRM_RESIZE))

            # After confirm resize action, instance task_state
            # is reset to None, so is the expected value. But
            # for soft delete, task_state will be again reset
            # back to soft-deleting in the code to avoid status
            # checking failure.
            updates['task_state'] = None
            if delete_type == 'soft_delete':
                expected_save_calls.append(mock.call())
                updates['task_state'] = 'soft-deleting'

        if inst.host is not None:
            mock_elevated.return_value = self.context
            expected_elevated_calls.append(mock.call())
            mock_get_cn.return_value = objects.Service()
            mock_up.return_value = (inst.host != 'down-host')

        if is_downed_host:
            mock_elevated.return_value = self.context
            expected_elevated_calls.append(mock.call())
            expected_save_calls.append(mock.call())
            state = ('soft' in delete_type and vm_states.SOFT_DELETED or
                     vm_states.DELETED)
            updates.update({'vm_state': state,
                            'task_state': None,
                            'terminated_at': delete_time,
                            'deleted_at': delete_time,
                            'deleted': True})
            fake_inst = fake_instance.fake_db_instance(**updates)
            mock_inst_destroy.return_value = fake_inst
            cell = objects.CellMapping(uuid=uuids.cell,
                                       transport_url='fake://',
                                       database_connection='fake://')
            im = objects.InstanceMapping(cell_mapping=cell)
            mock_get_inst.return_value = im
            cast = False

        if cast:
            expected_record_calls.append(mock.call(self.context, inst,
                                                   instance_actions.DELETE))

        # NOTE(takashin): If objects.Instance.destroy() is called,
        # objects.Instance.uuid (inst.uuid) and host (inst.host) are changed.
        # So preserve them before calling the method to test.
        instance_uuid = inst.uuid
        instance_host = inst.host
        getattr(self.compute_api, delete_type)(self.context, inst)
        for k, v in updates.items():
            self.assertEqual(inst[k], v)

        mock_save.assert_has_calls(expected_save_calls)
        mock_bdm_get.assert_called_once_with(self.context, instance_uuid)

        if expected_record_calls:
            mock_record.assert_has_calls(expected_record_calls)
        if expected_elevated_calls:
            mock_elevated.assert_has_calls(expected_elevated_calls)

        if inst.vm_state == vm_states.RESIZED:
            mock_mig_get.assert_called_once_with(
                self.context, instance_uuid, 'finished')
            mock_confirm.assert_called_once_with(
                self.context, inst, migration, migration['source_compute'],
                cast=False)
        if instance_host is not None:
            mock_get_cn.assert_called_once_with(self.context,
                                                instance_host)
            mock_up.assert_called_once_with(
                test.MatchType(objects.Service))
        if is_downed_host:
            if 'soft' in delete_type:
                mock_notify_legacy.assert_has_calls([
                    mock.call(self.compute_api.notifier, self.context,
                              inst, 'delete.start'),
                    mock.call(self.compute_api.notifier, self.context,
                              inst, 'delete.end')])
            else:
                mock_notify_legacy.assert_has_calls([
                    mock.call(self.compute_api.notifier, self.context,
                              inst, '%s.start' % delete_type),
                    mock.call(self.compute_api.notifier, self.context,
                              inst, '%s.end' % delete_type)])
            mock_deallocate.assert_called_once_with(self.context, inst)
            mock_inst_destroy.assert_called_once_with(
                self.context, instance_uuid, constraint=None,
                hard_delete=False)
            mock_get_inst.assert_called_with(self.context, instance_uuid)
            self.assertEqual(2, mock_get_inst.call_count)
            self.assertTrue(mock_get_inst.return_value.queued_for_delete)
            mock_save_im.assert_called_once_with()

        if cast:
            if delete_type == 'soft_delete':
                mock_soft_delete.assert_called_once_with(self.context, inst)
            elif delete_type in ['delete', 'force_delete']:
                mock_terminate.assert_called_once_with(
                    self.context, inst, [])

        if is_shelved:
            mock_image_delete.assert_called_once_with(self.context,
                                                      snapshot_id)
        if not cast and delete_type == 'delete':
            mock_notify.assert_has_calls([
                mock.call(self.context, inst, host='fake-mini',
                          source='nova-api',
                          action=delete_type, phase='start'),
                mock.call(self.context, inst, host='fake-mini',
                          source='nova-api',
                          action=delete_type, phase='end')])

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

    def test_delete_soft_in_resized(self):
        self._test_delete('soft_delete', vm_state=vm_states.RESIZED)

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
            mock_service_get.assert_called_once_with(
                    mock_elevated.return_value, 'fake-host')
            mock_service_up.assert_called_once_with(
                    mock_service_get.return_value)
            mock_terminate.assert_called_once_with(
                    self.context, inst, mock_bdm_get.return_value)
            mock_local_delete.assert_not_called()

    def test_delete_forced_when_task_state_is_not_none(self):
        for vm_state in self._get_vm_states():
            self._test_delete('force_delete', vm_state=vm_state,
                              task_state=task_states.RESIZE_MIGRATING)

    @mock.patch.object(compute_utils, 'notify_about_instance_action')
    @mock.patch.object(compute_utils, 'notify_about_instance_usage')
    @mock.patch.object(db, 'instance_destroy')
    @mock.patch.object(db, 'constraint')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_delete_fast_if_host_not_set(self, mock_br_get, mock_save,
                                         mock_bdm_get, mock_cons,
                                         mock_inst_destroy,
                                         mock_notify_legacy, mock_notify):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()
        inst.host = ''
        updates = {'progress': 0, 'task_state': task_states.DELETING}

        mock_lookup = self.useFixture(
            fixtures.MockPatchObject(self.compute_api,
                                     '_lookup_instance')).mock

        mock_lookup.return_value = (None, inst)
        mock_bdm_get.return_value = objects.BlockDeviceMappingList()
        mock_br_get.side_effect = exception.BuildRequestNotFound(
            uuid=inst.uuid)

        mock_cons.return_value = 'constraint'
        delete_time = datetime.datetime(1955, 11, 5, 9, 30,
                                        tzinfo=iso8601.UTC)
        updates['deleted_at'] = delete_time
        updates['deleted'] = True
        fake_inst = fake_instance.fake_db_instance(**updates)
        mock_inst_destroy.return_value = fake_inst

        instance_uuid = inst.uuid
        self.compute_api.delete(self.context, inst)

        for k, v in updates.items():
            self.assertEqual(inst[k], v)

        mock_lookup.assert_called_once_with(self.context, instance_uuid)
        mock_bdm_get.assert_called_once_with(self.context, instance_uuid)
        mock_br_get.assert_called_once_with(self.context, instance_uuid)
        mock_save.assert_called_once_with()

        mock_notify_legacy.assert_has_calls([
            mock.call(self.compute_api.notifier, self.context,
                      inst, 'delete.start'),
            mock.call(self.compute_api.notifier, self.context,
                      inst, 'delete.end')])
        mock_notify.assert_has_calls([
            mock.call(self.context, inst, host='fake-mini',
                      source='nova-api', action='delete', phase='start'),
            mock.call(self.context, inst, host='fake-mini',
                      source='nova-api', action='delete', phase='end')])

        mock_cons.assert_called_once_with(host=mock.ANY)
        mock_inst_destroy.assert_called_once_with(
            self.context, instance_uuid, constraint='constraint',
            hard_delete=False)

    def _fake_do_delete(context, instance, bdms,
                        rservations=None, local=False):
        pass

    @mock.patch.object(compute_utils, 'notify_about_instance_action')
    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    @mock.patch.object(cinder.API, 'detach')
    @mock.patch.object(compute_utils, 'notify_about_instance_usage')
    @mock.patch.object(neutron_api.API, 'deallocate_for_instance')
    @mock.patch.object(context.RequestContext, 'elevated')
    @mock.patch.object(objects.Instance, 'destroy')
    def test_local_delete_with_deleted_volume(
            self, mock_inst_destroy, mock_elevated, mock_dealloc,
            mock_notify_legacy, mock_detach, mock_bdm_destroy, mock_notify):
        bdms = [objects.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 42, 'volume_id': 'volume_id',
                 'source_type': 'volume', 'destination_type': 'volume',
                 'delete_on_termination': False}))]

        inst = self._create_instance_obj()
        inst._context = self.context
        mock_elevated.return_value = self.context
        mock_detach.side_effect = exception.VolumeNotFound('volume_id')

        self.compute_api._local_delete(self.context, inst, bdms,
                                       'delete',
                                       self._fake_do_delete)

        mock_notify_legacy.assert_has_calls([
            mock.call(self.compute_api.notifier, self.context,
                      inst, 'delete.start'),
            mock.call(self.compute_api.notifier, self.context,
                      inst, 'delete.end')])
        mock_notify.assert_has_calls([
            mock.call(self.context, inst, host='fake-mini', source='nova-api',
                      action='delete', phase='start'),
            mock.call(self.context, inst, host='fake-mini', source='nova-api',
                      action='delete', phase='end')])

        mock_elevated.assert_has_calls([mock.call(), mock.call()])
        mock_detach.assert_called_once_with(mock.ANY, 'volume_id', inst.uuid)
        mock_bdm_destroy.assert_called_once_with()
        mock_inst_destroy.assert_called_once_with()

        mock_dealloc.assert_called_once_with(self.context, inst)

    @mock.patch.object(compute_utils, 'notify_about_instance_action')
    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    @mock.patch.object(cinder.API, 'detach')
    @mock.patch.object(compute_utils, 'notify_about_instance_usage')
    @mock.patch.object(neutron_api.API, 'deallocate_for_instance')
    @mock.patch.object(context.RequestContext, 'elevated')
    @mock.patch.object(objects.Instance, 'destroy')
    @mock.patch.object(compute_utils, 'delete_arqs_if_needed')
    def test_local_delete_for_arqs(
            self, mock_del_arqs, mock_inst_destroy, mock_elevated,
            mock_dealloc, mock_notify_legacy, mock_detach,
            mock_bdm_destroy, mock_notify):
        inst = self._create_instance_obj()
        inst._context = self.context
        mock_elevated.return_value = self.context
        bdms = []
        self.compute_api._local_delete(self.context, inst, bdms,
                                       'delete', self._fake_do_delete)
        mock_del_arqs.assert_called_once_with(self.context, inst)

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

    def test_delete_disabled(self):
        # If 'disable_terminate' is True, log output is executed only and
        # just return immediately.
        inst = self._create_instance_obj()
        inst.disable_terminate = True
        self.compute_api.delete(self.context, inst)

    @mock.patch.object(objects.Instance, 'save',
                       side_effect=test.TestingException)
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid',
                       return_value=objects.BlockDeviceMappingList())
    def test_delete_soft_rollback(self, mock_get, mock_save):
        inst = self._create_instance_obj()

        delete_time = datetime.datetime(1955, 11, 5)
        self.useFixture(utils_fixture.TimeFixture(delete_time))

        self.assertRaises(test.TestingException,
                          self.compute_api.soft_delete, self.context, inst)
        mock_get.assert_called_once_with(self.context, inst.uuid)
        mock_save.assert_called_once_with()

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

    def test_delete_while_booting_buildreq_not_deleted(self):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        inst = self._create_instance_obj()
        with mock.patch.object(self.compute_api,
                               '_attempt_delete_of_buildrequest',
                               return_value=False):
            self.assertFalse(
                self.compute_api._delete_while_booting(self.context, inst))

    def test_delete_while_booting_buildreq_deleted_instance_none(self):
        self.useFixture(nova_fixtures.AllServicesCurrent())
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
        self.useFixture(nova_fixtures.AllServicesCurrent())
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
            expected_cell = inst_map.cell_mapping
            self.assertEqual((expected_cell, instance),
                             (cell, ret_instance))
            mock_inst_get.assert_called_once_with(self.context, instance.uuid)
            mock_target_cell.assert_called_once_with(self.context,
                                                     inst_map.cell_mapping)

        test()

    @mock.patch('nova.compute.api.API._get_source_compute_service')
    @mock.patch('nova.servicegroup.api.API.service_is_up', return_value=True)
    @mock.patch.object(objects.Migration, 'save')
    @mock.patch.object(objects.Migration, 'get_by_instance_and_status')
    @mock.patch.object(context.RequestContext, 'elevated')
    def _test_confirm_resize(self, mock_elevated, mock_get, mock_save,
                             mock_service_is_up, mock_get_service,
                             mig_ref_passed=False):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_mig = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())

        mock_record = self.useFixture(
            fixtures.MockPatchObject(self.compute_api,
                                     '_record_action_start')).mock
        mock_confirm = self.useFixture(
            fixtures.MockPatchObject(self.compute_api.compute_rpcapi,
                                     'confirm_resize')).mock

        mock_elevated.return_value = self.context
        if not mig_ref_passed:
            mock_get.return_value = fake_mig

        def _check_mig(expected_task_state=None):
            self.assertEqual('confirming', fake_mig.status)

        mock_save.side_effect = _check_mig

        if mig_ref_passed:
            self.compute_api.confirm_resize(self.context, fake_inst,
                                            migration=fake_mig)
        else:
            self.compute_api.confirm_resize(self.context, fake_inst)

        mock_elevated.assert_called_once_with()
        mock_service_is_up.assert_called_once_with(
            mock_get_service.return_value)
        mock_save.assert_called_once_with()
        mock_record.assert_called_once_with(self.context, fake_inst,
                                            'confirmResize')
        mock_confirm.assert_called_once_with(self.context, fake_inst, fake_mig,
                                             'compute-source')

        if not mig_ref_passed:
            mock_get.assert_called_once_with(self.context, fake_inst['uuid'],
                                             'finished')

    def test_confirm_resize(self):
        self._test_confirm_resize()

    def test_confirm_resize_with_migration_ref(self):
        self._test_confirm_resize(mig_ref_passed=True)

    @mock.patch('nova.objects.HostMapping.get_by_host',
                return_value=objects.HostMapping(
                    cell_mapping=objects.CellMapping(
                        database_connection='fake://', transport_url='none://',
                        uuid=uuids.cell_uuid)))
    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_get_source_compute_service(self, mock_service_get, mock_hm_get):
        # First start with a same-cell migration.
        migration = objects.Migration(source_compute='source.host',
                                      cross_cell_move=False)
        self.compute_api._get_source_compute_service(self.context, migration)
        mock_hm_get.assert_not_called()
        mock_service_get.assert_called_once_with(self.context, 'source.host')
        # Make sure the context was not targeted.
        ctxt = mock_service_get.call_args[0][0]
        self.assertIsNone(ctxt.cell_uuid)

        # Now test with a cross-cell migration.
        mock_service_get.reset_mock()
        migration.cross_cell_move = True
        self.compute_api._get_source_compute_service(self.context, migration)
        mock_hm_get.assert_called_once_with(self.context, 'source.host')
        mock_service_get.assert_called_once_with(
            test.MatchType(context.RequestContext), 'source.host')
        # Make sure the context was targeted.
        ctxt = mock_service_get.call_args[0][0]
        self.assertEqual(uuids.cell_uuid, ctxt.cell_uuid)

    @mock.patch('nova.virt.hardware.numa_get_constraints')
    @mock.patch('nova.network.neutron.API.get_requested_resource_for_instance',
                return_value=[])
    @mock.patch('nova.availability_zones.get_host_availability_zone',
                return_value='nova')
    @mock.patch('nova.objects.Quotas.check_deltas')
    @mock.patch('nova.objects.Migration.get_by_instance_and_status')
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.RequestSpec.get_by_instance_uuid')
    def _test_revert_resize(
            self, mock_get_reqspec, mock_elevated, mock_get_migration,
            mock_check, mock_get_host_az, mock_get_requested_resources,
            mock_get_numa, same_flavor):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_inst.info_cache.network_info = model.NetworkInfo([
            model.VIF(id=uuids.port1, profile={'allocation': uuids.rp})])
        fake_mig = objects.Migration._from_db_object(
                self.context, objects.Migration(),
                test_migration.fake_db_migration())
        fake_reqspec = objects.RequestSpec()
        fake_reqspec.flavor = fake_inst.flavor
        fake_numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=0, cpuset=set([0]), pcpuset=set(), memory=512,
                pagesize=None,
                cpu_pinning_raw=None, cpuset_reserved=None, cpu_policy=None,
                cpu_thread_policy=None)])

        if same_flavor:
            fake_inst.old_flavor = fake_inst.flavor
        else:
            fake_inst.old_flavor = self._create_flavor(
                id=200, flavorid='new-flavor-id', name='new_flavor',
                disabled=False, extra_specs={'hw:numa_nodes': '1'})

        mock_elevated.return_value = self.context
        mock_get_migration.return_value = fake_mig
        mock_get_reqspec.return_value = fake_reqspec
        mock_get_numa.return_value = fake_numa_topology

        def _check_reqspec():
            if same_flavor:
                assert_func = self.assertNotEqual
            else:
                assert_func = self.assertEqual

            assert_func(fake_numa_topology, fake_reqspec.numa_topology)
            assert_func(fake_inst.old_flavor, fake_reqspec.flavor)

        def _check_state(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_REVERTING,
                             fake_inst.task_state)

        def _check_mig():
            self.assertEqual('reverting', fake_mig.status)

        with test.nested(
            mock.patch.object(fake_reqspec, 'save',
                              side_effect=_check_reqspec),
            mock.patch.object(fake_inst, 'save', side_effect=_check_state),
            mock.patch.object(fake_mig, 'save', side_effect=_check_mig),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi, 'revert_resize')
        ) as (mock_reqspec_save, mock_inst_save, mock_mig_save,
              mock_record_action, mock_revert_resize):
            self.compute_api.revert_resize(self.context, fake_inst)

            mock_elevated.assert_called_once_with()
            mock_get_migration.assert_called_once_with(
                self.context, fake_inst['uuid'], 'finished')
            mock_inst_save.assert_called_once_with(expected_task_state=[None])
            mock_mig_save.assert_called_once_with()
            mock_get_reqspec.assert_called_once_with(
                self.context, fake_inst.uuid)
            if same_flavor:
                # if we are not changing flavors through the revert, we
                # shouldn't attempt to rebuild the NUMA topology since it won't
                # have changed
                mock_get_numa.assert_not_called()
            else:
                # not so if the flavor *has* changed though
                mock_get_numa.assert_called_once_with(
                    fake_inst.old_flavor, mock.ANY)
            mock_record_action.assert_called_once_with(self.context, fake_inst,
                                                       'revertResize')
            mock_revert_resize.assert_called_once_with(
                self.context, fake_inst, fake_mig, 'compute-dest',
                mock_get_reqspec.return_value)
            mock_get_requested_resources.assert_called_once_with(
                self.context, fake_inst.uuid)
            self.assertEqual(
                [],
                mock_get_reqspec.return_value.requested_resources)

    def test_revert_resize(self):
        self._test_revert_resize(same_flavor=False)

    def test_revert_resize_same_flavor(self):
        """Test behavior when reverting a migration or a resize to the same
        flavor.
        """
        self._test_revert_resize(same_flavor=True)

    @mock.patch('nova.network.neutron.API.get_requested_resource_for_instance')
    @mock.patch('nova.availability_zones.get_host_availability_zone',
                return_value='nova')
    @mock.patch('nova.objects.Quotas.check_deltas')
    @mock.patch('nova.objects.Migration.get_by_instance_and_status')
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.RequestSpec')
    def test_revert_resize_concurrent_fail(
            self, mock_reqspec, mock_elevated, mock_get_migration, mock_check,
            mock_get_host_az, mock_get_requested_resources):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_inst.info_cache.network_info = model.NetworkInfo([])
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
            mock_get_requested_resources.assert_not_called()

    # TODO(stephenfin): This is a terrible, terrible function and should be
    # broken up into its constituent parts
    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch('nova.virt.hardware.numa_get_constraints')
    @mock.patch('nova.compute.api.API._allow_resize_to_same_host')
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.compute.api.API._validate_flavor_image_nostatus')
    @mock.patch('nova.objects.Migration')
    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(quotas_obj.Quotas, 'limit_check_project_and_user')
    @mock.patch.object(quotas_obj.Quotas, 'count_as_dict')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_utils, 'upsize_quota_delta')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def _test_resize(self, mock_get_all_by_host,
                     mock_get_by_instance_uuid, mock_get_flavor, mock_upsize,
                     mock_inst_save, mock_count, mock_limit, mock_record,
                     mock_migration, mock_validate, mock_is_vol_backed,
                     mock_allow_resize_to_same_host,
                     mock_get_numa,
                     flavor_id_passed=True,
                     same_host=False, allow_same_host=False,
                     project_id=None,
                     same_flavor=False,
                     clean_shutdown=True,
                     host_name=None,
                     request_spec=True,
                     requested_destination=False,
                     allow_cross_cell_resize=False):

        self.flags(allow_resize_to_same_host=allow_same_host)
        mock_allow_resize_to_same_host.return_value = allow_same_host

        params = {}
        if project_id is not None:
            # To test instance w/ different project id than context (admin)
            params['project_id'] = project_id
        fake_inst = self._create_instance_obj(params=params)
        fake_numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=0, cpuset=set([0]), pcpuset=set(), memory=512,
                pagesize=None,
                cpu_pinning_raw=None, cpuset_reserved=None, cpu_policy=None,
                cpu_thread_policy=None)])

        mock_resize = self.useFixture(
            fixtures.MockPatchObject(self.compute_api.compute_task_api,
                                     'resize_instance')).mock
        mock_get_numa.return_value = fake_numa_topology

        if host_name:
            mock_get_all_by_host.return_value = [objects.ComputeNode(
                host=host_name, hypervisor_hostname='hypervisor_host')]

        current_flavor = fake_inst.get_flavor()
        if flavor_id_passed:
            new_flavor = self._create_flavor(
                id=200, flavorid='new-flavor-id', name='new_flavor',
                disabled=False, extra_specs={'hw:numa_nodes': '1'})
            if same_flavor:
                new_flavor.id = current_flavor.id
            mock_get_flavor.return_value = new_flavor
        else:
            new_flavor = current_flavor

        if not (flavor_id_passed and same_flavor):
            project_id, user_id = quotas_obj.ids_from_instance(self.context,
                                                               fake_inst)
            if flavor_id_passed:
                mock_upsize.return_value = {'cores': 0, 'ram': 0}

                proj_count = {'instances': 1, 'cores': current_flavor.vcpus,
                              'ram': current_flavor.memory_mb}
                user_count = proj_count.copy()
                mock_count.return_value = {'project': proj_count,
                                           'user': user_count}

            def _check_state(expected_task_state=None):
                self.assertEqual(task_states.RESIZE_PREP,
                                 fake_inst.task_state)
                self.assertEqual(fake_inst.progress, 0)

            mock_inst_save.side_effect = _check_state

            if allow_same_host:
                filter_properties = {'ignore_hosts': []}
            else:
                filter_properties = {'ignore_hosts': [fake_inst['host']]}

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

        mock_allow_cross_cell_resize = self.useFixture(
            fixtures.MockPatchObject(
                self.compute_api, '_allow_cross_cell_resize')).mock
        mock_allow_cross_cell_resize.return_value = allow_cross_cell_resize

        if flavor_id_passed:
            self.compute_api.resize(self.context, fake_inst,
                                    flavor_id='new-flavor-id',
                                    clean_shutdown=clean_shutdown,
                                    host_name=host_name)
        else:
            if request_spec:
                self.compute_api.resize(self.context, fake_inst,
                                        clean_shutdown=clean_shutdown,
                                        host_name=host_name)
            else:
                self.assertRaises(exception.RequestSpecNotFound,
                                  self.compute_api.resize,
                                  self.context, fake_inst,
                                  clean_shutdown=clean_shutdown,
                                  host_name=host_name)

        if request_spec:
            if allow_same_host:
                self.assertEqual([], fake_spec.ignore_hosts)
            else:
                self.assertEqual([fake_inst['host']], fake_spec.ignore_hosts)

            if host_name is None:
                self.assertIsNotNone(fake_spec.requested_destination)
            else:
                self.assertIn('host', fake_spec.requested_destination)
                self.assertEqual(host_name,
                                 fake_spec.requested_destination.host)
                self.assertIn('node', fake_spec.requested_destination)
                self.assertEqual('hypervisor_host',
                                 fake_spec.requested_destination.node)
            self.assertEqual(
                allow_cross_cell_resize,
                fake_spec.requested_destination.allow_cross_cell_move)
            mock_allow_resize_to_same_host.assert_called_once()

            if flavor_id_passed and not same_flavor:
                mock_get_numa.assert_called_once_with(new_flavor, mock.ANY)
            else:
                mock_get_numa.assert_not_called()

        if host_name:
            mock_get_all_by_host.assert_called_once_with(
                self.context, host_name, True)

        if flavor_id_passed:
            mock_get_flavor.assert_called_once_with('new-flavor-id',
                                                    read_deleted='no')

        if not (flavor_id_passed and same_flavor):
            if flavor_id_passed:
                mock_upsize.assert_called_once_with(
                    test.MatchType(objects.Flavor),
                    test.MatchType(objects.Flavor))
                image_meta = utils.get_image_from_system_metadata(
                    fake_inst.system_metadata)
                if not same_flavor:
                    mock_validate.assert_called_once_with(
                        self.context, image_meta, new_flavor, root_bdm=None,
                        validate_pci=True)
                # mock.ANY might be 'instances', 'cores', or 'ram'
                # depending on how the deltas dict is iterated in check_deltas
                mock_count.assert_called_once_with(
                    self.context, mock.ANY, project_id, user_id=user_id)
                # The current and new flavor have the same cores/ram
                req_cores = current_flavor.vcpus
                req_ram = current_flavor.memory_mb
                values = {'cores': req_cores, 'ram': req_ram}
                mock_limit.assert_called_once_with(
                    self.context, user_values=values, project_values=values,
                    project_id=project_id, user_id=user_id)

                mock_inst_save.assert_called_once_with(
                    expected_task_state=[None])
            else:
                # This is a migration
                mock_validate.assert_not_called()

            mock_migration.assert_not_called()

            mock_get_by_instance_uuid.assert_called_once_with(self.context,
                                                              fake_inst.uuid)

            if flavor_id_passed:
                mock_record.assert_called_once_with(self.context, fake_inst,
                                                    'resize')
            else:
                if request_spec:
                    mock_record.assert_called_once_with(
                        self.context, fake_inst, 'migrate')
                else:
                    mock_record.assert_not_called()

            if request_spec:
                mock_resize.assert_called_once_with(
                    self.context, fake_inst,
                    scheduler_hint=scheduler_hint,
                    flavor=test.MatchType(objects.Flavor),
                    clean_shutdown=clean_shutdown,
                    request_spec=fake_spec, do_cast=True)
            else:
                mock_resize.assert_not_called()

    def test_resize(self):
        self._test_resize()

    def test_resize_same_host_and_allowed(self):
        self._test_resize(same_host=True, allow_same_host=True)

    def test_resize_same_host_and_not_allowed(self):
        self._test_resize(same_host=True, allow_same_host=False)

    def test_resize_different_project_id(self):
        self._test_resize(project_id='different')

    def test_resize_forced_shutdown(self):
        self._test_resize(clean_shutdown=False)

    def test_resize_allow_cross_cell_resize_true(self):
        self._test_resize(allow_cross_cell_resize=True)

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
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
                                    root_gb=10, disabled=False, extra_specs={})
        fake_inst = self._create_instance_obj()
        fake_inst.flavor = cur_flavor
        new_flavor = objects.Flavor(id=2, name='bar', vcpus=1, memory_mb=2048,
                                    root_gb=10, disabled=False, extra_specs={})
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

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                new=mock.Mock(return_value=False))
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize__with_accelerator(self, mock_get_flavor):
        """Ensure resizes are rejected if either flavor requests accelerator.
        """
        fake_inst = self._create_instance_obj()
        new_flavor = self._create_flavor(
            id=200, flavorid='new-flavor-id', name='new_flavor',
            disabled=False, extra_specs={'accel:device_profile': 'dp'})
        mock_get_flavor.return_value = new_flavor

        self.assertRaises(
            exception.ForbiddenWithAccelerators,
            self.compute_api.resize,
            self.context, fake_inst, flavor_id=new_flavor.flavorid)

    def _test_migrate(self, *args, **kwargs):
        self._test_resize(*args, flavor_id_passed=False, **kwargs)

    def test_migrate(self):
        self._test_migrate()

    def test_migrate_same_host_and_allowed(self):
        self._test_migrate(same_host=True, allow_same_host=True)

    def test_migrate_same_host_and_not_allowed(self):
        self._test_migrate(same_host=True, allow_same_host=False)

    def test_migrate_different_project_id(self):
        self._test_migrate(project_id='different')

    def test_migrate_request_spec_not_found(self):
        self._test_migrate(request_spec=False)

    def test_migrate_with_requested_destination(self):
        # RequestSpec has requested_destination
        self._test_migrate(requested_destination=True)

    def test_migrate_with_host_name(self):
        self._test_migrate(host_name='target_host')

    def test_migrate_with_host_name_allow_cross_cell_resize_true(self):
        self._test_migrate(host_name='target_host',
                           allow_cross_cell_resize=True)

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
                       side_effect=exception.ComputeHostNotFound(
                           host='nonexistent_host'))
    def test_migrate_nonexistent_host(self, mock_get_all_by_host):
        fake_inst = self._create_instance_obj()
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, host_name='nonexistent_host')

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(quotas_obj.Quotas, 'limit_check_project_and_user')
    @mock.patch.object(quotas_obj.Quotas, 'count_as_dict')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_invalid_flavor_fails(self, mock_get_flavor, mock_count,
                                         mock_limit, mock_record, mock_save):
        mock_resize = self.useFixture(fixtures.MockPatchObject(
            self.compute_api.compute_task_api, 'resize_instance')).mock

        fake_inst = self._create_instance_obj()
        exc = exception.FlavorNotFound(flavor_id='flavor-id')
        mock_get_flavor.side_effect = exc

        self.assertRaises(exception.FlavorNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')
        mock_get_flavor.assert_called_once_with('flavor-id', read_deleted='no')
        # Should never reach these.
        mock_count.assert_not_called()
        mock_limit.assert_not_called()
        mock_record.assert_not_called()
        mock_resize.assert_not_called()
        mock_save.assert_not_called()

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(quotas_obj.Quotas, 'limit_check_project_and_user')
    @mock.patch.object(quotas_obj.Quotas, 'count_as_dict')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_disabled_flavor_fails(self, mock_get_flavor, mock_count,
                                          mock_limit, mock_record, mock_save):
        mock_resize = self.useFixture(fixtures.MockPatchObject(
            self.compute_api.compute_task_api, 'resize_instance')).mock

        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', disabled=True)
        mock_get_flavor.return_value = fake_flavor

        self.assertRaises(exception.FlavorNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')
        mock_get_flavor.assert_called_once_with('flavor-id', read_deleted='no')
        # Should never reach these.
        mock_count.assert_not_called()
        mock_limit.assert_not_called()
        mock_record.assert_not_called()
        mock_resize.assert_not_called()
        mock_save.assert_not_called()

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
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

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch('nova.compute.api.API._validate_flavor_image_nostatus')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch('nova.conductor.conductor_api.ComputeTaskAPI.resize_instance')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_to_zero_disk_flavor_volume_backed(self,
                                                      get_flavor_by_flavor_id,
                                                      resize_instance_mock,
                                                      record_mock,
                                                      get_by_inst,
                                                      validate_mock):
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

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(quotas_obj.Quotas,
                       'limit_check_project_and_user')
    @mock.patch.object(quotas_obj.Quotas, 'count_as_dict')
    @mock.patch.object(compute_utils, 'upsize_quota_delta')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_quota_exceeds_fails(self, mock_get_flavor, mock_upsize,
                                        mock_count, mock_limit, mock_record,
                                        mock_save):
        mock_resize = self.useFixture(fixtures.MockPatchObject(
            self.compute_api.compute_task_api, 'resize_instance')).mock

        fake_inst = self._create_instance_obj()
        fake_flavor = self._create_flavor(id=200, flavorid='flavor-id',
                            name='foo', disabled=False)
        mock_get_flavor.return_value = fake_flavor
        deltas = dict(cores=0)
        mock_upsize.return_value = deltas
        quotas = {'cores': 0}
        overs = ['cores']
        over_quota_args = dict(quotas=quotas,
                               usages={'instances': 1, 'cores': 1, 'ram': 512},
                               overs=overs)

        proj_count = {'instances': 1, 'cores': fake_inst.flavor.vcpus,
                      'ram': fake_inst.flavor.memory_mb}
        user_count = proj_count.copy()
        mock_count.return_value = {'project': proj_count, 'user': user_count}

        req_cores = fake_inst.flavor.vcpus
        req_ram = fake_inst.flavor.memory_mb
        values = {'cores': req_cores, 'ram': req_ram}
        mock_limit.side_effect = exception.OverQuota(**over_quota_args)

        self.assertRaises(exception.TooManyInstances,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')

        mock_save.assert_not_called()
        mock_get_flavor.assert_called_once_with('flavor-id', read_deleted='no')
        mock_upsize.assert_called_once_with(test.MatchType(objects.Flavor),
                                            test.MatchType(objects.Flavor))
        # mock.ANY might be 'instances', 'cores', or 'ram'
        # depending on how the deltas dict is iterated in check_deltas
        mock_count.assert_called_once_with(self.context, mock.ANY,
                                           fake_inst.project_id,
                                           user_id=fake_inst.user_id)
        mock_limit.assert_called_once_with(self.context, user_values=values,
                                           project_values=values,
                                           project_id=fake_inst.project_id,
                                           user_id=fake_inst.user_id)
        # Should never reach these.
        mock_record.assert_not_called()
        mock_resize.assert_not_called()

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
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

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
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

    # TODO(huaqiang): Remove in Wallaby
    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
    @mock.patch.object(compute_utils, 'is_volume_backed_instance',
                       new=mock.Mock(return_value=True))
    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                new=mock.Mock(return_value=51))
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(flavors, 'get_flavor_by_flavor_id')
    def test_resize_mixed_instance_compute_version_low_fails(
            self, mock_get_flavor, mock_image, mock_spec):
        """Check resizing an mixed policy instance fails if some
        nova-compute node is not upgraded to Victory yet.
        """
        numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set([0, 1, 2, 3]), memory=1024,
                pagesize=None, cpu_pinning_raw=None, cpuset_reserved=None,
                cpu_policy='dedicated', cpu_thread_policy=None)
        ])
        flavor = objects.Flavor(id=1, name='current', vcpus=4, memory_mb=1024,
                                root_gb=10, disabled=False,
                                extra_specs={
                                    "hw:cpu_policy": "dedicated"
                                })
        new_flavor = objects.Flavor(id=2, name='new', vcpus=4, memory_mb=1024,
                                    root_gb=10, disabled=False,
                                    extra_specs={
                                        "hw:cpu_policy": "mixed",
                                        "hw:cpu_dedicated_mask": "^0-2",
                                    })
        image = {"properties": {}}
        params = {
            'vcpus': 4,
            'numa_topology': numa_topology,
        }

        mock_image.return_value = image
        mock_get_flavor.return_value = new_flavor
        instance = self._create_instance_obj(params=params, flavor=flavor)
        self.assertRaises(exception.MixedInstanceNotSupportByComputeService,
                          self.compute_api.resize, self.context,
                          instance, flavor_id='flavor-new')
        mock_spec.assert_called_once()

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(objects.Instance, 'save')
    def test_pause(self, mock_save, mock_record):
        # Ensure instance can be paused.
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertIsNone(instance.task_state)

        rpcapi = self.compute_api.compute_rpcapi

        mock_pause = self.useFixture(
            fixtures.MockPatchObject(rpcapi, 'pause_instance')).mock

        with mock.patch.object(rpcapi, 'pause_instance') as mock_pause:
            self.compute_api.pause(self.context, instance)

        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertEqual(task_states.PAUSING,
                         instance.task_state)
        mock_save.assert_called_once_with(expected_task_state=[None])
        mock_record.assert_called_once_with(self.context, instance,
                                            instance_actions.PAUSE)
        mock_pause.assert_called_once_with(self.context, instance)

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

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(objects.Instance, 'save')
    def test_unpause(self, mock_save, mock_record):
        # Ensure instance can be unpaused.
        params = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=params)
        self.assertEqual(instance.vm_state, vm_states.PAUSED)
        self.assertIsNone(instance.task_state)

        rpcapi = self.compute_api.compute_rpcapi

        with mock.patch.object(rpcapi, 'unpause_instance') as mock_unpause:
            self.compute_api.unpause(self.context, instance)

        self.assertEqual(vm_states.PAUSED, instance.vm_state)
        self.assertEqual(task_states.UNPAUSING, instance.task_state)
        mock_save.assert_called_once_with(expected_task_state=[None])
        mock_record.assert_called_once_with(self.context, instance,
                                            instance_actions.UNPAUSE)
        mock_unpause.assert_called_once_with(self.context, instance)

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

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_live_migrate_active_vm_state(self, mock_nodelist):
        instance = self._create_instance_obj()
        self._live_migrate_instance(instance)

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_live_migrate_paused_vm_state(self, mock_nodelist):
        paused_state = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=paused_state)
        self._live_migrate_instance(instance)

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    @mock.patch.object(objects.Instance, 'save')
    def test_live_migrate_messaging_timeout(self, _save, _action, get_spec,
                                            add_instance_fault_from_exc,
                                            mock_nodelist):
        instance = self._create_instance_obj()
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
    @mock.patch.object(objects.InstanceAction, 'action_start')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
                       side_effect=exception.ComputeHostNotFound(
                           host='fake_host'))
    def test_live_migrate_computehost_notfound(self, mock_nodelist,
                                               mock_action,
                                               mock_get_spec):
        instance = self._create_instance_obj()
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api.live_migrate,
                          self.context, instance,
                          host_name='fake_host',
                          block_migration='auto',
                          disk_over_commit=False)
        self.assertIsNone(instance.task_state)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceAction, 'action_start')
    def _live_migrate_instance(self, instance, _save, _action, get_spec):
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
                                         async_=False)

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

    def test_count_attachments_for_swap_not_found_and_readonly(self):
        """Tests that attachment records that aren't found are considered
        read/write by default. Also tests that read-only attachments are
        not counted.
        """
        ctxt = context.get_admin_context()
        volume = {
            'attachments': {
                uuids.server1: {
                    'attachment_id': uuids.attachment1
                },
                uuids.server2: {
                    'attachment_id': uuids.attachment2
                }
            }
        }

        def fake_attachment_get(_context, attachment_id):
            if attachment_id == uuids.attachment1:
                raise exception.VolumeAttachmentNotFound(
                    attachment_id=attachment_id)
            return {'attach_mode': 'ro'}

        with mock.patch.object(self.compute_api.volume_api, 'attachment_get',
                               side_effect=fake_attachment_get) as mock_get:
            self.assertEqual(
                1, self.compute_api._count_attachments_for_swap(ctxt, volume))
        mock_get.assert_has_calls([
            mock.call(ctxt, uuids.attachment1),
            mock.call(ctxt, uuids.attachment2)], any_order=True)

    @mock.patch('nova.volume.cinder.API.attachment_get',
                new_callable=mock.NonCallableMock)  # asserts not called
    def test_count_attachments_for_swap_no_query(self, mock_attachment_get):
        """Tests that if the volume has <2 attachments, we don't query
        the attachments for their attach_mode value.
        """
        volume = {}
        self.assertEqual(
            0, self.compute_api._count_attachments_for_swap(
                mock.sentinel.context, volume))
        volume = {
            'attachments': {
                uuids.server: {
                    'attachment_id': uuids.attach1
                }
            }
        }
        self.assertEqual(
            1, self.compute_api._count_attachments_for_swap(
                mock.sentinel.context, volume))

    @mock.patch.object(compute_utils, 'is_volume_backed_instance')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(image_api.API, 'create')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def _test_snapshot_and_backup(self, mock_record, mock_get_image,
                                  mock_create, mock_save, mock_is_volume,
                                  is_snapshot=True, with_base_ref=False,
                                  min_ram=None, min_disk=None,
                                  create_fails=False,
                                  instance_vm_state=vm_states.ACTIVE):
        params = dict(locked=True)
        instance = self._create_instance_obj(params=params)
        instance.vm_state = instance_vm_state

        # Test non-inheritable properties, 'user_id' should also not be
        # carried from sys_meta into image property...since it should be set
        # explicitly by _create_image() in compute api.
        fake_image_meta = {
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
            'visibility': 'private',
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

        if not is_snapshot:
            mock_is_volume.return_value = False

        mock_get_image.return_value = fake_image_meta

        fake_image = dict(id='fake-image-id')
        if create_fails:
            mock_create.side_effect = test.TestingException()
        else:
            mock_create.return_value = fake_image

        def check_state(expected_task_state=None):
            expected_state = (is_snapshot and
                              task_states.IMAGE_SNAPSHOT_PENDING or
                              task_states.IMAGE_BACKUP)
            self.assertEqual(expected_state, instance.task_state)

        if not create_fails:
            mock_save.side_effect = check_state

        if is_snapshot:
            with mock.patch.object(self.compute_api.compute_rpcapi,
                                   'snapshot_instance') as mock_snapshot:
                if create_fails:
                    self.assertRaises(test.TestingException,
                                      self.compute_api.snapshot,
                                      self.context, instance, 'fake-name',
                                      extra_properties=extra_props)
                else:
                    res = self.compute_api.snapshot(
                        self.context, instance, 'fake-name',
                        extra_properties=extra_props)
                    mock_record.assert_called_once_with(
                        self.context, instance, instance_actions.CREATE_IMAGE)
                    mock_snapshot.assert_called_once_with(
                        self.context, instance, fake_image['id'])
        else:
            with mock.patch.object(self.compute_api.compute_rpcapi,
                                   'backup_instance') as mock_backup:
                if create_fails:
                    self.assertRaises(test.TestingException,
                                      self.compute_api.backup,
                                      self.context, instance,
                                      'fake-name', 'fake-backup-type',
                                      'fake-rotation',
                                      extra_properties=extra_props)
                else:
                    res = self.compute_api.backup(
                        self.context, instance, 'fake-name',
                        'fake-backup-type', 'fake-rotation',
                        extra_properties=extra_props)
                    mock_record.assert_called_once_with(
                        self.context, instance, instance_actions.BACKUP)
                    mock_backup.assert_called_once_with(
                        self.context, instance, fake_image['id'],
                        'fake-backup-type', 'fake-rotation')

        mock_create.assert_called_once_with(self.context, sent_meta)
        mock_get_image.assert_called_once_with(instance.system_metadata)

        if not is_snapshot:
            mock_is_volume.assert_called_once_with(self.context, instance)
        else:
            mock_is_volume.assert_not_called()

        if not create_fails:
            self.assertEqual(fake_image, res)
            mock_save.assert_called_once_with(expected_task_state=[None])

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
    @mock.patch.object(compute_utils, 'create_image')
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
    @mock.patch.object(compute_utils, 'create_image')
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
    @mock.patch.object(compute_utils, 'create_image')
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

    def _test_snapshot_volume_backed(self, quiesce_required=False,
                                     quiesce_fails=False,
                                     quiesce_unsupported=False,
                                     vm_state=vm_states.ACTIVE,
                                     snapshot_fails=False, limits=None):
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
            'visibility': 'private',
            'min_ram': '11',
        }
        if quiesce_required:
            expect_meta['properties']['os_require_quiesce'] = 'yes'

        quiesced = [False, False]
        quiesce_expected = not (quiesce_unsupported or quiesce_fails) \
                           and vm_state == vm_states.ACTIVE

        @classmethod
        def fake_bdm_list_get_by_instance_uuid(cls, context, instance_uuid):
            return obj_base.obj_make_list(context, cls(),
                    objects.BlockDeviceMapping, instance_bdms)

        def fake_image_create(_self, context, image_meta, data=None):
            self.assertThat(image_meta, matchers.DictMatches(expect_meta))

        def fake_volume_create_snapshot(self, context, volume_id, name,
                                        description):
            if snapshot_fails:
                raise exception.OverQuota(overs="snapshots")
            return {'id': '%s-snapshot' % volume_id}

        def fake_quiesce_instance(context, instance):
            if quiesce_unsupported:
                raise exception.InstanceQuiesceNotSupported(
                    instance_id=instance['uuid'], reason='unsupported')
            if quiesce_fails:
                raise oslo_exceptions.MessagingTimeout('quiece timeout')
            quiesced[0] = True

        def fake_unquiesce_instance(context, instance, mapping=None):
            quiesced[1] = True

        def fake_get_absolute_limits(context):
            if limits is not None:
                return limits
            return {"totalSnapshotsUsed": 0, "maxTotalSnapshots": 10}

        self.stub_out('nova.objects.BlockDeviceMappingList'
                      '.get_by_instance_uuid',
                      fake_bdm_list_get_by_instance_uuid)
        self.stub_out('nova.image.glance.API.create', fake_image_create)
        self.stub_out('nova.volume.cinder.API.get',
                      lambda self, context, volume_id:
                          {'id': volume_id, 'display_description': ''})
        self.stub_out('nova.volume.cinder.API.create_snapshot_force',
                       fake_volume_create_snapshot)
        self.useFixture(fixtures.MockPatchObject(
            self.compute_api.compute_rpcapi, 'quiesce_instance',
            side_effect=fake_quiesce_instance))
        self.useFixture(fixtures.MockPatchObject(
            self.compute_api.compute_rpcapi, 'unquiesce_instance',
            side_effect=fake_unquiesce_instance))
        self.useFixture(nova_fixtures.GlanceFixture(self))

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
                                           CONF.host,
                                           instance.uuid,
                                           graceful_exit=False)

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
             'tag': None, 'volume_type': None})

        limits_patcher = mock.patch.object(
            self.compute_api.volume_api, 'get_absolute_limits',
            side_effect=fake_get_absolute_limits)
        limits_patcher.start()
        self.addCleanup(limits_patcher.stop)

        with test.nested(
                mock.patch.object(compute_api.API, '_record_action_start'),
                mock.patch.object(compute_utils, 'EventReporter')) as (
                mock_record, mock_event):
            # All the db_only fields and the volume ones are removed
            if snapshot_fails:
                self.assertRaises(exception.OverQuota,
                                  self.compute_api.snapshot_volume_backed,
                                  self.context, instance, "test-snapshot")
            else:
                self.compute_api.snapshot_volume_backed(
                    self.context, instance, 'test-snapshot')

        self.assertEqual(quiesce_expected, quiesced[0])
        self.assertEqual(quiesce_expected, quiesced[1])

        mock_record.assert_called_once_with(self.context,
                                            instance,
                                            instance_actions.CREATE_IMAGE)
        mock_event.assert_called_once_with(self.context,
                                           'api_snapshot_instance',
                                           CONF.host,
                                           instance.uuid,
                                           graceful_exit=False)

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
                  'no_device': None, 'volume_type': None}])[:255])

        bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'no_device': False, 'volume_id': None, 'boot_index': -1,
                 'connection_info': 'inf', 'device_name': '/dev/vdh',
                 'source_type': 'blank', 'destination_type': 'local',
                 'guest_format': 'swap', 'delete_on_termination': True,
                 'tag': None, 'volume_type': None})
        instance_bdms.append(bdm)
        # The non-volume image mapping will go at the front of the list
        # because the volume BDMs are processed separately.
        expect_meta['properties']['block_device_mapping'].insert(0,
            {'guest_format': 'swap', 'boot_index': -1, 'no_device': False,
             'image_id': None, 'volume_id': None, 'disk_bus': None,
             'volume_size': None, 'source_type': 'blank',
             'device_type': None, 'snapshot_id': None,
             'device_name': '/dev/vdh',
             'destination_type': 'local', 'delete_on_termination': True,
             'tag': None, 'volume_type': None})

        quiesced = [False, False]

        with test.nested(
                mock.patch.object(compute_api.API, '_record_action_start'),
                mock.patch.object(compute_utils, 'EventReporter')) as (
                mock_record, mock_event):
            # Check that the mappings from the image properties are not
            # included
            if snapshot_fails:
                self.assertRaises(exception.OverQuota,
                                  self.compute_api.snapshot_volume_backed,
                                  self.context, instance, "test-snapshot")
            else:
                self.compute_api.snapshot_volume_backed(
                    self.context, instance, 'test-snapshot')

        self.assertEqual(quiesce_expected, quiesced[0])
        self.assertEqual(quiesce_expected, quiesced[1])

        mock_record.assert_called_once_with(self.context,
                                            instance,
                                            instance_actions.CREATE_IMAGE)
        mock_event.assert_called_once_with(self.context,
                                           'api_snapshot_instance',
                                           CONF.host,
                                           instance.uuid,
                                           graceful_exit=False)

    def test_snapshot_volume_backed(self):
        self._test_snapshot_volume_backed(quiesce_required=False,
                                          quiesce_unsupported=False)

    def test_snapshot_volume_backed_with_quiesce_unsupported(self):
        self._test_snapshot_volume_backed(quiesce_required=True,
                                          quiesce_unsupported=False)

    def test_snaphost_volume_backed_with_quiesce_failure(self):
        self.assertRaises(oslo_exceptions.MessagingTimeout,
                          self._test_snapshot_volume_backed,
                          quiesce_required=True,
                          quiesce_fails=True)

    def test_snapshot_volume_backed_with_quiesce_create_snap_fails(self):
        self._test_snapshot_volume_backed(quiesce_required=True,
                                          snapshot_fails=True)

    def test_snapshot_volume_backed_unlimited_quota(self):
        """Tests that there is unlimited quota on volume snapshots so we
        don't perform a quota check.
        """
        limits = {'maxTotalSnapshots': -1, 'totalSnapshotsUsed': 0}
        self._test_snapshot_volume_backed(limits=limits)

    def test_snapshot_volume_backed_over_quota_before_snapshot(self):
        """Tests that the up-front check on quota fails before actually
        attempting to snapshot any volumes.
        """
        limits = {'maxTotalSnapshots': 1, 'totalSnapshotsUsed': 1}
        self.assertRaises(exception.OverQuota,
                          self._test_snapshot_volume_backed,
                          limits=limits)

    def test_snapshot_volume_backed_with_quiesce_skipped(self):
        self._test_snapshot_volume_backed(quiesce_required=False,
                                          quiesce_unsupported=True)

    def test_snapshot_volume_backed_with_quiesce_exception(self):
        self.assertRaises(exception.NovaException,
                          self._test_snapshot_volume_backed,
                          quiesce_required=True,
                          quiesce_unsupported=True)

    def test_snapshot_volume_backed_with_suspended(self):
        self._test_snapshot_volume_backed(quiesce_required=False,
                                          quiesce_unsupported=True,
                                          vm_state=vm_states.SUSPENDED)

    def test_snapshot_volume_backed_with_pause(self):
        self._test_snapshot_volume_backed(quiesce_required=False,
                                          quiesce_unsupported=True,
                                          vm_state=vm_states.PAUSED)

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

    @mock.patch.object(compute_api.API, '_get_bdm_by_volume_id')
    def test_volume_snapshot_create(self, mock_get_bdm):
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

        mock_get_bdm.return_value = fake_bdm

        with mock.patch.object(self.compute_api.compute_rpcapi,
                               'volume_snapshot_create') as mock_snapshot:
            snapshot = self.compute_api.volume_snapshot_create(self.context,
                volume_id, create_info)

        expected_snapshot = {
            'snapshot': {
                'id': create_info['id'],
                'volumeId': volume_id,
            },
        }
        self.assertEqual(snapshot, expected_snapshot)
        mock_get_bdm.assert_called_once_with(
            self.context, volume_id, expected_attrs=['instance'])
        mock_snapshot.assert_called_once_with(
            self.context, fake_bdm['instance'], volume_id, create_info)

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

    @mock.patch.object(compute_api.API, '_get_bdm_by_volume_id')
    def test_volume_snapshot_delete(self, mock_get_bdm):
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

        mock_get_bdm.return_value = fake_bdm

        with mock.patch.object(self.compute_api.compute_rpcapi,
                               'volume_snapshot_delete') as mock_snapshot:
            self.compute_api.volume_snapshot_delete(self.context, volume_id,
                snapshot_id, {})

        mock_get_bdm.assert_called_once_with(self.context, volume_id,
                                             expected_attrs=['instance'])
        mock_snapshot.assert_called_once_with(
            self.context, fake_bdm['instance'], volume_id, snapshot_id, {})

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

        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.stub_out('nova.tests.fixtures.GlanceFixture.show',
                      lambda obj, context, image_id, **kwargs: self.fake_image)
        return self.fake_image['id']

    def _setup_fake_image_with_invalid_arch(self):
        self.fake_image = {
            'id': 2,
            'name': 'fake_name',
            'status': 'active',
            'properties': {"hw_architecture": "arm64"},
        }

        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.stub_out('nova.tests.fixtures.GlanceFixture.show',
                      lambda obj, context, image_id, **kwargs: self.fake_image)
        return self.fake_image['id']

    @mock.patch('nova.compute.api.API.get_instance_host_status',
                new=mock.Mock(return_value=fields_obj.HostStatus.UP))
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

    def test_rebuild_with_invalid_image_arch(self):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE, cell_name='fake-cell',
            launched_at=timeutils.utcnow(),
            system_metadata={}, image_ref='foo',
            expected_attrs=['system_metadata'])
        image_id = self._setup_fake_image_with_invalid_arch()
        self.assertRaises(exception.InvalidArchitectureName,
                          self.compute_api.rebuild,
                          self.context,
                          instance,
                          image_id,
                          "new password")
        self.assertIsNone(instance.task_state)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_image_arch')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_with_invalid_volume(self, _record_action_start,
            _checks_for_create_and_rebuild, _check_auto_disk_config,
            _check_image_arch, mock_get_image,
            mock_get_bdms, get_flavor,
            instance_save, req_spec_get_by_inst_uuid):
        """Test a negative scenario where the instance has an
        invalid volume.
        """
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE, cell_name='fake-cell',
            launched_at=timeutils.utcnow(),
            system_metadata={}, image_ref='foo',
            expected_attrs=['system_metadata'])

        bdms = objects.BlockDeviceMappingList(objects=[
                objects.BlockDeviceMapping(
                    boot_index=None, image_id=None,
                    source_type='volume', destination_type='volume',
                    volume_type=None, snapshot_id=None,
                    volume_id=uuids.volume_id, volume_size=None)])
        mock_get_bdms.return_value = bdms

        get_flavor.return_value = test_flavor.fake_flavor
        flavor = instance.get_flavor()

        image_href = 'foo'
        image = {
            "min_ram": 10, "min_disk": 1,
            "properties": {
                'architecture': fields_obj.Architecture.X86_64}}
        mock_get_image.return_value = (None, image)

        fake_spec = objects.RequestSpec()
        req_spec_get_by_inst_uuid.return_value = fake_spec

        fake_volume = {'id': uuids.volume_id, 'status': 'retyping'}
        with mock.patch.object(self.compute_api.volume_api, 'get',
                               return_value=fake_volume) as mock_get_volume:
            self.assertRaises(exception.InvalidVolume,
                              self.compute_api.rebuild,
                              self.context,
                              instance,
                              image_href,
                              "new password")
            self.assertIsNone(instance.task_state)
            mock_get_bdms.assert_called_once_with(self.context,
                                                  instance.uuid)
            mock_get_volume.assert_called_once_with(self.context,
                                                    uuids.volume_id)
            _check_auto_disk_config.assert_called_once_with(
                image=image, auto_disk_config=None)
            _check_image_arch.assert_called_once_with(image=image)
            _checks_for_create_and_rebuild.assert_called_once_with(
                self.context, None, image, flavor, {}, [], None)

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
                    request_spec=fake_spec)

        _check_auto_disk_config.assert_called_once_with(
            image=image, auto_disk_config=None)
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
                    request_spec=fake_spec)
            # assert the request spec was modified so the scheduler picks
            # the existing instance host/node
            req_spec_save.assert_called_once_with()
            self.assertIn('_nova_check_type', fake_spec.scheduler_hints)
            self.assertEqual('rebuild',
                             fake_spec.scheduler_hints['_nova_check_type'][0])

        _check_auto_disk_config.assert_called_once_with(
            image=new_image, auto_disk_config=None)
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
                    request_spec=fake_spec)

        _check_auto_disk_config.assert_called_once_with(
            image=image, auto_disk_config=None)
        _checks_for_create_and_rebuild.assert_called_once_with(self.context,
                None, image, flavor, {}, [], None)
        self.assertNotEqual(orig_key_name, instance.key_name)
        self.assertNotEqual(orig_key_data, instance.key_data)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_change_trusted_certs(self, _record_action_start,
            _checks_for_create_and_rebuild, _check_auto_disk_config,
            _get_image, bdm_get_by_instance_uuid, get_flavor, instance_save,
            req_spec_get_by_inst_uuid):
        orig_system_metadata = {}
        orig_trusted_certs = ['orig-trusted-cert-1', 'orig-trusted-cert-2']
        new_trusted_certs = ['new-trusted-cert-1', 'new-trusted-cert-2']
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE, cell_name='fake-cell',
            launched_at=timeutils.utcnow(),
            system_metadata=orig_system_metadata, image_ref='foo',
            expected_attrs=['system_metadata'],
            trusted_certs=orig_trusted_certs)
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

        with mock.patch.object(self.compute_api.compute_task_api,
                'rebuild_instance') as rebuild_instance:
            self.compute_api.rebuild(self.context, instance, image_href,
                                     admin_pass, files_to_inject,
                                     trusted_certs=new_trusted_certs)

            rebuild_instance.assert_called_once_with(
                self.context, instance=instance, new_pass=admin_pass,
                injected_files=files_to_inject, image_ref=image_href,
                orig_image_ref=image_href,
                orig_sys_metadata=orig_system_metadata, bdms=bdms,
                preserve_ephemeral=False, host=instance.host,
                request_spec=fake_spec)

        _check_auto_disk_config.assert_called_once_with(
            image=image, auto_disk_config=None)
        _checks_for_create_and_rebuild.assert_called_once_with(
            self.context, None, image, flavor, {}, [], None)
        self.assertEqual(new_trusted_certs, instance.trusted_certs.ids)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_unset_trusted_certs(self, _record_action_start,
                                          _checks_for_create_and_rebuild,
                                          _check_auto_disk_config,
                                          _get_image, bdm_get_by_instance_uuid,
                                          get_flavor, instance_save,
                                          req_spec_get_by_inst_uuid):
        """Tests the scenario that the server was created with some trusted
        certs and then rebuilt without trusted_image_certificates=None
        explicitly to unset the trusted certs on the server.
        """
        orig_system_metadata = {}
        orig_trusted_certs = ['orig-trusted-cert-1', 'orig-trusted-cert-2']
        new_trusted_certs = None
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE, cell_name='fake-cell',
            launched_at=timeutils.utcnow(),
            system_metadata=orig_system_metadata, image_ref='foo',
            expected_attrs=['system_metadata'],
            trusted_certs=orig_trusted_certs)
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

        with mock.patch.object(self.compute_api.compute_task_api,
                               'rebuild_instance') as rebuild_instance:
            self.compute_api.rebuild(self.context, instance, image_href,
                                     admin_pass, files_to_inject,
                                     trusted_certs=new_trusted_certs)

            rebuild_instance.assert_called_once_with(
                self.context, instance=instance, new_pass=admin_pass,
                injected_files=files_to_inject, image_ref=image_href,
                orig_image_ref=image_href,
                orig_sys_metadata=orig_system_metadata, bdms=bdms,
                preserve_ephemeral=False, host=instance.host,
                request_spec=fake_spec)

        _check_auto_disk_config.assert_called_once_with(
            image=image, auto_disk_config=None)
        _checks_for_create_and_rebuild.assert_called_once_with(
            self.context, None, image, flavor, {}, [], None)
        self.assertIsNone(instance.trusted_certs)

    @mock.patch.object(compute_utils, 'is_volume_backed_instance',
                       return_value=True)
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_volume_backed_instance_with_trusted_certs(
            self, _record_action_start, _check_auto_disk_config, _get_image,
            bdm_get_by_instance_uuid, get_flavor, instance_is_volume_backed):
        orig_system_metadata = {}
        new_trusted_certs = ['new-trusted-cert-1', 'new-trusted-cert-2']
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE, cell_name='fake-cell',
            launched_at=timeutils.utcnow(),
            system_metadata=orig_system_metadata, image_ref=None,
            expected_attrs=['system_metadata'], trusted_certs=None)
        get_flavor.return_value = test_flavor.fake_flavor
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

        self.assertRaises(exception.CertificateValidationFailed,
                          self.compute_api.rebuild, self.context, instance,
                          image_href, admin_pass, files_to_inject,
                          trusted_certs=new_trusted_certs)

        _check_auto_disk_config.assert_called_once_with(
            image=image, auto_disk_config=None)

    @mock.patch('nova.objects.Quotas.limit_check')
    def test_check_metadata_properties_quota_with_empty_dict(self,
                                                             limit_check):
        metadata = {}
        self.compute_api._check_metadata_properties_quota(self.context,
                                                          metadata)
        self.assertEqual(0, limit_check.call_count)

    @mock.patch('nova.objects.Quotas.limit_check')
    def test_check_injected_file_quota_with_empty_list(self,
                                                       limit_check):
        injected_files = []
        self.compute_api._check_injected_file_quota(self.context,
                                                    injected_files)
        self.assertEqual(0, limit_check.call_count)

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

    @mock.patch('nova.objects.Quotas.get_all_by_project_and_user',
                new=mock.MagicMock())
    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.InstanceAction.action_start')
    @mock.patch('nova.compute.api.API._update_queued_for_deletion')
    def test_restore_by_admin(self, update_qfd, action_start, instance_save,
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
        # user_id is expected to be None because no per-user quotas have been
        # defined
        quota_count.assert_called_once_with(admin_context, mock.ANY,
                                            instance.project_id,
                                            user_id=None)
        quota_check.assert_called_once_with(
            admin_context,
            user_values={'instances': 2,
                         'cores': 1 + instance.flavor.vcpus,
                         'ram': 512 + instance.flavor.memory_mb},
            project_values={'instances': 2,
                            'cores': 1 + instance.flavor.vcpus,
                            'ram': 512 + instance.flavor.memory_mb},
            project_id=instance.project_id)
        update_qfd.assert_called_once_with(admin_context, instance, False)

    @mock.patch('nova.objects.Quotas.get_all_by_project_and_user',
                new=mock.MagicMock())
    @mock.patch('nova.objects.Quotas.count_as_dict')
    @mock.patch('nova.objects.Quotas.limit_check_project_and_user')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.InstanceAction.action_start')
    @mock.patch('nova.compute.api.API._update_queued_for_deletion')
    def test_restore_by_instance_owner(self, update_qfd, action_start,
                                       instance_save,
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
        # user_id is expected to be None because no per-user quotas have been
        # defined
        quota_count.assert_called_once_with(self.context, mock.ANY,
                                            instance.project_id,
                                            user_id=None)
        quota_check.assert_called_once_with(
            self.context,
            user_values={'instances': 2,
                         'cores': 1 + instance.flavor.vcpus,
                         'ram': 512 + instance.flavor.memory_mb},
            project_values={'instances': 2,
                            'cores': 1 + instance.flavor.vcpus,
                            'ram': 512 + instance.flavor.memory_mb},
            project_id=instance.project_id)
        update_qfd.assert_called_once_with(self.context, instance, False)

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
            objects.Instance(uuid=uuids.instance_5, host='host2',
                             migration_context=None, task_state=None,
                             vm_state=vm_states.STOPPED,
                             power_state=power_state.SHUTDOWN),
            objects.Instance(uuid=uuids.instance_6, host='host2',
                             migration_context=None, task_state=None,
                             vm_state=vm_states.ACTIVE,
                             power_state=power_state.RUNNING)
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
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_5,
                name='power-update',
                tag="POWER_ON"),
            objects.InstanceExternalEvent(
                instance_uuid=uuids.instance_6,
                name='power-update',
                tag="POWER_OFF"),
            ]
        self.compute_api.compute_rpcapi = mock.MagicMock()
        self.compute_api.external_instance_event(self.context,
                                                 instances, events)
        method = self.compute_api.compute_rpcapi.external_instance_event
        method.assert_any_call(cell_context, instances[0:2], events[0:2],
                               host='host1')
        method.assert_any_call(cell_context, instances[2:], events[2:],
                               host='host2')
        calls = [mock.call(self.context, uuids.instance_4,
                           instance_actions.EXTEND_VOLUME, want_result=False),
                 mock.call(self.context, uuids.instance_5,
                           instance_actions.START, want_result=False),
                 mock.call(self.context, uuids.instance_6,
                           instance_actions.STOP, want_result=False)]
        mock_action_start.assert_has_calls(calls)
        self.assertEqual(2, method.call_count)

    def test_external_instance_event_power_update_invalid_tag(self):
        instance1 = objects.Instance(self.context)
        instance1.uuid = uuids.instance1
        instance1.id = 1
        instance1.vm_state = vm_states.ACTIVE
        instance1.task_state = None
        instance1.power_state = power_state.RUNNING
        instance1.host = 'host1'
        instance1.migration_context = None
        instance2 = objects.Instance(self.context)
        instance2.uuid = uuids.instance2
        instance2.id = 2
        instance2.vm_state = vm_states.STOPPED
        instance2.task_state = None
        instance2.power_state = power_state.SHUTDOWN
        instance2.host = 'host2'
        instance2.migration_context = None
        instances = [instance1, instance2]
        events = [
            objects.InstanceExternalEvent(
                instance_uuid=instance1.uuid,
                name='power-update',
                tag="VACATION"),
            objects.InstanceExternalEvent(
                instance_uuid=instance2.uuid,
                name='power-update',
                tag="POWER_ON")
            ]
        with test.nested(
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'external_instance_event'),
            mock.patch.object(objects.InstanceAction, 'action_start'),
            mock.patch.object(compute_api, 'LOG')
        ) as (
            mock_ex, mock_action_start, mock_log
        ):
            self.compute_api.external_instance_event(self.context,
                instances, events)
            self.assertEqual(2, mock_ex.call_count)
            # event VACATION requested on instance1 is ignored because
            # its an invalid event tag.
            mock_ex.assert_has_calls(
                [mock.call(self.context, [instance2],
                           [events[1]], host=u'host2'),
                 mock.call(self.context, [instance1], [], host=u'host1')],
                any_order=True)
            mock_action_start.assert_called_once_with(
                self.context, instance2.uuid, instance_actions.START,
                want_result=False)
            self.assertEqual(1, mock_log.warning.call_count)
            self.assertIn(
                'Invalid power state', mock_log.warning.call_args[0][0])

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
                          'updated_at': None, 'deleted_at': None,
                          'cross_cell_move': False, 'user_id': None,
                          'project_id': None}

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

    @mock.patch('nova.objects.Migration.get_by_id')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.context.set_target_cell')
    @mock.patch('nova.context.get_admin_context')
    def test_external_instance_event_cross_cell_move(
            self, get_admin_context, set_target_cell, get_hm_by_host,
            get_mig_by_id):
        """Tests a scenario where an external server event comes for an
        instance undergoing a cross-cell migration so the event is routed
        to both the source host in the source cell and dest host in dest cell
        using the properly targeted request contexts.
        """
        migration = objects.Migration(
            id=1, source_compute='host1', dest_compute='host2',
            cross_cell_move=True)
        migration_context = objects.MigrationContext(
            instance_uuid=uuids.instance, migration_id=migration.id,
            migration_type='resize', cross_cell_move=True)
        instance = objects.Instance(
            self.context, uuid=uuids.instance, host=migration.source_compute,
            migration_context=migration_context)
        get_mig_by_id.return_value = migration
        source_cell_mapping = objects.CellMapping(name='source-cell')
        dest_cell_mapping = objects.CellMapping(name='dest-cell')

        # Wrap _get_relevant_hosts and sort the result for predictable asserts.
        original_get_relevant_hosts = self.compute_api._get_relevant_hosts

        def wrap_get_relevant_hosts(_self, *a, **kw):
            hosts, cross_cell_move = original_get_relevant_hosts(*a, **kw)
            return sorted(hosts), cross_cell_move
        self.stub_out('nova.compute.api.API._get_relevant_hosts',
                      wrap_get_relevant_hosts)

        def fake_hm_get_by_host(ctxt, host):
            if host == migration.source_compute:
                return objects.HostMapping(
                    host=host, cell_mapping=source_cell_mapping)
            if host == migration.dest_compute:
                return objects.HostMapping(
                    host=host, cell_mapping=dest_cell_mapping)
            raise Exception('Unexpected host: %s' % host)

        get_hm_by_host.side_effect = fake_hm_get_by_host
        # get_admin_context should be called twice in order (source and dest)
        get_admin_context.side_effect = [
            mock.sentinel.source_context, mock.sentinel.dest_context]

        event = objects.InstanceExternalEvent(
            instance_uuid=instance.uuid, name='network-vif-plugged')
        events = [event]

        with mock.patch.object(self.compute_api.compute_rpcapi,
                               'external_instance_event') as rpc_mock:
            self.compute_api.external_instance_event(
                self.context, [instance], events)

        # We should have gotten the migration because of the migration_context.
        get_mig_by_id.assert_called_once_with(self.context, migration.id)
        # We should have gotten two host mappings (for source and dest).
        self.assertEqual(2, get_hm_by_host.call_count)
        get_hm_by_host.assert_has_calls([
            mock.call(self.context, migration.source_compute),
            mock.call(self.context, migration.dest_compute)])
        self.assertEqual(2, get_admin_context.call_count)
        # We should have targeted a context to both cells.
        self.assertEqual(2, set_target_cell.call_count)
        set_target_cell.assert_has_calls([
            mock.call(mock.sentinel.source_context, source_cell_mapping),
            mock.call(mock.sentinel.dest_context, dest_cell_mapping)])
        # We should have RPC cast to both hosts in different cells.
        self.assertEqual(2, rpc_mock.call_count)
        rpc_mock.assert_has_calls([
            mock.call(mock.sentinel.source_context, [instance], events,
                      host=migration.source_compute),
            mock.call(mock.sentinel.dest_context, [instance], events,
                      host=migration.dest_compute)],
            # The rpc calls are based on iterating over a dict which is not
            # ordered so we have to just assert the calls in any order.
            any_order=True)

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

    def test_get_volumes_for_bdms_errors(self):
        """Simple test to make sure _get_volumes_for_bdms raises up errors."""
        # Use a mix of pre-existing and source_type=image volumes to test the
        # filtering logic in the method.
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='image', volume_id=None),
            objects.BlockDeviceMapping(source_type='volume',
                                       volume_id=uuids.volume_id)])
        for exc in (
            exception.VolumeNotFound(volume_id=uuids.volume_id),
            exception.CinderConnectionFailed(reason='gremlins'),
            exception.Forbidden()
        ):
            with mock.patch.object(self.compute_api.volume_api, 'get',
                                   side_effect=exc) as mock_vol_get:
                self.assertRaises(type(exc),
                                  self.compute_api._get_volumes_for_bdms,
                                  self.context, bdms)
            mock_vol_get.assert_called_once_with(self.context, uuids.volume_id)

    @ddt.data(True, False)
    def test_validate_vol_az_for_create_multiple_vols_diff_az(self, cross_az):
        """Tests cross_az_attach=True|False scenarios where the volumes are
        in different zones.
        """
        self.flags(cross_az_attach=cross_az, group='cinder')
        volumes = [{'availability_zone': str(x)} for x in range(2)]
        if cross_az:
            # Since cross_az_attach=True (the default) we do not care that the
            # volumes are in different zones.
            self.assertIsNone(self.compute_api._validate_vol_az_for_create(
                None, volumes))
        else:
            # In this case the volumes cannot be in different zones.
            ex = self.assertRaises(
                exception.MismatchVolumeAZException,
                self.compute_api._validate_vol_az_for_create, None, volumes)
            self.assertIn('Volumes are in different availability zones: 0,1',
                          six.text_type(ex))

    def test_validate_vol_az_for_create_vol_az_matches_default_cpu_az(self):
        """Tests the scenario that the instance is not being created in a
        specific zone and the volume's zone matches
        CONF.default_availabilty_zone so None is returned indicating the
        RequestSpec.availability_zone does not need to be updated.
        """
        self.flags(cross_az_attach=False, group='cinder')
        volumes = [{'availability_zone': CONF.default_availability_zone}]
        self.assertIsNone(self.compute_api._validate_vol_az_for_create(
            None, volumes))

    @mock.patch.object(cinder.API, 'get_snapshot',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    def test_validate_bdm_with_cinder_down(self, mock_get_snapshot):
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()
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
        image_cache = volumes = {}
        self.assertRaises(exception.CinderConnectionFailed,
                          self.compute_api._validate_bdm,
                          self.context,
                          instance, instance_type, bdms, image_cache, volumes)

    @mock.patch.object(cinder.API, 'attachment_create',
                       side_effect=exception.InvalidInput(reason='error'))
    def test_validate_bdm_with_error_volume_new_flow(self, mock_attach_create):
        # Tests that an InvalidInput exception raised from
        # volume_api.attachment_create due to the volume status not being
        # 'available' results in _validate_bdm re-raising InvalidVolume.
        instance = self._create_instance_obj()
        del instance.id
        instance_type = self._create_flavor()
        volume_id = 'e856840e-9f5b-4894-8bde-58c6e29ac1e8'
        volume_info = {'status': 'error',
                       'attach_status': 'detached',
                       'id': volume_id, 'multiattach': False}
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
                          instance, instance_type, bdms, {},
                          {volume_id: volume_info})

        mock_attach_create.assert_called_once_with(
            self.context, volume_id, instance.uuid)

    def test_validate_bdm_missing_boot_index(self):
        """Tests that _validate_bdm will fail if there is no boot_index=0 entry
        """
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(
                boot_index=None, image_id=uuids.image_id,
                source_type='image', destination_type='volume')])
        image_cache = volumes = {}
        self.assertRaises(exception.InvalidBDMBootSequence,
                          self.compute_api._validate_bdm,
                          self.context, objects.Instance(), objects.Flavor(),
                          bdms, image_cache, volumes)

    def test_validate_bdm_with_volume_type_name_is_specified(self):
        """Test _check_requested_volume_type method is used.
        """
        instance = self._create_instance_obj()
        instance_type = self._create_flavor()

        volume_type = 'fake_lvm_1'
        volume_types = [{'id': 'fake_volume_type_id_1', 'name': 'fake_lvm_1'},
                        {'id': 'fake_volume_type_id_2', 'name': 'fake_lvm_2'}]

        bdm1 = objects.BlockDeviceMapping(
            **fake_block_device.AnonFakeDbBlockDeviceDict(
                {
                    'uuid': uuids.image_id,
                    'source_type': 'image',
                    'destination_type': 'volume',
                    'device_name': 'vda',
                    'boot_index': 0,
                    'volume_size': 3,
                    'volume_type': 'fake_lvm_1'
                }))
        bdm2 = objects.BlockDeviceMapping(
            **fake_block_device.AnonFakeDbBlockDeviceDict(
                {
                    'uuid': uuids.image_id,
                    'source_type': 'snapshot',
                    'destination_type': 'volume',
                    'device_name': 'vdb',
                    'boot_index': 1,
                    'volume_size': 3,
                    'volume_type': 'fake_lvm_1'
                }))
        bdms = [bdm1, bdm2]

        with test.nested(
                mock.patch.object(cinder.API, 'get_all_volume_types',
                                  return_value=volume_types),
                mock.patch.object(compute_api.API,
                                  '_check_requested_volume_type')) as (
                get_all_vol_types, vol_type_requested):

            image_cache = volumes = {}
            self.compute_api._validate_bdm(self.context, instance,
                                           instance_type, bdms, image_cache,
                                           volumes)

            get_all_vol_types.assert_called_once_with(self.context)

            vol_type_requested.assert_any_call(bdms[0], volume_type,
                                               volume_types)
            vol_type_requested.assert_any_call(bdms[1], volume_type,
                                               volume_types)

    @mock.patch('nova.compute.api.API._get_image')
    def test_validate_bdm_missing_volume_size(self, mock_get_image):
        """Tests that _validate_bdm fail if there volume_size not provided
        """
        instance = self._create_instance_obj()
        # first we test the case of instance.image_ref == bdm.image_id
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(
                boot_index=0, image_id=instance.image_ref,
                source_type='image', destination_type='volume',
                volume_type=None, snapshot_id=None, volume_id=None,
                volume_size=None)])
        image_cache = volumes = {}
        self.assertRaises(exception.InvalidBDM,
                          self.compute_api._validate_bdm,
                          self.context, instance, objects.Flavor(),
                          bdms, image_cache, volumes)
        self.assertEqual(0, mock_get_image.call_count)
        # then we test the case of instance.image_ref != bdm.image_id
        image_id = uuids.image_id
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(
                boot_index=0, image_id=image_id,
                source_type='image', destination_type='volume',
                volume_type=None, snapshot_id=None, volume_id=None,
                volume_size=None)])
        self.assertRaises(exception.InvalidBDM,
                          self.compute_api._validate_bdm,
                          self.context, instance, objects.Flavor(),
                          bdms, image_cache, volumes)
        mock_get_image.assert_called_once_with(self.context, image_id)

    @mock.patch('nova.compute.api.API._get_image')
    def test_validate_bdm_disk_bus(self, mock_get_image):
        """Tests that _validate_bdm fail if an invalid disk_bus is provided
        """
        instance = self._create_instance_obj()
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(
                boot_index=0, image_id=instance.image_ref,
                source_type='image', destination_type='volume',
                volume_type=None, snapshot_id=None, volume_id=None,
                volume_size=1, disk_bus='virtio-scsi')])
        image_cache = volumes = {}
        self.assertRaises(exception.InvalidBDMDiskBus,
                          self.compute_api._validate_bdm,
                          self.context, instance, objects.Flavor(),
                          bdms, image_cache, volumes)

    def test_the_specified_volume_type_id_assignment_to_name(self):
        """Test _check_requested_volume_type method is called, if the user
        is using the volume type ID, assign volume_type to volume type name.
        """
        volume_type = 'fake_volume_type_id_1'
        volume_types = [{'id': 'fake_volume_type_id_1', 'name': 'fake_lvm_1'},
                        {'id': 'fake_volume_type_id_2', 'name': 'fake_lvm_2'}]

        bdms = [objects.BlockDeviceMapping(
            **fake_block_device.AnonFakeDbBlockDeviceDict(
                {
                    'uuid': uuids.image_id,
                    'source_type': 'image',
                    'destination_type': 'volume',
                    'device_name': 'vda',
                    'boot_index': 0,
                    'volume_size': 3,
                    'volume_type': 'fake_volume_type_id_1'
                }))]

        self.compute_api._check_requested_volume_type(bdms[0],
                                                      volume_type,
                                                      volume_types)
        self.assertEqual(bdms[0].volume_type, volume_types[0]['name'])

    def _test_provision_instances_with_cinder_error(self,
                                                    expected_exception):
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects.Instance, 'create')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        def do_test(
                mock_req_spec_from_components, _mock_create,
                mock_check_num_inst_quota):
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
                            'pci_requests': None,
                            'port_resource_requests': None}
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
            trusted_certs = None

            self.assertRaises(expected_exception,
                              self.compute_api._provision_instances, ctxt,
                              flavor, min_count, max_count, base_options,
                              boot_meta, security_groups, block_device_mapping,
                              shutdown_terminate, instance_group,
                              check_server_group_quota, filter_properties,
                              None, objects.TagList(), trusted_certs, False)

        do_test()

    @mock.patch.object(cinder.API, 'get',
             side_effect=exception.CinderConnectionFailed(reason='error'))
    def test_provision_instances_with_cinder_down(self, mock_get):
        self._test_provision_instances_with_cinder_error(
            expected_exception=exception.CinderConnectionFailed)

    @mock.patch.object(cinder.API, 'get', new=mock.Mock(
        return_value={'id': '1', 'multiattach': False}))
    @mock.patch.object(cinder.API, 'check_availability_zone', new=mock.Mock())
    @mock.patch.object(cinder.API, 'attachment_create', new=mock.Mock(
        side_effect=exception.InvalidInput(reason='error')))
    def test_provision_instances_with_error_volume(self):
        self._test_provision_instances_with_cinder_error(
            expected_exception=exception.InvalidVolume)

    @mock.patch('nova.objects.RequestSpec.from_components')
    @mock.patch('nova.objects.BuildRequest')
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.objects.InstanceMapping.create')
    def test_provision_instances_with_keypair(self, mock_im, mock_instance,
                                              mock_br, mock_rs):
        fake_keypair = objects.KeyPair(name='test')
        inst_type = self._create_flavor()

        @mock.patch.object(self.compute_api, '_get_volumes_for_bdms')
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping',
                           new=mock.MagicMock())
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch('nova.network.security_group_api')
        @mock.patch.object(self.compute_api,
                           'create_db_entry_for_new_instance')
        @mock.patch.object(self.compute_api,
                           '_bdm_validate_set_size_and_instance')
        def do_test(mock_bdm_v, mock_cdb, mock_sg, mock_cniq, mock_get_vols):
            mock_cniq.return_value = 1
            self.compute_api._provision_instances(self.context,
                                                  inst_type,
                                                  1, 1, mock.MagicMock(),
                                                  {}, None,
                                                  None, None, None, {}, None,
                                                  fake_keypair,
                                                  objects.TagList(), None,
                                                  False)
            self.assertEqual(
                'test',
                mock_instance.return_value.keypairs.objects[0].name)
            self.compute_api._provision_instances(self.context,
                                                  inst_type,
                                                  1, 1, mock.MagicMock(),
                                                  {}, None,
                                                  None, None, None, {}, None,
                                                  None, objects.TagList(),
                                                  None, False)
            self.assertEqual(
                0,
                len(mock_instance.return_value.keypairs.objects))

        do_test()

    @mock.patch('nova.accelerator.cyborg.get_device_profile_request_groups')
    @mock.patch('nova.objects.RequestSpec.from_components')
    @mock.patch('nova.objects.BuildRequest')
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.objects.InstanceMapping.create')
    def _test_provision_instances_with_accels(self,
        instance_type, dp_request_groups, prev_request_groups,
        mock_im, mock_instance, mock_br, mock_rs, mock_get_dp):

        @mock.patch.object(self.compute_api, '_get_volumes_for_bdms')
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping',
                           new=mock.MagicMock())
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch('nova.network.security_group_api')
        @mock.patch.object(self.compute_api,
                           'create_db_entry_for_new_instance')
        @mock.patch.object(self.compute_api,
                           '_bdm_validate_set_size_and_instance')
        def do_test(mock_bdm_v, mock_cdb, mock_sg, mock_cniq, mock_get_vols):
            mock_cniq.return_value = 1
            self.compute_api._provision_instances(self.context,
                                                  instance_type,
                                                  1, 1, mock.MagicMock(),
                                                  {}, None,
                                                  None, None, None, {}, None,
                                                  None,
                                                  objects.TagList(), None,
                                                  False)

        mock_get_dp.return_value = dp_request_groups
        fake_rs = fake_request_spec.fake_spec_obj()
        fake_rs.requested_resources = prev_request_groups
        mock_rs.return_value = fake_rs
        do_test()
        return mock_get_dp, fake_rs

    def test_provision_instances_with_accels_ok(self):
        # If extra_specs has accel spec, device profile's request_groups
        # should be obtained, and added to reqspec's requested_resources.
        dp_name = 'mydp'
        extra_specs = {'extra_specs': {'accel:device_profile': dp_name}}
        instance_type = self._create_flavor(**extra_specs)

        prev_groups = [objects.RequestGroup(requester_id='prev0'),
                       objects.RequestGroup(requester_id='prev1')]
        dp_groups = [objects.RequestGroup(requester_id='deviceprofile2'),
                     objects.RequestGroup(requester_id='deviceprofile3')]

        mock_get_dp, fake_rs = self._test_provision_instances_with_accels(
            instance_type, dp_groups, prev_groups)
        mock_get_dp.assert_called_once_with(self.context, dp_name)
        self.assertEqual(prev_groups + dp_groups, fake_rs.requested_resources)

    def test_provision_instances_with_accels_no_dp(self):
        # If extra specs has no accel spec, no attempt should be made to
        # get device profile's request_groups, and reqspec.requested_resources
        # should be left unchanged.
        instance_type = self._create_flavor()
        prev_groups = [objects.RequestGroup(requester_id='prev0'),
                       objects.RequestGroup(requester_id='prev1')]
        mock_get_dp, fake_rs = self._test_provision_instances_with_accels(
            instance_type, [], prev_groups)
        mock_get_dp.assert_not_called()
        self.assertEqual(prev_groups, fake_rs.requested_resources)

    def test_provision_instances_creates_build_request(self):
        @mock.patch.object(self.compute_api, '_get_volumes_for_bdms')
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping')
        @mock.patch.object(objects.Instance, 'create')
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        def do_test(mock_req_spec_from_components, mock_check_num_inst_quota,
                    mock_inst_create, mock_create_rs_br_im, mock_get_volumes):

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
                            'pci_requests': None,
                            'port_resource_requests': None}
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
            instance_tags = objects.TagList(objects=[objects.Tag(tag='tag')])
            shutdown_terminate = True
            trusted_certs = None
            instance_group = None
            check_server_group_quota = False
            filter_properties = {'scheduler_hints': None,
                    'instance_type': flavor}

            with mock.patch.object(
                    self.compute_api,
                    '_bdm_validate_set_size_and_instance',
                    return_value=block_device_mappings) as validate_bdm:
                instances_to_build = self.compute_api._provision_instances(
                        ctxt, flavor,
                        min_count, max_count, base_options, boot_meta,
                        security_groups, block_device_mappings,
                        shutdown_terminate, instance_group,
                        check_server_group_quota, filter_properties, None,
                        instance_tags, trusted_certs, False)
            validate_bdm.assert_has_calls([mock.call(
                ctxt, test.MatchType(objects.Instance), flavor,
                block_device_mappings, {}, mock_get_volumes.return_value,
                False)] * max_count)

            for rs, br, im in instances_to_build:
                self.assertIsInstance(br.instance, objects.Instance)
                self.assertTrue(uuidutils.is_uuid_like(br.instance.uuid))
                self.assertEqual(base_options['project_id'],
                                 br.instance.project_id)
                self.assertEqual(1, br.block_device_mappings[0].id)
                self.assertEqual(br.instance.uuid, br.tags[0].resource_id)
                mock_create_rs_br_im.assert_any_call(ctxt, rs, br, im)

        do_test()

    def test_provision_instances_creates_instance_mapping(self):
        @mock.patch.object(self.compute_api, '_get_volumes_for_bdms')
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping',
                           new=mock.MagicMock())
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects.Instance, 'create', new=mock.MagicMock())
        @mock.patch.object(self.compute_api, '_validate_bdm',
                new=mock.MagicMock())
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch('nova.objects.InstanceMapping')
        def do_test(mock_inst_mapping, mock_rs, mock_check_num_inst_quota,
                    mock_get_vols):
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
                            'pci_requests': None,
                            'port_resource_requests': None}
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
            trusted_certs = None

            instances_to_build = (
                self.compute_api._provision_instances(ctxt, flavor,
                    min_count, max_count, base_options, boot_meta,
                    security_groups, block_device_mapping, shutdown_terminate,
                    instance_group, check_server_group_quota,
                    filter_properties, None, objects.TagList(), trusted_certs,
                    False))
            rs, br, im = instances_to_build[0]
            self.assertTrue(uuidutils.is_uuid_like(br.instance.uuid))
            self.assertEqual(br.instance_uuid, im.instance_uuid)

            self.assertEqual(br.instance.uuid,
                             inst_mapping_mock.instance_uuid)
            self.assertIsNone(inst_mapping_mock.cell_mapping)
            self.assertEqual(ctxt.project_id, inst_mapping_mock.project_id)
            # Verify that the instance mapping created has user_id populated.
            self.assertEqual(ctxt.user_id, inst_mapping_mock.user_id)
        do_test()

    @mock.patch.object(cinder.API, 'get',
                       return_value={'id': '1', 'multiattach': False})
    @mock.patch.object(cinder.API, 'check_availability_zone',)
    @mock.patch.object(cinder.API, 'attachment_create',
                       side_effect=[{'id': uuids.attachment_id},
                                    exception.InvalidInput(reason='error')])
    @mock.patch.object(objects.BlockDeviceMapping, 'save')
    def test_provision_instances_cleans_up_when_volume_invalid_new_flow(self,
            _mock_bdm, _mock_cinder_attach_create,
            _mock_cinder_check_availability_zone, _mock_cinder_get):
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping')
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch.object(objects, 'Instance')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch.object(objects, 'BuildRequest')
        @mock.patch.object(objects, 'InstanceMapping')
        def do_test(mock_inst_mapping, mock_build_req,
                mock_req_spec_from_components, mock_inst,
                mock_check_num_inst_quota, mock_create_rs_br_im):

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
            flavor = self._create_flavor(extra_specs={})
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
                            'pci_requests': None,
                            'port_resource_requests': None}
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
            trusted_certs = None
            self.assertRaises(exception.InvalidVolume,
                              self.compute_api._provision_instances, ctxt,
                              flavor, min_count, max_count, base_options,
                              boot_meta, security_groups, block_device_mapping,
                              shutdown_terminate, instance_group,
                              check_server_group_quota, filter_properties,
                              None, tags, trusted_certs, False)
            # First instance, build_req, mapping is created and destroyed
            mock_create_rs_br_im.assert_called_once_with(ctxt, req_spec_mock,
                                                         build_req_mocks[0],
                                                         inst_map_mocks[0])
            self.assertTrue(build_req_mocks[0].destroy.called)
            self.assertTrue(inst_map_mocks[0].destroy.called)
            # Second instance, build_req, mapping is not created nor destroyed
            self.assertFalse(inst_mocks[1].create.called)
            self.assertFalse(inst_mocks[1].destroy.called)
            self.assertFalse(build_req_mocks[1].destroy.called)
            self.assertFalse(inst_map_mocks[1].destroy.called)

        do_test()

    def test_provision_instances_creates_reqspec_with_secgroups(self):
        @mock.patch.object(self.compute_api,
                           '_create_reqspec_buildreq_instmapping',
                           new=mock.MagicMock())
        @mock.patch('nova.compute.utils.check_num_instances_quota')
        @mock.patch('nova.network.security_group_api'
                    '.populate_security_groups')
        @mock.patch.object(compute_api, 'objects')
        @mock.patch.object(self.compute_api,
                           'create_db_entry_for_new_instance',
                           new=mock.MagicMock())
        @mock.patch.object(self.compute_api,
                           '_bdm_validate_set_size_and_instance',
                           new=mock.MagicMock())
        def test(mock_objects, mock_secgroup, mock_cniq):
            ctxt = context.RequestContext('fake-user', 'fake-project')
            mock_cniq.return_value = 1
            inst_type = self._create_flavor()
            self.compute_api._provision_instances(ctxt, inst_type, None, None,
                                                  mock.MagicMock(), None, None,
                                                  [], None, None, None, None,
                                                  None, objects.TagList(),
                                                  None, False)
            secgroups = mock_secgroup.return_value
            mock_objects.RequestSpec.from_components.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, mock.ANY, mock.ANY, mock.ANY,
                mock.ANY, mock.ANY, mock.ANY,
                security_groups=secgroups, port_resource_requests=mock.ANY)
        test()

    def _test_rescue(self, vm_state=vm_states.ACTIVE, rescue_password=None,
                     rescue_image=None, clean_shutdown=True):
        instance = self._create_instance_obj(params={'vm_state': vm_state})
        rescue_image_meta_obj = image_meta_obj.ImageMeta.from_dict({})
        bdms = []
        with test.nested(
            mock.patch.object(objects.BlockDeviceMappingList,
                              'get_by_instance_uuid', return_value=bdms),
            mock.patch.object(compute_utils, 'is_volume_backed_instance',
                              return_value=False),
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'rescue_instance'),
            mock.patch.object(objects.ImageMeta, 'from_image_ref',
                              return_value=rescue_image_meta_obj),
        ) as (
            bdm_get_by_instance_uuid, volume_backed_inst, instance_save,
            record_action_start, rpcapi_rescue_instance, mock_find_image_ref,
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
            if rescue_image:
                mock_find_image_ref.assert_called_once_with(
                    self.context, self.compute_api.image_api, rescue_image)

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

    @mock.patch('nova.objects.image_meta.ImageMeta.from_image_ref')
    @mock.patch('nova.objects.compute_node.ComputeNode'
                '.get_by_host_and_nodename')
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=True)
    @mock.patch('nova.objects.block_device.BlockDeviceMappingList'
                '.get_by_instance_uuid')
    def test_rescue_bfv_with_required_trait(self, mock_get_bdms,
            mock_is_volume_backed, mock_get_cn, mock_image_meta_obj_from_ref):
        instance = self._create_instance_obj()
        bdms = objects.BlockDeviceMappingList(objects=[
                objects.BlockDeviceMapping(
                    boot_index=0, image_id=uuids.image_id, source_type='image',
                    destination_type='volume', volume_type=None,
                    snapshot_id=None, volume_id=uuids.volume_id,
                    volume_size=None)])
        rescue_image_meta_obj = image_meta_obj.ImageMeta.from_dict({})

        with test.nested(
            mock.patch.object(self.compute_api.placementclient,
                              'get_provider_traits'),
            mock.patch.object(self.compute_api.volume_api, 'get'),
            mock.patch.object(self.compute_api.volume_api, 'check_attached'),
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'rescue_instance')
        ) as (
            mock_get_traits, mock_get_volume, mock_check_attached,
            mock_instance_save, mock_record_start, mock_rpcapi_rescue
        ):
            # Mock out the returned compute node, image, bdms and volume
            mock_get_cn.return_value = mock.Mock(uuid=uuids.cn)
            mock_image_meta_obj_from_ref.return_value = rescue_image_meta_obj
            mock_get_bdms.return_value = bdms
            mock_get_volume.return_value = mock.sentinel.volume

            # Ensure the required trait is returned, allowing BFV rescue
            mock_trait_info = mock.Mock(traits=[ot.COMPUTE_RESCUE_BFV])
            mock_get_traits.return_value = mock_trait_info

            # Try to rescue the instance
            self.compute_api.rescue(self.context, instance,
                                    rescue_image_ref=uuids.rescue_image_id,
                                    allow_bfv_rescue=True)

            # Assert all of the calls made in the compute API
            mock_get_bdms.assert_called_once_with(self.context, instance.uuid)
            mock_get_volume.assert_called_once_with(
                self.context, uuids.volume_id)
            mock_check_attached.assert_called_once_with(
                self.context, mock.sentinel.volume)
            mock_is_volume_backed.assert_called_once_with(
                self.context, instance, bdms)
            mock_get_cn.assert_called_once_with(
                self.context, instance.host, instance.node)
            mock_get_traits.assert_called_once_with(self.context, uuids.cn)
            mock_instance_save.assert_called_once_with(
                expected_task_state=[None])
            mock_record_start.assert_called_once_with(
                self.context, instance, instance_actions.RESCUE)
            mock_rpcapi_rescue.assert_called_once_with(
                self.context, instance=instance, rescue_password=None,
                rescue_image_ref=uuids.rescue_image_id, clean_shutdown=True)

            # Assert that the instance task state as set in the compute API
            self.assertEqual(task_states.RESCUING, instance.task_state)

    @mock.patch('nova.objects.compute_node.ComputeNode'
                '.get_by_host_and_nodename')
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=True)
    @mock.patch('nova.objects.block_device.BlockDeviceMappingList'
                '.get_by_instance_uuid')
    def test_rescue_bfv_without_required_trait(self, mock_get_bdms,
                                               mock_is_volume_backed,
                                               mock_get_cn):
        instance = self._create_instance_obj()
        bdms = objects.BlockDeviceMappingList(objects=[
                objects.BlockDeviceMapping(
                    boot_index=0, image_id=uuids.image_id, source_type='image',
                    destination_type='volume', volume_type=None,
                    snapshot_id=None, volume_id=uuids.volume_id,
                    volume_size=None)])
        with test.nested(
            mock.patch.object(self.compute_api.placementclient,
                              'get_provider_traits'),
            mock.patch.object(self.compute_api.volume_api, 'get'),
            mock.patch.object(self.compute_api.volume_api, 'check_attached'),
        ) as (
            mock_get_traits, mock_get_volume, mock_check_attached
        ):
            # Mock out the returned compute node, bdms and volume
            mock_get_bdms.return_value = bdms
            mock_get_volume.return_value = mock.sentinel.volume
            mock_get_cn.return_value = mock.Mock(uuid=uuids.cn)

            # Ensure the required trait is not returned, denying BFV rescue
            mock_trait_info = mock.Mock(traits=[])
            mock_get_traits.return_value = mock_trait_info

            # Assert that any attempt to rescue a bfv instance on a compute
            # node that does not report the COMPUTE_RESCUE_BFV trait fails and
            # raises InstanceNotRescuable
            self.assertRaises(exception.InstanceNotRescuable,
                              self.compute_api.rescue, self.context, instance,
                              rescue_image_ref=None, allow_bfv_rescue=True)

            # Assert the calls made in the compute API prior to the failure
            mock_get_bdms.assert_called_once_with(self.context, instance.uuid)
            mock_get_volume.assert_called_once_with(
                self.context, uuids.volume_id)
            mock_check_attached.assert_called_once_with(
                self.context, mock.sentinel.volume)
            mock_is_volume_backed.assert_called_once_with(
                self.context, instance, bdms)
            mock_get_cn.assert_called_once_with(
                self.context, instance.host, instance.node)
            mock_get_traits.assert_called_once_with(
                self.context, uuids.cn)

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=True)
    @mock.patch('nova.objects.block_device.BlockDeviceMappingList'
                '.get_by_instance_uuid')
    def test_rescue_bfv_without_allow_flag(self, mock_get_bdms,
                                           mock_is_volume_backed):
        instance = self._create_instance_obj()
        bdms = objects.BlockDeviceMappingList(objects=[
                objects.BlockDeviceMapping(
                    boot_index=0, image_id=uuids.image_id, source_type='image',
                    destination_type='volume', volume_type=None,
                    snapshot_id=None, volume_id=uuids.volume_id,
                    volume_size=None)])
        with test.nested(
            mock.patch.object(self.compute_api.volume_api, 'get'),
            mock.patch.object(self.compute_api.volume_api, 'check_attached'),
        ) as (
            mock_get_volume, mock_check_attached
        ):
            # Mock out the returned bdms and volume
            mock_get_bdms.return_value = bdms
            mock_get_volume.return_value = mock.sentinel.volume

            # Assert that any attempt to rescue a bfv instance with
            # allow_bfv_rescue=False fails and raises InstanceNotRescuable
            self.assertRaises(exception.InstanceNotRescuable,
                              self.compute_api.rescue, self.context, instance,
                              rescue_image_ref=None, allow_bfv_rescue=False)

            # Assert the calls made in the compute API prior to the failure
            mock_get_bdms.assert_called_once_with(self.context, instance.uuid)
            mock_get_volume.assert_called_once_with(
                self.context, uuids.volume_id)
            mock_check_attached.assert_called_once_with(
                self.context, mock.sentinel.volume)
            mock_is_volume_backed.assert_called_once_with(
                self.context, instance, bdms)

    @mock.patch('nova.objects.image_meta.ImageMeta.from_image_ref')
    def test_rescue_from_image_ref_failure(self, mock_image_meta_obj_from_ref):
        instance = self._create_instance_obj()
        mock_image_meta_obj_from_ref.side_effect = [
            exception.ImageNotFound(image_id=mock.sentinel.rescue_image_ref),
            exception.ImageBadRequest(
                image_id=mock.sentinel.rescue_image_ref, response='bar')]

        # Assert that UnsupportedRescueImage is raised when from_image_ref
        # returns exception.ImageNotFound
        self.assertRaises(exception.UnsupportedRescueImage,
                          self.compute_api.rescue, self.context, instance,
                          rescue_image_ref=mock.sentinel.rescue_image_ref)

        # Assert that UnsupportedRescueImage is raised when from_image_ref
        # returns exception.ImageBadRequest
        self.assertRaises(exception.UnsupportedRescueImage,
                          self.compute_api.rescue, self.context, instance,
                          rescue_image_ref=mock.sentinel.rescue_image_ref)

        # Assert that we called from_image_ref using the provided ref
        mock_image_meta_obj_from_ref.assert_has_calls([
            mock.call(self.context, self.compute_api.image_api,
                mock.sentinel.rescue_image_ref),
            mock.call(self.context, self.compute_api.image_api,
                mock.sentinel.rescue_image_ref)])

    @mock.patch('nova.objects.image_meta.ImageMeta.from_image_ref')
    def test_rescue_using_volume_backed_snapshot(self,
            mock_image_meta_obj_from_ref):
        instance = self._create_instance_obj()
        rescue_image_obj = image_meta_obj.ImageMeta.from_dict(
            {'min_disk': 0, 'min_ram': 0,
             'properties': {'bdm_v2': True, 'block_device_mapping': [{}]},
             'size': 0, 'status': 'active'})
        mock_image_meta_obj_from_ref.return_value = rescue_image_obj

        # Assert that UnsupportedRescueImage is raised
        self.assertRaises(exception.UnsupportedRescueImage,
                          self.compute_api.rescue, self.context, instance,
                          rescue_image_ref=mock.sentinel.rescue_image_ref)

        # Assert that we called from_image_ref using the provided ref
        mock_image_meta_obj_from_ref.assert_called_once_with(
            self.context, self.compute_api.image_api,
            mock.sentinel.rescue_image_ref)

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
            self.compute_api.set_admin_password(self.context, instance, 'pass')
            # make our assertions
            instance_save_mock.assert_called_once_with(
                expected_task_state=[None])
            record_mock.assert_called_once_with(
                self.context, instance, instance_actions.CHANGE_PASSWORD)
            compute_rpcapi_mock.assert_called_once_with(
                self.context, instance=instance, new_pass='pass')

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
            image_cache = volumes = {}
            bdms = self.compute_api._bdm_validate_set_size_and_instance(
                self.context, instance, instance_type, block_device_mapping,
                image_cache, volumes)

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
        mock_get.return_value = objects.InstanceList(objects=[]), list()
        api = compute_api.API()
        api.get_all(self.context, search_opts={'tenant_id': 'foo'})
        filters = mock_get.call_args_list[0][0][1]
        self.assertEqual({'project_id': 'foo'}, filters)

    def test_populate_instance_names_host_name(self):
        params = dict(display_name="vm1")
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 1, 0)
        self.assertEqual('vm1', instance.hostname)

    def test_populate_instance_names_host_name_is_empty(self):
        params = dict(display_name=u'\u865a\u62df\u673a\u662f\u4e2d\u6587')
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 1, 0)
        self.assertEqual('Server-%s' % instance.uuid, instance.hostname)

    def test_populate_instance_names_host_name_multi(self):
        params = dict(display_name="vm")
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 2, 1)
        self.assertEqual('vm-2', instance.hostname)

    def test_populate_instance_names_host_name_is_empty_multi(self):
        params = dict(display_name=u'\u865a\u62df\u673a\u662f\u4e2d\u6587')
        instance = self._create_instance_obj(params=params)
        self.compute_api._populate_instance_names(instance, 2, 1)
        self.assertEqual('Server-%s' % instance.uuid, instance.hostname)

    def test_host_statuses(self):
        five_min_ago = timeutils.utcnow() - datetime.timedelta(minutes=5)
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
                             disabled=False, last_seen_up=five_min_ago,
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
        mock_lm_abort.assert_called_once_with(self.context, instance,
                                              migration.id)

    @mock.patch('nova.compute.api.API._record_action_start')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'live_migration_abort')
    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    def test_live_migrate_abort_in_queue_succeeded(self,
                                                   mock_get_migration,
                                                   mock_lm_abort,
                                                   mock_rec_action):
        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING
        for migration_status in ('queued', 'preparing'):
            migration = self._get_migration(
                21, migration_status, 'live-migration')
            mock_get_migration.return_value = migration
            self.compute_api.live_migrate_abort(self.context,
                                                instance,
                                                migration.id,
                                                support_abort_in_queue=True)
            mock_rec_action.assert_called_once_with(
                self.context, instance, instance_actions.LIVE_MIGRATION_CANCEL)
            mock_lm_abort.assert_called_once_with(self.context, instance,
                                                  migration.id)
            mock_get_migration.reset_mock()
            mock_rec_action.reset_mock()
            mock_lm_abort.reset_mock()

    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    def test_live_migration_abort_in_queue_old_microversion_fails(
            self, mock_get_migration):
        instance = self._create_instance_obj()
        instance.task_state = task_states.MIGRATING
        migration = self._get_migration(21, 'queued', 'live-migration')
        mock_get_migration.return_value = migration
        self.assertRaises(exception.InvalidMigrationState,
                          self.compute_api.live_migrate_abort, self.context,
                          instance, migration.id,
                          support_abort_in_queue=False)

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

    @mock.patch.object(objects.InstanceMapping, 'save')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_update_queued_for_deletion(self, mock_get, mock_save):
        uuid = uuids.inst
        inst = objects.Instance(uuid=uuid)
        im = objects.InstanceMapping(instance_uuid=uuid)
        mock_get.return_value = im
        self.compute_api._update_queued_for_deletion(self.context, inst, True)
        self.assertTrue(im.queued_for_delete)
        mock_get.assert_called_once_with(self.context, inst.uuid)
        mock_save.assert_called_once_with()

    @mock.patch.object(objects.InstanceMappingList,
                       'get_not_deleted_by_cell_and_project')
    def test_generate_minimal_construct_for_down_cells(self, mock_get_ims):
        im1 = objects.InstanceMapping(instance_uuid=uuids.inst1, cell_id=1,
            project_id='fake', created_at=None, queued_for_delete=False)
        mock_get_ims.return_value = [im1]
        down_cell_uuids = [uuids.cell1, uuids.cell2, uuids.cell3]
        result = self.compute_api._generate_minimal_construct_for_down_cells(
            self.context, down_cell_uuids, [self.context.project_id], None)
        for inst in result:
            self.assertEqual(inst.uuid, im1.instance_uuid)
            self.assertIn('created_at', inst)
            # minimal construct doesn't contain the usual keys
            self.assertNotIn('display_name', inst)
        self.assertEqual(3, mock_get_ims.call_count)

    @mock.patch.object(objects.InstanceMappingList,
                       'get_not_deleted_by_cell_and_project')
    def test_generate_minimal_construct_for_down_cells_limited(self,
                                                               mock_get_ims):
        im1 = objects.InstanceMapping(instance_uuid=uuids.inst1, cell_id=1,
            project_id='fake', created_at=None, queued_for_delete=False)
        # If this gets called a third time, it'll explode, thus asserting
        # that we break out of the loop once the limit is reached
        mock_get_ims.side_effect = [[im1, im1], [im1]]
        down_cell_uuids = [uuids.cell1, uuids.cell2, uuids.cell3]
        result = self.compute_api._generate_minimal_construct_for_down_cells(
            self.context, down_cell_uuids, [self.context.project_id], 3)
        for inst in result:
            self.assertEqual(inst.uuid, im1.instance_uuid)
            self.assertIn('created_at', inst)
            # minimal construct doesn't contain the usual keys
            self.assertNotIn('display_name', inst)
        # Two instances at limit 3 from first cell, one at limit 1 from the
        # second, no third call.
        self.assertEqual(2, mock_get_ims.call_count)
        mock_get_ims.assert_has_calls([
            mock.call(self.context, uuids.cell1, [self.context.project_id],
                      limit=3),
            mock.call(self.context, uuids.cell2, [self.context.project_id],
                      limit=1),
        ])

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.InstanceMappingList,
                       'get_not_deleted_by_cell_and_project')
    def test_get_all_without_cell_down_support(self, mock_get_ims,
                                               mock_buildreq_get):
        mock_buildreq_get.return_value = objects.BuildRequestList()
        im1 = objects.InstanceMapping(instance_uuid=uuids.inst1, cell_id=1,
            project_id='fake', created_at=None, queued_for_delete=False)
        mock_get_ims.return_value = [im1]
        cell_instances = self._list_of_instances(2)
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances), [uuids.cell1]
            insts = self.compute_api.get_all(self.context,
                cell_down_support=False)
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(self.context, {}, None, None,
                fields, None, None, cell_down_support=False)
            for i, instance in enumerate(cell_instances):
                self.assertEqual(instance, insts[i])
            mock_get_ims.assert_not_called()

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.InstanceMappingList,
                       'get_not_deleted_by_cell_and_project')
    def test_get_all_with_cell_down_support(self, mock_get_ims,
                                            mock_buildreq_get):
        mock_buildreq_get.return_value = objects.BuildRequestList()
        im = objects.InstanceMapping(context=self.context,
            instance_uuid=uuids.inst1, cell_id=1,
            project_id='fake', created_at=None, queued_for_delete=False)
        mock_get_ims.return_value = [im]
        cell_instances = self._list_of_instances(2)
        full_instances = objects.InstanceList(self.context,
            objects=cell_instances)
        inst = objects.Instance(context=self.context, uuid=im.instance_uuid,
            project_id=im.project_id, created_at=im.created_at)
        partial_instances = objects.InstanceList(self.context, objects=[inst])
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances), [uuids.cell1]
            insts = self.compute_api.get_all(self.context, limit=3,
                cell_down_support=True)
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(self.context, {},
                                                  3, None, fields, None, None,
                                                  cell_down_support=True)
            for i, instance in enumerate(partial_instances + full_instances):
                self.assertTrue(obj_base.obj_equal_prims(instance, insts[i]))
            # With an original limit of 3, and 0 build requests but 2 instances
            # from "up" cells, we should only get at most 1 instance mapping
            # to fill the limit.
            mock_get_ims.assert_called_once_with(self.context, uuids.cell1,
                                                 self.context.project_id,
                                                 limit=1)

    @mock.patch.object(objects.BuildRequestList, 'get_by_filters')
    @mock.patch.object(objects.InstanceMappingList,
                       'get_not_deleted_by_cell_and_project')
    def test_get_all_with_cell_down_support_all_tenants(self, mock_get_ims,
                                                        mock_buildreq_get):
        mock_buildreq_get.return_value = objects.BuildRequestList()
        im = objects.InstanceMapping(context=self.context,
            instance_uuid=uuids.inst1, cell_id=1,
            project_id='fake', created_at=None, queued_for_delete=False)
        mock_get_ims.return_value = [im]
        inst = objects.Instance(context=self.context, uuid=im.instance_uuid,
            project_id=im.project_id, created_at=im.created_at)
        partial_instances = objects.InstanceList(self.context, objects=[inst])
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                partial_instances), [uuids.cell1]
            insts = self.compute_api.get_all(self.context, limit=3,
                cell_down_support=True, all_tenants=True)
            for i, instance in enumerate(partial_instances):
                self.assertTrue(obj_base.obj_equal_prims(instance, insts[i]))
            # get_not_deleted_by_cell_and_project is called with None
            # project_id because of the all_tenants case.
            mock_get_ims.assert_called_once_with(self.context, uuids.cell1,
                                                 None,
                                                 limit=3)

    @mock.patch('nova.compute.api.API._save_user_id_in_instance_mapping',
                new=mock.MagicMock())
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_from_cell_success(self, mock_get_inst):
        cell_mapping = objects.CellMapping(uuid=uuids.cell1,
                                           name='1', id=1)
        im = objects.InstanceMapping(instance_uuid=uuids.inst,
                                     cell_mapping=cell_mapping)
        mock_get_inst.return_value = objects.Instance(uuid=uuids.inst)
        result = self.compute_api._get_instance_from_cell(self.context,
            im, [], True)
        self.assertEqual(uuids.inst, result.uuid)
        mock_get_inst.assert_called_once()

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_from_cell_failure(self, mock_get_inst):
        # Make sure InstanceNotFound is bubbled up and not treated like
        # other errors
        mock_get_inst.side_effect = exception.InstanceNotFound(
            instance_id=uuids.inst)
        cell_mapping = objects.CellMapping(uuid=uuids.cell1,
                                           name='1', id=1)
        im = objects.InstanceMapping(instance_uuid=uuids.inst,
                                     cell_mapping=cell_mapping)
        exp = self.assertRaises(exception.InstanceNotFound,
            self.compute_api._get_instance_from_cell, self.context,
            im, [], False)
        self.assertIn('could not be found', six.text_type(exp))

    @mock.patch('nova.compute.api.API._save_user_id_in_instance_mapping')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_instance_with_cell_down_support(self, mock_sg, mock_rs,
                                                 mock_save_uid):
        cell_mapping = objects.CellMapping(uuid=uuids.cell1,
                                           name='1', id=1)
        im1 = objects.InstanceMapping(instance_uuid=uuids.inst1,
                                      cell_mapping=cell_mapping,
                                      queued_for_delete=True)
        im2 = objects.InstanceMapping(instance_uuid=uuids.inst2,
                                      cell_mapping=cell_mapping,
                                      queued_for_delete=False,
                                      project_id='fake',
                                      created_at=None)
        mock_sg.return_value = {
            uuids.cell1: context.did_not_respond_sentinel
        }

        # No cell down support, error means we return 500
        exp = self.assertRaises(exception.NovaException,
            self.compute_api._get_instance_from_cell, self.context,
            im1, [], False)
        self.assertIn('info is not available', six.text_type(exp))

        # Have cell down support, error + queued_for_delete = NotFound
        exp = self.assertRaises(exception.InstanceNotFound,
            self.compute_api._get_instance_from_cell, self.context,
            im1, [], True)
        self.assertIn('could not be found', six.text_type(exp))

        # Have cell down support, error + archived reqspec = NotFound
        mock_rs.side_effect = exception.RequestSpecNotFound(
            instance_uuid=uuids.inst2)
        exp = self.assertRaises(exception.InstanceNotFound,
            self.compute_api._get_instance_from_cell, self.context,
            im2, [], True)
        self.assertIn('could not be found', six.text_type(exp))

        # Have cell down support, error + reqspec + not queued_for_delete
        # means we return a minimal instance
        req_spec = objects.RequestSpec(instance_uuid=uuids.inst2,
                                       user_id='fake',
                                       flavor=objects.Flavor(name='fake1'),
                                       image=objects.ImageMeta(id=uuids.image,
                                                               name='fake1'),
                                       availability_zone='nova')
        mock_rs.return_value = req_spec
        mock_rs.side_effect = None
        result = self.compute_api._get_instance_from_cell(self.context,
            im2, [], True)
        self.assertIn('user_id', result)
        self.assertNotIn('display_name', result)
        self.assertEqual(uuids.inst2, result.uuid)
        self.assertEqual('nova', result.availability_zone)
        self.assertEqual(uuids.image, result.image_ref)
        # Verify that user_id is populated during a compute_api.get().
        mock_save_uid.assert_called_once_with(im2, result)

        # Same as above, but boot-from-volume where image is not None but the
        # id of the image is not set.
        req_spec.image = objects.ImageMeta(name='fake1')
        result = self.compute_api._get_instance_from_cell(self.context,
            im2, [], True)
        self.assertIsNone(result.image_ref)

        # Same as above, but boot-from-volume where image is None
        req_spec.image = None
        result = self.compute_api._get_instance_from_cell(self.context,
            im2, [], True)
        self.assertIsNone(result.image_ref)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
            side_effect=exception.InstanceMappingNotFound(uuid='fake'))
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_no_mapping(self, mock_get_inst, mock_get_build_req,
            mock_get_inst_map):

        self.useFixture(nova_fixtures.AllServicesCurrent())
        # No Mapping means NotFound
        self.assertRaises(exception.InstanceNotFound,
                          self.compute_api.get, self.context,
                          uuids.inst_uuid)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_not_in_cell(self, mock_get_inst, mock_get_build_req,
                mock_get_inst_map):
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        mock_get_inst_map.return_value = objects.InstanceMapping(
                cell_mapping=None)
        mock_get_build_req.return_value = build_req_obj
        instance = build_req_obj.instance
        mock_get_inst.return_value = instance

        inst_from_build_req = self.compute_api.get(self.context, instance.uuid)
        mock_get_inst_map.assert_called_once_with(self.context,
                                                  instance.uuid)
        mock_get_build_req.assert_called_once_with(self.context,
                                                   instance.uuid)
        self.assertEqual(instance, inst_from_build_req)

    @mock.patch('nova.compute.api.API._save_user_id_in_instance_mapping',
                new=mock.MagicMock())
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_not_in_cell_buildreq_deleted_inst_in_cell(
            self, mock_get_inst, mock_get_build_req, mock_get_inst_map):
        # This test checks the following scenario:
        # The instance is not mapped to a cell, so it should be retrieved from
        # a BuildRequest object. However the BuildRequest does not exist
        # because the instance was put in a cell and mapped while while
        # attempting to get the BuildRequest. So pull the instance from the
        # cell.
        self.useFixture(nova_fixtures.AllServicesCurrent())
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        instance = build_req_obj.instance
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping(
            uuid=uuids.cell), instance_uuid=instance.uuid)

        mock_get_inst_map.side_effect = [
            objects.InstanceMapping(cell_mapping=None), inst_map]
        mock_get_build_req.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_get_inst.return_value = instance

        inst_from_get = self.compute_api.get(self.context, instance.uuid)

        inst_map_calls = [mock.call(self.context, instance.uuid),
                          mock.call(self.context, instance.uuid)]
        mock_get_inst_map.assert_has_calls(inst_map_calls)
        self.assertEqual(2, mock_get_inst_map.call_count)
        mock_get_build_req.assert_called_once_with(self.context,
                                                   instance.uuid)

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
        self.useFixture(nova_fixtures.AllServicesCurrent())
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        instance = build_req_obj.instance

        mock_get_inst_map.side_effect = [
            objects.InstanceMapping(cell_mapping=None),
            objects.InstanceMapping(cell_mapping=None)]
        mock_get_build_req.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_get_inst.return_value = instance

        self.assertRaises(exception.InstanceNotFound,
                          self.compute_api.get,
                          self.context, instance.uuid)

    @mock.patch('nova.objects.InstanceMapping.save')
    def test_save_user_id_in_instance_mapping(self, im_save):
        # Verify user_id is populated if it not set
        im = objects.InstanceMapping()
        i = objects.Instance(user_id='fake')
        self.compute_api._save_user_id_in_instance_mapping(im, i)
        self.assertEqual(im.user_id, i.user_id)
        im_save.assert_called_once_with()
        # Verify user_id is not saved if it is already set
        im_save.reset_mock()
        im.user_id = 'fake-other'
        self.compute_api._save_user_id_in_instance_mapping(im, i)
        self.assertNotEqual(im.user_id, i.user_id)
        im_save.assert_not_called()
        # Verify user_id is not saved if it is None
        im_save.reset_mock()
        im = objects.InstanceMapping()
        i = objects.Instance(user_id=None)
        self.compute_api._save_user_id_in_instance_mapping(im, i)
        self.assertNotIn('user_id', im)
        im_save.assert_not_called()

    @mock.patch('nova.compute.api.API._save_user_id_in_instance_mapping')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_get_instance_in_cell(self, mock_get_inst, mock_get_build_req,
            mock_get_inst_map, mock_save_uid):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        # This just checks that the instance is looked up normally and not
        # synthesized from a BuildRequest object. Verification of pulling the
        # instance from the proper cell will be added when that capability is.
        instance = self._create_instance_obj()
        build_req_obj = fake_build_request.fake_req_obj(self.context)
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping(
            uuid=uuids.cell), instance_uuid=instance.uuid)
        mock_get_inst_map.return_value = inst_map
        mock_get_build_req.return_value = build_req_obj
        mock_get_inst.return_value = instance

        returned_inst = self.compute_api.get(self.context, instance.uuid)
        mock_get_build_req.assert_not_called()
        mock_get_inst_map.assert_called_once_with(self.context,
                                                  instance.uuid)
        # Verify that user_id is populated during a compute_api.get().
        mock_save_uid.assert_called_once_with(inst_map, instance)
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
                self.context, objects=cell_instances), list()

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
                fields, ['baz'], ['desc'], cell_down_support=False)
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
            mock_inst_get.return_value = objects.InstanceList(self.context,
                objects=build_req_instances[:1] + cell_instances), list()

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
                fields, ['baz'], ['desc'], cell_down_support=False)
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
                self.context, objects=cell_instances), list()

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
                fields, ['baz'], ['desc'], cell_down_support=False)
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
            mock_inst_get.return_value = objects.InstanceList(
                                             self.context,
                                             objects=cell_instances), []

            instances = self.compute_api.get_all(
                self.context, search_opts={'foo': 'bar'},
                limit=10, marker='fake-marker', sort_keys=['baz'],
                sort_dirs=['desc'])

            for cm in mock_cm_get_all.return_value:
                mock_target_cell.assert_any_call(self.context, cm)

            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                mock.ANY, {'foo': 'bar'},
                8, None,
                fields, ['baz'], ['desc'], cell_down_support=False)
            for i, instance in enumerate(build_req_instances +
                                         cell_instances):
                self.assertEqual(instance, instances[i])

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_update_existing_instance_not_in_cell(self, mock_instmap_get,
                                                  mock_buildreq_get):
        mock_instmap_get.side_effect = exception.InstanceMappingNotFound(
            uuid='fake')
        self.useFixture(nova_fixtures.AllServicesCurrent())

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
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_update_existing_instance_in_cell(self, mock_instmap_get,
                                              mock_buildreq_get):
        inst_map = objects.InstanceMapping(cell_mapping=objects.CellMapping())
        mock_instmap_get.return_value = inst_map
        self.useFixture(nova_fixtures.AllServicesCurrent())

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
    def test_update_future_instance_with_buildreq(self, mock_buildreq_get):

        # This test checks that a new instance which is not yet peristed in
        # DB can be found by looking up the BuildRequest object so we can
        # update it.

        build_req_obj = fake_build_request.fake_req_obj(self.context)
        mock_buildreq_get.return_value = build_req_obj
        self.useFixture(nova_fixtures.AllServicesCurrent())

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

        self.useFixture(nova_fixtures.AllServicesCurrent())

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

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    def test_update_instance_not_in_cell_in_transition_state(self,
                                                             mock_buildreq_get,
                                                             mock_instmap_get):

        # This test is for covering the following case:
        #  - when we lookup the instance initially, that one is not yet mapped
        #    to a cell and consequently we retrieve it from the BuildRequest
        #  - when we update the instance, that one could have been mapped
        #    meanwhile and the BuildRequest was deleted
        #  - if the instance is not mapped, lookup the API DB to find whether
        #    the instance was deleted

        self.useFixture(nova_fixtures.AllServicesCurrent())

        instance = self._create_instance_obj()
        # Fake the fact that the instance is not yet persisted in DB
        del instance.id

        mock_buildreq_get.side_effect = exception.BuildRequestNotFound(
            uuid=instance.uuid)
        mock_instmap_get.side_effect = exception.InstanceMappingNotFound(
            uuid='fake')

        updates = {'display_name': 'foo_updated'}
        with mock.patch.object(instance, 'save') as mock_inst_save:
            self.assertRaises(exception.InstanceNotFound,
                              self.compute_api.update_instance,
                              self.context, instance, updates)

        mock_buildreq_get.assert_called_once_with(self.context, instance.uuid)
        mock_inst_save.assert_not_called()

    def test_populate_instance_for_create_neutron_secgroups(self):
        """Tests that a list of security groups passed in do not actually get
        stored on with the instance when using neutron.
        """
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

    def test_retrieve_trusted_certs_object(self):
        ids = ['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8',
               '674736e3-f25c-405c-8362-bbf991e0ce0a']

        retrieved_certs = self.compute_api._retrieve_trusted_certs_object(
            self.context, ids)
        self.assertEqual(ids, retrieved_certs.ids)

    def test_retrieve_trusted_certs_object_conf(self):
        ids = ['conf-trusted-cert-1', 'conf-trusted-cert-2']

        self.flags(verify_glance_signatures=True, group='glance')
        self.flags(enable_certificate_validation=True, group='glance')
        self.flags(default_trusted_certificate_ids='conf-trusted-cert-1, '
                                                   'conf-trusted-cert-2',
                   group='glance')
        retrieved_certs = self.compute_api._retrieve_trusted_certs_object(
            self.context, None)
        self.assertEqual(ids, retrieved_certs.ids)

    def test_retrieve_trusted_certs_object_none(self):
        self.flags(enable_certificate_validation=False, group='glance')
        self.assertIsNone(
            self.compute_api._retrieve_trusted_certs_object(self.context,
                None))

    def test_retrieve_trusted_certs_object_empty(self):
        self.flags(enable_certificate_validation=False, group='glance')
        self.assertIsNone(self.compute_api._retrieve_trusted_certs_object(
            self.context, []))

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_host(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm):
        host = 'fake-host'
        node = None

        self.compute_api._validate_host_or_node(self.context, host, node)
        mock_get_hm.assert_called_once_with(self.context, 'fake-host')
        mock_get_host_node.assert_not_called()
        mock_get_provider_by_name.assert_not_called()

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_invalid_host(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm):
        host = 'fake-host'
        node = None

        mock_get_hm.side_effect = exception.HostMappingNotFound(name=host)
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api._validate_host_or_node,
                          self.context, host, node)
        mock_get_hm.assert_called_once_with(self.context, 'fake-host')
        mock_get_host_node.assert_not_called()
        mock_get_provider_by_name.assert_not_called()

    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_host_and_node(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm,
            mock_target_cell):
        host = 'fake-host'
        node = 'fake-host'

        self.compute_api._validate_host_or_node(self.context, host, node)
        mock_get_host_node.assert_called_once_with(
            mock_target_cell.return_value.__enter__.return_value,
            'fake-host', 'fake-host')
        mock_get_hm.assert_called_once_with(self.context, 'fake-host')
        mock_get_provider_by_name.assert_not_called()

    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_invalid_host_and_node(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm,
            mock_target_cell):
        host = 'fake-host'
        node = 'fake-host'

        mock_get_host_node.side_effect = (
            exception.ComputeHostNotFound(host=host))
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api._validate_host_or_node,
                          self.context, host, node)
        mock_get_host_node.assert_called_once_with(
            mock_target_cell.return_value.__enter__.return_value,
            'fake-host', 'fake-host')
        mock_get_hm.assert_called_once_with(self.context, 'fake-host')
        mock_get_provider_by_name.assert_not_called()

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_node(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm):
        host = None
        node = 'fake-host'

        self.compute_api._validate_host_or_node(self.context, host, node)
        mock_get_provider_by_name.assert_called_once_with(
            self.context, 'fake-host')
        mock_get_host_node.assert_not_called()
        mock_get_hm.assert_not_called()

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_invalid_node(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm):
        host = None
        node = 'fake-host'

        mock_get_provider_by_name.side_effect = (
            exception.ResourceProviderNotFound(name_or_uuid=node))
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api._validate_host_or_node,
                          self.context, host, node)
        mock_get_provider_by_name.assert_called_once_with(
            self.context, 'fake-host')
        mock_get_host_node.assert_not_called()
        mock_get_hm.assert_not_called()

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test__validate_host_or_node_with_rp_500_exception(
            self, mock_get_provider_by_name, mock_get_host_node, mock_get_hm):
        host = None
        node = 'fake-host'

        mock_get_provider_by_name.side_effect = (
            exception.PlacementAPIConnectFailure())
        self.assertRaises(exception.PlacementAPIConnectFailure,
                          self.compute_api._validate_host_or_node,
                          self.context, host, node)
        mock_get_provider_by_name.assert_called_once_with(
            self.context, 'fake-host')
        mock_get_host_node.assert_not_called()
        mock_get_hm.assert_not_called()


# TODO(stephenfin): The separation of the mixin is a hangover from cells v1
# days and should be removed
class ComputeAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIUnitTestCase, self).setUp()
        self.compute_api = compute_api.API()

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

    def test__validate_numa_rebuild_non_numa(self):
        """Assert that a rebuild of an instance without a NUMA
        topology passes validation.
        """
        flavor = objects.Flavor(
            id=42, vcpus=1, memory_mb=512, root_gb=1, extra_specs={})
        instance = self._create_instance_obj(flavor=flavor)
        # we use a dict instead of image metadata object as
        # _validate_numa_rebuild constructs the object internally
        image = {
            'id': uuids.image_id, 'status': 'foo',
            'properties': {}}
        self.compute_api._validate_numa_rebuild(instance, image, flavor)

    def test__validate_numa_rebuild_no_conflict(self):
        """Assert that a rebuild of an instance without a change
        in NUMA topology passes validation.
        """
        flavor = objects.Flavor(
            id=42, vcpus=1, memory_mb=512, root_gb=1,
            extra_specs={"hw:numa_nodes": 1})
        instance = self._create_instance_obj(flavor=flavor)
        # we use a dict instead of image metadata object as
        # _validate_numa_rebuild constructs the object internally
        image = {
            'id': uuids.image_id, 'status': 'foo',
            'properties': {}}
        # The flavor creates a NUMA topology but the default image and the
        # rebuild image do not have any image properties so there will
        # be no conflict.
        self.compute_api._validate_numa_rebuild(instance, image, flavor)

    def test__validate_numa_rebuild_add_numa_toplogy(self):
        """Assert that a rebuild of an instance with a new image
        that requests a NUMA topology when the original instance did not
        have a NUMA topology is invalid.
        """

        flavor = objects.Flavor(
            id=42, vcpus=1, memory_mb=512, root_gb=1,
            extra_specs={})
        # _create_instance_obj results in the instance.image_meta being None.
        instance = self._create_instance_obj(flavor=flavor)
        # we use a dict instead of image metadata object as
        # _validate_numa_rebuild constructs the object internally
        image = {
            'id': uuids.image_id, 'status': 'foo',
            'properties': {"hw_numa_nodes": 1}}
        # The flavor and default image have no NUMA topology defined. The image
        # used to rebuild requests a NUMA topology which is not allowed as it
        # would alter the NUMA constrains.
        self.assertRaises(
            exception.ImageNUMATopologyRebuildConflict,
            self.compute_api._validate_numa_rebuild, instance, image, flavor)

    def test__validate_numa_rebuild_remove_numa_toplogy(self):
        """Assert that a rebuild of an instance with a new image
        that does not request a NUMA topology when the original image did
        is invalid if it would alter the instances topology as a result.
        """

        flavor = objects.Flavor(
            id=42, vcpus=1, memory_mb=512, root_gb=1,
            extra_specs={})
        # _create_instance_obj results in the instance.image_meta being None.
        instance = self._create_instance_obj(flavor=flavor)
        # we use a dict instead of image metadata object as
        # _validate_numa_rebuild constructs the object internally
        old_image = {
            'id': uuidutils.generate_uuid(), 'status': 'foo',
            'properties': {"hw_numa_nodes": 1}}
        old_image_meta = objects.ImageMeta.from_dict(old_image)
        image = {
            'id': uuidutils.generate_uuid(), 'status': 'foo',
            'properties': {}}
        with mock.patch(
                'nova.objects.instance.Instance.image_meta',
                new_callable=mock.PropertyMock(return_value=old_image_meta)):
            # The old image has a NUMA topology defined but the new image
            # used to rebuild does not. This would alter the NUMA constrains
            # and therefor should raise.
            self.assertRaises(
                exception.ImageNUMATopologyRebuildConflict,
                self.compute_api._validate_numa_rebuild, instance,
                image, flavor)

    def test__validate_numa_rebuild_alter_numa_toplogy(self):
        """Assert that a rebuild of an instance with a new image
        that requests a different NUMA topology than the original image
        is invalid.
        """

        # NOTE(sean-k-mooney): we need to use 2 vcpus here or we will fail
        # with a different exception ImageNUMATopologyAsymmetric when we
        # construct the NUMA constrains as the rebuild image would result
        # in an invalid topology.
        flavor = objects.Flavor(
            id=42, vcpus=2, memory_mb=512, root_gb=1,
            extra_specs={})
        # _create_instance_obj results in the instance.image_meta being None.
        instance = self._create_instance_obj(flavor=flavor)
        # we use a dict instead of image metadata object as
        # _validate_numa_rebuild constructs the object internally
        old_image = {
            'id': uuidutils.generate_uuid(), 'status': 'foo',
            'properties': {"hw_numa_nodes": 1}}
        old_image_meta = objects.ImageMeta.from_dict(old_image)
        image = {
            'id': uuidutils.generate_uuid(), 'status': 'foo',
            'properties': {"hw_numa_nodes": 2}}
        with mock.patch(
                'nova.objects.instance.Instance.image_meta',
                new_callable=mock.PropertyMock(return_value=old_image_meta)):
            # the original image requested 1 NUMA node and the image used
            # for rebuild requests 2 so assert an error is raised.
            self.assertRaises(
                exception.ImageNUMATopologyRebuildConflict,
                self.compute_api._validate_numa_rebuild, instance,
                image, flavor)

    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    def test_pmu_image_and_flavor_conflict(self, mock_request):
        """Tests that calling _validate_flavor_image_nostatus()
        with an image that conflicts with the flavor raises but no
        exception is raised if there is no conflict.
        """
        image = {'id': uuids.image_id, 'status': 'foo',
                 'properties': {'hw_pmu': False}}
        flavor = objects.Flavor(
            vcpus=1, memory_mb=512, root_gb=1, extra_specs={'hw:pmu': "true"})
        self.assertRaises(
            exception.ImagePMUConflict,
            self.compute_api._validate_flavor_image_nostatus,
            self.context, image, flavor, None)

    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    def test_pmu_image_and_flavor_same_value(self, mock_request):
        # assert that if both the image and flavor are set to the same value
        # no exception is raised and the function returns nothing.
        flavor = objects.Flavor(
            vcpus=1, memory_mb=512, root_gb=1, extra_specs={'hw:pmu': "true"})

        image = {'id': uuids.image_id, 'status': 'foo',
                 'properties': {'hw_pmu': True}}
        self.assertIsNone(self.compute_api._validate_flavor_image_nostatus(
            self.context, image, flavor, None))

    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    def test_pmu_image_only(self, mock_request):
        # assert that if only the image metadata is set then it is valid
        flavor = objects.Flavor(
            vcpus=1, memory_mb=512, root_gb=1, extra_specs={})

        # ensure string to bool conversion works for image metadata
        # property by using "yes".
        image = {'id': uuids.image_id, 'status': 'foo',
                 'properties': {'hw_pmu': "yes"}}
        self.assertIsNone(self.compute_api._validate_flavor_image_nostatus(
            self.context, image, flavor, None))

    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    def test_pmu_flavor_only(self, mock_request):
        # assert that if only the flavor extra_spec is set then it is valid
        # and test the string to bool conversion of "on" works.
        flavor = objects.Flavor(
            vcpus=1, memory_mb=512, root_gb=1, extra_specs={'hw:pmu': "on"})

        image = {'id': uuids.image_id, 'status': 'foo', 'properties': {}}
        self.assertIsNone(self.compute_api._validate_flavor_image_nostatus(
            self.context, image, flavor, None))

    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    def test_pci_validated(self, mock_request):
        """Tests that calling _validate_flavor_image_nostatus() with
        validate_pci=True results in get_pci_requests_from_flavor() being
        called.
        """
        image = {'id': uuids.image_id, 'status': 'foo'}
        flavor = self._create_flavor()
        self.compute_api._validate_flavor_image_nostatus(
            self.context, image, flavor, root_bdm=None, validate_pci=True)
        mock_request.assert_called_once_with(flavor)

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
        # will be translated to a UUID for Neutron.
        requested_secgroups = ['default', 'fake-security-group']
        # This will short-circuit _check_requested_networks
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='none')])
        max_count = 1
        supports_port_resource_request = False
        with mock.patch(
                'nova.network.security_group_api.validate_name',
                return_value=uuids.secgroup_uuid) as scget:
            base_options, max_network_count, key_pair, security_groups, \
                    network_metadata = (
                self.compute_api._validate_and_build_base_options(
                    self.context, instance_type, boot_meta, uuids.image_href,
                    mock.sentinel.image_id, kernel_id, ramdisk_id,
                    'fake-display-name', 'fake-description', key_name,
                    key_data, requested_secgroups, 'fake-az', user_data,
                    metadata, access_ip_v4, access_ip_v6, requested_networks,
                    config_drive, auto_disk_config, reservation_id, max_count,
                    supports_port_resource_request
                )
            )
        # Assert the neutron security group API get method was called once
        # and only for the non-default security group name.
        scget.assert_called_once_with(self.context, 'fake-security-group')
        # Assert we translated the non-default secgroup name to uuid.
        self.assertCountEqual(['default', uuids.secgroup_uuid],
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
    def test_attach_interface_qos_aware_port(self, mock_record):
        instance = self._create_instance_obj()
        with mock.patch.object(
                self.compute_api.network_api, 'show_port',
                return_value={'port': {
                    constants.RESOURCE_REQUEST: {
                        'resources': {'CUSTOM_RESOURCE_CLASS': 42}
                }}}) as mock_show_port:
            self.assertRaises(
                exception.AttachInterfaceWithQoSPolicyNotSupported,
                self.compute_api.attach_interface,
                self.context, instance,
                'foo_net_id', 'foo_port_id', None
            )
        mock_show_port.assert_called_once_with(self.context, 'foo_port_id')

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

    @mock.patch('nova.volume.cinder.API.get',
                return_value={'id': uuids.volumeid, 'multiattach': True})
    def test_attach_volume_shelved_offloaded_fails(
            self, volume_get):
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

    def test_validate_bdm_check_volume_type_raise_not_found(self):
        """Tests that _validate_bdm will fail if the requested volume type
        name or id does not match the volume types in Cinder.
        """
        volume_types = [{'id': 'fake_volume_type_id_1', 'name': 'fake_lvm_1'},
                        {'id': 'fake_volume_type_id_2', 'name': 'fake_lvm_2'}]
        bdm = objects.BlockDeviceMapping(
            **fake_block_device.FakeDbBlockDeviceDict(
                {
                    'uuid': uuids.image_id,
                    'source_type': 'image',
                    'destination_type': 'volume',
                    'device_name': 'vda',
                    'boot_index': 0,
                    'volume_size': 3,
                    'volume_type': 'lvm-1'}))
        self.assertRaises(exception.VolumeTypeNotFound,
                          self.compute_api._check_requested_volume_type,
                          bdm, 'lvm-1', volume_types)

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters',
                       new_callable=mock.NonCallableMock)
    def test_get_all_ip_filter(self, mock_buildreq_get, mock_list_port,
                               mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances), list()

            self.compute_api.get_all(
                self.context, search_opts={'ip': 'fake'},
                limit=None, marker=None, sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_called_once_with(
                self.context, fixed_ips='ip_address_substr=fake',
                fields=['device_id'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip': 'fake', 'uuid': ['fake_device_id']},
                None, None, fields, ['baz'], ['desc'], cell_down_support=False)

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters',
                       new_callable=mock.NonCallableMock)
    def test_get_all_ip6_filter(self, mock_buildreq_get, mock_list_port,
                                mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances), list()

            self.compute_api.get_all(
                self.context, search_opts={'ip6': 'fake'},
                limit=None, marker=None, sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_called_once_with(
                self.context, fixed_ips='ip_address_substr=fake',
                fields=['device_id'])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip6': 'fake', 'uuid': ['fake_device_id']},
                None, None, fields, ['baz'], ['desc'], cell_down_support=False)

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    @mock.patch.object(objects.BuildRequestList, 'get_by_filters',
                       new_callable=mock.NonCallableMock)
    def test_get_all_ip_and_ip6_filter(self, mock_buildreq_get, mock_list_port,
                                       mock_check_ext):
        mock_check_ext.return_value = True
        cell_instances = self._list_of_instances(2)
        mock_list_port.return_value = {
            'ports': [{'device_id': 'fake_device_id'}]}
        with mock.patch('nova.compute.instance_list.'
                        'get_instance_objects_sorted') as mock_inst_get:
            mock_inst_get.return_value = objects.InstanceList(
                self.context, objects=cell_instances), list()

            self.compute_api.get_all(
                self.context, search_opts={'ip': 'fake1', 'ip6': 'fake2'},
                limit=None, marker=None, sort_keys=['baz'],
                sort_dirs=['desc'])

            mock_list_port.assert_has_calls([
                mock.call(
                    self.context, fixed_ips='ip_address_substr=fake1',
                    fields=['device_id']),
                mock.call(
                    self.context, fixed_ips='ip_address_substr=fake2',
                    fields=['device_id'])
            ])
            fields = ['metadata', 'info_cache', 'security_groups']
            mock_inst_get.assert_called_once_with(
                self.context, {'ip': 'fake1', 'ip6': 'fake2',
                               'uuid': ['fake_device_id', 'fake_device_id']},
                None, None, fields, ['baz'], ['desc'], cell_down_support=False)

    @mock.patch.object(neutron_api.API, 'has_substr_port_filtering_extension')
    @mock.patch.object(neutron_api.API, 'list_ports')
    def test_get_all_ip6_filter_exc(self, mock_list_port, mock_check_ext):
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

    @mock.patch.object(compute_utils, 'notify_about_instance_action')
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
            bdm_get_by_instance_uuid, mock_lookup, _mock_del_booting,
            notify_about_instance_action):
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

    def test_compute_api_host(self):
        self.assertTrue(hasattr(self.compute_api, 'host'))
        self.assertEqual(CONF.host, self.compute_api.host)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    def test_placement_client_init(self, mock_report_client):
        """Tests to make sure that the construction of the placement client
        only happens once per API class instance.
        """
        self.assertIsNone(self.compute_api._placementclient)
        # Access the property twice to make sure SchedulerReportClient is
        # only loaded once.
        for x in range(2):
            self.compute_api.placementclient
        mock_report_client.assert_called_once_with()

    def test_validate_host_for_cold_migrate_same_host_fails(self):
        """Asserts CannotMigrateToSameHost is raised when trying to cold
        migrate to the same host.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.CannotMigrateToSameHost,
                          self.compute_api._validate_host_for_cold_migrate,
                          self.context, instance, instance.host,
                          allow_cross_cell_resize=False)

    @mock.patch('nova.objects.ComputeNode.'
                'get_first_node_by_host_for_old_compat')
    def test_validate_host_for_cold_migrate_diff_host_no_cross_cell(
            self, mock_cn_get):
        """Tests the scenario where allow_cross_cell_resize=False and the
        host is found in the same cell as the instance.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        node = self.compute_api._validate_host_for_cold_migrate(
            self.context, instance, uuids.host, allow_cross_cell_resize=False)
        self.assertIs(node, mock_cn_get.return_value)
        mock_cn_get.assert_called_once_with(
            self.context, uuids.host, use_slave=True)

    @mock.patch('nova.objects.HostMapping.get_by_host',
                side_effect=exception.HostMappingNotFound(name=uuids.host))
    def test_validate_host_for_cold_migrate_cross_cell_host_mapping_not_found(
            self, mock_hm_get):
        """Tests the scenario where allow_cross_cell_resize=True but the
        HostMapping for the given host could not be found.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.ComputeHostNotFound,
                          self.compute_api._validate_host_for_cold_migrate,
                          self.context, instance, uuids.host,
                          allow_cross_cell_resize=True)
        mock_hm_get.assert_called_once_with(self.context, uuids.host)

    @mock.patch('nova.objects.HostMapping.get_by_host',
                return_value=objects.HostMapping(
                    cell_mapping=objects.CellMapping(uuid=uuids.cell2)))
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.ComputeNode.'
                'get_first_node_by_host_for_old_compat')
    def test_validate_host_for_cold_migrate_cross_cell(
            self, mock_cn_get, mock_target_cell, mock_hm_get):
        """Tests the scenario where allow_cross_cell_resize=True and the
        ComputeNode is pulled from the target cell defined by the HostMapping.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        node = self.compute_api._validate_host_for_cold_migrate(
            self.context, instance, uuids.host,
            allow_cross_cell_resize=True)
        self.assertIs(node, mock_cn_get.return_value)
        mock_hm_get.assert_called_once_with(self.context, uuids.host)
        # get_first_node_by_host_for_old_compat is called with a temporarily
        # cell-targeted context
        mock_cn_get.assert_called_once_with(
            mock_target_cell.return_value.__enter__.return_value,
            uuids.host, use_slave=True)

    def _test_get_migrations_sorted_filter_duplicates(self, migrations,
                                                      expected):
        """Tests the cross-cell scenario where there are multiple migrations
        with the same UUID from different cells and only one should be
        returned.
        """
        sort_keys = ['created_at', 'id']
        sort_dirs = ['desc', 'desc']
        filters = {'migration_type': 'resize'}
        limit = 1000
        marker = None
        with mock.patch(
                'nova.compute.migration_list.get_migration_objects_sorted',
                return_value=objects.MigrationList(
                    objects=migrations)) as getter:
            sorted_migrations = self.compute_api.get_migrations_sorted(
                self.context, filters, sort_dirs=sort_dirs,
                sort_keys=sort_keys, limit=limit, marker=marker)
        self.assertEqual(1, len(sorted_migrations))
        getter.assert_called_once_with(
            self.context, filters, limit, marker, sort_keys, sort_dirs)
        self.assertIs(expected, sorted_migrations[0])

    def test_get_migrations_sorted_filter_duplicates(self):
        """Tests filtering duplicated Migration records where both have
        created_at and updated_at set.
        """
        t1 = timeutils.utcnow()
        source_cell_migration = objects.Migration(
            uuid=uuids.migration, created_at=t1, updated_at=t1)
        t2 = t1 + datetime.timedelta(seconds=1)
        target_cell_migration = objects.Migration(
            uuid=uuids.migration, created_at=t2, updated_at=t2)
        self._test_get_migrations_sorted_filter_duplicates(
            [source_cell_migration, target_cell_migration],
            target_cell_migration)
        # Run it again in reverse.
        self._test_get_migrations_sorted_filter_duplicates(
            [target_cell_migration, source_cell_migration],
            target_cell_migration)

    def test_get_migrations_sorted_filter_duplicates_using_created_at(self):
        """Tests the cross-cell scenario where there are multiple migrations
        with the same UUID from different cells and only one should be
        returned. In this test the first Migration object to be processed has
        not been updated yet but is created after the second record to process.
        """
        t1 = timeutils.utcnow()
        older = objects.Migration(
            uuid=uuids.migration, created_at=t1, updated_at=t1)
        t2 = t1 + datetime.timedelta(seconds=1)
        newer = objects.Migration(
            uuid=uuids.migration, created_at=t2, updated_at=None)
        self._test_get_migrations_sorted_filter_duplicates(
            [newer, older], newer)
        # Test with just created_at.
        older.updated_at = None
        self._test_get_migrations_sorted_filter_duplicates(
            [newer, older], newer)
        # Run it again in reverse.
        self._test_get_migrations_sorted_filter_duplicates(
            [older, newer], newer)

    @mock.patch('nova.servicegroup.api.API.service_is_up', return_value=True)
    @mock.patch('nova.objects.Migration.get_by_instance_and_status')
    def test_confirm_resize_cross_cell_move_true(self, mock_migration_get,
                                                 mock_service_is_up):
        """Tests confirm_resize where Migration.cross_cell_move is True"""
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.RESIZED, task_state=None,
            launched_at=timeutils.utcnow())
        migration = objects.Migration(cross_cell_move=True)
        mock_migration_get.return_value = migration
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(migration, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_task_api,
                              'confirm_snapshot_based_resize'),
            mock.patch.object(self.compute_api, '_get_source_compute_service'),
        ) as (
            mock_elevated, mock_migration_save, mock_record_action,
            mock_conductor_confirm, mock_get_service
        ):
            self.compute_api.confirm_resize(self.context, instance)
        mock_elevated.assert_called_once_with()
        mock_service_is_up.assert_called_once_with(
            mock_get_service.return_value)
        mock_migration_save.assert_called_once_with()
        self.assertEqual('confirming', migration.status)
        mock_record_action.assert_called_once_with(
            self.context, instance, instance_actions.CONFIRM_RESIZE)
        mock_conductor_confirm.assert_called_once_with(
            self.context, instance, migration)

    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_allow_cross_cell_resize_default_false(self, mock_get_min_ver):
        """Based on the default policy this asserts nobody is allowed to
        perform cross-cell resize.
        """
        instance = objects.Instance(
            project_id='fake-project', user_id='fake-user')
        self.assertFalse(self.compute_api._allow_cross_cell_resize(
            self.context, instance))
        # We did not need to check the minimum nova-compute version since the
        # policy check failed.
        mock_get_min_ver.assert_not_called()

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=compute_api.MIN_COMPUTE_CROSS_CELL_RESIZE - 1)
    def test_allow_cross_cell_resize_false_old_version(self, mock_get_min_ver):
        """Policy allows cross-cell resize but minimum nova-compute service
        version is not new enough.
        """
        instance = objects.Instance(
            project_id='fake-project', user_id='fake-user',
            uuid=uuids.instance)
        with mock.patch.object(self.context, 'can', return_value=True) as can:
            self.assertFalse(self.compute_api._allow_cross_cell_resize(
                self.context, instance))
        can.assert_called_once()
        mock_get_min_ver.assert_called_once_with(
            self.context, ['nova-compute'])

    @mock.patch('nova.network.neutron.API.get_requested_resource_for_instance',
                return_value=[objects.RequestGroup()])
    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=compute_api.MIN_COMPUTE_CROSS_CELL_RESIZE)
    def test_allow_cross_cell_resize_false_port_with_resource_req(
            self, mock_get_min_ver, mock_get_res_req):
        """Policy allows cross-cell resize but minimum nova-compute service
        version is not new enough.
        """
        instance = objects.Instance(
            project_id='fake-project', user_id='fake-user',
            uuid=uuids.instance)
        with mock.patch.object(self.context, 'can', return_value=True) as can:
            self.assertFalse(self.compute_api._allow_cross_cell_resize(
                self.context, instance))
        can.assert_called_once()
        mock_get_min_ver.assert_called_once_with(
            self.context, ['nova-compute'])
        mock_get_res_req.assert_called_once_with(self.context, uuids.instance)

    @mock.patch('nova.network.neutron.API.get_requested_resource_for_instance',
                return_value=[])
    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=compute_api.MIN_COMPUTE_CROSS_CELL_RESIZE)
    def test_allow_cross_cell_resize_true(
            self, mock_get_min_ver, mock_get_res_req):
        """Policy allows cross-cell resize and minimum nova-compute service
        version is new enough.
        """
        instance = objects.Instance(
            project_id='fake-project', user_id='fake-user',
            uuid=uuids.instance)
        with mock.patch.object(self.context, 'can', return_value=True) as can:
            self.assertTrue(self.compute_api._allow_cross_cell_resize(
                self.context, instance))
        can.assert_called_once()
        mock_get_min_ver.assert_called_once_with(
            self.context, ['nova-compute'])
        mock_get_res_req.assert_called_once_with(self.context, uuids.instance)

    def _test_block_accelerators(self, instance, args_info,
                                 until_service=None):
        @compute_api.block_accelerators(until_service=until_service)
        def myfunc(self, context, instance, *args, **kwargs):
            args_info['args'] = (context, instance, *args)
            args_info['kwargs'] = dict(**kwargs)

        args = ('arg1', 'arg2')
        kwargs = {'arg3': 'dummy3', 'arg4': 'dummy4'}

        myfunc(mock.ANY, self.context, instance, *args, **kwargs)

        expected_args = (self.context, instance, *args)
        return expected_args, kwargs

    def test_block_accelerators_no_device_profile(self):
        instance = self._create_instance_obj()
        args_info = {}

        expected_args, kwargs = self._test_block_accelerators(
                                    instance, args_info)
        self.assertEqual(expected_args, args_info['args'])
        self.assertEqual(kwargs, args_info['kwargs'])

    def test_block_accelerators_with_device_profile(self):
        extra_specs = {'accel:device_profile': 'mydp'}
        flavor = self._create_flavor(extra_specs=extra_specs)
        instance = self._create_instance_obj(flavor=flavor)
        args_info = {}

        self.assertRaisesRegex(exception.ForbiddenWithAccelerators,
            'Forbidden with instances that have accelerators.',
            self._test_block_accelerators, instance, args_info)
        # myfunc was not called
        self.assertEqual({}, args_info)

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=54)
    def test_block_accelerators_until_service(self, mock_get_min):
        """Support operating server with acclerators until compute service
        more than the version of 53.
        """
        extra_specs = {'accel:device_profile': 'mydp'}
        flavor = self._create_flavor(extra_specs=extra_specs)
        instance = self._create_instance_obj(flavor=flavor)
        args_info = {}
        expected_args, kwargs = self._test_block_accelerators(
                                    instance, args_info, until_service=53)
        self.assertEqual(expected_args, args_info['args'])
        self.assertEqual(kwargs, args_info['kwargs'])

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=52)
    def test_block_accelerators_until_service_forbidden(self, mock_get_min):
        """Ensure a 'ForbiddenWithAccelerators' exception raises if any
        compute service less than the version of 53.
        """
        extra_specs = {'accel:device_profile': 'mydp'}
        flavor = self._create_flavor(extra_specs=extra_specs)
        instance = self._create_instance_obj(flavor=flavor)
        args_info = {}
        self.assertRaisesRegex(exception.ForbiddenWithAccelerators,
            'Forbidden with instances that have accelerators.',
            self._test_block_accelerators, instance, args_info, 53)
        # myfunc was not called
        self.assertEqual({}, args_info)

    # TODO(huaqiang): Remove in Wallaby
    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test__check_compute_service_for_mixed_instance(self, mock_ver):
        """Ensure a 'MixedInstanceNotSupportByComputeService' exception raises
        if any compute node has not been upgraded to Victoria or later.
        """
        mock_ver.side_effect = [52, 51]
        fake_numa_topo = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=0, cpuset=set([0]), pcpuset=set([1]), memory=512,
                cpu_policy='mixed')
        ])

        self.compute_api._check_compute_service_for_mixed_instance(
            fake_numa_topo)
        # 'get_minimum_version_all_cells' has been called
        mock_ver.assert_called()

        self.assertRaises(
            exception.MixedInstanceNotSupportByComputeService,
            self.compute_api._check_compute_service_for_mixed_instance,
            fake_numa_topo)


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
