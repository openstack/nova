#    Copyright 2013 IBM Corp.
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

from nova import context
from nova import db
from nova.objects import service
from nova.openstack.common import timeutils
from nova.tests.objects import test_objects

NOW = timeutils.utcnow().replace(microsecond=0)
fake_service = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'host': 'fake-host',
    'binary': 'fake-service',
    'topic': 'fake-service-topic',
    'report_count': 1,
    'disabled': False,
    'disabled_reason': None,
    }


def compare(obj, db_obj):
    allow_missing = ('availability_zone',)
    for key in obj.fields:
        if key in allow_missing and not obj.obj_attr_is_set(key):
            continue
        obj_val = obj[key]
        if isinstance(obj_val, datetime.datetime):
            obj_val = obj_val.replace(tzinfo=None)
        db_val = db_obj[key]
        assert db_val == obj_val, '%s != %s' % (db_val, obj_val)


class _TestServiceObject(object):
    def _test_query(self, db_method, obj_method, *args, **kwargs):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, db_method)
        getattr(db, db_method)(ctxt, *args, **kwargs).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        obj = getattr(service.Service, obj_method)(ctxt, *args, **kwargs)
        compare(obj, fake_service)

    def test_get_by_id(self):
        self._test_query('service_get', 'get_by_id', 123)

    def test_get_by_host_and_topic(self):
        self._test_query('service_get_by_host_and_topic',
                         'get_by_host_and_topic', 'fake-host', 'fake-topic')

    def test_get_by_compute_host(self):
        self._test_query('service_get_by_compute_host', 'get_by_compute_host',
                         'fake-host')

    def test_get_by_args(self):
        self._test_query('service_get_by_args', 'get_by_args', 'fake-host',
                         'fake-service')

    def test_create(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_create')
        db.service_create(ctxt, {'host': 'fake-host'}).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service()
        service_obj.host = 'fake-host'
        service_obj.create(ctxt)
        self.assertEqual(fake_service['id'], service_obj.id)

    def test_save(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_update')
        db.service_update(ctxt, 123, {'host': 'fake-host'}).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service()
        service_obj.id = 123
        service_obj.host = 'fake-host'
        service_obj.save(ctxt)

    def _test_destroy(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_destroy')
        db.service_destroy(ctxt, 123)
        self.mox.ReplayAll()
        service_obj = service.Service()
        service_obj.id = 123
        service_obj.destroy(ctxt)

    def test_destroy(self):
        # The test harness needs db.service_destroy to work,
        # so avoid leaving it broken here after we're done
        orig_service_destroy = db.service_destroy
        try:
            self._test_destroy()
        finally:
            db.service_destroy = orig_service_destroy

    def test_get_by_topic(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        db.service_get_all_by_topic(ctxt, 'fake-topic').AndReturn(
            [fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_by_topic(ctxt, 'fake-topic')
        self.assertEqual(1, len(services))
        compare(services[0], fake_service)

    def test_get_by_host(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all_by_host')
        db.service_get_all_by_host(ctxt, 'fake-host').AndReturn(
            [fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_by_host(ctxt, 'fake-host')
        self.assertEqual(1, len(services))
        compare(services[0], fake_service)

    def test_get_all(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all')
        db.service_get_all(ctxt, disabled=False).AndReturn([fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_all(ctxt, disabled=False)
        self.assertEqual(1, len(services))
        compare(services[0], fake_service)

    def test_get_all_with_az(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all')
        self.mox.StubOutWithMock(db, 'aggregate_host_get_by_metadata_key')
        db.service_get_all(ctxt, disabled=None).AndReturn(
            [dict(fake_service, topic='compute')])
        db.aggregate_host_get_by_metadata_key(
            ctxt, key='availability_zone').AndReturn(
                {fake_service['host']: ['test-az']})
        self.mox.ReplayAll()
        services = service.ServiceList.get_all(ctxt, set_zones=True)
        self.assertEqual(1, len(services))
        self.assertEqual('test-az', services[0].availability_zone)


class TestServiceObject(test_objects._LocalTest,
                        _TestServiceObject):
    pass


class TestRemoteServiceObject(test_objects._RemoteTest,
                              _TestServiceObject):
    pass
