# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 University of Southern California
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

import functools
import mox
import StringIO
import stubout

from nova import flags
from nova import utils
from nova import test
from nova.compute import power_state
from nova import context
from nova.tests import fake_utils
from nova import exception

from nova.virt.baremetal import proxy
from nova.virt.baremetal import dom

FLAGS = flags.FLAGS


# Same fake_domains is used by different classes,
# but different fake_file is used by different classes for unit test.
fake_domains = [{'status': 1, 'name': 'instance-00000001',
                 'memory_kb': 16777216, 'kernel_id': '1896115634',
                 'ramdisk_id': '', 'image_id': '1552326678',
                 'vcpus': 1, 'node_id': 6,
                 'mac_address': '02:16:3e:01:4e:c9',
                 'ip_address': '10.5.1.2'}]


class DomainReadWriteTestCase(test.TestCase):

    def setUp(self):
        super(DomainReadWriteTestCase, self).setUp()
        self.flags(baremetal_driver='fake')

    def test_read_domain_with_empty_list(self):
        """Read a file that contains no domains"""

        self.mox.StubOutWithMock(__builtin__, 'open')
        try:
            fake_file = StringIO.StringIO('[]')
            open('/tftpboot/test_fake_dom_file', 'r').AndReturn(fake_file)

            self.mox.ReplayAll()

            domains = dom.read_domains('/tftpboot/test_fake_dom_file')

            self.assertEqual(domains, [])

        finally:
            self.mox.UnsetStubs()

    def test_read_domain(self):
        """Read a file that contains at least one domain"""
        fake_file = StringIO.StringIO('''[{"status": 1,
         "image_id": "1552326678", "vcpus": 1, "node_id": 6,
         "name": "instance-00000001", "memory_kb": 16777216,
         "mac_address": "02:16:3e:01:4e:c9", "kernel_id": "1896115634",
         "ramdisk_id": "", "ip_address": "10.5.1.2"}]''')

        self.mox.StubOutWithMock(__builtin__, 'open')
        try:
            open('/tftpboot/test_fake_dom_file', 'r').AndReturn(fake_file)

            self.mox.ReplayAll()

            domains = dom.read_domains('/tftpboot/test_fake_dom_file')

            self.assertEqual(domains, fake_domains)

        finally:
            self.mox.UnsetStubs()

    def test_read_no_file(self):
        """Try to read when the file does not exist

        This should through and IO exception"""

        self.mox.StubOutWithMock(__builtin__, 'open')
        try:
            open('/tftpboot/test_fake_dom_file',
                 'r').AndRaise(IOError(2, 'No such file or directory',
                                       '/tftpboot/test_fake_dom_file'))

            self.mox.ReplayAll()

            self.assertRaises(exception.NotFound, dom.read_domains,
                       '/tftpboot/test_fake_dom_file')

        finally:
            self.mox.UnsetStubs()

    def assertJSONEquals(self, x, y):
        """Check if two json strings represent the equivalent Python object"""
        self.assertEquals(utils.loads(x), utils.loads(y))
        return utils.loads(x) == utils.loads(y)

    def test_write_domain(self):
        """Write the domain to file"""
        self.mox.StubOutWithMock(__builtin__, 'open')
        mock_file = self.mox.CreateMock(file)
        expected_json = '''[{"status": 1,
               "image_id": "1552326678", "vcpus": 1, "node_id": 6,
               "name": "instance-00000001", "memory_kb": 16777216,
               "mac_address": "02:16:3e:01:4e:c9", "kernel_id": "1896115634",
               "ramdisk_id": "", "ip_address": "10.5.1.2"}]'''
        try:
            open('/tftpboot/test_fake_dom_file', 'w').AndReturn(mock_file)

            # Check if the argument to file.write() represents the same
            # Python object as expected_json
            # We can't do an exact string comparison
            # because of ordering and whitespace
            mock_file.write(mox.Func(functools.partial(self.assertJSONEquals,
                                                       expected_json)))
            mock_file.close()

            self.mox.ReplayAll()

            dom.write_domains('/tftpboot/test_fake_dom_file', fake_domains)

        finally:
            self.mox.UnsetStubs()


class BareMetalDomTestCase(test.TestCase):

    def setUp(self):
        super(BareMetalDomTestCase, self).setUp()
        self.flags(baremetal_driver='fake')
        # Stub out utils.execute
        self.stubs = stubout.StubOutForTesting()
        fake_utils.stub_out_utils_execute(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(BareMetalDomTestCase, self).tearDown()

        # Reset the singleton state
        dom.BareMetalDom._instance = None
        dom.BareMetalDom._is_init = False

    def test_read_domain_only_once(self):
        """Confirm that the domain is read from a file only once,
        even if the object is instantiated multiple times"""
        self.mox.StubOutWithMock(dom, 'read_domains')
        self.mox.StubOutWithMock(dom, 'write_domains')

        dom.read_domains('/tftpboot/test_fake_dom_file').AndReturn([])
        dom.write_domains('/tftpboot/test_fake_dom_file', [])

        self.mox.ReplayAll()

        # Instantiate multiple instances
        x = dom.BareMetalDom()
        x = dom.BareMetalDom()
        x = dom.BareMetalDom()

    def test_init_no_domains(self):

        # Create the mock objects
        self.mox.StubOutWithMock(dom, 'read_domains')
        self.mox.StubOutWithMock(dom, 'write_domains')

        dom.read_domains('/tftpboot/test_fake_dom_file').AndReturn([])
        dom.write_domains('/tftpboot/test_fake_dom_file', [])

        self.mox.ReplayAll()

        # Code under test
        bmdom = dom.BareMetalDom()

        # Expectd values
        self.assertEqual(bmdom.fake_dom_nums, 0)

    def test_init_remove_non_running_domain(self):
        """Check to see that all entries in the domain list are removed
        except for the one that is in the running state"""

        fake_file = StringIO.StringIO()

        domains = [dict(node_id=1, name='i-00000001',
                        status=power_state.NOSTATE),
              dict(node_id=2, name='i-00000002', status=power_state.RUNNING),
              dict(node_id=3, name='i-00000003', status=power_state.BLOCKED),
              dict(node_id=4, name='i-00000004', status=power_state.PAUSED),
              dict(node_id=5, name='i-00000005', status=power_state.SHUTDOWN),
              dict(node_id=6, name='i-00000006', status=power_state.SHUTOFF),
              dict(node_id=7, name='i-00000007', status=power_state.CRASHED),
              dict(node_id=8, name='i-00000008', status=power_state.SUSPENDED),
              dict(node_id=9, name='i-00000009', status=power_state.FAILED)]

        # Create the mock objects
        self.mox.StubOutWithMock(dom, 'read_domains')
        self.mox.StubOutWithMock(dom, 'write_domains')
        dom.read_domains('/tftpboot/test_fake_dom_file').AndReturn(domains)
        dom.write_domains('/tftpboot/test_fake_dom_file', domains)

        self.mox.ReplayAll()

        # Code under test
        bmdom = dom.BareMetalDom()

        self.assertEqual(bmdom.domains, [{'node_id': 2,
                                          'name': 'i-00000002',
                                          'status': power_state.RUNNING}])
        self.assertEqual(bmdom.fake_dom_nums, 1)

    def test_find_domain(self):
        domain = {'status': 1, 'name': 'instance-00000001',
                    'memory_kb': 16777216, 'kernel_id': '1896115634',
                    'ramdisk_id': '', 'image_id': '1552326678',
                    'vcpus': 1, 'node_id': 6,
                    'mac_address': '02:16:3e:01:4e:c9',
                    'ip_address': '10.5.1.2'}

        # Create the mock objects
        self.mox.StubOutWithMock(dom, 'read_domains')
        self.mox.StubOutWithMock(dom, 'write_domains')

        # Expected calls
        dom.read_domains('/tftpboot/'
                         'test_fake_dom_file').AndReturn(fake_domains)
        dom.write_domains('/tftpboot/test_fake_dom_file', fake_domains)

        self.mox.ReplayAll()

        # Code under test
        bmdom = dom.BareMetalDom()

        # Expected values
        self.assertEquals(bmdom.find_domain('instance-00000001'), domain)


class ProxyBareMetalTestCase(test.TestCase):

    test_ip = '10.11.12.13'
    test_instance = {'memory_kb': '1024000',
                     'basepath': '/some/path',
                     'bridge_name': 'br100',
                     'mac_address': '02:12:34:46:56:67',
                     'vcpus': 2,
                     'project_id': 'fake',
                     'bridge': 'br101',
                     'image_ref': '123456',
                     'instance_type_id': '5'}  # m1.small

    def setUp(self):
        super(ProxyBareMetalTestCase, self).setUp()
        self.flags(baremetal_driver='fake')
        self.context = context.get_admin_context()
        fake_utils.stub_out_utils_execute(self.stubs)

    def test_get_info(self):
        # Create the mock objects
        self.mox.StubOutWithMock(dom, 'read_domains')
        self.mox.StubOutWithMock(dom, 'write_domains')

        # Expected calls
        dom.read_domains('/tftpboot/'
                         'test_fake_dom_file').AndReturn(fake_domains)
        dom.write_domains('/tftpboot/test_fake_dom_file', fake_domains)

        self.mox.ReplayAll()

        # Code under test
        conn = proxy.get_connection(True)
        # TODO: this is not a very good fake instance
        info = conn.get_info({'name': 'instance-00000001'})

        # Expected values
        self.assertEquals(info['mem'], 16777216)
        self.assertEquals(info['state'], 1)
        self.assertEquals(info['num_cpu'], 1)
        self.assertEquals(info['cpu_time'], 100)
        self.assertEquals(info['max_mem'], 16777216)
