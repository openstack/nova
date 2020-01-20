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
for resource in ('cpu', 'memory', 'disk_io', 'vif'):
    for key, fmt in (
            ('limit', int),
            ('reservation', int),
            ('shares_level', str),
            ('shares_share', int)
        ):
        EXTRA_SPEC_VALIDATORS.append(
            base.ExtraSpecValidator(
                name=f'quota:{resource}_{key}',
                description=(
                    'The {} for {}. Only supported by the VMWare virt '
                    'driver.'.format(' '.join(key.split('_')), resource)
                ),
                value={
                    'type': fmt,
                },
            )
        )


# CPU quotas (libvirt)
for key in ('shares', 'period', 'quota'):
    EXTRA_SPEC_VALIDATORS.append(
        base.ExtraSpecValidator(
            name=f'quota:cpu_{key}',
            description=(
                f'The quota {key} for CPU. Only supported by the libvirt '
                f'virt driver.'
            ),
            value={
                'type': int,
                'min': 0,
            },
        )
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
                    f'The quota {stat} {metric} for disk. Only supported '
                    f'by the libvirt virt driver.'
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
