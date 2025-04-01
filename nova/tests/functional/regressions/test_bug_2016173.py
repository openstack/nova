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

from cinderclient import exceptions as cinder_exception

from nova import context as nova_context
from nova.tests.functional import integrated_helpers
from nova.volume import cinder


class TestVolumeDetachRollback(integrated_helpers._IntegratedTestBase):
    """Regression test for bug #880399

    This tests that the volume status is rolled back to "in-use" if the volume
    detach fails at the Cinder level.
    """
    # Detach volume is a cast and should not fail at the API.
    CAST_AS_CALL = False

    def setUp(self):
        super().setUp()

        def fail_detach(*args, **kwargs):
            raise cinder_exception.ClientException(500)

        # Fake a volume detach failure from Cinder API.
        self.stub_out('nova.volume.cinder.API.attachment_delete', fail_detach)
        self.ctxt = nova_context.get_admin_context()
        self.volume_api = cinder.API()

    def test_server_create_volume_detach_fails(self):
        # Create a server.
        server = self._create_server(networks=[])
        # Create a volume.
        volume_id = self.volume_api.create(self.ctxt, 1, None, None)['id']
        # Attach the volume to the server.
        self._attach_volume(server, volume_id)

        # Detach the volume (which will fail internally for this test).
        self.api.delete_server_volume(server['id'], volume_id)

        # Wait for the detach to fail.
        self._wait_for_action_fail_completion(
            server, 'detach_volume', 'compute_detach_volume')

        # FIXME(melwitt): This is the bug, the volume does not go back to
        # "in-use" after the detach fails.
        volume = self.volume_api.get(self.ctxt, volume_id)
        self.assertNotEqual('in-use', volume['status'])
