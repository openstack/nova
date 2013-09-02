# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 Canonical Corp.
# All Rights Reserved.
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
import re

from nova import exception
from nova.openstack.common.gettextutils import _
from nova import test
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import vm_util


class fake_session(object):
    def __init__(self, ret=None):
        self.ret = ret

    def _call_method(self, *args):
        return self.ret


class VMwareVMUtilTestCase(test.TestCase):
    def setUp(self):
        super(VMwareVMUtilTestCase, self).setUp()
        fake.reset()

    def tearDown(self):
        super(VMwareVMUtilTestCase, self).tearDown()
        fake.reset()

    def test_get_datastore_ref_and_name(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore())
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects))

        self.assertEquals(result[1], "fake-ds")
        self.assertEquals(result[2], 1024 * 1024 * 1024 * 1024)
        self.assertEquals(result[3], 1024 * 1024 * 500 * 1024)

    def test_get_datastore_ref_and_name_with_regex(self):
        # Test with a regex that matches with a datastore
        datastore_valid_regex = re.compile("^openstack.*\d$")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects), None, None, datastore_valid_regex)
        self.assertEquals("openstack-ds0", result[1])

    def test_get_datastore_ref_and_name_with_list(self):
        # Test with a regex containing whitelist of datastores
        datastore_valid_regex = re.compile("(openstack-ds0|openstack-ds2)")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("openstack-ds1"))
        fake_objects.add_object(fake.Datastore("openstack-ds2"))
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects), None, None, datastore_valid_regex)
        self.assertNotEquals("openstack-ds1", result[1])

    def test_get_datastore_ref_and_name_with_regex_error(self):
        # Test with a regex that has no match
        # Checks if code raises DatastoreNotFound with a specific message
        datastore_invalid_regex = re.compile("unknown-ds")
        exp_message = (_("Datastore regex %s did not match any datastores")
                       % datastore_invalid_regex.pattern)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))
        # assertRaisesRegExp would have been a good choice instead of
        # try/catch block, but it's available only from Py 2.7.
        try:
            vm_util.get_datastore_ref_and_name(
                fake_session(fake_objects), None, None,
                datastore_invalid_regex)
        except exception.DatastoreNotFound as e:
            self.assertEquals(exp_message, e.args[0])
        else:
            self.fail("DatastoreNotFound Exception was not raised with "
                      "message: %s" % exp_message)

    def test_get_datastore_ref_and_name_without_datastore(self):

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(), host="fake-host")

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(), cluster="fake-cluster")

    def test_get_host_ref_from_id(self):
        fake_host_name = "ha-host"
        fake_host_sys = fake.HostSystem(fake_host_name)
        fake_host_id = fake_host_sys.obj.value
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake_host_sys)
        ref = vm_util.get_host_ref_from_id(
            fake_session(fake_objects), fake_host_id, ['name'])

        self.assertIsInstance(ref, fake.HostSystem)
        self.assertEqual(fake_host_id, ref.obj.value)

        host_name = vm_util.get_host_name_from_host_ref(ref)

        self.assertEquals(fake_host_name, host_name)

    def test_get_host_name_for_vm(self):
        fake_host = fake.HostSystem()
        fake_host_id = fake_host.obj.value
        fake_vm = fake.VirtualMachine(name='vm-123',
                                      runtime_host=fake_host.obj)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake_vm)

        vm_ref = vm_util.get_vm_ref_from_name(
                fake_session(fake_objects), 'vm-123')

        self.assertIsNotNone(vm_ref)

        host_id = vm_util.get_host_id_from_vm_ref(
            fake_session(fake_objects), vm_ref)

        self.assertEqual(fake_host_id, host_id)

    def test_property_from_property_set(self):

        ObjectContent = collections.namedtuple('ObjectContent', ['propSet'])
        DynamicProperty = collections.namedtuple('Property', ['name', 'val'])
        MoRef = collections.namedtuple('Val', ['value'])

        good_objects = fake.FakeRetrieveResult()
        results_good = [
            ObjectContent(propSet=[
                DynamicProperty(name='name', val=MoRef(value='vm-123'))]),
            ObjectContent(propSet=[
                DynamicProperty(name='foo', val=MoRef(value='bar1')),
                DynamicProperty(
                    name='runtime.host', val=MoRef(value='host-123')),
                DynamicProperty(name='foo', val=MoRef(value='bar2')),
            ]),
            ObjectContent(propSet=[
                DynamicProperty(
                    name='something', val=MoRef(value='thing'))]), ]
        for result in results_good:
            good_objects.add_object(result)

        bad_objects = fake.FakeRetrieveResult()
        results_bad = [
            ObjectContent(propSet=[
                DynamicProperty(name='name', val=MoRef(value='vm-123'))]),
            ObjectContent(propSet=[
                DynamicProperty(name='foo', val='bar1'),
                DynamicProperty(name='foo', val='bar2'), ]),
            ObjectContent(propSet=[
                DynamicProperty(
                    name='something', val=MoRef(value='thing'))]), ]
        for result in results_bad:
            bad_objects.add_object(result)

        prop = vm_util.property_from_property_set(
                    'runtime.host', good_objects)
        self.assertIsNotNone(prop)
        value = prop.val.value
        self.assertEqual('host-123', value)

        prop2 = vm_util.property_from_property_set(
                    'runtime.host', bad_objects)
        self.assertIsNone(prop2)

        prop3 = vm_util.property_from_property_set('foo', good_objects)
        self.assertIsNotNone(prop3)
        val3 = prop3.val.value
        self.assertEqual('bar1', val3)

        prop4 = vm_util.property_from_property_set('foo', bad_objects)
        self.assertIsNotNone(prop4)
        self.assertEqual('bar1', prop4.val)

    def test_get_datastore_ref_and_name_inaccessible_ds(self):
        data_store = fake.Datastore()
        data_store.set("summary.accessible", False)

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(data_store)

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(fake_objects))

    def test_get_cdrom_attach_config_spec(self):

        result = vm_util.get_cdrom_attach_config_spec(fake.FakeFactory(),
                                             fake.Datastore(),
                                             "/tmp/foo.iso",
                                             0)
        expected = """{
    'deviceChange': [
        {
            'device': {
                'connectable': {
                    'allowGuestControl': False,
                    'startConnected': True,
                    'connected': True,
                    'obj_name': 'ns0: VirtualDeviceConnectInfo'
                },
                'backing': {
                    'datastore': {
                        "summary.type": "VMFS",
                        "summary.freeSpace": 536870912000,
                        "summary.capacity": 1099511627776,
                        "summary.accessible":true,
                        "summary.name": "fake-ds"
                    },
                    'fileName': '/tmp/foo.iso',
                    'obj_name': 'ns0: VirtualCdromIsoBackingInfo'
                },
                'controllerKey': 200,
                'unitNumber': 0,
                'key': -1,
                'obj_name': 'ns0: VirtualCdrom'
            },
            'operation': 'add',
            'obj_name': 'ns0: VirtualDeviceConfigSpec'
        }
    ],
    'obj_name': 'ns0: VirtualMachineConfigSpec'
}
"""

        expected = re.sub(r'\s+', '', expected)
        result = re.sub(r'\s+', '', repr(result))
        self.assertEqual(expected, result)
