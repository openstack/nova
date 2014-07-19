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

from nova.api.openstack.compute.plugins.v3 import flavor_access
from nova.api.openstack.compute.plugins.v3 import flavor_manage
from nova.api.openstack.compute.plugins.v3 import flavor_rxtx
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


def fake_get_flavor_by_flavor_id(flavorid, ctxt=None, read_deleted='yes'):
    if flavorid == 'failtest':
        raise exception.FlavorNotFound("Not found!")
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
    newflavor["disabled"] = bool(kwargs.get('disabled'))

    return newflavor


class FlavorManageTest(test.NoDBTestCase):
    def setUp(self):
        super(FlavorManageTest, self).setUp()
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_get_flavor_by_flavor_id)
        self.stubs.Set(flavors, "destroy", fake_destroy)
        self.stubs.Set(db, "flavor_create", fake_create)
        self.controller = flavor_manage.FlavorManageController()
        self.app = fakes.wsgi_app_v3(init_only=('servers', 'flavors',
                                                'flavor-manage',
                                                'os-flavor-rxtx',
                                                'flavor-access'))

        self.base_request_dict = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": unicode('1234'),
                "swap": 512,
                "%s:rxtx_factor" % flavor_rxtx.ALIAS: 1,
                "flavor-access:is_public": True,
            }
        }

        self.expected_flavor = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": unicode('1234'),
                "swap": 512,
                "%s:rxtx_factor" % flavor_rxtx.ALIAS: 1,
                "flavor-access:is_public": True,
            }
        }

    def test_delete(self):
        req = fakes.HTTPRequestV3.blank('/flavors/1234')
        res = self.controller._delete(req, 1234)
        self.assertEqual(res.status_int, 204)

        # subsequent delete should fail
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._delete, req, "failtest")

    def test_create(self):
        expected = self.expected_flavor
        url = '/v3/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(expected)
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])

    def test_create_public_default(self):
        expected = self.expected_flavor
        res = self._create_flavor_helper(self.base_request_dict)
        body = jsonutils.loads(res.body)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])

    def _create_flavor_helper(self, request_dict):
        url = '/v3/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(request_dict)
        return req.get_response(self.app)

    def _test_create_bad_request(self, request_dict):
        res = self._create_flavor_helper(request_dict)
        self.assertEqual(400, res.status_int)

    def test_create_without_flavor(self):
        body = {'foo': None}
        self._test_create_bad_request(body)

    def test_create_without_flavorid(self):
        expected = self.expected_flavor
        expected['flavor']['id'] = None

        res = self._create_flavor_helper(expected)
        body = jsonutils.loads(res.body)

        for key in expected["flavor"]:
            if key != 'id':
                self.assertEqual(body["flavor"][key], expected["flavor"][key])

    def test_flavor_exists_exception_returns_409(self):
        expected = self.expected_flavor
        expected['flavor']['id'] = 1235

        def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                        flavorid, swap, rxtx_factor, is_public):
            raise exception.FlavorExists(name=name)

        self.stubs.Set(flavors, "create", fake_create)
        res = self._create_flavor_helper(expected)
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

    def test_create_flavorid_with_leading_trailing_whitespaces(self):
        id = " 1234 "
        self.base_request_dict['flavor']['id'] = id
        self._test_create_bad_request(self.base_request_dict)

    def test_create_without_name(self):
        del self.base_request_dict['flavor']['name']
        self._test_create_bad_request(self.base_request_dict)

    def test_create_all_whitespace_flavor_names_are_rejected(self):
        name = " "
        self.base_request_dict['flavor']['name'] = name
        self._test_create_bad_request(self.base_request_dict)

    def test_create_flavor_name_with_leading_trailing_whitespaces(self):
        # Common "name" is defined in I05391a03f383cac1d475cd4266cf7f5ced664f9e
        name = " test "
        self.base_request_dict['flavor']['name'] = name
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_name_too_long(self):
        name = 'a' * 256
        self.base_request_dict['flavor']['name'] = name
        self._test_create_bad_request(self.base_request_dict)

    def test_create_without_ram(self):
        del self.base_request_dict['flavor']['ram']
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_0_ram(self):
        ram = 0
        self.base_request_dict['flavor']['ram'] = ram
        self._test_create_bad_request(self.base_request_dict)

    def test_create_without_vcpus(self):
        del self.base_request_dict['flavor']['vcpus']
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_0_vcpus(self):
        vcpus = 0
        self.base_request_dict['flavor']['vcpus'] = vcpus
        self._test_create_bad_request(self.base_request_dict)

    def test_create_without_disk(self):
        del self.base_request_dict['flavor']['disk']
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_minus_disk(self):
        disk = -1
        self.base_request_dict['flavor']['disk'] = disk
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_minus_ephemeral(self):
        ephemeral = -1
        self.base_request_dict['flavor']['ephemeral'] = ephemeral
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_minus_swap(self):
        swap = -1
        self.base_request_dict['flavor']['swap'] = swap
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_minus_rxtx_factor(self):
        rxtx_factor = -1
        self.base_request_dict['flavor'][('%s:rxtx_factor'
            % flavor_rxtx.ALIAS)] = rxtx_factor
        self._test_create_bad_request(self.base_request_dict)

    def test_create_with_non_boolean_is_public(self):
        is_public = 1234
        self.base_request_dict['flavor']['flavor-access:is_public'] = is_public
        self._test_create_bad_request(self.base_request_dict)


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

        self.controller = flavor_manage.FlavorManageController()
        self.flavor_access_controller = flavor_access.FlavorAccessController()
        self.app = fakes.wsgi_app(init_only=('flavors',))

        self.base_request_dict = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": unicode('1234'),
                "swap": 512,
                "%s:rxtx_factor" % flavor_rxtx.ALIAS: 1,
                "flavor-access:is_public": False
            }
        }

    def test_create_private_flavor_should_create_flavor_access(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1
            }
        }

        ctxt = context.RequestContext('fake', 'fake',
                                      is_admin=True, auth_token=True)
        url = '/os-flavor-manage'

        req = fakes.HTTPRequestV3.blank(url, use_admin_context=True)
        body = self.controller._create(req, body=self.base_request_dict)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])
        flavor_access_body = self.flavor_access_controller.index(
            FakeRequest(), body["flavor"]["id"])
        expected_flavor_access_body = {
            "tenant_id": "%s" % ctxt.project_id,
            "flavor_id": "%s" % body["flavor"]["id"]
        }
        self.assertIn(expected_flavor_access_body,
                      flavor_access_body["flavor_access"])

    def test_create_public_flavor_should_not_create_flavor_access(self):
        self.base_request_dict['flavor']['flavor-access:is_public'] = True
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1
            }
        }

        self.mox.StubOutWithMock(flavors, "add_flavor_access")
        self.mox.ReplayAll()
        url = '/os-flavor-manage'
        req = fakes.HTTPRequestV3.blank(url, use_admin_context=True)
        body = self.controller._create(req, body=self.base_request_dict)
        for key in expected["flavor"]:
            self.assertEqual(body["flavor"][key], expected["flavor"][key])
