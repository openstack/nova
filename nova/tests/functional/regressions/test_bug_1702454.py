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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import cast_as_call
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture


class SchedulerOnlyChecksTargetTest(test.TestCase,
                                    integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1702454 introduced in Newton.

    That test is for verifying that if we evacuate by providing a target, the
    scheduler only checks the related host. If the host is not able to
    accepting the instance, it would return a NoValidHost to the user instead
    of passing the instance to another host.

    Unfortunately, when we wrote the feature for that in Newton, we forgot to
    transform the new RequestSpec field called `requested_destination` into an
    item for the legacy filter_properties dictionary so the scheduler wasn't
    getting it.

    That test will use 3 hosts:
     - host1 which will be the source host for the instance
     - host2 which will be the requested target when evacuating from host1
     - host3 which could potentially be the evacuation target if the scheduler
       doesn't correctly get host2 as the requested destination from the user.
    """

    def setUp(self):
        super(SchedulerOnlyChecksTargetTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())

        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))

        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        # The admin API is used to get the server details to verify the
        # host on which the server was built.
        self.admin_api = api_fixture.admin_api
        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        image_fake.stub_out_image_service(self)
        self.addCleanup(image_fake.FakeImageService_reset)

        self.start_service('conductor')

        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.admin_api.microversion = 'latest'
        self.api.microversion = 'latest'

        # Define a very basic scheduler that only verifies if host is down.
        self.flags(enabled_filters=['ComputeFilter'],
                   group='filter_scheduler')
        # NOTE(sbauza): Use the HostNameWeigherFixture so we are sure that
        # we prefer first host1 for the boot request and forget about any
        # other weigher.
        # Host2 should only be preferred over host3 if and only if that's the
        # only host we verify (as requested_destination does).
        self.useFixture(nova_fixtures.HostNameWeigherFixture(
            weights={'host1': 100, 'host2': 1, 'host3': 50}))
        self.start_service('scheduler')

        # Let's now start three compute nodes as we said above.
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')
        self.start_service('compute', host='host3')
        self.useFixture(cast_as_call.CastAsCall(self))

    def test_evacuate_server(self):
        # We first create the instance
        server = self._build_server(networks='none')
        server = self.admin_api.post_server({'server': server})
        server_id = server['id']
        self.addCleanup(self.api.delete_server, server_id)
        self._wait_for_state_change(server, 'ACTIVE')

        # We need to get instance details for knowing its host
        server = self.admin_api.get_server(server_id)
        host = server['OS-EXT-SRV-ATTR:host']

        # As weigher prefers host1, we are sure we find it here.
        self.assertEqual('host1', host)

        # Now, force host1 to be down. As we use ComputeFilter, it won't ever
        # be a possible destination for the scheduler now.
        self.admin_api.microversion = '2.11'     # Cap for the force-down call.
        self.admin_api.force_down_service(host, 'nova-compute', True)
        self.admin_api.microversion = 'latest'

        # It's time to evacuate by asking host2 as a target. Remember, the
        # only possibility the instance can end up on it is because the
        # scheduler should only verify the requested destination as host2
        # is weighed lower than host3.
        evacuate = {
            'evacuate': {
                'host': 'host2'
            }
        }
        self.admin_api.post_server_action(server['id'], evacuate)

        self._wait_for_state_change(server, 'ACTIVE')
        server = self.admin_api.get_server(server_id)

        # Yeepee, that works!
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
