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

"""Validators for ``os`` namespaced extra specs."""

from nova.api.validation.extra_specs import base


# TODO(stephenfin): Most of these belong in the 'hw:' namespace
# and should be moved.
EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='os:secure_boot',
        description=(
            'Determine whether secure boot is enabled or not. Only supported '
            'by the libvirt virt drivers.'
        ),
        value={
            'type': str,
            'description': 'Whether secure boot is required or not',
            'enum': [
                'disabled',
                'required',
            ],
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
