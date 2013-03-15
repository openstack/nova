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

from nova.api.openstack.compute.contrib import services
from nova import availability_zones
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes


fake_services_list = [
        {'binary': 'nova-scheduler',
         'host': 'host1',
         'id': 1,
         'disabled': True,
         'topic': 'scheduler',
         'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
         'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27)},
        {'binary': 'nova-compute',
         'host': 'host1',
         'id': 2,
         'disabled': True,
         'topic': 'compute',
         'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
         'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27)},
        {'binary': 'nova-scheduler',
         'host': 'host2',
         'id': 3,
         'disabled': False,
         'topic': 'scheduler',
         'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34),
         'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28)},
        {'binary': 'nova-compute',
         'host': 'host2',
         'id': 4,
         'disabled': True,
         'topic': 'compute',
         'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
         'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28)},
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
    return None


def fake_service_get_by_id(value):
    for service in fake_services_list:
        if service['id'] == value:
            return service
    return None


def fake_service_update(context, service_id, values):
    service = fake_service_get_by_id(service_id)
    if service is None:
        raise exception.ServiceNotFound(service_id=service_id)
    else:
        {'host': 'host1', 'service': 'nova-compute',
         'disabled': values['disabled']}


def fake_utcnow():
    return datetime.datetime(2012, 10, 29, 13, 42, 11)


class ServicesTest(test.TestCase):

    def setUp(self):
        super(ServicesTest, self).setUp()

        self.context = context.get_admin_context()
        self.controller = services.ServiceController()

        self.stubs.Set(self.controller.host_api, "service_get_all",
                       fake_host_api_service_get_all)
        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(db, "service_get_by_args",
                       fake_service_get_by_host_binary)
        self.stubs.Set(db, "service_update", fake_service_update)

    def test_services_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'nova-scheduler',
                    'host': 'host1', 'zone': 'internal',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2)},
                    {'binary': 'nova-compute',
                     'host': 'host1', 'zone': 'nova',
                     'status': 'disabled', 'state': 'up',
                     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
                    {'binary': 'nova-scheduler', 'host': 'host2',
                     'zone': 'internal',
                     'status': 'enabled', 'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34)},
                    {'binary': 'nova-compute', 'host': 'host2',
                     'zone': 'nova',
                     'status': 'disabled', 'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_host(self):
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'nova-scheduler', 'host': 'host1',
                    'zone': 'internal',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2)},
                   {'binary': 'nova-compute', 'host': 'host1',
                    'zone': 'nova',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_service(self):
        req = FakeRequestWithService()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'nova-compute', 'host': 'host1',
                    'zone': 'nova',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
                    {'binary': 'nova-compute', 'host': 'host2',
                     'zone': 'nova',
                     'status': 'disabled', 'state': 'down',
                     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_host_service(self):
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'nova-compute', 'host': 'host1',
                    'zone': 'nova',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5)}]}
        self.assertEqual(res_dict, response)

    def test_services_enable(self):
        body = {'host': 'host1', 'binary': 'nova-compute'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/enable')
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual(res_dict['service']['status'], 'enabled')

    def test_services_disable(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/disable')
        body = {'host': 'host1', 'binary': 'nova-compute'}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual(res_dict['service']['status'], 'disabled')
