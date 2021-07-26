#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import datetime

from nova.compute import instance_actions
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network

CELL1_NAME = 'cell1'
CELL2_NAME = 'cell2'


class _AggregateTestCase(integrated_helpers._IntegratedTestBase):

    def _create_aggregate(self, metadata):
        aggregate = self.admin_api.post_aggregate(
            {'aggregate': {'name': 'my-aggregate'}})
        aggregate = self.admin_api.post_aggregate_action(
            aggregate['id'],
            {'set_metadata': {'metadata': metadata}})
        self.admin_api.add_host_to_aggregate(
            aggregate['id'], self.compute.host)
        return aggregate


class AggregateImagePropertiesIsolationTestCase(_AggregateTestCase):
    """Test the AggregateImagePropertiesIsolation filter."""

    def setUp(self):
        self.flags(
            enabled_filters=['AggregateImagePropertiesIsolation'],
            group='filter_scheduler')

        super().setUp()

    def _create_image(self, metadata):
        image = {
            'id': 'c456eb30-91d7-4f43-8f46-2efd9eccd744',
            'name': 'fake-image-custom-property',
            'created_at': datetime.datetime(2011, 1, 1, 1, 2, 3),
            'updated_at': datetime.datetime(2011, 1, 1, 1, 2, 3),
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'raw',
            'disk_format': 'raw',
            'size': '25165824',
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': ['tag1', 'tag2'],
            'properties': {
                'kernel_id': 'nokernel',
                'ramdisk_id': 'nokernel',
            },
        }
        image['properties'].update(metadata)
        return self.glance.create(None, image)

    def test_filter_passes(self):
        """Ensure the filter allows hosts in aggregates with matching metadata.
        """
        self._create_aggregate(metadata={'os_type': 'windows'})
        image = self._create_image(metadata={'os_type': 'windows'})
        self._create_server(image_uuid=image['id'])

    def test_filter_rejects(self):
        """Ensure the filter rejects hosts in aggregates with mismatched
        metadata.
        """
        self._create_aggregate(metadata={'os_type': 'windows'})
        image = self._create_image(metadata={'os_type': 'linux'})
        self._create_server(image_uuid=image['id'], expected_state='ERROR')

    def test_filter_passes_with_prefix(self):
        """Ensure the filter allows hosts in aggregates with matching metadata
        when a namespace is configured.
        """
        self.flags(
            aggregate_image_properties_isolation_namespace='os',
            aggregate_image_properties_isolation_separator='_',
            group='filter_scheduler',
        )
        self._create_aggregate(metadata={'os_type': 'windows'})
        image = self._create_image(metadata={'os_type': 'windows'})
        self._create_server(image_uuid=image['id'])

    def test_filter_rejects_with_prefix(self):
        """Ensure the filter rejects hosts in aggregates with matching metadata
        when a namespace is configured.
        """
        self.flags(
            aggregate_image_properties_isolation_namespace='os',
            aggregate_image_properties_isolation_separator='_',
            group='filter_scheduler',
        )
        self._create_aggregate(metadata={'os_type': 'windows'})
        image = self._create_image(metadata={'os_type': 'linux'})
        self._create_server(image_uuid=image['id'], expected_state='ERROR')

    def test_filter_passes_with_invalid_key(self):
        """Ensure invalid keys are ignored by the filter."""
        self._create_aggregate(metadata={'type': 'windows'})
        image = self._create_image(metadata={'type': 'linux'})
        self._create_server(image_uuid=image['id'])

    def test_filter_passes_with_irrelevant_key(self):
        """Ensure valid keys that are no in the namespace are ignored by the
        filter.
        """
        self.flags(
            aggregate_image_properties_isolation_namespace='os',
            aggregate_image_properties_isolation_separator='_',
            group='filter_scheduler',
        )
        self._create_aggregate(metadata={'os_type': 'windows'})
        image = self._create_image(metadata={'hw_firmware_type': 'uefi'})
        self._create_server(image_uuid=image['id'])


class AggregateInstanceExtraSpecsFilterTestCase(_AggregateTestCase):
    """Test the AggregateInstanceExtraSpecsFilter filter."""

    def setUp(self):
        self.flags(
            enabled_filters=['AggregateInstanceExtraSpecsFilter'],
            group='filter_scheduler')

        super().setUp()

    def test_filter_passes(self):
        """Ensure the filter allows hosts in aggregates with matching metadata.
        """
        self._create_aggregate(metadata={'foo': 'bar'})
        flavor_id = self._create_flavor(extra_spec={'foo': 'bar'})
        self._create_server(flavor_id=flavor_id)

    def test_filter_rejects(self):
        """Ensure the filter rejects hosts in aggregates with mismatched
        metadata.
        """
        self._create_aggregate(metadata={'foo': 'bar'})
        flavor_id = self._create_flavor(extra_spec={'foo': 'baz'})
        self._create_server(flavor_id=flavor_id, expected_state='ERROR')

    def test_filter_passes_with_prefix(self):
        """Ensure the filter allows hosts in aggregates with matching metadata
        when the namespace is used.
        """
        self._create_aggregate(metadata={'foo': 'bar'})
        flavor_id = self._create_flavor(
            extra_spec={'aggregate_instance_extra_specs:foo': 'bar'})
        self._create_server(flavor_id=flavor_id)

    def test_filter_rejects_with_prefix(self):
        """Ensure the filter rejects hosts in aggregates with mismatched
        metadata when the namespace is used.
        """
        self._create_aggregate(metadata={'foo': 'bar'})
        flavor_id = self._create_flavor(
            extra_spec={'aggregate_instance_extra_specs:foo': 'baz'})
        self._create_server(flavor_id=flavor_id, expected_state='ERROR')


class MultiCellSchedulerTestCase(test.TestCase,
                                 integrated_helpers.InstanceHelperMixin):

    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(MultiCellSchedulerTestCase, self).setUp()
        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.AllServicesCurrent())
        self.useFixture(func_fixtures.PlacementFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        fake_network.set_stub_network_methods(self)

        self.flags(allow_resize_to_same_host=False)
        self.flags(enabled_filters=['AllHostsFilter'],
                   group='filter_scheduler')
        self.start_service('conductor')
        self.start_service('scheduler')

    def _test_create_and_migrate(self, expected_status, az=None):
        server = self._create_server(az=az)

        return self.admin_api.api_post(
            '/servers/%s/action' % server['id'],
            {'migrate': None},
            check_response_status=[expected_status]), server

    def test_migrate_between_cells(self):
        """Verify that migrating between cells is not allowed.

        Right now, we can't migrate between cells. So, create two computes
        in different cells and make sure that migration fails with NoValidHost.
        """
        # Hosts in different cells
        self.start_service('compute', host='compute1', cell_name=CELL1_NAME)
        self.start_service('compute', host='compute2', cell_name=CELL2_NAME)

        _, server = self._test_create_and_migrate(expected_status=202)
        # The instance action should have failed with details.
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')

    def test_migrate_within_cell(self):
        """Verify that migrating within cells is allowed.

        Create two computes in the same cell and validate that the same
        migration is allowed.
        """
        # Hosts in the same cell
        self.start_service('compute', host='compute1', cell_name=CELL1_NAME)
        self.start_service('compute', host='compute2', cell_name=CELL1_NAME)
        # Create another host just so it looks like we have hosts in
        # both cells
        self.start_service('compute', host='compute3', cell_name=CELL2_NAME)

        # Force the server onto compute1 in cell1 so we do not accidentally
        # land on compute3 in cell2 and fail to migrate.
        _, server = self._test_create_and_migrate(expected_status=202,
                                      az='nova:compute1')
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
