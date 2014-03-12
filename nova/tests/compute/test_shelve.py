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

import iso8601
import mox
from oslo.config import cfg

from nova.compute import claims
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.tests.compute import test_compute
from nova.tests.image import fake as fake_image
from nova import utils

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
    def _shelve_instance(self, shelved_offload_time):
        CONF.set_override('shelved_offload_time', shelved_offload_time)
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, db_instance, {}, {}, [], None,
                None, True, None, False)
        instance = instance_obj.Instance.get_by_uuid(
            self.context, db_instance['uuid'],
            expected_attrs=['metadata', 'system_metadata'])
        image_id = 'fake_image_id'
        host = 'fake-mini'
        cur_time = timeutils.utcnow()
        timeutils.set_time_override(cur_time)
        instance.task_state = task_states.SHELVING
        instance.save()
        sys_meta = dict(instance.system_metadata)
        sys_meta['shelved_at'] = timeutils.strtime(at=cur_time)
        sys_meta['shelved_image_id'] = image_id
        sys_meta['shelved_host'] = host
        db_instance['system_metadata'] = utils.dict_to_metadata(sys_meta)

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'snapshot')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve.start')
        self.compute.driver.power_off(instance)
        self.compute._get_power_state(self.context,
                instance).AndReturn(123)
        self.compute.driver.snapshot(self.context, instance, 'fake_image_id',
                mox.IgnoreArg())

        update_values = {'power_state': 123,
                         'vm_state': vm_states.SHELVED,
                         'task_state': None,
                         'expected_task_state': [task_states.SHELVING,
                                task_states.SHELVING_IMAGE_UPLOADING],
                         'system_metadata': sys_meta}
        if CONF.shelved_offload_time == 0:
            update_values['task_state'] = task_states.SHELVING_OFFLOADING
        db.instance_update_and_get_original(self.context, instance['uuid'],
                 update_values, update_cells=False,
                 columns_to_join=['metadata', 'system_metadata'],
                ).AndReturn((db_instance,
                                                db_instance))
        self.compute._notify_about_instance_usage(self.context,
                                                  instance, 'shelve.end')
        if CONF.shelved_offload_time == 0:
            self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.start')
            self.compute.driver.power_off(instance)
            self.compute._get_power_state(self.context,
                                          instance).AndReturn(123)
            db.instance_update_and_get_original(self.context,
                              instance['uuid'],
                              {'power_state': 123, 'host': None, 'node': None,
                               'vm_state': vm_states.SHELVED_OFFLOADED,
                               'task_state': None,
                               'expected_task_state': [task_states.SHELVING,
                                           task_states.SHELVING_OFFLOADING]},
                              update_cells=False,
                              columns_to_join=['metadata', 'system_metadata'],
                              ).AndReturn((db_instance, db_instance))
            self.compute._notify_about_instance_usage(self.context, instance,
                                                      'shelve_offload.end')
        self.mox.ReplayAll()

        self.compute.shelve_instance(self.context, instance,
                image_id=image_id)

    def test_shelve(self):
        self._shelve_instance(-1)

    def test_shelve_offload(self):
        self._shelve_instance(0)

    def test_shelve_volume_backed(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, db_instance, {}, {}, [], None,
                None, True, None, False)
        instance = instance_obj.Instance.get_by_uuid(
            self.context, db_instance['uuid'],
            expected_attrs=['metadata', 'system_metadata'])
        instance.task_state = task_states.SHELVING
        instance.save()
        host = 'fake-mini'
        cur_time = timeutils.utcnow()
        timeutils.set_time_override(cur_time)
        sys_meta = dict(instance.system_metadata)
        sys_meta['shelved_at'] = timeutils.strtime(at=cur_time)
        sys_meta['shelved_image_id'] = None
        sys_meta['shelved_host'] = host
        db_instance['system_metadata'] = utils.dict_to_metadata(sys_meta)

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'power_off')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.start')
        self.compute.driver.power_off(instance)
        self.compute._get_power_state(self.context,
                instance).AndReturn(123)
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'power_state': 123, 'host': None, 'node': None,
                 'vm_state': vm_states.SHELVED_OFFLOADED,
                 'task_state': None,
                 'expected_task_state': [task_states.SHELVING,
                    task_states.SHELVING_OFFLOADING]},
                 update_cells=False,
                 columns_to_join=['metadata', 'system_metadata'],
                 ).AndReturn((db_instance, db_instance))
        self.compute._notify_about_instance_usage(self.context, instance,
                'shelve_offload.end')
        self.mox.ReplayAll()

        self.compute.shelve_offload_instance(self.context, instance)

    def test_unshelve(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, db_instance, {}, {}, [], None,
                None, True, None, False)
        instance = instance_obj.Instance.get_by_uuid(
            self.context, db_instance['uuid'],
            expected_attrs=['metadata', 'system_metadata'])
        instance.task_state = task_states.UNSHELVING
        instance.save()
        image = {'id': 'fake_id'}
        host = 'fake-mini'
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        cur_time = timeutils.utcnow()
        cur_time_tz = cur_time.replace(tzinfo=iso8601.iso8601.Utc())
        timeutils.set_time_override(cur_time)
        sys_meta = dict(instance.system_metadata)
        sys_meta['shelved_at'] = timeutils.strtime(at=cur_time)
        sys_meta['shelved_image_id'] = image['id']
        sys_meta['shelved_host'] = host

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.deleted_image_id = None

        def fake_delete(self2, ctxt, image_id):
            self.deleted_image_id = image_id

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'delete', fake_delete)

        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.start')
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'task_state': task_states.SPAWNING},
                update_cells=False,
                columns_to_join=['metadata', 'system_metadata'],
                ).AndReturn((db_instance, db_instance))
        self.compute._prep_block_device(self.context, instance,
                mox.IgnoreArg()).AndReturn('fake_bdm')
        db_instance['key_data'] = None
        db_instance['auto_disk_config'] = None
        self.rt.instance_claim(self.context, instance, limits).AndReturn(
                claims.Claim(db_instance, self.rt, _fake_resources()))
        self.compute.driver.spawn(self.context, instance, image,
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm')
        self.compute._get_power_state(self.context, instance).AndReturn(123)
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'power_state': 123,
                 'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'image_ref': instance['image_ref'],
                 'key_data': None,
                 'auto_disk_config': False,
                 'expected_task_state': task_states.SPAWNING,
                 'launched_at': cur_time_tz},
                 update_cells=False,
                 columns_to_join=['metadata', 'system_metadata']
                 ).AndReturn((db_instance, db_instance))
        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.end')
        self.mox.ReplayAll()

        self.compute.unshelve_instance(self.context, instance, image=image,
                filter_properties=filter_properties, node=node)
        self.assertEqual(image['id'], self.deleted_image_id)
        self.assertEqual(instance.host, self.compute.host)

    def test_unshelve_volume_backed(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        host = 'fake-mini'
        node = test_compute.NODENAME
        limits = {}
        filter_properties = {'limits': limits}
        cur_time = timeutils.utcnow()
        cur_time_tz = cur_time.replace(tzinfo=iso8601.iso8601.Utc())
        timeutils.set_time_override(cur_time)
        self.compute.run_instance(self.context, db_instance, {}, {}, [], None,
                None, True, None, False)
        instance = instance_obj.Instance.get_by_uuid(
            self.context, db_instance['uuid'],
            expected_attrs=['metadata', 'system_metadata'])
        instance.task_state = task_states.UNSHELVING
        instance.save()
        sys_meta = dict(instance.system_metadata)
        sys_meta['shelved_at'] = timeutils.strtime(at=cur_time)
        sys_meta['shelved_image_id'] = None
        sys_meta['shelved_host'] = host

        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.rt, 'instance_claim')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.start')
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'task_state': task_states.SPAWNING},
                update_cells=False,
                columns_to_join=['metadata', 'system_metadata']
                ).AndReturn((db_instance, db_instance))
        self.compute._prep_block_device(self.context, instance,
                mox.IgnoreArg()).AndReturn('fake_bdm')
        db_instance['key_data'] = None
        db_instance['auto_disk_config'] = None
        self.rt.instance_claim(self.context, instance, limits).AndReturn(
                claims.Claim(db_instance, self.rt, _fake_resources()))
        self.compute.driver.spawn(self.context, instance, None,
                injected_files=[], admin_password=None,
                network_info=[],
                block_device_info='fake_bdm')
        self.compute._get_power_state(self.context, instance).AndReturn(123)
        db.instance_update_and_get_original(self.context, instance['uuid'],
                {'power_state': 123,
                 'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'key_data': None,
                 'auto_disk_config': False,
                 'expected_task_state': task_states.SPAWNING,
                 'launched_at': cur_time_tz},
                 update_cells=False,
                 columns_to_join=['metadata', 'system_metadata']
                 ).AndReturn((db_instance, db_instance))
        self.compute._notify_about_instance_usage(self.context, instance,
                'unshelve.end')
        self.mox.ReplayAll()

        self.compute.unshelve_instance(self.context, instance, image=None,
                filter_properties=filter_properties, node=node)

    def test_shelved_poll_none_exist(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance, {}, {}, [], None,
                None, True, None, False)
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.StubOutWithMock(timeutils, 'is_older_than')
        self.mox.ReplayAll()
        self.compute._poll_shelved_instances(self.context)

    def test_shelved_poll_not_timedout(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance, {}, {}, [], None,
                None, True, None, False)
        sys_meta = utils.metadata_to_dict(instance['system_metadata'])
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
        active_instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, active_instance, {}, {}, [],
                None, None, True, None, False)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance, {}, {}, [], None,
                None, True, None, False)
        sys_meta = utils.metadata_to_dict(instance['system_metadata'])
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
        fake_instance = self._create_fake_instance({'display_name': 'vm01'})
        instance = jsonutils.to_primitive(fake_instance)
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance, {}, {}, [], None,
                None, True, None, False)

        self.assertIsNone(instance['task_state'])

        def fake_init(self2):
            # In original _FakeImageService.__init__(), some fake images are
            # created. To verify the snapshot name of this test only, here
            # sets a fake method.
            self2.images = {}

        def fake_create(self2, ctxt, metadata):
            self.assertEqual(metadata['name'], 'vm01-shelved')
            metadata['id'] = '8b24ed3f-ee57-43bc-bc2e-fb2e9482bc42'
            return metadata

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, '__init__', fake_init)
        self.stubs.Set(fake_image._FakeImageService, 'create', fake_create)

        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     instance_uuid)
        self.compute_api.shelve(self.context, inst_obj)

        inst_obj.refresh()
        self.assertEqual(inst_obj.task_state, task_states.SHELVING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_unshelve(self):
        # Ensure instance can be unshelved.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance, {}, {}, [], None,
                None, True, None, False)

        self.assertIsNone(instance['task_state'])

        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     instance_uuid)
        self.compute_api.shelve(self.context, inst_obj)

        inst_obj.refresh()
        inst_obj.task_state = None
        inst_obj.vm_state = vm_states.SHELVED
        inst_obj.save()

        self.compute_api.unshelve(self.context, inst_obj)

        inst_obj.refresh()
        self.assertEqual(inst_obj.task_state, task_states.UNSHELVING)

        db.instance_destroy(self.context, instance['uuid'])
