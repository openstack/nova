# Copyright (c) 2014 VMware, Inc.
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
Shared constants across the VMware driver
"""

from nova.network import model as network_model

DISK_FORMAT_ISO = 'iso'
DISK_FORMAT_VMDK = 'vmdk'
DISK_FORMATS_ALL = [DISK_FORMAT_ISO, DISK_FORMAT_VMDK]

DISK_TYPE_SPARSE = 'sparse'
DISK_TYPE_PREALLOCATED = 'preallocated'

DEFAULT_VIF_MODEL = network_model.VIF_MODEL_E1000
DEFAULT_OS_TYPE = "otherGuest"
DEFAULT_ADAPTER_TYPE = "lsiLogic"
DEFAULT_DISK_TYPE = DISK_TYPE_PREALLOCATED
DEFAULT_DISK_FORMAT = DISK_FORMAT_VMDK

ADAPTER_TYPE_BUSLOGIC = "busLogic"
ADAPTER_TYPE_IDE = "ide"
ADAPTER_TYPE_LSILOGICSAS = "lsiLogicsas"
ADAPTER_TYPE_PARAVIRTUAL = "paraVirtual"

SUPPORTED_FLAT_VARIANTS = ["thin", "preallocated", "thick", "eagerZeroedThick"]
