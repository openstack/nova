# Copyright 2023, Red Hat, Inc. All Rights Reserved.
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
from nova import context
from nova import objects
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestAttachedVolumes(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin):

    microversion = 'latest'

    def setUp(self):
        super(TestAttachedVolumes, self).setUp()
        self.admin_api = self.api_fixture.admin_api
        self.start_compute()

    def _get_bdm_list(self, server):
        ctxt = context.get_admin_context()
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            ctxt, server['id'])

        return [(
            bdm.volume_id, bdm.attachment_id) for bdm in bdms if bdm.volume_id]

    def test_delete_stale_attachment_from_nova(self):
        volume_id = 'aeb9b5f4-1fe9-4964-ab65-5e168be4de8e'
        # create a server
        server = self._create_server(networks=[])
        server = self._attach_volumes(server, [volume_id])

        # verify if volume attachment created at cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])
        self.assertEqual(1, len(attached_volume_ids))

        # verify if volume attachment created at nova
        bdm_list = self._get_bdm_list(server)
        self.assertEqual(1, len(bdm_list))
        self.assertEqual(volume_id, bdm_list[0][0])

        # delete volume attachment using cinder api
        self.cinder.delete_vol_attachment(bdm_list[0][0])

        # rebooting server should remove stale attachments
        server = self._reboot_server(server, hard=True)

        # verify if volume attachment is present at cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])
        self.assertEqual(0, len(attached_volume_ids))

        # verify if volume attachment is present at nova
        bdm_list = self._get_bdm_list(server)

        # after fix bdm should not have any volume
        self.assertEqual(0, len(bdm_list))

    def test_delete_multiple_stale_attachment_from_nova(self):
        volumes = [
            '543c6517-e1f7-4327-968d-7be8246b798a',
            'f37d7501-f1dd-428f-a1f8-6a9eb951f247',
            '45990290-ef3d-410c-b8cc-45f7830b5a8f',
            '6addafaf-9dc8-470e-88d2-288d0daa616c',
            ]
        # create a server
        server = self._create_server(networks='none')
        server = self._attach_volumes(server, volumes)

        # verify if volume attachment created at cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])
        self.assertEqual(4, len(attached_volume_ids))

        # verify if volume attachment created at nova
        bdm_list = self._get_bdm_list(server)
        bdm_attc_vols = set([bdm[0] for bdm in bdm_list])

        self.assertEqual(4, len(bdm_list))
        self.assertEqual(set(volumes), set(bdm_attc_vols))

        # delete 2 volume attachment using cinder api
        self.cinder.delete_vol_attachment(bdm_list[1][0])
        self.cinder.delete_vol_attachment(bdm_list[3][0])

        server = self._reboot_server(server, hard=True)

        # verify if volume attachment is present at cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])
        self.assertEqual(2, len(attached_volume_ids))

        # verify if volume attachment is present at nova
        bdm_list_2 = self._get_bdm_list(server)
        bdm_attc_vols = [bdm[0] for bdm in bdm_list_2]

        self.assertEqual(2, len(bdm_list_2))

        self.assertIn(bdm_list[0][0], bdm_attc_vols)
        self.assertNotIn(bdm_list[1][0], bdm_attc_vols)
        self.assertIn(bdm_list[2][0], bdm_attc_vols)
        self.assertNotIn(bdm_list[3][0], bdm_attc_vols)

    def test_delete_multiple_stale_attachment_from_cinder(self):
        volume_id = 'aeb9b5f4-1fe9-4964-ab65-5e168be4de8e'
        server = self._create_server(networks=[])
        # this will create a valid attachments
        server = self._attach_volumes(server, [volume_id])

        attachments = 4
        # create stale attachments at cinder
        self._create_vol_attachments_by_cinder(volume_id, server, attachments)

        # verify if volume attachment created at cinder
        # get attachment id by server from cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])

        # here we are checking with +1 because we had attached
        # a valid attachment at L145.
        # this is to differentiate that reboot should not remove
        # a valid attachment and only remove dangling one.
        self.assertEqual(attachments + 1, len(attached_volume_ids))

        for _id in attached_volume_ids:
            _ = self.cinder.get_vol_attachment(_id)
            self.assertEqual(_['instance_uuid'], server['id'])

        # verify if nova aware of new attachments
        bdm_list = self._get_bdm_list(server)
        self.assertEqual(1, len(bdm_list))

        # rebooting server should remove stale attachments
        server = self._reboot_server(server, hard=True)

        # verify if how many volume attachments are present at cinder
        attached_volume_ids = self.cinder.attachment_ids_for_instance(
            server['id'])
        self.assertEqual(1, len(attached_volume_ids))
