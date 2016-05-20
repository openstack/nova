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

from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova import utils


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    # FIXME(danms): This is just until we use o.vo's class properties
    # and object base.
    return '_obj_' + name


class NovaObjectRegistry(ovoo_base.VersionedObjectRegistry):
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


remotable_classmethod = ovoo_base.remotable_classmethod
remotable = ovoo_base.remotable


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

    # NOTE(danms): This has some minor change between the nova and o.vo
    # version, so avoid inheriting it for the moment so we can make that
    # transition separately for clarity.
    def obj_reset_changes(self, fields=None, recursive=False):
        """Reset the list of fields that have been changed.

        .. note::

          - This is NOT "revert to previous values"
          - Specifying fields on recursive resets will only be honored at the
            top level. Everything below the top will reset all.

        :param fields: List of fields to reset, or "all" if None.
        :param recursive: Call obj_reset_changes(recursive=True) on
                          any sub-objects within the list of fields
                          being reset.
        """
        if recursive:
            for field in self.obj_get_changes():

                # Ignore fields not in requested set (if applicable)
                if fields and field not in fields:
                    continue

                # Skip any fields that are unset
                if not self.obj_attr_is_set(field):
                    continue

                value = getattr(self, field)

                # Don't reset nulled fields
                if value is None:
                    continue

                # Reset straight Object and ListOfObjects fields
                if isinstance(self.fields[field], obj_fields.ObjectField):
                    value.obj_reset_changes(recursive=True)
                elif isinstance(self.fields[field],
                                obj_fields.ListOfObjectsField):
                    for thing in value:
                        thing.obj_reset_changes(recursive=True)

        if fields:
            self._changed_fields -= set(fields)
        else:
            self._changed_fields.clear()

    # NOTE(danms): This is nova-specific
    @contextlib.contextmanager
    def obj_alternate_context(self, context):
        original_context = self._context
        self._context = context
        try:
            yield
        finally:
            self._context = original_context

    # NOTE(danms): This is nova-specific
    @contextlib.contextmanager
    def obj_as_admin(self):
        """Context manager to make an object call as an admin.

        This temporarily modifies the context embedded in an object to
        be elevated() and restores it after the call completes. Example
        usage:

           with obj.obj_as_admin():
               obj.save()

        """
        if self._context is None:
            raise exception.OrphanedObjectError(method='obj_as_admin',
                                                objtype=self.obj_name())

        original_context = self._context
        self._context = self._context.elevated()
        try:
            yield
        finally:
            self._context = original_context


class NovaObjectDictCompat(ovoo_base.VersionedObjectDictCompat):
    def __iter__(self):
        for name in self.obj_fields:
            if (self.obj_attr_is_set(name) or
                    name in self.obj_extra_fields):
                yield name

    def keys(self):
        return list(self)


class NovaTimestampObject(object):
    """Mixin class for db backed objects with timestamp fields.

    Sqlalchemy models that inherit from the oslo_db TimestampMixin will include
    these fields and the corresponding objects will benefit from this mixin.
    """
    fields = {
        'created_at': obj_fields.DateTimeField(nullable=True),
        'updated_at': obj_fields.DateTimeField(nullable=True),
        }


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
                            for k, v in six.iteritems(values)})
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


def obj_make_list(context, list_obj, item_cls, db_list, **extra_args):
    """Construct an object list from a list of primitives.

    This calls item_cls._from_db_object() on each item of db_list, and
    adds the resulting object to list_obj.

    :param:context: Request context
    :param:list_obj: An ObjectListBase object
    :param:item_cls: The NovaObject class of the objects within the list
    :param:db_list: The list of primitives to convert to objects
    :param:extra_args: Extra arguments to pass to _from_db_object()
    :returns: list_obj
    """
    list_obj.objects = []
    for db_item in db_list:
        item = item_cls._from_db_object(context, item_cls(), db_item,
                                        **extra_args)
        list_obj.objects.append(item)
    list_obj._context = context
    list_obj.obj_reset_changes()
    return list_obj


def serialize_args(fn):
    """Decorator that will do the arguments serialization before remoting."""
    def wrapper(obj, *args, **kwargs):
        args = [utils.strtime(arg) if isinstance(arg, datetime.datetime)
                else arg for arg in args]
        for k, v in six.iteritems(kwargs):
            if k == 'exc_val' and v:
                kwargs[k] = six.text_type(v)
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
