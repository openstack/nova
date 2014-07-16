# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

import os

from nova import exception
from nova import image
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import io_util
from nova.virt.vmwareapi import read_write_util

LOG = logging.getLogger(__name__)
IMAGE_API = image.API()

QUEUE_BUFFER_SIZE = 10


def start_transfer(context, read_file_handle, data_size,
        write_file_handle=None, image_id=None, image_meta=None):
    """Start the data transfer from the reader to the writer.
    Reader writes to the pipe and the writer reads from the pipe. This means
    that the total transfer time boils down to the slower of the read/write
    and not the addition of the two times.
    """

    if not image_meta:
        image_meta = {}

    # The pipe that acts as an intermediate store of data for reader to write
    # to and writer to grab from.
    thread_safe_pipe = io_util.ThreadSafePipe(QUEUE_BUFFER_SIZE, data_size)
    # The read thread. In case of glance it is the instance of the
    # GlanceFileRead class. The glance client read returns an iterator
    # and this class wraps that iterator to provide datachunks in calls
    # to read.
    read_thread = io_util.IOThread(read_file_handle, thread_safe_pipe)

    # In case of Glance - VMware transfer, we just need a handle to the
    # HTTP Connection that is to send transfer data to the VMware datastore.
    if write_file_handle:
        write_thread = io_util.IOThread(thread_safe_pipe, write_file_handle)
    # In case of VMware - Glance transfer, we relinquish VMware HTTP file read
    # handle to Glance Client instance, but to be sure of the transfer we need
    # to be sure of the status of the image on glance changing to active.
    # The GlanceWriteThread handles the same for us.
    elif image_id:
        write_thread = io_util.GlanceWriteThread(context, thread_safe_pipe,
                image_id, image_meta)
    # Start the read and write threads.
    read_event = read_thread.start()
    write_event = write_thread.start()
    try:
        # Wait on the read and write events to signal their end
        read_event.wait()
        write_event.wait()
    except Exception as exc:
        # In case of any of the reads or writes raising an exception,
        # stop the threads so that we un-necessarily don't keep the other one
        # waiting.
        read_thread.stop()
        write_thread.stop()

        # Log and raise the exception.
        LOG.exception(exc)
        raise exception.NovaException(exc)
    finally:
        # No matter what, try closing the read and write handles, if it so
        # applies.
        read_file_handle.close()
        if write_file_handle:
            write_file_handle.close()


def upload_iso_to_datastore(iso_path, instance, **kwargs):
    LOG.debug("Uploading iso %s to datastore", iso_path,
              instance=instance)
    with open(iso_path, 'r') as iso_file:
        write_file_handle = read_write_util.VMwareHTTPWriteFile(
            kwargs.get("host"),
            kwargs.get("data_center_name"),
            kwargs.get("datastore_name"),
            kwargs.get("cookies"),
            kwargs.get("file_path"),
            os.fstat(iso_file.fileno()).st_size)

        LOG.debug("Uploading iso of size : %s ",
                  os.fstat(iso_file.fileno()).st_size)
        block_size = 0x10000
        data = iso_file.read(block_size)
        while len(data) > 0:
            write_file_handle.write(data)
            data = iso_file.read(block_size)
        write_file_handle.close()

    LOG.debug("Uploaded iso %s to datastore", iso_path,
              instance=instance)


def fetch_image(context, instance, host, dc_name, ds_name, file_path,
                cookies=None):
    """Download image from the glance image server."""
    image_ref = instance['image_ref']
    LOG.debug("Downloading image file data %(image_ref)s to the "
              "data store %(data_store_name)s",
              {'image_ref': image_ref,
               'data_store_name': ds_name},
              instance=instance)

    metadata = IMAGE_API.get(context, image_ref)
    file_size = int(metadata['size'])
    read_iter = IMAGE_API.download(context, image_ref)
    read_file_handle = read_write_util.GlanceFileRead(read_iter)
    write_file_handle = read_write_util.VMwareHTTPWriteFile(
        host, dc_name, ds_name, cookies, file_path, file_size)
    start_transfer(context, read_file_handle, file_size,
                   write_file_handle=write_file_handle)
    LOG.debug("Downloaded image file data %(image_ref)s to "
              "%(upload_name)s on the data store "
              "%(data_store_name)s",
              {'image_ref': image_ref,
               'upload_name': 'n/a' if file_path is None else file_path,
               'data_store_name': 'n/a' if ds_name is None else ds_name},
              instance=instance)


def upload_image(context, image, instance, **kwargs):
    """Upload the snapshotted vm disk file to Glance image server."""
    LOG.debug("Uploading image %s to the Glance image server", image,
              instance=instance)
    read_file_handle = read_write_util.VMwareHTTPReadFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"))
    file_size = read_file_handle.get_size()
    metadata = IMAGE_API.get(context, image)

    # The properties and other fields that we need to set for the image.
    image_metadata = {"disk_format": "vmdk",
                      "is_public": "false",
                      "name": metadata['name'],
                      "status": "active",
                      "container_format": "bare",
                      "size": file_size,
                      "properties": {"vmware_adaptertype":
                                            kwargs.get("adapter_type"),
                                     "vmware_disktype":
                                            kwargs.get("disk_type"),
                                     "vmware_ostype": kwargs.get("os_type"),
                                     "vmware_image_version":
                                            kwargs.get("image_version"),
                                     "owner_id": instance['project_id']}}
    start_transfer(context, read_file_handle, file_size,
                   image_id=metadata['id'], image_meta=image_metadata)
    LOG.debug("Uploaded image %s to the Glance image server", image,
              instance=instance)


def get_vmdk_size_and_properties(context, image, instance):
    """Get size of the vmdk file that is to be downloaded for attach in spawn.
    Need this to create the dummy virtual disk for the meta-data file. The
    geometry of the disk created depends on the size.
    """

    LOG.debug("Getting image size for the image %s", image,
              instance=instance)
    meta_data = IMAGE_API.get(context, image)
    size, properties = meta_data["size"], meta_data["properties"]
    LOG.debug("Got image size of %(size)s for the image %(image)s",
              {'size': size, 'image': image}, instance=instance)
    return size, properties
