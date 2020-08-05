# Copyright 2017 Huawei Technologies Co.,LTD.
#
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

import nova.conf
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers

CONF = nova.conf.CONF


class RebuildVolumeBackedSameImage(integrated_helpers._IntegratedTestBase):
    """Tests the regression in bug 1732947 where rebuilding a volume-backed
    instance with the original image still results in conductor calling the
    scheduler to validate the image. This is because the instance.image_ref
    is not set for a volume-backed instance, so the conditional check in the
    API to see if the provided image_ref for rebuild is different than the
    original image.
    """
    api_major_version = 'v2.1'
    microversion = 'latest'

    def _setup_scheduler_service(self):
        # Add the IsolatedHostsFilter to the list of enabled filters since it
        # is not enabled by default.
        enabled_filters = CONF.filter_scheduler.enabled_filters
        enabled_filters.append('IsolatedHostsFilter')
        self.flags(enabled_filters=enabled_filters, group='filter_scheduler')
        return self.start_service('scheduler')

    def test_volume_backed_rebuild_same_image(self):
        # First create our server as normal.
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server_req_body = {
            # There is no imageRef because this is boot from volume.
            'server': {
                'flavorRef': '1',   # m1.tiny from DefaultFlavorsFixture,
                'name': 'test_volume_backed_rebuild_same_image',
                # We don't care about networking for this test. This requires
                # microversion >= 2.37.
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid': volume_id,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        server = self.api.post_server(server_req_body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # For a volume-backed server, the image ref will be an empty string
        # in the server response.
        self.assertEqual('', server['image'])

        # Now we mark the host that the instance is running on as isolated
        # but we won't mark the image as isolated, meaning the rebuild
        # will fail for that image on that host.
        self.flags(isolated_hosts=[self.compute.host],
                   group='filter_scheduler')

        # Now rebuild the server with the same image that was used to create
        # our fake volume.
        rebuild_req_body = {
            'rebuild': {
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
            }
        }
        server = self.api.api_post('/servers/%s/action' % server['id'],
                                   rebuild_req_body).body['server']
        # The server image ref should still be blank for a volume-backed server
        # after the rebuild.
        self.assertEqual('', server['image'])
