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

from oslo_log import log as logging

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers

LOG = logging.getLogger(__name__)


class TestLocalDeleteAttachedVolumes(integrated_helpers._IntegratedTestBase):
    """Test local delete in the API of a server with a volume attached.

    This test creates a server, then shelve-offloads it, attaches a
    volume, and then deletes the server.

    Since the server is shelved-offloaded it does not have instance.host
    set which should trigger a local delete flow in the API. During local
    delete we should try to cleanup any attached volumes.

    This test asserts that on a local delete we also detach any volumes
    and destroy the related BlockDeviceMappings.
    """

    microversion = 'latest'

    def setUp(self):
        super().setUp()
        self.flavor_id = self.api.get_flavors()[0]['id']

    def _delete_server(self, server):
        try:
            self.api.delete_server(server['id'])
        except client.OpenStackApiNotFoundException:
            pass

    def test_local_delete_with_volume_attached(self, mock_version_get=None):
        LOG.info('Creating server and waiting for it to be ACTIVE.')
        server = dict(
            name='local-delete-volume-attach-test',
            # The image ID comes from GlanceFixture
            imageRef='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            flavorRef=self.flavor_id,
            # Bypass network setup on the compute.
            networks='none')
        server = self.api.post_server({'server': server})
        server_id = server['id']
        self.addCleanup(self._delete_server, server)
        self._wait_for_state_change(server, 'ACTIVE')

        LOG.info('Shelve-offloading server %s', server_id)
        self.api.post_server_action(server_id, {'shelve': None})
        # Wait for the server to be offloaded.
        self._wait_for_state_change(server, 'SHELVED_OFFLOADED')

        volume_id = '9a695496-44aa-4404-b2cc-ccab2501f87e'
        LOG.info('Attaching volume %s to server %s', volume_id, server_id)
        self.api.post_server_volume(
            server_id, dict(volumeAttachment=dict(volumeId=volume_id)))
        # Wait for the volume to show up in the server's list of attached
        # volumes.
        LOG.info('Validating that volume %s is attached to server %s.',
                 volume_id, server_id)
        self._wait_for_volume_attach(server_id, volume_id)
        # Check to see that the fixture is tracking the server and volume
        # attachment.
        self.assertIn(volume_id,
                      self.cinder.volume_ids_for_instance(server_id))

        # At this point the instance.host is no longer set, so deleting
        # the server will take the local delete path in the API.
        LOG.info('Deleting shelved-offloaded server %s.', server_id)
        self._delete_server(server)
        # Now wait for the server to be gone.
        self._wait_until_deleted(server)

        LOG.info('Validating that volume %s was detached from server %s.',
                 volume_id, server_id)
        # Now that the bug is fixed, assert the volume was detached.
        self.assertNotIn(volume_id,
                         self.cinder.volume_ids_for_instance(server_id))
