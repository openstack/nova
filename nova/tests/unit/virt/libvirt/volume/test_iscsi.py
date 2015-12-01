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

import mock
from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import iscsi


class LibvirtISCSIVolumeDriverTestCase(
        test_volume.LibvirtISCSIVolumeBaseTestCase):

    # TODO(mriedem): move this to os-brick
    def test_iscsiadm_discover_parsing(self):
        # Ensure that parsing iscsiadm discover ignores cruft.

        targets = [
            ["192.168.204.82:3260,1",
             ("iqn.2010-10.org.openstack:volume-"
              "f9b12623-6ce3-4dac-a71f-09ad4249bdd3")],
            ["192.168.204.82:3261,1",
             ("iqn.2010-10.org.openstack:volume-"
              "f9b12623-6ce3-4dac-a71f-09ad4249bdd4")]]

        # This slight wonkiness brought to you by pep8, as the actual
        # example output runs about 97 chars wide.
        sample_input = """Loading iscsi modules: done
Starting iSCSI initiator service: done
Setting up iSCSI targets: unused
%s %s
%s %s
""" % (targets[0][0], targets[0][1], targets[1][0], targets[1][1])
        driver = iscsi.LibvirtISCSIVolumeDriver("none")
        out = driver.connector._get_target_portals_from_iscsiadm_output(
            sample_input)
        self.assertEqual(targets, out)

    def test_libvirt_iscsi_driver(self, transport=None):
        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_conn)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.ISCSIConnector)

    # TODO(mriedem): move this to os-brick
    def test_sanitize_log_run_iscsiadm(self):
        # Tests that the parameters to the os-brick connector's
        # _run_iscsiadm function are sanitized for passwords when logged.
        def fake_debug(*args, **kwargs):
            self.assertIn('node.session.auth.password', args[0])
            self.assertNotIn('scrubme', args[0])

        def fake_execute(*args, **kwargs):
            return (None, None)

        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver.connector.set_execute(fake_execute)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        iscsi_properties = connection_info['data']
        with mock.patch.object(connector.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            libvirt_driver.connector._iscsiadm_update(
                iscsi_properties, 'node.session.auth.password', 'scrubme')

            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)

    def test_libvirt_iscsi_driver_get_config(self):
        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_conn)

        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self.assertEqual('block', tree.get('type'))
        self.assertEqual(device_path, tree.find('./source').get('dev'))
        self.assertEqual('raw', tree.find('./driver').get('type'))
        self.assertEqual('native', tree.find('./driver').get('io'))
