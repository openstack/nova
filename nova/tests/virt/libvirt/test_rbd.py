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

from nova.openstack.common import log as logging
from nova import test
from nova import utils
from nova.virt.libvirt import rbd


LOG = logging.getLogger(__name__)


CEPH_MON_DUMP = """dumped monmap epoch 1
{ "epoch": 1,
  "fsid": "33630410-6d93-4d66-8e42-3b953cf194aa",
  "modified": "2013-05-22 17:44:56.343618",
  "created": "2013-05-22 17:44:56.343618",
  "mons": [
        { "rank": 0,
          "name": "a",
          "addr": "[::1]:6789\/0"},
        { "rank": 1,
          "name": "b",
          "addr": "[::1]:6790\/0"},
        { "rank": 2,
          "name": "c",
          "addr": "[::1]:6791\/0"},
        { "rank": 3,
          "name": "d",
          "addr": "127.0.0.1:6792\/0"},
        { "rank": 4,
          "name": "e",
          "addr": "example.com:6791\/0"}],
  "quorum": [
        0,
        1,
        2]}
"""


class RbdTestCase(test.NoDBTestCase):

    @mock.patch.object(rbd, 'rbd')
    @mock.patch.object(rbd, 'rados')
    def setUp(self, mock_rados, mock_rbd):
        super(RbdTestCase, self).setUp()

        self.mock_rados = mock_rados
        self.mock_rados.Rados = mock.Mock
        self.mock_rados.Rados.ioctx = mock.Mock()
        self.mock_rados.Rados.connect = mock.Mock()
        self.mock_rados.Rados.shutdown = mock.Mock()
        self.mock_rados.Rados.open_ioctx = mock.Mock()
        self.mock_rados.Rados.open_ioctx.return_value = \
            self.mock_rados.Rados.ioctx
        self.mock_rados.Error = Exception

        self.mock_rbd = mock_rbd
        self.mock_rbd.RBD = mock.Mock
        self.mock_rbd.Image = mock.Mock
        self.mock_rbd.Image.close = mock.Mock()
        self.mock_rbd.RBD.Error = Exception

        self.rbd_pool = 'rbd'
        self.driver = rbd.RBDDriver(self.rbd_pool, None, None)

        self.volume_name = u'volume-00000001'

    def tearDown(self):
        super(RbdTestCase, self).tearDown()

    @mock.patch.object(utils, 'execute')
    def test_get_mon_addrs(self, mock_execute):
        mock_execute.return_value = (CEPH_MON_DUMP, '')
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.assertEqual((hosts, ports), self.driver.get_mon_addrs())

    @mock.patch.object(rbd, 'RBDVolumeProxy')
    def test_resize(self, mock_proxy):
        size = 1024
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.driver.resize(self.volume_name, size)
        proxy.resize.assert_called_once_with(size)

    @mock.patch.object(rbd.RBDDriver, '_disconnect_from_rados')
    @mock.patch.object(rbd.RBDDriver, '_connect_to_rados')
    @mock.patch.object(rbd, 'rbd')
    @mock.patch.object(rbd, 'rados')
    def test_rbd_volume_proxy_init(self, mock_rados, mock_rbd,
                                   mock_connect_from_rados,
                                   mock_disconnect_from_rados):
        mock_connect_from_rados.return_value = (None, None)
        mock_disconnect_from_rados.return_value = (None, None)

        with rbd.RBDVolumeProxy(self.driver, self.volume_name):
            mock_connect_from_rados.assert_called_once_with(None)
            self.assertFalse(mock_disconnect_from_rados.called)

        mock_disconnect_from_rados.assert_called_once_with(None, None)

    @mock.patch.object(rbd, 'rbd')
    @mock.patch.object(rbd, 'rados')
    def test_connect_to_rados_default(self, mock_rados, mock_rbd):
        ret = self.driver._connect_to_rados()
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with(self.rbd_pool)

    @mock.patch.object(rbd, 'rbd')
    @mock.patch.object(rbd, 'rados')
    def test_connect_to_rados_different_pool(self, mock_rados, mock_rbd):
        ret = self.driver._connect_to_rados('alt_pool')
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with('alt_pool')

    @mock.patch.object(rbd, 'rados')
    def test_connect_to_rados_error(self, mock_rados):
        mock_rados.Rados.open_ioctx.side_effect = mock_rados.Error
        self.assertRaises(mock_rados.Error, self.driver._connect_to_rados)
        mock_rados.Rados.open_ioctx.assert_called_once_with(self.rbd_pool)
        mock_rados.Rados.shutdown.assert_called_once_with()

    def test_ceph_args_none(self):
        self.driver.rbd_user = None
        self.driver.ceph_conf = None
        self.assertEqual([], self.driver.ceph_args())

    def test_ceph_args_rbd_user(self):
        self.driver.rbd_user = 'foo'
        self.driver.ceph_conf = None
        self.assertEqual(['--id', 'foo'], self.driver.ceph_args())

    def test_ceph_args_ceph_conf(self):
        self.driver.rbd_user = None
        self.driver.ceph_conf = '/path/bar.conf'
        self.assertEqual(['--conf', '/path/bar.conf'],
                         self.driver.ceph_args())

    def test_ceph_args_rbd_user_and_ceph_conf(self):
        self.driver.rbd_user = 'foo'
        self.driver.ceph_conf = '/path/bar.conf'
        self.assertEqual(['--id', 'foo', '--conf', '/path/bar.conf'],
                         self.driver.ceph_args())

    @mock.patch.object(rbd, 'RBDVolumeProxy')
    def test_exists(self, mock_proxy):
        proxy = mock_proxy.return_value
        self.assertTrue(self.driver.exists(self.volume_name))
        proxy.__enter__.assert_called_once_with()
        proxy.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd, 'rbd')
    @mock.patch.object(rbd, 'rados')
    @mock.patch.object(rbd, 'RADOSClient')
    def test_cleanup_volumes(self, mock_client, mock_rados, mock_rbd):
        instance = {'uuid': '12345'}

        rbd = mock_rbd.RBD.return_value
        rbd.list.return_value = ['12345_test', '111_test']

        client = mock_client.return_value
        self.driver.cleanup_volumes(instance)
        rbd.remove.assert_called_once_with(client.ioctx, '12345_test')
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)
