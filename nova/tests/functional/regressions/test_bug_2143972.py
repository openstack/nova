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

import nova

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
import oslo_messaging as messaging
from unittest import mock


class PostLiveMigrationFail(
    test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 2143972
    """

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        self.start_service('conductor')
        self.start_service('scheduler')

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api
        self.api.microversion = 'latest'

        self.src = self._start_compute(host='host1')
        self.dest = self._start_compute(host='host2')

    def test_post_live_migration_keystone_fails(self):
        """Test for bug 2143972.
        This test simulate a service failure during post live migration.
        """
        orig_function = nova.network.neutron.API.setup_networks_on_host
        service_exception = messaging.RemoteError(
            exc_type="Remote Error",
            value="ServiceUnavailable The server is currently "
            "unavailable.")
        self.count_call = 0

        # Fist setup_networks_on_host call is in the pre_live_migration method.
        # Second setup_networks_on_host call is in the post_live_migration
        # method.
        def fake_setup_networks_on_host(*args, **kwargs):
            """Call the original function first and then raise an exception
            simulating keystone or neutron not available.
            """
            self.count_call += 1
            if self.count_call > 1:
                raise service_exception
            return orig_function(*args, **kwargs)

        server = self._create_server(networks=[])
        self.assertEqual(self.src.host, server['OS-EXT-SRV-ATTR:host'])

        with mock.patch(
            'nova.network.neutron.API.setup_networks_on_host',
            side_effect=fake_setup_networks_on_host
        ):

            # FIXME(Uggla) A failure with post_live_migration_at_destination
            # leave the instance in MIGRATING status and
            # migration_expected_state to completed because the exception
            # is not raised by the compute manager.  This is mainly due to
            # the previous behavior that would not want to break, allowing a
            # migration cleanup.  A recent patch allows better handling of post
            # migration errors, so we can now raise an exception in such cases.
            server = self._live_migrate(
                server, migration_expected_state='completed',
                server_expected_state='MIGRATING')

            self.assertEqual(self.src.host, server['OS-EXT-SRV-ATTR:host'])
