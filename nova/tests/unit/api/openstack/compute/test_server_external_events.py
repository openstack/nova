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
import webob

from nova.api.openstack.compute import server_external_events \
                                                 as server_external_events_v21
from nova import exception
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids

fake_instances = {
    '00000000-0000-0000-0000-000000000001': objects.Instance(id=1,
        uuid='00000000-0000-0000-0000-000000000001', host='host1'),
    '00000000-0000-0000-0000-000000000002': objects.Instance(id=2,
        uuid='00000000-0000-0000-0000-000000000002', host='host1'),
    '00000000-0000-0000-0000-000000000003': objects.Instance(id=3,
        uuid='00000000-0000-0000-0000-000000000003', host='host2'),
    '00000000-0000-0000-0000-000000000004': objects.Instance(id=4,
        uuid='00000000-0000-0000-0000-000000000004', host=None),
}
fake_instance_uuids = sorted(fake_instances.keys())
MISSING_UUID = '00000000-0000-0000-0000-000000000005'

fake_cells = [objects.CellMapping(uuid=uuids.cell1, database_connection="db1"),
              objects.CellMapping(uuid=uuids.cell2, database_connection="db2")]
fake_instance_mappings = [
        objects.InstanceMapping(cell_mapping=fake_cells[instance.id % 2],
                                instance_uuid=instance.uuid)
        for instance in fake_instances.values()]


@classmethod
def fake_get_by_filters(cls, context, filters, expected_attrs=None):
    if expected_attrs:
        # This is a regression check for bug 1645479.
        expected_attrs_set = set(expected_attrs)
        full_expected_attrs_set = set(instance_obj.INSTANCE_OPTIONAL_ATTRS)
        assert expected_attrs_set.issubset(full_expected_attrs_set), \
            ('%s is not a subset of %s' % (expected_attrs_set,
                                           full_expected_attrs_set))
    l = objects.InstanceList(objects=[
        inst for inst in fake_instances.values()
        if inst.uuid in filters['uuid']])
    return l


@classmethod
def fake_get_by_instance_uuids(cls, context, uuids):
    mappings = [im for im in fake_instance_mappings
                if im.instance_uuid in uuids]
    return objects.InstanceMappingList(objects=mappings)


@mock.patch('nova.objects.InstanceMappingList.get_by_instance_uuids',
            fake_get_by_instance_uuids)
@mock.patch('nova.objects.InstanceList.get_by_filters',
            fake_get_by_filters)
class ServerExternalEventsTestV21(test.NoDBTestCase):
    server_external_events = server_external_events_v21
    invalid_error = exception.ValidationError
    wsgi_api_version = '2.1'

    def setUp(self):
        super(ServerExternalEventsTestV21, self).setUp()
        self.api = \
            self.server_external_events.ServerExternalEventsController()
        self.event_1 = {'name': 'network-vif-plugged',
                        'tag': 'foo',
                        'server_uuid': fake_instance_uuids[0],
                        'status': 'completed'}
        self.event_2 = {'name': 'network-changed',
                        'server_uuid': fake_instance_uuids[1]}
        self.default_body = {'events': [self.event_1, self.event_2]}
        self.resp_event_1 = dict(self.event_1)
        self.resp_event_1['code'] = 200
        self.resp_event_2 = dict(self.event_2)
        self.resp_event_2['code'] = 200
        self.resp_event_2['status'] = 'completed'
        self.default_resp_body = {'events': [self.resp_event_1,
                                             self.resp_event_2]}
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                           version=self.wsgi_api_version)

    def _assert_call(self, body, expected_uuids, expected_events):
        with mock.patch.object(self.api.compute_api,
                               'external_instance_event') as api_method:
            response = self.api.create(self.req, body=body)

        result = response.obj
        code = response._code

        self.assertEqual(1, api_method.call_count)
        call = api_method.call_args_list[0]
        args = call[0]

        call_instances = args[1]
        call_events = args[2]

        self.assertEqual(set(expected_uuids),
                         set([instance.uuid for instance in call_instances]))
        self.assertEqual(len(expected_uuids), len(call_instances))

        self.assertEqual(set(expected_events),
                         set([event.name for event in call_events]))
        self.assertEqual(len(expected_events),
                         len(call_events))

        return result, code

    def test_create(self):
        result, code = self._assert_call(self.default_body,
                                         fake_instance_uuids[:2],
                                         ['network-vif-plugged',
                                          'network-changed'])
        self.assertEqual(self.default_resp_body, result)
        self.assertEqual(200, code)

    def test_create_one_bad_instance(self):
        body = self.default_body
        body['events'][1]['server_uuid'] = MISSING_UUID
        result, code = self._assert_call(body, [fake_instance_uuids[0]],
                                         ['network-vif-plugged'])
        self.assertEqual('failed', result['events'][1]['status'])
        self.assertEqual(200, result['events'][0]['code'])
        self.assertEqual(404, result['events'][1]['code'])
        self.assertEqual(207, code)

    def test_create_event_instance_has_no_host(self):
        body = self.default_body
        body['events'][0]['server_uuid'] = fake_instance_uuids[-1]
        # the instance without host should not be passed to the compute layer
        result, code = self._assert_call(body,
                                         [fake_instance_uuids[1]],
                                         ['network-changed'])
        self.assertEqual(422, result['events'][0]['code'])
        self.assertEqual('failed', result['events'][0]['status'])
        self.assertEqual(200, result['events'][1]['code'])
        self.assertEqual(207, code)

    def test_create_no_good_instances(self):
        body = self.default_body
        body['events'][0]['server_uuid'] = MISSING_UUID
        body['events'][1]['server_uuid'] = MISSING_UUID
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.api.create, self.req, body=body)

    def test_create_bad_status(self):
        body = self.default_body
        body['events'][1]['status'] = 'foo'
        self.assertRaises(self.invalid_error,
                          self.api.create, self.req, body=body)

    def test_create_extra_gorp(self):
        body = self.default_body
        body['events'][0]['foobar'] = 'bad stuff'
        self.assertRaises(self.invalid_error,
                          self.api.create, self.req, body=body)

    def test_create_bad_events(self):
        body = {'events': 'foo'}
        self.assertRaises(self.invalid_error,
                          self.api.create, self.req, body=body)

    def test_create_bad_body(self):
        body = {'foo': 'bar'}
        self.assertRaises(self.invalid_error,
                          self.api.create, self.req, body=body)

    def test_create_unknown_events(self):
        self.event_1['name'] = 'unkown_event'
        body = {'events': self.event_1}
        self.assertRaises(self.invalid_error,
                          self.api.create, self.req, body=body)


@mock.patch('nova.objects.InstanceMappingList.get_by_instance_uuids',
            fake_get_by_instance_uuids)
@mock.patch('nova.objects.InstanceList.get_by_filters',
            fake_get_by_filters)
class ServerExternalEventsTestV251(ServerExternalEventsTestV21):
    wsgi_api_version = '2.51'

    def test_create_with_missing_tag(self):
        body = self.default_body
        body['events'][1]['name'] = 'volume-extended'
        result, code = self._assert_call(body,
                                         [fake_instance_uuids[0]],
                                         ['network-vif-plugged'])
        self.assertEqual(200, result['events'][0]['code'])
        self.assertEqual('completed', result['events'][0]['status'])
        self.assertEqual(400, result['events'][1]['code'])
        self.assertEqual('failed', result['events'][1]['status'])
        self.assertEqual(207, code)
