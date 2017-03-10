# Copyright 2011 Grid Dynamics
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

import mock
import webob

from nova.api.openstack.compute import fping as fping_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


FAKE_UUID = fakes.FAKE_UUID


def execute(*cmd, **args):
    return "".join(["%s is alive" % ip for ip in cmd[1:]])


class FpingTestV21(test.TestCase):
    controller_cls = fping_v21.FpingController

    def setUp(self):
        super(FpingTestV21, self).setUp()
        self.flags(use_ipv6=False)
        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stub_out("nova.db.instance_get_all_by_filters",
                      return_servers)
        self.stub_out("nova.db.instance_get_by_uuid",
                      return_server)
        self.stub_out('nova.utils.execute',
                      execute)
        self.stub_out("nova.api.openstack.compute.fping.FpingController."
                      "check_fping",
                      lambda self: None)
        self.controller = self.controller_cls()

    def _get_url(self):
        return "/v2/1234"

    def test_fping_index(self):
        req = fakes.HTTPRequest.blank(self._get_url() + "/os-fping")
        res_dict = self.controller.index(req)
        self.assertIn("servers", res_dict)
        for srv in res_dict["servers"]:
            for key in "project_id", "id", "alive":
                self.assertIn(key, srv)

    def test_fping_index_policy(self):
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "os-fping?all_tenants=1")
        self.assertRaises(exception.Forbidden, self.controller.index, req)
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "/os-fping?all_tenants=1")
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.index(req)
        self.assertIn("servers", res_dict)

    def test_fping_index_include(self):
        req = fakes.HTTPRequest.blank(self._get_url() + "/os-fping")
        res_dict = self.controller.index(req)
        ids = [srv["id"] for srv in res_dict["servers"]]
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "/os-fping?include=%s" % ids[0])
        res_dict = self.controller.index(req)
        self.assertEqual(len(res_dict["servers"]), 1)
        self.assertEqual(res_dict["servers"][0]["id"], ids[0])

    def test_fping_index_exclude(self):
        req = fakes.HTTPRequest.blank(self._get_url() + "/os-fping")
        res_dict = self.controller.index(req)
        ids = [srv["id"] for srv in res_dict["servers"]]
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "/os-fping?exclude=%s" %
                                      ",".join(ids[1:]))
        res_dict = self.controller.index(req)
        self.assertEqual(len(res_dict["servers"]), 1)
        self.assertEqual(res_dict["servers"][0]["id"], ids[0])

    def test_fping_show(self):
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "os-fping/%s" % FAKE_UUID)
        res_dict = self.controller.show(req, FAKE_UUID)
        self.assertIn("server", res_dict)
        srv = res_dict["server"]
        for key in "project_id", "id", "alive":
            self.assertIn(key, srv)

    @mock.patch('nova.db.instance_get_by_uuid')
    def test_fping_show_with_not_found(self, mock_get_instance):
        mock_get_instance.side_effect = exception.InstanceNotFound(
            instance_id='')
        req = fakes.HTTPRequest.blank(self._get_url() +
                                      "os-fping/%s" % FAKE_UUID)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, FAKE_UUID)


class FpingPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FpingPolicyEnforcementV21, self).setUp()
        self.controller = fping_v21.FpingController()
        self.req = fakes.HTTPRequest.blank('')

    def common_policy_check(self, rule, func, *arg, **kwarg):
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." %
            rule.popitem()[0], exc.format_message())

    def test_list_policy_failed(self):
        rule = {"os_compute_api:os-fping": "project:non_fake"}
        self.common_policy_check(rule, self.controller.index, self.req)

        self.req.GET.update({"all_tenants": "True"})
        rule = {"os_compute_api:os-fping:all_tenants":
                "project:non_fake"}
        self.common_policy_check(rule, self.controller.index, self.req)

    def test_show_policy_failed(self):
        rule = {"os_compute_api:os-fping": "project:non_fake"}
        self.common_policy_check(
            rule, self.controller.show, self.req, FAKE_UUID)


class FpingTestDeprecation(test.NoDBTestCase):

    def setUp(self):
        super(FpingTestDeprecation, self).setUp()
        self.controller = fping_v21.FpingController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
