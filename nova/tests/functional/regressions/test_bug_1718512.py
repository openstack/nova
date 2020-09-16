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

from nova.compute import manager as compute_manager
from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class TestRequestSpecRetryReschedule(test.TestCase,
                                     integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1718512 introduced in Newton.

    Contains a test for a regression where an instance builds on one host,
    then is resized. During the resize, the first attempted host fails and
    the resize is rescheduled to another host which passes. The failed host
    is persisted in the RequestSpec.retry field by mistake. Then later when
    trying to live migrate the instance to the same host that failed during
    resize, it is rejected by the RetryFilter because it's already in the
    RequestSpec.retry field.
    """
    def setUp(self):
        super(TestRequestSpecRetryReschedule, self).setUp()
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
        self.useFixture(nova_fixtures.GlanceFixture(self))

        self.start_service('conductor')

        # We have to get the image before we use 2.latest otherwise we'll get
        # a 404 on the /images proxy API because of 2.36.
        self.image_id = self.api.get_images()[0]['id']

        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.admin_api.microversion = 'latest'
        self.api.microversion = 'latest'

        # Use custom weigher to make sure that we have a predictable
        # scheduling sort order.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        self.start_service('scheduler')

        # Let's now start three compute nodes as we said above.
        for host in ['host1', 'host2', 'host3']:
            self.start_service('compute', host=host)

    def _stub_resize_failure(self, failed_host):
        actual_prep_resize = compute_manager.ComputeManager._prep_resize

        def fake_prep_resize(_self, *args, **kwargs):
            if _self.host == failed_host:
                raise Exception('%s:fake_prep_resize' % failed_host)
            actual_prep_resize(_self, *args, **kwargs)
        self.stub_out('nova.compute.manager.ComputeManager._prep_resize',
                      fake_prep_resize)

    def test_resize_with_reschedule_then_live_migrate(self):
        """Tests the following scenario:

        - Server is created on host1 successfully.
        - Server is resized; host2 is tried and fails, and rescheduled to
          host3.
        - Then try to live migrate the instance to host2 which should work.
        """
        flavors = self.api.get_flavors()
        flavor1 = flavors[0]
        flavor2 = flavors[1]
        if flavor1["disk"] > flavor2["disk"]:
            # Make sure that flavor1 is smaller
            flavor1, flavor2 = flavor2, flavor1

        # create the instance which should go to host1
        server = self._build_server(
            image_uuid=self.image_id,
            flavor_id=flavor1['id'],
            networks='none')
        server = self.admin_api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        # Stub out the resize to fail on host2, which will trigger a reschedule
        # to host3.
        self._stub_resize_failure('host2')

        # Resize the server to flavor2, which should make it ultimately end up
        # on host3.
        data = {'resize': {'flavorRef': flavor2['id']}}
        self.api.post_server_action(server['id'], data)
        server = self._wait_for_state_change(server,
                                             'VERIFY_RESIZE')
        self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Now live migrate the server to host2 specifically, which previously
        # failed the resize attempt but here it should pass.
        data = {'os-migrateLive': {'host': 'host2', 'block_migration': 'auto'}}
        self.admin_api.post_server_action(server['id'], data)
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        # NOTE(mriedem): The instance status effectively goes to ACTIVE before
        # the migration status is changed to "completed" since
        # post_live_migration_at_destination changes the instance status
        # and _post_live_migration changes the migration status later. So we
        # need to poll the migration record until it's complete or we timeout.
        self._wait_for_migration_status(server, ['completed'])
        reqspec = objects.RequestSpec.get_by_instance_uuid(
            nova_context.get_admin_context(), server['id'])
        self.assertIsNone(reqspec.retry)
