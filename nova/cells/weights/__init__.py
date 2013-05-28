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
Cell Scheduler weights
"""

from nova import weights


class WeightedCell(weights.WeighedObject):
    def __repr__(self):
        return "WeightedCell [cell: %s, weight: %s]" % (
                self.obj.name, self.weight)


class BaseCellWeigher(weights.BaseWeigher):
    """Base class for cell weights."""
    pass


class CellWeightHandler(weights.BaseWeightHandler):
    object_class = WeightedCell

    def __init__(self):
        super(CellWeightHandler, self).__init__(BaseCellWeigher)


def all_weighers():
    """Return a list of weight plugin classes found in this directory."""
    return CellWeightHandler().get_all_classes()
