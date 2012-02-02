# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012, Red Hat, Inc.
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
Unit Tests for remote procedure calls using qpid
"""

import mox

from nova import context
from nova import log as logging
from nova import test
import nova.rpc.amqp as rpc_amqp

try:
    import qpid
    from nova.rpc import impl_qpid
except ImportError:
    qpid = None
    impl_qpid = None


LOG = logging.getLogger('nova.tests.rpc')


class RpcQpidTestCase(test.TestCase):
    """
    Exercise the public API of impl_qpid utilizing mox.

    This set of tests utilizes mox to replace the Qpid objects and ensures
    that the right operations happen on them when the various public rpc API
    calls are exercised.  The API calls tested here include:

        nova.rpc.create_connection()
        nova.rpc.common.Connection.create_consumer()
        nova.rpc.common.Connection.close()
        nova.rpc.cast()
        nova.rpc.fanout_cast()
        nova.rpc.call()
        nova.rpc.multicall()
    """

    def setUp(self):
        self.mocker = mox.Mox()

        self.mock_connection = None
        self.mock_session = None
        self.mock_sender = None
        self.mock_receiver = None

        if qpid:
            self.orig_connection = qpid.messaging.Connection
            self.orig_session = qpid.messaging.Session
            self.orig_sender = qpid.messaging.Sender
            self.orig_receiver = qpid.messaging.Receiver
            qpid.messaging.Connection = lambda *_x, **_y: self.mock_connection
            qpid.messaging.Session = lambda *_x, **_y: self.mock_session
            qpid.messaging.Sender = lambda *_x, **_y: self.mock_sender
            qpid.messaging.Receiver = lambda *_x, **_y: self.mock_receiver

        super(RpcQpidTestCase, self).setUp()

    def tearDown(self):
        if qpid:
            qpid.messaging.Connection = self.orig_connection
            qpid.messaging.Session = self.orig_session
            qpid.messaging.Sender = self.orig_sender
            qpid.messaging.Receiver = self.orig_receiver

        self.mocker.ResetAll()

        super(RpcQpidTestCase, self).tearDown()

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_create_connection(self):
        self.mock_connection = self.mocker.CreateMock(self.orig_connection)
        self.mock_session = self.mocker.CreateMock(self.orig_session)

        self.mock_connection.opened().AndReturn(False)
        self.mock_connection.open()
        self.mock_connection.session().AndReturn(self.mock_session)
        self.mock_connection.close()

        self.mocker.ReplayAll()

        connection = impl_qpid.create_connection()
        connection.close()

        self.mocker.VerifyAll()

    def _test_create_consumer(self, fanout):
        self.mock_connection = self.mocker.CreateMock(self.orig_connection)
        self.mock_session = self.mocker.CreateMock(self.orig_session)
        self.mock_receiver = self.mocker.CreateMock(self.orig_receiver)

        self.mock_connection.opened().AndReturn(False)
        self.mock_connection.open()
        self.mock_connection.session().AndReturn(self.mock_session)
        if fanout:
            # The link name includes a UUID, so match it with a regex.
            expected_address = mox.Regex(r'^impl_qpid_test_fanout ; '
                '{"node": {"x-declare": {"auto-delete": true, "durable": '
                'false, "type": "fanout"}, "type": "topic"}, "create": '
                '"always", "link": {"x-declare": {"auto-delete": true, '
                '"exclusive": true, "durable": false}, "durable": true, '
                '"name": "impl_qpid_test_fanout_.*"}}$')
        else:
            expected_address = ('nova/impl_qpid_test ; {"node": {"x-declare": '
                '{"auto-delete": true, "durable": true}, "type": "topic"}, '
                '"create": "always", "link": {"x-declare": {"auto-delete": '
                'true, "exclusive": false, "durable": false}, "durable": '
                'true, "name": "impl_qpid_test"}}')
        self.mock_session.receiver(expected_address).AndReturn(
                                                        self.mock_receiver)
        self.mock_receiver.capacity = 1
        self.mock_connection.close()

        self.mocker.ReplayAll()

        connection = impl_qpid.create_connection()
        connection.create_consumer("impl_qpid_test",
                                   lambda *_x, **_y: None,
                                   fanout)
        connection.close()

        self.mocker.VerifyAll()

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_create_consumer(self):
        self._test_create_consumer(fanout=False)

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_create_consumer_fanout(self):
        self._test_create_consumer(fanout=True)

    def _test_cast(self, fanout):
        self.mock_connection = self.mocker.CreateMock(self.orig_connection)
        self.mock_session = self.mocker.CreateMock(self.orig_session)
        self.mock_sender = self.mocker.CreateMock(self.orig_sender)

        self.mock_connection.opened().AndReturn(False)
        self.mock_connection.open()
        self.mock_connection.session().AndReturn(self.mock_session)
        if fanout:
            expected_address = ('impl_qpid_test_fanout ; '
                '{"node": {"x-declare": {"auto-delete": true, '
                '"durable": false, "type": "fanout"}, '
                '"type": "topic"}, "create": "always"}')
        else:
            expected_address = ('nova/impl_qpid_test ; {"node": {"x-declare": '
                '{"auto-delete": true, "durable": false}, "type": "topic"}, '
                '"create": "always"}')
        self.mock_session.sender(expected_address).AndReturn(self.mock_sender)
        self.mock_sender.send(mox.IgnoreArg())
        # This is a pooled connection, so instead of closing it, it gets reset,
        # which is just creating a new session on the connection.
        self.mock_session.close()
        self.mock_connection.session().AndReturn(self.mock_session)

        self.mocker.ReplayAll()

        try:
            ctx = context.RequestContext("user", "project")

            if fanout:
                impl_qpid.fanout_cast(ctx, "impl_qpid_test",
                               {"method": "test_method", "args": {}})
            else:
                impl_qpid.cast(ctx, "impl_qpid_test",
                               {"method": "test_method", "args": {}})

            self.mocker.VerifyAll()
        finally:
            while rpc_amqp.ConnectionContext._connection_pool.free_items:
                # Pull the mock connection object out of the connection pool so
                # that it doesn't mess up other test cases.
                rpc_amqp.ConnectionContext._connection_pool.get()

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_cast(self):
        self._test_cast(fanout=False)

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_fanout_cast(self):
        self._test_cast(fanout=True)

    def _test_call(self, multi):
        self.mock_connection = self.mocker.CreateMock(self.orig_connection)
        self.mock_session = self.mocker.CreateMock(self.orig_session)
        self.mock_sender = self.mocker.CreateMock(self.orig_sender)
        self.mock_receiver = self.mocker.CreateMock(self.orig_receiver)

        self.mock_connection.opened().AndReturn(False)
        self.mock_connection.open()
        self.mock_connection.session().AndReturn(self.mock_session)
        rcv_addr = mox.Regex(r'^.*/.* ; {"node": {"x-declare": {"auto-delete":'
                   ' true, "durable": true, "type": "direct"}, "type": '
                   '"topic"}, "create": "always", "link": {"x-declare": '
                   '{"auto-delete": true, "exclusive": true, "durable": '
                   'false}, "durable": true, "name": ".*"}}')
        self.mock_session.receiver(rcv_addr).AndReturn(self.mock_receiver)
        self.mock_receiver.capacity = 1
        send_addr = ('nova/impl_qpid_test ; {"node": {"x-declare": '
            '{"auto-delete": true, "durable": false}, "type": "topic"}, '
            '"create": "always"}')
        self.mock_session.sender(send_addr).AndReturn(self.mock_sender)
        self.mock_sender.send(mox.IgnoreArg())

        self.mock_session.next_receiver(timeout=mox.IsA(int)).AndReturn(
                                                        self.mock_receiver)
        self.mock_receiver.fetch().AndReturn(qpid.messaging.Message(
                        {"result": "foo", "failure": False, "ending": False}))
        if multi:
            self.mock_session.next_receiver(timeout=mox.IsA(int)).AndReturn(
                                                        self.mock_receiver)
            self.mock_receiver.fetch().AndReturn(
                            qpid.messaging.Message(
                                {"result": "bar", "failure": False,
                                 "ending": False}))
            self.mock_session.next_receiver(timeout=mox.IsA(int)).AndReturn(
                                                        self.mock_receiver)
            self.mock_receiver.fetch().AndReturn(
                            qpid.messaging.Message(
                                {"result": "baz", "failure": False,
                                 "ending": False}))
        self.mock_session.next_receiver(timeout=mox.IsA(int)).AndReturn(
                                                        self.mock_receiver)
        self.mock_receiver.fetch().AndReturn(qpid.messaging.Message(
                        {"failure": False, "ending": True}))
        self.mock_session.close()
        self.mock_connection.session().AndReturn(self.mock_session)

        self.mocker.ReplayAll()

        try:
            ctx = context.RequestContext("user", "project")

            if multi:
                method = impl_qpid.multicall
            else:
                method = impl_qpid.call

            res = method(ctx, "impl_qpid_test",
                           {"method": "test_method", "args": {}})

            if multi:
                self.assertEquals(list(res), ["foo", "bar", "baz"])
            else:
                self.assertEquals(res, "foo")

            self.mocker.VerifyAll()
        finally:
            while rpc_amqp.ConnectionContext._connection_pool.free_items:
                # Pull the mock connection object out of the connection pool so
                # that it doesn't mess up other test cases.
                rpc_amqp.ConnectionContext._connection_pool.get()

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_call(self):
        self._test_call(multi=False)

    @test.skip_if(qpid is None, "Test requires qpid")
    def test_multicall(self):
        self._test_call(multi=True)


#
#from nova.tests.rpc import common
#
# Qpid does not have a handy in-memory transport like kombu, so it's not
# terribly straight forward to take advantage of the common unit tests.
# However, at least at the time of this writing, the common unit tests all pass
# with qpidd running.
#
# class RpcQpidCommonTestCase(common._BaseRpcTestCase):
#     def setUp(self):
#         self.rpc = impl_qpid
#         super(RpcQpidCommonTestCase, self).setUp()
#
#     def tearDown(self):
#         super(RpcQpidCommonTestCase, self).tearDown()
#
