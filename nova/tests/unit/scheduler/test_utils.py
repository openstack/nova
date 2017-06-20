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

from nova import objects
from nova.scheduler import utils
from nova import test


class TestUtils(test.NoDBTestCase):

    def _test_resources_from_request_spec(self, flavor, expected):
        fake_spec = objects.RequestSpec(flavor=flavor)
        resources = utils.resources_from_request_spec(fake_spec)
        self.assertEqual(expected, resources)

    def test_resources_from_request_spec(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0)
        expected_resources = {'VCPU': 1,
                              'MEMORY_MB': 1024,
                              'DISK_GB': 15}
        self._test_resources_from_request_spec(flavor, expected_resources)

    def test_resources_from_request_spec_with_no_disk(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=0,
                                ephemeral_gb=0,
                                swap=0)
        expected_resources = {'VCPU': 1,
                              'MEMORY_MB': 1024}
        self._test_resources_from_request_spec(flavor, expected_resources)
