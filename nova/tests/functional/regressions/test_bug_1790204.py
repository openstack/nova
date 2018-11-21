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

from oslo_utils.fixture import uuidsentinel as uuids
import six

from nova.tests.functional.api import client as api_client
from nova.tests.functional import integrated_helpers


class ResizeSameHostDoubledAllocations(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Regression test for bug 1790204 introduced in Pike.

    Since Pike, the FilterScheduler uses Placement to "claim" resources
    via allocations during scheduling. During a move operation, the
    scheduler will claim resources on the selected destination resource
    provider (compute node). For a same-host resize, this means claiming
    resources from the *new_flavor* on the destination while holding
    allocations for the *old_flavor* on the source, which is the same
    provider. This can lead to NoValidHost failures during scheduling a
    resize to the same host since the allocations are "doubled up" on the
    same provider even though the *new_flavor* allocations could fit.

    This test reproduces the regression.
    """

    # Use the SmallFakeDriver which has little inventory:
    # vcpus = 2, memory_mb = 8192, local_gb = 1028
    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(ResizeSameHostDoubledAllocations, self).setUp()
        self._start_compute(uuids.host)

    def test_resize_same_host_full_allocations(self):
        self.flags(allow_resize_to_same_host=True)
        # Create two flavors so we can control what the test uses.
        flavor = {
            'flavor': {
                'name': 'v1r2d1', 'ram': 2048, 'vcpus': 1, 'disk': 1028,
            }
        }
        flavor1 = self.admin_api.post_flavor(flavor)
        # Tweak the flavor to increase the number of VCPUs.
        flavor['flavor'].update({'name': 'v2r2d1', 'vcpus': 2})
        flavor2 = self.admin_api.post_flavor(flavor)

        # Create a server from flavor1.
        server = self._boot_and_check_allocations(flavor1, uuids.host)

        # Now try to resize to flavor2.
        resize_req = {
            'resize': {
                'flavorRef': flavor2['id'],
            }
        }
        # FIXME(mriedem): This is bug 1790204 where scheduling fails with
        # NoValidHost because the scheduler fails to claim "doubled up"
        # allocations on the same compute node resource provider. Scheduling
        # fails because DISK_GB inventory allocation ratio is 1.0 and when
        # resizing to the same host we'll be trying to claim 2048 but the
        # provider only has a total of 1024.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], resize_req)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('No valid host was found', six.text_type(ex))
