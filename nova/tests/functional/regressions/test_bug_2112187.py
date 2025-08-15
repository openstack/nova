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

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestDirectSwapVolume(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 2112187

    During a Cinder orchestrated volume migration nova leaves the
    stashed connection_info of the attachment pointing at the original
    volume UUID used during the migration because cinder will atomically
    revert the UUID of the volume back to the original value.

    When swap volume is used directly the uuid should be updated
    in the libvirt xml but nova does not support that today.
    That results in the uuid in the xml and the uuid in the BDMs
    being out of sync.

    As a result it is unsafe to allow direct swap volume.
    """

    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()
        self.start_compute()

    def test_direct_swap_volume(self):
        # NOTE(sean-k-mooney): This test is emulating calling swap volume
        # directly instead of using cinder volume migrate or retype.
        server_id = self._create_server(networks='none')['id']
        # We do not need to use a multiattach volume but any volume
        # that does not have a migration state set will work.
        self.api.post_server_volume(
            server_id,
            {
                'volumeAttachment': {
                    'volumeId': self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL
                }
            }
        )
        self._wait_for_volume_attach(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL)

        # NOTE(sean-k-mooney): because of bug 212187 directly using
        # swap volume is not supported and should fail.
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.put_server_volume,
            server_id, self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL,
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL)
        self.assertIn("this api should only be called by Cinder", str(ex))
