# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestRescheduleWithServerGroup(test.TestCase,
                                    integrated_helpers.InstanceHelperMixin):
    """This tests a regression introduced in the Pike release.

    In Pike we converted the affinity filter code to use the RequestSpec object
    instead of legacy dicts. The filter used to populate server group info in
    the filter_properties and the conversion removed that. However, in the
    conductor, we are still converting RequestSpec back and forth between
    object and primitive, and there is a mismatch between the keys being
    set/get in filter_properties. So during a reschedule with a server group,
    we hit an exception "'NoneType' object is not iterable" in the
    RequestSpec.from_primitives method and the reschedule fails.
    """
    def setUp(self):
        super(TestRescheduleWithServerGroup, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())

        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))

        # This stubs out the network allocation in compute.
        fake_network.set_stub_network_methods(self)

        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        # The admin API is used to get the server details to verify the
        # host on which the server was built.
        self.admin_api = api_fixture.admin_api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        # We start two compute services because we're going to fake one raising
        # RescheduledException to trigger a retry to the other compute host.
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

        # This is our flag that we set when we hit the first host and
        # made it fail.
        self.failed_host = None
        self.attempts = 0

        def fake_validate_instance_group_policy(_self, *args, **kwargs):
            self.attempts += 1
            if self.failed_host is None:
                # Set the failed_host value to the ComputeManager.host value.
                self.failed_host = _self.host
                raise exception.RescheduledException(instance_uuid='fake',
                                                     reason='Policy violated')

        self.stub_out('nova.compute.manager.ComputeManager.'
                      '_validate_instance_group_policy',
                      fake_validate_instance_group_policy)

    def test_reschedule_with_server_group(self):
        """Tests the reschedule with server group when one compute host fails.

        This tests the scenario where we have two compute services and try to
        build a single server. The test is setup such that the scheduler picks
        the first host which we mock out to fail the late affinity check. This
        should then trigger a retry on the second host.
        """
        group = {'name': 'a-name', 'policies': ['affinity']}
        created_group = self.api.post_server_groups(group)

        server = {'name': 'retry-with-server-group',
                  'imageRef': self.image_id,
                  'flavorRef': self.flavor_id}
        hints = {'group': created_group['id']}
        created_server = self.api.post_server({'server': server,
                                               'os:scheduler_hints': hints})
        found_server = self._wait_for_state_change(self.admin_api,
                                                   created_server, 'ACTIVE')
        # Assert that the host is not the failed host.
        self.assertNotEqual(self.failed_host,
                            found_server['OS-EXT-SRV-ATTR:host'])
        # Assert that we retried.
        self.assertEqual(2, self.attempts)
