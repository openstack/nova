# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

import copy

import mock
from oslo_serialization import jsonutils

from nova.cells import utils as cells_utils
from nova import compute
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_service


class ComputeHostAPITestCase(test.TestCase):
    def setUp(self):
        super(ComputeHostAPITestCase, self).setUp()
        self.host_api = compute.HostAPI()
        self.ctxt = context.get_admin_context()
        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

    def _compare_obj(self, obj, db_obj):
        test_objects.compare_obj(self, obj, db_obj,
                                 allow_missing=test_service.OPTIONAL)

    def _compare_objs(self, obj_list, db_obj_list):
        for index, obj in enumerate(obj_list):
            self._compare_obj(obj, db_obj_list[index])

    def _mock_rpc_call(self, method, **kwargs):
        self.mox.StubOutWithMock(self.host_api.rpcapi, method)
        getattr(self.host_api.rpcapi, method)(
            self.ctxt, **kwargs).AndReturn('fake-result')

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
        self._mock_rpc_call('set_host_enabled',
                            host='fake_host',
                            enabled='fake_enabled')
        self.mox.ReplayAll()
        fake_notifier.NOTIFICATIONS = []
        result = self.host_api.set_host_enabled(self.ctxt, 'fake_host',
                                                'fake_enabled')
        self.assertEqual('fake-result', result)
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('HostAPI.set_enabled.start', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_enabled', msg.payload['enabled'])
        self.assertEqual('fake_host', msg.payload['host_name'])
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual('HostAPI.set_enabled.end', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_enabled', msg.payload['enabled'])
        self.assertEqual('fake_host', msg.payload['host_name'])

    def test_host_name_from_assert_hosts_exists(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call('set_host_enabled',
                            host='fake_host',
                            enabled='fake_enabled')
        self.mox.ReplayAll()
        result = self.host_api.set_host_enabled(self.ctxt, 'fake_hosT',
                                                'fake_enabled')
        self.assertEqual('fake-result', result)

    def test_get_host_uptime(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call('get_host_uptime',
                            host='fake_host')
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
        self._mock_rpc_call('host_power_action',
                            host='fake_host',
                            action='fake_action')
        self.mox.ReplayAll()
        fake_notifier.NOTIFICATIONS = []
        result = self.host_api.host_power_action(self.ctxt, 'fake_host',
                                                 'fake_action')
        self.assertEqual('fake-result', result)
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('HostAPI.power_action.start', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_action', msg.payload['action'])
        self.assertEqual('fake_host', msg.payload['host_name'])
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual('HostAPI.power_action.end', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_action', msg.payload['action'])
        self.assertEqual('fake_host', msg.payload['host_name'])

    def test_set_host_maintenance(self):
        self._mock_assert_host_exists()
        self._mock_rpc_call('host_maintenance_mode',
                            host='fake_host',
                            host_param='fake_host',
                            mode='fake_mode')
        self.mox.ReplayAll()
        fake_notifier.NOTIFICATIONS = []
        result = self.host_api.set_host_maintenance(self.ctxt, 'fake_host',
                                                    'fake_mode')
        self.assertEqual('fake-result', result)
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('HostAPI.set_maintenance.start', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_host', msg.payload['host_name'])
        self.assertEqual('fake_mode', msg.payload['mode'])
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual('HostAPI.set_maintenance.end', msg.event_type)
        self.assertEqual('api.fake_host', msg.publisher_id)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake_host', msg.payload['host_name'])
        self.assertEqual('fake_mode', msg.payload['mode'])

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

        self.mox.StubOutWithMock(self.host_api.db,
                                 'service_get_by_host_and_binary')
        self.host_api.db.service_get_by_host_and_binary(self.ctxt,
            host_name, binary).AndReturn(expected_result)

        self.mox.StubOutWithMock(self.host_api.db, 'service_update')
        self.host_api.db.service_update(
            self.ctxt, service_id, params_to_update).AndReturn(expected_result)

        self.mox.ReplayAll()

        result = self.host_api.service_update(
            self.ctxt, host_name, binary, params_to_update)
        self._compare_obj(result, expected_result)

    @mock.patch.object(objects.InstanceList, 'get_by_host',
                       return_value = ['fake-responses'])
    def test_instance_get_all_by_host(self, mock_get):
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

    def test_service_delete(self):
        with test.nested(
            mock.patch.object(objects.Service, 'get_by_id',
                              return_value=objects.Service()),
            mock.patch.object(objects.Service, 'destroy')
        ) as (
            get_by_id, destroy
        ):
            self.host_api.service_delete(self.ctxt, 1)
            get_by_id.assert_called_once_with(self.ctxt, 1)
            destroy.assert_called_once_with()


class ComputeHostAPICellsTestCase(ComputeHostAPITestCase):
    def setUp(self):
        self.flags(enable=True, group='cells')
        self.flags(cell_type='api', group='cells')
        super(ComputeHostAPICellsTestCase, self).setUp()

    def _mock_rpc_call(self, method, **kwargs):
        if 'host_param' in kwargs:
            kwargs.pop('host_param')
        else:
            kwargs.pop('host')
        rpc_message = {
            'method': method,
            'namespace': None,
            'args': kwargs,
            'version': self.host_api.rpcapi.client.target.version,
        }
        cells_rpcapi = self.host_api.rpcapi.client.cells_rpcapi
        self.mox.StubOutWithMock(cells_rpcapi, 'proxy_rpc_to_manager')
        cells_rpcapi.proxy_rpc_to_manager(self.ctxt,
                                          rpc_message,
                                          'compute.fake_host',
                                          call=True).AndReturn('fake-result')

    def test_service_get_all_no_zones(self):
        services = [
            cells_utils.ServiceProxy(
                objects.Service(id=1, topic='compute', host='host1'),
                'cell1'),
            cells_utils.ServiceProxy(
                objects.Service(id=2, topic='compute', host='host2'),
                'cell1')]

        fake_filters = {'host': 'host1'}
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_all')
        self.host_api.cells_rpcapi.service_get_all(self.ctxt,
                filters=fake_filters).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=fake_filters)
        self.assertEqual(services, result)

    def _test_service_get_all(self, fake_filters, **kwargs):
        service_attrs = dict(test_service.fake_service)
        del service_attrs['version']
        services = [
            cells_utils.ServiceProxy(
                objects.Service(**dict(service_attrs, id=1,
                                topic='compute', host='host1')),
                'cell1'),
            cells_utils.ServiceProxy(
                objects.Service(**dict(service_attrs, id=2,
                                topic='compute', host='host2')),
                'cell1')]
        exp_services = []
        for service in services:
            exp_service = copy.copy(service)
            exp_service.update({'availability_zone': 'nova'})
            exp_services.append(exp_service)

        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_all')
        self.host_api.cells_rpcapi.service_get_all(self.ctxt,
                filters=fake_filters).AndReturn(services)
        self.mox.ReplayAll()
        result = self.host_api.service_get_all(self.ctxt,
                                               filters=fake_filters,
                                               **kwargs)
        self.mox.VerifyAll()
        self.assertEqual(jsonutils.to_primitive(exp_services),
                         jsonutils.to_primitive(result))

    def test_service_get_all(self):
        fake_filters = {'availability_zone': 'nova'}
        self._test_service_get_all(fake_filters)

    def test_service_get_all_set_zones(self):
        fake_filters = {'key1': 'val1'}
        self._test_service_get_all(fake_filters, set_zones=True)

    def test_service_get_by_compute_host(self):
        self.mox.StubOutWithMock(self.host_api.cells_rpcapi,
                                 'service_get_by_compute_host')

        obj = objects.Service(id=1, host='fake')
        fake_service = cells_utils.ServiceProxy(obj, 'cell1')

        self.host_api.cells_rpcapi.service_get_by_compute_host(self.ctxt,
                'fake-host').AndReturn(fake_service)
        self.mox.ReplayAll()
        result = self.host_api.service_get_by_compute_host(self.ctxt,
                                                           'fake-host')
        self.assertEqual(fake_service, result)

    def test_service_update(self):
        host_name = 'fake-host'
        binary = 'nova-compute'
        params_to_update = dict(disabled=True)

        obj = objects.Service(id=42, host='fake')
        fake_service = cells_utils.ServiceProxy(obj, 'cell1')

        self.mox.StubOutWithMock(self.host_api.cells_rpcapi, 'service_update')
        self.host_api.cells_rpcapi.service_update(
            self.ctxt, host_name,
            binary, params_to_update).AndReturn(fake_service)

        self.mox.ReplayAll()

        result = self.host_api.service_update(
            self.ctxt, host_name, binary, params_to_update)
        self.assertEqual(fake_service, result)

    def test_service_delete(self):
        cell_service_id = cells_utils.cell_with_item('cell1', 1)
        with mock.patch.object(self.host_api.cells_rpcapi,
                               'service_delete') as service_delete:
            self.host_api.service_delete(self.ctxt, cell_service_id)
            service_delete.assert_called_once_with(
                self.ctxt, cell_service_id)

    @mock.patch.object(objects.InstanceList, 'get_by_host')
    def test_instance_get_all_by_host(self, mock_get):
        instances = [dict(id=1, cell_name='cell1', host='host1'),
                     dict(id=2, cell_name='cell2', host='host1'),
                     dict(id=3, cell_name='cell1', host='host2')]

        mock_get.return_value = instances
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
        # The corresponding Compute test case depends on the
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
