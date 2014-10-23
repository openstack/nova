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
Utility functions for Image transfer and manipulation.
"""

import os
import tarfile
import tempfile

from lxml import etree
from oslo_config import cfg
from oslo_utils import strutils
from oslo_utils import units
from oslo_vmware import rw_handles

from nova import exception
from nova.i18n import _, _LI
from nova import image
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import io_util

# NOTE(mdbooth): We use use_linked_clone below, but don't have to import it
# because nova.virt.vmwareapi.driver is imported first. In fact, it is not
# possible to import it here, as nova.virt.vmwareapi.driver calls
# CONF.register_opts() after the import chain which imports this module. This
# is not a problem as long as the import order doesn't change.
CONF = cfg.CONF

LOG = logging.getLogger(__name__)
IMAGE_API = image.API()

QUEUE_BUFFER_SIZE = 10

LINKED_CLONE_PROPERTY = 'vmware_linked_clone'


class VMwareImage(object):
    def __init__(self, image_id,
                 file_size=0,
                 os_type=constants.DEFAULT_OS_TYPE,
                 adapter_type=constants.DEFAULT_ADAPTER_TYPE,
                 disk_type=constants.DEFAULT_DISK_TYPE,
                 container_format=constants.CONTAINER_FORMAT_BARE,
                 file_type=constants.DEFAULT_DISK_FORMAT,
                 linked_clone=None,
                 vif_model=constants.DEFAULT_VIF_MODEL):
        """VMwareImage holds values for use in building VMs.

            image_id (str): uuid of the image
            file_size (int): size of file in bytes
            os_type (str): name of guest os (use vSphere names only)
            adapter_type (str): name of the adapter's type
            disk_type (str): type of disk in thin, thick, etc
            container_format (str): container format (bare or ova)
            file_type (str): vmdk or iso
            linked_clone(bool): use linked clone, or don't
        """
        self.image_id = image_id
        self.file_size = file_size
        self.os_type = os_type
        self.adapter_type = adapter_type
        self.container_format = container_format
        self.disk_type = disk_type
        self.file_type = file_type

        # NOTE(vui): This should be removed when we restore the
        # descriptor-based validation.
        if (self.file_type is not None and
                self.file_type not in constants.DISK_FORMATS_ALL):
            raise exception.InvalidDiskFormat(disk_format=self.file_type)

        if linked_clone is not None:
            self.linked_clone = linked_clone
        else:
            self.linked_clone = CONF.vmware.use_linked_clone
        self.vif_model = vif_model

    @property
    def file_size_in_kb(self):
        return self.file_size / units.Ki

    @property
    def is_sparse(self):
        return self.disk_type == constants.DISK_TYPE_SPARSE

    @property
    def is_iso(self):
        return self.file_type == constants.DISK_FORMAT_ISO

    @property
    def is_ova(self):
        return self.container_format == constants.CONTAINER_FORMAT_OVA

    @classmethod
    def from_image(cls, image_id, image_meta=None):
        """Returns VMwareImage, the subset of properties the driver uses.

        :param image_id - image id of image
        :param image_meta - image metadata we are working with
        :return: vmware image object
        :rtype: nova.virt.vmwareapi.images.VmwareImage
        """
        if image_meta is None:
            image_meta = {}

        properties = image_meta.get("properties", {})

        # calculate linked_clone flag, allow image properties to override the
        # global property set in the configurations.
        image_linked_clone = properties.get(LINKED_CLONE_PROPERTY,
                                            CONF.vmware.use_linked_clone)

        # catch any string values that need to be interpreted as boolean values
        linked_clone = strutils.bool_from_string(image_linked_clone)

        props = {
            'image_id': image_id,
            'linked_clone': linked_clone,
            'container_format': image_meta.get('container_format')
        }

        if 'size' in image_meta:
            props['file_size'] = image_meta['size']
        if 'disk_format' in image_meta:
            props['file_type'] = image_meta['disk_format']

        props_map = {
            'vmware_ostype': 'os_type',
            'vmware_adaptertype': 'adapter_type',
            'vmware_disktype': 'disk_type',
            'hw_vif_model': 'vif_model'
        }

        for k, v in props_map.iteritems():
            if k in properties:
                props[v] = properties[k]

        return cls(**props)


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
        write_file_handle = rw_handles.FileWriteHandle(
            kwargs.get("host"),
            kwargs.get("port"),
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


def fetch_image(context, instance, host, port, dc_name, ds_name, file_path,
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
    read_file_handle = rw_handles.ImageReadHandle(read_iter)
    write_file_handle = rw_handles.FileWriteHandle(
        host, port, dc_name, ds_name, cookies, file_path, file_size)
    start_transfer(context, read_file_handle, file_size,
                   write_file_handle=write_file_handle)
    LOG.debug("Downloaded image file data %(image_ref)s to "
              "%(upload_name)s on the data store "
              "%(data_store_name)s",
              {'image_ref': image_ref,
               'upload_name': 'n/a' if file_path is None else file_path,
               'data_store_name': 'n/a' if ds_name is None else ds_name},
              instance=instance)


def _build_shadow_vm_config_spec(session, name, size_kb, disk_type, ds_name):
    """Return spec for creating a shadow VM for image disk.

    The VM is never meant to be powered on. When used in importing
    a disk it governs the directory name created for the VM
    and the disk type of the disk image to convert to.

    :param name: Name of the backing
    :param size_kb: Size in KB of the backing
    :param disk_type: VMDK type for the disk
    :param ds_name: Datastore name where the disk is to be provisioned
    :return: Spec for creation
    """
    cf = session.vim.client.factory
    controller_device = cf.create('ns0:VirtualLsiLogicController')
    controller_device.key = -100
    controller_device.busNumber = 0
    controller_device.sharedBus = 'noSharing'
    controller_spec = cf.create('ns0:VirtualDeviceConfigSpec')
    controller_spec.operation = 'add'
    controller_spec.device = controller_device

    disk_device = cf.create('ns0:VirtualDisk')
    # for very small disks allocate at least 1KB
    disk_device.capacityInKB = max(1, int(size_kb))
    disk_device.key = -101
    disk_device.unitNumber = 0
    disk_device.controllerKey = -100
    disk_device_bkng = cf.create('ns0:VirtualDiskFlatVer2BackingInfo')
    if disk_type == constants.DISK_TYPE_EAGER_ZEROED_THICK:
        disk_device_bkng.eagerlyScrub = True
    elif disk_type == constants.DISK_TYPE_THIN:
        disk_device_bkng.thinProvisioned = True
    disk_device_bkng.fileName = '[%s]' % ds_name
    disk_device_bkng.diskMode = 'persistent'
    disk_device.backing = disk_device_bkng
    disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
    disk_spec.operation = 'add'
    disk_spec.fileOperation = 'create'
    disk_spec.device = disk_device

    vm_file_info = cf.create('ns0:VirtualMachineFileInfo')
    vm_file_info.vmPathName = '[%s]' % ds_name

    create_spec = cf.create('ns0:VirtualMachineConfigSpec')
    create_spec.name = name
    create_spec.guestId = 'otherGuest'
    create_spec.numCPUs = 1
    create_spec.memoryMB = 128
    create_spec.deviceChange = [controller_spec, disk_spec]
    create_spec.files = vm_file_info

    return create_spec


def _build_import_spec_for_import_vapp(session, vm_name, datastore_name):
    vm_create_spec = _build_shadow_vm_config_spec(
            session, vm_name, 0, constants.DISK_TYPE_THIN, datastore_name)

    client_factory = session.vim.client.factory
    vm_import_spec = client_factory.create('ns0:VirtualMachineImportSpec')
    vm_import_spec.configSpec = vm_create_spec
    return vm_import_spec


def fetch_image_stream_optimized(context, instance, session, vm_name,
                                 ds_name, vm_folder_ref, res_pool_ref):
    """Fetch image from Glance to ESX datastore."""
    image_ref = instance.image_ref
    LOG.debug("Downloading image file data %(image_ref)s to the ESX "
              "as VM named '%(vm_name)s'",
              {'image_ref': image_ref, 'vm_name': vm_name},
              instance=instance)

    metadata = IMAGE_API.get(context, image_ref)
    file_size = int(metadata['size'])

    vm_import_spec = _build_import_spec_for_import_vapp(
            session, vm_name, ds_name)

    read_iter = IMAGE_API.download(context, image_ref)
    read_handle = rw_handles.ImageReadHandle(read_iter)

    write_handle = rw_handles.VmdkWriteHandle(session,
                                              session._host,
                                              session._port,
                                              res_pool_ref,
                                              vm_folder_ref,
                                              vm_import_spec,
                                              file_size)
    start_transfer(context,
                   read_handle,
                   file_size,
                   write_file_handle=write_handle)

    imported_vm_ref = write_handle.get_imported_vm()

    LOG.info(_LI("Downloaded image file data %(image_ref)s"),
             {'image_ref': instance['image_ref']}, instance=instance)
    session._call_method(session.vim, "UnregisterVM", imported_vm_ref)
    LOG.info(_LI("The imported VM was unregistered"), instance=instance)


def get_vmdk_name_from_ovf(xmlstr):
    """Parse the OVA descriptor to extract the vmdk name."""

    ovf = etree.fromstring(xmlstr)
    nsovf = "{%s}" % ovf.nsmap["ovf"]

    disk = ovf.find("./%sDiskSection/%sDisk" % (nsovf, nsovf))
    file_id = disk.get("%sfileRef" % nsovf)

    file = ovf.find('./%sReferences/%sFile[@%sid="%s"]' % (nsovf, nsovf,
                                                           nsovf, file_id))
    vmdk_name = file.get("%shref" % nsovf)
    return vmdk_name


def fetch_image_ova(context, instance, session, vm_name, ds_name,
                    vm_folder_ref, res_pool_ref):
    """Download the OVA image from the glance image server to the
    Nova compute node.
    """
    image_ref = instance.image_ref
    LOG.debug("Downloading OVA image file %(image_ref)s to the ESX "
              "as VM named '%(vm_name)s'",
              {'image_ref': image_ref, 'vm_name': vm_name},
              instance=instance)

    metadata = IMAGE_API.get(context, image_ref)
    file_size = int(metadata['size'])

    vm_import_spec = _build_import_spec_for_import_vapp(
        session, vm_name, ds_name)

    read_iter = IMAGE_API.download(context, image_ref)
    ova_fd, ova_path = tempfile.mkstemp()

    try:
        # NOTE(arnaud): Look to eliminate first writing OVA to file system
        with os.fdopen(ova_fd, 'w') as fp:
            for chunk in read_iter:
                fp.write(chunk)
        with tarfile.open(ova_path, mode="r") as tar:
            vmdk_name = None
            for tar_info in tar:
                if tar_info and tar_info.name.endswith(".ovf"):
                    extracted = tar.extractfile(tar_info.name)
                    xmlstr = extracted.read()
                    vmdk_name = get_vmdk_name_from_ovf(xmlstr)
                elif vmdk_name and tar_info.name.startswith(vmdk_name):
                    # Actual file name is <vmdk_name>.XXXXXXX
                    extracted = tar.extractfile(tar_info.name)
                    write_handle = rw_handles.VmdkWriteHandle(
                        session,
                        session._host,
                        session._port,
                        res_pool_ref,
                        vm_folder_ref,
                        vm_import_spec,
                        file_size)
                    start_transfer(context,
                                   extracted,
                                   file_size,
                                   write_file_handle=write_handle)
                    extracted.close()
                    LOG.info(_LI("Downloaded OVA image file %(image_ref)s"),
                        {'image_ref': instance.image_ref}, instance=instance)
                    imported_vm_ref = write_handle.get_imported_vm()
                    session._call_method(session.vim, "UnregisterVM",
                                         imported_vm_ref)
                    LOG.info(_LI("The imported VM was unregistered"),
                             instance=instance)
                    return
            raise exception.ImageUnacceptable(
                reason=_("Extracting vmdk from OVA failed."),
                image_id=image_ref)
    finally:
        os.unlink(ova_path)


def upload_image_stream_optimized(context, image_id, instance, session,
                                  vm, vmdk_size):
    """Upload the snapshotted vm disk file to Glance image server."""
    LOG.debug("Uploading image %s", image_id, instance=instance)
    metadata = IMAGE_API.get(context, image_id)

    read_handle = rw_handles.VmdkReadHandle(session,
                                            session._host,
                                            session._port,
                                            vm,
                                            None,
                                            vmdk_size)

    # Set the image properties. It is important to set the 'size' to 0.
    # Otherwise, the image service client will use the VM's disk capacity
    # which will not be the image size after upload, since it is converted
    # to a stream-optimized sparse disk.
    image_metadata = {'disk_format': 'vmdk',
                      'is_public': metadata['is_public'],
                      'name': metadata['name'],
                      'status': 'active',
                      'container_format': 'bare',
                      'size': 0,
                      'properties': {'vmware_image_version': 1,
                                     'vmware_disktype': 'streamOptimized',
                                     'owner_id': instance.project_id}}

    # Passing 0 as the file size since data size to be transferred cannot be
    # predetermined.
    start_transfer(context,
                   read_handle,
                   0,
                   image_id=image_id,
                   image_meta=image_metadata)

    LOG.debug("Uploaded image %s to the Glance image server", image_id,
              instance=instance)
