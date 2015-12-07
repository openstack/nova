# Copyright 2013 OpenStack Foundation
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

import mock

from nova import exception
from nova.network import model
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi import network_utils
from nova.virt.xenapi import vif

fake_vif = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': '123456789123',
    'address': '00:00:00:00:00:00',
    'network_id': 123,
    'instance_uuid': 'fake-uuid',
    'uuid': 'fake-uuid-2',
}


def fake_call_xenapi(method, *args):
    if method == "VM.get_VIFs":
        return ["fake_vif_ref", "fake_vif_ref_A2"]
    if method == "VIF.get_record":
        if args[0] == "fake_vif_ref":
            return {'uuid': fake_vif['uuid'],
                    'MAC': fake_vif['address'],
                    'network': 'fake_network',
                    'other_config': {'nicira-iface-id': fake_vif['id']}
                    }
        else:
            raise exception.Exception("Failed get vif record")
    if method == "VIF.unplug":
        return
    if method == "VIF.destroy":
        if args[0] == "fake_vif_ref":
            return
        else:
            raise exception.Exception("unplug vif failed")
    if method == "VIF.create":
        if args[0] == "fake_vif_rec":
            return "fake_vif_ref"
        else:
            raise exception.Exception("VIF existed")
    return "Unexpected call_xenapi: %s.%s" % (method, args)


class XenVIFDriverTestBase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(XenVIFDriverTestBase, self).setUp()
        self._session = mock.Mock()
        self._session.call_xenapi.side_effect = fake_call_xenapi


class XenVIFDriverTestCase(XenVIFDriverTestBase):
    def setUp(self):
        super(XenVIFDriverTestCase, self).setUp()
        self.base_driver = vif.XenVIFDriver(self._session)

    def test_get_vif_ref(self):
        vm_ref = "fake_vm_ref"
        vif_ref = 'fake_vif_ref'
        ret_vif_ref = self.base_driver._get_vif_ref(fake_vif, vm_ref)
        self.assertEqual(vif_ref, ret_vif_ref)

        expected = [mock.call('VM.get_VIFs', vm_ref),
                    mock.call('VIF.get_record', vif_ref)]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)

    def test_get_vif_ref_none_and_exception(self):
        vm_ref = "fake_vm_ref"
        vif = {'address': "no_match_vif_address"}
        ret_vif_ref = self.base_driver._get_vif_ref(vif, vm_ref)
        self.assertIsNone(ret_vif_ref)

        expected = [mock.call('VM.get_VIFs', vm_ref),
                    mock.call('VIF.get_record', 'fake_vif_ref'),
                    mock.call('VIF.get_record', 'fake_vif_ref_A2')]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)

    def test_create_vif(self):
        vif_rec = "fake_vif_rec"
        vm_ref = "fake_vm_ref"
        ret_vif_ref = self.base_driver._create_vif(fake_vif, vif_rec, vm_ref)
        self.assertEqual("fake_vif_ref", ret_vif_ref)

        expected = [mock.call('VIF.create', vif_rec)]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)

    def test_create_vif_exception(self):
        self.assertRaises(exception.NovaException,
                          self.base_driver._create_vif,
                          "fake_vif", "missing_vif_rec", "fake_vm_ref")

    @mock.patch.object(vif.XenVIFDriver, '_get_vif_ref',
                       return_value='fake_vif_ref')
    def test_unplug(self, mock_get_vif_ref):
        instance = {'name': "fake_instance"}
        vm_ref = "fake_vm_ref"
        self.base_driver.unplug(instance, fake_vif, vm_ref)
        expected = [mock.call('VIF.destroy', 'fake_vif_ref')]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)

    @mock.patch.object(vif.XenVIFDriver, '_get_vif_ref',
                       return_value='missing_vif_ref')
    def test_unplug_exception(self, mock_get_vif_ref):
        instance = "fake_instance"
        vm_ref = "fake_vm_ref"
        self.assertRaises(exception.NovaException,
                          self.base_driver.unplug,
                          instance, fake_vif, vm_ref)


class XenAPIBridgeDriverTestCase(XenVIFDriverTestBase, object):
    def setUp(self):
        super(XenAPIBridgeDriverTestCase, self).setUp()
        self.bridge_driver = vif.XenAPIBridgeDriver(self._session)

    @mock.patch.object(vif.XenAPIBridgeDriver, '_ensure_vlan_bridge',
                       return_value='fake_network_ref')
    @mock.patch.object(vif.XenVIFDriver, '_create_vif',
                       return_value='fake_vif_ref')
    def test_plug_create_vlan(self, mock_create_vif, mock_ensure_vlan_bridge):
        instance = {'name': "fake_instance_name"}
        network = model.Network()
        network._set_meta({'should_create_vlan': True})
        vif = model.VIF()
        vif._set_meta({'rxtx_cap': 1})
        vif['network'] = network
        vif['address'] = "fake_address"
        vm_ref = "fake_vm_ref"
        device = 1
        ret_vif_ref = self.bridge_driver.plug(instance, vif, vm_ref, device)
        self.assertEqual('fake_vif_ref', ret_vif_ref)

    @mock.patch.object(vif.XenVIFDriver, '_get_vif_ref',
                       return_value='fake_vif_ref')
    def test_unplug(self, mock_get_vif_ref):
        instance = {'name': "fake_instance"}
        vm_ref = "fake_vm_ref"
        self.bridge_driver.unplug(instance, fake_vif, vm_ref)

        expected = [mock.call('VIF.destroy', 'fake_vif_ref')]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)


class XenAPIOpenVswitchDriverTestCase(XenVIFDriverTestBase):
    def setUp(self):
        super(XenAPIOpenVswitchDriverTestCase, self).setUp()
        self.ovs_driver = vif.XenAPIOpenVswitchDriver(self._session)

    @mock.patch.object(network_utils, 'find_network_with_bridge',
                       return_value='fake_network_ref')
    @mock.patch.object(vif.XenVIFDriver, '_create_vif',
                       return_value='fake_vif_ref')
    @mock.patch.object(vif.XenVIFDriver, '_get_vif_ref', return_value=None)
    def test_plug(self, mock_get_vif_ref, mock_create_vif,
                  mock_find_network_with_bridge):
        instance = {'name': "fake_instance_name"}
        vm_ref = "fake_vm_ref"
        device = 1
        ret_vif_ref = self.ovs_driver.plug(instance, fake_vif, vm_ref, device)
        self.assertEqual('fake_vif_ref', ret_vif_ref)

    @mock.patch.object(vif.XenVIFDriver, '_get_vif_ref',
                       return_value='fake_vif_ref')
    def test_unplug(self, mock_get_vif_ref):
        instance = {'name': "fake_instance"}
        vm_ref = "fake_vm_ref"
        self.ovs_driver.unplug(instance, fake_vif, vm_ref)

        expected = [mock.call('VIF.destroy', 'fake_vif_ref')]
        self.assertEqual(expected, self._session.call_xenapi.call_args_list)
