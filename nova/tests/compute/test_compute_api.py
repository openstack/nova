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

import datetime
import mox

from nova.compute import api as compute_api
from nova.compute import cells_api as compute_cells_api
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import quota
from nova import test


FAKE_IMAGE_REF = 'fake-image-ref'
NODENAME = 'fakenode1'


class _ComputeAPIUnitTestMixIn(object):
    def setUp(self):
        super(_ComputeAPIUnitTestMixIn, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def _create_flavor(self, params=None):
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
                 }
        if params:
            flavor.update(params)
        return flavor

    def _create_instance_obj(self, params=None, flavor=None):
        """Create a test instance."""
        if not params:
            params = {}

        if flavor is None:
            flavor = self._create_flavor()

        def make_fake_sys_meta():
            sys_meta = {}
            for key in flavors.system_metadata_flavor_props:
                sys_meta['instance_type_%s' % key] = flavor[key]
            return sys_meta

        now = timeutils.utcnow()

        instance = instance_obj.Instance()
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
        instance.instance_type_id = flavor['id']
        instance.ami_launch_index = 0
        instance.memory_mb = 0
        instance.vcpus = 0
        instance.root_gb = 0
        instance.ephemeral_gb = 0
        instance.architecture = 'x86_64'
        instance.os_type = 'Linux'
        instance.system_metadata = make_fake_sys_meta()
        instance.locked = False
        instance.created_at = now
        instance.updated_at = now
        instance.launched_at = now
        instance.disable_terminate = False

        if params:
            instance.update(params)
        instance.obj_reset_changes()
        return instance

    def test_suspend(self):
        # Ensure instance can be suspended.
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertEqual(instance.task_state, None)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'suspend_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.SUSPEND)
        rpcapi.suspend_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.suspend(self.context, instance)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertEqual(task_states.SUSPENDING,
                         instance.task_state)

    def test_resume(self):
        # Ensure instance can be resumed (if suspended).
        instance = self._create_instance_obj(
                params=dict(vm_state=vm_states.SUSPENDED))
        self.assertEqual(instance.vm_state, vm_states.SUSPENDED)
        self.assertEqual(instance.task_state, None)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'resume_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.RESUME)
        rpcapi.resume_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.resume(self.context, instance)
        self.assertEqual(vm_states.SUSPENDED, instance.vm_state)
        self.assertEqual(task_states.RESUMING,
                         instance.task_state)

    def test_start(self):
        params = dict(vm_state=vm_states.STOPPED)
        instance = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.START)

        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        self.mox.StubOutWithMock(rpcapi, 'start_instance')
        rpcapi.start_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.start(self.context, instance)
        self.assertEqual(task_states.POWERING_ON,
                         instance.task_state)

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

    def test_stop(self):
        # Make sure 'progress' gets reset
        params = dict(task_state=None, progress=99)
        instance = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.STOP)

        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        self.mox.StubOutWithMock(rpcapi, 'stop_instance')
        rpcapi.stop_instance(self.context, instance, do_cast=True)

        self.mox.ReplayAll()

        self.compute_api.stop(self.context, instance)
        self.assertEqual(task_states.POWERING_OFF,
                         instance.task_state)
        self.assertEqual(0, instance.progress)

    def test_stop_invalid_state(self):
        params = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.stop,
                          self.context, instance)

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

    def _test_reboot_type(self, vm_state, reboot_type, task_state=None):
        # Ensure instance can be soft rebooted.
        inst = self._create_instance_obj()
        inst.vm_state = vm_state
        inst.task_state = task_state

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(self.compute_api, '_get_block_device_info')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(inst, 'save')
        inst.save(expected_task_state=[None, task_states.REBOOTING])
        self.context.elevated().AndReturn(self.context)
        self.compute_api._get_block_device_info(self.context, inst.uuid
                                                ).AndReturn('blkinfo')
        self.compute_api._record_action_start(self.context, inst,
                                              instance_actions.REBOOT)

        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        self.mox.StubOutWithMock(rpcapi, 'reboot_instance')
        rpcapi.reboot_instance(self.context, instance=inst,
                               block_device_info='blkinfo',
                               reboot_type=reboot_type)
        self.mox.ReplayAll()

        self.compute_api.reboot(self.context, inst, reboot_type)

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

    def test_reboot_hard_rescued(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.RESCUED)

    def test_reboot_hard_error_not_launched(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.ERROR,
                                     launched_at=None)

    def test_reboot_soft(self):
        self._test_reboot_type(vm_states.ACTIVE, 'SOFT')

    def test_reboot_soft_error(self):
        self._test_reboot_type(vm_states.ERROR, 'SOFT')

    def test_reboot_soft_rebooting(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.REBOOTING)

    def test_reboot_soft_rescued(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.RESCUED)

    def test_reboot_soft_error_not_launched(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.ERROR,
                                     launched_at=None)

    def _test_delete_resized_part(self, db_inst):
        migration = {'source_compute': 'foo'}
        self.context.elevated().AndReturn(self.context)
        db.migration_get_by_instance_and_status(
            self.context, db_inst['uuid'], 'finished').AndReturn(migration)
        self.compute_api._downsize_quota_delta(self.context, db_inst
                                               ).AndReturn('deltas')
        self.compute_api._reserve_quota_delta(self.context, 'deltas'
                                              ).AndReturn('rsvs')
        self.compute_api._record_action_start(
            self.context, db_inst, instance_actions.CONFIRM_RESIZE)
        self.compute_api.compute_rpcapi.confirm_resize(
            self.context, db_inst, migration,
            host=migration['source_compute'],
            cast=False, reservations='rsvs')

    def _test_delete(self, delete_type, **attrs):
        inst = self._create_instance_obj()
        inst.update(attrs)
        delete_time = datetime.datetime(1955, 11, 5, 9, 30)
        timeutils.set_time_override(delete_time)
        task_state = (delete_type == 'soft_delete' and
                      task_states.SOFT_DELETING or task_states.DELETING)
        db_inst = obj_base.obj_to_primitive(inst)
        updates = {'progress': 0, 'task_state': task_state}
        if delete_type == 'soft_delete':
            updates['deleted_at'] = delete_time
        new_inst = dict(db_inst, **updates)
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.compute_api, '_create_reservations')
        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(self.compute_api.servicegroup_api,
                                 'service_is_up')
        self.mox.StubOutWithMock(db, 'migration_get_by_instance_and_status')
        self.mox.StubOutWithMock(self.compute_api, '_downsize_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_info_cache_delete')
        self.mox.StubOutWithMock(self.compute_api.network_api,
                                 'deallocate_for_instance')
        self.mox.StubOutWithMock(db, 'instance_system_metadata_get')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'terminate_instance')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'soft_delete_instance')

        db.block_device_mapping_get_all_by_instance(
            self.context, inst.uuid).AndReturn([])
        db.instance_update_and_get_original(
            self.context, inst.uuid, updates).AndReturn((db_inst, new_inst))
        self.compute_api._create_reservations(
            self.context, db_inst, new_inst, inst.project_id, inst.user_id
            ).AndReturn('fake-resv')

        if inst.vm_state == vm_states.RESIZED:
            self._test_delete_resized_part(db_inst)

        self.context.elevated().MultipleTimes().AndReturn(self.context)
        db.service_get_by_compute_host(self.context, inst.host).AndReturn(
            'fake-service')
        self.compute_api.servicegroup_api.service_is_up(
            'fake-service').AndReturn(inst.host != 'down-host')

        if inst.host == 'down-host' and (
                not self.is_cells or not inst.cell_name):
            db.instance_info_cache_delete(self.context, inst.uuid)
            compute_utils.notify_about_instance_usage(self.context,
                                                      db_inst, 'delete.start')
            self.compute_api.network_api.deallocate_for_instance(
                self.context, db_inst)
            db.instance_system_metadata_get(self.context, inst.uuid
                                            ).AndReturn('sys-meta')
            updates = {'vm_state': vm_states.DELETED,
                       'task_state': None,
                       'terminated_at': delete_time}
            del_inst = dict(new_inst, **updates)
            db.instance_update_and_get_original(
                self.context, inst.uuid, updates
                ).AndReturn((db_inst, del_inst))
            db.instance_destroy(self.context, inst.uuid)
            compute_utils.notify_about_instance_usage(
                self.context, del_inst, 'delete.end',
                system_metadata='sys-meta')
        if inst.host == 'down-host':
            quota.QUOTAS.commit(self.context, 'fake-resv',
                                project_id=inst.project_id,
                                user_id=inst.user_id)
        elif delete_type == 'soft_delete':
            self.compute_api._record_action_start(self.context, db_inst,
                                                  instance_actions.DELETE)
            self.compute_api.compute_rpcapi.soft_delete_instance(
                self.context, db_inst, reservations='fake-resv')
        elif delete_type in ['delete', 'force_delete']:
            self.compute_api._record_action_start(self.context, db_inst,
                                                  instance_actions.DELETE)
            self.compute_api.compute_rpcapi.terminate_instance(
                self.context, db_inst, [], reservations='fake-resv')

        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api, '_cast_to_cells')
            self.compute_api._cast_to_cells(
                self.context, db_inst, delete_type)

        self.mox.ReplayAll()

        getattr(self.compute_api, delete_type)(self.context, db_inst)

    def test_delete(self):
        self._test_delete('delete')

    def test_delete_if_not_launched(self):
        self._test_delete('delete', launched_at=None)

    def test_delete_in_resizing(self):
        self._test_delete('delete', task_state=task_states.RESIZE_FINISH)

    def test_delete_in_resized(self):
        self._test_delete('delete', vm_state=vm_states.RESIZED)

    def test_delete_with_down_host(self):
        self._test_delete('delete', host='down-host')

    def test_delete_soft(self):
        self._test_delete('soft_delete')

    def test_delete_forced(self):
        self._test_delete('force_delete', vm_state=vm_states.SOFT_DELETED)

    def test_delete_fast_if_host_not_set(self):
        inst = self._create_instance_obj()
        inst.host = ''
        db_inst = obj_base.obj_to_primitive(inst)
        updates = {'progress': 0, 'task_state': task_states.DELETING}
        new_inst = dict(db_inst, **updates)

        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(db,
                                 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'constraint')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(self.compute_api, '_create_reservations')

        db.block_device_mapping_get_all_by_instance(self.context,
                                                    inst.uuid).AndReturn([])
        db.instance_update_and_get_original(
            self.context, inst.uuid, updates).AndReturn((db_inst, new_inst))
        self.compute_api._create_reservations(self.context,
                                              db_inst, new_inst,
                                              inst.project_id,
                                              inst.user_id).AndReturn(None)
        db.constraint(host=mox.IgnoreArg()).AndReturn('constraint')
        db.instance_destroy(self.context, inst.uuid, 'constraint')

        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api, '_cast_to_cells')
            self.compute_api._cast_to_cells(
                self.context, db_inst, 'delete')

        self.mox.ReplayAll()

        self.compute_api.delete(self.context, db_inst)

    def test_delete_disabled(self):
        inst = self._create_instance_obj()
        inst.disable_terminate = True
        db_inst = obj_base.obj_to_primitive(inst)
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.ReplayAll()
        self.compute_api.delete(self.context, db_inst)

    def test_delete_soft_rollback(self):
        inst = self._create_instance_obj()
        db_inst = obj_base.obj_to_primitive(inst)
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(db,
                                 'instance_update_and_get_original')

        delete_time = datetime.datetime(1955, 11, 5)
        timeutils.set_time_override(delete_time)

        db.block_device_mapping_get_all_by_instance(
            self.context, inst.uuid).AndReturn([])
        db.instance_update_and_get_original(
            self.context, inst.uuid,
            {'progress': 0,
             'deleted_at': delete_time,
             'task_state': task_states.SOFT_DELETING,
             }).AndRaise(Exception)

        self.mox.ReplayAll()

        self.assertRaises(Exception,
                          self.compute_api.soft_delete, self.context, db_inst)

    def test_is_volume_backed_being_true_if_root_is_block_device(self):
        bdms = [{'device_name': '/dev/xvda1', 'volume_id': 'volume_id',
            'snapshot_id': 'snapshot_id'}]
        params = {'image_ref': 'some-image-ref', 'root_device_name':
                '/dev/xvda1'}
        instance = self._create_instance_obj(params=params)
        self.assertTrue(self.compute_api.is_volume_backed_instance(
                                                        self.context,
                                                        instance, bdms))

    def test_is_volume_backed_being_false_if_root_is_not_block_device(self):
        bdms = [{'device_name': '/dev/xvda1', 'volume_id': 'volume_id',
            'snapshot_id': 'snapshot_id'}]
        params = {'image_ref': 'some-image-ref', 'root_device_name':
                '/dev/xvdd1'}
        instance = self._create_instance_obj(params=params)
        self.assertFalse(self.compute_api.is_volume_backed_instance(
                                                        self.context,
                                                        instance, bdms))

    def test_is_volume_backed_being_false_if_root_device_is_not_set(self):
        bdms = [{'device_name': None}]
        params = {'image_ref': 'some-image-ref', 'root_device_name': None}
        instance = self._create_instance_obj(params=params)
        self.assertFalse(self.compute_api.is_volume_backed_instance(
                                                        self.context,
                                                        instance, bdms))

    def test_resize(self):
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'migrate_server')

        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api.db, 'migration_create')
            self.compute_api.db.migration_create(mox.IgnoreArg(),
                                                 mox.IgnoreArg())

        inst = self._create_instance_obj()
        self.compute_api.update(self.context, inst, expected_task_state=None,
                                progress=0,
                                task_state='resize_prep').AndReturn(inst)
        self.compute_api._record_action_start(self.context, inst, 'resize')

        filter_properties = {'ignore_hosts': ['fake_host', 'fake_host']}
        scheduler_hint = {'filter_properties': filter_properties}
        flavor = flavors.extract_flavor(inst)
        self.compute_api.compute_task_api.migrate_server(
                self.context, inst, scheduler_hint=scheduler_hint,
                live=False, rebuild=False, flavor=flavor,
                block_migration=None, disk_over_commit=None,
                reservations=None)

        self.mox.ReplayAll()
        self.compute_api.resize(self.context, inst)


class ComputeAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIUnitTestCase, self).setUp()
        self.compute_api = compute_api.API()
        self.is_cells = False


class ComputeCellsAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeCellsAPIUnitTestCase, self).setUp()
        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.is_cells = True
