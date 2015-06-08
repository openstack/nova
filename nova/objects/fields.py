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
from collections import OrderedDict
import datetime

import copy
import iso8601
import netaddr
from oslo_utils import strutils
from oslo_utils import timeutils
import six

# TODO(berrange) Temporary import for Arch class
from nova.compute import arch
# TODO(berrange) Temporary import for CPU* classes
from nova.compute import cpumodel
# TODO(berrange) Temporary import for HVType class
from nova.compute import hv_type
# TODO(berrange) Temporary import for VMMode class
from nova.compute import vm_mode
from nova import exception
from nova.i18n import _
from nova.network import model as network_model


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


@six.add_metaclass(abc.ABCMeta)
class AbstractFieldType(object):
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

    @abc.abstractmethod
    def stringify(self, value):
        """Returns a short stringified version of a value."""
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

    def stringify(self, value):
        return str(value)


class UnspecifiedDefault(object):
    pass


class Field(object):
    def __init__(self, field_type, nullable=False,
                 default=UnspecifiedDefault, read_only=False):
        self._type = field_type
        self._nullable = nullable
        self._default = default
        self._read_only = read_only

    def __repr__(self):
        args = {
            'nullable': self._nullable,
            'default': self._default,
            }
        args = OrderedDict(sorted(args.items()))
        return '%s(%s)' % (self._type.__class__.__name__,
                           ','.join(['%s=%s' % (k, v)
                                     for k, v in args.items()]))

    @property
    def nullable(self):
        return self._nullable

    @property
    def default(self):
        return self._default

    @property
    def read_only(self):
        return self._read_only

    def _null(self, obj, attr):
        if self.nullable:
            return None
        elif self._default != UnspecifiedDefault:
            # NOTE(danms): We coerce the default value each time the field
            # is set to None as our contract states that we'll let the type
            # examine the object and attribute name at that time.
            return self._type.coerce(obj, attr, copy.deepcopy(self._default))
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

    def stringify(self, value):
        if value is None:
            return 'None'
        else:
            return self._type.stringify(value)


class String(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        # FIXME(danms): We should really try to avoid the need to do this
        if isinstance(value, (six.string_types, int, long, float,
                              datetime.datetime)):
            return six.text_type(value)
        else:
            raise ValueError(_('A string is required in field %(attr)s, '
                               'not %(type)s') %
                             {'attr': attr, 'type': value.__class__.__name__})

    @staticmethod
    def stringify(value):
        return '\'%s\'' % value


class Enum(String):
    def __init__(self, valid_values, **kwargs):
        try:
            length = len(valid_values)
        except TypeError:
            raise ValueError('valid_values is not a sequence'
                             ' of permitted values')
        if length == 0:
            raise ValueError('valid_values may not be empty')
        self._valid_values = valid_values
        super(Enum, self).__init__(**kwargs)

    def coerce(self, obj, attr, value):
        if value not in self._valid_values:
            msg = _("Field value %s is invalid") % value
            raise ValueError(msg)
        return super(Enum, self).coerce(obj, attr, value)

    def stringify(self, value):
        if value not in self._valid_values:
            msg = _("Field value %s is invalid") % value
            raise ValueError(msg)
        return super(Enum, self).stringify(value)


class Architecture(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.arch'
    # into fields on this class
    def __init__(self, **kwargs):
        super(Architecture, self).__init__(
            valid_values=arch.ALL, **kwargs)

    def coerce(self, obj, attr, value):
        try:
            value = arch.canonicalize(value)
        except exception.InvalidArchitectureName:
            msg = _("Architecture name '%s' is not valid") % value
            raise ValueError(msg)
        return super(Architecture, self).coerce(obj, attr, value)


class CPUAllocationPolicy(Enum):

    DEDICATED = "dedicated"
    SHARED = "shared"

    ALL = (DEDICATED, SHARED)

    def __init__(self):
        super(CPUAllocationPolicy, self).__init__(
            valid_values=CPUAllocationPolicy.ALL)


class CPUMode(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUMode, self).__init__(
            valid_values=cpumodel.ALL_CPUMODES, **kwargs)


class CPUMatch(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUMatch, self).__init__(
            valid_values=cpumodel.ALL_MATCHES, **kwargs)


class CPUFeaturePolicy(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUFeaturePolicy, self).__init__(
            valid_values=cpumodel.ALL_POLICIES, **kwargs)


class DiskBus(Enum):

    FDC = "fdc"
    IDE = "ide"
    SATA = "sata"
    SCSI = "scsi"
    USB = "usb"
    VIRTIO = "virtio"
    XEN = "xen"

    ALL = (FDC, IDE, SATA, SCSI, USB, VIRTIO, XEN)

    def __init__(self):
        super(DiskBus, self).__init__(
            valid_values=DiskBus.ALL)


class HVType(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.hv_type'
    # into fields on this class
    def __init__(self):
        super(HVType, self).__init__(
            valid_values=hv_type.ALL)

    def coerce(self, obj, attr, value):
        try:
            value = hv_type.canonicalize(value)
        except exception.InvalidHypervisorVirtType:
            msg = _("Hypervisor virt type '%s' is not valid") % value
            raise ValueError(msg)
        return super(HVType, self).coerce(obj, attr, value)


class OSType(Enum):

    LINUX = "linux"
    WINDOWS = "windows"

    ALL = (LINUX, WINDOWS)

    def __init__(self):
        super(OSType, self).__init__(
            valid_values=OSType.ALL)

    def coerce(self, obj, attr, value):
        # Some code/docs use upper case or initial caps
        # so canonicalize to all lower case
        value = value.lower()
        return super(OSType, self).coerce(obj, attr, value)


class RNGModel(Enum):

    VIRTIO = "virtio"

    ALL = (VIRTIO,)

    def __init__(self):
        super(RNGModel, self).__init__(
            valid_values=RNGModel.ALL)


class SCSIModel(Enum):

    BUSLOGIC = "buslogic"
    IBMVSCSI = "ibmvscsi"
    LSILOGIC = "lsilogic"
    LSISAS1068 = "lsisas1068"
    LSISAS1078 = "lsisas1078"
    VIRTIO_SCSI = "virtio-scsi"
    VMPVSCSI = "vmpvscsi"

    ALL = (BUSLOGIC, IBMVSCSI, LSILOGIC, LSISAS1068,
           LSISAS1078, VIRTIO_SCSI, VMPVSCSI)

    def __init__(self):
        super(SCSIModel, self).__init__(
            valid_values=SCSIModel.ALL)

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # vmware_adaptertype image property
        value = value.lower()
        if value == "lsilogicsas":
            value = SCSIModel.LSISAS1068
        elif value == "paravirtual":
            value = SCSIModel.VMPVSCSI

        return super(SCSIModel, self).coerce(obj, attr, value)


class VideoModel(Enum):

    CIRRUS = "cirrus"
    QXL = "qxl"
    VGA = "vga"
    VMVGA = "vmvga"
    XEN = "xen"

    ALL = (CIRRUS, QXL, VGA, VMVGA, XEN)

    def __init__(self):
        super(VideoModel, self).__init__(
            valid_values=VideoModel.ALL)


class VIFModel(Enum):

    LEGACY_VALUES = {"virtuale1000":
                     network_model.VIF_MODEL_E1000,
                     "virtuale1000e":
                     network_model.VIF_MODEL_E1000E,
                     "virtualpcnet32":
                     network_model.VIF_MODEL_PCNET,
                     "virtualsriovethernetcard":
                     network_model.VIF_MODEL_SRIOV,
                     "virtualvmxnet":
                     network_model.VIF_MODEL_VMXNET,
                     "virtualvmxnet3":
                     network_model.VIF_MODEL_VMXNET3,
                    }

    def __init__(self):
        super(VIFModel, self).__init__(
            valid_values=network_model.VIF_MODEL_ALL)

    def _get_legacy(self, value):
        return value

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # hw_vif_model image property
        value = value.lower()
        value = VIFModel.LEGACY_VALUES.get(value, value)
        return super(VIFModel, self).coerce(obj, attr, value)


class VMMode(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.vm_mode'
    # into fields on this class
    def __init__(self):
        super(VMMode, self).__init__(
            valid_values=vm_mode.ALL)

    def coerce(self, obj, attr, value):
        try:
            value = vm_mode.canonicalize(value)
        except exception.InvalidVirtualMachineMode:
            msg = _("Virtual machine mode '%s' is not valid") % value
            raise ValueError(msg)
        return super(VMMode, self).coerce(obj, attr, value)


class WatchdogAction(Enum):

    NONE = "none"
    PAUSE = "pause"
    POWEROFF = "poweroff"
    RESET = "reset"

    ALL = (NONE, PAUSE, POWEROFF, RESET)

    def __init__(self):
        super(WatchdogAction, self).__init__(
            valid_values=WatchdogAction.ALL)


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


class FlexibleBoolean(Boolean):
    @staticmethod
    def coerce(obj, attr, value):
        return strutils.bool_from_string(value)


class DateTime(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, six.string_types):
            # NOTE(danms): Being tolerant of isotime strings here will help us
            # during our objects transition
            value = timeutils.parse_isotime(value)
        elif not isinstance(value, datetime.datetime):
            raise ValueError(_('A datetime.datetime is required '
                               'in field %s') % attr)

        if value.utcoffset() is None:
            # NOTE(danms): Legacy objects from sqlalchemy are stored in UTC,
            # but are returned without a timezone attached.
            # As a transitional aid, assume a tz-naive object is in UTC.
            value = value.replace(tzinfo=iso8601.iso8601.Utc())
        return value

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, timeutils.parse_isotime(value))

    @staticmethod
    def to_primitive(obj, attr, value):
        return timeutils.isotime(value)

    @staticmethod
    def stringify(value):
        return timeutils.isotime(value)


class IPAddress(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPAddress(value)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, value)

    @staticmethod
    def to_primitive(obj, attr, value):
        return str(value)


class IPV4Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 4:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


class IPV6Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 6:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


class IPV4AndV6Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 4 and result.version != 6:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


class IPNetwork(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class IPV4Network(IPNetwork):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value, version=4)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class IPV6Network(IPNetwork):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value, version=6)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class CompoundFieldType(FieldType):
    def __init__(self, element_type, **field_args):
        self._element_type = Field(element_type, **field_args)


class List(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, list):
            raise ValueError(_('A list is required in field %s') % attr)
        for index, element in enumerate(list(value)):
            value[index] = self._element_type.coerce(
                    obj, '%s[%i]' % (attr, index), element)
        return value

    def to_primitive(self, obj, attr, value):
        return [self._element_type.to_primitive(obj, attr, x) for x in value]

    def from_primitive(self, obj, attr, value):
        return [self._element_type.from_primitive(obj, attr, x) for x in value]

    def stringify(self, value):
        return '[%s]' % (
            ','.join([self._element_type.stringify(x) for x in value]))


class Dict(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, dict):
            raise ValueError(_('A dict is required in field %s') % attr)
        for key, element in value.items():
            if not isinstance(key, six.string_types):
                # NOTE(guohliu) In order to keep compatibility with python3
                # we need to use six.string_types rather than basestring here,
                # since six.string_types is a tuple, so we need to pass the
                # real type in.
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

    def stringify(self, value):
        return '{%s}' % (
            ','.join(['%s=%s' % (key, self._element_type.stringify(val))
                      for key, val in sorted(value.items())]))


class DictProxyField(object):
    """Descriptor allowing us to assign pinning data as a dict of key_types

    This allows us to have an object field that will be a dict of key_type
    keys, allowing that will convert back to string-keyed dict.

    This will take care of the conversion while the dict field will make sure
    that we store the raw json-serializable data on the object.

    key_type should return a type that unambiguously responds to six.text_type
    so that calling key_type on it yields the same thing.
    """
    def __init__(self, dict_field_name, key_type=int):
        self._fld_name = dict_field_name
        self._key_type = key_type

    def __get__(self, obj, obj_type=None):
        if obj is None:
            return self
        if getattr(obj, self._fld_name) is None:
            return
        return {self._key_type(k): v
                for k, v in six.iteritems(getattr(obj, self._fld_name))}

    def __set__(self, obj, val):
        if val is None:
            setattr(obj, self._fld_name, val)
        else:
            setattr(obj, self._fld_name, {six.text_type(k): v
                                          for k, v in six.iteritems(val)})


class Set(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, set):
            raise ValueError(_('A set is required in field %s') % attr)

        coerced = set()
        for element in value:
            coerced.add(self._element_type.coerce(
                obj, '%s["%s"]' % (attr, element), element))
        return coerced

    def to_primitive(self, obj, attr, value):
        return tuple(
            self._element_type.to_primitive(obj, attr, x) for x in value)

    def from_primitive(self, obj, attr, value):
        return set([self._element_type.from_primitive(obj, attr, x)
                    for x in value])

    def stringify(self, value):
        return 'set([%s])' % (
            ','.join([self._element_type.stringify(x) for x in value]))


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
            raise ValueError(_('An object of type %(type)s is required '
                               'in field %(attr)s') %
                             {'type': self._obj_name, 'attr': attr})
        return value

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.obj_to_primitive()

    @staticmethod
    def from_primitive(obj, attr, value):
        # FIXME(danms): Avoid circular import from base.py
        from nova.objects import base as obj_base
        # NOTE (ndipanov): If they already got hydrated by the serializer, just
        # pass them back unchanged
        if isinstance(value, obj_base.NovaObject):
            return value
        return obj_base.NovaObject.obj_from_primitive(value, obj._context)

    def describe(self):
        return "Object<%s>" % self._obj_name

    def stringify(self, value):
        if 'uuid' in value.fields:
            ident = '(%s)' % (value.obj_attr_is_set('uuid') and value.uuid or
                              'UNKNOWN')
        elif 'id' in value.fields:
            ident = '(%s)' % (value.obj_attr_is_set('id') and value.id or
                              'UNKNOWN')
        else:
            ident = ''

        return '%s%s' % (self._obj_name, ident)


class NetworkModel(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, network_model.NetworkInfo):
            return value
        elif isinstance(value, six.string_types):
            # Hmm, do we need this?
            return network_model.NetworkInfo.hydrate(value)
        else:
            raise ValueError(_('A NetworkModel is required in field %s') %
                             attr)

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.json()

    @staticmethod
    def from_primitive(obj, attr, value):
        return network_model.NetworkInfo.hydrate(value)

    def stringify(self, value):
        return 'NetworkModel(%s)' % (
            ','.join([str(vif['id']) for vif in value]))


class AutoTypedField(Field):
    AUTO_TYPE = None

    def __init__(self, **kwargs):
        super(AutoTypedField, self).__init__(self.AUTO_TYPE, **kwargs)


class StringField(AutoTypedField):
    AUTO_TYPE = String()


class BaseEnumField(AutoTypedField):
    '''This class should not be directly instantiated. Instead
    subclass it and set AUTO_TYPE to be a SomeEnum()
    where SomeEnum is a subclass of Enum.
    '''
    def __init__(self, **kwargs):
        if self.AUTO_TYPE is None:
            raise exception.EnumFieldUnset(
                fieldname=self.__class__.__name__)

        if not isinstance(self.AUTO_TYPE, Enum):
            raise exception.EnumFieldInvalid(
                typename=self.AUTO_TYPE.__class__.__name,
                fieldname=self.__class__.__name__)

        super(BaseEnumField, self).__init__(**kwargs)

    def __repr__(self):
        valid_values = self._type._valid_values
        args = {
            'nullable': self._nullable,
            'default': self._default,
            }
        if valid_values:
            args.update({'valid_values': valid_values})
        args = OrderedDict(sorted(args.items()))
        return '%s(%s)' % (self._type.__class__.__name__,
                           ','.join(['%s=%s' % (k, v)
                                     for k, v in args.items()]))


class EnumField(BaseEnumField):
    '''This class allows for anonymous enum types to be
    declared, simply by passing in a list of valid values
    to its constructor. It is generally preferrable though,
    to create an explicit named enum type by sub-classing
    the BaeEnumField type directly. See ArchitectureField
    for an example.
    '''
    def __init__(self, valid_values, **kwargs):
        self.AUTO_TYPE = Enum(valid_values=valid_values)
        super(EnumField, self).__init__(**kwargs)


class ArchitectureField(BaseEnumField):
    AUTO_TYPE = Architecture()


class CPUAllocationPolicyField(BaseEnumField):
    AUTO_TYPE = CPUAllocationPolicy()


class CPUModeField(BaseEnumField):
    AUTO_TYPE = CPUMode()


class CPUMatchField(BaseEnumField):
    AUTO_TYPE = CPUMatch()


class CPUFeaturePolicyField(BaseEnumField):
    AUTO_TYPE = CPUFeaturePolicy()


class DiskBusField(BaseEnumField):
    AUTO_TYPE = DiskBus()


class HVTypeField(BaseEnumField):
    AUTO_TYPE = HVType()


class OSTypeField(BaseEnumField):
    AUTO_TYPE = OSType()


class RNGModelField(BaseEnumField):
    AUTO_TYPE = RNGModel()


class SCSIModelField(BaseEnumField):
    AUTO_TYPE = SCSIModel()


class VideoModelField(BaseEnumField):
    AUTO_TYPE = VideoModel()


class VIFModelField(BaseEnumField):
    AUTO_TYPE = VIFModel()


class VMModeField(BaseEnumField):
    AUTO_TYPE = VMMode()


class WatchdogActionField(BaseEnumField):
    AUTO_TYPE = WatchdogAction()


class UUIDField(AutoTypedField):
    AUTO_TYPE = UUID()


class IntegerField(AutoTypedField):
    AUTO_TYPE = Integer()


class FloatField(AutoTypedField):
    AUTO_TYPE = Float()


# This is a strict interpretation of boolean
# values using Python's semantics for truth/falsehood
class BooleanField(AutoTypedField):
    AUTO_TYPE = Boolean()


# This is a flexible interpretation of boolean
# values using common user friendly semantics for
# truth/falsehood. ie strings like 'yes', 'no',
# 'on', 'off', 't', 'f' get mapped to values you
# would expect.
class FlexibleBooleanField(AutoTypedField):
    AUTO_TYPE = FlexibleBoolean()


class DateTimeField(AutoTypedField):
    AUTO_TYPE = DateTime()


class IPAddressField(AutoTypedField):
    AUTO_TYPE = IPAddress()


class IPV4AddressField(AutoTypedField):
    AUTO_TYPE = IPV4Address()


class IPV6AddressField(AutoTypedField):
    AUTO_TYPE = IPV6Address()


class IPV4AndV6AddressField(AutoTypedField):
    AUTO_TYPE = IPV4AndV6Address()


class IPNetworkField(AutoTypedField):
    AUTO_TYPE = IPNetwork()


class IPV4NetworkField(AutoTypedField):
    AUTO_TYPE = IPV4Network()


class IPV6NetworkField(AutoTypedField):
    AUTO_TYPE = IPV6Network()


class DictOfStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String())


class DictOfNullableStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String(), nullable=True)


class DictOfIntegersField(AutoTypedField):
    AUTO_TYPE = Dict(Integer())


class ListOfStringsField(AutoTypedField):
    AUTO_TYPE = List(String())


class ListOfIntegersField(AutoTypedField):
    AUTO_TYPE = List(Integer())


class SetOfIntegersField(AutoTypedField):
    AUTO_TYPE = Set(Integer())


class ListOfSetsOfIntegersField(AutoTypedField):
    AUTO_TYPE = List(Set(Integer()))


class ListOfDictOfNullableStringsField(AutoTypedField):
    AUTO_TYPE = List(Dict(String(), nullable=True))


class ObjectField(AutoTypedField):
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = Object(objtype)
        super(ObjectField, self).__init__(**kwargs)


class ListOfObjectsField(AutoTypedField):
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = List(Object(objtype))
        super(ListOfObjectsField, self).__init__(**kwargs)
