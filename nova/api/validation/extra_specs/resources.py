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

"""Validators for ``resources`` namespaced extra specs."""

import os_resource_classes

from nova.api.validation.extra_specs import base


EXTRA_SPEC_VALIDATORS = []

for resource_class in os_resource_classes.STANDARDS:
    EXTRA_SPEC_VALIDATORS.append(
        base.ExtraSpecValidator(
            name=f'resources{{group}}:{resource_class}',
            description=f'The amount of resource {resource_class} requested.',
            value={
                'type': int,
            },
            parameters=[
                {
                    'name': 'group',
                    'pattern': r'([a-zA-Z0-9_-]{1,64})?',
                },
            ],
        )
    )

EXTRA_SPEC_VALIDATORS.append(
    base.ExtraSpecValidator(
        name='resources{group}:CUSTOM_{resource}',
        description=(
            'The amount of resource CUSTOM_{resource} requested.'
        ),
        value={
            'type': int,
        },
        parameters=[
            {
                'name': 'group',
                'pattern': r'([a-zA-Z0-9_-]{1,64})?',
            },
            {
                'name': 'resource',
                'pattern': r'[A-Z0-9_]+',
            },
        ],
    )
)


def register():
    return EXTRA_SPEC_VALIDATORS
