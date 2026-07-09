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
import fixtures
import threading
import time

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.libvirt import base


class TestAttachVolumeListAttachmentRace(base.ServersTestBase):
    """Regression test for bug 2160224.

    see https://bugs.launchpad.net/nova/+bug/2160224 for details
    """

    microversion = 'latest'
    CAST_AS_CALL = False

    def setUp(self):
        super().setUp()
        self.start_compute()

        # Simulate that cinder slow creating the volume attachment so that
        # we can trigger a race
        event = threading.Event()
        self.addCleanup(event.set)

        def fake_attachment_create(*args, **kwargs):
            event.wait(2)
            return nova_fixtures.CinderFixture.fake_attachment_create(
                self.cinder, *args, **kwargs)

        self.useFixture(fixtures.MockPatch(
            'nova.volume.cinder.API.attachment_create',
            side_effect=fake_attachment_create, autospec=False))

    def test_attach_and_show_race(self):
        volume_id = self.cinder.IMAGE_BACKED_VOL
        server = self._create_server(networks='none')
        self.notifier.wait_for_versioned_notifications('instance.create.end')

        # Attach a volume and monitor the volume attachments. As above we
        # injected a wait() into the attachment create in the cinder fixture
        # the BDM will be created but the attachment_id will not be populated.
        # The API correctly filters the BDMs that has no attachment_id so the
        # response schema is kept.
        self._attach_volume(server, volume_id)

    def test_attach_and_list_race(self):
        volume_id = self.cinder.IMAGE_BACKED_VOL
        server = self._create_server(networks='none')
        self.notifier.wait_for_versioned_notifications('instance.create.end')

        # Attach a volume and monitor the volume attachments. As above we
        # injected a wait() into the attachment create in the cinder fixture
        # the BDM will be created but the attachment_id will not be populated.
        # The API correctly filters the BDMs that has no attachment_id so the
        # response schema is kept.
        self.api.post_server_volume(
            server['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        while not self.api.get_server_volumes(server['id']):
            time.sleep(0.1)

        self.assertEqual(1, len(self.api.get_server_volumes(server['id'])))
