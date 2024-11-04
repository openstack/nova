#    Copyright 2013 OpenStack Foundation
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

import datetime


FAKE_UUID = 'b48316c5-71e8-45e4-9884-6c78055b9b13'
FAKE_REQUEST_ID1 = 'req-3293a3f1-b44c-4609-b8d2-d81b105636b8'
FAKE_REQUEST_ID2 = 'req-25517360-b757-47d3-be45-0e8d2a01b36a'
FAKE_ACTION_ID1 = 123
FAKE_ACTION_ID2 = 456
# the value of the hostId fields depends on the value of the projectID field,
# so we define these statically
FAKE_PROJECT_ID1 = '9ccc9bd7-8b23-4d57-8421-291fe888bdc6'
FAKE_PROJECT_ID2 = '427b71e6-49d2-4c30-a8a0-d23adfe772e2'
FAKE_HOST_ID1 = 'b7e03ca48116ea93152de5d2eff1c69f515a5198f3cfbe59103faf17'
FAKE_HOST_ID2 = '7bd9ecf0b8cec52cd1410aee9b4bee5370c698bfc11f9478b35b80e2'

FAKE_ACTIONS = {
    FAKE_UUID: {
        FAKE_REQUEST_ID1: {
            'id': FAKE_ACTION_ID1,
            'action': 'reboot',
            'instance_uuid': FAKE_UUID,
            'request_id': FAKE_REQUEST_ID1,
            'project_id': FAKE_PROJECT_ID1,
            'user_id': '091d35ff-a42d-4717-8ba4-7dabfa7b13a4',
            'start_time': datetime.datetime(2012, 12, 5, 0, 0, 0, 0),
            'finish_time': None,
            'message': '',
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
        },
        FAKE_REQUEST_ID2: {
            'id': FAKE_ACTION_ID2,
            'action': 'resize',
            'instance_uuid': FAKE_UUID,
            'request_id': FAKE_REQUEST_ID2,
            'project_id': FAKE_PROJECT_ID2,
            'user_id': 'c0ab3ebb-ad1b-4b60-8e63-b8a5656315d0',
            'start_time': datetime.datetime(2012, 12, 5, 1, 0, 0, 0),
            'finish_time': None,
            'message': '',
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
        }
    }
}

FAKE_EVENTS = {
    FAKE_ACTION_ID1: [{'id': 1,
                       'action_id': FAKE_ACTION_ID1,
                       'event': 'schedule',
                       'start_time': datetime.datetime(
                           2012, 12, 5, 1, 0, 2, 0),
                       'finish_time': datetime.datetime(
                           2012, 12, 5, 1, 2, 0, 0),
                       'result': 'Success',
                       'traceback': '',
                       'created_at': None,
                       'updated_at': None,
                       'deleted_at': None,
                       'deleted': False,
                       'host': 'host1',
                       'hostId': FAKE_HOST_ID1,
                       'details': None
                      },
                      {'id': 2,
                       'action_id': FAKE_ACTION_ID1,
                       'event': 'compute_create',
                       'start_time': datetime.datetime(
                           2012, 12, 5, 1, 3, 0, 0),
                       'finish_time': datetime.datetime(
                           2012, 12, 5, 1, 4, 0, 0),
                       'result': 'Success',
                       'traceback': '',
                       'created_at': None,
                       'updated_at': None,
                       'deleted_at': None,
                       'deleted': False,
                       'host': 'host1',
                       'hostId': FAKE_HOST_ID1,
                       'details': None
                       }
    ],
    FAKE_ACTION_ID2: [{'id': 3,
                       'action_id': FAKE_ACTION_ID2,
                       'event': 'schedule',
                       'start_time': datetime.datetime(
                           2012, 12, 5, 3, 0, 0, 0),
                       'finish_time': datetime.datetime(
                           2012, 12, 5, 3, 2, 0, 0),
                       'result': 'Error',
                       'traceback': '',
                       'created_at': None,
                       'updated_at': None,
                       'deleted_at': None,
                       'deleted': False,
                       'host': 'host2',
                       'hostId': FAKE_HOST_ID2,
                       'details': None
                       }
   ]
}


def fake_action_event_start(*args):
    return FAKE_EVENTS[FAKE_ACTION_ID1][0]


def fake_action_event_finish(*args):
    return FAKE_EVENTS[FAKE_ACTION_ID1][0]


def stub_out_action_events(test):
    test.stub_out(
        'nova.db.main.api.action_event_start', fake_action_event_start)
    test.stub_out(
        'nova.db.main.api.action_event_finish', fake_action_event_finish)
