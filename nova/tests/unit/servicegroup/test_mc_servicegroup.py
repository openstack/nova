# Copyright (c) 2013 Akira Yoshiyama <akirayoshiyama at gmail dot com>
#
# This is derived from test_db_servicegroup.py.
# Copyright 2012 IBM Corp.
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

import fixtures
from oslo_utils import timeutils

from nova import context
from nova import db
from nova import service
from nova import servicegroup
from nova import test


class ServiceFixture(fixtures.Fixture):

    def __init__(self, host, binary, topic):
        super(ServiceFixture, self).__init__()
        self.host = host
        self.binary = binary
        self.topic = topic
        self.serv = None

    def setUp(self):
        super(ServiceFixture, self).setUp()
        self.serv = service.Service(self.host,
                                    self.binary,
                                    self.topic,
                                    'nova.tests.unit.test_service.FakeManager',
                                    1, 1)
        self.addCleanup(self.serv.kill)


class MemcachedServiceGroupTestCase(test.TestCase):

    def setUp(self):
        super(MemcachedServiceGroupTestCase, self).setUp()
        servicegroup.API._driver = None
        self.flags(servicegroup_driver='mc')
        self.down_time = 15
        self.flags(enable_new_services=True)
        self.flags(service_down_time=self.down_time)
        self.servicegroup_api = servicegroup.API(test=True)
        self._host = 'foo'
        self._binary = 'nova-fake'
        self._topic = 'unittest'
        self._ctx = context.get_admin_context()

    def test_memcached_driver(self):
        serv = self.useFixture(
            ServiceFixture(self._host, self._binary, self._topic)).serv
        serv.start()
        service_ref = db.service_get_by_args(self._ctx,
                                             self._host,
                                             self._binary)
        hostkey = str("%s:%s" % (self._topic, self._host))
        self.servicegroup_api._driver.mc.set(hostkey,
                                             timeutils.utcnow(),
                                             time=self.down_time)

        self.assertTrue(self.servicegroup_api.service_is_up(service_ref))
        self.useFixture(test.TimeOverride())
        timeutils.advance_time_seconds(self.down_time + 1)
        self.servicegroup_api._driver._report_state(serv)
        service_ref = db.service_get_by_args(self._ctx,
                                             self._host,
                                             self._binary)

        self.assertTrue(self.servicegroup_api.service_is_up(service_ref))
        serv.stop()
        timeutils.advance_time_seconds(self.down_time + 1)
        service_ref = db.service_get_by_args(self._ctx,
                                             self._host,
                                             self._binary)
        self.assertFalse(self.servicegroup_api.service_is_up(service_ref))

    def test_get_all(self):
        host1 = self._host + '_1'
        host2 = self._host + '_2'
        host3 = self._host + '_3'

        serv1 = self.useFixture(
            ServiceFixture(host1, self._binary, self._topic)).serv
        serv1.start()

        serv2 = self.useFixture(
            ServiceFixture(host2, self._binary, self._topic)).serv
        serv2.start()

        serv3 = self.useFixture(
            ServiceFixture(host3, self._binary, self._topic)).serv
        serv3.start()

        db.service_get_by_args(self._ctx, host1, self._binary)
        db.service_get_by_args(self._ctx, host2, self._binary)
        db.service_get_by_args(self._ctx, host3, self._binary)

        host1key = str("%s:%s" % (self._topic, host1))
        host2key = str("%s:%s" % (self._topic, host2))
        host3key = str("%s:%s" % (self._topic, host3))
        self.servicegroup_api._driver.mc.set(host1key,
                                             timeutils.utcnow(),
                                             time=self.down_time)
        self.servicegroup_api._driver.mc.set(host2key,
                                             timeutils.utcnow(),
                                             time=self.down_time)
        self.servicegroup_api._driver.mc.set(host3key,
                                             timeutils.utcnow(),
                                             time=-1)

        services = self.servicegroup_api.get_all(self._topic)

        self.assertIn(host1, services)
        self.assertIn(host2, services)
        self.assertNotIn(host3, services)

        service_id = self.servicegroup_api.get_one(self._topic)
        self.assertIn(service_id, services)

    def test_service_is_up(self):
        serv = self.useFixture(
            ServiceFixture(self._host, self._binary, self._topic)).serv
        serv.start()
        service_ref = db.service_get_by_args(self._ctx,
                                             self._host,
                                             self._binary)
        fake_now = 1000
        down_time = 15
        self.flags(service_down_time=down_time)
        self.mox.StubOutWithMock(timeutils, 'utcnow_ts')
        self.servicegroup_api = servicegroup.API()
        hostkey = str("%s:%s" % (self._topic, self._host))

        # Up (equal)
        timeutils.utcnow_ts().AndReturn(fake_now)
        timeutils.utcnow_ts().AndReturn(fake_now + down_time - 1)
        self.mox.ReplayAll()
        self.servicegroup_api._driver.mc.set(hostkey,
                                             timeutils.utcnow(),
                                             time=down_time)
        result = self.servicegroup_api.service_is_up(service_ref)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Up
        timeutils.utcnow_ts().AndReturn(fake_now)
        timeutils.utcnow_ts().AndReturn(fake_now + down_time - 2)
        self.mox.ReplayAll()
        self.servicegroup_api._driver.mc.set(hostkey,
                                             timeutils.utcnow(),
                                             time=down_time)
        result = self.servicegroup_api.service_is_up(service_ref)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Down
        timeutils.utcnow_ts().AndReturn(fake_now)
        timeutils.utcnow_ts().AndReturn(fake_now + down_time)
        self.mox.ReplayAll()
        self.servicegroup_api._driver.mc.set(hostkey,
                                             timeutils.utcnow(),
                                             time=down_time)
        result = self.servicegroup_api.service_is_up(service_ref)
        self.assertFalse(result)

        self.mox.ResetAll()
        # Down
        timeutils.utcnow_ts().AndReturn(fake_now)
        timeutils.utcnow_ts().AndReturn(fake_now + down_time + 1)
        self.mox.ReplayAll()
        self.servicegroup_api._driver.mc.set(hostkey,
                                             timeutils.utcnow(),
                                             time=down_time)
        result = self.servicegroup_api.service_is_up(service_ref)
        self.assertFalse(result)

        self.mox.ResetAll()

    def test_report_state(self):
        serv = self.useFixture(
            ServiceFixture(self._host, self._binary, self._topic)).serv
        serv.start()
        db.service_get_by_args(self._ctx, self._host, self._binary)
        self.servicegroup_api = servicegroup.API()

        # updating model_disconnected
        serv.model_disconnected = True
        self.servicegroup_api._driver._report_state(serv)
        self.assertFalse(serv.model_disconnected)

        # handling exception
        serv.model_disconnected = True
        self.servicegroup_api._driver.mc = None
        self.servicegroup_api._driver._report_state(serv)
        self.assertTrue(serv.model_disconnected)

        delattr(serv, 'model_disconnected')
        self.servicegroup_api._driver.mc = None
        self.servicegroup_api._driver._report_state(serv)
        self.assertTrue(serv.model_disconnected)
