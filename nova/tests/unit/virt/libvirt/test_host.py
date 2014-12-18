#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
#    Copyright 2014 Red Hat, Inc
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

import eventlet
from eventlet import greenthread
import mock

from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt import event
from nova.virt.libvirt import host

try:
    import libvirt
except ImportError:
    libvirt = fakelibvirt
host.libvirt = libvirt


class HostTestCase(test.NoDBTestCase):

    def setUp(self):
        super(HostTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")

    @mock.patch.object(fakelibvirt.virConnect, "registerCloseCallback")
    def test_close_callback(self, mock_close):
        self.close_callback = None

        def set_close_callback(cb, opaque):
            self.close_callback = cb

        mock_close.side_effect = set_close_callback
        # verify that the driver registers for the close callback
        self.host.get_connection()
        self.assertTrue(self.close_callback)

    @mock.patch.object(fakelibvirt.virConnect, "registerCloseCallback")
    def test_close_callback_bad_signature(self, mock_close):
        '''Validates that a connection to libvirt exist,
           even when registerCloseCallback method has a different
           number of arguments in the libvirt python library.
        '''
        mock_close.side_effect = TypeError('dd')
        connection = self.host.get_connection()
        self.assertTrue(connection)

    @mock.patch.object(fakelibvirt.virConnect, "registerCloseCallback")
    def test_close_callback_not_defined(self, mock_close):
        '''Validates that a connection to libvirt exist,
           even when registerCloseCallback method missing from
           the libvirt python library.
        '''
        mock_close.side_effect = AttributeError('dd')

        connection = self.host.get_connection()
        self.assertTrue(connection)

    @mock.patch.object(fakelibvirt.virConnect, "getLibVersion")
    def test_broken_connection(self, mock_ver):
        for (error, domain) in (
                (libvirt.VIR_ERR_SYSTEM_ERROR, libvirt.VIR_FROM_REMOTE),
                (libvirt.VIR_ERR_SYSTEM_ERROR, libvirt.VIR_FROM_RPC),
                (libvirt.VIR_ERR_INTERNAL_ERROR, libvirt.VIR_FROM_RPC)):

            conn = self.host._connect("qemu:///system", False)
            mock_ver.side_effect = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "Connection broken",
                error_code=error,
                error_domain=domain)
            self.assertFalse(self.host._test_connection(conn))

    @mock.patch.object(host, 'LOG')
    def test_connect_auth_cb_exception(self, log_mock):
        creds = dict(authname='nova', password='verybadpass')
        self.assertRaises(exception.NovaException,
                          self.host._connect_auth_cb, creds, False)
        self.assertEqual(0, len(log_mock.method_calls),
                         'LOG should not be used in _connect_auth_cb.')

    def test_event_dispatch(self):
        # Validate that the libvirt self-pipe for forwarding
        # events between threads is working sanely
        def handler(event):
            got_events.append(event)

        hostimpl = host.Host("qemu:///system",
                             lifecycle_event_handler=handler)
        got_events = []

        hostimpl._init_events_pipe()

        event1 = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_STARTED)
        event2 = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_PAUSED)
        hostimpl._queue_event(event1)
        hostimpl._queue_event(event2)
        hostimpl._dispatch_events()

        want_events = [event1, event2]
        self.assertEqual(want_events, got_events)

        event3 = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_RESUMED)
        event4 = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_STOPPED)

        hostimpl._queue_event(event3)
        hostimpl._queue_event(event4)
        hostimpl._dispatch_events()

        want_events = [event1, event2, event3, event4]
        self.assertEqual(want_events, got_events)

    def test_event_lifecycle(self):
        got_events = []

        # Validate that libvirt events are correctly translated
        # to Nova events
        def handler(event):
            got_events.append(event)

        hostimpl = host.Host("qemu:///system",
                             lifecycle_event_handler=handler)
        conn = hostimpl.get_connection()

        hostimpl._init_events_pipe()
        fake_dom_xml = """
                <domain type='kvm'>
                  <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                  <devices>
                    <disk type='file'>
                      <source file='filename'/>
                    </disk>
                  </devices>
                </domain>
            """
        dom = fakelibvirt.Domain(conn,
                                 fake_dom_xml,
                                 False)

        hostimpl._event_lifecycle_callback(conn,
                                           dom,
                                           libvirt.VIR_DOMAIN_EVENT_STOPPED,
                                           0,
                                           hostimpl)
        hostimpl._dispatch_events()
        self.assertEqual(len(got_events), 1)
        self.assertIsInstance(got_events[0], event.LifecycleEvent)
        self.assertEqual(got_events[0].uuid,
                         "cef19ce0-0ca2-11df-855d-b19fbce37686")
        self.assertEqual(got_events[0].transition,
                         event.EVENT_LIFECYCLE_STOPPED)

    def test_event_emit_delayed_call_now(self):
        got_events = []

        def handler(event):
            got_events.append(event)

        hostimpl = host.Host("qemu:///system",
                             lifecycle_event_handler=handler)
        ev = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_STOPPED)
        hostimpl._event_emit_delayed(ev)
        self.assertEqual(1, len(got_events))
        self.assertEqual(ev, got_events[0])

    @mock.patch.object(greenthread, 'spawn_after')
    def test_event_emit_delayed_call_delayed(self, spawn_after_mock):
        hostimpl = host.Host("xen:///",
                             lifecycle_event_handler=lambda e: None)
        ev = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_STOPPED)
        hostimpl._event_emit_delayed(ev)
        spawn_after_mock.assert_called_once_with(15, hostimpl._event_emit, ev)

    @mock.patch.object(greenthread, 'spawn_after')
    def test_event_emit_delayed_call_delayed_pending(self, spawn_after_mock):
        hostimpl = host.Host("xen:///",
                             lifecycle_event_handler=lambda e: None)

        uuid = "cef19ce0-0ca2-11df-855d-b19fbce37686"
        hostimpl._events_delayed[uuid] = None
        ev = event.LifecycleEvent(
            uuid, event.EVENT_LIFECYCLE_STOPPED)
        hostimpl._event_emit_delayed(ev)
        self.assertFalse(spawn_after_mock.called)

    def test_event_delayed_cleanup(self):
        hostimpl = host.Host("xen:///",
                             lifecycle_event_handler=lambda e: None)
        uuid = "cef19ce0-0ca2-11df-855d-b19fbce37686"
        ev = event.LifecycleEvent(
            uuid, event.EVENT_LIFECYCLE_STARTED)
        gt_mock = mock.Mock()
        hostimpl._events_delayed[uuid] = gt_mock
        hostimpl._event_delayed_cleanup(ev)
        gt_mock.cancel.assert_called_once_with()
        self.assertNotIn(uuid, hostimpl._events_delayed.keys())

    @mock.patch.object(fakelibvirt.virConnect, "domainEventRegisterAny")
    @mock.patch.object(host.Host, "_connect")
    def test_get_connection_serial(self, mock_conn, mock_event):
        def get_conn_currency(host):
            host.get_connection().getLibVersion()

        def connect_with_block(*a, **k):
            # enough to allow another connect to run
            eventlet.sleep(0)
            self.connect_calls += 1
            return fakelibvirt.openAuth("qemu:///system",
                                        [[], lambda: 1, None], 0)

        def fake_register(*a, **k):
            self.register_calls += 1

        self.connect_calls = 0
        self.register_calls = 0

        mock_conn.side_effect = connect_with_block
        mock_event.side_effect = fake_register

        # call serially
        get_conn_currency(self.host)
        get_conn_currency(self.host)
        self.assertEqual(self.connect_calls, 1)
        self.assertEqual(self.register_calls, 1)

    @mock.patch.object(fakelibvirt.virConnect, "domainEventRegisterAny")
    @mock.patch.object(host.Host, "_connect")
    def test_get_connection_concurrency(self, mock_conn, mock_event):
        def get_conn_currency(host):
            host.get_connection().getLibVersion()

        def connect_with_block(*a, **k):
            # enough to allow another connect to run
            eventlet.sleep(0)
            self.connect_calls += 1
            return fakelibvirt.openAuth("qemu:///system",
                                        [[], lambda: 1, None], 0)

        def fake_register(*a, **k):
            self.register_calls += 1

        self.connect_calls = 0
        self.register_calls = 0

        mock_conn.side_effect = connect_with_block
        mock_event.side_effect = fake_register

        # call concurrently
        thr1 = eventlet.spawn(get_conn_currency, self.host)
        thr2 = eventlet.spawn(get_conn_currency, self.host)

        # let threads run
        eventlet.sleep(0)

        thr1.wait()
        thr2.wait()
        self.assertEqual(self.connect_calls, 1)
        self.assertEqual(self.register_calls, 1)
