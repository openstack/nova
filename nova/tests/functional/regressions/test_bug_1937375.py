# Copyright 2020, Red Hat, Inc. All Rights Reserved.
#
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

from nova import context
from nova import exception
from nova import objects
from nova.tests.functional import integrated_helpers


class TestDuplicateVolAttachRace(integrated_helpers._IntegratedTestBase):
    """Regression test for bug #1937375

    A regression test to assert the behaviour of bug #1937375 where calls
    to reserve_block_device_name can race and create duplicate bdm records.

    As we can't recreate the race with pure API driven requests in our
    functional tests this instead makes duplicate calls to
    reserve_block_device_name during an attach to mimic the behaviour.
    """

    microversion = 'latest'

    def test_duplicate_volume_attach_race(self):

        ctxt = context.get_admin_context()
        volume_id = self.cinder.IMAGE_BACKED_VOL
        server_id = self._create_server(networks='none')['id']
        original_reserve_name = self.compute.manager.reserve_block_device_name

        def wrap_reserve_block_device_name(*args, **kwargs):
            # We can't cause a race with duplicate API requests as functional
            # tests are single threaded and the first would always complete
            # before the second was serviced. Instead we can wrap
            # reserve_block_device_name on the compute manager and call it
            # twice to mimic two callers racing each other after the checks on
            # the api.
            original_bdm = original_reserve_name(*args, **kwargs)

            # Assert that a repeat call fails as an attachment already exists
            self.assertRaises(
                exception.InvalidVolume,
                original_reserve_name, *args, **kwargs)

            return original_bdm

        with mock.patch.object(
            self.compute.manager,
            'reserve_block_device_name',
            wrap_reserve_block_device_name
        ):
            self.api.post_server_volume(
                server_id, {'volumeAttachment': {'volumeId': volume_id}})

        # Wait for a volume to be attached
        self._wait_for_volume_attach(server_id, volume_id)

        # Fetch all bdms for the instance to assert what we have
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            ctxt, server_id)

        # Assert that the correct bdms are present
        self.assertEqual(2, len(bdms))
        self.assertEqual(volume_id, bdms[1].volume_id)
        self.assertEqual('local', bdms[0].destination_type)
