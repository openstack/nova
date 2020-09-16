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

import copy

from oslo_utils.fixture import uuidsentinel as uuids

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class TestNeutronExternalNetworks(test.TestCase,
                                  integrated_helpers.InstanceHelperMixin):
    """Tests for creating a server on a neutron network with
    router:external=True.
    """
    def setUp(self):
        super(TestNeutronExternalNetworks, self).setUp()
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.GlanceFixture(self))
        neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        self._setup_external_network(neutron)
        # Start nova controller services.
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute', host='host1')

    @staticmethod
    def _setup_external_network(neutron):
        # Add related network to the neutron fixture specifically for these
        # tests. It cannot be added globally in the fixture init as it adds a
        # second network that makes auto allocation based tests fail due to
        # ambiguous networks.
        external_network = copy.deepcopy(neutron.network_2)  # has shared=False
        external_network['name'] = 'external'
        external_network['router:external'] = True
        external_network['id'] = uuids.external_network
        neutron._networks[external_network['id']] = external_network

    def test_non_admin_create_server_on_external_network(self):
        """By default policy non-admin users are not allowed to create
        servers on external networks that are not shared. Doing so should
        result in the server failing to build with an
        ExternalNetworkAttachForbidden error. Note that we do not use
        SpawnIsSynchronousFixture to make _allocate_network_async synchronous
        in this test since that would change the behavior of the
        ComputeManager._build_resources method and abort the build which is
        not how ExternalNetworkAttachForbidden is really handled in reality.
        """
        server = self._build_server(
            networks=[{'uuid': uuids.external_network}])
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ERROR')
        # The BuildAbortException should be in the server fault message.
        self.assertIn('aborted: Failed to allocate the network(s), not '
                      'rescheduling.', server['fault']['message'])
        # And ExternalNetworkAttachForbidden should be in the logs.
        self.assertIn('ExternalNetworkAttachForbidden',
                      self.stdlog.logger.output)
