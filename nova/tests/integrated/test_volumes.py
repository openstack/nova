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

from nova import flags
from nova import test
from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.tests.integrated.api import client
from nova.volume import driver


LOG = logging.getLogger('nova.tests.integrated')

FLAGS = flags.FLAGS
FLAGS.verbose = True


class VolumesTest(test.TestCase):
    def setUp(self):
        super(VolumesTest, self).setUp()

        self.flags(image_service='nova.image.fake.MockImageService',
                   volume_driver='nova.volume.driver.LoggingVolumeDriver')

        context = integrated_helpers.IntegratedUnitTestContext.startup()
        self.user = context.test_user
        self.api = self.user.openstack_api

    def tearDown(self):
        integrated_helpers.IntegratedUnitTestContext.shutdown()
        super(VolumesTest, self).tearDown()

    def test_get_volumes(self):
        """Simple check that listing volumes works"""
        volumes = self.api.get_volumes()
        for volume in volumes:
            LOG.debug("volume: %s" % volume)

    def test_create_and_delete_volume(self):
        """Creates and deletes a volume"""

        # Create volume with name
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
        retries = 0
        while found_volume['status'] == 'creating':
            LOG.debug("Found %s" % found_volume)
            time.sleep(1)
            found_volume = self.api.get_volume(created_volume_id)
            retries = retries + 1
            if retries > 5:
                break

        # It should be available...
        self.assertEqual('available', found_volume['status'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        for retries in range(5):
            try:
                found_volume = self.api.get_volume(created_volume_id)
            except client.OpenStackApiNotFoundException:
                found_volume = None
                LOG.debug("Got 404, proceeding")
                break

            LOG.debug("Found_volume=%s" % found_volume)
            if found_volume['status'] != 'deleting':
                break
            time.sleep(1)

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


if __name__ == "__main__":
    unittest.main()