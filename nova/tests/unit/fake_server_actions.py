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

FAKE_ACTIONS = {
    FAKE_UUID: {
        FAKE_REQUEST_ID1: {'id': FAKE_ACTION_ID1,
                          'action': 'reboot',
                          'instance_uuid': FAKE_UUID,
                          'request_id': FAKE_REQUEST_ID1,
                          'project_id': '147',
                          'user_id': '789',
                          'start_time': datetime.datetime(
                              2012, 12, 5, 0, 0, 0, 0),
                          'finish_time': None,
                          'message': '',
                           'created_at': None,
                           'updated_at': None,
                           'deleted_at': None,
                           'deleted': False,
        },
        FAKE_REQUEST_ID2: {'id': FAKE_ACTION_ID2,
                          'action': 'resize',
                          'instance_uuid': FAKE_UUID,
                          'request_id': FAKE_REQUEST_ID2,
                          'user_id': '789',
                          'project_id': '842',
                          'start_time': datetime.datetime(
                              2012, 12, 5, 1, 0, 0, 0),
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
                       }
   ]
}


def fake_action_event_start(*args):
    return FAKE_EVENTS[FAKE_ACTION_ID1][0]


def fake_action_event_finish(*args):
    return FAKE_EVENTS[FAKE_ACTION_ID1][0]


def stub_out_action_events(test):
    test.stub_out('nova.db.action_event_start', fake_action_event_start)
    test.stub_out('nova.db.action_event_finish', fake_action_event_finish)
