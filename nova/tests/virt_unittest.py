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

from xml.dom.minidom import parseString

from nova import db
from nova import flags
from nova import test
from nova.virt import libvirt_conn

FLAGS = flags.FLAGS


class LibvirtConnTestCase(test.TrialTestCase):
    def bitrot_test_get_uri_and_template(self):
        class MockDataModel(object):
            def __getitem__(self, name):
                return self.datamodel[name]

            def __init__(self):
                self.datamodel = { 'name' : 'i-cafebabe',
                                   'memory_kb' : '1024000',
                                   'basepath' : '/some/path',
                                   'bridge_name' : 'br100',
                                   'mac_address' : '02:12:34:46:56:67',
                                   'vcpus' : 2,
                                   'project_id' : None }

        type_uri_map = { 'qemu' : ('qemu:///system',
                                [lambda s: '<domain type=\'qemu\'>' in s,
                                 lambda s: 'type>hvm</type' in s,
                                 lambda s: 'emulator>/usr/bin/kvm' not in s]),
                         'kvm' : ('qemu:///system',
                                [lambda s: '<domain type=\'kvm\'>' in s,
                                 lambda s: 'type>hvm</type' in s,
                                 lambda s: 'emulator>/usr/bin/qemu<' not in s]),
                         'uml' : ('uml:///system',
                                [lambda s: '<domain type=\'uml\'>' in s,
                                 lambda s: 'type>uml</type' in s]),
                          }

        for (libvirt_type,(expected_uri, checks)) in type_uri_map.iteritems():
            FLAGS.libvirt_type = libvirt_type
            conn = libvirt_conn.LibvirtConnection(True)

            uri, template = conn.get_uri_and_template()
            self.assertEquals(uri, expected_uri)

            for i, check in enumerate(checks):
                xml = conn.to_xml(MockDataModel())
                self.assertTrue(check(xml), '%s failed check %d' % (xml, i))

        # Deliberately not just assigning this string to FLAGS.libvirt_uri and
        # checking against that later on. This way we make sure the
        # implementation doesn't fiddle around with the FLAGS.
        testuri = 'something completely different'
        FLAGS.libvirt_uri = testuri
        for (libvirt_type,(expected_uri, checks)) in type_uri_map.iteritems():
            FLAGS.libvirt_type = libvirt_type
            conn = libvirt_conn.LibvirtConnection(True)
            uri, template = conn.get_uri_and_template()
            self.assertEquals(uri, testuri)


class NWFilterTestCase(test.TrialTestCase):
    def setUp(self):
        super(NWFilterTestCase, self).setUp()

        class Mock(object):
            pass

        self.context = Mock()
        self.context.user = Mock()
        self.context.user.id = 'fake'
        self.context.user.is_superuser = lambda:True
        self.context.project = Mock()
        self.context.project.id = 'fake'

        self.fake_libvirt_connection = Mock()

        self.fw = libvirt_conn.NWFilterFirewall(self.fake_libvirt_connection)

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


        security_group = db.security_group_get_by_name({}, 'fake', 'testgroup')

        xml = self.fw.security_group_to_nwfilter_xml(security_group.id)

        dom = parseString(xml)
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
        self.assertEqual(ip_conditions[0].getAttribute('srcipaddr'), '0.0.0.0/0')
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

        return db.security_group_get_by_name({}, 'fake', 'testgroup')

    def test_creates_base_rule_first(self):
        self.defined_filters = []
        self.fake_libvirt_connection.listNWFilters = lambda:self.defined_filters
        self.base_filter_defined = False
        self.i = 0
        def _filterDefineXMLMock(xml):
            dom = parseString(xml)
            name = dom.firstChild.getAttribute('name')
            if self.i == 0:
                self.assertEqual(dom.firstChild.getAttribute('name'),
                                 'nova-base-filter')
            elif self.i == 1:
                self.assertTrue(name.startswith('nova-secgroup-'),
                             'unexpected name: %s' % name)
            elif self.i == 2:
                self.assertTrue(name.startswith('nova-instance-'),
                             'unexpected name: %s' % name)

            self.defined_filters.append(name)
            self.i += 1
            return True

        def _ensure_all_called(_):
            self.assertEqual(self.i, 3)

        self.fake_libvirt_connection.nwfilterDefineXML = _filterDefineXMLMock

        inst_id = db.instance_create({}, { 'user_id' : 'fake', 'project_id' : 'fake' })
        security_group = self.setup_and_return_security_group()

        db.instance_add_security_group({}, inst_id, security_group.id)
        instance = db.instance_get({}, inst_id)

        d = self.fw.setup_nwfilters_for_instance(instance)
        d.addCallback(_ensure_all_called)
        d.addCallback(lambda _:self.teardown_security_group())

        return d
