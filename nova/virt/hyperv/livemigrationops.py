# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Management class for live migration VM operations.
"""
import functools

from oslo.config import cfg

from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.hyperv import imagecache
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import volumeops

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('use_cow_images', 'nova.virt.driver')


def check_os_version_requirement(function):
    @functools.wraps(function)
    def wrapper(self, *args, **kwds):
        if not self._livemigrutils:
            raise NotImplementedError(_('Live migration is supported '
                                        'starting with Hyper-V Server '
                                        '2012'))
        return function(self, *args, **kwds)
    return wrapper


class LiveMigrationOps(object):
    def __init__(self):
        # Live migration is supported starting from Hyper-V Server 2012
        if utilsfactory.get_hostutils().check_min_windows_version(6, 2):
            self._livemigrutils = utilsfactory.get_livemigrationutils()
        else:
            self._livemigrutils = None

        self._pathutils = utilsfactory.get_pathutils()
        self._volumeops = volumeops.VolumeOps()
        self._imagecache = imagecache.ImageCache()

    @check_os_version_requirement
    def live_migration(self, context, instance_ref, dest, post_method,
                       recover_method, block_migration=False,
                       migrate_data=None):
        LOG.debug(_("live_migration called"), instance=instance_ref)
        instance_name = instance_ref["name"]

        try:
            iscsi_targets = self._livemigrutils.live_migrate_vm(instance_name,
                                                                dest)
            for (target_iqn, target_lun) in iscsi_targets:
                self._volumeops.logout_storage_target(target_iqn)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug(_("Calling live migration recover_method "
                            "for instance: %s"), instance_name)
                recover_method(context, instance_ref, dest, block_migration)

        LOG.debug(_("Calling live migration post_method for instance: %s"),
                  instance_name)
        post_method(context, instance_ref, dest, block_migration)

    @check_os_version_requirement
    def pre_live_migration(self, context, instance, block_device_info,
                           network_info):
        LOG.debug(_("pre_live_migration called"), instance=instance)
        self._livemigrutils.check_live_migration_config()

        if CONF.use_cow_images:
            boot_from_volume = self._volumeops.ebs_root_in_block_devices(
                block_device_info)
            if not boot_from_volume:
                self._imagecache.get_cached_image(context, instance)

        self._volumeops.login_storage_targets(block_device_info)

    @check_os_version_requirement
    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info, block_migration):
        LOG.debug(_("post_live_migration_at_destination called"),
                  instance=instance_ref)

    @check_os_version_requirement
    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        LOG.debug(_("check_can_live_migrate_destination called"), instance_ref)
        return {}

    @check_os_version_requirement
    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        LOG.debug(_("check_can_live_migrate_destination_cleanup called"))

    @check_os_version_requirement
    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        LOG.debug(_("check_can_live_migrate_source called"), instance_ref)
        return dest_check_data
