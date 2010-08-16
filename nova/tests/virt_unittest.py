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

from nova import flags
from nova import test
from nova.virt import libvirt_conn

FLAGS = flags.FLAGS


class LibvirtConnTestCase(test.TrialTestCase):
    def test_get_uri_and_template(self):
        class MockDataModel(object):
            def __init__(self):
                self.datamodel = { 'name' : 'i-cafebabe',
                                   'memory_kb' : '1024000',
                                   'basepath' : '/some/path',
                                   'bridge_name' : 'br100',
                                   'mac_address' : '02:12:34:46:56:67',
                                   'vcpus' : 2 }

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
                xml = conn.toXml(MockDataModel())
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

