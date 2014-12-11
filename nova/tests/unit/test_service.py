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

import mock
from mox3 import mox
from oslo.config import cfg
from oslo_concurrency import processutils
import testtools

from nova import context
from nova import db
from nova import exception
from nova import manager
from nova.openstack.common import service as _service
from nova import rpc
from nova import service
from nova import test
from nova.tests.unit import utils
from nova import wsgi

test_service_opts = [
    cfg.StrOpt("fake_manager",
               default="nova.tests.unit.test_service.FakeManager",
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
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'manager')

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'service')

    def test_service_with_min_down_time(self):
        CONF.set_override('service_down_time', 10)
        CONF.set_override('report_interval', 10)
        serv = service.Service('test',
                               'test',
                               'test',
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        self.assertEqual(CONF.service_down_time, 25)


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
        self.assertFalse(ref['disabled'])

    def test_service_disabled_on_create_based_on_flag(self):
        self.flags(enable_new_services=False)
        host = 'foo'
        binary = 'nova-fake'
        app = service.Service.create(host=host, binary=binary)
        app.start()
        app.stop()
        ref = db.service_get(context.get_admin_context(), app.service_id)
        db.service_destroy(context.get_admin_context(), app.service_id)
        self.assertTrue(ref['disabled'])


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

        self.assertTrue(app)

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
        self.mox.StubOutWithMock(self.manager_mock, 'post_start_hook')

        FakeManager(host=self.host).AndReturn(self.manager_mock)

        self.manager_mock.service_name = self.topic
        self.manager_mock.additional_endpoints = []

        # init_host is called before any service record is created
        self.manager_mock.init_host()
        self._service_start_mocks()
        # pre_start_hook is called after service record is created,
        # but before RPC consumer is created
        self.manager_mock.pre_start_hook()
        # post_start_hook is called after RPC consumer is created.
        self.manager_mock.post_start_hook()

        self.mox.ReplayAll()

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()

    def _test_service_check_create_race(self, ex):
        self.manager_mock = self.mox.CreateMock(FakeManager)
        self.mox.StubOutWithMock(sys.modules[__name__], 'FakeManager',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(self.manager_mock, 'init_host')
        self.mox.StubOutWithMock(self.manager_mock, 'pre_start_hook')
        self.mox.StubOutWithMock(self.manager_mock, 'post_start_hook')

        FakeManager(host=self.host).AndReturn(self.manager_mock)

        # init_host is called before any service record is created
        self.manager_mock.init_host()

        db.service_get_by_args(mox.IgnoreArg(), self.host, self.binary
                               ).AndRaise(exception.NotFound)
        db.service_create(mox.IgnoreArg(), mox.IgnoreArg()
                          ).AndRaise(ex)

        class TestException(Exception):
            pass

        db.service_get_by_args(mox.IgnoreArg(), self.host, self.binary
                               ).AndRaise(TestException)

        self.mox.ReplayAll()

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        self.assertRaises(TestException, serv.start)

    def test_service_check_create_race_topic_exists(self):
        ex = exception.ServiceTopicExists(host='foo', topic='bar')
        self._test_service_check_create_race(ex)

    def test_service_check_create_race_binary_exists(self):
        ex = exception.ServiceBinaryExists(host='foo', binary='bar')
        self._test_service_check_create_race(ex)

    def test_parent_graceful_shutdown(self):
        self.manager_mock = self.mox.CreateMock(FakeManager)
        self.mox.StubOutWithMock(sys.modules[__name__],
                'FakeManager', use_mock_anything=True)
        self.mox.StubOutWithMock(self.manager_mock, 'init_host')
        self.mox.StubOutWithMock(self.manager_mock, 'pre_start_hook')
        self.mox.StubOutWithMock(self.manager_mock, 'post_start_hook')

        self.mox.StubOutWithMock(_service.Service, 'stop')

        FakeManager(host=self.host).AndReturn(self.manager_mock)

        self.manager_mock.service_name = self.topic
        self.manager_mock.additional_endpoints = []

        # init_host is called before any service record is created
        self.manager_mock.init_host()
        self._service_start_mocks()
        # pre_start_hook is called after service record is created,
        # but before RPC consumer is created
        self.manager_mock.pre_start_hook()
        # post_start_hook is called after RPC consumer is created.
        self.manager_mock.post_start_hook()

        _service.Service.stop()

        self.mox.ReplayAll()

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()

        serv.stop()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.conductor.api.LocalAPI.service_get_by_args')
    def test_parent_graceful_shutdown_with_cleanup_host(self,
                                                        mock_svc_get_by_args,
                                                        mock_API):
        mock_svc_get_by_args.return_value = {'id': 'some_value'}
        mock_manager = mock.Mock()

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')

        serv.manager = mock_manager
        serv.manager.additional_endpoints = []

        serv.start()
        serv.manager.init_host.assert_called_with()

        serv.stop()
        serv.manager.cleanup_host.assert_called_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.conductor.api.LocalAPI.service_get_by_args')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_waits_for_rpcserver(
            self, mock_rpc, mock_svc_get_by_args, mock_API):
        mock_svc_get_by_args.return_value = {'id': 'some_value'}
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        serv.stop()
        serv.rpcserver.start.assert_called_once_with()
        serv.rpcserver.stop.assert_called_once_with()
        serv.rpcserver.wait.assert_called_once_with()


class TestWSGIService(test.TestCase):

    def setUp(self):
        super(TestWSGIService, self).setUp()
        self.stubs.Set(wsgi.Loader, "load_app", mox.MockAnything())

    def test_service_random_port(self):
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertNotEqual(0, test_service.port)
        test_service.stop()

    def test_workers_set_default(self):
        test_service = service.WSGIService("osapi_compute")
        self.assertEqual(test_service.workers, processutils.get_worker_count())

    def test_workers_set_good_user_setting(self):
        CONF.set_override('osapi_compute_workers', 8)
        test_service = service.WSGIService("osapi_compute")
        self.assertEqual(test_service.workers, 8)

    def test_workers_set_zero_user_setting(self):
        CONF.set_override('osapi_compute_workers', 0)
        test_service = service.WSGIService("osapi_compute")
        # If a value less than 1 is used, defaults to number of procs available
        self.assertEqual(test_service.workers, processutils.get_worker_count())

    def test_service_start_with_illegal_workers(self):
        CONF.set_override("osapi_compute_workers", -1)
        self.assertRaises(exception.InvalidInput,
                          service.WSGIService, "osapi_compute")

    def test_openstack_compute_api_workers_set_default(self):
        test_service = service.WSGIService("openstack_compute_api_v2")
        self.assertEqual(test_service.workers, processutils.get_worker_count())

    def test_openstack_compute_api_workers_set_good_user_setting(self):
        CONF.set_override('osapi_compute_workers', 8)
        test_service = service.WSGIService("openstack_compute_api_v2")
        self.assertEqual(test_service.workers, 8)

    def test_openstack_compute_api_workers_set_zero_user_setting(self):
        CONF.set_override('osapi_compute_workers', 0)
        test_service = service.WSGIService("openstack_compute_api_v2")
        # If a value less than 1 is used, defaults to number of procs available
        self.assertEqual(test_service.workers, processutils.get_worker_count())

    def test_openstack_compute_api_service_start_with_illegal_workers(self):
        CONF.set_override("osapi_compute_workers", -1)
        self.assertRaises(exception.InvalidInput,
                          service.WSGIService, "openstack_compute_api_v2")

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_service_random_port_with_ipv6(self):
        CONF.set_default("test_service_listen", "::1")
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertEqual("::1", test_service.host)
        self.assertNotEqual(0, test_service.port)
        test_service.stop()

    def test_reset_pool_size_to_default(self):
        test_service = service.WSGIService("test_service")
        test_service.start()

        # Stopping the service, which in turn sets pool size to 0
        test_service.stop()
        self.assertEqual(test_service.server._pool.size, 0)

        # Resetting pool size to default
        test_service.reset()
        test_service.start()
        self.assertEqual(test_service.server._pool.size,
                         CONF.wsgi_default_pool_size)


class TestLauncher(test.TestCase):

    def setUp(self):
        super(TestLauncher, self).setUp()
        self.stubs.Set(wsgi.Loader, "load_app", mox.MockAnything())
        self.service = service.WSGIService("test_service")

    def test_launch_app(self):
        service.serve(self.service)
        self.assertNotEqual(0, self.service.port)
        service._launcher.stop()
