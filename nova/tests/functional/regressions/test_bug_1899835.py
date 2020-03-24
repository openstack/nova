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

from unittest import mock

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.libvirt import base

from oslo_serialization import jsonutils


class TestVolumeDisconnectDuringPreLiveMigrationRollback(base.ServersTestBase):
    """Regression test for bug #1899835

    This regression test aims to ensure that no attempt is made to disconnect
    volumes from the destination host of a live migration if a failure is
    encountered early when creating the new volume attachment during
    pre_live_migration ahead of any volumes actually being connected.
    """
    # Default self.api to the self.admin_api as live migration is admin only
    ADMIN_API = True
    microversion = 'latest'

    def setUp(self):
        super().setUp()
        self.start_compute(hostname='src')
        self.start_compute(hostname='dest')

    def test_disconnect_volume_called_during_pre_live_migration_failure(self):
        server = {
            'name': 'test',
            'imageRef': '',
            'flavorRef': 1,
            'networks': 'none',
            'host': 'src',
            'block_device_mapping_v2': [{
                'source_type': 'volume',
                'destination_type': 'volume',
                'boot_index': 0,
                'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
            }]
        }

        with test.nested(
            mock.patch.object(
                self.computes['src'].driver, 'get_volume_connector'),
            mock.patch.object(
                self.computes['src'].driver, '_connect_volume'),
        ) as (
            mock_src_connector, mock_src_connect
        ):
            server = self.api.post_server({'server': server})
            self._wait_for_state_change(server, 'ACTIVE')

        # Assert that we called the src connector and connect mocks
        mock_src_connector.assert_called_once()
        mock_src_connect.assert_called_once()

        # Fetch the connection_info from the src
        ctxt = context.get_admin_context()
        bdm = objects.BlockDeviceMapping.get_by_volume_id(
            ctxt, nova_fixtures.CinderFixture.IMAGE_BACKED_VOL,
            instance_uuid=server['id'])
        src_connection_info = jsonutils.loads(bdm.connection_info)

        with test.nested(
            mock.patch.object(
                self.computes['dest'].driver, 'get_volume_connector'),
            mock.patch.object(
                self.computes['dest'].driver, '_connect_volume'),
            mock.patch.object(
                self.computes['dest'].driver, '_disconnect_volume'),
            mock.patch(
                'nova.volume.cinder.API.attachment_create',
                side_effect=test.TestingException)
        ) as (
            mock_dest_connector, mock_dest_connect, mock_dest_disconnect,
            mock_attachment_create
        ):
            # Attempt to live migrate and ensure it is marked as failed
            self._live_migrate(server, 'failed')

        # Assert that we called the dest connector and attachment_create mocks
        mock_dest_connector.assert_called_once()
        mock_attachment_create.assert_called_once()

        # Assert that connect_volume hasn't been called on the dest
        mock_dest_connect.assert_not_called()

        # FIXME(lyarwood): This is bug #1899835, disconnect_volume shouldn't be
        # called on the destination host without connect_volume first being
        # called and especially using with the connection_info from the source
        mock_dest_disconnect.assert_called_with(
            mock.ANY, src_connection_info, mock.ANY, encryption=mock.ANY)
