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
from nova.tests.unit.objects import test_objects


_top_dict = {
    'sockets': 2,
    'cores': 4,
    'threads': 8
}


class _TestVirtCPUTopologyObject(object):

    def test_object_from_dict(self):
        top_obj = objects.VirtCPUTopology.from_dict(_top_dict)
        self.compare_obj(top_obj, _top_dict)

    def test_object_to_dict(self):
        top_obj = objects.VirtCPUTopology()
        top_obj.sockets = 2
        top_obj.cores = 4
        top_obj.threads = 8
        spec = top_obj.to_dict()
        self.assertEqual(_top_dict, spec)


class TestVirtCPUTopologyObject(test_objects._LocalTest,
                        _TestVirtCPUTopologyObject):
    pass


class TestRemoteVirtCPUTopologyObject(test_objects._RemoteTest,
                             _TestVirtCPUTopologyObject):
    pass
