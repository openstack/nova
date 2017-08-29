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

import mock
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import used_limits \
        as used_limits_v21
from nova.api.openstack import wsgi
import nova.context
from nova import exception
from nova.policies import used_limits as ul_policies
from nova import quota
from nova import test


class FakeRequest(object):
    def __init__(self, context, reserved=False):
        self.environ = {'nova.context': context}
        self.reserved = reserved

        self.api_version_request = api_version_request.min_api_version()
        if reserved:
            self.GET = webob.request.MultiDict({'reserved': 1})
        else:
            self.GET = webob.request.MultiDict({})

    def is_legacy_v2(self):
        return False


class UsedLimitsTestCaseV21(test.NoDBTestCase):
    used_limit_extension = "os_compute_api:os-used-limits"
    include_server_group_quotas = True

    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCaseV21, self).setUp()
        self._set_up_controller()
        self.fake_context = nova.context.RequestContext('fake', 'fake')

    def _set_up_controller(self):
        self.controller = used_limits_v21.UsedLimitsController()
        patcher = self.mock_can = mock.patch('nova.context.RequestContext.can')
        self.mock_can = patcher.start()
        self.addCleanup(patcher.stop)

    def _do_test_used_limits(self, reserved):
        fake_req = FakeRequest(self.fake_context, reserved=reserved)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)
        quota_map = {
            'totalRAMUsed': 'ram',
            'totalCoresUsed': 'cores',
            'totalInstancesUsed': 'instances',
            'totalFloatingIpsUsed': 'floating_ips',
            'totalSecurityGroupsUsed': 'security_groups',
            'totalServerGroupsUsed': 'server_groups',
        }
        limits = {}
        expected_abs_limits = []
        for display_name, q in quota_map.items():
            limits[q] = {'limit': len(display_name),
                         'in_use': len(display_name) / 2,
                         'reserved': 0}
            if (self.include_server_group_quotas or
                display_name != 'totalServerGroupsUsed'):
                expected_abs_limits.append(display_name)

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits

        self.stub_out('nova.quota.QUOTAS.get_project_quotas',
                      stub_get_project_quotas)

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        for limit in expected_abs_limits:
            value = abs_limits[limit]
            r = limits[quota_map[limit]]['reserved'] if reserved else 0
            self.assertEqual(limits[quota_map[limit]]['in_use'] + r, value)

    def test_used_limits_basic(self):
        self._do_test_used_limits(False)

    def test_used_limits_with_reserved(self):
        self._do_test_used_limits(True)

    def test_admin_can_fetch_limits_for_a_given_tenant_id(self):
        project_id = "123456"
        user_id = "A1234"
        tenant_id = 'abcd'
        self.fake_context.project_id = project_id
        self.fake_context.user_id = user_id
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        target = {
            "project_id": tenant_id,
            "user_id": user_id
        }
        fake_req = FakeRequest(self.fake_context)
        fake_req.GET = webob.request.MultiDict({'tenant_id': tenant_id})

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                              return_value={}) as mock_get_quotas:
            res = wsgi.ResponseObject(obj)
            self.controller.index(fake_req, res)
            self.mock_can.assert_called_once_with(ul_policies.BASE_POLICY_NAME,
                                                  target)
            mock_get_quotas.assert_called_once_with(self.fake_context,
                tenant_id, usages=True)

    def _test_admin_can_fetch_used_limits_for_own_project(self, req_get):
        project_id = "123456"
        if 'tenant_id' in req_get:
            project_id = req_get['tenant_id']

        user_id = "A1234"
        self.fake_context.project_id = project_id
        self.fake_context.user_id = user_id
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        fake_req = FakeRequest(self.fake_context)
        fake_req.GET = webob.request.MultiDict(req_get)

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:
            res = wsgi.ResponseObject(obj)
            self.controller.index(fake_req, res)

            mock_get_quotas.assert_called_once_with(self.fake_context,
                project_id, usages=True)

    def test_admin_can_fetch_used_limits_for_own_project(self):
        req_get = {}
        self._test_admin_can_fetch_used_limits_for_own_project(req_get)

    def test_admin_can_fetch_used_limits_for_dummy_only(self):
        # for back compatible we allow additional param to be send to req.GET
        # it can be removed when we add restrictions to query param later
        req_get = {'dummy': 'dummy'}
        self._test_admin_can_fetch_used_limits_for_own_project(req_get)

    def test_admin_can_fetch_used_limits_with_positive_int(self):
        req_get = {'tenant_id': 123}
        self._test_admin_can_fetch_used_limits_for_own_project(req_get)

    def test_admin_can_fetch_used_limits_with_negative_int(self):
        req_get = {'tenant_id': -1}
        self._test_admin_can_fetch_used_limits_for_own_project(req_get)

    def test_admin_can_fetch_used_limits_with_unkown_param(self):
        req_get = {'tenant_id': '123', 'unknown': 'unknown'}
        self._test_admin_can_fetch_used_limits_for_own_project(req_get)

    def test_non_admin_cannot_fetch_used_limits_for_any_other_project(self):
        project_id = "123456"
        user_id = "A1234"
        tenant_id = "abcd"
        self.fake_context.project_id = project_id
        self.fake_context.user_id = user_id
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        target = {
            "project_id": tenant_id,
            "user_id": user_id
        }
        fake_req = FakeRequest(self.fake_context)
        fake_req.GET = webob.request.MultiDict({'tenant_id': tenant_id})

        self.mock_can.side_effect = exception.PolicyNotAuthorized(
            action=self.used_limit_extension)

        res = wsgi.ResponseObject(obj)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index,
                          fake_req, res)

        self.mock_can.assert_called_once_with(ul_policies.BASE_POLICY_NAME,
                                              target)

    def test_used_limits_fetched_for_context_project_id(self):
        project_id = "123456"
        self.fake_context.project_id = project_id
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        fake_req = FakeRequest(self.fake_context)

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:
            res = wsgi.ResponseObject(obj)
            self.controller.index(fake_req, res)

            mock_get_quotas.assert_called_once_with(self.fake_context,
                project_id, usages=True)

    def test_used_ram_added(self):
        fake_req = FakeRequest(self.fake_context)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {
                    "maxTotalRAMSize": 512,
                },
            },
        }
        res = wsgi.ResponseObject(obj)

        def stub_get_project_quotas(context, project_id, usages=True):
            return {'ram': {'limit': 512, 'in_use': 256}}

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               side_effect=stub_get_project_quotas
                               ) as mock_get_quotas:

            self.controller.index(fake_req, res)
            abs_limits = res.obj['limits']['absolute']
            self.assertIn('totalRAMUsed', abs_limits)
            self.assertEqual(256, abs_limits['totalRAMUsed'])
            self.assertEqual(1, mock_get_quotas.call_count)

    def test_no_ram_quota(self):
        fake_req = FakeRequest(self.fake_context)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:

            self.controller.index(fake_req, res)
            abs_limits = res.obj['limits']['absolute']
            self.assertNotIn('totalRAMUsed', abs_limits)
            self.assertEqual(1, mock_get_quotas.call_count)
