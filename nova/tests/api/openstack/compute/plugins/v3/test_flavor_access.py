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

from lxml import etree
from webob import exc

from nova.api.openstack.compute import flavors as flavors_api
from nova.api.openstack.compute.plugins.v3 import flavor_access
from nova.compute import flavors
from nova import context
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


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


def fake_get_flavor_access_by_flavor_id(flavorid):
    res = []
    for access in ACCESS_LIST:
        if access['flavor_id'] == flavorid:
            res.append(access)
    return res


def fake_get_flavor_by_flavor_id(flavorid, ctxt=None):
    return INSTANCE_TYPES[flavorid]


def _has_flavor_access(flavorid, projectid):
    for access in ACCESS_LIST:
        if access['flavor_id'] == flavorid and \
           access['project_id'] == projectid:
                return True
    return False


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    if filters == None or filters['is_public'] == None:
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


class FlavorAccessTest(test.NoDBTestCase):
    def setUp(self):
        super(FlavorAccessTest, self).setUp()
        self.flavor_controller = flavors_api.Controller()
        self.flavor_access_controller = flavor_access.FlavorAccessController()
        self.flavor_action_controller = flavor_access.FlavorActionController()
        self.req = FakeRequest()
        self.context = self.req.environ['nova.context']
        self.stubs.Set(flavors, 'get_flavor_by_flavor_id',
                       fake_get_flavor_by_flavor_id)
        self.stubs.Set(flavors, 'get_all_flavors_sorted_list',
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(flavors, 'get_flavor_access_by_flavor_id',
                       fake_get_flavor_access_by_flavor_id)

    def _verify_flavor_list(self, result, expected):
        # result already sorted by flavor_id
        self.assertEqual(len(result), len(expected))

        for d1, d2 in zip(result, expected):
            self.assertEqual(d1['id'], d2['id'])

    def test_list_flavor_access_public(self):
        # query flavor-access on public flavor should return 404
        req = fakes.HTTPRequestV3.blank('/flavors/fake/flavor-access',
                                        use_admin_context=True)
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
        req = fakes.HTTPRequestV3.blank('/flavors/2/flavor-access')

        def fake_authorize(context, target=None, action=None):
            raise exception.PolicyNotAuthorized(action='index')

        self.stubs.Set(flavor_access, 'authorize', fake_authorize)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.flavor_access_controller.index,
                          req, '2')

    def test_list_flavor_with_admin_default_proj1(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors',
                                        use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj1'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_default_proj2(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}, {'id': '2'}]}
        req = fakes.HTTPRequestV3.blank('/flavors',
                                        use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj2'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_true(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=true',
                                        use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_false(self):
        expected = {'flavors': [{'id': '2'}, {'id': '3'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=false',
                                        use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_false_proj2(self):
        expected = {'flavors': [{'id': '2'}, {'id': '3'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=false',
                                        use_admin_context=True)
        req.environ['nova.context'].project_id = 'proj2'
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_admin_ispublic_none(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}, {'id': '2'},
                                {'id': '3'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=none',
                                        use_admin_context=True)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_default(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors',
                                        use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_true(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=true',
                                        use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_false(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=false',
                                        use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_list_flavor_with_no_admin_ispublic_none(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequestV3.blank('/flavors?is_public=none',
                                        use_admin_context=False)
        result = self.flavor_controller.index(req)
        self._verify_flavor_list(result['flavors'], expected['flavors'])

    def test_show(self):
        resp = FakeResponse()
        self.flavor_action_controller.show(self.req, resp, '0')
        self.assertEqual({'id': '0', 'flavor-access:is_public': True},
                         resp.obj['flavor'])
        self.flavor_action_controller.show(self.req, resp, '2')
        self.assertEqual({'id': '0', 'flavor-access:is_public': False},
                         resp.obj['flavor'])

    def test_detail(self):
        resp = FakeResponse()
        self.flavor_action_controller.detail(self.req, resp)
        self.assertEqual([{'id': '0', 'flavor-access:is_public': True},
                          {'id': '2', 'flavor-access:is_public': False}],
                         resp.obj['flavors'])

    def test_create(self):
        resp = FakeResponse()
        self.flavor_action_controller.create(self.req, {}, resp)
        self.assertEqual({'id': '0', 'flavor-access:is_public': True},
                         resp.obj['flavor'])

    def test_add_tenant_access(self):
        def stub_add_flavor_access(flavorid, projectid, ctxt=None):
            self.assertEqual('3', flavorid, "flavorid")
            self.assertEqual("proj2", projectid, "projectid")
        self.stubs.Set(flavors, 'add_flavor_access',
                       stub_add_flavor_access)
        expected = {'flavor_access':
            [{'flavor_id': '3', 'tenant_id': 'proj3'}]}
        body = {'add_tenant_access': {'tenant_id': 'proj2'}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        result = self.flavor_action_controller.\
            _add_tenant_access(req, '3', body)
        self.assertEqual(result, expected)

    def test_add_tenant_access_with_non_existed_flavor(self):
        def stub_add_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'add_flavor_access',
                       stub_add_flavor_access)
        body = {'add_tenant_access': {'tenant_id': 'proj2'}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_action_controller._add_tenant_access,
                          req, '3', body)

    def test_add_tenant_access_with_no_admin_user(self):
        req = fakes.HTTPRequestV3.blank('/flavors/2/action')
        body = {'add_tenant_access': {'tenant_id': 'proj2'}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body)

    def test_add_tenant_access_without_policy_check(self):
        req = fakes.HTTPRequestV3.blank('/flavors/2/action')
        body = {'add_tenant_access': {'tenant_id': 'proj2'}}

        def fake_authorize(context, target=None, action=None):
            pass

        self.stubs.Set(flavor_access, 'authorize', fake_authorize)
        self.assertRaises(exc.HTTPForbidden,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body)

    def test_add_tenant_access_without_tenant_id(self):
        def stub_add_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'add_flavor_access',
                       stub_add_flavor_access)
        body = {'add_tenant_access': {}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._add_tenant_access,
                          req, '3', body)

    def test_add_tenant_access_with_invalid_request(self):
        def stub_add_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'add_flavor_access',
                       stub_add_flavor_access)
        body = {'add_tenant_access': None}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._add_tenant_access,
                          req, '3', body)

    def test_add_tenant_access_with_already_added_access(self):
        def stub_add_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorAccessExists(flavor_id=flavorid,
                                               project_id=projectid)
        self.stubs.Set(flavors, 'add_flavor_access',
                       stub_add_flavor_access)
        body = {'add_tenant_access': {'tenant_id': 'proj2'}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPConflict,
                          self.flavor_action_controller._add_tenant_access,
                          req, '3', body)

    def test_remove_tenant_access_with_bad_access(self):
        def stub_remove_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorAccessNotFound(flavor_id=flavorid,
                                                 project_id=projectid)
        self.stubs.Set(flavors, 'remove_flavor_access',
                       stub_remove_flavor_access)
        body = {'remove_tenant_access': {'tenant_id': 'proj2'}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '3', body)

    def test_remove_tenant_access_with_non_existed_flavor(self):
        def stub_remove_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'remove_flavor_access',
                       stub_remove_flavor_access)
        body = {'remove_tenant_access': {'tenant_id': 'proj2'}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '3', body)

    def test_remove_tenant_access_without_tenant_id(self):
        def stub_remove_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'remove_flavor_access',
                       stub_remove_flavor_access)
        body = {'remove_tenant_access': {}}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '3', body)

    def test_remove_tenant_access_with_invalid_request(self):
        def stub_remove_flavor_access(flavorid, projectid, ctxt=None):
            raise exception.FlavorNotFound(flavor_id=flavorid)
        self.stubs.Set(flavors, 'remove_flavor_access',
                       stub_remove_flavor_access)
        body = {'remove_tenant_access': None}
        req = fakes.HTTPRequestV3.blank('/flavors/3/action',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '3', body)

    def test_remove_tenant_access_with_no_admin_user(self):
        req = fakes.HTTPRequestV3.blank('flavors/2/action',
                                        use_admin_context=False)
        body = {'remove_tenant_access': {'tenant_id': 'proj2'}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '2', body)

    def test_remove_tenant_access_without_policy_check(self):
        req = fakes.HTTPRequestV3.blank('/flavors/2/action')
        body = {'remove_tenant_access': {'tenant_id': 'proj2'}}

        def fake_authorize(context, target=None, action=None):
            pass

        self.stubs.Set(flavor_access, 'authorize', fake_authorize)
        self.assertRaises(exc.HTTPForbidden,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '2', body)


class FlavorAccessSerializerTest(test.NoDBTestCase):
    def test_serializer_empty(self):
        serializer = flavor_access.FlavorAccessTemplate()
        text = serializer.serialize(dict(flavor_access=[]))
        tree = etree.fromstring(text)
        self.assertEqual(len(tree), 0)

    def test_serializer(self):
        expected = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<flavor_access>'
                    '<access tenant_id="proj2" flavor_id="2"/>'
                    '<access tenant_id="proj3" flavor_id="2"/>'
                    '</flavor_access>')
        access_list = [{'flavor_id': '2', 'tenant_id': 'proj2'},
                       {'flavor_id': '2', 'tenant_id': 'proj3'}]

        serializer = flavor_access.FlavorAccessTemplate()
        text = serializer.serialize(dict(flavor_access=access_list))
        self.assertEqual(text, expected)
