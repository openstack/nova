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

import sys
import testtools

import mox
from oslo.config import cfg

from nova import context
from nova import db
from nova import exception
from nova import manager
from nova import service
from nova import test
from nova.tests import utils
from nova import wsgi

test_service_opts = [
    cfg.StrOpt("fake_manager",
               default="nova.tests.test_service.FakeManager",
               help="Manager for testing"),
    cfg.StrOpt("test_service_listen",
               default='127.0.0.1',
               help="Host to bind test service to"),
    cfg.IntOpt("test_service_listen_port",
               default=0,
               help="Port number to bind test service to"),
    ]

CONF = cfg.CONF
CONF.register_opts(test_service_opts)


class FakeManager(manager.Manager):
    """Fake manager for tests."""
    def test_method(self):
        return 'manager'


class ExtendedService(service.Service):
    def test_method(self):
        return 'service'


class ServiceManagerTestCase(test.TestCase):
    """Test cases for Services."""

    def test_message_gets_to_manager(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'nova.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'manager')

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'nova.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'service')


class ServiceFlagsTestCase(test.TestCase):
    def test_service_enabled_on_create_based_on_flag(self):
        self.flags(enable_new_services=True)
        host = 'foo'
        binary = 'nova-fake'
        app = service.Service.create(host=host, binary=binary)
        app.start()
        app.stop()
        ref = db.service_get(context.get_admin_context(), app.service_id)
        db.service_destroy(context.get_admin_context(), app.service_id)
        self.assert_(not ref['disabled'])

    def test_service_disabled_on_create_based_on_flag(self):
        self.flags(enable_new_services=False)
        host = 'foo'
        binary = 'nova-fake'
        app = service.Service.create(host=host, binary=binary)
        app.start()
        app.stop()
        ref = db.service_get(context.get_admin_context(), app.service_id)
        db.service_destroy(context.get_admin_context(), app.service_id)
        self.assert_(ref['disabled'])


class ServiceTestCase(test.TestCase):
    """Test cases for Services."""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.host = 'foo'
        self.binary = 'nova-fake'
        self.topic = 'fake'
        self.mox.StubOutWithMock(db, 'service_create')
        self.mox.StubOutWithMock(db, 'service_get_by_args')
        self.flags(use_local=True, group='conductor')

    def test_create(self):

        # NOTE(vish): Create was moved out of mox replay to make sure that
        #             the looping calls are created in StartService.
        app = service.Service.create(host=self.host, binary=self.binary,
                topic=self.topic)

        self.assert_(app)

    def _service_start_mocks(self):
        service_create = {'host': self.host,
                          'binary': self.binary,
                          'topic': self.topic,
                          'report_count': 0}
        service_ref = {'host': self.host,
                          'binary': self.binary,
                          'topic': self.topic,
                          'report_count': 0,
                          'id': 1}

        db.service_get_by_args(mox.IgnoreArg(),
                self.host, self.binary).AndRaise(exception.NotFound())
        db.service_create(mox.IgnoreArg(),
                service_create).AndReturn(service_ref)
        return service_ref

    def test_init_and_start_hooks(self):
        self.manager_mock = self.mox.CreateMock(FakeManager)
        self.mox.StubOutWithMock(sys.modules[__name__],
                'FakeManager', use_mock_anything=True)
        self.mox.StubOutWithMock(self.manager_mock, 'init_host')
        self.mox.StubOutWithMock(self.manager_mock, 'pre_start_hook')
        self.mox.StubOutWithMock(self.manager_mock, 'create_rpc_dispatcher')
        self.mox.StubOutWithMock(self.manager_mock, 'post_start_hook')

        FakeManager(host=self.host).AndReturn(self.manager_mock)

        # init_host is called before any service record is created
        self.manager_mock.init_host()
        self._service_start_mocks()
        # pre_start_hook is called after service record is created,
        # but before RPC consumer is created
        self.manager_mock.pre_start_hook()
        self.manager_mock.create_rpc_dispatcher(None)
        # post_start_hook is called after RPC consumer is created.
        self.manager_mock.post_start_hook()

        self.mox.ReplayAll()

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.test_service.FakeManager')
        serv.start()


class TestWSGIService(test.TestCase):

    def setUp(self):
        super(TestWSGIService, self).setUp()
        self.stubs.Set(wsgi.Loader, "load_app", mox.MockAnything())

    def test_service_random_port(self):
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertNotEqual(0, test_service.port)
        test_service.stop()

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_service_random_port_with_ipv6(self):
        CONF.set_default("test_service_listen", "::1")
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertEqual("::1", test_service.host)
        self.assertNotEqual(0, test_service.port)
        test_service.stop()


class TestLauncher(test.TestCase):

    def setUp(self):
        super(TestLauncher, self).setUp()
        self.stubs.Set(wsgi.Loader, "load_app", mox.MockAnything())
        self.service = service.WSGIService("test_service")

    def test_launch_app(self):
        service.serve(self.service)
        self.assertNotEquals(0, self.service.port)
        service._launcher.stop()
