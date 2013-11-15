#    Copyright 2013 IBM Corp.
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

"""Utility methods for objects"""

import datetime
import iso8601

import netaddr
import six

from nova.network import model as network_model
from nova.openstack.common.gettextutils import _
from nova.openstack.common import timeutils


def datetime_or_none(dt):
    """Validate a datetime or None value."""
    if dt is None:
        return None
    elif isinstance(dt, datetime.datetime):
        if dt.utcoffset() is None:
            # NOTE(danms): Legacy objects from sqlalchemy are stored in UTC,
            # but are returned without a timezone attached.
            # As a transitional aid, assume a tz-naive object is in UTC.
            return dt.replace(tzinfo=iso8601.iso8601.Utc())
        else:
            return dt
    raise ValueError('A datetime.datetime is required here')


# NOTE(danms): Being tolerant of isotime strings here will help us
# during our objects transition
def datetime_or_str_or_none(val):
    if isinstance(val, six.string_types):
        return timeutils.parse_isotime(val)
    return datetime_or_none(val)


def int_or_none(val):
    """Attempt to parse an integer value, or None."""
    if val is None:
        return val
    else:
        return int(val)


def str_value(val):
    if val is None:
        raise ValueError(_('None is not valid here'))
    return unicode(val)


def str_or_none(val):
    """Attempt to stringify a value, or None."""
    if val is None:
        return val
    else:
        return str_value(val)


def cstring(val):
    if val is None:
        raise ValueError(_('None is not valid here'))
    return str(val)


def ip_or_none(version):
    """Return a version-specific IP address validator."""
    def validator(val, version=version):
        if val is None:
            return val
        else:
            return netaddr.IPAddress(val, version=version)
    return validator


def nested_object(objclass, none_ok=True):
    def validator(val, objclass=objclass):
        if none_ok and val is None:
            return val
        if isinstance(val, objclass):
            return val
        raise ValueError('An object of class %s is required here' % objclass)
    return validator


def network_model_or_none(val):
    """Validate/Convert to a network_model.NetworkInfo, or None."""
    if val is None:
        return val
    if isinstance(val, network_model.NetworkInfo):
        return val
    return network_model.NetworkInfo.hydrate(val)


def list_of_strings_or_none(val):
    if val is None:
        return val
    if not isinstance(val, list):
        raise ValueError(_('A list of strings is required here'))
    if not all([isinstance(x, six.string_types) for x in val]):
        raise ValueError(_('Invalid values found in list '
                           '(strings are required)'))
    return val


def dict_of_strings_or_none(val):
    if val is None:
        return val
    if not isinstance(val, dict):
        try:
            val = dict(val.iteritems())
        except Exception:
            raise ValueError(_('A dict of strings is required here'))
    if not all([isinstance(x, six.string_types) for x in val.keys()]):
        raise ValueError(_('Invalid keys found in dict '
                           '(strings are required)'))
    if not all([isinstance(x, six.string_types) for x in val.values()]):
        raise ValueError(_('Invalid values found in dict '
                           '(strings are required)'))
    return val


def dt_serializer(name):
    """Return a datetime serializer for a named attribute."""
    def serializer(self, name=name):
        if getattr(self, name) is not None:
            return timeutils.isotime(getattr(self, name))
        else:
            return None
    return serializer


def dt_deserializer(instance, val):
    """A deserializer method for datetime attributes."""
    if val is None:
        return None
    else:
        return timeutils.parse_isotime(val)


def obj_serializer(name):
    def serializer(self, name=name):
        if getattr(self, name) is not None:
            return getattr(self, name).obj_to_primitive()
        else:
            return None
    return serializer
