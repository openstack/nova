# Copyright 2015, 2018 IBM Corp.
#
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

"""Utilities related to glance image management for the PowerVM driver."""

from nova import utils


def stream_blockdev_to_glance(context, image_api, image_id, metadata, devpath):
    """Stream the entire contents of a block device to a glance image.

    :param context: Nova security context.
    :param image_api: Handle to the glance image API.
    :param image_id: UUID of the prepared glance image.
    :param metadata: Dictionary of metadata for the image.
    :param devpath: String path to device file of block device to be uploaded,
                    e.g. "/dev/sde".
    """
    # Make the device file owned by the current user for the duration of the
    # operation.
    with utils.temporary_chown(devpath), open(devpath, 'rb') as stream:
        # Stream it.  This is synchronous.
        image_api.update(context, image_id, metadata, stream)


def generate_snapshot_metadata(context, image_api, image_id, instance):
    """Generate a metadata dictionary for an instance snapshot.

    :param context: Nova security context.
    :param image_api: Handle to the glance image API.
    :param image_id: UUID of the prepared glance image.
    :param instance: The Nova instance whose disk is to be snapshotted.
    :return: A dict of metadata suitable for image_api.update.
    """
    image = image_api.get(context, image_id)

    # TODO(esberglu): Update this to v2 metadata
    metadata = {
        'name': image['name'],
        'status': 'active',
        'disk_format': 'raw',
        'container_format': 'bare',
        'properties': {
            'image_location': 'snapshot',
            'image_state': 'available',
            'owner_id': instance.project_id,
        }
    }
    return metadata
