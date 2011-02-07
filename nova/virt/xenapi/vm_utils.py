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
import time
import urllib
from xml.dom import minidom

from eventlet import event
import glance.client
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.auth.manager import AuthManager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import images
from nova.virt.xenapi import HelperBase
from nova.virt.xenapi.volume_utils import StorageError


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.virt.xenapi.vm_utils")

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
    """

    KERNEL_RAMDISK = 0
    DISK = 1
    DISK_RAW = 2


class VMHelper(HelperBase):
    """
    The class that wraps the helper methods together.
    """

    @classmethod
    def create_vm(cls, session, instance, kernel, ramdisk, pv_kernel=False):
        """Create a VM record.  Returns a Deferred that gives the new
        VM reference.
        the pv_kernel flag indicates whether the guest is HVM or PV
        """

        instance_type = instance_types.INSTANCE_TYPES[instance.instance_type]
        mem = str(long(instance_type['memory_mb']) * 1024 * 1024)
        vcpus = str(instance_type['vcpus'])
        rec = {
            'name_label': instance.name,
            'name_description': '',
            'is_a_template': False,
            'memory_static_min': '0',
            'memory_static_max': mem,
            'memory_dynamic_min': mem,
            'memory_dynamic_max': mem,
            'VCPUs_at_startup': vcpus,
            'VCPUs_max': vcpus,
            'VCPUs_params': {},
            'actions_after_shutdown': 'destroy',
            'actions_after_reboot': 'restart',
            'actions_after_crash': 'destroy',
            'PV_bootloader': '',
            'PV_kernel': '',
            'PV_ramdisk': '',
            'PV_args': '',
            'PV_bootloader_args': '',
            'PV_legacy_args': '',
            'HVM_boot_policy': '',
            'HVM_boot_params': {},
            'platform': {},
            'PCI_bus': '',
            'recommendations': '',
            'affinity': '',
            'user_version': '0',
            'other_config': {},
            }
        #Complete VM configuration record according to the image type
        #non-raw/raw with PV kernel/raw in HVM mode
        if instance.kernel_id:
            rec['PV_bootloader'] = ''
            rec['PV_kernel'] = kernel
            rec['PV_ramdisk'] = ramdisk
            rec['PV_args'] = 'root=/dev/xvda1'
            rec['PV_bootloader_args'] = ''
            rec['PV_legacy_args'] = ''
        else:
            if pv_kernel:
                rec['PV_args'] = 'noninteractive'
                rec['PV_bootloader'] = 'pygrub'
            else:
                rec['HVM_boot_policy'] = 'BIOS order'
                rec['HVM_boot_params'] = {'order': 'dc'}
                rec['platform'] = {'acpi': 'true', 'apic': 'true',
                                   'pae': 'true', 'viridian': 'true'}
        LOG.debug(_('Created VM %s...'), instance.name)
        vm_ref = session.call_xenapi('VM.create', rec)
        instance_name = instance.name
        LOG.debug(_('Created VM %(instance_name)s as %(vm_ref)s.') % locals())
        return vm_ref

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
        vbds = session.get_xenapi().VM.get_VBDs(vm_ref)
        if vbds:
            for vbd in vbds:
                try:
                    vbd_rec = session.get_xenapi().VBD.get_record(vbd)
                    if vbd_rec['userdevice'] == str(number):
                        return vbd
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
            #FIXME(armando): find a solution to missing instance_id
            #with Josh Kearney
            session.wait_for_task(0, task)
        except cls.XenAPI.Failure, exc:
            LOG.exception(exc)
            raise StorageError(_('Unable to destroy VBD %s') % vbd_ref)

    @classmethod
    def create_vif(cls, session, vm_ref, network_ref, mac_address):
        """Create a VIF record.  Returns a Deferred that gives the new
        VIF reference."""
        vif_rec = {}
        vif_rec['device'] = '0'
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = mac_address
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        vif_rec['qos_algorithm_type'] = ''
        vif_rec['qos_algorithm_params'] = {}
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
    def create_snapshot(cls, session, instance_id, vm_ref, label):
        """ Creates Snapshot (Template) VM, Snapshot VBD, Snapshot VDI,
        Snapshot VHD
        """
        #TODO(sirp): Add quiesce and VSS locking support when Windows support
        # is added
        LOG.debug(_("Snapshotting VM %(vm_ref)s with label '%(label)s'...")
                % locals())

        vm_vdi_ref, vm_vdi_rec = get_vdi_for_vm_safely(session, vm_ref)
        vm_vdi_uuid = vm_vdi_rec["uuid"]
        sr_ref = vm_vdi_rec["SR"]

        original_parent_uuid = get_vhd_parent_uuid(session, vm_vdi_ref)

        task = session.call_xenapi('Async.VM.snapshot', vm_ref, label)
        template_vm_ref = session.wait_for_task(instance_id, task)
        template_vdi_rec = get_vdi_for_vm_safely(session, template_vm_ref)[1]
        template_vdi_uuid = template_vdi_rec["uuid"]

        LOG.debug(_('Created snapshot %(template_vm_ref)s from'
                ' VM %(vm_ref)s.') % locals())

        parent_uuid = wait_for_vhd_coalesce(
            session, instance_id, sr_ref, vm_vdi_ref, original_parent_uuid)

        #TODO(sirp): we need to assert only one parent, not parents two deep
        return template_vm_ref, [template_vdi_uuid, parent_uuid]

    @classmethod
    def upload_image(cls, session, instance_id, vdi_uuids, image_id):
        """ Requests that the Glance plugin bundle the specified VDIs and
        push them into Glance using the specified human-friendly name.
        """
        logging.debug(_("Asking xapi to upload %(vdi_uuids)s as"
                " ID %(image_id)s") % locals())

        params = {'vdi_uuids': vdi_uuids,
                  'image_id': image_id,
                  'glance_host': FLAGS.glance_host,
                  'glance_port': FLAGS.glance_port}

        kwargs = {'params': pickle.dumps(params)}
        task = session.async_call_plugin('glance', 'put_vdis', kwargs)
        session.wait_for_task(instance_id, task)

    @classmethod
    def fetch_image(cls, session, instance_id, image, user, project, type):
        """
        type is interpreted as an ImageType instance
        Related flags:
            xenapi_image_service = ['glance', 'objectstore']
            glance_address = 'address for glance services'
            glance_port = 'port for glance services'
        """
        access = AuthManager().get_access_key(user, project)

        if FLAGS.xenapi_image_service == 'glance':
            return cls._fetch_image_glance(session, instance_id, image,
                                           access, type)
        else:
            return cls._fetch_image_objectstore(session, instance_id, image,
                                                access, user.secret, type)

    @classmethod
    def _fetch_image_glance(cls, session, instance_id, image, access, type):
        sr = find_sr(session)
        if sr is None:
            raise exception.NotFound('Cannot find SR to write VDI to')

        c = glance.client.Client(FLAGS.glance_host, FLAGS.glance_port)

        meta, image_file = c.get_image(image)
        virtual_size = int(meta['size'])
        vdi_size = virtual_size
        LOG.debug(_("Size for image %(image)s:%(virtual_size)d") % locals())
        if type == ImageType.DISK:
            # Make room for MBR.
            vdi_size += MBR_SIZE_BYTES

        vdi = cls.create_vdi(session, sr, _('Glance image %s') % image,
                             vdi_size, False)

        with_vdi_attached_here(session, vdi, False,
                               lambda dev:
                               _stream_disk(dev, type,
                                            virtual_size, image_file))
        if (type == ImageType.KERNEL_RAMDISK):
            #we need to invoke a plugin for copying VDI's
            #content into proper path
            LOG.debug(_("Copying VDI %s to /boot/guest on dom0"), vdi)
            fn = "copy_kernel_vdi"
            args = {}
            args['vdi-ref'] = vdi
            #let the plugin copy the correct number of bytes
            args['image-size'] = str(vdi_size)
            task = session.async_call_plugin('glance', fn, args)
            filename = session.wait_for_task(instance_id, task)
            #remove the VDI as it is not needed anymore
            session.get_xenapi().VDI.destroy(vdi)
            LOG.debug(_("Kernel/Ramdisk VDI %s destroyed"), vdi)
            return filename
        else:
            return session.get_xenapi().VDI.get_uuid(vdi)

    @classmethod
    def _fetch_image_objectstore(cls, session, instance_id, image, access,
                                 secret, type):
        url = images.image_url(image)
        LOG.debug(_("Asking xapi to fetch %(url)s as %(access)s") % locals())
        fn = (type != ImageType.KERNEL_RAMDISK) and 'get_vdi' or 'get_kernel'
        args = {}
        args['src_url'] = url
        args['username'] = access
        args['password'] = secret
        args['add_partition'] = 'false'
        args['raw'] = 'false'
        if type != ImageType.KERNEL_RAMDISK:
            args['add_partition'] = 'true'
            if type == ImageType.DISK_RAW:
                args['raw'] = 'true'
        task = session.async_call_plugin('objectstore', fn, args)
        uuid = session.wait_for_task(instance_id, task)
        return uuid

    @classmethod
    def lookup_image(cls, session, instance_id, vdi_ref):
        if FLAGS.xenapi_image_service == 'glance':
            return cls._lookup_image_glance(session, vdi_ref)
        else:
            return cls._lookup_image_objectstore(session, instance_id, vdi_ref)

    @classmethod
    def _lookup_image_objectstore(cls, session, instance_id, vdi_ref):
        LOG.debug(_("Looking up vdi %s for PV kernel"), vdi_ref)
        fn = "is_vdi_pv"
        args = {}
        args['vdi-ref'] = vdi_ref
        task = session.async_call_plugin('objectstore', fn, args)
        pv_str = session.wait_for_task(instance_id, task)
        pv = None
        if pv_str.lower() == 'true':
            pv = True
        elif pv_str.lower() == 'false':
            pv = False
        LOG.debug(_("PV Kernel in VDI:%d"), pv)
        return pv

    @classmethod
    def _lookup_image_glance(cls, session, vdi_ref):
        LOG.debug(_("Looking up vdi %s for PV kernel"), vdi_ref)

        def is_vdi_pv(dev):
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
        return with_vdi_attached_here(session, vdi_ref, True, is_vdi_pv)

    @classmethod
    def lookup(cls, session, i):
        """Look the instance i up, and returns it if available"""
        vms = session.get_xenapi().VM.get_by_name_label(i)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise exception.Duplicate(_('duplicate name found: %s') % i)
        else:
            return vms[0]

    @classmethod
    def lookup_vm_vdis(cls, session, vm):
        """Look for the VDIs that are attached to the VM"""
        # Firstly we get the VBDs, then the VDIs.
        # TODO(Armando): do we leave the read-only devices?
        vbds = session.get_xenapi().VM.get_VBDs(vm)
        vdis = []
        if vbds:
            for vbd in vbds:
                try:
                    vdi = session.get_xenapi().VBD.get_VDI(vbd)
                    # Test valid VDI
                    record = session.get_xenapi().VDI.get_record(vdi)
                    LOG.debug(_('VDI %s is still available'), record['uuid'])
                except cls.XenAPI.Failure, exc:
                    LOG.exception(exc)
                else:
                    vdis.append(vdi)
            if len(vdis) > 0:
                return vdis
            else:
                return None
    @classmethod
    def lookup_kernel_ramdisk(cls,session,vm):
        vm_rec = session.get_xenapi().VM.get_record(vm)
        return (vm_rec['PV_kernel'],vm_rec['PV_ramdisk'])

    
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


def scan_sr(session, instance_id, sr_ref):
    LOG.debug(_("Re-scanning SR %s"), sr_ref)
    task = session.call_xenapi('Async.SR.scan', sr_ref)
    session.wait_for_task(instance_id, task)


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

        scan_sr(session, instance_id, sr_ref)
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


def find_sr(session):
    host = session.get_xenapi_host()
    srs = session.get_xenapi().SR.get_all()
    for sr in srs:
        sr_rec = session.get_xenapi().SR.get_record(sr)
        if not ('i18n-key' in sr_rec['other_config'] and
                sr_rec['other_config']['i18n-key'] == 'local-storage'):
            continue
        for pbd in sr_rec['PBDs']:
            pbd_rec = session.get_xenapi().PBD.get_record(pbd)
            if pbd_rec['host'] == host:
                return sr
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


def with_vdi_attached_here(session, vdi, read_only, f):
    this_vm_ref = get_this_vm_ref(session)
    vbd_rec = {}
    vbd_rec['VM'] = this_vm_ref
    vbd_rec['VDI'] = vdi
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
    LOG.debug(_('Creating VBD for VDI %s ... '), vdi)
    vbd = session.get_xenapi().VBD.create(vbd_rec)
    LOG.debug(_('Creating VBD for VDI %s done.'), vdi)
    try:
        LOG.debug(_('Plugging VBD %s ... '), vbd)
        session.get_xenapi().VBD.plug(vbd)
        LOG.debug(_('Plugging VBD %s done.'), vbd)
        orig_dev = session.get_xenapi().VBD.get_device(vbd)
        LOG.debug(_('VBD %(vbd)s plugged as %(orig_dev)s') % locals())
        dev = remap_vbd_dev(orig_dev)
        if dev != orig_dev:
            LOG.debug(_('VBD %(vbd)s plugged into wrong dev, '
                        'remapping to %(dev)s') % locals())
        return f(dev)
    finally:
        LOG.debug(_('Destroying VBD for VDI %s ... '), vdi)
        vbd_unplug_with_retry(session, vbd)
        ignore_failure(session.get_xenapi().VBD.destroy, vbd)
        LOG.debug(_('Destroying VBD for VDI %s done.'), vdi)


def vbd_unplug_with_retry(session, vbd):
    """Call VBD.unplug on the given VBD, with a retry if we get
    DEVICE_DETACH_REJECTED.  For reasons which I don't understand, we're
    seeing the device still in use, even when all processes using the device
    should be dead."""
    # FIXME(sirp): We can use LoopingCall here w/o blocking sleep()
    while True:
        try:
            session.get_xenapi().VBD.unplug(vbd)
            LOG.debug(_('VBD.unplug successful first time.'))
            return
        except VMHelper.XenAPI.Failure, e:
            if (len(e.details) > 0 and
                e.details[0] == 'DEVICE_DETACH_REJECTED'):
                LOG.debug(_('VBD.unplug rejected: retrying...'))
                time.sleep(1)
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


def _stream_disk(dev, type, virtual_size, image_file):
    offset = 0
    if type == ImageType.DISK:
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

    def execute(cmd, process_input=None, check_exit_code=True):
        return utils.execute(cmd=cmd,
                             process_input=process_input,
                             check_exit_code=check_exit_code)

    execute('parted --script %s mklabel msdos' % dest)
    execute('parted --script %s mkpart primary %ds %ds' %
            (dest, primary_first, primary_last))

    LOG.debug(_('Writing partition table %s done.'), dest)
