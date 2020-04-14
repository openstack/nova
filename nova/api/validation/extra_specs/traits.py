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

"""Validators for ``traits`` namespaced extra specs."""

import os_traits

from nova.api.validation.extra_specs import base


EXTRA_SPEC_VALIDATORS = []

for trait in os_traits.get_traits():
    EXTRA_SPEC_VALIDATORS.append(
        base.ExtraSpecValidator(
            name=f'trait{{group}}:{trait}',
            description=f'Require or forbid trait {trait}.',
            value={
                'type': str,
                'enum': [
                    'required',
                    'forbidden',
                ],
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
        name='trait{group}:CUSTOM_{trait}',
        description=(
            'Require or forbid trait CUSTOM_{trait}.'
        ),
        value={
            'type': str,
            'enum': [
                'required',
                'forbidden',
            ],
        },
        parameters=[
            {
                'name': 'group',
                'pattern': r'([a-zA-Z0-9_-]{1,64})?',
            },
            {
                'name': 'trait',
                'pattern': r'[A-Z0-9_]+',
            },
        ],
    )
)


def register():
    return EXTRA_SPEC_VALIDATORS
