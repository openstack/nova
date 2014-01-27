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

from oslo.config import cfg


cells_opts = [
    cfg.BoolOpt('enable',
                default=False,
                help='Enable cell functionality'),
    cfg.StrOpt('topic',
                default='cells',
                help='The topic cells nodes listen on'),
    cfg.StrOpt('manager',
               default='nova.cells.manager.CellsManager',
               help='Manager for cells'),
    cfg.StrOpt('name',
                default='nova',
                help='Name of this cell'),
    cfg.ListOpt('capabilities',
                default=['hypervisor=xenserver;kvm', 'os=linux;windows'],
                help='Key/Multi-value list with the capabilities of the cell'),
    cfg.IntOpt('call_timeout',
                default=60,
                help='Seconds to wait for response from a call to a cell.'),
    cfg.FloatOpt('reserve_percent',
                default=10.0,
                help='Percentage of cell capacity to hold in reserve. '
                     'Affects both memory and disk utilization'),
    cfg.StrOpt('cell_type',
               default='compute',
               help='Type of cell: api or compute'),
    cfg.IntOpt("mute_child_interval",
               default=300,
               help='Number of seconds after which a lack of capability and '
                     'capacity updates signals the child cell is to be '
                     'treated as a mute.'),
    cfg.IntOpt('bandwidth_update_interval',
                default=600,
                help='Seconds between bandwidth updates for cells.'),
]

CONF = cfg.CONF
CONF.register_opts(cells_opts, group='cells')


def get_cell_type():
    """Return the cell type, 'api', 'compute', or None (if cells is disabled).
    """
    if not CONF.cells.enable:
        return
    return CONF.cells.cell_type
