# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Unit Tests for remote procedure calls using queue
"""

import logging

import mox
from twisted.internet import defer

from nova import exception
from nova import flags
from nova import rpc
from nova import test
from nova import service
from nova import manager

FLAGS = flags.FLAGS

flags.DEFINE_string("fake_manager", "nova.tests.service_unittest.FakeManager",
                    "Manager for testing")

class FakeManager(manager.Manager):
    """Fake manager for tests"""
    pass

class ServiceTestCase(test.BaseTestCase):
    """Test cases for rpc"""
    def setUp(self):  # pylint: disable=C0103
        super(ServiceTestCase, self).setUp()
        self.mox.StubOutWithMock(service, 'db')

    def test_create(self):
        self.mox.StubOutWithMock(rpc, 'AdapterConsumer', use_mock_anything=True)
        self.mox.StubOutWithMock(
                service.task, 'LoopingCall', use_mock_anything=True)
        rpc.AdapterConsumer(connection=mox.IgnoreArg(),
                            topic='fake',
                            proxy=mox.IsA(service.Service)
                            ).AndReturn(rpc.AdapterConsumer)

        rpc.AdapterConsumer(connection=mox.IgnoreArg(),
                            topic='fake.%s' % FLAGS.node_name,
                            proxy=mox.IsA(service.Service)
                            ).AndReturn(rpc.AdapterConsumer)

        # Stub out looping call a bit needlessly since we don't have an easy
        # way to cancel it (yet) when the tests finishes
        service.task.LoopingCall(
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        service.task.LoopingCall)
        service.task.LoopingCall.start(interval=mox.IgnoreArg(),
                                       now=mox.IgnoreArg())

        rpc.AdapterConsumer.attach_to_twisted()
        rpc.AdapterConsumer.attach_to_twisted()
        self.mox.ReplayAll()

        app = service.Service.create(bin_name='nova-fake')
        self.assert_(app)

    # We're testing sort of weird behavior in how report_state decides
    # whether it is disconnected, it looks for a variable on itself called
    # 'model_disconnected' and report_state doesn't really do much so this
    # these are mostly just for coverage

    def test_report_state(self):
        node_name = 'foo'
        binary = 'bar'
        daemon_ref = {'node_name': node_name,
                      'binary': binary,
                      'report_count': 0,
                      'id': 1}
        service.db.__getattr__('report_state')
        service.db.daemon_get_by_args(None,
                                      node_name,
                                      binary).AndReturn(daemon_ref)
        service.db.daemon_update(None, daemon_ref['id'],
                                 mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        s = service.Service()
        rv = yield s.report_state(node_name, binary)


    def test_report_state_no_daemon(self):
        node_name = 'foo'
        binary = 'bar'
        daemon_create = {'node_name': node_name,
                      'binary': binary,
                      'report_count': 0}
        daemon_ref = {'node_name': node_name,
                      'binary': binary,
                      'report_count': 0,
                      'id': 1}

        service.db.__getattr__('report_state')
        service.db.daemon_get_by_args(None,
                                      node_name,
                                      binary).AndRaise(exception.NotFound())
        service.db.daemon_create(None, daemon_create).AndReturn(daemon_ref['id'])
        service.db.daemon_get(None, daemon_ref['id']).AndReturn(daemon_ref)
        service.db.daemon_update(None, daemon_ref['id'],
                                 mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        s = service.Service()
        rv = yield s.report_state(node_name, binary)


    def test_report_state_newly_disconnected(self):
        node_name = 'foo'
        binary = 'bar'
        daemon_ref = {'node_name': node_name,
                      'binary': binary,
                      'report_count': 0,
                      'id': 1}

        service.db.__getattr__('report_state')
        service.db.daemon_get_by_args(None,
                                      node_name,
                                      binary).AndRaise(Exception())

        self.mox.ReplayAll()
        s = service.Service()
        rv = yield s.report_state(node_name, binary)

        self.assert_(s.model_disconnected)


    def test_report_state_newly_connected(self):
        node_name = 'foo'
        binary = 'bar'
        daemon_ref = {'node_name': node_name,
                      'binary': binary,
                      'report_count': 0,
                      'id': 1}

        service.db.__getattr__('report_state')
        service.db.daemon_get_by_args(None,
                                      node_name,
                                      binary).AndReturn(daemon_ref)
        service.db.daemon_update(None, daemon_ref['id'],
                                 mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        s = service.Service()
        s.model_disconnected = True
        rv = yield s.report_state(node_name, binary)

        self.assert_(not s.model_disconnected)

