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
                help="""
Enable cell functionality

When this functionality is enabled, it lets you to scale an OpenStack
Compute cloud in a more distributed fashion without having to use
complicated technologies like database and message queue clustering.
Cells are configured as a tree. The top-level cell should have a host
that runs a nova-api service, but no nova-compute services. Each
child cell should run all of the typical nova-* services in a regular
Compute cloud except for nova-api. You can think of cells as a normal
Compute deployment in that each cell has its own database server and
message queue broker.

Possible values:

* True: Enables the feature
* False: Disables the feature

Services which consume this:

* nova-api
* nova-cells
* nova-compute

Related options:

* name: A unique cell name must be given when this functionality
  is enabled.
* cell_type: Cell type should be defined for all cells.
"""),
    cfg.StrOpt('topic',
                default='cells',
                help="""
Topic

This is the message queue topic that cells nodes listen on. It is
used when the cells service is started up to configure the queue,
and whenever an RPC call to the scheduler is made.

Possible values:

* cells: This is the recommended and the default value.

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.StrOpt('manager',
               default='nova.cells.manager.CellsManager',
               help="""
DEPRECATED: Manager for cells

The nova-cells manager class. This class defines RPC methods that
the local cell may call. This class is NOT used for messages coming
from other cells. That communication is driver-specific.

Communication to other cells happens via the nova.cells.messaging module.
The MessageRunner from that module will handle routing the message to
the correct cell via the communication driver. Most methods below
create 'targeted' (where we want to route a message to a specific cell)
or 'broadcast' (where we want a message to go to multiple cells)
messages.

Scheduling requests get passed to the scheduler class.

Possible values:

* 'nova.cells.manager.CellsManager' is the only possible value for
  this option as of the Mitaka release

Services which consume this:

* nova-cells

Related options:

* None
""",
        deprecated_for_removal=True
    ),
    cfg.StrOpt('name',
                default='nova',
                help="""
Name of the current cell

This value must be unique for each cell. Name of a cell is used as
its id, leaving this option unset or setting the same name for
two or more cells may cause unexpected behaviour.

Possible values:

* Unique name string

Services which consume this:

* nova-cells

Related options:

* enabled: This option is meaningful only when cells service
  is enabled
"""),
    cfg.ListOpt('capabilities',
                default=['hypervisor=xenserver;kvm', 'os=linux;windows'],
                help="""
Cell capabilities

List of arbitrary key=value pairs defining capabilities of the
current cell to be sent to the parent cells. These capabilities
are intended to be used in cells scheduler filters/weighers.

Possible values:

* key=value pairs list for example;
  ``hypervisor=xenserver;kvm,os=linux;windows``

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.IntOpt('call_timeout',
                default=60,
                help="""
Call timeout

Cell messaging module waits for response(s) to be put into the
eventlet queue. This option defines the seconds waited for
response from a call to a cell.

Possible values:

* Time in seconds.

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.FloatOpt('reserve_percent',
                 default=10.0,
                 help="""
Reserve percentage

Percentage of cell capacity to hold in reserve, so the minimum
amount of free resource is considered to be;
  min_free = total * (reserve_percent / 100.0)
This option affects both memory and disk utilization.
The primary purpose of this reserve is to ensure some space is
available for users who want to resize their instance to be larger.
Note that currently once the capacity expands into this reserve
space this option is ignored.

Possible values:

* Float percentage value

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.StrOpt('cell_type',
               default='compute',
               choices=('api', 'compute'),
               help="""
Type of cell

When cells feature is enabled the hosts in the OpenStack Compute
cloud are partitioned into groups. Cells are configured as a tree.
The top-level cell's cell_type must be set to ``api``. All other
cells are defined as a ``compute cell`` by default.

Possible values:

* api: Cell type of top-level cell.
* compute: Cell type of all child cells. (Default)

Services which consume this:

* nova-cells

Related options:

* compute_api_class: This option must be set to cells api driver
  for the top-level cell (nova.compute.cells_api.ComputeCellsAPI)
* quota_driver: Disable quota checking for the child cells.
  (nova.quota.NoopQuotaDriver)
"""),
    cfg.IntOpt("mute_child_interval",
               default=300,
               help="""
Mute child interval

Number of seconds after which a lack of capability and capacity
update the child cell is to be treated as a mute cell. Then the
child cell will be weighed as recommend highly that it be skipped.

Possible values:

* Time in seconds.

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.IntOpt('bandwidth_update_interval',
                default=600,
                help="""
Bandwidth update interval

Seconds between bandwidth usage cache updates for cells.

Possible values:

* Time in seconds.

Services which consume this:

* nova-compute

Related options:

* None
"""),
    cfg.IntOpt('instance_update_sync_database_limit',
            default=100,
            help="""
Instance update sync database limit

Number of instances to pull from the database at one time for
a sync. If there are more instances to update the results will
be paged through.

Possible values:

* Number of instances.

Services which consume this:

* nova-cells

Related options:

* None
"""),
]

mute_weigher_opts = [
        cfg.FloatOpt('mute_weight_multiplier',
                default=-10000.0,
                help="""
Mute weight multiplier

Multiplier used to weigh mute children. Mute children cells are
recommended to be skipped so their weight is multiplied by this
negative value.

Possible values:

* Negative numeric number

Services which consume this:

* nova-cells

Related options:

* None
"""),
]

ram_weigher_opts = [
        cfg.FloatOpt('ram_weight_multiplier',
                     default=10.0,
                     help="""
Ram weight multiplier

Multiplier used for weighing ram. Negative numbers indicate that
Compute should stack VMs on one host instead of spreading out new
VMs to more hosts in the cell.

Possible values:

* Numeric multiplier

Services which consume this:

* nova-cells

Related options:

* None
"""),
]

weigher_opts = [
    cfg.FloatOpt('offset_weight_multiplier',
                 default=1.0,
                 help="""
Offset weight multiplier

Multiplier used to weigh offset weigher. Cells with higher
weight_offsets in the DB will be preferred. The weight_offset
is a property of a cell stored in the database. It can be used
by a deployer to have scheduling decisions favor or disfavor
cells based on the setting.

Possible values:

* Numeric multiplier

Services which consume this:

* nova-cells

Related options:

* None
"""),
]

cell_manager_opts = [
        cfg.StrOpt('driver',
                default='nova.cells.rpc_driver.CellsRPCDriver',
                help="""
Cells communication driver

Driver for cell<->cell communication via RPC. This is used to
setup the RPC consumers as well as to send a message to another cell.
'nova.cells.rpc_driver.CellsRPCDriver' starts up 2 separate servers
for handling inter-cell communication via RPC.

Possible values:

* 'nova.cells.rpc_driver.CellsRPCDriver' is the default driver
* Otherwise it should be the full Python path to the class to be used

Services which consume this:

* nova-cells

Related options:

* None
"""),
        cfg.IntOpt("instance_updated_at_threshold",
                default=3600,
                help="""
Instance updated at threshold

Number of seconds after an instance was updated or deleted to
continue to update cells. This option lets cells manager to only
attempt to sync instances that have been updated recently.
i.e., a threshold of 3600 means to only update instances that
have modified in the last hour.

Possible values:

* Threshold in seconds

Services which consume this:

* nova-cells

Related options:

* This value is used with the ``instance_update_num_instances``
  value in a periodic task run.
"""),
        cfg.IntOpt("instance_update_num_instances",
                default=1,
                help="""
Instance update num instances

On every run of the periodic task, nova cells manager will attempt to
sync instance_updated_at_threshold number of instances. When the
manager gets the list of instances, it shuffles them so that multiple
nova-cells services do not attempt to sync the same instances in
lockstep.

Possible values:

* Positive integer number

Services which consume this:

* nova-cells

Related options:

* This value is used with the ``instance_updated_at_threshold``
  value in a periodic task run.
""")
]

cell_messaging_opts = [
    cfg.IntOpt('max_hop_count',
            default=10,
            help="""
Maximum hop count

When processing a targeted message, if the local cell is not the
target, a route is defined between neighbouring cells. And the
message is processed across the whole routing path. This option
defines the maximum hop counts until reaching the target.

Possible values:

* Positive integer value

Services which consume this:

* nova-cells

Related options:

* None
"""),
    cfg.StrOpt('scheduler',
            default='nova.cells.scheduler.CellsScheduler',
            help="""
Cells scheduler

The class of the driver used by the cells scheduler. This should be
the full Python path to the class to be used. If nothing is specified
in this option, the CellsScheduler is used.


Possible values:

* 'nova.cells.scheduler.CellsScheduler' is the default option
* Otherwise it should be the full Python path to the class to be used

Services which consume this:

* nova-cells

Related options:

* None
""")
]

cell_rpc_driver_opts = [
        cfg.StrOpt('rpc_driver_queue_base',
                   default='cells.intercell',
                   help="""
RPC driver queue base

When sending a message to another cell by JSON-ifying the message
and making an RPC cast to 'process_message', a base queue is used.
This option defines the base queue name to be used when communicating
between cells. Various topics by message type will be appended to this.

Possible values:

* The base queue name to be used when communicating between cells.

Services which consume this:

* nova-cells

Related options:

* None
""")
]

cell_scheduler_opts = [
        cfg.ListOpt('scheduler_filter_classes',
                default=['nova.cells.filters.all_filters'],
                help="""
Scheduler filter classes

Filter classes the cells scheduler should use. An entry of
"nova.cells.filters.all_filters" maps to all cells filters
included with nova. As of the Mitaka release the following
filter classes are available:

Different cell filter: A scheduler hint of 'different_cell'
with a value of a full cell name may be specified to route
a build away from a particular cell.

Image properties filter: Image metadata named
'hypervisor_version_requires' with a version specification
may be specified to ensure the build goes to a cell which
has hypervisors of the required version. If either the version
requirement on the image or the hypervisor capability of the
cell is not present, this filter returns without filtering out
the cells.

Target cell filter: A scheduler hint of 'target_cell' with a
value of a full cell name may be specified to route a build to
a particular cell. No error handling is done as there's no way
to know whether the full path is a valid.

As an admin user, you can also add a filter that directs builds
to a particular cell.


Possible values:

* 'nova.cells.filters.all_filters' is the default option
* Otherwise it should be the full Python path to the class to be used

Services which consume this:

* nova-cells

Related options:

* None
"""),
        cfg.ListOpt('scheduler_weight_classes',
                default=['nova.cells.weights.all_weighers'],
                help="""
Scheduler weight classes

Weigher classes the cells scheduler should use. An entry of
"nova.cells.weights.all_weighers" maps to all cell weighers
included with nova. As of the Mitaka release the following
weight classes are available:

mute_child: Downgrades the likelihood of child cells being
chosen for scheduling requests, which haven't sent capacity
or capability updates in a while. Options include
mute_weight_multiplier (multiplier for mute children; value
should be negative).

ram_by_instance_type: Select cells with the most RAM capacity
for the instance type being requested. Because higher weights
win, Compute returns the number of available units for the
instance type requested. The ram_weight_multiplier option defaults
to 10.0 that adds to the weight by a factor of 10. Use a negative
number to stack VMs on one host instead of spreading out new VMs
to more hosts in the cell.

weight_offset: Allows modifying the database to weight a particular
cell. The highest weight will be the first cell to be scheduled for
launching an instance. When the weight_offset of a cell is set to 0,
it is unlikely to be picked but it could be picked if other cells
have a lower weight, like if they're full. And when the weight_offset
is set to a very high value (for example, '999999999999999'), it is
likely to be picked if another cell do not have a higher weight.

Possible values:

* 'nova.cells.weights.all_weighers' is the default option
* Otherwise it should be the full Python path to the class to be used

Services which consume this:

* nova-cells

Related options:

* None
"""),
        cfg.IntOpt('scheduler_retries',
                default=10,
                help="""
Scheduler retries

How many retries when no cells are available. Specifies how many
times the scheduler tries to launch a new instance when no cells
are available.

Possible values:

* Positive integer value

Services which consume this:

* nova-cells

Related options:

* This value is used with the ``scheduler_retry_delay`` value
  while retrying to find a suitable cell.
"""),
        cfg.IntOpt('scheduler_retry_delay',
                default=2,
                help="""
Scheduler retry delay

Specifies the delay (in seconds) between scheduling retries when no
cell can be found to place the new instance on. When the instance
could not be scheduled to a cell after ``scheduler_retries`` in
combination with ``scheduler_retry_delay``, then the scheduling
of the instance failed.

Possible values:

* Time in seconds.

Services which consume this:

* nova-cells

Related options:

* This value is used with the ``scheduler_retries`` value
  while retrying to find a suitable cell.
""")
]

cell_state_manager_opts = [
        cfg.IntOpt('db_check_interval',
               default=60,
               help="""
DB check interval

Cell state manager updates cell status for all cells from the DB
only after this particular interval time is passed. Otherwise cached
status are used. If this value is 0 or negative all cell status are
updated from the DB whenever a state is needed.

Possible values:

* Interval time, in seconds.

Services which consume this:

* nova-cells

Related options:

* None
"""),
        cfg.StrOpt('cells_config',
               help="""
Optional cells configuration

Configuration file from which to read cells configuration. If given,
overrides reading cells from the database.

Cells store all inter-cell communication data, including user names
and passwords, in the database. Because the cells data is not updated
very frequently, use this option to specify a JSON file to store
cells data. With this configuration, the database is no longer
consulted when reloading the cells data. The file must have columns
present in the Cell model (excluding common database fields and the
id column). You must specify the queue connection information through
a transport_url field, instead of username, password, and so on.

The transport_url has the following form:
rabbit://USERNAME:PASSWORD@HOSTNAME:PORT/VIRTUAL_HOST

Possible values:

The scheme can be either qpid or rabbit, the following sample shows
this optional configuration:

    {
        "parent": {
            "name": "parent",
            "api_url": "http://api.example.com:8774",
            "transport_url": "rabbit://rabbit.example.com",
            "weight_offset": 0.0,
            "weight_scale": 1.0,
            "is_parent": true
        },
        "cell1": {
            "name": "cell1",
            "api_url": "http://api.example.com:8774",
            "transport_url": "rabbit://rabbit1.example.com",
            "weight_offset": 0.0,
            "weight_scale": 1.0,
            "is_parent": false
        },
        "cell2": {
            "name": "cell2",
            "api_url": "http://api.example.com:8774",
            "transport_url": "rabbit://rabbit2.example.com",
            "weight_offset": 0.0,
            "weight_scale": 1.0,
            "is_parent": false
        }
    }

Services which consume this:

* nova-cells

Related options:

* None
""")
]


rpcapi_cap_intercell_opt = cfg.StrOpt('intercell',
        help="""
Intercell version

Intercell RPC API is the client side of the Cell<->Cell RPC API.
Use this option to set a version cap for messages sent between
cells services.

Possible values:

* None: This is the default value.
* grizzly: message version 1.0.

Services which consume this:

* nova-cells

Related options:

* None
""")


rpcapi_cap_cells_opt = cfg.StrOpt('cells',
        help="""
Cells version

Cells client-side RPC API version. Use this option to set a version
cap for messages sent to local cells services.

Possible values:

* None: This is the default value.
* grizzly: message version 1.6.
* havana: message version 1.24.
* icehouse: message version 1.27.
* juno: message version 1.29.
* kilo: message version 1.34.
* liberty: message version 1.37.

Services which consume this:

* nova-cells

Related options:

* None
""")


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
