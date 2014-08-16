# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

import datetime

import webob

from nova.api.openstack.compute.contrib import flavor_access
from nova.api.openstack.compute.contrib import flavormanage
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


def fake_get_flavor_by_flavor_id(flavorid, ctxt=None, read_deleted='yes'):
    if flavorid == 'failtest':
        raise exception.NotFound("Not found sucka!")
    elif not str(flavorid) == '1234':
        raise Exception("This test expects flavorid 1234, not %s" % flavorid)
    if read_deleted != 'no':
        raise test.TestingException("Should not be reading deleted")

    return {
        'root_gb': 1,
        'ephemeral_gb': 1,
        'name': u'frob',
        'deleted': False,
        'created_at': datetime.datetime(2012, 1, 19, 18, 49, 30, 877329),
        'updated_at': None,
        'memory_mb': 256,
        'vcpus': 1,
        'flavorid': flavorid,
        'swap': 0,
        'rxtx_factor': 1.0,
        'extra_specs': {},
        'deleted_at': None,
        'vcpu_weight': None,
        'id': 7,
        'is_public': True,
        'disabled': False,
    }


def fake_destroy(flavorname):
    pass


def fake_create(context, kwargs):
    flavorid = kwargs.get('flavorid')
    if flavorid is None:
        flavorid = 1234

    newflavor = {'flavorid': flavorid}
    newflavor["name"] = kwargs.get('name')
    newflavor["memory_mb"] = int(kwargs.get('memory_mb'))
    newflavor["vcpus"] = int(kwargs.get('vcpus'))
    newflavor["root_gb"] = int(kwargs.get('root_gb'))
    newflavor["ephemeral_gb"] = int(kwargs.get('ephemeral_gb'))
    newflavor["swap"] = kwargs.get('swap')
    newflavor["rxtx_factor"] = float(kwargs.get('rxtx_factor'))
    newflavor["is_public"] = bool(kwargs.get('is_public'))

    return newflavor


class FlavorManageTest(test.NoDBTestCase):
    def setUp(self):
        super(FlavorManageTest, self).setUp()
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_get_flavor_by_flavor_id)
        self.stubs.Set(flavors, "destroy", fake_destroy)
        self.stubs.Set(db, "flavor_create", fake_create)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Flavormanage', 'Flavorextradata',
                'Flavor_access', 'Flavor_rxtx', 'Flavor_swap'])

        self.controller = flavormanage.FlavorManageController()
        self.app = fakes.wsgi_app(init_only=('flavors',))

        self.request_body = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": unicode('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        self.expected_flavor = self.request_body

    def test_delete(self):
        req = fakes.HTTPRequest.blank('/v2/123/flavors/1234')
        res = self.controller._delete(req, 1234)
        self.assertEqual(res.status_int, 202)

        # subsequent delete should fail
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._delete, req, "failtest")

    def _create_flavor_success_case(self, body):
        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(200, res.status_code)
        return jsonutils.loads(res.body)

    def test_create(self):
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def test_create_public_default(self):
        del self.request_body['flavor']['os-flavor-access:is_public']
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def test_create_flavor_name_with_leading_trailing_whitespace(self):
        self.request_body['flavor']['name'] = " test "
        body = self._create_flavor_success_case(self.request_body)
        self.assertEqual("test", body["flavor"]["name"])

    def test_create_without_flavorid(self):
        del self.request_body['flavor']['id']
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def _create_flavor_bad_request_case(self, body):
        self.stubs.UnsetAll()

        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(res.status_code, 400)

    def test_create_invalid_name(self):
        self.request_body['flavor']['name'] = 'bad !@#!$% name'
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_flavor_name_is_whitespace(self):
        self.request_body['flavor']['name'] = ' '
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_name_too_long(self):
        self.request_body['flavor']['name'] = 'a' * 256
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_flavorname(self):
        del self.request_body['flavor']['name']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_empty_body(self):
        body = {
            "flavor": {}
        }
        self._create_flavor_bad_request_case(body)

    def test_create_no_body(self):
        body = {}
        self._create_flavor_bad_request_case(body)

    def test_create_invalid_format_body(self):
        body = {
            "flavor": []
        }
        self._create_flavor_bad_request_case(body)

    def test_create_invalid_flavorid(self):
        self.request_body['flavor']['id'] = "!@#!$#!$^#&^$&"
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_check_flavor_id_length(self):
        MAX_LENGTH = 255
        self.request_body['flavor']['id'] = "a" * (MAX_LENGTH + 1)
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_leading_trailing_whitespaces_in_flavor_id(self):
        self.request_body['flavor']['id'] = "   bad_id   "
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_ram(self):
        del self.request_body['flavor']['ram']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_0_ram(self):
        self.request_body['flavor']['ram'] = 0
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_vcpus(self):
        del self.request_body['flavor']['vcpus']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_0_vcpus(self):
        self.request_body['flavor']['vcpus'] = 0
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_disk(self):
        del self.request_body['flavor']['disk']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_disk(self):
        self.request_body['flavor']['disk'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_ephemeral(self):
        self.request_body['flavor']['OS-FLV-EXT-DATA:ephemeral'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_swap(self):
        self.request_body['flavor']['swap'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_rxtx_factor(self):
        self.request_body['flavor']['rxtx_factor'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_non_boolean_is_public(self):
        self.request_body['flavor']['os-flavor-access:is_public'] = 123
        self._create_flavor_bad_request_case(self.request_body)

    def test_flavor_exists_exception_returns_409(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": 1235,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }

        def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                        flavorid, swap, rxtx_factor, is_public):
            raise exception.FlavorExists(name=name)

        self.stubs.Set(flavors, "create", fake_create)
        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(expected)
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 409)

    def test_invalid_memory_mb(self):
        """Check negative and decimal number can't be accepted."""

        self.stubs.UnsetAll()
        self.assertRaises(exception.InvalidInput, flavors.create, "abc",
                          -512, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcd",
                          512.2, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcde",
                          None, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcdef",
                          512, 2, None, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcdef",
                          "test_memory_mb", 2, None, 1, 1234, 512, 1, True)


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}


class PrivateFlavorManageTest(test.TestCase):
    def setUp(self):
        super(PrivateFlavorManageTest, self).setUp()
        # self.stubs.Set(flavors,
        #                "get_flavor_by_flavor_id",
        #                fake_get_flavor_by_flavor_id)
        # self.stubs.Set(flavors, "destroy", fake_destroy)
        # self.stubs.Set(flavors, "create", fake_create)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Flavormanage', 'Flavorextradata',
                'Flavor_access', 'Flavor_rxtx', 'Flavor_swap'])

        self.controller = flavormanage.FlavorManageController()
        self.flavor_access_controller = flavor_access.FlavorAccessController()
        self.app = fakes.wsgi_app(init_only=('flavors',))

    def test_create_private_flavor_should_not_grant_flavor_access(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": False
            }
        }

        ctxt = context.RequestContext('fake', 'fake',
                                      is_admin=True, auth_token=True)
        self.app = fakes.wsgi_app(init_only=('flavors',),
                                  fake_auth_context=ctxt)
        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(expected)
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])
        flavor_access_body = self.flavor_access_controller.index(
            FakeRequest(), body["flavor"]["id"])
        expected_flavor_access_body = {
            "tenant_id": "%s" % ctxt.project_id,
            "flavor_id": "%s" % body["flavor"]["id"]
        }
        self.assertNotIn(expected_flavor_access_body,
                         flavor_access_body["flavor_access"])

    def test_create_public_flavor_should_not_create_flavor_access(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True
            }
        }

        ctxt = context.RequestContext('fake', 'fake',
                                      is_admin=True, auth_token=True)
        self.app = fakes.wsgi_app(init_only=('flavors',),
                                  fake_auth_context=ctxt)
        self.mox.StubOutWithMock(flavors, "add_flavor_access")
        self.mox.ReplayAll()
        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(expected)
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])
