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

from nova.objects import external_event as external_event_obj
from nova.tests.unit.objects import test_objects


class _TestInstanceExternalEventObject(object):
    def test_make_key(self):
        key = external_event_obj.InstanceExternalEvent.make_key('foo', 'bar')
        self.assertEqual('foo-bar', key)

    def test_make_key_no_tag(self):
        key = external_event_obj.InstanceExternalEvent.make_key('foo')
        self.assertEqual('foo', key)

    def test_key(self):
        event = external_event_obj.InstanceExternalEvent(
                    name='network-changed',
                    tag='bar')
        with mock.patch.object(event, 'make_key') as make_key:
            make_key.return_value = 'key'
            self.assertEqual('key', event.key)
            make_key.assert_called_once_with('network-changed', 'bar')

    def test_event_names(self):
        for event in external_event_obj.EVENT_NAMES:
            external_event_obj.InstanceExternalEvent(name=event, tag='bar')

        self.assertRaises(ValueError,
                          external_event_obj.InstanceExternalEvent,
                          name='foo', tag='bar')


class TestInstanceExternalEventObject(test_objects._LocalTest,
                                      _TestInstanceExternalEventObject):
    pass


class TestRemoteInstanceExternalEventObject(test_objects._RemoteTest,
                                            _TestInstanceExternalEventObject):
    pass
