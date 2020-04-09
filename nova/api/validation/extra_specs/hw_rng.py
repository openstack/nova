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

"""Validators for ``hw_rng`` namespaced extra specs."""

from nova.api.validation.extra_specs import base


# TODO(stephenfin): Move these to the 'hw:' namespace
EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='hw_rng:allowed',
        description=(
            'Whether to disable configuration of a random number generator '
            'in their image. Before 21.0.0 (Ussuri), random number generators '
            'were not enabled by default so this was used to determine '
            'whether to **enable** configuration.'
        ),
        value={
            'type': bool,
        },
    ),
    base.ExtraSpecValidator(
        name='hw_rng:rate_bytes',
        description=(
            'The allowed amount of bytes for the guest to read from the '
            'host\'s entropy per period.'
        ),
        value={
            'type': int,
            'min': 0,
        },
    ),
    base.ExtraSpecValidator(
        name='hw_rng:rate_period',
        description='The duration of a read period in seconds.',
        value={
            'type': int,
            'min': 0,
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
