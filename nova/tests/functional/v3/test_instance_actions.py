# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

import copy

from nova.compute import api as compute_api
from nova import db
from nova.tests.functional.v3 import api_sample_base
from nova.tests.unit import fake_server_actions
from nova.tests.unit import utils as test_utils


class ServerActionsSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = 'os-instance-actions'

    def setUp(self):
        super(ServerActionsSampleJsonTest, self).setUp()
        self.actions = fake_server_actions.FAKE_ACTIONS
        self.events = fake_server_actions.FAKE_EVENTS
        self.instance = test_utils.get_test_instance()

        def fake_instance_action_get_by_request_id(context, uuid, request_id):
            return copy.deepcopy(self.actions[uuid][request_id])

        def fake_server_actions_get(context, uuid):
            return [copy.deepcopy(value) for value in
                    self.actions[uuid].itervalues()]

        def fake_instance_action_events_get(context, action_id):
            return copy.deepcopy(self.events[action_id])

        def fake_instance_get_by_uuid(context, instance_id):
            return self.instance

        def fake_get(self, context, instance_uuid, **kwargs):
            return {'uuid': instance_uuid}

        self.stubs.Set(db, 'action_get_by_request_id',
                       fake_instance_action_get_by_request_id)
        self.stubs.Set(db, 'actions_get', fake_server_actions_get)
        self.stubs.Set(db, 'action_events_get',
                       fake_instance_action_events_get)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)

    def test_instance_action_get(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_request_id = fake_server_actions.FAKE_REQUEST_ID1
        fake_action = self.actions[fake_uuid][fake_request_id]

        response = self._do_get('servers/%s/os-instance-actions/%s' %
                                (fake_uuid, fake_request_id))
        subs = self._get_regexes()
        subs['action'] = '(reboot)|(resize)'
        subs['instance_uuid'] = fake_uuid
        subs['integer_id'] = '[0-9]+'
        subs['request_id'] = fake_action['request_id']
        subs['start_time'] = fake_action['start_time']
        subs['result'] = '(Success)|(Error)'
        subs['event'] = '(schedule)|(compute_create)'
        self._verify_response('instance-action-get-resp', subs, response, 200)

    def test_instance_actions_list(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        response = self._do_get('servers/%s/os-instance-actions' % (fake_uuid))
        subs = self._get_regexes()
        subs['action'] = '(reboot)|(resize)'
        subs['integer_id'] = '[0-9]+'
        subs['request_id'] = ('req-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                              '-[0-9a-f]{4}-[0-9a-f]{12}')
        self._verify_response('instance-actions-list-resp', subs,
                              response, 200)
