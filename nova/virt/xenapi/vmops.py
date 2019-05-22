# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack Foundation
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
Management class for VM-related functions (spawn, reboot, etc).
"""

import base64
import functools
import time
import zlib

import eventlet
from eventlet import greenthread
import netaddr
from os_xenapi.client import host_xenstore
from os_xenapi.client import vm_management
from os_xenapi.client import XenAPI
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
from oslo_utils import versionutils
import six

from nova import block_device
from nova.compute import api as compute
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova.console import type as ctype
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import fields as obj_fields
from nova.pci import manager as pci_manager
from nova import utils
from nova.virt import configdrive
from nova.virt import driver as virt_driver
from nova.virt import firewall
from nova.virt.xenapi import agent as xapi_agent
from nova.virt.xenapi.image import utils as image_utils
from nova.virt.xenapi import vif as xapi_vif
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import volumeops


LOG = logging.getLogger(__name__)


CONF = nova.conf.CONF

DEFAULT_FIREWALL_DRIVER = "%s.%s" % (
    firewall.__name__,
    firewall.IptablesFirewallDriver.__name__)

RESIZE_TOTAL_STEPS = 5

DEVICE_ROOT = '0'
DEVICE_RESCUE = '1'
DEVICE_SWAP = '2'
DEVICE_CONFIGDRIVE = '3'
# Note(johngarbutt) HVM guests only support four devices
# until the PV tools activate, when others before available
# As such, ephemeral disk only available once PV tools load
# Note(johngarbutt) When very large ephemeral storage is required,
# multiple disks may be added. In this case the device id below
# is the used for the first disk. The second disk will be given
# next device id, i.e. 5, and so on, until enough space is added.
DEVICE_EPHEMERAL = '4'
# Note(johngarbutt) Currently don't support ISO boot during rescue
# and we must have the ISO visible before the PV drivers start
DEVICE_CD = '1'


def make_step_decorator(context, instance, update_instance_progress,
                        total_offset=0):
    """Factory to create a decorator that records instance progress as a series
    of discrete steps.

    Each time the decorator is invoked we bump the total-step-count, so after::

        @step
        def step1():
            ...

        @step
        def step2():
            ...

    we have a total-step-count of 2.

    Each time the step-function (not the step-decorator!) is invoked, we bump
    the current-step-count by 1, so after::

        step1()

    the current-step-count would be 1 giving a progress of ``1 / 2 *
    100`` or 50%.
    """
    step_info = dict(total=total_offset, current=0)

    def bump_progress():
        step_info['current'] += 1
        update_instance_progress(context, instance,
                                 step_info['current'], step_info['total'])

    def step_decorator(f):
        step_info['total'] += 1

        @functools.wraps(f)
        def inner(*args, **kwargs):
            rv = f(*args, **kwargs)
            bump_progress()
            return rv

        return inner

    return step_decorator


class VMOps(object):
    """Management class for VM-related tasks."""
    def __init__(self, session, virtapi):
        self.compute_api = compute.API()
        self._session = session
        self._virtapi = virtapi
        self._volumeops = volumeops.VolumeOps(self._session)
        self.firewall_driver = firewall.load_driver(
            DEFAULT_FIREWALL_DRIVER,
            xenapi_session=self._session)
        self.vif_driver = xapi_vif.XenAPIOpenVswitchDriver(
            xenapi_session=self._session)
        self.default_root_dev = '/dev/sda'

        image_handler_cfg = CONF.xenserver.image_handler
        self.image_handler = image_utils.get_image_handler(image_handler_cfg)
        # TODO(jianghuaw): Remove these lines relative to the deprecated
        # option of "image_upload_handler" in the next release - Stein.
        self.image_upload_handler = None
        image_upload_handler_cfg = CONF.xenserver.image_upload_handler
        if image_upload_handler_cfg:
            # If *image_upload_handler* is explicitly configured, it
            # means it indends to use non-default image upload handler.
            # In order to avoid mis-using the default image_handler which
            # may have different behavor than the explicitly configured
            # handler, we keep using *image_upload_handler*.
            LOG.warning("Deprecated: importing image upload handler: %s",
                        image_upload_handler_cfg)
            self.image_upload_handler = importutils.import_object(
                image_upload_handler_cfg)

    def agent_enabled(self, instance):
        if CONF.xenserver.disable_agent:
            return False

        return xapi_agent.should_use_agent(instance)

    def _get_agent(self, instance, vm_ref):
        if self.agent_enabled(instance):
            return xapi_agent.XenAPIBasedAgent(self._session, self._virtapi,
                                               instance, vm_ref)
        raise exception.NovaException(_("Error: Agent is disabled"))

    def instance_exists(self, name_label):
        return vm_utils.lookup(self._session, name_label) is not None

    def list_instances(self):
        """List VM instances."""
        # TODO(justinsb): Should we just always use the details method?
        #  Seems to be the same number of API calls..
        name_labels = []
        for vm_ref, vm_rec in vm_utils.list_vms(self._session):
            name_labels.append(vm_rec["name_label"])

        return name_labels

    def list_instance_uuids(self):
        """Get the list of nova instance uuids for VMs found on the
        hypervisor.
        """
        nova_uuids = []
        for vm_ref, vm_rec in vm_utils.list_vms(self._session):
            other_config = vm_rec['other_config']
            nova_uuid = other_config.get('nova_uuid')
            if nova_uuid:
                nova_uuids.append(nova_uuid)
        return nova_uuids

    def confirm_migration(self, migration, instance, network_info):
        self._destroy_orig_vm(instance, network_info)

    def _destroy_orig_vm(self, instance, network_info):
        name_label = self._get_orig_vm_name_label(instance)
        vm_ref = vm_utils.lookup(self._session, name_label)
        return self._destroy(instance, vm_ref, network_info=network_info)

    def _attach_mapped_block_devices(self, instance, block_device_info):
        # We are attaching these volumes before start (no hotplugging)
        # because some guests (windows) don't load PV drivers quickly
        block_device_mapping = virt_driver.block_device_info_get_mapping(
                block_device_info)
        for vol in block_device_mapping:
            if vol['mount_device'] == instance['root_device_name']:
                # NOTE(alaski): The root device should be attached already
                continue
            connection_info = vol['connection_info']
            mount_device = vol['mount_device'].rpartition("/")[2]
            self._volumeops.attach_volume(connection_info,
                                          instance['name'],
                                          mount_device,
                                          hotplug=False)

    def finish_revert_migration(self, context, instance,
                                block_device_info=None,
                                power_on=True):
        self._restore_orig_vm_and_cleanup_orphan(instance, block_device_info,
                                                 power_on)

    def _restore_orig_vm_and_cleanup_orphan(self, instance,
                                            block_device_info=None,
                                            power_on=True):
        # NOTE(sirp): the original vm was suffixed with '-orig'; find it using
        # the old suffix, remove the suffix, then power it back on.
        name_label = self._get_orig_vm_name_label(instance)
        vm_ref = vm_utils.lookup(self._session, name_label)

        # NOTE(danms): if we're reverting migration in the failure case,
        # make sure we don't have a conflicting vm still running here,
        # as might be the case in a failed migrate-to-same-host situation
        new_ref = vm_utils.lookup(self._session, instance['name'])
        if vm_ref is not None:
            if new_ref is not None:
                self._destroy(instance, new_ref)
            # Remove the '-orig' suffix (which was added in case the
            # resized VM ends up on the source host, common during
            # testing)
            name_label = instance['name']
            vm_utils.set_vm_name_label(self._session, vm_ref, name_label)
            self._attach_mapped_block_devices(instance, block_device_info)
        elif new_ref is not None:
            # We crashed before the -orig backup was made
            vm_ref = new_ref

        if power_on and vm_utils.is_vm_shutdown(self._session, vm_ref):
            self._start(instance, vm_ref)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):

        def null_step_decorator(f):
            return f

        def create_disks_step(undo_mgr, disk_image_type, image_meta,
                              name_label):
            import_root = True
            root_vol_vdi = None
            if block_device_info:
                LOG.debug("Block device information present: %s",
                          block_device_info, instance=instance)
                # NOTE(alaski): Follows the basic procedure of
                # vm_utils.get_vdis_for_instance() used by spawn()
                for bdm in block_device_info['block_device_mapping']:
                    if bdm['mount_device'] == instance['root_device_name']:
                        connection_info = bdm['connection_info']
                        _sr, root_vol_vdi = self._volumeops.connect_volume(
                                connection_info)
                        import_root = False
                        break

            # TODO(johngarbutt) clean up if this is not run
            vdis = vm_utils.import_all_migrated_disks(self._session, instance,
                                                      import_root=import_root)

            if root_vol_vdi:
                vol_vdi_ref = self._session.call_xenapi('VDI.get_by_uuid',
                        root_vol_vdi)
                vdis['root'] = dict(uuid=root_vol_vdi, file=None,
                        ref=vol_vdi_ref, osvol=True)

            def undo_create_disks():
                eph_vdis = vdis['ephemerals']
                root_vdi = vdis['root']
                vdi_refs = [vdi['ref'] for vdi in eph_vdis.values()]
                if not root_vdi.get('osvol', False):
                    vdi_refs.append(root_vdi['ref'])
                else:
                    self._volumeops.safe_cleanup_from_vdis(root_vdi['ref'])
                vm_utils.safe_destroy_vdis(self._session, vdi_refs)

            undo_mgr.undo_with(undo_create_disks)
            return vdis

        def completed_callback():
            self._update_instance_progress(context, instance,
                                           step=5,
                                           total_steps=RESIZE_TOTAL_STEPS)

        self._spawn(context, instance, image_meta, null_step_decorator,
                    create_disks_step, first_boot=False, injected_files=None,
                    admin_password=None, network_info=network_info,
                    block_device_info=block_device_info, name_label=None,
                    rescue=False, power_on=power_on, resize=resize_instance,
                    completed_callback=completed_callback)

    def _start(self, instance, vm_ref=None, bad_volumes_callback=None,
               start_pause=False):
        """Power on a VM instance."""
        vm_ref = vm_ref or self._get_vm_opaque_ref(instance)
        LOG.debug("Starting instance", instance=instance)

        # Attached volumes that have become non-responsive will prevent a VM
        # from starting, so scan for these before attempting to start
        #
        # In order to make sure this detach is consistent (virt, BDM, cinder),
        # we only detach in the virt-layer if a callback is provided.
        if bad_volumes_callback:
            bad_devices = self._volumeops.find_bad_volumes(vm_ref)
            for device_name in bad_devices:
                self._volumeops.detach_volume(
                        None, instance['name'], device_name)

        self._session.call_xenapi('VM.start_on', vm_ref,
                                  self._session.host_ref,
                                  start_pause, False)

        # Allow higher-layers a chance to detach bad-volumes as well (in order
        # to cleanup BDM entries and detach in Cinder)
        if bad_volumes_callback and bad_devices:
            bad_volumes_callback(bad_devices)

        # Do some operations which have to be done after start:
        #   e.g. The vif's interim bridge won't be created until VM starts.
        #        So the operations on the interim bridge have be done after
        #        start.
        self._post_start_actions(instance)

    def _post_start_actions(self, instance):
        vm_ref = vm_utils.lookup(self._session, instance['name'])
        vif_refs = self._session.call_xenapi("VM.get_VIFs", vm_ref)
        for vif_ref in vif_refs:
            self.vif_driver.post_start_actions(instance, vif_ref)

    def _get_vdis_for_instance(self, context, instance, name_label,
                               image_meta, image_type, block_device_info):
        """Create or connect to all virtual disks for this instance."""

        vdis = self._connect_cinder_volumes(instance, block_device_info)

        # If we didn't get a root VDI from volumes,
        # then use the Glance image as the root device
        if 'root' not in vdis:
            create_image_vdis = vm_utils.create_image(
                context, self._session, instance, name_label, image_meta.id,
                image_type, self.image_handler)
            vdis.update(create_image_vdis)

        # Fetch VDI refs now so we don't have to fetch the ref multiple times
        for vdi in six.itervalues(vdis):
            vdi['ref'] = self._session.call_xenapi('VDI.get_by_uuid',
                                                   vdi['uuid'])
        return vdis

    def _connect_cinder_volumes(self, instance, block_device_info):
        """Attach all the cinder volumes described in block_device_info."""
        vdis = {}

        if block_device_info:
            msg = "block device info: %s" % block_device_info
            # NOTE(mriedem): block_device_info can contain an auth_password
            # so we have to scrub the message before logging it.
            LOG.debug(strutils.mask_password(msg), instance=instance)
            root_device_name = block_device_info['root_device_name']

            for bdm in block_device_info['block_device_mapping']:
                if (block_device.strip_prefix(bdm['mount_device']) ==
                        block_device.strip_prefix(root_device_name)):
                    # If we're a root-device, record that fact so we don't
                    # download a root image via Glance
                    type_ = 'root'
                else:
                    # Otherwise, use mount_device as `type_` so that we have
                    # easy access to it in _attach_disks to create the VBD
                    type_ = bdm['mount_device']

                conn_info = bdm['connection_info']
                _sr, vdi_uuid = self._volumeops.connect_volume(conn_info)
                if vdi_uuid:
                    vdis[type_] = dict(uuid=vdi_uuid, file=None, osvol=True)

        return vdis

    def _update_last_dom_id(self, vm_ref):
        other_config = self._session.VM.get_other_config(vm_ref)
        other_config['last_dom_id'] = self._session.VM.get_domid(vm_ref)
        self._session.VM.set_other_config(vm_ref, other_config)

    def _attach_vgpu(self, vm_ref, vgpu_info, instance):
        if not vgpu_info:
            return
        grp_ref = self._session.call_xenapi("GPU_group.get_by_uuid",
                                            vgpu_info['gpu_grp_uuid'])
        type_ref = self._session.call_xenapi("VGPU_type.get_by_uuid",
                                            vgpu_info['vgpu_type_uuid'])
        # NOTE(jianghuaw): set other-config with "nova-instance-uuid" to
        # declare which nova instance owns this vGPU. That should be useful
        # for tracking purposes. '0' is the device id for VGPU. As we only
        # support one VGPU at the moment, so only '0' is the valid value.
        # Refer to https://xapi-project.github.io/xen-api/classes/vgpu.html
        # for this Xen API of 'VGPU.create'.
        self._session.call_xenapi('VGPU.create', vm_ref, grp_ref, '0',
                                  {'nova-instance-uuid': instance['uuid']},
                                  type_ref)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              vgpu_info=None, name_label=None, rescue=False):

        if block_device_info:
            LOG.debug("Block device information present: %s",
                      block_device_info, instance=instance)
        if block_device_info and not block_device_info['root_device_name']:
            block_device_info['root_device_name'] = self.default_root_dev

        step = make_step_decorator(context, instance,
                                   self._update_instance_progress)

        @step
        def create_disks_step(undo_mgr, disk_image_type, image_meta,
                              name_label):
            vdis = self._get_vdis_for_instance(context, instance, name_label,
                        image_meta, disk_image_type,
                        block_device_info)

            def undo_create_disks():
                vdi_refs = [vdi['ref'] for vdi in vdis.values()
                        if not vdi.get('osvol')]
                vm_utils.safe_destroy_vdis(self._session, vdi_refs)
                vol_vdi_refs = [vdi['ref'] for vdi in vdis.values()
                        if vdi.get('osvol')]
                self._volumeops.safe_cleanup_from_vdis(vol_vdi_refs)

            undo_mgr.undo_with(undo_create_disks)
            return vdis

        self._spawn(context, instance, image_meta, step, create_disks_step,
                    True, injected_files, admin_password, network_info,
                    block_device_info, vgpu_info, name_label, rescue)

    def _spawn(self, context, instance, image_meta, step, create_disks_step,
               first_boot, injected_files=None, admin_password=None,
               network_info=None, block_device_info=None, vgpu_info=None,
               name_label=None, rescue=False, power_on=True, resize=True,
               completed_callback=None):
        if name_label is None:
            name_label = instance['name']

        self._ensure_instance_name_unique(name_label)
        self._ensure_enough_free_mem(instance)

        def attach_disks(undo_mgr, vm_ref, vdis, disk_image_type):
            if image_meta.properties.get('hw_ipxe_boot', False):
                if 'iso' in vdis:
                    vm_utils.handle_ipxe_iso(
                        self._session, instance, vdis['iso'], network_info)
                else:
                    LOG.warning('ipxe_boot is True but no ISO image found',
                                instance=instance)

            if resize:
                self._resize_up_vdis(instance, vdis)

            instance.device_metadata = self._save_device_metadata(
                context, instance, block_device_info)
            self._attach_disks(context, instance, image_meta, vm_ref,
                               name_label, vdis, disk_image_type,
                               network_info, rescue,
                               admin_password, injected_files)
            if not first_boot:
                self._attach_mapped_block_devices(instance,
                                                  block_device_info)

        def attach_pci_devices(undo_mgr, vm_ref):
            dev_to_passthrough = ""
            devices = pci_manager.get_instance_pci_devs(instance)
            for d in devices:
                pci_address = d["address"]
                if pci_address.count(":") == 1:
                    pci_address = "0000:" + pci_address
                dev_to_passthrough += ",0/" + pci_address

            # Remove the first comma if string is not empty.
            # Note(guillaume-thouvenin): If dev_to_passthrough is empty, we
            #                            don't need to update other_config.
            if dev_to_passthrough:
                vm_utils.set_other_config_pci(self._session,
                                              vm_ref,
                                              dev_to_passthrough[1:])

        @step
        def determine_disk_image_type_step(undo_mgr):
            return vm_utils.determine_disk_image_type(image_meta)

        @step
        def create_kernel_ramdisk_step(undo_mgr):
            kernel_file, ramdisk_file = vm_utils.create_kernel_and_ramdisk(
                    context, self._session, instance, name_label)

            def undo_create_kernel_ramdisk():
                vm_utils.destroy_kernel_ramdisk(self._session, instance,
                        kernel_file, ramdisk_file)

            undo_mgr.undo_with(undo_create_kernel_ramdisk)
            return kernel_file, ramdisk_file

        @step
        def create_vm_record_step(undo_mgr, disk_image_type,
                                  kernel_file, ramdisk_file):
            vm_ref = self._create_vm_record(context, instance, name_label,
                                            disk_image_type, kernel_file,
                                            ramdisk_file, image_meta, rescue)

            def undo_create_vm():
                self._destroy(instance, vm_ref, network_info=network_info)

            undo_mgr.undo_with(undo_create_vm)
            return vm_ref

        @step
        def attach_devices_step(undo_mgr, vm_ref, vdis, disk_image_type,
                                vgpu_info):
            attach_disks(undo_mgr, vm_ref, vdis, disk_image_type)
            attach_pci_devices(undo_mgr, vm_ref)
            # NOTE(jianghuaw): in XAPI, the VGPU record is associated with a
            # VM since creation. The record will be destroyed automatically
            # once VM is destroyed. So there is no need to add any additional
            # undo functions for VGPU.
            self._attach_vgpu(vm_ref, vgpu_info, instance)

        if rescue:
            # NOTE(johannes): Attach disks from original VM to rescue VM now,
            # before booting the VM, since we can't hotplug block devices
            # on non-PV guests
            @step
            def attach_orig_disks_step(undo_mgr, vm_ref):
                vbd_refs = self._attach_orig_disks(instance, vm_ref)

                def undo_attach_orig_disks():
                    # Destroy the VBDs in preparation to re-attach the VDIs
                    # to its original VM.  (does not delete VDI)
                    for vbd_ref in vbd_refs:
                        vm_utils.destroy_vbd(self._session, vbd_ref)

                undo_mgr.undo_with(undo_attach_orig_disks)

        @step
        def inject_instance_data_step(undo_mgr, vm_ref, vdis):
            self._inject_instance_metadata(instance, vm_ref)
            self._inject_auto_disk_config(instance, vm_ref)
            # NOTE: We add the hostname here so windows PV tools
            # can pick it up during booting
            if first_boot:
                self._inject_hostname(instance, vm_ref, rescue)
            self._file_inject_vm_settings(instance, vm_ref, vdis, network_info)
            self.inject_network_info(instance, network_info, vm_ref)

        @step
        def setup_network_step(undo_mgr, vm_ref):
            self._create_vifs(instance, vm_ref, network_info)
            self._prepare_instance_filter(instance, network_info)

        @step
        def start_paused_step(undo_mgr, vm_ref):
            if power_on:
                self._start(instance, vm_ref, start_pause=True)

        @step
        def boot_and_configure_instance_step(undo_mgr, vm_ref):
            self._unpause_and_wait(vm_ref, instance, power_on)
            if first_boot:
                self._configure_new_instance_with_agent(instance, vm_ref,
                        injected_files, admin_password)
                self._remove_hostname(instance, vm_ref)

        @step
        def apply_security_group_filters_step(undo_mgr):
            self.firewall_driver.apply_instance_filter(instance, network_info)

        undo_mgr = utils.UndoManager()
        try:
            # NOTE(sirp): The create_disks() step will potentially take a
            # *very* long time to complete since it has to fetch the image
            # over the network and images can be several gigs in size. To
            # avoid progress remaining at 0% for too long, make sure the
            # first step is something that completes rather quickly.
            disk_image_type = determine_disk_image_type_step(undo_mgr)

            vdis = create_disks_step(undo_mgr, disk_image_type, image_meta,
                                     name_label)
            kernel_file, ramdisk_file = create_kernel_ramdisk_step(undo_mgr)

            vm_ref = create_vm_record_step(undo_mgr, disk_image_type,
                    kernel_file, ramdisk_file)
            attach_devices_step(undo_mgr, vm_ref, vdis, disk_image_type,
                                vgpu_info)

            inject_instance_data_step(undo_mgr, vm_ref, vdis)

            # if use neutron, prepare waiting event from neutron
            # first_boot is True in new booted instance
            # first_boot is False in migration and we don't waiting
            # for neutron event regardless of whether or not it is
            # migrated to another host, if unplug VIFs locally, the
            # port status may not changed in neutron side and we
            # cannot get the vif plug event from neutron
            # rescue is True in rescued instance and the port in neutron side
            # won't change, so we don't wait event from neutron
            timeout = CONF.vif_plugging_timeout
            events = self._get_neutron_events(network_info, power_on,
                                              first_boot, rescue)
            try:
                with self._virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                    LOG.debug("wait for instance event:%s", events,
                              instance=instance)
                    setup_network_step(undo_mgr, vm_ref)
                    if rescue:
                        attach_orig_disks_step(undo_mgr, vm_ref)
                    start_paused_step(undo_mgr, vm_ref)
            except eventlet.timeout.Timeout:
                self._handle_neutron_event_timeout(instance, undo_mgr)

            apply_security_group_filters_step(undo_mgr)
            boot_and_configure_instance_step(undo_mgr, vm_ref)
            if completed_callback:
                completed_callback()
        except Exception:
            msg = _("Failed to spawn, rolling back")
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def _handle_neutron_event_timeout(self, instance, undo_mgr):
        # We didn't get callback from Neutron within given time
        LOG.warning('Timeout waiting for vif plugging callback',
                    instance=instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _unpause_and_wait(self, vm_ref, instance, power_on):
        if power_on:
            LOG.debug("Update instance when power on", instance=instance)
            self._session.VM.unpause(vm_ref)
            self._wait_for_instance_to_start(instance, vm_ref)
            self._update_last_dom_id(vm_ref)

    def _neutron_failed_callback(self, event_name, instance):
        LOG.warning('Neutron Reported failure on event %(event)s',
                    {'event': event_name}, instance=instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _get_neutron_events(self, network_info, power_on, first_boot, rescue):
        # Only get network-vif-plugged events with VIF's status is not active.
        # With VIF whose status is active, neutron may not notify such event.
        # Don't get network-vif-plugged events from rescued VM or migrated VM
        timeout = CONF.vif_plugging_timeout
        if (utils.is_neutron() and power_on and timeout and first_boot and
                not rescue):
            return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]
        else:
            return []

    def _attach_orig_disks(self, instance, vm_ref):
        orig_vm_ref = vm_utils.lookup(self._session, instance['name'])
        orig_vdi_refs = self._find_vdi_refs(orig_vm_ref,
                                            exclude_volumes=True)

        # Attach original root disk
        root_vdi_ref = orig_vdi_refs.get(DEVICE_ROOT)
        if not root_vdi_ref:
            raise exception.NotFound(_("Unable to find root VBD/VDI for VM"))

        vbd_ref = vm_utils.create_vbd(self._session, vm_ref, root_vdi_ref,
                                      DEVICE_RESCUE, bootable=False)
        vbd_refs = [vbd_ref]

        # Attach original swap disk
        swap_vdi_ref = orig_vdi_refs.get(DEVICE_SWAP)
        if swap_vdi_ref:
            vbd_ref = vm_utils.create_vbd(self._session, vm_ref, swap_vdi_ref,
                                          DEVICE_SWAP, bootable=False)
            vbd_refs.append(vbd_ref)

        # Attach original ephemeral disks
        for userdevice, vdi_ref in orig_vdi_refs.items():
            if userdevice >= DEVICE_EPHEMERAL:
                vbd_ref = vm_utils.create_vbd(self._session, vm_ref, vdi_ref,
                                              userdevice, bootable=False)
                vbd_refs.append(vbd_ref)

        return vbd_refs

    def _file_inject_vm_settings(self, instance, vm_ref, vdis, network_info):
        if CONF.flat_injected:
            vm_utils.preconfigure_instance(self._session, instance,
                                           vdis['root']['ref'], network_info)

    def _ensure_instance_name_unique(self, name_label):
        vm_ref = vm_utils.lookup(self._session, name_label)
        if vm_ref is not None:
            raise exception.InstanceExists(name=name_label)

    def _ensure_enough_free_mem(self, instance):
        if not vm_utils.is_enough_free_mem(self._session, instance):
            raise exception.InsufficientFreeMemory(uuid=instance['uuid'])

    def _create_vm_record(self, context, instance, name_label, disk_image_type,
                          kernel_file, ramdisk_file, image_meta, rescue=False):
        """Create the VM record in Xen, making sure that we do not create
        a duplicate name-label.  Also do a rough sanity check on memory
        to try to short-circuit a potential failure later.  (The memory
        check only accounts for running VMs, so it can miss other builds
        that are in progress.)
        """
        mode = vm_utils.determine_vm_mode(instance, disk_image_type)
        # NOTE(tpownall): If rescue mode then we should try to pull the vm_mode
        # value from the image properties to ensure the vm is built properly.
        if rescue:
            rescue_vm_mode = image_meta.properties.get('hw_vm_mode', None)
            if rescue_vm_mode is None:
                LOG.debug("vm_mode not found in rescue image properties."
                          "Setting vm_mode to %s", mode, instance=instance)
            else:
                mode = obj_fields.VMMode.canonicalize(rescue_vm_mode)

        if instance.vm_mode != mode:
            # Update database with normalized (or determined) value
            instance.vm_mode = mode
            instance.save()

        device_id = vm_utils.get_vm_device_id(self._session, image_meta)
        use_pv_kernel = (mode == obj_fields.VMMode.XEN)
        LOG.debug("Using PV kernel: %s", use_pv_kernel, instance=instance)
        vm_ref = vm_utils.create_vm(self._session, instance, name_label,
                                    kernel_file, ramdisk_file,
                                    use_pv_kernel, device_id)
        return vm_ref

    def _attach_disks(self, context, instance, image_meta, vm_ref, name_label,
                      vdis, disk_image_type, network_info, rescue=False,
                      admin_password=None, files=None):
        flavor = instance.get_flavor()

        # Attach (required) root disk
        if disk_image_type == vm_utils.ImageType.DISK_ISO:
            # DISK_ISO needs two VBDs: the ISO disk and a blank RW disk
            root_disk_size = flavor.root_gb
            if root_disk_size > 0:
                vm_utils.generate_iso_blank_root_disk(self._session, instance,
                    vm_ref, DEVICE_ROOT, name_label, root_disk_size)

            cd_vdi = vdis.pop('iso')
            vm_utils.attach_cd(self._session, vm_ref, cd_vdi['ref'],
                               DEVICE_CD)
        else:
            root_vdi = vdis['root']

            auto_disk_config = instance['auto_disk_config']
            # NOTE(tpownall): If rescue mode we need to ensure that we're
            # pulling the auto_disk_config value from the image properties so
            # that we can pull it from the rescue_image_ref.
            if rescue:
                if not image_meta.properties.obj_attr_is_set(
                        "hw_auto_disk_config"):
                    LOG.debug("'hw_auto_disk_config' value not found in "
                              "rescue image_properties. Setting value to %s",
                              auto_disk_config, instance=instance)
                else:
                    auto_disk_config = strutils.bool_from_string(
                        image_meta.properties.hw_auto_disk_config)

            if auto_disk_config:
                LOG.debug("Auto configuring disk, attempting to "
                          "resize root disk...", instance=instance)
                vm_utils.try_auto_configure_disk(self._session,
                                                 root_vdi['ref'],
                                                 flavor.root_gb)

            vm_utils.create_vbd(self._session, vm_ref, root_vdi['ref'],
                                DEVICE_ROOT, bootable=True,
                                osvol=root_vdi.get('osvol'))

        # Attach (optional) additional block-devices
        for type_, vdi_info in vdis.items():
            # Additional block-devices for boot use their device-name as the
            # type.
            if not type_.startswith('/dev'):
                continue

            # Convert device name to user device number, e.g. /dev/xvdb -> 1
            userdevice = ord(block_device.strip_prefix(type_)) - ord('a')
            vm_utils.create_vbd(self._session, vm_ref, vdi_info['ref'],
                                userdevice, bootable=False,
                                osvol=vdi_info.get('osvol'))

        # For rescue, swap and ephemeral disks get attached in
        # _attach_orig_disks

        # Attach (optional) swap disk
        swap_mb = flavor.swap
        if not rescue and swap_mb:
            vm_utils.generate_swap(self._session, instance, vm_ref,
                                   DEVICE_SWAP, name_label, swap_mb)

        ephemeral_gb = flavor.ephemeral_gb
        if not rescue and ephemeral_gb:
            ephemeral_vdis = vdis.get('ephemerals')
            if ephemeral_vdis:
                # attach existing (migrated) ephemeral disks
                for userdevice, ephemeral_vdi in ephemeral_vdis.items():
                    vm_utils.create_vbd(self._session, vm_ref,
                                        ephemeral_vdi['ref'],
                                        userdevice, bootable=False)
            else:
                # create specified ephemeral disks
                vm_utils.generate_ephemeral(self._session, instance, vm_ref,
                                            DEVICE_EPHEMERAL, name_label,
                                            ephemeral_gb)

        # Attach (optional) configdrive v2 disk
        if configdrive.required_by(instance):
            vm_utils.generate_configdrive(self._session, context,
                                          instance, vm_ref,
                                          DEVICE_CONFIGDRIVE,
                                          network_info,
                                          admin_password=admin_password,
                                          files=files)

    @staticmethod
    def _prepare_disk_metadata(bdm):
        """Returns the disk metadata with dual disk buses - ide and xen. More
           details about Xen device number can be found in
           http://xenbits.xen.org/docs/4.2-testing/misc/vbd-interface.txt
        """
        path = bdm.device_name
        disk_num = volume_utils.get_device_number(path)

        xen0 = objects.XenDeviceBus(address=("00%02d00" % disk_num))

        registry = ('HKLM\\SYSTEM\\ControlSet001\\Enum\\SCSI\\'
                    'Disk&Ven_XENSRC&Prod_PVDISK\\')
        vbd_prefix = '/sys/devices/vbd-'

        if disk_num < 4:
            ide = objects.IDEDeviceBus(
                address=("%d:%d" % (disk_num / 2, disk_num % 2)))

            xen1 = objects.XenDeviceBus(
                address=("%d" % (202 << 8 | disk_num << 4)))
            xen2 = objects.XenDeviceBus()
            if disk_num < 2:
                xen2.address = "%d" % (3 << 8 | disk_num << 6)
            else:
                xen2.address = "%d" % (22 << 8 | (disk_num - 2) << 6)

            return [objects.DiskMetadata(path=path, bus=ide, tags=[bdm.tag]),
                    objects.DiskMetadata(path=registry + xen0.address,
                                         bus=xen0, tags=[bdm.tag]),
                    objects.DiskMetadata(path=vbd_prefix + xen1.address,
                                         bus=xen1, tags=[bdm.tag]),
                    objects.DiskMetadata(path=vbd_prefix + xen2.address,
                                         bus=xen2, tags=[bdm.tag])]
        else:
            xen1 = objects.XenDeviceBus()

            if disk_num < 16:
                xen1.address = "%d" % (202 << 8 | disk_num << 4)
            else:
                xen1.address = "%d" % (1 << 28 | disk_num << 8)

            return [objects.DiskMetadata(path=registry + xen0.address,
                                         bus=xen0, tags=[bdm.tag]),
                    objects.DiskMetadata(path=vbd_prefix + xen1.address,
                                         bus=xen1, tags=[bdm.tag])]

    def _save_device_metadata(self, context, instance, block_device_info):
        """Builds a metadata object for instance devices, that maps the user
           provided tag to the hypervisor assigned device address.
        """
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
            context, instance["uuid"])

        metadata = []
        for vif in vifs:
            if 'tag' in vif and vif.tag:
                device = objects.NetworkInterfaceMetadata(
                    mac=vif.address,
                    bus=objects.PCIDeviceBus(),
                    tags=[vif.tag])
                metadata.append(device)

        block_device_mapping = virt_driver.block_device_info_get_mapping(
            block_device_info)
        if block_device_mapping:
            # TODO(mriedem): We should be able to get the BDMs out of the
            # block_device_info['block_device_mapping'] field, however, that
            # is a list of DriverVolumeBlockDevice objects and do not currently
            # proxy the 'tag' attribute.
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance["uuid"])
            for bdm in bdms:
                if 'tag' in bdm and bdm.tag:
                    metadata.extend(self._prepare_disk_metadata(bdm))

        if metadata:
            return objects.InstanceDeviceMetadata(devices=metadata)

    def _wait_for_instance_to_start(self, instance, vm_ref):
        LOG.debug('Waiting for instance state to become running',
                  instance=instance)
        expiration = time.time() + CONF.xenserver.running_timeout
        while time.time() < expiration:
            state = vm_utils.get_power_state(self._session, vm_ref)
            if state == power_state.RUNNING:
                break
            greenthread.sleep(0.5)

    def _configure_new_instance_with_agent(self, instance, vm_ref,
                                           injected_files, admin_password):
        if not self.agent_enabled(instance):
            LOG.debug("Skip agent setup, not enabled.", instance=instance)
            return

        agent = self._get_agent(instance, vm_ref)

        version = agent.get_version()
        if not version:
            LOG.debug("Skip agent setup, unable to contact agent.",
                      instance=instance)
            return

        LOG.debug('Detected agent version: %s', version, instance=instance)

        # NOTE(johngarbutt) the agent object allows all of
        # the following steps to silently fail
        agent.inject_ssh_key()

        if injected_files:
            agent.inject_files(injected_files)

        if admin_password:
            agent.set_admin_password(admin_password)

        agent.resetnetwork()
        agent.update_if_needed(version)

    def _prepare_instance_filter(self, instance, network_info):
        try:
            self.firewall_driver.setup_basic_filtering(
                    instance, network_info)
        except NotImplementedError:
            # NOTE(salvatore-orlando): setup_basic_filtering might be
            # empty or not implemented at all, as basic filter could
            # be implemented with VIF rules created by xapi plugin
            pass

        self.firewall_driver.prepare_instance_filter(instance,
                                                     network_info)

    def _get_vm_opaque_ref(self, instance, check_rescue=False):
        """Get xapi OpaqueRef from a db record.
        :param check_rescue: if True will return the 'name'-rescue vm if it
                             exists, instead of just 'name'
        """
        vm_ref = vm_utils.lookup(self._session, instance['name'], check_rescue)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance['name'])
        return vm_ref

    def _acquire_bootlock(self, vm):
        """Prevent an instance from booting."""
        self._session.call_xenapi(
            "VM.set_blocked_operations",
            vm,
            {"start": ""})

    def _release_bootlock(self, vm):
        """Allow an instance to boot."""
        self._session.call_xenapi(
            "VM.remove_from_blocked_operations",
            vm,
            "start")

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance.

        :param context: request context
        :param instance: instance to be snapshotted
        :param image_id: id of image to upload to

        Steps involved in a XenServer snapshot:

        1. XAPI-Snapshot: Snapshotting the instance using XenAPI. This
           creates: Snapshot (Template) VM, Snapshot VBD, Snapshot VDI,
           Snapshot VHD

        2. Wait-for-coalesce: The Snapshot VDI and Instance VDI both point to
           a 'base-copy' VDI.  The base_copy is immutable and may be chained
           with other base_copies.  If chained, the base_copies
           coalesce together, so, we must wait for this coalescing to occur to
           get a stable representation of the data on disk.

        3. Push-to-data-store: Once coalesced, we call
           'image_upload_handler' to upload the images.

        """
        vm_ref = self._get_vm_opaque_ref(instance)
        label = "%s-snapshot" % instance['name']

        start_time = timeutils.utcnow()
        with vm_utils.snapshot_attached_here(
                self._session, instance, vm_ref, label,
                post_snapshot_callback=update_task_state) as vdi_uuids:
            update_task_state(task_state=task_states.IMAGE_UPLOADING,
                              expected_state=task_states.IMAGE_PENDING_UPLOAD)
            if self.image_upload_handler:
                # TODO(jianghuaw): remove this branch once the
                # deprecated option of "image_upload_handler"
                # gets removed in the next release - Stein.
                self.image_upload_handler.upload_image(context,
                                                       self._session,
                                                       instance,
                                                       image_id,
                                                       vdi_uuids,
                                                       )
            else:
                self.image_handler.upload_image(context,
                                                self._session,
                                                instance,
                                                image_id,
                                                vdi_uuids,
                                                )

        duration = timeutils.delta_seconds(start_time, timeutils.utcnow())
        LOG.debug("Finished snapshot and upload for VM, duration: "
                  "%(duration).2f secs for image %(image_id)s",
                  {'image_id': image_id, 'duration': duration},
                  instance=instance)

    def post_interrupted_snapshot_cleanup(self, context, instance):
        """Cleans up any resources left after a failed snapshot."""
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_utils.remove_old_snapshots(self._session, instance, vm_ref)

    def _get_orig_vm_name_label(self, instance):
        return instance['name'] + '-orig'

    def _update_instance_progress(self, context, instance, step, total_steps):
        """Update instance progress percent to reflect current step number
        """
        # FIXME(sirp): for now we're taking a KISS approach to instance
        # progress:
        # Divide the action's workflow into discrete steps and "bump" the
        # instance's progress field as each step is completed.
        #
        # For a first cut this should be fine, however, for large VM images,
        # the get_vdis_for_instance step begins to dominate the equation. A
        # better approximation would use the percentage of the VM image that
        # has been streamed to the destination host.
        progress = round(float(step) / total_steps * 100)
        LOG.debug("Updating progress to %d", progress,
                  instance=instance)
        instance.progress = progress
        instance.save()

    def _resize_ensure_vm_is_shutdown(self, instance, vm_ref):
        if vm_utils.is_vm_shutdown(self._session, vm_ref):
            LOG.debug("VM was already shutdown.", instance=instance)
            return

        if not vm_utils.clean_shutdown_vm(self._session, instance, vm_ref):
            LOG.debug("Clean shutdown did not complete successfully, "
                      "trying hard shutdown.", instance=instance)
            if not vm_utils.hard_shutdown_vm(self._session, instance, vm_ref):
                raise exception.ResizeError(
                    reason=_("Unable to terminate instance."))

    def _migrate_disk_resizing_down(self, context, instance, dest,
                                    flavor, vm_ref, sr_path):
        step = make_step_decorator(context, instance,
                                   self._update_instance_progress,
                                   total_offset=1)

        @step
        def fake_step_to_match_resizing_up():
            pass

        @step
        def rename_and_power_off_vm(undo_mgr):
            self._resize_ensure_vm_is_shutdown(instance, vm_ref)
            self._apply_orig_vm_name_label(instance, vm_ref)

            def restore_orig_vm():
                # Do not need to restore block devices, not yet been removed
                self._restore_orig_vm_and_cleanup_orphan(instance)

            undo_mgr.undo_with(restore_orig_vm)

        @step
        def create_copy_vdi_and_resize(undo_mgr, old_vdi_ref):
            new_vdi_ref, new_vdi_uuid = vm_utils.resize_disk(self._session,
                instance, old_vdi_ref, flavor)

            def cleanup_vdi_copy():
                vm_utils.destroy_vdi(self._session, new_vdi_ref)

            undo_mgr.undo_with(cleanup_vdi_copy)

            return new_vdi_ref, new_vdi_uuid

        @step
        def transfer_vhd_to_dest(new_vdi_ref, new_vdi_uuid):
            vm_utils.migrate_vhd(self._session, instance, new_vdi_uuid,
                                 dest, sr_path, 0)
            # Clean up VDI now that it's been copied
            vm_utils.destroy_vdi(self._session, new_vdi_ref)

        undo_mgr = utils.UndoManager()
        try:
            fake_step_to_match_resizing_up()
            rename_and_power_off_vm(undo_mgr)
            old_vdi_ref, _ignore = vm_utils.get_vdi_for_vm_safely(
                self._session, vm_ref)
            new_vdi_ref, new_vdi_uuid = create_copy_vdi_and_resize(
                undo_mgr, old_vdi_ref)
            transfer_vhd_to_dest(new_vdi_ref, new_vdi_uuid)
        except Exception as error:
            LOG.exception(_("_migrate_disk_resizing_down failed. Restoring "
                            "orig vm"), instance=instance)
            undo_mgr._rollback()
            raise exception.InstanceFaultRollback(error)

    def _migrate_disk_resizing_up(self, context, instance, dest, vm_ref,
                                  sr_path):
        step = make_step_decorator(context,
                                   instance,
                                   self._update_instance_progress,
                                   total_offset=1)
        """
        NOTE(johngarbutt) Understanding how resize up works.

        For resize up, we attempt to minimize the amount of downtime
        for users by copying snapshots of their disks, while their
        VM is still running.

        It is worth noting, that migrating the snapshot, means migrating
        the whole VHD chain up to, but not including, the leaf VHD the VM
        is still writing to.

        Once the snapshots have been migrated, we power down the VM
        and migrate all the disk changes since the snapshots were taken.

        In addition, the snapshots are taken at the latest possible point,
        to help minimize the time it takes to migrate the disk changes
        after the VM has been turned off.

        Before starting to migrate any of the disks, we rename the VM,
        to <current_vm_name>-orig, in case we attempt to migrate the VM
        back onto this host, and so once we have completed the migration
        of the disk, confirm/rollback migrate can work in the usual way.

        If there is a failure at any point, we need to rollback to the
        position we were in before starting to migrate. In particular,
        we need to delete and snapshot VDIs that may have been created,
        and restore the VM back to its original name.
        """

        @step
        def fake_step_to_show_snapshot_complete():
            pass

        @step
        def transfer_immutable_vhds(root_vdi_uuids):
            immutable_root_vdi_uuids = root_vdi_uuids[1:]
            for vhd_num, vdi_uuid in enumerate(immutable_root_vdi_uuids,
                                               start=1):
                vm_utils.migrate_vhd(self._session, instance, vdi_uuid, dest,
                                     sr_path, vhd_num)
            LOG.debug("Migrated root base vhds", instance=instance)

        def _process_ephemeral_chain_recursive(ephemeral_chains,
                                               active_vdi_uuids,
                                               ephemeral_disk_index=0):
            # This method is called several times, recursively.
            # The first phase snapshots the ephemeral disks, and
            # migrates the read only VHD files.
            # The final call into this method calls
            # power_down_and_transfer_leaf_vhds
            # to turn off the VM and copy the rest of the VHDs.
            number_of_chains = len(ephemeral_chains)
            if number_of_chains == 0:
                # If we get here, we have snapshotted and migrated
                # all the ephemeral disks, so its time to power down
                # and complete the migration of the diffs since the snapshot
                LOG.debug("Migrated all base vhds.", instance=instance)
                return power_down_and_transfer_leaf_vhds(active_root_vdi_uuid,
                                                         active_vdi_uuids)

            remaining_chains = []
            if number_of_chains > 1:
                remaining_chains = ephemeral_chains[1:]

            userdevice = int(DEVICE_EPHEMERAL) + ephemeral_disk_index

            # Ensure we are not snapshotting a volume
            if not volume_utils.is_booted_from_volume(self._session, vm_ref,
                                                      userdevice):

                # Here we take a snapshot of the ephemeral disk,
                # and migrate all VHDs in the chain that are not being written
                # to. Once that is completed, we call back into this method to
                # either:
                # - migrate any remaining ephemeral disks
                # - or, if all disks are migrated, we power down and complete
                #   the migration but copying the diffs since all the snapshots
                #   were taken

                with vm_utils.snapshot_attached_here(self._session, instance,
                            vm_ref, label, str(userdevice)) as chain_vdi_uuids:

                    # remember active vdi, we will migrate these later
                    vdi_ref, vm_vdi_rec = vm_utils.get_vdi_for_vm_safely(
                        self._session, vm_ref, str(userdevice))
                    active_uuid = vm_vdi_rec['uuid']
                    active_vdi_uuids.append(active_uuid)

                    # migrate inactive vhds
                    inactive_vdi_uuids = chain_vdi_uuids[1:]
                    ephemeral_disk_number = ephemeral_disk_index + 1
                    for seq_num, vdi_uuid in enumerate(inactive_vdi_uuids,
                                                       start=1):
                        vm_utils.migrate_vhd(self._session, instance, vdi_uuid,
                                             dest, sr_path, seq_num,
                                             ephemeral_disk_number)

                    LOG.debug("Read-only migrated for disk: %s", userdevice,
                              instance=instance)

            # This method is recursive, so we will increment our index
            # and process again until the chains are empty.
            ephemeral_disk_index = ephemeral_disk_index + 1
            return _process_ephemeral_chain_recursive(remaining_chains,
                                                      active_vdi_uuids,
                                                      ephemeral_disk_index)

        @step
        def transfer_ephemeral_disks_then_all_leaf_vdis():
            ephemeral_chains = vm_utils.get_all_vdi_uuids_for_vm(
                    self._session, vm_ref,
                    min_userdevice=int(DEVICE_EPHEMERAL))

            if ephemeral_chains:
                ephemeral_chains = list(ephemeral_chains)
            else:
                ephemeral_chains = []

            _process_ephemeral_chain_recursive(ephemeral_chains, [])

        @step
        def power_down_and_transfer_leaf_vhds(root_vdi_uuid,
                                              ephemeral_vdi_uuids=None):
            self._resize_ensure_vm_is_shutdown(instance, vm_ref)
            if root_vdi_uuid is not None:
                vm_utils.migrate_vhd(self._session, instance, root_vdi_uuid,
                                     dest, sr_path, 0)
            if ephemeral_vdi_uuids:
                for ephemeral_disk_number, ephemeral_vdi_uuid in enumerate(
                            ephemeral_vdi_uuids, start=1):
                    vm_utils.migrate_vhd(self._session, instance,
                                         ephemeral_vdi_uuid, dest,
                                         sr_path, 0, ephemeral_disk_number)

        self._apply_orig_vm_name_label(instance, vm_ref)
        try:
            label = "%s-snapshot" % instance['name']

            if volume_utils.is_booted_from_volume(self._session, vm_ref):
                LOG.debug('Not snapshotting root disk since it is a volume',
                        instance=instance)
                # NOTE(alaski): This is done twice to match the number of
                # defined steps.
                fake_step_to_show_snapshot_complete()
                fake_step_to_show_snapshot_complete()
                # NOTE(alaski): This is set to None to avoid transferring the
                # VHD in power_down_and_transfer_leaf_vhds.
                active_root_vdi_uuid = None
                # snapshot and transfer all ephemeral disks
                # then power down and transfer any diffs since
                # the snapshots were taken
                transfer_ephemeral_disks_then_all_leaf_vdis()
                return

            with vm_utils.snapshot_attached_here(
                    self._session, instance, vm_ref, label) as root_vdi_uuids:
                # NOTE(johngarbutt) snapshot attached here will delete
                # the snapshot if an error occurs
                fake_step_to_show_snapshot_complete()

                # transfer all the non-active VHDs in the root disk chain
                transfer_immutable_vhds(root_vdi_uuids)
                vdi_ref, vm_vdi_rec = vm_utils.get_vdi_for_vm_safely(
                        self._session, vm_ref)
                active_root_vdi_uuid = vm_vdi_rec['uuid']

                # snapshot and transfer all ephemeral disks
                # then power down and transfer any diffs since
                # the snapshots were taken
                transfer_ephemeral_disks_then_all_leaf_vdis()

        except Exception as error:
            LOG.exception(_("_migrate_disk_resizing_up failed. "
                            "Restoring orig vm due_to: %s."),
                          error, instance=instance)
            try:
                self._restore_orig_vm_and_cleanup_orphan(instance)
                # TODO(johngarbutt) should also cleanup VHDs at destination
            except Exception as rollback_error:
                LOG.warning("_migrate_disk_resizing_up failed to "
                            "rollback: %s", rollback_error,
                            instance=instance)
            raise exception.InstanceFaultRollback(error)

    def _apply_orig_vm_name_label(self, instance, vm_ref):
        # NOTE(sirp): in case we're resizing to the same host (for dev
        # purposes), apply a suffix to name-label so the two VM records
        # extant until a confirm_resize don't collide.
        name_label = self._get_orig_vm_name_label(instance)
        vm_utils.set_vm_name_label(self._session, vm_ref, name_label)

    def _ensure_not_resize_down_ephemeral(self, instance, flavor):
        old_gb = instance.flavor.ephemeral_gb
        new_gb = flavor.ephemeral_gb

        if old_gb > new_gb:
            reason = _("Can't resize down ephemeral disks.")
            raise exception.ResizeError(reason)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, block_device_info):
        """Copies a VHD from one host machine to another, possibly
        resizing filesystem beforehand.

        :param instance: the instance that owns the VHD in question.
        :param dest: the destination host machine.
        :param flavor: flavor to resize to
        """
        self._ensure_not_resize_down_ephemeral(instance, flavor)

        # 0. Zero out the progress to begin
        self._update_instance_progress(context, instance,
                                       step=0,
                                       total_steps=RESIZE_TOTAL_STEPS)

        old_gb = instance.flavor.root_gb
        new_gb = flavor.root_gb
        resize_down = old_gb > new_gb

        if new_gb == 0 and old_gb != 0:
            reason = _("Can't resize a disk to 0 GB.")
            raise exception.ResizeError(reason=reason)

        vm_ref = self._get_vm_opaque_ref(instance)
        sr_path = vm_utils.get_sr_path(self._session)

        if resize_down:
            self._migrate_disk_resizing_down(
                    context, instance, dest, flavor, vm_ref, sr_path)
        else:
            self._migrate_disk_resizing_up(
                    context, instance, dest, vm_ref, sr_path)

        self._detach_block_devices_from_orig_vm(instance, block_device_info)

        # NOTE(sirp): disk_info isn't used by the xenapi driver, instead it
        # uses a staging-area (/images/instance<uuid>) and sequence-numbered
        # VHDs to figure out how to reconstruct the VDI chain after syncing
        disk_info = {}
        return disk_info

    def _detach_block_devices_from_orig_vm(self, instance, block_device_info):
        block_device_mapping = virt_driver.block_device_info_get_mapping(
                block_device_info)
        name_label = self._get_orig_vm_name_label(instance)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            mount_device = vol['mount_device'].rpartition("/")[2]
            self._volumeops.detach_volume(connection_info, name_label,
                                          mount_device)

    def _resize_up_vdis(self, instance, vdis):
        new_root_gb = instance.flavor.root_gb
        root_vdi = vdis.get('root')
        if new_root_gb and root_vdi:
            if root_vdi.get('osvol', False):  # Don't resize root volumes.
                LOG.debug("Not resizing the root volume.",
                    instance=instance)
            else:
                vdi_ref = root_vdi['ref']
                vm_utils.update_vdi_virtual_size(self._session, instance,
                                                 vdi_ref, new_root_gb)

        ephemeral_vdis = vdis.get('ephemerals')
        if not ephemeral_vdis:
            # NOTE(johngarbutt) no existing (migrated) ephemeral disks
            # to resize, so nothing more to do here.
            return

        total_ephemeral_gb = instance.flavor.ephemeral_gb
        if total_ephemeral_gb:
            sizes = vm_utils.get_ephemeral_disk_sizes(total_ephemeral_gb)
            # resize existing (migrated) ephemeral disks,
            # and add any extra disks if required due to a
            # larger total_ephemeral_gb (resize down is not supported).
            for userdevice, new_size in enumerate(sizes,
                                                  start=int(DEVICE_EPHEMERAL)):
                vdi = ephemeral_vdis.get(str(userdevice))
                if vdi:
                    vdi_ref = vdi['ref']
                    vm_utils.update_vdi_virtual_size(self._session, instance,
                                                     vdi_ref, new_size)
                else:
                    LOG.debug("Generating new ephemeral vdi %d during resize",
                              userdevice, instance=instance)
                    # NOTE(johngarbutt) we generate but don't attach
                    # the new disk to make up any additional ephemeral space
                    vdi_ref = vm_utils.generate_single_ephemeral(
                        self._session, instance, None, userdevice, new_size)
                    vdis[str(userdevice)] = {'ref': vdi_ref, 'generated': True}

    def reboot(self, instance, reboot_type, bad_volumes_callback=None):
        """Reboot VM instance."""
        # Note (salvatore-orlando): security group rules are not re-enforced
        # upon reboot, since this action on the XenAPI drivers does not
        # remove existing filters
        vm_ref = self._get_vm_opaque_ref(instance, check_rescue=True)

        try:
            if reboot_type == "HARD":
                self._session.call_xenapi('VM.hard_reboot', vm_ref)
            else:
                self._session.call_xenapi('VM.clean_reboot', vm_ref)
        except self._session.XenAPI.Failure as exc:
            details = exc.details
            if (details[0] == 'VM_BAD_POWER_STATE' and
                    details[-1] == 'halted'):
                LOG.info("Starting halted instance found during reboot",
                         instance=instance)
                self._start(instance, vm_ref=vm_ref,
                            bad_volumes_callback=bad_volumes_callback)
                return
            elif details[0] == 'SR_BACKEND_FAILURE_46':
                LOG.warning("Reboot failed due to bad volumes, detaching "
                            "bad volumes and starting halted instance",
                            instance=instance)
                self._start(instance, vm_ref=vm_ref,
                            bad_volumes_callback=bad_volumes_callback)
                return
            else:
                raise

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance."""
        if self.agent_enabled(instance):
            vm_ref = self._get_vm_opaque_ref(instance)
            agent = self._get_agent(instance, vm_ref)
            agent.set_admin_password(new_pass)
        else:
            raise NotImplementedError()

    def inject_file(self, instance, path, contents):
        """Write a file to the VM instance."""
        if self.agent_enabled(instance):
            vm_ref = self._get_vm_opaque_ref(instance)
            agent = self._get_agent(instance, vm_ref)
            agent.inject_file(path, contents)
        else:
            raise NotImplementedError()

    @staticmethod
    def _sanitize_xenstore_key(key):
        """Xenstore only allows the following characters as keys:

        ABCDEFGHIJKLMNOPQRSTUVWXYZ
        abcdefghijklmnopqrstuvwxyz
        0123456789-/_@

        So convert the others to _

        Also convert / to _, because that is somewhat like a path
        separator.
        """
        allowed_chars = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                         "abcdefghijklmnopqrstuvwxyz"
                         "0123456789-_@")
        return ''.join([x in allowed_chars and x or '_' for x in key])

    def _inject_instance_metadata(self, instance, vm_ref):
        """Inject instance metadata into xenstore."""
        @utils.synchronized('xenstore-' + instance['uuid'])
        def store_meta(topdir, data_dict):
            for key, value in data_dict.items():
                key = self._sanitize_xenstore_key(key)
                value = value or ''
                self._add_to_param_xenstore(vm_ref, '%s/%s' % (topdir, key),
                                            jsonutils.dumps(value))

        # Store user metadata
        store_meta('vm-data/user-metadata', utils.instance_meta(instance))

    def _inject_auto_disk_config(self, instance, vm_ref):
        """Inject instance's auto_disk_config attribute into xenstore."""
        @utils.synchronized('xenstore-' + instance['uuid'])
        def store_auto_disk_config(key, value):
            value = value and True or False
            self._add_to_param_xenstore(vm_ref, key, str(value))

        store_auto_disk_config('vm-data/auto-disk-config',
                               instance['auto_disk_config'])

    def change_instance_metadata(self, instance, diff):
        """Apply changes to instance metadata to xenstore."""
        try:
            vm_ref = self._get_vm_opaque_ref(instance)
        except exception.NotFound:
            # NOTE(johngarbutt) race conditions mean we can still get here
            # during operations where the VM is not present, like resize.
            # Skip the update when not possible, as the updated metadata will
            # get added when the VM is being booted up at the end of the
            # resize or rebuild.
            LOG.warning("Unable to update metadata, VM not found.",
                        instance=instance, exc_info=True)
            return

        def process_change(location, change):
            if change[0] == '-':
                self._remove_from_param_xenstore(vm_ref, location)
                try:
                    self._delete_from_xenstore(instance, location,
                                               vm_ref=vm_ref)
                except exception.InstanceNotFound:
                    # If the VM is not running then no need to update
                    # the live xenstore - the param xenstore will be
                    # used next time the VM is booted
                    pass
            elif change[0] == '+':
                self._add_to_param_xenstore(vm_ref, location,
                                            jsonutils.dumps(change[1]))
                try:
                    self._write_to_xenstore(instance, location, change[1],
                                            vm_ref=vm_ref)
                except exception.InstanceNotFound:
                    # If the VM is not running then no need to update
                    # the live xenstore
                    pass

        @utils.synchronized('xenstore-' + instance['uuid'])
        def update_meta():
            for key, change in diff.items():
                key = self._sanitize_xenstore_key(key)
                location = 'vm-data/user-metadata/%s' % key
                process_change(location, change)
        update_meta()

    def _find_vdi_refs(self, vm_ref, exclude_volumes=False):
        """Find and return the root and ephemeral vdi refs for a VM."""
        if not vm_ref:
            return {}

        vdi_refs = {}
        for vbd_ref in self._session.call_xenapi("VM.get_VBDs", vm_ref):
            vbd = self._session.call_xenapi("VBD.get_record", vbd_ref)
            if not exclude_volumes or 'osvol' not in vbd['other_config']:
                vdi_refs[vbd['userdevice']] = vbd['VDI']

        return vdi_refs

    def _destroy_vdis(self, instance, vm_ref):
        """Destroys all VDIs associated with a VM."""
        LOG.debug("Destroying VDIs", instance=instance)

        vdi_refs = vm_utils.lookup_vm_vdis(self._session, vm_ref)
        if not vdi_refs:
            return
        for vdi_ref in vdi_refs:
            try:
                vm_utils.destroy_vdi(self._session, vdi_ref)
            except exception.StorageError as exc:
                LOG.error(exc)

    def _destroy_kernel_ramdisk(self, instance, vm_ref):
        """Three situations can occur:

            1. We have neither a ramdisk nor a kernel, in which case we are a
               RAW image and can omit this step

            2. We have one or the other, in which case, we should flag as an
               error

            3. We have both, in which case we safely remove both the kernel
               and the ramdisk.

        """
        instance_uuid = instance['uuid']
        if not instance['kernel_id'] and not instance['ramdisk_id']:
            # 1. No kernel or ramdisk
            LOG.debug("Using RAW or VHD, skipping kernel and ramdisk "
                      "deletion", instance=instance)
            return

        if not (instance['kernel_id'] and instance['ramdisk_id']):
            # 2. We only have kernel xor ramdisk
            raise exception.InstanceUnacceptable(instance_id=instance_uuid,
               reason=_("instance has a kernel or ramdisk but not both"))

        # 3. We have both kernel and ramdisk
        (kernel, ramdisk) = vm_utils.lookup_kernel_ramdisk(self._session,
                                                           vm_ref)
        if kernel or ramdisk:
            vm_utils.destroy_kernel_ramdisk(self._session, instance,
                                            kernel, ramdisk)
            LOG.debug("kernel/ramdisk files removed", instance=instance)

    def _destroy_rescue_instance(self, rescue_vm_ref, original_vm_ref):
        """Destroy a rescue instance."""
        # Shutdown Rescue VM
        state = vm_utils.get_power_state(self._session, rescue_vm_ref)
        if state != power_state.SHUTDOWN:
            self._session.call_xenapi("VM.hard_shutdown", rescue_vm_ref)

        # Destroy Rescue VDIs
        vdi_refs = vm_utils.lookup_vm_vdis(self._session, rescue_vm_ref)

        # Don't destroy any VDIs belonging to the original VM
        orig_vdi_refs = self._find_vdi_refs(original_vm_ref)
        vdi_refs = set(vdi_refs) - set(orig_vdi_refs.values())

        vm_utils.safe_destroy_vdis(self._session, vdi_refs)

        # Destroy Rescue VM
        self._session.call_xenapi("VM.destroy", rescue_vm_ref)

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy VM instance.

        This is the method exposed by xenapi_conn.destroy(). The rest of the
        destroy_* methods are internal.

        """
        LOG.info("Destroying VM", instance=instance)

        # We don't use _get_vm_opaque_ref because the instance may
        # truly not exist because of a failure during build. A valid
        # vm_ref is checked correctly where necessary.
        vm_ref = vm_utils.lookup(self._session, instance['name'])

        rescue_vm_ref = vm_utils.lookup(self._session,
                                        "%s-rescue" % instance['name'])
        if rescue_vm_ref:
            self._destroy_rescue_instance(rescue_vm_ref, vm_ref)

        # NOTE(sirp): information about which volumes should be detached is
        # determined by the VBD.other_config['osvol'] attribute
        # NOTE(alaski): `block_device_info` is used to efficiently determine if
        # there's a volume attached, or which volumes to cleanup if there is
        # no VM present.
        return self._destroy(instance, vm_ref, network_info=network_info,
                             destroy_disks=destroy_disks,
                             block_device_info=block_device_info)

    def _destroy(self, instance, vm_ref, network_info=None,
                 destroy_disks=True, block_device_info=None):
        """Destroys VM instance by performing:

            1. A shutdown
            2. Destroying associated VDIs.
            3. Destroying kernel and ramdisk files (if necessary).
            4. Destroying that actual VM record.

        """
        if vm_ref is None:
            LOG.warning("VM is not present, skipping destroy...",
                        instance=instance)
            # NOTE(alaski): There should not be a block device mapping here,
            # but if there is it very likely means there was an error cleaning
            # it up previously and there is now an orphaned sr/pbd. This will
            # prevent both volume and instance deletes from completing.
            bdms = block_device_info['block_device_mapping'] or []
            if not bdms:
                return
            for bdm in bdms:
                volume_id = bdm['connection_info']['data']['volume_id']
                # Note(bobba): Check for the old-style SR first; if this
                # doesn't find the SR, also look for the new-style from
                # parse_sr_info
                sr_uuid = 'FA15E-D15C-%s' % volume_id
                sr_ref = None
                try:
                    sr_ref = volume_utils.find_sr_by_uuid(self._session,
                                                          sr_uuid)
                    if not sr_ref:
                        connection_data = bdm['connection_info']['data']
                        (sr_uuid, unused, unused) = volume_utils.parse_sr_info(
                            connection_data)
                        sr_ref = volume_utils.find_sr_by_uuid(self._session,
                                                              sr_uuid)
                except Exception:
                    LOG.exception(_('Failed to find an SR for volume %s'),
                                  volume_id, instance=instance)

                try:
                    if sr_ref:
                        volume_utils.forget_sr(self._session, sr_ref)
                    else:
                        LOG.error('Volume %s is associated with the '
                                  'instance but no SR was found for it',
                                  volume_id, instance=instance)
                except Exception:
                    LOG.exception(_('Failed to forget the SR for volume %s'),
                                  volume_id, instance=instance)
            return

        # NOTE(alaski): Attempt clean shutdown first if there's an attached
        # volume to reduce the risk of corruption.
        if block_device_info and block_device_info['block_device_mapping']:
            if not vm_utils.clean_shutdown_vm(self._session, instance, vm_ref):
                LOG.debug("Clean shutdown did not complete successfully, "
                          "trying hard shutdown.", instance=instance)
                vm_utils.hard_shutdown_vm(self._session, instance, vm_ref)
        else:
            vm_utils.hard_shutdown_vm(self._session, instance, vm_ref)

        if destroy_disks:
            self._volumeops.detach_all(vm_ref)
            self._destroy_vdis(instance, vm_ref)
            self._destroy_kernel_ramdisk(instance, vm_ref)

        self.unplug_vifs(instance, network_info, vm_ref)
        self.firewall_driver.unfilter_instance(
                instance, network_info=network_info)
        vm_utils.destroy_vm(self._session, instance, vm_ref)

    def pause(self, instance):
        """Pause VM instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._session.call_xenapi('VM.pause', vm_ref)

    def unpause(self, instance):
        """Unpause VM instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._session.call_xenapi('VM.unpause', vm_ref)

    def suspend(self, instance):
        """Suspend the specified instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._acquire_bootlock(vm_ref)
        self._session.call_xenapi('VM.suspend', vm_ref)

    def resume(self, instance):
        """Resume the specified instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._release_bootlock(vm_ref)
        self._session.call_xenapi('VM.resume', vm_ref, False, True)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance.

            - shutdown the instance VM.
            - set 'bootlock' to prevent the instance from starting in rescue.
            - spawn a rescue VM (the vm name-label will be instance-N-rescue).

        """
        rescue_name_label = '%s-rescue' % instance.name
        rescue_vm_ref = vm_utils.lookup(self._session, rescue_name_label)
        if rescue_vm_ref:
            raise RuntimeError(_("Instance is already in Rescue Mode: %s")
                               % instance.name)

        vm_ref = self._get_vm_opaque_ref(instance)
        vm_utils.hard_shutdown_vm(self._session, instance, vm_ref)
        self._acquire_bootlock(vm_ref)
        self.spawn(context, instance, image_meta, [], rescue_password,
                   network_info, name_label=rescue_name_label, rescue=True)

    def set_bootable(self, instance, is_bootable):
        """Set the ability to power on/off an instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        if is_bootable:
            self._release_bootlock(vm_ref)
        else:
            self._acquire_bootlock(vm_ref)

    def unrescue(self, instance):
        """Unrescue the specified instance.

            - unplug the instance VM's disk from the rescue VM.
            - teardown the rescue VM.
            - release the bootlock to allow the instance VM to start.

        """
        rescue_vm_ref = vm_utils.lookup(self._session,
                                        "%s-rescue" % instance.name)
        if not rescue_vm_ref:
            raise exception.InstanceNotInRescueMode(
                    instance_id=instance.uuid)

        original_vm_ref = self._get_vm_opaque_ref(instance)

        self._destroy_rescue_instance(rescue_vm_ref, original_vm_ref)
        self._release_bootlock(original_vm_ref)
        self._start(instance, original_vm_ref)

    def soft_delete(self, instance):
        """Soft delete the specified instance."""
        try:
            vm_ref = self._get_vm_opaque_ref(instance)
        except exception.NotFound:
            LOG.warning("VM is not present, skipping soft delete...",
                        instance=instance)
        else:
            vm_utils.hard_shutdown_vm(self._session, instance, vm_ref)
            self._acquire_bootlock(vm_ref)

    def restore(self, instance):
        """Restore the specified instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._release_bootlock(vm_ref)
        self._start(instance, vm_ref)

    def power_off(self, instance):
        """Power off the specified instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_utils.hard_shutdown_vm(self._session, instance, vm_ref)

    def power_on(self, instance):
        """Power on the specified instance."""
        vm_ref = self._get_vm_opaque_ref(instance)
        self._start(instance, vm_ref)

    def _cancel_stale_tasks(self, timeout, task):
        """Cancel the given tasks that are older than the given timeout."""
        task_refs = self._session.call_xenapi("task.get_by_name_label", task)
        for task_ref in task_refs:
            task_rec = self._session.call_xenapi("task.get_record", task_ref)
            task_created = timeutils.parse_strtime(task_rec["created"].value,
                                                   "%Y%m%dT%H:%M:%SZ")

            if timeutils.is_older_than(task_created, timeout):
                self._session.call_xenapi("task.cancel", task_ref)

    def poll_rebooting_instances(self, timeout, instances):
        """Look for rebooting instances that can be expired.

            - issue a "hard" reboot to any instance that has been stuck in a
              reboot state for >= the given timeout
        """
        # NOTE(jk0): All existing clean_reboot tasks must be canceled before
        # we can kick off the hard_reboot tasks.
        self._cancel_stale_tasks(timeout, 'VM.clean_reboot')

        ctxt = nova_context.get_admin_context()

        instances_info = dict(instance_count=len(instances),
                timeout=timeout)

        if instances_info["instance_count"] > 0:
            LOG.info("Found %(instance_count)d hung reboots "
                     "older than %(timeout)d seconds", instances_info)

        for instance in instances:
            LOG.info("Automatically hard rebooting", instance=instance)
            self.compute_api.reboot(ctxt, instance, "HARD")

    def get_info(self, instance, vm_ref=None):
        """Return data about VM instance."""
        vm_ref = vm_ref or self._get_vm_opaque_ref(instance)
        return vm_utils.compile_info(self._session, vm_ref)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_rec = self._session.call_xenapi("VM.get_record", vm_ref)
        return vm_utils.compile_diagnostics(vm_rec)

    def get_instance_diagnostics(self, instance):
        """Return data about VM diagnostics using the common API."""
        vm_ref = self._get_vm_opaque_ref(instance)
        return vm_utils.compile_instance_diagnostics(self._session, instance,
                                                     vm_ref)

    def _get_vif_device_map(self, vm_rec):
        vif_map = {}
        for vif in [self._session.call_xenapi("VIF.get_record", vrec)
                    for vrec in vm_rec['VIFs']]:
            vif_map[vif['device']] = vif['MAC']
        return vif_map

    def get_all_bw_counters(self):
        """Return running bandwidth counter for each interface on each
           running VM.
        """
        counters = vm_utils.fetch_bandwidth(self._session)
        bw = {}
        for vm_ref, vm_rec in vm_utils.list_vms(self._session):
            vif_map = self._get_vif_device_map(vm_rec)
            name = vm_rec['name_label']
            if 'nova_uuid' not in vm_rec['other_config']:
                continue
            dom = vm_rec.get('domid')
            if dom is None or dom not in counters:
                continue
            vifs_bw = bw.setdefault(name, {})
            for vif_num, vif_data in counters[dom].items():
                mac = vif_map[vif_num]
                vif_data['mac_address'] = mac
                vifs_bw[mac] = vif_data
        return bw

    def get_console_output(self, instance):
        """Return last few lines of instance console."""
        dom_id = self._get_last_dom_id(instance, check_rescue=True)

        try:
            raw_console_data = vm_management.get_console_log(
                self._session, dom_id)
        except self._session.XenAPI.Failure:
            LOG.exception(_("Guest does not have a console available"))
            raise exception.ConsoleNotAvailable()

        return zlib.decompress(base64.b64decode(raw_console_data))

    def get_vnc_console(self, instance):
        """Return connection info for a vnc console."""
        if instance.vm_state == vm_states.RESCUED:
            name = '%s-rescue' % instance.name
            vm_ref = vm_utils.lookup(self._session, name)
            if vm_ref is None:
                # The rescue instance might not be ready at this point.
                raise exception.InstanceNotReady(instance_id=instance.uuid)
        else:
            vm_ref = vm_utils.lookup(self._session, instance.name)
            if vm_ref is None:
                # The compute manager expects InstanceNotFound for this case.
                raise exception.InstanceNotFound(instance_id=instance.uuid)

        session_id = self._session.get_session_id()
        path = "/console?ref=%s&session_id=%s" % (str(vm_ref), session_id)

        # NOTE: XS5.6sp2+ use http over port 80 for xenapi com
        return ctype.ConsoleVNC(
            host=CONF.vnc.server_proxyclient_address,
            port=80,
            internal_access_path=path)

    def _vif_xenstore_data(self, vif):
        """convert a network info vif to injectable instance data."""

        def get_ip(ip):
            if not ip:
                return None
            return ip['address']

        def fixed_ip_dict(ip, subnet):
            if ip['version'] == 4:
                netmask = str(subnet.as_netaddr().netmask)
            else:
                netmask = subnet.as_netaddr()._prefixlen

            return {'ip': ip['address'],
                    'enabled': '1',
                    'netmask': netmask,
                    'gateway': get_ip(subnet['gateway'])}

        def convert_route(route):
            return {'route': str(netaddr.IPNetwork(route['cidr']).network),
                    'netmask': str(netaddr.IPNetwork(route['cidr']).netmask),
                    'gateway': get_ip(route['gateway'])}

        network = vif['network']
        v4_subnets = [subnet for subnet in network['subnets']
                             if subnet['version'] == 4]
        v6_subnets = [subnet for subnet in network['subnets']
                             if subnet['version'] == 6]

        # NOTE(tr3buchet): routes and DNS come from all subnets
        routes = [convert_route(route) for subnet in network['subnets']
                                       for route in subnet['routes']]
        dns = [get_ip(ip) for subnet in network['subnets']
                          for ip in subnet['dns']]

        info_dict = {'label': network['label'],
                     'mac': vif['address']}

        if v4_subnets:
            # NOTE(tr3buchet): gateway and broadcast from first subnet
            #                  primary IP will be from first subnet
            #                  subnets are generally unordered :(
            info_dict['gateway'] = get_ip(v4_subnets[0]['gateway'])
            info_dict['broadcast'] = str(v4_subnets[0].as_netaddr().broadcast)
            info_dict['ips'] = [fixed_ip_dict(ip, subnet)
                                for subnet in v4_subnets
                                for ip in subnet['ips']]
        if v6_subnets:
            # NOTE(tr3buchet): gateway from first subnet
            #                  primary IP will be from first subnet
            #                  subnets are generally unordered :(
            info_dict['gateway_v6'] = get_ip(v6_subnets[0]['gateway'])
            info_dict['ip6s'] = [fixed_ip_dict(ip, subnet)
                                 for subnet in v6_subnets
                                 for ip in subnet['ips']]
        if routes:
            info_dict['routes'] = routes

        if dns:
            info_dict['dns'] = list(set(dns))

        return info_dict

    def inject_network_info(self, instance, network_info, vm_ref=None):
        """Generate the network info and make calls to place it into the
        xenstore and the xenstore param list.
        vm_ref can be passed in because it will sometimes be different than
        what vm_utils.lookup(session, instance['name']) will find (ex: rescue)
        """
        vm_ref = vm_ref or self._get_vm_opaque_ref(instance)
        LOG.debug("Injecting network info to xenstore", instance=instance)

        @utils.synchronized('xenstore-' + instance['uuid'])
        def update_nwinfo():
            for vif in network_info:
                xs_data = self._vif_xenstore_data(vif)
                location = ('vm-data/networking/%s' %
                            vif['address'].replace(':', ''))
                self._add_to_param_xenstore(vm_ref,
                                            location,
                                            jsonutils.dumps(xs_data))
                try:
                    self._write_to_xenstore(instance, location, xs_data,
                                            vm_ref=vm_ref)
                except exception.InstanceNotFound:
                    # If the VM is not running, no need to update the
                    # live xenstore
                    pass
        update_nwinfo()

    def _create_vifs(self, instance, vm_ref, network_info):
        """Creates vifs for an instance."""

        LOG.debug("Creating vifs", instance=instance)
        vif_refs = []

        # this function raises if vm_ref is not a vm_opaque_ref
        self._session.call_xenapi("VM.get_domid", vm_ref)

        for device, vif in enumerate(network_info):
            LOG.debug('Create VIF %s', vif, instance=instance)
            vif_ref = self.vif_driver.plug(instance, vif,
                                           vm_ref=vm_ref, device=device)
            vif_refs.append(vif_ref)

        LOG.debug('Created the vif_refs: %(vifs)s for VM name: %(name)s',
                  {'vifs': vif_refs, 'name': instance['name']},
                  instance=instance)

    def plug_vifs(self, instance, network_info):
        """Set up VIF networking on the host."""
        for device, vif in enumerate(network_info):
            self.vif_driver.plug(instance, vif, device=device)

    def unplug_vifs(self, instance, network_info, vm_ref):
        if network_info:
            for vif in network_info:
                self.vif_driver.unplug(instance, vif, vm_ref)

    def reset_network(self, instance, rescue=False):
        """Calls resetnetwork method in agent."""
        if self.agent_enabled(instance):
            vm_ref = self._get_vm_opaque_ref(instance)
            agent = self._get_agent(instance, vm_ref)
            self._inject_hostname(instance, vm_ref, rescue)
            agent.resetnetwork()
            self._remove_hostname(instance, vm_ref)
        else:
            raise NotImplementedError()

    def _inject_hostname(self, instance, vm_ref, rescue):
        """Inject the hostname of the instance into the xenstore."""
        hostname = instance['hostname']
        if rescue:
            hostname = 'RESCUE-%s' % hostname

        if instance['os_type'] == "windows":
            # NOTE(jk0): Windows host names can only be <= 15 chars.
            hostname = hostname[:15]

        LOG.debug("Injecting hostname (%s) into xenstore", hostname,
                  instance=instance)

        @utils.synchronized('xenstore-' + instance['uuid'])
        def update_hostname():
            self._add_to_param_xenstore(vm_ref, 'vm-data/hostname', hostname)

        update_hostname()

    def _remove_hostname(self, instance, vm_ref):
        LOG.debug("Removing hostname from xenstore", instance=instance)

        @utils.synchronized('xenstore-' + instance['uuid'])
        def update_hostname():
            self._remove_from_param_xenstore(vm_ref, 'vm-data/hostname')

        update_hostname()

    def _write_to_xenstore(self, instance, path, value, vm_ref=None):
        """Writes the passed value to the xenstore record for the given VM
        at the specified location. A XenAPIPlugin.PluginError will be raised
        if any error is encountered in the write process.
        """
        dom_id = self._get_dom_id(instance, vm_ref)
        try:
            return host_xenstore.write_record(self._session, dom_id, path,
                                              jsonutils.dumps(value))
        except self._session.XenAPI.Failure as e:
            return self._process_plugin_exception(e, 'write_record', instance)

    def _read_from_xenstore(self, instance, path, ignore_missing_path=True,
                            vm_ref=None):
        """Reads the passed location from xenstore for the given vm. Missing
        paths are ignored, unless explicitly stated not to, which causes
        xenstore to raise an exception. A XenAPIPlugin.PluginError is raised
        if any error is encountered in the read process.
        """
        # NOTE(sulo): These need to be string for valid field type
        # for xapi.
        dom_id = self._get_dom_id(instance, vm_ref)
        try:
            return host_xenstore.read_record(
                self._session, dom_id, path,
                ignore_missing_path=ignore_missing_path)
        except XenAPI.Failure as e:
            return self._process_plugin_exception(e, 'read_record', instance)

    def _delete_from_xenstore(self, instance, path, vm_ref=None):
        """Deletes the value from the xenstore record for the given VM at
        the specified location.  A XenAPIPlugin.PluginError will be
        raised if any error is encountered in the delete process.
        """
        dom_id = self._get_dom_id(instance, vm_ref)
        try:
            return host_xenstore.delete_record(self._session, dom_id, path)
        except XenAPI.Failure as e:
            return self._process_plugin_exception(e, 'delete_record', instance)

    def _process_plugin_exception(self, plugin_exception, method, instance):
        err_msg = plugin_exception.details[-1].splitlines()[-1]
        if 'TIMEOUT:' in err_msg:
            LOG.error('TIMEOUT: The call to %s timed out',
                      method, instance=instance)
            return {'returncode': 'timeout', 'message': err_msg}
        elif 'NOT IMPLEMENTED:' in err_msg:
            LOG.error('NOT IMPLEMENTED: The call to %s is not supported'
                      ' by the agent.', method, instance=instance)
            return {'returncode': 'notimplemented', 'message': err_msg}
        else:
            LOG.error('The call to %(method)s returned an error: %(e)s.',
                      {'method': method, 'e': plugin_exception},
                      instance=instance)
            return {'returncode': 'error', 'message': err_msg}

    def _get_dom_id(self, instance, vm_ref=None, check_rescue=False):
        vm_ref = vm_ref or self._get_vm_opaque_ref(instance, check_rescue)
        domid = self._session.call_xenapi("VM.get_domid", vm_ref)
        if not domid or domid == "-1":
            raise exception.InstanceNotFound(instance_id=instance['name'])
        return domid

    def _get_last_dom_id(self, instance, vm_ref=None, check_rescue=False):
        vm_ref = vm_ref or self._get_vm_opaque_ref(instance, check_rescue)
        other_config = self._session.call_xenapi("VM.get_other_config", vm_ref)
        if 'last_dom_id' not in other_config:
            raise exception.InstanceNotFound(instance_id=instance['name'])
        return other_config['last_dom_id']

    def _add_to_param_xenstore(self, vm_ref, key, val):
        """Takes a key/value pair and adds it to the xenstore parameter
        record for the given vm instance. If the key exists in xenstore,
        it is overwritten
        """
        self._remove_from_param_xenstore(vm_ref, key)
        self._session.call_xenapi('VM.add_to_xenstore_data', vm_ref, key, val)

    def _remove_from_param_xenstore(self, vm_ref, key):
        """Takes a single key and removes it from the xenstore parameter
        record data for the given VM.
        If the key doesn't exist, the request is ignored.
        """
        self._session.call_xenapi('VM.remove_from_xenstore_data', vm_ref, key)

    def refresh_security_group_rules(self, security_group_id):
        """recreates security group rules for every instance."""
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_instance_security_rules(self, instance):
        """recreates security group rules for specified instance."""
        self.firewall_driver.refresh_instance_security_rules(instance)

    def unfilter_instance(self, instance_ref, network_info):
        """Removes filters for each VIF of the specified instance."""
        self.firewall_driver.unfilter_instance(instance_ref,
                                               network_info=network_info)

    def _get_host_opaque_ref(self, hostname):
        host_ref_set = self._session.host.get_by_name_label(hostname)
        # If xenapi can't get host ref by the name label, it means the
        # destination host is not in the same pool with the source host.
        if host_ref_set is None or host_ref_set == []:
            return None
        # It should be only one host with the name, or there would be
        # a confuse on which host is required
        if len(host_ref_set) > 1:
            reason = _('Multiple hosts have the same hostname: %s.') % hostname
            raise exception.MigrationPreCheckError(reason=reason)
        return host_ref_set[0]

    def _get_host_ref_no_aggr(self):
        # Pull the current host ref from Dom0's resident_on field.  This
        # allows us a simple way to pull the accurate host without aggregates
        dom0_rec = self._session.call_xenapi("VM.get_all_records_where",
                                             'field "domid"="0"')
        dom0_ref = list(dom0_rec.keys())[0]

        return dom0_rec[dom0_ref]['resident_on']

    def _get_host_software_versions(self):
        # Get software versions from host.get_record.
        # Works around aggregate checking as not all places use aggregates.
        host_ref = self._get_host_ref_no_aggr()
        host_rec = self._session.call_xenapi("host.get_record", host_ref)
        return host_rec['software_version']

    def _get_network_ref(self):
        # Get the network to for migrate.
        # This is the one associated with the pif marked management. From cli:
        # uuid=`xe pif-list --minimal management=true`
        # xe pif-param-get param-name=network-uuid uuid=$uuid
        expr = ('field "management" = "true" and field "host" = "%s"' %
                self._session.host_ref)
        pifs = self._session.call_xenapi('PIF.get_all_records_where',
                                         expr)
        if len(pifs) != 1:
            msg = _('No suitable network for migrate')
            raise exception.MigrationPreCheckError(reason=msg)

        pifkey = list(pifs.keys())[0]
        if not (netutils.is_valid_ipv4(pifs[pifkey]['IP']) or
                netutils.is_valid_ipv6(pifs[pifkey]['IPv6'])):
            msg = (_('PIF %s does not contain IP address')
                   % pifs[pifkey]['uuid'])
            raise exception.MigrationPreCheckError(reason=msg)

        nwref = pifs[list(pifs.keys())[0]]['network']
        return nwref

    def _migrate_receive(self, ctxt):
        destref = self._session.host_ref
        # Get the network to for migrate.
        nwref = self._get_network_ref()
        try:
            options = {}
            migrate_data = self._session.call_xenapi("host.migrate_receive",
                                                     destref,
                                                     nwref,
                                                     options)
        except self._session.XenAPI.Failure:
            LOG.exception(_('Migrate Receive failed'))
            msg = _('Migrate Receive failed')
            raise exception.MigrationPreCheckError(reason=msg)
        return migrate_data

    def _get_iscsi_srs(self, ctxt, instance_ref):
        vm_ref = self._get_vm_opaque_ref(instance_ref)
        vbd_refs = self._session.call_xenapi("VM.get_VBDs", vm_ref)

        iscsi_srs = []

        for vbd_ref in vbd_refs:
            vdi_ref = self._session.call_xenapi("VBD.get_VDI", vbd_ref)
            # Check if it's on an iSCSI SR
            sr_ref = self._session.call_xenapi("VDI.get_SR", vdi_ref)
            if self._session.call_xenapi("SR.get_type", sr_ref) == 'iscsi':
                iscsi_srs.append(sr_ref)

        return iscsi_srs

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        :param ctxt: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param block_migration: if true, prepare for block migration
                                if None, calculate it from driver
        :param disk_over_commit: if true, allow disk over commit

        """
        dest_check_data = objects.XenapiLiveMigrateData()

        src = instance_ref.host

        def _host_in_this_pool(host_name_label):
            host_ref = self._get_host_opaque_ref(host_name_label)
            if not host_ref:
                return False
            return vm_utils.host_in_this_pool(self._session, host_ref)

        # Check if migrate happen in a xapi pool
        pooled_migrate = _host_in_this_pool(src)
        # Notes(eliqiao): if block_migration is None, we calculate it
        # by checking if src and dest node are in same xapi pool
        if block_migration is None:
            if not pooled_migrate:
                block_migration = True
            else:
                sr_ref = vm_utils.safe_find_sr(self._session)
                sr_rec = self._session.get_rec('SR', sr_ref)
                block_migration = not sr_rec["shared"]

        if block_migration:
            dest_check_data.block_migration = True
            dest_check_data.migrate_send_data = self._migrate_receive(ctxt)
            dest_check_data.destination_sr_ref = vm_utils.safe_find_sr(
                self._session)
        else:
            dest_check_data.block_migration = False
            # TODO(eilqiao): There is still one case that block_migration is
            # passed from admin user, so we need this check until
            # block_migration flag is removed from API
            if not pooled_migrate:
                reason = _("Destination host is not in the same shared "
                           "storage pool as source host %s.") % src
                raise exception.MigrationPreCheckError(reason=reason)
            # TODO(johngarbutt) we currently assume
            # instance is on a SR shared with other destination
            # block migration work will be able to resolve this

        # Set the default net_ref for use in generate_vif_mapping
        net_ref = self._get_network_ref()
        dest_check_data.vif_uuid_map = {'': net_ref}
        return dest_check_data

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        """Check if it's possible to execute live migration on the source side.

        :param ctxt: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest_check_data: data returned by the check on the
                                destination, includes block_migration flag

        """
        if len(self._get_iscsi_srs(ctxt, instance_ref)) > 0:
            # XAPI must support the relaxed SR check for live migrating with
            # iSCSI VBDs
            if not self._session.is_xsm_sr_check_relaxed():
                raise exception.MigrationError(reason=_('XAPI supporting '
                                'relax-xsm-sr-check=true required'))

        # TODO(bkaminski): This entire block needs to be removed from this
        # if statement. Live Migration should assert_can_migrate either way.
        if ('block_migration' in dest_check_data and
                dest_check_data.block_migration):
            vm_ref = self._get_vm_opaque_ref(instance_ref)
            host_sw = self._get_host_software_versions()
            host_pfv = host_sw['platform_version']
            try:
                self._call_live_migrate_command(
                    "VM.assert_can_migrate", vm_ref, dest_check_data)
            except self._session.XenAPI.Failure as exc:
                reason = exc.details[0]
                # XCP>=2.1 Will error on this assert call if iSCSI are attached
                # as the SR has not been configured on the hypervisor at this
                # point in the migration. We swallow this exception until a
                # more intensive refactor can be done to correct this.
                if ("VDI_NOT_IN_MAP" in reason and
                        host_sw['platform_name'] == "XCP" and
                        versionutils.is_compatible("2.1.0", host_pfv)):
                    LOG.debug("Skipping exception for XCP>=2.1.0, %s", reason)
                    return dest_check_data
                msg = _('assert_can_migrate failed because: %s') % reason
                LOG.debug(msg, exc_info=True)
                raise exception.MigrationPreCheckError(reason=msg)
        return dest_check_data

    def _ensure_pv_driver_info_for_live_migration(self, instance, vm_ref):
        """Checks if pv drivers are present for this instance. If it is
        present but not reported, try to fake the info for live-migration.
        """
        if self._pv_driver_version_reported(instance, vm_ref):
            # Since driver version is reported we do not need to do anything
            return

        if self._pv_device_reported(instance, vm_ref):
            LOG.debug("PV device present but missing pv driver info. "
                      "Attempting to insert missing info in xenstore.",
                      instance=instance)
            self._write_fake_pv_version(instance, vm_ref)
        else:
            LOG.debug("Could not determine the presence of pv device. "
                      "Skipping inserting pv driver info.",
                      instance=instance)

    def _pv_driver_version_reported(self, instance, vm_ref):
        xs_path = "attr/PVAddons/MajorVersion"
        major_version = self._read_from_xenstore(instance, xs_path,
                                                 vm_ref=vm_ref)
        LOG.debug("Major Version: %s reported.", major_version,
                  instance=instance)
        # xenstore reports back string only, if the path is missing we get
        # None as string, since missing paths are ignored.
        if major_version == '"None"':
            return False
        else:
            return True

    def _pv_device_reported(self, instance, vm_ref):
        vm_rec = self._session.VM.get_record(vm_ref)
        vif_list = [self._session.call_xenapi("VIF.get_record", vrec)
                    for vrec in vm_rec['VIFs']]
        net_devices = [vif['device'] for vif in vif_list]
        # NOTE(sulo): We infer the presence of pv driver
        # by the presence of a pv network device. If xenstore reports
        # device status as connected (status=4) we take that as the presence
        # of pv driver. Any other status will likely cause migration to fail.
        for device in net_devices:
            xs_path = "device/vif/%s/state" % device
            ret = self._read_from_xenstore(instance, xs_path, vm_ref=vm_ref)
            LOG.debug("PV Device vif.%(vif_ref)s reporting state %(ret)s",
                      {'vif_ref': device, 'ret': ret}, instance=instance)
            if strutils.is_int_like(ret) and int(ret) == 4:
                return True

        return False

    def _write_fake_pv_version(self, instance, vm_ref):
        version = self._session.product_version
        LOG.debug("Writing pvtools version major: %(major)s minor: %(minor)s "
                  "micro: %(micro)s", {'major': version[0],
                                       'minor': version[1],
                                       'micro': version[2]},
                                       instance=instance)
        major_ver = "attr/PVAddons/MajorVersion"
        self._write_to_xenstore(instance, major_ver, version[0], vm_ref=vm_ref)
        minor_ver = "attr/PVAddons/MinorVersion"
        self._write_to_xenstore(instance, minor_ver, version[1], vm_ref=vm_ref)
        micro_ver = "attr/PVAddons/MicroVersion"
        self._write_to_xenstore(instance, micro_ver, version[2], vm_ref=vm_ref)
        xs_path = "data/updated"
        self._write_to_xenstore(instance, xs_path, "1", vm_ref=vm_ref)

    def _generate_vdi_map(self, destination_sr_ref, vm_ref, sr_ref=None):
        """generate a vdi_map for _call_live_migrate_command."""
        if sr_ref is None:
            sr_ref = vm_utils.safe_find_sr(self._session)
        vm_vdis = vm_utils.get_instance_vdis_for_sr(self._session,
                                                    vm_ref, sr_ref)
        return {vdi: destination_sr_ref for vdi in vm_vdis}

    def _call_live_migrate_command(self, command_name, vm_ref, migrate_data):
        """unpack xapi specific parameters, and call a live migrate command."""
        # NOTE(coreywright): though a nullable object field, migrate_send_data
        # is required for XenAPI live migration commands
        migrate_send_data = None
        if 'migrate_send_data' in migrate_data:
            migrate_send_data = migrate_data.migrate_send_data
        if not migrate_send_data:
            raise exception.InvalidParameterValue(
                'XenAPI requires destination migration data')
        # NOTE(coreywright): convert to xmlrpc marshallable type
        migrate_send_data = dict(migrate_send_data)

        destination_sr_ref = migrate_data.destination_sr_ref
        vdi_map = self._generate_vdi_map(destination_sr_ref, vm_ref)

        # Add destination SR refs for all of the VDIs that we created
        # as part of the pre migration callback
        sr_uuid_map = None
        if "sr_uuid_map" in migrate_data:
            sr_uuid_map = migrate_data.sr_uuid_map
        if sr_uuid_map:
            for sr_uuid in sr_uuid_map:
                # Source and destination SRs have the same UUID, so get the
                # reference for the local SR
                sr_ref = self._session.call_xenapi("SR.get_by_uuid", sr_uuid)
                vdi_map.update(
                    self._generate_vdi_map(
                        sr_uuid_map[sr_uuid], vm_ref, sr_ref))
        vif_map = {}
        # For block migration, need to pass vif map to the destination hosts.
        if not vm_utils.host_in_this_pool(self._session,
                                          migrate_send_data.get('host')):
            vif_uuid_map = None
            if 'vif_uuid_map' in migrate_data:
                vif_uuid_map = migrate_data.vif_uuid_map
            if vif_uuid_map:
                vif_map = self._generate_vif_network_map(vm_ref, vif_uuid_map)
                LOG.debug("Generated vif_map for live migration: %s", vif_map)
        options = {}
        self._session.call_xenapi(command_name, vm_ref,
                                  migrate_send_data, True,
                                  vdi_map, vif_map, options)

    def _generate_vif_network_map(self, vm_ref, vif_uuid_map):
        # Generate a mapping dictionary of src_vif_ref: dest_network_ref
        vif_map = {}
        # vif_uuid_map is dictionary of neutron_vif_uuid: dest_network_ref
        vifs = self._session.VM.get_VIFs(vm_ref)
        default_net_ref = vif_uuid_map.get('')
        for vif in vifs:
            other_config = self._session.VIF.get_other_config(vif)
            neutron_id = other_config.get('neutron-port-id')
            network_ref = vif_uuid_map.get(neutron_id, default_net_ref)
            if network_ref is None:
                raise exception.MigrationError(
                    reason=_('No mapping for source network %s') % (
                           neutron_id))
            vif_map[vif] = network_ref
        return vif_map

    def create_interim_networks(self, network_info):
        # Creating an interim bridge in destination host before live_migration
        vif_map = {}
        for vif in network_info:
            network_ref = self.vif_driver.create_vif_interim_network(vif)
            vif_map.update({vif['id']: network_ref})
        return vif_map

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        migrate_data.sr_uuid_map = self.connect_block_device_volumes(
                block_device_info)
        migrate_data.vif_uuid_map = self.create_interim_networks(network_info)
        LOG.debug("pre_live_migration, vif_uuid_map: %(vif_map)s, "
                  "sr_uuid_map: %(sr_map)s",
                  {'vif_map': migrate_data.vif_uuid_map,
                   'sr_map': migrate_data.sr_uuid_map}, instance=instance)
        return migrate_data

    def live_migrate(self, context, instance, destination_hostname,
                     post_method, recover_method, block_migration,
                     migrate_data=None):
        try:
            vm_ref = self._get_vm_opaque_ref(instance)
            # NOTE(sulo): We try to ensure that PV driver information is
            # present in xenstore for the instance we are trying to
            # live-migrate, if the process of faking pv version info fails,
            # we simply log it and carry on with the rest of the process.
            # Any xapi error due to PV version are caught and migration
            # will be safely reverted by the rollback process.
            try:
                self._ensure_pv_driver_info_for_live_migration(instance,
                                                               vm_ref)
            except Exception as e:
                LOG.warning(e)

            if migrate_data is not None:
                (kernel, ramdisk) = vm_utils.lookup_kernel_ramdisk(
                    self._session, vm_ref)
                migrate_data.kernel_file = kernel
                migrate_data.ramdisk_file = ramdisk

            if migrate_data is not None and migrate_data.block_migration:
                iscsi_srs = self._get_iscsi_srs(context, instance)
                try:
                    self._call_live_migrate_command(
                        "VM.migrate_send", vm_ref, migrate_data)
                except self._session.XenAPI.Failure:
                    LOG.exception(_('Migrate Send failed'))
                    raise exception.MigrationError(
                        reason=_('Migrate Send failed'))

                # Tidy up the iSCSI SRs
                for sr_ref in iscsi_srs:
                    volume_utils.forget_sr(self._session, sr_ref)
            else:
                host_ref = self._get_host_opaque_ref(destination_hostname)
                if not host_ref:
                    LOG.exception(_("Destination host %s was not found in the"
                                    " same shared storage pool as source "
                                    "host."), destination_hostname)
                    raise exception.MigrationError(
                        reason=_('No host with name %s found')
                        % destination_hostname)
                self._session.call_xenapi("VM.pool_migrate", vm_ref,
                                          host_ref, {"live": "true"})
            post_method(context, instance, destination_hostname,
                        block_migration, migrate_data)
        except Exception:
            with excutils.save_and_reraise_exception():
                recover_method(context, instance, destination_hostname,
                               migrate_data)

    def post_live_migration(self, context, instance, migrate_data=None):
        if migrate_data is not None:
            vm_utils.destroy_kernel_ramdisk(self._session, instance,
                                            migrate_data.kernel_file,
                                            migrate_data.ramdisk_file)

    def post_live_migration_at_source(self, context, instance, network_info):
        LOG.debug('post_live_migration_at_source, delete networks and bridges',
                  instance=instance)
        self._delete_networks_and_bridges(instance, network_info)

    def post_live_migration_at_destination(self, context, instance,
                                           network_info, block_migration,
                                           block_device_info):
        # FIXME(johngarbutt): we should block all traffic until we have
        # applied security groups, however this requires changes to XenServer
        self._prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

        # hook linux bridge and ovs bridge at destination
        self._post_start_actions(instance)
        vm_utils.create_kernel_and_ramdisk(context, self._session, instance,
                                           instance['name'])

        # NOTE(johngarbutt) workaround XenServer bug CA-98606
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_utils.strip_base_mirror_from_vdis(self._session, vm_ref)

    def rollback_live_migration_at_destination(self, instance, network_info,
                                               block_device_info):
        bdms = block_device_info['block_device_mapping'] or []

        for bdm in bdms:
            conn_data = bdm['connection_info']['data']
            uuid, label, params = volume_utils.parse_sr_info(conn_data)
            try:
                sr_ref = volume_utils.find_sr_by_uuid(self._session,
                                                      uuid)

                if sr_ref:
                    volume_utils.forget_sr(self._session, sr_ref)
            except Exception:
                LOG.exception(_('Failed to forget the SR for volume %s'),
                              params['id'], instance=instance)

        # delete VIF and network in destination host
        LOG.debug('rollback_live_migration_at_destination, delete networks '
                  'and bridges', instance=instance)
        self._delete_networks_and_bridges(instance, network_info)

    def _delete_networks_and_bridges(self, instance, network_info):
        # Unplug VIFs and delete networks
        for vif in network_info:
            try:
                self.vif_driver.delete_network_and_bridge(instance, vif['id'])
            except Exception:
                LOG.exception(_('Failed to delete networks and bridges with '
                                'VIF %s'), vif['id'], instance=instance)

    def get_per_instance_usage(self):
        """Get usage info about each active instance."""
        usage = {}

        def _is_active(vm_rec):
            power_state = vm_rec['power_state'].lower()
            return power_state in ['running', 'paused']

        def _get_uuid(vm_rec):
            other_config = vm_rec['other_config']
            return other_config.get('nova_uuid', None)

        for vm_ref, vm_rec in vm_utils.list_vms(self._session):
            uuid = _get_uuid(vm_rec)

            if _is_active(vm_rec) and uuid is not None:
                memory_mb = int(vm_rec['memory_static_max']) / units.Mi
                usage[uuid] = {'memory_mb': memory_mb, 'uuid': uuid}

        return usage

    def connect_block_device_volumes(self, block_device_info):
        sr_uuid_map = {}
        try:
            if block_device_info is not None:
                for block_device_map in block_device_info[
                                                'block_device_mapping']:
                    sr_uuid, _ = self._volumeops.connect_volume(
                            block_device_map['connection_info'])
                    sr_ref = self._session.call_xenapi('SR.get_by_uuid',
                                                       sr_uuid)
                    sr_uuid_map[sr_uuid] = sr_ref
        except Exception:
            with excutils.save_and_reraise_exception():
                # Disconnect the volumes we just connected
                for sr_ref in six.itervalues(sr_uuid_map):
                    volume_utils.forget_sr(self._session, sr_ref)

        return sr_uuid_map

    def attach_interface(self, instance, vif):
        LOG.debug("Attach interface, vif info: %s", vif, instance=instance)
        vm_ref = self._get_vm_opaque_ref(instance)

        @utils.synchronized('xenapi-vif-' + vm_ref)
        def _attach_interface(instance, vm_ref, vif):
            # find device for use with XenAPI
            allowed_devices = self._session.VM.get_allowed_VIF_devices(vm_ref)
            if allowed_devices is None or len(allowed_devices) == 0:
                raise exception.InterfaceAttachFailed(
                    _('attach network interface %(vif_id)s to instance '
                      '%(instance_uuid)s failed, no allowed devices.'),
                    vif_id=vif['id'], instance_uuid=instance.uuid)
            device = allowed_devices[0]
            try:
                # plug VIF
                self.vif_driver.plug(instance, vif, vm_ref=vm_ref,
                                     device=device)
                # set firewall filtering
                self.firewall_driver.setup_basic_filtering(instance, [vif])
            except exception.NovaException:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_('attach network interface %s failed.'),
                                  vif['id'], instance=instance)
                    try:
                        self.vif_driver.unplug(instance, vif, vm_ref)
                    except exception.NovaException:
                        # if unplug failed, no need to raise exception
                        LOG.warning('Unplug VIF %s failed.',
                                    vif['id'], instance=instance)

        _attach_interface(instance, vm_ref, vif)

    def detach_interface(self, instance, vif):
        LOG.debug("Detach interface, vif info: %s", vif, instance=instance)

        try:
            vm_ref = self._get_vm_opaque_ref(instance)
            self.vif_driver.unplug(instance, vif, vm_ref)
        except exception.InstanceNotFound:
            # Let this go up to the compute manager which will log a message
            # for it.
            raise
        except exception.NovaException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('detach network interface %s failed.'),
                              vif['id'], instance=instance)
