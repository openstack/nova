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

import collections
from unittest import mock

import eventlet.timeout
import os_traits
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import manager as compute_manager
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova import test
from nova.virt import fake
from nova.virt import virtapi


class VirtAPIBaseTest(test.NoDBTestCase, test.APICoverage):

    cover_api = virtapi.VirtAPI

    def setUp(self):
        super(VirtAPIBaseTest, self).setUp()
        self.set_up_virtapi()

    def set_up_virtapi(self):
        self.virtapi = virtapi.VirtAPI()

    def assertExpected(self, method, *args, **kwargs):
        self.assertRaises(NotImplementedError,
                          getattr(self.virtapi, method),
                          *args, **kwargs)

    def test_wait_for_instance_event(self):
        self.assertExpected('wait_for_instance_event',
                            'instance', ['event'])

    def test_exit_wait_early(self):
        self.assertExpected('exit_wait_early', [])

    def test_update_compute_provider_status(self):
        self.assertExpected('update_compute_provider_status',
                            nova_context.get_admin_context(), uuids.rp_uuid,
                            enabled=False)


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
        elif method == 'exit_wait_early':
            self.virtapi.exit_wait_early(*args, **kwargs)
        elif method == 'update_compute_provider_status':
            self.virtapi.update_compute_provider_status(*args, **kwargs)
        else:
            self.fail("Unhandled FakeVirtAPI method: %s" % method)


class FakeCompute(object):
    def __init__(self):
        self.conductor_api = mock.MagicMock()
        self._events = []
        self.instance_events = mock.MagicMock()
        self.instance_events.prepare_for_instance_event.side_effect = \
            self._prepare_for_instance_event

        self.reportclient = mock.Mock(spec=report.SchedulerReportClient)
        # Keep track of the traits set on each provider in the test.
        self.provider_traits = collections.defaultdict(set)
        self.reportclient.get_provider_traits.side_effect = (
            self._get_provider_traits)
        self.reportclient.set_traits_for_provider.side_effect = (
            self._set_traits_for_provider)

    def _get_provider_traits(self, context, rp_uuid):
        return mock.Mock(traits=self.provider_traits[rp_uuid])

    def _set_traits_for_provider(
            self, context, rp_uuid, traits, generation=None):
        self.provider_traits[rp_uuid] = traits

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

    def test_exit_wait_early(self):
        self.assertRaises(self.virtapi._exit_early_exc,
                          self.virtapi.exit_wait_early,
                          [('foo', 'bar'),
                           ('foo', 'baz')])

    @mock.patch.object(compute_manager, 'LOG')
    def test_wait_for_instance_event(self, mock_log):
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
        mock_log.debug.assert_called_once_with(
            'Instance event wait completed in %i seconds for %s',
            mock.ANY, 'event1,event2', instance=event.instance)

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

    @mock.patch(
        'oslo_utils.timeutils.StopWatch.elapsed',
        new=mock.Mock(return_value=1.23))
    def test_wait_for_instance_event_timeout(self):
        instance = mock.Mock()
        instance.vm_state = mock.sentinel.vm_state
        instance.task_state = mock.sentinel.task_state

        mock_log = mock.Mock()

        @mock.patch.object(compute_manager, 'LOG', new=mock_log)
        @mock.patch.object(self.virtapi._compute, '_event_waiter',
                           side_effect=eventlet.timeout.Timeout())
        def do_test(mock_waiter):
            with self.virtapi.wait_for_instance_event(
                    instance, [('foo', 'bar')]):
                pass

        self.assertRaises(eventlet.timeout.Timeout, do_test)
        mock_log.warning.assert_called_once_with(
            'Timeout waiting for %(events)s for instance with vm_state '
            '%(vm_state)s and task_state %(task_state)s. '
            'Event states are: %(event_states)s',
            {
                'events': ['foo-bar'],
                'vm_state': mock.sentinel.vm_state,
                'task_state': mock.sentinel.task_state,
                'event_states':
                    'foo-bar: timed out after 1.23 seconds',
            },
            instance=instance
        )

    @mock.patch(
        'oslo_utils.timeutils.StopWatch.elapsed',
        new=mock.Mock(return_value=1.23))
    def test_wait_for_instance_event_one_received_one_timed_out(self):
        instance = mock.Mock()
        instance.vm_state = mock.sentinel.vm_state
        instance.task_state = mock.sentinel.task_state

        mock_log = mock.Mock()

        calls = []

        def fake_event_waiter(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                event = mock.Mock(status="completed")
                return event
            else:
                raise eventlet.timeout.Timeout()

        @mock.patch.object(compute_manager, 'LOG', new=mock_log)
        @mock.patch.object(self.virtapi._compute, '_event_waiter',
                           side_effect=fake_event_waiter)
        def do_test(mock_waiter):
            with self.virtapi.wait_for_instance_event(
                    instance, [('foo', 'bar'), ('missing', 'event')]):
                pass

        self.assertRaises(eventlet.timeout.Timeout, do_test)
        mock_log.warning.assert_called_once_with(
            'Timeout waiting for %(events)s for instance with vm_state '
            '%(vm_state)s and task_state %(task_state)s. '
            'Event states are: %(event_states)s',
            {
                'events': ['foo-bar', 'missing-event'],
                'vm_state': mock.sentinel.vm_state,
                'task_state': mock.sentinel.task_state,
                'event_states':
                    'foo-bar: received after waiting 1.23 seconds, '
                    'missing-event: timed out after 1.23 seconds',
            },
            instance=instance
        )

    @mock.patch(
        'oslo_utils.timeutils.StopWatch.elapsed',
        new=mock.Mock(return_value=1.23))
    def test_wait_for_instance_event_multiple_events(self):
        instance = mock.Mock()
        instance.vm_state = mock.sentinel.vm_state
        instance.task_state = mock.sentinel.task_state

        mock_log = mock.Mock()

        calls = []

        def fake_event_waiter(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                event = mock.Mock(status="completed")
                return event
            else:
                raise eventlet.timeout.Timeout()

        def fake_prepare_for_instance_event(instance, name, tag):
            m = mock.MagicMock()
            m.instance = instance
            m.name = name
            m.tag = tag
            m.event_name = '%s-%s' % (name, tag)
            m.wait.side_effect = fake_event_waiter
            if name == 'received-but-not-waited':
                m.ready.return_value = True
            if name == 'missing-but-not-waited':
                m.ready.return_value = False
            return m

        self.virtapi._compute.instance_events.prepare_for_instance_event.\
            side_effect = fake_prepare_for_instance_event

        @mock.patch.object(compute_manager, 'LOG', new=mock_log)
        def do_test():
            with self.virtapi.wait_for_instance_event(
                    instance,
                    [
                        ('received', 'event'),
                        ('early', 'event'),
                        ('missing', 'event'),
                        ('received-but-not-waited', 'event'),
                        ('missing-but-not-waited', 'event'),
                    ]
            ):
                self.virtapi.exit_wait_early([('early', 'event')])

        self.assertRaises(eventlet.timeout.Timeout, do_test)
        mock_log.warning.assert_called_once_with(
            'Timeout waiting for %(events)s for instance with vm_state '
            '%(vm_state)s and task_state %(task_state)s. '
            'Event states are: %(event_states)s',
            {
                'events':
                    [
                        'received-event',
                        'early-event',
                        'missing-event',
                        'received-but-not-waited-event',
                        'missing-but-not-waited-event'
                     ],
                'vm_state': mock.sentinel.vm_state,
                'task_state': mock.sentinel.task_state,
                'event_states':
                    'received-event: received after waiting 1.23 seconds, '
                    'early-event: received early, '
                    'missing-event: timed out after 1.23 seconds, '
                    'received-but-not-waited-event: received but not '
                    'processed, '
                    'missing-but-not-waited-event: expected but not received'
            },
            instance=instance
        )

    def test_wait_for_instance_event_exit_early(self):
        # Wait for two events, exit early skipping one.
        # Make sure we waited for one and did not wait for the other
        with self.virtapi.wait_for_instance_event('instance',
                                                  [('foo', 'bar'),
                                                   ('foo', 'baz')]):
            self.virtapi.exit_wait_early([('foo', 'baz')])
            self.fail('never gonna happen')

        self.assertEqual(2, len(self.compute._events))
        for event in self.compute._events:
            if event.tag == 'bar':
                event.wait.assert_called_once_with()
            else:
                event.wait.assert_not_called()

    def test_update_compute_provider_status(self):
        """Tests scenarios for adding/removing the COMPUTE_STATUS_DISABLED
        trait on a given compute node resource provider.
        """
        ctxt = nova_context.get_admin_context()
        # Start by adding the trait to a disabled provider.
        self.assertNotIn(uuids.rp_uuid, self.compute.provider_traits)
        self.virtapi.update_compute_provider_status(
            ctxt, uuids.rp_uuid, enabled=False)
        self.assertEqual({os_traits.COMPUTE_STATUS_DISABLED},
                         self.compute.provider_traits[uuids.rp_uuid])
        # Now run it again to make sure nothing changed.
        with mock.patch.object(self.compute.reportclient,
                               'set_traits_for_provider',
                               new_callable=mock.NonCallableMock):
            self.virtapi.update_compute_provider_status(
                ctxt, uuids.rp_uuid, enabled=False)
        # Now enable the provider and make sure the trait is removed.
        self.virtapi.update_compute_provider_status(
            ctxt, uuids.rp_uuid, enabled=True)
        self.assertEqual(set(), self.compute.provider_traits[uuids.rp_uuid])
