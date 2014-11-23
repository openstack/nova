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

from eventlet import event as eventlet_event
import mock
import mox
from oslo.config import cfg

from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import external_event as external_event_obj
from nova.objects import instance as instance_obj
from nova.objects import migration as migration_obj
from nova.openstack.common import importutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.compute import fake_resource_tracker
from nova.tests import fake_block_device
from nova.tests import fake_instance
from nova.tests.objects import test_instance_info_cache


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')


class ComputeManagerUnitTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerUnitTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')

    def test_allocate_network_succeeds_after_retries(self):
        self.flags(network_allocate_retries=8)

        nwapi = self.compute.network_api
        self.mox.StubOutWithMock(nwapi, 'allocate_for_instance')
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(time, 'sleep')

        instance = fake_instance.fake_db_instance(system_metadata={})
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
                                        mox.IsA(instance_obj.Instance))
            self.compute._init_instance(fake_context,
                                        mox.IsA(instance_obj.Instance))
            self.compute._init_instance(fake_context,
                                        mox.IsA(instance_obj.Instance))
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

    @mock.patch('nova.objects.instance.InstanceList')
    def test_cleanup_host(self, mock_instance_list):
        # just testing whether the cleanup_host method
        # when fired will invoke the underlying driver's
        # equivalent method.

        mock_instance_list.get_by_host.return_value = []

        with mock.patch.object(self.compute, 'driver') as mock_driver:
            self.compute.init_host()
            mock_driver.init_host.assert_called_once()

            self.compute.cleanup_host()
            mock_driver.cleanup_host.assert_called_once()

    def test_init_host_with_deleted_migration(self):
        our_host = self.compute.host
        not_our_host = 'not-' + our_host
        fake_context = 'fake-context'

        deleted_instance = instance_obj.Instance(host=not_our_host,
                                                 uuid='fake-uuid',
                                                 task_state=None)

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
        self.compute._set_instance_error_state(mox.IgnoreArg(),
                instance['uuid'])
        self.mox.ReplayAll()
        self.compute._init_instance('fake-context', instance)

    def test_init_instance_stuck_in_deleting(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='fake-uuid',
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=task_states.DELETING)

        self.mox.StubOutWithMock(block_device_obj.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(self.compute, '_delete_instance')
        self.mox.StubOutWithMock(instance, 'obj_load_attr')

        bdms = []
        instance.obj_load_attr('metadata')
        instance.obj_load_attr('system_metadata')
        block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, instance.uuid).AndReturn(bdms)
        self.compute._delete_instance(self.context, instance, bdms)

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
            {'state': power_state.SHUTDOWN})
        self.compute.driver.get_info(instance).AndReturn(
            {'state': power_state.SHUTDOWN})

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

    def test_init_instance_sets_building_error(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid='foo',
                vm_state=vm_states.BUILDING,
                task_state=None)
        with mock.patch.object(instance, 'save') as save:
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ERROR, instance.vm_state)

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
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.BLOCK_DEVICE_MAPPING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_networking(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.NETWORKING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_spawning(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = None
        instance.task_state = task_states.SPAWNING
        self._test_init_instance_sets_building_tasks_error(instance)

    def _test_init_instance_cleans_image_states(self, instance):
        with mock.patch.object(instance, 'save') as save:
            self.compute._get_power_state = mock.Mock()
            instance.info_cache = None
            instance.power_state = power_state.RUNNING
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
        self.assertIsNone(instance.task_state)

    def test_init_instance_cleans_image_state_pending_upload(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_PENDING_UPLOAD
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_uploading(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_UPLOADING
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot_pending(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT_PENDING
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_errors_when_not_migrating(self):
        instance = instance_obj.Instance(self.context)
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
        self.mox.StubOutWithMock(block_device_obj.BlockDeviceMappingList,
                                 'get_by_instance_uuid')
        self.mox.StubOutWithMock(self.compute, '_delete_instance')
        self.mox.StubOutWithMock(instance, 'obj_load_attr')

        bdms = []
        instance.obj_load_attr('metadata')
        instance.obj_load_attr('system_metadata')
        block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, instance.uuid).AndReturn(bdms)
        self.compute._delete_instance(self.context, instance, bdms)
        self.mox.ReplayAll()

        self.compute._init_instance(self.context, instance)
        self.mox.VerifyAll()

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
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_PENDING
        for state in vm_states.ALLOW_SOFT_REBOOT:
            instance.vm_state = state
            self._test_init_instance_retries_reboot(instance, 'SOFT',
                                                    power_state.RUNNING)

    def test_init_instance_retries_reboot_pending_hard(self):
        instance = instance_obj.Instance(self.context)
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
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        self._test_init_instance_retries_reboot(instance, 'HARD',
                                                power_state.NOSTATE)

    def test_init_instance_retries_reboot_started_hard(self):
        instance = instance_obj.Instance(self.context)
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
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

    def test_init_instance_cleans_image_state_reboot_started_hard(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED_HARD
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

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
        instances = [{'uuid': 'foo'}]
        self.flags(instance_usage_audit=True)
        self.stubs.Set(compute_utils, 'has_audit_been_run',
                       lambda *a, **k: False)
        self.stubs.Set(self.compute.conductor_api,
                       'instance_get_active_by_window_joined',
                       lambda *a, **k: instances)
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

    def _get_sync_instance(self, power_state, vm_state, task_state=None):
        instance = instance_obj.Instance()
        instance.uuid = 'fake-uuid'
        instance.power_state = power_state
        instance.vm_state = vm_state
        instance.host = self.compute.host
        instance.task_state = task_state
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
                           stop=True, force=False):
        instance = self._get_sync_instance(power_state, vm_state)
        instance.refresh(use_slave=False)
        instance.save()
        self.mox.StubOutWithMock(self.compute.compute_api, 'stop')
        self.mox.StubOutWithMock(self.compute.compute_api, 'force_stop')
        if stop:
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

    def test_sync_instance_power_state_to_no_stop(self):
        for ps in (power_state.PAUSED, power_state.NOSTATE):
            self._test_sync_to_stop(power_state.RUNNING, vm_states.ACTIVE, ps,
                                    stop=False)
        for vs in (vm_states.SOFT_DELETED, vm_states.DELETED):
            for ps in (power_state.NOSTATE, power_state.SHUTDOWN):
                self._test_sync_to_stop(power_state.RUNNING, vs, ps,
                                        stop=False)

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

            def save(self, context):
                pass

        class FakeInstanceList(object):
            def get_by_filters(self, *args, **kwargs):
                return []

        a = FakeInstance('123', 'apple', {'clean_attempts': '100'})
        b = FakeInstance('456', 'orange', {'clean_attempts': '3'})
        c = FakeInstance('789', 'banana', {})

        self.mox.StubOutWithMock(instance_obj.InstanceList,
                                 'get_by_filters')
        instance_obj.InstanceList.get_by_filters(
            {'read_deleted': 'yes'},
            {'deleted': True, 'soft_deleted': False, 'host': 'fake-mini',
             'cleaned': False},
            expected_attrs=['info_cache', 'security_groups',
                            'system_metadata']).AndReturn([a, b, c])

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

    def test_swap_volume_volume_api_usage(self):
        # This test ensures that volume_id arguments are passed to volume_api
        # and that volume states are OK
        volumes = {}
        old_volume_id = uuidutils.generate_uuid()
        volumes[old_volume_id] = {'id': old_volume_id,
                                  'display_name': 'old_volume',
                                  'status': 'detaching'}
        new_volume_id = uuidutils.generate_uuid()
        volumes[new_volume_id] = {'id': new_volume_id,
                                  'display_name': 'new_volume',
                                  'status': 'available'}

        def fake_vol_api_begin_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            volumes[volume_id]['status'] = 'detaching'

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

        def fake_vol_attach(context, volume_id, instance_uuid, connector):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            self.assertIn(volumes[volume_id]['status'],
                          ['available', 'attaching'])
            volumes[volume_id]['status'] = 'in-use'

        def fake_vol_api_reserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            self.assertEqual(volumes[volume_id]['status'], 'available')
            volumes[volume_id]['status'] = 'attaching'

        def fake_vol_unreserve(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'attaching':
                volumes[volume_id]['status'] = 'available'

        def fake_vol_detach(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            volumes[volume_id]['status'] = 'available'

        def fake_vol_migrate_volume_completion(context, old_volume_id,
                                               new_volume_id, error=False):
            self.assertTrue(uuidutils.is_uuid_like(old_volume_id))
            self.assertTrue(uuidutils.is_uuid_like(old_volume_id))
            return {'save_volume_id': new_volume_id}

        def fake_func_exc(*args, **kwargs):
            raise AttributeError  # Random exception

        self.stubs.Set(self.compute.volume_api, 'begin_detaching',
                       fake_vol_api_begin_detaching)
        self.stubs.Set(self.compute.volume_api, 'roll_detaching',
                       fake_vol_api_roll_detaching)
        self.stubs.Set(self.compute.volume_api, 'get', fake_vol_get)
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       fake_vol_api_func)
        self.stubs.Set(self.compute.volume_api, 'attach', fake_vol_attach)
        self.stubs.Set(self.compute.volume_api, 'reserve_volume',
                       fake_vol_api_reserve)
        self.stubs.Set(self.compute.volume_api, 'unreserve_volume',
                       fake_vol_unreserve)
        self.stubs.Set(self.compute.volume_api, 'terminate_connection',
                       fake_vol_api_func)
        self.stubs.Set(self.compute.volume_api, 'detach', fake_vol_detach)
        self.stubs.Set(db, 'block_device_mapping_get_by_volume_id',
                       lambda x, y, z: fake_bdm)
        self.stubs.Set(self.compute.driver, 'get_volume_connector',
                       lambda x: {})
        self.stubs.Set(self.compute.driver, 'swap_volume',
                       lambda w, x, y, z: None)
        self.stubs.Set(self.compute.volume_api, 'migrate_volume_completion',
                      fake_vol_migrate_volume_completion)
        self.stubs.Set(db, 'block_device_mapping_update',
                       lambda *a, **k: fake_bdm)
        self.stubs.Set(self.compute.conductor_api,
                       'instance_fault_create',
                       lambda x, y: None)

        # Good path
        self.compute.swap_volume(self.context, old_volume_id, new_volume_id,
                fake_instance.fake_instance_obj(
                    self.context, **{'uuid': 'fake'}))
        self.assertEqual(volumes[old_volume_id]['status'], 'available')
        self.assertEqual(volumes[new_volume_id]['status'], 'in-use')

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
        bdms = 'bdms'
        dest_check_data = dict(foo='bar')
        db_instance = fake_instance.fake_db_instance()
        instance = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), db_instance)
        expected_dest_check_data = dict(dest_check_data,
                                        is_volume_backed=is_volume_backed)

        self.mox.StubOutWithMock(self.compute.compute_api,
                                 'is_volume_backed_instance')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_source')

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.compute_api.is_volume_backed_instance(
                self.context, instance).AndReturn(is_volume_backed)
        self.compute.driver.check_can_live_migrate_source(
                self.context, instance, expected_dest_check_data)

        self.mox.ReplayAll()

        self.compute.check_can_live_migrate_source(
                self.context, instance=instance,
                dest_check_data=dest_check_data)

    def _test_check_can_live_migrate_destination(self, do_raise=False,
                                                 has_mig_data=False):
        db_instance = fake_instance.fake_db_instance(host='fake-host')
        instance = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), db_instance)
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
            self.mox.StubOutWithMock(self.compute.conductor_api,
                    'instance_fault_create')
            self.compute.conductor_api.instance_fault_create(self.context,
                    mox.IgnoreArg())
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

    def test_prepare_for_instance_event(self):
        inst_obj = instance_obj.Instance(uuid='foo')
        result = self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event')
        self.assertIn('foo', self.compute.instance_events._events)
        self.assertIn('test-event',
                      self.compute.instance_events._events['foo'])
        self.assertEqual(
            result,
            self.compute.instance_events._events['foo']['test-event'])
        self.assertTrue(hasattr(result, 'send'))

    def test_prepare_for_instance_event_again(self):
        inst_obj = instance_obj.Instance(uuid='foo')
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
        inst_obj = instance_obj.Instance(uuid='foo')
        event_obj = external_event_obj.InstanceExternalEvent(name='test-event',
                                                             tag=None)
        self.compute._process_instance_event(inst_obj, event_obj)
        self.assertTrue(event.ready())
        self.assertEqual(event_obj, event.wait())
        self.assertEqual({}, self.compute.instance_events._events)

    def test_external_instance_event(self):
        instances = [
            instance_obj.Instance(uuid='uuid1'),
            instance_obj.Instance(uuid='uuid2')]
        events = [
            external_event_obj.InstanceExternalEvent(name='network-changed',
                                                     instance_uuid='uuid1'),
            external_event_obj.InstanceExternalEvent(name='foo',
                                                     instance_uuid='uuid2')]

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
        instance = instance_obj.Instance(self.context)
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
        instance = instance_obj.Instance(self.context)
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
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.NOSTATE):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_off(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED_HARD
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.NOSTATE):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertTrue(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_on(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = task_states.REBOOT_STARTED_HARD
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertFalse(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_no_reboot(self):
        instance = instance_obj.Instance(self.context)
        instance.uuid = 'foo'
        instance.task_state = 'bar'
        with mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING):
            allow_reboot, reboot_type = self.compute._retry_reboot(
                                                             context, instance)
            self.assertFalse(allow_reboot)
            self.assertEqual(reboot_type, 'HARD')

    def test_init_host_with_partial_migration(self):
        our_host = self.compute.host
        instance_1 = instance_obj.Instance(self.context)
        instance_1.uuid = 'foo'
        instance_1.task_state = task_states.MIGRATING
        instance_1.host = 'not-' + our_host
        instance_2 = instance_obj.Instance(self.context)
        instance_2.uuid = 'bar'
        instance_2.task_state = None
        instance_2.host = 'not-' + our_host

        with contextlib.nested(
            mock.patch.object(self.compute, '_get_instances_on_driver',
                               return_value=[instance_1,
                                             instance_2]),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                               return_value=None),
            mock.patch.object(self.compute,
                              '_get_instance_block_device_info',
                               return_value={}),
            mock.patch.object(self.compute, '_is_instance_storage_shared',
                               return_value=False),
            mock.patch.object(self.compute.driver, 'destroy')
        ) as (_get_instances_on_driver, _get_instance_nw_info,
              _get_instance_block_device_info,
              _is_instance_storage_shared, destroy):
            self.compute._destroy_evacuated_instances(self.context)
            destroy.assert_called_once_with(self.context, instance_2, None,
                                            {}, True)

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
            mock.patch.object(objects.instance.Instance, 'save',
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

    def test_build_and_run_instance_called_with_proper_args(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_build_abort_exception(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                                 'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits).AndRaise(
                        exception.BuildAbortException(reason='',
                            instance_uuid=self.instance['uuid']))
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        self.compute._set_instance_error_state(self.context,
                self.instance['uuid'])
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_rescheduled_exception(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                                 'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance['uuid']))
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_rescheduled_exception_do_not_deallocate_network(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance['uuid']))
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_rescheduled_exception_deallocate_network_if_dhcp(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute.driver,
                'dhcp_options_for_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update(reschedule_update=True)
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits).AndRaise(
                        exception.RescheduledException(reason='',
                            instance_uuid=self.instance['uuid']))
        self.compute.driver.dhcp_options_for_instance(self.instance).AndReturn(
                {'fake': 'options'})
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def _test_build_and_run_exceptions(self, exc, set_error=False):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_allocated_networks')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self._do_build_instance_update()
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits).AndRaise(
                        exc)
        self.compute._cleanup_allocated_networks(self.context, self.instance,
                self.requested_networks)
        if set_error:
            self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
            self.compute._set_instance_error_state(self.context,
                    self.instance['uuid'])
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)
        self.mox.UnsetStubs()

    def test_build_and_run_instance_exceptions(self):
        exceptions = [
                exception.InstanceNotFound(instance_id=''),
                exception.UnexpectedDeletingTaskStateError(expected='',
                    actual='')]
        error_exceptions = [
                exception.BuildAbortException(instance_uuid='', reason=''),
                test.TestingException()]

        for exc in exceptions:
            self._test_build_and_run_exceptions(exc)
        for exc in error_exceptions:
            self._test_build_and_run_exceptions(exc, set_error=True)

    def test_instance_not_found(self):
        exc = exception.InstanceNotFound(instance_id=1)
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._build_and_run_instance_update()
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info).AndRaise(exc)
        self._notify_about_instance_usage('create.end',
                fault=exc, stub=False)
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceNotFound,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node,
                self.limits)

    def test_reschedule_on_exception(self):
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._build_and_run_instance_update()
        exc = test.TestingException()
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass,
                network_info=self.network_info,
                block_device_info=self.block_device_info).AndRaise(exc)
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self._notify_about_instance_usage('create.error',
            fault=exc, stub=False)
        self.mox.ReplayAll()

        self.assertRaises(exception.RescheduledException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node,
                self.limits)

    def test_spawn_network_alloc_failure(self):
        # Because network allocation is asynchronous, failures may not present
        # themselves until the virt spawn method is called.
        exc = exception.NoMoreNetworks()
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
                    '_notify_about_instance_usage')
        ) as (spawn, instance_update, save,
                _build_networks_for_instance, _notify_about_instance_usage):

            self.assertRaises(exception.BuildAbortException,
                    self.compute._build_and_run_instance, self.context,
                    self.instance, self.image, self.injected_files,
                    self.admin_pass, self.requested_networks,
                    self.security_groups, self.block_device_mapping, self.node,
                    self.limits)

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
                block_device_info=self.block_device_info))

            instance_update.assert_has_calls(mock.call(self.context,
                self.instance['uuid'], mock.ANY, 'conductor'))

    @mock.patch('nova.compute.manager.ComputeManager._get_power_state')
    def test_spawn_waits_for_network_and_saves_info_cache(self, gps):
        inst = mock.MagicMock()
        network_info = mock.MagicMock()
        with mock.patch.object(self.compute, 'driver'):
            self.compute._spawn(self.context, inst, {}, network_info, None,
                                None, None)
        network_info.wait.assert_called_once_with(do_raise=True)
        self.assertEqual(network_info, inst.info_cache.network_info)
        inst.save.assert_called_with(expected_task_state=task_states.SPAWNING)

    def test_reschedule_on_resources_unavailable(self):
        reason = 'resource unavailable'
        exc = exception.ComputeResourcesUnavailable(reason=reason)

        class FakeResourceTracker(object):
            def instance_claim(self, context, instance, limits):
                raise exc

        self.mox.StubOutWithMock(self.compute, '_get_resource_tracker')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self.compute._get_resource_tracker(self.node).AndReturn(
            FakeResourceTracker())
        self._do_build_instance_update(reschedule_update=True)
        self._notify_about_instance_usage('create.start',
            extra_usage_info={'image_name': self.image.get('name')})
        self._notify_about_instance_usage('create.error',
            fault=exc, stub=False)
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits)

    def test_build_resources_buildabort_reraise(self):
        exc = exception.BuildAbortException(
                instance_uuid=self.instance['uuid'], reason='')
        self.mox.StubOutWithMock(self.compute, '_build_resources')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
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
                self.limits)

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

    def test_build_resources_cleans_up_and_reraises_on_spawn_failure(self):
        self.mox.StubOutWithMock(self.compute, '_cleanup_build_resources')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self._build_resources_instance_update()
        self.compute._cleanup_build_resources(self.context, self.instance,
                self.block_device_mapping)
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

    def test_build_resources_aborts_on_cleanup_failure(self):
        self.mox.StubOutWithMock(self.compute, '_cleanup_build_resources')
        self.mox.StubOutWithMock(self.compute, '_build_networks_for_instance')
        self.compute._build_networks_for_instance(self.context, self.instance,
                self.requested_networks, self.security_groups).AndReturn(
                        self.network_info)
        self._build_resources_instance_update()
        self.compute._cleanup_build_resources(self.context, self.instance,
                self.block_device_mapping).AndRaise(test.TestingException())
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

    def test_cleanup_cleans_volumes(self):
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.compute._cleanup_volumes(self.context, self.instance['uuid'],
                self.block_device_mapping)
        self.mox.ReplayAll()

        self.compute._cleanup_build_resources(self.context, self.instance,
                self.block_device_mapping)

    def test_cleanup_reraises_volume_cleanup_failure(self):
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.compute._cleanup_volumes(self.context, self.instance['uuid'],
                self.block_device_mapping).AndRaise(test.TestingException())
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                self.compute._cleanup_build_resources, self.context,
                self.instance, self.block_device_mapping)

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


class ComputeManagerMigrationTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerMigrationTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')
        self.image = {}
        self.instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.migration = migration_obj.Migration()
        self.migration.status = 'migrating'

    def test_finish_resize_failure(self):
        elevated_context = self.context.elevated()
        with contextlib.nested(
            mock.patch.object(self.compute, '_finish_resize',
                              side_effect=exception.ResizeError(reason='')),
            mock.patch.object(self.compute.conductor_api,
                              'action_event_start'),
            mock.patch.object(self.compute.conductor_api,
                              'action_event_finish'),
            mock.patch.object(self.compute.conductor_api,
                              'instance_fault_create'),
            mock.patch.object(self.compute, '_instance_update'),
            mock.patch.object(self.migration, 'save'),
            mock.patch.object(self.context, 'elevated',
                              return_value=elevated_context)
        ) as (meth, event_start, event_finish, fault_create, instance_update,
              migration_save, context_elevated):
            self.assertRaises(
                exception.ResizeError, self.compute.finish_resize,
                context=self.context, disk_info=[], image=self.image,
                instance=self.instance, reservations=[],
                migration=self.migration
            )
            self.assertEqual("error", self.migration.status)
            migration_save.assert_has_calls([mock.call(elevated_context)])

    def test_resize_instance_failure(self):
        elevated_context = self.context.elevated()
        self.migration.dest_host = None
        with contextlib.nested(
            mock.patch.object(self.compute.driver,
                              'migrate_disk_and_power_off',
                              side_effect=exception.ResizeError(reason='')),
            mock.patch.object(self.compute.conductor_api,
                              'action_event_start'),
            mock.patch.object(self.compute.conductor_api,
                              'action_event_finish'),
            mock.patch.object(self.compute.conductor_api,
                              'instance_fault_create'),
            mock.patch.object(self.compute, '_instance_update'),
            mock.patch.object(self.migration, 'save'),
            mock.patch.object(self.context, 'elevated',
                              return_value=elevated_context),
            mock.patch.object(self.compute, '_get_instance_nw_info',
                              return_value=None),
            mock.patch.object(self.instance, 'save'),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute,
                              '_get_instance_block_device_info',
                              return_value=None),
            mock.patch.object(block_device_obj.BlockDeviceMappingList,
                              'get_by_instance_uuid',
                              return_value=None)
        ) as (meth, event_start, event_finish, fault_create, instance_update,
              migration_save, context_elevated, nw_info, save_inst, notify,
              vol_block_info, bdm):
            self.assertRaises(
                exception.ResizeError, self.compute.resize_instance,
                context=self.context, instance=self.instance, image=self.image,
                reservations=[], migration=self.migration, instance_type='type'
            )
            self.assertEqual("error", self.migration.status)
            migration_save.assert_has_calls([mock.call(elevated_context)])
