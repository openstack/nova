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

from oslo_config import cfg
import six

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_server_actions
from nova.tests.unit import utils as test_utils

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ServerActionsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = 'os-instance-actions'

    def _get_flags(self):
        f = super(ServerActionsSampleJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.instance_actions.Instance_actions')
        return f

    def setUp(self):
        super(ServerActionsSampleJsonTest, self).setUp()
        self.actions = fake_server_actions.FAKE_ACTIONS
        self.events = fake_server_actions.FAKE_EVENTS
        self.instance = test_utils.get_test_instance(obj=True)

        def fake_instance_action_get_by_request_id(context, uuid, request_id):
            return copy.deepcopy(self.actions[uuid][request_id])

        def fake_server_actions_get(context, uuid):
            return [copy.deepcopy(value) for value in
                    six.itervalues(self.actions[uuid])]

        def fake_instance_action_events_get(context, action_id):
            return copy.deepcopy(self.events[action_id])

        def fake_instance_get_by_uuid(context, instance_id):
            return self.instance

        def fake_get(self, context, instance_uuid, expected_attrs=None,
                     want_objects=True):
            return fake_instance.fake_instance_obj(
                None, **{'uuid': instance_uuid})

        self.stub_out('nova.db.action_get_by_request_id',
                      fake_instance_action_get_by_request_id)
        self.stub_out('nova.db.actions_get', fake_server_actions_get)
        self.stub_out('nova.db.action_events_get',
                      fake_instance_action_events_get)
        self.stub_out('nova.db.instance_get_by_uuid',
                      fake_instance_get_by_uuid)
        self.stub_out('nova.compute.api.API.get', fake_get)

    def test_instance_action_get(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_request_id = fake_server_actions.FAKE_REQUEST_ID1
        fake_action = self.actions[fake_uuid][fake_request_id]

        response = self._do_get('servers/%s/os-instance-actions/%s' %
                                (fake_uuid, fake_request_id))
        subs = {}
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
        subs = {}
        subs['action'] = '(reboot)|(resize)'
        subs['integer_id'] = '[0-9]+'
        subs['request_id'] = ('req-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                              '-[0-9a-f]{4}-[0-9a-f]{12}')
        self._verify_response('instance-actions-list-resp', subs,
                              response, 200)
