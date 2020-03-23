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

"""Nova common internal object model"""

import contextlib
import datetime
import functools
import traceback

import netaddr
import oslo_messaging as messaging
from oslo_utils import versionutils
from oslo_versionedobjects import base as ovoo_base
from oslo_versionedobjects import exception as ovoo_exc
import six

from nova import objects
from nova.objects import fields as obj_fields
from nova import utils


def all_things_equal(obj_a, obj_b):
    if obj_b is None:
        return False

    for name in obj_a.fields:
        set_a = name in obj_a
        set_b = name in obj_b
        if set_a != set_b:
            return False
        elif not set_a:
            continue

        if getattr(obj_a, name) != getattr(obj_b, name):
            return False
    return True


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    # FIXME(danms): This is just until we use o.vo's class properties
    # and object base.
    return '_obj_' + name


class NovaObjectRegistry(ovoo_base.VersionedObjectRegistry):
    notification_classes = []

    def registration_hook(self, cls, index):
        # NOTE(danms): This is called when an object is registered,
        # and is responsible for maintaining nova.objects.$OBJECT
        # as the highest-versioned implementation of a given object.
        version = versionutils.convert_version_to_tuple(cls.VERSION)
        if not hasattr(objects, cls.obj_name()):
            setattr(objects, cls.obj_name(), cls)
        else:
            cur_version = versionutils.convert_version_to_tuple(
                getattr(objects, cls.obj_name()).VERSION)
            if version >= cur_version:
                setattr(objects, cls.obj_name(), cls)

    @classmethod
    def register_notification(cls, notification_cls):
        """Register a class as notification.
        Use only to register concrete notification or payload classes,
        do not register base classes intended for inheritance only.
        """
        cls.register_if(False)(notification_cls)
        cls.notification_classes.append(notification_cls)
        return notification_cls

    @classmethod
    def register_notification_objects(cls):
        """Register previously decorated notification as normal ovos.
        This is not intended for production use but only for testing and
        document generation purposes.
        """
        for notification_cls in cls.notification_classes:
            cls.register(notification_cls)


remotable_classmethod = ovoo_base.remotable_classmethod
remotable = ovoo_base.remotable
obj_make_list = ovoo_base.obj_make_list
NovaObjectDictCompat = ovoo_base.VersionedObjectDictCompat
NovaTimestampObject = ovoo_base.TimestampedObject


class NovaObject(ovoo_base.VersionedObject):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """

    OBJ_SERIAL_NAMESPACE = 'nova_object'
    OBJ_PROJECT_NAMESPACE = 'nova'

    # NOTE(ndipanov): This is nova-specific
    @staticmethod
    def should_migrate_data():
        """A check that can be used to inhibit online migration behavior

        This is usually used to check if all services that will be accessing
        the db directly are ready for the new format.
        """
        raise NotImplementedError()

    # NOTE(danms): This is nova-specific
    @contextlib.contextmanager
    def obj_alternate_context(self, context):
        original_context = self._context
        self._context = context
        try:
            yield
        finally:
            self._context = original_context


class NovaPersistentObject(object):
    """Mixin class for Persistent objects.

    This adds the fields that we use in common for most persistent objects.
    """
    fields = {
        'created_at': obj_fields.DateTimeField(nullable=True),
        'updated_at': obj_fields.DateTimeField(nullable=True),
        'deleted_at': obj_fields.DateTimeField(nullable=True),
        'deleted': obj_fields.BooleanField(default=False),
        }


# NOTE(danms): This is copied from oslo.versionedobjects ahead of
#              a release. Do not use it directly or modify it.
# TODO(danms): Remove this when we can get it from oslo.versionedobjects
class EphemeralObject(object):
    """Mix-in to provide more recognizable field defaulting.

    If an object should have all fields with a default= set to
    those values during instantiation, inherit from this class.

    The base VersionedObject class is designed in such a way that all
    fields are optional, which makes sense when representing a remote
    database row where not all columns are transported across RPC and
    not all columns should be set during an update operation. This is
    why fields with default= are not set implicitly during object
    instantiation, to avoid clobbering existing fields in the
    database. However, objects based on VersionedObject are also used
    to represent all-or-nothing blobs stored in the database, or even
    used purely in RPC to represent things that are not ever stored in
    the database. Thus, this mix-in is provided for these latter
    object use cases where the desired behavior is to always have
    default= fields be set at __init__ time.
    """

    def __init__(self, *args, **kwargs):
        super(EphemeralObject, self).__init__(*args, **kwargs)
        # Not specifying any fields causes all defaulted fields to be set
        self.obj_set_defaults()


class NovaEphemeralObject(EphemeralObject,
                          NovaObject):
    """Base class for objects that are not row-column in the DB.

    Objects that are used purely over RPC (i.e. not persisted) or are
    written to the database in blob form or otherwise do not represent
    rows directly as fields should inherit from this object.

    The principal difference is that fields with a default value will
    be set at __init__ time instead of requiring manual intervention.
    """
    pass


class ObjectListBase(ovoo_base.ObjectListBase):
    # NOTE(danms): These are for transition to using the oslo
    # base object and can be removed when we move to it.
    @classmethod
    def _obj_primitive_key(cls, field):
        return 'nova_object.%s' % field

    @classmethod
    def _obj_primitive_field(cls, primitive, field,
                             default=obj_fields.UnspecifiedDefault):
        key = cls._obj_primitive_key(field)
        if default == obj_fields.UnspecifiedDefault:
            return primitive[key]
        else:
            return primitive.get(key, default)


class NovaObjectSerializer(messaging.NoOpSerializer):
    """A NovaObject-aware Serializer.

    This implements the Oslo Serializer interface and provides the
    ability to serialize and deserialize NovaObject entities. Any service
    that needs to accept or return NovaObjects as arguments or result values
    should pass this to its RPCClient and RPCServer objects.
    """

    @property
    def conductor(self):
        if not hasattr(self, '_conductor'):
            from nova import conductor
            self._conductor = conductor.API()
        return self._conductor

    def _process_object(self, context, objprim):
        try:
            objinst = NovaObject.obj_from_primitive(objprim, context=context)
        except ovoo_exc.IncompatibleObjectVersion:
            objver = objprim['nova_object.version']
            if objver.count('.') == 2:
                # NOTE(danms): For our purposes, the .z part of the version
                # should be safe to accept without requiring a backport
                objprim['nova_object.version'] = \
                    '.'.join(objver.split('.')[:2])
                return self._process_object(context, objprim)
            objname = objprim['nova_object.name']
            version_manifest = ovoo_base.obj_tree_get_versions(objname)
            if objname in version_manifest:
                objinst = self.conductor.object_backport_versions(
                    context, objprim, version_manifest)
            else:
                raise
        return objinst

    def _process_iterable(self, context, action_fn, values):
        """Process an iterable, taking an action on each value.
        :param:context: Request context
        :param:action_fn: Action to take on each item in values
        :param:values: Iterable container of things to take action on
        :returns: A new container of the same type (except set) with
                  items from values having had action applied.
        """
        iterable = values.__class__
        if issubclass(iterable, dict):
            return iterable(**{k: action_fn(context, v)
                            for k, v in values.items()})
        else:
            # NOTE(danms, gibi) A set can't have an unhashable value inside,
            # such as a dict. Convert the set to list, which is fine, since we
            # can't send them over RPC anyway. We convert it to list as this
            # way there will be no semantic change between the fake rpc driver
            # used in functional test and a normal rpc driver.
            if iterable == set:
                iterable = list
            return iterable([action_fn(context, value) for value in values])

    def serialize_entity(self, context, entity):
        if isinstance(entity, (tuple, list, set, dict)):
            entity = self._process_iterable(context, self.serialize_entity,
                                            entity)
        elif (hasattr(entity, 'obj_to_primitive') and
              callable(entity.obj_to_primitive)):
            entity = entity.obj_to_primitive()
        return entity

    def deserialize_entity(self, context, entity):
        if isinstance(entity, dict) and 'nova_object.name' in entity:
            entity = self._process_object(context, entity)
        elif isinstance(entity, (tuple, list, set, dict)):
            entity = self._process_iterable(context, self.deserialize_entity,
                                            entity)
        return entity


def obj_to_primitive(obj):
    """Recursively turn an object into a python primitive.

    A NovaObject becomes a dict, and anything that implements ObjectListBase
    becomes a list.
    """
    if isinstance(obj, ObjectListBase):
        return [obj_to_primitive(x) for x in obj]
    elif isinstance(obj, NovaObject):
        result = {}
        for key in obj.obj_fields:
            if obj.obj_attr_is_set(key) or key in obj.obj_extra_fields:
                result[key] = obj_to_primitive(getattr(obj, key))
        return result
    elif isinstance(obj, netaddr.IPAddress):
        return str(obj)
    elif isinstance(obj, netaddr.IPNetwork):
        return str(obj)
    else:
        return obj


def obj_make_dict_of_lists(context, list_cls, obj_list, item_key):
    """Construct a dictionary of object lists, keyed by item_key.

    :param:context: Request context
    :param:list_cls: The ObjectListBase class
    :param:obj_list: The list of objects to place in the dictionary
    :param:item_key: The object attribute name to use as a dictionary key
    """

    obj_lists = {}
    for obj in obj_list:
        key = getattr(obj, item_key)
        if key not in obj_lists:
            obj_lists[key] = list_cls()
            obj_lists[key].objects = []
        obj_lists[key].objects.append(obj)
    for key in obj_lists:
        obj_lists[key]._context = context
        obj_lists[key].obj_reset_changes()
    return obj_lists


def serialize_args(fn):
    """Decorator that will do the arguments serialization before remoting."""
    def wrapper(obj, *args, **kwargs):
        args = [utils.strtime(arg) if isinstance(arg, datetime.datetime)
                else arg for arg in args]
        for k, v in kwargs.items():
            if k == 'exc_val' and v:
                try:
                    # NOTE(danms): When we run this for a remotable method,
                    # we need to attempt to format_message() the exception to
                    # get the sanitized message, and if it's not a
                    # NovaException, fall back to just the exception class
                    # name. However, a remotable will end up calling this again
                    # on the other side of the RPC call, so we must not try
                    # to do that again, otherwise we will always end up with
                    # just str. So, only do that if exc_val is an Exception
                    # class.
                    kwargs[k] = (v.format_message() if isinstance(v, Exception)
                                 else v)
                except Exception:
                    kwargs[k] = v.__class__.__name__
            elif k == 'exc_tb' and v and not isinstance(v, six.string_types):
                kwargs[k] = ''.join(traceback.format_tb(v))
            elif isinstance(v, datetime.datetime):
                kwargs[k] = utils.strtime(v)
        if hasattr(fn, '__call__'):
            return fn(obj, *args, **kwargs)
        # NOTE(danms): We wrap a descriptor, so use that protocol
        return fn.__get__(None, obj)(*args, **kwargs)

    # NOTE(danms): Make this discoverable
    wrapper.remotable = getattr(fn, 'remotable', False)
    wrapper.original_fn = fn
    return (functools.wraps(fn)(wrapper) if hasattr(fn, '__call__')
            else classmethod(wrapper))


def obj_equal_prims(obj_1, obj_2, ignore=None):
    """Compare two primitives for equivalence ignoring some keys.

    This operation tests the primitives of two objects for equivalence.
    Object primitives may contain a list identifying fields that have been
    changed - this is ignored in the comparison. The ignore parameter lists
    any other keys to be ignored.

    :param:obj1: The first object in the comparison
    :param:obj2: The second object in the comparison
    :param:ignore: A list of fields to ignore
    :returns: True if the primitives are equal ignoring changes
    and specified fields, otherwise False.
    """

    def _strip(prim, keys):
        if isinstance(prim, dict):
            for k in keys:
                prim.pop(k, None)
            for v in prim.values():
                _strip(v, keys)
        if isinstance(prim, list):
            for v in prim:
                _strip(v, keys)
        return prim

    if ignore is not None:
        keys = ['nova_object.changes'] + ignore
    else:
        keys = ['nova_object.changes']
    prim_1 = _strip(obj_1.obj_to_primitive(), keys)
    prim_2 = _strip(obj_2.obj_to_primitive(), keys)
    return prim_1 == prim_2
