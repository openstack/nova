# Copyright (c) 2012 Rackspace Hosting
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
"""
Tests For Cells Utility methods
"""
import inspect
import random

from nova.cells import utils as cells_utils
from nova import db
from nova import test


class CellsUtilsTestCase(test.NoDBTestCase):
    """Test case for Cells utility methods."""
    def test_get_instances_to_sync(self):
        fake_context = 'fake_context'

        call_info = {'get_all': 0, 'shuffle': 0}

        def random_shuffle(_list):
            call_info['shuffle'] += 1

        def instance_get_all_by_filters(context, filters,
                sort_key, sort_order):
            self.assertEqual(context, fake_context)
            self.assertEqual(sort_key, 'deleted')
            self.assertEqual(sort_order, 'asc')
            call_info['got_filters'] = filters
            call_info['get_all'] += 1
            return ['fake_instance1', 'fake_instance2', 'fake_instance3']

        self.stubs.Set(db, 'instance_get_all_by_filters',
                instance_get_all_by_filters)
        self.stubs.Set(random, 'shuffle', random_shuffle)

        instances = cells_utils.get_instances_to_sync(fake_context)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(len([x for x in instances]), 3)
        self.assertEqual(call_info['get_all'], 1)
        self.assertEqual(call_info['got_filters'], {})
        self.assertEqual(call_info['shuffle'], 0)

        instances = cells_utils.get_instances_to_sync(fake_context,
                                                      shuffle=True)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(len([x for x in instances]), 3)
        self.assertEqual(call_info['get_all'], 2)
        self.assertEqual(call_info['got_filters'], {})
        self.assertEqual(call_info['shuffle'], 1)

        instances = cells_utils.get_instances_to_sync(fake_context,
                updated_since='fake-updated-since')
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(len([x for x in instances]), 3)
        self.assertEqual(call_info['get_all'], 3)
        self.assertEqual(call_info['got_filters'],
                {'changes-since': 'fake-updated-since'})
        self.assertEqual(call_info['shuffle'], 1)

        instances = cells_utils.get_instances_to_sync(fake_context,
                project_id='fake-project',
                updated_since='fake-updated-since', shuffle=True)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(len([x for x in instances]), 3)
        self.assertEqual(call_info['get_all'], 4)
        self.assertEqual(call_info['got_filters'],
                {'changes-since': 'fake-updated-since',
                 'project_id': 'fake-project'})
        self.assertEqual(call_info['shuffle'], 2)

    def test_split_cell_and_item(self):
        path = 'australia', 'queensland', 'gold_coast'
        cell = cells_utils.PATH_CELL_SEP.join(path)
        item = 'host_5'
        together = cells_utils.cell_with_item(cell, item)
        self.assertEqual(cells_utils._CELL_ITEM_SEP.join([cell, item]),
                         together)

        # Test normal usage
        result_cell, result_item = cells_utils.split_cell_and_item(together)
        self.assertEqual(cell, result_cell)
        self.assertEqual(item, result_item)

        # Test with no cell
        cell = None
        together = cells_utils.cell_with_item(cell, item)
        self.assertEqual(item, together)
        result_cell, result_item = cells_utils.split_cell_and_item(together)
        self.assertEqual(cell, result_cell)
        self.assertEqual(item, result_item)
