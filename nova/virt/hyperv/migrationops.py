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
Management class for migration / resize operations.
"""
import os

from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova.virt import configdrive
from nova.virt.hyperv import imagecache
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vmops
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeops

LOG = logging.getLogger(__name__)


class MigrationOps(object):
    def __init__(self):
        self._hostutils = utilsfactory.get_hostutils()
        self._vmutils = utilsfactory.get_vmutils()
        self._vhdutils = utilsfactory.get_vhdutils()
        self._pathutils = utilsfactory.get_pathutils()
        self._volumeops = volumeops.VolumeOps()
        self._vmops = vmops.VMOps()
        self._imagecache = imagecache.ImageCache()

    def _migrate_disk_files(self, instance_name, disk_files, dest):
        # TODO(mikal): it would be nice if this method took a full instance,
        # because it could then be passed to the log messages below.
        same_host = False
        if dest in self._hostutils.get_local_ips():
            same_host = True
            LOG.debug(_("Migration target is the source host"))
        else:
            LOG.debug(_("Migration target host: %s") % dest)

        instance_path = self._pathutils.get_instance_dir(instance_name)
        revert_path = self._pathutils.get_instance_migr_revert_dir(
            instance_name, remove_dir=True)
        dest_path = None

        try:
            if same_host:
                # Since source and target are the same, we copy the files to
                # a temporary location before moving them into place
                dest_path = '%s_tmp' % instance_path
                if self._pathutils.exists(dest_path):
                    self._pathutils.rmtree(dest_path)
                self._pathutils.makedirs(dest_path)
            else:
                dest_path = self._pathutils.get_instance_dir(
                    instance_name, dest, remove_dir=True)
            for disk_file in disk_files:
                # Skip the config drive as the instance is already configured
                if os.path.basename(disk_file).lower() != 'configdrive.vhd':
                    LOG.debug(_('Copying disk "%(disk_file)s" to '
                                '"%(dest_path)s"'),
                              {'disk_file': disk_file, 'dest_path': dest_path})
                    self._pathutils.copy(disk_file, dest_path)

            self._pathutils.rename(instance_path, revert_path)

            if same_host:
                self._pathutils.rename(dest_path, instance_path)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._cleanup_failed_disk_migration(instance_path, revert_path,
                                                    dest_path)

    def _cleanup_failed_disk_migration(self, instance_path,
                                       revert_path, dest_path):
        try:
            if dest_path and self._pathutils.exists(dest_path):
                self._pathutils.rmtree(dest_path)
            if self._pathutils.exists(revert_path):
                self._pathutils.rename(revert_path, instance_path)
        except Exception as ex:
            # Log and ignore this exception
            LOG.exception(ex)
            LOG.error(_("Cannot cleanup migration files"))

    def _check_target_flavor(self, instance, flavor):
        new_root_gb = flavor['root_gb']
        curr_root_gb = instance['root_gb']

        if new_root_gb < curr_root_gb:
            raise exception.InstanceFaultRollback(
                vmutils.VHDResizeException(
                    _("Cannot resize the root disk to a smaller size. "
                      "Current size: %(curr_root_gb)s GB. Requested size: "
                      "%(new_root_gb)s GB") %
                    {'curr_root_gb': curr_root_gb,
                     'new_root_gb': new_root_gb}))

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None):
        LOG.debug(_("migrate_disk_and_power_off called"), instance=instance)

        self._check_target_flavor(instance, flavor)

        self._vmops.power_off(instance)

        instance_name = instance["name"]

        (disk_files,
         volume_drives) = self._vmutils.get_vm_storage_paths(instance_name)

        if disk_files:
            self._migrate_disk_files(instance_name, disk_files, dest)

        self._vmops.destroy(instance, destroy_disks=False)

        # disk_info is not used
        return ""

    def confirm_migration(self, migration, instance, network_info):
        LOG.debug(_("confirm_migration called"), instance=instance)

        self._pathutils.get_instance_migr_revert_dir(instance['name'],
                                                     remove_dir=True)

    def _revert_migration_files(self, instance_name):
        instance_path = self._pathutils.get_instance_dir(
            instance_name, create_dir=False, remove_dir=True)

        revert_path = self._pathutils.get_instance_migr_revert_dir(
            instance_name)
        self._pathutils.rename(revert_path, instance_path)

    def _check_and_attach_config_drive(self, instance):
        if configdrive.required_by(instance):
            configdrive_path = self._pathutils.lookup_configdrive_path(
                instance.name)
            if configdrive_path:
                self._vmops.attach_config_drive(instance, configdrive_path)
            else:
                raise vmutils.HyperVException(
                    _("Config drive is required by instance: %s, "
                      "but it does not exist.") % instance.name)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        LOG.debug(_("finish_revert_migration called"), instance=instance)

        instance_name = instance['name']
        self._revert_migration_files(instance_name)

        if self._volumeops.ebs_root_in_block_devices(block_device_info):
            root_vhd_path = None
        else:
            root_vhd_path = self._pathutils.lookup_root_vhd_path(instance_name)

        eph_vhd_path = self._pathutils.lookup_ephemeral_vhd_path(instance_name)

        self._vmops.create_instance(instance, network_info, block_device_info,
                                    root_vhd_path, eph_vhd_path)

        self._check_and_attach_config_drive(instance)

        if power_on:
            self._vmops.power_on(instance)

    def _merge_base_vhd(self, diff_vhd_path, base_vhd_path):
        base_vhd_copy_path = os.path.join(os.path.dirname(diff_vhd_path),
                                          os.path.basename(base_vhd_path))
        try:
            LOG.debug(_('Copying base disk %(base_vhd_path)s to '
                        '%(base_vhd_copy_path)s'),
                      {'base_vhd_path': base_vhd_path,
                       'base_vhd_copy_path': base_vhd_copy_path})
            self._pathutils.copyfile(base_vhd_path, base_vhd_copy_path)

            LOG.debug(_("Reconnecting copied base VHD "
                        "%(base_vhd_copy_path)s and diff "
                        "VHD %(diff_vhd_path)s"),
                      {'base_vhd_copy_path': base_vhd_copy_path,
                       'diff_vhd_path': diff_vhd_path})
            self._vhdutils.reconnect_parent_vhd(diff_vhd_path,
                                                base_vhd_copy_path)

            LOG.debug(_("Merging base disk %(base_vhd_copy_path)s and "
                        "diff disk %(diff_vhd_path)s"),
                      {'base_vhd_copy_path': base_vhd_copy_path,
                       'diff_vhd_path': diff_vhd_path})
            self._vhdutils.merge_vhd(diff_vhd_path, base_vhd_copy_path)

            # Replace the differential VHD with the merged one
            self._pathutils.rename(base_vhd_copy_path, diff_vhd_path)
        except Exception:
            with excutils.save_and_reraise_exception():
                if self._pathutils.exists(base_vhd_copy_path):
                    self._pathutils.remove(base_vhd_copy_path)

    def _check_resize_vhd(self, vhd_path, vhd_info, new_size):
        curr_size = vhd_info['MaxInternalSize']
        if new_size < curr_size:
            raise vmutils.VHDResizeException(_("Cannot resize a VHD "
                                               "to a smaller size"))
        elif new_size > curr_size:
            self._resize_vhd(vhd_path, new_size)

    def _resize_vhd(self, vhd_path, new_size):
        if vhd_path.split('.')[-1].lower() == "vhd":
            LOG.debug(_("Getting parent disk info for disk: %s"), vhd_path)
            base_disk_path = self._vhdutils.get_vhd_parent_path(vhd_path)
            if base_disk_path:
                # A differential VHD cannot be resized. This limitation
                # does not apply to the VHDX format.
                self._merge_base_vhd(vhd_path, base_disk_path)
        LOG.debug(_("Resizing disk \"%(vhd_path)s\" to new max "
                    "size %(new_size)s"),
                  {'vhd_path': vhd_path, 'new_size': new_size})
        self._vhdutils.resize_vhd(vhd_path, new_size)

    def _check_base_disk(self, context, instance, diff_vhd_path,
                         src_base_disk_path):
        base_vhd_path = self._imagecache.get_cached_image(context, instance)

        # If the location of the base host differs between source
        # and target hosts we need to reconnect the base disk
        if src_base_disk_path.lower() != base_vhd_path.lower():
            LOG.debug(_("Reconnecting copied base VHD "
                        "%(base_vhd_path)s and diff "
                        "VHD %(diff_vhd_path)s"),
                      {'base_vhd_path': base_vhd_path,
                       'diff_vhd_path': diff_vhd_path})
            self._vhdutils.reconnect_parent_vhd(diff_vhd_path,
                                                base_vhd_path)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        LOG.debug(_("finish_migration called"), instance=instance)

        instance_name = instance['name']

        if self._volumeops.ebs_root_in_block_devices(block_device_info):
            root_vhd_path = None
        else:
            root_vhd_path = self._pathutils.lookup_root_vhd_path(instance_name)
            if not root_vhd_path:
                raise vmutils.HyperVException(_("Cannot find boot VHD "
                                                "file for instance: %s") %
                                              instance_name)

            root_vhd_info = self._vhdutils.get_vhd_info(root_vhd_path)
            src_base_disk_path = root_vhd_info.get("ParentPath")
            if src_base_disk_path:
                self._check_base_disk(context, instance, root_vhd_path,
                                      src_base_disk_path)

            if resize_instance:
                new_size = instance['root_gb'] * units.Gi
                self._check_resize_vhd(root_vhd_path, root_vhd_info, new_size)

        eph_vhd_path = self._pathutils.lookup_ephemeral_vhd_path(instance_name)
        if resize_instance:
            new_size = instance.get('ephemeral_gb', 0) * units.Gi
            if not eph_vhd_path:
                if new_size:
                    eph_vhd_path = self._vmops.create_ephemeral_vhd(instance)
            else:
                eph_vhd_info = self._vhdutils.get_vhd_info(eph_vhd_path)
                self._check_resize_vhd(eph_vhd_path, eph_vhd_info, new_size)

        self._vmops.create_instance(instance, network_info, block_device_info,
                                    root_vhd_path, eph_vhd_path)

        self._check_and_attach_config_drive(instance)

        if power_on:
            self._vmops.power_on(instance)
