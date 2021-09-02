# Copyright 2021, Red Hat, Inc. All Rights Reserved.
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

from oslo_serialization import jsonutils

from nova import context
from nova import objects
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base
from nova.virt import block_device as driver_block_device


class TestLibvirtROMultiattachMigrate(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 1939545

    This regression test asserts the now fixed behaviour of Nova during
    a Cinder orchestrated volume migration that leaves the stashed
    connection_info of the attachment pointing at the original
    volume UUID used during the migration.

    This is slightly different to the Nova orchestrated pure swap_volume
    flow so an additional test is included to assert the current correct
    behaviour there and to hopefully illustrate the differences better to
    reviewers.
    """

    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()
        self.start_compute()

    def test_ro_multiattach_swap_volume(self):
        server_id = self._create_server(networks='none')['id']
        self.api.post_server_volume(
            server_id,
            {
                'volumeAttachment': {
                    'volumeId': self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL
                }
            }
        )
        self._wait_for_volume_attach(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL)

        # Swap between the old and new volumes
        self.api.put_server_volume(
            server_id,
            self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL,
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL)

        # Wait until the old volume is detached and new volume is attached
        self._wait_for_volume_detach(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_OLD_VOL)
        self._wait_for_volume_attach(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL)

        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            context.get_admin_context(),
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL,
            server_id)
        connection_info = jsonutils.loads(bdm.connection_info)

        # Assert that only the new volume UUID is referenced within the stashed
        # connection_info and returned by driver_block_device.get_volume_id
        self.assertIn('volume_id', connection_info.get('data'))
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL,
            connection_info['data']['volume_id'])
        self.assertIn('volume_id', connection_info)
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL,
            connection_info['volume_id'])
        self.assertIn('serial', connection_info)
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL,
            connection_info.get('serial'))
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL,
            driver_block_device.get_volume_id(connection_info))

        # Assert that the new volume can be detached from the instance
        self.api.delete_server_volume(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL)
        self._wait_for_volume_detach(
            server_id, self.cinder.MULTIATTACH_RO_SWAP_NEW_VOL)

    def test_ro_multiattach_migrate_volume(self):
        server_id = self._create_server(networks='none')['id']
        self.api.post_server_volume(
            server_id,
            {
                'volumeAttachment': {
                    'volumeId': self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL
                }
            }
        )
        self._wait_for_volume_attach(
            server_id, self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL)

        # Mimic Cinder during the volume migration flow by calling swap_volume
        # with a source volume that has a migration_status of migrating.
        self.api.put_server_volume(
            server_id,
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            self.cinder.MULTIATTACH_RO_MIGRATE_NEW_VOL)

        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            context.get_admin_context(),
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            server_id)
        connection_info = jsonutils.loads(bdm.connection_info)

        # Assert that only the old volume UUID is referenced within the stashed
        # connection_info and returned by driver_block_device.get_volume_id
        self.assertIn('serial', connection_info)
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            connection_info.get('serial'))
        self.assertIn('volume_id', connection_info)
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            connection_info['volume_id'])
        self.assertIn('volume_id', connection_info.get('data'))
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            connection_info['data']['volume_id'])
        self.assertEqual(
            self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL,
            driver_block_device.get_volume_id(connection_info))

        # Assert that the old volume can be detached from the instance
        self.api.delete_server_volume(
            server_id, self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL)
        self._wait_for_volume_detach(
            server_id, self.cinder.MULTIATTACH_RO_MIGRATE_OLD_VOL)
