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
    help='Defines which pcpus that instance vcpus can use. For example, '
    '"4-12,^8,15"')


ALL_OPTS = [vcpu_pin_set]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    # TODO(sfinucan): This should be moved to a virt or hardware group
    return ('DEFAULT', ALL_OPTS)
