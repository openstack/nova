# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

import os
import pickle
import re
import tempfile
import time
import urllib
import uuid
from xml.dom import minidom

from eventlet import event
import glance.client
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.auth.manager import AuthManager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import disk
from nova.virt import images
from nova.virt.xenapi import HelperBase
from nova.virt.xenapi.volume_utils import StorageError


LOG = logging.getLogger("nova.virt.xenapi.vm_utils")

FLAGS = flags.FLAGS
flags.DEFINE_string('default_os_type', 'linux', 'Default OS type')

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


class ImageType:
    """
    Enumeration class for distinguishing different image types
        0 - kernel/ramdisk image (goes on dom0's filesystem)
        1 - disk image (local SR, partitioned by objectstore plugin)
        2 - raw disk image (local SR, NOT partitioned by plugin)
        3 - vhd disk image (local SR, NOT inspected by XS, PV assumed for
            linux, HVM assumed for Windows)
    """

    KERNEL_RAMDISK = 0
    DISK = 1
    DISK_RAW = 2
    DISK_VHD = 3


class VMHelper(HelperBase):
    """
    The class that wraps the helper methods together.
    """

    @classmethod
    def create_vm(cls, session, instance, kernel, ramdisk,
                  use_pv_kernel=False):
        """Create a VM record.  Returns a Deferred that gives the new
        VM reference.
        the use_pv_kernel flag indicates whether the guest is HVM or PV

        There are 3 scenarios:

            1. Using paravirtualization,  kernel passed in

            2. Using paravirtualization, kernel within the image

            3. Using hardware virtualization
        """

        inst_type_id = instance.instance_type_id
        instance_type = instance_types.get_instance_type(inst_type_id)
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
            'name_label': instance.name,
            'other_config': {'allowvssprovider': False},
            'other_config': {},
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
            if instance.kernel_id:
                # 1. Kernel explicitly passed in, use that
                rec['PV_args'] = 'root=/dev/xvda1'
                rec['PV_kernel'] = kernel
                rec['PV_ramdisk'] = ramdisk
            else:
                # 2. Use kernel within the image
                rec['PV_args'] = 'clocksource=jiffies'
                rec['PV_bootloader'] = 'pygrub'
        else:
            # 3. Using hardware virtualization
            rec['platform']['nx'] = 'true'
            rec['HVM_boot_params'] = {'order': 'dc'}
            rec['HVM_boot_policy'] = 'BIOS order'

        LOG.debug(_('Created VM %s...'), instance.name)
        vm_ref = session.call_xenapi('VM.create', rec)
        instance_name = instance.name
        LOG.debug(_('Created VM %(instance_name)s as %(vm_ref)s.') % locals())
        return vm_ref

    @classmethod
    def ensure_free_mem(cls, session, instance):
        inst_type_id = instance.instance_type_id
        instance_type = instance_types.get_instance_type(inst_type_id)
        mem = long(instance_type['memory_mb']) * 1024 * 1024
        #get free memory from host
        host = session.get_xenapi_host()
        host_free_mem = long(session.get_xenapi().host.
                             compute_free_memory(host))
        return host_free_mem >= mem

    @classmethod
    def create_vbd(cls, session, vm_ref, vdi_ref, userdevice, bootable):
        """Create a VBD record.  Returns a Deferred that gives the new
        VBD reference."""
        vbd_rec = {}
        vbd_rec['VM'] = vm_ref
        vbd_rec['VDI'] = vdi_ref
        vbd_rec['userdevice'] = str(userdevice)
        vbd_rec['bootable'] = bootable
        vbd_rec['mode'] = 'RW'
        vbd_rec['type'] = 'disk'
        vbd_rec['unpluggable'] = True
        vbd_rec['empty'] = False
        vbd_rec['other_config'] = {}
        vbd_rec['qos_algorithm_type'] = ''
        vbd_rec['qos_algorithm_params'] = {}
        vbd_rec['qos_supported_algorithms'] = []
        LOG.debug(_('Creating VBD for VM %(vm_ref)s,'
                ' VDI %(vdi_ref)s ... ') % locals())
        vbd_ref = session.call_xenapi('VBD.create', vbd_rec)
        LOG.debug(_('Created VBD %(vbd_ref)s for VM %(vm_ref)s,'
                ' VDI %(vdi_ref)s.') % locals())
        return vbd_ref

    @classmethod
    def find_vbd_by_number(cls, session, vm_ref, number):
        """Get the VBD reference from the device number"""
        vbd_refs = session.get_xenapi().VM.get_VBDs(vm_ref)
        if vbd_refs:
            for vbd_ref in vbd_refs:
                try:
                    vbd_rec = session.get_xenapi().VBD.get_record(vbd_ref)
                    if vbd_rec['userdevice'] == str(number):
                        return vbd_ref
                except cls.XenAPI.Failure, exc:
                    LOG.exception(exc)
        raise StorageError(_('VBD not found in instance %s') % vm_ref)

    @classmethod
    def unplug_vbd(cls, session, vbd_ref):
        """Unplug VBD from VM"""
        try:
            vbd_ref = session.call_xenapi('VBD.unplug', vbd_ref)
        except cls.XenAPI.Failure, exc:
            LOG.exception(exc)
            if exc.details[0] != 'DEVICE_ALREADY_DETACHED':
                raise StorageError(_('Unable to unplug VBD %s') % vbd_ref)

    @classmethod
    def destroy_vbd(cls, session, vbd_ref):
        """Destroy VBD from host database"""
        try:
            task = session.call_xenapi('Async.VBD.destroy', vbd_ref)
            session.wait_for_task(task)
        except cls.XenAPI.Failure, exc:
            LOG.exception(exc)
            raise StorageError(_('Unable to destroy VBD %s') % vbd_ref)

    @classmethod
    def create_vif(cls, session, vm_ref, network_ref, mac_address,
                   dev, rxtx_cap=0):
        """Create a VIF record.  Returns a Deferred that gives the new
        VIF reference."""
        vif_rec = {}
        vif_rec['device'] = str(dev)
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = mac_address
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        vif_rec['qos_algorithm_type'] = "ratelimit" if rxtx_cap else ''
        vif_rec['qos_algorithm_params'] = \
                {"kbps": str(rxtx_cap * 1024)} if rxtx_cap else {}
        LOG.debug(_('Creating VIF for VM %(vm_ref)s,'
                ' network %(network_ref)s.') % locals())
        vif_ref = session.call_xenapi('VIF.create', vif_rec)
        LOG.debug(_('Created VIF %(vif_ref)s for VM %(vm_ref)s,'
                ' network %(network_ref)s.') % locals())
        return vif_ref

    @classmethod
    def create_vdi(cls, session, sr_ref, name_label, virtual_size, read_only):
        """Create a VDI record and returns its reference."""
        vdi_ref = session.get_xenapi().VDI.create(
             {'name_label': name_label,
              'name_description': '',
              'SR': sr_ref,
              'virtual_size': str(virtual_size),
              'type': 'User',
              'sharable': False,
              'read_only': read_only,
              'xenstore_data': {},
              'other_config': {},
              'sm_config': {},
              'tags': []})
        LOG.debug(_('Created VDI %(vdi_ref)s (%(name_label)s,'
                ' %(virtual_size)s, %(read_only)s) on %(sr_ref)s.')
                % locals())
        return vdi_ref

    @classmethod
    def get_vdi_for_vm_safely(cls, session, vm_ref):
        vdi_refs = VMHelper.lookup_vm_vdis(session, vm_ref)
        if vdi_refs is None:
            raise Exception(_("No VDIs found for VM %s") % vm_ref)
        else:
            num_vdis = len(vdi_refs)
            if num_vdis != 1:
                raise Exception(
                        _("Unexpected number of VDIs (%(num_vdis)s) found"
                        " for VM %(vm_ref)s") % locals())

        vdi_ref = vdi_refs[0]
        vdi_rec = session.get_xenapi().VDI.get_record(vdi_ref)
        return vdi_ref, vdi_rec

    @classmethod
    def create_snapshot(cls, session, instance_id, vm_ref, label):
        """Creates Snapshot (Template) VM, Snapshot VBD, Snapshot VDI,
        Snapshot VHD"""
        #TODO(sirp): Add quiesce and VSS locking support when Windows support
        # is added
        LOG.debug(_("Snapshotting VM %(vm_ref)s with label '%(label)s'...")
                % locals())

        vm_vdi_ref, vm_vdi_rec = cls.get_vdi_for_vm_safely(session, vm_ref)
        vm_vdi_uuid = vm_vdi_rec["uuid"]
        sr_ref = vm_vdi_rec["SR"]

        original_parent_uuid = get_vhd_parent_uuid(session, vm_vdi_ref)

        task = session.call_xenapi('Async.VM.snapshot', vm_ref, label)
        template_vm_ref = session.wait_for_task(task, instance_id)
        template_vdi_rec = cls.get_vdi_for_vm_safely(session,
                template_vm_ref)[1]
        template_vdi_uuid = template_vdi_rec["uuid"]

        LOG.debug(_('Created snapshot %(template_vm_ref)s from'
                ' VM %(vm_ref)s.') % locals())

        parent_uuid = wait_for_vhd_coalesce(
            session, instance_id, sr_ref, vm_vdi_ref, original_parent_uuid)

        #TODO(sirp): we need to assert only one parent, not parents two deep
        template_vdi_uuids = {'image': parent_uuid,
                              'snap': template_vdi_uuid}
        return template_vm_ref, template_vdi_uuids

    @classmethod
    def get_sr(cls, session, sr_label='slices'):
        """Finds the SR named by the given name label and returns
        the UUID"""
        return session.call_xenapi('SR.get_by_name_label', sr_label)[0]

    @classmethod
    def get_sr_path(cls, session):
        """Return the path to our storage repository

        This is used when we're dealing with VHDs directly, either by taking
        snapshots or by restoring an image in the DISK_VHD format.
        """
        sr_ref = safe_find_sr(session)
        sr_rec = session.get_xenapi().SR.get_record(sr_ref)
        sr_uuid = sr_rec["uuid"]
        return os.path.join(FLAGS.xenapi_sr_base_path, sr_uuid)

    @classmethod
    def upload_image(cls, session, instance, vdi_uuids, image_id):
        """ Requests that the Glance plugin bundle the specified VDIs and
        push them into Glance using the specified human-friendly name.
        """
        # NOTE(sirp): Currently we only support uploading images as VHD, there
        # is no RAW equivalent (yet)
        logging.debug(_("Asking xapi to upload %(vdi_uuids)s as"
                " ID %(image_id)s") % locals())

        os_type = instance.os_type or FLAGS.default_os_type

        params = {'vdi_uuids': vdi_uuids,
                  'image_id': image_id,
                  'glance_host': FLAGS.glance_host,
                  'glance_port': FLAGS.glance_port,
                  'sr_path': cls.get_sr_path(session),
                  'os_type': os_type}

        kwargs = {'params': pickle.dumps(params)}
        task = session.async_call_plugin('glance', 'upload_vhd', kwargs)
        session.wait_for_task(task, instance.id)

    @classmethod
    def fetch_image(cls, session, instance_id, image, user, project,
                    image_type):
        """
        image_type is interpreted as an ImageType instance
        Related flags:
            xenapi_image_service = ['glance', 'objectstore']
            glance_address = 'address for glance services'
            glance_port = 'port for glance services'
        """
        access = AuthManager().get_access_key(user, project)

        if FLAGS.xenapi_image_service == 'glance':
            return cls._fetch_image_glance(session, instance_id, image,
                                           access, image_type)
        else:
            return cls._fetch_image_objectstore(session, instance_id, image,
                                                access, user.secret,
                                                image_type)

    @classmethod
    def _fetch_image_glance_vhd(cls, session, instance_id, image, access,
                                image_type):
        LOG.debug(_("Asking xapi to fetch vhd image %(image)s")
                    % locals())

        sr_ref = safe_find_sr(session)

        # NOTE(sirp): The Glance plugin runs under Python 2.4 which does not
        # have the `uuid` module. To work around this, we generate the uuids
        # here (under Python 2.6+) and pass them as arguments
        uuid_stack = [str(uuid.uuid4()) for i in xrange(2)]

        params = {'image_id': image,
                  'glance_host': FLAGS.glance_host,
                  'glance_port': FLAGS.glance_port,
                  'uuid_stack': uuid_stack,
                  'sr_path': cls.get_sr_path(session)}

        kwargs = {'params': pickle.dumps(params)}
        task = session.async_call_plugin('glance', 'download_vhd', kwargs)
        vdi_uuid = session.wait_for_task(task, instance_id)

        cls.scan_sr(session, instance_id, sr_ref)

        # Set the name-label to ease debugging
        vdi_ref = session.get_xenapi().VDI.get_by_uuid(vdi_uuid)
        name_label = get_name_label_for_image(image)
        session.get_xenapi().VDI.set_name_label(vdi_ref, name_label)

        LOG.debug(_("xapi 'download_vhd' returned VDI UUID %(vdi_uuid)s")
                  % locals())
        return vdi_uuid

    @classmethod
    def _fetch_image_glance_disk(cls, session, instance_id, image, access,
                                 image_type):
        """Fetch the image from Glance

        NOTE:
        Unlike _fetch_image_glance_vhd, this method does not use the Glance
        plugin; instead, it streams the disks through domU to the VDI
        directly.

        """
        # FIXME(sirp): Since the Glance plugin seems to be required for the
        # VHD disk, it may be worth using the plugin for both VHD and RAW and
        # DISK restores
        sr_ref = safe_find_sr(session)

        client = glance.client.Client(FLAGS.glance_host, FLAGS.glance_port)
        meta, image_file = client.get_image(image)
        virtual_size = int(meta['size'])
        vdi_size = virtual_size
        LOG.debug(_("Size for image %(image)s:%(virtual_size)d") % locals())

        if image_type == ImageType.DISK:
            # Make room for MBR.
            vdi_size += MBR_SIZE_BYTES

        name_label = get_name_label_for_image(image)
        vdi_ref = cls.create_vdi(session, sr_ref, name_label, vdi_size, False)

        with_vdi_attached_here(session, vdi_ref, False,
                               lambda dev:
                               _stream_disk(dev, image_type,
                                            virtual_size, image_file))
        if image_type == ImageType.KERNEL_RAMDISK:
            #we need to invoke a plugin for copying VDI's
            #content into proper path
            LOG.debug(_("Copying VDI %s to /boot/guest on dom0"), vdi_ref)
            fn = "copy_kernel_vdi"
            args = {}
            args['vdi-ref'] = vdi_ref
            #let the plugin copy the correct number of bytes
            args['image-size'] = str(vdi_size)
            task = session.async_call_plugin('glance', fn, args)
            filename = session.wait_for_task(task, instance_id)
            #remove the VDI as it is not needed anymore
            session.get_xenapi().VDI.destroy(vdi_ref)
            LOG.debug(_("Kernel/Ramdisk VDI %s destroyed"), vdi_ref)
            return filename
        else:
            return session.get_xenapi().VDI.get_uuid(vdi_ref)

    @classmethod
    def determine_disk_image_type(cls, instance):
        """Disk Image Types are used to determine where the kernel will reside
        within an image. To figure out which type we're dealing with, we use
        the following rules:

        1. If we're using Glance, we can use the image_type field to
           determine the image_type

        2. If we're not using Glance, then we need to deduce this based on
           whether a kernel_id is specified.
        """
        def log_disk_format(image_type):
            pretty_format = {ImageType.KERNEL_RAMDISK: 'KERNEL_RAMDISK',
                             ImageType.DISK: 'DISK',
                             ImageType.DISK_RAW: 'DISK_RAW',
                             ImageType.DISK_VHD: 'DISK_VHD'}
            disk_format = pretty_format[image_type]
            image_id = instance.image_id
            instance_id = instance.id
            LOG.debug(_("Detected %(disk_format)s format for image "
                        "%(image_id)s, instance %(instance_id)s") % locals())

        def determine_from_glance():
            glance_disk_format2nova_type = {
                'ami': ImageType.DISK,
                'aki': ImageType.KERNEL_RAMDISK,
                'ari': ImageType.KERNEL_RAMDISK,
                'raw': ImageType.DISK_RAW,
                'vhd': ImageType.DISK_VHD}
            client = glance.client.Client(FLAGS.glance_host, FLAGS.glance_port)
            meta = client.get_image_meta(instance.image_id)
            disk_format = meta['disk_format']
            try:
                return glance_disk_format2nova_type[disk_format]
            except KeyError:
                raise exception.NotFound(
                    _("Unrecognized disk_format '%(disk_format)s'")
                    % locals())

        def determine_from_instance():
            if instance.kernel_id:
                return ImageType.DISK
            else:
                return ImageType.DISK_RAW

        # FIXME(sirp): can we unify the ImageService and xenapi_image_service
        # abstractions?
        if FLAGS.xenapi_image_service == 'glance':
            image_type = determine_from_glance()
        else:
            image_type = determine_from_instance()

        log_disk_format(image_type)
        return image_type

    @classmethod
    def _fetch_image_glance(cls, session, instance_id, image, access,
                            image_type):
        if image_type == ImageType.DISK_VHD:
            return cls._fetch_image_glance_vhd(
                session, instance_id, image, access, image_type)
        else:
            return cls._fetch_image_glance_disk(
                session, instance_id, image, access, image_type)

    @classmethod
    def _fetch_image_objectstore(cls, session, instance_id, image, access,
                                 secret, image_type):
        url = images.image_url(image)
        LOG.debug(_("Asking xapi to fetch %(url)s as %(access)s") % locals())
        if image_type == ImageType.KERNEL_RAMDISK:
            fn = 'get_kernel'
        else:
            fn = 'get_vdi'
        args = {}
        args['src_url'] = url
        args['username'] = access
        args['password'] = secret
        args['add_partition'] = 'false'
        args['raw'] = 'false'
        if image_type != ImageType.KERNEL_RAMDISK:
            args['add_partition'] = 'true'
            if image_type == ImageType.DISK_RAW:
                args['raw'] = 'true'
        task = session.async_call_plugin('objectstore', fn, args)
        uuid = session.wait_for_task(task, instance_id)
        return uuid

    @classmethod
    def determine_is_pv(cls, session, instance_id, vdi_ref, disk_image_type,
                        os_type):
        """
        Determine whether the VM will use a paravirtualized kernel or if it
        will use hardware virtualization.

            1. Objectstore (any image type):
               We use plugin to figure out whether the VDI uses PV

            2. Glance (VHD): then we use `os_type`, raise if not set

            3. Glance (DISK_RAW): use Pygrub to figure out if pv kernel is
               available

            4. Glance (DISK): pv is assumed
        """
        if FLAGS.xenapi_image_service == 'glance':
            # 2, 3, 4: Glance
            return cls._determine_is_pv_glance(
              session, vdi_ref, disk_image_type, os_type)
        else:
            # 1. Objecstore
            return cls._determine_is_pv_objectstore(session, instance_id,
                                                    vdi_ref)

    @classmethod
    def _determine_is_pv_objectstore(cls, session, instance_id, vdi_ref):
        LOG.debug(_("Looking up vdi %s for PV kernel"), vdi_ref)
        fn = "is_vdi_pv"
        args = {}
        args['vdi-ref'] = vdi_ref
        task = session.async_call_plugin('objectstore', fn, args)
        pv_str = session.wait_for_task(task, instance_id)
        pv = None
        if pv_str.lower() == 'true':
            pv = True
        elif pv_str.lower() == 'false':
            pv = False
        LOG.debug(_("PV Kernel in VDI:%s"), pv)
        return pv

    @classmethod
    def _determine_is_pv_glance(cls, session, vdi_ref, disk_image_type,
                                os_type):
        """
        For a Glance image, determine if we need paravirtualization.

        The relevant scenarios are:
            2. Glance (VHD): then we use `os_type`, raise if not set

            3. Glance (DISK_RAW): use Pygrub to figure out if pv kernel is
               available

            4. Glance (DISK): pv is assumed
        """

        LOG.debug(_("Looking up vdi %s for PV kernel"), vdi_ref)
        if disk_image_type == ImageType.DISK_VHD:
            # 2. VHD
            if os_type == 'windows':
                is_pv = False
            else:
                is_pv = True
        elif disk_image_type == ImageType.DISK_RAW:
            # 3. RAW
            is_pv = with_vdi_attached_here(session, vdi_ref, True, _is_vdi_pv)
        elif disk_image_type == ImageType.DISK:
            # 4. Disk
            is_pv = True
        else:
            raise exception.Error(_("Unknown image format %(disk_image_type)s")
                                  % locals())

        return is_pv

    @classmethod
    def lookup(cls, session, name_label):
        """Look the instance i up, and returns it if available"""
        vm_refs = session.get_xenapi().VM.get_by_name_label(name_label)
        n = len(vm_refs)
        if n == 0:
            return None
        elif n > 1:
            raise exception.Duplicate(_('duplicate name found: %s') %
                                        name_label)
        else:
            return vm_refs[0]

    @classmethod
    def lookup_vm_vdis(cls, session, vm_ref):
        """Look for the VDIs that are attached to the VM"""
        # Firstly we get the VBDs, then the VDIs.
        # TODO(Armando): do we leave the read-only devices?
        vbd_refs = session.get_xenapi().VM.get_VBDs(vm_ref)
        vdi_refs = []
        if vbd_refs:
            for vbd_ref in vbd_refs:
                try:
                    vdi_ref = session.get_xenapi().VBD.get_VDI(vbd_ref)
                    # Test valid VDI
                    record = session.get_xenapi().VDI.get_record(vdi_ref)
                    LOG.debug(_('VDI %s is still available'), record['uuid'])
                except cls.XenAPI.Failure, exc:
                    LOG.exception(exc)
                else:
                    vdi_refs.append(vdi_ref)
            if len(vdi_refs) > 0:
                return vdi_refs
            else:
                return None

    @classmethod
    def preconfigure_instance(cls, session, instance, vdi_ref, network_info):
        """Makes alterations to the image before launching as part of spawn.
        """

        # As mounting the image VDI is expensive, we only want do do it once,
        # if at all, so determine whether it's required first, and then do
        # everything
        mount_required = False
        key, net = _prepare_injectables(instance, network_info)
        mount_required = key or net
        if not mount_required:
            return

        with_vdi_attached_here(session, vdi_ref, False,
                               lambda dev: _mounted_processing(dev, key, net))

    @classmethod
    def lookup_kernel_ramdisk(cls, session, vm):
        vm_rec = session.get_xenapi().VM.get_record(vm)
        if 'PV_kernel' in vm_rec and 'PV_ramdisk' in vm_rec:
            return (vm_rec['PV_kernel'], vm_rec['PV_ramdisk'])
        else:
            return (None, None)

    @classmethod
    def compile_info(cls, record):
        """Fill record with VM status information"""
        LOG.info(_("(VM_UTILS) xenserver vm state -> |%s|"),
                 record['power_state'])
        LOG.info(_("(VM_UTILS) xenapi power_state -> |%s|"),
                 XENAPI_POWER_STATE[record['power_state']])
        return {'state': XENAPI_POWER_STATE[record['power_state']],
                'max_mem': long(record['memory_static_max']) >> 10,
                'mem': long(record['memory_dynamic_max']) >> 10,
                'num_cpu': record['VCPUs_max'],
                'cpu_time': 0}

    @classmethod
    def compile_diagnostics(cls, session, record):
        """Compile VM diagnostics data"""
        try:
            host = session.get_xenapi_host()
            host_ip = session.get_xenapi().host.get_record(host)["address"]
        except (cls.XenAPI.Failure, KeyError) as e:
            return {"Unable to retrieve diagnostics": e}

        try:
            diags = {}
            xml = get_rrd(host_ip, record["uuid"])
            if xml:
                rrd = minidom.parseString(xml)
                for i, node in enumerate(rrd.firstChild.childNodes):
                    # We don't want all of the extra garbage
                    if i >= 3 and i <= 11:
                        ref = node.childNodes
                        # Name and Value
                        if len(ref) > 6:
                            diags[ref[0].firstChild.data] = \
                                ref[6].firstChild.data
            return diags
        except cls.XenAPI.Failure as e:
            return {"Unable to retrieve diagnostics": e}

    @classmethod
    def scan_sr(cls, session, instance_id=None, sr_ref=None):
        """Scans the SR specified by sr_ref"""
        if sr_ref:
            LOG.debug(_("Re-scanning SR %s"), sr_ref)
            task = session.call_xenapi('Async.SR.scan', sr_ref)
            session.wait_for_task(task, instance_id)

    @classmethod
    def scan_default_sr(cls, session):
        """Looks for the system default SR and triggers a re-scan"""
        #FIXME(sirp/mdietz): refactor scan_default_sr in there
        sr_ref = cls.get_sr(session)
        session.call_xenapi('SR.scan', sr_ref)


def get_rrd(host, uuid):
    """Return the VM RRD XML as a string"""
    try:
        xml = urllib.urlopen("http://%s:%s@%s/vm_rrd?uuid=%s" % (
            FLAGS.xenapi_connection_username,
            FLAGS.xenapi_connection_password,
            host,
            uuid))
        return xml.read()
    except IOError:
        return None


#TODO(sirp): This code comes from XS5.6 pluginlib.py, we should refactor to
# use that implmenetation
def get_vhd_parent(session, vdi_rec):
    """
    Returns the VHD parent of the given VDI record, as a (ref, rec) pair.
    Returns None if we're at the root of the tree.
    """
    if 'vhd-parent' in vdi_rec['sm_config']:
        parent_uuid = vdi_rec['sm_config']['vhd-parent']
        parent_ref = session.get_xenapi().VDI.get_by_uuid(parent_uuid)
        parent_rec = session.get_xenapi().VDI.get_record(parent_ref)
        vdi_uuid = vdi_rec['uuid']
        LOG.debug(_("VHD %(vdi_uuid)s has parent %(parent_ref)s") % locals())
        return parent_ref, parent_rec
    else:
        return None


def get_vhd_parent_uuid(session, vdi_ref):
    vdi_rec = session.get_xenapi().VDI.get_record(vdi_ref)
    ret = get_vhd_parent(session, vdi_rec)
    if ret:
        parent_ref, parent_rec = ret
        return parent_rec["uuid"]
    else:
        return None


def wait_for_vhd_coalesce(session, instance_id, sr_ref, vdi_ref,
                          original_parent_uuid):
    """ Spin until the parent VHD is coalesced into its parent VHD

    Before coalesce:
        * original_parent_vhd
            * parent_vhd
                snapshot

    Atter coalesce:
        * parent_vhd
            snapshot
    """
    max_attempts = FLAGS.xenapi_vhd_coalesce_max_attempts
    attempts = {'counter': 0}

    def _poll_vhds():
        attempts['counter'] += 1
        if attempts['counter'] > max_attempts:
            counter = attempts['counter']
            msg = (_("VHD coalesce attempts exceeded (%(counter)d >"
                    " %(max_attempts)d), giving up...") % locals())
            raise exception.Error(msg)

        VMHelper.scan_sr(session, instance_id, sr_ref)
        parent_uuid = get_vhd_parent_uuid(session, vdi_ref)
        if original_parent_uuid and (parent_uuid != original_parent_uuid):
            LOG.debug(_("Parent %(parent_uuid)s doesn't match original parent"
                    " %(original_parent_uuid)s, waiting for coalesce...")
                    % locals())
        else:
            # Breakout of the loop (normally) and return the parent_uuid
            raise utils.LoopingCallDone(parent_uuid)

    loop = utils.LoopingCall(_poll_vhds)
    loop.start(FLAGS.xenapi_vhd_coalesce_poll_interval, now=True)
    parent_uuid = loop.wait()
    return parent_uuid


def get_vdi_for_vm_safely(session, vm_ref):
    vdi_refs = VMHelper.lookup_vm_vdis(session, vm_ref)
    if vdi_refs is None:
        raise Exception(_("No VDIs found for VM %s") % vm_ref)
    else:
        num_vdis = len(vdi_refs)
        if num_vdis != 1:
            raise Exception(_("Unexpected number of VDIs (%(num_vdis)s) found"
                    " for VM %(vm_ref)s") % locals())

    vdi_ref = vdi_refs[0]
    vdi_rec = session.get_xenapi().VDI.get_record(vdi_ref)
    return vdi_ref, vdi_rec


def safe_find_sr(session):
    """Same as find_sr except raises a NotFound exception if SR cannot be
    determined
    """
    sr_ref = find_sr(session)
    if sr_ref is None:
        raise exception.NotFound(_('Cannot find SR to read/write VDI'))
    return sr_ref


def find_sr(session):
    """Return the storage repository to hold VM images"""
    host = session.get_xenapi_host()
    sr_refs = session.get_xenapi().SR.get_all()
    for sr_ref in sr_refs:
        sr_rec = session.get_xenapi().SR.get_record(sr_ref)
        if not ('i18n-key' in sr_rec['other_config'] and
                sr_rec['other_config']['i18n-key'] == 'local-storage'):
            continue
        for pbd_ref in sr_rec['PBDs']:
            pbd_rec = session.get_xenapi().PBD.get_record(pbd_ref)
            if pbd_rec['host'] == host:
                return sr_ref
    return None


def remap_vbd_dev(dev):
    """Return the appropriate location for a plugged-in VBD device

    Ubuntu Maverick moved xvd? -> sd?. This is considered a bug and will be
    fixed in future versions:
        https://bugs.launchpad.net/ubuntu/+source/linux/+bug/684875

    For now, we work around it by just doing a string replace.
    """
    # NOTE(sirp): This hack can go away when we pull support for Maverick
    should_remap = FLAGS.xenapi_remap_vbd_dev
    if not should_remap:
        return dev

    old_prefix = 'xvd'
    new_prefix = FLAGS.xenapi_remap_vbd_dev_prefix
    remapped_dev = dev.replace(old_prefix, new_prefix)

    return remapped_dev


def with_vdi_attached_here(session, vdi_ref, read_only, f):
    this_vm_ref = get_this_vm_ref(session)
    vbd_rec = {}
    vbd_rec['VM'] = this_vm_ref
    vbd_rec['VDI'] = vdi_ref
    vbd_rec['userdevice'] = 'autodetect'
    vbd_rec['bootable'] = False
    vbd_rec['mode'] = read_only and 'RO' or 'RW'
    vbd_rec['type'] = 'disk'
    vbd_rec['unpluggable'] = True
    vbd_rec['empty'] = False
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    LOG.debug(_('Creating VBD for VDI %s ... '), vdi_ref)
    vbd_ref = session.get_xenapi().VBD.create(vbd_rec)
    LOG.debug(_('Creating VBD for VDI %s done.'), vdi_ref)
    try:
        LOG.debug(_('Plugging VBD %s ... '), vbd_ref)
        session.get_xenapi().VBD.plug(vbd_ref)
        LOG.debug(_('Plugging VBD %s done.'), vbd_ref)
        orig_dev = session.get_xenapi().VBD.get_device(vbd_ref)
        LOG.debug(_('VBD %(vbd_ref)s plugged as %(orig_dev)s') % locals())
        dev = remap_vbd_dev(orig_dev)
        if dev != orig_dev:
            LOG.debug(_('VBD %(vbd_ref)s plugged into wrong dev, '
                        'remapping to %(dev)s') % locals())
        return f(dev)
    finally:
        LOG.debug(_('Destroying VBD for VDI %s ... '), vdi_ref)
        vbd_unplug_with_retry(session, vbd_ref)
        ignore_failure(session.get_xenapi().VBD.destroy, vbd_ref)
        LOG.debug(_('Destroying VBD for VDI %s done.'), vdi_ref)


def vbd_unplug_with_retry(session, vbd_ref):
    """Call VBD.unplug on the given VBD, with a retry if we get
    DEVICE_DETACH_REJECTED.  For reasons which I don't understand, we're
    seeing the device still in use, even when all processes using the device
    should be dead."""
    # FIXME(sirp): We can use LoopingCall here w/o blocking sleep()
    while True:
        try:
            session.get_xenapi().VBD.unplug(vbd_ref)
            LOG.debug(_('VBD.unplug successful first time.'))
            return
        except VMHelper.XenAPI.Failure, e:
            if (len(e.details) > 0 and
                e.details[0] == 'DEVICE_DETACH_REJECTED'):
                LOG.debug(_('VBD.unplug rejected: retrying...'))
                time.sleep(1)
                LOG.debug(_('Not sleeping anymore!'))
            elif (len(e.details) > 0 and
                  e.details[0] == 'DEVICE_ALREADY_DETACHED'):
                LOG.debug(_('VBD.unplug successful eventually.'))
                return
            else:
                LOG.error(_('Ignoring XenAPI.Failure in VBD.unplug: %s'),
                              e)
                return


def ignore_failure(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except VMHelper.XenAPI.Failure, e:
        LOG.error(_('Ignoring XenAPI.Failure %s'), e)
        return None


def get_this_vm_uuid():
    with file('/sys/hypervisor/uuid') as f:
        return f.readline().strip()


def get_this_vm_ref(session):
    return session.get_xenapi().VM.get_by_uuid(get_this_vm_uuid())


def _is_vdi_pv(dev):
    LOG.debug(_("Running pygrub against %s"), dev)
    output = os.popen('pygrub -qn /dev/%s' % dev)
    for line in output.readlines():
        #try to find kernel string
        m = re.search('(?<=kernel:)/.*(?:>)', line)
        if m and m.group(0).find('xen') != -1:
            LOG.debug(_("Found Xen kernel %s") % m.group(0))
            return True
    LOG.debug(_("No Xen kernel found.  Booting HVM."))
    return False


def _stream_disk(dev, image_type, virtual_size, image_file):
    offset = 0
    if image_type == ImageType.DISK:
        offset = MBR_SIZE_BYTES
        _write_partition(virtual_size, dev)

    with open('/dev/%s' % dev, 'wb') as f:
        f.seek(offset)
        for chunk in image_file:
            f.write(chunk)


def _write_partition(virtual_size, dev):
    dest = '/dev/%s' % dev
    mbr_last = MBR_SIZE_SECTORS - 1
    primary_first = MBR_SIZE_SECTORS
    primary_last = MBR_SIZE_SECTORS + (virtual_size / SECTOR_SIZE) - 1

    LOG.debug(_('Writing partition table %(primary_first)d %(primary_last)d'
            ' to %(dest)s...') % locals())

    def execute(*cmd, **kwargs):
        return utils.execute(*cmd, **kwargs)

    execute('sudo', 'parted', '--script', dest, 'mklabel', 'msdos')
    execute('sudo', 'parted', '--script', dest, 'mkpart', 'primary',
            '%ds' % primary_first,
            '%ds' % primary_last)

    LOG.debug(_('Writing partition table %s done.'), dest)


def get_name_label_for_image(image):
    # TODO(sirp): This should eventually be the URI for the Glance image
    return _('Glance image %s') % image


def _mount_filesystem(dev_path, dir):
    """mounts the device specified by dev_path in dir"""
    try:
        out, err = utils.execute('sudo', 'mount',
                                 '-t', 'ext2,ext3',
                                 dev_path, dir)
    except exception.ProcessExecutionError as e:
        err = str(e)
    return err


def _find_guest_agent(base_dir, agent_rel_path):
    """
    tries to locate a guest agent at the path
    specificed by agent_rel_path
    """
    agent_path = os.path.join(base_dir, agent_rel_path)
    if os.path.isfile(agent_path):
        # The presence of the guest agent
        # file indicates that this instance can
        # reconfigure the network from xenstore data,
        # so manipulation of files in /etc is not
        # required
        LOG.info(_('XenServer tools installed in this '
                'image are capable of network injection.  '
                'Networking files will not be'
                'manipulated'))
        return True
    xe_daemon_filename = os.path.join(base_dir,
        'usr', 'sbin', 'xe-daemon')
    if os.path.isfile(xe_daemon_filename):
        LOG.info(_('XenServer tools are present '
                'in this image but are not capable '
                'of network injection'))
    else:
        LOG.info(_('XenServer tools are not '
                'installed in this image'))
    return False


def _mounted_processing(device, key, net):
    """Callback which runs with the image VDI attached"""

    dev_path = '/dev/' + device + '1'  # NB: Partition 1 hardcoded
    tmpdir = tempfile.mkdtemp()
    try:
        # Mount only Linux filesystems, to avoid disturbing NTFS images
        err = _mount_filesystem(dev_path, tmpdir)
        if not err:
            try:
                # This try block ensures that the umount occurs
                if not _find_guest_agent(tmpdir, FLAGS.xenapi_agent_path):
                    LOG.info(_('Manipulating interface files '
                            'directly'))
                    disk.inject_data_into_fs(tmpdir, key, net,
                        utils.execute)
            finally:
                utils.execute('sudo', 'umount', dev_path)
        else:
            LOG.info(_('Failed to mount filesystem (expected for '
                'non-linux instances): %s') % err)
    finally:
        # remove temporary directory
        os.rmdir(tmpdir)


def _prepare_injectables(inst, networks_info):
    """
    prepares the ssh key and the network configuration file to be
    injected into the disk image
    """
    #do the import here - Cheetah.Template will be loaded
    #only if injection is performed
    from Cheetah import Template as t
    template = t.Template
    template_data = open(FLAGS.injected_network_template).read()

    key = str(inst['key_data'])
    net = None
    if networks_info:
        ifc_num = -1
        interfaces_info = []
        have_injected_networks = False
        for (network_ref, info) in networks_info:
            ifc_num += 1
            if not network_ref['injected']:
                continue

            have_injected_networks = True
            ip_v4 = ip_v6 = None
            if 'ips' in info and len(info['ips']) > 0:
                ip_v4 = info['ips'][0]
            if 'ip6s' in info and len(info['ip6s']) > 0:
                ip_v6 = info['ip6s'][0]
            if len(info['dns']) > 0:
                dns = info['dns'][0]
            interface_info = {'name': 'eth%d' % ifc_num,
                              'address': ip_v4 and ip_v4['ip'] or '',
                              'netmask': ip_v4 and ip_v4['netmask'] or '',
                              'gateway': info['gateway'],
                              'broadcast': info['broadcast'],
                              'dns': dns,
                              'address_v6': ip_v6 and ip_v6['ip'] or '',
                              'netmask_v6': ip_v6 and ip_v6['netmask'] or '',
                              'gateway_v6': ip_v6 and info['gateway6'] or '',
                              'use_ipv6': FLAGS.use_ipv6}
            interfaces_info.append(interface_info)

        if have_injected_networks:
            net = str(template(template_data,
                                searchList=[{'interfaces': interfaces_info,
                                            'use_ipv6': FLAGS.use_ipv6}]))
    return key, net
