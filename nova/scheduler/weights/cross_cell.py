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
Cross-cell move weigher. Weighs hosts based on which cell they are in. "Local"
cells are preferred when moving an instance. In other words, select a host
from the source cell all other things being equal.
"""

from nova import conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = conf.CONF


class CrossCellWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """How weighted this weigher should be."""
        return utils.get_weight_multiplier(
            host_state, 'cross_cell_move_weight_multiplier',
            CONF.filter_scheduler.cross_cell_move_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win. Hosts within the "preferred" cell are weighed
        higher than hosts in other cells.

        :param host_state: nova.scheduler.host_manager.HostState object
            representing a ComputeNode in a cell
        :param weight_properties: nova.objects.RequestSpec - this is inspected
            to see if there is a preferred cell via the requested_destination
            field and if so, is the request spec allowing cross-cell move
        :returns: 1 if cross-cell move and host_state is within the preferred
            cell, -1 if cross-cell move and host_state is *not* within the
            preferred cell, 0 for all other cases
        """
        # RequestSpec.requested_destination.cell should only be set for
        # move operations. The allow_cross_cell_move value will only be True if
        # policy allows.
        if ('requested_destination' in weight_properties and
                weight_properties.requested_destination and
                'cell' in weight_properties.requested_destination and
                weight_properties.requested_destination.cell and
                weight_properties.requested_destination.allow_cross_cell_move):
            # Determine if the given host is in the "preferred" cell from
            # the request spec. If it is, weigh it higher.
            if (host_state.cell_uuid ==
                    weight_properties.requested_destination.cell.uuid):
                return 1
            # The host is in another cell, so weigh it lower.
            return -1
        # We don't know or don't care what cell we're going to be in, so noop.
        return 0
