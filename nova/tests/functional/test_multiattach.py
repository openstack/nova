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


from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class TestMultiattachVolumes(integrated_helpers._IntegratedTestBase,
                             integrated_helpers.InstanceHelperMixin):
    """Functional tests for creating a server from a multiattach volume
    and attaching a multiattach volume to a server.

    Uses the CinderFixtureNewAttachFlow fixture with a specific volume ID
    to represent a multiattach volume.
    """
    # These are all used in _IntegratedTestBase.
    USE_NEUTRON = True
    api_major_version = 'v2.1'
    microversion = '2.60'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    def setUp(self):
        # Everything has been upgraded to the latest code to support
        # multiattach.
        self.useFixture(nova_fixtures.AllServicesCurrent())
        super(TestMultiattachVolumes, self).setUp()
        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))

    def test_boot_from_volume_and_attach_to_second_server(self):
        """This scenario creates a server from the multiattach volume, waits
        for it to be ACTIVE, and then attaches the volume to another server.
        """
        volume_id = nova_fixtures.CinderFixtureNewAttachFlow.MULTIATTACH_VOL
        create_req = self._build_server(flavor_id='1', image='')
        create_req['networks'] = 'none'
        create_req['block_device_mapping_v2'] = [{
            'uuid': volume_id,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': False,
            'boot_index': 0
        }]
        server = self.api.post_server({'server': create_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Make sure the volume is attached to the first server.
        attachments = self.api.api_get(
            '/servers/%s/os-volume_attachments' % server['id']).body[
            'volumeAttachments']
        self.assertEqual(1, len(attachments))
        self.assertEqual(server['id'], attachments[0]['serverId'])
        self.assertEqual(volume_id, attachments[0]['volumeId'])

        # Now create a second server and attach the same volume to that.
        create_req = self._build_server(
            flavor_id='1', image='155d900f-4e14-4e4c-a73d-069cbf4541e6')
        create_req['networks'] = 'none'
        server2 = self.api.post_server({'server': create_req})
        self._wait_for_state_change(self.api, server2, 'ACTIVE')
        # Attach the volume to the second server.
        self.api.api_post('/servers/%s/os-volume_attachments' % server2['id'],
                          {'volumeAttachment': {'volumeId': volume_id}})
        # Make sure the volume is attached to the second server.
        attachments = self.api.api_get(
            '/servers/%s/os-volume_attachments' % server2['id']).body[
            'volumeAttachments']
        self.assertEqual(1, len(attachments))
        self.assertEqual(server2['id'], attachments[0]['serverId'])
        self.assertEqual(volume_id, attachments[0]['volumeId'])
