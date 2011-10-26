# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 OpenStack LLC
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

import copy
import eventlet
import mox
import os
import re
import shutil
import sys
import tempfile

from xml.etree.ElementTree import fromstring as xml_to_tree
from xml.dom.minidom import parseString as xml_to_dom

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.api.ec2 import cloud
from nova.compute import power_state
from nova.compute import vm_states
from nova.virt.libvirt import connection
from nova.virt.libvirt import firewall

libvirt = None
FLAGS = flags.FLAGS


def _concurrency(wait, done, target):
    wait.wait()
    done.send()


class FakeVirDomainSnapshot(object):

    def __init__(self, dom=None):
        self.dom = dom

    def delete(self, flags):
        pass


class FakeVirtDomain(object):

    def __init__(self, fake_xml=None):
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

    def snapshotCreateXML(self, *args):
        return FakeVirDomainSnapshot(self)

    def createWithFlags(self, launch_flags):
        pass

    def XMLDesc(self, *args):
        return self._fake_dom_xml


def _create_network_info(count=1, ipv6=None):
    if ipv6 is None:
        ipv6 = FLAGS.use_ipv6
    fake = 'fake'
    fake_ip = '10.11.12.13'
    fake_ip_2 = '0.0.0.1'
    fake_ip_3 = '0.0.0.1'
    fake_vlan = 100
    fake_bridge_interface = 'eth0'
    network = {'bridge': fake,
               'cidr': fake_ip,
               'cidr_v6': fake_ip,
               'gateway_v6': fake,
               'vlan': fake_vlan,
               'bridge_interface': fake_bridge_interface}
    mapping = {'mac': fake,
               'dhcp_server': '10.0.0.1',
               'gateway': fake,
               'gateway6': fake,
               'ips': [{'ip': fake_ip}, {'ip': fake_ip}]}
    if ipv6:
        mapping['ip6s'] = [{'ip': fake_ip},
                           {'ip': fake_ip_2},
                           {'ip': fake_ip_3}]
    return [(network, mapping) for x in xrange(0, count)]


def _setup_networking(instance_id, ip='1.2.3.4', mac='56:12:12:12:12:12'):
    ctxt = context.get_admin_context()
    network_ref = db.project_get_networks(ctxt,
                                           'fake',
                                           associate=True)[0]
    vif = {'address': mac,
           'network_id': network_ref['id'],
           'instance_id': instance_id}
    vif_ref = db.virtual_interface_create(ctxt, vif)

    fixed_ip = {'address': ip,
                'network_id': network_ref['id'],
                'virtual_interface_id': vif_ref['id']}
    db.fixed_ip_create(ctxt, fixed_ip)
    db.fixed_ip_update(ctxt, ip, {'allocated': True,
                                  'instance_id': instance_id})


class CacheConcurrencyTestCase(test.TestCase):
    def setUp(self):
        super(CacheConcurrencyTestCase, self).setUp()
        self.flags(instances_path='nova.compute.manager')

        def fake_exists(fname):
            basedir = os.path.join(FLAGS.instances_path, '_base')
            if fname == basedir:
                return True
            return False

        def fake_execute(*args, **kwargs):
            pass

        self.stubs.Set(os.path, 'exists', fake_exists)
        self.stubs.Set(utils, 'execute', fake_execute)

    def test_same_fname_concurrency(self):
        """Ensures that the same fname cache runs at a sequentially"""
        conn = connection.LibvirtConnection
        wait1 = eventlet.event.Event()
        done1 = eventlet.event.Event()
        eventlet.spawn(conn._cache_image, _concurrency,
                       'target', 'fname', False, wait1, done1)
        wait2 = eventlet.event.Event()
        done2 = eventlet.event.Event()
        eventlet.spawn(conn._cache_image, _concurrency,
                       'target', 'fname', False, wait2, done2)
        wait2.send()
        eventlet.sleep(0)
        try:
            self.assertFalse(done2.ready())
        finally:
            wait1.send()
        done1.wait()
        eventlet.sleep(0)
        self.assertTrue(done2.ready())

    def test_different_fname_concurrency(self):
        """Ensures that two different fname caches are concurrent"""
        conn = connection.LibvirtConnection
        wait1 = eventlet.event.Event()
        done1 = eventlet.event.Event()
        eventlet.spawn(conn._cache_image, _concurrency,
                       'target', 'fname2', False, wait1, done1)
        wait2 = eventlet.event.Event()
        done2 = eventlet.event.Event()
        eventlet.spawn(conn._cache_image, _concurrency,
                       'target', 'fname1', False, wait2, done2)
        wait2.send()
        eventlet.sleep(0)
        try:
            self.assertTrue(done2.ready())
        finally:
            wait1.send()
            eventlet.sleep(0)


class LibvirtConnTestCase(test.TestCase):

    def setUp(self):
        super(LibvirtConnTestCase, self).setUp()
        connection._late_load_cheetah()
        self.flags(fake_call=True)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.network = utils.import_object(FLAGS.network_manager)
        self.context = context.get_admin_context()
        self.flags(instances_path='')
        self.call_libvirt_dependant_setup = False
        self.test_ip = '10.11.12.13'

    test_instance = {'memory_kb': '1024000',
                     'basepath': '/some/path',
                     'bridge_name': 'br100',
                     'vcpus': 2,
                     'project_id': 'fake',
                     'bridge': 'br101',
                     'image_ref': '123456',
                     'local_gb': 20,
                     'instance_type_id': '5'}  # m1.small

    def lazy_load_library_exists(self):
        """check if libvirt is available."""
        # try to connect libvirt. if fail, skip test.
        try:
            import libvirt
            import libxml2
        except ImportError:
            return False
        global libvirt
        libvirt = __import__('libvirt')
        connection.libvirt = __import__('libvirt')
        connection.libxml2 = __import__('libxml2')
        return True

    def create_fake_libvirt_mock(self, **kwargs):
        """Defining mocks for LibvirtConnection(libvirt is not used)."""

        # A fake libvirt.virConnect
        class FakeLibvirtConnection(object):
            def defineXML(self, xml):
                return FakeVirtDomain()

        # A fake connection.IptablesFirewallDriver
        class FakeIptablesFirewallDriver(object):

            def __init__(self, **kwargs):
                pass

            def setattr(self, key, val):
                self.__setattr__(key, val)

        # A fake VIF driver
        class FakeVIFDriver(object):

            def __init__(self, **kwargs):
                pass

            def setattr(self, key, val):
                self.__setattr__(key, val)

            def plug(self, instance, network, mapping):
                return {
                    'id': 'fake',
                    'bridge_name': 'fake',
                    'mac_address': 'fake',
                    'ip_address': 'fake',
                    'dhcp_server': 'fake',
                    'extra_params': 'fake',
                }

        # Creating mocks
        fake = FakeLibvirtConnection()
        fakeip = FakeIptablesFirewallDriver
        fakevif = FakeVIFDriver()
        # Customizing above fake if necessary
        for key, val in kwargs.items():
            fake.__setattr__(key, val)

        # Inevitable mocks for connection.LibvirtConnection
        self.mox.StubOutWithMock(connection.utils, 'import_class')
        connection.utils.import_class(mox.IgnoreArg()).AndReturn(fakeip)
        self.mox.StubOutWithMock(connection.utils, 'import_object')
        connection.utils.import_object(mox.IgnoreArg()).AndReturn(fakevif)
        self.mox.StubOutWithMock(connection.LibvirtConnection, '_conn')
        connection.LibvirtConnection._conn = fake

    def fake_lookup(self, instance_name):
        return FakeVirtDomain()

    def fake_execute(self, *args):
        open(args[-1], "a").close()

    def create_service(self, **kwargs):
        service_ref = {'host': kwargs.get('host', 'dummy'),
                       'binary': 'nova-compute',
                       'topic': 'compute',
                       'report_count': 0,
                       'availability_zone': 'zone'}

        return db.service_create(context.get_admin_context(), service_ref)

    def test_preparing_xml_info(self):
        conn = connection.LibvirtConnection(True)
        instance_ref = db.instance_create(self.context, self.test_instance)

        result = conn._prepare_xml_info(instance_ref,
                                        _create_network_info(),
                                        False)
        self.assertTrue(len(result['nics']) == 1)

        result = conn._prepare_xml_info(instance_ref,
                                        _create_network_info(2),
                                        False)
        self.assertTrue(len(result['nics']) == 2)

    def test_xml_and_uri_no_ramdisk_no_kernel(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_uri(instance_data,
                                expect_kernel=False, expect_ramdisk=False)

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
                                expect_ramdisk=True, rescue=True)

    def test_lxc_container_and_uri(self):
        instance_data = dict(self.test_instance)
        self._check_xml_and_container(instance_data)

    def test_snapshot_in_ami_format(self):
        if not self.lazy_load_library_exists():
            return

        self.flags(image_service='nova.image.fake.FakeImageService')

        # Start test
        image_service = utils.import_object(FLAGS.image_service)

        # Assign image_ref = 3 from nova/images/fakes for testing
        # ami image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = "3"

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

        self.mox.StubOutWithMock(connection.LibvirtConnection, '_conn')
        connection.LibvirtConnection._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(connection.utils, 'execute')
        connection.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = connection.LibvirtConnection(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'])

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertEquals(snapshot['properties']['image_state'], 'available')
        self.assertEquals(snapshot['status'], 'active')
        self.assertEquals(snapshot['disk_format'], 'ami')
        self.assertEquals(snapshot['name'], snapshot_name)

    def test_snapshot_in_raw_format(self):
        if not self.lazy_load_library_exists():
            return

        self.flags(image_service='nova.image.fake.FakeImageService')

        # Start test
        image_service = utils.import_object(FLAGS.image_service)

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

        self.mox.StubOutWithMock(connection.LibvirtConnection, '_conn')
        connection.LibvirtConnection._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(connection.utils, 'execute')
        connection.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = connection.LibvirtConnection(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'])

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertEquals(snapshot['properties']['image_state'], 'available')
        self.assertEquals(snapshot['status'], 'active')
        self.assertEquals(snapshot['disk_format'], 'raw')
        self.assertEquals(snapshot['name'], snapshot_name)

    def test_snapshot_in_qcow2_format(self):
        if not self.lazy_load_library_exists():
            return

        self.flags(image_service='nova.image.fake.FakeImageService')
        self.flags(snapshot_image_format='qcow2')

        # Start test
        image_service = utils.import_object(FLAGS.image_service)

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

        self.mox.StubOutWithMock(connection.LibvirtConnection, '_conn')
        connection.LibvirtConnection._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(connection.utils, 'execute')
        connection.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = connection.LibvirtConnection(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'])

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertEquals(snapshot['properties']['image_state'], 'available')
        self.assertEquals(snapshot['status'], 'active')
        self.assertEquals(snapshot['disk_format'], 'qcow2')
        self.assertEquals(snapshot['name'], snapshot_name)

    def test_snapshot_no_image_architecture(self):
        if not self.lazy_load_library_exists():
            return

        self.flags(image_service='nova.image.fake.FakeImageService')

        # Start test
        image_service = utils.import_object(FLAGS.image_service)

        # Assign image_ref = 2 from nova/images/fakes for testing different
        # base image
        test_instance = copy.deepcopy(self.test_instance)
        test_instance["image_ref"] = "2"

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

        self.mox.StubOutWithMock(connection.LibvirtConnection, '_conn')
        connection.LibvirtConnection._conn.lookupByName = self.fake_lookup
        self.mox.StubOutWithMock(connection.utils, 'execute')
        connection.utils.execute = self.fake_execute

        self.mox.ReplayAll()

        conn = connection.LibvirtConnection(False)
        conn.snapshot(self.context, instance_ref, recv_meta['id'])

        snapshot = image_service.show(context, recv_meta['id'])
        self.assertEquals(snapshot['properties']['image_state'], 'available')
        self.assertEquals(snapshot['status'], 'active')
        self.assertEquals(snapshot['name'], snapshot_name)

    def test_attach_invalid_device(self):
        self.create_fake_libvirt_mock()
        connection.LibvirtConnection._conn.lookupByName = self.fake_lookup
        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        self.assertRaises(exception.InvalidDevicePath,
                          conn.attach_volume,
                          "fake", "bad/device/path", "/dev/fake")

    def test_multi_nic(self):
        instance_data = dict(self.test_instance)
        network_info = _create_network_info(2)
        conn = connection.LibvirtConnection(True)
        instance_ref = db.instance_create(self.context, instance_data)
        xml = conn.to_xml(instance_ref, network_info, False)
        tree = xml_to_tree(xml)
        interfaces = tree.findall("./devices/interface")
        self.assertEquals(len(interfaces), 2)
        parameters = interfaces[0].findall('./filterref/parameter')
        self.assertEquals(interfaces[0].get('type'), 'bridge')
        self.assertEquals(parameters[0].get('name'), 'IP')
        self.assertEquals(parameters[0].get('value'), '10.11.12.13')
        self.assertEquals(parameters[1].get('name'), 'DHCPSERVER')
        self.assertEquals(parameters[1].get('value'), '10.0.0.1')

    def _check_xml_and_container(self, instance):
        user_context = context.RequestContext(self.user_id,
                                              self.project_id)
        instance_ref = db.instance_create(user_context, instance)
        _setup_networking(instance_ref['id'], self.test_ip)

        self.flags(libvirt_type='lxc')
        conn = connection.LibvirtConnection(True)

        uri = conn.get_uri()
        self.assertEquals(uri, 'lxc:///')

        network_info = _create_network_info()
        xml = conn.to_xml(instance_ref, network_info)
        tree = xml_to_tree(xml)

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

    def _check_xml_and_uri(self, instance, expect_ramdisk, expect_kernel,
                           rescue=False):
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, instance)
        network_ref = db.project_get_networks(context.get_admin_context(),
                                             self.project_id)[0]

        _setup_networking(instance_ref['id'], self.test_ip)

        type_uri_map = {'qemu': ('qemu:///system',
                             [(lambda t: t.find('.').get('type'), 'qemu'),
                              (lambda t: t.find('./os/type').text, 'hvm'),
                              (lambda t: t.find('./devices/emulator'), None)]),
                        'kvm': ('qemu:///system',
                             [(lambda t: t.find('.').get('type'), 'kvm'),
                              (lambda t: t.find('./os/type').text, 'hvm'),
                              (lambda t: t.find('./devices/emulator'), None)]),
                        'uml': ('uml:///system',
                             [(lambda t: t.find('.').get('type'), 'uml'),
                              (lambda t: t.find('./os/type').text, 'uml')]),
                        'xen': ('xen:///',
                             [(lambda t: t.find('.').get('type'), 'xen'),
                              (lambda t: t.find('./os/type').text, 'linux')]),
                              }

        for hypervisor_type in ['qemu', 'kvm', 'xen']:
            check_list = type_uri_map[hypervisor_type][1]

            if rescue:
                check = (lambda t: t.find('./os/kernel').text.split('/')[1],
                         'kernel.rescue')
                check_list.append(check)
                check = (lambda t: t.find('./os/initrd').text.split('/')[1],
                         'ramdisk.rescue')
                check_list.append(check)
            else:
                if expect_kernel:
                    check = (lambda t: t.find('./os/kernel').text.split(
                        '/')[1], 'kernel')
                else:
                    check = (lambda t: t.find('./os/kernel'), None)
                check_list.append(check)

                if expect_ramdisk:
                    check = (lambda t: t.find('./os/initrd').text.split(
                        '/')[1], 'ramdisk')
                else:
                    check = (lambda t: t.find('./os/initrd'), None)
                check_list.append(check)

        parameter = './devices/interface/filterref/parameter'
        common_checks = [
            (lambda t: t.find('.').tag, 'domain'),
            (lambda t: t.find(parameter).get('name'), 'IP'),
            (lambda t: t.find(parameter).get('value'), '10.11.12.13'),
            (lambda t: t.findall(parameter)[1].get('name'), 'DHCPSERVER'),
            (lambda t: t.findall(parameter)[1].get('value'), '10.0.0.1'),
            (lambda t: t.find('./devices/serial/source').get(
                'path').split('/')[1], 'console.log'),
            (lambda t: t.find('./memory').text, '2097152')]
        if rescue:
            common_checks += [
                (lambda t: t.findall('./devices/disk/source')[0].get(
                    'file').split('/')[1], 'disk.rescue'),
                (lambda t: t.findall('./devices/disk/source')[1].get(
                    'file').split('/')[1], 'disk')]
        else:
            common_checks += [(lambda t: t.findall(
                './devices/disk/source')[0].get('file').split('/')[1],
                               'disk')]
            common_checks += [(lambda t: t.findall(
                './devices/disk/source')[1].get('file').split('/')[1],
                               'disk.local')]

        for (libvirt_type, (expected_uri, checks)) in type_uri_map.iteritems():
            self.flags(libvirt_type=libvirt_type)
            conn = connection.LibvirtConnection(True)

            uri = conn.get_uri()
            self.assertEquals(uri, expected_uri)

            network_info = _create_network_info()
            xml = conn.to_xml(instance_ref, network_info, rescue)
            tree = xml_to_tree(xml)
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

        # This test is supposed to make sure we don't
        # override a specifically set uri
        #
        # Deliberately not just assigning this string to FLAGS.libvirt_uri and
        # checking against that later on. This way we make sure the
        # implementation doesn't fiddle around with the FLAGS.
        testuri = 'something completely different'
        self.flags(libvirt_uri=testuri)
        for (libvirt_type, (expected_uri, checks)) in type_uri_map.iteritems():
            self.flags(libvirt_type=libvirt_type)
            conn = connection.LibvirtConnection(True)
            uri = conn.get_uri()
            self.assertEquals(uri, testuri)
        db.instance_destroy(user_context, instance_ref['id'])

    def test_update_available_resource_works_correctly(self):
        """Confirm compute_node table is updated successfully."""
        self.flags(instances_path='.')

        # Prepare mocks
        def getVersion():
            return 12003

        def getType():
            return 'qemu'

        def listDomainsID():
            return []

        service_ref = self.create_service(host='dummy')
        self.create_fake_libvirt_mock(getVersion=getVersion,
                                      getType=getType,
                                      listDomainsID=listDomainsID)
        self.mox.StubOutWithMock(connection.LibvirtConnection,
                                 'get_cpu_info')
        connection.LibvirtConnection.get_cpu_info().AndReturn('cpuinfo')

        # Start test
        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        conn.update_available_resource(self.context, 'dummy')
        service_ref = db.service_get(self.context, service_ref['id'])
        compute_node = service_ref['compute_node'][0]

        if sys.platform.upper() == 'LINUX2':
            self.assertTrue(compute_node['vcpus'] >= 0)
            self.assertTrue(compute_node['memory_mb'] > 0)
            self.assertTrue(compute_node['local_gb'] > 0)
            self.assertTrue(compute_node['vcpus_used'] == 0)
            self.assertTrue(compute_node['memory_mb_used'] > 0)
            self.assertTrue(compute_node['local_gb_used'] > 0)
            self.assertTrue(len(compute_node['hypervisor_type']) > 0)
            self.assertTrue(compute_node['hypervisor_version'] > 0)
        else:
            self.assertTrue(compute_node['vcpus'] >= 0)
            self.assertTrue(compute_node['memory_mb'] == 0)
            self.assertTrue(compute_node['local_gb'] > 0)
            self.assertTrue(compute_node['vcpus_used'] == 0)
            self.assertTrue(compute_node['memory_mb_used'] == 0)
            self.assertTrue(compute_node['local_gb_used'] > 0)
            self.assertTrue(len(compute_node['hypervisor_type']) > 0)
            self.assertTrue(compute_node['hypervisor_version'] > 0)

        db.service_destroy(self.context, service_ref['id'])

    def test_update_resource_info_no_compute_record_found(self):
        """Raise exception if no recorde found on services table."""
        self.flags(instances_path='.')
        self.create_fake_libvirt_mock()

        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        self.assertRaises(exception.ComputeServiceUnavailable,
                          conn.update_available_resource,
                          self.context, 'dummy')

    def test_ensure_filtering_rules_for_instance_timeout(self):
        """ensure_filtering_fules_for_instance() finishes with timeout."""
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

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

        self.create_fake_libvirt_mock()
        instance_ref = db.instance_create(self.context, self.test_instance)
        network_info = _create_network_info()

        # Start test
        self.mox.ReplayAll()
        try:
            conn = connection.LibvirtConnection(False)
            conn.firewall_driver.setattr('setup_basic_filtering', fake_none)
            conn.firewall_driver.setattr('prepare_instance_filter', fake_none)
            conn.firewall_driver.setattr('instance_filter_exists', fake_none)
            conn.ensure_filtering_rules_for_instance(instance_ref,
                                                     network_info,
                                                     time=fake_timer)
        except exception.Error, e:
            c1 = (0 <= e.message.find('Timeout migrating for'))
        self.assertTrue(c1)

        self.assertEqual(29, fake_timer.counter, "Didn't wait the expected "
                                                 "amount of time")

        db.instance_destroy(self.context, instance_ref['id'])

    def test_live_migration_raises_exception(self):
        """Confirms recover method is called when exceptions are raised."""
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        # Preparing data
        self.compute = utils.import_object(FLAGS.compute_manager)
        instance_dict = {'host': 'fake',
                         'power_state': power_state.RUNNING,
                         'vm_state': vm_states.ACTIVE}
        instance_ref = db.instance_create(self.context, self.test_instance)
        instance_ref = db.instance_update(self.context, instance_ref['id'],
                                          instance_dict)
        vol_dict = {'status': 'migrating', 'size': 1}
        volume_ref = db.volume_create(self.context, vol_dict)
        db.volume_attached(self.context, volume_ref['id'], instance_ref['id'],
                           '/dev/fake')

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI")
        vdmock.migrateToURI(FLAGS.live_migration_uri % 'dest',
                            mox.IgnoreArg(),
                            None, FLAGS.live_migration_bandwidth).\
                            AndRaise(libvirt.libvirtError('ERR'))

        def fake_lookup(instance_name):
            if instance_name == instance_ref.name:
                return vdmock

        self.create_fake_libvirt_mock(lookupByName=fake_lookup)
#        self.mox.StubOutWithMock(self.compute, "recover_live_migration")
        self.mox.StubOutWithMock(self.compute, "rollback_live_migration")
#        self.compute.recover_live_migration(self.context, instance_ref,
#                                             dest='dest')
        self.compute.rollback_live_migration(self.context, instance_ref,
                                            'dest', False)

        #start test
        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', False,
                      self.compute.rollback_live_migration)

        instance_ref = db.instance_get(self.context, instance_ref['id'])
        self.assertTrue(instance_ref['vm_state'] == vm_states.ACTIVE)
        self.assertTrue(instance_ref['power_state'] == power_state.RUNNING)
        volume_ref = db.volume_get(self.context, volume_ref['id'])
        self.assertTrue(volume_ref['status'] == 'in-use')

        db.volume_destroy(self.context, volume_ref['id'])
        db.instance_destroy(self.context, instance_ref['id'])

    def test_pre_block_migration_works_correctly(self):
        """Confirms pre_block_migration works correctly."""

        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        # Replace instances_path since this testcase creates tmpfile
        tmpdir = tempfile.mkdtemp()
        store = FLAGS.instances_path
        FLAGS.instances_path = tmpdir

        # Test data
        instance_ref = db.instance_create(self.context, self.test_instance)
        dummyjson = ('[{"path": "%s/disk", "local_gb": "10G",'
                     ' "type": "raw", "backing_file": ""}]')

        # Preparing mocks
        # qemu-img should be mockd since test environment might not have
        # large disk space.
        self.mox.StubOutWithMock(utils, "execute")
        utils.execute('qemu-img', 'create', '-f', 'raw',
                      '%s/%s/disk' % (tmpdir, instance_ref.name), '10G')

        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        conn.pre_block_migration(self.context, instance_ref,
                                 dummyjson % tmpdir)

        self.assertTrue(os.path.exists('%s/%s/' %
                                       (tmpdir, instance_ref.name)))

        shutil.rmtree(tmpdir)
        db.instance_destroy(self.context, instance_ref['id'])
        # Restore FLAGS.instances_path
        FLAGS.instances_path = store

    def test_get_instance_disk_info_works_correctly(self):
        """Confirms pre_block_migration works correctly."""
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

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

        ret = ("image: /test/disk\nfile format: raw\n"
               "virtual size: 20G (21474836480 bytes)\ndisk size: 3.1G\n"
               "disk size: 102M\n"
               "cluster_size: 2097152\n"
               "backing file: /test/dummy (actual path: /backing/file)\n")

        # Preparing mocks
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "XMLDesc")
        vdmock.XMLDesc(0).AndReturn(dummyxml)

        def fake_lookup(instance_name):
            if instance_name == instance_ref.name:
                return vdmock
        self.create_fake_libvirt_mock(lookupByName=fake_lookup)

        self.mox.StubOutWithMock(os.path, "getsize")
        # based on above testdata, one is raw image, so getsize is mocked.
        os.path.getsize("/test/disk").AndReturn(10 * 1024 * 1024 * 1024)
        # another is qcow image, so qemu-img should be mocked.
        self.mox.StubOutWithMock(utils, "execute")
        utils.execute('qemu-img', 'info', '/test/disk.local').\
            AndReturn((ret, ''))

        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        info = conn.get_instance_disk_info(self.context, instance_ref)
        info = utils.loads(info)

        self.assertTrue(info[0]['type'] == 'raw' and
                        info[1]['type'] == 'qcow2' and
                        info[0]['path'] == '/test/disk' and
                        info[1]['path'] == '/test/disk.local' and
                        info[0]['local_gb'] == '10G' and
                        info[1]['local_gb'] == '20G' and
                        info[0]['backing_file'] == "" and
                        info[1]['backing_file'] == "file")

        db.instance_destroy(self.context, instance_ref['id'])

    def test_spawn_with_network_info(self):
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        # Preparing mocks
        def fake_none(self, instance):
            return

        self.create_fake_libvirt_mock()
        instance = db.instance_create(self.context, self.test_instance)

        # Start test
        self.mox.ReplayAll()
        conn = connection.LibvirtConnection(False)
        conn.firewall_driver.setattr('setup_basic_filtering', fake_none)
        conn.firewall_driver.setattr('prepare_instance_filter', fake_none)

        network_info = _create_network_info()

        try:
            conn.spawn(self.context, instance, network_info)
        except Exception, e:
            count = (0 <= str(e.message).find('Unexpected method call'))

        shutil.rmtree(os.path.join(FLAGS.instances_path, instance.name))
        shutil.rmtree(os.path.join(FLAGS.instances_path, '_base'))

        self.assertTrue(count)

    def test_get_host_ip_addr(self):
        conn = connection.LibvirtConnection(False)
        ip = conn.get_host_ip_addr()
        self.assertEquals(ip, FLAGS.my_ip)

    def test_volume_in_mapping(self):
        conn = connection.LibvirtConnection(False)
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'num': 0,
                       'virtual_name': 'ephemeral0',
                       'device_name': '/dev/sdc1',
                       'size': 1},
                      {'num': 2,
                       'virtual_name': 'ephemeral2',
                       'device_name': '/dev/sdd',
                       'size': 1}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'},
                                {'mount_device': '/dev/sdf',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        def _assert_volume_in_mapping(device_name, true_or_false):
            self.assertEquals(conn._volume_in_mapping(device_name,
                                                      block_device_info),
                              true_or_false)

        _assert_volume_in_mapping('sda', False)
        _assert_volume_in_mapping('sdb', True)
        _assert_volume_in_mapping('sdc1', True)
        _assert_volume_in_mapping('sdd', True)
        _assert_volume_in_mapping('sde', True)
        _assert_volume_in_mapping('sdf', True)
        _assert_volume_in_mapping('sdg', False)
        _assert_volume_in_mapping('sdh1', False)


class NWFilterFakes:
    def __init__(self):
        self.filters = {}

    def nwfilterLookupByName(self, name):
        if name in self.filters:
            return self.filters[name]
        raise libvirt.libvirtError('Filter Not Found')

    def filterDefineXMLMock(self, xml):
        class FakeNWFilterInternal:
            def __init__(self, parent, name):
                self.name = name
                self.parent = parent

            def undefine(self):
                del self.parent.filters[self.name]
                pass
        tree = xml_to_tree(xml)
        name = tree.get('name')
        if name not in self.filters:
            self.filters[name] = FakeNWFilterInternal(self, name)
        return True


class IptablesFirewallTestCase(test.TestCase):
    def setUp(self):
        super(IptablesFirewallTestCase, self).setUp()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.network = utils.import_object(FLAGS.network_manager)

        class FakeLibvirtConnection(object):
            def nwfilterDefineXML(*args, **kwargs):
                """setup_basic_rules in nwfilter calls this."""
                pass
        self.fake_libvirt_connection = FakeLibvirtConnection()
        self.test_ip = '10.11.12.13'
        self.fw = firewall.IptablesFirewallDriver(
                      get_connection=lambda: self.fake_libvirt_connection)

    def lazy_load_library_exists(self):
        """check if libvirt is available."""
        # try to connect libvirt. if fail, skip test.
        try:
            import libvirt
            import libxml2
        except ImportError:
            return False
        global libvirt
        libvirt = __import__('libvirt')
        connection.libvirt = __import__('libvirt')
        connection.libxml2 = __import__('libxml2')
        return True

    in_nat_rules = [
      '# Generated by iptables-save v1.4.10 on Sat Feb 19 00:03:19 2011',
      '*nat',
      ':PREROUTING ACCEPT [1170:189210]',
      ':INPUT ACCEPT [844:71028]',
      ':OUTPUT ACCEPT [5149:405186]',
      ':POSTROUTING ACCEPT [5063:386098]',
    ]

    in_filter_rules = [
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*filter',
      ':INPUT ACCEPT [969615:281627771]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [915599:63811649]',
      ':nova-block-ipv4 - [0:0]',
      '-A INPUT -i virbr0 -p tcp -m tcp --dport 67 -j ACCEPT ',
      '-A FORWARD -d 192.168.122.0/24 -o virbr0 -m state --state RELATED'
      ',ESTABLISHED -j ACCEPT ',
      '-A FORWARD -s 192.168.122.0/24 -i virbr0 -j ACCEPT ',
      '-A FORWARD -i virbr0 -o virbr0 -j ACCEPT ',
      '-A FORWARD -o virbr0 -j REJECT --reject-with icmp-port-unreachable ',
      '-A FORWARD -i virbr0 -j REJECT --reject-with icmp-port-unreachable ',
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
        src_ip = '10.11.12.14'
        src_mac = '56:12:12:12:12:13'
        _setup_networking(instance_ref['id'], self.test_ip, src_mac)
        _setup_networking(src_instance_ref['id'], src_ip)

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

        db.instance_add_security_group(admin_ctxt, instance_ref['id'],
                                       secgroup['id'])
        db.instance_add_security_group(admin_ctxt, src_instance_ref['id'],
                                       src_secgroup['id'])
        instance_ref = db.instance_get(admin_ctxt, instance_ref['id'])
        src_instance_ref = db.instance_get(admin_ctxt, src_instance_ref['id'])

#        self.fw.add_instance(instance_ref)
        def fake_iptables_execute(*cmd, **kwargs):
            process_input = kwargs.get('process_input', None)
            if cmd == ('ip6tables-save', '-t', 'filter'):
                return '\n'.join(self.in6_filter_rules), None
            if cmd == ('iptables-save', '-t', 'filter'):
                return '\n'.join(self.in_filter_rules), None
            if cmd == ('iptables-save', '-t', 'nat'):
                return '\n'.join(self.in_nat_rules), None
            if cmd == ('iptables-restore',):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out_rules = lines
                return '', ''
            if cmd == ('ip6tables-restore',):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out6_rules = lines
                return '', ''
            print cmd, kwargs

        from nova.network import linux_net
        linux_net.iptables_manager.execute = fake_iptables_execute

        network_info = _create_network_info()
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)

        in_rules = filter(lambda l: not l.startswith('#'),
                          self.in_filter_rules)
        for rule in in_rules:
            if not 'nova' in rule:
                self.assertTrue(rule in self.out_rules,
                                'Rule went missing: %s' % rule)

        instance_chain = None
        for rule in self.out_rules:
            # This is pretty crude, but it'll do for now
            if '-d 10.11.12.13 -j' in rule:
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

        regex = re.compile('-A .* -j ACCEPT -p icmp -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP acceptance rule wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p icmp -m icmp --icmp-type 8'
                           ' -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP Echo Request acceptance rule wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p tcp -m multiport '
                           '--dports 80:81 -s %s' % (src_ip,))
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p tcp '
                           '-m multiport --dports 80:81 -s 192.168.10.0/24')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")
        db.instance_destroy(admin_ctxt, instance_ref['id'])

    def test_filters_for_instance_with_ip_v6(self):
        self.flags(use_ipv6=True)
        network_info = _create_network_info()
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 3)

    def test_filters_for_instance_without_ip_v6(self):
        self.flags(use_ipv6=False)
        network_info = _create_network_info()
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 0)

    def test_multinic_iptables(self):
        ipv4_rules_per_network = 2
        ipv6_rules_per_network = 3
        networks_count = 5
        instance_ref = self._create_instance_ref()
        network_info = _create_network_info(networks_count)
        ipv4_len = len(self.fw.iptables.ipv4['filter'].rules)
        ipv6_len = len(self.fw.iptables.ipv6['filter'].rules)
        inst_ipv4, inst_ipv6 = self.fw.instance_rules(instance_ref,
                                                      network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        ipv4 = self.fw.iptables.ipv4['filter'].rules
        ipv6 = self.fw.iptables.ipv6['filter'].rules
        ipv4_network_rules = len(ipv4) - len(inst_ipv4) - ipv4_len
        ipv6_network_rules = len(ipv6) - len(inst_ipv6) - ipv6_len
        self.assertEquals(ipv4_network_rules,
                          ipv4_rules_per_network * networks_count)
        self.assertEquals(ipv6_network_rules,
                          ipv6_rules_per_network * networks_count)

    def test_do_refresh_security_group_rules(self):
        instance_ref = self._create_instance_ref()
        self.mox.StubOutWithMock(self.fw,
                                 'add_filters_for_instance',
                                 use_mock_anything=True)
        self.fw.prepare_instance_filter(instance_ref, mox.IgnoreArg())
        self.fw.instances[instance_ref['id']] = instance_ref
        self.mox.ReplayAll()
        self.fw.do_refresh_security_group_rules("fake")

    def test_unfilter_instance_undefines_nwfilter(self):
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        admin_ctxt = context.get_admin_context()

        fakefilter = NWFilterFakes()
        self.fw.nwfilter._conn.nwfilterDefineXML =\
                               fakefilter.filterDefineXMLMock
        self.fw.nwfilter._conn.nwfilterLookupByName =\
                               fakefilter.nwfilterLookupByName
        instance_ref = self._create_instance_ref()

        _setup_networking(instance_ref['id'], self.test_ip)
        network_info = _create_network_info()
        self.fw.setup_basic_filtering(instance_ref, network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)
        original_filter_count = len(fakefilter.filters)
        self.fw.unfilter_instance(instance_ref, network_info)

        # should undefine just the instance filter
        self.assertEqual(original_filter_count - len(fakefilter.filters), 1)

        db.instance_destroy(admin_ctxt, instance_ref['id'])

    def test_provider_firewall_rules(self):
        # setup basic instance data
        instance_ref = self._create_instance_ref()
        _setup_networking(instance_ref['id'], self.test_ip)
        # FRAGILE: peeks at how the firewall names chains
        chain_name = 'inst-%s' % instance_ref['id']

        # create a firewall via setup_basic_filtering like libvirt_conn.spawn
        # should have a chain with 0 rules
        network_info = _create_network_info(1)
        self.fw.setup_basic_filtering(instance_ref, network_info)
        self.assertTrue('provider' in self.fw.iptables.ipv4['filter'].chains)
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

        self.test_ip = '10.11.12.13'
        self.fw = firewall.NWFilterFirewall(
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

        xml = self.fw.security_group_to_nwfilter_xml(security_group.id)

        dom = xml_to_dom(xml)
        self.assertEqual(dom.firstChild.tagName, 'filter')

        rules = dom.getElementsByTagName('rule')
        self.assertEqual(len(rules), 1)

        # It's supposed to allow inbound traffic.
        self.assertEqual(rules[0].getAttribute('action'), 'accept')
        self.assertEqual(rules[0].getAttribute('direction'), 'in')

        # Must be lower priority than the base filter (which blocks everything)
        self.assertTrue(int(rules[0].getAttribute('priority')) < 1000)

        ip_conditions = rules[0].getElementsByTagName('tcp')
        self.assertEqual(len(ip_conditions), 1)
        self.assertEqual(ip_conditions[0].getAttribute('srcipaddr'), '0.0.0.0')
        self.assertEqual(ip_conditions[0].getAttribute('srcipmask'), '0.0.0.0')
        self.assertEqual(ip_conditions[0].getAttribute('dstportstart'), '80')
        self.assertEqual(ip_conditions[0].getAttribute('dstportend'), '81')
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

    def _create_instance_type(self, params=None):
        """Create a test instance"""
        if not params:
            params = {}

        context = self.context.elevated()
        inst = {}
        inst['name'] = 'm1.small'
        inst['memory_mb'] = '1024'
        inst['vcpus'] = '1'
        inst['local_gb'] = '20'
        inst['flavorid'] = '1'
        inst['swap'] = '2048'
        inst['rxtx_quota'] = 100
        inst['rxtx_cap'] = 200
        inst.update(params)
        return db.instance_type_create(context, inst)['id']

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
            dom = xml_to_dom(xml)
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

        _setup_networking(instance_ref['id'], self.test_ip)

        def _ensure_all_called():
            instance_filter = 'nova-instance-%s-%s' % (instance_ref['name'],
                                                       'fake')
            secgroup_filter = 'nova-secgroup-%s' % self.security_group['id']
            for required in [secgroup_filter, 'allow-dhcp-server',
                             'no-arp-spoofing', 'no-ip-spoofing',
                             'no-mac-spoofing']:
                self.assertTrue(required in
                                self.recursive_depends[instance_filter],
                                "Instance's filter does not include %s" %
                                required)

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_id,
                                       self.security_group.id)
        instance = db.instance_get(self.context, inst_id)

        network_info = _create_network_info()
        self.fw.setup_basic_filtering(instance, network_info)
        self.fw.prepare_instance_filter(instance, network_info)
        self.fw.apply_instance_filter(instance, network_info)
        _ensure_all_called()
        self.teardown_security_group()
        db.instance_destroy(context.get_admin_context(), instance_ref['id'])

    def test_create_network_filters(self):
        instance_ref = self._create_instance()
        network_info = _create_network_info(3)
        result = self.fw._create_network_filters(instance_ref,
                                                 network_info,
                                                 "fake")
        self.assertEquals(len(result), 3)

    def test_unfilter_instance_undefines_nwfilters(self):
        admin_ctxt = context.get_admin_context()

        fakefilter = NWFilterFakes()
        self.fw._conn.nwfilterDefineXML = fakefilter.filterDefineXMLMock
        self.fw._conn.nwfilterLookupByName = fakefilter.nwfilterLookupByName

        instance_ref = self._create_instance()
        inst_id = instance_ref['id']

        self.security_group = self.setup_and_return_security_group()

        db.instance_add_security_group(self.context, inst_id,
                                       self.security_group.id)

        instance = db.instance_get(self.context, inst_id)

        _setup_networking(instance_ref['id'], self.test_ip)
        network_info = _create_network_info()
        self.fw.setup_basic_filtering(instance, network_info)
        self.fw.prepare_instance_filter(instance, network_info)
        self.fw.apply_instance_filter(instance, network_info)
        original_filter_count = len(fakefilter.filters)
        self.fw.unfilter_instance(instance, network_info)

        # should undefine 2 filters: instance and instance-secgroup
        self.assertEqual(original_filter_count - len(fakefilter.filters), 2)

        db.instance_destroy(admin_ctxt, instance_ref['id'])
