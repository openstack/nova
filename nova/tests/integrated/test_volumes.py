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

from nova import service
from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.tests.integrated.api import client
from nova.volume import driver


LOG = logging.getLogger('nova.tests.integrated')


class VolumesTest(integrated_helpers._IntegratedTestBase):
    def setUp(self):
        super(VolumesTest, self).setUp()
        driver.LoggingVolumeDriver.clear_logs()

    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_volume")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/v1' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

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
