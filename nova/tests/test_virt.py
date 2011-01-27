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
from nova import test
from nova import logging
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

    def _driver_dependent_test_setup(self): 
        """
        Setup method.
        Call this method at the top of each testcase method, 
        if the testcase is necessary libvirt and cheetah.
        """
        try : 
            global libvirt
            global libxml2
            libvirt_conn.libvirt = __import__('libvirt')
            libvirt_conn.libxml2 = __import__('libxml2')
            libvirt_conn._late_load_cheetah()
            libvirt = __import__('libvirt')
        except ImportError, e:
            logging.warn("""This test has not been done since """
                 """using driver-dependent library Cheetah/libvirt/libxml2.""")
            raise e

        # inebitable mocks for calling 
        #nova.virt.libvirt_conn.LibvirtConnection.__init__
        nwmock = self.mox.CreateMock(libvirt_conn.NWFilterFirewall)
        self.mox.StubOutWithMock(libvirt_conn, 'NWFilterFirewall',
                                 use_mock_anything=True)
        libvirt_conn.NWFilterFirewall(mox.IgnoreArg()).AndReturn(nwmock)

        obj = utils.import_object(FLAGS.firewall_driver)
        fwmock = self.mox.CreateMock(obj)
        self.mox.StubOutWithMock(libvirt_conn, 'utils',
                                 use_mock_anything=True)
        libvirt_conn.utils.import_object(FLAGS.firewall_driver).AndReturn(fwmock)
        return nwmock, fwmock

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
                         'rescue-kernel')
                check_list.append(check)
                check = (lambda t: t.find('./os/initrd').text.split('/')[1],
                         'rescue-ramdisk')
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
                    'file').split('/')[1], 'rescue-disk'),
                (lambda t: t.findall('./devices/disk/source')[1].get(
                    'file').split('/')[1], 'disk')]
        else:
            common_checks += [(lambda t: t.findall(
                './devices/disk/source')[0].get('file').split('/')[1],
                               'disk')]

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

        # This test is supposed to make sure we don't override a specifically set uri
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

    def test_get_memory_mb(self):
        """
        Check if get_memory_mb returns memory value
        Connection/OS/driver differenct does not matter for this method,
        so everyone can execute for checking.
        """
        try: 
            self._driver_dependent_test_setup()
        except: 
            return 

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < conn.get_memory_mb())
        self.mox.UnsetStubs()

    def test_get_cpu_info_works_correctly(self):
        """
        Check if get_cpu_info works correctly.
        (in case libvirt.getCapabilities() works correctly)
        """
        xml=("""<cpu><arch>x86_64</arch><model>Nehalem</model>"""
             """<vendor>Intel</vendor><topology sockets='2' """
             """cores='4' threads='2'/><feature name='rdtscp'/>"""
             """<feature name='dca'/><feature name='xtpr'/>"""
             """<feature name='tm2'/><feature name='est'/>"""
             """<feature name='vmx'/><feature name='ds_cpl'/>"""
             """<feature name='monitor'/><feature name='pbe'/>"""
             """<feature name='tm'/><feature name='ht'/>"""
             """<feature name='ss'/><feature name='acpi'/>"""
             """<feature name='ds'/><feature name='vme'/></cpu>""")

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue(0 < len(conn.get_cpu_info()))
        self.mox.UnsetStubs()

    def test_get_cpu_info_inappropreate_xml(self):
        """
        Check if get_cpu_info raises exception
        in case libvirt.getCapabilities() returns wrong xml
        (in case of xml doesnt have <cpu> tag)
        """
        xml=("""<cccccpu><arch>x86_64</arch><model>Nehalem</model>"""
             """<vendor>Intel</vendor><topology sockets='2' """
             """cores='4' threads='2'/><feature name='rdtscp'/>"""
             """<feature name='dca'/><feature name='xtpr'/>"""
             """<feature name='tm2'/><feature name='est'/>"""
             """<feature name='vmx'/><feature name='ds_cpl'/>"""
             """<feature name='monitor'/><feature name='pbe'/>"""
             """<feature name='tm'/><feature name='ht'/>"""
             """<feature name='ss'/><feature name='acpi'/>"""
             """<feature name='ds'/><feature name='vme'/></cccccpu>""")

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        try: 
            conn.get_cpu_info()
        except exception.Invalid, e:
            c1 = ( 0 <= e.message.find('Invalid xml') )
            self.assertTrue(c1)
        self.mox.UnsetStubs()
            
    def test_get_cpu_info_inappropreate_xml2(self):
        """
        Check if get_cpu_info raises exception
        in case libvirt.getCapabilities() returns wrong xml
        (in case of xml doesnt have inproper <topology> tag
        meaning missing "socket" attribute)
        """
        xml=("""<cpu><arch>x86_64</arch><model>Nehalem</model>"""
             """<vendor>Intel</vendor><topology """
             """cores='4' threads='2'/><feature name='rdtscp'/>"""
             """<feature name='dca'/><feature name='xtpr'/>"""
             """<feature name='tm2'/><feature name='est'/>"""
             """<feature name='vmx'/><feature name='ds_cpl'/>"""
             """<feature name='monitor'/><feature name='pbe'/>"""
             """<feature name='tm'/><feature name='ht'/>"""
             """<feature name='ss'/><feature name='acpi'/>"""
             """<feature name='ds'/><feature name='vme'/></cpu>""")

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.getCapabilities().AndReturn(xml)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        try: 
            conn.get_cpu_info()
        except exception.Invalid, e:
            c1 = ( 0 <= e.message.find('Invalid xml: topology') )
            self.assertTrue(c1)
        self.mox.UnsetStubs()

    def test_compare_cpu_works_correctly(self):
        """Calling libvirt.compute_cpu() and works correctly """

        t = ("""{"arch":"%s", "model":"%s", "vendor":"%s", """
                    """"topology":{"cores":"%s", "threads":"%s", """
                    """"sockets":"%s"}, "features":[%s]}""")
        cpu_info = t % ('x86', 'model', 'vendor', '2', '1', '4', '"tm"')

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn', use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(),0).AndReturn(1)

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertTrue( None== conn.compare_cpu(cpu_info))
        self.mox.UnsetStubs()

    def test_compare_cpu_raises_exception(self):
        """
        Libvirt-related exception occurs when calling
        libvirt.compare_cpu().
        """
        t = ("""{"arch":"%s", "model":"%s", "vendor":"%s", """
                    """"topology":{"cores":"%s", "threads":"%s", """
                    """"sockets":"%s"}, "features":[%s]}""")
        cpu_info = t % ('x86', 'model', 'vendor', '2', '1', '4', '"tm"')

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(),0).\
            AndRaise(libvirt.libvirtError('ERR'))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError, conn.compare_cpu, cpu_info)
        self.mox.UnsetStubs()

    def test_compare_cpu_no_compatibility(self):
        """libvirt.compare_cpu() return less than 0.(no compatibility)"""

        t = ("""{"arch":"%s", "model":"%s", "vendor":"%s", """
                    """"topology":{"cores":"%s", "threads":"%s", """
                    """"sockets":"%s"}, "features":[%s]}""")
        cpu_info = t % ('x86', 'model', 'vendor', '2', '1', '4', '"tm"')

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        libvirt_conn.LibvirtConnection._conn.compareCPU(mox.IgnoreArg(),0).\
            AndRaise(exception.Invalid('ERR'))

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(exception.Invalid, conn.compare_cpu, cpu_info)
        self.mox.UnsetStubs()

    def test_ensure_filtering_rules_for_instance_works_correctly(self):
        """ensure_filtering_rules_for_instance works as expected correctly"""

        instance_ref = models.Instance()
        instance_ref.__setitem__('id', 1)

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
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
        self.mox.UnsetStubs()

    def test_ensure_filtering_rules_for_instance_timeout(self):
        """ensure_filtering_fules_for_instance finishes with timeout"""

        instance_ref = models.Instance()
        instance_ref.__setitem__('id', 1)

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
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
            c1 = ( 0<=e.message.find('Timeout migrating for'))
            self.assertTrue(c1)
        self.mox.UnsetStubs()

    def test_live_migration_works_correctly(self):
        """_live_migration works as expected correctly """

        class dummyCall(object):
            f = None
            def start(self, interval=0, now=False): 
                pass

        instance_ref = models.Instance()
        instance_ref.__setitem__('id', 1)
        dest = 'desthost'
        ctxt = context.get_admin_context()

        try: 
            self._driver_dependent_test_setup()
        except: 
            return 

        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn',
                                 use_mock_anything=True)
        vdmock = self.mox.CreateMock(libvirt.virDomain)
        self.mox.StubOutWithMock(vdmock, "migrateToURI",
                                 use_mock_anything=True)
        vdmock.migrateToURI(FLAGS.live_migration_uri % dest, mox.IgnoreArg(),
                            None, FLAGS.live_migration_bandwidth).\
                            AndReturn(None)
        libvirt_conn.LibvirtConnection._conn.lookupByName(instance_ref.name).\
            AndReturn(vdmock)
        # below description is also ok.
        #self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection._conn, 
        #    "lookupByName", use_mock_anything=True)
        
        libvirt_conn.utils.LoopingCall(f=None).AndReturn(dummyCall())


        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        ret = conn._live_migration(ctxt, instance_ref, dest)
        self.assertTrue(ret == None)
        self.mox.UnsetStubs()

    def test_live_migration_raises_exception(self):
        """
        _live_migration raises exception, then this testcase confirms
        state_description/state for the instances/volumes are recovered. 
        """
        class Instance(models.NovaBase): 
            id = 0
            volumes = None
            name = 'name'

        ctxt = context.get_admin_context()
        dest = 'desthost'
        instance_ref = Instance()
        instance_ref.__setitem__('id', 1)
        instance_ref.__setitem__('volumes', [{'id':1}, {'id':2}])

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
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
            db.volume_update(ctxt, v['id'], {'status': 'in-use'}).\
            InAnyOrder('g1')

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError, 
                         conn._live_migration,
                         ctxt, instance_ref, dest)
        self.mox.UnsetStubs()

    def test_post_live_migration_working_correctly(self):
        """_post_live_migration works as expected correctly """

        dest = 'dummydest'
        ctxt = context.get_admin_context()
        instance_ref = {'id':1, 'hostname':'i-00000001', 'host':dest, 
                       'fixed_ip':'dummyip', 'floating_ip':'dummyflip', 
                       'volumes':[{'id':1}, {'id':2} ]}
        network_ref = {'id':1, 'host':dest}
        floating_ip_ref = {'id':1, 'address':'1.1.1.1'}

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
        except: 
            return 
        fwmock.unfilter_instance(instance_ref)

        fixed_ip = instance_ref['fixed_ip']
        self.mox.StubOutWithMock(db, 'instance_get_fixed_address')
        db.instance_get_fixed_address(ctxt, instance_ref['id']).AndReturn(fixed_ip)
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        db.fixed_ip_update(ctxt, fixed_ip, {'host': dest})
        self.mox.StubOutWithMock(db, 'fixed_ip_get_network')
        db.fixed_ip_get_network(ctxt, fixed_ip).AndReturn(network_ref)
        self.mox.StubOutWithMock(db, 'network_update')
        db.network_update(ctxt, network_ref['id'], {'host': dest})
        
        fl_ip = instance_ref['floating_ip']
        self.mox.StubOutWithMock(db, 'instance_get_floating_address')
        db.instance_get_floating_address(ctxt, instance_ref['id']).AndReturn(fl_ip)
        self.mox.StubOutWithMock(db, 'floating_ip_get_by_address')
        db.floating_ip_get_by_address(ctxt, instance_ref['floating_ip']).\
                                      AndReturn(floating_ip_ref)
        self.mox.StubOutWithMock(db, 'floating_ip_update')
        db.floating_ip_update(ctxt, floating_ip_ref['address'], {'host': dest})
        
        self.mox.StubOutWithMock(db, 'instance_update')
        db.instance_update(ctxt, instance_ref['id'],
                           {'state_description': 'running',
                            'state': power_state.RUNNING, 'host': dest})
        self.mox.StubOutWithMock(db, 'volume_update')
        for v in instance_ref['volumes']:
            db.volume_update(ctxt, v['id'], {'status': 'in-use'})

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        conn._post_live_migration( ctxt, instance_ref, dest)
        self.mox.UnsetStubs()

    def test_post_live_migration_no_floating_ip(self):
        """
        _post_live_migration works as expected correctly 
        (in case instance doesnt have floaitng ip)
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        instance_ref = {'id':1, 'hostname':'i-00000001', 'host':dest, 
                       'fixed_ip':'dummyip', 'floating_ip':'dummyflip', 
                       'volumes':[{'id':1}, {'id':2} ]}
        network_ref = {'id':1, 'host':dest}
        floating_ip_ref = {'id':1, 'address':'1.1.1.1'}

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
        except: 
            return 
        fwmock.unfilter_instance(instance_ref)

        fixed_ip = instance_ref['fixed_ip']
        self.mox.StubOutWithMock(db, 'instance_get_fixed_address')
        db.instance_get_fixed_address(ctxt, instance_ref['id']).AndReturn(fixed_ip)
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        db.fixed_ip_update(ctxt, fixed_ip, {'host': dest})
        self.mox.StubOutWithMock(db, 'fixed_ip_get_network')
        db.fixed_ip_get_network(ctxt, fixed_ip).AndReturn(network_ref)
        self.mox.StubOutWithMock(db, 'network_update')
        db.network_update(ctxt, network_ref['id'], {'host': dest})

        self.mox.StubOutWithMock(db, 'instance_get_floating_address')
        db.instance_get_floating_address(ctxt, instance_ref['id']).AndReturn(None)
        self.mox.StubOutWithMock(libvirt_conn.LOG, 'info')
        libvirt_conn.LOG.info(_('post livemigration operation is started..'))
        libvirt_conn.LOG.info(_('floating_ip is not found for %s'), 
                              instance_ref['hostname'])
        # Checking last messages are ignored. may be no need to check so strictly?
        libvirt_conn.LOG.info(mox.IgnoreArg())
        libvirt_conn.LOG.info(mox.IgnoreArg())

        self.mox.StubOutWithMock(db, 'instance_update')
        db.instance_update(ctxt, instance_ref['id'],
                           {'state_description': 'running',
                            'state': power_state.RUNNING,
                            'host': dest})
        self.mox.StubOutWithMock(db, 'volume_update')
        for v in instance_ref['volumes']:
            db.volume_update(ctxt, v['id'], {'status': 'in-use'})

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        conn._post_live_migration( ctxt, instance_ref, dest)
        self.mox.UnsetStubs()

    def test_post_live_migration_no_floating_ip_with_exception(self):
        """
        _post_live_migration works as expected correctly 
        (in case instance doesnt have floaitng ip, and raise exception)
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        instance_ref = {'id':1, 'hostname':'i-00000001', 'host':dest, 
                       'fixed_ip':'dummyip', 'floating_ip':'dummyflip', 
                       'volumes':[{'id':1}, {'id':2} ]}
        network_ref = {'id':1, 'host':dest}
        floating_ip_ref = {'id':1, 'address':'1.1.1.1'}

        try: 
            nwmock, fwmock = self._driver_dependent_test_setup()
        except: 
            return 
        fwmock.unfilter_instance(instance_ref)

        fixed_ip = instance_ref['fixed_ip']
        self.mox.StubOutWithMock(db, 'instance_get_fixed_address')
        db.instance_get_fixed_address(ctxt, instance_ref['id']).AndReturn(fixed_ip)
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        db.fixed_ip_update(ctxt, fixed_ip, {'host': dest})
        self.mox.StubOutWithMock(db, 'fixed_ip_get_network')
        db.fixed_ip_get_network(ctxt, fixed_ip).AndReturn(network_ref)
        self.mox.StubOutWithMock(db, 'network_update')
        db.network_update(ctxt, network_ref['id'], {'host': dest})

        self.mox.StubOutWithMock(db, 'instance_get_floating_address')
        db.instance_get_floating_address(ctxt, instance_ref['id']).\
                                         AndRaise(exception.NotFound())
        self.mox.StubOutWithMock(libvirt_conn.LOG, 'info')
        libvirt_conn.LOG.info(_('post livemigration operation is started..'))
        libvirt_conn.LOG.info(_('floating_ip is not found for %s'),
                              instance_ref['hostname'])
        # the last message is ignored. may be no need to check so strictly?
        libvirt_conn.LOG.info(mox.IgnoreArg())
        libvirt_conn.LOG.info(mox.IgnoreArg())

        self.mox.StubOutWithMock(db, 'instance_update')
        db.instance_update(ctxt, instance_ref['id'],
                           {'state_description': 'running',
                            'state': power_state.RUNNING, 'host': dest})
        self.mox.StubOutWithMock(db, 'volume_update')
        for v in instance_ref['volumes']:
            db.volume_update(ctxt, v['id'], {'status': 'in-use'})

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        conn._post_live_migration( ctxt, instance_ref, dest)
        self.mox.UnsetStubs()

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
        self.fw = libvirt_conn.IptablesFirewallDriver()

    def tearDown(self):
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        super(IptablesFirewallTestCase, self).tearDown()

    def _p(self, *args, **kwargs):
        if 'iptables-restore' in args:
            print ' '.join(args), kwargs['stdin']
        if 'iptables-save' in args:
            return

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

    def test_static_filters(self):
        self.fw.execute = self._p
        instance_ref = db.instance_create(self.context,
                                          {'user_id': 'fake',
                                          'project_id': 'fake'})
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

        self.fw.add_instance(instance_ref)

        out_rules = self.fw.modify_rules(self.in_rules)

        in_rules = filter(lambda l: not l.startswith('#'), self.in_rules)
        for rule in in_rules:
            if not 'nova' in rule:
                self.assertTrue(rule in out_rules,
                                'Rule went missing: %s' % rule)

        instance_chain = None
        for rule in out_rules:
            # This is pretty crude, but it'll do for now
            if '-d 10.11.12.13 -j' in rule:
                instance_chain = rule.split(' ')[-1]
                break
        self.assertTrue(instance_chain, "The instance chain wasn't added")

        security_group_chain = None
        for rule in out_rules:
            # This is pretty crude, but it'll do for now
            if '-A %s -j' % instance_chain in rule:
                security_group_chain = rule.split(' ')[-1]
                break
        self.assertTrue(security_group_chain,
                        "The security group chain wasn't added")

        self.assertTrue('-A %s -p icmp -s 192.168.11.0/24 -j ACCEPT' % \
                               security_group_chain in out_rules,
                        "ICMP acceptance rule wasn't added")

        self.assertTrue('-A %s -p icmp -s 192.168.11.0/24 -m icmp --icmp-type'
                        ' 8 -j ACCEPT' % security_group_chain in out_rules,
                        "ICMP Echo Request acceptance rule wasn't added")

        self.assertTrue('-A %s -p tcp -s 192.168.10.0/24 -m multiport '
                        '--dports 80:81 -j ACCEPT' % security_group_chain \
                            in out_rules,
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
        _ensure_all_called()
        self.teardown_security_group()

