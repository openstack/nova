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

import mox

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import rpc
from nova import test
from nova import service
from nova import manager
from nova.compute import manager as compute_manager

FLAGS = flags.FLAGS
flags.DEFINE_string("fake_manager", "nova.tests.test_service.FakeManager",
                    "Manager for testing")


class FakeManager(manager.Manager):
    """Fake manager for tests"""
    def test_method(self):
        return 'manager'


class ExtendedService(service.Service):
    def test_method(self):
        return 'service'


class ServiceManagerTestCase(test.TestCase):
    """Test cases for Services"""

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
    """Test cases for Services"""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.mox.StubOutWithMock(service, 'db')

    def test_create(self):
        host = 'foo'
        binary = 'nova-fake'
        topic = 'fake'

        # NOTE(vish): Create was moved out of mox replay to make sure that
        #             the looping calls are created in StartService.
        app = service.Service.create(host=host, binary=binary)

        self.mox.StubOutWithMock(rpc,
                                 'TopicAdapterConsumer',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(rpc,
                                 'FanoutAdapterConsumer',
                                 use_mock_anything=True)
        rpc.TopicAdapterConsumer(connection=mox.IgnoreArg(),
                            topic=topic,
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.TopicAdapterConsumer)

        rpc.TopicAdapterConsumer(connection=mox.IgnoreArg(),
                            topic='%s.%s' % (topic, host),
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.TopicAdapterConsumer)

        rpc.FanoutAdapterConsumer(connection=mox.IgnoreArg(),
                            topic=topic,
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.FanoutAdapterConsumer)

        rpc.TopicAdapterConsumer.attach_to_eventlet()
        rpc.TopicAdapterConsumer.attach_to_eventlet()
        rpc.FanoutAdapterConsumer.attach_to_eventlet()

        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                       'binary': binary,
                       'report_count': 0,
                       'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                       host,
                                       binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        self.mox.ReplayAll()

        app.start()
        app.stop()
        self.assert_(app)

    # We're testing sort of weird behavior in how report_state decides
    # whether it is disconnected, it looks for a variable on itself called
    # 'model_disconnected' and report_state doesn't really do much so this
    # these are mostly just for coverage
    def test_report_state_no_service(self):
        host = 'foo'
        binary = 'bar'
        topic = 'test'
        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova',
                          'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                      host,
                                      binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        service.db.service_get(mox.IgnoreArg(),
                               service_ref['id']).AndReturn(service_ref)
        service.db.service_update(mox.IgnoreArg(), service_ref['id'],
                                  mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        serv = service.Service(host,
                               binary,
                               topic,
                               'nova.tests.test_service.FakeManager')
        serv.start()
        serv.report_state()

    def test_report_state_newly_disconnected(self):
        host = 'foo'
        binary = 'bar'
        topic = 'test'
        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova',
                          'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                      host,
                                      binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        service.db.service_get(mox.IgnoreArg(),
                               mox.IgnoreArg()).AndRaise(Exception())

        self.mox.ReplayAll()
        serv = service.Service(host,
                               binary,
                               topic,
                               'nova.tests.test_service.FakeManager')
        serv.start()
        serv.report_state()
        self.assert_(serv.model_disconnected)

    def test_report_state_newly_connected(self):
        host = 'foo'
        binary = 'bar'
        topic = 'test'
        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova',
                          'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                      host,
                                      binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        service.db.service_get(mox.IgnoreArg(),
                               service_ref['id']).AndReturn(service_ref)
        service.db.service_update(mox.IgnoreArg(), service_ref['id'],
                                  mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        serv = service.Service(host,
                               binary,
                               topic,
                               'nova.tests.test_service.FakeManager')
        serv.start()
        serv.model_disconnected = True
        serv.report_state()

        self.assert_(not serv.model_disconnected)

    def test_compute_can_update_available_resource(self):
        """Confirm compute updates their record of compute-service table."""
        host = 'foo'
        binary = 'nova-compute'
        topic = 'compute'

        # Any mocks are not working without UnsetStubs() here.
        self.mox.UnsetStubs()
        ctxt = context.get_admin_context()
        service_ref = db.service_create(ctxt, {'host': host,
                                               'binary': binary,
                                               'topic': topic})
        serv = service.Service(host,
                               binary,
                               topic,
                               'nova.compute.manager.ComputeManager')

        # This testcase want to test calling update_available_resource.
        # No need to call periodic call, then below variable must be set 0.
        serv.report_interval = 0
        serv.periodic_interval = 0

        # Creating mocks
        self.mox.StubOutWithMock(service.rpc.Connection, 'instance')
        service.rpc.Connection.instance(new=mox.IgnoreArg())
        service.rpc.Connection.instance(new=mox.IgnoreArg())
        service.rpc.Connection.instance(new=mox.IgnoreArg())
        self.mox.StubOutWithMock(serv.manager.driver,
                                 'update_available_resource')
        serv.manager.driver.update_available_resource(mox.IgnoreArg(), host)

        # Just doing start()-stop(), not confirm new db record is created,
        # because update_available_resource() works only in
        # libvirt environment. This testcase confirms
        # update_available_resource() is called. Otherwise, mox complains.
        self.mox.ReplayAll()
        serv.start()
        serv.stop()

        db.service_destroy(ctxt, service_ref['id'])
