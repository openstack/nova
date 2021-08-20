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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


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
    # Default self.api to the self.admin_api as live migration is admin only
    ADMIN_API = True
    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super(LiveMigrationCinderFailure, self).setUp()
        # Start a second compute node (the first one was started for us by
        # _IntegratedTestBase. set_nodes() is needed to avoid duplicate
        # nodenames. See comments in test_bug_1702454.py.
        self.compute2 = self.start_service('compute', host='host2')

    def test_live_migrate_attachment_delete_fails(self):
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

    def _setup_compute_service(self):
        self._start_compute('src')
        self._start_compute('dest')

    @mock.patch('nova.virt.fake.FakeDriver.live_migration')
    def test_vol_attachments_during_driver_live_mig_failure(self, mock_lm):
        """Assert volume attachments during live migration rollback

        * Mock live_migration to always rollback and raise a failure within the
          fake virt driver
        * Launch a boot from volume instance on src
        * Assert that the volume is attached correctly to the instance
        * Assert that the expected source attachment is recorded in the bdm
        * Wrap pre_live_migration on the dest and assert that we switch over
          to the new attachment and connection_info on the dest.
        * Live migrate the instance to another host invoking the mocked
          live_migration method
        * Assert that the instance is still on the source host
        * Assert that the original source host volume attachment remains
        * Assert that the original src connection_info is in the bdm
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
            name='test_bfv_live_migration_failure',
            image_uuid='',
            networks='none',
            host='src'
        )
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': volume_id,
        }]
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(server, 'ACTIVE')

        # Assert that the instance has landed correctly on src
        server = self.api.get_server(server['id'])
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])

        # Assert that the volume is connected to the instance
        self.assertIn(
            volume_id, self.cinder.volume_ids_for_instance(server['id']))

        # Assert that we have an active attachment in the fixture
        attachments = self.cinder.volume_to_attachment.get(volume_id)
        self.assertEqual(1, len(attachments))

        # Fetch the attachment_id for use later once we have migrated
        src_attachment_id = list(attachments.keys())[0]

        # Assert that this attachment_id is stashed in the connection_info
        # of the bdm so we can assert things again after the failure
        ctxt = context.get_admin_context()
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            ctxt, volume_id, server['id'])
        self.assertEqual(src_attachment_id, bdm.attachment_id)
        connection_info = jsonutils.loads(bdm.connection_info)
        self.assertIn('attachment_id', connection_info['data'])
        self.assertEqual(
            src_attachment_id, connection_info['data']['attachment_id'])

        dest_pre_live_mig = self.computes['dest'].manager.pre_live_migration

        # Wrap pre_live_migration on the destination so we can assert that
        # we do switch over to the new attachment before the failure
        # and then later rollback to the source attachment
        def wrap_pre_live_migration(*args, **kwargs):

            # Continue with pre_live_migration before we assert anything
            migrate_data = dest_pre_live_mig(*args, **kwargs)

            # Assert that we now have two attachments in the fixture, one for
            # the src and another for the dest.
            attachments = self.cinder.volume_to_attachment.get(volume_id)
            self.assertEqual(2, len(attachments))

            # Assert that the dest attachment id is saved in the bdm
            # and the connection_info.
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                ctxt, volume_id, server['id'])
            self.assertNotEqual(src_attachment_id, bdm.attachment_id)
            dest_attachment_id = bdm.attachment_id
            connection_info = jsonutils.loads(bdm.connection_info)
            self.assertIn('attachment_id', connection_info['data'])
            self.assertEqual(
                dest_attachment_id, connection_info['data']['attachment_id'])
            return migrate_data

        with mock.patch.object(
            self.computes['dest'].manager,
            'pre_live_migration',
            wrap_pre_live_migration
        ):
            # Migrate the instance and wait until the migration errors out
            # thanks to our mocked version of live_migration raising
            # TestingException
            self._live_migrate(server, 'error', server_expected_state='ERROR')

        # Assert that we called the fake live_migration method
        mock_lm.assert_called_once()

        # Assert that the instance is on the source
        server = self.api.get_server(server['id'])
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])

        # Assert that the src attachment is still present
        attachments = self.cinder.volume_to_attachment.get(volume_id)
        self.assertIn(src_attachment_id, attachments.keys())
        self.assertEqual(1, len(attachments))

        # Assert that the connection_info has reverted back to the src
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            ctxt, volume_id, server['id'])
        self.assertEqual(src_attachment_id, bdm.attachment_id)
        connection_info = jsonutils.loads(bdm.connection_info)
        self.assertIn('attachment_id', connection_info['data'])
        self.assertEqual(
            src_attachment_id, connection_info['data']['attachment_id'])


class LiveMigrationNeutronInteractionsTest(
        integrated_helpers._IntegratedTestBase):
    # NOTE(artom) We need the admin API to force the host when booting the test
    # server.
    ADMIN_API = True
    microversion = 'latest'

    def _setup_compute_service(self):
        self._start_compute('src')
        self._start_compute('dest')

    def test_live_migrate_vifs_from_info_cache(self):
        """Test that bug 1879787 can no longer manifest itself because we get
        the network_info from the instance info cache, and not Neutron.
        """
        def stub_notify(context, instance, event_suffix,
                        network_info=None, extra_usage_info=None, fault=None):
            vif = network_info[0]
            # Make sure we have the correct VIF (the NeutronFixture
            # deterministically uses port_2 for networks=auto) and that the
            # profile does not contain `migrating_to`, indicating that we did
            # not obtain it from the Neutron API.
            self.assertEqual(self.neutron.port_2['id'], vif['id'])
            self.assertNotIn('migrating_to', vif['profile'])

        server = self._create_server(networks='auto',
                                     host=self.computes['src'].host)

        with mock.patch.object(self.computes['src'].manager,
                              '_notify_about_instance_usage',
                              side_effect=stub_notify) as mock_notify:
            self._live_migrate(server, 'completed')
            server = self.api.get_server(server['id'])
            self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
            # We don't care about call arguments here, we just want to be sure
            # our stub actually got called.
            mock_notify.assert_called()
