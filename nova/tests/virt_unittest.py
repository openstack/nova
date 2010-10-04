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

from xml.etree.ElementTree import fromstring as parseXml

from nova import flags
from nova import test
from nova.virt import libvirt_conn

FLAGS = flags.FLAGS

class LibvirtConnTestCase(test.TrialTestCase):
    def test_get_uri_and_template(self):
        instance = { 'name'           : 'i-cafebabe',
                     'id'             : 'i-cafebabe',
                     'memory_kb'      : '1024000',
                     'basepath'       : '/some/path',
                     'bridge_name'    : 'br100',
                     'mac_address'    : '02:12:34:46:56:67',
                     'vcpus'          : 2,
                     'project_id'     : 'fake',
                     'ip_address'     : '10.11.12.13',
                     'bridge'         : 'br101',
                     'instance_type'  : 'm1.small'}

        type_uri_map = { 'qemu' : ('qemu:///system',
                              [(lambda t: t.find('.').tag, 'domain'),
                               (lambda t: t.find('.').get('type'), 'qemu'),
                               (lambda t: t.find('./os/type').text, 'hvm'),
                               (lambda t: t.find('./devices/emulator'), None)]),
                         'kvm' : ('qemu:///system',
                              [(lambda t: t.find('.').tag, 'domain'),
                               (lambda t: t.find('.').get('type'), 'kvm'),
                               (lambda t: t.find('./os/type').text, 'hvm'),
                               (lambda t: t.find('./devices/emulator'), None)]),
                         'uml' : ('uml:///system',
                              [(lambda t: t.find('.').tag, 'domain'),
                               (lambda t: t.find('.').get('type'), 'uml'),
                               (lambda t: t.find('./os/type').text, 'uml')]),
                       }
        common_checks = [(lambda t: \
                             t.find('./devices/interface/filterref/parameter') \
                              .get('name'), 'IP'),
                         (lambda t: \
                             t.find('./devices/interface/filterref/parameter') \
                              .get('value'), '10.11.12.13')]

        for (libvirt_type,(expected_uri, checks)) in type_uri_map.iteritems():
            FLAGS.libvirt_type = libvirt_type
            conn = libvirt_conn.LibvirtConnection(True)

            uri, template = conn.get_uri_and_template()
            self.assertEquals(uri, expected_uri)

            xml = conn.to_xml(instance)
            tree = parseXml(xml)
            for i, (check, expected_result) in enumerate(checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s failed check %d' % (xml, i))

            for i, (check, expected_result) in enumerate(common_checks):
                self.assertEqual(check(tree),
                                 expected_result,
                                 '%s failed common check %d' % (xml, i))

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

