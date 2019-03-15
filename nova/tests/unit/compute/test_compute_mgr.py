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
import copy
import datetime
import time

from cinderclient import exceptions as cinder_exception
from cursive import exception as cursive_exception
from eventlet import event as eventlet_event
from eventlet import timeout as eventlet_timeout
import mock
import netaddr
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
import testtools

import nova
from nova.compute import build_results
from nova.compute import manager
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import api as conductor_api
import nova.conf
from nova import context
from nova import db
from nova import exception
from nova.network import api as network_api
from nova.network import model as network_model
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.objects import fields
from nova.objects import instance as instance_obj
from nova.objects import migrate_data as migrate_data_obj
from nova.objects import network_request as net_req_obj
from nova import test
from nova.tests import fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.compute import fake_resource_tracker
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.tests.unit import fake_network_cache_model
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt.block_device import DriverVolumeBlockDevice as driver_bdm_volume
from nova.virt import driver as virt_driver
from nova.virt import event as virtevent
from nova.virt import fake as fake_driver
from nova.virt import hardware
from nova.volume import cinder


CONF = nova.conf.CONF
fake_host_list = [mock.sentinel.host1]


class ComputeManagerUnitTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerUnitTestCase, self).setUp()
        self.compute = manager.ComputeManager()
        self.context = context.RequestContext(fakes.FAKE_USER_ID,
                                              fakes.FAKE_PROJECT_ID)

        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        self.useFixture(fixtures.EventReporterStub())

    @mock.patch.object(manager.ComputeManager, '_get_power_state')
    @mock.patch.object(manager.ComputeManager, '_sync_instance_power_state')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def _test_handle_lifecycle_event(self, mock_get, mock_sync,
                                     mock_get_power_state, transition,
                                     event_pwr_state, current_pwr_state):
        event = mock.Mock()
        event.get_instance_uuid.return_value = mock.sentinel.uuid
        event.get_transition.return_value = transition
        mock_get_power_state.return_value = current_pwr_state

        self.compute.handle_lifecycle_event(event)

        mock_get.assert_called_with(mock.ANY, mock.sentinel.uuid,
                                    expected_attrs=[])
        if event_pwr_state == current_pwr_state:
            mock_sync.assert_called_with(mock.ANY, mock_get.return_value,
                                         event_pwr_state)
        else:
            self.assertFalse(mock_sync.called)

    def test_handle_lifecycle_event(self):
        event_map = {virtevent.EVENT_LIFECYCLE_STOPPED: power_state.SHUTDOWN,
                     virtevent.EVENT_LIFECYCLE_STARTED: power_state.RUNNING,
                     virtevent.EVENT_LIFECYCLE_PAUSED: power_state.PAUSED,
                     virtevent.EVENT_LIFECYCLE_RESUMED: power_state.RUNNING,
                     virtevent.EVENT_LIFECYCLE_SUSPENDED:
                         power_state.SUSPENDED,
        }

        for transition, pwr_state in event_map.items():
            self._test_handle_lifecycle_event(transition=transition,
                                              event_pwr_state=pwr_state,
                                              current_pwr_state=pwr_state)

    def test_handle_lifecycle_event_state_mismatch(self):
        self._test_handle_lifecycle_event(
            transition=virtevent.EVENT_LIFECYCLE_STOPPED,
            event_pwr_state=power_state.SHUTDOWN,
            current_pwr_state=power_state.RUNNING)

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_delete_instance_info_cache_delete_ordering(self, mock_notify):
        call_tracker = mock.Mock()
        call_tracker.clear_events_for_instance.return_value = None
        mgr_class = self.compute.__class__
        orig_delete = mgr_class._delete_instance
        specd_compute = mock.create_autospec(mgr_class)
        # spec out everything except for the method we really want
        # to test, then use call_tracker to verify call sequence
        specd_compute._delete_instance = orig_delete
        specd_compute.host = 'compute'

        mock_inst = mock.Mock()
        mock_inst.uuid = uuids.instance
        mock_inst.save = mock.Mock()
        mock_inst.destroy = mock.Mock()
        mock_inst.system_metadata = mock.Mock()

        def _mark_notify(*args, **kwargs):
            call_tracker._notify_about_instance_usage(*args, **kwargs)

        def _mark_shutdown(*args, **kwargs):
            call_tracker._shutdown_instance(*args, **kwargs)

        specd_compute.instance_events = call_tracker
        specd_compute._notify_about_instance_usage = _mark_notify
        specd_compute._shutdown_instance = _mark_shutdown
        mock_inst.info_cache = call_tracker

        mock_bdms = mock.Mock()
        specd_compute._delete_instance(specd_compute,
                                       self.context,
                                       mock_inst,
                                       mock_bdms)

        methods_called = [n for n, a, k in call_tracker.mock_calls]
        self.assertEqual(['clear_events_for_instance',
                          '_notify_about_instance_usage',
                          '_shutdown_instance', 'delete'],
                         methods_called)
        mock_notify.assert_called_once_with(self.context,
                                            mock_inst,
                                            specd_compute.host,
                                            action='delete',
                                            phase='start',
                                            bdms=mock_bdms)

    def _make_compute_node(self, hyp_hostname, cn_id):
            cn = mock.Mock(spec_set=['hypervisor_hostname', 'id',
                                     'destroy'])
            cn.id = cn_id
            cn.hypervisor_hostname = hyp_hostname
            return cn

    @mock.patch.object(manager.ComputeManager, '_get_resource_tracker')
    def test_update_available_resource_for_node(self, get_rt):
        rt = mock.Mock(spec_set=['update_available_resource'])
        get_rt.return_value = rt

        self.compute.update_available_resource_for_node(
            self.context,
            mock.sentinel.node,
        )
        rt.update_available_resource.assert_called_once_with(
            self.context,
            mock.sentinel.node,
        )

    @mock.patch('nova.compute.manager.LOG')
    @mock.patch.object(manager.ComputeManager, '_get_resource_tracker')
    def test_update_available_resource_for_node_fail_no_host(self, get_rt,
            log_mock):
        rt = mock.Mock(spec_set=['update_available_resource'])
        exc = exception.ComputeHostNotFound(host=mock.sentinel.host)
        rt.update_available_resource.side_effect = exc
        get_rt.return_value = rt
        # Fake out the RT on the compute manager object so we can assert it's
        # nulled out after the ComputeHostNotFound exception is raised.
        self.compute._resource_tracker = rt

        self.compute.update_available_resource_for_node(
            self.context,
            mock.sentinel.node,
        )
        rt.update_available_resource.assert_called_once_with(
            self.context,
            mock.sentinel.node,
        )
        self.assertTrue(log_mock.info.called)
        self.assertIsNone(self.compute._resource_tracker)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_resource_provider')
    @mock.patch.object(manager.ComputeManager,
                       'update_available_resource_for_node')
    @mock.patch.object(fake_driver.FakeDriver, 'get_available_nodes')
    @mock.patch.object(manager.ComputeManager, '_get_compute_nodes_in_db')
    def test_update_available_resource(self, get_db_nodes, get_avail_nodes,
                                       update_mock, del_rp_mock):
        db_nodes = [self._make_compute_node('node%s' % i, i)
                    for i in range(1, 5)]
        avail_nodes = set(['node2', 'node3', 'node4', 'node5'])
        avail_nodes_l = list(avail_nodes)

        get_db_nodes.return_value = db_nodes
        get_avail_nodes.return_value = avail_nodes
        self.compute.update_available_resource(self.context)
        get_db_nodes.assert_called_once_with(self.context, use_slave=True,
                                             startup=False)
        update_mock.has_calls(
            [mock.call(self.context, node) for node in avail_nodes_l]
        )

        # First node in set should have been removed from DB
        for db_node in db_nodes:
            if db_node.hypervisor_hostname == 'node1':
                db_node.destroy.assert_called_once_with()
                del_rp_mock.assert_called_once_with(self.context, db_node,
                        cascade=True)
            else:
                self.assertFalse(db_node.destroy.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_resource_provider')
    @mock.patch.object(manager.ComputeManager,
                       'update_available_resource_for_node')
    @mock.patch.object(fake_driver.FakeDriver, 'get_available_nodes')
    @mock.patch.object(manager.ComputeManager, '_get_compute_nodes_in_db')
    def test_update_available_resource_not_ready(self, get_db_nodes,
                                                 get_avail_nodes,
                                                 update_mock,
                                                 del_rp_mock):
        db_nodes = [self._make_compute_node('node1', 1)]
        get_db_nodes.return_value = db_nodes
        get_avail_nodes.side_effect = exception.VirtDriverNotReady

        self.compute.update_available_resource(self.context)

        # these shouldn't get processed on VirtDriverNotReady
        update_mock.assert_not_called()
        del_rp_mock.assert_not_called()

    @mock.patch('nova.context.get_admin_context')
    def test_pre_start_hook(self, get_admin_context):
        """Very simple test just to make sure update_available_resource is
        called as expected.
        """
        with mock.patch.object(
                self.compute, 'update_available_resource') as update_res:
            self.compute.pre_start_hook()
        update_res.assert_called_once_with(
            get_admin_context.return_value, startup=True)

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
                       side_effect=exception.NotFound)
    @mock.patch('nova.compute.manager.LOG')
    def test_get_compute_nodes_in_db_on_startup(self, mock_log,
                                                get_all_by_host):
        """Tests to make sure we only log a warning when we do not find a
        compute node on startup since this may be expected.
        """
        self.assertEqual([], self.compute._get_compute_nodes_in_db(
            self.context, startup=True))
        get_all_by_host.assert_called_once_with(
            self.context, self.compute.host, use_slave=False)
        self.assertTrue(mock_log.warning.called)
        self.assertFalse(mock_log.error.called)

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_detach_volume')
    def test_delete_instance_without_info_cache(self, mock_detach,
                                                mock_notify):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_states.ERROR,
                host=self.compute.host,
                expected_attrs=['system_metadata'])

        with test.nested(
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute, '_shutdown_instance'),
            mock.patch.object(instance, 'obj_load_attr'),
            mock.patch.object(instance, 'save'),
            mock.patch.object(instance, 'destroy')
        ) as (
            compute_notify_about_instance_usage, compute_shutdown_instance,
            instance_obj_load_attr, instance_save, instance_destroy
        ):
            instance.info_cache = None
            self.compute._delete_instance(self.context, instance, [])

        mock_notify.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='delete', phase='start', bdms=[]),
            mock.call(self.context, instance, 'fake-mini',
                      action='delete', phase='end', bdms=[])])

    def test_check_device_tagging_no_tagging(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       instance_uuid=uuids.instance)])
        net_req = net_req_obj.NetworkRequest(tag=None)
        net_req_list = net_req_obj.NetworkRequestList(objects=[net_req])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=False):
            self.compute._check_device_tagging(net_req_list, bdms)

    def test_check_device_tagging_no_networks(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       instance_uuid=uuids.instance)])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=False):
            self.compute._check_device_tagging(None, bdms)

    def test_check_device_tagging_tagged_net_req_no_virt_support(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       instance_uuid=uuids.instance)])
        net_req = net_req_obj.NetworkRequest(port_id=uuids.bar, tag='foo')
        net_req_list = net_req_obj.NetworkRequestList(objects=[net_req])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=False):
            self.assertRaises(exception.BuildAbortException,
                              self.compute._check_device_tagging,
                              net_req_list, bdms)

    def test_check_device_tagging_tagged_bdm_no_driver_support(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       tag='foo',
                                       instance_uuid=uuids.instance)])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=False):
            self.assertRaises(exception.BuildAbortException,
                              self.compute._check_device_tagging,
                              None, bdms)

    def test_check_device_tagging_tagged_bdm_no_driver_support_declared(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       tag='foo',
                                       instance_uuid=uuids.instance)])
        with mock.patch.dict(self.compute.driver.capabilities):
            self.compute.driver.capabilities.pop('supports_device_tagging',
                                                 None)
            self.assertRaises(exception.BuildAbortException,
                              self.compute._check_device_tagging,
                              None, bdms)

    def test_check_device_tagging_tagged_bdm_with_driver_support(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       tag='foo',
                                       instance_uuid=uuids.instance)])
        net_req = net_req_obj.NetworkRequest(network_id=uuids.bar)
        net_req_list = net_req_obj.NetworkRequestList(objects=[net_req])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=True):
            self.compute._check_device_tagging(net_req_list, bdms)

    def test_check_device_tagging_tagged_net_req_with_driver_support(self):
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(source_type='volume',
                                       destination_type='volume',
                                       instance_uuid=uuids.instance)])
        net_req = net_req_obj.NetworkRequest(network_id=uuids.bar, tag='foo')
        net_req_list = net_req_obj.NetworkRequestList(objects=[net_req])
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_device_tagging=True):
            self.compute._check_device_tagging(net_req_list, bdms)

    @mock.patch.object(objects.BlockDeviceMapping, 'create')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid',
                       return_value=objects.BlockDeviceMappingList())
    def test_reserve_block_device_name_with_tag(self, mock_get, mock_create):
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
                mock.patch.object(self.compute,
                                  '_get_device_name_for_instance',
                                  return_value='/dev/vda'),
                mock.patch.dict(self.compute.driver.capabilities,
                                supports_tagged_attach_volume=True)):
            bdm = self.compute.reserve_block_device_name(
                    self.context, instance, None, None, None, None, 'foo',
                    False)
            self.assertEqual('foo', bdm.tag)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_reserve_block_device_name_raises(self, _):
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_tagged_attach_volume=False):
            self.assertRaises(exception.VolumeTaggedAttachNotSupported,
                              self.compute.reserve_block_device_name,
                              self.context,
                              fake_instance.fake_instance_obj(self.context),
                              'fake_device', 'fake_volume_id', 'fake_disk_bus',
                              'fake_device_type', 'foo', False)

    @mock.patch.object(objects.BlockDeviceMapping, 'create')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid',
                       return_value=objects.BlockDeviceMappingList())
    def test_reserve_block_device_name_multiattach(self, mock_get,
                                                   mock_create):
        """Tests the case that multiattach=True and the driver supports it."""
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
                mock.patch.object(self.compute,
                                  '_get_device_name_for_instance',
                                  return_value='/dev/vda'),
                mock.patch.dict(self.compute.driver.capabilities,
                                supports_multiattach=True)):
            self.compute.reserve_block_device_name(
                self.context, instance, device=None, volume_id=uuids.volume_id,
                disk_bus=None, device_type=None, tag=None, multiattach=True)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_reserve_block_device_name_multiattach_raises(self, _):
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_multiattach=False):
            self.assertRaises(exception.MultiattachNotSupportedByVirtDriver,
                              self.compute.reserve_block_device_name,
                              self.context,
                              fake_instance.fake_instance_obj(self.context),
                              'fake_device', 'fake_volume_id', 'fake_disk_bus',
                              'fake_device_type', tag=None, multiattach=True)

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(time, 'sleep')
    def test_allocate_network_succeeds_after_retries(
            self, mock_sleep, mock_save):
        self.flags(network_allocate_retries=8)

        instance = fake_instance.fake_instance_obj(
                       self.context, expected_attrs=['system_metadata'])

        is_vpn = 'fake-is-vpn'
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake')])
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        final_result = 'meow'

        expected_sleep_times = [1, 2, 4, 8, 16, 30, 30, 30]

        with mock.patch.object(
                self.compute.network_api, 'allocate_for_instance',
                side_effect=[test.TestingException()] * 7 + [final_result]):
            res = self.compute._allocate_network_async(self.context, instance,
                                                       req_networks,
                                                       macs,
                                                       sec_groups,
                                                       is_vpn)

        mock_sleep.has_calls(expected_sleep_times)
        self.assertEqual(final_result, res)
        # Ensure save is not called in while allocating networks, the instance
        # is saved after the allocation.
        self.assertFalse(mock_save.called)
        self.assertEqual('True', instance.system_metadata['network_allocated'])

    def test_allocate_network_fails(self):
        self.flags(network_allocate_retries=0)

        instance = {}
        is_vpn = 'fake-is-vpn'
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake')])
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'

        with mock.patch.object(
                self.compute.network_api, 'allocate_for_instance',
                side_effect=test.TestingException) as mock_allocate:
            self.assertRaises(test.TestingException,
                              self.compute._allocate_network_async,
                              self.context, instance, req_networks, macs,
                              sec_groups, is_vpn)

        mock_allocate.assert_called_once_with(
            self.context, instance, vpn=is_vpn,
            requested_networks=req_networks, macs=macs,
            security_groups=sec_groups,
            bind_host_id=instance.get('host'))

    @mock.patch.object(manager.ComputeManager, '_instance_update')
    @mock.patch.object(time, 'sleep')
    def test_allocate_network_with_conf_value_is_one(
            self, sleep, _instance_update):
        self.flags(network_allocate_retries=1)

        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        is_vpn = 'fake-is-vpn'
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake')])
        macs = 'fake-macs'
        sec_groups = 'fake-sec-groups'
        final_result = 'zhangtralon'

        with mock.patch.object(self.compute.network_api,
                               'allocate_for_instance',
                               side_effect = [test.TestingException(),
                                              final_result]):
            res = self.compute._allocate_network_async(self.context, instance,
                                                       req_networks,
                                                       macs,
                                                       sec_groups,
                                                       is_vpn)
        self.assertEqual(final_result, res)
        self.assertEqual(1, sleep.call_count)

    def test_allocate_network_skip_for_no_allocate(self):
        # Ensures that we don't do anything if requested_networks has 'none'
        # for the network_id.
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='none')])
        nwinfo = self.compute._allocate_network_async(
            self.context, mock.sentinel.instance, req_networks, macs=None,
            security_groups=['default'], is_vpn=False)
        self.assertEqual(0, len(nwinfo))

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_do_build_and_run_instance')
    def _test_max_concurrent_builds(self, mock_dbari):

        with mock.patch.object(self.compute,
                               '_build_semaphore') as mock_sem:
            instance = objects.Instance(uuid=uuidutils.generate_uuid())
            for i in (1, 2, 3):
                self.compute.build_and_run_instance(self.context, instance,
                                                    mock.sentinel.image,
                                                    mock.sentinel.request_spec,
                                                    {})
            self.assertEqual(3, mock_sem.__enter__.call_count)

    def test_max_concurrent_builds_limited(self):
        self.flags(max_concurrent_builds=2)
        self._test_max_concurrent_builds()

    def test_max_concurrent_builds_unlimited(self):
        self.flags(max_concurrent_builds=0)
        self._test_max_concurrent_builds()

    def test_max_concurrent_builds_semaphore_limited(self):
        self.flags(max_concurrent_builds=123)
        self.assertEqual(123,
                         manager.ComputeManager()._build_semaphore.balance)

    def test_max_concurrent_builds_semaphore_unlimited(self):
        self.flags(max_concurrent_builds=0)
        compute = manager.ComputeManager()
        self.assertEqual(0, compute._build_semaphore.balance)
        self.assertIsInstance(compute._build_semaphore,
                              compute_utils.UnlimitedSemaphore)

    def test_nil_out_inst_obj_host_and_node_sets_nil(self):
        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance,
                                                   host='foo-host',
                                                   node='foo-node')
        self.assertIsNotNone(instance.host)
        self.assertIsNotNone(instance.node)
        self.compute._nil_out_instance_obj_host_and_node(instance)
        self.assertIsNone(instance.host)
        self.assertIsNone(instance.node)

    def test_init_host(self):
        our_host = self.compute.host
        inst = fake_instance.fake_db_instance(
                vm_state=vm_states.ACTIVE,
                info_cache=dict(test_instance_info_cache.fake_info_cache,
                                network_info=None),
                security_groups=None)
        startup_instances = [inst, inst, inst]

        def _make_instance_list(db_list):
            return instance_obj._make_instance_list(
                    self.context, objects.InstanceList(), db_list, None)

        @mock.patch.object(fake_driver.FakeDriver, 'init_host')
        @mock.patch.object(fake_driver.FakeDriver, 'filter_defer_apply_on')
        @mock.patch.object(fake_driver.FakeDriver, 'filter_defer_apply_off')
        @mock.patch.object(objects.InstanceList, 'get_by_host')
        @mock.patch.object(context, 'get_admin_context')
        @mock.patch.object(manager.ComputeManager,
                           '_destroy_evacuated_instances')
        @mock.patch.object(manager.ComputeManager, '_init_instance')
        @mock.patch.object(self.compute, '_update_scheduler_instance_info')
        def _do_mock_calls(mock_update_scheduler, mock_inst_init,
                           mock_destroy, mock_admin_ctxt, mock_host_get,
                           mock_filter_off, mock_filter_on, mock_init_host,
                           defer_iptables_apply):
            mock_admin_ctxt.return_value = self.context
            inst_list = _make_instance_list(startup_instances)
            mock_host_get.return_value = inst_list

            self.compute.init_host()

            if defer_iptables_apply:
                self.assertTrue(mock_filter_on.called)
            mock_destroy.assert_called_once_with(self.context)
            mock_inst_init.assert_has_calls(
                [mock.call(self.context, inst_list[0]),
                 mock.call(self.context, inst_list[1]),
                 mock.call(self.context, inst_list[2])])

            if defer_iptables_apply:
                self.assertTrue(mock_filter_off.called)
            mock_init_host.assert_called_once_with(host=our_host)
            mock_host_get.assert_called_once_with(self.context, our_host,
                                    expected_attrs=['info_cache', 'metadata'])

            mock_update_scheduler.assert_called_once_with(
                self.context, inst_list)

        # Test with defer_iptables_apply
        self.flags(defer_iptables_apply=True)
        _do_mock_calls(defer_iptables_apply=True)

        # Test without defer_iptables_apply
        self.flags(defer_iptables_apply=False)
        _do_mock_calls(defer_iptables_apply=False)

    @mock.patch('nova.objects.InstanceList.get_by_host',
                return_value=objects.InstanceList())
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_destroy_evacuated_instances')
    @mock.patch('nova.compute.manager.ComputeManager._init_instance',
                mock.NonCallableMock())
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_update_scheduler_instance_info', mock.NonCallableMock())
    def test_init_host_no_instances(self, mock_destroy_evac_instances,
                                    mock_get_by_host):
        """Tests the case that init_host runs and there are no instances
        on this host yet (it's brand new). Uses NonCallableMock for the
        methods we assert should not be called.
        """
        self.compute.init_host()

    @mock.patch('nova.objects.InstanceList')
    @mock.patch('nova.objects.MigrationList.get_by_filters')
    def test_cleanup_host(self, mock_miglist_get, mock_instance_list):
        # just testing whether the cleanup_host method
        # when fired will invoke the underlying driver's
        # equivalent method.

        mock_miglist_get.return_value = []
        mock_instance_list.get_by_host.return_value = []

        with mock.patch.object(self.compute, 'driver') as mock_driver:
            self.compute.init_host()
            mock_driver.init_host.assert_called_once_with(host='fake-mini')

            self.compute.cleanup_host()
            # register_event_listener is called on startup (init_host) and
            # in cleanup_host
            mock_driver.register_event_listener.assert_has_calls([
                mock.call(self.compute.handle_events), mock.call(None)])
            mock_driver.cleanup_host.assert_called_once_with(host='fake-mini')

    def test_init_virt_events_disabled(self):
        self.flags(handle_virt_lifecycle_events=False, group='workarounds')
        with mock.patch.object(self.compute.driver,
                               'register_event_listener') as mock_register:
            self.compute.init_virt_events()
        self.assertFalse(mock_register.called)

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    @mock.patch.object(manager.ComputeManager, '_get_instances_on_driver')
    @mock.patch.object(manager.ComputeManager, 'init_virt_events')
    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(objects.InstanceList, 'get_by_host')
    @mock.patch.object(fake_driver.FakeDriver, 'destroy')
    @mock.patch.object(fake_driver.FakeDriver, 'init_host')
    @mock.patch('nova.utils.temporary_mutation')
    @mock.patch('nova.objects.MigrationList.get_by_filters')
    @mock.patch('nova.objects.Migration.save')
    def test_init_host_with_evacuated_instance(self, mock_save, mock_mig_get,
            mock_temp_mut, mock_init_host, mock_destroy, mock_host_get,
            mock_admin_ctxt, mock_init_virt, mock_get_inst, mock_resources,
            mock_get_node, mock_elevated):
        our_host = self.compute.host
        not_our_host = 'not-' + our_host

        read_deleted_context = self.context.elevated(read_deleted='yes')
        mock_elevated.return_value = read_deleted_context
        deleted_instance = fake_instance.fake_instance_obj(
                self.context, host=not_our_host, uuid=uuids.deleted_instance)
        migration = objects.Migration(instance_uuid=deleted_instance.uuid)
        migration.source_node = 'fake-node'
        mock_mig_get.return_value = [migration]
        mock_admin_ctxt.return_value = self.context
        mock_host_get.return_value = objects.InstanceList()
        our_node = objects.ComputeNode(host=our_host, uuid=uuids.our_node_uuid)
        mock_get_node.return_value = our_node
        mock_resources.return_value = mock.sentinel.my_resources

        # simulate failed instance
        mock_get_inst.return_value = [deleted_instance]
        with test.nested(
            mock.patch.object(
                self.compute.network_api, 'get_instance_nw_info',
                side_effect = exception.InstanceNotFound(
                    instance_id=deleted_instance['uuid'])),
            mock.patch.object(
                self.compute.reportclient,
                'remove_provider_from_instance_allocation')
        ) as (mock_get_net, mock_remove_allocation):

            self.compute.init_host()

            mock_remove_allocation.assert_called_once_with(
                self.context, deleted_instance.uuid, uuids.our_node_uuid,
                deleted_instance.user_id, deleted_instance.project_id,
                mock.sentinel.my_resources)

        mock_init_host.assert_called_once_with(host=our_host)
        mock_host_get.assert_called_once_with(self.context, our_host,
                                expected_attrs=['info_cache', 'metadata'])
        mock_init_virt.assert_called_once_with()
        mock_temp_mut.assert_called_once_with(self.context, read_deleted='yes')
        mock_get_inst.assert_called_once_with(read_deleted_context)
        mock_get_net.assert_called_once_with(self.context, deleted_instance)

        # ensure driver.destroy is called so that driver may
        # clean up any dangling files
        mock_destroy.assert_called_once_with(self.context, deleted_instance,
                                             mock.ANY, mock.ANY, mock.ANY)
        mock_save.assert_called_once_with()

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(objects.InstanceList, 'get_by_host')
    @mock.patch.object(fake_driver.FakeDriver, 'init_host')
    @mock.patch('nova.compute.manager.ComputeManager._init_instance')
    @mock.patch('nova.compute.manager.ComputeManager.'
                  '_destroy_evacuated_instances')
    def test_init_host_with_in_progress_evacuations(self, mock_destroy_evac,
            mock_init_instance, mock_init_host, mock_host_get,
            mock_admin_ctxt):
        """Assert that init_instance is not called for instances that are
           evacuating from the host during init_host.
        """
        active_instance = fake_instance.fake_instance_obj(
            self.context, host=self.compute.host, uuid=uuids.active_instance)
        evacuating_instance = fake_instance.fake_instance_obj(
            self.context, host=self.compute.host, uuid=uuids.evac_instance)
        instance_list = objects.InstanceList(self.context,
            objects=[active_instance, evacuating_instance])

        mock_host_get.return_value = instance_list
        mock_admin_ctxt.return_value = self.context
        mock_destroy_evac.return_value = {
            uuids.evac_instance: evacuating_instance
        }

        self.compute.init_host()

        mock_init_instance.assert_called_once_with(
            self.context, active_instance)

    def test_init_instance_with_binding_failed_vif_type(self):
        # this instance will plug a 'binding_failed' vif
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                info_cache=None,
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=None,
                host=self.compute.host,
                expected_attrs=['info_cache'])

        with test.nested(
            mock.patch.object(context, 'get_admin_context',
                return_value=self.context),
            mock.patch.object(objects.Instance, 'get_network_info',
                return_value=network_model.NetworkInfo()),
            mock.patch.object(self.compute.driver, 'plug_vifs',
                side_effect=exception.VirtualInterfacePlugException(
                    "Unexpected vif_type=binding_failed")),
            mock.patch.object(self.compute, '_set_instance_obj_error_state')
        ) as (get_admin_context, get_nw_info, plug_vifs, set_error_state):
            self.compute._init_instance(self.context, instance)
            set_error_state.assert_called_once_with(self.context, instance)

    def test__get_power_state_InstanceNotFound(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                power_state=power_state.RUNNING)
        with mock.patch.object(self.compute.driver,
                'get_info',
                side_effect=exception.InstanceNotFound(instance_id=1)):
            self.assertEqual(self.compute._get_power_state(self.context,
                                                           instance),
                    power_state.NOSTATE)

    def test__get_power_state_NotFound(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                power_state=power_state.RUNNING)
        with mock.patch.object(self.compute.driver,
                'get_info',
                side_effect=exception.NotFound()):
            self.assertRaises(exception.NotFound,
                              self.compute._get_power_state,
                              self.context, instance)

    @mock.patch.object(manager.ComputeManager, '_get_power_state')
    @mock.patch.object(fake_driver.FakeDriver, 'plug_vifs')
    @mock.patch.object(fake_driver.FakeDriver, 'resume_state_on_host_boot')
    @mock.patch.object(manager.ComputeManager,
                       '_get_instance_block_device_info')
    @mock.patch.object(manager.ComputeManager, '_set_instance_obj_error_state')
    def test_init_instance_failed_resume_sets_error(self, mock_set_inst,
                mock_get_inst, mock_resume, mock_plug, mock_get_power):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                info_cache=None,
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                task_state=None,
                host=self.compute.host,
                expected_attrs=['info_cache'])

        self.flags(resume_guests_state_on_host_boot=True)
        mock_get_power.side_effect = (power_state.SHUTDOWN,
                                      power_state.SHUTDOWN)
        mock_get_inst.return_value = 'fake-bdm'
        mock_resume.side_effect = test.TestingException
        self.compute._init_instance('fake-context', instance)
        mock_get_power.assert_has_calls([mock.call(mock.ANY, instance),
                                         mock.call(mock.ANY, instance)])
        mock_plug.assert_called_once_with(instance, mock.ANY)
        mock_get_inst.assert_called_once_with(mock.ANY, instance)
        mock_resume.assert_called_once_with(mock.ANY, instance, mock.ANY,
                                            'fake-bdm')
        mock_set_inst.assert_called_once_with(mock.ANY, instance)

    @mock.patch.object(objects.BlockDeviceMapping, 'destroy')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'destroy')
    @mock.patch.object(objects.Instance, 'obj_load_attr')
    @mock.patch.object(objects.quotas, 'ids_from_instance')
    def test_init_instance_complete_partial_deletion(
            self, mock_ids_from_instance,
            mock_inst_destroy, mock_obj_load_attr, mock_get_by_instance_uuid,
            mock_bdm_destroy):
        """Test to complete deletion for instances in DELETED status but not
        marked as deleted in the DB
        """
        instance = fake_instance.fake_instance_obj(
                self.context,
                project_id=fakes.FAKE_PROJECT_ID,
                uuid=uuids.instance,
                vcpus=1,
                memory_mb=64,
                power_state=power_state.SHUTDOWN,
                vm_state=vm_states.DELETED,
                host=self.compute.host,
                task_state=None,
                deleted=False,
                deleted_at=None,
                metadata={},
                system_metadata={},
                expected_attrs=['metadata', 'system_metadata'])

        # Make sure instance vm_state is marked as 'DELETED' but instance is
        # not destroyed from db.
        self.assertEqual(vm_states.DELETED, instance.vm_state)
        self.assertFalse(instance.deleted)

        def fake_inst_destroy():
            instance.deleted = True
            instance.deleted_at = timeutils.utcnow()

        mock_ids_from_instance.return_value = (instance.project_id,
                                               instance.user_id)
        mock_inst_destroy.side_effect = fake_inst_destroy()

        self.compute._init_instance(self.context, instance)

        # Make sure that instance.destroy method was called and
        # instance was deleted from db.
        self.assertNotEqual(0, instance.deleted)

    @mock.patch('nova.compute.manager.LOG')
    def test_init_instance_complete_partial_deletion_raises_exception(
            self, mock_log):
        instance = fake_instance.fake_instance_obj(
                self.context,
                project_id=fakes.FAKE_PROJECT_ID,
                uuid=uuids.instance,
                vcpus=1,
                memory_mb=64,
                power_state=power_state.SHUTDOWN,
                vm_state=vm_states.DELETED,
                host=self.compute.host,
                task_state=None,
                deleted=False,
                deleted_at=None,
                metadata={},
                system_metadata={},
                expected_attrs=['metadata', 'system_metadata'])

        with mock.patch.object(self.compute,
                               '_complete_partial_deletion') as mock_deletion:
            mock_deletion.side_effect = test.TestingException()
            self.compute._init_instance(self, instance)
            msg = u'Failed to complete a deletion'
            mock_log.exception.assert_called_once_with(msg, instance=instance)

    def test_init_instance_stuck_in_deleting(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                project_id=fakes.FAKE_PROJECT_ID,
                uuid=uuids.instance,
                vcpus=1,
                memory_mb=64,
                power_state=power_state.RUNNING,
                vm_state=vm_states.ACTIVE,
                host=self.compute.host,
                task_state=task_states.DELETING)

        bdms = []

        with test.nested(
                mock.patch.object(objects.BlockDeviceMappingList,
                                  'get_by_instance_uuid',
                                  return_value=bdms),
                mock.patch.object(self.compute, '_delete_instance'),
                mock.patch.object(instance, 'obj_load_attr')
        ) as (mock_get, mock_delete, mock_load):
            self.compute._init_instance(self.context, instance)
            mock_get.assert_called_once_with(self.context, instance.uuid)
            mock_delete.assert_called_once_with(self.context, instance,
                                                bdms)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    def test_init_instance_stuck_in_deleting_raises_exception(
            self, mock_get_by_instance_uuid, mock_get_by_uuid):

        instance = fake_instance.fake_instance_obj(
            self.context,
            project_id=fakes.FAKE_PROJECT_ID,
            uuid=uuids.instance,
            vcpus=1,
            memory_mb=64,
            metadata={},
            system_metadata={},
            host=self.compute.host,
            vm_state=vm_states.ACTIVE,
            task_state=task_states.DELETING,
            expected_attrs=['metadata', 'system_metadata'])

        bdms = []

        def _create_patch(name, attr):
            patcher = mock.patch.object(name, attr)
            mocked_obj = patcher.start()
            self.addCleanup(patcher.stop)
            return mocked_obj

        mock_delete_instance = _create_patch(self.compute, '_delete_instance')
        mock_set_instance_error_state = _create_patch(
            self.compute, '_set_instance_obj_error_state')
        mock_get_by_instance_uuid.return_value = bdms
        mock_get_by_uuid.return_value = instance
        mock_delete_instance.side_effect = test.TestingException('test')
        self.compute._init_instance(self.context, instance)
        mock_set_instance_error_state.assert_called_once_with(
            self.context, instance)

    def _test_init_instance_reverts_crashed_migrations(self,
                                                       old_vm_state=None):
        power_on = True if (not old_vm_state or
                            old_vm_state == vm_states.ACTIVE) else False
        sys_meta = {
            'old_vm_state': old_vm_state
            }
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_states.ERROR,
                task_state=task_states.RESIZE_MIGRATING,
                power_state=power_state.SHUTDOWN,
                system_metadata=sys_meta,
                host=self.compute.host,
                expected_attrs=['system_metadata'])

        with test.nested(
            mock.patch.object(objects.Instance, 'get_network_info',
                              return_value=network_model.NetworkInfo()),
            mock.patch.object(self.compute.driver, 'plug_vifs'),
            mock.patch.object(self.compute.driver, 'finish_revert_migration'),
            mock.patch.object(self.compute, '_get_instance_block_device_info',
                              return_value=[]),
            mock.patch.object(self.compute.driver, 'get_info'),
            mock.patch.object(instance, 'save'),
            mock.patch.object(self.compute, '_retry_reboot',
                              return_value=(False, None))
        ) as (mock_get_nw, mock_plug, mock_finish, mock_get_inst,
              mock_get_info, mock_save, mock_retry):
            mock_get_info.side_effect = (
                hardware.InstanceInfo(state=power_state.SHUTDOWN),
                hardware.InstanceInfo(state=power_state.SHUTDOWN))

            self.compute._init_instance(self.context, instance)

            mock_retry.assert_called_once_with(self.context, instance,
                power_state.SHUTDOWN)
            mock_get_nw.assert_called_once_with()
            mock_plug.assert_called_once_with(instance, [])
            mock_get_inst.assert_called_once_with(self.context, instance)
            mock_finish.assert_called_once_with(self.context, instance,
                                                [], [], power_on)
            mock_save.assert_called_once_with()
            mock_get_info.assert_has_calls([mock.call(instance),
                                            mock.call(instance)])
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
                uuid=uuids.instance,
                vm_state=vm_states.ACTIVE,
                host=self.compute.host,
                task_state=task_states.MIGRATING)
        with test.nested(
            mock.patch.object(instance, 'save'),
            mock.patch('nova.objects.Instance.get_network_info',
                       return_value=network_model.NetworkInfo())
        ) as (save, get_nw_info):
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with(expected_task_state=['migrating'])
            get_nw_info.assert_called_once_with()
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)

    def _test_init_instance_sets_building_error(self, vm_state,
                                                task_state=None):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_state,
                host=self.compute.host,
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
        instance.host = self.compute.host
        with mock.patch.object(instance, 'save') as save:
            self.compute._init_instance(self.context, instance)
            save.assert_called_once_with()
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ERROR, instance.vm_state)

    def test_init_instance_sets_building_tasks_error_scheduling(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=None,
                task_state=task_states.SCHEDULING)
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_block_device(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = None
        instance.task_state = task_states.BLOCK_DEVICE_MAPPING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_networking(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = None
        instance.task_state = task_states.NETWORKING
        self._test_init_instance_sets_building_tasks_error(instance)

    def test_init_instance_sets_building_tasks_error_spawning(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = None
        instance.task_state = task_states.SPAWNING
        self._test_init_instance_sets_building_tasks_error(instance)

    def _test_init_instance_cleans_image_states(self, instance):
        with mock.patch.object(instance, 'save') as save:
            self.compute._get_power_state = mock.Mock()
            self.compute.driver.post_interrupted_snapshot_cleanup = mock.Mock()
            instance.info_cache = None
            instance.power_state = power_state.RUNNING
            instance.host = self.compute.host
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
        instance.uuid = uuids.instance
        instance.info_cache = None
        instance.power_state = power_state.RUNNING
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = state
        instance.host = self.compute.host
        mock_get_power_state.return_value = powerstate

        self.compute._init_instance(self.context, instance)

        return instance

    def test_init_instance_cleans_image_state_pending_upload(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_PENDING_UPLOAD
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_uploading(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_UPLOADING
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.IMAGE_SNAPSHOT
        self._test_init_instance_cleans_image_states(instance)

    def test_init_instance_cleans_image_state_snapshot_pending(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
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

    def test_init_instance_deletes_error_deleting_instance(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                project_id=fakes.FAKE_PROJECT_ID,
                uuid=uuids.instance,
                vcpus=1,
                memory_mb=64,
                vm_state=vm_states.ERROR,
                host=self.compute.host,
                task_state=task_states.DELETING)
        bdms = []

        with test.nested(
                mock.patch.object(objects.BlockDeviceMappingList,
                                  'get_by_instance_uuid',
                                  return_value=bdms),
                mock.patch.object(self.compute, '_delete_instance'),
                mock.patch.object(instance, 'obj_load_attr')
        ) as (mock_get, mock_delete, mock_load):
            self.compute._init_instance(self.context, instance)
            mock_get.assert_called_once_with(self.context, instance.uuid)
            mock_delete.assert_called_once_with(self.context, instance,
                                                bdms)

    def test_init_instance_resize_prep(self):
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_states.ACTIVE,
                host=self.compute.host,
                task_state=task_states.RESIZE_PREP,
                power_state=power_state.RUNNING)

        with test.nested(
            mock.patch.object(self.compute, '_get_power_state',
                              return_value=power_state.RUNNING),
            mock.patch.object(objects.Instance, 'get_network_info'),
            mock.patch.object(instance, 'save', autospec=True)
        ) as (mock_get_power_state, mock_nw_info, mock_instance_save):
            self.compute._init_instance(self.context, instance)
            mock_instance_save.assert_called_once_with()
            self.assertIsNone(instance.task_state)

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch(
        'nova.compute.manager.ComputeManager._get_instance_block_device_info')
    @mock.patch('nova.virt.driver.ComputeDriver.destroy')
    @mock.patch('nova.virt.fake.FakeDriver.get_volume_connector')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch(
        'nova.compute.manager.ComputeManager._notify_about_instance_usage')
    def test_shutdown_instance_versioned_notifications(self,
            mock_notify_unversioned, mock_notify, mock_connector,
            mock_destroy, mock_blk_device_info, mock_nw_info, mock_elevated):
        mock_elevated.return_value = self.context
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_states.ERROR,
                task_state=task_states.DELETING)
        bdms = [mock.Mock(id=1, is_volume=True)]
        self.compute._shutdown_instance(self.context, instance, bdms,
                        notify=True, try_deallocate_networks=False)
        mock_notify.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='shutdown', phase='start', bdms=bdms),
            mock.call(self.context, instance, 'fake-mini',
                      action='shutdown', phase='end', bdms=bdms)])

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch(
        'nova.compute.manager.ComputeManager._get_instance_block_device_info')
    @mock.patch('nova.virt.driver.ComputeDriver.destroy')
    @mock.patch('nova.virt.fake.FakeDriver.get_volume_connector')
    def _test_shutdown_instance_exception(self, exc, mock_connector,
            mock_destroy, mock_blk_device_info, mock_nw_info, mock_elevated):
        mock_connector.side_effect = exc
        mock_elevated.return_value = self.context
        instance = fake_instance.fake_instance_obj(
                self.context,
                uuid=uuids.instance,
                vm_state=vm_states.ERROR,
                task_state=task_states.DELETING)
        bdms = [mock.Mock(id=1, is_volume=True)]

        self.compute._shutdown_instance(self.context, instance, bdms,
                notify=False, try_deallocate_networks=False)

    def test_shutdown_instance_endpoint_not_found(self):
        exc = cinder_exception.EndpointNotFound
        self._test_shutdown_instance_exception(exc)

    def test_shutdown_instance_client_exception(self):
        exc = cinder_exception.ClientException(code=9001)
        self._test_shutdown_instance_exception(exc)

    def test_shutdown_instance_volume_not_found(self):
        exc = exception.VolumeNotFound(volume_id=42)
        self._test_shutdown_instance_exception(exc)

    def test_shutdown_instance_disk_not_found(self):
        exc = exception.DiskNotFound(location="not\\here")
        self._test_shutdown_instance_exception(exc)

    def test_shutdown_instance_other_exception(self):
        exc = Exception('some other exception')
        self._test_shutdown_instance_exception(exc)

    def _test_init_instance_retries_reboot(self, instance, reboot_type,
                                           return_power_state):
        instance.host = self.compute.host
        with test.nested(
            mock.patch.object(self.compute, '_get_power_state',
                               return_value=return_power_state),
            mock.patch.object(self.compute, 'reboot_instance'),
            mock.patch.object(objects.Instance, 'get_network_info')
          ) as (
            _get_power_state,
            reboot_instance,
            get_network_info
          ):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance, block_device_info=None,
                             reboot_type=reboot_type)
            reboot_instance.assert_has_calls([call])

    def test_init_instance_retries_reboot_pending(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_PENDING
        for state in vm_states.ALLOW_SOFT_REBOOT:
            instance.vm_state = state
            self._test_init_instance_retries_reboot(instance, 'SOFT',
                                                    power_state.RUNNING)

    def test_init_instance_retries_reboot_pending_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_PENDING_HARD
        for state in vm_states.ALLOW_HARD_REBOOT:
            # NOTE(dave-mcnally) while a reboot of a vm in error state is
            # possible we don't attempt to recover an error during init
            if state == vm_states.ERROR:
                continue
            instance.vm_state = state
            self._test_init_instance_retries_reboot(instance, 'HARD',
                                                    power_state.RUNNING)

    def test_init_instance_retries_reboot_pending_soft_became_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_PENDING
        for state in vm_states.ALLOW_HARD_REBOOT:
            # NOTE(dave-mcnally) while a reboot of a vm in error state is
            # possible we don't attempt to recover an error during init
            if state == vm_states.ERROR:
                continue
            instance.vm_state = state
            with mock.patch.object(instance, 'save'):
                self._test_init_instance_retries_reboot(instance, 'HARD',
                                                        power_state.SHUTDOWN)
                self.assertEqual(task_states.REBOOT_PENDING_HARD,
                                instance.task_state)

    def test_init_instance_retries_reboot_started(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        with mock.patch.object(instance, 'save'):
            self._test_init_instance_retries_reboot(instance, 'HARD',
                                                    power_state.NOSTATE)

    def test_init_instance_retries_reboot_started_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED_HARD
        self._test_init_instance_retries_reboot(instance, 'HARD',
                                                power_state.NOSTATE)

    def _test_init_instance_cleans_reboot_state(self, instance):
        instance.host = self.compute.host
        with test.nested(
            mock.patch.object(self.compute, '_get_power_state',
                               return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save', autospec=True),
            mock.patch.object(objects.Instance, 'get_network_info')
          ) as (
            _get_power_state,
            instance_save,
            get_network_info
          ):
            self.compute._init_instance(self.context, instance)
            instance_save.assert_called_once_with()
            self.assertIsNone(instance.task_state)
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)

    def test_init_instance_cleans_image_state_reboot_started(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

    def test_init_instance_cleans_image_state_reboot_started_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.REBOOT_STARTED_HARD
        instance.power_state = power_state.RUNNING
        self._test_init_instance_cleans_reboot_state(instance)

    def test_init_instance_retries_power_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_OFF
        instance.host = self.compute.host
        with mock.patch.object(self.compute, 'stop_instance'):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance, True)
            self.compute.stop_instance.assert_has_calls([call])

    def test_init_instance_retries_power_on(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_ON
        instance.host = self.compute.host
        with mock.patch.object(self.compute, 'start_instance'):
            self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.start_instance.assert_has_calls([call])

    def test_init_instance_retries_power_on_silent_exception(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_ON
        instance.host = self.compute.host
        with mock.patch.object(self.compute, 'start_instance',
                              return_value=Exception):
            init_return = self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance)
            self.compute.start_instance.assert_has_calls([call])
            self.assertIsNone(init_return)

    def test_init_instance_retries_power_off_silent_exception(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.id = 1
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = task_states.POWERING_OFF
        instance.host = self.compute.host
        with mock.patch.object(self.compute, 'stop_instance',
                              return_value=Exception):
            init_return = self.compute._init_instance(self.context, instance)
            call = mock.call(self.context, instance, True)
            self.compute.stop_instance.assert_has_calls([call])
            self.assertIsNone(init_return)

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    def test_get_instances_on_driver(self, mock_instance_list):
        driver_instances = []
        for x in range(10):
            driver_instances.append(fake_instance.fake_db_instance())

        def _make_instance_list(db_list):
            return instance_obj._make_instance_list(
                    self.context, objects.InstanceList(), db_list, None)

        driver_uuids = [inst['uuid'] for inst in driver_instances]
        mock_instance_list.return_value = _make_instance_list(driver_instances)

        with mock.patch.object(self.compute.driver,
                               'list_instance_uuids') as mock_driver_uuids:
            mock_driver_uuids.return_value = driver_uuids
            result = self.compute._get_instances_on_driver(self.context)

        self.assertEqual([x['uuid'] for x in driver_instances],
                         [x['uuid'] for x in result])
        expected_filters = {'uuid': driver_uuids}
        mock_instance_list.assert_called_with(self.context, expected_filters,
                                              use_slave=True)

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    def test_get_instances_on_driver_empty(self, mock_instance_list):
        with mock.patch.object(self.compute.driver,
                               'list_instance_uuids') as mock_driver_uuids:
            mock_driver_uuids.return_value = []
            result = self.compute._get_instances_on_driver(self.context)

        # Short circuit DB call, get_by_filters should not be called
        self.assertEqual(0, mock_instance_list.call_count)
        self.assertEqual(1, mock_driver_uuids.call_count)
        self.assertEqual([], [x['uuid'] for x in result])

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    def test_get_instances_on_driver_fallback(self, mock_instance_list):
        # Test getting instances when driver doesn't support
        # 'list_instance_uuids'
        self.compute.host = 'host'
        filters = {}

        self.flags(instance_name_template='inst-%i')

        all_instances = []
        driver_instances = []
        for x in range(10):
            instance = fake_instance.fake_db_instance(name='inst-%i' % x,
                                                      id=x)
            if x % 2:
                driver_instances.append(instance)
            all_instances.append(instance)

        def _make_instance_list(db_list):
            return instance_obj._make_instance_list(
                    self.context, objects.InstanceList(), db_list, None)

        driver_instance_names = [inst['name'] for inst in driver_instances]
        mock_instance_list.return_value = _make_instance_list(all_instances)

        with test.nested(
            mock.patch.object(self.compute.driver, 'list_instance_uuids'),
            mock.patch.object(self.compute.driver, 'list_instances')
        ) as (
            mock_driver_uuids,
            mock_driver_instances
        ):
            mock_driver_uuids.side_effect = NotImplementedError()
            mock_driver_instances.return_value = driver_instance_names
            result = self.compute._get_instances_on_driver(self.context,
                                                           filters)

        self.assertEqual([x['uuid'] for x in driver_instances],
                         [x['uuid'] for x in result])
        expected_filters = {'host': self.compute.host}
        mock_instance_list.assert_called_with(self.context, expected_filters,
                                              use_slave=True)

    def test_instance_usage_audit(self):
        instances = [objects.Instance(uuid=uuids.instance)]

        def fake_task_log(*a, **k):
            pass

        def fake_get(*a, **k):
            return instances

        self.flags(instance_usage_audit=True)
        with test.nested(
            mock.patch.object(objects.TaskLog, 'get',
                              side_effect=fake_task_log),
            mock.patch.object(objects.InstanceList,
                              'get_active_by_window_joined',
                              side_effect=fake_get),
            mock.patch.object(objects.TaskLog, 'begin_task',
                              side_effect=fake_task_log),
            mock.patch.object(objects.TaskLog, 'end_task',
                              side_effect=fake_task_log),
            mock.patch.object(compute_utils, 'notify_usage_exists')
        ) as (mock_get, mock_get_active, mock_begin, mock_end, mock_notify):
            self.compute._instance_usage_audit(self.context)
            mock_notify.assert_called_once_with(self.compute.notifier,
                self.context, instances[0], ignore_missing_network_data=False)
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_get_active.called)
            self.assertTrue(mock_begin.called)
            self.assertTrue(mock_end.called)

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

    @mock.patch('nova.objects.InstanceList.get_by_host', new=mock.Mock())
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_query_driver_power_state_and_sync',
                new_callable=mock.NonCallableMock)
    def test_sync_power_states_virt_driver_not_ready(self, _mock_sync):
        """"Tests that the periodic task exits early if the driver raises
        VirtDriverNotReady.
        """
        with mock.patch.object(
                self.compute.driver, 'get_num_instances',
                side_effect=exception.VirtDriverNotReady) as gni:
            self.compute._sync_power_states(mock.sentinel.context)
        gni.assert_called_once_with()

    def _get_sync_instance(self, power_state, vm_state, task_state=None,
                           shutdown_terminate=False):
        instance = objects.Instance()
        instance.uuid = uuids.instance
        instance.power_state = power_state
        instance.vm_state = vm_state
        instance.host = self.compute.host
        instance.task_state = task_state
        instance.shutdown_terminate = shutdown_terminate
        return instance

    @mock.patch.object(objects.Instance, 'refresh')
    def test_sync_instance_power_state_match(self, mock_refresh):
        instance = self._get_sync_instance(power_state.RUNNING,
                                           vm_states.ACTIVE)
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.RUNNING)
        mock_refresh.assert_called_once_with(use_slave=False)

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(objects.Instance, 'save')
    def test_sync_instance_power_state_running_stopped(self, mock_save,
                                                       mock_refresh):
        instance = self._get_sync_instance(power_state.RUNNING,
                                           vm_states.ACTIVE)
        self.compute._sync_instance_power_state(self.context, instance,
                                                power_state.SHUTDOWN)
        self.assertEqual(instance.power_state, power_state.SHUTDOWN)
        mock_refresh.assert_called_once_with(use_slave=False)
        self.assertTrue(mock_save.called)

    def _test_sync_to_stop(self, power_state, vm_state, driver_power_state,
                           stop=True, force=False, shutdown_terminate=False):
        instance = self._get_sync_instance(
            power_state, vm_state, shutdown_terminate=shutdown_terminate)

        with test.nested(
            mock.patch.object(objects.Instance, 'refresh'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(self.compute.compute_api, 'stop'),
            mock.patch.object(self.compute.compute_api, 'delete'),
            mock.patch.object(self.compute.compute_api, 'force_stop'),
        ) as (mock_refresh, mock_save, mock_stop, mock_delete, mock_force):
            self.compute._sync_instance_power_state(self.context, instance,
                                                    driver_power_state)
            if shutdown_terminate:
                mock_delete.assert_called_once_with(self.context, instance)
            elif stop:
                if force:
                    mock_force.assert_called_once_with(self.context, instance)
                else:
                    mock_stop.assert_called_once_with(self.context, instance)
            mock_refresh.assert_called_once_with(use_slave=False)
            self.assertTrue(mock_save.called)

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
            db_instance = objects.Instance(uuid=uuids.db_instance,
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
            db_instance = objects.Instance(uuid=uuids.db_instance,
                                           task_state=None)
            self.compute._query_driver_power_state_and_sync(self.context,
                                                            db_instance)
            mock_get_info.assert_called_once_with(db_instance)
            mock_sync_power_state.assert_called_once_with(self.context,
                                                          db_instance,
                                                          power_state.NOSTATE,
                                                          use_slave=True)

    @mock.patch.object(virt_driver.ComputeDriver, 'delete_instance_files')
    @mock.patch.object(objects.InstanceList, 'get_by_filters')
    def test_run_pending_deletes(self, mock_get, mock_delete):
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

        def _fake_get(ctx, filter, expected_attrs, use_slave):
            mock_get.assert_called_once_with(
                {'read_deleted': 'yes'},
                {'deleted': True, 'soft_deleted': False, 'host': 'fake-mini',
                 'cleaned': False},
                expected_attrs=['system_metadata'],
                use_slave=True)
            return [a, b, c]

        a = FakeInstance(uuids.instanceA, 'apple', {'clean_attempts': '100'})
        b = FakeInstance(uuids.instanceB, 'orange', {'clean_attempts': '3'})
        c = FakeInstance(uuids.instanceC, 'banana', {})

        mock_get.side_effect = _fake_get
        mock_delete.side_effect = [True, False]

        self.compute._run_pending_deletes({})

        self.assertFalse(a.cleaned)
        self.assertEqual('100', a.system_metadata['clean_attempts'])
        self.assertTrue(b.cleaned)
        self.assertEqual('4', b.system_metadata['clean_attempts'])
        self.assertFalse(c.cleaned)
        self.assertEqual('1', c.system_metadata['clean_attempts'])
        mock_delete.assert_has_calls([mock.call(mock.ANY),
                                      mock.call(mock.ANY)])

    @mock.patch.object(objects.Migration, 'obj_as_admin')
    @mock.patch.object(objects.Migration, 'save')
    @mock.patch.object(objects.MigrationList, 'get_by_filters')
    @mock.patch.object(objects.InstanceList, 'get_by_filters')
    def _test_cleanup_incomplete_migrations(self, inst_host,
                                            mock_inst_get_by_filters,
                                            mock_migration_get_by_filters,
                                            mock_save, mock_obj_as_admin):
        def fake_inst(context, uuid, host):
            inst = objects.Instance(context)
            inst.uuid = uuid
            inst.host = host
            return inst

        def fake_migration(uuid, status, inst_uuid, src_host, dest_host):
            migration = objects.Migration()
            migration.uuid = uuid
            migration.status = status
            migration.instance_uuid = inst_uuid
            migration.source_compute = src_host
            migration.dest_compute = dest_host
            return migration

        fake_instances = [fake_inst(self.context, uuids.instance_1, inst_host),
                          fake_inst(self.context, uuids.instance_2, inst_host)]

        fake_migrations = [fake_migration(uuids.mig1, 'error',
                                          uuids.instance_1,
                                          'fake-host', 'fake-mini'),
                           fake_migration(uuids.mig2, 'error',
                                           uuids.instance_2,
                                          'fake-host', 'fake-mini')]

        mock_migration_get_by_filters.return_value = fake_migrations
        mock_inst_get_by_filters.return_value = fake_instances

        with mock.patch.object(self.compute.driver, 'delete_instance_files'):
            self.compute._cleanup_incomplete_migrations(self.context)

        # Ensure that migration status is set to 'failed' after instance
        # files deletion for those instances whose instance.host is not
        # same as compute host where periodic task is running.
        for inst in fake_instances:
            if inst.host != CONF.host:
                for mig in fake_migrations:
                    if inst.uuid == mig.instance_uuid:
                        self.assertEqual('failed', mig.status)

    def test_cleanup_incomplete_migrations_dest_node(self):
        """Test to ensure instance files are deleted from destination node.

        If instance gets deleted during resizing/revert-resizing operation,
        in that case instance files gets deleted from instance.host (source
        host here), but there is possibility that instance files could be
        present on destination node.
        This test ensures that `_cleanup_incomplete_migration` periodic
        task deletes orphaned instance files from destination compute node.
        """
        self.flags(host='fake-mini')
        self._test_cleanup_incomplete_migrations('fake-host')

    def test_cleanup_incomplete_migrations_source_node(self):
        """Test to ensure instance files are deleted from source node.

        If instance gets deleted during resizing/revert-resizing operation,
        in that case instance files gets deleted from instance.host (dest
        host here), but there is possibility that instance files could be
        present on source node.
        This test ensures that `_cleanup_incomplete_migration` periodic
        task deletes orphaned instance files from source compute node.
        """
        self.flags(host='fake-host')
        self._test_cleanup_incomplete_migrations('fake-mini')

    def test_attach_interface_failure(self):
        # Test that the fault methods are invoked when an attach fails
        db_instance = fake_instance.fake_db_instance()
        f_instance = objects.Instance._from_db_object(self.context,
                                                      objects.Instance(),
                                                      db_instance)
        e = exception.InterfaceAttachFailed(instance_uuid=f_instance.uuid)

        @mock.patch.object(compute_utils, 'EventReporter')
        @mock.patch.object(compute_utils, 'notify_about_instance_action')
        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(self.compute.network_api,
                           'allocate_port_for_instance',
                           side_effect=e)
        @mock.patch.object(self.compute, '_instance_update',
                           side_effect=lambda *a, **k: {})
        def do_test(update, meth, add_fault, notify, event):
            self.assertRaises(exception.InterfaceAttachFailed,
                              self.compute.attach_interface,
                              self.context, f_instance, 'net_id', 'port_id',
                              None, None)
            add_fault.assert_has_calls([
                    mock.call(self.context, f_instance, e,
                              mock.ANY)])
            event.assert_called_once_with(
                self.context, 'compute_attach_interface',
                f_instance.uuid)

        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_attach_interface=True):
            do_test()

    def test_detach_interface_failure(self):
        # Test that the fault methods are invoked when a detach fails

        # Build test data that will cause a PortNotFound exception
        nw_info = network_model.NetworkInfo([])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        f_instance = objects.Instance(id=3, uuid=uuids.instance,
                                      info_cache=info_cache)

        @mock.patch.object(compute_utils, 'EventReporter')
        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(self.compute, '_set_instance_obj_error_state')
        def do_test(meth, add_fault, event):
            self.assertRaises(exception.PortNotFound,
                              self.compute.detach_interface,
                              self.context, f_instance, 'port_id')
            add_fault.assert_has_calls(
                   [mock.call(self.context, f_instance, mock.ANY, mock.ANY)])
            event.assert_called_once_with(
                self.context, 'compute_detach_interface',
                f_instance.uuid)

        do_test()

    @mock.patch('nova.compute.manager.LOG.log')
    @mock.patch.object(compute_utils, 'EventReporter')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(compute_utils, 'notify_about_instance_action')
    def test_detach_interface_instance_not_found(self, mock_notify, mock_fault,
                                                 mock_event, mock_log):
        nw_info = network_model.NetworkInfo([
            network_model.VIF(uuids.port_id)])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        instance = objects.Instance(id=1, uuid=uuids.instance,
                                    info_cache=info_cache)
        with mock.patch.object(self.compute.driver, 'detach_interface',
                               side_effect=exception.InstanceNotFound(
                                   instance_id=uuids.instance)):
            self.assertRaises(exception.InterfaceDetachFailed,
                              self.compute.detach_interface,
                              self.context, instance, uuids.port_id)
            self.assertEqual(1, mock_log.call_count)
            self.assertEqual(logging.DEBUG, mock_log.call_args[0][0])

    @mock.patch.object(compute_utils, 'EventReporter')
    @mock.patch.object(virt_driver.ComputeDriver, 'get_volume_connector',
                       return_value={})
    @mock.patch.object(manager.ComputeManager, '_instance_update',
                       return_value={})
    @mock.patch.object(db, 'instance_fault_create')
    @mock.patch.object(db, 'block_device_mapping_update')
    @mock.patch.object(db,
                       'block_device_mapping_get_by_instance_and_volume_id')
    @mock.patch.object(cinder.API, 'migrate_volume_completion')
    @mock.patch.object(cinder.API, 'terminate_connection')
    @mock.patch.object(cinder.API, 'unreserve_volume')
    @mock.patch.object(cinder.API, 'get')
    @mock.patch.object(cinder.API, 'roll_detaching')
    @mock.patch.object(compute_utils, 'notify_about_volume_swap')
    def _test_swap_volume(self, mock_notify, mock_roll_detaching,
                          mock_cinder_get, mock_unreserve_volume,
                          mock_terminate_connection,
                          mock_migrate_volume_completion,
                          mock_bdm_get, mock_bdm_update,
                          mock_instance_fault_create,
                          mock_instance_update,
                          mock_get_volume_connector,
                          mock_event,
                          expected_exception=None):
        # This test ensures that volume_id arguments are passed to volume_api
        # and that volume states are OK
        volumes = {}
        volumes[uuids.old_volume] = {'id': uuids.old_volume,
                                  'display_name': 'old_volume',
                                  'status': 'detaching',
                                  'size': 1}
        volumes[uuids.new_volume] = {'id': uuids.new_volume,
                                  'display_name': 'new_volume',
                                  'status': 'available',
                                  'size': 2}

        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                   {'device_name': '/dev/vdb', 'source_type': 'volume',
                    'destination_type': 'volume',
                    'instance_uuid': uuids.instance,
                    'connection_info': '{"foo": "bar"}',
                    'volume_id': uuids.old_volume,
                    'attachment_id': None})

        def fake_vol_api_roll_detaching(context, volume_id):
            self.assertTrue(uuidutils.is_uuid_like(volume_id))
            if volumes[volume_id]['status'] == 'detaching':
                volumes[volume_id]['status'] = 'in-use'

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

        def fake_block_device_mapping_update(ctxt, id, updates, legacy):
            self.assertEqual(2, updates['volume_size'])
            return fake_bdm

        mock_roll_detaching.side_effect = fake_vol_api_roll_detaching
        mock_terminate_connection.side_effect = fake_vol_api_func
        mock_cinder_get.side_effect = fake_vol_get
        mock_migrate_volume_completion.side_effect = (
            fake_vol_migrate_volume_completion)
        mock_unreserve_volume.side_effect = fake_vol_unreserve
        mock_bdm_get.return_value = fake_bdm
        mock_bdm_update.side_effect = fake_block_device_mapping_update
        mock_instance_fault_create.return_value = (
            test_instance_fault.fake_faults['fake-uuid'][0])

        instance1 = fake_instance.fake_instance_obj(
            self.context, **{'uuid': uuids.instance})

        if expected_exception:
            volumes[uuids.old_volume]['status'] = 'detaching'
            volumes[uuids.new_volume]['status'] = 'attaching'
            self.assertRaises(expected_exception, self.compute.swap_volume,
                              self.context, uuids.old_volume, uuids.new_volume,
                              instance1, None)
            self.assertEqual('in-use', volumes[uuids.old_volume]['status'])
            self.assertEqual('available', volumes[uuids.new_volume]['status'])
            self.assertEqual(2, mock_notify.call_count)
            mock_notify.assert_any_call(
                test.MatchType(context.RequestContext), instance1,
                self.compute.host,
                fields.NotificationAction.VOLUME_SWAP,
                fields.NotificationPhase.START,
                uuids.old_volume, uuids.new_volume)
            mock_notify.assert_any_call(
                test.MatchType(context.RequestContext), instance1,
                self.compute.host,
                fields.NotificationAction.VOLUME_SWAP,
                fields.NotificationPhase.ERROR,
                uuids.old_volume, uuids.new_volume,
                test.MatchType(expected_exception))
        else:
            self.compute.swap_volume(self.context, uuids.old_volume,
                                     uuids.new_volume, instance1, None)
            self.assertEqual(volumes[uuids.old_volume]['status'], 'in-use')
            self.assertEqual(2, mock_notify.call_count)
            mock_notify.assert_any_call(test.MatchType(context.RequestContext),
                                        instance1, self.compute.host,
                                        fields.NotificationAction.VOLUME_SWAP,
                                        fields.NotificationPhase.START,
                                        uuids.old_volume, uuids.new_volume)
            mock_notify.assert_any_call(test.MatchType(context.RequestContext),
                                        instance1, self.compute.host,
                                        fields.NotificationAction.VOLUME_SWAP,
                                        fields.NotificationPhase.END,
                                        uuids.old_volume, uuids.new_volume)
        mock_event.assert_called_once_with(self.context,
                                           'compute_swap_volume',
                                           instance1.uuid)

    def _assert_volume_api(self, context, volume, *args):
        self.assertTrue(uuidutils.is_uuid_like(volume))
        return {}

    def _assert_swap_volume(self, context, old_connection_info,
                            new_connection_info, instance, mountpoint,
                            resize_to):
        self.assertEqual(2, resize_to)

    @mock.patch.object(cinder.API, 'initialize_connection')
    @mock.patch.object(fake_driver.FakeDriver, 'swap_volume')
    def test_swap_volume_volume_api_usage(self, mock_swap_volume,
                                          mock_initialize_connection):
        mock_initialize_connection.side_effect = self._assert_volume_api
        mock_swap_volume.side_effect = self._assert_swap_volume
        self._test_swap_volume()

    @mock.patch.object(cinder.API, 'initialize_connection')
    @mock.patch.object(fake_driver.FakeDriver, 'swap_volume',
                       side_effect=test.TestingException())
    def test_swap_volume_with_compute_driver_exception(
        self, mock_swap_volume, mock_initialize_connection):
        mock_initialize_connection.side_effect = self._assert_volume_api
        self._test_swap_volume(expected_exception=test.TestingException)

    @mock.patch.object(cinder.API, 'initialize_connection',
                       side_effect=test.TestingException())
    @mock.patch.object(fake_driver.FakeDriver, 'swap_volume')
    def test_swap_volume_with_initialize_connection_exception(
        self, mock_swap_volume, mock_initialize_connection):
        self._test_swap_volume(expected_exception=test.TestingException)

    @mock.patch('nova.compute.utils.notify_about_volume_swap')
    @mock.patch('nova.db.block_device_mapping_get_by_instance_and_volume_id')
    @mock.patch('nova.db.block_device_mapping_update')
    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.virt.libvirt.LibvirtDriver.get_volume_connector')
    @mock.patch('nova.compute.manager.ComputeManager._swap_volume')
    def test_swap_volume_delete_on_termination_flag(self, swap_volume_mock,
                                                    volume_connector_mock,
                                                    get_volume_mock,
                                                    update_bdm_mock,
                                                    get_bdm_mock,
                                                    notify_mock):
        # This test ensures that delete_on_termination flag arguments
        # are reserved
        volumes = {}
        old_volume_id = uuids.fake
        volumes[old_volume_id] = {'id': old_volume_id,
                                  'display_name': 'old_volume',
                                  'status': 'detaching',
                                  'size': 2}
        new_volume_id = uuids.fake_2
        volumes[new_volume_id] = {'id': new_volume_id,
                                  'display_name': 'new_volume',
                                  'status': 'available',
                                  'size': 2}
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                   {'device_name': '/dev/vdb', 'source_type': 'volume',
                    'destination_type': 'volume',
                    'instance_uuid': uuids.instance,
                    'delete_on_termination': True,
                    'connection_info': '{"foo": "bar"}',
                    'attachment_id': None})
        comp_ret = {'save_volume_id': old_volume_id}
        new_info = {"foo": "bar", "serial": old_volume_id}
        swap_volume_mock.return_value = (comp_ret, new_info)
        volume_connector_mock.return_value = {}
        update_bdm_mock.return_value = fake_bdm
        get_bdm_mock.return_value = fake_bdm
        get_volume_mock.return_value = volumes[old_volume_id]
        self.compute.swap_volume(self.context, old_volume_id, new_volume_id,
                fake_instance.fake_instance_obj(self.context,
                                                **{'uuid': uuids.instance}),
                                 None)
        update_values = {'no_device': False,
                         'connection_info': jsonutils.dumps(new_info),
                         'volume_id': old_volume_id,
                         'source_type': u'volume',
                         'snapshot_id': None,
                         'destination_type': u'volume'}
        update_bdm_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                update_values, legacy=False)

    @mock.patch.object(compute_utils, 'notify_about_volume_swap')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.volume.cinder.API.attachment_update')
    @mock.patch('nova.volume.cinder.API.attachment_delete')
    @mock.patch('nova.volume.cinder.API.attachment_complete')
    @mock.patch('nova.volume.cinder.API.migrate_volume_completion',
                return_value={'save_volume_id': uuids.old_volume_id})
    def test_swap_volume_with_new_attachment_id_cinder_migrate_true(
            self, migrate_volume_completion, attachment_complete,
            attachment_delete, attachment_update, get_volume, get_bdm,
            notify_about_volume_swap):
        """Tests a swap volume operation with a new style volume attachment
        passed in from the compute API, and the case that Cinder initiated
        the swap volume because of a volume retype situation. This is a happy
        path test. Since it is a retype there is no volume size change.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}', volume_size=1)
        old_volume = {
            'id': uuids.old_volume_id, 'size': 1, 'status': 'retyping',
            'multiattach': False
        }
        new_volume = {
            'id': uuids.new_volume_id, 'size': 1, 'status': 'reserved',
            'multiattach': False
        }
        attachment_update.return_value = {"connection_info": {"data": {}}}
        get_bdm.return_value = bdm
        get_volume.side_effect = (old_volume, new_volume)
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.driver, 'get_volume_connector',
                              return_value=mock.sentinel.connector),
            mock.patch.object(bdm, 'save')
        ) as (
            mock_elevated, mock_get_volume_connector, mock_save
        ):
            self.compute.swap_volume(
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                instance, uuids.new_attachment_id)
            # Assert the expected calls.
            get_bdm.assert_called_once_with(
                self.context, uuids.old_volume_id, instance.uuid)
            # We updated the new attachment with the host connector.
            attachment_update.assert_called_once_with(
                self.context, uuids.new_attachment_id, mock.sentinel.connector,
                bdm.device_name)
            # We tell Cinder that the new volume is connected
            attachment_complete.assert_called_once_with(
                self.context, uuids.new_attachment_id)
            # After a successful swap volume, we deleted the old attachment.
            attachment_delete.assert_called_once_with(
                self.context, uuids.old_attachment_id)
            # After a successful swap volume, we tell Cinder so it can complete
            # the retype operation.
            migrate_volume_completion.assert_called_once_with(
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                error=False)
            # The BDM should have been updated. Since it's a retype, the old
            # volume ID is returned from Cinder so that's what goes into the
            # BDM but the new attachment ID is saved.
            mock_save.assert_called_once_with()
            self.assertEqual(uuids.old_volume_id, bdm.volume_id)
            self.assertEqual(uuids.new_attachment_id, bdm.attachment_id)
            self.assertEqual(1, bdm.volume_size)
            self.assertEqual(uuids.old_volume_id,
                             jsonutils.loads(bdm.connection_info)['serial'])

    @mock.patch.object(compute_utils, 'notify_about_volume_swap')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.volume.cinder.API.attachment_update')
    @mock.patch('nova.volume.cinder.API.attachment_delete')
    @mock.patch('nova.volume.cinder.API.attachment_complete')
    @mock.patch('nova.volume.cinder.API.migrate_volume_completion')
    def test_swap_volume_with_new_attachment_id_cinder_migrate_false(
            self, migrate_volume_completion, attachment_complete,
            attachment_delete, attachment_update, get_volume, get_bdm,
            notify_about_volume_swap):
        """Tests a swap volume operation with a new style volume attachment
        passed in from the compute API, and the case that Cinder did not
        initiate the swap volume. This is a happy path test. Since it is not a
        retype we also change the size.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}')
        old_volume = {
            'id': uuids.old_volume_id, 'size': 1, 'status': 'detaching',
            'multiattach': False
        }
        new_volume = {
            'id': uuids.new_volume_id, 'size': 2, 'status': 'reserved',
            'multiattach': False
        }
        attachment_update.return_value = {"connection_info": {"data": {}}}
        get_bdm.return_value = bdm
        get_volume.side_effect = (old_volume, new_volume)
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.driver, 'get_volume_connector',
                              return_value=mock.sentinel.connector),
            mock.patch.object(bdm, 'save')
        ) as (
            mock_elevated, mock_get_volume_connector, mock_save
        ):
            self.compute.swap_volume(
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                instance, uuids.new_attachment_id)
            # Assert the expected calls.
            get_bdm.assert_called_once_with(
                self.context, uuids.old_volume_id, instance.uuid)
            # We updated the new attachment with the host connector.
            attachment_update.assert_called_once_with(
                self.context, uuids.new_attachment_id, mock.sentinel.connector,
                bdm.device_name)
            # We tell Cinder that the new volume is connected
            attachment_complete.assert_called_once_with(
                self.context, uuids.new_attachment_id)
            # After a successful swap volume, we deleted the old attachment.
            attachment_delete.assert_called_once_with(
                self.context, uuids.old_attachment_id)
            # After a successful swap volume, since it was not a
            # Cinder-initiated call, we don't call migrate_volume_completion.
            migrate_volume_completion.assert_not_called()
            # The BDM should have been updated. Since it's a not a retype, the
            # volume_id is now the new volume ID.
            mock_save.assert_called_once_with()
            self.assertEqual(uuids.new_volume_id, bdm.volume_id)
            self.assertEqual(uuids.new_attachment_id, bdm.attachment_id)
            self.assertEqual(2, bdm.volume_size)
            new_conn_info = jsonutils.loads(bdm.connection_info)
            self.assertEqual(uuids.new_volume_id, new_conn_info['serial'])
            self.assertNotIn('multiattach', new_conn_info)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(compute_utils, 'notify_about_volume_swap')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.volume.cinder.API.attachment_update',
                side_effect=exception.VolumeAttachmentNotFound(
                    attachment_id=uuids.new_attachment_id))
    @mock.patch('nova.volume.cinder.API.roll_detaching')
    @mock.patch('nova.volume.cinder.API.attachment_delete')
    @mock.patch('nova.volume.cinder.API.migrate_volume_completion')
    def test_swap_volume_with_new_attachment_id_attachment_update_fails(
            self, migrate_volume_completion, attachment_delete, roll_detaching,
            attachment_update, get_volume, get_bdm, notify_about_volume_swap,
            add_instance_fault_from_exc):
        """Tests a swap volume operation with a new style volume attachment
        passed in from the compute API, and the case that Cinder initiated
        the swap volume because of a volume migrate situation. This is a
        negative test where attachment_update fails.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}')
        old_volume = {
            'id': uuids.old_volume_id, 'size': 1, 'status': 'migrating',
            'multiattach': False
        }
        new_volume = {
            'id': uuids.new_volume_id, 'size': 1, 'status': 'reserved',
            'multiattach': False
        }
        get_bdm.return_value = bdm
        get_volume.side_effect = (old_volume, new_volume)
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.driver, 'get_volume_connector',
                              return_value=mock.sentinel.connector)
        ) as (
            mock_elevated, mock_get_volume_connector
        ):
            self.assertRaises(
                exception.VolumeAttachmentNotFound, self.compute.swap_volume,
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                instance, uuids.new_attachment_id)
            # Assert the expected calls.
            get_bdm.assert_called_once_with(
                self.context, uuids.old_volume_id, instance.uuid)
            # We tried to update the new attachment with the host connector.
            attachment_update.assert_called_once_with(
                self.context, uuids.new_attachment_id, mock.sentinel.connector,
                bdm.device_name)
            # After a failure, we rollback the detaching status of the old
            # volume.
            roll_detaching.assert_called_once_with(
                self.context, uuids.old_volume_id)
            # After a failure, we deleted the new attachment.
            attachment_delete.assert_called_once_with(
                self.context, uuids.new_attachment_id)
            # After a failure for a Cinder-initiated swap volume, we called
            # migrate_volume_completion to let Cinder know things blew up.
            migrate_volume_completion.assert_called_once_with(
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                error=True)

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(compute_utils, 'notify_about_volume_swap')
    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance')
    @mock.patch('nova.volume.cinder.API.get')
    @mock.patch('nova.volume.cinder.API.attachment_update')
    @mock.patch('nova.volume.cinder.API.roll_detaching')
    @mock.patch('nova.volume.cinder.API.attachment_delete')
    @mock.patch('nova.volume.cinder.API.migrate_volume_completion')
    def test_swap_volume_with_new_attachment_id_driver_swap_fails(
            self, migrate_volume_completion, attachment_delete, roll_detaching,
            attachment_update, get_volume, get_bdm, notify_about_volume_swap,
            add_instance_fault_from_exc):
        """Tests a swap volume operation with a new style volume attachment
        passed in from the compute API, and the case that Cinder did not
        initiate the swap volume. This is a negative test where the compute
        driver swap_volume method fails.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}')
        old_volume = {
            'id': uuids.old_volume_id, 'size': 1, 'status': 'detaching',
            'multiattach': False
        }
        new_volume = {
            'id': uuids.new_volume_id, 'size': 2, 'status': 'reserved',
            'multiattach': False
        }
        attachment_update.return_value = {"connection_info": {"data": {}}}
        get_bdm.return_value = bdm
        get_volume.side_effect = (old_volume, new_volume)
        instance = fake_instance.fake_instance_obj(self.context)
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.driver, 'get_volume_connector',
                              return_value=mock.sentinel.connector),
            mock.patch.object(self.compute.driver, 'swap_volume',
                              side_effect=test.TestingException('yikes'))
        ) as (
            mock_elevated, mock_get_volume_connector, mock_driver_swap
        ):
            self.assertRaises(
                test.TestingException, self.compute.swap_volume,
                self.context, uuids.old_volume_id, uuids.new_volume_id,
                instance, uuids.new_attachment_id)
            # Assert the expected calls.
            # The new connection_info has the new_volume_id as the serial.
            new_cinfo = mock_driver_swap.call_args[0][2]
            self.assertIn('serial', new_cinfo)
            self.assertEqual(uuids.new_volume_id, new_cinfo['serial'])
            get_bdm.assert_called_once_with(
                self.context, uuids.old_volume_id, instance.uuid)
            # We updated the new attachment with the host connector.
            attachment_update.assert_called_once_with(
                self.context, uuids.new_attachment_id, mock.sentinel.connector,
                bdm.device_name)
            # After a failure, we rollback the detaching status of the old
            # volume.
            roll_detaching.assert_called_once_with(
                self.context, uuids.old_volume_id)
            # After a failed swap volume, we deleted the new attachment.
            attachment_delete.assert_called_once_with(
                self.context, uuids.new_attachment_id)
            # After a failed swap volume, since it was not a
            # Cinder-initiated call, we don't call migrate_volume_completion.
            migrate_volume_completion.assert_not_called()

    @mock.patch('nova.volume.cinder.API.attachment_update')
    def test_swap_volume_with_multiattach(self, attachment_update):
        """Tests swap volume where the volume being swapped-to supports
        multiattach as well as the compute driver, so the attachment for the
        new volume (created in the API) is updated with the host connector
        and the new_connection_info is updated with the multiattach flag.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}')
        new_volume = {
            'id': uuids.new_volume_id, 'size': 2, 'status': 'reserved',
            'multiattach': True
        }
        attachment_update.return_value = {"connection_info": {"data": {}}}
        connector = mock.sentinel.connector
        with mock.patch.dict(self.compute.driver.capabilities,
                             {'supports_multiattach': True}):
            _, new_cinfo = self.compute._init_volume_connection(
                self.context, new_volume, uuids.old_volume_id,
                connector, bdm, uuids.new_attachment_id, bdm.device_name)
            self.assertEqual(uuids.new_volume_id, new_cinfo['serial'])
            self.assertIn('multiattach', new_cinfo)
            self.assertTrue(new_cinfo['multiattach'])
            attachment_update.assert_called_once_with(
                self.context, uuids.new_attachment_id, connector,
                bdm.device_name)

    def test_swap_volume_with_multiattach_no_driver_support(self):
        """Tests a swap volume scenario where the new volume being swapped-to
        supports multiattach but the virt driver does not, so swap volume
        fails.
        """
        bdm = objects.BlockDeviceMapping(
            volume_id=uuids.old_volume_id, device_name='/dev/vda',
            attachment_id=uuids.old_attachment_id,
            connection_info='{"data": {}}')
        new_volume = {
            'id': uuids.new_volume_id, 'size': 2, 'status': 'reserved',
            'multiattach': True
        }
        connector = {'host': 'localhost'}
        with mock.patch.dict(self.compute.driver.capabilities,
                             {'supports_multiattach': False}):
            self.assertRaises(exception.MultiattachNotSupportedByVirtDriver,
                              self.compute._init_volume_connection,
                              self.context, new_volume, uuids.old_volume_id,
                              connector, bdm, uuids.new_attachment_id,
                              bdm.device_name)

    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(fake_driver.FakeDriver,
                       'check_can_live_migrate_source')
    @mock.patch.object(manager.ComputeManager,
                       '_get_instance_block_device_info')
    @mock.patch.object(compute_utils, 'is_volume_backed_instance')
    @mock.patch.object(compute_utils, 'EventReporter')
    def test_check_can_live_migrate_source(self, mock_event, mock_volume,
                                           mock_get_inst, mock_check,
                                           mock_get_bdms):
        fake_bdms = objects.BlockDeviceMappingList()
        mock_get_bdms.return_value = fake_bdms
        is_volume_backed = 'volume_backed'
        dest_check_data = migrate_data_obj.LiveMigrateData()
        db_instance = fake_instance.fake_db_instance()
        instance = objects.Instance._from_db_object(
                self.context, objects.Instance(), db_instance)

        mock_volume.return_value = is_volume_backed
        mock_get_inst.return_value = {'block_device_mapping': 'fake'}

        self.compute.check_can_live_migrate_source(
                self.context, instance=instance,
                dest_check_data=dest_check_data)
        mock_event.assert_called_once_with(
            self.context, 'compute_check_can_live_migrate_source',
            instance.uuid)
        mock_check.assert_called_once_with(self.context, instance,
                                           dest_check_data,
                                           {'block_device_mapping': 'fake'})
        mock_volume.assert_called_once_with(self.context, instance, fake_bdms)
        mock_get_inst.assert_called_once_with(self.context, instance,
                                              refresh_conn_info=False,
                                              bdms=fake_bdms)

        self.assertTrue(dest_check_data.is_volume_backed)

    def _test_check_can_live_migrate_destination(self, do_raise=False):
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

        with test.nested(
            mock.patch.object(self.compute, '_get_compute_info'),
            mock.patch.object(self.compute.driver,
                              'check_can_live_migrate_destination'),
            mock.patch.object(self.compute.compute_rpcapi,
                              'check_can_live_migrate_source'),
            mock.patch.object(self.compute.driver,
                              'cleanup_live_migration_destination_check'),
            mock.patch.object(db, 'instance_fault_create'),
            mock.patch.object(compute_utils, 'EventReporter')
        ) as (mock_get, mock_check_dest, mock_check_src, mock_check_clean,
              mock_fault_create, mock_event):
            mock_get.side_effect = (src_info, dest_info)
            mock_check_dest.return_value = dest_check_data

            if do_raise:
                mock_check_src.side_effect = test.TestingException
                mock_fault_create.return_value = \
                    test_instance_fault.fake_faults['fake-uuid'][0]
            else:
                mock_check_src.return_value = mig_data

            result = self.compute.check_can_live_migrate_destination(
                self.context, instance=instance,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

            if do_raise:
                mock_fault_create.assert_called_once_with(self.context,
                                                          mock.ANY)
            mock_check_src.assert_called_once_with(self.context, instance,
                                                   dest_check_data)
            mock_check_clean.assert_called_once_with(self.context,
                                                     dest_check_data)
            mock_get.assert_has_calls([mock.call(self.context, 'fake-host'),
                                       mock.call(self.context, CONF.host)])
            mock_check_dest.assert_called_once_with(self.context, instance,
                        src_info, dest_info, block_migration, disk_over_commit)

            self.assertEqual(mig_data, result)
            mock_event.assert_called_once_with(
                self.context, 'compute_check_can_live_migrate_destination',
                instance.uuid)

    def test_check_can_live_migrate_destination_success(self):
        self._test_check_can_live_migrate_destination()

    def test_check_can_live_migrate_destination_fail(self):
        self.assertRaises(
                test.TestingException,
                self._test_check_can_live_migrate_destination,
                do_raise=True)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_prepare_for_instance_event(self, lock_name_mock):
        inst_obj = objects.Instance(uuid=uuids.instance)
        result = self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event', None)
        self.assertIn(uuids.instance, self.compute.instance_events._events)
        self.assertIn(('test-event', None),
                      self.compute.instance_events._events[uuids.instance])
        self.assertEqual(
            result,
            self.compute.instance_events._events[uuids.instance]
                                                [('test-event', None)])
        self.assertTrue(hasattr(result, 'send'))
        lock_name_mock.assert_called_once_with(inst_obj)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_pop_instance_event(self, lock_name_mock):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            uuids.instance: {
                ('network-vif-plugged', None): event,
                }
            }
        inst_obj = objects.Instance(uuid=uuids.instance)
        event_obj = objects.InstanceExternalEvent(name='network-vif-plugged',
                                                  tag=None)
        result = self.compute.instance_events.pop_instance_event(inst_obj,
                                                                 event_obj)
        self.assertEqual(result, event)
        lock_name_mock.assert_called_once_with(inst_obj)

    @mock.patch('nova.compute.manager.InstanceEvents._lock_name')
    def test_clear_events_for_instance(self, lock_name_mock):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            uuids.instance: {
                ('test-event', None): event,
                }
            }
        inst_obj = objects.Instance(uuid=uuids.instance)
        result = self.compute.instance_events.clear_events_for_instance(
            inst_obj)
        self.assertEqual(result, {'test-event-None': event})
        lock_name_mock.assert_called_once_with(inst_obj)

    def test_instance_events_lock_name(self):
        inst_obj = objects.Instance(uuid=uuids.instance)
        result = self.compute.instance_events._lock_name(inst_obj)
        self.assertEqual(result, "%s-events" % uuids.instance)

    def test_prepare_for_instance_event_again(self):
        inst_obj = objects.Instance(uuid=uuids.instance)
        self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event', None)
        # A second attempt will avoid creating a new list; make sure we
        # get the current list
        result = self.compute.instance_events.prepare_for_instance_event(
            inst_obj, 'test-event', None)
        self.assertIn(uuids.instance, self.compute.instance_events._events)
        self.assertIn(('test-event', None),
                      self.compute.instance_events._events[uuids.instance])
        self.assertEqual(
            result,
            self.compute.instance_events._events[uuids.instance]
                                                [('test-event', None)])
        self.assertTrue(hasattr(result, 'send'))

    def test_process_instance_event(self):
        event = eventlet_event.Event()
        self.compute.instance_events._events = {
            uuids.instance: {
                ('network-vif-plugged', None): event,
                }
            }
        inst_obj = objects.Instance(uuid=uuids.instance)
        event_obj = objects.InstanceExternalEvent(name='network-vif-plugged',
                                                  tag=None)
        self.compute._process_instance_event(inst_obj, event_obj)
        self.assertTrue(event.ready())
        self.assertEqual(event_obj, event.wait())
        self.assertEqual({}, self.compute.instance_events._events)

    @mock.patch('nova.compute.manager.LOG')
    def test_process_instance_event_deleting(self, mock_log):
        """Tests that we don't log a warning when we get a
        network-vif-unplugged event for an instance that's being deleted.
        """
        inst_obj = objects.Instance(uuid=uuids.instance,
                                    vm_state=vm_states.ACTIVE,
                                    task_state=task_states.DELETING)
        event_obj = objects.InstanceExternalEvent(name='network-vif-unplugged',
                                                  tag=uuids.port_id)
        with mock.patch.object(self.compute.instance_events,
                               'pop_instance_event', return_value=None):
            self.compute._process_instance_event(inst_obj, event_obj)
        # assert we logged at debug level
        mock_log.debug.assert_called()
        self.assertThat(mock_log.debug.call_args[0][0],
                        testtools.matchers.MatchesRegex(
                            'Received event .* for instance which is being '
                            'deleted.'))

    @mock.patch('nova.compute.manager.LOG')
    def test_process_instance_event_unexpected_warning(self, mock_log):
        """Tests that we log a warning when we get an unexpected event."""
        inst_obj = objects.Instance(uuid=uuids.instance,
                                    vm_state=vm_states.ACTIVE,
                                    task_state=None)
        event_obj = objects.InstanceExternalEvent(name='network-vif-unplugged',
                                                  tag=uuids.port_id)
        with mock.patch.object(self.compute.instance_events,
                               'pop_instance_event', return_value=None):
            self.compute._process_instance_event(inst_obj, event_obj)
        # assert we logged at warning level
        mock_log.warning.assert_called()
        self.assertThat(mock_log.warning.call_args[0][0],
                        testtools.matchers.MatchesRegex(
                            'Received unexpected event .* for '
                            'instance with vm_state .* and '
                            'task_state .*.'))

    def test_process_instance_vif_deleted_event(self):
        vif1 = fake_network_cache_model.new_vif()
        vif1['id'] = '1'
        vif2 = fake_network_cache_model.new_vif()
        vif2['id'] = '2'
        nw_info = network_model.NetworkInfo([vif1, vif2])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        inst_obj = objects.Instance(id=3, uuid=uuids.instance,
                                    info_cache=info_cache)

        @mock.patch.object(manager.base_net_api,
                           'update_instance_cache_with_nw_info')
        @mock.patch.object(self.compute.driver, 'detach_interface')
        def do_test(detach_interface, update_instance_cache_with_nw_info):
            self.compute._process_instance_vif_deleted_event(self.context,
                                                             inst_obj,
                                                             vif2['id'])
            update_instance_cache_with_nw_info.assert_called_once_with(
                                                   self.compute.network_api,
                                                   self.context,
                                                   inst_obj,
                                                   nw_info=[vif1])
            detach_interface.assert_called_once_with(self.context,
                                                     inst_obj, vif2)
        do_test()

    def test_process_instance_vif_deleted_event_not_implemented_error(self):
        """Tests the case where driver.detach_interface raises
        NotImplementedError.
        """
        vif = fake_network_cache_model.new_vif()
        nw_info = network_model.NetworkInfo([vif])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        inst_obj = objects.Instance(id=3, uuid=uuids.instance,
                                    info_cache=info_cache)

        @mock.patch.object(manager.base_net_api,
                           'update_instance_cache_with_nw_info')
        @mock.patch.object(self.compute.driver, 'detach_interface',
                           side_effect=NotImplementedError)
        def do_test(detach_interface, update_instance_cache_with_nw_info):
            self.compute._process_instance_vif_deleted_event(
                self.context, inst_obj, vif['id'])
            update_instance_cache_with_nw_info.assert_called_once_with(
                self.compute.network_api, self.context, inst_obj, nw_info=[])
            detach_interface.assert_called_once_with(
                self.context, inst_obj, vif)

        do_test()

    def test_extend_volume(self):
        inst_obj = objects.Instance(id=3, uuid=uuids.instance)
        connection_info = {'foo': 'bar'}
        bdm = objects.BlockDeviceMapping(
            source_type='volume',
            destination_type='volume',
            volume_id=uuids.volume_id,
            volume_size=10,
            instance_uuid=uuids.instance,
            device_name='/dev/vda',
            connection_info=jsonutils.dumps(connection_info))

        @mock.patch.object(self.compute, 'volume_api')
        @mock.patch.object(self.compute.driver, 'extend_volume')
        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance')
        @mock.patch.object(objects.BlockDeviceMapping, 'save')
        def do_test(bdm_save, bdm_get_by_vol_and_inst, extend_volume,
                    volume_api):
            bdm_get_by_vol_and_inst.return_value = bdm
            volume_api.get.return_value = {'size': 20}

            self.compute.extend_volume(
                self.context, inst_obj, uuids.volume_id)
            bdm_save.assert_called_once_with()
            extend_volume.assert_called_once_with(
                connection_info, inst_obj)

        do_test()

    def test_extend_volume_not_implemented_error(self):
        """Tests the case where driver.extend_volume raises
        NotImplementedError.
        """
        inst_obj = objects.Instance(id=3, uuid=uuids.instance)
        connection_info = {'foo': 'bar'}
        bdm = objects.BlockDeviceMapping(
            source_type='volume',
            destination_type='volume',
            volume_id=uuids.volume_id,
            volume_size=10,
            instance_uuid=uuids.instance,
            device_name='/dev/vda',
            connection_info=jsonutils.dumps(connection_info))

        @mock.patch.object(self.compute, 'volume_api')
        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance')
        @mock.patch.object(objects.BlockDeviceMapping, 'save')
        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        def do_test(add_fault_mock, bdm_save, bdm_get_by_vol_and_inst,
                    volume_api):
            bdm_get_by_vol_and_inst.return_value = bdm
            volume_api.get.return_value = {'size': 20}
            self.assertRaises(
                exception.ExtendVolumeNotSupported,
                self.compute.extend_volume,
                self.context, inst_obj, uuids.volume_id)
            add_fault_mock.assert_called_once_with(
                self.context, inst_obj, mock.ANY, mock.ANY)

        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_extend_volume=False):
            do_test()

    def test_extend_volume_volume_not_found(self):
        """Tests the case where driver.extend_volume tries to extend
        a volume not attached to the specified instance.
        """
        inst_obj = objects.Instance(id=3, uuid=uuids.instance)

        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance',
                           side_effect=exception.NotFound())
        def do_test(bdm_get_by_vol_and_inst):
            self.compute.extend_volume(
                self.context, inst_obj, uuids.volume_id)

        do_test()

    def test_external_instance_event(self):
        instances = [
            objects.Instance(id=1, uuid=uuids.instance_1),
            objects.Instance(id=2, uuid=uuids.instance_2),
            objects.Instance(id=3, uuid=uuids.instance_3),
            objects.Instance(id=4, uuid=uuids.instance_4)]
        events = [
            objects.InstanceExternalEvent(name='network-changed',
                                          tag='tag1',
                                          instance_uuid=uuids.instance_1),
            objects.InstanceExternalEvent(name='network-vif-plugged',
                                          instance_uuid=uuids.instance_2,
                                          tag='tag2'),
            objects.InstanceExternalEvent(name='network-vif-deleted',
                                          instance_uuid=uuids.instance_3,
                                          tag='tag3'),
            objects.InstanceExternalEvent(name='volume-extended',
                                          instance_uuid=uuids.instance_4,
                                          tag='tag4')]

        @mock.patch.object(self.compute,
                           'extend_volume')
        @mock.patch.object(self.compute, '_process_instance_vif_deleted_event')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info')
        @mock.patch.object(self.compute, '_process_instance_event')
        def do_test(_process_instance_event, get_instance_nw_info,
                    _process_instance_vif_deleted_event, extend_volume):
            self.compute.external_instance_event(self.context,
                                                 instances, events)
            get_instance_nw_info.assert_called_once_with(self.context,
                                                         instances[0],
                                                         refresh_vif_id='tag1')
            _process_instance_event.assert_called_once_with(instances[1],
                                                            events[1])
            _process_instance_vif_deleted_event.assert_called_once_with(
                self.context, instances[2], events[2].tag)
            extend_volume.assert_called_once_with(
                self.context, instances[3], events[3].tag)
        do_test()

    def test_external_instance_event_with_exception(self):
        vif1 = fake_network_cache_model.new_vif()
        vif1['id'] = '1'
        vif2 = fake_network_cache_model.new_vif()
        vif2['id'] = '2'
        nw_info = network_model.NetworkInfo([vif1, vif2])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance_2)
        instances = [
            objects.Instance(id=1, uuid=uuids.instance_1),
            objects.Instance(id=2, uuid=uuids.instance_2,
                             info_cache=info_cache),
            objects.Instance(id=3, uuid=uuids.instance_3),
            # instance_4 doesn't have info_cache set so it will be lazy-loaded
            # and blow up with an InstanceNotFound error.
            objects.Instance(id=4, uuid=uuids.instance_4),
            objects.Instance(id=5, uuid=uuids.instance_5),
        ]
        events = [
            objects.InstanceExternalEvent(name='network-changed',
                                          tag='tag1',
                                          instance_uuid=uuids.instance_1),
            objects.InstanceExternalEvent(name='network-vif-deleted',
                                          instance_uuid=uuids.instance_2,
                                          tag='2'),
            objects.InstanceExternalEvent(name='network-vif-plugged',
                                          instance_uuid=uuids.instance_3,
                                          tag='tag3'),
            objects.InstanceExternalEvent(name='network-vif-deleted',
                                          instance_uuid=uuids.instance_4,
                                          tag='tag4'),
            objects.InstanceExternalEvent(name='volume-extended',
                                          instance_uuid=uuids.instance_5,
                                          tag='tag5'),
        ]

        # Make sure all the four events are handled despite the exceptions in
        # processing events 1, 2, 4 and 5.
        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance',
                           side_effect=exception.InstanceNotFound(
                               instance_id=uuids.instance_5))
        @mock.patch.object(instances[3], 'obj_load_attr',
                           side_effect=exception.InstanceNotFound(
                               instance_id=uuids.instance_4))
        @mock.patch.object(manager.base_net_api,
                           'update_instance_cache_with_nw_info')
        @mock.patch.object(self.compute.driver, 'detach_interface',
                           side_effect=exception.NovaException)
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                           side_effect=exception.InstanceInfoCacheNotFound(
                                         instance_uuid=uuids.instance_1))
        @mock.patch.object(self.compute, '_process_instance_event')
        def do_test(_process_instance_event, get_instance_nw_info,
                    detach_interface, update_instance_cache_with_nw_info,
                    obj_load_attr, bdm_get_by_vol_and_inst):
            self.compute.external_instance_event(self.context,
                                                 instances, events)
            get_instance_nw_info.assert_called_once_with(self.context,
                                                         instances[0],
                                                         refresh_vif_id='tag1')
            update_instance_cache_with_nw_info.assert_called_once_with(
                                                   self.compute.network_api,
                                                   self.context,
                                                   instances[1],
                                                   nw_info=[vif1])
            detach_interface.assert_called_once_with(self.context,
                                                     instances[1], vif2)
            _process_instance_event.assert_called_once_with(instances[2],
                                                            events[2])
            obj_load_attr.assert_called_once_with('info_cache')
            bdm_get_by_vol_and_inst.assert_called_once_with(
                self.context, 'tag5', instances[4].uuid)
        do_test()

    def test_cancel_all_events(self):
        inst = objects.Instance(uuid=uuids.instance)
        fake_eventlet_event = mock.MagicMock()
        self.compute.instance_events._events = {
            inst.uuid: {
                ('network-vif-plugged', uuids.portid): fake_eventlet_event,
            }
        }
        self.compute.instance_events.cancel_all_events()
        # call it again to make sure we handle that gracefully
        self.compute.instance_events.cancel_all_events()
        self.assertTrue(fake_eventlet_event.send.called)
        event = fake_eventlet_event.send.call_args_list[0][0][0]
        self.assertEqual('network-vif-plugged', event.name)
        self.assertEqual(uuids.portid, event.tag)
        self.assertEqual('failed', event.status)

    def test_cleanup_cancels_all_events(self):
        with mock.patch.object(self.compute, 'instance_events') as mock_ev:
            self.compute.cleanup_host()
            mock_ev.cancel_all_events.assert_called_once_with()

    def test_cleanup_blocks_new_events(self):
        instance = objects.Instance(uuid=uuids.instance)
        self.compute.instance_events.cancel_all_events()
        callback = mock.MagicMock()
        body = mock.MagicMock()
        with self.compute.virtapi.wait_for_instance_event(
                instance, [('network-vif-plugged', 'bar')],
                error_callback=callback):
            body()
        self.assertTrue(body.called)
        callback.assert_called_once_with('network-vif-plugged-bar', instance)

    def test_pop_events_fails_gracefully(self):
        inst = objects.Instance(uuid=uuids.instance)
        event = mock.MagicMock()
        self.compute.instance_events._events = None
        self.assertIsNone(
            self.compute.instance_events.pop_instance_event(inst, event))

    def test_clear_events_fails_gracefully(self):
        inst = objects.Instance(uuid=uuids.instance)
        self.compute.instance_events._events = None
        self.assertEqual(
            self.compute.instance_events.clear_events_for_instance(inst), {})

    def test_retry_reboot_pending_soft(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_PENDING
        instance.vm_state = vm_states.ACTIVE
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.RUNNING)
        self.assertTrue(allow_reboot)
        self.assertEqual(reboot_type, 'SOFT')

    def test_retry_reboot_pending_hard(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_PENDING_HARD
        instance.vm_state = vm_states.ACTIVE
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.RUNNING)
        self.assertTrue(allow_reboot)
        self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_soft_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_STARTED
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.NOSTATE)
        self.assertTrue(allow_reboot)
        self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_off(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_STARTED_HARD
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.NOSTATE)
        self.assertTrue(allow_reboot)
        self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_starting_hard_on(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = task_states.REBOOT_STARTED_HARD
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.RUNNING)
        self.assertFalse(allow_reboot)
        self.assertEqual(reboot_type, 'HARD')

    def test_retry_reboot_no_reboot(self):
        instance = objects.Instance(self.context)
        instance.uuid = uuids.instance
        instance.task_state = 'bar'
        allow_reboot, reboot_type = self.compute._retry_reboot(
            context, instance, power_state.RUNNING)
        self.assertFalse(allow_reboot)
        self.assertEqual(reboot_type, 'HARD')

    @mock.patch('nova.objects.BlockDeviceMapping.get_by_volume_and_instance')
    def test_remove_volume_connection(self, bdm_get):
        inst = mock.Mock()
        inst.uuid = uuids.instance_uuid
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'source_type': 'volume', 'destination_type': 'volume',
                 'volume_id': uuids.volume_id, 'device_name': '/dev/vdb',
                 'connection_info': '{"test": "test"}'})
        bdm = objects.BlockDeviceMapping(context=self.context, **fake_bdm)
        bdm_get.return_value = bdm
        with test.nested(
            mock.patch.object(self.compute, 'volume_api'),
            mock.patch.object(self.compute, 'driver'),
            mock.patch.object(driver_bdm_volume, 'driver_detach'),
        ) as (mock_volume_api, mock_virt_driver, mock_driver_detach):
            connector = mock.Mock()

            def fake_driver_detach(context, instance, volume_api, virt_driver):
                # This is just here to validate the function signature.
                pass

            # There should be an easier way to do this with autospec...
            mock_driver_detach.side_effect = fake_driver_detach
            mock_virt_driver.get_volume_connector.return_value = connector
            self.compute.remove_volume_connection(self.context,
                                                  uuids.volume_id, inst)

            bdm_get.assert_called_once_with(self.context, uuids.volume_id,
                                            uuids.instance_uuid)
            mock_driver_detach.assert_called_once_with(self.context, inst,
                                                       mock_volume_api,
                                                       mock_virt_driver)
            mock_volume_api.terminate_connection.assert_called_once_with(
                    self.context, uuids.volume_id, connector)

    def test_remove_volume_connection_cinder_v3_api(self):
        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        volume_id = uuids.volume
        vol_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})
        vol_bdm.attachment_id = uuids.attachment

        @mock.patch.object(self.compute.volume_api, 'terminate_connection')
        @mock.patch.object(self.compute, 'driver')
        @mock.patch.object(driver_bdm_volume, 'driver_detach')
        @mock.patch.object(objects.BlockDeviceMapping,
                           'get_by_volume_and_instance')
        def _test(mock_get_bdms, mock_detach, mock_driver, mock_terminate):
            mock_get_bdms.return_value = vol_bdm

            self.compute.remove_volume_connection(self.context,
                                                  volume_id, instance)

            mock_detach.assert_called_once_with(self.context, instance,
                                                self.compute.volume_api,
                                                mock_driver)
            mock_terminate.assert_not_called()
        _test()

    def test_delete_disk_metadata(self):
        bdm = objects.BlockDeviceMapping(volume_id=uuids.volume_id, tag='foo')
        instance = fake_instance.fake_instance_obj(self.context)
        instance.device_metadata = objects.InstanceDeviceMetadata(
                devices=[objects.DiskMetadata(serial=uuids.volume_id,
                                              tag='foo')])
        instance.save = mock.Mock()
        self.compute._delete_disk_metadata(instance, bdm)
        self.assertEqual(0, len(instance.device_metadata.devices))
        instance.save.assert_called_once_with()

    def test_delete_disk_metadata_no_serial(self):
        bdm = objects.BlockDeviceMapping(tag='foo')
        instance = fake_instance.fake_instance_obj(self.context)
        instance.device_metadata = objects.InstanceDeviceMetadata(
                devices=[objects.DiskMetadata(tag='foo')])
        self.compute._delete_disk_metadata(instance, bdm)
        # NOTE(artom) This looks weird because we haven't deleted anything, but
        # it's normal behaviour for when DiskMetadata doesn't have serial set
        # and we can't find it based on BlockDeviceMapping's volume_id.
        self.assertEqual(1, len(instance.device_metadata.devices))

    def test_detach_volume(self):
        # TODO(lyarwood): Test DriverVolumeBlockDevice.detach in
        # ../virt/test_block_device.py
        self._test_detach_volume()

    def test_detach_volume_not_destroy_bdm(self):
        # TODO(lyarwood): Test DriverVolumeBlockDevice.detach in
        # ../virt/test_block_device.py
        self._test_detach_volume(destroy_bdm=False)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_notify_about_instance_usage')
    @mock.patch.object(driver_bdm_volume, 'detach')
    @mock.patch('nova.compute.utils.notify_about_volume_attach_detach')
    @mock.patch('nova.compute.manager.ComputeManager._delete_disk_metadata')
    def test_detach_untagged_volume_metadata_not_deleted(
            self, mock_delete_metadata, _, __, ___):
        inst_obj = mock.Mock()
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'source_type': 'volume', 'destination_type': 'volume',
                 'volume_id': uuids.volume, 'device_name': '/dev/vdb',
                 'connection_info': '{"test": "test"}'})
        bdm = objects.BlockDeviceMapping(context=self.context, **fake_bdm)

        self.compute._detach_volume(self.context, bdm, inst_obj,
                                    destroy_bdm=False,
                                    attachment_id=uuids.attachment)
        self.assertFalse(mock_delete_metadata.called)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_notify_about_instance_usage')
    @mock.patch.object(driver_bdm_volume, 'detach')
    @mock.patch('nova.compute.utils.notify_about_volume_attach_detach')
    @mock.patch('nova.compute.manager.ComputeManager._delete_disk_metadata')
    def test_detach_tagged_volume(self, mock_delete_metadata, _, __, ___):
        inst_obj = mock.Mock()
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'source_type': 'volume', 'destination_type': 'volume',
                 'volume_id': uuids.volume, 'device_name': '/dev/vdb',
                 'connection_info': '{"test": "test"}', 'tag': 'foo'})
        bdm = objects.BlockDeviceMapping(context=self.context, **fake_bdm)

        self.compute._detach_volume(self.context, bdm, inst_obj,
                                    destroy_bdm=False,
                                    attachment_id=uuids.attachment)
        mock_delete_metadata.assert_called_once_with(inst_obj, bdm)

    @mock.patch.object(driver_bdm_volume, 'detach')
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_volume_attach_detach')
    def _test_detach_volume(self, mock_notify_attach_detach, notify_inst_usage,
                            detach, destroy_bdm=True):
        # TODO(lyarwood): Test DriverVolumeBlockDevice.detach in
        # ../virt/test_block_device.py
        volume_id = uuids.volume
        inst_obj = mock.Mock()
        inst_obj.uuid = uuids.instance
        inst_obj.host = CONF.host
        attachment_id = uuids.attachment

        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
                {'source_type': 'volume', 'destination_type': 'volume',
                 'volume_id': volume_id, 'device_name': '/dev/vdb',
                 'connection_info': '{"test": "test"}'})
        bdm = objects.BlockDeviceMapping(context=self.context, **fake_bdm)

        with test.nested(
            mock.patch.object(self.compute, 'volume_api'),
            mock.patch.object(self.compute, 'driver'),
            mock.patch.object(bdm, 'destroy'),
        ) as (volume_api, driver, bdm_destroy):
            self.compute._detach_volume(self.context, bdm, inst_obj,
                                        destroy_bdm=destroy_bdm,
                                        attachment_id=attachment_id)
            detach.assert_called_once_with(self.context, inst_obj,
                    self.compute.volume_api, self.compute.driver,
                    attachment_id=attachment_id,
                    destroy_bdm=destroy_bdm)
            notify_inst_usage.assert_called_once_with(
                self.context, inst_obj, "volume.detach",
                extra_usage_info={'volume_id': volume_id})

            if destroy_bdm:
                bdm_destroy.assert_called_once_with()
            else:
                self.assertFalse(bdm_destroy.called)

        mock_notify_attach_detach.assert_has_calls([
            mock.call(self.context, inst_obj, 'fake-mini',
                      action='volume_detach', phase='start',
                      volume_id=volume_id),
            mock.call(self.context, inst_obj, 'fake-mini',
                      action='volume_detach', phase='end',
                      volume_id=volume_id),
            ])

    def test_detach_volume_evacuate(self):
        """For evacuate, terminate_connection is called with original host."""
        # TODO(lyarwood): Test DriverVolumeBlockDevice.driver_detach in
        # ../virt/test_block_device.py
        expected_connector = {'host': 'evacuated-host'}
        conn_info_str = '{"connector": {"host": "evacuated-host"}}'
        self._test_detach_volume_evacuate(conn_info_str,
                                          expected=expected_connector)

    def test_detach_volume_evacuate_legacy(self):
        """Test coverage for evacuate with legacy attachments.

        In this case, legacy means the volume was attached to the instance
        before nova stashed the connector in connection_info. The connector
        sent to terminate_connection will still be for the local host in this
        case because nova does not have the info to get the connector for the
        original (evacuated) host.
        """
        # TODO(lyarwood): Test DriverVolumeBlockDevice.driver_detach in
        # ../virt/test_block_device.py
        conn_info_str = '{"foo": "bar"}'  # Has no 'connector'.
        self._test_detach_volume_evacuate(conn_info_str)

    def test_detach_volume_evacuate_mismatch(self):
        """Test coverage for evacuate with connector mismatch.

        For evacuate, if the stashed connector also has the wrong host,
        then log it and stay with the local connector.
        """
        # TODO(lyarwood): Test DriverVolumeBlockDevice.driver_detach in
        # ../virt/test_block_device.py
        conn_info_str = '{"connector": {"host": "other-host"}}'
        self._test_detach_volume_evacuate(conn_info_str)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_volume_attach_detach')
    def _test_detach_volume_evacuate(self, conn_info_str,
                                     mock_notify_attach_detach,
                                     notify_inst_usage,
                                     expected=None):
        """Re-usable code for detach volume evacuate test cases.

        :param conn_info_str: String form of the stashed connector.
        :param expected: Dict of the connector that is expected in the
                         terminate call (optional). Default is to expect the
                         local connector to be used.
        """
        # TODO(lyarwood): Test DriverVolumeBlockDevice.driver_detach in
        # ../virt/test_block_device.py
        volume_id = 'vol_id'
        instance = fake_instance.fake_instance_obj(self.context,
                                                   host='evacuated-host')
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(
        {'source_type': 'volume', 'destination_type': 'volume',
         'volume_id': volume_id, 'device_name': '/dev/vdb',
         'connection_info': '{"test": "test"}'})
        bdm = objects.BlockDeviceMapping(context=self.context, **fake_bdm)
        bdm.connection_info = conn_info_str

        local_connector = {'host': 'local-connector-host'}
        expected_connector = local_connector if not expected else expected

        with test.nested(
            mock.patch.object(self.compute, 'volume_api'),
            mock.patch.object(self.compute, 'driver'),
            mock.patch.object(driver_bdm_volume, 'driver_detach'),
        ) as (volume_api, driver, driver_detach):
            driver.get_volume_connector.return_value = local_connector

            self.compute._detach_volume(self.context,
                                        bdm,
                                        instance,
                                        destroy_bdm=False)

            driver_detach.assert_not_called()
            driver.get_volume_connector.assert_called_once_with(instance)
            volume_api.terminate_connection.assert_called_once_with(
                self.context, volume_id, expected_connector)
            volume_api.detach.assert_called_once_with(mock.ANY,
                                                      volume_id,
                                                      instance.uuid,
                                                      None)
            notify_inst_usage.assert_called_once_with(
                self.context, instance, "volume.detach",
                extra_usage_info={'volume_id': volume_id}
            )

            mock_notify_attach_detach.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                          action='volume_detach', phase='start',
                          volume_id=volume_id),
                mock.call(self.context, instance, 'fake-mini',
                          action='volume_detach', phase='end',
                          volume_id=volume_id),
                ])

    @mock.patch('nova.compute.utils.notify_about_instance_rescue_action')
    def _test_rescue(self, mock_notify, clean_shutdown=True):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE)
        fake_nw_info = network_model.NetworkInfo()
        rescue_image_meta = objects.ImageMeta.from_dict(
            {'id': uuids.image_id, 'name': uuids.image_name})
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                              return_value=fake_nw_info),
            mock.patch.object(self.compute, '_get_rescue_image',
                              return_value=rescue_image_meta),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute, '_power_off_instance'),
            mock.patch.object(self.compute.driver, 'rescue'),
            mock.patch.object(compute_utils, 'notify_usage_exists'),
            mock.patch.object(self.compute, '_get_power_state',
                              return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save')
        ) as (
            elevated_context, get_nw_info, get_rescue_image,
            notify_instance_usage, power_off_instance, driver_rescue,
            notify_usage_exists, get_power_state, instance_save
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

            extra_usage_info = {'rescue_image_name': uuids.image_name}
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

            notify_usage_exists.assert_called_once_with(self.compute.notifier,
                self.context, instance, current_period=True)
            mock_notify.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini', None,
                      action='rescue', phase='start'),
                mock.call(self.context, instance, 'fake-mini', None,
                      action='rescue', phase='end')])

            instance_save.assert_called_once_with(
                expected_task_state=task_states.RESCUING)

    def test_rescue(self):
        self._test_rescue()

    def test_rescue_forced_shutdown(self):
        self._test_rescue(clean_shutdown=False)

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_unrescue(self, mock_notify):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.RESCUED)
        fake_nw_info = network_model.NetworkInfo()
        with test.nested(
            mock.patch.object(self.context, 'elevated',
                              return_value=self.context),
            mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                              return_value=fake_nw_info),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute.driver, 'unrescue'),
            mock.patch.object(self.compute, '_get_power_state',
                              return_value=power_state.RUNNING),
            mock.patch.object(instance, 'save')
        ) as (
            elevated_context, get_nw_info, notify_instance_usage,
            driver_unrescue, get_power_state, instance_save
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
            mock_notify.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                      action='unrescue', phase='start'),
                mock.call(self.context, instance, 'fake-mini',
                      action='unrescue', phase='end')])

            instance_save.assert_called_once_with(
                expected_task_state=task_states.UNRESCUING)

    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.RUNNING)
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch('nova.utils.generate_password', return_value='fake-pass')
    def test_set_admin_password(self, gen_password_mock, instance_save_mock,
                                power_state_mock):
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

    @mock.patch('nova.compute.manager.ComputeManager._get_power_state',
                return_value=power_state.NOSTATE)
    @mock.patch('nova.compute.manager.ComputeManager._instance_update')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_set_admin_password_bad_state(self, add_fault_mock,
                                          instance_save_mock, update_mock,
                                          power_state_mock):
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
                                                 gen_password_mock):
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

            if expected_exception != exception.InstancePasswordSetFailed:
                instance_save_mock.assert_called_once_with(
                    expected_task_state=task_states.UPDATING_PASSWORD)

            self.assertEqual(expected_vm_state, instance.vm_state)
            # check revert_task_state decorator
            update_mock.assert_called_once_with(
                self.context, instance, task_state=expected_task_state)
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
            exc, vm_states.ACTIVE, None, expected_exception)

    def test_set_admin_password_driver_not_implemented(self):
        # Ensure expected exception is raised if set_admin_password not
        # implemented by driver.
        exc = NotImplementedError()
        expected_exception = NotImplementedError
        self._do_test_set_admin_password_driver_error(
            exc, vm_states.ACTIVE, None, expected_exception)

    def test_set_admin_password_driver_not_supported(self):
        exc = exception.SetAdminPasswdNotSupported()
        expected_exception = exception.SetAdminPasswdNotSupported
        self._do_test_set_admin_password_driver_error(
            exc, vm_states.ACTIVE, None, expected_exception)

    def test_set_admin_password_guest_agent_no_enabled(self):
        exc = exception.QemuGuestAgentNotEnabled()
        expected_exception = exception.InstanceAgentNotEnabled
        self._do_test_set_admin_password_driver_error(
            exc, vm_states.ACTIVE, None, expected_exception)

    def test_destroy_evacuated_instances(self):
        our_host = self.compute.host
        flavor = objects.Flavor()
        instance_1 = objects.Instance(self.context, flavor=flavor)
        instance_1.uuid = uuids.instance_1
        instance_1.task_state = None
        instance_1.vm_state = vm_states.ACTIVE
        instance_1.host = 'not-' + our_host
        instance_1.user_id = uuids.user_id
        instance_1.project_id = uuids.project_id
        instance_2 = objects.Instance(self.context, flavor=flavor)
        instance_2.uuid = uuids.instance_2
        instance_2.task_state = None
        instance_2.vm_state = vm_states.ACTIVE
        instance_2.host = 'not-' + our_host
        instance_2.user_id = uuids.user_id
        instance_2.project_id = uuids.project_id
        instance_2.deleted = False

        # Only instance 2 has a migration record
        migration = objects.Migration(instance_uuid=instance_2.uuid)
        # Consider the migration successful
        migration.status = 'done'
        migration.source_node = 'fake-node'

        our_node = objects.ComputeNode(
            host=our_host, uuid=uuids.our_node_uuid)

        with test.nested(
            mock.patch.object(self.compute, '_get_instances_on_driver',
                               return_value=[instance_1,
                                             instance_2]),
            mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                               return_value=None),
            mock.patch.object(self.compute, '_get_instance_block_device_info',
                               return_value={}),
            mock.patch.object(self.compute, '_is_instance_storage_shared',
                               return_value=False),
            mock.patch.object(self.compute.driver, 'destroy'),
            mock.patch('nova.objects.MigrationList.get_by_filters'),
            mock.patch('nova.objects.Migration.save'),
            mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename'),
            mock.patch('nova.scheduler.utils.resources_from_flavor'),
            mock.patch.object(self.compute.reportclient,
                              'remove_provider_from_instance_allocation')
        ) as (_get_instances_on_driver, get_instance_nw_info,
              _get_instance_block_device_info, _is_instance_storage_shared,
              destroy, migration_list, migration_save, get_node,
              get_resources, remove_allocation):
            migration_list.return_value = [migration]
            get_node.return_value = our_node
            get_resources.return_value = mock.sentinel.resources

            self.compute._destroy_evacuated_instances(self.context)
            # Only instance 2 should be deleted. Instance 1 is still running
            # here, but no migration from our host exists, so ignore it
            destroy.assert_called_once_with(self.context, instance_2, None,
                                            {}, True)

            get_node.assert_called_once_with(
                self.context, our_host, migration.source_node)
            remove_allocation.assert_called_once_with(
                self.context, instance_2.uuid, uuids.our_node_uuid,
                uuids.user_id, uuids.project_id, mock.sentinel.resources)

    def test_destroy_evacuated_instances_node_deleted(self):
        our_host = self.compute.host
        flavor = objects.Flavor()
        instance_1 = objects.Instance(self.context, flavor=flavor)
        instance_1.uuid = uuids.instance_1
        instance_1.task_state = None
        instance_1.vm_state = vm_states.ACTIVE
        instance_1.host = 'not-' + our_host
        instance_1.user_id = uuids.user_id
        instance_1.project_id = uuids.project_id
        instance_1.deleted = False
        instance_2 = objects.Instance(self.context, flavor=flavor)
        instance_2.uuid = uuids.instance_2
        instance_2.task_state = None
        instance_2.vm_state = vm_states.ACTIVE
        instance_2.host = 'not-' + our_host
        instance_2.user_id = uuids.user_id
        instance_2.project_id = uuids.project_id
        instance_2.deleted = False

        migration_1 = objects.Migration(instance_uuid=instance_1.uuid)
        # Consider the migration successful but the node was deleted while the
        # compute was down
        migration_1.status = 'done'
        migration_1.source_node = 'deleted-node'

        migration_2 = objects.Migration(instance_uuid=instance_2.uuid)
        # Consider the migration successful
        migration_2.status = 'done'
        migration_2.source_node = 'fake-node'

        our_node = objects.ComputeNode(
            host=our_host, uuid=uuids.our_node_uuid)

        with test.nested(
            mock.patch.object(self.compute, '_get_instances_on_driver',
                               return_value=[instance_1,
                                             instance_2]),
            mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                               return_value=None),
            mock.patch.object(self.compute, '_get_instance_block_device_info',
                               return_value={}),
            mock.patch.object(self.compute, '_is_instance_storage_shared',
                               return_value=False),
            mock.patch.object(self.compute.driver, 'destroy'),
            mock.patch('nova.objects.MigrationList.get_by_filters'),
            mock.patch('nova.objects.Migration.save'),
            mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename'),
            mock.patch('nova.scheduler.utils.resources_from_flavor'),
            mock.patch.object(self.compute.reportclient,
                              'remove_provider_from_instance_allocation')
        ) as (_get_instances_on_driver, get_instance_nw_info,
              _get_instance_block_device_info, _is_instance_storage_shared,
              destroy, migration_list, migration_save, get_node,
              get_resources, remove_allocation):
            migration_list.return_value = [migration_1, migration_2]

            def fake_get_node(context, host, node):
                if node == 'fake-node':
                    return our_node
                else:
                    raise exception.ComputeHostNotFound(host=host)

            get_node.side_effect = fake_get_node
            get_resources.return_value = mock.sentinel.resources

            self.compute._destroy_evacuated_instances(self.context)

            # both instance_1 and instance_2 is destroyed in the driver
            destroy.assert_has_calls(
                [mock.call(self.context, instance_1, None, {}, True),
                 mock.call(self.context, instance_2, None, {}, True)])

            # but only instance_2 is deallocated as the compute node for
            # instance_1 is already deleted
            remove_allocation.assert_called_once_with(
                self.context, instance_2.uuid, uuids.our_node_uuid,
                uuids.user_id, uuids.project_id, mock.sentinel.resources)

            self.assertEqual(2, get_node.call_count)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_destroy_evacuated_instances')
    @mock.patch('nova.compute.manager.LOG')
    def test_init_host_foreign_instance(self, mock_log, mock_destroy):
        inst = mock.MagicMock()
        inst.host = self.compute.host + '-alt'
        self.compute._init_instance(mock.sentinel.context, inst)
        self.assertFalse(inst.save.called)
        self.assertTrue(mock_log.warning.called)
        msg = mock_log.warning.call_args_list[0]
        self.assertIn('appears to not be owned by this host', msg[0][0])

    def test_init_host_pci_passthrough_whitelist_validation_failure(self):
        # Tests that we fail init_host if there is a pci.passthrough_whitelist
        # configured incorrectly.
        self.flags(passthrough_whitelist=[
            # it's invalid to specify both in the same devspec
            jsonutils.dumps({'address': 'foo', 'devname': 'bar'})],
            group='pci')
        self.assertRaises(exception.PciDeviceInvalidDeviceName,
                          self.compute.init_host)

    def test_init_host_placement_ensures_default_config_is_unset(self):
        # Tests that by default the placement config option is unset
        # NOTE(sbauza): Just resets the conf opt to the real value and not
        # the faked one.
        fake_conf = copy.copy(CONF)
        fake_conf.clear_default('os_region_name', group='placement')
        self.assertIsNone(CONF.placement.os_region_name)

    def test_init_host_placement_config_failure(self):
        # Tests that we fail init_host if the placement section is
        # configured incorrectly.
        self.flags(os_region_name=None, group='placement')
        self.flags(region_name=None, group='placement')
        self.assertRaises(exception.PlacementNotConfigured,
                          self.compute.init_host)

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
            self.context, instance,
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
            self.context, instance,
            vm_state=vm_states.ACTIVE, task_state=None)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_set_instance_obj_error_state')
    def test_error_out_instance_on_exception_unknown_with_quotas(self,
                                                                 set_error):
        instance = fake_instance.fake_instance_obj(self.context)

        def do_test():
            with self.compute._error_out_instance_on_exception(
                    self.context, instance):
                raise test.TestingException('test')

        self.assertRaises(test.TestingException, do_test)
        set_error.assert_called_once_with(self.context, instance)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_detach_volume')
    def test_cleanup_volumes(self, mock_detach):
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
            self.compute._cleanup_volumes(self.context, instance, bdms)
            calls = [mock.call(self.context, bdm, instance,
                               destroy_bdm=bdm.delete_on_termination)
                     for bdm in bdms]
            self.assertEqual(calls, mock_detach.call_args_list)
            volume_delete.assert_called_once_with(self.context,
                    bdms[1].volume_id)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_detach_volume')
    def test_cleanup_volumes_exception_do_not_raise(self, mock_detach):
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
            self.compute._cleanup_volumes(self.context, instance, bdms,
                    raise_exc=False)
            calls = [mock.call(self.context, bdm.volume_id) for bdm in bdms]
            self.assertEqual(calls, volume_delete.call_args_list)
            calls = [mock.call(self.context, bdm, instance,
                               destroy_bdm=True) for bdm in bdms]
            self.assertEqual(calls, mock_detach.call_args_list)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_detach_volume')
    def test_cleanup_volumes_exception_raise(self, mock_detach):
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
                    self.compute._cleanup_volumes, self.context, instance,
                    bdms)
            calls = [mock.call(self.context, bdm.volume_id) for bdm in bdms]
            self.assertEqual(calls, volume_delete.call_args_list)
            calls = [mock.call(self.context, bdm, instance,
                               destroy_bdm=bdm.delete_on_termination)
                     for bdm in bdms]
            self.assertEqual(calls, mock_detach.call_args_list)

    @mock.patch('nova.compute.manager.ComputeManager._detach_volume',
                side_effect=exception.CinderConnectionFailed(reason='idk'))
    def test_cleanup_volumes_detach_fails_raise_exc(self, mock_detach):
        instance = fake_instance.fake_instance_obj(self.context)
        bdms = block_device_obj.block_device_make_list(
            self.context,
            [fake_block_device.FakeDbBlockDeviceDict(
                {'volume_id': uuids.volume_id,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'delete_on_termination': False})])
        self.assertRaises(exception.CinderConnectionFailed,
                          self.compute._cleanup_volumes, self.context,
                          instance, bdms)
        mock_detach.assert_called_once_with(
            self.context, bdms[0], instance, destroy_bdm=False)

    def test_stop_instance_task_state_none_power_state_shutdown(self):
        # Tests that stop_instance doesn't puke when the instance power_state
        # is shutdown and the task_state is None.
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE,
            task_state=None, power_state=power_state.SHUTDOWN)

        @mock.patch.object(self.compute, '_get_power_state',
                           return_value=power_state.SHUTDOWN)
        @mock.patch.object(compute_utils, 'notify_about_instance_action')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, '_power_off_instance')
        @mock.patch.object(instance, 'save')
        def do_test(save_mock, power_off_mock, notify_mock,
                    notify_action_mock, get_state_mock):
            # run the code
            self.compute.stop_instance(self.context, instance, True)
            # assert the calls
            self.assertEqual(2, get_state_mock.call_count)
            notify_mock.assert_has_calls([
                mock.call(self.context, instance, 'power_off.start'),
                mock.call(self.context, instance, 'power_off.end')
            ])
            notify_action_mock.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                          action='power_off', phase='start'),
                mock.call(self.context, instance, 'fake-mini',
                          action='power_off', phase='end'),
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

    @mock.patch.object(manager.ComputeManager, '_set_migration_status')
    @mock.patch.object(manager.ComputeManager,
                       '_do_rebuild_instance_with_claim')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    def _test_rebuild_ex(self, instance, exc,
                         mock_notify_about_instance_usage,
                         mock_notify, mock_rebuild, mock_set,
                         recreate=False, scheduled_node=None):

        mock_rebuild.side_effect = exc

        self.compute.rebuild_instance(self.context, instance, None, None, None,
                                      None, None, None, recreate,
                                      False, False, None, scheduled_node, {},
                                      None)
        mock_set.assert_called_once_with(None, 'failed')
        mock_notify_about_instance_usage.assert_called_once_with(
            mock.ANY, instance, 'rebuild.error', fault=mock_rebuild.side_effect
        )
        mock_notify.assert_called_once_with(
            mock.ANY, instance, 'fake-mini', action='rebuild', phase='error',
            exception=exc, bdms=None)

    def test_rebuild_deleting(self):
        instance = fake_instance.fake_instance_obj(self.context)
        ex = exception.UnexpectedDeletingTaskStateError(
            instance_uuid=instance.uuid, expected='expected', actual='actual')
        self._test_rebuild_ex(instance, ex)

    def test_rebuild_notfound(self):
        instance = fake_instance.fake_instance_obj(self.context)
        ex = exception.InstanceNotFound(instance_id=instance.uuid)
        self._test_rebuild_ex(instance, ex)

    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager,
                       '_error_out_instance_on_exception')
    def test_rebuild_driver_error_same_host(self, mock_error, mock_aiffe):
        instance = fake_instance.fake_instance_obj(self.context)
        ex = test.TestingException('foo')
        with mock.patch.object(self.compute, '_get_resource_tracker') as mrt:
            self.assertRaises(test.TestingException,
                              self._test_rebuild_ex, instance, ex)
            rt = mrt.return_value
            self.assertFalse(
                rt.delete_allocation_for_evacuated_instance.called)

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager,
                       '_error_out_instance_on_exception')
    def test_rebuild_driver_error_evacuate(self, mock_error, mock_aiffe,
                                           mock_elevated):
        mock_elevated.return_value = self.context
        instance = fake_instance.fake_instance_obj(self.context)
        ex = test.TestingException('foo')
        with mock.patch.object(self.compute, '_get_resource_tracker') as mrt:
            self.assertRaises(test.TestingException,
                              self._test_rebuild_ex, instance, ex,
                              recreate=True, scheduled_node='foo')
            rt = mrt.return_value
            delete_alloc = rt.delete_allocation_for_evacuated_instance
            delete_alloc.assert_called_once_with(self.context, instance, 'foo',
                                                 node_type='destination')

    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.instance.Instance.drop_migration_context')
    @mock.patch('nova.objects.instance.Instance.apply_migration_context')
    @mock.patch('nova.objects.instance.Instance.mutated_migration_context')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.network.neutronv2.api.API.'
                'setup_instance_network_on_host')
    @mock.patch('nova.network.neutronv2.api.API.setup_networks_on_host')
    @mock.patch('nova.objects.instance.Instance.save')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_usage_exists')
    @mock.patch('nova.objects.instance.Instance.image_meta',
                new_callable=mock.PropertyMock)
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_validate_instance_group_policy')
    @mock.patch('nova.compute.manager.ComputeManager._set_migration_status')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.rebuild_claim')
    def test_evacuate_late_server_group_policy_check(
            self, mock_rebuild_claim, mock_set_migration_status,
            mock_validate_policy, mock_image_meta, mock_notify_exists,
            mock_notify_legacy, mock_notify, mock_instance_save,
            mock_setup_networks, mock_setup_intance_network, mock_get_bdms,
            mock_mutate_migration, mock_appy_migration, mock_drop_migration,
            mock_context_elevated):
        self.flags(api_servers=['http://localhost/image/v2'], group='glance')
        instance = fake_instance.fake_instance_obj(self.context)
        instance.info_cache = None
        elevated_context = mock.Mock()
        mock_context_elevated.return_value = elevated_context
        request_spec = objects.RequestSpec()
        request_spec.scheduler_hints = {'group': [uuids.group]}

        with mock.patch.object(self.compute, 'network_api'):
            self.compute.rebuild_instance(
                self.context, instance, None, None, None, None, None,
                None, recreate=True, on_shared_storage=None,
                preserve_ephemeral=False, migration=None,
                scheduled_node='fake-node',
                limits={}, request_spec=request_spec)

        mock_validate_policy.assert_called_once_with(
            elevated_context, instance, {'group': [uuids.group]})

    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                'delete_allocation_for_evacuated_instance')
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.objects.instance.Instance.save')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.manager.ComputeManager.'
                '_validate_instance_group_policy')
    @mock.patch('nova.compute.manager.ComputeManager._set_migration_status')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.rebuild_claim')
    def test_evacuate_late_server_group_policy_check_fails(
            self, mock_rebuild_claim, mock_set_migration_status,
            mock_validate_policy, mock_notify_legacy, mock_notify,
            mock_instance_save, mock_context_elevated, mock_delete_allocation,
            mock_instance_fault):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.info_cache = None
        elevated_context = mock.Mock()
        mock_context_elevated.return_value = elevated_context
        request_spec = objects.RequestSpec()
        request_spec.scheduler_hints = {'group': [uuids.group]}

        exc = exception.RescheduledException(
            instance_uuid=instance.uuid, reason='policy violation')
        mock_validate_policy.side_effect = exc

        self.assertRaises(
            exception.BuildAbortException, self.compute.rebuild_instance,
            self.context, instance, None, None, None, None, None, None,
            recreate=True, on_shared_storage=None, preserve_ephemeral=False,
            migration=None, scheduled_node='fake-node', limits={},
            request_spec=request_spec)

        mock_validate_policy.assert_called_once_with(
            elevated_context, instance, {'group': [uuids.group]})
        mock_delete_allocation.assert_called_once_with(
            elevated_context, instance, 'fake-node', node_type='destination')
        mock_notify.assert_called_once_with(
            elevated_context, instance, 'fake-mini', action='rebuild',
            bdms=None, exception=exc, phase='error')

    def test_rebuild_node_not_updated_if_not_recreate(self):
        node = uuidutils.generate_uuid()  # ironic node uuid
        instance = fake_instance.fake_instance_obj(self.context, node=node)
        instance.migration_context = None
        with test.nested(
            mock.patch.object(self.compute, '_get_compute_info'),
            mock.patch.object(self.compute, '_do_rebuild_instance_with_claim'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(self.compute, '_set_migration_status'),
        ) as (mock_get, mock_rebuild, mock_save, mock_set):
            self.compute.rebuild_instance(self.context, instance, None, None,
                                          None, None, None, None, False,
                                          False, False, None, None, {}, None)
            self.assertFalse(mock_get.called)
            self.assertEqual(node, instance.node)
            mock_set.assert_called_once_with(None, 'done')

    def test_rebuild_node_updated_if_recreate(self):
        dead_node = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.context,
                                                   node=dead_node)
        instance.migration_context = None
        with test.nested(
            mock.patch.object(self.compute, '_get_resource_tracker'),
            mock.patch.object(self.compute, '_get_compute_info'),
            mock.patch.object(self.compute, '_do_rebuild_instance_with_claim'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(self.compute, '_set_migration_status'),
        ) as (mock_rt, mock_get, mock_rebuild, mock_save, mock_set):
            mock_get.return_value.hypervisor_hostname = 'new-node'
            self.compute.rebuild_instance(self.context, instance, None, None,
                                          None, None, None, None, True,
                                          False, False, None, None, {}, None)
            mock_get.assert_called_once_with(mock.ANY, self.compute.host)
            self.assertEqual('new-node', instance.node)
            mock_set.assert_called_once_with(None, 'done')
            mock_rt.assert_called_once_with()

    @mock.patch.object(compute_utils, 'notify_usage_exists')
    @mock.patch.object(compute_utils, 'notify_about_instance_action')
    @mock.patch.object(objects.ImageMeta, 'from_instance')
    @mock.patch.object(objects.Instance, 'save', return_value=None)
    def test_rebuild_nw_updated_if_recreate(self,
                                            mock_save,
                                            mock_image_ref,
                                            mock_notify,
                                            mock_notify_exists):
        with test.nested(
            mock.patch.object(self.compute,
                              '_notify_about_instance_usage'),
            mock.patch.object(self.compute.network_api,
                              'setup_networks_on_host'),
            mock.patch.object(self.compute.network_api,
                              'setup_instance_network_on_host'),
            mock.patch.object(self.compute.network_api,
                              'get_instance_nw_info'),
            mock.patch.object(self.compute,
                              '_get_instance_block_device_info',
                              return_value='fake-bdminfo'),
        ) as(
             mock_notify_usage,
             mock_setup,
             mock_setup_inst,
             mock_get_nw_info,
             mock_get_blk
        ):
            self.flags(group="glance", api_servers="http://127.0.0.1:9292")
            instance = fake_instance.fake_instance_obj(self.context)
            orig_vif = fake_network_cache_model.new_vif(
                {'profile': {"pci_slot": "0000:01:00.1"}})
            orig_nw_info = network_model.NetworkInfo([orig_vif])
            new_vif = fake_network_cache_model.new_vif(
                {'profile': {"pci_slot": "0000:02:00.1"}})
            new_nw_info = network_model.NetworkInfo([new_vif])

            info_cache = objects.InstanceInfoCache(network_info=orig_nw_info,
                                                   instance_uuid=instance.uuid)

            instance.info_cache = info_cache
            instance.task_state = task_states.REBUILDING
            instance.migration_context = None
            instance.numa_topology = None
            instance.pci_requests = None
            instance.pci_devices = None
            orig_image_ref = None
            image_ref = None
            injected_files = []
            new_pass = None
            orig_sys_metadata = None
            bdms = []
            recreate = True
            on_shared_storage = None
            preserve_ephemeral = None

            mock_get_nw_info.return_value = new_nw_info

            self.compute._do_rebuild_instance(self.context, instance,
                                              orig_image_ref, image_ref,
                                              injected_files, new_pass,
                                              orig_sys_metadata, bdms,
                                              recreate, on_shared_storage,
                                              preserve_ephemeral, {}, {})

            mock_notify_usage.assert_has_calls(
                [mock.call(self.context, instance, "rebuild.start",
                           extra_usage_info=mock.ANY),
                 mock.call(self.context, instance, "rebuild.end",
                           network_info=new_nw_info,
                           extra_usage_info=mock.ANY)])
            self.assertTrue(mock_image_ref.called)
            self.assertTrue(mock_save.called)
            self.assertTrue(mock_notify_exists.called)
            mock_setup.assert_called_once_with(self.context, instance,
                                               mock.ANY)
            mock_setup_inst.assert_called_once_with(self.context, instance,
                                                    mock.ANY, mock.ANY)
            mock_get_nw_info.assert_called_once_with(self.context, instance)

    def test_rebuild_default_impl(self):
        def _detach(context, bdms):
            # NOTE(rpodolyaka): check that instance has been powered off by
            # the time we detach block devices, exact calls arguments will be
            # checked below
            self.assertTrue(mock_power_off.called)
            self.assertFalse(mock_destroy.called)

        def _attach(context, instance, bdms):
            return {'block_device_mapping': 'shared_block_storage'}

        def _spawn(context, instance, image_meta, injected_files,
                   admin_password, allocations, network_info=None,
                   block_device_info=None):
            self.assertEqual(block_device_info['block_device_mapping'],
                             'shared_block_storage')

        with test.nested(
            mock.patch.object(self.compute.driver, 'destroy',
                              return_value=None),
            mock.patch.object(self.compute.driver, 'spawn',
                              side_effect=_spawn),
            mock.patch.object(objects.Instance, 'save',
                              return_value=None),
            mock.patch.object(self.compute, '_power_off_instance',
                              return_value=None)
        ) as(
             mock_destroy,
             mock_spawn,
             mock_save,
             mock_power_off
        ):
            instance = fake_instance.fake_instance_obj(self.context)
            instance.migration_context = None
            instance.numa_topology = None
            instance.pci_requests = None
            instance.pci_devices = None
            instance.device_metadata = None
            instance.task_state = task_states.REBUILDING
            instance.save(expected_task_state=[task_states.REBUILDING])
            self.compute._rebuild_default_impl(self.context,
                                               instance,
                                               None,
                                               [],
                                               admin_password='new_pass',
                                               bdms=[],
                                               allocations={},
                                               detach_block_devices=_detach,
                                               attach_block_devices=_attach,
                                               network_info=None,
                                               recreate=False,
                                               block_device_info=None,
                                               preserve_ephemeral=False)

            self.assertTrue(mock_save.called)
            self.assertTrue(mock_spawn.called)
            mock_destroy.assert_called_once_with(
                self.context, instance,
                network_info=None, block_device_info=None)
            mock_power_off.assert_called_once_with(
                self.context, instance, clean_shutdown=True)

    @mock.patch.object(utils, 'last_completed_audit_period',
            return_value=(0, 0))
    @mock.patch.object(time, 'time', side_effect=[10, 20, 21])
    @mock.patch.object(objects.InstanceList, 'get_by_host', return_value=[])
    @mock.patch.object(objects.BandwidthUsage, 'get_by_instance_uuid_and_mac')
    @mock.patch.object(db, 'bw_usage_update')
    def test_poll_bandwidth_usage(self, bw_usage_update, get_by_uuid_mac,
            get_by_host, time, last_completed_audit):
        bw_counters = [{'uuid': uuids.instance, 'mac_address': 'fake-mac',
                        'bw_in': 1, 'bw_out': 2}]
        usage = objects.BandwidthUsage()
        usage.bw_in = 3
        usage.bw_out = 4
        usage.last_ctr_in = 0
        usage.last_ctr_out = 0
        self.flags(bandwidth_poll_interval=1)
        get_by_uuid_mac.return_value = usage
        _time = timeutils.utcnow()
        bw_usage_update.return_value = {'uuid': uuids.instance, 'mac': '',
                'start_period': _time, 'last_refreshed': _time, 'bw_in': 0,
                'bw_out': 0, 'last_ctr_in': 0, 'last_ctr_out': 0, 'deleted': 0,
                'created_at': _time, 'updated_at': _time, 'deleted_at': _time}
        with mock.patch.object(self.compute.driver,
                'get_all_bw_counters', return_value=bw_counters):
            self.compute._poll_bandwidth_usage(self.context)
            get_by_uuid_mac.assert_called_once_with(self.context,
                    uuids.instance, 'fake-mac',
                    start_period=0, use_slave=True)
            # NOTE(sdague): bw_usage_update happens at some time in
            # the future, so what last_refreshed is irrelevant.
            bw_usage_update.assert_called_once_with(self.context,
                    uuids.instance,
                    'fake-mac', 0, 4, 6, 1, 2,
                    last_refreshed=mock.ANY,
                    update_cells=False)

    def test_reverts_task_state_instance_not_found(self):
        # Tests that the reverts_task_state decorator in the compute manager
        # will not trace when an InstanceNotFound is raised.
        instance = objects.Instance(uuid=uuids.instance, task_state="FAKE")
        instance_update_mock = mock.Mock(
            side_effect=exception.InstanceNotFound(instance_id=instance.uuid))
        self.compute._instance_update = instance_update_mock

        log_mock = mock.Mock()
        manager.LOG = log_mock

        @manager.reverts_task_state
        def fake_function(self, context, instance):
            raise test.TestingException()

        self.assertRaises(test.TestingException, fake_function,
                          self, self.context, instance)

        self.assertFalse(log_mock.called)

    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'update_instance_info')
    def test_update_scheduler_instance_info(self, mock_update):
        instance = objects.Instance(uuid=uuids.instance)
        self.compute._update_scheduler_instance_info(self.context, instance)
        self.assertEqual(mock_update.call_count, 1)
        args = mock_update.call_args[0]
        self.assertNotEqual(args[0], self.context)
        self.assertIsInstance(args[0], self.context.__class__)
        self.assertEqual(args[1], self.compute.host)
        # Send a single instance; check that the method converts to an
        # InstanceList
        self.assertIsInstance(args[2], objects.InstanceList)
        self.assertEqual(args[2].objects[0], instance)

    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'delete_instance_info')
    def test_delete_scheduler_instance_info(self, mock_delete):
        self.compute._delete_scheduler_instance_info(self.context,
                                                     mock.sentinel.inst_uuid)
        self.assertEqual(mock_delete.call_count, 1)
        args = mock_delete.call_args[0]
        self.assertNotEqual(args[0], self.context)
        self.assertIsInstance(args[0], self.context.__class__)
        self.assertEqual(args[1], self.compute.host)
        self.assertEqual(args[2], mock.sentinel.inst_uuid)

    @mock.patch.object(nova.context.RequestContext, 'elevated')
    @mock.patch.object(nova.objects.InstanceList, 'get_by_host')
    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'sync_instance_info')
    def test_sync_scheduler_instance_info(self, mock_sync, mock_get_by_host,
            mock_elevated):
        inst1 = objects.Instance(uuid=uuids.instance_1)
        inst2 = objects.Instance(uuid=uuids.instance_2)
        inst3 = objects.Instance(uuid=uuids.instance_3)
        exp_uuids = [inst.uuid for inst in [inst1, inst2, inst3]]
        mock_get_by_host.return_value = objects.InstanceList(
                objects=[inst1, inst2, inst3])
        fake_elevated = context.get_admin_context()
        mock_elevated.return_value = fake_elevated
        self.compute._sync_scheduler_instance_info(self.context)
        mock_get_by_host.assert_called_once_with(
                fake_elevated, self.compute.host, expected_attrs=[],
                use_slave=True)
        mock_sync.assert_called_once_with(fake_elevated, self.compute.host,
                                          exp_uuids)

    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'sync_instance_info')
    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'delete_instance_info')
    @mock.patch.object(nova.scheduler.client.SchedulerClient,
                       'update_instance_info')
    def test_scheduler_info_updates_off(self, mock_update, mock_delete,
                                        mock_sync):
        mgr = self.compute
        mgr.send_instance_updates = False
        mgr._update_scheduler_instance_info(self.context,
                                            mock.sentinel.instance)
        mgr._delete_scheduler_instance_info(self.context,
                                            mock.sentinel.instance_uuid)
        mgr._sync_scheduler_instance_info(self.context)
        # None of the calls should have been made
        self.assertFalse(mock_update.called)
        self.assertFalse(mock_delete.called)
        self.assertFalse(mock_sync.called)

    def test_refresh_instance_security_rules_takes_non_object(self):
        inst = objects.Instance(uuid=uuids.instance)
        with mock.patch.object(self.compute.driver,
                               'refresh_instance_security_rules') as mock_r:
            self.compute.refresh_instance_security_rules(self.context, inst)
            self.assertIsInstance(mock_r.call_args_list[0][0][0],
                                  objects.Instance)

    def test_set_instance_obj_error_state_with_clean_task_state(self):
        instance = fake_instance.fake_instance_obj(self.context,
            vm_state=vm_states.BUILDING, task_state=task_states.SPAWNING)
        with mock.patch.object(instance, 'save'):
            self.compute._set_instance_obj_error_state(self.context, instance,
                                                       clean_task_state=True)
            self.assertEqual(vm_states.ERROR, instance.vm_state)
            self.assertIsNone(instance.task_state)

    def test_set_instance_obj_error_state_by_default(self):
        instance = fake_instance.fake_instance_obj(self.context,
            vm_state=vm_states.BUILDING, task_state=task_states.SPAWNING)
        with mock.patch.object(instance, 'save'):
            self.compute._set_instance_obj_error_state(self.context, instance)
            self.assertEqual(vm_states.ERROR, instance.vm_state)
            self.assertEqual(task_states.SPAWNING, instance.task_state)

    @mock.patch.object(objects.Instance, 'save')
    def test_instance_update(self, mock_save):
        instance = objects.Instance(task_state=task_states.SCHEDULING,
                                    vm_state=vm_states.BUILDING)
        updates = {'task_state': None, 'vm_state': vm_states.ERROR}

        with mock.patch.object(self.compute,
                               '_update_resource_tracker') as mock_rt:
            self.compute._instance_update(self.context, instance, **updates)

            self.assertIsNone(instance.task_state)
            self.assertEqual(vm_states.ERROR, instance.vm_state)
            mock_save.assert_called_once_with()
            mock_rt.assert_called_once_with(self.context, instance)

    def test_reset_reloads_rpcapi(self):
        orig_rpc = self.compute.compute_rpcapi
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            self.compute.reset()
            mock_rpc.assert_called_once_with()
            self.assertIsNot(orig_rpc, self.compute.compute_rpcapi)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.compute.manager.ComputeManager._delete_instance')
    def test_terminate_instance_no_bdm_volume_id(self, mock_delete_instance,
                                                 mock_bdm_get_by_inst):
        # Tests that we refresh the bdm list if a volume bdm does not have the
        # volume_id set.
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ERROR,
            task_state=task_states.DELETING)
        bdm = fake_block_device.FakeDbBlockDeviceDict(
            {'source_type': 'snapshot', 'destination_type': 'volume',
             'instance_uuid': instance.uuid, 'device_name': '/dev/vda'})
        bdms = block_device_obj.block_device_make_list(self.context, [bdm])
        # since the bdms passed in don't have a volume_id, we'll go back to the
        # database looking for updated versions
        mock_bdm_get_by_inst.return_value = bdms
        self.compute.terminate_instance(self.context, instance, bdms)
        mock_bdm_get_by_inst.assert_called_once_with(
            self.context, instance.uuid)
        mock_delete_instance.assert_called_once_with(
            self.context, instance, bdms)

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch.object(nova.compute.manager.ComputeManager,
                       '_notify_about_instance_usage')
    @mock.patch.object(compute_utils, 'EventReporter')
    def test_trigger_crash_dump(self, event_mock, notify_mock,
                                mock_instance_action_notify):
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE)

        self.compute.trigger_crash_dump(self.context, instance)

        mock_instance_action_notify.assert_has_calls([
            mock.call(self.context, instance, 'fake-mini',
                      action='trigger_crash_dump', phase='start'),
            mock.call(self.context, instance, 'fake-mini',
                      action='trigger_crash_dump', phase='end')])

        notify_mock.assert_has_calls([
            mock.call(self.context, instance, 'trigger_crash_dump.start'),
            mock.call(self.context, instance, 'trigger_crash_dump.end')
        ])
        self.assertIsNone(instance.task_state)
        self.assertEqual(vm_states.ACTIVE, instance.vm_state)

    def test_instance_restore_notification(self):
        inst_obj = fake_instance.fake_instance_obj(self.context,
            vm_state=vm_states.SOFT_DELETED)
        with test.nested(
            mock.patch.object(nova.compute.utils,
                              'notify_about_instance_action'),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(self.compute.driver, 'restore')
        ) as (
            fake_notify, fake_usage, fake_save, fake_restore
        ):
            self.compute.restore_instance(self.context, inst_obj)
            fake_notify.assert_has_calls([
                mock.call(self.context, inst_obj, 'fake-mini',
                          action='restore', phase='start'),
                mock.call(self.context, inst_obj, 'fake-mini',
                          action='restore', phase='end')])

    def test_delete_image_on_error_image_not_found_ignored(self):
        """Tests that we don't log an exception trace if we get a 404 when
        trying to delete an image as part of the image cleanup decorator.
        """
        @manager.delete_image_on_error
        def some_image_related_op(self, context, image_id, instance):
            raise test.TestingException('oops!')

        image_id = uuids.image_id
        instance = objects.Instance(uuid=uuids.instance_uuid)

        with mock.patch.object(manager.LOG, 'exception') as mock_log:
            with mock.patch.object(
                    self, 'image_api', create=True) as mock_image_api:
                mock_image_api.delete.side_effect = (
                    exception.ImageNotFound(image_id=image_id))
                self.assertRaises(test.TestingException,
                                  some_image_related_op,
                                  self, self.context, image_id, instance)

        mock_image_api.delete.assert_called_once_with(
            self.context, image_id)
        # make sure nothing was logged at exception level
        mock_log.assert_not_called()

    @mock.patch('nova.volume.cinder.API.attachment_delete')
    @mock.patch('nova.volume.cinder.API.attachment_create',
                return_value={'id': uuids.attachment_id})
    @mock.patch('nova.objects.BlockDeviceMapping.save')
    @mock.patch('nova.volume.cinder.API.terminate_connection')
    def test_terminate_volume_connections(self, mock_term_conn,
                                          mock_bdm_save,
                                          mock_attach_create,
                                          mock_attach_delete):
        """Tests _terminate_volume_connections with cinder v2 style,
        cinder v3.44 style, and non-volume BDMs.
        """
        bdms = objects.BlockDeviceMappingList(
            objects=[
                # We use two old-style BDMs to make sure we only build the
                # connector object once.
                objects.BlockDeviceMapping(volume_id=uuids.v2_volume_id_1,
                                           destination_type='volume',
                                           attachment_id=None),
                objects.BlockDeviceMapping(volume_id=uuids.v2_volume_id_2,
                                           destination_type='volume',
                                           attachment_id=None),
                objects.BlockDeviceMapping(volume_id=uuids.v3_volume_id,
                                           destination_type='volume',
                                           attachment_id=uuids.attach_id),
                objects.BlockDeviceMapping(volume_id=None,
                                           destination_type='local')
            ])
        instance = fake_instance.fake_instance_obj(
            self.context, vm_state=vm_states.ACTIVE)
        fake_connector = mock.sentinel.fake_connector
        with mock.patch.object(self.compute.driver, 'get_volume_connector',
                               return_value=fake_connector) as connector_mock:
            self.compute._terminate_volume_connections(
                self.context, instance, bdms)
        # assert we called terminate_connection twice (once per old volume bdm)
        mock_term_conn.assert_has_calls([
            mock.call(self.context, uuids.v2_volume_id_1, fake_connector),
            mock.call(self.context, uuids.v2_volume_id_2, fake_connector)
        ])
        # assert we only build the connector once
        connector_mock.assert_called_once_with(instance)
        # assert we called delete_attachment once for the single new volume bdm
        mock_attach_delete.assert_called_once_with(
            self.context, uuids.attach_id)
        mock_attach_create.assert_called_once_with(
            self.context, uuids.v3_volume_id, instance.uuid)

    def test_instance_soft_delete_notification(self):
        inst_obj = fake_instance.fake_instance_obj(self.context,
            vm_state=vm_states.ACTIVE)
        with test.nested(
            mock.patch.object(nova.compute.utils,
                              'notify_about_instance_action'),
            mock.patch.object(nova.compute.utils,
                              'notify_about_instance_delete'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(self.compute.driver, 'soft_delete')
        ) as (fake_notify, fake_notify_usage, fake_save, fake_soft_delete):
            self.compute.soft_delete_instance(self.context, inst_obj)
            fake_notify.assert_has_calls([
                mock.call(self.context, inst_obj, 'fake-mini',
                          action='soft_delete', phase='start'),
                mock.call(self.context, inst_obj, 'fake-mini',
                          action='soft_delete', phase='end')])

    def test_get_scheduler_hints(self):
        # 1. No hints and no request_spec.
        self.assertEqual({}, self.compute._get_scheduler_hints({}))
        # 2. Hints come from the filter_properties.
        hints = {'foo': 'bar'}
        filter_properties = {'scheduler_hints': hints}
        self.assertEqual(
            hints, self.compute._get_scheduler_hints(filter_properties))
        # 3. Hints come from filter_properties because reqspec is empty.
        reqspec = objects.RequestSpec.from_primitives(self.context, {}, {})
        self.assertEqual(
            hints, self.compute._get_scheduler_hints(
                filter_properties, reqspec))
        # 4. Hints come from the request spec.
        reqspec_hints = {'boo': 'baz'}
        reqspec = objects.RequestSpec.from_primitives(
            self.context, {}, {'scheduler_hints': reqspec_hints})
        # The RequestSpec unconditionally stores hints as a key=list
        # unlike filter_properties which just stores whatever came in from
        # the API request.
        expected_reqspec_hints = {'boo': ['baz']}
        self.assertDictEqual(
            expected_reqspec_hints, self.compute._get_scheduler_hints(
                filter_properties, reqspec))

    def test_notify_volume_usage_detach_no_block_stats(self):
        """Tests the case that the virt driver returns None from the
        block_stats() method and no notification is sent, similar to the
        virt driver raising NotImplementedError.
        """
        self.flags(volume_usage_poll_interval=60)
        fake_instance = objects.Instance()
        fake_bdm = objects.BlockDeviceMapping(device_name='/dev/vda')
        with mock.patch.object(self.compute.driver, 'block_stats',
                               return_value=None) as block_stats:
            # Assert a notification isn't sent.
            with mock.patch.object(self.compute.notifier, 'info',
                                   new_callable=mock.NonCallableMock):
                self.compute._notify_volume_usage_detach(
                    self.context, fake_instance, fake_bdm)
        block_stats.assert_called_once_with(fake_instance, 'vda')


class ComputeManagerBuildInstanceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerBuildInstanceTestCase, self).setUp()
        self.compute = manager.ComputeManager()
        self.context = context.RequestContext(fakes.FAKE_USER_ID,
                                              fakes.FAKE_PROJECT_ID)
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

        self.useFixture(fixtures.SpawnIsSynchronousFixture())

        def fake_network_info():
            return network_model.NetworkInfo([{'address': '1.2.3.4'}])

        self.network_info = network_model.NetworkInfoAsyncWrapper(
                fake_network_info)
        self.block_device_info = self.compute._prep_block_device(context,
                self.instance, self.block_device_mapping)

        # override tracker with a version that doesn't need the database:
        fake_rt = fake_resource_tracker.FakeResourceTracker(self.compute.host,
                    self.compute.driver)
        self.compute._resource_tracker = fake_rt

        self.allocations = [{
            "resource_provider": {
                "uuid": uuids.rp1,
            },
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 512,
            },
        }]
        self.mock_get_allocs = self.useFixture(
            fixtures.fixtures.MockPatch(
                'nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocations_for_consumer')).mock
        self.mock_get_allocs.return_value = self.allocations

    def _do_build_instance_update(self, mock_save, reschedule_update=False):
        mock_save.return_value = self.instance
        if reschedule_update:
            mock_save.side_effect = (self.instance, self.instance)

    @staticmethod
    def _assert_build_instance_update(mock_save,
                                      reschedule_update=False):
        if reschedule_update:
            mock_save.assert_has_calls([
                mock.call(expected_task_state=(task_states.SCHEDULING, None)),
                mock.call()])
        else:
            mock_save.assert_called_once_with(expected_task_state=
                                              (task_states.SCHEDULING, None))

    def _instance_action_events(self, mock_start, mock_finish):
        mock_start.assert_called_once_with(self.context, self.instance.uuid,
                mock.ANY, want_result=False)
        mock_finish.assert_called_once_with(self.context, self.instance.uuid,
                mock.ANY, exc_val=mock.ANY, exc_tb=mock.ANY, want_result=False)

    @staticmethod
    def _assert_build_instance_hook_called(mock_hooks, result):
        # NOTE(coreywright): we want to test the return value of
        # _do_build_and_run_instance, but it doesn't bubble all the way up, so
        # mock the hooking, which allows us to test that too, though a little
        # too intimately
        mock_hooks.setdefault().run_post.assert_called_once_with(
            'build_instance', result, mock.ANY, mock.ANY, f=None)

    def test_build_and_run_instance_called_with_proper_args(self):
        self._test_build_and_run_instance()

    def test_build_and_run_instance_with_unlimited_max_concurrent_builds(self):
        self.flags(max_concurrent_builds=0)
        self.compute = manager.ComputeManager()
        self._test_build_and_run_instance()

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def _test_build_and_run_instance(self, mock_hooks, mock_build, mock_save,
                                     mock_start, mock_finish):
        self._do_build_instance_update(mock_save)

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.ACTIVE)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save)
        mock_build.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})

    # This test when sending an icehouse compatible rpc call to juno compute
    # node, NetworkRequest object can load from three items tuple.
    @mock.patch.object(compute_utils, 'EventReporter')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.compute.manager.ComputeManager._build_and_run_instance')
    def test_build_and_run_instance_with_icehouse_requested_network(
            self, mock_build_and_run, mock_save, mock_event):
        mock_save.return_value = self.instance
        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=[objects.NetworkRequest(
                    network_id='fake_network_id',
                    address='10.0.0.1',
                    port_id=uuids.port_instance)],
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)
        requested_network = mock_build_and_run.call_args[0][5][0]
        self.assertEqual('fake_network_id', requested_network.network_id)
        self.assertEqual('10.0.0.1', str(requested_network.address))
        self.assertEqual(uuids.port_instance, requested_network.port_id)

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(manager.ComputeManager, '_cleanup_volumes')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(manager.ComputeManager, '_set_instance_obj_error_state')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def test_build_abort_exception(self, mock_hooks, mock_build_run,
                                   mock_build, mock_set, mock_nil, mock_add,
                                   mock_clean_vol, mock_clean_net, mock_save,
                                   mock_start, mock_finish):
        self._do_build_instance_update(mock_save)
        mock_build_run.side_effect = exception.BuildAbortException(reason='',
                                        instance_uuid=self.instance.uuid)

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save)
        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.FAILED)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})
        mock_clean_net.assert_called_once_with(self.context, self.instance,
                self.requested_networks)
        mock_clean_vol.assert_called_once_with(self.context,
                self.instance, self.block_device_mapping, raise_exc=False)
        mock_add.assert_called_once_with(self.context, self.instance,
                mock.ANY, mock.ANY)
        mock_nil.assert_called_once_with(self.instance)
        mock_set.assert_called_once_with(self.context, self.instance,
                clean_task_state=True)

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(manager.ComputeManager, '_set_instance_obj_error_state')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def test_rescheduled_exception(self, mock_hooks, mock_build_run,
                                   mock_build, mock_set, mock_nil,
                                   mock_save, mock_start, mock_finish):
        self.flags(use_neutron=False)
        self._do_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.side_effect = exception.RescheduledException(reason='',
                instance_uuid=self.instance.uuid)

        with mock.patch.object(
                self.compute.network_api,
                'cleanup_instance_network_on_host') as mock_clean:
            self.compute.build_and_run_instance(self.context, self.instance,
                    self.image, request_spec={},
                    filter_properties=self.filter_properties,
                    injected_files=self.injected_files,
                    admin_password=self.admin_pass,
                    requested_networks=self.requested_networks,
                    security_groups=self.security_groups,
                    block_device_mapping=self.block_device_mapping,
                    node=self.node, limits=self.limits,
                    host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})
        mock_clean.assert_called_once_with(self.context, self.instance,
                self.compute.host)
        mock_nil.assert_called_once_with(self.instance)
        mock_build.assert_called_once_with(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping,
                request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(manager.ComputeManager, '_shutdown_instance')
    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch.object(fake_driver.FakeDriver, 'spawn')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    def test_rescheduled_exception_with_non_ascii_exception(self,
            mock_notify, mock_save, mock_spawn, mock_build, mock_shutdown):
        exc = exception.NovaException(u's\xe9quence')

        mock_build.return_value = self.network_info
        mock_spawn.side_effect = exc

        self.assertRaises(exception.RescheduledException,
                          self.compute._build_and_run_instance,
                          self.context, self.instance, self.image,
                          self.injected_files, self.admin_pass,
                          self.requested_networks, self.security_groups,
                          self.block_device_mapping, self.node,
                          self.limits, self.filter_properties)
        mock_save.assert_has_calls([
            mock.call(),
            mock.call(),
            mock.call(expected_task_state='block_device_mapping'),
        ])
        mock_notify.assert_has_calls([
            mock.call(self.context, self.instance, 'create.start',
                extra_usage_info={'image_name': self.image.get('name')}),
            mock.call(self.context, self.instance, 'create.error', fault=exc)])
        mock_build.assert_called_once_with(self.context, self.instance,
            self.requested_networks, self.security_groups)
        mock_shutdown.assert_called_once_with(self.context, self.instance,
            self.block_device_mapping, self.requested_networks,
            try_deallocate_networks=False)
        mock_spawn.assert_called_once_with(self.context, self.instance,
            test.MatchType(objects.ImageMeta), self.injected_files,
            self.admin_pass, self.allocations, network_info=self.network_info,
            block_device_info=self.block_device_info)

    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(virt_driver.ComputeDriver, 'macs_for_instance')
    def test_rescheduled_exception_with_network_allocated(self,
            mock_macs_for_instance, mock_event_finish,
            mock_event_start, mock_ins_save,
            mock_build_ins, mock_build_and_run):
        self.flags(use_neutron=False)
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                system_metadata={'network_allocated': 'True'},
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        mock_ins_save.return_value = instance
        mock_macs_for_instance.return_value = []
        mock_build_and_run.side_effect = exception.RescheduledException(
            reason='', instance_uuid=self.instance.uuid)

        with mock.patch.object(
                self.compute.network_api,
                'cleanup_instance_network_on_host') as mock_cleanup_network:
            self.compute._do_build_and_run_instance(self.context, instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        mock_build_and_run.assert_called_once_with(self.context,
            instance,
            self.image, self.injected_files, self.admin_pass,
            self.requested_networks, self.security_groups,
            self.block_device_mapping, self.node, self.limits,
            self.filter_properties, {})
        mock_cleanup_network.assert_called_once_with(
            self.context, instance, self.compute.host)
        mock_build_ins.assert_called_once_with(self.context,
            [instance], self.image, self.filter_properties,
            self.admin_pass, self.injected_files, self.requested_networks,
            self.security_groups, self.block_device_mapping,
            request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(virt_driver.ComputeDriver, 'macs_for_instance')
    def test_rescheduled_exception_with_network_allocated_with_neutron(self,
            mock_macs_for_instance, mock_event_finish, mock_event_start,
            mock_ins_save, mock_build_ins, mock_cleanup_network,
            mock_build_and_run):
        """Tests that we always cleanup allocated networks for the instance
        when using neutron and before we reschedule off the failed host.
        """
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                system_metadata={'network_allocated': 'True'},
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        mock_ins_save.return_value = instance
        mock_macs_for_instance.return_value = []
        mock_build_and_run.side_effect = exception.RescheduledException(
            reason='', instance_uuid=self.instance.uuid)

        self.compute._do_build_and_run_instance(self.context, instance,
            self.image, request_spec={},
            filter_properties=self.filter_properties,
            injected_files=self.injected_files,
            admin_password=self.admin_pass,
            requested_networks=self.requested_networks,
            security_groups=self.security_groups,
            block_device_mapping=self.block_device_mapping, node=self.node,
            limits=self.limits, host_list=fake_host_list)

        mock_build_and_run.assert_called_once_with(self.context,
            instance,
            self.image, self.injected_files, self.admin_pass,
            self.requested_networks, self.security_groups,
            self.block_device_mapping, self.node, self.limits,
            self.filter_properties, {})
        mock_cleanup_network.assert_called_once_with(
            self.context, instance, self.requested_networks)
        mock_build_ins.assert_called_once_with(self.context,
            [instance], self.image, self.filter_properties,
            self.admin_pass, self.injected_files, self.requested_networks,
            self.security_groups, self.block_device_mapping,
            request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(virt_driver.ComputeDriver, 'macs_for_instance')
    def test_rescheduled_exception_with_sriov_network_allocated(self,
            mock_macs_for_instance, mock_event_finish,
            mock_event_start, mock_ins_save, mock_cleanup_network,
            mock_build_ins, mock_build_and_run):
        vif1 = fake_network_cache_model.new_vif()
        vif1['id'] = '1'
        vif1['vnic_type'] = network_model.VNIC_TYPE_NORMAL
        vif2 = fake_network_cache_model.new_vif()
        vif2['id'] = '2'
        vif1['vnic_type'] = network_model.VNIC_TYPE_DIRECT
        nw_info = network_model.NetworkInfo([vif1, vif2])
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                system_metadata={'network_allocated': 'True'},
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=instance.uuid)
        instance.info_cache = info_cache

        mock_ins_save.return_value = instance
        mock_macs_for_instance.return_value = []
        mock_build_and_run.side_effect = exception.RescheduledException(
            reason='', instance_uuid=self.instance.uuid)

        self.compute._do_build_and_run_instance(self.context, instance,
            self.image, request_spec={},
            filter_properties=self.filter_properties,
            injected_files=self.injected_files,
            admin_password=self.admin_pass,
            requested_networks=self.requested_networks,
            security_groups=self.security_groups,
            block_device_mapping=self.block_device_mapping, node=self.node,
            limits=self.limits, host_list=fake_host_list)

        mock_build_and_run.assert_called_once_with(self.context,
            instance,
            self.image, self.injected_files, self.admin_pass,
            self.requested_networks, self.security_groups,
            self.block_device_mapping, self.node, self.limits,
            self.filter_properties, {})
        mock_cleanup_network.assert_called_once_with(
            self.context, instance, self.requested_networks)
        mock_build_ins.assert_called_once_with(self.context,
            [instance], self.image, self.filter_properties,
            self.admin_pass, self.injected_files, self.requested_networks,
            self.security_groups, self.block_device_mapping,
            request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(manager.ComputeManager, '_cleanup_volumes')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(manager.ComputeManager, '_set_instance_obj_error_state')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def test_rescheduled_exception_without_retry(self, mock_hooks,
            mock_build_run, mock_add, mock_set, mock_clean_net, mock_clean_vol,
            mock_nil, mock_save, mock_start, mock_finish):
        self._do_build_instance_update(mock_save)
        mock_build_run.side_effect = exception.RescheduledException(reason='',
                instance_uuid=self.instance.uuid)

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties={},
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                build_results.FAILED)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits, {}, {})
        mock_clean_net.assert_called_once_with(self.context, self.instance,
                self.requested_networks)
        mock_clean_vol.assert_called_once_with(self.context,
                self.instance, self.block_device_mapping,
                raise_exc=False)
        mock_add.assert_called_once_with(self.context, self.instance,
                mock.ANY, mock.ANY, fault_message=mock.ANY)
        mock_nil.assert_called_once_with(self.instance)
        mock_set.assert_called_once_with(self.context, self.instance,
                clean_task_state=True)

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(fake_driver.FakeDriver,
                       'deallocate_networks_on_reschedule')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def test_rescheduled_exception_do_not_deallocate_network(self, mock_hooks,
            mock_build_run, mock_build, mock_deallocate, mock_nil,
            mock_clean_net, mock_save, mock_start,
            mock_finish):
        self.flags(use_neutron=False)
        self._do_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.side_effect = exception.RescheduledException(reason='',
                instance_uuid=self.instance.uuid)
        mock_deallocate.return_value = False

        with mock.patch.object(
                self.compute.network_api,
                'cleanup_instance_network_on_host') as mock_clean_inst:
            self.compute.build_and_run_instance(self.context, self.instance,
                    self.image, request_spec={},
                    filter_properties=self.filter_properties,
                    injected_files=self.injected_files,
                    admin_password=self.admin_pass,
                    requested_networks=self.requested_networks,
                    security_groups=self.security_groups,
                    block_device_mapping=self.block_device_mapping,
                    node=self.node, limits=self.limits,
                    host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})
        mock_deallocate.assert_called_once_with(self.instance)
        mock_clean_inst.assert_called_once_with(self.context, self.instance,
                self.compute.host)
        mock_nil.assert_called_once_with(self.instance)
        mock_build.assert_called_once_with(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping,
                request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(fake_driver.FakeDriver,
                       'deallocate_networks_on_reschedule')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def test_rescheduled_exception_deallocate_network(self, mock_hooks,
            mock_build_run, mock_build, mock_deallocate, mock_nil, mock_clean,
            mock_save, mock_start, mock_finish):
        self._do_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.side_effect = exception.RescheduledException(reason='',
                instance_uuid=self.instance.uuid)
        mock_deallocate.return_value = True

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.RESCHEDULED)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save, reschedule_update=True)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})
        mock_deallocate.assert_called_once_with(self.instance)
        mock_clean.assert_called_once_with(self.context, self.instance,
                self.requested_networks)
        mock_nil.assert_called_once_with(self.instance)
        mock_build.assert_called_once_with(self.context,
                [self.instance], self.image, self.filter_properties,
                self.admin_pass, self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping,
                request_spec={}, host_lists=[fake_host_list])

    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_cleanup_allocated_networks')
    @mock.patch.object(manager.ComputeManager, '_cleanup_volumes')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(manager.ComputeManager, '_set_instance_obj_error_state')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(manager.ComputeManager, '_build_and_run_instance')
    @mock.patch('nova.hooks._HOOKS')
    def _test_build_and_run_exceptions(self, exc, mock_hooks, mock_build_run,
                mock_build, mock_set, mock_nil, mock_add, mock_clean_vol,
                mock_clean_net, mock_save, mock_start, mock_finish,
                set_error=False, cleanup_volumes=False,
                nil_out_host_and_node=False):
        self._do_build_instance_update(mock_save)
        mock_build_run.side_effect = exc

        self.compute.build_and_run_instance(self.context, self.instance,
                self.image, request_spec={},
                filter_properties=self.filter_properties,
                injected_files=self.injected_files,
                admin_password=self.admin_pass,
                requested_networks=self.requested_networks,
                security_groups=self.security_groups,
                block_device_mapping=self.block_device_mapping, node=self.node,
                limits=self.limits, host_list=fake_host_list)

        self._assert_build_instance_hook_called(mock_hooks,
                                                build_results.FAILED)
        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save)
        if cleanup_volumes:
            mock_clean_vol.assert_called_once_with(self.context,
                    self.instance, self.block_device_mapping,
                    raise_exc=False)
        if nil_out_host_and_node:
            mock_nil.assert_called_once_with(self.instance)
        if set_error:
            mock_add.assert_called_once_with(self.context, self.instance,
                    mock.ANY, mock.ANY)
            mock_set.assert_called_once_with(self.context,
                    self.instance, clean_task_state=True)
        mock_build_run.assert_called_once_with(self.context, self.instance,
                self.image, self.injected_files, self.admin_pass,
                self.requested_networks, self.security_groups,
                self.block_device_mapping, self.node, self.limits,
                self.filter_properties, {})
        mock_clean_net.assert_called_once_with(self.context, self.instance,
                self.requested_networks)

    def test_build_and_run_notfound_exception(self):
        self._test_build_and_run_exceptions(exception.InstanceNotFound(
            instance_id=''))

    def test_build_and_run_unexpecteddeleting_exception(self):
        self._test_build_and_run_exceptions(
                exception.UnexpectedDeletingTaskStateError(
                    instance_uuid=uuids.instance, expected={}, actual={}))

    def test_build_and_run_buildabort_exception(self):
        self._test_build_and_run_exceptions(
            exception.BuildAbortException(instance_uuid='', reason=''),
            set_error=True, cleanup_volumes=True, nil_out_host_and_node=True)

    def test_build_and_run_unhandled_exception(self):
        self._test_build_and_run_exceptions(test.TestingException(),
                set_error=True, cleanup_volumes=True,
                nil_out_host_and_node=True)

    @mock.patch.object(manager.ComputeManager, '_do_build_and_run_instance')
    @mock.patch('nova.compute.stats.Stats.build_failed')
    def test_build_failures_reported(self, mock_failed, mock_dbari):
        mock_dbari.return_value = build_results.FAILED
        instance = objects.Instance(uuid=uuids.instance)
        for i in range(0, 10):
            self.compute.build_and_run_instance(self.context, instance, None,
                                                None, None)

        self.assertEqual(10, mock_failed.call_count)

    @mock.patch.object(manager.ComputeManager, '_do_build_and_run_instance')
    @mock.patch('nova.compute.stats.Stats.build_failed')
    def test_build_failures_not_reported(self, mock_failed, mock_dbari):
        self.flags(consecutive_build_service_disable_threshold=0,
                   group='compute')
        mock_dbari.return_value = build_results.FAILED
        instance = objects.Instance(uuid=uuids.instance)
        for i in range(0, 10):
            self.compute.build_and_run_instance(self.context, instance, None,
                                                None, None)

        mock_failed.assert_not_called()

    @mock.patch.object(manager.ComputeManager, '_do_build_and_run_instance')
    @mock.patch.object(manager.ComputeManager, '_build_failed')
    @mock.patch.object(manager.ComputeManager, '_build_succeeded')
    def test_transient_build_failures_no_report(self, mock_succeeded,
                                                mock_failed,
                                                mock_dbari):
        results = [build_results.FAILED,
                   build_results.ACTIVE,
                   build_results.RESCHEDULED]

        def _fake_build(*a, **k):
            if results:
                return results.pop(0)
            else:
                return build_results.ACTIVE

        mock_dbari.side_effect = _fake_build
        instance = objects.Instance(uuid=uuids.instance)
        for i in range(0, 10):
            self.compute.build_and_run_instance(self.context, instance, None,
                                                None, None)

        self.assertEqual(2, mock_failed.call_count)
        self.assertEqual(8, mock_succeeded.call_count)

    @mock.patch.object(manager.ComputeManager, '_do_build_and_run_instance')
    @mock.patch.object(manager.ComputeManager, '_build_failed')
    @mock.patch.object(manager.ComputeManager, '_build_succeeded')
    def test_build_reschedules_reported(self, mock_succeeded,
                                        mock_failed,
                                        mock_dbari):
        mock_dbari.return_value = build_results.RESCHEDULED
        instance = objects.Instance(uuid=uuids.instance)
        for i in range(0, 10):
            self.compute.build_and_run_instance(self.context, instance, None,
                                                None, None)

        self.assertEqual(10, mock_failed.call_count)
        mock_succeeded.assert_not_called()

    @mock.patch.object(manager.ComputeManager, '_do_build_and_run_instance')
    @mock.patch('nova.exception_wrapper._emit_exception_notification')
    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager, '_build_failed')
    @mock.patch.object(manager.ComputeManager, '_build_succeeded')
    def test_build_exceptions_reported(self, mock_succeeded,
                                       mock_failed,
                                       mock_if, mock_notify,
                                       mock_dbari):
        mock_dbari.side_effect = test.TestingException()
        instance = objects.Instance(uuid=uuids.instance,
                                    task_state=None)
        for i in range(0, 10):
            self.assertRaises(test.TestingException,
                              self.compute.build_and_run_instance,
                              self.context, instance, None,
                              None, None)

        self.assertEqual(10, mock_failed.call_count)
        mock_succeeded.assert_not_called()

    @mock.patch.object(manager.ComputeManager, '_shutdown_instance')
    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch.object(fake_driver.FakeDriver, 'spawn')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    def _test_instance_exception(self, exc, raised_exc,
                                 mock_notify, mock_save, mock_spawn,
                                 mock_build, mock_shutdown):
        """This method test the instance related InstanceNotFound
            and reschedule on exception errors. The test cases get from
            arguments.

            :param exc: Injected exception into the code under test
            :param exception: Raised exception in test case
            :param result: At end the excepted state
        """
        mock_build.return_value = self.network_info
        mock_spawn.side_effect = exc

        self.assertRaises(raised_exc,
                          self.compute._build_and_run_instance,
                          self.context, self.instance, self.image,
                          self.injected_files, self.admin_pass,
                          self.requested_networks, self.security_groups,
                          self.block_device_mapping, self.node,
                          self.limits, self.filter_properties)

        mock_save.assert_has_calls([
            mock.call(),
            mock.call(),
            mock.call(expected_task_state='block_device_mapping')])
        mock_notify.assert_has_calls([
            mock.call(self.context, self.instance, 'create.start',
                      extra_usage_info={'image_name': self.image.get('name')}),
            mock.call(self.context, self.instance, 'create.error',
                      fault=exc)])
        mock_build.assert_called_once_with(
            self.context, self.instance, self.requested_networks,
            self.security_groups)
        mock_shutdown.assert_called_once_with(
            self.context, self.instance, self.block_device_mapping,
            self.requested_networks, try_deallocate_networks=False)
        mock_spawn.assert_called_once_with(
            self.context, self.instance, test.MatchType(objects.ImageMeta),
            self.injected_files, self.admin_pass, self.allocations,
            network_info=self.network_info,
            block_device_info=self.block_device_info)

    def test_instance_not_found(self):
        got_exc = exception.InstanceNotFound(instance_id=1)
        self._test_instance_exception(got_exc, exception.InstanceNotFound)

    def test_reschedule_on_exception(self):
        got_exc = test.TestingException()
        self._test_instance_exception(got_exc, exception.RescheduledException)

    def test_spawn_network_alloc_failure(self):
        # Because network allocation is asynchronous, failures may not present
        # themselves until the virt spawn method is called.
        self._test_build_and_run_spawn_exceptions(exception.NoMoreNetworks())

    def test_spawn_network_auto_alloc_failure(self):
        # This isn't really a driver.spawn failure, it's a failure from
        # network_api.allocate_for_instance, but testing it here is convenient.
        self._test_build_and_run_spawn_exceptions(
            exception.UnableToAutoAllocateNetwork(
                project_id=self.context.project_id))

    def test_spawn_network_fixed_ip_not_valid_on_host_failure(self):
        self._test_build_and_run_spawn_exceptions(
            exception.FixedIpInvalidOnHost(port_id='fake-port-id'))

    def test_build_and_run_no_more_fixedips_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.NoMoreFixedIps("error messge"))

    def test_build_and_run_flavor_disk_smaller_image_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.FlavorDiskSmallerThanImage(
                flavor_size=0, image_size=1))

    def test_build_and_run_flavor_disk_smaller_min_disk(self):
        self._test_build_and_run_spawn_exceptions(
            exception.FlavorDiskSmallerThanMinDisk(
                flavor_size=0, image_min_disk=1))

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

    def test_build_and_run_invalid_disk_info_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.InvalidDiskInfo(reason=""))

    def test_build_and_run_invalid_disk_format_exception(self):
        self._test_build_and_run_spawn_exceptions(
            exception.InvalidDiskFormat(disk_format=""))

    def test_build_and_run_signature_verification_error(self):
        self._test_build_and_run_spawn_exceptions(
            cursive_exception.SignatureVerificationError(reason=""))

    def test_build_and_run_volume_encryption_not_supported(self):
        self._test_build_and_run_spawn_exceptions(
            exception.VolumeEncryptionNotSupported(volume_type='something',
                                                   volume_id='something'))

    def test_build_and_run_invalid_input(self):
        self._test_build_and_run_spawn_exceptions(
            exception.InvalidInput(reason=""))

    def test_build_and_run_requested_vram_too_high(self):
        self._test_build_and_run_spawn_exceptions(
            exception.RequestedVRamTooHigh(req_vram=200, max_vram=100))

    def _test_build_and_run_spawn_exceptions(self, exc):
        with test.nested(
                mock.patch.object(self.compute.driver, 'spawn',
                    side_effect=exc),
                mock.patch.object(self.instance, 'save',
                    side_effect=[self.instance, self.instance, self.instance]),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance',
                    return_value=self.network_info),
                mock.patch.object(self.compute,
                    '_notify_about_instance_usage'),
                mock.patch.object(self.compute,
                    '_shutdown_instance'),
                mock.patch.object(self.compute,
                    '_validate_instance_group_policy'),
                mock.patch('nova.compute.utils.notify_about_instance_create')
        ) as (spawn, save,
                _build_networks_for_instance, _notify_about_instance_usage,
                _shutdown_instance, _validate_instance_group_policy,
                mock_notify):

            self.assertRaises(exception.BuildAbortException,
                    self.compute._build_and_run_instance, self.context,
                    self.instance, self.image, self.injected_files,
                    self.admin_pass, self.requested_networks,
                    self.security_groups, self.block_device_mapping, self.node,
                    self.limits, self.filter_properties)

            _validate_instance_group_policy.assert_called_once_with(
                    self.context, self.instance, {})
            _build_networks_for_instance.assert_has_calls(
                    [mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups)])

            _notify_about_instance_usage.assert_has_calls([
                mock.call(self.context, self.instance, 'create.start',
                    extra_usage_info={'image_name': self.image.get('name')}),
                mock.call(self.context, self.instance, 'create.error',
                    fault=exc)])

            mock_notify.assert_has_calls([
                mock.call(self.context, self.instance, 'fake-mini',
                          phase='start', bdms=[]),
                mock.call(self.context, self.instance, 'fake-mini',
                          phase='error', exception=exc, bdms=[])])

            save.assert_has_calls([
                mock.call(),
                mock.call(),
                mock.call(
                    expected_task_state=task_states.BLOCK_DEVICE_MAPPING)])

            spawn.assert_has_calls([mock.call(self.context, self.instance,
                test.MatchType(objects.ImageMeta),
                self.injected_files, self.admin_pass, self.allocations,
                network_info=self.network_info,
                block_device_info=self.block_device_info)])

            _shutdown_instance.assert_called_once_with(self.context,
                    self.instance, self.block_device_mapping,
                    self.requested_networks, try_deallocate_networks=False)

    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    @mock.patch.object(objects.InstanceActionEvent,
                       'event_finish_with_failure')
    @mock.patch.object(objects.InstanceActionEvent, 'event_start')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager,
                       '_nil_out_instance_obj_host_and_node')
    @mock.patch.object(conductor_api.ComputeTaskAPI, 'build_instances')
    @mock.patch.object(resource_tracker.ResourceTracker, 'instance_claim')
    def test_reschedule_on_resources_unavailable(self, mock_claim,
                mock_build, mock_nil, mock_save, mock_start,
                mock_finish, mock_notify):
        self.flags(use_neutron=False)
        reason = 'resource unavailable'
        exc = exception.ComputeResourcesUnavailable(reason=reason)
        mock_claim.side_effect = exc
        self._do_build_instance_update(mock_save, reschedule_update=True)

        with mock.patch.object(
                self.compute.network_api,
                'cleanup_instance_network_on_host') as mock_clean:
            self.compute.build_and_run_instance(self.context, self.instance,
                    self.image, request_spec={},
                    filter_properties=self.filter_properties,
                    injected_files=self.injected_files,
                    admin_password=self.admin_pass,
                    requested_networks=self.requested_networks,
                    security_groups=self.security_groups,
                    block_device_mapping=self.block_device_mapping,
                    node=self.node, limits=self.limits,
                    host_list=fake_host_list)

        self._instance_action_events(mock_start, mock_finish)
        self._assert_build_instance_update(mock_save, reschedule_update=True)
        mock_claim.assert_called_once_with(self.context, self.instance,
            self.node, self.limits)
        mock_notify.assert_has_calls([
            mock.call(self.context, self.instance, 'create.start',
                extra_usage_info= {'image_name': self.image.get('name')}),
            mock.call(self.context, self.instance, 'create.error', fault=exc)])
        mock_build.assert_called_once_with(self.context, [self.instance],
                self.image, self.filter_properties, self.admin_pass,
                self.injected_files, self.requested_networks,
                self.security_groups, self.block_device_mapping,
                request_spec={}, host_lists=[fake_host_list])
        mock_nil.assert_called_once_with(self.instance)
        mock_clean.assert_called_once_with(self.context, self.instance,
                self.compute.host)

    @mock.patch.object(manager.ComputeManager, '_build_resources')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    def test_build_resources_buildabort_reraise(self, mock_notify, mock_save,
                                                mock_build):
        exc = exception.BuildAbortException(
                instance_uuid=self.instance.uuid, reason='')
        mock_build.side_effect = exc

        self.assertRaises(exception.BuildAbortException,
                          self.compute._build_and_run_instance,
                          self.context,
                          self.instance, self.image, self.injected_files,
                          self.admin_pass, self.requested_networks,
                          self.security_groups, self.block_device_mapping,
                          self.node, self.limits, self.filter_properties)

        mock_save.assert_called_once_with()
        mock_notify.assert_has_calls([
            mock.call(self.context, self.instance, 'create.start',
                extra_usage_info={'image_name': self.image.get('name')}),
            mock.call(self.context, self.instance, 'create.error',
                fault=exc)])
        mock_build.assert_called_once_with(self.context, self.instance,
            self.requested_networks, self.security_groups,
            test.MatchType(objects.ImageMeta), self.block_device_mapping)

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch.object(manager.ComputeManager, '_prep_block_device')
    @mock.patch.object(virt_driver.ComputeDriver,
                       'prepare_networks_before_block_device_mapping')
    @mock.patch.object(virt_driver.ComputeDriver,
                       'clean_networks_preparation')
    def test_build_resources_reraises_on_failed_bdm_prep(
            self, mock_clean, mock_prepnet, mock_prep, mock_build, mock_save):
        mock_save.return_value = self.instance
        mock_build.return_value = self.network_info
        mock_prep.side_effect = test.TestingException

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                pass
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

        mock_save.assert_called_once_with()
        mock_build.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_prep.assert_called_once_with(self.context, self.instance,
                self.block_device_mapping)
        mock_prepnet.assert_called_once_with(self.instance, self.network_info)
        mock_clean.assert_called_once_with(self.instance, self.network_info)

    @mock.patch('nova.virt.block_device.attach_block_devices',
                side_effect=exception.VolumeNotCreated('oops!'))
    def test_prep_block_device_maintain_original_error_message(self,
                                                               mock_attach):
        """Tests that when attach_block_devices raises an Exception, the
        re-raised InvalidBDM has the original error message which contains
        the actual details of the failure.
        """
        bdms = objects.BlockDeviceMappingList(
            objects=[fake_block_device.fake_bdm_object(
                self.context,
                dict(source_type='image',
                     destination_type='volume',
                     boot_index=0,
                     image_id=uuids.image_id,
                     device_name='/dev/vda',
                     volume_size=1))])
        ex = self.assertRaises(exception.InvalidBDM,
                               self.compute._prep_block_device,
                               self.context, self.instance, bdms)
        self.assertEqual('oops!', six.text_type(ex))

    @mock.patch('nova.objects.InstanceGroup.get_by_hint')
    def test_validate_policy_honors_workaround_disabled(self, mock_get):
        instance = objects.Instance(uuid=uuids.instance)
        hints = {'group': 'foo'}
        mock_get.return_value = objects.InstanceGroup(policies=[])
        self.compute._validate_instance_group_policy(self.context,
                                                     instance, hints)
        mock_get.assert_called_once_with(self.context, 'foo')

    @mock.patch('nova.objects.InstanceGroup.get_by_hint')
    def test_validate_policy_honors_workaround_enabled(self, mock_get):
        self.flags(disable_group_policy_check_upcall=True, group='workarounds')
        instance = objects.Instance(uuid=uuids.instance)
        hints = {'group': 'foo'}
        self.compute._validate_instance_group_policy(self.context,
                                                     instance, hints)
        self.assertFalse(mock_get.called)

    @mock.patch('nova.objects.InstanceGroup.get_by_hint')
    def test_validate_instance_group_policy_handles_hint_list(self, mock_get):
        """Tests that _validate_instance_group_policy handles getting
        scheduler_hints from a RequestSpec which stores the hints as a key=list
        pair.
        """
        instance = objects.Instance(uuid=uuids.instance)
        hints = {'group': [uuids.group_hint]}
        self.compute._validate_instance_group_policy(self.context,
                                                     instance, hints)
        mock_get.assert_called_once_with(self.context, uuids.group_hint)

    @mock.patch.object(virt_driver.ComputeDriver,
                       'prepare_networks_before_block_device_mapping')
    @mock.patch.object(virt_driver.ComputeDriver,
                       'clean_networks_preparation')
    def test_failed_bdm_prep_from_delete_raises_unexpected(self, mock_clean,
                                                           mock_prepnet):
        with test.nested(
                mock.patch.object(self.compute,
                    '_build_networks_for_instance',
                    return_value=self.network_info),
                mock.patch.object(self.instance, 'save',
                    side_effect=exception.UnexpectedDeletingTaskStateError(
                        instance_uuid=uuids.instance,
                        actual={'task_state': task_states.DELETING},
                        expected={'task_state': None})),
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
                    [mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups)])

            save.assert_has_calls([mock.call()])
        mock_prepnet.assert_called_once_with(self.instance, self.network_info)
        mock_clean.assert_called_once_with(self.instance, self.network_info)

    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    def test_build_resources_aborts_on_failed_network_alloc(self, mock_build):
        mock_build.side_effect = test.TestingException

        try:
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups, self.image,
                    self.block_device_mapping):
                pass
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

        mock_build.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)

    def test_failed_network_alloc_from_delete_raises_unexpected(self):
        with mock.patch.object(self.compute,
                '_build_networks_for_instance') as _build_networks:

            exc = exception.UnexpectedDeletingTaskStateError
            _build_networks.side_effect = exc(
                instance_uuid=uuids.instance,
                actual={'task_state': task_states.DELETING},
                expected={'task_state': None})

            try:
                with self.compute._build_resources(self.context, self.instance,
                        self.requested_networks, self.security_groups,
                        self.image, self.block_device_mapping):
                    pass
            except Exception as e:
                self.assertIsInstance(e, exc)

            _build_networks.assert_has_calls(
                    [mock.call(self.context, self.instance,
                        self.requested_networks, self.security_groups)])

    @mock.patch('nova.network.model.NetworkInfoAsyncWrapper.wait')
    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch('nova.objects.Instance.save')
    def test_build_resources_aborts_on_failed_allocations_get(
            self, mock_save, mock_bn, mock_net_wait):
        mock_bn.return_value = self.network_info
        mock_save.return_value = self.instance
        self.mock_get_allocs.side_effect = exception.NotFound()

        try:
            with self.compute._build_resources(
                    self.context, self.instance, self.requested_networks,
                    self.security_groups, self.image,
                    self.block_device_mapping):
                pass
        except Exception as e:
            self.assertIsInstance(e, exception.BuildAbortException)

        self.mock_get_allocs.assert_called_once_with(self.context,
                                                     self.instance.uuid)
        mock_net_wait.assert_called_once_with(do_raise=False)

    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch.object(manager.ComputeManager, '_shutdown_instance')
    @mock.patch.object(objects.Instance, 'save')
    def test_build_resources_cleans_up_and_reraises_on_spawn_failure(self,
                                        mock_save, mock_shutdown, mock_build):
        mock_save.return_value = self.instance
        mock_build.return_value = self.network_info
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

        mock_save.assert_called_once_with()
        mock_build.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_shutdown.assert_called_once_with(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)

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
    @mock.patch.object(virt_driver.ComputeDriver,
                       'prepare_networks_before_block_device_mapping')
    @mock.patch.object(virt_driver.ComputeDriver,
                       'clean_networks_preparation')
    def test_build_resources_unexpected_task_error_before_yield(
            self, mock_clean, mock_prepnet, mock_save, mock_build_network,
            mock_info_wait):
        mock_build_network.return_value = self.network_info
        mock_save.side_effect = exception.UnexpectedTaskStateError(
            instance_uuid=uuids.instance, expected={}, actual={})
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
        mock_prepnet.assert_called_once_with(self.instance, self.network_info)
        mock_clean.assert_called_once_with(self.instance, self.network_info)

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

    @mock.patch.object(manager.ComputeManager, '_build_networks_for_instance')
    @mock.patch.object(manager.ComputeManager, '_shutdown_instance')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch('nova.compute.manager.LOG')
    def test_build_resources_aborts_on_cleanup_failure(self, mock_log,
                                        mock_save, mock_shutdown, mock_build):
        mock_save.return_value = self.instance
        mock_build.return_value = self.network_info
        mock_shutdown.side_effect = test.TestingException('Failed to shutdown')

        def fake_spawn():
            raise test.TestingException('Failed to spawn')

        with self.assertRaisesRegex(exception.BuildAbortException,
                                    'Failed to spawn'):
            with self.compute._build_resources(self.context, self.instance,
                    self.requested_networks, self.security_groups,
                    self.image, self.block_device_mapping):
                fake_spawn()

        self.assertTrue(mock_log.warning.called)
        msg = mock_log.warning.call_args_list[0]
        self.assertIn('Failed to shutdown', msg[0][1])
        mock_save.assert_called_once_with()
        mock_build.assert_called_once_with(self.context, self.instance,
                self.requested_networks, self.security_groups)
        mock_shutdown.assert_called_once_with(self.context, self.instance,
                self.block_device_mapping, self.requested_networks,
                try_deallocate_networks=False)

    @mock.patch.object(manager.ComputeManager, '_allocate_network')
    @mock.patch.object(network_api.API, 'get_instance_nw_info')
    def test_build_networks_if_not_allocated(self, mock_get, mock_allocate):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata={},
                expected_attrs=['system_metadata'])

        nw_info_obj = self.compute._build_networks_for_instance(self.context,
                instance, self.requested_networks, self.security_groups)

        mock_allocate.assert_called_once_with(self.context, instance,
                self.requested_networks, None, self.security_groups)
        self.assertTrue(hasattr(nw_info_obj, 'wait'), "wait must be there")

    @mock.patch.object(manager.ComputeManager, '_allocate_network')
    @mock.patch.object(network_api.API, 'get_instance_nw_info')
    def test_build_networks_if_allocated_false(self, mock_get, mock_allocate):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata=dict(network_allocated='False'),
                expected_attrs=['system_metadata'])

        nw_info_obj = self.compute._build_networks_for_instance(self.context,
                instance, self.requested_networks, self.security_groups)

        mock_allocate.assert_called_once_with(self.context, instance,
                self.requested_networks, None, self.security_groups)
        self.assertTrue(hasattr(nw_info_obj, 'wait'), "wait must be there")

    @mock.patch.object(manager.ComputeManager, '_allocate_network')
    def test_return_networks_if_found(self, mock_allocate):
        instance = fake_instance.fake_instance_obj(self.context,
                system_metadata=dict(network_allocated='True'),
                expected_attrs=['system_metadata'])

        def fake_network_info():
            return network_model.NetworkInfo([{'address': '123.123.123.123'}])

        with test.nested(
                mock.patch.object(
                    self.compute.network_api,
                    'setup_instance_network_on_host'),
                mock.patch.object(
                    self.compute.network_api,
                    'get_instance_nw_info')) as (
            mock_setup, mock_get
        ):
            # this should be a NetworkInfo, not NetworkInfoAsyncWrapper, to
            # match what get_instance_nw_info really returns
            mock_get.return_value = fake_network_info()
            self.compute._build_networks_for_instance(self.context, instance,
                    self.requested_networks, self.security_groups)

        mock_get.assert_called_once_with(self.context, instance)
        mock_setup.assert_called_once_with(self.context, instance,
                                           instance.host)

    def test_cleanup_allocated_networks_instance_not_found(self):
        with test.nested(
                mock.patch.object(self.compute, '_deallocate_network'),
                mock.patch.object(self.instance, 'save',
                    side_effect=exception.InstanceNotFound(instance_id=''))
        ) as (_deallocate_network, save):
            # Testing that this doesn't raise an exception
            self.compute._cleanup_allocated_networks(self.context,
                    self.instance, self.requested_networks)
            save.assert_called_once_with()
            self.assertEqual('False',
                    self.instance.system_metadata['network_allocated'])

    def test_deallocate_network_none_requested(self):
        # Tests that we don't deallocate networks if 'none' were
        # specifically requested.
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='none')])
        with mock.patch.object(self.compute.network_api,
                               'deallocate_for_instance') as deallocate:
            self.compute._deallocate_network(
                self.context, mock.sentinel.instance, req_networks)
        self.assertFalse(deallocate.called)

    def test_deallocate_network_auto_requested_or_none_provided(self):
        # Tests that we deallocate networks if we were requested to
        # auto-allocate networks or requested_networks=None.
        req_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='auto')])
        for requested_networks in (req_networks, None):
            with mock.patch.object(self.compute.network_api,
                                   'deallocate_for_instance') as deallocate:
                self.compute._deallocate_network(
                    self.context, mock.sentinel.instance, requested_networks)
            deallocate.assert_called_once_with(
                self.context, mock.sentinel.instance,
                requested_networks=requested_networks)

    @mock.patch('nova.compute.utils.notify_about_instance_create')
    @mock.patch.object(manager.ComputeManager, '_instance_update')
    def test_launched_at_in_create_end_notification(self,
            mock_instance_update, mock_notify_instance_create):

        def fake_notify(*args, **kwargs):
            if args[2] == 'create.end':
                # Check that launched_at is set on the instance
                self.assertIsNotNone(args[1].launched_at)

        with test.nested(
                mock.patch.object(self.compute,
                    '_update_scheduler_instance_info'),
                mock.patch.object(self.compute.driver, 'spawn'),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance', return_value=[]),
                mock.patch.object(self.instance, 'save'),
                mock.patch.object(self.compute, '_notify_about_instance_usage',
                    side_effect=fake_notify)
        ) as (mock_upd, mock_spawn, mock_networks, mock_save, mock_notify):
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

            mock_notify_instance_create.assert_has_calls([
                mock.call(self.context, self.instance, 'fake-mini',
                          phase='start', bdms=[]),
                mock.call(self.context, self.instance, 'fake-mini',
                          phase='end', bdms=[])])

    def test_access_ip_set_when_instance_set_to_active(self):

        self.flags(default_access_ip_network_name='test1')
        instance = fake_instance.fake_db_instance()

        @mock.patch.object(db, 'instance_update_and_get_original',
                return_value=({}, instance))
        @mock.patch.object(self.compute.driver, 'spawn')
        @mock.patch.object(self.compute, '_build_networks_for_instance',
                return_value=fake_network.fake_get_instance_nw_info(self))
        @mock.patch.object(db, 'instance_extra_update_by_uuid')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        def _check_access_ip(mock_notify, mock_extra, mock_networks,
                mock_spawn, mock_db_update):
            self.compute._build_and_run_instance(self.context, self.instance,
                    self.image, self.injected_files, self.admin_pass,
                    self.requested_networks, self.security_groups,
                    self.block_device_mapping, self.node, self.limits,
                    self.filter_properties)

            updates = {'vm_state': u'active', 'access_ip_v6':
                    netaddr.IPAddress('2001:db8:0:1:dcad:beff:feef:1'),
                    'access_ip_v4': netaddr.IPAddress('192.168.1.100'),
                    'power_state': 0, 'task_state': None, 'launched_at':
                    mock.ANY, 'expected_task_state': 'spawning'}
            expected_call = mock.call(self.context, self.instance.uuid,
                    updates, columns_to_join=['metadata', 'system_metadata',
                        'info_cache', 'tags'])
            last_update_call = mock_db_update.call_args_list[
                mock_db_update.call_count - 1]
            self.assertEqual(expected_call, last_update_call)

        _check_access_ip()

    @mock.patch.object(manager.ComputeManager, '_instance_update')
    def test_create_error_on_instance_delete(self, mock_instance_update):

        def fake_notify(*args, **kwargs):
            if args[2] == 'create.error':
                # Check that launched_at is set on the instance
                self.assertIsNotNone(args[1].launched_at)

        exc = exception.InstanceNotFound(instance_id='')

        with test.nested(
                mock.patch.object(self.compute.driver, 'spawn'),
                mock.patch.object(self.compute,
                    '_build_networks_for_instance', return_value=[]),
                mock.patch.object(self.instance, 'save',
                    side_effect=[None, None, None, exc]),
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
                    'create.error', fault=exc)
            create_error_call = mock_notify.call_args_list[
                    mock_notify.call_count - 1]
            self.assertEqual(expected_call, create_error_call)


class ComputeManagerErrorsOutMigrationTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeManagerErrorsOutMigrationTestCase, self).setUp()
        self.context = context.RequestContext(fakes.FAKE_USER_ID,
                                              fakes.FAKE_PROJECT_ID)

        self.instance = fake_instance.fake_instance_obj(self.context)

        self.migration = objects.Migration()
        self.migration.instance_uuid = self.instance.uuid
        self.migration.status = 'migrating'
        self.migration.id = 0

    @mock.patch.object(objects.Migration, 'save')
    @mock.patch.object(objects.Migration, 'obj_as_admin')
    def test_decorator(self, mock_save, mock_obj_as_admin):
        # Tests that errors_out_migration decorator in compute manager sets
        # migration status to 'error' when an exception is raised from
        # decorated method

        @manager.errors_out_migration
        def fake_function(self, context, instance, migration):
            raise test.TestingException()

        mock_obj_as_admin.return_value = mock.MagicMock()

        self.assertRaises(test.TestingException, fake_function,
                          self, self.context, self.instance, self.migration)
        self.assertEqual('error', self.migration.status)
        mock_save.assert_called_once_with()
        mock_obj_as_admin.assert_called_once_with()

    @mock.patch.object(objects.Migration, 'save')
    @mock.patch.object(objects.Migration, 'obj_as_admin')
    def test_contextmanager(self, mock_save, mock_obj_as_admin):
        # Tests that errors_out_migration_ctxt context manager in compute
        # manager sets migration status to 'error' when an exception is raised
        # from decorated method

        def test_function():
            with manager.errors_out_migration_ctxt(self.migration):
                raise test.TestingException()

        mock_obj_as_admin.return_value = mock.MagicMock()

        self.assertRaises(test.TestingException, test_function)
        self.assertEqual('error', self.migration.status)
        mock_save.assert_called_once_with()
        mock_obj_as_admin.assert_called_once_with()


class ComputeManagerMigrationTestCase(test.NoDBTestCase):
    class TestResizeError(Exception):
        pass

    def setUp(self):
        super(ComputeManagerMigrationTestCase, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        self.compute = manager.ComputeManager()
        self.context = context.RequestContext(fakes.FAKE_USER_ID,
                                              fakes.FAKE_PROJECT_ID)
        self.image = {}
        self.instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.migration = objects.Migration(
            context=self.context.elevated(),
            uuid=mock.sentinel.uuid,
            instance_uuid=self.instance.uuid,
            new_instance_type_id=7,
            dest_compute=None,
            dest_node=None,
            dest_host=None,
            status='migrating')
        self.migration.save = mock.MagicMock()
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        self.useFixture(fixtures.EventReporterStub())

    @contextlib.contextmanager
    def _mock_finish_resize(self):
        with test.nested(
            mock.patch.object(self.compute, '_finish_resize'),
            mock.patch.object(db, 'instance_fault_create'),
            mock.patch.object(self.compute, '_update_resource_tracker'),
            mock.patch.object(self.instance, 'save'),
            mock.patch.object(objects.BlockDeviceMappingList,
                              'get_by_instance_uuid')
        ) as (_finish_resize, fault_create, instance_update, instance_save,
              get_bdm):
            fault_create.return_value = (
                test_instance_fault.fake_faults['fake-uuid'][0])
            yield _finish_resize

    def test_finish_resize_failure(self):
        self.migration.status = 'post-migrating'

        with self._mock_finish_resize() as _finish_resize:
            _finish_resize.side_effect = self.TestResizeError
            self.assertRaises(
                self.TestResizeError, self.compute.finish_resize,
                context=self.context, disk_info=[], image=self.image,
                instance=self.instance,
                migration=self.migration
            )

        # Assert that we set the migration to an error state
        self.assertEqual("error", self.migration.status)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_notify_about_instance_usage')
    def test_finish_resize_notify_failure(self, notify):
        self.migration.status = 'post-migrating'

        with self._mock_finish_resize():
            notify.side_effect = self.TestResizeError
            self.assertRaises(
                self.TestResizeError, self.compute.finish_resize,
                context=self.context, disk_info=[], image=self.image,
                instance=self.instance,
                migration=self.migration
            )

        # Assert that we did not set the migration to an error state
        self.assertEqual('post-migrating', self.migration.status)

    @contextlib.contextmanager
    def _mock_resize_instance(self):
        with test.nested(
            mock.patch.object(self.compute.driver,
                              'migrate_disk_and_power_off'),
            mock.patch.object(db, 'instance_fault_create'),
            mock.patch.object(self.compute, '_update_resource_tracker'),
            mock.patch.object(self.compute, 'network_api'),
            mock.patch.object(self.instance, 'save'),
            mock.patch.object(self.compute, '_notify_about_instance_usage'),
            mock.patch.object(self.compute,
                              '_get_instance_block_device_info'),
            mock.patch.object(objects.BlockDeviceMappingList,
                              'get_by_instance_uuid'),
            mock.patch.object(objects.Flavor, 'get_by_id'),
            mock.patch.object(self.compute, '_terminate_volume_connections'),
            mock.patch.object(self.compute, 'compute_rpcapi'),
        ) as (
            migrate_disk_and_power_off, fault_create, instance_update,
            network_api, save_inst, notify, vol_block_info, bdm, flavor,
            terminate_volume_connections, compute_rpcapi
        ):
            fault_create.return_value = (
                test_instance_fault.fake_faults['fake-uuid'][0])
            yield (migrate_disk_and_power_off, notify)

    def test_resize_instance_failure(self):
        with self._mock_resize_instance() as (
                migrate_disk_and_power_off, notify):
            migrate_disk_and_power_off.side_effect = self.TestResizeError
            self.assertRaises(
                self.TestResizeError, self.compute.resize_instance,
                context=self.context, instance=self.instance, image=self.image,
                migration=self.migration,
                instance_type='type', clean_shutdown=True)

        # Assert that we set the migration to an error state
        self.assertEqual("error", self.migration.status)

    def test_resize_instance_notify_failure(self):
        # Raise an exception sending the end notification, which is after we
        # cast the migration to the destination host
        def fake_notify(context, instance, event, network_info=None):
            if event == 'resize.end':
                raise self.TestResizeError()

        with self._mock_resize_instance() as (
                migrate_disk_and_power_off, notify_about_instance_action):
            notify_about_instance_action.side_effect = fake_notify
            self.assertRaises(
                self.TestResizeError, self.compute.resize_instance,
                context=self.context, instance=self.instance, image=self.image,
                migration=self.migration,
                instance_type='type', clean_shutdown=True)

        # Assert that we did not set the migration to an error state
        self.assertEqual('post-migrating', self.migration.status)

    def _test_revert_resize_instance_destroy_disks(self, is_shared=False):

        # This test asserts that _is_instance_storage_shared() is called from
        # revert_resize() and the return value is passed to driver.destroy().
        # Otherwise we could regress this.

        @mock.patch('nova.compute.rpcapi.ComputeAPI.finish_revert_resize')
        @mock.patch.object(self.instance, 'revert_migration_context')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info')
        @mock.patch.object(self.compute, '_is_instance_storage_shared')
        @mock.patch.object(self.compute, 'finish_revert_resize')
        @mock.patch.object(self.compute, '_instance_update')
        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute.driver, 'destroy')
        @mock.patch.object(self.compute.network_api, 'setup_networks_on_host')
        @mock.patch.object(self.compute.network_api, 'migrate_instance_start')
        @mock.patch.object(compute_utils, 'notify_usage_exists')
        @mock.patch.object(self.migration, 'save')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        def do_test(get_by_instance_uuid,
                    migration_save,
                    notify_usage_exists,
                    migrate_instance_start,
                    setup_networks_on_host,
                    destroy,
                    _get_resource_tracker,
                    _instance_update,
                    finish_revert_resize,
                    _is_instance_storage_shared,
                    get_instance_nw_info,
                    revert_migration_context,
                    mock_finish_revert):

            # NOTE(danms): Before a revert, the instance is "on"
            # the destination host/node
            self.migration.uuid = uuids.migration
            self.migration.source_compute = 'src'
            self.migration.source_node = 'srcnode'
            self.migration.dest_compute = self.instance.host
            self.migration.dest_node = self.instance.node

            # Inform compute that instance uses non-shared or shared storage
            _is_instance_storage_shared.return_value = is_shared

            self.compute.revert_resize(context=self.context,
                                       migration=self.migration,
                                       instance=self.instance)

            _is_instance_storage_shared.assert_called_once_with(
                self.context, self.instance,
                host=self.migration.source_compute)

            # If instance storage is shared, driver destroy method
            # should not destroy disks otherwise it should destroy disks.
            destroy.assert_called_once_with(self.context, self.instance,
                                            mock.ANY, mock.ANY, not is_shared)
            mock_finish_revert.assert_called_once_with(
                    self.context, self.instance, self.migration,
                    self.migration.source_compute)

        do_test()

    def test_revert_resize_instance_destroy_disks_shared_storage(self):
        self._test_revert_resize_instance_destroy_disks(is_shared=True)

    def test_revert_resize_instance_destroy_disks_non_shared_storage(self):
        self._test_revert_resize_instance_destroy_disks(is_shared=False)

    def test_finish_revert_resize_network_calls_order(self):
        self.nw_info = None

        def _migrate_instance_finish(context, instance, migration):
            self.nw_info = 'nw_info'

        def _get_instance_nw_info(context, instance):
            return self.nw_info

        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
        @mock.patch.object(self.compute.driver, 'finish_revert_migration')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                           side_effect=_get_instance_nw_info)
        @mock.patch.object(self.compute.network_api, 'migrate_instance_finish',
                           side_effect=_migrate_instance_finish)
        @mock.patch.object(self.compute.network_api, 'setup_networks_on_host')
        @mock.patch.object(self.migration, 'save')
        @mock.patch.object(self.instance, 'save')
        @mock.patch.object(self.compute, '_set_instance_info')
        @mock.patch.object(db, 'instance_fault_create')
        @mock.patch.object(db, 'instance_extra_update_by_uuid')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        @mock.patch.object(compute_utils, 'notify_about_instance_usage')
        def do_test(notify_about_instance_usage,
                    get_by_instance_uuid,
                    extra_update,
                    fault_create,
                    set_instance_info,
                    instance_save,
                    migration_save,
                    setup_networks_on_host,
                    migrate_instance_finish,
                    get_instance_nw_info,
                    finish_revert_migration,
                    mock_get_cn,
                    get_resource_tracker):

            fault_create.return_value = (
                test_instance_fault.fake_faults['fake-uuid'][0])
            self.instance.migration_context = objects.MigrationContext()
            self.migration.uuid = uuids.migration
            self.migration.source_compute = self.instance['host']
            self.migration.source_node = self.instance['host']
            self.compute.finish_revert_resize(context=self.context,
                                              migration=self.migration,
                                              instance=self.instance)
            finish_revert_migration.assert_called_with(self.context,
                self.instance, 'nw_info', mock.ANY, mock.ANY)

        do_test()

    def test_finish_revert_resize_migration_context(self):
        fake_rt = resource_tracker.ResourceTracker(None, None)
        fake_rt.tracked_migrations[self.instance['uuid']] = (
            self.migration, None)

        @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                    'drop_move_claim')
        @mock.patch.object(self.compute, '_delete_allocation_after_move')
        @mock.patch('nova.compute.rpcapi.ComputeAPI.finish_revert_resize')
        @mock.patch.object(self.instance, 'revert_migration_context')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info')
        @mock.patch.object(self.compute, '_is_instance_storage_shared')
        @mock.patch.object(self.compute, '_instance_update')
        @mock.patch.object(self.compute, '_get_resource_tracker',
                           return_value=fake_rt)
        @mock.patch.object(self.compute.driver, 'destroy')
        @mock.patch.object(self.compute.network_api, 'setup_networks_on_host')
        @mock.patch.object(self.compute.network_api, 'migrate_instance_start')
        @mock.patch.object(compute_utils, 'notify_usage_exists')
        @mock.patch.object(db, 'instance_extra_update_by_uuid')
        @mock.patch.object(self.migration, 'save')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        def do_revert_resize(mock_get_by_instance_uuid,
                             mock_migration_save,
                             mock_extra_update,
                             mock_notify_usage_exists,
                             mock_migrate_instance_start,
                             mock_setup_networks_on_host,
                             mock_destroy,
                             mock_get_resource_tracker,
                             mock_instance_update,
                             mock_is_instance_storage_shared,
                             mock_get_instance_nw_info,
                             mock_revert_migration_context,
                             mock_finish_revert,
                             mock_delete_allocation,
                             mock_drop_move_claim):

            self.instance.migration_context = objects.MigrationContext()
            self.migration.source_compute = self.instance['host']
            self.migration.source_node = self.instance['node']

            self.compute.revert_resize(context=self.context,
                                       migration=self.migration,
                                       instance=self.instance)
            mock_drop_move_claim.assert_called_once_with(self.context,
                self.instance, self.instance.node)
            mock_delete_allocation.assert_called_once_with(
                self.context, self.instance, self.migration,
                self.instance.flavor, self.instance.node)
            self.assertIsNotNone(self.instance.migration_context)

        # Three fake BDMs:
        # 1. volume BDM with an attachment_id which will be updated/completed
        # 2. volume BDM without an attachment_id so it's not updated
        # 3. non-volume BDM so it's not updated
        fake_bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(destination_type='volume',
                                       attachment_id=uuids.attachment_id,
                                       device_name='/dev/vdb'),
            objects.BlockDeviceMapping(destination_type='volume',
                                       attachment_id=None),
            objects.BlockDeviceMapping(destination_type='local')
        ])

        @mock.patch('nova.objects.Service.get_minimum_version',
                    return_value=22)
        @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
        @mock.patch.object(self.compute, "_notify_about_instance_usage")
        @mock.patch.object(compute_utils, 'notify_about_instance_action')
        @mock.patch.object(self.compute, "_set_instance_info")
        @mock.patch.object(self.instance, 'save')
        @mock.patch.object(self.migration, 'save')
        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(db, 'instance_fault_create')
        @mock.patch.object(db, 'instance_extra_update_by_uuid')
        @mock.patch.object(self.compute.network_api, 'setup_networks_on_host')
        @mock.patch.object(self.compute.network_api, 'migrate_instance_finish')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid', return_value=fake_bdms)
        @mock.patch.object(self.compute, '_get_instance_block_device_info')
        @mock.patch.object(self.compute.driver, 'get_volume_connector')
        @mock.patch.object(self.compute.volume_api, 'attachment_update')
        @mock.patch.object(self.compute.volume_api, 'attachment_complete')
        def do_finish_revert_resize(mock_attachment_complete,
                                    mock_attachment_update,
                                    mock_get_vol_connector,
                                    mock_get_blk,
                                    mock_get_by_instance_uuid,
                                    mock_get_instance_nw_info,
                                    mock_instance_finish,
                                    mock_setup_network,
                                    mock_extra_update,
                                    mock_fault_create,
                                    mock_fault_from_exc,
                                    mock_mig_save,
                                    mock_inst_save,
                                    mock_set,
                                    mock_notify_about_instance_action,
                                    mock_notify,
                                    mock_get_cn,
                                    mock_version):
            self.migration.uuid = uuids.migration
            self.compute.finish_revert_resize(context=self.context,
                                              instance=self.instance,
                                              migration=self.migration)
            self.assertIsNone(self.instance.migration_context)
            # We should only have one attachment_update/complete call for the
            # volume BDM that had an attachment.
            mock_attachment_update.assert_called_once_with(
                self.context, uuids.attachment_id,
                mock_get_vol_connector.return_value, '/dev/vdb')
            mock_attachment_complete.assert_called_once_with(
                self.context, uuids.attachment_id)

        do_revert_resize()
        do_finish_revert_resize()

    def test_confirm_resize_deletes_allocations(self):
        @mock.patch.object(self.migration, 'save')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, 'network_api')
        @mock.patch.object(self.compute.driver, 'confirm_migration')
        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, '_delete_allocation_after_move')
        @mock.patch.object(self.instance, 'drop_migration_context')
        @mock.patch.object(self.instance, 'save')
        def do_confirm_resize(mock_save, mock_drop, mock_delete, mock_get_rt,
                              mock_confirm, mock_nwapi, mock_notify,
                              mock_mig_save):
            self.instance.migration_context = objects.MigrationContext()
            self.migration.source_compute = self.instance['host']
            self.migration.source_node = self.instance['node']
            self.compute._confirm_resize(self.context, self.instance,
                                         self.migration)
            mock_delete.assert_called_once_with(self.context, self.instance,
                                                self.migration,
                                                self.instance.old_flavor,
                                                self.migration.source_node)
            mock_save.assert_called_with(expected_task_state=
                                         [None, task_states.DELETING,
                                         task_states.SOFT_DELETING])

        do_confirm_resize()

    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    def test_delete_allocation_after_move_legacy(self, mock_resources):
        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, 'reportclient')
        def do_it(mock_rc, mock_grt):
            instance = mock.MagicMock()
            migration = mock.MagicMock()
            self.compute._delete_allocation_after_move(self.context,
                                                       instance,
                                                       migration,
                                                       mock.sentinel.flavor,
                                                       mock.sentinel.node)
            mock_resources.assert_called_once_with(instance,
                                                   mock.sentinel.flavor)
            rt = mock_grt.return_value
            rt.get_node_uuid.assert_called_once_with(mock.sentinel.node)
            remove = mock_rc.remove_provider_from_instance_allocation
            remove.assert_called_once_with(
                self.context, instance.uuid, rt.get_node_uuid.return_value,
                instance.user_id, instance.project_id,
                mock_resources.return_value)
        do_it()

    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    def test_delete_allocation_after_move_confirm_by_migration(self, mock_rff):
        mock_rff.return_value = {}

        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, 'reportclient')
        def doit(new_rules, mock_report, mock_rt):
            mock_report.delete_allocation_for_instance.return_value = new_rules
            self.migration.source_node = 'src'
            self.migration.uuid = uuids.migration
            self.migration.status = 'confirmed'
            self.compute._delete_allocation_after_move(self.context,
                                                       self.instance,
                                                       self.migration,
                                                       mock.sentinel.flavor,
                                                       'src')
            mock_report.delete_allocation_for_instance.assert_called_once_with(
                self.context, self.migration.uuid)

            old = mock_report.remove_provider_from_instance_allocation
            if new_rules:
                self.assertFalse(old.called)
            else:
                self.assertTrue(old.called)

        # Allocations by migration, no legacy cleanup
        doit(True)

        # No allocations by migration, legacy cleanup
        doit(False)

    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    def test_delete_allocation_after_move_fail_by_migration(self, mock_rff):
        mock_rff.return_value = {}

        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, 'reportclient')
        def doit(new_rules, mock_report, mock_rt):
            ga = mock_report.get_allocations_for_consumer_by_provider
            ga.return_value = new_rules
            self.migration.source_node = 'src'
            self.migration.uuid = uuids.migration
            self.migration.status = 'failed'
            self.compute._delete_allocation_after_move(self.context,
                                                       self.instance,
                                                       self.migration,
                                                       mock.sentinel.flavor,
                                                       'src')
            self.assertFalse(mock_report.delete_allocation_for_instance.called)
            ga.assert_called_once_with(
                self.context, mock_rt().get_node_uuid.return_value,
                self.migration.uuid)

            old = mock_report.remove_provider_from_instance_allocation
            if new_rules:
                self.assertFalse(old.called)
            else:
                self.assertTrue(old.called)

        # Allocations by migration, no legacy cleanup
        doit(True)

        # No allocations by migration, legacy cleanup
        doit(False)

    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    def test_delete_allocation_after_move_revert_by_migration(self, mock_rff):
        mock_rff.return_value = {}

        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, 'reportclient')
        def doit(new_rules, mock_report, mock_rt):
            a = new_rules and {'allocations': 'fake'} or {}
            ga = mock_report.get_allocations_for_consumer_by_provider
            ga.return_value = a
            self.migration.source_node = 'src'
            self.migration.dest_node = 'dst'
            self.migration.uuid = uuids.migration
            self.compute._delete_allocation_after_move(self.context,
                                                       self.instance,
                                                       self.migration,
                                                       mock.sentinel.flavor,
                                                       'dst')
            self.assertFalse(mock_report.delete_allocation_for_instance.called)
            cn_uuid = mock_rt().get_node_uuid.return_value
            ga.assert_called_once_with(self.context, cn_uuid,
                                       self.migration.uuid)

            old = mock_report.remove_provider_from_instance_allocation
            if new_rules:
                self.assertFalse(old.called)
            else:
                self.assertTrue(old.called)

        # Allocations by migration, no legacy cleanup
        doit(True)

        # No allocations by migration, legacy cleanup
        doit(False)

    def test_revert_allocation(self):
        """New-style migration-based allocation revert."""

        @mock.patch.object(self.compute, '_get_resource_tracker')
        @mock.patch.object(self.compute, 'reportclient')
        def doit(mock_report, mock_rt):
            cu = uuids.node
            mock_rt.return_value.compute_nodes[self.instance.node].uuid = cu
            a = {cu: {'resources': {'DISK_GB': 1}}}
            mock_report.get_allocations_for_consumer.return_value = a
            self.migration.uuid = uuids.migration

            r = self.compute._revert_allocation(mock.sentinel.ctx,
                                                self.instance, self.migration)

            self.assertTrue(r)
            mock_report.set_and_clear_allocations.assert_called_once_with(
                mock.sentinel.ctx, cu, self.instance.uuid, {'DISK_GB': 1},
                self.instance.project_id, self.instance.user_id,
                consumer_to_clear=self.migration.uuid)

        doit()

    def test_revert_allocation_old_style(self):
        """Test that we don't delete allocs for migration if none found."""

        @mock.patch.object(self.compute, 'reportclient')
        def doit(mock_report):
            mock_report.get_allocations_for_consumer.return_value = {}
            self.migration.uuid = uuids.migration

            r = self.compute._revert_allocation(mock.sentinel.ctx,
                                                self.instance, self.migration)

            self.assertFalse(r)
            self.assertFalse(mock_report.set_and_clear_allocations.called)

        doit()

    def test_revert_allocation_new_style_unpossible(self):
        """Test for the should-not-be-possible case of multiple old allocs.

        This should not be a thing that can happen, but just verify that
        we fall through and guess at one of them. There's not really much else
        we can do.
        """

        @mock.patch.object(self.compute, 'reportclient')
        def doit(mock_report):
            a = {
                uuids.node: {'resources': {'DISK_GB': 1}},
                uuids.edon: {'resources': {'DISK_GB': 1}},
            }
            mock_report.get_allocations_for_consumer.return_value = a
            self.migration.uuid = uuids.migration

            r = self.compute._revert_allocation(mock.sentinel.ctx,
                                                self.instance, self.migration)

            self.assertTrue(r)
            self.assertTrue(mock_report.set_and_clear_allocations.called)

        doit()

    def test_consoles_enabled(self):
        self.flags(enabled=False, group='vnc')
        self.flags(enabled=False, group='spice')
        self.flags(enabled=False, group='rdp')
        self.flags(enabled=False, group='serial_console')
        self.assertFalse(self.compute._consoles_enabled())

        self.flags(enabled=True, group='vnc')
        self.assertTrue(self.compute._consoles_enabled())
        self.flags(enabled=False, group='vnc')

        for console in ['spice', 'rdp', 'serial_console']:
            self.flags(enabled=True, group=console)
            self.assertTrue(self.compute._consoles_enabled())
            self.flags(enabled=False, group=console)

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_do_live_migration')
    def _test_max_concurrent_live(self, mock_lm):

        @mock.patch('nova.objects.Migration.save')
        def _do_it(mock_mig_save):
            instance = objects.Instance(uuid=uuids.fake)
            migration = objects.Migration()
            self.compute.live_migration(self.context,
                                        mock.sentinel.dest,
                                        instance,
                                        mock.sentinel.block_migration,
                                        migration,
                                        mock.sentinel.migrate_data)
            self.assertEqual('queued', migration.status)
            migration.save.assert_called_once_with()

        with mock.patch.object(self.compute,
                               '_live_migration_semaphore') as mock_sem:
            for i in (1, 2, 3):
                _do_it()
        self.assertEqual(3, mock_sem.__enter__.call_count)

    def test_max_concurrent_live_limited(self):
        self.flags(max_concurrent_live_migrations=2)
        self._test_max_concurrent_live()

    def test_max_concurrent_live_unlimited(self):
        self.flags(max_concurrent_live_migrations=0)
        self._test_max_concurrent_live()

    def test_max_concurrent_live_semaphore_limited(self):
        self.flags(max_concurrent_live_migrations=123)
        self.assertEqual(
            123,
            manager.ComputeManager()._live_migration_semaphore.balance)

    def test_max_concurrent_live_semaphore_unlimited(self):
        self.flags(max_concurrent_live_migrations=0)
        compute = manager.ComputeManager()
        self.assertEqual(0, compute._live_migration_semaphore.balance)
        self.assertIsInstance(compute._live_migration_semaphore,
                              compute_utils.UnlimitedSemaphore)

    def test_max_concurrent_live_semaphore_negative(self):
        self.flags(max_concurrent_live_migrations=-2)
        compute = manager.ComputeManager()
        self.assertEqual(0, compute._live_migration_semaphore.balance)
        self.assertIsInstance(compute._live_migration_semaphore,
                              compute_utils.UnlimitedSemaphore)

    def test_check_migrate_source_converts_object(self):
        # NOTE(danms): Make sure that we legacy-ify any data objects
        # the drivers give us back, if we were passed a non-object
        data = migrate_data_obj.LiveMigrateData(is_volume_backed=False)
        compute = manager._ComputeV4Proxy(mock.MagicMock())
        compute.manager.check_can_live_migrate_source.return_value = data
        self.assertIsInstance(
            compute.check_can_live_migrate_source(
                self.context, objects.Instance(uuid=uuids.instance), {}),
            dict)
        mgr = compute.manager
        self.assertIsInstance(
            mgr.check_can_live_migrate_source.call_args_list[0][0][2],
            migrate_data_obj.LiveMigrateData)

    def test_pre_live_migration_handles_dict(self):
        compute = manager._ComputeV4Proxy(mock.MagicMock())

        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        migrate_data = migrate_data_obj.LiveMigrateData()
        compute.manager.pre_live_migration.return_value = migrate_data
        r = compute.pre_live_migration(self.context, instance,
                                       False, {}, {})
        self.assertIsInstance(r, dict)
        self.assertIsInstance(
            compute.manager.pre_live_migration.call_args_list[0][0][4],
            migrate_data_obj.LiveMigrateData)

    def test_live_migration_handles_dict(self):
        compute = manager._ComputeV4Proxy(mock.MagicMock())

        migrate_data = migrate_data_obj.LiveMigrateData()
        migration = objects.Migration()
        migration.save = mock.MagicMock()
        compute.manager.compute_rpcapi.pre_live_migration.return_value = (
            migrate_data)
        compute.live_migration(self.context, 'foo', {'uuid': 'foo'},
                               False, migration, {})
        self.assertIsInstance(
            compute.manager.live_migration.call_args_list[0][0][5],
            migrate_data_obj.LiveMigrateData)

    def test_pre_live_migration_cinder_v3_api(self):
        # This tests that pre_live_migration with a bdm with an
        # attachment_id, will create a new attachment and update
        # attachment_id's in the bdm.
        compute = manager.ComputeManager()

        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        volume_id = uuids.volume
        vol_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})

        # attach_create should not be called on this
        image_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'image', 'destination_type': 'local',
             'volume_id': volume_id, 'device_name': '/dev/vda',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})

        orig_attachment_id = uuids.attachment1
        vol_bdm.attachment_id = orig_attachment_id
        new_attachment_id = uuids.attachment2
        image_bdm.attachment_id = uuids.attachment3

        migrate_data = migrate_data_obj.LiveMigrateData()
        migrate_data.old_vol_attachment_ids = {}

        @mock.patch.object(compute_utils, 'notify_about_instance_action')
        @mock.patch.object(compute.volume_api, 'attachment_complete')
        @mock.patch.object(vol_bdm, 'save')
        @mock.patch.object(compute, '_notify_about_instance_usage')
        @mock.patch.object(compute, 'network_api')
        @mock.patch.object(compute.driver, 'pre_live_migration')
        @mock.patch.object(compute, '_get_instance_block_device_info')
        @mock.patch.object(compute_utils, 'is_volume_backed_instance')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        @mock.patch.object(compute.volume_api, 'attachment_create')
        def _test(mock_attach, mock_get_bdms, mock_ivbi,
                  mock_gibdi, mock_plm, mock_nwapi, mock_notify,
                  mock_bdm_save, mock_attach_complete, mock_notify_about_inst):

            mock_get_bdms.return_value = [vol_bdm, image_bdm]
            mock_attach.return_value = {'id': new_attachment_id}
            mock_plm.return_value = migrate_data
            connector = compute.driver.get_volume_connector(instance)

            r = compute.pre_live_migration(self.context, instance,
                                           False, {}, migrate_data)

            mock_notify_about_inst.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                          action='live_migration_pre', phase='start',
                          bdms=mock_get_bdms.return_value),
                mock.call(self.context, instance, 'fake-mini',
                          action='live_migration_pre', phase='end',
                          bdms=mock_get_bdms.return_value)])
            self.assertIsInstance(r, migrate_data_obj.LiveMigrateData)
            self.assertIsInstance(mock_plm.call_args_list[0][0][5],
                                  migrate_data_obj.LiveMigrateData)
            mock_attach.assert_called_once_with(
                self.context, volume_id, instance.uuid, connector=connector,
                mountpoint=vol_bdm.device_name)
            self.assertEqual(vol_bdm.attachment_id, new_attachment_id)
            self.assertEqual(migrate_data.old_vol_attachment_ids[volume_id],
                             orig_attachment_id)
            mock_bdm_save.assert_called_once_with()
            mock_attach_complete.assert_called_once_with(self.context,
                                                         new_attachment_id)

        _test()

    def test_pre_live_migration_exception_cinder_v3_api(self):
        # The instance in this test has 2 attachments. The second attach_create
        # will throw an exception. This will test that the first attachment
        # is restored after the exception is thrown.
        compute = manager.ComputeManager()

        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        volume1_id = uuids.volume1
        vol1_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume1_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})
        vol1_orig_attachment_id = uuids.attachment1
        vol1_bdm.attachment_id = vol1_orig_attachment_id

        volume2_id = uuids.volume2
        vol2_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume2_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})
        vol2_orig_attachment_id = uuids.attachment2
        vol2_bdm.attachment_id = vol2_orig_attachment_id

        migrate_data = migrate_data_obj.LiveMigrateData()
        migrate_data.old_vol_attachment_ids = {}

        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(vol1_bdm, 'save')
        @mock.patch.object(compute, '_notify_about_instance_usage')
        @mock.patch('nova.compute.utils.notify_about_instance_action')
        @mock.patch.object(compute, 'network_api')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        @mock.patch.object(compute.volume_api, 'attachment_delete')
        @mock.patch.object(compute.volume_api, 'attachment_create')
        def _test(mock_attach_create, mock_attach_delete, mock_get_bdms,
                  mock_nwapi, mock_ver_notify, mock_notify, mock_bdm_save,
                  mock_exception):
            new_attachment_id = uuids.attachment3
            mock_attach_create.side_effect = [{'id': new_attachment_id},
                                              test.TestingException]
            mock_get_bdms.return_value = [vol1_bdm, vol2_bdm]

            self.assertRaises(test.TestingException,
                              compute.pre_live_migration,
                              self.context, instance, False, {}, migrate_data)

            self.assertEqual(vol1_orig_attachment_id, vol1_bdm.attachment_id)
            self.assertEqual(vol2_orig_attachment_id, vol2_bdm.attachment_id)
            self.assertEqual(mock_attach_create.call_count, 2)
            mock_attach_delete.assert_called_once_with(self.context,
                                                       new_attachment_id)

            # Meta: ensure un-asserted mocks are still required
            for m in (mock_nwapi, mock_get_bdms, mock_ver_notify, mock_notify,
                      mock_bdm_save, mock_exception):
                # NOTE(artom) This is different from assert_called() because
                # mock_calls contains the calls to a mock's method as well
                # (which is what we want for network_api.get_instance_nw_info
                # for example), whereas assert_called() only asserts
                # calls to the mock itself.
                self.assertGreater(len(m.mock_calls), 0)
        _test()

    def test_pre_live_migration_exceptions_delete_attachments(self):
        # The instance in this test has 2 attachments. The call to
        # driver.pre_live_migration will raise an exception. This will test
        # that the attachments are restored after the exception is thrown.
        compute = manager.ComputeManager()

        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        vol1_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': uuids.vol1, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})
        vol1_bdm.attachment_id = uuids.vol1_attach_orig

        vol2_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': uuids.vol2, 'device_name': '/dev/vdc',
             'instance_uuid': instance.uuid,
             'connection_info': '{"test": "test"}'})
        vol2_bdm.attachment_id = uuids.vol2_attach_orig

        migrate_data = migrate_data_obj.LiveMigrateData()
        migrate_data.old_vol_attachment_ids = {}

        @mock.patch.object(manager, 'compute_utils', autospec=True)
        @mock.patch.object(compute, 'network_api', autospec=True)
        @mock.patch.object(compute, 'volume_api', autospec=True)
        @mock.patch.object(objects.BlockDeviceMapping, 'save')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        @mock.patch.object(compute.driver, 'pre_live_migration', autospec=True)
        def _test(mock_plm, mock_bdms_get, mock_bdm_save, mock_vol_api,
                  mock_net_api, mock_compute_utils):
            mock_vol_api.attachment_create.side_effect = [
                    {'id': uuids.vol1_attach_new},
                    {'id': uuids.vol2_attach_new}]
            mock_bdms_get.return_value = [vol1_bdm, vol2_bdm]
            mock_plm.side_effect = test.TestingException

            self.assertRaises(test.TestingException,
                              compute.pre_live_migration,
                              self.context, instance, False, {}, migrate_data)

            self.assertEqual(2, mock_vol_api.attachment_create.call_count)

            # Assert BDMs have original attachments restored
            self.assertEqual(uuids.vol1_attach_orig, vol1_bdm.attachment_id)
            self.assertEqual(uuids.vol2_attach_orig, vol2_bdm.attachment_id)

            # Assert attachment cleanup
            self.assertEqual(2, mock_vol_api.attachment_delete.call_count)
            mock_vol_api.attachment_delete.assert_has_calls(
                    [mock.call(self.context, uuids.vol1_attach_new),
                     mock.call(self.context, uuids.vol2_attach_new)],
                    any_order=True)

            # Meta: ensure un-asserted mocks are still required
            for m in (mock_net_api, mock_compute_utils):
                self.assertGreater(len(m.mock_calls), 0)
        _test()

    def test_get_neutron_events_for_live_migration_empty(self):
        """Tests the various ways that _get_neutron_events_for_live_migration
        will return an empty list.
        """
        nw = network_model.NetworkInfo([network_model.VIF(uuids.port1)])
        # 1. no timeout
        self.flags(vif_plugging_timeout=0)
        self.assertEqual(
            [], self.compute._get_neutron_events_for_live_migration(nw))
        # 2. not neutron
        self.flags(vif_plugging_timeout=300, use_neutron=False)
        self.assertEqual(
            [], self.compute._get_neutron_events_for_live_migration(nw))
        # 3. no VIFs
        self.flags(vif_plugging_timeout=300, use_neutron=True)
        self.assertEqual(
            [], self.compute._get_neutron_events_for_live_migration([]))

    @mock.patch('nova.compute.rpcapi.ComputeAPI.pre_live_migration')
    @mock.patch('nova.compute.manager.ComputeManager._post_live_migration')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    def test_live_migration_wait_vif_plugged(
            self, mock_get_bdms, mock_post_live_mig, mock_pre_live_mig):
        """Tests the happy path of waiting for network-vif-plugged events from
        neutron when so configured.
        """
        self.flags(live_migration_wait_for_vif_plug=True, group='compute')
        migrate_data = objects.LibvirtLiveMigrateData(
            wait_for_vif_plugged=True)
        mock_get_bdms.return_value = objects.BlockDeviceMappingList(objects=[])
        mock_pre_live_mig.return_value = migrate_data
        self.instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([
                network_model.VIF(uuids.port1), network_model.VIF(uuids.port2)
            ]))
        with mock.patch.object(self.compute.virtapi,
                               'wait_for_instance_event') as wait_for_event:
            self.compute._do_live_migration(
                self.context, 'dest-host', self.instance, None, self.migration,
                migrate_data)
        self.assertEqual(2, len(wait_for_event.call_args[0][1]))
        self.assertEqual(CONF.vif_plugging_timeout,
                         wait_for_event.call_args[1]['deadline'])
        mock_pre_live_mig.assert_called_once_with(
            self.context, self.instance, None, None, 'dest-host',
            migrate_data)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.pre_live_migration')
    @mock.patch('nova.compute.manager.ComputeManager._rollback_live_migration')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    def test_live_migration_wait_vif_plugged_vif_plug_error(
            self, mock_get_bdms, mock_rollback_live_mig, mock_pre_live_mig):
        """Tests the scenario where wait_for_instance_event fails with
        VirtualInterfacePlugException.
        """
        self.flags(live_migration_wait_for_vif_plug=True, group='compute')
        migrate_data = objects.LibvirtLiveMigrateData(
            wait_for_vif_plugged=True)
        mock_get_bdms.return_value = objects.BlockDeviceMappingList(objects=[])
        mock_pre_live_mig.return_value = migrate_data
        self.instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([
                network_model.VIF(uuids.port1)]))
        with mock.patch.object(
                self.compute.virtapi,
                'wait_for_instance_event') as wait_for_event:
            wait_for_event.return_value.__enter__.side_effect = (
                exception.VirtualInterfacePlugException())
            self.assertRaises(
                exception.VirtualInterfacePlugException,
                self.compute._do_live_migration, self.context, 'dest-host',
                self.instance, None, self.migration, migrate_data)
        self.assertEqual('error', self.migration.status)
        mock_rollback_live_mig.assert_called_once_with(
            self.context, self.instance, 'dest-host', migrate_data)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.pre_live_migration')
    @mock.patch('nova.compute.manager.ComputeManager._rollback_live_migration')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    def test_live_migration_wait_vif_plugged_timeout_error(
            self, mock_get_bdms, mock_rollback_live_mig, mock_pre_live_mig):
        """Tests the scenario where wait_for_instance_event raises an
        eventlet Timeout exception and we're configured such that vif plugging
        failures are fatal (which is the default).
        """
        self.flags(live_migration_wait_for_vif_plug=True, group='compute')
        migrate_data = objects.LibvirtLiveMigrateData(
            wait_for_vif_plugged=True)
        mock_get_bdms.return_value = objects.BlockDeviceMappingList(objects=[])
        mock_pre_live_mig.return_value = migrate_data
        self.instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([
                network_model.VIF(uuids.port1)]))
        with mock.patch.object(
                self.compute.virtapi,
                'wait_for_instance_event') as wait_for_event:
            wait_for_event.return_value.__enter__.side_effect = (
                eventlet_timeout.Timeout())
            ex = self.assertRaises(
                exception.MigrationError, self.compute._do_live_migration,
                self.context, 'dest-host', self.instance, None,
                self.migration, migrate_data)
            self.assertIn('Timed out waiting for events', six.text_type(ex))
        self.assertEqual('error', self.migration.status)
        mock_rollback_live_mig.assert_called_once_with(
            self.context, self.instance, 'dest-host', migrate_data)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.pre_live_migration')
    @mock.patch('nova.compute.manager.ComputeManager._rollback_live_migration')
    @mock.patch('nova.compute.manager.ComputeManager._post_live_migration')
    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    def test_live_migration_wait_vif_plugged_timeout_non_fatal(
            self, mock_get_bdms, mock_post_live_mig, mock_rollback_live_mig,
            mock_pre_live_mig):
        """Tests the scenario where wait_for_instance_event raises an
        eventlet Timeout exception and we're configured such that vif plugging
        failures are NOT fatal.
        """
        self.flags(live_migration_wait_for_vif_plug=True, group='compute')
        self.flags(vif_plugging_is_fatal=False)
        mock_get_bdms.return_value = objects.BlockDeviceMappingList(objects=[])
        migrate_data = objects.LibvirtLiveMigrateData(
            wait_for_vif_plugged=True)
        mock_pre_live_mig.return_value = migrate_data
        self.instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([
                network_model.VIF(uuids.port1)]))
        with mock.patch.object(
                self.compute.virtapi,
                'wait_for_instance_event') as wait_for_event:
            wait_for_event.return_value.__enter__.side_effect = (
                eventlet_timeout.Timeout())
            self.compute._do_live_migration(
                self.context, 'dest-host', self.instance, None,
                self.migration, migrate_data)
        self.assertEqual('running', self.migration.status)
        mock_rollback_live_mig.assert_not_called()

    def test_live_migration_force_complete_succeeded(self):
        migration = objects.Migration()
        migration.status = 'running'
        migration.id = 0

        @mock.patch('nova.image.api.API.generate_image_url',
                    return_value='fake-url')
        @mock.patch.object(objects.Migration, 'get_by_id',
                           return_value=migration)
        @mock.patch.object(self.compute.driver,
                           'live_migration_force_complete')
        def _do_test(force_complete, get_by_id, gen_img_url):
            self.compute.live_migration_force_complete(
                self.context, self.instance)

            force_complete.assert_called_once_with(self.instance)

            self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
            self.assertEqual(
                'compute.instance.live.migration.force.complete.start',
                fake_notifier.NOTIFICATIONS[0].event_type)
            self.assertEqual(
                self.instance.uuid,
                fake_notifier.NOTIFICATIONS[0].payload['instance_id'])
            self.assertEqual(
                'compute.instance.live.migration.force.complete.end',
                fake_notifier.NOTIFICATIONS[1].event_type)
            self.assertEqual(
                self.instance.uuid,
                fake_notifier.NOTIFICATIONS[1].payload['instance_id'])

        _do_test()

    def test_post_live_migration_at_destination_success(self):

        @mock.patch.object(self.instance, 'save')
        @mock.patch.object(self.compute.network_api, 'get_instance_nw_info',
                           return_value='test_network')
        @mock.patch.object(self.compute.network_api, 'setup_networks_on_host')
        @mock.patch.object(self.compute.network_api, 'migrate_instance_finish')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, '_get_instance_block_device_info')
        @mock.patch.object(self.compute, '_get_power_state', return_value=1)
        @mock.patch.object(self.compute, '_get_compute_info')
        @mock.patch.object(self.compute.driver,
                           'post_live_migration_at_destination')
        def _do_test(post_live_migration_at_destination, _get_compute_info,
                     _get_power_state, _get_instance_block_device_info,
                     _notify_about_instance_usage, migrate_instance_finish,
                     setup_networks_on_host, get_instance_nw_info, save):

            cn = mock.Mock(spec_set=['hypervisor_hostname'])
            cn.hypervisor_hostname = 'test_host'
            _get_compute_info.return_value = cn
            cn_old = self.instance.host
            instance_old = self.instance

            self.compute.post_live_migration_at_destination(
                self.context, self.instance, False)

            setup_networks_calls = [
                mock.call(self.context, self.instance, self.compute.host),
                mock.call(self.context, self.instance, cn_old, teardown=True),
                mock.call(self.context, self.instance, self.compute.host)
            ]
            setup_networks_on_host.assert_has_calls(setup_networks_calls)

            notify_usage_calls = [
                mock.call(self.context, instance_old,
                          "live_migration.post.dest.start",
                          network_info='test_network'),
                mock.call(self.context, self.instance,
                          "live_migration.post.dest.end",
                          network_info='test_network')
            ]
            _notify_about_instance_usage.assert_has_calls(notify_usage_calls)

            migrate_instance_finish.assert_called_once_with(
                self.context, self.instance,
                {'source_compute': cn_old,
                 'dest_compute': self.compute.host})
            _get_instance_block_device_info.assert_called_once_with(
                self.context, self.instance
            )
            get_instance_nw_info.assert_called_once_with(self.context,
                                                         self.instance)
            _get_power_state.assert_called_once_with(self.context,
                                                     self.instance)
            _get_compute_info.assert_called_once_with(self.context,
                                                      self.compute.host)

            self.assertEqual(self.compute.host, self.instance.host)
            self.assertEqual('test_host', self.instance.node)
            self.assertEqual(1, self.instance.power_state)
            self.assertEqual(0, self.instance.progress)
            self.assertIsNone(self.instance.task_state)
            save.assert_called_once_with(
                expected_task_state=task_states.MIGRATING)

        _do_test()

    def test_post_live_migration_at_destination_compute_not_found(self):

        @mock.patch.object(self.instance, 'save')
        @mock.patch.object(self.compute, 'network_api')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, '_get_instance_block_device_info')
        @mock.patch.object(self.compute, '_get_power_state', return_value=1)
        @mock.patch.object(self.compute, '_get_compute_info',
                           side_effect=exception.ComputeHostNotFound(
                               host=uuids.fake_host))
        @mock.patch.object(self.compute.driver,
                           'post_live_migration_at_destination')
        def _do_test(post_live_migration_at_destination, _get_compute_info,
                     _get_power_state, _get_instance_block_device_info,
                     _notify_about_instance_usage, network_api, save):
            cn = mock.Mock(spec_set=['hypervisor_hostname'])
            cn.hypervisor_hostname = 'test_host'
            _get_compute_info.return_value = cn

            self.compute.post_live_migration_at_destination(
                self.context, self.instance, False)
            self.assertIsNone(self.instance.node)

        _do_test()

    def test_post_live_migration_at_destination_unexpected_exception(self):

        @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
        @mock.patch.object(self.instance, 'save')
        @mock.patch.object(self.compute, 'network_api')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, '_get_instance_block_device_info')
        @mock.patch.object(self.compute, '_get_power_state', return_value=1)
        @mock.patch.object(self.compute, '_get_compute_info')
        @mock.patch.object(self.compute.driver,
                           'post_live_migration_at_destination',
                           side_effect=exception.NovaException)
        def _do_test(post_live_migration_at_destination, _get_compute_info,
                     _get_power_state, _get_instance_block_device_info,
                     _notify_about_instance_usage, network_api, save,
                     add_instance_fault_from_exc):
            cn = mock.Mock(spec_set=['hypervisor_hostname'])
            cn.hypervisor_hostname = 'test_host'
            _get_compute_info.return_value = cn

            self.assertRaises(exception.NovaException,
                              self.compute.post_live_migration_at_destination,
                              self.context, self.instance, False)
            self.assertEqual(vm_states.ERROR, self.instance.vm_state)

        _do_test()

    def _call_post_live_migration(self, *args, **kwargs):
        @mock.patch.object(self.compute, 'update_available_resource')
        @mock.patch.object(self.compute, 'compute_rpcapi')
        @mock.patch.object(self.compute, '_notify_about_instance_usage')
        @mock.patch.object(self.compute, 'network_api')
        def _do_call(nwapi, notify, rpc, update):
            bdms = objects.BlockDeviceMappingList(objects=[])
            return self.compute._post_live_migration(self.context,
                                                     self.instance,
                                                     'foo',
                                                     *args, source_bdms=bdms,
                                                     **kwargs)
        return _do_call()

    def test_post_live_migration_new_allocations(self):
        # We have a migrate_data with a migration...
        migration = objects.Migration(uuid=uuids.migration)
        migration.save = mock.MagicMock()
        md = objects.LibvirtLiveMigrateData(migration=migration,
                                            is_shared_instance_path=False,
                                            is_shared_block_storage=False)
        with test.nested(
                mock.patch.object(self.compute.scheduler_client,
                                  'reportclient'),
                mock.patch.object(self.compute,
                                  '_delete_allocation_after_move'),
        ) as (
            mock_report, mock_delete,
        ):
            # ...and that migration has allocations...
            mock_report.get_allocations_for_consumer.return_value = (
                mock.sentinel.allocs)
            self._call_post_live_migration(migrate_data=md)
            # ...so we should have called the new style delete
            mock_delete.assert_called_once_with(self.context,
                                                self.instance,
                                                migration,
                                                self.instance.flavor,
                                                self.instance.node)

    def test_post_live_migration_old_allocations(self):
        # We have a migrate_data with a migration...
        migration = objects.Migration(uuid=uuids.migration)
        migration.save = mock.MagicMock()
        md = objects.LibvirtLiveMigrateData(migration=migration,
                                            is_shared_instance_path=False,
                                            is_shared_block_storage=False)
        with test.nested(
                mock.patch.object(self.compute.scheduler_client,
                                  'reportclient'),
                mock.patch.object(self.compute,
                                  '_delete_allocation_after_move'),
                mock.patch.object(self.compute,
                                  '_get_resource_tracker'),
        ) as (
            mock_report, mock_delete, mock_rt,
        ):
            # ...and that migration does not have allocations...
            mock_report.get_allocations_for_consumer.return_value = None
            self._call_post_live_migration(migrate_data=md)
            # ...so we should have called the old style delete
            mock_delete.assert_not_called()
            fn = mock_rt.return_value.delete_allocation_for_migrated_instance
            fn.assert_called_once_with(self.context, self.instance,
                                       self.instance.node)

    def test_post_live_migration_legacy(self):
        # We have no migrate_data...
        md = None
        with test.nested(
                mock.patch.object(self.compute.scheduler_client,
                                  'reportclient'),
                mock.patch.object(self.compute,
                                  '_delete_allocation_after_move'),
                mock.patch.object(self.compute,
                                  '_get_resource_tracker'),
        ) as (
            mock_report, mock_delete, mock_rt,
        ):
            self._call_post_live_migration(migrate_data=md)
            # ...without migrate_data, no migration allocations check...
            ga = mock_report.get_allocations_for_consumer
            self.assertFalse(ga.called)
            # ...so we should have called the old style delete
            mock_delete.assert_not_called()
            fn = mock_rt.return_value.delete_allocation_for_migrated_instance
            fn.assert_called_once_with(self.context, self.instance,
                                       self.instance.node)

    def test_post_live_migration_cinder_v3_api(self):
        # Because live migration has succeeded, _post_live_migration
        # should call attachment_delete with the original/old attachment_id
        compute = manager.ComputeManager()

        dest_host = 'test_dest_host'
        instance = fake_instance.fake_instance_obj(self.context,
                                                   node='dest',
                                                   uuid=uuids.instance)
        bdm_id = 1
        volume_id = uuids.volume

        vol_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid,
             'id': bdm_id,
             'connection_info':
             '{"connector": {"host": "%s"}}' % dest_host})
        image_bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'image', 'destination_type': 'local',
             'volume_id': volume_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid})
        vol_bdm.attachment_id = uuids.attachment
        migrate_data = migrate_data_obj.LiveMigrateData()
        migrate_data.migration = objects.Migration(uuid=uuids.migration,
                                                   dest_node=instance.node,
                                                   source_node='src')
        image_bdm.attachment_id = uuids.attachment3

        @mock.patch.object(migrate_data.migration, 'save',
                           new=lambda: None)
        @mock.patch.object(compute.reportclient,
                           'get_allocations_for_consumer_by_provider')
        @mock.patch.object(compute, '_get_resource_tracker')
        @mock.patch.object(vol_bdm, 'save')
        @mock.patch.object(compute, 'update_available_resource')
        @mock.patch.object(compute.volume_api, 'attachment_delete')
        @mock.patch.object(compute, '_get_instance_block_device_info')
        @mock.patch.object(compute, 'compute_rpcapi')
        @mock.patch.object(compute, 'driver')
        @mock.patch.object(compute, '_notify_about_instance_usage')
        @mock.patch.object(compute, 'network_api')
        def _test(mock_net_api, mock_notify, mock_driver,
                  mock_rpc, mock_get_bdm_info, mock_attach_delete,
                  mock_update_resource, mock_bdm_save, mock_rt, mock_ga):
            mock_rt.return_value = mock.Mock()
            bdms = objects.BlockDeviceMappingList(objects=[vol_bdm, image_bdm])

            compute._post_live_migration(self.context, instance, dest_host,
                                         migrate_data=migrate_data,
                                         source_bdms=bdms)

            mock_attach_delete.assert_called_once_with(
                self.context, uuids.attachment)

        _test()

    @mock.patch.object(objects.ComputeNode,
                       'get_first_node_by_host_for_old_compat')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'remove_provider_from_instance_allocation')
    def test_rollback_live_migration_cinder_v3_api(self, mock_remove_allocs,
                                                   mock_get_node):
        compute = manager.ComputeManager()
        dest_node = objects.ComputeNode(host='foo', uuid=uuids.dest_node)
        mock_get_node.return_value = dest_node
        instance = fake_instance.fake_instance_obj(self.context,
                                                   uuid=uuids.instance)
        volume_id = uuids.volume
        orig_attachment_id = uuids.attachment1
        new_attachment_id = uuids.attachment2
        migrate_data = migrate_data_obj.LiveMigrateData()
        migrate_data.old_vol_attachment_ids = {
            volume_id: orig_attachment_id}

        bdm = fake_block_device.fake_bdm_object(
            self.context,
            {'source_type': 'volume', 'destination_type': 'volume',
             'volume_id': volume_id, 'device_name': '/dev/vdb',
             'instance_uuid': instance.uuid})
        bdm.attachment_id = new_attachment_id

        @mock.patch.object(compute.volume_api, 'attachment_delete')
        @mock.patch.object(bdm, 'save')
        @mock.patch.object(compute_utils, 'notify_about_instance_action')
        @mock.patch.object(instance, 'save')
        @mock.patch.object(compute, '_notify_about_instance_usage')
        @mock.patch.object(compute.compute_rpcapi, 'remove_volume_connection')
        @mock.patch.object(compute, 'network_api')
        @mock.patch.object(objects.BlockDeviceMappingList,
                           'get_by_instance_uuid')
        def _test(mock_get_bdms, mock_net_api, mock_remove_conn,
                  mock_usage, mock_instance_save, mock_action, mock_save,
                  mock_attach_delete):
            # this tests that _rollback_live_migration replaces the bdm's
            # attachment_id with the original attachment id that is in
            # migrate_data.
            mock_get_bdms.return_value = objects.BlockDeviceMappingList(
                objects=[bdm])

            compute._rollback_live_migration(self.context, instance, None,
                                             migrate_data)

            mock_remove_conn.assert_called_once_with(self.context, instance,
                                                     bdm.volume_id, None)
            mock_attach_delete.called_once_with(self.context,
                                                new_attachment_id)
            self.assertEqual(bdm.attachment_id, orig_attachment_id)
            mock_save.assert_called_once_with()

        _test()

    def _get_migration(self, migration_id, status, migration_type):
        migration = objects.Migration()
        migration.id = migration_id
        migration.status = status
        migration.migration_type = migration_type
        return migration

    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    @mock.patch.object(objects.Migration, 'get_by_id')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'live_migration_abort')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_live_migration_abort(self, mock_notify_action, mock_driver,
                                   mock_get_migration, mock_notify):
        instance = objects.Instance(id=123, uuid=uuids.instance)
        migration = self._get_migration(10, 'running', 'live-migration')
        mock_get_migration.return_value = migration
        self.compute.live_migration_abort(self.context, instance, migration.id)
        mock_driver.assert_called_with(instance)
        mock_notify.assert_has_calls(
            [mock.call(self.context, instance,
                       'live.migration.abort.start'),
             mock.call(self.context, instance,
                       'live.migration.abort.end')]
        )
        mock_notify_action.assert_has_calls(
            [mock.call(self.context, instance, 'fake-mini',
                    action='live_migration_abort', phase='start'),
             mock.call(self.context, instance, 'fake-mini',
                    action='live_migration_abort', phase='end')]
        )

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(manager.ComputeManager, '_notify_about_instance_usage')
    @mock.patch.object(objects.Migration, 'get_by_id')
    @mock.patch.object(nova.virt.fake.SmallFakeDriver, 'live_migration_abort')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_live_migration_abort_not_supported(self, mock_notify_action,
                                                mock_driver,
                                                mock_get_migration,
                                                mock_notify,
                                                mock_instance_fault):
        instance = objects.Instance(id=123, uuid=uuids.instance)
        migration = self._get_migration(10, 'running', 'live-migration')
        mock_get_migration.return_value = migration
        mock_driver.side_effect = NotImplementedError()
        self.assertRaises(NotImplementedError,
                          self.compute.live_migration_abort,
                          self.context,
                          instance,
                          migration.id)
        mock_notify_action.assert_called_once_with(self.context, instance,
            'fake-mini', action='live_migration_abort', phase='start')

    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(objects.Migration, 'get_by_id')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_live_migration_abort_wrong_migration_state(self,
                                                        mock_notify_action,
                                                        mock_get_migration,
                                                        mock_instance_fault):
        instance = objects.Instance(id=123, uuid=uuids.instance)
        migration = self._get_migration(10, 'completed', 'live-migration')
        mock_get_migration.return_value = migration
        self.assertRaises(exception.InvalidMigrationState,
                          self.compute.live_migration_abort,
                          self.context,
                          instance,
                          migration.id)
        mock_notify_action.assert_not_called()

    def test_live_migration_cleanup_flags_block_migrate_libvirt(self):
        migrate_data = objects.LibvirtLiveMigrateData(
            is_shared_block_storage=False,
            is_shared_instance_path=False)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertTrue(do_cleanup)
        self.assertTrue(destroy_disks)

    def test_live_migration_cleanup_flags_shared_block_libvirt(self):
        migrate_data = objects.LibvirtLiveMigrateData(
            is_shared_block_storage=True,
            is_shared_instance_path=False)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertTrue(do_cleanup)
        self.assertFalse(destroy_disks)

    def test_live_migration_cleanup_flags_shared_path_libvirt(self):
        migrate_data = objects.LibvirtLiveMigrateData(
            is_shared_block_storage=False,
            is_shared_instance_path=True)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertFalse(do_cleanup)
        self.assertTrue(destroy_disks)

    def test_live_migration_cleanup_flags_shared_libvirt(self):
        migrate_data = objects.LibvirtLiveMigrateData(
            is_shared_block_storage=True,
            is_shared_instance_path=True)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertFalse(do_cleanup)
        self.assertFalse(destroy_disks)

    def test_live_migration_cleanup_flags_block_migrate_xenapi(self):
        migrate_data = objects.XenapiLiveMigrateData(block_migration=True)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertTrue(do_cleanup)
        self.assertTrue(destroy_disks)

    def test_live_migration_cleanup_flags_live_migrate_xenapi(self):
        migrate_data = objects.XenapiLiveMigrateData(block_migration=False)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertFalse(do_cleanup)
        self.assertFalse(destroy_disks)

    def test_live_migration_cleanup_flags_live_migrate(self):
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            {})
        self.assertFalse(do_cleanup)
        self.assertFalse(destroy_disks)

    def test_live_migration_cleanup_flags_block_migrate_hyperv(self):
        migrate_data = objects.HyperVLiveMigrateData(
            is_shared_instance_path=False)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertTrue(do_cleanup)
        self.assertTrue(destroy_disks)

    def test_live_migration_cleanup_flags_shared_hyperv(self):
        migrate_data = objects.HyperVLiveMigrateData(
            is_shared_instance_path=True)
        do_cleanup, destroy_disks = self.compute._live_migration_cleanup_flags(
            migrate_data)
        self.assertFalse(do_cleanup)
        self.assertFalse(destroy_disks)

    @mock.patch('nova.compute.utils.notify_about_resize_prep_instance')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.InstanceFault.create')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.compute.utils.notify_usage_exists')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                new=lambda *a: False)
    def test_prep_resize_errors_migration(self, mock_niu,
                                          mock_notify, mock_save,
                                          mock_if, mock_cn,
                                          mock_notify_resize):
        migration = mock.MagicMock()
        flavor = objects.Flavor(name='flavor', id=1)
        cn = objects.ComputeNode(uuid=uuids.compute)
        mock_cn.return_value = cn

        @mock.patch.object(self.compute, '_reschedule')
        @mock.patch.object(self.compute, '_prep_resize')
        @mock.patch.object(self.compute, '_get_resource_tracker')
        def doit(mock_grt, mock_pr, mock_r):
            mock_r.return_value = False
            mock_pr.side_effect = test.TestingException

            instance = objects.Instance(uuid=uuids.instance,
                                        host='host',
                                        node='node',
                                        vm_state='active',
                                        task_state=None)

            self.assertRaises(test.TestingException,
                              self.compute.prep_resize,
                              self.context, mock.sentinel.image,
                              instance, flavor,
                              mock.sentinel.request_spec,
                              {}, 'node', False,
                              migration, [])

            # Make sure we set migration status to error
            self.assertEqual(migration.status, 'error')

            # Run it again with migration=None and make sure we don't choke
            self.assertRaises(test.TestingException,
                              self.compute.prep_resize,
                              self.context, mock.sentinel.image,
                              instance, flavor,
                              mock.sentinel.request_spec,
                              {}, 'node', False,
                              None, [])

            # Make sure we only called save once (kinda obviously must be true)
            migration.save.assert_called_once_with()
            mock_notify_resize.assert_has_calls([
                mock.call(self.context, instance, 'fake-mini',
                          'start', flavor),
                mock.call(self.context, instance, 'fake-mini',
                          'end', flavor),
                mock.call(self.context, instance, 'fake-mini',
                          'start', flavor),
                mock.call(self.context, instance, 'fake-mini',
                          'end', flavor)])

        doit()


class ComputeManagerInstanceUsageAuditTestCase(test.TestCase):
    def setUp(self):
        super(ComputeManagerInstanceUsageAuditTestCase, self).setUp()
        self.flags(group='glance', api_servers=['http://localhost:9292'])
        self.flags(instance_usage_audit=True)

    @mock.patch('nova.objects.TaskLog')
    def test_deleted_instance(self, mock_task_log):
        mock_task_log.get.return_value = None

        compute = manager.ComputeManager()
        admin_context = context.get_admin_context()

        fake_db_flavor = fake_flavor.fake_db_flavor()
        flavor = objects.Flavor(admin_context, **fake_db_flavor)

        updates = {'host': compute.host, 'flavor': flavor, 'root_gb': 0,
                   'ephemeral_gb': 0}

        # fudge beginning and ending time by a second (backwards and forwards,
        # respectively) so they differ from the instance's launch and
        # termination times when sub-seconds are truncated and fall within the
        # audit period
        one_second = datetime.timedelta(seconds=1)

        begin = timeutils.utcnow() - one_second
        instance = objects.Instance(admin_context, **updates)
        instance.create()
        instance.launched_at = timeutils.utcnow()
        instance.save()
        instance.destroy()
        end = timeutils.utcnow() + one_second

        def fake_last_completed_audit_period():
            return (begin, end)

        self.stub_out('nova.utils.last_completed_audit_period',
                      fake_last_completed_audit_period)

        compute._instance_usage_audit(admin_context)

        self.assertEqual(1, mock_task_log().task_items,
                         'the deleted test instance was not found in the audit'
                         ' period')
        self.assertEqual(0, mock_task_log().errors,
                         'an error was encountered processing the deleted test'
                         ' instance')
