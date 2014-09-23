# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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
Class for VM tasks like spawn, snapshot, suspend, resume etc.
"""

import collections
import copy
import os

from oslo.config import cfg

from nova.api.metadata import base as instance_metadata
from nova import compute
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import lockutils
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova import utils
from nova.virt import configdrive
from nova.virt import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import imagecache
from nova.virt.vmwareapi import vif as vmwarevif
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmware_images


vmware_vif_opts = [
    cfg.StrOpt('integration_bridge',
               default='br-int',
               help='Name of Integration Bridge'),
    ]

vmware_group = cfg.OptGroup(name='vmware',
                            title='VMware Options')

CONF = cfg.CONF
CONF.register_group(vmware_group)
CONF.register_opts(vmware_vif_opts, vmware_group)
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('remove_unused_base_images', 'nova.virt.imagecache')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('my_ip', 'nova.netconf')

LOG = logging.getLogger(__name__)

VMWARE_POWER_STATES = {
                   'poweredOff': power_state.SHUTDOWN,
                    'poweredOn': power_state.RUNNING,
                    'suspended': power_state.SUSPENDED}

VMWARE_LINKED_CLONE = 'vmware_linked_clone'

RESIZE_TOTAL_STEPS = 4

DcInfo = collections.namedtuple('DcInfo',
                                ['ref', 'name', 'vmFolder'])


class VMwareVMOps(object):
    """Management class for VM-related tasks."""

    def __init__(self, session, virtapi, volumeops, cluster=None,
                 datastore_regex=None):
        """Initializer."""
        self.compute_api = compute.API()
        self._session = session
        self._virtapi = virtapi
        self._volumeops = volumeops
        self._cluster = cluster
        self._datastore_regex = datastore_regex
        # Ensure that the base folder is unique per compute node
        if CONF.remove_unused_base_images:
            self._base_folder = '%s%s' % (CONF.my_ip,
                                          CONF.image_cache_subdirectory_name)
        else:
            # Aging disable ensures backward compatibility
            self._base_folder = CONF.image_cache_subdirectory_name
        self._tmp_folder = 'vmware_temp'
        self._default_root_device = 'vda'
        self._rescue_suffix = '-rescue'
        self._migrate_suffix = '-orig'
        self._poll_rescue_last_ran = None
        self._is_neutron = utils.is_neutron()
        self._datastore_dc_mapping = {}
        self._datastore_browser_mapping = {}
        self._imagecache = imagecache.ImageCacheManager(self._session,
                                                        self._base_folder)

    def list_instances(self):
        """Lists the VM instances that are registered with the ESX host."""
        LOG.debug(_("Getting list of instances"))
        vms = self._session._call_method(vim_util, "get_objects",
                     "VirtualMachine",
                     ["name", "runtime.connectionState"])
        lst_vm_names = self._get_valid_vms_from_retrieve_result(vms)

        LOG.debug(_("Got total of %s instances") % str(len(lst_vm_names)))
        return lst_vm_names

    def _extend_virtual_disk(self, instance, requested_size, name, dc_ref):
        service_content = self._session._get_vim().get_service_content()
        LOG.debug(_("Extending root virtual disk to %s"), requested_size)
        vmdk_extend_task = self._session._call_method(
                self._session._get_vim(),
                "ExtendVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=name,
                datacenter=dc_ref,
                newCapacityKb=requested_size,
                eagerZero=False)
        try:
            self._session._wait_for_task(vmdk_extend_task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Extending virtual disk failed with error: %s'),
                          e, instance=instance)
                # Clean up files created during the extend operation
                files = [name.replace(".vmdk", "-flat.vmdk"), name]
                for file in files:
                    self._delete_datastore_file(instance, file, dc_ref)

        LOG.debug(_("Extended root virtual disk"))

    def _delete_datastore_file(self, instance, datastore_path, dc_ref):
        try:
            ds_util.file_delete(self._session, datastore_path, dc_ref)
        except (error_util.CannotDeleteFileException,
                error_util.FileFaultException,
                error_util.FileLockedException,
                error_util.FileNotFoundException) as e:
            LOG.debug(_("Unable to delete %(ds)s. There may be more than "
                        "one process or thread that tries to delete the file. "
                        "Exception: %(ex)s"),
                      {'ds': datastore_path, 'ex': e})

    def _get_vmdk_path(self, ds_name, folder, name):
        path = "%s/%s.vmdk" % (folder, name)
        return ds_util.build_datastore_path(ds_name, path)

    def _get_disk_format(self, image_meta):
        disk_format = image_meta.get('disk_format')
        if disk_format not in ['iso', 'vmdk', None]:
            raise exception.InvalidDiskFormat(disk_format=disk_format)
        return (disk_format, disk_format == 'iso')

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info=None,
              instance_name=None, power_on=True):
        """Creates a VM instance.

        Steps followed are:

        1. Create a VM with no disk and the specifics in the instance object
           like RAM size.
        2. For flat disk
          2.1. Create a dummy vmdk of the size of the disk file that is to be
               uploaded. This is required just to create the metadata file.
          2.2. Delete the -flat.vmdk file created in the above step and retain
               the metadata .vmdk file.
          2.3. Upload the disk file.
        3. For sparse disk
          3.1. Upload the disk file to a -sparse.vmdk file.
          3.2. Copy/Clone the -sparse.vmdk file to a thin vmdk.
          3.3. Delete the -sparse.vmdk file.
        4. Attach the disk to the VM by reconfiguring the same.
        5. Power on the VM.
        """
        ebs_root = False
        if block_device_info:
            msg = "Block device information present: %s" % block_device_info
            # NOTE(mriedem): block_device_info can contain an auth_password
            # so we have to scrub the message before logging it.
            LOG.debug(logging.mask_password(msg), instance=instance)
            block_device_mapping = driver.block_device_info_get_mapping(
                    block_device_info)
            if block_device_mapping:
                ebs_root = True

        (file_type, is_iso) = self._get_disk_format(image_meta)

        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()
        ds = vm_util.get_datastore_ref_and_name(self._session, self._cluster,
                 datastore_regex=self._datastore_regex)
        data_store_ref = ds[0]
        data_store_name = ds[1]
        dc_info = self.get_datacenter_ref_and_name(data_store_ref)

        #TODO(hartsocks): this pattern is confusing, reimplement as methods
        # The use of nested functions in this file makes for a confusing and
        # hard to maintain file. At some future date, refactor this method to
        # be a full-fledged method. This will also make unit testing easier.
        def _get_image_properties(root_size):
            """Get the Size of the flat vmdk file that is there on the storage
            repository.
            """
            image_ref = instance.get('image_ref')
            if image_ref:
                _image_info = vmware_images.get_vmdk_size_and_properties(
                        context, image_ref, instance)
            else:
                # The case that the image may be booted from a volume
                _image_info = (root_size, {})

            image_size, image_properties = _image_info
            vmdk_file_size_in_kb = int(image_size) / 1024
            os_type = image_properties.get("vmware_ostype", "otherGuest")
            adapter_type = image_properties.get("vmware_adaptertype",
                                                "lsiLogic")
            disk_type = image_properties.get("vmware_disktype",
                                             "preallocated")
            # Get the network card type from the image properties.
            vif_model = image_properties.get("hw_vif_model", "VirtualE1000")

            # Fetch the image_linked_clone data here. It is retrieved
            # with the above network based API call. To retrieve it
            # later will necessitate additional network calls using the
            # identical method. Consider this a cache.
            image_linked_clone = image_properties.get(VMWARE_LINKED_CLONE)

            return (vmdk_file_size_in_kb, os_type, adapter_type, disk_type,
                vif_model, image_linked_clone)

        root_gb = instance['root_gb']
        root_gb_in_kb = root_gb * units.Mi

        (vmdk_file_size_in_kb, os_type, adapter_type, disk_type, vif_model,
            image_linked_clone) = _get_image_properties(root_gb_in_kb)

        if root_gb_in_kb and vmdk_file_size_in_kb > root_gb_in_kb:
            reason = _("Image disk size greater than requested disk size")
            raise exception.InstanceUnacceptable(instance_id=instance['uuid'],
                                                 reason=reason)

        node_mo_id = vm_util.get_mo_id_from_instance(instance)
        res_pool_ref = vm_util.get_res_pool_ref(self._session,
                                                self._cluster, node_mo_id)

        def _get_vif_infos():
            vif_infos = []
            if network_info is None:
                return vif_infos
            for vif in network_info:
                mac_address = vif['address']
                network_name = vif['network']['bridge'] or \
                               CONF.vmware.integration_bridge
                network_ref = vmwarevif.get_network_ref(self._session,
                                                        self._cluster,
                                                        vif,
                                                        self._is_neutron)
                vif_infos.append({'network_name': network_name,
                                  'mac_address': mac_address,
                                  'network_ref': network_ref,
                                  'iface_id': vif['id'],
                                  'vif_model': vif_model
                                 })
            return vif_infos

        vif_infos = _get_vif_infos()

        # Get the instance name. In some cases this may differ from the 'uuid',
        # for example when the spawn of a rescue instance takes place.
        if not instance_name:
            instance_name = instance['uuid']
        # Get the create vm config spec
        config_spec = vm_util.get_vm_create_spec(
                            client_factory, instance, instance_name,
                            data_store_name, vif_infos, os_type)

        def _execute_create_vm():
            """Create VM on ESX host."""
            LOG.debug(_("Creating VM on the ESX host"), instance=instance)
            # Create the VM on the ESX host
            vm_create_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "CreateVM_Task", dc_info.vmFolder,
                                    config=config_spec, pool=res_pool_ref)
            self._session._wait_for_task(vm_create_task)

            LOG.debug(_("Created VM on the ESX host"), instance=instance)

        _execute_create_vm()

        # In the case of a rescue disk the instance_name is not the same as
        # instance UUID. In this case the VM reference is accessed via the
        # instance name.
        if instance_name != instance['uuid']:
            vm_ref = vm_util.get_vm_ref_from_name(self._session,
                                                  instance_name)
        else:
            vm_ref = vm_util.get_vm_ref(self._session, instance)

        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        if CONF.flat_injected:
            self._set_machine_id(client_factory, instance, network_info)

        # Set the vnc configuration of the instance, vnc port starts from 5900
        if CONF.vnc_enabled:
            vnc_port = vm_util.get_vnc_port(self._session)
            self._set_vnc_config(client_factory, instance, vnc_port)

        def _create_virtual_disk(virtual_disk_path, file_size_in_kb):
            """Create a virtual disk of the size of flat vmdk file."""
            # Create a Virtual Disk of the size of the flat vmdk file. This is
            # done just to generate the meta-data file whose specifics
            # depend on the size of the disk, thin/thick provisioning and the
            # storage adapter type.
            # Here we assume thick provisioning and lsiLogic for the adapter
            # type
            LOG.debug(_("Creating Virtual Disk of size  "
                      "%(vmdk_file_size_in_kb)s KB and adapter type "
                      "%(adapter_type)s on the ESX host local store "
                      "%(data_store_name)s"),
                       {"vmdk_file_size_in_kb": file_size_in_kb,
                        "adapter_type": adapter_type,
                        "data_store_name": data_store_name},
                      instance=instance)
            vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                    file_size_in_kb, adapter_type,
                                    disk_type)
            vmdk_create_task = self._session._call_method(
                self._session._get_vim(),
                "CreateVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=virtual_disk_path,
                datacenter=dc_info.ref,
                spec=vmdk_create_spec)
            self._session._wait_for_task(vmdk_create_task)
            LOG.debug(_("Created Virtual Disk of size %(vmdk_file_size_in_kb)s"
                        " KB and type %(disk_type)s on "
                        "the ESX host local store %(data_store_name)s") %
                        {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                         "disk_type": disk_type,
                         "data_store_name": data_store_name},
                      instance=instance)

        def _fetch_image_on_datastore(upload_name):
            """Fetch image from Glance to datastore."""
            LOG.debug(_("Downloading image file data %(image_ref)s to the "
                        "data store %(data_store_name)s") %
                        {'image_ref': instance['image_ref'],
                         'data_store_name': data_store_name},
                      instance=instance)
            vmware_images.fetch_image(
                context,
                instance['image_ref'],
                instance,
                host=self._session._host_ip,
                data_center_name=dc_info.name,
                datastore_name=data_store_name,
                cookies=cookies,
                file_path=upload_name)
            LOG.debug(_("Downloaded image file data %(image_ref)s to "
                        "%(upload_name)s on the data store "
                        "%(data_store_name)s") %
                        {'image_ref': instance['image_ref'],
                         'upload_name': upload_name,
                         'data_store_name': data_store_name},
                      instance=instance)

        def _copy_virtual_disk(source, dest):
            """Copy a sparse virtual disk to a thin virtual disk."""
            # Copy a sparse virtual disk to a thin virtual disk. This is also
            # done to generate the meta-data file whose specifics
            # depend on the size of the disk, thin/thick provisioning and the
            # storage adapter type.
            LOG.debug(_("Copying Virtual Disk of size "
                      "%(vmdk_file_size_in_kb)s KB and adapter type "
                      "%(adapter_type)s on the ESX host local store "
                      "%(data_store_name)s to disk type %(disk_type)s") %
                       {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                        "adapter_type": adapter_type,
                        "data_store_name": data_store_name,
                        "disk_type": disk_type},
                      instance=instance)
            vmdk_copy_spec = self.get_copy_virtual_disk_spec(client_factory,
                                                             adapter_type,
                                                             disk_type)
            vmdk_copy_task = self._session._call_method(
                self._session._get_vim(),
                "CopyVirtualDisk_Task",
                service_content.virtualDiskManager,
                sourceName=source,
                sourceDatacenter=dc_info.ref,
                destName=dest,
                destSpec=vmdk_copy_spec)
            self._session._wait_for_task(vmdk_copy_task)
            LOG.debug(_("Copied Virtual Disk of size %(vmdk_file_size_in_kb)s"
                        " KB and type %(disk_type)s on "
                        "the ESX host local store %(data_store_name)s") %
                        {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                         "disk_type": disk_type,
                         "data_store_name": data_store_name},
                        instance=instance)

        if not ebs_root:
            # this logic allows for instances or images to decide
            # for themselves which strategy is best for them.

            linked_clone = VMwareVMOps.decide_linked_clone(
                image_linked_clone,
                CONF.vmware.use_linked_clone
            )
            upload_name = instance['image_ref']
            upload_folder = '%s/%s' % (self._base_folder, upload_name)

            # The vmdk meta-data file
            uploaded_file_name = "%s/%s.%s" % (upload_folder, upload_name,
                                               file_type)
            uploaded_file_path = ds_util.build_datastore_path(data_store_name,
                                                uploaded_file_name)

            session_vim = self._session._get_vim()
            cookies = session_vim.client.options.transport.cookiejar

            ds_browser = self._get_ds_browser(data_store_ref)
            upload_file_name = upload_name + ".%s" % file_type

            # Check if the timestamp file exists - if so then delete it. This
            # will ensure that the aging will not delete a cache image if it
            # is going to be used now.
            if CONF.remove_unused_base_images:
                ds_path = ds_util.build_datastore_path(data_store_name,
                                                       self._base_folder)
                path = self._imagecache.timestamp_folder_get(ds_path,
                                                             upload_name)
                # Lock to ensure that the spawn will not try and access a image
                # that is currently being deleted on the datastore.
                with lockutils.lock(path, lock_file_prefix='nova-vmware-ts',
                                    external=True):
                    self._imagecache.timestamp_cleanup(dc_info.ref, ds_browser,
                            data_store_ref, data_store_name, path)

            # Check if the image exists in the datastore cache. If not the
            # image will be uploaded and cached.
            if not (self._check_if_folder_file_exists(ds_browser,
                                        data_store_ref, data_store_name,
                                        upload_folder, upload_file_name)):
                # Upload will be done to the self._tmp_folder and then moved
                # to the self._base_folder
                tmp_upload_folder = '%s/%s' % (self._tmp_folder,
                                               uuidutils.generate_uuid())
                upload_folder = '%s/%s' % (tmp_upload_folder, upload_name)

                # Naming the VM files in correspondence with the VM instance
                # The flat vmdk file name
                flat_uploaded_vmdk_name = "%s/%s-flat.vmdk" % (
                                            upload_folder, upload_name)
                # The sparse vmdk file name for sparse disk image
                sparse_uploaded_vmdk_name = "%s/%s-sparse.vmdk" % (
                                            upload_folder, upload_name)

                flat_uploaded_vmdk_path = ds_util.build_datastore_path(
                                                    data_store_name,
                                                    flat_uploaded_vmdk_name)
                sparse_uploaded_vmdk_path = ds_util.build_datastore_path(
                                                    data_store_name,
                                                    sparse_uploaded_vmdk_name)

                upload_file_name = "%s/%s.%s" % (upload_folder, upload_name,
                                                 file_type)
                upload_path = ds_util.build_datastore_path(data_store_name,
                                                           upload_file_name)
                if not is_iso:
                    if disk_type != "sparse":
                        # Create a flat virtual disk and retain the metadata
                        # file. This will be done in the unique temporary
                        # directory.
                        ds_util.mkdir(self._session,
                                      ds_util.build_datastore_path(
                                          data_store_name, upload_folder),
                                      dc_info.ref)
                        _create_virtual_disk(upload_path,
                                             vmdk_file_size_in_kb)
                        self._delete_datastore_file(instance,
                                                    flat_uploaded_vmdk_path,
                                                    dc_info.ref)
                        upload_file_name = flat_uploaded_vmdk_name
                    else:
                        upload_file_name = sparse_uploaded_vmdk_name

                _fetch_image_on_datastore(upload_file_name)

                if not is_iso and disk_type == "sparse":
                    # Copy the sparse virtual disk to a thin virtual disk.
                    disk_type = "thin"
                    _copy_virtual_disk(sparse_uploaded_vmdk_path, upload_path)
                    self._delete_datastore_file(instance,
                                                sparse_uploaded_vmdk_path,
                                                dc_info.ref)
                base_folder = '%s/%s' % (self._base_folder, upload_name)
                dest_folder = ds_util.build_datastore_path(data_store_name,
                                                           base_folder)
                src_folder = ds_util.build_datastore_path(data_store_name,
                                                          upload_folder)
                try:
                    ds_util.file_move(self._session, dc_info.ref,
                                      src_folder, dest_folder)
                except error_util.FileAlreadyExistsException:
                    # File move has failed. This may be due to the fact that a
                    # process or thread has already completed the opertaion.
                    # In the event of a FileAlreadyExists we continue,
                    # all other exceptions will be raised.
                    LOG.debug(_("File %s already exists"), dest_folder)

                # Delete the temp upload folder
                self._delete_datastore_file(instance,
                        ds_util.build_datastore_path(data_store_name,
                                                     tmp_upload_folder),
                        dc_info.ref)
            else:
                # linked clone base disk exists
                if disk_type == "sparse":
                    disk_type = "thin"

            if is_iso:
                if root_gb_in_kb:
                    dest_vmdk_path = self._get_vmdk_path(data_store_name,
                            instance['uuid'], instance_name)
                    # Create the blank virtual disk for the VM
                    _create_virtual_disk(dest_vmdk_path, root_gb_in_kb)
                    root_vmdk_path = dest_vmdk_path
                else:
                    root_vmdk_path = None
            else:
                # Extend the disk size if necessary
                if not linked_clone:
                    # If we are not using linked_clone, copy the image from
                    # the cache into the instance directory.  If we are using
                    # linked clone it is references from the cache directory
                    dest_vmdk_path = self._get_vmdk_path(data_store_name,
                            instance_name, instance_name)
                    _copy_virtual_disk(uploaded_file_path, dest_vmdk_path)

                    root_vmdk_path = dest_vmdk_path
                    if root_gb_in_kb > vmdk_file_size_in_kb:
                        self._extend_virtual_disk(instance, root_gb_in_kb,
                                                  root_vmdk_path, dc_info.ref)
                else:
                    upload_folder = '%s/%s' % (self._base_folder, upload_name)
                    if root_gb:
                        root_vmdk_name = "%s/%s.%s.vmdk" % (upload_folder,
                                                            upload_name,
                                                            root_gb)
                    else:
                        root_vmdk_name = "%s/%s.vmdk" % (upload_folder,
                                                         upload_name)
                    root_vmdk_path = ds_util.build_datastore_path(
                            data_store_name, root_vmdk_name)

                    # Ensure only a single thread extends the image at once.
                    # We do this by taking a lock on the name of the extended
                    # image. This allows multiple threads to create resized
                    # copies simultaneously, as long as they are different
                    # sizes. Threads attempting to create the same resized copy
                    # will be serialized, with only the first actually creating
                    # the copy.
                    #
                    # Note that the object is in a per-nova cache directory,
                    # so inter-nova locking is not a concern. Consequently we
                    # can safely use simple thread locks.

                    with lockutils.lock(root_vmdk_path,
                                        lock_file_prefix='nova-vmware-image'):
                        if not self._check_if_folder_file_exists(
                                ds_browser,
                                data_store_ref, data_store_name,
                                upload_folder,
                                upload_name + ".%s.vmdk" % root_gb):
                            LOG.debug("Copying root disk of size %sGb",
                                      root_gb)

                            # Create a copy of the base image, ensuring we
                            # clean up on failure
                            try:
                                _copy_virtual_disk(uploaded_file_path,
                                                   root_vmdk_path)
                            except Exception as e:
                                with excutils.save_and_reraise_exception():
                                    LOG.error(_('Failed to copy cached '
                                                  'image %(source)s to '
                                                  '%(dest)s for resize: '
                                                  '%(error)s'),
                                              {'source': uploaded_file_path,
                                               'dest': root_vmdk_path,
                                               'error': e.message})
                                    try:
                                        ds_util.file_delete(self._session,
                                                            root_vmdk_path,
                                                            dc_info.ref)
                                    except error_util.FileNotFoundException:
                                        # File was never created: cleanup not
                                        # required
                                        pass

                            # Resize the copy to the appropriate size. No need
                            # for cleanup up here, as _extend_virtual_disk
                            # already does it
                            if root_gb_in_kb > vmdk_file_size_in_kb:
                                self._extend_virtual_disk(instance,
                                                          root_gb_in_kb,
                                                          root_vmdk_path,
                                                          dc_info.ref)

            # Attach the root disk to the VM.
            if root_vmdk_path:
                self._volumeops.attach_disk_to_vm(
                                    vm_ref, instance,
                                    adapter_type, disk_type, root_vmdk_path,
                                    root_gb_in_kb, linked_clone)

            if is_iso:
                self._attach_cdrom_to_vm(
                    vm_ref, instance,
                    data_store_ref,
                    uploaded_file_path)

            if configdrive.required_by(instance):
                uploaded_iso_path = self._create_config_drive(instance,
                                                              injected_files,
                                                              admin_password,
                                                              data_store_name,
                                                              dc_info.name,
                                                              instance['uuid'],
                                                              cookies)
                uploaded_iso_path = ds_util.build_datastore_path(
                    data_store_name,
                    uploaded_iso_path)
                self._attach_cdrom_to_vm(
                    vm_ref, instance,
                    data_store_ref,
                    uploaded_iso_path)

        else:
            # Attach the root disk to the VM.
            for root_disk in block_device_mapping:
                connection_info = root_disk['connection_info']
                self._volumeops.attach_root_volume(connection_info, instance,
                                                   self._default_root_device,
                                                   data_store_ref)

        def _power_on_vm():
            """Power on the VM."""
            LOG.debug(_("Powering on the VM instance"), instance=instance)
            # Power On the VM
            power_on_task = self._session._call_method(
                               self._session._get_vim(),
                               "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(power_on_task)
            LOG.debug(_("Powered on the VM instance"), instance=instance)

        if power_on:
            _power_on_vm()

    def _create_config_drive(self, instance, injected_files, admin_password,
                             data_store_name, dc_name, upload_folder, cookies):
        if CONF.config_drive_format != 'iso9660':
            reason = (_('Invalid config_drive_format "%s"') %
                      CONF.config_drive_format)
            raise exception.InstancePowerOnFailure(reason=reason)

        LOG.info(_('Using config drive for instance'), instance=instance)
        extra_md = {}
        if admin_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)
        try:
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                with utils.tempdir() as tmp_path:
                    tmp_file = os.path.join(tmp_path, 'configdrive.iso')
                    cdb.make_drive(tmp_file)
                    upload_iso_path = "%s/configdrive.iso" % (
                        upload_folder)
                    vmware_images.upload_iso_to_datastore(
                        tmp_file, instance,
                        host=self._session._host_ip,
                        data_center_name=dc_name,
                        datastore_name=data_store_name,
                        cookies=cookies,
                        file_path=upload_iso_path)
                    return upload_iso_path
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Creating config drive failed with error: %s'),
                          e, instance=instance)

    def _attach_cdrom_to_vm(self, vm_ref, instance,
                         datastore, file_path):
        """Attach cdrom to VM by reconfiguration."""
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        devices = self._session._call_method(vim_util,
                                    "get_dynamic_property", vm_ref,
                                    "VirtualMachine", "config.hardware.device")
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                              client_factory,
                                                              devices,
                                                              'ide')
        cdrom_attach_config_spec = vm_util.get_cdrom_attach_config_spec(
                                    client_factory, datastore, file_path,
                                    controller_key, unit_number)
        if controller_spec:
            cdrom_attach_config_spec.deviceChange.append(controller_spec)

        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to attach "
                    "cdrom %(file_path)s"),
                  {'instance_name': instance_name, 'file_path': file_path})
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=cdrom_attach_config_spec)
        self._session._wait_for_task(reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to attach "
                    "cdrom %(file_path)s"),
                  {'instance_name': instance_name, 'file_path': file_path})

    @staticmethod
    def decide_linked_clone(image_linked_clone, global_linked_clone):
        """Explicit decision logic: whether to use linked clone on a vmdk.

        This is *override* logic not boolean logic.

        1. let the image over-ride if set at all
        2. default to the global setting

        In math terms, I need to allow:
        glance image to override global config.

        That is g vs c. "g" for glance. "c" for Config.

        So, I need  g=True vs c=False to be True.
        And, I need g=False vs c=True to be False.
        And, I need g=None vs c=True to be True.

        Some images maybe independently best tuned for use_linked_clone=True
        saving datastorage space. Alternatively a whole OpenStack install may
        be tuned to performance use_linked_clone=False but a single image
        in this environment may be best configured to save storage space and
        set use_linked_clone=True only for itself.

        The point is: let each layer of control override the layer beneath it.

        rationale:
        For technical discussion on the clone strategies and their trade-offs
        see: https://www.vmware.com/support/ws5/doc/ws_clone_typeofclone.html

        :param image_linked_clone: boolean or string or None
        :param global_linked_clone: boolean or string or None
        :return: Boolean
        """

        value = None

        # Consider the values in order of override.
        if image_linked_clone is not None:
            value = image_linked_clone
        else:
            # this will never be not-set by this point.
            value = global_linked_clone

        return strutils.bool_from_string(value)

    def get_copy_virtual_disk_spec(self, client_factory, adapter_type,
                                   disk_type):
        return vm_util.get_copy_virtual_disk_spec(client_factory,
                                                  adapter_type,
                                                  disk_type)

    def _create_vm_snapshot(self, instance, vm_ref):
        LOG.debug(_("Creating Snapshot of the VM instance"), instance=instance)
        snapshot_task = self._session._call_method(
                    self._session._get_vim(),
                    "CreateSnapshot_Task", vm_ref,
                    name="%s-snapshot" % instance['uuid'],
                    description="Taking Snapshot of the VM",
                    memory=False,
                    quiesce=True)
        self._session._wait_for_task(snapshot_task)
        LOG.debug(_("Created Snapshot of the VM instance"), instance=instance)
        task_info = self._session._call_method(vim_util,
                                               "get_dynamic_property",
                                               snapshot_task, "Task", "info")
        snapshot = task_info.result
        return snapshot

    def _delete_vm_snapshot(self, instance, vm_ref, snapshot):
        LOG.debug(_("Deleting Snapshot of the VM instance"), instance=instance)
        delete_snapshot_task = self._session._call_method(
                    self._session._get_vim(),
                    "RemoveSnapshot_Task", snapshot,
                    removeChildren=False, consolidate=True)
        self._session._wait_for_task(delete_snapshot_task)
        LOG.debug(_("Deleted Snapshot of the VM instance"), instance=instance)

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance.

        Steps followed are:

        1. Get the name of the vmdk file which the VM points to right now.
           Can be a chain of snapshots, so we need to know the last in the
           chain.
        2. Create the snapshot. A new vmdk is created which the VM points to
           now. The earlier vmdk becomes read-only.
        3. Call CopyVirtualDisk which coalesces the disk chain to form a single
           vmdk, rather a .vmdk metadata file and a -flat.vmdk disk data file.
        4. Now upload the -flat.vmdk file to the image store.
        5. Delete the coalesced .vmdk and -flat.vmdk created.
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()

        def _get_vm_and_vmdk_attribs():
            # Get the vmdk file name that the VM is pointing to
            hw_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
            (vmdk_file_path_before_snapshot, adapter_type,
             disk_type) = vm_util.get_vmdk_path_and_adapter_type(
                                        hw_devices, uuid=instance['uuid'])
            if not vmdk_file_path_before_snapshot:
                LOG.debug("No root disk defined. Unable to snapshot.")
                raise error_util.NoRootDiskDefined()

            datastore_name = ds_util.split_datastore_path(
                                        vmdk_file_path_before_snapshot)[0]
            os_type = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "summary.config.guestId")
            return (vmdk_file_path_before_snapshot, adapter_type, disk_type,
                    datastore_name, os_type)

        (vmdk_file_path_before_snapshot, adapter_type, disk_type,
         datastore_name, os_type) = _get_vm_and_vmdk_attribs()

        snapshot = self._create_vm_snapshot(instance, vm_ref)
        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        def _check_if_tmp_folder_exists():
            # Copy the contents of the VM that were there just before the
            # snapshot was taken
            ds_ref_ret = self._session._call_method(
                vim_util, "get_dynamic_property", vm_ref, "VirtualMachine",
                "datastore")
            if ds_ref_ret is None:
                raise exception.DatastoreNotFound()
            ds_ref = ds_ref_ret.ManagedObjectReference[0]
            self.check_temp_folder(datastore_name, ds_ref)
            return ds_ref

        ds_ref = _check_if_tmp_folder_exists()

        # Generate a random vmdk file name to which the coalesced vmdk content
        # will be copied to. A random name is chosen so that we don't have
        # name clashes.
        random_name = uuidutils.generate_uuid()
        dest_vmdk_file_path = ds_util.build_datastore_path(datastore_name,
                   "%s/%s.vmdk" % (self._tmp_folder, random_name))
        dest_vmdk_data_file_path = ds_util.build_datastore_path(datastore_name,
                   "%s/%s-flat.vmdk" % (self._tmp_folder, random_name))
        dc_info = self.get_datacenter_ref_and_name(ds_ref)

        def _copy_vmdk_content():
            # Consolidate the snapshotted disk to a temporary vmdk.
            copy_spec = self.get_copy_virtual_disk_spec(client_factory,
                                                        adapter_type,
                                                        disk_type)
            LOG.debug(_('Copying snapshotted disk %s.'),
                      vmdk_file_path_before_snapshot,
                      instance=instance)
            copy_disk_task = self._session._call_method(
                self._session._get_vim(),
                "CopyVirtualDisk_Task",
                service_content.virtualDiskManager,
                sourceName=vmdk_file_path_before_snapshot,
                sourceDatacenter=dc_info.ref,
                destName=dest_vmdk_file_path,
                destDatacenter=dc_info.ref,
                destSpec=copy_spec,
                force=False)
            self._session._wait_for_task(copy_disk_task)
            LOG.debug(_('Copied snapshotted disk %s.'),
                      vmdk_file_path_before_snapshot,
                      instance=instance)

        _copy_vmdk_content()
        # Note(vui): handle snapshot cleanup on exceptions.
        self._delete_vm_snapshot(instance, vm_ref, snapshot)

        cookies = self._session._get_vim().client.options.transport.cookiejar

        def _upload_vmdk_to_image_repository():
            # Upload the contents of -flat.vmdk file which has the disk data.
            LOG.debug(_("Uploading image %s") % image_id,
                      instance=instance)
            vmware_images.upload_image(
                context,
                image_id,
                instance,
                os_type=os_type,
                disk_type="preallocated",
                adapter_type=adapter_type,
                image_version=1,
                host=self._session._host_ip,
                data_center_name=dc_info.name,
                datastore_name=datastore_name,
                cookies=cookies,
                file_path="%s/%s-flat.vmdk" % (self._tmp_folder, random_name))
            LOG.debug(_("Uploaded image %s") % image_id,
                      instance=instance)

        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)
        _upload_vmdk_to_image_repository()

        def _clean_temp_data():
            """Delete temporary vmdk files generated in image handling
            operations.
            """
            # The data file is the one occupying space, and likelier to see
            # deletion problems, so prioritize its deletion first. In the
            # unlikely event that its deletion fails, the small descriptor file
            # is retained too by design since it makes little sense to remove
            # it when the data disk it refers to still lingers.
            for f in dest_vmdk_data_file_path, dest_vmdk_file_path:
                self._delete_datastore_file(instance, f, dc_info.ref)

        _clean_temp_data()

    def _get_values_from_object_properties(self, props, query):
        while props:
            token = vm_util._get_token(props)
            for elem in props.objects:
                for prop in elem.propSet:
                    for key in query.keys():
                        if prop.name == key:
                            query[key] = prop.val
                            break
            if token:
                props = self._session._call_method(vim_util,
                                                   "continue_to_get_objects",
                                                   token)
            else:
                break

    def reboot(self, instance, network_info):
        """Reboot a VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        lst_properties = ["summary.guest.toolsStatus", "runtime.powerState",
                          "summary.guest.toolsRunningStatus"]
        props = self._session._call_method(vim_util, "get_object_properties",
                           None, vm_ref, "VirtualMachine",
                           lst_properties)
        query = {'runtime.powerState': None,
                 'summary.guest.toolsStatus': None,
                 'summary.guest.toolsRunningStatus': False}
        self._get_values_from_object_properties(props, query)
        pwr_state = query['runtime.powerState']
        tools_status = query['summary.guest.toolsStatus']
        tools_running_status = query['summary.guest.toolsRunningStatus']

        # Raise an exception if the VM is not powered On.
        if pwr_state not in ["poweredOn"]:
            reason = _("instance is not powered on")
            raise exception.InstanceRebootFailure(reason=reason)

        # If latest vmware tools are installed in the VM, and that the tools
        # are running, then only do a guest reboot. Otherwise do a hard reset.
        if (tools_status == "toolsOk" and
                tools_running_status == "guestToolsRunning"):
            LOG.debug(_("Rebooting guest OS of VM"), instance=instance)
            self._session._call_method(self._session._get_vim(), "RebootGuest",
                                       vm_ref)
            LOG.debug(_("Rebooted guest OS of VM"), instance=instance)
        else:
            LOG.debug(_("Doing hard reboot of VM"), instance=instance)
            reset_task = self._session._call_method(self._session._get_vim(),
                                                    "ResetVM_Task", vm_ref)
            self._session._wait_for_task(reset_task)
            LOG.debug(_("Did hard reboot of VM"), instance=instance)

    def _delete(self, instance, network_info):
        """Destroy a VM instance. Steps followed are:
        1. Power off the VM, if it is in poweredOn state.
        2. Destroy the VM.
        """
        try:
            vm_ref = vm_util.get_vm_ref(self._session, instance)
            self.power_off(instance)
            try:
                LOG.debug(_("Destroying the VM"), instance=instance)
                destroy_task = self._session._call_method(
                    self._session._get_vim(),
                    "Destroy_Task", vm_ref)
                self._session._wait_for_task(destroy_task)
                LOG.debug(_("Destroyed the VM"), instance=instance)
            except Exception as excep:
                LOG.warn(_("In vmwareapi:vmops:delete, got this exception"
                           " while destroying the VM: %s") % str(excep))
        except Exception as exc:
            LOG.exception(exc, instance=instance)

    def _destroy_instance(self, instance, network_info, destroy_disks=True,
                          instance_name=None):
        # Destroy a VM instance
        # Get the instance name. In some cases this may differ from the 'uuid',
        # for example when the spawn of a rescue instance takes place.
        if not instance_name:
            instance_name = instance['uuid']
        try:
            vm_ref = vm_util.get_vm_ref_from_name(self._session, instance_name)
            lst_properties = ["config.files.vmPathName", "runtime.powerState",
                              "datastore"]
            props = self._session._call_method(vim_util,
                        "get_object_properties",
                        None, vm_ref, "VirtualMachine", lst_properties)
            query = {'runtime.powerState': None,
                     'config.files.vmPathName': None,
                     'datastore': None}
            self._get_values_from_object_properties(props, query)
            pwr_state = query['runtime.powerState']
            vm_config_pathname = query['config.files.vmPathName']
            datastore_name = None
            if vm_config_pathname:
                _ds_path = ds_util.split_datastore_path(vm_config_pathname)
                datastore_name, vmx_file_path = _ds_path
            # Power off the VM if it is in PoweredOn state.
            if pwr_state == "poweredOn":
                LOG.debug(_("Powering off the VM"), instance=instance)
                poweroff_task = self._session._call_method(
                       self._session._get_vim(),
                       "PowerOffVM_Task", vm_ref)
                self._session._wait_for_task(poweroff_task)
                LOG.debug(_("Powered off the VM"), instance=instance)

            # Un-register the VM
            try:
                LOG.debug(_("Unregistering the VM"), instance=instance)
                self._session._call_method(self._session._get_vim(),
                                           "UnregisterVM", vm_ref)
                LOG.debug(_("Unregistered the VM"), instance=instance)
            except Exception as excep:
                LOG.warn(_("In vmwareapi:vmops:_destroy_instance, got this "
                           "exception while un-registering the VM: %s"),
                         excep)
            # Delete the folder holding the VM related content on
            # the datastore.
            if destroy_disks and datastore_name:
                try:
                    dir_ds_compliant_path = ds_util.build_datastore_path(
                                     datastore_name,
                                     os.path.dirname(vmx_file_path))
                    LOG.debug(_("Deleting contents of the VM from "
                                "datastore %(datastore_name)s") %
                               {'datastore_name': datastore_name},
                              instance=instance)
                    ds_ref_ret = query['datastore']
                    ds_ref = ds_ref_ret.ManagedObjectReference[0]
                    dc_info = self.get_datacenter_ref_and_name(ds_ref)
                    ds_util.file_delete(self._session,
                                        dir_ds_compliant_path,
                                        dc_info.ref)
                    LOG.debug(_("Deleted contents of the VM from "
                                "datastore %(datastore_name)s") %
                               {'datastore_name': datastore_name},
                              instance=instance)
                except Exception as excep:
                    LOG.warn(_("In vmwareapi:vmops:_destroy_instance, "
                                "got this exception while deleting "
                                "the VM contents from the disk: %s"),
                             excep)
        except Exception as exc:
            LOG.exception(exc, instance=instance)
        finally:
            vm_util.vm_ref_cache_delete(instance_name)

    def destroy(self, instance, network_info, destroy_disks=True):
        """Destroy a VM instance.

        Steps followed for each VM are:
        1. Power off, if it is in poweredOn state.
        2. Un-register.
        3. Delete the contents of the folder holding the VM related data.
        """
        # If there is a rescue VM then we need to destroy that one too.
        LOG.debug(_("Destroying instance"), instance=instance)
        if instance['vm_state'] == vm_states.RESCUED:
            LOG.debug(_("Rescue VM configured"), instance=instance)
            try:
                self.unrescue(instance, power_on=False)
                LOG.debug(_("Rescue VM destroyed"), instance=instance)
            except Exception:
                rescue_name = instance['uuid'] + self._rescue_suffix
                self._destroy_instance(instance, network_info,
                                       destroy_disks=destroy_disks,
                                       instance_name=rescue_name)
        self._destroy_instance(instance, network_info,
                               destroy_disks=destroy_disks)
        LOG.debug(_("Instance destroyed"), instance=instance)

    def pause(self, instance):
        msg = _("pause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def unpause(self, instance):
        msg = _("unpause not supported for vmwareapi")
        raise NotImplementedError(msg)

    def suspend(self, instance):
        """Suspend the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        # Only PoweredOn VMs can be suspended.
        if pwr_state == "poweredOn":
            LOG.debug(_("Suspending the VM"), instance=instance)
            suspend_task = self._session._call_method(self._session._get_vim(),
                    "SuspendVM_Task", vm_ref)
            self._session._wait_for_task(suspend_task)
            LOG.debug(_("Suspended the VM"), instance=instance)
        # Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            reason = _("instance is powered off and cannot be suspended.")
            raise exception.InstanceSuspendFailure(reason=reason)
        else:
            LOG.debug(_("VM was already in suspended state. So returning "
                      "without doing anything"), instance=instance)

    def resume(self, instance):
        """Resume the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.debug(_("Resuming the VM"), instance=instance)
            suspend_task = self._session._call_method(
                                        self._session._get_vim(),
                                       "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(suspend_task)
            LOG.debug(_("Resumed the VM"), instance=instance)
        else:
            reason = _("instance is not in a suspended state")
            raise exception.InstanceResumeFailure(reason=reason)

    def rescue(self, context, instance, network_info, image_meta):
        """Rescue the specified instance.

            - shutdown the instance VM.
            - spawn a rescue VM (the vm name-label will be instance-N-rescue).

        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        self.power_off(instance)
        r_instance = copy.deepcopy(instance)
        instance_name = r_instance['uuid'] + self._rescue_suffix
        self.spawn(context, r_instance, image_meta,
                   None, None, network_info,
                   instance_name=instance_name,
                   power_on=False)

        # Attach vmdk to the rescue VM
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
        (vmdk_path, adapter_type,
         disk_type) = vm_util.get_vmdk_path_and_adapter_type(
                hardware_devices, uuid=instance['uuid'])
        rescue_vm_ref = vm_util.get_vm_ref_from_name(self._session,
                                                     instance_name)
        self._volumeops.attach_disk_to_vm(
                                rescue_vm_ref, r_instance,
                                adapter_type, disk_type, vmdk_path)
        self._power_on(instance, vm_ref=rescue_vm_ref)

    def unrescue(self, instance, power_on=True):
        """Unrescue the specified instance."""
        # Get the original vmdk_path
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
        (vmdk_path, adapter_type,
         disk_type) = vm_util.get_vmdk_path_and_adapter_type(
                hardware_devices, uuid=instance['uuid'])

        r_instance = copy.deepcopy(instance)
        instance_name = r_instance['uuid'] + self._rescue_suffix
        # detach the original instance disk from the rescue disk
        vm_rescue_ref = vm_util.get_vm_ref_from_name(self._session,
                                                     instance_name)
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_rescue_ref,
                        "VirtualMachine", "config.hardware.device")
        device = vm_util.get_vmdk_volume_disk(hardware_devices, path=vmdk_path)
        self._power_off_vm_ref(vm_rescue_ref)
        self._volumeops.detach_disk_from_vm(vm_rescue_ref, r_instance, device)
        self._destroy_instance(r_instance, None, instance_name=instance_name)
        if power_on:
            self._power_on(instance)

    def _power_off_vm_ref(self, vm_ref):
        """Power off the specifed vm.

        :param vm_ref: a reference object to the VM.
        """
        poweroff_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "PowerOffVM_Task", vm_ref)
        self._session._wait_for_task(poweroff_task)

    def power_off(self, instance):
        """Power off the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        # Only PoweredOn VMs can be powered off.
        if pwr_state == "poweredOn":
            LOG.debug(_("Powering off the VM"), instance=instance)
            self._power_off_vm_ref(vm_ref)
            LOG.debug(_("Powered off the VM"), instance=instance)
        # Raise Exception if VM is suspended
        elif pwr_state == "suspended":
            reason = _("instance is suspended and cannot be powered off.")
            raise exception.InstancePowerOffFailure(reason=reason)
        else:
            LOG.debug(_("VM was already in powered off state. So returning "
                        "without doing anything"), instance=instance)

    def _power_on(self, instance, vm_ref=None):
        """Power on the specified instance."""
        if not vm_ref:
            vm_ref = vm_util.get_vm_ref(self._session, instance)

        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state == "poweredOn":
            LOG.debug(_("VM was already in powered on state. So returning "
                      "without doing anything"), instance=instance)
        # Only PoweredOff and Suspended VMs can be powered on.
        else:
            LOG.debug(_("Powering on the VM"), instance=instance)
            poweron_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(poweron_task)
            LOG.debug(_("Powered on the VM"), instance=instance)

    def power_on(self, context, instance, network_info, block_device_info):
        self._power_on(instance)

    def _get_orig_vm_name_label(self, instance):
        return instance['uuid'] + '-orig'

    def _update_instance_progress(self, context, instance, step, total_steps):
        """Update instance progress percent to reflect current step number
        """
        # Divide the action's workflow into discrete steps and "bump" the
        # instance's progress field as each step is completed.
        #
        # For a first cut this should be fine, however, for large VM images,
        # the clone disk step begins to dominate the equation. A
        # better approximation would use the percentage of the VM image that
        # has been streamed to the destination host.
        progress = round(float(step) / total_steps * 100)
        instance_uuid = instance['uuid']
        LOG.debug(_("Updating instance '%(instance_uuid)s' progress to"
                    " %(progress)d"),
                  {'instance_uuid': instance_uuid, 'progress': progress},
                  instance=instance)
        self._virtapi.instance_update(context, instance_uuid,
                                      {'progress': progress})

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor):
        """Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        # 0. Zero out the progress to begin
        self._update_instance_progress(context, instance,
                                       step=0,
                                       total_steps=RESIZE_TOTAL_STEPS)

        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Read the host_ref for the destination. If this is None then the
        # VC will decide on placement
        host_ref = self._get_host_ref_from_name(dest)

        # 1. Power off the instance
        self.power_off(instance)
        self._update_instance_progress(context, instance,
                                       step=1,
                                       total_steps=RESIZE_TOTAL_STEPS)

        # 2. Disassociate the linked vsphere VM from the instance
        vm_util.disassociate_vmref_from_instance(self._session, instance,
                                                 vm_ref,
                                                 suffix=self._migrate_suffix)
        self._update_instance_progress(context, instance,
                                       step=2,
                                       total_steps=RESIZE_TOTAL_STEPS)

        ds_ref = vm_util.get_datastore_ref_and_name(
                            self._session, self._cluster, host_ref,
                            datastore_regex=self._datastore_regex)[0]
        dc_info = self.get_datacenter_ref_and_name(ds_ref)
        # 3. Clone the VM for instance
        vm_util.clone_vmref_for_instance(self._session, instance, vm_ref,
                                         host_ref, ds_ref, dc_info.vmFolder)
        self._update_instance_progress(context, instance,
                                       step=3,
                                       total_steps=RESIZE_TOTAL_STEPS)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        # Destroy the original VM. The vm_ref needs to be searched using the
        # instance['uuid'] + self._migrate_suffix as the identifier. We will
        # not get the vm when searched using the instanceUuid but rather will
        # be found using the uuid buried in the extraConfig
        vm_ref = vm_util.search_vm_ref_by_identifier(self._session,
                                    instance['uuid'] + self._migrate_suffix)
        if vm_ref is None:
            LOG.debug(_("instance not present"), instance=instance)
            return

        try:
            LOG.debug(_("Destroying the VM"), instance=instance)
            destroy_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "Destroy_Task", vm_ref)
            self._session._wait_for_task(destroy_task)
            LOG.debug(_("Destroyed the VM"), instance=instance)
        except Exception as excep:
            LOG.warn(_("In vmwareapi:vmops:confirm_migration, got this "
                     "exception while destroying the VM: %s") % str(excep))

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info, power_on=True):
        """Finish reverting a resize."""
        vm_util.associate_vmref_for_instance(self._session, instance,
                                             suffix=self._migrate_suffix)
        if power_on:
            self._power_on(instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        if resize_instance:
            client_factory = self._session._get_vim().client.factory
            vm_ref = vm_util.get_vm_ref(self._session, instance)
            vm_resize_spec = vm_util.get_vm_resize_spec(client_factory,
                                                        instance)
            reconfig_task = self._session._call_method(
                                            self._session._get_vim(),
                                            "ReconfigVM_Task", vm_ref,
                                            spec=vm_resize_spec)
            self._session._wait_for_task(reconfig_task)

        # 4. Start VM
        if power_on:
            self._power_on(instance)
        self._update_instance_progress(context, instance,
                                       step=4,
                                       total_steps=RESIZE_TOTAL_STEPS)

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """Spawning live_migration operation for distributing high-load."""
        vm_ref = vm_util.get_vm_ref(self._session, instance_ref)

        host_ref = self._get_host_ref_from_name(dest)
        if host_ref is None:
            raise exception.HostNotFound(host=dest)

        LOG.debug(_("Migrating VM to host %s") % dest, instance=instance_ref)
        try:
            vm_migrate_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "MigrateVM_Task", vm_ref,
                                    host=host_ref,
                                    priority="defaultPriority")
            self._session._wait_for_task(vm_migrate_task)
        except Exception:
            with excutils.save_and_reraise_exception():
                recover_method(context, instance_ref, dest, block_migration)
        post_method(context, instance_ref, dest, block_migration)
        LOG.debug(_("Migrated VM to host %s") % dest, instance=instance_ref)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        ctxt = nova_context.get_admin_context()

        instances_info = dict(instance_count=len(instances),
                timeout=timeout)

        if instances_info["instance_count"] > 0:
            LOG.info(_("Found %(instance_count)d hung reboots "
                    "older than %(timeout)d seconds") % instances_info)

        for instance in instances:
            LOG.info(_("Automatically hard rebooting"), instance=instance)
            self.compute_api.reboot(ctxt, instance, "HARD")

    def get_info(self, instance):
        """Return data about the VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        lst_properties = ["summary.config.numCpu",
                    "summary.config.memorySizeMB",
                    "runtime.powerState"]
        vm_props = self._session._call_method(vim_util,
                    "get_object_properties", None, vm_ref, "VirtualMachine",
                    lst_properties)
        query = {'summary.config.numCpu': 0,
                 'summary.config.memorySizeMB': 0,
                 'runtime.powerState': None}
        self._get_values_from_object_properties(vm_props, query)
        max_mem = int(query['summary.config.memorySizeMB']) * 1024
        return {'state': VMWARE_POWER_STATES[query['runtime.powerState']],
                'max_mem': max_mem,
                'mem': max_mem,
                'num_cpu': int(query['summary.config.numCpu']),
                'cpu_time': 0}

    def _get_diagnostic_from_object_properties(self, props, wanted_props):
        diagnostics = {}
        while props:
            for elem in props.objects:
                for prop in elem.propSet:
                    if prop.name in wanted_props:
                        prop_dict = vim.object_to_dict(prop.val, list_depth=1)
                        diagnostics.update(prop_dict)
            token = vm_util._get_token(props)
            if not token:
                break

            props = self._session._call_method(vim_util,
                                               "continue_to_get_objects",
                                               token)
        return diagnostics

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        lst_properties = ["summary.config",
                          "summary.quickStats",
                          "summary.runtime"]
        vm_props = self._session._call_method(vim_util,
                    "get_object_properties", None, vm_ref, "VirtualMachine",
                    lst_properties)
        data = self._get_diagnostic_from_object_properties(vm_props,
                                                           set(lst_properties))
        # Add a namespace to all of the diagnostsics
        return dict([('vmware:' + k, v) for k, v in data.items()])

    def get_vnc_console(self, instance):
        """Return connection info for a vnc console."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        opt_value = self._session._call_method(vim_util,
                               'get_dynamic_property',
                               vm_ref, 'VirtualMachine',
                               vm_util.VNC_CONFIG_KEY)
        if opt_value:
            port = int(opt_value.value)
        else:
            raise exception.ConsoleTypeUnavailable(console_type='vnc')

        return {'host': CONF.vmware.host_ip,
                'port': port,
                'internal_access_path': None}

    def get_vnc_console_vcenter(self, instance):
        """Return connection info for a vnc console using vCenter logic."""

        # vCenter does not run virtual machines and does not run
        # a VNC proxy. Instead, you need to tell OpenStack to talk
        # directly to the ESX host running the VM you are attempting
        # to connect to via VNC.

        vnc_console = self.get_vnc_console(instance)
        host_name = vm_util.get_host_name_for_vm(
                        self._session,
                        instance)
        vnc_console['host'] = host_name

        # NOTE: VM can move hosts in some situations. Debug for admins.
        LOG.debug(_("VM %(uuid)s is currently on host %(host_name)s"),
                {'uuid': instance['name'], 'host_name': host_name})

        return vnc_console

    @staticmethod
    def _get_machine_id_str(network_info):
        machine_id_str = ''
        for vif in network_info:
            # TODO(vish): add support for dns2
            # TODO(sateesh): add support for injection of ipv6 configuration
            network = vif['network']
            ip_v4 = netmask_v4 = gateway_v4 = broadcast_v4 = dns = None
            subnets_v4 = [s for s in network['subnets'] if s['version'] == 4]
            if len(subnets_v4) > 0:
                if len(subnets_v4[0]['ips']) > 0:
                    ip_v4 = subnets_v4[0]['ips'][0]
                if len(subnets_v4[0]['dns']) > 0:
                    dns = subnets_v4[0]['dns'][0]['address']

                netmask_v4 = str(subnets_v4[0].as_netaddr().netmask)
                gateway_v4 = subnets_v4[0]['gateway']['address']
                broadcast_v4 = str(subnets_v4[0].as_netaddr().broadcast)

            interface_str = ";".join([vif['address'],
                                      ip_v4 and ip_v4['address'] or '',
                                      netmask_v4 or '',
                                      gateway_v4 or '',
                                      broadcast_v4 or '',
                                      dns or ''])
            machine_id_str = machine_id_str + interface_str + '#'
        return machine_id_str

    def _set_machine_id(self, client_factory, instance, network_info):
        """Set the machine id of the VM for guest tools to pick up
        and reconfigure the network interfaces.
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        machine_id_change_spec = vm_util.get_machine_id_change_spec(
                                 client_factory,
                                 self._get_machine_id_str(network_info))

        LOG.debug(_("Reconfiguring VM instance to set the machine id"),
                  instance=instance)
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=machine_id_change_spec)
        self._session._wait_for_task(reconfig_task)
        LOG.debug(_("Reconfigured VM instance to set the machine id"),
                  instance=instance)

    def _set_vnc_config(self, client_factory, instance, port):
        """Set the vnc configuration of the VM."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        vnc_config_spec = vm_util.get_vnc_config_spec(
                                      client_factory, port)

        LOG.debug(_("Reconfiguring VM instance to enable vnc on "
                  "port - %(port)s") % {'port': port},
                  instance=instance)
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=vnc_config_spec)
        self._session._wait_for_task(reconfig_task)
        LOG.debug(_("Reconfigured VM instance to enable vnc on "
                  "port - %(port)s") % {'port': port},
                  instance=instance)

    def _get_ds_browser(self, ds_ref):
        ds_browser = self._datastore_browser_mapping.get(ds_ref.value)
        if not ds_browser:
            ds_browser = self._session._call_method(
                vim_util, "get_dynamic_property", ds_ref, "Datastore",
                "browser")
            self._datastore_browser_mapping[ds_ref.value] = ds_browser
        return ds_browser

    def get_datacenter_ref_and_name(self, ds_ref):
        """Get the datacenter name and the reference."""
        map = self._datastore_dc_mapping.get(ds_ref.value)
        if not map:
            dc_obj = self._session._call_method(vim_util, "get_objects",
                    "Datacenter", ["name"])
            vm_util._cancel_retrieve_if_necessary(self._session, dc_obj)
            map = DcInfo(ref=dc_obj.objects[0].obj,
                         name=dc_obj.objects[0].propSet[0].val,
                         vmFolder=self._get_vmfolder_ref())
            self._datastore_dc_mapping[ds_ref.value] = map
        return map

    def _get_host_ref_from_name(self, host_name):
        """Get reference to the host with the name specified."""
        host_objs = self._session._call_method(vim_util, "get_objects",
                    "HostSystem", ["name"])
        vm_util._cancel_retrieve_if_necessary(self._session, host_objs)
        for host in host_objs:
            if hasattr(host, 'propSet'):
                if host.propSet[0].val == host_name:
                    return host.obj
        return None

    def _get_vmfolder_ref(self):
        """Get the Vm folder ref from the datacenter."""
        dc_objs = self._session._call_method(vim_util, "get_objects",
                                             "Datacenter", ["vmFolder"])
        vm_util._cancel_retrieve_if_necessary(self._session, dc_objs)
        # There is only one default datacenter in a standalone ESX host
        vm_folder_ref = dc_objs.objects[0].propSet[0].val
        return vm_folder_ref

    def _create_folder_if_missing(self, ds_name, ds_ref, folder):
        """Create a folder if it does not exist.

        Currently there are two folder that are required on the datastore
         - base folder - the folder to store cached images
         - temp folder - the folder used for snapshot management and
                         image uploading
        This method is aimed to be used for the management of those
        folders to ensure that they are created if they are missing.
        The ds_util method mkdir will be used to check if the folder
        exists. If this throws and exception 'FileAlreadyExistsException'
        then the folder already exists on the datastore.
        """
        path = ds_util.build_datastore_path(ds_name, folder)
        dc_info = self.get_datacenter_ref_and_name(ds_ref)
        try:
            ds_util.mkdir(self._session, path, dc_info.ref)
            LOG.debug(_("Folder %s created."), path)
        except error_util.FileAlreadyExistsException:
            # NOTE(hartsocks): if the folder already exists, that
            # just means the folder was prepped by another process.
            pass

    def check_cache_folder(self, ds_name, ds_ref):
        """Check that the cache folder exists."""
        self._create_folder_if_missing(ds_name, ds_ref, self._base_folder)

    def check_temp_folder(self, ds_name, ds_ref):
        """Check that the temp folder exists."""
        self._create_folder_if_missing(ds_name, ds_ref, self._tmp_folder)

    def _check_if_folder_file_exists(self, ds_browser, ds_ref, ds_name,
                                     folder_name, file_name):
        # Ensure that the cache folder exists
        self.check_cache_folder(ds_name, ds_ref)
        # Check if the file exists or not.
        folder_path = ds_util.build_datastore_path(ds_name, folder_name)
        file_exists = ds_util.file_exists(self._session, ds_browser,
                                          folder_path, file_name)
        return file_exists

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        client_factory = self._session._get_vim().client.factory
        self._set_machine_id(client_factory, instance, network_info)

    def manage_image_cache(self, context, instances):
        if not CONF.remove_unused_base_images:
            LOG.debug(_("Image aging disabled. Aging will not be done."))
            return

        datastores = vm_util.get_available_datastores(self._session,
                                                      self._cluster,
                                                      self._datastore_regex)
        datastores_info = []
        for ds in datastores:
            ds_info = self.get_datacenter_ref_and_name(ds['ref'])
            datastores_info.append((ds, ds_info))
        self._imagecache.update(context, instances, datastores_info)

    def _get_valid_vms_from_retrieve_result(self, retrieve_result):
        """Returns list of valid vms from RetrieveResult object."""
        lst_vm_names = []

        while retrieve_result:
            token = vm_util._get_token(retrieve_result)
            for vm in retrieve_result.objects:
                vm_name = None
                conn_state = None
                for prop in vm.propSet:
                    if prop.name == "name":
                        vm_name = prop.val
                    elif prop.name == "runtime.connectionState":
                        conn_state = prop.val
                # Ignoring the orphaned or inaccessible VMs
                if conn_state not in ["orphaned", "inaccessible"]:
                    lst_vm_names.append(vm_name)
            if token:
                retrieve_result = self._session._call_method(vim_util,
                                                 "continue_to_get_objects",
                                                 token)
            else:
                break
        return lst_vm_names


class VMwareVCVMOps(VMwareVMOps):
    """Management class for VM-related tasks.

    Contains specializations to account for differences in vSphere API behavior
    when invoked on Virtual Center instead of ESX host.
    """

    def get_copy_virtual_disk_spec(self, client_factory, adapter_type,
                                   disk_type):
        LOG.debug(_("Will copy while retaining adapter type "
                    "%(adapter_type)s and disk type %(disk_type)s") %
                    {"disk_type": disk_type,
                     "adapter_type": adapter_type})
        # Passing of the destination copy spec is not supported when
        # VirtualDiskManager.CopyVirtualDisk is called on VC. The behavior of a
        # spec-less copy is to consolidate to the target disk while keeping its
        # disk and adapter type unchanged.

    def _update_datacenter_cache_from_objects(self, dcs):
        """Updates the datastore/datacenter cache."""

        while dcs:
            token = vm_util._get_token(dcs)
            for dco in dcs.objects:
                dc_ref = dco.obj
                ds_refs = []
                prop_dict = vm_util.propset_dict(dco.propSet)
                name = prop_dict.get('name')
                vmFolder = prop_dict.get('vmFolder')
                datastore_refs = prop_dict.get('datastore')
                if datastore_refs:
                    datastore_refs = datastore_refs.ManagedObjectReference
                    for ds in datastore_refs:
                        ds_refs.append(ds.value)
                else:
                    LOG.debug("Datacenter %s doesn't have any datastore "
                              "associated with it, ignoring it", name)
                for ds_ref in ds_refs:
                    self._datastore_dc_mapping[ds_ref] = DcInfo(ref=dc_ref,
                            name=name, vmFolder=vmFolder)

            if token:
                dcs = self._session._call_method(vim_util,
                                                 "continue_to_get_objects",
                                                 token)
            else:
                break

    def get_datacenter_ref_and_name(self, ds_ref):
        """Get the datacenter name and the reference."""
        dc_info = self._datastore_dc_mapping.get(ds_ref.value)
        if not dc_info:
            dcs = self._session._call_method(vim_util, "get_objects",
                    "Datacenter", ["name", "datastore", "vmFolder"])
            self._update_datacenter_cache_from_objects(dcs)
            dc_info = self._datastore_dc_mapping.get(ds_ref.value)
        return dc_info

    def list_instances(self):
        """Lists the VM instances that are registered with vCenter cluster."""
        properties = ['name', 'runtime.connectionState']
        LOG.debug(_("Getting list of instances from cluster %s"),
                  self._cluster)
        vms = []
        root_res_pool = self._session._call_method(
            vim_util, "get_dynamic_property", self._cluster,
            'ClusterComputeResource', 'resourcePool')
        if root_res_pool:
            vms = self._session._call_method(
                vim_util, 'get_inner_objects', root_res_pool, 'vm',
                'VirtualMachine', properties)
        lst_vm_names = self._get_valid_vms_from_retrieve_result(vms)

        LOG.debug(_("Got total of %s instances") % str(len(lst_vm_names)))
        return lst_vm_names
