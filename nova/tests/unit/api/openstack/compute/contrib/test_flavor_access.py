# Copyright 2012 OpenStack Foundation
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

from webob import exc

from nova.api.openstack import api_version_request as api_version
from nova.api.openstack.compute.contrib import flavor_access \
    as flavor_access_v2
from nova.api.openstack.compute import flavors as flavors_api
from nova.api.openstack.compute.plugins.v3 import flavor_access \
    as flavor_access_v3
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


def generate_flavor(flavorid, ispublic):
    return {
        'id': flavorid,
        'flavorid': str(flavorid),
        'root_gb': 1,
        'ephemeral_gb': 1,
        'name': u'test',
        'deleted': False,
        'created_at': datetime.datetime(2012, 1, 1, 1, 1, 1, 1),
        'updated_at': None,
        'memory_mb': 512,
        'vcpus': 1,
        'swap': 512,
        'rxtx_factor': 1.0,
        'disabled': False,
        'extra_specs': {},
        'deleted_at': None,
        'vcpu_weight': None,
        'is_public': bool(ispublic)
    }


INSTANCE_TYPES = {
        '0': generate_flavor(0, True),
        '1': generate_flavor(1, True),
        '2': generate_flavor(2, False),
        '3': generate_flavor(3, False)}


ACCESS_LIST = [{'flavor_id': '2', 'project_id': 'proj2'},
               {'flavor_id': '2', 'project_id': 'proj3'},
               {'flavor_id': '3', 'project_id': 'proj3'}]


def fake_get_flavor_access_by_flavor_id(context, flavorid):
    res = []
    for access in ACCESS_LIST:
        if access['flavor_id'] == flavorid:
            res.append(access)
    return res


def fake_get_flavor_by_flavor_id(context, flavorid, read_deleted=None):
    return INSTANCE_TYPES[flavorid]


def _has_flavor_access(flavorid, projectid):
    for access in ACCESS_LIST:
        if access['flavor_id'] == flavorid and \
           access['project_id'] == projectid:
                return True
    return False


def fake_get_all_flavors_sorted_list(context, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    if filters is None or filters['is_public'] is None:
        return sorted(INSTANCE_TYPES.values(), key=lambda item: item[sort_key])

    res = {}
    for k, v in INSTANCE_TYPES.iteritems():
        if filters['is_public'] and _has_flavor_access(k, context.project_id):
            res.update({k: v})
            continue
        if v['is_public'] == filters['is_public']:
            res.update({k: v})

    res = sorted(res.values(), key=lambda item: item[sort_key])
    return res


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}
    api_version_request = api_version.APIVersionRequest("2.1")

    def get_db_flavor(self, flavor_id):
        return INSTANCE_TYPES[flavor_id]


class FakeResponse(object):
    obj = {'flavor': {'id': '0'},
           'flavors': [
               {'id': '0'},
               {'id': '2'}]
    }

    def attach(self, **kwargs):
        pass


class FlavorAccessTestV21(test.NoDBTestCase):
    api_version = "2.1"
    FlavorAccessController = flavor_access_v3.FlavorAccessController
    FlavorActionController = flavor_access_v3.FlavorActionController
    _prefix = "/v3"
    validation_ex = exception.ValidationError

    def setUp(self):
        super(FlavorAccessTestV21, self).setUp()
        self.flavor_controller = flavors_api.Controller()
        self.req = FakeRequest()
        self.context = self.req.environ['nova.context']
        self.stubs.Set(db, 'flavor_get_by_flavor_id',
                       fake_get_flavor_by_flavor_id)
        self.stubs.Set(db, 'flavor_get_all',
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(db, 'flavor_access_get_by_flavor_id',
                       fake_get_flavor_access_by_flavor_id)

        self.flavor_access_controller = self.FlavorAccessController()
        self.flavor_action_controller = self.FlavorActionController()

    def _verify_flavor_list(self, result, expected):
        # result already sorted by flavor_id
        self.assertEqual(len(result), len(expected))

        for d1, d2 in zip(result, expected):
            self.assertEqual(d1['id'], d2['id'])

    def test_list_flavor_access_public(self):
        # query os-flavor-access on public flavor should return 404
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_access_controller.index,
                          self.req, '1')

    def test_list_flavor_access_private(self):
        expected = {'flavor_access': [
            {'flavor_id': '2', 'tenant_id': 'proj2'},
            {'flavor_id': '2', 'tenant_id': 'proj3'}]}
        result = self.flavor_access_controller.index(self.req, '2')
        self.assertEqual(result, expected)

    def test_list_with_no_context(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/fake/flavors')

        def fake_authorize(context, target=None, action=None):
            raise exception.PolicyNotAuthorized(action='index')

        if self.api_version == "2.1":
            self.stubs.Set(flavor_access_v3,
                           'authorize',
                           fake_authorize)
        else:
            self.stubs.Set(flavor_access_v2,
                           'authorize',
                           fake_authorize)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.flavor_access_controller.index,
                          req, 'fake')

    def test_list_flavor_with_admin_default_proj1(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequest.blank(self._prefix + '/fake/flavors',
                                      use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj1'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_default_proj2(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}, {'id': '2'}]}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors',
                                      use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj2'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_true(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        url = self._prefix + '/flavors?is_public=true'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_false(self):
        expected = {'flavors': [{'id': '2'}, {'id': '3'}]}
        url = self._prefix + '/flavors?is_public=false'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_false_proj2(self):
        expected = {'flavors': [{'id': '2'}, {'id': '3'}]}
        url = self._prefix + '/flavors?is_public=false'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj2'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_none(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}, {'id': '2'},
                                {'id': '3'}]}
        url = self._prefix + '/flavors?is_public=none'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_default(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors',
                                      use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_true(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        url = self._prefix + '/flavors?is_public=true'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_false(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        url = self._prefix + '/flavors?is_public=false'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_none(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        url = self._prefix + '/flavors?is_public=none'
        req = fakes.HTTPRequest.blank(url,
                                      use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_show(self):
        resp = FakeResponse()
        self.flavor_action_controller.show(self.req, resp, '0')
        self.assertEqual({'id': '0', 'os-flavor-access:is_public': True},
                         resp.obj['flavor'])
        self.flavor_action_controller.show(self.req, resp, '2')
        self.assertEqual({'id': '0', 'os-flavor-access:is_public': False},
                         resp.obj['flavor'])

    def test_detail(self):
        resp = FakeResponse()
        self.flavor_action_controller.detail(self.req, resp)
        self.assertEqual([{'id': '0', 'os-flavor-access:is_public': True},
                          {'id': '2', 'os-flavor-access:is_public': False}],
                         resp.obj['flavors'])

    def test_create(self):
        resp = FakeResponse()
        self.flavor_action_controller.create(self.req, {}, resp)
        self.assertEqual({'id': '0', 'os-flavor-access:is_public': True},
                         resp.obj['flavor'])

    def _get_add_access(self):
        if self.api_version == "2.1":
            return self.flavor_action_controller._add_tenant_access
        else:
            return self.flavor_action_controller._addTenantAccess

    def _get_remove_access(self):
        if self.api_version == "2.1":
            return self.flavor_action_controller._remove_tenant_access
        else:
            return self.flavor_action_controller._removeTenantAccess

    def test_add_tenant_access(self):
        def stub_add_flavor_access(context, flavorid, projectid):
            self.assertEqual('3', flavorid, "flavorid")
            self.assertEqual("proj2", projectid, "projectid")
        self.stubs.Set(db, 'flavor_access_add',
                       stub_add_flavor_access)
        expected = {'flavor_access':
            [{'flavor_id': '3', 'tenant_id': 'proj3'}]}
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)

        add_access = self._get_add_access()
        result = add_access(req, '3', body=body)
        self.assertEqual(result, expected)

    def test_add_tenant_access_with_no_admin_user(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=False)
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        add_access = self._get_add_access()
        self.assertRaises(exception.PolicyNotAuthorized,
                          add_access, req, '2', body=body)

    def test_add_tenant_access_with_no_tenant(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        body = {'addTenantAccess': {'foo': 'proj2'}}
        add_access = self._get_add_access()
        self.assertRaises(self.validation_ex,
                          add_access, req, '2', body=body)
        body = {'addTenantAccess': {'tenant': ''}}
        self.assertRaises(self.validation_ex,
                          add_access, req, '2', body=body)

    def test_add_tenant_access_with_already_added_access(self):
        def stub_add_flavor_access(context, flavorid, projectid):
            raise exception.FlavorAccessExists(flavor_id=flavorid,
                                               project_id=projectid)
        self.stubs.Set(db, 'flavor_access_add',
                       stub_add_flavor_access)
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        add_access = self._get_add_access()
        self.assertRaises(exc.HTTPConflict,
                          add_access, self.req, '3', body=body)

    def test_remove_tenant_access_with_bad_access(self):
        def stub_remove_flavor_access(context, flavorid, projectid):
            raise exception.FlavorAccessNotFound(flavor_id=flavorid,
                                                 project_id=projectid)
        self.stubs.Set(db, 'flavor_access_remove',
                       stub_remove_flavor_access)
        body = {'removeTenantAccess': {'tenant': 'proj2'}}
        remove_access = self._get_remove_access()
        self.assertRaises(exc.HTTPNotFound,
                          remove_access, self.req, '3', body=body)

    def test_delete_tenant_access_with_no_tenant(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        remove_access = self._get_remove_access()
        body = {'removeTenantAccess': {'foo': 'proj2'}}
        self.assertRaises(self.validation_ex,
                          remove_access, req, '2', body=body)
        body = {'removeTenantAccess': {'tenant': ''}}
        self.assertRaises(self.validation_ex,
                          remove_access, req, '2', body=body)

    def test_remove_tenant_access_with_no_admin_user(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=False)
        body = {'removeTenantAccess': {'tenant': 'proj2'}}
        remove_access = self._get_remove_access()
        self.assertRaises(exception.PolicyNotAuthorized,
                          remove_access, req, '2', body=body)


class FlavorAccessTestV20(FlavorAccessTestV21):
    api_version = "2.0"
    FlavorAccessController = flavor_access_v2.FlavorAccessController
    FlavorActionController = flavor_access_v2.FlavorActionController
    _prefix = "/v2/fake"
    validation_ex = exc.HTTPBadRequest
