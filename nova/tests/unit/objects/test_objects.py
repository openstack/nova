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
import inspect
import os
import pprint

import fixtures
import mock
from oslo_log import log
from oslo_utils import timeutils
from oslo_utils import versionutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import exception as ovo_exc
from oslo_versionedobjects import fixture
import six

from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import notification
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_notifier
from nova import utils


LOG = log.getLogger(__name__)


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
class TestSubclassedObject(RandomMixInWithNoFields, MyObj):
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


class TestObjMakeList(test.NoDBTestCase):

    def test_obj_make_list(self):
        class MyList(base.ObjectListBase, base.NovaObject):
            fields = {
                'objects': fields.ListOfObjectsField('MyObj'),
            }

        db_objs = [{'foo': 1, 'bar': 'baz', 'missing': 'banana'},
                   {'foo': 2, 'bar': 'bat', 'missing': 'apple'},
                   ]
        mylist = base.obj_make_list('ctxt', MyList(), MyObj, db_objs)
        self.assertEqual(2, len(mylist))
        self.assertEqual('ctxt', mylist._context)
        for index, item in enumerate(mylist):
            self.assertEqual(db_objs[index]['foo'], item.foo)
            self.assertEqual(db_objs[index]['bar'], item.bar)
            self.assertEqual(db_objs[index]['missing'], item.missing)


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
        fake_notifier.stub_notifier(self.stubs)
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

    def test_obj_reset_changes_recursive(self):
        obj = MyObj(rel_object=MyOwnedObject(baz=123),
                    rel_objects=[MyOwnedObject(baz=456)])
        self.assertEqual(set(['rel_object', 'rel_objects']),
                         obj.obj_what_changed())
        obj.obj_reset_changes()
        self.assertEqual(set(['rel_object']), obj.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_object.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_objects[0].obj_what_changed())
        obj.obj_reset_changes(recursive=True, fields=['foo'])
        self.assertEqual(set(['rel_object']), obj.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_object.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_objects[0].obj_what_changed())
        obj.obj_reset_changes(recursive=True)
        self.assertEqual(set([]), obj.rel_object.obj_what_changed())
        self.assertEqual(set([]), obj.obj_what_changed())

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
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields.keys()))

    def test_obj_as_admin(self):
        obj = MyObj(context=self.context)

        def fake(*args, **kwargs):
            self.assertTrue(obj._context.is_admin)

        with mock.patch.object(obj, 'obj_reset_changes') as mock_fn:
            mock_fn.side_effect = fake
            with obj.obj_as_admin():
                obj.save()
            self.assertTrue(mock_fn.called)

        self.assertFalse(obj._context.is_admin)

    def test_obj_as_admin_orphaned(self):
        def testme():
            obj = MyObj()
            with obj.obj_as_admin():
                pass
        self.assertRaises(exception.OrphanedObjectError, testme)

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
        class Parent(base.NovaObject):
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
        self.unicode_str = u'\xF0\x9F\x92\xA9'

    @base.serialize_args
    def _test_serialize_args(self, *args, **kwargs):
        expected_args = ('untouched', self.str_now, self.str_now)
        for index, val in enumerate(args):
            self.assertEqual(expected_args[index], val)

        expected_kwargs = {'a': 'untouched', 'b': self.str_now,
                           'c': self.str_now, 'exc_val': self.unicode_str}
        for key, val in six.iteritems(kwargs):
            self.assertEqual(expected_kwargs[key], val)

    def test_serialize_args(self):
        self._test_serialize_args('untouched', self.now, self.now,
                                  a='untouched', b=self.now, c=self.now,
                                  exc_val=self.unicode_str)


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
    'Aggregate': '1.1-1ab35c4516f71de0bef7087026ab10d1',
    'AggregateList': '1.2-fb6e19f3c3a3186b04eceb98b5dadbfa',
    'BandwidthUsage': '1.2-c6e4c779c7f40f2407e3d70022e3cd1c',
    'BandwidthUsageList': '1.2-5fe7475ada6fe62413cbfcc06ec70746',
    'BlockDeviceMapping': '1.16-12319f6f47f740a67a88a23f7c7ee6ef',
    'BlockDeviceMappingList': '1.17-1e568eecb91d06d4112db9fd656de235',
    'CellMapping': '1.0-7f1a7e85a22bbb7559fc730ab658b9bd',
    'ComputeNode': '1.14-a396975707b66281c5f404a68fccd395',
    'ComputeNodeList': '1.14-3b6f4f5ade621c40e70cb116db237844',
    'DNSDomain': '1.0-7b0b2dab778454b6a7b6c66afe163a1a',
    'DNSDomainList': '1.0-4ee0d9efdfd681fed822da88376e04d2',
    'EC2Ids': '1.0-474ee1094c7ec16f8ce657595d8c49d9',
    'EC2InstanceMapping': '1.0-a4556eb5c5e94c045fe84f49cf71644f',
    'EC2SnapshotMapping': '1.0-47e7ddabe1af966dce0cfd0ed6cd7cd1',
    'EC2VolumeMapping': '1.0-5b713751d6f97bad620f3378a521020d',
    'EventType': '1.0-21dc35de314fc5fc0a7965211c0c00f7',
    'FixedIP': '1.14-53e1c10b539f1a82fe83b1af4720efae',
    'FixedIPList': '1.14-87a39361c8f08f059004d6b15103cdfd',
    'Flavor': '1.1-b6bb7a730a79d720344accefafacf7ee',
    'FlavorList': '1.1-52b5928600e7ca973aa4fc1e46f3934c',
    'FloatingIP': '1.10-52a67d52d85eb8b3f324a5b7935a335b',
    'FloatingIPList': '1.11-7f2ba670714e1b7bab462ab3290f7159',
    'HostMapping': '1.0-1a3390a696792a552ab7bd31a77ba9ac',
    'HVSpec': '1.2-db672e73304da86139086d003f3977e7',
    'ImageMeta': '1.8-642d1b2eb3e880a367f37d72dd76162d',
    'ImageMetaProps': '1.12-6a132dee47931447bf86c03c7006d96c',
    'Instance': '2.1-416fdd0dfc33dfa12ff2cfdd8cc32e17',
    'InstanceAction': '1.1-f9f293e526b66fca0d05c3b3a2d13914',
    'InstanceActionEvent': '1.1-e56a64fa4710e43ef7af2ad9d6028b33',
    'InstanceActionEventList': '1.1-13d92fb953030cdbfee56481756e02be',
    'InstanceActionList': '1.0-4a53826625cc280e15fae64a575e0879',
    'InstanceExternalEvent': '1.1-6e446ceaae5f475ead255946dd443417',
    'InstanceFault': '1.2-7ef01f16f1084ad1304a513d6d410a38',
    'InstanceFaultList': '1.1-f8ec07cbe3b60f5f07a8b7a06311ac0d',
    'InstanceGroup': '1.10-1a0c8c7447dc7ecb9da53849430c4a5f',
    'InstanceGroupList': '1.7-be18078220513316abd0ae1b2d916873',
    'InstanceInfoCache': '1.5-cd8b96fefe0fc8d4d337243ba0bf0e1e',
    'InstanceList': '2.0-6c8ba6147cca3082b1e4643f795068bf',
    'InstanceMapping': '1.0-47ef26034dfcbea78427565d9177fe50',
    'InstanceMappingList': '1.0-9e982e3de1613b9ada85e35f69b23d47',
    'InstanceNUMACell': '1.3-6991a20992c5faa57fae71a45b40241b',
    'InstanceNUMATopology': '1.2-d944a7d6c21e1c773ffdf09c6d025954',
    'InstancePCIRequest': '1.1-b1d75ebc716cb12906d9d513890092bf',
    'InstancePCIRequests': '1.1-65e38083177726d806684cb1cc0136d2',
    'LibvirtLiveMigrateBDMInfo': '1.0-252aabb723ca79d5469fa56f64b57811',
    'LibvirtLiveMigrateData': '1.1-4ecf40aae7fee7bb37fc3b2123e760de',
    'KeyPair': '1.3-bfaa2a8b148cdf11e0c72435d9dd097a',
    'KeyPairList': '1.2-58b94f96e776bedaf1e192ddb2a24c4e',
    'Migration': '1.2-8784125bedcea0a9227318511904e853',
    'MigrationContext': '1.0-d8c2f10069e410f639c49082b5932c92',
    'MigrationList': '1.2-02c0ec0c50b75ca86a2a74c5e8c911cc',
    'MonitorMetric': '1.1-53b1db7c4ae2c531db79761e7acc52ba',
    'MonitorMetricList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'NotificationPublisher': '1.0-bbbc1402fb0e443a3eb227cc52b61545',
    'NUMACell': '1.2-74fc993ac5c83005e76e34e8487f1c05',
    'NUMAPagesTopology': '1.0-c71d86317283266dc8364c149155e48e',
    'NUMATopology': '1.2-c63fad38be73b6afd04715c9c1b29220',
    'NUMATopologyLimits': '1.0-9463e0edd40f64765ae518a539b9dfd2',
    'Network': '1.2-a977ab383aa462a479b2fae8211a5dde',
    'NetworkList': '1.2-69eca910d8fa035dfecd8ba10877ee59',
    'NetworkRequest': '1.1-7a3e4ca2ce1e7b62d8400488f2f2b756',
    'NetworkRequestList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'PciDevice': '1.5-0d5abe5c91645b8469eb2a93fc53f932',
    'PciDeviceList': '1.3-52ff14355491c8c580bdc0ba34c26210',
    'PciDevicePool': '1.1-3f5ddc3ff7bfa14da7f6c7e9904cc000',
    'PciDevicePoolList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Quotas': '1.2-1fe4cd50593aaf5d36a6dc5ab3f98fb3',
    'QuotasNoOp': '1.2-e041ddeb7dc8188ca71706f78aad41c1',
    'RequestSpec': '1.5-576a249869c161e17b7cd6d55f9d85f3',
    'S3ImageMapping': '1.0-7dd7366a890d82660ed121de9092276e',
    'SchedulerLimits': '1.0-249c4bd8e62a9b327b7026b7f19cc641',
    'SchedulerRetries': '1.1-3c9c8b16143ebbb6ad7030e999d14cc0',
    'SecurityGroup': '1.1-0e1b9ba42fe85c13c1437f8b74bdb976',
    'SecurityGroupList': '1.0-dc8bbea01ba09a2edb6e5233eae85cbc',
    'SecurityGroupRule': '1.1-ae1da17b79970012e8536f88cb3c6b29',
    'SecurityGroupRuleList': '1.2-0005c47fcd0fb78dd6d7fd32a1409f5b',
    'Service': '1.19-8914320cbeb4ec29f252d72ce55d07e1',
    'ServiceList': '1.17-b767102cba7cbed290e396114c3f86b3',
    'ServiceStatusNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServiceStatusPayload': '1.0-a5e7b4fd6cc5581be45b31ff1f3a3f7f',
    'TaskLog': '1.0-78b0534366f29aa3eebb01860fbe18fe',
    'TaskLogList': '1.0-cc8cce1af8a283b9d28b55fcd682e777',
    'Tag': '1.1-8b8d7d5b48887651a0e01241672e2963',
    'TagList': '1.1-55231bdb671ecf7641d6a2e9109b5d8e',
    'VirtCPUFeature': '1.0-3310718d8c72309259a6e39bdefe83ee',
    'VirtCPUModel': '1.0-6a5cc9f322729fc70ddc6733bacd57d3',
    'VirtCPUTopology': '1.0-fc694de72e20298f7c6bab1083fd4563',
    'VirtualInterface': '1.0-19921e38cba320f355d56ecbf8f29587',
    'VirtualInterfaceList': '1.0-9750e2074437b3077e46359102779fc6',
    'VolumeUsage': '1.0-6c8190c46ce1469bb3286a1f21c2e475',
    'XenapiLiveMigrateData': '1.0-5f982bec68f066e194cd9ce53a24ac4c',
}


class TestObjectVersions(test.NoDBTestCase):
    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            base.NovaObjectRegistry.obj_classes())
        fingerprints = checker.get_hashes(extra_data_func=get_extra_data)

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

    def test_notification_payload_version_depends_on_the_schema(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestNotificationPayload(notification.NotificationPayloadBase):
            VERSION = '1.0'

            SCHEMA = {
                'field_1': ('source_field', 'field_1'),
                'field_2': ('source_field', 'field_2'),
            }

            fields = {
                'extra_field': fields.StringField(),  # filled by ctor
                'field_1': fields.StringField(),  # filled by the schema
                'field_2': fields.IntegerField(),   # filled by the schema
            }

        checker = fixture.ObjectVersionChecker(
            {'TestNotificationPayload': (TestNotificationPayload,)})

        old_hash = checker.get_hashes(extra_data_func=get_extra_data)
        TestNotificationPayload.SCHEMA['field_3'] = ('source_field',
                                                     'field_3')
        new_hash = checker.get_hashes(extra_data_func=get_extra_data)

        self.assertNotEqual(old_hash, new_hash)

    def test_obj_make_compatible(self):
        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.
        obj_classes = base.NovaObjectRegistry.obj_classes()
        for obj_name in obj_classes:
            versions = ovo_base.obj_tree_get_versions(obj_name)
            obj_class = obj_classes[obj_name][0]
            version = versionutils.convert_version_to_tuple(obj_class.VERSION)
            for n in range(version[1]):
                test_version = '%d.%d' % (version[0], n)
                LOG.info('testing obj: %s version: %s' %
                         (obj_name, test_version))
                obj_class().obj_to_primitive(target_version=test_version,
                                             version_manifest=versions)

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
        args = inspect.getargspec(base.NovaObject.obj_reset_changes)
        obj_classes = base.NovaObjectRegistry.obj_classes()
        for obj_name in obj_classes:
            obj_class = obj_classes[obj_name][0]
            self.assertEqual(args,
                    inspect.getargspec(obj_class.obj_reset_changes))


def get_extra_data(obj_class):
    extra_data = tuple()

    # Get the SCHEMA items to add to the fingerprint
    # if we are looking at a notification
    if issubclass(obj_class, notification.NotificationPayloadBase):
        schema_data = collections.OrderedDict(
            sorted(obj_class.SCHEMA.items()))

        extra_data += (schema_data,)

    return extra_data
