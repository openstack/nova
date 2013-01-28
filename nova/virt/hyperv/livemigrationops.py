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
import os

from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova.virt.hyperv import livemigrationutils
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vmutils
from nova.virt import images

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('use_cow_images', 'nova.virt.driver')


class LiveMigrationOps(object):
    def __init__(self, volumeops):

        self._pathutils = pathutils.PathUtils()
        self._vmutils = vmutils.VMUtils()
        self._livemigrutils = livemigrationutils.LiveMigrationUtils()
        self._volumeops = volumeops

    def live_migration(self, context, instance_ref, dest, post_method,
                       recover_method, block_migration=False,
                       migrate_data=None):
        LOG.debug(_("live_migration called"), instance=instance_ref)
        instance_name = instance_ref["name"]

        try:
            self._livemigrutils.live_migrate_vm(instance_name, dest)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug(_("Calling live migration recover_method "
                            "for instance: %s"), instance_name)
                recover_method(context, instance_ref, dest, block_migration)

        LOG.debug(_("Calling live migration post_method for instance: %s"),
                  instance_name)
        post_method(context, instance_ref, dest, block_migration)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info):
        LOG.debug(_("pre_live_migration called"), instance=instance)
        self._livemigrutils.check_live_migration_config()

        if CONF.use_cow_images:
            ebs_root = self._volumeops.volume_in_mapping(
                self._volumeops.get_default_root_device(),
                block_device_info)
            if not ebs_root:
                base_vhd_path = self._pathutils.get_base_vhd_path(
                    instance["image_ref"])
                if not os.path.exists(base_vhd_path):
                    images.fetch(context, instance["image_ref"], base_vhd_path,
                                 instance["user_id"], instance["project_id"])

    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info, block_migration):
        LOG.debug(_("post_live_migration_at_destination called"),
                  instance=instance_ref)

    def compare_cpu(self, cpu_info):
        LOG.debug(_("compare_cpu called %s"), cpu_info)
        return True
