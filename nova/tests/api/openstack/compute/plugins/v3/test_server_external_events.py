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

import json

import mock
import webob

from nova.api.openstack.compute.plugins.v3 import server_external_events
from nova import context
from nova import exception
from nova.objects import instance as instance_obj
from nova import test

fake_instances = {
    '00000000-0000-0000-0000-000000000001': instance_obj.Instance(
        uuid='00000000-0000-0000-0000-000000000001', host='host1'),
    '00000000-0000-0000-0000-000000000002': instance_obj.Instance(
        uuid='00000000-0000-0000-0000-000000000002', host='host1'),
    '00000000-0000-0000-0000-000000000003': instance_obj.Instance(
        uuid='00000000-0000-0000-0000-000000000003', host='host2'),
}
fake_instance_uuids = sorted(fake_instances.keys())
MISSING_UUID = '00000000-0000-0000-0000-000000000004'


@classmethod
def fake_get_by_uuid(cls, context, uuid):
    try:
        return fake_instances[uuid]
    except KeyError:
        raise exception.InstanceNotFound(instance_id=uuid)


@mock.patch('nova.objects.instance.Instance.get_by_uuid', fake_get_by_uuid)
class ServerExternalEventsTest(test.NoDBTestCase):
    def setUp(self):
        super(ServerExternalEventsTest, self).setUp()
        self.api = server_external_events.ServerExternalEventsController()
        self.context = context.get_admin_context()
        self.default_body = {
            'events': [
                {'name': 'network-vif-plugged',
                 'tag': 'foo',
                 'status': 'completed',
                 'server_uuid': fake_instance_uuids[0]},
                {'name': 'network-changed',
                 'status': 'completed',
                 'server_uuid': fake_instance_uuids[1]},
                ]
            }

    def _create_req(self, body):
        req = webob.Request.blank('/v2/fake/os-server-external-events')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        req.body = json.dumps(body)
        return req

    def _assert_call(self, req, body, expected_uuids, expected_events):
        with mock.patch.object(self.api.compute_api,
                               'external_instance_event') as api_method:
            response = self.api.create(req, body)

        result = response.obj
        code = response._code

        self.assertEqual(1, api_method.call_count)
        for inst in api_method.call_args_list[0][0][1]:
            expected_uuids.remove(inst.uuid)
        self.assertEqual([], expected_uuids)
        for event in api_method.call_args_list[0][0][2]:
            expected_events.remove(event.name)
        self.assertEqual([], expected_events)
        return result, code

    def test_create(self):
        req = self._create_req(self.default_body)
        result, code = self._assert_call(req, self.default_body,
                                         fake_instance_uuids[:2],
                                         ['network-vif-plugged',
                                          'network-changed'])
        self.assertEqual(self.default_body, result)
        self.assertEqual(200, code)

    def test_create_one_bad_instance(self):
        body = self.default_body
        body['events'][1]['server_uuid'] = MISSING_UUID
        req = self._create_req(body)
        result, code = self._assert_call(req, body, [fake_instance_uuids[0]],
                                         ['network-vif-plugged'])
        self.assertEqual('failed', result['events'][1]['status'])
        self.assertEqual(200, result['events'][0]['code'])
        self.assertEqual(404, result['events'][1]['code'])
        self.assertEqual(207, code)

    def test_create_no_good_instances(self):
        body = self.default_body
        body['events'][0]['server_uuid'] = MISSING_UUID
        body['events'][1]['server_uuid'] = MISSING_UUID
        req = self._create_req(body)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.api.create, req, body)

    def test_create_bad_status(self):
        body = self.default_body
        body['events'][1]['status'] = 'foo'
        req = self._create_req(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.api.create, req, body)

    def test_create_extra_gorp(self):
        body = self.default_body
        body['events'][0]['foobar'] = 'bad stuff'
        req = self._create_req(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.api.create, req, body)

    def test_create_bad_events(self):
        body = {'events': 'foo'}
        req = self._create_req(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.api.create, req, body)

    def test_create_bad_body(self):
        body = {'foo': 'bar'}
        req = self._create_req(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.api.create, req, body)
