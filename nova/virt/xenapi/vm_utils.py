# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 OpenStack Foundation
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
import math
import os
import time
import urllib
from xml.dom import minidom
from xml.parsers import expat

from eventlet import greenthread
from os_xenapi.client import disk_management
from os_xenapi.client import host_network
from os_xenapi.client import vm_management
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
from oslo_utils import uuidutils
from oslo_utils import versionutils
import six
from six.moves import range
import six.moves.urllib.parse as urlparse

from nova.api.metadata import base as instance_metadata
from nova.compute import power_state
from nova.compute import task_states
import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova.objects import diagnostics
from nova.objects import fields as obj_fields
from nova import utils
from nova.virt import configdrive
from nova.virt.disk import api as disk
from nova.virt.disk.vfs import localfs as vfsimpl
from nova.virt import hardware
from nova.virt.image import model as imgmodel
from nova.virt import netutils
from nova.virt.xenapi import agent
from nova.virt.xenapi.image import utils as image_utils
from nova.virt.xenapi import volume_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

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
PROGRESS_INTERVAL_SECONDS = 300
DD_BLOCKSIZE = 65536

# Fudge factor to allow for the VHD chain to be slightly larger than
# the partitioned space. Otherwise, legitimate images near their
# maximum allowed size can fail on build with FlavorDiskSmallerThanImage.
VHD_SIZE_CHECK_FUDGE_FACTOR_GB = 10


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
        return dict(zip(cls._ids, ImageType._strs)).get(image_type)

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


def get_vm_device_id(session, image_meta):
    # NOTE: device_id should be 2 for windows VMs which run new xentools
    # (>=6.1). Refer to http://support.citrix.com/article/CTX135099 for more
    # information.
    device_id = image_meta.properties.get('hw_device_id')

    # The device_id is required to be set for hypervisor version 6.1 and above
    if device_id:
        hypervisor_version = session.product_version
        if _hypervisor_supports_device_id(hypervisor_version):
            return device_id
        else:
            msg = _("Device id %(id)s specified is not supported by "
                    "hypervisor version %(version)s") % {'id': device_id,
                    'version': hypervisor_version}
            raise exception.NovaException(msg)


def _hypervisor_supports_device_id(version):
    version_as_string = '.'.join(str(v) for v in version)
    return versionutils.is_compatible('6.1', version_as_string)


def create_vm(session, instance, name_label, kernel, ramdisk,
              use_pv_kernel=False, device_id=None):
    """Create a VM record.  Returns new VM reference.
    the use_pv_kernel flag indicates whether the guest is HVM or PV

    There are 3 scenarios:

        1. Using paravirtualization, kernel passed in

        2. Using paravirtualization, kernel within the image

        3. Using hardware virtualization
    """
    flavor = instance.get_flavor()
    mem = str(int(flavor.memory_mb) * units.Mi)
    vcpus = str(flavor.vcpus)

    vcpu_weight = flavor.vcpu_weight
    vcpu_params = {}
    if vcpu_weight is not None:
        # NOTE(johngarbutt) bug in XenServer 6.1 and 6.2 means
        # we need to specify both weight and cap for either to apply
        vcpu_params = {"weight": str(vcpu_weight), "cap": "0"}

    cpu_mask_list = hardware.get_vcpu_pin_set()
    if cpu_mask_list:
        cpu_mask = hardware.format_cpu_spec(cpu_mask_list,
                                            allow_ranges=False)
        vcpu_params["mask"] = cpu_mask

    viridian = 'true' if instance['os_type'] == 'windows' else 'false'

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
        'other_config': {'nova_uuid': str(instance['uuid'])},
        'PCI_bus': '',
        'platform': {'acpi': 'true', 'apic': 'true', 'pae': 'true',
                     'viridian': viridian, 'timeoffset': '0'},
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
        'VCPUs_params': vcpu_params,
        'xenstore_data': {'vm-data/allowvssprovider': 'false'}}

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

    if device_id:
        rec['platform']['device_id'] = str(device_id).zfill(4)

    vm_ref = session.VM.create(rec)
    LOG.debug('Created VM', instance=instance)
    return vm_ref


def destroy_vm(session, instance, vm_ref):
    """Destroys a VM record."""
    try:
        session.VM.destroy(vm_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Destroy VM failed'))
        return

    LOG.debug("VM destroyed", instance=instance)


def clean_shutdown_vm(session, instance, vm_ref):
    if is_vm_shutdown(session, vm_ref):
        LOG.warning("VM already halted, skipping shutdown...",
                    instance=instance)
        return True

    LOG.debug("Shutting down VM (cleanly)", instance=instance)
    try:
        session.call_xenapi('VM.clean_shutdown', vm_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Shutting down VM (cleanly) failed.'))
        return False
    return True


def hard_shutdown_vm(session, instance, vm_ref):
    if is_vm_shutdown(session, vm_ref):
        LOG.warning("VM already halted, skipping shutdown...",
                    instance=instance)
        return True

    LOG.debug("Shutting down VM (hard)", instance=instance)
    try:
        session.call_xenapi('VM.hard_shutdown', vm_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Shutting down VM (hard) failed'))
        return False
    return True


def is_vm_shutdown(session, vm_ref):
    state = get_power_state(session, vm_ref)
    if state == power_state.SHUTDOWN:
        return True
    return False


def is_enough_free_mem(session, instance):
    flavor = instance.get_flavor()
    mem = int(flavor.memory_mb) * units.Mi
    host_free_mem = int(session.call_xenapi("host.compute_free_memory",
                                            session.host_ref))
    return host_free_mem >= mem


def _should_retry_unplug_vbd(err):
    # Retry if unplug failed with DEVICE_DETACH_REJECTED
    # For reasons which we don't understand,
    # we're seeing the device still in use, even when all processes
    # using the device should be dead.
    # Since XenServer 6.2, we also need to retry if we get
    # INTERNAL_ERROR, as that error goes away when you retry.
    return (err == 'DEVICE_DETACH_REJECTED'
            or
            err == 'INTERNAL_ERROR')


def unplug_vbd(session, vbd_ref, this_vm_ref):
    # make sure that perform at least once
    max_attempts = max(0, CONF.xenserver.num_vbd_unplug_retries) + 1
    for num_attempt in range(1, max_attempts + 1):
        try:
            if num_attempt > 1:
                greenthread.sleep(1)

            session.VBD.unplug(vbd_ref, this_vm_ref)
            return
        except session.XenAPI.Failure as exc:
            err = len(exc.details) > 0 and exc.details[0]
            if err == 'DEVICE_ALREADY_DETACHED':
                LOG.info('VBD %s already detached', vbd_ref)
                return
            elif _should_retry_unplug_vbd(err):
                LOG.info('VBD %(vbd_ref)s unplug failed with "%(err)s", '
                         'attempt %(num_attempt)d/%(max_attempts)d',
                         {'vbd_ref': vbd_ref, 'num_attempt': num_attempt,
                          'max_attempts': max_attempts, 'err': err})
            else:
                LOG.exception(_('Unable to unplug VBD'))
                raise exception.StorageError(
                        reason=_('Unable to unplug VBD %s') % vbd_ref)

    raise exception.StorageError(
            reason=_('Reached maximum number of retries '
                     'trying to unplug VBD %s')
                        % vbd_ref)


def destroy_vbd(session, vbd_ref):
    """Destroy VBD from host database."""
    try:
        session.call_xenapi('VBD.destroy', vbd_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to destroy VBD'))
        raise exception.StorageError(
                reason=_('Unable to destroy VBD %s') % vbd_ref)


def create_vbd(session, vm_ref, vdi_ref, userdevice, vbd_type='disk',
               read_only=False, bootable=False, osvol=False,
               empty=False, unpluggable=True):
    """Create a VBD record and returns its reference."""
    vbd_rec = {}
    vbd_rec['VM'] = vm_ref
    if vdi_ref is None:
        vdi_ref = 'OpaqueRef:NULL'
    vbd_rec['VDI'] = vdi_ref
    vbd_rec['userdevice'] = str(userdevice)
    vbd_rec['bootable'] = bootable
    vbd_rec['mode'] = read_only and 'RO' or 'RW'
    vbd_rec['type'] = vbd_type
    vbd_rec['unpluggable'] = unpluggable
    vbd_rec['empty'] = empty
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    LOG.debug('Creating %(vbd_type)s-type VBD for VM %(vm_ref)s,'
              ' VDI %(vdi_ref)s ... ',
              {'vbd_type': vbd_type, 'vm_ref': vm_ref, 'vdi_ref': vdi_ref})
    vbd_ref = session.call_xenapi('VBD.create', vbd_rec)
    LOG.debug('Created VBD %(vbd_ref)s for VM %(vm_ref)s,'
              ' VDI %(vdi_ref)s.',
              {'vbd_ref': vbd_ref, 'vm_ref': vm_ref, 'vdi_ref': vdi_ref})
    if osvol:
        # set osvol=True in other-config to indicate this is an
        # attached nova (or cinder) volume
        session.call_xenapi('VBD.add_to_other_config',
                            vbd_ref, 'osvol', 'True')
    return vbd_ref


def attach_cd(session, vm_ref, vdi_ref, userdevice):
    """Create an empty VBD, then insert the CD."""
    vbd_ref = create_vbd(session, vm_ref, None, userdevice,
                         vbd_type='cd', read_only=True,
                         bootable=True, empty=True,
                         unpluggable=False)
    session.call_xenapi('VBD.insert', vbd_ref, vdi_ref)
    return vbd_ref


def destroy_vdi(session, vdi_ref):
    try:
        session.call_xenapi('VDI.destroy', vdi_ref)
    except session.XenAPI.Failure:
        LOG.debug("Unable to destroy VDI %s", vdi_ref, exc_info=True)
        msg = _("Unable to destroy VDI %s") % vdi_ref
        LOG.error(msg)
        raise exception.StorageError(reason=msg)


def safe_destroy_vdis(session, vdi_refs):
    """Tries to destroy the requested VDIs, but ignores any errors."""
    for vdi_ref in vdi_refs:
        try:
            destroy_vdi(session, vdi_ref)
        except exception.StorageError:
            LOG.debug("Ignoring error while destroying VDI: %s", vdi_ref)


def create_vdi(session, sr_ref, instance, name_label, disk_type, virtual_size,
               read_only=False):
    """Create a VDI record and returns its reference."""
    vdi_ref = session.call_xenapi("VDI.create",
         {'name_label': name_label,
          'name_description': disk_type,
          'SR': sr_ref,
          'virtual_size': str(virtual_size),
          'type': 'User',
          'sharable': False,
          'read_only': read_only,
          'xenstore_data': {},
          'other_config': _get_vdi_other_config(disk_type, instance=instance),
          'sm_config': {},
          'tags': []})
    LOG.debug('Created VDI %(vdi_ref)s (%(name_label)s,'
              ' %(virtual_size)s, %(read_only)s) on %(sr_ref)s.',
              {'vdi_ref': vdi_ref, 'name_label': name_label,
               'virtual_size': virtual_size, 'read_only': read_only,
               'sr_ref': sr_ref})
    return vdi_ref


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
            except exception.StorageError:
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
            sr_path = get_sr_path(session, sr_ref=sr_ref)
            uuid_stack = _make_uuid_stack()
            imported_vhds = disk_management.safe_copy_vdis(
                session, sr_path, vdi_uuids, uuid_stack)
    root_uuid = imported_vhds['root']['uuid']

    # rescan to discover new VHDs
    scan_default_sr(session)
    vdi_ref = session.call_xenapi('VDI.get_by_uuid', root_uuid)
    return vdi_ref


def _clone_vdi(session, vdi_to_clone_ref):
    """Clones a VDI and return the new VDIs reference."""
    vdi_ref = session.call_xenapi('VDI.clone', vdi_to_clone_ref)
    LOG.debug('Cloned VDI %(vdi_ref)s from VDI '
              '%(vdi_to_clone_ref)s',
              {'vdi_ref': vdi_ref, 'vdi_to_clone_ref': vdi_to_clone_ref})
    return vdi_ref


def _get_vdi_other_config(disk_type, instance=None):
    """Return metadata to store in VDI's other_config attribute.

    `nova_instance_uuid` is used to associate a VDI with a particular instance
    so that, if it becomes orphaned from an unclean shutdown of a
    compute-worker, we can safely detach it.
    """
    other_config = {'nova_disk_type': disk_type}

    # create_vdi may be called simply while creating a volume
    # hence information about instance may or may not be present
    if instance:
        other_config['nova_instance_uuid'] = instance['uuid']

    return other_config


def _set_vdi_info(session, vdi_ref, vdi_type, name_label, description,
                  instance):
    existing_other_config = session.call_xenapi('VDI.get_other_config',
                                                vdi_ref)

    session.call_xenapi('VDI.set_name_label', vdi_ref, name_label)
    session.call_xenapi('VDI.set_name_description', vdi_ref, description)

    other_config = _get_vdi_other_config(vdi_type, instance=instance)
    for key, value in other_config.items():
        if key not in existing_other_config:
            session.call_xenapi(
                    "VDI.add_to_other_config", vdi_ref, key, value)


def _vm_get_vbd_refs(session, vm_ref):
    return session.call_xenapi("VM.get_VBDs", vm_ref)


def _vbd_get_rec(session, vbd_ref):
    return session.call_xenapi("VBD.get_record", vbd_ref)


def _vdi_get_rec(session, vdi_ref):
    return session.call_xenapi("VDI.get_record", vdi_ref)


def _vdi_get_uuid(session, vdi_ref):
    return session.call_xenapi("VDI.get_uuid", vdi_ref)


def _vdi_snapshot(session, vdi_ref):
    return session.call_xenapi("VDI.snapshot", vdi_ref, {})


def get_vdi_for_vm_safely(session, vm_ref, userdevice='0'):
    """Retrieves the primary VDI for a VM."""
    vbd_refs = _vm_get_vbd_refs(session, vm_ref)
    for vbd_ref in vbd_refs:
        vbd_rec = _vbd_get_rec(session, vbd_ref)
        # Convention dictates the primary VDI will be userdevice 0
        if vbd_rec['userdevice'] == userdevice:
            vdi_ref = vbd_rec['VDI']
            vdi_rec = _vdi_get_rec(session, vdi_ref)
            return vdi_ref, vdi_rec
    raise exception.NovaException(_("No primary VDI found for %s") % vm_ref)


def get_all_vdi_uuids_for_vm(session, vm_ref, min_userdevice=0):
    vbd_refs = _vm_get_vbd_refs(session, vm_ref)
    for vbd_ref in vbd_refs:
        vbd_rec = _vbd_get_rec(session, vbd_ref)
        if int(vbd_rec['userdevice']) >= min_userdevice:
            vdi_ref = vbd_rec['VDI']
            yield _vdi_get_uuid(session, vdi_ref)


def _try_strip_base_mirror_from_vdi(session, vdi_ref):
    try:
        session.call_xenapi("VDI.remove_from_sm_config", vdi_ref,
                            "base_mirror")
    except session.XenAPI.Failure:
        LOG.debug("Error while removing sm_config", exc_info=True)


def strip_base_mirror_from_vdis(session, vm_ref):
    # NOTE(johngarbutt) part of workaround for XenServer bug CA-98606
    vbd_refs = session.call_xenapi("VM.get_VBDs", vm_ref)
    for vbd_ref in vbd_refs:
        vdi_ref = session.call_xenapi("VBD.get_VDI", vbd_ref)
        _try_strip_base_mirror_from_vdi(session, vdi_ref)


def _delete_snapshots_in_vdi_chain(session, instance, vdi_uuid_chain, sr_ref):
    possible_snapshot_parents = vdi_uuid_chain[1:]

    if len(possible_snapshot_parents) == 0:
        LOG.debug("No VHD chain.", instance=instance)
        return

    snapshot_uuids = _child_vhds(session, sr_ref, possible_snapshot_parents,
                                 old_snapshots_only=True)
    number_of_snapshots = len(snapshot_uuids)

    if number_of_snapshots <= 0:
        LOG.debug("No snapshots to remove.", instance=instance)
        return

    vdi_refs = [session.VDI.get_by_uuid(vdi_uuid)
                for vdi_uuid in snapshot_uuids]
    safe_destroy_vdis(session, vdi_refs)

    # ensure garbage collector has been run
    _scan_sr(session, sr_ref)

    LOG.info("Deleted %s snapshots.", number_of_snapshots, instance=instance)


def remove_old_snapshots(session, instance, vm_ref):
    """See if there is an snapshot present that should be removed."""
    LOG.debug("Starting remove_old_snapshots for VM", instance=instance)
    vm_vdi_ref, vm_vdi_rec = get_vdi_for_vm_safely(session, vm_ref)
    chain = _walk_vdi_chain(session, vm_vdi_rec['uuid'])
    vdi_uuid_chain = [vdi_rec['uuid'] for vdi_rec in chain]
    sr_ref = vm_vdi_rec["SR"]
    _delete_snapshots_in_vdi_chain(session, instance, vdi_uuid_chain, sr_ref)


@contextlib.contextmanager
def snapshot_attached_here(session, instance, vm_ref, label, userdevice='0',
                           post_snapshot_callback=None):
    # impl method allow easier patching for tests
    return _snapshot_attached_here_impl(session, instance, vm_ref, label,
                                        userdevice, post_snapshot_callback)


def _snapshot_attached_here_impl(session, instance, vm_ref, label, userdevice,
                                 post_snapshot_callback):
    """Snapshot the root disk only.  Return a list of uuids for the vhds
    in the chain.
    """
    LOG.debug("Starting snapshot for VM", instance=instance)

    # Memorize the VDI chain so we can poll for coalesce
    vm_vdi_ref, vm_vdi_rec = get_vdi_for_vm_safely(session, vm_ref,
                                                   userdevice)
    chain = _walk_vdi_chain(session, vm_vdi_rec['uuid'])
    vdi_uuid_chain = [vdi_rec['uuid'] for vdi_rec in chain]
    sr_ref = vm_vdi_rec["SR"]

    # clean up after any interrupted snapshot attempts
    _delete_snapshots_in_vdi_chain(session, instance, vdi_uuid_chain, sr_ref)

    snapshot_ref = _vdi_snapshot(session, vm_vdi_ref)
    if post_snapshot_callback is not None:
        post_snapshot_callback(task_state=task_states.IMAGE_PENDING_UPLOAD)
    try:
        # When the VDI snapshot is taken a new parent is introduced.
        # If we have taken a snapshot before, the new parent can be coalesced.
        # We need to wait for this to happen before trying to copy the chain.
        _wait_for_vhd_coalesce(session, instance, sr_ref, vm_vdi_ref,
                               vdi_uuid_chain)

        snapshot_uuid = _vdi_get_uuid(session, snapshot_ref)
        chain = _walk_vdi_chain(session, snapshot_uuid)
        vdi_uuids = [vdi_rec['uuid'] for vdi_rec in chain]
        yield vdi_uuids
    finally:
        safe_destroy_vdis(session, [snapshot_ref])
        # TODO(johngarbut) we need to check the snapshot has been coalesced
        # now its associated VDI has been deleted.


def get_sr_path(session, sr_ref=None):
    """Return the path to our storage repository

    This is used when we're dealing with VHDs directly, either by taking
    snapshots or by restoring an image in the DISK_VHD format.
    """
    if sr_ref is None:
        sr_ref = safe_find_sr(session)
    pbd_rec = session.call_xenapi("PBD.get_all_records_where",
                                  'field "host"="%s" and '
                                  'field "SR"="%s"' %
                                  (session.host_ref, sr_ref))

    # NOTE(bobball): There can only be one PBD for a host/SR pair, but path is
    # not always present - older versions of XS do not set it.
    pbd_ref = list(pbd_rec.keys())[0]
    device_config = pbd_rec[pbd_ref]['device_config']
    if 'path' in device_config:
        return device_config['path']

    sr_rec = session.call_xenapi("SR.get_record", sr_ref)
    sr_uuid = sr_rec["uuid"]
    if sr_rec["type"] not in ["ext", "nfs"]:
        raise exception.NovaException(
            _("Only file-based SRs (ext/NFS) are supported by this feature."
              "  SR %(uuid)s is of type %(type)s") %
            {"uuid": sr_uuid, "type": sr_rec["type"]})

    return os.path.join(CONF.xenserver.sr_base_path, sr_uuid)


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
        LOG.debug("Destroying cached VDI '%(vdi_uuid)s'")
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
            children = _child_vhds(session, sr_ref, [root_vdi_rec['uuid']])
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
    name_label = _get_image_vdi_label(image_id)
    recs = session.call_xenapi("VDI.get_all_records_where",
                               'field "name__label"="%s"'
                               % name_label)
    number_found = len(recs)
    if number_found > 0:
        if number_found > 1:
            LOG.warning("Multiple base images for image: %s", image_id)
        return list(recs.keys())[0]


def _get_resize_func_name(session):
    brand = session.product_brand
    version = session.product_version

    # To maintain backwards compatibility. All recent versions
    # should use VDI.resize
    if version and brand:
        xcp = brand == 'XCP'
        r1_2_or_above = (version[0] == 1 and version[1] > 1) or version[0] > 1

        xenserver = brand == 'XenServer'
        r6_or_above = version[0] > 5

        if (xcp and not r1_2_or_above) or (xenserver and not r6_or_above):
            return 'VDI.resize_online'

    return 'VDI.resize'


def _vdi_get_virtual_size(session, vdi_ref):
    size = session.call_xenapi('VDI.get_virtual_size', vdi_ref)
    return int(size)


def _vdi_resize(session, vdi_ref, new_size):
    resize_func_name = _get_resize_func_name(session)
    session.call_xenapi(resize_func_name, vdi_ref, str(new_size))


def update_vdi_virtual_size(session, instance, vdi_ref, new_gb):
    virtual_size = _vdi_get_virtual_size(session, vdi_ref)
    new_disk_size = new_gb * units.Gi

    msg = ("Resizing up VDI %(vdi_ref)s from %(virtual_size)d "
           "to %(new_disk_size)d")
    LOG.debug(msg, {'vdi_ref': vdi_ref, 'virtual_size': virtual_size,
                    'new_disk_size': new_disk_size},
              instance=instance)

    if virtual_size < new_disk_size:
        # For resize up. Simple VDI resize will do the trick
        _vdi_resize(session, vdi_ref, new_disk_size)

    elif virtual_size == new_disk_size:
        LOG.debug("No need to change vdi virtual size.",
                  instance=instance)

    else:
        # NOTE(johngarbutt): we should never get here
        # but if we don't raise an exception, a user might be able to use
        # more storage than allowed by their chosen instance flavor
        msg = _("VDI %(vdi_ref)s is %(virtual_size)d bytes which is larger "
                "than flavor size of %(new_disk_size)d bytes.")
        msg = msg % {'vdi_ref': vdi_ref, 'virtual_size': virtual_size,
              'new_disk_size': new_disk_size}
        LOG.debug(msg, instance=instance)
        raise exception.ResizeError(reason=msg)


def resize_disk(session, instance, vdi_ref, flavor):
    size_gb = flavor.root_gb
    if size_gb == 0:
        reason = _("Can't resize a disk to 0 GB.")
        raise exception.ResizeError(reason=reason)

    sr_ref = safe_find_sr(session)
    clone_ref = _clone_vdi(session, vdi_ref)

    try:
        # Resize partition and filesystem down
        _auto_configure_disk(session, clone_ref, size_gb)

        # Create new VDI
        vdi_size = size_gb * units.Gi
        # NOTE(johannes): No resizing allowed for rescue instances, so
        # using instance['name'] is safe here
        new_ref = create_vdi(session, sr_ref, instance, instance['name'],
                             'root', vdi_size)

        new_uuid = session.call_xenapi('VDI.get_uuid', new_ref)

        # Manually copy contents over
        virtual_size = size_gb * units.Gi
        _copy_partition(session, clone_ref, new_ref, 1, virtual_size)

        return new_ref, new_uuid
    finally:
        destroy_vdi(session, clone_ref)


def _auto_configure_disk(session, vdi_ref, new_gb):
    """Partition and resize FS to match the size specified by
    flavors.root_gb.

    This is a fail-safe to prevent accidentally destroying data on a disk
    erroneously marked as auto_disk_config=True.

    The criteria for allowing resize are:

        1. 'auto_disk_config' must be true for the instance (and image).
           (If we've made it here, then auto_disk_config=True.)

        2. The disk must have only one partition.

        3. The file-system on the one partition must be ext3 or ext4.

        4. We are not running in independent_compute mode (checked by
           vdi_attached)
    """
    if new_gb == 0:
        LOG.debug("Skipping auto_config_disk as destination size is 0GB")
        return

    with vdi_attached(session, vdi_ref, read_only=False) as dev:
        partitions = _get_partitions(dev)

        if len(partitions) != 1:
            reason = _('Disk must have only one partition.')
            raise exception.CannotResizeDisk(reason=reason)

        num, start, old_sectors, fstype, name, flags = partitions[0]
        if fstype not in ('ext3', 'ext4'):
            reason = _('Disk contains a filesystem '
                       'we are unable to resize: %s')
            raise exception.CannotResizeDisk(reason=(reason % fstype))

        if num != 1:
            reason = _('The only partition should be partition 1.')
            raise exception.CannotResizeDisk(reason=reason)

        new_sectors = new_gb * units.Gi / SECTOR_SIZE
        _resize_part_and_fs(dev, start, old_sectors, new_sectors, flags)


def try_auto_configure_disk(session, vdi_ref, new_gb):
    if CONF.xenserver.independent_compute:
        raise exception.NotSupportedWithOption(
            operation='auto_configure_disk',
            option='CONF.xenserver.independent_compute')
    try:
        _auto_configure_disk(session, vdi_ref, new_gb)
    except exception.CannotResizeDisk as e:
        LOG.warning('Attempted auto_configure_disk failed because: %s', e)


def _make_partition(session, dev, partition_start, partition_end):
    dev_path = utils.make_dev_path(dev)

    # NOTE(bobball) If this runs in Dom0, parted will error trying
    # to re-read the partition table and return a generic error
    utils.execute('parted', '--script', dev_path,
                  'mklabel', 'msdos', run_as_root=True,
                  check_exit_code=not session.is_local_connection)

    utils.execute('parted', '--script', dev_path, '--',
                  'mkpart', 'primary',
                  partition_start,
                  partition_end,
                  run_as_root=True,
                  check_exit_code=not session.is_local_connection)

    partition_path = utils.make_dev_path(dev, partition=1)
    if session.is_local_connection:
        # Need to refresh the partitions
        utils.trycmd('kpartx', '-a', dev_path,
                     run_as_root=True,
                     discard_warnings=True)

        # Sometimes the partition gets created under /dev/mapper, depending
        # on the setup in dom0.
        mapper_path = '/dev/mapper/%s' % os.path.basename(partition_path)
        if os.path.exists(mapper_path):
            return mapper_path

    return partition_path


def _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   disk_type, size_mb, fs_type, fs_label=None):
    """Steps to programmatically generate a disk:

    1. Create VDI of desired size

    2. Attach VDI to Dom0

    3. Create partition
    3.a. If the partition type is supported by dom0 (currently ext3,
    swap) then create it while the VDI is attached to dom0.
    3.b. If the partition type is not supported by dom0, attach the
    VDI to the domU and create there.
    This split between DomU/Dom0 ensures that we can create most
    VM types in the "isolated compute" case.

    4. Create VBD between instance VM and VDI

    """
    # 1. Create VDI
    sr_ref = safe_find_sr(session)
    ONE_MEG = units.Mi
    virtual_size = size_mb * ONE_MEG
    vdi_ref = create_vdi(session, sr_ref, instance, name_label, disk_type,
                         virtual_size)

    try:
        # 2. Attach VDI to Dom0 (VBD hotplug)
        mkfs_in_dom0 = fs_type in ('ext3', 'swap')
        with vdi_attached(session, vdi_ref, read_only=False,
                               dom0=True) as dev:
            # 3. Create partition
            partition_start = "2048"
            partition_end = "-"

            disk_management.make_partition(session, dev, partition_start,
                                           partition_end)

            if mkfs_in_dom0:
                disk_management.mkfs(session, dev, '1', fs_type, fs_label)

        # 3.a. dom0 does not support nfs/ext4, so may have to mkfs in domU
        if fs_type is not None and not mkfs_in_dom0:
            with vdi_attached(session, vdi_ref, read_only=False) as dev:
                partition_path = utils.make_dev_path(dev, partition=1)
                utils.mkfs(fs_type, partition_path, fs_label,
                           run_as_root=True)

        # 4. Create VBD between instance VM and VDI
        if vm_ref:
            create_vbd(session, vm_ref, vdi_ref, userdevice, bootable=False)
    except Exception:
        with excutils.save_and_reraise_exception():
            msg = "Error while generating disk number: %s" % userdevice
            LOG.debug(msg, instance=instance, exc_info=True)
            safe_destroy_vdis(session, [vdi_ref])

    return vdi_ref


def generate_swap(session, instance, vm_ref, userdevice, name_label, swap_mb):
    # NOTE(jk0): We use a FAT32 filesystem for the Windows swap
    # partition because that is what parted supports.
    is_windows = instance['os_type'] == "windows"
    fs_type = "vfat" if is_windows else "swap"

    if CONF.xenserver.independent_compute and fs_type != "swap":
        raise exception.NotSupportedWithOption(
            operation='swap drives for Windows',
            option='CONF.xenserver.independent_compute')

    _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   'swap', swap_mb, fs_type)


def get_ephemeral_disk_sizes(total_size_gb):
    if not total_size_gb:
        return

    max_size_gb = 2000
    if total_size_gb % 1024 == 0:
        max_size_gb = 1024

    left_to_allocate = total_size_gb
    while left_to_allocate > 0:
        size_gb = min(max_size_gb, left_to_allocate)
        yield size_gb
        left_to_allocate -= size_gb


def generate_single_ephemeral(session, instance, vm_ref, userdevice,
                              size_gb, instance_name_label=None):
    if instance_name_label is None:
        instance_name_label = instance["name"]

    name_label = "%s ephemeral" % instance_name_label
    fs_label = "ephemeral"
    # TODO(johngarbutt) need to move DEVICE_EPHEMERAL from vmops to use it here
    label_number = int(userdevice) - 4
    if label_number > 0:
        name_label = "%s (%d)" % (name_label, label_number)
        fs_label = "ephemeral%d" % label_number

    return _generate_disk(session, instance, vm_ref, str(userdevice),
                          name_label, 'ephemeral', size_gb * 1024,
                          CONF.default_ephemeral_format, fs_label)


def generate_ephemeral(session, instance, vm_ref, first_userdevice,
                       instance_name_label, total_size_gb):
    # NOTE(johngarbutt): max possible size of a VHD disk is 2043GB
    sizes = get_ephemeral_disk_sizes(total_size_gb)
    first_userdevice = int(first_userdevice)

    vdi_refs = []
    try:
        for userdevice, size_gb in enumerate(sizes, start=first_userdevice):
            ref = generate_single_ephemeral(session, instance, vm_ref,
                                            userdevice, size_gb,
                                            instance_name_label)
            vdi_refs.append(ref)
    except Exception as exc:
        with excutils.save_and_reraise_exception():
            LOG.debug("Error when generating ephemeral disk. "
                      "Device: %(userdevice)s Size GB: %(size_gb)s "
                      "Error: %(exc)s", {
                            'userdevice': userdevice,
                            'size_gb': size_gb,
                            'exc': exc})
            safe_destroy_vdis(session, vdi_refs)


def generate_iso_blank_root_disk(session, instance, vm_ref, userdevice,
                                 name_label, size_gb):
    _generate_disk(session, instance, vm_ref, userdevice, name_label,
                   'user', size_gb * 1024, CONF.default_ephemeral_format)


def generate_configdrive(session, context, instance, vm_ref, userdevice,
                         network_info, admin_password=None, files=None):
    sr_ref = safe_find_sr(session)
    vdi_ref = create_vdi(session, sr_ref, instance, 'config-2',
                         'configdrive', configdrive.CONFIGDRIVESIZE_BYTES)
    try:
        extra_md = {}
        if admin_password:
            extra_md['admin_pass'] = admin_password
        inst_md = instance_metadata.InstanceMetadata(
            instance, content=files, extra_md=extra_md,
            network_info=network_info, request_context=context)
        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            with utils.tempdir() as tmp_path:
                tmp_file = os.path.join(tmp_path, 'configdrive')
                cdb.make_drive(tmp_file)
                # XAPI can only import a VHD file, so convert to vhd format
                vhd_file = '%s.vhd' % tmp_file
                utils.execute('qemu-img', 'convert', '-Ovpc', tmp_file,
                              vhd_file)
                vhd_file_size = os.path.getsize(vhd_file)
                with open(vhd_file) as file_obj:
                    volume_utils.stream_to_vdi(
                        session, instance, 'vhd', file_obj,
                        vhd_file_size, vdi_ref)
        create_vbd(session, vm_ref, vdi_ref, userdevice, bootable=False,
                   read_only=True)
    except Exception:
        with excutils.save_and_reraise_exception():
            msg = "Error while generating config drive"
            LOG.debug(msg, instance=instance, exc_info=True)
            safe_destroy_vdis(session, [vdi_ref])


def _create_kernel_image(context, session, instance, name_label, image_id,
                         image_type):
    """Creates kernel/ramdisk file from the image stored in the cache.
    If the image is not present in the cache, fetch it from glance.

    Returns: A list of dictionaries that describe VDIs
    """
    if CONF.xenserver.independent_compute:
        raise exception.NotSupportedWithOption(
            operation='Non-VHD images',
            option='CONF.xenserver.independent_compute')

    filename = ""
    if CONF.xenserver.cache_images != 'none':
        new_image_uuid = uuidutils.generate_uuid()
        filename = disk_management.create_kernel_ramdisk(
            session, image_id, new_image_uuid)

    if filename == "":
        return _fetch_disk_image(context, session, instance, name_label,
                                 image_id, image_type)
    else:
        vdi_type = ImageType.to_string(image_type)
        return {vdi_type: dict(uuid=None, file=filename)}


def create_kernel_and_ramdisk(context, session, instance, name_label):
    kernel_file = None
    ramdisk_file = None
    if instance['kernel_id']:
        vdis = _create_kernel_image(context, session,
                instance, name_label, instance['kernel_id'],
                ImageType.KERNEL)
        kernel_file = vdis['kernel'].get('file')

    if instance['ramdisk_id']:
        vdis = _create_kernel_image(context, session,
                instance, name_label, instance['ramdisk_id'],
                ImageType.RAMDISK)
        ramdisk_file = vdis['ramdisk'].get('file')

    return kernel_file, ramdisk_file


def destroy_kernel_ramdisk(session, instance, kernel, ramdisk):
    if kernel or ramdisk:
        LOG.debug("Removing kernel/ramdisk files from dom0",
                    instance=instance)
        disk_management.remove_kernel_ramdisk(
            session, kernel_file=kernel, ramdisk_file=ramdisk)


def _get_image_vdi_label(image_id):
    return 'Glance Image %s' % image_id


def _create_cached_image(context, session, instance, name_label,
                         image_id, image_type):
    sr_ref = safe_find_sr(session)
    sr_type = session.call_xenapi('SR.get_type', sr_ref)

    if CONF.use_cow_images and sr_type != "ext":
        LOG.warning("Fast cloning is only supported on default local SR "
                    "of type ext. SR on this system was found to be of "
                    "type %s. Ignoring the cow flag.", sr_type)

    @utils.synchronized('xenapi-image-cache' + image_id)
    def _create_cached_image_impl(context, session, instance, name_label,
                                  image_id, image_type, sr_ref):
        cache_vdi_ref = _find_cached_image(session, image_id, sr_ref)
        downloaded = False
        if cache_vdi_ref is None:
            downloaded = True
            vdis = _fetch_image(context, session, instance, name_label,
                                image_id, image_type)

            cache_vdi_ref = session.call_xenapi(
                    'VDI.get_by_uuid', vdis['root']['uuid'])

            session.call_xenapi('VDI.set_name_label', cache_vdi_ref,
                                _get_image_vdi_label(image_id))
            session.call_xenapi('VDI.set_name_description', cache_vdi_ref,
                                'root')
            session.call_xenapi('VDI.add_to_other_config',
                                cache_vdi_ref, 'image-id', str(image_id))

        if CONF.use_cow_images:
            new_vdi_ref = _clone_vdi(session, cache_vdi_ref)
        elif sr_type == 'ext':
            new_vdi_ref = _safe_copy_vdi(session, sr_ref, instance,
                                         cache_vdi_ref)
        else:
            new_vdi_ref = session.call_xenapi("VDI.copy", cache_vdi_ref,
                                              sr_ref)

        session.call_xenapi('VDI.set_name_label', new_vdi_ref, '')
        session.call_xenapi('VDI.set_name_description', new_vdi_ref, '')
        session.call_xenapi('VDI.remove_from_other_config',
                            new_vdi_ref, 'image-id')

        vdi_uuid = session.call_xenapi('VDI.get_uuid', new_vdi_ref)
        return downloaded, vdi_uuid

    downloaded, vdi_uuid = _create_cached_image_impl(context, session,
                                                     instance, name_label,
                                                     image_id, image_type,
                                                     sr_ref)

    vdis = {}
    vdi_type = ImageType.get_role(image_type)
    vdis[vdi_type] = dict(uuid=vdi_uuid, file=None)
    return downloaded, vdis


def create_image(context, session, instance, name_label, image_id,
                 image_type):
    """Creates VDI from the image stored in the local cache. If the image
    is not present in the cache, it streams it from glance.

    Returns: A list of dictionaries that describe VDIs
    """
    cache_images = CONF.xenserver.cache_images.lower()

    # Determine if the image is cacheable
    if image_type == ImageType.DISK_ISO:
        cache = False
    elif cache_images == 'all':
        cache = True
    elif cache_images == 'some':
        sys_meta = utils.instance_sys_meta(instance)
        try:
            cache = strutils.bool_from_string(sys_meta['image_cache_in_nova'])
        except KeyError:
            cache = False
    elif cache_images == 'none':
        cache = False
    else:
        LOG.warning("Unrecognized cache_images value '%s', defaulting to True",
                    CONF.xenserver.cache_images)
        cache = True

    # Fetch (and cache) the image
    start_time = timeutils.utcnow()
    if cache:
        downloaded, vdis = _create_cached_image(context, session, instance,
                                                name_label, image_id,
                                                image_type)
    else:
        vdis = _fetch_image(context, session, instance, name_label,
                            image_id, image_type)
        downloaded = True
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    LOG.info("Image creation data, cacheable: %(cache)s, "
             "downloaded: %(downloaded)s duration: %(duration).2f secs "
             "for image %(image_id)s",
             {'image_id': image_id, 'cache': cache, 'downloaded': downloaded,
              'duration': duration})

    for vdi_type, vdi in vdis.items():
        vdi_ref = session.call_xenapi('VDI.get_by_uuid', vdi['uuid'])
        _set_vdi_info(session, vdi_ref, vdi_type, name_label, vdi_type,
                      instance)

    return vdis


def _fetch_image(context, session, instance, name_label, image_id, image_type):
    """Fetch image from glance based on image type.

    Returns: A single filename if image_type is KERNEL or RAMDISK
             A list of dictionaries that describe VDIs, otherwise
    """
    if image_type == ImageType.DISK_VHD:
        vdis = _fetch_vhd_image(context, session, instance, image_id)
    else:
        if CONF.xenserver.independent_compute:
            raise exception.NotSupportedWithOption(
                operation='Non-VHD images',
                option='CONF.xenserver.independent_compute')
        vdis = _fetch_disk_image(context, session, instance, name_label,
                                 image_id, image_type)

    for vdi_type, vdi in vdis.items():
        vdi_uuid = vdi['uuid']
        LOG.debug("Fetched VDIs of type '%(vdi_type)s' with UUID"
                  " '%(vdi_uuid)s'",
                  {'vdi_type': vdi_type, 'vdi_uuid': vdi_uuid},
                  instance=instance)

    return vdis


def _make_uuid_stack():
    # NOTE(sirp): The XenAPI plugins run under Python 2.4
    # which does not have the `uuid` module. To work around this,
    # we generate the uuids here (under Python 2.6+) and
    # pass them as arguments
    return [uuidutils.generate_uuid() for i in range(MAX_VDI_CHAIN_SIZE)]


def _default_download_handler():
    # TODO(sirp):  This should be configurable like upload_handler
    return importutils.import_object(
            'nova.virt.xenapi.image.glance.GlanceStore')


def get_compression_level():
    level = CONF.xenserver.image_compression_level
    if level is not None and (level < 1 or level > 9):
        LOG.warning("Invalid value '%d' for image_compression_level", level)
        return None
    return level


def _fetch_vhd_image(context, session, instance, image_id):
    """Tell glance to download an image and put the VHDs into the SR

    Returns: A list of dictionaries that describe VDIs
    """
    LOG.debug("Asking xapi to fetch vhd image %s", image_id,
              instance=instance)

    handler = _default_download_handler()

    try:
        vdis = handler.download_image(context, session, instance, image_id)
    except Exception:
        raise

    # Ensure we can see the import VHDs as VDIs
    scan_default_sr(session)

    vdi_uuid = vdis['root']['uuid']
    try:
        _check_vdi_size(context, session, instance, vdi_uuid)
    except Exception:
        with excutils.save_and_reraise_exception():
            msg = "Error while checking vdi size"
            LOG.debug(msg, instance=instance, exc_info=True)
            for vdi in vdis.values():
                vdi_uuid = vdi['uuid']
                vdi_ref = session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
                safe_destroy_vdis(session, [vdi_ref])

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
        LOG.debug('vdi_uuid=%(cur_vdi_uuid)s vdi_size_bytes='
                  '%(vdi_size_bytes)d',
                  {'cur_vdi_uuid': cur_vdi_uuid,
                   'vdi_size_bytes': vdi_size_bytes})
        size_bytes += vdi_size_bytes
    return size_bytes


def _check_vdi_size(context, session, instance, vdi_uuid):
    flavor = instance.get_flavor()
    allowed_size = (flavor.root_gb +
                    VHD_SIZE_CHECK_FUDGE_FACTOR_GB) * units.Gi
    if not flavor.root_gb:
        # root_gb=0 indicates that we're disabling size checks
        return

    size = _get_vdi_chain_size(session, vdi_uuid)
    if size > allowed_size:
        LOG.error("Image size %(size)d exceeded flavor "
                  "allowed size %(allowed_size)d",
                  {'size': size, 'allowed_size': allowed_size},
                  instance=instance)

        raise exception.FlavorDiskSmallerThanImage(
            flavor_size=(flavor.root_gb * units.Gi),
            image_size=(size * units.Gi))


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
    LOG.debug("Fetching image %(image_id)s, type %(image_type_str)s",
              {'image_id': image_id, 'image_type_str': image_type_str},
              instance=instance)

    if image_type == ImageType.DISK_ISO:
        sr_ref = _safe_find_iso_sr(session)
    else:
        sr_ref = safe_find_sr(session)

    glance_image = image_utils.GlanceImage(context, image_id)
    if glance_image.is_raw_tgz():
        image = image_utils.RawTGZImage(glance_image)
    else:
        image = image_utils.RawImage(glance_image)

    virtual_size = image.get_size()
    vdi_size = virtual_size
    LOG.debug("Size for image %(image_id)s: %(virtual_size)d",
              {'image_id': image_id, 'virtual_size': virtual_size},
              instance=instance)
    if image_type == ImageType.DISK:
        # Make room for MBR.
        vdi_size += MBR_SIZE_BYTES
    elif (image_type in (ImageType.KERNEL, ImageType.RAMDISK) and
          vdi_size > CONF.xenserver.max_kernel_ramdisk_size):
        max_size = CONF.xenserver.max_kernel_ramdisk_size
        raise exception.NovaException(
            _("Kernel/Ramdisk image is too large: %(vdi_size)d bytes, "
              "max %(max_size)d bytes") %
            {'vdi_size': vdi_size, 'max_size': max_size})

    vdi_ref = create_vdi(session, sr_ref, instance, name_label,
                         image_type_str, vdi_size)
    # From this point we have a VDI on Xen host;
    # If anything goes wrong, we need to remember its uuid.
    try:
        filename = None
        vdi_uuid = session.call_xenapi("VDI.get_uuid", vdi_ref)

        with vdi_attached(session, vdi_ref, read_only=False) as dev:
            _stream_disk(
                session, image.stream_to, image_type, virtual_size, dev)

        if image_type in (ImageType.KERNEL, ImageType.RAMDISK):
            # We need to invoke a plugin for copying the
            # content of the VDI into the proper path.
            LOG.debug("Copying VDI %s to /boot/guest on dom0",
                      vdi_ref, instance=instance)

            cache_image = None
            if CONF.xenserver.cache_images != 'none':
                cache_image = image_id
            filename = disk_management.copy_vdi(session, vdi_ref, vdi_size,
                                                image_id=cache_image)

            # Remove the VDI as it is not needed anymore.
            destroy_vdi(session, vdi_ref)
            LOG.debug("Kernel/Ramdisk VDI %s destroyed", vdi_ref,
                      instance=instance)
            vdi_role = ImageType.get_role(image_type)
            return {vdi_role: dict(uuid=None, file=filename)}
        else:
            vdi_role = ImageType.get_role(image_type)
            return {vdi_role: dict(uuid=vdi_uuid, file=None)}
    except (session.XenAPI.Failure, IOError, OSError) as e:
        # We look for XenAPI and OS failures.
        LOG.exception(_("Failed to fetch glance image"), instance=instance)
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
    if not image_meta.obj_attr_is_set("disk_format"):
        return None

    disk_format_map = {
        'ami': ImageType.DISK,
        'aki': ImageType.KERNEL,
        'ari': ImageType.RAMDISK,
        'raw': ImageType.DISK_RAW,
        'vhd': ImageType.DISK_VHD,
        'iso': ImageType.DISK_ISO,
    }

    try:
        image_type = disk_format_map[image_meta.disk_format]
    except KeyError:
        raise exception.InvalidDiskFormat(disk_format=image_meta.disk_format)

    LOG.debug("Detected %(type)s format for image %(image)s",
              {'type': ImageType.to_string(image_type),
               'image': image_meta})

    return image_type


def determine_vm_mode(instance, disk_image_type):
    current_mode = obj_fields.VMMode.get_from_instance(instance)
    if (current_mode == obj_fields.VMMode.XEN or
        current_mode == obj_fields.VMMode.HVM):
        return current_mode

    os_type = instance['os_type']
    if os_type == "linux":
        return obj_fields.VMMode.XEN
    if os_type == "windows":
        return obj_fields.VMMode.HVM

    # disk_image_type specific default for backwards compatibility
    if disk_image_type == ImageType.DISK_VHD or \
            disk_image_type == ImageType.DISK:
        return obj_fields.VMMode.XEN

    # most images run OK as HVM
    return obj_fields.VMMode.HVM


def set_vm_name_label(session, vm_ref, name_label):
    session.call_xenapi("VM.set_name_label", vm_ref, name_label)


def list_vms(session):
    vms = session.call_xenapi("VM.get_all_records_where",
                              'field "is_control_domain"="false" and '
                              'field "is_a_template"="false" and '
                              'field "resident_on"="%s"' % session.host_ref)
    for vm_ref in vms.keys():
        yield vm_ref, vms[vm_ref]


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
                vdi_uuid = session.call_xenapi("VDI.get_uuid", vdi_ref)
                LOG.debug('VDI %s is still available', vdi_uuid)
                vbd_other_config = session.call_xenapi("VBD.get_other_config",
                                                       vbd_ref)
                if not vbd_other_config.get('osvol'):
                    # This is not an attached volume
                    vdi_refs.append(vdi_ref)
            except session.XenAPI.Failure:
                LOG.exception(_('"Look for the VDIs failed'))
    return vdi_refs


def lookup(session, name_label, check_rescue=False):
    """Look the instance up and return it if available.
    :param:check_rescue: if True will return the 'name'-rescue vm if it
    exists, instead of just 'name'
    """
    if check_rescue:
        result = lookup(session, name_label + '-rescue', False)
        if result:
            return result
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
    key = str(instance['key_data'])
    net = netutils.get_injected_network_template(network_info)
    metadata = instance['metadata']

    # As mounting the image VDI is expensive, we only want do it once,
    # if at all, so determine whether it's required first, and then do
    # everything
    mount_required = key or net or metadata
    if not mount_required:
        return

    with vdi_attached(session, vdi_ref, read_only=False) as dev:
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


def get_power_state(session, vm_ref):
    xapi_state = session.call_xenapi("VM.get_power_state", vm_ref)
    return XENAPI_POWER_STATE[xapi_state]


def _vm_query_data_source(session, *args):
    """We're getting diagnostics stats from the RRDs which are updated every
    5 seconds. It means that diagnostics information may be incomplete during
    first 5 seconds of VM life. In such cases method ``query_data_source()``
    may raise a ``XenAPI.Failure`` exception or may return a `NaN` value.
    """

    try:
        value = session.VM.query_data_source(*args)
    except session.XenAPI.Failure:
        return None

    if math.isnan(value):
        return None
    return value


def compile_info(session, vm_ref):
    """Fill record with VM status information."""
    power_state = get_power_state(session, vm_ref)
    max_mem = session.call_xenapi("VM.get_memory_static_max", vm_ref)
    mem = session.call_xenapi("VM.get_memory_dynamic_max", vm_ref)
    num_cpu = session.call_xenapi("VM.get_VCPUs_max", vm_ref)

    return hardware.InstanceInfo(state=power_state,
                                 max_mem_kb=int(max_mem) >> 10,
                                 mem_kb=int(mem) >> 10,
                                 num_cpu=num_cpu)


def compile_instance_diagnostics(session, instance, vm_ref):
    xen_power_state = session.VM.get_power_state(vm_ref)
    vm_power_state = power_state.STATE_MAP[XENAPI_POWER_STATE[xen_power_state]]
    config_drive = configdrive.required_by(instance)

    diags = diagnostics.Diagnostics(state=vm_power_state,
                                    driver='xenapi',
                                    config_drive=config_drive)
    _add_cpu_usage(session, vm_ref, diags)
    _add_nic_usage(session, vm_ref, diags)
    _add_disk_usage(session, vm_ref, diags)
    _add_memory_usage(session, vm_ref, diags)

    return diags


def _add_cpu_usage(session, vm_ref, diag_obj):
    cpu_num = int(session.VM.get_VCPUs_max(vm_ref))
    for cpu_num in range(0, cpu_num):
        utilisation = _vm_query_data_source(session, vm_ref, "cpu%d" % cpu_num)
        if utilisation is not None:
            utilisation *= 100
        diag_obj.add_cpu(id=cpu_num, utilisation=utilisation)


def _add_nic_usage(session, vm_ref, diag_obj):
    vif_refs = session.VM.get_VIFs(vm_ref)
    for vif_ref in vif_refs:
        vif_rec = session.VIF.get_record(vif_ref)
        rx_rate = _vm_query_data_source(session, vm_ref,
                                        "vif_%s_rx" % vif_rec['device'])
        tx_rate = _vm_query_data_source(session, vm_ref,
                                        "vif_%s_tx" % vif_rec['device'])
        diag_obj.add_nic(mac_address=vif_rec['MAC'],
                         rx_rate=rx_rate,
                         tx_rate=tx_rate)


def _add_disk_usage(session, vm_ref, diag_obj):
    vbd_refs = session.VM.get_VBDs(vm_ref)
    for vbd_ref in vbd_refs:
        vbd_rec = session.VBD.get_record(vbd_ref)
        read_bytes = _vm_query_data_source(session, vm_ref,
                                           "vbd_%s_read" % vbd_rec['device'])
        write_bytes = _vm_query_data_source(session, vm_ref,
                                            "vbd_%s_write" % vbd_rec['device'])
        diag_obj.add_disk(read_bytes=read_bytes, write_bytes=write_bytes)


def _add_memory_usage(session, vm_ref, diag_obj):
    total_mem = _vm_query_data_source(session, vm_ref, "memory")
    free_mem = _vm_query_data_source(session, vm_ref, "memory_internal_free")
    used_mem = None
    if total_mem is not None:
        # total_mem provided from XenServer is in Bytes. Converting it to MB.
        total_mem /= units.Mi

        if free_mem is not None:
            # free_mem provided from XenServer is in KB. Converting it to MB.
            used_mem = total_mem - free_mem / units.Ki

    diag_obj.memory_details = diagnostics.MemoryDiagnostics(
        maximum=total_mem, used=used_mem)


def compile_diagnostics(vm_rec):
    """Compile VM diagnostics data."""
    try:
        keys = []
        diags = {}
        vm_uuid = vm_rec["uuid"]
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
        LOG.exception(_('Unable to parse rrd of %s'), e)
        return {"Unable to retrieve diagnostics": e}


def fetch_bandwidth(session):
    bw = host_network.fetch_all_bandwidth(session)
    return bw


def _scan_sr(session, sr_ref=None, max_attempts=4):
    if sr_ref:
        # NOTE(johngarbutt) xenapi will collapse any duplicate requests
        # for SR.scan if there is already a scan in progress.
        # However, we don't want that, because the scan may have started
        # before we modified the underlying VHDs on disk through a plugin.
        # Using our own mutex will reduce cases where our periodic SR scan
        # in host.update_status starts racing the sr.scan after a plugin call.
        @utils.synchronized('sr-scan-' + sr_ref)
        def do_scan(sr_ref):
            LOG.debug("Scanning SR %s", sr_ref)

            attempt = 1
            while True:
                try:
                    return session.call_xenapi('SR.scan', sr_ref)
                except session.XenAPI.Failure as exc:
                    with excutils.save_and_reraise_exception() as ctxt:
                        if exc.details[0] == 'SR_BACKEND_FAILURE_40':
                            if attempt < max_attempts:
                                ctxt.reraise = False
                                LOG.warning("Retry SR scan due to error: %s",
                                            exc)
                                greenthread.sleep(2 ** attempt)
                                attempt += 1
        do_scan(sr_ref)


def scan_default_sr(session):
    """Looks for the system default SR and triggers a re-scan."""
    sr_ref = safe_find_sr(session)
    _scan_sr(session, sr_ref)
    return sr_ref


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
    host = session.host_ref
    try:
        tokens = CONF.xenserver.sr_matching_filter.split(':')
        filter_criteria = tokens[0]
        filter_pattern = tokens[1]
    except IndexError:
        # oops, flag is invalid
        LOG.warning("Flag sr_matching_filter '%s' does not respect "
                    "formatting convention",
                    CONF.xenserver.sr_matching_filter)
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
        sr_ref = session.call_xenapi('pool.get_default_SR', pool_ref)
        if sr_ref:
            return sr_ref
    # No SR found!
    LOG.error("XenAPI is unable to find a Storage Repository to "
              "install guest instances on. Please check your "
              "configuration (e.g. set a default SR for the pool) "
              "and/or configure the flag 'sr_matching_filter'.")
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
    host = session.host_ref
    for sr_ref, sr_rec in session.get_all_refs_and_recs('SR'):
        LOG.debug("ISO: looking at SR %s", sr_rec)
        if not sr_rec['content_type'] == 'iso':
            LOG.debug("ISO: not iso content")
            continue
        if 'i18n-key' not in sr_rec['other_config']:
            LOG.debug("ISO: iso content_type, no 'i18n-key' key")
            continue
        if not sr_rec['other_config']['i18n-key'] == 'local-storage-iso':
            LOG.debug("ISO: iso content_type, i18n-key value not "
                      "'local-storage-iso'")
            continue

        LOG.debug("ISO: SR MATCHing our criteria")
        for pbd_ref in sr_rec['PBDs']:
            LOG.debug("ISO: ISO, looking to see if it is host local")
            pbd_rec = session.get_rec('PBD', pbd_ref)
            if not pbd_rec:
                LOG.debug("ISO: PBD %s disappeared", pbd_ref)
                continue
            pbd_rec_host = pbd_rec['host']
            LOG.debug("ISO: PBD matching, want %(pbd_rec)s, have %(host)s",
                      {'pbd_rec': pbd_rec, 'host': host})
            if pbd_rec_host == host:
                LOG.debug("ISO: SR with local PBD")
                return sr_ref
    return None


def _get_rrd_server():
    """Return server's scheme and address to use for retrieving RRD XMLs."""
    xs_url = urlparse.urlparse(CONF.xenserver.connection_url)
    return [xs_url.scheme, xs_url.netloc]


def _get_rrd(server, vm_uuid):
    """Return the VM RRD XML as a string."""
    try:
        xml = urllib.urlopen("%s://%s:%s@%s/vm_rrd?uuid=%s" % (
            server[0],
            CONF.xenserver.connection_username,
            CONF.xenserver.connection_password,
            server[1],
            vm_uuid))
        return xml.read()
    except IOError:
        LOG.exception(_('Unable to obtain RRD XML for VM %(vm_uuid)s with '
                        'server details: %(server)s.'),
                      {'vm_uuid': vm_uuid, 'server': server})
        return None


def _get_all_vdis_in_sr(session, sr_ref):
    for vdi_ref in session.call_xenapi('SR.get_VDIs', sr_ref):
        vdi_rec = session.get_rec('VDI', vdi_ref)
        # Check to make sure the record still exists. It may have
        # been deleted between the get_all call and get_rec call
        if vdi_rec:
            yield vdi_ref, vdi_rec


def get_instance_vdis_for_sr(session, vm_ref, sr_ref):
    """Return opaqueRef for all the vdis which live on sr."""
    for vbd_ref in session.call_xenapi('VM.get_VBDs', vm_ref):
        try:
            vdi_ref = session.call_xenapi('VBD.get_VDI', vbd_ref)
            if sr_ref == session.call_xenapi('VDI.get_SR', vdi_ref):
                yield vdi_ref
        except session.XenAPI.Failure:
            continue


def _get_vhd_parent_uuid(session, vdi_ref, vdi_rec=None):
    if vdi_rec is None:
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)

    if 'vhd-parent' not in vdi_rec['sm_config']:
        return None

    parent_uuid = vdi_rec['sm_config']['vhd-parent']
    vdi_uuid = vdi_rec['uuid']
    LOG.debug('VHD %(vdi_uuid)s has parent %(parent_uuid)s',
              {'vdi_uuid': vdi_uuid, 'parent_uuid': parent_uuid})
    return parent_uuid


def _walk_vdi_chain(session, vdi_uuid):
    """Yield vdi_recs for each element in a VDI chain."""
    scan_default_sr(session)
    while True:
        vdi_ref = session.call_xenapi("VDI.get_by_uuid", vdi_uuid)
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
        yield vdi_rec

        parent_uuid = _get_vhd_parent_uuid(session, vdi_ref, vdi_rec)
        if not parent_uuid:
            break

        vdi_uuid = parent_uuid


def _is_vdi_a_snapshot(vdi_rec):
    """Ensure VDI is a snapshot, and not cached image."""
    is_a_snapshot = vdi_rec['is_a_snapshot']
    image_id = vdi_rec['other_config'].get('image-id')
    return is_a_snapshot and not image_id


def _child_vhds(session, sr_ref, vdi_uuid_list, old_snapshots_only=False):
    """Return the immediate children of a given VHD.

    This is not recursive, only the immediate children are returned.
    """
    children = set()
    for ref, rec in _get_all_vdis_in_sr(session, sr_ref):
        rec_uuid = rec['uuid']

        if rec_uuid in vdi_uuid_list:
            continue

        parent_uuid = _get_vhd_parent_uuid(session, ref, rec)
        if parent_uuid not in vdi_uuid_list:
            continue

        if old_snapshots_only and not _is_vdi_a_snapshot(rec):
            continue

        children.add(rec_uuid)

    return list(children)


def _count_children(session, parent_vdi_uuid, sr_ref):
    # Search for any other vdi which has the same parent as us to work out
    # whether we have siblings and therefore if coalesce is possible
    children = 0
    for _ref, rec in _get_all_vdis_in_sr(session, sr_ref):
        if (rec['sm_config'].get('vhd-parent') == parent_vdi_uuid):
            children = children + 1
    return children


def _wait_for_vhd_coalesce(session, instance, sr_ref, vdi_ref,
                           vdi_uuid_list):
    """Spin until the parent VHD is coalesced into one of the VDIs in the list

    vdi_uuid_list is a list of acceptable final parent VDIs for vdi_ref; once
    the parent of vdi_ref is in vdi_uuid_chain we consider the coalesce over.

    The use case is there are any number of VDIs between those in
    vdi_uuid_list and vdi_ref that we expect to be coalesced, but any of those
    in vdi_uuid_list may also be coalesced (except the base UUID - which is
    guaranteed to remain)
    """
    # If the base disk was a leaf node, there will be no coalescing
    # after a VDI snapshot.
    if len(vdi_uuid_list) == 1:
        LOG.debug("Old chain is single VHD, coalesce not possible.",
                  instance=instance)
        return

    # If the parent of the original disk has other children,
    # there will be no coalesce because of the VDI snapshot.
    # For example, the first snapshot for an instance that has been
    # spawned from a cached image, will not coalesce, because of this rule.
    parent_vdi_uuid = vdi_uuid_list[1]
    if _count_children(session, parent_vdi_uuid, sr_ref) > 1:
        LOG.debug("Parent has other children, coalesce is unlikely.",
                  instance=instance)
        return

    # When the VDI snapshot is taken, a new parent is created.
    # Assuming it is not one of the above cases, that new parent
    # can be coalesced, so we need to wait for that to happen.
    max_attempts = CONF.xenserver.vhd_coalesce_max_attempts
    # Remove the leaf node from list, to get possible good parents
    # when the coalesce has completed.
    # Its possible that other coalesce operation happen, so we need
    # to consider the full chain, rather than just the most recent parent.
    good_parent_uuids = vdi_uuid_list[1:]
    for i in range(max_attempts):
        # NOTE(sirp): This rescan is necessary to ensure the VM's `sm_config`
        # matches the underlying VHDs.
        # This can also kick XenServer into performing a pending coalesce.
        _scan_sr(session, sr_ref)
        parent_uuid = _get_vhd_parent_uuid(session, vdi_ref)
        if parent_uuid and (parent_uuid not in good_parent_uuids):
            LOG.debug("Parent %(parent_uuid)s not yet in parent list"
                      " %(good_parent_uuids)s, waiting for coalesce...",
                      {'parent_uuid': parent_uuid,
                       'good_parent_uuids': good_parent_uuids},
                      instance=instance)
        else:
            LOG.debug("Coalesce detected, because parent is: %s", parent_uuid,
                      instance=instance)
            return

        greenthread.sleep(CONF.xenserver.vhd_coalesce_poll_interval)

    msg = (_("VHD coalesce attempts exceeded (%d)"
             ", giving up...") % max_attempts)
    raise exception.NovaException(msg)


def _remap_vbd_dev(dev):
    """Return the appropriate location for a plugged-in VBD device

    Ubuntu Maverick moved xvd? -> sd?. This is considered a bug and will be
    fixed in future versions:
        https://bugs.launchpad.net/ubuntu/+source/linux/+bug/684875

    For now, we work around it by just doing a string replace.
    """
    # NOTE(sirp): This hack can go away when we pull support for Maverick
    should_remap = CONF.xenserver.remap_vbd_dev
    if not should_remap:
        return dev

    old_prefix = 'xvd'
    new_prefix = CONF.xenserver.remap_vbd_dev_prefix
    remapped_dev = dev.replace(old_prefix, new_prefix)

    return remapped_dev


def _wait_for_device(session, dev, dom0, max_seconds):
    """Wait for device node to appear."""
    dev_path = utils.make_dev_path(dev)
    found_path = None
    if dom0:
        found_path = disk_management.wait_for_dev(session, dev_path,
                                                  max_seconds)
    else:
        for i in range(0, max_seconds):
            if os.path.exists(dev_path):
                found_path = dev_path
                break
            time.sleep(1)

    if found_path is None:
        raise exception.StorageError(
            reason=_('Timeout waiting for device %s to be created') % dev)


def cleanup_attached_vdis(session):
    """Unplug any instance VDIs left after an unclean restart."""
    this_vm_ref = _get_this_vm_ref(session)

    vbd_refs = session.call_xenapi('VM.get_VBDs', this_vm_ref)
    for vbd_ref in vbd_refs:
        try:
            vdi_ref = session.call_xenapi('VBD.get_VDI', vbd_ref)
            vdi_rec = session.call_xenapi('VDI.get_record', vdi_ref)
        except session.XenAPI.Failure as e:
            if e.details[0] != 'HANDLE_INVALID':
                raise
            continue

        if 'nova_instance_uuid' in vdi_rec['other_config']:
            # Belongs to an instance and probably left over after an
            # unclean restart
            LOG.info('Disconnecting stale VDI %s from compute domU',
                     vdi_rec['uuid'])
            unplug_vbd(session, vbd_ref, this_vm_ref)
            destroy_vbd(session, vbd_ref)


@contextlib.contextmanager
def vdi_attached(session, vdi_ref, read_only=False, dom0=False):
    if dom0:
        this_vm_ref = _get_dom0_ref(session)
    else:
        # Make sure we are running as a domU.
        ensure_correct_host(session)
        this_vm_ref = _get_this_vm_ref(session)

    vbd_ref = create_vbd(session, this_vm_ref, vdi_ref, 'autodetect',
                         read_only=read_only, bootable=False)
    try:
        LOG.debug('Plugging VBD %s ... ', vbd_ref)
        session.VBD.plug(vbd_ref, this_vm_ref)
        try:
            LOG.debug('Plugging VBD %s done.', vbd_ref)
            orig_dev = session.call_xenapi("VBD.get_device", vbd_ref)
            LOG.debug('VBD %(vbd_ref)s plugged as %(orig_dev)s',
                      {'vbd_ref': vbd_ref, 'orig_dev': orig_dev})
            dev = _remap_vbd_dev(orig_dev)
            if dev != orig_dev:
                LOG.debug('VBD %(vbd_ref)s plugged into wrong dev, '
                          'remapping to %(dev)s',
                          {'vbd_ref': vbd_ref, 'dev': dev})
            _wait_for_device(session, dev, dom0,
                             CONF.xenserver.block_device_creation_timeout)
            yield dev
        finally:
            # As we can not have filesystems mounted here (we cannot
            # destroy the VBD with filesystems mounted), it is not
            # useful to call sync.
            LOG.debug('Destroying VBD for VDI %s ... ', vdi_ref)
            unplug_vbd(session, vbd_ref, this_vm_ref)
    finally:
        try:
            destroy_vbd(session, vbd_ref)
        except exception.StorageError:
            # destroy_vbd() will log error
            pass
        LOG.debug('Destroying VBD for VDI %s done.', vdi_ref)


def _get_sys_hypervisor_uuid():
    with open('/sys/hypervisor/uuid') as f:
        return f.readline().strip()


def _get_dom0_ref(session):
    vms = session.call_xenapi("VM.get_all_records_where",
                              'field "domid"="0" and '
                              'field "resident_on"="%s"' %
                              session.host_ref)
    return list(vms.keys())[0]


def get_this_vm_uuid(session):
    if CONF.xenserver.independent_compute:
        LOG.error("This host has been configured with the independent "
                  "compute flag.  An operation has been attempted which is "
                  "incompatible with this flag, but should have been "
                  "caught earlier.  Please raise a bug against the "
                  "OpenStack Nova project")
        raise exception.NotSupportedWithOption(
            operation='uncaught operation',
            option='CONF.xenserver.independent_compute')
    if session and session.is_local_connection:
        # UUID is the control domain running on this host
        vms = session.call_xenapi("VM.get_all_records_where",
                                  'field "domid"="0" and '
                                  'field "resident_on"="%s"' %
                                  session.host_ref)
        return vms[list(vms.keys())[0]]['uuid']
    try:
        return _get_sys_hypervisor_uuid()
    except IOError:
        # Some guest kernels (without 5c13f8067745efc15f6ad0158b58d57c44104c25)
        # cannot read from uuid after a reboot.  Fall back to trying xenstore.
        # See https://bugs.launchpad.net/ubuntu/+source/xen-api/+bug/1081182
        domid, _ = utils.execute('xenstore-read', 'domid', run_as_root=True)
        vm_key, _ = utils.execute('xenstore-read',
                                 '/local/domain/%s/vm' % domid.strip(),
                                 run_as_root=True)
        return vm_key.strip()[4:]


def _get_this_vm_ref(session):
    return session.call_xenapi("VM.get_by_uuid", get_this_vm_uuid(session))


def _get_partitions(dev):
    """Return partition information (num, size, type) for a device."""
    dev_path = utils.make_dev_path(dev)
    out, _err = utils.execute('parted', '--script', '--machine',
                             dev_path, 'unit s', 'print',
                             run_as_root=True)
    lines = [line for line in out.split('\n') if line]
    partitions = []

    LOG.debug("Partitions:")
    for line in lines[2:]:
        line = line.rstrip(';')
        num, start, end, size, fstype, name, flags = line.split(':')
        num = int(num)
        start = int(start.rstrip('s'))
        end = int(end.rstrip('s'))
        size = int(size.rstrip('s'))
        LOG.debug("  %(num)s: %(fstype)s %(size)d sectors",
                  {'num': num, 'fstype': fstype, 'size': size})
        partitions.append((num, start, size, fstype, name, flags))

    return partitions


def _stream_disk(session, image_service_func, image_type, virtual_size, dev):
    offset = 0
    if image_type == ImageType.DISK:
        offset = MBR_SIZE_BYTES
        _write_partition(session, virtual_size, dev)

    dev_path = utils.make_dev_path(dev)

    with utils.temporary_chown(dev_path):
        with open(dev_path, 'wb') as f:
            f.seek(offset)
            image_service_func(f)


def _write_partition(session, virtual_size, dev):
    dev_path = utils.make_dev_path(dev)
    primary_first = MBR_SIZE_SECTORS
    primary_last = MBR_SIZE_SECTORS + (virtual_size / SECTOR_SIZE) - 1

    LOG.debug('Writing partition table %(primary_first)d %(primary_last)d'
              ' to %(dev_path)s...',
              {'primary_first': primary_first, 'primary_last': primary_last,
               'dev_path': dev_path})

    _make_partition(session, dev, "%ds" % primary_first, "%ds" % primary_last)
    LOG.debug('Writing partition table %s done.', dev_path)


def _repair_filesystem(partition_path):
    # Exit Code 1 = File system errors corrected
    #           2 = File system errors corrected, system needs a reboot
    utils.execute('e2fsck', '-f', '-y', partition_path, run_as_root=True,
        check_exit_code=[0, 1, 2])


def _resize_part_and_fs(dev, start, old_sectors, new_sectors, flags):
    """Resize partition and fileystem.

    This assumes we are dealing with a single primary partition and using
    ext3 or ext4.
    """
    size = new_sectors - start
    end = new_sectors - 1

    dev_path = utils.make_dev_path(dev)
    partition_path = utils.make_dev_path(dev, partition=1)

    # Replay journal if FS wasn't cleanly unmounted
    _repair_filesystem(partition_path)

    # Remove ext3 journal (making it ext2)
    utils.execute('tune2fs', '-O ^has_journal', partition_path,
                  run_as_root=True)

    if new_sectors < old_sectors:
        # Resizing down, resize filesystem before partition resize
        try:
            utils.execute('resize2fs', partition_path, '%ds' % size,
                          run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error(six.text_type(exc))
            reason = _("Shrinking the filesystem down with resize2fs "
                       "has failed, please check if you have "
                       "enough free space on your disk.")
            raise exception.ResizeError(reason=reason)

    utils.execute('parted', '--script', dev_path, 'rm', '1',
                  run_as_root=True)
    utils.execute('parted', '--script', dev_path, 'mkpart',
                  'primary',
                  '%ds' % start,
                  '%ds' % end,
                  run_as_root=True)
    if "boot" in flags.lower():
        utils.execute('parted', '--script', dev_path,
                      'set', '1', 'boot', 'on',
                      run_as_root=True)

    if new_sectors > old_sectors:
        # Resizing up, resize filesystem after partition resize
        utils.execute('resize2fs', partition_path, run_as_root=True)

    # Add back journal
    utils.execute('tune2fs', '-j', partition_path, run_as_root=True)


def _log_progress_if_required(left, last_log_time, virtual_size):
    if timeutils.is_older_than(last_log_time, PROGRESS_INTERVAL_SECONDS):
        last_log_time = timeutils.utcnow()
        complete_pct = float(virtual_size - left) / virtual_size * 100
        LOG.debug("Sparse copy in progress, "
                  "%(complete_pct).2f%% complete. "
                  "%(left)s bytes left to copy",
            {"complete_pct": complete_pct, "left": left})
    return last_log_time


def _sparse_copy(src_path, dst_path, virtual_size, block_size=4096):
    """Copy data, skipping long runs of zeros to create a sparse file."""
    start_time = last_log_time = timeutils.utcnow()
    EMPTY_BLOCK = '\0' * block_size
    bytes_read = 0
    skipped_bytes = 0
    left = virtual_size

    LOG.debug("Starting sparse_copy src=%(src_path)s dst=%(dst_path)s "
              "virtual_size=%(virtual_size)d block_size=%(block_size)d",
              {'src_path': src_path, 'dst_path': dst_path,
               'virtual_size': virtual_size, 'block_size': block_size})

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
                        greenthread.sleep(0)
                        last_log_time = _log_progress_if_required(
                            left, last_log_time, virtual_size)

    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())
    compression_pct = float(skipped_bytes) / bytes_read * 100

    LOG.debug("Finished sparse_copy in %(duration).2f secs, "
              "%(compression_pct).2f%% reduction in size",
              {'duration': duration, 'compression_pct': compression_pct})


def _copy_partition(session, src_ref, dst_ref, partition, virtual_size):
    # Part of disk taken up by MBR
    virtual_size -= MBR_SIZE_BYTES

    with vdi_attached(session, src_ref, read_only=True) as src:
        src_path = utils.make_dev_path(src, partition=partition)

        with vdi_attached(session, dst_ref, read_only=False) as dst:
            dst_path = utils.make_dev_path(dst, partition=partition)

            _write_partition(session, virtual_size, dst)

            if CONF.xenserver.sparse_copy:
                _sparse_copy(src_path, dst_path, virtual_size)
            else:
                num_blocks = virtual_size / SECTOR_SIZE
                utils.execute('dd',
                              'if=%s' % src_path,
                              'of=%s' % dst_path,
                              'bs=%d' % DD_BLOCKSIZE,
                              'count=%d' % num_blocks,
                              'iflag=direct,sync',
                              'oflag=direct,sync',
                              run_as_root=True)


def _mount_filesystem(dev_path, dir):
    """mounts the device specified by dev_path in dir."""
    try:
        _out, err = utils.execute('mount',
                                 '-t', 'ext2,ext3,ext4,reiserfs',
                                 dev_path, dir, run_as_root=True)
    except processutils.ProcessExecutionError as e:
        err = six.text_type(e)
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
                    # TODO(berrange) passing in a None filename is
                    # rather dubious. We shouldn't be re-implementing
                    # the mount/unmount logic here either, when the
                    # VFSLocalFS impl has direct support for mount
                    # and unmount handling if it were passed a
                    # non-None filename
                    vfs = vfsimpl.VFSLocalFS(
                        imgmodel.LocalFileImage(None, imgmodel.FORMAT_RAW),
                        imgdir=tmpdir)
                    LOG.info('Manipulating interface files directly')
                    # for xenapi, we don't 'inject' admin_password here,
                    # it's handled at instance startup time, nor do we
                    # support injecting arbitrary files here.
                    disk.inject_data_into_fs(vfs,
                                             key, net, metadata, None, None)
            finally:
                utils.execute('umount', dev_path, run_as_root=True)
        else:
            LOG.info('Failed to mount filesystem (expected for '
                     'non-linux instances): %s', err)


def ensure_correct_host(session):
    """Ensure we're connected to the host we're running on. This is the
    required configuration for anything that uses vdi_attached without
    the dom0 flag.
    """
    if session.host_checked:
        return

    this_vm_uuid = get_this_vm_uuid(session)

    try:
        session.call_xenapi('VM.get_by_uuid', this_vm_uuid)
        session.host_checked = True
    except session.XenAPI.Failure as exc:
        if exc.details[0] != 'UUID_INVALID':
            raise
        raise Exception(_('This domU must be running on the host '
                          'specified by connection_url'))


def import_all_migrated_disks(session, instance, import_root=True):
    root_vdi = None
    if import_root:
        root_vdi = _import_migrated_root_disk(session, instance)
    eph_vdis = _import_migrate_ephemeral_disks(session, instance)
    return {'root': root_vdi, 'ephemerals': eph_vdis}


def _import_migrated_root_disk(session, instance):
    chain_label = instance['uuid']
    vdi_label = instance['name']
    return _import_migrated_vhds(session, instance, chain_label, "root",
                                 vdi_label)


def _import_migrate_ephemeral_disks(session, instance):
    ephemeral_vdis = {}
    instance_uuid = instance['uuid']
    ephemeral_gb = instance.old_flavor.ephemeral_gb
    disk_sizes = get_ephemeral_disk_sizes(ephemeral_gb)
    for chain_number, _size in enumerate(disk_sizes, start=1):
        chain_label = instance_uuid + "_ephemeral_%d" % chain_number
        vdi_label = "%(name)s ephemeral (%(number)d)" % dict(
                        name=instance['name'], number=chain_number)
        ephemeral_vdi = _import_migrated_vhds(session, instance,
                                              chain_label, "ephemeral",
                                              vdi_label)
        userdevice = 3 + chain_number
        ephemeral_vdis[str(userdevice)] = ephemeral_vdi
    return ephemeral_vdis


def _import_migrated_vhds(session, instance, chain_label, disk_type,
                          vdi_label):
    """Move and possibly link VHDs via the XAPI plugin."""
    imported_vhds = vm_management.receive_vhd(session, chain_label,
                                              get_sr_path(session),
                                              _make_uuid_stack())

    # Now we rescan the SR so we find the VHDs
    scan_default_sr(session)

    vdi_uuid = imported_vhds['root']['uuid']
    vdi_ref = session.call_xenapi('VDI.get_by_uuid', vdi_uuid)

    # Set name-label so we can find if we need to clean up a failed migration
    _set_vdi_info(session, vdi_ref, disk_type, vdi_label,
                  disk_type, instance)

    return {'uuid': vdi_uuid, 'ref': vdi_ref}


def migrate_vhd(session, instance, vdi_uuid, dest, sr_path, seq_num,
                ephemeral_number=0):
    LOG.debug("Migrating VHD '%(vdi_uuid)s' with seq_num %(seq_num)d",
              {'vdi_uuid': vdi_uuid, 'seq_num': seq_num},
              instance=instance)
    chain_label = instance['uuid']
    if ephemeral_number:
        chain_label = instance['uuid'] + "_ephemeral_%d" % ephemeral_number
    try:
        vm_management.transfer_vhd(session, chain_label, dest, vdi_uuid,
                                   sr_path, seq_num)
    except session.XenAPI.Failure:
        msg = "Failed to transfer vhd to new host"
        LOG.debug(msg, instance=instance, exc_info=True)
        raise exception.MigrationError(reason=msg)


def vm_ref_or_raise(session, instance_name):
    vm_ref = lookup(session, instance_name)
    if vm_ref is None:
        raise exception.InstanceNotFound(instance_id=instance_name)
    return vm_ref


def handle_ipxe_iso(session, instance, cd_vdi, network_info):
    """iPXE ISOs are a mechanism to allow the customer to roll their own
    image.

    To use this feature, a service provider needs to configure the
    appropriate Nova flags, roll an iPXE ISO, then distribute that image
    to customers via Glance.

    NOTE: `mkisofs` is not present by default in the Dom0, so the service
    provider can either add that package manually to Dom0 or include the
    `mkisofs` binary in the image itself.
    """
    boot_menu_url = CONF.xenserver.ipxe_boot_menu_url
    if not boot_menu_url:
        LOG.warning('ipxe_boot_menu_url not set, user will have to'
                    ' enter URL manually...', instance=instance)
        return

    network_name = CONF.xenserver.ipxe_network_name
    if not network_name:
        LOG.warning('ipxe_network_name not set, user will have to'
                    ' enter IP manually...', instance=instance)
        return

    network = None
    for vif in network_info:
        if vif['network']['label'] == network_name:
            network = vif['network']
            break

    if not network:
        LOG.warning("Unable to find network matching '%(network_name)s', "
                    "user will have to enter IP manually...",
                    {'network_name': network_name}, instance=instance)
        return

    sr_path = get_sr_path(session)

    # Unpack IPv4 network info
    subnet = [sn for sn in network['subnets']
              if sn['version'] == 4][0]
    ip = subnet['ips'][0]

    ip_address = ip['address']
    netmask = network_model.get_netmask(ip, subnet)
    gateway = subnet['gateway']['address']
    dns = subnet['dns'][0]['address']

    try:
        disk_management.inject_ipxe_config(session, sr_path, cd_vdi['uuid'],
                                           boot_menu_url, ip_address, netmask,
                                           gateway, dns,
                                           CONF.xenserver.ipxe_mkisofs_cmd)
    except session.XenAPI.Failure as exc:
        _type, _method, error = exc.details[:3]
        if error == 'CommandNotFound':
            LOG.warning("ISO creation tool '%s' does not exist.",
                        CONF.xenserver.ipxe_mkisofs_cmd, instance=instance)
        else:
            raise


def set_other_config_pci(session, vm_ref, params):
    """Set the pci key of other-config parameter to params."""
    other_config = session.call_xenapi("VM.get_other_config", vm_ref)
    other_config['pci'] = params
    session.call_xenapi("VM.set_other_config", vm_ref, other_config)
