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

from oslo_config import cfg

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
    cfg.ListOpt('compute_resources',
                default=[],
                help='DEPRECATED:The names of the extra resources to track. '
                     'The Extensible Resource Tracker is deprecated and will '
                     'be removed in the 14.0.0 release. If you '
                     'use this functionality and have custom resources that '
                     'are managed by the Extensible Resource Tracker, please '
                     'contact the Nova development team by posting to the '
                     'openstack-dev mailing list. There is no future planned '
                     'support for the tracking of custom resources.',
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

ALL_OPTS = itertools.chain(
           compute_opts,
           resource_tracker_opts,
           allocation_ratio_opts
           )


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
