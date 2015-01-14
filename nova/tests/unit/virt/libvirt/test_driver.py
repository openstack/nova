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

import __builtin__
import contextlib
import copy
import datetime
import errno
import os
import random
import re
import shutil
import threading
import time
import uuid

import eventlet
from eventlet import greenthread
import fixtures
from lxml import etree
import mock
from mox3 import mox
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import encodeutils
from oslo.utils import importutils
from oslo.utils import timeutils
from oslo.utils import units
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
import six

from nova.api.metadata import base as instance_metadata
from nova.compute import arch
from nova.compute import manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_mode
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.openstack.common import fileutils
from nova.openstack.common import loopingcall
from nova.openstack.common import uuidutils
from nova.pci import manager as pci_manager
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
import nova.tests.unit.image.fake
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_pci_device
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova import version
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt.disk import api as disk
from nova.virt import driver
from nova.virt import fake
from nova.virt import firewall as base_firewall
from nova.virt import hardware
from nova.virt import images
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import firewall
from nova.virt.libvirt import host
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils

try:
    import libvirt
except ImportError:
    libvirt = fakelibvirt
libvirt_driver.libvirt = libvirt
host.libvirt = libvirt


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('instances_path', 'nova.compute.manager')

_fake_network_info = fake_network.fake_get_instance_nw_info

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

    def __init__(self, fake_xml=None, uuidstr=None, id=None, name=None):
        if uuidstr is None:
            uuidstr = str(uuid.uuid4())
        self.uuidstr = uuidstr
        self.id = id
        self.domname = name
        self._info = [power_state.RUNNING, 2048 * units.Mi, 1234 * units.Mi,
                     None, None]
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
        if self.domname is None:
            return "fake-domain %s" % self
        else:
            return self.domname

    def ID(self):
        return self.id

    def info(self):
        return self._info

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

    def attachDevice(self, xml):
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

    def destroy(self):
        pass

    def fsFreeze(self, disks=None, flags=0):
        pass

    def fsThaw(self, disks=None, flags=0):
        pass


class CacheConcurrencyTestCase(test.NoDBTestCase):
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

    def get_config(self, *args):
        """Connect the volume to a fake device."""
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_type = "network"
        conf.source_protocol = "fake"
        conf.source_name = "fake"
        conf.target_dev = "fake"
        conf.target_bus = "fake"
        return conf

    def connect_volume(self, *args):
        """Connect the volume to a fake device."""
        return self.get_config()


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


class LibvirtConnTestCase(test.NoDBTestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(LibvirtConnTestCase, self).setUp()
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

        self.flags(sysinfo_serial="hardware", group="libvirt")

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
                            <feature policy='require' name='hypervisor'/>
                          </cpu>"""

            def getCapabilities(self):
                """Ensure standard capabilities being returned."""
                return """<capabilities>
                            <host><cpu><arch>x86_64</arch>
                            <feature policy='require' name='hypervisor'/>
                            </cpu></host>
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

            def listDevices(self, cap, flags):
                return []

            def lookupByName(self, name):
                pass

            def getHostname(self):
                return "mustard"

            def getType(self):
                return "QEMU"

            def numOfDomains(self):
                return 0

            def listDomainsID(self):
                return []

            def listDefinedDomains(self):
                return []

            def getInfo(self):
                return [arch.X86_64, 123456, 2, 2000,
                        2, 1, 1, 1]

        self.conn = FakeConn()
        self.stubs.Set(host.Host,
                       'get_connection',
                       lambda h: self.conn)

        sys_meta = {
            'instance_type_memory_mb': 2048,
            'instance_type_swap': 0,
            'instance_type_vcpu_weight': None,
            'instance_type_root_gb': 1,
            'instance_type_id': 2,
            'instance_type_name': u'm1.small',
            'instance_type_ephemeral_gb': 0,
            'instance_type_rxtx_factor': 1.0,
            'instance_type_flavorid': u'1',
            'instance_type_vcpus': 1
        }

        self.image_service = nova.tests.unit.image.fake.stub_out_image_service(
                self.stubs)
        self.test_instance = {
            'id': 1,
            'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
            'memory_kb': '1024000',
            'basepath': '/some/path',
            'bridge_name': 'br100',
            'display_name': "Acme webserver",
            'vcpus': 2,
            'project_id': 'fake',
            'bridge': 'br101',
            'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
            'root_gb': 10,
            'ephemeral_gb': 20,
            'instance_type_id': '5',  # m1.small
            'extra_specs': {},
            'system_metadata': sys_meta,
            'pci_devices': objects.PciDeviceList(),
            'numa_topology': None,
            'config_drive': None,
            'vm_mode': None,
            'kernel_id': None,
            'ramdisk_id': None,
            'os_type': 'linux',
            'user_id': '838a72b0-0d54-4827-8fd6-fb1227633ceb',
            'ephemeral_key_uuid': None,
        }

    def relpath(self, path):
        return os.path.relpath(path, CONF.instances_path)

    def tearDown(self):
        nova.tests.unit.image.fake.FakeImageService_reset()
        super(LibvirtConnTestCase, self).tearDown()

    def create_fake_libvirt_mock(self, **kwargs):
        """Defining mocks for LibvirtDriver(libvirt is not used)."""

        # A fake libvirt.virConnect
        class FakeLibvirtDriver(object):
            def defineXML(self, xml):
                return FakeVirtDomain()

        # Creating mocks
        volume_driver = ('iscsi=nova.tests.unit.virt.libvirt.test_driver'
                         '.FakeVolumeDriver')
        self.flags(volume_drivers=[volume_driver],
                   group='libvirt')
        fake = FakeLibvirtDriver()
        # Customizing above fake if necessary
        for key, val in kwargs.items():
            fake.__setattr__(key, val)

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

        return objects.Service(**service_ref)

    def _get_launch_flags(self, conn, network_info, power_on=True,
                          vifs_already_plugged=False):
        timeout = CONF.vif_plugging_timeout

        events = []
        if (conn._conn_supports_start_paused and
            utils.is_neutron() and
            not vifs_already_plugged and
            power_on and timeout):
            events = conn._get_neutron_events(network_info)

        launch_flags = events and libvirt.VIR_DOMAIN_START_PAUSED or 0

        return launch_flags

    def test_public_api_signatures(self):
        baseinst = driver.ComputeDriver(None)
        inst = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.assertPublicAPISignatures(baseinst, inst)

    def test_legacy_block_device_info(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.assertFalse(conn.need_legacy_block_device_info)

    @mock.patch.object(host.Host, "has_min_version")
    def test_min_version_start_ok(self, mock_version):
        mock_version.return_value = True
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        drvr.init_host("dummyhost")

    @mock.patch.object(host.Host, "has_min_version")
    def test_min_version_start_abort(self, mock_version):
        mock_version.return_value = False
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.assertRaises(exception.NovaException,
                          drvr.init_host,
                          "dummyhost")

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_set_host_enabled_with_disable(self, mock_svc):
        # Tests disabling an enabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        svc = self._create_service(host='fake-mini')
        mock_svc.return_value = svc
        conn._set_host_enabled(False)
        self.assertTrue(svc.disabled)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_set_host_enabled_with_enable(self, mock_svc):
        # Tests enabling a disabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        svc = self._create_service(disabled=True, host='fake-mini')
        mock_svc.return_value = svc
        conn._set_host_enabled(True)
        self.assertTrue(svc.disabled)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_set_host_enabled_with_enable_state_enabled(self, mock_svc):
        # Tests enabling an enabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        svc = self._create_service(disabled=False, host='fake-mini')
        mock_svc.return_value = svc
        conn._set_host_enabled(True)
        self.assertFalse(svc.disabled)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_set_host_enabled_with_disable_state_disabled(self, mock_svc):
        # Tests disabling a disabled host.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        svc = self._create_service(disabled=True, host='fake-mini')
        mock_svc.return_value = svc
        conn._set_host_enabled(False)
        self.assertTrue(svc.disabled)

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
        self.mox.StubOutWithMock(host.Host,
                                 'has_min_version')
        host.Host.has_min_version = lambda x, y: False

        self.assertRaises(exception.PciDeviceDetachFailed,
                          conn._detach_pci_devices, None, pci_devices)

    def test_detach_pci_devices(self):

        fake_domXML1 =\
            """<domain> <devices>
            <disk type='file' device='disk'>
            <driver name='qemu' type='qcow2' cache='none'/>
            <source file='xxx'/>
            <target dev='vda' bus='virtio'/>
            <alias name='virtio-disk0'/>
            <address type='pci' domain='0x0000' bus='0x00'
            slot='0x04' function='0x0'/>
            </disk>
            <hostdev mode="subsystem" type="pci" managed="yes">
            <source>
            <address function="0x1" slot="0x10" domain="0x0000"
             bus="0x04"/>
            </source>
            </hostdev></devices></domain>"""

        pci_devices = [dict(hypervisor_name='xxx',
                            id='id1',
                            instance_uuid='uuid',
                            address="0001:04:10:1")]

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        self.mox.StubOutWithMock(host.Host,
                                 'has_min_version')
        host.Host.has_min_version = lambda x, y: True

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 '_get_guest_pci_device')

        class FakeDev():
            def to_xml(self):
                pass

        libvirt_driver.LibvirtDriver._get_guest_pci_device =\
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
        self.mox.StubOutWithMock(host.Host,
                                 'has_min_version')
        host.Host.has_min_version = lambda x, y: True

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 '_get_guest_pci_device')

        class FakeDev():
            def to_xml(self):
                pass

        libvirt_driver.LibvirtDriver._get_guest_pci_device =\
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

    def test_get_connector_storage_ip(self):
        ip = '100.100.100.100'
        storage_ip = '101.101.101.101'
        self.flags(my_block_storage_ip=storage_ip, my_ip=ip)
        volume = {
            'id': 'fake'
        }
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        result = conn.get_volume_connector(volume)
        self.assertEqual(storage_ip, result['ip'])

    def test_lifecycle_event_registration(self):
        calls = []

        def fake_registerErrorHandler(*args, **kwargs):
            calls.append('fake_registerErrorHandler')

        def fake_get_host_capabilities(**args):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = arch.ARMV7

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            calls.append('fake_get_host_capabilities')
            return caps

        @mock.patch.object(libvirt, 'registerErrorHandler',
                           side_effect=fake_registerErrorHandler)
        @mock.patch.object(libvirt_driver.LibvirtDriver,
                           '_get_host_capabilities',
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

        # Tests that the parameters to the _get_guest_xml method
        # are sanitized for passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.assertNotIn('scrubme', args[0])

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conf = mock.Mock()
        with contextlib.nested(
            mock.patch.object(libvirt_driver.LOG, 'debug',
                              side_effect=fake_debug),
            mock.patch.object(conn, '_get_guest_config', return_value=conf)
        ) as (
            debug_mock, conf_mock
        ):
            conn._get_guest_xml(self.context, self.test_instance,
                                network_info={}, disk_info={},
                                image_meta={}, block_device_info=bdi)
            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)

    def test_cpu_features_bug_1217630(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        # Test old version of libvirt, it shouldn't see the `aes' feature
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            del mock_libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES
            caps = conn._get_host_capabilities()
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Test new verion of libvirt, should find the `aes' feature
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            mock_libvirt['VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'] = 1
            # Cleanup the capabilities cache firstly
            conn._caps = None
            caps = conn._get_host_capabilities()
            self.assertIn('aes', [x.name for x in caps.host.cpu.features])

    def test_cpu_features_are_not_duplicated(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        # Test old version of libvirt. Should return single 'hypervisor'
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            del mock_libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES
            caps = conn._get_host_capabilities()
            cnt = [x.name for x in caps.host.cpu.features].count('hypervisor')
            self.assertEqual(1, cnt)

        # Test new version of libvirt. Should still return single 'hypervisor'
        with mock.patch('nova.virt.libvirt.driver.libvirt') as mock_libvirt:
            mock_libvirt['VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'] = 1
            # Cleanup the capabilities cache firstly
            conn._caps = None
            caps = conn._get_host_capabilities()
            cnt = [x.name for x in caps.host.cpu.features].count('hypervisor')
            self.assertEqual(1, cnt)

    def test_baseline_cpu_not_supported(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        # `mock` has trouble stubbing attributes that don't exist yet, so
        # fallback to plain-Python attribute setting/deleting
        cap_str = 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'
        if not hasattr(libvirt_driver.libvirt, cap_str):
            setattr(libvirt_driver.libvirt, cap_str, True)
            self.addCleanup(delattr, libvirt_driver.libvirt, cap_str)

        # Handle just the NO_SUPPORT error
        not_supported_exc = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                'this function is not supported by the connection driver:'
                ' virConnectBaselineCPU',
                error_code=libvirt.VIR_ERR_NO_SUPPORT)

        with mock.patch.object(conn._conn, 'baselineCPU',
                               side_effect=not_supported_exc):
            caps = conn._get_host_capabilities()
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

        # Clear cached result so we can test again...
        conn._caps = None

        # Other errors should not be caught
        other_exc = fakelibvirt.make_libvirtError(
            libvirt.libvirtError,
            'other exc',
            error_code=libvirt.VIR_ERR_NO_DOMAIN)

        with mock.patch.object(conn._conn, 'baselineCPU',
                               side_effect=other_exc):
            self.assertRaises(libvirt.libvirtError,
                              conn._get_host_capabilities)

    def test_lxc_get_host_capabilities_failed(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        with mock.patch.object(conn._conn, 'baselineCPU', return_value=-1):
            setattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES', 1)
            caps = conn._get_host_capabilities()
            delattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES')
            self.assertEqual(vconfig.LibvirtConfigCaps, type(caps))
            self.assertNotIn('aes', [x.name for x in caps.host.cpu.features])

    @mock.patch.object(time, "time")
    def test_get_guest_config(self, time_mock):
        time_mock.return_value = 1234567.89

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        test_instance = copy.deepcopy(self.test_instance)
        test_instance["display_name"] = "purple tomatoes"

        ctxt = context.RequestContext(project_id=123,
                                      project_name="aubergine",
                                      user_id=456,
                                      user_name="pie")

        flavor = objects.Flavor(name='m1.small',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs={})
        instance_ref = objects.Instance(**test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info,
                                     context=ctxt, flavor=flavor)

        self.assertEqual(cfg.uuid, instance_ref["uuid"])
        self.assertEqual(2, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureAPIC)
        self.assertEqual(cfg.memory, 6 * units.Ki)
        self.assertEqual(cfg.vcpus, 28)
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
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[4],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestInput)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigMemoryBalloon)
        self.assertEqual(len(cfg.metadata), 1)
        self.assertIsInstance(cfg.metadata[0],
                              vconfig.LibvirtConfigGuestMetaNovaInstance)
        self.assertEqual(version.version_string_with_package(),
                         cfg.metadata[0].package)
        self.assertEqual("purple tomatoes",
                         cfg.metadata[0].name)
        self.assertEqual(1234567.89,
                         cfg.metadata[0].creationTime)
        self.assertEqual("image",
                         cfg.metadata[0].roottype)
        self.assertEqual(str(instance_ref["image_ref"]),
                         cfg.metadata[0].rootid)

        self.assertIsInstance(cfg.metadata[0].owner,
                              vconfig.LibvirtConfigGuestMetaNovaOwner)
        self.assertEqual(456,
                         cfg.metadata[0].owner.userid)
        self.assertEqual("pie",
                         cfg.metadata[0].owner.username)
        self.assertEqual(123,
                         cfg.metadata[0].owner.projectid)
        self.assertEqual("aubergine",
                         cfg.metadata[0].owner.projectname)

        self.assertIsInstance(cfg.metadata[0].flavor,
                              vconfig.LibvirtConfigGuestMetaNovaFlavor)
        self.assertEqual("m1.small",
                         cfg.metadata[0].flavor.name)
        self.assertEqual(6,
                         cfg.metadata[0].flavor.memory)
        self.assertEqual(28,
                         cfg.metadata[0].flavor.vcpus)
        self.assertEqual(496,
                         cfg.metadata[0].flavor.disk)
        self.assertEqual(8128,
                         cfg.metadata[0].flavor.ephemeral)
        self.assertEqual(33550336,
                         cfg.metadata[0].flavor.swap)

    def test_get_guest_config_lxc(self):
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}

        cfg = conn._get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    None, {'mapping': {}}, flavor=flavor)
        self.assertEqual(instance_ref["uuid"], cfg.uuid)
        self.assertEqual(2 * units.Mi, cfg.memory)
        self.assertEqual(1, cfg.vcpus)
        self.assertEqual(vm_mode.EXE, cfg.os_type)
        self.assertEqual("/sbin/init", cfg.os_init_path)
        self.assertEqual("console=tty0 console=ttyS0", cfg.os_cmdline)
        self.assertIsNone(cfg.os_root)
        self.assertEqual(3, len(cfg.devices))
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestFilesys)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestInterface)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestConsole)

    def test_get_guest_config_lxc_with_id_maps(self):
        self.flags(virt_type='lxc', group='libvirt')
        self.flags(uid_maps=['0:1000:100'], group='libvirt')
        self.flags(gid_maps=['0:1000:100'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}

        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     None, {'mapping': {}}, flavor=flavor)
        self.assertEqual(instance_ref["uuid"], cfg.uuid)
        self.assertEqual(2 * units.Mi, cfg.memory)
        self.assertEqual(1, cfg.vcpus)
        self.assertEqual(vm_mode.EXE, cfg.os_type)
        self.assertEqual("/sbin/init", cfg.os_init_path)
        self.assertEqual("console=tty0 console=ttyS0", cfg.os_cmdline)
        self.assertIsNone(cfg.os_root)
        self.assertEqual(3, len(cfg.devices))
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestFilesys)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestInterface)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestConsole)
        self.assertEqual(len(cfg.idmaps), 2)
        self.assertIsInstance(cfg.idmaps[0],
                              vconfig.LibvirtConfigGuestUIDMap)
        self.assertIsInstance(cfg.idmaps[1],
                              vconfig.LibvirtConfigGuestGIDMap)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_numa_host_instance_fits(self, mock_flavor):
        instance_ref = objects.Instance(**self.test_instance)
        flavor = objects.Flavor(memory_mb=1, vcpus=2, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps),
                mock.patch.object(
                        random, 'choice', side_effect=lambda cells: cells[0])):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            self.assertEqual(set([0, 1]), cfg.cpuset)
            self.assertIsNone(cfg.cputune)
            self.assertIsNone(cfg.cpu.numa)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_numa_host_instance_no_fit(self, mock_flavor):
        instance_ref = objects.Instance(**self.test_instance)
        flavor = objects.Flavor(memory_mb=4096, vcpus=4, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps),
                mock.patch.object(
                    hardware, 'get_vcpu_pin_set', return_value=set([3])),
                mock.patch.object(random, 'choice')
            ) as (get_host_cap_mock,
                  get_vcpu_pin_set_mock, choice_mock):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            self.assertFalse(choice_mock.called)
            self.assertEqual(set([3]), cfg.cpuset)
            self.assertIsNone(cfg.cputune)
            self.assertIsNone(cfg.cpu.numa)

    def _test_get_guest_memory_backing_config(
            self, host_topology, inst_topology, numatune):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        with mock.patch.object(
                conn, "_get_host_numa_topology",
                return_value=host_topology):
            return conn._get_guest_memory_backing_config(
                inst_topology, numatune)

    def test_get_guest_memory_backing_config_large_success(self):
        host_topology = objects.NUMATopology(
            cells=[
                objects.NUMACell(
                    id=3, cpuset=set([1]), memory=1024, mempages=[
                        objects.NUMAPagesTopology(size_kb=4, total=2000,
                                                  used=0),
                        objects.NUMAPagesTopology(size_kb=2048, total=512,
                                                  used=0),
                        objects.NUMAPagesTopology(size_kb=1048576, total=0,
                                                  used=0),
                    ])])
        inst_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=3, cpuset=set([0, 1]), memory=1024, pagesize=2048)])

        numa_tune = vconfig.LibvirtConfigGuestNUMATune()
        numa_tune.memnodes = [vconfig.LibvirtConfigGuestNUMATuneMemNode()]
        numa_tune.memnodes[0].cellid = 0
        numa_tune.memnodes[0].nodeset = [3]

        result = self._test_get_guest_memory_backing_config(
            host_topology, inst_topology, numa_tune)
        self.assertEqual(1, len(result.hugepages))
        self.assertEqual(2048, result.hugepages[0].size_kb)
        self.assertEqual([0], result.hugepages[0].nodeset)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_numa_host_instance_fit_w_cpu_pinset(self,
                                                                  mock_flavor):
        instance_ref = objects.Instance(**self.test_instance)
        flavor = objects.Flavor(memory_mb=1024, vcpus=2, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps),
                mock.patch.object(
                    hardware, 'get_vcpu_pin_set', return_value=set([2, 3])),
                mock.patch.object(
                    random, 'choice', side_effect=lambda cells: cells[0])
                ) as (has_min_version_mock, get_host_cap_mock,
                        get_vcpu_pin_set_mock, choice_mock):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            # NOTE(ndipanov): we make sure that pin_set was taken into account
            # when choosing viable cells
            choice_mock.assert_called_once_with([set([2, 3])])
            self.assertEqual(set([2, 3]), cfg.cpuset)
            self.assertIsNone(cfg.cputune)
            self.assertIsNone(cfg.cpu.numa)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_non_numa_host_instance_topo(self, mock_flavor):
        instance_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=0, cpuset=set([0]), memory=1024),
                           objects.InstanceNUMACell(
                        id=1, cpuset=set([2]), memory=1024)])
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.numa_topology = instance_topology
        flavor = objects.Flavor(memory_mb=2048, vcpus=2, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(
                    objects.InstanceNUMATopology, "get_by_instance_uuid",
                    return_value=instance_topology),
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps)):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            self.assertIsNone(cfg.cpuset)
            self.assertIsNone(cfg.cputune)
            self.assertIsNone(cfg.numatune)
            self.assertIsNotNone(cfg.cpu.numa)
            for instance_cell, numa_cfg_cell in zip(
                    instance_topology.cells, cfg.cpu.numa.cells):
                self.assertEqual(instance_cell.id, numa_cfg_cell.id)
                self.assertEqual(instance_cell.cpuset, numa_cfg_cell.cpus)
                self.assertEqual(instance_cell.memory * units.Ki,
                                 numa_cfg_cell.memory)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_numa_host_instance_topo(self, mock_flavor):
        instance_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=1, cpuset=set([0, 1]), memory=1024, pagesize=None),
                           objects.InstanceNUMACell(
                               id=2, cpuset=set([2, 3]), memory=1024,
                               pagesize=None)])
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.numa_topology = instance_topology
        flavor = objects.Flavor(memory_mb=2048, vcpus=4, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(
                    objects.Flavor, "get_by_id", return_value=flavor),
                mock.patch.object(
                    objects.InstanceNUMATopology, "get_by_instance_uuid",
                    return_value=instance_topology),
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps),
                mock.patch.object(
                    hardware, 'get_vcpu_pin_set',
                    return_value=set([2, 3, 4, 5]))
                ):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            self.assertIsNone(cfg.cpuset)
            # Test that the pinning is correct and limited to allowed only
            self.assertEqual(0, cfg.cputune.vcpupin[0].id)
            self.assertEqual(set([2, 3]), cfg.cputune.vcpupin[0].cpuset)
            self.assertEqual(1, cfg.cputune.vcpupin[1].id)
            self.assertEqual(set([2, 3]), cfg.cputune.vcpupin[1].cpuset)
            self.assertEqual(2, cfg.cputune.vcpupin[2].id)
            self.assertEqual(set([4, 5]), cfg.cputune.vcpupin[2].cpuset)
            self.assertEqual(3, cfg.cputune.vcpupin[3].id)
            self.assertEqual(set([4, 5]), cfg.cputune.vcpupin[3].cpuset)
            self.assertIsNotNone(cfg.cpu.numa)

            self.assertIsInstance(cfg.cputune.emulatorpin,
                                  vconfig.LibvirtConfigGuestCPUTuneEmulatorPin)
            self.assertEqual(set([2, 3, 4, 5]), cfg.cputune.emulatorpin.cpuset)

            for instance_cell, numa_cfg_cell, index in zip(
                    instance_topology.cells,
                    cfg.cpu.numa.cells,
                    range(len(instance_topology.cells))):
                self.assertEqual(index, numa_cfg_cell.id)
                self.assertEqual(instance_cell.cpuset, numa_cfg_cell.cpus)
                self.assertEqual(instance_cell.memory * units.Ki,
                                 numa_cfg_cell.memory)

            allnodes = [cell.id for cell in instance_topology.cells]
            self.assertEqual(allnodes, cfg.numatune.memory.nodeset)
            self.assertEqual("strict", cfg.numatune.memory.mode)

            for instance_cell, memnode, index in zip(
                    instance_topology.cells,
                    cfg.numatune.memnodes,
                    range(len(instance_topology.cells))):
                self.assertEqual(index, memnode.cellid)
                self.assertEqual([instance_cell.id], memnode.nodeset)
                self.assertEqual("strict", memnode.mode)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_numa_host_instance_topo_reordered(self,
                                                                mock_flavor):
        instance_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=3, cpuset=set([0, 1]), memory=1024),
                           objects.InstanceNUMACell(
                        id=0, cpuset=set([2, 3]), memory=1024)])
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.numa_topology = instance_topology
        flavor = objects.Flavor(memory_mb=2048, vcpus=4, root_gb=496,
                                ephemeral_gb=8128, swap=33550336, name='fake',
                                extra_specs={})
        mock_flavor.return_value = flavor

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigCPU()
        caps.host.cpu.arch = "x86_64"
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with contextlib.nested(
                mock.patch.object(
                    objects.Flavor, "get_by_id", return_value=flavor),
                mock.patch.object(
                    objects.InstanceNUMATopology, "get_by_instance_uuid",
                    return_value=instance_topology),
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, "_get_host_capabilities", return_value=caps),
                ):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
            self.assertIsNone(cfg.cpuset)
            # Test that the pinning is correct and limited to allowed only
            self.assertEqual(0, cfg.cputune.vcpupin[0].id)
            self.assertEqual(set([6, 7]), cfg.cputune.vcpupin[0].cpuset)
            self.assertEqual(1, cfg.cputune.vcpupin[1].id)
            self.assertEqual(set([6, 7]), cfg.cputune.vcpupin[1].cpuset)
            self.assertEqual(2, cfg.cputune.vcpupin[2].id)
            self.assertEqual(set([0, 1]), cfg.cputune.vcpupin[2].cpuset)
            self.assertEqual(3, cfg.cputune.vcpupin[3].id)
            self.assertEqual(set([0, 1]), cfg.cputune.vcpupin[3].cpuset)
            self.assertIsNotNone(cfg.cpu.numa)

            self.assertIsInstance(cfg.cputune.emulatorpin,
                                  vconfig.LibvirtConfigGuestCPUTuneEmulatorPin)
            self.assertEqual(set([0, 1, 6, 7]), cfg.cputune.emulatorpin.cpuset)

            for index, (instance_cell, numa_cfg_cell) in enumerate(zip(
                    instance_topology.cells,
                    cfg.cpu.numa.cells)):
                self.assertEqual(index, numa_cfg_cell.id)
                self.assertEqual(instance_cell.cpuset, numa_cfg_cell.cpus)
                self.assertEqual(instance_cell.memory * units.Ki,
                                 numa_cfg_cell.memory)

            allnodes = set([cell.id for cell in instance_topology.cells])
            self.assertEqual(allnodes, set(cfg.numatune.memory.nodeset))
            self.assertEqual("strict", cfg.numatune.memory.mode)

            for index, (instance_cell, memnode) in enumerate(zip(
                    instance_topology.cells,
                    cfg.numatune.memnodes)):
                self.assertEqual(index, memnode.cellid)
                self.assertEqual([instance_cell.id], memnode.nodeset)
                self.assertEqual("strict", memnode.mode)

    def test_get_cpu_numa_config_from_instance(self):
        topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([1, 2]), memory=128),
            objects.InstanceNUMACell(id=1, cpuset=set([3, 4]), memory=128),
        ])
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conf = conn._get_cpu_numa_config_from_instance(topology)

        self.assertIsInstance(conf, vconfig.LibvirtConfigGuestCPUNUMA)
        self.assertEqual(0, conf.cells[0].id)
        self.assertEqual(set([1, 2]), conf.cells[0].cpus)
        self.assertEqual(131072, conf.cells[0].memory)
        self.assertEqual(1, conf.cells[1].id)
        self.assertEqual(set([3, 4]), conf.cells[1].cpus)
        self.assertEqual(131072, conf.cells[1].memory)

    def test_get_cpu_numa_config_from_instance_none(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conf = conn._get_cpu_numa_config_from_instance(None)
        self.assertIsNone(conf)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_clock(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {}
        hpet_map = {
            arch.X86_64: True,
            arch.I686: True,
            arch.PPC: False,
            arch.PPC64: False,
            arch.ARMV7: False,
            arch.AARCH64: False,
            }

        for guestarch, expect_hpet in hpet_map.items():
            with mock.patch.object(libvirt_driver.libvirt_utils,
                                   'get_arch',
                                   return_value=guestarch):
                cfg = conn._get_guest_config(instance_ref, [],
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

    @mock.patch.object(libvirt_utils, 'get_arch')
    @mock.patch.object(host.Host, 'has_min_version')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_windows(self, mock_flavor, mock_version,
                                      mock_get_arch):
        mock_version.return_value = False
        mock_get_arch.return_value = arch.I686
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref['os_type'] = 'windows'
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)

        self.assertIsInstance(cfg.clock,
                              vconfig.LibvirtConfigGuestClock)
        self.assertEqual(cfg.clock.offset, "localtime")

        self.assertEqual(3, len(cfg.clock.timers), cfg.clock.timers)
        self.assertEqual("pit", cfg.clock.timers[0].name)
        self.assertEqual("rtc", cfg.clock.timers[1].name)
        self.assertEqual("hpet", cfg.clock.timers[2].name)
        self.assertFalse(cfg.clock.timers[2].present)

    @mock.patch.object(libvirt_utils, 'get_arch')
    @mock.patch.object(host.Host, 'has_min_version')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_windows_timer(self, mock_flavor, mock_version,
                                            mock_get_arch):
        mock_version.return_value = True
        mock_get_arch.return_value = arch.I686
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref['os_type'] = 'windows'
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)

        self.assertIsInstance(cfg.clock,
                              vconfig.LibvirtConfigGuestClock)
        self.assertEqual(cfg.clock.offset, "localtime")

        self.assertEqual(4, len(cfg.clock.timers), cfg.clock.timers)
        self.assertEqual("pit", cfg.clock.timers[0].name)
        self.assertEqual("rtc", cfg.clock.timers[1].name)
        self.assertEqual("hpet", cfg.clock.timers[2].name)
        self.assertFalse(cfg.clock.timers[2].present)
        self.assertEqual("hypervclock", cfg.clock.timers[3].name)
        self.assertTrue(cfg.clock.timers[3].present)

        self.assertEqual(3, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureAPIC)
        self.assertIsInstance(cfg.features[2],
                              vconfig.LibvirtConfigGuestFeatureHyperV)

    @mock.patch.object(host.Host, 'has_min_version')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_windows_hyperv_feature1(self,
                                                      mock_flavor,
                                                      mock_version):
        def fake_version(lv_ver=None, hv_ver=None, hv_type=None):
            if lv_ver == (1, 0, 0) and hv_ver == (1, 1, 0):
                return True
            return False

        mock_version.side_effect = fake_version
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref['os_type'] = 'windows'
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)

        self.assertIsInstance(cfg.clock,
                              vconfig.LibvirtConfigGuestClock)
        self.assertEqual(cfg.clock.offset, "localtime")

        self.assertEqual(3, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureAPIC)
        self.assertIsInstance(cfg.features[2],
                              vconfig.LibvirtConfigGuestFeatureHyperV)

        self.assertTrue(cfg.features[2].relaxed)
        self.assertFalse(cfg.features[2].spinlocks)
        self.assertFalse(cfg.features[2].vapic)

    @mock.patch.object(host.Host, 'has_min_version')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_windows_hyperv_feature2(self,
                                                      mock_flavor,
                                                      mock_version):
        mock_version.return_value = True
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref['os_type'] = 'windows'
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)

        self.assertIsInstance(cfg.clock,
                              vconfig.LibvirtConfigGuestClock)
        self.assertEqual(cfg.clock.offset, "localtime")

        self.assertEqual(3, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureAPIC)
        self.assertIsInstance(cfg.features[2],
                              vconfig.LibvirtConfigGuestFeatureHyperV)

        self.assertTrue(cfg.features[2].relaxed)
        self.assertTrue(cfg.features[2].spinlocks)
        self.assertEqual(8191, cfg.features[2].spinlock_retries)
        self.assertTrue(cfg.features[2].vapic)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_two_nics(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 2),
                                     {}, disk_info)
        self.assertEqual(2, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureAPIC)
        self.assertEqual(cfg.memory, 2 * units.Mi)
        self.assertEqual(cfg.vcpus, 1)
        self.assertEqual(cfg.os_type, vm_mode.HVM)
        self.assertEqual(cfg.os_boot_dev, ["hd"])
        self.assertIsNone(cfg.os_root)
        self.assertEqual(len(cfg.devices), 10)
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
        self.assertIsInstance(cfg.devices[9],
                              vconfig.LibvirtConfigMemoryBalloon)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_bug_1118829(self, mock_flavor):
        self.flags(virt_type='uml', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

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
        conn._get_guest_config(instance_ref, [], {}, disk_info,
                               None, block_device_info)
        self.assertEqual(instance_ref['root_device_name'], '/dev/vda')

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_root_device_name(self, mock_flavor):
        self.flags(virt_type='uml', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        block_device_info = {'root_device_name': '/dev/vdb'}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref,
                                            block_device_info)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info,
                                     None, block_device_info)
        self.assertEqual(0, len(cfg.features))
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_block_device(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        conn_info = {'driver_volume_type': 'fake'}
        info = {'block_device_mapping': driver_block_device.convert_volumes([
                    fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 1,
                         'source_type': 'volume', 'destination_type': 'volume',
                         'device_name': '/dev/vdc'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 2,
                         'source_type': 'volume', 'destination_type': 'volume',
                         'device_name': '/dev/vdd'}),
                ])}
        info['block_device_mapping'][0]['connection_info'] = conn_info
        info['block_device_mapping'][1]['connection_info'] = conn_info

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, info)
        with mock.patch.object(
                driver_block_device.DriverVolumeBlockDevice, 'save'):
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info,
                                     None, info)
            self.assertIsInstance(cfg.devices[2],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertEqual(cfg.devices[2].target_dev, 'vdc')
            self.assertIsInstance(cfg.devices[3],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertEqual(cfg.devices[3].target_dev, 'vdd')
            self.assertTrue(info['block_device_mapping'][0].save.called)
            self.assertTrue(info['block_device_mapping'][1].save.called)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_lxc_with_attached_volume(self, mock_flavor):
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        conn_info = {'driver_volume_type': 'fake'}
        info = {'block_device_mapping': driver_block_device.convert_volumes([
                  fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 1,
                         'source_type': 'volume', 'destination_type': 'volume',
                         'boot_index': 0}),
                  fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 2,
                         'source_type': 'volume', 'destination_type': 'volume',
                        }),
                  fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 3,
                         'source_type': 'volume', 'destination_type': 'volume',
                        }),
               ])}

        info['block_device_mapping'][0]['connection_info'] = conn_info
        info['block_device_mapping'][1]['connection_info'] = conn_info
        info['block_device_mapping'][2]['connection_info'] = conn_info
        info['block_device_mapping'][0]['mount_device'] = '/dev/vda'
        info['block_device_mapping'][1]['mount_device'] = '/dev/vdc'
        info['block_device_mapping'][2]['mount_device'] = '/dev/vdd'
        with mock.patch.object(
                driver_block_device.DriverVolumeBlockDevice, 'save'):
            disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                instance_ref, info)
            cfg = conn._get_guest_config(instance_ref, [], {}, disk_info,
                                        None, info)
            self.assertIsInstance(cfg.devices[1],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertEqual(cfg.devices[1].target_dev, 'vdc')
            self.assertIsInstance(cfg.devices[2],
                                  vconfig.LibvirtConfigGuestDisk)
            self.assertEqual(cfg.devices[2].target_dev, 'vdd')

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_configdrive(self, mock_flavor):
        # It's necessary to check if the architecture is power, because
        # power doesn't have support to ide, and so libvirt translate
        # all ide calls to scsi

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        # make configdrive.required_by() return True
        instance_ref['config_drive'] = True

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)

        # The last device is selected for this. on x86 is the last ide
        # device (hdd). Since power only support scsi, the last device
        # is sdz

        expect = {"ppc": "sdz", "ppc64": "sdz"}
        disk = expect.get(blockinfo.libvirt_utils.get_arch({}), "hdd")
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(cfg.devices[2].target_dev, disk)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_virtio_scsi_bus(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        image_meta = {"properties": {"hw_scsi_model": "virtio-scsi"}}
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, [], image_meta)
        cfg = conn._get_guest_config(instance_ref, [], image_meta, disk_info)
        self.assertIsInstance(cfg.devices[0],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                         vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                         vconfig.LibvirtConfigGuestController)
        self.assertEqual(cfg.devices[2].model, 'virtio-scsi')

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_virtio_scsi_bus_bdm(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        image_meta = {"properties": {"hw_scsi_model": "virtio-scsi"}}
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        conn_info = {'driver_volume_type': 'fake'}
        bd_info = {
            'block_device_mapping': driver_block_device.convert_volumes([
                    fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 1,
                         'source_type': 'volume', 'destination_type': 'volume',
                         'device_name': '/dev/sdc', 'disk_bus': 'scsi'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 2,
                         'source_type': 'volume', 'destination_type': 'volume',
                         'device_name': '/dev/sdd', 'disk_bus': 'scsi'}),
                ])}
        bd_info['block_device_mapping'][0]['connection_info'] = conn_info
        bd_info['block_device_mapping'][1]['connection_info'] = conn_info

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref, bd_info, image_meta)
        with mock.patch.object(
                driver_block_device.DriverVolumeBlockDevice, 'save'):
            cfg = conn._get_guest_config(instance_ref, [], image_meta,
                    disk_info, [], bd_info)
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_vnc(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False, group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "vnc")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_vnc_and_tablet(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=False, group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_spice_and_tablet(self, mock_flavor):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "spice")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_spice_and_agent(self, mock_flavor):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
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
                              vconfig.LibvirtConfigGuestChannel)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].target_name, "com.redhat.spice.0")
        self.assertEqual(cfg.devices[5].type, "spice")
        self.assertEqual(cfg.devices[6].type, "qxl")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch('nova.console.serial.acquire_port')
    def test_get_guest_config_serial_console(self, acquire_port,
                                             mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        acquire_port.return_value = 11111

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("tcp", cfg.devices[2].type)
        self.assertEqual(11111, cfg.devices[2].listen_port)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_serial_console_through_flavor(self, mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw:serial_port_count': 3}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        self.assertEqual(10, len(cfg.devices))
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
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
        self.assertIsInstance(cfg.devices[9],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("tcp", cfg.devices[2].type)
        self.assertEqual("tcp", cfg.devices[3].type)
        self.assertEqual("tcp", cfg.devices[4].type)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_serial_console_invalid_flavor(self, mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw:serial_port_count': "a"}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.assertRaises(
            exception.ImageSerialPortNumberInvalid,
            conn._get_guest_config, instance_ref, [], {}, disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_serial_console_image_and_flavor(self,
                                                              mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        image_meta = {"properties": {"hw_serial_port_count": "3"}}
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw:serial_port_count': 4}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], image_meta,
                                     disk_info)
        self.assertEqual(10, len(cfg.devices), cfg.devices)
        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[2],
                              vconfig.LibvirtConfigGuestSerial)
        self.assertIsInstance(cfg.devices[3],
                              vconfig.LibvirtConfigGuestSerial)
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
        self.assertIsInstance(cfg.devices[9],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("tcp", cfg.devices[2].type)
        self.assertEqual("tcp", cfg.devices[3].type)
        self.assertEqual("tcp", cfg.devices[4].type)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_serial_console_invalid_img_meta(self,
                                                              mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_serial_port_count": "fail"}}
        self.assertRaises(
            exception.ImageSerialPortNumberInvalid,
            conn._get_guest_config, instance_ref, [], image_meta, disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch('nova.console.serial.acquire_port')
    def test_get_guest_config_serial_console_through_port_rng_exhausted(
            self, acquire_port, mock_flavor):
        self.flags(enabled=True, group='serial_console')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        acquire_port.side_effect = exception.SocketPortRangeExhaustedException(
            '127.0.0.1')
        self.assertRaises(
            exception.SocketPortRangeExhaustedException,
            conn._get_guest_config, instance_ref, [], {}, disk_info)

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_get_serial_ports_from_instance(self, _lookup_by_name):
        i = self._test_get_serial_ports_from_instance(_lookup_by_name)
        self.assertEqual([
            ('127.0.0.1', 100),
            ('127.0.0.1', 101),
            ('127.0.0.2', 100),
            ('127.0.0.2', 101)], list(i))

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_get_serial_ports_from_instance_bind_only(self, _lookup_by_name):
        i = self._test_get_serial_ports_from_instance(
            _lookup_by_name, mode='bind')
        self.assertEqual([
            ('127.0.0.1', 101),
            ('127.0.0.2', 100)], list(i))

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_get_serial_ports_from_instance_connect_only(self,
                                                         _lookup_by_name):
        i = self._test_get_serial_ports_from_instance(
            _lookup_by_name, mode='connect')
        self.assertEqual([
            ('127.0.0.1', 100),
            ('127.0.0.2', 101)], list(i))

    def _test_get_serial_ports_from_instance(self, _lookup_by_name, mode=None):
        xml = """
        <domain type='kvm'>
          <devices>
            <serial type="tcp">
              <source host="127.0.0.1" service="100" mode="connect"/>
            </serial>
            <serial type="tcp">
              <source host="127.0.0.1" service="101" mode="bind"/>
            </serial>
            <serial type="tcp">
              <source host="127.0.0.2" service="100" mode="bind"/>
            </serial>
            <serial type="tcp">
              <source host="127.0.0.2" service="101" mode="connect"/>
            </serial>
          </devices>
        </domain>"""

        dom = mock.MagicMock()
        dom.XMLDesc.return_value = xml
        _lookup_by_name.return_value = dom

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance = objects.Instance(**self.test_instance)
        return conn._get_serial_ports_from_instance(
            instance, mode=mode)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_type_xen(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='xen',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        self.assertEqual(len(cfg.devices), 6)
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
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[3].type, "vnc")
        self.assertEqual(cfg.devices[4].type, "xen")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_type_kvm_on_s390(self, mock_flavor):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        host_arch = arch.S390X
        self._stub_host_capabilities_cpu_arch(host_arch)
        self._stub_guest_cpu_config_arch(host_arch)

        instance_ref = self._get_flavor_mocked_test_instance(mock_flavor)

        cfg = self._get_guest_config_via_fake_api(instance_ref)

        self.assertIsInstance(cfg.devices[0],
                              vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(cfg.devices[1],
                              vconfig.LibvirtConfigGuestDisk)
        log_file_device = cfg.devices[2]
        self.assertIsInstance(log_file_device,
                              vconfig.LibvirtConfigGuestConsole)
        self.assertEqual("sclplm", log_file_device.target_type)
        self.assertEqual("file", log_file_device.type)
        terminal_device = cfg.devices[3]
        self.assertIsInstance(terminal_device,
                              vconfig.LibvirtConfigGuestConsole)
        self.assertEqual("sclp", terminal_device.target_type)
        self.assertEqual("pty", terminal_device.type)
        self.assertEqual("s390-ccw-virtio", cfg.os_mach_type)
        self.assertEqual("s390x", cfg.cpu.arch)

    def _stub_host_capabilities_cpu_arch(self, cpu_arch):
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = cpu_arch

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "_get_host_capabilities",
                       get_host_capabilities_stub)

    def _stub_guest_cpu_config_arch(self, cpu_arch):
        def get_guest_cpu_config(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = cpu_arch
            return cpu

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "_get_guest_cpu_model_config",
                       get_guest_cpu_config)

    def _get_flavor_mocked_test_instance(self, mock_flavor):
        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        return instance

    def _get_guest_config_via_fake_api(self, instance):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance)
        return conn._get_guest_config(instance, [], {}, disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_type_xen_pae_hvm(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='xen',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref['vm_mode'] = vm_mode.HVM
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)

        self.assertEqual(cfg.os_type, vm_mode.HVM)
        self.assertEqual(cfg.os_loader, CONF.libvirt.xen_hvmloader_path)
        self.assertEqual(3, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeaturePAE)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[2],
                              vconfig.LibvirtConfigGuestFeatureAPIC)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_type_xen_pae_pvm(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='xen',
                   use_usb_tablet=False,
                   group='libvirt')
        self.flags(enabled=False,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)

        self.assertEqual(cfg.os_type, vm_mode.XEN)
        self.assertEqual(3, len(cfg.features))
        self.assertIsInstance(cfg.features[0],
                              vconfig.LibvirtConfigGuestFeaturePAE)
        self.assertIsInstance(cfg.features[1],
                              vconfig.LibvirtConfigGuestFeatureACPI)
        self.assertIsInstance(cfg.features[2],
                              vconfig.LibvirtConfigGuestFeatureAPIC)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_vnc_and_spice(self, mock_flavor):
        self.flags(vnc_enabled=True)
        self.flags(virt_type='kvm',
                   use_usb_tablet=True,
                   group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        self.assertEqual(len(cfg.devices), 10)
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
        self.assertIsInstance(cfg.devices[9],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].target_name, "com.redhat.spice.0")
        self.assertEqual(cfg.devices[6].type, "vnc")
        self.assertEqual(cfg.devices[7].type, "spice")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_invalid_watchdog_action(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_watchdog_action": "something"}}
        self.assertRaises(exception.InvalidWatchdogAction,
                          conn._get_guest_config,
                          instance_ref,
                          [],
                          image_meta,
                          disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_watchdog_action_image_meta(self,
                                                              mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_watchdog_action": "none"}}
        cfg = conn._get_guest_config(instance_ref, [], image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestWatchdog)
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("none", cfg.devices[7].action)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _test_get_guest_config_with_watchdog_action_flavor(self, mock_flavor,
            hw_watchdog_action="hw:watchdog_action"):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {hw_watchdog_action: 'none'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)

        self.assertEqual(9, len(cfg.devices))
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
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("none", cfg.devices[7].action)

    def test_get_guest_config_with_watchdog_action_through_flavor(self):
        self._test_get_guest_config_with_watchdog_action_flavor()

    # TODO(pkholkin): the test accepting old property name 'hw_watchdog_action'
    #                should be removed in the next release
    def test_get_guest_config_with_watchdog_action_through_flavor_no_scope(
            self):
        self._test_get_guest_config_with_watchdog_action_flavor(
            hw_watchdog_action="hw_watchdog_action")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_watchdog_overrides_flavor(self,
                                                             mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_watchdog_action': 'none'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_watchdog_action": "pause"}}

        cfg = conn._get_guest_config(instance_ref, [],
                                     image_meta, disk_info)

        self.assertEqual(9, len(cfg.devices))
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
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual("pause", cfg.devices[7].action)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_unsupported_video_driver_through_image_meta(self,
                                                         mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "something"}}
        self.assertRaises(exception.InvalidVideoMode,
                          conn._get_guest_config,
                          instance_ref,
                          [],
                          image_meta,
                          disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_video_driver_image_meta(self,
                                                           mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "vmvga"}}
        cfg = conn._get_guest_config(instance_ref, [], image_meta, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[5].type, "vnc")
        self.assertEqual(cfg.devices[6].type, "vmvga")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_qga_through_image_meta(self,
                                                          mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_qemu_guest_agent": "yes"}}
        cfg = conn._get_guest_config(instance_ref, [], image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigGuestChannel)
        self.assertIsInstance(cfg.devices[8],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")
        self.assertEqual(cfg.devices[7].type, "unix")
        self.assertEqual(cfg.devices[7].target_name, "org.qemu.guest_agent.0")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_video_driver_vram(self, mock_flavor):
        self.flags(vnc_enabled=False)
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_video:ram_max_mb': "100"}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}

        cfg = conn._get_guest_config(instance_ref, [],
                                     image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestChannel)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[5].type, "spice")
        self.assertEqual(cfg.devices[6].type, "qxl")
        self.assertEqual(cfg.devices[6].vram, 64 * units.Mi / units.Ki)

    @mock.patch('nova.virt.disk.api.teardown_container')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.get_info')
    @mock.patch('nova.virt.disk.api.setup_container')
    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
    @mock.patch.object(fake_libvirt_utils, 'get_instance_path')
    def test_unmount_fs_if_error_during_lxc_create_domain(self,
            mock_get_inst_path, mock_ensure_tree, mock_setup_container,
            mock_get_info, mock_teardown):
        """If we hit an error during a `_create_domain` call to `libvirt+lxc`
        we need to ensure the guest FS is unmounted from the host so that any
        future `lvremove` calls will work.
        """
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        mock_instance = mock.MagicMock()
        mock_get_inst_path.return_value = '/tmp/'
        mock_image_backend = mock.MagicMock()
        conn.image_backend = mock_image_backend
        mock_image = mock.MagicMock()
        mock_image.path = '/tmp/test.img'
        conn.image_backend.image.return_value = mock_image
        mock_setup_container.return_value = '/dev/nbd0'
        mock_get_info.side_effect = exception.InstanceNotFound(
                                                   instance_id='foo')
        conn._conn.defineXML = mock.Mock()
        conn._conn.defineXML.side_effect = ValueError('somethingbad')
        with contextlib.nested(
              mock.patch.object(conn, '_is_booted_from_volume',
                                return_value=False),
              mock.patch.object(conn, 'plug_vifs'),
              mock.patch.object(conn, 'firewall_driver'),
              mock.patch.object(conn, 'cleanup')):
            self.assertRaises(ValueError,
                              conn._create_domain_and_network,
                              self.context,
                              'xml',
                              mock_instance, None, None)

            mock_teardown.assert_called_with(container_dir='/tmp/rootfs')

    def test_video_driver_flavor_limit_not_set(self):
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}

        with contextlib.nested(
            mock.patch.object(objects.Flavor, 'get_by_id'),
            mock.patch.object(objects.Instance, 'save'),
        ) as (mock_flavor, mock_instance):
            flavor = instance_ref.get_flavor()
            flavor.extra_specs = {}
            mock_flavor.return_value = flavor

            self.assertRaises(exception.RequestedVRamTooHigh,
                              conn._get_guest_config,
                              instance_ref,
                              [],
                              image_meta,
                              disk_info)

    def test_video_driver_ram_above_flavor_limit(self):
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(enabled=True,
                   agent_enabled=True,
                   group='spice')

        instance_ref = objects.Instance(**self.test_instance)
        instance_type = instance_ref.get_flavor()
        instance_type.extra_specs = {'hw_video:ram_max_mb': "50"}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_video_model": "qxl",
                                     "hw_video_ram": "64"}}
        with contextlib.nested(
                mock.patch.object(objects.Flavor, 'get_by_id',
                                  return_value=instance_type),
                mock.patch.object(objects.Instance, 'save')):
            self.assertRaises(exception.RequestedVRamTooHigh,
                              conn._get_guest_config,
                              instance_ref,
                              [],
                              image_meta,
                              disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_without_qga_through_image_meta(self,
                                                             mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {"properties": {"hw_qemu_guest_agent": "no"}}
        cfg = conn._get_guest_config(instance_ref, [], image_meta, disk_info)
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
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[4].type, "tablet")
        self.assertEqual(cfg.devices[5].type, "vnc")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_rng_device(self, mock_flavor):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_rng:allowed': 'True'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}

        cfg = conn._get_guest_config(instance_ref, [],
                                     image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestRng)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[6].model, 'random')
        self.assertIsNone(cfg.devices[6].backend)
        self.assertIsNone(cfg.devices[6].rate_bytes)
        self.assertIsNone(cfg.devices[6].rate_period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_rng_not_allowed(self, mock_flavor):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}
        cfg = conn._get_guest_config(instance_ref, [],
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
                              vconfig.LibvirtConfigMemoryBalloon)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_rng_limits(self, mock_flavor):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_rng:allowed': 'True',
                              'hw_rng:rate_bytes': '1024',
                              'hw_rng:rate_period': '2'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}

        cfg = conn._get_guest_config(instance_ref, [],
                                     image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestRng)
        self.assertIsInstance(cfg.devices[7],
                            vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[6].model, 'random')
        self.assertIsNone(cfg.devices[6].backend)
        self.assertEqual(cfg.devices[6].rate_bytes, 1024)
        self.assertEqual(cfg.devices[6].rate_period, 2)

    @mock.patch('nova.virt.libvirt.driver.os.path.exists')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_rng_backend(self, mock_flavor, mock_path):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   rng_dev_path='/dev/hw_rng',
                   group='libvirt')
        mock_path.return_value = True

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_rng:allowed': 'True'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}

        cfg = conn._get_guest_config(instance_ref, [],
                                     image_meta, disk_info)
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
                              vconfig.LibvirtConfigGuestGraphics)
        self.assertIsInstance(cfg.devices[5],
                              vconfig.LibvirtConfigGuestVideo)
        self.assertIsInstance(cfg.devices[6],
                              vconfig.LibvirtConfigGuestRng)
        self.assertIsInstance(cfg.devices[7],
                              vconfig.LibvirtConfigMemoryBalloon)

        self.assertEqual(cfg.devices[6].model, 'random')
        self.assertEqual(cfg.devices[6].backend, '/dev/hw_rng')
        self.assertIsNone(cfg.devices[6].rate_bytes)
        self.assertIsNone(cfg.devices[6].rate_period)

    @mock.patch('nova.virt.libvirt.driver.os.path.exists')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_rng_dev_not_present(self, mock_flavor,
                                                       mock_path):
        self.flags(virt_type='kvm',
                   use_usb_tablet=False,
                   rng_dev_path='/dev/hw_rng',
                   group='libvirt')
        mock_path.return_value = False

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'hw_rng:allowed': 'True'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_rng_model": "virtio"}}

        self.assertRaises(exception.RngDeviceNotExist,
                          conn._get_guest_config,
                          instance_ref,
                          [],
                          image_meta, disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_cpu_quota(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'quota:cpu_shares': '10000',
                              'quota:cpu_period': '20000'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)

        self.assertEqual(10000, cfg.cputune.shares)
        self.assertEqual(20000, cfg.cputune.period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_bogus_cpu_quota(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {'quota:cpu_shares': 'fishfood',
                              'quota:cpu_period': '20000'}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.assertRaises(ValueError,
                          conn._get_guest_config,
                          instance_ref, [], {}, disk_info)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _test_get_guest_config_sysinfo_serial(self, expected_serial,
                                              mock_flavor):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        cfg = drvr._get_guest_config_sysinfo(instance_ref)

        self.assertIsInstance(cfg, vconfig.LibvirtConfigGuestSysinfo)
        self.assertEqual(version.vendor_string(),
                         cfg.system_manufacturer)
        self.assertEqual(version.product_string(),
                         cfg.system_product)
        self.assertEqual(version.version_string_with_package(),
                         cfg.system_version)
        self.assertEqual(expected_serial,
                         cfg.system_serial)
        self.assertEqual(instance_ref['uuid'],
                         cfg.system_uuid)

    def test_get_guest_config_sysinfo_serial_none(self):
        self.flags(sysinfo_serial="none", group="libvirt")
        self._test_get_guest_config_sysinfo_serial(None)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_get_host_sysinfo_serial_hardware")
    def test_get_guest_config_sysinfo_serial_hardware(self, mock_uuid):
        self.flags(sysinfo_serial="hardware", group="libvirt")

        theuuid = "56b40135-a973-4eb3-87bb-a2382a3e6dbc"
        mock_uuid.return_value = theuuid

        self._test_get_guest_config_sysinfo_serial(theuuid)

    def test_get_guest_config_sysinfo_serial_os(self):
        self.flags(sysinfo_serial="os", group="libvirt")

        real_open = __builtin__.open
        with contextlib.nested(
                mock.patch.object(__builtin__, "open"),
        ) as (mock_open, ):
            theuuid = "56b40135-a973-4eb3-87bb-a2382a3e6dbc"

            def fake_open(filename, *args, **kwargs):
                if filename == "/etc/machine-id":
                    h = mock.MagicMock()
                    h.read.return_value = theuuid
                    h.__enter__.return_value = h
                    return h
                return real_open(filename, *args, **kwargs)

            mock_open.side_effect = fake_open

            self._test_get_guest_config_sysinfo_serial(theuuid)

    def test_get_guest_config_sysinfo_serial_auto_hardware(self):
        self.flags(sysinfo_serial="auto", group="libvirt")

        real_exists = os.path.exists
        with contextlib.nested(
                mock.patch.object(os.path, "exists"),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  "_get_host_sysinfo_serial_hardware")
        ) as (mock_exists, mock_uuid):
            def fake_exists(filename):
                if filename == "/etc/machine-id":
                    return False
                return real_exists(filename)

            mock_exists.side_effect = fake_exists

            theuuid = "56b40135-a973-4eb3-87bb-a2382a3e6dbc"
            mock_uuid.return_value = theuuid

            self._test_get_guest_config_sysinfo_serial(theuuid)

    def test_get_guest_config_sysinfo_serial_auto_os(self):
        self.flags(sysinfo_serial="auto", group="libvirt")

        real_exists = os.path.exists
        real_open = __builtin__.open
        with contextlib.nested(
                mock.patch.object(os.path, "exists"),
                mock.patch.object(__builtin__, "open"),
        ) as (mock_exists, mock_open):
            def fake_exists(filename):
                if filename == "/etc/machine-id":
                    return True
                return real_exists(filename)

            mock_exists.side_effect = fake_exists

            theuuid = "56b40135-a973-4eb3-87bb-a2382a3e6dbc"

            def fake_open(filename, *args, **kwargs):
                if filename == "/etc/machine-id":
                    h = mock.MagicMock()
                    h.read.return_value = theuuid
                    h.__enter__.return_value = h
                    return h
                return real_open(filename, *args, **kwargs)

            mock_open.side_effect = fake_open

            self._test_get_guest_config_sysinfo_serial(theuuid)

    def test_get_guest_config_sysinfo_serial_invalid(self):
        self.flags(sysinfo_serial="invalid", group="libvirt")

        self.assertRaises(exception.NovaException,
                          libvirt_driver.LibvirtDriver,
                          fake.FakeVirtAPI(),
                          True)

    def _create_fake_service_compute(self):
        service_info = {
            'id': 1729,
            'host': 'fake',
            'report_count': 0
        }
        service_ref = objects.Service(**service_info)

        compute_info = {
            'id': 1729,
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
            'service_id': service_ref['id'],
            'host': service_ref['host']
        }
        compute_ref = objects.ComputeNode(**compute_info)
        return (service_ref, compute_ref)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_pci_passthrough_kvm(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')
        service_ref, compute_ref = self._create_fake_service_compute()

        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        pci_device_info = dict(test_pci_device.fake_db_dev)
        pci_device_info.update(compute_node_id=1,
                               label='fake',
                               status='allocated',
                               address='0000:00:00.1',
                               compute_id=compute_ref['id'],
                               instance_uuid=instance.uuid,
                               request_id=None,
                               extra_info={})
        pci_device = objects.PciDevice(**pci_device_info)
        pci_list = objects.PciDeviceList()
        pci_list.objects.append(pci_device)
        instance.pci_devices = pci_list

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance)
        cfg = conn._get_guest_config(instance, [], {}, disk_info)

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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_with_pci_passthrough_xen(self, mock_flavor):
        self.flags(virt_type='xen', group='libvirt')
        service_ref, compute_ref = self._create_fake_service_compute()

        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        pci_device_info = dict(test_pci_device.fake_db_dev)
        pci_device_info.update(compute_node_id=1,
                               label='fake',
                               status='allocated',
                               address='0000:00:00.2',
                               compute_id=compute_ref['id'],
                               instance_uuid=instance.uuid,
                               request_id=None,
                               extra_info={})
        pci_device = objects.PciDevice(**pci_device_info)
        pci_list = objects.PciDeviceList()
        pci_list.objects.append(pci_device)
        instance.pci_devices = pci_list

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance)
        cfg = conn._get_guest_config(instance, [], {}, disk_info)
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_os_command_line_through_image_meta(self,
                                                                 mock_flavor):
        self.flags(virt_type="kvm",
                   cpu_mode=None,
                   group='libvirt')

        self.test_instance['kernel_id'] = "fake_kernel_id"

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"os_command_line":
            "fake_os_command_line"}}
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     image_meta, disk_info)
        self.assertEqual(cfg.os_cmdline, "fake_os_command_line")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_os_command_line_without_kernel_id(self,
                                                                mock_flavor):
        self.flags(virt_type="kvm",
                cpu_mode=None,
                group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"os_command_line":
            "fake_os_command_line"}}

        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     image_meta, disk_info)
        self.assertIsNone(cfg.os_cmdline)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_os_command_empty(self, mock_flavor):
        self.flags(virt_type="kvm",
                   cpu_mode=None,
                   group='libvirt')

        self.test_instance['kernel_id'] = "fake_kernel_id"

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        # the instance has 'root=/dev/vda console=tty0 console=ttyS0' set by
        # default, so testing an empty string and None value in the
        # os_command_line image property must pass
        image_meta = {"properties": {"os_command_line": ""}}
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     image_meta, disk_info)
        self.assertNotEqual(cfg.os_cmdline, "")

        image_meta = {"properties": {"os_command_line": None}}
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     image_meta, disk_info)
        self.assertIsNotNone(cfg.os_cmdline)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_armv7(self, mock_flavor):
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = arch.ARMV7

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.flags(virt_type="kvm",
                   group="libvirt")

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "_get_host_capabilities",
                       get_host_capabilities_stub)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)
        self.assertEqual(cfg.os_mach_type, "vexpress-a15")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_aarch64(self, mock_flavor):
        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.arch = arch.AARCH64

            caps = vconfig.LibvirtConfigCaps()
            caps.host = vconfig.LibvirtConfigCapsHost()
            caps.host.cpu = cpu
            return caps

        self.flags(virt_type="kvm",
                   group="libvirt")

        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       "_get_host_capabilities",
                       get_host_capabilities_stub)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     {}, disk_info)
        self.assertEqual(cfg.os_mach_type, "virt")

    def test_get_guest_config_machine_type_s390(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.cpu = vconfig.LibvirtConfigGuestCPU()

        host_cpu_archs = (arch.S390, arch.S390X)
        for host_cpu_arch in host_cpu_archs:
            caps.host.cpu.arch = host_cpu_arch
            os_mach_type = conn._get_machine_type(None, caps)
            self.assertEqual('s390-ccw-virtio', os_mach_type)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_machine_type_through_image_meta(self,
                                                              mock_flavor):
        self.flags(virt_type="kvm",
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        image_meta = {"properties": {"hw_machine_type":
            "fake_machine_type"}}
        cfg = conn._get_guest_config(instance_ref,
                                     _fake_network_info(self.stubs, 1),
                                     image_meta, disk_info)
        self.assertEqual(cfg.os_mach_type, "fake_machine_type")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_config_machine_type_from_config(self, mock_flavor):
        self.flags(virt_type='kvm', group='libvirt')
        self.flags(hw_machine_type=['x86_64=fake_machine_type'],
                group='libvirt')

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

        # Make sure the host arch is mocked as x86_64
        self.create_fake_libvirt_mock(getCapabilities=fake_getCapabilities,
                                      baselineCPU=fake_baselineCPU,
                                      getVersion=lambda: 1005001)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        cfg = conn._get_guest_config(instance_ref,
                                    _fake_network_info(self.stubs, 1),
                                    {}, disk_info)
        self.assertEqual(cfg.os_mach_type, "fake_machine_type")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _test_get_guest_config_ppc64(self, device_index, mock_flavor):
        """Test for nova.virt.libvirt.driver.LibvirtDriver._get_guest_config.
        """
        self.flags(virt_type='kvm', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        image_meta = {}
        expected = (arch.PPC64, arch.PPC)
        for guestarch in expected:
            with mock.patch.object(libvirt_driver.libvirt_utils,
                                   'get_arch',
                                   return_value=guestarch):
                cfg = conn._get_guest_config(instance_ref, [],
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_none(self, mock_flavor):
        self.flags(cpu_mode="none", group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertIsNone(conf.cpu.mode)
        self.assertIsNone(conf.cpu.model)
        self.assertEqual(conf.cpu.sockets, 1)
        self.assertEqual(conf.cpu.cores, 1)
        self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_default_kvm(self, mock_flavor):
        self.flags(virt_type="kvm",
                   cpu_mode=None,
                   group='libvirt')

        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 11

        self.stubs.Set(self.conn,
                       "getLibVersion",
                       get_lib_version_stub)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-model")
        self.assertIsNone(conf.cpu.model)
        self.assertEqual(conf.cpu.sockets, 1)
        self.assertEqual(conf.cpu.cores, 1)
        self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_default_uml(self, mock_flavor):
        self.flags(virt_type="uml",
                   cpu_mode=None,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsNone(conf.cpu)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_default_lxc(self, mock_flavor):
        self.flags(virt_type="lxc",
                   cpu_mode=None,
                   group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsNone(conf.cpu)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_host_passthrough(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        self.flags(cpu_mode="host-passthrough", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-passthrough")
        self.assertIsNone(conf.cpu.model)
        self.assertEqual(conf.cpu.sockets, 1)
        self.assertEqual(conf.cpu.cores, 1)
        self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_host_model(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        self.flags(cpu_mode="host-model", group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "host-model")
        self.assertIsNone(conf.cpu.model)
        self.assertEqual(conf.cpu.sockets, 1)
        self.assertEqual(conf.cpu.cores, 1)
        self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_config_custom(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        self.flags(cpu_mode="custom",
                   cpu_model="Penryn",
                   group='libvirt')
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        conf = conn._get_guest_config(instance_ref,
                                      _fake_network_info(self.stubs, 1),
                                      {}, disk_info)
        self.assertIsInstance(conf.cpu,
                              vconfig.LibvirtConfigGuestCPU)
        self.assertEqual(conf.cpu.mode, "custom")
        self.assertEqual(conf.cpu.model, "Penryn")
        self.assertEqual(conf.cpu.sockets, 1)
        self.assertEqual(conf.cpu.cores, 1)
        self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_cpu_topology(self, mock_flavor):
        fake_flavor = objects.flavor.Flavor.get_by_id(
                                 self.context,
                                 self.test_instance['instance_type_id'])
        fake_flavor.vcpus = 8
        fake_flavor.extra_specs = {'hw:cpu_max_sockets': '4'}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        with mock.patch.object(objects.flavor.Flavor, 'get_by_id',
                               return_value=fake_flavor):
            conf = conn._get_guest_config(instance_ref,
                                          _fake_network_info(self.stubs, 1),
                                          {}, disk_info)
            self.assertIsInstance(conf.cpu,
                                  vconfig.LibvirtConfigGuestCPU)
            self.assertEqual(conf.cpu.mode, "host-model")
            self.assertEqual(conf.cpu.sockets, 4)
            self.assertEqual(conf.cpu.cores, 2)
            self.assertEqual(conf.cpu.threads, 1)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_by_default(self, mock_flavor):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                self.assertIsInstance(device,
                                      vconfig.LibvirtConfigMemoryBalloon)
                self.assertEqual('virtio', device.model)
                self.assertEqual(10, device.period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_disable(self, mock_flavor):
        self.flags(mem_stats_period_seconds=0, group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        no_exist = True
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                no_exist = False
                break
        self.assertTrue(no_exist)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_period_value(self, mock_flavor):
        self.flags(mem_stats_period_seconds=21, group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                self.assertIsInstance(device,
                                      vconfig.LibvirtConfigMemoryBalloon)
                self.assertEqual('virtio', device.model)
                self.assertEqual(21, device.period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_qemu(self, mock_flavor):
        self.flags(virt_type='qemu', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                self.assertIsInstance(device,
                                      vconfig.LibvirtConfigMemoryBalloon)
                self.assertEqual('virtio', device.model)
                self.assertEqual(10, device.period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_xen(self, mock_flavor):
        self.flags(virt_type='xen', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                self.assertIsInstance(device,
                                      vconfig.LibvirtConfigMemoryBalloon)
                self.assertEqual('xen', device.model)
                self.assertEqual(10, device.period)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_get_guest_memory_balloon_config_lxc(self, mock_flavor):
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        cfg = conn._get_guest_config(instance_ref, [], {}, disk_info)
        no_exist = True
        for device in cfg.devices:
            if device.root_name == 'memballoon':
                no_exist = False
                break
        self.assertTrue(no_exist)

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
        self._check_xml_and_disk_prefix(instance_data, None)

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
        # It's necessary to check if the architecture is power, because
        # power doesn't have support to ide, and so libvirt translate
        # all ide calls to scsi

        expected = {arch.PPC: ("cdrom", "scsi", "sda"),
                    arch.PPC64: ("cdrom", "scsi", "sda")}

        expec_val = expected.get(blockinfo.libvirt_utils.get_arch({}),
                                  ("cdrom", "ide", "hda"))
        self._check_xml_and_disk_bus({"disk_format": "iso"},
                                      None,
                                      (expec_val,))

    def test_xml_disk_bus_ide_and_virtio(self):
        # It's necessary to check if the architecture is power, because
        # power doesn't have support to ide, and so libvirt translate
        # all ide calls to scsi

        expected = {arch.PPC: ("cdrom", "scsi", "sda"),
                    arch.PPC64: ("cdrom", "scsi", "sda")}

        swap = {'device_name': '/dev/vdc',
                'swap_size': 1}
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'virtio',
                       'device_name': '/dev/vdb',
                       'size': 1}]
        block_device_info = {
                'swap': swap,
                'ephemerals': ephemerals}
        expec_val = expected.get(blockinfo.libvirt_utils.get_arch({}),
                                  ("cdrom", "ide", "hda"))
        self._check_xml_and_disk_bus({"disk_format": "iso"},
                                     block_device_info,
                                     (expec_val,
                                      ("disk", "virtio", "vdb"),
                                      ("disk", "virtio", "vdc")))

    def test_list_instance_domains_fast(self):
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

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.listAllDomains = fake_list_all

        self.mox.ReplayAll()
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        doms = drvr._list_instance_domains_fast()
        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())

        doms = drvr._list_instance_domains_fast(only_running=False)
        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())

    def test_list_instance_domains_slow(self):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")
        vms = [vm1, vm2, vm3, vm4]

        def fake_lookup_id(id):
            for vm in vms:
                if vm.ID() == id:
                    return vm
            ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "No such domain",
                error_code=libvirt.VIR_ERR_NO_DOMAIN)
            raise ex

        def fake_lookup_name(name):
            for vm in vms:
                if vm.name() == name:
                    return vm
            ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "No such domain",
                error_code=libvirt.VIR_ERR_NO_DOMAIN)
            raise ex

        def fake_list_doms():
            # Include one ID that no longer exists
            return [vm1.ID(), vm2.ID(), 666]

        def fake_list_ddoms():
            # Include one name that no longer exists and
            # one dup from running list to show race in
            # transition from inactive -> running
            return [vm1.name(), vm3.name(), vm4.name(), "fishfood"]

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.listDomainsID = fake_list_doms
        libvirt_driver.LibvirtDriver._conn.listDefinedDomains = fake_list_ddoms
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup_id
        libvirt_driver.LibvirtDriver._conn.lookupByName = fake_lookup_name
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 2
        libvirt_driver.LibvirtDriver._conn.numOfDefinedDomains = lambda: 2

        self.mox.ReplayAll()
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        doms = drvr._list_instance_domains_slow()
        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())

        doms = drvr._list_instance_domains_slow(only_running=False)
        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())

    def test_list_instance_domains_fallback_no_support(self):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vms = [vm1, vm2]

        def fake_lookup_id(id):
            for vm in vms:
                if vm.ID() == id:
                    return vm
            ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "No such domain",
                error_code=libvirt.VIR_ERR_NO_DOMAIN)
            raise ex

        def fake_list_doms():
            return [vm1.ID(), vm2.ID()]

        def fake_list_all(flags):
            ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "API is not supported",
                error_code=libvirt.VIR_ERR_NO_SUPPORT)
            raise ex

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.listDomainsID = fake_list_doms
        libvirt_driver.LibvirtDriver._conn.lookupByID = fake_lookup_id
        libvirt_driver.LibvirtDriver._conn.numOfDomains = lambda: 2
        libvirt_driver.LibvirtDriver._conn.listAllDomains = fake_list_all

        self.mox.ReplayAll()
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        doms = drvr._list_instance_domains()
        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].id, vm1.id)
        self.assertEqual(doms[1].id, vm2.id)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains_fast")
    def test_list_instance_domains_filtering(self, mock_list):
        vm0 = FakeVirtDomain(id=0, name="Domain-0")  # Xen dom-0
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        mock_list.return_value = [vm0, vm1, vm2]
        doms = drvr._list_instance_domains()
        self.assertEqual(len(doms), 2)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        mock_list.assert_called_with(True)

        mock_list.return_value = [vm0, vm1, vm2, vm3, vm4]
        doms = drvr._list_instance_domains(only_running=False)
        self.assertEqual(len(doms), 4)
        self.assertEqual(doms[0].name(), vm1.name())
        self.assertEqual(doms[1].name(), vm2.name())
        self.assertEqual(doms[2].name(), vm3.name())
        self.assertEqual(doms[3].name(), vm4.name())
        mock_list.assert_called_with(False)

        mock_list.return_value = [vm0, vm1, vm2]
        doms = drvr._list_instance_domains(only_guests=False)
        self.assertEqual(len(doms), 3)
        self.assertEqual(doms[0].name(), vm0.name())
        self.assertEqual(doms[1].name(), vm1.name())
        self.assertEqual(doms[2].name(), vm2.name())
        mock_list.assert_called_with(True)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_list_instances(self, mock_list):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        mock_list.return_value = [vm1, vm2, vm3, vm4]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        names = drvr.list_instances()
        self.assertEqual(names[0], vm1.name())
        self.assertEqual(names[1], vm2.name())
        self.assertEqual(names[2], vm3.name())
        self.assertEqual(names[3], vm4.name())
        mock_list.assert_called_with(only_running=False)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_list_instance_uuids(self, mock_list):
        vm1 = FakeVirtDomain(id=3, name="instance00000001")
        vm2 = FakeVirtDomain(id=17, name="instance00000002")
        vm3 = FakeVirtDomain(name="instance00000003")
        vm4 = FakeVirtDomain(name="instance00000004")

        mock_list.return_value = [vm1, vm2, vm3, vm4]
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        uuids = drvr.list_instance_uuids()
        self.assertEqual(len(uuids), 4)
        self.assertEqual(uuids[0], vm1.UUIDString())
        self.assertEqual(uuids[1], vm2.UUIDString())
        self.assertEqual(uuids[2], vm3.UUIDString())
        self.assertEqual(uuids[3], vm4.UUIDString())
        mock_list.assert_called_with(only_running=False)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_get_all_block_devices(self, mock_list):
        xml = [
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

        mock_list.return_value = [
            FakeVirtDomain(xml[0], id=3, name="instance00000001"),
            FakeVirtDomain(xml[1], id=1, name="instance00000002"),
            FakeVirtDomain(xml[2], id=5, name="instance00000003")]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        devices = drvr._get_all_block_devices()
        self.assertEqual(devices, ['/path/to/dev/1', '/path/to/dev/3'])
        mock_list.assert_called_with()

    @mock.patch.object(host.Host, "has_min_version", return_value=True)
    def test_quiesce(self, mock_has_min_version):
        self.create_fake_libvirt_mock(lookupByName=self.fake_lookup)
        with mock.patch.object(FakeVirtDomain, "fsFreeze") as mock_fsfreeze:
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
            instance = objects.Instance(**self.test_instance)
            img_meta = {"properties": {"hw_qemu_guest_agent": "yes",
                                       "os_require_quiesce": "yes"}}
            self.assertIsNone(conn.quiesce(self.context, instance, img_meta))
            mock_fsfreeze.assert_called_once_with()

    def test_quiesce_not_supported(self):
        self.create_fake_libvirt_mock()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        instance = objects.Instance(**self.test_instance)
        self.assertRaises(exception.InstanceQuiesceNotSupported,
                      conn.quiesce, self.context, instance, None)

    @mock.patch.object(host.Host, "has_min_version", return_value=True)
    def test_unquiesce(self, mock_has_min_version):
        self.create_fake_libvirt_mock(getLibVersion=lambda: 1002005,
                                      lookupByName=self.fake_lookup)
        with mock.patch.object(FakeVirtDomain, "fsThaw") as mock_fsthaw:
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
            instance = objects.Instance(**self.test_instance)
            img_meta = {"properties": {"hw_qemu_guest_agent": "yes",
                                       "os_require_quiesce": "yes"}}
            self.assertIsNone(conn.unquiesce(self.context, instance, img_meta))
            mock_fsthaw.assert_called_once_with()

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

        # Assign different image_ref from nova/images/fakes for testing ami
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assign different image_ref from nova/images/fakes for testing ami
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

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

        snapshot = self.image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'raw')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lvm_snapshot_in_raw_format(self):
        # Tests Lvm backend snapshot functionality with raw format
        # snapshots.
        xml = """
              <domain type='kvm'>
                   <devices>
                       <disk type='block' device='disk'>
                           <source dev='/dev/some-vg/some-lv'/>
                       </disk>
                   </devices>
              </domain>
              """
        update_task_state_calls = [
            mock.call(task_state=task_states.IMAGE_PENDING_UPLOAD),
            mock.call(task_state=task_states.IMAGE_UPLOADING,
                      expected_state=task_states.IMAGE_PENDING_UPLOAD)]
        mock_update_task_state = mock.Mock()
        mock_lookupByName = mock.Mock(return_value=FakeVirtDomain(xml),
                                      autospec=True)
        volume_info = {'VG': 'nova-vg', 'LV': 'disk'}
        mock_volume_info = mock.Mock(return_value=volume_info,
                                             autospec=True)
        mock_volume_info_calls = [mock.call('/dev/nova-vg/lv')]
        mock_convert_image = mock.Mock()

        def convert_image_side_effect(source, dest, out_format,
                                      run_as_root=True):
            libvirt_driver.libvirt_utils.files[dest] = ''
        mock_convert_image.side_effect = convert_image_side_effect

        self.flags(snapshots_directory='./',
                   snapshot_image_format='raw',
                   images_type='lvm',
                   images_volume_group='nova-vg', group='libvirt')
        libvirt_driver.libvirt_utils.disk_type = "lvm"

        # Start test
        image_service = nova.tests.unit.image.fake.FakeImageService()
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                   '_conn',
                                   autospec=True),
                mock.patch.object(libvirt_driver.imagebackend.lvm,
                                  'volume_info',
                                  mock_volume_info),
                mock.patch.object(libvirt_driver.imagebackend.images,
                                  'convert_image',
                                  mock_convert_image),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  '_lookup_by_name',
                                  mock_lookupByName)):
            conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      mock_update_task_state)

        mock_lookupByName.assert_called_once_with("instance-00000001")
        mock_volume_info.assert_has_calls(mock_volume_info_calls)
        mock_convert_image.assert_called_once_with('/dev/nova-vg/lv',
                                                   mock.ANY,
                                                   'raw',
                                                   run_as_root=True)
        snapshot = image_service.show(context, recv_meta['id'])
        mock_update_task_state.assert_has_calls(update_task_state_calls)
        self.assertEqual('available', snapshot['properties']['image_state'])
        self.assertEqual('active', snapshot['status'])
        self.assertEqual('raw', snapshot['disk_format'])
        self.assertEqual(snapshot_name, snapshot['name'])
        # This is for all the subsequent tests that do not set the value of
        # images type
        self.flags(images_type='default', group='libvirt')
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

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

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        self.stubs.Set(libvirt_driver.libvirt_utils, 'disk_type', 'raw')
        libvirt_driver.libvirt_utils.disk_type = "raw"

        def convert_image(source, dest, out_format):
            libvirt_driver.libvirt_utils.files[dest] = ''

        self.stubs.Set(images, 'convert_image', convert_image)

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
        self.assertIsNone(func_call_matcher.match())
        self.assertEqual(snapshot['properties']['image_state'], 'available')
        self.assertEqual(snapshot['status'], 'active')
        self.assertEqual(snapshot['disk_format'], 'qcow2')
        self.assertEqual(snapshot['name'], snapshot_name)

    def test_lvm_snapshot_in_qcow2_format(self):
        # Tests Lvm backend snapshot functionality with raw format
        # snapshots.
        xml = """
              <domain type='kvm'>
                   <devices>
                       <disk type='block' device='disk'>
                           <source dev='/dev/some-vg/some-lv'/>
                       </disk>
                   </devices>
              </domain>
              """
        update_task_state_calls = [
            mock.call(task_state=task_states.IMAGE_PENDING_UPLOAD),
            mock.call(task_state=task_states.IMAGE_UPLOADING,
                      expected_state=task_states.IMAGE_PENDING_UPLOAD)]
        mock_update_task_state = mock.Mock()
        mock_lookupByName = mock.Mock(return_value=FakeVirtDomain(xml),
                                      autospec=True)
        volume_info = {'VG': 'nova-vg', 'LV': 'disk'}
        mock_volume_info = mock.Mock(return_value=volume_info, autospec=True)
        mock_volume_info_calls = [mock.call('/dev/nova-vg/lv')]
        mock_convert_image = mock.Mock()

        def convert_image_side_effect(source, dest, out_format,
                                      run_as_root=True):
            libvirt_driver.libvirt_utils.files[dest] = ''
        mock_convert_image.side_effect = convert_image_side_effect

        self.flags(snapshots_directory='./',
                   snapshot_image_format='qcow2',
                   images_type='lvm',
                   images_volume_group='nova-vg', group='libvirt')
        libvirt_driver.libvirt_utils.disk_type = "lvm"

        # Start test
        image_service = nova.tests.unit.image.fake.FakeImageService()
        instance_ref = objects.Instance(**self.test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                   '_conn',
                                   autospec=True),
                mock.patch.object(libvirt_driver.imagebackend.lvm,
                                  'volume_info',
                                   mock_volume_info),
                mock.patch.object(libvirt_driver.imagebackend.images,
                                   'convert_image',
                                   mock_convert_image),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                   '_lookup_by_name',
                                   mock_lookupByName)):
            conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      mock_update_task_state)

        mock_lookupByName.assert_called_once_with("instance-00000001")
        mock_volume_info.assert_has_calls(mock_volume_info_calls)
        mock_convert_image.assert_called_once_with('/dev/nova-vg/lv',
                                                   mock.ANY,
                                                   'qcow2',
                                                   run_as_root=True)
        snapshot = image_service.show(context, recv_meta['id'])
        mock_update_task_state.assert_has_calls(update_task_state_calls)
        self.assertEqual('available', snapshot['properties']['image_state'])
        self.assertEqual('active', snapshot['status'])
        self.assertEqual('qcow2', snapshot['disk_format'])
        self.assertEqual(snapshot_name, snapshot['name'])
        self.flags(images_type='default', group='libvirt')
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

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

        # Assign different image_ref from nova/images/fakes for
        # testing different base image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assign different image_ref from nova/images/fakes for
        # testing different base image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

        # Assuming that base image already exists in image_service
        instance_ref = objects.Instance(**test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        # Create new image. It will be updated in snapshot method
        # To work with it from snapshot, the single image_service is needed
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'

        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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
        libvirt_driver.libvirt_utils.disk_type = "qcow2"

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'

        instance_ref = objects.Instance(**test_instance)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assign an image with an architecture defined (x86_64)
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = 'a440c04b-79fa-479c-bed1-0b816eaec379'

        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)

        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id),
                      'architecture': 'fake_arch',
                      'key_a': 'value_a',
                      'key_b': 'value_b'}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

        # Assign a non-existent image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = '661122aa-1234-dede-fefe-babababababa'
        test_instance["os_type"] = 'linux'

        instance_ref = objects.Instance(**test_instance)
        instance_ref.info_cache = objects.InstanceInfoCache(
            network_info=None)
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id),
                      'os_type': instance_ref['os_type']}
        snapshot_name = 'test-snap'
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(libvirt_driver.utils, 'execute')
        libvirt_driver.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        snapshot = self.image_service.show(context, recv_meta['id'])
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

    @mock.patch('nova.virt.libvirt.volume.LibvirtFakeVolumeDriver.'
                'connect_volume')
    @mock.patch('nova.virt.libvirt.volume.LibvirtFakeVolumeDriver.get_config')
    def test_get_volume_config(self, get_config, connect_volume):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        connection_info = {'driver_volume_type': 'fake',
                           'data': {'device_path': '/fake',
                                    'access_mode': 'rw'}}
        bdm = {'device_name': 'vdb',
               'disk_bus': 'fake-bus',
               'device_type': 'fake-type'}
        disk_info = {'bus': bdm['disk_bus'], 'type': bdm['device_type'],
                     'dev': 'vdb'}
        mock_config = mock.MagicMock()

        get_config.return_value = mock_config
        config = conn._get_volume_config(connection_info, disk_info)
        get_config.assert_called_once_with(connection_info, disk_info)
        self.assertEqual(mock_config, config)

    def test_attach_invalid_volume_type(self):
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        instance = fake_instance.fake_instance_obj(
            self.context, **self.test_instance)
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.VolumeDriverNotFound,
                          conn.attach_volume, None,
                          {"driver_volume_type": "badtype"},
                          instance,
                          "/dev/sda")

    def test_attach_blockio_invalid_hypervisor(self):
        self.flags(virt_type='fake_type', group='libvirt')
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        instance = fake_instance.fake_instance_obj(
            self.context, **self.test_instance)
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.InvalidHypervisorType,
                          conn.attach_volume, None,
                          {"driver_volume_type": "fake",
                           "data": {"logical_block_size": "4096",
                                    "physical_block_size": "4096"}
                          },
                          instance,
                          "/dev/sda")

    def test_attach_blockio_invalid_version(self):
        def get_lib_version_stub():
            return (0 * 1000 * 1000) + (9 * 1000) + 8
        self.flags(virt_type='qemu', group='libvirt')
        self.create_fake_libvirt_mock()
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup
        instance = fake_instance.fake_instance_obj(
            self.context, **self.test_instance)
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(self.conn, "getLibVersion", get_lib_version_stub)
        self.assertRaises(exception.Invalid,
                          conn.attach_volume, None,
                          {"driver_volume_type": "fake",
                           "data": {"logical_block_size": "4096",
                                    "physical_block_size": "4096"}
                          },
                          instance,
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
            mock.patch.object(conn, '_connect_volume'),
            mock.patch.object(conn, '_get_volume_config',
                              return_value=mock_conf),
            mock.patch.object(conn, '_set_cache_mode')
        ) as (mock_connect_volume, mock_get_volume_config,
              mock_set_cache_mode):
            for state in (power_state.RUNNING, power_state.PAUSED):
                mock_dom.info.return_value = [state, 512, 512, 2, 1234, 5678]

                conn.attach_volume(self.context, connection_info, instance,
                                   "/dev/vdb", disk_bus=bdm['disk_bus'],
                                   device_type=bdm['device_type'])

                mock_lookup_by_name.assert_called_with(instance['name'])
                mock_get_info.assert_called_with(CONF.libvirt.virt_type, bdm)
                mock_connect_volume.assert_called_with(
                    connection_info, disk_info)
                mock_get_volume_config.assert_called_with(
                    connection_info, disk_info)
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

        with mock.patch.object(conn, '_disconnect_volume') as \
                mock_disconnect_volume:
            for state in (power_state.RUNNING, power_state.PAUSED):
                mock_dom.info.return_value = [state, 512, 512, 2, 1234, 5678]
                mock_lookup_by_name.return_value = mock_dom

                conn.detach_volume(connection_info, instance, '/dev/vdc')

                mock_lookup_by_name.assert_called_with(instance['name'])
                mock_get_disk_xml.assert_called_with(mock_dom.XMLDesc(0),
                                                     'vdc')
                mock_dom.detachDeviceFlags.assert_called_with(mock_xml, flags)
                mock_disconnect_volume.assert_called_with(
                    connection_info, 'vdc')

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_multi_nic(self, mock_flavor):
        network_info = _fake_network_info(self.stubs, 2)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        instance_ref = objects.Instance(**self.test_instance)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = conn._get_guest_xml(self.context, instance_ref,
                                  network_info, disk_info)
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
        # O_DIRECT is not supported on all Python runtimes, so on platforms
        # where it's not supported (e.g. Mac), we can still test the code-path
        # by stubbing out the value.
        if not hasattr(os, 'O_DIRECT'):
            # `mock` seems to have trouble stubbing an attr that doesn't
            # originally exist, so falling back to stubbing out the attribute
            # directly.
            os.O_DIRECT = 16384
            self.addCleanup(delattr, os, 'O_DIRECT')

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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_container(self, instance, mock_flavor):
        instance_ref = objects.Instance(**instance)

        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        self.assertEqual(conn.uri(), 'lxc:///')

        network_info = _fake_network_info(self.stubs, 1)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        xml = conn._get_guest_xml(self.context, instance_ref,
                                  network_info, disk_info)
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_disk_prefix(self, instance, prefix, mock_flavor):
        instance_ref = objects.Instance(**instance)

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

            flavor = instance_ref.get_flavor()
            flavor.extra_specs = {}
            mock_flavor.return_value = flavor
            xml = conn._get_guest_xml(self.context, instance_ref,
                                      network_info, disk_info)
            tree = etree.fromstring(xml)

            for i, (check, expected_result) in enumerate(checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s != %s failed check %d' %
                                 (check(tree), expected_result, i))

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_disk_driver(self, image_meta, mock_flavor):
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

        instance_ref = objects.Instance(**self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)

        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        xml = drv._get_guest_xml(self.context, instance_ref,
                                 network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        disks = tree.findall('./devices/disk/driver')
        for guest_disk in disks:
            self.assertEqual(guest_disk.get("cache"), "none")

        directio_supported = False

        # The O_DIRECT availability is cached on first use in
        # LibvirtDriver, hence we re-create it here
        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        xml = drv._get_guest_xml(self.context, instance_ref,
                                 network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        disks = tree.findall('./devices/disk/driver')
        for guest_disk in disks:
            self.assertEqual(guest_disk.get("cache"), "writethrough")

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_disk_bus(self, image_meta,
                                block_device_info, wantConfig,
                                mock_flavor):
        instance_ref = objects.Instance(**self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref,
                                            block_device_info,
                                            image_meta)

        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        xml = drv._get_guest_xml(self.context, instance_ref,
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

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_uuid(self, image_meta, mock_flavor):
        instance_ref = objects.Instance(**self.test_instance)
        network_info = _fake_network_info(self.stubs, 1)

        drv = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance_ref)
        flavor = instance_ref.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor
        xml = drv._get_guest_xml(self.context, instance_ref,
                                 network_info, disk_info, image_meta)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.find('./uuid').text,
                         instance_ref['uuid'])

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_get_host_sysinfo_serial_hardware",)
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _check_xml_and_uri(self, instance, mock_flavor, mock_serial,
                           expect_ramdisk=False, expect_kernel=False,
                           rescue=None, expect_xen_hvm=False, xen_only=False):
        mock_serial.return_value = "cef19ce0-0ca2-11df-855d-b19fbce37686"
        instance_ref = objects.Instance(**instance)

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

                flavor = instance_ref.get_flavor()
                flavor.extra_specs = {}
                mock_flavor.return_value = flavor
                xml = conn._get_guest_xml(self.context, instance_ref,
                                          network_info, disk_info,
                                          rescue=rescue)
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

        def fake_sleep(t):
            fake_timer.sleep(t)

        # _fake_network_info must be called before create_fake_libvirt_mock(),
        # as _fake_network_info calls importutils.import_class() and
        # create_fake_libvirt_mock() mocks importutils.import_class().
        network_info = _fake_network_info(self.stubs, 1)
        self.create_fake_libvirt_mock()
        instance_ref = objects.Instance(**self.test_instance)

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
            self.stubs.Set(greenthread,
                           'sleep',
                           fake_sleep)
            conn.ensure_filtering_rules_for_instance(instance_ref,
                                                     network_info)
        except exception.NovaException as e:
            msg = ('The firewall filter for %s does not exist' %
                   instance_ref['name'])
            c1 = (0 <= six.text_type(e).find(msg))
        self.assertTrue(c1)

        self.assertEqual(29, fake_timer.counter, "Didn't wait the expected "
                                                 "amount of time")

    def test_check_can_live_migrate_dest_all_pass_with_block_migration(self):
        instance_ref = objects.Instance(**self.test_instance)
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
                         'image_type': 'default',
                         'disk_available_mb': 409600,
                         "disk_over_commit": False,
                         "block_migration": True},
                        matchers.DictMatches(return_value))

    def test_check_can_live_migrate_dest_all_pass_no_block_migration(self):
        instance_ref = objects.Instance(**self.test_instance)
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
                         "image_type": 'default',
                         "block_migration": False,
                         "disk_over_commit": False,
                         "disk_available_mb": None},
                        matchers.DictMatches(return_value))

    def test_check_can_live_migrate_dest_incompatible_cpu_raises(self):
        instance_ref = objects.Instance(**self.test_instance)
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
        objects.Instance(**self.test_instance)
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

    def _mock_can_live_migrate_source(self, block_migration=False,
                                      is_shared_block_storage=False,
                                      is_shared_instance_path=False,
                                      disk_available_mb=1024,
                                      block_device_info=None):
        instance = objects.Instance(**self.test_instance)
        dest_check_data = {'filename': 'file',
                           'image_type': 'default',
                           'block_migration': block_migration,
                           'disk_over_commit': False,
                           'disk_available_mb': disk_available_mb}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(conn, '_is_shared_block_storage')
        conn._is_shared_block_storage(instance, dest_check_data,
                block_device_info).AndReturn(is_shared_block_storage)
        self.mox.StubOutWithMock(conn, '_check_shared_storage_test_file')
        conn._check_shared_storage_test_file('file').AndReturn(
                is_shared_instance_path)

        return (instance, dest_check_data, conn)

    def test_check_can_live_migrate_source_block_migration(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                block_migration=True)

        self.mox.StubOutWithMock(conn, "_assert_dest_node_has_enough_disk")
        conn._assert_dest_node_has_enough_disk(
            self.context, instance, dest_check_data['disk_available_mb'],
            False, None)

        self.mox.ReplayAll()
        ret = conn.check_can_live_migrate_source(self.context, instance,
                                                 dest_check_data)
        self.assertIsInstance(ret, dict)
        self.assertIn('is_shared_block_storage', ret)
        self.assertIn('is_shared_instance_path', ret)
        self.assertEqual(ret['is_shared_instance_path'],
                         ret['is_shared_storage'])

    def test_check_can_live_migrate_source_shared_block_storage(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                is_shared_block_storage=True)
        self.mox.ReplayAll()
        conn.check_can_live_migrate_source(self.context, instance,
                                           dest_check_data)

    def test_check_can_live_migrate_source_shared_instance_path(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                is_shared_instance_path=True)
        self.mox.ReplayAll()
        conn.check_can_live_migrate_source(self.context, instance,
                                           dest_check_data)

    def test_check_can_live_migrate_source_non_shared_fails(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source()
        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidSharedStorage,
                          conn.check_can_live_migrate_source, self.context,
                          instance, dest_check_data)

    def test_check_can_live_migrate_source_shared_block_migration_fails(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                block_migration=True,
                is_shared_block_storage=True)

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidLocalStorage,
                          conn.check_can_live_migrate_source,
                          self.context, instance, dest_check_data)

    def test_check_can_live_migrate_shared_path_block_migration_fails(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                block_migration=True,
                is_shared_instance_path=True)

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidLocalStorage,
                          conn.check_can_live_migrate_source,
                          self.context, instance, dest_check_data, None)

    def test_check_can_live_migrate_non_shared_non_block_migration_fails(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source()
        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidSharedStorage,
                          conn.check_can_live_migrate_source,
                          self.context, instance, dest_check_data)

    def test_check_can_live_migrate_source_with_dest_not_enough_disk(self):
        instance, dest_check_data, conn = self._mock_can_live_migrate_source(
                block_migration=True,
                disk_available_mb=0)

        self.mox.StubOutWithMock(conn, "get_instance_disk_info")
        conn.get_instance_disk_info(instance,
                                    block_device_info=None).AndReturn(
                                        '[{"virt_disk_size":2}]')

        self.mox.ReplayAll()
        self.assertRaises(exception.MigrationError,
                          conn.check_can_live_migrate_source,
                          self.context, instance, dest_check_data)

    def _is_shared_block_storage_test_create_mocks(self, disks):
        # Test data
        instance_xml = ("<domain type='kvm'><name>instance-0000000a</name>"
                        "<devices>{}</devices></domain>")
        disks_xml = ''
        for dsk in disks:
            if dsk['type'] is not 'network':
                disks_xml = ''.join([disks_xml,
                                "<disk type='{type}'>"
                                "<driver name='qemu' type='{driver}'/>"
                                "<source {source}='{source_path}'/>"
                                "<target dev='{target_dev}' bus='virtio'/>"
                                "</disk>".format(**dsk)])
            else:
                disks_xml = ''.join([disks_xml,
                                "<disk type='{type}'>"
                                "<driver name='qemu' type='{driver}'/>"
                                "<source protocol='{source_proto}'"
                                "name='{source_image}' >"
                                "<host name='hostname' port='7000'/>"
                                "<config file='/path/to/file'/>"
                                "</source>"
                                "<target dev='{target_dev}'"
                                "bus='ide'/>".format(**dsk)])

        # Preparing mocks
        mock_virDomain = mock.Mock(libvirt.virDomain)
        mock_virDomain.XMLDesc = mock.Mock()
        mock_virDomain.XMLDesc.return_value = (instance_xml.format(disks_xml))

        mock_lookup = mock.Mock()

        def mock_lookup_side_effect(name):
            return mock_virDomain
        mock_lookup.side_effect = mock_lookup_side_effect

        mock_getsize = mock.Mock()
        mock_getsize.return_value = "10737418240"

        return (mock_getsize, mock_lookup)

    def test_is_shared_block_storage_rbd(self):
        self.flags(images_type='rbd', group='libvirt')
        bdi = {'block_device_mapping': []}
        instance = objects.Instance(**self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        mock_get_instance_disk_info = mock.Mock()
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.assertTrue(conn._is_shared_block_storage(instance,
                                  {'image_type': 'rbd'},
                                  block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    def test_is_shared_block_storage_lvm(self):
        self.flags(images_type='lvm', group='libvirt')
        bdi = {'block_device_mapping': []}
        instance = objects.Instance(**self.test_instance)
        mock_get_instance_disk_info = mock.Mock()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.assertFalse(conn._is_shared_block_storage(
                                    instance, {'image_type': 'lvm'},
                                    block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    def test_is_shared_block_storage_qcow2(self):
        self.flags(images_type='qcow2', group='libvirt')
        bdi = {'block_device_mapping': []}
        instance = objects.Instance(**self.test_instance)
        mock_get_instance_disk_info = mock.Mock()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.assertFalse(conn._is_shared_block_storage(
                                    instance, {'image_type': 'qcow2'},
                                    block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    def test_is_shared_block_storage_rbd_only_source(self):
        self.flags(images_type='rbd', group='libvirt')
        bdi = {'block_device_mapping': []}
        instance = objects.Instance(**self.test_instance)
        mock_get_instance_disk_info = mock.Mock()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.assertFalse(conn._is_shared_block_storage(
                                  instance, {'is_shared_instance_path': False},
                                  block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    def test_is_shared_block_storage_rbd_only_dest(self):
        bdi = {'block_device_mapping': []}
        instance = objects.Instance(**self.test_instance)
        mock_get_instance_disk_info = mock.Mock()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            self.assertFalse(conn._is_shared_block_storage(
                                    instance, {'image_type': 'rbd',
                                    'is_shared_instance_path': False},
                                    block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    def test_is_shared_block_storage_volume_backed(self):
        disks = [{'type': 'block',
                 'driver': 'raw',
                 'source': 'dev',
                 'source_path': '/dev/disk',
                 'target_dev': 'vda'}]
        bdi = {'block_device_mapping': [
                  {'connection_info': 'info', 'mount_device': '/dev/vda'}]}
        instance = objects.Instance(**self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        (mock_getsize, mock_lookup) =\
            self._is_shared_block_storage_test_create_mocks(disks)
        with mock.patch.object(conn, '_lookup_by_name', mock_lookup):
            self.assertTrue(conn._is_shared_block_storage(instance,
                                  {'is_volume_backed': True,
                                   'is_shared_instance_path': False},
                                  block_device_info = bdi))
        mock_lookup.assert_called_once_with(instance['name'])

    def test_is_shared_block_storage_volume_backed_with_disk(self):
        disks = [{'type': 'block',
                 'driver': 'raw',
                 'source': 'dev',
                 'source_path': '/dev/disk',
                 'target_dev': 'vda'},
                {'type': 'file',
                 'driver': 'raw',
                 'source': 'file',
                 'source_path': '/instance/disk.local',
                 'target_dev': 'vdb'}]
        bdi = {'block_device_mapping': [
                  {'connection_info': 'info', 'mount_device': '/dev/vda'}]}
        instance = objects.Instance(**self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        (mock_getsize, mock_lookup) =\
            self._is_shared_block_storage_test_create_mocks(disks)
        with contextlib.nested(
                mock.patch.object(os.path, 'getsize', mock_getsize),
                mock.patch.object(conn, '_lookup_by_name', mock_lookup)):
            self.assertFalse(conn._is_shared_block_storage(
                                    instance,
                                    {'is_volume_backed': True,
                                    'is_shared_instance_path': False},
                                    block_device_info = bdi))
        mock_getsize.assert_called_once_with('/instance/disk.local')
        mock_lookup.assert_called_once_with(instance['name'])

    def test_is_shared_block_storage_nfs(self):
        bdi = {'block_device_mapping': []}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        mock_image_backend = mock.MagicMock()
        conn.image_backend = mock_image_backend
        mock_backend = mock.MagicMock()
        mock_image_backend.backend.return_value = mock_backend
        mock_backend.is_file_in_instance_path.return_value = True
        mock_get_instance_disk_info = mock.Mock()
        with mock.patch.object(conn, 'get_instance_disk_info',
                               mock_get_instance_disk_info):
            self.assertTrue(conn._is_shared_block_storage('instance',
                                    {'is_shared_instance_path': True},
                                    block_device_info=bdi))
        self.assertEqual(0, mock_get_instance_disk_info.call_count)

    @mock.patch.object(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE', 8675, create=True)
    def test_live_migration_changes_listen_addresses(self):
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = dict(self.test_instance)
        instance_dict.update({'host': 'fake',
                              'power_state': power_state.RUNNING,
                              'vm_state': vm_states.ACTIVE})
        instance_ref = objects.Instance(**instance_dict)

        xml_tmpl = ("<domain type='kvm'>"
                    "<devices>"
                    "<graphics type='vnc' listen='{vnc}'>"
                    "<listen address='{vnc}'/>"
                    "</graphics>"
                    "<graphics type='spice' listen='{spice}'>"
                    "<listen address='{spice}'/>"
                    "</graphics>"
                    "</devices>"
                    "</domain>")

        initial_xml = xml_tmpl.format(vnc='1.2.3.4',
                                      spice='5.6.7.8')

        target_xml = xml_tmpl.format(vnc='10.0.0.1',
                                     spice='10.0.0.2')
        target_xml = etree.tostring(etree.fromstring(target_xml))

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI2")
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        vdmock.XMLDesc(libvirt.VIR_DOMAIN_XML_MIGRATABLE).AndReturn(
                initial_xml)
        vdmock.migrateToURI2(CONF.libvirt.live_migration_uri % 'dest',
                             None,
                             target_xml,
                             mox.IgnoreArg(),
                             None,
                             _bandwidth).AndRaise(libvirt.libvirtError("ERR"))

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        # start test
        migrate_data = {'pre_live_migration_result':
                {'graphics_listen_addrs':
                    {'vnc': '10.0.0.1', 'spice': '10.0.0.2'}}}
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration,
                      migrate_data=migrate_data)

    @mock.patch.object(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE', None, create=True)
    def test_live_migration_uses_migrateToURI_without_migratable_flag(self):
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = dict(self.test_instance)
        instance_dict.update({'host': 'fake',
                              'power_state': power_state.RUNNING,
                              'vm_state': vm_states.ACTIVE})
        instance_ref = objects.Instance(**instance_dict)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI")
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        vdmock.migrateToURI(CONF.libvirt.live_migration_uri % 'dest',
                            mox.IgnoreArg(),
                            None,
                            _bandwidth).AndRaise(libvirt.libvirtError("ERR"))

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        # start test
        migrate_data = {'pre_live_migration_result':
                {'graphics_listen_addrs':
                    {'vnc': '0.0.0.0', 'spice': '0.0.0.0'}}}
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration,
                      migrate_data=migrate_data)

    def test_live_migration_uses_migrateToURI_without_dest_listen_addrs(self):
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = dict(self.test_instance)
        instance_dict.update({'host': 'fake',
                              'power_state': power_state.RUNNING,
                              'vm_state': vm_states.ACTIVE})
        instance_ref = objects.Instance(**instance_dict)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI")
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        vdmock.migrateToURI(CONF.libvirt.live_migration_uri % 'dest',
                            mox.IgnoreArg(),
                            None,
                            _bandwidth).AndRaise(libvirt.libvirtError("ERR"))

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        # start test
        migrate_data = {}
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration,
                      migrate_data=migrate_data)

    @mock.patch.object(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE', None, create=True)
    def test_live_migration_fails_without_migratable_flag_or_0_addr(self):
        self.flags(vnc_enabled=True, vncserver_listen='1.2.3.4')
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = dict(self.test_instance)
        instance_dict.update({'host': 'fake',
                              'power_state': power_state.RUNNING,
                              'vm_state': vm_states.ACTIVE})
        instance_ref = objects.Instance(**instance_dict)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI")

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        # start test
        migrate_data = {'pre_live_migration_result':
                {'graphics_listen_addrs':
                    {'vnc': '1.2.3.4', 'spice': '1.2.3.4'}}}
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(exception.MigrationError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration,
                      migrate_data=migrate_data)

    def test_live_migration_raises_exception(self):
        # Confirms recover method is called when exceptions are raised.
        # Preparing data
        self.compute = importutils.import_object(CONF.compute_manager)
        instance_dict = dict(self.test_instance)
        instance_dict.update({'host': 'fake',
                              'power_state': power_state.RUNNING,
                              'vm_state': vm_states.ACTIVE})
        instance_ref = objects.Instance(**instance_dict)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI2")
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        if getattr(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE', None) is None:
            vdmock.migrateToURI(CONF.libvirt.live_migration_uri % 'dest',
                                mox.IgnoreArg(),
                                None,
                                _bandwidth).AndRaise(
                                        libvirt.libvirtError('ERR'))
        else:
            vdmock.XMLDesc(libvirt.VIR_DOMAIN_XML_MIGRATABLE).AndReturn(
                    FakeVirtDomain().XMLDesc(0))
            vdmock.migrateToURI2(CONF.libvirt.live_migration_uri % 'dest',
                                 None,
                                 mox.IgnoreArg(),
                                 mox.IgnoreArg(),
                                 None,
                                 _bandwidth).AndRaise(
                                         libvirt.libvirtError('ERR'))

        def fake_lookup(instance_name):
            if instance_name == instance_ref['name']:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
        self.mox.StubOutWithMock(self.compute, "_rollback_live_migration")
        self.compute._rollback_live_migration(self.context, instance_ref,
                                              'dest', False)

        # start test
        migrate_data = {'pre_live_migration_result':
                {'graphics_listen_addrs':
                    {'vnc': '127.0.0.1', 'spice': '127.0.0.1'}}}
        self.mox.ReplayAll()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute._rollback_live_migration,
                      migrate_data=migrate_data)

        self.assertEqual(vm_states.ACTIVE, instance_ref.vm_state)
        self.assertEqual(power_state.RUNNING, instance_ref.power_state)

    @mock.patch.object(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE', 8675, create=True)
    def test_live_migration_raises_unsupported_config_exception(self):
        # Tests that when migrateToURI2 fails with VIR_ERR_CONFIG_UNSUPPORTED,
        # migrateToURI is used instead.

        # Preparing data
        instance_ref = fake_instance.fake_instance_obj(
            self.context, **self.test_instance)

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, 'migrateToURI2')
        self.mox.StubOutWithMock(vdmock, 'migrateToURI')
        _bandwidth = CONF.libvirt.live_migration_bandwidth
        vdmock.XMLDesc(libvirt.VIR_DOMAIN_XML_MIGRATABLE).AndReturn(
                FakeVirtDomain().XMLDesc(0))
        unsupported_config_error = libvirt.libvirtError('ERR')
        unsupported_config_error.err = (libvirt.VIR_ERR_CONFIG_UNSUPPORTED,)
        # This is the first error we hit but since the error code is
        # VIR_ERR_CONFIG_UNSUPPORTED we'll try migrateToURI.
        vdmock.migrateToURI2(CONF.libvirt.live_migration_uri % 'dest', None,
                             mox.IgnoreArg(), mox.IgnoreArg(), None,
                             _bandwidth).AndRaise(unsupported_config_error)
        # This is the second and final error that will actually kill the run,
        # we use TestingException to make sure it's not the same libvirtError
        # above.
        vdmock.migrateToURI(CONF.libvirt.live_migration_uri % 'dest',
                            mox.IgnoreArg(), None,
                            _bandwidth).AndRaise(test.TestingException('oops'))

        def fake_lookup(instance_name):
            if instance_name == instance_ref.name:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        def fake_recover_method(context, instance, dest, block_migration):
            pass

        graphics_listen_addrs = {'vnc': '0.0.0.0', 'spice': '127.0.0.1'}
        migrate_data = {'pre_live_migration_result':
                {'graphics_listen_addrs': graphics_listen_addrs}}
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.mox.StubOutWithMock(
            conn, '_check_graphics_addresses_can_live_migrate')
        conn._check_graphics_addresses_can_live_migrate(graphics_listen_addrs)
        self.mox.ReplayAll()

        # start test
        self.assertRaises(test.TestingException, conn._live_migration,
                          self.context, instance_ref, 'dest', post_method=None,
                          recover_method=fake_recover_method,
                          migrate_data=migrate_data)

    def test_rollback_live_migration_at_destination(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(conn, "destroy") as mock_destroy:
            conn.rollback_live_migration_at_destination("context",
                    "instance", [], None, True, None)
            mock_destroy.assert_called_once_with("context",
                    "instance", [], None, True, None)

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
        self.mox.StubOutWithMock(conn, "_connect_volume")
        for v in vol['block_device_mapping']:
            disk_info = {
                'bus': "scsi",
                'dev': v['mount_device'].rpartition("/")[2],
                'type': "disk"
                }
            conn._connect_volume(v['connection_info'],
                                 disk_info)
        self.mox.StubOutWithMock(conn, 'plug_vifs')
        conn.plug_vifs(mox.IsA(inst_ref), nw_info)

        self.mox.ReplayAll()
        result = conn.pre_live_migration(c, inst_ref, vol, nw_info, None)

        target_res = {'graphics_listen_addrs': {'spice': '127.0.0.1',
                                                'vnc': '127.0.0.1'}}
        self.assertEqual(result, target_res)

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

        self.assertRaises(exception.NoLiveMigrationForConfigDriveInLibVirt,
                          conn.pre_live_migration, c, inst_ref, vol, None,
                          None, {'is_shared_instance_path': False,
                                 'is_shared_block_storage': False})

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
            inst_ref = objects.Instance(**self.test_instance)
            c = context.get_admin_context()
            nw_info = FakeNetworkInfo()
            # Creating mocks
            self.mox.StubOutWithMock(conn, "_connect_volume")
            for v in vol['block_device_mapping']:
                disk_info = {
                    'bus': "scsi",
                    'dev': v['mount_device'].rpartition("/")[2],
                    'type': "disk"
                    }
                conn._connect_volume(v['connection_info'],
                                     disk_info)
            self.mox.StubOutWithMock(conn, 'plug_vifs')
            conn.plug_vifs(mox.IsA(inst_ref), nw_info)
            self.mox.ReplayAll()
            migrate_data = {'is_shared_instance_path': False,
                            'is_volume_backed': True,
                            'block_migration': False,
                            'instance_relative_path': inst_ref['name']
                            }
            ret = conn.pre_live_migration(c, inst_ref, vol, nw_info, None,
                                          migrate_data)
            target_ret = {'graphics_listen_addrs': {'spice': '127.0.0.1',
                                                    'vnc': '127.0.0.1'}}
            self.assertEqual(ret, target_ret)
            self.assertTrue(os.path.exists('%s/%s/' % (tmpdir,
                                                       inst_ref['name'])))

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

    def test_pre_live_migration_image_not_created_with_shared_storage(self):
        migrate_data_set = [{'is_shared_block_storage': False,
                             'block_migration': False},
                            {'is_shared_block_storage': True,
                             'block_migration': False},
                            {'is_shared_block_storage': False,
                             'block_migration': True}]

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(**self.test_instance)
        # creating mocks
        with contextlib.nested(
            mock.patch.object(conn,
                              '_create_images_and_backing'),
            mock.patch.object(conn,
                              'ensure_filtering_rules_for_instance'),
            mock.patch.object(conn, 'plug_vifs'),
        ) as (
            create_image_mock,
            rules_mock,
            plug_mock,
        ):
            for migrate_data in migrate_data_set:
                res = conn.pre_live_migration(self.context, instance,
                                        block_device_info=None,
                                        network_info=[], disk_info={},
                                        migrate_data=migrate_data)
                self.assertFalse(create_image_mock.called)
                self.assertIsInstance(res, dict)

    def test_pre_live_migration_with_not_shared_instance_path(self):
        migrate_data = {'is_shared_block_storage': False,
                        'is_shared_instance_path': False}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(**self.test_instance)

        def check_instance_dir(context, instance,
                               instance_dir, disk_info):
            self.assertTrue(instance_dir)
        # creating mocks
        with contextlib.nested(
            mock.patch.object(conn,
                              '_create_images_and_backing',
                              side_effect=check_instance_dir),
            mock.patch.object(conn,
                              'ensure_filtering_rules_for_instance'),
            mock.patch.object(conn, 'plug_vifs'),
        ) as (
            create_image_mock,
            rules_mock,
            plug_mock,
        ):
            res = conn.pre_live_migration(self.context, instance,
                                    block_device_info=None,
                                    network_info=[], disk_info={},
                                    migrate_data=migrate_data)
            self.assertTrue(create_image_mock.called)
            self.assertIsInstance(res, dict)

    def test_get_instance_disk_info_works_correctly(self):
        # Test data
        instance = objects.Instance(**self.test_instance)
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
            if instance_name == instance.name:
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
        info = conn.get_instance_disk_info(instance)
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
            mock.patch.object(conn, '_disconnect_volume')
        ) as (block_device_info_get_mapping, _disconnect_volume):
            conn.post_live_migration(cntx, inst_ref, vol)

            block_device_info_get_mapping.assert_has_calls([
                mock.call(vol)])
            _disconnect_volume.assert_has_calls([
                mock.call(v['connection_info'],
                          v['mount_device'].rpartition("/")[2])
                for v in vol['block_device_mapping']])

    def test_get_instance_disk_info_excludes_volumes(self):
        # Test data
        instance = objects.Instance(**self.test_instance)
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
            if instance_name == instance.name:
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
        info = conn.get_instance_disk_info(instance,
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

    def test_spawn_with_network_info(self):
        # Preparing mocks
        def fake_none(*args, **kwargs):
            return

        def fake_getLibVersion():
            return 9011

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
        instance = objects.Instance(**instance_ref)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}

        # Mock out the get_info method of the LibvirtDriver so that the polling
        # in the spawn method of the LibvirtDriver returns immediately
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, 'get_info')
        libvirt_driver.LibvirtDriver.get_info(instance
            ).AndReturn(hardware.InstanceInfo(state=power_state.RUNNING))

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
                        network_info=network_info, flavor=flavor)

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
            return hardware.InstanceInfo(state=power_state.RUNNING)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        instance = objects.Instance(**instance_ref)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_get_guest_xml', fake_none)
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
            return hardware.InstanceInfo(state=power_state.RUNNING)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_get_guest_xml', fake_none)

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
        instance = objects.Instance(**instance_ref)

        conn.spawn(self.context, instance, None, [], None,
                   block_device_info=block_device_info)
        self.assertFalse(self.cache_called_for_disk)

        # Booted from volume but with placeholder image
        instance_ref = self.test_instance
        instance_ref['image_ref'] = 'my_fake_image'
        instance_ref['root_device_name'] = '/dev/vda'
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance = objects.Instance(**instance_ref)

        conn.spawn(self.context, instance, None, [], None,
                   block_device_info=block_device_info)
        self.assertFalse(self.cache_called_for_disk)

        # Booted from an image
        instance_ref['image_ref'] = 'my_fake_image'
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance = objects.Instance(**instance_ref)
        conn.spawn(self.context, instance, None, [], None)
        self.assertTrue(self.cache_called_for_disk)

    def test_start_lxc_from_volume(self):
        self.flags(virt_type="lxc",
                   group='libvirt')

        def check_setup_container(path, container_dir=None, use_cow=False):
            self.assertEqual(path, '/dev/path/to/dev')
            self.assertTrue(use_cow)
            return '/dev/nbd1'

        bdm = {
                  'guest_format': None,
                  'boot_index': 0,
                  'mount_device': '/dev/sda',
                  'connection_info': {
                      'driver_volume_type': 'iscsi',
                      'serial': 'afc1',
                      'data': {
                          'access_mode': 'rw',
                          'device_path': '/dev/path/to/dev',
                          'target_discovered': False,
                          'encrypted': False,
                          'qos_specs': None,
                          'target_iqn': 'iqn: volume-afc1',
                          'target_portal': 'ip: 3260',
                          'volume_id': 'afc1',
                          'target_lun': 1,
                          'auth_password': 'uj',
                          'auth_username': '47',
                          'auth_method': 'CHAP'
                      }
                  },
                  'disk_bus': 'scsi',
                  'device_type': 'disk',
                  'delete_on_termination': False
              }

        def _get(key, opt=None):
            return bdm.get(key, opt)

        def getitem(key):
            return bdm[key]

        def setitem(key, val):
            bdm[key] = val

        bdm_mock = mock.MagicMock()
        bdm_mock.__getitem__.side_effect = getitem
        bdm_mock.__setitem__.side_effect = setitem
        bdm_mock.get = _get

        disk_mock = mock.MagicMock()
        disk_mock.source_path = '/dev/path/to/dev'

        block_device_info = {'block_device_mapping': [bdm_mock],
                             'root_device_name': '/dev/sda'}

        # Volume-backed instance created without image
        instance_ref = self.test_instance
        instance_ref['image_ref'] = ''
        instance_ref['root_device_name'] = '/dev/sda'
        instance_ref['ephemeral_gb'] = 0
        instance_ref['uuid'] = uuidutils.generate_uuid()
        instance_ref['system_metadata']['image_disk_format'] = 'qcow2'
        inst_obj = objects.Instance(**instance_ref)

        flavor = inst_obj.get_flavor()
        flavor.extra_specs = {}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
            mock.patch.object(conn, '_create_images_and_backing'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver, 'prepare_instance_filter'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter'),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn, '_connect_volume'),
            mock.patch.object(conn, '_get_volume_config',
                                     return_value=disk_mock),
            mock.patch.object(conn, 'get_info',
                              return_value=hardware.InstanceInfo(
                              state=power_state.RUNNING)),
            mock.patch('nova.virt.disk.api.setup_container',
                       side_effect=check_setup_container),
            mock.patch('nova.virt.disk.api.teardown_container'),
            mock.patch.object(objects.Instance, 'save'),
            mock.patch.object(objects.Flavor, 'get_by_id',
                              return_value=flavor)):

            conn.spawn(self.context, inst_obj, None, [], None,
                       network_info=[],
                       block_device_info=block_device_info)
            self.assertEqual('/dev/nbd1',
                             inst_obj.system_metadata.get(
                             'rootfs_device_name'))

    def test_spawn_with_pci_devices(self):
        def fake_none(*args, **kwargs):
            return None

        def fake_get_info(instance):
            return hardware.InstanceInfo(state=power_state.RUNNING)

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
        self.stubs.Set(conn, '_get_guest_xml', fake_none)
        self.stubs.Set(conn, '_create_image', fake_none)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        conn._conn.nodeDeviceLookupByName = \
                    fake_node_device_lookup_by_name

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 'my_fake_image'
        instance = objects.Instance(**instance_ref)
        instance['pci_devices'] = objects.PciDeviceList(
            objects=[objects.PciDevice(address='0000:00:00.0')])

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
            return hardware.InstanceInfo(state=power_state.RUNNING)

        # Stop 'libvirt_driver._create_image' touching filesystem
        self.stubs.Set(nova.virt.libvirt.imagebackend.Backend, "image",
                       fake_image)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        instance = objects.Instance(**instance_ref)
        instance['os_type'] = os_type

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_get_guest_xml', fake_none)
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
        conn._create_image(context, instance, disk_info['mapping'])
        conn._get_guest_xml(self.context, instance, None,
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
            return hardware.InstanceInfo(state=power_state.RUNNING)

        # Stop 'libvirt_driver._create_image' touching filesystem
        self.stubs.Set(nova.virt.libvirt.imagebackend.Backend, "image",
                       fake_image)

        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        # Turn on some swap to exercise that codepath in _create_image
        instance_ref['system_metadata']['instance_type_swap'] = 500
        instance = objects.Instance(**instance_ref)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_get_guest_xml', fake_none)
        self.stubs.Set(conn, '_create_domain_and_network', fake_none)
        self.stubs.Set(conn, 'get_info', fake_get_info)

        image_meta = {'id': instance['image_ref']}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            None,
                                            image_meta)
        conn._create_image(context, instance, disk_info['mapping'])
        conn._get_guest_xml(self.context, instance, None,
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

    @mock.patch.object(utils, 'execute')
    def test_create_ephemeral_specified_fs(self, mock_exec):
        self.flags(default_ephemeral_format='ext3')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn._create_ephemeral('/dev/something', 20, 'myVol', 'linux',
                               is_block_dev=True, max_size=20,
                               specified_fs='ext4')
        mock_exec.assert_called_once_with('mkfs', '-t', 'ext4', '-F', '-L',
                                          'myVol', '/dev/something',
                                          run_as_root=True)

    def test_create_ephemeral_specified_fs_not_valid(self):
        CONF.set_override('default_ephemeral_format', 'ext4')
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'virtio',
                       'device_name': '/dev/vdb',
                       'guest_format': 'dummy',
                       'size': 1}]
        block_device_info = {
                'ephemerals': ephemerals}
        instance_ref = self.test_instance
        instance_ref['image_ref'] = 1
        instance = objects.Instance(**instance_ref)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        image_meta = {'id': instance['image_ref']}
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            None,
                                            image_meta)
        disk_info['mapping'].pop('disk.local')

        with contextlib.nested(
            mock.patch.object(utils, 'execute'),
            mock.patch.object(conn, 'get_info'),
            mock.patch.object(conn, '_create_domain_and_network')):
            self.assertRaises(exception.InvalidBDMFormat, conn._create_image,
                              context, instance, disk_info['mapping'],
                              block_device_info=block_device_info)

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
            instance = objects.Instance(**instance_ref)

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
                with mock.patch('os.path.exists', return_value=True):
                    output = conn.get_console_output(self.context, instance)
            finally:
                libvirt_driver.MAX_CONSOLE_BYTES = prev_max

            self.assertEqual('67890', output)

    def test_get_console_output_file_missing(self):
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)

            instance_ref = self.test_instance
            instance_ref['image_ref'] = 123456
            instance = objects.Instance(**instance_ref)

            console_log = os.path.join(tmpdir, instance['name'],
                                       'non-existent.log')
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

            with mock.patch('os.path.exists', return_value=False):
                output = conn.get_console_output(self.context, instance)

            self.assertEqual('', output)

    def test_get_console_output_pty(self):
        fake_libvirt_utils.files['pty'] = '01234567890'

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)

            instance_ref = self.test_instance
            instance_ref['image_ref'] = 123456
            instance = objects.Instance(**instance_ref)

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

    def test_conn_event_handler(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = False
        with contextlib.nested(
            mock.patch.object(conn._host, "_connect",
                              side_effect=fakelibvirt.make_libvirtError(
                                  libvirt.libvirtError,
                                  "Failed to connect to host",
                                  error_code=libvirt.VIR_ERR_INTERNAL_ERROR)),
            mock.patch.object(conn._host, "_init_events",
                              return_value=None),
            mock.patch.object(objects.Service, "get_by_compute_host",
                              return_value=service_mock)):

            # verify that the driver registers for the close callback
            # and re-connects after receiving the callback
            self.assertRaises(exception.HypervisorUnavailable,
                              conn.init_host,
                              "wibble")
            self.assertTrue(service_mock.disabled)

    def test_command_with_broken_connection(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = False
        with contextlib.nested(
            mock.patch.object(conn._host, "_connect",
                              side_effect=fakelibvirt.make_libvirtError(
                                  libvirt.libvirtError,
                                  "Failed to connect to host",
                                  error_code=libvirt.VIR_ERR_INTERNAL_ERROR)),
            mock.patch.object(conn._host, "_init_events",
                              return_value=None),
            mock.patch.object(host.Host, "has_min_version",
                              return_value=True),
            mock.patch.object(conn, "_do_quality_warnings",
                              return_value=None),
            mock.patch.object(objects.Service, "get_by_compute_host",
                              return_value=service_mock)):

            conn.init_host("wibble")
            self.assertRaises(exception.HypervisorUnavailable,
                              conn.get_num_instances)
            self.assertTrue(service_mock.disabled)

    def test_service_resume_after_broken_connection(self):
        self.mox.UnsetStubs()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        service_mock = mock.MagicMock()
        service_mock.disabled.return_value = True
        with contextlib.nested(
            mock.patch.object(conn._host, "_connect",
                              return_value=mock.MagicMock()),
            mock.patch.object(conn._host, "_init_events",
                              return_value=None),
            mock.patch.object(host.Host, "has_min_version",
                              return_value=True),
            mock.patch.object(conn, "_do_quality_warnings",
                              return_value=None),
            mock.patch.object(objects.Service, "get_by_compute_host",
                              return_value=service_mock)):

            conn.init_host("wibble")
            conn.get_num_instances()
            self.assertTrue(not service_mock.disabled and
                            service_mock.disabled_reason is 'None')

    def test_immediate_delete(self):
        def fake_lookup_by_name(instance_name):
            raise exception.InstanceNotFound(instance_id=instance_name)

        def fake_delete_instance_files(instance):
            pass

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)

        instance = objects.Instance(**self.test_instance)
        conn.destroy(self.context, instance, {})

    def _test_destroy_removes_disk(self, volume_fail=False):
        instance = {"name": "instancename", "id": "42",
                    "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64",
                    "cleaned": 0, 'info_cache': None, 'security_groups': []}
        vol = {'block_device_mapping': [
              {'connection_info': 'dummy', 'mount_device': '/dev/sdb'}]}

        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 '_undefine_domain')
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
                                 "_disconnect_volume")
        if volume_fail:
            libvirt_driver.LibvirtDriver._disconnect_volume(
                        mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).\
                                     AndRaise(exception.VolumeNotFound('vol'))
        else:
            libvirt_driver.LibvirtDriver._disconnect_volume(
                        mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver,
                                 'delete_instance_files')
        (libvirt_driver.LibvirtDriver.delete_instance_files(mox.IgnoreArg()).
         AndReturn(True))
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
        self.stubs.Set(objects.Instance, 'fields',
                       {'id': int, 'uuid': str, 'cleaned': int})
        self.stubs.Set(objects.Instance, 'obj_load_attr',
                       fake_obj_load_attr)
        self.stubs.Set(objects.Instance, 'save', fake_save)

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

    @mock.patch.object(libvirt_driver.LibvirtDriver, 'cleanup')
    @mock.patch.object(libvirt_driver.LibvirtDriver, '_teardown_container')
    @mock.patch.object(libvirt_driver.LibvirtDriver, '_lookup_by_name')
    def test_destroy_lxc_calls_teardown_container(self, mock_look_up,
                                                  mock_teardown_container,
                                                  mock_cleanup):
        self.flags(virt_type='lxc', group='libvirt')
        fake_domain = FakeVirtDomain()

        def destroy_side_effect(*args, **kwargs):
            fake_domain._info[0] = power_state.SHUTDOWN

        with mock.patch.object(fake_domain, 'destroy',
               side_effect=destroy_side_effect) as mock_domain_destroy:
            mock_look_up.return_value = fake_domain
            instance = fake_instance.fake_instance_obj(self.context)

            conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
            network_info = []
            conn.destroy(self.context, instance, network_info, None, False)

            mock_look_up.assert_has_calls([mock.call(instance.name),
                                           mock.call(instance.name)])
            mock_domain_destroy.assert_called_once_with()
            mock_teardown_container.assert_called_once_with(instance)
            mock_cleanup.assert_called_once_with(self.context, instance,
                                                 network_info, None, False,
                                                 None)

    @mock.patch.object(libvirt_driver.LibvirtDriver, 'cleanup')
    @mock.patch.object(libvirt_driver.LibvirtDriver, '_teardown_container')
    @mock.patch.object(libvirt_driver.LibvirtDriver, '_lookup_by_name')
    def test_destroy_lxc_calls_teardown_container_when_no_domain(self,
            mock_look_up, mock_teardown_container, mock_cleanup):
        self.flags(virt_type='lxc', group='libvirt')
        instance = fake_instance.fake_instance_obj(self.context)
        inf_exception = exception.InstanceNotFound(instance_id=instance.name)
        mock_look_up.side_effect = inf_exception

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        network_info = []
        conn.destroy(self.context, instance, network_info, None, False)

        mock_look_up.assert_has_calls([mock.call(instance.name),
                                       mock.call(instance.name)])
        mock_teardown_container.assert_called_once_with(instance)
        mock_cleanup.assert_called_once_with(self.context, instance,
                                             network_info, None, False,
                                             None)

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
        instance = objects.Instance(**self.test_instance)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_create_domain', fake_create_domain)
        self.stubs.Set(loopingcall, 'FixedIntervalLoopingCall',
                       lambda *a, **k: FakeLoopingCall())
        self.stubs.Set(pci_manager, 'get_instance_pci_devs', lambda *a: [])
        conn.reboot(None, instance, [], 'SOFT')
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
        instance = objects.Instance(**self.test_instance)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(greenthread, 'sleep', fake_sleep)
        self.stubs.Set(conn, '_hard_reboot', fake_hard_reboot)
        self.stubs.Set(loopingcall, 'FixedIntervalLoopingCall',
                       lambda *a, **k: FakeLoopingCall())
        self.stubs.Set(pci_manager, 'get_instance_pci_devs', lambda *a: [])
        conn.reboot(None, instance, [], 'SOFT')
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
        instance = objects.Instance(**self.test_instance)
        network_info = []

        self.mox.StubOutWithMock(conn, '_lookup_by_name')
        conn._lookup_by_name(instance['name']).AndReturn(mock_domain)
        self.mox.StubOutWithMock(conn, '_hard_reboot')
        conn._hard_reboot(context, instance, network_info, None)

        self.mox.ReplayAll()

        conn.reboot(context, instance, network_info, 'SOFT')

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
        instance_details = {"name": "instancename", "id": 1,
                            "uuid": "875a8070-d0b9-4949-8b31-104d125c9a64"}
        instance = fake_instance.fake_instance_obj(
            self.context, **instance_details)
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
        instance_details = {'name': 'test'}
        instance = fake_instance.fake_instance_obj(
            self.context, **instance_details)

        def fake_lookup_by_name(instance_name):
            raise exception.InstanceNotFound(instance_id='fake')

        def fake_hard_reboot(*args):
            called['count'] += 1

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_hard_reboot', fake_hard_reboot)
        conn.resume_state_on_host_boot(self.context, instance, network_info=[],
                                       block_device_info=None)

        self.assertEqual(called['count'], 1)

    def test_hard_reboot(self):
        called = {'count': 0}
        self.context.auth_token = True  # any non-None value will suffice
        instance = objects.Instance(**self.test_instance)
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
        self.mox.StubOutWithMock(conn, '_get_instance_disk_info')
        self.mox.StubOutWithMock(conn, '_get_guest_xml')
        self.mox.StubOutWithMock(conn, '_create_images_and_backing')
        self.mox.StubOutWithMock(conn, '_create_domain_and_network')

        def fake_get_info(instance_name):
            called['count'] += 1
            if called['count'] == 1:
                state = power_state.SHUTDOWN
            else:
                state = power_state.RUNNING
            return hardware.InstanceInfo(state=state)

        self.stubs.Set(conn, 'get_info', fake_get_info)

        conn._destroy(instance)
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance, block_device_info)

        system_meta = utils.instance_sys_meta(instance)
        image_meta = utils.get_image_from_system_metadata(system_meta)

        conn._get_guest_xml(self.context, instance, network_info, disk_info,
                            image_meta=image_meta,
                            block_device_info=block_device_info,
                            write_to_disk=True).AndReturn(dummyxml)
        disk_info_json = '[{"virt_disk_size": 2}]'
        conn._get_instance_disk_info(instance["name"], dummyxml,
                            block_device_info).AndReturn(disk_info_json)
        conn._create_images_and_backing(self.context, instance,
                                libvirt_utils.get_instance_path(instance),
                                disk_info_json)
        conn._create_domain_and_network(self.context, dummyxml, instance,
                                        network_info, disk_info,
                                        block_device_info=block_device_info,
                                        reboot=True, vifs_already_plugged=True)
        self.mox.ReplayAll()

        conn._hard_reboot(self.context, instance, network_info,
                          block_device_info)

    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
    @mock.patch('nova.openstack.common.loopingcall.FixedIntervalLoopingCall')
    @mock.patch('nova.pci.manager.get_instance_pci_devs')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._prepare_pci_devices_for_use')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_domain_and_network')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_images_and_backing')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._get_instance_disk_info')
    @mock.patch('nova.virt.libvirt.utils.write_to_file')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._get_guest_config')
    @mock.patch('nova.virt.libvirt.blockinfo.get_disk_info')
    @mock.patch('nova.virt.libvirt.LibvirtDriver._destroy')
    def test_hard_reboot_does_not_call_glance_show(self,
            mock_destroy, mock_get_disk_info, mock_get_guest_config,
            mock_get_instance_path, mock_write_to_file,
            mock_get_instance_disk_info, mock_create_images_and_backing,
            mock_create_domand_and_network, mock_prepare_pci_devices_for_use,
            mock_get_instance_pci_devs, mock_looping_call, mock_ensure_tree):
        """For a hard reboot, we shouldn't need an additional call to glance
        to get the image metadata.

        This is important for automatically spinning up instances on a
        host-reboot, since we won't have a user request context that'll allow
        the Glance request to go through. We have to rely on the cached image
        metadata, instead.

        https://bugs.launchpad.net/nova/+bug/1339386
        """
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        instance = objects.Instance(**self.test_instance)

        network_info = mock.MagicMock()
        block_device_info = mock.MagicMock()
        mock_get_disk_info.return_value = {}
        mock_get_guest_config.return_value = mock.MagicMock()
        mock_get_instance_path.return_value = '/foo'
        mock_looping_call.return_value = mock.MagicMock()
        conn._image_api = mock.MagicMock()

        conn._hard_reboot(self.context, instance, network_info,
                          block_device_info)

        self.assertFalse(conn._image_api.get.called)
        mock_ensure_tree.assert_called_once_with('/foo')

    def test_power_on(self):

        def _check_xml_bus(name, xml, block_info):
            tree = etree.fromstring(xml)
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
            return hardware.InstanceInfo(state=state)

        def _get_inst(with_meta=True):
            inst_ref = self.test_instance
            inst_ref['uuid'] = uuidutils.generate_uuid()
            if with_meta:
                inst_ref['system_metadata']['image_hw_disk_bus'] = 'ide'
            instance = objects.Instance(**inst_ref)
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
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        network_info = _fake_network_info(self.stubs, 1)
        block_device_info = None
        image_service_mock = mock.Mock()
        image_service_mock.show.return_value = self.fake_img

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
                mock.patch.object(conn, '_destroy', return_value=None),
                mock.patch.object(conn, '_create_images_and_backing'),
                mock.patch.object(conn, '_create_domain_and_network'),
                mock.patch.object(objects.Flavor, 'get_by_id',
                                  return_value = flavor),
                mock.patch.object(objects.Instance, 'save')):
            conn.get_info = fake_get_info
            conn._get_instance_disk_info = _check_xml_bus
            conn._hard_reboot(self.context, instance, network_info,
                              block_device_info)

            instance = _get_inst(with_meta=False)
            conn._hard_reboot(self.context, instance, network_info,
                              block_device_info)

    def _test_clean_shutdown(self, seconds_to_shutdown,
                             timeout, retry_interval,
                             shutdown_attempts, succeeds):
        self.stubs.Set(time, 'sleep', lambda x: None)
        info_tuple = ('fake', 'fake', 'fake', 'also_fake')
        shutdown_count = []

        def count_shutdowns():
            shutdown_count.append("shutdown")

        # Mock domain
        mock_domain = self.mox.CreateMock(libvirt.virDomain)

        mock_domain.info().AndReturn(
                (libvirt_driver.VIR_DOMAIN_RUNNING,) + info_tuple)
        mock_domain.shutdown().WithSideEffects(count_shutdowns)

        retry_countdown = retry_interval
        for x in xrange(min(seconds_to_shutdown, timeout)):
            mock_domain.info().AndReturn(
                (libvirt_driver.VIR_DOMAIN_RUNNING,) + info_tuple)
            if retry_countdown == 0:
                mock_domain.shutdown().WithSideEffects(count_shutdowns)
                retry_countdown = retry_interval
            else:
                retry_countdown -= 1

        if seconds_to_shutdown < timeout:
            mock_domain.info().AndReturn(
                (libvirt_driver.VIR_DOMAIN_SHUTDOWN,) + info_tuple)

        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock_domain

        def fake_create_domain(**kwargs):
            self.reboot_create_called = True

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(**self.test_instance)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, '_create_domain', fake_create_domain)
        result = conn._clean_shutdown(instance, timeout, retry_interval)

        self.assertEqual(succeeds, result)
        self.assertEqual(shutdown_attempts, len(shutdown_count))

    def test_clean_shutdown_first_time(self):
        self._test_clean_shutdown(seconds_to_shutdown=2,
                                  timeout=5,
                                  retry_interval=3,
                                  shutdown_attempts=1,
                                  succeeds=True)

    def test_clean_shutdown_with_retry(self):
        self._test_clean_shutdown(seconds_to_shutdown=4,
                                  timeout=5,
                                  retry_interval=3,
                                  shutdown_attempts=2,
                                  succeeds=True)

    def test_clean_shutdown_failure(self):
        self._test_clean_shutdown(seconds_to_shutdown=6,
                                  timeout=5,
                                  retry_interval=3,
                                  shutdown_attempts=2,
                                  succeeds=False)

    def test_clean_shutdown_no_wait(self):
        self._test_clean_shutdown(seconds_to_shutdown=6,
                                  timeout=0,
                                  retry_interval=3,
                                  shutdown_attempts=1,
                                  succeeds=False)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(FakeVirtDomain, 'attachDevice')
    @mock.patch.object(FakeVirtDomain, 'ID', return_value=1)
    @mock.patch.object(compute_utils, 'get_image_metadata', return_value=None)
    def test_attach_sriov_ports(self,
                                mock_get_image_metadata,
                                mock_ID,
                                mock_attachDevice,
                                mock_flavor):
        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        network_info = _fake_network_info(self.stubs, 1)
        network_info[0]['vnic_type'] = network_model.VNIC_TYPE_DIRECT
        domain = FakeVirtDomain()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        conn._attach_sriov_ports(self.context, instance, domain, network_info)
        mock_get_image_metadata.assert_called_once_with(self.context,
            conn._image_api, instance['image_ref'], instance)
        self.assertTrue(mock_attachDevice.called)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(FakeVirtDomain, 'attachDevice')
    @mock.patch.object(FakeVirtDomain, 'ID', return_value=1)
    @mock.patch.object(compute_utils, 'get_image_metadata', return_value=None)
    def test_attach_sriov_ports_with_info_cache(self,
                                                mock_get_image_metadata,
                                                mock_ID,
                                                mock_attachDevice,
                                                mock_flavor):
        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        network_info = _fake_network_info(self.stubs, 1)
        network_info[0]['vnic_type'] = network_model.VNIC_TYPE_DIRECT
        instance.info_cache = objects.InstanceInfoCache(
            network_info=network_info)
        domain = FakeVirtDomain()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        conn._attach_sriov_ports(self.context, instance, domain, None)
        mock_get_image_metadata.assert_called_once_with(self.context,
            conn._image_api, instance['image_ref'], instance)
        self.assertTrue(mock_attachDevice.called)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(host.Host,
                       'has_min_version', return_value=True)
    @mock.patch.object(FakeVirtDomain, 'detachDeviceFlags')
    @mock.patch.object(compute_utils, 'get_image_metadata', return_value=None)
    def test_detach_sriov_ports(self,
                                mock_get_image_metadata,
                                mock_detachDeviceFlags,
                                mock_has_min_version,
                                mock_flavor):
        instance = objects.Instance(**self.test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        mock_flavor.return_value = flavor

        network_info = _fake_network_info(self.stubs, 1)
        network_info[0]['vnic_type'] = network_model.VNIC_TYPE_DIRECT
        instance.info_cache = objects.InstanceInfoCache(
            network_info=network_info)

        domain = FakeVirtDomain()
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        conn._detach_sriov_ports(instance, domain)
        mock_get_image_metadata.assert_called_once_with(mock.ANY,
            conn._image_api, instance['image_ref'], instance)
        self.assertTrue(mock_detachDeviceFlags.called)

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
        instance = objects.Instance(**self.test_instance)
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
            mock.patch.object(compute_utils, 'get_image_metadata'),
            mock.patch.object(blockinfo, 'get_disk_info'),
        ) as (_get_existing_domain_xml, _create_domain_and_network,
              _attach_pci_devices, get_instance_pci_devs, get_image_metadata,
              get_disk_info):
            get_image_metadata.return_value = {'bar': 234}

            disk_info = {'foo': 123}
            get_disk_info.return_value = disk_info

            conn.resume(self.context, instance, network_info,
                        block_device_info)
            _get_existing_domain_xml.assert_has_calls([mock.call(instance,
                                            network_info, block_device_info)])
            _create_domain_and_network.assert_has_calls([mock.call(
                                        self.context, dummyxml,
                                        instance, network_info, disk_info,
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
            return hardware.InstanceInfo(state=power_state.SHUTDOWN, id=-1)

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)

        instance = objects.Instance(**self.test_instance)
        conn.destroy(self.context, instance, [])

    @mock.patch.object(rbd_utils, 'RBDDriver')
    def test_cleanup_rbd(self, mock_driver):
        driver = mock_driver.return_value
        driver.cleanup_volumes = mock.Mock()
        fake_instance = {'uuid': '875a8070-d0b9-4949-8b31-104d125c9a64'}

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        conn._cleanup_rbd(fake_instance)

        driver.cleanup_volumes.assert_called_once_with(fake_instance)

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
            return hardware.InstanceInfo(state=power_state.SHUTDOWN, id=-1)

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = objects.Instance(**self.test_instance)
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
            return hardware.InstanceInfo(state=power_state.SHUTDOWN, id=-1)

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = objects.Instance(**self.test_instance)
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
            return hardware.InstanceInfo(state=power_state.SHUTDOWN)

        def fake_delete_instance_files(instance):
            return None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        self.stubs.Set(conn, 'get_info', fake_get_info)
        self.stubs.Set(conn, '_delete_instance_files',
                       fake_delete_instance_files)
        instance = objects.Instance(**self.test_instance)
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
        instance = objects.Instance(**self.test_instance)
        self.assertRaises(exception.InstancePowerOffFailure,
                conn.destroy, self.context, instance, [])

    def test_private_destroy_not_found(self):
        ex = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                "No such domain",
                error_code=libvirt.VIR_ERR_NO_DOMAIN)
        mock = self.mox.CreateMock(libvirt.virDomain)
        mock.ID()
        mock.destroy().AndRaise(ex)
        mock.info().AndRaise(ex)
        self.mox.ReplayAll()

        def fake_lookup_by_name(instance_name):
            return mock

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.stubs.Set(conn, '_lookup_by_name', fake_lookup_by_name)
        instance = objects.Instance(**self.test_instance)
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
        instance = objects.Instance(**self.test_instance)

        # NOTE(wenjianhn): verifies undefine doesn't raise if the
        # instance disappears
        conn._undefine_domain(instance)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_disk_over_committed_size_total(self, mock_list):
        # Ensure destroy calls managedSaveRemove for saved instance.
        class DiagFakeDomain(object):
            def __init__(self, name):
                self._name = name

            def ID(self):
                return 1

            def name(self):
                return self._name

            def UUIDString(self):
                return "19479fee-07a5-49bb-9138-d3738280d63c"

            def XMLDesc(self, flags):
                return "<domain/>"

        mock_list.return_value = [
            DiagFakeDomain("instance0000001"),
            DiagFakeDomain("instance0000002")]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        fake_disks = {'instance0000001':
                      [{'type': 'qcow2', 'path': '/somepath/disk1',
                        'virt_disk_size': '10737418240',
                        'backing_file': '/somepath/disk1',
                        'disk_size': '83886080',
                        'over_committed_disk_size': '10653532160'}],
                      'instance0000002':
                      [{'type': 'raw', 'path': '/somepath/disk2',
                        'virt_disk_size': '0',
                        'backing_file': '/somepath/disk2',
                        'disk_size': '10737418240',
                        'over_committed_disk_size': '0'}]}

        def get_info(instance_name, xml, **kwargs):
            return jsonutils.dumps(fake_disks.get(instance_name))

        with mock.patch.object(drvr,
                               "_get_instance_disk_info") as mock_info:
            mock_info.side_effect = get_info

            result = drvr._get_disk_over_committed_size_total()
            self.assertEqual(result, 10653532160)
            mock_list.assert_called_with()
            self.assertTrue(mock_info.called)

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_disk_over_committed_size_total_eperm(self, mock_list):
        # Ensure destroy calls managedSaveRemove for saved instance.
        class DiagFakeDomain(object):
            def __init__(self, name):
                self._name = name

            def ID(self):
                return 1

            def name(self):
                return self._name

            def UUIDString(self):
                return "19479fee-07a5-49bb-9138-d3738280d63c"

            def XMLDesc(self, flags):
                return "<domain/>"

        mock_list.return_value = [
            DiagFakeDomain("instance0000001"),
            DiagFakeDomain("instance0000002")]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        fake_disks = {'instance0000001':
                      [{'type': 'qcow2', 'path': '/somepath/disk1',
                        'virt_disk_size': '10737418240',
                        'backing_file': '/somepath/disk1',
                        'disk_size': '83886080',
                        'over_committed_disk_size': '10653532160'}],
                      'instance0000002':
                      [{'type': 'raw', 'path': '/somepath/disk2',
                        'virt_disk_size': '0',
                        'backing_file': '/somepath/disk2',
                        'disk_size': '10737418240',
                        'over_committed_disk_size': '21474836480'}]}

        def side_effect(name, dom):
            if name == 'instance0000001':
                raise OSError(errno.EACCES, 'Permission denied')
            if name == 'instance0000002':
                return jsonutils.dumps(fake_disks.get(name))
        get_disk_info = mock.Mock()
        get_disk_info.side_effect = side_effect
        drvr._get_instance_disk_info = get_disk_info

        result = drvr._get_disk_over_committed_size_total()
        self.assertEqual(21474836480, result)
        mock_list.assert_called_with()

    @mock.patch.object(libvirt_driver.LibvirtDriver, "_list_instance_domains",
                       return_value=[mock.MagicMock(name='foo')])
    @mock.patch.object(libvirt_driver.LibvirtDriver, "_get_instance_disk_info",
                       side_effect=exception.VolumeBDMPathNotFound(path='bar'))
    def test_disk_over_committed_size_total_bdm_not_found(self,
                                                          mock_get_disk_info,
                                                          mock_list_domains):
        # Tests that we handle VolumeBDMPathNotFound gracefully.
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertEqual(0, drvr._get_disk_over_committed_size_total())

    def test_cpu_info(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        def get_host_capabilities_stub(self):
            cpu = vconfig.LibvirtConfigCPU()
            cpu.model = "Opteron_G4"
            cpu.vendor = "AMD"
            cpu.arch = arch.X86_64

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
            guest.arch = arch.X86_64
            guest.domtype = ["kvm"]
            caps.guests.append(guest)

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = vm_mode.HVM
            guest.arch = arch.I686
            guest.domtype = ["kvm"]
            caps.guests.append(guest)

            return caps

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       '_get_host_capabilities',
                       get_host_capabilities_stub)

        want = {"vendor": "AMD",
                "features": ["extapic", "3dnow"],
                "model": "Opteron_G4",
                "arch": arch.X86_64,
                "topology": {"cores": 2, "threads": 1, "sockets": 4}}
        got = jsonutils.loads(conn._get_cpu_info())
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

    def test_list_devices_not_supported(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        # Handle just the NO_SUPPORT error
        not_supported_exc = fakelibvirt.make_libvirtError(
                libvirt.libvirtError,
                'this function is not supported by the connection driver:'
                ' virNodeNumOfDevices',
                error_code=libvirt.VIR_ERR_NO_SUPPORT)

        with mock.patch.object(conn._conn, 'listDevices',
                               side_effect=not_supported_exc):
            self.assertEqual('[]', conn._get_pci_passthrough_devices())

        # We cache not supported status to avoid emitting too many logging
        # messages. Clear this value to test the other exception case.
        del conn._list_devices_supported

        # Other errors should not be caught
        other_exc = fakelibvirt.make_libvirtError(
            libvirt.libvirtError,
            'other exc',
            error_code=libvirt.VIR_ERR_NO_DOMAIN)

        with mock.patch.object(conn._conn, 'listDevices',
                               side_effect=other_exc):
            self.assertRaises(libvirt.libvirtError,
                              conn._get_pci_passthrough_devices)

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
        actjson = conn._get_pci_passthrough_devices()

        expectvfs = [
            {
                "dev_id": "pci_0000_04_00_3",
                "address": "0000:04:00.3",
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

        actualvfs = jsonutils.loads(actjson)
        for dev in range(len(actualvfs)):
            for key in actualvfs[dev].keys():
                if key not in ['phys_function', 'virt_functions', 'label']:
                    self.assertEqual(actualvfs[dev][key], expectvfs[dev][key])

    def _fake_caps_numa_topology(self):
        topology = vconfig.LibvirtConfigCapsNUMATopology()

        for i in range(4):
            cell = vconfig.LibvirtConfigCapsNUMACell()
            cell.id = i
            cell.memory = 1024 * units.Ki
            cpu_0 = vconfig.LibvirtConfigCapsNUMACPU()
            cpu_0.id = 2 * i
            cpu_0.socket_id = i
            cpu_0.core_id = 0
            cpu_0.sibling = 2 * i
            mempages_0 = vconfig.LibvirtConfigCapsNUMAPages()
            mempages_0.size = 4
            mempages_0.total = 1024 * i
            cpu_1 = vconfig.LibvirtConfigCapsNUMACPU()
            cpu_1.id = 2 * i + 1
            cpu_1.socket_id = i
            cpu_1.core_id = 1
            cpu_1.sibling = 2 * i + 1
            mempages_1 = vconfig.LibvirtConfigCapsNUMAPages()
            mempages_1.size = 2048
            mempages_1.total = 0 + i
            cell.cpus = [cpu_0, cpu_1]
            cell.mempages = [mempages_0, mempages_1]
            topology.cells.append(cell)

        return topology

    def test_get_host_numa_topology(self):
        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.topology = self._fake_caps_numa_topology()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        expected_topo_dict = {'cells': [
                                {'cpus': '0,1', 'cpu_usage': 0,
                                  'mem': {'total': 1024, 'used': 0},
                                  'id': 0},
                                {'cpus': '3', 'cpu_usage': 0,
                                  'mem': {'total': 1024, 'used': 0},
                                  'id': 1},
                                {'cpus': '', 'cpu_usage': 0,
                                  'mem': {'total': 1024, 'used': 0},
                                  'id': 2},
                                {'cpus': '', 'cpu_usage': 0,
                                  'mem': {'total': 1024, 'used': 0},
                                  'id': 3}]}
        with contextlib.nested(
                mock.patch.object(host.Host, 'has_min_version',
                                  return_value=True),
                mock.patch.object(
                    conn, '_get_host_capabilities', return_value=caps),
                mock.patch.object(
                    hardware, 'get_vcpu_pin_set', return_value=set([0, 1, 3]))
                ):
            got_topo = conn._get_host_numa_topology()
            got_topo_dict = got_topo._to_dict()
            self.assertThat(
                    expected_topo_dict, matchers.DictMatches(got_topo_dict))
            # cells 0
            self.assertEqual(4, got_topo.cells[0].mempages[0].size_kb)
            self.assertEqual(0, got_topo.cells[0].mempages[0].total)
            self.assertEqual(2048, got_topo.cells[0].mempages[1].size_kb)
            self.assertEqual(0, got_topo.cells[0].mempages[1].total)
            # cells 1
            self.assertEqual(4, got_topo.cells[1].mempages[0].size_kb)
            self.assertEqual(1024, got_topo.cells[1].mempages[0].total)
            self.assertEqual(2048, got_topo.cells[1].mempages[1].size_kb)
            self.assertEqual(1, got_topo.cells[1].mempages[1].total)

    def test_get_host_numa_topology_empty(self):
        caps = vconfig.LibvirtConfigCaps()
        caps.host = vconfig.LibvirtConfigCapsHost()
        caps.host.topology = None

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with contextlib.nested(
            mock.patch.object(host.Host, 'has_min_version', return_value=True),
            mock.patch.object(conn, '_get_host_capabilities',
                              return_value=caps)
        ) as (has_min_version, get_caps):
            self.assertIsNone(conn._get_host_numa_topology())
        get_caps.assert_called_once_with()

    def test_get_host_numa_topology_not_supported(self):
        # Tests that libvirt isn't new enough to support numa topology.
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        with mock.patch.object(host.Host, 'has_min_version',
                               return_value=False):
            self.assertIsNone(conn._get_host_numa_topology())

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
        instance = objects.Instance(**self.test_instance)
        actual = conn.get_diagnostics(instance)
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

        lt = datetime.datetime(2012, 11, 22, 12, 00, 00)
        diags_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        timeutils.set_time_override(diags_time)

        instance.launched_at = lt
        actual = conn.get_instance_diagnostics(instance)
        expected = {'config_drive': False,
                    'cpu_details': [],
                    'disk_details': [{'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L},
                                     {'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L}],
                    'driver': 'libvirt',
                    'hypervisor_os': 'linux',
                    'memory_details': {'maximum': 2048, 'used': 1234},
                    'nic_details': [{'mac_address': '52:54:00:a4:38:38',
                                     'rx_drop': 0L,
                                     'rx_errors': 0L,
                                     'rx_octets': 4408L,
                                     'rx_packets': 82L,
                                     'tx_drop': 0L,
                                     'tx_errors': 0L,
                                     'tx_octets': 0L,
                                     'tx_packets': 0L}],
                    'state': 'running',
                    'uptime': 10,
                    'version': '1.0'}
        self.assertEqual(expected, actual.serialize())

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
        instance = objects.Instance(**self.test_instance)
        actual = conn.get_diagnostics(instance)
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

        lt = datetime.datetime(2012, 11, 22, 12, 00, 00)
        diags_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        timeutils.set_time_override(diags_time)

        instance.launched_at = lt
        actual = conn.get_instance_diagnostics(instance)
        expected = {'config_drive': False,
                    'cpu_details': [{'time': 15340000000L},
                                    {'time': 1640000000L},
                                    {'time': 3040000000L},
                                    {'time': 1420000000L}],
                    'disk_details': [],
                    'driver': 'libvirt',
                    'hypervisor_os': 'linux',
                    'memory_details': {'maximum': 2048, 'used': 1234},
                    'nic_details': [{'mac_address': '52:54:00:a4:38:38',
                                     'rx_drop': 0L,
                                     'rx_errors': 0L,
                                     'rx_octets': 4408L,
                                     'rx_packets': 82L,
                                     'tx_drop': 0L,
                                     'tx_errors': 0L,
                                     'tx_octets': 0L,
                                     'tx_packets': 0L}],
                    'state': 'running',
                    'uptime': 10,
                    'version': '1.0'}
        self.assertEqual(expected, actual.serialize())

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
        instance = objects.Instance(**self.test_instance)
        actual = conn.get_diagnostics(instance)
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

        lt = datetime.datetime(2012, 11, 22, 12, 00, 00)
        diags_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        timeutils.set_time_override(diags_time)

        instance.launched_at = lt
        actual = conn.get_instance_diagnostics(instance)
        expected = {'config_drive': False,
                    'cpu_details': [{'time': 15340000000L},
                                    {'time': 1640000000L},
                                    {'time': 3040000000L},
                                    {'time': 1420000000L}],
                    'disk_details': [{'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L},
                                     {'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L}],
                    'driver': 'libvirt',
                    'hypervisor_os': 'linux',
                    'memory_details': {'maximum': 2048, 'used': 1234},
                    'nic_details': [],
                    'state': 'running',
                    'uptime': 10,
                    'version': '1.0'}
        self.assertEqual(expected, actual.serialize())

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
        instance = objects.Instance(**self.test_instance)
        actual = conn.get_diagnostics(instance)
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

        lt = datetime.datetime(2012, 11, 22, 12, 00, 00)
        diags_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        timeutils.set_time_override(diags_time)

        instance.launched_at = lt
        actual = conn.get_instance_diagnostics(instance)
        expected = {'config_drive': False,
                    'cpu_details': [{'time': 15340000000L},
                                    {'time': 1640000000L},
                                    {'time': 3040000000L},
                                    {'time': 1420000000L}],
                    'disk_details': [{'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L},
                                     {'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L}],
                    'driver': 'libvirt',
                    'hypervisor_os': 'linux',
                    'memory_details': {'maximum': 2048, 'used': 1234},
                    'nic_details': [{'mac_address': '52:54:00:a4:38:38',
                                     'rx_drop': 0L,
                                     'rx_errors': 0L,
                                     'rx_octets': 4408L,
                                     'rx_packets': 82L,
                                     'tx_drop': 0L,
                                     'tx_errors': 0L,
                                     'tx_octets': 0L,
                                     'tx_packets': 0L}],
                    'state': 'running',
                    'uptime': 10,
                    'version': '1.0'}
        self.assertEqual(expected, actual.serialize())

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
        instance = objects.Instance(**self.test_instance)
        actual = conn.get_diagnostics(instance)
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

        lt = datetime.datetime(2012, 11, 22, 12, 00, 00)
        diags_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        timeutils.set_time_override(diags_time)

        instance.launched_at = lt
        actual = conn.get_instance_diagnostics(instance)
        expected = {'config_drive': False,
                    'cpu_details': [{'time': 15340000000L},
                                    {'time': 1640000000L},
                                    {'time': 3040000000L},
                                    {'time': 1420000000L}],
                    'disk_details': [{'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L},
                                     {'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 688640L,
                                      'read_requests': 169L,
                                      'write_bytes': 0L,
                                      'write_requests': 0L}],
                    'driver': 'libvirt',
                    'hypervisor_os': 'linux',
                    'memory_details': {'maximum': 2048, 'used': 1234},
                    'nic_details': [{'mac_address': '52:54:00:a4:38:38',
                                     'rx_drop': 0L,
                                     'rx_errors': 0L,
                                     'rx_octets': 4408L,
                                     'rx_packets': 82L,
                                     'tx_drop': 0L,
                                     'tx_errors': 0L,
                                     'tx_octets': 0L,
                                     'tx_packets': 0L}],
                    'state': 'running',
                    'uptime': 10,
                    'version': '1.0'}
        self.assertEqual(expected, actual.serialize())

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_failing_vcpu_count(self, mock_list):
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

            def ID(self):
                return 1

            def name(self):
                return "instance000001"

            def UUIDString(self):
                return "19479fee-07a5-49bb-9138-d3738280d63c"

        mock_list.return_value = [
            DiagFakeDomain(None), DiagFakeDomain(5)]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        self.assertEqual(5, drvr._get_vcpu_used())
        mock_list.assert_called_with()

    @mock.patch.object(libvirt_driver.LibvirtDriver,
                       "_list_instance_domains")
    def test_failing_vcpu_count_none(self, mock_list):
        """Domain will return zero if the current number of vcpus used
        is None. This is in case of VM state starting up or shutting
        down. None type returned is counted as zero.
        """

        class DiagFakeDomain(object):
            def __init__(self):
                pass

            def vcpus(self):
                return None

            def ID(self):
                return 1

            def name(self):
                return "instance000001"

        mock_list.return_value = [DiagFakeDomain()]

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.assertEqual(0, drvr._get_vcpu_used())
        mock_list.assert_called_with()

    def test_get_memory_used_normal(self):
        m = mock.mock_open(read_data="""
MemTotal:       16194180 kB
MemFree:          233092 kB
MemAvailable:    8892356 kB
Buffers:          567708 kB
Cached:          8362404 kB
SwapCached:            0 kB
Active:          8381604 kB
""")
        with contextlib.nested(
                mock.patch("__builtin__.open", m, create=True),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  "_conn"),
                mock.patch('sys.platform', 'linux2'),
                ) as (mock_file, mock_conn, mock_platform):
            mock_conn.getInfo.return_value = [
                arch.X86_64, 15814L, 8, 1208, 1, 1, 4, 2]

            drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

            self.assertEqual(6866, drvr._get_memory_mb_used())

    def test_get_memory_used_xen(self):
        self.flags(virt_type='xen', group='libvirt')

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
                return str(uuid.uuid4())

        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        m = mock.mock_open(read_data="""
MemTotal:       16194180 kB
MemFree:          233092 kB
MemAvailable:    8892356 kB
Buffers:          567708 kB
Cached:          8362404 kB
SwapCached:            0 kB
Active:          8381604 kB
""")

        with contextlib.nested(
                mock.patch("__builtin__.open", m, create=True),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  "_list_instance_domains"),
                mock.patch.object(libvirt_driver.LibvirtDriver,
                                  "_conn"),
                mock.patch('sys.platform', 'linux2'),
                ) as (mock_file, mock_list, mock_conn, mock_platform):
            mock_list.return_value = [
                DiagFakeDomain(0, 15814),
                DiagFakeDomain(1, 750),
                DiagFakeDomain(2, 1042)]
            mock_conn.getInfo.return_value = [
                arch.X86_64, 15814L, 8, 1208, 1, 1, 4, 2]

            self.assertEqual(8657, drvr._get_memory_mb_used())
            mock_list.assert_called_with(only_guests=False)

    def test_get_instance_capabilities(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        def get_host_capabilities_stub(self):
            caps = vconfig.LibvirtConfigCaps()

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = 'hvm'
            guest.arch = arch.X86_64
            guest.domtype = ['kvm', 'qemu']
            caps.guests.append(guest)

            guest = vconfig.LibvirtConfigGuest()
            guest.ostype = 'hvm'
            guest.arch = arch.I686
            guest.domtype = ['kvm']
            caps.guests.append(guest)

            return caps

        self.stubs.Set(libvirt_driver.LibvirtDriver,
                       '_get_host_capabilities',
                       get_host_capabilities_stub)

        want = [(arch.X86_64, 'kvm', 'hvm'),
                (arch.X86_64, 'qemu', 'hvm'),
                (arch.I686, 'kvm', 'hvm')]
        got = conn._get_instance_capabilities()
        self.assertEqual(want, got)

    def test_set_cache_mode(self):
        self.flags(disk_cachemodes=['file=directsync'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuestDisk()

        fake_conf.source_type = 'file'
        conn._set_cache_mode(fake_conf)
        self.assertEqual(fake_conf.driver_cache, 'directsync')

    def test_set_cache_mode_invalid_mode(self):
        self.flags(disk_cachemodes=['file=FAKE'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuestDisk()

        fake_conf.source_type = 'file'
        conn._set_cache_mode(fake_conf)
        self.assertIsNone(fake_conf.driver_cache)

    def test_set_cache_mode_invalid_object(self):
        self.flags(disk_cachemodes=['file=directsync'], group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        fake_conf = FakeConfigGuest()

        fake_conf.driver_cache = 'fake'
        conn._set_cache_mode(fake_conf)
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

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._lookup_by_name')
    def test_get_domain_info_with_more_return(self, lookup_mock):
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        dom_mock = mock.MagicMock()
        dom_mock.info.return_value = [
            1, 2048, 737, 8, 12345, 888888
        ]
        dom_mock.ID.return_value = mock.sentinel.instance_id
        lookup_mock.return_value = dom_mock
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        info = conn.get_info(instance)
        self.assertEqual(1, info.state)
        self.assertEqual(2048, info.max_mem_kb)
        self.assertEqual(737, info.mem_kb)
        self.assertEqual(8, info.num_cpu)
        self.assertEqual(12345, info.cpu_time_ns)
        self.assertEqual(mock.sentinel.instance_id, info.id)
        dom_mock.info.assert_called_once_with()
        dom_mock.ID.assert_called_once_with()
        lookup_mock.assert_called_once_with(instance['name'])

    @mock.patch.object(encodeutils, 'safe_decode')
    def test_create_domain(self, mock_safe_decode):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        mock_domain = mock.MagicMock()
        mock_instance = mock.MagicMock()

        domain = conn._create_domain(domain=mock_domain,
                                     instance=mock_instance)

        self.assertEqual(mock_domain, domain)
        mock_domain.createWithFlags.assert_has_calls([mock.call(0)])
        self.assertEqual(2, mock_safe_decode.call_count)

    @mock.patch('nova.virt.disk.api.clean_lxc_namespace')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.get_info')
    @mock.patch('nova.virt.disk.api.setup_container')
    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
    @mock.patch.object(fake_libvirt_utils, 'get_instance_path')
    def test_create_domain_lxc(self, mock_get_inst_path, mock_ensure_tree,
                           mock_setup_container, mock_get_info, mock_clean):
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        mock_instance = mock.MagicMock()
        inst_sys_meta = dict()
        mock_instance.system_metadata = inst_sys_meta
        mock_get_inst_path.return_value = '/tmp/'
        mock_image_backend = mock.MagicMock()
        conn.image_backend = mock_image_backend
        mock_image = mock.MagicMock()
        mock_image.path = '/tmp/test.img'
        conn.image_backend.image.return_value = mock_image
        mock_setup_container.return_value = '/dev/nbd0'
        mock_get_info.return_value = hardware.InstanceInfo(
            state=power_state.RUNNING)

        with contextlib.nested(
            mock.patch.object(conn, '_create_images_and_backing'),
            mock.patch.object(conn, '_is_booted_from_volume',
                              return_value=False),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver, 'prepare_instance_filter'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter')):
            conn._create_domain_and_network(self.context, 'xml',
                                            mock_instance, [], None)

        self.assertEqual('/dev/nbd0', inst_sys_meta['rootfs_device_name'])
        self.assertFalse(mock_instance.called)
        mock_get_inst_path.assert_has_calls([mock.call(mock_instance)])
        mock_ensure_tree.assert_has_calls([mock.call('/tmp/rootfs')])
        conn.image_backend.image.assert_has_calls([mock.call(mock_instance,
                                                             'disk')])
        setup_container_call = mock.call('/tmp/test.img',
                                         container_dir='/tmp/rootfs',
                                         use_cow=CONF.use_cow_images)
        mock_setup_container.assert_has_calls([setup_container_call])
        mock_get_info.assert_has_calls([mock.call(mock_instance)])
        mock_clean.assert_has_calls([mock.call(container_dir='/tmp/rootfs')])

    @mock.patch('nova.virt.disk.api.clean_lxc_namespace')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.get_info')
    @mock.patch.object(fake_libvirt_utils, 'chown_for_id_maps')
    @mock.patch('nova.virt.disk.api.setup_container')
    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
    @mock.patch.object(fake_libvirt_utils, 'get_instance_path')
    def test_create_domain_lxc_id_maps(self, mock_get_inst_path,
                                       mock_ensure_tree, mock_setup_container,
                                       mock_chown, mock_get_info, mock_clean):
        self.flags(virt_type='lxc', uid_maps=["0:1000:100"],
                   gid_maps=["0:1000:100"], group='libvirt')

        def chown_side_effect(path, id_maps):
            self.assertEqual('/tmp/rootfs', path)
            self.assertIsInstance(id_maps[0], vconfig.LibvirtConfigGuestUIDMap)
            self.assertEqual(0, id_maps[0].start)
            self.assertEqual(1000, id_maps[0].target)
            self.assertEqual(100, id_maps[0].count)
            self.assertIsInstance(id_maps[1], vconfig.LibvirtConfigGuestGIDMap)
            self.assertEqual(0, id_maps[1].start)
            self.assertEqual(1000, id_maps[1].target)
            self.assertEqual(100, id_maps[1].count)

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        mock_instance = mock.MagicMock()
        inst_sys_meta = dict()
        mock_instance.system_metadata = inst_sys_meta
        mock_get_inst_path.return_value = '/tmp/'
        mock_image_backend = mock.MagicMock()
        conn.image_backend = mock_image_backend
        mock_image = mock.MagicMock()
        mock_image.path = '/tmp/test.img'
        conn.image_backend.image.return_value = mock_image
        mock_setup_container.return_value = '/dev/nbd0'
        mock_chown.side_effect = chown_side_effect
        mock_get_info.return_value = hardware.InstanceInfo(
            state=power_state.RUNNING)

        with contextlib.nested(
            mock.patch.object(conn, '_create_images_and_backing'),
            mock.patch.object(conn, '_is_booted_from_volume',
                              return_value=False),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver, 'prepare_instance_filter'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter')):
            conn._create_domain_and_network(self.context, 'xml',
                                            mock_instance, [], None)

        self.assertEqual('/dev/nbd0', inst_sys_meta['rootfs_device_name'])
        self.assertFalse(mock_instance.called)
        mock_get_inst_path.assert_has_calls([mock.call(mock_instance)])
        mock_ensure_tree.assert_has_calls([mock.call('/tmp/rootfs')])
        conn.image_backend.image.assert_has_calls([mock.call(mock_instance,
                                                             'disk')])
        setup_container_call = mock.call('/tmp/test.img',
                                         container_dir='/tmp/rootfs',
                                         use_cow=CONF.use_cow_images)
        mock_setup_container.assert_has_calls([setup_container_call])
        mock_get_info.assert_has_calls([mock.call(mock_instance)])
        mock_clean.assert_has_calls([mock.call(container_dir='/tmp/rootfs')])

    @mock.patch('nova.virt.disk.api.teardown_container')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.get_info')
    @mock.patch('nova.virt.disk.api.setup_container')
    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
    @mock.patch.object(fake_libvirt_utils, 'get_instance_path')
    def test_create_domain_lxc_not_running(self, mock_get_inst_path,
                                           mock_ensure_tree,
                                           mock_setup_container,
                                           mock_get_info, mock_teardown):
        self.flags(virt_type='lxc', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)
        mock_instance = mock.MagicMock()
        inst_sys_meta = dict()
        mock_instance.system_metadata = inst_sys_meta
        mock_get_inst_path.return_value = '/tmp/'
        mock_image_backend = mock.MagicMock()
        conn.image_backend = mock_image_backend
        mock_image = mock.MagicMock()
        mock_image.path = '/tmp/test.img'
        conn.image_backend.image.return_value = mock_image
        mock_setup_container.return_value = '/dev/nbd0'
        mock_get_info.return_value = hardware.InstanceInfo(
            state=power_state.SHUTDOWN)

        with contextlib.nested(
            mock.patch.object(conn, '_create_images_and_backing'),
            mock.patch.object(conn, '_is_booted_from_volume',
                              return_value=False),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver, 'prepare_instance_filter'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter')):
            conn._create_domain_and_network(self.context, 'xml',
                                            mock_instance, [], None)

        self.assertEqual('/dev/nbd0', inst_sys_meta['rootfs_device_name'])
        self.assertFalse(mock_instance.called)
        mock_get_inst_path.assert_has_calls([mock.call(mock_instance)])
        mock_ensure_tree.assert_has_calls([mock.call('/tmp/rootfs')])
        conn.image_backend.image.assert_has_calls([mock.call(mock_instance,
                                                             'disk')])
        setup_container_call = mock.call('/tmp/test.img',
                                         container_dir='/tmp/rootfs',
                                         use_cow=CONF.use_cow_images)
        mock_setup_container.assert_has_calls([setup_container_call])
        mock_get_info.assert_has_calls([mock.call(mock_instance)])
        teardown_call = mock.call(container_dir='/tmp/rootfs')
        mock_teardown.assert_has_calls([teardown_call])

    def test_create_domain_define_xml_fails(self):
        """Tests that the xml is logged when defining the domain fails."""
        fake_xml = "<test>this is a test</test>"

        def fake_defineXML(xml):
            self.assertEqual(fake_xml, xml)
            raise libvirt.libvirtError('virDomainDefineXML() failed')

        self.log_error_called = False

        def fake_error(msg, *args):
            self.log_error_called = True
            self.assertIn(fake_xml, msg % args)

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

        def fake_error(msg, *args):
            self.log_error_called = True
            self.assertIn(fake_xml, msg % args)

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
        fake_xml = "<test>this is a test</test>"
        fake_domain = FakeVirtDomain(fake_xml)

        def fake_enable_hairpin(launch_flags):
            raise processutils.ProcessExecutionError('error')

        self.log_error_called = False

        def fake_error(msg, *args):
            self.log_error_called = True
            self.assertIn(fake_xml, msg % args)

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
        instance = objects.Instance(**self.test_instance)
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
        self.assertEqual(vnc_dict.port, '5900')

    def test_get_vnc_console_unavailable(self):
        instance = objects.Instance(**self.test_instance)
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
        instance = objects.Instance(**self.test_instance)
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
        self.assertEqual(spice_dict.port, '5950')

    def test_get_spice_console_unavailable(self):
        instance = objects.Instance(**self.test_instance)
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

        instance = objects.Instance(**self.test_instance)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        with contextlib.nested(
            mock.patch.object(conn, '_lookup_by_name',
                              side_effect=exception.InstanceNotFound(
                                  instance_id=instance.name)),
            mock.patch.object(conn, '_disconnect_volume')
        ) as (_lookup_by_name, _disconnect_volume):
            connection_info = {'driver_volume_type': 'fake'}
            conn.detach_volume(connection_info, instance, '/dev/sda')
            _lookup_by_name.assert_called_once_with(instance.name)
            _disconnect_volume.assert_called_once_with(connection_info,
                                                       'sda')

    @mock.patch.object(objects.Flavor, 'get_by_id')
    def _test_attach_detach_interface_get_config(self, method_name,
                                                 mock_flavor):
        """Tests that the get_config() method is properly called in
        attach_interface() and detach_interface().

        method_name: either \"attach_interface\" or \"detach_interface\"
                     depending on the method to test.
        """
        self.mox.StubOutWithMock(libvirt_driver.LibvirtDriver, '_conn')
        libvirt_driver.LibvirtDriver._conn.lookupByName = self.fake_lookup

        instance = objects.Instance(**self.test_instance)
        mock_flavor.return_value = instance.get_flavor()
        network_info = _fake_network_info(self.stubs, 1)
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), True)

        if method_name == "attach_interface":
            fake_image_meta = {'id': instance['image_ref']}
        elif method_name == "detach_interface":
            fake_image_meta = None
        else:
            raise ValueError("Unhandled method %" % method_name)

        if method_name == "attach_interface":
            self.mox.StubOutWithMock(conn.firewall_driver,
                                     'setup_basic_filtering')
            conn.firewall_driver.setup_basic_filtering(instance, network_info)

        expected = conn.vif_driver.get_config(instance, network_info[0],
                                              fake_image_meta,
                                              instance.get_flavor(),
                                              CONF.libvirt.virt_type)
        self.mox.StubOutWithMock(conn.vif_driver, 'get_config')
        conn.vif_driver.get_config(instance, network_info[0],
                                   fake_image_meta,
                                   mox.IsA(objects.Flavor),
                                   CONF.libvirt.virt_type).\
                                   AndReturn(expected)

        self.mox.ReplayAll()

        if method_name == "attach_interface":
            conn.attach_interface(instance, fake_image_meta,
                                  network_info[0])
        elif method_name == "detach_interface":
            conn.detach_interface(instance, network_info[0])
        else:
            raise ValueError("Unhandled method %" % method_name)

    @mock.patch.object(lockutils, "external_lock")
    def test_attach_interface_get_config(self, mock_lock):
        """Tests that the get_config() method is properly called in
        attach_interface().
        """
        mock_lock.return_value = threading.Semaphore()

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

    def test_is_supported_fs_format(self):
        supported_fs = [disk.FS_FORMAT_EXT2, disk.FS_FORMAT_EXT3,
                        disk.FS_FORMAT_EXT4, disk.FS_FORMAT_XFS]
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        for fs in supported_fs:
            self.assertTrue(conn.is_supported_fs_format(fs))

        supported_fs = ['', 'dummy']
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        for fs in supported_fs:
            self.assertFalse(conn.is_supported_fs_format(fs))

    def test_hypervisor_hostname_caching(self):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        conn = drvr._conn
        self.mox.StubOutWithMock(conn, 'getHostname')
        conn.getHostname().AndReturn('foo')
        conn.getHostname().AndReturn('bar')
        self.mox.ReplayAll()
        self.assertEqual('foo', drvr._get_hypervisor_hostname())
        self.assertEqual('foo', drvr._get_hypervisor_hostname())

    def test_post_live_migration_at_destination_with_block_device_info(self):
        # Preparing mocks
        mock_domain = self.mox.CreateMock(libvirt.virDomain)
        self.resultXML = None

        def fake_none(*args, **kwargs):
            return

        def fake_getLibVersion():
            return 9011

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
            if image_meta is None:
                image_meta = {}
            conf = conn._get_guest_config(instance, network_info, image_meta,
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
        instance = objects.Instance(**instance_ref)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}

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
                       '_get_guest_xml',
                       fake_to_xml)
        self.stubs.Set(conn,
                       '_lookup_by_name',
                       fake_lookup_name)
        block_device_info = {'block_device_mapping':
                driver_block_device.convert_volumes([
                    fake_block_device.FakeDbBlockDeviceDict(
                              {'id': 1, 'guest_format': None,
                               'boot_index': 0,
                               'source_type': 'volume',
                               'destination_type': 'volume',
                               'device_name': '/dev/vda',
                               'disk_bus': 'virtio',
                               'device_type': 'disk',
                               'delete_on_termination': False}),
                    ])}
        block_device_info['block_device_mapping'][0]['connection_info'] = (
                {'driver_volume_type': 'iscsi'})
        with contextlib.nested(
                mock.patch.object(
                    driver_block_device.DriverVolumeBlockDevice, 'save'),
                mock.patch.object(objects.Flavor, 'get_by_id',
                                   return_value=flavor),
                mock.patch.object(objects.Instance, 'save')):
            conn.post_live_migration_at_destination(
                    self.context, instance, network_info, True,
                    block_device_info=block_device_info)
            self.assertIn('fake', self.resultXML)
            self.assertTrue(
                    block_device_info['block_device_mapping'][0].save.called)

    def test_create_propagates_exceptions(self):
        self.flags(virt_type='lxc', group='libvirt')

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(id=1, uuid='fake-uuid',
                                    image_ref='my_fake_image')

        with contextlib.nested(
              mock.patch.object(conn, '_create_domain_setup_lxc'),
              mock.patch.object(conn, '_create_domain_cleanup_lxc'),
              mock.patch.object(conn, '_is_booted_from_volume',
                                return_value=False),
              mock.patch.object(conn, 'plug_vifs'),
              mock.patch.object(conn, 'firewall_driver'),
              mock.patch.object(conn, '_create_domain',
                                side_effect=exception.NovaException),
              mock.patch.object(conn, 'cleanup')):
            self.assertRaises(exception.NovaException,
                              conn._create_domain_and_network,
                              self.context,
                              'xml',
                              instance, None, None)

    def test_create_without_pause(self):
        self.flags(virt_type='lxc', group='libvirt')

        @contextlib.contextmanager
        def fake_lxc_disk_handler(*args, **kwargs):
            yield

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(id=1, uuid='fake-uuid')

        with contextlib.nested(
              mock.patch.object(conn, '_lxc_disk_handler',
                                side_effect=fake_lxc_disk_handler),
              mock.patch.object(conn, 'plug_vifs'),
              mock.patch.object(conn, 'firewall_driver'),
              mock.patch.object(conn, '_create_domain'),
              mock.patch.object(conn, 'cleanup')) as (
              _handler, cleanup, firewall_driver, create, plug_vifs):
            domain = conn._create_domain_and_network(self.context, 'xml',
                                                     instance, None, None)
            self.assertEqual(0, create.call_args_list[0][1]['launch_flags'])
            self.assertEqual(0, domain.resume.call_count)

    def _test_create_with_network_events(self, neutron_failure=None,
                                         power_on=True):
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

        instance = objects.Instance(id=1, uuid='fake-uuid')
        vifs = [{'id': 'vif1', 'active': False},
                {'id': 'vif2', 'active': False}]

        @mock.patch.object(conn, 'plug_vifs')
        @mock.patch.object(conn, 'firewall_driver')
        @mock.patch.object(conn, '_create_domain')
        @mock.patch.object(conn, 'cleanup')
        def test_create(cleanup, create, fw_driver, plug_vifs):
            domain = conn._create_domain_and_network(self.context, 'xml',
                                                     instance, vifs, None,
                                                     power_on=power_on)
            plug_vifs.assert_called_with(instance, vifs)

            flag = self._get_launch_flags(conn, vifs, power_on=power_on)
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
        block_device_info = {'block_device_mapping': [mock_volume]}
        network_info = [network_model.VIF(id='1'),
                        network_model.VIF(id='2', active=True)]

        with contextlib.nested(
            mock.patch.object(conn, '_get_volume_encryptor'),
            mock.patch.object(conn, 'plug_vifs'),
            mock.patch.object(conn.firewall_driver, 'setup_basic_filtering'),
            mock.patch.object(conn.firewall_driver,
                              'prepare_instance_filter'),
            mock.patch.object(conn, '_create_domain'),
            mock.patch.object(conn.firewall_driver, 'apply_instance_filter'),
        ) as (get_volume_encryptor, plug_vifs, setup_basic_filtering,
              prepare_instance_filter, create_domain, apply_instance_filter):
            create_domain.return_value = mock_dom

            domain = conn._create_domain_and_network(
                    self.context, fake_xml, instance, network_info, None,
                    block_device_info=block_device_info)

            get_encryption_metadata.assert_called_once_with(self.context,
                conn._volume_api, fake_volume_id, connection_info)
            get_volume_encryptor.assert_called_once_with(connection_info,
                                                         mock_encryption_meta)
            plug_vifs.assert_called_once_with(instance, network_info)
            setup_basic_filtering.assert_called_once_with(instance,
                                                          network_info)
            prepare_instance_filter.assert_called_once_with(instance,
                                                          network_info)
            flags = self._get_launch_flags(conn, network_info)
            create_domain.assert_called_once_with(fake_xml, instance=instance,
                                                  launch_flags=flags,
                                                  power_on=True)
            self.assertEqual(mock_dom, domain)

    def test_get_guest_storage_config(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        test_instance = copy.deepcopy(self.test_instance)
        test_instance["default_swap_device"] = None
        instance = objects.Instance(**test_instance)
        flavor = instance.get_flavor()
        flavor.extra_specs = {}
        conn_info = {'driver_volume_type': 'fake', 'data': {}}
        bdi = {'block_device_mapping':
               driver_block_device.convert_volumes([
                   fake_block_device.FakeDbBlockDeviceDict({
                       'id': 1,
                       'source_type': 'volume',
                       'destination_type': 'volume',
                       'device_name': '/dev/vdc'})
                ])}
        bdm = bdi['block_device_mapping'][0]
        bdm['connection_info'] = conn_info
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance, bdi)
        mock_conf = mock.MagicMock(source_path='fake')

        with contextlib.nested(
            mock.patch.object(driver_block_device.DriverVolumeBlockDevice,
                              'save'),
            mock.patch.object(conn, '_connect_volume'),
            mock.patch.object(conn, '_get_volume_config',
                              return_value=mock_conf),
            mock.patch.object(conn, '_set_cache_mode')
        ) as (volume_save, connect_volume, get_volume_config, set_cache_mode):
            devices = conn._get_guest_storage_config(instance, None,
                disk_info, False, bdi, flavor)

            self.assertEqual(3, len(devices))
            self.assertEqual('/dev/vdb', instance.default_ephemeral_device)
            self.assertIsNone(instance.default_swap_device)
            connect_volume.assert_called_with(bdm['connection_info'],
                {'bus': 'virtio', 'type': 'disk', 'dev': 'vdc'})
            get_volume_config.assert_called_with(bdm['connection_info'],
                {'bus': 'virtio', 'type': 'disk', 'dev': 'vdc'})
            self.assertEqual(1, volume_save.call_count)
            self.assertEqual(3, set_cache_mode.call_count)

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
            conn._unplug_vifs('inst', [1], ignore_errors=True)
            vif_driver.unplug.assert_called_once_with('inst', 1)

    def test_unplug_vifs_reports_errors(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        with mock.patch.object(conn, 'vif_driver') as vif_driver:
            vif_driver.unplug.side_effect = exception.AgentError(
                method='unplug')
            self.assertRaises(exception.AgentError,
                              conn.unplug_vifs, 'inst', [1])
            vif_driver.unplug.assert_called_once_with('inst', 1)

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._unplug_vifs')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._undefine_domain')
    def test_cleanup_pass_with_no_mount_device(self, undefine, unplug):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        conn.firewall_driver = mock.Mock()
        conn._disconnect_volume = mock.Mock()
        fake_inst = {'name': 'foo'}
        fake_bdms = [{'connection_info': 'foo',
                     'mount_device': None}]
        with mock.patch('nova.virt.driver'
                        '.block_device_info_get_mapping',
                        return_value=fake_bdms):
            conn.cleanup('ctxt', fake_inst, 'netinfo', destroy_disks=False)
        self.assertTrue(conn._disconnect_volume.called)

    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._unplug_vifs')
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
            unplug.assert_called_once_with(fake_inst, 'netinfo', True)

    @mock.patch('nova.virt.driver.block_device_info_get_mapping')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.'
                '_get_serial_ports_from_instance')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._undefine_domain')
    def test_cleanup_serial_console_enabled(
            self, undefine, get_ports,
            block_device_info_get_mapping):
        self.flags(enabled="True", group='serial_console')
        instance = 'i1'
        network_info = {}
        bdm_info = {}
        firewall_driver = mock.MagicMock()

        get_ports.return_value = iter([('127.0.0.1', 10000)])
        block_device_info_get_mapping.return_value = ()

        # We want to ensure undefine_domain is called after
        # lookup_domain.
        def undefine_domain(instance):
            get_ports.side_effect = Exception("domain undefined")
        undefine.side_effect = undefine_domain

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())
        conn.firewall_driver = firewall_driver
        conn.cleanup(
            'ctx', instance, network_info,
            block_device_info=bdm_info,
            destroy_disks=False, destroy_vifs=False)

        get_ports.assert_called_once_with(instance)
        undefine.assert_called_once_with(instance)
        firewall_driver.unfilter_instance.assert_called_once_with(
            instance, network_info=network_info)
        block_device_info_get_mapping.assert_called_once_with(bdm_info)

    def test_swap_volume(self):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())

        mock_dom = mock.MagicMock()

        with mock.patch.object(drvr._conn, 'defineXML',
                               create=True) as mock_define:
            xmldoc = "<domain/>"
            srcfile = "/first/path"
            dstfile = "/second/path"

            mock_dom.XMLDesc.return_value = xmldoc
            mock_dom.isPersistent.return_value = True
            mock_dom.blockJobInfo.return_value = {}

            drvr._swap_volume(mock_dom, srcfile, dstfile, 1)

            mock_dom.XMLDesc.assert_called_once_with(
                fakelibvirt.VIR_DOMAIN_XML_INACTIVE |
                fakelibvirt.VIR_DOMAIN_XML_SECURE)
            mock_dom.blockRebase.assert_called_once_with(
                srcfile, dstfile, 0,
                libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY |
                libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT)
            mock_dom.blockResize.assert_called_once_with(
                srcfile, 1 * units.Gi / units.Ki)
            mock_define.assert_called_once_with(xmldoc)

    def test_live_snapshot(self):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())

        mock_dom = mock.MagicMock()

        with contextlib.nested(
                mock.patch.object(drvr._conn, 'defineXML', create=True),
                mock.patch.object(fake_libvirt_utils, 'get_disk_size'),
                mock.patch.object(fake_libvirt_utils, 'get_disk_backing_file'),
                mock.patch.object(fake_libvirt_utils, 'create_cow_image'),
                mock.patch.object(fake_libvirt_utils, 'chown'),
                mock.patch.object(fake_libvirt_utils, 'extract_snapshot'),
        ) as (mock_define, mock_size, mock_backing, mock_create_cow,
              mock_chown, mock_snapshot):

            xmldoc = "<domain/>"
            srcfile = "/first/path"
            dstfile = "/second/path"
            bckfile = "/other/path"
            dltfile = dstfile + ".delta"

            mock_dom.XMLDesc.return_value = xmldoc
            mock_dom.isPersistent.return_value = True
            mock_size.return_value = 1004009
            mock_backing.return_value = bckfile

            drvr._live_snapshot(self.context, self.test_instance, mock_dom,
                                srcfile, dstfile, "qcow2", {})

            mock_dom.XMLDesc.assert_called_once_with(
                fakelibvirt.VIR_DOMAIN_XML_INACTIVE |
                fakelibvirt.VIR_DOMAIN_XML_SECURE)
            mock_dom.blockRebase.assert_called_once_with(
                srcfile, dltfile, 0,
                libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY |
                libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT |
                libvirt.VIR_DOMAIN_BLOCK_REBASE_SHALLOW)

            mock_size.assert_called_once_with(srcfile)
            mock_backing.assert_called_once_with(srcfile, basename=False)
            mock_create_cow.assert_called_once_with(bckfile, dltfile, 1004009)
            mock_chown.assert_called_once_with(dltfile, os.getuid())
            mock_snapshot.assert_called_once_with(dltfile, "qcow2",
                                                  dstfile, "qcow2")
            mock_define.assert_called_once_with(xmldoc)

    @mock.patch.object(greenthread, "spawn")
    def test_live_migration_hostname_valid(self, mock_spawn):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        drvr.live_migration(self.context, self.test_instance,
                            "host1.example.com",
                            lambda x: x,
                            lambda x: x)
        self.assertEqual(1, mock_spawn.call_count)

    @mock.patch.object(greenthread, "spawn")
    @mock.patch.object(fake_libvirt_utils, "is_valid_hostname")
    def test_live_migration_hostname_invalid(self, mock_hostname, mock_spawn):
        drvr = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        mock_hostname.return_value = False
        self.assertRaises(exception.InvalidHostname,
                          drvr.live_migration,
                          self.context, self.test_instance,
                          "foo/?com=/bin/sh",
                          lambda x: x,
                          lambda x: x)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('tempfile.mkstemp')
    @mock.patch('os.close', return_value=None)
    def test_check_instance_shared_storage_local_raw(self,
                                                 mock_close,
                                                 mock_mkstemp,
                                                 mock_exists):
        instance_uuid = str(uuid.uuid4())
        self.flags(images_type='raw', group='libvirt')
        self.flags(instances_path='/tmp')
        mock_mkstemp.return_value = (-1,
                                     '/tmp/{0}/file'.format(instance_uuid))
        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = fake_instance.fake_instance_obj(self.context)
        temp_file = driver.check_instance_shared_storage_local(self.context,
                                                               instance)
        self.assertEqual('/tmp/{0}/file'.format(instance_uuid),
                         temp_file['filename'])

    def test_check_instance_shared_storage_local_rbd(self):
        self.flags(images_type='rbd', group='libvirt')
        driver = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertIsNone(driver.
                          check_instance_shared_storage_local(self.context,
                                                              instance))


class HostStateTestCase(test.NoDBTestCase):

    cpu_info = ('{"vendor": "Intel", "model": "pentium", "arch": "i686", '
                 '"features": ["ssse3", "monitor", "pni", "sse2", "sse", '
                 '"fxsr", "clflush", "pse36", "pat", "cmov", "mca", "pge", '
                 '"mtrr", "sep", "apic"], '
                 '"topology": {"cores": "1", "threads": "1", "sockets": "1"}}')
    instance_caps = [(arch.X86_64, "kvm", "hvm"),
                     (arch.I686, "kvm", "hvm")]
    pci_devices = [{
        "dev_id": "pci_0000_04_00_3",
        "address": "0000:04:10.3",
        "product_id": '1521',
        "vendor_id": '8086',
        "dev_type": 'type-PF',
        "phys_function": None}]
    numa_topology = objects.NUMATopology(
                        cells=[objects.NUMACell(
                            id=1, cpuset=set([1, 2]), memory=1024,
                            cpu_usage=0, memory_usage=0),
                               objects.NUMACell(
                            id=2, cpuset=set([3, 4]), memory=1024,
                            cpu_usage=0, memory_usage=0)])

    class FakeConnection(libvirt_driver.LibvirtDriver):
        """Fake connection object."""
        def __init__(self):
            super(HostStateTestCase.FakeConnection,
                  self).__init__(fake.FakeVirtAPI(), True)

        def _get_vcpu_total(self):
            return 1

        def _get_vcpu_used(self):
            return 0

        def _get_cpu_info(self):
            return HostStateTestCase.cpu_info

        def _get_disk_over_committed_size_total(self):
            return 0

        def _get_local_gb_info(self):
            return {'total': 100, 'used': 20, 'free': 80}

        def _get_memory_mb_total(self):
            return 497

        def _get_memory_mb_used(self):
            return 88

        def _get_hypervisor_type(self):
            return 'QEMU'

        def _get_hypervisor_version(self):
            return 13091

        def _get_hypervisor_hostname(self):
            return 'compute1'

        def get_host_uptime(self):
            return ('10:01:16 up  1:36,  6 users,  '
                    'load average: 0.21, 0.16, 0.19')

        def _get_disk_available_least(self):
            return 13091

        def _get_instance_capabilities(self):
            return HostStateTestCase.instance_caps

        def _get_pci_passthrough_devices(self):
            return jsonutils.dumps(HostStateTestCase.pci_devices)

        def _get_host_numa_topology(self):
            return HostStateTestCase.numa_topology

    def test_update_status(self):
        drvr = HostStateTestCase.FakeConnection()

        stats = drvr.get_available_resource("compute1")
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
                {"vendor": "Intel", "model": "pentium",
                 "arch": arch.I686,
                 "features": ["ssse3", "monitor", "pni", "sse2", "sse",
                              "fxsr", "clflush", "pse36", "pat", "cmov",
                              "mca", "pge", "mtrr", "sep", "apic"],
                 "topology": {"cores": "1", "threads": "1", "sockets": "1"}
                })
        self.assertEqual(stats["disk_available_least"], 80)
        self.assertEqual(jsonutils.loads(stats["pci_passthrough_devices"]),
                         HostStateTestCase.pci_devices)
        self.assertThat(objects.NUMATopology.obj_from_db_obj(
                            stats['numa_topology'])._to_dict(),
                        matchers.DictMatches(
                                HostStateTestCase.numa_topology._to_dict()))


class LibvirtDriverTestCase(test.NoDBTestCase):
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

        sys_meta = {
            'instance_type_memory_mb': 512,
            'instance_type_swap': 0,
            'instance_type_vcpu_weight': None,
            'instance_type_root_gb': 1,
            'instance_type_id': 2,
            'instance_type_name': u'm1.tiny',
            'instance_type_ephemeral_gb': 0,
            'instance_type_rxtx_factor': 1.0,
            'instance_type_flavorid': u'1',
            'instance_type_vcpus': 1
        }

        inst = {}
        inst['id'] = 1
        inst['uuid'] = '52d3b512-1152-431f-a8f7-28f0288a622b'
        inst['os_type'] = 'linux'
        inst['image_ref'] = '1'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type_id'] = 2
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

        return objects.Instance(**inst)

    def test_migrate_disk_and_power_off_exception(self):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .migrate_disk_and_power_off.
        """

        self.counter = 0
        self.checked_shared_storage = False

        def fake_get_instance_disk_info(instance,
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
        flavor_obj = objects.Flavor(**flavor)

        self.assertRaises(AssertionError,
                          self.libvirtconnection.migrate_disk_and_power_off,
                          context.get_admin_context(), ins_ref, '10.0.0.2',
                          flavor_obj, None)

    def _test_migrate_disk_and_power_off(self, flavor_obj):
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

        def fake_get_instance_disk_info(instance,
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

        # dest is different host case
        out = self.libvirtconnection.migrate_disk_and_power_off(
               context.get_admin_context(), ins_ref, '10.0.0.2',
               flavor_obj, None)
        self.assertEqual(out, disk_info_text)

        # dest is same host case
        out = self.libvirtconnection.migrate_disk_and_power_off(
               context.get_admin_context(), ins_ref, '10.0.0.1',
               flavor_obj, None)
        self.assertEqual(out, disk_info_text)

    def test_migrate_disk_and_power_off(self):
        flavor = {'root_gb': 10, 'ephemeral_gb': 20}
        flavor_obj = objects.Flavor(**flavor)

        self._test_migrate_disk_and_power_off(flavor_obj)

    @mock.patch('nova.utils.execute')
    @mock.patch('nova.virt.libvirt.utils.copy_image')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver._destroy')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver.get_host_ip_addr')
    @mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                '.get_instance_disk_info')
    def test_migrate_disk_and_power_off_swap(self, mock_get_disk_info,
                                             get_host_ip_addr,
                                             mock_destroy,
                                             mock_copy_image,
                                             mock_execute):
        """Test for nova.virt.libvirt.libvirt_driver.LivirtConnection
        .migrate_disk_and_power_off.
        """
        self.copy_or_move_swap_called = False

        # 10G root and 512M swap disk
        disk_info = [{'disk_size': 1, 'type': 'qcow2',
                      'virt_disk_size': 10737418240, 'path': '/test/disk',
                      'backing_file': '/base/disk'},
                     {'disk_size': 1, 'type': 'qcow2',
                      'virt_disk_size': 536870912, 'path': '/test/disk.swap',
                      'backing_file': '/base/swap_512'}]
        disk_info_text = jsonutils.dumps(disk_info)
        mock_get_disk_info.return_value = disk_info_text
        get_host_ip_addr.return_value = '10.0.0.1'

        def fake_copy_image(*args, **kwargs):
            # disk.swap should not be touched since it is skipped over
            if '/test/disk.swap' in list(args):
                self.copy_or_move_swap_called = True

        def fake_execute(*args, **kwargs):
            # disk.swap should not be touched since it is skipped over
            if set(['mv', '/test/disk.swap']).issubset(list(args)):
                self.copy_or_move_swap_called = True

        mock_copy_image.side_effect = fake_copy_image
        mock_execute.side_effect = fake_execute

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        # Original instance config
        instance = self._create_instance({'root_gb': 10,
                                          'ephemeral_gb': 0})

        # Re-size fake instance to 20G root and 1024M swap disk
        flavor = {'root_gb': 20, 'ephemeral_gb': 0, 'swap': 1024}
        flavor_obj = objects.Flavor(**flavor)

        # Destination is same host
        out = conn.migrate_disk_and_power_off(context.get_admin_context(),
                                              instance, '10.0.0.1',
                                              flavor_obj, None)

        mock_get_disk_info.assert_called_once_with(instance,
                                                   block_device_info=None)
        self.assertTrue(get_host_ip_addr.called)
        mock_destroy.assert_called_once_with(instance)
        self.assertFalse(self.copy_or_move_swap_called)
        self.assertEqual(disk_info_text, out)

    def test_migrate_disk_and_power_off_lvm(self):
        """Test for nova.virt.libvirt.libvirt_driver.LibvirtConnection
        .migrate_disk_and_power_off.
        """

        self.flags(images_type='lvm', group='libvirt')
        disk_info = [{'type': 'raw', 'path': '/dev/vg/disk',
                      'disk_size': '83886080'},
                     {'type': 'raw', 'path': '/dev/disk.local',
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
        flavor_obj = objects.Flavor(**flavor)

        # Migration is not implemented for LVM backed instances
        self.assertRaises(exception.MigrationPreCheckError,
              self.libvirtconnection.migrate_disk_and_power_off,
              None, ins_ref, '10.0.0.1', flavor_obj, None)

    def test_migrate_disk_and_power_off_resize_error(self):
        instance = self._create_instance()
        flavor = {'root_gb': 5, 'ephemeral_gb': 10}
        flavor_obj = objects.Flavor(**flavor)

        self.assertRaises(
            exception.InstanceFaultRollback,
            self.libvirtconnection.migrate_disk_and_power_off,
            'ctx', instance, '10.0.0.1', flavor_obj, None)

    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_migrate_disk_and_power_off_resize_error_eph(self, mock_get):
        mappings = [
            {
                 'device_name': '/dev/sdb4',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'guest_format': 'swap',
                 'boot_index': -1,
                 'volume_size': 1
             },
             {
                 'device_name': '/dev/sda1',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_type': 'disk',
                 'volume_id': 1,
                 'guest_format': None,
                 'boot_index': 1,
                 'volume_size': 6
             },
             {
                 'device_name': '/dev/sda2',
                 'source_type': 'snapshot',
                 'destination_type': 'volume',
                 'snapshot_id': 1,
                 'device_type': 'disk',
                 'guest_format': None,
                 'boot_index': 0,
                 'volume_size': 4
             },
             {
                 'device_name': '/dev/sda3',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'guest_format': None,
                 'boot_index': -1,
                 'volume_size': 3
             }
        ]
        mock_get.return_value = mappings
        instance = self._create_instance()

        # Old flavor, eph is 20, real disk is 3, target is 2, fail
        flavor = {'root_gb': 10, 'ephemeral_gb': 2}
        flavor_obj = objects.Flavor(**flavor)

        self.assertRaises(
            exception.InstanceFaultRollback,
            self.libvirtconnection.migrate_disk_and_power_off,
            'ctx', instance, '10.0.0.1', flavor_obj, None)

        # Old flavor, eph is 20, real disk is 3, target is 4
        flavor = {'root_gb': 10, 'ephemeral_gb': 4}
        flavor_obj = objects.Flavor(**flavor)
        self._test_migrate_disk_and_power_off(flavor_obj)

    def test_wait_for_running(self):
        def fake_get_info(instance):
            if instance['name'] == "not_found":
                raise exception.InstanceNotFound(instance_id=instance['uuid'])
            elif instance['name'] == "running":
                return hardware.InstanceInfo(state=power_state.RUNNING)
            else:
                return hardware.InstanceInfo(state=power_state.SHUTDOWN)

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

    def test_disk_size_from_instance_disk_info(self):
        inst = {'root_gb': 10, 'ephemeral_gb': 20, 'swap_gb': 30}

        info = {'path': '/path/disk'}
        self.assertEqual(10 * units.Gi,
            self.libvirtconnection._disk_size_from_instance(inst, info))

        info = {'path': '/path/disk.local'}
        self.assertEqual(20 * units.Gi,
            self.libvirtconnection._disk_size_from_instance(inst, info))

        info = {'path': '/path/disk.swap'}
        self.assertEqual(0,
            self.libvirtconnection._disk_size_from_instance(inst, info))

    @mock.patch('nova.utils.execute')
    def test_disk_raw_to_qcow2(self, mock_execute):
        path = '/test/disk'
        _path_qcow = path + '_qcow'

        self.libvirtconnection._disk_raw_to_qcow2(path)
        mock_execute.assert_has_calls([
            mock.call('qemu-img', 'convert', '-f', 'raw',
                      '-O', 'qcow2', path, _path_qcow),
            mock.call('mv', _path_qcow, path)])

    @mock.patch('nova.utils.execute')
    def test_disk_qcow2_to_raw(self, mock_execute):
        path = '/test/disk'
        _path_raw = path + '_raw'

        self.libvirtconnection._disk_qcow2_to_raw(path)
        mock_execute.assert_has_calls([
            mock.call('qemu-img', 'convert', '-f', 'qcow2',
                      '-O', 'raw', path, _path_raw),
            mock.call('mv', _path_raw, path)])

    @mock.patch('nova.virt.disk.api.extend')
    def test_disk_resize_raw(self, mock_extend):
        info = {'type': 'raw', 'path': '/test/disk'}

        self.libvirtconnection._disk_resize(info, 50)
        mock_extend.assert_called_once_with(info['path'], 50, use_cow=False)

    @mock.patch('nova.virt.disk.api.can_resize_image')
    @mock.patch('nova.virt.disk.api.is_image_partitionless')
    @mock.patch('nova.virt.disk.api.extend')
    def test_disk_resize_qcow2(
            self, mock_extend, mock_can_resize, mock_is_partitionless):
        info = {'type': 'qcow2', 'path': '/test/disk'}

        with contextlib.nested(
                mock.patch.object(
                    self.libvirtconnection, '_disk_qcow2_to_raw'),
                mock.patch.object(
                    self.libvirtconnection, '_disk_raw_to_qcow2'))\
        as (mock_disk_qcow2_to_raw, mock_disk_raw_to_qcow2):

            mock_can_resize.return_value = True
            mock_is_partitionless.return_value = True

            self.libvirtconnection._disk_resize(info, 50)

            mock_disk_qcow2_to_raw.assert_called_once_with(info['path'])
            mock_extend.assert_called_once_with(
                info['path'], 50, use_cow=False)
            mock_disk_raw_to_qcow2.assert_called_once_with(info['path'])

    def _test_finish_migration(self, power_on, resize_instance=False):
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
        self.fake_disk_resize_called = False

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
            context, xml, instance, network_info, disk_info,
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
                return hardware.InstanceInfo(state=power_state.RUNNING)
            else:
                return hardware.InstanceInfo(state=power_state.SHUTDOWN)

        def fake_disk_resize(info, size):
            self.fake_disk_resize_called = True

        self.flags(use_cow_images=True)
        self.stubs.Set(self.libvirtconnection, '_disk_resize',
                       fake_disk_resize)
        self.stubs.Set(self.libvirtconnection, '_get_guest_xml', fake_to_xml)
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
                      disk_info_text, [], None,
                      resize_instance, None, power_on)
        self.assertTrue(self.fake_create_domain_called)
        self.assertEqual(
            resize_instance, self.fake_disk_resize_called)

    def test_finish_migration_resize(self):
        self._test_finish_migration(True, resize_instance=True)

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
                return hardware.InstanceInfo(state=power_state.RUNNING)
            else:
                return hardware.InstanceInfo(state=power_state.SHUTDOWN)

        def fake_to_xml(context, instance, network_info, disk_info,
                        image_meta=None, rescue=None,
                        block_device_info=None):
            return ""

        self.stubs.Set(self.libvirtconnection, '_get_guest_xml', fake_to_xml)
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
        self.stubs.Set(compute_utils, 'get_image_metadata', lambda *a: None)

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
        self.stubs.Set(self.libvirtconnection, '_get_guest_xml',
                       lambda *a, **k: None)
        self.stubs.Set(self.libvirtconnection, '_create_domain_and_network',
                       lambda *a, **kw: None)
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

    def test_finish_revert_migration_preserves_disk_bus(self):

        def fake_get_guest_xml(context, instance, network_info, disk_info,
                               block_device_info=None):
            self.assertEqual('ide', disk_info['disk_bus'])

        image_meta = {"properties": {"hw_disk_bus": "ide"}}
        instance = self._create_instance()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        with contextlib.nested(
                mock.patch.object(conn, '_create_domain_and_network'),
                mock.patch.object(compute_utils, 'get_image_metadata',
                                  return_value=image_meta),
                mock.patch.object(conn, '_get_guest_xml',
                                  side_effect=fake_get_guest_xml)):
            conn.finish_revert_migration('', instance, None, power_on=False)

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
        CONF.set_override('policy_dirs', [])
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
        CONF.set_override('policy_dirs', [])
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
        instance = self._create_instance()

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
            instance)

    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.lvm.list_volumes')
    def test_lvm_disks(self, listlvs, exists):
        instance = objects.Instance(uuid='fake-uuid', id=1)
        self.flags(images_volume_group='vols', group='libvirt')
        exists.return_value = True
        listlvs.return_value = ['fake-uuid_foo',
                                'other-uuid_foo']
        disks = self.libvirtconnection._lvm_disks(instance)
        self.assertEqual(['/dev/vols/fake-uuid_foo'], disks)

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
        class ImageBackend(object):
            path = '/path'

            def check_image_exists(self):
                if self.path == '/fail/path':
                    return False
                return True

        def fake_inj_network(*args, **kwds):
            return args[0] or None
        inj_network.side_effect = fake_inj_network

        image_backend = ImageBackend()
        image_backend.path = disk_params[0]

        with mock.patch.object(
                self.libvirtconnection.image_backend,
                'image',
                return_value=image_backend):
            self.flags(inject_partition=0, group='libvirt')

            self.libvirtconnection._inject_data(**driver_params)

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

    def test_inject_not_exist_image(self):
        driver_params = self._test_inject_data_default_driver_params()
        disk_params = [
            '/fail/path',  # injection_path
            'key-content',  # key
            None,  # net
            None,  # metadata
            None,  # admin_pass
            None,  # files
        ]
        self._test_inject_data(driver_params, disk_params, called=False)

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
        self.mox.StubOutWithMock(objects.Flavor, 'get_by_id')

        self.libvirtconnection._lookup_by_name(
            'instance-00000001').AndReturn(domain)
        if method == 'attach_interface':
            self.libvirtconnection.firewall_driver.setup_basic_filtering(
                instance, [network_info[0]])

        fake_flavor = instance.get_flavor()

        objects.Flavor.get_by_id(mox.IgnoreArg(), 2).AndReturn(fake_flavor)

        if method == 'attach_interface':
            fake_image_meta = {'id': instance['image_ref']}
        elif method == 'detach_interface':
            fake_image_meta = None
        expected = self.libvirtconnection.vif_driver.get_config(
            instance, network_info[0], fake_image_meta, fake_flavor,
            CONF.libvirt.virt_type)

        self.mox.StubOutWithMock(self.libvirtconnection.vif_driver,
                                 'get_config')
        self.libvirtconnection.vif_driver.get_config(
            instance, network_info[0],
            fake_image_meta,
            mox.IsA(objects.Flavor),
            CONF.libvirt.virt_type).AndReturn(expected)
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

    def test_rescue(self):
        instance = self._create_instance({'config_drive': None})
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "</devices></domain>")
        network_info = _fake_network_info(self.stubs, 1)

        self.mox.StubOutWithMock(self.libvirtconnection,
                                     '_get_existing_domain_xml')
        self.mox.StubOutWithMock(libvirt_utils, 'write_to_file')
        self.mox.StubOutWithMock(imagebackend.Backend, 'image')
        self.mox.StubOutWithMock(imagebackend.Image, 'cache')
        self.mox.StubOutWithMock(self.libvirtconnection, '_get_guest_xml')
        self.mox.StubOutWithMock(self.libvirtconnection, '_destroy')
        self.mox.StubOutWithMock(self.libvirtconnection, '_create_domain')

        self.libvirtconnection._get_existing_domain_xml(mox.IgnoreArg(),
                        mox.IgnoreArg()).MultipleTimes().AndReturn(dummyxml)
        libvirt_utils.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        libvirt_utils.write_to_file(mox.IgnoreArg(), mox.IgnoreArg(),
                               mox.IgnoreArg())
        imagebackend.Backend.image(instance, 'kernel.rescue', 'raw'
                                        ).AndReturn(fake_imagebackend.Raw())
        imagebackend.Backend.image(instance, 'ramdisk.rescue', 'raw'
                                        ).AndReturn(fake_imagebackend.Raw())
        imagebackend.Backend.image(instance, 'disk.rescue', 'default'
                                        ).AndReturn(fake_imagebackend.Raw())
        imagebackend.Image.cache(context=mox.IgnoreArg(),
                                fetch_func=mox.IgnoreArg(),
                                filename=mox.IgnoreArg(),
                                image_id=mox.IgnoreArg(),
                                project_id=mox.IgnoreArg(),
                                user_id=mox.IgnoreArg()).MultipleTimes()

        imagebackend.Image.cache(context=mox.IgnoreArg(),
                                fetch_func=mox.IgnoreArg(),
                                filename=mox.IgnoreArg(),
                                image_id=mox.IgnoreArg(),
                                project_id=mox.IgnoreArg(),
                                size=None, user_id=mox.IgnoreArg())

        image_meta = {'id': 'fake', 'name': 'fake'}
        self.libvirtconnection._get_guest_xml(mox.IgnoreArg(), instance,
                                    network_info, mox.IgnoreArg(),
                                    image_meta, rescue=mox.IgnoreArg(),
                                    write_to_disk=mox.IgnoreArg()
                                    ).AndReturn(dummyxml)

        self.libvirtconnection._destroy(instance)
        self.libvirtconnection._create_domain(mox.IgnoreArg())

        self.mox.ReplayAll()

        rescue_password = 'fake_password'

        self.libvirtconnection.rescue(self.context, instance,
                    network_info, image_meta, rescue_password)
        self.mox.VerifyAll()

    @mock.patch(
        'nova.virt.configdrive.ConfigDriveBuilder.add_instance_metadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder.make_drive')
    def test_rescue_config_drive(self, mock_make, mock_add):
        instance = self._create_instance()
        uuid = instance.uuid
        configdrive_path = uuid + '/disk.config.rescue'
        dummyxml = ("<domain type='kvm'><name>instance-0000000a</name>"
                    "<devices>"
                    "<disk type='file'><driver name='qemu' type='raw'/>"
                    "<source file='/test/disk'/>"
                    "<target dev='vda' bus='virtio'/></disk>"
                    "<disk type='file'><driver name='qemu' type='qcow2'/>"
                    "<source file='/test/disk.local'/>"
                    "<target dev='vdb' bus='virtio'/></disk>"
                    "</devices></domain>")
        network_info = _fake_network_info(self.stubs, 1)

        self.mox.StubOutWithMock(self.libvirtconnection,
                                    '_get_existing_domain_xml')
        self.mox.StubOutWithMock(libvirt_utils, 'write_to_file')
        self.mox.StubOutWithMock(imagebackend.Backend, 'image')
        self.mox.StubOutWithMock(imagebackend.Image, 'cache')
        self.mox.StubOutWithMock(instance_metadata.InstanceMetadata,
                                                            '__init__')
        self.mox.StubOutWithMock(self.libvirtconnection, '_get_guest_xml')
        self.mox.StubOutWithMock(self.libvirtconnection, '_destroy')
        self.mox.StubOutWithMock(self.libvirtconnection, '_create_domain')

        self.libvirtconnection._get_existing_domain_xml(mox.IgnoreArg(),
                    mox.IgnoreArg()).MultipleTimes().AndReturn(dummyxml)
        libvirt_utils.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        libvirt_utils.write_to_file(mox.IgnoreArg(), mox.IgnoreArg(),
                                    mox.IgnoreArg())

        imagebackend.Backend.image(instance, 'kernel.rescue', 'raw'
                                    ).AndReturn(fake_imagebackend.Raw())
        imagebackend.Backend.image(instance, 'ramdisk.rescue', 'raw'
                                    ).AndReturn(fake_imagebackend.Raw())
        imagebackend.Backend.image(instance, 'disk.rescue', 'default'
                                    ).AndReturn(fake_imagebackend.Raw())

        imagebackend.Image.cache(context=mox.IgnoreArg(),
                                fetch_func=mox.IgnoreArg(),
                                filename=mox.IgnoreArg(),
                                image_id=mox.IgnoreArg(),
                                project_id=mox.IgnoreArg(),
                                user_id=mox.IgnoreArg()).MultipleTimes()

        imagebackend.Image.cache(context=mox.IgnoreArg(),
                                fetch_func=mox.IgnoreArg(),
                                filename=mox.IgnoreArg(),
                                image_id=mox.IgnoreArg(),
                                project_id=mox.IgnoreArg(),
                                size=None, user_id=mox.IgnoreArg())

        instance_metadata.InstanceMetadata.__init__(mox.IgnoreArg(),
                                            content=mox.IgnoreArg(),
                                            extra_md=mox.IgnoreArg(),
                                            network_info=mox.IgnoreArg())
        image_meta = {'id': 'fake', 'name': 'fake'}
        self.libvirtconnection._get_guest_xml(mox.IgnoreArg(), instance,
                                network_info, mox.IgnoreArg(),
                                image_meta, rescue=mox.IgnoreArg(),
                                write_to_disk=mox.IgnoreArg()
                                ).AndReturn(dummyxml)
        self.libvirtconnection._destroy(instance)
        self.libvirtconnection._create_domain(mox.IgnoreArg())

        self.mox.ReplayAll()

        rescue_password = 'fake_password'

        self.libvirtconnection.rescue(self.context, instance, network_info,
                                                image_meta, rescue_password)
        self.mox.VerifyAll()

        mock_add.assert_any_call(mock.ANY)
        expected_call = [mock.call(os.path.join(CONF.instances_path,
                                                configdrive_path))]
        mock_make.assert_has_calls(expected_call)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files(self, get_instance_path, exists, exe,
                                   shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        exists.side_effect = [False, False, True, False]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        exe.assert_called_with('mv', '/path', '/path_del')
        shutil.assert_called_with('/path_del')
        self.assertTrue(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_resize(self, get_instance_path, exists,
                                          exe, shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        nova.utils.execute.side_effect = [Exception(), None]
        exists.side_effect = [False, False, True, False]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        expected = [mock.call('mv', '/path', '/path_del'),
                    mock.call('mv', '/path_resize', '/path_del')]
        self.assertEqual(expected, exe.mock_calls)
        shutil.assert_called_with('/path_del')
        self.assertTrue(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_failed(self, get_instance_path, exists, exe,
                                          shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        exists.side_effect = [False, False, True, True]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        exe.assert_called_with('mv', '/path', '/path_del')
        shutil.assert_called_with('/path_del')
        self.assertFalse(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_mv_failed(self, get_instance_path, exists,
                                             exe, shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        nova.utils.execute.side_effect = Exception()
        exists.side_effect = [True, True]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        expected = [mock.call('mv', '/path', '/path_del'),
                    mock.call('mv', '/path_resize', '/path_del')] * 2
        self.assertEqual(expected, exe.mock_calls)
        self.assertFalse(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_resume(self, get_instance_path, exists,
                                             exe, shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        nova.utils.execute.side_effect = Exception()
        exists.side_effect = [False, False, True, False]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        expected = [mock.call('mv', '/path', '/path_del'),
                    mock.call('mv', '/path_resize', '/path_del')] * 2
        self.assertEqual(expected, exe.mock_calls)
        self.assertTrue(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_none(self, get_instance_path, exists,
                                        exe, shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        nova.utils.execute.side_effect = Exception()
        exists.side_effect = [False, False, False, False]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        expected = [mock.call('mv', '/path', '/path_del'),
                    mock.call('mv', '/path_resize', '/path_del')] * 2
        self.assertEqual(expected, exe.mock_calls)
        self.assertEqual(0, len(shutil.mock_calls))
        self.assertTrue(result)

    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    @mock.patch('nova.virt.libvirt.utils.get_instance_path')
    def test_delete_instance_files_concurrent(self, get_instance_path, exists,
                                              exe, shutil):
        lv = self.libvirtconnection
        get_instance_path.return_value = '/path'
        instance = objects.Instance(uuid='fake-uuid', id=1)

        nova.utils.execute.side_effect = [Exception(), Exception(), None]
        exists.side_effect = [False, False, True, False]

        result = lv.delete_instance_files(instance)
        get_instance_path.assert_called_with(instance)
        expected = [mock.call('mv', '/path', '/path_del'),
                    mock.call('mv', '/path_resize', '/path_del')]
        expected.append(expected[0])
        self.assertEqual(expected, exe.mock_calls)
        shutil.assert_called_with('/path_del')
        self.assertTrue(result)

    def _assert_on_id_map(self, idmap, klass, start, target, count):
        self.assertIsInstance(idmap, klass)
        self.assertEqual(start, idmap.start)
        self.assertEqual(target, idmap.target)
        self.assertEqual(count, idmap.count)

    def test_get_id_maps(self):
        self.flags(virt_type="lxc", group="libvirt")
        CONF.libvirt.virt_type = "lxc"
        CONF.libvirt.uid_maps = ["0:10000:1", "1:20000:10"]
        CONF.libvirt.gid_maps = ["0:10000:1", "1:20000:10"]

        idmaps = self.libvirtconnection._get_guest_idmaps()

        self.assertEqual(len(idmaps), 4)
        self._assert_on_id_map(idmaps[0],
                               vconfig.LibvirtConfigGuestUIDMap,
                               0, 10000, 1)
        self._assert_on_id_map(idmaps[1],
                               vconfig.LibvirtConfigGuestUIDMap,
                               1, 20000, 10)
        self._assert_on_id_map(idmaps[2],
                               vconfig.LibvirtConfigGuestGIDMap,
                               0, 10000, 1)
        self._assert_on_id_map(idmaps[3],
                               vconfig.LibvirtConfigGuestGIDMap,
                               1, 20000, 10)

    def test_get_id_maps_not_lxc(self):
        CONF.libvirt.uid_maps = ["0:10000:1", "1:20000:10"]
        CONF.libvirt.gid_maps = ["0:10000:1", "1:20000:10"]

        idmaps = self.libvirtconnection._get_guest_idmaps()

        self.assertEqual(0, len(idmaps))

    def test_get_id_maps_only_uid(self):
        self.flags(virt_type="lxc", group="libvirt")
        CONF.libvirt.uid_maps = ["0:10000:1", "1:20000:10"]
        CONF.libvirt.gid_maps = []

        idmaps = self.libvirtconnection._get_guest_idmaps()

        self.assertEqual(2, len(idmaps))
        self._assert_on_id_map(idmaps[0],
                               vconfig.LibvirtConfigGuestUIDMap,
                               0, 10000, 1)
        self._assert_on_id_map(idmaps[1],
                               vconfig.LibvirtConfigGuestUIDMap,
                               1, 20000, 10)

    def test_get_id_maps_only_gid(self):
        self.flags(virt_type="lxc", group="libvirt")
        CONF.libvirt.uid_maps = []
        CONF.libvirt.gid_maps = ["0:10000:1", "1:20000:10"]

        idmaps = self.libvirtconnection._get_guest_idmaps()

        self.assertEqual(2, len(idmaps))
        self._assert_on_id_map(idmaps[0],
                               vconfig.LibvirtConfigGuestGIDMap,
                               0, 10000, 1)
        self._assert_on_id_map(idmaps[1],
                               vconfig.LibvirtConfigGuestGIDMap,
                               1, 20000, 10)

    def test_instance_on_disk(self):
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(uuid='fake-uuid', id=1)
        self.assertFalse(conn.instance_on_disk(instance))

    def test_instance_on_disk_rbd(self):
        self.flags(images_type='rbd', group='libvirt')
        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        instance = objects.Instance(uuid='fake-uuid', id=1)
        self.assertTrue(conn.instance_on_disk(instance))

    @mock.patch("nova.objects.Flavor.get_by_id")
    @mock.patch("nova.compute.utils.get_image_metadata")
    def test_prepare_args_for_get_config(self, mock_image, mock_get):
        instance = self._create_instance()

        conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI())

        def fake_get_by_id(context, id):
            self.assertEqual('yes', context.read_deleted)

        mock_get.side_effect = fake_get_by_id

        conn._prepare_args_for_get_config(self.context, instance)

        mock_get.assert_called_once_with(self.context,
                                         instance['instance_type_id'])


class LibvirtVolumeUsageTestCase(test.NoDBTestCase):
    """Test for LibvirtDriver.get_all_volume_usage."""

    def setUp(self):
        super(LibvirtVolumeUsageTestCase, self).setUp()
        self.conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.c = context.get_admin_context()

        self.ins_ref = objects.Instance(
            id=1729,
            uuid='875a8070-d0b9-4949-8b31-104d125c9a64'
        )

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
                           'rd_req': 169L, 'wr_bytes': 0L},
                           {'volume': 2,
                            'instance': self.ins_ref,
                            'rd_bytes': 688640L, 'wr_req': 0L,
                            'rd_req': 169L, 'wr_bytes': 0L}]
        self.assertEqual(vol_usage, expected_usage)

    def test_get_all_volume_usage_device_not_found(self):
        def fake_lookup(instance_name):
            raise libvirt.libvirtError('invalid path')

        self.stubs.Set(self.conn, '_lookup_by_name', fake_lookup)
        vol_usage = self.conn.get_all_volume_usage(self.c,
              [dict(instance=self.ins_ref, instance_bdms=self.bdms)])
        self.assertEqual(vol_usage, [])


class LibvirtNonblockingTestCase(test.NoDBTestCase):
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


class LibvirtVolumeSnapshotTestCase(test.NoDBTestCase):
    """Tests for libvirtDriver.volume_snapshot_create/delete."""

    def setUp(self):
        super(LibvirtVolumeSnapshotTestCase, self).setUp()

        self.conn = libvirt_driver.LibvirtDriver(fake.FakeVirtAPI(), False)
        self.c = context.get_admin_context()

        self.flags(instance_name_template='instance-%s')
        self.flags(qemu_allowed_storage_drivers=[], group='libvirt')

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

        # alternate domain info with network-backed snapshot chain
        self.dom_netdisk_xml = """
              <domain type='kvm'>
                <devices>
                  <disk type='file'>
                    <source file='disk1_file'/>
                    <target dev='vda' bus='virtio'/>
                    <serial>0e38683e-f0af-418f-a3f1-6b67eaffffff</serial>
                  </disk>
                  <disk type='network' device='disk'>
                    <driver name='qemu' type='qcow2'/>
                    <source protocol='gluster' name='vol1/root.img'>
                      <host name='server1' port='24007'/>
                    </source>
                    <backingStore type='network' index='1'>
                      <driver name='qemu' type='qcow2'/>
                      <source protocol='gluster' name='vol1/snap.img'>
                        <host name='server1' port='24007'/>
                      </source>
                      <backingStore type='network' index='2'>
                        <driver name='qemu' type='qcow2'/>
                        <source protocol='gluster' name='vol1/snap-b.img'>
                          <host name='server1' port='24007'/>
                        </source>
                        <backingStore/>
                      </backingStore>
                    </backingStore>
                    <target dev='vdb' bus='virtio'/>
                    <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
                  </disk>
                </devices>
              </domain>
        """

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

        self.delete_info_netdisk = {'type': 'qcow2',
                                    'file_to_merge': 'snap.img',
                                    'merge_target_file': 'root.img'}

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
        """Test snapshot creation with file-based disk."""
        self.flags(instance_name_template='instance-%s')
        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')

        instance = objects.Instance(**self.inst)

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
           '    <disk name="vdb" snapshot="no"/>\n'
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
                                          self.volume_uuid, new_file)

        self.mox.VerifyAll()

    def test_volume_snapshot_create_libgfapi(self, quiesce=True):
        """Test snapshot creation with libgfapi network disk."""
        self.flags(instance_name_template = 'instance-%s')
        self.flags(qemu_allowed_storage_drivers = ['gluster'], group='libvirt')
        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')

        self.dom_xml = """
              <domain type='kvm'>
                <devices>
                  <disk type='file'>
                    <source file='disk1_file'/>
                    <target dev='vda' bus='virtio'/>
                    <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
                  </disk>
                  <disk type='block'>
                    <source protocol='gluster' name='gluster1/volume-1234'>
                      <host name='127.3.4.5' port='24007'/>
                    </source>
                    <target dev='vdb' bus='virtio' serial='1234'/>
                  </disk>
                </devices>
              </domain>"""

        instance = objects.Instance(**self.inst)

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
           '    <disk name="vdb" snapshot="no"/>\n'
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
                                          self.volume_uuid, new_file)

        self.mox.VerifyAll()

    def test_volume_snapshot_create_noquiesce(self):
        self.test_volume_snapshot_create(quiesce=False)

    def test_volume_snapshot_create_outer_success(self):
        instance = objects.Instance(**self.inst)

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_create')

        self.conn._lookup_by_name('instance-1').AndReturn(domain)

        self.conn._volume_snapshot_create(self.c,
                                          instance,
                                          domain,
                                          self.volume_uuid,
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
        instance = objects.Instance(**self.inst)

        domain = FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn, '_volume_snapshot_create')

        self.conn._lookup_by_name('instance-1').AndReturn(domain)

        self.conn._volume_snapshot_create(self.c,
                                          instance,
                                          domain,
                                          self.volume_uuid,
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

        instance = objects.Instance(**self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn._host, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn._host.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockRebase('vda', 'snap.img', 0, 0)

        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1000, 'end': 1000})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id, self.delete_info_1)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_2(self):
        """Deleting older snapshot -- blockCommit."""

        instance = objects.Instance(**self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeVirtDomain(fake_xml=self.dom_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn._host, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn._host.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockCommit('vda', 'other-snap.img', 'snap.img', 0, 0)

        domain.blockJobInfo('vda', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vda', 0).AndReturn({})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id, self.delete_info_2)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_outer_success(self):
        instance = objects.Instance(**self.inst)
        snapshot_id = 'snapshot-1234'

        FakeVirtDomain(fake_xml=self.dom_xml)

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
        instance = objects.Instance(**self.inst)
        snapshot_id = '1234-9876'

        FakeVirtDomain(fake_xml=self.dom_xml)

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
        instance = objects.Instance(**self.inst)

        FakeVirtDomain(fake_xml=self.dom_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn, '_volume_api')
        self.mox.StubOutWithMock(self.conn._host, 'has_min_version')

        self.conn._host.has_min_version(mox.IgnoreArg()).AndReturn(True)

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

    def test_volume_snapshot_delete_netdisk_1(self):
        """Delete newest snapshot -- blockRebase for libgfapi/network disk."""

        class FakeNetdiskDomain(FakeVirtDomain):
            def __init__(self, *args, **kwargs):
                super(FakeNetdiskDomain, self).__init__(*args, **kwargs)

            def XMLDesc(self, *args):
                return self.dom_netdisk_xml

        # Ensure the libvirt lib has VIR_DOMAIN_BLOCK_COMMIT_RELATIVE
        self.stubs.Set(libvirt_driver, 'libvirt', fakelibvirt)

        instance = objects.Instance(**self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeNetdiskDomain(fake_xml=self.dom_netdisk_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_netdisk_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn._host, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn._host.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockRebase('vdb', 'vdb[1]', 0, 0)

        domain.blockJobInfo('vdb', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vdb', 0).AndReturn({'cur': 1000, 'end': 1000})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id, self.delete_info_1)

        self.mox.VerifyAll()

    def test_volume_snapshot_delete_netdisk_2(self):
        """Delete older snapshot -- blockCommit for libgfapi/network disk."""

        class FakeNetdiskDomain(FakeVirtDomain):
            def __init__(self, *args, **kwargs):
                super(FakeNetdiskDomain, self).__init__(*args, **kwargs)

            def XMLDesc(self, *args):
                return self.dom_netdisk_xml

        # Ensure the libvirt lib has VIR_DOMAIN_BLOCK_COMMIT_RELATIVE
        self.stubs.Set(libvirt_driver, 'libvirt', fakelibvirt)

        instance = objects.Instance(**self.inst)
        snapshot_id = 'snapshot-1234'

        domain = FakeNetdiskDomain(fake_xml=self.dom_netdisk_xml)
        self.mox.StubOutWithMock(domain, 'XMLDesc')
        domain.XMLDesc(0).AndReturn(self.dom_netdisk_xml)

        self.mox.StubOutWithMock(self.conn, '_lookup_by_name')
        self.mox.StubOutWithMock(self.conn._host, 'has_min_version')
        self.mox.StubOutWithMock(domain, 'blockRebase')
        self.mox.StubOutWithMock(domain, 'blockCommit')
        self.mox.StubOutWithMock(domain, 'blockJobInfo')

        self.conn._lookup_by_name('instance-%s' % instance['id']).\
            AndReturn(domain)
        self.conn._host.has_min_version(mox.IgnoreArg()).AndReturn(True)

        domain.blockCommit('vdb', 'vdb[0]', 'vdb[1]', 0,
                           fakelibvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE)

        domain.blockJobInfo('vdb', 0).AndReturn({'cur': 1, 'end': 1000})
        domain.blockJobInfo('vdb', 0).AndReturn({'cur': 1000, 'end': 1000})

        self.mox.ReplayAll()

        self.conn._volume_snapshot_delete(self.c, instance, self.volume_uuid,
                                          snapshot_id,
                                          self.delete_info_netdisk)

        self.mox.VerifyAll()
