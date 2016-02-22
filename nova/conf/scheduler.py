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

DEFAULT_GROUP_NAME = "DEFAULT"
# The scheduler has options in several groups
METRICS_GROUP_NAME = "metrics"
TRUSTED_GROUP_NAME = "trusted_computing"
UPGRADE_GROUP_NAME = "upgrade_levels"


host_subset_size_opt = cfg.IntOpt("scheduler_host_subset_size",
        default=1,
        help="""
New instances will be scheduled on a host chosen randomly from a subset of the
N best hosts, where N is the value set by this option.  Valid values are 1 or
greater. Any value less than one will be treated as 1.

Setting this to a value greater than 1 will reduce the chance that multiple
scheduler processes handling similar requests will select the same host,
creating a potential race condition. By selecting a host randomly from the N
hosts that best fit the request, the chance of a conflict is reduced. However,
the higher you set this value, the less optimal the chosen host may be for a
given request.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

bm_default_filter_opt = cfg.ListOpt("baremetal_scheduler_default_filters",
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
        help="""
This option specifies the filters used for filtering baremetal hosts. The value
should be a list of strings, with each string being the name of a filter class
to be used. When used, they will be applied in order, so place your most
restrictive filters first to make the filtering process more efficient.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    If the 'scheduler_use_baremetal_filters' option is False, this option has
    no effect.
""")

use_bm_filters_opt = cfg.BoolOpt("scheduler_use_baremetal_filters",
        default=False,
        help="""
Set this to True to tell the nova scheduler that it should use the filters
specified in the 'baremetal_scheduler_default_filters' option. If you are not
scheduling baremetal nodes, leave this at the default setting of False.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    If this option is set to True, then the filters specified in the
    'baremetal_scheduler_default_filters' are used instead of the filters
    specified in 'scheduler_default_filters'.
""")

host_mgr_avail_filt_opt = cfg.MultiStrOpt("scheduler_available_filters",
        default=["nova.scheduler.filters.all_filters"],
        help="""
This is an unordered list of the filter classes the Nova scheduler may apply.
Only the filters specified in the 'scheduler_default_filters' option will be
used, but any filter appearing in that option must also be included in this
list.

By default, this is set to all filters that are included with Nova. If you wish
to change this, replace this with a list of strings, where each element is the
path to a filter.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    scheduler_default_filters
""")

host_mgr_default_filt_opt = cfg.ListOpt("scheduler_default_filters",
        default=[
          "RetryFilter",
          "AvailabilityZoneFilter",
          "RamFilter",
          "DiskFilter",
          "ComputeFilter",
          "ComputeCapabilitiesFilter",
          "ImagePropertiesFilter",
          "ServerGroupAntiAffinityFilter",
          "ServerGroupAffinityFilter",
          ],
        help="""
This option is the list of filter class names that will be used for filtering
hosts. The use of 'default' in the name of this option implies that other
filters may sometimes be used, but that is not the case. These filters will be
applied in the order they are listed, so place your most restrictive filters
first to make the filtering process more efficient.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    All of the filters in this option *must* be present in the
    'scheduler_available_filters' option, or a SchedulerHostFilterNotFound
    exception will be raised.
""")

host_mgr_sched_wgt_cls_opt = cfg.ListOpt("scheduler_weight_classes",
        default=["nova.scheduler.weights.all_weighers"],
        help="""
This is a list of weigher class names. Only hosts which pass the filters are
weighed. The weight for any host starts at 0, and the weighers order these
hosts by adding to or subtracting from the weight assigned by the previous
weigher. Weights may become negative.

An instance will be scheduled to one of the N most-weighted hosts, where N is
'scheduler_host_subset_size'.

By default, this is set to all weighers that are included with Nova. If you
wish to change this, replace this with a list of strings, where each element is
the path to a weigher.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

host_mgr_tracks_inst_chg_opt = cfg.BoolOpt("scheduler_tracks_instance_changes",
        default=True,
        help="""
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

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

rpc_sched_topic_opt = cfg.StrOpt("scheduler_topic",
        default="scheduler",
        help="""
This is the message queue topic that the scheduler 'listens' on. It is used
when the scheduler service is started up to configure the queue, and whenever
an RPC call to the scheduler is made. There is almost never any reason to ever
change this value.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

scheduler_json_config_location_opt = cfg.StrOpt(
        "scheduler_json_config_location",
        default="",
        help="""
The absolute path to the scheduler configuration JSON file, if any. This file
location is monitored by the scheduler for changes and reloads it if needed. It
is converted from JSON to a Python data structure, and passed into the
filtering and weighing functions of the scheduler, which can use it for dynamic
configuration.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

sched_driver_host_mgr_opt = cfg.StrOpt("scheduler_host_manager",
        default="host_manager",
        help="""
The scheduler host manager to use, which manages the in-memory picture of the
hosts that the scheduler uses.

The option value should be chosen from one of the entrypoints under the
namespace 'nova.scheduler.host_manager' of file 'setup.cfg'. For example,
'host_manager' is the default setting. Aside from the default, the only other
option as of the Mitaka release is 'ironic_host_manager', which should be used
if you're using Ironic to provision bare-metal instances.

This option also supports a full class path style, for example
"nova.scheduler.host_manager.HostManager", but note this support is deprecated
and will be dropped in the N release.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

driver_opt = cfg.StrOpt("scheduler_driver",
        default="filter_scheduler",
        help="""
The class of the driver used by the scheduler. This should be chosen from one
of the entrypoints under the namespace 'nova.scheduler.driver' of file
'setup.cfg'. If nothing is specified in this option, the 'filter_scheduler' is
used.

This option also supports deprecated full Python path to the class to be used.
For example, "nova.scheduler.filter_scheduler.FilterScheduler". But note: this
support will be dropped in the N Release.

Other options are:

    * 'caching_scheduler' which aggressively caches the system state for better
    individual scheduler performance at the risk of more retries when running
    multiple schedulers.

    * 'chance_scheduler' which simply picks a host at random.

    * 'fake_scheduler' which is used for testing.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

driver_period_opt = cfg.IntOpt("scheduler_driver_task_period",
        default=60,
        help="""
This value controls how often (in seconds) to run periodic tasks in the
scheduler. The specific tasks that are run for each period are determined by
the particular scheduler being used.

If this is larger than the nova-service 'service_down_time' setting, Nova may
report the scheduler service as down. This is because the scheduler driver is
responsible for sending a heartbeat and it will only do that as often as this
option allows. As each scheduler can work a little differently than the others,
be sure to test this with your selected scheduler.

* Services that use this:

    ``nova-scheduler``

* Related options:

    ``nova-service service_down_time``
""")

isolated_img_opt = cfg.ListOpt("isolated_images",
        default=[],
        help="""
If there is a need to restrict some images to only run on certain designated
hosts, list those image UUIDs here.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    scheduler/isolated_hosts
    scheduler/restrict_isolated_hosts_to_isolated_images
""")

isolated_host_opt = cfg.ListOpt("isolated_hosts",
        default=[],
        help="""
If there is a need to restrict some images to only run on certain designated
hosts, list those host names here.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    scheduler/isolated_images
    scheduler/restrict_isolated_hosts_to_isolated_images
""")

restrict_iso_host_img_opt = cfg.BoolOpt(
        "restrict_isolated_hosts_to_isolated_images",
        default=True,
        help="""
This setting determines if the scheduler's isolated_hosts filter will allow
non-isolated images on a host designated as an isolated host. When set to True
(the default), non-isolated images will not be allowed to be built on isolated
hosts. When False, non-isolated images can be built on both isolated and
non-isolated hosts alike.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'IsolatedHostsFilter' filter is enabled. Even
then, this option doesn't affect the behavior of requests for isolated images,
which will *always* be restricted to isolated hosts.

* Services that use this:

    ``nova-scheduler``

* Related options:

    scheduler/isolated_images
    scheduler/isolated_hosts
""")

# This option specifies an option group, so register separately
rpcapi_cap_opt = cfg.StrOpt("scheduler",
        help="""
Sets a version cap (limit) for messages sent to scheduler services. In the
situation where there were multiple scheduler services running, and they were
not being upgraded together, you would set this to the lowest deployed version
to guarantee that other services never send messages that any of your running
schedulers cannot understand.

This is rarely needed in practice as most deployments run a single scheduler.
It exists mainly for design compatibility with the other services, such as
compute, which are routinely upgraded in a rolling fashion.

* Services that use this:

    ``nova-compute, nova-conductor``

* Related options:

    None
""")

# These opts are registered as a separate OptGroup
trusted_opts = [
    cfg.StrOpt("attestation_server",
            help="""
The host to use as the attestation server.

Cloud computing pools can involve thousands of compute nodes located at
different geographical locations, making it difficult for cloud providers to
identify a node's trustworthiness. When using the Trusted filter, users can
request that their VMs only be placed on nodes that have been verified by the
attestation server specified in this option.

The value is a string, and can be either an IP address or FQDN.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server_ca_file
    attestation_port
    attestation_api_url
    attestation_auth_blob
    attestation_auth_timeout
    attestation_insecure_ssl
"""),
    cfg.StrOpt("attestation_server_ca_file",
            help="""
The absolute path to the certificate to use for authentication when connecting
to the attestation server. See the `attestation_server` help text for more
information about host verification.

The value is a string, and must point to a file that is readable by the
scheduler.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_port
    attestation_api_url
    attestation_auth_blob
    attestation_auth_timeout
    attestation_insecure_ssl
"""),
    cfg.StrOpt("attestation_port",
            default="8443",
            help="""
The port to use when connecting to the attestation server. See the
`attestation_server` help text for more information about host verification.

Valid values are strings, not integers, but must be digits only.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_server_ca_file
    attestation_api_url
    attestation_auth_blob
    attestation_auth_timeout
    attestation_insecure_ssl
"""),
    cfg.StrOpt("attestation_api_url",
            default="/OpenAttestationWebServices/V1.0",
            help="""
The URL on the attestation server to use. See the `attestation_server` help
text for more information about host verification.

This value must be just that path portion of the full URL, as it will be joined
to the host specified in the attestation_server option.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_server_ca_file
    attestation_port
    attestation_auth_blob
    attestation_auth_timeout
    attestation_insecure_ssl
"""),
    cfg.StrOpt("attestation_auth_blob",
            help="""
Attestation servers require a specific blob that is used to authenticate. The
content and format of the blob are determined by the particular attestation
server being used. There is no default value; you must supply the value as
specified by your attestation service. See the `attestation_server` help text
for more information about host verification.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_server_ca_file
    attestation_port
    attestation_api_url
    attestation_auth_timeout
    attestation_insecure_ssl
"""),
    cfg.IntOpt("attestation_auth_timeout",
            default=60,
            help="""
This value controls how long a successful attestation is cached. Once this
period has elapsed, a new attestation request will be made. See the
`attestation_server` help text for more information about host verification.

The value is in seconds. Valid values must be positive integers for any
caching; setting this to zero or a negative value will result in calls to the
attestation_server for every request, which may impact performance.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_server_ca_file
    attestation_port
    attestation_api_url
    attestation_auth_blob
    attestation_insecure_ssl
"""),
    cfg.BoolOpt("attestation_insecure_ssl",
            default=False,
            help="""
When set to True, the SSL certificate verification is skipped for the
attestation service. See the `attestation_server` help text for more
information about host verification.

Valid values are True or False. The default is False.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'TrustedFilter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    attestation_server
    attestation_server_ca_file
    attestation_port
    attestation_api_url
    attestation_auth_blob
    attestation_auth_timeout
"""),
]

max_io_ops_per_host_opt = cfg.IntOpt("max_io_ops_per_host",
        default=8,
        help="""
This setting caps the number of instances on a host that can be actively
performing IO (in a build, resize, snapshot, migrate, rescue, or unshelve task
state) before that host becomes ineligible to build new instances.

Valid values are positive integers: 1 or greater.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'io_ops_filter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

agg_img_prop_iso_namespace_opt = cfg.StrOpt(
        "aggregate_image_properties_isolation_namespace",
        help="""
Images and hosts can be configured so that certain images can only be scheduled
to hosts in a particular aggregate. This is done with metadata values set on
the host aggregate that are identified by beginning with the value of this
option. If the host is part of an aggregate with such a metadata key, the image
in the request spec must have the value of that metadata in its properties in
order for the scheduler to consider the host as acceptable.

Valid values are strings.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'aggregate_image_properties_isolation' filter is
enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    aggregate_image_properties_isolation_separator
""")

agg_img_prop_iso_separator_opt = cfg.StrOpt(
        "aggregate_image_properties_isolation_separator",
        default=".",
        help="""
When using the aggregate_image_properties_isolation filter, the relevant
metadata keys are prefixed with the namespace defined in the
aggregate_image_properties_isolation_namespace configuration option plus a
separator. This option defines the separator to be used. It defaults to a
period ('.').

Valid values are strings.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'aggregate_image_properties_isolation' filter is
enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    aggregate_image_properties_isolation_namespace
""")

max_instances_per_host_opt = cfg.IntOpt("max_instances_per_host",
        default=50,
        help="""
If you need to limit the number of instances on any given host, set this option
to the maximum number of instances you want to allow. The num_instances_filter
will reject any host that has at least as many instances as this option's
value.

Valid values are positive integers; setting it to zero will cause all hosts to
be rejected if the num_instances_filter is active.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect. Also note that this setting
only affects scheduling if the 'num_instances_filter' filter is enabled.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

ram_weight_mult_opt = cfg.FloatOpt("ram_weight_multiplier",
        default=1.0,
        help="""
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

Valid values are numeric, either integer or float.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

disk_weight_mult_opt = cfg.FloatOpt("disk_weight_multiplier",
        default=1.0,
        help="Multiplier used for weighing free disk space. Negative "
             "numbers mean to stack vs spread.")

io_ops_weight_mult_opt = cfg.FloatOpt("io_ops_weight_multiplier",
        default=-1.0,
        help="""
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

Valid values are numeric, either integer or float.

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

# These opts are registered as a separate OptGroup
metrics_weight_opts = [
     cfg.FloatOpt("weight_multiplier",
            default=1.0,
            help="""
When using metrics to weight the suitability of a host, you can use this option
to change how the calculated weight influences the weight assigned to a host as
follows:

    * Greater than 1.0: increases the effect of the metric on overall weight.

    * Equal to 1.0: No change to the calculated weight.

    * Less than 1.0, greater than 0: reduces the effect of the metric on
    overall weight.

    * 0: The metric value is ignored, and the value of the
    'weight_of_unavailable' option is returned instead.

    * Greater than -1.0, less than 0: the effect is reduced and reversed.

    * -1.0: the effect is reversed

    * Less than -1.0: the effect is increased proportionally and reversed.

Valid values are numeric, either integer or float.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    weight_of_unavailable
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

* Services that use this:

    ``nova-scheduler``

* Related options:

    weight_of_unavailable
"""),
    cfg.BoolOpt("required",
            default=True,
            help="""
This setting determines how any unavailable metrics are treated. If this option
is set to True, any hosts for which a metric is unavailable will raise an
exception, so it is recommended to also use the MetricFilter to filter out
those hosts before weighing.

When this option is False, any metric being unavailable for a host will set the
host weight to 'weight_of_unavailable'.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    weight_of_unavailable
"""),
    cfg.FloatOpt("weight_of_unavailable",
            default=float(-10000.0),
            help="""
When any of the following conditions are met, this value will be used in place
of any actual metric value:

    * One of the metrics named in 'weight_setting' is not available for a host,
    and the value of 'required' is False.

    * The ratio specified for a metric in 'weight_setting' is 0.

    * The 'weight_multiplier' option is set to 0.

This option is only used by the FilterScheduler and its subclasses; if you use
a different scheduler, this option has no effect.

* Services that use this:

    ``nova-scheduler``

* Related options:

    weight_setting
    required
    weight_multiplier
"""),
]

scheduler_max_att_opt = cfg.IntOpt("scheduler_max_attempts",
        default=3,
        help="""
This is the maximum number of attempts that will be made to schedule an
instance before it is assumed that the failures aren't due to normal occasional
race conflicts, but rather some other problem. When this is reached a
MaxRetriesExceeded exception is raised, and the instance is set to an error
state.

Valid values are positive integers (1 or greater).

* Services that use this:

    ``nova-scheduler``

* Related options:

    None
""")

soft_affinity_weight_opt = cfg.FloatOpt('soft_affinity_weight_multiplier',
            default=1.0,
            help='Multiplier used for weighing hosts '
                 'for group soft-affinity. Only a '
                 'positive value is meaningful. Negative '
                 'means that the behavior will change to '
                 'the opposite, which is soft-anti-affinity.')

soft_anti_affinity_weight_opt = cfg.FloatOpt(
    'soft_anti_affinity_weight_multiplier',
                 default=1.0,
                 help='Multiplier used for weighing hosts '
                      'for group soft-anti-affinity. Only a '
                      'positive value is meaningful. Negative '
                      'means that the behavior will change to '
                      'the opposite, which is soft-affinity.')


default_opts = [host_subset_size_opt,
               bm_default_filter_opt,
               use_bm_filters_opt,
               host_mgr_avail_filt_opt,
               host_mgr_default_filt_opt,
               host_mgr_sched_wgt_cls_opt,
               host_mgr_tracks_inst_chg_opt,
               rpc_sched_topic_opt,
               sched_driver_host_mgr_opt,
               driver_opt,
               driver_period_opt,
               scheduler_json_config_location_opt,
               isolated_img_opt,
               isolated_host_opt,
               restrict_iso_host_img_opt,
               max_io_ops_per_host_opt,
               agg_img_prop_iso_namespace_opt,
               agg_img_prop_iso_separator_opt,
               max_instances_per_host_opt,
               ram_weight_mult_opt,
               disk_weight_mult_opt,
               io_ops_weight_mult_opt,
               scheduler_max_att_opt,
               soft_affinity_weight_opt,
               soft_anti_affinity_weight_opt,
              ]


def register_opts(conf):
    conf.register_opts(default_opts)
    conf.register_opt(rpcapi_cap_opt, UPGRADE_GROUP_NAME)
    trust_group = cfg.OptGroup(name=TRUSTED_GROUP_NAME,
                               title="Trust parameters")
    conf.register_group(trust_group)
    conf.register_opts(trusted_opts, group=trust_group)
    conf.register_opts(metrics_weight_opts, group=METRICS_GROUP_NAME)


def list_opts():
    return {DEFAULT_GROUP_NAME: default_opts,
            UPGRADE_GROUP_NAME: [rpcapi_cap_opt],
            TRUSTED_GROUP_NAME: trusted_opts,
            METRICS_GROUP_NAME: metrics_weight_opts,
            }
