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

import iso8601
import netaddr
from oslo_versionedobjects import exception as ovo_exc
import six

from nova.network import model as network_model
from nova.objects import fields
from nova import signature_utils
from nova import test
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
    def setUp(self):
        super(TestArchitecture, self).setUp()
        self.field = fields.ArchitectureField()
        self.coerce_good_values = [('x86_64', 'x86_64'),
                                   ('amd64', 'x86_64'),
                                   ('I686', 'i686'),
                                   ('i386', 'i686')]
        self.coerce_bad_values = ['x86_99']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'aarch64'", self.field.stringify('aarch64'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'ppc42')


class TestBlockDeviceDestinationType(TestField):
    def setUp(self):
        super(TestBlockDeviceDestinationType, self).setUp()
        self.field = fields.BlockDeviceDestinationTypeField()
        self.coerce_good_values = [('local', 'local'),
                                   ('volume', 'volume')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'volume'", self.field.stringify('volume'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestBlockDeviceSourceType(TestField):
    def setUp(self):
        super(TestBlockDeviceSourceType, self).setUp()
        self.field = fields.BlockDeviceSourceTypeField()
        self.coerce_good_values = [('blank', 'blank'),
                                   ('image', 'image'),
                                   ('snapshot', 'snapshot'),
                                   ('volume', 'volume')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'image'", self.field.stringify('image'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestBlockDeviceType(TestField):
    def setUp(self):
        super(TestBlockDeviceType, self).setUp()
        self.field = fields.BlockDeviceTypeField()
        self.coerce_good_values = [('cdrom', 'cdrom'),
                                   ('disk', 'disk'),
                                   ('floppy', 'floppy'),
                                   ('fs', 'fs'),
                                   ('lun', 'lun')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'disk'", self.field.stringify('disk'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestCPUMode(TestField):
    def setUp(self):
        super(TestCPUMode, self).setUp()
        self.field = fields.CPUModeField()
        self.coerce_good_values = [('host-model', 'host-model'),
                                   ('host-passthrough', 'host-passthrough'),
                                   ('custom', 'custom')]
        self.coerce_bad_values = ['magic']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'custom'", self.field.stringify('custom'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'magic')


class TestCPUMatch(TestField):
    def setUp(self):
        super(TestCPUMatch, self).setUp()
        self.field = fields.CPUMatchField()
        self.coerce_good_values = [('exact', 'exact'),
                                   ('strict', 'strict'),
                                   ('minimum', 'minimum')]
        self.coerce_bad_values = ['best']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'exact'", self.field.stringify('exact'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'best')


class TestCPUFeaturePolicy(TestField):
    def setUp(self):
        super(TestCPUFeaturePolicy, self).setUp()
        self.field = fields.CPUFeaturePolicyField()
        self.coerce_good_values = [('force', 'force'),
                                   ('require', 'require'),
                                   ('optional', 'optional'),
                                   ('disable', 'disable'),
                                   ('forbid', 'forbid')]
        self.coerce_bad_values = ['disallow']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'forbid'", self.field.stringify('forbid'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'disallow')


class TestConfigDrivePolicy(TestField):
    def setUp(self):
        super(TestConfigDrivePolicy, self).setUp()
        self.field = fields.ConfigDrivePolicyField()
        self.coerce_good_values = [('optional', 'optional'),
                                   ('mandatory', 'mandatory')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'optional'", self.field.stringify('optional'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestCPUAllocationPolicy(TestField):
    def setUp(self):
        super(TestCPUAllocationPolicy, self).setUp()
        self.field = fields.CPUAllocationPolicyField()
        self.coerce_good_values = [('dedicated', 'dedicated'),
                                   ('shared', 'shared')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'shared'", self.field.stringify('shared'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestCPUThreadAllocationPolicy(TestField):
    def setUp(self):
        super(TestCPUThreadAllocationPolicy, self).setUp()
        self.field = fields.CPUThreadAllocationPolicyField()
        self.coerce_good_values = [('prefer', 'prefer'),
                                   ('isolate', 'isolate'),
                                   ('require', 'require')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'prefer'", self.field.stringify('prefer'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestPciDeviceType(TestField):
    def setUp(self):
        super(TestPciDeviceType, self).setUp()
        self.field = fields.PciDeviceTypeField()
        self.coerce_good_values = [('type-PCI', 'type-PCI'),
                                   ('type-PF', 'type-PF'),
                                   ('type-VF', 'type-VF')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'type-VF'", self.field.stringify('type-VF'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestDiskBus(TestField):
    def setUp(self):
        super(TestDiskBus, self).setUp()
        self.field = fields.DiskBusField()
        self.coerce_good_values = [('fdc', 'fdc'),
                                   ('ide', 'ide'),
                                   ('sata', 'sata'),
                                   ('scsi', 'scsi'),
                                   ('usb', 'usb'),
                                   ('virtio', 'virtio'),
                                   ('xen', 'xen'),
                                   ('lxc', 'lxc'),
                                   ('uml', 'uml')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'ide'", self.field.stringify('ide'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestHVType(TestField):
    def setUp(self):
        super(TestHVType, self).setUp()
        self.field = fields.HVTypeField()
        self.coerce_good_values = [('baremetal', 'baremetal'),
                                   ('bhyve', 'bhyve'),
                                   ('fake', 'fake'),
                                   ('kvm', 'kvm'),
                                   ('xapi', 'xen')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'xen'", self.field.stringify('xen'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestImageSignatureTypes(TestField):
    # Ensure that the object definition is updated
    # in step with the signature_utils module
    def setUp(self):
        super(TestImageSignatureTypes, self).setUp()
        self.hash_field = fields.ImageSignatureHashType()
        self.key_type_field = fields.ImageSignatureKeyType()

    def test_hashes(self):
        for hash_name in list(signature_utils.HASH_METHODS.keys()):
            self.assertIn(hash_name, self.hash_field.hashes)

    def test_key_types(self):
        key_type_dict = signature_utils.SignatureKeyType._REGISTERED_TYPES
        key_types = list(key_type_dict.keys())
        for key_type in key_types:
            self.assertIn(key_type, self.key_type_field.key_types)


class TestOSType(TestField):
    def setUp(self):
        super(TestOSType, self).setUp()
        self.field = fields.OSTypeField()
        self.coerce_good_values = [('linux', 'linux'),
                                   ('windows', 'windows'),
                                   ('WINDOWS', 'windows')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'linux'", self.field.stringify('linux'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestRNGModel(TestField):
    def setUp(self):
        super(TestRNGModel, self).setUp()
        self.field = fields.RNGModelField()
        self.coerce_good_values = [('virtio', 'virtio'), ]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'virtio'", self.field.stringify('virtio'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestSCSIModel(TestField):
    def setUp(self):
        super(TestSCSIModel, self).setUp()
        self.field = fields.SCSIModelField()
        self.coerce_good_values = [('buslogic', 'buslogic'),
                                   ('ibmvscsi', 'ibmvscsi'),
                                   ('lsilogic', 'lsilogic'),
                                   ('lsisas1068', 'lsisas1068'),
                                   ('lsisas1078', 'lsisas1078'),
                                   ('virtio-scsi', 'virtio-scsi'),
                                   ('vmpvscsi', 'vmpvscsi'),
                                   ('lsilogicsas', 'lsisas1068'),
                                   ('paravirtual', 'vmpvscsi')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'vmpvscsi'", self.field.stringify('vmpvscsi'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestVideoModel(TestField):
    def setUp(self):
        super(TestVideoModel, self).setUp()
        self.field = fields.VideoModelField()
        self.coerce_good_values = [('cirrus', 'cirrus'),
                                   ('qxl', 'qxl'),
                                   ('vga', 'vga'),
                                   ('vmvga', 'vmvga'),
                                   ('xen', 'xen')]

        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'cirrus'", self.field.stringify('cirrus'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestVIFModel(TestField):
    def setUp(self):
        super(TestVIFModel, self).setUp()
        self.field = fields.VIFModelField()
        self.coerce_good_values = [('virtio', 'virtio'),
                                   ('ne2k_pci', 'ne2k_pci'),
                                   ('pcnet', 'pcnet'),
                                   ('rtl8139', 'rtl8139'),
                                   ('e1000', 'e1000'),
                                   ('e1000e', 'e1000e'),
                                   ('netfront', 'netfront'),
                                   ('spapr-vlan', 'spapr-vlan'),
                                   ('VirtualE1000', 'e1000'),
                                   ('VirtualE1000e', 'e1000e'),
                                   ('VirtualPCNet32', 'pcnet'),
                                   ('VirtualSriovEthernetCard', 'sriov'),
                                   ('VirtualVmxnet', 'vmxnet'),
                                   ('VirtualVmxnet3', 'vmxnet3'),
                                  ]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'e1000'", self.field.stringify('e1000'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestVMMode(TestField):
    def setUp(self):
        super(TestVMMode, self).setUp()
        self.field = fields.VMModeField()
        self.coerce_good_values = [('hvm', 'hvm'),
                                   ('xen', 'xen'),
                                   ('uml', 'uml'),
                                   ('exe', 'exe'),
                                   ('pv', 'xen'),
                                   ('hv', 'hvm'),
                                   ('baremetal', 'hvm')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'hvm'", self.field.stringify('hvm'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestWatchdogAction(TestField):
    def setUp(self):
        super(TestWatchdogAction, self).setUp()
        self.field = fields.WatchdogActionField()
        self.coerce_good_values = [('none', 'none'),
                                   ('pause', 'pause'),
                                   ('poweroff', 'poweroff'),
                                   ('reset', 'reset')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'reset'", self.field.stringify('reset'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


class TestMonitorMetricType(TestField):
    def setUp(self):
        super(TestMonitorMetricType, self).setUp()
        self.field = fields.MonitorMetricTypeField()
        self.coerce_good_values = [('cpu.frequency', 'cpu.frequency'),
                                   ('cpu.user.time', 'cpu.user.time'),
                                   ('cpu.kernel.time', 'cpu.kernel.time'),
                                   ('cpu.idle.time', 'cpu.idle.time'),
                                   ('cpu.iowait.time', 'cpu.iowait.time'),
                                   ('cpu.user.percent', 'cpu.user.percent'),
                                   ('cpu.kernel.percent',
                                       'cpu.kernel.percent'),
                                   ('cpu.idle.percent', 'cpu.idle.percent'),
                                   ('cpu.iowait.percent',
                                       'cpu.iowait.percent'),
                                   ('cpu.percent', 'cpu.percent')]
        self.coerce_bad_values = ['cpu.typo']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'cpu.frequency'",
                         self.field.stringify('cpu.frequency'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'cpufrequency')


class TestDiskFormat(TestField):
    def setUp(self):
        super(TestDiskFormat, self).setUp()
        self.field = fields.DiskFormatField()
        self.coerce_good_values = [('qcow2', 'qcow2'),
                                   ('raw', 'raw'),
                                   ('lvm', 'lvm'),
                                   ('rbd', 'rbd'),
                                   ('ploop', 'ploop'),
                                   ('vhd', 'vhd'),
                                   ('vmdk', 'vmdk'),
                                   ('vdi', 'vdi'),
                                   ('iso', 'iso')]

        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'rbd'", self.field.stringify('rbd'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'acme')


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
        self.field = fields.Field(fields.NonNegativeInteger())
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
        self.field = fields.Field(fields.NonNegativeFloat())
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
        self.dt = datetime.datetime(1955, 11, 5, tzinfo=iso8601.iso8601.Utc())
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
                                  tzinfo=iso8601.iso8601.Utc())))


class TestIPAddress(TestField):
    def setUp(self):
        super(TestIPAddress, self).setUp()
        self.field = fields.IPAddressField()
        self.coerce_good_values = [('1.2.3.4', netaddr.IPAddress('1.2.3.4')),
                                   ('::1', netaddr.IPAddress('::1')),
                                   (netaddr.IPAddress('::1'),
                                    netaddr.IPAddress('::1'))]
        self.coerce_bad_values = ['1-2', 'foo']
        self.to_primitive_values = [(netaddr.IPAddress('1.2.3.4'), '1.2.3.4'),
                                    (netaddr.IPAddress('::1'), '::1')]
        self.from_primitive_values = [('1.2.3.4',
                                       netaddr.IPAddress('1.2.3.4')),
                                      ('::1',
                                       netaddr.IPAddress('::1'))]


class TestIPAddressV4(TestField):
    def setUp(self):
        super(TestIPAddressV4, self).setUp()
        self.field = fields.IPV4AddressField()
        self.coerce_good_values = [('1.2.3.4', netaddr.IPAddress('1.2.3.4')),
                                   (netaddr.IPAddress('1.2.3.4'),
                                    netaddr.IPAddress('1.2.3.4'))]
        self.coerce_bad_values = ['1-2', 'foo', '::1']
        self.to_primitive_values = [(netaddr.IPAddress('1.2.3.4'), '1.2.3.4')]
        self.from_primitive_values = [('1.2.3.4',
                                       netaddr.IPAddress('1.2.3.4'))]


class TestIPAddressV6(TestField):
    def setUp(self):
        super(TestIPAddressV6, self).setUp()
        self.field = fields.IPV6AddressField()
        self.coerce_good_values = [('::1', netaddr.IPAddress('::1')),
                                   (netaddr.IPAddress('::1'),
                                    netaddr.IPAddress('::1'))]
        self.coerce_bad_values = ['1.2', 'foo', '1.2.3.4']
        self.to_primitive_values = [(netaddr.IPAddress('::1'), '::1')]
        self.from_primitive_values = [('::1',
                                       netaddr.IPAddress('::1'))]


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


class TestIPNetwork(TestField):
    def setUp(self):
        super(TestIPNetwork, self).setUp()
        self.field = fields.Field(fields.IPNetwork())
        good = ['192.168.1.0/24', '0.0.0.0/0', '::1/128', '::1/64', '::1/0']
        self.coerce_good_values = [(x, netaddr.IPNetwork(x)) for x in good]
        self.coerce_bad_values = ['192.168.0.0/f', '192.168.0.0/foo',
                                  '::1/129', '192.168.0.0/-1']
        self.to_primitive_values = [(netaddr.IPNetwork(x), x)
                                    for x in good]
        self.from_primitive_values = [(x, netaddr.IPNetwork(x))
                                      for x in good]


class TestIPV4Network(TestField):
    def setUp(self):
        super(TestIPV4Network, self).setUp()
        self.field = fields.Field(fields.IPV4Network())
        good = ['192.168.1.0/24', '0.0.0.0/0']
        self.coerce_good_values = [(x, netaddr.IPNetwork(x)) for x in good]
        self.coerce_bad_values = ['192.168.0.0/f', '192.168.0.0/foo',
                                  '::1/129', '192.168.0.0/-1']
        self.to_primitive_values = [(netaddr.IPNetwork(x), x)
                                    for x in good]
        self.from_primitive_values = [(x, netaddr.IPNetwork(x))
                                      for x in good]


class TestIPV6Network(TestField):
    def setUp(self):
        super(TestIPV6Network, self).setUp()
        self.field = fields.Field(fields.IPV6Network())
        good = ['::1/128', '::1/64', '::1/0']
        self.coerce_good_values = [(x, netaddr.IPNetwork(x)) for x in good]
        self.coerce_bad_values = ['192.168.0.0/f', '192.168.0.0/foo',
                                  '::1/129', '192.168.0.0/-1']
        self.to_primitive_values = [(netaddr.IPNetwork(x), x)
                                    for x in good]
        self.from_primitive_values = [(x, netaddr.IPNetwork(x))
                                      for x in good]


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
