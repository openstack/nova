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

from nova.api.openstack.compute.contrib import fping
from nova.api.openstack import extensions
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
import nova.utils


FAKE_UUID = fakes.FAKE_UUID


def execute(*cmd, **args):
    return "".join(["%s is alive" % ip for ip in cmd[1:]])


class FpingTest(test.TestCase):

    def setUp(self):
        super(FpingTest, self).setUp()
        self.flags(verbose=True, use_ipv6=False)
        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(nova.db, "instance_get_all_by_filters",
                       return_servers)
        self.stubs.Set(nova.db, "instance_get_by_uuid",
                       return_server)
        self.stubs.Set(nova.utils, "execute",
                       execute)
        self.stubs.Set(fping.FpingController, "check_fping",
                       lambda self: None)
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = fping.FpingController(self.ext_mgr)

    def test_fping_index(self):
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping")
        res_dict = self.controller.index(req)
        self.assertIn("servers", res_dict)
        for srv in res_dict["servers"]:
            for key in "project_id", "id", "alive":
                self.assertIn(key, srv)

    def test_fping_index_policy(self):
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping?all_tenants=1")
        self.assertRaises(exception.NotAuthorized, self.controller.index, req)
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping?all_tenants=1")
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.index(req)
        self.assertIn("servers", res_dict)

    def test_fping_index_include(self):
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping")
        res_dict = self.controller.index(req)
        ids = [srv["id"] for srv in res_dict["servers"]]
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping?include=%s" % ids[0])
        res_dict = self.controller.index(req)
        self.assertEqual(len(res_dict["servers"]), 1)
        self.assertEqual(res_dict["servers"][0]["id"], ids[0])

    def test_fping_index_exclude(self):
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping")
        res_dict = self.controller.index(req)
        ids = [srv["id"] for srv in res_dict["servers"]]
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping?exclude=%s" %
                                      ",".join(ids[1:]))
        res_dict = self.controller.index(req)
        self.assertEqual(len(res_dict["servers"]), 1)
        self.assertEqual(res_dict["servers"][0]["id"], ids[0])

    def test_fping_show(self):
        req = fakes.HTTPRequest.blank("/v2/1234/os-fping/%s" % FAKE_UUID)
        res_dict = self.controller.show(req, FAKE_UUID)
        self.assertIn("server", res_dict)
        srv = res_dict["server"]
        for key in "project_id", "id", "alive":
            self.assertIn(key, srv)
