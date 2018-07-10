# Copyright (c) 2013 Rackspace Hosting
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
Tests For CellStateManager
"""

import datetime
import time

import mock
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_utils import timeutils
import six

from nova.cells import state
from nova.db.sqlalchemy import models
from nova import exception
from nova import objects
from nova import test
from nova import utils

FAKE_COMPUTES = [
    ('host1', 1024, 100, 0, 0),
    ('host2', 1024, 100, -1, -1),
    ('host3', 1024, 100, 1024, 100),
    ('host4', 1024, 100, 300, 30),
]

FAKE_COMPUTES_N_TO_ONE = [
    ('host1', 1024, 100, 0, 0),
    ('host1', 1024, 100, -1, -1),
    ('host2', 1024, 100, 1024, 100),
    ('host2', 1024, 100, 300, 30),
]

FAKE_SERVICES = [
    ('host1', 0),
    ('host2', 0),
    ('host3', 0),
    ('host4', 3600),
]

# NOTE(alaski): It's important to have multiple types that end up having the
# same memory and disk requirements.  So two types need the same first value,
# and two need the second and third values to add up to the same thing.
FAKE_ITYPES = [
    (0, 0, 0),
    (50, 12, 13),
    (50, 2, 4),
    (10, 20, 5),
]


def _create_fake_node(host, total_mem, total_disk, free_mem, free_disk):
    return objects.ComputeNode(host=host,
                               memory_mb=total_mem,
                               local_gb=total_disk,
                               free_ram_mb=free_mem,
                               free_disk_gb=free_disk)


@classmethod
def _fake_service_get_all_by_binary(cls, context, binary):
    def _node(host, total_mem, total_disk, free_mem, free_disk):
        now = timeutils.utcnow()
        return objects.Service(host=host,
                               disabled=False,
                               forced_down=False,
                               last_seen_up=now)

    return [_node(*fake) for fake in FAKE_COMPUTES]


@classmethod
def _fake_service_get_all_by_binary_nodedown(cls, context, binary):
    def _service(host, noupdate_sec):
        now = timeutils.utcnow()
        last_seen = now - datetime.timedelta(seconds=noupdate_sec)
        return objects.Service(host=host,
                               disabled=False,
                               forced_down=False,
                               last_seen_up=last_seen,
                               binary=binary)

    return [_service(*fake) for fake in FAKE_SERVICES]


@classmethod
def _fake_compute_node_get_all(cls, context):
    return [_create_fake_node(*fake) for fake in FAKE_COMPUTES]


@classmethod
def _fake_compute_node_n_to_one_get_all(cls, context):
    return [_create_fake_node(*fake) for fake in FAKE_COMPUTES_N_TO_ONE]


def _fake_cell_get_all(context):
    return []


def _fake_instance_type_all(*args):
    def _type(mem, root, eph):
        return objects.Flavor(root_gb=root,
                              ephemeral_gb=eph,
                              memory_mb=mem)

    return [_type(*fake) for fake in FAKE_ITYPES]


class TestCellsStateManager(test.NoDBTestCase):

    def setUp(self):
        super(TestCellsStateManager, self).setUp()

        self.stub_out('nova.objects.ComputeNodeList.get_all',
                      _fake_compute_node_get_all)
        self.stub_out('nova.objects.ServiceList.get_by_binary',
                      _fake_service_get_all_by_binary)
        self.stub_out('nova.objects.FlavorList.get_all',
                      _fake_instance_type_all)
        self.stub_out('nova.db.api.cell_get_all', _fake_cell_get_all)

    def test_cells_config_not_found(self):
        self.flags(cells_config='no_such_file_exists.conf', group='cells')
        e = self.assertRaises(cfg.ConfigFilesNotFoundError,
                              state.CellStateManager)
        self.assertEqual(['no_such_file_exists.conf'], e.config_files)

    @mock.patch.object(cfg.ConfigOpts, 'find_file')
    @mock.patch.object(utils, 'read_cached_file')
    def test_filemanager_returned(self, mock_read_cached_file, mock_find_file):
        mock_find_file.return_value = "/etc/nova/cells.json"
        mock_read_cached_file.return_value = (False, six.StringIO('{}'))
        self.flags(cells_config='cells.json', group='cells')
        manager = state.CellStateManager()
        self.assertIsInstance(manager,
                              state.CellStateManagerFile)
        self.assertRaises(exception.CellsUpdateUnsupported,
                          manager.cell_create, None, None)
        self.assertRaises(exception.CellsUpdateUnsupported,
                          manager.cell_update, None, None, None)
        self.assertRaises(exception.CellsUpdateUnsupported,
                          manager.cell_delete, None, None)

    def test_dbmanager_returned(self):
        self.assertIsInstance(state.CellStateManager(),
                              state.CellStateManagerDB)

    def test_capacity_no_reserve(self):
        # utilize entire cell
        cap = self._capacity(0.0)

        cell_free_ram = sum(max(0, compute[3]) for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(max(0, compute[4])
                                    for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = cell_free_ram // 50
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 5  # 4 on host 3, 1 on host4
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_full_reserve(self):
        # reserve the entire cell. (utilize zero percent)
        cap = self._capacity(100.0)

        cell_free_ram = sum(max(0, compute[3]) for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(max(0, compute[4])
                                    for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        self.assertEqual(0, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_part_reserve(self):
        # utilize half the cell's free capacity
        cap = self._capacity(50.0)

        cell_free_ram = sum(max(0, compute[3]) for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(max(0, compute[4])
                                    for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = 10  # 10 from host 3
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 2  # 2 on host 3
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def _get_state_manager(self, reserve_percent=0.0):
        self.flags(reserve_percent=reserve_percent, group='cells')
        return state.CellStateManager()

    def _capacity(self, reserve_percent):
        state_manager = self._get_state_manager(reserve_percent)
        my_state = state_manager.get_my_state()
        return my_state.capacities


class TestCellsStateManagerNToOne(TestCellsStateManager):
    def setUp(self):
        super(TestCellsStateManagerNToOne, self).setUp()

        self.stub_out('nova.objects.ComputeNodeList.get_all',
                      _fake_compute_node_n_to_one_get_all)

    def test_capacity_part_reserve(self):
        # utilize half the cell's free capacity
        cap = self._capacity(50.0)

        cell_free_ram = sum(max(0, compute[3])
                            for compute in FAKE_COMPUTES_N_TO_ONE)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = (1024 *
                sum(max(0, compute[4])
                    for compute in FAKE_COMPUTES_N_TO_ONE))
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = 6  # 6 from host 2
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 1  # 1 on host 2
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])


class TestCellsStateManagerNodeDown(test.NoDBTestCase):
    def setUp(self):
        super(TestCellsStateManagerNodeDown, self).setUp()

        self.stub_out('nova.objects.ComputeNodeList.get_all',
                       _fake_compute_node_get_all)
        self.stub_out('nova.objects.ServiceList.get_by_binary',
               _fake_service_get_all_by_binary_nodedown)
        self.stub_out('nova.objects.FlavorList.get_all',
                      _fake_instance_type_all)
        self.stub_out('nova.db.api.cell_get_all', _fake_cell_get_all)

    def test_capacity_no_reserve_nodedown(self):
        cap = self._capacity(0.0)

        cell_free_ram = sum(max(0, compute[3])
                            for compute in FAKE_COMPUTES[:-1])
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        free_disk = sum(max(0, compute[4])
                        for compute in FAKE_COMPUTES[:-1])
        cell_free_disk = 1024 * free_disk
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

    def _get_state_manager(self, reserve_percent=0.0):
        self.flags(reserve_percent=reserve_percent, group='cells')
        return state.CellStateManager()

    def _capacity(self, reserve_percent):
        state_manager = self._get_state_manager(reserve_percent)
        my_state = state_manager.get_my_state()
        return my_state.capacities


class TestCellStateManagerException(test.NoDBTestCase):
    @mock.patch.object(time, 'sleep')
    def test_init_db_error(self, mock_sleep):
        class TestCellStateManagerDB(state.CellStateManagerDB):
            def __init__(self):
                self._cell_data_sync = mock.Mock()
                self._cell_data_sync.side_effect = [db_exc.DBError(), []]
                super(TestCellStateManagerDB, self).__init__()
        test = TestCellStateManagerDB()
        mock_sleep.assert_called_once_with(30)
        self.assertEqual(2, test._cell_data_sync.call_count)


class TestCellsGetCapacity(TestCellsStateManager):
    def setUp(self):
        super(TestCellsGetCapacity, self).setUp()
        self.capacities = {"ram_free": 1234}
        self.state_manager = self._get_state_manager()
        cell = models.Cell(name="cell_name")
        other_cell = models.Cell(name="other_cell_name")
        cell.capacities = self.capacities
        other_cell.capacities = self.capacities
        self.state_manager.child_cells = {"cell_name": cell,
                                          "other_cell_name": other_cell}
        self.state_manager.my_cell_state.capacities = self.capacities

    def test_get_cell_capacity_for_all_cells(self):
        capacities = self.state_manager.get_capacities()
        self.assertEqual({"ram_free": 3702}, capacities)

    def test_get_cell_capacity_for_the_parent_cell(self):
        capacities = self.state_manager.\
                     get_capacities(self.state_manager.my_cell_state.name)
        self.assertEqual({"ram_free": 3702}, capacities)

    def test_get_cell_capacity_for_a_cell(self):
        self.assertEqual(self.capacities,
                self.state_manager.get_capacities(cell_name="cell_name"))

    def test_get_cell_capacity_for_non_existing_cell(self):
        self.assertRaises(exception.CellNotFound,
                          self.state_manager.get_capacities,
                          cell_name="invalid_cell_name")


class FakeCellStateManager(object):
    def __init__(self):
        self.called = []

    def _cell_data_sync(self, force=False):
        self.called.append(('_cell_data_sync', force))


class TestSyncDecorators(test.NoDBTestCase):
    def test_sync_before(self):
        manager = FakeCellStateManager()

        def test(inst, *args, **kwargs):
            self.assertEqual(manager, inst)
            self.assertEqual((1, 2, 3), args)
            self.assertEqual(dict(a=4, b=5, c=6), kwargs)
            return 'result'
        wrapper = state.sync_before(test)

        result = wrapper(manager, 1, 2, 3, a=4, b=5, c=6)

        self.assertEqual('result', result)
        self.assertEqual([('_cell_data_sync', False)], manager.called)

    def test_sync_after(self):
        manager = FakeCellStateManager()

        def test(inst, *args, **kwargs):
            self.assertEqual(manager, inst)
            self.assertEqual((1, 2, 3), args)
            self.assertEqual(dict(a=4, b=5, c=6), kwargs)
            return 'result'
        wrapper = state.sync_after(test)

        result = wrapper(manager, 1, 2, 3, a=4, b=5, c=6)

        self.assertEqual('result', result)
        self.assertEqual([('_cell_data_sync', True)], manager.called)
