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

from nova import exception
from nova.openstack.common import log as logging
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

    def test_good_locations(self):
        locations = ['rbd://fsid/pool/image/snap',
                     'rbd://%2F/%2F/%2F/%2F', ]
        map(self.driver.parse_location, locations)

    def test_bad_locations(self):
        locations = ['rbd://image',
                     'http://path/to/somewhere/else',
                     'rbd://image/extra',
                     'rbd://image/',
                     'rbd://fsid/pool/image/',
                     'rbd://fsid/pool/image/snap/',
                     'rbd://///', ]
        for loc in locations:
            self.assertRaises(exception.ImageUnacceptable,
                              self.driver.parse_location,
                              loc)
            self.assertFalse(
                self.driver.is_cloneable(loc, {'disk_format': 'raw'}))

    def test_cloneable(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            info = {'disk_format': 'raw'}
            self.assertTrue(self.driver.is_cloneable(location, info))
            self.assertTrue(mock_get_fsid.called)

    def test_uncloneable_different_fsid(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://def/pool/image/snap'
            self.assertFalse(
                self.driver.is_cloneable(location, {'disk_format': 'raw'}))
            self.assertTrue(mock_get_fsid.called)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_uncloneable_unreadable(self, mock_proxy):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'

            mock_proxy.side_effect = self.mock_rbd.Error

            args = [location, {'disk_format': 'raw'}]
            self.assertFalse(self.driver.is_cloneable(*args))
            mock_proxy.assert_called_once()
            self.assertTrue(mock_get_fsid.called)

    def test_uncloneable_bad_format(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            formats = ['qcow2', 'vmdk', 'vdi']
            for f in formats:
                self.assertFalse(
                    self.driver.is_cloneable(location, {'disk_format': f}))
            self.assertTrue(mock_get_fsid.called)

    def test_get_mon_addrs(self):
        with mock.patch.object(utils, 'execute') as mock_execute:
            mock_execute.return_value = (CEPH_MON_DUMP, '')
            hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
            ports = ['6789', '6790', '6791', '6792', '6791']
            self.assertEqual((hosts, ports), self.driver.get_mon_addrs())

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_clone(self, mock_client):
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        self.mock_rbd.RBD.clone = mock.Mock()

        self.driver.clone(self.rbd_pool, self.volume_name,
                          src_pool, src_image, src_snap)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_name)]
        kwargs = {'features': self.mock_rbd.RBD_FEATURE_LAYERING}
        self.mock_rbd.RBD.clone.assert_called_once_with(*args, **kwargs)
        self.assertEqual(client.__enter__.call_count, 2)

    def test_resize(self):
        size = 1024

        with mock.patch.object(rbd_utils, 'RBDVolumeProxy') as proxy_init:
            proxy = proxy_init.return_value
            proxy.__enter__.return_value = proxy
            self.driver.resize(self.volume_name, size)
            proxy.resize.assert_called_once_with(size)

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

    def test_exists(self):
        snapshot = 'snap'

        with mock.patch.object(rbd_utils, 'RBDVolumeProxy') as proxy_init:
            proxy = proxy_init.return_value
            self.assertTrue(self.driver.exists(self.volume_name,
                                               self.rbd_pool,
                                               snapshot))
            proxy.__enter__.assert_called_once()
            proxy.__exit__.assert_called_once()

    def test_rename(self):
        new_name = 'bar'

        with mock.patch.object(rbd_utils, 'RADOSClient') as client_init:
            client = client_init.return_value
            client.__enter__.return_value = client
            self.mock_rbd.RBD = mock.Mock(return_value=mock.Mock())
            self.driver.rename(self.volume_name, new_name)
            mock_rename = self.mock_rbd.RBD.return_value
            mock_rename.rename.assert_called_once_with(client.ioctx,
                                                       self.volume_name,
                                                       new_name)
