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

"""Validators for ``vmware`` namespaced extra specs."""

from nova.api.validation.extra_specs import base


EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='vmware:hw_version',
        description=(
            'Specify the hardware version used to create images. In an '
            'environment with different host versions, you can use this '
            'parameter to place instances on the correct hosts.'
        ),
        value={
            'type': str,
        },
    ),
    base.ExtraSpecValidator(
        name='vmware:storage_policy',
        description=(
            'Specify the storage policy used for new instances.'
            '\n'
            'If Storage Policy-Based Management (SPBM) is not enabled, this '
            'parameter is ignored.'
        ),
        value={
            'type': str,
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
