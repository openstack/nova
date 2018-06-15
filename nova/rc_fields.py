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
"""Standard Resource Class Fields."""

# NOTE(cdent): This is kept as its own independent file as it is used by
# both the placement and nova sides of the placement interaction. On the
# placement side we don't want to import all the nova fields, nor all the
# nova objects (which are automatically loaded and registered if the
# nova.objects package is imported).

import re

from oslo_versionedobjects import fields


class ResourceClass(fields.StringField):
    """Classes of resources provided to consumers."""

    CUSTOM_NAMESPACE = 'CUSTOM_'
    """All non-standard resource classes must begin with this string."""

    VCPU = 'VCPU'
    MEMORY_MB = 'MEMORY_MB'
    DISK_GB = 'DISK_GB'
    PCI_DEVICE = 'PCI_DEVICE'
    SRIOV_NET_VF = 'SRIOV_NET_VF'
    NUMA_SOCKET = 'NUMA_SOCKET'
    NUMA_CORE = 'NUMA_CORE'
    NUMA_THREAD = 'NUMA_THREAD'
    NUMA_MEMORY_MB = 'NUMA_MEMORY_MB'
    IPV4_ADDRESS = 'IPV4_ADDRESS'
    VGPU = 'VGPU'
    VGPU_DISPLAY_HEAD = 'VGPU_DISPLAY_HEAD'

    # The ordering here is relevant. If you must add a value, only
    # append.
    STANDARD = (VCPU, MEMORY_MB, DISK_GB, PCI_DEVICE, SRIOV_NET_VF,
                NUMA_SOCKET, NUMA_CORE, NUMA_THREAD, NUMA_MEMORY_MB,
                IPV4_ADDRESS, VGPU, VGPU_DISPLAY_HEAD)

    @classmethod
    def normalize_name(cls, rc_name):
        if rc_name is None:
            return None
        # Replace non-alphanumeric characters with underscores
        norm_name = re.sub('[^0-9A-Za-z]+', '_', rc_name)
        # Bug #1762789: Do .upper after replacing non alphanumerics.
        norm_name = norm_name.upper()
        norm_name = cls.CUSTOM_NAMESPACE + norm_name
        return norm_name


class ResourceClassField(fields.AutoTypedField):
    AUTO_TYPE = ResourceClass()
