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

"""Validators for ``quota`` namespaced extra specs."""

from nova.api.validation.extra_specs import base


EXTRA_SPEC_VALIDATORS = []


# CPU, memory, disk IO and VIF quotas (VMWare)
for key, name, unit in (
    ('cpu', 'CPU', 'MHz'),
    ('memory', 'memory', 'MB'),
    ('disk_io', 'disk IO', 'I/O per second'),
    ('vif', 'virtual interface', 'Mbps'),
):
    EXTRA_SPEC_VALIDATORS.extend(
        [
            base.ExtraSpecValidator(
                name=f'quota:{key}_limit',
                description=(
                    f'The upper limit for {name} allocation in {unit}. '
                    f'The utilization of an instance will not exceed this '
                    f'limit, even if there are available resources. '
                    f'This is typically used to ensure a consistent '
                    f'performance of instances independent of available '
                    f'resources.'
                    f'The value ``0`` indicates that {name} usage is not '
                    f'limited.'
                    f'Only supported by the VMWare virt driver.'
                ),
                value={
                    'type': int,
                    'min': 0,
                },
            ),
            base.ExtraSpecValidator(
                name=f'quota:{key}_reservation',
                description=(
                    f'The guaranteed minimum {name} reservation in {unit}. '
                    f'This means the specified amount of {name} that will '
                    f'be guaranteed for the instance. '
                    f'Only supported by the VMWare virt driver.'
                ),
                value={
                    'type': int,
                },
            ),
            base.ExtraSpecValidator(
                name=f'quota:{key}_shares_level',
                description=(
                    f"The allocation level for {name}. If you choose "
                    f"'custom', set the number of {name} shares using "
                    f"'quota:{key}_shares_share'. "
                    f"Only supported by the VMWare virt driver."
                ),
                value={
                    'type': str,
                    'enum': ['custom', 'high', 'normal', 'low'],
                },
            ),
            base.ExtraSpecValidator(
                name=f'quota:{key}_shares_share',
                description=(
                    f"The number of shares of {name} allocated in the "
                    f"event that 'quota:{key}_shares_level=custom' is "
                    f"used. "
                    f"Ignored otherwise. "
                    f"There is no unit for this value: it is a relative "
                    f"measure based on the settings for other instances. "
                    f"Only supported by the VMWare virt driver."
                ),
                value={
                    'type': int,
                    'min': 0,
                },
            ),
        ]
    )


# CPU quotas (libvirt)
EXTRA_SPEC_VALIDATORS.extend(
    [
        base.ExtraSpecValidator(
            name='quota:cpu_shares',
            description=(
                'The proportional weighted share for the domain. '
                'If this element is omitted, the service defaults to the OS '
                'provided defaults. '
                'There is no unit for the value; it is a relative measure '
                'based on the setting of other VMs. '
                'For example, a VM configured with a value of 2048 gets '
                'twice as much CPU time as a VM configured with value 1024. '
                'Only supported by the libvirt virt driver.'
            ),
            value={
                'type': int,
                'min': 0,
            },
        ),
        base.ExtraSpecValidator(
            name='quota:cpu_period',
            description=(
                'Specifies the enforcement interval in microseconds. '
                'Within a period, each VCPU of the instance is not allowed '
                'to consume more than the quota worth of runtime. '
                'The value should be in range 1,000 - 1,000,000. '
                'A period with a value of 0 means no value. '
                'Only supported by the libvirt virt driver.'
            ),
            value={
                'type': int,
                'min': 0,
            },
        ),
        base.ExtraSpecValidator(
            name='quota:cpu_quota',
            description=(
                "The maximum allowed bandwidth in microseconds. "
                "Can be combined with 'quota:cpu_period' to limit an instance "
                "to a percentage of capacity of a physical CPU. "
                "The value should be in range 1,000 - 2^64 or negative. "
                "A negative value indicates that the instance has infinite "
                "bandwidth. "
                "Only supported by the libvirt virt driver."
            ),
            value={
                'type': int,
            },
        ),
    ]
)


# Disk quotas (libvirt, HyperV)
for stat in ('read', 'write', 'total'):
    for metric in ('bytes', 'iops'):
        EXTRA_SPEC_VALIDATORS.append(
            base.ExtraSpecValidator(
                name=f'quota:disk_{stat}_{metric}_sec',
                # NOTE(stephenfin): HyperV supports disk_total_{metric}_sec
                # too; update
                description=(
                    f'The quota {stat} {metric} for disk. '
                    f'Only supported by the libvirt virt driver.'
                ),
                value={
                    'type': int,
                    'min': 0,
                },
            )
        )


# VIF quotas (libvirt)
# TODO(stephenfin): Determine whether this should be deprecated now that
# nova-network is dead
for stat in ('inbound', 'outbound'):
    for metric in ('average', 'peak', 'burst'):
        EXTRA_SPEC_VALIDATORS.append(
            base.ExtraSpecValidator(
                name=f'quota:vif_{stat}_{metric}',
                description=(
                    f'The quota {stat} {metric} for VIF. Only supported '
                    f'by the libvirt virt driver.'
                ),
                value={
                    'type': int,
                    'min': 0,
                },
            )
        )


def register():
    return EXTRA_SPEC_VALIDATORS
