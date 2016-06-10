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


class VirtualInterfacesJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-virtual-interfaces"

    def setUp(self):
        super(VirtualInterfacesJsonTest, self).setUp()
        self.template = 'vifs-list-resp'
        if self.api_major_version == 'v2':
            self.template = 'vifs-list-resp-v2'

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)

        subs = {'mac_addr': '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'}
        self._verify_response(self.template, subs, response, 200)


class VirtualInterfacesJsonV212Test(VirtualInterfacesJsonTest):
    microversion = '2.12'
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.12 which will run the original tests
    # by appending '(v2_12)' in test_id.
    scenarios = [('v2_12', {'api_major_version': 'v2.1'})]
