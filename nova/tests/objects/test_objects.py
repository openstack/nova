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
import datetime
import hashlib
import inspect
import os
import pprint

import mock
import six
from testtools import matchers

from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import rpc
from nova import test
from nova.tests import fake_notifier


class MyObj(base.NovaPersistentObject, base.NovaObject):
    VERSION = '1.6'
    fields = {'foo': fields.Field(fields.Integer()),
              'bar': fields.Field(fields.String()),
              'missing': fields.Field(fields.String()),
              'readonly': fields.Field(fields.Integer(), read_only=True),
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
        obj = cls(foo=1, bar='bar')
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

    def obj_make_compatible(self, primitive, target_version):
        # NOTE(danms): Simulate an older version that had a different
        # format for the 'bar' attribute
        if target_version == '1.1':
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
        obj_val = obj[key]
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
        self.context = context.RequestContext('fake-user', 'fake-project')
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
        # NOTE(danms): Can't use assertRaisesRegexp() because of py26
        raised = False
        try:
            obj.foobar
        except NotImplementedError as ex:
            raised = True
        self.assertTrue(raised)
        self.assertIn('foobar', str(ex))

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
        obj.save(self.context)
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh(self.context)
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')
        self.assertRemotes()

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify(self.context)
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
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
        myobj_fields = ['foo', 'bar', 'missing', 'readonly'] + base_fields
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields.keys()))

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
                         'updated_at=<?>)', repr(obj))


class TestObject(_LocalTest, _TestObject):
    pass


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
                list_obj_class.child_versions.values())

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

    def test_deserialize_entity_newer_version(self):
        ser = base.NovaObjectSerializer()
        ser._conductor = mock.Mock()
        ser._conductor.object_backport.return_value = 'backported'
        obj = MyObj()
        obj.VERSION = '1.25'
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        self.assertEqual('backported', result)
        ser._conductor.object_backport.assert_called_with(self.context,
                                                          primitive,
                                                          '1.6')

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


# NOTE(danms): The hashes in this list should only be changed if
# they come with a corresponding version bump in the affected
# objects
object_data = {
    'Agent': '1.0-c4ff8a833aee8ae44ab8aed1a171273d',
    'AgentList': '1.0-f8b860e1f2ce80e676ba1a37ddf86e4f',
    'Aggregate': '1.1-f5d477be06150529a9b2d27cc49030b5',
    'AggregateList': '1.2-504137b7ec3855b00d01f165dcebc23e',
    'BlockDeviceMapping': '1.1-9968ffe513e7672484b0f528b034cd0f',
    'BlockDeviceMappingList': '1.2-d6d7df540ca149dda78b22b4b10bdef3',
    'ComputeNode': '1.4-ed20e7a7c1a4612fe7d2836d5887c726',
    'ComputeNodeList': '1.3-ff59187056eaa96f6fd3fb70693d818c',
    'DNSDomain': '1.0-5bdc288d7c3b723ce86ede998fd5c9ba',
    'DNSDomainList': '1.0-6e3cc498d89dd7e90f9beb021644221c',
    'EC2InstanceMapping': '1.0-627baaf4b12c9067200979bdc4558a99',
    'EC2VolumeMapping': '1.0-2f8c3bf077c65a425294ec2b361c9143',
    'FixedIP': '1.1-082fb26772ce2db783ce4934edca4652',
    'FixedIPList': '1.1-8ea5cfca611598f1242fd4095e49e58b',
    'Flavor': '1.1-096cfd023c35d07542cf732fb29b45e4',
    'FlavorList': '1.1-d559595f55936a6d602721c3bdff6fff',
    'FloatingIP': '1.1-27eb68b7c9c620dd5f0561b5a3be0e82',
    'FloatingIPList': '1.2-1b77acb3523d16e3282624f51fee60d8',
    'Instance': '1.13-c9cfd71ddc9d6e7e7c72879f4d5982ee',
    'InstanceAction': '1.1-6b1d0a6dbd522b5a83c20757ec659663',
    'InstanceActionEvent': '1.1-f144eaa9fb22f248fc41ed8401a3a1be',
    'InstanceActionEventList': '1.0-937f4ed414ff2354de416834b948fbd6',
    'InstanceActionList': '1.0-d46ade45deeba63c55821e22c164bd1b',
    'InstanceExternalEvent': '1.0-f1134523654407a875fd59b80f759ee7',
    'InstanceFault': '1.2-313438e37e9d358f3566c85f6ddb2d3e',
    'InstanceFaultList': '1.1-bd578be60d045629ca7b3ce1a2493ae4',
    'InstanceGroup': '1.6-c032430832b3cbaf92c99088e4b2fdc8',
    'InstanceGroupList': '1.2-bebd07052779ae3b47311efe85428a8b',
    'InstanceInfoCache': '1.5-ef64b604498bfa505a8c93747a9d8b2f',
    'InstanceList': '1.6-78800140a5f9818ab00f8c052437655f',
    'KeyPair': '1.1-3410f51950d052d861c11946a6ae621a',
    'KeyPairList': '1.0-854cfff138dac9d5925c89cf805d1a70',
    'Migration': '1.1-67c47726c2c71422058cd9d149d6d3ed',
    'MigrationList': '1.1-6ca2ebb822ebfe1a660bace824b378c6',
    'MyObj': '1.6-9039bc29de1c08943771407697c83076',
    'Network': '1.2-2ea21ede5e45bb80e7b7ac7106915c4e',
    'NetworkList': '1.2-16510568c6e64cb8b358cb2b11333196',
    'PciDevice': '1.1-523c46f960d93f78db55f0280b09441e',
    'PciDeviceList': '1.0-5da7b4748a5a2594bae2cd0bd211cca2',
    'Quotas': '1.1-7897deef00e6cd3095c8916f68d24418',
    'QuotasNoOp': '1.1-4b06fd721c586b907ddd6543a00d6c2f',
    'SecurityGroup': '1.1-bba0e72865e0953793e796571692453b',
    'SecurityGroupList': '1.0-9513387aabf08c2a7961ac4da4315ed4',
    'SecurityGroupRule': '1.0-fdd020bdd7eb8bac744ad6f9a4ef8165',
    'SecurityGroupRuleList': '1.0-af4deeea8699ee90fb217f77d711d781',
    'Service': '1.2-5a3df338c669e1148251431370b440ef',
    'ServiceList': '1.0-ae64b4922df28d7cd11c59cddddf926c',
    'TestSubclassedObject': '1.6-1629421d83f474b7fadc41d3fc0e4998',
    'VirtualInterface': '1.0-10fdac4c704102b6d57d6936d6d790d2',
    'VirtualInterfaceList': '1.0-dc9e9d5bce522d28f96092c49119b3e0',
}


class TestObjectVersions(test.TestCase):
    def setUp(self):
        super(TestObjectVersions, self).setUp()
        self._fingerprints = {}

    def _get_fingerprint(self, obj_class):
        fields = obj_class.fields.items()
        fields.sort()
        methods = []
        for name in dir(obj_class):
            thing = getattr(obj_class, name)
            if inspect.ismethod(thing) and hasattr(thing, 'remotable'):
                methods.append((name, inspect.getargspec(thing.original_fn)))
        methods.sort()
        # NOTE(danms): Things that need a version bump are any fields
        # and their types, or the signatures of any remotable methods.
        # Of course, these are just the mechanical changes we can detect,
        # but many other things may require a version bump (method behavior
        # and return value changes, for example).
        relevant_data = (fields, methods)
        return '%s-%s' % (obj_class.VERSION,
                          hashlib.md5(str(relevant_data)).hexdigest())

    def _test_versions_cls(self, obj_name):
        obj_class = base.NovaObject._obj_classes[obj_name][0]
        expected_fingerprint = object_data.get(obj_name, 'unknown')
        actual_fingerprint = self._get_fingerprint(obj_class)

        self._fingerprints[obj_name] = actual_fingerprint

        if os.getenv('GENERATE_HASHES'):
            return

        self.assertEqual(
            expected_fingerprint, actual_fingerprint,
            ('%s object has changed; please make sure the version '
             'has been bumped, and then update this hash') % obj_name)

    def test_versions(self):
        for obj_name in base.NovaObject._obj_classes:
            self._test_versions_cls(obj_name)

        if os.getenv('GENERATE_HASHES'):
            file('object_hashes.txt', 'w').write(
                pprint.pformat(self._fingerprints))
            raise test.TestingException(
                'Generated hashes in object_hashes.txt')
