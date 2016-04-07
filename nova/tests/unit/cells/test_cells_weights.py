# Copyright (c) 2012 OpenStack Foundation
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
Unit Tests for testing the cells weight algorithms.

Cells with higher weights should be given priority for new builds.
"""

import datetime

from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils

from nova.cells import state
from nova.cells import weights
from nova import test


class FakeCellState(state.CellState):
    def __init__(self, cell_name):
        super(FakeCellState, self).__init__(cell_name)
        self.capacities['ram_free'] = {'total_mb': 0,
                                       'units_by_mb': {}}
        self.db_info = {}

    def _update_ram_free(self, *args):
        ram_free = self.capacities['ram_free']
        for ram_size, units in args:
            ram_free['total_mb'] += units * ram_size
            ram_free['units_by_mb'][str(ram_size)] = units


def _get_fake_cells():

    cell1 = FakeCellState('cell1')
    cell1._update_ram_free((512, 1), (1024, 4), (2048, 3))
    cell1.db_info['weight_offset'] = -200.0
    cell2 = FakeCellState('cell2')
    cell2._update_ram_free((512, 2), (1024, 3), (2048, 4))
    cell2.db_info['weight_offset'] = -200.1
    cell3 = FakeCellState('cell3')
    cell3._update_ram_free((512, 3), (1024, 2), (2048, 1))
    cell3.db_info['weight_offset'] = 400.0
    cell4 = FakeCellState('cell4')
    cell4._update_ram_free((512, 4), (1024, 1), (2048, 2))
    cell4.db_info['weight_offset'] = 300.0

    return [cell1, cell2, cell3, cell4]


class CellsWeightsTestCase(test.NoDBTestCase):
    """Makes sure the proper weighers are in the directory."""

    def test_all_weighers(self):
        weighers = weights.all_weighers()
        # Check at least a couple that we expect are there
        self.assertGreaterEqual(len(weighers), 2)
        class_names = [cls.__name__ for cls in weighers]
        self.assertIn('WeightOffsetWeigher', class_names)
        self.assertIn('RamByInstanceTypeWeigher', class_names)


class _WeigherTestClass(test.NoDBTestCase):
    """Base class for testing individual weigher plugins."""
    weigher_cls_name = None

    def setUp(self):
        super(_WeigherTestClass, self).setUp()
        self.weight_handler = weights.CellWeightHandler()
        weigher_classes = self.weight_handler.get_matching_classes(
                [self.weigher_cls_name])
        self.weighers = [cls() for cls in weigher_classes]

    def _get_weighed_cells(self, cells, weight_properties):
        return self.weight_handler.get_weighed_objects(self.weighers,
                cells, weight_properties)


class RAMByInstanceTypeWeigherTestClass(_WeigherTestClass):

    weigher_cls_name = ('nova.cells.weights.ram_by_instance_type.'
                        'RamByInstanceTypeWeigher')

    def test_default_spreading(self):
        """Test that cells with more ram available return a higher weight."""
        cells = _get_fake_cells()
        # Simulate building a new 512MB instance.
        instance_type = {'memory_mb': 512}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[3], cells[2], cells[1], cells[0]]
        self.assertEqual(expected_cells, resulting_cells)

        # Simulate building a new 1024MB instance.
        instance_type = {'memory_mb': 1024}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[0], cells[1], cells[2], cells[3]]
        self.assertEqual(expected_cells, resulting_cells)

        # Simulate building a new 2048MB instance.
        instance_type = {'memory_mb': 2048}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[1], cells[0], cells[3], cells[2]]
        self.assertEqual(expected_cells, resulting_cells)

    def test_negative_multiplier(self):
        """Test that cells with less ram available return a higher weight."""
        self.flags(ram_weight_multiplier=-1.0, group='cells')
        cells = _get_fake_cells()
        # Simulate building a new 512MB instance.
        instance_type = {'memory_mb': 512}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[0], cells[1], cells[2], cells[3]]
        self.assertEqual(expected_cells, resulting_cells)

        # Simulate building a new 1024MB instance.
        instance_type = {'memory_mb': 1024}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[3], cells[2], cells[1], cells[0]]
        self.assertEqual(expected_cells, resulting_cells)

        # Simulate building a new 2048MB instance.
        instance_type = {'memory_mb': 2048}
        weight_properties = {'request_spec': {'instance_type': instance_type}}
        weighed_cells = self._get_weighed_cells(cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        expected_cells = [cells[2], cells[3], cells[0], cells[1]]
        self.assertEqual(expected_cells, resulting_cells)


class WeightOffsetWeigherTestClass(_WeigherTestClass):
    """Test the RAMWeigher class."""
    weigher_cls_name = 'nova.cells.weights.weight_offset.WeightOffsetWeigher'

    def test_weight_offset(self):
        """Test that cells with higher weight_offsets return higher
        weights.
        """
        cells = _get_fake_cells()
        weighed_cells = self._get_weighed_cells(cells, {})
        self.assertEqual(4, len(weighed_cells))
        expected_cells = [cells[2], cells[3], cells[0], cells[1]]
        resulting_cells = [weighed_cell.obj for weighed_cell in weighed_cells]
        self.assertEqual(expected_cells, resulting_cells)


class MuteWeigherTestClass(_WeigherTestClass):
    weigher_cls_name = 'nova.cells.weights.mute_child.MuteChildWeigher'

    def setUp(self):
        super(MuteWeigherTestClass, self).setUp()
        self.flags(mute_weight_multiplier=-10.0, mute_child_interval=100,
                   group='cells')

        self.now = timeutils.utcnow()
        self.useFixture(utils_fixture.TimeFixture(self.now))

        self.cells = _get_fake_cells()
        for cell in self.cells:
            cell.last_seen = self.now

    def test_non_mute(self):
        weight_properties = {}
        weighed_cells = self._get_weighed_cells(self.cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))

        for weighed_cell in weighed_cells:
            self.assertEqual(0, weighed_cell.weight)

    def test_mutes(self):
        # make 2 of them mute:
        self.cells[0].last_seen = (self.cells[0].last_seen -
                                   datetime.timedelta(seconds=200))
        self.cells[1].last_seen = (self.cells[1].last_seen -
                                   datetime.timedelta(seconds=200))

        weight_properties = {}
        weighed_cells = self._get_weighed_cells(self.cells, weight_properties)
        self.assertEqual(4, len(weighed_cells))

        for i in range(2):
            weighed_cell = weighed_cells.pop(0)
            self.assertEqual(0, weighed_cell.weight)
            self.assertIn(weighed_cell.obj.name, ['cell3', 'cell4'])

        for i in range(2):
            weighed_cell = weighed_cells.pop(0)
            self.assertEqual(-10.0, weighed_cell.weight)
            self.assertIn(weighed_cell.obj.name, ['cell1', 'cell2'])
