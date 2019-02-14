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

# NOTE(cdent): This file is only used by the placement code within
# nova. Other uses of resource classes in nova make use of the
# os-resource-classes library. The placement code within nova
# continues to use this so that that code can remain unchanged.

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
    # Standard resource class for network bandwidth egress measured in
    # kilobits per second.
    NET_BW_EGR_KILOBIT_PER_SEC = 'NET_BW_EGR_KILOBIT_PER_SEC'
    # Standard resource class for network bandwidth ingress measured in
    # kilobits per second.
    NET_BW_IGR_KILOBIT_PER_SEC = 'NET_BW_IGR_KILOBIT_PER_SEC'

    # The ordering here is relevant. If you must add a value, only
    # append.
    STANDARD = (VCPU, MEMORY_MB, DISK_GB, PCI_DEVICE, SRIOV_NET_VF,
                NUMA_SOCKET, NUMA_CORE, NUMA_THREAD, NUMA_MEMORY_MB,
                IPV4_ADDRESS, VGPU, VGPU_DISPLAY_HEAD,
                NET_BW_EGR_KILOBIT_PER_SEC, NET_BW_IGR_KILOBIT_PER_SEC)

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
