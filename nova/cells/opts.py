# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging


cells_opts = [
    cfg.BoolOpt('enable',
                default=False,
                help='Enable cell functionality'),
    cfg.StrOpt('topic',
                default='cells',
                help='the topic cells nodes listen on'),
    cfg.StrOpt('manager',
               default='nova.cells.manager.CellsManager',
               help='Manager for cells'),
    cfg.StrOpt('name',
                default='nova',
                help='name of this cell'),
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


# NOTE(comstud): Remove 'compute_api_class' after Havana and set a reasonable
# default for 'cell_type'.
_compute_opts = [
    cfg.StrOpt('compute_api_class',
               default='nova.compute.api.API',
               help='The full class name of the '
                    'compute API class to use (deprecated)'),
]

CONF.register_opts(_compute_opts)
LOG = logging.getLogger(__name__)


def get_cell_type():
    """Return the cell type, 'api', 'compute', or None (if cells is disabled).

    This call really exists just to support the deprecated compute_api_class
    config option.  Otherwise, one could just access CONF.cells.enable and
    CONF.cells.cell_type directly.
    """
    if not CONF.cells.enable:
        return
    cell_type = CONF.cells.cell_type
    if cell_type:
        if cell_type == 'api' or cell_type == 'compute':
            return cell_type
        msg = _("cell_type must be configured as 'api' or 'compute'")
        raise exception.InvalidInput(reason=msg)
    LOG.deprecated(_("The compute_api_class is now deprecated and "
                     "will be removed in next release. Please set the"
                     " cell_type option to 'api' or 'compute'"))
    if CONF.compute_api_class == 'nova.compute.cells_api.ComputeCellsAPI':
        return 'api'
    return 'compute'
