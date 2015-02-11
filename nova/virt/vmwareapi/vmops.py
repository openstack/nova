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
import os
import time

import decorator
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
from oslo_vmware import exceptions as vexc

from nova.api.metadata import base as instance_metadata
from nova import compute
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova.console import type as ctype
from nova import context as nova_context
from nova import exception
from nova.i18n import _, _LE, _LI, _LW
from nova import objects
from nova.openstack.common import log as logging
from nova.openstack.common import uuidutils
from nova import utils
from nova.virt import configdrive
from nova.virt import diagnostics
from nova.virt import driver
from nova.virt import hardware
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import imagecache
from nova.virt.vmwareapi import images
from nova.virt.vmwareapi import vif as vmwarevif
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

vmops_opts = [
    cfg.StrOpt('cache_prefix',
               help='The prefix for Where cached images are stored. This is '
                    'NOT the full path - just a folder prefix. '
                    'This should only be used when a datastore cache should '
                    'be shared between compute nodes. Note: this should only '
                    'be used when the compute nodes have a shared file '
                    'system.'),
    ]

CONF = cfg.CONF
CONF.register_opts(vmops_opts, 'vmware')

CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('remove_unused_base_images', 'nova.virt.imagecache')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('my_ip', 'nova.netconf')

LOG = logging.getLogger(__name__)

VMWARE_POWER_STATES = {
                   'poweredOff': power_state.SHUTDOWN,
                    'poweredOn': power_state.RUNNING,
                    'suspended': power_state.SUSPENDED}

RESIZE_TOTAL_STEPS = 4

DcInfo = collections.namedtuple('DcInfo',
                                ['ref', 'name', 'vmFolder'])


class VirtualMachineInstanceConfigInfo(object):
    """Parameters needed to create and configure a new instance."""

    def __init__(self, instance, instance_name, image_info,
                 datastore, dc_info, image_cache):

        # Some methods called during spawn take the instance parameter purely
        # for logging purposes.
        # TODO(vui) Clean them up, so we no longer need to keep this variable
        self.instance = instance

        # Get the instance name. In some cases this may differ from the 'uuid',
        # for example when the spawn of a rescue instance takes place.
        self.instance_name = instance_name or instance.uuid

        self.ii = image_info
        self.root_gb = instance.root_gb
        self.datastore = datastore
        self.dc_info = dc_info
        self._image_cache = image_cache

    @property
    def cache_image_folder(self):
        if self.ii.image_id is None:
            return
        return self._image_cache.get_image_cache_folder(
                   self.datastore, self.ii.image_id)

    @property
    def cache_image_path(self):
        if self.ii.image_id is None:
            return
        cached_image_file_name = "%s.%s" % (self.ii.image_id,
                                            self.ii.file_type)
        return self.cache_image_folder.join(cached_image_file_name)


# Note(vui): See https://bugs.launchpad.net/nova/+bug/1363349
# for cases where mocking time.sleep() can have unintended effects on code
# not under test. For now, unblock the affected test cases by providing
# a wrapper function to work around needing to mock time.sleep()
def _time_sleep_wrapper(delay):
    time.sleep(delay)


@decorator.decorator
def retry_if_task_in_progress(f, *args, **kwargs):
    retries = max(CONF.vmware.api_retry_count, 1)
    delay = 1
    for attempt in range(1, retries + 1):
        if attempt != 1:
            _time_sleep_wrapper(delay)
            delay = min(2 * delay, 60)
        try:
            f(*args, **kwargs)
            return
        except vexc.TaskInProgress:
            pass


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
        self._root_resource_pool = vm_util.get_res_pool_ref(self._session,
                                                            self._cluster)
        self._datastore_regex = datastore_regex
        self._base_folder = self._get_base_folder()
        self._tmp_folder = 'vmware_temp'
        self._rescue_suffix = '-rescue'
        self._migrate_suffix = '-orig'
        self._datastore_dc_mapping = {}
        self._datastore_browser_mapping = {}
        self._imagecache = imagecache.ImageCacheManager(self._session,
                                                        self._base_folder)

    def _get_base_folder(self):
        # Enable more than one compute node to run on the same host
        if CONF.vmware.cache_prefix:
            base_folder = '%s%s' % (CONF.vmware.cache_prefix,
                                    CONF.image_cache_subdirectory_name)
        # Ensure that the base folder is unique per compute node
        elif CONF.remove_unused_base_images:
            base_folder = '%s%s' % (CONF.my_ip,
                                    CONF.image_cache_subdirectory_name)
        else:
            # Aging disable ensures backward compatibility
            base_folder = CONF.image_cache_subdirectory_name
        return base_folder

    def _extend_virtual_disk(self, instance, requested_size, name, dc_ref):
        service_content = self._session.vim.service_content
        LOG.debug("Extending root virtual disk to %s", requested_size)
        vmdk_extend_task = self._session._call_method(
                self._session.vim,
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
                LOG.error(_LE('Extending virtual disk failed with error: %s'),
                          e, instance=instance)
                # Clean up files created during the extend operation
                files = [name.replace(".vmdk", "-flat.vmdk"), name]
                for file in files:
                    ds_path = ds_util.DatastorePath.parse(file)
                    self._delete_datastore_file(ds_path, dc_ref)

        LOG.debug("Extended root virtual disk")

    def _delete_datastore_file(self, datastore_path, dc_ref):
        try:
            ds_util.file_delete(self._session, datastore_path, dc_ref)
        except (vexc.CannotDeleteFileException,
                vexc.FileFaultException,
                vexc.FileLockedException,
                vexc.FileNotFoundException):
            LOG.debug("Unable to delete %(ds)s. There may be more than "
                      "one process or thread trying to delete the file",
                      {'ds': datastore_path},
                      exc_info=True)

    def _extend_if_required(self, dc_info, image_info, instance,
                            root_vmdk_path):
        """Increase the size of the root vmdk if necessary."""
        if instance.root_gb * units.Gi > image_info.file_size:
            size_in_kb = instance.root_gb * units.Mi
            self._extend_virtual_disk(instance, size_in_kb,
                                      root_vmdk_path, dc_info.ref)

    def _configure_config_drive(self, instance, vm_ref, dc_info, datastore,
                                injected_files, admin_password):
        session_vim = self._session.vim
        cookies = session_vim.client.options.transport.cookiejar

        uploaded_iso_path = self._create_config_drive(instance,
                                                      injected_files,
                                                      admin_password,
                                                      datastore.name,
                                                      dc_info.name,
                                                      instance.uuid,
                                                      cookies)
        uploaded_iso_path = datastore.build_path(uploaded_iso_path)
        self._attach_cdrom_to_vm(
            vm_ref, instance,
            datastore.ref,
            str(uploaded_iso_path))

    def build_virtual_machine(self, instance, instance_name, image_info,
                              dc_info, datastore, network_info, extra_specs):
        vif_infos = vmwarevif.get_vif_info(self._session,
                                           self._cluster,
                                           utils.is_neutron(),
                                           image_info.vif_model,
                                           network_info)

        if extra_specs.storage_policy:
            profile_spec = vm_util.get_storage_profile_spec(
                self._session, extra_specs.storage_policy)
        else:
            profile_spec = None
        # Get the create vm config spec
        client_factory = self._session.vim.client.factory
        config_spec = vm_util.get_vm_create_spec(client_factory,
                                                 instance,
                                                 instance_name,
                                                 datastore.name,
                                                 vif_infos,
                                                 extra_specs,
                                                 image_info.os_type,
                                                 profile_spec=profile_spec)
        # Create the VM
        vm_ref = vm_util.create_vm(self._session, instance, dc_info.vmFolder,
                                   config_spec, self._root_resource_pool)
        return vm_ref

    def _get_extra_specs(self, flavor):
        extra_specs = vm_util.ExtraSpecs()
        for (key, type) in (('cpu_limit', int),
                            ('cpu_reservation', int),
                            ('cpu_shares_level', str),
                            ('cpu_shares_share', int)):
            value = flavor.extra_specs.get('quota:' + key)
            if value:
                setattr(extra_specs.cpu_limits, key, type(value))
        hw_version = flavor.extra_specs.get('vmware:hw_version')
        extra_specs.hw_version = hw_version
        if CONF.vmware.pbm_enabled:
            storage_policy = flavor.extra_specs.get('vmware:storage_policy',
                    CONF.vmware.pbm_default_policy)
            extra_specs.storage_policy = storage_policy
        return extra_specs

    def _fetch_image_as_file(self, context, vi, image_ds_loc):
        """Download image as an individual file to host via HTTP PUT."""
        session = self._session
        session_vim = session.vim
        cookies = session_vim.client.options.transport.cookiejar

        LOG.debug("Downloading image file data %(image_id)s to "
                  "%(file_path)s on the data store "
                  "%(datastore_name)s",
                  {'image_id': vi.ii.image_id,
                   'file_path': image_ds_loc,
                   'datastore_name': vi.datastore.name},
                  instance=vi.instance)

        images.fetch_image(
            context,
            vi.instance,
            session._host,
            session._port,
            vi.dc_info.name,
            vi.datastore.name,
            image_ds_loc.rel_path,
            cookies=cookies)

    def _fetch_image_as_vapp(self, context, vi, image_ds_loc):
        """Download stream optimized image to host as a vApp."""

        # The directory of the imported disk is the unique name
        # of the VM use to import it with.
        vm_name = image_ds_loc.parent.basename

        LOG.debug("Downloading stream optimized image %(image_id)s to "
                  "%(file_path)s on the data store "
                  "%(datastore_name)s as vApp",
                  {'image_id': vi.ii.image_id,
                   'file_path': image_ds_loc,
                   'datastore_name': vi.datastore.name},
                  instance=vi.instance)

        images.fetch_image_stream_optimized(
            context,
            vi.instance,
            self._session,
            vm_name,
            vi.datastore.name,
            vi.dc_info.vmFolder,
            self._root_resource_pool)

    def _fetch_image_as_ova(self, context, vi, image_ds_loc):
        """Download root disk of an OVA image as streamOptimized."""

        # The directory of the imported disk is the unique name
        # of the VM use to import it with.
        vm_name = image_ds_loc.parent.basename

        images.fetch_image_ova(context,
                               vi.instance,
                               self._session,
                               vm_name,
                               vi.datastore.name,
                               vi.dc_info.vmFolder,
                               self._root_resource_pool)

    def _prepare_sparse_image(self, vi):
        tmp_dir_loc = vi.datastore.build_path(
                self._tmp_folder, uuidutils.generate_uuid())
        tmp_image_ds_loc = tmp_dir_loc.join(
                vi.ii.image_id, "tmp-sparse.vmdk")
        return tmp_dir_loc, tmp_image_ds_loc

    def _prepare_flat_image(self, vi):
        tmp_dir_loc = vi.datastore.build_path(
                self._tmp_folder, uuidutils.generate_uuid())
        tmp_image_ds_loc = tmp_dir_loc.join(
                vi.ii.image_id, vi.cache_image_path.basename)
        ds_util.mkdir(self._session, tmp_image_ds_loc.parent, vi.dc_info.ref)
        vm_util.create_virtual_disk(
                self._session, vi.dc_info.ref,
                vi.ii.adapter_type,
                vi.ii.disk_type,
                str(tmp_image_ds_loc),
                vi.ii.file_size_in_kb)
        flat_vmdk_name = vi.cache_image_path.basename.replace('.vmdk',
                                                              '-flat.vmdk')
        flat_vmdk_ds_loc = tmp_dir_loc.join(vi.ii.image_id, flat_vmdk_name)
        self._delete_datastore_file(str(flat_vmdk_ds_loc), vi.dc_info.ref)
        return tmp_dir_loc, flat_vmdk_ds_loc

    def _prepare_stream_optimized_image(self, vi):
        vm_name = "%s_%s" % (constants.IMAGE_VM_PREFIX,
                             uuidutils.generate_uuid())
        tmp_dir_loc = vi.datastore.build_path(vm_name)
        tmp_image_ds_loc = tmp_dir_loc.join("%s.vmdk" % tmp_dir_loc.basename)
        return tmp_dir_loc, tmp_image_ds_loc

    def _prepare_iso_image(self, vi):
        tmp_dir_loc = vi.datastore.build_path(
                self._tmp_folder, uuidutils.generate_uuid())
        tmp_image_ds_loc = tmp_dir_loc.join(
                vi.ii.image_id, vi.cache_image_path.basename)
        return tmp_dir_loc, tmp_image_ds_loc

    def _move_to_cache(self, dc_ref, src_folder_ds_path, dst_folder_ds_path):
        try:
            ds_util.file_move(self._session, dc_ref,
                              src_folder_ds_path, dst_folder_ds_path)
        except vexc.FileAlreadyExistsException:
            # Folder move has failed. This may be due to the fact that a
            # process or thread has already completed the operation.
            # Since image caching is synchronized, this can only happen
            # due to action external to the process.
            # In the event of a FileAlreadyExists we continue,
            # all other exceptions will be raised.
            LOG.warning(_LW("Destination %s already exists! Concurrent moves "
                            "can lead to unexpected results."),
                        dst_folder_ds_path)

    def _cache_sparse_image(self, vi, tmp_image_ds_loc):
        tmp_dir_loc = tmp_image_ds_loc.parent.parent
        converted_image_ds_loc = tmp_dir_loc.join(
                vi.ii.image_id, vi.cache_image_path.basename)
        # converts fetched image to preallocated disk
        vm_util.copy_virtual_disk(
                self._session,
                vi.dc_info.ref,
                str(tmp_image_ds_loc),
                str(converted_image_ds_loc))

        self._delete_datastore_file(str(tmp_image_ds_loc), vi.dc_info.ref)

        self._move_to_cache(vi.dc_info.ref,
                            tmp_image_ds_loc.parent,
                            vi.cache_image_folder)

    def _cache_flat_image(self, vi, tmp_image_ds_loc):
        self._move_to_cache(vi.dc_info.ref,
                            tmp_image_ds_loc.parent,
                            vi.cache_image_folder)

    def _cache_stream_optimized_image(self, vi, tmp_image_ds_loc):
        dst_path = vi.cache_image_folder.join("%s.vmdk" % vi.ii.image_id)
        ds_util.mkdir(self._session, vi.cache_image_folder, vi.dc_info.ref)
        try:
            ds_util.disk_move(self._session, vi.dc_info.ref,
                              tmp_image_ds_loc, dst_path)
        except vexc.FileAlreadyExistsException:
            pass

    def _cache_iso_image(self, vi, tmp_image_ds_loc):
        self._move_to_cache(vi.dc_info.ref,
                            tmp_image_ds_loc.parent,
                            vi.cache_image_folder)

    def _get_vm_config_info(self, instance, image_info, instance_name=None,
                            storage_policy=None):
        """Captures all relevant information from the spawn parameters."""

        if (instance.root_gb != 0 and
                image_info.file_size > instance.root_gb * units.Gi):
            reason = _("Image disk size greater than requested disk size")
            raise exception.InstanceUnacceptable(instance_id=instance.uuid,
                                                 reason=reason)
        allowed_ds_types = ds_util.get_allowed_datastore_types(
            image_info.disk_type)
        datastore = ds_util.get_datastore(self._session,
                                          self._cluster,
                                          self._datastore_regex,
                                          storage_policy,
                                          allowed_ds_types)
        dc_info = self.get_datacenter_ref_and_name(datastore.ref)

        return VirtualMachineInstanceConfigInfo(instance,
                                                instance_name,
                                                image_info,
                                                datastore,
                                                dc_info,
                                                self._imagecache)

    def _get_image_callbacks(self, vi):
        disk_type = vi.ii.disk_type

        if vi.ii.is_ova:
            image_fetch = self._fetch_image_as_ova
        elif disk_type == constants.DISK_TYPE_STREAM_OPTIMIZED:
            image_fetch = self._fetch_image_as_vapp
        else:
            image_fetch = self._fetch_image_as_file

        if vi.ii.is_iso:
            image_prepare = self._prepare_iso_image
            image_cache = self._cache_iso_image
        elif disk_type == constants.DISK_TYPE_SPARSE:
            image_prepare = self._prepare_sparse_image
            image_cache = self._cache_sparse_image
        elif disk_type == constants.DISK_TYPE_STREAM_OPTIMIZED:
            image_prepare = self._prepare_stream_optimized_image
            image_cache = self._cache_stream_optimized_image
        elif disk_type in constants.SUPPORTED_FLAT_VARIANTS:
            image_prepare = self._prepare_flat_image
            image_cache = self._cache_flat_image
        else:
            reason = _("disk type '%s' not supported") % disk_type
            raise exception.InvalidDiskInfo(reason=reason)
        return image_prepare, image_fetch, image_cache

    def _fetch_image_if_missing(self, context, vi):
        image_prepare, image_fetch, image_cache = self._get_image_callbacks(vi)
        LOG.debug("Processing image %s", vi.ii.image_id)

        with lockutils.lock(str(vi.cache_image_path),
                            lock_file_prefix='nova-vmware-fetch_image'):
            self.check_cache_folder(vi.datastore.name, vi.datastore.ref)
            ds_browser = self._get_ds_browser(vi.datastore.ref)
            if not ds_util.file_exists(self._session, ds_browser,
                                       vi.cache_image_folder,
                                       vi.cache_image_path.basename):
                LOG.debug("Preparing fetch location")
                tmp_dir_loc, tmp_image_ds_loc = image_prepare(vi)
                LOG.debug("Fetch image to %s", tmp_image_ds_loc)
                image_fetch(context, vi, tmp_image_ds_loc)
                LOG.debug("Caching image")
                image_cache(vi, tmp_image_ds_loc)
                LOG.debug("Cleaning up location %s", str(tmp_dir_loc))
                self._delete_datastore_file(str(tmp_dir_loc), vi.dc_info.ref)

    def _create_and_attach_ephemeral_disk(self, instance, vm_ref, vi, size,
                                          adapter_type, filename):
        path = str(ds_util.DatastorePath(vi.datastore.name, instance.uuid,
                                         filename))
        disk_type = constants.DISK_TYPE_THIN
        vm_util.create_virtual_disk(
                self._session, vi.dc_info.ref,
                adapter_type,
                disk_type,
                path,
                size)

        self._volumeops.attach_disk_to_vm(
                vm_ref, vi.instance,
                adapter_type, disk_type,
                path, size, False)

    def _create_ephemeral(self, bdi, instance, vm_ref, vi):
        ephemerals = None
        if bdi is not None:
            ephemerals = driver.block_device_info_get_ephemerals(bdi)
            for idx, eph in enumerate(ephemerals):
                size = eph['size'] * units.Mi
                adapter_type = eph.get('disk_bus', vi.ii.adapter_type)
                filename = vm_util.get_ephemeral_name(idx)
                self._create_and_attach_ephemeral_disk(instance, vm_ref, vi,
                                                       size, adapter_type,
                                                       filename)
        # There may be block devices defined but no ephemerals. In this case
        # we need to allocate a ephemeral disk if required
        if not ephemerals and instance.ephemeral_gb:
            size = instance.ephemeral_gb * units.Mi
            filename = vm_util.get_ephemeral_name(0)
            self._create_and_attach_ephemeral_disk(instance, vm_ref, vi,
                                                   size, vi.ii.adapter_type,
                                                   filename)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info=None,
              instance_name=None, power_on=True,
              flavor=None):

        client_factory = self._session.vim.client.factory
        image_info = images.VMwareImage.from_image(instance.image_ref,
                                                   image_meta)
        # Read flavors for extra_specs
        if flavor is None:
            flavor = objects.Flavor.get_by_id(
                nova_context.get_admin_context(read_deleted='yes'),
                instance.instance_type_id)

        extra_specs = self._get_extra_specs(flavor)

        vi = self._get_vm_config_info(instance, image_info, instance_name,
                                      extra_specs.storage_policy)

        # Creates the virtual machine. The virtual machine reference returned
        # is unique within Virtual Center.
        vm_ref = self.build_virtual_machine(instance,
                                            vi.instance_name,
                                            image_info,
                                            vi.dc_info,
                                            vi.datastore,
                                            network_info,
                                            extra_specs)

        # Cache the vm_ref. This saves a remote call to the VC. This uses the
        # instance_name. This covers all use cases including rescue and resize.
        vm_util.vm_ref_cache_update(vi.instance_name, vm_ref)

        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        if CONF.flat_injected:
            self._set_machine_id(client_factory, instance, network_info,
                                vm_ref=vm_ref)

        # Set the vnc configuration of the instance, vnc port starts from 5900
        if CONF.vnc_enabled:
            self._get_and_set_vnc_config(client_factory, instance, vm_ref)

        block_device_mapping = []
        if block_device_info is not None:
            block_device_mapping = driver.block_device_info_get_mapping(
                block_device_info)

        # NOTE(mdbooth): the logic here is that we ignore the image if there
        # are block device mappings. This behaviour is incorrect, and a bug in
        # the driver.  We should be able to accept an image and block device
        # mappings.
        if len(block_device_mapping) > 0:
            msg = "Block device information present: %s" % block_device_info
            # NOTE(mriedem): block_device_info can contain an auth_password
            # so we have to scrub the message before logging it.
            LOG.debug(strutils.mask_password(msg), instance=instance)

            for root_disk in block_device_mapping:
                connection_info = root_disk['connection_info']
                # TODO(hartsocks): instance is unnecessary, remove it
                # we still use instance in many locations for no other purpose
                # than logging, can we simplify this?
                self._volumeops.attach_root_volume(connection_info, instance,
                                                   vi.datastore.ref)
        else:
            self._imagecache.enlist_image(
                    image_info.image_id, vi.datastore, vi.dc_info.ref)
            self._fetch_image_if_missing(context, vi)

            if image_info.is_iso:
                self._use_iso_image(vm_ref, vi)
            elif image_info.linked_clone:
                self._use_disk_image_as_linked_clone(vm_ref, vi)
            else:
                self._use_disk_image_as_full_clone(vm_ref, vi)

        # Create ephemeral disks
        self._create_ephemeral(block_device_info, instance, vm_ref, vi)

        if configdrive.required_by(instance):
            self._configure_config_drive(
                    instance, vm_ref, vi.dc_info, vi.datastore,
                    injected_files, admin_password)

        if power_on:
            vm_util.power_on_instance(self._session, instance, vm_ref=vm_ref)

    def _create_config_drive(self, instance, injected_files, admin_password,
                             data_store_name, dc_name, upload_folder, cookies):
        if CONF.config_drive_format != 'iso9660':
            reason = (_('Invalid config_drive_format "%s"') %
                      CONF.config_drive_format)
            raise exception.InstancePowerOnFailure(reason=reason)

        LOG.info(_LI('Using config drive for instance'), instance=instance)
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
                    images.upload_iso_to_datastore(
                        tmp_file, instance,
                        host=self._session._host,
                        port=self._session._port,
                        data_center_name=dc_name,
                        datastore_name=data_store_name,
                        cookies=cookies,
                        file_path=upload_iso_path)
                    return upload_iso_path
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Creating config drive failed with error: %s'),
                          e, instance=instance)

    def _attach_cdrom_to_vm(self, vm_ref, instance,
                            datastore, file_path):
        """Attach cdrom to VM by reconfiguration."""
        client_factory = self._session.vim.client.factory
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

        LOG.debug("Reconfiguring VM instance to attach cdrom %s",
                  file_path, instance=instance)
        vm_util.reconfigure_vm(self._session, vm_ref, cdrom_attach_config_spec)
        LOG.debug("Reconfigured VM instance to attach cdrom %s",
                  file_path, instance=instance)

    def _create_vm_snapshot(self, instance, vm_ref):
        LOG.debug("Creating Snapshot of the VM instance", instance=instance)
        snapshot_task = self._session._call_method(
                    self._session.vim,
                    "CreateSnapshot_Task", vm_ref,
                    name="%s-snapshot" % instance.uuid,
                    description="Taking Snapshot of the VM",
                    memory=False,
                    quiesce=True)
        self._session._wait_for_task(snapshot_task)
        LOG.debug("Created Snapshot of the VM instance", instance=instance)
        task_info = self._session._call_method(vim_util,
                                               "get_dynamic_property",
                                               snapshot_task, "Task", "info")
        snapshot = task_info.result
        return snapshot

    @retry_if_task_in_progress
    def _delete_vm_snapshot(self, instance, vm_ref, snapshot):
        LOG.debug("Deleting Snapshot of the VM instance", instance=instance)
        delete_snapshot_task = self._session._call_method(
                    self._session.vim,
                    "RemoveSnapshot_Task", snapshot,
                    removeChildren=False, consolidate=True)
        self._session._wait_for_task(delete_snapshot_task)
        LOG.debug("Deleted Snapshot of the VM instance", instance=instance)

    def _create_linked_clone_from_snapshot(self, instance,
                                           vm_ref, snapshot_ref, dc_info):
        """Create linked clone VM to be deployed to same ds as source VM
        """
        client_factory = self._session.vim.client.factory
        rel_spec = vm_util.relocate_vm_spec(
                client_factory,
                datastore=None,
                host=None,
                disk_move_type="createNewChildDiskBacking")
        clone_spec = vm_util.clone_vm_spec(client_factory, rel_spec,
                power_on=False, snapshot=snapshot_ref, template=True)
        vm_name = "%s_%s" % (constants.SNAPSHOT_VM_PREFIX,
                             uuidutils.generate_uuid())

        LOG.debug("Creating linked-clone VM from snapshot", instance=instance)
        vm_clone_task = self._session._call_method(
                                self._session.vim,
                                "CloneVM_Task",
                                vm_ref,
                                folder=dc_info.vmFolder,
                                name=vm_name,
                                spec=clone_spec)
        self._session._wait_for_task(vm_clone_task)
        LOG.info(_LI("Created linked-clone VM from snapshot"),
                 instance=instance)
        task_info = self._session._call_method(vim_util,
                                               "get_dynamic_property",
                                               vm_clone_task, "Task", "info")
        return task_info.result

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance.

        Steps followed are:

        1. Get the name of the vmdk file which the VM points to right now.
           Can be a chain of snapshots, so we need to know the last in the
           chain.
        2. Create the snapshot. A new vmdk is created which the VM points to
           now. The earlier vmdk becomes read-only.
        3. Creates a linked clone VM from the snapshot
        4. Exports the disk in the link clone VM as a streamOptimized disk.
        5. Delete the linked clone VM
        6. Deletes the snapshot in original instance.
        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        def _get_vm_and_vmdk_attribs():
            # Get the vmdk info that the VM is pointing to
            vmdk = vm_util.get_vmdk_info(self._session, vm_ref,
                                              instance.uuid)
            if not vmdk.path:
                LOG.debug("No root disk defined. Unable to snapshot.")
                raise error_util.NoRootDiskDefined()

            lst_properties = ["datastore", "summary.config.guestId"]
            props = self._session._call_method(vim_util,
                                               "get_object_properties",
                                               None, vm_ref, "VirtualMachine",
                                               lst_properties)
            query = vm_util.get_values_from_object_properties(self._session,
                                                              props)
            os_type = query['summary.config.guestId']
            datastores = query['datastore']
            return (vmdk, datastores, os_type)

        vmdk, datastores, os_type = _get_vm_and_vmdk_attribs()
        ds_ref = datastores.ManagedObjectReference[0]
        dc_info = self.get_datacenter_ref_and_name(ds_ref)

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        # TODO(vui): convert to creating plain vm clone and uploading from it
        # instead of using live vm snapshot.
        snapshot_ref = self._create_vm_snapshot(instance, vm_ref)

        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)
        snapshot_vm_ref = None

        try:
            # Create a temporary VM (linked clone from snapshot), then export
            # the VM's root disk to glance via HttpNfc API
            snapshot_vm_ref = self._create_linked_clone_from_snapshot(
                instance, vm_ref, snapshot_ref, dc_info)
            images.upload_image_stream_optimized(
                context, image_id, instance, self._session, vm=snapshot_vm_ref,
                vmdk_size=vmdk.capacity_in_bytes)
        finally:
            if snapshot_vm_ref:
                vm_util.destroy_vm(self._session, instance, snapshot_vm_ref)
            # Deleting the snapshot after destroying the temporary VM created
            # based on it allows the instance vm's disks to be consolidated.
            # TODO(vui) Add handling for when vmdk volume is attached.
            self._delete_vm_snapshot(instance, vm_ref, snapshot_ref)

    def reboot(self, instance, network_info):
        """Reboot a VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        lst_properties = ["summary.guest.toolsStatus", "runtime.powerState",
                          "summary.guest.toolsRunningStatus"]
        props = self._session._call_method(vim_util, "get_object_properties",
                           None, vm_ref, "VirtualMachine",
                           lst_properties)
        query = vm_util.get_values_from_object_properties(self._session, props)
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
            LOG.debug("Rebooting guest OS of VM", instance=instance)
            self._session._call_method(self._session.vim, "RebootGuest",
                                       vm_ref)
            LOG.debug("Rebooted guest OS of VM", instance=instance)
        else:
            LOG.debug("Doing hard reboot of VM", instance=instance)
            reset_task = self._session._call_method(self._session.vim,
                                                    "ResetVM_Task", vm_ref)
            self._session._wait_for_task(reset_task)
            LOG.debug("Did hard reboot of VM", instance=instance)

    def _destroy_instance(self, instance, destroy_disks=True,
                          instance_name=None):
        # Destroy a VM instance
        # Get the instance name. In some cases this may differ from the 'uuid',
        # for example when the spawn of a rescue instance takes place.
        if instance_name is None:
            instance_name = instance.uuid
        try:
            vm_ref = vm_util.get_vm_ref_from_name(self._session, instance_name)
            if vm_ref is None:
                LOG.warning(_LW('Instance does not exist on backend'),
                            instance=instance)
                return
            lst_properties = ["config.files.vmPathName", "runtime.powerState",
                              "datastore"]
            props = self._session._call_method(vim_util,
                        "get_object_properties",
                        None, vm_ref, "VirtualMachine", lst_properties)
            query = vm_util.get_values_from_object_properties(
                    self._session, props)
            pwr_state = query['runtime.powerState']

            vm_config_pathname = query.get('config.files.vmPathName')
            vm_ds_path = None
            if vm_config_pathname is not None:
                vm_ds_path = ds_util.DatastorePath.parse(
                        vm_config_pathname)

            # Power off the VM if it is in PoweredOn state.
            if pwr_state == "poweredOn":
                vm_util.power_off_instance(self._session, instance, vm_ref)

            # Un-register the VM
            try:
                LOG.debug("Unregistering the VM", instance=instance)
                self._session._call_method(self._session.vim,
                                           "UnregisterVM", vm_ref)
                LOG.debug("Unregistered the VM", instance=instance)
            except Exception as excep:
                LOG.warning(_LW("In vmwareapi:vmops:_destroy_instance, got "
                                "this exception while un-registering the VM: "
                                "%s"), excep)
            # Delete the folder holding the VM related content on
            # the datastore.
            if destroy_disks and vm_ds_path:
                try:
                    dir_ds_compliant_path = vm_ds_path.parent
                    LOG.debug("Deleting contents of the VM from "
                              "datastore %(datastore_name)s",
                              {'datastore_name': vm_ds_path.datastore},
                              instance=instance)
                    ds_ref_ret = query['datastore']
                    ds_ref = ds_ref_ret.ManagedObjectReference[0]
                    dc_info = self.get_datacenter_ref_and_name(ds_ref)
                    ds_util.file_delete(self._session,
                                        dir_ds_compliant_path,
                                        dc_info.ref)
                    LOG.debug("Deleted contents of the VM from "
                              "datastore %(datastore_name)s",
                              {'datastore_name': vm_ds_path.datastore},
                              instance=instance)
                except Exception:
                    LOG.warning(_LW("In vmwareapi:vmops:_destroy_instance, "
                                    "exception while deleting the VM contents "
                                    "from the disk"), exc_info=True)
        except Exception as exc:
            LOG.exception(exc, instance=instance)
        finally:
            vm_util.vm_ref_cache_delete(instance_name)

    def destroy(self, instance, destroy_disks=True):
        """Destroy a VM instance.

        Steps followed for each VM are:
        1. Power off, if it is in poweredOn state.
        2. Un-register.
        3. Delete the contents of the folder holding the VM related data.
        """
        # If there is a rescue VM then we need to destroy that one too.
        LOG.debug("Destroying instance", instance=instance)
        if instance['vm_state'] == vm_states.RESCUED:
            LOG.debug("Rescue VM configured", instance=instance)
            try:
                self.unrescue(instance, power_on=False)
                LOG.debug("Rescue VM destroyed", instance=instance)
            except Exception:
                rescue_name = instance.uuid + self._rescue_suffix
                self._destroy_instance(instance,
                                       destroy_disks=destroy_disks,
                                       instance_name=rescue_name)
        # NOTE(arnaud): Destroy uuid-orig and uuid VMs iff it is not
        # triggered by the revert resize api call. This prevents
        # the uuid-orig VM to be deleted to be able to associate it later.
        if instance.task_state != task_states.RESIZE_REVERTING:
            # When a VM deletion is triggered in the middle of VM resize and
            # before the state is set to RESIZED, the uuid-orig VM needs
            # to be deleted. This will avoid VM leaks.
            # The method _destroy_instance will check that the vmref
            # exists before attempting the deletion.
            resize_orig_vmname = instance.uuid + self._migrate_suffix
            vm_orig_ref = vm_util.get_vm_ref_from_name(self._session,
                                                       resize_orig_vmname)
            if vm_orig_ref:
                self._destroy_instance(instance,
                                       destroy_disks=destroy_disks,
                                       instance_name=resize_orig_vmname)
        self._destroy_instance(instance, destroy_disks=destroy_disks)
        LOG.debug("Instance destroyed", instance=instance)

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
            LOG.debug("Suspending the VM", instance=instance)
            suspend_task = self._session._call_method(self._session.vim,
                    "SuspendVM_Task", vm_ref)
            self._session._wait_for_task(suspend_task)
            LOG.debug("Suspended the VM", instance=instance)
        # Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            reason = _("instance is powered off and cannot be suspended.")
            raise exception.InstanceSuspendFailure(reason=reason)
        else:
            LOG.debug("VM was already in suspended state. So returning "
                      "without doing anything", instance=instance)

    def resume(self, instance):
        """Resume the specified instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.debug("Resuming the VM", instance=instance)
            suspend_task = self._session._call_method(
                                        self._session.vim,
                                       "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(suspend_task)
            LOG.debug("Resumed the VM", instance=instance)
        else:
            reason = _("instance is not in a suspended state")
            raise exception.InstanceResumeFailure(reason=reason)

    def rescue(self, context, instance, network_info, image_meta):
        """Rescue the specified instance.

            - shutdown the instance VM.
            - spawn a rescue VM (the vm name-label will be instance-N-rescue).

        """
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        vm_util.power_off_instance(self._session, instance, vm_ref)
        instance_name = instance.uuid + self._rescue_suffix
        self.spawn(context, instance, image_meta,
                   None, None, network_info,
                   instance_name=instance_name,
                   power_on=False)

        # Attach vmdk to the rescue VM
        vmdk = vm_util.get_vmdk_info(self._session, vm_ref, instance.uuid)
        rescue_vm_ref = vm_util.get_vm_ref_from_name(self._session,
                                                     instance_name)
        self._volumeops.attach_disk_to_vm(rescue_vm_ref,
                                          instance,
                                          vmdk.adapter_type,
                                          vmdk.disk_type,
                                          vmdk.path)
        vm_util.power_on_instance(self._session, instance,
                                  vm_ref=rescue_vm_ref)

    def unrescue(self, instance, power_on=True):
        """Unrescue the specified instance."""
        # Get the original vmdk_path
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        vmdk = vm_util.get_vmdk_info(self._session, vm_ref, instance.uuid)
        instance_name = instance.uuid + self._rescue_suffix
        # detach the original instance disk from the rescue disk
        vm_rescue_ref = vm_util.get_vm_ref_from_name(self._session,
                                                     instance_name)
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_rescue_ref,
                        "VirtualMachine", "config.hardware.device")
        device = vm_util.get_vmdk_volume_disk(hardware_devices, path=vmdk.path)
        vm_util.power_off_instance(self._session, instance, vm_rescue_ref)
        self._volumeops.detach_disk_from_vm(vm_rescue_ref, instance, device)
        self._destroy_instance(instance, instance_name=instance_name)
        if power_on:
            vm_util.power_on_instance(self._session, instance, vm_ref=vm_ref)

    def power_off(self, instance):
        """Power off the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        vm_util.power_off_instance(self._session, instance)

    def power_on(self, instance):
        vm_util.power_on_instance(self._session, instance)

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
        instance_uuid = instance.uuid
        LOG.debug("Updating instance '%(instance_uuid)s' progress to"
                  " %(progress)d",
                  {'instance_uuid': instance_uuid, 'progress': progress},
                  instance=instance)
        instance.progress = progress
        instance.save()

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor):
        """Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        # Checks if the migration needs a disk resize down.
        if flavor['root_gb'] < instance['root_gb']:
            reason = _("Unable to shrink disk.")
            raise exception.InstanceFaultRollback(
                exception.ResizeError(reason=reason))

        # 0. Zero out the progress to begin
        self._update_instance_progress(context, instance,
                                       step=0,
                                       total_steps=RESIZE_TOTAL_STEPS)

        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Read the host_ref for the destination. If this is None then the
        # VC will decide on placement
        host_ref = self._get_host_ref_from_name(dest)

        # 1. Power off the instance
        vm_util.power_off_instance(self._session, instance, vm_ref)
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

        ds_ref = ds_util.get_datastore(
                            self._session, self._cluster,
                            datastore_regex=self._datastore_regex).ref
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
        # instance.uuid + self._migrate_suffix as the identifier. We will
        # not get the vm when searched using the instanceUuid but rather will
        # be found using the uuid buried in the extraConfig
        vm_ref = vm_util.search_vm_ref_by_identifier(self._session,
                                    instance.uuid + self._migrate_suffix)
        if vm_ref is None:
            LOG.debug("instance not present", instance=instance)
            return

        try:
            LOG.debug("Destroying the VM", instance=instance)
            destroy_task = self._session._call_method(
                                        self._session.vim,
                                        "Destroy_Task", vm_ref)
            self._session._wait_for_task(destroy_task)
            LOG.debug("Destroyed the VM", instance=instance)
        except Exception as excep:
            LOG.warning(_LW("In vmwareapi:vmops:confirm_migration, got this "
                            "exception while destroying the VM: %s"), excep)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info, power_on=True):
        """Finish reverting a resize."""
        vm_util.associate_vmref_for_instance(self._session, instance,
                                             suffix=self._migrate_suffix)
        if power_on:
            vm_util.power_on_instance(self._session, instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)

        if resize_instance:
            client_factory = self._session.vim.client.factory
            vm_resize_spec = vm_util.get_vm_resize_spec(client_factory,
                                                        instance.vcpus,
                                                        instance.memory_mb)
            vm_util.reconfigure_vm(self._session, vm_ref, vm_resize_spec)

            # Resize the disk (if larger)
            old_root_gb = instance.system_metadata['old_instance_type_root_gb']
            if instance['root_gb'] > int(old_root_gb):
                root_disk_in_kb = instance['root_gb'] * units.Mi
                vmdk_info = vm_util.get_vmdk_info(self._session, vm_ref,
                                                  instance.uuid)
                vmdk_path = vmdk_info.path
                data_store_ref = ds_util.get_datastore(self._session,
                    self._cluster, datastore_regex=self._datastore_regex).ref
                dc_info = self.get_datacenter_ref_and_name(data_store_ref)
                self._extend_virtual_disk(instance, root_disk_in_kb, vmdk_path,
                                          dc_info.ref)

            # TODO(ericwb): add extend for ephemeral disk

        # 4. Start VM
        if power_on:
            vm_util.power_on_instance(self._session, instance, vm_ref=vm_ref)

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

        LOG.debug("Migrating VM to host %s", dest, instance=instance_ref)
        try:
            vm_migrate_task = self._session._call_method(
                                    self._session.vim,
                                    "MigrateVM_Task", vm_ref,
                                    host=host_ref,
                                    priority="defaultPriority")
            self._session._wait_for_task(vm_migrate_task)
        except Exception:
            with excutils.save_and_reraise_exception():
                recover_method(context, instance_ref, dest, block_migration)
        post_method(context, instance_ref, dest, block_migration)
        LOG.debug("Migrated VM to host %s", dest, instance=instance_ref)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        ctxt = nova_context.get_admin_context()

        instances_info = dict(instance_count=len(instances),
                timeout=timeout)

        if instances_info["instance_count"] > 0:
            LOG.info(_LI("Found %(instance_count)d hung reboots "
                         "older than %(timeout)d seconds"), instances_info)

        for instance in instances:
            LOG.info(_LI("Automatically hard rebooting"), instance=instance)
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
        query = vm_util.get_values_from_object_properties(
                self._session, vm_props)
        max_mem = int(query.get('summary.config.memorySizeMB', 0)) * 1024
        num_cpu = int(query.get('summary.config.numCpu', 0))
        return hardware.InstanceInfo(
            state=VMWARE_POWER_STATES[query['runtime.powerState']],
            max_mem_kb=max_mem,
            mem_kb=max_mem,
            num_cpu=num_cpu)

    def _get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        lst_properties = ["summary.config",
                          "summary.quickStats",
                          "summary.runtime"]
        vm_props = self._session._call_method(vim_util,
                    "get_object_properties", None, vm_ref, "VirtualMachine",
                    lst_properties)
        query = vm_util.get_values_from_object_properties(self._session,
                                                          vm_props)
        data = {}
        # All of values received are objects. Convert them to dictionaries
        for value in query.values():
            prop_dict = vim_util.object_to_dict(value, list_depth=1)
            data.update(prop_dict)
        return data

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        data = self._get_diagnostics(instance)
        # Add a namespace to all of the diagnostsics
        return {'vmware:' + k: v for k, v in data.items()}

    def get_instance_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        data = self._get_diagnostics(instance)
        state = data.get('powerState')
        if state:
            state = power_state.STATE_MAP[VMWARE_POWER_STATES[state]]
        uptime = data.get('uptimeSeconds', 0)
        config_drive = configdrive.required_by(instance)
        diags = diagnostics.Diagnostics(state=state,
                                        driver='vmwareapi',
                                        config_drive=config_drive,
                                        hypervisor_os='esxi',
                                        uptime=uptime)
        diags.memory_details.maximum = data.get('memorySizeMB', 0)
        diags.memory_details.used = data.get('guestMemoryUsage', 0)
        # TODO(garyk): add in cpu, nic and disk stats
        return diags

    def _get_vnc_console_connection(self, instance):
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

        return {'port': port,
                'internal_access_path': None}

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

    def _set_machine_id(self, client_factory, instance, network_info,
                        vm_ref=None):
        """Set the machine id of the VM for guest tools to pick up
        and reconfigure the network interfaces.
        """
        if vm_ref is None:
            vm_ref = vm_util.get_vm_ref(self._session, instance)

        machine_id_change_spec = vm_util.get_machine_id_change_spec(
                                 client_factory,
                                 self._get_machine_id_str(network_info))

        LOG.debug("Reconfiguring VM instance to set the machine id",
                  instance=instance)
        vm_util.reconfigure_vm(self._session, vm_ref, machine_id_change_spec)
        LOG.debug("Reconfigured VM instance to set the machine id",
                  instance=instance)

    @utils.synchronized('vmware.get_and_set_vnc_port')
    def _get_and_set_vnc_config(self, client_factory, instance, vm_ref):
        """Set the vnc configuration of the VM."""
        port = vm_util.get_vnc_port(self._session)
        vnc_config_spec = vm_util.get_vnc_config_spec(
                                      client_factory, port)

        LOG.debug("Reconfiguring VM instance to enable vnc on "
                  "port - %(port)s", {'port': port},
                  instance=instance)
        vm_util.reconfigure_vm(self._session, vm_ref, vnc_config_spec)
        LOG.debug("Reconfigured VM instance to enable vnc on "
                  "port - %(port)s", {'port': port},
                  instance=instance)

    def _get_ds_browser(self, ds_ref):
        ds_browser = self._datastore_browser_mapping.get(ds_ref.value)
        if not ds_browser:
            ds_browser = self._session._call_method(
                vim_util, "get_dynamic_property", ds_ref, "Datastore",
                "browser")
            self._datastore_browser_mapping[ds_ref.value] = ds_browser
        return ds_browser

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
        path = ds_util.DatastorePath(ds_name, folder)
        dc_info = self.get_datacenter_ref_and_name(ds_ref)
        try:
            ds_util.mkdir(self._session, path, dc_info.ref)
            LOG.debug("Folder %s created.", path)
        except vexc.FileAlreadyExistsException:
            # NOTE(hartsocks): if the folder already exists, that
            # just means the folder was prepped by another process.
            pass

    def check_cache_folder(self, ds_name, ds_ref):
        """Check that the cache folder exists."""
        self._create_folder_if_missing(ds_name, ds_ref, self._base_folder)

    def check_temp_folder(self, ds_name, ds_ref):
        """Check that the temp folder exists."""
        self._create_folder_if_missing(ds_name, ds_ref, self._tmp_folder)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        client_factory = self._session.vim.client.factory
        self._set_machine_id(client_factory, instance, network_info)

    def manage_image_cache(self, context, instances):
        if not CONF.remove_unused_base_images:
            LOG.debug("Image aging disabled. Aging will not be done.")
            return

        datastores = ds_util.get_available_datastores(self._session,
                                                      self._cluster,
                                                      self._datastore_regex)
        datastores_info = []
        for ds in datastores:
            dc_info = self.get_datacenter_ref_and_name(ds.ref)
            datastores_info.append((ds, dc_info))
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
                if (conn_state not in ["orphaned", "inaccessible"] and
                    uuidutils.is_uuid_like(vm_name)):
                    lst_vm_names.append(vm_name)
            if token:
                retrieve_result = self._session._call_method(vim_util,
                                                 "continue_to_get_objects",
                                                 token)
            else:
                break
        return lst_vm_names

    def instance_exists(self, instance):
        try:
            vm_util.get_vm_ref(self._session, instance)
            return True
        except exception.InstanceNotFound:
            return False

    def attach_interface(self, instance, image_meta, vif):
        """Attach an interface to the instance."""
        vif_model = image_meta.get("hw_vif_model",
                                   constants.DEFAULT_VIF_MODEL)
        vif_model = vm_util.convert_vif_model(vif_model)
        vif_info = vmwarevif.get_vif_dict(self._session, self._cluster,
                                          vif_model, utils.is_neutron(), vif)
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Ensure that there is not a race with the port index management
        with lockutils.lock(instance.uuid,
                            lock_file_prefix='nova-vmware-hot-plug'):
            port_index = vm_util.get_attach_port_index(self._session, vm_ref)
            client_factory = self._session.vim.client.factory
            attach_config_spec = vm_util.get_network_attach_config_spec(
                                        client_factory, vif_info, port_index)
            LOG.debug("Reconfiguring VM to attach interface",
                      instance=instance)
            try:
                vm_util.reconfigure_vm(self._session, vm_ref,
                                       attach_config_spec)
            except Exception as e:
                LOG.error(_LE('Attaching network adapter failed. Exception: '
                              ' %s'),
                          e, instance=instance)
                raise exception.InterfaceAttachFailed(
                        instance_uuid=instance.uuid)
        LOG.debug("Reconfigured VM to attach interface", instance=instance)

    def detach_interface(self, instance, vif):
        """Detach an interface from the instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Ensure that there is not a race with the port index management
        with lockutils.lock(instance.uuid,
                            lock_file_prefix='nova-vmware-hot-plug'):
            port_index = vm_util.get_vm_detach_port_index(self._session,
                                                          vm_ref,
                                                          vif['id'])
            if port_index is None:
                msg = _("No device with interface-id %s exists on "
                        "VM") % vif['id']
                raise exception.NotFound(msg)

            hardware_devices = self._session._call_method(vim_util,
                            "get_dynamic_property", vm_ref,
                            "VirtualMachine", "config.hardware.device")
            device = vmwarevif.get_network_device(hardware_devices,
                                                  vif['address'])
            if device is None:
                msg = _("No device with MAC address %s exists on the "
                        "VM") % vif['address']
                raise exception.NotFound(msg)

            client_factory = self._session.vim.client.factory
            detach_config_spec = vm_util.get_network_detach_config_spec(
                                        client_factory, device, port_index)
            LOG.debug("Reconfiguring VM to detach interface",
                      instance=instance)
            try:
                vm_util.reconfigure_vm(self._session, vm_ref,
                                       detach_config_spec)
            except Exception as e:
                LOG.error(_LE('Detaching network adapter failed. Exception: '
                              '%s'),
                          e, instance=instance)
                raise exception.InterfaceDetachFailed(
                        instance_uuid=instance.uuid)
        LOG.debug("Reconfigured VM to detach interface", instance=instance)

    def _use_disk_image_as_full_clone(self, vm_ref, vi):
        """Uses cached image disk by copying it into the VM directory."""

        instance_folder = vi.instance_name
        root_disk_name = "%s.vmdk" % vi.instance_name
        root_disk_ds_loc = vi.datastore.build_path(instance_folder,
                                                   root_disk_name)

        vm_util.copy_virtual_disk(
                self._session,
                vi.dc_info.ref,
                str(vi.cache_image_path),
                str(root_disk_ds_loc))

        self._extend_if_required(
                vi.dc_info, vi.ii, vi.instance, str(root_disk_ds_loc))

        self._volumeops.attach_disk_to_vm(
                vm_ref, vi.instance,
                vi.ii.adapter_type, vi.ii.disk_type,
                str(root_disk_ds_loc),
                vi.root_gb * units.Mi, False)

    def _sized_image_exists(self, sized_disk_ds_loc, ds_ref):
        ds_browser = self._get_ds_browser(ds_ref)
        return ds_util.file_exists(
                self._session, ds_browser, sized_disk_ds_loc.parent,
                sized_disk_ds_loc.basename)

    def _use_disk_image_as_linked_clone(self, vm_ref, vi):
        """Uses cached image as parent of a COW child in the VM directory."""

        sized_image_disk_name = "%s.vmdk" % vi.ii.image_id
        if vi.root_gb > 0:
            sized_image_disk_name = "%s.%s.vmdk" % (vi.ii.image_id, vi.root_gb)
        sized_disk_ds_loc = vi.cache_image_folder.join(sized_image_disk_name)

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

        with lockutils.lock(str(sized_disk_ds_loc),
                            lock_file_prefix='nova-vmware-image'):

            if not self._sized_image_exists(sized_disk_ds_loc,
                                            vi.datastore.ref):
                LOG.debug("Copying root disk of size %sGb", vi.root_gb)
                try:
                    vm_util.copy_virtual_disk(
                            self._session,
                            vi.dc_info.ref,
                            str(vi.cache_image_path),
                            str(sized_disk_ds_loc))
                except Exception as e:
                    LOG.warning(_LW("Root disk file creation "
                                    "failed - %s"), e)
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE('Failed to copy cached '
                                      'image %(source)s to '
                                      '%(dest)s for resize: '
                                      '%(error)s'),
                                  {'source': vi.cache_image_path,
                                   'dest': sized_disk_ds_loc,
                                   'error': e.message})
                        try:
                            ds_util.file_delete(self._session,
                                                sized_disk_ds_loc,
                                                vi.dc_info.ref)
                        except vexc.FileNotFoundException:
                            # File was never created: cleanup not
                            # required
                            pass

                # Resize the copy to the appropriate size. No need
                # for cleanup up here, as _extend_virtual_disk
                # already does it
                self._extend_if_required(
                        vi.dc_info, vi.ii, vi.instance, str(sized_disk_ds_loc))

        # Associate the sized image disk to the VM by attaching to the VM a
        # COW child of said disk.
        self._volumeops.attach_disk_to_vm(
                vm_ref, vi.instance,
                vi.ii.adapter_type, vi.ii.disk_type,
                str(sized_disk_ds_loc),
                vi.root_gb * units.Mi, vi.ii.linked_clone)

    def _use_iso_image(self, vm_ref, vi):
        """Uses cached image as a bootable virtual cdrom."""

        self._attach_cdrom_to_vm(
                vm_ref, vi.instance, vi.datastore.ref,
                str(vi.cache_image_path))

        # Optionally create and attach blank disk
        if vi.root_gb > 0:
            instance_folder = vi.instance_name
            root_disk_name = "%s.vmdk" % vi.instance_name
            root_disk_ds_loc = vi.datastore.build_path(instance_folder,
                                                       root_disk_name)

            # It is pointless to COW a blank disk
            linked_clone = False

            vm_util.create_virtual_disk(
                    self._session, vi.dc_info.ref,
                    vi.ii.adapter_type,
                    vi.ii.disk_type,
                    str(root_disk_ds_loc),
                    vi.root_gb * units.Mi)

            self._volumeops.attach_disk_to_vm(
                    vm_ref, vi.instance,
                    vi.ii.adapter_type, vi.ii.disk_type,
                    str(root_disk_ds_loc),
                    vi.root_gb * units.Mi, linked_clone)

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
        LOG.debug("Getting list of instances from cluster %s",
                  self._cluster)
        vms = []
        if self._root_resource_pool:
            vms = self._session._call_method(
                vim_util, 'get_inner_objects', self._root_resource_pool, 'vm',
                'VirtualMachine', properties)
        lst_vm_names = self._get_valid_vms_from_retrieve_result(vms)

        LOG.debug("Got total of %s instances", str(len(lst_vm_names)))
        return lst_vm_names

    def get_vnc_console(self, instance):
        """Return connection info for a vnc console using vCenter logic."""

        # vCenter does not run virtual machines and does not run
        # a VNC proxy. Instead, you need to tell OpenStack to talk
        # directly to the ESX host running the VM you are attempting
        # to connect to via VNC.

        vnc_console = self._get_vnc_console_connection(instance)
        host_name = vm_util.get_host_name_for_vm(
                        self._session,
                        instance)
        vnc_console['host'] = host_name

        # NOTE: VM can move hosts in some situations. Debug for admins.
        LOG.debug("VM %(uuid)s is currently on host %(host_name)s",
                  {'uuid': instance.name, 'host_name': host_name},
                  instance=instance)
        return ctype.ConsoleVNC(**vnc_console)
