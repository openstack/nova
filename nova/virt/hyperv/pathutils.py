# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

import os
import shutil

from nova.openstack.common import cfg
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('instances_path', 'nova.compute.manager')


class PathUtils(object):
    def open(self, path, mode):
        """Wrapper on __builin__.open used to simplify unit testing."""
        import __builtin__
        return __builtin__.open(path, mode)

    def get_instances_path(self):
        return os.path.normpath(CONF.instances_path)

    def get_instance_path(self, instance_name):
        instance_path = os.path.join(self.get_instances_path(), instance_name)
        if not os.path.exists(instance_path):
            LOG.debug(_('Creating folder %s '), instance_path)
            os.makedirs(instance_path)
        return instance_path

    def get_vhd_path(self, instance_name):
        instance_path = self.get_instance_path(instance_name)
        return os.path.join(instance_path, instance_name + ".vhd")

    def get_base_vhd_path(self, image_name):
        base_dir = os.path.join(self.get_instances_path(), '_base')
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        return os.path.join(base_dir, image_name + ".vhd")

    def make_export_path(self, instance_name):
        export_folder = os.path.join(self.get_instances_path(), "export",
                                     instance_name)
        if os.path.isdir(export_folder):
            LOG.debug(_('Removing existing folder %s '), export_folder)
            shutil.rmtree(export_folder)
        LOG.debug(_('Creating folder %s '), export_folder)
        os.makedirs(export_folder)
        return export_folder

    def vhd_exists(self, path):
        return os.path.exists(path)
