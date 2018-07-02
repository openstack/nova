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

from oslo_config import cfg

cells_group = cfg.OptGroup('cells',
                            title='Cells Options',
                            help="""
DEPRECATED: Cells options allow you to use cells v1 functionality in an
OpenStack deployment.

Note that the options in this group are only for cells v1 functionality, which
is considered experimental and not recommended for new deployments. Cells v1
is being replaced with cells v2, which starting in the 15.0.0 Ocata release is
required and all Nova deployments will be at least a cells v2 cell of one.

""")

cells_opts = [
    cfg.BoolOpt('enable',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Enable cell v1 functionality.

Note that cells v1 is considered experimental and not recommended for new
Nova deployments. Cells v1 is being replaced by cells v2 which starting in
the 15.0.0 Ocata release, all Nova deployments are at least a cells v2 cell
of one. Setting this option, or any other options in the [cells] group, is
not required for cells v2.

When this functionality is enabled, it lets you to scale an OpenStack
Compute cloud in a more distributed fashion without having to use
complicated technologies like database and message queue clustering.
Cells are configured as a tree. The top-level cell should have a host
that runs a nova-api service, but no nova-compute services. Each
child cell should run all of the typical nova-* services in a regular
Compute cloud except for nova-api. You can think of cells as a normal
Compute deployment in that each cell has its own database server and
message queue broker.

Related options:

* name: A unique cell name must be given when this functionality
  is enabled.
* cell_type: Cell type should be defined for all cells.
"""),
    cfg.StrOpt('name',
        default='nova',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Name of the current cell.

This value must be unique for each cell. Name of a cell is used as
its id, leaving this option unset or setting the same name for
two or more cells may cause unexpected behaviour.

Related options:

* enabled: This option is meaningful only when cells service
  is enabled
"""),
    cfg.ListOpt('capabilities',
        default=['hypervisor=xenserver;kvm', 'os=linux;windows'],
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Cell capabilities.

List of arbitrary key=value pairs defining capabilities of the
current cell to be sent to the parent cells. These capabilities
are intended to be used in cells scheduler filters/weighers.

Possible values:

* key=value pairs list for example;
  ``hypervisor=xenserver;kvm,os=linux;windows``
"""),
    cfg.IntOpt('call_timeout',
        default=60,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        min=0,
        help="""
Call timeout.

Cell messaging module waits for response(s) to be put into the
eventlet queue. This option defines the seconds waited for
response from a call to a cell.

Possible values:

* An integer, corresponding to the interval time in seconds.
"""),
    cfg.FloatOpt('reserve_percent',
        default=10.0,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
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

* An integer or float, corresponding to the percentage of cell capacity to
  be held in reserve.
"""),
    cfg.StrOpt('cell_type',
        default='compute',
        choices=('api', 'compute'),
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Type of cell.

When cells feature is enabled the hosts in the OpenStack Compute
cloud are partitioned into groups. Cells are configured as a tree.
The top-level cell's cell_type must be set to ``api``. All other
cells are defined as a ``compute cell`` by default.

Related option:

* quota_driver: Disable quota checking for the child cells.
  (nova.quota.NoopQuotaDriver)
"""),
    cfg.IntOpt('mute_child_interval',
        default=300,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Mute child interval.

Number of seconds after which a lack of capability and capacity
update the child cell is to be treated as a mute cell. Then the
child cell will be weighed as recommend highly that it be skipped.

Possible values:

* An integer, corresponding to the interval time in seconds.
"""),
    cfg.IntOpt('bandwidth_update_interval',
        default=600,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Bandwidth update interval.

Seconds between bandwidth usage cache updates for cells.

Possible values:

* An integer, corresponding to the interval time in seconds.
"""),
    cfg.IntOpt('instance_update_sync_database_limit',
        default=100,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Instance update sync database limit.

Number of instances to pull from the database at one time for
a sync. If there are more instances to update the results will
be paged through.

Possible values:

* An integer, corresponding to a number of instances.
"""),
]

mute_weigher_opts = [
    cfg.FloatOpt('mute_weight_multiplier',
        default=-10000.0,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Mute weight multiplier.

Multiplier used to weigh mute children. Mute children cells are
recommended to be skipped so their weight is multiplied by this
negative value.

Possible values:

* Negative numeric number
"""),
]

ram_weigher_opts = [
    cfg.FloatOpt('ram_weight_multiplier',
        default=10.0,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Ram weight multiplier.

Multiplier used for weighing ram. Negative numbers indicate that
Compute should stack VMs on one host instead of spreading out new
VMs to more hosts in the cell.

Possible values:

* Numeric multiplier
"""),
]

weigher_opts = [
    cfg.FloatOpt('offset_weight_multiplier',
        default=1.0,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Offset weight multiplier

Multiplier used to weigh offset weigher. Cells with higher
weight_offsets in the DB will be preferred. The weight_offset
is a property of a cell stored in the database. It can be used
by a deployer to have scheduling decisions favor or disfavor
cells based on the setting.

Possible values:

* Numeric multiplier
"""),
]

cell_manager_opts = [
    cfg.IntOpt('instance_updated_at_threshold',
        default=3600,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Instance updated at threshold

Number of seconds after an instance was updated or deleted to
continue to update cells. This option lets cells manager to only
attempt to sync instances that have been updated recently.
i.e., a threshold of 3600 means to only update instances that
have modified in the last hour.

Possible values:

* Threshold in seconds

Related options:

* This value is used with the ``instance_update_num_instances``
  value in a periodic task run.
"""),
    cfg.IntOpt("instance_update_num_instances",
        default=1,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Instance update num instances

On every run of the periodic task, nova cells manager will attempt to
sync instance_updated_at_threshold number of instances. When the
manager gets the list of instances, it shuffles them so that multiple
nova-cells services do not attempt to sync the same instances in
lockstep.

Possible values:

* Positive integer number

Related options:

* This value is used with the ``instance_updated_at_threshold``
  value in a periodic task run.
""")
]

cell_messaging_opts = [
    cfg.IntOpt('max_hop_count',
        default=10,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Maximum hop count

When processing a targeted message, if the local cell is not the
target, a route is defined between neighbouring cells. And the
message is processed across the whole routing path. This option
defines the maximum hop counts until reaching the target.

Possible values:

* Positive integer value
"""),
    cfg.StrOpt('scheduler',
        default='nova.cells.scheduler.CellsScheduler',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Cells scheduler.

The class of the driver used by the cells scheduler. This should be
the full Python path to the class to be used. If nothing is specified
in this option, the CellsScheduler is used.
""")
]

cell_rpc_driver_opts = [
    cfg.StrOpt('rpc_driver_queue_base',
        default='cells.intercell',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
RPC driver queue base.

When sending a message to another cell by JSON-ifying the message
and making an RPC cast to 'process_message', a base queue is used.
This option defines the base queue name to be used when communicating
between cells. Various topics by message type will be appended to this.

Possible values:

* The base queue name to be used when communicating between cells.
""")
]

cell_scheduler_opts = [
    cfg.ListOpt('scheduler_filter_classes',
        default=['nova.cells.filters.all_filters'],
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Scheduler filter classes.

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

"""),
    cfg.ListOpt('scheduler_weight_classes',
        default=['nova.cells.weights.all_weighers'],
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Scheduler weight classes.

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
"""),
    cfg.IntOpt('scheduler_retries',
        default=10,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Scheduler retries.

How many retries when no cells are available. Specifies how many
times the scheduler tries to launch a new instance when no cells
are available.

Possible values:

* Positive integer value

Related options:

* This value is used with the ``scheduler_retry_delay`` value
  while retrying to find a suitable cell.
"""),
    cfg.IntOpt('scheduler_retry_delay',
        default=2,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Scheduler retry delay.

Specifies the delay (in seconds) between scheduling retries when no
cell can be found to place the new instance on. When the instance
could not be scheduled to a cell after ``scheduler_retries`` in
combination with ``scheduler_retry_delay``, then the scheduling
of the instance failed.

Possible values:

* Time in seconds.

Related options:

* This value is used with the ``scheduler_retries`` value
  while retrying to find a suitable cell.
""")
]

cell_state_manager_opts = [
    cfg.IntOpt('db_check_interval',
        default=60,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
DB check interval.

Cell state manager updates cell status for all cells from the DB
only after this particular interval time is passed. Otherwise cached
status are used. If this value is 0 or negative all cell status are
updated from the DB whenever a state is needed.

Possible values:

* Interval time, in seconds.

"""),
    cfg.StrOpt('cells_config',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason='Cells v1 is being replaced with Cells v2.',
        help="""
Optional cells configuration.

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
this optional configuration::

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
""")
]

ALL_CELLS_OPTS = (cells_opts +
                  mute_weigher_opts +
                  ram_weigher_opts +
                  weigher_opts +
                  cell_manager_opts +
                  cell_messaging_opts +
                  cell_rpc_driver_opts +
                  cell_scheduler_opts +
                  cell_state_manager_opts)


def register_opts(conf):
    conf.register_group(cells_group)
    conf.register_opts(ALL_CELLS_OPTS, group=cells_group)


def list_opts():
    return {cells_group: ALL_CELLS_OPTS}
