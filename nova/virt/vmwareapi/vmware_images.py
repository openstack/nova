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
Utility functions to handle vm images. Also include fake image handlers.

"""

import logging
import os
import time

from nova import flags
from nova.virt.vmwareapi import read_write_util
from nova.virt.vmwareapi import io_util

FLAGS = flags.FLAGS

QUEUE_BUFFER_SIZE = 5
READ_CHUNKSIZE = 2 * 1024 * 1024
WRITE_CHUNKSIZE = 2 * 1024 * 1024

LOG = logging.getLogger("nova.virt.vmwareapi.vmware_images")
TEST_IMAGE_PATH = "/tmp/vmware-test-images"


def start_transfer(read_file_handle, write_file_handle, data_size):
    """Start the data transfer from the read handle to the write handle."""
    #The thread safe pipe
    thread_safe_pipe = io_util.ThreadSafePipe(QUEUE_BUFFER_SIZE)
    #The read thread
    read_thread = io_util.IOThread(read_file_handle, thread_safe_pipe,
                                   READ_CHUNKSIZE, long(data_size))
    #The write thread
    write_thread = io_util.IOThread(thread_safe_pipe, write_file_handle,
                                    WRITE_CHUNKSIZE, long(data_size))
    read_thread.start()
    write_thread.start()
    LOG.debug(_("Starting image file transfer"))
    #Wait till both the read thread and the write thread are done
    while not (read_thread.is_done() and write_thread.is_done()):
        if read_thread.get_error() or write_thread.get_error():
            read_thread.stop_io_transfer()
            write_thread.stop_io_transfer()
            # If there was an exception in reading or writing, raise the same.
            read_excep = read_thread.get_exception()
            write_excep = write_thread.get_exception()
            if read_excep is not None:
                LOG.exception(str(read_excep))
                raise Exception(read_excep)
            if write_excep is not None:
                LOG.exception(str(write_excep))
                raise Exception(write_excep)
        time.sleep(2)
    LOG.debug(_("Finished image file transfer and closing the file handles"))
    #Close the file handles
    read_file_handle.close()
    write_file_handle.close()


def fetch_image(image, instance, **kwargs):
    """Fetch an image for attaching to the newly created VM."""
    #Depending upon the image service, make appropriate image service call
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        func = _get_glance_image
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        func = _get_s3_image
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        func = _get_local_image
    elif FLAGS.image_service == "nova.FakeImageService":
        func = _get_fake_image
    else:
        raise NotImplementedError(_("The Image Service %s is not implemented")
                                  % FLAGS.image_service)
    return func(image, instance, **kwargs)


def upload_image(image, instance, **kwargs):
    """Upload the newly snapshotted VM disk file."""
    #Depending upon the image service, make appropriate image service call
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        func = _put_glance_image
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        func = _put_s3_image
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        func = _put_local_image
    elif FLAGS.image_service == "nova.FakeImageService":
        func = _put_fake_image
    else:
        raise NotImplementedError(_("The Image Service %s is not implemented")
                                  % FLAGS.image_service)
    return func(image, instance, **kwargs)


def _get_glance_image(image, instance, **kwargs):
    """Download image from the glance image server."""
    LOG.debug(_("Downloading image %s from glance image server") % image)
    read_file_handle = read_write_util.GlanceHTTPReadFile(FLAGS.glance_host,
                                                          FLAGS.glance_port,
                                                          image)
    file_size = read_file_handle.get_size()
    write_file_handle = read_write_util.VMWareHTTPWriteFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"),
                                file_size)
    start_transfer(read_file_handle, write_file_handle, file_size)
    LOG.debug(_("Downloaded image %s from glance image server") % image)


def _get_s3_image(image, instance, **kwargs):
    """Download image from the S3 image server."""
    raise NotImplementedError


def _get_local_image(image, instance, **kwargs):
    """Download image from the local nova compute node."""
    raise NotImplementedError


def _get_fake_image(image, instance, **kwargs):
    """ Download a fake image from the nova local file repository for testing
    purposes.
    """
    LOG.debug(_("Downloading image %s from fake image service") % image)
    image = str(image)
    file_path = os.path.join(TEST_IMAGE_PATH, image, image)
    file_path = os.path.abspath(file_path)
    read_file_handle = read_write_util.FakeFileRead(file_path)
    file_size = read_file_handle.get_size()
    write_file_handle = read_write_util.VMWareHTTPWriteFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"),
                                file_size)
    start_transfer(read_file_handle, write_file_handle, file_size)
    LOG.debug(_("Downloaded image %s from fake image service") % image)


def _put_glance_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to Glance image server."""
    LOG.debug(_("Uploading image %s to the Glance image server") % image)
    read_file_handle = read_write_util.VmWareHTTPReadFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"))
    file_size = read_file_handle.get_size()
    write_file_handle = read_write_util.GlanceHTTPWriteFile(
                                FLAGS.glance_host,
                                FLAGS.glance_port,
                                image,
                                file_size,
                                kwargs.get("os_type"),
                                kwargs.get("adapter_type"),
                                kwargs.get("image_version"))
    start_transfer(read_file_handle, write_file_handle, file_size)
    LOG.debug(_("Uploaded image %s to the Glance image server") % image)


def _put_local_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to the local nova compute node."""
    raise NotImplementedError


def _put_s3_image(image, instance, **kwargs):
    """Upload the snapshotted vm disk file to S3 image server."""
    raise NotImplementedError


def _put_fake_image(image, instance, **kwargs):
    """ Upload a dummy vmdk from the ESX host to the local file repository of
    the nova node for testing purposes.
    """
    LOG.debug(_("Uploading image %s to the Fake Image Service") % image)
    read_file_handle = read_write_util.VmWareHTTPReadFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"))
    file_size = read_file_handle.get_size()
    image = str(image)
    image_dir_path = os.path.join(TEST_IMAGE_PATH, image)
    if not os.path.exists(TEST_IMAGE_PATH):
        os.mkdir(TEST_IMAGE_PATH)
        os.mkdir(image_dir_path)
    else:
        if not os.path.exists(image_dir_path):
            os.mkdir(image_dir_path)
    file_path = os.path.join(image_dir_path, image)
    file_path = os.path.abspath(file_path)
    write_file_handle = read_write_util.FakeFileWrite(file_path)
    start_transfer(read_file_handle, write_file_handle, file_size)
    LOG.debug(_("Uploaded image %s to the Fake Image Service") % image)


def get_vmdk_size_and_properties(image, instance):
    """
    Get size of the vmdk file that is to be downloaded for attach in spawn.
    Need this to create the dummy virtual disk for the meta-data file. The
    geometry of the disk created depends on the size.
    """
    LOG.debug(_("Getting image size for the image %s") % image)
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        read_file_handle = read_write_util.GlanceHTTPReadFile(
                                      FLAGS.glance_host,
                                      FLAGS.glance_port,
                                      image)
    elif FLAGS.image_service == "nova.image.s3.S3ImageService":
        raise NotImplementedError
    elif FLAGS.image_service == "nova.image.local.LocalImageService":
        raise NotImplementedError
    elif FLAGS.image_service == "nova.FakeImageService":
        image = str(image)
        file_path = os.path.join(TEST_IMAGE_PATH, image, image)
        file_path = os.path.abspath(file_path)
        read_file_handle = read_write_util.FakeFileRead(file_path)
    size = read_file_handle.get_size()
    properties = read_file_handle.get_image_properties()
    read_file_handle.close()
    LOG.debug(_("Got image size of %s for the image %s") % (size, image))
    return size, properties
