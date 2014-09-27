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
import functools
import os

from oslo.config import cfg

from nova.api.metadata import base as instance_metadata
from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova import utils
from nova.virt import configdrive
from nova.virt.hyperv import constants
from nova.virt.hyperv import imagecache
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeops

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
               help='Path of qemu-img command which is used to convert '
                    'between different image types'),
    cfg.BoolOpt('config_drive_cdrom',
                default=False,
                help='Attaches the Config Drive image as a cdrom drive '
                     'instead of a disk drive'),
    cfg.BoolOpt('enable_instance_metrics_collection',
                default=False,
                help='Enables metrics collections for an instance by using '
                     'Hyper-V\'s metric APIs. Collected data can by retrieved '
                     'by other apps and services, e.g.: Ceilometer. '
                     'Requires Hyper-V / Windows Server 2012 and above'),
    cfg.FloatOpt('dynamic_memory_ratio',
                 default=1.0,
                 help='Enables dynamic memory allocation (ballooning) when '
                      'set to a value greater than 1. The value expresses '
                      'the ratio between the total RAM assigned to an '
                      'instance and its startup RAM amount. For example a '
                      'ratio of 2.0 for an instance with 1024MB of RAM '
                      'implies 512MB of RAM allocated at startup')
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts, 'hyperv')
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('network_api_class', 'nova.network')


def check_admin_permissions(function):
    @functools.wraps(function)
    def wrapper(self, *args, **kwds):

        # Make sure the windows account has the required admin permissions.
        self._vmutils.check_admin_permissions()
        return function(self, *args, **kwds)
    return wrapper


class VMOps(object):
    _vif_driver_class_map = {
        'nova.network.neutronv2.api.API':
        'nova.virt.hyperv.vif.HyperVNeutronVIFDriver',
        'nova.network.api.API':
        'nova.virt.hyperv.vif.HyperVNovaNetworkVIFDriver',
    }

    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._vhdutils = utilsfactory.get_vhdutils()
        self._pathutils = utilsfactory.get_pathutils()
        self._volumeops = volumeops.VolumeOps()
        self._imagecache = imagecache.ImageCache()
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

    def list_instance_uuids(self):
        instance_uuids = []
        for (instance_name, notes) in self._vmutils.list_instance_notes():
            if notes and uuidutils.is_uuid_like(notes[0]):
                instance_uuids.append(str(notes[0]))
            else:
                LOG.debug("Notes not found or not resembling a GUID for "
                          "instance: %s" % instance_name)
        return instance_uuids

    def list_instances(self):
        return self._vmutils.list_instances()

    def get_info(self, instance):
        """Get information about the VM."""
        LOG.debug(_("get_info called for instance"), instance=instance)

        instance_name = instance['name']
        if not self._vmutils.vm_exists(instance_name):
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        info = self._vmutils.get_vm_summary_info(instance_name)

        state = constants.HYPERV_POWER_STATE[info['EnabledState']]
        return {'state': state,
                'max_mem': info['MemoryUsage'],
                'mem': info['MemoryUsage'],
                'num_cpu': info['NumberOfProcessors'],
                'cpu_time': info['UpTime']}

    def _create_root_vhd(self, context, instance):
        base_vhd_path = self._imagecache.get_cached_image(context, instance)
        format_ext = base_vhd_path.split('.')[-1]
        root_vhd_path = self._pathutils.get_root_vhd_path(instance['name'],
                                                          format_ext)

        try:
            if CONF.use_cow_images:
                LOG.debug(_("Creating differencing VHD. Parent: "
                            "%(base_vhd_path)s, Target: %(root_vhd_path)s"),
                          {'base_vhd_path': base_vhd_path,
                           'root_vhd_path': root_vhd_path},
                          instance=instance)
                self._vhdutils.create_differencing_vhd(root_vhd_path,
                                                       base_vhd_path)
            else:
                LOG.debug(_("Copying VHD image %(base_vhd_path)s to target: "
                            "%(root_vhd_path)s"),
                          {'base_vhd_path': base_vhd_path,
                           'root_vhd_path': root_vhd_path},
                          instance=instance)
                self._pathutils.copyfile(base_vhd_path, root_vhd_path)

                base_vhd_info = self._vhdutils.get_vhd_info(base_vhd_path)
                base_vhd_size = base_vhd_info['MaxInternalSize']
                root_vhd_size = instance['root_gb'] * units.Gi

                root_vhd_internal_size = (
                        self._vhdutils.get_internal_vhd_size_by_file_size(
                            root_vhd_path, root_vhd_size))

                if root_vhd_internal_size < base_vhd_size:
                    error_msg = _("Cannot resize a VHD to a smaller size, the"
                                  " original size is %(base_vhd_size)s, the"
                                  " newer size is %(root_vhd_size)s"
                                  ) % {'base_vhd_size': base_vhd_size,
                                       'root_vhd_size': root_vhd_internal_size}
                    raise vmutils.HyperVException(error_msg)
                elif root_vhd_internal_size > base_vhd_size:
                    LOG.debug(_("Resizing VHD %(root_vhd_path)s to new "
                                "size %(root_vhd_size)s"),
                              {'root_vhd_size': root_vhd_internal_size,
                               'root_vhd_path': root_vhd_path},
                              instance=instance)
                    self._vhdutils.resize_vhd(root_vhd_path,
                                              root_vhd_internal_size,
                                              is_file_max_size=False)
        except Exception:
            with excutils.save_and_reraise_exception():
                if self._pathutils.exists(root_vhd_path):
                    self._pathutils.remove(root_vhd_path)

        return root_vhd_path

    def create_ephemeral_vhd(self, instance):
        eph_vhd_size = instance.get('ephemeral_gb', 0) * units.Gi
        if eph_vhd_size:
            vhd_format = self._vhdutils.get_best_supported_vhd_format()

            eph_vhd_path = self._pathutils.get_ephemeral_vhd_path(
                instance['name'], vhd_format)
            self._vhdutils.create_dynamic_vhd(eph_vhd_path, eph_vhd_size,
                                              vhd_format)
            return eph_vhd_path

    @check_admin_permissions
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info=None):
        """Create a new VM and start it."""
        LOG.info(_("Spawning new instance"), instance=instance)

        instance_name = instance['name']
        if self._vmutils.vm_exists(instance_name):
            raise exception.InstanceExists(name=instance_name)

        # Make sure we're starting with a clean slate.
        self._delete_disk_files(instance_name)

        if self._volumeops.ebs_root_in_block_devices(block_device_info):
            root_vhd_path = None
        else:
            root_vhd_path = self._create_root_vhd(context, instance)

        eph_vhd_path = self.create_ephemeral_vhd(instance)

        try:
            self.create_instance(instance, network_info, block_device_info,
                                 root_vhd_path, eph_vhd_path)

            if configdrive.required_by(instance):
                configdrive_path = self._create_config_drive(instance,
                                                             injected_files,
                                                             admin_password)
                self.attach_config_drive(instance, configdrive_path)

            self.power_on(instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.destroy(instance)

    def create_instance(self, instance, network_info, block_device_info,
                        root_vhd_path, eph_vhd_path):
        instance_name = instance['name']

        self._vmutils.create_vm(instance_name,
                                instance['memory_mb'],
                                instance['vcpus'],
                                CONF.hyperv.limit_cpu_features,
                                CONF.hyperv.dynamic_memory_ratio,
                                [instance['uuid']])

        ctrl_disk_addr = 0
        if root_vhd_path:
            self._vmutils.attach_ide_drive(instance_name,
                                           root_vhd_path,
                                           0,
                                           ctrl_disk_addr,
                                           constants.IDE_DISK)
            ctrl_disk_addr += 1

        if eph_vhd_path:
            self._vmutils.attach_ide_drive(instance_name,
                                           eph_vhd_path,
                                           0,
                                           ctrl_disk_addr,
                                           constants.IDE_DISK)

        self._vmutils.create_scsi_controller(instance_name)

        self._volumeops.attach_volumes(block_device_info,
                                       instance_name,
                                       root_vhd_path is None)

        for vif in network_info:
            LOG.debug(_('Creating nic for instance'), instance=instance)
            self._vmutils.create_nic(instance_name,
                                     vif['id'],
                                     vif['address'])
            self._vif_driver.plug(instance, vif)

        if CONF.hyperv.enable_instance_metrics_collection:
            self._vmutils.enable_vm_metrics_collection(instance_name)

    def _create_config_drive(self, instance, injected_files, admin_password):
        if CONF.config_drive_format != 'iso9660':
            raise vmutils.UnsupportedConfigDriveFormatException(
                _('Invalid config_drive_format "%s"') %
                CONF.config_drive_format)

        LOG.info(_('Using config drive for instance'), instance=instance)

        extra_md = {}
        if admin_password and CONF.hyperv.config_drive_inject_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)

        instance_path = self._pathutils.get_instance_dir(
            instance['name'])
        configdrive_path_iso = os.path.join(instance_path, 'configdrive.iso')
        LOG.info(_('Creating config drive at %(path)s'),
                 {'path': configdrive_path_iso}, instance=instance)

        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            try:
                cdb.make_drive(configdrive_path_iso)
            except processutils.ProcessExecutionError as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Creating config drive failed with error: %s'),
                              e, instance=instance)

        if not CONF.hyperv.config_drive_cdrom:
            configdrive_path = os.path.join(instance_path,
                                            'configdrive.vhd')
            utils.execute(CONF.hyperv.qemu_img_cmd,
                          'convert',
                          '-f',
                          'raw',
                          '-O',
                          'vpc',
                          configdrive_path_iso,
                          configdrive_path,
                          attempts=1)
            self._pathutils.remove(configdrive_path_iso)
        else:
            configdrive_path = configdrive_path_iso

        return configdrive_path

    def attach_config_drive(self, instance, configdrive_path):
        configdrive_ext = configdrive_path[(configdrive_path.rfind('.') + 1):]
        # Do the attach here and if there is a certain file format that isn't
        # supported in constants.DISK_FORMAT_MAP then bomb out.
        try:
            self._vmutils.attach_ide_drive(instance.name, configdrive_path,
                    1, 0, constants.DISK_FORMAT_MAP[configdrive_ext])
        except KeyError:
            raise exception.InvalidDiskFormat(disk_format=configdrive_ext)

    def _disconnect_volumes(self, volume_drives):
        for volume_drive in volume_drives:
            self._volumeops.disconnect_volume(volume_drive)

    def _delete_disk_files(self, instance_name):
        self._pathutils.get_instance_dir(instance_name,
                                         create_dir=False,
                                         remove_dir=True)

    def destroy(self, instance, network_info=None, block_device_info=None,
                destroy_disks=True):
        instance_name = instance['name']
        LOG.info(_("Got request to destroy instance"), instance=instance)
        try:
            if self._vmutils.vm_exists(instance_name):

                #Stop the VM first.
                self.power_off(instance)

                storage = self._vmutils.get_vm_storage_paths(instance_name)
                (disk_files, volume_drives) = storage

                self._vmutils.destroy_vm(instance_name)
                self._disconnect_volumes(volume_drives)
            else:
                LOG.debug(_("Instance not found"), instance=instance)

            if destroy_disks:
                self._delete_disk_files(instance_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Failed to destroy instance: %s'),
                              instance_name)

    def reboot(self, instance, network_info, reboot_type):
        """Reboot the specified instance."""
        LOG.debug(_("Rebooting instance"), instance=instance)
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
                        " to: %(req_state)s"),
                      {'vm_name': vm_name, 'req_state': req_state})
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Failed to change vm state of %(vm_name)s"
                            " to %(req_state)s"),
                          {'vm_name': vm_name, 'req_state': req_state})
