# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
#
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

import unittest
import time

from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.tests.integrated.api import client
from nova.volume import driver


LOG = logging.getLogger('nova.tests.integrated')


class VolumesTest(integrated_helpers._IntegratedTestBase):
    def setUp(self):
        super(VolumesTest, self).setUp()
        driver.LoggingVolumeDriver.clear_logs()

    def _get_flags(self):
        f = super(VolumesTest, self)._get_flags()
        f['use_local_volumes'] = False  # Avoids calling local_path
        f['volume_driver'] = 'nova.volume.driver.LoggingVolumeDriver'
        return f

    def test_get_volumes_summary(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes(False)
        for volume in volumes:
            LOG.debug("volume: %s" % volume)

    def test_get_volumes(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes()
        for volume in volumes:
            LOG.debug("volume: %s" % volume)

    def _poll_while(self, volume_id, continue_states, max_retries=5):
        """Poll (briefly) while the state is in continue_states."""
        retries = 0
        while True:
            try:
                found_volume = self.api.get_volume(volume_id)
            except client.OpenStackApiNotFoundException:
                found_volume = None
                LOG.debug("Got 404, proceeding")
                break

            LOG.debug("Found %s" % found_volume)

            self.assertEqual(volume_id, found_volume['id'])

            if not found_volume['status'] in continue_states:
                break

            time.sleep(1)
            retries = retries + 1
            if retries > max_retries:
                break
        return found_volume

    def test_create_and_delete_volume(self):
        """Creates and deletes a volume."""

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        LOG.debug("created_volume: %s" % created_volume)
        self.assertTrue(created_volume['id'])
        created_volume_id = created_volume['id']

        # Check it's there
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])

        # It should also be in the all-volume list
        volumes = self.api.get_volumes()
        volume_names = [volume['id'] for volume in volumes]
        self.assertTrue(created_volume_id in volume_names)

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_while(created_volume_id, ['creating'])

        # It should be available...
        self.assertEqual('available', found_volume['status'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_while(created_volume_id, ['deleting'])

        # Should be gone
        self.assertFalse(found_volume)

        LOG.debug("Logs: %s" % driver.LoggingVolumeDriver.all_logs())

        create_actions = driver.LoggingVolumeDriver.logs_like(
                            'create_volume',
                            id=created_volume_id)
        LOG.debug("Create_Actions: %s" % create_actions)

        self.assertEquals(1, len(create_actions))
        create_action = create_actions[0]
        self.assertEquals(create_action['id'], created_volume_id)
        self.assertEquals(create_action['availability_zone'], 'nova')
        self.assertEquals(create_action['size'], 1)

        export_actions = driver.LoggingVolumeDriver.logs_like(
                            'create_export',
                            id=created_volume_id)
        self.assertEquals(1, len(export_actions))
        export_action = export_actions[0]
        self.assertEquals(export_action['id'], created_volume_id)
        self.assertEquals(export_action['availability_zone'], 'nova')

        delete_actions = driver.LoggingVolumeDriver.logs_like(
                            'delete_volume',
                            id=created_volume_id)
        self.assertEquals(1, len(delete_actions))
        delete_action = export_actions[0]
        self.assertEquals(delete_action['id'], created_volume_id)

    def test_attach_and_detach_volume(self):
        """Creates, attaches, detaches and deletes a volume."""

        # Create server
        server_req = {'server': self._build_minimal_create_server_request()}
        # NOTE(justinsb): Create an extra server so that server_id != volume_id
        self.api.post_server(server_req)
        created_server = self.api.post_server(server_req)
        LOG.debug("created_server: %s" % created_server)
        server_id = created_server['id']

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        LOG.debug("created_volume: %s" % created_volume)
        volume_id = created_volume['id']
        self._poll_while(volume_id, ['creating'])

        # Check we've got different IDs
        self.assertNotEqual(server_id, volume_id)

        # List current server attachments - should be none
        attachments = self.api.get_server_volumes(server_id)
        self.assertEquals([], attachments)

        # Template attach request
        device = '/dev/sdc'
        attach_req = {'device': device}
        post_req = {'volumeAttachment': attach_req}

        # Try to attach to a non-existent volume; should fail
        attach_req['volumeId'] = 3405691582
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.post_server_volume, server_id, post_req)

        # Try to attach to a non-existent server; should fail
        attach_req['volumeId'] = volume_id
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.post_server_volume, 3405691582, post_req)

        # Should still be no attachments...
        attachments = self.api.get_server_volumes(server_id)
        self.assertEquals([], attachments)

        # Do a real attach
        attach_req['volumeId'] = volume_id
        attach_result = self.api.post_server_volume(server_id, post_req)
        LOG.debug(_("Attachment = %s") % attach_result)

        attachment_id = attach_result['id']
        self.assertEquals(volume_id, attach_result['volumeId'])

        # These fields aren't set because it's async
        #self.assertEquals(server_id, attach_result['serverId'])
        #self.assertEquals(device, attach_result['device'])

        # This is just an implementation detail, but let's check it...
        self.assertEquals(volume_id, attachment_id)

        # NOTE(justinsb): There's an issue with the attach code, in that
        # it's currently asynchronous and not recorded until the attach
        # completes.  So the caller must be 'smart', like this...
        attach_done = None
        retries = 0
        while True:
            try:
                attach_done = self.api.get_server_volume(server_id,
                                                             attachment_id)
                break
            except client.OpenStackApiNotFoundException:
                LOG.debug("Got 404, waiting")

            time.sleep(1)
            retries = retries + 1
            if retries > 10:
                break

        expect_attach = {}
        expect_attach['id'] = volume_id
        expect_attach['volumeId'] = volume_id
        expect_attach['serverId'] = server_id
        expect_attach['device'] = device

        self.assertEqual(expect_attach, attach_done)

        # Should be one attachemnt
        attachments = self.api.get_server_volumes(server_id)
        self.assertEquals([expect_attach], attachments)

        # Should be able to get details
        attachment_info = self.api.get_server_volume(server_id, attachment_id)
        self.assertEquals(expect_attach, attachment_info)

        # Getting details on a different id should fail
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.get_server_volume, server_id, 3405691582)
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.get_server_volume,
                          3405691582, attachment_id)

        # Trying to detach a different id should fail
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.delete_server_volume, server_id, 3405691582)

        # Detach should work
        self.api.delete_server_volume(server_id, attachment_id)

        # Again, it's async, so wait...
        retries = 0
        while True:
            try:
                attachment = self.api.get_server_volume(server_id,
                                                        attachment_id)
                LOG.debug("Attachment still there: %s" % attachment)
            except client.OpenStackApiNotFoundException:
                LOG.debug("Got 404, delete done")
                break

            time.sleep(1)
            retries = retries + 1
            self.assertTrue(retries < 10)

        # Should be no attachments again
        attachments = self.api.get_server_volumes(server_id)
        self.assertEquals([], attachments)

        LOG.debug("Logs: %s" % driver.LoggingVolumeDriver.all_logs())

        # Discover_volume and undiscover_volume are called from compute
        #  on attach/detach

        disco_moves = driver.LoggingVolumeDriver.logs_like(
                            'discover_volume',
                            id=volume_id)
        LOG.debug("discover_volume actions: %s" % disco_moves)

        self.assertEquals(1, len(disco_moves))
        disco_move = disco_moves[0]
        self.assertEquals(disco_move['id'], volume_id)

        last_days_of_disco_moves = driver.LoggingVolumeDriver.logs_like(
                            'undiscover_volume',
                            id=volume_id)
        LOG.debug("undiscover_volume actions: %s" % last_days_of_disco_moves)

        self.assertEquals(1, len(last_days_of_disco_moves))
        undisco_move = last_days_of_disco_moves[0]
        self.assertEquals(undisco_move['id'], volume_id)
        self.assertEquals(undisco_move['mountpoint'], device)
        self.assertEquals(undisco_move['instance_id'], server_id)

    def test_create_volume_with_metadata(self):
        """Creates and deletes a volume."""

        # Create volume
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'metadata': metadata}})
        LOG.debug("created_volume: %s" % created_volume)
        self.assertTrue(created_volume['id'])
        created_volume_id = created_volume['id']

        # Check it's there and metadata present
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(metadata, found_volume['metadata'])

if __name__ == "__main__":
    unittest.main()
