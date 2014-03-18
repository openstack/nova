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

import calendar
import datetime

import mock
import webob.exc

from nova.api.openstack.compute.plugins.v3 import services
from nova import availability_zones
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import timeutils
from nova.servicegroup.drivers import db as db_driver
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.objects import test_service


fake_services_list = [
    dict(test_service.fake_service,
         binary='nova-scheduler',
         host='host1',
         id=1,
         disabled=True,
         topic='scheduler',
         updated_at=datetime.datetime(2012, 10, 29, 13, 42, 2),
         created_at=datetime.datetime(2012, 9, 18, 2, 46, 27),
         disabled_reason='test1'),
    dict(test_service.fake_service,
         binary='nova-compute',
         host='host1',
         id=2,
         disabled=True,
         topic='compute',
         updated_at=datetime.datetime(2012, 10, 29, 13, 42, 5),
         created_at=datetime.datetime(2012, 9, 18, 2, 46, 27),
         disabled_reason='test2'),
    dict(test_service.fake_service,
         binary='nova-scheduler',
         host='host2',
         id=3,
         disabled=False,
         topic='scheduler',
         updated_at=datetime.datetime(2012, 9, 19, 6, 55, 34),
         created_at=datetime.datetime(2012, 9, 18, 2, 46, 28),
         disabled_reason=''),
    dict(test_service.fake_service,
         binary='nova-compute',
         host='host2',
         id=4,
         disabled=True,
         topic='compute',
         updated_at=datetime.datetime(2012, 9, 18, 8, 3, 38),
         created_at=datetime.datetime(2012, 9, 18, 2, 46, 28),
         disabled_reason='test4'),
    ]


class FakeRequest(object):
        environ = {"nova.context": context.get_admin_context()}
        GET = {}


class FakeRequestWithService(object):
        environ = {"nova.context": context.get_admin_context()}
        GET = {"binary": "nova-compute"}


class FakeRequestWithHost(object):
        environ = {"nova.context": context.get_admin_context()}
        GET = {"host": "host1"}


class FakeRequestWithHostService(object):
        environ = {"nova.context": context.get_admin_context()}
        GET = {"host": "host1", "binary": "nova-compute"}


def fake_host_api_service_get_all(context, filters=None, set_zones=False):
    if set_zones or 'availability_zone' in filters:
        return availability_zones.set_availability_zones(context,
                                                         fake_services_list)


def fake_db_api_service_get_all(context, disabled=None):
    return fake_services_list


def fake_service_get_by_host_binary(context, host, binary):
    for service in fake_services_list:
        if service['host'] == host and service['binary'] == binary:
            return service
    raise exception.HostBinaryNotFound(host=host, binary=binary)


def fake_service_get_by_id(value):
    for service in fake_services_list:
        if service['id'] == value:
            return service
    return None


def fake_service_update(context, service_id, values):
    service = fake_service_get_by_id(service_id)
    if service is None:
        raise exception.ServiceNotFound(service_id=service_id)
    return service


def fake_utcnow():
    return datetime.datetime(2012, 10, 29, 13, 42, 11)


def fake_utcnow_ts():
    d = fake_utcnow()
    return calendar.timegm(d.utctimetuple())


class ServicesTest(test.TestCase):

    def setUp(self):
        super(ServicesTest, self).setUp()

        self.context = context.get_admin_context()
        self.controller = services.ServiceController()
        self.stubs.Set(self.controller.host_api, "service_get_all",
                       fake_host_api_service_get_all)
        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(timeutils, "utcnow_ts", fake_utcnow_ts)
        self.stubs.Set(db, "service_get_by_args",
                       fake_service_get_by_host_binary)
        self.stubs.Set(db, "service_update", fake_service_update)

    def test_services_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)
        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'id': 1,
                    'host': 'host1',
                    'zone': 'internal',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                    'disabled_reason': 'test1'},
                    {'binary': 'nova-compute',
                     'host': 'host1',
                     'id': 2,
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'up',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                     'disabled_reason': 'test2'},
                    {'binary': 'nova-scheduler',
                     'host': 'host2',
                     'id': 3,
                     'zone': 'internal',
                     'status': 'enabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34),
                     'disabled_reason': ''},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'id': 4,
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
                     'disabled_reason': 'test4'}]}
        self.assertEqual(res_dict, response)

    def test_service_list_with_host(self):
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)
        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'host': 'host1',
                    'id': 1,
                    'zone': 'internal',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                    'disabled_reason': 'test1'},
                   {'binary': 'nova-compute',
                    'host': 'host1',
                    'id': 2,
                    'zone': 'nova',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'}]}
        self.assertEqual(res_dict, response)

    def test_service_list_with_service(self):
        req = FakeRequestWithService()
        res_dict = self.controller.index(req)
        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'id': 2,
                    'zone': 'nova',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'id': 4,
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
                     'disabled_reason': 'test4'}]}
        self.assertEqual(res_dict, response)

    def test_service_list_with_host_service(self):
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)
        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'id': 2,
                    'zone': 'nova',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'}]}
        self.assertEqual(res_dict, response)

    def test_services_enable(self):
        def _service_update(context, service_id, values):
            self.assertIsNone(values['disabled_reason'])
            return test_service.fake_service

        self.stubs.Set(db, "service_update", _service_update)

        body = {'service': {'host': 'host1',
                            'binary': 'nova-compute'}}
        req = fakes.HTTPRequestV3.blank('/os-services/enable')
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual(res_dict['service']['status'], 'enabled')
        self.assertNotIn('disabled_reason', res_dict['service'])

    def test_services_enable_with_invalid_host(self):
        body = {'service': {'host': 'invalid',
                            'binary': 'nova-compute'}}
        req = fakes.HTTPRequestV3.blank('/os-services/enable')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req,
                          "enable",
                          body)

    def test_services_enable_with_invalid_binary(self):
        body = {'service': {'host': 'host1',
                            'binary': 'invalid'}}
        req = fakes.HTTPRequestV3.blank('/os-services/enable')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req,
                          "enable",
                          body)

    # This test is just to verify that the servicegroup API gets used when
    # calling this API.
    def test_services_with_exception(self):
        def dummy_is_up(self, dummy):
            raise KeyError()

        self.stubs.Set(db_driver.DbDriver, 'is_up', dummy_is_up)
        req = FakeRequestWithHostService()
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.index, req)

    def test_services_disable(self):
        req = fakes.HTTPRequestV3.blank('/os-services/disable')
        body = {'service': {'host': 'host1',
                            'binary': 'nova-compute'}}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual(res_dict['service']['status'], 'disabled')
        self.assertNotIn('disabled_reason', res_dict['service'])

    def test_services_disable_with_invalid_host(self):
        body = {'service': {'host': 'invalid',
                            'binary': 'nova-compute'}}
        req = fakes.HTTPRequestV3.blank('/os-services/disable')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req,
                          "disable",
                          body)

    def test_services_disable_with_invalid_binary(self):
        body = {'service': {'host': 'host1',
                            'binary': 'invalid'}}
        req = fakes.HTTPRequestV3.blank('/os-services/disable')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req,
                          "disable",
                          body)

    def test_services_disable_log_reason(self):
        req = \
            fakes.HTTPRequestV3.blank('/os-services/disable-log-reason')
        body = {'service': {'host': 'host1',
                            'binary': 'nova-compute',
                            'disabled_reason': 'test-reason'}}
        res_dict = self.controller.update(req, "disable-log-reason", body)

        self.assertEqual(res_dict['service']['status'], 'disabled')
        self.assertEqual(res_dict['service']['disabled_reason'], 'test-reason')

    def test_mandatory_reason_field(self):
        req = \
            fakes.HTTPRequestV3.blank('/os-services/disable-log-reason')
        body = {'service': {'host': 'host1',
                            'binary': 'nova-compute'}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                self.controller.update, req, "disable-log-reason", body)

    def test_invalid_reason_field(self):
        reason = ' '
        self.assertFalse(self.controller._is_valid_as_reason(reason))
        reason = 'a' * 256
        self.assertFalse(self.controller._is_valid_as_reason(reason))
        reason = 'it\'s a valid reason.'
        self.assertTrue(self.controller._is_valid_as_reason(reason))

    def test_services_delete(self):
        request = fakes.HTTPRequestV3.blank('/v3/os-services/1',
                                            use_admin_context=True)
        request.method = 'DELETE'

        with mock.patch.object(self.controller.host_api,
                               'service_delete') as service_delete:
            response = self.controller.delete(request, '1')
            service_delete.assert_called_once_with(
                request.environ['nova.context'], '1')
            self.assertEqual(self.controller.delete.wsgi_code, 204)

    def test_services_delete_not_found(self):
        request = fakes.HTTPRequestV3.blank('/v3/os-services/abc',
                                            use_admin_context=True)
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, 'abc')
