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

import time

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
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.openstack.common import importutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.compute import fake_resource_tracker
from nova.tests import fake_instance
from nova import utils


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
        self.mox.StubOutWithMock(time, 'sleep')

        instance = {}
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
                    conductor_api=self.compute.conductor_api,
                    security_groups=sec_groups,
                    dhcp_options=dhcp_options).AndRaise(
                            test.TestingException())
            time.sleep(sleep_time)

        nwapi.allocate_for_instance(
                self.context, instance, vpn=is_vpn,
                requested_networks=req_networks, macs=macs,
                conductor_api=self.compute.conductor_api,
                security_groups=sec_groups,
                dhcp_options=dhcp_options).AndReturn(final_result)

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
                conductor_api=self.compute.conductor_api,
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
                conductor_api=self.compute.conductor_api,
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
                info_cache={'instance_uuid': 'fake-uuid',
                            'network_info': None},
                security_groups=None)
        startup_instances = [inst, inst, inst]

        def _do_mock_calls(defer_iptables_apply):
            self.compute.driver.init_host(host=our_host)
            context.get_admin_context().AndReturn(fake_context)
            db.instance_get_all_by_host(
                    fake_context, our_host, columns_to_join=['info_cache']
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

    def test_init_host_with_deleted_migration(self):
        our_host = self.compute.host
        not_our_host = 'not-' + our_host
        fake_context = 'fake-context'

        deleted_instance = {
            'name': 'fake-name',
            'host': not_our_host,
            'uuid': 'fake-uuid',
            }

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
                                    columns_to_join=['info_cache']
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
        self.compute.driver.destroy(deleted_instance,
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

        self.mox.ReplayAll()
        self.compute.init_host()
        # tearDown() uses context.get_admin_context(), so we have
        # to do the verification here and unstub it.
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def test_init_instance_failed_resume_sets_error(self):
        instance = {
            'uuid': 'fake-uuid',
            'info_cache': None,
            'power_state': power_state.RUNNING,
            'vm_state': vm_states.ACTIVE,
            'task_state': None,
        }
        self.flags(resume_guests_state_on_host_boot=True)
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'resume_state_on_host_boot')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_set_instance_error_state')
        self.compute._get_power_state(mox.IgnoreArg(),
                instance).AndReturn(power_state.SHUTDOWN)
        self.compute.driver.plug_vifs(instance, mox.IgnoreArg())
        self.compute._get_instance_volume_block_device_info(mox.IgnoreArg(),
                instance).AndReturn('fake-bdm')
        self.compute.driver.resume_state_on_host_boot(mox.IgnoreArg(),
                instance, mox.IgnoreArg(),
                'fake-bdm').AndRaise(test.TestingException)
        self.compute._set_instance_error_state(mox.IgnoreArg(),
                instance['uuid'])
        self.mox.ReplayAll()
        self.compute._init_instance('fake-context', instance)

    def _test_init_instance_reverts_crashed_migrations(self,
                                                       old_vm_state=None):
        power_on = True if (not old_vm_state or
                            old_vm_state == vm_states.ACTIVE) else False
        sys_meta = {
            'old_vm_state': old_vm_state
            }
        instance = {
            'uuid': 'foo',
            'vm_state': vm_states.ERROR,
            'task_state': task_states.RESIZE_MIGRATING,
            'power_state': power_state.SHUTDOWN,
            'system_metadata': sys_meta
            }
        fixed = dict(instance, task_state=None)
        self.mox.StubOutWithMock(compute_utils, 'get_nw_info_for_instance')
        self.mox.StubOutWithMock(utils, 'instance_sys_meta')
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'finish_revert_migration')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute.driver, 'get_info')
        self.mox.StubOutWithMock(self.compute, '_instance_update')

        compute_utils.get_nw_info_for_instance(instance).AndReturn(
            network_model.NetworkInfo())
        self.compute.driver.plug_vifs(instance, [])
        utils.instance_sys_meta(instance).AndReturn(sys_meta)
        self.compute._get_instance_volume_block_device_info(
            self.context, instance).AndReturn([])
        self.compute.driver.finish_revert_migration(instance, [], [], power_on)
        self.compute._instance_update(self.context, instance['uuid'],
                                      task_state=None).AndReturn(fixed)
        self.compute.driver.get_info(fixed).AndReturn(
            {'state': power_state.SHUTDOWN})

        self.mox.ReplayAll()

        self.compute._init_instance(self.context, instance)

    def test_init_instance_reverts_crashed_migration_from_active(self):
        self._test_init_instance_reverts_crashed_migrations(
                                                old_vm_state=vm_states.ACTIVE)

    def test_init_instance_reverts_crashed_migration_from_stopped(self):
        self._test_init_instance_reverts_crashed_migrations(
                                                old_vm_state=vm_states.STOPPED)

    def test_init_instance_reverts_crashed_migration_no_old_state(self):
        self._test_init_instance_reverts_crashed_migrations(old_vm_state=None)

    def test_get_instances_on_driver(self):
        fake_context = context.get_admin_context()

        driver_instances = []
        for x in xrange(10):
            instance = dict(uuid=uuidutils.generate_uuid())
            driver_instances.append(instance)

        self.mox.StubOutWithMock(self.compute.driver,
                'list_instance_uuids')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                'instance_get_all_by_filters')

        self.compute.driver.list_instance_uuids().AndReturn(
                [inst['uuid'] for inst in driver_instances])
        self.compute.conductor_api.instance_get_all_by_filters(
                fake_context,
                {'uuid': [inst['uuid'] for
                          inst in driver_instances]},
                columns_to_join=[]).AndReturn(
                        driver_instances)

        self.mox.ReplayAll()

        result = self.compute._get_instances_on_driver(fake_context,
                                                       columns_to_join=[])
        self.assertEqual(driver_instances, result)

    def test_get_instances_on_driver_fallback(self):
        # Test getting instances when driver doesn't support
        # 'list_instance_uuids'
        self.compute.host = 'host'
        filters = {'host': self.compute.host}
        fake_context = context.get_admin_context()

        all_instances = []
        driver_instances = []
        for x in xrange(10):
            instance = dict(name=uuidutils.generate_uuid())
            if x % 2:
                driver_instances.append(instance)
            all_instances.append(instance)

        self.mox.StubOutWithMock(self.compute.driver,
                'list_instance_uuids')
        self.mox.StubOutWithMock(self.compute.driver,
                'list_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                'instance_get_all_by_filters')

        self.compute.driver.list_instance_uuids().AndRaise(
                NotImplementedError())
        self.compute.driver.list_instances().AndReturn(
                [inst['name'] for inst in driver_instances])
        self.compute.conductor_api.instance_get_all_by_filters(
                fake_context, filters,
                columns_to_join=None).AndReturn(all_instances)

        self.mox.ReplayAll()

        result = self.compute._get_instances_on_driver(fake_context, filters)
        self.assertEqual(driver_instances, result)

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
        instance.refresh()
        self.mox.ReplayAll()
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.RUNNING)

    def test_sync_instance_power_state_running_stopped(self):
        instance = self._get_sync_instance(power_state.RUNNING,
                                           vm_states.ACTIVE)
        instance.refresh()
        instance.save()
        self.mox.ReplayAll()
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.SHUTDOWN)
        self.assertEqual(instance.power_state, power_state.SHUTDOWN)

    def _test_sync_to_stop(self, power_state, vm_state, driver_power_state,
                           stop=True, force=False):
        instance = self._get_sync_instance(power_state, vm_state)
        instance.refresh()
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
                                  'status': 'attaching'}

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

        self.stubs.Set(self.compute.volume_api, 'get', fake_vol_get)
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       fake_vol_api_func)
        self.stubs.Set(self.compute.volume_api, 'attach', fake_vol_attach)
        self.stubs.Set(self.compute.volume_api, 'unreserve_volume',
                       fake_vol_unreserve)
        self.stubs.Set(self.compute.volume_api, 'terminate_connection',
                       fake_vol_api_func)
        self.stubs.Set(self.compute.volume_api, 'detach', fake_vol_detach)
        self.stubs.Set(self.compute, '_get_instance_volume_bdm',
                       lambda x, y, z: {'device_name': '/dev/vdb',
                                        'connection_info': '{"foo": "bar"}'})
        self.stubs.Set(self.compute.driver, 'get_volume_connector',
                       lambda x: {})
        self.stubs.Set(self.compute.driver, 'swap_volume',
                       lambda w, x, y, z: None)
        self.stubs.Set(self.compute.volume_api, 'migrate_volume_completion',
                      fake_vol_migrate_volume_completion)
        self.stubs.Set(self.compute.conductor_api,
                       'block_device_mapping_update_or_create',
                       lambda x, y: None)
        self.stubs.Set(self.compute.conductor_api,
                       'instance_fault_create',
                       lambda x, y: None)

        # Good path
        self.compute.swap_volume(self.context, old_volume_id, new_volume_id,
                                 {'uuid': 'fake'})
        self.assertEqual(volumes[old_volume_id]['status'], 'available')
        self.assertEqual(volumes[new_volume_id]['status'], 'in-use')

        # Error paths
        volumes[old_volume_id]['status'] = 'detaching'
        volumes[new_volume_id]['status'] = 'attaching'
        self.stubs.Set(self.compute.driver, 'swap_volume', fake_func_exc)
        self.assertRaises(AttributeError, self.compute.swap_volume,
                          self.context, old_volume_id, new_volume_id,
                          {'uuid': 'fake'})
        self.assertEqual(volumes[old_volume_id]['status'], 'detaching')
        self.assertEqual(volumes[new_volume_id]['status'], 'attaching')

        volumes[old_volume_id]['status'] = 'detaching'
        volumes[new_volume_id]['status'] = 'attaching'
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       fake_func_exc)
        self.assertRaises(AttributeError, self.compute.swap_volume,
                          self.context, old_volume_id, new_volume_id,
                          {'uuid': 'fake'})
        self.assertEqual(volumes[old_volume_id]['status'], 'detaching')
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

        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.compute.compute_api,
                                 'is_volume_backed_instance')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_source')

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.conductor_api.block_device_mapping_get_all_by_instance(
                self.context, instance_p).AndReturn(bdms)
        self.compute.compute_api.is_volume_backed_instance(
                self.context, instance, bdms).AndReturn(is_volume_backed)
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


class ComputeManagerBuildInstanceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerBuildInstanceTestCase, self).setUp()
        self.compute = importutils.import_object(CONF.compute_manager)
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_instance.fake_db_instance(
                vm_state=vm_states.ACTIVE)
        self.admin_pass = 'pass'
        self.injected_files = []
        self.image = {}
        self.node = 'fake-node'
        self.limits = {}

        # override tracker with a version that doesn't need the database:
        fake_rt = fake_resource_tracker.FakeResourceTracker(self.compute.host,
                    self.compute.driver, self.node)
        self.compute._resource_tracker_dict[self.node] = fake_rt

    def test_build_and_run_instance_called_with_proper_args(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass, self.node,
                self.limits)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass, node=self.node,
                limits=self.limits)

    def test_build_abort_exception(self):
        self.mox.StubOutWithMock(self.compute, '_build_and_run_instance')
        self.mox.StubOutWithMock(self.compute, '_set_instance_error_state')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                                 'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass, self.node,
                self.limits).AndRaise(exception.BuildAbortException(reason='',
                            instance_uuid=self.instance['uuid']))
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
                admin_password=self.admin_pass, node=self.node,
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
        self.compute._build_and_run_instance(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass, self.node,
                self.limits).AndRaise(exception.RescheduledException(reason='',
                            instance_uuid=self.instance['uuid']))
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, None, None, None)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass, node=self.node,
                limits=self.limits)

    def test_instance_not_found(self):
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass).AndRaise(
                        exception.InstanceNotFound(instance_id=1))
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.BuildAbortException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.node, self.limits)

    def test_reschedule_on_exception(self):
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass).AndRaise(
                        test.TestingException())
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.RescheduledException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.node, self.limits)

    def test_unexpected_task_state(self):
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.mox.StubOutWithMock(conductor_rpcapi.ConductorAPI,
                                 'instance_update')
        self.compute.driver.spawn(self.context, self.instance, self.image,
                self.injected_files, self.admin_pass).AndRaise(
                        exception.UnexpectedTaskStateError(expected=None,
                            actual='deleting'))
        conductor_rpcapi.ConductorAPI.instance_update(
            self.context, self.instance['uuid'], mox.IgnoreArg(), 'conductor')
        self.mox.ReplayAll()

        self.assertRaises(exception.BuildAbortException,
                self.compute._build_and_run_instance, self.context,
                self.instance, self.image, self.injected_files,
                self.admin_pass, self.node, self.limits)

    def test_reschedule_on_resources_unavailable(self):
        class FakeResourceTracker(object):
            def instance_claim(self, context, instance, limits):
                raise exception.ComputeResourcesUnavailable

        self.mox.StubOutWithMock(self.compute, '_get_resource_tracker')
        self.mox.StubOutWithMock(self.compute.compute_task_api,
                'build_instances')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_start')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'action_event_finish')
        self.compute._get_resource_tracker('node').AndReturn(
                FakeResourceTracker())
        self.compute.compute_task_api.build_instances(self.context,
                [self.instance], self.image, [], self.admin_pass,
                self.injected_files, None, None, None)
        self.compute.conductor_api.action_event_start(self.context,
                                                      mox.IgnoreArg())
        self.compute.conductor_api.action_event_finish(self.context,
                                                       mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={}, filter_properties=[],
                injected_files=self.injected_files,
                admin_password=self.admin_pass, node=self.node,
                limits=self.limits)
