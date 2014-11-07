#    Copyright 2014 Red Hat, Inc.
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

from nova import objects
from nova.tests.unit.objects import test_objects


FAKE_UUID = '0C5C9AD2-F967-4E92-A7F3-24410F697440'


class _TestNetworkRequestObject(object):
    def test_basic(self):
        request = objects.NetworkRequest()
        request.network_id = '456'
        request.address = '1.2.3.4'
        request.port_id = FAKE_UUID

    def test_load(self):
        request = objects.NetworkRequest()
        self.assertIsNone(request.port_id)

    def test_to_tuple_neutron(self):
        request = objects.NetworkRequest(network_id='123',
                                         address='1.2.3.4',
                                         port_id=FAKE_UUID,
                                     )
        with mock.patch('nova.utils.is_neutron', return_value=True):
            self.assertEqual(('123', '1.2.3.4', FAKE_UUID, None),
                             request.to_tuple())

    def test_to_tuple_nova(self):
        request = objects.NetworkRequest(network_id='123',
                                         address='1.2.3.4',
                                         port_id=FAKE_UUID)
        with mock.patch('nova.utils.is_neutron', return_value=False):
            self.assertEqual(('123', '1.2.3.4'),
                             request.to_tuple())

    def test_from_tuple_neutron(self):
        request = objects.NetworkRequest.from_tuple(
            ('123', '1.2.3.4', FAKE_UUID, None))
        self.assertEqual('123', request.network_id)
        self.assertEqual('1.2.3.4', str(request.address))
        self.assertEqual(FAKE_UUID, request.port_id)

    def test_from_tuple_neutron_without_pci_request_id(self):
        request = objects.NetworkRequest.from_tuple(
            ('123', '1.2.3.4', FAKE_UUID))
        self.assertEqual('123', request.network_id)
        self.assertEqual('1.2.3.4', str(request.address))
        self.assertEqual(FAKE_UUID, request.port_id)

    def test_from_tuple_nova(self):
        request = objects.NetworkRequest.from_tuple(
            ('123', '1.2.3.4'))
        self.assertEqual('123', request.network_id)
        self.assertEqual('1.2.3.4', str(request.address))
        self.assertIsNone(request.port_id)

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_list_as_tuples(self, is_neutron):
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='123'),
                     objects.NetworkRequest(network_id='456')])
        self.assertEqual(
            [('123', None, None, None), ('456', None, None, None)],
             requests.as_tuples())

    def test_is_single_unspecified(self):
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='123')])
        self.assertFalse(requests.is_single_unspecified)
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(),
                     objects.NetworkRequest()])
        self.assertFalse(requests.is_single_unspecified)
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest()])
        self.assertTrue(requests.is_single_unspecified)


class TestNetworkRequestObject(test_objects._LocalTest,
                               _TestNetworkRequestObject):
    pass


class TestNetworkRequestRemoteObject(test_objects._RemoteTest,
                                     _TestNetworkRequestObject):
    pass
