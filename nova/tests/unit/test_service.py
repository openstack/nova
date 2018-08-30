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

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_service import service as _service
import testtools

from nova import exception
from nova import manager
from nova import objects
from nova.objects import base as obj_base
from nova import rpc
from nova import service
from nova import test
from nova.tests.unit import utils

test_service_opts = [
    cfg.HostAddressOpt("test_service_listen",
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


class ServiceManagerTestCase(test.NoDBTestCase):
    """Test cases for Services."""

    def test_message_gets_to_manager(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'nova.tests.unit.test_service.FakeManager')
        self.assertEqual('manager', serv.test_method())

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'nova.tests.unit.test_service.FakeManager')
        self.assertEqual('service', serv.test_method())

    def test_service_with_min_down_time(self):
        # TODO(hanlind): This really tests code in the servicegroup api.
        self.flags(service_down_time=10, report_interval=10)
        service.Service('test',
                        'test',
                        'test',
                        'nova.tests.unit.test_service.FakeManager')
        self.assertEqual(25, CONF.service_down_time)


class ServiceTestCase(test.NoDBTestCase):
    """Test cases for Services."""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.host = 'foo'
        self.binary = 'nova-compute'
        self.topic = 'fake'

    def test_create(self):

        # NOTE(vish): Create was moved out of mox replay to make sure that
        #             the looping calls are created in StartService.
        app = service.Service.create(host=self.host, binary=self.binary,
                topic=self.topic,
                manager='nova.tests.unit.test_service.FakeManager')

        self.assertTrue(app)

    def test_repr(self):
        # Test if a Service object is correctly represented, for example in
        # log files.
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        exp = "<Service: host=foo, binary=nova-compute, " \
              "manager_class_name=nova.tests.unit.test_service.FakeManager>"
        self.assertEqual(exp, repr(serv))

    @mock.patch.object(objects.Service, 'create')
    @mock.patch.object(objects.Service, 'get_by_host_and_binary')
    def test_init_and_start_hooks(self, mock_get_by_host_and_binary,
                                                        mock_create):
        mock_get_by_host_and_binary.return_value = None
        mock_manager = mock.Mock(target=None)
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.manager = mock_manager
        serv.manager.service_name = self.topic
        serv.manager.additional_endpoints = []
        serv.start()
        # init_host is called before any service record is created
        serv.manager.init_host.assert_called_once_with()
        mock_get_by_host_and_binary.assert_called_once_with(mock.ANY,
                                                       self.host, self.binary)
        mock_create.assert_called_once_with()
        # pre_start_hook is called after service record is created,
        # but before RPC consumer is created
        serv.manager.pre_start_hook.assert_called_once_with()
        # post_start_hook is called after RPC consumer is created.
        serv.manager.post_start_hook.assert_called_once_with()

    @mock.patch('nova.conductor.api.API.wait_until_ready')
    def test_init_with_indirection_api_waits(self, mock_wait):
        obj_base.NovaObject.indirection_api = mock.MagicMock()

        with mock.patch.object(FakeManager, '__init__') as init:
            def check(*a, **k):
                self.assertTrue(mock_wait.called)

            init.side_effect = check
            service.Service(self.host, self.binary, self.topic,
                            'nova.tests.unit.test_service.FakeManager')
            self.assertTrue(init.called)
        mock_wait.assert_called_once_with(mock.ANY)

    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    def test_start_updates_version(self, mock_get_by_host_and_binary):
        # test that the service version gets updated on services startup
        service_obj = mock.Mock()
        service_obj.binary = 'fake-binary'
        service_obj.host = 'fake-host'
        service_obj.version = -42
        mock_get_by_host_and_binary.return_value = service_obj

        serv = service.Service(self.host, self.binary, self.topic,
                              'nova.tests.unit.test_service.FakeManager')
        serv.start()

        # test service version got updated and saved:
        self.assertEqual(1, service_obj.save.call_count)
        self.assertEqual(objects.service.SERVICE_VERSION, service_obj.version)

    @mock.patch.object(objects.Service, 'create')
    @mock.patch.object(objects.Service, 'get_by_host_and_binary')
    def _test_service_check_create_race(self, ex,
                                         mock_get_by_host_and_binary,
                                         mock_create):

        mock_manager = mock.Mock()
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')

        mock_get_by_host_and_binary.side_effect = [None,
                                                   test.TestingException()]
        mock_create.side_effect = ex
        serv.manager = mock_manager
        self.assertRaises(test.TestingException, serv.start)
        serv.manager.init_host.assert_called_with()
        mock_get_by_host_and_binary.assert_has_calls([
                mock.call(mock.ANY, self.host, self.binary),
                mock.call(mock.ANY, self.host, self.binary)])
        mock_create.assert_called_once_with()

    def test_service_check_create_race_topic_exists(self):
        ex = exception.ServiceTopicExists(host='foo', topic='bar')
        self._test_service_check_create_race(ex)

    def test_service_check_create_race_binary_exists(self):
        ex = exception.ServiceBinaryExists(host='foo', binary='bar')
        self._test_service_check_create_race(ex)

    @mock.patch.object(objects.Service, 'create')
    @mock.patch.object(objects.Service, 'get_by_host_and_binary')
    @mock.patch.object(_service.Service, 'stop')
    def test_parent_graceful_shutdown(self, mock_stop,
                                      mock_get_by_host_and_binary,
                                      mock_create):
        mock_get_by_host_and_binary.return_value = None
        mock_manager = mock.Mock(target=None)
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.manager = mock_manager
        serv.manager.service_name = self.topic
        serv.manager.additional_endpoints = []
        serv.start()
        serv.manager.init_host.assert_called_once_with()
        mock_get_by_host_and_binary.assert_called_once_with(mock.ANY,
                                                            self.host,
                                                            self.binary)
        mock_create.assert_called_once_with()
        serv.manager.pre_start_hook.assert_called_once_with()
        serv.manager.post_start_hook.assert_called_once_with()
        serv.stop()
        mock_stop.assert_called_once_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    def test_parent_graceful_shutdown_with_cleanup_host(
            self, mock_svc_get_by_host_and_binary, mock_API):
        mock_manager = mock.Mock(target=None)

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
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_waits_for_rpcserver(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        serv.stop()
        serv.rpcserver.start.assert_called_once_with()
        serv.rpcserver.stop.assert_called_once_with()
        serv.rpcserver.wait.assert_called_once_with()

    def test_reset(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        with mock.patch.object(serv.manager, 'reset') as mock_reset:
            serv.reset()
            mock_reset.assert_called_once_with()


class TestWSGIService(test.NoDBTestCase):

    def setUp(self):
        super(TestWSGIService, self).setUp()
        self.stub_out('nova.api.wsgi.Loader.load_app',
                      lambda *a, **kw: mock.MagicMock())

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.objects.Service.create')
    def test_service_start_creates_record(self, mock_create, mock_get):
        mock_get.return_value = None
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertTrue(mock_create.called)

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.objects.Service.create')
    def test_service_start_does_not_create_record(self, mock_create, mock_get):
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertFalse(mock_create.called)

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_service_random_port(self, mock_get):
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

    def test_openstack_compute_api_workers_set_default(self):
        test_service = service.WSGIService("openstack_compute_api_v2")
        self.assertEqual(test_service.workers, processutils.get_worker_count())

    def test_openstack_compute_api_workers_set_good_user_setting(self):
        CONF.set_override('osapi_compute_workers', 8)
        test_service = service.WSGIService("openstack_compute_api_v2")
        self.assertEqual(test_service.workers, 8)

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_service_random_port_with_ipv6(self, mock_get):
        CONF.set_default("test_service_listen", "::1")
        test_service = service.WSGIService("test_service")
        test_service.start()
        self.assertEqual("::1", test_service.host)
        self.assertNotEqual(0, test_service.port)
        test_service.stop()

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_reset_pool_size_to_default(self, mock_get):
        test_service = service.WSGIService("test_service")
        test_service.start()

        # Stopping the service, which in turn sets pool size to 0
        test_service.stop()
        self.assertEqual(test_service.server._pool.size, 0)

        # Resetting pool size to default
        test_service.reset()
        test_service.start()
        self.assertEqual(test_service.server._pool.size,
                         CONF.wsgi.default_pool_size)


class TestLauncher(test.NoDBTestCase):

    @mock.patch.object(_service, 'launch')
    def test_launch_app(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service)
        mock_launch.assert_called_once_with(mock.ANY,
                                            mock.sentinel.service,
                                            workers=None,
                                            restart_method='mutate')

    @mock.patch.object(_service, 'launch')
    def test_launch_app_with_workers(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service, workers=mock.sentinel.workers)
        mock_launch.assert_called_once_with(mock.ANY,
                                            mock.sentinel.service,
                                            workers=mock.sentinel.workers,
                                            restart_method='mutate')

    @mock.patch.object(_service, 'launch')
    def test_launch_app_more_than_once_raises(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service)
        self.assertRaises(RuntimeError, service.serve, mock.sentinel.service)
