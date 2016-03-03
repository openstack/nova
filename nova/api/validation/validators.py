# Copyright 2013 NEC Corporation.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Internal implementation of request Body validating middleware.

"""

import base64
import re

import jsonschema
from jsonschema import exceptions as jsonschema_exc
import netaddr
from oslo_utils import timeutils
from oslo_utils import uuidutils
import rfc3986
import six

from nova import exception
from nova.i18n import _


@jsonschema.FormatChecker.cls_checks('date-time')
def _validate_datetime_format(instance):
    try:
        timeutils.parse_isotime(instance)
    except ValueError:
        return False
    else:
        return True


@jsonschema.FormatChecker.cls_checks('base64')
def _validate_base64_format(instance):
    try:
        base64.decodestring(instance)
    except base64.binascii.Error:
        return False

    return True


@jsonschema.FormatChecker.cls_checks('cidr')
def _validate_cidr_format(cidr):
    try:
        netaddr.IPNetwork(cidr)
    except netaddr.AddrFormatError:
        return False
    if '/' not in cidr:
        return False
    if re.search('\s', cidr):
        return False
    return True


@jsonschema.FormatChecker.cls_checks('uuid')
def _validate_uuid_format(instance):
    return uuidutils.is_uuid_like(instance)


@jsonschema.FormatChecker.cls_checks('uri')
def _validate_uri(instance):
    return rfc3986.is_valid_uri(instance, require_scheme=True,
                                require_authority=True)


def _soft_validate_additional_properties(validator,
                                         additional_properties_value,
                                         instance,
                                         schema):
    """This validator function is used for legacy v2 compatible mode in v2.1.
    This will skip all the additional properties checking but keep check the
    'patternProperties'. 'patternProperties' is used for metadata API.

    If there are not any properties on the instance that are not specified in
    the schema, this will return without any effect. If there are any such
    extra properties, they will be handled as follows:

    - if the validator passed to the method is not of type "object", this
      method will return without any effect.
    - if the 'additional_properties_value' parameter is True, this method will
      return without any effect.
    - if the schema has an additionalProperties value of True, the extra
      properties on the instance will not be touched.
    - if the schema has an additionalProperties value of False and there
      aren't patternProperties specified, the extra properties will be stripped
      from the instance.
    - if the schema has an additionalProperties value of False and there
      are patternProperties specified, the extra properties will not be
      touched and raise validation error if pattern doesn't match.
    """
    if (not validator.is_type(instance, "object") or
            additional_properties_value):
        return

    properties = schema.get("properties", {})
    patterns = "|".join(schema.get("patternProperties", {}))
    extra_properties = set()
    for prop in instance:
        if prop not in properties:
            if patterns:
                if not re.search(patterns, prop):
                    extra_properties.add(prop)
            else:
                extra_properties.add(prop)

    if not extra_properties:
        return

    if patterns:
        error = "Additional properties are not allowed (%s %s unexpected)"
        if len(extra_properties) == 1:
            verb = "was"
        else:
            verb = "were"
        yield jsonschema_exc.ValidationError(
            error % (", ".join(repr(extra) for extra in extra_properties),
                     verb))
    else:
        for prop in extra_properties:
            del instance[prop]


class _SchemaValidator(object):
    """A validator class

    This class is changed from Draft4Validator to validate minimum/maximum
    value of a string number(e.g. '10'). This changes can be removed when
    we tighten up the API definition and the XML conversion.
    Also FormatCheckers are added for checking data formats which would be
    passed through nova api commonly.

    """
    validator = None
    validator_org = jsonschema.Draft4Validator

    def __init__(self, schema, relax_additional_properties=False):
        validators = {
            'minimum': self._validate_minimum,
            'maximum': self._validate_maximum,
        }
        if relax_additional_properties:
            validators[
                'additionalProperties'] = _soft_validate_additional_properties

        validator_cls = jsonschema.validators.extend(self.validator_org,
                                                     validators)
        format_checker = jsonschema.FormatChecker()
        self.validator = validator_cls(schema, format_checker=format_checker)

    def validate(self, *args, **kwargs):
        try:
            self.validator.validate(*args, **kwargs)
        except jsonschema.ValidationError as ex:
            # NOTE: For whole OpenStack message consistency, this error
            #       message has been written as the similar format of WSME.
            if len(ex.path) > 0:
                detail = _("Invalid input for field/attribute %(path)s."
                           " Value: %(value)s. %(message)s") % {
                               'path': ex.path.pop(), 'value': ex.instance,
                               'message': ex.message
                           }
            else:
                detail = ex.message
            raise exception.ValidationError(detail=detail)
        except TypeError as ex:
            # NOTE: If passing non string value to patternProperties parameter,
            #       TypeError happens. Here is for catching the TypeError.
            detail = six.text_type(ex)
            raise exception.ValidationError(detail=detail)

    def _number_from_str(self, instance):
        try:
            value = int(instance)
        except (ValueError, TypeError):
            try:
                value = float(instance)
            except (ValueError, TypeError):
                return None
        return value

    def _validate_minimum(self, validator, minimum, instance, schema):
        instance = self._number_from_str(instance)
        if instance is None:
            return
        return self.validator_org.VALIDATORS['minimum'](validator, minimum,
                                                        instance, schema)

    def _validate_maximum(self, validator, maximum, instance, schema):
        instance = self._number_from_str(instance)
        if instance is None:
            return
        return self.validator_org.VALIDATORS['maximum'](validator, maximum,
                                                        instance, schema)
