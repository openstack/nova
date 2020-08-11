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

import mock
import six

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class BootFromVolumeTest(integrated_helpers._IntegratedTestBase):

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
        server = self._build_server(image_uuid='', flavor_id=flavor_id)
        volume_uuid = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        bdm = {'boot_index': 0,
               'uuid': volume_uuid,
               'source_type': 'volume',
               'destination_type': 'volume'}
        server['block_device_mapping_v2'] = [bdm]
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        self._wait_for_state_change(created_server, 'ACTIVE')

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
        self._wait_for_state_change(created_server, 'VERIFY_RESIZE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Confirm the resize
        post_data = {'confirmResize': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Shelve
        post_data = {'shelve': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(created_server, 'SHELVED_OFFLOADED')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Unshelve
        post_data = {'unshelve': None}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

        # Rebuild
        # The image_uuid is from CinderFixture for the
        # volume representing IMAGE_BACKED_VOL.
        image_uuid = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        post_data = {'rebuild': {'imageRef': image_uuid}}
        self.api.post_server_action(server_id, post_data)
        self._wait_for_state_change(created_server, 'ACTIVE')

        # Check that hypervisor local disk reporting is still 0
        self._verify_zero_local_gb_used()
        # Check that instance has not been saved with 0 root_gb
        self._verify_instance_flavor_not_zero(server_id)
        # Check that request spec has not been saved with 0 root_gb
        self._verify_request_spec_flavor_not_zero(server_id)

    def test_max_local_block_devices_0_force_bfv(self):
        """Tests that when the API is configured with max_local_block_devices=0
        a user cannot boot from image, they must boot from volume.
        """
        self.flags(max_local_block_devices=0)
        server = self._build_server()
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.admin_api.post_server,
                               {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('You specified more local devices than the limit allows',
                      six.text_type(ex))


class BootFromVolumeLargeRequestTest(test.TestCase,
                                     integrated_helpers.InstanceHelperMixin):

    def setUp(self):
        super(BootFromVolumeLargeRequestTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.CinderFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        # The test cases will handle starting compute/conductor/scheduler
        # services if they need them.

    def test_boot_from_volume_10_servers_255_volumes_2_images(self):
        """Create 10 servers with 255 BDMs each using the same image for 200
        of the BDMs and another image for 55 other BDMs. This is a bit silly
        but it just shows that it's possible and there is no rate limiting
        involved in this type of very heavy request.
        """
        # We only care about API performance in this test case so stub out
        # conductor to not do anything.
        self.useFixture(nova_fixtures.NoopConductorFixture())
        # NOTE(gibi): Do not use 'c905cedb-7281-47e4-8a62-f26bc5fc4c77' image
        # as that is defined with a separate kernel image, leading to one extra
        # call to nova.image.glance.API.get from compute.api
        # _handle_kernel_and_ramdisk()
        image1 = 'a2459075-d96c-40d5-893e-577ff92e721c'
        image2 = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        server = self._build_server()
        server.pop('imageRef')
        server['min_count'] = 10
        bdms = []
        # Create 200 BDMs using image1 and 55 using image2.
        for boot_index in range(255):
            image_uuid = image2 if boot_index >= 200 else image1
            bdms.append({
                'source_type': 'image',
                'destination_type': 'volume',
                'delete_on_termination': True,
                'volume_size': 1,
                'boot_index': boot_index,
                'uuid': image_uuid
            })
        server['block_device_mapping_v2'] = bdms

        # Wrap the image service get method to check how many times it was
        # called.
        with mock.patch('nova.image.glance.API.get',
                        wraps=self.glance.show) as mock_image_get:
            self.api.post_server({'server': server})
            # Assert that there was caching of the GET /v2/images/{image_id}
            # calls. The expected total in this case is 3: one for validating
            # the root BDM image, one for image1 and one for image2 during bdm
            # validation - only the latter two cases use a cache.
            self.assertEqual(3, mock_image_get.call_count)
