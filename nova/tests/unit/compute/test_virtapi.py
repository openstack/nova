#    Copyright 2012 IBM Corp.
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

from nova.compute import manager as compute_manager
from nova import context
from nova.db import api as db
from nova import exception
from nova import objects
from nova import test
from nova.virt import fake
from nova.virt import virtapi


class VirtAPIBaseTest(test.NoDBTestCase, test.APICoverage):

    cover_api = virtapi.VirtAPI

    def setUp(self):
        super(VirtAPIBaseTest, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.set_up_virtapi()

    def set_up_virtapi(self):
        self.virtapi = virtapi.VirtAPI()

    def assertExpected(self, method, *args, **kwargs):
        self.assertRaises(NotImplementedError,
                          getattr(self.virtapi, method), self.context,
                          *args, **kwargs)

    def test_wait_for_instance_event(self):
        self.assertExpected('wait_for_instance_event',
                            'instance', ['event'])


class FakeVirtAPITest(VirtAPIBaseTest):

    cover_api = fake.FakeVirtAPI

    def set_up_virtapi(self):
        self.virtapi = fake.FakeVirtAPI()

    def assertExpected(self, method, *args, **kwargs):
        if method == 'wait_for_instance_event':
            run = False
            with self.virtapi.wait_for_instance_event(*args, **kwargs):
                run = True
            self.assertTrue(run)
            return

        if method in ('aggregate_metadata_add', 'aggregate_metadata_delete',
                      'security_group_rule_get_by_security_group'):
            # NOTE(danms): FakeVirtAPI will convert the first argument to
            # argument['id'], so expect that in the actual db call
            e_args = tuple([args[0]['id']] + list(args[1:]))
        elif method == 'security_group_get_by_instance':
            e_args = tuple([args[0]['uuid']] + list(args[1:]))
        else:
            e_args = args

        with mock.patch.object(db, method,
                               return_value='it worked') as mock_call:
            result = getattr(self.virtapi, method)(self.context, *args,
                                                   **kwargs)
            self.assertEqual('it worked', result)
            mock_call.assert_called_once_with(self.context, *e_args, **kwargs)


class FakeCompute(object):
    def __init__(self):
        self.conductor_api = mock.MagicMock()
        self.db = mock.MagicMock()
        self._events = []
        self.instance_events = mock.MagicMock()
        self.instance_events.prepare_for_instance_event.side_effect = \
            self._prepare_for_instance_event

    def _event_waiter(self):
        event = mock.MagicMock()
        event.status = 'completed'
        return event

    def _prepare_for_instance_event(self, instance, name, tag):
        m = mock.MagicMock()
        m.instance = instance
        m.name = name
        m.tag = tag
        m.event_name = '%s-%s' % (name, tag)
        m.wait.side_effect = self._event_waiter
        self._events.append(m)
        return m


class ComputeVirtAPITest(VirtAPIBaseTest):

    cover_api = compute_manager.ComputeVirtAPI

    def set_up_virtapi(self):
        self.compute = FakeCompute()
        self.virtapi = compute_manager.ComputeVirtAPI(self.compute)

    def assertExpected(self, method, *args, **kwargs):
        with mock.patch.object(self.compute.conductor_api,
                               method, return_value='it worked') as mock_call:
            result = getattr(self.virtapi, method)(self.context, *args,
                                                   **kwargs)
            self.assertEqual('it worked', result)
            mock_call.assert_called_once_with(self.context, *args, **kwargs)

    def test_wait_for_instance_event(self):
        and_i_ran = ''
        event_1_tag = objects.InstanceExternalEvent.make_key(
            'event1')
        event_2_tag = objects.InstanceExternalEvent.make_key(
            'event2', 'tag')
        events = {
            ('event1', None): event_1_tag,
            ('event2', 'tag'): event_2_tag,
            }
        with self.virtapi.wait_for_instance_event('instance', events.keys()):
            and_i_ran = 'I ran so far a-waa-y'

        self.assertEqual('I ran so far a-waa-y', and_i_ran)
        self.assertEqual(2, len(self.compute._events))
        for event in self.compute._events:
            self.assertEqual('instance', event.instance)
            self.assertIn((event.name, event.tag), events.keys())
            event.wait.assert_called_once_with()

    def test_wait_for_instance_event_failed(self):
        def _failer():
            event = mock.MagicMock()
            event.status = 'failed'
            return event

        @mock.patch.object(self.virtapi._compute, '_event_waiter', _failer)
        def do_test():
            with self.virtapi.wait_for_instance_event('instance',
                                                      [('foo', 'bar')]):
                pass

        self.assertRaises(exception.NovaException, do_test)

    def test_wait_for_instance_event_failed_callback(self):
        def _failer():
            event = mock.MagicMock()
            event.status = 'failed'
            return event

        @mock.patch.object(self.virtapi._compute, '_event_waiter', _failer)
        def do_test():
            callback = mock.MagicMock()
            with self.virtapi.wait_for_instance_event('instance',
                                                      [('foo', None)],
                                                      error_callback=callback):
                pass
            callback.assert_called_with('foo', 'instance')

        do_test()

    def test_wait_for_instance_event_timeout(self):
        @mock.patch.object(self.virtapi._compute, '_event_waiter',
                           side_effect=test.TestingException())
        @mock.patch('eventlet.timeout.Timeout')
        def do_test(mock_timeout, mock_waiter):
            with self.virtapi.wait_for_instance_event('instance',
                                                      [('foo', 'bar')]):
                pass

        self.assertRaises(test.TestingException, do_test)
