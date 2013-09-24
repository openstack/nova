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
Tests For Cells RPC Communication Driver
"""

import urlparse

from oslo.config import cfg

from nova.cells import messaging
from nova.cells import rpc_driver
from nova import context
from nova.openstack.common import rpc
from nova.openstack.common.rpc import dispatcher as rpc_dispatcher
from nova import test
from nova.tests.cells import fakes

CONF = cfg.CONF
CONF.import_opt('rpc_driver_queue_base', 'nova.cells.rpc_driver',
                group='cells')


class CellsRPCDriverTestCase(test.NoDBTestCase):
    """Test case for Cells communication via RPC."""

    def setUp(self):
        super(CellsRPCDriverTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self.driver = rpc_driver.CellsRPCDriver()

    def test_start_consumers(self):
        self.flags(rpc_driver_queue_base='cells.intercell42', group='cells')
        rpc_consumers = []
        rpc_conns = []
        fake_msg_runner = fakes.get_message_runner('api-cell')
        call_info = {}

        class FakeInterCellRPCDispatcher(object):
            def __init__(_self, msg_runner):
                self.assertEqual(fake_msg_runner, msg_runner)
                call_info['intercell_dispatcher'] = _self

        class FakeRPCDispatcher(object):
            def __init__(_self, proxy_objs):
                self.assertEqual([call_info['intercell_dispatcher']],
                                 proxy_objs)
                call_info['rpc_dispatcher'] = _self

        class FakeRPCConn(object):
            def create_consumer(_self, topic, proxy_obj, **kwargs):
                self.assertEqual(call_info['rpc_dispatcher'], proxy_obj)
                rpc_consumers.append((topic, kwargs))

            def consume_in_thread(_self):
                pass

        def _fake_create_connection(new):
            self.assertTrue(new)
            fake_conn = FakeRPCConn()
            rpc_conns.append(fake_conn)
            return fake_conn

        self.stubs.Set(rpc, 'create_connection', _fake_create_connection)
        self.stubs.Set(rpc_driver, 'InterCellRPCDispatcher',
                       FakeInterCellRPCDispatcher)
        self.stubs.Set(rpc_dispatcher, 'RpcDispatcher', FakeRPCDispatcher)

        self.driver.start_consumers(fake_msg_runner)

        for message_type in ['broadcast', 'response', 'targeted']:
            topic = 'cells.intercell42.' + message_type
            self.assertIn((topic, {'fanout': True}), rpc_consumers)
            self.assertIn((topic, {'fanout': False}), rpc_consumers)
        self.assertEqual(rpc_conns, self.driver.rpc_connections)

    def test_stop_consumers(self):
        call_info = {'closed': []}

        class FakeRPCConn(object):
            def close(self):
                call_info['closed'].append(self)

        fake_conns = [FakeRPCConn() for x in xrange(5)]
        self.driver.rpc_connections = fake_conns
        self.driver.stop_consumers()
        self.assertEqual(fake_conns, call_info['closed'])

    def test_send_message_to_cell_cast(self):
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._TargetedMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', cell_state, fanout=False)

        call_info = {}

        def _fake_make_msg(method, namespace, **kwargs):
            call_info['rpc_method'] = method
            call_info['rpc_kwargs'] = kwargs
            return 'fake-message'

        def _fake_cast_to_server(*args, **kwargs):
            call_info['cast_args'] = args
            call_info['cast_kwargs'] = kwargs

        self.stubs.Set(rpc, 'cast_to_server', _fake_cast_to_server)
        self.stubs.Set(self.driver.intercell_rpcapi, 'make_namespaced_msg',
                       _fake_make_msg)
        self.stubs.Set(self.driver.intercell_rpcapi, 'cast_to_server',
                       _fake_cast_to_server)

        self.driver.send_message_to_cell(cell_state, message)
        expected_server_params = {'hostname': 'rpc_host2',
                                  'password': 'password2',
                                  'port': 3092,
                                  'username': 'username2',
                                  'virtual_host': 'rpc_vhost2'}
        expected_cast_args = (self.ctxt, expected_server_params,
                              'fake-message')
        expected_cast_kwargs = {'topic': 'cells.intercell.targeted'}
        expected_rpc_kwargs = {'message': message.to_json()}
        self.assertEqual(expected_cast_args, call_info['cast_args'])
        self.assertEqual(expected_cast_kwargs, call_info['cast_kwargs'])
        self.assertEqual('process_message', call_info['rpc_method'])
        self.assertEqual(expected_rpc_kwargs, call_info['rpc_kwargs'])

    def test_send_message_to_cell_fanout_cast(self):
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._TargetedMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', cell_state, fanout=True)

        call_info = {}

        def _fake_make_msg(method, namespace, **kwargs):
            call_info['rpc_method'] = method
            call_info['rpc_kwargs'] = kwargs
            return 'fake-message'

        def _fake_fanout_cast_to_server(*args, **kwargs):
            call_info['cast_args'] = args
            call_info['cast_kwargs'] = kwargs

        self.stubs.Set(rpc, 'fanout_cast_to_server',
                       _fake_fanout_cast_to_server)
        self.stubs.Set(self.driver.intercell_rpcapi, 'make_namespaced_msg',
                       _fake_make_msg)
        self.stubs.Set(self.driver.intercell_rpcapi,
                       'fanout_cast_to_server', _fake_fanout_cast_to_server)

        self.driver.send_message_to_cell(cell_state, message)
        expected_server_params = {'hostname': 'rpc_host2',
                                  'password': 'password2',
                                  'port': 3092,
                                  'username': 'username2',
                                  'virtual_host': 'rpc_vhost2'}
        expected_cast_args = (self.ctxt, expected_server_params,
                              'fake-message')
        expected_cast_kwargs = {'topic': 'cells.intercell.targeted'}
        expected_rpc_kwargs = {'message': message.to_json()}
        self.assertEqual(expected_cast_args, call_info['cast_args'])
        self.assertEqual(expected_cast_kwargs, call_info['cast_kwargs'])
        self.assertEqual('process_message', call_info['rpc_method'])
        self.assertEqual(expected_rpc_kwargs, call_info['rpc_kwargs'])

    def test_rpc_topic_uses_message_type(self):
        self.flags(rpc_driver_queue_base='cells.intercell42', group='cells')
        msg_runner = fakes.get_message_runner('api-cell')
        cell_state = fakes.get_cell_state('api-cell', 'child-cell2')
        message = messaging._BroadcastMessage(msg_runner,
                self.ctxt, 'fake', {}, 'down', fanout=True)
        message.message_type = 'fake-message-type'

        call_info = {}

        def _fake_fanout_cast_to_server(*args, **kwargs):
            call_info['topic'] = kwargs.get('topic')

        self.stubs.Set(self.driver.intercell_rpcapi,
                       'fanout_cast_to_server', _fake_fanout_cast_to_server)

        self.driver.send_message_to_cell(cell_state, message)
        self.assertEqual('cells.intercell42.fake-message-type',
                         call_info['topic'])

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


class ParseTransportURLTestCase(test.NoDBTestCase):
    def test_bad_scheme(self):
        url = "bad:///"
        self.assertRaises(ValueError, rpc_driver.parse_transport_url, url)

    def test_query_string(self):
        url = "rabbit://u:p@h:10/virtual?ssl=1"
        self.assertRaises(ValueError, rpc_driver.parse_transport_url, url)

    def test_query_string_old_urlparse(self):
        # Test parse_transport_url with urlparse.urlparse behaving as in python
        # 2.7.3 or below. See https://bugs.launchpad.net/nova/+bug/1202149
        url = "rabbit://u:p@h:10/virtual?ssl=1"

        parse_result = urlparse.ParseResult(
            scheme='rabbit', netloc='u:p@h:10', path='/virtual?ssl=1',
            params='', query='', fragment=''
        )

        self.mox.StubOutWithMock(urlparse, 'urlparse')
        urlparse.urlparse(url).AndReturn(parse_result)
        self.mox.ReplayAll()

        self.assertRaises(ValueError, rpc_driver.parse_transport_url, url)

    def test_query_string_new_urlparse(self):
        # Test parse_transport_url with urlparse.urlparse behaving as in python
        # 2.7.4 or above. See https://bugs.launchpad.net/nova/+bug/1202149
        url = "rabbit://u:p@h:10/virtual?ssl=1"

        parse_result = urlparse.ParseResult(
            scheme='rabbit', netloc='u:p@h:10', path='/virtual',
            params='', query='ssl=1', fragment=''
        )

        self.mox.StubOutWithMock(urlparse, 'urlparse')
        urlparse.urlparse(url).AndReturn(parse_result)
        self.mox.ReplayAll()

        self.assertRaises(ValueError, rpc_driver.parse_transport_url, url)

    def test_empty(self):
        url = "rabbit:"

        result = rpc_driver.parse_transport_url(url)

        self.assertEqual(result, {
            'username': None,
            'password': None,
            'hostname': None,
            'port': None,
            'virtual_host': None,
        })

    def test_normal_parsing(self):
        url = "rabbit://us%65r:p%61ss@host.example.com:10/virtual%5fhost"

        result = rpc_driver.parse_transport_url(url)

        self.assertEqual(result, {
            'username': 'user',
            'password': 'pass',
            'hostname': 'host.example.com',
            'port': 10,
            'virtual_host': 'virtual_host',
        })

    def test_normal_ipv6_parsing(self):
        url = "rabbit://us%65r:p%61ss@[ffff::1]:10/virtual%5fhost"

        result = rpc_driver.parse_transport_url(url)

        self.assertEqual(result, {
            'username': 'user',
            'password': 'pass',
            'hostname': 'ffff::1',
            'port': 10,
            'virtual_host': 'virtual_host',
        })

    def test_normal_parsing_no_port(self):
        url = "rabbit://us%65r:p%61ss@host.example.com/virtual%5fhost"

        result = rpc_driver.parse_transport_url(url)

        self.assertEqual(result, {
            'username': 'user',
            'password': 'pass',
            'hostname': 'host.example.com',
            'port': None,
            'virtual_host': 'virtual_host',
        })

    def test_normal_ipv6_parsing_no_port(self):
        url = "rabbit://us%65r:p%61ss@[ffff::1]/virtual%5fhost"

        result = rpc_driver.parse_transport_url(url)

        self.assertEqual(result, {
            'username': 'user',
            'password': 'pass',
            'hostname': 'ffff::1',
            'port': None,
            'virtual_host': 'virtual_host',
        })

    def test_invalid_ipv6_parsing(self):
        url = "rabbit://user:pass@[ffff::1/virtual_host"
        self.assertRaises(ValueError, rpc_driver.parse_transport_url, url)


class UnparseTransportURLTestCase(test.NoDBTestCase):
    def test_empty(self):
        result = rpc_driver.unparse_transport_url({})

        self.assertEqual(result, "rabbit:///")

    def test_username_only(self):
        result = rpc_driver.unparse_transport_url({'username': 'user/'})

        self.assertEqual(result, "rabbit://user%2F@/")

    def test_password_only(self):
        result = rpc_driver.unparse_transport_url({'password': 'pass/'})

        self.assertEqual(result, "rabbit://:pass%2F@/")

    def test_hostname_only(self):
        result = rpc_driver.unparse_transport_url({'hostname': 'example.com'})

        self.assertEqual(result, "rabbit://example.com/")

    def test_hostname_v6_only(self):
        result = rpc_driver.unparse_transport_url({'hostname': 'ffff::1'})

        self.assertEqual(result, "rabbit://[ffff::1]/")

    def test_port_only(self):
        result = rpc_driver.unparse_transport_url({'port': 2345})

        self.assertEqual(result, "rabbit://:2345/")

    def test_virtual_host_only(self):
        result = rpc_driver.unparse_transport_url({'virtual_host': 'virtual/'})

        self.assertEqual(result, "rabbit:///virtual%2F")

    def test_complete_secure(self):
        transport = {
            'username': 'user',
            'password': 'pass',
            'hostname': 'example.com',
            'port': 2345,
            'virtual_host': 'virtual',
        }

        result = rpc_driver.unparse_transport_url(transport)

        self.assertEqual(result, "rabbit://user:pass@example.com:2345/virtual")

    def test_complete_insecure(self):
        transport = {
            'username': 'user',
            'password': 'pass',
            'hostname': 'example.com',
            'port': 2345,
            'virtual_host': 'virtual',
        }

        result = rpc_driver.unparse_transport_url(transport, False)

        self.assertEqual(result, "rabbit://user@example.com:2345/virtual")
