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
from nova.openstack.common import units
from nova import test
from nova import utils
from nova.virt.libvirt import rbd_utils


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


class RBDTestCase(test.NoDBTestCase):

    def setUp(self):
        super(RBDTestCase, self).setUp()

        self.mock_rbd = mock.Mock()
        self.mock_rados = mock.Mock()
        self.mock_rados.Rados = mock.Mock
        self.mock_rados.Rados.ioctx = mock.Mock()

        self.mock_rbd.RBD = mock.Mock
        self.mock_rbd.Image = mock.Mock
        self.mock_rbd.Image.close = mock.Mock()
        self.mock_rbd.RBD.Error = Exception
        self.mock_rados.Error = Exception

        self.rbd_pool = 'rbd'
        self.driver = rbd_utils.RBDDriver(self.rbd_pool, None, None,
                                          rbd_lib=self.mock_rbd,
                                          rados_lib=self.mock_rados)

        self.volume_name = u'volume-00000001'

    def tearDown(self):
        super(RBDTestCase, self).tearDown()

    def test_get_mon_addrs(self):
        with mock.patch.object(utils, 'execute') as mock_execute:
            mock_execute.return_value = (CEPH_MON_DUMP, '')
            hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
            ports = ['6789', '6790', '6791', '6792', '6791']
            self.assertEqual((hosts, ports), self.driver.get_mon_addrs())

    def test_resize(self):
        size = 1024

        with mock.patch.object(rbd_utils, 'RBDVolumeProxy') as proxy_init:
            proxy = proxy_init.return_value
            proxy.__enter__.return_value = proxy
            self.driver.resize(self.volume_name, size)
            proxy.resize.assert_called_once_with(size * units.Ki)

    def test_rbd_volume_proxy_init(self):
        with mock.patch.object(self.driver, '_connect_to_rados') as \
                mock_connect_from_rados:
            with mock.patch.object(self.driver, '_disconnect_from_rados') as \
                    mock_disconnect_from_rados:
                mock_connect_from_rados.return_value = (None, None)
                mock_disconnect_from_rados.return_value = (None, None)

                with rbd_utils.RBDVolumeProxy(self.driver, self.volume_name):
                    mock_connect_from_rados.assert_called_once()
                    self.assertFalse(mock_disconnect_from_rados.called)

                mock_disconnect_from_rados.assert_called_once()

    def test_connect_to_rados(self):
        self.mock_rados.Rados.connect = mock.Mock()
        self.mock_rados.Rados.shutdown = mock.Mock()
        self.mock_rados.Rados.open_ioctx = mock.Mock()
        self.mock_rados.Rados.open_ioctx.return_value = \
            self.mock_rados.Rados.ioctx

        # default configured pool
        ret = self.driver._connect_to_rados()
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with(self.rbd_pool)

        # different pool
        ret = self.driver._connect_to_rados('alt_pool')
        self.assertTrue(self.mock_rados.Rados.connect.called)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(ret[1], self.mock_rados.Rados.ioctx)
        self.mock_rados.Rados.open_ioctx.assert_called_with('alt_pool')

        # error
        self.mock_rados.Rados.open_ioctx.reset_mock()
        self.mock_rados.Rados.shutdown.reset_mock()
        self.mock_rados.Rados.open_ioctx.side_effect = self.mock_rados.Error
        self.assertRaises(self.mock_rados.Error, self.driver._connect_to_rados)
        self.mock_rados.Rados.open_ioctx.assert_called_once()
        self.mock_rados.Rados.shutdown.assert_called_once()

    def test_ceph_args(self):
        self.driver.rbd_user = None
        self.driver.ceph_conf = None
        self.assertEqual([], self.driver.ceph_args())

        self.driver.rbd_user = 'foo'
        self.driver.ceph_conf = None
        self.assertEqual(['--id', 'foo'], self.driver.ceph_args())

        self.driver.rbd_user = None
        self.driver.ceph_conf = '/path/bar.conf'
        self.assertEqual(['--conf', '/path/bar.conf'],
                         self.driver.ceph_args())

        self.driver.rbd_user = 'foo'
        self.driver.ceph_conf = '/path/bar.conf'
        self.assertEqual(['--id', 'foo', '--conf', '/path/bar.conf'],
                         self.driver.ceph_args())
