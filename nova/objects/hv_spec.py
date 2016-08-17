# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

from oslo_utils import versionutils

from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class HVSpec(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added 'vz' hypervisor
    # Version 1.2: Added 'lxd' hypervisor
    VERSION = '1.2'

    fields = {
        'arch': fields.ArchitectureField(),
        'hv_type': fields.HVTypeField(),
        'vm_mode': fields.VMModeField(),
        }

    # NOTE(pmurray): for backward compatibility, the supported instance
    # data is stored in the database as a list.
    @classmethod
    def from_list(cls, data):
        return cls(arch=data[0],
                   hv_type=data[1],
                   vm_mode=data[2])

    def to_list(self):
        return [self.arch, self.hv_type, self.vm_mode]

    def obj_make_compatible(self, primitive, target_version):
        super(HVSpec, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if (target_version < (1, 1) and 'hv_type' in primitive and
                fields.HVType.VIRTUOZZO == primitive['hv_type']):
            primitive['hv_type'] = fields.HVType.PARALLELS
