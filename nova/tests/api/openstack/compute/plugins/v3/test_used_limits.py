# vim: tabstop=5 shiftwidth=4 softtabstop=4

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

from nova.api.openstack.compute import limits
from nova.api.openstack.compute.plugins.v3 import used_limits
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


class UsedLimitsTestCase(test.NoDBTestCase):
    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCase, self).setUp()
        self.controller = used_limits.UsedLimitsController()

        self.fake_context = nova.context.RequestContext('fake', 'fake')
        self.mox.StubOutWithMock(used_limits, 'authorize')
        self.authorize = used_limits.authorize

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
        }
        limits = {}
        for display_name, q in quota_map.iteritems():
            limits[q] = {'limit': len(display_name),
                         'in_use': len(display_name) / 2,
                         'reserved': len(display_name) / 3}

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.authorize(self.fake_context)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        for used_limit, value in abs_limits.iteritems():
            r = limits[quota_map[used_limit]]['reserved'] if reserved else 0
            self.assertEqual(value,
                             limits[quota_map[used_limit]]['in_use'] + r)

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
        self.authorize(self.fake_context)
        self.authorize(self.fake_context, target=target, action='tenant')
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
        self.mox.StubOutWithMock(extensions, 'extension_authorizer')
        self.mox.StubOutWithMock(quota.QUOTAS, 'get_project_quotas')
        self.authorize(self.fake_context)
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
        self.authorize(self.fake_context)
        self.authorize(self.fake_context, target=target, action='tenant'). \
            AndRaise(exception.PolicyNotAuthorized(
            action="compute_extension:used_limits_for_admin"))
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
        self.mox.StubOutWithMock(quota.QUOTAS, 'get_project_quotas')
        self.authorize(self.fake_context)
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

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.authorize(self.fake_context)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertTrue('totalRAMUsed' in abs_limits)
        self.assertEqual(abs_limits['totalRAMUsed'], 256)

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

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.authorize(self.fake_context)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertFalse('totalRAMUsed' in abs_limits)

    def test_used_limits_xmlns(self):
        fake_req = FakeRequest(self.fake_context)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj, xml=limits.LimitsTemplate)
        res.preserialize('xml')

        def stub_get_project_quotas(context, project_id, usages=True):
            return {}

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)
        self.authorize(self.fake_context)
        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        response = res.serialize(None, 'xml')
        self.assertTrue(used_limits.XMLNS in response.body)
