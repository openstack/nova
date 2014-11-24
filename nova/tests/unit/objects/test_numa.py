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


fake_obj_numa = objects.NUMATopology(
    cells=[
        objects.NUMACell(
            id=0, cpuset=set([1, 2]), memory=512,
            cpu_usage=2, memory_usage=256),
        objects.NUMACell(
            id=1, cpuset=set([3, 4]), memory=512,
            cpu_usage=1, memory_usage=128)])


class _TestNUMA(object):

    def test_convert_wipe(self):
        d1 = fake_obj_numa._to_dict()
        d2 = objects.NUMATopology.obj_from_primitive(d1)._to_dict()

        self.assertEqual(d1, d2)


class TestNUMA(test_objects._LocalTest,
               _TestNUMA):
    pass


class TestNUMARemote(test_objects._RemoteTest,
                     _TestNUMA):
    pass
