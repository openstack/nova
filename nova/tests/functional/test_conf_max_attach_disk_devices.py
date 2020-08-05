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

import time

import six

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class ConfigurableMaxDiskDevicesTest(integrated_helpers._IntegratedTestBase):

    def _wait_for_volume_attach(self, server_id, volume_id):
        for i in range(0, 100):
            server = self.api.get_server(server_id)
            attached_vols = [vol['id'] for vol in
                             server['os-extended-volumes:volumes_attached']]
            if volume_id in attached_vols:
                return
            time.sleep(.1)
        self.fail('Timed out waiting for volume %s to be attached to '
                  'server %s. Currently attached volumes: %s' %
                  (volume_id, server_id, attached_vols))

    def test_boot_from_volume(self):
        # Set the maximum to 1 and boot from 1 volume. This should pass.
        self.flags(max_disk_devices_to_attach=1, group='compute')
        server = self._build_server(flavor_id='1')
        server['imageRef'] = ''
        volume_uuid = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        bdm = {'boot_index': 0,
               'uuid': volume_uuid,
               'source_type': 'volume',
               'destination_type': 'volume'}
        server['block_device_mapping_v2'] = [bdm]
        created_server = self.api.post_server({"server": server})
        self._wait_for_state_change(created_server, 'ACTIVE')

    def test_boot_from_volume_plus_attach_max_exceeded(self):
        # Set the maximum to 1, boot from 1 volume, and attach one volume.
        # This should fail because it's trying to attach 2 disk devices.
        self.flags(max_disk_devices_to_attach=1, group='compute')
        server = self._build_server(flavor_id='1')
        server['imageRef'] = ''
        vol_img_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        boot_vol = {'boot_index': 0,
                    'uuid': vol_img_id,
                    'source_type': 'volume',
                    'destination_type': 'volume'}
        vol_id = '9a695496-44aa-4404-b2cc-ccab2501f87e'
        other_vol = {'uuid': vol_id,
                     'source_type': 'volume',
                     'destination_type': 'volume'}
        server['block_device_mapping_v2'] = [boot_vol, other_vol]
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        # Server should go into ERROR state
        self._wait_for_state_change(created_server, 'ERROR')
        # Verify the instance fault
        server = self.api.get_server(server_id)
        # If anything fails during _prep_block_device, a 500 internal server
        # error is raised.
        self.assertEqual(500, server['fault']['code'])
        expected = ('Build of instance %s aborted: The maximum allowed number '
                    'of disk devices (1) to attach to a single instance has '
                    'been exceeded.' % server_id)
        self.assertIn(expected, server['fault']['message'])
        # Verify no volumes are attached (this is a generator)
        attached_vols = list(self.cinder.volume_ids_for_instance(server_id))
        self.assertNotIn(vol_img_id, attached_vols)
        self.assertNotIn(vol_id, attached_vols)

    def test_attach(self):
        # Set the maximum to 2. This will allow one disk device for the local
        # disk of the server and also one volume to attach. A second volume
        # attach request will fail.
        self.flags(max_disk_devices_to_attach=2, group='compute')
        server = self._build_server(flavor_id='1')
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        self._wait_for_state_change(created_server, 'ACTIVE')
        # Attach one volume, should pass.
        vol_id = '9a695496-44aa-4404-b2cc-ccab2501f87e'
        self.api.post_server_volume(
            server_id, dict(volumeAttachment=dict(volumeId=vol_id)))
        self._wait_for_volume_attach(server_id, vol_id)
        # Attach a second volume, should fail fast in the API.
        other_vol_id = 'f2063123-0f88-463c-ac9d-74127faebcbe'
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.post_server_volume,
            server_id, dict(volumeAttachment=dict(volumeId=other_vol_id)))
        self.assertEqual(403, ex.response.status_code)
        expected = ('The maximum allowed number of disk devices (2) to attach '
                    'to a single instance has been exceeded.')
        self.assertIn(expected, six.text_type(ex))
        # Verify only one volume is attached (this is a generator)
        attached_vols = list(self.cinder.volume_ids_for_instance(server_id))
        self.assertIn(vol_id, attached_vols)
        self.assertNotIn(other_vol_id, attached_vols)
