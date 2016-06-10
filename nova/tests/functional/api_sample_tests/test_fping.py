# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack.compute import test_fping


class FpingSampleJsonTests(test_servers.ServersSampleBase):
    sample_dir = "os-fping"

    def setUp(self):
        super(FpingSampleJsonTests, self).setUp()

        def fake_check_fping(self):
            pass
        self.stub_out("nova.utils.execute", test_fping.execute)
        self.stub_out("nova.api.openstack.compute.fping."
                      "FpingController.check_fping",
                      fake_check_fping)

    def test_get_fping(self):
        self._post_server()
        response = self._do_get('os-fping')
        self._verify_response('fping-get-resp', {}, response, 200)

    def test_get_fping_details(self):
        uuid = self._post_server()
        response = self._do_get('os-fping/%s' % (uuid))
        self._verify_response('fping-get-details-resp', {}, response, 200)
