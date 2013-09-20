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

from nova.api.openstack.compute.plugins.v3 import flavor_manage
from nova.compute import flavors
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


def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                flavorid, swap, rxtx_factor, is_public):
    if flavorid is None:
        flavorid = 1234
    newflavor = fake_get_flavor_by_flavor_id(flavorid,
                                                    read_deleted="no")

    newflavor["name"] = name
    newflavor["memory_mb"] = int(memory_mb)
    newflavor["vcpus"] = int(vcpus)
    newflavor["root_gb"] = int(root_gb)
    newflavor["ephemeral_gb"] = int(ephemeral_gb)
    newflavor["swap"] = swap
    newflavor["rxtx_factor"] = float(rxtx_factor)
    newflavor["is_public"] = bool(is_public)

    return newflavor


class FlavorManageTest(test.NoDBTestCase):
    def setUp(self):
        super(FlavorManageTest, self).setUp()
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_get_flavor_by_flavor_id)
        self.stubs.Set(flavors, "destroy", fake_destroy)
        self.stubs.Set(flavors, "create", fake_create)
        self.controller = flavor_manage.FlavorManageController()
        self.app = fakes.wsgi_app_v3(init_only=('servers', 'flavors',
                                                'flavor-manage',
                                                'os-flavor-rxtx',
                                                'os-flavor-access'))

        self.expected_flavor = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": 1234,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }

    def test_delete(self):
        req = fakes.HTTPRequest.blank('/v3/flavors/1234')
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
            self.assertEquals(body["flavor"][key], expected["flavor"][key])

    def test_create_public_default(self):
        flavor = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": 1234,
                "swap": 512,
                "rxtx_factor": 1,
            }
        }

        expected = self.expected_flavor
        self.stubs.Set(flavors, "create", fake_create)
        url = '/v3/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(flavor)
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for key in expected["flavor"]:
            self.assertEquals(body["flavor"][key], expected["flavor"][key])

    def test_create_without_flavorid(self):
        expected = self.expected_flavor
        del expected['flavor']['id']

        url = '/v3/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dumps(expected)
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)

        for key in expected["flavor"]:
            self.assertEquals(body["flavor"][key], expected["flavor"][key])

    def test_flavor_exists_exception_returns_409(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "ephemeral": 1,
                "id": 1235,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }

        def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                        flavorid, swap, rxtx_factor, is_public):
            raise exception.InstanceTypeExists(name=name)

        self.stubs.Set(flavors, "create", fake_create)
        url = '/v3/flavors'
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
