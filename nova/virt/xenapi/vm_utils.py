# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 OpenStack, LLC.
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
Helper methods for operations related to the management of VM records and
their attributes like VDIs, VIFs, as well as their lookup functions.
"""

import contextlib
import decimal
import os
import re
import time
import urllib
import urlparse
import uuid
from xml.dom import minidom
from xml.parsers import expat

from eventlet import greenthread

from nova.api.metadata import base as instance_metadata
from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
from nova import exception
from nova.image import glance
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import configdrive
from nova.virt.disk import api as disk
from nova.virt.disk.vfs import localfs as vfsimpl
from nova.virt import driver
from nova.virt.xenapi import agent
from nova.virt.xenapi import volume_utils


LOG = logging.getLogger(__name__)

xenapi_vm_utils_opts = [
    cfg.StrOpt('cache_images',
                default='all',
                help='Cache glance images locally. `all` will cache all'
                     ' images, `some` will only cache images that have the'
                     ' image_property `cache_in_nova=True`, and `none` turns'
                     ' off caching entirely'),
    cfg.StrOpt('default_os_type',
               default='linux',
               help='Default OS type'),
    cfg.IntOpt('block_device_creation_timeout',
               default=10,
               help='Time to wait for a block device to be created'),
    cfg.IntOpt('max_kernel_ramdisk_size',
               default=16 * 1024 * 1024,
               help='Maximum size in bytes of kernel or ramdisk images'),
    cfg.StrOpt('sr_matching_filter',
               default='other-config:i18n-key=local-storage',
               help='Filter for finding the SR to be used to install guest '
                    'instances on. The default value is the Local Storage in '
                    'default XenServer/XCP installations. To select an SR '
                    'with a different matching criteria, you could set it to '
                    'other-config:my_favorite_sr=true. On the other hand, to '
                    'fall back on the Default SR, as displayed by XenCenter, '
                    'set this flag to: default-sr:true'),
    cfg.BoolOpt('xenapi_sparse_copy',
                default=True,
                help='Whether to use sparse_copy for copying data on a '
                     'resize down (False will use standard dd). This speeds '
                     'up resizes down considerably since large runs of zeros '
                     'won\'t have to be rsynced'),
    cfg.IntOpt('xenapi_num_vbd_unplug_retries',
               default=10,
               help='Maximum number of retries to unplug VBD'),
    cfg.StrOpt('xenapi_torrent_images',
               default='none',
               help='Whether or not to download images via Bit Torrent '
                    '(all|some|none).'),
    cfg.StrOpt('xenapi_torrent_base_url',
               default=None,
               help='Base URL for torrent files.'),
    cfg.FloatOpt('xenapi_torrent_seed_chance',
                 default=1.0,
                 help='Probability that peer will become a seeder.'
                      ' (1.0 = 100%)'),
    cfg.IntOpt('xenapi_torrent_seed_duration',
               default=3600,
               help='Number of seconds after downloading an image via'
                    ' BitTorrent that it should be seeded for other peers.'),
    cfg.IntOpt('xenapi_torrent_max_last_accessed',
               default=86400,
               help='Cached torrent files not accessed within this number of'
                    ' seconds can be reaped'),
    cfg.IntOpt('xenapi_torrent_listen_port_start',
               default=6881,
               help='Beginning of port range to listen on'),
    cfg.IntOpt('xenapi_torrent_listen_port_end',
               default=6891,
               help='End of port range to listen on'),
    cfg.IntOpt('xenapi_torrent_download_stall_cutoff',
               default=600,
               help='Number of seconds a download can remain at the same'
                    ' progress percentage w/o being considered a stall'),
    cfg.IntOpt('xenapi_torrent_max_seeder_processes_per_host',
               default=1,
               help='Maximum number of seeder processes to run concurrently'
                    ' within a given dom0. (-1 = no limit)')
    ]

CONF = cfg.CONF
CONF.register_opts(xenapi_vm_utils_opts)
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('glance_num_retries', 'nova.image.glance')
CONF.import_opt('use_ipv6', 'nova.netconf')

XENAPI_POWER_STATE = {
    'Halted': power_state.SHUTDOWN,
    'Running': power_state.RUNNING,
    'Paused': power_state.PAUSED,
    'Suspended': power_state.SUSPENDED,
    'Crashed': power_state.CRASHED}


SECTOR_SIZE = 512
MBR_SIZE_SECTORS = 63
MBR_SIZE_BYTES = MBR_SIZE_SECTORS * SECTOR_SIZE
KERNEL_DIR = '/boot/guest'
MAX_VDI_CHAIN_SIZE = 16


class ImageType(object):
    """Enumeration class for distinguishing different image types

    | 0 - kernel image (goes on dom0's filesystem)
    | 1 - ramdisk image (goes on dom0's filesystem)
    | 2 - disk image (local SR, partitioned by objectstore plugin)
    | 3 - raw disk image (local SR, NOT partitioned by plugin)
    | 4 - vhd disk image (local SR, NOT inspected by XS, PV assumed for
    |     linux, HVM assumed for Windows)
    | 5 - ISO disk image (local SR, NOT partitioned by plugin)
    | 6 - config drive
    """

    KERNEL = 0
    RAMDISK = 1
    DISK = 2
    DISK_RAW = 3
    DISK_VHD = 4
    DISK_ISO = 5
    DISK_CONFIGDRIVE = 6
    _ids = (KERNEL, RAMDISK, DISK, DISK_RAW, DISK_VHD, DISK_ISO,
            DISK_CONFIGDRIVE)

    KERNEL_STR = "kernel"
    RAMDISK_STR = "ramdisk"
    DISK_STR = "root"
    DISK_RAW_STR = "os_raw"
    DISK_VHD_STR = "vhd"
    DISK_ISO_STR = "iso"
    DISK_CONFIGDRIVE_STR = "configdrive"
    _strs = (KERNEL_STR, RAMDISK_STR, DISK_STR, DISK_RAW_STR, DISK_VHD_STR,
             DISK_ISO_STR, DISK_CONFIGDRIVE_STR)

    @classmethod
    def to_string(cls, image_type):
        return dict(zip(ImageType._ids, ImageType._strs)).get(image_type)

    @classmethod
    def get_role(cls, image_type_id):
        """Get the role played by the image, based on its type."""
        return {
            cls.KERNEL: 'kernel',
            cls.RAMDISK: 'ramdisk',
            cls.DISK: 'root',
            cls.DISK_RAW: 'root',
            cls.DISK_VHD: 'root',
            cls.DISK_ISO: 'iso',
            cls.DISK_CONFIGDRIVE: 'configdrive'
        }.get(image_type_id)


def create_vm(session, instance, name_label, kernel, ramdisk,
              use_pv_kernel=False):
    """Create a VM record.  Returns new VM reference.
    the use_pv_kernel flag indicates whether the guest is HVM or PV

    There are 3 scenarios:

        1. Using paravirtualization, kernel passed in

        2. Using paravirtualization, kernel within the image

        3. Using hardware virtualization
    """
    instance_type = instance['instance_type']
    mem = str(long(instance_type['memory_mb']) * 1024 * 1024)
    vcpus = str(instance_type['vcpus'])

    rec = {
        'actions_after_crash': 'destroy',
        'actions_after_reboot': 'restart',
        'actions_after_shutdown': 'destroy',
        'affinity': '',
        'blocked_operations': {},
        'ha_always_run': False,
        'ha_restart_priority': '',
        'HVM_boot_params': {},
        'HVM_boot_policy': '',
        'is_a_template': False,
        'memory_dynamic_min': mem,
        'memory_dynamic_max': mem,
        'memory_static_min': '0',
        'memory_static_max': mem,
        'memory_target': mem,
        'name_description': '',
        'name_label': name_label,
        'other_config': {'allowvssprovider': str(False),
                         'nova_uuid': str(instance['uuid'])},
        'PCI_bus': '',
        'platform': {'acpi': 'true', 'apic': 'true', 'pae': 'true',
                     'viridian': 'true', 'timeoffset': '0'},
        'PV_args': '',
        'PV_bootloader': '',
        'PV_bootloader_args': '',
        'PV_kernel': '',
        'PV_legacy_args': '',
        'PV_ramdisk': '',
        'recommendations': '',
        'tags': [],
        'user_version': '0',
        'VCPUs_at_startup': vcpus,
        'VCPUs_max': vcpus,
        'VCPUs_params': {},
        'xenstore_data': {}}

    # Complete VM configuration record according to the image type
    # non-raw/raw with PV kernel/raw in HVM mode
    if use_pv_kernel:
        rec['platform']['nx'] = 'false'
        if instance['kernel_id']:
            # 1. Kernel explicitly passed in, use that
            rec['PV_args'] = 'root=/dev/xvda1'
            rec['PV_kernel'] = kernel
            rec['PV_ramdisk'] = ramdisk
        else:
            # 2. Use kernel within the image
            rec['PV_bootloader'] = 'pygrub'
    else:
        # 3. Using hardware virtualization
        rec['platform']['nx'] = 'true'
        rec['HVM_boot_params'] = {'order': 'dc'}
        rec['HVM_boot_policy'] = 'BIOS order'

    vm_ref = session.call_xenapi('VM.create', rec)
    LOG.debug(_('Created VM'), instance=instance)
    return vm_ref


def destroy_vm(session, instance, vm_ref):
    """Destroys a VM record."""
    try:
        session.call_xenapi('VM.destroy', vm_ref)
    except session.XenAPI.Failure, exc:
        LOG.exception(exc)
        return

    LOG.debug(_("VM destroyed"), instance=instance)


def clean_shutdown_vm(session, instance, vm_ref):
    if _is_vm_shutdown(session, vm_ref):
        LOG.warn(_("VM already halted, skipping shutdown..."),
                 instance=instance)
        return False

    LOG.debug(_("Shutting down VM (cleanly)"), instance=instance)
    try:
        session.call_xenapi('VM.clean_shutdown', vm_ref)
    except session.XenAPI.Failure, exc:
        LOG.exception(exc)
        return False
    return True


def hard_shutdown_vm(session, instance, vm_ref):
    if _is_vm_shutdown(session, vm_ref):
        LOG.warn(_("VM already halted, skipping shutdown..."),
                 instance=instance)
        return False

    LOG.debug(_("Shutting down VM (hard)"), instance=instance)
    try:
        session.call_xenapi('VM.hard_shutdown', vm_ref)
    except session.XenAPI.Failure, exc:
        LOG.exception(exc)
        return False
    return True


def _is_vm_shutdown(session, vm_ref):
    vm_rec = session.call_xenapi("VM.get_record", vm_ref)
    state = compile_info(vm_rec)['state']
    if state == power_state.SHUTDOWN:
        return True
    return False


def ensure_free_mem(session, instance):
    inst_type_id = instance['instance_type_id']
    instance_type = instance['instance_type']
    mem = long(instance_type['memory_mb']) * 1024 * 1024
    host = session.get_xenapi_host()
    host_free_mem = long(session.call_xenapi("host.compute_free_memory",
                                             host))
    return host_free_mem >= mem


def find_vbd_by_number(session, vm_ref, number):
    """Get the VBD reference from the device number."""
    vbd_refs = session.call_xenapi("VM.get_VBDs", vm_ref)
    if vbd_refs:
        for vbd_ref in vbd_refs:
            try:
                vbd_rec = session.call_xenapi("VBD.get_record", vbd_ref)
                if vbd_rec['userdevice'] == str(number):
                    return vbd_ref
            except session.XenAPI.Failure, exc:
                LOG.exception(exc)
    raise volume_utils.StorageError(
            _('VBD not found in instance %s') % vm_ref)


def unplug_vbd(session, vbd_ref):
    """Unplug VBD from VM."""
    # Call VBD.unplug on the given VBD, with a retry if we get
    # DEVICE_DETACH_REJECTED.  For reasons which we don't understand,
    # we're seeing the device still in use, even when all processes
    # using the device should be dead.
    max_attempts = CONF.xenapi_num_vbd_unplug_retries + 1
    for num_attempt in xrange(1, max_attempts + 1):
        try:
            session.call_xenapi('VBD.unplug', vbd_ref)
            return
        except session.XenAPI.Failure, exc:
            err = len(exc.details) > 0 and exc.details[0]
            if err == 'DEVICE_ALREADY_DETACHED':
                LOG.info(_('VBD %s already detached'), vbd_ref)
                return
            elif err == 'DEVICE_DETACH_REJECTED':
                LOG.info(_('VBD %(vbd_ref)s detach rejected, attempt'
                           ' %(num_attempt)d/%(max_attempts)d'), locals())
            else:
                LOG.exception(exc)
                raise volume_utils.StorageError(
                        _('Unable to unplug VBD %s') % vbd_ref)

        greenthread.sleep(1)

    raise volume_utils.StorageError(
            _('Reached maximum number of retries trying to unplug VBD %s')
            % vbd_ref)


def destroy_vbd(session, vbd_ref):
    """Destroy VBD from host database."""
    try:
        session.call_xenapi('VBD.destroy', vbd_ref)
    except session.XenAPI.Failure, exc:
        LOG.exception(exc)
        raise volume_utils.StorageError(
                _('Unable to destroy VBD %s') % vbd_ref)


def create_vbd(session, vm_ref, vdi_ref, userdevice, vbd_type='disk',
               read_only=False, bootable=False, osvol=False):
    """Create a VBD record and returns its reference."""
    vbd_rec = {}
    vbd_rec['VM'] = vm_ref
    vbd_rec['VDI'] = vdi_ref
    vbd_rec['userdevice'] = str(userdevice)
    vbd_rec['bootable'] = bootable
    vbd_rec['mode'] = read_only and 'RO' or 'RW'
    vbd_rec['type'] = vbd_type
    vbd_rec['unpluggable'] = True
    vbd_rec['empty'] = False
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    LOG.debug(_('Creating %(vbd_type)s-type VBD for VM %(vm_ref)s,'
                ' VDI %(vdi_ref)s ... '), locals())
    vbd_ref = session.call_xenapi('VBD.create', vbd_rec)
    LOG.debug(_('Created VBD %(vbd_ref)s for VM %(vm_ref)s,'
                ' VDI %(vdi_ref)s.'), locals())
    if osvol:
        # set osvol=True in other-config to indicate this is an
        # attached nova (or cinder) volume
        session.call_xenapi("VBD.add_to_other_config",
                                  vbd_ref, 'osvol', "True")
    return vbd_ref


def destroy_vdi(session, vdi_ref):
    try:
        session.call_xenapi('VDI.destroy', vdi_ref)
    except session.XenAPI.Failure, exc:
        LOG.exception(exc)
        raise volume_utils.StorageError(
                _('Unable to destroy VDI %s') % vdi_ref)


def safe_destroy_vdis(session, vdi_refs):
    """Destroys the requested VDIs, logging any StorageError exceptions."""
    for vdi_ref in vdi_refs:
        try:
            destroy_vdi(session, vdi_ref)
        except volume_utils.StorageError as exc:
            LOG.error(exc)


def create_vdi(session, sr_ref, instance, name_label, disk_type, virtual_size,
               read_only=False):
    """Create a VDI record and returns its reference."""
    # create_vdi may be called simply while creating a volume
    # hence information about instance may or may not be present
    otherconf = {'nova_disk_type': disk_type}
    if instance:
        otherconf['nova_instance_uuid'] = instance['uuid']
    vdi_ref = session.call_xenapi("VDI.create",
         {'name_label': name_label,
          'name_description': disk_type,
          'SR': sr_ref,
          'virtual_size': str(virtual_size),
          'type': 'User',
          'sharable': False,
          'read_only': read_only,
          'xenstore_data': {},
          'other_config': otherconf,
          'sm_config': {},
          'tags': []})
    LOG.debug(_('Created VDI %(vdi_ref)s (%(name_label)s,'
                ' %(virtual_size)s, %(read_only)s) on %(sr_ref)s.'),
              locals())
    return vdi_ref


def get_vdis_for_boot_from_vol(session, dev_params):
    vdis = {}
    sr_uuid, label, sr_params = volume_utils.parse_sr_info(dev_params)
    sr_ref = volume_utils.find_sr_by_uuid(session, sr_uuid)
    # Try introducing SR if it is not present
    if not sr_ref:
        sr_ref = volume_utils.introduce_sr(session, sr_uuid, label, sr_params)

    if sr_ref is None:
        raise exception.NovaException(_('SR not present and could not be '
                                        'introduced'))
    else:
        if 'vdi_uuid' in dev_params:
            session.call_xenapi("SR.scan", sr_ref)
            vdis = {'root': dict(uuid=dev_params['vdi_uuid'],
                    file=None, osvol=True)}
        else:
            try:
                vdi_ref = volume_utils.introduce_vdi(session, sr_ref)
                vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
                vdis = {'root': dict(uuid=vdi_rec['uuid'],
                                     file=None, osvol=True)}
            except volume_utils.StorageError, exc:
                LOG.exception(exc)
                volume_utils.forget_sr(session, sr_uuid)
    return vdis


def _volume_in_mapping(mount_device, block_device_info):
    block_device_list = [block_device.strip_prefix(vol['mount_device'])
                         for vol in
                         driver.block_device_info_get_mapping(
                         block_device_info)]
    swap = driver.block_device_info_get_swap(block_device_info)
    if driver.swap_is_usable(swap):
        swap_dev = swap['device_name']
        block_device_list.append(block_device.strip_prefix(swap_dev))
    block_device_list += [block_device.strip_prefix(ephemeral['device_name'])
                          for ephemeral in
                          driver.block_device_info_get_ephemerals(
                          block_device_info)]
    LOG.debug(_("block_device_list %s"), block_device_list)
    return block_device.strip_prefix(mount_device) in block_device_list


def get_vdis_for_instance(context, session, instance, name_label, image,
                          image_type, block_device_info=None):
    if block_device_info:
        LOG.debug(_("block device info: %s"), block_device_info)
        rootdev = block_device_info['root_device_name']
        if _volume_in_mapping(rootdev, block_device_info):
            # call function to return the vdi in connection info of block
            # device.
            # make it a point to return from here.
            bdm_root_dev = block_device_info['block_device_mapping'][0]
            dev_params = bdm_root_dev['connection_info']['data']
            LOG.debug(dev_params)
            return get_vdis_for_boot_from_vol(session, dev_params)
    return _create_image(context, session, instance, name_label, image,
                        image_type)


@contextlib.contextmanager
def _dummy_vm(session, instance, vdi_ref):
    """This creates a temporary VM so that we can snapshot a VDI.

    VDI's can't be snapshotted directly since the API expects a `vm_ref`. To
    work around this, we need to create a temporary VM and then map the VDI to
    the VM using a temporary VBD.
    """
    name_label = "dummy"
    vm_ref = create_vm(session, instance, name_label, None, None)
    try:
        vbd_ref = create_vbd(session, vm_ref, vdi_ref, 'autodetect',
                             read_only=True)
        try:
            yield vm_ref
        finally:
            try:
                destroy_vbd(session, vbd_ref)
            except volume_utils.StorageError:
                # destroy_vbd() will log error
                pass
    finally:
        destroy_vm(session, instance, vm_ref)


def _safe_copy_vdi(session, sr_ref, instance, vdi_to_copy_ref):
    """Copy a VDI and return the new VDIs reference.

    This function differs from the XenAPI `VDI.copy` call in that the copy is
    atomic and isolated, meaning we don't see half-downloaded images. It
    accomplishes this by copying the VDI's into a temporary directory and then
    atomically renaming them into the SR when the copy is completed.

    The correct long term solution is to fix `VDI.copy` so that it is atomic
    and isolated.
    """
    with _dummy_vm(session, instance, vdi_to_copy_ref) as vm_ref:
        label = "snapshot"
        with snapshot_attached_here(
                session, instance, vm_ref, label) as vdi_uuids:
            imported_vhds = session.call_plugin_serialized(
                'workarounds', 'safe_copy_vdis', sr_path=get_sr_path(session),
                vdi_uuids=vdi_uuids, uuid_stack=_make_uuid_stack())

    root_uuid = imported_vhds['root']['uuid']

    # TODO(sirp): for safety, we should probably re-scan the SR after every
    # call to a dom0 plugin, since there is a possibility that the underlying
    # VHDs changed
    scan_default_sr(session)
    vdi_ref = session.call_xenapi('VDI.get_by_uuid', root_uuid)
    return vdi_ref


def _clone_vdi(session, vdi_to_clone_ref):
    """Clones a VDI and return the new VDIs reference."""
    vdi_ref = session.call_xenapi('VDI.clone', vdi_to_clone_ref)
    LOG.debug(_('Cloned VDI %(vdi_ref)s from VDI '
                '%(vdi_to_clone_ref)s') % locals())
    return vdi_ref


def set_vdi_name(session, vdi_uuid, label, description, vdi_ref=None):
    vdi_ref = vdi_ref or session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
    session.call_xenapi('VDI.set_name_label', vdi_ref, label)
    session.call_xenapi('VDI.set_name_description', vdi_ref, description)


def get_vdi_for_vm_safely(session, vm_ref):
    """Retrieves the primary VDI for a VM."""
    vbd_refs = session.call_xenapi("VM.get_VBDs", vm_ref)
    for vbd in vbd_refs:
        vbd_rec = session.call_xenapi("VBD.get_record", vbd)
        # Convention dictates the primary VDI will be userdevice 0
        if vbd_rec['userdevice'] == '0':
            vdi_rec = session.call_xenapi("VDI.get_record", vbd_rec['VDI'])
            return vbd_rec['VDI'], vdi_rec
    raise exception.NovaException(_("No primary VDI found for %(vm_ref)s")
                                  % locals())


@contextlib.contextmanager
def snapshot_attached_here(session, instance, vm_ref, label, *args):
    update_task_state = None
    if len(args) == 1:
        update_task_state = args[0]

    """Snapshot the root disk only.  Return a list of uuids for the vhds
    in the chain.
    """
    LOG.debug(_("Starting snapshot for VM"), instance=instance)

    # Memorize the original_parent_uuid so we can poll for coalesce
    vm_vdi_ref, vm_vdi_rec = get_vdi_for_vm_safely(session, vm_ref)
    original_parent_uuid = _get_vhd_parent_uuid(session, vm_vdi_ref)
    sr_ref = vm_vdi_rec["SR"]

    snapshot_ref = session.call_xenapi("VDI.snapshot", vm_vdi_ref, {})
    if update_task_state is not None:
        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
    try:
        snapshot_rec = session.call_xenapi("VDI.get_record", snapshot_ref)
        _wait_for_vhd_coalesce(session, instance, sr_ref, vm_vdi_ref,
                original_parent_uuid)
        vdi_uuids = [vdi_rec['uuid'] for vdi_rec in
                _walk_vdi_chain(session, snapshot_rec['uuid'])]
        yield vdi_uuids
    finally:
        safe_destroy_vdis(session, [snapshot_ref])


def get_sr_path(session):
    """Return the path to our storage repository

    This is used when we're dealing with VHDs directly, either by taking
    snapshots or by restoring an image in the DISK_VHD format.
    """
    sr_ref = safe_find_sr(session)
    sr_rec = session.call_xenapi("SR.get_record", sr_ref)
    sr_uuid = sr_rec["uuid"]
    return os.path.join(CONF.xenapi_sr_base_path, sr_uuid)


def destroy_cached_images(session, sr_ref, all_cached=False, dry_run=False):
    """Destroy used or unused cached images.

    A cached image that is being used by at least one VM is said to be 'used'.

    In the case of an 'unused' image, the cached image will be the only
    descendent of the base-copy. So when we delete the cached-image, the
    refcount will drop to zero and XenServer will automatically destroy the
    base-copy for us.

    The default behavior of this function is to destroy only 'unused' cached
    images. To destroy all cached images, use the `all_cached=True` kwarg.
    """
    cached_images = _find_cached_images(session, sr_ref)
    destroyed = set()

    def destroy_cached_vdi(vdi_uuid, vdi_ref):
        LOG.debug(_("Destroying cached VDI '%(vdi_uuid)s'"))
        if not dry_run:
            destroy_vdi(session, vdi_ref)
        destroyed.add(vdi_uuid)

    for vdi_ref in cached_images.values():
        vdi_uuid = session.call_xenapi('VDI.get_uuid', vdi_ref)

        if all_cached:
            destroy_cached_vdi(vdi_uuid, vdi_ref)
            continue

        # Unused-Only: Search for siblings

        # Chain length greater than two implies a VM must be holding a ref to
        # the base-copy (otherwise it would have coalesced), so consider this
        # cached image used.
        chain = list(_walk_vdi_chain(session, vdi_uuid))
        if len(chain) > 2:
            continue
        elif len(chain) == 2:
            # Siblings imply cached image is used
            root_vdi_rec = chain[-1]
            children = _child_vhds(session, sr_ref, root_vdi_rec['uuid'])
            if len(children) > 1:
                continue

        destroy_cached_vdi(vdi_uuid, vdi_ref)

    return destroyed


def _find_cached_images(session, sr_ref):
    """Return a dict(uuid=vdi_ref) representing all cached images."""
    cached_images = {}
    for vdi_ref, vdi_rec in _get_all_vdis_in_sr(session, sr_ref):
        try:
            image_id = vdi_rec['other_config']['image-id']
        except KeyError:
            continue

        cached_images[image_id] = vdi_ref

    return cached_images


def _find_cached_image(session, image_id, sr_ref):
    """Returns the vdi-ref of the cached image."""
    cached_images = _find_cached_images(session, sr_ref)
    return cached_images.get(image_id)


def upload_image(context, session, instance, vdi_uuids, image_id):
    """Requests that the Glance plugin bundle the specified VDIs and
    push them into Glance using the specified human-friendly name.
    """
    # NOTE(sirp): Currently we only support uploading images as VHD, there
    # is no RAW equivalent (yet)
    LOG.debug(_("Asking xapi to upload %(vdi_uuids)s as"
                " ID %(image_id)s"), locals(), instance=instance)

    glance_api_servers = glance.get_api_servers()
    glance_host, glance_port, glance_use_ssl = glance_api_servers.next()

    properties = {
        'auto_disk_config': instance['auto_disk_config'],
        'os_type': instance['os_type'] or CONF.default_os_type,
    }

    params = {'vdi_uuids': vdi_uuids,
              'image_id': image_id,
              'glance_host': glance_host,
              'glance_port': glance_port,
              'glance_use_ssl': glance_use_ssl,
              'sr_path': get_sr_path(session),
              'auth_token': getattr(context, 'auth_token', None),
              'properties': properties}

    session.call_plugin_serialized('glance', 'upload_vhd', **params)


def resize_disk(session, instance, vdi_ref, instance_type):
    # Copy VDI over to something we can resize
    # NOTE(jerdfelt): Would be nice to just set vdi_ref to read/write
    sr_ref = safe_find_sr(session)
    copy_ref = session.call_xenapi('VDI.copy', vdi_ref, sr_ref)

    try:
        # Resize partition and filesystem down
        auto_configure_disk(session, copy_ref, instance_type['root_gb'])

        # Create new VDI
        vdi_size = instance_type['root_gb'] * 1024 * 1024 * 1024
        # NOTE(johannes): No resizing allowed for rescue instances, so
        # using instance['name'] is safe here
        new_ref = create_vdi(session, sr_ref, instance, instance['name'],
                             'root', vdi_size)

        new_uuid = session.call_xenapi('VDI.get_uuid', new_ref)

        # Manually copy contents over
        virtual_size = instance_type['root_gb'] * 1024 * 1024 * 1024
        _copy_partition(session, copy_ref, new_ref, 1, virtual_size)

        return new_ref, new_uuid
    finally:
        destroy_vdi(session, copy_ref)


def auto_configure_disk(session, vdi_ref, new_gb):
    """Partition and resize FS to match the size specified by
    instance_types.root_gb.

    This is a fail-safe to prevent accidentally destroying data on a disk
    erroneously marked as auto_disk_config=True.

    The criteria for allowing resize are:

        1. 'auto_disk_config' must be true for the instance (and image).
           (If we've made it here, then auto_disk_config=True.)

        2. The disk must have only one partition.

        3. The file-system on the one partition must be ext3 or ext4.
    """
    with vdi_attached_here(session, vdi_ref, read_only=False) as dev:
        partitions = _get_partitions(dev)

        if len(partitions) != 1:
            return

        _num, start, old_sectors, ptype = partitions[0]
        if ptype in ('ext3', 'ext4'):
            new_sectors = new_gb * 1024 * 1024 * 1024 / SECTOR_SIZE
            _resize_part_and_fs(dev, start, old_sectors, new_sectors)


def _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   disk_type, size_mb, fs_type):
    """
    Steps to programmatically generate a disk:

        1. Create VDI of desired size

        2. Attach VDI to compute worker

        3. Create partition

        4. Create VBD between instance VM and VDI
    """
    # 1. Create VDI
    sr_ref = safe_find_sr(session)
    ONE_MEG = 1024 * 1024
    virtual_size = size_mb * ONE_MEG
    vdi_ref = create_vdi(session, sr_ref, instance, name_label, disk_type,
                         virtual_size)

    try:
        # 2. Attach VDI to compute worker (VBD hotplug)
        with vdi_attached_here(session, vdi_ref, read_only=False) as dev:
            # 3. Create partition
            dev_path = utils.make_dev_path(dev)
            utils.execute('parted', '--script', dev_path,
                          'mklabel', 'msdos', run_as_root=True)

            partition_start = 0
            partition_end = size_mb
            utils.execute('parted', '--script', dev_path,
                          'mkpart', 'primary',
                          str(partition_start),
                          str(partition_end),
                          run_as_root=True)

            partition_path = utils.make_dev_path(dev, partition=1)

            if fs_type == 'linux-swap':
                utils.execute('mkswap', partition_path, run_as_root=True)
            elif fs_type is not None:
                utils.execute('mkfs', '-t', fs_type, partition_path,
                              run_as_root=True)

        # 4. Create VBD between instance VM and swap VDI
        create_vbd(session, vm_ref, vdi_ref, userdevice, bootable=False)
    except Exception:
        with excutils.save_and_reraise_exception():
            destroy_vdi(session, vdi_ref)


def generate_swap(session, instance, vm_ref, userdevice, name_label, swap_mb):
    # NOTE(jk0): We use a FAT32 filesystem for the Windows swap
    # partition because that is what parted supports.
    is_windows = instance['os_type'] == "windows"
    fs_type = "vfat" if is_windows else "linux-swap"

    _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   'swap', swap_mb, fs_type)


def generate_ephemeral(session, instance, vm_ref, userdevice, name_label,
                       size_gb):
    _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   'ephemeral', size_gb * 1024,
                   CONF.default_ephemeral_format)


def generate_configdrive(session, instance, vm_ref, userdevice,
                         admin_password=None, files=None):
    sr_ref = safe_find_sr(session)
    vdi_ref = create_vdi(session, sr_ref, instance, 'config-2',
                         'configdrive', configdrive.CONFIGDRIVESIZE_BYTES)

    try:
        with vdi_attached_here(session, vdi_ref, read_only=False) as dev:
            extra_md = {}
            if admin_password:
                extra_md['admin_pass'] = admin_password
            inst_md = instance_metadata.InstanceMetadata(instance,
                                                         content=files,
                                                         extra_md=extra_md)
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                with utils.tempdir() as tmp_path:
                    tmp_file = os.path.join(tmp_path, 'configdrive')
                    cdb.make_drive(tmp_file)

                    dev_path = utils.make_dev_path(dev)
                    utils.execute('dd',
                                  'if=%s' % tmp_file,
                                  'of=%s' % dev_path,
                                  run_as_root=True)

        create_vbd(session, vm_ref, vdi_ref, userdevice, bootable=False,
                   read_only=True)
    except Exception:
        with excutils.save_and_reraise_exception():
            destroy_vdi(session, vdi_ref)


def create_kernel_image(context, session, instance, name_label, image_id,
                        image_type):
    """Creates kernel/ramdisk file from the image stored in the cache.
    If the image is not present in the cache, it streams it from glance.

    Returns: A list of dictionaries that describe VDIs
    """
    filename = ""
    if CONF.cache_images:
        args = {}
        args['cached-image'] = image_id
        args['new-image-uuid'] = str(uuid.uuid4())
        filename = session.call_plugin('kernel', 'create_kernel_ramdisk', args)

    if filename == "":
        return _fetch_disk_image(context, session, instance, name_label,
                                 image_id, image_type)
    else:
        vdi_type = ImageType.to_string(image_type)
        return {vdi_type: dict(uuid=None, file=filename)}


def destroy_kernel_ramdisk(session, kernel, ramdisk):
    args = {}
    if kernel:
        args['kernel-file'] = kernel
    if ramdisk:
        args['ramdisk-file'] = ramdisk
    if args:
        session.call_plugin('kernel', 'remove_kernel_ramdisk', args)


def _create_cached_image(context, session, instance, name_label,
                         image_id, image_type):
    sr_ref = safe_find_sr(session)
    sr_type = session.call_xenapi('SR.get_record', sr_ref)["type"]
    vdis = {}

    if CONF.use_cow_images and sr_type != "ext":
        LOG.warning(_("Fast cloning is only supported on default local SR "
                      "of type ext. SR on this system was found to be of "
                      "type %(sr_type)s. Ignoring the cow flag.")
                      % locals())

    root_vdi_ref = _find_cached_image(session, image_id, sr_ref)
    if root_vdi_ref is None:
        vdis = _fetch_image(context, session, instance, name_label,
                            image_id, image_type)
        root_vdi = vdis['root']
        root_vdi_ref = session.call_xenapi('VDI.get_by_uuid',
                                           root_vdi['uuid'])
        set_vdi_name(session, root_vdi['uuid'], 'Glance Image %s' % image_id,
                     'root', vdi_ref=root_vdi_ref)
        session.call_xenapi('VDI.add_to_other_config',
                            root_vdi_ref, 'image-id', str(image_id))

    if CONF.use_cow_images and sr_type == 'ext':
        new_vdi_ref = _clone_vdi(session, root_vdi_ref)
    else:
        new_vdi_ref = _safe_copy_vdi(session, sr_ref, instance, root_vdi_ref)

    # Set the name label for the image we just created and remove image id
    # field from other-config.
    session.call_xenapi('VDI.remove_from_other_config',
                        new_vdi_ref, 'image-id')

    vdi_type = ImageType.get_role(image_type)
    vdi_uuid = session.call_xenapi('VDI.get_uuid', new_vdi_ref)
    vdis[vdi_type] = dict(uuid=vdi_uuid, file=None)
    return vdis


def _create_image(context, session, instance, name_label, image_id,
                  image_type):
    """Creates VDI from the image stored in the local cache. If the image
    is not present in the cache, it streams it from glance.

    Returns: A list of dictionaries that describe VDIs
    """
    cache_images = CONF.cache_images.lower()

    # Deterimine if the image is cacheable
    if image_type == ImageType.DISK_ISO:
        cache = False
    elif cache_images == 'all':
        cache = True
    elif cache_images == 'some':
        sys_meta = utils.metadata_to_dict(instance['system_metadata'])
        try:
            cache = utils.bool_from_str(sys_meta['image_cache_in_nova'])
        except KeyError:
            cache = False
    elif cache_images == 'none':
        cache = False
    else:
        LOG.warning(_("Unrecognized cache_images value '%s', defaulting to"
                      " True"), CONF.cache_images)
        cache = True

    # Fetch (and cache) the image
    if cache:
        vdis = _create_cached_image(context, session, instance, name_label,
                                    image_id, image_type)
    else:
        vdis = _fetch_image(context, session, instance, name_label,
                            image_id, image_type)

    # Set the name label and description to easily identify what
    # instance and disk it's for
    for vdi_type, vdi in vdis.iteritems():
        set_vdi_name(session, vdi['uuid'], name_label, vdi_type)

    return vdis


def _fetch_image(context, session, instance, name_label, image_id, image_type):
    """Fetch image from glance based on image type.

    Returns: A single filename if image_type is KERNEL or RAMDISK
             A list of dictionaries that describe VDIs, otherwise
    """
    if image_type == ImageType.DISK_VHD:
        vdis = _fetch_vhd_image(context, session, instance, image_id)
    else:
        vdis = _fetch_disk_image(context, session, instance, name_label,
                                 image_id, image_type)

    for vdi_type, vdi in vdis.iteritems():
        vdi_uuid = vdi['uuid']
        LOG.debug(_("Fetched VDIs of type '%(vdi_type)s' with UUID"
                    " '%(vdi_uuid)s'"),
                  locals(), instance=instance)

    return vdis


def _fetch_using_dom0_plugin_with_retry(context, session, image_id,
                                        plugin_name, params, callback=None):
    max_attempts = CONF.glance_num_retries + 1
    sleep_time = 0.5
    for attempt_num in xrange(1, max_attempts + 1):
        LOG.info(_('download_vhd %(image_id)s, '
                   'attempt %(attempt_num)d/%(max_attempts)d, '
                   'params: %(params)s') % locals())

        try:
            if callback:
                callback(params)

            return session.call_plugin_serialized(
                    plugin_name, 'download_vhd', **params)
        except session.XenAPI.Failure as exc:
            _type, _method, error = exc.details[:3]
            if error == 'RetryableError':
                LOG.error(_('download_vhd failed: %r') %
                          (exc.details[3:],))
            else:
                raise

        time.sleep(sleep_time)
        sleep_time = min(2 * sleep_time, 15)

    raise exception.CouldNotFetchImage(image_id=image_id)


def _make_uuid_stack():
    # NOTE(sirp): The XenAPI plugins run under Python 2.4
    # which does not have the `uuid` module. To work around this,
    # we generate the uuids here (under Python 2.6+) and
    # pass them as arguments
    return [str(uuid.uuid4()) for i in xrange(MAX_VDI_CHAIN_SIZE)]


def _image_uses_bittorrent(context, instance):
    bittorrent = False
    xenapi_torrent_images = CONF.xenapi_torrent_images.lower()

    if xenapi_torrent_images == 'all':
        bittorrent = True
    elif xenapi_torrent_images == 'some':
        sys_meta = utils.metadata_to_dict(instance['system_metadata'])
        try:
            bittorrent = utils.bool_from_str(sys_meta['image_bittorrent'])
        except KeyError:
            pass
    elif xenapi_torrent_images == 'none':
        pass
    else:
        LOG.warning(_("Invalid value '%s' for xenapi_torrent_images"),
                    xenapi_torrent_images)

    return bittorrent


def _fetch_vhd_image(context, session, instance, image_id):
    """Tell glance to download an image and put the VHDs into the SR

    Returns: A list of dictionaries that describe VDIs
    """
    LOG.debug(_("Asking xapi to fetch vhd image %(image_id)s"), locals(),
              instance=instance)

    params = {'image_id': image_id,
              'uuid_stack': _make_uuid_stack(),
              'sr_path': get_sr_path(session)}

    if _image_uses_bittorrent(context, instance):
        plugin_name = 'bittorrent'
        callback = None
        params['torrent_base_url'] = CONF.xenapi_torrent_base_url
        params['torrent_seed_duration'] = CONF.xenapi_torrent_seed_duration
        params['torrent_seed_chance'] = CONF.xenapi_torrent_seed_chance
        params['torrent_max_last_accessed'] =\
                CONF.xenapi_torrent_max_last_accessed
        params['torrent_listen_port_start'] =\
                CONF.xenapi_torrent_listen_port_start
        params['torrent_listen_port_end'] =\
                CONF.xenapi_torrent_listen_port_end
        params['torrent_download_stall_cutoff'] =\
                CONF.xenapi_torrent_download_stall_cutoff
        params['torrent_max_seeder_processes_per_host'] =\
                CONF.xenapi_torrent_max_seeder_processes_per_host
    else:
        plugin_name = 'glance'
        glance_api_servers = glance.get_api_servers()

        def pick_glance(params):
            g_host, g_port, g_use_ssl = glance_api_servers.next()
            params['glance_host'] = g_host
            params['glance_port'] = g_port
            params['glance_use_ssl'] = g_use_ssl
            params['auth_token'] = getattr(context, 'auth_token', None)

        callback = pick_glance

    vdis = _fetch_using_dom0_plugin_with_retry(
            context, session, image_id, plugin_name, params,
            callback=callback)

    sr_ref = safe_find_sr(session)
    _scan_sr(session, sr_ref)

    # Pull out the UUID of the root VDI
    root_vdi_uuid = vdis['root']['uuid']

    # Set the name-label to ease debugging
    set_vdi_name(session, root_vdi_uuid, instance['name'], 'root')

    _check_vdi_size(context, session, instance, root_vdi_uuid)
    return vdis


def _get_vdi_chain_size(session, vdi_uuid):
    """Compute the total size of a VDI chain, starting with the specified
    VDI UUID.

    This will walk the VDI chain to the root, add the size of each VDI into
    the total.
    """
    size_bytes = 0
    for vdi_rec in _walk_vdi_chain(session, vdi_uuid):
        cur_vdi_uuid = vdi_rec['uuid']
        vdi_size_bytes = int(vdi_rec['physical_utilisation'])
        LOG.debug(_('vdi_uuid=%(cur_vdi_uuid)s vdi_size_bytes='
                    '%(vdi_size_bytes)d'), locals())
        size_bytes += vdi_size_bytes
    return size_bytes


def _check_vdi_size(context, session, instance, vdi_uuid):
    size_bytes = _get_vdi_chain_size(session, vdi_uuid)

    # FIXME(jk0): this was copied directly from compute.manager.py, let's
    # refactor this to a common area
    instance_type = instance['instance_type']
    allowed_size_gb = instance_type['root_gb']
    allowed_size_bytes = allowed_size_gb * 1024 * 1024 * 1024

    LOG.debug(_("image_size_bytes=%(size_bytes)d, allowed_size_bytes="
                "%(allowed_size_bytes)d"), locals(), instance=instance)

    if size_bytes > allowed_size_bytes:
        LOG.info(_("Image size %(size_bytes)d exceeded instance_type "
                   "allowed size %(allowed_size_bytes)d"),
                 locals(), instance=instance)
        raise exception.ImageTooLarge()


def _fetch_disk_image(context, session, instance, name_label, image_id,
                      image_type):
    """Fetch the image from Glance

    NOTE:
    Unlike _fetch_vhd_image, this method does not use the Glance
    plugin; instead, it streams the disks through domU to the VDI
    directly.

    Returns: A single filename if image_type is KERNEL_RAMDISK
             A list of dictionaries that describe VDIs, otherwise
    """
    # FIXME(sirp): Since the Glance plugin seems to be required for the
    # VHD disk, it may be worth using the plugin for both VHD and RAW and
    # DISK restores
    image_type_str = ImageType.to_string(image_type)
    LOG.debug(_("Fetching image %(image_id)s, type %(image_type_str)s"),
              locals(), instance=instance)

    if image_type == ImageType.DISK_ISO:
        sr_ref = _safe_find_iso_sr(session)
    else:
        sr_ref = safe_find_sr(session)

    image_service, image_id = glance.get_remote_image_service(
            context, image_id)
    meta = image_service.show(context, image_id)
    virtual_size = int(meta['size'])
    vdi_size = virtual_size
    LOG.debug(_("Size for image %(image_id)s: %(virtual_size)d"), locals(),
              instance=instance)
    if image_type == ImageType.DISK:
        # Make room for MBR.
        vdi_size += MBR_SIZE_BYTES
    elif (image_type in (ImageType.KERNEL, ImageType.RAMDISK) and
          vdi_size > CONF.max_kernel_ramdisk_size):
        max_size = CONF.max_kernel_ramdisk_size
        raise exception.NovaException(
            _("Kernel/Ramdisk image is too large: %(vdi_size)d bytes, "
              "max %(max_size)d bytes") % locals())

    vdi_ref = create_vdi(session, sr_ref, instance, name_label,
                         image_type_str, vdi_size)
    # From this point we have a VDI on Xen host;
    # If anything goes wrong, we need to remember its uuid.
    try:
        filename = None
        vdi_uuid = session.call_xenapi("VDI.get_uuid", vdi_ref)

        with vdi_attached_here(session, vdi_ref, read_only=False) as dev:
            stream_func = lambda f: image_service.download(
                    context, image_id, f)
            _stream_disk(stream_func, image_type, virtual_size, dev)

        if image_type in (ImageType.KERNEL, ImageType.RAMDISK):
            # We need to invoke a plugin for copying the
            # content of the VDI into the proper path.
            LOG.debug(_("Copying VDI %s to /boot/guest on dom0"),
                      vdi_ref, instance=instance)

            args = {}
            args['vdi-ref'] = vdi_ref

            # Let the plugin copy the correct number of bytes.
            args['image-size'] = str(vdi_size)
            if CONF.cache_images:
                args['cached-image'] = image_id
            filename = session.call_plugin('kernel', 'copy_vdi', args)

            # Remove the VDI as it is not needed anymore.
            destroy_vdi(session, vdi_ref)
            LOG.debug(_("Kernel/Ramdisk VDI %s destroyed"), vdi_ref,
                      instance=instance)
            vdi_role = ImageType.get_role(image_type)
            return {vdi_role: dict(uuid=None, file=filename)}
        else:
            vdi_role = ImageType.get_role(image_type)
            return {vdi_role: dict(uuid=vdi_uuid, file=None)}
    except (session.XenAPI.Failure, IOError, OSError) as e:
        # We look for XenAPI and OS failures.
        LOG.exception(_("Failed to fetch glance image"),
                      instance=instance)
        e.args = e.args + ([dict(type=ImageType.to_string(image_type),
                                 uuid=vdi_uuid,
                                 file=filename)],)
        raise


def determine_disk_image_type(image_meta):
    """Disk Image Types are used to determine where the kernel will reside
    within an image. To figure out which type we're dealing with, we use
    the following rules:

    1. If we're using Glance, we can use the image_type field to
       determine the image_type

    2. If we're not using Glance, then we need to deduce this based on
       whether a kernel_id is specified.
    """
    if not image_meta:
        return None

    disk_format = image_meta['disk_format']

    disk_format_map = {
        'ami': 'DISK',
        'aki': 'KERNEL',
        'ari': 'RAMDISK',
        'raw': 'DISK_RAW',
        'vhd': 'DISK_VHD',
        'iso': 'DISK_ISO',
    }

    try:
        image_type_str = disk_format_map[disk_format]
    except KeyError:
        raise exception.InvalidDiskFormat(disk_format=disk_format)

    image_type = getattr(ImageType, image_type_str)

    image_ref = image_meta['id']
    msg = _("Detected %(image_type_str)s format for image %(image_ref)s")
    LOG.debug(msg % locals())

    return image_type


def determine_is_pv(session, vdi_ref, disk_image_type, os_type):
    """
    Determine whether the VM will use a paravirtualized kernel or if it
    will use hardware virtualization.

        1. Glance (VHD): then we use `os_type`, raise if not set

        2. Glance (DISK_RAW): use Pygrub to figure out if pv kernel is
           available

        3. Glance (DISK): pv is assumed

        4. Glance (DISK_ISO): no pv is assumed

        5. Boot From Volume - without image metadata (None): attempt to
           use Pygrub to figure out if the volume stores a PV VM or a
           HVM one. Log a warning, because there may be cases where the
           volume is RAW (in which case using pygrub is fine) and cases
           where the content of the volume is VHD, and pygrub might not
           work as expected.
           NOTE: if disk_image_type is not specified, instances launched
           from remote volumes will have to include kernel and ramdisk
           because external kernel and ramdisk will not be fetched.
    """

    LOG.debug(_("Looking up vdi %s for PV kernel"), vdi_ref)
    if disk_image_type == ImageType.DISK_VHD:
        # 1. VHD
        if os_type == 'windows':
            is_pv = False
        else:
            is_pv = True
    elif disk_image_type == ImageType.DISK_RAW:
        # 2. RAW
        with vdi_attached_here(session, vdi_ref, read_only=True) as dev:
            is_pv = _is_vdi_pv(dev)
    elif disk_image_type == ImageType.DISK:
        # 3. Disk
        is_pv = True
    elif disk_image_type == ImageType.DISK_ISO:
        # 4. ISO
        is_pv = False
    elif not disk_image_type:
        LOG.warning(_("Image format is None: trying to determine PV status "
                      "using pygrub; if instance with vdi %s does not boot "
                      "correctly, try with image metadata.") % vdi_ref)
        with vdi_attached_here(session, vdi_ref, read_only=True) as dev:
            is_pv = _is_vdi_pv(dev)
    else:
        msg = _("Unknown image format %(disk_image_type)s") % locals()
        raise exception.NovaException(msg)

    return is_pv


def set_vm_name_label(session, vm_ref, name_label):
    session.call_xenapi("VM.set_name_label", vm_ref, name_label)


def list_vms(session):
    for vm_ref, vm_rec in session.get_all_refs_and_recs('VM'):
        if (vm_rec["resident_on"] != session.get_xenapi_host() or
            vm_rec["is_a_template"] or vm_rec["is_control_domain"]):
            continue
        else:
            yield vm_ref, vm_rec


def lookup_vm_vdis(session, vm_ref):
    """Look for the VDIs that are attached to the VM."""
    # Firstly we get the VBDs, then the VDIs.
    # TODO(Armando): do we leave the read-only devices?
    vbd_refs = session.call_xenapi("VM.get_VBDs", vm_ref)
    vdi_refs = []
    if vbd_refs:
        for vbd_ref in vbd_refs:
            try:
                vdi_ref = session.call_xenapi("VBD.get_VDI", vbd_ref)
                # Test valid VDI
                record = session.call_xenapi("VDI.get_record", vdi_ref)
                LOG.debug(_('VDI %s is still available'), record['uuid'])
                vbd_other_config = session.call_xenapi("VBD.get_other_config",
                                                       vbd_ref)
                if not vbd_other_config.get('osvol'):
                    # This is not an attached volume
                    vdi_refs.append(vdi_ref)
            except session.XenAPI.Failure, exc:
                LOG.exception(exc)
    return vdi_refs


def lookup(session, name_label):
    """Look the instance up and return it if available."""
    vm_refs = session.call_xenapi("VM.get_by_name_label", name_label)
    n = len(vm_refs)
    if n == 0:
        return None
    elif n > 1:
        raise exception.InstanceExists(name=name_label)
    else:
        return vm_refs[0]


def preconfigure_instance(session, instance, vdi_ref, network_info):
    """Makes alterations to the image before launching as part of spawn.
    """

    # As mounting the image VDI is expensive, we only want do do it once,
    # if at all, so determine whether it's required first, and then do
    # everything
    mount_required = False
    key, net, metadata = _prepare_injectables(instance, network_info)
    mount_required = key or net or metadata
    if not mount_required:
        return

    with vdi_attached_here(session, vdi_ref, read_only=False) as dev:
        _mounted_processing(dev, key, net, metadata)


def lookup_kernel_ramdisk(session, vm):
    vm_rec = session.call_xenapi("VM.get_record", vm)
    if 'PV_kernel' in vm_rec and 'PV_ramdisk' in vm_rec:
        return (vm_rec['PV_kernel'], vm_rec['PV_ramdisk'])
    else:
        return (None, None)


def is_snapshot(session, vm):
    vm_rec = session.call_xenapi("VM.get_record", vm)
    if 'is_a_template' in vm_rec and 'is_a_snapshot' in vm_rec:
        return vm_rec['is_a_template'] and vm_rec['is_a_snapshot']
    else:
        return False


def compile_info(record):
    """Fill record with VM status information."""
    return {'state': XENAPI_POWER_STATE[record['power_state']],
            'max_mem': long(record['memory_static_max']) >> 10,
            'mem': long(record['memory_dynamic_max']) >> 10,
            'num_cpu': record['VCPUs_max'],
            'cpu_time': 0}


def compile_diagnostics(record):
    """Compile VM diagnostics data."""
    try:
        keys = []
        diags = {}
        vm_uuid = record["uuid"]
        xml = _get_rrd(_get_rrd_server(), vm_uuid)
        if xml:
            rrd = minidom.parseString(xml)
            for i, node in enumerate(rrd.firstChild.childNodes):
                # Provide the last update of the information
                if node.localName == 'lastupdate':
                    diags['last_update'] = node.firstChild.data

                # Create a list of the diagnostic keys (in their order)
                if node.localName == 'ds':
                    ref = node.childNodes
                    # Name and Value
                    if len(ref) > 6:
                        keys.append(ref[0].firstChild.data)

                # Read the last row of the first RRA to get the latest info
                if node.localName == 'rra':
                    rows = node.childNodes[4].childNodes
                    last_row = rows[rows.length - 1].childNodes
                    for j, value in enumerate(last_row):
                        diags[keys[j]] = value.firstChild.data
                    break

        return diags
    except expat.ExpatError as e:
        LOG.exception(_('Unable to parse rrd of %(vm_uuid)s') % locals())
        return {"Unable to retrieve diagnostics": e}


def fetch_bandwidth(session):
    bw = session.call_plugin_serialized('bandwidth', 'fetch_all_bandwidth')
    return bw


def compile_metrics(start_time, stop_time=None):
    """Compile bandwidth usage, cpu, and disk metrics for all VMs on
       this host.
       Note that some stats, like bandwidth, do not seem to be very
       accurate in some of the data from XenServer (mdragon). """
    start_time = int(start_time)

    xml = _get_rrd_updates(_get_rrd_server(), start_time)
    if xml:
        doc = minidom.parseString(xml)
        return _parse_rrd_update(doc, start_time, stop_time)

    raise exception.CouldNotFetchMetrics()


def _scan_sr(session, sr_ref=None):
    """Scans the SR specified by sr_ref."""
    if sr_ref:
        LOG.debug(_("Re-scanning SR %s"), sr_ref)
        session.call_xenapi('SR.scan', sr_ref)


def scan_default_sr(session):
    """Looks for the system default SR and triggers a re-scan."""
    _scan_sr(session, _find_sr(session))


def safe_find_sr(session):
    """Same as _find_sr except raises a NotFound exception if SR cannot be
    determined
    """
    sr_ref = _find_sr(session)
    if sr_ref is None:
        raise exception.StorageRepositoryNotFound()
    return sr_ref


def _find_sr(session):
    """Return the storage repository to hold VM images."""
    host = session.get_xenapi_host()
    try:
        tokens = CONF.sr_matching_filter.split(':')
        filter_criteria = tokens[0]
        filter_pattern = tokens[1]
    except IndexError:
        # oops, flag is invalid
        LOG.warning(_("Flag sr_matching_filter '%s' does not respect "
                      "formatting convention"), CONF.sr_matching_filter)
        return None

    if filter_criteria == 'other-config':
        key, value = filter_pattern.split('=', 1)
        for sr_ref, sr_rec in session.get_all_refs_and_recs('SR'):
            if not (key in sr_rec['other_config'] and
                    sr_rec['other_config'][key] == value):
                continue
            for pbd_ref in sr_rec['PBDs']:
                pbd_rec = session.get_rec('PBD', pbd_ref)
                if pbd_rec and pbd_rec['host'] == host:
                    return sr_ref
    elif filter_criteria == 'default-sr' and filter_pattern == 'true':
        pool_ref = session.call_xenapi('pool.get_all')[0]
        return session.call_xenapi('pool.get_default_SR', pool_ref)
    # No SR found!
    LOG.warning(_("XenAPI is unable to find a Storage Repository to "
                  "install guest instances on. Please check your "
                  "configuration and/or configure the flag "
                  "'sr_matching_filter'"))
    return None


def _safe_find_iso_sr(session):
    """Same as _find_iso_sr except raises a NotFound exception if SR
    cannot be determined
    """
    sr_ref = _find_iso_sr(session)
    if sr_ref is None:
        raise exception.NotFound(_('Cannot find SR of content-type ISO'))
    return sr_ref


def _find_iso_sr(session):
    """Return the storage repository to hold ISO images."""
    host = session.get_xenapi_host()
    for sr_ref, sr_rec in session.get_all_refs_and_recs('SR'):
        LOG.debug(_("ISO: looking at SR %(sr_rec)s") % locals())
        if not sr_rec['content_type'] == 'iso':
            LOG.debug(_("ISO: not iso content"))
            continue
        if not 'i18n-key' in sr_rec['other_config']:
            LOG.debug(_("ISO: iso content_type, no 'i18n-key' key"))
            continue
        if not sr_rec['other_config']['i18n-key'] == 'local-storage-iso':
            LOG.debug(_("ISO: iso content_type, i18n-key value not "
                        "'local-storage-iso'"))
            continue

        LOG.debug(_("ISO: SR MATCHing our criteria"))
        for pbd_ref in sr_rec['PBDs']:
            LOG.debug(_("ISO: ISO, looking to see if it is host local"))
            pbd_rec = session.get_rec('PBD', pbd_ref)
            if not pbd_rec:
                LOG.debug(_("ISO: PBD %(pbd_ref)s disappeared") % locals())
                continue
            pbd_rec_host = pbd_rec['host']
            LOG.debug(_("ISO: PBD matching, want %(pbd_rec)s, "
                        "have %(host)s") % locals())
            if pbd_rec_host == host:
                LOG.debug(_("ISO: SR with local PBD"))
                return sr_ref
    return None


def _get_rrd_server():
    """Return server's scheme and address to use for retrieving RRD XMLs."""
    xs_url = urlparse.urlparse(CONF.xenapi_connection_url)
    return [xs_url.scheme, xs_url.netloc]


def _get_rrd(server, vm_uuid):
    """Return the VM RRD XML as a string."""
    try:
        xml = urllib.urlopen("%s://%s:%s@%s/vm_rrd?uuid=%s" % (
            server[0],
            CONF.xenapi_connection_username,
            CONF.xenapi_connection_password,
            server[1],
            vm_uuid))
        return xml.read()
    except IOError:
        LOG.exception(_('Unable to obtain RRD XML for VM %(vm_uuid)s with '
                        'server details: %(server)s.') % locals())
        return None


def _get_rrd_updates(server, start_time):
    """Return the RRD updates XML as a string."""
    try:
        xml = urllib.urlopen("%s://%s:%s@%s/rrd_updates?start=%s" % (
            server[0],
            CONF.xenapi_connection_username,
            CONF.xenapi_connection_password,
            server[1],
            start_time))
        return xml.read()
    except IOError:
        LOG.exception(_('Unable to obtain RRD XML updates with '
                        'server details: %(server)s.') % locals())
        return None


def _parse_rrd_meta(doc):
    data = {}
    meta = doc.getElementsByTagName('meta')[0]
    for tag in ('start', 'end', 'step'):
        data[tag] = int(meta.getElementsByTagName(tag)[0].firstChild.data)
    legend = meta.getElementsByTagName('legend')[0]
    data['legend'] = [child.firstChild.data for child in legend.childNodes]
    return data


def _parse_rrd_data(doc):
    dnode = doc.getElementsByTagName('data')[0]
    return [dict(
            time=int(child.getElementsByTagName('t')[0].firstChild.data),
            values=[decimal.Decimal(valnode.firstChild.data)
                  for valnode in child.getElementsByTagName('v')])
            for child in dnode.childNodes]


def _parse_rrd_update(doc, start, until=None):
    sum_data = {}
    meta = _parse_rrd_meta(doc)
    data = _parse_rrd_data(doc)
    for col, collabel in enumerate(meta['legend']):
        _datatype, _objtype, uuid, name = collabel.split(':')
        vm_data = sum_data.get(uuid, dict())
        if name.startswith('vif'):
            vm_data[name] = _integrate_series(data, col, start, until)
        else:
            vm_data[name] = _average_series(data, col, until)
        sum_data[uuid] = vm_data
    return sum_data


def _average_series(data, col, until=None):
    vals = [row['values'][col] for row in data
            if (not until or (row['time'] <= until)) and
                row['values'][col].is_finite()]
    if vals:
        try:
            return (sum(vals) / len(vals)).quantize(decimal.Decimal('1.0000'))
        except decimal.InvalidOperation:
            # (mdragon) Xenserver occasionally returns odd values in
            # data that will throw an error on averaging (see bug 918490)
            # These are hard to find, since, whatever those values are,
            # Decimal seems to think they are a valid number, sortof.
            # We *think* we've got the the cases covered, but just in
            # case, log and return NaN, so we don't break reporting of
            # other statistics.
            LOG.error(_("Invalid statistics data from Xenserver: %s")
                      % str(vals))
            return decimal.Decimal('NaN')
    else:
        return decimal.Decimal('0.0000')


def _integrate_series(data, col, start, until=None):
    total = decimal.Decimal('0.0000')
    prev_time = int(start)
    prev_val = None
    for row in reversed(data):
        if not until or (row['time'] <= until):
            time = row['time']
            val = row['values'][col]
            if val.is_nan():
                val = decimal.Decimal('0.0000')
            if prev_val is None:
                prev_val = val
            if prev_val >= val:
                total += ((val * (time - prev_time)) +
                          (decimal.Decimal('0.5000') * (prev_val - val) *
                          (time - prev_time)))
            else:
                total += ((prev_val * (time - prev_time)) +
                          (decimal.Decimal('0.5000') * (val - prev_val) *
                          (time - prev_time)))
            prev_time = time
            prev_val = val
    return total.quantize(decimal.Decimal('1.0000'))


def _get_all_vdis_in_sr(session, sr_ref):
    for vdi_ref in session.call_xenapi('SR.get_VDIs', sr_ref):
        try:
            vdi_rec = session.call_xenapi('VDI.get_record', vdi_ref)
            yield vdi_ref, vdi_rec
        except session.XenAPI.Failure:
            continue


def get_instance_vdis_for_sr(session, vm_ref, sr_ref):
    """Return opaqueRef for all the vdis which live on sr."""
    for vbd_ref in session.call_xenapi('VM.get_VBDs', vm_ref):
        try:
            vdi_ref = session.call_xenapi('VBD.get_VDI', vbd_ref)
            if sr_ref == session.call_xenapi('VDI.get_SR', vdi_ref):
                yield vdi_ref
        except session.XenAPI.Failure:
            continue


def _get_vhd_parent_uuid(session, vdi_ref):
    vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)

    if 'vhd-parent' not in vdi_rec['sm_config']:
        return None

    parent_uuid = vdi_rec['sm_config']['vhd-parent']
    vdi_uuid = vdi_rec['uuid']
    LOG.debug(_("VHD %(vdi_uuid)s has parent %(parent_uuid)s") % locals())
    return parent_uuid


def _walk_vdi_chain(session, vdi_uuid):
    """Yield vdi_recs for each element in a VDI chain."""
    scan_default_sr(session)
    while True:
        vdi_ref = session.call_xenapi("VDI.get_by_uuid", vdi_uuid)
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
        yield vdi_rec

        parent_uuid = _get_vhd_parent_uuid(session, vdi_ref)
        if not parent_uuid:
            break

        vdi_uuid = parent_uuid


def _child_vhds(session, sr_ref, vdi_uuid):
    """Return the immediate children of a given VHD.

    This is not recursive, only the immediate children are returned.
    """
    children = set()
    for ref, rec in _get_all_vdis_in_sr(session, sr_ref):
        rec_uuid = rec['uuid']

        if rec_uuid == vdi_uuid:
            continue

        parent_uuid = _get_vhd_parent_uuid(session, ref)
        if parent_uuid != vdi_uuid:
            continue

        children.add(rec_uuid)

    return children


def _wait_for_vhd_coalesce(session, instance, sr_ref, vdi_ref,
                           original_parent_uuid):
    """Spin until the parent VHD is coalesced into its parent VHD

    Before coalesce:
        * original_parent_vhd
            * parent_vhd
                snapshot

    After coalesce:
        * parent_vhd
            snapshot
    """
    def _another_child_vhd():
        if not original_parent_uuid:
            return False

        # Search for any other vdi which parents to original parent and is not
        # in the active vm/instance vdi chain.
        vdi_uuid = session.call_xenapi('VDI.get_record', vdi_ref)['uuid']
        parent_vdi_uuid = _get_vhd_parent_uuid(session, vdi_ref)
        for _ref, rec in _get_all_vdis_in_sr(session, sr_ref):
            if ((rec['uuid'] != vdi_uuid) and
               (rec['uuid'] != parent_vdi_uuid) and
               (rec['sm_config'].get('vhd-parent') == original_parent_uuid)):
                # Found another vhd which too parents to original parent.
                return True
        # Found no other vdi with the same parent.
        return False

    # Check if original parent has any other child. If so, coalesce will
    # not take place.
    if _another_child_vhd():
        parent_uuid = _get_vhd_parent_uuid(session, vdi_ref)
        parent_ref = session.call_xenapi("VDI.get_by_uuid", parent_uuid)
        base_uuid = _get_vhd_parent_uuid(session, parent_ref)
        return parent_uuid, base_uuid

    # NOTE(sirp): This rescan is necessary to ensure the VM's `sm_config`
    # matches the underlying VHDs.
    _scan_sr(session, sr_ref)

    max_attempts = CONF.xenapi_vhd_coalesce_max_attempts
    for i in xrange(max_attempts):
        _scan_sr(session, sr_ref)
        parent_uuid = _get_vhd_parent_uuid(session, vdi_ref)
        if original_parent_uuid and (parent_uuid != original_parent_uuid):
            LOG.debug(_("Parent %(parent_uuid)s doesn't match original parent"
                        " %(original_parent_uuid)s, waiting for coalesce..."),
                      locals(), instance=instance)
        else:
            parent_ref = session.call_xenapi("VDI.get_by_uuid", parent_uuid)
            base_uuid = _get_vhd_parent_uuid(session, parent_ref)
            return parent_uuid, base_uuid

        greenthread.sleep(CONF.xenapi_vhd_coalesce_poll_interval)

    msg = (_("VHD coalesce attempts exceeded (%(max_attempts)d)"
             ", giving up...") % locals())
    raise exception.NovaException(msg)


def _remap_vbd_dev(dev):
    """Return the appropriate location for a plugged-in VBD device

    Ubuntu Maverick moved xvd? -> sd?. This is considered a bug and will be
    fixed in future versions:
        https://bugs.launchpad.net/ubuntu/+source/linux/+bug/684875

    For now, we work around it by just doing a string replace.
    """
    # NOTE(sirp): This hack can go away when we pull support for Maverick
    should_remap = CONF.xenapi_remap_vbd_dev
    if not should_remap:
        return dev

    old_prefix = 'xvd'
    new_prefix = CONF.xenapi_remap_vbd_dev_prefix
    remapped_dev = dev.replace(old_prefix, new_prefix)

    return remapped_dev


def _wait_for_device(dev):
    """Wait for device node to appear."""
    for i in xrange(0, CONF.block_device_creation_timeout):
        dev_path = utils.make_dev_path(dev)
        if os.path.exists(dev_path):
            return
        time.sleep(1)

    raise volume_utils.StorageError(
        _('Timeout waiting for device %s to be created') % dev)


def cleanup_attached_vdis(session):
    """Unplug any instance VDIs left after an unclean restart."""
    this_vm_ref = _get_this_vm_ref(session)

    vbd_refs = session.call_xenapi('VM.get_VBDs', this_vm_ref)
    for vbd_ref in vbd_refs:
        try:
            vbd_rec = session.call_xenapi('VBD.get_record', vbd_ref)
            vdi_rec = session.call_xenapi('VDI.get_record', vbd_rec['VDI'])
        except session.XenAPI.Failure, e:
            if e.details[0] != 'HANDLE_INVALID':
                raise
            continue

        if 'nova_instance_uuid' in vdi_rec['other_config']:
            # Belongs to an instance and probably left over after an
            # unclean restart
            LOG.info(_('Disconnecting stale VDI %s from compute domU'),
                     vdi_rec['uuid'])
            unplug_vbd(session, vbd_ref)
            destroy_vbd(session, vbd_ref)


@contextlib.contextmanager
def vdi_attached_here(session, vdi_ref, read_only=False):
    this_vm_ref = _get_this_vm_ref(session)

    vbd_ref = create_vbd(session, this_vm_ref, vdi_ref, 'autodetect',
                         read_only=read_only, bootable=False)
    try:
        LOG.debug(_('Plugging VBD %s ... '), vbd_ref)
        session.call_xenapi("VBD.plug", vbd_ref)
        try:
            LOG.debug(_('Plugging VBD %s done.'), vbd_ref)
            orig_dev = session.call_xenapi("VBD.get_device", vbd_ref)
            LOG.debug(_('VBD %(vbd_ref)s plugged as %(orig_dev)s') % locals())
            dev = _remap_vbd_dev(orig_dev)
            if dev != orig_dev:
                LOG.debug(_('VBD %(vbd_ref)s plugged into wrong dev, '
                            'remapping to %(dev)s') % locals())
            _wait_for_device(dev)
            yield dev
        finally:
            LOG.debug(_('Destroying VBD for VDI %s ... '), vdi_ref)
            unplug_vbd(session, vbd_ref)
    finally:
        try:
            destroy_vbd(session, vbd_ref)
        except volume_utils.StorageError:
            # destroy_vbd() will log error
            pass
        LOG.debug(_('Destroying VBD for VDI %s done.'), vdi_ref)


def get_this_vm_uuid():
    with file('/sys/hypervisor/uuid') as f:
        return f.readline().strip()


def _get_this_vm_ref(session):
    return session.call_xenapi("VM.get_by_uuid", get_this_vm_uuid())


def _is_vdi_pv(dev):
    LOG.debug(_("Running pygrub against %s"), dev)
    dev_path = utils.make_dev_path(dev)
    try:
        out, err = utils.execute('pygrub', '-qn', dev_path, run_as_root=True)
        for line in out:
            # try to find kernel string
            m = re.search('(?<=kernel:)/.*(?:>)', line)
            if m and m.group(0).find('xen') != -1:
                LOG.debug(_("Found Xen kernel %s") % m.group(0))
                return True
        LOG.debug(_("No Xen kernel found.  Booting HVM."))
    except exception.ProcessExecutionError:
        LOG.exception(_("Error while executing pygrub! Please, ensure the "
                        "binary is installed correctly, and available in your "
                        "PATH; on some Linux distros, pygrub may be installed "
                        "in /usr/lib/xen-X.Y/bin/pygrub. Attempting to boot "
                        "in HVM mode."))
    return False


def _get_partitions(dev):
    """Return partition information (num, size, type) for a device."""
    dev_path = utils.make_dev_path(dev)
    out, _err = utils.execute('parted', '--script', '--machine',
                             dev_path, 'unit s', 'print',
                             run_as_root=True)
    lines = [line for line in out.split('\n') if line]
    partitions = []

    LOG.debug(_("Partitions:"))
    for line in lines[2:]:
        num, start, end, size, ptype = line.split(':')[:5]
        start = int(start.rstrip('s'))
        end = int(end.rstrip('s'))
        size = int(size.rstrip('s'))
        LOG.debug(_("  %(num)s: %(ptype)s %(size)d sectors") % locals())
        partitions.append((num, start, size, ptype))

    return partitions


def _stream_disk(image_service_func, image_type, virtual_size, dev):
    offset = 0
    if image_type == ImageType.DISK:
        offset = MBR_SIZE_BYTES
        _write_partition(virtual_size, dev)

    dev_path = utils.make_dev_path(dev)

    with utils.temporary_chown(dev_path):
        with open(dev_path, 'wb') as f:
            f.seek(offset)
            image_service_func(f)


def _write_partition(virtual_size, dev):
    dev_path = utils.make_dev_path(dev)
    primary_first = MBR_SIZE_SECTORS
    primary_last = MBR_SIZE_SECTORS + (virtual_size / SECTOR_SIZE) - 1

    LOG.debug(_('Writing partition table %(primary_first)d %(primary_last)d'
                ' to %(dev_path)s...'), locals())

    def execute(*cmd, **kwargs):
        return utils.execute(*cmd, **kwargs)

    execute('parted', '--script', dev_path, 'mklabel', 'msdos',
            run_as_root=True)
    execute('parted', '--script', dev_path, 'mkpart', 'primary',
            '%ds' % primary_first,
            '%ds' % primary_last,
            run_as_root=True)

    LOG.debug(_('Writing partition table %s done.'), dev_path)


def _resize_part_and_fs(dev, start, old_sectors, new_sectors):
    """Resize partition and fileystem.

    This assumes we are dealing with a single primary partition and using
    ext3 or ext4.
    """
    size = new_sectors - start
    end = new_sectors - 1

    dev_path = utils.make_dev_path(dev)
    partition_path = utils.make_dev_path(dev, partition=1)

    # Replay journal if FS wasn't cleanly unmounted
    # Exit Code 1 = File system errors corrected
    #           2 = File system errors corrected, system needs a reboot
    utils.execute('e2fsck', '-f', '-y', partition_path, run_as_root=True,
                  check_exit_code=[0, 1, 2])

    # Remove ext3 journal (making it ext2)
    utils.execute('tune2fs', '-O ^has_journal', partition_path,
                  run_as_root=True)

    if new_sectors < old_sectors:
        # Resizing down, resize filesystem before partition resize
        utils.execute('resize2fs', partition_path, '%ds' % size,
                      run_as_root=True)

    utils.execute('parted', '--script', dev_path, 'rm', '1',
                  run_as_root=True)
    utils.execute('parted', '--script', dev_path, 'mkpart',
                  'primary',
                  '%ds' % start,
                  '%ds' % end,
                  run_as_root=True)

    if new_sectors > old_sectors:
        # Resizing up, resize filesystem after partition resize
        utils.execute('resize2fs', partition_path, run_as_root=True)

    # Add back journal
    utils.execute('tune2fs', '-j', partition_path, run_as_root=True)


def _sparse_copy(src_path, dst_path, virtual_size, block_size=4096):
    """Copy data, skipping long runs of zeros to create a sparse file."""
    start_time = time.time()
    EMPTY_BLOCK = '\0' * block_size
    bytes_read = 0
    skipped_bytes = 0
    left = virtual_size

    LOG.debug(_("Starting sparse_copy src=%(src_path)s dst=%(dst_path)s "
                "virtual_size=%(virtual_size)d block_size=%(block_size)d"),
              locals())

    # NOTE(sirp): we need read/write access to the devices; since we don't have
    # the luxury of shelling out to a sudo'd command, we temporarily take
    # ownership of the devices.
    with utils.temporary_chown(src_path):
        with utils.temporary_chown(dst_path):
            with open(src_path, "r") as src:
                with open(dst_path, "w") as dst:
                    data = src.read(min(block_size, left))
                    while data:
                        if data == EMPTY_BLOCK:
                            dst.seek(block_size, os.SEEK_CUR)
                            left -= block_size
                            bytes_read += block_size
                            skipped_bytes += block_size
                        else:
                            dst.write(data)
                            data_len = len(data)
                            left -= data_len
                            bytes_read += data_len

                        if left <= 0:
                            break

                        data = src.read(min(block_size, left))

    duration = time.time() - start_time
    compression_pct = float(skipped_bytes) / bytes_read * 100

    LOG.debug(_("Finished sparse_copy in %(duration).2f secs, "
                "%(compression_pct).2f%% reduction in size"), locals())


def _copy_partition(session, src_ref, dst_ref, partition, virtual_size):
    # Part of disk taken up by MBR
    virtual_size -= MBR_SIZE_BYTES

    with vdi_attached_here(session, src_ref, read_only=True) as src:
        src_path = utils.make_dev_path(src, partition=partition)

        with vdi_attached_here(session, dst_ref, read_only=False) as dst:
            dst_path = utils.make_dev_path(dst, partition=partition)

            _write_partition(virtual_size, dst)

            if CONF.xenapi_sparse_copy:
                _sparse_copy(src_path, dst_path, virtual_size)
            else:
                num_blocks = virtual_size / SECTOR_SIZE
                utils.execute('dd',
                              'if=%s' % src_path,
                              'of=%s' % dst_path,
                              'count=%d' % num_blocks,
                              run_as_root=True)


def _mount_filesystem(dev_path, dir):
    """mounts the device specified by dev_path in dir."""
    try:
        _out, err = utils.execute('mount',
                                 '-t', 'ext2,ext3,ext4,reiserfs',
                                 dev_path, dir, run_as_root=True)
    except exception.ProcessExecutionError as e:
        err = str(e)
    return err


def _mounted_processing(device, key, net, metadata):
    """Callback which runs with the image VDI attached."""
    # NB: Partition 1 hardcoded
    dev_path = utils.make_dev_path(device, partition=1)
    with utils.tempdir() as tmpdir:
        # Mount only Linux filesystems, to avoid disturbing NTFS images
        err = _mount_filesystem(dev_path, tmpdir)
        if not err:
            try:
                # This try block ensures that the umount occurs
                if not agent.find_guest_agent(tmpdir):
                    vfs = vfsimpl.VFSLocalFS(imgfile=None,
                                             imgfmt=None,
                                             imgdir=tmpdir)
                    LOG.info(_('Manipulating interface files directly'))
                    # for xenapi, we don't 'inject' admin_password here,
                    # it's handled at instance startup time, nor do we
                    # support injecting arbitrary files here.
                    disk.inject_data_into_fs(vfs,
                                             key, net, metadata, None, None)
            finally:
                utils.execute('umount', dev_path, run_as_root=True)
        else:
            LOG.info(_('Failed to mount filesystem (expected for '
                       'non-linux instances): %s') % err)


def _prepare_injectables(inst, network_info):
    """
    prepares the ssh key and the network configuration file to be
    injected into the disk image
    """
    #do the import here - Cheetah.Template will be loaded
    #only if injection is performed
    from Cheetah import Template as t
    template = t.Template
    template_data = open(CONF.injected_network_template).read()

    metadata = inst['metadata']
    key = str(inst['key_data'])
    net = None
    if network_info:
        ifc_num = -1
        interfaces_info = []
        for vif in network_info:
            ifc_num += 1
            try:
                if not vif['network'].get_meta('injected'):
                    # network is not specified injected
                    continue
            except KeyError:
                # vif network is None
                continue

            # NOTE(tr3buchet): using all subnets in case dns is stored in a
            #                  subnet that isn't chosen as first v4 or v6
            #                  subnet in the case where there is more than one
            # dns = list of address of each dns entry from each vif subnet
            dns = [ip['address'] for subnet in vif['network']['subnets']
                                 for ip in subnet['dns']]
            dns = ' '.join(dns).strip()

            interface_info = {'name': 'eth%d' % ifc_num,
                              'address': '',
                              'netmask': '',
                              'gateway': '',
                              'broadcast': '',
                              'dns': dns or '',
                              'address_v6': '',
                              'netmask_v6': '',
                              'gateway_v6': '',
                              'use_ipv6': CONF.use_ipv6}

            # NOTE(tr3buchet): the original code used the old network_info
            #                  which only supported a single ipv4 subnet
            #                  (and optionally, a single ipv6 subnet).
            #                  I modified it to use the new network info model,
            #                  which adds support for multiple v4 or v6
            #                  subnets. I chose to ignore any additional
            #                  subnets, just as the original code ignored
            #                  additional IP information

            # populate v4 info if v4 subnet and ip exist
            try:
                # grab the first v4 subnet (or it raises)
                subnet = [s for s in vif['network']['subnets']
                            if s['version'] == 4][0]
                # get the subnet's first ip (or it raises)
                ip = subnet['ips'][0]

                # populate interface_info
                subnet_netaddr = subnet.as_netaddr()
                interface_info['address'] = ip['address']
                interface_info['netmask'] = subnet_netaddr.netmask
                interface_info['gateway'] = subnet['gateway']['address']
                interface_info['broadcast'] = subnet_netaddr.broadcast
            except IndexError:
                # there isn't a v4 subnet or there are no ips
                pass

            # populate v6 info if v6 subnet and ip exist
            try:
                # grab the first v6 subnet (or it raises)
                subnet = [s for s in vif['network']['subnets']
                            if s['version'] == 6][0]
                # get the subnet's first ip (or it raises)
                ip = subnet['ips'][0]

                # populate interface_info
                interface_info['address_v6'] = ip['address']
                interface_info['netmask_v6'] = subnet.as_netaddr().netmask
                interface_info['gateway_v6'] = subnet['gateway']['address']
            except IndexError:
                # there isn't a v6 subnet or there are no ips
                pass

            interfaces_info.append(interface_info)

        if interfaces_info:
            net = str(template(template_data,
                                searchList=[{'interfaces': interfaces_info,
                                            'use_ipv6': CONF.use_ipv6}]))
    return key, net, metadata


def ensure_correct_host(session):
    """Ensure we're connected to the host we're running on. This is the
    required configuration for anything that uses vdi_attached_here."""
    this_vm_uuid = get_this_vm_uuid()

    try:
        session.call_xenapi('VM.get_by_uuid', this_vm_uuid)
    except session.XenAPI.Failure as exc:
        if exc.details[0] != 'UUID_INVALID':
            raise
        raise Exception(_('This domU must be running on the host '
                          'specified by xenapi_connection_url'))


def move_disks(session, instance, disk_info):
    """Move and possibly link VHDs via the XAPI plugin."""
    imported_vhds = session.call_plugin_serialized(
            'migration', 'move_vhds_into_sr', instance_uuid=instance['uuid'],
            sr_path=get_sr_path(session), uuid_stack=_make_uuid_stack())

    # Now we rescan the SR so we find the VHDs
    scan_default_sr(session)

    # Set name-label so we can find if we need to clean up a failed
    # migration
    root_uuid = imported_vhds['root']['uuid']
    set_vdi_name(session, root_uuid, instance['name'], 'root')

    root_vdi_ref = session.call_xenapi('VDI.get_by_uuid', root_uuid)

    return {'uuid': root_uuid, 'ref': root_vdi_ref}


def vm_ref_or_raise(session, instance_name):
    vm_ref = lookup(session, instance_name)
    if vm_ref is None:
        raise exception.InstanceNotFound(instance_id=instance_name)
    return vm_ref
