# Copyright 2018 Red Hat, Inc.
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

import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class FakeCinderError(object):
    """Poor man's Mock because we're stubbing out and not mock.patching. Stubs
    out attachment_delete. We keep a raise and call count to simulate a single
    volume error while being able to assert that we still got called for all
    of an instance's volumes.
    """

    def __init__(self):
        self.raise_count = 0
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        if self.raise_count == 0:
            self.raise_count += 1
            raise exception.CinderConnectionFailed(reason='Fake Cinder error')


class LiveMigrationCinderFailure(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super(LiveMigrationCinderFailure, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        # Start a second compute node (the first one was started for us by
        # _IntegratedTestBase. set_nodes() is needed to avoid duplicate
        # nodenames. See comments in test_bug_1702454.py.
        self.compute2 = self.start_service('compute', host='host2')

    def test_live_migrate_attachment_delete_fails(self):
        self.useFixture(nova_fixtures.CinderFixture(self))
        server = self.api.post_server({
            'server': {
                'flavorRef': 1,
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'name': 'live-migrate-attachment-delete-fail-test',
                'networks': 'none',
                'block_device_mapping_v2': [
                    {'boot_index': 0,
                     'uuid': uuids.broken_volume,
                     'source_type': 'volume',
                     'destination_type': 'volume'},
                    {'boot_index': 1,
                     'uuid': uuids.working_volume,
                     'source_type': 'volume',
                     'destination_type': 'volume'}]}})
        server = self._wait_for_state_change(server, 'ACTIVE')

        source = server['OS-EXT-SRV-ATTR:host']
        if source == self.compute.host:
            dest = self.compute2.host
        else:
            dest = self.compute.host

        post = {
            'os-migrateLive': {
                'host': dest,
                'block_migration': False,
            }
        }
        stub_attachment_delete = FakeCinderError()
        self.stub_out('nova.volume.cinder.API.attachment_delete',
                      stub_attachment_delete)
        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(server,
                                        {'OS-EXT-SRV-ATTR:host': dest,
                                         'status': 'ACTIVE'})
        self.assertEqual(2, stub_attachment_delete.call_count)
        self.assertEqual(1, stub_attachment_delete.raise_count)


class TestVolAttachmentsDuringLiveMigration(
    integrated_helpers._IntegratedTestBase
):
    """Assert the lifecycle of volume attachments during LM rollbacks
    """

    # Default self.api to the self.admin_api as live migration is admin only
    ADMIN_API = True
    microversion = 'latest'

    def setUp(self):
        super().setUp()
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))

    def _setup_compute_service(self):
        self._start_compute('src')
        self._start_compute('dest')

    @mock.patch('nova.virt.fake.FakeDriver.live_migration')
    def test_vol_attachments_during_driver_live_mig_failure(self, mock_lm):
        """Assert volume attachments during live migration rollback

        * Mock live_migration to always rollback and raise a failure within the
          fake virt driver
        * Launch a boot from volume instance
        * Assert that the volume is attached correctly to the instance
        * Live migrate the instance to another host invoking the mocked
          live_migration method
        * Assert that the instance is still on the source host
        * Assert that the original source host volume attachment remains
        """
        # Mock out driver.live_migration so that we always rollback
        def _fake_live_migration_with_rollback(
                context, instance, dest, post_method, recover_method,
                block_migration=False, migrate_data=None):
            # Just call the recover_method to simulate a rollback
            recover_method(context, instance, dest, migrate_data)
            # raise test.TestingException here to imitate a virt driver
            raise test.TestingException()
        mock_lm.side_effect = _fake_live_migration_with_rollback

        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server = self._build_server(
            name='test_bfv_live_migration_failure', image_uuid='',
            networks='none'
        )
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': volume_id
        }]
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(server, 'ACTIVE')

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
        # to our mocked version of live_migration raising TestingException
        self._live_migrate(server, 'error', server_expected_state='ERROR')

        # Assert that we called the fake live_migration method
        mock_lm.assert_called_once()

        # Assert that the instance is on the source
        server = self.api.get_server(server['id'])
        self.assertEqual(src_host, server['OS-EXT-SRV-ATTR:host'])

        # Assert that the src attachment is still present
        attachments = self.cinder.volume_to_attachment.get(volume_id)
        self.assertIn(src_attachment_id, attachments.keys())
        self.assertEqual(1, len(attachments))


class LiveMigrationNeutronFailure(integrated_helpers._IntegratedTestBase):
    # NOTE(artom) We need the admin API to force the host when booting the test
    # server.
    ADMIN_API = True
    microversion = 'latest'

    def _setup_compute_service(self):
        self._start_compute('src')
        self._start_compute('dest')

    def test_live_migrate_get_nw_info_fails(self):
        """Test that if the driver.post_live_migration() call fails (for
        example by not being able to connect to Neutron), the exception goes
        unhandled and results in the live-migration erroring out. This is bug
        1879787.
        """
        server = self._create_server(networks='auto',
                                     host=self.computes['src'].host)

        orig_plm = self.computes['src'].manager._post_live_migration

        def stub_plm(*args, **kwargs):
            """We simulate a failure in driver.post_live_migration() on the
            source by stubbing the source compute's _post_live_migration() with
            a method that, within a context that mocks
            driver.post_live_migration() to raise an exception, calls the
            original compute.manager._post_live_migration(). This is needed to
            make sure driver.post_live_migration() raises only once, and only
            on the source.
            """
            with mock.patch.object(self.computes['src'].manager.network_api,
                                   'get_instance_nw_info',
                                   side_effect=ConnectionError):
                return orig_plm(*args, **kwargs)

        with mock.patch.object(self.computes['src'].manager,
                               '_post_live_migration',
                               side_effect=stub_plm):
            # FIXME(artom) Until bug 1879787 is fixed, the raised
            # ConnectionError will go unhandled, the migration will fail, and
            # the instance will still be reported as being on the source, even
            # though it's actually running on the destination.
            self._live_migrate(server, 'error', server_expected_state='ERROR')
            server = self.api.get_server(server['id'])
            self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])
