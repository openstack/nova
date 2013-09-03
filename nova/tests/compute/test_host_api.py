# Copyright (c) 2012 OpenStack Foundation
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

from nova.cells import utils as cells_utils
from nova import compute
from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import exception
from nova.openstack.common import rpc
from nova import test
from nova.tests.objects import test_service


class ComputeHostAPITestCase(test.TestCase):
    def setUp(self):
        super(ComputeHostAPITestCase, self).setUp()
        self.host_api = compute.HostAPI()
        self.ctxt = context.get_admin_context()

    def _compare_obj(self, obj, db_obj):
        test_service.compare(obj, db_obj)

    def _compare_objs(self, obj_list, db_obj_list):
        for index, obj in enumerate(obj_list):
            test_service.compare(obj, db_obj_list[index])

    def _mock_rpc_call(self, expected_message, result=None):
        if result is None:
            result = 'fake-result'
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(self.ctxt, 'compute.fake_host',
                 expected_message, None).AndReturn(result)

    def _mock_assert_host_exists(self):
        """Sets it so that the host API always thinks that 'fake_host'
        exists.
        """
        def fake_assert_host_exists(context, host_name, must_be_up=False):
            return 'fake_host'
        self.stubs.Set(self.host_api, '_assert_host_exists',
                                    fake_assert_host_exists)

    def test_set_host_enabled(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call(
                {'method': 'set_host_enabled',
                 'namespace': None,
                 'args': {'enabled': 'fake_enabled'},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

        self.mox.ReplayAll()
        result = self.host_api.set_host_enabled(self.ctxt, 'fake_host',
                                                'fake_enabled')
        self.assertEqual('fake-result', result)

    def test_host_name_from_assert_hosts_exists(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call(
                {'method': 'set_host_enabled',
                 'namespace': None,
                 'args': {'enabled': 'fake_enabled'},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

        self.mox.ReplayAll()
        result = self.host_api.set_host_enabled(self.ctxt, 'fake_hosT',
                                                'fake_enabled')
        self.assertEqual('fake-result', result)

    def test_get_host_uptime(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call(
                {'method': 'get_host_uptime',
                 'namespace': None,
                 'args': {},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()
        result = self.host_api.get_host_uptime(self.ctxt, 'fake_host')
        self.assertEqual('fake-result', result)

    def test_get_host_uptime_service_down(self):
        def fake_service_get_by_compute_host(context, host_name):
            return dict(test_service.fake_service, id=1)
        self.stubs.Set(self.host_api.db, 'service_get_by_compute_host',
                                    fake_service_get_by_compute_host)

        def fake_service_is_up(service):
            return False
        self.stubs.Set(self.host_api.servicegroup_api,
                       'service_is_up', fake_service_is_up)

        self.assertRaises(exception.ComputeServiceUnavailable,
                          self.host_api.get_host_uptime, self.ctxt,
                          'fake_host')

    def test_host_power_action(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call(
                {'method': 'host_power_action',
                 'namespace': None,
                 'args': {'action': 'fake_action'},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()
        result = self.host_api.host_power_action(self.ctxt, 'fake_host',
                                                 'fake_action')
        self.assertEqual('fake-result', result)

    def test_set_host_maintenance(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call(
                {'method': 'host_maintenance_mode',
                 'namespace': None,
                 'args': {'host': 'fake_host', 'mode': 'fake_mode'},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()
        result = self.host_api.set_host_maintenance(self.ctxt, 'fake_host',
                                                    'fake_mode')
        self.assertEqual('fake-result', result)

    def test_service_get_all_no_zones(self):
        services = [dict(test_service.fake_service,
                         id=1, topic='compute', host='host1'),
                    dict(test_service.fake_service,
                         topic='compute', host='host2')]

        self.mox.StubOutWithMock(self.host_api.db,
                                 'service_get_all')

        # Test no filters
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt)
        self.mox.VerifyAll()
        self._compare_objs(result, services)

        # Test no filters #2
        self.mox.ResetAll()
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt, filters={})
        self.mox.VerifyAll()
        self._compare_objs(result, services)

        # Test w/ filter
        self.mox.ResetAll()
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=dict(host='host2'))
        self.mox.VerifyAll()
        self._compare_objs(result, [services[1]])

    def test_service_get_all(self):
        services = [dict(test_service.fake_service,
                         topic='compute', host='host1'),
                    dict(test_service.fake_service,
                         topic='compute', host='host2')]
        exp_services = []
        for service in services:
            exp_service = {}
            exp_service.update(availability_zone='nova', **service)
            exp_services.append(exp_service)

        self.mox.StubOutWithMock(self.host_api.db,
                                 'service_get_all')

        # Test no filters
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt, set_zones=True)
        self.mox.VerifyAll()
        self._compare_objs(result, exp_services)

        # Test no filters #2
        self.mox.ResetAll()
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt, filters={},
                                               set_zones=True)
        self.mox.VerifyAll()
        self._compare_objs(result, exp_services)

        # Test w/ filter
        self.mox.ResetAll()
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=dict(host='host2'),
                                               set_zones=True)
        self.mox.VerifyAll()
        self._compare_objs(result, [exp_services[1]])

        # Test w/ zone filter but no set_zones arg.
        self.mox.ResetAll()
        self.host_api.db.service_get_all(self.ctxt,
                                         disabled=None).AndReturn(services)
        self.mox.ReplayAll()
        filters = {'availability_zone': 'nova'}
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=filters)
        self.mox.VerifyAll()
        self._compare_objs(result, exp_services)

    def test_service_get_by_compute_host(self):
        self.mox.StubOutWithMock(self.host_api.db,
                                 'service_get_by_compute_host')

        self.host_api.db.service_get_by_compute_host(self.ctxt,
                'fake-host').AndReturn(test_service.fake_service)
        self.mox.ReplayAll()
        result = self.host_api.service_get_by_compute_host(self.ctxt,
                                                           'fake-host')
        self.assertEqual(test_service.fake_service['id'], result.id)

    def test_service_update(self):
        host_name = 'fake-host'
        binary = 'nova-compute'
        params_to_update = dict(disabled=True)
        service_id = 42
        expected_result = dict(test_service.fake_service, id=service_id)

        self.mox.StubOutWithMock(self.host_api.db, 'service_get_by_args')
        self.host_api.db.service_get_by_args(self.ctxt,
            host_name, binary).AndReturn(expected_result)

        self.mox.StubOutWithMock(self.host_api.db, 'service_update')
        self.host_api.db.service_update(
            self.ctxt, service_id, params_to_update).AndReturn(expected_result)

        self.mox.ReplayAll()

        result = self.host_api.service_update(
            self.ctxt, host_name, binary, params_to_update)
        self._compare_obj(result, expected_result)

    def test_instance_get_all_by_host(self):
        self.mox.StubOutWithMock(self.host_api.db,
                                 'instance_get_all_by_host')

        self.host_api.db.instance_get_all_by_host(self.ctxt,
                'fake-host').AndReturn(['fake-responses'])
        self.mox.ReplayAll()
        result = self.host_api.instance_get_all_by_host(self.ctxt,
                                                        'fake-host')
        self.assertEqual(['fake-responses'], result)

    def test_task_log_get_all(self):
        self.mox.StubOutWithMock(self.host_api.db, 'task_log_get_all')

        self.host_api.db.task_log_get_all(self.ctxt,
                'fake-name', 'fake-begin', 'fake-end', host='fake-host',
                state='fake-state').AndReturn('fake-response')
        self.mox.ReplayAll()
        result = self.host_api.task_log_get_all(self.ctxt, 'fake-name',
                'fake-begin', 'fake-end', host='fake-host',
                state='fake-state')
        self.assertEqual('fake-response', result)


class ComputeHostAPICellsTestCase(ComputeHostAPITestCase):
    def setUp(self):
        self.flags(enable=True, group='cells')
        self.flags(cell_type='api', group='cells')
        super(ComputeHostAPICellsTestCase, self).setUp()

    def _mock_rpc_call(self, expected_message, result=None):
        if result is None:
            result = 'fake-result'
        # Wrapped with cells call
        expected_message = {'method': 'proxy_rpc_to_manager',
                            'namespace': None,
                            'args': {'topic': 'compute.fake_host',
                                     'rpc_message': expected_message,
                                     'call': True,
                                     'timeout': None},
                            'version': '1.2'}
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(self.ctxt, 'cells', expected_message,
                 None).AndReturn(result)

    def test_service_get_all_no_zones(self):
        services = [dict(test_service.fake_service,
                         id=1, topic='compute', host='host1'),
                    dict(test_service.fake_service,
                         id=2, topic='compute', host='host2')]

        fake_filters = {'host': 'host1'}
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_all')
        self.host_api.cells_rpcapi.service_get_all(self.ctxt,
                filters=fake_filters).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=fake_filters)
        self._compare_objs(result, services)

    def test_service_get_all(self):
        services = [dict(test_service.fake_service,
                         id=1, key1='val1', key2='val2', topic='compute',
                         host='host1'),
                    dict(test_service.fake_service,
                         id=2, key1='val2', key3='val3', topic='compute',
                         host='host2')]
        exp_services = []
        for service in services:
            exp_service = {}
            exp_service.update(availability_zone='nova', **service)
            exp_services.append(exp_service)

        fake_filters = {'key1': 'val1'}
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_all')
        self.host_api.cells_rpcapi.service_get_all(self.ctxt,
                filters=fake_filters).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=fake_filters,
                                               set_zones=True)
        self.mox.VerifyAll()
        self._compare_objs(result, exp_services)

        # Test w/ zone filter but no set_zones arg.
        self.mox.ResetAll()
        fake_filters = {'availability_zone': 'nova'}
        # Zone filter is done client-size, so should be stripped
        # from this call.
        self.host_api.cells_rpcapi.service_get_all(self.ctxt,
                filters={}).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=fake_filters)
        self.mox.VerifyAll()
        self._compare_objs(result, exp_services)

    def test_service_get_by_compute_host(self):
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_by_compute_host')

        self.host_api.cells_rpcapi.service_get_by_compute_host(self.ctxt,
                'fake-host').AndReturn(test_service.fake_service)
        self.mox.ReplayAll()
        result = self.host_api.service_get_by_compute_host(self.ctxt,
                                                           'fake-host')
        self._compare_obj(result, test_service.fake_service)

    def test_service_update(self):
        host_name = 'fake-host'
        binary = 'nova-compute'
        params_to_update = dict(disabled=True)
        service_id = 42
        expected_result = dict(test_service.fake_service, id=service_id)

        self.mox.StubOutWithMock(self.host_api.cells_rpcapi, 'service_update')
        self.host_api.cells_rpcapi.service_update(
            self.ctxt, host_name,
            binary, params_to_update).AndReturn(expected_result)

        self.mox.ReplayAll()

        result = self.host_api.service_update(
            self.ctxt, host_name, binary, params_to_update)
        self._compare_obj(result, expected_result)

    def test_instance_get_all_by_host(self):
        instances = [dict(id=1, cell_name='cell1', host='host1'),
                     dict(id=2, cell_name='cell2', host='host1'),
                     dict(id=3, cell_name='cell1', host='host2')]

        self.mox.StubOutWithMock(self.host_api.db,
                                 'instance_get_all_by_host')

        self.host_api.db.instance_get_all_by_host(self.ctxt,
                'fake-host').AndReturn(instances)
        self.mox.ReplayAll()
        expected_result = [instances[0], instances[2]]
        cell_and_host = cells_utils.cell_with_item('cell1', 'fake-host')
        result = self.host_api.instance_get_all_by_host(self.ctxt,
                cell_and_host)
        self.assertEqual(expected_result, result)

    def test_task_log_get_all(self):
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'task_log_get_all')

        self.host_api.cells_rpcapi.task_log_get_all(self.ctxt,
                'fake-name', 'fake-begin', 'fake-end', host='fake-host',
                state='fake-state').AndReturn('fake-response')
        self.mox.ReplayAll()
        result = self.host_api.task_log_get_all(self.ctxt, 'fake-name',
                'fake-begin', 'fake-end', host='fake-host',
                state='fake-state')
        self.assertEqual('fake-response', result)

    def test_get_host_uptime_service_down(self):
        # The corresponing Compute test case depends on the
        # _assert_host_exists which is a no-op in the cells api
        pass

    def test_get_host_uptime(self):
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'get_host_uptime')

        self.host_api.cells_rpcapi.get_host_uptime(self.ctxt,
                                                   'fake-host'). \
            AndReturn('fake-response')
        self.mox.ReplayAll()
        result = self.host_api.get_host_uptime(self.ctxt, 'fake-host')
        self.assertEqual('fake-response', result)
