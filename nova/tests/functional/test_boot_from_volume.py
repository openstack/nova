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

from nova import context
from nova import objects
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.functional import test_servers


class BootFromVolumeTest(integrated_helpers.InstanceHelperMixin,
                         test_servers.ServersTestBase):
    def _get_hypervisor_stats(self):
        response = self.admin_api.api_get('/os-hypervisors/statistics')
        return response.body['hypervisor_statistics']

    def _verify_zero_local_gb_used(self):
        stats = self._get_hypervisor_stats()
        self.assertEqual(0, stats['local_gb_used'])

    def _verify_instance_flavor_not_zero(self, instance_uuid):
        # We are trying to avoid saving instance records with root_gb=0
        ctxt = context.RequestContext('fake', self.api.project_id)
        instance = objects.Instance.get_by_uuid(ctxt, instance_uuid)
        self.assertNotEqual(0, instance.root_gb)
        self.assertNotEqual(0, instance.flavor.root_gb)

    def _verify_request_spec_flavor_not_zero(self, instance_uuid):
        # We are trying to avoid saving request spec records with root_gb=0
        ctxt = context.RequestContext('fake', self.api.project_id)
        rspec = objects.RequestSpec.get_by_instance_uuid(ctxt, instance_uuid)
        self.assertNotEqual(0, rspec.flavor.root_gb)

    def setUp(self):
        # These need to be set up before services are started, else they
        # won't be reflected in the running service.
        self.flags(allow_resize_to_same_host=True)
        super(BootFromVolumeTest, self).setUp()
        self.admin_api = self.api_fixture.admin_api
        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))

    def test_boot_from_volume_larger_than_local_gb(self):
        # Verify no local disk is being used currently
        self._verify_zero_local_gb_used()

        # Create flavors with disk larger than available host local disk
        flavor_id = self._create_flavor(memory_mb=64, vcpu=1, disk=8192,
                                        ephemeral=0)
        flavor_id_alt = self._create_flavor(memory_mb=64, vcpu=1, disk=16384,
                                            ephemeral=0)

        # Boot a server with a flavor disk larger than the available local
        # disk. It should succeed for boot from volume.
        server = self._build_server(flavor_id)
        server['imageRef'] = ''
        volume_uuid = nova_fixtures.CinderFixtureNewAttachFlow.IMAGE_BACKED_VOL
        bdm = {'boot_index': 0,
               'uuid': volume_uuid,
               'source_type': 'volume',
               'destination_type': 'volume'}
        server['block_device_mapping_v2'] = [bdm]
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        self._wait_for_state_change(self.api, created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Do actions that could change local disk reporting and verify they
        # don't change local disk reporting.

        # Resize
        post_data = {'resize': {'flavorRef': flavor_id_alt}}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(self.api, created_server, 'VERIFY_RESIZE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Confirm the resize
        post_data = {'confirmResize': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(self.api, created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Shelve
        post_data = {'shelve': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(self.api, created_server,
                                    'SHELVED_OFFLOADED')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Unshelve
        post_data = {'unshelve': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(self.api, created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Rebuild
        # The image_uuid is from CinderFixtureNewAttachFlow for the
        # volume representing IMAGE_BACKED_VOL.
        image_uuid = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        post_data = {'rebuild': {'imageRef': image_uuid}}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(self.api, created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)
