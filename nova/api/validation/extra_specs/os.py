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


# TODO(stephenfin): Most of these belong in the 'hw:' or 'hyperv:' namespace
# and should be moved.
EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='os:secure_boot',
        description=(
            'Determine whether secure boot is enabled or not. Currently only '
            'supported by the HyperV driver.'
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
    base.ExtraSpecValidator(
        name='os:resolution',
        description=(
            'Guest VM screen resolution size. Only supported by the HyperV '
            'driver.'
        ),
        value={
            'type': str,
            'description': 'The chosen resolution',
            'enum': [
                '1024x768',
                '1280x1024',
                '1600x1200',
                '1920x1200',
                '2560x1600',
                '3840x2160',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='os:monitors',
        description=(
            'Guest VM number of monitors. Only supported by the HyperV driver.'
        ),
        value={
            'type': int,
            'description': 'The number of monitors enabled',
            'min': 1,
            'max': 8,
        },
    ),
    # TODO(stephenfin): Consider merging this with the 'hw_video_ram' image
    # metadata property or adding a 'hw:video_ram' extra spec that works for
    # both Hyper-V and libvirt.
    base.ExtraSpecValidator(
        name='os:vram',
        description=(
            'Guest VM VRAM amount. Only supported by the HyperV driver.'
        ),
        # NOTE(stephenfin): This is really an int, but because there's a
        # limited range of options we treat it as a string
        value={
            'type': str,
            'description': 'Amount of VRAM to allocate to instance',
            'enum': [
                '64',
                '128',
                '256',
                '512',
                '1024',
            ],
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
