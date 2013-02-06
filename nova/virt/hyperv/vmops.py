# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Cloud.com, Inc
# Copyright 2012 Cloudbase Solutions Srl
# All Rights Reserved.
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
Management class for basic VM operations.
"""
import os

from nova.api.metadata import base as instance_metadata
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import lockutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import configdrive
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt import images

LOG = logging.getLogger(__name__)

hyperv_opts = [
    cfg.BoolOpt('limit_cpu_features',
                default=False,
                help='Required for live migration among '
                     'hosts with different CPU features'),
    cfg.BoolOpt('config_drive_inject_password',
                default=False,
                help='Sets the admin password in the config drive image'),
    cfg.StrOpt('qemu_img_cmd',
               default="qemu-img.exe",
               help='qemu-img is used to convert between '
                    'different image types'),
    cfg.BoolOpt('config_drive_cdrom',
                default=False,
                help='Attaches the Config Drive image as a cdrom drive '
                     'instead of a disk drive')
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts)
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('network_api_class', 'nova.network')


class VMOps(object):
    _vif_driver_class_map = {
        'nova.network.quantumv2.api.API':
        'nova.virt.hyperv.vif.HyperVQuantumVIFDriver',
        'nova.network.api.API':
        'nova.virt.hyperv.vif.HyperVNovaNetworkVIFDriver',
    }

    def __init__(self, volumeops):
        self._vmutils = vmutils.VMUtils()
        self._vhdutils = vhdutils.VHDUtils()
        self._pathutils = pathutils.PathUtils()
        self._volumeops = volumeops
        self._vif_driver = None
        self._load_vif_driver_class()

    def _load_vif_driver_class(self):
        try:
            class_name = self._vif_driver_class_map[CONF.network_api_class]
            self._vif_driver = importutils.import_object(class_name)
        except KeyError:
            raise TypeError(_("VIF driver not found for "
                              "network_api_class: %s") %
                            CONF.network_api_class)

    def list_instances(self):
        return self._vmutils.list_instances()

    def get_info(self, instance):
        """Get information about the VM."""
        LOG.debug(_("get_info called for instance"), instance=instance)

        instance_name = instance['name']
        if not self._vmutils.vm_exists(instance_name):
            raise exception.InstanceNotFound(instance=instance)

        info = self._vmutils.get_vm_summary_info(instance_name)

        state = constants.HYPERV_POWER_STATE[info['EnabledState']]
        return {'state': state,
                'max_mem': info['MemoryUsage'],
                'mem': info['MemoryUsage'],
                'num_cpu': info['NumberOfProcessors'],
                'cpu_time': info['UpTime']}

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info=None):
        """Create a new VM and start it."""

        instance_name = instance['name']
        if self._vmutils.vm_exists(instance_name):
            raise exception.InstanceExists(name=instance_name)

        ebs_root = self._volumeops.volume_in_mapping(
            self._volumeops.get_default_root_device(),
            block_device_info)

        #If is not a boot from volume spawn
        if not (ebs_root):
            #Fetch the file, assume it is a VHD file.
            vhdfile = self._pathutils.get_vhd_path(instance_name)
            try:
                self._cache_image(fn=self._fetch_image,
                                  context=context,
                                  target=vhdfile,
                                  fname=instance['image_ref'],
                                  image_id=instance['image_ref'],
                                  user=instance['user_id'],
                                  project=instance['project_id'],
                                  cow=CONF.use_cow_images)
            except Exception as exn:
                LOG.exception(_('cache image failed: %s'), exn)
                raise

        try:
            self._vmutils.create_vm(instance_name,
                                    instance['memory_mb'],
                                    instance['vcpus'],
                                    CONF.limit_cpu_features)

            if not ebs_root:
                self._vmutils.attach_ide_drive(instance_name,
                                               vhdfile,
                                               0,
                                               0,
                                               constants.IDE_DISK)
            else:
                self._volumeops.attach_boot_volume(block_device_info,
                                                   instance_name)

            self._vmutils.create_scsi_controller(instance_name)

            for vif in network_info:
                LOG.debug(_('Creating nic for instance: %s'), instance_name)
                self._vmutils.create_nic(instance_name,
                                         vif['id'],
                                         vif['address'])
                self._vif_driver.plug(instance, vif)

            if configdrive.required_by(instance):
                self._create_config_drive(instance, injected_files,
                                          admin_password)

            self._set_vm_state(instance_name,
                               constants.HYPERV_VM_STATE_ENABLED)
        except Exception as ex:
            LOG.exception(ex)
            self.destroy(instance)
            raise vmutils.HyperVException(_('Spawn instance failed'))

    def _create_config_drive(self, instance, injected_files, admin_password):
        if CONF.config_drive_format != 'iso9660':
            vmutils.HyperVException(_('Invalid config_drive_format "%s"') %
                                    CONF.config_drive_format)

        LOG.info(_('Using config drive for instance: %s'), instance=instance)

        extra_md = {}
        if admin_password and CONF.config_drive_inject_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)

        instance_path = self._pathutils.get_instance_path(
            instance['name'])
        configdrive_path_iso = os.path.join(instance_path, 'configdrive.iso')
        LOG.info(_('Creating config drive at %(path)s'),
                 {'path': configdrive_path_iso}, instance=instance)

        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            try:
                cdb.make_drive(configdrive_path_iso)
            except exception.ProcessExecutionError, e:
                LOG.error(_('Creating config drive failed with error: %s'),
                          e, instance=instance)
                raise

        if not CONF.config_drive_cdrom:
            drive_type = constants.IDE_DISK
            configdrive_path = os.path.join(instance_path,
                                            'configdrive.vhd')
            utils.execute(CONF.qemu_img_cmd,
                          'convert',
                          '-f',
                          'raw',
                          '-O',
                          'vpc',
                          configdrive_path_iso,
                          configdrive_path,
                          attempts=1)
            os.remove(configdrive_path_iso)
        else:
            drive_type = constants.IDE_DVD
            configdrive_path = configdrive_path_iso

        self._vmutils.attach_ide_drive(instance['name'], configdrive_path,
                                       1, 0, drive_type)

    def destroy(self, instance, network_info=None, cleanup=True,
                destroy_disks=True):
        instance_name = instance['name']
        LOG.debug(_("Got request to destroy instance: %s"), instance_name)
        try:
            if self._vmutils.vm_exists(instance_name):
                volumes_drives_list = self._vmutils.destroy_vm(instance_name,
                                                               destroy_disks)
                #Disconnect volumes
                for volume_drive in volumes_drives_list:
                    self._volumeops.disconnect_volume(volume_drive)
            else:
                LOG.debug(_("Instance not found: %s"), instance_name)
        except Exception as ex:
            LOG.exception(ex)
            raise vmutils.HyperVException(_('Failed to destroy instance: %s') %
                                          instance_name)

    def reboot(self, instance, network_info, reboot_type):
        """Reboot the specified instance."""
        LOG.debug(_("reboot instance"), instance=instance)
        self._set_vm_state(instance['name'],
                           constants.HYPERV_VM_STATE_REBOOT)

    def pause(self, instance):
        """Pause VM instance."""
        LOG.debug(_("Pause instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_PAUSED)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        LOG.debug(_("Unpause instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_ENABLED)

    def suspend(self, instance):
        """Suspend the specified instance."""
        print instance
        LOG.debug(_("Suspend instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_SUSPENDED)

    def resume(self, instance):
        """Resume the suspended VM instance."""
        LOG.debug(_("Resume instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_ENABLED)

    def power_off(self, instance):
        """Power off the specified instance."""
        LOG.debug(_("Power off instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_DISABLED)

    def power_on(self, instance):
        """Power on the specified instance."""
        LOG.debug(_("Power on instance"), instance=instance)
        self._set_vm_state(instance["name"],
                           constants.HYPERV_VM_STATE_ENABLED)

    def _set_vm_state(self, vm_name, req_state):
        try:
            self._vmutils.set_vm_state(vm_name, req_state)
            LOG.debug(_("Successfully changed state of VM %(vm_name)s"
                        " to: %(req_state)s") % locals())
        except Exception as ex:
            LOG.exception(ex)
            msg = _("Failed to change vm state of %(vm_name)s"
                    " to %(req_state)s") % locals()
            raise vmutils.HyperVException(msg)

    def _fetch_image(self, target, context, image_id, user, project,
                     *args, **kwargs):
        images.fetch(context, image_id, target, user, project)

    def _cache_image(self, fn, target, fname, cow=False, size=None,
                     *args, **kwargs):
        """Wrapper for a method that creates and caches an image.

        This wrapper will save the image into a common store and create a
        copy for use by the hypervisor.

        The underlying method should specify a kwarg of target representing
        where the image will be saved.

        fname is used as the filename of the base image.  The filename needs
        to be unique to a given image.

        If cow is True, it will make a CoW image instead of a copy.
        """
        @lockutils.synchronized(fname, 'nova-')
        def call_if_not_exists(path, fn, *args, **kwargs):
            if not os.path.exists(path):
                fn(target=path, *args, **kwargs)

        if not self._pathutils.vhd_exists(target):
            LOG.debug(_("Use CoW image: %s"), cow)
            if cow:
                parent_path = self._pathutils.get_base_vhd_path(fname)
                call_if_not_exists(parent_path, fn, *args, **kwargs)

                LOG.debug(_("Creating differencing VHD. Parent: "
                            "%(parent_path)s, Target: %(target)s") % locals())
                try:
                    self._vhdutils.create_differencing_vhd(target, parent_path)
                except Exception as ex:
                    LOG.exception(ex)
                    raise vmutils.HyperVException(
                        _('Failed to create a differencing disk from '
                          '%(parent_path)s to %(target)s') % locals())
            else:
                call_if_not_exists(target, fn, *args, **kwargs)
