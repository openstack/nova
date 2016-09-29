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
Cell scheduler filters
"""

from nova import filters


class BaseCellFilter(filters.BaseFilter):
    """Base class for cell filters."""

    def authorized(self, ctxt):
        """Return whether or not the context is authorized for this filter
        based on policy.
        The policy action is "cells_scheduler_filter:<name>" where <name>
        is the name of the filter class.
        """
        name = 'cells_scheduler_filter:' + self.__class__.__name__
        return ctxt.can(name, fatal=False)

    def _filter_one(self, cell, filter_properties):
        return self.cell_passes(cell, filter_properties)

    def cell_passes(self, cell, filter_properties):
        """Return True if the CellState passes the filter, otherwise False.
        Override this in a subclass.
        """
        raise NotImplementedError()


class CellFilterHandler(filters.BaseFilterHandler):
    def __init__(self):
        super(CellFilterHandler, self).__init__(BaseCellFilter)


def all_filters():
    """Return a list of filter classes found in this directory.

    This method is used as the default for available scheduler filters
    and should return a list of all filter classes available.
    """
    return CellFilterHandler().get_all_classes()
