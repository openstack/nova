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

import datetime

from nova.compute import instance_list
from nova import context
from nova import objects
from nova import test


class InstanceListTestCase(test.TestCase):
    NUMBER_OF_CELLS = 3

    def setUp(self):
        super(InstanceListTestCase, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.num_instances = 3
        self.instances = []

        dt = datetime.datetime(1985, 10, 25, 1, 21, 0)
        spread = datetime.timedelta(minutes=10)

        cells = objects.CellMappingList.get_all(self.context)
        # Create three instances in each of the real cells. Leave the
        # first cell empty to make sure we don't break with an empty
        # one.
        for cell in cells[1:]:
            for i in range(0, self.num_instances):
                with context.target_cell(self.context, cell) as cctx:
                    inst = objects.Instance(
                        context=cctx,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id,
                        launched_at=dt,
                        instance_type_id=i,
                        hostname='%s-inst%i' % (cell.name, i))
                    inst.create()
                self.instances.append(inst)
                im = objects.InstanceMapping(context=self.context,
                                             project_id=inst.project_id,
                                             user_id=inst.user_id,
                                             instance_uuid=inst.uuid,
                                             cell_mapping=cell)
                im.create()
                dt += spread

    def test_get_sorted(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        insts = instance_list.get_instances_sorted(self.context, filters,
                                                   limit, marker, columns,
                                                   sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(sorted(uuids), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def test_get_sorted_descending(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['desc']
        insts = instance_list.get_instances_sorted(self.context, filters,
                                                   limit, marker, columns,
                                                   sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(list(reversed(sorted(uuids))), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def test_get_sorted_with_filter(self):
        filters = {'instance_type_id': 1}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        insts = instance_list.get_instances_sorted(self.context, filters,
                                                   limit, marker, columns,
                                                   sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        expected = [inst['uuid'] for inst in self.instances
                    if inst['instance_type_id'] == 1]
        self.assertEqual(list(sorted(expected)), uuids)

    def test_get_sorted_by_defaults(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = None
        sort_dirs = None
        insts = instance_list.get_instances_sorted(self.context, filters,
                                                   limit, marker, columns,
                                                   sort_keys, sort_dirs)
        uuids = set([inst['uuid'] for inst in insts])
        expected = set([inst['uuid'] for inst in self.instances])
        self.assertEqual(expected, uuids)
