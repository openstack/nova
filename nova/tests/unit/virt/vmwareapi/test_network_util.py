# Copyright (c) 2014 VMware, Inc.
#
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

import mock
from oslo_vmware import vim_util

from nova import exception
from nova import test
from nova.tests.unit.virt.vmwareapi import fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import network_util
from nova.virt.vmwareapi import vm_util


ResultSet = collections.namedtuple('ResultSet', ['objects'])
ObjectContent = collections.namedtuple('ObjectContent', ['obj', 'propSet'])
DynamicProperty = collections.namedtuple('DynamicProperty', ['name', 'val'])


class GetNetworkWithTheNameTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GetNetworkWithTheNameTestCase, self).setUp()
        fake.reset()
        self.stub_out('nova.virt.vmwareapi.driver.VMwareAPISession.vim',
                      stubs.fake_vim_prop)
        self.stub_out('nova.virt.vmwareapi.driver.'
                      'VMwareAPISession.is_vim_object',
                       stubs.fake_is_vim_object)
        self._session = driver.VMwareAPISession()

    def _build_cluster_networks(self, networks):
        """Returns a set of results for a cluster network lookup.

        This is an example:
        (ObjectContent){
           obj =
              (obj){
                 value = "domain-c7"
                 _type = "ClusterComputeResource"
              }
           propSet[] =
              (DynamicProperty){
                 name = "network"
                 val =
                    (ArrayOfManagedObjectReference){
                       ManagedObjectReference[] =
                          (ManagedObjectReference){
                             value = "network-54"
                             _type = "Network"
                          },
                          (ManagedObjectReference){
                             value = "dvportgroup-14"
                             _type = "DistributedVirtualPortgroup"
                          },
                    }
              },
        }]
        """

        objects = []
        obj = ObjectContent(obj=vim_util.get_moref("domain-c7",
                                                   "ClusterComputeResource"),
                            propSet=[])
        value = fake.DataObject()
        value.ManagedObjectReference = []
        for network in networks:
            value.ManagedObjectReference.append(network)

        obj.propSet.append(
                    DynamicProperty(name='network',
                                    val=value))
        objects.append(obj)
        return ResultSet(objects=objects)

    def test_get_network_no_match(self):
        net_morefs = [vim_util.get_moref("dvportgroup-135",
                                         "DistributedVirtualPortgroup"),
                      vim_util.get_moref("dvportgroup-136",
                                         "DistributedVirtualPortgroup")]
        networks = self._build_cluster_networks(net_morefs)
        self._continue_retrieval_called = False

        def mock_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties':
                return networks
            if method == 'get_object_property':
                result = fake.DataObject()
                result.name = 'no-match'
                return result
            if method == 'continue_retrieval':
                self._continue_retrieval_called = True

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            res = network_util.get_network_with_the_name(self._session,
                                                        'fake_net',
                                                        'fake_cluster')
            self.assertTrue(self._continue_retrieval_called)
            self.assertIsNone(res)

    def _get_network_dvs_match(self, name, token=False):
        net_morefs = [vim_util.get_moref("dvportgroup-135",
                                         "DistributedVirtualPortgroup")]
        networks = self._build_cluster_networks(net_morefs)

        def mock_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties':
                return networks
            if method == 'get_object_property':
                result = fake.DataObject()
                if not token or self._continue_retrieval_called:
                    result.name = name
                else:
                    result.name = 'fake_name'
                result.key = 'fake_key'
                result.distributedVirtualSwitch = 'fake_dvs'
                return result
            if method == 'continue_retrieval':
                if token:
                    self._continue_retrieval_called = True
                    return networks
            if method == 'cancel_retrieval':
                self._cancel_retrieval_called = True

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            res = network_util.get_network_with_the_name(self._session,
                                                        'fake_net',
                                                        'fake_cluster')
            self.assertIsNotNone(res)

    def test_get_network_dvs_exact_match(self):
        self._cancel_retrieval_called = False
        self._get_network_dvs_match('fake_net')
        self.assertTrue(self._cancel_retrieval_called)

    def test_get_network_dvs_match(self):
        self._cancel_retrieval_called = False
        self._get_network_dvs_match('dvs_7-virtualwire-7-fake_net')
        self.assertTrue(self._cancel_retrieval_called)

    def test_get_network_dvs_match_with_token(self):
        self._continue_retrieval_called = False
        self._cancel_retrieval_called = False
        self._get_network_dvs_match('dvs_7-virtualwire-7-fake_net',
                                    token=True)
        self.assertTrue(self._continue_retrieval_called)
        self.assertTrue(self._cancel_retrieval_called)

    def test_get_network_network_match(self):
        net_morefs = [vim_util.get_moref("network-54", "Network")]
        networks = self._build_cluster_networks(net_morefs)

        def mock_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties':
                return networks
            if method == 'get_object_property':
                return 'fake_net'

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            res = network_util.get_network_with_the_name(self._session,
                                                        'fake_net',
                                                        'fake_cluster')
            self.assertIsNotNone(res)


class GetVlanIdAndVswitchForPortgroupTestCase(test.NoDBTestCase):

    @mock.patch.object(vm_util, 'get_host_ref')
    def test_no_port_groups(self, mock_get_host_ref):
        session = mock.Mock()
        session._call_method.return_value = None
        self.assertRaises(
            exception.NovaException,
            network_util.get_vlanid_and_vswitch_for_portgroup,
            session,
            'port_group_name',
            'fake_cluster'
        )

    @mock.patch.object(vm_util, 'get_host_ref')
    def test_valid_port_group(self, mock_get_host_ref):
        session = mock.Mock()
        session._call_method.return_value = self._fake_port_groups()
        vlanid, vswitch = network_util.get_vlanid_and_vswitch_for_portgroup(
            session,
            'port_group_name',
            'fake_cluster'
        )
        self.assertEqual(vlanid, 100)
        self.assertEqual(vswitch, 'vswitch_name')

    @mock.patch.object(vm_util, 'get_host_ref')
    def test_unknown_port_group(self, mock_get_host_ref):
        session = mock.Mock()
        session._call_method.return_value = self._fake_port_groups()
        vlanid, vswitch = network_util.get_vlanid_and_vswitch_for_portgroup(
            session,
            'unknown_port_group',
            'fake_cluster'
        )
        self.assertIsNone(vlanid)
        self.assertIsNone(vswitch)

    def _fake_port_groups(self):
        port_group_spec = fake.DataObject()
        port_group_spec.name = 'port_group_name'
        port_group_spec.vlanId = 100
        port_group_spec.vswitchName = 'vswitch_name'

        port_group = fake.DataObject()
        port_group.vswitch = 'vswitch_name'
        port_group.spec = port_group_spec

        response = fake.DataObject()
        response.HostPortGroup = [port_group]
        return response
