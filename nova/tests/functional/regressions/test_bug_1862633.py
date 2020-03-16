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
from neutronclient.common import exceptions as neutron_exception

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier
from nova.tests.unit.image import fake as fake_image


class UnshelveNeutronErrorTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    def setUp(self):
        super(UnshelveNeutronErrorTest, self).setUp()
        # Start standard fixtures.
        placement = func_fixtures.PlacementFixture()
        self.useFixture(placement)
        self.placement_api = placement.api
        self.neutron = nova_fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start nova services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.api.microversion = 'latest'
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

    def test_unshelve_offloaded_fails_due_to_neutron(self):
        server_req = self._build_minimal_create_server_request(
            self.api, name='unshelve-error-vm',
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks=[{'port': self.neutron.port_1['id']}], az='nova:host1')
        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(
            self.api, created_server, 'ACTIVE')

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            self.api, server, {'status': 'SHELVED_OFFLOADED',
                               'OS-EXT-SRV-ATTR:host': None})
        allocations = self.placement_api.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        # disable the original host of the instance to force a port update
        # during unshelve
        source_service_id = self.api.get_services(
            host='host1', binary='nova-compute')[0]['id']
        self.api.put_service(source_service_id, {"status": "disabled"})

        # Simulate that port update fails during unshelve due to neutron is
        # unavailable
        with mock.patch(
                'nova.tests.fixtures.NeutronFixture.'
                'update_port') as mock_update_port:
            mock_update_port.side_effect = neutron_exception.ConnectionFailed(
                reason='test')
            req = {'unshelve': None}
            self.api.post_server_action(server['id'], req)
            fake_notifier.wait_for_versioned_notifications(
                'instance.unshelve.start')
            self._wait_for_server_parameter(
                self.api,
                server,
                {'status': 'SHELVED_OFFLOADED',
                 'OS-EXT-STS:task_state': None,
                 'OS-EXT-SRV-ATTR:host': None})

        # As the instance went back to offloaded state we expect no allocation
        allocations = self.placement_api.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))
