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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_versionedobjects import base as ovo_base

from nova import objects
from nova.objects import fields
from nova.tests.unit.objects import test_objects


FAKE_UUID = '79a53d6b-0893-4838-a971-15f4f382e7c2'
FAKE_REQUEST_UUID = '69b53d6b-0793-4839-c981-f5c4f382e7d2'

# NOTE(danms): Yes, these are the same right now, but going forward,
# we have changes to make which will be reflected in the format
# in instance_extra, but not in system_metadata.
fake_pci_requests = [
    {'count': 2,
     'spec': [{'vendor_id': '8086',
               'device_id': '1502'}],
     'alias_name': 'alias_1',
     'is_new': False,
     'numa_policy': 'preferred',
     'request_id': FAKE_REQUEST_UUID},
    {'count': 2,
     'spec': [{'vendor_id': '6502',
               'device_id': '07B5'}],
     'alias_name': 'alias_2',
     'is_new': True,
     'numa_policy': 'preferred',
     'request_id': FAKE_REQUEST_UUID,
     'requester_id': uuids.requester_id},
 ]

fake_legacy_pci_requests = [
    {'count': 2,
     'spec': [{'vendor_id': '8086',
                'device_id': '1502'}],
     'alias_name': 'alias_1'},
    {'count': 1,
     'spec': [{'vendor_id': '6502',
               'device_id': '07B5'}],
     'alias_name': 'alias_2'},
 ]


class _TestInstancePCIRequests(object):
    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = {
            'instance_uuid': FAKE_UUID,
            'pci_requests': jsonutils.dumps(fake_pci_requests),
        }
        requests = objects.InstancePCIRequests.get_by_instance_uuid(
            self.context, FAKE_UUID)
        self.assertEqual(2, len(requests.requests))
        for index, request in enumerate(requests.requests):
            self.assertEqual(fake_pci_requests[index]['alias_name'],
                             request.alias_name)
            self.assertEqual(fake_pci_requests[index]['count'],
                             request.count)
            self.assertEqual(fake_pci_requests[index]['spec'],
                             [dict(x.items()) for x in request.spec])
            self.assertEqual(fake_pci_requests[index]['numa_policy'],
                             request.numa_policy)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    def test_get_by_instance_current(self, mock_get):
        instance = objects.Instance(uuid=uuids.instance,
                                    system_metadata={})
        objects.InstancePCIRequests.get_by_instance(self.context,
                                                    instance)
        mock_get.assert_called_once_with(self.context, uuids.instance)

    def test_get_by_instance_legacy(self):
        fakesysmeta = {
            'pci_requests': jsonutils.dumps([fake_legacy_pci_requests[0]]),
            'new_pci_requests': jsonutils.dumps([fake_legacy_pci_requests[1]]),
        }
        instance = objects.Instance(uuid=uuids.instance,
                                    system_metadata=fakesysmeta)
        requests = objects.InstancePCIRequests.get_by_instance(self.context,
                                                               instance)
        self.assertEqual(2, len(requests.requests))
        self.assertEqual('alias_1', requests.requests[0].alias_name)
        self.assertFalse(requests.requests[0].is_new)
        self.assertEqual('alias_2', requests.requests[1].alias_name)
        self.assertTrue(requests.requests[1].is_new)

    def test_obj_from_db(self):
        req = objects.InstancePCIRequests.obj_from_db(None, FAKE_UUID, None)
        self.assertEqual(FAKE_UUID, req.instance_uuid)
        self.assertEqual(0, len(req.requests))
        db_req = jsonutils.dumps(fake_pci_requests)
        req = objects.InstancePCIRequests.obj_from_db(None, FAKE_UUID, db_req)
        self.assertEqual(FAKE_UUID, req.instance_uuid)
        self.assertEqual(2, len(req.requests))
        self.assertEqual('alias_1', req.requests[0].alias_name)
        self.assertEqual('preferred', req.requests[0].numa_policy)
        self.assertIsNone(req.requests[0].requester_id)
        self.assertEqual(uuids.requester_id, req.requests[1].requester_id)

    def test_from_request_spec_instance_props(self):
        requests = objects.InstancePCIRequests(
            requests=[objects.InstancePCIRequest(count=1,
                                                 request_id=FAKE_UUID,
                                                 spec=[{'vendor_id': '8086',
                                                        'device_id': '1502'}])
                      ],
            instance_uuid=FAKE_UUID)
        result = jsonutils.to_primitive(requests)
        result = objects.InstancePCIRequests.from_request_spec_instance_props(
                                                                        result)
        self.assertEqual(1, len(result.requests))
        self.assertEqual(1, result.requests[0].count)
        self.assertEqual(FAKE_UUID, result.requests[0].request_id)
        self.assertEqual([{'vendor_id': '8086', 'device_id': '1502'}],
                          result.requests[0].spec)

    def test_obj_make_compatible_pre_1_2(self):
        topo_obj = objects.InstancePCIRequest(
            count=1,
            spec=[{'vendor_id': '8086', 'device_id': '1502'}],
            request_id=uuids.pci_request_id,
            numa_policy=fields.PCINUMAAffinityPolicy.PREFERRED)
        versions = ovo_base.obj_tree_get_versions('InstancePCIRequest')
        primitive = topo_obj.obj_to_primitive(target_version='1.1',
                                              version_manifest=versions)

        self.assertNotIn('numa_policy', primitive['nova_object.data'])
        self.assertIn('request_id', primitive['nova_object.data'])

    def test_obj_make_compatible_pre_1_1(self):
        topo_obj = objects.InstancePCIRequest(
            count=1,
            spec=[{'vendor_id': '8086', 'device_id': '1502'}],
            request_id=uuids.pci_request_id)
        versions = ovo_base.obj_tree_get_versions('InstancePCIRequest')
        primitive = topo_obj.obj_to_primitive(target_version='1.0',
                                              version_manifest=versions)

        self.assertNotIn('request_id', primitive['nova_object.data'])

    def test_obj_make_compatible_pre_1_3(self):
        topo_obj = objects.InstancePCIRequest(
            count=1,
            spec=[{'vendor_id': '8086', 'device_id': '1502'}],
            request_id=uuids.pci_request_id,
            requester_id=uuids.requester_id,
            numa_policy=fields.PCINUMAAffinityPolicy.PREFERRED)
        versions = ovo_base.obj_tree_get_versions('InstancePCIRequest')
        primitive = topo_obj.obj_to_primitive(target_version='1.2',
                                              version_manifest=versions)

        self.assertNotIn('requester_id', primitive['nova_object.data'])
        self.assertIn('numa_policy', primitive['nova_object.data'])

    def test_source_property(self):
        neutron_port_pci_req = objects.InstancePCIRequest(
            count=1,
            spec=[{'vendor_id': '15b3', 'device_id': '1018'}],
            request_id=uuids.pci_request_id1,
            requester_id=uuids.requester_id1,
            alias_name = None)
        flavor_alias_pci_req = objects.InstancePCIRequest(
            count=1,
            spec=[{'vendor_id': '15b3', 'device_id': '1810'}],
            request_id=uuids.pci_request_id2,
            requester_id=uuids.requester_id2,
            alias_name = 'alias_1')
        self.assertEqual(neutron_port_pci_req.source,
                         objects.InstancePCIRequest.NEUTRON_PORT)
        self.assertEqual(flavor_alias_pci_req.source,
                         objects.InstancePCIRequest.FLAVOR_ALIAS)


class TestInstancePCIRequests(test_objects._LocalTest,
                              _TestInstancePCIRequests):
    pass


class TestRemoteInstancePCIRequests(test_objects._RemoteTest,
                                    _TestInstancePCIRequests):
    pass
