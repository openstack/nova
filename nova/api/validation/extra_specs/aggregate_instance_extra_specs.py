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

"""Validators for (preferrably) ``aggregate_instance_extra_specs`` namespaced
extra specs.

These are used by the ``AggregateInstanceExtraSpecsFilter`` scheduler filter.
Note that we explicitly do not support the unnamespaced variant of extra specs
since these have been deprecated since Havana (commit fbedf60a432). Users that
insist on using these can disable extra spec validation.
"""

from nova.api.validation.extra_specs import base


DESCRIPTION = """\
Specify metadata that must be present on the aggregate of a host. If this
metadata is not present, the host will be rejected. Requires the
``AggregateInstanceExtraSpecsFilter`` scheduler filter.

The value can be one of the following:

* ``=`` (equal to or greater than as a number; same as vcpus case)
* ``==`` (equal to as a number)
* ``!=`` (not equal to as a number)
* ``>=`` (greater than or equal to as a number)
* ``<=`` (less than or equal to as a number)
* ``s==`` (equal to as a string)
* ``s!=`` (not equal to as a string)
* ``s>=`` (greater than or equal to as a string)
* ``s>`` (greater than as a string)
* ``s<=`` (less than or equal to as a string)
* ``s<`` (less than as a string)
* ``<in>`` (substring)
* ``<all-in>`` (all elements contained in collection)
* ``<or>`` (find one of these)
* A specific value, e.g. ``true``, ``123``, ``testing``
"""

EXTRA_SPEC_VALIDATORS = [
    base.ExtraSpecValidator(
        name='aggregate_instance_extra_specs:{key}',
        description=DESCRIPTION,
        parameters=[
            {
                'name': 'key',
                'description': 'The metadata key to match on',
                'pattern': r'.+',
            },
        ],
        value={
            # this is totally arbitary, since we need to support specific
            # values
            'type': str,
        },
    ),
]


def register():
    return EXTRA_SPEC_VALIDATORS
