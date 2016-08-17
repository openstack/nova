# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

from nova import objects
from nova.objects import fields as obj_fields
from nova.tests.unit.objects import test_objects


spec_dict = {
    'arch': obj_fields.Architecture.I686,
    'hv_type': obj_fields.HVType.KVM,
    'vm_mode': obj_fields.VMMode.HVM
}

spec_list = [
    obj_fields.Architecture.I686,
    obj_fields.HVType.KVM,
    obj_fields.VMMode.HVM
]

spec_dict_vz = {
    'arch': obj_fields.Architecture.I686,
    'hv_type': obj_fields.HVType.VIRTUOZZO,
    'vm_mode': obj_fields.VMMode.HVM
}

spec_dict_parallels = {
    'arch': obj_fields.Architecture.I686,
    'hv_type': obj_fields.HVType.PARALLELS,
    'vm_mode': obj_fields.VMMode.HVM
}


class _TestHVSpecObject(object):

    def test_hv_spec_from_list(self):
        spec_obj = objects.HVSpec.from_list(spec_list)
        self.compare_obj(spec_obj, spec_dict)

    def test_hv_spec_to_list(self):
        spec_obj = objects.HVSpec()
        spec_obj.arch = obj_fields.Architecture.I686
        spec_obj.hv_type = obj_fields.HVType.KVM
        spec_obj.vm_mode = obj_fields.VMMode.HVM
        spec = spec_obj.to_list()
        self.assertEqual(spec_list, spec)

    def test_hv_spec_obj_make_compatible(self):
        spec_dict_vz_copy = spec_dict_vz.copy()

        # check 1.1->1.0 compatibility
        objects.HVSpec().obj_make_compatible(spec_dict_vz_copy, '1.0')
        self.assertEqual(spec_dict_parallels, spec_dict_vz_copy)

        # check that nothing changed
        objects.HVSpec().obj_make_compatible(spec_dict_vz_copy, '1.1')
        self.assertEqual(spec_dict_parallels, spec_dict_vz_copy)


class TestHVSpecObject(test_objects._LocalTest,
                        _TestHVSpecObject):
    pass


class TestRemoteHVSpecObject(test_objects._RemoteTest,
                             _TestHVSpecObject):
    pass
