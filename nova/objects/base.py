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
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovoo_base
from oslo_versionedobjects import exception as ovoo_exc
import six

from nova import context
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova import utils


LOG = logging.getLogger('object')


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    # FIXME(danms): This is just until we use o.vo's class properties
    # and object base.
    return '_obj_' + name


class NovaObjectRegistry(ovoo_base.VersionedObjectRegistry):
    def registration_hook(self, cls, index):
        # NOTE(danms): Set the *latest* version of this class
        newest = self._registry._obj_classes[cls.obj_name()][0]
        setattr(objects, cls.obj_name(), newest)


# These are decorators that mark an object's method as remotable.
# If the metaclass is configured to forward object methods to an
# indirection service, these will result in making an RPC call
# instead of directly calling the implementation in the object. Instead,
# the object implementation on the remote end will perform the
# requested action and the result will be returned here.
def remotable_classmethod(fn):
    """Decorator for remotable classmethods."""
    @functools.wraps(fn)
    def wrapper(cls, context, *args, **kwargs):
        if NovaObject.indirection_api:
            result = NovaObject.indirection_api.object_class_action(
                context, cls.obj_name(), fn.__name__, cls.VERSION,
                args, kwargs)
        else:
            result = fn(cls, context, *args, **kwargs)
            if isinstance(result, NovaObject):
                result._context = context
        return result

    # NOTE(danms): Make this discoverable
    wrapper.remotable = True
    wrapper.original_fn = fn
    return classmethod(wrapper)


# See comment above for remotable_classmethod()
#
# Note that this will use either the provided context, or the one
# stashed in the object. If neither are present, the object is
# "orphaned" and remotable methods cannot be called.
def remotable(fn):
    """Decorator for remotable object methods."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if args and isinstance(args[0], context.RequestContext):
            raise exception.ObjectActionError(
                action=fn.__name__,
                reason='Calling remotables with context is deprecated')
        if self._context is None:
            raise exception.OrphanedObjectError(method=fn.__name__,
                                                objtype=self.obj_name())
        if NovaObject.indirection_api:
            updates, result = NovaObject.indirection_api.object_action(
                self._context, self, fn.__name__, args, kwargs)
            for key, value in six.iteritems(updates):
                if key in self.fields:
                    field = self.fields[key]
                    # NOTE(ndipanov): Since NovaObjectSerializer will have
                    # deserialized any object fields into objects already,
                    # we do not try to deserialize them again here.
                    if isinstance(value, NovaObject):
                        setattr(self, key, value)
                    else:
                        setattr(self, key,
                                field.from_primitive(self, key, value))
            self.obj_reset_changes()
            self._changed_fields = set(updates.get('obj_what_changed', []))
            return result
        else:
            return fn(self, *args, **kwargs)

    wrapper.remotable = True
    wrapper.original_fn = fn
    return wrapper


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

    # NOTE(danms): Keep the compatibility bits in nova separate from o.vo
    # for the time being so that we can keep changes required to use
    # the base version of those risky methods separate from the rest of the
    # simple inherited methods.
    def obj_calculate_child_version(self, target_version, child):
        """Calculate the appropriate version for a child object.

        This is to be used when backporting an object for an older client.
        A sub-object will need to be backported to a suitable version for
        the client as well, and this method will calculate what that
        version should be, based on obj_relationships.

        :param target_version: Version this object is being backported to
        :param child: The child field for which the appropriate version
                      is to be calculated
        :returns: None if the child should be omitted from the backport,
                  otherwise, the version to which the child should be
                  backported
        """
        target_version = utils.convert_version_to_tuple(target_version)
        for index, versions in enumerate(self.obj_relationships[child]):
            my_version, child_version = versions
            my_version = utils.convert_version_to_tuple(my_version)
            if target_version < my_version:
                if index == 0:
                    # We're backporting to a version from before this
                    # subobject was added: delete it from the primitive.
                    return None
                else:
                    # We're in the gap between index-1 and index, so
                    # backport to the older version
                    return self.obj_relationships[child][index - 1][1]
            elif target_version == my_version:
                # This is the first mapping that satisfies the
                # target_version request: backport the object.
                return child_version
        # No need to backport, as far as we know, so return the latest
        # version of the sub-object we know about
        return self.obj_relationships[child][-1][1]

    def _obj_make_obj_compatible(self, primitive, target_version, field):
        """Backlevel a sub-object based on our versioning rules.

        This is responsible for backporting objects contained within
        this object's primitive according to a set of rules we
        maintain about version dependencies between objects. This
        requires that the obj_relationships table in this object is
        correct and up-to-date.

        :param:primitive: The primitive version of this object
        :param:target_version: The version string requested for this object
        :param:field: The name of the field in this object containing the
                      sub-object to be backported
        """

        def _do_backport(to_version):
            obj = getattr(self, field)
            if obj is None:
                return
            if isinstance(obj, NovaObject):
                if to_version != primitive[field]['nova_object.version']:
                    obj.obj_make_compatible(
                        primitive[field]['nova_object.data'],
                        to_version)
                primitive[field]['nova_object.version'] = to_version
            elif isinstance(obj, list):
                for i, element in enumerate(obj):
                    element.obj_make_compatible(
                        primitive[field][i]['nova_object.data'],
                        to_version)
                    primitive[field][i]['nova_object.version'] = to_version

        child_version = self.obj_calculate_child_version(target_version, field)
        if child_version is None:
            del primitive[field]
        else:
            _do_backport(child_version)

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version.

        This is responsible for taking the primitive representation of
        an object and making it suitable for the given target_version.
        This may mean converting the format of object attributes, removing
        attributes that have been added since the target version, etc. In
        general:

        - If a new version of an object adds a field, this routine
          should remove it for older versions.
        - If a new version changed or restricted the format of a field, this
          should convert it back to something a client knowing only of the
          older version will tolerate.
        - If an object that this object depends on is bumped, then this
          object should also take a version bump. Then, this routine should
          backlevel the dependent object (by calling its obj_make_compatible())
          if the requested version of this object is older than the version
          where the new dependent object was added.

        :param:primitive: The result of self.obj_to_primitive()
        :param:target_version: The version string requested by the recipient
        of the object
        :raises: nova.exception.UnsupportedObjectError if conversion
        is not possible for some reason
        """
        for key, field in self.fields.items():
            if not isinstance(field, (obj_fields.ObjectField,
                                      obj_fields.ListOfObjectsField)):
                continue
            if not self.obj_attr_is_set(key):
                continue
            if key not in self.obj_relationships:
                # NOTE(danms): This is really a coding error and shouldn't
                # happen unless we miss something
                raise exception.ObjectActionError(
                    action='obj_make_compatible',
                    reason='No rule for %s' % key)
            self._obj_make_obj_compatible(primitive, target_version, key)

    # NOTE(danms): This has some minor change between the nova and o.vo
    # version, so avoid inheriting it for the moment so we can make that
    # transition separately for clarity.
    def obj_reset_changes(self, fields=None, recursive=False):
        """Reset the list of fields that have been changed.

        :param fields: List of fields to reset, or "all" if None.
        :param recursive: Call obj_reset_changes(recursive=True) on
                          any sub-objects within the list of fields
                          being reset.

        NOTE: This is NOT "revert to previous values"
        NOTE: Specifying fields on recursive resets will only be
              honored at the top level. Everything below the top
              will reset all.
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
            supported = NovaObjectRegistry.obj_classes().get(objname, [])
            if supported:
                objinst = self.conductor.object_backport(context, objprim,
                                                         supported[0].VERSION)
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
        args = [timeutils.strtime(at=arg) if isinstance(arg, datetime.datetime)
                else arg for arg in args]
        for k, v in six.iteritems(kwargs):
            if k == 'exc_val' and v:
                kwargs[k] = str(v)
            elif k == 'exc_tb' and v and not isinstance(v, six.string_types):
                kwargs[k] = ''.join(traceback.format_tb(v))
            elif isinstance(v, datetime.datetime):
                kwargs[k] = timeutils.strtime(at=v)
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
