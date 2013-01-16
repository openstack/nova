# vim: tabstop=5 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from nova.api.openstack.compute.contrib import used_limits
from nova.api.openstack.compute import limits
from nova.api.openstack import wsgi
import nova.context
from nova import quota
from nova import test


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class UsedLimitsTestCase(test.TestCase):

    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCase, self).setUp()
        self.controller = used_limits.UsedLimitsController()

        self.fake_context = nova.context.RequestContext('fake', 'fake')
        self.fake_req = FakeRequest(self.fake_context)

    def test_used_limits(self):
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
            'totalVolumesUsed': 'volumes',
            'totalVolumeGigabytesUsed': 'gigabytes',
            'totalFloatingIpsUsed': 'floating_ips',
            'totalSecurityGroupsUsed': 'security_groups',
        }
        limits = {}
        for display_name, q in quota_map.iteritems():
            limits[q] = {'limit': 10, 'in_use': 2}

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits
        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)

        self.controller.index(self.fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        for used_limit, value in abs_limits.iteritems():
            self.assertEqual(value, limits[quota_map[used_limit]]['in_use'])

    def test_used_ram_added(self):
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
        self.controller.index(self.fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertTrue('totalRAMUsed' in abs_limits)
        self.assertEqual(abs_limits['totalRAMUsed'], 256)

    def test_no_ram_quota(self):
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
        self.controller.index(self.fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertFalse('totalRAMUsed' in abs_limits)

    def test_used_limits_xmlns(self):
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
        self.controller.index(self.fake_req, res)
        response = res.serialize(None, 'xml')
        self.assertTrue(used_limits.XMLNS in response.body)
