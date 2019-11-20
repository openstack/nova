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

from nova.compute import api as compute_api
from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class ColdMigrationDisallowSameHost(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests cold migrate where the source host does not have the
    COMPUTE_SAME_HOST_COLD_MIGRATE trait.
    """
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(ColdMigrationDisallowSameHost, self).setUp()
        # Start one compute service which will use the fake virt driver
        # which disallows cold migration to the same host.
        self._start_compute('host1')

    def _wait_for_migrate_no_valid_host(self, error='NoValidHost'):
        event = fake_notifier.wait_for_versioned_notifications(
            'compute_task.migrate_server.error')[0]
        self.assertEqual(error,
                         event['payload']['nova_object.data']['reason'][
                             'nova_object.data']['exception'])

    def test_cold_migrate_same_host_not_supported(self):
        """Simple test to show that you cannot cold-migrate to the same host
        when the resource provider does not expose the
        COMPUTE_SAME_HOST_COLD_MIGRATE trait.
        """
        server = self._create_server(networks='none')
        # The fake driver does not report COMPUTE_SAME_HOST_COLD_MIGRATE
        # so cold migration should fail since we only have one host.
        self.api.post_server_action(server['id'], {'migrate': None})
        self._wait_for_migrate_no_valid_host()

    def test_cold_migrate_same_host_old_compute_disallow(self):
        """Upgrade compat test where the resource provider does not report
        the COMPUTE_SAME_HOST_COLD_MIGRATE trait but the compute service is
        old so the API falls back to the allow_resize_to_same_host config which
        defaults to False.
        """
        server = self._create_server(networks='none')
        # Stub the compute service version check to make the compute service
        # appear old.
        fake_service = objects.Service()
        fake_service.version = (
            compute_api.MIN_COMPUTE_SAME_HOST_COLD_MIGRATE - 1)
        with mock.patch('nova.objects.Service.get_by_compute_host',
                        return_value=fake_service) as mock_get_service:
            self.api.post_server_action(server['id'], {'migrate': None})
        mock_get_service.assert_called_once_with(
            test.MatchType(nova_context.RequestContext), 'host1')
        # Since allow_resize_to_same_host defaults to False scheduling failed
        # since there are no other hosts.
        self._wait_for_migrate_no_valid_host()

    def test_cold_migrate_same_host_old_compute_allow(self):
        """Upgrade compat test where the resource provider does not report
        the COMPUTE_SAME_HOST_COLD_MIGRATE trait but the compute service is
        old so the API falls back to the allow_resize_to_same_host config which
        in this test is set to True.
        """
        self.flags(allow_resize_to_same_host=True)
        server = self._create_server(networks='none')
        # Stub the compute service version check to make the compute service
        # appear old.
        fake_service = objects.Service()
        fake_service.version = (
            compute_api.MIN_COMPUTE_SAME_HOST_COLD_MIGRATE - 1)
        with mock.patch('nova.objects.Service.get_by_compute_host',
                        return_value=fake_service) as mock_get_service:
            self.api.post_server_action(server['id'], {'migrate': None})
        mock_get_service.assert_called_once_with(
            test.MatchType(nova_context.RequestContext), 'host1')
        # In this case the compute is old so the API falls back to checking
        # allow_resize_to_same_host which says same-host cold migrate is
        # allowed so the scheduler sends the request to the only compute
        # available but the virt driver says same-host cold migrate is not
        # supported and raises UnableToMigrateToSelf. A reschedule is sent
        # to conductor which results in MaxRetriesExceeded since there are no
        # alternative hosts.
        self._wait_for_migrate_no_valid_host(error='MaxRetriesExceeded')


class ColdMigrationAllowSameHost(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests cold migrate where the source host has the
    COMPUTE_SAME_HOST_COLD_MIGRATE trait.
    """
    compute_driver = 'fake.SameHostColdMigrateDriver'

    def setUp(self):
        super(ColdMigrationAllowSameHost, self).setUp()
        self._start_compute('host1')

    def test_cold_migrate_same_host_supported(self):
        """Simple test to show that you can cold-migrate to the same host
        when the resource provider exposes the COMPUTE_SAME_HOST_COLD_MIGRATE
        trait.
        """
        server = self._create_server(networks='none')
        self.api.post_server_action(server['id'], {'migrate': None})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])
