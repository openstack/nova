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

from unittest import mock

from nova import context
from nova import exception
from nova import objects
from nova.tests.functional import integrated_helpers


class TestDetachAttachmentNotFound(integrated_helpers._IntegratedTestBase):
    """Regression test for the Nova portion of bug 1937084

    This regression test asserts the behaviour of Nova when Cinder raises a 404
    during a DELETE request against an attachment.

    In the context of bug 1937084 this could happen if a caller attempted to
    DELETE a volume attachment through Nova's os-volume_attachments API and
    then made a separate DELETE request against the underlying volume in Cinder
    when it was marked as available.
    """

    microversion = 'latest'

    def test_delete_attachment_volume_not_found(self):
        # Create a server and attach a single volume
        server = self._create_server(networks='none')
        server_id = server['id']
        self.api.post_server_volume(
            server_id,
            {
                'volumeAttachment': {
                    'volumeId': self.cinder.IMAGE_BACKED_VOL
                }
            }
        )
        self._wait_for_volume_attach(server_id, self.cinder.IMAGE_BACKED_VOL)

        # Assert that we have an active bdm for the attachment before we detach
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            context.get_admin_context(),
            self.cinder.IMAGE_BACKED_VOL,
            server_id)

        with mock.patch(
            'nova.volume.cinder.API.attachment_delete',
            side_effect=exception.VolumeAttachmentNotFound(
                attachment_id=bdm.attachment_id)
        ) as (
            mock_attachment_delete
        ):
            # DELETE /servers/{server_id}/os-volume_attachments/{volume_id} is
            # async but as we are using CastAsCall it's sync in our func tests
            self.api.delete_server_volume(
                server_id,
                self.cinder.IMAGE_BACKED_VOL)
            mock_attachment_delete.assert_called_once()

        # Assert that the volume attachment is still removed in Nova
        self.assertRaises(
            exception.VolumeBDMNotFound,
            objects.BlockDeviceMapping.get_by_volume_and_instance,
            context.get_admin_context(),
            self.cinder.IMAGE_BACKED_VOL,
            server_id)
