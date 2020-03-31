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

"""Validators for ``accel`` namespaced extra specs."""

from nova.api.validation.extra_specs import base


EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='accel:device_profile',
        description=(
            'The name of a device profile to configure for the instance. '
            'A device profile may be viewed as a "flavor for devices".'
        ),
        value={
            'type': str,
            'description': 'A name of a device profile.',
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
