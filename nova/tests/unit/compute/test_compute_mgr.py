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

"""Unit tests for ComputeManager()."""

import contextlib
import time
import uuid

from cinderclient import exceptions as cinder_exception
from eventlet import event as eventlet_event
import mock
import mox
from oslo.config import cfg
from oslo import messaging
from oslo.utils import importutils
from oslo.utils import timeutils

from nova.compute import build_results
from nova.compute import manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import db
from nova import exception
from nova.network import api as network_api
from nova.network import model as network_model
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit.compute import fake_resource_tracker
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.objects import test_instance_info_cache
from nova import utils
from nova.virt import event as virtevent
from nova.virt import hardware


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')


class ComputeManagerUnitTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerUnitTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')

    @mock.patch.object(manager.ComputeManager, '_sync_instance_power_state')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_handle_lifecycle_event(self, mock_get, mock_sync):
        event_map = {virtevent.EVENT_LIFECYCLE_STOPPED: power_state.SHUTDOWN,
                     virtevent.EVENT_LIFECYCLE_STARTED: power_state.RUNNING,
                     virtevent.EVENT_LIFECYCLE_PAUSED: power_state.PAUSED,
                     virtevent.EVENT_LIFECYCLE_RESUMED: power_state.RUNNING}
        event = mock.Mock()
        event.get_instance_uuid.return_value = mock.sentinel.uuid
        for transition, pwr_state in event_map.iteritems():
            event.get_transition.return_value = transition
            self.compute.handle_lifecycle_event(event)
            mock_get.assert_called_with(mock.ANY, mock.sentinel.uuid,
                                        expected_attrs=[])
            mock_sync.assert_called_with(mock.ANY, mock_get.return_value,
                                         pwr_state)

    def test_allocate_network_succeeds_after_retries(self):
        self.flags(network_allocate_retries=8)

        nwapi = self.compute.network_api
        self.mox.StubOutWithMock(nwapi, 'allocate_for_instance')
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(time, 'sleep')

        instance = fake_instance.fake_instance_obj(
                       self.context, expected_attrs=['system_metadata'])

        is_vpn = 'fake-is-vpn'
        req_networks = 'fake-req-networks'
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        final_result = 'meow'
        dhcp_options = None

        expected_sleep_times = [1, 2, 4, 8, 16, 30, 30, 30]

        for sleep_time in expected_sleep_times:
            nwapi.allocate_for_instance(
                    self.context, instance, vpn=is_vpn,
                    requested_networks=req_networks, macs=macs,
                    security_groups=sec_groups,
                    dhcp_options=dhcp_options).AndRaise(
                            test.TestingException())
            time.sleep(sleep_time)

        nwapi.allocate_for_instance(
                self.context, instance, vpn=is_vpn,
                requested_networks=req_networks, macs=macs,
                security_groups=sec_groups,
                dhcp_options=dhcp_options).AndReturn(final_result)
        self.compute._instance_update(self.context, instance['uuid'],
                system_metadata={'network_allocated': 'True'})

        self.mox.ReplayAll()

        res = self.compute._allocate_network_async(self.context, instance,
                                                   req_networks,
                                                   macs,
                                                   sec_groups,
                                                   is_vpn,
                                                   dhcp_options)
        self.assertEqual(final_result, res)

    def test_allocate_network_maintains_context(self):
        # override tracker with a version that doesn't need the database:
        class FakeResourceTracker(object):
            def instance_claim(self, context, instance, limits):
                return mox.MockAnything()

        self.mox.StubOutWithMock(self.compute, '_get_resource_tracker')
        self.mox.StubOutWithMock(self.compute, '_allocate_network')
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')

        instance = fake_instance.fake_instance_obj(self.context)

        objects.BlockDeviceMappingList.get_by_instance_uuid(
                mox.IgnoreArg(), instance.uuid).AndReturn([])

        node = 'fake_node'
        self.compute._get_resource_tracker(node).AndReturn(
            FakeResourceTracker())

        self.admin_context = False

        def fake_allocate(context, *args, **kwargs):
            if context.is_admin:
                self.admin_context = True

        # NOTE(vish): The nice mox parameter matchers here don't work well
        #             because they raise an exception that gets wrapped by
        #             the retry exception handling, so use a side effect
        #             to keep track of whether allocate was called with admin
        #             context.
        self.compute._allocate_network(mox.IgnoreArg(), instance,
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).WithSideEffects(fake_allocate)

        self.mox.ReplayAll()

        instance, nw_info = self.compute._build_instance(self.context, {}, {},
                                     None, None, None, True,
                                     node, instance,
                                     {}, False)
        self.assertFalse(self.admin_context,
                         "_allocate_network called with admin context")
        self.assertEqual(vm_states.BUILDING, instance.vm_state)
        self.assertEqual(task_states.BLOCK_DEVICE_MAPPING, instance.task_state)

    def test_reschedule_maintains_context(self):
        # override tracker with a version that causes a reschedule
        class FakeResourceTracker(object):
            def instance_claim(self, context, instance, limits):
                raise test.TestingException()

        self.mox.StubOutWithMock(self.compute, '_get_resource_tracker')
        self.mox.StubOutWithMock(self.compute, '_reschedule_or_error')
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        instance = fake_instance.fake_instance_obj(self.context)

        objects.BlockDeviceMappingList.get_by_instance_uuid(
                mox.IgnoreArg(), instance.uuid).AndReturn([])

        node = 'fake_node'
        self.compute._get_resource_tracker(node).AndReturn(
            FakeResourceTracker())

        self.admin_context = False

        def fake_retry_or_error(context, *args, **kwargs):
            if context.is_admin:
                self.admin_context = True

        # NOTE(vish): we could use a mos parameter matcher here but it leads
        #             to a very cryptic error message, so use the same method
        #             as the allocate_network_maintains_context test.
        self.compute._reschedule_or_error(mox.IgnoreArg(), instance,
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).WithSideEffects(fake_retry_or_error)

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.compute._build_instance, self.context, {}, {},
                          None, None, None, True, node, instance, {}, False)
        self.assertFalse(self.admin_context,
                         "_reschedule_or_error called with admin context")

    def test_allocate_network_fails(self):
        self.flags(network_allocate_retries=0)

        nwapi = self.compute.network_api
        self.mox.StubOutWithMock(nwapi, 'allocate_for_instance')

        instance = {}
        is_vpn = 'fake-is-vpn'
        req_networks = 'fake-req-networks'
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        dhcp_options = None

        nwapi.allocate_for_instance(
                self.context, instance, vpn=is_vpn,
                requested_networks=req_networks, macs=macs,
                security_groups=sec_groups,
                dhcp_options=dhcp_options).AndRaise(test.TestingException())

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.compute._allocate_network_async,
                          self.context, instance, req_networks, macs,
                          sec_groups, is_vpn, dhcp_options)

    def test_allocate_network_neg_conf_value_treated_as_zero(self):
        self.flags(network_allocate_retries=-1)

        nwapi = self.compute.network_api
        self.mox.StubOutWithMock(nwapi, 'allocate_for_instance')

        instance = {}
        is_vpn = 'fake-is-vpn'
        req_networks = 'fake-req-networks'
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        dhcp_options = None

        # Only attempted once.
        nwapi.allocate_for_instance(
                self.context, instance, vpn=is_vpn,
                requested_networks=req_networks, macs=macs,
                security_groups=sec_groups,
                dhcp_options=dhcp_options).AndRaise(test.TestingException())

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.compute._allocate_network_async,
                          self.context, instance, req_networks, macs,
                          sec_groups, is_vpn, dhcp_options)

    @mock.patch.object(network_api.API, 'allocate_for_instance')
    @mock.patch.object(manager.ComputeManager, '_instance_update')
    @mock.patch.object(time, 'sleep')
    def test_allocate_network_with_conf_value_is_one(
            self, sleep, _instance_update, allocate_for_instance):
        self.flags(network_allocate_retries=1)

        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        is_vpn = 'fake-is-vpn'
        req_networks = 'fake-req-networks'
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        dhcp_options = None
        final_result = 'zhangtralon'

        allocate_for_instance.side_effect = [test.TestingException(),
                                             final_result]
        res = self.compute._allocate_network_async(self.context, instance,
                                                   req_networks,
                                                   macs,
                                                   sec_groups,
                                                   is_vpn,
                                                   dhcp_options)
        self.assertEqual(final_result, res)
        self.assertEqual(1, sleep.call_count)

    def test_init_host(self):
        our_host = self.compute.host
        fake_context = 'fake-context'
        inst = fake_instance.fake_db_instance(
                vm_state=vm_states.ACTIVE,
                info_cache=dict(test_instance_info_cache.fake_info_cache,
                                network_info=None),
                security_groups=None)
        startup_instances = [inst, inst, inst]

        def _do_mock_calls(defer_iptables_apply):
            self.compute.driver.init_host(host=our_host)
            context.get_admin_context().AndReturn(fake_context)
            db.instance_get_all_by_host(
                    fake_context, our_host, columns_to_join=['info_cache'],
                    use_slave=False
                    ).AndReturn(startup_instances)
            if defer_iptables_apply:
                self.compute.driver.filter_defer_apply_on()
            self.compute._destroy_evacuated_instances(fake_context)
            self.compute._init_instance(fake_context,
                                        mox.IsA(objects.Instance))
            self.compute._init_instance(fake_context,
                                        mox.IsA(objects.Instance))
            self.compute._init_instance(fake_context,
                                        mox.IsA(objects.Instance))
            if defer_iptables_apply:
                self.compute.driver.filter_defer_apply_off()

        self.mox.StubOutWithMock(self.compute.driver, 'init_host')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'filter_defer_apply_on')
        self.mox.StubOutWithMock(self.compute.driver,
                'filter_defer_apply_off')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(context, 'get_admin_context')
        self.mox.StubOutWithMock(self.compute,
                '_destroy_evacuated_instances')
        self.mox.StubOutWithMock(self.compute,
                '_init_instance')

        # Test with defer_iptables_apply
        self.flags(defer_iptables_apply=True)
        _do_mock_calls(True)

        self.mox.ReplayAll()
        self.compute.init_host()
        self.mox.VerifyAll()

        # Test without defer_iptables_apply
        self.mox.ResetAll()
        self.flags(defer_iptables_apply=False)
        _do_mock_calls(False)

        self.mox.ReplayAll()
        self.compute.init_host()
        # tearDown() uses context.get_admin_context(), so we have
        # to do the verification here and unstub it.
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    @mock.patch('nova.objects.InstanceList')
    def test_cleanup_host(self, mock_instance_list):
        # just testing whether the cleanup_host method
        # when fired will invoke the underlying driver's
        # equivalent method.

        mock_instance_list.get_by_host.return_value = []

        with mock.patch.object(self.compute, 'driver') as mock_driver:
            self.compute.init_host()
            mock_driver.init_host.assert_called_once_with(host='fake-mini')

            self.compute.cleanup_host()
            mock_driver.cleanup_host.assert_called_once_with(host='fake-mini')

    def test_init_host_with_deleted_migration(self):
        our_host = self.compute.host
        not_our_host = 'not-' + our_host
        fake_context = 'fake-context'

        deleted_instance = fake_instance.fake_instance_obj(
                self.context, host=not_our_host, uuid='fake-uuid')

        self.mox.StubOutWithMock(self.compute.driver, 'init_host')
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(context, 'get_admin_context')
        self.mox.StubOutWithMock(self.compute, 'init_virt_events')
        self.mox.StubOutWithMock(self.compute, '_get_instances_on_driver')
        self.mox.StubOutWithMock(self.compute, '_init_instance')
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')

        self.compute.driver.init_host(host=our_host)
        context.get_admin_context().AndReturn(fake_context)
        db.instance_get_all_by_host(fake_context, our_host,
                                    columns_to_join=['info_cache'],
                                    use_slave=False
                                    ).AndReturn([])
        self.compute.init_virt_events()

        # simulate failed instance
        self.compute._get_instances_on_driver(
            fake_context, {'deleted': False}).AndReturn([deleted_instance])
        self.compute._get_instance_nw_info(fake_context, deleted_instance
            ).AndRaise(exception.InstanceNotFound(
                instance_id=deleted_instance['uuid']))
        # ensure driver.destroy is called so that driver may
        # clean up any dangling files
        self.compute.driver.destroy(fake_context, deleted_instance,
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

        self.mox.ReplayAll()
        self.compute.init_host()
        # tearDown() uses context.get_admin_context(), so we have
        # to do the verification here and unstub it.
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def test_init_instance_with_binding_failed_vif_type(self):
        # this instance will plug a 'binding_failed' vif
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake-uuid',
                info_cache=None,
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=None,
                expected_attrs=['info_cache'])

        with contextlib.nested(
            mock.patch.object(context, 'get_admin_context',
                return_value=self.context),
            mock.patch.object(compute_utils, 'get_nw_info_for_instance',
                return_value=network_model.NetworkInfo()),
            mock.patch.object(self.compute.driver, 'plug_vifs',
                side_effect=exception.VirtualInterfacePlugException(
                    "Unexpected vif_type=binding_failed")),
            mock.patch.object(self.compute, '_set_instance_error_state')
        ) as (get_admin_context, get_nw_info, plug_vifs, set_error_state):
            self.compute._init_instance(self.context, instance)
            set_error_state.assert_called_once_with(self.context, instance)

    def test_init_instance_failed_resume_sets_error(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake-uuid',
                info_cache=None,
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=None,
                expected_attrs=['info_cache'])

        self.flags(resume_guests_state_on_host_boot=True)
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'resume_state_on_host_boot')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_block_device_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_set_instance_error_state')
        self.compute._get_power_state(mox.IgnoreArg(),
                instance).AndReturn(power_state.SHUTDOWN)
        self.compute._get_power_state(mox.IgnoreArg(),
                instance).AndReturn(power_state.SHUTDOWN)
        self.compute._get_power_state(mox.IgnoreArg(),
                instance).AndReturn(power_state.SHUTDOWN)
        self.compute.driver.plug_vifs(instance, mox.IgnoreArg())
        self.compute._get_instance_block_device_info(mox.IgnoreArg(),
                instance).AndReturn('fake-bdm')
        self.compute.driver.resume_state_on_host_boot(mox.IgnoreArg(),
                instance, mox.IgnoreArg(),
                'fake-bdm').AndRaise(test.TestingException)
        self.compute._set_instance_error_state(mox.IgnoreArg(), instance)
        self.mox.ReplayAll()
        self.compute._init_instance('fake-context', instance)

    def test_init_instance_stuck_in_deleting(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake-uuid',
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=task_states.DELETING)

        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(self.compute, '_delete_instance')
        self.mox.StubOutWithMock(instance, 'obj_load_attr')

        bdms = []
        instance.obj_load_attr('metadata')
        instance.obj_load_attr('system_metadata')
        objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, instance.uuid).AndReturn(bdms)
        self.compute._delete_instance(self.context, instance, bdms,
                                      mox.IgnoreArg())

        self.mox.ReplayAll()
        self.compute._init_instance(self.context, instance)

    def _test_init_instance_reverts_crashed_migrations(self,
                                                       old_vm_state=None):
        power_on = True if (not old_vm_state or
                            old_vm_state == vm_states.ACTIVE) else False
        sys_meta = {
            'old_vm_state': old_vm_state
            }
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='foo',
                vm_state=vm_states.ERROR,
                task_state=task_states.RESIZE_MIGRATING,
                power_state=power_state.SHUTDOWN,
                system_metadata=sys_meta,
                expected_attrs=['system_metadata'])

        self.mox.StubOutWithMock(compute_utils, 'get_nw_info_for_instance')
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'finish_revert_migration')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_block_device_info')
        self.mox.StubOutWithMock(self.compute.driver, 'get_info')
        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute, '_retry_reboot')

        self.compute._retry_reboot(self.context, instance).AndReturn(
                                                                (False, None))
        compute_utils.get_nw_info_for_instance(instance).AndReturn(
            network_model.NetworkInfo())
        self.compute.driver.plug_vifs(instance, [])
        self.compute._get_instance_block_device_info(
            self.context, instance).AndReturn([])
        self.compute.driver.finish_revert_migration(self.context, instance,
                                                    [], [], power_on)
        instance.save()
        self.compute.driver.get_info(instance).AndReturn(
            hardware.InstanceInfo(state=power_state.SHUTDOWN))
        self.compute.driver.get_info(instance).AndReturn(
            hardware.InstanceInfo(state=power_state.SHUTDOWN))

        self.mox.ReplayAll()

        self.compute._init_instance(self.context, instance)
        self.assertIsNone(instance.task_state)

    def test_init_instance_reverts_crashed_migration_from_active(self):
        self._test_init_instance_reverts_crashed_migrations(
                                                old_vm_state=vm_states.ACTIVE)

    def test_init_instance_reverts_crashed_migration_from_stopped(self):
        self._test_init_instance_reverts_crashed_migrations(
                                                old_vm_state=vm_states.STOPPED)

    def test_init_instance_reverts_crashed_migration_no_old_state(self):
        self._test_init_instance_reverts_crashed_migrations(old_vm_state=None)

    def test_init_instance_resets_crashed_live_migration(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='foo',
                vm_state=vm_states.ACTIVE,
                task_state=task_states.MIGRATING)
        with contextlib.nested(
            mock.patch.object(instance, 'save'),
            mock.patch('nova.compute.utils.get_nw_info_for_instance',
                       return_value=network_model.NetworkInfo())
        ) as (save, get_nw_info):
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with(expected_task_state=['migrating'])
            get_nw_info.assert_called_once_with(instance)
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)

    def _test_init_instance_sets_building_error(self, vm_state,
                                                task_state=None):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='foo',
                vm_state=vm_state,
                task_state=task_state)
        with mock.patch.object(instance, 'save') as save:
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ERROR, instance.vm_state)

    def test_init_instance_sets_building_error(self):
        self._test_init_instance_sets_building_error(vm_states.BUILDING)

    def test_init_instance_sets_rebuilding_errors(self):
        tasks = [task_states.REBUILDING,
                 task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                 task_states.REBUILD_SPAWNING]
        vms = [vm_states.ACTIVE, vm_states.STOPPED]

        for vm_state in vms:
            for task_state in tasks:
                self._test_init_instance_sets_building_error(
                    vm_state, task_state)

    def _test_init_instance_sets_building_tasks_error(self, instance):
        with mock.patch.object(instance, 'save') as save:
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ERROR, instance.vm_state)

    def test_init_instance_sets_building_tasks_error_scheduling(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='foo',
                vm_state=None,
                task_state=task_states.SCHEDULING)
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_block_device(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.BLOCK_DEVICE_MAPPING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_networking(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.NETWORKING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_spawning(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.SPAWNING
        self._test_init_instance_sets_building_tasks_error(instance)

    def _test_init_instance_cleans_image_states(self, instance):
        with mock.patch.object(instance, 'save') as save:
            self.compute._get_power_state = mock.Mock()
            self.compute.driver.post_interrupted_snapshot_cleanup = mock.Mock()
            instance.info_cache = None
            instance.power_state = power_state.RUNNING
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
            self.compute.driver.post_interrupted_snapshot_cleanup.\
                    assert_called_once_with(self.context, instance)
        self.assertIsNone(instance.task_state)

    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.RUNNING)
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    def _test_init_instance_cleans_task_states(self, powerstate, state,
            mock_get_uuid, mock_get_power_state):
        instance = objects.Instance(self.context)
        instance.uuid = 'fake-uuid'
        instance.info_cache = None
        instance.power_state = power_state.RUNNING
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = state
        mock_get_power_state.return_value = powerstate

        self.compute._init_instance(self.context, instance)

        return instance

    def test_init_instance_cleans_image_state_pending_upload(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_PENDING_UPLOAD
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_uploading(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_UPLOADING
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot_pending(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT_PENDING
        self._test_init_instance_cleans_image_states(instance)

    @mock.patch.object(objects.Instance, 'save')
    def test_init_instance_cleans_running_pausing(self, mock_save):
        instance = self._test_init_instance_cleans_task_states(
            power_state.RUNNING, task_states.PAUSING)
        mock_save.assert_called_once_with()
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertIsNone(instance.task_state)

    @mock.patch.object(objects.Instance, 'save')
    def test_init_instance_cleans_running_unpausing(self, mock_save):
        instance = self._test_init_instance_cleans_task_states(
            power_state.RUNNING, task_states.UNPAUSING)
        mock_save.assert_called_once_with()
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertIsNone(instance.task_state)

    @mock.patch('nova.compute.manager.ComputeManager.unpause_instance')
    def test_init_instance_cleans_paused_unpausing(self, mock_unpause):

        def fake_unpause(context, instance):
            instance.task_state = None

        mock_unpause.side_effect = fake_unpause
        instance = self._test_init_instance_cleans_task_states(
            power_state.PAUSED, task_states.UNPAUSING)
        mock_unpause.assert_called_once_with(self.context, instance)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        self.assertIsNone(instance.task_state)

    def test_init_instance_errors_when_not_migrating(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ERROR
        instance.task_state = task_states.IMAGE_UPLOADING
        self.mox.StubOutWithMock(compute_utils, 'get_nw_info_for_instance')
        self.mox.ReplayAll()
        self.compute._init_instance(self.context, instance)
        self.mox.VerifyAll()

    def test_init_instance_deletes_error_deleting_instance(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake',
                vm_state=vm_states.ERROR,
                task_state=task_states.DELETING)
        self.mox.StubOutWithMock(objects.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(self.compute, '_delete_instance')
        self.mox.StubOutWithMock(instance, 'obj_load_attr')

        bdms = []
        instance.obj_load_attr('metadata')
        instance.obj_load_attr('system_metadata')
        objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, instance.uuid).AndReturn(bdms)
        self.compute._delete_instance(self.context, instance, bdms,
                                      mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute._init_instance(self.context, instance)
        self.mox.VerifyAll()

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.compute.utils.get_nw_info_for_instance')
    @mock.patch(
        'nova.compute.manager.ComputeManager._get_instance_block_device_info')
    @mock.patch('nova.virt.driver.ComputeDriver.destroy')
    @mock.patch('nova.virt.driver.ComputeDriver.get_volume_connector')
    def test_shutdown_instance_endpoint_not_found(self, mock_connector,
            mock_destroy, mock_blk_device_info, mock_nw_info, mock_elevated):
        mock_connector.side_effect = cinder_exception.EndpointNotFound
        mock_elevated.return_value = self.context
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake',
                vm_state=vm_states.ERROR,
                task_state=task_states.DELETING)
        bdms = [mock.Mock(id=1, is_volume=True)]

        self.compute._shutdown_instance(self.context, instance, bdms,
                notify=False, try_deallocate_networks=False)

    def _test_init_instance_retries_reboot(self, instance, reboot_type,
                                           return_power_state):
        with contextlib.nested(
            mock.patch.object(self.compute, '_get_power_state',
                               return_value=return_power_state),
            mock.patch.object(self.compute.compute_rpcapi, 'reboot_instance'),
            mock.patch.object(compute_utils, 'get_nw_info_for_instance')
          ) as (
            _get_power_state,
            reboot_instance,
            get_nw_info_for_instance
          ):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance, block_device_info=None,
                             reboot_type=reboot_type)
            reboot_instance.assert_has_calls([call])

    def test_init_instance_retries_reboot_pending(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_PENDING
        for state in vm_states.ALLOW_SOFT_REBOOT:
            instance.vm_state = state
            self._test_init_instance_retries_reboot(instance, 'SOFT',
                                                    power_state.RUNNING)

    def test_init_instance_retries_reboot_pending_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_PENDING_HARD
        for state in vm_states.ALLOW_HARD_REBOOT:
            # NOTE(dave-mcnally) while a reboot of a vm in error state is
            # possible we don't attempt to recover an error during init
            if state == vm_states.ERROR:
                continue
            instance.vm_state = state
            self._test_init_instance_retries_reboot(instance, 'HARD',
                                                    power_state.RUNNING)

    def test_init_instance_retries_reboot_started(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        self._test_init_instance_retries_reboot(instance, 'HARD',
                                                power_state.NOSTATE)

    def test_init_instance_retries_reboot_started_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED_HARD
        self._test_init_instance_retries_reboot(instance, 'HARD',
                                                power_state.NOSTATE)

    def _test_init_instance_cleans_reboot_state(self, instance):
        with contextlib.nested(
            mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save', autospec=True),
            mock.patch.object(compute_utils, 'get_nw_info_for_instance')
          ) as (
            _get_power_state,
            instance_save,
            get_nw_info_for_instance
          ):
            self.compute._init_instance(self.context, instance)
            instance_save.assert_called_once_with()
            self.assertIsNone(instance.task_state)
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)

    def test_init_instance_cleans_image_state_reboot_started(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

    def test_init_instance_cleans_image_state_reboot_started_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED_HARD
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

    def test_init_instance_retries_power_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_OFF
        with mock.patch.object(self.compute, 'stop_instance'):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.stop_instance.assert_has_calls([call])

    def test_init_instance_retries_power_on(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_ON
        with mock.patch.object(self.compute, 'start_instance'):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.start_instance.assert_has_calls([call])

    def test_init_instance_retries_power_on_silent_exception(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_ON
        with mock.patch.object(self.compute, 'start_instance',
                              return_value=Exception):
            init_return = self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.start_instance.assert_has_calls([call])
            self.assertIsNone(init_return)

    def test_init_instance_retries_power_off_silent_exception(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_OFF
        with mock.patch.object(self.compute, 'stop_instance',
                              return_value=Exception):
            init_return = self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.stop_instance.assert_has_calls([call])
            self.assertIsNone(init_return)

    def test_get_instances_on_driver(self):
        fake_context = context.get_admin_context()

        driver_instances = []
        for x in xrange(10):
            driver_instances.append(fake_instance.fake_db_instance())

        self.mox.StubOutWithMock(self.compute.driver,
                'list_instance_uuids')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')

        self.compute.driver.list_instance_uuids().AndReturn(
                [inst['uuid'] for inst in driver_instances])
        db.instance_get_all_by_filters(
                fake_context,
                {'uuid': [inst['uuid'] for
                          inst in driver_instances]},
                'created_at', 'desc', columns_to_join=None,
                limit=None, marker=None,
                use_slave=True).AndReturn(
                        driver_instances)

        self.mox.ReplayAll()

        result = self.compute._get_instances_on_driver(fake_context)
        self.assertEqual([x['uuid'] for x in driver_instances],
                         [x['uuid'] for x in result])

    @mock.patch('nova.virt.driver.ComputeDriver.list_instance_uuids')
    @mock.patch('nova.db.api.instance_get_all_by_filters')
    def test_get_instances_on_driver_empty(self, mock_list, mock_db):
        fake_context = context.get_admin_context()
        mock_list.return_value = []

        result = self.compute._get_instances_on_driver(fake_context)
        # instance_get_all_by_filters should not be called
        self.assertEqual(0, mock_db.call_count)
        self.assertEqual([],
                         [x['uuid'] for x in result])

    def test_get_instances_on_driver_fallback(self):
        # Test getting instances when driver doesn't support
        # 'list_instance_uuids'
        self.compute.host = 'host'
        filters = {'host': self.compute.host}
        fake_context = context.get_admin_context()

        self.flags(instance_name_template='inst-%i')

        all_instances = []
        driver_instances = []
        for x in xrange(10):
            instance = fake_instance.fake_db_instance(name='inst-%i' % x,
                                                      id=x)
            if x % 2:
                driver_instances.append(instance)
            all_instances.append(instance)

        self.mox.StubOutWithMock(self.compute.driver,
                'list_instance_uuids')
        self.mox.StubOutWithMock(self.compute.driver,
                'list_instances')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')

        self.compute.driver.list_instance_uuids().AndRaise(
                NotImplementedError())
        self.compute.driver.list_instances().AndReturn(
                [inst['name'] for inst in driver_instances])
        db.instance_get_all_by_filters(
                fake_context, filters,
                'created_at', 'desc', columns_to_join=None,
                limit=None, marker=None,
                use_slave=True).AndReturn(all_instances)

        self.mox.ReplayAll()

        result = self.compute._get_instances_on_driver(fake_context, filters)
        self.assertEqual([x['uuid'] for x in driver_instances],
                         [x['uuid'] for x in result])

    def test_instance_usage_audit(self):
        instances = [objects.Instance(uuid='foo')]

        @classmethod
        def fake_get(*a, **k):
            return instances

        self.flags(instance_usage_audit=True)
        self.stubs.Set(compute_utils, 'has_audit_been_run',
                       lambda *a, **k: False)
        self.stubs.Set(objects.InstanceList,
                       'get_active_by_window_joined', fake_get)
        self.stubs.Set(compute_utils, 'start_instance_usage_audit',
                       lambda *a, **k: None)
        self.stubs.Set(compute_utils, 'finish_instance_usage_audit',
                       lambda *a, **k: None)

        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'notify_usage_exists')
        self.compute.conductor_api.notify_usage_exists(
            self.context, instances[0], ignore_missing_network_data=False)
        self.mox.ReplayAll()
        self.compute._instance_usage_audit(self.context)

    @mock.patch.object(objects.InstanceList, 'get_by_host')
    def test_sync_power_states(self, mock_get):
        instance = mock.Mock()
        mock_get.return_value = [instance]
        with mock.patch.object(self.compute._sync_power_pool,
                               'spawn_n') as mock_spawn:
            self.compute._sync_power_states(mock.sentinel.context)
            mock_get.assert_called_with(mock.sentinel.context,
                                        self.compute.host, expected_attrs=[],
                                        use_slave=True)
            mock_spawn.assert_called_once_with(mock.ANY, instance)

    def _get_sync_instance(self, power_state, vm_state, task_state=None,
                           shutdown_terminate=False):
        instance = objects.Instance()
        instance.uuid = 'fake-uuid'
        instance.power_state = power_state
        instance.vm_state = vm_state
        instance.host = self.compute.host
        instance.task_state = task_state
        instance.shutdown_terminate = shutdown_terminate
        self.mox.StubOutWithMock(instance, 'refresh')
        self.mox.StubOutWithMock(instance, 'save')
        return instance

    def test_sync_instance_power_state_match(self):
        instance = self._get_sync_instance(power_state.RUNNING,
                                           vm_states.ACTIVE)
        instance.refresh(use_slave=False)
        self.mox.ReplayAll()
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.RUNNING)

    def test_sync_instance_power_state_running_stopped(self):
        instance = self._get_sync_instance(power_state.RUNNING,
                                           vm_states.ACTIVE)
        instance.refresh(use_slave=False)
        instance.save()
        self.mox.ReplayAll()
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.SHUTDOWN)
        self.assertEqual(instance.power_state, power_state.SHUTDOWN)

    def _test_sync_to_stop(self, power_state, vm_state, driver_power_state,
                           stop=True, force=False, shutdown_terminate=False):
        instance = self._get_sync_instance(
            power_state, vm_state, shutdown_terminate=shutdown_terminate)
        instance.refresh(use_slave=False)
        instance.save()
        self.mox.StubOutWithMock(self.compute.compute_api, 'stop')
        self.mox.StubOutWithMock(self.compute.compute_api, 'delete')
        self.mox.StubOutWithMock(self.compute.compute_api, 'force_stop')
        if shutdown_terminate:
            self.compute.compute_api.delete(self.context, instance)
        elif stop:
            if force:
                self.compute.compute_api.force_stop(self.context, instance)
            else:
                self.compute.compute_api.stop(self.context, instance)
        self.mox.ReplayAll()
        self.compute._sync_instance_power_state(self.context, instance,
                                                driver_power_state)
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def test_sync_instance_power_state_to_stop(self):
        for ps in (power_state.SHUTDOWN, power_state.CRASHED,
                   power_state.SUSPENDED):
            self._test_sync_to_stop(power_state.RUNNING, vm_states.ACTIVE, ps)

        for ps in (power_state.SHUTDOWN, power_state.CRASHED):
            self._test_sync_to_stop(power_state.PAUSED, vm_states.PAUSED, ps,
                                    force=True)

        self._test_sync_to_stop(power_state.SHUTDOWN, vm_states.STOPPED,
                                power_state.RUNNING, force=True)

    def test_sync_instance_power_state_to_terminate(self):
        self._test_sync_to_stop(power_state.RUNNING, vm_states.ACTIVE,
                                power_state.SHUTDOWN,
                                force=False, shutdown_terminate=True)

    def test_sync_instance_power_state_to_no_stop(self):
        for ps in (power_state.PAUSED, power_state.NOSTATE):
            self._test_sync_to_stop(power_state.RUNNING, vm_states.ACTIVE, ps,
                                    stop=False)
        for vs in (vm_states.SOFT_DELETED, vm_states.DELETED):
            for ps in (power_state.NOSTATE, power_state.SHUTDOWN):
                self._test_sync_to_stop(power_state.RUNNING, vs, ps,
                                        stop=False)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_sync_instance_power_state')
    def test_query_driver_power_state_and_sync_pending_task(
            self, mock_sync_power_state):
        with mock.patch.object(self.compute.driver,
                               'get_info') as mock_get_info:
            db_instance = objects.Instance(uuid='fake-uuid',
                                           task_state=task_states.POWERING_OFF)
            self.compute._query_driver_power_state_and_sync(self.context,
                                                            db_instance)
            self.assertFalse(mock_get_info.called)
            self.assertFalse(mock_sync_power_state.called)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_sync_instance_power_state')
    def test_query_driver_power_state_and_sync_not_found_driver(
            self, mock_sync_power_state):
        error = exception.InstanceNotFound(instance_id=1)
        with mock.patch.object(self.compute.driver,
                               'get_info', side_effect=error) as mock_get_info:
            db_instance = objects.Instance(uuid='fake-uuid', task_state=None)
            self.compute._query_driver_power_state_and_sync(self.context,
                                                            db_instance)
            mock_get_info.assert_called_once_with(db_instance)
            mock_sync_power_state.assert_called_once_with(self.context,
                                                          db_instance,
                                                          power_state.NOSTATE,
                                                          use_slave=True)

    def test_run_pending_deletes(self):
        self.flags(instance_delete_interval=10)

        class FakeInstance(object):
            def __init__(self, uuid, name, smd):
                self.uuid = uuid
                self.name = name
                self.system_metadata = smd
                self.cleaned = False

            def __getitem__(self, name):
                return getattr(self, name)

            def save(self):
                pass

        class FakeInstanceList(object):
            def get_by_filters(self, *args, **kwargs):
                return []

        a = FakeInstance('123', 'apple', {'clean_attempts': '100'})
        b = FakeInstance('456', 'orange', {'clean_attempts': '3'})
        c = FakeInstance('789', 'banana', {})

        self.mox.StubOutWithMock(objects.InstanceList,
                                 'get_by_filters')
        objects.InstanceList.get_by_filters(
            {'read_deleted': 'yes'},
            {'deleted': True, 'soft_deleted': False, 'host': 'fake-mini',
             'cleaned': False},
            expected_attrs=['info_cache', 'security_groups',
                            'system_metadata'],
            use_slave=True).AndReturn([a, b, c])

        self.mox.StubOutWithMock(self.compute.driver, 'delete_instance_files')
        self.compute.driver.delete_instance_files(
            mox.IgnoreArg()).AndReturn(True)
        self.compute.driver.delete_instance_files(
            mox.IgnoreArg()).AndReturn(False)

        self.mox.ReplayAll()

        self.compute._run_pending_deletes({})
        self.assertFalse(a.cleaned)
        self.assertEqual('100', a.system_metadata['clean_attempts'])
        self.assertTrue(b.cleaned)
        self.assertEqual('4', b.system_metadata['clean_attempts'])
        self.assertFalse(c.cleaned)
        self.assertEqual('1', c.system_metadata['clean_attempts'])

    def test_attach_interface_failure(self):
        # Test that the fault methods are invoked when an attach fails
        db_instance = fake_instance.fake_db_instance()
        f_instance = objects.Instance._from_db_object(self.context,
                                                      objects.Instance(),
                                                      db_instance)
        e = exception.InterfaceAttachFailed(instance_uuid=f_instance.uuid)

        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(self.compute.network_api,
                           'allocate_port_for_instance',
                           side_effect=e)
        def do_test(meth, add_fault):
            self.assertRaises(exception.InterfaceAttachFailed,
                              self.compute.attach_interface,
                              self.context, f_instance, 'net_id', 'port_id',
                              None)
            add_fault.assert_has_calls(
                    mock.call(self.context, f_instance, e,
                              mock.ANY))

        do_test()

    def test_detach_interface_failure(self):
        # Test that the fault methods are invoked when a detach fails

        # Build test data that will cause a PortNotFound exception
        f_instance = mock.MagicMock()
        f_instance.info_cache = mock.MagicMock()
        f_instance.info_cache.network_info = []

        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(self.compute, '_set_instance_error_state')
        def do_test(meth, add_fault):
            self.assertRaises(exception.PortNotFound,
                              self.compute.detach_interface,
                              self.context, f_instance, 'port_id')
            add_fault.assert_has_calls(
                    mock.call(self.context, f_instance, mock.ANY, mock.ANY))

        do_test()

    def test_swap_volume_volume_api_usage(self):
        # This test ensures that volume_id arguments are passed to volume_api
        # and that volume states are OK
        volumes = {}
        old_volume_id = uuidutils.generate_uuid()
        volumes[old_volume_id] = {'id': old_volume_id,
                                  'display_name': 'old_volume',
                                  'status': 'detaching',
                                  'size': 1}
        new_volume_id = uuidutils.generate_uuid()
        volumes[new_volume_id] = {'id': new_volume_id,
                                  'display_name': 'new_volume',
                                  'status': 'available',
                                  'size': 2}

        def fake_vol_api_roll_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'detaching':
                volumes[volume_id]['status'] = 'in-use'

        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                   {'device_name': '/dev/vdb', 'source_type': 'volume',
                    'destination_type': 'volume', 'instance_uuid': 'fake',
                    'connection_info': '{"foo": "bar"}'})

        def fake_vol_api_func(context, volume, *args):
            self.assertTrue(uuidutils.is_uuid_like(volume))
            return {}

        def fake_vol_get(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            return volumes[volume_id]

        def fake_vol_unreserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'attaching':
                volumes[volume_id]['status'] = 'available'

        def fake_vol_migrate_volume_completion(context, old_volume_id,
                                               new_volume_id, error=False):
            self.assertTrue(uuidutils.is_uuid_like(old_volume_id))
            self.assertTrue(uuidutils.is_uuid_like(new_volume_id))
            volumes[old_volume_id]['status'] = 'in-use'
            return {'save_volume_id': new_volume_id}

        def fake_func_exc(*args, **kwargs):
            raise AttributeError  # Random exception

        def fake_swap_volume(old_connection_info, new_connection_info,
                             instance, mountpoint, resize_to):
            self.assertEqual(resize_to, 2)

        self.stubs.Set(self.compute.volume_api, 'roll_detaching',
                       fake_vol_api_roll_detaching)
        self.stubs.Set(self.compute.volume_api, 'get', fake_vol_get)
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       fake_vol_api_func)
        self.stubs.Set(self.compute.volume_api, 'unreserve_volume',
                       fake_vol_unreserve)
        self.stubs.Set(self.compute.volume_api, 'terminate_connection',
                       fake_vol_api_func)
        self.stubs.Set(db, 'block_device_mapping_get_by_volume_id',
                       lambda x, y, z: fake_bdm)
        self.stubs.Set(self.compute.driver, 'get_volume_connector',
                       lambda x: {})
        self.stubs.Set(self.compute.driver, 'swap_volume',
                       fake_swap_volume)
        self.stubs.Set(self.compute.volume_api, 'migrate_volume_completion',
                      fake_vol_migrate_volume_completion)
        self.stubs.Set(db, 'block_device_mapping_update',
                       lambda *a, **k: fake_bdm)
        self.stubs.Set(db,
                       'instance_fault_create',
                       lambda x, y:
                           test_instance_fault.fake_faults['fake-uuid'][0])

        # Good path
        self.compute.swap_volume(self.context, old_volume_id, new_volume_id,
                fake_instance.fake_instance_obj(
                    self.context, **{'uuid': 'fake'}))
        self.assertEqual(volumes[old_volume_id]['status'], 'in-use')

        # Error paths
        volumes[old_volume_id]['status'] = 'detaching'
        volumes[new_volume_id]['status'] = 'attaching'
        self.stubs.Set(self.compute.driver, 'swap_volume', fake_func_exc)
        self.assertRaises(AttributeError, self.compute.swap_volume,
                          self.context, old_volume_id, new_volume_id,
                          fake_instance.fake_instance_obj(
                                self.context, **{'uuid': 'fake'}))
        self.assertEqual(volumes[old_volume_id]['status'], 'in-use')
        self.assertEqual(volumes[new_volume_id]['status'], 'available')

        volumes[old_volume_id]['status'] = 'detaching'
        volumes[new_volume_id]['status'] = 'attaching'
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       fake_func_exc)
        self.assertRaises(AttributeError, self.compute.swap_volume,
                          self.context, old_volume_id, new_volume_id,
                          fake_instance.fake_instance_obj(
                                self.context, **{'uuid': 'fake'}))
        self.assertEqual(volumes[old_volume_id]['status'], 'in-use')
        self.assertEqual(volumes[new_volume_id]['status'], 'available')

    def test_check_can_live_migrate_source(self):
        is_volume_backed = 'volume_backed'
        dest_check_data = dict(foo='bar')
        db_instance = fake_instance.fake_db_instance()
        instance = objects.Instance._from_db_object(
                self.context, objects.Instance(), db_instance)
        expected_dest_check_data = dict(dest_check_data,
                                        is_volume_backed=is_volume_backed)

        self.mox.StubOutWithMock(self.compute.compute_api,
                                 'is_volume_backed_instance')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_block_device_info')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_source')

        self.compute.compute_api.is_volume_backed_instance(
                self.context, instance).AndReturn(is_volume_backed)
        self.compute._get_instance_block_device_info(
                self.context, instance, refresh_conn_info=True
                ).AndReturn({'block_device_mapping': 'fake'})
        self.compute.driver.check_can_live_migrate_source(
                self.context, instance, expected_dest_check_data,
                {'block_device_mapping': 'fake'})

        self.mox.ReplayAll()

        self.compute.check_can_live_migrate_source(
                self.context, instance=instance,
                dest_check_data=dest_check_data)

    def _test_check_can_live_migrate_destination(self, do_raise=False,
                                                 has_mig_data=False):
        db_instance = fake_instance.fake_db_instance(host='fake-host')
        instance = objects.Instance._from_db_object(
                self.context, objects.Instance(), db_instance)
        instance.host = 'fake-host'
        block_migration = 'block_migration'
        disk_over_commit = 'disk_over_commit'
        src_info = 'src_info'
        dest_info = 'dest_info'
        dest_check_data = dict(foo='bar')
        mig_data = dict(cow='moo')
        expected_result = dict(mig_data)
        if has_mig_data:
            dest_check_data['migrate_data'] = dict(cat='meow')
            expected_result.update(cat='meow')

        self.mox.StubOutWithMock(self.compute, '_get_compute_info')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'check_can_live_migrate_source')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination_cleanup')

        self.compute._get_compute_info(self.context,
                                       'fake-host').AndReturn(src_info)
        self.compute._get_compute_info(self.context,
                                       CONF.host).AndReturn(dest_info)
        self.compute.driver.check_can_live_migrate_destination(
                self.context, instance, src_info, dest_info,
                block_migration, disk_over_commit).AndReturn(dest_check_data)

        mock_meth = self.compute.compute_rpcapi.check_can_live_migrate_source(
                self.context, instance, dest_check_data)
        if do_raise:
            mock_meth.AndRaise(test.TestingException())
            self.mox.StubOutWithMock(db, 'instance_fault_create')
            db.instance_fault_create(
                self.context, mox.IgnoreArg()).AndReturn(
                    test_instance_fault.fake_faults['fake-uuid'][0])
        else:
            mock_meth.AndReturn(mig_data)
        self.compute.driver.check_can_live_migrate_destination_cleanup(
                self.context, dest_check_data)

        self.mox.ReplayAll()

        result = self.compute.check_can_live_migrate_destination(
                self.context, instance=instance,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)
        self.assertEqual(expected_result, result)

    def test_check_can_live_migrate_destination_success(self):
        self._test_check_can_live_migrate_destination()

    def test_check_can_live_migrate_destination_success_w_mig_data(self):
        self._test_check_can_live_migrate_destination(has_mig_data=True)

    def test_check_can_live_migrate_destination_fail(self):
        self.assertRaises(
                test.TestingException,
                self._test_check_can_live_migrate_destination,
                do_raise=True)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_prepare_for_instance_event(self, lock_name_mock):
        inst_obj = objects.Instance(uuid='foo')
        result = self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event')
        self.assertIn('foo', self.compute.instance_events._events)
        self.assertIn('test-event',
                      self.compute.instance_events._events['foo'])
        self.assertEqual(
            result,
            self.compute.instance_events._events['foo']['test-event'])
        self.assertTrue(hasattr(result, 'send'))
        lock_name_mock.assert_called_once_with(inst_obj)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_pop_instance_event(self, lock_name_mock):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            'foo': {
                'test-event': event,
                }
            }
        inst_obj = objects.Instance(uuid='foo')
        event_obj = objects.InstanceExternalEvent(name='test-event',
                                                  tag=None)
        result = self.compute.instance_events.pop_instance_event(inst_obj,
                                                                 event_obj)
        self.assertEqual(result, event)
        lock_name_mock.assert_called_once_with(inst_obj)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_clear_events_for_instance(self, lock_name_mock):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            'foo': {
                'test-event': event,
                }
            }
        inst_obj = objects.Instance(uuid='foo')
        result = self.compute.instance_events.clear_events_for_instance(
            inst_obj)
        self.assertEqual(result, {'test-event': event})
        lock_name_mock.assert_called_once_with(inst_obj)

    def test_instance_events_lock_name(self):
        inst_obj = objects.Instance(uuid='foo')
        result = self.compute.instance_events._lock_name(inst_obj)
        self.assertEqual(result, 'foo-events')

    def test_prepare_for_instance_event_again(self):
        inst_obj = objects.Instance(uuid='foo')
        self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event')
        # A second attempt will avoid creating a new list; make sure we
        # get the current list
        result = self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event')
        self.assertIn('foo', self.compute.instance_events._events)
        self.assertIn('test-event',
                      self.compute.instance_events._events['foo'])
        self.assertEqual(
            result,
            self.compute.instance_events._events['foo']['test-event'])
        self.assertTrue(hasattr(result, 'send'))

    def test_process_instance_event(self):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            'foo': {
                'test-event': event,
                }
            }
        inst_obj = objects.Instance(uuid='foo')
        event_obj = objects.InstanceExternalEvent(name='test-event', tag=None)
        self.compute._process_instance_event(inst_obj, event_obj)
        self.assertTrue(event.ready())
        self.assertEqual(event_obj, event.wait())
        self.assertEqual({}, self.compute.instance_events._events)

    def test_external_instance_event(self):
        instances = [
            objects.Instance(id=1, uuid='uuid1'),
            objects.Instance(id=2, uuid='uuid2')]
        events = [
            objects.InstanceExternalEvent(name='network-changed',
                                          tag='tag1',
                                          instance_uuid='uuid1'),
            objects.InstanceExternalEvent(name='foo', instance_uuid='uuid2',
                                          tag='tag2')]

        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info')
        @mock.patch.object(self.compute, '_process_instance_event')
        def do_test(_process_instance_event, get_instance_nw_info):
            self.compute.external_instance_event(self.context,
                                                 instances, events)
            get_instance_nw_info.assert_called_once_with(self.context,
                                                         instances[0])
            _process_instance_event.assert_called_once_with(instances[1],
                                                            events[1])
        do_test()

    def test_retry_reboot_pending_soft(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_PENDING
        instance.vm_state = vm_states.ACTIVE
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'SOFT')

    def test_retry_reboot_pending_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_PENDING_HARD
        instance.vm_state = vm_states.ACTIVE
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_soft_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.NOSTATE):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED_HARD
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.NOSTATE):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_on(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED_HARD
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertFalse(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_no_reboot(self):
        instance = objects.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = 'bar'
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertFalse(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    @mock.patch('nova.objects.BlockDeviceMapping.get_by_volume_id')
    @mock.patch('nova.compute.manager.ComputeManager._detach_volume')
    @mock.patch('nova.objects.Instance._from_db_object')
    def test_remove_volume_connection(self, inst_from_db, detach, bdm_get):
        bdm = mock.sentinel.bdm
        inst_obj = mock.sentinel.inst_obj
        bdm_get.return_value = bdm
        inst_from_db.return_value = inst_obj
        with mock.patch.object(self.compute, 'volume_api'):
            self.compute.remove_volume_connection(self.context, 'vol',
                                                  inst_obj)
        detach.assert_called_once_with(self.context, inst_obj, bdm)

    def _test_rescue(self, clean_shutdown=True):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE)
        fake_nw_info = network_model.NetworkInfo()
        rescue_image_meta = {'id': 'fake', 'name': 'fake'}
        with contextlib.nested(
            mock.patch.object(objects.InstanceActionEvent, 'event_start'),
            mock.patch.object(objects.InstanceActionEvent,
                              'event_finish_with_failure'),
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                              return_value=fake_nw_info),
            mock.patch.object(self.compute, '_get_rescue_image',
                              return_value=rescue_image_meta),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute, '_power_off_instance'),
            mock.patch.object(self.compute.driver, 'rescue'),
            mock.patch.object(self.compute.conductor_api,
                              'notify_usage_exists'),
            mock.patch.object(self.compute, '_get_power_state',
                              return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save')
        ) as (
            event_start, event_finish, elevated_context, get_nw_info,
            get_rescue_image, notify_instance_usage, power_off_instance,
            driver_rescue, notify_usage_exists, get_power_state, instance_save
        ):
            self.compute.rescue_instance(
                self.context, instance, rescue_password='verybadpass',
                rescue_image_ref=None, clean_shutdown=clean_shutdown)

            # assert the field values on the instance object
            self.assertEqual(vm_states.RESCUED, instance.vm_state)
            self.assertIsNone(instance.task_state)
            self.assertEqual(power_state.RUNNING, instance.power_state)
            self.assertIsNotNone(instance.launched_at)

            # assert our mock calls
            get_nw_info.assert_called_once_with(self.context, instance)
            get_rescue_image.assert_called_once_with(
                self.context, instance, None)

            extra_usage_info = {'rescue_image_name': 'fake'}
            notify_calls = [
                mock.call(self.context, instance, "rescue.start",
                          extra_usage_info=extra_usage_info,
                          network_info=fake_nw_info),
                mock.call(self.context, instance, "rescue.end",
                          extra_usage_info=extra_usage_info,
                          network_info=fake_nw_info)
            ]
            notify_instance_usage.assert_has_calls(notify_calls)

            power_off_instance.assert_called_once_with(self.context, instance,
                                                       clean_shutdown)

            driver_rescue.assert_called_once_with(
                self.context, instance, fake_nw_info, rescue_image_meta,
                'verybadpass')

            notify_usage_exists.assert_called_once_with(
                self.context, instance, current_period=True)

            instance_save.assert_called_once_with(
                expected_task_state=task_states.RESCUING)

    def test_rescue(self):
        self._test_rescue()

    def test_rescue_forced_shutdown(self):
        self._test_rescue(clean_shutdown=False)

    def test_unrescue(self):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.RESCUED)
        fake_nw_info = network_model.NetworkInfo()
        with contextlib.nested(
            mock.patch.object(objects.InstanceActionEvent, 'event_start'),
            mock.patch.object(objects.InstanceActionEvent,
                              'event_finish_with_failure'),
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                              return_value=fake_nw_info),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute.driver, 'unrescue'),
            mock.patch.object(self.compute, '_get_power_state',
                              return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save')
        ) as (
            event_start, event_finish, elevated_context, get_nw_info,
            notify_instance_usage, driver_unrescue, get_power_state,
            instance_save
        ):
            self.compute.unrescue_instance(self.context, instance)

            # assert the field values on the instance object
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)
            self.assertIsNone(instance.task_state)
            self.assertEqual(power_state.RUNNING, instance.power_state)

            # assert our mock calls
            get_nw_info.assert_called_once_with(self.context, instance)

            notify_calls = [
                mock.call(self.context, instance, "unrescue.start",
                          network_info=fake_nw_info),
                mock.call(self.context, instance, "unrescue.end",
                          network_info=fake_nw_info)
            ]
            notify_instance_usage.assert_has_calls(notify_calls)

            driver_unrescue.assert_called_once_with(instance, fake_nw_info)

            instance_save.assert_called_once_with(
                expected_task_state=task_states.UNRESCUING)

    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.RUNNING)
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch('nova.utils.generate_password', return_value='fake-pass')
    def test_set_admin_password(self, gen_password_mock,
                                instance_save_mock, power_state_mock,
                                event_finish_mock, event_start_mock):
        # Ensure instance can have its admin password set.
        instance = fake_instance.fake_instance_obj(
            self.context,
            vm_state=vm_states.ACTIVE,
            task_state=task_states.UPDATING_PASSWORD)

        @mock.patch.object(self.context, 'elevated', return_value=self.context)
        @mock.patch.object(self.compute.driver, 'set_admin_password')
        def do_test(driver_mock, elevated_mock):
            # call the manager method
            self.compute.set_admin_password(self.context, instance, None)
            # make our assertions
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)
            self.assertIsNone(instance.task_state)

            power_state_mock.assert_called_once_with(self.context, instance)
            driver_mock.assert_called_once_with(instance, 'fake-pass')
            instance_save_mock.assert_called_once_with(
                expected_task_state=task_states.UPDATING_PASSWORD)

        do_test()

    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.NOSTATE)
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_set_admin_password_bad_state(self, add_fault_mock,
                                          instance_save_mock, power_state_mock,
                                          event_finish_mock, event_start_mock):
        # Test setting password while instance is rebuilding.
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self.context, 'elevated',
                               return_value=self.context):
            # call the manager method
            self.assertRaises(exception.InstancePasswordSetFailed,
                              self.compute.set_admin_password,
                              self.context, instance, None)

        # make our assertions
        power_state_mock.assert_called_once_with(self.context, instance)
        instance_save_mock.assert_called_once_with(
            expected_task_state=task_states.UPDATING_PASSWORD)
        add_fault_mock.assert_called_once_with(
            self.context, instance, mock.ANY, mock.ANY)

    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch('nova.utils.generate_password', return_value='fake-pass')
    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.RUNNING)
    @mock.patch('nova.compute.manager.ComputeManager._instance_update')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def _do_test_set_admin_password_driver_error(self, exc,
                                                 expected_vm_state,
                                                 expected_task_state,
                                                 expected_exception,
                                                 add_fault_mock,
                                                 instance_save_mock,
                                                 update_mock,
                                                 power_state_mock,
                                                 gen_password_mock,
                                                 event_finish_mock,
                                                 event_start_mock):
        # Ensure expected exception is raised if set_admin_password fails.
        instance = fake_instance.fake_instance_obj(
            self.context,
            vm_state=vm_states.ACTIVE,
            task_state=task_states.UPDATING_PASSWORD)

        @mock.patch.object(self.context, 'elevated', return_value=self.context)
        @mock.patch.object(self.compute.driver, 'set_admin_password',
                           side_effect=exc)
        def do_test(driver_mock, elevated_mock):
            # error raised from the driver should not reveal internal
            # information so a new error is raised
            self.assertRaises(expected_exception,
                              self.compute.set_admin_password,
                              self.context,
                              instance=instance,
                              new_pass=None)

            if expected_exception == NotImplementedError:
                instance_save_mock.assert_called_once_with(
                    expected_task_state=task_states.UPDATING_PASSWORD)
            else:
                # setting the instance to error state
                instance_save_mock.assert_called_once_with()

            self.assertEqual(expected_vm_state, instance.vm_state)
            # check revert_task_state decorator
            update_mock.assert_called_once_with(
                self.context, instance.uuid,
                task_state=expected_task_state)
            # check wrap_instance_fault decorator
            add_fault_mock.assert_called_once_with(
                self.context, instance, mock.ANY, mock.ANY)

        do_test()

    def test_set_admin_password_driver_not_authorized(self):
        # Ensure expected exception is raised if set_admin_password not
        # authorized.
        exc = exception.Forbidden('Internal error')
        expected_exception = exception.InstancePasswordSetFailed
        self._do_test_set_admin_password_driver_error(
            exc, vm_states.ERROR, None, expected_exception)

    def test_set_admin_password_driver_not_implemented(self):
        # Ensure expected exception is raised if set_admin_password not
        # implemented by driver.
        exc = NotImplementedError()
        expected_exception = NotImplementedError
        self._do_test_set_admin_password_driver_error(
            exc, vm_states.ACTIVE, None, expected_exception)

    def _test_init_host_with_partial_migration(self, task_state=None,
                                               vm_state=vm_states.ACTIVE):
        our_host = self.compute.host
        instance_1 = objects.Instance(self.context)
        instance_1.uuid = 'foo'
        instance_1.task_state = task_state
        instance_1.vm_state = vm_state
        instance_1.host = 'not-' + our_host
        instance_2 = objects.Instance(self.context)
        instance_2.uuid = 'bar'
        instance_2.task_state = None
        instance_2.vm_state = vm_states.ACTIVE
        instance_2.host = 'not-' + our_host

        with contextlib.nested(
            mock.patch.object(self.compute, '_get_instances_on_driver',
                               return_value=[instance_1,
                                             instance_2]),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                               return_value=None),
            mock.patch.object(self.compute, '_get_instance_block_device_info',
                               return_value={}),
            mock.patch.object(self.compute, '_is_instance_storage_shared',
                               return_value=False),
            mock.patch.object(self.compute.driver, 'destroy')
        ) as (_get_instances_on_driver, _get_instance_nw_info,
              _get_instance_block_device_info, _is_instance_storage_shared,
              destroy):
            self.compute._destroy_evacuated_instances(self.context)
            destroy.assert_called_once_with(self.context, instance_2, None,
                                            {}, True)

    def test_init_host_with_partial_migration_migrating(self):
        self._test_init_host_with_partial_migration(
            task_state=task_states.MIGRATING)

    def test_init_host_with_partial_migration_resize_migrating(self):
        self._test_init_host_with_partial_migration(
            task_state=task_states.RESIZE_MIGRATING)

    def test_init_host_with_partial_migration_resize_migrated(self):
        self._test_init_host_with_partial_migration(
            task_state=task_states.RESIZE_MIGRATED)

    def test_init_host_with_partial_migration_finish_resize(self):
        self._test_init_host_with_partial_migration(
            task_state=task_states.RESIZE_FINISH)

    def test_init_host_with_partial_migration_resized(self):
        self._test_init_host_with_partial_migration(
            vm_state=vm_states.RESIZED)

    @mock.patch('nova.compute.manager.ComputeManager._instance_update')
    def test_error_out_instance_on_exception_not_implemented_err(self,
                                                        inst_update_mock):
        instance = fake_instance.fake_instance_obj(self.context)

        def do_test():
            with self.compute._error_out_instance_on_exception(
                    self.context, instance, instance_state=vm_states.STOPPED):
                raise NotImplementedError('test')

        self.assertRaises(NotImplementedError, do_test)
        inst_update_mock.assert_called_once_with(
            self.context, instance.uuid,
            vm_state=vm_states.STOPPED, task_state=None)

    @mock.patch('nova.compute.manager.ComputeManager._instance_update')
    def test_error_out_instance_on_exception_inst_fault_rollback(self,
                                                        inst_update_mock):
        instance = fake_instance.fake_instance_obj(self.context)

        def do_test():
            with self.compute._error_out_instance_on_exception(self.context,
                                                               instance):
                raise exception.InstanceFaultRollback(
                    inner_exception=test.TestingException('test'))

        self.assertRaises(test.TestingException, do_test)
        inst_update_mock.assert_called_once_with(
            self.context, instance.uuid,
            vm_state=vm_states.ACTIVE, task_state=None)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_set_instance_error_state')
    def test_error_out_instance_on_exception_unknown_with_quotas(self,
                                                                 set_error):
        instance = fake_instance.fake_instance_obj(self.context)
        quotas = mock.create_autospec(objects.Quotas, spec_set=True)

        def do_test():
            with self.compute._error_out_instance_on_exception(
                    self.context, instance, quotas):
                raise test.TestingException('test')

        self.assertRaises(test.TestingException, do_test)
        self.assertEqual(1, len(quotas.method_calls))
        self.assertEqual(mock.call.rollback(), quotas.method_calls[0])
        set_error.assert_called_once_with(self.context, instance)

    def test_cleanup_volumes(self):
        instance = fake_instance.fake_instance_obj(self.context)
        bdm_do_not_delete_dict = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id1', 'source_type': 'image',
                'delete_on_termination': False})
        bdm_delete_dict = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id2', 'source_type': 'image',
                'delete_on_termination': True})
        bdms = block_device_obj.block_device_make_list(self.context,
            [bdm_do_not_delete_dict, bdm_delete_dict])

        with mock.patch.object(self.compute.volume_api,
                'delete') as volume_delete:
            self.compute._cleanup_volumes(self.context, instance.uuid, bdms)
            volume_delete.assert_called_once_with(self.context,
                    bdms[1].volume_id)

    def test_cleanup_volumes_exception_do_not_raise(self):
        instance = fake_instance.fake_instance_obj(self.context)
        bdm_dict1 = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id1', 'source_type': 'image',
                'delete_on_termination': True})
        bdm_dict2 = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id2', 'source_type': 'image',
                'delete_on_termination': True})
        bdms = block_device_obj.block_device_make_list(self.context,
            [bdm_dict1, bdm_dict2])

        with mock.patch.object(self.compute.volume_api,
                'delete',
                side_effect=[test.TestingException(), None]) as volume_delete:
            self.compute._cleanup_volumes(self.context, instance.uuid, bdms,
                    raise_exc=False)
            calls = [mock.call(self.context, bdm.volume_id) for bdm in bdms]
            self.assertEqual(calls, volume_delete.call_args_list)

    def test_cleanup_volumes_exception_raise(self):
        instance = fake_instance.fake_instance_obj(self.context)
        bdm_dict1 = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id1', 'source_type': 'image',
                'delete_on_termination': True})
        bdm_dict2 = fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': 'fake-id2', 'source_type': 'image',
                'delete_on_termination': True})
        bdms = block_device_obj.block_device_make_list(self.context,
            [bdm_dict1, bdm_dict2])

        with mock.patch.object(self.compute.volume_api,
                'delete',
                side_effect=[test.TestingException(), None]) as volume_delete:
            self.assertRaises(test.TestingException,
                    self.compute._cleanup_volumes, self.context, instance.uuid,
                    bdms)
            calls = [mock.call(self.context, bdm.volume_id) for bdm in bdms]
            self.assertEqual(calls, volume_delete.call_args_list)

    def test_start_building(self):
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self.compute, '_instance_update') as update:
            self.compute._start_building(self.context, instance)
            update.assert_called_once_with(
                self.context, instance.uuid, vm_state=vm_states.BUILDING,
                task_state=None, expected_task_state=(task_states.SCHEDULING,
                                                      None))

    def _test_prebuild_instance_build_abort_exception(self, exc):
        instance = fake_instance.fake_instance_obj(self.context)
        with contextlib.nested(
            mock.patch.object(self.compute, '_check_instance_exists'),
            mock.patch.object(self.compute, '_start_building',
                              side_effect=exc)
        ) as (
            check, start
        ):
            # run the code
            self.assertRaises(exception.BuildAbortException,
                              self.compute._prebuild_instance,
                              self.context, instance)
        # assert the calls
        check.assert_called_once_with(self.context, instance)
        start.assert_called_once_with(self.context, instance)

    def test_prebuild_instance_instance_not_found(self):
        self._test_prebuild_instance_build_abort_exception(
            exception.InstanceNotFound(instance_id='fake'))

    def test_prebuild_instance_unexpected_deleting_task_state_err(self):
        self._test_prebuild_instance_build_abort_exception(
            exception.UnexpectedDeletingTaskStateError(expected='foo',
                                                       actual='bar'))

    def test_stop_instance_task_state_none_power_state_shutdown(self):
        # Tests that stop_instance doesn't puke when the instance power_state
        # is shutdown and the task_state is None.
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE,
            task_state=None, power_state=power_state.SHUTDOWN)

        @mock.patch.object(objects.InstanceActionEvent, 'event_start')
        @mock.patch.object(objects.InstanceActionEvent,
                           'event_finish_with_failure')
        @mock.patch.object(self.compute, '_get_power_state',
                           return_value=power_state.SHUTDOWN)
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, '_power_off_instance')
        @mock.patch.object(instance, 'save')
        def do_test(save_mock, power_off_mock, notify_mock, get_state_mock,
                    event_finish_mock, event_start_mock):
            # run the code
            self.compute.stop_instance(self.context, instance)
            # assert the calls
            self.assertEqual(2, get_state_mock.call_count)
            notify_mock.assert_has_calls([
                mock.call(self.context, instance, 'power_off.start'),
                mock.call(self.context, instance, 'power_off.end')
            ])
            power_off_mock.assert_called_once_with(
                self.context, instance, True)
            save_mock.assert_called_once_with(
                expected_task_state=[task_states.POWERING_OFF, None])
            self.assertEqual(power_state.SHUTDOWN, instance.power_state)
            self.assertIsNone(instance.task_state)
            self.assertEqual(vm_states.STOPPED, instance.vm_state)

        do_test()

    def test_reset_network_driver_not_implemented(self):
        instance = fake_instance.fake_instance_obj(self.context)

        @mock.patch.object(self.compute.driver, 'reset_network',
                           side_effect=NotImplementedError())
        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        def do_test(mock_add_fault, mock_reset):
            self.assertRaises(messaging.ExpectedException,
                              self.compute.reset_network,
                              self.context,
                              instance)

            self.compute = utils.ExceptionHelper(self.compute)

            self.assertRaises(NotImplementedError,
                              self.compute.reset_network,
                              self.context,
                              instance)

        do_test()

    def test_rebuild_default_impl(self):
        def _detach(context, bdms):
            pass

        def _attach(context, instance, bdms, do_check_attach=True):
            return {'block_device_mapping': 'shared_block_storage'}

        def _spawn(context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
            self.assertEqual(block_device_info['block_device_mapping'],
                             'shared_block_storage')

        with contextlib.nested(
            mock.patch.object(self.compute.driver, 'destroy',
                              return_value=None),
            mock.patch.object(self.compute.driver, 'spawn',
                              side_effect=_spawn),
            mock.patch.object(objects.Instance, 'save',
                              return_value=None)
        ) as(
             mock_destroy,
             mock_spawn,
             mock_save
        ):
            instance = fake_instance.fake_instance_obj(self.context)
            instance.task_state = task_states.REBUILDING
            instance.save(expected_task_state=[task_states.REBUILDING])
            self.compute._rebuild_default_impl(self.context,
                                               instance,
                                               None,
                                               [],
                                               admin_password='new_pass',
                                               bdms=[],
                                               detach_block_devices=_detach,
                                               attach_block_devices=_attach,
                                               network_info=None,
                                               recreate=True,
                                               block_device_info=None,
                                               preserve_ephemeral=False)

            self.assertFalse(mock_destroy.called)
            self.assertTrue(mock_save.called)
            self.assertTrue(mock_spawn.called)

    @mock.patch.object(utils, 'last_completed_audit_period',
            return_value=(0, 0))
    @mock.patch.object(time, 'time', side_effect=[10, 20, 21])
    @mock.patch.object(objects.InstanceList, 'get_by_host', return_value=[])
    @mock.patch.object(objects.BandwidthUsage, 'get_by_instance_uuid_and_mac')
    @mock.patch.object(db, 'bw_usage_update')
    def test_poll_bandwidth_usage(self, bw_usage_update, get_by_uuid_mac,
            get_by_host, time, last_completed_audit):
        bw_counters = [{'uuid': 'fake-uuid', 'mac_address': 'fake-mac',
                        'bw_in': 1, 'bw_out': 2}]
        usage = objects.BandwidthUsage()
        usage.bw_in = 3
        usage.bw_out = 4
        usage.last_ctr_in = 0
        usage.last_ctr_out = 0
        self.flags(bandwidth_poll_interval=1)
        get_by_uuid_mac.return_value = usage
        _time = timeutils.utcnow()
        bw_usage_update.return_value = {'instance_uuid': '', 'mac': '',
                'start_period': _time, 'last_refreshed': _time, 'bw_in': 0,
                'bw_out': 0, 'last_ctr_in': 0, 'last_ctr_out': 0, 'deleted': 0,
                'created_at': _time, 'updated_at': _time, 'deleted_at': _time}
        with mock.patch.object(self.compute.driver,
                'get_all_bw_counters', return_value=bw_counters):
            self.compute._poll_bandwidth_usage(self.context)
            get_by_uuid_mac.assert_called_once_with(self.context, 'fake-uuid',
                    'fake-mac', start_period=0, use_slave=True)
            bw_usage_update.assert_called_once_with(self.context, 'fake-uuid',
                    'fake-mac', 0, 4, 6, 1, 2,
                    last_refreshed=timeutils.isotime(_time),
                    update_cells=False)


class ComputeManagerBuildInstanceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerBuildInstanceTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.admin_pass = 'pass'
        self.injected_files = []
        self.image = {}
        self.node = 'fake-node'
        self.limits = {}
        self.requested_networks = []
        self.security_groups = []
        self.block_device_mapping = []
        self.filter_properties = {'retry': {'num_attempts': 1,
                                            'hosts': [[self.compute.host,
                                                       'fake-node']]}}

        def fake_network_info():
            return network_model.NetworkInfo()

        self.network_info = network_model.NetworkInfoAsyncWrapper(
                fake_network_info)
        self.block_device_info = self.compute._prep_block_device(context,
                self.instance, self.block_device_mapping)

        # override tracker with a version that doesn't need the database:
        fake_rt = fake_resource_tracker.FakeResourceTracker(self.compute.host,
                    self.compute.driver, self.node)
        self.compute._resource_tracker_dict[self.node] = fake_rt

    def _do_build_instance_update(self, reschedule_update=False):
        self.mox.StubOutWithMock(self.instance, 'save')
        self.instance.save(
                expected_task_state=(task_states.SCHEDULING, None)).AndReturn(
                        self.instance)
        if reschedule_update:
            self.instance.save().AndReturn(self.instance)

    def _build_and_run_instance_update(self):
        self.mox.StubOutWithMock(self.instance, 'save')
        self._build_resources_instance_update(stub=False)
        self.instance.save(expected_task_state=
                task_states.BLOCK_DEVICE_MAPPING).AndReturn(self.instance)

    def _build_resources_instance_update(self, stub=True):
        if stub:
            self.mox.StubOutWithMock(self.instance, 'save')
        self.instance.save().AndReturn(self.instance)

    def _notify_about_instance_usage(self, event, stub=True, **kwargs):
        if stub:
            self.mox.StubOutWithMock(self.compute,
                    '_notify_about_instance_usage')
        self.compute._notify_about_instance_usage(self.context, self.instance,
                event, **kwargs)

    def _instance_action_events(self):
        self.mox.StubOutWithMock(objects.InstanceActionEvent, 'event_start')
        self.mox.StubOutWithMock(objects.InstanceActionEvent,
                                 'event_finish_with_failure')
        objects.InstanceActionEvent.event_start(
                self.context, self.instance.uuid, mox.IgnoreArg(),
                want_result=False)
        objects.InstanceActionEvent.event_finish_with_failure(
                self.context, self.instance.uuid, mox.IgnoreArg(),
                exc_val=mox.IgnoreArg(), exc_tb=mox.IgnoreArg(),
                want_result=False)

    @staticmethod
    def _assert_build_instance_hook_called(mock_hooks, result):
        # NOTE(coreywright): we want to test the return value of
        # _do_build_and_run_instance, but it doesn't bubble all the way up, so
        # mock the hooking, which allows us to test that too, though a little
        # too intimately
        mock_hooks.setdefault().run_post.assert_called_once_with(
            'build_instance', result, mock.ANY, mock.ANY, f=None)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_build_and_run_instance_called_with_proper_args(self, mock_spawn,
                                                            mock_hooks):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.ACTIVE)

    # This test when sending an icehouse compatible rpc call to juno compute
    # node, NetworkRequest object can load from three items tuple.
    @mock.patch('nova.objects.InstanceActionEvent.event_finish_with_failure')
    @mock.patch('nova.objects.InstanceActionEvent.event_start')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.compute.manager.ComputeManager._build_and_run_instance')
    @mock.patch('nova.utils.spawn_n')
    def test_build_and_run_instance_with_icehouse_requested_network(
            self, mock_spawn, mock_build_and_run, mock_save, mock_event_start,
            mock_event_finish):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        mock_save.return_value = self.instance
        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=[('fake_network_id', '10.0.0.1',
                                     'fake_port_id')],
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        requested_network = mock_build_and_run.call_args[0][5][0]
        self.assertEqual('fake_network_id', requested_network.network_id)
        self.assertEqual('10.0.0.1', str(requested_network.address))
        self.assertEqual('fake_port_id', requested_network.port_id)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_build_abort_exception(self, mock_spawn, mock_hooks):
        def fake_spawn(f, *args, **kwargs):
            # NOTE(danms): Simulate the detached nature of spawn so that
            # we confirm that the inner task has the fault logic
            try:
                return f(*args, **kwargs)
            except Exception:
                pass

        mock_spawn.side_effect = fake_spawn

        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                                 'build_instances')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties).AndRaise(
                        exception.BuildAbortException(reason='',
                            instance_uuid=self.instance.uuid))
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        self.compute._cleanup_volumes(self.context, self.instance.uuid,
                self.block_device_mapping, raise_exc=False)
        compute_utils.add_instance_fault_from_exc(self.context,
                self.instance, mox.IgnoreArg(), mox.IgnoreArg())
        self.compute._set_instance_error_state(self.context, self.instance)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.FAILED)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_rescheduled_exception(self, mock_spawn, mock_hooks):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                                 'build_instances')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance.uuid))
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)

    def test_rescheduled_exception_with_non_ascii_exception(self):
        exc = exception.NovaException(u's\xe9quence')
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._build_and_run_instance_update()
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info,
                flavor=None).AndRaise(exc)
        self._notify_about_instance_usage('create.error',
                fault=exc, stub=False)
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.RescheduledException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node,
                self.limits, self.filter_properties)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_rescheduled_exception_without_retry(self, mock_spawn, mock_hooks):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                {}).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance.uuid))
        self.compute._cleanup_allocated_networks(self.context, self.instance,
            self.requested_networks)
        compute_utils.add_instance_fault_from_exc(self.context, self.instance,
                mox.IgnoreArg(), mox.IgnoreArg())
        self.compute._set_instance_error_state(self.context,
                                               self.instance)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties={},
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.FAILED)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_rescheduled_exception_do_not_deallocate_network(self, mock_spawn,
                                                             mock_hooks):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'deallocate_networks_on_reschedule')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance.uuid))
        self.compute.driver.deallocate_networks_on_reschedule(
                self.instance).AndReturn(False)
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)

    @mock.patch('nova.hooks._HOOKS')
    @mock.patch('nova.utils.spawn_n')
    def test_rescheduled_exception_deallocate_network(self, mock_spawn,
                                                      mock_hooks):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'deallocate_networks_on_reschedule')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance.uuid))
        self.compute.driver.deallocate_networks_on_reschedule(
                self.instance).AndReturn(True)
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)

    def _test_build_and_run_exceptions(self, exc, set_error=False,
            cleanup_volumes=False):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties).AndRaise(exc)
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        if cleanup_volumes:
            self.compute._cleanup_volumes(self.context, self.instance.uuid,
                    self.block_device_mapping, raise_exc=False)
        if set_error:
            self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
            self.mox.StubOutWithMock(compute_utils,
                    'add_instance_fault_from_exc')
            compute_utils.add_instance_fault_from_exc(self.context,
                    self.instance, mox.IgnoreArg(), mox.IgnoreArg())
            self.compute._set_instance_error_state(self.context, self.instance)
        self._instance_action_events()
        self.mox.ReplayAll()

        with contextlib.nested(
            mock.patch('nova.utils.spawn_n'),
            mock.patch('nova.hooks._HOOKS')
        ) as (
            mock_spawn,
            mock_hooks
        ):
            mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
            self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
            self._assert_build_instance_hook_called(mock_hooks,
                                                    build_results.FAILED)

    def test_build_and_run_notfound_exception(self):
        self._test_build_and_run_exceptions(exception.InstanceNotFound(
            instance_id=''))

    def test_build_and_run_unexpecteddeleting_exception(self):
        self._test_build_and_run_exceptions(
                exception.UnexpectedDeletingTaskStateError(expected='',
                    actual=''))

    def test_build_and_run_buildabort_exception(self):
        self._test_build_and_run_exceptions(exception.BuildAbortException(
            instance_uuid='', reason=''), set_error=True, cleanup_volumes=True)

    def test_build_and_run_unhandled_exception(self):
        self._test_build_and_run_exceptions(test.TestingException(),
                set_error=True, cleanup_volumes=True)

    def test_instance_not_found(self):
        exc = exception.InstanceNotFound(instance_id=1)
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._build_and_run_instance_update()
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info,
                flavor=None).AndRaise(exc)
        self._notify_about_instance_usage('create.end',
                fault=exc, stub=False)
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance.uuid, mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceNotFound,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node,
                self.limits, self.filter_properties)

    def test_reschedule_on_exception(self):
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._build_and_run_instance_update()
        exc = test.TestingException()
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info,
                flavor=None).AndRaise(exc)
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance.uuid, mox.IgnoreArg(), 'conductor')
        self._notify_about_instance_usage('create.error',
            fault=exc, stub=False)
        self.mox.ReplayAll()

        self.assertRaises(exception.RescheduledException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node,
                self.limits, self.filter_properties)

    def test_spawn_network_alloc_failure(self):
        # Because network allocation is asynchronous, failures may not present
        # themselves until the virt spawn method is called.
        self._test_build_and_run_spawn_exceptions(exception.NoMoreNetworks())

    def test_build_and_run_flavor_disk_too_small_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.FlavorDiskTooSmall())

    def test_build_and_run_flavor_memory_too_small_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.FlavorMemoryTooSmall())

    def test_build_and_run_image_not_active_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.ImageNotActive(image_id=self.image.get('id')))

    def test_build_and_run_image_unacceptable_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.ImageUnacceptable(image_id=self.image.get('id'),
                                        reason=""))

    def _test_build_and_run_spawn_exceptions(self, exc):
        with contextlib.nested(
                mock.patch.object(self.compute.driver, 'spawn',
                    side_effect=exc),
                mock.patch.object(conductor_rpcapi.ConductorAPI,
                    'instance_update'),
                mock.patch.object(self.instance, 'save',
                    side_effect=[self.instance, self.instance]),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance',
                    return_value=self.network_info),
                mock.patch.object(self.compute,
                    '_notify_about_instance_usage'),
                mock.patch.object(self.compute,
                    '_shutdown_instance'),
                mock.patch.object(self.compute,
                    '_validate_instance_group_policy')
        ) as (spawn, instance_update, save,
                _build_networks_for_instance, _notify_about_instance_usage,
                _shutdown_instance, _validate_instance_group_policy):

            self.assertRaises(exception.BuildAbortException,
                    self.compute._build_and_run_instance, self.context,
                    self.instance, self.image, self.injected_files,
                    self.admin_pass, self.requested_networks,
                    self.security_groups, self.block_device_mapping, self.node,
                    self.limits, self.filter_properties)

            _validate_instance_group_policy.assert_called_once_with(
                    self.context, self.instance, self.filter_properties)
            _build_networks_for_instance.assert_has_calls(
                    mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups))

            _notify_about_instance_usage.assert_has_calls([
                mock.call(self.context, self.instance, 'create.start',
                    extra_usage_info={'image_name': self.image.get('name')}),
                mock.call(self.context, self.instance, 'create.error',
                    fault=exc)])

            save.assert_has_calls([
                mock.call(),
                mock.call(
                    expected_task_state=task_states.BLOCK_DEVICE_MAPPING)])

            spawn.assert_has_calls(mock.call(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info,
                flavor=None))

            instance_update.assert_has_calls(mock.call(self.context,
                self.instance.uuid, mock.ANY, 'conductor'))

            _shutdown_instance.assert_called_once_with(self.context,
                    self.instance, self.block_device_mapping,
                    self.requested_networks, try_deallocate_networks=False)

    @mock.patch('nova.compute.manager.ComputeManager._get_power_state')
    def test_spawn_waits_for_network_and_saves_info_cache(self, gps):
        inst = mock.MagicMock()
        network_info = mock.MagicMock()
        with mock.patch.object(self.compute, 'driver'):
            self.compute._spawn(self.context, inst, {}, network_info, None,
                                None, None, flavor=None)
        network_info.wait.assert_called_once_with(do_raise=True)
        self.assertEqual(network_info, inst.info_cache.network_info)
        inst.save.assert_called_with(expected_task_state=task_states.SPAWNING)

    @mock.patch('nova.utils.spawn_n')
    def test_reschedule_on_resources_unavailable(self, mock_spawn):
        mock_spawn.side_effect = lambda f, *a, **k: f(*a, **k)
        reason = 'resource unavailable'
        exc = exception.ComputeResourcesUnavailable(reason=reason)

        class FakeResourceTracker(object):
            def instance_claim(self, context, instance, limits):
                raise exc

        self.mox.StubOutWithMock(self.compute, '_get_resource_tracker')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.compute._get_resource_tracker(self.node).AndReturn(
            FakeResourceTracker())
        self._do_build_instance_update(reschedule_update=True)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._notify_about_instance_usage('create.error',
            fault=exc, stub=False)
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self._instance_action_events()
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_build_resources_buildabort_reraise(self):
        exc = exception.BuildAbortException(
                instance_uuid=self.instance.uuid, reason='')
        self.mox.StubOutWithMock(self.compute, '_build_resources')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance.uuid, mox.IgnoreArg(), 'conductor')
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self.compute._build_resources(self.context, self.instance,
                self.requested_networks, self.security_groups, self.image,
                self.block_device_mapping).AndRaise(exc)
        self._notify_about_instance_usage('create.error',
            fault=exc, stub=False)
        self.mox.ReplayAll()
        self.assertRaises(exception.BuildAbortException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks,
                self.security_groups, self.block_device_mapping, self.node,
                self.limits, self.filter_properties)

    def test_build_resources_reraises_on_failed_bdm_prep(self):
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self._build_resources_instance_update()
        self.compute._prep_block_device(self.context, self.instance,
                self.block_device_mapping).AndRaise(test.TestingException())
        self.mox.ReplayAll()

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                pass
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

    def test_failed_bdm_prep_from_delete_raises_unexpected(self):
        with contextlib.nested(
                mock.patch.object(self.compute,
                    '_build_networks_for_instance',
                    return_value=self.network_info),
                mock.patch.object(self.instance, 'save',
                    side_effect=exception.UnexpectedDeletingTaskStateError(
                        actual=task_states.DELETING, expected='None')),
        ) as (_build_networks_for_instance, save):

            try:
                with self.compute._build_resources(self.context, self.instance,
                        self.requested_networks, self.security_groups,
                        self.image, self.block_device_mapping):
                    pass
            except Exception as e:
                self.assertIsInstance(e,
                    exception.UnexpectedDeletingTaskStateError)

            _build_networks_for_instance.assert_has_calls(
                    mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups))

            save.assert_has_calls(mock.call())

    def test_build_resources_aborts_on_failed_network_alloc(self):
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndRaise(
                        test.TestingException())
        self.mox.ReplayAll()

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups, self.image,
                    self.block_device_mapping):
                pass
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

    def test_failed_network_alloc_from_delete_raises_unexpected(self):
        with mock.patch.object(self.compute,
                '_build_networks_for_instance') as _build_networks:

            exc = exception.UnexpectedDeletingTaskStateError
            _build_networks.side_effect = exc(actual=task_states.DELETING,
                    expected='None')

            try:
                with self.compute._build_resources(self.context, self.instance,
                        self.requested_networks, self.security_groups,
                        self.image, self.block_device_mapping):
                    pass
            except Exception as e:
                self.assertIsInstance(e, exc)

            _build_networks.assert_has_calls(
                    mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups))

    def test_build_resources_with_network_info_obj_on_spawn_failure(self):
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        network_model.NetworkInfo())
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)
        self._build_resources_instance_update()
        self.mox.ReplayAll()

        test_exception = test.TestingException()

        def fake_spawn():
            raise test_exception

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                fake_spawn()
        except Exception as e:
            self.assertEqual(test_exception, e)

    def test_build_resources_cleans_up_and_reraises_on_spawn_failure(self):
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)
        self._build_resources_instance_update()
        self.mox.ReplayAll()

        test_exception = test.TestingException()

        def fake_spawn():
            raise test_exception

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                fake_spawn()
        except Exception as e:
            self.assertEqual(test_exception, e)

    @mock.patch('nova.network.model.NetworkInfoAsyncWrapper.wait')
    @mock.patch(
        'nova.compute.manager.ComputeManager._build_networks_for_instance')
    @mock.patch('nova.objects.Instance.save')
    def test_build_resources_instance_not_found_before_yield(
            self, mock_save, mock_build_network, mock_info_wait):
        mock_build_network.return_value = self.network_info
        expected_exc = exception.InstanceNotFound(
            instance_id=self.instance.uuid)
        mock_save.side_effect = expected_exc
        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                raise
        except Exception as e:
            self.assertEqual(expected_exc, e)
        mock_build_network.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_info_wait.assert_called_once_with(do_raise=False)

    @mock.patch('nova.network.model.NetworkInfoAsyncWrapper.wait')
    @mock.patch(
        'nova.compute.manager.ComputeManager._build_networks_for_instance')
    @mock.patch('nova.objects.Instance.save')
    def test_build_resources_unexpected_task_error_before_yield(
            self, mock_save, mock_build_network, mock_info_wait):
        mock_build_network.return_value = self.network_info
        mock_save.side_effect = exception.UnexpectedTaskStateError(
            expected='', actual='')
        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                raise
        except exception.BuildAbortException:
            pass
        mock_build_network.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_info_wait.assert_called_once_with(do_raise=False)

    @mock.patch('nova.network.model.NetworkInfoAsyncWrapper.wait')
    @mock.patch(
        'nova.compute.manager.ComputeManager._build_networks_for_instance')
    @mock.patch('nova.objects.Instance.save')
    def test_build_resources_exception_before_yield(
            self, mock_save, mock_build_network, mock_info_wait):
        mock_build_network.return_value = self.network_info
        mock_save.side_effect = Exception()
        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                raise
        except exception.BuildAbortException:
            pass
        mock_build_network.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_info_wait.assert_called_once_with(do_raise=False)

    def test_build_resources_aborts_on_cleanup_failure(self):
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self.compute._shutdown_instance(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False).AndRaise(
                        test.TestingException())
        self._build_resources_instance_update()
        self.mox.ReplayAll()

        def fake_spawn():
            raise test.TestingException()

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                fake_spawn()
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_get_instance_nw_info_properly_queries_for_sysmeta(self,
                                                               mock_get):
        instance = objects.Instance(uuid=uuid.uuid4().hex)
        with mock.patch.object(self.compute, 'network_api'):
            self.compute._get_instance_nw_info(self.context, instance)
        mock_get.assert_called_once_with(self.context, instance.uuid,
                                         expected_attrs=['system_metadata'],
                                         use_slave=False)

    def test_build_networks_if_not_allocated(self):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata={},
                expected_attrs=['system_metadata'])

        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute, '_allocate_network')
        self.compute._allocate_network(self.context, instance,
                self.requested_networks, None, self.security_groups, None)
        self.mox.ReplayAll()

        self.compute._build_networks_for_instance(self.context, instance,
                self.requested_networks, self.security_groups)

    def test_build_networks_if_allocated_false(self):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata=dict(network_allocated='False'),
                expected_attrs=['system_metadata'])

        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute, '_allocate_network')
        self.compute._allocate_network(self.context, instance,
                self.requested_networks, None, self.security_groups, None)
        self.mox.ReplayAll()

        self.compute._build_networks_for_instance(self.context, instance,
                self.requested_networks, self.security_groups)

    def test_return_networks_if_found(self):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata=dict(network_allocated='True'),
                expected_attrs=['system_metadata'])

        def fake_network_info():
            return network_model.NetworkInfo([{'address': '123.123.123.123'}])

        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute, '_allocate_network')
        self.compute._get_instance_nw_info(self.context, instance).AndReturn(
                    network_model.NetworkInfoAsyncWrapper(fake_network_info))
        self.mox.ReplayAll()

        self.compute._build_networks_for_instance(self.context, instance,
                self.requested_networks, self.security_groups)

    def test_cleanup_allocated_networks_instance_not_found(self):
        with contextlib.nested(
                mock.patch.object(self.compute, '_deallocate_network'),
                mock.patch.object(self.instance, 'save',
                    side_effect=exception.InstanceNotFound(instance_id=''))
        ) as (_deallocate_network, save):
            # Testing that this doesn't raise an exeption
            self.compute._cleanup_allocated_networks(self.context,
                    self.instance, self.requested_networks)
            save.assert_called_once_with()
            self.assertEqual('False',
                    self.instance.system_metadata['network_allocated'])

    @mock.patch.object(conductor_rpcapi.ConductorAPI, 'instance_update')
    def test_launched_at_in_create_end_notification(self,
            mock_instance_update):

        def fake_notify(*args, **kwargs):
            if args[2] == 'create.end':
                # Check that launched_at is set on the instance
                self.assertIsNotNone(args[1].launched_at)

        with contextlib.nested(
                mock.patch.object(self.compute.driver, 'spawn'),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance', return_value=[]),
                mock.patch.object(self.instance, 'save'),
                mock.patch.object(self.compute, '_notify_about_instance_usage',
                    side_effect=fake_notify)
        ) as (mock_spawn, mock_networks, mock_save, mock_notify):
            self.compute._build_and_run_instance(self.context, self.instance,
                    self.image, self.injected_files, self.admin_pass,
                    self.requested_networks, self.security_groups,
                    self.block_device_mapping, self.node, self.limits,
                    self.filter_properties)
            expected_call = mock.call(self.context, self.instance,
                    'create.end', extra_usage_info={'message': u'Success'},
                    network_info=[])
            create_end_call = mock_notify.call_args_list[
                    mock_notify.call_count - 1]
            self.assertEqual(expected_call, create_end_call)

    @mock.patch.object(conductor_rpcapi.ConductorAPI, 'instance_update')
    def test_create_end_on_instance_delete(self, mock_instance_update):

        def fake_notify(*args, **kwargs):
            if args[2] == 'create.end':
                # Check that launched_at is set on the instance
                self.assertIsNotNone(args[1].launched_at)

        exc = exception.InstanceNotFound(instance_id='')

        with contextlib.nested(
                mock.patch.object(self.compute.driver, 'spawn'),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance', return_value=[]),
                mock.patch.object(self.instance, 'save',
                    side_effect=[None, None, exc]),
                mock.patch.object(self.compute, '_notify_about_instance_usage',
                    side_effect=fake_notify)
        ) as (mock_spawn, mock_networks, mock_save, mock_notify):
            self.assertRaises(exception.InstanceNotFound,
                    self.compute._build_and_run_instance, self.context,
                    self.instance, self.image, self.injected_files,
                    self.admin_pass, self.requested_networks,
                    self.security_groups, self.block_device_mapping, self.node,
                    self.limits, self.filter_properties)
            expected_call = mock.call(self.context, self.instance,
                    'create.end', fault=exc)
            create_end_call = mock_notify.call_args_list[
                    mock_notify.call_count - 1]
            self.assertEqual(expected_call, create_end_call)


class ComputeManagerMigrationTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerMigrationTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')
        self.image = {}
        self.instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.migration = objects.Migration(context=self.context.elevated())
        self.migration.status = 'migrating'

    def test_finish_resize_failure(self):
        with contextlib.nested(
            mock.patch.object(self.compute, '_finish_resize',
                              side_effect=exception.ResizeError(reason='')),
            mock.patch.object(objects.InstanceActionEvent, 'event_start'),
            mock.patch.object(objects.InstanceActionEvent,
                              'event_finish_with_failure'),
            mock.patch.object(db, 'instance_fault_create'),
            mock.patch.object(self.compute, '_instance_update'),
            mock.patch.object(self.migration, 'save'),
            mock.patch.object(self.migration, 'obj_as_admin',
                              return_value=mock.MagicMock())
        ) as (meth, event_start, event_finish, fault_create, instance_update,
              migration_save, migration_obj_as_admin):
            fault_create.return_value = (
                test_instance_fault.fake_faults['fake-uuid'][0])
            self.assertRaises(
                exception.ResizeError, self.compute.finish_resize,
                context=self.context, disk_info=[], image=self.image,
                instance=self.instance, reservations=[],
                migration=self.migration
            )
            self.assertEqual("error", self.migration.status)
            migration_save.assert_called_once_with()
            migration_obj_as_admin.assert_called_once_with()

    def test_resize_instance_failure(self):
        self.migration.dest_host = None
        with contextlib.nested(
            mock.patch.object(self.compute.driver,
                              'migrate_disk_and_power_off',
                              side_effect=exception.ResizeError(reason='')),
            mock.patch.object(objects.InstanceActionEvent, 'event_start'),
            mock.patch.object(objects.InstanceActionEvent,
                              'event_finish_with_failure'),
            mock.patch.object(db, 'instance_fault_create'),
            mock.patch.object(self.compute, '_instance_update'),
            mock.patch.object(self.migration, 'save'),
            mock.patch.object(self.migration, 'obj_as_admin',
                              return_value=mock.MagicMock()),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                              return_value=None),
            mock.patch.object(self.instance, 'save'),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute,
                              '_get_instance_block_device_info',
                              return_value=None),
            mock.patch.object(objects.BlockDeviceMappingList,
                              'get_by_instance_uuid',
                              return_value=None)
        ) as (meth, event_start, event_finish, fault_create, instance_update,
              migration_save, migration_obj_as_admin, nw_info, save_inst,
              notify, vol_block_info, bdm):
            fault_create.return_value = (
                test_instance_fault.fake_faults['fake-uuid'][0])
            self.assertRaises(
                exception.ResizeError, self.compute.resize_instance,
                context=self.context, instance=self.instance, image=self.image,
                reservations=[], migration=self.migration, instance_type='type'
            )
            self.assertEqual("error", self.migration.status)
            self.assertEqual([mock.call(), mock.call()],
                             migration_save.mock_calls)
            self.assertEqual([mock.call(), mock.call()],
                             migration_obj_as_admin.mock_calls)
