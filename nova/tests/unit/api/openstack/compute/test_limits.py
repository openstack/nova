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
            return {k: dict(limit=v)
                    for k, v in self.absolute_limits.items()}

        mock_get_project_quotas = mock.patch.object(
            nova.quota.QUOTAS,
            "get_project_quotas",
            side_effect = stub_get_project_quotas)
        mock_get_project_quotas.start()
        self.addCleanup(mock_get_project_quotas.stop)

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
                           tenant_id=None):
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
        context = nova.context.RequestContext('testuser', 'testproject')
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
                    },
            },
        }

        def _get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v) for k, v in self.absolute_limits.items()}

        with mock.patch('nova.quota.QUOTAS.get_project_quotas') as \
                get_project_quotas:
            get_project_quotas.side_effect = _get_project_quotas

            response = request.get_response(self.controller)

            body = jsonutils.loads(response.body)
            self.assertEqual(expected, body)
            get_project_quotas.assert_called_once_with(context, tenant_id,
                                                       usages=False)


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
        self.rate_limits = []
        self.absolute_limits = {"metadata_items": 1,
                                "injected_files": 5,
                                "injected_file_content_bytes": 5}

    def test_build_limits(self):
        expected_limits = {"limits": {
                "rate": [],
                "absolute": {"maxServerMeta": 1,
                             "maxImageMeta": 1,
                             "maxPersonality": 5,
                             "maxPersonalitySize": 5}}}

        output = self.view_builder.build(self.absolute_limits)
        self.assertThat(output, matchers.DictMatches(expected_limits))

    def test_build_limits_empty_limits(self):
        expected_limits = {"limits": {"rate": [],
                           "absolute": {}}}

        abs_limits = {}
        output = self.view_builder.build(abs_limits)
        self.assertThat(output, matchers.DictMatches(expected_limits))


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
            return {k: dict(limit=v) for k, v in absolute_limits.items()}

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
            return {k: dict(limit=v) for k, v in absolute_limits.items()}

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
