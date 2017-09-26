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

from nova import context as nova_context
from nova.db import api as db_api
from nova.objects import virtual_interface
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image


class FillVirtualInterfaceListMigration(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for a bug 1825034 introduced in Stein.

    The fill_virtual_interface_list online data migration creates a mostly
    empty marker instance record and immediately (soft) deletes it just to
    satisfy a foreign key constraint with the virtual_interfaces table.

    The problem is since the fake instance marker record is mostly empty,
    it can fail to load fields in the API when listing deleted servers.
    """

    def setUp(self):
        super(FillVirtualInterfaceListMigration, self).setUp()
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')
        # the image fake backend needed for image discovery
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

    def _create_server(self):
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'test_fill_vifs_migration',
                'networks': [{
                    'uuid': nova_fixtures.NeutronFixture.network_1['id']
                }],
                'imageRef': fake_image.get_valid_image_id()
            }
        })
        return self._wait_for_state_change(self.api, server, 'ACTIVE')

    def test_fill_vifs_migration(self):
        # Create a test server.
        self._create_server()
        # Run the online data migration which will create a (soft-deleted)
        # marker record.
        ctxt = nova_context.get_admin_context()
        virtual_interface.fill_virtual_interface_list(ctxt, max_count=50)
        # Now archive the deleted instance record.
        # The following (archive stuff) is used to prove that the migration
        # created a "fake instance". It is not necessary to trigger the bug.
        table_to_rows_archived, deleted_instance_uuids, total_rows_archived = (
            db_api.archive_deleted_rows(max_rows=1000))
        self.assertIn('instances', table_to_rows_archived)
        self.assertEqual(1, table_to_rows_archived['instances'])
        self.assertEqual(1, len(deleted_instance_uuids))
        self.assertEqual(virtual_interface.FAKE_UUID,
                         deleted_instance_uuids[0])
        # Since the above (archive stuff) removed the fake instance, do the
        # migration again to recreate it so we can exercise the code path.
        virtual_interface.fill_virtual_interface_list(ctxt, max_count=50)
        # Now list deleted servers. The fake marker instance should be excluded
        # from the API results.
        for detail in (True, False):
            servers = self.api.get_servers(detail=detail,
                                           search_opts={'all_tenants': 1,
                                                        'deleted': 1})
            self.assertEqual(0, len(servers))
