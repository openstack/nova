# Copyright 2011 OpenStack Foundation
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

"""
Tests dealing with HTTP rate-limiting.
"""

import mock
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from six.moves import http_client as httplib
from six.moves import StringIO

from nova.api.openstack.compute import limits as limits_v21
from nova.api.openstack.compute import views
from nova.api.openstack import wsgi
import nova.context
from nova import exception
from nova.policies import used_limits as ul_policies
from nova import quota
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers


class BaseLimitTestSuite(test.NoDBTestCase):
    """Base test suite which provides relevant stubs and time abstraction."""

    def setUp(self):
        super(BaseLimitTestSuite, self).setUp()
        self.time = 0.0
        self.absolute_limits = {}

        def stub_get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in self.absolute_limits.items()}

        mock_get_project_quotas = mock.patch.object(
            nova.quota.QUOTAS,
            "get_project_quotas",
            side_effect = stub_get_project_quotas)
        mock_get_project_quotas.start()
        self.addCleanup(mock_get_project_quotas.stop)
        patcher = self.mock_can = mock.patch('nova.context.RequestContext.can')
        self.mock_can = patcher.start()
        self.addCleanup(patcher.stop)

    def _get_time(self):
        """Return the "time" according to this test suite."""
        return self.time


class LimitsControllerTestV21(BaseLimitTestSuite):
    """Tests for `limits.LimitsController` class."""
    limits_controller = limits_v21.LimitsController

    def setUp(self):
        """Run before each test."""
        super(LimitsControllerTestV21, self).setUp()
        self.controller = wsgi.Resource(self.limits_controller())
        self.ctrler = self.limits_controller()

    def _get_index_request(self, accept_header="application/json",
                           tenant_id=None, user_id='testuser',
                           project_id='testproject'):
        """Helper to set routing arguments."""
        request = fakes.HTTPRequest.blank('', version='2.1')
        if tenant_id:
            request = fakes.HTTPRequest.blank('/?tenant_id=%s' % tenant_id,
                                              version='2.1')

        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        context = nova.context.RequestContext(user_id, project_id)
        request.environ["nova.context"] = context
        return request

    def test_empty_index_json(self):
        # Test getting empty limit details in JSON.
        request = self._get_index_request()
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        body = jsonutils.loads(response.body)
        self.assertEqual(expected, body)

    def test_index_json(self):
        self._test_index_json()

    def test_index_json_by_tenant(self):
        self._test_index_json('faketenant')

    def _test_index_json(self, tenant_id=None):
        # Test getting limit details in JSON.
        request = self._get_index_request(tenant_id=tenant_id)
        context = request.environ["nova.context"]
        if tenant_id is None:
            tenant_id = context.project_id

        self.absolute_limits = {
            'ram': 512,
            'instances': 5,
            'cores': 21,
            'key_pairs': 10,
            'floating_ips': 10,
            'security_groups': 10,
            'security_group_rules': 20,
        }
        expected = {
            "limits": {
                "rate": [],
                "absolute": {
                    "maxTotalRAMSize": 512,
                    "maxTotalInstances": 5,
                    "maxTotalCores": 21,
                    "maxTotalKeypairs": 10,
                    "maxTotalFloatingIps": 10,
                    "maxSecurityGroups": 10,
                    "maxSecurityGroupRules": 20,
                    "totalRAMUsed": 256,
                    "totalCoresUsed": 10,
                    "totalInstancesUsed": 2,
                    "totalFloatingIpsUsed": 5,
                    "totalSecurityGroupsUsed": 5,
                    },
            },
        }

        def _get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in self.absolute_limits.items()}

        with mock.patch('nova.quota.QUOTAS.get_project_quotas') as \
                get_project_quotas:
            get_project_quotas.side_effect = _get_project_quotas

            response = request.get_response(self.controller)

            body = jsonutils.loads(response.body)
            self.assertEqual(expected, body)
            get_project_quotas.assert_called_once_with(context, tenant_id,
                                                       usages=True)

    def _do_test_used_limits(self, reserved):
        request = self._get_index_request(tenant_id=None)
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
                         'in_use': len(display_name) // 2,
                         'reserved': 0}
            expected_abs_limits.append(display_name)

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits

        self.stub_out('nova.quota.QUOTAS.get_project_quotas',
                      stub_get_project_quotas)

        res = request.get_response(self.controller)
        body = jsonutils.loads(res.body)
        abs_limits = body['limits']['absolute']
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
        target = {
            "project_id": tenant_id,
            "user_id": user_id
        }
        fake_req = self._get_index_request(tenant_id=tenant_id,
                                           user_id=user_id,
                                           project_id=project_id)
        context = fake_req.environ["nova.context"]
        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                              return_value={}) as mock_get_quotas:
            fake_req.get_response(self.controller)
            self.assertEqual(2, self.mock_can.call_count)
            self.mock_can.assert_called_with(ul_policies.BASE_POLICY_NAME,
                                             target)
            mock_get_quotas.assert_called_once_with(context,
                tenant_id, usages=True)

    def _test_admin_can_fetch_used_limits_for_own_project(self, req_get):
        project_id = "123456"
        if 'tenant_id' in req_get:
            project_id = req_get['tenant_id']

        user_id = "A1234"
        fake_req = self._get_index_request(user_id=user_id,
                                           project_id=project_id)
        context = fake_req.environ["nova.context"]

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:
            fake_req.get_response(self.controller)
            mock_get_quotas.assert_called_once_with(context,
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

    def test_used_limits_fetched_for_context_project_id(self):
        project_id = "123456"
        fake_req = self._get_index_request(project_id=project_id)
        context = fake_req.environ["nova.context"]
        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:
            fake_req.get_response(self.controller)

            mock_get_quotas.assert_called_once_with(context,
                project_id, usages=True)

    def test_used_ram_added(self):
        fake_req = self._get_index_request()

        def stub_get_project_quotas(context, project_id, usages=True):
            return {'ram': {'limit': 512, 'in_use': 256}}

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               side_effect=stub_get_project_quotas
                               ) as mock_get_quotas:

            res = fake_req.get_response(self.controller)
            body = jsonutils.loads(res.body)
            abs_limits = body['limits']['absolute']
            self.assertIn('totalRAMUsed', abs_limits)
            self.assertEqual(256, abs_limits['totalRAMUsed'])
            self.assertEqual(1, mock_get_quotas.call_count)

    def test_no_ram_quota(self):
        fake_req = self._get_index_request()

        with mock.patch.object(quota.QUOTAS, 'get_project_quotas',
                               return_value={}) as mock_get_quotas:

            res = fake_req.get_response(self.controller)
            body = jsonutils.loads(res.body)
            abs_limits = body['limits']['absolute']
            self.assertNotIn('totalRAMUsed', abs_limits)
            self.assertEqual(1, mock_get_quotas.call_count)


class FakeHttplibSocket(object):
    """Fake `httplib.HTTPResponse` replacement."""

    def __init__(self, response_string):
        """Initialize new `FakeHttplibSocket`."""
        self._buffer = StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer."""
        return self._buffer


class FakeHttplibConnection(object):
    """Fake `httplib.HTTPConnection`."""

    def __init__(self, app, host):
        """Initialize `FakeHttplibConnection`."""
        self.app = app
        self.host = host

    def request(self, method, path, body="", headers=None):
        """Requests made via this connection actually get translated and routed
        into our WSGI app, we then wait for the response and turn it back into
        an `httplib.HTTPResponse`.
        """
        if not headers:
            headers = {}

        req = fakes.HTTPRequest.blank(path)
        req.method = method
        req.headers = headers
        req.host = self.host
        req.body = encodeutils.safe_encode(body)

        resp = str(req.get_response(self.app))
        resp = "HTTP/1.0 %s" % resp
        sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(sock)
        self.http_response.begin()

    def getresponse(self):
        """Return our generated response from the request."""
        return self.http_response


class LimitsViewBuilderTest(test.NoDBTestCase):
    def setUp(self):
        super(LimitsViewBuilderTest, self).setUp()
        self.view_builder = views.limits.ViewBuilder()
        self.req = fakes.HTTPRequest.blank('/?tenant_id=None')
        self.rate_limits = []
        patcher = self.mock_can = mock.patch('nova.context.RequestContext.can')
        self.mock_can = patcher.start()
        self.addCleanup(patcher.stop)
        self.absolute_limits = {"metadata_items": {'limit': 1, 'in_use': 1},
                                "injected_files": {'limit': 5, 'in_use': 1},
                                "injected_file_content_bytes":
                                    {'limit': 5, 'in_use': 1}}

    def test_build_limits(self):
        expected_limits = {"limits": {
                "rate": [],
                "absolute": {"maxServerMeta": 1,
                             "maxImageMeta": 1,
                             "maxPersonality": 5,
                             "maxPersonalitySize": 5}}}

        output = self.view_builder.build(self.req, self.absolute_limits)
        self.assertThat(output, matchers.DictMatches(expected_limits))

    def test_build_limits_empty_limits(self):
        expected_limits = {"limits": {"rate": [],
                           "absolute": {}}}

        quotas = {}
        output = self.view_builder.build(self.req, quotas)
        self.assertThat(output, matchers.DictMatches(expected_limits))

    def test_non_admin_cannot_fetch_used_limits_for_any_other_project(self):
        project_id = "123456"
        user_id = "A1234"
        tenant_id = "abcd"
        target = {
            "project_id": tenant_id,
            "user_id": user_id
        }
        req = fakes.HTTPRequest.blank('/?tenant_id=%s' % tenant_id)
        context = nova.context.RequestContext(user_id, project_id)
        req.environ["nova.context"] = context

        self.mock_can.side_effect = exception.PolicyNotAuthorized(
            action="os_compute_api:os-used-limits")
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.view_builder.build,
                          req, self.absolute_limits)

        self.mock_can.assert_called_with(ul_policies.BASE_POLICY_NAME,
                                         target)


class LimitsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(LimitsPolicyEnforcementV21, self).setUp()
        self.controller = limits_v21.LimitsController()

    def test_limits_index_policy_failed(self):
        rule_name = "os_compute_api:limits"
        self.policy.set_rules({rule_name: "project:non_fake"})
        req = fakes.HTTPRequest.blank('')
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, req=req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class LimitsControllerTestV236(BaseLimitTestSuite):

    def setUp(self):
        super(LimitsControllerTestV236, self).setUp()
        self.controller = limits_v21.LimitsController()
        self.req = fakes.HTTPRequest.blank("/?tenant_id=faketenant",
                                           version='2.36')

    def test_index_filtered(self):
        absolute_limits = {
            'ram': 512,
            'instances': 5,
            'cores': 21,
            'key_pairs': 10,
            'floating_ips': 10,
            'security_groups': 10,
            'security_group_rules': 20,
        }

        def _get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in absolute_limits.items()}

        with mock.patch('nova.quota.QUOTAS.get_project_quotas') as \
                get_project_quotas:
            get_project_quotas.side_effect = _get_project_quotas
            response = self.controller.index(self.req)
            expected_response = {
                "limits": {
                    "rate": [],
                    "absolute": {
                        "maxTotalRAMSize": 512,
                        "maxTotalInstances": 5,
                        "maxTotalCores": 21,
                        "maxTotalKeypairs": 10,
                        "totalRAMUsed": 256,
                        "totalCoresUsed": 10,
                        "totalInstancesUsed": 2,
                    },
                },
            }
            self.assertEqual(expected_response, response)


class LimitsControllerTestV239(BaseLimitTestSuite):

    def setUp(self):
        super(LimitsControllerTestV239, self).setUp()
        self.controller = limits_v21.LimitsController()
        self.req = fakes.HTTPRequest.blank("/?tenant_id=faketenant",
                                           version='2.39')

    def test_index_filtered_no_max_image_meta(self):
        absolute_limits = {
            "metadata_items": 1,
        }

        def _get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in absolute_limits.items()}

        with mock.patch('nova.quota.QUOTAS.get_project_quotas') as \
                get_project_quotas:
            get_project_quotas.side_effect = _get_project_quotas
            response = self.controller.index(self.req)
            # staring from version 2.39 there is no 'maxImageMeta' field
            # in response after removing 'image-metadata' proxy API
            expected_response = {
                "limits": {
                    "rate": [],
                    "absolute": {
                        "maxServerMeta": 1,
                    },
                },
            }
            self.assertEqual(expected_response, response)


class LimitsControllerTestV275(BaseLimitTestSuite):
    def setUp(self):
        super(LimitsControllerTestV275, self).setUp()
        self.controller = limits_v21.LimitsController()

    def test_index_additional_query_param_old_version(self):
        absolute_limits = {
            "metadata_items": 1,
        }
        req = fakes.HTTPRequest.blank("/?unkown=fake",
                                       version='2.74')

        def _get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in absolute_limits.items()}

        with mock.patch('nova.quota.QUOTAS.get_project_quotas') as \
                get_project_quotas:
            get_project_quotas.side_effect = _get_project_quotas
            self.controller.index(req)

    def test_index_additional_query_param(self):
        req = fakes.HTTPRequest.blank("/?unkown=fake",
                                      version='2.75')
        self.assertRaises(
            exception.ValidationError,
            self.controller.index, req=req)
