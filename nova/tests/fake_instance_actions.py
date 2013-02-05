# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2013 OpenStack LLC
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


def fake_action_event_start(*args):
    pass


def fake_action_event_finish(*args):
    pass


def stub_out_action_events(stubs):
    stubs.Set(db, 'action_event_start', fake_action_event_start)
    stubs.Set(db, 'action_event_finish', fake_action_event_finish)
