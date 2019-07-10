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

import nova.conf
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import net

CONF = nova.conf.CONF


class LibvirtNetVolumeDriverTestCase(
    test_volume.LibvirtISCSIVolumeBaseTestCase):
    """Tests the libvirt network volume driver."""

    def _assertNetworkAndProtocolEquals(self, tree):
        self.assertEqual('network', tree.get('type'))
        self.assertEqual('rbd', tree.find('./source').get('protocol'))
        rbd_name = '%s/%s' % ('rbd', self.name)
        self.assertEqual(rbd_name, tree.find('./source').get('name'))

    def _assertISCSINetworkAndProtocolEquals(self, tree):
        self.assertEqual('network', tree.get('type'))
        self.assertEqual('iscsi', tree.find('./source').get('protocol'))
        iscsi_name = '%s/%s' % (self.iqn, self.vol['id'])
        self.assertEqual(iscsi_name, tree.find('./source').get('name'))

    def sheepdog_connection(self, volume):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name']
            }
        }

    def test_libvirt_sheepdog_driver(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.sheepdog_connection(self.vol)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('network', tree.get('type'))
        self.assertEqual('sheepdog', tree.find('./source').get('protocol'))
        self.assertEqual(self.name, tree.find('./source').get('name'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def rbd_connection(self, volume):
        return {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % ('rbd', volume['name']),
                'auth_enabled': CONF.libvirt.rbd_user is not None,
                'auth_username': CONF.libvirt.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': CONF.libvirt.rbd_secret_uuid,
                'qos_specs': {
                    'total_bytes_sec': '1048576',
                    'read_iops_sec': '500',
                    }
            }
        }

    def test_libvirt_rbd_driver(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./source/auth'))
        self.assertEqual('1048576', tree.find('./iotune/total_bytes_sec').text)
        self.assertEqual('500', tree.find('./iotune/read_iops_sec').text)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_hosts(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        hosts = ['example.com', '1.2.3.4', '::1']
        ports = [None, '6790', '6791']
        connection_info['data']['hosts'] = hosts
        connection_info['data']['ports'] = ports
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./source/auth'))
        found_hosts = tree.findall('./source/host')
        self.assertEqual(hosts, [host.get('name') for host in found_hosts])
        self.assertEqual(ports, [host.get('port') for host in found_hosts])
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_auth_enabled(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = True
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(self.user, tree.find('./auth').get('username'))
        self.assertEqual(secret_type, tree.find('./auth/secret').get('type'))
        self.assertEqual(self.uuid, tree.find('./auth/secret').get('uuid'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_auth_enabled_flags(self):
        # The values from the cinder connection_info take precedence over
        # nova.conf values.
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = True
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        flags_uuid = '37152720-1785-11e2-a740-af0c1d8b8e4b'
        flags_user = 'bar'
        self.flags(rbd_user=flags_user,
                   rbd_secret_uuid=flags_uuid,
                   group='libvirt')

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(self.user, tree.find('./auth').get('username'))
        self.assertEqual(secret_type, tree.find('./auth/secret').get('type'))
        self.assertEqual(self.uuid, tree.find('./auth/secret').get('uuid'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_auth_enabled_flags_secret_uuid_fallback(self):
        """The values from the cinder connection_info take precedence over
        nova.conf values, unless it's old connection data where the
        secret_uuid wasn't set on the cinder side for the original connection
        which is now persisted in the
        nova.block_device_mappings.connection_info column and used here. In
        this case we fallback to use the local config for secret_uuid and
        username.
        """
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = True
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        # Fake out cinder not setting the secret_uuid in the old connection.
        connection_info['data']['secret_uuid'] = None

        flags_uuid = '37152720-1785-11e2-a740-af0c1d8b8e4b'
        flags_user = 'bar'
        self.flags(rbd_user=flags_user,
                   rbd_secret_uuid=flags_uuid,
                   group='libvirt')

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(flags_user, tree.find('./auth').get('username'))
        self.assertEqual(secret_type, tree.find('./auth/secret').get('type'))
        # Assert that the secret_uuid comes from CONF.libvirt.rbd_secret_uuid.
        self.assertEqual(flags_uuid, tree.find('./auth/secret').get('uuid'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_auth_disabled(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = False
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./auth'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_libvirt_rbd_driver_auth_disabled_flags_override(self):
        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = False
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        # NOTE: Supplying the rbd_secret_uuid will enable authentication
        # locally in nova-compute even if not enabled in nova-volume/cinder
        flags_uuid = '37152720-1785-11e2-a740-af0c1d8b8e4b'
        flags_user = 'bar'
        self.flags(rbd_user=flags_user,
                   rbd_secret_uuid=flags_uuid,
                   group='libvirt')

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(flags_user, tree.find('./auth').get('username'))
        self.assertEqual(secret_type, tree.find('./auth/secret').get('type'))
        self.assertEqual(flags_uuid, tree.find('./auth/secret').get('uuid'))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

    def test_extend_volume(self):
        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        requested_size = 20 * pow(1024, 3)  # 20GiB

        libvirt_driver = net.LibvirtNetVolumeDriver(self.fake_host)
        new_size = libvirt_driver.extend_volume(connection_info,
                                                mock.sentinel.instance,
                                                requested_size)

        self.assertEqual(requested_size, new_size)
