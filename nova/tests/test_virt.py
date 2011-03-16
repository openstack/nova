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

import eventlet
import mox
import os
import re
import sys

from xml.etree.ElementTree import fromstring as xml_to_tree
from xml.dom.minidom import parseString as xml_to_dom

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.api.ec2 import cloud
from nova.auth import manager
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova.db.sqlalchemy import models
from nova.virt import libvirt_conn

libvirt = None
FLAGS = flags.FLAGS
flags.DECLARE('instances_path', 'nova.compute.manager')


def _concurrency(wait, done, target):
    wait.wait()
    done.send()


class CacheConcurrencyTestCase(test.TestCase):
    def setUp(self):
        super(CacheConcurrencyTestCase, self).setUp()

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
        conn = libvirt_conn.LibvirtConnection
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
            self.assertTrue('fname' in conn._image_sems)
        finally:
            wait1.send()
        done1.wait()
        eventlet.sleep(0)
        self.assertTrue(done2.ready())
        self.assertFalse('fname' in conn._image_sems)

    def test_different_fname_concurrency(self):
        """Ensures that two different fname caches are concurrent"""
        conn = libvirt_conn.LibvirtConnection
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
        self.context = context.get_admin_context()
        FLAGS.instances_path = ''
        self.call_libvirt_dependant_setup = False

    test_ip = '10.11.12.13'
    test_instance = {'memory_kb':     '1024000',
                     'basepath':      '/some/path',
                     'bridge_name':   'br100',
                     'mac_address':   '02:12:34:46:56:67',
                     'vcpus':         2,
                     'project_id':    'fake',
                     'bridge':        'br101',
                     'instance_type': 'm1.small'}

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
        libvirt_conn.libvirt = __import__('libvirt')
        libvirt_conn.libxml2 = __import__('libxml2')
        return True

    def create_fake_libvirt_mock(self, **kwargs):
        """Defining mocks for LibvirtConnection(libvirt is not used)."""

        # A fake libvirt.virConnect
        class FakeLibvirtConnection(object):
            pass

        # A fake libvirt_conn.IptablesFirewallDriver
        class FakeIptablesFirewallDriver(object):

            def __init__(self, **kwargs):
                pass

            def setattr(self, key, val):
                self.__setattr__(key, val)

        # Creating mocks
        fake = FakeLibvirtConnection()
        fakeip = FakeIptablesFirewallDriver
        # Customizing above fake if necessary
        for key, val in kwargs.items():
            fake.__setattr__(key, val)

        # Inevitable mocks for libvirt_conn.LibvirtConnection
        self.mox.StubOutWithMock(libvirt_conn.utils, 'import_class')
        libvirt_conn.utils.import_class(mox.IgnoreArg()).AndReturn(fakeip)
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection, '_conn')
        libvirt_conn.LibvirtConnection._conn = fake

    def create_service(self, **kwargs):
        service_ref = {'host': kwargs.get('host', 'dummy'),
                       'binary': 'nova-compute',
                       'topic': 'compute',
                       'report_count': 0,
                       'availability_zone': 'zone'}

        return db.service_create(context.get_admin_context(), service_ref)

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
                        'lxc': ('lxc:///',
                            [(lambda t: t.find('.').get('type'), 'lxc'),
                            (lambda t: t.find('./os/type').text, 'exe')]),
                        'xen': ('xen:///',
                             [(lambda t: t.find('.').get('type'), 'xen'),
                              (lambda t: t.find('./os/type').text, 'linux')]),
                              }

        for hypervisor_type in ['qemu', 'kvm', 'lxc', 'xen']:
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
        db.instance_destroy(user_context, instance_ref['id'])

    def test_update_available_resource_works_correctly(self):
        """Confirm compute_node table is updated successfully."""
        org_path = FLAGS.instances_path = ''
        FLAGS.instances_path = '.'

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
        self.mox.StubOutWithMock(libvirt_conn.LibvirtConnection,
                                 'get_cpu_info')
        libvirt_conn.LibvirtConnection.get_cpu_info().AndReturn('cpuinfo')

        # Start test
        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
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
        FLAGS.instances_path = org_path

    def test_update_resource_info_no_compute_record_found(self):
        """Raise exception if no recorde found on services table."""
        org_path = FLAGS.instances_path = ''
        FLAGS.instances_path = '.'
        self.create_fake_libvirt_mock()

        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(exception.Invalid,
                          conn.update_available_resource,
                          self.context, 'dummy')

        FLAGS.instances_path = org_path

    def test_ensure_filtering_rules_for_instance_timeout(self):
        """ensure_filtering_fules_for_instance() finishes with timeout."""
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        # Preparing mocks
        def fake_none(self):
            return

        def fake_raise(self):
            raise libvirt.libvirtError('ERR')

        self.create_fake_libvirt_mock(nwfilterLookupByName=fake_raise)
        instance_ref = db.instance_create(self.context, self.test_instance)

        # Start test
        self.mox.ReplayAll()
        try:
            conn = libvirt_conn.LibvirtConnection(False)
            conn.firewall_driver.setattr('setup_basic_filtering', fake_none)
            conn.firewall_driver.setattr('prepare_instance_filter', fake_none)
            conn.ensure_filtering_rules_for_instance(instance_ref)
        except exception.Error, e:
            c1 = (0 <= e.message.find('Timeout migrating for'))
        self.assertTrue(c1)

        db.instance_destroy(self.context, instance_ref['id'])

    def test_live_migration_raises_exception(self):
        """Confirms recover method is called when exceptions are raised."""
        # Skip if non-libvirt environment
        if not self.lazy_load_library_exists():
            return

        # Preparing data
        self.compute = utils.import_object(FLAGS.compute_manager)
        instance_dict = {'host': 'fake', 'state': power_state.RUNNING,
                         'state_description': 'running'}
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

        # Start test
        self.mox.ReplayAll()
        conn = libvirt_conn.LibvirtConnection(False)
        self.assertRaises(libvirt.libvirtError,
                      conn._live_migration,
                      self.context, instance_ref, 'dest', '',
                      self.compute.recover_live_migration)

        instance_ref = db.instance_get(self.context, instance_ref['id'])
        self.assertTrue(instance_ref['state_description'] == 'running')
        self.assertTrue(instance_ref['state'] == power_state.RUNNING)
        volume_ref = db.volume_get(self.context, volume_ref['id'])
        self.assertTrue(volume_ref['status'] == 'in-use')

        db.volume_destroy(self.context, volume_ref['id'])
        db.instance_destroy(self.context, instance_ref['id'])

    def tearDown(self):
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        super(LibvirtConnTestCase, self).tearDown()


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
        def fake_iptables_execute(*cmd, **kwargs):
            process_input = kwargs.get('process_input', None)
            if cmd == ('sudo', 'ip6tables-save', '-t', 'filter'):
                return '\n'.join(self.in6_filter_rules), None
            if cmd == ('sudo', 'iptables-save', '-t', 'filter'):
                return '\n'.join(self.in_filter_rules), None
            if cmd == ('sudo', 'iptables-save', '-t', 'nat'):
                return '\n'.join(self.in_nat_rules), None
            if cmd == ('sudo', 'iptables-restore'):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out_rules = lines
                return '', ''
            if cmd == ('sudo', 'ip6tables-restore'):
                lines = process_input.split('\n')
                if '*filter' in lines:
                    self.out6_rules = lines
                return '', ''
            print cmd, kwargs

        from nova.network import linux_net
        linux_net.iptables_manager.execute = fake_iptables_execute

        self.fw.prepare_instance_filter(instance_ref)
        self.fw.apply_instance_filter(instance_ref)

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

        regex = re.compile('-A .* -p icmp -s 192.168.11.0/24 -j ACCEPT')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP acceptance rule wasn't added")

        regex = re.compile('-A .* -p icmp -s 192.168.11.0/24 -m icmp '
                           '--icmp-type 8 -j ACCEPT')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "ICMP Echo Request acceptance rule wasn't added")

        regex = re.compile('-A .* -p tcp -s 192.168.10.0/24 -m multiport '
                           '--dports 80:81 -j ACCEPT')
        self.assertTrue(len(filter(regex.match, self.out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")
        db.instance_destroy(admin_ctxt, instance_ref['id'])


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
        super(NWFilterTestCase, self).tearDown()

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
        db.instance_destroy(admin_ctxt, instance_ref['id'])
