# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
"""
Utility functions for Image transfer.
"""

import glance.client

from nova import exception
from nova import flags
from nova import log as logging
from nova.virt.vmwareapi import read_write_util

FLAGS = flags.FLAGS

QUEUE_BUFFER_SIZE = 5
READ_CHUNKSIZE = 2 * 1024 * 1024
WRITE_CHUNKSIZE = 2 * 1024 * 1024

LOG = logging.getLogger("nova.virt.vmwareapi.vmware_images")


def fetch_image(image, instance, **kwargs):
    """Fetch an image for attaching to the newly created VM."""
    # Depending upon the image service, make appropriate image service call
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        func = _get_glance_image
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        func = _get_s3_image
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        func = _get_local_image
    else:
        raise NotImplementedError(_("The Image Service %s is not implemented")
                                  % FLAGS.image_service)
    return func(image, instance, **kwargs)


def upload_image(image, instance, **kwargs):
    """Upload the newly snapshotted VM disk file."""
    # Depending upon the image service, make appropriate image service call
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        func = _put_glance_image
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        func = _put_s3_image
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        func = _put_local_image
    else:
        raise NotImplementedError(_("The Image Service %s is not implemented")
                                  % FLAGS.image_service)
    return func(image, instance, **kwargs)


def _get_glance_image(image, instance, **kwargs):
    """Download image from the glance image server."""
    LOG.debug(_("Downloading image %s from glance image server") % image)
    glance_client = glance.client.Client(FLAGS.glance_host, FLAGS.glance_port)
    metadata, read_file_handle = glance_client.get_image(image)
    file_size = int(metadata['size'])
    write_file_handle = read_write_util.VMWareHTTPWriteFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"),
                                file_size)
    for chunk in read_file_handle:
        write_file_handle.write(chunk)
    LOG.debug(_("Downloaded image %s from glance image server") % image)


def _get_s3_image(image, instance, **kwargs):
    """Download image from the S3 image server."""
    raise NotImplementedError


def _get_local_image(image, instance, **kwargs):
    """Download image from the local nova compute node."""
    raise NotImplementedError


def _put_glance_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to Glance image server."""
    LOG.debug(_("Uploading image %s to the Glance image server") % image)
    read_file_handle = read_write_util.VmWareHTTPReadFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"))
    glance_client = glance.client.Client(FLAGS.glance_host, FLAGS.glance_port)
    image_metadata = {"is_public": True,
                      "disk_format": "vmdk",
                      "container_format": "bare",
                      "type": "vmdk",
                      "properties": {"vmware_adaptertype":
                                            kwargs.get("adapter_type"),
                                     "vmware_ostype": kwargs.get("os_type"),
                                     "vmware_image_version":
                                            kwargs.get("image_version")}}
    glance_client.update_image(image, image_meta=image_metadata,
                               image_data=read_file_handle)
    LOG.debug(_("Uploaded image %s to the Glance image server") % image)


def _put_local_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to the local nova compute node."""
    raise NotImplementedError


def _put_s3_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to S3 image server."""
    raise NotImplementedError


def get_vmdk_size_and_properties(image, instance):
    """
    Get size of the vmdk file that is to be downloaded for attach in spawn.
    Need this to create the dummy virtual disk for the meta-data file. The
    geometry of the disk created depends on the size.
    """

    LOG.debug(_("Getting image size for the image %s") % image)
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        glance_client = glance.client.Client(FLAGS.glance_host,
                                             FLAGS.glance_port)
        meta_data = glance_client.get_image_meta(image)
        size, properties = meta_data["size"], meta_data["properties"]
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        raise NotImplementedError
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        raise NotImplementedError
    LOG.debug(_("Got image size of %(size)s for the image %(image)s") %
              locals())
    return size, properties
