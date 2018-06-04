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

from nova.virt import arch


scheduler_group = cfg.OptGroup(name="scheduler",
                               title="Scheduler configuration")

scheduler_opts = [
    cfg.StrOpt("host_manager",
        default="host_manager",
        choices=("host_manager", "ironic_host_manager"),
        deprecated_name="scheduler_host_manager",
        deprecated_group="DEFAULT",
        help="""
The scheduler host manager to use.

The host manager manages the in-memory picture of the hosts that the scheduler
uses. The options values are chosen from the entry points under the namespace
'nova.scheduler.host_manager' in 'setup.cfg'.

NOTE: The "ironic_host_manager" option is deprecated as of the 17.0.0 Queens
release.
"""),
    cfg.StrOpt("driver",
        default="filter_scheduler",
        deprecated_name="scheduler_driver",
        deprecated_group="DEFAULT",
        help="""
The class of the driver used by the scheduler. This should be chosen from one
of the entrypoints under the namespace 'nova.scheduler.driver' of file
'setup.cfg'. If nothing is specified in this option, the 'filter_scheduler' is
used.

Other options are:

* 'caching_scheduler' which aggressively caches the system state for better
  individual scheduler performance at the risk of more retries when running
  multiple schedulers. [DEPRECATED]
* 'chance_scheduler' which simply picks a host at random. [DEPRECATED]
* 'fake_scheduler' which is used for testing.

Possible values:

* Any of the drivers included in Nova:
** filter_scheduler
** caching_scheduler
** chance_scheduler
** fake_scheduler
* You may also set this to the entry point name of a custom scheduler driver,
  but you will be responsible for creating and maintaining it in your setup.cfg
  file.
"""),
    cfg.IntOpt("periodic_task_interval",
        default=60,
        deprecated_name="scheduler_driver_task_period",
        deprecated_group="DEFAULT",
        help="""
Periodic task interval.

This value controls how often (in seconds) to run periodic tasks in the
scheduler. The specific tasks that are run for each period are determined by
the particular scheduler being used.

If this is larger than the nova-service 'service_down_time' setting, Nova may
report the scheduler service as down. This is because the scheduler driver is
responsible for sending a heartbeat and it will only do that as often as this
option allows. As each scheduler can work a little differently than the others,
be sure to test this with your selected scheduler.

Possible values:

* An integer, where the integer corresponds to periodic task interval in
  seconds. 0 uses the default interval (60 seconds). A negative value disables
  periodic tasks.

Related options:

* ``nova-service service_down_time``
"""),
    cfg.IntOpt("max_attempts",
        default=3,
        min=1,
        deprecated_name="scheduler_max_attempts",
        deprecated_group="DEFAULT",
        help="""
This is the maximum number of attempts that will be made for a given instance
build/move operation. It limits the number of alternate hosts returned by the
scheduler. When that list of hosts is exhausted, a MaxRetriesExceeded
exception is raised and the instance is set to an error state.

Possible values:

* A positive integer, where the integer corresponds to the max number of
  attempts that can be made when building or moving an instance.
        """),
    cfg.IntOpt("discover_hosts_in_cells_interval",
               default=-1,
               min=-1,
               help="""
Periodic task interval.

This value controls how often (in seconds) the scheduler should attempt
to discover new hosts that have been added to cells. If negative (the
default), no automatic discovery will occur.

Deployments where compute nodes come and go frequently may want this
enabled, where others may prefer to manually discover hosts when one
is added to avoid any overhead from constantly checking. If enabled,
every time this runs, we will select any unmapped hosts out of each
cell database on every run.
"""),
    cfg.IntOpt("max_placement_results",
               default=1000,
               min=1,
               help="""
This setting determines the maximum limit on results received from the
placement service during a scheduling operation. It effectively limits
the number of hosts that may be considered for scheduling requests that
match a large number of candidates.

A value of 1 (the minimum) will effectively defer scheduling to the placement
service strictly on "will it fit" grounds. A higher value will put an upper
cap on the number of results the scheduler will consider during the filtering
and weighing process. Large deployments may need to set this lower than the
total number of hosts available to limit memory consumption, network traffic,
etc. of the scheduler.

This option is only used by the FilterScheduler; if you use a different
scheduler, this option has no effect.
"""),
]

filter_scheduler_group = cfg.OptGroup(name="filter_scheduler",
                           title="Filter scheduler options")

filter_scheduler_opts = [
    cfg.IntOpt("host_subset_size",
        default=1,
        min=1,
        deprecated_name="scheduler_host_subset_size",
        deprecated_group="DEFAULT",
        help="""
Size of subset of best hosts selected by scheduler.

New instances will be scheduled on a host chosen randomly from a subset of the
N best hosts, where N is the value set by this option.

Setting this to a value greater than 1 will reduce the chance that multiple
scheduler processes handling similar requests will select the same host,
creating a potential race condition. By selecting a host randomly from the N
hosts that best fit the request, the chance of a conflict is reduced. However,
the higher you set this value, the less optimal the chosen host may be for a
given request.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* An integer, where the integer corresponds to the size of a host subset. Any
  integer is valid, although any value less than 1 will be treated as 1
"""),
    cfg.IntOpt("max_io_ops_per_host",
        default=8,
        deprecated_group="DEFAULT",
        help="""
The number of instances that can be actively performing IO on a host.

Instances performing IO includes those in the following states: build, resize,
snapshot, migrate, rescue, unshelve.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'io_ops_filter' filter is enabled.

Possible values:

* An integer, where the integer corresponds to the max number of instances
  that can be actively performing IO on any given host.
"""),
    cfg.IntOpt("max_instances_per_host",
        default=50,
        min=1,
        deprecated_group="DEFAULT",
        help="""
Maximum number of instances that be active on a host.

If you need to limit the number of instances on any given host, set this option
to the maximum number of instances you want to allow. The num_instances_filter
will reject any host that has at least as many instances as this option's
value.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'num_instances_filter' filter is enabled.

Possible values:

* An integer, where the integer corresponds to the max instances that can be
  scheduled on a host.
"""),
    cfg.BoolOpt("track_instance_changes",
        default=True,
        deprecated_name="scheduler_tracks_instance_changes",
        deprecated_group="DEFAULT",
        help="""
Enable querying of individual hosts for instance information.

The scheduler may need information about the instances on a host in order to
evaluate its filters and weighers. The most common need for this information is
for the (anti-)affinity filters, which need to choose a host based on the
instances already running on a host.

If the configured filters and weighers do not need this information, disabling
this option will improve performance. It may also be disabled when the tracking
overhead proves too heavy, although this will cause classes requiring host
usage data to query the database on each request instead.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

NOTE: In a multi-cell (v2) setup where the cell MQ is separated from the
top-level, computes cannot directly communicate with the scheduler. Thus,
this option cannot be enabled in that scenario. See also the
[workarounds]/disable_group_policy_check_upcall option.
"""),
    cfg.MultiStrOpt("available_filters",
        default=["nova.scheduler.filters.all_filters"],
        deprecated_name="scheduler_available_filters",
        deprecated_group="DEFAULT",
        help="""
Filters that the scheduler can use.

An unordered list of the filter classes the nova scheduler may apply.  Only the
filters specified in the 'enabled_filters' option will be used, but
any filter appearing in that option must also be included in this list.

By default, this is set to all filters that are included with nova.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a filter that may be used for selecting a host

Related options:

* enabled_filters
"""),
    cfg.ListOpt("enabled_filters",
        default=[
          "RetryFilter",
          "AvailabilityZoneFilter",
          "ComputeFilter",
          "ComputeCapabilitiesFilter",
          "ImagePropertiesFilter",
          "ServerGroupAntiAffinityFilter",
          "ServerGroupAffinityFilter",
          ],
        deprecated_name="scheduler_default_filters",
        deprecated_group="DEFAULT",
        help="""
Filters that the scheduler will use.

An ordered list of filter class names that will be used for filtering
hosts. These filters will be applied in the order they are listed so
place your most restrictive filters first to make the filtering process more
efficient.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a filter to be used for selecting a host

Related options:

* All of the filters in this option *must* be present in the
  'scheduler_available_filters' option, or a SchedulerHostFilterNotFound
  exception will be raised.
"""),
    cfg.ListOpt("baremetal_enabled_filters",
        default=[
            "RetryFilter",
            "AvailabilityZoneFilter",
            "ComputeFilter",
            "ComputeCapabilitiesFilter",
            "ImagePropertiesFilter",
            "ExactRamFilter",
            "ExactDiskFilter",
            "ExactCoreFilter",
        ],
        deprecated_name="baremetal_scheduler_default_filters",
        deprecated_group="DEFAULT",
        deprecated_for_removal=True,
        deprecated_reason="""
These filters were used to overcome some of the baremetal scheduling
limitations in Nova prior to the use of the Placement API. Now scheduling will
use the custom resource class defined for each baremetal node to make its
selection.
""",
        help="""
Filters used for filtering baremetal hosts.

Filters are applied in order, so place your most restrictive filters first to
make the filtering process more efficient.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a filter to be used for selecting a baremetal host

Related options:

* If the 'scheduler_use_baremetal_filters' option is False, this option has
  no effect.
"""),
    cfg.BoolOpt("use_baremetal_filters",
        deprecated_name="scheduler_use_baremetal_filters",
        deprecated_group="DEFAULT",
        # NOTE(mriedem): We likely can't remove this option until the
        # IronicHostManager is removed, and we likely can't remove that
        # until all filters can at least not fail on ironic nodes, like the
        # NUMATopologyFilter.
        deprecated_for_removal=True,
        deprecated_reason="""
These filters were used to overcome some of the baremetal scheduling
limitations in Nova prior to the use of the Placement API. Now scheduling will
use the custom resource class defined for each baremetal node to make its
selection.
""",
        default=False,
        help="""
Enable baremetal filters.

Set this to True to tell the nova scheduler that it should use the filters
specified in the 'baremetal_enabled_filters' option. If you are not
scheduling baremetal nodes, leave this at the default setting of False.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Related options:

* If this option is set to True, then the filters specified in the
  'baremetal_enabled_filters' are used instead of the filters
  specified in 'enabled_filters'.
"""),
    cfg.ListOpt("weight_classes",
        default=["nova.scheduler.weights.all_weighers"],
        deprecated_name="scheduler_weight_classes",
        deprecated_group="DEFAULT",
        help="""
Weighers that the scheduler will use.

Only hosts which pass the filters are weighed. The weight for any host starts
at 0, and the weighers order these hosts by adding to or subtracting from the
weight assigned by the previous weigher. Weights may become negative. An
instance will be scheduled to one of the N most-weighted hosts, where N is
'scheduler_host_subset_size'.

By default, this is set to all weighers that are included with Nova.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a weigher that will be used for selecting a host
"""),
    cfg.FloatOpt("ram_weight_multiplier",
        default=1.0,
        deprecated_group="DEFAULT",
        help="""
Ram weight multipler ratio.

This option determines how hosts with more or less available RAM are weighed. A
positive value will result in the scheduler preferring hosts with more
available RAM, and a negative number will result in the scheduler preferring
hosts with less available RAM. Another way to look at it is that positive
values for this option will tend to spread instances across many hosts, while
negative values will tend to fill up (stack) hosts as much as possible before
scheduling to a less-used host. The absolute value, whether positive or
negative, controls how strong the RAM weigher is relative to other weighers.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'ram' weigher is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.
"""),
    cfg.FloatOpt("disk_weight_multiplier",
        default=1.0,
        deprecated_group="DEFAULT",
        help="""
Disk weight multipler ratio.

Multiplier used for weighing free disk space. Negative numbers mean to
stack vs spread.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'disk' weigher is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.
"""),
    cfg.FloatOpt("io_ops_weight_multiplier",
        default=-1.0,
        deprecated_group="DEFAULT",
        help="""
IO operations weight multipler ratio.

This option determines how hosts with differing workloads are weighed. Negative
values, such as the default, will result in the scheduler preferring hosts with
lighter workloads whereas positive values will prefer hosts with heavier
workloads. Another way to look at it is that positive values for this option
will tend to schedule instances onto hosts that are already busy, while
negative values will tend to distribute the workload across more hosts. The
absolute value, whether positive or negative, controls how strong the io_ops
weigher is relative to other weighers.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'io_ops' weigher is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.
"""),
    cfg.FloatOpt("pci_weight_multiplier",
        default=1.0,
        min=0.0,
        help="""
PCI device affinity weight multiplier.

The PCI device affinity weighter computes a weighting based on the number of
PCI devices on the host and the number of PCI devices requested by the
instance. The ``NUMATopologyFilter`` filter must be enabled for this to have
any significance. For more information, refer to the filter documentation:

    https://docs.openstack.org/nova/latest/user/filter-scheduler.html

Possible values:

* A positive integer or float value, where the value corresponds to the
  multiplier ratio for this weigher.
"""),
    # TODO(sfinucan): Add 'min' parameter and remove warning in 'affinity.py'
    cfg.FloatOpt("soft_affinity_weight_multiplier",
        default=1.0,
        deprecated_group="DEFAULT",
        help="""
Multiplier used for weighing hosts for group soft-affinity.

Possible values:

* An integer or float value, where the value corresponds to weight multiplier
  for hosts with group soft affinity. Only a positive value are meaningful, as
  negative values would make this behave as a soft anti-affinity weigher.
"""),
    cfg.FloatOpt(
        "soft_anti_affinity_weight_multiplier",
        default=1.0,
        deprecated_group="DEFAULT",
        help="""
Multiplier used for weighing hosts for group soft-anti-affinity.

Possible values:

* An integer or float value, where the value corresponds to weight multiplier
  for hosts with group soft anti-affinity. Only a positive value are
  meaningful, as negative values would make this behave as a soft affinity
  weigher.
"""),
    cfg.FloatOpt(
        "build_failure_weight_multiplier",
        default=1000000.0,
        help="""
Multiplier used for weighing hosts that have had recent build failures.

This option determines how much weight is placed on a compute node with
recent build failures. Build failures may indicate a failing, misconfigured,
or otherwise ailing compute node, and avoiding it during scheduling may be
beneficial. The weight is inversely proportional to the number of recent
build failures the compute node has experienced. This value should be
set to some high value to offset weight given by other enabled weighers
due to available resources. To disable weighing compute hosts by the
number of recent failures, set this to zero.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* An integer or float value, where the value corresponds to the multiplier
  ratio for this weigher.

Related options:

* [compute]/consecutive_build_service_disable_threshold - Must be nonzero
  for a compute to report data considered by this weigher.
"""),
    cfg.BoolOpt(
        "shuffle_best_same_weighed_hosts",
        default=False,
        help="""
Enable spreading the instances between hosts with the same best weight.

Enabling it is beneficial for cases when host_subset_size is 1
(default), but there is a large number of hosts with same maximal weight.
This scenario is common in Ironic deployments where there are typically many
baremetal nodes with identical weights returned to the scheduler.
In such case enabling this option will reduce contention and chances for
rescheduling events.
At the same time it will make the instance packing (even in unweighed case)
less dense.
"""),
    cfg.StrOpt(
        "image_properties_default_architecture",
        choices=arch.ALL,
        help="""
The default architecture to be used when using the image properties filter.

When using the ImagePropertiesFilter, it is possible that you want to define
a default architecture to make the user experience easier and avoid having
something like x86_64 images landing on aarch64 compute nodes because the
user did not specify the 'hw_architecture' property in Glance.

Possible values:

* CPU Architectures such as x86_64, aarch64, s390x.
"""),
    # TODO(mikal): replace this option with something involving host aggregates
    cfg.ListOpt("isolated_images",
        default=[],
        deprecated_group="DEFAULT",
        help="""
List of UUIDs for images that can only be run on certain hosts.

If there is a need to restrict some images to only run on certain designated
hosts, list those image UUIDs here.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled.

Possible values:

* A list of UUID strings, where each string corresponds to the UUID of an
  image

Related options:

* scheduler/isolated_hosts
* scheduler/restrict_isolated_hosts_to_isolated_images
"""),
    cfg.ListOpt("isolated_hosts",
        default=[],
        deprecated_group="DEFAULT",
        help="""
List of hosts that can only run certain images.

If there is a need to restrict some images to only run on certain designated
hosts, list those host names here.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled.

Possible values:

* A list of strings, where each string corresponds to the name of a host

Related options:

* scheduler/isolated_images
* scheduler/restrict_isolated_hosts_to_isolated_images
"""),
    cfg.BoolOpt(
        "restrict_isolated_hosts_to_isolated_images",
        default=True,
        deprecated_group="DEFAULT",
        help="""
Prevent non-isolated images from being built on isolated hosts.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled. Even
then, this option doesn't affect the behavior of requests for isolated images,
which will *always* be restricted to isolated hosts.

Related options:

* scheduler/isolated_images
* scheduler/isolated_hosts
"""),
    cfg.StrOpt(
        "aggregate_image_properties_isolation_namespace",
        deprecated_group="DEFAULT",
        help="""
Image property namespace for use in the host aggregate.

Images and hosts can be configured so that certain images can only be scheduled
to hosts in a particular aggregate. This is done with metadata values set on
the host aggregate that are identified by beginning with the value of this
option. If the host is part of an aggregate with such a metadata key, the image
in the request spec must have the value of that metadata in its properties in
order for the scheduler to consider the host as acceptable.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'aggregate_image_properties_isolation' filter is
enabled.

Possible values:

* A string, where the string corresponds to an image property namespace

Related options:

* aggregate_image_properties_isolation_separator
"""),
    cfg.StrOpt(
        "aggregate_image_properties_isolation_separator",
        default=".",
        deprecated_group="DEFAULT",
        help="""
Separator character(s) for image property namespace and name.

When using the aggregate_image_properties_isolation filter, the relevant
metadata keys are prefixed with the namespace defined in the
aggregate_image_properties_isolation_namespace configuration option plus a
separator. This option defines the separator to be used.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'aggregate_image_properties_isolation' filter
is enabled.

Possible values:

* A string, where the string corresponds to an image property namespace
  separator character

Related options:

* aggregate_image_properties_isolation_namespace
""")]

metrics_group = cfg.OptGroup(name="metrics",
                             title="Metrics parameters",
                             help="""
Configuration options for metrics

Options under this group allow to adjust how values assigned to metrics are
calculated.
""")

metrics_weight_opts = [
     cfg.FloatOpt("weight_multiplier",
            default=1.0,
            help="""
When using metrics to weight the suitability of a host, you can use this option
to change how the calculated weight influences the weight assigned to a host as
follows:

* >1.0: increases the effect of the metric on overall weight
* 1.0: no change to the calculated weight
* >0.0,<1.0: reduces the effect of the metric on overall weight
* 0.0: the metric value is ignored, and the value of the
  'weight_of_unavailable' option is returned instead
* >-1.0,<0.0: the effect is reduced and reversed
* -1.0: the effect is reversed
* <-1.0: the effect is increased proportionally and reversed

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* weight_of_unavailable
"""),
     cfg.ListOpt("weight_setting",
            default=[],
            help="""
This setting specifies the metrics to be weighed and the relative ratios for
each metric. This should be a single string value, consisting of a series of
one or more 'name=ratio' pairs, separated by commas, where 'name' is the name
of the metric to be weighed, and 'ratio' is the relative weight for that
metric.

Note that if the ratio is set to 0, the metric value is ignored, and instead
the weight will be set to the value of the 'weight_of_unavailable' option.

As an example, let's consider the case where this option is set to:

    ``name1=1.0, name2=-1.3``

The final weight will be:

    ``(name1.value * 1.0) + (name2.value * -1.3)``

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* A list of zero or more key/value pairs separated by commas, where the key is
  a string representing the name of a metric and the value is a numeric weight
  for that metric. If any value is set to 0, the value is ignored and the
  weight will be set to the value of the 'weight_of_unavailable' option.

Related options:

* weight_of_unavailable
"""),
    cfg.BoolOpt("required",
            default=True,
            help="""
This setting determines how any unavailable metrics are treated. If this option
is set to True, any hosts for which a metric is unavailable will raise an
exception, so it is recommended to also use the MetricFilter to filter out
those hosts before weighing.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* True or False, where False ensures any metric being unavailable for a host
  will set the host weight to 'weight_of_unavailable'.

Related options:

* weight_of_unavailable
"""),
    cfg.FloatOpt("weight_of_unavailable",
            default=float(-10000.0),
            help="""
When any of the following conditions are met, this value will be used in place
of any actual metric value:

* One of the metrics named in 'weight_setting' is not available for a host,
  and the value of 'required' is False
* The ratio specified for a metric in 'weight_setting' is 0
* The 'weight_multiplier' option is set to 0

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* weight_setting
* required
* weight_multiplier
"""),
]


def register_opts(conf):
    conf.register_group(scheduler_group)
    conf.register_opts(scheduler_opts, group=scheduler_group)

    conf.register_group(filter_scheduler_group)
    conf.register_opts(filter_scheduler_opts, group=filter_scheduler_group)

    conf.register_group(metrics_group)
    conf.register_opts(metrics_weight_opts, group=metrics_group)


def list_opts():
    return {scheduler_group: scheduler_opts,
            filter_scheduler_group: filter_scheduler_opts,
            metrics_group: metrics_weight_opts}
