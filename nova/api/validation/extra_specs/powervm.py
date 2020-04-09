# Copyright 2020 Red Hat, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Validators for ``powervm`` namespaced extra specs.

These were all taken from the IBM documentation.

https://www.ibm.com/support/knowledgecenter/SSXK2N_1.4.4/com.ibm.powervc.standard.help.doc/powervc_pg_flavorsextraspecs_hmc.html
"""

from nova.api.validation.extra_specs import base


# TODO(stephenfin): A lot of these seem to overlap with existing 'hw:' extra
# specs and could be deprecated in favour of those.
EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='powervm:min_mem',
        description=(
            'Minimum memory (MB). If you do not specify the value, the value '
            'is defaulted to the value for ``memory_mb``.'
        ),
        value={
            'type': int,
            'min': 256,
            'description': 'Integer >=256 divisible by LMB size of the target',
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:max_mem',
        description=(
            'Maximum memory (MB). If you do not specify the value, the value '
            'is defaulted to the value for ``memory_mb``.'
        ),
        value={
            'type': int,
            'min': 256,
            'description': 'Integer >=256 divisible by LMB size of the target',
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:min_vcpu',
        description=(
            'Minimum virtual processors. Minimum resource that is required '
            'for LPAR to boot is 1. The maximum value can be equal to the '
            'value, which is set to vCPUs. If you specify the value of the '
            'attribute, you must also specify value of powervm:max_vcpu. '
            'Defaults to value set for vCPUs.'
        ),
        value={
            'type': int,
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:max_vcpu',
        description=(
            'Minimum virtual processors. Minimum resource that is required '
            'for LPAR to boot is 1. The maximum value can be equal to the '
            'value, which is set to vCPUs. If you specify the value of the '
            'attribute, you must also specify value of powervm:max_vcpu. '
            'Defaults to value set for vCPUs.'
        ),
        value={
            'type': int,
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:proc_units',
        description=(
            'The wanted ``proc_units``. The value for the attribute cannot be '
            'less than 1/10 of the value that is specified for Virtual '
            'CPUs (vCPUs) for hosts with firmware level 7.5 or earlier and '
            '1/20 of the value that is specified for vCPUs for hosts with '
            'firmware level 7.6 or later. If the value is not specified '
            'during deployment, it is defaulted to vCPUs * 0.5.'
        ),
        value={
            'type': str,
            'pattern': r'\d+\.\d+',
            'description': (
                'Float (divisible by 0.1 for hosts with firmware level 7.5 or '
                'earlier and 0.05 for hosts with firmware level 7.6 or later)'
            ),
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:min_proc_units',
        description=(
            'Minimum ``proc_units``. The minimum value for the attribute is '
            '0.1 for hosts with firmware level 7.5 or earlier and 0.05 for '
            'hosts with firmware level 7.6 or later. The maximum value must '
            'be equal to the maximum value of ``powervm:proc_units``. If you '
            'specify the attribute, you must also specify '
            '``powervm:proc_units``, ``powervm:max_proc_units``, '
            '``powervm:min_vcpu``, `powervm:max_vcpu``, and '
            '``powervm:dedicated_proc``. Set the ``powervm:dedicated_proc`` '
            'to false.'
            '\n'
            'The value for the attribute cannot be less than 1/10 of the '
            'value that is specified for powervm:min_vcpu for hosts with '
            'firmware level 7.5 or earlier and 1/20 of the value that is '
            'specified for ``powervm:min_vcpu`` for hosts with firmware '
            'level 7.6 or later. If you do not specify the value of the '
            'attribute during deployment, it is defaulted to equal the value '
            'of ``powervm:proc_units``.'
        ),
        value={
            'type': str,
            'pattern': r'\d+\.\d+',
            'description': (
                'Float (divisible by 0.1 for hosts with firmware level 7.5 or '
                'earlier and 0.05 for hosts with firmware level 7.6 or later)'
            ),
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:max_proc_units',
        description=(
            'Maximum ``proc_units``. The minimum value can be equal to `` '
            '``powervm:proc_units``. The maximum value for the attribute '
            'cannot be more than the value of the host for maximum allowed '
            'processors per partition. If you specify this attribute, you '
            'must also specify ``powervm:proc_units``, '
            '``powervm:min_proc_units``, ``powervm:min_vcpu``, '
            '``powervm:max_vcpu``, and ``powervm:dedicated_proc``. Set the '
            '``powervm:dedicated_proc`` to false.'
            '\n'
            'The value for the attribute cannot be less than 1/10 of the '
            'value that is specified for powervm:max_vcpu for hosts with '
            'firmware level 7.5 or earlier and 1/20 of the value that is '
            'specified for ``powervm:max_vcpu`` for hosts with firmware '
            'level 7.6 or later. If you do not specify the value of the '
            'attribute during deployment, the value is defaulted to equal the '
            'value of ``powervm:proc_units``.'
        ),
        value={
            'type': str,
            'pattern': r'\d+\.\d+',
            'description': (
                'Float (divisible by 0.1 for hosts with firmware level 7.5 or '
                'earlier and 0.05 for hosts with firmware level 7.6 or later)'
            ),
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:dedicated_proc',
        description=(
            'Use dedicated processors. The attribute defaults to false.'
        ),
        value={
            'type': bool,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:shared_weight',
        description=(
            'Shared processor weight. When ``powervm:dedicated_proc`` is set '
            'to true and ``powervm:uncapped`` is also set to true, the value '
            'of the attribute defaults to 128.'
        ),
        value={
            'type': int,
            'min': 0,
            'max': 255,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:availability_priority',
        description=(
            'Availability priority. The attribute priority of the server if '
            'there is a processor failure and there are not enough resources '
            'for all servers. VIOS and i5 need to remain high priority '
            'default of 191. The value of the attribute defaults to 128.'
        ),
        value={
            'type': int,
            'min': 0,
            'max': 255,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:uncapped',
        description=(
            'LPAR can use unused processor cycles that are beyond or exceed '
            'the wanted setting of the attribute. This attribute is '
            'supported only when ``powervm:dedicated_proc`` is set to false. '
            'When ``powervm:dedicated_proc`` is set to false, '
            '``powervm:uncapped`` defaults to true.'
        ),
        value={
            'type': bool,
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:dedicated_sharing_mode',
        description=(
            'Sharing mode for dedicated processors. The attribute is '
            'supported only when ``powervm:dedicated_proc`` is set to true.'
        ),
        value={
            'type': str,
            'enum': (
                'share_idle_procs',
                'keep_idle_procs',
                'share_idle_procs_active',
                'share_idle_procs_always',
            )
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:processor_compatibility',
        description=(
            'A processor compatibility mode is a value that is assigned to a '
            'logical partition by the hypervisor that specifies the processor '
            'environment in which the logical partition can successfully '
            'operate.'
        ),
        value={
            'type': str,
            'enum': (
                'default',
                'POWER6',
                'POWER6+',
                'POWER6_Enhanced',
                'POWER6+_Enhanced',
                'POWER7',
                'POWER8'
            ),
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:shared_proc_pool_name',
        description=(
            'Specifies the shared processor pool to be targeted during '
            'deployment of a virtual machine.'
        ),
        value={
            'type': str,
            'description': 'String with upper limit of 14 characters',
        },
    ),
    base.ExtraSpecValidator(
        name='powervm:srr_capability',
        description=(
            'If the value of simplified remote restart capability is set to '
            'true for the LPAR, you can remote restart the LPAR to supported '
            'CEC or host when the source CEC or host is down. The attribute '
            'defaults to false.'
        ),
        value={
            'type': bool,
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
