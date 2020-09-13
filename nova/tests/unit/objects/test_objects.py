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

import collections
import contextlib
import copy
import datetime
import os
import pprint

import fixtures
import mock
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import exception as ovo_exc
from oslo_versionedobjects import fixture
import six

from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import virt_device_metadata
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_notifier
from nova import utils


class MyOwnedObject(base.NovaPersistentObject, base.NovaObject):
    VERSION = '1.0'
    fields = {'baz': fields.IntegerField()}


class MyObj(base.NovaPersistentObject, base.NovaObject,
            base.NovaObjectDictCompat):
    VERSION = '1.6'
    fields = {'foo': fields.IntegerField(default=1),
              'bar': fields.StringField(),
              'missing': fields.StringField(),
              'readonly': fields.IntegerField(read_only=True),
              'rel_object': fields.ObjectField('MyOwnedObject', nullable=True),
              'rel_objects': fields.ListOfObjectsField('MyOwnedObject',
                                                       nullable=True),
              'mutable_default': fields.ListOfStringsField(default=[]),
              }

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        self = MyObj()
        self.foo = db_obj['foo']
        self.bar = db_obj['bar']
        self.missing = db_obj['missing']
        self.readonly = 1
        self._context = context
        return self

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls(context=context, foo=1, bar='bar')
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self):
        return 'polo'

    @base.remotable
    def _update_test(self):
        self.bar = 'updated'

    @base.remotable
    def save(self):
        self.obj_reset_changes()

    @base.remotable
    def refresh(self):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @base.remotable
    def modify_save_modify(self):
        self.bar = 'meow'
        self.save()
        self.foo = 42
        self.rel_object = MyOwnedObject(baz=42)

    def obj_make_compatible(self, primitive, target_version):
        super(MyObj, self).obj_make_compatible(primitive, target_version)
        # NOTE(danms): Simulate an older version that had a different
        # format for the 'bar' attribute
        if target_version == '1.1' and 'bar' in primitive:
            primitive['bar'] = 'old%s' % primitive['bar']


class RandomMixInWithNoFields(object):
    """Used to test object inheritance using a mixin that has no fields."""
    pass


@base.NovaObjectRegistry.register_if(False)
class SubclassedObject(RandomMixInWithNoFields, MyObj):
    fields = {'new_field': fields.StringField()}


class TestObjToPrimitive(test.NoDBTestCase):

    def test_obj_to_primitive_list(self):
        @base.NovaObjectRegistry.register_if(False)
        class MyObjElement(base.NovaObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyObjElement, self).__init__()
                self.foo = foo

        @base.NovaObjectRegistry.register_if(False)
        class MyList(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('MyObjElement')}

        mylist = MyList()
        mylist.objects = [MyObjElement(1), MyObjElement(2), MyObjElement(3)]
        self.assertEqual([1, 2, 3],
                         [x['foo'] for x in base.obj_to_primitive(mylist)])

    def test_obj_to_primitive_dict(self):
        base.NovaObjectRegistry.register(MyObj)
        myobj = MyObj(foo=1, bar='foo')
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        base.NovaObjectRegistry.register(MyObj)

        class MyList(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('MyObj')}

        mylist = MyList(objects=[MyObj(), MyObj()])
        for i, value in enumerate(mylist):
            value.foo = i
        self.assertEqual([{'foo': 0}, {'foo': 1}],
                         base.obj_to_primitive(mylist))

    def test_obj_to_primitive_with_ip_addr(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestObject(base.NovaObject):
            fields = {'addr': fields.IPAddressField(),
                      'cidr': fields.IPNetworkField()}

        obj = TestObject(addr='1.2.3.4', cidr='1.1.1.1/16')
        self.assertEqual({'addr': '1.2.3.4', 'cidr': '1.1.1.1/16'},
                         base.obj_to_primitive(obj))


def compare_obj(test, obj, db_obj, subs=None, allow_missing=None,
                comparators=None):
    """Compare a NovaObject and a dict-like database object.

    This automatically converts TZ-aware datetimes and iterates over
    the fields of the object.

    :param:test: The TestCase doing the comparison
    :param:obj: The NovaObject to examine
    :param:db_obj: The dict-like database object to use as reference
    :param:subs: A dict of objkey=dbkey field substitutions
    :param:allow_missing: A list of fields that may not be in db_obj
    :param:comparators: Map of comparator functions to use for certain fields
    """

    if subs is None:
        subs = {}
    if allow_missing is None:
        allow_missing = []
    if comparators is None:
        comparators = {}

    for key in obj.fields:
        if key in allow_missing and not obj.obj_attr_is_set(key):
            continue
        obj_val = getattr(obj, key)
        db_key = subs.get(key, key)
        db_val = db_obj[db_key]
        if isinstance(obj_val, datetime.datetime):
            obj_val = obj_val.replace(tzinfo=None)

        if key in comparators:
            comparator = comparators[key]
            comparator(db_val, obj_val)
        else:
            test.assertEqual(db_val, obj_val)


class _BaseTestCase(test.TestCase):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        # NOTE(danms): register these here instead of at import time
        # so that they're not always present
        base.NovaObjectRegistry.register(MyObj)
        base.NovaObjectRegistry.register(MyOwnedObject)

    def compare_obj(self, obj, db_obj, subs=None, allow_missing=None,
                    comparators=None):
        compare_obj(self, obj, db_obj, subs=subs, allow_missing=allow_missing,
                    comparators=comparators)

    def str_comparator(self, expected, obj_val):
        """Compare an object field to a string in the db by performing
        a simple coercion on the object field value.
        """
        self.assertEqual(expected, str(obj_val))


class _LocalTest(_BaseTestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        # Just in case
        self.useFixture(nova_fixtures.IndirectionAPIFixture(None))


@contextlib.contextmanager
def things_temporarily_local():
    # Temporarily go non-remote so the conductor handles
    # this request directly
    _api = base.NovaObject.indirection_api
    base.NovaObject.indirection_api = None
    yield
    base.NovaObject.indirection_api = _api


# FIXME(danms): We shouldn't be overriding any of this, but need to
# for the moment because of the mocks in the base fixture that don't
# hit our registry subclass.
class FakeIndirectionHack(fixture.FakeIndirectionAPI):
    def object_action(self, context, objinst, objmethod, args, kwargs):
        objinst = self._ser.deserialize_entity(
            context, self._ser.serialize_entity(
                context, objinst))
        objmethod = six.text_type(objmethod)
        args = self._ser.deserialize_entity(
            None, self._ser.serialize_entity(None, args))
        kwargs = self._ser.deserialize_entity(
            None, self._ser.serialize_entity(None, kwargs))
        original = objinst.obj_clone()
        with mock.patch('nova.objects.base.NovaObject.'
                        'indirection_api', new=None):
            result = getattr(objinst, objmethod)(*args, **kwargs)
        updates = self._get_changes(original, objinst)
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        objname = six.text_type(objname)
        objmethod = six.text_type(objmethod)
        objver = six.text_type(objver)
        args = self._ser.deserialize_entity(
            None, self._ser.serialize_entity(None, args))
        kwargs = self._ser.deserialize_entity(
            None, self._ser.serialize_entity(None, kwargs))
        cls = base.NovaObject.obj_class_from_name(objname, objver)
        with mock.patch('nova.objects.base.NovaObject.'
                        'indirection_api', new=None):
            result = getattr(cls, objmethod)(context, *args, **kwargs)
        manifest = ovo_base.obj_tree_get_versions(objname)
        return (base.NovaObject.obj_from_primitive(
            result.obj_to_primitive(target_version=objver,
                                    version_manifest=manifest),
            context=context)
            if isinstance(result, base.NovaObject) else result)

    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        objname = six.text_type(objname)
        objmethod = six.text_type(objmethod)
        object_versions = {six.text_type(o): six.text_type(v)
                           for o, v in object_versions.items()}
        args, kwargs = self._canonicalize_args(context, args, kwargs)
        objver = object_versions[objname]
        cls = base.NovaObject.obj_class_from_name(objname, objver)
        with mock.patch('nova.objects.base.NovaObject.'
                        'indirection_api', new=None):
            result = getattr(cls, objmethod)(context, *args, **kwargs)
        return (base.NovaObject.obj_from_primitive(
            result.obj_to_primitive(target_version=objver),
            context=context)
            if isinstance(result, base.NovaObject) else result)


class IndirectionFixture(fixtures.Fixture):
    def setUp(self):
        super(IndirectionFixture, self).setUp()
        ser = base.NovaObjectSerializer()
        self.indirection_api = FakeIndirectionHack(serializer=ser)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.base.NovaObject.indirection_api',
            self.indirection_api))


class _RemoteTest(_BaseTestCase):
    def setUp(self):
        super(_RemoteTest, self).setUp()
        self.useFixture(IndirectionFixture())


class _TestObject(object):
    def test_object_attrs_in_init(self):
        # Spot check a few
        objects.Instance
        objects.InstanceInfoCache
        objects.SecurityGroup
        # Now check the test one in this file. Should be newest version
        self.assertEqual('1.6', objects.MyObj.VERSION)

    def test_hydration_type_error(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'nova',
                     'nova_object.version': '1.5',
                     'nova_object.data': {'foo': 'a'}}
        self.assertRaises(ValueError, MyObj.obj_from_primitive, primitive)

    def test_hydration(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'nova',
                     'nova_object.version': '1.5',
                     'nova_object.data': {'foo': 1}}
        real_method = MyObj._obj_from_primitive

        def _obj_from_primitive(*args):
            return real_method(*args)

        with mock.patch.object(MyObj, '_obj_from_primitive') as ofp:
            ofp.side_effect = _obj_from_primitive
            obj = MyObj.obj_from_primitive(primitive)
            ofp.assert_called_once_with(None, '1.5', primitive)
        self.assertEqual(obj.foo, 1)

    def test_hydration_version_different(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'nova',
                     'nova_object.version': '1.2',
                     'nova_object.data': {'foo': 1}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj.foo, 1)
        self.assertEqual('1.2', obj.VERSION)

    def test_hydration_bad_ns(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'foo',
                     'nova_object.version': '1.5',
                     'nova_object.data': {'foo': 1}}
        self.assertRaises(ovo_exc.UnsupportedObjectError,
                          MyObj.obj_from_primitive, primitive)

    def test_hydration_additional_unexpected_stuff(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'nova',
                     'nova_object.version': '1.5.1',
                     'nova_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): If we call obj_from_primitive() directly
        # with a version containing .z, we'll get that version
        # in the resulting object. In reality, when using the
        # serializer, we'll get that snipped off (tested
        # elsewhere)
        self.assertEqual('1.5.1', obj.VERSION)

    def test_dehydration(self):
        expected = {'nova_object.name': 'MyObj',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.6',
                    'nova_object.data': {'foo': 1}}
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_object_property(self):
        obj = MyObj(foo=1)
        self.assertEqual(obj.foo, 1)

    def test_object_property_type_error(self):
        obj = MyObj()

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_load(self):
        obj = MyObj()
        self.assertEqual(obj.bar, 'loaded!')

    def test_load_in_base(self):
        @base.NovaObjectRegistry.register_if(False)
        class Foo(base.NovaObject):
            fields = {'foobar': fields.IntegerField()}
        obj = Foo()
        with self.assertRaisesRegex(NotImplementedError, ".*foobar.*"):
            obj.foobar

    def test_loaded_in_primitive(self):
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.bar, 'loaded!')
        expected = {'nova_object.name': 'MyObj',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.6',
                    'nova_object.changes': ['bar'],
                    'nova_object.data': {'foo': 1,
                                         'bar': 'loaded!'}}
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_changes_in_primitive(self):
        obj = MyObj(foo=123)
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        primitive = obj.obj_to_primitive()
        self.assertIn('nova_object.changes', primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj2.obj_what_changed(), set(['foo']))
        obj2.obj_reset_changes()
        self.assertEqual(obj2.obj_what_changed(), set())

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(ovo_exc.OrphanedObjectError,
                          obj._update_test)

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj._update_test()
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'bar']))
        self.assertEqual(obj.foo, 123)

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.save()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify()
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'rel_object']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
        self.assertIsInstance(obj.rel_object, MyOwnedObject)

    def test_changed_with_sub_object(self):
        @base.NovaObjectRegistry.register_if(False)
        class ParentObject(base.NovaObject):
            fields = {'foo': fields.IntegerField(),
                      'bar': fields.ObjectField('MyObj'),
                      }
        obj = ParentObject()
        self.assertEqual(set(), obj.obj_what_changed())
        obj.foo = 1
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        bar = MyObj()
        obj.bar = bar
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())
        obj.obj_reset_changes()
        self.assertEqual(set(), obj.obj_what_changed())
        bar.foo = 1
        self.assertEqual(set(['bar']), obj.obj_what_changed())

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        result = obj.marco()
        self.assertEqual(result, 'polo')

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.foo, 1)
        obj._update_test()
        self.assertEqual(obj.bar, 'updated')

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5)
        obj = MyObj(created_at=dt, updated_at=dt, deleted_at=None,
                    deleted=False)
        expected = {'nova_object.name': 'MyObj',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.6',
                    'nova_object.changes':
                        ['deleted', 'created_at', 'deleted_at', 'updated_at'],
                    'nova_object.data':
                        {'created_at': utils.isotime(dt),
                         'updated_at': utils.isotime(dt),
                         'deleted_at': None,
                         'deleted': False,
                         }
                    }
        actual = obj.obj_to_primitive()
        self.assertJsonEqual(actual, expected)

    def test_contains(self):
        obj = MyObj()
        self.assertNotIn('foo', obj)
        obj.foo = 1
        self.assertIn('foo', obj)
        self.assertNotIn('does_not_exist', obj)

    def test_obj_attr_is_set(self):
        obj = MyObj(foo=1)
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_get(self):
        obj = MyObj(foo=1)
        # Foo has value, should not get the default
        self.assertEqual(obj.get('foo', 2), 1)
        # Foo has value, should return the value without error
        self.assertEqual(obj.get('foo'), 1)
        # Bar is not loaded, so we should get the default
        self.assertEqual(obj.get('bar', 'not-loaded'), 'not-loaded')
        # Bar without a default should lazy-load
        self.assertEqual(obj.get('bar'), 'loaded!')
        # Bar now has a default, but loaded value should be returned
        self.assertEqual(obj.get('bar', 'not-loaded'), 'loaded!')
        # Invalid attribute should raise AttributeError
        self.assertRaises(AttributeError, obj.get, 'nothing')
        # ...even with a default
        self.assertRaises(AttributeError, obj.get, 'nothing', 3)

    def test_object_inheritance(self):
        base_fields = base.NovaPersistentObject.fields.keys()
        myobj_fields = (['foo', 'bar', 'missing',
                         'readonly', 'rel_object',
                         'rel_objects', 'mutable_default'] +
                        list(base_fields))
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(SubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(SubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(SubclassedObject.fields.keys()))

    def test_obj_alternate_context(self):
        obj = MyObj(context=self.context)
        with obj.obj_alternate_context(mock.sentinel.alt_ctx):
            self.assertEqual(mock.sentinel.alt_ctx,
                             obj._context)
        self.assertEqual(self.context, obj._context)

    def test_get_changes(self):
        obj = MyObj()
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_obj_fields(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestObj(base.NovaObject):
            fields = {'foo': fields.IntegerField()}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj()
        self.assertEqual(['foo', 'bar'], obj.obj_fields)

    def test_obj_constructor(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        self.assertEqual(123, obj.foo)
        self.assertEqual('abc', obj.bar)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())

    def test_obj_read_only(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        obj.readonly = 1
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
                          obj, 'readonly', 2)

    def test_obj_mutable_default(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        obj.mutable_default = None
        obj.mutable_default.append('s1')
        self.assertEqual(obj.mutable_default, ['s1'])

        obj1 = MyObj(context=self.context, foo=123, bar='abc')
        obj1.mutable_default = None
        obj1.mutable_default.append('s2')
        self.assertEqual(obj1.mutable_default, ['s2'])

    def test_obj_mutable_default_set_default(self):
        obj1 = MyObj(context=self.context, foo=123, bar='abc')
        obj1.obj_set_defaults('mutable_default')
        self.assertEqual(obj1.mutable_default, [])
        obj1.mutable_default.append('s1')
        self.assertEqual(obj1.mutable_default, ['s1'])

        obj2 = MyObj(context=self.context, foo=123, bar='abc')
        obj2.obj_set_defaults('mutable_default')
        self.assertEqual(obj2.mutable_default, [])
        obj2.mutable_default.append('s2')
        self.assertEqual(obj2.mutable_default, ['s2'])

    def test_obj_repr(self):
        obj = MyObj(foo=123)
        self.assertEqual('MyObj(bar=<?>,created_at=<?>,deleted=<?>,'
                         'deleted_at=<?>,foo=123,missing=<?>,'
                         'mutable_default=<?>,readonly=<?>,rel_object=<?>,'
                         'rel_objects=<?>,updated_at=<?>)',
                         repr(obj))

    def test_obj_make_obj_compatible(self):
        subobj = MyOwnedObject(baz=1)
        subobj.VERSION = '1.2'
        obj = MyObj(rel_object=subobj)
        obj.obj_relationships = {
            'rel_object': [('1.5', '1.1'), ('1.7', '1.2')],
        }
        orig_primitive = obj.obj_to_primitive()['nova_object.data']
        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            primitive = copy.deepcopy(orig_primitive)
            obj._obj_make_obj_compatible(primitive, '1.8', 'rel_object')
            self.assertFalse(mock_compat.called)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            primitive = copy.deepcopy(orig_primitive)
            obj._obj_make_obj_compatible(primitive, '1.7', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.2')

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            primitive = copy.deepcopy(orig_primitive)
            obj._obj_make_obj_compatible(primitive, '1.6', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['nova_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            primitive = copy.deepcopy(orig_primitive)
            obj._obj_make_obj_compatible(primitive, '1.5', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['nova_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            primitive = copy.deepcopy(orig_primitive)
            obj._obj_make_obj_compatible(primitive, '1.4', 'rel_object')
            self.assertFalse(mock_compat.called)
            self.assertNotIn('rel_object', primitive)

    def test_obj_make_compatible_hits_sub_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            mock_compat.assert_called_once_with({'rel_object': 'foo'}, '1.10',
                                                'rel_object')

    def test_obj_make_compatible_skips_unset_sub_objects(self):
        obj = MyObj(foo=123)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            self.assertFalse(mock_compat.called)

    def test_obj_make_compatible_doesnt_skip_falsey_sub_objects(self):
        @base.NovaObjectRegistry.register_if(False)
        class MyList(base.ObjectListBase, base.NovaObject):
            VERSION = '1.2'
            fields = {'objects': fields.ListOfObjectsField('MyObjElement')}
            obj_relationships = {
                'objects': [('1.1', '1.1'), ('1.2', '1.2')],
            }

        mylist = MyList(objects=[])

        @base.NovaObjectRegistry.register_if(False)
        class MyOwner(base.NovaObject):
            VERSION = '1.2'
            fields = {'mylist': fields.ObjectField('MyList')}
            obj_relationships = {
                'mylist': [('1.1', '1.1')],
            }

        myowner = MyOwner(mylist=mylist)
        primitive = myowner.obj_to_primitive('1.1')
        self.assertIn('mylist', primitive['nova_object.data'])

    def test_obj_make_compatible_handles_list_of_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_objects=[subobj])
        obj.obj_relationships = {'rel_objects': [('1.0', '1.123')]}

        def fake_make_compat(primitive, version):
            self.assertEqual('1.123', version)
            self.assertIn('baz', primitive)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_mc:
            mock_mc.side_effect = fake_make_compat
            obj.obj_to_primitive('1.0')
            self.assertTrue(mock_mc.called)

    def test_delattr(self):
        obj = MyObj(bar='foo')
        del obj.bar

        # Should appear unset now
        self.assertFalse(obj.obj_attr_is_set('bar'))

        # Make sure post-delete, references trigger lazy loads
        self.assertEqual('loaded!', getattr(obj, 'bar'))

    def test_delattr_unset(self):
        obj = MyObj()
        self.assertRaises(AttributeError, delattr, obj, 'bar')


class TestObject(_LocalTest, _TestObject):
    def test_set_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults('foo')
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertEqual(1, obj.foo)

    def test_set_defaults_no_default(self):
        obj = MyObj()
        self.assertRaises(ovo_exc.ObjectActionError,
                          obj.obj_set_defaults, 'bar')

    def test_set_all_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults()
        self.assertEqual(set(['deleted', 'foo', 'mutable_default']),
                         obj.obj_what_changed())
        self.assertEqual(1, obj.foo)

    def test_set_defaults_not_overwrite(self):
        # NOTE(danms): deleted defaults to False, so verify that it does
        # not get reset by obj_set_defaults()
        obj = MyObj(deleted=True)
        obj.obj_set_defaults()
        self.assertEqual(1, obj.foo)
        self.assertTrue(obj.deleted)


class TestObjectSerializer(_BaseTestCase):
    def test_serialize_entity_primitive(self):
        ser = base.NovaObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.serialize_entity(None, thing))

    def test_deserialize_entity_primitive(self):
        ser = base.NovaObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.deserialize_entity(None, thing))

    def test_serialize_set_to_list(self):
        ser = base.NovaObjectSerializer()
        self.assertEqual([1, 2], ser.serialize_entity(None, set([1, 2])))

    def _test_deserialize_entity_newer(self, obj_version, backported_to,
                                       my_version='1.6'):
        ser = base.NovaObjectSerializer()
        ser._conductor = mock.Mock()
        ser._conductor.object_backport_versions.return_value = 'backported'

        class MyTestObj(MyObj):
            VERSION = my_version

        base.NovaObjectRegistry.register(MyTestObj)

        obj = MyTestObj()
        obj.VERSION = obj_version
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        if backported_to is None:
            self.assertFalse(ser._conductor.object_backport_versions.called)
        else:
            self.assertEqual('backported', result)
            versions = ovo_base.obj_tree_get_versions('MyTestObj')
            ser._conductor.object_backport_versions.assert_called_with(
                self.context, primitive, versions)

    def test_deserialize_entity_newer_version_backports(self):
        self._test_deserialize_entity_newer('1.25', '1.6')

    def test_deserialize_entity_newer_revision_does_not_backport_zero(self):
        self._test_deserialize_entity_newer('1.6.0', None)

    def test_deserialize_entity_newer_revision_does_not_backport(self):
        self._test_deserialize_entity_newer('1.6.1', None)

    def test_deserialize_entity_newer_version_passes_revision(self):
        self._test_deserialize_entity_newer('1.7', '1.6.1', '1.6.1')

    def test_deserialize_dot_z_with_extra_stuff(self):
        primitive = {'nova_object.name': 'MyObj',
                     'nova_object.namespace': 'nova',
                     'nova_object.version': '1.6.1',
                     'nova_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        ser = base.NovaObjectSerializer()
        obj = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): The serializer is where the logic lives that
        # avoids backports for cases where only a .z difference in
        # the received object version is detected. As a result, we
        # end up with a version of what we expected, effectively the
        # .0 of the object.
        self.assertEqual('1.6', obj.VERSION)

    @mock.patch('oslo_versionedobjects.base.obj_tree_get_versions')
    def test_object_tree_backport(self, mock_get_versions):
        # Test the full client backport path all the way from the serializer
        # to the conductor and back.
        self.start_service('conductor',
                           manager='nova.conductor.manager.ConductorManager')

        # NOTE(danms): Actually register a complex set of objects,
        # two versions of the same parent object which contain a
        # child sub object.
        @base.NovaObjectRegistry.register
        class Child(base.NovaObject):
            VERSION = '1.10'

        @base.NovaObjectRegistry.register
        class Parent(base.NovaObject):
            VERSION = '1.0'

            fields = {
                'child': fields.ObjectField('Child'),
            }

        @base.NovaObjectRegistry.register  # noqa
        class Parent(base.NovaObject):  # noqa
            VERSION = '1.1'

            fields = {
                'child': fields.ObjectField('Child'),
            }

        # NOTE(danms): Since we're on the same node as conductor,
        # return a fake version manifest so that we confirm that it
        # actually honors what the client asked for and not just what
        # it sees in the local machine state.
        mock_get_versions.return_value = {
            'Parent': '1.0',
            'Child': '1.5',
        }
        call_context = {}
        real_ofp = base.NovaObject.obj_from_primitive

        def fake_obj_from_primitive(*a, **k):
            # NOTE(danms): We need the first call to this to report an
            # incompatible object version, but subsequent calls must
            # succeed. Since we're testing the backport path all the
            # way through conductor and RPC, we can't fully break this
            # method, we just need it to fail once to trigger the
            # backport.
            if 'run' in call_context:
                return real_ofp(*a, **k)
            else:
                call_context['run'] = True
                raise ovo_exc.IncompatibleObjectVersion('foo')

        child = Child()
        parent = Parent(child=child)
        prim = parent.obj_to_primitive()
        ser = base.NovaObjectSerializer()

        with mock.patch('nova.objects.base.NovaObject.'
                        'obj_from_primitive') as mock_ofp:
            mock_ofp.side_effect = fake_obj_from_primitive
            result = ser.deserialize_entity(self.context, prim)

            # Our newest version (and what we passed back) of Parent
            # is 1.1, make sure that the manifest version is honored
            self.assertEqual('1.0', result.VERSION)

            # Our newest version (and what we passed back) of Child
            # is 1.10, make sure that the manifest version is honored
            self.assertEqual('1.5', result.child.VERSION)

    def test_object_serialization(self):
        ser = base.NovaObjectSerializer()
        obj = MyObj()
        primitive = ser.serialize_entity(self.context, obj)
        self.assertIn('nova_object.name', primitive)
        obj2 = ser.deserialize_entity(self.context, primitive)
        self.assertIsInstance(obj2, MyObj)
        self.assertEqual(self.context, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.NovaObjectSerializer()
        obj = MyObj()
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(self.context, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertNotIsInstance(item, base.NovaObject)
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)
        # dict case
        thing = {'key': obj}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(1, len(primitive))
        for item in six.itervalues(primitive):
            self.assertNotIsInstance(item, base.NovaObject)
        thing2 = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, len(thing2))
        for item in six.itervalues(thing2):
            self.assertIsInstance(item, MyObj)

        # object-action updates dict case
        thing = {'foo': obj.obj_to_primitive()}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(thing, primitive)
        thing2 = ser.deserialize_entity(self.context, thing)
        self.assertIsInstance(thing2['foo'], base.NovaObject)


class TestArgsSerializer(test.NoDBTestCase):
    def setUp(self):
        super(TestArgsSerializer, self).setUp()
        self.now = timeutils.utcnow()
        self.str_now = utils.strtime(self.now)
        self.exc = exception.NotFound()

    @base.serialize_args
    def _test_serialize_args(self, *args, **kwargs):
        expected_args = ('untouched', self.str_now, self.str_now)
        for index, val in enumerate(args):
            self.assertEqual(expected_args[index], val)

        expected_kwargs = {'a': 'untouched', 'b': self.str_now,
                           'c': self.str_now}

        nonnova = kwargs.pop('nonnova', None)
        if nonnova:
            expected_kwargs['exc_val'] = 'TestingException'
        else:
            expected_kwargs['exc_val'] = self.exc.format_message()
        for key, val in kwargs.items():
            self.assertEqual(expected_kwargs[key], val)

    def test_serialize_args(self):
        self._test_serialize_args('untouched', self.now, self.now,
                                  a='untouched', b=self.now, c=self.now,
                                  exc_val=self.exc)

    def test_serialize_args_non_nova_exception(self):
        self._test_serialize_args('untouched', self.now, self.now,
                                  a='untouched', b=self.now, c=self.now,
                                  exc_val=test.TestingException('foo'),
                                  nonnova=True)


class TestRegistry(test.NoDBTestCase):
    @mock.patch('nova.objects.base.objects')
    def test_hook_chooses_newer_properly(self, mock_objects):
        reg = base.NovaObjectRegistry()
        reg.registration_hook(MyObj, 0)

        class MyNewerObj(object):
            VERSION = '1.123'

            @classmethod
            def obj_name(cls):
                return 'MyObj'

        self.assertEqual(MyObj, mock_objects.MyObj)
        reg.registration_hook(MyNewerObj, 0)
        self.assertEqual(MyNewerObj, mock_objects.MyObj)

    @mock.patch('nova.objects.base.objects')
    def test_hook_keeps_newer_properly(self, mock_objects):
        reg = base.NovaObjectRegistry()
        reg.registration_hook(MyObj, 0)

        class MyOlderObj(object):
            VERSION = '1.1'

            @classmethod
            def obj_name(cls):
                return 'MyObj'

        self.assertEqual(MyObj, mock_objects.MyObj)
        reg.registration_hook(MyOlderObj, 0)
        self.assertEqual(MyObj, mock_objects.MyObj)


# NOTE(danms): The hashes in this list should only be changed if
# they come with a corresponding version bump in the affected
# objects
object_data = {
    'Agent': '1.0-c0c092abaceb6f51efe5d82175f15eba',
    'AgentList': '1.0-5a7380d02c3aaf2a32fc8115ae7ca98c',
    'Aggregate': '1.3-f315cb68906307ca2d1cca84d4753585',
    'AggregateList': '1.3-3ea55a050354e72ef3306adefa553957',
    'BandwidthUsage': '1.2-c6e4c779c7f40f2407e3d70022e3cd1c',
    'BandwidthUsageList': '1.2-5fe7475ada6fe62413cbfcc06ec70746',
    'BlockDeviceMapping': '1.20-45a6ad666ddf14bbbedece2293af77e2',
    'BlockDeviceMappingList': '1.17-1e568eecb91d06d4112db9fd656de235',
    'BuildRequest': '1.3-077dee42bed93f8a5b62be77657b7152',
    'BuildRequestList': '1.0-cd95608eccb89fbc702c8b52f38ec738',
    'CellMapping': '1.1-5d652928000a5bc369d79d5bde7e497d',
    'CellMappingList': '1.1-496ef79bb2ab41041fff8bcb57996352',
    'ComputeNode': '1.19-af6bd29a6c3b225da436a0d8487096f2',
    'ComputeNodeList': '1.17-52f3b0962b1c86b98590144463ebb192',
    'ConsoleAuthToken': '1.1-8da320fb065080eb4d3c2e5c59f8bf52',
    'CpuDiagnostics': '1.0-d256f2e442d1b837735fd17dfe8e3d47',
    'Destination': '1.4-3b440d29459e2c98987ad5b25ad1cb2c',
    'DeviceBus': '1.0-77509ea1ea0dd750d5864b9bd87d3f9d',
    'DeviceMetadata': '1.0-04eb8fd218a49cbc3b1e54b774d179f7',
    'Diagnostics': '1.0-38ad3e9b1a59306253fc03f97936db95',
    'DiskDiagnostics': '1.0-dfd0892b5924af1a585f3fed8c9899ca',
    'DiskMetadata': '1.0-e7a0f1ccccf10d26a76b28e7492f3788',
    'EC2Ids': '1.0-474ee1094c7ec16f8ce657595d8c49d9',
    'EC2InstanceMapping': '1.0-a4556eb5c5e94c045fe84f49cf71644f',
    'Flavor': '1.2-4ce99b41327bb230262e5a8f45ff0ce3',
    'FlavorList': '1.1-52b5928600e7ca973aa4fc1e46f3934c',
    'HVSpec': '1.2-de06bcec472a2f04966b855a49c46b41',
    'HostMapping': '1.0-1a3390a696792a552ab7bd31a77ba9ac',
    'HostMappingList': '1.1-18ac2bfb8c1eb5545bed856da58a79bc',
    'HyperVLiveMigrateData': '1.4-e265780e6acfa631476c8170e8d6fce0',
    'IDEDeviceBus': '1.0-29d4c9f27ac44197f01b6ac1b7e16502',
    'ImageMeta': '1.8-642d1b2eb3e880a367f37d72dd76162d',
    'ImageMetaProps': '1.27-f3f17d5e35146a0dbb56420ffc4f3990',
    'Instance': '2.7-d187aec68cad2e4d8b8a03a68e4739ce',
    'InstanceAction': '1.2-9a5abc87fdd3af46f45731960651efb5',
    'InstanceActionEvent': '1.4-5b1f361bd81989f8bb2c20bb7e8a4cb4',
    'InstanceActionEventList': '1.1-13d92fb953030cdbfee56481756e02be',
    'InstanceActionList': '1.1-a2b2fb6006b47c27076d3a1d48baa759',
    'InstanceDeviceMetadata': '1.0-74d78dd36aa32d26d2769a1b57caf186',
    'InstanceExternalEvent': '1.4-06c2dfcf2d2813c24cd37ee728524f1a',
    'InstanceFault': '1.2-7ef01f16f1084ad1304a513d6d410a38',
    'InstanceFaultList': '1.2-6bb72de2872fe49ded5eb937a93f2451',
    'InstanceGroup': '1.11-852ac511d30913ee88f3c3a869a8f30a',
    'InstanceGroupList': '1.8-90f8f1a445552bb3bbc9fa1ae7da27d4',
    'InstanceInfoCache': '1.5-cd8b96fefe0fc8d4d337243ba0bf0e1e',
    'InstanceList': '2.6-238f125650c25d6d12722340d726f723',
    'InstanceMapping': '1.2-3bd375e65c8eb9c45498d2f87b882e03',
    'InstanceMappingList': '1.3-d34b6ebb076d542ae0f8b440534118da',
    'InstanceNUMACell': '1.6-25d9120d83a18356f4146f2a6fe2cc8d',
    'InstanceNUMATopology': '1.3-ec0030cb0402a49c96da7051c037082a',
    'InstancePCIRequest': '1.3-f6d324f1c337fad4f34892ed5f484c9a',
    'InstancePCIRequests': '1.1-65e38083177726d806684cb1cc0136d2',
    'KeyPair': '1.4-1244e8d1b103cc69d038ed78ab3a8cc6',
    'KeyPairList': '1.3-94aad3ac5c938eef4b5e83da0212f506',
    'LibvirtLiveMigrateBDMInfo': '1.1-5f4a68873560b6f834b74e7861d71aaf',
    'LibvirtLiveMigrateData': '1.10-348cf70ea44d3b985f45f64725d6f6a7',
    'LibvirtLiveMigrateNUMAInfo': '1.0-0e777677f3459d0ed1634eabbdb6c22f',
    'MemoryDiagnostics': '1.0-2c995ae0f2223bb0f8e523c5cc0b83da',
    'Migration': '1.7-bd45b232fd7c95cd79ae9187e10ef582',
    'MigrationContext': '1.2-89f10a83999f852a489962ae37d8a026',
    'MigrationList': '1.5-36793f8d65bae421bd5564d09a4de7be',
    'MonitorMetric': '1.1-53b1db7c4ae2c531db79761e7acc52ba',
    'MonitorMetricList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'NUMACell': '1.4-7695303e820fa855d76954be2eb2680e',
    'NUMAPagesTopology': '1.1-edab9fa2dc43c117a38d600be54b4542',
    'NUMATopology': '1.2-c63fad38be73b6afd04715c9c1b29220',
    'NUMATopologyLimits': '1.1-4235c5da7a76c7e36075f0cd2f5cf922',
    'NetworkInterfaceMetadata': '1.2-6f3d480b40fe339067b1c0dd4d656716',
    'NetworkMetadata': '1.0-2cb8d21b34f87b0261d3e1d1ae5cf218',
    'NetworkRequest': '1.2-af1ff2d986999fbb79377712794d82aa',
    'NetworkRequestList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'NicDiagnostics': '1.0-895e9ad50e0f56d5258585e3e066aea5',
    'PCIDeviceBus': '1.0-2b891cb77e42961044689f3dc2718995',
    'PciDevice': '1.6-25ca0542a22bc25386a72c0065a79c01',
    'PciDeviceList': '1.3-52ff14355491c8c580bdc0ba34c26210',
    'PciDevicePool': '1.1-3f5ddc3ff7bfa14da7f6c7e9904cc000',
    'PciDevicePoolList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'PowerVMLiveMigrateData': '1.4-a745f4eda16b45e1bc5686a0c498f27e',
    'Quotas': '1.3-3b2b91371f60e788035778fc5f87797d',
    'QuotasNoOp': '1.3-d1593cf969c81846bc8192255ea95cce',
    'RequestGroup': '1.3-0458d350a8ec9d0673f9be5640a990ce',
    'RequestLevelParams': '1.0-1e5c8c18bd44cd233c8b32509c99d06f',
    'RequestSpec': '1.13-e1aa38b2bf3f8547474ee9e4c0aa2745',
    'Resource': '1.0-d8a2abbb380da583b995fd118f6a8953',
    'ResourceList': '1.0-4a53826625cc280e15fae64a575e0879',
    'ResourceMetadata': '1.0-77509ea1ea0dd750d5864b9bd87d3f9d',
    'S3ImageMapping': '1.0-7dd7366a890d82660ed121de9092276e',
    'SCSIDeviceBus': '1.0-61c1e89a00901069ab1cf2991681533b',
    'SchedulerLimits': '1.0-249c4bd8e62a9b327b7026b7f19cc641',
    'SchedulerRetries': '1.1-3c9c8b16143ebbb6ad7030e999d14cc0',
    'SecurityGroup': '1.2-86d67d8d3ab0c971e1dc86e02f9524a8',
    'SecurityGroupList': '1.1-c655ed13298e630f4d398152f7d08d71',
    'Selection': '1.1-548e3c2f04da2a61ceaf9c4e1589f264',
    'Service': '1.22-8a740459ab9bf258a19c8fcb875c2d9a',
    'ServiceList': '1.19-5325bce13eebcbf22edc9678285270cc',
    'Tag': '1.1-8b8d7d5b48887651a0e01241672e2963',
    'TagList': '1.1-55231bdb671ecf7641d6a2e9109b5d8e',
    'TaskLog': '1.0-78b0534366f29aa3eebb01860fbe18fe',
    'TaskLogList': '1.0-cc8cce1af8a283b9d28b55fcd682e777',
    'TrustedCerts': '1.0-dcf528851e0f868c77ee47e90563cda7',
    'USBDeviceBus': '1.0-e4c7dd6032e46cd74b027df5eb2d4750',
    'VIFMigrateData': '1.0-cb15282b25a039ab35046ed705eb931d',
    'VMwareLiveMigrateData': '1.0-a3cc858a2bf1d3806d6f57cfaa1fb98a',
    'VirtCPUFeature': '1.0-ea2464bdd09084bd388e5f61d5d4fc86',
    'VirtCPUModel': '1.0-5e1864af9227f698326203d7249796b5',
    'VirtCPUTopology': '1.0-fc694de72e20298f7c6bab1083fd4563',
    'VirtualInterface': '1.3-efd3ca8ebcc5ce65fff5a25f31754c54',
    'VirtualInterfaceList': '1.0-9750e2074437b3077e46359102779fc6',
    'VolumeUsage': '1.0-6c8190c46ce1469bb3286a1f21c2e475',
    'XenDeviceBus': '1.0-272a4f899b24e31e42b2b9a7ed7e9194',
    # TODO(efried): re-alphabetize this
    'LibvirtVPMEMDevice': '1.0-17ffaf47585199eeb9a2b83d6bde069f',
}


def get_nova_objects():
    """Get Nova versioned objects

    This returns a dict of versioned objects which are
    in the Nova project namespace only. ie excludes
    objects from os-vif and other 3rd party modules

    :return: a dict mapping class names to lists of versioned objects
    """

    all_classes = base.NovaObjectRegistry.obj_classes()
    nova_classes = {}
    for name in all_classes:
        objclasses = all_classes[name]
        # NOTE(danms): All object registries that inherit from the
        # base VersionedObjectRegistry share a common list of classes.
        # That means even things like os_vif objects will be in our
        # registry, and for any of them that share the same name
        # (i.e. Network), we need to keep ours and exclude theirs.
        our_ns = [cls for cls in objclasses
                  if (cls.OBJ_PROJECT_NAMESPACE ==
                      base.NovaObject.OBJ_PROJECT_NAMESPACE)]
        if our_ns:
            nova_classes[name] = our_ns
    return nova_classes


class TestObjectVersions(test.NoDBTestCase):
    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            get_nova_objects())
        fingerprints = checker.get_hashes()

        if os.getenv('GENERATE_HASHES'):
            open('object_hashes.txt', 'w').write(
                pprint.pformat(fingerprints))
            raise test.TestingException(
                'Generated hashes in object_hashes.txt')

        expected, actual = checker.test_hashes(object_data)
        self.assertEqual(expected, actual,
                         'Some objects have changed; please make sure the '
                         'versions have been bumped, and then update their '
                         'hashes here.')

    def test_obj_make_compatible(self):
        # NOTE(danms): This is normally not registered because it is just a
        # base class. However, the test fixture below requires it to be
        # in the registry so that it can verify backports based on its
        # children. So, register it here, which will be reverted after the
        # cleanUp for this (and all) tests is run.
        base.NovaObjectRegistry.register(virt_device_metadata.DeviceBus)

        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.

        # Hold a dictionary of args/kwargs that need to get passed into
        # __init__() for specific classes. The key in the dictionary is
        # the obj_class that needs the init args/kwargs.
        init_args = {}
        init_kwargs = {}

        checker = fixture.ObjectVersionChecker(get_nova_objects())
        checker.test_compatibility_routines(use_manifest=True,
                                            init_args=init_args,
                                            init_kwargs=init_kwargs)

    def test_list_obj_make_compatible(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestObj(base.NovaObject):
            VERSION = '1.4'
            fields = {'foo': fields.IntegerField()}

        @base.NovaObjectRegistry.register_if(False)
        class TestListObj(base.ObjectListBase, base.NovaObject):
            VERSION = '1.5'
            fields = {'objects': fields.ListOfObjectsField('TestObj')}
            obj_relationships = {
                'objects': [('1.0', '1.1'), ('1.1', '1.2'),
                            ('1.3', '1.3'), ('1.5', '1.4')]
            }

        my_list = TestListObj()
        my_obj = TestObj(foo=1)
        my_list.objects = [my_obj]
        primitive = my_list.obj_to_primitive(target_version='1.5')
        primitive_data = primitive['nova_object.data']
        obj_primitive = my_obj.obj_to_primitive(target_version='1.4')
        obj_primitive_data = obj_primitive['nova_object.data']
        with mock.patch.object(TestObj, 'obj_make_compatible') as comp:
            my_list.obj_make_compatible(primitive_data, '1.1')
            comp.assert_called_with(obj_primitive_data,
                                    '1.2')

    def test_list_obj_make_compatible_when_no_objects(self):
        # Test to make sure obj_make_compatible works with no 'objects'
        # If a List object ever has a version that did not contain the
        # 'objects' key, we need to make sure converting back to that version
        # doesn't cause backporting problems.
        @base.NovaObjectRegistry.register_if(False)
        class TestObj(base.NovaObject):
            VERSION = '1.1'
            fields = {'foo': fields.IntegerField()}

        @base.NovaObjectRegistry.register_if(False)
        class TestListObj(base.ObjectListBase, base.NovaObject):
            VERSION = '1.1'
            fields = {'objects': fields.ListOfObjectsField('TestObj')}
            # pretend that version 1.0 didn't have 'objects'
            obj_relationships = {
                'objects': [('1.1', '1.1')]
            }

        my_list = TestListObj()
        my_list.objects = [TestObj(foo=1)]
        primitive = my_list.obj_to_primitive(target_version='1.1')
        primitive_data = primitive['nova_object.data']
        my_list.obj_make_compatible(primitive_data,
                                    target_version='1.0')
        self.assertNotIn('objects', primitive_data,
                         "List was backported to before 'objects' existed."
                         " 'objects' should not be in the primitive.")


class TestObjEqualPrims(_BaseTestCase):

    def test_object_equal(self):
        obj1 = MyObj(foo=1, bar='goodbye')
        obj1.obj_reset_changes()
        obj2 = MyObj(foo=1, bar='goodbye')
        obj2.obj_reset_changes()
        obj2.bar = 'goodbye'
        # obj2 will be marked with field 'three' updated
        self.assertTrue(base.obj_equal_prims(obj1, obj2),
                        "Objects that differ only because one a is marked "
                        "as updated should be equal")

    def test_object_not_equal(self):
        obj1 = MyObj(foo=1, bar='goodbye')
        obj1.obj_reset_changes()
        obj2 = MyObj(foo=1, bar='hello')
        obj2.obj_reset_changes()
        self.assertFalse(base.obj_equal_prims(obj1, obj2),
                         "Objects that differ in any field "
                         "should not be equal")

    def test_object_ignore_equal(self):
        obj1 = MyObj(foo=1, bar='goodbye')
        obj1.obj_reset_changes()
        obj2 = MyObj(foo=1, bar='hello')
        obj2.obj_reset_changes()
        self.assertTrue(base.obj_equal_prims(obj1, obj2, ['bar']),
                        "Objects that only differ in an ignored field "
                        "should be equal")


class TestObjMethodOverrides(test.NoDBTestCase):
    def test_obj_reset_changes(self):
        args = utils.getargspec(base.NovaObject.obj_reset_changes)
        obj_classes = base.NovaObjectRegistry.obj_classes()
        for obj_name in obj_classes:
            obj_class = obj_classes[obj_name][0]
            self.assertEqual(args,
                utils.getargspec(obj_class.obj_reset_changes))


class TestObjectsDefaultingOnInit(test.NoDBTestCase):
    def test_init_behavior_policy(self):
        all_objects = get_nova_objects()

        violations = collections.defaultdict(list)

        # NOTE(danms): Do not add things to this list!
        #
        # There is one known exception to this init policy, and that
        # is the Service object because of the special behavior of the
        # version field. We *want* to counteract the usual non-clobber
        # behavior of that field specifically. See the comments in
        # Service.__init__ for more details. This will likely never
        # apply to any other non-ephemeral object, so this list should
        # never grow.
        exceptions = [objects.Service]

        for name, objclasses in all_objects.items():
            for objcls in objclasses:
                if objcls in exceptions:
                    continue

                key = '%s-%s' % (name, objcls.VERSION)
                obj = objcls()
                if isinstance(obj, base.NovaEphemeralObject):
                    # Skip ephemeral objects, which are allowed to
                    # set fields at init time
                    continue
                for field in objcls.fields:
                    if field in obj:
                        violations[key].append(field)

        self.assertEqual({}, violations,
                         'Some non-ephemeral objects set fields during '
                         'initialization; This is not allowed.')
