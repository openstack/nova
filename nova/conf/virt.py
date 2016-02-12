# Copyright 2015 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

vcpu_pin_set = cfg.StrOpt(
    'vcpu_pin_set',
    help="""Defines which physical CPUs (pCPUs) can be used by instance
virtual CPUs (vCPUs).

Possible values:

* A comma-separated list of physical CPU numbers that virtual CPUs can be
  allocated to by default. Each element should be either a single CPU number,
  a range of CPU numbers, or a caret followed by a CPU number to be
  excluded from a previous range. For example:

    vcpu_pin_set = "4-12,^8,15"

Services which consume this:

* nova-scheduler
* nova-compute

Related options:

* None""")

compute_driver = cfg.StrOpt(
    'compute_driver',
    help='Driver to use for controlling virtualization. Options '
         'include: libvirt.LibvirtDriver, xenapi.XenAPIDriver, '
         'fake.FakeDriver, ironic.IronicDriver, '
         'vmwareapi.VMwareVCDriver, hyperv.HyperVDriver')

default_ephemeral_format = cfg.StrOpt(
    'default_ephemeral_format',
    help='The default format an ephemeral_volume will be '
         'formatted with on creation.')

preallocate_images = cfg.StrOpt(
    'preallocate_images',
    default='none',
    choices=('none', 'space'),
    help='VM image preallocation mode: '
         '"none" => no storage provisioning is done up front, '
         '"space" => storage is fully allocated at instance start')

use_cow_images = cfg.BoolOpt(
    'use_cow_images',
    default=True,
    help='Whether to use cow images')

vif_plugging_is_fatal = cfg.BoolOpt(
    'vif_plugging_is_fatal',
    default=True,
    help='Fail instance boot if vif plugging fails')

vif_plugging_timeout = cfg.IntOpt(
    'vif_plugging_timeout',
    default=300,
    help='Number of seconds to wait for neutron vif plugging '
         'events to arrive before continuing or failing (see '
         'vif_plugging_is_fatal). If this is set to zero and '
         'vif_plugging_is_fatal is False, events should not '
         'be expected to arrive at all.')

ALL_OPTS = [vcpu_pin_set,
            compute_driver,
            default_ephemeral_format,
            preallocate_images,
            use_cow_images,
            vif_plugging_is_fatal,
            vif_plugging_timeout]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    # TODO(sfinucan): This should be moved to a virt or hardware group
    return {'DEFAULT': ALL_OPTS}
