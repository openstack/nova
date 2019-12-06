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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image


class VolumeBackedResizeDiskDown(test.TestCase,
                                 integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1825020 introduced in Stein.

    This tests a resize scenario where a volume-backed server is resized
    to a flavor with a smaller disk than the flavor used to create the
    server. Since the server is volume-backed, the disk in the new flavor
    should not matter since it won't be used for the guest.
    """

    def setUp(self):
        super(VolumeBackedResizeDiskDown, self).setUp()
        self.flags(allow_resize_to_same_host=True)

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api

        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.CinderFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')

    def test_volume_backed_resize_disk_down(self):
        # First determine the flavors we're going to use by picking two flavors
        # with different size disks and create a volume-backed server using the
        # flavor with the bigger disk size.
        flavors = self.api.get_flavors()
        flavor1 = flavors[0]
        flavor2 = flavors[1]
        self.assertGreater(flavor2['disk'], flavor1['disk'])

        vol_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server = {
            'name': 'test_volume_backed_resize_disk_down',
            'imageRef': '',
            'flavorRef': flavor2['id'],
            'block_device_mapping_v2': [{
                'source_type': 'volume',
                'destination_type': 'volume',
                'boot_index': 0,
                'uuid': vol_id
            }]
        }
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(server, 'ACTIVE')

        # Now try to resize the server with the flavor that has smaller disk.
        # This should be allowed since the server is volume-backed and the
        # disk size in the flavor shouldn't matter.
        data = {'resize': {'flavorRef': flavor1['id']}}
        self.api.post_server_action(server['id'], data)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        # Now confirm the resize just to complete the operation.
        self.api.post_server_action(server['id'], {'confirmResize': None})
        self._wait_for_state_change(server, 'ACTIVE')
