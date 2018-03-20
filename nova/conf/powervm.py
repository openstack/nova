# Copyright 2018 IBM Corporation
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


powervm_group = cfg.OptGroup(
    name="powervm",
    title="PowerVM Options",
    help="""PowerVM options allow cloud administrators to configure how
         OpenStack will work with the PowerVM hypervisor.
         """
)

powervm_opts = [
    cfg.FloatOpt(
        'proc_units_factor',
        default=0.1,
        min=0.05,
        max=1,
        help="""Factor used to calculate the amount of physical processor
             compute power given to each vCPU. E.g. A value of 1.0 means a
             whole physical processor, whereas 0.05 means 1/20th of a physical
             processor.
             """
    ),
]


def register_opts(conf):
    conf.register_group(powervm_group)
    conf.register_opts(powervm_opts, group=powervm_group)


def list_opts():
    return {powervm_group: powervm_opts}
