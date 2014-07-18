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

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import livemigrationutils
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import networkutilsv2
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import rdpconsoleutils
from nova.virt.hyperv import rdpconsoleutilsv2
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vhdutilsv2
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import vmutilsv2
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2

hyper_opts = [
    cfg.BoolOpt('force_hyperv_utils_v1',
                default=False,
                help='Force V1 WMI utility classes'),
    cfg.BoolOpt('force_volumeutils_v1',
                default=False,
                help='Force V1 volume utility class'),
]

CONF = cfg.CONF
CONF.register_opts(hyper_opts, 'hyperv')

LOG = logging.getLogger(__name__)


def _get_class(v1_class, v2_class, force_v1_flag):
    # V2 classes are supported starting from Hyper-V Server 2012 and
    # Windows Server 2012 (kernel version 6.2)
    if not force_v1_flag and get_hostutils().check_min_windows_version(6, 2):
        cls = v2_class
    else:
        cls = v1_class
    LOG.debug("Loading class: %(module_name)s.%(class_name)s",
              {'module_name': cls.__module__, 'class_name': cls.__name__})
    return cls


def _get_virt_utils_class(v1_class, v2_class):
    # The "root/virtualization" WMI namespace is no longer supported on
    # Windows Server / Hyper-V Server 2012 R2 / Windows 8.1
    # (kernel version 6.3) or above.
    if (CONF.hyperv.force_hyperv_utils_v1 and
            get_hostutils().check_min_windows_version(6, 3)):
        raise vmutils.HyperVException(
            _('The "force_hyperv_utils_v1" option cannot be set to "True" '
              'on Windows Server / Hyper-V Server 2012 R2 or above as the WMI '
              '"root/virtualization" namespace is no longer supported.'))
    return _get_class(v1_class, v2_class, CONF.hyperv.force_hyperv_utils_v1)


def get_vmutils(host='.'):
    return _get_virt_utils_class(vmutils.VMUtils, vmutilsv2.VMUtilsV2)(host)


def get_vhdutils():
    return _get_virt_utils_class(vhdutils.VHDUtils, vhdutilsv2.VHDUtilsV2)()


def get_networkutils():
    return _get_virt_utils_class(networkutils.NetworkUtils,
                           networkutilsv2.NetworkUtilsV2)()


def get_hostutils():
    return hostutils.HostUtils()


def get_pathutils():
    return pathutils.PathUtils()


def get_volumeutils():
    return _get_class(volumeutils.VolumeUtils, volumeutilsv2.VolumeUtilsV2,
                      CONF.hyperv.force_volumeutils_v1)()


def get_livemigrationutils():
    return livemigrationutils.LiveMigrationUtils()


def get_rdpconsoleutils():
    return _get_virt_utils_class(rdpconsoleutils.RDPConsoleUtils,
                      rdpconsoleutilsv2.RDPConsoleUtilsV2)()
