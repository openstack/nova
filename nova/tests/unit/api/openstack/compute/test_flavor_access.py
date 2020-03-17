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

import mock
from webob import exc

from nova.api.openstack import api_version_request as api_version
from nova.api.openstack.compute import flavor_access \
        as flavor_access_v21
from nova.api.openstack.compute import flavors as flavors_api
from nova import context
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
        'created_at': datetime.datetime(2012, 1, 1, 1, 1, 1, 1),
        'updated_at': None,
        'memory_mb': 512,
        'vcpus': 1,
        'swap': 512,
        'rxtx_factor': 1.0,
        'disabled': False,
        'extra_specs': {},
        'vcpu_weight': None,
        'is_public': bool(ispublic),
        'description': None
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
            res.append(access['project_id'])
    return res


def fake_get_flavor_by_flavor_id(context, flavorid):
    return INSTANCE_TYPES[flavorid]


def _has_flavor_access(flavorid, projectid):
    for access in ACCESS_LIST:
        if (access['flavor_id'] == flavorid and
                access['project_id'] == projectid):
            return True
    return False


def fake_get_all_flavors_sorted_list(context, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    if filters is None or filters['is_public'] is None:
        return sorted(INSTANCE_TYPES.values(), key=lambda item: item[sort_key])

    res = {}
    for k, v in INSTANCE_TYPES.items():
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

    def is_legacy_v2(self):
        return False


class FakeResponse(object):
    obj = {'flavor': {'id': '0'},
           'flavors': [
               {'id': '0'},
               {'id': '2'}]
    }

    def attach(self, **kwargs):
        pass


def fake_get_flavor_projects_from_db(context, flavorid):
    raise exception.FlavorNotFound(flavor_id=flavorid)


class FlavorAccessTestV21(test.NoDBTestCase):
    api_version = "2.1"
    FlavorAccessController = flavor_access_v21.FlavorAccessController
    FlavorActionController = flavor_access_v21.FlavorActionController
    _prefix = "/v2/%s" % fakes.FAKE_PROJECT_ID
    validation_ex = exception.ValidationError

    def setUp(self):
        super(FlavorAccessTestV21, self).setUp()
        self.flavor_controller = flavors_api.FlavorsController()
        # We need to stub out verify_project_id so that it doesn't
        # generate an EndpointNotFound exception and result in a
        # server error.
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)

        self.req = FakeRequest()
        self.req.environ = {"nova.context": context.RequestContext(
            'fake_user', fakes.FAKE_PROJECT_ID)}
        self.stub_out('nova.objects.Flavor._flavor_get_by_flavor_id_from_db',
                      fake_get_flavor_by_flavor_id)
        self.stub_out('nova.objects.flavor._flavor_get_all_from_db',
                      fake_get_all_flavors_sorted_list)
        self.stub_out('nova.objects.flavor._get_projects_from_db',
                      fake_get_flavor_access_by_flavor_id)

        self.flavor_access_controller = self.FlavorAccessController()
        self.flavor_action_controller = self.FlavorActionController()

    def _verify_flavor_list(self, result, expected):
        # result already sorted by flavor_id
        self.assertEqual(len(result), len(expected))

        for d1, d2 in zip(result, expected):
            self.assertEqual(d1['id'], d2['id'])

    @mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db',
                side_effect=exception.FlavorNotFound(flavor_id='foo'))
    def test_list_flavor_access_public(self, mock_api_get):
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

    def test_list_flavor_with_admin_default_proj1(self):
        expected = {'flavors': [{'id': '0'}, {'id': '1'}]}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors',
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

    def test_add_tenant_access(self):
        def stub_add_flavor_access(context, flavor_id, projectid):
            self.assertEqual(3, flavor_id, "flavor_id")
            self.assertEqual("proj2", projectid, "projectid")
        self.stub_out('nova.objects.Flavor._flavor_add_project',
                      stub_add_flavor_access)
        expected = {'flavor_access':
            [{'flavor_id': '3', 'tenant_id': 'proj3'}]}
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)

        result = self.flavor_action_controller._add_tenant_access(
            req, '3', body=body)
        self.assertEqual(result, expected)

    @mock.patch('nova.objects.Flavor.get_by_flavor_id',
                side_effect=exception.FlavorNotFound(flavor_id='1'))
    def test_add_tenant_access_with_flavor_not_found(self, mock_get):
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body=body)

    def test_add_tenant_access_with_no_tenant(self):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        body = {'addTenantAccess': {'foo': 'proj2'}}
        self.assertRaises(self.validation_ex,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body=body)
        body = {'addTenantAccess': {'tenant': ''}}
        self.assertRaises(self.validation_ex,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body=body)

    def test_add_tenant_access_with_already_added_access(self):
        def stub_add_flavor_access(context, flavorid, projectid):
            raise exception.FlavorAccessExists(flavor_id=flavorid,
                                               project_id=projectid)
        self.stub_out('nova.objects.Flavor._flavor_add_project',
                      stub_add_flavor_access)
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        self.assertRaises(exc.HTTPConflict,
                          self.flavor_action_controller._add_tenant_access,
                          self.req, '3', body=body)

    def test_remove_tenant_access_with_bad_access(self):
        def stub_remove_flavor_access(context, flavorid, projectid):
            raise exception.FlavorAccessNotFound(flavor_id=flavorid,
                                                 project_id=projectid)
        self.stub_out('nova.objects.Flavor._flavor_del_project',
                      stub_remove_flavor_access)
        body = {'removeTenantAccess': {'tenant': 'proj2'}}
        self.assertRaises(exc.HTTPNotFound,
                          self.flavor_action_controller._remove_tenant_access,
                          self.req, '3', body=body)

    def test_add_tenant_access_is_public(self):
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        req.api_version_request = api_version.APIVersionRequest('2.7')
        self.assertRaises(exc.HTTPConflict,
                          self.flavor_action_controller._add_tenant_access,
                          req, '1', body=body)

    @mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db',
                side_effect=exception.FlavorNotFound(flavor_id='foo'))
    def test_delete_tenant_access_with_no_tenant(self, mock_api_get):
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        body = {'removeTenantAccess': {'foo': 'proj2'}}
        self.assertRaises(self.validation_ex,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '2', body=body)
        body = {'removeTenantAccess': {'tenant': ''}}
        self.assertRaises(self.validation_ex,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '2', body=body)

    @mock.patch('nova.api.openstack.identity.verify_project_id',
                side_effect=exc.HTTPBadRequest(
                    explanation="Project ID proj2 is not a valid project."))
    def test_add_tenant_access_with_invalid_tenant(self, mock_verify):
        """Tests the case that the tenant does not exist in Keystone."""
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        body = {'addTenantAccess': {'tenant': 'proj2'}}
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._add_tenant_access,
                          req, '2', body=body)
        mock_verify.assert_called_once_with(
            req.environ['nova.context'], 'proj2')

    @mock.patch('nova.api.openstack.identity.verify_project_id',
                side_effect=exc.HTTPBadRequest(
                    explanation="Project ID proj2 is not a valid project."))
    def test_remove_tenant_access_with_invalid_tenant(self, mock_verify):
        """Tests the case that the tenant does not exist in Keystone."""
        req = fakes.HTTPRequest.blank(self._prefix + '/flavors/2/action',
                                      use_admin_context=True)
        body = {'removeTenantAccess': {'tenant': 'proj2'}}
        self.assertRaises(exc.HTTPBadRequest,
                          self.flavor_action_controller._remove_tenant_access,
                          req, '2', body=body)
        mock_verify.assert_called_once_with(
            req.environ['nova.context'], 'proj2')
