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
]


def register_opts(conf):
    conf.register_opts(compute_opts)


def list_opts():
    return {'DEFAULT': compute_opts}
