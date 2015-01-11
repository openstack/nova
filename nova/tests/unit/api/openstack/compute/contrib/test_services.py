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

import iso8601
import mock
from oslo_utils import timeutils
import webob.exc

from nova.api.openstack.compute.contrib import services as services_v2
from nova.api.openstack.compute.plugins.v3 import services as services_v21
from nova.api.openstack import extensions
from nova import availability_zones
from nova.compute import cells_api
from nova import context
from nova import db
from nova import exception
from nova.servicegroup.drivers import db as db_driver
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_service


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
         disabled_reason=None),
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


def fake_service_get_all(services):
    def service_get_all(context, filters=None, set_zones=False):
        if set_zones or 'availability_zone' in filters:
            return availability_zones.set_availability_zones(context,
                                                             services)
        return services
    return service_get_all


def fake_db_api_service_get_all(context, disabled=None):
    return fake_services_list


def fake_db_service_get_by_host_binary(services):
    def service_get_by_host_binary(context, host, binary):
        for service in services:
            if service['host'] == host and service['binary'] == binary:
                return service
        raise exception.HostBinaryNotFound(host=host, binary=binary)
    return service_get_by_host_binary


def fake_service_get_by_host_binary(context, host, binary):
    fake = fake_db_service_get_by_host_binary(fake_services_list)
    return fake(context, host, binary)


def _service_get_by_id(services, value):
    for service in services:
        if service['id'] == value:
            return service
    return None


def fake_db_service_update(services):
    def service_update(context, service_id, values):
        service = _service_get_by_id(services, service_id)
        if service is None:
            raise exception.ServiceNotFound(service_id=service_id)
        return service
    return service_update


def fake_service_update(context, service_id, values):
    fake = fake_db_service_update(fake_services_list)
    return fake(context, service_id, values)


def fake_utcnow():
    return datetime.datetime(2012, 10, 29, 13, 42, 11)


fake_utcnow.override_time = None


def fake_utcnow_ts():
    d = fake_utcnow()
    return calendar.timegm(d.utctimetuple())


class ServicesTestV21(test.TestCase):
    service_is_up_exc = webob.exc.HTTPInternalServerError
    bad_request = exception.ValidationError

    def _set_up_controller(self):
        self.controller = services_v21.ServiceController()

    def setUp(self):
        super(ServicesTestV21, self).setUp()

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}

        self._set_up_controller()
        self.stubs.Set(self.controller.host_api, "service_get_all",
                       fake_service_get_all(fake_services_list))

        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(timeutils, "utcnow_ts", fake_utcnow_ts)

        self.stubs.Set(db, "service_get_by_args",
                       fake_db_service_get_by_host_binary(fake_services_list))
        self.stubs.Set(db, "service_update",
                       fake_db_service_update(fake_services_list))

        self.req = fakes.HTTPRequest.blank('')
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)

    def _process_output(self, services, has_disabled=False, has_id=False):
        return services

    def test_services_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'host': 'host1',
                    'zone': 'internal',
                    'status': 'disabled',
                    'id': 1,
                    'state': 'up',
                    'disabled_reason': 'test1',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2)},
                    {'binary': 'nova-compute',
                     'host': 'host1',
                     'zone': 'nova',
                     'id': 2,
                     'status': 'disabled',
                     'disabled_reason': 'test2',
                     'state': 'up',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
                    {'binary': 'nova-scheduler',
                     'host': 'host2',
                     'zone': 'internal',
                     'id': 3,
                     'status': 'enabled',
                     'disabled_reason': None,
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34)},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'zone': 'nova',
                     'id': 4,
                     'status': 'disabled',
                     'disabled_reason': 'test4',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38)}]}
        self._process_output(response)
        self.assertEqual(res_dict, response)

    def test_services_list_with_host(self):
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'host': 'host1',
                    'disabled_reason': 'test1',
                    'id': 1,
                    'zone': 'internal',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2)},
                   {'binary': 'nova-compute',
                    'host': 'host1',
                    'zone': 'nova',
                    'disabled_reason': 'test2',
                    'id': 2,
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)}]}
        self._process_output(response)
        self.assertEqual(res_dict, response)

    def test_services_list_with_service(self):
        req = FakeRequestWithService()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'disabled_reason': 'test2',
                    'id': 2,
                    'zone': 'nova',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'zone': 'nova',
                     'disabled_reason': 'test4',
                     'id': 4,
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38)}]}
        self._process_output(response)
        self.assertEqual(res_dict, response)

    def test_services_list_with_host_service(self):
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'zone': 'nova',
                    'disabled_reason': 'test2',
                    'id': 2,
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)}]}
        self._process_output(response)
        self.assertEqual(res_dict, response)

    def test_services_detail(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'host': 'host1',
                    'zone': 'internal',
                    'status': 'disabled',
                    'id': 1,
                    'disabled_reason': 'test1',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                    'disabled_reason': 'test1'},
                    {'binary': 'nova-compute',
                     'host': 'host1',
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'up',
                     'id': 2,
                     'disabled_reason': 'test2',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                     'disabled_reason': 'test2'},
                    {'binary': 'nova-scheduler',
                     'host': 'host2',
                     'zone': 'internal',
                     'status': 'enabled',
                     'id': 3,
                     'disabled_reason': 'test3',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34),
                     'disabled_reason': None},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'zone': 'nova',
                     'id': 4,
                     'disabled_reason': 'test4',
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
                     'disabled_reason': 'test4'}]}
        self._process_output(response, has_disabled=True)
        self.assertEqual(res_dict, response)

    def test_service_detail_with_host(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-scheduler',
                    'host': 'host1',
                    'zone': 'internal',
                    'id': 1,
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                    'disabled_reason': 'test1'},
                   {'binary': 'nova-compute',
                    'host': 'host1',
                    'zone': 'nova',
                    'id': 2,
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'}]}
        self._process_output(response, has_disabled=True)
        self.assertEqual(res_dict, response)

    def test_service_detail_with_service(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        req = FakeRequestWithService()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'zone': 'nova',
                    'id': 2,
                    'disabled_reason': 'test2',
                    'status': 'disabled',
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'},
                    {'binary': 'nova-compute',
                     'host': 'host2',
                     'id': 4,
                     'disabled_reason': 'test4',
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
                     'disabled_reason': 'test4'}]}
        self._process_output(response, has_disabled=True)
        self.assertEqual(res_dict, response)

    def test_service_detail_with_host_service(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [
                    {'binary': 'nova-compute',
                    'host': 'host1',
                    'zone': 'nova',
                    'status': 'disabled',
                    'id': 2,
                    'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
                    'disabled_reason': 'test2'}]}
        self._process_output(response, has_disabled=True)
        self.assertEqual(res_dict, response)

    def test_services_detail_with_delete_extension(self):
        self.ext_mgr.extensions['os-extended-services-delete'] = True
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'nova-scheduler',
             'host': 'host1',
             'id': 1,
             'zone': 'internal',
             'disabled_reason': 'test1',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2)},
            {'binary': 'nova-compute',
             'host': 'host1',
             'id': 2,
             'zone': 'nova',
             'disabled_reason': 'test2',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
            {'binary': 'nova-scheduler',
             'host': 'host2',
             'disabled_reason': None,
             'id': 3,
             'zone': 'internal',
             'status': 'enabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34)},
            {'binary': 'nova-compute',
             'host': 'host2',
             'id': 4,
             'disabled_reason': 'test4',
             'zone': 'nova',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38)}]}
        self._process_output(response, has_id=True)
        self.assertEqual(res_dict, response)

    def test_services_enable(self):
        def _service_update(context, service_id, values):
            self.assertIsNone(values['disabled_reason'])
            return dict(test_service.fake_service, id=service_id, **values)

        self.stubs.Set(db, "service_update", _service_update)

        body = {'host': 'host1', 'binary': 'nova-compute'}
        res_dict = self.controller.update(self.req, "enable", body=body)
        self.assertEqual(res_dict['service']['status'], 'enabled')
        self.assertNotIn('disabled_reason', res_dict['service'])

    def test_services_enable_with_invalid_host(self):
        body = {'host': 'invalid', 'binary': 'nova-compute'}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          self.req,
                          "enable",
                          body=body)

    def test_services_enable_with_invalid_binary(self):
        body = {'host': 'host1', 'binary': 'invalid'}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          self.req,
                          "enable",
                          body=body)

    def test_services_disable(self):
        body = {'host': 'host1', 'binary': 'nova-compute'}
        res_dict = self.controller.update(self.req, "disable", body=body)

        self.assertEqual(res_dict['service']['status'], 'disabled')
        self.assertNotIn('disabled_reason', res_dict['service'])

    def test_services_disable_with_invalid_host(self):
        body = {'host': 'invalid', 'binary': 'nova-compute'}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          self.req,
                          "disable",
                          body=body)

    def test_services_disable_with_invalid_binary(self):
        body = {'host': 'host1', 'binary': 'invalid'}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          self.req,
                          "disable",
                          body=body)

    def test_services_disable_log_reason(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'disabled_reason': 'test-reason',
                }
        res_dict = self.controller.update(self.req,
                                          "disable-log-reason",
                                          body=body)

        self.assertEqual(res_dict['service']['status'], 'disabled')
        self.assertEqual(res_dict['service']['disabled_reason'], 'test-reason')

    def test_mandatory_reason_field(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        body = {'host': 'host1',
                'binary': 'nova-compute',
               }
        self.assertRaises(webob.exc.HTTPBadRequest,
                self.controller.update, self.req, "disable-log-reason",
                body=body)

    def test_invalid_reason_field(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        reason = 'a' * 256
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'disabled_reason': reason,
               }
        self.assertRaises(self.bad_request,
                self.controller.update, self.req, "disable-log-reason",
                body=body)

    def test_services_delete(self):
        self.ext_mgr.extensions['os-extended-services-delete'] = True

        with mock.patch.object(self.controller.host_api,
                               'service_delete') as service_delete:
            self.controller.delete(self.admin_req, '1')
            service_delete.assert_called_once_with(
                self.admin_req.environ['nova.context'], '1')
            self.assertEqual(self.controller.delete.wsgi_code, 204)

    def test_services_delete_not_found(self):
        self.ext_mgr.extensions['os-extended-services-delete'] = True

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, self.admin_req, 'abc')

    # This test is just to verify that the servicegroup API gets used when
    # calling the API
    def test_services_with_exception(self):
        def dummy_is_up(self, dummy):
            raise KeyError()

        self.stubs.Set(db_driver.DbDriver, 'is_up', dummy_is_up)
        req = FakeRequestWithHostService()
        self.assertRaises(self.service_is_up_exc, self.controller.index, req)


class ServicesTestV20(ServicesTestV21):
    service_is_up_exc = KeyError
    bad_request = webob.exc.HTTPBadRequest

    def _set_up_controller(self):
        self.controller = services_v2.ServiceController(self.ext_mgr)

    def test_services_delete_not_enabled(self):
        self.assertRaises(webob.exc.HTTPMethodNotAllowed,
                          self.controller.delete, self.admin_req, '300')

    def _process_output(self, services, has_disabled=False, has_id=False):
        for service in services['services']:
            if not has_disabled:
                service.pop('disabled_reason')
            if not has_id:
                service.pop('id')
        return services


class ServicesCellsTestV21(test.TestCase):

    def setUp(self):
        super(ServicesCellsTestV21, self).setUp()

        host_api = cells_api.HostAPI()

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self._set_up_controller()
        self.controller.host_api = host_api

        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(timeutils, "utcnow_ts", fake_utcnow_ts)

        services_list = []
        for service in fake_services_list:
            service = service.copy()
            service['id'] = 'cell1@%d' % service['id']
            services_list.append(service)

        self.stubs.Set(host_api.cells_rpcapi, "service_get_all",
                       fake_service_get_all(services_list))

    def _set_up_controller(self):
        self.controller = services_v21.ServiceController()

    def _process_out(self, res_dict):
        for res in res_dict['services']:
            res.pop('disabled_reason')

    def test_services_detail(self):
        self.ext_mgr.extensions['os-extended-services-delete'] = True
        req = FakeRequest()
        res_dict = self.controller.index(req)
        utc = iso8601.iso8601.Utc()
        response = {'services': [
                    {'id': 'cell1@1',
                     'binary': 'nova-scheduler',
                     'host': 'host1',
                     'zone': 'internal',
                     'status': 'disabled',
                     'state': 'up',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2,
                                                     tzinfo=utc)},
                    {'id': 'cell1@2',
                     'binary': 'nova-compute',
                     'host': 'host1',
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'up',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5,
                                                     tzinfo=utc)},
                    {'id': 'cell1@3',
                     'binary': 'nova-scheduler',
                     'host': 'host2',
                     'zone': 'internal',
                     'status': 'enabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34,
                                                     tzinfo=utc)},
                    {'id': 'cell1@4',
                     'binary': 'nova-compute',
                     'host': 'host2',
                     'zone': 'nova',
                     'status': 'disabled',
                     'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38,
                                                     tzinfo=utc)}]}
        self._process_out(res_dict)
        self.assertEqual(res_dict, response)


class ServicesCellsTestV20(ServicesCellsTestV21):

    def _set_up_controller(self):
        self.controller = services_v2.ServiceController(self.ext_mgr)

    def _process_out(self, res_dict):
        pass
