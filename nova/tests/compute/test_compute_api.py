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
import iso8601
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
from nova.objects import instance_info_cache
from nova.objects import migration as migration_obj
from nova.objects import service as service_obj
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import quota
from nova import test
from nova.tests.image import fake as fake_image
from nova.tests.objects import test_migration
from nova.tests.objects import test_service


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
            sys_meta = params.pop("system_metadata", {})
            for key in flavors.system_metadata_flavor_props:
                sys_meta['instance_type_%s' % key] = flavor[key]
            return sys_meta

        now = timeutils.utcnow()

        instance = instance_obj.Instance()
        instance.metadata = {}
        instance.metadata.update(params.pop('metadata', {}))
        instance.system_metadata = make_fake_sys_meta()
        instance.system_metadata.update(params.pop('system_metadata', {}))
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
        instance.instance_type_id = flavor['id']
        instance.ami_launch_index = 0
        instance.memory_mb = 0
        instance.vcpus = 0
        instance.root_gb = 0
        instance.ephemeral_gb = 0
        instance.architecture = 'x86_64'
        instance.os_type = 'Linux'
        instance.locked = False
        instance.created_at = now
        instance.updated_at = now
        instance.launched_at = now
        instance.disable_terminate = False
        instance.info_cache = instance_info_cache.InstanceInfoCache()

        if params:
            instance.update(params)
        instance.obj_reset_changes()
        return instance

    def test_create_quota_exceeded_messages(self):
        image_href = "image_href"
        image_id = 0
        instance_type = self._create_flavor()

        self.mox.StubOutWithMock(self.compute_api, "_get_image")
        self.mox.StubOutWithMock(quota.QUOTAS, "limit_check")
        self.mox.StubOutWithMock(quota.QUOTAS, "reserve")

        quota_exception = exception.OverQuota(
            quotas={'instances': 1, 'cores': 1, 'ram': 1},
            usages=dict((r, {'in_use': 1, 'reserved': 1}) for r in
                        ['instances', 'cores', 'ram']),
            overs=['instances'])

        for _unused in range(2):
            self.compute_api._get_image(self.context, image_href).AndReturn(
                (image_id, {}))
            quota.QUOTAS.limit_check(self.context, metadata_items=mox.IsA(int))
            quota.QUOTAS.reserve(self.context, instances=40,
                                 cores=mox.IsA(int),
                                 ram=mox.IsA(int)).AndRaise(quota_exception)

        self.mox.ReplayAll()

        for min_count, message in [(20, '20-40'), (40, '40')]:
            try:
                self.compute_api.create(self.context, instance_type,
                                        "image_href", min_count=min_count,
                                        max_count=40)
            except exception.TooManyInstances as e:
                self.assertEqual(message, e.kwargs['req'])
            else:
                self.fail("Exception not raised")

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

    def _test_stop(self, vm_state, force=False):
        # Make sure 'progress' gets reset
        params = dict(task_state=None, progress=99, vm_state=vm_state)
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

        if force:
            self.compute_api.force_stop(self.context, instance)
        else:
            self.compute_api.stop(self.context, instance)
        self.assertEqual(task_states.POWERING_OFF,
                         instance.task_state)
        self.assertEqual(0, instance.progress)

    def test_stop(self):
        self._test_stop(vm_states.ACTIVE)

    def test_stop_stopped_instance_with_bypass(self):
        self._test_stop(vm_states.STOPPED, force=True)

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
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(inst, 'save')
        inst.save(expected_task_state=[None, task_states.REBOOTING])
        self.context.elevated().AndReturn(self.context)
        self.compute_api._record_action_start(self.context, inst,
                                              instance_actions.REBOOT)

        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi

        self.mox.StubOutWithMock(rpcapi, 'reboot_instance')
        rpcapi.reboot_instance(self.context, instance=inst,
                               block_device_info=None,
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

    def _test_delete_resized_part(self, inst):
        migration = migration_obj.Migration._from_db_object(
                self.context, migration_obj.Migration(),
                test_migration.fake_db_migration())

        self.mox.StubOutWithMock(migration_obj.Migration,
                                 'get_by_instance_and_status')

        self.context.elevated().AndReturn(self.context)
        migration_obj.Migration.get_by_instance_and_status(
            self.context, inst.uuid, 'finished').AndReturn(migration)
        self.compute_api._downsize_quota_delta(self.context, inst
                                               ).AndReturn('deltas')
        self.compute_api._reserve_quota_delta(self.context, 'deltas'
                                              ).AndReturn('rsvs')
        self.compute_api._record_action_start(
            self.context, inst, instance_actions.CONFIRM_RESIZE)
        self.compute_api.compute_rpcapi.confirm_resize(
            self.context, inst, migration,
            migration['source_compute'], 'rsvs', cast=False)

    def _test_downed_host_part(self, inst, updates, delete_time, delete_type):
        inst.info_cache.delete()
        compute_utils.notify_about_instance_usage(
                mox.IgnoreArg(), self.context, inst,
                '%s.start' % delete_type)
        self.context.elevated().AndReturn(self.context)
        self.compute_api.network_api.deallocate_for_instance(
                self.context, inst)
        db.instance_system_metadata_get(self.context,
                                        inst.uuid).AndReturn('sys-meta')
        state = ('soft' in delete_type and vm_states.SOFT_DELETED or
                vm_states.DELETED)
        updates.update({'vm_state': state,
                        'task_state': None,
                        'terminated_at': delete_time})
        inst.save()

        db.instance_destroy(self.context, inst.uuid, constraint=None)
        compute_utils.notify_about_instance_usage(
                mox.IgnoreArg(),
                self.context, inst, '%s.end' % delete_type,
                system_metadata='sys-meta')

    def _test_delete(self, delete_type, **attrs):
        reservations = 'fake-resv'
        inst = self._create_instance_obj()
        inst.update(attrs)
        inst._context = self.context
        delete_time = datetime.datetime(1955, 11, 5, 9, 30,
                                        tzinfo=iso8601.iso8601.Utc())
        timeutils.set_time_override(delete_time)
        task_state = (delete_type == 'soft_delete' and
                      task_states.SOFT_DELETING or task_states.DELETING)
        updates = {'progress': 0, 'task_state': task_state}
        if delete_type == 'soft_delete':
            updates['deleted_at'] = delete_time
        self.mox.StubOutWithMock(inst, 'save')
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
        self.mox.StubOutWithMock(inst.info_cache, 'delete')
        self.mox.StubOutWithMock(self.compute_api.network_api,
                                 'deallocate_for_instance')
        self.mox.StubOutWithMock(db, 'instance_system_metadata_get')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'confirm_resize')
        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'terminate_instance')
        self.mox.StubOutWithMock(rpcapi, 'soft_delete_instance')

        db.block_device_mapping_get_all_by_instance(
            self.context, inst.uuid).AndReturn([])
        inst.save()
        self.compute_api._create_reservations(
            self.context, inst, inst.instance_type_id, inst.project_id,
            inst.user_id).AndReturn(reservations)

        # NOTE(comstud): This is getting messy.  But what we are wanting
        # to test is:
        # If cells is enabled and we're the API cell:
        #   * Cast to cells_rpcapi.<method> with reservations=None
        #   * Commit reservations
        # Otherwise:
        #   * Check for downed host
        #   * If downed host:
        #     * Clean up instance, destroying it, sending notifications.
        #       (Tested in _test_downed_host_part())
        #     * Commit reservations
        #   * If not downed host:
        #     * Record the action start.
        #     * Cast to compute_rpcapi.<method> with the reservations

        cast = True
        commit_quotas = True
        if not self.is_cells:
            if inst.vm_state == vm_states.RESIZED:
                self._test_delete_resized_part(inst)

            self.context.elevated().AndReturn(self.context)
            db.service_get_by_compute_host(
                    self.context, inst.host).AndReturn(
                            test_service.fake_service)
            self.compute_api.servicegroup_api.service_is_up(
                    mox.IsA(service_obj.Service)).AndReturn(
                            inst.host != 'down-host')

            if inst.host == 'down-host':
                self._test_downed_host_part(inst, updates, delete_time,
                                            delete_type)
                cast = False
            else:
                # Happens on the manager side
                commit_quotas = False

        if cast:
            if not self.is_cells:
                self.compute_api._record_action_start(self.context, inst,
                                                      instance_actions.DELETE)
            if commit_quotas:
                cast_reservations = None
            else:
                cast_reservations = reservations
            if delete_type == 'soft_delete':
                rpcapi.soft_delete_instance(self.context, inst,
                                            reservations=cast_reservations)
            elif delete_type in ['delete', 'force_delete']:
                rpcapi.terminate_instance(self.context, inst, [],
                                          reservations=cast_reservations)

        if commit_quotas:
            # Local delete or when is_cells is True.
            quota.QUOTAS.commit(self.context, reservations,
                                project_id=inst.project_id,
                                user_id=inst.user_id)

        self.mox.ReplayAll()

        getattr(self.compute_api, delete_type)(self.context, inst)
        for k, v in updates.items():
            self.assertEqual(inst[k], v)

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

    def test_delete_soft_with_down_host(self):
        self._test_delete('soft_delete', host='down-host')

    def test_delete_soft(self):
        self._test_delete('soft_delete')

    def test_delete_forced(self):
        self._test_delete('force_delete', vm_state=vm_states.SOFT_DELETED)

    def test_delete_fast_if_host_not_set(self):
        inst = self._create_instance_obj()
        inst.host = ''
        updates = {'progress': 0, 'task_state': task_states.DELETING}

        self.mox.StubOutWithMock(inst, 'save')
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')

        self.mox.StubOutWithMock(db, 'constraint')
        self.mox.StubOutWithMock(db, 'instance_destroy')
        self.mox.StubOutWithMock(self.compute_api, '_create_reservations')
        self.mox.StubOutWithMock(compute_utils,
                                 'notify_about_instance_usage')
        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'terminate_instance')

        db.block_device_mapping_get_all_by_instance(self.context,
                                                    inst.uuid).AndReturn([])
        inst.save()
        self.compute_api._create_reservations(self.context,
                                              inst, inst.instance_type_id,
                                              inst.project_id, inst.user_id
                                              ).AndReturn(None)

        if self.is_cells:
            rpcapi.terminate_instance(self.context, inst, [],
                                      reservations=None)
        else:
            compute_utils.notify_about_instance_usage(mox.IgnoreArg(),
                                                      self.context,
                                                      inst,
                                                      'delete.start')
            db.constraint(host=mox.IgnoreArg()).AndReturn('constraint')
            db.instance_destroy(self.context, inst.uuid,
                                constraint='constraint')
            compute_utils.notify_about_instance_usage(
                    mox.IgnoreArg(), self.context, inst, 'delete.end',
                    system_metadata=inst.system_metadata)

        self.mox.ReplayAll()

        self.compute_api.delete(self.context, inst)
        for k, v in updates.items():
            self.assertEqual(inst[k], v)

    def test_delete_disabled(self):
        inst = self._create_instance_obj()
        inst.disable_terminate = True
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.ReplayAll()
        self.compute_api.delete(self.context, inst)

    def test_delete_soft_rollback(self):
        inst = self._create_instance_obj()
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(inst, 'save')

        delete_time = datetime.datetime(1955, 11, 5)
        timeutils.set_time_override(delete_time)

        db.block_device_mapping_get_all_by_instance(
            self.context, inst.uuid).AndReturn([])
        inst.save().AndRaise(test.TestingException)

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.compute_api.soft_delete, self.context, inst)

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

    def _test_confirm_resize(self, mig_ref_passed=False):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_mig = migration_obj.Migration._from_db_object(
                self.context, migration_obj.Migration(),
                test_migration.fake_db_migration())

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(migration_obj.Migration,
                                 'get_by_instance_and_status')
        self.mox.StubOutWithMock(self.compute_api, '_downsize_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(fake_mig, 'save')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'confirm_resize')

        self.context.elevated().AndReturn(self.context)
        if not mig_ref_passed:
            migration_obj.Migration.get_by_instance_and_status(
                    self.context, fake_inst['uuid'], 'finished').AndReturn(
                            fake_mig)
        self.compute_api._downsize_quota_delta(self.context,
                                               fake_inst).AndReturn('deltas')

        resvs = ['resvs']

        self.compute_api._reserve_quota_delta(self.context,
                                              'deltas').AndReturn(resvs)

        def _check_mig(expected_task_state=None):
            self.assertEqual('confirming', fake_mig.status)

        fake_mig.save().WithSideEffects(_check_mig)

        if self.is_cells:
            quota.QUOTAS.commit(self.context, resvs)
            resvs = []

        self.compute_api._record_action_start(self.context, fake_inst,
                                              'confirmResize')

        self.compute_api.compute_rpcapi.confirm_resize(
                self.context, fake_inst, fake_mig, 'compute-source', resvs)

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

    def _test_revert_resize(self):
        params = dict(vm_state=vm_states.RESIZED)
        fake_inst = self._create_instance_obj(params=params)
        fake_mig = migration_obj.Migration._from_db_object(
                self.context, migration_obj.Migration(),
                test_migration.fake_db_migration())

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(migration_obj.Migration,
                                 'get_by_instance_and_status')
        self.mox.StubOutWithMock(self.compute_api,
                                 '_reverse_upsize_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(fake_inst, 'save')
        self.mox.StubOutWithMock(fake_mig, 'save')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'revert_resize')

        self.context.elevated().AndReturn(self.context)
        migration_obj.Migration.get_by_instance_and_status(
                self.context, fake_inst['uuid'], 'finished').AndReturn(
                        fake_mig)
        self.compute_api._reverse_upsize_quota_delta(
                self.context, fake_mig).AndReturn('deltas')

        resvs = ['resvs']

        self.compute_api._reserve_quota_delta(self.context,
                                              'deltas').AndReturn(resvs)

        def _check_state(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_REVERTING,
                             fake_inst.task_state)

        fake_inst.save(expected_task_state=None).WithSideEffects(
                _check_state)

        def _check_mig(expected_task_state=None):
            self.assertEqual('reverting', fake_mig.status)

        fake_mig.save().WithSideEffects(_check_mig)

        if self.is_cells:
            quota.QUOTAS.commit(self.context, resvs)
            resvs = []

        self.compute_api._record_action_start(self.context, fake_inst,
                                              'revertResize')

        self.compute_api.compute_rpcapi.revert_resize(
                self.context, fake_inst, fake_mig, 'compute-dest', resvs)

        self.mox.ReplayAll()

        self.compute_api.revert_resize(self.context, fake_inst)

    def test_revert_resize(self):
        self._test_revert_resize()

    def _test_resize(self, flavor_id_passed=True,
                     same_host=False, allow_same_host=False,
                     allow_mig_same_host=False,
                     project_id=None,
                     extra_kwargs=None):
        if extra_kwargs is None:
            extra_kwargs = {}

        self.flags(allow_resize_to_same_host=allow_same_host,
                   allow_migrate_to_same_host=allow_mig_same_host)

        params = {}
        if project_id is not None:
            # To test instance w/ different project id than context (admin)
            params['project_id'] = project_id
        fake_inst = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        self.mox.StubOutWithMock(self.compute_api, '_upsize_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(fake_inst, 'save')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        current_flavor = flavors.extract_flavor(fake_inst)
        if flavor_id_passed:
            new_flavor = dict(id=200, flavorid='new-flavor-id',
                              name='new_flavor', disabled=False)
            flavors.get_flavor_by_flavor_id(
                    'new-flavor-id',
                    read_deleted='no').AndReturn(new_flavor)
        else:
            new_flavor = current_flavor

        resvs = ['resvs']

        self.compute_api._upsize_quota_delta(
                self.context, new_flavor,
                current_flavor).AndReturn('deltas')
        self.compute_api._reserve_quota_delta(self.context, 'deltas',
                project_id=fake_inst['project_id']).AndReturn(resvs)

        def _check_state(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_PREP, fake_inst.task_state)
            self.assertEqual(fake_inst.progress, 0)
            for key, value in extra_kwargs.items():
                self.assertEqual(value, getattr(fake_inst, key))

        fake_inst.save(expected_task_state=None).WithSideEffects(
                _check_state)

        if allow_same_host:
            filter_properties = {'ignore_hosts': []}
        else:
            filter_properties = {'ignore_hosts': [fake_inst['host']]}

        if not flavor_id_passed and not allow_mig_same_host:
            filter_properties['ignore_hosts'].append(fake_inst['host'])

        if self.is_cells:
            quota.QUOTAS.commit(self.context, resvs,
                                project_id=fake_inst['project_id'])
            resvs = []
            mig = migration_obj.Migration()

            def _get_migration():
                return mig

            def _check_mig(ctxt):
                self.assertEqual(fake_inst.uuid, mig.instance_uuid)
                self.assertEqual(current_flavor['id'],
                                 mig.old_instance_type_id)
                self.assertEqual(new_flavor['id'],
                                 mig.new_instance_type_id)
                self.assertEqual('finished', mig.status)

            self.stubs.Set(migration_obj, 'Migration', _get_migration)
            self.mox.StubOutWithMock(self.context, 'elevated')
            self.mox.StubOutWithMock(mig, 'create')

            self.context.elevated().AndReturn(self.context)
            mig.create(self.context).WithSideEffects(_check_mig)

        self.compute_api._record_action_start(self.context, fake_inst,
                                              'resize')

        scheduler_hint = {'filter_properties': filter_properties}

        self.compute_api.compute_task_api.resize_instance(
                self.context, fake_inst, extra_kwargs,
                scheduler_hint=scheduler_hint,
                flavor=new_flavor, reservations=resvs)

        self.mox.ReplayAll()

        if flavor_id_passed:
            self.compute_api.resize(self.context, fake_inst,
                                    flavor_id='new-flavor-id',
                                    **extra_kwargs)
        else:
            self.compute_api.resize(self.context, fake_inst, **extra_kwargs)

    def _test_migrate(self, *args, **kwargs):
        self._test_resize(*args, flavor_id_passed=True, **kwargs)

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

    def test_resize_invalid_flavor_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        # Should never reach these.
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = obj_base.obj_to_primitive(self._create_instance_obj())
        exc = exception.FlavorNotFound(flavor_id='flavor-id')

        flavors.get_flavor_by_flavor_id('flavor-id',
                                        read_deleted='no').AndRaise(exc)

        self.mox.ReplayAll()

        self.assertRaises(exception.FlavorNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')

    def test_resize_disabled_flavor_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        # Should never reach these.
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = obj_base.obj_to_primitive(self._create_instance_obj())
        fake_flavor = dict(id=200, flavorid='flavor-id', name='foo',
                           disabled=True)

        flavors.get_flavor_by_flavor_id(
                'flavor-id', read_deleted='no').AndReturn(fake_flavor)

        self.mox.ReplayAll()

        self.assertRaises(exception.FlavorNotFound,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')

    def test_resize_same_flavor_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        # Should never reach these.
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = obj_base.obj_to_primitive(self._create_instance_obj())
        fake_flavor = flavors.extract_flavor(fake_inst)

        flavors.get_flavor_by_flavor_id(
                fake_flavor['flavorid'],
                read_deleted='no').AndReturn(fake_flavor)

        self.mox.ReplayAll()

        # Pass in flavor_id.. same as current flavor.
        self.assertRaises(exception.CannotResizeToSameFlavor,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id=fake_flavor['flavorid'])

    def test_resize_quota_exceeds_fails(self):
        self.mox.StubOutWithMock(flavors, 'get_flavor_by_flavor_id')
        self.mox.StubOutWithMock(self.compute_api, '_upsize_quota_delta')
        self.mox.StubOutWithMock(self.compute_api, '_reserve_quota_delta')
        # Should never reach these.
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api.compute_task_api,
                                 'resize_instance')

        fake_inst = obj_base.obj_to_primitive(self._create_instance_obj())
        current_flavor = flavors.extract_flavor(fake_inst)
        fake_flavor = dict(id=200, flavorid='flavor-id', name='foo',
                           disabled=False)
        flavors.get_flavor_by_flavor_id(
                'flavor-id', read_deleted='no').AndReturn(fake_flavor)
        deltas = dict(resource=0)
        self.compute_api._upsize_quota_delta(
                self.context, fake_flavor,
                current_flavor).AndReturn(deltas)
        usage = dict(in_use=0, reserved=0)
        over_quota_args = dict(quotas={'resource': 0},
                               usages={'resource': usage},
                               overs=['resource'])
        self.compute_api._reserve_quota_delta(self.context, deltas,
                project_id=fake_inst['project_id']).AndRaise(
                        exception.OverQuota(**over_quota_args))

        self.mox.ReplayAll()

        self.assertRaises(exception.TooManyInstances,
                          self.compute_api.resize, self.context,
                          fake_inst, flavor_id='flavor-id')

    def test_pause(self):
        # Ensure instance can be paused.
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
        self.mox.StubOutWithMock(rpcapi, 'pause_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.PAUSE)
        rpcapi.pause_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.pause(self.context, instance)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertEqual(task_states.PAUSING,
                         instance.task_state)

    def test_unpause(self):
        # Ensure instance can be unpaused.
        params = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=params)
        self.assertEqual(instance.vm_state, vm_states.PAUSED)
        self.assertEqual(instance.task_state, None)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        if self.is_cells:
            rpcapi = self.compute_api.cells_rpcapi
        else:
            rpcapi = self.compute_api.compute_rpcapi
        self.mox.StubOutWithMock(rpcapi, 'unpause_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.UNPAUSE)
        rpcapi.unpause_instance(self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.unpause(self.context, instance)
        self.assertEqual(vm_states.PAUSED, instance.vm_state)
        self.assertEqual(task_states.UNPAUSING, instance.task_state)

    def test_swap_volume_volume_api_usage(self):
        # This test ensures that volume_id arguments are passed to volume_api
        # and that volumes return to previous states in case of error.
        def fake_vol_api_begin_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            volumes[volume_id]['status'] = 'detaching'

        def fake_vol_api_roll_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'detaching':
                volumes[volume_id]['status'] = 'in-use'

        def fake_vol_api_reserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            self.assertEqual(volumes[volume_id]['status'], 'available')
            volumes[volume_id]['status'] = 'attaching'

        def fake_vol_api_unreserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'attaching':
                volumes[volume_id]['status'] = 'available'

        def fake_swap_volume_exc(context, instance, old_volume_id,
                                 new_volume_id):
            raise AttributeError  # Random exception

        # Should fail if VM state is not valid
        instance = {'vm_state': vm_states.BUILDING,
                    'launched_at': timeutils.utcnow(),
                    'locked': False,
                    'availability_zone': 'fake_az',
                    'uuid': 'fake'}
        volumes = {}
        old_volume_id = uuidutils.generate_uuid()
        volumes[old_volume_id] = {'id': old_volume_id,
                                  'display_name': 'old_volume',
                                  'attach_status': 'attached',
                                  'instance_uuid': 'fake',
                                  'size': 5,
                                  'status': 'in-use'}
        new_volume_id = uuidutils.generate_uuid()
        volumes[new_volume_id] = {'id': new_volume_id,
                                  'display_name': 'new_volume',
                                  'attach_status': 'detached',
                                  'instance_uuid': None,
                                  'size': 5,
                                  'status': 'available'}
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        instance['vm_state'] = vm_states.ACTIVE

        # Should fail if old volume is not attached
        volumes[old_volume_id]['attach_status'] = 'detached'
        self.assertRaises(exception.VolumeUnattached,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        self.assertEquals(volumes[old_volume_id]['status'], 'in-use')
        self.assertEquals(volumes[new_volume_id]['status'], 'available')
        volumes[old_volume_id]['attach_status'] = 'attached'

        # Should fail if old volume's instance_uuid is not that of the instance
        volumes[old_volume_id]['instance_uuid'] = 'fake2'
        self.assertRaises(exception.InvalidVolume,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        self.assertEquals(volumes[old_volume_id]['status'], 'in-use')
        self.assertEquals(volumes[new_volume_id]['status'], 'available')
        volumes[old_volume_id]['instance_uuid'] = 'fake'

        # Should fail if new volume is attached
        volumes[new_volume_id]['attach_status'] = 'attached'
        self.assertRaises(exception.InvalidVolume,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        self.assertEquals(volumes[old_volume_id]['status'], 'in-use')
        self.assertEquals(volumes[new_volume_id]['status'], 'available')
        volumes[new_volume_id]['attach_status'] = 'detached'

        # Should fail if new volume is smaller than the old volume
        volumes[new_volume_id]['size'] = 4
        self.assertRaises(exception.InvalidVolume,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        self.assertEquals(volumes[old_volume_id]['status'], 'in-use')
        self.assertEquals(volumes[new_volume_id]['status'], 'available')
        volumes[new_volume_id]['size'] = 5

        # Fail call to swap_volume
        self.stubs.Set(self.compute_api.volume_api, 'begin_detaching',
                       fake_vol_api_begin_detaching)
        self.stubs.Set(self.compute_api.volume_api, 'roll_detaching',
                       fake_vol_api_roll_detaching)
        self.stubs.Set(self.compute_api.volume_api, 'reserve_volume',
                       fake_vol_api_reserve)
        self.stubs.Set(self.compute_api.volume_api, 'unreserve_volume',
                       fake_vol_api_unreserve)
        self.stubs.Set(self.compute_api.compute_rpcapi, 'swap_volume',
                       fake_swap_volume_exc)
        self.assertRaises(AttributeError,
                          self.compute_api.swap_volume, self.context, instance,
                          volumes[old_volume_id], volumes[new_volume_id])
        self.assertEquals(volumes[old_volume_id]['status'], 'in-use')
        self.assertEquals(volumes[new_volume_id]['status'], 'available')

        # Should succeed
        self.stubs.Set(self.compute_api.compute_rpcapi, 'swap_volume',
                       lambda c, instance, old_volume_id, new_volume_id: True)
        self.compute_api.swap_volume(self.context, instance,
                                     volumes[old_volume_id],
                                     volumes[new_volume_id])

    def _test_snapshot_and_backup(self, is_snapshot=True,
                                  with_base_ref=False, min_ram=None,
                                  min_disk=None,
                                  create_fails=False):
        # 'cache_in_nova' is for testing non-inheritable properties
        # 'user_id' should also not be carried from sys_meta into
        # image property...since it should be set explicitly by
        # _create_image() in compute api.
        fake_sys_meta = dict(image_foo='bar', blah='bug?',
                             image_cache_in_nova='dropped',
                             cache_in_nova='dropped',
                             user_id='meow')
        if with_base_ref:
            fake_sys_meta['image_base_image_ref'] = 'fake-base-ref'
        params = dict(system_metadata=fake_sys_meta)
        instance = self._create_instance_obj(params=params)
        fake_sys_meta.update(instance.system_metadata)
        extra_props = dict(cow='moo', cat='meow')

        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(self.compute_api.image_service,
                                 'create')
        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'snapshot_instance')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'backup_instance')

        image_type = is_snapshot and 'snapshot' or 'backup'

        expected_sys_meta = dict(fake_sys_meta)
        expected_sys_meta.pop('cache_in_nova')
        expected_sys_meta.pop('image_cache_in_nova')
        expected_sys_meta.pop('user_id')
        expected_sys_meta['foo'] = expected_sys_meta.pop('image_foo')
        if with_base_ref:
            expected_sys_meta['base_image_ref'] = expected_sys_meta.pop(
                    'image_base_image_ref')

        expected_props = {'instance_uuid': instance.uuid,
                          'user_id': self.context.user_id,
                          'image_type': image_type}
        expected_props.update(extra_props)
        expected_props.update(expected_sys_meta)
        expected_meta = {'name': 'fake-name',
                         'is_public': False,
                         'properties': expected_props}
        if is_snapshot:
            if min_ram is not None:
                expected_meta['min_ram'] = min_ram
            if min_disk is not None:
                expected_meta['min_disk'] = min_disk
        else:
            expected_props['backup_type'] = 'fake-backup-type'

        compute_utils.get_image_metadata(
            self.context, self.compute_api.image_service,
            FAKE_IMAGE_REF, instance).AndReturn(expected_meta)

        fake_image = dict(id='fake-image-id')
        mock_method = self.compute_api.image_service.create(
                self.context, expected_meta)
        if create_fails:
            mock_method.AndRaise(test.TestingException())
        else:
            mock_method.AndReturn(fake_image)

        def check_state(expected_task_state=None):
            expected_state = (is_snapshot and task_states.IMAGE_SNAPSHOT or
                              task_states.IMAGE_BACKUP)
            self.assertEqual(expected_state, instance.task_state)

        if not create_fails:
            instance.save(expected_task_state=None).WithSideEffects(
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
            else:
                res = self.compute_api.backup(self.context, instance,
                                        'fake-name',
                                        'fake-backup-type',
                                        'fake-rotation',
                                        extra_properties=extra_props)
            self.assertEqual(fake_image, res)
        except test.TestingException:
            got_exc = True
        self.assertEqual(create_fails, got_exc)

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

    def test_snapshot_with_base_image_ref(self):
        self._test_snapshot_and_backup(with_base_ref=True)

    def test_snapshot_min_ram(self):
        self._test_snapshot_and_backup(min_ram=42)

    def test_snapshot_min_disk(self):
        self._test_snapshot_and_backup(min_disk=42)

    def test_backup(self):
        self._test_snapshot_and_backup(is_snapshot=False)

    def test_backup_fails(self):
        self._test_snapshot_and_backup(is_snapshot=False, create_fails=True)

    def test_backup_invalid_state(self):
        instance = self._create_instance_obj()
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
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
                          self.compute_api.snapshot,
                          self.context, instance, 'fake-name',
                          'fake', 'fake')

    def test_backup_with_base_image_ref(self):
        self._test_snapshot_and_backup(is_snapshot=False,
                                       with_base_ref=True)

    def test_volume_snapshot_create(self):
        volume_id = '1'
        create_info = {'id': 'eyedee'}
        fake_bdm = {
            'instance': {
                'uuid': 'fake_uuid',
                'vm_state': vm_states.ACTIVE,
            },
        }

        def fake_get_bdm(context, _volume_id, columns_to_join):
            self.assertEqual(volume_id, _volume_id)
            return fake_bdm

        self.stubs.Set(self.compute_api.db,
                'block_device_mapping_get_by_volume_id', fake_get_bdm)
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                'volume_snapshot_create')

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

    def test_volume_snapshot_delete(self):
        volume_id = '1'
        snapshot_id = '2'
        fake_bdm = {
            'instance': {
                'uuid': 'fake_uuid',
                'vm_state': vm_states.ACTIVE,
            },
        }

        def fake_get_bdm(context, _volume_id, columns_to_join):
            self.assertEqual(volume_id, _volume_id)
            return fake_bdm

        self.stubs.Set(self.compute_api.db,
                'block_device_mapping_get_by_volume_id', fake_get_bdm)
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                'volume_snapshot_delete')

        self.compute_api.compute_rpcapi.volume_snapshot_delete(self.context,
                fake_bdm['instance'], volume_id, snapshot_id, {})

        self.mox.ReplayAll()

        self.compute_api.volume_snapshot_delete(self.context, volume_id,
                snapshot_id, {})

    def _create_instance_with_disabled_disk_config(self):
        sys_meta = {"image_auto_disk_config": "Disabled"}
        params = {"system_metadata": sys_meta}
        return obj_base.obj_to_primitive(self._create_instance_obj(
                                                            params=params))

    def _setup_fake_image_with_disabled_disk_config(self):
        self.fake_image = {
            'id': 1,
            'name': 'fake_name',
            'status': 'active',
            'properties': {"auto_disk_config": "Disabled"},
        }

        def fake_show(obj, context, image_id):
            return self.fake_image
        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        return self.fake_image['id']

    def test_resize_with_disabled_auto_disk_config_fails(self):
        fake_inst = self._create_instance_with_disabled_disk_config()

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
        fake_inst = self._create_instance_with_disabled_disk_config()
        image_id = self._setup_fake_image_with_disabled_disk_config()
        self.assertRaises(exception.AutoDiskConfigDisabledByImage,
                          self.compute_api.rebuild,
                          self.context,
                          fake_inst,
                          image_id,
                          "new password",
                          auto_disk_config=True)


class ComputeAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIUnitTestCase, self).setUp()
        self.compute_api = compute_api.API()
        self.is_cells = False


class ComputeCellsAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeCellsAPIUnitTestCase, self).setUp()
        self.flags(cell_type='api', enable=True, group='cells')
        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.is_cells = True
