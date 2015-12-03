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

from oslo_config import cfg
from oslo_log import log as logging

from nova.virt.hyperv import hostutils
from nova.virt.hyperv import hostutilsv2
from nova.virt.hyperv import livemigrationutils
from nova.virt.hyperv import networkutilsv2
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import rdpconsoleutilsv2
from nova.virt.hyperv import vhdutilsv2
from nova.virt.hyperv import vmutilsv2
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2

CONF = cfg.CONF

LOG = logging.getLogger(__name__)
CONF.import_group('hyperv', 'os_win.utilsfactory')

utils = hostutils.HostUtils()


def _get_class(v1_class, v2_class, force_v1_flag=False):
    # V2 classes are supported starting from Hyper-V Server 2012 and
    # Windows Server 2012 (kernel version 6.2)
    if not force_v1_flag and utils.check_min_windows_version(6, 2):
        cls = v2_class
    else:
        cls = v1_class
    LOG.debug("Loading class: %(module_name)s.%(class_name)s",
              {'module_name': cls.__module__, 'class_name': cls.__name__})
    return cls


def get_vmutils(host='.'):
    return vmutilsv2.VMUtilsV2(host)


def get_vhdutils():
    return vhdutilsv2.VHDUtilsV2()


def get_networkutils():
    return networkutilsv2.NetworkUtilsV2()


def get_hostutils():
    return hostutilsv2.HostUtilsV2()


def get_pathutils():
    return pathutils.PathUtils()


def get_volumeutils():
    return _get_class(volumeutils.VolumeUtils, volumeutilsv2.VolumeUtilsV2,
                      CONF.hyperv.force_volumeutils_v1)()


def get_livemigrationutils():
    return livemigrationutils.LiveMigrationUtils()


def get_rdpconsoleutils():
    return rdpconsoleutilsv2.RDPConsoleUtilsV2()
