# Copyright (c) 2012-2013 Rackspace Hosting
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
Weigh cells by memory needed in a way that spreads instances.
"""

from nova.cells import weights
import nova.conf


CONF = nova.conf.CONF


class RamByInstanceTypeWeigher(weights.BaseCellWeigher):
    """Weigh cells by instance_type requested."""

    def weight_multiplier(self):
        return CONF.cells.ram_weight_multiplier

    def _weigh_object(self, cell, weight_properties):
        """Use the 'ram_free' for a particular instance_type advertised from a
        child cell's capacity to compute a weight.  We want to direct the
        build to a cell with a higher capacity.  Since higher weights win,
        we just return the number of units available for the instance_type.
        """
        request_spec = weight_properties['request_spec']
        instance_type = request_spec['instance_type']
        memory_needed = instance_type['memory_mb']

        ram_free = cell.capacities.get('ram_free', {})
        units_by_mb = ram_free.get('units_by_mb', {})

        return units_by_mb.get(str(memory_needed), 0)
