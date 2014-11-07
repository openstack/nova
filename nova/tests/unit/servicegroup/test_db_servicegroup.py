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

import datetime

import fixtures
from oslo.utils import timeutils

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


class DBServiceGroupTestCase(test.TestCase):

    def setUp(self):
        super(DBServiceGroupTestCase, self).setUp()
        servicegroup.API._driver = None
        self.flags(servicegroup_driver='db')
        self.down_time = 15
        self.flags(enable_new_services=True)
        self.flags(service_down_time=self.down_time)
        self.servicegroup_api = servicegroup.API()
        self._host = 'foo'
        self._binary = 'nova-fake'
        self._topic = 'unittest'
        self._ctx = context.get_admin_context()

    def test_DB_driver(self):
        serv = self.useFixture(
            ServiceFixture(self._host, self._binary, self._topic)).serv
        serv.start()
        service_ref = db.service_get_by_args(self._ctx,
                                             self._host,
                                             self._binary)

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

        serv1 = self.useFixture(
            ServiceFixture(host1, self._binary, self._topic)).serv
        serv1.start()

        serv2 = self.useFixture(
            ServiceFixture(host2, self._binary, self._topic)).serv
        serv2.start()

        service_ref1 = db.service_get_by_args(self._ctx,
                                              host1,
                                              self._binary)
        service_ref2 = db.service_get_by_args(self._ctx,
                                              host2,
                                              self._binary)

        services = self.servicegroup_api.get_all(self._topic)

        self.assertIn(service_ref1['host'], services)
        self.assertIn(service_ref2['host'], services)

        service_id = self.servicegroup_api.get_one(self._topic)
        self.assertIn(service_id, services)

    def test_service_is_up(self):
        fts_func = datetime.datetime.fromtimestamp
        fake_now = 1000
        down_time = 15
        self.flags(service_down_time=down_time)
        self.mox.StubOutWithMock(timeutils, 'utcnow')
        self.servicegroup_api = servicegroup.API()

        # Up (equal)
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - self.down_time),
                   'created_at': fts_func(fake_now - self.down_time)}
        self.mox.ReplayAll()
        result = self.servicegroup_api.service_is_up(service)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Up
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - self.down_time + 1),
                   'created_at': fts_func(fake_now - self.down_time + 1)}
        self.mox.ReplayAll()
        result = self.servicegroup_api.service_is_up(service)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Down
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - self.down_time - 3),
                   'created_at': fts_func(fake_now - self.down_time - 3)}
        self.mox.ReplayAll()
        result = self.servicegroup_api.service_is_up(service)
        self.assertFalse(result)
