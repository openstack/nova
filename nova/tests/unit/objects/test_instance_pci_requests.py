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

from nova import objects
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
     'request_id': FAKE_REQUEST_UUID},
    {'count': 2,
     'spec': [{'vendor_id': '6502',
               'device_id': '07B5'}],
     'alias_name': 'alias_2',
     'is_new': True,
     'request_id': FAKE_REQUEST_UUID},
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
    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
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

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    def test_get_by_instance_uuid_and_newness(self, mock_get):
        pcir = objects.InstancePCIRequests
        mock_get.return_value = objects.InstancePCIRequests(
            instance_uuid='fake-uuid',
            requests=[objects.InstancePCIRequest(count=1, is_new=False),
                      objects.InstancePCIRequest(count=2, is_new=True)])
        old_req = pcir.get_by_instance_uuid_and_newness(self.context,
                                                        'fake-uuid',
                                                        False)
        mock_get.return_value = objects.InstancePCIRequests(
            instance_uuid='fake-uuid',
            requests=[objects.InstancePCIRequest(count=1, is_new=False),
                      objects.InstancePCIRequest(count=2, is_new=True)])
        new_req = pcir.get_by_instance_uuid_and_newness(self.context,
                                                        'fake-uuid',
                                                        True)
        self.assertEqual(1, old_req.requests[0].count)
        self.assertEqual(2, new_req.requests[0].count)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    def test_get_by_instance_current(self, mock_get):
        instance = objects.Instance(uuid='fake-uuid',
                                    system_metadata={})
        objects.InstancePCIRequests.get_by_instance(self.context,
                                                    instance)
        mock_get.assert_called_once_with(self.context, 'fake-uuid')

    def test_get_by_instance_legacy(self):
        fakesysmeta = {
            'pci_requests': jsonutils.dumps([fake_legacy_pci_requests[0]]),
            'new_pci_requests': jsonutils.dumps([fake_legacy_pci_requests[1]]),
        }
        instance = objects.Instance(uuid='fake-uuid',
                                    system_metadata=fakesysmeta)
        requests = objects.InstancePCIRequests.get_by_instance(self.context,
                                                               instance)
        self.assertEqual(2, len(requests.requests))
        self.assertEqual('alias_1', requests.requests[0].alias_name)
        self.assertFalse(requests.requests[0].is_new)
        self.assertEqual('alias_2', requests.requests[1].alias_name)
        self.assertTrue(requests.requests[1].is_new)

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    def test_save(self, mock_update):
        requests = objects.InstancePCIRequests(
            context=self.context,
            instance_uuid=FAKE_UUID,
            requests=[objects.InstancePCIRequest(
                count=1,
                spec=[{'foo': 'bar'}, {'baz': 'bat'}],
                alias_name='alias_1',
                is_new=False,
                request_id=FAKE_REQUEST_UUID)])
        requests.save()
        self.assertEqual(FAKE_UUID, mock_update.call_args_list[0][0][1])
        self.assertEqual(
            [{'count': 1, 'is_new': False,
              'alias_name': 'alias_1',
              'spec': [{'foo': 'bar'}, {'baz': 'bat'}],
              'request_id': FAKE_REQUEST_UUID}],
            jsonutils.loads(
                mock_update.call_args_list[0][0][2]['pci_requests']))

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
    def test_save_and_reload(self, mock_get, mock_update):
        database = {}

        def _save(context, uuid, values):
            database.setdefault(uuid, {'instance_uuid': uuid})
            database[uuid].update(values)

        def _get(context, uuid, columns):
            return database.get(uuid, {})

        mock_update.side_effect = _save
        mock_get.side_effect = _get

        requests = objects.InstancePCIRequests(
            context=self.context,
            instance_uuid=FAKE_UUID,
            requests=[objects.InstancePCIRequest(
                count=1, is_new=False, alias_name='alias_1',
                spec=[{'foo': 'bar'}])])
        requests.save()
        _requests = objects.InstancePCIRequests.get_by_instance_uuid(
            self.context, FAKE_UUID)

        self.assertEqual(requests.instance_uuid, _requests.instance_uuid)
        self.assertEqual(len(requests.requests), len(_requests.requests))
        self.assertEqual(requests.requests[0].alias_name,
                         _requests.requests[0].alias_name)

    def test_new_compatibility(self):
        request = objects.InstancePCIRequest(is_new=False)
        self.assertFalse(request.new)

    def test_backport_1_0(self):
        requests = objects.InstancePCIRequests(
            requests=[objects.InstancePCIRequest(count=1,
                                                 request_id=FAKE_UUID),
                      objects.InstancePCIRequest(count=2,
                                                 request_id=FAKE_UUID)])
        primitive = requests.obj_to_primitive(target_version='1.0')
        backported = objects.InstancePCIRequests.obj_from_primitive(
            primitive)
        self.assertEqual('1.0', backported.VERSION)
        self.assertEqual(2, len(backported.requests))
        self.assertFalse(backported.requests[0].obj_attr_is_set('request_id'))
        self.assertFalse(backported.requests[1].obj_attr_is_set('request_id'))


class TestInstancePCIRequests(test_objects._LocalTest,
                              _TestInstancePCIRequests):
    pass


class TestRemoteInstancePCIRequests(test_objects._RemoteTest,
                                    _TestInstancePCIRequests):
    pass
