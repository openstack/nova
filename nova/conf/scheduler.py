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


host_subset_size_opt = cfg.IntOpt("scheduler_host_subset_size",
        default=1,
        help="New instances will be scheduled on a host chosen randomly from "
             "a subset of the N best hosts. This property defines the subset "
             "size that a host is chosen from. A value of 1 chooses the first "
             "host returned by the weighing functions.  This value must be at "
             "least 1. Any value less than 1 will be ignored, and 1 will be "
             "used instead")

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
        help="Which filter class names to use for filtering baremetal hosts "
             "when not specified in the request.")

use_bm_filters_opt = cfg.BoolOpt("scheduler_use_baremetal_filters",
        default=False,
        help="Flag to decide whether to use "
             "baremetal_scheduler_default_filters or not.")

host_mgr_avail_filt_opt = cfg.MultiStrOpt("scheduler_available_filters",
        default=["nova.scheduler.filters.all_filters"],
        help="Filter classes available to the scheduler which may be "
             "specified more than once.  An entry of "
             "'nova.scheduler.filters.all_filters' maps to all filters "
             "included with nova.")

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
        help="Which filter class names to use for filtering hosts when not "
             "specified in the request.")

host_mgr_sched_wgt_cls_opt = cfg.ListOpt("scheduler_weight_classes",
        default=["nova.scheduler.weights.all_weighers"],
        help="Which weight class names to use for weighing hosts")

host_mgr_tracks_inst_chg_opt = cfg.BoolOpt("scheduler_tracks_instance_changes",
        default=True,
        help="Determines if the Scheduler tracks changes to instances to help "
             "with its filtering decisions.")

rpc_sched_topic_opt = cfg.StrOpt("scheduler_topic",
        default="scheduler",
        help="The topic scheduler nodes listen on")

# This option specifies an option group, so register separately
rpcapi_cap_opt = cfg.StrOpt("scheduler",
        help="Set a version cap for messages sent to scheduler services")

scheduler_json_config_location_opt = cfg.StrOpt(
        "scheduler_json_config_location",
        default="",
        help="Absolute path to scheduler configuration JSON file.")

sched_driver_host_mgr_opt = cfg.StrOpt("scheduler_host_manager",
        default="nova.scheduler.host_manager.HostManager",
        help="The scheduler host manager class to use")

driver_opt = cfg.StrOpt("scheduler_driver",
        default="nova.scheduler.filter_scheduler.FilterScheduler",
        help="Default driver to use for the scheduler")

driver_period_opt = cfg.IntOpt("scheduler_driver_task_period",
        default=60,
        help="How often (in seconds) to run periodic tasks in the scheduler "
             "driver of your choice. Please note this is likely to interact "
             "with the value of service_down_time, but exactly how they "
             "interact will depend on your choice of scheduler driver.")

disk_allocation_ratio_opt = cfg.FloatOpt("disk_allocation_ratio",
        default=1.0,
        help="Virtual disk to physical disk allocation ratio")

isolated_img_opt = cfg.ListOpt("isolated_images",
        default=[],
        help="Images to run on isolated host")

isolated_host_opt = cfg.ListOpt("isolated_hosts",
        default=[],
        help="Host reserved for specific images")

restrict_iso_host_img_opt = cfg.BoolOpt(
        "restrict_isolated_hosts_to_isolated_images",
        default=True,
        help="Whether to force isolated hosts to run only isolated images")

# These opts are registered as a separate OptGroup
trusted_opts = [
    cfg.StrOpt("attestation_server",
            help="Attestation server HTTP"),
    cfg.StrOpt("attestation_server_ca_file",
            help="Attestation server Cert file for Identity verification"),
    cfg.StrOpt("attestation_port",
            default="8443",
            help="Attestation server port"),
    cfg.StrOpt("attestation_api_url",
            default="/OpenAttestationWebServices/V1.0",
            help="Attestation web API URL"),
    cfg.StrOpt("attestation_auth_blob",
            help="Attestation authorization blob - must change"),
    cfg.IntOpt("attestation_auth_timeout",
            default=60,
            help="Attestation status cache valid period length"),
    cfg.BoolOpt("attestation_insecure_ssl",
            default=False,
            help="Disable SSL cert verification for Attestation service")
]

max_io_ops_per_host_opt = cfg.IntOpt("max_io_ops_per_host",
        default=8,
        help="Tells filters to ignore hosts that have this many or more "
             "instances currently in build, resize, snapshot, migrate, rescue "
             "or unshelve task states")

agg_img_prop_iso_namespace_opt = cfg.StrOpt(
        "aggregate_image_properties_isolation_namespace",
        help="Force the filter to consider only keys matching the given "
             "namespace.")

agg_img_prop_iso_separator_opt = cfg.StrOpt(
        "aggregate_image_properties_isolation_separator",
        default=".",
        help="The separator used between the namespace and keys")

max_instances_per_host_opt = cfg.IntOpt("max_instances_per_host",
        default=50,
        help="Ignore hosts that have too many instances")

ram_weight_mult_opt = cfg.FloatOpt("ram_weight_multiplier",
        default=1.0,
        help="Multiplier used for weighing ram. Negative numbers mean to "
             "stack vs spread.")

io_ops_weight_mult_opt = cfg.FloatOpt("io_ops_weight_multiplier",
        default=-1.0,
        help="Multiplier used for weighing host io ops. Negative numbers mean "
             "a preference to choose light workload compute hosts.")

# These opts are registered as a separate OptGroup
metrics_weight_opts = [
     cfg.FloatOpt("weight_multiplier",
            default=1.0,
            help="Multiplier used for weighing metrics."),
     cfg.ListOpt("weight_setting",
            default=[],
            help="How the metrics are going to be weighed. This should be in "
                 "the form of '<name1>=<ratio1>, <name2>=<ratio2>, ...', "
                 "where <nameX> is one of the metrics to be weighed, and "
                 "<ratioX> is the corresponding ratio. So for "
                 "'name1=1.0, name2=-1.0' The final weight would be "
                 "name1.value * 1.0 + name2.value * -1.0."),
    cfg.BoolOpt("required",
            default=True,
            help="How to treat the unavailable metrics. When a metric is NOT "
                 "available for a host, if it is set to be True, it would "
                 "raise an exception, so it is recommended to use the "
                 "scheduler filter MetricFilter to filter out those hosts. If "
                 "it is set to be False, the unavailable metric would be "
                 "treated as a negative factor in weighing process, the "
                 "returned value would be set by the option "
                 "weight_of_unavailable."),
    cfg.FloatOpt("weight_of_unavailable",
            default=float(-10000.0),
            help="The final weight value to be returned if required is set to "
                 "False and any one of the metrics set by weight_setting is "
                 "unavailable."),
]

scheduler_max_att_opt = cfg.IntOpt("scheduler_max_attempts",
            default=3,
            min=1,
            help="Maximum number of attempts to schedule an instance")

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


SIMPLE_OPTS = [host_subset_size_opt,
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
               disk_allocation_ratio_opt,
               isolated_img_opt,
               isolated_host_opt,
               restrict_iso_host_img_opt,
               max_io_ops_per_host_opt,
               agg_img_prop_iso_namespace_opt,
               agg_img_prop_iso_separator_opt,
               max_instances_per_host_opt,
               ram_weight_mult_opt,
               io_ops_weight_mult_opt,
               scheduler_max_att_opt,
               soft_affinity_weight_opt,
               soft_anti_affinity_weight_opt,
              ]

ALL_OPTS = itertools.chain(
        SIMPLE_OPTS,
        [rpcapi_cap_opt],
        trusted_opts,
        metrics_weight_opts,
        )


def register_opts(conf):
    conf.register_opts(SIMPLE_OPTS)
    conf.register_opt(rpcapi_cap_opt, "upgrade_levels")
    trust_group = cfg.OptGroup(name="trusted_computing",
                               title="Trust parameters")
    conf.register_group(trust_group)
    conf.register_opts(trusted_opts, group=trust_group)
    conf.register_opts(metrics_weight_opts, group="metrics")


def list_opts():
    return {"DEFAULT": SIMPLE_OPTS,
            "upgrade_levels": [rpcapi_cap_opt],
            "trusted_computing": trusted_opts,
            "metrics": metrics_weight_opts,
            }
