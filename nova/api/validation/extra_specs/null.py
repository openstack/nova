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

"""Validators for non-namespaced extra specs."""

from nova.api.validation.extra_specs import base


# TODO(stephenfin): These should be moved to a namespace
EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='hide_hypervisor_id',
        description=(
            'Determine whether the hypervisor ID should be hidden from the '
            'guest. Only supported by the libvirt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to hide the hypervisor ID.',
        },
    ),
    base.ExtraSpecValidator(
        name='group_policy',
        description=(
            'The group policy to apply when using the granular resource '
            'request syntax.'
        ),
        value={
            'type': str,
            'enum': [
                'isolate',
                'none',
            ],
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
