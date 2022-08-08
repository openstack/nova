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


scheduler_group = cfg.OptGroup(
    name="scheduler", title="Scheduler configuration")

scheduler_opts = [
    cfg.IntOpt("max_attempts",
        default=3,
        min=1,
        help="""
The maximum number of schedule attempts.

This is the maximum number of attempts that will be made for a given instance
build/move operation. It limits the number of alternate hosts returned by the
scheduler. When that list of hosts is exhausted, a ``MaxRetriesExceeded``
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

Possible values:

* An integer, where the integer corresponds to periodic task interval in
  seconds. 0 uses the default interval (60 seconds). A negative value disables
  periodic tasks.
"""),
    cfg.IntOpt("max_placement_results",
        default=1000,
        min=1,
        help="""
The maximum number of placement results to request.

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

Possible values:

* An integer, where the integer corresponds to the number of placement results
  to return.
"""),
    cfg.IntOpt("workers",
        min=0,
        help="""
Number of workers for the nova-scheduler service.

Defaults to the number of CPUs available.

Possible values:

* An integer, where the integer corresponds to the number of worker processes.
"""),
    cfg.BoolOpt("query_placement_for_routed_network_aggregates",
                default=False,
                help="""
Enable the scheduler to filter compute hosts affined to routed network segment
aggregates.

See https://docs.openstack.org/neutron/latest/admin/config-routed-networks.html
for details.
"""),
    cfg.BoolOpt("limit_tenants_to_placement_aggregate",
        default=False,
        help="""
Restrict tenants to specific placement aggregates.

This setting causes the scheduler to look up a host aggregate with the
metadata key of ``filter_tenant_id`` set to the project of an incoming
request, and request results from placement be limited to that aggregate.
Multiple tenants may be added to a single aggregate by appending a serial
number to the key, such as ``filter_tenant_id:123``.

The matching aggregate UUID must be mirrored in placement for proper
operation. If no host aggregate with the tenant id is found, or that
aggregate does not match one in placement, the result will be the same
as not finding any suitable hosts for the request.

Possible values:

- A boolean value.

Related options:

- ``[scheduler] placement_aggregate_required_for_tenants``
"""),
    cfg.BoolOpt("placement_aggregate_required_for_tenants",
        default=False,
        help="""
Require a placement aggregate association for all tenants.

This setting, when limit_tenants_to_placement_aggregate=True, will control
whether or not a tenant with no aggregate affinity will be allowed to schedule
to any available node. If aggregates are used to limit some tenants but
not all, then this should be False. If all tenants should be confined via
aggregate, then this should be True to prevent them from receiving unrestricted
scheduling to any available node.

Possible values:

- A boolean value.

Related options:

- ``[scheduler] placement_aggregate_required_for_tenants``
"""),
    cfg.BoolOpt("query_placement_for_availability_zone",
        default=True,
        deprecated_for_removal=True,
        deprecated_since='24.0.0',
        deprecated_reason="""
Since the introduction of placement pre-filters in 18.0.0 (Rocky), we have
supported tracking Availability Zones either natively in placement or using the
legacy ``AvailabilityZoneFilter`` scheduler filter. In 24.0.0 (Xena), the
filter-based approach has been deprecated for removal in favor of the
placement-based approach. As a result, this config option has also been
deprecated and will be removed when the ``AvailabilityZoneFilter`` filter is
removed.
""",
        help="""
Use placement to determine availability zones.

This setting causes the scheduler to look up a host aggregate with the
metadata key of `availability_zone` set to the value provided by an
incoming request, and request results from placement be limited to that
aggregate.

The matching aggregate UUID must be mirrored in placement for proper
operation. If no host aggregate with the `availability_zone` key is
found, or that aggregate does not match one in placement, the result will
be the same as not finding any suitable hosts.

Note that if you disable this flag, you **must** enable the (less efficient)
``AvailabilityZoneFilter`` in the scheduler in order to availability zones to
work correctly.

Possible values:

- A boolean value.

Related options:

- ``[filter_scheduler] enabled_filters``
"""),
    cfg.BoolOpt("query_placement_for_image_type_support",
        default=False,
        help="""
Use placement to determine host support for the instance's image type.

This setting causes the scheduler to ask placement only for compute
hosts that support the ``disk_format`` of the image used in the request.

Possible values:

- A boolean value.
"""),
    cfg.BoolOpt("enable_isolated_aggregate_filtering",
        default=False,
        help="""
Restrict use of aggregates to instances with matching metadata.

This setting allows the scheduler to restrict hosts in aggregates based on
matching required traits in the aggregate metadata and the instance
flavor/image. If an aggregate is configured with a property with key
``trait:$TRAIT_NAME`` and value ``required``, the instance flavor extra_specs
and/or image metadata must also contain ``trait:$TRAIT_NAME=required`` to be
eligible to be scheduled to hosts in that aggregate. More technical details
at https://docs.openstack.org/nova/latest/reference/isolate-aggregates.html

Possible values:

- A boolean value.
"""),
    cfg.BoolOpt("image_metadata_prefilter",
        default=False,
        help="""
Use placement to filter hosts based on image metadata.

This setting causes the scheduler to transform well known image metadata
properties into placement required traits to filter host based on image
metadata. This feature requires host support and is currently supported by the
following compute drivers:

- ``libvirt.LibvirtDriver`` (since Ussuri (21.0.0))

Possible values:

- A boolean value.

Related options:

- ``[compute] compute_driver``
"""),
]

filter_scheduler_group = cfg.OptGroup(
    name="filter_scheduler", title="Filter scheduler options")

filter_scheduler_opts = [
    cfg.IntOpt("host_subset_size",
        default=1,
        min=1,
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

Possible values:

* An integer, where the integer corresponds to the size of a host subset.
"""),
    cfg.IntOpt("max_io_ops_per_host",
        default=8,
        min=0,
        help="""
The number of instances that can be actively performing IO on a host.

Instances performing IO includes those in the following states: build, resize,
snapshot, migrate, rescue, unshelve.

Note that this setting only affects scheduling if the ``IoOpsFilter`` filter is
enabled.

Possible values:

* An integer, where the integer corresponds to the max number of instances
  that can be actively performing IO on any given host.

Related options:

- ``[filter_scheduler] enabled_filters``
"""),
    cfg.IntOpt("max_instances_per_host",
        default=50,
        min=1,
        help="""
Maximum number of instances that can exist on a host.

If you need to limit the number of instances on any given host, set this option
to the maximum number of instances you want to allow. The NumInstancesFilter
and AggregateNumInstancesFilter will reject any host that has at least as many
instances as this option's value.

Note that this setting only affects scheduling if the ``NumInstancesFilter`` or
``AggregateNumInstancesFilter`` filter is enabled.

Possible values:

* An integer, where the integer corresponds to the max instances that can be
  scheduled on a host.

Related options:

- ``[filter_scheduler] enabled_filters``
"""),
    cfg.BoolOpt("track_instance_changes",
        default=True,
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

.. note::

   In a multi-cell (v2) setup where the cell MQ is separated from the
   top-level, computes cannot directly communicate with the scheduler. Thus,
   this option cannot be enabled in that scenario. See also the
   ``[workarounds] disable_group_policy_check_upcall`` option.

Related options:

- ``[filter_scheduler] enabled_filters``
- ``[workarounds] disable_group_policy_check_upcall``
"""),
    cfg.MultiStrOpt("available_filters",
        default=["nova.scheduler.filters.all_filters"],
        help="""
Filters that the scheduler can use.

An unordered list of the filter classes the nova scheduler may apply.  Only the
filters specified in the ``[filter_scheduler] enabled_filters`` option will be
used, but any filter appearing in that option must also be included in this
list.

By default, this is set to all filters that are included with nova.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a filter that may be used for selecting a host

Related options:

* ``[filter_scheduler] enabled_filters``
"""),
    cfg.ListOpt("enabled_filters",
        # NOTE(artom) If we change the defaults here, we should also update
        # Tempest's scheduler_enabled_filters to keep the default values in
        # sync.
        default=[
            "ComputeFilter",
            "ComputeCapabilitiesFilter",
            "ImagePropertiesFilter",
            "ServerGroupAntiAffinityFilter",
            "ServerGroupAffinityFilter",
        ],
        help="""
Filters that the scheduler will use.

An ordered list of filter class names that will be used for filtering
hosts. These filters will be applied in the order they are listed so
place your most restrictive filters first to make the filtering process more
efficient.

All of the filters in this option *must* be present in the ``[scheduler_filter]
available_filter`` option, or a ``SchedulerHostFilterNotFound`` exception will
be raised.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a filter to be used for selecting a host

Related options:

- ``[filter_scheduler] available_filters``
"""),
    cfg.ListOpt("weight_classes",
        default=["nova.scheduler.weights.all_weighers"],
        help="""
Weighers that the scheduler will use.

Only hosts which pass the filters are weighed. The weight for any host starts
at 0, and the weighers order these hosts by adding to or subtracting from the
weight assigned by the previous weigher. Weights may become negative. An
instance will be scheduled to one of the N most-weighted hosts, where N is
``[filter_scheduler] host_subset_size``.

By default, this is set to all weighers that are included with Nova.

Possible values:

* A list of zero or more strings, where each string corresponds to the name of
  a weigher that will be used for selecting a host
"""),
    cfg.FloatOpt("ram_weight_multiplier",
        default=1.0,
        help="""
RAM weight multipler ratio.

This option determines how hosts with more or less available RAM are weighed. A
positive value will result in the scheduler preferring hosts with more
available RAM, and a negative number will result in the scheduler preferring
hosts with less available RAM. Another way to look at it is that positive
values for this option will tend to spread instances across many hosts, while
negative values will tend to fill up (stack) hosts as much as possible before
scheduling to a less-used host. The absolute value, whether positive or
negative, controls how strong the RAM weigher is relative to other weighers.

Note that this setting only affects scheduling if the ``RAMWeigher`` weigher is
enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt("cpu_weight_multiplier",
        default=1.0,
        help="""
CPU weight multiplier ratio.

Multiplier used for weighting free vCPUs. Negative numbers indicate stacking
rather than spreading.

Note that this setting only affects scheduling if the ``CPUWeigher`` weigher is
enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt("disk_weight_multiplier",
        default=1.0,
        help="""
Disk weight multipler ratio.

Multiplier used for weighing free disk space. Negative numbers mean to
stack vs spread.

Note that this setting only affects scheduling if the ``DiskWeigher`` weigher
is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.
"""),
    cfg.FloatOpt("io_ops_weight_multiplier",
        default=-1.0,
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

Note that this setting only affects scheduling if the ``IoOpsWeigher`` weigher
is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt("pci_weight_multiplier",
        default=1.0,
        min=0.0,
        help="""
PCI device affinity weight multiplier.

The PCI device affinity weighter computes a weighting based on the number of
PCI devices on the host and the number of PCI devices requested by the
instance.

Note that this setting only affects scheduling if the ``PCIWeigher`` weigher
and ``NUMATopologyFilter`` filter are enabled.

Possible values:

* A positive integer or float value, where the value corresponds to the
  multiplier ratio for this weigher.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt("soft_affinity_weight_multiplier",
        default=1.0,
        min=0.0,
        help="""
Multiplier used for weighing hosts for group soft-affinity.

Note that this setting only affects scheduling if the
``ServerGroupSoftAffinityWeigher`` weigher is enabled.

Possible values:

* A non-negative integer or float value, where the value corresponds to
  weight multiplier for hosts with group soft affinity.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt(
        "soft_anti_affinity_weight_multiplier",
        default=1.0,
        min=0.0,
        help="""
Multiplier used for weighing hosts for group soft-anti-affinity.

Note that this setting only affects scheduling if the
``ServerGroupSoftAntiAffinityWeigher`` weigher is enabled.

Possible values:

* A non-negative integer or float value, where the value corresponds to
  weight multiplier for hosts with group soft anti-affinity.

Related options:

* ``[filter_scheduler] weight_classes``
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

Note that this setting only affects scheduling if the ``BuildFailureWeigher``
weigher is enabled.

Possible values:

* An integer or float value, where the value corresponds to the multiplier
  ratio for this weigher.

Related options:

* ``[compute] consecutive_build_service_disable_threshold`` - Must be nonzero
  for a compute to report data considered by this weigher.
* ``[filter_scheduler] weight_classes``
"""),
    cfg.FloatOpt(
        "cross_cell_move_weight_multiplier",
        default=1000000.0,
        help="""
Multiplier used for weighing hosts during a cross-cell move.

This option determines how much weight is placed on a host which is within the
same source cell when moving a server, for example during cross-cell resize.
By default, when moving an instance, the scheduler will prefer hosts within
the same cell since cross-cell move operations can be slower and riskier due to
the complicated nature of cross-cell migrations.

Note that this setting only affects scheduling if the ``CrossCellWeigher``
weigher is enabled.  If your cloud is not configured to support cross-cell
migrations, then this option has no effect.

The value of this configuration option can be overridden per host aggregate
by setting the aggregate metadata key with the same name
(``cross_cell_move_weight_multiplier``).

Possible values:

* An integer or float value, where the value corresponds to the multiplier
  ratio for this weigher. Positive values mean the weigher will prefer
  hosts within the same cell in which the instance is currently running.
  Negative values mean the weigher will prefer hosts in *other* cells from
  which the instance is currently running.

Related options:

* ``[filter_scheduler] weight_classes``
"""),
    cfg.BoolOpt(
        "shuffle_best_same_weighed_hosts",
        default=False,
        help="""
Enable spreading the instances between hosts with the same best weight.

Enabling it is beneficial for cases when ``[filter_scheduler]
host_subset_size`` is 1 (default), but there is a large number of hosts with
same maximal weight.  This scenario is common in Ironic deployments where there
are typically many baremetal nodes with identical weights returned to the
scheduler.  In such case enabling this option will reduce contention and
chances for rescheduling events.  At the same time it will make the instance
packing (even in unweighed case) less dense.
"""),
    cfg.StrOpt(
        "image_properties_default_architecture",
        choices=arch.ALL,
        help="""
The default architecture to be used when using the image properties filter.

When using the ``ImagePropertiesFilter``, it is possible that you want to
define a default architecture to make the user experience easier and avoid
having something like x86_64 images landing on AARCH64 compute nodes because
the user did not specify the ``hw_architecture`` property in Glance.

Possible values:

* CPU Architectures such as x86_64, aarch64, s390x.
"""),
    # TODO(mikal): replace this option with something involving host aggregates
    cfg.ListOpt("isolated_images",
        default=[],
        help="""
List of UUIDs for images that can only be run on certain hosts.

If there is a need to restrict some images to only run on certain designated
hosts, list those image UUIDs here.

Note that this setting only affects scheduling if the ``IsolatedHostsFilter``
filter is enabled.

Possible values:

* A list of UUID strings, where each string corresponds to the UUID of an
  image

Related options:

* ``[filter_scheduler] isolated_hosts``
* ``[filter_scheduler] restrict_isolated_hosts_to_isolated_images``
"""),
    cfg.ListOpt("isolated_hosts",
        default=[],
        help="""
List of hosts that can only run certain images.

If there is a need to restrict some images to only run on certain designated
hosts, list those host names here.

Note that this setting only affects scheduling if the ``IsolatedHostsFilter``
filter is enabled.

Possible values:

* A list of strings, where each string corresponds to the name of a host

Related options:

* ``[filter_scheduler] isolated_images``
* ``[filter_scheduler] restrict_isolated_hosts_to_isolated_images``
"""),
    cfg.BoolOpt(
        "restrict_isolated_hosts_to_isolated_images",
        default=True,
        help="""
Prevent non-isolated images from being built on isolated hosts.

Note that this setting only affects scheduling if the ``IsolatedHostsFilter``
filter is enabled. Even then, this option doesn't affect the behavior of
requests for isolated images, which will *always* be restricted to isolated
hosts.

Related options:

* ``[filter_scheduler] isolated_images``
* ``[filter_scheduler] isolated_hosts``
"""),
    # TODO(stephenfin): Consider deprecating these next two options: they're
    # effectively useless now that we don't support arbitrary image metadata
    # properties
    cfg.StrOpt(
        "aggregate_image_properties_isolation_namespace",
        help="""
Image property namespace for use in the host aggregate.

Images and hosts can be configured so that certain images can only be scheduled
to hosts in a particular aggregate. This is done with metadata values set on
the host aggregate that are identified by beginning with the value of this
option. If the host is part of an aggregate with such a metadata key, the image
in the request spec must have the value of that metadata in its properties in
order for the scheduler to consider the host as acceptable.

Note that this setting only affects scheduling if the
``AggregateImagePropertiesIsolation`` filter is enabled.

Possible values:

* A string, where the string corresponds to an image property namespace

Related options:

* ``[filter_scheduler] aggregate_image_properties_isolation_separator``
"""),
    cfg.StrOpt(
        "aggregate_image_properties_isolation_separator",
        default=".",
        help="""
Separator character(s) for image property namespace and name.

When using the aggregate_image_properties_isolation filter, the relevant
metadata keys are prefixed with the namespace defined in the
aggregate_image_properties_isolation_namespace configuration option plus a
separator. This option defines the separator to be used.

Note that this setting only affects scheduling if the
``AggregateImagePropertiesIsolation`` filter is enabled.

Possible values:

* A string, where the string corresponds to an image property namespace
  separator character

Related options:

* ``[filter_scheduler] aggregate_image_properties_isolation_namespace``
""")]

metrics_group = cfg.OptGroup(
    name="metrics",
    title="Metrics parameters",
    help="""
Configuration options for metrics

Options under this group allow to adjust how values assigned to metrics are
calculated.
""")

# TODO(stephenfin): This entire feature could probably be removed. It's not
# tested and likely doesn't work with most drivers now.
metrics_weight_opts = [
    cfg.FloatOpt("weight_multiplier",
        default=1.0,
        help="""
Multiplier used for weighing hosts based on reported metrics.

When using metrics to weight the suitability of a host, you can use this option
to change how the calculated weight influences the weight assigned to a host as
follows:

* ``>1.0``: increases the effect of the metric on overall weight
* ``1.0``: no change to the calculated weight
* ``>0.0,<1.0``: reduces the effect of the metric on overall weight
* ``0.0``: the metric value is ignored, and the value of the
  ``[metrics] weight_of_unavailable`` option is returned instead
* ``>-1.0,<0.0``: the effect is reduced and reversed
* ``-1.0``: the effect is reversed
* ``<-1.0``: the effect is increased proportionally and reversed

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* ``[filter_scheduler] weight_classes``
* ``[metrics] weight_of_unavailable``
"""),
    cfg.ListOpt("weight_setting",
        default=[],
        help="""
Mapping of metric to weight modifier.

This setting specifies the metrics to be weighed and the relative ratios for
each metric. This should be a single string value, consisting of a series of
one or more 'name=ratio' pairs, separated by commas, where ``name`` is the name
of the metric to be weighed, and ``ratio`` is the relative weight for that
metric.

Note that if the ratio is set to 0, the metric value is ignored, and instead
the weight will be set to the value of the ``[metrics] weight_of_unavailable``
option.

As an example, let's consider the case where this option is set to:

    ``name1=1.0, name2=-1.3``

The final weight will be:

    ``(name1.value * 1.0) + (name2.value * -1.3)``

Possible values:

* A list of zero or more key/value pairs separated by commas, where the key is
  a string representing the name of a metric and the value is a numeric weight
  for that metric. If any value is set to 0, the value is ignored and the
  weight will be set to the value of the ``[metrics] weight_of_unavailable``
  option.

Related options:

* ``[metrics] weight_of_unavailable``
"""),
    cfg.BoolOpt("required",
        default=True,
        help="""
Whether metrics are required.

This setting determines how any unavailable metrics are treated. If this option
is set to True, any hosts for which a metric is unavailable will raise an
exception, so it is recommended to also use the MetricFilter to filter out
those hosts before weighing.

Possible values:

* A boolean value, where False ensures any metric being unavailable for a host
  will set the host weight to ``[metrics] weight_of_unavailable``.

Related options:

* ``[metrics] weight_of_unavailable``
"""),
    cfg.FloatOpt("weight_of_unavailable",
        default=float(-10000.0),
        help="""
Default weight for unavailable metrics.

When any of the following conditions are met, this value will be used in place
of any actual metric value:

- One of the metrics named in ``[metrics] weight_setting`` is not available for
  a host, and the value of ``required`` is ``False``.
- The ratio specified for a metric in ``[metrics] weight_setting`` is 0.
- The ``[metrics] weight_multiplier`` option is set to 0.

Possible values:

* An integer or float value, where the value corresponds to the multipler
  ratio for this weigher.

Related options:

* ``[metrics] weight_setting``
* ``[metrics] required``
* ``[metrics] weight_multiplier``
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
    return {
        scheduler_group: scheduler_opts,
        filter_scheduler_group: filter_scheduler_opts,
        metrics_group: metrics_weight_opts,
    }
