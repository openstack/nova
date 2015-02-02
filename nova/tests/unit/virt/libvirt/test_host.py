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

import uuid

import eventlet
from eventlet import greenthread
import mock

from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt import event
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import host

try:
    import libvirt
except ImportError:
    libvirt = fakelibvirt
host.libvirt = libvirt


class FakeVirtDomain(object):

    def __init__(self, id=-1, name=None):
        self._id = id
        self._name = name
        self._uuid = str(uuid.uuid4())

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

    @mock.patch.object(fakelibvirt.virConnect, "lookupByID")
    def test_get_domain_by_id(self, fake_lookup):
        dom = fakelibvirt.virDomain(self.host.get_connection(),
                                    "<domain id='7'/>")

        fake_lookup.return_value = dom

        self.assertEqual(dom, self.host._get_domain_by_id(7))

        fake_lookup.assert_called_once_with(7)

    @mock.patch.object(fakelibvirt.virConnect, "lookupByID")
    def test_get_domain_by_id_raises(self, fake_lookup):
        fake_lookup.side_effect = fakelibvirt.make_libvirtError(
            libvirt.libvirtError,
            'Domain not found: no domain with matching id 7',
            error_code=libvirt.VIR_ERR_NO_DOMAIN,
            error_domain=libvirt.VIR_FROM_QEMU)

        self.assertRaises(exception.InstanceNotFound,
                          self.host._get_domain_by_id,
                          7)

        fake_lookup.assert_called_once_with(7)

    @mock.patch.object(fakelibvirt.virConnect, "lookupByName")
    def test_get_domain_by_name(self, fake_lookup):
        dom = fakelibvirt.virDomain(self.host.get_connection(),
                                    "<domain id='7'/>")

        fake_lookup.return_value = dom

        self.assertEqual(dom, self.host._get_domain_by_name("wibble"))

        fake_lookup.assert_called_once_with("wibble")

    @mock.patch.object(fakelibvirt.virConnect, "lookupByName")
    def test_get_domain_by_name_raises(self, fake_lookup):
        fake_lookup.side_effect = fakelibvirt.make_libvirtError(
            libvirt.libvirtError,
            'Domain not found: no domain with matching name',
            error_code=libvirt.VIR_ERR_NO_DOMAIN,
            error_domain=libvirt.VIR_FROM_QEMU)

        self.assertRaises(exception.InstanceNotFound,
                          self.host._get_domain_by_name,
                          "wibble")

        fake_lookup.assert_called_once_with("wibble")

    @mock.patch.object(host.Host, "_get_domain_by_name")
    def test_get_domain(self, fake_get_domain):
        dom = fakelibvirt.virDomain(self.host.get_connection(),
                                    "<domain id='7'/>")

        fake_get_domain.return_value = dom
        instance = objects.Instance(id="124")

        self.assertEqual(dom, self.host.get_domain(instance))

        fake_get_domain.assert_called_once_with("instance-0000007c")

    @mock.patch.object(fakelibvirt.Connection, "listAllDomains")
    def test_list_instance_domains_fast(self, mock_list_all):
        if not hasattr(libvirt, "VIR_CONNECT_LIST_DOMAINS_ACTIVE"):
            self.skipTest("libvirt missing VIR_CONNECT_LIST_DOMAINS_ACTIVE")

        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        def fake_list_all(flags):
            vms = []
            if flags & libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE:
                vms.extend([vm1, vm2])
            if flags & libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE:
                vms.extend([vm3, vm4])
            return vms

        mock_list_all.side_effect = fake_list_all

        doms = self.host._list_instance_domains_fast()

        mock_list_all.assert_called_once_with(
            libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        mock_list_all.reset_mock()

        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())

        doms = self.host._list_instance_domains_fast(only_running=False)

        mock_list_all.assert_called_once_with(
            libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE |
            libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE)

        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())

    @mock.patch.object(fakelibvirt.Connection, "numOfDomains")
    @mock.patch.object(fakelibvirt.Connection, "listDefinedDomains")
    @mock.patch.object(fakelibvirt.Connection, "listDomainsID")
    @mock.patch.object(host.Host, "_get_domain_by_name")
    @mock.patch.object(host.Host, "_get_domain_by_id")
    def test_list_instance_domains_slow(self,
                                        mock_get_id, mock_get_name,
                                        mock_list_ids, mock_list_names,
                                        mock_num_ids):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")
        vms = [vm1, vm2, vm3, vm4]

        def fake_get_domain_by_id(id):
            for vm in vms:
                if vm.ID() == id:
                    return vm
            raise exception.InstanceNotFound(instance_id=id)

        def fake_get_domain_by_name(name):
            for vm in vms:
                if vm.name() == name:
                    return vm
            raise exception.InstanceNotFound(instance_id=name)

        def fake_list_ids():
            # Include one ID that no longer exists
            return [vm1.ID(), vm2.ID(), 666]

        def fake_list_names():
            # Include one name that no longer exists and
            # one dup from running list to show race in
            # transition from inactive -> running
            return [vm1.name(), vm3.name(), vm4.name(), "fishfood"]

        mock_get_id.side_effect = fake_get_domain_by_id
        mock_get_name.side_effect = fake_get_domain_by_name
        mock_list_ids.side_effect = fake_list_ids
        mock_list_names.side_effect = fake_list_names
        mock_num_ids.return_value = 2

        doms = self.host._list_instance_domains_slow()

        mock_list_ids.assert_called_once_with()
        mock_num_ids.assert_called_once_with()
        self.assertFalse(mock_list_names.called)
        mock_list_ids.reset_mock()
        mock_list_names.reset_mock()
        mock_num_ids.reset_mock()

        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())

        doms = self.host._list_instance_domains_slow(only_running=False)

        mock_list_ids.assert_called_once_with()
        mock_num_ids.assert_called_once_with()
        mock_list_names.assert_called_once_with()

        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())

    @mock.patch.object(fakelibvirt.Connection, "listAllDomains")
    @mock.patch.object(fakelibvirt.Connection, "numOfDomains")
    @mock.patch.object(fakelibvirt.Connection, "listDomainsID")
    @mock.patch.object(host.Host, "_get_domain_by_id")
    def test_list_instance_domains_fallback(self,
                                            mock_get_id, mock_list_ids,
                                            mock_num_ids, mock_list_all):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vms = [vm1, vm2]

        def fake_get_domain_by_id(id):
            for vm in vms:
                if vm.ID() == id:
                    return vm
            raise exception.InstanceNotFound(instance_id=id)

        def fake_list_doms():
            return [vm1.ID(), vm2.ID()]

        def fake_list_all(flags):
            ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "API is not supported",
                error_code=libvirt.VIR_ERR_NO_SUPPORT)
            raise ex

        mock_get_id.side_effect = fake_get_domain_by_id
        mock_list_ids.side_effect = fake_list_doms
        mock_num_ids.return_value = 2
        mock_list_all.side_effect = fake_list_all

        doms = self.host.list_instance_domains()

        mock_list_all.assert_called_once_with(
            libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        mock_list_ids.assert_called_once_with()
        mock_num_ids.assert_called_once_with()

        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].ID(), vm1.ID())
        self.assertEqual(doms[1].ID(), vm2.ID())

    @mock.patch.object(host.Host, "_list_instance_domains_fast")
    def test_list_instance_domains_filtering(self, mock_list):
        vm0 = FakeVirtDomain(id=0, name="Domain-0")  # Xen dom-0
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        mock_list.return_value = [vm0, vm1, vm2]
        doms = self.host.list_instance_domains()
        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        mock_list.assert_called_with(True)

        mock_list.return_value = [vm0, vm1, vm2, vm3, vm4]
        doms = self.host.list_instance_domains(only_running=False)
        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())
        mock_list.assert_called_with(False)

        mock_list.return_value = [vm0, vm1, vm2]
        doms = self.host.list_instance_domains(only_guests=False)
        self.assertEqual(len(doms), 3)
        self.assertEqual(doms[0].name(), vm0.name())
        self.assertEqual(doms[1].name(), vm1.name())
        self.assertEqual(doms[2].name(), vm2.name())
        mock_list.assert_called_with(True)

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
        # `mock` has trouble stubbing attributes that don't exist yet, so
        # fallback to plain-Python attribute setting/deleting
        cap_str = 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'
        if not hasattr(host.libvirt, cap_str):
            setattr(host.libvirt, cap_str, True)
            self.addCleanup(delattr, host.libvirt, cap_str)

        # Handle just the NO_SUPPORT error
        not_supported_exc = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                'this function is not supported by the connection driver:'
                ' virConnectBaselineCPU',
                error_code=libvirt.VIR_ERR_NO_SUPPORT)

        with mock.patch.object(fakelibvirt.virConnect, 'baselineCPU',
                               side_effect=not_supported_exc):
            caps = self.host.get_capabilities()
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Clear cached result so we can test again...
        self.host._caps = None

        # Other errors should not be caught
        other_exc = fakelibvirt.make_libvirtError(
            libvirt.libvirtError,
            'other exc',
            error_code=libvirt.VIR_ERR_NO_DOMAIN)

        with mock.patch.object(fakelibvirt.virConnect, 'baselineCPU',
                               side_effect=other_exc):
            self.assertRaises(libvirt.libvirtError,
                              self.host.get_capabilities)

    def test_lxc_get_host_capabilities_failed(self):
        with mock.patch.object(fakelibvirt.virConnect, 'baselineCPU',
                               return_value=-1):
            setattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES', 1)
            caps = self.host.get_capabilities()
            delattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES')
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

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
            mock.call(libvirt.VIR_SECRET_USAGE_TYPE_CEPH, 'rbdvol'),
            mock.call(libvirt.VIR_SECRET_USAGE_TYPE_CEPH, 'cephvol'),
            mock.call(libvirt.VIR_SECRET_USAGE_TYPE_ISCSI, 'iscsivol'),
            mock.call(libvirt.VIR_SECRET_USAGE_TYPE_VOLUME, 'vol')]

        self.host.find_secret('rbd', 'rbdvol')
        self.host.find_secret('ceph', 'cephvol')
        self.host.find_secret('iscsi', 'iscsivol')
        self.host.find_secret('volume', 'vol')
        self.assertEqual(expected, mock_sec.mock_calls)
        self.assertRaises(exception.NovaException,
                          self.host.find_secret, "foo", "foovol")

        mock_sec.side_effect = libvirt.libvirtError("")
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
