# Copyright (c) 2012 Rackspace Hosting
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
Global cells config options
"""
import nova.conf

CONF = nova.conf.CONF


def get_cell_type():
    """Return the cell type, 'api', 'compute', or None (if cells is disabled).
    """
    if not CONF.cells.enable:
        return
    return CONF.cells.cell_type
