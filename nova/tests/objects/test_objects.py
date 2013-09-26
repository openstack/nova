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
import iso8601
import netaddr

from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import exception
from nova.objects import base
from nova.objects import utils
from nova.openstack.common import timeutils
from nova import test


class MyObj(base.NovaPersistentObject, base.NovaObject):
    version = '1.5'
    fields = {'foo': int,
              'bar': str,
              'missing': str,
              }

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        self = MyObj()
        self.foo = db_obj['foo']
        self.bar = db_obj['bar']
        self.missing = db_obj['missing']
        return self

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls()
        obj.foo = 1
        obj.bar = 'bar'
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self, context):
        return 'polo'

    @base.remotable
    def update_test(self, context):
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
    fields = {'new_field': str}


class TestMetaclass(test.TestCase):
    def test_obj_tracking(self):

        class NewBaseClass(object):
            __metaclass__ = base.NovaObjectMetaclass
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        class Test1(NewBaseClass):
            @staticmethod
            def obj_name():
                return 'fake1'

        class Test2(NewBaseClass):
            pass

        class Test2v2(NewBaseClass):
            @staticmethod
            def obj_name():
                return 'Test2'

        expected = {'fake1': [Test1], 'Test2': [Test2, Test2v2]}

        self.assertEqual(expected, NewBaseClass._obj_classes)
        # The following should work, also.
        self.assertEqual(expected, Test1._obj_classes)
        self.assertEqual(expected, Test2._obj_classes)


class TestUtils(test.TestCase):
    def test_datetime_or_none(self):
        naive_dt = timeutils.utcnow()
        dt = timeutils.parse_isotime(timeutils.isotime(naive_dt))
        self.assertEqual(utils.datetime_or_none(dt), dt)
        self.assertEqual(utils.datetime_or_none(dt),
                         naive_dt.replace(tzinfo=iso8601.iso8601.Utc(),
                                          microsecond=0))
        self.assertEqual(utils.datetime_or_none(None), None)
        self.assertRaises(ValueError, utils.datetime_or_none, 'foo')

    def test_datetime_or_str_or_none(self):
        dts = timeutils.isotime()
        dt = timeutils.parse_isotime(dts)
        self.assertEqual(utils.datetime_or_str_or_none(dt), dt)
        self.assertEqual(utils.datetime_or_str_or_none(None), None)
        self.assertEqual(utils.datetime_or_str_or_none(dts), dt)
        self.assertRaises(ValueError, utils.datetime_or_str_or_none, 'foo')

    def test_int_or_none(self):
        self.assertEqual(utils.int_or_none(1), 1)
        self.assertEqual(utils.int_or_none('1'), 1)
        self.assertEqual(utils.int_or_none(None), None)
        self.assertRaises(ValueError, utils.int_or_none, 'foo')

    def test_str_or_none(self):
        class Obj(object):
            pass
        self.assertEqual(utils.str_or_none('foo'), 'foo')
        self.assertEqual(utils.str_or_none(1), '1')
        self.assertEqual(utils.str_or_none(None), None)
        self.assertTrue(isinstance(utils.str_or_none('foo'), unicode))

    def test_str_value(self):
        self.assertEqual('foo', utils.str_value('foo'))
        self.assertEqual('1', utils.str_value(1))
        self.assertRaises(ValueError, utils.str_value, None)
        self.assertTrue(isinstance(utils.str_value('foo'), unicode))

    def test_cstring(self):
        self.assertEqual('foo', utils.cstring('foo'))
        self.assertEqual('1', utils.cstring(1))
        self.assertRaises(ValueError, utils.cstring, None)

    def test_ip_or_none(self):
        ip4 = netaddr.IPAddress('1.2.3.4', 4)
        ip6 = netaddr.IPAddress('1::2', 6)
        self.assertEqual(utils.ip_or_none(4)('1.2.3.4'), ip4)
        self.assertEqual(utils.ip_or_none(6)('1::2'), ip6)
        self.assertEqual(utils.ip_or_none(4)(None), None)
        self.assertEqual(utils.ip_or_none(6)(None), None)
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(4), 'foo')
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(6), 'foo')

    def test_list_of_strings_or_none(self):
        self.assertEqual(utils.list_of_strings_or_none(None), None)
        self.assertEqual(utils.list_of_strings_or_none(['1', '2']),
                         ['1', '2'])
        self.assertRaises(ValueError,
                          utils.list_of_strings_or_none, 'foo')
        self.assertRaises(ValueError,
                          utils.list_of_strings_or_none, [1, 2])
        self.assertRaises(ValueError,
                          utils.list_of_strings_or_none, ['1', 2])

    def test_dict_of_strings_or_none(self):
        self.assertEqual(utils.dict_of_strings_or_none(None), None)
        self.assertEqual(utils.dict_of_strings_or_none({'1': '2'}),
                         {'1': '2'})
        self.assertRaises(ValueError,
                          utils.dict_of_strings_or_none, {'1': '2', '3': 4})
        self.assertRaises(ValueError,
                          utils.dict_of_strings_or_none, {'1': '2', 3: '4'})
        self.assertRaises(ValueError,
                          utils.dict_of_strings_or_none, {'1': '2', 3: '4'})
        self.assertRaises(ValueError,
                          utils.dict_of_strings_or_none, 'foo')

    def test_dt_serializer(self):
        class Obj(object):
            foo = utils.dt_serializer('bar')

        obj = Obj()
        obj.bar = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual(obj.foo(), '1955-11-05T00:00:00Z')
        obj.bar = None
        self.assertEqual(obj.foo(), None)
        obj.bar = 'foo'
        self.assertRaises(AttributeError, obj.foo)

    def test_dt_deserializer(self):
        dt = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual(utils.dt_deserializer(None, timeutils.isotime(dt)),
                         dt)
        self.assertEqual(utils.dt_deserializer(None, None), None)
        self.assertRaises(ValueError, utils.dt_deserializer, None, 'foo')

    def test_obj_to_primitive_list(self):
        class MyList(base.ObjectListBase, base.NovaObject):
            pass
        mylist = MyList()
        mylist.objects = [1, 2, 3]
        self.assertEqual([1, 2, 3], base.obj_to_primitive(mylist))

    def test_obj_to_primitive_dict(self):
        myobj = MyObj()
        myobj.foo = 1
        myobj.bar = 'foo'
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        class MyList(base.ObjectListBase, base.NovaObject):
            pass

        mylist = MyList()
        mylist.objects = [MyObj(), MyObj()]
        for i, value in enumerate(mylist):
            value.foo = i
        self.assertEqual([{'foo': 0}, {'foo': 1}],
                         base.obj_to_primitive(mylist))

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


def compare_obj(test, obj, db_obj, subs=None, allow_missing=None):
    """Compare a NovaObject and a dict-like database object.

    This automatically converts TZ-aware datetimes and iterates over
    the fields of the object.

    :param:test: The TestCase doing the comparison
    :param:obj: The NovaObject to examine
    :param:db_obj: The dict-like database object to use as reference
    :param:subs: A dict of objkey=dbkey field substitutions
    :param:allow_missing: A list of fields that may not be in db_obj
    """

    if subs is None:
        subs = {}
    if allow_missing is None:
        allow_missing = []

    for key in obj.fields:
        if key in allow_missing and not obj.obj_attr_is_set(key):
            continue
        obj_val = obj[key]
        db_key = subs.get(key, key)
        db_val = db_obj[db_key]
        if isinstance(obj_val, datetime.datetime):
            obj_val = obj_val.replace(tzinfo=None)
        test.assertEqual(db_val, obj_val)


class _BaseTestCase(test.TestCase):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.remote_object_calls = list()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def compare_obj(self, obj, db_obj, subs=None, allow_missing=None):
        compare_obj(self, obj, db_obj, subs=subs, allow_missing=allow_missing)


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
            return result
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

    def setUp(self):
        super(_RemoteTest, self).setUp()
        self._testable_conductor()

    def assertRemotes(self):
        self.assertNotEqual(self.remote_object_calls, [])


class _TestObject(object):
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
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj.foo, 1)

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
                    'nova_object.version': '1.5',
                    'nova_object.data': {'foo': 1}}
        obj = MyObj()
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_object_property(self):
        obj = MyObj()
        obj.foo = 1
        self.assertEqual(obj.foo, 1)

    def test_object_property_type_error(self):
        obj = MyObj()

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_object_dict_syntax(self):
        obj = MyObj()
        obj.foo = 123
        obj.bar = 'bar'
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
            fields = {'foobar': int}
        obj = Foo()
        # NOTE(danms): Can't use assertRaisesRegexp() because of py26
        raised = False
        try:
            obj.foobar
        except NotImplementedError as ex:
            raised = True
        self.assertTrue(raised)
        self.assertTrue('foobar' in str(ex))

    def test_loaded_in_primitive(self):
        obj = MyObj()
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual(obj.bar, 'loaded!')
        expected = {'nova_object.name': 'MyObj',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.5',
                    'nova_object.changes': ['bar'],
                    'nova_object.data': {'foo': 1,
                                         'bar': 'loaded!'}}
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_changes_in_primitive(self):
        obj = MyObj()
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        primitive = obj.obj_to_primitive()
        self.assertTrue('nova_object.changes' in primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj2.obj_what_changed(), set(['foo']))
        obj2.obj_reset_changes()
        self.assertEqual(obj2.obj_what_changed(), set())

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.NovaObject.obj_class_from_name, 'foo', '1.0')

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext('foo', 'foo')
        ctxt2 = context.RequestContext('bar', 'alternate')
        obj = MyObj.query(ctxt1)
        obj.update_test(ctxt2)
        self.assertEqual(obj.bar, 'alternate-context')
        self.assertRemotes()

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj.update_test)
        self.assertRemotes()

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.update_test(self.context)
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

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        result = obj.marco()
        self.assertEqual(result, 'polo')
        self.assertRemotes()

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.foo, 1)
        obj.update_test()
        self.assertEqual(obj.bar, 'updated')
        self.assertRemotes()

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5)
        obj = MyObj()
        obj.created_at = dt
        obj.updated_at = dt
        obj.deleted_at = None
        obj.deleted = False
        expected = {'nova_object.name': 'MyObj',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.5',
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
        self.assertFalse('foo' in obj)
        obj.foo = 1
        self.assertTrue('foo' in obj)
        self.assertFalse('does_not_exist' in obj)

    def test_obj_attr_is_set(self):
        obj = MyObj()
        obj.foo = 1
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_get(self):
        obj = MyObj()
        obj.foo = 1
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
        myobj_fields = ['foo', 'bar', 'missing'] + base_fields
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
            fields = {'foo': int}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj()
        self.assertEqual(['foo', 'bar'], obj.obj_fields)


class TestObject(_LocalTest, _TestObject):
    pass


class TestRemoteObject(_RemoteTest, _TestObject):
    def test_major_version_mismatch(self):
        MyObj2.version = '2.0'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_greater(self):
        MyObj2.version = '1.6'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_less(self):
        MyObj2.version = '1.2'
        obj = MyObj2.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        self.assertRemotes()


class TestObjectListBase(test.TestCase):
    def test_list_like_operations(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            pass

        objlist = Foo()
        objlist._context = 'foo'
        objlist.objects = [1, 2, 3]
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(len(objlist), 3)
        self.assertIn(2, objlist)
        self.assertEqual(list(objlist[:1]), [1])
        self.assertEqual(objlist[:1]._context, 'foo')
        self.assertEqual(objlist[2], 3)
        self.assertEqual(objlist.count(1), 1)
        self.assertEqual(objlist.index(2), 1)

    def test_serialization(self):
        class Foo(base.ObjectListBase, base.NovaObject):
            pass

        class Bar(base.NovaObject):
            fields = {'foo': str}

        obj = Foo()
        obj.objects = []
        for i in 'abc':
            bar = Bar()
            bar.foo = i
            obj.objects.append(bar)

        obj2 = base.NovaObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])


class TestObjectSerializer(_BaseTestCase):
    def test_serialize_entity_primitive(self):
        ser = base.NovaObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.serialize_entity(None, thing))

    def test_deserialize_entity_primitive(self):
        ser = base.NovaObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.deserialize_entity(None, thing))

    def test_object_serialization(self):
        ser = base.NovaObjectSerializer()
        obj = MyObj()
        primitive = ser.serialize_entity(self.context, obj)
        self.assertTrue('nova_object.name' in primitive)
        obj2 = ser.deserialize_entity(self.context, primitive)
        self.assertTrue(isinstance(obj2, MyObj))
        self.assertEqual(self.context, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.NovaObjectSerializer()
        obj = MyObj()
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(self.context, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertFalse(isinstance(item, base.NovaObject))
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertTrue(isinstance(item, MyObj))
