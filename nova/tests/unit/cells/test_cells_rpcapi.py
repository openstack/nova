# Copyright (c) 2012 Rackspace Hosting
# All Rights Reserved.
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
"""
Tests For Cells RPCAPI
"""

import mock
import six

from nova.cells import rpcapi as cells_rpcapi
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids


class CellsAPITestCase(test.NoDBTestCase):
    """Test case for cells.api interfaces."""

    def setUp(self):
        super(CellsAPITestCase, self).setUp()
        self.fake_topic = 'cells'
        self.fake_context = 'fake_context'
        self.flags(enable=True, group='cells')
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _stub_rpc_method(self, rpc_method, result):
        call_info = {}

        orig_prepare = self.cells_rpcapi.client.prepare

        def fake_rpc_prepare(self_rpcclient, **kwargs):
            if 'version' in kwargs:
                call_info['version'] = kwargs.pop('version')
            return self.cells_rpcapi.client

        def fake_csv(self, version):
            return orig_prepare(version).can_send_version()

        def fake_rpc_method(self, ctxt, method, **kwargs):
            call_info['context'] = ctxt
            call_info['method'] = method
            call_info['args'] = kwargs
            return result

        self.stub_out('oslo_messaging.rpc.client.RPCClient.prepare',
                      fake_rpc_prepare)
        self.stub_out('oslo_messaging.rpc.client.RPCClient.can_send_version',
                      fake_csv)
        self.stub_out('oslo_messaging.rpc.client.RPCClient.%s' % rpc_method,
                      fake_rpc_method)

        return call_info

    def _check_result(self, call_info, method, args, version=None):
        self.assertEqual(self.fake_topic,
                         self.cells_rpcapi.client.target.topic)
        self.assertEqual(self.fake_context, call_info['context'])
        self.assertEqual(method, call_info['method'])
        self.assertEqual(args, call_info['args'])
        if version is not None:
            self.assertIn('version', call_info)
            self.assertIsInstance(call_info['version'], six.string_types,
                                  msg="Message version %s is not a string" %
                                  call_info['version'])
            self.assertEqual(version, call_info['version'])
        else:
            self.assertNotIn('version', call_info)

    def test_cast_compute_api_method(self):
        fake_cell_name = 'fake_cell_name'
        fake_method = 'fake_method'
        fake_method_args = (1, 2)
        fake_method_kwargs = {'kwarg1': 10, 'kwarg2': 20}

        expected_method_info = {'method': fake_method,
                                'method_args': fake_method_args,
                                'method_kwargs': fake_method_kwargs}
        expected_args = {'method_info': expected_method_info,
                         'cell_name': fake_cell_name,
                         'call': False}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.cast_compute_api_method(self.fake_context,
                fake_cell_name, fake_method,
                *fake_method_args, **fake_method_kwargs)
        self._check_result(call_info, 'run_compute_api_method',
                expected_args)

    def test_call_compute_api_method(self):
        fake_cell_name = 'fake_cell_name'
        fake_method = 'fake_method'
        fake_method_args = (1, 2)
        fake_method_kwargs = {'kwarg1': 10, 'kwarg2': 20}
        fake_response = 'fake_response'

        expected_method_info = {'method': fake_method,
                                'method_args': fake_method_args,
                                'method_kwargs': fake_method_kwargs}
        expected_args = {'method_info': expected_method_info,
                         'cell_name': fake_cell_name,
                         'call': True}

        call_info = self._stub_rpc_method('call', fake_response)

        result = self.cells_rpcapi.call_compute_api_method(self.fake_context,
                fake_cell_name, fake_method,
                *fake_method_args, **fake_method_kwargs)
        self._check_result(call_info, 'run_compute_api_method',
                expected_args)
        self.assertEqual(fake_response, result)

    def test_build_instances(self):
        call_info = self._stub_rpc_method('cast', None)

        instances = [objects.Instance(id=1),
                     objects.Instance(id=2)]

        self.cells_rpcapi.build_instances(
                self.fake_context, instances=instances,
                image={'fake': 'image'}, arg1=1, arg2=2, arg3=3)

        expected_args = {'build_inst_kwargs': {'instances': instances,
                                               'image': {'fake': 'image'},
                                               'arg1': 1,
                                               'arg2': 2,
                                               'arg3': 3}}
        self._check_result(call_info, 'build_instances',
                expected_args, version='1.34')

    def test_get_capacities(self):
        capacity_info = {"capacity": "info"}
        call_info = self._stub_rpc_method('call',
                                          result=capacity_info)
        result = self.cells_rpcapi.get_capacities(self.fake_context,
                                                  cell_name="name")
        self._check_result(call_info, 'get_capacities',
                           {'cell_name': 'name'}, version='1.9')
        self.assertEqual(capacity_info, result)

    def test_instance_update_at_top(self):
        fake_info_cache = objects.InstanceInfoCache(
            instance_uuid=uuids.instance)
        fake_sys_metadata = {'key1': 'value1',
                             'key2': 'value2'}
        fake_attrs = {'id': 2,
                      'cell_name': 'fake',
                      'metadata': {'fake': 'fake'},
                      'info_cache': fake_info_cache,
                      'system_metadata': fake_sys_metadata}
        fake_instance = objects.Instance(**fake_attrs)

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_update_at_top(
                self.fake_context, fake_instance)

        expected_args = {'instance': fake_instance}
        self._check_result(call_info, 'instance_update_at_top',
                expected_args, version='1.35')

    def test_instance_destroy_at_top(self):
        fake_instance = objects.Instance(uuid=uuids.instance)

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_destroy_at_top(
                self.fake_context, fake_instance)

        expected_args = {'instance': fake_instance}
        self._check_result(call_info, 'instance_destroy_at_top',
                expected_args, version='1.35')

    def test_instance_delete_everywhere(self):
        instance = fake_instance.fake_instance_obj(self.fake_context)

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_delete_everywhere(
                self.fake_context, instance,
                'fake-type')

        expected_args = {'instance': instance,
                         'delete_type': 'fake-type'}
        self._check_result(call_info, 'instance_delete_everywhere',
                expected_args, version='1.27')

    def test_instance_fault_create_at_top(self):
        fake_instance_fault = {'id': 2,
                               'other': 'meow'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_fault_create_at_top(
                self.fake_context, fake_instance_fault)

        expected_args = {'instance_fault': fake_instance_fault}
        self._check_result(call_info, 'instance_fault_create_at_top',
                expected_args)

    def test_bw_usage_update_at_top(self):
        update_args = ('fake_uuid', 'fake_mac', 'fake_start_period',
                'fake_bw_in', 'fake_bw_out', 'fake_ctr_in',
                'fake_ctr_out')
        update_kwargs = {'last_refreshed': 'fake_refreshed'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.bw_usage_update_at_top(
                self.fake_context, *update_args, **update_kwargs)

        bw_update_info = {'uuid': 'fake_uuid',
                          'mac': 'fake_mac',
                          'start_period': 'fake_start_period',
                          'bw_in': 'fake_bw_in',
                          'bw_out': 'fake_bw_out',
                          'last_ctr_in': 'fake_ctr_in',
                          'last_ctr_out': 'fake_ctr_out',
                          'last_refreshed': 'fake_refreshed'}

        expected_args = {'bw_update_info': bw_update_info}
        self._check_result(call_info, 'bw_usage_update_at_top',
                expected_args)

    def test_get_cell_info_for_neighbors(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.get_cell_info_for_neighbors(
                self.fake_context)
        self._check_result(call_info, 'get_cell_info_for_neighbors', {},
                           version='1.1')
        self.assertEqual('fake_response', result)

    def test_sync_instances(self):
        call_info = self._stub_rpc_method('cast', None)
        self.cells_rpcapi.sync_instances(self.fake_context,
                project_id='fake_project', updated_since='fake_time',
                deleted=True)

        expected_args = {'project_id': 'fake_project',
                         'updated_since': 'fake_time',
                         'deleted': True}
        self._check_result(call_info, 'sync_instances', expected_args,
                           version='1.1')

    def test_service_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        fake_filters = {'key1': 'val1', 'key2': 'val2'}
        result = self.cells_rpcapi.service_get_all(self.fake_context,
                filters=fake_filters)

        expected_args = {'filters': fake_filters}
        self._check_result(call_info, 'service_get_all', expected_args,
                           version='1.2')
        self.assertEqual('fake_response', result)

    def test_service_get_by_compute_host(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.service_get_by_compute_host(
                self.fake_context, host_name='fake-host-name')
        expected_args = {'host_name': 'fake-host-name'}
        self._check_result(call_info, 'service_get_by_compute_host',
                           expected_args,
                           version='1.2')
        self.assertEqual('fake_response', result)

    def test_get_host_uptime(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.get_host_uptime(
            self.fake_context, host_name='fake-host-name')
        expected_args = {'host_name': 'fake-host-name'}
        self._check_result(call_info, 'get_host_uptime',
                           expected_args,
                           version='1.17')
        self.assertEqual('fake_response', result)

    def test_service_update(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.service_update(
            self.fake_context, host_name='fake-host-name',
            binary='nova-api', params_to_update={'disabled': True})
        expected_args = {
            'host_name': 'fake-host-name',
            'binary': 'nova-api',
            'params_to_update': {'disabled': True}}
        self._check_result(call_info, 'service_update',
                           expected_args,
                           version='1.7')
        self.assertEqual('fake_response', result)

    def test_service_delete(self):
        call_info = self._stub_rpc_method('call', None)
        cell_service_id = 'cell@id'
        result = self.cells_rpcapi.service_delete(
            self.fake_context, cell_service_id=cell_service_id)
        expected_args = {'cell_service_id': cell_service_id}
        self._check_result(call_info, 'service_delete',
                           expected_args, version='1.26')
        self.assertIsNone(result)

    def test_proxy_rpc_to_manager(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.proxy_rpc_to_manager(
                self.fake_context, rpc_message='fake-msg',
                topic='fake-topic', call=True)
        expected_args = {'rpc_message': 'fake-msg',
                         'topic': 'fake-topic',
                         'call': True}
        self._check_result(call_info, 'proxy_rpc_to_manager',
                           expected_args,
                           version='1.2')
        self.assertEqual('fake_response', result)

    def test_task_log_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.task_log_get_all(self.fake_context,
                task_name='fake_name',
                period_beginning='fake_begin',
                period_ending='fake_end',
                host='fake_host',
                state='fake_state')

        expected_args = {'task_name': 'fake_name',
                         'period_beginning': 'fake_begin',
                         'period_ending': 'fake_end',
                         'host': 'fake_host',
                         'state': 'fake_state'}
        self._check_result(call_info, 'task_log_get_all', expected_args,
                           version='1.3')
        self.assertEqual('fake_response', result)

    def test_compute_node_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_get_all(self.fake_context,
                hypervisor_match='fake-match')

        expected_args = {'hypervisor_match': 'fake-match'}
        self._check_result(call_info, 'compute_node_get_all', expected_args,
                           version='1.4')
        self.assertEqual('fake_response', result)

    def test_compute_node_stats(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_stats(self.fake_context)
        expected_args = {}
        self._check_result(call_info, 'compute_node_stats',
                           expected_args, version='1.4')
        self.assertEqual('fake_response', result)

    def test_compute_node_get(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_get(self.fake_context,
                'fake_compute_id')
        expected_args = {'compute_id': 'fake_compute_id'}
        self._check_result(call_info, 'compute_node_get',
                           expected_args, version='1.4')
        self.assertEqual('fake_response', result)

    def test_compute_node_get_too_old(self):
        """Tests that ComputeHostNotFound is raised if passed a compute node
        uuid but we can't send it on the 1.38 version.
        """
        with mock.patch.object(self.cells_rpcapi.client, 'can_send_version',
                               return_value=False) as can_send_version_mock:
            self.assertRaises(exception.ComputeHostNotFound,
                              self.cells_rpcapi.compute_node_get,
                              self.fake_context, uuids.compute_id)
        can_send_version_mock.assert_called_once_with('1.38')

    def test_compute_node_get_with_uuid(self):
        """Tests that we send a message at 1.38 if the compute node uuid is
        passed in and the version check passes.
        """
        fake_compute_node = objects.ComputeNode(uuid=uuids.compute_id)
        call_info = self._stub_rpc_method('call', fake_compute_node)
        self.assertEqual(fake_compute_node,
                         self.cells_rpcapi.compute_node_get(
                             self.fake_context, uuids.compute_id))
        args = dict(compute_id=uuids.compute_id)
        self._check_result(call_info, 'compute_node_get', args, version='1.38')

    def test_actions_get(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': 'region!child'}
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.actions_get(self.fake_context,
                                               fake_instance)
        expected_args = {'cell_name': 'region!child',
                         'instance_uuid': fake_instance['uuid']}
        self._check_result(call_info, 'actions_get', expected_args,
                           version='1.5')
        self.assertEqual('fake_response', result)

    def test_actions_get_no_cell(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': None}
        self.assertRaises(exception.InstanceUnknownCell,
                          self.cells_rpcapi.actions_get, self.fake_context,
                          fake_instance)

    def test_action_get_by_request_id(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': 'region!child'}
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.action_get_by_request_id(self.fake_context,
                                                            fake_instance,
                                                            'req-fake')
        expected_args = {'cell_name': 'region!child',
                         'instance_uuid': fake_instance['uuid'],
                         'request_id': 'req-fake'}
        self._check_result(call_info, 'action_get_by_request_id',
                           expected_args, version='1.5')
        self.assertEqual('fake_response', result)

    def test_action_get_by_request_id_no_cell(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': None}
        self.assertRaises(exception.InstanceUnknownCell,
                          self.cells_rpcapi.action_get_by_request_id,
                          self.fake_context, fake_instance, 'req-fake')

    def test_action_events_get(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': 'region!child'}
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.action_events_get(self.fake_context,
                                                     fake_instance,
                                                     'fake-action')
        expected_args = {'cell_name': 'region!child',
                         'action_id': 'fake-action'}
        self._check_result(call_info, 'action_events_get', expected_args,
                           version='1.5')
        self.assertEqual('fake_response', result)

    def test_action_events_get_no_cell(self):
        fake_instance = {'uuid': uuids.instance, 'cell_name': None}
        self.assertRaises(exception.InstanceUnknownCell,
                          self.cells_rpcapi.action_events_get,
                          self.fake_context, fake_instance, 'fake-action')

    def test_consoleauth_delete_tokens(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.consoleauth_delete_tokens(self.fake_context,
                                                    uuids.instance)

        expected_args = {'instance_uuid': uuids.instance}
        self._check_result(call_info, 'consoleauth_delete_tokens',
                expected_args, version='1.6')

    def test_validate_console_port(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.validate_console_port(self.fake_context,
                uuids.instance, 'fake-port', 'fake-type')

        expected_args = {'instance_uuid': uuids.instance,
                         'console_port': 'fake-port',
                         'console_type': 'fake-type'}
        self._check_result(call_info, 'validate_console_port',
                expected_args, version='1.6')
        self.assertEqual('fake_response', result)

    def test_bdm_update_or_create_at_top(self):
        fake_bdm = {'id': 2, 'other': 'meow'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.bdm_update_or_create_at_top(
                self.fake_context, fake_bdm, create='fake-create')

        expected_args = {'bdm': fake_bdm, 'create': 'fake-create'}
        self._check_result(call_info, 'bdm_update_or_create_at_top',
                expected_args, version='1.28')

    def test_bdm_destroy_at_top(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.bdm_destroy_at_top(self.fake_context,
                                             uuids.instance,
                                             device_name='fake-device',
                                             volume_id='fake-vol')

        expected_args = {'instance_uuid': uuids.instance,
                         'device_name': 'fake-device',
                         'volume_id': 'fake-vol'}
        self._check_result(call_info, 'bdm_destroy_at_top',
                expected_args, version='1.10')

    def test_get_migrations(self):
        call_info = self._stub_rpc_method('call', None)
        filters = {'cell_name': 'ChildCell', 'status': 'confirmed'}

        self.cells_rpcapi.get_migrations(self.fake_context, filters)

        expected_args = {'filters': filters}
        self._check_result(call_info, 'get_migrations', expected_args,
                           version="1.11")

    def test_instance_update_from_api(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_update_from_api(
                self.fake_context, 'fake-instance',
                expected_vm_state='exp_vm',
                expected_task_state='exp_task',
                admin_state_reset='admin_reset')

        expected_args = {'instance': 'fake-instance',
                         'expected_vm_state': 'exp_vm',
                         'expected_task_state': 'exp_task',
                         'admin_state_reset': 'admin_reset'}
        self._check_result(call_info, 'instance_update_from_api',
                expected_args, version='1.16')

    def test_start_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.start_instance(
                self.fake_context, 'fake-instance')

        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'start_instance',
                expected_args, version='1.12')

    def test_stop_instance_cast(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.stop_instance(
                self.fake_context, 'fake-instance', do_cast=True,
                clean_shutdown=True)

        expected_args = {'instance': 'fake-instance',
                         'do_cast': True,
                         'clean_shutdown': True}
        self._check_result(call_info, 'stop_instance',
                expected_args, version='1.31')

    def test_stop_instance_call(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.stop_instance(
                self.fake_context, 'fake-instance', do_cast=False,
                clean_shutdown=True)

        expected_args = {'instance': 'fake-instance',
                         'do_cast': False,
                         'clean_shutdown': True}
        self._check_result(call_info, 'stop_instance',
                expected_args, version='1.31')
        self.assertEqual('fake_response', result)

    def test_cell_create(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.cell_create(self.fake_context, 'values')

        expected_args = {'values': 'values'}
        self._check_result(call_info, 'cell_create',
                           expected_args, version='1.13')
        self.assertEqual('fake_response', result)

    def test_cell_update(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.cell_update(self.fake_context,
                                               'cell_name', 'values')

        expected_args = {'cell_name': 'cell_name',
                         'values': 'values'}
        self._check_result(call_info, 'cell_update',
                           expected_args, version='1.13')
        self.assertEqual('fake_response', result)

    def test_cell_delete(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.cell_delete(self.fake_context,
                                               'cell_name')

        expected_args = {'cell_name': 'cell_name'}
        self._check_result(call_info, 'cell_delete',
                           expected_args, version='1.13')
        self.assertEqual('fake_response', result)

    def test_cell_get(self):
        call_info = self._stub_rpc_method('call', 'fake_response')

        result = self.cells_rpcapi.cell_get(self.fake_context,
                                            'cell_name')

        expected_args = {'cell_name': 'cell_name'}
        self._check_result(call_info, 'cell_get',
                           expected_args, version='1.13')
        self.assertEqual('fake_response', result)

    def test_reboot_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.reboot_instance(
                self.fake_context, 'fake-instance',
                block_device_info='ignored', reboot_type='HARD')

        expected_args = {'instance': 'fake-instance',
                         'reboot_type': 'HARD'}
        self._check_result(call_info, 'reboot_instance',
                expected_args, version='1.14')

    def test_pause_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.pause_instance(
                self.fake_context, 'fake-instance')

        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'pause_instance',
                expected_args, version='1.19')

    def test_unpause_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.unpause_instance(
                self.fake_context, 'fake-instance')

        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'unpause_instance',
                expected_args, version='1.19')

    def test_suspend_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.suspend_instance(
                self.fake_context, 'fake-instance')

        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'suspend_instance',
                expected_args, version='1.15')

    def test_resume_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.resume_instance(
                self.fake_context, 'fake-instance')

        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'resume_instance',
                expected_args, version='1.15')

    def test_terminate_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.terminate_instance(self.fake_context,
                                             'fake-instance', [],
                                             delete_type='delete')
        expected_args = {'instance': 'fake-instance',
                         'delete_type': 'delete'}
        self._check_result(call_info, 'terminate_instance',
                           expected_args, version='1.36')

    def test_soft_delete_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.soft_delete_instance(self.fake_context,
                                               'fake-instance')
        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'soft_delete_instance',
                           expected_args, version='1.18')

    def test_resize_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.resize_instance(self.fake_context,
                                          'fake-instance',
                                          dict(cow='moo'),
                                          'fake-hint',
                                          'fake-flavor',
                                          'fake-reservations',
                                          clean_shutdown=True)
        expected_args = {'instance': 'fake-instance',
                         'flavor': 'fake-flavor',
                         'extra_instance_updates': dict(cow='moo'),
                         'clean_shutdown': True}
        self._check_result(call_info, 'resize_instance',
                           expected_args, version='1.33')

    def test_resize_instance_not_passing_request_spec(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.resize_instance(self.fake_context,
                                          'fake-instance',
                                          dict(cow='moo'),
                                          'fake-hint',
                                          'fake-flavor',
                                          'fake-reservations',
                                          clean_shutdown=True,
                                          request_spec='fake-spec')
        expected_args = {'instance': 'fake-instance',
                         'flavor': 'fake-flavor',
                         'extra_instance_updates': dict(cow='moo'),
                         'clean_shutdown': True}
        self._check_result(call_info, 'resize_instance',
                           expected_args, version='1.33')

    def test_live_migrate_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.live_migrate_instance(self.fake_context,
                                                'fake-instance',
                                                'fake-host',
                                                'fake-block',
                                                'fake-commit')
        expected_args = {'instance': 'fake-instance',
                         'block_migration': 'fake-block',
                         'disk_over_commit': 'fake-commit',
                         'host_name': 'fake-host'}
        self._check_result(call_info, 'live_migrate_instance',
                           expected_args, version='1.20')

    def test_live_migrate_instance_not_passing_request_spec(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.live_migrate_instance(self.fake_context,
                                                'fake-instance',
                                                'fake-host',
                                                'fake-block',
                                                'fake-commit',
                                                'fake-spec')
        expected_args = {'instance': 'fake-instance',
                         'block_migration': 'fake-block',
                         'disk_over_commit': 'fake-commit',
                         'host_name': 'fake-host'}
        self._check_result(call_info, 'live_migrate_instance',
                           expected_args, version='1.20')

    def test_rebuild_instance_not_passing_request_spec(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.rebuild_instance(self.fake_context,
                                           'fake-instance',
                                           'fake-pass',
                                           'fake-files',
                                           'fake-image_ref',
                                           'fake-orig_image_ref',
                                           'fake-orig_sys_metadata',
                                           'fake-bdms',
                                           recreate=False,
                                           on_shared_storage=False,
                                           host=None,
                                           preserve_ephemeral=False,
                                           request_spec='fake-spec',
                                           kwargs=None)
        expected_args = {'instance': 'fake-instance',
                         'image_href': 'fake-image_ref',
                         'admin_password': 'fake-pass',
                         'files_to_inject': 'fake-files',
                         'preserve_ephemeral': False,
                         'kwargs': None}
        self._check_result(call_info, 'rebuild_instance',
                           expected_args, version='1.25')

    def test_revert_resize(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.revert_resize(self.fake_context,
                                        'fake-instance',
                                        'fake-migration',
                                        'fake-dest',
                                        'resvs')
        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'revert_resize',
                           expected_args, version='1.21')

    def test_confirm_resize(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.confirm_resize(self.fake_context,
                                         'fake-instance',
                                         'fake-migration',
                                         'fake-source',
                                         'resvs')
        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'confirm_resize',
                           expected_args, version='1.21')

    def test_reset_network(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.reset_network(self.fake_context,
                                        'fake-instance')
        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'reset_network',
                           expected_args, version='1.22')

    def test_inject_network_info(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.inject_network_info(self.fake_context,
                                             'fake-instance')
        expected_args = {'instance': 'fake-instance'}
        self._check_result(call_info, 'inject_network_info',
                           expected_args, version='1.23')

    def test_snapshot_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.snapshot_instance(self.fake_context,
                                            'fake-instance',
                                            'image-id')
        expected_args = {'instance': 'fake-instance',
                         'image_id': 'image-id'}
        self._check_result(call_info, 'snapshot_instance',
                           expected_args, version='1.24')

    def test_backup_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.backup_instance(self.fake_context,
                                          'fake-instance',
                                          'image-id',
                                          'backup-type',
                                          'rotation')
        expected_args = {'instance': 'fake-instance',
                         'image_id': 'image-id',
                         'backup_type': 'backup-type',
                         'rotation': 'rotation'}
        self._check_result(call_info, 'backup_instance',
                           expected_args, version='1.24')

    def test_set_admin_password(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.set_admin_password(self.fake_context,
                'fake-instance', 'fake-password')

        expected_args = {'instance': 'fake-instance',
                         'new_pass': 'fake-password'}
        self._check_result(call_info, 'set_admin_password',
                expected_args, version='1.29')

    def test_get_keypair_at_top(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.get_keypair_at_top(self.fake_context,
                                              'fake_user_id', 'fake_name')

        expected_args = {'user_id': 'fake_user_id',
                         'name': 'fake_name'}
        self._check_result(call_info, 'get_keypair_at_top',
                           expected_args, version='1.37')
        self.assertEqual(result, 'fake_response')

    def test_get_keypair_at_top_with_not_found(self):
        call_info = self._stub_rpc_method('call', None)
        self.assertRaises(exception.KeypairNotFound,
                          self.cells_rpcapi.get_keypair_at_top,
                          self.fake_context, 'fake_user_id', 'fake_name')

        expected_args = {'user_id': 'fake_user_id',
                         'name': 'fake_name'}
        self._check_result(call_info, 'get_keypair_at_top',
                           expected_args, version='1.37')
