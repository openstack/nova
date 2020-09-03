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

import mock

from nova import test

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class TestVolAttachmentsDuringPreLiveMigration(
    integrated_helpers._IntegratedTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 1889108.

    This regression test asserts that the original source volume attachments
    are not removed during the rollback from pre_live_migration failures on the
    destination.
    """
    api_major_version = 'v2.1'
    microversion = 'latest'
    ADMIN_API = True
    USE_NEUTRON = True

    def setUp(self):
        super(TestVolAttachmentsDuringPreLiveMigration, self).setUp()
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

    def _setup_compute_service(self):
        self.start_service('compute', host='src', cell=None)
        self.start_service('compute', host='dest', cell=None)

    @mock.patch('nova.virt.fake.FakeDriver.pre_live_migration',
                side_effect=test.TestingException)
    def test_vol_attachments_during_driver_pre_live_mig_failure(
            self, mock_plm):
        """Assert that the src attachment is incorrectly removed

        * Mock pre_live_migration to always fail within the virt driver
        * Launch a boot from volume instance
        * Assert that the volume is attached correctly to the instance.
        * Live migrate the instance to another host invoking the mocked
          pre_live_migration
        * Assert that the instance is still on the source host
        * Assert that both the original source host volume attachment and
          new destination volume attachment have been removed
        """
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server = {
            'name': 'test_bfv_pre_live_migration_failure',
            'flavorRef': 1,
            'imageRef': '',
            'networks': 'none',
            'block_device_mapping_v2': [{
                'source_type': 'volume',
                'destination_type': 'volume',
                'boot_index': 0,
                'uuid': volume_id}],
        }
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Fetch the source host for use later
        server = self.api.get_server(server['id'])
        src_host = server['OS-EXT-SRV-ATTR:host']

        # Assert that the volume is connected to the instance
        self.assertIn(
            volume_id, self.cinder.volume_ids_for_instance(server['id']))

        # Assert that we have an active attachment in the fixture
        attachments = self.cinder.volume_to_attachment.get(volume_id)
        self.assertEqual(1, len(attachments))

        # Fetch the attachment_id for use later once we have migrated
        src_attachment_id = list(attachments.keys())[0]

        # Migrate the instance and wait until the migration errors out thanks
        # to our mocked version of pre_live_migration raising
        # test.TestingException
        self.api.post_server_action(
            server['id'],
            {'os-migrateLive': {'host': None, 'block_migration': 'auto'}})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        self._wait_for_migration_status(server, ['error'])

        # Assert that we called the fake pre_live_migration method
        mock_plm.assert_called_once()

        # Assert that the instance is listed on the source
        server = self.api.get_server(server['id'])
        self.assertEqual(src_host, server['OS-EXT-SRV-ATTR:host'])

        # Assert that the src attachment is still present
        attachments = self.cinder.volume_to_attachment.get(volume_id)
        self.assertIn(src_attachment_id, attachments.keys())
        self.assertEqual(1, len(attachments))
