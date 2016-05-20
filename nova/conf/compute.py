# Copyright 2015 Huawei Technology corp.
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
import socket

from oslo_config import cfg

from nova.conf import paths

compute_opts = [
    cfg.BoolOpt('allow_resize_to_same_host',
                default=False,
                help='Allow destination machine to match source for resize. '
                     'Useful when testing in single-host environments.'),
    cfg.StrOpt('default_schedule_zone',
               help='Availability zone to use when user doesn\'t specify one'),
    cfg.ListOpt('non_inheritable_image_properties',
                default=['cache_in_nova',
                         'bittorrent'],
                help='These are image properties which a snapshot should not'
                     ' inherit from an instance'),
    cfg.StrOpt('null_kernel',
               default='nokernel',
               help='Kernel image that indicates not to use a kernel, but to '
                    'use a raw disk image instead'),
    cfg.StrOpt('multi_instance_display_name_template',
               default='%(name)s-%(count)d',
               help='When creating multiple instances with a single request '
                    'using the os-multiple-create API extension, this '
                    'template will be used to build the display name for '
                    'each instance. The benefit is that the instances '
                    'end up with different hostnames. To restore legacy '
                    'behavior of every instance having the same name, set '
                    'this option to "%(name)s".  Valid keys for the '
                    'template are: name, uuid, count.'),
    cfg.IntOpt('max_local_block_devices',
               default=3,
               help='Maximum number of devices that will result '
                    'in a local image being created on the hypervisor node. '
                    'A negative number means unlimited. Setting '
                    'max_local_block_devices to 0 means that any request that '
                    'attempts to create a local disk will fail. This option '
                    'is meant to limit the number of local discs (so root '
                    'local disc that is the result of --image being used, and '
                    'any other ephemeral and swap disks). 0 does not mean '
                    'that images will be automatically converted to volumes '
                    'and boot instances from volumes - it just means that all '
                    'requests that attempt to create a local disk will fail.'),
    cfg.MultiStrOpt('compute_available_monitors',
                    deprecated_for_removal=True,
                    help='Monitor classes available to the compute which may '
                         'be specified more than once. This option is '
                         'DEPRECATED and no longer used. Use setuptools entry '
                         'points to list available monitor plugins.'),
    cfg.ListOpt('compute_monitors',
                default=[],
                help='A list of monitors that can be used for getting '
                     'compute metrics. You can use the alias/name from '
                     'the setuptools entry points for nova.compute.monitors.* '
                     'namespaces. If no namespace is supplied, the "cpu." '
                     'namespace is assumed for backwards-compatibility. '
                     'An example value that would enable both the CPU and '
                     'NUMA memory bandwidth monitors that used the virt '
                     'driver variant: '
                     '["cpu.virt_driver", "numa_mem_bw.virt_driver"]'),
]

resource_tracker_opts = [
    cfg.IntOpt('reserved_host_disk_mb',
               default=0,
               help='Amount of disk in MB to reserve for the host'),
    cfg.IntOpt('reserved_host_memory_mb',
               default=512,
               help='Amount of memory in MB to reserve for the host'),
    cfg.StrOpt('compute_stats_class',
               default='nova.compute.stats.Stats',
               help='DEPRECATED: Class that will manage stats for the '
                    'local compute host',
               deprecated_for_removal=True),
]

allocation_ratio_opts = [
    cfg.FloatOpt('cpu_allocation_ratio',
        default=0.0,
        help='Virtual CPU to physical CPU allocation ratio which affects '
             'all CPU filters. This configuration specifies a global ratio '
             'for CoreFilter. For AggregateCoreFilter, it will fall back to '
             'this configuration value if no per-aggregate setting found. '
             'NOTE: This can be set per-compute, or if set to 0.0, the value '
             'set on the scheduler node(s) will be used '
             'and defaulted to 16.0'),
    cfg.FloatOpt('ram_allocation_ratio',
        default=0.0,
        help='Virtual ram to physical ram allocation ratio which affects '
             'all ram filters. This configuration specifies a global ratio '
             'for RamFilter. For AggregateRamFilter, it will fall back to '
             'this configuration value if no per-aggregate setting found. '
             'NOTE: This can be set per-compute, or if set to 0.0, the value '
             'set on the scheduler node(s) will be used '
             'and defaulted to 1.5'),
    cfg.FloatOpt('disk_allocation_ratio',
        default=0.0,
        help='This is the virtual disk to physical disk allocation ratio used '
             'by the disk_filter.py script to determine if a host has '
             'sufficient disk space to fit a requested instance. A ratio '
             'greater than 1.0 will result in over-subscription of the '
             'available physical disk, which can be useful for more '
             'efficiently packing instances created with images that do not '
             'use the entire virtual disk,such as sparse or compressed '
             'images. It can be set to a value between 0.0 and 1.0 in order '
             'to preserve a percentage of the disk for uses other than '
             'instances.'
             'NOTE: This can be set per-compute, or if set to 0.0, the value '
             'set on the scheduler node(s) will be used '
             'and defaulted to 1.0'),
]

compute_manager_opts = [
    cfg.StrOpt('console_host',
               default=socket.gethostname(),
               help='Console proxy host to use to connect '
                    'to instances on this host.'),
    cfg.StrOpt('default_access_ip_network_name',
               help='Name of network to use to set access IPs for instances'),
    cfg.BoolOpt('defer_iptables_apply',
                default=False,
                help='Whether to batch up the application of IPTables rules'
                     ' during a host restart and apply all at the end of the'
                     ' init phase'),
    cfg.StrOpt('instances_path',
               default=paths.state_path_def('instances'),
               help='Where instances are stored on disk'),
    cfg.BoolOpt('instance_usage_audit',
                default=False,
                help="Generate periodic compute.instance.exists"
                     " notifications"),
    cfg.IntOpt('live_migration_retry_count',
               default=30,
               help="Number of 1 second retries needed in live_migration"),
    cfg.BoolOpt('resume_guests_state_on_host_boot',
                default=False,
                help='Whether to start guests that were running before the '
                     'host rebooted'),
    cfg.IntOpt('network_allocate_retries',
               default=0,
               help="Number of times to retry network allocation on failures"),
    cfg.IntOpt('max_concurrent_builds',
               default=10,
               help='Maximum number of instance builds to run concurrently'),
    cfg.IntOpt('max_concurrent_live_migrations',
               default=1,
               help='Maximum number of live migrations to run concurrently. '
                    'This limit is enforced to avoid outbound live migrations '
                    'overwhelming the host/network and causing failures. It '
                    'is not recommended that you change this unless you are '
                    'very sure that doing so is safe and stable in your '
                    'environment.'),
    cfg.IntOpt('block_device_allocate_retries',
               default=60,
               help='Number of times to retry block device '
                    'allocation on failures.\n'
                    'Starting with Liberty, Cinder can use image volume '
                    'cache. This may help with block device allocation '
                    'performance. Look at the cinder '
                    'image_volume_cache_enabled configuration option.')
]

interval_opts = [
    cfg.IntOpt('bandwidth_poll_interval',
               default=600,
               help='Interval to pull network bandwidth usage info. Not '
                    'supported on all hypervisors. Set to -1 to disable. '
                    'Setting this to 0 will run at the default rate.'),
    cfg.IntOpt('sync_power_state_interval',
               default=600,
               help='Interval to sync power states between the database and '
                    'the hypervisor. Set to -1 to disable. '
                    'Setting this to 0 will run at the default rate.'),
    cfg.IntOpt("heal_instance_info_cache_interval",
               default=60,
               help="Number of seconds between instance network information "
                    "cache updates"),
    cfg.IntOpt('reclaim_instance_interval',
               min=0,
               default=0,
               help='Interval in seconds for reclaiming deleted instances. '
                    'It takes effect only when value is greater than 0.'),
    cfg.IntOpt('volume_usage_poll_interval',
               default=0,
               help='Interval in seconds for gathering volume usages'),
    cfg.IntOpt('shelved_poll_interval',
               default=3600,
               help='Interval in seconds for polling shelved instances to '
                    'offload. Set to -1 to disable.'
                    'Setting this to 0 will run at the default rate.'),
    cfg.IntOpt('shelved_offload_time',
               default=0,
               help='Time in seconds before a shelved instance is eligible '
                    'for removing from a host. -1 never offload, 0 offload '
                    'immediately when shelved'),
    cfg.IntOpt('instance_delete_interval',
               default=300,
               help='Interval in seconds for retrying failed instance file '
                    'deletes. Set to -1 to disable. '
                    'Setting this to 0 will run at the default rate.'),
    cfg.IntOpt('block_device_allocate_retries_interval',
               default=3,
               help='Waiting time interval (seconds) between block'
                    ' device allocation retries on failures'),
    cfg.IntOpt('scheduler_instance_sync_interval',
               default=120,
               help='Waiting time interval (seconds) between sending the '
                    'scheduler a list of current instance UUIDs to verify '
                    'that its view of instances is in sync with nova. If the '
                    'CONF option `scheduler_tracks_instance_changes` is '
                    'False, changing this option will have no effect.'),
    cfg.IntOpt('update_resources_interval',
               default=0,
               help='Interval in seconds for updating compute resources. A '
                    'number less than 0 means to disable the task completely. '
                    'Leaving this at the default of 0 will cause this to run '
                    'at the default periodic interval. Setting it to any '
                    'positive value will cause it to run at approximately '
                    'that number of seconds.'),
]

timeout_opts = [
    cfg.IntOpt("reboot_timeout",
               default=0,
               help="Automatically hard reboot an instance if it has been "
                    "stuck in a rebooting state longer than N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("instance_build_timeout",
               default=0,
               help="Amount of time in seconds an instance can be in BUILD "
                    "before going into ERROR status. "
                    "Set to 0 to disable."),
    cfg.IntOpt("rescue_timeout",
               default=0,
               help="Automatically unrescue an instance after N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("resize_confirm_window",
               default=0,
               help="Automatically confirm resizes after N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("shutdown_timeout",
               default=60,
               help="Total amount of time to wait in seconds for an instance "
                    "to perform a clean shutdown."),
]

running_deleted_opts = [
    cfg.StrOpt("running_deleted_instance_action",
               default="reap",
               choices=('noop', 'log', 'shutdown', 'reap'),
               help="Action to take if a running deleted instance is detected."
                    "Set to 'noop' to take no action."),
    cfg.IntOpt("running_deleted_instance_poll_interval",
               default=1800,
               help="Number of seconds to wait between runs of the cleanup "
                    "task."),
    cfg.IntOpt("running_deleted_instance_timeout",
               default=0,
               help="Number of seconds after being deleted when a running "
                    "instance should be considered eligible for cleanup."),
]

instance_cleaning_opts = [
    cfg.IntOpt('maximum_instance_delete_attempts',
               default=5,
               help='The number of times to attempt to reap an instance\'s '
                    'files.'),
]

rpcapi_opts = [
    cfg.StrOpt("compute_topic",
            default="compute",
            help="""
This is the message queue topic that the compute service 'listens' on. It is
used when the compute service is started up to configure the queue, and
whenever an RPC call to the compute service is made.

* Possible values:

    Any string, but there is almost never any reason to ever change this value
    from its default of 'compute'.

* Services that use this:

    ``nova-compute``

* Related options:

    None
"""),
]

db_opts = [
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
               default='',
               help='When set, compute API will consider duplicate hostnames '
                    'invalid within the specified scope, regardless of case. '
                    'Should be empty, "project" or "global".'),
    cfg.BoolOpt('enable_new_services',
                default=True,
                help='Services to be added to the available pool on create'),
    cfg.StrOpt('instance_name_template',
               default='instance-%08x',
               help='Template string to be used to generate instance names'),
    cfg.StrOpt('snapshot_name_template',
               default='snapshot-%s',
               help='Template string to be used to generate snapshot names'),
]

ALL_OPTS = list(itertools.chain(
           compute_opts,
           resource_tracker_opts,
           allocation_ratio_opts,
           compute_manager_opts,
           interval_opts,
           timeout_opts,
           running_deleted_opts,
           instance_cleaning_opts,
           rpcapi_opts,
           db_opts,
           ))


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
