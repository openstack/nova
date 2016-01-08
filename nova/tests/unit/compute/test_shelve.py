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
from mox3 import mox
from oslo_config import cfg
from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils

from nova.compute import claims
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import objects
from nova.tests.unit.compute import test_compute
from nova.tests.unit.image import fake as fake_image

CONF = cfg.CONF
CONF.import_opt('shelved_offload_time', 'nova.compute.manager')


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
    def _shelve_instance(self, shelved_offload_time, clean_shutdown=True):
        CONF.set_override('shelved_offload_time', shelved_offload_time)
        host = 'fake-mini'
        instance = self._create_fake_instance_obj(params={'host': host})
        image_id = 'fake_image_id'
        host = 'fake-mini'
        self.useFixture(utils_fixture.TimeFixture())
        instance.task_state = task_states.SHELVING
        instance.save()

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'snapshot')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'cleanup_instance_network_on_host')

        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve.start')
        if clean_shutdown:
            self.compute.driver.power_off(instance,
                                          CONF.shutdown_timeout,
                                          self.compute.SHUTDOWN_RETRY_INTERVAL)
        else:
            self.compute.driver.power_off(instance, 0, 0)
        self.compute._get_power_state(self.context,
                instance).AndReturn(123)
        if CONF.shelved_offload_time == 0:
            self.compute.network_api.cleanup_instance_network_on_host(
                self.context, instance, instance.host)
        self.compute.driver.snapshot(self.context, instance, 'fake_image_id',
                mox.IgnoreArg())

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
                self.assertIsNone(instance.host)
                self.assertIsNone(instance.node)
                self.assertIsNone(instance.task_state)
                self.assertEqual(vm_states.SHELVED_OFFLOADED,
                                 instance.vm_state)
                self.assertEqual([task_states.SHELVING,
                                  task_states.SHELVING_OFFLOADING],
                                 expected_task_state)
                tracking['last_state'] = instance.vm_state
            else:
                self.fail('Unexpected save!')

        self.compute._notify_about_instance_usage(self.context,
                                                  instance, 'shelve.end')
        if CONF.shelved_offload_time == 0:
            self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.start')
            self.compute.driver.power_off(instance, 0, 0)
            self.compute._get_power_state(self.context,
                                          instance).AndReturn(123)
            self.compute._notify_about_instance_usage(self.context, instance,
                                                      'shelve_offload.end')
        self.mox.ReplayAll()

        with mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.shelve_instance(self.context, instance,
                    image_id=image_id, clean_shutdown=clean_shutdown)

    def test_shelve(self):
        self._shelve_instance(-1)

    def test_shelve_forced_shutdown(self):
        self._shelve_instance(-1, clean_shutdown=False)

    def test_shelve_and_offload(self):
        self._shelve_instance(0)

    def _shelve_offload(self, clean_shutdown=True):
        host = 'fake-mini'
        instance = self._create_fake_instance_obj(params={'host': host})
        instance.task_state = task_states.SHELVING
        instance.save()
        self.useFixture(utils_fixture.TimeFixture())

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'cleanup_instance_network_on_host')
        self.mox.StubOutWithMock(self.compute, '_update_resource_tracker')

        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.start')
        if clean_shutdown:
            self.compute.driver.power_off(instance,
                                          CONF.shutdown_timeout,
                                          self.compute.SHUTDOWN_RETRY_INTERVAL)
        else:
            self.compute.driver.power_off(instance, 0, 0)
        self.compute.network_api.cleanup_instance_network_on_host(
                self.context, instance, instance.host)
        self.compute._get_power_state(self.context,
                instance).AndReturn(123)
        self.compute._update_resource_tracker(self.context, instance)
        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.end')
        self.mox.ReplayAll()

        with mock.patch.object(instance, 'save'):
            self.compute.shelve_offload_instance(self.context, instance,
                                                 clean_shutdown=clean_shutdown)
        self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)
        self.assertIsNone(instance.task_state)

    def test_shelve_offload(self):
        self._shelve_offload()

    def test_shelve_offload_forced_shutdown(self):
        self._shelve_offload(clean_shutdown=False)

    def test_unshelve(self):
        instance = self._create_fake_instance_obj()
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image = {'id': 'fake_id'}
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

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_instance_network_on_host')

        self.deleted_image_id = None

        def fake_delete(self2, ctxt, image_id):
            self.deleted_image_id = image_id

        def fake_claim(context, instance, limits):
            instance.host = self.compute.host
            return claims.Claim(context, instance,
                                self.rt, _fake_resources())

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

        fake_image.stub_out_image_service(self)
        self.stubs.Set(fake_image._FakeImageService, 'delete', fake_delete)

        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.start')
        self.compute._prep_block_device(self.context, instance,
                mox.IgnoreArg(), do_check_attach=False).AndReturn('fake_bdm')
        self.compute.network_api.setup_instance_network_on_host(
                self.context, instance, self.compute.host)
        self.compute.driver.spawn(self.context, instance,
                mox.IsA(objects.ImageMeta),
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm')
        self.compute._get_power_state(self.context, instance).AndReturn(123)
        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.end')
        self.mox.ReplayAll()

        with mock.patch.object(self.rt, 'instance_claim',
                               side_effect=fake_claim), \
                 mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.unshelve_instance(
                self.context, instance, image=image,
                filter_properties=filter_properties,
                node=node)
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

    @mock.patch('nova.utils.get_image_from_system_metadata')
    def test_unshelve_volume_backed(self, mock_image_meta):
        instance = self._create_fake_instance_obj()
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image_meta = {'properties': {'base_image_ref': 'fake_id'}}
        mock_image_meta.return_value = image_meta

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_instance_network_on_host')

        tracking = {'last_state': instance.task_state}

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

        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.start')

        self.compute._prep_block_device(self.context, instance,
                mox.IgnoreArg(), do_check_attach=False).AndReturn('fake_bdm')
        self.compute.network_api.setup_instance_network_on_host(
                self.context, instance, self.compute.host)
        self.rt.instance_claim(self.context, instance, limits).AndReturn(
                claims.Claim(self.context, instance, self.rt,
                             _fake_resources()))
        self.compute.driver.spawn(self.context, instance,
                mox.IsA(objects.ImageMeta),
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm')
        self.compute._get_power_state(self.context, instance).AndReturn(123)
        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.end')
        self.mox.ReplayAll()

        with mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.unshelve_instance(self.context, instance, image=None,
                    filter_properties=filter_properties, node=node)

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
    def test_shelve(self):
        # Ensure instance can be shelved.
        fake_instance = self._create_fake_instance_obj(
            {'display_name': 'vm01'})
        instance = fake_instance

        self.assertIsNone(instance['task_state'])

        def fake_init(self2):
            # In original _FakeImageService.__init__(), some fake images are
            # created. To verify the snapshot name of this test only, here
            # sets a fake method.
            self2.images = {}

        def fake_create(self2, ctxt, metadata, data=None):
            self.assertEqual(metadata['name'], 'vm01-shelved')
            metadata['id'] = '8b24ed3f-ee57-43bc-bc2e-fb2e9482bc42'
            return metadata

        fake_image.stub_out_image_service(self)
        self.stubs.Set(fake_image._FakeImageService, '__init__', fake_init)
        self.stubs.Set(fake_image._FakeImageService, 'create', fake_create)

        self.compute_api.shelve(self.context, instance)

        self.assertEqual(instance.task_state, task_states.SHELVING)

        db.instance_destroy(self.context, instance['uuid'])

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_unshelve(self, get_by_instance_uuid):
        # Ensure instance can be unshelved.
        instance = self._create_fake_instance_obj()

        self.assertIsNone(instance['task_state'])

        self.compute_api.shelve(self.context, instance)

        instance.task_state = None
        instance.vm_state = vm_states.SHELVED
        instance.save()

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
