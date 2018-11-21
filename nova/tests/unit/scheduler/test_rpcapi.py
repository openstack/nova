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

"""
Unit Tests for nova.scheduler.rpcapi
"""

import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova import conf
from nova import context
from nova import exception as exc
from nova import objects
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test

CONF = conf.CONF


class SchedulerRpcAPITestCase(test.NoDBTestCase):
    def _test_scheduler_api(self, method, rpc_method, expected_args=None,
                            **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic,
                         scheduler_rpcapi.RPC_TOPIC)

        expected_retval = 'foo' if rpc_method == 'call' else None
        expected_version = kwargs.pop('version', None)
        expected_fanout = kwargs.pop('fanout', None)
        expected_kwargs = kwargs.copy()

        if expected_args:
            expected_kwargs = expected_args

        prepare_kwargs = {}
        if method == 'select_destinations':
            prepare_kwargs.update({
                'call_monitor_timeout': CONF.rpc_response_timeout,
                'timeout': CONF.long_rpc_timeout
            })
        if expected_fanout:
            prepare_kwargs['fanout'] = True
        if expected_version:
            prepare_kwargs['version'] = expected_version

        # NOTE(sbauza): We need to persist the method before mocking it
        orig_prepare = rpcapi.client.prepare

        def fake_can_send_version(version=None):
            return orig_prepare(version=version).can_send_version()

        @mock.patch.object(rpcapi.client, rpc_method,
                           return_value=expected_retval)
        @mock.patch.object(rpcapi.client, 'prepare',
                           return_value=rpcapi.client)
        @mock.patch.object(rpcapi.client, 'can_send_version',
                           side_effect=fake_can_send_version)
        def do_test(mock_csv, mock_prepare, mock_rpc_method):
            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, expected_retval)
            mock_prepare.assert_called_once_with(**prepare_kwargs)
            mock_rpc_method.assert_called_once_with(ctxt, method,
                                                    **expected_kwargs)
        do_test()

    def test_select_destinations(self):
        fake_spec = objects.RequestSpec()
        self._test_scheduler_api('select_destinations', rpc_method='call',
                expected_args={'spec_obj': fake_spec,
                'instance_uuids': [uuids.instance], 'return_objects': True,
                'return_alternates': True},
                spec_obj=fake_spec, instance_uuids=[uuids.instance],
                return_objects=True, return_alternates=True, version='4.5')

    def test_select_destinations_4_4(self):
        self.flags(scheduler='4.4', group='upgrade_levels')
        fake_spec = objects.RequestSpec()
        self._test_scheduler_api('select_destinations', rpc_method='call',
                expected_args={'spec_obj': fake_spec,
                'instance_uuids': [uuids.instance]}, spec_obj=fake_spec,
                instance_uuids=[uuids.instance], return_objects=False,
                return_alternates=False, version='4.4')

    def test_select_destinations_4_3(self):
        self.flags(scheduler='4.3', group='upgrade_levels')
        fake_spec = objects.RequestSpec()
        self._test_scheduler_api('select_destinations', rpc_method='call',
                expected_args={'spec_obj': fake_spec},
                spec_obj=fake_spec, instance_uuids=[uuids.instance],
                return_alternates=False, version='4.3')

    def test_select_destinations_old_with_new_params(self):
        self.flags(scheduler='4.4', group='upgrade_levels')
        fake_spec = objects.RequestSpec()
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.assertRaises(exc.SelectionObjectsWithOldRPCVersionNotSupported,
                rpcapi.select_destinations, ctxt, fake_spec, ['fake_uuids'],
                return_objects=True, return_alternates=True)
        self.assertRaises(exc.SelectionObjectsWithOldRPCVersionNotSupported,
                rpcapi.select_destinations, ctxt, fake_spec, ['fake_uuids'],
                return_objects=False, return_alternates=True)
        self.assertRaises(exc.SelectionObjectsWithOldRPCVersionNotSupported,
                rpcapi.select_destinations, ctxt, fake_spec, ['fake_uuids'],
                return_objects=True, return_alternates=False)

    @mock.patch.object(objects.RequestSpec, 'to_legacy_filter_properties_dict')
    @mock.patch.object(objects.RequestSpec, 'to_legacy_request_spec_dict')
    def test_select_destinations_with_old_manager(self, to_spec, to_props):
        self.flags(scheduler='4.0', group='upgrade_levels')

        to_spec.return_value = 'fake_request_spec'
        to_props.return_value = 'fake_prop'
        fake_spec = objects.RequestSpec()
        self._test_scheduler_api('select_destinations', rpc_method='call',
                expected_args={'request_spec': 'fake_request_spec',
                               'filter_properties': 'fake_prop'},
                spec_obj=fake_spec, instance_uuids=[uuids.instance],
                version='4.0')

    def test_update_aggregates(self):
        self._test_scheduler_api('update_aggregates', rpc_method='cast',
                aggregates='aggregates',
                version='4.1',
                fanout=True)

    def test_delete_aggregate(self):
        self._test_scheduler_api('delete_aggregate', rpc_method='cast',
                aggregate='aggregate',
                version='4.1',
                fanout=True)

    def test_update_instance_info(self):
        self._test_scheduler_api('update_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_info='fake_instance',
                fanout=True,
                version='4.2')

    def test_delete_instance_info(self):
        self._test_scheduler_api('delete_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_uuid='fake_uuid',
                fanout=True,
                version='4.2')

    def test_sync_instance_info(self):
        self._test_scheduler_api('sync_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_uuids=['fake1', 'fake2'],
                fanout=True,
                version='4.2')
