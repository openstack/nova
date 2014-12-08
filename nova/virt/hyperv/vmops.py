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
import time

from eventlet import timeout as etimeout
from oslo.config import cfg
from oslo.utils import excutils
from oslo.utils import importutils
from oslo.utils import units
from oslo_concurrency import processutils

from nova.api.metadata import base as instance_metadata
from nova import exception
from nova.i18n import _, _LI, _LE, _LW
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common import uuidutils
from nova import utils
from nova.virt import configdrive
from nova.virt import hardware
from nova.virt.hyperv import constants
from nova.virt.hyperv import imagecache
from nova.virt.hyperv import ioutils
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
                      'implies 512MB of RAM allocated at startup'),
    cfg.IntOpt('wait_soft_reboot_seconds',
               default=60,
               help='Number of seconds to wait for instance to shut down after'
                    ' soft reboot request is made. We fall back to hard reboot'
                    ' if instance does not shutdown within this window.'),
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts, 'hyperv')
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('network_api_class', 'nova.network')

SHUTDOWN_TIME_INCREMENT = 5
REBOOT_TYPE_SOFT = 'SOFT'
REBOOT_TYPE_HARD = 'HARD'


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

    # The console log is stored in two files, each should have at most half of
    # the maximum console log size.
    _MAX_CONSOLE_LOG_FILE_SIZE = units.Mi / 2

    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._vhdutils = utilsfactory.get_vhdutils()
        self._pathutils = utilsfactory.get_pathutils()
        self._volumeops = volumeops.VolumeOps()
        self._imagecache = imagecache.ImageCache()
        self._vif_driver = None
        self._load_vif_driver_class()
        self._vm_log_writers = {}

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
        LOG.debug("get_info called for instance", instance=instance)

        instance_name = instance['name']
        if not self._vmutils.vm_exists(instance_name):
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        info = self._vmutils.get_vm_summary_info(instance_name)

        state = constants.HYPERV_POWER_STATE[info['EnabledState']]
        return hardware.InstanceInfo(state=state,
                                     max_mem_kb=info['MemoryUsage'],
                                     mem_kb=info['MemoryUsage'],
                                     num_cpu=info['NumberOfProcessors'],
                                     cpu_time_ns=info['UpTime'])

    def _create_root_vhd(self, context, instance):
        base_vhd_path = self._imagecache.get_cached_image(context, instance)
        base_vhd_info = self._vhdutils.get_vhd_info(base_vhd_path)
        base_vhd_size = base_vhd_info['MaxInternalSize']
        format_ext = base_vhd_path.split('.')[-1]
        root_vhd_path = self._pathutils.get_root_vhd_path(instance['name'],
                                                          format_ext)
        root_vhd_size = instance['root_gb'] * units.Gi

        try:
            if CONF.use_cow_images:
                LOG.debug("Creating differencing VHD. Parent: "
                          "%(base_vhd_path)s, Target: %(root_vhd_path)s",
                          {'base_vhd_path': base_vhd_path,
                           'root_vhd_path': root_vhd_path},
                          instance=instance)
                self._vhdutils.create_differencing_vhd(root_vhd_path,
                                                       base_vhd_path)
                vhd_type = self._vhdutils.get_vhd_format(base_vhd_path)
                if vhd_type == constants.DISK_FORMAT_VHD:
                    # The base image has already been resized. As differencing
                    # vhdx images support it, the root image will be resized
                    # instead if needed.
                    return root_vhd_path
            else:
                LOG.debug("Copying VHD image %(base_vhd_path)s to target: "
                          "%(root_vhd_path)s",
                          {'base_vhd_path': base_vhd_path,
                           'root_vhd_path': root_vhd_path},
                          instance=instance)
                self._pathutils.copyfile(base_vhd_path, root_vhd_path)

            root_vhd_internal_size = (
                self._vhdutils.get_internal_vhd_size_by_file_size(
                    base_vhd_path, root_vhd_size))

            if self._is_resize_needed(root_vhd_path, base_vhd_size,
                                      root_vhd_internal_size,
                                      instance):
                self._vhdutils.resize_vhd(root_vhd_path,
                                          root_vhd_internal_size,
                                          is_file_max_size=False)
        except Exception:
            with excutils.save_and_reraise_exception():
                if self._pathutils.exists(root_vhd_path):
                    self._pathutils.remove(root_vhd_path)

        return root_vhd_path

    def _is_resize_needed(self, vhd_path, old_size, new_size, instance):
        if new_size < old_size:
            error_msg = _("Cannot resize a VHD to a smaller size, the"
                          " original size is %(old_size)s, the"
                          " newer size is %(new_size)s"
                          ) % {'old_size': old_size,
                               'new_size': new_size}
            raise vmutils.VHDResizeException(error_msg)
        elif new_size > old_size:
            LOG.debug("Resizing VHD %(vhd_path)s to new "
                      "size %(new_size)s" %
                      {'new_size': new_size,
                       'vhd_path': vhd_path},
                      instance=instance)
            return True
        return False

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
        LOG.info(_LI("Spawning new instance"), instance=instance)

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
                                           constants.DISK)
            ctrl_disk_addr += 1

        if eph_vhd_path:
            self._vmutils.attach_ide_drive(instance_name,
                                           eph_vhd_path,
                                           0,
                                           ctrl_disk_addr,
                                           constants.DISK)

        self._vmutils.create_scsi_controller(instance_name)

        self._volumeops.attach_volumes(block_device_info,
                                       instance_name,
                                       root_vhd_path is None)

        for vif in network_info:
            LOG.debug('Creating nic for instance', instance=instance)
            self._vmutils.create_nic(instance_name,
                                     vif['id'],
                                     vif['address'])
            self._vif_driver.plug(instance, vif)

        if CONF.hyperv.enable_instance_metrics_collection:
            self._vmutils.enable_vm_metrics_collection(instance_name)

        self._create_vm_com_port_pipe(instance)

    def _create_config_drive(self, instance, injected_files, admin_password):
        if CONF.config_drive_format != 'iso9660':
            raise vmutils.UnsupportedConfigDriveFormatException(
                _('Invalid config_drive_format "%s"') %
                CONF.config_drive_format)

        LOG.info(_LI('Using config drive for instance'), instance=instance)

        extra_md = {}
        if admin_password and CONF.hyperv.config_drive_inject_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)

        instance_path = self._pathutils.get_instance_dir(
            instance['name'])
        configdrive_path_iso = os.path.join(instance_path, 'configdrive.iso')
        LOG.info(_LI('Creating config drive at %(path)s'),
                 {'path': configdrive_path_iso}, instance=instance)

        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            try:
                cdb.make_drive(configdrive_path_iso)
            except processutils.ProcessExecutionError as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Creating config drive failed with '
                                  'error: %s'),
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

    def _delete_disk_files(self, instance_name):
        self._pathutils.get_instance_dir(instance_name,
                                         create_dir=False,
                                         remove_dir=True)

    def destroy(self, instance, network_info=None, block_device_info=None,
                destroy_disks=True):
        instance_name = instance['name']
        LOG.info(_LI("Got request to destroy instance"), instance=instance)
        try:
            if self._vmutils.vm_exists(instance_name):

                # Stop the VM first.
                self.power_off(instance)

                self._vmutils.destroy_vm(instance_name)
                self._volumeops.disconnect_volumes(block_device_info)
            else:
                LOG.debug("Instance not found", instance=instance)

            if destroy_disks:
                self._delete_disk_files(instance_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Failed to destroy instance: %s'),
                              instance_name)

    def reboot(self, instance, network_info, reboot_type):
        """Reboot the specified instance."""
        LOG.debug("Rebooting instance", instance=instance)

        if reboot_type == REBOOT_TYPE_SOFT:
            if self._soft_shutdown(instance):
                self.power_on(instance)
                return

        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_REBOOT)

    def _soft_shutdown(self, instance,
                       timeout=CONF.hyperv.wait_soft_reboot_seconds,
                       retry_interval=SHUTDOWN_TIME_INCREMENT):
        """Perform a soft shutdown on the VM.

           :return: True if the instance was shutdown within time limit,
                    False otherwise.
        """
        LOG.debug("Performing Soft shutdown on instance", instance=instance)

        while timeout > 0:
            # Perform a soft shutdown on the instance.
            # Wait maximum timeout for the instance to be shutdown.
            # If it was not shutdown, retry until it succeeds or a maximum of
            # time waited is equal to timeout.
            wait_time = min(retry_interval, timeout)
            try:
                LOG.debug("Soft shutdown instance, timeout remaining: %d",
                          timeout, instance=instance)
                self._vmutils.soft_shutdown_vm(instance.name)
                if self._wait_for_power_off(instance.name, wait_time):
                    LOG.info(_LI("Soft shutdown succeeded."),
                             instance=instance)
                    return True
            except vmutils.HyperVException as e:
                # Exception is raised when trying to shutdown the instance
                # while it is still booting.
                LOG.debug("Soft shutdown failed: %s", e, instance=instance)
                time.sleep(wait_time)

            timeout -= retry_interval

        LOG.warning(_LW("Timed out while waiting for soft shutdown."),
                    instance=instance)
        return False

    def pause(self, instance):
        """Pause VM instance."""
        LOG.debug("Pause instance", instance=instance)
        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_PAUSED)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        LOG.debug("Unpause instance", instance=instance)
        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_ENABLED)

    def suspend(self, instance):
        """Suspend the specified instance."""
        LOG.debug("Suspend instance", instance=instance)
        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_SUSPENDED)

    def resume(self, instance):
        """Resume the suspended VM instance."""
        LOG.debug("Resume instance", instance=instance)
        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_ENABLED)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance."""
        LOG.debug("Power off instance", instance=instance)
        if retry_interval <= 0:
            retry_interval = SHUTDOWN_TIME_INCREMENT
        if timeout and self._soft_shutdown(instance, timeout, retry_interval):
            return

        self._set_vm_state(instance,
                           constants.HYPERV_VM_STATE_DISABLED)

    def power_on(self, instance, block_device_info=None):
        """Power on the specified instance."""
        LOG.debug("Power on instance", instance=instance)

        if block_device_info:
            self._volumeops.fix_instance_volume_disk_paths(instance['name'],
                                                           block_device_info)

        self._set_vm_state(instance, constants.HYPERV_VM_STATE_ENABLED)

    def _set_vm_state(self, instance, req_state):
        instance_name = instance['name']
        instance_uuid = instance['uuid']

        try:
            self._vmutils.set_vm_state(instance_name, req_state)

            if req_state in (constants.HYPERV_VM_STATE_DISABLED,
                             constants.HYPERV_VM_STATE_REBOOT):
                self._delete_vm_console_log(instance)
            if req_state in (constants.HYPERV_VM_STATE_ENABLED,
                             constants.HYPERV_VM_STATE_REBOOT):
                self.log_vm_serial_output(instance_name,
                                          instance_uuid)

            LOG.debug("Successfully changed state of VM %(instance_name)s"
                      " to: %(req_state)s", {'instance_name': instance_name,
                                             'req_state': req_state})
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to change vm state of %(instance_name)s"
                              " to %(req_state)s"),
                          {'instance_name': instance_name,
                           'req_state': req_state})

    def _get_vm_state(self, instance_name):
        summary_info = self._vmutils.get_vm_summary_info(instance_name)
        return summary_info['EnabledState']

    def _wait_for_power_off(self, instance_name, time_limit):
        """Waiting for a VM to be in a disabled state.

           :return: True if the instance is shutdown within time_limit,
                    False otherwise.
        """

        desired_vm_states = [constants.HYPERV_VM_STATE_DISABLED]

        def _check_vm_status(instance_name):
            if self._get_vm_state(instance_name) in desired_vm_states:
                raise loopingcall.LoopingCallDone()

        periodic_call = loopingcall.FixedIntervalLoopingCall(_check_vm_status,
                                                             instance_name)

        try:
            # add a timeout to the periodic call.
            periodic_call.start(interval=SHUTDOWN_TIME_INCREMENT)
            etimeout.with_timeout(time_limit, periodic_call.wait)
        except etimeout.Timeout:
            # VM did not shutdown in the expected time_limit.
            return False
        finally:
            # stop the periodic call, in case of exceptions or Timeout.
            periodic_call.stop()

        return True

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """Resume guest state when a host is booted."""
        self.power_on(instance, block_device_info)

    def log_vm_serial_output(self, instance_name, instance_uuid):
        # Uses a 'thread' that will run in background, reading
        # the console output from the according named pipe and
        # write it to a file.
        console_log_path = self._pathutils.get_vm_console_log_paths(
            instance_name)[0]
        pipe_path = r'\\.\pipe\%s' % instance_uuid

        vm_log_writer = ioutils.IOThread(pipe_path, console_log_path,
                                         self._MAX_CONSOLE_LOG_FILE_SIZE)
        self._vm_log_writers[instance_uuid] = vm_log_writer

        vm_log_writer.start()

    def get_console_output(self, instance):
        console_log_paths = (
            self._pathutils.get_vm_console_log_paths(instance['name']))

        try:
            instance_log = ''
            # Start with the oldest console log file.
            for console_log_path in console_log_paths[::-1]:
                if os.path.exists(console_log_path):
                    with open(console_log_path, 'rb') as fp:
                        instance_log += fp.read()
            return instance_log
        except IOError as err:
            msg = _("Could not get instance console log. Error: %s") % err
            raise vmutils.HyperVException(msg, instance=instance)

    def _delete_vm_console_log(self, instance):
        console_log_files = self._pathutils.get_vm_console_log_paths(
            instance['name'])

        vm_log_writer = self._vm_log_writers.get(instance['uuid'])
        if vm_log_writer:
            vm_log_writer.join()

        for log_file in console_log_files:
            fileutils.delete_if_exists(log_file)

    def copy_vm_console_logs(self, vm_name, dest_host):
        local_log_paths = self._pathutils.get_vm_console_log_paths(
            vm_name)
        remote_log_paths = self._pathutils.get_vm_console_log_paths(
            vm_name, remote_server=dest_host)

        for local_log_path, remote_log_path in (local_log_paths,
                                                remote_log_paths):
            if self._pathutils.exists(local_log_path):
                self._pathutils.copy(local_log_path,
                                     remote_log_path)

    def _create_vm_com_port_pipe(self, instance):
        # Creates a pipe to the COM 0 serial port of the specified vm.
        pipe_path = r'\\.\pipe\%s' % instance['uuid']
        self._vmutils.get_vm_serial_port_connection(
            instance['name'], update_connection=pipe_path)

    def restart_vm_log_writers(self):
        # Restart the VM console log writers after nova compute restarts.
        active_instances = self._vmutils.get_active_instances()
        for instance_name in active_instances:
            instance_path = self._pathutils.get_instance_dir(instance_name)

            # Skip instances that are not created by Nova
            if not os.path.exists(instance_path):
                continue

            vm_serial_conn = self._vmutils.get_vm_serial_port_connection(
                instance_name)
            if vm_serial_conn:
                instance_uuid = os.path.basename(vm_serial_conn)
                self.log_vm_serial_output(instance_name, instance_uuid)
