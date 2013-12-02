#    Copyright 2013 Red Hat, Inc.
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

import abc
import datetime
import iso8601

import netaddr
import six

from nova.network import model as network_model
from nova.openstack.common.gettextutils import _
from nova.openstack.common import timeutils


class KeyTypeError(TypeError):
    def __init__(self, expected, value):
        super(KeyTypeError, self).__init__(
            _('Key %(key)s must be of type %(expected)s not %(actual)s'
              ) % {'key': repr(value),
                   'expected': expected.__name__,
                   'actual': value.__class__.__name__,
                   })


class ElementTypeError(TypeError):
    def __init__(self, expected, key, value):
        super(ElementTypeError, self).__init__(
            _('Element %(key)s:%(val)s must be of type %(expected)s'
              ' not %(actual)s'
              ) % {'key': key,
                   'val': repr(value),
                   'expected': expected,
                   'actual': value.__class__.__name__,
                   })


class AbstractFieldType(six.with_metaclass(abc.ABCMeta, object)):
    @abc.abstractmethod
    def coerce(self, obj, attr, value):
        """This is called to coerce (if possible) a value on assignment.

        This method should convert the value given into the designated type,
        or throw an exception if this is not possible.

        :param:obj: The NovaObject on which an attribute is being set
        :param:attr: The name of the attribute being set
        :param:value: The value being set
        :returns: A properly-typed value
        """
        pass

    @abc.abstractmethod
    def from_primitive(self, obj, attr, value):
        """This is called to deserialize a value.

        This method should deserialize a value from the form given by
        to_primitive() to the designated type.

        :param:obj: The NovaObject on which the value is to be set
        :param:attr: The name of the attribute which will hold the value
        :param:value: The serialized form of the value
        :returns: The natural form of the value
        """
        pass

    @abc.abstractmethod
    def to_primitive(self, obj, attr, value):
        """This is called to serialize a value.

        This method should serialize a value to the form expected by
        from_primitive().

        :param:obj: The NovaObject on which the value is set
        :param:attr: The name of the attribute holding the value
        :param:value: The natural form of the value
        :returns: The serialized form of the value
        """
        pass

    @abc.abstractmethod
    def describe(self):
        """Returns a string describing the type of the field."""
        pass


class FieldType(AbstractFieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return value

    @staticmethod
    def from_primitive(obj, attr, value):
        return value

    @staticmethod
    def to_primitive(obj, attr, value):
        return value

    def describe(self):
        return self.__class__.__name__


class UnspecifiedDefault(object):
    pass


class Field(object):
    def __init__(self, field_type, nullable=False, default=UnspecifiedDefault):
        self._type = field_type
        self._nullable = nullable
        self._default = default

    @property
    def nullable(self):
        return self._nullable

    @property
    def default(self):
        return self._default

    def _null(self, obj, attr):
        if self.nullable:
            return None
        elif self._default != UnspecifiedDefault:
            # NOTE(danms): We coerce the default value each time the field
            # is set to None as our contract states that we'll let the type
            # examine the object and attribute name at that time.
            return self._type.coerce(obj, attr, self._default)
        else:
            raise ValueError(_("Field `%s' cannot be None") % attr)

    def coerce(self, obj, attr, value):
        """Coerce a value to a suitable type.

        This is called any time you set a value on an object, like:

          foo.myint = 1

        and is responsible for making sure that the value (1 here) is of
        the proper type, or can be sanely converted.

        This also handles the potentially nullable or defaultable
        nature of the field and calls the coerce() method on a
        FieldType to actually do the coercion.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being set
        :param:value: The value being set
        :returns: The properly-typed value
        """
        if value is None:
            return self._null(obj, attr)
        else:
            return self._type.coerce(obj, attr, value)

    def from_primitive(self, obj, attr, value):
        """Deserialize a value from primitive form.

        This is responsible for deserializing a value from primitive
        into regular form. It calls the from_primitive() method on a
        FieldType to do the actual deserialization.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being deserialized
        :param:value: The value to be deserialized
        :returns: The deserialized value
        """
        if value is None:
            return None
        else:
            return self._type.from_primitive(obj, attr, value)

    def to_primitive(self, obj, attr, value):
        """Serialize a value to primitive form.

        This is responsible for serializing a value to primitive
        form. It calls to_primitive() on a FieldType to do the actual
        serialization.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being serialized
        :param:value: The value to be serialized
        :returns: The serialized value
        """
        if value is None:
            return None
        else:
            return self._type.to_primitive(obj, attr, value)

    def describe(self):
        """Return a short string describing the type of this field."""
        name = self._type.describe()
        prefix = self.nullable and 'Nullable' or ''
        return prefix + name


class String(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        # FIXME(danms): We should really try to avoid the need to do this
        if isinstance(value, (six.string_types, int, long, float,
                              datetime.datetime)):
            return unicode(value)
        else:
            raise ValueError(_('A string is required here, not %s'),
                             value.__class__.__name__)


class UUID(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        # FIXME(danms): We should actually verify the UUIDness here
        return str(value)


class Integer(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return int(value)


class Float(FieldType):
    def coerce(self, obj, attr, value):
        return float(value)


class Boolean(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return bool(value)


class DateTime(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, six.string_types):
            value = timeutils.parse_isotime(value)
        elif not isinstance(value, datetime.datetime):
            raise ValueError(_('A datetime.datetime is required here'))

        if value.utcoffset() is None:
            value = value.replace(tzinfo=iso8601.iso8601.Utc())
        return value

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, timeutils.parse_isotime(value))

    @staticmethod
    def to_primitive(obj, attr, value):
        return timeutils.isotime(value)


class IPV4Address(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPAddress(value, version=4)
        except netaddr.AddrFormatError as e:
            raise ValueError(str(e))

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, value)

    @staticmethod
    def to_primitive(obj, attr, value):
        return str(value)


class IPV6Address(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPAddress(value, version=6)
        except netaddr.AddrFormatError as e:
            raise ValueError(str(e))

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, value)

    @staticmethod
    def to_primitive(obj, attr, value):
        return str(value)


class CompoundFieldType(FieldType):
    def __init__(self, element_type, **field_args):
        self._element_type = Field(element_type, **field_args)


class List(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, list):
            raise ValueError(_('A list is required here'))
        for index, element in enumerate(list(value)):
            value[index] = self._element_type.coerce(
                    obj, '%s[%i]' % (attr, index), element)
        return value

    def to_primitive(self, obj, attr, value):
        return [self._element_type.to_primitive(obj, attr, x) for x in value]

    def from_primitive(self, obj, attr, value):
        return [self._element_type.from_primitive(obj, attr, x) for x in value]


class Dict(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, dict):
            raise ValueError(_('A dict is required here'))
        for key, element in value.items():
            if not isinstance(key, six.string_types):
                #NOTE(guohliu) In order to keep compatibility with python3
                #we need to use six.string_types rather than basestring here,
                #since six.string_types is a tuple, so we need to pass the
                #real type in.
                raise KeyTypeError(six.string_types[0], key)
            value[key] = self._element_type.coerce(
                obj, '%s["%s"]' % (attr, key), element)
        return value

    def to_primitive(self, obj, attr, value):
        primitive = {}
        for key, element in value.items():
            primitive[key] = self._element_type.to_primitive(
                obj, '%s["%s"]' % (attr, key), element)
        return primitive

    def from_primitive(self, obj, attr, value):
        concrete = {}
        for key, element in value.items():
            concrete[key] = self._element_type.from_primitive(
                obj, '%s["%s"]' % (attr, key), element)
        return concrete


class Object(FieldType):
    def __init__(self, obj_name, **kwargs):
        self._obj_name = obj_name
        super(Object, self).__init__(**kwargs)

    def coerce(self, obj, attr, value):
        try:
            obj_name = value.obj_name()
        except AttributeError:
            obj_name = ""

        if obj_name != self._obj_name:
            raise ValueError(_('An object of type %s is required here') %
                             self._obj_name)
        return value

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.obj_to_primitive()

    @staticmethod
    def from_primitive(obj, attr, value):
        # FIXME(danms): Avoid circular import from base.py
        from nova.objects import base as obj_base
        return obj_base.NovaObject.obj_from_primitive(value, obj._context)

    def describe(self):
        return "Object<%s>" % self._obj_name


class NetworkModel(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, network_model.NetworkInfo):
            return value
        elif isinstance(value, six.string_types):
            # Hmm, do we need this?
            return network_model.NetworkInfo.hydrate(value)
        else:
            raise ValueError(_('A NetworkModel is required here'))

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.json()

    @staticmethod
    def from_primitive(obj, attr, value):
        return network_model.NetworkInfo.hydrate(value)


class CIDR(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            network, length = value.split('/')
        except (ValueError, AttributeError):
            raise ValueError(_('CIDR "%s" is not in proper form') % value)
        try:
            network = netaddr.IPAddress(network)
        except netaddr.AddrFormatError:
            raise ValueError(_('Network "%s" is not valid') % network)
        try:
            length = int(length)
            assert (length >= 0)
        except (ValueError, AssertionError):
            raise ValueError(_('Netmask length "%s" is not valid') % length)
        if ((network.version == 4 and length > 32) or
                (network.version == 6 and length > 128)):
            raise ValueError(_('Netmask length "%(length)s" is not valid '
                               'for IPv%(version)i address') %
                             {'length': length, 'version': network.version})
        return value


class AutoTypedField(Field):
    AUTO_TYPE = None

    def __init__(self, **kwargs):
        super(AutoTypedField, self).__init__(self.AUTO_TYPE, **kwargs)


class StringField(AutoTypedField):
    AUTO_TYPE = String()


class UUIDField(AutoTypedField):
    AUTO_TYPE = UUID()


class IntegerField(AutoTypedField):
    AUTO_TYPE = Integer()


class FloatField(AutoTypedField):
    AUTO_TYPE = Float()


class BooleanField(AutoTypedField):
    AUTO_TYPE = Boolean()


class DateTimeField(AutoTypedField):
    AUTO_TYPE = DateTime()


class IPV4AddressField(AutoTypedField):
    AUTO_TYPE = IPV4Address()


class IPV6AddressField(AutoTypedField):
    AUTO_TYPE = IPV6Address()


class DictOfStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String())


class DictOfNullableStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String(), nullable=True)


class ListOfStringsField(AutoTypedField):
    AUTO_TYPE = List(String())


class ObjectField(AutoTypedField):
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = Object(objtype)
        super(ObjectField, self).__init__(**kwargs)


class ListOfObjectsField(AutoTypedField):
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = List(Object(objtype))
        super(ListOfObjectsField, self).__init__(**kwargs)
