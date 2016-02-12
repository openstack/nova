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
from mox3 import mox
import oslo_messaging

from nova.cells import messaging
from nova.cells import rpc_driver
import nova.conf
from nova import context
from nova import rpc
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

    def test_start_servers(self):
        self.flags(rpc_driver_queue_base='cells.intercell42', group='cells')
        fake_msg_runner = fakes.get_message_runner('api-cell')

        class FakeInterCellRPCDispatcher(object):
            def __init__(_self, msg_runner):
                self.assertEqual(fake_msg_runner, msg_runner)

        self.stubs.Set(rpc_driver, 'InterCellRPCDispatcher',
                       FakeInterCellRPCDispatcher)
        self.mox.StubOutWithMock(rpc, 'get_server')

        for message_type in messaging.MessageRunner.get_message_types():
            topic = 'cells.intercell42.' + message_type
            target = oslo_messaging.Target(topic=topic, server=CONF.host)
            endpoints = [mox.IsA(FakeInterCellRPCDispatcher)]

            rpcserver = self.mox.CreateMockAnything()
            rpc.get_server(target, endpoints=endpoints).AndReturn(rpcserver)
            rpcserver.start()

        self.mox.ReplayAll()

        self.driver.start_servers(fake_msg_runner)

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
        with mock.patch.object(oslo_messaging, 'get_transport') as get_trans:
            transport = rpcapi._get_transport(next_hop)
            get_trans.assert_called_once_with(rpc_driver.CONF, transport_url,
                                              rpc.TRANSPORT_ALIASES)
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

        def check_transport_url(cell_state):
            return cell_state.db_info['transport_url'] == expected_url

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = self.mox.CreateMockAnything()

        self.mox.StubOutWithMock(rpcapi, '_get_client')
        rpcapi._get_client(
            mox.Func(check_transport_url),
            'cells.intercell.targeted').AndReturn(rpcclient)

        rpcclient.cast(mox.IgnoreArg(), 'process_message',
                       message=message.to_json())

        self.mox.ReplayAll()

        self.driver.send_message_to_cell(cell_state, message)

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

        def check_transport_url(cell_state):
            return cell_state.db_info['transport_url'] == expected_url

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = self.mox.CreateMockAnything()

        self.mox.StubOutWithMock(rpcapi, '_get_client')
        rpcapi._get_client(
            mox.Func(check_transport_url),
            'cells.intercell.targeted').AndReturn(rpcclient)

        rpcclient.prepare(fanout=True).AndReturn(rpcclient)
        rpcclient.cast(mox.IgnoreArg(), 'process_message',
                       message=message.to_json())

        self.mox.ReplayAll()

        self.driver.send_message_to_cell(cell_state, message)

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

        def check_transport_url(cell_state):
            return cell_state.db_info['transport_url'] == expected_url

        rpcapi = self.driver.intercell_rpcapi
        rpcclient = self.mox.CreateMockAnything()

        self.mox.StubOutWithMock(rpcapi, '_get_client')
        rpcapi._get_client(
            mox.Func(check_transport_url),
            'cells.intercell42.fake-message-type').AndReturn(rpcclient)

        rpcclient.prepare(fanout=True).AndReturn(rpcclient)
        rpcclient.cast(mox.IgnoreArg(), 'process_message',
                       message=message.to_json())

        self.mox.ReplayAll()

        self.driver.send_message_to_cell(cell_state, message)

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

        self.stubs.Set(msg_runner, 'message_from_json',
                _fake_message_from_json)
        self.stubs.Set(message, 'process', _fake_process)

        dispatcher.process_message(self.ctxt, message.to_json())
        self.assertEqual(message.to_json(), call_info['json_message'])
        self.assertTrue(call_info['process_called'])
