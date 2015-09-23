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
import mock
import random

from nova.cells import utils as cells_utils
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_instance


class CellsUtilsTestCase(test.NoDBTestCase):
    """Test case for Cells utility methods."""
    def test_get_instances_to_sync(self):
        fake_context = 'fake_context'

        call_info = {'get_all': 0, 'shuffle': 0}

        def random_shuffle(_list):
            call_info['shuffle'] += 1

        @staticmethod
        def instance_get_all_by_filters(context, filters,
                sort_key, sort_dir, limit, marker):
            # Pretend we return a full list the first time otherwise we loop
            # infinitely
            if marker is not None:
                return []
            self.assertEqual(fake_context, context)
            self.assertEqual('deleted', sort_key)
            self.assertEqual('asc', sort_dir)
            call_info['got_filters'] = filters
            call_info['get_all'] += 1
            instances = [fake_instance.fake_db_instance() for i in range(3)]
            return instances

        self.stubs.Set(objects.InstanceList, 'get_by_filters',
                instance_get_all_by_filters)
        self.stubs.Set(random, 'shuffle', random_shuffle)

        instances = cells_utils.get_instances_to_sync(fake_context)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(3, len([x for x in instances]))
        self.assertEqual(1, call_info['get_all'])
        self.assertEqual({}, call_info['got_filters'])
        self.assertEqual(0, call_info['shuffle'])

        instances = cells_utils.get_instances_to_sync(fake_context,
                                                      shuffle=True)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(3, len([x for x in instances]))
        self.assertEqual(2, call_info['get_all'])
        self.assertEqual({}, call_info['got_filters'])
        self.assertEqual(1, call_info['shuffle'])

        instances = cells_utils.get_instances_to_sync(fake_context,
                updated_since='fake-updated-since')
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(3, len([x for x in instances]))
        self.assertEqual(3, call_info['get_all'])
        self.assertEqual({'changes-since': 'fake-updated-since'},
                         call_info['got_filters'])
        self.assertEqual(1, call_info['shuffle'])

        instances = cells_utils.get_instances_to_sync(fake_context,
                project_id='fake-project',
                updated_since='fake-updated-since', shuffle=True)
        self.assertTrue(inspect.isgenerator(instances))
        self.assertEqual(3, len([x for x in instances]))
        self.assertEqual(4, call_info['get_all'])
        self.assertEqual({'changes-since': 'fake-updated-since',
                 'project_id': 'fake-project'}, call_info['got_filters'])
        self.assertEqual(2, call_info['shuffle'])

    @mock.patch.object(objects.InstanceList, 'get_by_filters')
    @mock.patch.object(random, 'shuffle')
    def _test_get_instances_pagination(self, mock_shuffle,
            mock_get_by_filters, shuffle=False, updated_since=None,
            project_id=None):
        fake_context = 'fake_context'

        instances0 = objects.instance._make_instance_list(fake_context,
                objects.InstanceList(),
                [fake_instance.fake_db_instance() for i in range(3)],
                expected_attrs=None)
        marker0 = instances0[-1]['uuid']
        instances1 = objects.instance._make_instance_list(fake_context,
                objects.InstanceList(),
                [fake_instance.fake_db_instance() for i in range(3)],
                expected_attrs=None)
        marker1 = instances1[-1]['uuid']

        mock_get_by_filters.side_effect = [instances0, instances1, []]

        instances = cells_utils.get_instances_to_sync(fake_context,
                updated_since, project_id, shuffle=shuffle)
        self.assertEqual(len([x for x in instances]), 6)

        filters = {}
        if updated_since is not None:
            filters['changes-since'] = updated_since
        if project_id is not None:
            filters['project_id'] = project_id
        limit = 100
        expected_calls = [mock.call(fake_context, filters, sort_key='deleted',
                              sort_dir='asc', limit=limit, marker=None),
                          mock.call(fake_context, filters, sort_key='deleted',
                              sort_dir='asc', limit=limit, marker=marker0),
                          mock.call(fake_context, filters, sort_key='deleted',
                              sort_dir='asc', limit=limit, marker=marker1)]
        mock_get_by_filters.assert_has_calls(expected_calls)
        self.assertEqual(3, mock_get_by_filters.call_count)

    def test_get_instances_to_sync_limit(self):
        self._test_get_instances_pagination()

    def test_get_instances_to_sync_shuffle(self):
        self._test_get_instances_pagination(shuffle=True)

    def test_get_instances_to_sync_updated_since(self):
        self._test_get_instances_pagination(updated_since='fake-updated-since')

    def test_get_instances_to_sync_multiple_params(self):
        self._test_get_instances_pagination(project_id='fake-project',
                updated_since='fake-updated-since', shuffle=True)

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

    def test_add_cell_to_compute_node(self):
        fake_compute = objects.ComputeNode(id=1, host='fake')
        cell_path = 'fake_path'

        proxy = cells_utils.add_cell_to_compute_node(fake_compute, cell_path)

        self.assertIsInstance(proxy, cells_utils.ComputeNodeProxy)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 1), proxy.id)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 'fake'),
                         proxy.host)

    @mock.patch.object(objects.Service, 'obj_load_attr')
    def test_add_cell_to_service_no_compute_node(self, mock_get_by_id):
        fake_service = objects.Service(id=1, host='fake')
        mock_get_by_id.side_effect = exception.ServiceNotFound(service_id=1)
        cell_path = 'fake_path'

        proxy = cells_utils.add_cell_to_service(fake_service, cell_path)

        self.assertIsInstance(proxy, cells_utils.ServiceProxy)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 1), proxy.id)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 'fake'),
                         proxy.host)
        self.assertRaises(AttributeError,
                          getattr, proxy, 'compute_node')

    def test_add_cell_to_service_with_compute_node(self):
        fake_service = objects.Service(id=1, host='fake')
        fake_service.compute_node = objects.ComputeNode(id=1, host='fake')
        cell_path = 'fake_path'

        proxy = cells_utils.add_cell_to_service(fake_service, cell_path)

        self.assertIsInstance(proxy, cells_utils.ServiceProxy)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 1), proxy.id)
        self.assertEqual(cells_utils.cell_with_item(cell_path, 'fake'),
                         proxy.host)
        self.assertRaises(AttributeError,
                          getattr, proxy, 'compute_node')

    def test_proxy_object_serializer_to_primitive(self):
        obj = objects.ComputeNode(id=1, host='fake')
        obj_proxy = cells_utils.ComputeNodeProxy(obj, 'fake_path')
        serializer = cells_utils.ProxyObjectSerializer()

        primitive = serializer.serialize_entity('ctx', obj_proxy)
        self.assertIsInstance(primitive, dict)
        class_name = primitive.pop('cell_proxy.class_name')
        cell_path = primitive.pop('cell_proxy.cell_path')
        self.assertEqual('ComputeNodeProxy', class_name)
        self.assertEqual('fake_path', cell_path)
        self.assertEqual(obj.obj_to_primitive(), primitive)

    def test_proxy_object_serializer_from_primitive(self):
        obj = objects.ComputeNode(id=1, host='fake')
        serializer = cells_utils.ProxyObjectSerializer()

        # Recreating the primitive by hand to isolate the test for only
        # the deserializing method
        primitive = obj.obj_to_primitive()
        primitive['cell_proxy.class_name'] = 'ComputeNodeProxy'
        primitive['cell_proxy.cell_path'] = 'fake_path'

        result = serializer.deserialize_entity('ctx', primitive)
        self.assertIsInstance(result, cells_utils.ComputeNodeProxy)
        self.assertEqual(obj.obj_to_primitive(),
                         result._obj.obj_to_primitive())
        self.assertEqual('fake_path', result._cell_path)
