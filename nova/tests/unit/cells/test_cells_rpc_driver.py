# Copyright (c) 2012 Rackspace Hosting
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
"""
Tests For Cells RPC Communication Driver
"""

import mock
import oslo_messaging

from nova.cells import messaging
from nova.cells import rpc_driver
import nova.conf
from nova import context
from nova import test
from nova.tests.unit.cells import fakes

CONF = nova.conf.CONF


class CellsRPCDriverTestCase(test.NoDBTestCase):
    """Test case for Cells communication via RPC."""

    def setUp(self):
        super(CellsRPCDriverTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self.driver = rpc_driver.CellsRPCDriver()

    @mock.patch('nova.rpc.get_server')
    def test_start_servers(self, mock_get_server):
        self.flags(rpc_driver_queue_base='cells.intercell42', group='cells')
        fake_msg_runner = fakes.get_message_runner('api-cell')

        class FakeInterCellRPCDispatcher(object):
            def __init__(_self, msg_runner):
                self.assertEqual(fake_msg_runner, msg_runner)

        endpoints = [test.MatchType(FakeInterCellRPCDispatcher)]
        self.stub_out('nova.cells.rpc_driver.InterCellRPCDispatcher',
                      FakeInterCellRPCDispatcher)
        rpcserver = mock.Mock()
        mock_get_server.return_value = rpcserver

        expected_mock_get_server_called_list = []
        for message_type in messaging.MessageRunner.get_message_types():
            topic = 'cells.intercell42.' + message_type
            target = oslo_messaging.Target(topic=topic, server=CONF.host)
            expected_mock_get_server_called_list.append(
                mock.call(target, endpoints=endpoints))

        self.driver.start_servers(fake_msg_runner)
        rpcserver.start.assert_called()
        self.assertEqual(expected_mock_get_server_called_list,
                         mock_get_server.call_args_list)
        self.assertEqual(len(messaging.MessageRunner.get_message_types()),
                         rpcserver.start.call_count)
        self.assertEqual(len(messaging.MessageRunner.get_message_types()),
                         mock_get_server.call_count)

    def test_stop_servers(self):
        call_info = {'stopped': []}

        class FakeRPCServer(object):
            def stop(self):
                call_info['stopped'].append(self)

        fake_servers = [FakeRPCServer() for x in range(5)]
        self.driver.rpc_servers = fake_servers
        self.driver.stop_servers()
        self.assertEqual(fake_servers, call_info['stopped'])

    def test_create_transport_once(self):
        # should only construct each Transport once
        rpcapi = self.driver.intercell_rpcapi

        transport_url = 'amqp://fakeurl'
        next_hop = fakes.FakeCellState('cellname')
        next_hop.db_info['transport_url'] = transport_url

        # first call to _get_transport creates a oslo.messaging.Transport obj
        with mock.patch.object(oslo_messaging,
                               'get_rpc_transport') as get_trans:
            transport = rpcapi._get_transport(next_hop)
            get_trans.assert_called_once_with(rpc_driver.CONF, transport_url)
            self.assertIn(transport_url, rpcapi.transports)
            self.assertEqual(transport, rpcapi.transports[transport_url])

        # subsequent calls should return the pre-created Transport obj
        transport2 = rpcapi._get_transport(next_hop)
        self.assertEqual(transport, transport2)

    def test_send_message_to_cell_cast(self):
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._TargetedMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', cell_state, fanout=False)

        expected_server_params = {'hostname': 'rpc_host2',
                                  'password': 'password2',
                                  'port': 3092,
                                  'username': 'username2',
                                  'virtual_host': 'rpc_vhost2'}
        expected_url = ('rabbit://%(username)s:%(password)s@'
                        '%(hostname)s:%(port)d/%(virtual_host)s' %
                        expected_server_params)

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = mock.Mock()

        with mock.patch.object(rpcapi, '_get_client') as m_get_client:
            m_get_client.return_value = rpcclient

            self.driver.send_message_to_cell(cell_state, message)
            m_get_client.assert_called_with(cell_state,
                                            'cells.intercell.targeted')
            self.assertEqual(expected_url,
                             cell_state.db_info['transport_url'])
            rpcclient.cast.assert_called_with(mock.ANY,
                                              'process_message',
                                              message=message.to_json())

    def test_send_message_to_cell_fanout_cast(self):
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._TargetedMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', cell_state, fanout=True)

        expected_server_params = {'hostname': 'rpc_host2',
                                  'password': 'password2',
                                  'port': 3092,
                                  'username': 'username2',
                                  'virtual_host': 'rpc_vhost2'}
        expected_url = ('rabbit://%(username)s:%(password)s@'
                        '%(hostname)s:%(port)d/%(virtual_host)s' %
                        expected_server_params)

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = mock.Mock()

        with mock.patch.object(rpcapi, '_get_client') as m_get_client:
            m_get_client.return_value = rpcclient

            rpcclient.return_value = rpcclient
            rpcclient.prepare.return_value = rpcclient

            self.driver.send_message_to_cell(cell_state, message)
            m_get_client.assert_called_with(cell_state,
                                            'cells.intercell.targeted')
            self.assertEqual(expected_url,
                             cell_state.db_info['transport_url'])
            rpcclient.prepare.assert_called_with(fanout=True)
            rpcclient.cast.assert_called_with(mock.ANY,
                                              'process_message',
                                              message=message.to_json())

    def test_rpc_topic_uses_message_type(self):
        self.flags(rpc_driver_queue_base='cells.intercell42', group='cells')
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._BroadcastMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', fanout=True)
        message.message_type = 'fake-message-type'

        expected_server_params = {'hostname': 'rpc_host2',
                                  'password': 'password2',
                                  'port': 3092,
                                  'username': 'username2',
                                  'virtual_host': 'rpc_vhost2'}
        expected_url = ('rabbit://%(username)s:%(password)s@'
                        '%(hostname)s:%(port)d/%(virtual_host)s' %
                        expected_server_params)

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = mock.Mock()

        with mock.patch.object(rpcapi, '_get_client') as m_get_client:
            m_get_client.return_value = rpcclient

            rpcclient.prepare(fanout=True)
            rpcclient.prepare.return_value = rpcclient

            self.driver.send_message_to_cell(cell_state, message)
            m_get_client.assert_called_with(cell_state,
                    'cells.intercell42.fake-message-type')
            self.assertEqual(expected_url,
                             cell_state.db_info['transport_url'])
            rpcclient.prepare.assert_called_with(fanout=True)
            rpcclient.cast.assert_called_with(mock.ANY,
                                              'process_message',
                                              message=message.to_json())

    def test_process_message(self):
        msg_runner = fakes.get_message_runner('api-cell')
        dispatcher = rpc_driver.InterCellRPCDispatcher(msg_runner)
        message = messaging._BroadcastMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', fanout=True)

        call_info = {}

        def _fake_message_from_json(json_message):
            call_info['json_message'] = json_message
            self.assertEqual(message.to_json(), json_message)
            return message

        def _fake_process():
            call_info['process_called'] = True

        msg_runner.message_from_json = _fake_message_from_json
        message.process = _fake_process
        dispatcher.process_message(self.ctxt, message.to_json())
        self.assertEqual(message.to_json(), call_info['json_message'])
        self.assertTrue(call_info['process_called'])
