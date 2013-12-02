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

import collections
import copy
import functools

from nova import context
from nova import exception
from nova.objects import utils as obj_utils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common
import nova.openstack.common.rpc.serializer


LOG = logging.getLogger('object')


class NotSpecifiedSentinel:
    pass


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    return '_%s' % name


def make_class_properties(cls):
    # NOTE(danms/comstud): Inherit fields from super classes.
    # mro() returns the current class first and returns 'object' last, so
    # those can be skipped.  Also be careful to not overwrite any fields
    # that already exist.  And make sure each cls has its own copy of
    # fields and that it is not sharing the dict with a super class.
    cls.fields = dict(cls.fields)
    for supercls in cls.mro()[1:-1]:
        if not hasattr(supercls, 'fields'):
            continue
        for field, typefn in supercls.fields.items():
            if field not in cls.fields:
                cls.fields[field] = typefn
    for name, typefn in cls.fields.iteritems():

        def getter(self, name=name):
            attrname = get_attrname(name)
            if not hasattr(self, attrname):
                self.obj_load_attr(name)
            return getattr(self, attrname)

        def setter(self, value, name=name, typefn=typefn):
            self._changed_fields.add(name)
            try:
                return setattr(self, get_attrname(name), typefn(value))
            except Exception:
                attr = "%s.%s" % (self.obj_name(), name)
                LOG.exception(_('Error setting %(attr)s') %
                              {'attr': attr})
                raise

        setattr(cls, name, property(getter, setter))


class NovaObjectMetaclass(type):
    """Metaclass that allows tracking of object classes."""

    # NOTE(danms): This is what controls whether object operations are
    # remoted. If this is not None, use it to remote things over RPC.
    indirection_api = None

    def __init__(cls, names, bases, dict_):
        if not hasattr(cls, '_obj_classes'):
            # This will be set in the 'NovaObject' class.
            cls._obj_classes = collections.defaultdict(list)
        else:
            # Add the subclass to NovaObject._obj_classes
            make_class_properties(cls)
            cls._obj_classes[cls.obj_name()].append(cls)


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
        ctxt = self._context
        try:
            if isinstance(args[0], (context.RequestContext,
                                    rpc_common.CommonRpcContext)):
                ctxt = args[0]
                args = args[1:]
        except IndexError:
            pass
        if ctxt is None:
            raise exception.OrphanedObjectError(method=fn.__name__,
                                                objtype=self.obj_name())
        # Force this to be set if it wasn't before.
        self._context = ctxt
        if NovaObject.indirection_api:
            updates, result = NovaObject.indirection_api.object_action(
                ctxt, self, fn.__name__, args, kwargs)
            for key, value in updates.iteritems():
                if key in self.fields:
                    self[key] = self._attr_from_primitive(key, value)
            self.obj_reset_changes()
            self._changed_fields = set(updates.get('obj_what_changed', []))
            return result
        else:
            return fn(self, ctxt, *args, **kwargs)
    return wrapper


# Object versioning rules
#
# Each service has its set of objects, each with a version attached. When
# a client attempts to call an object method, the server checks to see if
# the version of that object matches (in a compatible way) its object
# implementation. If so, cool, and if not, fail.
def check_object_version(server, client):
    try:
        client_major, _client_minor = client.split('.')
        server_major, _server_minor = server.split('.')
        client_minor = int(_client_minor)
        server_minor = int(_server_minor)
    except ValueError:
        raise exception.IncompatibleObjectVersion(
            _('Invalid version string'))

    if client_major != server_major:
        raise exception.IncompatibleObjectVersion(
            dict(client=client_major, server=server_major))
    if client_minor > server_minor:
        raise exception.IncompatibleObjectVersion(
            dict(client=client_minor, server=server_minor))


class NovaObject(object):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """
    __metaclass__ = NovaObjectMetaclass

    # Version of this object (see rules above check_object_version())
    VERSION = '1.0'

    # The fields present in this object as key:typefn pairs. For example:
    #
    # fields = { 'foo': int,
    #            'bar': str,
    #            'baz': lambda x: str(x).ljust(8),
    #          }
    fields = {}
    obj_extra_fields = []

    def __init__(self):
        self._changed_fields = set()
        self._context = None

    @classmethod
    def obj_name(cls):
        """Return a canonical name for this object which will be used over
        the wire for remote hydration.
        """
        return cls.__name__

    @classmethod
    def obj_class_from_name(cls, objname, objver):
        """Returns a class from the registry based on a name and version."""
        if objname not in cls._obj_classes:
            LOG.error(_('Unable to instantiate unregistered object type '
                        '%(objtype)s') % dict(objtype=objname))
            raise exception.UnsupportedObjectError(objtype=objname)

        latest = None
        compatible_match = None
        for objclass in cls._obj_classes[objname]:
            if objclass.VERSION == objver:
                return objclass

            version_bits = tuple([int(x) for x in objclass.VERSION.split(".")])
            if latest is None:
                latest = version_bits
            elif latest < version_bits:
                latest = version_bits

            try:
                check_object_version(objclass.VERSION, objver)
                compatible_match = objclass
            except exception.IncompatibleObjectVersion:
                pass

        if compatible_match:
            return compatible_match

        latest_ver = '%i.%i' % latest
        raise exception.IncompatibleObjectVersion(objname=objname,
                                                  objver=objver,
                                                  supported=latest_ver)

    def _attr_from_primitive(self, attribute, value):
        """Attribute deserialization dispatcher.

        This calls self._attr_foo_from_primitive(value) for an attribute
        foo with value, if it exists, otherwise it assumes the value
        is suitable for the attribute's setter method.
        """
        handler = '_attr_%s_from_primitive' % attribute
        if hasattr(self, handler):
            return getattr(self, handler)(value)
        return value

    @classmethod
    def obj_from_primitive(cls, primitive, context=None):
        """Simple base-case hydration.

        This calls self._attr_from_primitive() for each item in fields.
        """
        if primitive['nova_object.namespace'] != 'nova':
            # NOTE(danms): We don't do anything with this now, but it's
            # there for "the future"
            raise exception.UnsupportedObjectError(
                objtype='%s.%s' % (primitive['nova_object.namespace'],
                                   primitive['nova_object.name']))
        objname = primitive['nova_object.name']
        objver = primitive['nova_object.version']
        objdata = primitive['nova_object.data']
        objclass = cls.obj_class_from_name(objname, objver)
        self = objclass()
        self._context = context
        for name in self.fields:
            if name in objdata:
                setattr(self, name,
                        self._attr_from_primitive(name, objdata[name]))
        changes = primitive.get('nova_object.changes', [])
        self._changed_fields = set([x for x in changes if x in self.fields])
        return self

    def _attr_to_primitive(self, attribute):
        """Attribute serialization dispatcher.

        This calls self._attr_foo_to_primitive() for an attribute foo,
        if it exists, otherwise it assumes the attribute itself is
        primitive-enough to be sent over the RPC wire.
        """
        handler = '_attr_%s_to_primitive' % attribute
        if hasattr(self, handler):
            return getattr(self, handler)()
        else:
            return getattr(self, attribute)

    def __deepcopy__(self, memo):
        nobj = self.__class__()
        nobj._context = self._context
        for name in self.fields:
            if self.obj_attr_is_set(name):
                nval = copy.deepcopy(getattr(self, name), memo)
                setattr(nobj, name, nval)
        nobj._changed_fields = set(self._changed_fields)
        return nobj

    def obj_clone(self):
        """Create a copy."""
        return copy.deepcopy(self)

    def obj_to_primitive(self):
        """Simple base-case dehydration.

        This calls self._attr_to_primitive() for each item in fields.
        """
        primitive = dict()
        for name in self.fields:
            if self.obj_attr_is_set(name):
                primitive[name] = self._attr_to_primitive(name)
        obj = {'nova_object.name': self.obj_name(),
               'nova_object.namespace': 'nova',
               'nova_object.version': self.VERSION,
               'nova_object.data': primitive}
        if self.obj_what_changed():
            obj['nova_object.changes'] = list(self.obj_what_changed())
        return obj

    def obj_load_attr(self, attrname):
        """Load an additional attribute from the real object.

        This should use self._conductor, and cache any data that might
        be useful for future load operations.
        """
        raise NotImplementedError(
            _("Cannot load '%s' in the base class") % attrname)

    def save(self, context):
        """Save the changed fields back to the store.

        This is optional for subclasses, but is presented here in the base
        class for consistency among those that do.
        """
        raise NotImplementedError('Cannot save anything in the base class')

    def obj_what_changed(self):
        """Returns a set of fields that have been modified."""
        return self._changed_fields

    def obj_get_changes(self):
        """Returns a dict of changed fields and their new values."""
        changes = {}
        for key in self.obj_what_changed():
            changes[key] = self[key]
        return changes

    def obj_reset_changes(self, fields=None):
        """Reset the list of fields that have been changed.

        Note that this is NOT "revert to previous values"
        """
        if fields:
            self._changed_fields -= set(fields)
        else:
            self._changed_fields.clear()

    def obj_attr_is_set(self, attrname):
        """Test object to see if attrname is present.

        Returns True if the named attribute has a value set, or
        False if not. Raises AttributeError if attrname is not
        a valid attribute for this object.
        """
        if attrname not in self.obj_fields:
            raise AttributeError(
                _("%(objname)s object has no attribute '%(attrname)s'") %
                {'objname': self.obj_name(), 'attrname': attrname})
        return hasattr(self, get_attrname(attrname))

    @property
    def obj_fields(self):
        return self.fields.keys() + self.obj_extra_fields

    # dictish syntactic sugar
    def iteritems(self):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        for name in self.obj_fields:
            if (self.obj_attr_is_set(name) or
                    name in self.obj_extra_fields):
                yield name, getattr(self, name)

    items = lambda self: list(self.iteritems())

    def __getitem__(self, name):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        return getattr(self, name)

    def __setitem__(self, name, value):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        setattr(self, name, value)

    def __contains__(self, name):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        try:
            return self.obj_attr_is_set(name)
        except AttributeError:
            return False

    def get(self, key, value=NotSpecifiedSentinel):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        if key not in self.obj_fields:
            raise AttributeError("'%s' object has no attribute '%s'" % (
                    self.__class__, key))
        if value != NotSpecifiedSentinel and not self.obj_attr_is_set(key):
            return value
        else:
            return self[key]

    def update(self, updates):
        """For backwards-compatibility with dict-base objects.

        NOTE(danms): May be removed in the future.
        """
        for key, value in updates.items():
            self[key] = value


class NovaPersistentObject(object):
    """Mixin class for Persistent objects.

    This adds the fields that we use in common for all persisent objects.
    """
    fields = {
        'created_at': obj_utils.datetime_or_str_or_none,
        'updated_at': obj_utils.datetime_or_str_or_none,
        'deleted_at': obj_utils.datetime_or_str_or_none,
        'deleted': bool,
        }

    _attr_created_at_from_primitive = obj_utils.dt_deserializer
    _attr_updated_at_from_primitive = obj_utils.dt_deserializer
    _attr_deleted_at_from_primitive = obj_utils.dt_deserializer
    _attr_created_at_to_primitive = obj_utils.dt_serializer('created_at')
    _attr_updated_at_to_primitive = obj_utils.dt_serializer('updated_at')
    _attr_deleted_at_to_primitive = obj_utils.dt_serializer('deleted_at')


class ObjectListBase(object):
    """Mixin class for lists of objects.

    This mixin class can be added as a base class for an object that
    is implementing a list of objects. It adds a single field of 'objects',
    which is the list store, and behaves like a list itself. It supports
    serialization of the list of objects automatically.
    """
    fields = {
        'objects': list,
        }

    def __iter__(self):
        """List iterator interface."""
        return iter(self.objects)

    def __len__(self):
        """List length."""
        return len(self.objects)

    def __getitem__(self, index):
        """List index access."""
        if isinstance(index, slice):
            new_obj = self.__class__()
            new_obj.objects = self.objects[index]
            # NOTE(danms): We must be mixed in with a NovaObject!
            new_obj.obj_reset_changes()
            new_obj._context = self._context
            return new_obj
        return self.objects[index]

    def __contains__(self, value):
        """List membership test."""
        return value in self.objects

    def count(self, value):
        """List count of value occurrences."""
        return self.objects.count(value)

    def index(self, value):
        """List index of value."""
        return self.objects.index(value)

    def _attr_objects_to_primitive(self):
        """Serialization of object list."""
        return [x.obj_to_primitive() for x in self.objects]

    def _attr_objects_from_primitive(self, value):
        """Deserialization of object list."""
        objects = []
        for entity in value:
            obj = NovaObject.obj_from_primitive(entity, context=self._context)
            objects.append(obj)
        return objects


class NovaObjectSerializer(nova.openstack.common.rpc.serializer.Serializer):
    """A NovaObject-aware Serializer.

    This implements the Oslo Serializer interface and provides the
    ability to serialize and deserialize NovaObject entities. Any service
    that needs to accept or return NovaObjects as arguments or result values
    should pass this to its RpcProxy and RpcDispatcher objects.
    """

    @property
    def conductor(self):
        if not hasattr(self, '_conductor'):
            from nova.conductor import api as conductor_api
            self._conductor = conductor_api.API()
        return self._conductor

    def _process_object(self, context, objprim):
        try:
            objinst = NovaObject.obj_from_primitive(objprim, context=context)
        except exception.IncompatibleObjectVersion as e:
            objinst = self.conductor.object_backport(context, objprim,
                                                     e.kwargs['supported'])
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
        if iterable == set:
            # NOTE(danms): A set can't have an unhashable value inside, such as
            # a dict. Convert sets to tuples, which is fine, since we can't
            # send them over RPC anyway.
            iterable = tuple
        return iterable([action_fn(context, value) for value in values])

    def serialize_entity(self, context, entity):
        if isinstance(entity, (tuple, list, set)):
            entity = self._process_iterable(context, self.serialize_entity,
                                            entity)
        elif (hasattr(entity, 'obj_to_primitive') and
              callable(entity.obj_to_primitive)):
            entity = entity.obj_to_primitive()
        return entity

    def deserialize_entity(self, context, entity):
        if isinstance(entity, dict) and 'nova_object.name' in entity:
            entity = self._process_object(context, entity)
        elif isinstance(entity, (tuple, list, set)):
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
        for key, value in obj.iteritems():
            result[key] = obj_to_primitive(value)
        return result
    else:
        return obj


def obj_make_list(context, list_obj, item_cls, db_list, **extra_args):
    """Construct an object list from a list of primitives.

    This calls item_cls._from_db_object() on each item of db_list, and
    adds the resulting object to list_obj.

    :param:context: Request contextr
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
