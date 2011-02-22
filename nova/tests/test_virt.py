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

import mox

from xml.etree.ElementTree import fromstring as xml_to_tree
from xml.dom.minidom import parseString as xml_to_dom

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import logging
from nova import test
from nova import utils
from nova.api.ec2 import cloud
from nova.auth import manager
from nova.db.sqlalchemy import models
from nova.compute import power_state
from nova.virt import libvirt_conn

FLAGS = flags.FLAGS
flags.DECLARE('instances_path', 'nova.compute.manager')

libvirt = None
libxml2 = None


class LibvirtConnTestCase(test.TestCase):
    def setUp(self):
        super(LibvirtConnTestCase, self).setUp()
        libvirt_conn._late_load_cheetah()
        self.flags(fake_call=True)
        self.manager = manager.AuthManager()

        try:
            pjs = self.manager.get_projects()
            pjs = [p for p in pjs if p.name == 'fake']
            if 0 != len(pjs):
                self.manager.delete_project(pjs[0])

            users = self.manager.get_users()
            users = [u for u in users if u.name == 'fake']
            if 0 != len(users):
                self.manager.delete_user(users[0])
        except Exception, e:
            pass

        users = self.manager.get_users()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)
        FLAGS.instances_path = ''

    test_ip = '10.11.12.13'
    test_instance = {'memory_kb':     '1024000',
                     'basepath':      '/some/path',
                     'bridge_name':   'br100',
                     'mac_address':   '02:12:34:46:56:67',
                     'vcpus':         2,
                     'project_id':    'fake',
                     'bridge':        'br101',
                     'instance_type': 'm1.small'}

    def _driver_dependant_test_setup(self):
        """Call this method at the top of each testcase method.

        Checks if libvirt and cheetah, etc is installed.
        Otherwise, skip testing."""

        try:
            global libvirt
            global libxml2
            libvirt_conn.libvirt = __import__('libvirt')
            libvirt_conn.libxml2 = __import__('libxml2')
            libvirt_conn._late_load_cheetah()
            libvirt = __import__('libvirt')
        except ImportError, e:
            logging.warn("""This test has not been done since """
                 """using driver-dependent library Cheetah/libvirt/libxml2.""")
            raise

        # inebitable mocks for calling
        obj = utils.import_object(FLAGS.firewall_driver)
        fwmock = self.mox.CreateMock(obj)
        self.mox.StubOutWithMock(libvirt_conn, 'utils',
                                 use_mock_anything=True)
        libvirt_conn.utils.import_object(FLAGS.firewall_driver).\
                                         AndReturn(fwmock)
        return fwmock

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

    def _check_xml_and_uri(self, instance, expect_ramdisk, expect_kernel,
                           rescue=False):
        user_context = context.RequestContext(project=self.project,
                                              user=self.user)
        instance_ref = db.instance_create(user_context, instance)
        host = self.network.get_network_host(user_context.elevated())
        network_ref = db.project_get_network(context.get_admin_context(),
                                             self.project.id)

        fixed_ip = {'address':    self.test_ip,
                    'network_id': network_ref['id']}

        ctxt = context.get_admin_context()
        fixed_ip_ref = db.fixed_ip_create(ctxt, fixed_ip)
        db.fixed_ip_update(ctxt, self.test_ip,
                                 {'allocated':   True,
                                  'instance_id': instance_ref['id']})

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

        common_checks = [
            (lambda t: t.find('.').tag, 'domain'),
            (lambda t: t.find(
                './devices/interface/filterref/parameter').get('name'), 'IP'),
            (lambda t: t.find(
                './devices/interface/filterref/parameter').get(
                    'value'), '10.11.12.13'),
            (lambda t: t.findall(
                './devices/interface/filterref/parameter')[1].get(
                    'name'), 'DHCPSERVER'),
            (lambda t: t.findall(
                './devices/interface/filterref/parameter')[1].get(
                    'value'), '10.0.0.1'),
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
            FLAGS.libvirt_type = libvirt_type
            conn = libvirt_conn.LibvirtConnection(True)

            uri = conn.get_uri()
            self.assertEquals(uri, expected_uri)

            xml = conn.to_xml(instance_ref, rescue)
            tree = xml_to_tree(xml)
            for i, (check, expected_result) in enumerate(checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s failed check %d' % (xml, i))

            for i, (check, expected_result) in enumerate(common_checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s failed common check %d' % (xml, i))

        # This test is supposed to make sure we don't
        # override a specifically set uri
        #
        # Deliberately not just assigning this string to FLAGS.libvirt_uri and
        # checking against that later on. This way we make sure the
        # implementation doesn't fiddle around with the FLAGS.
        testuri = 'something completely different'
        FLAGS.libvirt_uri = testuri
        for (libvirt_type, (expected_uri, checks)) in type_uri_map.iteritems():
            FLAGS.libvirt_type = libvirt_type
            conn = libvirt_conn.LibvirtConnection(True)
            uri = conn.get_uri()
            self.assertEquals(uri, testuri)

    def test_get_vcpu_total(self):
        """Check if get_vcpu_total returns appropriate cpu value."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < conn.get_vcpu_total())

    def test_get_memory_mb_total(self):
        """Check if get_memory_mb returns appropriate memory value."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < conn.get_memory_mb_total())

    def test_get_vcpu_used(self):
        """Check if get_local_gb_total returns appropriate disk value."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.listDomainsID().AndReturn([1, 2])
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "vcpus", use_mock_anything=True)
        vdmock.vcpus().AndReturn(['', [('dummycpu'), ('dummycpu')]])
        vdmock.vcpus().AndReturn(['', [('dummycpu'), ('dummycpu')]])
        libvirt_conn.LibvirtConnection._conn.lookupByID(mox.IgnoreArg()).\
            AndReturn(vdmock)
        libvirt_conn.LibvirtConnection._conn.lookupByID(mox.IgnoreArg()).\
            AndReturn(vdmock)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(conn.get_vcpu_used() == 4)

    def test_get_memory_mb_used(self):
        """Check if get_memory_mb returns appropriate memory value."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < conn.get_memory_mb_used())

    def test_get_cpu_info_works_correctly(self):
        """Check if get_cpu_info works correctly as expected."""
        xml = """<cpu>
                     <arch>x86_64</arch>
                     <model>Nehalem</model>
                     <vendor>Intel</vendor>
                     <topology sockets='2' cores='4' threads='2'/>
                     <feature name='rdtscp'/>
                     <feature name='dca'/>
                     <feature name='xtpr'/>
                     <feature name='tm2'/>
                     <feature name='est'/>
                     <feature name='vmx'/>
                     <feature name='ds_cpl'/>
                     <feature name='monitor'/>
                     <feature name='pbe'/>
                     <feature name='tm'/>
                     <feature name='ht'/>
                     <feature name='ss'/>
                     <feature name='acpi'/>
                     <feature name='ds'/>
                     <feature name='vme'/>
                </cpu>
             """

        try:
            self._driver_dependant_test_setup()
        except:
            return
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < len(conn.get_cpu_info()))

    def test_get_cpu_info_inappropreate_xml(self):
        """Raise exception if given xml is inappropriate."""
        xml = """<cccccpu>
                     <arch>x86_64</arch>
                     <model>Nehalem</model>
                     <vendor>Intel</vendor>
                     <topology sockets='2' cores='4' threads='2'/>
                     <feature name='rdtscp'/>
                     <feature name='dca'/>
                     <feature name='xtpr'/>
                     <feature name='tm2'/>
                     <feature name='est'/>
                     <feature name='vmx'/>
                     <feature name='ds_cpl'/>
                     <feature name='monitor'/>
                     <feature name='pbe'/>
                     <feature name='tm'/>
                     <feature name='ht'/>
                     <feature name='ss'/>
                     <feature name='acpi'/>
                     <feature name='ds'/>
                     <feature name='vme'/>
                 </cccccpu>
              """

        try:
            self._driver_dependant_test_setup()
        except:
            return
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        try:
            conn.get_cpu_info()
        except exception.Invalid, e:
            c1 = (0 <= e.message.find('Invalid xml'))
        self.assertTrue(c1)

    def test_get_cpu_info_inappropreate_xml2(self):
        """Raise exception if given xml is inappropriate(topology tag)."""

        xml = """<cpu>
                      <arch>x86_64</arch>
                      <model>Nehalem</model>
                      <vendor>Intel</vendor><topology cores='4' threads='2'/>
                      <feature name='rdtscp'/>
                      <feature name='dca'/>
                      <feature name='xtpr'/>
                      <feature name='tm2'/>
                      <feature name='est'/>
                      <feature name='vmx'/>
                      <feature name='ds_cpl'/>
                      <feature name='monitor'/>
                      <feature name='pbe'/>
                      <feature name='tm'/>
                      <feature name='ht'/>
                      <feature name='ss'/>
                      <feature name='acpi'/>
                      <feature name='ds'/>
                      <feature name='vme'/>
                  </cpu>
              """
        try:
            self._driver_dependant_test_setup()
        except:
            return
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        try:
            conn.get_cpu_info()
        except exception.Invalid, e:
            c1 = (0 <= e.message.find('Invalid xml: topology'))
        self.assertTrue(c1)

    def test_update_available_resource_works_correctly(self):
        """Confirm compute_service table is updated successfully."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        def dic_key_check(dic):
            validkey = ['vcpus', 'memory_mb', 'local_gb',
                        'vcpus_used', 'memory_mb_used', 'local_gb_used',
                        'hypervisor_type', 'hypervisor_version', 'cpu_info']
            return (list(set(validkey)) == list(set(dic.keys())))

        host = 'foo'
        binary = 'nova-compute'
        service_ref = {'id': 1,
                       'host': host,
                       'binary': binary,
                       'topic': 'compute'}

        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        db.service_get_all_by_topic(mox.IgnoreMox(), 'compute').\
            AndReturn([service_ref])
        dbmock.service_update(mox.IgnoreArg(),
                              service_ref['id'],
                              mox.Func(dic_key_check))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        conn.update_available_resource(host)

    def test_update_resource_info_raise_exception(self):
        """Raise exception if no recorde found on services table."""
        try:
            self._driver_dependant_test_setup()
        except:
            return

        host = 'foo'
        binary = 'nova-compute'
        dbmock = self.mox.CreateMock(db)
        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        db.service_get_all_by_topic(mox.IgnoreMox(), 'compute').\
            AndRaise(exceptin.NotFound())

        self.mox.ReplayAll()
        try:
            conn = libvirt_conn.LibvirtConnection(False)
            conn.update_available_resource(host)
        except exception.Invalid, e:
            msg = 'Cannot insert compute manager specific info'
            c1 = (0 <= e.message.find(msg))
            self.assertTrue(c1)

    def test_compare_cpu_works_correctly(self):
        """Calling libvirt.compute_cpu() and works correctly."""
        t = {}
        t['arch'] = 'x86'
        t['model'] = 'model'
        t['vendor'] = 'Intel'
        t['topology'] = {'cores': "2", "threads": "1", "sockets": "4"}
        t['features'] = ["tm"]
        cpu_info = utils.dumps(t)

        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 '_conn',
                                 use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(),
                                                        0).AndReturn(1)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(None == conn.compare_cpu(cpu_info))

    def test_compare_cpu_raises_exception(self):
        """Libvirt-related exception occurs when calling compare_cpu()."""
        t = {}
        t['arch'] = 'x86'
        t['model'] = 'model'
        t['vendor'] = 'Intel'
        t['topology'] = {'cores': "2", "threads": "1", "sockets": "4"}
        t['features'] = ["tm"]
        cpu_info = utils.dumps(t)

        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(), 0).\
            AndRaise(libvirt.libvirtError('ERR'))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError, conn.compare_cpu, cpu_info)

    def test_compare_cpu_no_compatibility(self):
        """Libvirt.compare_cpu() return less than 0.(no compatibility)."""
        t = {}
        t['arch'] = 'x86'
        t['model'] = 'model'
        t['vendor'] = 'Intel'
        t['topology'] = {'cores': "2", "threads": "1", "sockets": "4"}
        t['features'] = ["tm"]
        cpu_info = utils.dumps(t)

        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(), 0).\
            AndRaise(exception.Invalid('ERR'))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(exception.Invalid, conn.compare_cpu, cpu_info)

    def test_ensure_filtering_rules_for_instance_works_correctly(self):
        """ensure_filtering_rules_for_instance() works successfully."""
        instance_ref = models.Instance()
        instance_ref.__setitem__('id', 1)

        try:
            nwmock, fwmock = self._driver_dependant_test_setup()
        except:
            return

        nwmock.setup_basic_filtering(mox.IgnoreArg())
        fwmock.prepare_instance_filter(instance_ref)
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        n = 'nova-instance-%s' % instance_ref.name
        libvirt_conn.LibvirtConnection._conn.nwfilterLookupByName(n)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        conn.ensure_filtering_rules_for_instance(instance_ref)

    def test_ensure_filtering_rules_for_instance_timeout(self):
        """ensure_filtering_fules_for_instance() finishes with timeout."""
        instance_ref = models.Instance()
        instance_ref.__setitem__('id', 1)

        try:
            nwmock, fwmock = self._driver_dependant_test_setup()
        except:
            return

        nwmock.setup_basic_filtering(mox.IgnoreArg())
        fwmock.prepare_instance_filter(instance_ref)
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        n = 'nova-instance-%s' % instance_ref.name
        for i in range(FLAGS.live_migration_timeout_sec * 2):
            libvirt_conn.LibvirtConnection._conn.\
                nwfilterLookupByName(n).AndRaise(libvirt.libvirtError('ERR'))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        try:
            conn.ensure_filtering_rules_for_instance(instance_ref)
        except exception.Error, e:
            c1 = (0 <= e.message.find('Timeout migrating for'))
            self.assertTrue(c1)

    def test_live_migration_works_correctly(self):
        """_live_migration() works as expected correctly."""
        class dummyCall(object):
            f = None

            def start(self, interval=0, now=False):
                pass

        i_ref = models.Instance()
        i_ref.__setitem__('id', 1)
        i_ref.__setitem__('host', 'dummy')
        ctxt = context.get_admin_context()

        try:
            self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI",
                                 use_mock_anything=True)
        vdmock.migrateToURI(FLAGS.live_migration_uri % i_ref['host'],
                            mox.IgnoreArg(),
                            None, FLAGS.live_migration_bandwidth).\
                            AndReturn(None)
        libvirt_conn.LibvirtConnection._conn.lookupByName(i_ref.name).\
            AndReturn(vdmock)
        libvirt_conn.utils.LoopingCall(f=None).AndReturn(dummyCall())

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        # Not setting post_method/recover_method in this testcase.
        ret = conn._live_migration(ctxt, i_ref, i_ref['host'], '', '')
        self.assertTrue(ret == None)

    def test_live_migration_raises_exception(self):
        """Confirms recover method is called when exceptions are raised."""
        i_ref = models.Instance()
        i_ref.__setitem__('id', 1)
        i_ref.__setitem__('host', 'dummy')
        ctxt = context.get_admin_context()

        def dummy_recover_method(self, c, instance):
            pass

        try:
            nwmock, fwmock = self._driver_dependant_test_setup()
        except:
            return

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI",
                                 use_mock_anything=True)
        vdmock.migrateToURI(FLAGS.live_migration_uri % dest, mox.IgnoreArg(),
                            None, FLAGS.live_migration_bandwidth).\
                            AndRaise(libvirt.libvirtError('ERR'))
        libvirt_conn.LibvirtConnection._conn.lookupByName(instance_ref.name).\
                                                          AndReturn(vdmock)
        self.mox.StubOutWithMock(db, 'instance_set_state')
        db.instance_set_state(ctxt, instance_ref['id'],
                              power_state.RUNNING, 'running')
        self.mox.StubOutWithMock(db, 'volume_update')
        for v in instance_ref.volumes:
            db.volume_update(ctxt, v['id'], {'status': 'in-use'})

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError,
                          conn._mlive_migration,
                          ctxt, instance_ref, dest,
                          '', dummy_recover_method)

    def tearDown(self):
        super(LibvirtConnTestCase, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)


class IptablesFirewallTestCase(test.TestCase):
    def setUp(self):
        super(IptablesFirewallTestCase, self).setUp()

        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = context.RequestContext('fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)

        class FakeLibvirtConnection(object):
            pass
        self.fake_libvirt_connection = FakeLibvirtConnection()
        self.fw = libvirt_conn.IptablesFirewallDriver(
                      get_connection=lambda: self.fake_libvirt_connection)

    def tearDown(self):
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        super(IptablesFirewallTestCase, self).tearDown()

    in_rules = [
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*filter',
      ':INPUT ACCEPT [969615:281627771]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [915599:63811649]',
      ':nova-block-ipv4 - [0:0]',
      '-A INPUT -i virbr0 -p udp -m udp --dport 53 -j ACCEPT ',
      '-A INPUT -i virbr0 -p tcp -m tcp --dport 53 -j ACCEPT ',
      '-A INPUT -i virbr0 -p udp -m udp --dport 67 -j ACCEPT ',
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

    in6_rules = [
      '# Generated by ip6tables-save v1.4.4 on Tue Jan 18 23:47:56 2011',
      '*filter',
      ':INPUT ACCEPT [349155:75810423]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [349256:75777230]',
      'COMMIT',
      '# Completed on Tue Jan 18 23:47:56 2011',
    ]

    def test_static_filters(self):
        instance_ref = db.instance_create(self.context,
                                          {'user_id': 'fake',
                                          'project_id': 'fake',
                                          'mac_address': '56:12:12:12:12:12'})
        ip = '10.11.12.13'

        network_ref = db.project_get_network(self.context,
                                             'fake')

        fixed_ip = {'address': ip,
                    'network_id': network_ref['id']}

        admin_ctxt = context.get_admin_context()
        db.fixed_ip_create(admin_ctxt, fixed_ip)
        db.fixed_ip_update(admin_ctxt, ip, {'allocated': True,
                                            'instance_id': instance_ref['id']})

        secgroup = db.security_group_create(admin_ctxt,
                                            {'user_id': 'fake',
                                             'project_id': 'fake',
                                             'name': 'testgroup',
                                             'description': 'test group'})

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

        db.instance_add_security_group(admin_ctxt, instance_ref['id'],
                                       secgroup['id'])
        instance_ref = db.instance_get(admin_ctxt, instance_ref['id'])

#        self.fw.add_instance(instance_ref)
        def fake_iptables_execute(cmd, process_input=None):
            if cmd == 'sudo ip6tables-save -t filter':
                return '\n'.join(self.in6_rules), None
            if cmd == 'sudo iptables-save -t filter':
                return '\n'.join(self.in_rules), None
            if cmd == 'sudo iptables-restore':
                self.out_rules = process_input.split('\n')
                return '', ''
            if cmd == 'sudo ip6tables-restore':
                self.out6_rules = process_input.split('\n')
                return '', ''
        self.fw.execute = fake_iptables_execute

        self.fw.prepare_instance_filter(instance_ref)
        self.fw.apply_instance_filter(instance_ref)

        in_rules = filter(lambda l: not l.startswith('#'), self.in_rules)
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

        self.assertTrue('-A %s -p icmp -s 192.168.11.0/24 -j ACCEPT' % \
                               security_group_chain in self.out_rules,
                        "ICMP acceptance rule wasn't added")

        self.assertTrue('-A %s -p icmp -s 192.168.11.0/24 -m icmp --icmp-type '
                        '8 -j ACCEPT' % security_group_chain in self.out_rules,
                        "ICMP Echo Request acceptance rule wasn't added")

        self.assertTrue('-A %s -p tcp -s 192.168.10.0/24 -m multiport '
                        '--dports 80:81 -j ACCEPT' % security_group_chain \
                            in self.out_rules,
                        "TCP port 80/81 acceptance rule wasn't added")


class NWFilterTestCase(test.TestCase):
    def setUp(self):
        super(NWFilterTestCase, self).setUp()

        class Mock(object):
            pass

        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = context.RequestContext(self.user, self.project)

        self.fake_libvirt_connection = Mock()

        self.fw = libvirt_conn.NWFilterFirewall(
                                         lambda: self.fake_libvirt_connection)

    def tearDown(self):
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)

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

        instance_ref = db.instance_create(self.context,
                                          {'user_id': 'fake',
                                          'project_id': 'fake'})
        inst_id = instance_ref['id']

        ip = '10.11.12.13'

        network_ref = db.project_get_network(self.context,
                                             'fake')

        fixed_ip = {'address': ip,
                    'network_id': network_ref['id']}

        admin_ctxt = context.get_admin_context()
        db.fixed_ip_create(admin_ctxt, fixed_ip)
        db.fixed_ip_update(admin_ctxt, ip, {'allocated': True,
                                            'instance_id': instance_ref['id']})

        def _ensure_all_called():
            instance_filter = 'nova-instance-%s' % instance_ref['name']
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

        self.fw.setup_basic_filtering(instance)
        self.fw.prepare_instance_filter(instance)
        self.fw.apply_instance_filter(instance)
        _ensure_all_called()
        self.teardown_security_group()
