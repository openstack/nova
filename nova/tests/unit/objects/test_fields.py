#    Copyright 2013 Red Hat, Inc.
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

import datetime
import os

import iso8601
import mock
from oslo_versionedobjects import exception as ovo_exc
import six

from nova import exception
from nova.network import model as network_model
from nova.objects import fields
from nova import test
from nova.tests.unit import fake_instance
from nova import utils


class FakeFieldType(fields.FieldType):
    def coerce(self, obj, attr, value):
        return '*%s*' % value

    def to_primitive(self, obj, attr, value):
        return '!%s!' % value

    def from_primitive(self, obj, attr, value):
        return value[1:-1]


class FakeEnum(fields.Enum):
    FROG = "frog"
    PLATYPUS = "platypus"
    ALLIGATOR = "alligator"

    ALL = (FROG, PLATYPUS, ALLIGATOR)

    def __init__(self, **kwargs):
        super(FakeEnum, self).__init__(valid_values=FakeEnum.ALL,
                                       **kwargs)


class FakeEnumAlt(fields.Enum):
    FROG = "frog"
    PLATYPUS = "platypus"
    AARDVARK = "aardvark"

    ALL = (FROG, PLATYPUS, AARDVARK)

    def __init__(self, **kwargs):
        super(FakeEnumAlt, self).__init__(valid_values=FakeEnumAlt.ALL,
                                          **kwargs)


class FakeAddress(fields.AddressBase):
    PATTERN = '[a-z]+[0-9]+'


class FakeAddressField(fields.AutoTypedField):
    AUTO_TYPE = FakeAddress()


class FakeEnumField(fields.BaseEnumField):
    AUTO_TYPE = FakeEnum()


class FakeEnumAltField(fields.BaseEnumField):
    AUTO_TYPE = FakeEnumAlt()


class TestField(test.NoDBTestCase):
    def setUp(self):
        super(TestField, self).setUp()
        self.field = fields.Field(FakeFieldType())
        self.coerce_good_values = [('foo', '*foo*')]
        self.coerce_bad_values = []
        self.to_primitive_values = [('foo', '!foo!')]
        self.from_primitive_values = [('!foo!', 'foo')]

    def test_coerce_good_values(self):
        for in_val, out_val in self.coerce_good_values:
            self.assertEqual(out_val, self.field.coerce('obj', 'attr', in_val))

    def test_coerce_bad_values(self):
        for in_val in self.coerce_bad_values:
            self.assertRaises((TypeError, ValueError),
                              self.field.coerce, 'obj', 'attr', in_val)

    def test_to_primitive(self):
        for in_val, prim_val in self.to_primitive_values:
            self.assertEqual(prim_val, self.field.to_primitive('obj', 'attr',
                                                               in_val))

    def test_from_primitive(self):
        class ObjectLikeThing(object):
            _context = 'context'

        for prim_val, out_val in self.from_primitive_values:
            self.assertEqual(out_val, self.field.from_primitive(
                    ObjectLikeThing, 'attr', prim_val))

    def test_stringify(self):
        self.assertEqual('123', self.field.stringify(123))


class TestString(TestField):
    def setUp(self):
        super(TestString, self).setUp()
        self.field = fields.StringField()
        self.coerce_good_values = [('foo', 'foo'), (1, '1'), (True, 'True')]
        if six.PY2:
            self.coerce_good_values.append((int(1), '1'))
        self.coerce_bad_values = [None]
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'123'", self.field.stringify(123))


class TestBaseEnum(TestField):
    def setUp(self):
        super(TestBaseEnum, self).setUp()
        self.field = FakeEnumField()
        self.coerce_good_values = [('frog', 'frog'),
                                   ('platypus', 'platypus'),
                                   ('alligator', 'alligator')]
        self.coerce_bad_values = ['aardvark', 'wookie']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'platypus'", self.field.stringify('platypus'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'aardvark')

    def test_fingerprint(self):
        # Notes(yjiang5): make sure changing valid_value will be detected
        # in test_objects.test_versions
        field1 = FakeEnumField()
        field2 = FakeEnumAltField()
        self.assertNotEqual(str(field1), str(field2))


class TestEnum(TestField):
    def setUp(self):
        super(TestEnum, self).setUp()
        self.field = fields.EnumField(
            valid_values=['foo', 'bar', 1, 1, True])
        self.coerce_good_values = [('foo', 'foo'), (1, '1'), (True, 'True')]
        if six.PY2:
            self.coerce_good_values.append((int(1), '1'))
        self.coerce_bad_values = ['boo', 2, False]
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'foo'", self.field.stringify('foo'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, '123')

    def test_fingerprint(self):
        # Notes(yjiang5): make sure changing valid_value will be detected
        # in test_objects.test_versions
        field1 = fields.EnumField(valid_values=['foo', 'bar'])
        field2 = fields.EnumField(valid_values=['foo', 'bar1'])
        self.assertNotEqual(str(field1), str(field2))

    def test_without_valid_values(self):
        self.assertRaises(ovo_exc.EnumValidValuesInvalidError,
                          fields.EnumField, 1)

    def test_with_empty_values(self):
        self.assertRaises(ovo_exc.EnumRequiresValidValuesError,
                          fields.EnumField, [])


class TestArchitecture(TestField):
    @mock.patch.object(os, 'uname')
    def test_host(self, mock_uname):
        mock_uname.return_value = (
            'Linux',
            'localhost.localdomain',
            '3.14.8-200.fc20.x86_64',
            '#1 SMP Mon Jun 16 21:57:53 UTC 2014',
            'i686'
        )

        self.assertEqual(fields.Architecture.I686,
                         fields.Architecture.from_host())

    def test_valid_string(self):
        self.assertTrue(fields.Architecture.is_valid('x86_64'))

    def test_valid_constant(self):
        self.assertTrue(fields.Architecture.is_valid(
            fields.Architecture.X86_64))

    def test_valid_bogus(self):
        self.assertFalse(fields.Architecture.is_valid('x86_64wibble'))

    def test_canonicalize_i386(self):
        self.assertEqual(fields.Architecture.I686,
                         fields.Architecture.canonicalize('i386'))

    def test_canonicalize_amd64(self):
        self.assertEqual(fields.Architecture.X86_64,
                         fields.Architecture.canonicalize('amd64'))

    def test_canonicalize_case(self):
        self.assertEqual(fields.Architecture.X86_64,
                         fields.Architecture.canonicalize('X86_64'))

    def test_canonicalize_compat_xen1(self):
        self.assertEqual(fields.Architecture.I686,
                         fields.Architecture.canonicalize('x86_32'))

    def test_canonicalize_compat_xen2(self):
        self.assertEqual(fields.Architecture.I686,
                         fields.Architecture.canonicalize('x86_32p'))

    def test_canonicalize_invalid(self):
        self.assertRaises(exception.InvalidArchitectureName,
                          fields.Architecture.canonicalize,
                          'x86_64wibble')


class TestHVType(TestField):
    def test_valid_string(self):
        self.assertTrue(fields.HVType.is_valid('vmware'))

    def test_valid_constant(self):
        self.assertTrue(fields.HVType.is_valid(fields.HVType.QEMU))

    def test_valid_docker(self):
        self.assertTrue(fields.HVType.is_valid('docker'))

    def test_valid_lxd(self):
        self.assertTrue(fields.HVType.is_valid('lxd'))

    def test_valid_vz(self):
        self.assertTrue(fields.HVType.is_valid(
            fields.HVType.VIRTUOZZO))

    def test_valid_bogus(self):
        self.assertFalse(fields.HVType.is_valid('acmehypervisor'))

    def test_canonicalize_none(self):
        self.assertIsNone(fields.HVType.canonicalize(None))

    def test_canonicalize_case(self):
        self.assertEqual(fields.HVType.QEMU,
                         fields.HVType.canonicalize('QeMu'))

    def test_canonicalize_xapi(self):
        self.assertEqual(fields.HVType.XEN,
                         fields.HVType.canonicalize('xapi'))

    def test_canonicalize_invalid(self):
        self.assertRaises(exception.InvalidHypervisorVirtType,
                          fields.HVType.canonicalize,
                          'wibble')


class TestVMMode(TestField):
    def _fake_object(self, updates):
        return fake_instance.fake_instance_obj(None, **updates)

    def test_case(self):
        inst = self._fake_object(dict(vm_mode='HVM'))
        mode = fields.VMMode.get_from_instance(inst)
        self.assertEqual(mode, 'hvm')

    def test_legacy_pv(self):
        inst = self._fake_object(dict(vm_mode='pv'))
        mode = fields.VMMode.get_from_instance(inst)
        self.assertEqual(mode, 'xen')

    def test_legacy_hv(self):
        inst = self._fake_object(dict(vm_mode='hv'))
        mode = fields.VMMode.get_from_instance(inst)
        self.assertEqual(mode, 'hvm')

    def test_bogus(self):
        inst = self._fake_object(dict(vm_mode='wibble'))
        self.assertRaises(exception.Invalid,
                          fields.VMMode.get_from_instance,
                          inst)

    def test_good(self):
        inst = self._fake_object(dict(vm_mode='hvm'))
        mode = fields.VMMode.get_from_instance(inst)
        self.assertEqual(mode, 'hvm')

    def test_canonicalize_pv_compat(self):
        mode = fields.VMMode.canonicalize('pv')
        self.assertEqual(fields.VMMode.XEN, mode)

    def test_canonicalize_hv_compat(self):
        mode = fields.VMMode.canonicalize('hv')
        self.assertEqual(fields.VMMode.HVM, mode)

    def test_canonicalize_baremetal_compat(self):
        mode = fields.VMMode.canonicalize('baremetal')
        self.assertEqual(fields.VMMode.HVM, mode)

    def test_canonicalize_hvm(self):
        mode = fields.VMMode.canonicalize('hvm')
        self.assertEqual(fields.VMMode.HVM, mode)

    def test_canonicalize_none(self):
        mode = fields.VMMode.canonicalize(None)
        self.assertIsNone(mode)

    def test_canonicalize_invalid(self):
        self.assertRaises(exception.InvalidVirtualMachineMode,
                          fields.VMMode.canonicalize,
                          'invalid')


class TestResourceClass(TestString):
    def setUp(self):
        super(TestResourceClass, self).setUp()
        self.field = fields.ResourceClassField()
        self.coerce_good_values = [
            ('VCPU', 'VCPU'),
            ('MEMORY_MB', 'MEMORY_MB'),
            ('DISK_GB', 'DISK_GB'),
            ('PCI_DEVICE', 'PCI_DEVICE'),
            ('SRIOV_NET_VF', 'SRIOV_NET_VF'),
            ('NUMA_SOCKET', 'NUMA_SOCKET'),
            ('NUMA_CORE', 'NUMA_CORE'),
            ('NUMA_THREAD', 'NUMA_THREAD'),
            ('NUMA_MEMORY_MB', 'NUMA_MEMORY_MB'),
            ('IPV4_ADDRESS', 'IPV4_ADDRESS'),
            ('VGPU', 'VGPU'),
            ('VGPU_DISPLAY_HEAD', 'VGPU_DISPLAY_HEAD'),
        ]
        self.coerce_bad_values = [object(), dict()]
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_normalize_name(self):
        values = [
            ("foo", "CUSTOM_FOO"),
            ("VCPU", "CUSTOM_VCPU"),
            ("CUSTOM_BOB", "CUSTOM_CUSTOM_BOB"),
            ("CUSTM_BOB", "CUSTOM_CUSTM_BOB"),
        ]
        for test_value, expected in values:
            result = fields.ResourceClass.normalize_name(test_value)
            self.assertEqual(expected, result)


class TestInteger(TestField):
    def setUp(self):
        super(TestInteger, self).setUp()
        self.field = fields.IntegerField()
        self.coerce_good_values = [(1, 1), ('1', 1)]
        self.coerce_bad_values = ['foo', None]
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]


class TestNonNegativeInteger(TestInteger):
    def setUp(self):
        super(TestNonNegativeInteger, self).setUp()
        self.field = fields.NonNegativeIntegerField()
        self.coerce_bad_values.extend(['-2', '4.2'])


class TestFloat(TestField):
    def setUp(self):
        super(TestFloat, self).setUp()
        self.field = fields.FloatField()
        self.coerce_good_values = [(1.1, 1.1), ('1.1', 1.1)]
        self.coerce_bad_values = ['foo', None]
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]


class TestNonNegativeFloat(TestFloat):
    def setUp(self):
        super(TestNonNegativeFloat, self).setUp()
        self.field = fields.NonNegativeFloatField()
        self.coerce_bad_values.extend(['-4.2'])


class TestBoolean(TestField):
    def setUp(self):
        super(TestBoolean, self).setUp()
        self.field = fields.BooleanField()
        self.coerce_good_values = [(True, True), (False, False), (1, True),
                                   ('foo', True), (0, False), ('', False)]
        self.coerce_bad_values = []
        self.to_primitive_values = self.coerce_good_values[0:2]
        self.from_primitive_values = self.coerce_good_values[0:2]


class TestDateTime(TestField):
    def setUp(self):
        super(TestDateTime, self).setUp()
        self.dt = datetime.datetime(1955, 11, 5, tzinfo=iso8601.UTC)
        self.field = fields.DateTimeField()
        self.coerce_good_values = [(self.dt, self.dt),
                                   (utils.isotime(self.dt), self.dt)]
        self.coerce_bad_values = [1, 'foo']
        self.to_primitive_values = [(self.dt, utils.isotime(self.dt))]
        self.from_primitive_values = [(utils.isotime(self.dt), self.dt)]

    def test_stringify(self):
        self.assertEqual(
            '1955-11-05T18:00:00Z',
            self.field.stringify(
                datetime.datetime(1955, 11, 5, 18, 0, 0,
                                  tzinfo=iso8601.UTC)))


class TestDict(TestField):
    def setUp(self):
        super(TestDict, self).setUp()
        self.field = fields.Field(fields.Dict(FakeFieldType()))
        self.coerce_good_values = [({'foo': 'bar'}, {'foo': '*bar*'}),
                                   ({'foo': 1}, {'foo': '*1*'})]
        self.coerce_bad_values = [{1: 'bar'}, 'foo']
        self.to_primitive_values = [({'foo': 'bar'}, {'foo': '!bar!'})]
        self.from_primitive_values = [({'foo': '!bar!'}, {'foo': 'bar'})]

    def test_stringify(self):
        self.assertEqual("{key=val}", self.field.stringify({'key': 'val'}))


class TestDictOfStrings(TestField):
    def setUp(self):
        super(TestDictOfStrings, self).setUp()
        self.field = fields.DictOfStringsField()
        self.coerce_good_values = [({'foo': 'bar'}, {'foo': 'bar'}),
                                   ({'foo': 1}, {'foo': '1'})]
        self.coerce_bad_values = [{1: 'bar'}, {'foo': None}, 'foo']
        self.to_primitive_values = [({'foo': 'bar'}, {'foo': 'bar'})]
        self.from_primitive_values = [({'foo': 'bar'}, {'foo': 'bar'})]

    def test_stringify(self):
        self.assertEqual("{key='val'}", self.field.stringify({'key': 'val'}))


class TestDictOfIntegers(TestField):
    def setUp(self):
        super(TestDictOfIntegers, self).setUp()
        self.field = fields.DictOfIntegersField()
        self.coerce_good_values = [({'foo': '42'}, {'foo': 42}),
                                   ({'foo': 4.2}, {'foo': 4})]
        self.coerce_bad_values = [{1: 'bar'}, {'foo': 'boo'},
                                  'foo', {'foo': None}]
        self.to_primitive_values = [({'foo': 42}, {'foo': 42})]
        self.from_primitive_values = [({'foo': 42}, {'foo': 42})]

    def test_stringify(self):
        self.assertEqual("{key=42}", self.field.stringify({'key': 42}))


class TestDictOfStringsNone(TestField):
    def setUp(self):
        super(TestDictOfStringsNone, self).setUp()
        self.field = fields.DictOfNullableStringsField()
        self.coerce_good_values = [({'foo': 'bar'}, {'foo': 'bar'}),
                                   ({'foo': 1}, {'foo': '1'}),
                                   ({'foo': None}, {'foo': None})]
        self.coerce_bad_values = [{1: 'bar'}, 'foo']
        self.to_primitive_values = [({'foo': 'bar'}, {'foo': 'bar'})]
        self.from_primitive_values = [({'foo': 'bar'}, {'foo': 'bar'})]

    def test_stringify(self):
        self.assertEqual("{k2=None,key='val'}",
                         self.field.stringify({'k2': None,
                                               'key': 'val'}))


class TestListOfDictOfNullableStringsField(TestField):
    def setUp(self):
        super(TestListOfDictOfNullableStringsField, self).setUp()
        self.field = fields.ListOfDictOfNullableStringsField()
        self.coerce_good_values = [([{'f': 'b', 'f1': 'b1'}, {'f2': 'b2'}],
                                    [{'f': 'b', 'f1': 'b1'}, {'f2': 'b2'}]),
                                   ([{'f': 1}, {'f1': 'b1'}],
                                    [{'f': '1'}, {'f1': 'b1'}]),
                                   ([{'foo': None}], [{'foo': None}])]
        self.coerce_bad_values = [[{1: 'a'}], ['ham', 1], ['eggs']]
        self.to_primitive_values = [([{'f': 'b'}, {'f1': 'b1'}, {'f2': None}],
                                     [{'f': 'b'}, {'f1': 'b1'}, {'f2': None}])]
        self.from_primitive_values = [([{'f': 'b'}, {'f1': 'b1'},
                                        {'f2': None}],
                                       [{'f': 'b'}, {'f1': 'b1'},
                                        {'f2': None}])]

    def test_stringify(self):
        self.assertEqual("[{f=None,f1='b1'},{f2='b2'}]",
                         self.field.stringify(
                            [{'f': None, 'f1': 'b1'}, {'f2': 'b2'}]))


class TestList(TestField):
    def setUp(self):
        super(TestList, self).setUp()
        self.field = fields.Field(fields.List(FakeFieldType()))
        self.coerce_good_values = [(['foo', 'bar'], ['*foo*', '*bar*'])]
        self.coerce_bad_values = ['foo']
        self.to_primitive_values = [(['foo'], ['!foo!'])]
        self.from_primitive_values = [(['!foo!'], ['foo'])]

    def test_stringify(self):
        self.assertEqual('[123]', self.field.stringify([123]))


class TestListOfStrings(TestField):
    def setUp(self):
        super(TestListOfStrings, self).setUp()
        self.field = fields.ListOfStringsField()
        self.coerce_good_values = [(['foo', 'bar'], ['foo', 'bar'])]
        self.coerce_bad_values = ['foo']
        self.to_primitive_values = [(['foo'], ['foo'])]
        self.from_primitive_values = [(['foo'], ['foo'])]

    def test_stringify(self):
        self.assertEqual("['abc']", self.field.stringify(['abc']))


class TestSet(TestField):
    def setUp(self):
        super(TestSet, self).setUp()
        self.field = fields.Field(fields.Set(FakeFieldType()))
        self.coerce_good_values = [(set(['foo', 'bar']),
                                    set(['*foo*', '*bar*']))]
        self.coerce_bad_values = [['foo'], {'foo': 'bar'}]
        self.to_primitive_values = [(set(['foo']), tuple(['!foo!']))]
        self.from_primitive_values = [(tuple(['!foo!']), set(['foo']))]

    def test_stringify(self):
        self.assertEqual('set([123])', self.field.stringify(set([123])))


class TestSetOfIntegers(TestField):
    def setUp(self):
        super(TestSetOfIntegers, self).setUp()
        self.field = fields.SetOfIntegersField()
        self.coerce_good_values = [(set(['1', 2]),
                                    set([1, 2]))]
        self.coerce_bad_values = [set(['foo'])]
        self.to_primitive_values = [(set([1]), tuple([1]))]
        self.from_primitive_values = [(tuple([1]), set([1]))]

    def test_stringify(self):
        self.assertEqual('set([1,2])', self.field.stringify(set([1, 2])))


class TestListOfSetsOfIntegers(TestField):
    def setUp(self):
        super(TestListOfSetsOfIntegers, self).setUp()
        self.field = fields.ListOfSetsOfIntegersField()
        self.coerce_good_values = [([set(['1', 2]), set([3, '4'])],
                                    [set([1, 2]), set([3, 4])])]
        self.coerce_bad_values = [[set(['foo'])]]
        self.to_primitive_values = [([set([1])], [tuple([1])])]
        self.from_primitive_values = [([tuple([1])], [set([1])])]

    def test_stringify(self):
        self.assertEqual('[set([1,2])]', self.field.stringify([set([1, 2])]))


class TestNetworkModel(TestField):
    def setUp(self):
        super(TestNetworkModel, self).setUp()
        model = network_model.NetworkInfo()
        self.field = fields.Field(fields.NetworkModel())
        self.coerce_good_values = [(model, model), (model.json(), model)]
        self.coerce_bad_values = [[], 'foo']
        self.to_primitive_values = [(model, model.json())]
        self.from_primitive_values = [(model.json(), model)]

    def test_stringify(self):
        networkinfo = network_model.NetworkInfo()
        networkinfo.append(network_model.VIF(id=123))
        networkinfo.append(network_model.VIF(id=456))
        self.assertEqual('NetworkModel(123,456)',
                         self.field.stringify(networkinfo))


class TestNotificationPriority(TestField):
    def setUp(self):
        super(TestNotificationPriority, self).setUp()
        self.field = fields.NotificationPriorityField()
        self.coerce_good_values = [('audit', 'audit'),
                                   ('critical', 'critical'),
                                   ('debug', 'debug'),
                                   ('error', 'error'),
                                   ('sample', 'sample'),
                                   ('warn', 'warn')]
        self.coerce_bad_values = ['warning']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'warn'", self.field.stringify('warn'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'warning')


class TestNotificationPhase(TestField):
    def setUp(self):
        super(TestNotificationPhase, self).setUp()
        self.field = fields.NotificationPhaseField()
        self.coerce_good_values = [('start', 'start'),
                                   ('end', 'end'),
                                   ('error', 'error')]
        self.coerce_bad_values = ['begin']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'error'", self.field.stringify('error'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'begin')


class TestNotificationAction(TestField):
    def setUp(self):
        super(TestNotificationAction, self).setUp()
        self.field = fields.NotificationActionField()
        self.coerce_good_values = [('update', 'update')]
        self.coerce_bad_values = ['magic']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'update'", self.field.stringify('update'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'magic')


class TestUSBAddress(TestField):
    def setUp(self):
        super(TestUSBAddress, self).setUp()
        self.field = fields.Field(fields.USBAddressField())
        self.coerce_good_values = [('0:0', '0:0')]
        self.coerce_bad_values = [
            '00',
            '0:',
            '0.0',
            '-.0',
        ]
        self.to_primitive_values = self.coerce_good_values
        self.from_primitive_values = self.coerce_good_values


class TestSCSIAddress(TestField):
    def setUp(self):
        super(TestSCSIAddress, self).setUp()
        self.field = fields.Field(fields.SCSIAddressField())
        self.coerce_good_values = [('1:0:2:0', '1:0:2:0')]
        self.coerce_bad_values = [
                '1:0:2',
                '-:0:2:0',
                '1:-:2:0',
                '1:0:-:0',
                '1:0:2:-',
        ]
        self.to_primitive_values = self.coerce_good_values
        self.from_primitive_values = self.coerce_good_values


class TestIDEAddress(TestField):
    def setUp(self):
        super(TestIDEAddress, self).setUp()
        self.field = fields.Field(fields.IDEAddressField())
        self.coerce_good_values = [('0:0', '0:0')]
        self.coerce_bad_values = [
            '0:2',
            '00',
            '0',
        ]
        self.to_primitive_values = self.coerce_good_values
        self.from_primitive_values = self.coerce_good_values


class TestXenAddress(TestField):
    def setUp(self):
        super(TestXenAddress, self).setUp()
        self.field = fields.Field(fields.XenAddressField())
        self.coerce_good_values = [('000100', '000100'),
                                   ('768', '768')]
        self.coerce_bad_values = [
            '1',
            '00100',
        ]
        self.to_primitive_values = self.coerce_good_values
        self.from_primitive_values = self.coerce_good_values


class TestSecureBoot(TestField):
    def setUp(self):
        super(TestSecureBoot, self).setUp()
        self.field = fields.SecureBoot()
        self.coerce_good_values = [('required', 'required'),
                                   ('disabled', 'disabled'),
                                   ('optional', 'optional')]
        self.coerce_bad_values = ['enabled']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'required'", self.field.stringify('required'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'enabled')


class TestSchemaGeneration(test.NoDBTestCase):
    def test_address_base_get_schema(self):
        field = FakeAddressField()
        expected = {'type': ['string'], 'pattern': '[a-z]+[0-9]+',
                    'readonly': False}
        self.assertEqual(expected, field.get_schema())


class TestNotificationSource(test.NoDBTestCase):
    def test_get_source_by_binary(self):
        self.assertEqual('nova-api',
                         fields.NotificationSource.get_source_by_binary(
                             'nova-osapi_compute'))
        self.assertEqual('nova-metadata',
                         fields.NotificationSource.get_source_by_binary(
                             'nova-metadata'))
