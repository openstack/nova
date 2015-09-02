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

import six

from nova.api.openstack.compute.legacy_v2.contrib import used_limits \
        as used_limits_v2
from nova.api.openstack.compute import used_limits \
        as used_limits_v21
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.context
from nova import exception
from nova import quota
from nova import test


class FakeRequest(object):
    def __init__(self, context, reserved=False):
        self.environ = {'nova.context': context}
        self.reserved = reserved
        self.GET = {'reserved': 1} if reserved else {}


class UsedLimitsTestCaseV21(test.NoDBTestCase):
    used_limit_extension = "os_compute_api:os-used-limits"
    include_server_group_quotas = True

    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCaseV21, self).setUp()
        self._set_up_controller()
        self.fake_context = nova.context.RequestContext('fake', 'fake')

    def _set_up_controller(self):
        self.ext_mgr = None
        self.controller = used_limits_v21.UsedLimitsController()
        self.mox.StubOutWithMock(used_limits_v21, 'authorize')
        self.authorize = used_limits_v21.authorize

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
        for display_name, q in six.iteritems(quota_map):
            limits[q] = {'limit': len(display_name),
                         'in_use': len(display_name) / 2,
                         'reserved': len(display_name) / 3}
            if (self.include_server_group_quotas or
                display_name != 'totalServerGroupsUsed'):
                expected_abs_limits.append(display_name)

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(False)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
            self.mox.ReplayAll()

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
        fake_req.GET = {'tenant_id': tenant_id}
        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(True)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
        self.authorize(self.fake_context, target=target)
        self.mox.StubOutWithMock(quota.QUOTAS, 'get_project_quotas')
        quota.QUOTAS.get_project_quotas(self.fake_context, '%s' % tenant_id,
                                        usages=True).AndReturn({})
        self.mox.ReplayAll()
        res = wsgi.ResponseObject(obj)
        self.controller.index(fake_req, res)

    def test_admin_can_fetch_used_limits_for_own_project(self):
        project_id = "123456"
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
        fake_req.GET = {}
        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(True)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
        self.mox.StubOutWithMock(extensions, 'extension_authorizer')
        self.mox.StubOutWithMock(quota.QUOTAS, 'get_project_quotas')
        quota.QUOTAS.get_project_quotas(self.fake_context, '%s' % project_id,
                                        usages=True).AndReturn({})
        self.mox.ReplayAll()
        res = wsgi.ResponseObject(obj)
        self.controller.index(fake_req, res)

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
        fake_req.GET = {'tenant_id': tenant_id}
        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(True)
        self.authorize(self.fake_context, target=target). \
            AndRaise(exception.PolicyNotAuthorized(
            action=self.used_limit_extension))
        self.mox.ReplayAll()
        res = wsgi.ResponseObject(obj)
        self.assertRaises(exception.PolicyNotAuthorized, self.controller.index,
                          fake_req, res)

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
        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(False)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
        self.mox.StubOutWithMock(quota.QUOTAS, 'get_project_quotas')
        quota.QUOTAS.get_project_quotas(self.fake_context, project_id,
                                        usages=True).AndReturn({})
        self.mox.ReplayAll()
        res = wsgi.ResponseObject(obj)
        self.controller.index(fake_req, res)

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

        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(False)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertIn('totalRAMUsed', abs_limits)
        self.assertEqual(256, abs_limits['totalRAMUsed'])

    def test_no_ram_quota(self):
        fake_req = FakeRequest(self.fake_context)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)

        def stub_get_project_quotas(context, project_id, usages=True):
            return {}

        if self.ext_mgr is not None:
            self.ext_mgr.is_loaded('os-used-limits-for-admin').AndReturn(False)
            self.ext_mgr.is_loaded('os-server-group-quotas').AndReturn(
                self.include_server_group_quotas)
        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertNotIn('totalRAMUsed', abs_limits)


class UsedLimitsTestCaseV2(UsedLimitsTestCaseV21):
    used_limit_extension = "compute_extension:used_limits_for_admin"

    def _set_up_controller(self):
        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.controller = used_limits_v2.UsedLimitsController(self.ext_mgr)
        self.mox.StubOutWithMock(used_limits_v2, 'authorize_for_admin')
        self.authorize = used_limits_v2.authorize_for_admin


class UsedLimitsTestCaseV2WithoutServerGroupQuotas(UsedLimitsTestCaseV2):
    used_limit_extension = "compute_extension:used_limits_for_admin"
    include_server_group_quotas = False
