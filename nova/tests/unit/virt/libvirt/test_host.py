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

import os

import eventlet
from eventlet import greenthread
from eventlet import tpool
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import six
from six.moves import builtins
import testtools


from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova import test
from nova.tests.unit.virt.libvirt import fake_libvirt_data
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt import event
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host


class StringMatcher(object):
    def __eq__(self, other):
        return isinstance(other, six.string_types)


class FakeVirtDomain(object):

    def __init__(self, id=-1, name=None):
        self._id = id
        self._name = name
        self._uuid = uuidutils.generate_uuid()

    def name(self):
        return self._name

    def ID(self):
        return self._id

    def UUIDString(self):
        return self._uuid


class HostTestCase(test.NoDBTestCase):

    def setUp(self):
        super(HostTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")

    @mock.patch("nova.virt.libvirt.host.Host._init_events")
    def test_repeat_initialization(self, mock_init_events):
        for i in range(3):
            self.host.initialize()
        mock_init_events.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virConnect, "registerCloseCallback")
    def test_close_callback(self, mock_close):
        self.close_callback = None

        def set_close_callback(cb, opaque):
            self.close_callback = cb

        mock_close.side_effect = set_close_callback
        # verify that the driver registers for the close callback
        self.host.get_connection()
        self.assertTrue(self.close_callback)

    @mock.patch.object(fakelibvirt.virConnect, "getLibVersion")
    def test_broken_connection(self, mock_ver):
        for (error, domain) in (
                (fakelibvirt.VIR_ERR_SYSTEM_ERROR,
                 fakelibvirt.VIR_FROM_REMOTE),
                (fakelibvirt.VIR_ERR_SYSTEM_ERROR,
                 fakelibvirt.VIR_FROM_RPC),
                (fakelibvirt.VIR_ERR_INTERNAL_ERROR,
                 fakelibvirt.VIR_FROM_RPC)):

            conn = self.host._connect("qemu:///system", False)
            mock_ver.side_effect = fakelibvirt.make_libvirtError(
                fakelibvirt.libvirtError,
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

    @mock.patch.object(greenthread, 'spawn_after')
    def test_event_dispatch(self, mock_spawn_after):
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

        want_events = [event1, event2, event3]
        self.assertEqual(want_events, got_events)

        # STOPPED is delayed so it's handled separately
        mock_spawn_after.assert_called_once_with(
            hostimpl._lifecycle_delay, hostimpl._event_emit, event4)

    def test_event_lifecycle(self):
        got_events = []

        # Validate that libvirt events are correctly translated
        # to Nova events
        def spawn_after(seconds, func, *args, **kwargs):
            got_events.append(args[0])
            return mock.Mock(spec=greenthread.GreenThread)

        greenthread.spawn_after = mock.Mock(side_effect=spawn_after)
        hostimpl = host.Host("qemu:///system",
                             lifecycle_event_handler=lambda e: None)
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

        hostimpl._event_lifecycle_callback(
            conn, dom, fakelibvirt.VIR_DOMAIN_EVENT_STOPPED, 0, hostimpl)
        hostimpl._dispatch_events()
        self.assertEqual(len(got_events), 1)
        self.assertIsInstance(got_events[0], event.LifecycleEvent)
        self.assertEqual(got_events[0].uuid,
                         "cef19ce0-0ca2-11df-855d-b19fbce37686")
        self.assertEqual(got_events[0].transition,
                         event.EVENT_LIFECYCLE_STOPPED)

    def test_event_lifecycle_callback_suspended_postcopy(self):
        """Tests the suspended lifecycle event with libvirt with post-copy"""
        hostimpl = mock.MagicMock()
        conn = mock.MagicMock()
        fake_dom_xml = """
                <domain type='kvm'>
                  <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                </domain>
            """
        dom = fakelibvirt.Domain(conn, fake_dom_xml, running=True)
        host.Host._event_lifecycle_callback(
            conn, dom, fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED,
            detail=fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED_POSTCOPY,
            opaque=hostimpl)
        expected_event = hostimpl._queue_event.call_args[0][0]
        self.assertEqual(event.EVENT_LIFECYCLE_POSTCOPY_STARTED,
                         expected_event.transition)

    @mock.patch('nova.virt.libvirt.guest.Guest.get_job_info')
    def test_event_lifecycle_callback_suspended_migrated(self, get_job_info):
        """Tests the suspended lifecycle event with libvirt with migrated"""
        hostimpl = mock.MagicMock()
        conn = mock.MagicMock()
        fake_dom_xml = """
                <domain type='kvm'>
                  <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                </domain>
            """
        dom = fakelibvirt.Domain(conn, fake_dom_xml, running=True)
        jobinfo = libvirt_guest.JobInfo(
            type=fakelibvirt.VIR_DOMAIN_JOB_COMPLETED)
        get_job_info.return_value = jobinfo
        host.Host._event_lifecycle_callback(
            conn, dom, fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED,
            detail=fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED,
            opaque=hostimpl)
        expected_event = hostimpl._queue_event.call_args[0][0]
        self.assertEqual(event.EVENT_LIFECYCLE_MIGRATION_COMPLETED,
                         expected_event.transition)
        get_job_info.assert_called_once_with()

    @mock.patch('nova.virt.libvirt.guest.Guest.get_job_info')
    @mock.patch('nova.virt.libvirt.migration.find_job_type')
    def test_event_lifecycle_callback_suspended_migrated_job_failed(
            self, find_job_type, get_job_info):
        """Tests the suspended lifecycle event with libvirt with migrated"""
        hostimpl = mock.MagicMock()
        conn = mock.MagicMock()
        fake_dom_xml = """
                <domain type='kvm'>
                  <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                </domain>
            """
        dom = fakelibvirt.Domain(conn, fake_dom_xml, running=True)
        jobinfo = libvirt_guest.JobInfo(type=fakelibvirt.VIR_DOMAIN_JOB_NONE)
        get_job_info.return_value = jobinfo
        # If the job type is VIR_DOMAIN_JOB_NONE we'll attempt to figure out
        # the actual job status, so in this case we mock it to be a failure.
        find_job_type.return_value = fakelibvirt.VIR_DOMAIN_JOB_FAILED
        host.Host._event_lifecycle_callback(
            conn, dom, fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED,
            detail=fakelibvirt.VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED,
            opaque=hostimpl)
        expected_event = hostimpl._queue_event.call_args[0][0]
        self.assertEqual(event.EVENT_LIFECYCLE_PAUSED,
                         expected_event.transition)
        get_job_info.assert_called_once_with()
        find_job_type.assert_called_once_with(
            test.MatchType(libvirt_guest.Guest), instance=None,
            logging_ok=False)

    def test_event_emit_delayed_call_delayed(self):
        ev = event.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            event.EVENT_LIFECYCLE_STOPPED)
        for uri in ("qemu:///system", "xen:///"):
            spawn_after_mock = mock.Mock()
            greenthread.spawn_after = spawn_after_mock
            hostimpl = host.Host(uri,
                                 lifecycle_event_handler=lambda e: None)
            hostimpl._event_emit_delayed(ev)
            spawn_after_mock.assert_called_once_with(
                15, hostimpl._event_emit, ev)

    @mock.patch.object(greenthread, 'spawn_after')
    def test_event_emit_delayed_call_delayed_pending(self, spawn_after_mock):
        hostimpl = host.Host("xen:///",
                             lifecycle_event_handler=lambda e: None)

        uuid = "cef19ce0-0ca2-11df-855d-b19fbce37686"
        gt_mock = mock.Mock()
        hostimpl._events_delayed[uuid] = gt_mock
        ev = event.LifecycleEvent(
            uuid, event.EVENT_LIFECYCLE_STOPPED)
        hostimpl._event_emit_delayed(ev)
        gt_mock.cancel.assert_called_once_with()
        self.assertTrue(spawn_after_mock.called)

    def test_event_delayed_cleanup(self):
        hostimpl = host.Host("xen:///",
                             lifecycle_event_handler=lambda e: None)
        uuid = "cef19ce0-0ca2-11df-855d-b19fbce37686"
        ev = event.LifecycleEvent(
            uuid, event.EVENT_LIFECYCLE_STARTED)
        gt_mock = mock.Mock()
        hostimpl._events_delayed[uuid] = gt_mock
        hostimpl._event_emit_delayed(ev)
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

    @mock.patch.object(host.Host, "_connect")
    def test_conn_event(self, mock_conn):
        handler = mock.MagicMock()
        h = host.Host("qemu:///system", conn_event_handler=handler)

        h.get_connection()
        h._dispatch_conn_event()

        handler.assert_called_once_with(True, None)

    @mock.patch.object(host.Host, "_connect")
    def test_conn_event_fail(self, mock_conn):
        handler = mock.MagicMock()
        h = host.Host("qemu:///system", conn_event_handler=handler)
        mock_conn.side_effect = fakelibvirt.libvirtError('test')

        self.assertRaises(exception.HypervisorUnavailable, h.get_connection)
        h._dispatch_conn_event()

        handler.assert_called_once_with(False, StringMatcher())

        # Attempt to get a second connection, and assert that we don't add
        # queue a second callback. Note that we can't call
        # _dispatch_conn_event() and assert no additional call to the handler
        # here as above. This is because we haven't added an event, so it would
        # block. We mock the helper method which queues an event for callback
        # instead.
        with mock.patch.object(h, '_queue_conn_event_handler') as mock_queue:
            self.assertRaises(exception.HypervisorUnavailable,
                              h.get_connection)
            mock_queue.assert_not_called()

    @mock.patch.object(host.Host, "_test_connection")
    @mock.patch.object(host.Host, "_connect")
    def test_conn_event_up_down(self, mock_conn, mock_test_conn):
        handler = mock.MagicMock()
        h = host.Host("qemu:///system", conn_event_handler=handler)
        mock_conn.side_effect = (mock.MagicMock(),
                                 fakelibvirt.libvirtError('test'))
        mock_test_conn.return_value = False

        h.get_connection()
        self.assertRaises(exception.HypervisorUnavailable, h.get_connection)
        h._dispatch_conn_event()
        h._dispatch_conn_event()

        handler.assert_has_calls([
            mock.call(True, None),
            mock.call(False, StringMatcher())
        ])

    @mock.patch.object(host.Host, "_connect")
    def test_conn_event_thread(self, mock_conn):
        event = eventlet.event.Event()
        h = host.Host("qemu:///system", conn_event_handler=event.send)
        h.initialize()

        h.get_connection()
        event.wait()
        # This test will timeout if it fails. Success is implicit in a
        # timely return from wait(), indicating that the connection event
        # handler was called.

    @mock.patch.object(fakelibvirt.virConnect, "getLibVersion")
    @mock.patch.object(fakelibvirt.virConnect, "getVersion")
    @mock.patch.object(fakelibvirt.virConnect, "getType")
    def test_has_min_version(self, fake_hv_type, fake_hv_ver, fake_lv_ver):
        fake_lv_ver.return_value = 1002003
        fake_hv_ver.return_value = 4005006
        fake_hv_type.return_value = 'xyz'

        lv_ver = (1, 2, 3)
        hv_ver = (4, 5, 6)
        hv_type = 'xyz'
        self.assertTrue(self.host.has_min_version(lv_ver, hv_ver, hv_type))

        self.assertFalse(self.host.has_min_version(lv_ver, hv_ver, 'abc'))
        self.assertFalse(self.host.has_min_version(lv_ver, (4, 5, 7), hv_type))
        self.assertFalse(self.host.has_min_version((1, 3, 3), hv_ver, hv_type))

        self.assertTrue(self.host.has_min_version(lv_ver, hv_ver, None))
        self.assertTrue(self.host.has_min_version(lv_ver, None, hv_type))
        self.assertTrue(self.host.has_min_version(None, hv_ver, hv_type))

    @mock.patch.object(fakelibvirt.virConnect, "getLibVersion")
    @mock.patch.object(fakelibvirt.virConnect, "getVersion")
    @mock.patch.object(fakelibvirt.virConnect, "getType")
    def test_has_version(self, fake_hv_type, fake_hv_ver, fake_lv_ver):
        fake_lv_ver.return_value = 1002003
        fake_hv_ver.return_value = 4005006
        fake_hv_type.return_value = 'xyz'

        lv_ver = (1, 2, 3)
        hv_ver = (4, 5, 6)
        hv_type = 'xyz'
        self.assertTrue(self.host.has_version(lv_ver, hv_ver, hv_type))

        for lv_ver_ in [(1, 2, 2), (1, 2, 4)]:
            self.assertFalse(self.host.has_version(lv_ver_, hv_ver, hv_type))
        for hv_ver_ in [(4, 4, 6), (4, 6, 6)]:
            self.assertFalse(self.host.has_version(lv_ver, hv_ver_, hv_type))
        self.assertFalse(self.host.has_version(lv_ver, hv_ver, 'abc'))

        self.assertTrue(self.host.has_version(lv_ver, hv_ver, None))
        self.assertTrue(self.host.has_version(lv_ver, None, hv_type))
        self.assertTrue(self.host.has_version(None, hv_ver, hv_type))

    @mock.patch.object(fakelibvirt.virConnect, "lookupByUUIDString")
    def test_get_domain(self, fake_lookup):
        uuid = uuidutils.generate_uuid()
        dom = fakelibvirt.virDomain(self.host.get_connection(),
                                    "<domain id='7'/>")
        instance = objects.Instance(id="124", uuid=uuid)
        fake_lookup.return_value = dom

        self.assertEqual(dom, self.host._get_domain(instance))
        fake_lookup.assert_called_once_with(uuid)

    @mock.patch.object(fakelibvirt.virConnect, "lookupByUUIDString")
    def test_get_domain_raises(self, fake_lookup):
        instance = objects.Instance(uuid=uuids.instance,
                                    vm_state=vm_states.ACTIVE)
        fake_lookup.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            'Domain not found: no domain with matching name',
            error_code=fakelibvirt.VIR_ERR_NO_DOMAIN,
            error_domain=fakelibvirt.VIR_FROM_QEMU)

        with testtools.ExpectedException(exception.InstanceNotFound):
            self.host._get_domain(instance)

        fake_lookup.assert_called_once_with(uuids.instance)

    @mock.patch.object(fakelibvirt.virConnect, "lookupByUUIDString")
    def test_get_guest(self, fake_lookup):
        uuid = uuidutils.generate_uuid()
        dom = fakelibvirt.virDomain(self.host.get_connection(),
                                    "<domain id='7'/>")

        fake_lookup.return_value = dom
        instance = objects.Instance(id="124", uuid=uuid)

        guest = self.host.get_guest(instance)
        self.assertEqual(dom, guest._domain)
        self.assertIsInstance(guest, libvirt_guest.Guest)

        fake_lookup.assert_called_once_with(uuid)

    @mock.patch.object(fakelibvirt.Connection, "listAllDomains")
    def test_list_instance_domains(self, mock_list_all):
        vm0 = FakeVirtDomain(id=0, name="Domain-0")  # Xen dom-0
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        def fake_list_all(flags):
            vms = [vm0]
            if flags & fakelibvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE:
                vms.extend([vm1, vm2])
            if flags & fakelibvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE:
                vms.extend([vm3, vm4])
            return vms

        mock_list_all.side_effect = fake_list_all

        doms = self.host.list_instance_domains()

        mock_list_all.assert_called_once_with(
            fakelibvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        mock_list_all.reset_mock()

        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())

        doms = self.host.list_instance_domains(only_running=False)

        mock_list_all.assert_called_once_with(
            fakelibvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE |
            fakelibvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE)
        mock_list_all.reset_mock()

        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())

        doms = self.host.list_instance_domains(only_guests=False)

        mock_list_all.assert_called_once_with(
            fakelibvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        mock_list_all.reset_mock()

        self.assertEqual(len(doms), 3)
        self.assertEqual(doms[0].name(), vm0.name())
        self.assertEqual(doms[1].name(), vm1.name())
        self.assertEqual(doms[2].name(), vm2.name())

    @mock.patch.object(host.Host, "list_instance_domains")
    def test_list_guests(self, mock_list_domains):
        dom0 = mock.Mock(spec=fakelibvirt.virDomain)
        dom1 = mock.Mock(spec=fakelibvirt.virDomain)
        mock_list_domains.return_value = [
            dom0, dom1]
        result = self.host.list_guests(True, False)
        mock_list_domains.assert_called_once_with(
            only_running=True, only_guests=False)
        self.assertEqual(dom0, result[0]._domain)
        self.assertEqual(dom1, result[1]._domain)

    def test_cpu_features_bug_1217630(self):
        self.host.get_connection()

        # Test old version of libvirt, it shouldn't see the `aes' feature
        with mock.patch('nova.virt.libvirt.host.libvirt') as mock_libvirt:
            del mock_libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES
            caps = self.host.get_capabilities()
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Cleanup the capabilities cache firstly
        self.host._caps = None

        # Test new version of libvirt, should find the `aes' feature
        with mock.patch('nova.virt.libvirt.host.libvirt') as mock_libvirt:
            mock_libvirt['VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'] = 1
            caps = self.host.get_capabilities()
            self.assertIn('aes', [x.name for x in caps.host.cpu.features])

    def test_cpu_features_are_not_duplicated(self):
        self.host.get_connection()

        # Test old version of libvirt. Should return single 'hypervisor'
        with mock.patch('nova.virt.libvirt.host.libvirt') as mock_libvirt:
            del mock_libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES
            caps = self.host.get_capabilities()
            cnt = [x.name for x in caps.host.cpu.features].count('xtpr')
            self.assertEqual(1, cnt)

        # Cleanup the capabilities cache firstly
        self.host._caps = None

        # Test new version of libvirt. Should still return single 'hypervisor'
        with mock.patch('nova.virt.libvirt.host.libvirt') as mock_libvirt:
            mock_libvirt['VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'] = 1
            caps = self.host.get_capabilities()
            cnt = [x.name for x in caps.host.cpu.features].count('xtpr')
            self.assertEqual(1, cnt)

    def test_baseline_cpu_not_supported(self):
        # Handle just the NO_SUPPORT error
        not_supported_exc = fakelibvirt.make_libvirtError(
                fakelibvirt.libvirtError,
                'this function is not supported by the connection driver:'
                ' virConnectBaselineCPU',
                error_code=fakelibvirt.VIR_ERR_NO_SUPPORT)

        with mock.patch.object(fakelibvirt.virConnect, 'baselineCPU',
                               side_effect=not_supported_exc):
            caps = self.host.get_capabilities()
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Clear cached result so we can test again...
        self.host._caps = None

        # Other errors should not be caught
        other_exc = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            'other exc',
            error_code=fakelibvirt.VIR_ERR_NO_DOMAIN)

        with mock.patch.object(fakelibvirt.virConnect, 'baselineCPU',
                               side_effect=other_exc):
            self.assertRaises(fakelibvirt.libvirtError,
                              self.host.get_capabilities)

    def test_get_capabilities_no_host_cpu_model(self):
        """Tests that cpu features are not retrieved when the host cpu model
        is not in the capabilities.
        """
        fake_caps_xml = '''
<capabilities>
  <host>
    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
    <cpu>
      <arch>x86_64</arch>
      <vendor>Intel</vendor>
    </cpu>
  </host>
</capabilities>'''
        with mock.patch.object(fakelibvirt.virConnect, 'getCapabilities',
                               return_value=fake_caps_xml):
            caps = self.host.get_capabilities()
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertIsNone(caps.host.cpu.model)
            self.assertEqual(0, len(caps.host.cpu.features))

    def test__get_machine_types(self):
        expected = [
            # NOTE(aspiers): in the real world, i686 would probably
            # have q35 too, but our fixtures are manipulated to
            # exclude it to allow more thorough testing the our
            # canonical machine types logic is correct.
            ('i686', 'qemu', ['pc']),
            ('i686', 'kvm', ['pc']),
            ('x86_64', 'qemu', ['pc', 'q35']),
            ('x86_64', 'kvm', ['pc', 'q35']),
            ('armv7l', 'qemu', ['virt']),
            # NOTE(aspiers): we're currently missing default machine
            # types for the other architectures for which we have fake
            # capabilities.
        ]
        for arch, domain, expected_mach_types in expected:
            guest_xml = fake_libvirt_data.CAPABILITIES_GUEST[arch]
            guest = vconfig.LibvirtConfigCapsGuest()
            guest.parse_str(guest_xml)
            domain = guest.domains[domain]
            self.assertEqual(set(expected_mach_types),
                             self.host._get_machine_types(arch, domain),
                             "for arch %s domain %s" %
                             (arch, domain.domtype))

    def _test_get_domain_capabilities(self):
        caps = self.host.get_domain_capabilities()
        for arch, mtypes in caps.items():
            for mtype, dom_cap in mtypes.items():
                self.assertIsInstance(dom_cap, vconfig.LibvirtConfigDomainCaps)
                # NOTE(sean-k-mooney): this should always be true since we are
                # mapping from an arch and machine_type to a domain cap object
                # for that pair. We use 'in' to allow libvirt to expand the
                # unversioned alias such as 'pc' or 'q35' to its versioned
                # form e.g. pc-i440fx-2.11
                self.assertIn(mtype, dom_cap.machine_type)
                self.assertIn(dom_cap.machine_type_alias, mtype)

        # We assume we are testing with x86_64 in other parts of the code
        # so we just assert it's in the test data and return it.
        expected = [
            ('i686', ['pc', 'pc-i440fx-2.11']),
            ('x86_64', ['pc', 'pc-i440fx-2.11', 'q35', 'pc-q35-2.11']),
        ]
        for arch, expected_mtypes in expected:
            self.assertIn(arch, caps)
            for mach_type in expected_mtypes:
                self.assertIn(mach_type, caps[arch], "for arch %s" % arch)

        return caps['x86_64']['pc']

    def test_get_domain_capabilities(self):
        caps = self._test_get_domain_capabilities()
        self.assertEqual(vconfig.LibvirtConfigDomainCaps, type(caps))
        # There is a <gic supported='no'/> feature in the fixture but
        # we don't parse that because nothing currently cares about it.
        self.assertEqual(0, len(caps.features))

    def test_get_domain_capabilities_non_native_kvm(self):
        # This test assumes that we are on a x86 host and the
        # virt-type is set to kvm. In that case we would expect
        # libvirt to raise an error if you try to get the domain
        # capabilities for non-native archs specifying the kvm virt
        # type.
        archs = {
            'sparc': 'SS-5',
            'mips': 'malta',
            'mipsel': 'malta',
            'ppc': 'g3beige',
            'armv7l': 'virt-2.11',
        }

        # Because we are mocking out the libvirt connection and
        # supplying fake data, no exception will be raised, so we
        # first store a reference to the original
        # _get_domain_capabilities function
        local__get_domain_caps = self.host._get_domain_capabilities

        # We then define our own version that will raise for
        # non-native archs and otherwise delegates to the private
        # function.
        def _get_domain_capabilities(**kwargs):
            arch = kwargs['arch']
            if arch not in archs:
                return local__get_domain_caps(**kwargs)
            else:
                exc = fakelibvirt.make_libvirtError(
                    fakelibvirt.libvirtError,
                    "invalid argument: KVM is not supported by "
                    "'/usr/bin/qemu-system-%s' on this host" % arch,
                    error_code=fakelibvirt.VIR_ERR_INVALID_ARG)
                raise exc

        # Finally we patch to use our own version
        with test.nested(
            mock.patch.object(host.LOG, 'debug'),
            mock.patch.object(self.host, "_get_domain_capabilities"),
        ) as (mock_log, mock_caps):
            mock_caps.side_effect = _get_domain_capabilities
            self.flags(virt_type='kvm', group='libvirt')
            # and call self.host.get_domain_capabilities() directly as
            # the exception should be caught internally
            caps = self.host.get_domain_capabilities()
            # We don't really care what mock_caps is called with,
            # as we assert the behavior we expect below. However we
            # can at least check for the expected debug messages.
            mock_caps.assert_called()
            warnings = []
            for call in mock_log.mock_calls:
                name, args, kwargs = call
                if "Error from libvirt when retrieving domain capabilities" \
                        in args[0]:
                    warnings.append(call)
            self.assertTrue(len(warnings) > 0)

        # The resulting capabilities object should be non-empty
        # as the x86 archs won't raise a libvirtError exception
        self.assertTrue(len(caps) > 0)
        # but all of the archs we mocked out should be skipped and
        # not included in the result set
        for arch in archs:
            self.assertNotIn(arch, caps)

    def test_get_domain_capabilities_other_archs(self):
        # NOTE(aspiers): only architectures which are returned by
        # fakelibvirt's getCapabilities() can be tested here, since
        # Host.get_domain_capabilities() iterates over those
        # architectures.
        archs = {
            'sparc': 'SS-5',
            'mips': 'malta',
            'mipsel': 'malta',
            'ppc': 'g3beige',
            'armv7l': 'virt-2.11',
        }

        caps = self.host.get_domain_capabilities()

        for arch, mtype in archs.items():
            self.assertIn(arch, caps)
            self.assertNotIn('pc', caps[arch])
            self.assertIn(mtype, caps[arch])
            self.assertEqual(mtype, caps[arch][mtype].machine_type)

    def test_get_domain_capabilities_with_versioned_machine_type(self):
        caps = self.host.get_domain_capabilities()

        # i686 supports both an unversioned pc alias and
        # a versioned form.
        i686 = caps['i686']
        self.assertIn('pc', i686)
        self.assertIn('pc-i440fx-2.11', i686)
        # both the versioned and unversioned forms
        # have the unversioned name available as a machine_type_alias
        unversioned_caps = i686['pc']
        self.assertEqual('pc', unversioned_caps.machine_type_alias)
        versioned_caps = i686['pc-i440fx-2.11']
        self.assertEqual('pc', versioned_caps.machine_type_alias)
        # the unversioned_caps and versioned_caps
        # are equal and are actually the same object.
        self.assertEqual(unversioned_caps, versioned_caps)
        self.assertIs(unversioned_caps, versioned_caps)

    @mock.patch.object(fakelibvirt.virConnect, '_domain_capability_features',
                       new='')
    def test_get_domain_capabilities_no_features(self):
        caps = self._test_get_domain_capabilities()
        self.assertEqual(vconfig.LibvirtConfigDomainCaps, type(caps))
        features = caps.features
        self.assertEqual([], features)

    def _test_get_domain_capabilities_sev(self, supported):
        caps = self._test_get_domain_capabilities()
        self.assertEqual(vconfig.LibvirtConfigDomainCaps, type(caps))
        features = caps.features
        self.assertEqual(1, len(features))
        sev = features[0]
        self.assertEqual(vconfig.LibvirtConfigDomainCapsFeatureSev, type(sev))
        self.assertEqual(supported, sev.supported)
        if supported:
            self.assertEqual(47, sev.cbitpos)
            self.assertEqual(1, sev.reduced_phys_bits)

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features', new=
        fakelibvirt.virConnect._domain_capability_features_with_SEV_unsupported
    )
    def test_get_domain_capabilities_sev_unsupported(self):
        self._test_get_domain_capabilities_sev(False)

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def test_get_domain_capabilities_sev_supported(self):
        self._test_get_domain_capabilities_sev(True)

    @mock.patch.object(fakelibvirt.virConnect, "getHostname")
    def test_get_hostname_caching(self, mock_hostname):
        mock_hostname.return_value = "foo"
        self.assertEqual('foo', self.host.get_hostname())
        mock_hostname.assert_called_with()

        mock_hostname.reset_mock()

        mock_hostname.return_value = "bar"
        self.assertEqual('foo', self.host.get_hostname())
        mock_hostname.assert_called_with()

    @mock.patch.object(fakelibvirt.virConnect, "getType")
    def test_get_driver_type(self, mock_type):
        mock_type.return_value = "qemu"
        self.assertEqual("qemu", self.host.get_driver_type())
        mock_type.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virConnect, "getVersion")
    def test_get_version(self, mock_version):
        mock_version.return_value = 1005001
        self.assertEqual(1005001, self.host.get_version())
        mock_version.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virConnect, "secretLookupByUsage")
    def test_find_secret(self, mock_sec):
        """finding secrets with various usage_type."""
        expected = [
            mock.call(fakelibvirt.VIR_SECRET_USAGE_TYPE_CEPH, 'rbdvol'),
            mock.call(fakelibvirt.VIR_SECRET_USAGE_TYPE_CEPH, 'cephvol'),
            mock.call(fakelibvirt.VIR_SECRET_USAGE_TYPE_ISCSI, 'iscsivol'),
            mock.call(fakelibvirt.VIR_SECRET_USAGE_TYPE_VOLUME, 'vol')]

        self.host.find_secret('rbd', 'rbdvol')
        self.host.find_secret('ceph', 'cephvol')
        self.host.find_secret('iscsi', 'iscsivol')
        self.host.find_secret('volume', 'vol')
        self.assertEqual(expected, mock_sec.mock_calls)
        self.assertRaises(exception.NovaException,
                          self.host.find_secret, "foo", "foovol")

        mock_sec.side_effect = fakelibvirt.libvirtError("")
        mock_sec.side_effect.err = (66, )
        self.assertIsNone(self.host.find_secret('rbd', 'rbdvol'))

    @mock.patch.object(fakelibvirt.virConnect, "secretDefineXML")
    def test_create_secret(self, mock_sec):
        """creating secrets with various usage_type."""
        self.host.create_secret('rbd', 'rbdvol')
        self.host.create_secret('ceph', 'cephvol')
        self.host.create_secret('iscsi', 'iscsivol')
        self.host.create_secret('volume', 'vol')
        self.assertRaises(exception.NovaException,
                          self.host.create_secret, "foo", "foovol")

        secret = mock.MagicMock()
        mock_sec.return_value = secret
        self.host.create_secret('iscsi', 'iscsivol', password="foo")
        secret.setValue.assert_called_once_with("foo")

    @mock.patch('nova.virt.libvirt.host.Host.find_secret')
    def test_delete_secret(self, mock_find_secret):
        """deleting secret."""
        secret = mock.MagicMock()
        mock_find_secret.return_value = secret
        expected = [mock.call('rbd', 'rbdvol'),
                    mock.call().undefine()]
        self.host.delete_secret('rbd', 'rbdvol')
        self.assertEqual(expected, mock_find_secret.mock_calls)

        mock_find_secret.return_value = None
        self.host.delete_secret("rbd", "rbdvol")

    def test_get_memory_total(self):
        with mock.patch.object(host.Host, "get_connection") as mock_conn:
            mock_conn().getInfo.return_value = ['zero', 'one', 'two']
            self.assertEqual('one', self.host.get_memory_mb_total())

    def test_get_memory_total_file_backed(self):
        self.flags(file_backed_memory=1048576, group="libvirt")
        self.assertEqual(1048576, self.host.get_memory_mb_total())

    def test_get_memory_used(self):
        m = mock.mock_open(read_data="""
MemTotal:       16194180 kB
MemFree:          233092 kB
MemAvailable:    8892356 kB
Buffers:          567708 kB
Cached:          8362404 kB
SwapCached:            0 kB
Active:          8381604 kB
""")
        with test.nested(
            mock.patch.object(builtins, "open", m, create=True),
            mock.patch.object(host.Host, "get_connection"),
        ) as (mock_file, mock_conn):
            mock_conn().getInfo.return_value = [
                obj_fields.Architecture.X86_64, 15814, 8, 1208, 1, 1, 4, 2]

            self.assertEqual(6866, self.host.get_memory_mb_used())

    def test_sum_domain_memory_mb_xen(self):
        class DiagFakeDomain(object):
            def __init__(self, id, memmb):
                self.id = id
                self.memmb = memmb

            def info(self):
                return [0, 0, self.memmb * 1024]

            def ID(self):
                return self.id

            def name(self):
                return "instance000001"

            def UUIDString(self):
                return uuids.fake

        m = mock.mock_open(read_data="""
MemTotal:       16194180 kB
MemFree:          233092 kB
MemAvailable:    8892356 kB
Buffers:          567708 kB
Cached:          8362404 kB
SwapCached:            0 kB
Active:          8381604 kB
""")

        with test.nested(
                mock.patch.object(six.moves.builtins, "open", m, create=True),
                mock.patch.object(host.Host,
                                  "list_guests"),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  "_conn"),
        ) as (mock_file, mock_list, mock_conn):
            mock_list.return_value = [
                libvirt_guest.Guest(DiagFakeDomain(0, 15814)),
                libvirt_guest.Guest(DiagFakeDomain(1, 750)),
                libvirt_guest.Guest(DiagFakeDomain(2, 1042))]
            mock_conn.getInfo.return_value = [
                obj_fields.Architecture.X86_64, 15814, 8, 1208, 1, 1, 4, 2]

            self.assertEqual(8657, self.host._sum_domain_memory_mb())
            mock_list.assert_called_with(only_guests=False)

    def test_get_memory_used_xen(self):
        self.flags(virt_type='xen', group='libvirt')
        with mock.patch.object(
            self.host, "_sum_domain_memory_mb"
        ) as mock_sumDomainMemory:
            mock_sumDomainMemory.return_value = 8192
            self.assertEqual(8192, self.host.get_memory_mb_used())
            mock_sumDomainMemory.assert_called_once_with(include_host=True)

    def test_sum_domain_memory_mb_file_backed(self):
        class DiagFakeDomain(object):
            def __init__(self, id, memmb):
                self.id = id
                self.memmb = memmb

            def info(self):
                return [0, 0, self.memmb * 1024]

            def ID(self):
                return self.id

            def name(self):
                return "instance000001"

            def UUIDString(self):
                return uuids.fake

        with mock.patch.object(host.Host, 'list_guests') as mock_list:
            mock_list.return_value = [
                libvirt_guest.Guest(DiagFakeDomain(0, 4096)),
                libvirt_guest.Guest(DiagFakeDomain(1, 2048)),
                libvirt_guest.Guest(DiagFakeDomain(2, 1024)),
                libvirt_guest.Guest(DiagFakeDomain(3, 1024))]

            self.assertEqual(8192,
                    self.host._sum_domain_memory_mb(include_host=False))

    def test_get_memory_used_file_backed(self):
        self.flags(file_backed_memory=1048576,
                   group='libvirt')

        with mock.patch.object(
            self.host, "_sum_domain_memory_mb"
        ) as mock_sumDomainMemory:
            mock_sumDomainMemory.return_value = 8192
            self.assertEqual(8192, self.host.get_memory_mb_used())
            mock_sumDomainMemory.assert_called_once_with(include_host=False)

    def test_get_cpu_stats(self):
        stats = self.host.get_cpu_stats()
        self.assertEqual(
            {'kernel': 5664160000000,
             'idle': 1592705190000000,
             'frequency': 800,
             'user': 26728850000000,
             'iowait': 6121490000000},
            stats)

    @mock.patch.object(fakelibvirt.virConnect, "defineXML")
    def test_write_instance_config(self, mock_defineXML):
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
        conn = self.host.get_connection()
        dom = fakelibvirt.Domain(conn,
                                 fake_dom_xml,
                                 False)
        mock_defineXML.return_value = dom
        guest = self.host.write_instance_config(fake_dom_xml)
        mock_defineXML.assert_called_once_with(fake_dom_xml)
        self.assertIsInstance(guest, libvirt_guest.Guest)

    def test_write_instance_config_unicode(self):
        fake_dom_xml = u"""
                <domain type='kvm'>
                  <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                  <devices>
                    <disk type='file'>
                      <source file='\u4e2d\u6587'/>
                    </disk>
                  </devices>
                </domain>
            """

        def emulate_defineXML(xml):
            conn = self.host.get_connection()
            # Emulate the decoding behavior of defineXML in Python2
            if six.PY2:
                xml = xml.decode("utf-8")
            dom = fakelibvirt.Domain(conn, xml, False)
            return dom
        with mock.patch.object(fakelibvirt.virConnect, "defineXML"
                               ) as mock_defineXML:
            mock_defineXML.side_effect = emulate_defineXML
            guest = self.host.write_instance_config(fake_dom_xml)
            self.assertIsInstance(guest, libvirt_guest.Guest)

    @mock.patch.object(fakelibvirt.virConnect, "nodeDeviceLookupByName")
    def test_device_lookup_by_name(self, mock_nodeDeviceLookupByName):
        self.host.device_lookup_by_name("foo")
        mock_nodeDeviceLookupByName.assert_called_once_with("foo")

    def test_list_pci_devices(self):
        with mock.patch.object(self.host, "_list_devices") as mock_listDevices:
            self.host.list_pci_devices(8)
        mock_listDevices.assert_called_once_with('pci', flags=8)

    def test_list_mdev_capable_devices(self):
        with mock.patch.object(self.host, "_list_devices") as mock_listDevices:
            self.host.list_mdev_capable_devices(8)
        mock_listDevices.assert_called_once_with('mdev_types', flags=8)

    def test_list_mediated_devices(self):
        with mock.patch.object(self.host, "_list_devices") as mock_listDevices:
            self.host.list_mediated_devices(8)
        mock_listDevices.assert_called_once_with('mdev', flags=8)

    @mock.patch.object(fakelibvirt.virConnect, "listDevices")
    def test_list_devices(self, mock_listDevices):
        self.host._list_devices('mdev', 8)
        mock_listDevices.assert_called_once_with('mdev', 8)

    @mock.patch.object(fakelibvirt.virConnect, "listDevices")
    def test_list_devices_unsupported(self, mock_listDevices):
        not_supported_exc = fakelibvirt.make_libvirtError(
                fakelibvirt.libvirtError,
                'this function is not supported by the connection driver:'
                ' listDevices',
                error_code=fakelibvirt.VIR_ERR_NO_SUPPORT)
        mock_listDevices.side_effect = not_supported_exc
        self.assertEqual([], self.host._list_devices('mdev', 8))

    @mock.patch.object(fakelibvirt.virConnect, "listDevices")
    def test_list_devices_other_exc(self, mock_listDevices):
        mock_listDevices.side_effect = fakelibvirt.libvirtError('test')
        self.assertRaises(fakelibvirt.libvirtError,
                          self.host._list_devices, 'mdev', 8)

    @mock.patch.object(fakelibvirt.virConnect, "compareCPU")
    def test_compare_cpu(self, mock_compareCPU):
        self.host.compare_cpu("cpuxml")
        mock_compareCPU.assert_called_once_with("cpuxml", 0)

    def test_is_cpu_control_policy_capable_ok(self):
        m = mock.mock_open(
            read_data="""cg /cgroup/cpu,cpuacct cg opt1,cpu,opt3 0 0
cg /cgroup/memory cg opt1,opt2 0 0
""")
        with mock.patch(
                "six.moves.builtins.open", m, create=True):
            self.assertTrue(self.host.is_cpu_control_policy_capable())

    def test_is_cpu_control_policy_capable_ko(self):
        m = mock.mock_open(
            read_data="""cg /cgroup/cpu,cpuacct cg opt1,opt2,opt3 0 0
cg /cgroup/memory cg opt1,opt2 0 0
""")
        with mock.patch(
                "six.moves.builtins.open", m, create=True):
            self.assertFalse(self.host.is_cpu_control_policy_capable())

    @mock.patch('six.moves.builtins.open', side_effect=IOError)
    def test_is_cpu_control_policy_capable_ioerror(self, mock_open):
        self.assertFalse(self.host.is_cpu_control_policy_capable())

    @mock.patch('nova.virt.libvirt.host.libvirt.Connection.getCapabilities')
    def test_has_hyperthreading__true(self, mock_cap):
        mock_cap.return_value = """
        <capabilities>
          <host>
            <uuid>1f71d34a-7c89-45cf-95ce-3df20fc6b936</uuid>
            <cpu>
            </cpu>
            <topology>
              <cells num='1'>
                <cell id='0'>
                  <cpus num='4'>
                    <cpu id='0' socket_id='0' core_id='0' siblings='0,2'/>
                    <cpu id='1' socket_id='0' core_id='1' siblings='1,3'/>
                    <cpu id='2' socket_id='0' core_id='0' siblings='0,2'/>
                    <cpu id='3' socket_id='0' core_id='1' siblings='1,3'/>
                  </cpus>
                </cell>
              </cells>
            </topology>
          </host>
        </capabilities>
        """
        self.assertTrue(self.host.has_hyperthreading)

    @mock.patch('nova.virt.libvirt.host.libvirt.Connection.getCapabilities')
    def test_has_hyperthreading__false(self, mock_cap):
        mock_cap.return_value = """
        <capabilities>
          <host>
            <uuid>1f71d34a-7c89-45cf-95ce-3df20fc6b936</uuid>
            <cpu>
            </cpu>
            <topology>
              <cells num='1'>
                <cell id='0'>
                  <cpus num='4'>
                    <cpu id='0' socket_id='0' core_id='0' siblings='0'/>
                    <cpu id='1' socket_id='0' core_id='1' siblings='1'/>
                    <cpu id='2' socket_id='0' core_id='2' siblings='2'/>
                    <cpu id='3' socket_id='0' core_id='3' siblings='3'/>
                  </cpus>
                </cell>
              </cells>
            </topology>
          </host>
        </capabilities>
        """
        self.assertFalse(self.host.has_hyperthreading)


vc = fakelibvirt.virConnect


class TestLibvirtSEV(test.NoDBTestCase):
    """Libvirt host tests for AMD SEV support."""

    def setUp(self):
        super(TestLibvirtSEV, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")


class TestLibvirtSEVUnsupported(TestLibvirtSEV):
    @mock.patch.object(os.path, 'exists', return_value=False)
    def test_kernel_parameter_missing(self, fake_exists):
        self.assertFalse(self.host._kernel_supports_amd_sev())
        fake_exists.assert_called_once_with(
            '/sys/module/kvm_amd/parameters/sev')

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(builtins, 'open', mock.mock_open(read_data="0\n"))
    def test_kernel_parameter_zero(self, fake_exists):
        self.assertFalse(self.host._kernel_supports_amd_sev())
        fake_exists.assert_called_once_with(
            '/sys/module/kvm_amd/parameters/sev')

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(builtins, 'open', mock.mock_open(read_data="1\n"))
    def test_kernel_parameter_one(self, fake_exists):
        self.assertTrue(self.host._kernel_supports_amd_sev())
        fake_exists.assert_called_once_with(
            '/sys/module/kvm_amd/parameters/sev')

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(builtins, 'open', mock.mock_open(read_data="1\n"))
    def test_unsupported_without_feature(self, fake_exists):
        self.assertFalse(self.host.supports_amd_sev)

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(builtins, 'open', mock.mock_open(read_data="1\n"))
    @mock.patch.object(vc, '_domain_capability_features',
        new=vc._domain_capability_features_with_SEV_unsupported)
    def test_unsupported_with_feature(self, fake_exists):
        self.assertFalse(self.host.supports_amd_sev)


class TestLibvirtSEVSupported(TestLibvirtSEV):
    """Libvirt driver tests for when AMD SEV support is present."""

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(builtins, 'open', mock.mock_open(read_data="1\n"))
    @mock.patch.object(vc, '_domain_capability_features',
                       new=vc._domain_capability_features_with_SEV)
    def test_supported_with_feature(self, fake_exists):
        self.assertTrue(self.host.supports_amd_sev)


class LibvirtTpoolProxyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LibvirtTpoolProxyTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")

        def _stub_xml(uuid):
            return ("<domain>"
                    "  <uuid>" + uuid + "</uuid>"
                    "  <name>" + uuid + "</name>"
                    "</domain>")

        self.conn = self.host.get_connection()
        self.conn.defineXML(_stub_xml(uuids.vm1)).create()
        self.conn.defineXML(_stub_xml(uuids.vm2)).create()

    def test_get_libvirt_proxy_classes(self):
        proxy_classes = host.Host._get_libvirt_proxy_classes(host.libvirt)

        # Assert the classes we're using currently
        # NOTE(mdbooth): We're obviously asserting the wrong classes here
        # because we're explicitly asserting the faked versions. This is a
        # concession to avoid a test dependency on libvirt.
        self.assertIn(fakelibvirt.virDomain, proxy_classes)
        self.assertIn(fakelibvirt.virConnect, proxy_classes)
        self.assertIn(fakelibvirt.virNodeDevice, proxy_classes)
        self.assertIn(fakelibvirt.virSecret, proxy_classes)
        self.assertIn(fakelibvirt.virNWFilter, proxy_classes)

        # Assert that we filtered out libvirtError
        self.assertNotIn(fakelibvirt.libvirtError, proxy_classes)

    def test_tpool_get_connection(self):
        # Test that Host.get_connection() returns a tpool.Proxy
        self.assertIsInstance(self.conn, tpool.Proxy)

    def test_tpool_instance_lookup(self):
        # Test that domains returns by our libvirt connection are also proxied
        dom = self.conn.lookupByUUIDString(uuids.vm1)
        self.assertIsInstance(dom, tpool.Proxy)

    def test_tpool_list_all_connections(self):
        # Test that Host.list_all_connections() returns a list of proxied
        # virDomain objects

        domains = self.host.list_instance_domains()
        self.assertEqual(2, len(domains))
        for domain in domains:
            self.assertIsInstance(domain, tpool.Proxy)
            self.assertIn(domain.UUIDString(), (uuids.vm1, uuids.vm2))
