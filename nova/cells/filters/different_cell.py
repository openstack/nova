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
Different cell filter.

A scheduler hint of 'different_cell' with a value of a full cell name may be
specified to route a build away from a particular cell.
"""

import six

from nova.cells import filters
from nova.cells import utils as cells_utils


class DifferentCellFilter(filters.BaseCellFilter):
    """Different cell filter.  Works by specifying a scheduler hint of
    'different_cell'. The value should be the full cell path.
    """
    def filter_all(self, cells, filter_properties):
        """Override filter_all() which operates on the full list
        of cells...
        """
        scheduler_hints = filter_properties.get('scheduler_hints')
        if not scheduler_hints:
            return cells

        cell_routes = scheduler_hints.get('different_cell')
        if not cell_routes:
            return cells
        if isinstance(cell_routes, six.string_types):
            cell_routes = [cell_routes]

        if not self.authorized(filter_properties['context']):
            # No filtering, if not authorized.
            return cells

        routing_path = filter_properties['routing_path']
        filtered_cells = []
        for cell in cells:
            if not self._cell_state_matches(cell, routing_path, cell_routes):
                filtered_cells.append(cell)

        return filtered_cells

    def _cell_state_matches(self, cell_state, routing_path, cell_routes):
        cell_route = routing_path
        if not cell_state.is_me:
            cell_route += cells_utils.PATH_CELL_SEP + cell_state.name
        if cell_route in cell_routes:
            return True
        return False
