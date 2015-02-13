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

import contextlib
import copy
import datetime
import hashlib
import inspect
import os
import pprint

import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import six
from testtools import matchers

from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.openstack.common import log
from nova import rpc
from nova import test
from nova.tests.unit import fake_notifier
from nova import utils


LOG = log.getLogger(__name__)


class MyOwnedObject(base.NovaPersistentObject, base.NovaObject):
    VERSION = '1.0'
    fields = {'baz': fields.Field(fields.Integer())}


class MyObj(base.NovaPersistentObject, base.NovaObject,
            base.NovaObjectDictCompat):
    VERSION = '1.6'
    fields = {'foo': fields.Field(fields.Integer(), default=1),
              'bar': fields.Field(fields.String()),
              'missing': fields.Field(fields.String()),
              'readonly': fields.Field(fields.Integer(), read_only=True),
              'rel_object': fields.ObjectField('MyOwnedObject', nullable=True),
              'rel_objects': fields.ListOfObjectsField('MyOwnedObject',
                                                       nullable=True),
              }

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        self = MyObj()
        self.foo = db_obj['foo']
        self.bar = db_obj['bar']
        self.missing = db_obj['missing']
        self.readonly = 1
        return self

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls(context=context, foo=1, bar='bar')
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self, context):
        return 'polo'

    @base.remotable
    def _update_test(self, context):
        if context.project_id == 'alternate':
            self.bar = 'alternate-context'
        else:
            self.bar = 'updated'

    @base.remotable
    def save(self, context):
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @base.remotable
    def modify_save_modify(self, context):
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


class MyObjDiffVers(MyObj):
    VERSION = '1.5'

    @classmethod
    def obj_name(cls):
        return 'MyObj'


class MyObj2(object):
    @classmethod
    def obj_name(cls):
        return 'MyObj'

    @base.remotable_classmethod
    def query(cls, *args, **kwargs):
        pass


class RandomMixInWithNoFields(object):
    """Used to test object inheritance using a mixin that has no fields."""
    pass


class TestSubclassedObject(RandomMixInWithNoFields, MyObj):
    fields = {'new_field': fields.Field(fields.String())}


class TestMetaclass(test.TestCase):
    def test_obj_tracking(self):

        @six.add_metaclass(base.NovaObjectMetaclass)
        class NewBaseClass(object):
            VERSION = '1.0'
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        class Fake1TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake1'

        class Fake1TestObj2(Fake1TestObj1):
            pass

        class Fake1TestObj3(Fake1TestObj1):
            VERSION = '1.1'

        class Fake2TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake2'

        class Fake1TestObj4(Fake1TestObj3):
            VERSION = '1.2'

        class Fake2TestObj2(Fake2TestObj1):
            VERSION = '1.1'

        class Fake1TestObj5(Fake1TestObj1):
            VERSION = '1.1'

        # Newest versions first in the list. Duplicate versions take the
        # newest object.
        expected = {'fake1': [Fake1TestObj4, Fake1TestObj5, Fake1TestObj2],
                    'fake2': [Fake2TestObj2, Fake2TestObj1]}
        self.assertEqual(expected, NewBaseClass._obj_classes)
        # The following should work, also.
        self.assertEqual(expected, Fake1TestObj1._obj_classes)
        self.assertEqual(expected, Fake1TestObj2._obj_classes)
        self.assertEqual(expected, Fake1TestObj3._obj_classes)
        self.assertEqual(expected, Fake1TestObj4._obj_classes)
        self.assertEqual(expected, Fake1TestObj5._obj_classes)
        self.assertEqual(expected, Fake2TestObj1._obj_classes)
        self.assertEqual(expected, Fake2TestObj2._obj_classes)

    def test_field_checking(self):
        def create_class(field):
            class TestField(base.NovaObject):
                VERSION = '1.5'
                fields = {'foo': field()}
            return TestField

        create_class(fields.IPV4AndV6AddressField)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, fields.IPV4AndV6Address)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, int)


class TestObjToPrimitive(test.TestCase):

    def test_obj_to_primitive_list(self):
        class MyObjElement(base.NovaObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyObjElement, self).__init__()
                self.foo = foo

        class MyList(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('MyObjElement')}

        mylist = MyList()
        mylist.objects = [MyObjElement(1), MyObjElement(2), MyObjElement(3)]
        self.assertEqual([1, 2, 3],
                         [x['foo'] for x in base.obj_to_primitive(mylist)])

    def test_obj_to_primitive_dict(self):
        myobj = MyObj(foo=1, bar='foo')
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        class MyList(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('MyObj')}

        mylist = MyList(objects=[MyObj(), MyObj()])
        for i, value in enumerate(mylist):
            value.foo = i
        self.assertEqual([{'foo': 0}, {'foo': 1}],
                         base.obj_to_primitive(mylist))

    def test_obj_to_primitive_with_ip_addr(self):
        class TestObject(base.NovaObject):
            fields = {'addr': fields.IPAddressField(),
                      'cidr': fields.IPNetworkField()}

        obj = TestObject(addr='1.2.3.4', cidr='1.1.1.1/16')
        self.assertEqual({'addr': '1.2.3.4', 'cidr': '1.1.1.1/16'},
                         base.obj_to_primitive(obj))


class TestObjMakeList(test.TestCase):

    def test_obj_make_list(self):
        class MyList(base.ObjectListBase, base.NovaObject):
            pass

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
        self.remote_object_calls = list()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

    def compare_obj(self, obj, db_obj, subs=None, allow_missing=None,
                    comparators=None):
        compare_obj(self, obj, db_obj, subs=subs, allow_missing=allow_missing,
                    comparators=comparators)

    def json_comparator(self, expected, obj_val):
        # json-ify an object field for comparison with its db str
        # equivalent
        self.assertEqual(expected, jsonutils.dumps(obj_val))

    def str_comparator(self, expected, obj_val):
        """Compare an object field to a string in the db by performing
        a simple coercion on the object field value.
        """
        self.assertEqual(expected, str(obj_val))

    def assertNotIsInstance(self, obj, cls, msg=None):
        """Python < v2.7 compatibility.  Assert 'not isinstance(obj, cls)."""
        try:
            f = super(_BaseTestCase, self).assertNotIsInstance
        except AttributeError:
            self.assertThat(obj,
                            matchers.Not(matchers.IsInstance(cls)),
                            message=msg or '')
        else:
            f(obj, cls, msg=msg)


class _LocalTest(_BaseTestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        # Just in case
        base.NovaObject.indirection_api = None

    def assertRemotes(self):
        self.assertEqual(self.remote_object_calls, [])


@contextlib.contextmanager
def things_temporarily_local():
    # Temporarily go non-remote so the conductor handles
    # this request directly
    _api = base.NovaObject.indirection_api
    base.NovaObject.indirection_api = None
    yield
    base.NovaObject.indirection_api = _api


class _RemoteTest(_BaseTestCase):
    def _testable_conductor(self):
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.remote_object_calls = list()

        orig_object_class_action = \
            self.conductor_service.manager.object_class_action
        orig_object_action = \
            self.conductor_service.manager.object_action

        def fake_object_class_action(*args, **kwargs):
            self.remote_object_calls.append((kwargs.get('objname'),
                                             kwargs.get('objmethod')))
            with things_temporarily_local():
                result = orig_object_class_action(*args, **kwargs)
            return (base.NovaObject.obj_from_primitive(result, context=args[0])
                    if isinstance(result, base.NovaObject) else result)
        self.stubs.Set(self.conductor_service.manager, 'object_class_action',
                       fake_object_class_action)

        def fake_object_action(*args, **kwargs):
            self.remote_object_calls.append((kwargs.get('objinst'),
                                             kwargs.get('objmethod')))
            with things_temporarily_local():
                result = orig_object_action(*args, **kwargs)
            return result
        self.stubs.Set(self.conductor_service.manager, 'object_action',
                       fake_object_action)

        # Things are remoted by default in this session
        base.NovaObject.indirection_api = conductor_rpcapi.ConductorAPI()

        # To make sure local and remote contexts match
        self.stubs.Set(rpc.RequestContextSerializer,
                       'serialize_context',
                       lambda s, c: c)
        self.stubs.Set(rpc.RequestContextSerializer,
                       'deserialize_context',
                       lambda s, c: c)

    def setUp(self):
        super(_RemoteTest, self).setUp()
        self._testable_conductor()

    def assertRemotes(self):
        self.assertNotEqual(self.remote_object_calls, [])


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
        self.assertRaises(exception.UnsupportedObjectError,
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

    def test_object_dict_syntax(self):
        obj = MyObj(foo=123, bar='bar')
        self.assertEqual(obj['foo'], 123)
        self.assertEqual(sorted(obj.items(), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])
        self.assertEqual(sorted(list(obj.iteritems()), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])

    def test_load(self):
        obj = MyObj()
        self.assertEqual(obj.bar, 'loaded!')

    def test_load_in_base(self):
        class Foo(base.NovaObject):
            fields = {'foobar': fields.Field(fields.Integer())}
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

    def test_obj_class_from_name(self):
        obj = base.NovaObject.obj_class_from_name('MyObj', '1.5')
        self.assertEqual('1.5', obj.VERSION)

    def test_obj_class_from_name_latest_compatible(self):
        obj = base.NovaObject.obj_class_from_name('MyObj', '1.1')
        self.assertEqual('1.6', obj.VERSION)

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.NovaObject.obj_class_from_name, 'foo', '1.0')

    def test_obj_class_from_name_supported_version(self):
        error = None
        try:
            base.NovaObject.obj_class_from_name('MyObj', '1.25')
        except exception.IncompatibleObjectVersion as error:
            pass

        self.assertIsNotNone(error)
        self.assertEqual('1.6', error.kwargs['supported'])

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext('foo', 'foo')
        ctxt2 = context.RequestContext('bar', 'alternate')
        obj = MyObj.query(ctxt1)
        obj._update_test(ctxt2)
        self.assertEqual(obj.bar, 'alternate-context')
        self.assertRemotes()

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj._update_test)
        self.assertRemotes()

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj._update_test(self.context)
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'bar']))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.save()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')
        self.assertRemotes()

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify(self.context)
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'rel_object']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
        self.assertIsInstance(obj.rel_object, MyOwnedObject)
        self.assertRemotes()

    def test_changed_with_sub_object(self):
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
        self.assertRemotes()

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.foo, 1)
        obj._update_test()
        self.assertEqual(obj.bar, 'updated')
        self.assertRemotes()

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
                        {'created_at': timeutils.isotime(dt),
                         'updated_at': timeutils.isotime(dt),
                         'deleted_at': None,
                         'deleted': False,
                         }
                    }
        self.assertEqual(obj.obj_to_primitive(), expected)

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
                         'readonly', 'rel_object', 'rel_objects'] +
                        base_fields)
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
        class TestObj(base.NovaObject):
            fields = {'foo': fields.Field(fields.Integer())}
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
        self.assertRaises(exception.ReadOnlyFieldError, setattr,
                          obj, 'readonly', 2)

    def test_obj_repr(self):
        obj = MyObj(foo=123)
        self.assertEqual('MyObj(bar=<?>,created_at=<?>,deleted=<?>,'
                         'deleted_at=<?>,foo=123,missing=<?>,readonly=<?>,'
                         'rel_object=<?>,rel_objects=<?>,updated_at=<?>)',
                         repr(obj))

    def test_obj_make_obj_compatible(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_object=subobj)
        obj.obj_relationships = {
            'rel_object': [('1.5', '1.1'), ('1.7', '1.2')],
        }
        primitive = obj.obj_to_primitive()['nova_object.data']
        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.8',
                                         'rel_object')
            self.assertFalse(mock_compat.called)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.7', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.2')
            self.assertEqual('1.2',
                             primitive['rel_object']['nova_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.6', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['nova_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.5',
                                         'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['nova_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['nova_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            _prim = copy.copy(primitive)
            obj._obj_make_obj_compatible(_prim, '1.4', 'rel_object')
            self.assertFalse(mock_compat.called)
            self.assertNotIn('rel_object', _prim)

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

    def test_obj_make_compatible_complains_about_missing_rules(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {}
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_make_compatible, {}, '1.0')

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


class TestObject(_LocalTest, _TestObject):
    def test_set_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults('foo')
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertEqual(1, obj.foo)

    def test_set_defaults_no_default(self):
        obj = MyObj()
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_set_defaults, 'bar')

    def test_set_all_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults()
        self.assertEqual(set(['deleted', 'foo']), obj.obj_what_changed())
        self.assertEqual(1, obj.foo)

    def test_set_defaults_not_overwrite(self):
        # NOTE(danms): deleted defaults to False, so verify that it does
        # not get reset by obj_set_defaults()
        obj = MyObj(deleted=True)
        obj.obj_set_defaults()
        self.assertEqual(1, obj.foo)
        self.assertTrue(obj.deleted)


class TestRemoteObject(_RemoteTest, _TestObject):
    def test_major_version_mismatch(self):
        MyObj2.VERSION = '2.0'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_greater(self):
        MyObj2.VERSION = '1.7'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_less(self):
        MyObj2.VERSION = '1.2'
        obj = MyObj2.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        self.assertRemotes()

    def test_compat(self):
        MyObj2.VERSION = '1.1'
        obj = MyObj2.query(self.context)
        self.assertEqual('oldbar', obj.bar)

    def test_revision_ignored(self):
        MyObj2.VERSION = '1.1.456'
        obj = MyObj2.query(self.context)
        self.assertEqual('bar', obj.bar)


class TestObjectListBase(test.TestCase):
    def test_list_like_operations(self):
        class MyElement(base.NovaObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyElement, self).__init__()
                self.foo = foo

        class Foo(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('MyElement')}

        objlist = Foo(context='foo',
                      objects=[MyElement(1), MyElement(2), MyElement(3)])
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(len(objlist), 3)
        self.assertIn(objlist.objects[0], objlist)
        self.assertEqual(list(objlist[:1]), [objlist.objects[0]])
        self.assertEqual(objlist[:1]._context, 'foo')
        self.assertEqual(objlist[2], objlist.objects[2])
        self.assertEqual(objlist.count(objlist.objects[0]), 1)
        self.assertEqual(objlist.index(objlist.objects[1]), 1)
        objlist.sort(key=lambda x: x.foo, reverse=True)
        self.assertEqual([3, 2, 1],
                         [x.foo for x in objlist])

    def test_serialization(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.NovaObject):
            fields = {'foo': fields.Field(fields.String())}

        obj = Foo(objects=[])
        for i in 'abc':
            bar = Bar(foo=i)
            obj.objects.append(bar)

        obj2 = base.NovaObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])

    def _test_object_list_version_mappings(self, list_obj_class):
        # Figure out what sort of object this list is for
        list_field = list_obj_class.fields['objects']
        item_obj_field = list_field._type._element_type
        item_obj_name = item_obj_field._type._obj_name

        # Look through all object classes of this type and make sure that
        # the versions we find are covered by the parent list class
        for item_class in base.NovaObject._obj_classes[item_obj_name]:
            self.assertIn(
                item_class.VERSION,
                list_obj_class.child_versions.values(),
                'Version mapping is incomplete for %s' % (
                    list_obj_class.__name__))

    def test_object_version_mappings(self):
        # Find all object list classes and make sure that they at least handle
        # all the current object versions
        for obj_classes in base.NovaObject._obj_classes.values():
            for obj_class in obj_classes:
                if issubclass(obj_class, base.ObjectListBase):
                    self._test_object_list_version_mappings(obj_class)

    def test_list_changes(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.NovaObject):
            fields = {'foo': fields.StringField()}

        obj = Foo(objects=[])
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects.append(Bar(foo='test'))
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.obj_reset_changes()
        # This should still look dirty because the child is dirty
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects[0].obj_reset_changes()
        # This should now look clean because the child is clean
        self.assertEqual(set(), obj.obj_what_changed())

    def test_initialize_objects(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.NovaObject):
            fields = {'foo': fields.StringField()}

        obj = Foo()
        self.assertEqual([], obj.objects)
        self.assertEqual(set(), obj.obj_what_changed())

    def test_obj_repr(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.NovaObject):
            fields = {'uuid': fields.StringField()}

        obj = Foo(objects=[Bar(uuid='fake-uuid')])
        self.assertEqual('Foo(objects=[Bar(fake-uuid)])', repr(obj))


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
        ser._conductor.object_backport.return_value = 'backported'

        class MyTestObj(MyObj):
            VERSION = my_version

        obj = MyTestObj()
        obj.VERSION = obj_version
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        if backported_to is None:
            self.assertFalse(ser._conductor.object_backport.called)
        else:
            self.assertEqual('backported', result)
            ser._conductor.object_backport.assert_called_with(self.context,
                                                              primitive,
                                                              backported_to)

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
        for item in primitive.itervalues():
            self.assertNotIsInstance(item, base.NovaObject)
        thing2 = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, len(thing2))
        for item in thing2.itervalues():
            self.assertIsInstance(item, MyObj)

        # object-action updates dict case
        thing = {'foo': obj.obj_to_primitive()}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(thing, primitive)
        thing2 = ser.deserialize_entity(self.context, thing)
        self.assertIsInstance(thing2['foo'], base.NovaObject)


# NOTE(danms): The hashes in this list should only be changed if
# they come with a corresponding version bump in the affected
# objects
object_data = {
    'Agent': '1.0-c4ff8a833aee8ae44ab8aed1a171273d',
    'AgentList': '1.0-31f07426a729311a42ff7f6246e76e25',
    'Aggregate': '1.1-f5d477be06150529a9b2d27cc49030b5',
    'AggregateList': '1.2-4b02a285b8612bfb86a96ff80052fb0a',
    'BandwidthUsage': '1.2-a9d7c2ba54995e48ce38688c51c9416d',
    'BandwidthUsageList': '1.2-5b564cbfd5ae6e106443c086938e7602',
    'BlockDeviceMapping': '1.8-c53f09c7f969e0222d9f6d67a950a08e',
    'BlockDeviceMappingList': '1.9-0faaeebdca213010c791bc37a22546e3',
    'ComputeNode': '1.10-70202a38b858977837b313d94475a26b',
    'ComputeNodeList': '1.10-4ae1f844c247029fbcdb5fdccbe9e619',
    'DNSDomain': '1.0-5bdc288d7c3b723ce86ede998fd5c9ba',
    'DNSDomainList': '1.0-cfb3e7e82be661501c31099523154db4',
    'EC2InstanceMapping': '1.0-627baaf4b12c9067200979bdc4558a99',
    'EC2SnapshotMapping': '1.0-26cf315be1f8abab4289d4147671c836',
    'EC2VolumeMapping': '1.0-2f8c3bf077c65a425294ec2b361c9143',
    'FixedIP': '1.9-2472964d39e50da67202109eb85cd173',
    'FixedIPList': '1.9-68ade91cf8d97053c1ef401d87eb6ecd',
    'Flavor': '1.1-096cfd023c35d07542cf732fb29b45e4',
    'FlavorList': '1.1-a3d5551267cb8f62ff38ded125900721',
    'FloatingIP': '1.6-27eb68b7c9c620dd5f0561b5a3be0e82',
    'FloatingIPList': '1.7-f376f63ed99243f9d90841b7f6732bbf',
    'HVSpec': '1.0-c4d8377cc4fe519930e60c1d8265a142',
    'Instance': '1.19-e5b80cc3b734b418d5c4b9140a4d2a25',
    'InstanceAction': '1.1-6b1d0a6dbd522b5a83c20757ec659663',
    'InstanceActionEvent': '1.1-42dbdba74bd06e0619ca75cd3397cd1b',
    'InstanceActionEventList': '1.0-1d5cc958171d6ce07383c2ad6208318e',
    'InstanceActionList': '1.0-368410fdb8d69ae20c495308535d6266',
    'InstanceExternalEvent': '1.0-f1134523654407a875fd59b80f759ee7',
    'InstanceFault': '1.2-313438e37e9d358f3566c85f6ddb2d3e',
    'InstanceFaultList': '1.1-aeb598ffd0cd6aa61fca7adf0f5e900d',
    'InstanceGroup': '1.9-95ece99f092e8f4f88327cdbb44162c9',
    'InstanceGroupList': '1.6-c6b78f3c9d9080d33c08667e80589817',
    'InstanceInfoCache': '1.5-ef64b604498bfa505a8c93747a9d8b2f',
    'InstanceList': '1.15-20d822b2abb0051d72f81ed686a79e5b',
    'InstanceNUMACell': '1.2-5d2dfa36e9ecca9b63f24bf3bc958ea4',
    'InstanceNUMATopology': '1.1-86b95d263c4c68411d44c6741b8d2bb0',
    'InstancePCIRequest': '1.1-e082d174f4643e5756ba098c47c1510f',
    'InstancePCIRequests': '1.1-bc7c6684d8579ee49d6a3b8aef756918',
    'KeyPair': '1.2-adf0be7b68e0b9f1ec011e23a9761354',
    'KeyPairList': '1.1-152dc1efcc46014cc10656a0d0ac5bb0',
    'Migration': '1.1-67c47726c2c71422058cd9d149d6d3ed',
    'MigrationList': '1.1-8c5f678edc72a592d591a13b35e54353',
    'MyObj': '1.6-02b1e712b7ee334fa3fefe024c340977',
    'MyOwnedObject': '1.0-0f3d6c028543d7f3715d121db5b8e298',
    'Network': '1.2-2ea21ede5e45bb80e7b7ac7106915c4e',
    'NetworkList': '1.2-aa4ad23f035b97a41732ea8b3445fc5e',
    'NetworkRequest': '1.1-f31192f5a725017707f989585e12d7dc',
    'NetworkRequestList': '1.1-beeab521ac9450f1f5ef4eaa945a783c',
    'NUMACell': '1.2-cb9c3b08cc1c418d021492f788d04173',
    'NUMAPagesTopology': '1.0-97d93f70a68625b5f29ff63a40a4f612',
    'NUMATopology': '1.2-790f6bdff85bf6e5677f409f3a4f1c6a',
    'PciDevice': '1.3-e059641df10e85d464672c5183a9473b',
    'PciDeviceList': '1.1-38cbe2d3c23b9e46f7a74b486abcad85',
    'PciDevicePool': '1.0-d6ed1abe611c9947345a44155abe6f11',
    'PciDevicePoolList': '1.0-d31e08e0ff620a4df7cc2014b6c50da8',
    'Quotas': '1.2-36098cf2143e6535873c3fa3d6fe56f7',
    'QuotasNoOp': '1.2-164c628906b170fd946a7672e85e4935',
    'S3ImageMapping': '1.0-9225943a44a91ad0349b9fd8bd3f3ce2',
    'SecurityGroup': '1.1-bba0e72865e0953793e796571692453b',
    'SecurityGroupList': '1.0-528e6448adfeeb78921ebeda499ab72f',
    'SecurityGroupRule': '1.1-a9175baf7664439af1a16c2010b55576',
    'SecurityGroupRuleList': '1.1-667fca3a9928f23d2d10e61962c55f3c',
    'Service': '1.9-82bbfd46a744a9c89bc44b47a1b81683',
    'ServiceList': '1.7-b856301eb7714839248e189bf4886168',
    'Tag': '1.0-a11531f4e4e3166eef6243d6d58a18bd',
    'TagList': '1.0-e89bf8c8055f1f1d654fb44f0abf1f53',
    'TestSubclassedObject': '1.6-87177ccbefd7a740a9e261f958e15b00',
    'VirtualInterface': '1.0-10fdac4c704102b6d57d6936d6d790d2',
    'VirtualInterfaceList': '1.0-accbf02628a8063c1d885077a2bf49b6',
    'VirtCPUFeature': '1.0-3cac8c77d84a632ba79da01a4b87afb9',
    'VirtCPUModel': '1.0-ae051080026849eddf7179e353673756',
    'VirtCPUTopology': '1.0-fc694de72e20298f7c6bab1083fd4563',
}


object_relationships = {
    'BlockDeviceMapping': {'Instance': '1.19'},
    'ComputeNode': {'HVSpec': '1.0', 'PciDevicePoolList': '1.0'},
    'FixedIP': {'Instance': '1.19', 'Network': '1.2',
                'VirtualInterface': '1.0',
                'FloatingIPList': '1.7'},
    'FloatingIP': {'FixedIP': '1.9'},
    'Instance': {'InstanceFault': '1.2',
                 'InstanceInfoCache': '1.5',
                 'InstanceNUMATopology': '1.1',
                 'PciDeviceList': '1.1',
                 'TagList': '1.0',
                 'SecurityGroupList': '1.0',
                 'Flavor': '1.1',
                 'InstancePCIRequests': '1.1',
                 'VirtCPUModel': '1.0',
                 },
    'InstanceNUMACell': {'VirtCPUTopology': '1.0'},
    'InstanceNUMATopology': {'InstanceNUMACell': '1.2'},
    'InstancePCIRequests': {'InstancePCIRequest': '1.1'},
    'MyObj': {'MyOwnedObject': '1.0'},
    'NUMACell': {'NUMAPagesTopology': '1.0'},
    'NUMATopology': {'NUMACell': '1.2'},
    'SecurityGroupRule': {'SecurityGroup': '1.1'},
    'Service': {'ComputeNode': '1.10'},
    'TestSubclassedObject': {'MyOwnedObject': '1.0'},
    'VirtCPUModel': {'VirtCPUFeature': '1.0', 'VirtCPUTopology': '1.0'},
    'TestSubclassedObject': {'MyOwnedObject': '1.0'}
}


class TestObjectVersions(test.TestCase):
    def _find_remotable_method(self, cls, thing, parent_was_remotable=False):
        """Follow a chain of remotable things down to the original function."""
        if isinstance(thing, classmethod):
            return self._find_remotable_method(cls, thing.__get__(None, cls))
        elif inspect.ismethod(thing) and hasattr(thing, 'remotable'):
            return self._find_remotable_method(cls, thing.original_fn,
                                               parent_was_remotable=True)
        elif parent_was_remotable:
            # We must be the first non-remotable thing underneath a stack of
            # remotable things (i.e. the actual implementation method)
            return thing
        else:
            # This means the top-level thing never hit a remotable layer
            return None

    def _get_fingerprint(self, obj_name):
        obj_class = base.NovaObject._obj_classes[obj_name][0]
        fields = obj_class.fields.items()
        fields.sort()
        methods = []
        for name in dir(obj_class):
            thing = getattr(obj_class, name)
            if inspect.ismethod(thing) or isinstance(thing, classmethod):
                method = self._find_remotable_method(obj_class, thing)
                if method:
                    methods.append((name, inspect.getargspec(method)))
        methods.sort()
        # NOTE(danms): Things that need a version bump are any fields
        # and their types, or the signatures of any remotable methods.
        # Of course, these are just the mechanical changes we can detect,
        # but many other things may require a version bump (method behavior
        # and return value changes, for example).
        if hasattr(obj_class, 'child_versions'):
            relevant_data = (fields, methods, obj_class.child_versions)
        else:
            relevant_data = (fields, methods)
        fingerprint = '%s-%s' % (obj_class.VERSION,
                                 hashlib.md5(str(relevant_data)).hexdigest())
        return fingerprint

    def test_versions(self):
        fingerprints = {}
        for obj_name in base.NovaObject._obj_classes:
            fingerprints[obj_name] = self._get_fingerprint(obj_name)

        if os.getenv('GENERATE_HASHES'):
            file('object_hashes.txt', 'w').write(
                pprint.pformat(fingerprints))
            raise test.TestingException(
                'Generated hashes in object_hashes.txt')

        stored = set(object_data.items())
        computed = set(fingerprints.items())
        changed = stored.symmetric_difference(computed)
        expected = {}
        actual = {}
        for name, hash in changed:
            expected[name] = object_data.get(name)
            actual[name] = fingerprints.get(name)

        self.assertEqual(expected, actual,
                         'Some objects have changed; please make sure the '
                         'versions have been bumped, and then update their '
                         'hashes here.')

    def _get_object_field_name(self, field):
        if isinstance(field._type, fields.Object):
            return field._type._obj_name
        if isinstance(field, fields.ListOfObjectsField):
            return field._type._element_type._type._obj_name
        return None

    def _build_tree(self, tree, obj_class):
        obj_name = obj_class.obj_name()
        if obj_name in tree:
            return

        for name, field in obj_class.fields.items():
            # Notes(yjiang5): ObjectListBase should be covered by
            # child_versions test
            if (issubclass(obj_class, base.ObjectListBase) and
                    name == 'objects'):
                continue
            sub_obj_name = self._get_object_field_name(field)
            if sub_obj_name:
                sub_obj_class = base.NovaObject._obj_classes[sub_obj_name][0]
                self._build_tree(tree, sub_obj_class)
                tree.setdefault(obj_name, {})
                tree[obj_name][sub_obj_name] = sub_obj_class.VERSION

    def test_relationships(self):
        tree = {}
        for obj_name in base.NovaObject._obj_classes.keys():
            self._build_tree(tree, base.NovaObject._obj_classes[obj_name][0])

        stored = set([(x, str(y)) for x, y in object_relationships.items()])
        computed = set([(x, str(y)) for x, y in tree.items()])
        changed = stored.symmetric_difference(computed)
        expected = {}
        actual = {}
        for name, deps in changed:
            expected[name] = object_relationships.get(name)
            actual[name] = tree.get(name)
        self.assertEqual(expected, actual,
                         'Some objects have changed dependencies. '
                         'Please make sure to bump the versions of '
                         'parent objects and provide a rule in their '
                         'obj_make_compatible() routines to backlevel '
                         'the child object.')

    def test_obj_make_compatible(self):
        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.
        for obj_name in base.NovaObject._obj_classes:
            obj_class = base.NovaObject._obj_classes[obj_name][0]
            version = utils.convert_version_to_tuple(obj_class.VERSION)
            for n in range(version[1]):
                test_version = '%d.%d' % (version[0], n)
                LOG.info('testing obj: %s version: %s' %
                         (obj_name, test_version))
                obj_class().obj_to_primitive(target_version=test_version)

    def test_obj_relationships_in_order(self):
        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.
        for obj_name in base.NovaObject._obj_classes:
            obj_class = base.NovaObject._obj_classes[obj_name][0]
            for field, versions in obj_class.obj_relationships.items():
                last_my_version = (0, 0)
                last_child_version = (0, 0)
                for my_version, child_version in versions:
                    _my_version = utils.convert_version_to_tuple(my_version)
                    _ch_version = utils.convert_version_to_tuple(child_version)
                    self.assertTrue((last_my_version < _my_version
                                     and last_child_version <= _ch_version),
                                    'Object %s relationship '
                                    '%s->%s for field %s is out of order' % (
                                        obj_name, my_version, child_version,
                                        field))
                    last_my_version = _my_version
                    last_child_version = _ch_version
