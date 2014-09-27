#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
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

import contextlib
import copy
import errno
import eventlet
import fixtures
import functools
import mox
import os
import re
import shutil
import tempfile

from eventlet import greenthread
from lxml import etree
import mock
from oslo.config import cfg
from xml.dom import minidom

from nova.api.ec2 import cloud
from nova.compute import flavors
from nova.compute import manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.network import model as network_model
from nova.objects import flavor as flavor_obj
from nova.objects import instance as instance_obj
from nova.objects import pci_device as pci_device_obj
from nova.objects import service as service_obj
from nova.openstack.common import fileutils
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import loopingcall
from nova.openstack.common import processutils
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova.pci import pci_manager
from nova import test
from nova.tests import fake_block_device
from nova.tests import fake_instance
from nova.tests import fake_network
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests.objects import test_pci_device
from nova.tests.virt.libvirt import fake_libvirt_utils
from nova.tests.virt.libvirt import fakelibvirt
from nova import utils
from nova import version
from nova.virt import configdrive
from nova.virt.disk import api as disk
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import fake
from nova.virt import firewall as base_firewall
from nova.virt import images
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import firewall
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt import netutils

try:
    import libvirt
except ImportError:
    import nova.tests.virt.libvirt.fakelibvirt as libvirt
libvirt_driver.libvirt = libvirt


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('instances_path', 'nova.compute.manager')

_fake_network_info = fake_network.fake_get_instance_nw_info
_fake_stub_out_get_nw_info = fake_network.stub_out_nw_api_get_instance_nw_info
_ipv4_like = fake_network.ipv4_like

_fake_NodeDevXml = \
    {"pci_0000_04_00_3": """
        <device>
        <name>pci_0000_04_00_3</name>
        <parent>pci_0000_00_01_1</parent>
        <driver>
            <name>igb</name>
        </driver>
        <capability type='pci'>
            <domain>0</domain>
            <bus>4</bus>
            <slot>0</slot>
            <function>3</function>
            <product id='0x1521'>I350 Gigabit Network Connection</product>
            <vendor id='0x8086'>Intel Corporation</vendor>
            <capability type='virt_functions'>
              <address domain='0x0000' bus='0x04' slot='0x10' function='0x3'/>
              <address domain='0x0000' bus='0x04' slot='0x10' function='0x7'/>
              <address domain='0x0000' bus='0x04' slot='0x11' function='0x3'/>
              <address domain='0x0000' bus='0x04' slot='0x11' function='0x7'/>
            </capability>
        </capability>
      </device>""",
    "pci_0000_04_10_7": """
      <device>
         <name>pci_0000_04_10_7</name>
         <parent>pci_0000_00_01_1</parent>
         <driver>
         <name>igbvf</name>
         </driver>
         <capability type='pci'>
          <domain>0</domain>
          <bus>4</bus>
          <slot>16</slot>
          <function>7</function>
       <product id='0x1520'>I350 Ethernet Controller Virtual Function</product>
          <vendor id='0x8086'>Intel Corporation</vendor>
          <capability type='phys_function'>
             <address domain='0x0000' bus='0x04' slot='0x00' function='0x3'/>
          </capability>
          <capability type='virt_functions'>
          </capability>
        </capability>
    </device>"""}


def mocked_bdm(id, bdm_info):
    bdm_mock = mock.MagicMock()
    bdm_mock.__getitem__ = lambda s, k: bdm_info[k]
    bdm_mock.get = lambda *k, **kw: bdm_info.get(*k, **kw)
    bdm_mock.id = id
    return bdm_mock


def _concurrency(signal, wait, done, target, is_block_dev=False):
    signal.send()
    wait.wait()
    done.send()


class FakeVirDomainSnapshot(object):

    def __init__(self, dom=None):
        self.dom = dom

    def delete(self, flags):
        pass


class FakeVirtDomain(object):

    def __init__(self, fake_xml=None, uuidstr=None):
        self.uuidstr = uuidstr
        if fake_xml:
            self._fake_dom_xml = fake_xml
        else:
            self._fake_dom_xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                    </devices>
                </domain>
            """

    def name(self):
        return "fake-domain %s" % self

    def info(self):
        return [power_state.RUNNING, None, None, None, None]

    def create(self):
        pass

    def managedSave(self, *args):
        pass

    def createWithFlags(self, launch_flags):
        pass

    def XMLDesc(self, *args):
        return self._fake_dom_xml

    def UUIDString(self):
        return self.uuidstr

    def attachDeviceFlags(self, xml, flags):
        pass

    def detachDeviceFlags(self, xml, flags):
        pass

    def snapshotCreateXML(self, xml, flags):
        pass

    def blockCommit(self, disk, base, top, bandwidth=0, flags=0):
        pass

    def blockRebase(self, disk, base, bandwidth=0, flags=0):
        pass

    def blockJobInfo(self, path, flags):
        pass

    def resume(self):
        pass


class CacheConcurrencyTestCase(test.TestCase):
    def setUp(self):
        super(CacheConcurrencyTestCase, self).setUp()

        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)

        # utils.synchronized() will create the lock_path for us if it
        # doesn't already exist. It will also delete it when it's done,
        # which can cause race conditions with the multiple threads we
        # use for tests. So, create the path here so utils.synchronized()
        # won't delete it out from under one of the threads.
        self.lock_path = os.path.join(CONF.instances_path, 'locks')
        fileutils.ensure_tree(self.lock_path)

        def fake_exists(fname):
            basedir = os.path.join(CONF.instances_path,
                                   CONF.image_cache_subdirectory_name)
            if fname == basedir or fname == self.lock_path:
                return True
            return False

        def fake_execute(*args, **kwargs):
            pass

        def fake_extend(image, size, use_cow=False):
            pass

        self.stubs.Set(os.path, 'exists', fake_exists)
        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(imagebackend.disk, 'extend', fake_extend)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.libvirt_utils',
            fake_libvirt_utils))

    def test_same_fname_concurrency(self):
        # Ensures that the same fname cache runs at a sequentially.
        uuid = uuidutils.generate_uuid()

        backend = imagebackend.Backend(False)
        wait1 = eventlet.event.Event()
        done1 = eventlet.event.Event()
        sig1 = eventlet.event.Event()
        thr1 = eventlet.spawn(backend.image({'name': 'instance',
                                             'uuid': uuid},
                                            'name').cache,
                _concurrency, 'fname', None,
                signal=sig1, wait=wait1, done=done1)
        eventlet.sleep(0)
        # Thread 1 should run before thread 2.
        sig1.wait()

        wait2 = eventlet.event.Event()
        done2 = eventlet.event.Event()
        sig2 = eventlet.event.Event()
        thr2 = eventlet.spawn(backend.image({'name': 'instance',
                                             'uuid': uuid},
                                            'name').cache,
                _concurrency, 'fname', None,
                signal=sig2, wait=wait2, done=done2)

        wait2.send()
        eventlet.sleep(0)
        try:
            self.assertFalse(done2.ready())
        finally:
            wait1.send()
        done1.wait()
        eventlet.sleep(0)
        self.assertTrue(done2.ready())
        # Wait on greenthreads to assert they didn't raise exceptions
        # during execution
        thr1.wait()
        thr2.wait()

    def test_different_fname_concurrency(self):
        # Ensures that two different fname caches are concurrent.
        uuid = uuidutils.generate_uuid()

        backend = imagebackend.Backend(False)
        wait1 = eventlet.event.Event()
        done1 = eventlet.event.Event()
        sig1 = eventlet.event.Event()
        thr1 = eventlet.spawn(backend.image({'name': 'instance',
                                             'uuid': uuid},
                                            'name').cache,
                _concurrency, 'fname2', None,
                signal=sig1, wait=wait1, done=done1)
        eventlet.sleep(0)
        # Thread 1 should run before thread 2.
        sig1.wait()

        wait2 = eventlet.event.Event()
        done2 = eventlet.event.Event()
        sig2 = eventlet.event.Event()
        thr2 = eventlet.spawn(backend.image({'name': 'instance',
                                             'uuid': uuid},
                                            'name').cache,
                _concurrency, 'fname1', None,
                signal=sig2, wait=wait2, done=done2)
        eventlet.sleep(0)
        # Wait for thread 2 to start.
        sig2.wait()

        wait2.send()
        tries = 0
        while not done2.ready() and tries < 10:
            eventlet.sleep(0)
            tries += 1
        try:
            self.assertTrue(done2.ready())
        finally:
            wait1.send()
            eventlet.sleep(0)
        # Wait on greenthreads to assert they didn't raise exceptions
        # during execution
        thr1.wait()
        thr2.wait()


class FakeVolumeDriver(object):
    def __init__(self, *args, **kwargs):
        pass

    def attach_volume(self, *args):
        pass

    def detach_volume(self, *args):
        pass

    def get_xml(self, *args):
        return ""

    def connect_volume(self, *args):
        """Connect the volume to a fake device."""
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_type = "network"
        conf.source_protocol = "fake"
        conf.source_name = "fake"
        conf.target_dev = "fake"
        conf.target_bus = "fake"
        return conf


class FakeConfigGuestDisk(object):
    def __init__(self, *args, **kwargs):
        self.source_type = None
        self.driver_cache = None


class FakeConfigGuest(object):
    def __init__(self, *args, **kwargs):
        self.driver_cache = None


class FakeNodeDevice(object):
    def __init__(self, fakexml):
        self.xml = fakexml

    def XMLDesc(self, *args):
        return self.xml


class LibvirtConnTestCase(test.TestCase):

    def setUp(self):
        super(LibvirtConnTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.flags(fake_call=True)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.get_admin_context()
        temp_dir = self.useFixture(fixtures.TempDir()).path
        self.flags(instances_path=temp_dir)
        self.flags(snapshots_directory=temp_dir, group='libvirt')
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.libvirt_utils',
            fake_libvirt_utils))
        # Force libvirt to return a host UUID that matches the serial in
        # nova.tests.fakelibvirt. This is necessary because the host UUID
        # returned by libvirt becomes the serial whose value is checked for in
        # test_xml_and_uri_* below.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.LibvirtDriver.get_host_uuid',
            lambda _: 'cef19ce0-0ca2-11df-855d-b19fbce37686'))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.libvirt_utils',
            fake_libvirt_utils))

        def fake_extend(image, size, use_cow=False):
            pass

        self.stubs.Set(libvirt_driver.disk, 'extend', fake_extend)

        self.stubs.Set(imagebackend.Image, 'resolve_driver_format',
                       imagebackend.Image._get_driver_format)

        class FakeConn():
            def baselineCPU(self, cpu, flag):
                """Add new libvirt API."""
                return """<cpu mode='custom' match='exact'>
                            <model fallback='allow'>Westmere</model>
                            <vendor>Intel</vendor>
                            <feature policy='require' name='aes'/>
                          </cpu>"""

            def getCapabilities(self):
                """Ensure standard capabilities being returned."""
                return """<capabilities>
                            <host><cpu><arch>x86_64</arch></cpu></host>
                          </capabilities>"""

            def getVersion(self):
                return 1005001

            def getLibVersion(self):
                return (0 * 1000 * 1000) + (9 * 1000) + 11

            def domainEventRegisterAny(self, *args, **kwargs):
                pass

            def registerCloseCallback(self, cb, opaque):
                pass

            def nwfilterDefineXML(self, *args, **kwargs):
                pass

            def nodeDeviceLookupByName(self, x):
                pass

            def lookupByName(self, name):
                pass

        self.conn = FakeConn()
        self.stubs.Set(libvirt_driver.LibvirtDriver, '_connect',
                       lambda *a, **k: self.conn)

        flavor = db.flavor_get(self.context, 5)
        sys_meta = flavors.save_flavor_info({}, flavor)

        nova.tests.image.fake.stub_out_image_service(self.stubs)
        self.test_instance = {
                'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
                'memory_kb': '1024000',
                'basepath': '/some/path',
                'bridge_name': 'br100',
                'vcpus': 2,
                'project_id': 'fake',
                'bridge': 'br101',
                'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'root_gb': 10,
                'ephemeral_gb': 20,
                'instance_type_id': '5',  # m1.small
                'extra_specs': {},
                'system_metadata': sys_meta,
                "pci_devices": []}

    def relpath(self, path):
        return os.path.relpath(path, CONF.instances_path)

    def tearDown(self):
        nova.tests.image.fake.FakeImageService_reset()
        super(LibvirtConnTestCase, self).tearDown()

    def create_fake_libvirt_mock(self, **kwargs):
        """Defining mocks for LibvirtDriver(libvirt is not used)."""

        # A fake libvirt.virConnect
        class FakeLibvirtDriver(object):
            def defineXML(self, xml):
                return FakeVirtDomain()

        # Creating mocks
        volume_driver = ('iscsi=nova.tests.virt.libvirt.test_libvirt'
                         '.FakeVolumeDriver')
        self.flags(volume_drivers=[volume_driver],
                   group='libvirt')
        fake = FakeLibvirtDriver()
        # Customizing above fake if necessary
        for key, val in kwargs.items():
            fake.__setattr__(key, val)

        self.flags(vif_driver="nova.tests.fake_network.FakeVIFDriver",
                   group='libvirt')

        self.stubs.Set(libvirt_driver.LibvirtDriver, '_conn', fake)

    def fake_lookup(self, instance_name):
        return FakeVirtDomain()

    def fake_execute(self, *args, **kwargs):
        open(args[-1], "a").close()

    def _create_service(self, **kwargs):
        service_ref = {'host': kwargs.get('host', 'dummy'),
                       'disabled': kwargs.get('disabled', False),
                       'binary': 'nova-compute',
                       'topic': 'compute',
                       'report_count': 0}

        return db.service_create(context.get_admin_context(), service_ref)

    def _get_host_disabled(self, host):
        return db.service_get_by_compute_host(context.get_admin_context(),
                                              host)['disabled']

    def test_set_host_enabled_with_disable(self):
        # Tests disabling an enabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self._create_service(host='fake-mini')
        conn._set_host_enabled(False)
        self.assertTrue(self._get_host_disabled('fake-mini'))

    def test_set_host_enabled_with_enable(self):
        # Tests enabling a disabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self._create_service(disabled=True, host='fake-mini')
        conn._set_host_enabled(True)
        self.assertTrue(self._get_host_disabled('fake-mini'))

    def test_set_host_enabled_with_enable_state_enabled(self):
        # Tests enabling an enabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self._create_service(disabled=False, host='fake-mini')
        conn._set_host_enabled(True)
        self.assertFalse(self._get_host_disabled('fake-mini'))

    def test_set_host_enabled_with_disable_state_disabled(self):
        # Tests disabling a disabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self._create_service(disabled=True, host='fake-mini')
        conn._set_host_enabled(False)
        self.assertTrue(self._get_host_disabled('fake-mini'))

    def test_set_host_enabled_swallows_exceptions(self):
        # Tests that set_host_enabled will swallow exceptions coming from the
        # db_api code so they don't break anything calling it, e.g. the
        # _get_new_connection method.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        with mock.patch.object(db, 'service_get_by_compute_host') as db_mock:
            # Make db.service_get_by_compute_host raise NovaException; this
            # is more robust than just raising ComputeHostNotFound.
            db_mock.side_effect = exception.NovaException
            conn._set_host_enabled(False)

    def create_instance_obj(self, context, **params):
        default_params = self.test_instance
        default_params['pci_devices'] = pci_device_obj.PciDeviceList()
        default_params.update(params)
        instance = instance_obj.Instance(context, **params)
        instance.create()
        return instance

    def test_prepare_pci_device(self):

        pci_devices = [dict(hypervisor_name='xxx')]

        self.flags(virt_type='xen', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        class FakeDev():
            def attach(self):
                pass

            def dettach(self):
                pass

            def reset(self):
                pass

        self.mox.StubOutWithMock(self.conn, 'nodeDeviceLookupByName')
        self.conn.nodeDeviceLookupByName('xxx').AndReturn(FakeDev())
        self.conn.nodeDeviceLookupByName('xxx').AndReturn(FakeDev())
        self.mox.ReplayAll()
        conn._prepare_pci_devices_for_use(pci_devices)

    def test_prepare_pci_device_exception(self):

        pci_devices = [dict(hypervisor_name='xxx',
                            id='id1',
                            instance_uuid='uuid')]

        self.flags(virt_type='xen', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        class FakeDev():

            def attach(self):
                pass

            def dettach(self):
                raise libvirt.libvirtError("xxxxx")

            def reset(self):
                pass

        self.stubs.Set(self.conn, 'nodeDeviceLookupByName',
                       lambda x: FakeDev())
        self.assertRaises(exception.PciDevicePrepareFailed,
                         conn._prepare_pci_devices_for_use, pci_devices)

    def test_detach_pci_devices_exception(self):

        pci_devices = [dict(hypervisor_name='xxx',
                            id='id1',
                            instance_uuid='uuid')]

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'has_min_version')
        libvirt_driver.LibvirtDriver.has_min_version = lambda x, y: False

        self.assertRaises(exception.PciDeviceDetachFailed,
                          conn._detach_pci_devices, None, pci_devices)

    def test_detach_pci_devices(self):

        fake_domXML1 =\
            """<domain> <devices>
              <hostdev mode="subsystem" type="pci" managed="yes">
                <source>
            <address function="0x1" slot="0x10" domain="0x0000" bus="0x04"/>
                </source>
            </hostdev></devices></domain>"""

        pci_devices = [dict(hypervisor_name='xxx',
                            id='id1',
                            instance_uuid='uuid',
                            address="0001:04:10:1")]

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'has_min_version')
        libvirt_driver.LibvirtDriver.has_min_version = lambda x, y: True

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'get_guest_pci_device')

        class FakeDev():
            def to_xml(self):
                pass

        libvirt_driver.LibvirtDriver.get_guest_pci_device =\
            lambda x, y: FakeDev()

        class FakeDomain():
            def detachDeviceFlags(self, xml, flag):
                pci_devices[0]['hypervisor_name'] = 'marked'
                pass

            def XMLDesc(self, flag):
                return fake_domXML1

        conn._detach_pci_devices(FakeDomain(), pci_devices)
        self.assertEqual(pci_devices[0]['hypervisor_name'], 'marked')

    def test_detach_pci_devices_timeout(self):

        fake_domXML1 =\
            """<domain>
                <devices>
                  <hostdev mode="subsystem" type="pci" managed="yes">
                    <source>
            <address function="0x1" slot="0x10" domain="0x0000" bus="0x04"/>
                    </source>
                  </hostdev>
                </devices>
            </domain>"""

        pci_devices = [dict(hypervisor_name='xxx',
                            id='id1',
                            instance_uuid='uuid',
                            address="0000:04:10:1")]

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'has_min_version')
        libvirt_driver.LibvirtDriver.has_min_version = lambda x, y: True

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'get_guest_pci_device')

        class FakeDev():
            def to_xml(self):
                pass

        libvirt_driver.LibvirtDriver.get_guest_pci_device =\
            lambda x, y: FakeDev()

        class FakeDomain():
            def detachDeviceFlags(self, xml, flag):
                pass

            def XMLDesc(self, flag):
                return fake_domXML1
        self.assertRaises(exception.PciDeviceDetachFailed,
                          conn._detach_pci_devices, FakeDomain(), pci_devices)

    def test_get_connector(self):
        initiator = 'fake.initiator.iqn'
        ip = 'fakeip'
        host = 'fakehost'
        wwpns = ['100010604b019419']
        wwnns = ['200010604b019419']
        self.flags(my_ip=ip)
        self.flags(host=host)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        expected = {
            'ip': ip,
            'initiator': initiator,
            'host': host,
            'wwpns': wwpns,
            'wwnns': wwnns
        }
        volume = {
            'id': 'fake'
        }
        result = conn.get_volume_connector(volume)
        self.assertThat(expected, matchers.DictMatches(result))

    def test_lifecycle_event_registration(self):
        calls = []

        def fake_registerErrorHandler(*args, **kwargs):
            calls.append('fake_registerErrorHandler')

        def fake_get_host_capabilities(**args):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = "armv7l"

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            calls.append('fake_get_host_capabilities')
            return caps

        @mock.patch.object(libvirt, 'registerErrorHandler',
                           side_effect=fake_registerErrorHandler)
        @mock.patch.object(libvirt_driver.LibvirtDriver,
                           'get_host_capabilities',
                            side_effect=fake_get_host_capabilities)
        def test_init_host(get_host_capabilities, register_error_handler):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
            conn.init_host("test_host")

        test_init_host()
        # NOTE(dkliban): Will fail if get_host_capabilities is called before
        # registerErrorHandler
        self.assertEqual(['fake_registerErrorHandler',
                          'fake_get_host_capabilities'], calls)

    def test_sanitize_log_to_xml(self):
        # setup fake data
        data = {'auth_password': 'scrubme'}
        bdm = [{'connection_info': {'data': data}}]
        bdi = {'block_device_mapping': bdm}

        # Tests that the parameters to the to_xml method are sanitized for
        # passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.assertNotIn('scrubme', args[0])

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conf = mock.Mock()
        with contextlib.nested(
            mock.patch.object(libvirt_driver.LOG, 'debug',
                              side_effect=fake_debug),
            mock.patch.object(conn, 'get_guest_config', return_value=conf)
        ) as (
            debug_mock, conf_mock
        ):
            conn.to_xml(self.context, self.test_instance, network_info={},
                        disk_info={}, image_meta={}, block_device_info=bdi)
            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)

    def test_close_callback(self):
        self.close_callback = None

        def set_close_callback(cb, opaque):
            self.close_callback = cb

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = False
        with contextlib.nested(
            mock.patch.object(conn, "_connect", return_value=self.conn),
            mock.patch.object(self.conn, "registerCloseCallback",
                              side_effect=set_close_callback),
            mock.patch.object(service_obj.Service, "get_by_compute_host",
                              return_value=service_mock)):

            # verify that the driver registers for the close callback
            # and re-connects after receiving the callback
            conn._get_connection()
            self.assertFalse(service_mock.disabled)
            self.assertTrue(self.close_callback)
            conn._init_events_pipe()
            self.close_callback(self.conn, 1, None)
            conn._dispatch_events()

            self.assertTrue(service_mock.disabled)
            conn._get_connection()

    def test_close_callback_bad_signature(self):
        '''Validates that a connection to libvirt exist,
           even when registerCloseCallback method has a different
           number of arguments in the libvirt python library.
        '''
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = False
        with contextlib.nested(
            mock.patch.object(conn, "_connect", return_value=self.conn),
            mock.patch.object(self.conn, "registerCloseCallback",
                              side_effect=TypeError('dd')),
            mock.patch.object(service_obj.Service, "get_by_compute_host",
                              return_value=service_mock)):

            connection = conn._get_connection()
            self.assertTrue(connection)

    def test_close_callback_not_defined(self):
        '''Validates that a connection to libvirt exist,
           even when registerCloseCallback method missing from
           the libvirt python library.
        '''
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = False
        with contextlib.nested(
            mock.patch.object(conn, "_connect", return_value=self.conn),
            mock.patch.object(self.conn, "registerCloseCallback",
                              side_effect=AttributeError('dd')),
            mock.patch.object(service_obj.Service, "get_by_compute_host",
                              return_value=service_mock)):

            connection = conn._get_connection()
            self.assertTrue(connection)

    def test_cpu_features_bug_1217630(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        # Test old version of libvirt, it shouldn't see the `aes' feature
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            del mock_libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES
            caps = conn.get_host_capabilities()
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Test new verion of libvirt, should find the `aes' feature
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            mock_libvirt['VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'] = 1
            # Cleanup the capabilities cache firstly
            conn._caps = None
            caps = conn.get_host_capabilities()
            self.assertIn('aes', [x.name for x in caps.host.cpu.features])

    def test_lxc_get_host_capabilities_failed(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        with mock.patch.object(conn._conn, 'baselineCPU', return_value=-1):
            setattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES', 1)
            caps = conn.get_host_capabilities()
            delattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES')
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

    def test_get_guest_config(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    None, disk_info)
        self.assertEqual(cfg.uuid, instance_ref["uuid"])
        self.assertEqual(cfg.acpi, True)
        self.assertEqual(cfg.apic, True)
        self.assertEqual(cfg.memory, 2 * units.Mi)
        self.assertEqual(cfg.vcpus, 1)
        self.assertEqual(cfg.os_type, vm_mode.HVM)
        self.assertEqual(cfg.os_boot_dev, ["hd"])
        self.assertIsNone(cfg.os_root)
        self.assertEqual(len(cfg.devices), 8)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestInterface)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestVideo)

    def test_get_guest_config_clock(self):
        self.flags(virt_type='kvm', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {}
        hpet_map = {
            "x86_64": True,
            "i686": True,
            "ppc": False,
            "ppc64": False,
            "armv7": False,
            "aarch64": False,
            }

        for arch, expect_hpet in hpet_map.items():
            with mock.patch.object(libvirt_driver.libvirt_utils,
                                   'get_arch',
                                   return_value=arch):
                cfg = conn.get_guest_config(instance_ref, [],
                                            image_meta,
                                            disk_info)
                self.assertIsInstance(cfg.clock,
                                      vconfig.LibvirtConfigGuestClock)
                self.assertEqual(cfg.clock.offset, "utc")
                self.assertIsInstance(cfg.clock.timers[0],
                                      vconfig.LibvirtConfigGuestTimer)
                self.assertIsInstance(cfg.clock.timers[1],
                                      vconfig.LibvirtConfigGuestTimer)
                self.assertEqual(cfg.clock.timers[0].name, "pit")
                self.assertEqual(cfg.clock.timers[0].tickpolicy,
                                      "delay")
                self.assertEqual(cfg.clock.timers[1].name, "rtc")
                self.assertEqual(cfg.clock.timers[1].tickpolicy,
                                      "catchup")
                if expect_hpet:
                    self.assertEqual(3, len(cfg.clock.timers))
                    self.assertIsInstance(cfg.clock.timers[2],
                                          vconfig.LibvirtConfigGuestTimer)
                    self.assertEqual('hpet', cfg.clock.timers[2].name)
                    self.assertFalse(cfg.clock.timers[2].present)
                else:
                    self.assertEqual(2, len(cfg.clock.timers))

    def test_get_guest_config_windows(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)
        instance_ref['os_type'] = 'windows'

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    None, disk_info)

        self.assertIsInstance(cfg.clock,
                              vconfig.LibvirtConfigGuestClock)
        self.assertEqual(cfg.clock.offset, "localtime")

    def test_get_guest_config_with_two_nics(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 2),
                                    None, disk_info)
        self.assertEqual(cfg.acpi, True)
        self.assertEqual(cfg.memory, 2 * units.Mi)
        self.assertEqual(cfg.vcpus, 1)
        self.assertEqual(cfg.os_type, vm_mode.HVM)
        self.assertEqual(cfg.os_boot_dev, ["hd"])
        self.assertIsNone(cfg.os_root)
        self.assertEqual(len(cfg.devices), 9)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestInterface)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestInterface)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigGuestVideo)

    def test_get_guest_config_bug_1118829(self):
        self.flags(virt_type='uml', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = {'disk_bus': 'virtio',
                     'cdrom_bus': 'ide',
                     'mapping': {u'vda': {'bus': 'virtio',
                                          'type': 'disk',
                                          'dev': u'vda'},
                                 'root': {'bus': 'virtio',
                                          'type': 'disk',
                                          'dev': 'vda'}}}

        # NOTE(jdg): For this specific test leave this blank
        # This will exercise the failed code path still,
        # and won't require fakes and stubs of the iscsi discovery
        block_device_info = {}
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info,
                                    None, block_device_info)
        instance_ref = db.instance_get(self.context, instance_ref['id'])
        self.assertEqual(instance_ref['root_device_name'], '/dev/vda')

    def test_get_guest_config_with_root_device_name(self):
        self.flags(virt_type='uml', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        block_device_info = {'root_device_name': '/dev/vdb'}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref,
                                            block_device_info)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info,
                                    None, block_device_info)
        self.assertEqual(cfg.acpi, False)
        self.assertEqual(cfg.memory, 2 * units.Mi)
        self.assertEqual(cfg.vcpus, 1)
        self.assertEqual(cfg.os_type, "uml")
        self.assertEqual(cfg.os_boot_dev, [])
        self.assertEqual(cfg.os_root, '/dev/vdb')
        self.assertEqual(len(cfg.devices), 3)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestConsole)

    def test_get_guest_config_with_block_device(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = db.instance_create(self.context, self.test_instance)
        conn_info = {'driver_volume_type': 'fake'}
        info = {'block_device_mapping': [
                mocked_bdm(1, {'connection_info': conn_info,
                               'mount_device': '/dev/vdc'}),
                mocked_bdm(2, {'connection_info': conn_info,
                               'mount_device': '/dev/vdd'}),
                ]}

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, info)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info,
                                    None, info)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[2].target_dev, 'vdc')
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[3].target_dev, 'vdd')
        self.assertTrue(info['block_device_mapping'][0].save.called)
        self.assertTrue(info['block_device_mapping'][1].save.called)

    def test_get_guest_config_with_configdrive(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        # make configdrive.required_by() return True
        instance_ref['config_drive'] = True

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)

        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[2].target_dev, 'hdd')

    def test_get_guest_config_with_virtio_scsi_bus(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        image_meta = {"properties": {"hw_scsi_model": "virtio-scsi"}}
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, [], image_meta)
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertIsInstance(cfg.devices[0],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                         vconfig.LibvirtConfigGuestController)
        self.assertEqual(cfg.devices[2].model, 'virtio-scsi')

    def test_get_guest_config_with_virtio_scsi_bus_bdm(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        image_meta = {"properties": {"hw_scsi_model": "virtio-scsi"}}
        instance_ref = db.instance_create(self.context, self.test_instance)
        conn_info = {'driver_volume_type': 'fake'}
        bd_info = {'block_device_mapping': [
                mocked_bdm(1, {'connection_info': conn_info,
                               'mount_device': '/dev/sdc',
                               'disk_bus': 'scsi'}),
                mocked_bdm(2, {'connection_info': conn_info,
                               'mount_device': '/dev/sdd',
                               'disk_bus': 'scsi'}),
                ]}

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, bd_info, image_meta)
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info,
                                    [], bd_info)
        self.assertIsInstance(cfg.devices[2],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[2].target_dev, 'sdc')
        self.assertEqual(cfg.devices[2].target_bus, 'scsi')
        self.assertIsInstance(cfg.devices[3],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[3].target_dev, 'sdd')
        self.assertEqual(cfg.devices[3].target_bus, 'scsi')
        self.assertIsInstance(cfg.devices[4],
                         vconfig.LibvirtConfigGuestController)
        self.assertEqual(cfg.devices[4].model, 'virtio-scsi')

    def test_get_guest_config_with_vnc(self):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False, group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 6)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].type, "vnc")

    def test_get_guest_config_with_vnc_and_tablet(self):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=False, group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 7)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")

    def test_get_guest_config_with_spice_and_tablet(self):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 7)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "spice")

    def test_get_guest_config_with_spice_and_agent(self):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 7)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestChannel)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].target_name, "com.redhat.spice.0")
        self.assertEqual(cfg.devices[5].type, "spice")
        self.assertEqual(cfg.devices[6].type, "qxl")

    def test_get_guest_config_with_type_xen(self):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='xen',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 5)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestConsole)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[3].type, "vnc")
        self.assertEqual(cfg.devices[4].type, "xen")

    def test_get_guest_config_with_vnc_and_spice(self):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        self.assertEqual(len(cfg.devices), 9)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestChannel)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].target_name, "com.redhat.spice.0")
        self.assertEqual(cfg.devices[6].type, "vnc")
        self.assertEqual(cfg.devices[7].type, "spice")

    def test_invalid_watchdog_action(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_watchdog_action": "something"}}
        self.assertRaises(exception.InvalidWatchdogAction,
                          conn.get_guest_config,
                          instance_ref,
                          [],
                          image_meta,
                          disk_info)

    def test_get_guest_config_with_watchdog_action_through_image_meta(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_watchdog_action": "none"}}
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertEqual(len(cfg.devices), 8)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestWatchdog)

        self.assertEqual("none", cfg.devices[7].action)

    def test_get_guest_config_with_watchdog_action_through_flavor(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        flavor = db.flavor_get(self.context,
                               self.test_instance['instance_type_id'])
        db.flavor_extra_specs_update_or_create(
                self.context,
                flavor['flavorid'],
                {'hw_watchdog_action': 'none'})

        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn.get_guest_config(instance_ref, [], {}, disk_info)

        db.flavor_extra_specs_delete(self.context,
                                     flavor['flavorid'],
                                     'hw_watchdog_action')

        self.assertEqual(8, len(cfg.devices))
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestWatchdog)

        self.assertEqual("none", cfg.devices[7].action)

    def test_get_guest_config_with_watchdog_action_meta_overrides_flavor(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        flavor = db.flavor_get(self.context,
                               self.test_instance['instance_type_id'])
        db.flavor_extra_specs_update_or_create(
                self.context,
                flavor['flavorid'],
                {'hw_watchdog_action': 'none'})

        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_watchdog_action": "pause"}}

        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)

        db.flavor_extra_specs_delete(self.context,
                                     flavor['flavorid'],
                                     'hw_watchdog_action')

        self.assertEqual(8, len(cfg.devices))
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestWatchdog)

        self.assertEqual("pause", cfg.devices[7].action)

    def test_unsupported_video_driver_through_image_meta(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "something"}}
        self.assertRaises(exception.InvalidVideoMode,
                          conn.get_guest_config,
                          instance_ref,
                          [],
                          image_meta,
                          disk_info)

    def test_get_guest_config_with_video_driver_through_image_meta(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "vmvga"}}
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertEqual(len(cfg.devices), 7)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[5].type, "vnc")
        self.assertEqual(cfg.devices[6].type, "vmvga")

    def test_get_guest_config_with_qga_through_image_meta(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_qemu_guest_agent": "yes"}}
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertEqual(len(cfg.devices), 8)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestChannel)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")
        self.assertEqual(cfg.devices[7].type, "unix")
        self.assertEqual(cfg.devices[7].target_name, "org.qemu.guest_agent.0")

    def test_get_guest_config_with_video_driver_vram(self):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        instance_type = flavor_obj.Flavor.get_by_id(self.context, 5)
        instance_type.extra_specs = {'hw_video:ram_max_mb': "100"}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}
        with mock.patch.object(flavor_obj.Flavor, 'get_by_id',
                               return_value=instance_type):
            cfg = conn.get_guest_config(instance_ref, [],
                                        image_meta, disk_info)
            self.assertEqual(len(cfg.devices), 7)
            self.assertIsInstance(cfg.devices[0],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[1],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[2],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[3],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[4],
                                  vconfig.LibvirtConfigGuestChannel)
            self.assertIsInstance(cfg.devices[5],
                                  vconfig.LibvirtConfigGuestGraphics)
            self.assertIsInstance(cfg.devices[6],
                                  vconfig.LibvirtConfigGuestVideo)

            self.assertEqual(cfg.devices[5].type, "spice")
            self.assertEqual(cfg.devices[6].type, "qxl")
            self.assertEqual(cfg.devices[6].vram, 64)

    def test_video_driver_flavor_limit_not_set(self):
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}
        self.assertRaises(exception.RequestedVRamTooHigh,
                          conn.get_guest_config,
                          instance_ref,
                          [],
                          image_meta,
                          disk_info)

    def test_video_driver_ram_above_flavor_limit(self):
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        instance_type = flavor_obj.Flavor.get_by_id(self.context, 5)
        instance_type.extra_specs = {'hw_video:ram_max_mb': "50"}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}
        with mock.patch.object(flavor_obj.Flavor, 'get_by_id',
                               return_value=instance_type):
            self.assertRaises(exception.RequestedVRamTooHigh,
                              conn.get_guest_config,
                              instance_ref,
                              [],
                              image_meta,
                              disk_info)

    def test_get_guest_config_without_qga_through_image_meta(self):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_qemu_guest_agent": "no"}}
        cfg = conn.get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertEqual(len(cfg.devices), 7)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")

    def test_get_guest_config_with_rng_device(self):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        fake_flavour = flavor_obj.Flavor.get_by_id(
                                 self.context,
                                 self.test_instance['instance_type_id'])
        fake_flavour.extra_specs = {'hw_rng:allowed': 'True'}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        with mock.patch.object(flavor_obj.Flavor, 'get_by_id',
                               return_value=fake_flavour):
            cfg = conn.get_guest_config(instance_ref, [],
                                        image_meta, disk_info)
            self.assertEqual(len(cfg.devices), 7)
            self.assertIsInstance(cfg.devices[0],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[1],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[2],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[3],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[4],
                                  vconfig.LibvirtConfigGuestGraphics)
            self.assertIsInstance(cfg.devices[5],
                                  vconfig.LibvirtConfigGuestVideo)
            self.assertIsInstance(cfg.devices[6],
                                  vconfig.LibvirtConfigGuestRng)
            self.assertEqual(cfg.devices[6].model, 'random')
            self.assertIsNone(cfg.devices[6].backend)
            self.assertIsNone(cfg.devices[6].rate_bytes)
            self.assertIsNone(cfg.devices[6].rate_period)

    def test_get_guest_config_with_rng_not_allowed(self):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        cfg = conn.get_guest_config(instance_ref, [],
                                    image_meta, disk_info)
        self.assertEqual(len(cfg.devices), 6)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestVideo)

    def test_get_guest_config_with_rng_limits(self):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        fake_flavour = flavor_obj.Flavor.get_by_id(
                                 self.context,
                                 self.test_instance['instance_type_id'])
        fake_flavour.extra_specs = {'hw_rng:allowed': 'True',
                                    'hw_rng:rate_bytes': '1024',
                                    'hw_rng:rate_period': '2'}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        with mock.patch.object(flavor_obj.Flavor, 'get_by_id',
                               return_value=fake_flavour):
            cfg = conn.get_guest_config(instance_ref, [],
                                        image_meta, disk_info)
            self.assertEqual(len(cfg.devices), 7)
            self.assertIsInstance(cfg.devices[0],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[1],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[2],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[3],
                                  vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[4],
                                  vconfig.LibvirtConfigGuestGraphics)
            self.assertIsInstance(cfg.devices[5],
                                  vconfig.LibvirtConfigGuestVideo)
            self.assertIsInstance(cfg.devices[6],
                                  vconfig.LibvirtConfigGuestRng)
            self.assertEqual(cfg.devices[6].model, 'random')
            self.assertIsNone(cfg.devices[6].backend)
            self.assertEqual(cfg.devices[6].rate_bytes, 1024)
            self.assertEqual(cfg.devices[6].rate_period, 2)

    def test_get_guest_config_with_rng_backend(self):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   rng_dev_path='/dev/hw_rng',
                   group='libvirt')

        fake_flavour = flavor_obj.Flavor.get_by_id(
                                 self.context,
                                 self.test_instance['instance_type_id'])
        fake_flavour.extra_specs = {'hw_rng:allowed': 'True'}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        with contextlib.nested(mock.patch.object(flavor_obj.Flavor,
                                                 'get_by_id',
                                                 return_value=fake_flavour),
                       mock.patch('nova.virt.libvirt.driver.os.path.exists',
                                                 return_value=True)):
            cfg = conn.get_guest_config(instance_ref, [],
                                        image_meta, disk_info)
            self.assertEqual(len(cfg.devices), 7)
            self.assertIsInstance(cfg.devices[0],
                             vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[1],
                             vconfig.LibvirtConfigGuestDisk)
            self.assertIsInstance(cfg.devices[2],
                             vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[3],
                             vconfig.LibvirtConfigGuestSerial)
            self.assertIsInstance(cfg.devices[4],
                             vconfig.LibvirtConfigGuestGraphics)
            self.assertIsInstance(cfg.devices[5],
                             vconfig.LibvirtConfigGuestVideo)
            self.assertIsInstance(cfg.devices[6],
                             vconfig.LibvirtConfigGuestRng)
            self.assertEqual(cfg.devices[6].model, 'random')
            self.assertEqual(cfg.devices[6].backend, '/dev/hw_rng')
            self.assertIsNone(cfg.devices[6].rate_bytes)
            self.assertIsNone(cfg.devices[6].rate_period)

    def test_get_guest_config_with_rng_dev_not_present(self):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   rng_dev_path='/dev/hw_rng',
                   group='libvirt')

        fake_flavour = flavor_obj.Flavor.get_by_id(
                                 self.context,
                                 self.test_instance['instance_type_id'])
        fake_flavour.extra_specs = {'hw_rng:allowed': 'True'}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        with contextlib.nested(mock.patch.object(flavor_obj.Flavor,
                                                 'get_by_id',
                                                 return_value=fake_flavour),
                       mock.patch('nova.virt.libvirt.driver.os.path.exists',
                                                 return_value=False)):
            self.assertRaises(exception.RngDeviceNotExist,
                              conn.get_guest_config,
                              instance_ref,
                              [],
                              image_meta, disk_info)

    def _create_fake_service_compute(self):
        service_info = {
            'host': 'fake',
            'report_count': 0
        }
        service_ref = db.service_create(self.context, service_info)

        compute_info = {
            'vcpus': 2,
            'memory_mb': 1024,
            'local_gb': 2048,
            'vcpus_used': 0,
            'memory_mb_used': 0,
            'local_gb_used': 0,
            'free_ram_mb': 1024,
            'free_disk_gb': 2048,
            'hypervisor_type': 'xen',
            'hypervisor_version': 1,
            'running_vms': 0,
            'cpu_info': '',
            'current_workload': 0,
            'service_id': service_ref['id']
        }
        compute_ref = db.compute_node_create(self.context, compute_info)
        return (service_ref, compute_ref)

    def test_get_guest_config_with_pci_passthrough_kvm(self):
        self.flags(virt_type='kvm', group='libvirt')
        service_ref, compute_ref = self._create_fake_service_compute()

        instance_ref = db.instance_create(self.context, self.test_instance)
        pci_device_info = dict(test_pci_device.fake_db_dev)
        pci_device_info.update(compute_node_id=1,
                               label='fake',
                               status='allocated',
                               address='0000:00:00.1',
                               compute_id=compute_ref['id'],
                               instance_uuid=instance_ref['uuid'],
                               extra_info=jsonutils.dumps({}))
        db.pci_device_update(self.context, pci_device_info['compute_node_id'],
                             pci_device_info['address'], pci_device_info)

        instance_ref = db.instance_get(self.context, instance_ref['id'])

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)

        had_pci = 0
        # care only about the PCI devices
        for dev in cfg.devices:
            if type(dev) == vconfig.LibvirtConfigGuestHostdevPCI:
                had_pci += 1
                self.assertEqual(dev.type, 'pci')
                self.assertEqual(dev.managed, 'yes')
                self.assertEqual(dev.mode, 'subsystem')

                self.assertEqual(dev.domain, "0000")
                self.assertEqual(dev.bus, "00")
                self.assertEqual(dev.slot, "00")
                self.assertEqual(dev.function, "1")
        self.assertEqual(had_pci, 1)

    def test_get_guest_config_with_pci_passthrough_xen(self):
        self.flags(virt_type='xen', group='libvirt')
        service_ref, compute_ref = self._create_fake_service_compute()

        instance_ref = db.instance_create(self.context, self.test_instance)
        pci_device_info = dict(test_pci_device.fake_db_dev)
        pci_device_info.update(compute_node_id=1,
                               label='fake',
                               status='allocated',
                               address='0000:00:00.2',
                               compute_id=compute_ref['id'],
                               instance_uuid=instance_ref['uuid'],
                               extra_info=jsonutils.dumps({}))
        db.pci_device_update(self.context, pci_device_info['compute_node_id'],
                             pci_device_info['address'], pci_device_info)

        instance_ref = db.instance_get(self.context, instance_ref['id'])

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn.get_guest_config(instance_ref, [], None, disk_info)
        had_pci = 0
        # care only about the PCI devices
        for dev in cfg.devices:
            if type(dev) == vconfig.LibvirtConfigGuestHostdevPCI:
                had_pci += 1
                self.assertEqual(dev.type, 'pci')
                self.assertEqual(dev.managed, 'no')
                self.assertEqual(dev.mode, 'subsystem')

                self.assertEqual(dev.domain, "0000")
                self.assertEqual(dev.bus, "00")
                self.assertEqual(dev.slot, "00")
                self.assertEqual(dev.function, "2")
        self.assertEqual(had_pci, 1)

    def test_get_guest_config_os_command_line_through_image_meta(self):
        self.flags(virt_type="kvm",
                   cpu_mode=None,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"os_command_line":
            "fake_os_command_line"}}
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    image_meta, disk_info)
        self.assertEqual(cfg.os_cmdline, "fake_os_command_line")

    def test_get_guest_config_armv7(self):
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = "armv7l"

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.flags(virt_type="kvm",
                   group="libvirt")

        instance_ref = db.instance_create(self.context, self.test_instance)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "get_host_capabilities",
                       get_host_capabilities_stub)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    None, disk_info)
        self.assertEqual(cfg.os_mach_type, "vexpress-a15")

    def test_get_guest_config_aarch64(self):
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = "aarch64"

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.flags(virt_type="kvm",
                   group="libvirt")

        instance_ref = db.instance_create(self.context, self.test_instance)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "get_host_capabilities",
                       get_host_capabilities_stub)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    None, disk_info)
        self.assertEqual(cfg.os_mach_type, "virt")

    def test_get_guest_config_machine_type_through_image_meta(self):
        self.flags(virt_type="kvm",
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_machine_type":
            "fake_machine_type"}}
        cfg = conn.get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    image_meta, disk_info)
        self.assertEqual(cfg.os_mach_type, "fake_machine_type")

    def _test_get_guest_config_ppc64(self, device_index):
        """Test for nova.virt.libvirt.driver.LibvirtDriver.get_guest_config.
        """
        self.flags(virt_type='kvm', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {}
        expected = ('ppc64', 'ppc')
        for arch in expected:
            with mock.patch.object(libvirt_driver.libvirt_utils,
                                   'get_arch',
                                   return_value=arch):
                cfg = conn.get_guest_config(instance_ref, [],
                                            image_meta,
                                            disk_info)
                self.assertIsInstance(cfg.devices[device_index],
                                      vconfig.LibvirtConfigGuestVideo)
                self.assertEqual(cfg.devices[device_index].type, 'vga')

    def test_get_guest_config_ppc64_through_image_meta_vnc_enabled(self):
        self.flags(vnc_enabled=True)
        self._test_get_guest_config_ppc64(6)

    def test_get_guest_config_ppc64_through_image_meta_spice_enabled(self):
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')
        self._test_get_guest_config_ppc64(8)

    def test_get_guest_cpu_config_none(self):
        self.flags(cpu_mode="none", group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsNone(conf.cpu)

    def test_get_guest_cpu_config_default_kvm(self):
        self.flags(virt_type="kvm",
                   cpu_mode=None,
                   group='libvirt')

        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 11

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-model")
        self.assertIsNone(conf.cpu.model)

    def test_get_guest_cpu_config_default_uml(self):
        self.flags(virt_type="uml",
                   cpu_mode=None,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsNone(conf.cpu)

    def test_get_guest_cpu_config_default_lxc(self):
        self.flags(virt_type="lxc",
                   cpu_mode=None,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsNone(conf.cpu)

    def test_get_guest_cpu_config_host_passthrough_new(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 11

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="host-passthrough", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-passthrough")
        self.assertIsNone(conf.cpu.model)

    def test_get_guest_cpu_config_host_model_new(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 11

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="host-model", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-model")
        self.assertIsNone(conf.cpu.model)

    def test_get_guest_cpu_config_custom_new(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 11

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="custom",
                   cpu_model="Penryn",
                   group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "custom")
        self.assertEqual(conf.cpu.model, "Penryn")

    def test_get_guest_cpu_config_host_passthrough_old(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 7

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="host-passthrough", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        self.assertRaises(exception.NovaException,
                          conn.get_guest_config,
                          instance_ref,
                          _fake_network_info(self.stubs, 1),
                          None,
                          disk_info)

    def test_get_guest_cpu_config_host_model_old(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 7

        # Ensure we have a predictable host CPU
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.model = "Opteron_G4"
            cpu.vendor = "AMD"

            cpu.add_feature(vconfig.LibvirtConfigGuestCPUFeature("tm2"))
            cpu.add_feature(vconfig.LibvirtConfigGuestCPUFeature("ht"))

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "get_host_capabilities",
                       get_host_capabilities_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="host-model", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertIsNone(conf.cpu.mode)
        self.assertEqual(conf.cpu.model, "Opteron_G4")
        self.assertEqual(conf.cpu.vendor, "AMD")
        self.assertEqual(len(conf.cpu.features), 2)
        self.assertEqual(conf.cpu.features.pop().name, "tm2")
        self.assertEqual(conf.cpu.features.pop().name, "ht")

    def test_get_guest_cpu_config_custom_old(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 7

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        self.flags(cpu_mode="custom",
                   cpu_model="Penryn",
                   group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn.get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertIsNone(conf.cpu.mode)
        self.assertEqual(conf.cpu.model, "Penryn")

    def test_xml_and_uri_no_ramdisk_no_kernel(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_uri(instance_data,
                                expect_kernel=False, expect_ramdisk=False)

    def test_xml_and_uri_no_ramdisk_no_kernel_xen_hvm(self):
        instance_data = dict(self.test_instance)
        instance_data.update({'vm_mode': vm_mode.HVM})
        self._check_xml_and_uri(instance_data, expect_kernel=False,
                                expect_ramdisk=False, expect_xen_hvm=True)

    def test_xml_and_uri_no_ramdisk_no_kernel_xen_pv(self):
        instance_data = dict(self.test_instance)
        instance_data.update({'vm_mode': vm_mode.XEN})
        self._check_xml_and_uri(instance_data, expect_kernel=False,
                                expect_ramdisk=False, expect_xen_hvm=False,
                                xen_only=True)

    def test_xml_and_uri_no_ramdisk(self):
        instance_data = dict(self.test_instance)
        instance_data['kernel_id'] = 'aki-deadbeef'
        self._check_xml_and_uri(instance_data,
                                expect_kernel=True, expect_ramdisk=False)

    def test_xml_and_uri_no_kernel(self):
        instance_data = dict(self.test_instance)
        instance_data['ramdisk_id'] = 'ari-deadbeef'
        self._check_xml_and_uri(instance_data,
                                expect_kernel=False, expect_ramdisk=False)

    def test_xml_and_uri(self):
        instance_data = dict(self.test_instance)
        instance_data['ramdisk_id'] = 'ari-deadbeef'
        instance_data['kernel_id'] = 'aki-deadbeef'
        self._check_xml_and_uri(instance_data,
                                expect_kernel=True, expect_ramdisk=True)

    def test_xml_and_uri_rescue(self):
        instance_data = dict(self.test_instance)
        instance_data['ramdisk_id'] = 'ari-deadbeef'
        instance_data['kernel_id'] = 'aki-deadbeef'
        self._check_xml_and_uri(instance_data, expect_kernel=True,
                                expect_ramdisk=True, rescue=instance_data)

    def test_xml_and_uri_rescue_no_kernel_no_ramdisk(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_uri(instance_data, expect_kernel=False,
                                expect_ramdisk=False, rescue=instance_data)

    def test_xml_and_uri_rescue_no_kernel(self):
        instance_data = dict(self.test_instance)
        instance_data['ramdisk_id'] = 'aki-deadbeef'
        self._check_xml_and_uri(instance_data, expect_kernel=False,
                                expect_ramdisk=True, rescue=instance_data)

    def test_xml_and_uri_rescue_no_ramdisk(self):
        instance_data = dict(self.test_instance)
        instance_data['kernel_id'] = 'aki-deadbeef'
        self._check_xml_and_uri(instance_data, expect_kernel=True,
                                expect_ramdisk=False, rescue=instance_data)

    def test_xml_uuid(self):
        self._check_xml_and_uuid({"disk_format": "raw"})

    def test_lxc_container_and_uri(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_container(instance_data)

    def test_xml_disk_prefix(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_disk_prefix(instance_data)

    def test_xml_user_specified_disk_prefix(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_disk_prefix(instance_data, 'sd')

    def test_xml_disk_driver(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_disk_driver(instance_data)

    def test_xml_disk_bus_virtio(self):
        self._check_xml_and_disk_bus({"disk_format": "raw"},
                                     None,
                                     (("disk", "virtio", "vda"),))

    def test_xml_disk_bus_ide(self):
        self._check_xml_and_disk_bus({"disk_format": "iso"},
                                     None,
                                     (("cdrom", "ide", "hda"),))

    def test_xml_disk_bus_ide_and_virtio(self):
        swap = {'device_name': '/dev/vdc',
                'swap_size': 1}
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'virtio',
                       'device_name': '/dev/vdb',
                       'size': 1}]
        block_device_info = {
                'swap': swap,
                'ephemerals': ephemerals}

        self._check_xml_and_disk_bus({"disk_format": "iso"},
                                     block_device_info,
                                     (("cdrom", "ide", "hda"),
                                      ("disk", "virtio", "vdb"),
                                      ("disk", "virtio", "vdc")))

    def test_list_instances(self):
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = self.fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 2
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instances = conn.list_instances()
        # Only one should be listed, since domain with ID 0 must be skipped
        self.assertEqual(len(instances), 1)

    def test_list_instance_uuids(self):
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = self.fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 2
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instances = conn.list_instance_uuids()
        # Only one should be listed, since domain with ID 0 must be skipped
        self.assertEqual(len(instances), 1)

    def test_list_defined_instances(self):
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = self.fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 1
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: [1]

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instances = conn.list_instances()
        # Only one defined domain should be listed
        self.assertEqual(len(instances), 1)

    def test_list_instances_when_instance_deleted(self):

        def fake_lookup(instance_name):
            raise libvirt.libvirtError("we deleted an instance!")

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 1
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
        libvirt.libvirtError.get_error_code().AndReturn(
            libvirt.VIR_ERR_NO_DOMAIN)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instances = conn.list_instances()
        # None should be listed, since we fake deleted the last one
        self.assertEqual(len(instances), 0)

    def test_list_instance_uuids_when_instance_deleted(self):

        def fake_lookup(instance_name):
            raise libvirt.libvirtError("we deleted an instance!")

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 1
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
        libvirt.libvirtError.get_error_code().AndReturn(
            libvirt.VIR_ERR_NO_DOMAIN)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instances = conn.list_instance_uuids()
        # None should be listed, since we fake deleted the last one
        self.assertEqual(len(instances), 0)

    def test_list_instances_throws_nova_exception(self):
        def fake_lookup(instance_name):
            raise libvirt.libvirtError("we deleted an instance!")

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 1
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
        libvirt.libvirtError.get_error_code().AndReturn(
            libvirt.VIR_ERR_INTERNAL_ERROR)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.NovaException, conn.list_instances)

    def test_list_instance_uuids_throws_nova_exception(self):
        def fake_lookup(instance_name):
            raise libvirt.libvirtError("we deleted an instance!")

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 1
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: [0, 1]
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
        libvirt.libvirtError.get_error_code().AndReturn(
            libvirt.VIR_ERR_INTERNAL_ERROR)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.NovaException, conn.list_instance_uuids)

    def test_get_all_block_devices(self):
        xml = [
            # NOTE(vish): id 0 is skipped
            None,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                        </disk>
                    </devices>
                </domain>
            """,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                    </devices>
                </domain>
            """,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/3'/>
                        </disk>
                    </devices>
                </domain>
            """,
        ]

        def fake_lookup(id):
            return FakeVirtDomain(xml[id])

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 4
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: range(4)
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        devices = conn.get_all_block_devices()
        self.assertEqual(devices, ['/path/to/dev/1', '/path/to/dev/3'])

    def test_get_disks(self):
        xml = [
            # NOTE(vish): id 0 is skipped
            None,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                    </devices>
                </domain>
            """,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                    </devices>
                </domain>
            """,
            """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/3'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                    </devices>
                </domain>
            """,
        ]

        def fake_lookup(id):
            return FakeVirtDomain(xml[id])

        def fake_lookup_name(name):
            return FakeVirtDomain(xml[1])

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 4
        libvirt_driver.LibvirtDriver._conn.listDomainsID = lambda: range(4)
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        devices = conn.get_disks(conn.list_instances()[0])
        self.assertEqual(devices, ['vda', 'vdb'])

    def test_snapshot_in_ami_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./', group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign different image_ref from nova/images/fakes for testing ami
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'ami')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lxc_snapshot_in_ami_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   virt_type='lxc',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign different image_ref from nova/images/fakes for testing ami
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'ami')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_in_raw_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./', group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, self.test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        self.stubs.Set(libvirt_driver.libvirt_utils, 'disk_type', 'raw')

        def convert_image(source, dest, out_format):
            libvirt_driver.libvirt_utils.files[dest] = ''

        self.stubs.Set(images, 'convert_image', convert_image)

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'raw')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lxc_snapshot_in_raw_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   virt_type='lxc',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, self.test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        self.stubs.Set(libvirt_driver.libvirt_utils, 'disk_type', 'raw')

        def convert_image(source, dest, out_format):
            libvirt_driver.libvirt_utils.files[dest] = ''

        self.stubs.Set(images, 'convert_image', convert_image)

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'raw')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_in_qcow2_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshot_image_format='qcow2',
                   snapshots_directory='./',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, self.test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'qcow2')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lxc_snapshot_in_qcow2_format(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshot_image_format='qcow2',
                   snapshots_directory='./',
                   virt_type='lxc',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, self.test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'qcow2')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_no_image_architecture(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign different image_ref from nova/images/fakes for
        # testing different base image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lxc_snapshot_no_image_architecture(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   virt_type='lxc',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign different image_ref from nova/images/fakes for
        # testing different base image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

        # Assuming that base image already exists in image_service
        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_no_original_image(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'

        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lxc_snapshot_no_original_image(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   virt_type='lxc',
                   group='libvirt')

        # Start test
        image_service = nova.tests.image.fake.FakeImageService()

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'

        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_metadata_image(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   group='libvirt')

        image_service = nova.tests.image.fake.FakeImageService()

        # Assign an image with an architecture defined (x86_64)
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'a440c04b-79fa-479c-bed1-0b816eaec379'

        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id),
                      'architecture': 'fake_arch',
                      'key_a': 'value_a',
                      'key_b': 'value_b'}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['properties']['architecture'], 'fake_arch')
        self.assertEqual(snapshot['properties']['key_a'], 'value_a')
        self.assertEqual(snapshot['properties']['key_b'], 'value_b')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_snapshot_with_os_type(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        self.flags(snapshots_directory='./',
                   group='libvirt')

        image_service = nova.tests.image.fake.FakeImageService()

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'
        test_instance["os_type"] = 'linux'

        instance_ref = db.instance_create(self.context, test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id),
                      'os_type': instance_ref['os_type']}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['properties']['os_type'],
                         instance_ref['os_type'])
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test__create_snapshot_metadata(self):
        base = {}
        instance = {'kernel_id': 'kernel',
                    'project_id': 'prj_id',
                    'ramdisk_id': 'ram_id',
                    'os_type': None}
        img_fmt = 'raw'
        snp_name = 'snapshot_name'
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        ret = conn._create_snapshot_metadata(base, instance, img_fmt, snp_name)
        expected = {'is_public': False,
                    'status': 'active',
                    'name': snp_name,
                    'properties': {
                                   'kernel_id': instance['kernel_id'],
                                   'image_location': 'snapshot',
                                   'image_state': 'available',
                                   'owner_id': instance['project_id'],
                                   'ramdisk_id': instance['ramdisk_id'],
                                   },
                    'disk_format': img_fmt,
                    'container_format': base.get('container_format', 'bare')
                    }
        self.assertEqual(ret, expected)

        # simulate an instance with os_type field defined
        # disk format equals to ami
        # container format not equals to bare
        instance['os_type'] = 'linux'
        base['disk_format'] = 'ami'
        base['container_format'] = 'test_container'
        expected['properties']['os_type'] = instance['os_type']
        expected['disk_format'] = base['disk_format']
        expected['container_format'] = base.get('container_format', 'bare')
        ret = conn._create_snapshot_metadata(base, instance, img_fmt, snp_name)
        self.assertEqual(ret, expected)

    def test_attach_invalid_volume_type(self):
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.VolumeDriverNotFound,
                          conn.attach_volume, None,
                          {"driver_volume_type": "badtype"},
                          {"name": "fake-instance"},
                          "/dev/sda")

    def test_attach_blockio_invalid_hypervisor(self):
        self.flags(virt_type='fake_type', group='libvirt')
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.InvalidHypervisorType,
                          conn.attach_volume, None,
                          {"driver_volume_type": "fake",
                           "data": {"logical_block_size": "4096",
                                    "physical_block_size": "4096"}
                          },
                          {"name": "fake-instance"},
                          "/dev/sda")

    def test_attach_blockio_invalid_version(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 8
        self.flags(virt_type='qemu', group='libvirt')
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(self.conn, "getLibVersion", get_lib_version_stub)
        self.assertRaises(exception.Invalid,
                          conn.attach_volume, None,
                          {"driver_volume_type": "fake",
                           "data": {"logical_block_size": "4096",
                                    "physical_block_size": "4096"}
                          },
                          {"name": "fake-instance"},
                          "/dev/sda")

    @mock.patch('nova.virt.libvirt.blockinfo.get_info_from_bdm')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_attach_volume_with_vir_domain_affect_live_flag(self,
            mock_lookup_by_name, mock_get_info):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        mock_dom = mock.MagicMock()
        mock_lookup_by_name.return_value = mock_dom

        connection_info = {"driver_volume_type": "fake",
                           "data": {"device_path": "/fake",
                                    "access_mode": "rw"}}
        bdm = {'device_name': 'vdb',
               'disk_bus': 'fake-bus',
               'device_type': 'fake-type'}
        disk_info = {'bus': bdm['disk_bus'], 'type': bdm['device_type'],
                     'dev': 'vdb'}
        mock_get_info.return_value = disk_info
        mock_conf = mock.MagicMock()
        flags = (fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                 fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

        with contextlib.nested(
            mock.patch.object(conn, 'volume_driver_method',
                              return_value=mock_conf),
            mock.patch.object(conn, 'set_cache_mode')
        ) as (mock_volume_driver_method, mock_set_cache_mode):
            for state in (power_state.RUNNING, power_state.PAUSED):
                mock_dom.info.return_value = [state, 512, 512, 2, 1234, 5678]

                conn.attach_volume(self.context, connection_info, instance,
                                   "/dev/vdb", disk_bus=bdm['disk_bus'],
                                   device_type=bdm['device_type'])

                mock_lookup_by_name.assert_called_with(instance['name'])
                mock_get_info.assert_called_with(CONF.libvirt.virt_type, bdm)
                mock_volume_driver_method.assert_called_with(
                    'connect_volume', connection_info, disk_info)
                mock_set_cache_mode.assert_called_with(mock_conf)
                mock_dom.attachDeviceFlags.assert_called_with(
                    mock_conf.to_xml(), flags)

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._get_disk_xml')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_detach_volume_with_vir_domain_affect_live_flag(self,
            mock_lookup_by_name, mock_get_disk_xml):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        mock_dom = mock.MagicMock()
        mock_xml = \
            """
            <disk type='file'>
                <source file='/path/to/fake-volume'/>
                <target dev='vdc' bus='virtio'/>
            </disk>
            """
        mock_get_disk_xml.return_value = mock_xml

        connection_info = {"driver_volume_type": "fake",
                           "data": {"device_path": "/fake",
                                    "access_mode": "rw"}}
        flags = (fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                 fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

        with mock.patch.object(conn, 'volume_driver_method') as \
                mock_volume_driver_method:
            for state in (power_state.RUNNING, power_state.PAUSED):
                mock_dom.info.return_value = [state, 512, 512, 2, 1234, 5678]
                mock_lookup_by_name.return_value = mock_dom

                conn.detach_volume(connection_info, instance, '/dev/vdc')

                mock_lookup_by_name.assert_called_with(instance['name'])
                mock_get_disk_xml.assert_called_with(mock_dom.XMLDesc(0),
                                                     'vdc')
                mock_dom.detachDeviceFlags.assert_called_with(mock_xml, flags)
                mock_volume_driver_method.assert_called_with(
                    'disconnect_volume', connection_info, 'vdc')

    def test_multi_nic(self):
        instance_data = dict(self.test_instance)
        network_info = _fake_network_info(self.stubs, 2)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = db.instance_create(self.context, instance_data)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = conn.to_xml(self.context, instance_ref, network_info, disk_info)
        tree = etree.fromstring(xml)
        interfaces = tree.findall("./devices/interface")
        self.assertEqual(len(interfaces), 2)
        self.assertEqual(interfaces[0].get('type'), 'bridge')

    def _behave_supports_direct_io(self, raise_open=False, raise_write=False,
                                   exc=ValueError()):
        open_behavior = os.open(os.path.join('.', '.directio.test'),
                                os.O_CREAT | os.O_WRONLY | os.O_DIRECT)
        if raise_open:
            open_behavior.AndRaise(exc)
        else:
            open_behavior.AndReturn(3)
            write_bahavior = os.write(3, mox.IgnoreArg())
            if raise_write:
                write_bahavior.AndRaise(exc)
            else:
                os.close(3)
        os.unlink(3)

    def test_supports_direct_io(self):
        einval = OSError()
        einval.errno = errno.EINVAL
        self.mox.StubOutWithMock(os, 'open')
        self.mox.StubOutWithMock(os, 'write')
        self.mox.StubOutWithMock(os, 'close')
        self.mox.StubOutWithMock(os, 'unlink')
        _supports_direct_io = libvirt_driver.LibvirtDriver._supports_direct_io

        self._behave_supports_direct_io()
        self._behave_supports_direct_io(raise_write=True)
        self._behave_supports_direct_io(raise_open=True)
        self._behave_supports_direct_io(raise_write=True, exc=einval)
        self._behave_supports_direct_io(raise_open=True, exc=einval)

        self.mox.ReplayAll()
        self.assertTrue(_supports_direct_io('.'))
        self.assertRaises(ValueError, _supports_direct_io, '.')
        self.assertRaises(ValueError, _supports_direct_io, '.')
        self.assertFalse(_supports_direct_io('.'))
        self.assertFalse(_supports_direct_io('.'))
        self.mox.VerifyAll()

    def _check_xml_and_container(self, instance):
        user_context = context.RequestContext(self.user_id,
                                              self.project_id)
        instance_ref = db.instance_create(user_context, instance)

        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        self.assertEqual(conn.uri(), 'lxc:///')

        network_info = _fake_network_info(self.stubs, 1)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = conn.to_xml(self.context, instance_ref, network_info, disk_info)
        tree = etree.fromstring(xml)

        check = [
        (lambda t: t.find('.').get('type'), 'lxc'),
        (lambda t: t.find('./os/type').text, 'exe'),
        (lambda t: t.find('./devices/filesystem/target').get('dir'), '/')]

        for i, (check, expected_result) in enumerate(check):
            self.assertEqual(check(tree),
                             expected_result,
                             '%s failed common check %d' % (xml, i))

        target = tree.find('./devices/filesystem/source').get('dir')
        self.assertTrue(len(target) > 0)

    def _check_xml_and_disk_prefix(self, instance, prefix=None):
        user_context = context.RequestContext(self.user_id,
                                              self.project_id)
        instance_ref = db.instance_create(user_context, instance)

        def _get_prefix(p, default):
            if p:
                return p + 'a'
            return default

        type_disk_map = {
            'qemu': [
                (lambda t: t.find('.').get('type'), 'qemu'),
                (lambda t: t.find('./devices/disk/target').get('dev'),
                 _get_prefix(prefix, 'vda'))],
            'xen': [
                (lambda t: t.find('.').get('type'), 'xen'),
                (lambda t: t.find('./devices/disk/target').get('dev'),
                 _get_prefix(prefix, 'sda'))],
            'kvm': [
                (lambda t: t.find('.').get('type'), 'kvm'),
                (lambda t: t.find('./devices/disk/target').get('dev'),
                 _get_prefix(prefix, 'vda'))],
            'uml': [
                (lambda t: t.find('.').get('type'), 'uml'),
                (lambda t: t.find('./devices/disk/target').get('dev'),
                 _get_prefix(prefix, 'ubda'))]
            }

        for (virt_type, checks) in type_disk_map.iteritems():
            self.flags(virt_type=virt_type, group='libvirt')
            if prefix:
                self.flags(disk_prefix=prefix, group='libvirt')
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

            network_info = _fake_network_info(self.stubs, 1)
            disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                instance_ref)
            xml = conn.to_xml(self.context, instance_ref,
                              network_info, disk_info)
            tree = etree.fromstring(xml)

            for i, (check, expected_result) in enumerate(checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s != %s failed check %d' %
                                 (check(tree), expected_result, i))

    def _check_xml_and_disk_driver(self, image_meta):
        os_open = os.open
        directio_supported = True

        def os_open_stub(path, flags, *args, **kwargs):
            if flags & os.O_DIRECT:
                if not directio_supported:
                    raise OSError(errno.EINVAL,
                                  '%s: %s' % (os.strerror(errno.EINVAL), path))
                flags &= ~os.O_DIRECT
            return os_open(path, flags, *args, **kwargs)

        self.stubs.Set(os, 'open', os_open_stub)

        @staticmethod
        def connection_supports_direct_io_stub(dirpath):
            return directio_supported

        self.stubs.Set(libvirt_driver.LibvirtDriver,
            '_supports_direct_io', connection_supports_direct_io_stub)

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = drv.to_xml(self.context, instance_ref,
                         network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        disks = tree.findall('./devices/disk/driver')
        for disk in disks:
            self.assertEqual(disk.get("cache"), "none")

        directio_supported = False

        # The O_DIRECT availability is cached on first use in
        # LibvirtDriver, hence we re-create it here
        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = drv.to_xml(self.context, instance_ref,
                         network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        disks = tree.findall('./devices/disk/driver')
        for disk in disks:
            self.assertEqual(disk.get("cache"), "writethrough")

    def _check_xml_and_disk_bus(self, image_meta,
                                block_device_info, wantConfig):
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref,
                                            block_device_info,
                                            image_meta)
        xml = drv.to_xml(self.context, instance_ref,
                         network_info, disk_info, image_meta,
                         block_device_info=block_device_info)
        tree = etree.fromstring(xml)

        got_disks = tree.findall('./devices/disk')
        got_disk_targets = tree.findall('./devices/disk/target')
        for i in range(len(wantConfig)):
            want_device_type = wantConfig[i][0]
            want_device_bus = wantConfig[i][1]
            want_device_dev = wantConfig[i][2]

            got_device_type = got_disks[i].get('device')
            got_device_bus = got_disk_targets[i].get('bus')
            got_device_dev = got_disk_targets[i].get('dev')

            self.assertEqual(got_device_type, want_device_type)
            self.assertEqual(got_device_bus, want_device_bus)
            self.assertEqual(got_device_dev, want_device_dev)

    def _check_xml_and_uuid(self, image_meta):
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = drv.to_xml(self.context, instance_ref,
                         network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.find('./uuid').text,
                         instance_ref['uuid'])

    def _check_xml_and_uri(self, instance, expect_ramdisk, expect_kernel,
                           rescue=None, expect_xen_hvm=False, xen_only=False):
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, instance)
        network_ref = db.project_get_networks(context.get_admin_context(),
                                             self.project_id)[0]

        xen_vm_mode = vm_mode.XEN
        if expect_xen_hvm:
            xen_vm_mode = vm_mode.HVM

        type_uri_map = {'qemu': ('qemu:///system',
                             [(lambda t: t.find('.').get('type'), 'qemu'),
                              (lambda t: t.find('./os/type').text,
                               vm_mode.HVM),
                              (lambda t: t.find('./devices/emulator'), None)]),
                        'kvm': ('qemu:///system',
                             [(lambda t: t.find('.').get('type'), 'kvm'),
                              (lambda t: t.find('./os/type').text,
                               vm_mode.HVM),
                              (lambda t: t.find('./devices/emulator'), None)]),
                        'uml': ('uml:///system',
                             [(lambda t: t.find('.').get('type'), 'uml'),
                              (lambda t: t.find('./os/type').text,
                               vm_mode.UML)]),
                        'xen': ('xen:///',
                             [(lambda t: t.find('.').get('type'), 'xen'),
                              (lambda t: t.find('./os/type').text,
                               xen_vm_mode)])}

        if expect_xen_hvm or xen_only:
            hypervisors_to_check = ['xen']
        else:
            hypervisors_to_check = ['qemu', 'kvm', 'xen']

        for hypervisor_type in hypervisors_to_check:
            check_list = type_uri_map[hypervisor_type][1]

            if rescue:
                suffix = '.rescue'
            else:
                suffix = ''
            if expect_kernel:
                check = (lambda t: self.relpath(t.find('./os/kernel').text).
                         split('/')[1], 'kernel' + suffix)
            else:
                check = (lambda t: t.find('./os/kernel'), None)
            check_list.append(check)

            if expect_kernel:
                check = (lambda t: "no_timer_check" in t.find('./os/cmdline').
                         text, hypervisor_type == "qemu")
                check_list.append(check)
            # Hypervisors that only support vm_mode.HVM and Xen
            # should not produce configuration that results in kernel
            # arguments
            if not expect_kernel and (hypervisor_type in
                                      ['qemu', 'kvm', 'xen']):
                check = (lambda t: t.find('./os/root'), None)
                check_list.append(check)
                check = (lambda t: t.find('./os/cmdline'), None)
                check_list.append(check)

            if expect_ramdisk:
                check = (lambda t: self.relpath(t.find('./os/initrd').text).
                         split('/')[1], 'ramdisk' + suffix)
            else:
                check = (lambda t: t.find('./os/initrd'), None)
            check_list.append(check)

            if hypervisor_type in ['qemu', 'kvm']:
                xpath = "./sysinfo/system/entry"
                check = (lambda t: t.findall(xpath)[0].get("name"),
                         "manufacturer")
                check_list.append(check)
                check = (lambda t: t.findall(xpath)[0].text,
                         version.vendor_string())
                check_list.append(check)

                check = (lambda t: t.findall(xpath)[1].get("name"),
                         "product")
                check_list.append(check)
                check = (lambda t: t.findall(xpath)[1].text,
                         version.product_string())
                check_list.append(check)

                check = (lambda t: t.findall(xpath)[2].get("name"),
                         "version")
                check_list.append(check)
                # NOTE(sirp): empty strings don't roundtrip in lxml (they are
                # converted to None), so we need an `or ''` to correct for that
                check = (lambda t: t.findall(xpath)[2].text or '',
                         version.version_string_with_package())
                check_list.append(check)

                check = (lambda t: t.findall(xpath)[3].get("name"),
                         "serial")
                check_list.append(check)
                check = (lambda t: t.findall(xpath)[3].text,
                         "cef19ce0-0ca2-11df-855d-b19fbce37686")
                check_list.append(check)

                check = (lambda t: t.findall(xpath)[4].get("name"),
                         "uuid")
                check_list.append(check)
                check = (lambda t: t.findall(xpath)[4].text,
                         instance['uuid'])
                check_list.append(check)

            if hypervisor_type in ['qemu', 'kvm']:
                check = (lambda t: t.findall('./devices/serial')[0].get(
                        'type'), 'file')
                check_list.append(check)
                check = (lambda t: t.findall('./devices/serial')[1].get(
                        'type'), 'pty')
                check_list.append(check)
                check = (lambda t: self.relpath(t.findall(
                         './devices/serial/source')[0].get('path')).
                         split('/')[1], 'console.log')
                check_list.append(check)
            else:
                check = (lambda t: t.find('./devices/console').get(
                        'type'), 'pty')
                check_list.append(check)

        common_checks = [
            (lambda t: t.find('.').tag, 'domain'),
            (lambda t: t.find('./memory').text, '2097152')]
        if rescue:
            common_checks += [
                (lambda t: self.relpath(t.findall('./devices/disk/source')[0].
                    get('file')).split('/')[1], 'disk.rescue'),
                (lambda t: self.relpath(t.findall('./devices/disk/source')[1].
                    get('file')).split('/')[1], 'disk')]
        else:
            common_checks += [(lambda t: self.relpath(t.findall(
                './devices/disk/source')[0].get('file')).split('/')[1],
                               'disk')]
            common_checks += [(lambda t: self.relpath(t.findall(
                './devices/disk/source')[1].get('file')).split('/')[1],
                               'disk.local')]

        for virt_type in hypervisors_to_check:
            expected_uri = type_uri_map[virt_type][0]
            checks = type_uri_map[virt_type][1]
            self.flags(virt_type=virt_type, group='libvirt')

            with mock.patch('nova.virt.libvirt.driver.libvirt') as old_virt:
                del old_virt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES

                conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

                self.assertEqual(conn.uri(), expected_uri)

                network_info = _fake_network_info(self.stubs, 1)
                disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                    instance_ref,
                                                    rescue=rescue)
                xml = conn.to_xml(self.context, instance_ref,
                                network_info, disk_info, rescue=rescue)
                tree = etree.fromstring(xml)
                for i, (check, expected_result) in enumerate(checks):
                    self.assertEqual(check(tree),
                                    expected_result,
                                    '%s != %s failed check %d' %
                                    (check(tree), expected_result, i))

                for i, (check, expected_result) in enumerate(common_checks):
                    self.assertEqual(check(tree),
                                    expected_result,
                                    '%s != %s failed common check %d' %
                                    (check(tree), expected_result, i))

                filterref = './devices/interface/filterref'
                vif = network_info[0]
                nic_id = vif['address'].replace(':', '')
                fw = firewall.NWFilterFirewall(fake.FakeVirtAPI(), conn)
                instance_filter_name = fw._instance_filter_name(instance_ref,
                                                                nic_id)
                self.assertEqual(tree.find(filterref).get('filter'),
                                 instance_filter_name)

        # This test is supposed to make sure we don't
        # override a specifically set uri
        #
        # Deliberately not just assigning this string to CONF.connection_uri
        # and checking against that later on. This way we make sure the
        # implementation doesn't fiddle around with the CONF.
        testuri = 'something completely different'
        self.flags(connection_uri=testuri, group='libvirt')
        for (virt_type, (expected_uri, checks)) in type_uri_map.iteritems():
            self.flags(virt_type=virt_type, group='libvirt')
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
            self.assertEqual(conn.uri(), testuri)
        db.instance_destroy(user_context, instance_ref['uuid'])

    def test_ensure_filtering_rules_for_instance_timeout(self):
        # ensure_filtering_fules_for_instance() finishes with timeout.
        # Preparing mocks
        def fake_none(self, *args):
            return

        def fake_raise(self):
            raise libvirt.libvirtError('ERR')

        class FakeTime(object):
            def __init__(self):
                self.counter = 0

            def sleep(self, t):
                self.counter += t

        fake_timer = FakeTime()

        # _fake_network_info must be called before create_fake_libvirt_mock(),
        # as _fake_network_info calls importutils.import_class() and
        # create_fake_libvirt_mock() mocks importutils.import_class().
        network_info = _fake_network_info(self.stubs, 1)
        self.create_fake_libvirt_mock()
        instance_ref = db.instance_create(self.context, self.test_instance)

        # Start test
        self.mox.ReplayAll()
        try:
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.stubs.Set(conn.firewall_driver,
                           'setup_basic_filtering',
                           fake_none)
            self.stubs.Set(conn.firewall_driver,
                           'prepare_instance_filter',
                           fake_none)
            self.stubs.Set(conn.firewall_driver,
                           'instance_filter_exists',
                           fake_none)
            conn.ensure_filtering_rules_for_instance(instance_ref,
                                                     network_info,
                                                     time_module=fake_timer)
        except exception.NovaException as e:
            msg = ('The firewall filter for %s does not exist' %
                   instance_ref['name'])
            c1 = (0 <= str(e).find(msg))
        self.assertTrue(c1)

        self.assertEqual(29, fake_timer.counter, "Didn't wait the expected "
                                                 "amount of time")

        db.instance_destroy(self.context, instance_ref['uuid'])

    def test_check_can_live_migrate_dest_all_pass_with_block_migration(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        compute_info = {'disk_available_least': 400,
                        'cpu_info': 'asdf',
                        }
        filename = "file"

        self.mox.StubOutWithMock(conn, '_create_shared_storage_test_file')
        self.mox.StubOutWithMock(conn, '_compare_cpu')

        # _check_cpu_match
        conn._compare_cpu("asdf")

        # mounted_on_same_shared_storage
        conn._create_shared_storage_test_file().AndReturn(filename)

        self.mox.ReplayAll()
        return_value = conn.check_can_live_migrate_destination(self.context,
                instance_ref, compute_info, compute_info, True)
        self.assertThat({"filename": "file",
                         'disk_available_mb': 409600,
                         "disk_over_commit": False,
                         "block_migration": True},
                        matchers.DictMatches(return_value))

    def test_check_can_live_migrate_dest_all_pass_no_block_migration(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        compute_info = {'cpu_info': 'asdf'}
        filename = "file"

        self.mox.StubOutWithMock(conn, '_create_shared_storage_test_file')
        self.mox.StubOutWithMock(conn, '_compare_cpu')

        # _check_cpu_match
        conn._compare_cpu("asdf")

        # mounted_on_same_shared_storage
        conn._create_shared_storage_test_file().AndReturn(filename)

        self.mox.ReplayAll()
        return_value = conn.check_can_live_migrate_destination(self.context,
                instance_ref, compute_info, compute_info, False)
        self.assertThat({"filename": "file",
                         "block_migration": False,
                         "disk_over_commit": False,
                         "disk_available_mb": None},
                        matchers.DictMatches(return_value))

    def test_check_can_live_migrate_dest_incompatible_cpu_raises(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        compute_info = {'cpu_info': 'asdf'}

        self.mox.StubOutWithMock(conn, '_compare_cpu')

        conn._compare_cpu("asdf").AndRaise(exception.InvalidCPUInfo(
                                              reason='foo')
                                           )

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidCPUInfo,
                          conn.check_can_live_migrate_destination,
                          self.context, instance_ref,
                          compute_info, compute_info, False)

    def test_check_can_live_migrate_dest_cleanup_works_correctly(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": True,
                           "disk_over_commit": False,
                           "disk_available_mb": 1024}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, '_cleanup_shared_storage_test_file')
        conn._cleanup_shared_storage_test_file("file")

        self.mox.ReplayAll()
        conn.check_can_live_migrate_destination_cleanup(self.context,
                                                        dest_check_data)

    def test_check_can_live_migrate_source_works_correctly(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": True,
                           "disk_over_commit": False,
                           "disk_available_mb": 1024}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn('[]')

        self.mox.StubOutWithMock(conn, "_assert_dest_node_has_enough_disk")
        conn._assert_dest_node_has_enough_disk(
            self.context, instance_ref, dest_check_data['disk_available_mb'],
            False)

        self.mox.ReplayAll()
        conn.check_can_live_migrate_source(self.context, instance_ref,
                                           dest_check_data)

    def test_check_can_live_migrate_source_vol_backed_works_correctly(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": False,
                           "disk_over_commit": False,
                           "disk_available_mb": 1024,
                           "is_volume_backed": True}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn('[]')
        self.mox.ReplayAll()
        ret = conn.check_can_live_migrate_source(self.context, instance_ref,
                                                 dest_check_data)
        self.assertTrue(type(ret) == dict)
        self.assertIn('is_shared_storage', ret)

    def test_check_can_live_migrate_source_vol_backed_w_disk_raises(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": False,
                           "disk_over_commit": False,
                           "disk_available_mb": 1024,
                           "is_volume_backed": True}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn(
                '[{"fake_disk_attr": "fake_disk_val"}]')
        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidSharedStorage,
                          conn.check_can_live_migrate_source, self.context,
                          instance_ref, dest_check_data)

    def test_check_can_live_migrate_source_vol_backed_fails(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": False,
                           "disk_over_commit": False,
                           "disk_available_mb": 1024,
                           "is_volume_backed": False}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn(
                '[{"fake_disk_attr": "fake_disk_val"}]')
        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidSharedStorage,
                          conn.check_can_live_migrate_source, self.context,
                          instance_ref, dest_check_data)

    def test_check_can_live_migrate_dest_fail_shared_storage_with_blockm(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": True,
                           "disk_over_commit": False,
                           'disk_available_mb': 1024}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(True)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn('[]')

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidLocalStorage,
                          conn.check_can_live_migrate_source,
                          self.context, instance_ref, dest_check_data)

    def test_check_can_live_migrate_no_shared_storage_no_blck_mig_raises(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        dest_check_data = {"filename": "file",
                           "block_migration": False,
                           "disk_over_commit": False,
                           'disk_available_mb': 1024}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)
        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref['name']).AndReturn('[]')

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidSharedStorage,
                          conn.check_can_live_migrate_source,
                          self.context, instance_ref, dest_check_data)

    def test_check_can_live_migrate_source_with_dest_not_enough_disk(self):
        instance_ref = db.instance_create(self.context, self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, "_check_shared_storage_test_file")
        conn._check_shared_storage_test_file("file").AndReturn(False)

        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance_ref["name"]).AndReturn(
                                            '[{"virt_disk_size":2}]')
        conn.get_instance_disk_info(instance_ref["name"]).AndReturn(
                                            '[{"virt_disk_size":2}]')

        dest_check_data = {"filename": "file",
                           "disk_available_mb": 0,
                           "block_migration": True,
                           "disk_over_commit": False}
        self.mox.ReplayAll()
        self.assertRaises(exception.MigrationError,
                          conn.check_can_live_migrate_source,
                          self.context, instance_ref, dest_check_data)

    def test_live_migration_raises_exception(self):
        # Confirms recover method is called when exceptions are raised.
        # Preparing data
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = {'host': 'fake',
                         'power_state': power_state.RUNNING,
                         'vm_state': vm_states.ACTIVE}
        instance_ref = db.instance_create(self.context, self.test_instance)
        instance_ref = db.instance_update(self.context, instance_ref['uuid'],
                                          instance_dict)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI")
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        vdmock.migrateToURI(CONF.libvirt.live_migration_uri % 'dest',
                            mox.IgnoreArg(),
                            None,
                            _bandwidth).AndRaise(libvirt.libvirtError('ERR'))

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        #start test
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration)

        instance_ref = db.instance_get(self.context, instance_ref['id'])
        self.assertTrue(instance_ref['vm_state'] == vm_states.ACTIVE)
        self.assertTrue(instance_ref['power_state'] == power_state.RUNNING)

        db.instance_destroy(self.context, instance_ref['uuid'])

    def test_rollback_live_migration_at_destination(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, "destroy") as mock_destroy:
            conn.rollback_live_migration_at_destination("context",
                    "instance", [], None)
            mock_destroy.assert_called_once_with("context",
                    "instance", [], None)

    def _do_test_create_images_and_backing(self, disk_type):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, '_fetch_instance_kernel_ramdisk')
        self.mox.StubOutWithMock(libvirt_driver.libvirt_utils, 'create_image')

        disk_info = {'path': 'foo', 'type': disk_type,
                     'disk_size': 1 * 1024 ** 3,
                     'virt_disk_size': 20 * 1024 ** 3,
                     'backing_file': None}
        disk_info_json = jsonutils.dumps([disk_info])

        libvirt_driver.libvirt_utils.create_image(
            disk_info['type'], mox.IgnoreArg(), disk_info['virt_disk_size'])
        conn._fetch_instance_kernel_ramdisk(self.context, self.test_instance)
        self.mox.ReplayAll()

        self.stubs.Set(os.path, 'exists', lambda *args: False)
        conn._create_images_and_backing(self.context, self.test_instance,
                                        "/fake/instance/dir", disk_info_json)

    def test_create_images_and_backing_qcow2(self):
        self._do_test_create_images_and_backing('qcow2')

    def test_create_images_and_backing_raw(self):
        self._do_test_create_images_and_backing('raw')

    def test_create_images_and_backing_ephemeral_gets_created(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        disk_info_json = jsonutils.dumps(
            [{u'backing_file': u'fake_image_backing_file',
              u'disk_size': 10747904,
              u'path': u'disk_path',
              u'type': u'qcow2',
              u'virt_disk_size': 25165824},
             {u'backing_file': u'ephemeral_1_default',
              u'disk_size': 393216,
              u'over_committed_disk_size': 1073348608,
              u'path': u'disk_eph_path',
              u'type': u'qcow2',
              u'virt_disk_size': 1073741824}])

        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        self.test_instance.update({'name': 'fake_instance',
                                   'user_id': 'fake-user',
                                   'os_type': None,
                                   'project_id': 'fake-project'})

        with contextlib.nested(
            mock.patch.object(conn, '_fetch_instance_kernel_ramdisk'),
            mock.patch.object(libvirt_driver.libvirt_utils, 'fetch_image'),
            mock.patch.object(conn, '_create_ephemeral')
        ) as (fetch_kernel_ramdisk_mock, fetch_image_mock,
                create_ephemeral_mock):
            conn._create_images_and_backing(self.context, self.test_instance,
                                            "/fake/instance/dir",
                                            disk_info_json)
            self.assertEqual(len(create_ephemeral_mock.call_args_list), 1)
            m_args, m_kwargs = create_ephemeral_mock.call_args_list[0]
            self.assertEqual(
                    os.path.join(base_dir, 'ephemeral_1_default'),
                    m_kwargs['target'])
            self.assertEqual(len(fetch_image_mock.call_args_list), 1)
            m_args, m_kwargs = fetch_image_mock.call_args_list[0]
            self.assertEqual(
                    os.path.join(base_dir, 'fake_image_backing_file'),
                    m_kwargs['target'])

    def test_create_images_and_backing_disk_info_none(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, '_fetch_instance_kernel_ramdisk')

        conn._fetch_instance_kernel_ramdisk(self.context, self.test_instance)
        self.mox.ReplayAll()

        conn._create_images_and_backing(self.context, self.test_instance,
                                        "/fake/instance/dir", None)

    def test_pre_live_migration_works_correctly_mocked(self):
        # Creating testdata
        vol = {'block_device_mapping': [
                  {'connection_info': 'dummy', 'mount_device': '/dev/sda'},
                  {'connection_info': 'dummy', 'mount_device': '/dev/sdb'}]}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        class FakeNetworkInfo():
            def fixed_ips(self):
                return ["test_ip_addr"]

        def fake_none(*args, **kwargs):
            return

        self.stubs.Set(conn, '_create_images_and_backing', fake_none)

        inst_ref = {'id': 'foo'}
        c = context.get_admin_context()
        nw_info = FakeNetworkInfo()

        # Creating mocks
        self.mox.StubOutWithMock(driver, "block_device_info_get_mapping")
        driver.block_device_info_get_mapping(vol
            ).AndReturn(vol['block_device_mapping'])
        self.mox.StubOutWithMock(conn, "volume_driver_method")
        for v in vol['block_device_mapping']:
            disk_info = {
                'bus': "scsi",
                'dev': v['mount_device'].rpartition("/")[2],
                'type': "disk"
                }
            conn.volume_driver_method('connect_volume',
                                      v['connection_info'],
                                      disk_info)
        self.mox.StubOutWithMock(conn, 'plug_vifs')
        conn.plug_vifs(mox.IsA(inst_ref), nw_info)

        self.mox.ReplayAll()
        result = conn.pre_live_migration(c, inst_ref, vol, nw_info, None)
        self.assertIsNone(result)

    def test_pre_live_migration_block_with_config_drive_mocked(self):
        # Creating testdata
        vol = {'block_device_mapping': [
                  {'connection_info': 'dummy', 'mount_device': '/dev/sda'},
                  {'connection_info': 'dummy', 'mount_device': '/dev/sdb'}]}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        def fake_true(*args, **kwargs):
            return True

        self.stubs.Set(configdrive, 'required_by', fake_true)

        inst_ref = {'id': 'foo'}
        c = context.get_admin_context()

        self.assertRaises(exception.NoBlockMigrationForConfigDriveInLibVirt,
                          conn.pre_live_migration, c, inst_ref, vol, None,
                          None, {'is_shared_storage': False})

    def test_pre_live_migration_vol_backed_works_correctly_mocked(self):
        # Creating testdata, using temp dir.
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            vol = {'block_device_mapping': [
                  {'connection_info': 'dummy', 'mount_device': '/dev/sda'},
                  {'connection_info': 'dummy', 'mount_device': '/dev/sdb'}]}
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

            def fake_none(*args, **kwargs):
                return

            self.stubs.Set(conn, '_create_images_and_backing', fake_none)

            class FakeNetworkInfo():
                def fixed_ips(self):
                    return ["test_ip_addr"]
            inst_ref = db.instance_create(self.context, self.test_instance)
            c = context.get_admin_context()
            nw_info = FakeNetworkInfo()
            # Creating mocks
            self.mox.StubOutWithMock(conn, "volume_driver_method")
            for v in vol['block_device_mapping']:
                disk_info = {
                    'bus': "scsi",
                    'dev': v['mount_device'].rpartition("/")[2],
                    'type': "disk"
                    }
                conn.volume_driver_method('connect_volume',
                                          v['connection_info'],
                                          disk_info)
            self.mox.StubOutWithMock(conn, 'plug_vifs')
            conn.plug_vifs(mox.IsA(inst_ref), nw_info)
            self.mox.ReplayAll()
            migrate_data = {'is_shared_storage': False,
                            'is_volume_backed': True,
                            'block_migration': False,
                            'instance_relative_path': inst_ref['name']
                            }
            ret = conn.pre_live_migration(c, inst_ref, vol, nw_info, None,
                                          migrate_data)
            self.assertIsNone(ret)
            self.assertTrue(os.path.exists('%s/%s/' % (tmpdir,
                                                       inst_ref['name'])))
        db.instance_destroy(self.context, inst_ref['uuid'])

    def test_pre_live_migration_plug_vifs_retry_fails(self):
        self.flags(live_migration_retry_count=3)
        instance = {'name': 'test', 'uuid': 'uuid'}

        def fake_plug_vifs(instance, network_info):
            raise processutils.ProcessExecutionError()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'plug_vifs', fake_plug_vifs)
        self.stubs.Set(eventlet.greenthread, 'sleep', lambda x: None)
        self.assertRaises(processutils.ProcessExecutionError,
                          conn.pre_live_migration,
                          self.context, instance, block_device_info=None,
                          network_info=[], disk_info={})

    def test_pre_live_migration_plug_vifs_retry_works(self):
        self.flags(live_migration_retry_count=3)
        called = {'count': 0}
        instance = {'name': 'test', 'uuid': 'uuid'}

        def fake_plug_vifs(instance, network_info):
            called['count'] += 1
            if called['count'] < CONF.live_migration_retry_count:
                raise processutils.ProcessExecutionError()
            else:
                return

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'plug_vifs', fake_plug_vifs)
        self.stubs.Set(eventlet.greenthread, 'sleep', lambda x: None)
        conn.pre_live_migration(self.context, instance, block_device_info=None,
                                network_info=[], disk_info={})

    def test_get_instance_disk_info_works_correctly(self):
        # Test data
        instance_ref = db.instance_create(self.context, self.test_instance)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "</devices></domain>")

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        fake_libvirt_utils.disk_sizes['/test/disk'] = 10 * units.Gi
        fake_libvirt_utils.disk_sizes['/test/disk.local'] = 20 * units.Gi
        fake_libvirt_utils.disk_backing_files['/test/disk.local'] = 'file'

        self.mox.StubOutWithMock(os.path, "getsize")
        os.path.getsize('/test/disk').AndReturn((10737418240))
        os.path.getsize('/test/disk.local').AndReturn((3328599655))

        ret = ("image: /test/disk\n"
               "file format: raw\n"
               "virtual size: 20G (21474836480 bytes)\n"
               "disk size: 3.1G\n"
               "cluster_size: 2097152\n"
               "backing file: /test/dummy (actual path: /backing/file)\n")

        self.mox.StubOutWithMock(os.path, "exists")
        os.path.exists('/test/disk.local').AndReturn(True)

        self.mox.StubOutWithMock(utils, "execute")
        utils.execute('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info',
                      '/test/disk.local').AndReturn((ret, ''))

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        info = conn.get_instance_disk_info(instance_ref['name'])
        info = jsonutils.loads(info)
        self.assertEqual(info[0]['type'], 'raw')
        self.assertEqual(info[0]['path'], '/test/disk')
        self.assertEqual(info[0]['disk_size'], 10737418240)
        self.assertEqual(info[0]['backing_file'], "")
        self.assertEqual(info[0]['over_committed_disk_size'], 0)
        self.assertEqual(info[1]['type'], 'qcow2')
        self.assertEqual(info[1]['path'], '/test/disk.local')
        self.assertEqual(info[1]['virt_disk_size'], 21474836480)
        self.assertEqual(info[1]['backing_file'], "file")
        self.assertEqual(info[1]['over_committed_disk_size'], 18146236825)

        db.instance_destroy(self.context, instance_ref['uuid'])

    def test_post_live_migration(self):
        vol = {'block_device_mapping': [
                  {'connection_info': 'dummy1', 'mount_device': '/dev/sda'},
                  {'connection_info': 'dummy2', 'mount_device': '/dev/sdb'}]}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        inst_ref = {'id': 'foo'}
        cntx = context.get_admin_context()

        # Set up the mock expectations
        with contextlib.nested(
            mock.patch.object(driver, 'block_device_info_get_mapping',
                              return_value=vol['block_device_mapping']),
            mock.patch.object(conn, 'volume_driver_method')
        ) as (block_device_info_get_mapping, volume_driver_method):
            conn.post_live_migration(cntx, inst_ref, vol)

            block_device_info_get_mapping.assert_has_calls([
                mock.call(vol)])
            volume_driver_method.assert_has_calls([
                mock.call('disconnect_volume',
                          v['connection_info'],
                          v['mount_device'].rpartition("/")[2])
                for v in vol['block_device_mapping']])

    def test_get_instance_disk_info_excludes_volumes(self):
        # Test data
        instance_ref = db.instance_create(self.context, self.test_instance)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/fake/path/to/volume1'/>"
                    "<target dev='vdc' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/fake/path/to/volume2'/>"
                    "<target dev='vdd' bus='virtio'/></disk>"
                    "</devices></domain>")

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        fake_libvirt_utils.disk_sizes['/test/disk'] = 10 * units.Gi
        fake_libvirt_utils.disk_sizes['/test/disk.local'] = 20 * units.Gi
        fake_libvirt_utils.disk_backing_files['/test/disk.local'] = 'file'

        self.mox.StubOutWithMock(os.path, "getsize")
        os.path.getsize('/test/disk').AndReturn((10737418240))
        os.path.getsize('/test/disk.local').AndReturn((3328599655))

        ret = ("image: /test/disk\n"
               "file format: raw\n"
               "virtual size: 20G (21474836480 bytes)\n"
               "disk size: 3.1G\n"
               "cluster_size: 2097152\n"
               "backing file: /test/dummy (actual path: /backing/file)\n")

        self.mox.StubOutWithMock(os.path, "exists")
        os.path.exists('/test/disk.local').AndReturn(True)

        self.mox.StubOutWithMock(utils, "execute")
        utils.execute('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info',
                      '/test/disk.local').AndReturn((ret, ''))

        self.mox.ReplayAll()
        conn_info = {'driver_volume_type': 'fake'}
        info = {'block_device_mapping': [
                  {'connection_info': conn_info, 'mount_device': '/dev/vdc'},
                  {'connection_info': conn_info, 'mount_device': '/dev/vdd'}]}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        info = conn.get_instance_disk_info(instance_ref['name'],
                                           block_device_info=info)
        info = jsonutils.loads(info)
        self.assertEqual(info[0]['type'], 'raw')
        self.assertEqual(info[0]['path'], '/test/disk')
        self.assertEqual(info[0]['disk_size'], 10737418240)
        self.assertEqual(info[0]['backing_file'], "")
        self.assertEqual(info[0]['over_committed_disk_size'], 0)
        self.assertEqual(info[1]['type'], 'qcow2')
        self.assertEqual(info[1]['path'], '/test/disk.local')
        self.assertEqual(info[1]['virt_disk_size'], 21474836480)
        self.assertEqual(info[1]['backing_file'], "file")
        self.assertEqual(info[1]['over_committed_disk_size'], 18146236825)

        db.instance_destroy(self.context, instance_ref['uuid'])

    def test_spawn_with_network_info(self):
        # Preparing mocks
        def fake_none(*args, **kwargs):
            return

        def fake_getLibVersion():
            return 9007

        def fake_getCapabilities():
            return """
            <capabilities>
                <host>
                    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                    <cpu>
                      <arch>x86_64</arch>
                      <model>Penryn</model>
                      <vendor>Intel</vendor>
                      <topology sockets='1' cores='2' threads='1'/>
                      <feature name='xtpr'/>
                    </cpu>
                </host>
            </capabilities>
            """

        def fake_baselineCPU(cpu, flag):
            return """<cpu mode='custom' match='exact'>
                        <model fallback='allow'>Penryn</model>
                        <vendor>Intel</vendor>
                        <feature policy='require' name='xtpr'/>
                      </cpu>
                   """

        # _fake_network_info must be called before create_fake_libvirt_mock(),
        # as _fake_network_info calls importutils.import_class() and
        # create_fake_libvirt_mock() mocks importutils.import_class().
        network_info = _fake_network_info(self.stubs, 1)
        self.create_fake_libvirt_mock(getLibVersion=fake_getLibVersion,
                                      getCapabilities=fake_getCapabilities,
                                      getVersion=lambda: 1005001,
                                      baselineCPU=fake_baselineCPU)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 123456  # we send an int to test sha1 call
        flavor = db.flavor_get(self.context, instance_ref['instance_type_id'])
        sys_meta = flavors.save_flavor_info({}, flavor)
        instance_ref['system_metadata'] = sys_meta
        instance = db.instance_create(self.context, instance_ref)

        # Mock out the get_info method of the LibvirtDriver so that the polling
        # in the spawn method of the LibvirtDriver returns immediately
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, 'get_info')
        libvirt_driver.LibvirtDriver.get_info(instance
            ).AndReturn({'state': power_state.RUNNING})

        # Start test
        self.mox.ReplayAll()

        with mock.patch('nova.virt.libvirt.driver.libvirt') as old_virt:
            del old_virt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES

            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.stubs.Set(conn.firewall_driver,
                        'setup_basic_filtering',
                        fake_none)
            self.stubs.Set(conn.firewall_driver,
                        'prepare_instance_filter',
                        fake_none)
            self.stubs.Set(imagebackend.Image,
                        'cache',
                        fake_none)

            conn.spawn(self.context, instance, None, [], 'herp',
                        network_info=network_info)

        path = os.path.join(CONF.instances_path, instance['name'])
        if os.path.isdir(path):
            shutil.rmtree(path)

        path = os.path.join(CONF.instances_path,
                            CONF.image_cache_subdirectory_name)
        if os.path.isdir(path):
            shutil.rmtree(os.path.join(CONF.instances_path,
                                       CONF.image_cache_subdirectory_name))

    def test_spawn_without_image_meta(self):
        self.create_image_called = False

        def fake_none(*args, **kwargs):
            return

        def fake_create_image(*args, **kwargs):
            self.create_image_called = True

        def fake_get_info(instance):
            return {'state': power_state.RUNNING}

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        instance = db.instance_create(self.context, instance_ref)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'to_xml', fake_none)
        self.stubs.Set(conn, '_create_image', fake_create_image)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        conn.spawn(self.context, instance, None, [], None)
        self.assertTrue(self.create_image_called)

        conn.spawn(self.context,
                   instance,
                   {'id': instance['image_ref']},
                   [],
                   None)
        self.assertTrue(self.create_image_called)

    def test_spawn_from_volume_calls_cache(self):
        self.cache_called_for_disk = False

        def fake_none(*args, **kwargs):
            return

        def fake_cache(*args, **kwargs):
            if kwargs.get('image_id') == 'my_fake_image':
                self.cache_called_for_disk = True

        def fake_get_info(instance):
            return {'state': power_state.RUNNING}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'to_xml', fake_none)

        self.stubs.Set(imagebackend.Image, 'cache', fake_cache)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        block_device_info = {'root_device_name': '/dev/vda',
                             'block_device_mapping': [
                                {'mount_device': 'vda',
                                 'boot_index': 0}
                                ]
                            }

        # Volume-backed instance created without image
        instance_ref = self.test_instance
        instance_ref['image_ref'] = ''
        instance_ref['root_device_name'] = '/dev/vda'
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance = db.instance_create(self.context, instance_ref)

        conn.spawn(self.context, instance, None, [], None,
                   block_device_info=block_device_info)
        self.assertFalse(self.cache_called_for_disk)
        db.instance_destroy(self.context, instance['uuid'])

        # Booted from volume but with placeholder image
        instance_ref = self.test_instance
        instance_ref['image_ref'] = 'my_fake_image'
        instance_ref['root_device_name'] = '/dev/vda'
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance = db.instance_create(self.context, instance_ref)

        conn.spawn(self.context, instance, None, [], None,
                   block_device_info=block_device_info)
        self.assertFalse(self.cache_called_for_disk)
        db.instance_destroy(self.context, instance['uuid'])

        # Booted from an image
        instance_ref['image_ref'] = 'my_fake_image'
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance = db.instance_create(self.context, instance_ref)
        conn.spawn(self.context, instance, None, [], None)
        self.assertTrue(self.cache_called_for_disk)
        db.instance_destroy(self.context, instance['uuid'])

    def test_spawn_with_pci_devices(self):
        def fake_none(*args, **kwargs):
            return None

        def fake_get_info(instance):
            return {'state': power_state.RUNNING}

        class FakeLibvirtPciDevice():
            def dettach(self):
                return None

            def reset(self):
                return None

        def fake_node_device_lookup_by_name(address):
            pattern = ("pci_%(hex)s{4}_%(hex)s{2}_%(hex)s{2}_%(oct)s{1}"
                       % dict(hex='[\da-f]', oct='[0-8]'))
            pattern = re.compile(pattern)
            if pattern.match(address) is None:
                raise libvirt.libvirtError()
            return FakeLibvirtPciDevice()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'to_xml', fake_none)
        self.stubs.Set(conn, '_create_image', fake_none)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        conn._conn.nodeDeviceLookupByName = \
                    fake_node_device_lookup_by_name

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 'my_fake_image'
        instance = db.instance_create(self.context, instance_ref)
        instance = dict(instance.iteritems())
        instance['pci_devices'] = [{'address': '0000:00:00.0'}]

        conn.spawn(self.context, instance, None, [], None)

    def test_chown_disk_config_for_instance(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = copy.deepcopy(self.test_instance)
        instance['name'] = 'test_name'
        self.mox.StubOutWithMock(fake_libvirt_utils, 'get_instance_path')
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(fake_libvirt_utils, 'chown')
        fake_libvirt_utils.get_instance_path(instance).AndReturn('/tmp/uuid')
        os.path.exists('/tmp/uuid/disk.config').AndReturn(True)
        fake_libvirt_utils.chown('/tmp/uuid/disk.config', os.getuid())

        self.mox.ReplayAll()
        conn._chown_disk_config_for_instance(instance)

    def _test_create_image_plain(self, os_type='', filename='', mkfs=False):
        gotFiles = []

        def fake_image(self, instance, name, image_type=''):
            class FakeImage(imagebackend.Image):
                def __init__(self, instance, name, is_block_dev=False):
                    self.path = os.path.join(instance['name'], name)
                    self.is_block_dev = is_block_dev

                def create_image(self, prepare_template, base,
                                 size, *args, **kwargs):
                    pass

                def cache(self, fetch_func, filename, size=None,
                          *args, **kwargs):
                    gotFiles.append({'filename': filename,
                                     'size': size})

                def snapshot(self, name):
                    pass

            return FakeImage(instance, name)

        def fake_none(*args, **kwargs):
            return

        def fake_get_info(instance):
            return {'state': power_state.RUNNING}

        # Stop 'libvirt_driver._create_image' touching filesystem
        self.stubs.Set(nova.virt.libvirt.imagebackend.Backend, "image",
                       fake_image)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        instance = db.instance_create(self.context, instance_ref)
        instance['os_type'] = os_type

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'to_xml', fake_none)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        if mkfs:
            self.stubs.Set(nova.virt.disk.api, '_MKFS_COMMAND',
                       {os_type: 'mkfs.ext3 --label %(fs_label)s %(target)s'})

        image_meta = {'id': instance['image_ref']}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            None,
                                            image_meta)
        conn._create_image(context, instance,
                           disk_info['mapping'])
        xml = conn.to_xml(self.context, instance, None,
                          disk_info, image_meta)

        wantFiles = [
            {'filename': '356a192b7913b04c54574d18c28d46e6395428ab',
             'size': 10 * units.Gi},
            {'filename': filename,
             'size': 20 * units.Gi},
            ]
        self.assertEqual(gotFiles, wantFiles)

    def test_create_image_plain_os_type_blank(self):
        self._test_create_image_plain(os_type='',
                                      filename='ephemeral_20_default',
                                      mkfs=False)

    def test_create_image_plain_os_type_none(self):
        self._test_create_image_plain(os_type=None,
                                      filename='ephemeral_20_default',
                                      mkfs=False)

    def test_create_image_plain_os_type_set_no_fs(self):
        self._test_create_image_plain(os_type='test',
                                      filename='ephemeral_20_default',
                                      mkfs=False)

    def test_create_image_plain_os_type_set_with_fs(self):
        self._test_create_image_plain(os_type='test',
                                      filename='ephemeral_20_test',
                                      mkfs=True)

    def test_create_image_with_swap(self):
        gotFiles = []

        def fake_image(self, instance, name, image_type=''):
            class FakeImage(imagebackend.Image):
                def __init__(self, instance, name, is_block_dev=False):
                    self.path = os.path.join(instance['name'], name)
                    self.is_block_dev = is_block_dev

                def create_image(self, prepare_template, base,
                                 size, *args, **kwargs):
                    pass

                def cache(self, fetch_func, filename, size=None,
                          *args, **kwargs):
                    gotFiles.append({'filename': filename,
                                     'size': size})

                def snapshot(self, name):
                    pass

            return FakeImage(instance, name)

        def fake_none(*args, **kwargs):
            return

        def fake_get_info(instance):
            return {'state': power_state.RUNNING}

        # Stop 'libvirt_driver._create_image' touching filesystem
        self.stubs.Set(nova.virt.libvirt.imagebackend.Backend, "image",
                       fake_image)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        # Turn on some swap to exercise that codepath in _create_image
        instance_ref['system_metadata']['instance_type_swap'] = 500
        instance = db.instance_create(self.context, instance_ref)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'to_xml', fake_none)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        image_meta = {'id': instance['image_ref']}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            None,
                                            image_meta)
        conn._create_image(context, instance,
                           disk_info['mapping'])
        xml = conn.to_xml(self.context, instance, None,
                          disk_info, image_meta)

        wantFiles = [
            {'filename': '356a192b7913b04c54574d18c28d46e6395428ab',
             'size': 10 * units.Gi},
            {'filename': 'ephemeral_20_default',
             'size': 20 * units.Gi},
            {'filename': 'swap_500',
             'size': 500 * units.Mi},
            ]
        self.assertEqual(gotFiles, wantFiles)

    def test_create_ephemeral_default(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext3', '-F', '-L', 'myVol',
                      '/dev/something', run_as_root=True)
        self.mox.ReplayAll()
        conn._create_ephemeral('/dev/something', 20, 'myVol', 'linux',
                               is_block_dev=True, max_size=20)

    def test_create_ephemeral_with_conf(self):
        CONF.set_override('default_ephemeral_format', 'ext4')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext4', '-F', '-L', 'myVol',
                      '/dev/something', run_as_root=True)
        self.mox.ReplayAll()
        conn._create_ephemeral('/dev/something', 20, 'myVol', 'linux',
                               is_block_dev=True)

    def test_create_ephemeral_with_arbitrary(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(nova.virt.disk.api, '_MKFS_COMMAND',
                       {'linux': 'mkfs.ext3 --label %(fs_label)s %(target)s'})
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs.ext3', '--label', 'myVol', '/dev/something',
                      run_as_root=True)
        self.mox.ReplayAll()
        conn._create_ephemeral('/dev/something', 20, 'myVol', 'linux',
                               is_block_dev=True)

    def test_create_swap_default(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkswap', '/dev/something', run_as_root=False)
        self.mox.ReplayAll()

        conn._create_swap('/dev/something', 1, max_size=20)

    def test_get_console_output_file(self):
        fake_libvirt_utils.files['console.log'] = '01234567890'

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)

            instance_ref = self.test_instance
            instance_ref['image_ref'] = 123456
            instance = db.instance_create(self.context, instance_ref)

            console_dir = (os.path.join(tmpdir, instance['name']))
            console_log = '%s/console.log' % (console_dir)
            fake_dom_xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                        <console type='file'>
                            <source path='%s'/>
                            <target port='0'/>
                        </console>
                    </devices>
                </domain>
            """ % console_log

            def fake_lookup(id):
                return FakeVirtDomain(fake_dom_xml)

            self.create_fake_libvirt_mock()
            libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup

            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

            try:
                prev_max = libvirt_driver.MAX_CONSOLE_BYTES
                libvirt_driver.MAX_CONSOLE_BYTES = 5
                output = conn.get_console_output(self.context, instance)
            finally:
                libvirt_driver.MAX_CONSOLE_BYTES = prev_max

            self.assertEqual('67890', output)

    def test_get_console_output_pty(self):
        fake_libvirt_utils.files['pty'] = '01234567890'

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)

            instance_ref = self.test_instance
            instance_ref['image_ref'] = 123456
            instance = db.instance_create(self.context, instance_ref)

            console_dir = (os.path.join(tmpdir, instance['name']))
            pty_file = '%s/fake_pty' % (console_dir)
            fake_dom_xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                        </disk>
                        <console type='pty'>
                            <source path='%s'/>
                            <target port='0'/>
                        </console>
                    </devices>
                </domain>
            """ % pty_file

            def fake_lookup(id):
                return FakeVirtDomain(fake_dom_xml)

            def _fake_flush(self, fake_pty):
                return 'foo'

            def _fake_append_to_file(self, data, fpath):
                return 'pty'

            self.create_fake_libvirt_mock()
            libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup
            libvirt_driver.LibvirtDriver._flush_libvirt_console = _fake_flush
            libvirt_driver.LibvirtDriver._append_to_file = _fake_append_to_file

            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

            try:
                prev_max = libvirt_driver.MAX_CONSOLE_BYTES
                libvirt_driver.MAX_CONSOLE_BYTES = 5
                output = conn.get_console_output(self.context, instance)
            finally:
                libvirt_driver.MAX_CONSOLE_BYTES = prev_max

            self.assertEqual('67890', output)

    def test_get_host_ip_addr(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        ip = conn.get_host_ip_addr()
        self.assertEqual(ip, CONF.my_ip)

    def test_broken_connection(self):
        for (error, domain) in (
                (libvirt.VIR_ERR_SYSTEM_ERROR, libvirt.VIR_FROM_REMOTE),
                (libvirt.VIR_ERR_SYSTEM_ERROR, libvirt.VIR_FROM_RPC),
                (libvirt.VIR_ERR_INTERNAL_ERROR, libvirt.VIR_FROM_RPC)):

            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

            self.mox.StubOutWithMock(conn, "_wrapped_conn")
            self.mox.StubOutWithMock(conn._wrapped_conn, "getLibVersion")
            self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
            self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_domain")

            conn._wrapped_conn.getLibVersion().AndRaise(
                    libvirt.libvirtError("fake failure"))

            libvirt.libvirtError.get_error_code().AndReturn(error)
            libvirt.libvirtError.get_error_domain().AndReturn(domain)

            self.mox.ReplayAll()

            self.assertFalse(conn._test_connection(conn._wrapped_conn))

            self.mox.UnsetStubs()

    def test_command_with_broken_connection(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
            mock.patch.object(libvirt, 'openAuth',
                              side_effect=libvirt.libvirtError("fake")),
            mock.patch.object(libvirt.libvirtError, "get_error_code"),
            mock.patch.object(libvirt.libvirtError, "get_error_domain"),
            mock.patch.object(conn, '_set_host_enabled')):
            self.assertRaises(exception.HypervisorUnavailable,
                              conn.get_num_instances)

    def test_broken_connection_disable_service(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn._init_events_pipe()
        with contextlib.nested(
            mock.patch.object(conn, '_set_host_enabled')):
            conn._close_callback(conn._wrapped_conn, 'ERROR!', '')
            conn._dispatch_events()
            conn._set_host_enabled.assert_called_once_with(
                False,
                disable_reason=u'Connection to libvirt lost: ERROR!')

    def test_service_resume_after_broken_connection(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = True
        with contextlib.nested(
            mock.patch.object(libvirt, 'openAuth',
                              return_value=mock.MagicMock()),
            mock.patch.object(service_obj.Service, "get_by_compute_host",
                              return_value=service_mock)):

            conn.get_num_instances()
            self.assertTrue(not service_mock.disabled and
                            service_mock.disabled_reason is 'None')

    def test_broken_connection_no_wrapped_conn(self):
        # Tests that calling _close_callback when _wrapped_conn is None
        # is a no-op, i.e. set_host_enabled won't be called.
        self.mox.UnsetStubs()
        # conn._wrapped_conn will be None since we never call libvirt.openAuth
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        # create our mock connection that libvirt will send to the callback
        mock_failed_conn = mock.MagicMock()
        mock_failed_conn.__getitem__.return_value = True
        # nothing should happen when calling _close_callback since
        # _wrapped_conn is None in the driver
        conn._init_events_pipe()
        conn._close_callback(mock_failed_conn, reason=None, opaque=None)
        conn._dispatch_events()

    def test_immediate_delete(self):
        def fake_lookup_by_name(instance_name):
            raise exception.InstanceNotFound(instance_id=instance_name)

        def fake_delete_instance_files(instance):
            pass

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)

        instance = db.instance_create(self.context, self.test_instance)
        conn.destroy(self.context, instance, {})

    def _test_destroy_removes_disk(self, volume_fail=False):
        instance = {"name": "instancename", "id": "42",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64",
                    "cleaned": 0, 'info_cache': None, 'security_groups': []}
        vol = {'block_device_mapping': [
              {'connection_info': 'dummy', 'mount_device': '/dev/sdb'}]}

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 '_undefine_domain')
        libvirt_driver.LibvirtDriver._undefine_domain(instance)
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(mox.IgnoreArg(), mox.IgnoreArg(),
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(instance)
        self.mox.StubOutWithMock(driver, "block_device_info_get_mapping")
        driver.block_device_info_get_mapping(vol
                                 ).AndReturn(vol['block_device_mapping'])
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 "volume_driver_method")
        if volume_fail:
            libvirt_driver.LibvirtDriver.volume_driver_method(
                        mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).\
                                     AndRaise(exception.VolumeNotFound('vol'))
        else:
            libvirt_driver.LibvirtDriver.volume_driver_method(
                        mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.StubOutWithMock(shutil, "rmtree")
        shutil.rmtree(os.path.join(CONF.instances_path,
                                   'instance-%08x' % int(instance['id'])))
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_cleanup_lvm')
        libvirt_driver.LibvirtDriver._cleanup_lvm(instance)

        # Start test
        self.mox.ReplayAll()

        def fake_destroy(instance):
            pass

        def fake_os_path_exists(path):
            return True

        def fake_unplug_vifs(instance, network_info, ignore_errors=False):
            pass

        def fake_unfilter_instance(instance, network_info):
            pass

        def fake_obj_load_attr(self, attrname):
            if not hasattr(self, attrname):
                self[attrname] = {}

        def fake_save(self, context):
            pass

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.stubs.Set(conn, '_destroy', fake_destroy)
        self.stubs.Set(conn, 'unplug_vifs', fake_unplug_vifs)
        self.stubs.Set(conn.firewall_driver,
                       'unfilter_instance', fake_unfilter_instance)
        self.stubs.Set(os.path, 'exists', fake_os_path_exists)
        self.stubs.Set(instance_obj.Instance, 'fields',
                       {'id': int, 'uuid': str, 'cleaned': int})
        self.stubs.Set(instance_obj.Instance, 'obj_load_attr',
                       fake_obj_load_attr)
        self.stubs.Set(instance_obj.Instance, 'save', fake_save)

        conn.destroy(self.context, instance, [], vol)

    def test_destroy_removes_disk(self):
        self._test_destroy_removes_disk(volume_fail=False)

    def test_destroy_removes_disk_volume_fails(self):
        self._test_destroy_removes_disk(volume_fail=True)

    def test_destroy_not_removes_disk(self):
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 '_undefine_domain')
        libvirt_driver.LibvirtDriver._undefine_domain(instance)

        # Start test
        self.mox.ReplayAll()

        def fake_destroy(instance):
            pass

        def fake_os_path_exists(path):
            return True

        def fake_unplug_vifs(instance, network_info, ignore_errors=False):
            pass

        def fake_unfilter_instance(instance, network_info):
            pass

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.stubs.Set(conn, '_destroy', fake_destroy)
        self.stubs.Set(conn, 'unplug_vifs', fake_unplug_vifs)
        self.stubs.Set(conn.firewall_driver,
                       'unfilter_instance', fake_unfilter_instance)
        self.stubs.Set(os.path, 'exists', fake_os_path_exists)
        conn.destroy(self.context, instance, [], None, False)

    def test_delete_instance_files(self):
        instance = {"name": "instancename", "id": "42",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64",
                    "cleaned": 0, 'info_cache': None, 'security_groups': []}

        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(shutil, "rmtree")

        db.instance_get_by_uuid(mox.IgnoreArg(), mox.IgnoreArg(),
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(instance)
        os.path.exists(mox.IgnoreArg()).AndReturn(False)
        os.path.exists(mox.IgnoreArg()).AndReturn(True)
        shutil.rmtree(os.path.join(CONF.instances_path, instance['uuid']))
        os.path.exists(mox.IgnoreArg()).AndReturn(True)
        os.path.exists(mox.IgnoreArg()).AndReturn(False)
        os.path.exists(mox.IgnoreArg()).AndReturn(True)
        shutil.rmtree(os.path.join(CONF.instances_path, instance['uuid']))
        os.path.exists(mox.IgnoreArg()).AndReturn(False)
        self.mox.ReplayAll()

        def fake_obj_load_attr(self, attrname):
            if not hasattr(self, attrname):
                self[attrname] = {}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(instance_obj.Instance, 'fields',
                       {'id': int, 'uuid': str, 'cleaned': int})
        self.stubs.Set(instance_obj.Instance, 'obj_load_attr',
                       fake_obj_load_attr)

        inst_obj = instance_obj.Instance.get_by_uuid(None, instance['uuid'])
        self.assertFalse(conn.delete_instance_files(inst_obj))
        self.assertTrue(conn.delete_instance_files(inst_obj))

    def test_reboot_different_ids(self):
        class FakeLoopingCall:
            def start(self, *a, **k):
                return self

            def wait(self):
                return None

        self.flags(wait_soft_reboot_seconds=1, group='libvirt')
        info_tuple = ('fake', 'fake', 'fake', 'also_fake')
        self.reboot_create_called = False

        # Mock domain
        mock_domain = self.mox.CreateMock(libvirt.virDomain)
        mock_domain.info().AndReturn(
            (libvirt_driver.VIR_DOMAIN_RUNNING,) + info_tuple)
        mock_domain.ID().AndReturn('some_fake_id')
        mock_domain.shutdown()
        mock_domain.info().AndReturn(
            (libvirt_driver.VIR_DOMAIN_CRASHED,) + info_tuple)
        mock_domain.ID().AndReturn('some_other_fake_id')

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock_domain

        def fake_create_domain(**kwargs):
            self.reboot_create_called = True

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64",
                    "pci_devices": []}
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_create_domain', fake_create_domain)
        self.stubs.Set(loopingcall, 'FixedIntervalLoopingCall',
                       lambda *a, **k: FakeLoopingCall())
        conn.reboot(None, instance, [])
        self.assertTrue(self.reboot_create_called)

    def test_reboot_same_ids(self):
        class FakeLoopingCall:
            def start(self, *a, **k):
                return self

            def wait(self):
                return None

        self.flags(wait_soft_reboot_seconds=1, group='libvirt')
        info_tuple = ('fake', 'fake', 'fake', 'also_fake')
        self.reboot_hard_reboot_called = False

        # Mock domain
        mock_domain = self.mox.CreateMock(libvirt.virDomain)
        mock_domain.info().AndReturn(
            (libvirt_driver.VIR_DOMAIN_RUNNING,) + info_tuple)
        mock_domain.ID().AndReturn('some_fake_id')
        mock_domain.shutdown()
        mock_domain.info().AndReturn(
            (libvirt_driver.VIR_DOMAIN_CRASHED,) + info_tuple)
        mock_domain.ID().AndReturn('some_fake_id')

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock_domain

        def fake_hard_reboot(*args, **kwargs):
            self.reboot_hard_reboot_called = True

        def fake_sleep(interval):
            pass

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64",
                    "pci_devices": []}
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(greenthread, 'sleep', fake_sleep)
        self.stubs.Set(conn, '_hard_reboot', fake_hard_reboot)
        self.stubs.Set(loopingcall, 'FixedIntervalLoopingCall',
                       lambda *a, **k: FakeLoopingCall())
        conn.reboot(None, instance, [])
        self.assertTrue(self.reboot_hard_reboot_called)

    def test_soft_reboot_libvirt_exception(self):
        # Tests that a hard reboot is performed when a soft reboot results
        # in raising a libvirtError.
        info_tuple = ('fake', 'fake', 'fake', 'also_fake')

        # setup mocks
        mock_domain = self.mox.CreateMock(libvirt.virDomain)
        mock_domain.info().AndReturn(
            (libvirt_driver.VIR_DOMAIN_RUNNING,) + info_tuple)
        mock_domain.ID().AndReturn('some_fake_id')
        mock_domain.shutdown().AndRaise(libvirt.libvirtError('Err'))

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        context = None
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        network_info = []

        self.mox.StubOutWithMock(conn, '_lookup_by_name')
        conn._lookup_by_name(instance['name']).AndReturn(mock_domain)
        self.mox.StubOutWithMock(conn, '_hard_reboot')
        conn._hard_reboot(context, instance, network_info, None)

        self.mox.ReplayAll()

        conn.reboot(context, instance, network_info)

    def _test_resume_state_on_host_boot_with_state(self, state):
        called = {'count': 0}
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.info().AndReturn([state, None, None, None, None])
        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_hard_reboot(*args):
            called['count'] += 1

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_hard_reboot', fake_hard_reboot)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        network_info = _fake_network_info(self.stubs, 1)

        conn.resume_state_on_host_boot(self.context, instance, network_info,
                                       block_device_info=None)

        ignored_states = (power_state.RUNNING,
                          power_state.SUSPENDED,
                          power_state.NOSTATE,
                          power_state.PAUSED)
        if state in ignored_states:
            self.assertEqual(called['count'], 0)
        else:
            self.assertEqual(called['count'], 1)

    def test_resume_state_on_host_boot_with_running_state(self):
        self._test_resume_state_on_host_boot_with_state(power_state.RUNNING)

    def test_resume_state_on_host_boot_with_suspended_state(self):
        self._test_resume_state_on_host_boot_with_state(power_state.SUSPENDED)

    def test_resume_state_on_host_boot_with_paused_state(self):
        self._test_resume_state_on_host_boot_with_state(power_state.PAUSED)

    def test_resume_state_on_host_boot_with_nostate(self):
        self._test_resume_state_on_host_boot_with_state(power_state.NOSTATE)

    def test_resume_state_on_host_boot_with_shutdown_state(self):
        self._test_resume_state_on_host_boot_with_state(power_state.RUNNING)

    def test_resume_state_on_host_boot_with_crashed_state(self):
        self._test_resume_state_on_host_boot_with_state(power_state.CRASHED)

    def test_resume_state_on_host_boot_with_instance_not_found_on_driver(self):
        called = {'count': 0}
        instance = {'name': 'test'}

        def fake_instance_exists(name):
            return False

        def fake_hard_reboot(*args):
            called['count'] += 1

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, 'instance_exists', fake_instance_exists)
        self.stubs.Set(conn, '_hard_reboot', fake_hard_reboot)
        conn.resume_state_on_host_boot(self.context, instance, network_info=[],
                                       block_device_info=None)

        self.assertEqual(called['count'], 1)

    def test_hard_reboot(self):
        called = {'count': 0}
        instance = db.instance_create(self.context, self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)
        block_device_info = None

        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "</devices></domain>")

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.mox.StubOutWithMock(conn, '_destroy')
        self.mox.StubOutWithMock(conn, 'get_instance_disk_info')
        self.mox.StubOutWithMock(conn, 'to_xml')
        self.mox.StubOutWithMock(conn, '_create_images_and_backing')
        self.mox.StubOutWithMock(conn, '_create_domain_and_network')

        def fake_get_info(instance_name):
            called['count'] += 1
            if called['count'] == 1:
                state = power_state.SHUTDOWN
            else:
                state = power_state.RUNNING
            return dict(state=state)

        self.stubs.Set(conn, 'get_info', fake_get_info)

        conn._destroy(instance)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance, block_device_info)
        conn.to_xml(self.context, instance, network_info, disk_info,
                    block_device_info=block_device_info,
                    write_to_disk=True).AndReturn(dummyxml)
        disk_info_json = '[{"virt_disk_size": 2}]'
        conn.get_instance_disk_info(instance["name"], dummyxml,
                            block_device_info).AndReturn(disk_info_json)
        conn._create_images_and_backing(self.context, instance,
                                libvirt_utils.get_instance_path(instance),
                                disk_info_json)
        conn._create_domain_and_network(self.context, dummyxml, instance,
                                        network_info, block_device_info,
                                        reboot=True, vifs_already_plugged=True)
        self.mox.ReplayAll()

        conn._hard_reboot(self.context, instance, network_info,
                          block_device_info)

    def test_power_on(self):

        def _check_xml_bus(name, xml, block_info):
            tree = etree.fromstring(xml)
            got_disks = tree.findall('./devices/disk')
            got_disk_targets = tree.findall('./devices/disk/target')
            system_meta = utils.instance_sys_meta(instance)
            image_meta = utils.get_image_from_system_metadata(system_meta)
            want_device_bus = image_meta.get('hw_disk_bus')
            if not want_device_bus:
                want_device_bus = self.fake_img['properties']['hw_disk_bus']
            got_device_bus = got_disk_targets[0].get('bus')
            self.assertEqual(got_device_bus, want_device_bus)

        def fake_get_info(instance_name):
            called['count'] += 1
            if called['count'] == 1:
                state = power_state.SHUTDOWN
            else:
                state = power_state.RUNNING
            return dict(state=state)

        def _get_inst(with_meta=True):
            inst_ref = self.test_instance
            inst_ref['uuid'] = uuidutils.generate_uuid()
            if with_meta:
                inst_ref['system_metadata']['image_hw_disk_bus'] = 'ide'
            instance = db.instance_create(self.context, inst_ref)
            instance['image_ref'] = '70a599e0-31e7-49b7-b260-868f221a761e'
            return instance

        called = {'count': 0}
        self.fake_img = {'id': '70a599e0-31e7-49b7-b260-868f221a761e',
                         'name': 'myfakeimage',
                         'created_at': '',
                         'updated_at': '',
                         'deleted_at': None,
                         'deleted': False,
                         'status': 'active',
                         'is_public': False,
                         'container_format': 'bare',
                         'disk_format': 'qcow2',
                         'size': '74185822',
                         'properties': {'hw_disk_bus': 'ide'}}

        instance = _get_inst()
        network_info = _fake_network_info(self.stubs, 1)
        block_device_info = None
        image_service_mock = mock.Mock()
        image_service_mock.show.return_value = self.fake_img

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
            mock.patch.object(conn, '_destroy', return_value=None),
            mock.patch.object(conn, '_create_images_and_backing'),
            mock.patch.object(conn, '_create_domain_and_network'),
            mock.patch('nova.image.glance.get_remote_image_service',
                       return_value=(image_service_mock,
                       instance['image_ref']))):
            conn.get_info = fake_get_info
            conn.get_instance_disk_info = _check_xml_bus
            conn._hard_reboot(self.context, instance, network_info,
                              block_device_info)

            instance = _get_inst(with_meta=False)
            conn._hard_reboot(self.context, instance, network_info,
                              block_device_info)

    def test_resume(self):
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "</devices></domain>")
        instance = db.instance_create(self.context, self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)
        block_device_info = None
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
            mock.patch.object(conn, '_get_existing_domain_xml',
                              return_value=dummyxml),
            mock.patch.object(conn, '_create_domain_and_network',
                              return_value='fake_dom'),
            mock.patch.object(conn, '_attach_pci_devices'),
            mock.patch.object(pci_manager, 'get_instance_pci_devs',
                              return_value='fake_pci_devs'),
        ) as (_get_existing_domain_xml, _create_domain_and_network,
              _attach_pci_devices, get_instance_pci_devs):
            conn.resume(self.context, instance, network_info,
                        block_device_info)
            _get_existing_domain_xml.assert_has_calls([mock.call(instance,
                                            network_info, block_device_info)])
            _create_domain_and_network.assert_has_calls([mock.call(
                                        self.context, dummyxml,
                                        instance, network_info,
                                        block_device_info=block_device_info,
                                        vifs_already_plugged=True)])
            _attach_pci_devices.assert_has_calls([mock.call('fake_dom',
                                                 'fake_pci_devs')])

    def test_destroy_undefines(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy()
        mock.undefineFlags(1).AndReturn(1)

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            return {'state': power_state.SHUTDOWN, 'id': -1}

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)

        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        conn.destroy(self.context, instance, [])

    def test_cleanup_rbd(self):
        mock = self.mox.CreateMock(libvirt.virDomain)

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            return {'state': power_state.SHUTDOWN, 'id': -1}

        fake_volumes = ['875a8070-d0b9-4949-8b31-104d125c9a64.local',
                        '875a8070-d0b9-4949-8b31-104d125c9a64.swap',
                        '875a8070-d0b9-4949-8b31-104d125c9a64',
                        'wrong875a8070-d0b9-4949-8b31-104d125c9a64']
        fake_pool = 'fake_pool'
        fake_instance = {'name': 'fakeinstancename', 'id': 'instanceid',
                         'uuid': '875a8070-d0b9-4949-8b31-104d125c9a64'}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        self.flags(images_rbd_pool=fake_pool, group='libvirt')
        self.mox.StubOutWithMock(libvirt_driver.libvirt_utils,
                                 'remove_rbd_volumes')
        libvirt_driver.libvirt_utils.remove_rbd_volumes(fake_pool,
                                                        *fake_volumes[:3])

        self.mox.ReplayAll()

        conn._cleanup_rbd(fake_instance)

        self.mox.VerifyAll()

    def test_destroy_undefines_no_undefine_flags(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy()
        mock.undefineFlags(1).AndRaise(libvirt.libvirtError('Err'))
        mock.undefine()

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            return {'state': power_state.SHUTDOWN, 'id': -1}

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        conn.destroy(self.context, instance, [])

    def test_destroy_undefines_no_attribute_with_managed_save(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy()
        mock.undefineFlags(1).AndRaise(AttributeError())
        mock.hasManagedSaveImage(0).AndReturn(True)
        mock.managedSaveRemove(0)
        mock.undefine()

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            return {'state': power_state.SHUTDOWN, 'id': -1}

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        conn.destroy(self.context, instance, [])

    def test_destroy_undefines_no_attribute_no_managed_save(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy()
        mock.undefineFlags(1).AndRaise(AttributeError())
        mock.hasManagedSaveImage(0).AndRaise(AttributeError())
        mock.undefine()

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            return {'state': power_state.SHUTDOWN, 'id': -1}

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        conn.destroy(self.context, instance, [])

    def test_destroy_timed_out(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy().AndRaise(libvirt.libvirtError("timed out"))
        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_error_code(self):
            return libvirt.VIR_ERR_OPERATION_TIMEOUT

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(libvirt.libvirtError, 'get_error_code',
                fake_get_error_code)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        self.assertRaises(exception.InstancePowerOffFailure,
                conn.destroy, self.context, instance, [])

    def test_private_destroy_not_found(self):
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy()
        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        def fake_get_info(instance_name):
            raise exception.InstanceNotFound(instance_id=instance_name)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        instance = {"name": "instancename", "id": "instanceid",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        # NOTE(vish): verifies destroy doesn't raise if the instance disappears
        conn._destroy(instance)

    def test_undefine_domain_with_not_found_instance(self):
        def fake_lookup(instance_name):
            raise libvirt.libvirtError("not found")

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup
        self.mox.StubOutWithMock(libvirt.libvirtError, "get_error_code")
        libvirt.libvirtError.get_error_code().AndReturn(
            libvirt.VIR_ERR_NO_DOMAIN)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = {'name': 'test'}

        # NOTE(wenjianhn): verifies undefine doesn't raise if the
        # instance disappears
        conn._undefine_domain(instance)

    def test_disk_over_committed_size_total(self):
        # Ensure destroy calls managedSaveRemove for saved instance.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        def list_instances():
            return ['fake1', 'fake2']
        self.stubs.Set(conn, 'list_instances', list_instances)

        fake_disks = {'fake1': [{'type': 'qcow2', 'path': '/somepath/disk1',
                                 'virt_disk_size': '10737418240',
                                 'backing_file': '/somepath/disk1',
                                 'disk_size': '83886080',
                                 'over_committed_disk_size': '10653532160'}],
                      'fake2': [{'type': 'raw', 'path': '/somepath/disk2',
                                 'virt_disk_size': '0',
                                 'backing_file': '/somepath/disk2',
                                 'disk_size': '10737418240',
                                 'over_committed_disk_size': '0'}]}

        def get_info(instance_name):
            return jsonutils.dumps(fake_disks.get(instance_name))
        self.stubs.Set(conn, 'get_instance_disk_info', get_info)

        result = conn.get_disk_over_committed_size_total()
        self.assertEqual(result, 10653532160)

    def test_cpu_info(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigCPU()
            cpu.model = "Opteron_G4"
            cpu.vendor = "AMD"
            cpu.arch = "x86_64"

            cpu.cores = 2
            cpu.threads = 1
            cpu.sockets = 4

            cpu.add_feature(vconfig.LibvirtConfigCPUFeature("extapic"))
            cpu.add_feature(vconfig.LibvirtConfigCPUFeature("3dnow"))

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = vm_mode.HVM
            guest.arch = "x86_64"
            guest.domtype = ["kvm"]
            caps.guests.append(guest)

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = vm_mode.HVM
            guest.arch = "i686"
            guest.domtype = ["kvm"]
            caps.guests.append(guest)

            return caps

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       'get_host_capabilities',
                       get_host_capabilities_stub)

        want = {"vendor": "AMD",
                "features": ["extapic", "3dnow"],
                "model": "Opteron_G4",
                "arch": "x86_64",
                "topology": {"cores": 2, "threads": 1, "sockets": 4}}
        got = jsonutils.loads(conn.get_cpu_info())
        self.assertEqual(want, got)

    def test_get_pcidev_info(self):

        def fake_nodeDeviceLookupByName(name):
            return FakeNodeDevice(_fake_NodeDevXml[name])

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.nodeDeviceLookupByName =\
                                             fake_nodeDeviceLookupByName

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actualvf = conn._get_pcidev_info("pci_0000_04_00_3")
        expect_vf = {
            "dev_id": "pci_0000_04_00_3",
            "address": "0000:04:00.3",
            "product_id": '1521',
            "vendor_id": '8086',
            "label": 'label_8086_1521',
            "dev_type": 'type-PF',
            }

        self.assertEqual(actualvf, expect_vf)
        actualvf = conn._get_pcidev_info("pci_0000_04_10_7")
        expect_vf = {
            "dev_id": "pci_0000_04_10_7",
            "address": "0000:04:10.7",
            "product_id": '1520',
            "vendor_id": '8086',
            "label": 'label_8086_1520',
            "dev_type": 'type-VF',
            "phys_function": '0000:04:00.3',
            }

        self.assertEqual(actualvf, expect_vf)

    def test_pci_device_assignable(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn.dev_filter, 'device_assignable', lambda x: True)

        fake_dev = {'dev_type': 'type-PF'}
        self.assertFalse(conn._pci_device_assignable(fake_dev))
        fake_dev = {'dev_type': 'type-VF'}
        self.assertTrue(conn._pci_device_assignable(fake_dev))
        fake_dev = {'dev_type': 'type-PCI'}
        self.assertTrue(conn._pci_device_assignable(fake_dev))

    def test_get_pci_passthrough_devices(self):

        def fakelistDevices(caps, fakeargs=0):
            return ['pci_0000_04_00_3', 'pci_0000_04_10_7']

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.listDevices = fakelistDevices

        def fake_nodeDeviceLookupByName(name):
            return FakeNodeDevice(_fake_NodeDevXml[name])

        libvirt_driver.LibvirtDriver._conn.nodeDeviceLookupByName =\
                                             fake_nodeDeviceLookupByName
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn.dev_filter, 'device_assignable', lambda x: x)
        actjson = conn.get_pci_passthrough_devices()

        expectvfs = [
            {
                "dev_id": "pci_0000_04_00_3",
                "address": "0000:04:10.3",
                "product_id": '1521',
                "vendor_id": '8086',
                "dev_type": 'type-PF',
                "phys_function": None},
            {
                "dev_id": "pci_0000_04_10_7",
                "domain": 0,
                "address": "0000:04:10.7",
                "product_id": '1520',
                "vendor_id": '8086',
                "dev_type": 'type-VF',
                "phys_function": [('0x0000', '0x04', '0x00', '0x3')],
            }
        ]

        actctualvfs = jsonutils.loads(actjson)
        for key in actctualvfs[0].keys():
            if key not in ['phys_function', 'virt_functions', 'label']:
                self.assertEqual(actctualvfs[0][key], expectvfs[1][key])

    def test_diagnostic_vcpus_exception(self):
        xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                        <interface type='network'>
                            <mac address='52:54:00:a4:38:38'/>
                            <source network='default'/>
                            <target dev='vnet0'/>
                        </interface>
                    </devices>
                </domain>
            """

        class DiagFakeDomain(FakeVirtDomain):

            def __init__(self):
                super(DiagFakeDomain, self).__init__(fake_xml=xml)

            def vcpus(self):
                raise libvirt.libvirtError('vcpus missing')

            def blockStats(self, path):
                return (169L, 688640L, 0L, 0L, -1L)

            def interfaceStats(self, path):
                return (4408L, 82L, 0L, 0L, 0L, 0L, 0L, 0L)

            def memoryStats(self):
                return {'actual': 220160L, 'rss': 200164L}

            def maxMemory(self):
                return 280160L

        def fake_lookup_name(name):
            return DiagFakeDomain()

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actual = conn.get_diagnostics({"name": "testvirt"})
        expect = {'vda_read': 688640L,
                  'vda_read_req': 169L,
                  'vda_write': 0L,
                  'vda_write_req': 0L,
                  'vda_errors': -1L,
                  'vdb_read': 688640L,
                  'vdb_read_req': 169L,
                  'vdb_write': 0L,
                  'vdb_write_req': 0L,
                  'vdb_errors': -1L,
                  'memory': 280160L,
                  'memory-actual': 220160L,
                  'memory-rss': 200164L,
                  'vnet0_rx': 4408L,
                  'vnet0_rx_drop': 0L,
                  'vnet0_rx_errors': 0L,
                  'vnet0_rx_packets': 82L,
                  'vnet0_tx': 0L,
                  'vnet0_tx_drop': 0L,
                  'vnet0_tx_errors': 0L,
                  'vnet0_tx_packets': 0L,
                  }
        self.assertEqual(actual, expect)

    def test_diagnostic_blockstats_exception(self):
        xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                        <interface type='network'>
                            <mac address='52:54:00:a4:38:38'/>
                            <source network='default'/>
                            <target dev='vnet0'/>
                        </interface>
                    </devices>
                </domain>
            """

        class DiagFakeDomain(FakeVirtDomain):

            def __init__(self):
                super(DiagFakeDomain, self).__init__(fake_xml=xml)

            def vcpus(self):
                return ([(0, 1, 15340000000L, 0),
                         (1, 1, 1640000000L, 0),
                         (2, 1, 3040000000L, 0),
                         (3, 1, 1420000000L, 0)],
                        [(True, False),
                         (True, False),
                         (True, False),
                         (True, False)])

            def blockStats(self, path):
                raise libvirt.libvirtError('blockStats missing')

            def interfaceStats(self, path):
                return (4408L, 82L, 0L, 0L, 0L, 0L, 0L, 0L)

            def memoryStats(self):
                return {'actual': 220160L, 'rss': 200164L}

            def maxMemory(self):
                return 280160L

        def fake_lookup_name(name):
            return DiagFakeDomain()

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actual = conn.get_diagnostics({"name": "testvirt"})
        expect = {'cpu0_time': 15340000000L,
                  'cpu1_time': 1640000000L,
                  'cpu2_time': 3040000000L,
                  'cpu3_time': 1420000000L,
                  'memory': 280160L,
                  'memory-actual': 220160L,
                  'memory-rss': 200164L,
                  'vnet0_rx': 4408L,
                  'vnet0_rx_drop': 0L,
                  'vnet0_rx_errors': 0L,
                  'vnet0_rx_packets': 82L,
                  'vnet0_tx': 0L,
                  'vnet0_tx_drop': 0L,
                  'vnet0_tx_errors': 0L,
                  'vnet0_tx_packets': 0L,
                  }
        self.assertEqual(actual, expect)

    def test_diagnostic_interfacestats_exception(self):
        xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                        <interface type='network'>
                            <mac address='52:54:00:a4:38:38'/>
                            <source network='default'/>
                            <target dev='vnet0'/>
                        </interface>
                    </devices>
                </domain>
            """

        class DiagFakeDomain(FakeVirtDomain):

            def __init__(self):
                super(DiagFakeDomain, self).__init__(fake_xml=xml)

            def vcpus(self):
                return ([(0, 1, 15340000000L, 0),
                         (1, 1, 1640000000L, 0),
                         (2, 1, 3040000000L, 0),
                         (3, 1, 1420000000L, 0)],
                        [(True, False),
                         (True, False),
                         (True, False),
                         (True, False)])

            def blockStats(self, path):
                return (169L, 688640L, 0L, 0L, -1L)

            def interfaceStats(self, path):
                raise libvirt.libvirtError('interfaceStat missing')

            def memoryStats(self):
                return {'actual': 220160L, 'rss': 200164L}

            def maxMemory(self):
                return 280160L

        def fake_lookup_name(name):
            return DiagFakeDomain()

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actual = conn.get_diagnostics({"name": "testvirt"})
        expect = {'cpu0_time': 15340000000L,
                  'cpu1_time': 1640000000L,
                  'cpu2_time': 3040000000L,
                  'cpu3_time': 1420000000L,
                  'vda_read': 688640L,
                  'vda_read_req': 169L,
                  'vda_write': 0L,
                  'vda_write_req': 0L,
                  'vda_errors': -1L,
                  'vdb_read': 688640L,
                  'vdb_read_req': 169L,
                  'vdb_write': 0L,
                  'vdb_write_req': 0L,
                  'vdb_errors': -1L,
                  'memory': 280160L,
                  'memory-actual': 220160L,
                  'memory-rss': 200164L,
                  }
        self.assertEqual(actual, expect)

    def test_diagnostic_memorystats_exception(self):
        xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                        <interface type='network'>
                            <mac address='52:54:00:a4:38:38'/>
                            <source network='default'/>
                            <target dev='vnet0'/>
                        </interface>
                    </devices>
                </domain>
            """

        class DiagFakeDomain(FakeVirtDomain):

            def __init__(self):
                super(DiagFakeDomain, self).__init__(fake_xml=xml)

            def vcpus(self):
                return ([(0, 1, 15340000000L, 0),
                         (1, 1, 1640000000L, 0),
                         (2, 1, 3040000000L, 0),
                         (3, 1, 1420000000L, 0)],
                        [(True, False),
                         (True, False),
                         (True, False),
                         (True, False)])

            def blockStats(self, path):
                return (169L, 688640L, 0L, 0L, -1L)

            def interfaceStats(self, path):
                return (4408L, 82L, 0L, 0L, 0L, 0L, 0L, 0L)

            def memoryStats(self):
                raise libvirt.libvirtError('memoryStats missing')

            def maxMemory(self):
                return 280160L

        def fake_lookup_name(name):
            return DiagFakeDomain()

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actual = conn.get_diagnostics({"name": "testvirt"})
        expect = {'cpu0_time': 15340000000L,
                  'cpu1_time': 1640000000L,
                  'cpu2_time': 3040000000L,
                  'cpu3_time': 1420000000L,
                  'vda_read': 688640L,
                  'vda_read_req': 169L,
                  'vda_write': 0L,
                  'vda_write_req': 0L,
                  'vda_errors': -1L,
                  'vdb_read': 688640L,
                  'vdb_read_req': 169L,
                  'vdb_write': 0L,
                  'vdb_write_req': 0L,
                  'vdb_errors': -1L,
                  'memory': 280160L,
                  'vnet0_rx': 4408L,
                  'vnet0_rx_drop': 0L,
                  'vnet0_rx_errors': 0L,
                  'vnet0_rx_packets': 82L,
                  'vnet0_tx': 0L,
                  'vnet0_tx_drop': 0L,
                  'vnet0_tx_errors': 0L,
                  'vnet0_tx_packets': 0L,
                  }
        self.assertEqual(actual, expect)

    def test_diagnostic_full(self):
        xml = """
                <domain type='kvm'>
                    <devices>
                        <disk type='file'>
                            <source file='filename'/>
                            <target dev='vda' bus='virtio'/>
                        </disk>
                        <disk type='block'>
                            <source dev='/path/to/dev/1'/>
                            <target dev='vdb' bus='virtio'/>
                        </disk>
                        <interface type='network'>
                            <mac address='52:54:00:a4:38:38'/>
                            <source network='default'/>
                            <target dev='vnet0'/>
                        </interface>
                    </devices>
                </domain>
            """

        class DiagFakeDomain(FakeVirtDomain):

            def __init__(self):
                super(DiagFakeDomain, self).__init__(fake_xml=xml)

            def vcpus(self):
                return ([(0, 1, 15340000000L, 0),
                         (1, 1, 1640000000L, 0),
                         (2, 1, 3040000000L, 0),
                         (3, 1, 1420000000L, 0)],
                        [(True, False),
                         (True, False),
                         (True, False),
                         (True, False)])

            def blockStats(self, path):
                return (169L, 688640L, 0L, 0L, -1L)

            def interfaceStats(self, path):
                return (4408L, 82L, 0L, 0L, 0L, 0L, 0L, 0L)

            def memoryStats(self):
                return {'actual': 220160L, 'rss': 200164L}

            def maxMemory(self):
                return 280160L

        def fake_lookup_name(name):
            return DiagFakeDomain()

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        actual = conn.get_diagnostics({"name": "testvirt"})
        expect = {'cpu0_time': 15340000000L,
                  'cpu1_time': 1640000000L,
                  'cpu2_time': 3040000000L,
                  'cpu3_time': 1420000000L,
                  'vda_read': 688640L,
                  'vda_read_req': 169L,
                  'vda_write': 0L,
                  'vda_write_req': 0L,
                  'vda_errors': -1L,
                  'vdb_read': 688640L,
                  'vdb_read_req': 169L,
                  'vdb_write': 0L,
                  'vdb_write_req': 0L,
                  'vdb_errors': -1L,
                  'memory': 280160L,
                  'memory-actual': 220160L,
                  'memory-rss': 200164L,
                  'vnet0_rx': 4408L,
                  'vnet0_rx_drop': 0L,
                  'vnet0_rx_errors': 0L,
                  'vnet0_rx_packets': 82L,
                  'vnet0_tx': 0L,
                  'vnet0_tx_drop': 0L,
                  'vnet0_tx_errors': 0L,
                  'vnet0_tx_packets': 0L,
                  }
        self.assertEqual(actual, expect)

    def test_failing_vcpu_count(self):
        """Domain can fail to return the vcpu description in case it's
        just starting up or shutting down. Make sure None is handled
        gracefully.
        """

        class DiagFakeDomain(object):
            def __init__(self, vcpus):
                self._vcpus = vcpus

            def vcpus(self):
                if self._vcpus is None:
                    raise libvirt.libvirtError("fake-error")
                else:
                    return ([1] * self._vcpus, [True] * self._vcpus)

        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conn = driver._conn
        self.mox.StubOutWithMock(driver, 'list_instance_ids')
        conn.lookupByID = self.mox.CreateMockAnything()

        driver.list_instance_ids().AndReturn([1, 2])
        conn.lookupByID(1).AndReturn(DiagFakeDomain(None))
        conn.lookupByID(2).AndReturn(DiagFakeDomain(5))

        self.mox.ReplayAll()
        self.assertEqual(5, driver.get_vcpu_used())

    def test_failing_vcpu_count_none(self):
        """Domain will return zero if the current number of vcpus used
        is None. This is in case of VM state starting up or shutting
        down. None type returned is counted as zero.
        """

        class DiagFakeDomain(object):
            def __init__(self):
                pass

            def vcpus(self):
                return None

        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conn = driver._conn
        self.mox.StubOutWithMock(driver, 'list_instance_ids')
        conn.lookupByID = self.mox.CreateMockAnything()

        driver.list_instance_ids().AndReturn([1])
        conn.lookupByID(1).AndReturn(DiagFakeDomain())

        self.mox.ReplayAll()
        self.assertEqual(0, driver.get_vcpu_used())

    def test_get_instance_capabilities(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        def get_host_capabilities_stub(self):
            caps = vconfig.LibvirtConfigCaps()

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = 'hvm'
            guest.arch = 'x86_64'
            guest.domtype = ['kvm', 'qemu']
            caps.guests.append(guest)

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = 'hvm'
            guest.arch = 'i686'
            guest.domtype = ['kvm']
            caps.guests.append(guest)

            return caps

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       'get_host_capabilities',
                       get_host_capabilities_stub)

        want = [('x86_64', 'kvm', 'hvm'),
                ('x86_64', 'qemu', 'hvm'),
                ('i686', 'kvm', 'hvm')]
        got = conn.get_instance_capabilities()
        self.assertEqual(want, got)

    def test_event_dispatch(self):
        # Validate that the libvirt self-pipe for forwarding
        # events between threads is working sanely
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        got_events = []

        def handler(event):
            got_events.append(event)

        conn.register_event_listener(handler)

        conn._init_events_pipe()

        event1 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STARTED)
        event2 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_PAUSED)
        conn._queue_event(event1)
        conn._queue_event(event2)
        conn._dispatch_events()

        want_events = [event1, event2]
        self.assertEqual(want_events, got_events)

        event3 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_RESUMED)
        event4 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STOPPED)

        conn._queue_event(event3)
        conn._queue_event(event4)
        conn._dispatch_events()

        want_events = [event1, event2, event3, event4]
        self.assertEqual(want_events, got_events)

    def test_event_lifecycle(self):
        # Validate that libvirt events are correctly translated
        # to Nova events
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        got_events = []

        def handler(event):
            got_events.append(event)

        conn.register_event_listener(handler)
        conn._init_events_pipe()
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
        dom = FakeVirtDomain(fake_dom_xml,
                             "cef19ce0-0ca2-11df-855d-b19fbce37686")

        conn._event_lifecycle_callback(conn._conn,
                                       dom,
                                       libvirt.VIR_DOMAIN_EVENT_STOPPED,
                                       0,
                                       conn)
        conn._dispatch_events()
        self.assertEqual(len(got_events), 1)
        self.assertIsInstance(got_events[0], virtevent.LifecycleEvent)
        self.assertEqual(got_events[0].uuid,
                         "cef19ce0-0ca2-11df-855d-b19fbce37686")
        self.assertEqual(got_events[0].transition,
                         virtevent.EVENT_LIFECYCLE_STOPPED)

    def test_set_cache_mode(self):
        self.flags(disk_cachemodes=['file=directsync'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuestDisk()

        fake_conf.source_type = 'file'
        conn.set_cache_mode(fake_conf)
        self.assertEqual(fake_conf.driver_cache, 'directsync')

    def test_set_cache_mode_invalid_mode(self):
        self.flags(disk_cachemodes=['file=FAKE'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuestDisk()

        fake_conf.source_type = 'file'
        conn.set_cache_mode(fake_conf)
        self.assertIsNone(fake_conf.driver_cache)

    def test_set_cache_mode_invalid_object(self):
        self.flags(disk_cachemodes=['file=directsync'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuest()

        fake_conf.driver_cache = 'fake'
        conn.set_cache_mode(fake_conf)
        self.assertEqual(fake_conf.driver_cache, 'fake')

    def _test_shared_storage_detection(self, is_same):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(conn, 'get_host_ip_addr')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(os, 'unlink')
        conn.get_host_ip_addr().AndReturn('bar')
        utils.execute('ssh', 'foo', 'touch', mox.IgnoreArg())
        os.path.exists(mox.IgnoreArg()).AndReturn(is_same)
        if is_same:
            os.unlink(mox.IgnoreArg())
        else:
            utils.execute('ssh', 'foo', 'rm', mox.IgnoreArg())
        self.mox.ReplayAll()
        return conn._is_storage_shared_with('foo', '/path')

    def test_shared_storage_detection_same_host(self):
        self.assertTrue(self._test_shared_storage_detection(True))

    def test_shared_storage_detection_different_host(self):
        self.assertFalse(self._test_shared_storage_detection(False))

    def test_shared_storage_detection_easy(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(conn, 'get_host_ip_addr')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(os, 'unlink')
        conn.get_host_ip_addr().AndReturn('foo')
        self.mox.ReplayAll()
        self.assertTrue(conn._is_storage_shared_with('foo', '/path'))

    def test_create_domain_define_xml_fails(self):
        """Tests that the xml is logged when defining the domain fails."""
        fake_xml = "<test>this is a test</test>"

        def fake_defineXML(xml):
            self.assertEqual(fake_xml, xml)
            raise libvirt.libvirtError('virDomainDefineXML() failed')

        self.log_error_called = False

        def fake_error(msg):
            self.log_error_called = True
            self.assertIn(fake_xml, msg)

        self.stubs.Set(nova.virt.libvirt.driver.LOG, 'error', fake_error)

        self.create_fake_libvirt_mock(defineXML=fake_defineXML)
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        self.assertRaises(libvirt.libvirtError, conn._create_domain, fake_xml)
        self.assertTrue(self.log_error_called)

    def test_create_domain_with_flags_fails(self):
        """Tests that the xml is logged when creating the domain with flags
        fails
        """
        fake_xml = "<test>this is a test</test>"
        fake_domain = FakeVirtDomain(fake_xml)

        def fake_createWithFlags(launch_flags):
            raise libvirt.libvirtError('virDomainCreateWithFlags() failed')

        self.log_error_called = False

        def fake_error(msg):
            self.log_error_called = True
            self.assertIn(fake_xml, msg)

        self.stubs.Set(fake_domain, 'createWithFlags', fake_createWithFlags)
        self.stubs.Set(nova.virt.libvirt.driver.LOG, 'error', fake_error)

        self.create_fake_libvirt_mock()
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        self.assertRaises(libvirt.libvirtError, conn._create_domain,
                          domain=fake_domain)
        self.assertTrue(self.log_error_called)

    def test_create_domain_enable_hairpin_fails(self):
        """Tests that the xml is logged when enabling hairpin mode for the
        domain fails.
        """
        utils.reset_is_neutron()
        fake_xml = "<test>this is a test</test>"
        fake_domain = FakeVirtDomain(fake_xml)

        def fake_enable_hairpin(launch_flags):
            raise processutils.ProcessExecutionError('error')

        self.log_error_called = False

        def fake_error(msg):
            self.log_error_called = True
            self.assertIn(fake_xml, msg)

        self.stubs.Set(nova.virt.libvirt.driver.LOG, 'error', fake_error)

        self.create_fake_libvirt_mock()
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.stubs.Set(conn, '_enable_hairpin', fake_enable_hairpin)

        self.assertRaises(processutils.ProcessExecutionError,
                          conn._create_domain,
                          domain=fake_domain,
                          power_on=False)
        self.assertTrue(self.log_error_called)

    def test_get_vnc_console(self):
        instance = self.create_instance_obj(self.context)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<graphics type='vnc' port='5900'/>"
                    "</devices></domain>")

        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        vnc_dict = conn.get_vnc_console(self.context, instance)
        self.assertEqual(vnc_dict['port'], '5900')

    def test_get_vnc_console_unavailable(self):
        instance = self.create_instance_obj(self.context)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices></devices></domain>")

        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          conn.get_vnc_console, self.context, instance)

    def test_get_spice_console(self):
        instance = self.create_instance_obj(self.context)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<graphics type='spice' port='5950'/>"
                    "</devices></domain>")

        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        spice_dict = conn.get_spice_console(self.context, instance)
        self.assertEqual(spice_dict['port'], '5950')

    def test_get_spice_console_unavailable(self):
        instance = self.create_instance_obj(self.context)
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices></devices></domain>")

        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance['name']:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          conn.get_spice_console, self.context, instance)

    def test_detach_volume_with_instance_not_found(self):
        # Test that detach_volume() method does not raise exception,
        # if the instance does not exist.

        instance = self.create_instance_obj(self.context)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        with contextlib.nested(
            mock.patch.object(conn, '_lookup_by_name',
                              side_effect=exception.InstanceNotFound(
                                  instance_id=instance.name)),
            mock.patch.object(conn, 'volume_driver_method')
        ) as (_lookup_by_name, volume_driver_method):
            connection_info = {'driver_volume_type': 'fake'}
            conn.detach_volume(connection_info, instance, '/dev/sda')
            _lookup_by_name.assert_called_once_with(instance.name)
            volume_driver_method.assert_called_once_with('disconnect_volume',
                                                         connection_info,
                                                         'sda')

    def _test_attach_detach_interface_get_config(self, method_name):
        """Tests that the get_config() method is properly called in
        attach_interface() and detach_interface().

        method_name: either \"attach_interface\" or \"detach_interface\"
                     depending on the method to test.
        """
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup

        test_instance = copy.deepcopy(self.test_instance)
        test_instance['name'] = "test"
        network_info = _fake_network_info(self.stubs, 1)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        if method_name == "attach_interface":
            fake_image_meta = {'id': test_instance['image_ref']}
        elif method_name == "detach_interface":
            fake_image_meta = None
        else:
            raise ValueError("Unhandled method %" % method_name)

        fake_flavor = flavor_obj.Flavor.get_by_id(
            self.context, test_instance['instance_type_id'])
        expected = conn.vif_driver.get_config(test_instance, network_info[0],
                                              fake_image_meta,
                                              fake_flavor)
        self.mox.StubOutWithMock(conn.vif_driver, 'get_config')
        conn.vif_driver.get_config(test_instance, network_info[0],
                                   fake_image_meta,
                                   mox.IsA(flavor_obj.Flavor)).\
                                   AndReturn(expected)

        self.mox.ReplayAll()

        if method_name == "attach_interface":
            conn.attach_interface(test_instance, fake_image_meta,
                                  network_info[0])
        elif method_name == "detach_interface":
            conn.detach_interface(test_instance, network_info[0])
        else:
            raise ValueError("Unhandled method %" % method_name)

    def test_attach_interface_get_config(self):
        """Tests that the get_config() method is properly called in
        attach_interface().
        """
        self._test_attach_detach_interface_get_config("attach_interface")

    def test_detach_interface_get_config(self):
        """Tests that the get_config() method is properly called in
        detach_interface().
        """
        self._test_attach_detach_interface_get_config("detach_interface")

    def test_default_root_device_name(self):
        instance = {'uuid': 'fake_instance'}
        image_meta = {'id': 'fake'}
        root_bdm = {'source_type': 'image',
                    'detination_type': 'volume',
                    'image_id': 'fake_id'}
        self.flags(virt_type='fake_libvirt_type', group='libvirt')

        self.mox.StubOutWithMock(blockinfo, 'get_disk_bus_for_device_type')
        self.mox.StubOutWithMock(blockinfo, 'get_root_info')

        blockinfo.get_disk_bus_for_device_type('fake_libvirt_type',
                                               image_meta,
                                               'disk').InAnyOrder().\
                                                AndReturn('virtio')
        blockinfo.get_disk_bus_for_device_type('fake_libvirt_type',
                                               image_meta,
                                               'cdrom').InAnyOrder().\
                                                AndReturn('ide')
        blockinfo.get_root_info('fake_libvirt_type',
                                image_meta, root_bdm,
                                'virtio', 'ide').AndReturn({'dev': 'vda'})
        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertEqual(conn.default_root_device_name(instance, image_meta,
                                                       root_bdm), '/dev/vda')

    def test_default_device_names_for_instance(self):
        instance = {'uuid': 'fake_instance'}
        root_device_name = '/dev/vda'
        ephemerals = [{'device_name': 'vdb'}]
        swap = [{'device_name': 'vdc'}]
        block_device_mapping = [{'device_name': 'vdc'}]
        self.flags(virt_type='fake_libvirt_type', group='libvirt')

        self.mox.StubOutWithMock(blockinfo, 'default_device_names')

        blockinfo.default_device_names('fake_libvirt_type', mox.IgnoreArg(),
                                       instance, root_device_name,
                                       ephemerals, swap, block_device_mapping)
        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.default_device_names_for_instance(instance, root_device_name,
                                               ephemerals, swap,
                                               block_device_mapping)

    def test_hypervisor_hostname_caching(self):
        # Make sure that the first hostname is always returned
        class FakeConn(object):
            def getHostname(self):
                pass

            def getLibVersion(self):
                return 99999

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn._wrapped_conn = FakeConn()
        self.mox.StubOutWithMock(conn._wrapped_conn, 'getHostname')
        conn._conn.getHostname().AndReturn('foo')
        conn._conn.getHostname().AndReturn('bar')
        self.mox.ReplayAll()
        self.assertEqual('foo', conn.get_hypervisor_hostname())
        self.assertEqual('foo', conn.get_hypervisor_hostname())

    def test_get_connection_serial(self):

        def get_conn_currency(driver):
            driver._conn.getLibVersion()

        def connect_with_block(*a, **k):
            # enough to allow another connect to run
            eventlet.sleep(0)
            self.connect_calls += 1
            return self.conn

        def fake_register(*a, **k):
            self.register_calls += 1

        self.connect_calls = 0
        self.register_calls = 0
        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       '_connect', connect_with_block)
        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.stubs.Set(self.conn, 'domainEventRegisterAny', fake_register)

        # call serially
        get_conn_currency(driver)
        get_conn_currency(driver)
        self.assertEqual(self.connect_calls, 1)
        self.assertEqual(self.register_calls, 1)

    def test_get_connection_concurrency(self):

        def get_conn_currency(driver):
            driver._conn.getLibVersion()

        def connect_with_block(*a, **k):
            # enough to allow another connect to run
            eventlet.sleep(0)
            self.connect_calls += 1
            return self.conn

        def fake_register(*a, **k):
            self.register_calls += 1

        self.connect_calls = 0
        self.register_calls = 0
        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       '_connect', connect_with_block)
        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.stubs.Set(self.conn, 'domainEventRegisterAny', fake_register)

        # call concurrently
        thr1 = eventlet.spawn(get_conn_currency, driver=driver)
        thr2 = eventlet.spawn(get_conn_currency, driver=driver)

        # let threads run
        eventlet.sleep(0)

        thr1.wait()
        thr2.wait()
        self.assertEqual(self.connect_calls, 1)
        self.assertEqual(self.register_calls, 1)

    def test_post_live_migration_at_destination_with_block_device_info(self):
        # Preparing mocks
        mock_domain = self.mox.CreateMock(libvirt.virDomain)
        self.resultXML = None

        def fake_none(*args, **kwargs):
            return

        def fake_getLibVersion():
            return 9007

        def fake_getCapabilities():
            return """
            <capabilities>
                <host>
                    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
                    <cpu>
                      <arch>x86_64</arch>
                      <model>Penryn</model>
                      <vendor>Intel</vendor>
                      <topology sockets='1' cores='2' threads='1'/>
                      <feature name='xtpr'/>
                    </cpu>
                </host>
            </capabilities>
            """

        def fake_to_xml(context, instance, network_info, disk_info,
                        image_meta=None, rescue=None,
                        block_device_info=None, write_to_disk=False):
            conf = conn.get_guest_config(instance, network_info, image_meta,
                                         disk_info, rescue, block_device_info)
            self.resultXML = conf.to_xml()
            return self.resultXML

        def fake_lookup_name(instance_name):
            return mock_domain

        def fake_defineXML(xml):
            return

        def fake_baselineCPU(cpu, flag):
            return """<cpu mode='custom' match='exact'>
                        <model fallback='allow'>Westmere</model>
                        <vendor>Intel</vendor>
                        <feature policy='require' name='aes'/>
                      </cpu>
                   """

        network_info = _fake_network_info(self.stubs, 1)
        self.create_fake_libvirt_mock(getLibVersion=fake_getLibVersion,
                                      getCapabilities=fake_getCapabilities,
                                      getVersion=lambda: 1005001)
        instance_ref = self.test_instance
        instance_ref['image_ref'] = 123456  # we send an int to test sha1 call
        instance_type = db.flavor_get(self.context,
                                             instance_ref['instance_type_id'])
        sys_meta = flavors.save_flavor_info({}, instance_type)
        instance_ref['system_metadata'] = sys_meta
        instance = db.instance_create(self.context, instance_ref)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = lambda: []
        libvirt_driver.LibvirtDriver._conn.getCapabilities = \
                                                        fake_getCapabilities
        libvirt_driver.LibvirtDriver._conn.getVersion = lambda: 1005001
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name
        libvirt_driver.LibvirtDriver._conn.defineXML = fake_defineXML
        libvirt_driver.LibvirtDriver._conn.baselineCPU = fake_baselineCPU

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn,
                       'to_xml',
                       fake_to_xml)
        self.stubs.Set(conn,
                       '_lookup_by_name',
                       fake_lookup_name)
        block_device_info = {'block_device_mapping': [
                mocked_bdm(1, {'guest_format': None,
                               'boot_index': 0,
                               'mount_device': '/dev/vda',
                               'connection_info':
                                   {'driver_volume_type': 'iscsi'},
                               'disk_bus': 'virtio',
                               'device_type': 'disk',
                               'delete_on_termination': False}),
                    ]}
        conn.post_live_migration_at_destination(self.context, instance,
                                        network_info, True,
                                        block_device_info=block_device_info)
        self.assertTrue('fake' in self.resultXML)
        self.assertTrue(
            block_device_info['block_device_mapping'][0].save.called)

    def test_create_propogates_exceptions(self):
        self.flags(virt_type='lxc', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = instance_obj.Instance(id=1, uuid='fake-uuid')

        with contextlib.nested(
              mock.patch.object(conn, 'plug_vifs'),
              mock.patch.object(conn, 'firewall_driver'),
              mock.patch.object(conn, '_create_domain',
                                side_effect=exception.NovaException),
              mock.patch.object(conn, 'cleanup')) as (
              cleanup, firewall_driver, create, plug_vifs):
            self.assertRaises(exception.NovaException,
                              conn._create_domain_and_network,
                              self.context,
                              'xml',
                              instance, None)

    def test_create_without_pause(self):
        self.flags(virt_type='lxc', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = instance_obj.Instance(id=1, uuid='fake-uuid')

        with contextlib.nested(
              mock.patch.object(conn, 'plug_vifs'),
              mock.patch.object(conn, 'firewall_driver'),
              mock.patch.object(conn, '_create_domain'),
              mock.patch.object(conn, 'cleanup')) as (
              cleanup, firewall_driver, create, plug_vifs):
            domain = conn._create_domain_and_network(self.context, 'xml',
                                                     instance, None)
            self.assertEqual(0, create.call_args_list[0][1]['launch_flags'])
            self.assertEqual(0, domain.resume.call_count)

    def _test_create_with_network_events(self, neutron_failure=None,
                                         power_on=True):
        self.flags(vif_driver="nova.tests.fake_network.FakeVIFDriver",
                   group='libvirt')
        generated_events = []

        def wait_timeout():
            event = mock.MagicMock()
            if neutron_failure == 'timeout':
                raise eventlet.timeout.Timeout()
            elif neutron_failure == 'error':
                event.status = 'failed'
            else:
                event.status = 'completed'
            return event

        def fake_prepare(instance, event_name):
            m = mock.MagicMock()
            m.instance = instance
            m.event_name = event_name
            m.wait.side_effect = wait_timeout
            generated_events.append(m)
            return m

        virtapi = manager.ComputeVirtAPI(mock.MagicMock())
        prepare = virtapi._compute.instance_events.prepare_for_instance_event
        prepare.side_effect = fake_prepare
        conn = libvirt_driver.LibvirtDriver(virtapi, False)

        instance = instance_obj.Instance(id=1, uuid='fake-uuid')
        vifs = [{'id': 'vif1', 'active': False},
                {'id': 'vif2', 'active': False}]

        @mock.patch.object(conn, 'plug_vifs')
        @mock.patch.object(conn, 'firewall_driver')
        @mock.patch.object(conn, '_create_domain')
        @mock.patch.object(conn, 'cleanup')
        def test_create(cleanup, create, fw_driver, plug_vifs):
            domain = conn._create_domain_and_network(self.context, 'xml',
                                                     instance, vifs,
                                                     power_on=power_on)
            plug_vifs.assert_called_with(instance, vifs)
            event = (utils.is_neutron() and CONF.vif_plugging_timeout and
                     power_on)
            flag = event and libvirt.VIR_DOMAIN_START_PAUSED or 0
            self.assertEqual(flag,
                             create.call_args_list[0][1]['launch_flags'])
            if flag:
                domain.resume.assert_called_once_with()
            if neutron_failure and CONF.vif_plugging_is_fatal:
                cleanup.assert_called_once_with(self.context,
                                                instance, network_info=vifs,
                                                block_device_info=None)

        test_create()

        if utils.is_neutron() and CONF.vif_plugging_timeout and power_on:
            prepare.assert_has_calls([
                mock.call(instance, 'network-vif-plugged-vif1'),
                mock.call(instance, 'network-vif-plugged-vif2')])
            for event in generated_events:
                if neutron_failure and generated_events.index(event) != 0:
                    self.assertEqual(0, event.call_count)
                elif (neutron_failure == 'error' and
                          not CONF.vif_plugging_is_fatal):
                    event.wait.assert_called_once_with()
        else:
            self.assertEqual(0, prepare.call_count)

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron(self, is_neutron):
        self._test_create_with_network_events()

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_power_off(self,
                                                          is_neutron):
        # Tests that we don't wait for events if we don't start the instance.
        self._test_create_with_network_events(power_on=False)

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_nowait(self, is_neutron):
        self.flags(vif_plugging_timeout=0)
        self._test_create_with_network_events()

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_failed_nonfatal_timeout(
            self, is_neutron):
        self.flags(vif_plugging_is_fatal=False)
        self._test_create_with_network_events(neutron_failure='timeout')

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_failed_fatal_timeout(
            self, is_neutron):
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self._test_create_with_network_events,
                          neutron_failure='timeout')

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_failed_nonfatal_error(
            self, is_neutron):
        self.flags(vif_plugging_is_fatal=False)
        self._test_create_with_network_events(neutron_failure='error')

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_create_with_network_events_neutron_failed_fatal_error(
            self, is_neutron):
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self._test_create_with_network_events,
                          neutron_failure='error')

    @mock.patch('nova.utils.is_neutron', return_value=False)
    def test_create_with_network_events_non_neutron(self, is_neutron):
        self._test_create_with_network_events()

    @mock.patch('nova.volume.encryptors.get_encryption_metadata')
    @mock.patch('nova.virt.libvirt.blockinfo.get_info_from_bdm')
    def test_create_with_bdm(self, get_info_from_bdm, get_encryption_metadata):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        mock_dom = mock.MagicMock()
        mock_encryption_meta = mock.MagicMock()
        get_encryption_metadata.return_value = mock_encryption_meta

        fake_xml = """
            <domain>
                <name>instance-00000001</name>
                <memory>1048576</memory>
                <vcpu>1</vcpu>
                <devices>
                    <disk type='file' device='disk'>
                        <driver name='qemu' type='raw' cache='none'/>
                        <source file='/path/fake-volume1'/>
                        <target dev='vda' bus='virtio'/>
                    </disk>
                </devices>
            </domain>
        """
        fake_volume_id = "fake-volume-id"
        connection_info = {"driver_volume_type": "fake",
                           "data": {"access_mode": "rw",
                                    "volume_id": fake_volume_id}}

        def fake_getitem(*args, **kwargs):
            fake_bdm = {'connection_info': connection_info,
                        'mount_device': '/dev/vda'}
            return fake_bdm.get(args[0])

        mock_volume = mock.MagicMock()
        mock_volume.__getitem__.side_effect = fake_getitem
        bdi = {'block_device_mapping': [mock_volume]}
        network_info = [network_model.VIF(id='1'),
                        network_model.VIF(id='2', active=True)]
        disk_info = {'bus': 'virtio', 'type': 'file',
                     'dev': 'vda'}
        get_info_from_bdm.return_value = disk_info

        with contextlib.nested(
            mock.patch.object(conn, 'volume_driver_method'),
            mock.patch.object(conn, '_get_volume_encryptor'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver,
                              'prepare_instance_filter'),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter'),
        ) as (volume_driver_method, get_volume_encryptor, plug_vifs,
              setup_basic_filtering, prepare_instance_filter, create_domain,
              apply_instance_filter):
            volume_driver_method.return_value = mock.MagicMock(
                source_path='/path/fake-volume1')
            create_domain.return_value = mock_dom

            domain = conn._create_domain_and_network(self.context, fake_xml,
                                                     instance, network_info,
                                                     block_device_info=bdi)

            get_info_from_bdm.assert_called_once_with(CONF.libvirt.virt_type,
                                                      mock_volume)
            volume_driver_method.assert_called_once_with('connect_volume',
                                                         connection_info,
                                                         disk_info)
            self.assertEqual(connection_info['data']['device_path'],
                             '/path/fake-volume1')
            mock_volume.save.assert_called_once_with(self.context)
            get_encryption_metadata.assert_called_once_with(self.context,
                conn._volume_api, fake_volume_id, connection_info)
            get_volume_encryptor.assert_called_once_with(connection_info,
                                                         mock_encryption_meta)
            plug_vifs.assert_called_once_with(instance, network_info)
            setup_basic_filtering.assert_called_once_with(instance,
                                                          network_info)
            prepare_instance_filter.assert_called_once_with(instance,
                                                          network_info)

            event = utils.is_neutron() and CONF.vif_plugging_timeout
            flag = event and libvirt.VIR_DOMAIN_START_PAUSED or 0
            create_domain.assert_called_once_with(fake_xml, instance=instance,
                                                  launch_flags=flag,
                                                  power_on=True)
            self.assertEqual(mock_dom, domain)

    def test_get_neutron_events(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        network_info = [network_model.VIF(id='1'),
                        network_model.VIF(id='2', active=True)]
        events = conn._get_neutron_events(network_info)
        self.assertEqual([('network-vif-plugged', '1')], events)

    def test_unplug_vifs_ignores_errors(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        with mock.patch.object(conn, 'vif_driver') as vif_driver:
            vif_driver.unplug.side_effect = exception.AgentError(
                method='unplug')
            conn.unplug_vifs('inst', [1], ignore_errors=True)
            vif_driver.unplug.assert_called_once_with('inst', 1)

    def test_unplug_vifs_reports_errors(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        with mock.patch.object(conn, 'vif_driver') as vif_driver:
            vif_driver.unplug.side_effect = exception.AgentError(
                method='unplug')
            self.assertRaises(exception.AgentError,
                              conn.unplug_vifs, 'inst', [1])
            vif_driver.unplug.assert_called_once_with('inst', 1)

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.unplug_vifs')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._undefine_domain')
    def test_cleanup_wants_vif_errors_ignored(self, undefine, unplug):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        fake_inst = {'name': 'foo'}
        with mock.patch.object(conn._conn, 'lookupByName') as lookup:
            lookup.return_value = fake_inst
            # NOTE(danms): Make unplug cause us to bail early, since
            # we only care about how it was called
            unplug.side_effect = test.TestingException
            self.assertRaises(test.TestingException,
                              conn.cleanup, 'ctxt', fake_inst, 'netinfo')
            unplug.assert_called_once_with(fake_inst, 'netinfo',
                                           ignore_errors=True)


class HostStateTestCase(test.TestCase):

    cpu_info = ('{"vendor": "Intel", "model": "pentium", "arch": "i686", '
                 '"features": ["ssse3", "monitor", "pni", "sse2", "sse", '
                 '"fxsr", "clflush", "pse36", "pat", "cmov", "mca", "pge", '
                 '"mtrr", "sep", "apic"], '
                 '"topology": {"cores": "1", "threads": "1", "sockets": "1"}}')
    instance_caps = [("x86_64", "kvm", "hvm"), ("i686", "kvm", "hvm")]
    pci_devices = [{
        "dev_id": "pci_0000_04_00_3",
        "address": "0000:04:10.3",
        "product_id": '1521',
        "vendor_id": '8086',
        "dev_type": 'type-PF',
        "phys_function": None}]

    class FakeConnection(object):
        """Fake connection object."""

        def get_vcpu_total(self):
            return 1

        def get_vcpu_used(self):
            return 0

        def get_cpu_info(self):
            return HostStateTestCase.cpu_info

        def get_disk_over_committed_size_total(self):
            return 0

        def get_local_gb_info(self):
            return {'total': 100, 'used': 20, 'free': 80}

        def get_memory_mb_total(self):
            return 497

        def get_memory_mb_used(self):
            return 88

        def get_hypervisor_type(self):
            return 'QEMU'

        def get_hypervisor_version(self):
            return 13091

        def get_hypervisor_hostname(self):
            return 'compute1'

        def get_host_uptime(self):
            return ('10:01:16 up  1:36,  6 users,  '
                    'load average: 0.21, 0.16, 0.19')

        def get_disk_available_least(self):
            return 13091

        def get_instance_capabilities(self):
            return HostStateTestCase.instance_caps

        def get_pci_passthrough_devices(self):
            return jsonutils.dumps(HostStateTestCase.pci_devices)

    def test_update_status(self):
        hs = libvirt_driver.HostState(self.FakeConnection())
        stats = hs._stats
        self.assertEqual(stats["vcpus"], 1)
        self.assertEqual(stats["memory_mb"], 497)
        self.assertEqual(stats["local_gb"], 100)
        self.assertEqual(stats["vcpus_used"], 0)
        self.assertEqual(stats["memory_mb_used"], 88)
        self.assertEqual(stats["local_gb_used"], 20)
        self.assertEqual(stats["hypervisor_type"], 'QEMU')
        self.assertEqual(stats["hypervisor_version"], 13091)
        self.assertEqual(stats["hypervisor_hostname"], 'compute1')
        self.assertEqual(jsonutils.loads(stats["cpu_info"]),
                {"vendor": "Intel", "model": "pentium", "arch": "i686",
                 "features": ["ssse3", "monitor", "pni", "sse2", "sse",
                              "fxsr", "clflush", "pse36", "pat", "cmov",
                              "mca", "pge", "mtrr", "sep", "apic"],
                 "topology": {"cores": "1", "threads": "1", "sockets": "1"}
                })
        self.assertEqual(stats["disk_available_least"], 80)
        self.assertEqual(jsonutils.loads(stats["pci_passthrough_devices"]),
                         HostStateTestCase.pci_devices)


class NWFilterFakes:
    def __init__(self):
        self.filters = {}

    def nwfilterLookupByName(self, name):
        if name in self.filters:
            return self.filters[name]
        raise libvirt.libvirtError('Filter Not Found')

    def filterDefineXMLMock(self, xml):
        class FakeNWFilterInternal:
            def __init__(self, parent, name, xml):
                self.name = name
                self.parent = parent
                self.xml = xml

            def undefine(self):
                del self.parent.filters[self.name]
                pass
        tree = etree.fromstring(xml)
        name = tree.get('name')
        if name not in self.filters:
            self.filters[name] = FakeNWFilterInternal(self, name, xml)
        return True


class IptablesFirewallTestCase(test.TestCase):
    def setUp(self):
        super(IptablesFirewallTestCase, self).setUp()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        class FakeLibvirtDriver(object):
            def nwfilterDefineXML(*args, **kwargs):
                """setup_basic_rules in nwfilter calls this."""
                pass
        self.fake_libvirt_connection = FakeLibvirtDriver()
        self.fw = firewall.IptablesFirewallDriver(
                      fake.FakeVirtAPI(),
                      get_connection=lambda: self.fake_libvirt_connection)

    in_rules = [
      '# Generated by iptables-save v1.4.10 on Sat Feb 19 00:03:19 2011',
      '*nat',
      ':PREROUTING ACCEPT [1170:189210]',
      ':INPUT ACCEPT [844:71028]',
      ':OUTPUT ACCEPT [5149:405186]',
      ':POSTROUTING ACCEPT [5063:386098]',
      '# Completed on Tue Dec 18 15:50:25 2012',
      '# Generated by iptables-save v1.4.12 on Tue Dec 18 15:50:25 201;',
      '*mangle',
      ':PREROUTING ACCEPT [241:39722]',
      ':INPUT ACCEPT [230:39282]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [266:26558]',
      ':POSTROUTING ACCEPT [267:26590]',
      '-A POSTROUTING -o virbr0 -p udp -m udp --dport 68 -j CHECKSUM '
      '--checksum-fill',
      'COMMIT',
      '# Completed on Tue Dec 18 15:50:25 2012',
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*filter',
      ':INPUT ACCEPT [969615:281627771]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [915599:63811649]',
      ':nova-block-ipv4 - [0:0]',
      '[0:0] -A INPUT -i virbr0 -p tcp -m tcp --dport 67 -j ACCEPT ',
      '[0:0] -A FORWARD -d 192.168.122.0/24 -o virbr0 -m state --state RELATED'
      ',ESTABLISHED -j ACCEPT ',
      '[0:0] -A FORWARD -s 192.168.122.0/24 -i virbr0 -j ACCEPT ',
      '[0:0] -A FORWARD -i virbr0 -o virbr0 -j ACCEPT ',
      '[0:0] -A FORWARD -o virbr0 -j REJECT '
      '--reject-with icmp-port-unreachable ',
      '[0:0] -A FORWARD -i virbr0 -j REJECT '
      '--reject-with icmp-port-unreachable ',
      'COMMIT',
      '# Completed on Mon Dec  6 11:54:13 2010',
    ]

    in6_filter_rules = [
      '# Generated by ip6tables-save v1.4.4 on Tue Jan 18 23:47:56 2011',
      '*filter',
      ':INPUT ACCEPT [349155:75810423]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [349256:75777230]',
      'COMMIT',
      '# Completed on Tue Jan 18 23:47:56 2011',
    ]

    def _create_instance_ref(self):
        return db.instance_create(self.context,
                                  {'user_id': 'fake',
                                   'project_id': 'fake',
                                   'instance_type_id': 1})

    def test_static_filters(self):
        instance_ref = self._create_instance_ref()
        src_instance_ref = self._create_instance_ref()

        admin_ctxt = context.get_admin_context()
        secgroup = db.security_group_create(admin_ctxt,
                                            {'user_id': 'fake',
                                             'project_id': 'fake',
                                             'name': 'testgroup',
                                             'description': 'test group'})

        src_secgroup = db.security_group_create(admin_ctxt,
                                                {'user_id': 'fake',
                                                 'project_id': 'fake',
                                                 'name': 'testsourcegroup',
                                                 'description': 'src group'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': -1,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': 8,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'cidr': '192.168.10.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'group_id': src_secgroup['id']})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'group_id': src_secgroup['id']})

        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        db.instance_add_security_group(admin_ctxt, src_instance_ref['uuid'],
                                       src_secgroup['id'])
        instance_ref = db.instance_get(admin_ctxt, instance_ref['id'])
        src_instance_ref = db.instance_get(admin_ctxt, src_instance_ref['id'])

        def fake_iptables_execute(*cmd, **kwargs):
            process_input = kwargs.get('process_input', None)
            if cmd == ('ip6tables-save', '-c'):
                return '\n'.join(self.in6_filter_rules), None
            if cmd == ('iptables-save', '-c'):
                return '\n'.join(self.in_rules), None
            if cmd == ('iptables-restore', '-c'):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out_rules = lines
                return '', ''
            if cmd == ('ip6tables-restore', '-c',):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out6_rules = lines
                return '', ''

        network_model = _fake_network_info(self.stubs, 1)

        from nova.network import linux_net
        linux_net.iptables_manager.execute = fake_iptables_execute

        from nova.compute import utils as compute_utils
        self.stubs.Set(compute_utils, 'get_nw_info_for_instance',
                       lambda instance: network_model)

        self.fw.prepare_instance_filter(instance_ref, network_model)
        self.fw.apply_instance_filter(instance_ref, network_model)

        in_rules = filter(lambda l: not l.startswith('#'),
                          self.in_rules)
        for rule in in_rules:
            if 'nova' not in rule:
                self.assertTrue(rule in self.out_rules,
                                'Rule went missing: %s' % rule)

        instance_chain = None
        for rule in self.out_rules:
            # This is pretty crude, but it'll do for now
            # last two octets change
            if re.search('-d 192.168.[0-9]{1,3}.[0-9]{1,3} -j', rule):
                instance_chain = rule.split(' ')[-1]
                break
        self.assertTrue(instance_chain, "The instance chain wasn't added")

        security_group_chain = None
        for rule in self.out_rules:
            # This is pretty crude, but it'll do for now
            if '-A %s -j' % instance_chain in rule:
                security_group_chain = rule.split(' ')[-1]
                break
        self.assertTrue(security_group_chain,
                        "The security group chain wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p icmp '
                           '-s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP acceptance rule wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p icmp -m icmp '
                           '--icmp-type 8 -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP Echo Request acceptance rule wasn't added")

        for ip in network_model.fixed_ips():
            if ip['version'] != 4:
                continue
            regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p tcp -m multiport '
                               '--dports 80:81 -s %s' % ip['address'])
            self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                            "TCP port 80/81 acceptance rule wasn't added")
            regex = re.compile('\[0\:0\] -A .* -j ACCEPT -s '
                               '%s' % ip['address'])
            self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                            "Protocol/port-less acceptance rule wasn't added")

        regex = re.compile('\[0\:0\] -A .* -j ACCEPT -p tcp '
                           '-m multiport --dports 80:81 -s 192.168.10.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")
        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_filters_for_instance_with_ip_v6(self):
        self.flags(use_ipv6=True)
        network_info = _fake_network_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEqual(len(rulesv4), 2)
        self.assertEqual(len(rulesv6), 1)

    def test_filters_for_instance_without_ip_v6(self):
        self.flags(use_ipv6=False)
        network_info = _fake_network_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEqual(len(rulesv4), 2)
        self.assertEqual(len(rulesv6), 0)

    def test_multinic_iptables(self):
        ipv4_rules_per_addr = 1
        ipv4_addr_per_network = 2
        ipv6_rules_per_addr = 1
        ipv6_addr_per_network = 1
        networks_count = 5
        instance_ref = self._create_instance_ref()
        network_info = _fake_network_info(self.stubs, networks_count,
                                ipv4_addr_per_network)
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
        ipv4_len = len(self.fw.iptables.ipv4['filter'].rules)
        ipv6_len = len(self.fw.iptables.ipv6['filter'].rules)
        inst_ipv4, inst_ipv6 = self.fw.instance_rules(instance_ref,
                                                      network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        ipv4 = self.fw.iptables.ipv4['filter'].rules
        ipv6 = self.fw.iptables.ipv6['filter'].rules
        ipv4_network_rules = len(ipv4) - len(inst_ipv4) - ipv4_len
        ipv6_network_rules = len(ipv6) - len(inst_ipv6) - ipv6_len
        # Extra rules are for the DHCP request
        rules = (ipv4_rules_per_addr * ipv4_addr_per_network *
                 networks_count) + 2
        self.assertEqual(ipv4_network_rules, rules)
        self.assertEqual(ipv6_network_rules,
                  ipv6_rules_per_addr * ipv6_addr_per_network * networks_count)

    def test_do_refresh_security_group_rules(self):
        instance_ref = self._create_instance_ref()
        self.mox.StubOutWithMock(self.fw,
                                 'instance_rules')
        self.mox.StubOutWithMock(self.fw,
                                 'add_filters_for_instance',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(self.fw.iptables.ipv4['filter'],
                                 'has_chain')

        self.fw.instance_rules(instance_ref,
                               mox.IgnoreArg()).AndReturn((None, None))
        self.fw.add_filters_for_instance(instance_ref, mox.IgnoreArg(),
                                         mox.IgnoreArg(), mox.IgnoreArg())
        self.fw.instance_rules(instance_ref,
                               mox.IgnoreArg()).AndReturn((None, None))
        self.fw.iptables.ipv4['filter'].has_chain(mox.IgnoreArg()
                                                  ).AndReturn(True)
        self.fw.add_filters_for_instance(instance_ref, mox.IgnoreArg(),
                                         mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        self.fw.prepare_instance_filter(instance_ref, mox.IgnoreArg())
        self.fw.instance_info[instance_ref['id']] = (instance_ref, None)
        self.fw.do_refresh_security_group_rules("fake")

    def test_do_refresh_security_group_rules_instance_disappeared(self):
        instance1 = {'id': 1, 'uuid': 'fake-uuid1'}
        instance2 = {'id': 2, 'uuid': 'fake-uuid2'}
        self.fw.instance_info = {1: (instance1, 'netinfo1'),
                                 2: (instance2, 'netinfo2')}
        mock_filter = mock.MagicMock()
        with mock.patch.dict(self.fw.iptables.ipv4, {'filter': mock_filter}):
            mock_filter.has_chain.return_value = False
            with mock.patch.object(self.fw, 'instance_rules') as mock_ir:
                mock_ir.return_value = (None, None)
                self.fw.do_refresh_security_group_rules('secgroup')
                self.assertEqual(2, mock_ir.call_count)
            # NOTE(danms): Make sure that it is checking has_chain each time,
            # continuing to process all the instances, and never adding the
            # new chains back if has_chain() is False
            mock_filter.has_chain.assert_has_calls([mock.call('inst-1'),
                                                    mock.call('inst-2')],
                                                   any_order=True)
            self.assertEqual(0, mock_filter.add_chain.call_count)

    def test_unfilter_instance_undefines_nwfilter(self):
        admin_ctxt = context.get_admin_context()

        fakefilter = NWFilterFakes()
        _xml_mock = fakefilter.filterDefineXMLMock
        self.fw.nwfilter._conn.nwfilterDefineXML = _xml_mock
        _lookup_name = fakefilter.nwfilterLookupByName
        self.fw.nwfilter._conn.nwfilterLookupByName = _lookup_name
        instance_ref = self._create_instance_ref()

        network_info = _fake_network_info(self.stubs, 1)
        self.fw.setup_basic_filtering(instance_ref, network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)
        original_filter_count = len(fakefilter.filters)
        self.fw.unfilter_instance(instance_ref, network_info)

        # should undefine just the instance filter
        self.assertEqual(original_filter_count - len(fakefilter.filters), 1)

        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_provider_firewall_rules(self):
        # setup basic instance data
        instance_ref = self._create_instance_ref()
        # FRAGILE: peeks at how the firewall names chains
        chain_name = 'inst-%s' % instance_ref['id']

        # create a firewall via setup_basic_filtering like libvirt_conn.spawn
        # should have a chain with 0 rules
        network_info = _fake_network_info(self.stubs, 1)
        self.fw.setup_basic_filtering(instance_ref, network_info)
        self.assertIn('provider', self.fw.iptables.ipv4['filter'].chains)
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(0, len(rules))

        admin_ctxt = context.get_admin_context()
        # add a rule and send the update message, check for 1 rule
        provider_fw0 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'tcp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))

        # Add another, refresh, and make sure number of rules goes to two
        provider_fw1 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'udp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(2, len(rules))

        # create the instance filter and make sure it has a jump rule
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)
        inst_rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                           if rule.chain == chain_name]
        jump_rules = [rule for rule in inst_rules if '-j' in rule.rule]
        provjump_rules = []
        # IptablesTable doesn't make rules unique internally
        for rule in jump_rules:
            if 'provider' in rule.rule and rule not in provjump_rules:
                provjump_rules.append(rule)
        self.assertEqual(1, len(provjump_rules))

        # remove a rule from the db, cast to compute to refresh rule
        db.provider_fw_rule_destroy(admin_ctxt, provider_fw1['id'])
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))


class NWFilterTestCase(test.TestCase):
    def setUp(self):
        super(NWFilterTestCase, self).setUp()

        class Mock(object):
            pass

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        self.fake_libvirt_connection = Mock()

        self.fw = firewall.NWFilterFirewall(fake.FakeVirtAPI(),
                                         lambda: self.fake_libvirt_connection)

    def test_cidr_rule_nwfilter_xml(self):
        cloud_controller = cloud.CloudController()
        cloud_controller.create_security_group(self.context,
                                               'testgroup',
                                               'test group description')
        cloud_controller.authorize_security_group_ingress(self.context,
                                                          'testgroup',
                                                          from_port='80',
                                                          to_port='81',
                                                          ip_protocol='tcp',
                                                          cidr_ip='0.0.0.0/0')

        security_group = db.security_group_get_by_name(self.context,
                                                       'fake',
                                                       'testgroup')
        self.teardown_security_group()

    def teardown_security_group(self):
        cloud_controller = cloud.CloudController()
        cloud_controller.delete_security_group(self.context, 'testgroup')

    def setup_and_return_security_group(self):
        cloud_controller = cloud.CloudController()
        cloud_controller.create_security_group(self.context,
                                               'testgroup',
                                               'test group description')
        cloud_controller.authorize_security_group_ingress(self.context,
                                                          'testgroup',
                                                          from_port='80',
                                                          to_port='81',
                                                          ip_protocol='tcp',
                                                          cidr_ip='0.0.0.0/0')

        return db.security_group_get_by_name(self.context, 'fake', 'testgroup')

    def _create_instance(self):
        return db.instance_create(self.context,
                                  {'user_id': 'fake',
                                   'project_id': 'fake',
                                   'instance_type_id': 1})

    def test_creates_base_rule_first(self):
        # These come pre-defined by libvirt
        self.defined_filters = ['no-mac-spoofing',
                                'no-ip-spoofing',
                                'no-arp-spoofing',
                                'allow-dhcp-server']

        self.recursive_depends = {}
        for f in self.defined_filters:
            self.recursive_depends[f] = []

        def _filterDefineXMLMock(xml):
            dom = minidom.parseString(xml)
            name = dom.firstChild.getAttribute('name')
            self.recursive_depends[name] = []
            for f in dom.getElementsByTagName('filterref'):
                ref = f.getAttribute('filter')
                self.assertTrue(ref in self.defined_filters,
                                ('%s referenced filter that does ' +
                                'not yet exist: %s') % (name, ref))
                dependencies = [ref] + self.recursive_depends[ref]
                self.recursive_depends[name] += dependencies

            self.defined_filters.append(name)
            return True

        self.fake_libvirt_connection.nwfilterDefineXML = _filterDefineXMLMock

        instance_ref = self._create_instance()
        inst_id = instance_ref['id']
        inst_uuid = instance_ref['uuid']

        def _ensure_all_called(mac, allow_dhcp):
            instance_filter = 'nova-instance-%s-%s' % (instance_ref['name'],
                    mac.translate({ord(':'): None}))
            requiredlist = ['no-arp-spoofing', 'no-ip-spoofing',
                             'no-mac-spoofing']
            required_not_list = []
            if allow_dhcp:
                requiredlist.append('allow-dhcp-server')
            else:
                required_not_list.append('allow-dhcp-server')
            for required in requiredlist:
                self.assertTrue(required in
                                self.recursive_depends[instance_filter],
                                "Instance's filter does not include %s" %
                                required)
            for required_not in required_not_list:
                self.assertFalse(required_not in
                    self.recursive_depends[instance_filter],
                    "Instance filter includes %s" % required_not)

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_uuid,
                                       self.security_group['id'])
        instance = db.instance_get(self.context, inst_id)
        network_info = _fake_network_info(self.stubs, 1)
        # since there is one (network_info) there is one vif
        # pass this vif's mac to _ensure_all_called()
        # to set the instance_filter properly
        mac = network_info[0]['address']
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
        self.fw.setup_basic_filtering(instance, network_info)
        allow_dhcp = True
        _ensure_all_called(mac, allow_dhcp)

        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = None
        self.fw.setup_basic_filtering(instance, network_info)
        allow_dhcp = False
        _ensure_all_called(mac, allow_dhcp)
        db.instance_remove_security_group(self.context, inst_uuid,
                                          self.security_group['id'])
        self.teardown_security_group()
        db.instance_destroy(context.get_admin_context(), instance_ref['uuid'])

    def test_unfilter_instance_undefines_nwfilters(self):
        admin_ctxt = context.get_admin_context()

        fakefilter = NWFilterFakes()
        self.fw._conn.nwfilterDefineXML = fakefilter.filterDefineXMLMock
        self.fw._conn.nwfilterLookupByName = fakefilter.nwfilterLookupByName

        instance_ref = self._create_instance()
        inst_id = instance_ref['id']
        inst_uuid = instance_ref['uuid']

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_uuid,
                                       self.security_group['id'])

        instance = db.instance_get(self.context, inst_id)

        network_info = _fake_network_info(self.stubs, 1)
        self.fw.setup_basic_filtering(instance, network_info)
        original_filter_count = len(fakefilter.filters)
        self.fw.unfilter_instance(instance, network_info)
        self.assertEqual(original_filter_count - len(fakefilter.filters), 1)

        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_nwfilter_parameters(self):
        admin_ctxt = context.get_admin_context()

        fakefilter = NWFilterFakes()
        self.fw._conn.nwfilterDefineXML = fakefilter.filterDefineXMLMock
        self.fw._conn.nwfilterLookupByName = fakefilter.nwfilterLookupByName

        instance_ref = self._create_instance()
        inst_id = instance_ref['id']
        inst_uuid = instance_ref['uuid']

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_uuid,
                                       self.security_group['id'])

        instance = db.instance_get(self.context, inst_id)

        network_info = _fake_network_info(self.stubs, 1)
        self.fw.setup_basic_filtering(instance, network_info)

        vif = network_info[0]
        nic_id = vif['address'].replace(':', '')
        instance_filter_name = self.fw._instance_filter_name(instance, nic_id)
        f = fakefilter.nwfilterLookupByName(instance_filter_name)
        tree = etree.fromstring(f.xml)

        for fref in tree.findall('filterref'):
            parameters = fref.findall('./parameter')
            for parameter in parameters:
                subnet_v4, subnet_v6 = vif['network']['subnets']
                if parameter.get('name') == 'IP':
                    self.assertTrue(_ipv4_like(parameter.get('value'),
                                                             '192.168'))
                elif parameter.get('name') == 'DHCPSERVER':
                    dhcp_server = subnet_v4.get('dhcp_server')
                    self.assertEqual(parameter.get('value'), dhcp_server)
                elif parameter.get('name') == 'RASERVER':
                    ra_server = subnet_v6['gateway']['address'] + "/128"
                    self.assertEqual(parameter.get('value'), ra_server)
                elif parameter.get('name') == 'PROJNET':
                    ipv4_cidr = subnet_v4['cidr']
                    net, mask = netutils.get_net_and_mask(ipv4_cidr)
                    self.assertEqual(parameter.get('value'), net)
                elif parameter.get('name') == 'PROJMASK':
                    ipv4_cidr = subnet_v4['cidr']
                    net, mask = netutils.get_net_and_mask(ipv4_cidr)
                    self.assertEqual(parameter.get('value'), mask)
                elif parameter.get('name') == 'PROJNET6':
                    ipv6_cidr = subnet_v6['cidr']
                    net, prefix = netutils.get_net_and_prefixlen(ipv6_cidr)
                    self.assertEqual(parameter.get('value'), net)
                elif parameter.get('name') == 'PROJMASK6':
                    ipv6_cidr = subnet_v6['cidr']
                    net, prefix = netutils.get_net_and_prefixlen(ipv6_cidr)
                    self.assertEqual(parameter.get('value'), prefix)
                else:
                    raise exception.InvalidParameterValue('unknown parameter '
                                                          'in filter')

        db.instance_destroy(admin_ctxt, instance_ref['uuid'])

    def test_multinic_base_filter_selection(self):
        fakefilter = NWFilterFakes()
        self.fw._conn.nwfilterDefineXML = fakefilter.filterDefineXMLMock
        self.fw._conn.nwfilterLookupByName = fakefilter.nwfilterLookupByName

        instance_ref = self._create_instance()
        inst_id = instance_ref['id']
        inst_uuid = instance_ref['uuid']

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_uuid,
                                       self.security_group['id'])

        instance = db.instance_get(self.context, inst_id)

        network_info = _fake_network_info(self.stubs, 2)
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'

        self.fw.setup_basic_filtering(instance, network_info)

        def assert_filterref(instance, vif, expected=[]):
            nic_id = vif['address'].replace(':', '')
            filter_name = self.fw._instance_filter_name(instance, nic_id)
            f = fakefilter.nwfilterLookupByName(filter_name)
            tree = etree.fromstring(f.xml)
            frefs = [fr.get('filter') for fr in tree.findall('filterref')]
            self.assertTrue(set(expected) == set(frefs))

        assert_filterref(instance, network_info[0], expected=['nova-base'])
        assert_filterref(instance, network_info[1], expected=['nova-nodhcp'])

        db.instance_remove_security_group(self.context, inst_uuid,
                                          self.security_group['id'])
        self.teardown_security_group()
        db.instance_destroy(context.get_admin_context(), instance_ref['uuid'])


class LibvirtUtilsTestCase(test.TestCase):
    def test_create_image(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('qemu-img', 'create', '-f', 'raw',
                      '/some/path', '10G')
        utils.execute('qemu-img', 'create', '-f', 'qcow2',
                      '/some/stuff', '1234567891234')
        # Start test
        self.mox.ReplayAll()
        libvirt_utils.create_image('raw', '/some/path', '10G')
        libvirt_utils.create_image('qcow2', '/some/stuff', '1234567891234')

    def test_create_cow_image(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        rval = ('', '')
        os.path.exists('/some/path').AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', '/some/path').AndReturn(rval)
        utils.execute('qemu-img', 'create', '-f', 'qcow2',
                      '-o', 'backing_file=/some/path',
                      '/the/new/cow')
        # Start test
        self.mox.ReplayAll()
        libvirt_utils.create_cow_image('/some/path', '/the/new/cow')

    def test_pick_disk_driver_name(self):
        type_map = {'kvm': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'qemu': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'xen': ([True, 'phy'], [False, 'tap2'], [None, 'tap2']),
                    'uml': ([True, None], [False, None], [None, None]),
                    'lxc': ([True, None], [False, None], [None, None])}

        for (virt_type, checks) in type_map.iteritems():
            if virt_type == "xen":
                version = 4001000
            else:
                version = 1005001

            self.flags(virt_type=virt_type, group='libvirt')
            for (is_block_dev, expected_result) in checks:
                result = libvirt_utils.pick_disk_driver_name(version,
                                                             is_block_dev)
                self.assertEqual(result, expected_result)

    def test_pick_disk_driver_name_xen_4_0_0(self):
        self.flags(virt_type="xen", group='libvirt')
        result = libvirt_utils.pick_disk_driver_name(4000000, False)
        self.assertEqual(result, "tap")

    def test_get_disk_size(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists('/some/path').AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info',
                      '/some/path').AndReturn(('''image: 00000001
file format: raw
virtual size: 4.4M (4592640 bytes)
disk size: 4.4M''', ''))

        # Start test
        self.mox.ReplayAll()
        self.assertEqual(disk.get_disk_size('/some/path'), 4592640)

    def test_copy_image(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            src_fd, src_path = tempfile.mkstemp()
            try:
                with os.fdopen(src_fd, 'w') as fp:
                    fp.write('canary')

                libvirt_utils.copy_image(src_path, dst_path)
                with open(dst_path, 'r') as fp:
                    self.assertEqual(fp.read(), 'canary')
            finally:
                os.unlink(src_path)
        finally:
            os.unlink(dst_path)

    def test_write_to_file(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            libvirt_utils.write_to_file(dst_path, 'hello')
            with open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
        finally:
            os.unlink(dst_path)

    def test_write_to_file_with_umask(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)
            os.unlink(dst_path)

            libvirt_utils.write_to_file(dst_path, 'hello', umask=0o277)
            with open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
            mode = os.stat(dst_path).st_mode
            self.assertEqual(mode & 0o277, 0)
        finally:
            os.unlink(dst_path)

    def test_chown(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('chown', 'soren', '/some/path', run_as_root=True)
        self.mox.ReplayAll()
        libvirt_utils.chown('/some/path', 'soren')

    def _do_test_extract_snapshot(self, dest_format='raw', out_format='raw'):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('qemu-img', 'convert', '-f', 'qcow2', '-O', out_format,
                      '/path/to/disk/image', '/extracted/snap')

        # Start test
        self.mox.ReplayAll()
        libvirt_utils.extract_snapshot('/path/to/disk/image', 'qcow2',
                                       '/extracted/snap', dest_format)

    def test_extract_snapshot_raw(self):
        self._do_test_extract_snapshot()

    def test_extract_snapshot_iso(self):
        self._do_test_extract_snapshot(dest_format='iso')

    def test_extract_snapshot_qcow2(self):
        self._do_test_extract_snapshot(dest_format='qcow2', out_format='qcow2')

    def test_load_file(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            # We have a test for write_to_file. If that is sound, this suffices
            libvirt_utils.write_to_file(dst_path, 'hello')
            self.assertEqual(libvirt_utils.load_file(dst_path), 'hello')
        finally:
            os.unlink(dst_path)

    def test_file_open(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            # We have a test for write_to_file. If that is sound, this suffices
            libvirt_utils.write_to_file(dst_path, 'hello')
            with libvirt_utils.file_open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
        finally:
            os.unlink(dst_path)

    def test_get_fs_info(self):

        class FakeStatResult(object):

            def __init__(self):
                self.f_bsize = 4096
                self.f_frsize = 4096
                self.f_blocks = 2000
                self.f_bfree = 1000
                self.f_bavail = 900
                self.f_files = 2000
                self.f_ffree = 1000
                self.f_favail = 900
                self.f_flag = 4096
                self.f_namemax = 255

        self.path = None

        def fake_statvfs(path):
            self.path = path
            return FakeStatResult()

        self.stubs.Set(os, 'statvfs', fake_statvfs)

        fs_info = libvirt_utils.get_fs_info('/some/file/path')
        self.assertEqual('/some/file/path', self.path)
        self.assertEqual(8192000, fs_info['total'])
        self.assertEqual(3686400, fs_info['free'])
        self.assertEqual(4096000, fs_info['used'])

    def test_fetch_image(self):
        self.mox.StubOutWithMock(images, 'fetch_to_raw')

        context = 'opaque context'
        target = '/tmp/targetfile'
        image_id = '4'
        user_id = 'fake'
        project_id = 'fake'
        images.fetch_to_raw(context, image_id, target, user_id, project_id,
                            max_size=0)

        self.mox.ReplayAll()
        libvirt_utils.fetch_image(context, target, image_id,
                                  user_id, project_id)

    def test_fetch_raw_image(self):

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        def fake_rename(old, new):
            self.executes.append(('mv', old, new))

        def fake_unlink(path):
            self.executes.append(('rm', path))

        def fake_rm_on_error(path, remove=None):
            self.executes.append(('rm', '-f', path))

        def fake_qemu_img_info(path):
            class FakeImgInfo(object):
                pass

            file_format = path.split('.')[-1]
            if file_format == 'part':
                file_format = path.split('.')[-2]
            elif file_format == 'converted':
                file_format = 'raw'

            if 'backing' in path:
                backing_file = 'backing'
            else:
                backing_file = None

            if 'big' in path:
                virtual_size = 2
            else:
                virtual_size = 1

            FakeImgInfo.file_format = file_format
            FakeImgInfo.backing_file = backing_file
            FakeImgInfo.virtual_size = virtual_size

            return FakeImgInfo()

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os, 'rename', fake_rename)
        self.stubs.Set(os, 'unlink', fake_unlink)
        self.stubs.Set(images, 'fetch', lambda *_, **__: None)
        self.stubs.Set(images, 'qemu_img_info', fake_qemu_img_info)
        self.stubs.Set(fileutils, 'delete_if_exists', fake_rm_on_error)

        # Since the remove param of fileutils.remove_path_on_error()
        # is initialized at load time, we must provide a wrapper
        # that explicitly resets it to our fake delete_if_exists()
        old_rm_path_on_error = fileutils.remove_path_on_error
        f = functools.partial(old_rm_path_on_error, remove=fake_rm_on_error)
        self.stubs.Set(fileutils, 'remove_path_on_error', f)

        context = 'opaque context'
        image_id = '4'
        user_id = 'fake'
        project_id = 'fake'

        target = 't.qcow2'
        self.executes = []
        expected_commands = [('qemu-img', 'convert', '-O', 'raw',
                              't.qcow2.part', 't.qcow2.converted'),
                             ('rm', 't.qcow2.part'),
                             ('mv', 't.qcow2.converted', 't.qcow2')]
        images.fetch_to_raw(context, image_id, target, user_id, project_id,
                            max_size=1)
        self.assertEqual(self.executes, expected_commands)

        target = 't.raw'
        self.executes = []
        expected_commands = [('mv', 't.raw.part', 't.raw')]
        images.fetch_to_raw(context, image_id, target, user_id, project_id)
        self.assertEqual(self.executes, expected_commands)

        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw,
                          context, image_id, target, user_id, project_id)
        self.assertEqual(self.executes, expected_commands)

        target = 'big.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'big.qcow2.part')]
        self.assertRaises(exception.FlavorDiskTooSmall,
                          images.fetch_to_raw,
                          context, image_id, target, user_id, project_id,
                          max_size=1)
        self.assertEqual(self.executes, expected_commands)

        del self.executes

    def test_get_disk_backing_file(self):
        with_actual_path = False

        def fake_execute(*args, **kwargs):
            if with_actual_path:
                return ("some: output\n"
                        "backing file: /foo/bar/baz (actual path: /a/b/c)\n"
                        "...: ...\n"), ''
            else:
                return ("some: output\n"
                        "backing file: /foo/bar/baz\n"
                        "...: ...\n"), ''

        def return_true(*args, **kwargs):
            return True

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os.path, 'exists', return_true)

        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'baz')
        with_actual_path = True
        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'c')


class LibvirtDriverTestCase(test.TestCase):
    """Test for nova.virt.libvirt.libvirt_driver.LibvirtDriver."""
    def setUp(self):
        super(LibvirtDriverTestCase, self).setUp()
        self.libvirtconnection = libvirt_driver.LibvirtDriver(
            fake.FakeVirtAPI(), read_only=True)
        self.context = context.get_admin_context()

    def _create_instance(self, params=None):
        """Create a test instance."""
        if not params:
            params = {}

        sys_meta = flavors.save_flavor_info(
            {}, flavors.get_flavor_by_name('m1.tiny'))

        inst = {}
        inst['image_ref'] = '1'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['host'] = 'host1'
        inst['root_gb'] = 10
        inst['ephemeral_gb'] = 20
        inst['config_drive'] = True
        inst['kernel_id'] = 2
        inst['ramdisk_id'] = 3
        inst['key_data'] = 'ABCDEFG'
        inst['system_metadata'] = sys_meta

        inst.update(params)
        return db.instance_create(self.context, inst)

    def test_migrate_disk_and_power_off_exception(self):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .migrate_disk_and_power_off.
        """

        self.counter = 0
        self.checked_shared_storage = False

        def fake_get_instance_disk_info(instance, xml=None,
                                        block_device_info=None):
            return '[]'

        def fake_destroy(instance):
            pass

        def fake_get_host_ip_addr():
            return '10.0.0.1'

        def fake_execute(*args, **kwargs):
            self.counter += 1
            if self.counter == 1:
                assert False, "intentional failure"

        def fake_os_path_exists(path):
            return True

        def fake_is_storage_shared(dest, inst_base):
            self.checked_shared_storage = True
            return False

        self.stubs.Set(self.libvirtconnection, 'get_instance_disk_info',
                       fake_get_instance_disk_info)
        self.stubs.Set(self.libvirtconnection, '_destroy', fake_destroy)
        self.stubs.Set(self.libvirtconnection, 'get_host_ip_addr',
                       fake_get_host_ip_addr)
        self.stubs.Set(self.libvirtconnection, '_is_storage_shared_with',
                       fake_is_storage_shared)
        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os.path, 'exists', fake_os_path_exists)

        ins_ref = self._create_instance()
        flavor = {'root_gb': 10, 'ephemeral_gb': 20}

        self.assertRaises(AssertionError,
                          self.libvirtconnection.migrate_disk_and_power_off,
                          None, ins_ref, '10.0.0.2', flavor, None)

    def test_migrate_disk_and_power_off(self):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .migrate_disk_and_power_off.
        """

        disk_info = [{'type': 'qcow2', 'path': '/test/disk',
                      'virt_disk_size': '10737418240',
                      'backing_file': '/base/disk',
                      'disk_size': '83886080'},
                     {'type': 'raw', 'path': '/test/disk.local',
                      'virt_disk_size': '10737418240',
                      'backing_file': '/base/disk.local',
                      'disk_size': '83886080'}]
        disk_info_text = jsonutils.dumps(disk_info)

        def fake_get_instance_disk_info(instance, xml=None,
                                        block_device_info=None):
            return disk_info_text

        def fake_destroy(instance):
            pass

        def fake_get_host_ip_addr():
            return '10.0.0.1'

        def fake_execute(*args, **kwargs):
            pass

        self.stubs.Set(self.libvirtconnection, 'get_instance_disk_info',
                       fake_get_instance_disk_info)
        self.stubs.Set(self.libvirtconnection, '_destroy', fake_destroy)
        self.stubs.Set(self.libvirtconnection, 'get_host_ip_addr',
                       fake_get_host_ip_addr)
        self.stubs.Set(utils, 'execute', fake_execute)

        ins_ref = self._create_instance()
        flavor = {'root_gb': 10, 'ephemeral_gb': 20}

        # dest is different host case
        out = self.libvirtconnection.migrate_disk_and_power_off(
               None, ins_ref, '10.0.0.2', flavor, None)
        self.assertEqual(out, disk_info_text)

        # dest is same host case
        out = self.libvirtconnection.migrate_disk_and_power_off(
               None, ins_ref, '10.0.0.1', flavor, None)
        self.assertEqual(out, disk_info_text)

    def test_migrate_disk_and_power_off_resize_error(self):
        instance = self._create_instance()
        flavor = {'root_gb': 5}
        self.assertRaises(
            exception.InstanceFaultRollback,
            self.libvirtconnection.migrate_disk_and_power_off,
            'ctx', instance, '10.0.0.1', flavor, None)

    def test_wait_for_running(self):
        def fake_get_info(instance):
            if instance['name'] == "not_found":
                raise exception.InstanceNotFound(instance_id=instance['uuid'])
            elif instance['name'] == "running":
                return {'state': power_state.RUNNING}
            else:
                return {'state': power_state.SHUTDOWN}

        self.stubs.Set(self.libvirtconnection, 'get_info',
                       fake_get_info)

        # instance not found case
        self.assertRaises(exception.InstanceNotFound,
                self.libvirtconnection._wait_for_running,
                    {'name': 'not_found',
                     'uuid': 'not_found_uuid'})

        # instance is running case
        self.assertRaises(loopingcall.LoopingCallDone,
                self.libvirtconnection._wait_for_running,
                    {'name': 'running',
                     'uuid': 'running_uuid'})

        # else case
        self.libvirtconnection._wait_for_running({'name': 'else',
                                                  'uuid': 'other_uuid'})

    def _test_finish_migration(self, power_on):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .finish_migration.
        """

        disk_info = [{'type': 'qcow2', 'path': '/test/disk',
                      'local_gb': 10, 'backing_file': '/base/disk'},
                     {'type': 'raw', 'path': '/test/disk.local',
                      'local_gb': 10, 'backing_file': '/base/disk.local'}]
        disk_info_text = jsonutils.dumps(disk_info)
        powered_on = power_on
        self.fake_create_domain_called = False

        def fake_can_resize_image(path, size):
            return False

        def fake_extend(path, size, use_cow=False):
            pass

        def fake_to_xml(context, instance, network_info, disk_info,
                        image_meta=None, rescue=None,
                        block_device_info=None, write_to_disk=False):
            return ""

        def fake_plug_vifs(instance, network_info):
            pass

        def fake_create_image(context, inst,
                              disk_mapping, suffix='',
                              disk_images=None, network_info=None,
                              block_device_info=None, inject_files=True):
            self.assertFalse(inject_files)

        def fake_create_domain_and_network(
            context, xml, instance, network_info,
            block_device_info=None, power_on=True, reboot=False,
            vifs_already_plugged=False):
            self.fake_create_domain_called = True
            self.assertEqual(powered_on, power_on)
            self.assertTrue(vifs_already_plugged)

        def fake_enable_hairpin(instance):
            pass

        def fake_execute(*args, **kwargs):
            pass

        def fake_get_info(instance):
            if powered_on:
                return {'state': power_state.RUNNING}
            else:
                return {'state': power_state.SHUTDOWN}

        self.flags(use_cow_images=True)
        self.stubs.Set(libvirt_driver.disk, 'extend', fake_extend)
        self.stubs.Set(libvirt_driver.disk, 'can_resize_image',
                       fake_can_resize_image)
        self.stubs.Set(self.libvirtconnection, 'to_xml', fake_to_xml)
        self.stubs.Set(self.libvirtconnection, 'plug_vifs', fake_plug_vifs)
        self.stubs.Set(self.libvirtconnection, '_create_image',
                       fake_create_image)
        self.stubs.Set(self.libvirtconnection, '_create_domain_and_network',
                       fake_create_domain_and_network)
        self.stubs.Set(self.libvirtconnection, '_enable_hairpin',
                       fake_enable_hairpin)
        self.stubs.Set(utils, 'execute', fake_execute)
        fw = base_firewall.NoopFirewallDriver()
        self.stubs.Set(self.libvirtconnection, 'firewall_driver', fw)
        self.stubs.Set(self.libvirtconnection, 'get_info',
                       fake_get_info)

        ins_ref = self._create_instance()

        self.libvirtconnection.finish_migration(
                      context.get_admin_context(), None, ins_ref,
                      disk_info_text, [], None, None, None, power_on)
        self.assertTrue(self.fake_create_domain_called)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(True)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(False)

    def _test_finish_revert_migration(self, power_on):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .finish_revert_migration.
        """
        powered_on = power_on
        self.fake_create_domain_called = False

        def fake_execute(*args, **kwargs):
            pass

        def fake_plug_vifs(instance, network_info):
            pass

        def fake_create_domain(xml, instance=None, launch_flags=0,
                               power_on=True):
            self.fake_create_domain_called = True
            self.assertEqual(powered_on, power_on)
            return mock.MagicMock()

        def fake_enable_hairpin(instance):
            pass

        def fake_get_info(instance):
            if powered_on:
                return {'state': power_state.RUNNING}
            else:
                return {'state': power_state.SHUTDOWN}

        def fake_to_xml(context, instance, network_info, disk_info,
                        image_meta=None, rescue=None,
                        block_device_info=None):
            return ""

        self.stubs.Set(self.libvirtconnection, 'to_xml', fake_to_xml)
        self.stubs.Set(self.libvirtconnection, 'plug_vifs', fake_plug_vifs)
        self.stubs.Set(utils, 'execute', fake_execute)
        fw = base_firewall.NoopFirewallDriver()
        self.stubs.Set(self.libvirtconnection, 'firewall_driver', fw)
        self.stubs.Set(self.libvirtconnection, '_create_domain',
                       fake_create_domain)
        self.stubs.Set(self.libvirtconnection, '_enable_hairpin',
                       fake_enable_hairpin)
        self.stubs.Set(self.libvirtconnection, 'get_info',
                       fake_get_info)

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            ins_ref = self._create_instance()
            os.mkdir(os.path.join(tmpdir, ins_ref['name']))
            libvirt_xml_path = os.path.join(tmpdir,
                                            ins_ref['name'],
                                            'libvirt.xml')
            f = open(libvirt_xml_path, 'w')
            f.close()

            self.libvirtconnection.finish_revert_migration(
                                       context.get_admin_context(), ins_ref,
                                       [], None, power_on)
            self.assertTrue(self.fake_create_domain_called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(False)

    def _test_finish_revert_migration_after_crash(self, backup_made=True,
                                                  del_inst_failed=False):
        class FakeLoopingCall:
            def start(self, *a, **k):
                return self

            def wait(self):
                return None
        context = 'fake_context'

        self.mox.StubOutWithMock(libvirt_utils, 'get_instance_path')
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(shutil, 'rmtree')
        self.mox.StubOutWithMock(utils, 'execute')

        self.stubs.Set(blockinfo, 'get_disk_info', lambda *a: None)
        self.stubs.Set(self.libvirtconnection, 'to_xml', lambda *a, **k: None)
        self.stubs.Set(self.libvirtconnection, '_create_domain_and_network',
                       lambda *a: None)
        self.stubs.Set(loopingcall, 'FixedIntervalLoopingCall',
                       lambda *a, **k: FakeLoopingCall())

        libvirt_utils.get_instance_path({}).AndReturn('/fake/foo')
        os.path.exists('/fake/foo_resize').AndReturn(backup_made)
        if backup_made:
            if del_inst_failed:
                os_error = OSError(errno.ENOENT, 'No such file or directory')
                shutil.rmtree('/fake/foo').AndRaise(os_error)
            else:
                shutil.rmtree('/fake/foo')
            utils.execute('mv', '/fake/foo_resize', '/fake/foo')

        self.mox.ReplayAll()

        self.libvirtconnection.finish_revert_migration(context, {}, [])

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(backup_made=True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(backup_made=True)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(backup_made=False)

    def test_finish_revert_migration_after_crash_delete_failed(self):
        self._test_finish_revert_migration_after_crash(backup_made=True,
                                                       del_inst_failed=True)

    def test_cleanup_failed_migration(self):
        self.mox.StubOutWithMock(shutil, 'rmtree')
        shutil.rmtree('/fake/inst')
        self.mox.ReplayAll()
        self.libvirtconnection._cleanup_failed_migration('/fake/inst')

    def test_confirm_migration(self):
        ins_ref = self._create_instance()

        self.mox.StubOutWithMock(self.libvirtconnection, "_cleanup_resize")
        self.libvirtconnection._cleanup_resize(ins_ref,
                             _fake_network_info(self.stubs, 1))

        self.mox.ReplayAll()
        self.libvirtconnection.confirm_migration("migration_ref", ins_ref,
                                            _fake_network_info(self.stubs, 1))

    def test_cleanup_resize_same_host(self):
        ins_ref = self._create_instance({'host': CONF.host})

        def fake_os_path_exists(path):
            return True

        self.stubs.Set(os.path, 'exists', fake_os_path_exists)

        self.mox.StubOutWithMock(libvirt_utils, 'get_instance_path')
        self.mox.StubOutWithMock(utils, 'execute')

        libvirt_utils.get_instance_path(ins_ref,
                forceold=True).AndReturn('/fake/inst')
        utils.execute('rm', '-rf', '/fake/inst_resize', delay_on_retry=True,
                      attempts=5)

        self.mox.ReplayAll()
        self.libvirtconnection._cleanup_resize(ins_ref,
                                            _fake_network_info(self.stubs, 1))

    def test_cleanup_resize_not_same_host(self):
        host = 'not' + CONF.host
        ins_ref = self._create_instance({'host': host})

        def fake_os_path_exists(path):
            return True

        def fake_undefine_domain(instance):
            pass

        def fake_unplug_vifs(instance, network_info, ignore_errors=False):
            pass

        def fake_unfilter_instance(instance, network_info):
            pass

        self.stubs.Set(os.path, 'exists', fake_os_path_exists)
        self.stubs.Set(self.libvirtconnection, '_undefine_domain',
                       fake_undefine_domain)
        self.stubs.Set(self.libvirtconnection, 'unplug_vifs',
                       fake_unplug_vifs)
        self.stubs.Set(self.libvirtconnection.firewall_driver,
                       'unfilter_instance', fake_unfilter_instance)

        self.mox.StubOutWithMock(libvirt_utils, 'get_instance_path')
        self.mox.StubOutWithMock(utils, 'execute')

        libvirt_utils.get_instance_path(ins_ref,
                forceold=True).AndReturn('/fake/inst')
        utils.execute('rm', '-rf', '/fake/inst_resize', delay_on_retry=True,
                      attempts=5)

        self.mox.ReplayAll()
        self.libvirtconnection._cleanup_resize(ins_ref,
                                            _fake_network_info(self.stubs, 1))

    def test_get_instance_disk_info_exception(self):
        instance_name = "fake-instance-name"

        class FakeExceptionDomain(FakeVirtDomain):
            def __init__(self):
                super(FakeExceptionDomain, self).__init__()

            def XMLDesc(self, *args):
                raise libvirt.libvirtError("Libvirt error")

        def fake_lookup_by_name(instance_name):
            return FakeExceptionDomain()

        self.stubs.Set(self.libvirtconnection, '_lookup_by_name',
                       fake_lookup_by_name)
        self.assertRaises(exception.InstanceNotFound,
            self.libvirtconnection.get_instance_disk_info,
            instance_name)

    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.list_logical_volumes')
    def test_lvm_disks(self, listlvs, exists):
        instance = instance_obj.Instance(uuid='fake-uuid',
                                         id=1)
        self.flags(images_volume_group='vols', group='libvirt')
        exists.return_value = True
        listlvs.return_value = ['fake-uuid_foo',
                                'instance-00000001_bar',
                                'other-uuid_foo',
                                'instance-00000002_bar']
        disks = self.libvirtconnection._lvm_disks(instance)
        self.assertEqual(['/dev/vols/fake-uuid_foo',
                          '/dev/vols/instance-00000001_bar'], disks)

    def test_is_booted_from_volume(self):
        func = libvirt_driver.LibvirtDriver._is_booted_from_volume
        instance, disk_mapping = {}, {}

        self.assertTrue(func(instance, disk_mapping))
        disk_mapping['disk'] = 'map'
        self.assertTrue(func(instance, disk_mapping))

        instance['image_ref'] = 'uuid'
        self.assertFalse(func(instance, disk_mapping))

    @mock.patch('nova.virt.netutils.get_injected_network_template')
    @mock.patch('nova.virt.disk.api.inject_data')
    def _test_inject_data(self, driver_params, disk_params,
                          disk_inject_data, inj_network,
                          called=True):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())

        class i(object):
            path = '/path'

        def fake_inj_network(*args, **kwds):
            return args[0] or None
        inj_network.side_effect = fake_inj_network

        with mock.patch.object(
                conn.image_backend,
                'image',
                return_value=i()):
            self.flags(inject_partition=0, group='libvirt')

            conn._inject_data(**driver_params)

            if called:
                disk_inject_data.assert_called_once_with(
                    *disk_params,
                    partition=None, mandatory=('files',), use_cow=True)

            self.assertEqual(disk_inject_data.called, called)

    def _test_inject_data_default_driver_params(self):
        return {
            'instance': {
                'uuid': 'fake-uuid',
                'id': 1,
                'kernel_id': None,
                'image_ref': 1,
                'key_data': None,
                'metadata': None
            },
            'network_info': None,
            'admin_pass': None,
            'files': None,
            'suffix': ''
        }

    def test_inject_data_adminpass(self):
        self.flags(inject_password=True, group='libvirt')
        driver_params = self._test_inject_data_default_driver_params()
        driver_params['admin_pass'] = 'foobar'
        disk_params = [
            '/path',  # injection_path
            None,  # key
            None,  # net
            None,  # metadata
            'foobar',  # admin_pass
            None,  # files
        ]
        self._test_inject_data(driver_params, disk_params)

        # Test with the configuration setted to false.
        self.flags(inject_password=False, group='libvirt')
        self._test_inject_data(driver_params, disk_params, called=False)

    def test_inject_data_key(self):
        driver_params = self._test_inject_data_default_driver_params()
        driver_params['instance']['key_data'] = 'key-content'

        self.flags(inject_key=True, group='libvirt')
        disk_params = [
            '/path',  # injection_path
            'key-content',  # key
            None,  # net
            None,  # metadata
            None,  # admin_pass
            None,  # files
        ]
        self._test_inject_data(driver_params, disk_params)

        # Test with the configuration setted to false.
        self.flags(inject_key=False, group='libvirt')
        self._test_inject_data(driver_params, disk_params, called=False)

    def test_inject_data_metadata(self):
        driver_params = self._test_inject_data_default_driver_params()
        driver_params['instance']['metadata'] = 'data'
        disk_params = [
            '/path',  # injection_path
            None,  # key
            None,  # net
            'data',  # metadata
            None,  # admin_pass
            None,  # files
        ]
        self._test_inject_data(driver_params, disk_params)

    def test_inject_data_files(self):
        driver_params = self._test_inject_data_default_driver_params()
        driver_params['files'] = ['file1', 'file2']
        disk_params = [
            '/path',  # injection_path
            None,  # key
            None,  # net
            None,  # metadata
            None,  # admin_pass
            ['file1', 'file2'],  # files
        ]
        self._test_inject_data(driver_params, disk_params)

    def test_inject_data_net(self):
        driver_params = self._test_inject_data_default_driver_params()
        driver_params['network_info'] = {'net': 'eno1'}
        disk_params = [
            '/path',  # injection_path
            None,  # key
            {'net': 'eno1'},  # net
            None,  # metadata
            None,  # admin_pass
            None,  # files
        ]
        self._test_inject_data(driver_params, disk_params)

    def _test_attach_detach_interface(self, method, power_state,
                                      expected_flags):
        instance = self._create_instance()
        network_info = _fake_network_info(self.stubs, 1)
        domain = FakeVirtDomain()
        self.mox.StubOutWithMock(self.libvirtconnection, '_lookup_by_name')
        self.mox.StubOutWithMock(self.libvirtconnection.firewall_driver,
                                 'setup_basic_filtering')
        self.mox.StubOutWithMock(domain, 'attachDeviceFlags')
        self.mox.StubOutWithMock(domain, 'info')

        self.libvirtconnection._lookup_by_name(
            'instance-00000001').AndReturn(domain)
        if method == 'attach_interface':
            self.libvirtconnection.firewall_driver.setup_basic_filtering(
                instance, [network_info[0]])

        fake_flavor = flavor_obj.Flavor.get_by_id(
            self.context, instance['instance_type_id'])
        if method == 'attach_interface':
            fake_image_meta = {'id': instance['image_ref']}
        elif method == 'detach_interface':
            fake_image_meta = None
        expected = self.libvirtconnection.vif_driver.get_config(
            instance, network_info[0], fake_image_meta, fake_flavor)

        self.mox.StubOutWithMock(self.libvirtconnection.vif_driver,
                                 'get_config')
        self.libvirtconnection.vif_driver.get_config(
            instance, network_info[0],
            fake_image_meta,
            mox.IsA(flavor_obj.Flavor)).AndReturn(expected)
        domain.info().AndReturn([power_state])
        if method == 'attach_interface':
            domain.attachDeviceFlags(expected.to_xml(), expected_flags)
        elif method == 'detach_interface':
            domain.detachDeviceFlags(expected.to_xml(), expected_flags)

        self.mox.ReplayAll()
        if method == 'attach_interface':
            self.libvirtconnection.attach_interface(
                instance, fake_image_meta, network_info[0])
        elif method == 'detach_interface':
            self.libvirtconnection.detach_interface(
                instance, network_info[0])
        self.mox.VerifyAll()

    def test_attach_interface_with_running_instance(self):
        self._test_attach_detach_interface(
            'attach_interface', power_state.RUNNING,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG |
                            libvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_attach_interface_with_pause_instance(self):
        self._test_attach_detach_interface(
            'attach_interface', power_state.PAUSED,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG |
                            libvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_attach_interface_with_shutdown_instance(self):
        self._test_attach_detach_interface(
            'attach_interface', power_state.SHUTDOWN,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG))

    def test_detach_interface_with_running_instance(self):
        self._test_attach_detach_interface(
            'detach_interface', power_state.RUNNING,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG |
                            libvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_detach_interface_with_pause_instance(self):
        self._test_attach_detach_interface(
            'detach_interface', power_state.PAUSED,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG |
                            libvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_detach_interface_with_shutdown_instance(self):
        self._test_attach_detach_interface(
            'detach_interface', power_state.SHUTDOWN,
            expected_flags=(libvirt.VIR_DOMAIN_AFFECT_CONFIG))


class LibvirtVolumeUsageTestCase(test.TestCase):
    """Test for LibvirtDriver.get_all_volume_usage."""

    def setUp(self):
        super(LibvirtVolumeUsageTestCase, self).setUp()
        self.conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.c = context.get_admin_context()

        # creating instance
        inst = {}
        inst['uuid'] = '875a8070-d0b9-4949-8b31-104d125c9a64'
        self.ins_ref = db.instance_create(self.c, inst)

        # verify bootable volume device path also
        self.bdms = [{'volume_id': 1,
                      'device_name': '/dev/vde'},
                     {'volume_id': 2,
                      'device_name': 'vda'}]

    def test_get_all_volume_usage(self):
        def fake_block_stats(instance_name, disk):
            return (169L, 688640L, 0L, 0L, -1L)

        self.stubs.Set(self.conn, 'block_stats', fake_block_stats)
        vol_usage = self.conn.get_all_volume_usage(self.c,
              [dict(instance=self.ins_ref, instance_bdms=self.bdms)])

        expected_usage = [{'volume': 1,
                           'instance': self.ins_ref,
                           'rd_bytes': 688640L, 'wr_req': 0L,
                           'flush_operations': -1L, 'rd_req': 169L,
                           'wr_bytes': 0L},
                           {'volume': 2,
                            'instance': self.ins_ref,
                            'rd_bytes': 688640L, 'wr_req': 0L,
                            'flush_operations': -1L, 'rd_req': 169L,
                            'wr_bytes': 0L}]
        self.assertEqual(vol_usage, expected_usage)

    def test_get_all_volume_usage_device_not_found(self):
        def fake_lookup(instance_name):
            raise libvirt.libvirtError('invalid path')

        self.stubs.Set(self.conn, '_lookup_by_name', fake_lookup)
        vol_usage = self.conn.get_all_volume_usage(self.c,
              [dict(instance=self.ins_ref, instance_bdms=self.bdms)])
        self.assertEqual(vol_usage, [])


class LibvirtNonblockingTestCase(test.TestCase):
    """Test libvirtd calls are nonblocking."""

    def setUp(self):
        super(LibvirtNonblockingTestCase, self).setUp()
        self.flags(connection_uri="test:///default",
                   group='libvirt')

    def test_connection_to_primitive(self):
        # Test bug 962840.
        import nova.virt.libvirt.driver as libvirt_driver
        connection = libvirt_driver.LibvirtDriver('')
        connection.set_host_enabled = mock.Mock()
        jsonutils.to_primitive(connection._conn, convert_instances=True)

    def test_tpool_execute_calls_libvirt(self):
        conn = libvirt.virConnect()
        conn.is_expected = True

        self.mox.StubOutWithMock(eventlet.tpool, 'execute')
        eventlet.tpool.execute(
            libvirt.openAuth,
            'test:///default',
            mox.IgnoreArg(),
            mox.IgnoreArg()).AndReturn(conn)
        eventlet.tpool.execute(
            conn.domainEventRegisterAny,
            None,
            libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
            mox.IgnoreArg(),
            mox.IgnoreArg())
        if hasattr(libvirt.virConnect, 'registerCloseCallback'):
            eventlet.tpool.execute(
                conn.registerCloseCallback,
                mox.IgnoreArg(),
                mox.IgnoreArg())
        self.mox.ReplayAll()

        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        c = driver._get_connection()
        self.assertEqual(True, c.is_expected)


class LibvirtVolumeSnapshotTestCase(test.TestCase):
    """Tests for libvirtDriver.volume_snapshot_create/delete."""

    def setUp(self):
        super(LibvirtVolumeSnapshotTestCase, self).setUp()

        self.conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.c = context.get_admin_context()

        self.flags(instance_name_template='instance-%s')

        # creating instance
        self.inst = {}
        self.inst['uuid'] = uuidutils.generate_uuid()
        self.inst['id'] = '1'

        # create domain info
        self.dom_xml = """
              <domain type='kvm'>
                <devices>
                  <disk type='file'>
                     <source file='disk1_file'/>
                     <target dev='vda' bus='virtio'/>
                     <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
                  </disk>
                  <disk type='block'>
                    <source dev='/path/to/dev/1'/>
                    <target dev='vdb' bus='virtio' serial='1234'/>
                  </disk>
                </devices>
              </domain>"""

        self.create_info = {'type': 'qcow2',
                            'snapshot_id': '1234-5678',
                            'new_file': 'new-file'}

        self.volume_uuid = '0e38683e-f0af-418f-a3f1-6b67ea0f919d'
        self.snapshot_id = '9c3ca9f4-9f4e-4dba-bedd-5c5e4b52b162'

        self.delete_info_1 = {'type': 'qcow2',
                              'file_to_merge': 'snap.img',
                              'merge_target_file': None}

        self.delete_info_2 = {'type': 'qcow2',
                              'file_to_merge': 'snap.img',
                              'merge_target_file': 'other-snap.img'}

        self.delete_info_invalid_type = {'type': 'made_up_type',
                                         'file_to_merge': 'some_file',
                                         'merge_target_file':
                                             'some_other_file'}

    def tearDown(self):
        super(LibvirtVolumeSnapshotTestCase, self).tearDown()

    @mock.patch('nova.virt.block_device.DriverVolumeBlockDevice.'
                'refresh_connection_info')
    @mock.patch('nova.objects.block_device.BlockDeviceMapping.'
                'get_by_volume_id')
    def test_volume_refresh_connection_info(self, mock_get_by_volume_id,
                                            mock_refresh_connection_info):
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
            'id': 123,
            'instance_uuid': 'fake-instance',
            'device_name': '/dev/sdb',
            'source_type': 'volume',
            'destination_type': 'volume',
            'volume_id': 'fake-volume-id-1',
            'connection_info': '{"fake": "connection_info"}'})
        mock_get_by_volume_id.return_value = fake_bdm

        self.conn._volume_refresh_connection_info(self.c, self.inst,
                                                  self.volume_uuid)

        mock_get_by_volume_id.assert_called_once_with(self.c, self.volume_uuid)
        mock_refresh_connection_info.assert_called_once_with(self.c, self.inst,
            self.conn._volume_api, self.conn)

    def test_volume_snapshot_create(self, quiesce=True):
        CONF.instance_name_template = 'instance-%s'
        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')

        instance = db.instance_create(self.c, self.inst)

        snapshot_id = 'snap-asdf-qwert'
        new_file = 'new-file'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        self.mox.StubOutWithMock(domain, 'snapshotCreateXML')
        domain.XMLDesc(0).AndReturn(self.dom_xml)

        snap_xml_src = (
           '<domainsnapshot>\n'
           '  <disks>\n'
           '    <disk name="disk1_file" snapshot="external" type="file">\n'
           '      <source file="new-file"/>\n'
           '    </disk>\n'
           '    <disk name="/path/to/dev/1" snapshot="no"/>\n'
           '  </disks>\n'
           '</domainsnapshot>\n')

        # Older versions of libvirt may be missing these.
        libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT = 32
        libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE = 64

        snap_flags = (libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY |
                      libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA |
                      libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT)

        snap_flags_q = snap_flags | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE

        if quiesce:
            domain.snapshotCreateXML(snap_xml_src, snap_flags_q)
        else:
            domain.snapshotCreateXML(snap_xml_src, snap_flags_q).\
                AndRaise(libvirt.libvirtError('quiescing failed, no qemu-ga'))
            domain.snapshotCreateXML(snap_xml_src, snap_flags).AndReturn(0)

        self.mox.ReplayAll()

        self.conn._volume_snapshot_create(self.c, instance, domain,
                                          self.volume_uuid, snapshot_id,
                                          new_file)

        self.mox.VerifyAll()

    def test_volume_snapshot_create_noquiesce(self):
        self.test_volume_snapshot_create(quiesce=False)

    def test_volume_snapshot_create_outer_success(self):
        instance = db.instance_create(self.c, self.inst)

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_create')

        self.conn._lookup_by_name('instance-1').AndReturn(domain)

        self.conn._volume_snapshot_create(self.c,
                                          instance,
                                          domain,
                                          self.volume_uuid,
                                          self.create_info['snapshot_id'],
                                          self.create_info['new_file'])

        self.conn._volume_api.update_snapshot_status(
            self.c, self.create_info['snapshot_id'], 'creating')

        self.mox.StubOutWithMock(self.conn._volume_api, 'get_snapshot')
        self.conn._volume_api.get_snapshot(self.c,
            self.create_info['snapshot_id']).AndReturn({'status': 'available'})
        self.mox.StubOutWithMock(self.conn, '_volume_refresh_connection_info')
        self.conn._volume_refresh_connection_info(self.c, instance,
                                                  self.volume_uuid)

        self.mox.ReplayAll()

        self.conn.volume_snapshot_create(self.c, instance, self.volume_uuid,
                                         self.create_info)

    def test_volume_snapshot_create_outer_failure(self):
        instance = db.instance_create(self.c, self.inst)

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_create')

        self.conn._lookup_by_name('instance-1').AndReturn(domain)

        self.conn._volume_snapshot_create(self.c,
                                          instance,
                                          domain,
                                          self.volume_uuid,
                                          self.create_info['snapshot_id'],
                                          self.create_info['new_file']).\
            AndRaise(exception.NovaException('oops'))

        self.conn._volume_api.update_snapshot_status(
            self.c, self.create_info['snapshot_id'], 'error')

        self.mox.ReplayAll()

        self.assertRaises(exception.NovaException,
                          self.conn.volume_snapshot_create,
                          self.c,
                          instance,
                          self.volume_uuid,
                          self.create_info)

    def test_volume_snapshot_delete_1(self):
        """Deleting newest snapshot -- blockRebase."""

        instance = db.instance_create(self.c, self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockRebase('vda', 'snap.img', 0, 0)

        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1000, 'end': 1000})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id, self.delete_info_1)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_2(self):
        """Deleting older snapshot -- blockCommit."""

        instance = db.instance_create(self.c, self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockCommit('vda', 'other-snap.img', 'snap.img', 0, 0)

        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vda', 0).AndReturn({})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id, self.delete_info_2)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_outer_success(self):
        instance = db.instance_create(self.c, self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_delete')

        self.conn._volume_snapshot_delete(self.c,
                                          instance,
                                          self.volume_uuid,
                                          snapshot_id,
                                          delete_info=self.delete_info_1)

        self.conn._volume_api.update_snapshot_status(
            self.c, snapshot_id, 'deleting')

        self.mox.StubOutWithMock(self.conn, '_volume_refresh_connection_info')
        self.conn._volume_refresh_connection_info(self.c, instance,
                                                  self.volume_uuid)

        self.mox.ReplayAll()

        self.conn.volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                         snapshot_id,
                                         self.delete_info_1)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_outer_failure(self):
        instance = db.instance_create(self.c, self.inst)
        snapshot_id = '1234-9876'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_delete')

        self.conn._volume_snapshot_delete(self.c,
                                          instance,
                                          self.volume_uuid,
                                          snapshot_id,
                                          delete_info=self.delete_info_1).\
            AndRaise(exception.NovaException('oops'))

        self.conn._volume_api.update_snapshot_status(
            self.c, snapshot_id, 'error_deleting')

        self.mox.ReplayAll()

        self.assertRaises(exception.NovaException,
                          self.conn.volume_snapshot_delete,
                          self.c,
                          instance,
                          self.volume_uuid,
                          snapshot_id,
                          self.delete_info_1)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_invalid_type(self):
        instance = db.instance_create(self.c, self.inst)

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, 'has_min_version')

        self.conn.has_min_version(mox.IgnoreArg()).AndReturn(True)

        self.conn._volume_api.update_snapshot_status(
            self.c, self.snapshot_id, 'error_deleting')

        self.mox.ReplayAll()

        self.assertRaises(exception.NovaException,
                          self.conn.volume_snapshot_delete,
                          self.c,
                          instance,
                          self.volume_uuid,
                          self.snapshot_id,
                          self.delete_info_invalid_type)
