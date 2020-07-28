# Copyright 2018 VEXXHOST, Inc.
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

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class DeleteWithReservedVolumes(integrated_helpers._IntegratedTestBase):
    """Test deleting of an instance in error state that has a reserved volume.

    This test boots a server from volume which will fail to be scheduled,
    ending up in ERROR state with no host assigned and then deletes the server.

    Since the server failed to be scheduled, a local delete should run which
    will make sure that reserved volumes at the API layer are properly cleaned
    up.

    The regression is that Nova would not clean up the reserved volumes and
    the volume would be stuck in 'attaching' state.
    """
    api_major_version = 'v2.1'
    microversion = 'latest'

    def _setup_compute_service(self):
        # Override `_setup_compute_service` to make sure that we do not start
        # up the compute service, making sure that the instance will end up
        # failing to find a valid host.
        pass

    def _create_error_server(self, volume_id):
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'bfv-delete-server-in-error-status',
                'networks': 'none',
                'block_device_mapping_v2': [
                    {
                        'boot_index': 0,
                        'uuid': volume_id,
                        'source_type': 'volume',
                        'destination_type': 'volume'
                    },
                ]
            }
        })
        return self._wait_for_state_change(server, 'ERROR')

    def test_delete_with_reserved_volumes_new(self):

        # Create a server which should go to ERROR state because we don't
        # have any active computes.
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server = self._create_error_server(volume_id)
        server_id = server['id']

        # There should now exist an attachment to the volume as it was created
        # by Nova.
        self.assertIn(volume_id,
                      self.cinder.volume_ids_for_instance(server_id))

        # Delete this server, which should delete BDMs and remove the
        # reservation on the instances.
        self.api.delete_server(server['id'])

        # The volume should no longer have any attachments as instance delete
        # should have removed them.
        self.assertNotIn(volume_id,
                         self.cinder.volume_ids_for_instance(server_id))
