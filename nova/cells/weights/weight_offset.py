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
Weigh cells by their weight_offset in the DB.  Cells with higher
weight_offsets in the DB will be preferred.
"""

from nova.cells import weights
import nova.conf


CONF = nova.conf.CONF


class WeightOffsetWeigher(weights.BaseCellWeigher):
    """Weight cell by weight_offset db field.
    Originally designed so you can set a default cell by putting
    its weight_offset to 999999999999999 (highest weight wins)
    """

    def weight_multiplier(self):
        return CONF.cells.offset_weight_multiplier

    def _weigh_object(self, cell, weight_properties):
        """Returns whatever was in the DB for weight_offset."""
        return cell.db_info.get('weight_offset', 0)
