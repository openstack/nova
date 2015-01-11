# Copyright 2012 Pedro Navarro Perez
# Copyright 2013 Cloudbase Solutions Srl
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
Management class for Storage-related functions (attach, detach, etc).
"""
import collections
import os
import re
import time

from oslo_config import cfg
from oslo_utils import excutils

from nova import exception
from nova.i18n import _, _LE, _LW
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)

hyper_volumeops_opts = [
    cfg.IntOpt('volume_attach_retry_count',
               default=10,
               help='The number of times to retry to attach a volume'),
    cfg.IntOpt('volume_attach_retry_interval',
               default=5,
               help='Interval between volume attachment attempts, in seconds'),
    cfg.IntOpt('mounted_disk_query_retry_count',
               default=10,
               help='The number of times to retry checking for a disk mounted '
                    'via iSCSI.'),
    cfg.IntOpt('mounted_disk_query_retry_interval',
               default=5,
               help='Interval between checks for a mounted iSCSI '
                    'disk, in seconds.'),
]

CONF = cfg.CONF
CONF.register_opts(hyper_volumeops_opts, 'hyperv')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')


class VolumeOps(object):
    """Management class for Volume-related tasks
    """

    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._volutils = utilsfactory.get_volumeutils()
        self._initiator = None
        self._default_root_device = 'vda'
        self.volume_drivers = {'smbfs': SMBFSVolumeDriver(),
                               'iscsi': ISCSIVolumeDriver()}

    def _get_volume_driver(self, driver_type=None, connection_info=None):
        if connection_info:
            driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        return self.volume_drivers[driver_type]

    def attach_volumes(self, block_device_info, instance_name, ebs_root):
        mapping = driver.block_device_info_get_mapping(block_device_info)

        if ebs_root:
            self.attach_volume(mapping[0]['connection_info'],
                               instance_name, True)
            mapping = mapping[1:]
        for vol in mapping:
            self.attach_volume(vol['connection_info'], instance_name)

    def disconnect_volumes(self, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        block_devices = self._group_block_devices_by_type(
            mapping)
        for driver_type, block_device_mapping in block_devices.items():
            volume_driver = self._get_volume_driver(driver_type)
            volume_driver.disconnect_volumes(block_device_mapping)

    def attach_volume(self, connection_info, instance_name, ebs_root=False):
        volume_driver = self._get_volume_driver(
            connection_info=connection_info)
        volume_driver.attach_volume(connection_info, instance_name, ebs_root)

    def detach_volume(self, connection_info, instance_name):
        volume_driver = self._get_volume_driver(
            connection_info=connection_info)
        volume_driver.detach_volume(connection_info, instance_name)

    def ebs_root_in_block_devices(self, block_device_info):
        if block_device_info:
            root_device = block_device_info.get('root_device_name')
            if not root_device:
                root_device = self._default_root_device
            return self._volutils.volume_in_mapping(root_device,
                                                    block_device_info)

    def fix_instance_volume_disk_paths(self, instance_name, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)

        if self.ebs_root_in_block_devices(block_device_info):
            mapping = mapping[1:]

        disk_address = 0
        for vol in mapping:
            connection_info = vol['connection_info']
            volume_driver = self._get_volume_driver(
                connection_info=connection_info)
            volume_driver.fix_instance_volume_disk_path(
                instance_name, connection_info, disk_address)
            disk_address += 1

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = self._volutils.get_iscsi_initiator()
            if not self._initiator:
                LOG.warning(_LW('Could not determine iscsi initiator name'),
                            instance=instance)
        return {
            'ip': CONF.my_block_storage_ip,
            'host': CONF.host,
            'initiator': self._initiator,
        }

    def initialize_volumes_connection(self, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            connection_info = vol['connection_info']
            volume_driver = self._get_volume_driver(
                connection_info=connection_info)
            volume_driver.initialize_volume_connection(connection_info)

    def _group_block_devices_by_type(self, block_device_mapping):
        block_devices = collections.defaultdict(list)
        for volume in block_device_mapping:
            connection_info = volume['connection_info']
            volume_type = connection_info.get('driver_volume_type')
            block_devices[volume_type].append(volume)
        return block_devices


class ISCSIVolumeDriver(object):
    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._volutils = utilsfactory.get_volumeutils()

    def login_storage_target(self, connection_info):
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        auth_method = data.get('auth_method')
        auth_username = data.get('auth_username')
        auth_password = data.get('auth_password')

        if auth_method and auth_method.upper() != 'CHAP':
            raise vmutils.HyperVException(
                _("Cannot log in target %(target_iqn)s. Unsupported iSCSI "
                  "authentication method: %(auth_method)s.") %
                 {'target_iqn': target_iqn,
                  'auth_method': auth_method})

        # Check if we already logged in
        if self._volutils.get_device_number_for_target(target_iqn, target_lun):
            LOG.debug("Already logged in on storage target. No need to "
                      "login. Portal: %(target_portal)s, "
                      "IQN: %(target_iqn)s, LUN: %(target_lun)s",
                      {'target_portal': target_portal,
                       'target_iqn': target_iqn, 'target_lun': target_lun})
        else:
            LOG.debug("Logging in on storage target. Portal: "
                      "%(target_portal)s, IQN: %(target_iqn)s, "
                      "LUN: %(target_lun)s",
                      {'target_portal': target_portal,
                       'target_iqn': target_iqn, 'target_lun': target_lun})
            self._volutils.login_storage_target(target_lun, target_iqn,
                                                target_portal, auth_username,
                                                auth_password)
            # Wait for the target to be mounted
            self._get_mounted_disk_from_lun(target_iqn, target_lun, True)

    def disconnect_volumes(self, block_device_mapping):
        iscsi_targets = collections.defaultdict(int)
        for vol in block_device_mapping:
            target_iqn = vol['connection_info']['data']['target_iqn']
            iscsi_targets[target_iqn] += 1

        for target_iqn, disconnected_luns in iscsi_targets.items():
            self.logout_storage_target(target_iqn, disconnected_luns)

    def logout_storage_target(self, target_iqn, disconnected_luns_count=1):
        total_available_luns = self._volutils.get_target_lun_count(
            target_iqn)

        if total_available_luns == disconnected_luns_count:
            LOG.debug("Logging off storage target %s", target_iqn)
            self._volutils.logout_storage_target(target_iqn)
        else:
            LOG.debug("Skipping disconnecting target %s as there "
                      "are LUNs still being used.", target_iqn)

    def attach_volume(self, connection_info, instance_name, ebs_root=False):
        """Attach a volume to the SCSI controller or to the IDE controller if
        ebs_root is True
        """
        target_iqn = None
        LOG.debug("Attach_volume: %(connection_info)s to %(instance_name)s",
                  {'connection_info': connection_info,
                   'instance_name': instance_name})
        try:
            self.login_storage_target(connection_info)

            data = connection_info['data']
            target_lun = data['target_lun']
            target_iqn = data['target_iqn']

            # Getting the mounted disk
            mounted_disk_path = self._get_mounted_disk_from_lun(target_iqn,
                                                                target_lun)

            if ebs_root:
                # Find the IDE controller for the vm.
                ctrller_path = self._vmutils.get_vm_ide_controller(
                    instance_name, 0)
                # Attaching to the first slot
                slot = 0
            else:
                # Find the SCSI controller for the vm
                ctrller_path = self._vmutils.get_vm_scsi_controller(
                    instance_name)
                slot = self._vmutils.get_free_controller_slot(ctrller_path)

            self._vmutils.attach_volume_to_controller(instance_name,
                                                      ctrller_path,
                                                      slot,
                                                      mounted_disk_path)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Unable to attach volume to instance %s'),
                          instance_name)
                if target_iqn:
                    self.logout_storage_target(target_iqn)

    def detach_volume(self, connection_info, instance_name):
        """Detach a volume to the SCSI controller."""
        LOG.debug("Detach_volume: %(connection_info)s "
                  "from %(instance_name)s",
                  {'connection_info': connection_info,
                   'instance_name': instance_name})

        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']

        # Getting the mounted disk
        mounted_disk_path = self._get_mounted_disk_from_lun(target_iqn,
                                                            target_lun)

        LOG.debug("Detaching physical disk from instance: %s",
                  mounted_disk_path)
        self._vmutils.detach_vm_disk(instance_name, mounted_disk_path)

        self.logout_storage_target(target_iqn)

    def _get_mounted_disk_from_lun(self, target_iqn, target_lun,
                                   wait_for_device=False):
        # The WMI query in get_device_number_for_target can incorrectly
        # return no data when the system is under load.  This issue can
        # be avoided by adding a retry.
        for i in xrange(CONF.hyperv.mounted_disk_query_retry_count):
            device_number = self._volutils.get_device_number_for_target(
                target_iqn, target_lun)
            if device_number in (None, -1):
                attempt = i + 1
                LOG.debug('Attempt %d to get device_number '
                          'from get_device_number_for_target failed. '
                          'Retrying...', attempt)
                time.sleep(CONF.hyperv.mounted_disk_query_retry_interval)
            else:
                break

        if device_number in (None, -1):
            raise exception.NotFound(_('Unable to find a mounted disk for '
                                       'target_iqn: %s') % target_iqn)
        LOG.debug('Device number: %(device_number)s, '
                  'target lun: %(target_lun)s',
                  {'device_number': device_number, 'target_lun': target_lun})
        # Finding Mounted disk drive
        for i in range(0, CONF.hyperv.volume_attach_retry_count):
            mounted_disk_path = self._vmutils.get_mounted_disk_by_drive_number(
                device_number)
            if mounted_disk_path or not wait_for_device:
                break
            time.sleep(CONF.hyperv.volume_attach_retry_interval)

        if not mounted_disk_path:
            raise exception.NotFound(_('Unable to find a mounted disk for '
                                       'target_iqn: %s. Please ensure that '
                                       'the host\'s SAN policy is set to '
                                       '"OfflineAll" or "OfflineShared"') %
                                     target_iqn)
        return mounted_disk_path

    def get_target_from_disk_path(self, physical_drive_path):
        return self._volutils.get_target_from_disk_path(physical_drive_path)

    def fix_instance_volume_disk_path(self, instance_name, connection_info,
                                      disk_address):
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']

        mounted_disk_path = self._get_mounted_disk_from_lun(
            target_iqn, target_lun, True)
        ctrller_path = self._vmutils.get_vm_scsi_controller(instance_name)
        self._vmutils.set_disk_host_resource(
            instance_name, ctrller_path, disk_address, mounted_disk_path)

    def get_target_lun_count(self, target_iqn):
        return self._volutils.get_target_lun_count(target_iqn)

    def initialize_volume_connection(self, connection_info):
        self.login_storage_target(connection_info)


class SMBFSVolumeDriver(object):
    def __init__(self):
        self._pathutils = utilsfactory.get_pathutils()
        self._vmutils = utilsfactory.get_vmutils()
        self._volutils = utilsfactory.get_volumeutils()
        self._username_regex = re.compile(r'user(?:name)?=([^, ]+)')
        self._password_regex = re.compile(r'pass(?:word)?=([^, ]+)')

    def attach_volume(self, connection_info, instance_name, ebs_root=False):
        self.ensure_share_mounted(connection_info)

        disk_path = self._get_disk_path(connection_info)

        try:
            if ebs_root:
                ctrller_path = self._vmutils.get_vm_ide_controller(
                    instance_name, 0)
                slot = 0
            else:
                ctrller_path = self._vmutils.get_vm_scsi_controller(
                 instance_name)
                slot = self._vmutils.get_free_controller_slot(ctrller_path)

            self._vmutils.attach_drive(instance_name,
                                       disk_path,
                                       ctrller_path,
                                       slot)
        except vmutils.HyperVException as exn:
            LOG.exception(_LE('Attach volume failed: %s'), exn)
            raise vmutils.HyperVException(_('Unable to attach volume '
                                            'to instance %s') % instance_name)

    def detach_volume(self, connection_info, instance_name):
        LOG.debug("Detaching volume: %(connection_info)s "
                  "from %(instance_name)s",
                  {'connection_info': connection_info,
                   'instance_name': instance_name})

        disk_path = self._get_disk_path(connection_info)
        export_path = self._get_export_path(connection_info)

        self._vmutils.detach_vm_disk(instance_name, disk_path,
                                     is_physical=False)
        self._pathutils.unmount_smb_share(export_path)

    def disconnect_volumes(self, block_device_mapping):
        export_paths = set()
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            export_path = self._get_export_path(connection_info)
            export_paths.add(export_path)

        for export_path in export_paths:
            self._pathutils.unmount_smb_share(export_path)

    def _get_export_path(self, connection_info):
        return connection_info['data']['export'].replace('/', '\\')

    def _get_disk_path(self, connection_info):
        export = self._get_export_path(connection_info)
        disk_name = connection_info['data']['name']
        disk_path = os.path.join(export, disk_name)
        return disk_path

    def ensure_share_mounted(self, connection_info):
        export_path = self._get_export_path(connection_info)

        if not self._pathutils.check_smb_mapping(export_path):
            opts_str = connection_info['data'].get('options', '')
            username, password = self._parse_credentials(opts_str)
            self._pathutils.mount_smb_share(export_path,
                                            username=username,
                                            password=password)

    def _parse_credentials(self, opts_str):
        match = self._username_regex.findall(opts_str)
        username = match[0] if match and match[0] != 'guest' else None

        match = self._password_regex.findall(opts_str)
        password = match[0] if match else None

        return username, password

    def fix_instance_volume_disk_path(self, instance_name, connection_info,
                                      disk_address):
        self.ensure_share_mounted(connection_info)

    def initialize_volume_connection(self, connection_info):
        self.ensure_share_mounted(connection_info)
