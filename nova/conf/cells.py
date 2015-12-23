# Copyright 2015 OpenStack Foundation
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

import itertools

from oslo_config import cfg


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
               choices=('api', 'compute'),
               help='Type of cell'),
    cfg.IntOpt("mute_child_interval",
               default=300,
               help='Number of seconds after which a lack of capability and '
                     'capacity updates signals the child cell is to be '
                     'treated as a mute.'),
    cfg.IntOpt('bandwidth_update_interval',
                default=600,
                help='Seconds between bandwidth updates for cells.'),
    cfg.IntOpt('instance_update_sync_database_limit',
            default=100,
            help='Number of instances to pull from the database at one '
                 'time for a sync.  If there are more instances to update '
                 'the results will be paged through'),
]

mute_weigher_opts = [
        cfg.FloatOpt('mute_weight_multiplier',
                default=-10000.0,
                help='Multiplier used to weigh mute children. (The value '
                     'should be negative.)'),
]

ram_weigher_opts = [
        cfg.FloatOpt('ram_weight_multiplier',
                     default=10.0,
                     help='Multiplier used for weighing ram.  Negative '
                          'numbers mean to stack vs spread.'),
]

weigher_opts = [
    cfg.FloatOpt('offset_weight_multiplier',
                 default=1.0,
                 help='Multiplier used to weigh offset weigher.'),
]

cell_manager_opts = [
        cfg.StrOpt('driver',
                default='nova.cells.rpc_driver.CellsRPCDriver',
                help='Cells communication driver to use'),
        cfg.IntOpt("instance_updated_at_threshold",
                default=3600,
                help="Number of seconds after an instance was updated "
                        "or deleted to continue to update cells"),
        cfg.IntOpt("instance_update_num_instances",
                default=1,
                help="Number of instances to update per periodic task run")
]

cell_messaging_opts = [
    cfg.IntOpt('max_hop_count',
            default=10,
            help='Maximum number of hops for cells routing.'),
    cfg.StrOpt('scheduler',
            default='nova.cells.scheduler.CellsScheduler',
            help='Cells scheduler to use')
]

cell_rpc_driver_opts = [
        cfg.StrOpt('rpc_driver_queue_base',
                   default='cells.intercell',
                   help="Base queue name to use when communicating between "
                        "cells.  Various topics by message type will be "
                        "appended to this.")
]

cell_scheduler_opts = [
        cfg.ListOpt('scheduler_filter_classes',
                default=['nova.cells.filters.all_filters'],
                help='Filter classes the cells scheduler should use.  '
                        'An entry of "nova.cells.filters.all_filters" '
                        'maps to all cells filters included with nova.'),
        cfg.ListOpt('scheduler_weight_classes',
                default=['nova.cells.weights.all_weighers'],
                help='Weigher classes the cells scheduler should use.  '
                        'An entry of "nova.cells.weights.all_weighers" '
                        'maps to all cell weighers included with nova.'),
        cfg.IntOpt('scheduler_retries',
                default=10,
                help='How many retries when no cells are available.'),
        cfg.IntOpt('scheduler_retry_delay',
                default=2,
                help='How often to retry in seconds when no cells are '
                        'available.')
]

cell_state_manager_opts = [
        cfg.IntOpt('db_check_interval',
               default=60,
               help='Interval, in seconds, for getting fresh cell '
               'information from the database.'),
        cfg.StrOpt('cells_config',
               help='Configuration file from which to read cells '
               'configuration.  If given, overrides reading cells '
               'from the database.')
]


rpcapi_cap_intercell_opt = cfg.StrOpt('intercell',
        help='Set a version cap for messages sent between cells services')


rpcapi_cap_cells_opt = cfg.StrOpt('cells',
        help='Set a version cap for messages sent to local cells services')


ALL_CELLS_OPTS = list(itertools.chain(
            cells_opts,
            mute_weigher_opts,
            ram_weigher_opts,
            weigher_opts,
            cell_manager_opts,
            cell_messaging_opts,
            cell_rpc_driver_opts,
            cell_scheduler_opts,
            cell_state_manager_opts
            ))

ALL_RPCAPI_CAP_OPTS = [rpcapi_cap_intercell_opt,
                       rpcapi_cap_cells_opt]


def register_opts(conf):
    conf.register_opts(ALL_CELLS_OPTS, group="cells")
    conf.register_opts(ALL_RPCAPI_CAP_OPTS, group="upgrade_levels")


def list_opts():
    return {
        'cells': ALL_CELLS_OPTS,
        'upgrade_levels': ALL_RPCAPI_CAP_OPTS,
    }
