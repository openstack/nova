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

"""Validators for all extra specs known by nova."""

import re
import typing as ty

from oslo_log import log as logging
from stevedore import extension

from nova.api.validation.extra_specs import base
from nova import exception

LOG = logging.getLogger(__name__)

VALIDATORS: ty.Dict[str, base.ExtraSpecValidator] = {}
NAMESPACES: ty.Set[str] = set()


def validate(name: str, value: str):
    """Validate a given extra spec.

    :param name: Extra spec name.
    :param value: Extra spec value.
    :raises: exception.ValidationError if validation fails.
    """
    # attempt a basic lookup for extra specs without embedded parameters
    if name in VALIDATORS:
        VALIDATORS[name].validate(name, value)
        return

    # if that failed, fallback to a linear search through the registry
    for validator in VALIDATORS.values():
        if re.fullmatch(validator.name_regex, name):
            validator.validate(name, value)
            return

    # check if there's a namespace; if not, we've done all we can do
    if ':' not in name:  # no namespace
        return

    # if there is, check if it's one we recognize
    for namespace in NAMESPACES:
        if re.fullmatch(namespace, name.split(':', 1)[0]):
            break
    else:
        return

    raise exception.ValidationError(
        f"Validation failed; extra spec '{name}' does not appear to be a "
        f"valid extra spec."
    )


def load_validators():
    global VALIDATORS

    def _report_load_failure(mgr, ep, err):
        LOG.warning(u'Failed to load %s: %s', ep.module_name, err)

    mgr = extension.ExtensionManager(
        'nova.api.extra_spec_validators',
        on_load_failure_callback=_report_load_failure,
        invoke_on_load=False,
    )
    for ext in mgr:
        # TODO(stephenfin): Make 'register' return a dict rather than a list?
        for validator in ext.plugin.register():
            VALIDATORS[validator.name] = validator
            if ':' in validator.name_regex:
                NAMESPACES.add(validator.name_regex.split(':', 1)[0])


load_validators()
