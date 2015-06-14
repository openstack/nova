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

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
from nova import objects
from nova.tests.unit.objects import test_objects


spec_dict = {
    'arch': arch.I686,
    'hv_type': hv_type.KVM,
    'vm_mode': vm_mode.HVM
}

spec_list = [
    arch.I686,
    hv_type.KVM,
    vm_mode.HVM
]


class _TestHVSpecObject(object):

    def test_hv_spec_from_list(self):
        spec_obj = objects.HVSpec.from_list(spec_list)
        self.compare_obj(spec_obj, spec_dict)

    def test_hv_spec_to_list(self):
        spec_obj = objects.HVSpec()
        spec_obj.arch = arch.I686
        spec_obj.hv_type = hv_type.KVM
        spec_obj.vm_mode = vm_mode.HVM
        spec = spec_obj.to_list()
        self.assertEqual(spec_list, spec)


class TestHVSpecObject(test_objects._LocalTest,
                        _TestHVSpecObject):
    pass


class TestRemoteHVSpecObject(test_objects._RemoteTest,
                             _TestHVSpecObject):
    pass
