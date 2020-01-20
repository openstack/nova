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

import dataclasses
import re
import typing as ty

from oslo_utils import strutils

from nova import exception


@dataclasses.dataclass
class ExtraSpecValidator:
    name: str
    description: str
    value: ty.Dict[str, ty.Any]
    deprecated: bool = False
    parameters: ty.List[ty.Dict[str, ty.Any]] = dataclasses.field(
        default_factory=list
    )

    name_regex: str = None
    value_regex: str = None

    def __post_init__(self):
        # generate a regex for the name

        name_regex = self.name
        # replace the human-readable patterns with named regex groups; this
        # will transform e.g. 'hw:numa_cpus.{id}' to 'hw:numa_cpus.(?P<id>\d+)'
        for param in self.parameters:
            pattern = f'(?P<{param["name"]}>{param["pattern"]})'
            name_regex = name_regex.replace(f'{{{param["name"]}}}', pattern)

        self.name_regex = name_regex

        # ...and do the same for the value, but only if we're using strings

        if self.value['type'] not in (int, str, bool):
            raise ValueError(
                f"Unsupported parameter type '{self.value['type']}'"
            )

        value_regex = None
        if self.value['type'] == str and self.value.get('pattern'):
            value_regex = self.value['pattern']

        self.value_regex = value_regex

    def _validate_str(self, value):
        if 'pattern' in self.value:
            value_match = re.fullmatch(self.value_regex, value)
            if not value_match:
                raise exception.ValidationError(
                    f"Validation failed; '{value}' is not of the format "
                    f"'{self.value_regex}'."
                )
        elif 'enum' in self.value:
            if value not in self.value['enum']:
                values = ', '.join(str(x) for x in self.value['enum'])
                raise exception.ValidationError(
                    f"Validation failed; '{value}' is not one of: {values}."
                )

    def _validate_int(self, value):
        try:
            value = int(value)
        except ValueError:
            raise exception.ValidationError(
                f"Validation failed; '{value}' is not a valid integer value."
            )

        if 'max' in self.value and self.value['max'] < value:
            raise exception.ValidationError(
                f"Validation failed; '{value}' is greater than the max value "
                f"of '{self.value['max']}'."
            )

        if 'min' in self.value and self.value['min'] > value:
            raise exception.ValidationError(
                f"Validation failed; '{value}' is less than the min value "
                f"of '{self.value['min']}'."
            )

    def _validate_bool(self, value):
        try:
            strutils.bool_from_string(value, strict=True)
        except ValueError:
            raise exception.ValidationError(
                f"Validation failed; '{value}' is not a valid boolean-like "
                f"value."
            )

    def validate(self, name, value):
        name_match = re.fullmatch(self.name_regex, name)
        if not name_match:
            # NOTE(stephenfin): This is mainly here for testing purposes
            raise exception.ValidationError(
                f"Validation failed; expected a name of format '{self.name}' "
                f"but got '{name}'."
            )

        if self.value['type'] == int:
            self._validate_int(value)
        elif self.value['type'] == bool:
            self._validate_bool(value)
        else:  # str
            self._validate_str(value)
