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

from nova import objects
from nova.objects import network_request
from nova.tests.unit.objects import test_objects


FAKE_UUID = '0C5C9AD2-F967-4E92-A7F3-24410F697440'


class _TestNetworkRequestObject(object):
    def test_basic(self):
        request = objects.NetworkRequest()
        request.network_id = '456'
        request.address = '1.2.3.4'
        request.port_id = FAKE_UUID
        self.assertFalse(request.auto_allocate)
        self.assertFalse(request.no_allocate)

    def test_load(self):
        request = objects.NetworkRequest()
        self.assertIsNone(request.port_id)
        self.assertFalse(request.auto_allocate)
        self.assertFalse(request.no_allocate)

    def test_to_tuple(self):
        request = objects.NetworkRequest(network_id='123',
                                         address='1.2.3.4',
                                         port_id=FAKE_UUID,
                                     )
        self.assertEqual(('123', '1.2.3.4', FAKE_UUID, None),
                         request.to_tuple())

    def test_from_tuples(self):
        requests = objects.NetworkRequestList.from_tuples(
            [('123', '1.2.3.4', FAKE_UUID, None)])
        self.assertEqual(1, len(requests))
        self.assertEqual('123', requests[0].network_id)
        self.assertEqual('1.2.3.4', str(requests[0].address))
        self.assertEqual(FAKE_UUID, requests[0].port_id)
        self.assertIsNone(requests[0].pci_request_id)

    def test_list_as_tuples(self):
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

    def test_auto_allocate(self):
        # no objects
        requests = objects.NetworkRequestList()
        self.assertFalse(requests.auto_allocate)
        # single object with network uuid
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=FAKE_UUID)])
        self.assertFalse(requests.auto_allocate)
        # multiple objects
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(),
                     objects.NetworkRequest()])
        self.assertFalse(requests.auto_allocate)
        # single object, 'auto' case
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=network_request.NETWORK_ID_AUTO)])
        self.assertTrue(requests.auto_allocate)

    def test_no_allocate(self):
        # no objects
        requests = objects.NetworkRequestList()
        self.assertFalse(requests.no_allocate)
        # single object with network uuid
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=FAKE_UUID)])
        self.assertFalse(requests.no_allocate)
        # multiple objects
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(),
                     objects.NetworkRequest()])
        self.assertFalse(requests.no_allocate)
        # single object, 'none' case
        requests = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=network_request.NETWORK_ID_NONE)])
        self.assertTrue(requests.no_allocate)

    def test_obj_make_compatible_pre_1_2(self):
        net_req = objects.NetworkRequest()
        net_req.tag = 'foo'
        data = lambda x: x['nova_object.data']
        primitive = data(net_req.obj_to_primitive(target_version='1.2'))
        self.assertIn('tag', primitive)
        primitive = data(net_req.obj_to_primitive(target_version='1.1'))
        self.assertNotIn('tag', primitive)


class TestNetworkRequestObject(test_objects._LocalTest,
                               _TestNetworkRequestObject):
    pass


class TestNetworkRequestRemoteObject(test_objects._RemoteTest,
                                     _TestNetworkRequestObject):
    pass
