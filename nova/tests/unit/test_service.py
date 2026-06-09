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

import os.path
from unittest import mock

from oslo_config import cfg
import oslo_messaging as messaging
from oslo_service import service as _service

from nova import exception
from nova import manager
from nova import objects
from nova.objects import base as obj_base
from nova import rpc
from nova import service
from nova import test

test_service_opts = [
    cfg.HostAddressOpt("test_service_listen",
                       default='127.0.0.1',
                       help="Host to bind test service to"),
    cfg.IntOpt("test_service_listen_port",
               default=0,
               help="Port number to bind test service to"),
    ]
SSL_CERT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ssl_cert')
)

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
        self.addCleanup(serv.stop)
        serv.manager = mock_manager
        serv.manager.service_name = self.topic
        serv.manager.additional_endpoints = []
        serv.start()
        # init_host is called before any service record is created
        serv.manager.init_host.assert_called_once_with(None)
        mock_get_by_host_and_binary.assert_called_once_with(mock.ANY,
                                                       self.host, self.binary)
        mock_create.assert_called_once_with()
        # pre_start_hook is called after service record is created,
        # but before RPC consumer is created
        serv.manager.pre_start_hook.assert_called_once_with(
            serv.service_ref)
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
        service_obj.version = 42
        mock_get_by_host_and_binary.return_value = service_obj

        serv = service.Service(self.host, self.binary, self.topic,
                              'nova.tests.unit.test_service.FakeManager')
        self.addCleanup(serv.stop)
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
        serv.manager.init_host.assert_called_with(None)
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
        serv.manager.init_host.assert_called_once_with(None)
        mock_get_by_host_and_binary.assert_called_once_with(mock.ANY,
                                                            self.host,
                                                            self.binary)
        mock_create.assert_called_once_with()
        serv.manager.pre_start_hook.assert_called_once_with(serv.service_ref)
        serv.manager.post_start_hook.assert_called_once_with()
        serv.stop()
        mock_stop.assert_called_once_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    def test_service_stop_call_manager_graceful_shutdown(
            self, mock_svc_get_by_host_and_binary, mock_API):
        mock_manager = mock.Mock(target=None)

        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')

        serv.manager = mock_manager
        serv.manager.additional_endpoints = []

        serv.start()
        serv.manager.init_host.assert_called_with(
            mock_svc_get_by_host_and_binary.return_value)

        serv.stop()
        # Check service with one RPC server calls manager graceful_shutdown
        serv.manager.graceful_shutdown.assert_called_once_with()

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
        self.assertIsNone(serv.rpcserver_alt)
        self.assertEqual(mock_rpc.call_count, 1)

    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(messaging, 'get_rpc_server')
    def test_service_with_two_rpcservers(
            self, mock_get, mock_TRANSPORT, mock_svc_get):
        topic_alt = 'fake_alt'
        fake_manager = 'nova.tests.unit.test_service.FakeManager'
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               fake_manager,
                               topic_alt=topic_alt)
        serv.start()
        serv.stop()
        target = messaging.Target(topic=self.topic, server=self.host)
        target_alt = messaging.Target(topic=topic_alt, server=self.host)

        # Check the two calls to oslo.messasing get_rpc_server()
        # with different target
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(mock_TRANSPORT, target, mock.ANY,
                      executor=mock.ANY, serializer=mock.ANY,
                      access_policy=mock.ANY)
        mock_get.assert_any_call(mock_TRANSPORT, target_alt, mock.ANY,
                      executor=mock.ANY, serializer=mock.ANY,
                      access_policy=mock.ANY)
        self.assertIsNotNone(serv.rpcserver)
        self.assertIsNotNone(serv.rpcserver_alt)

    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(messaging.rpc.server.RPCServer, '_create_listener')
    def test_service_with_two_rpc_topics_get_two_different_rpcservers(
            self, mock_listner, mock_svc_get):
        topic_alt = 'fake_alt'
        fake_manager = 'nova.tests.unit.test_service.FakeManager'
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               fake_manager,
                               topic_alt=topic_alt)
        serv.start()
        self.assertIsNotNone(serv.rpcserver)
        self.assertIsNotNone(serv.rpcserver_alt)
        self.assertNotEqual(serv.rpcserver, serv.rpcserver_alt)

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_with_two_rpcservers(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager',
                               topic_alt='fake_alt')
        serv.start()
        rpcserver = serv.rpcserver
        rpcserver_alt = serv.rpcserver_alt
        self.assertIsNotNone(rpcserver_alt)
        with mock.patch.object(serv.manager, 'graceful_shutdown') as mock_gs:
            serv.stop()
            # Both rpcservers stop and wait is called.
            rpcserver.stop.assert_called_with()
            rpcserver.wait.assert_called_with()
            rpcserver_alt.stop.assert_called_with()
            rpcserver_alt.wait.assert_called_with()
            # Check service with two RPC server calls manager graceful_shutdown
            mock_gs.assert_called_once_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_handle_manager_gs_exception(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        serv.start()
        serv.manager.graceful_shutdown = mock.Mock(side_effect=Exception())
        # service.stop() should proceed even manager graceful_shutdown raise
        # error
        serv.stop()
        serv.manager.graceful_shutdown.assert_called_once_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_stop_with_two_rpcservers_handle_manager_gs_exception(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager',
                               topic_alt='fake-alt')
        serv.start()
        rpcserver = serv.rpcserver
        rpcserver_alt = serv.rpcserver_alt
        serv.manager.graceful_shutdown = mock.Mock(side_effect=Exception())
        serv.stop()
        # Even manager graceful_shutdown() raise error, both rpcservers stop
        # and wait is called.
        rpcserver.stop.assert_called_with()
        rpcserver.wait.assert_called_with()
        rpcserver_alt.stop.assert_called_with()
        rpcserver_alt.wait.assert_called_with()
        serv.manager.graceful_shutdown.assert_called_once_with()

    def test_stop_before_start_initialize_RPC_does_not_raise(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        # Neither rpcserver nor rpcserver_alt has been set by start() yet.
        self.assertIsNone(serv.rpcserver)
        self.assertIsNone(serv.rpcserver_alt)
        with mock.patch.object(serv.manager, 'graceful_shutdown'):
            # Should not raise AttributeError.
            serv.stop()

    def test_stop_with_topic_alt_before_start_does_not_raise(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager',
                               topic_alt='fake_alt')
        self.assertIsNone(serv.rpcserver)
        self.assertIsNone(serv.rpcserver_alt)
        with mock.patch.object(serv.manager, 'graceful_shutdown'):
            serv.stop()

    def test_shutdown_rpc_server(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        mock_rpc_server = mock.Mock()
        serv._shutdown_rpc_server(mock_rpc_server, self.topic)
        mock_rpc_server.stop.assert_called_once_with()
        mock_rpc_server.wait.assert_called_once_with()

    def test_shutdown_rpc_server_handle_exception(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        mock_rpc_server = mock.Mock()
        mock_rpc_server.stop.side_effect = Exception()
        serv._shutdown_rpc_server(mock_rpc_server, self.topic)
        mock_rpc_server.stop.assert_called_once_with()
        mock_rpc_server.wait.assert_not_called()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_handle_first_rpcserver_exception(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager',
                               topic_alt='fake_alt')
        serv.start()
        serv.rpcserver = mock.Mock()
        rpcserver = serv.rpcserver
        serv.rpcserver.stop.side_effect = Exception()
        rpcserver_alt = serv.rpcserver_alt
        self.assertIsNotNone(rpcserver_alt)
        with mock.patch.object(serv.manager, 'graceful_shutdown') as mock_gs:
            serv.stop()
            rpcserver.stop.assert_called_once_with()
            rpcserver.wait.assert_not_called()
            # Check if first RPC server stop() raise exception, it still call
            # manager graceful_shutdown() and 2nd RPC server stop/wait.
            mock_gs.assert_called_once_with()
            rpcserver_alt.stop.assert_called_once_with()
            rpcserver_alt.wait.assert_called_once_with()

    @mock.patch('nova.servicegroup.API')
    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    @mock.patch.object(rpc, 'get_server')
    def test_service_stop_handle_2nd_rpcserver_exception(
            self, mock_rpc, mock_svc_get_by_host_and_binary, mock_API):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager',
                               topic_alt='fake_alt')
        serv.start()
        rpcserver = serv.rpcserver
        serv.rpcserver_alt = mock.Mock()
        serv.rpcserver_alt.stop.side_effect = Exception()
        rpcserver_alt = serv.rpcserver_alt
        self.assertIsNotNone(rpcserver_alt)
        with mock.patch.object(serv.manager, 'graceful_shutdown') as mock_gs:
            serv.stop()
            rpcserver.stop.assert_called_once_with()
            rpcserver.wait.assert_called_once_with()
            mock_gs.assert_called_once_with()
            # service.stop() should proceed even 2nd RPC server stop() raise
            # error.
            rpcserver_alt.stop.assert_called_once_with()
            rpcserver_alt.wait.assert_not_called()

    def test_reset(self):
        serv = service.Service(self.host,
                               self.binary,
                               self.topic,
                               'nova.tests.unit.test_service.FakeManager')
        with mock.patch.object(serv.manager, 'reset') as mock_reset:
            serv.reset()
            mock_reset.assert_called_once_with()

    @mock.patch('nova.conductor.api.API.wait_until_ready')
    @mock.patch('nova.utils.raise_if_old_compute')
    def test_old_compute_version_check_happens_after_wait_for_conductor(
            self, mock_check_old, mock_wait):
        obj_base.NovaObject.indirection_api = mock.MagicMock()

        def fake_wait(*args, **kwargs):
            mock_check_old.assert_not_called()

        mock_wait.side_effect = fake_wait

        service.Service.create(
            self.host, self.binary, self.topic,
            'nova.tests.unit.test_service.FakeManager')

        mock_check_old.assert_called_once_with()
        mock_wait.assert_called_once_with(mock.ANY)

    @mock.patch('nova.utils.raise_if_old_compute')
    def test_old_compute_version_check_workaround(
            self, mock_check_old):

        mock_check_old.side_effect = exception.TooOldComputeService(
            oldest_supported_version='2',
            scope='scope',
            min_service_level=2,
            oldest_supported_service=1)

        self.assertRaises(exception.TooOldComputeService,
                          service.Service.create,
                          self.host, 'nova-conductor', self.topic,
                          'nova.tests.unit.test_service.FakeManager')

        CONF.set_override('disable_compute_service_check_for_ffu', True,
                          group='workarounds')

        service.Service.create(self.host, 'nova-conductor', self.topic,
                               'nova.tests.unit.test_service.FakeManager')

        mock_check_old.assert_has_calls([mock.call(), mock.call()])


class TestLauncher(test.NoDBTestCase):

    @mock.patch.object(_service, 'launch')
    def test_launch_app(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service)
        mock_launch.assert_called_once_with(mock.ANY,
                                            mock.sentinel.service,
                                            workers=None,
                                            restart_method='mutate',
                                            no_fork=False)

    @mock.patch.object(_service, 'launch')
    def test_launch_app_with_workers(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service, workers=mock.sentinel.workers)
        mock_launch.assert_called_once_with(mock.ANY,
                                            mock.sentinel.service,
                                            workers=mock.sentinel.workers,
                                            restart_method='mutate',
                                            no_fork=False)

    @mock.patch.object(_service, 'launch')
    def test_launch_app_with_workers_no_fork(self, mock_launch):
        service._launcher = None
        service.serve(
            mock.sentinel.service, workers=mock.sentinel.workers, no_fork=True)
        mock_launch.assert_called_once_with(mock.ANY,
                                            mock.sentinel.service,
                                            workers=mock.sentinel.workers,
                                            restart_method='mutate',
                                            no_fork=True)

    @mock.patch.object(_service, 'launch')
    def test_launch_app_more_than_once_raises(self, mock_launch):
        service._launcher = None
        service.serve(mock.sentinel.service)
        self.assertRaises(RuntimeError, service.serve, mock.sentinel.service)
