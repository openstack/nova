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

from nova import test
from nova.tests.unit.virt.vmwareapi import fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.virt.vmwareapi import network_util
from nova.virt.vmwareapi.session import VMwareAPISession


ResultSet = collections.namedtuple('ResultSet', ['objects'])
ObjectContent = collections.namedtuple('ObjectContent', ['obj', 'propSet'])
DynamicProperty = collections.namedtuple('DynamicProperty', ['name', 'val'])


class GetNetworkWithTheNameTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GetNetworkWithTheNameTestCase, self).setUp()
        fake.reset()
        self.stub_out('nova.virt.vmwareapi.session.VMwareAPISession.vim',
                      stubs.fake_vim_prop)
        self.stub_out('nova.virt.vmwareapi.session.'
                      'VMwareAPISession.is_vim_object',
                       stubs.fake_is_vim_object)
        self._session = VMwareAPISession()

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

        def mock_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties':
                return networks
            if method == 'get_object_property':
                result = fake.DataObject()
                result.name = 'no-match'
                return result

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            res = network_util.get_network_with_the_name(self._session,
                                                        'fake_net',
                                                        'fake_cluster')
            self.assertIsNone(res)

    def _get_network_dvs_match(self, name):
        net_morefs = [vim_util.get_moref("dvportgroup-135",
                                         "DistributedVirtualPortgroup")]
        networks = self._build_cluster_networks(net_morefs)

        def mock_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties':
                return networks
            if method == 'get_object_property':
                result = fake.DataObject()
                result.name = name
                result.key = 'fake_key'
                result.distributedVirtualSwitch = 'fake_dvs'
                return result

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            res = network_util.get_network_with_the_name(self._session,
                                                        'fake_net',
                                                        'fake_cluster')
            self.assertIsNotNone(res)

    def test_get_network_dvs_exact_match(self):
        self._get_network_dvs_match('fake_net')

    def test_get_network_dvs_match(self):
        self._get_network_dvs_match('dvs_7-virtualwire-7-fake_net')

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


class GetDVSNetworkNameTestCase(test.NoDBTestCase):

    def test__get_name_from_dvs_name(self):
        vxw = 'vxw-dvs-22-virtualwire-89-sid-5008-'
        uuid = '2425c130-fd39-45a6-91d8-bf7ebe66b77c'
        cases = [('name', 'name'),
                 ('%sname' % vxw, 'name'),
                 ('%s%s' % (vxw, uuid), uuid)]
        for (dvsname, expected) in cases:
            self.assertEqual(expected,
                             network_util._get_name_from_dvs_name(dvsname))
