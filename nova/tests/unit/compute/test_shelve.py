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

import mock
from oslo_utils import fixture as utils_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.compute import api as compute_api
from nova.compute import claims
from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova.db import api as db
from nova import exception
from nova.network import neutron as neutron_api
from nova import objects
from nova import test
from nova.tests import fixtures
from nova.tests.unit.compute import test_compute


CONF = nova.conf.CONF


def _fake_resources():
    resources = {
        'memory_mb': 2048,
        'memory_mb_used': 0,
        'free_ram_mb': 2048,
        'local_gb': 20,
        'local_gb_used': 0,
        'free_disk_gb': 20,
        'vcpus': 2,
        'vcpus_used': 0
    }
    return objects.ComputeNode(**resources)


class ShelveComputeManagerTestCase(test_compute.BaseTestCase):
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_terminate_volume_connections')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'power_off')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'snapshot')
    @mock.patch.object(nova.compute.manager.ComputeManager, '_get_power_state')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def _shelve_instance(self, shelved_offload_time, mock_notify,
                         mock_notify_instance_usage, mock_get_power_state,
                         mock_snapshot, mock_power_off, mock_terminate,
                         mock_get_bdms, clean_shutdown=True,
                         guest_power_state=power_state.RUNNING):
        mock_get_power_state.return_value = 123

        CONF.set_override('shelved_offload_time', shelved_offload_time)
        host = 'fake-mini'
        instance = self._create_fake_instance_obj(
            params={'host': host, 'power_state': guest_power_state})
        image_id = 'fake_image_id'
        host = 'fake-mini'
        self.useFixture(utils_fixture.TimeFixture())
        instance.task_state = task_states.SHELVING
        instance.save()

        fake_bdms = None
        if shelved_offload_time == 0:
            fake_bdms = objects.BlockDeviceMappingList()
            mock_get_bdms.return_value = fake_bdms

        tracking = {'last_state': instance.vm_state}

        def check_save(expected_task_state=None):
            self.assertEqual(123, instance.power_state)
            if tracking['last_state'] == vm_states.ACTIVE:
                if CONF.shelved_offload_time == 0:
                    self.assertEqual(task_states.SHELVING_OFFLOADING,
                                     instance.task_state)
                else:
                    self.assertIsNone(instance.task_state)
                self.assertEqual(vm_states.SHELVED, instance.vm_state)
                self.assertEqual([task_states.SHELVING,
                                  task_states.SHELVING_IMAGE_UPLOADING],
                                 expected_task_state)
                self.assertIn('shelved_at', instance.system_metadata)
                self.assertEqual(image_id,
                                 instance.system_metadata['shelved_image_id'])
                self.assertEqual(host,
                                 instance.system_metadata['shelved_host'])
                tracking['last_state'] = instance.vm_state
            elif (tracking['last_state'] == vm_states.SHELVED and
                  CONF.shelved_offload_time == 0):
                self.assertIsNone(instance.task_state)
                self.assertEqual(vm_states.SHELVED_OFFLOADED,
                                 instance.vm_state)
                self.assertEqual([task_states.SHELVING,
                                  task_states.SHELVING_OFFLOADING],
                                 expected_task_state)
                tracking['last_state'] = instance.vm_state
            elif (tracking['last_state'] == vm_states.SHELVED_OFFLOADED and
                  CONF.shelved_offload_time == 0):
                self.assertIsNone(instance.host)
                self.assertIsNone(instance.node)
                self.assertIsNone(expected_task_state)
            else:
                self.fail('Unexpected save!')

        with test.nested(
                mock.patch.object(instance, 'save'),
                mock.patch.object(self.compute.network_api,
                                  'cleanup_instance_network_on_host')) as (
            mock_save, mock_cleanup
        ):
            mock_save.side_effect = check_save
            self.compute.shelve_instance(self.context, instance,
                                         image_id=image_id,
                                         clean_shutdown=clean_shutdown)
            mock_notify.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                          action='shelve', phase='start', bdms=fake_bdms),
                mock.call(self.context, instance, 'fake-mini',
                          action='shelve', phase='end', bdms=fake_bdms)])

        # prepare expect call lists
        mock_notify_instance_usage_call_list = [
            mock.call(self.context, instance, 'shelve.start'),
            mock.call(self.context, instance, 'shelve.end')]
        mock_power_off_call_list = []
        mock_get_power_state_call_list = [mock.call(instance)]

        if clean_shutdown:
            if guest_power_state == power_state.PAUSED:
                mock_power_off_call_list.append(mock.call(instance, 0, 0))
            else:
                mock_power_off_call_list.append(
                    mock.call(instance, CONF.shutdown_timeout,
                              CONF.compute.shutdown_retry_interval))
        else:
            mock_power_off_call_list.append(mock.call(instance, 0, 0))

        if CONF.shelved_offload_time == 0:
            mock_notify_instance_usage_call_list.extend([
                mock.call(self.context, instance, 'shelve_offload.start'),
                mock.call(self.context, instance, 'shelve_offload.end')])
            mock_power_off_call_list.append(mock.call(instance, 0, 0))
            mock_get_power_state_call_list.append(mock.call(instance))

        mock_notify_instance_usage.assert_has_calls(
            mock_notify_instance_usage_call_list)
        mock_power_off.assert_has_calls(mock_power_off_call_list)
        mock_cleanup.assert_not_called()
        mock_snapshot.assert_called_once_with(self.context, instance,
                                              'fake_image_id', mock.ANY)
        mock_get_power_state.assert_has_calls(mock_get_power_state_call_list)

        if CONF.shelved_offload_time == 0:
            self.assertTrue(mock_terminate.called)

    def test_shelve(self):
        self._shelve_instance(-1)

    def test_shelve_forced_shutdown(self):
        self._shelve_instance(-1, clean_shutdown=False)

    def test_shelve_and_offload(self):
        self._shelve_instance(0)

    def test_shelve_paused_instance(self):
        self._shelve_instance(-1, guest_power_state=power_state.PAUSED)

    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'power_off')
    def test_shelve_offload(self, mock_power_off):
        instance = self._shelve_offload()
        mock_power_off.assert_called_once_with(instance,
            CONF.shutdown_timeout, CONF.compute.shutdown_retry_interval)

    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'power_off')
    def test_shelve_offload_forced_shutdown(self, mock_power_off):
        instance = self._shelve_offload(clean_shutdown=False)
        mock_power_off.assert_called_once_with(instance, 0, 0)

    @mock.patch.object(compute_utils, 'EventReporter')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_terminate_volume_connections')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                'delete_allocation_for_shelve_offloaded_instance')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_update_resource_tracker')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_get_power_state', return_value=123)
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def _shelve_offload(self, mock_notify, mock_notify_instance_usage,
                        mock_get_power_state, mock_update_resource_tracker,
                        mock_delete_alloc, mock_terminate, mock_get_bdms,
                        mock_event, clean_shutdown=True):
        host = 'fake-mini'
        instance = self._create_fake_instance_obj(params={'host': host})
        instance.task_state = task_states.SHELVING
        instance.save()
        self.useFixture(utils_fixture.TimeFixture())
        fake_bdms = objects.BlockDeviceMappingList()
        mock_get_bdms.return_value = fake_bdms

        def stub_instance_save(inst, *args, **kwargs):
            # If the vm_state is changed to SHELVED_OFFLOADED make sure we
            # have already freed up allocations in placement.
            if inst.vm_state == vm_states.SHELVED_OFFLOADED:
                self.assertTrue(mock_delete_alloc.called,
                                'Allocations must be deleted before the '
                                'vm_status can change to shelved_offloaded.')

        self.stub_out('nova.objects.Instance.save', stub_instance_save)
        self.compute.shelve_offload_instance(self.context, instance,
                                             clean_shutdown=clean_shutdown)
        mock_notify.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='shelve_offload', phase='start',
                      bdms=fake_bdms),
            mock.call(self.context, instance, 'fake-mini',
                      action='shelve_offload', phase='end',
                      bdms=fake_bdms)])

        self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)
        self.assertIsNone(instance.task_state)
        self.assertTrue(mock_terminate.called)

        # prepare expect call lists
        mock_notify_instance_usage_call_list = [
            mock.call(self.context, instance, 'shelve_offload.start'),
            mock.call(self.context, instance, 'shelve_offload.end')]

        mock_notify_instance_usage.assert_has_calls(
            mock_notify_instance_usage_call_list)
        # instance.host is replaced with host because
        # original instance.host is clear after
        # ComputeManager.shelve_offload_instance execute
        mock_get_power_state.assert_called_once_with(instance)
        mock_update_resource_tracker.assert_called_once_with(self.context,
                                                             instance)
        mock_delete_alloc.assert_called_once_with(self.context, instance)
        mock_event.assert_called_once_with(self.context,
                                           'compute_shelve_offload_instance',
                                           CONF.host,
                                           instance.uuid,
                                           graceful_exit=False)

        return instance

    @mock.patch('nova.compute.utils.'
                'update_pci_request_spec_with_allocated_interface_name',
                new=mock.NonCallableMock())
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_prep_block_device', return_value='fake_bdm')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'spawn')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_get_power_state', return_value=123)
    @mock.patch.object(neutron_api.API, 'setup_instance_network_on_host')
    def test_unshelve(self, mock_setup_network,
                      mock_get_power_state, mock_spawn,
                      mock_prep_block_device, mock_notify_instance_usage,
                      mock_notify_instance_action,
                      mock_get_bdms):
        mock_bdms = mock.Mock()
        mock_get_bdms.return_value = mock_bdms
        instance = self._create_fake_instance_obj()
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image = {'id': uuids.image_id}
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        host = 'fake-mini'
        cur_time = timeutils.utcnow()
        # Adding shelved_* keys in system metadata to verify
        # whether those are deleted after unshelve call.
        sys_meta = dict(instance.system_metadata)
        sys_meta['shelved_at'] = cur_time.isoformat()
        sys_meta['shelved_image_id'] = image['id']
        sys_meta['shelved_host'] = host
        instance.system_metadata = sys_meta

        self.deleted_image_id = None

        def fake_delete(self2, ctxt, image_id):
            self.deleted_image_id = image_id

        def fake_claim(context, instance, node, allocations, limits):
            instance.host = self.compute.host
            requests = objects.InstancePCIRequests(requests=[])
            return claims.Claim(context, instance, test_compute.NODENAME,
                                self.rt, _fake_resources(),
                                requests)

        tracking = {
            'last_state': instance.task_state,
            'spawned': False,
        }

        def check_save(expected_task_state=None):
            if tracking['last_state'] == task_states.UNSHELVING:
                if tracking['spawned']:
                    self.assertIsNone(instance.task_state)
                else:
                    self.assertEqual(task_states.SPAWNING, instance.task_state)
                    tracking['spawned'] = True
                tracking['last_state'] == instance.task_state
            elif tracking['last_state'] == task_states.SPAWNING:
                self.assertEqual(vm_states.ACTIVE, instance.vm_state)
                tracking['last_state'] == instance.task_state
            else:
                self.fail('Unexpected save!')

        self.useFixture(fixtures.GlanceFixture(self))
        self.stub_out('nova.tests.fixtures.GlanceFixture.delete', fake_delete)

        with mock.patch.object(self.rt, 'instance_claim',
                               side_effect=fake_claim), \
                 mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.unshelve_instance(
                self.context, instance, image=image,
                filter_properties=filter_properties,
                node=node, request_spec=objects.RequestSpec())

        mock_notify_instance_action.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='unshelve', phase='start', bdms=mock_bdms),
            mock.call(self.context, instance, 'fake-mini',
                      action='unshelve', phase='end', bdms=mock_bdms)])

        # prepare expect call lists
        mock_notify_instance_usage_call_list = [
            mock.call(self.context, instance, 'unshelve.start'),
            mock.call(self.context, instance, 'unshelve.end')]

        mock_notify_instance_usage.assert_has_calls(
            mock_notify_instance_usage_call_list)
        mock_prep_block_device.assert_called_once_with(self.context,
            instance, mock.ANY)
        mock_setup_network.assert_called_once_with(
            self.context, instance, self.compute.host, provider_mappings=None)
        mock_spawn.assert_called_once_with(self.context, instance,
                test.MatchType(objects.ImageMeta), injected_files=[],
                admin_password=None, allocations={}, network_info=[],
                block_device_info='fake_bdm')
        self.mock_get_allocations.assert_called_once_with(self.context,
                                                          instance.uuid)
        mock_get_power_state.assert_called_once_with(instance)

        self.assertNotIn('shelved_at', instance.system_metadata)
        self.assertNotIn('shelved_image_id', instance.system_metadata)
        self.assertNotIn('shelved_host', instance.system_metadata)
        self.assertEqual(image['id'], self.deleted_image_id)
        self.assertEqual(instance.host, self.compute.host)

        self.assertEqual(123, instance.power_state)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertIsNone(instance.task_state)
        self.assertIsNone(instance.key_data)
        self.assertEqual(self.compute.host, instance.host)
        self.assertFalse(instance.auto_disk_config)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch.object(nova.compute.resource_tracker.ResourceTracker,
                       'instance_claim')
    @mock.patch.object(neutron_api.API, 'setup_instance_network_on_host')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_get_power_state', return_value=123)
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'spawn')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_prep_block_device', return_value='fake_bdm')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch('nova.utils.get_image_from_system_metadata')
    def test_unshelve_volume_backed(self, mock_image_meta,
                                    mock_notify_instance_usage,
                                    mock_prep_block_device, mock_spawn,
                                    mock_get_power_state,
                                    mock_setup_network, mock_instance_claim,
                                    mock_notify_instance_action,
                                    mock_get_bdms):
        mock_bdms = mock.Mock()
        mock_get_bdms.return_value = mock_bdms
        instance = self._create_fake_instance_obj()
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image_meta = {'properties': {'base_image_ref': uuids.image_id}}
        mock_image_meta.return_value = image_meta

        tracking = {'last_state': instance.task_state}

        def fake_claim(context, instance, node, allocations, limits):
            instance.host = self.compute.host
            requests = objects.InstancePCIRequests(requests=[])
            return claims.Claim(context, instance, test_compute.NODENAME,
                                self.rt, _fake_resources(),
                                requests)
        mock_instance_claim.side_effect = fake_claim

        def check_save(expected_task_state=None):
            if tracking['last_state'] == task_states.UNSHELVING:
                self.assertEqual(task_states.SPAWNING, instance.task_state)
                tracking['last_state'] = instance.task_state
            elif tracking['last_state'] == task_states.SPAWNING:
                self.assertEqual(123, instance.power_state)
                self.assertEqual(vm_states.ACTIVE, instance.vm_state)
                self.assertIsNone(instance.task_state)
                self.assertIsNone(instance.key_data)
                self.assertFalse(instance.auto_disk_config)
                self.assertIsNone(instance.task_state)
                tracking['last_state'] = instance.task_state
            else:
                self.fail('Unexpected save!')

        with mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.unshelve_instance(self.context, instance, image=None,
                    filter_properties=filter_properties, node=node,
                    request_spec=objects.RequestSpec())

        mock_notify_instance_action.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='unshelve', phase='start', bdms=mock_bdms),
            mock.call(self.context, instance, 'fake-mini',
                      action='unshelve', phase='end', bdms=mock_bdms)])

        # prepare expect call lists
        mock_notify_instance_usage_call_list = [
            mock.call(self.context, instance, 'unshelve.start'),
            mock.call(self.context, instance, 'unshelve.end')]

        mock_notify_instance_usage.assert_has_calls(
            mock_notify_instance_usage_call_list)
        mock_prep_block_device.assert_called_once_with(self.context, instance,
                mock.ANY)
        mock_setup_network.assert_called_once_with(
            self.context, instance, self.compute.host, provider_mappings=None)
        mock_instance_claim.assert_called_once_with(self.context, instance,
                                                    test_compute.NODENAME,
                                                    {}, limits)
        mock_spawn.assert_called_once_with(self.context, instance,
                test.MatchType(objects.ImageMeta),
                injected_files=[], admin_password=None,
                allocations={}, network_info=[], block_device_info='fake_bdm')
        self.mock_get_allocations.assert_called_once_with(self.context,
                                                          instance.uuid)
        mock_get_power_state.assert_called_once_with(instance)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch.object(nova.compute.resource_tracker.ResourceTracker,
                       'instance_claim')
    @mock.patch.object(neutron_api.API, 'setup_instance_network_on_host')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'spawn',
                       side_effect=test.TestingException('oops!'))
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_prep_block_device', return_value='fake_bdm')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch('nova.utils.get_image_from_system_metadata')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_terminate_volume_connections')
    def test_unshelve_spawn_fails_cleanup_volume_connections(
            self, mock_terminate_volume_connections, mock_image_meta,
            mock_notify_instance_usage, mock_prep_block_device, mock_spawn,
            mock_setup_network, mock_instance_claim,
            mock_notify_instance_action, mock_get_bdms):
        """Tests error handling when a instance fails to unshelve and makes
        sure that volume connections are cleaned up from the host
        and that the host/node values are unset on the instance.
        """
        mock_bdms = mock.Mock()
        mock_get_bdms.return_value = mock_bdms
        instance = self._create_fake_instance_obj()
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image_meta = {'properties': {'base_image_ref': uuids.image_id}}
        mock_image_meta.return_value = image_meta

        tracking = {'last_state': instance.task_state}

        def fake_claim(context, instance, node, allocations, limits):
            instance.host = self.compute.host
            instance.node = node
            requests = objects.InstancePCIRequests(requests=[])
            return claims.Claim(context, instance, node,
                                self.rt, _fake_resources(),
                                requests, limits=limits)
        mock_instance_claim.side_effect = fake_claim

        def check_save(expected_task_state=None):
            if tracking['last_state'] == task_states.UNSHELVING:
                # This is before we've failed.
                self.assertEqual(task_states.SPAWNING, instance.task_state)
                tracking['last_state'] = instance.task_state
            elif tracking['last_state'] == task_states.SPAWNING:
                # This is after we've failed.
                self.assertIsNone(instance.host)
                self.assertIsNone(instance.node)
                self.assertIsNone(instance.task_state)
                tracking['last_state'] = instance.task_state
            else:
                self.fail('Unexpected save!')

        with mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.assertRaises(test.TestingException,
                              self.compute.unshelve_instance,
                              self.context, instance, image=None,
                              filter_properties=filter_properties, node=node,
                              request_spec=objects.RequestSpec())

        mock_notify_instance_action.assert_called_once_with(
            self.context, instance, 'fake-mini', action='unshelve',
            phase='start', bdms=mock_bdms)
        mock_notify_instance_usage.assert_called_once_with(
            self.context, instance, 'unshelve.start')
        mock_prep_block_device.assert_called_once_with(
            self.context, instance, mock_bdms)
        mock_setup_network.assert_called_once_with(
            self.context, instance, self.compute.host, provider_mappings=None)
        mock_instance_claim.assert_called_once_with(self.context, instance,
                                                    test_compute.NODENAME,
                                                    {}, limits)
        mock_spawn.assert_called_once_with(
            self.context, instance, test.MatchType(objects.ImageMeta),
            injected_files=[], admin_password=None,
            allocations={}, network_info=[], block_device_info='fake_bdm')
        mock_terminate_volume_connections.assert_called_once_with(
            self.context, instance, mock_bdms)

    @mock.patch('nova.network.neutron.API.setup_instance_network_on_host')
    @mock.patch('nova.compute.utils.'
                'update_pci_request_spec_with_allocated_interface_name')
    def test_unshelve_with_resource_request(
            self, mock_update_pci, mock_setup_network):
        requested_res = [objects.RequestGroup(
            requester_id=uuids.port_1,
            provider_uuids=[uuids.rp1])]
        request_spec = objects.RequestSpec(requested_resources=requested_res)
        instance = self._create_fake_instance_obj()

        self.compute.unshelve_instance(
            self.context, instance, image=None,
            filter_properties={}, node='fake-node', request_spec=request_spec)

        mock_update_pci.assert_called_once_with(
            self.context, self.compute.reportclient, instance,
            {uuids.port_1: [uuids.rp1]})
        mock_setup_network.assert_called_once_with(
            self.context, instance, self.compute.host,
            provider_mappings={uuids.port_1: [uuids.rp1]})

    @mock.patch('nova.network.neutron.API.setup_instance_network_on_host',
                new=mock.NonCallableMock())
    @mock.patch('nova.compute.utils.'
                'update_pci_request_spec_with_allocated_interface_name')
    def test_unshelve_with_resource_request_update_raises(
            self, mock_update_pci):
        requested_res = [objects.RequestGroup(
            requester_id=uuids.port_1,
            provider_uuids=[uuids.rp1])]
        request_spec = objects.RequestSpec(requested_resources=requested_res)
        instance = self._create_fake_instance_obj()
        mock_update_pci.side_effect = (
            exception.UnexpectedResourceProviderNameForPCIRequest(
                provider=uuids.rp1,
                requester=uuids.port1,
                provider_name='unexpected'))

        self.assertRaises(
            exception.UnexpectedResourceProviderNameForPCIRequest,
            self.compute.unshelve_instance, self.context, instance, image=None,
            filter_properties={}, node='fake-node', request_spec=request_spec)

        mock_update_pci.assert_called_once_with(
            self.context, self.compute.reportclient, instance,
            {uuids.port_1: [uuids.rp1]})

    @mock.patch.object(objects.InstanceList, 'get_by_filters')
    def test_shelved_poll_none_offloaded(self, mock_get_by_filters):
        # Test instances are not offloaded when shelved_offload_time is -1
        self.flags(shelved_offload_time=-1)
        self.compute._poll_shelved_instances(self.context)
        self.assertEqual(0, mock_get_by_filters.call_count)

    @mock.patch('oslo_utils.timeutils.is_older_than')
    def test_shelved_poll_none_exist(self, mock_older):
        self.flags(shelved_offload_time=1)
        mock_older.return_value = False

        with mock.patch.object(self.compute, 'shelve_offload_instance') as soi:
            self.compute._poll_shelved_instances(self.context)
            self.assertFalse(soi.called)

    @mock.patch('oslo_utils.timeutils.is_older_than')
    def test_shelved_poll_not_timedout(self, mock_older):
        mock_older.return_value = False
        self.flags(shelved_offload_time=1)
        shelved_time = timeutils.utcnow()
        time_fixture = self.useFixture(utils_fixture.TimeFixture(shelved_time))
        time_fixture.advance_time_seconds(CONF.shelved_offload_time - 1)
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED
        instance.task_state = None
        instance.host = self.compute.host
        sys_meta = instance.system_metadata
        sys_meta['shelved_at'] = shelved_time.isoformat()
        instance.save()

        with mock.patch.object(self.compute, 'shelve_offload_instance') as soi:
            self.compute._poll_shelved_instances(self.context)
            self.assertFalse(soi.called)
            self.assertTrue(mock_older.called)

    def test_shelved_poll_timedout(self):
        self.flags(shelved_offload_time=1)
        shelved_time = timeutils.utcnow()
        time_fixture = self.useFixture(utils_fixture.TimeFixture(shelved_time))
        time_fixture.advance_time_seconds(CONF.shelved_offload_time + 1)
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED
        instance.task_state = None
        instance.host = self.compute.host
        sys_meta = instance.system_metadata
        sys_meta['shelved_at'] = shelved_time.isoformat()
        instance.save()

        data = []

        def fake_soi(context, instance, **kwargs):
            data.append(instance.uuid)

        with mock.patch.object(self.compute, 'shelve_offload_instance') as soi:
            soi.side_effect = fake_soi
            self.compute._poll_shelved_instances(self.context)
            self.assertTrue(soi.called)
            self.assertEqual(instance.uuid, data[0])

    @mock.patch('oslo_utils.timeutils.is_older_than')
    @mock.patch('oslo_utils.timeutils.parse_strtime')
    def test_shelved_poll_filters_task_state(self, mock_parse, mock_older):
        self.flags(shelved_offload_time=1)
        mock_older.return_value = True
        instance1 = self._create_fake_instance_obj()
        instance1.task_state = task_states.SPAWNING
        instance1.vm_state = vm_states.SHELVED
        instance1.host = self.compute.host
        instance1.system_metadata = {'shelved_at': ''}
        instance1.save()
        instance2 = self._create_fake_instance_obj()
        instance2.task_state = None
        instance2.vm_state = vm_states.SHELVED
        instance2.host = self.compute.host
        instance2.system_metadata = {'shelved_at': ''}
        instance2.save()

        data = []

        def fake_soi(context, instance, **kwargs):
            data.append(instance.uuid)

        with mock.patch.object(self.compute, 'shelve_offload_instance') as soi:
            soi.side_effect = fake_soi
            self.compute._poll_shelved_instances(self.context)
            self.assertTrue(soi.called)
            self.assertEqual([instance2.uuid], data)

    @mock.patch('oslo_utils.timeutils.is_older_than')
    @mock.patch('oslo_utils.timeutils.parse_strtime')
    def test_shelved_poll_checks_task_state_on_save(self, mock_parse,
                                                    mock_older):
        self.flags(shelved_offload_time=1)
        mock_older.return_value = True
        instance = self._create_fake_instance_obj()
        instance.task_state = None
        instance.vm_state = vm_states.SHELVED
        instance.host = self.compute.host
        instance.system_metadata = {'shelved_at': ''}
        instance.save()

        def fake_parse_hook(timestring):
            instance.task_state = task_states.SPAWNING
            instance.save()

        mock_parse.side_effect = fake_parse_hook

        with mock.patch.object(self.compute, 'shelve_offload_instance') as soi:
            self.compute._poll_shelved_instances(self.context)
            self.assertFalse(soi.called)


class ShelveComputeAPITestCase(test_compute.BaseTestCase):
    def _get_vm_states(self, exclude_states=None):
        vm_state = set([vm_states.ACTIVE, vm_states.BUILDING, vm_states.PAUSED,
                    vm_states.SUSPENDED, vm_states.RESCUED, vm_states.STOPPED,
                    vm_states.RESIZED, vm_states.SOFT_DELETED,
                    vm_states.DELETED, vm_states.ERROR, vm_states.SHELVED,
                    vm_states.SHELVED_OFFLOADED])
        if not exclude_states:
            exclude_states = set()
        return vm_state - exclude_states

    def _test_shelve(self, vm_state=vm_states.ACTIVE, boot_from_volume=False,
                     clean_shutdown=True):
        # Ensure instance can be shelved.
        params = dict(task_state=None, vm_state=vm_state, display_name='vm01')
        fake_instance = self._create_fake_instance_obj(params=params)
        instance = fake_instance

        self.assertIsNone(instance['task_state'])

        with test.nested(
            mock.patch.object(compute_utils, 'is_volume_backed_instance',
                              return_value=boot_from_volume),
            mock.patch.object(compute_utils, 'create_image',
                              return_value=dict(id='fake-image-id')),
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute_api, '_record_action_start'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'shelve_instance'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'shelve_offload_instance')
        ) as (
            volume_backed_inst, create_image, instance_save,
            record_action_start, rpcapi_shelve_instance,
            rpcapi_shelve_offload_instance
        ):

            self.compute_api.shelve(self.context, instance,
                                    clean_shutdown=clean_shutdown)

            self.assertEqual(instance.task_state, task_states.SHELVING)
            # assert our mock calls
            volume_backed_inst.assert_called_once_with(
                self.context, instance)
            instance_save.assert_called_once_with(expected_task_state=[None])
            record_action_start.assert_called_once_with(
                self.context, instance, instance_actions.SHELVE)
            if boot_from_volume:
                rpcapi_shelve_offload_instance.assert_called_once_with(
                    self.context, instance=instance,
                    clean_shutdown=clean_shutdown)
            else:
                rpcapi_shelve_instance.assert_called_once_with(
                    self.context, instance=instance, image_id='fake-image-id',
                    clean_shutdown=clean_shutdown)

            db.instance_destroy(self.context, instance['uuid'])

    def test_shelve(self):
        self._test_shelve()

    def test_shelves_stopped(self):
        self._test_shelve(vm_state=vm_states.STOPPED)

    def test_shelves_paused(self):
        self._test_shelve(vm_state=vm_states.PAUSED)

    def test_shelves_suspended(self):
        self._test_shelve(vm_state=vm_states.SUSPENDED)

    def test_shelves_boot_from_volume(self):
        self._test_shelve(boot_from_volume=True)

    def test_shelve_forced_shutdown(self):
        self._test_shelve(clean_shutdown=False)

    def test_shelve_boot_from_volume_forced_shutdown(self):
        self._test_shelve(boot_from_volume=True,
                          clean_shutdown=False)

    def _test_shelve_invalid_state(self, vm_state):
        params = dict(vm_state=vm_state)
        fake_instance = self._create_fake_instance_obj(params=params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.shelve,
                          self.context, fake_instance)

    def test_shelve_fails_invalid_states(self):
        invalid_vm_states = self._get_vm_states(set([vm_states.ACTIVE,
                                                     vm_states.STOPPED,
                                                     vm_states.PAUSED,
                                                     vm_states.SUSPENDED]))
        for state in invalid_vm_states:
            self._test_shelve_invalid_state(state)

    def _test_shelve_offload(self, clean_shutdown=True):
        params = dict(task_state=None, vm_state=vm_states.SHELVED)
        fake_instance = self._create_fake_instance_obj(params=params)
        with test.nested(
            mock.patch.object(fake_instance, 'save'),
            mock.patch.object(self.compute_api.compute_rpcapi,
                              'shelve_offload_instance'),
            mock.patch('nova.compute.api.API._record_action_start')
        ) as (
            instance_save, rpcapi_shelve_offload_instance, record
        ):
            self.compute_api.shelve_offload(self.context, fake_instance,
                                            clean_shutdown=clean_shutdown)
            # assert field values set on the instance object
            self.assertEqual(task_states.SHELVING_OFFLOADING,
                             fake_instance.task_state)
            instance_save.assert_called_once_with(expected_task_state=[None])
            rpcapi_shelve_offload_instance.assert_called_once_with(
                    self.context, instance=fake_instance,
                    clean_shutdown=clean_shutdown)
            record.assert_called_once_with(self.context, fake_instance,
                                           instance_actions.SHELVE_OFFLOAD)

    def test_shelve_offload(self):
        self._test_shelve_offload()

    def test_shelve_offload_forced_shutdown(self):
        self._test_shelve_offload(clean_shutdown=False)

    def _test_shelve_offload_invalid_state(self, vm_state):
        params = dict(vm_state=vm_state)
        fake_instance = self._create_fake_instance_obj(params=params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.shelve_offload,
                          self.context, fake_instance)

    def test_shelve_offload_fails_invalid_states(self):
        invalid_vm_states = self._get_vm_states(set([vm_states.SHELVED]))
        for state in invalid_vm_states:
            self._test_shelve_offload_invalid_state(state)

    def _get_specify_state_instance(self, vm_state):
        # Ensure instance can be unshelved.
        instance = self._create_fake_instance_obj()

        self.assertIsNone(instance['task_state'])

        self.compute_api.shelve(self.context, instance)

        instance.task_state = None
        instance.vm_state = vm_state
        instance.save()

        return instance

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_unshelve(self, get_by_instance_uuid):
        # Ensure instance can be unshelved.
        instance = self._get_specify_state_instance(vm_states.SHELVED)

        fake_spec = objects.RequestSpec()
        get_by_instance_uuid.return_value = fake_spec
        with mock.patch.object(self.compute_api.compute_task_api,
                               'unshelve_instance') as unshelve:
            self.compute_api.unshelve(self.context, instance)
            get_by_instance_uuid.assert_called_once_with(self.context,
                                                         instance.uuid)
            unshelve.assert_called_once_with(self.context, instance, fake_spec)

        self.assertEqual(instance.task_state, task_states.UNSHELVING)

        db.instance_destroy(self.context, instance['uuid'])

    @mock.patch('nova.availability_zones.get_availability_zones',
                return_value=['az1', 'az2'])
    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_specified_az_ushelve_invalid_request(self,
                                                  get_by_instance_uuid,
                                                  mock_save,
                                                  mock_availability_zones):
        # Ensure instance can be unshelved.
        instance = self._get_specify_state_instance(
            vm_states.SHELVED_OFFLOADED)

        new_az = "fake-new-az"
        fake_spec = objects.RequestSpec()
        fake_spec.availability_zone = "fake-old-az"
        get_by_instance_uuid.return_value = fake_spec

        exc = self.assertRaises(exception.InvalidRequest,
                                self.compute_api.unshelve,
                                self.context, instance, new_az=new_az)
        self.assertEqual("The requested availability zone is not available",
                         exc.format_message())

    @mock.patch('nova.availability_zones.get_availability_zones',
                return_value=['az1', 'az2'])
    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_specified_az_unshelve_invalid_state(self, get_by_instance_uuid,
                                                 mock_save,
                                                 mock_availability_zones):
        # Ensure instance can be unshelved.
        instance = self._get_specify_state_instance(vm_states.SHELVED)

        new_az = "az1"
        fake_spec = objects.RequestSpec()
        fake_spec.availability_zone = "fake-old-az"
        get_by_instance_uuid.return_value = fake_spec

        self.assertRaises(exception.UnshelveInstanceInvalidState,
                          self.compute_api.unshelve,
                          self.context, instance, new_az=new_az)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid',
                new_callable=mock.NonCallableMock)
    @mock.patch('nova.availability_zones.get_availability_zones')
    def test_validate_unshelve_az_cross_az_attach_true(
            self, mock_get_azs, mock_get_bdms):
        """Tests a case where the new AZ to unshelve does not match the volume
        attached to the server but cross_az_attach=True so it's not an error.
        """
        # Ensure instance can be unshelved.
        instance = self._create_fake_instance_obj(
            params=dict(vm_state=vm_states.SHELVED_OFFLOADED))

        new_az = "west_az"
        mock_get_azs.return_value = ["west_az", "east_az"]
        self.flags(cross_az_attach=True, group='cinder')
        self.compute_api._validate_unshelve_az(self.context, instance, new_az)
        mock_get_azs.assert_called_once_with(
            self.context, self.compute_api.host_api, get_only_available=True)

    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.availability_zones.get_availability_zones')
    def test_validate_unshelve_az_cross_az_attach_false(
            self, mock_get_azs, mock_get_bdms, mock_get):
        """Tests a case where the new AZ to unshelve does not match the volume
        attached to the server and cross_az_attach=False so it's an error.
        """
        # Ensure instance can be unshelved.
        instance = self._create_fake_instance_obj(
            params=dict(vm_state=vm_states.SHELVED_OFFLOADED))

        new_az = "west_az"
        mock_get_azs.return_value = ["west_az", "east_az"]

        bdms = [objects.BlockDeviceMapping(destination_type='volume',
                                           volume_id=uuids.volume_id)]
        mock_get_bdms.return_value = bdms
        volume = {'id': uuids.volume_id, 'availability_zone': 'east_az'}
        mock_get.return_value = volume

        self.flags(cross_az_attach=False, group='cinder')
        self.assertRaises(exception.MismatchVolumeAZException,
                          self.compute_api._validate_unshelve_az,
                          self.context, instance, new_az)
        mock_get_azs.assert_called_once_with(
            self.context, self.compute_api.host_api, get_only_available=True)
        mock_get_bdms.assert_called_once_with(self.context, instance.uuid)
        mock_get.assert_called_once_with(self.context, uuids.volume_id)

    @mock.patch.object(compute_api.API, '_validate_unshelve_az')
    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_specified_az_unshelve(self, get_by_instance_uuid,
                                   mock_save, mock_validate_unshelve_az):
        # Ensure instance can be unshelved.
        instance = self._get_specify_state_instance(
            vm_states.SHELVED_OFFLOADED)

        new_az = "west_az"
        fake_spec = objects.RequestSpec()
        fake_spec.availability_zone = "fake-old-az"
        get_by_instance_uuid.return_value = fake_spec

        self.compute_api.unshelve(self.context, instance, new_az=new_az)

        mock_save.assert_called_once_with()
        self.assertEqual(new_az, fake_spec.availability_zone)

        mock_validate_unshelve_az.assert_called_once_with(
            self.context, instance, new_az)
