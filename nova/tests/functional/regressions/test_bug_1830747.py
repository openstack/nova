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

from nova.conductor import api as conductor_api
from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image


class MissingReqSpecInstanceGroupUUIDTestCase(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression recreate test for bug 1830747

    Before change I4244f7dd8fe74565180f73684678027067b4506e in Stein, when
    a cold migration would reschedule to conductor it would not send the
    RequestSpec, only the filter_properties. The filter_properties contain
    a primitive version of the instance group information from the RequestSpec
    for things like the group members, hosts and policies, but not the uuid.
    When conductor is trying to reschedule the cold migration without a
    RequestSpec, it builds a RequestSpec from the components it has, like the
    filter_properties. This results in a RequestSpec with an instance_group
    field set but with no uuid field in the RequestSpec.instance_group.
    That RequestSpec gets persisted and then because of change
    Ie70c77db753711e1449e99534d3b83669871943f, later attempts to load the
    RequestSpec from the database will fail because of the missing
    RequestSpec.instance_group.uuid.

    This test recreates the regression scenario by cold migrating a server
    to a host which fails and triggers a reschedule but without the RequestSpec
    so a RequestSpec is created/updated for the instance without the
    instance_group.uuid set which will lead to a failure loading the
    RequestSpec from the DB later.
    """

    def setUp(self):
        super(MissingReqSpecInstanceGroupUUIDTestCase, self).setUp()
        # Stub out external dependencies.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Configure the API to allow resizing to the same host so we can keep
        # the number of computes down to two in the test.
        self.flags(allow_resize_to_same_host=True)
        # Start nova controller services.
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.start_service('conductor')
        # Use a custom weigher to make sure that we have a predictable
        # scheduling sort order.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        self.start_service('scheduler')
        # Start two computes, one where the server will be created and another
        # where we'll cold migrate it.
        self._start_compute('host1')
        self._start_compute('host2')

    def test_cold_migrate_reschedule(self):
        # Create an anti-affinity group for the server.
        body = {
            'server_group': {
                'name': 'test-group',
                'policies': ['anti-affinity']
            }
        }
        group_id = self.api.api_post(
            '/os-server-groups', body).body['server_group']['id']

        # Create a server in the group which should land on host1 due to our
        # custom weigher.
        body = {'server': self._build_server()}
        body['os:scheduler_hints'] = {'group': group_id}
        server = self.api.post_server(body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        # Verify the group uuid is set in the request spec.
        ctxt = nova_context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(group_id, reqspec.instance_group.uuid)

        # Stub out the ComputeTaskAPI.resize_instance method to not pass the
        # request spec from compute to conductor during a reschedule.
        # This simulates the pre-Stein reschedule behavior.
        original_resize_instance = conductor_api.ComputeTaskAPI.resize_instance

        def stub_resize_instance(_self, context, instance, scheduler_hint,
                                 flavor, *args, **kwargs):
            # Only remove the request spec if we know we're rescheduling
            # which we can determine from the filter_properties retry dict.
            filter_properties = scheduler_hint['filter_properties']
            if filter_properties.get('retry', {}).get('exc'):
                # Assert the group_uuid is passed through the filter properties
                self.assertIn('group_uuid', filter_properties)
                self.assertEqual(group_id, filter_properties['group_uuid'])
                kwargs.pop('request_spec', None)
            return original_resize_instance(
                _self, context, instance, scheduler_hint, flavor, *args,
                **kwargs)
        self.stub_out('nova.conductor.api.ComputeTaskAPI.resize_instance',
                      stub_resize_instance)

        # Now cold migrate the server. Because of allow_resize_to_same_host and
        # the weigher, the scheduler will pick host1 first. The FakeDriver
        # actually allows migrating to the same host so we need to stub that
        # out so the compute will raise UnableToMigrateToSelf like when using
        # the libvirt driver.
        host1_driver = self.computes['host1'].driver
        with mock.patch.dict(host1_driver.capabilities,
                             supports_migrate_to_same_host=False):
            self.api.post_server_action(server['id'], {'migrate': None})
            server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
            self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        # The RequestSpec.instance_group.uuid should still be set.
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(group_id, reqspec.instance_group.uuid)
