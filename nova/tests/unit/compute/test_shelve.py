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
from oslo.config import cfg
from oslo.utils import timeutils

from nova.compute import claims
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
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
    return resources


class ShelveComputeManagerTestCase(test_compute.BaseTestCase):
    def _shelve_instance(self, shelved_offload_time, clean_shutdown=True):
        CONF.set_override('shelved_offload_time', shelved_offload_time)
        instance = self._create_fake_instance_obj()
        image_id = 'fake_image_id'
        host = 'fake-mini'
        cur_time = timeutils.utcnow()
        timeutils.set_time_override(cur_time)
        instance.task_state = task_states.SHELVING
        instance.save()

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'snapshot')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')

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
        instance = self._create_fake_instance_obj()
        instance.task_state = task_states.SHELVING
        instance.save()
        cur_time = timeutils.utcnow()
        timeutils.set_time_override(cur_time)

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')

        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.start')
        if clean_shutdown:
            self.compute.driver.power_off(instance,
                                          CONF.shutdown_timeout,
                                          self.compute.SHUTDOWN_RETRY_INTERVAL)
        else:
            self.compute.driver.power_off(instance, 0, 0)
        self.compute._get_power_state(self.context,
                instance).AndReturn(123)
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

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'migrate_instance_finish')

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

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'delete', fake_delete)

        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.start')
        self.compute._prep_block_device(self.context, instance,
                mox.IgnoreArg(), do_check_attach=False).AndReturn('fake_bdm')
        self.compute.network_api.migrate_instance_finish(
                self.context, instance, {'source_compute': '',
                                         'dest_compute': self.compute.host})
        self.compute.driver.spawn(self.context, instance, image,
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm',
                flavor=None)
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
        self.assertEqual(image['id'], self.deleted_image_id)
        self.assertEqual(instance.host, self.compute.host)

        self.assertEqual(123, instance.power_state)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertIsNone(instance.task_state)
        self.assertIsNone(instance.key_data)
        self.assertEqual(self.compute.host, instance.host)
        self.assertFalse(instance.auto_disk_config)

    def test_unshelve_volume_backed(self):
        instance = self._create_fake_instance_obj()
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        instance.task_state = task_states.UNSHELVING
        instance.save()

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'migrate_instance_finish')

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
        self.compute.network_api.migrate_instance_finish(
                self.context, instance, {'source_compute': '',
                                         'dest_compute': self.compute.host})
        self.rt.instance_claim(self.context, instance, limits).AndReturn(
                claims.Claim(self.context, instance, self.rt,
                             _fake_resources()))
        self.compute.driver.spawn(self.context, instance, None,
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm',
                flavor=None)
        self.compute._get_power_state(self.context, instance).AndReturn(123)
        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.end')
        self.mox.ReplayAll()

        with mock.patch.object(instance, 'save') as mock_save:
            mock_save.side_effect = check_save
            self.compute.unshelve_instance(self.context, instance, image=None,
                    filter_properties=filter_properties, node=node)

    def test_shelved_poll_none_exist(self):
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.StubOutWithMock(timeutils, 'is_older_than')
        self.mox.ReplayAll()
        self.compute._poll_shelved_instances(self.context)

    def test_shelved_poll_not_timedout(self):
        instance = self._create_fake_instance_obj()
        sys_meta = instance.system_metadata
        shelved_time = timeutils.utcnow()
        timeutils.set_time_override(shelved_time)
        timeutils.advance_time_seconds(CONF.shelved_offload_time - 1)
        sys_meta['shelved_at'] = timeutils.strtime(at=shelved_time)
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'vm_state': vm_states.SHELVED, 'system_metadata': sys_meta})

        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.ReplayAll()
        self.compute._poll_shelved_instances(self.context)

    def test_shelved_poll_timedout(self):
        instance = self._create_fake_instance_obj()
        sys_meta = instance.system_metadata
        shelved_time = timeutils.utcnow()
        timeutils.set_time_override(shelved_time)
        timeutils.advance_time_seconds(CONF.shelved_offload_time + 1)
        sys_meta['shelved_at'] = timeutils.strtime(at=shelved_time)
        (old, instance) = db.instance_update_and_get_original(self.context,
                instance['uuid'], {'vm_state': vm_states.SHELVED,
                                   'system_metadata': sys_meta})

        def fake_destroy(inst, nw_info, bdm):
            # NOTE(alaski) There are too many differences between an instance
            # as returned by instance_update_and_get_original and
            # instance_get_all_by_filters so just compare the uuid.
            self.assertEqual(instance['uuid'], inst['uuid'])

        self.stubs.Set(self.compute.driver, 'destroy', fake_destroy)
        self.compute._poll_shelved_instances(self.context)


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

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, '__init__', fake_init)
        self.stubs.Set(fake_image._FakeImageService, 'create', fake_create)

        self.compute_api.shelve(self.context, instance)

        self.assertEqual(instance.task_state, task_states.SHELVING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_unshelve(self):
        # Ensure instance can be unshelved.
        instance = self._create_fake_instance_obj()

        self.assertIsNone(instance['task_state'])

        self.compute_api.shelve(self.context, instance)

        instance.task_state = None
        instance.vm_state = vm_states.SHELVED
        instance.save()

        self.compute_api.unshelve(self.context, instance)

        self.assertEqual(instance.task_state, task_states.UNSHELVING)

        db.instance_destroy(self.context, instance['uuid'])
