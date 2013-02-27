# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from nova import db


FAKE_UUID = 'b48316c5-71e8-45e4-9884-6c78055b9b13'
FAKE_REQUEST_ID1 = 'req-3293a3f1-b44c-4609-b8d2-d81b105636b8'
FAKE_REQUEST_ID2 = 'req-25517360-b757-47d3-be45-0e8d2a01b36a'
FAKE_ACTION_ID1 = 'f811a359-0c98-4daa-87a4-2948d4c21b78'
FAKE_ACTION_ID2 = '4e9594b5-4ac5-421c-ac60-2d802b11c798'

FAKE_ACTIONS = {
    FAKE_UUID: {
        FAKE_REQUEST_ID1: {'id': FAKE_ACTION_ID1,
                          'action': 'reboot',
                          'instance_uuid': FAKE_UUID,
                          'request_id': FAKE_REQUEST_ID1,
                          'project_id': '147',
                          'user_id': '789',
                          'start_time': '2012-12-05 00:00:00.000000',
                          'finish_time': '',
                          'message': '',
        },
        FAKE_REQUEST_ID2: {'id': FAKE_ACTION_ID2,
                          'action': 'resize',
                          'instance_uuid': FAKE_UUID,
                          'request_id': FAKE_REQUEST_ID2,
                          'user_id': '789',
                          'project_id': '842',
                          'start_time': '2012-12-05 01:00:00.000000',
                          'finish_time': '',
                          'message': '',
        }
    }
}

FAKE_EVENTS = {
    FAKE_ACTION_ID1: [{'id': '1',
                       'event': 'schedule',
                       'start_time': '2012-12-05 01:00:02.000000',
                       'finish_time': '2012-12-05 01:02:00.000000',
                       'result': 'Success',
                       'traceback': '',
                      },
                      {'id': '2',
                       'event': 'compute_create',
                       'start_time': '2012-12-05 01:03:00.000000',
                       'finish_time': '2012-12-05 01:04:00.000000',
                       'result': 'Success',
                       'traceback': '',
                       }
    ],
    FAKE_ACTION_ID2: [{'id': '3',
                       'event': 'schedule',
                       'start_time': '2012-12-05 03:00:00.000000',
                       'finish_time': '2012-12-05 03:02:00.000000',
                       'result': 'Error',
                       'traceback': ''
                       }
   ]
}


def fake_action_event_start(*args):
    pass


def fake_action_event_finish(*args):
    pass


def stub_out_action_events(stubs):
    stubs.Set(db, 'action_event_start', fake_action_event_start)
    stubs.Set(db, 'action_event_finish', fake_action_event_finish)
