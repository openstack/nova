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
import contextlib
import copy
import datetime
import functools
import traceback

import netaddr
import oslo_messaging as messaging
from oslo_utils import timeutils
import six

from nova import context
from nova import exception
from nova.i18n import _, _LE
from nova import objects
from nova.objects import fields as obj_fields
from nova.openstack.common import log as logging
from nova.openstack.common import versionutils
from nova import utils


LOG = logging.getLogger('object')


class NotSpecifiedSentinel(object):
    pass


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    return '_' + name


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
        for name, field in supercls.fields.items():
            if name not in cls.fields:
                cls.fields[name] = field
    for name, field in cls.fields.iteritems():
        if not isinstance(field, obj_fields.Field):
            raise exception.ObjectFieldInvalid(
                field=name, objname=cls.obj_name())

        def getter(self, name=name):
            attrname = get_attrname(name)
            if not hasattr(self, attrname):
                self.obj_load_attr(name)
            return getattr(self, attrname)

        def setter(self, value, name=name, field=field):
            attrname = get_attrname(name)
            field_value = field.coerce(self, name, value)
            if field.read_only and hasattr(self, attrname):
                # Note(yjiang5): _from_db_object() may iterate
                # every field and write, no exception in such situation.
                if getattr(self, attrname) != field_value:
                    raise exception.ReadOnlyFieldError(field=name)
                else:
                    return

            self._changed_fields.add(name)
            try:
                return setattr(self, attrname, field_value)
            except Exception:
                attr = "%s.%s" % (self.obj_name(), name)
                LOG.exception(_LE('Error setting %(attr)s'), {'attr': attr})
                raise

        setattr(cls, name, property(getter, setter))


class NovaObjectMetaclass(type):
    """Metaclass that allows tracking of object classes."""

    # NOTE(danms): This is what controls whether object operations are
    # remoted. If this is not None, use it to remote things over RPC.
    indirection_api = None

    def __init__(cls, names, bases, dict_):
        if not hasattr(cls, '_obj_classes'):
            # This means this is a base class using the metaclass. I.e.,
            # the 'NovaObject' class.
            cls._obj_classes = collections.defaultdict(list)
            return

        def _vers_tuple(obj):
            return tuple([int(x) for x in obj.VERSION.split(".")])

        # Add the subclass to NovaObject._obj_classes. If the
        # same version already exists, replace it. Otherwise,
        # keep the list with newest version first.
        make_class_properties(cls)
        obj_name = cls.obj_name()
        for i, obj in enumerate(cls._obj_classes[obj_name]):
            if cls.VERSION == obj.VERSION:
                cls._obj_classes[obj_name][i] = cls
                # Update nova.objects with this newer class.
                setattr(objects, obj_name, cls)
                break
            if _vers_tuple(cls) > _vers_tuple(obj):
                # Insert before.
                cls._obj_classes[obj_name].insert(i, cls)
                if i == 0:
                    # Later version than we've seen before. Update
                    # nova.objects.
                    setattr(objects, obj_name, cls)
                break
        else:
            cls._obj_classes[obj_name].append(cls)
            # Either this is the first time we've seen the object or it's
            # an older version than anything we'e seen. Update nova.objects
            # only if it's the first time we've seen this object name.
            if not hasattr(objects, obj_name):
                setattr(objects, obj_name, cls)


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
        ctxt = self._context
        try:
            if isinstance(args[0], (context.RequestContext)):
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
                    field = self.fields[key]
                    # NOTE(ndipanov): Since NovaObjectSerializer will have
                    # deserialized any object fields into objects already,
                    # we do not try to deserialize them again here.
                    if isinstance(value, NovaObject):
                        self[key] = value
                    else:
                        self[key] = field.from_primitive(self, key, value)
            self.obj_reset_changes()
            self._changed_fields = set(updates.get('obj_what_changed', []))
            return result
        else:
            return fn(self, ctxt, *args, **kwargs)

    wrapper.remotable = True
    wrapper.original_fn = fn
    return wrapper


@six.add_metaclass(NovaObjectMetaclass)
class NovaObject(object):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """

    # Object versioning rules
    #
    # Each service has its set of objects, each with a version attached. When
    # a client attempts to call an object method, the server checks to see if
    # the version of that object matches (in a compatible way) its object
    # implementation. If so, cool, and if not, fail.
    #
    # This version is allowed to have three parts, X.Y.Z, where the .Z element
    # is reserved for stable branch backports. The .Z is ignored for the
    # purposes of triggering a backport, which means anything changed under
    # a .Z must be additive and non-destructive such that a node that knows
    # about X.Y can consider X.Y.Z equivalent.
    VERSION = '1.0'

    # The fields present in this object as key:field pairs. For example:
    #
    # fields = { 'foo': fields.IntegerField(),
    #            'bar': fields.StringField(),
    #          }
    fields = {}
    obj_extra_fields = []

    # Table of sub-object versioning information
    #
    # This contains a list of version mappings, by the field name of
    # the subobject. The mappings must be in order of oldest to
    # newest, and are tuples of (my_version, subobject_version). A
    # request to backport this object to $my_version will cause the
    # subobject to be backported to $subobject_version.
    #
    # obj_relationships = {
    #     'subobject1': [('1.2', '1.1'), ('1.4', '1.2')],
    #     'subobject2': [('1.2', '1.0')],
    # }
    #
    # In the above example:
    #
    # - If we are asked to backport our object to version 1.3,
    #   subobject1 will be backported to version 1.1, since it was
    #   bumped to version 1.2 when our version was 1.4.
    # - If we are asked to backport our object to version 1.5,
    #   no changes will be made to subobject1 or subobject2, since
    #   they have not changed since version 1.4.
    # - If we are asked to backlevel our object to version 1.1, we
    #   will remove both subobject1 and subobject2 from the primitive,
    #   since they were not added until version 1.2.
    obj_relationships = {}

    def __init__(self, context=None, **kwargs):
        self._changed_fields = set()
        self._context = context
        for key in kwargs.keys():
            setattr(self, key, kwargs[key])

    def __repr__(self):
        return '%s(%s)' % (
            self.obj_name(),
            ','.join(['%s=%s' % (name,
                                 (self.obj_attr_is_set(name) and
                                  field.stringify(getattr(self, name)) or
                                  '<?>'))
                      for name, field in sorted(self.fields.items())]))

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
            LOG.error(_LE('Unable to instantiate unregistered object type '
                          '%(objtype)s'), dict(objtype=objname))
            raise exception.UnsupportedObjectError(objtype=objname)

        # NOTE(comstud): If there's not an exact match, return the highest
        # compatible version. The objects stored in the class are sorted
        # such that highest version is first, so only set compatible_match
        # once below.
        compatible_match = None

        for objclass in cls._obj_classes[objname]:
            if objclass.VERSION == objver:
                return objclass
            if (not compatible_match and
                    versionutils.is_compatible(objver, objclass.VERSION)):
                compatible_match = objclass

        if compatible_match:
            return compatible_match

        # As mentioned above, latest version is always first in the list.
        latest_ver = cls._obj_classes[objname][0].VERSION
        raise exception.IncompatibleObjectVersion(objname=objname,
                                                  objver=objver,
                                                  supported=latest_ver)

    @classmethod
    def _obj_from_primitive(cls, context, objver, primitive):
        self = cls()
        self._context = context
        self.VERSION = objver
        objdata = primitive['nova_object.data']
        changes = primitive.get('nova_object.changes', [])
        for name, field in self.fields.items():
            if name in objdata:
                setattr(self, name, field.from_primitive(self, name,
                                                         objdata[name]))
        self._changed_fields = set([x for x in changes if x in self.fields])
        return self

    @classmethod
    def obj_from_primitive(cls, primitive, context=None):
        """Object field-by-field hydration."""
        if primitive['nova_object.namespace'] != 'nova':
            # NOTE(danms): We don't do anything with this now, but it's
            # there for "the future"
            raise exception.UnsupportedObjectError(
                objtype='%s.%s' % (primitive['nova_object.namespace'],
                                   primitive['nova_object.name']))
        objname = primitive['nova_object.name']
        objver = primitive['nova_object.version']
        objclass = cls.obj_class_from_name(objname, objver)
        return objclass._obj_from_primitive(context, objver, primitive)

    def __deepcopy__(self, memo):
        """Efficiently make a deep copy of this object."""

        # NOTE(danms): A naive deepcopy would copy more than we need,
        # and since we have knowledge of the volatile bits of the
        # object, we can be smarter here. Also, nested entities within
        # some objects may be uncopyable, so we can avoid those sorts
        # of issues by copying only our field data.

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
            if not obj:
                return
            if isinstance(obj, NovaObject):
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

        target_version = utils.convert_version_to_tuple(target_version)
        for index, versions in enumerate(self.obj_relationships[field]):
            my_version, child_version = versions
            my_version = utils.convert_version_to_tuple(my_version)
            if target_version < my_version:
                if index == 0:
                    # We're backporting to a version from before this
                    # subobject was added: delete it from the primitive.
                    del primitive[field]
                else:
                    # We're in the gap between index-1 and index, so
                    # backport to the older version
                    last_child_version = \
                        self.obj_relationships[field][index - 1][1]
                    _do_backport(last_child_version)
                return
            elif target_version == my_version:
                # This is the first mapping that satisfies the
                # target_version request: backport the object.
                _do_backport(child_version)
                return

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

    def obj_to_primitive(self, target_version=None):
        """Simple base-case dehydration.

        This calls to_primitive() for each item in fields.
        """
        primitive = dict()
        for name, field in self.fields.items():
            if self.obj_attr_is_set(name):
                primitive[name] = field.to_primitive(self, name,
                                                     getattr(self, name))
        if target_version:
            self.obj_make_compatible(primitive, target_version)
        obj = {'nova_object.name': self.obj_name(),
               'nova_object.namespace': 'nova',
               'nova_object.version': target_version or self.VERSION,
               'nova_object.data': primitive}
        if self.obj_what_changed():
            obj['nova_object.changes'] = list(self.obj_what_changed())
        return obj

    def obj_set_defaults(self, *attrs):
        if not attrs:
            attrs = [name for name, field in self.fields.items()
                     if field.default != obj_fields.UnspecifiedDefault]

        for attr in attrs:
            default = self.fields[attr].default
            if default is obj_fields.UnspecifiedDefault:
                raise exception.ObjectActionError(
                    action='set_defaults',
                    reason='No default set for field %s' % attr)
            if not self.obj_attr_is_set(attr):
                setattr(self, attr, default)

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
        raise NotImplementedError(_('Cannot save anything in the base class'))

    def obj_what_changed(self):
        """Returns a set of fields that have been modified."""
        changes = set(self._changed_fields)
        for field in self.fields:
            if (self.obj_attr_is_set(field) and
                    isinstance(getattr(self, field), NovaObject) and
                    getattr(self, field).obj_what_changed()):
                changes.add(field)
        return changes

    def obj_get_changes(self):
        """Returns a dict of changed fields and their new values."""
        changes = {}
        for key in self.obj_what_changed():
            changes[key] = getattr(self, key)
        return changes

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


class NovaObjectDictCompat(object):
    """Mix-in to provide dictionary key access compat

    If an object needs to support attribute access using
    dictionary items instead of object attributes, inherit
    from this class. This should only be used as a temporary
    measure until all callers are converted to use modern
    attribute access.

    NOTE(berrange) This class will eventually be deleted.
    """

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
            return getattr(self, key)

    def update(self, updates):
        """For backwards-compatibility with dict-base objects.

        NOTE(danms): May be removed in the future.
        """
        for key, value in updates.items():
            setattr(self, key, value)


class NovaPersistentObject(object):
    """Mixin class for Persistent objects.
    This adds the fields that we use in common for all persistent objects.
    """
    fields = {
        'created_at': obj_fields.DateTimeField(nullable=True),
        'updated_at': obj_fields.DateTimeField(nullable=True),
        'deleted_at': obj_fields.DateTimeField(nullable=True),
        'deleted': obj_fields.BooleanField(default=False),
        }

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


class ObjectListBase(object):
    """Mixin class for lists of objects.

    This mixin class can be added as a base class for an object that
    is implementing a list of objects. It adds a single field of 'objects',
    which is the list store, and behaves like a list itself. It supports
    serialization of the list of objects automatically.
    """
    fields = {
        'objects': obj_fields.ListOfObjectsField('NovaObject'),
        }

    # This is a dictionary of my_version:child_version mappings so that
    # we can support backleveling our contents based on the version
    # requested of the list object.
    child_versions = {}

    def __init__(self, *args, **kwargs):
        super(ObjectListBase, self).__init__(*args, **kwargs)
        if 'objects' not in kwargs:
            self.objects = []
            self._changed_fields.discard('objects')

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

    def sort(self, cmp=None, key=None, reverse=False):
        self.objects.sort(cmp=cmp, key=key, reverse=reverse)

    def obj_make_compatible(self, primitive, target_version):
        primitives = primitive['objects']
        child_target_version = self.child_versions.get(target_version, '1.0')
        for index, item in enumerate(self.objects):
            self.objects[index].obj_make_compatible(
                primitives[index]['nova_object.data'],
                child_target_version)
            primitives[index]['nova_object.version'] = child_target_version

    def obj_what_changed(self):
        changes = set(self._changed_fields)
        for child in self.objects:
            if child.obj_what_changed():
                changes.add('objects')
        return changes


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
        except exception.IncompatibleObjectVersion as e:
            objver = objprim['nova_object.version']
            if objver.count('.') == 2:
                # NOTE(danms): For our purposes, the .z part of the version
                # should be safe to accept without requiring a backport
                objprim['nova_object.version'] = \
                    '.'.join(objver.split('.')[:2])
                return self._process_object(context, objprim)
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
        for kw in kwargs:
            value_arg = kwargs.get(kw)
            if kw == 'exc_val' and value_arg:
                kwargs[kw] = str(value_arg)
            elif kw == 'exc_tb' and (
                    not isinstance(value_arg, six.string_types) and value_arg):
                kwargs[kw] = ''.join(traceback.format_tb(value_arg))
            elif isinstance(value_arg, datetime.datetime):
                kwargs[kw] = timeutils.isotime(value_arg)
        if hasattr(fn, '__call__'):
            return fn(obj, *args, **kwargs)
        # NOTE(danms): We wrap a descriptor, so use that protocol
        return fn.__get__(None, obj)(*args, **kwargs)

    # NOTE(danms): Make this discoverable
    wrapper.remotable = getattr(fn, 'remotable', False)
    wrapper.original_fn = fn
    return (functools.wraps(fn)(wrapper) if hasattr(fn, '__call__')
            else classmethod(wrapper))
