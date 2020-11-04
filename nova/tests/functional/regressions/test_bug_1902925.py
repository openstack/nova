# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
from nova.tests.functional import integrated_helpers
from nova.tests.unit import cast_as_call


class ComputeVersion5xPinnedRpcTests(integrated_helpers._IntegratedTestBase):

    compute_driver = 'fake.MediumFakeDriver'
    ADMIN_API = True
    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super(ComputeVersion5xPinnedRpcTests, self).setUp()
        self.useFixture(cast_as_call.CastAsCall(self))

        self.compute1 = self._start_compute(host='host1')

    def _test_rebuild_instance_with_compute_rpc_pin(self, version_cap):
        self.flags(compute=version_cap, group='upgrade_levels')

        server_req = self._build_server(networks='none')
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(server, 'ACTIVE')

        self.api.post_server_action(server['id'], {'rebuild': {
            'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        }})

    def test_rebuild_instance_5_0(self):
        self._test_rebuild_instance_with_compute_rpc_pin('5.0')

    def test_rebuild_instance_5_12(self):
        self._test_rebuild_instance_with_compute_rpc_pin('5.12')
