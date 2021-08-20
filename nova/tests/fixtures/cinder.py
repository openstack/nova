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

"""Cinder fixture."""

import collections
import copy
import fixtures

from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils

from nova import exception
from nova.tests.fixtures import nova as nova_fixtures

LOG = logging.getLogger(__name__)


class CinderFixture(fixtures.Fixture):
    """A fixture to volume operations with the new Cinder attach/detach API"""

    # the default project_id in OSAPIFixtures
    tenant_id = nova_fixtures.PROJECT_ID

    SWAP_OLD_VOL = 'a07f71dc-8151-4e7d-a0cc-cd24a3f11113'
    SWAP_NEW_VOL = '227cc671-f30b-4488-96fd-7d0bf13648d8'
    SWAP_ERR_OLD_VOL = '828419fa-3efb-4533-b458-4267ca5fe9b1'
    SWAP_ERR_NEW_VOL = '9c6d9c2d-7a8f-4c80-938d-3bf062b8d489'
    SWAP_ERR_ATTACH_ID = '4a3cd440-b9c2-11e1-afa6-0800200c9a66'
    MULTIATTACH_VOL = '4757d51f-54eb-4442-8684-3399a6431f67'

    # This represents a bootable image-backed volume to test
    # boot-from-volume scenarios.
    IMAGE_BACKED_VOL = '6ca404f3-d844-4169-bb96-bc792f37de98'
    # This represents a bootable image-backed volume with required traits
    # as part of volume image metadata
    IMAGE_WITH_TRAITS_BACKED_VOL = '6194fc02-c60e-4a01-a8e5-600798208b5f'

    # This represents a bootable volume backed by iSCSI storage.
    ISCSI_BACKED_VOL = uuids.iscsi_backed_volume

    # Dict of connection_info for the above volumes keyed by the volume id
    VOLUME_CONNECTION_INFO = {
        uuids.iscsi_backed_volume: {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_lun': '1'
            }
        },
        'fake': {
            'driver_volume_type': 'fake',
            'data': {
                'foo': 'bar',
            }
        }
    }

    def __init__(self, test, az='nova'):
        """Initialize this instance of the CinderFixture.

        :param test: The TestCase using this fixture.
        :param az: The availability zone to return in volume GET responses.
            Defaults to "nova" since that is the default we would see
            from Cinder's storage_availability_zone config option.
        """
        super().__init__()
        self.test = test
        self.swap_volume_instance_uuid = None
        self.swap_volume_instance_error_uuid = None
        self.attachment_error_id = None
        self.az = az
        # A dict, keyed by volume id, to a dict, keyed by attachment id,
        # with keys:
        # - id: the attachment id
        # - instance_uuid: uuid of the instance attached to the volume
        # - connector: host connector dict; None if not connected
        # Note that a volume can have multiple attachments even without
        # multi-attach, as some flows create a blank 'reservation' attachment
        # before deleting another attachment. However, a non-multiattach volume
        # can only have at most one attachment with a host connector at a time.
        self.volume_to_attachment = collections.defaultdict(dict)

    def setUp(self):
        super().setUp()

        def fake_get(self_api, context, volume_id, microversion=None):
            # Check for the special swap volumes.
            attachments = self.volume_to_attachment[volume_id]

            if volume_id in (self.SWAP_OLD_VOL, self.SWAP_ERR_OLD_VOL):
                volume = {
                    'status': 'available',
                    'display_name': 'TEST1',
                    'attach_status': 'detached',
                    'id': volume_id,
                    'multiattach': False,
                    'size': 1
                }
                if (
                    (
                        self.swap_volume_instance_uuid and
                        volume_id == self.SWAP_OLD_VOL
                    ) or (
                        self.swap_volume_instance_error_uuid and
                        volume_id == self.SWAP_ERR_OLD_VOL
                    )
                ):
                    if volume_id == self.SWAP_OLD_VOL:
                        instance_uuid = self.swap_volume_instance_uuid
                    else:
                        instance_uuid = self.swap_volume_instance_error_uuid

                    if attachments:
                        attachment = list(attachments.values())[0]

                        volume.update({
                            'status': 'in-use',
                            'attachments': {
                                instance_uuid: {
                                    'mountpoint': '/dev/vdb',
                                    'attachment_id': attachment['id']
                                }
                            },
                            'attach_status': 'attached',
                        })
                    return volume

            # Check to see if the volume is attached.
            if attachments:
                # The volume is attached.
                attachment = list(attachments.values())[0]
                volume = {
                    'status': 'in-use',
                    'display_name': volume_id,
                    'attach_status': 'attached',
                    'id': volume_id,
                    'multiattach': volume_id == self.MULTIATTACH_VOL,
                    'size': 1,
                    'attachments': {
                        attachment['instance_uuid']: {
                            'attachment_id': attachment['id'],
                            'mountpoint': '/dev/vdb'
                        }
                    }
                }
            else:
                # This is a test that does not care about the actual details.
                volume = {
                    'status': 'available',
                    'display_name': 'TEST2',
                    'attach_status': 'detached',
                    'id': volume_id,
                    'multiattach': volume_id == self.MULTIATTACH_VOL,
                    'size': 1
                }

            if 'availability_zone' not in volume:
                volume['availability_zone'] = self.az

            # Check for our special image-backed volume.
            if volume_id in (
                self.IMAGE_BACKED_VOL, self.IMAGE_WITH_TRAITS_BACKED_VOL,
            ):
                # Make it a bootable volume.
                volume['bootable'] = True
                if volume_id == self.IMAGE_BACKED_VOL:
                    # Add the image_id metadata.
                    volume['volume_image_metadata'] = {
                        # There would normally be more image metadata in here.
                        'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
                    }
                elif volume_id == self.IMAGE_WITH_TRAITS_BACKED_VOL:
                    # Add the image_id metadata with traits.
                    volume['volume_image_metadata'] = {
                        'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                        "trait:HW_CPU_X86_SGX": "required",
                    }

            return volume

        def fake_migrate_volume_completion(
            _self, context, old_volume_id, new_volume_id, error,
        ):
            return {'save_volume_id': new_volume_id}

        def _find_attachment(attachment_id):
            """Find attachment corresponding to ``attachment_id``.

            :returns: A tuple of the volume ID, an attachment dict for the
                given attachment ID, and a dict (keyed by attachment id) of
                attachment dicts for the volume.
            """
            for volume_id, attachments in self.volume_to_attachment.items():
                for attachment in attachments.values():
                    if attachment_id == attachment['id']:
                        return volume_id, attachment, attachments

            raise exception.VolumeAttachmentNotFound(
                attachment_id=attachment_id)

        def _find_connection_info(volume_id, attachment_id):
            """Find the connection_info associated with an attachment

            :returns: A connection_info dict based on a deepcopy associated
                with the volume_id but containing the attachment_id, making it
                unique for the attachment.
            """
            connection_info = copy.deepcopy(
                self.VOLUME_CONNECTION_INFO.get(
                    volume_id, self.VOLUME_CONNECTION_INFO.get('fake')
                )
            )
            connection_info['data']['attachment_id'] = attachment_id
            return connection_info

        def fake_attachment_create(
            _self, context, volume_id, instance_uuid, connector=None,
            mountpoint=None,
        ):
            attachment_id = uuidutils.generate_uuid()
            if self.attachment_error_id is not None:
                attachment_id = self.attachment_error_id

            attachment = {'id': attachment_id}

            if connector:
                attachment['connection_info'] = _find_connection_info(
                    volume_id, attachment_id)
            self.volume_to_attachment[volume_id][attachment_id] = {
                'id': attachment_id,
                'instance_uuid': instance_uuid,
                'connector': connector,
            }
            LOG.info(
                'Created attachment %s for volume %s. Total attachments '
                'for volume: %d',
                attachment_id, volume_id,
                len(self.volume_to_attachment[volume_id]))

            return attachment

        def fake_attachment_delete(_self, context, attachment_id):
            # 'attachment' is a tuple defining a attachment-instance mapping
            volume_id, attachment, attachments = (
                _find_attachment(attachment_id))
            del attachments[attachment_id]
            LOG.info(
                'Deleted attachment %s for volume %s. Total attachments '
                'for volume: %d',
                attachment_id, volume_id, len(attachments))

        def fake_attachment_update(
            _self, context, attachment_id, connector, mountpoint=None,
        ):
            # Ensure the attachment exists
            volume_id, attachment, attachments = _find_attachment(
                attachment_id)
            # Cinder will only allow one "connected" attachment per
            # non-multiattach volume at a time.
            if volume_id != self.MULTIATTACH_VOL:
                for _attachment in attachments.values():
                    if _attachment['connector'] is not None:
                        raise exception.InvalidInput(
                            'Volume %s is already connected with attachment '
                            '%s on host %s' % (
                                volume_id, _attachment['id'],
                                _attachment['connector'].get('host')))

            attachment['connector'] = connector
            LOG.info('Updating volume attachment: %s', attachment_id)
            attachment_ref = {
                'id': attachment_id,
                'connection_info': _find_connection_info(
                    volume_id, attachment_id)
            }
            if attachment_id == self.SWAP_ERR_ATTACH_ID:
                # This intentionally triggers a TypeError for the
                # instance.volume_swap.error versioned notification tests.
                attachment_ref = {'connection_info': ()}
            return attachment_ref

        def fake_attachment_get(_self, context, attachment_id):
            # Ensure the attachment exists and grab the volume_id
            volume_id, _, _ = _find_attachment(attachment_id)
            attachment_ref = {
                'id': attachment_id,
                'connection_info': _find_connection_info(
                    volume_id, attachment_id)
            }
            return attachment_ref

        def fake_get_all_volume_types(*args, **kwargs):
            return [{
                # This is used in the 2.67 API sample test.
                'id': '5f9204ec-3e94-4f27-9beb-fe7bb73b6eb9',
                'name': 'lvm-1'
            }]

        def fake_attachment_complete(_self, _context, attachment_id):
            # Ensure the attachment exists
            _find_attachment(attachment_id)
            LOG.info('Completing volume attachment: %s', attachment_id)

        self.test.stub_out(
            'nova.volume.cinder.API.attachment_create', fake_attachment_create)
        self.test.stub_out(
            'nova.volume.cinder.API.attachment_delete', fake_attachment_delete)
        self.test.stub_out(
            'nova.volume.cinder.API.attachment_update', fake_attachment_update)
        self.test.stub_out(
            'nova.volume.cinder.API.attachment_complete',
            fake_attachment_complete)
        self.test.stub_out(
            'nova.volume.cinder.API.attachment_get', fake_attachment_get)
        self.test.stub_out(
            'nova.volume.cinder.API.begin_detaching',
            lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.get', fake_get)
        self.test.stub_out(
            'nova.volume.cinder.API.migrate_volume_completion',
            fake_migrate_volume_completion)
        self.test.stub_out(
            'nova.volume.cinder.API.roll_detaching',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.volume.cinder.is_microversion_supported',
            lambda ctxt, microversion: None)
        self.test.stub_out(
            'nova.volume.cinder.API.check_attached',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.volume.cinder.API.get_all_volume_types',
            fake_get_all_volume_types)
        # TODO(lyarwood): These legacy cinderv2 APIs aren't currently wired
        # into the fixture but should be in the future before we migrate any
        # remaining legacy exports to cinderv3 attachments.
        self.test.stub_out(
            'nova.volume.cinder.API.initialize_connection',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.volume.cinder.API.terminate_connection',
            lambda *args, **kwargs: None)

    def volume_ids_for_instance(self, instance_uuid):
        for volume_id, attachments in self.volume_to_attachment.items():
            for attachment in attachments.values():
                if attachment['instance_uuid'] == instance_uuid:
                    # we might have multiple volumes attached to this instance
                    # so yield rather than return
                    yield volume_id
                    break

    def attachment_ids_for_instance(self, instance_uuid):
        attachment_ids = []
        for volume_id, attachments in self.volume_to_attachment.items():
            for attachment in attachments.values():
                if attachment['instance_uuid'] == instance_uuid:
                    attachment_ids.append(attachment['id'])
        return attachment_ids
