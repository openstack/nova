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


from eventlet import tpool
import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import task_states
from nova import exception
from nova import objects
from nova import test
from nova.virt.libvirt.storage import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils


CEPH_MON_DUMP = r"""dumped monmap epoch 1
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


# max_avail stats are tweaked for testing
CEPH_DF = """
{
    "stats": {
        "total_bytes": 25757220864,
        "total_used_bytes": 274190336,
        "total_avail_bytes": 25483030528
    },
    "pools": [
        {
            "name": "images",
            "id": 1,
            "stats": {
                "kb_used": 12419,
                "bytes_used": 12716067,
                "percent_used": 0.05,
                "max_avail": 24195168123,
                "objects": 6
            }
        },
        {
            "name": "rbd",
            "id": 2,
            "stats": {
                "kb_used": 0,
                "bytes_used": 0,
                "percent_used": 0.00,
                "max_avail": 24195168456,
                "objects": 0
            }
        },
        {
            "name": "volumes",
            "id": 3,
            "stats": {
                "kb_used": 0,
                "bytes_used": 0,
                "percent_used": 0.00,
                "max_avail": 24195168789,
                "objects": 0
            }
        }
    ]
}
"""


class FakeException(Exception):
    pass


class RbdTestCase(test.NoDBTestCase):

    def setUp(self):
        super(RbdTestCase, self).setUp()

        self.rbd_pool = 'rbd'
        self.rbd_connect_timeout = 5
        self.flags(images_rbd_pool=self.rbd_pool, group='libvirt')
        self.flags(rbd_connect_timeout=self.rbd_connect_timeout,
                    group='libvirt')

        rados_patcher = mock.patch.object(rbd_utils, 'rados')
        self.mock_rados = rados_patcher.start()
        self.addCleanup(rados_patcher.stop)
        self.mock_rados.Rados = mock.Mock
        self.mock_rados.Rados.ioctx = mock.Mock()
        self.mock_rados.Rados.connect = mock.Mock()
        self.mock_rados.Rados.shutdown = mock.Mock()
        self.mock_rados.Rados.open_ioctx = mock.Mock()
        self.mock_rados.Rados.open_ioctx.return_value = \
            self.mock_rados.Rados.ioctx
        self.mock_rados.Error = Exception

        rbd_patcher = mock.patch.object(rbd_utils, 'rbd')
        self.mock_rbd = rbd_patcher.start()
        self.addCleanup(rbd_patcher.stop)
        self.mock_rbd.RBD = mock.Mock()
        self.mock_rbd.Image = mock.Mock()
        self.mock_rbd.Image.close = mock.Mock()
        self.mock_rbd.Error = Exception
        self.mock_rbd.ImageBusy = FakeException
        self.mock_rbd.ImageHasSnapshots = FakeException

        self.driver = rbd_utils.RBDDriver()

        self.volume_name = u'volume-00000001'
        self.snap_name = u'test-snap'

    def test_rbdproxy_wraps_rbd(self):
        proxy = rbd_utils.RbdProxy()
        self.assertIsInstance(proxy._rbd, tpool.Proxy)

    def test_rbdproxy_attribute_access_proxying(self):
        client = mock.MagicMock(ioctx='fake_ioctx')
        rbd_utils.RbdProxy().list(client.ioctx)
        self.mock_rbd.RBD.return_value.list.assert_called_once_with(
            client.ioctx)

    def test_good_locations(self):
        locations = ['rbd://fsid/pool/image/snap',
                     'rbd://%2F/%2F/%2F/%2F', ]
        map(self.driver.parse_url, locations)

    def test_bad_locations(self):
        locations = ['rbd://image',
                     'http://path/to/somewhere/else',
                     'rbd://image/extra',
                     'rbd://image/',
                     'rbd://fsid/pool/image/',
                     'rbd://fsid/pool/image/snap/',
                     'rbd://///', ]
        image_meta = {'disk_format': 'raw'}

        for loc in locations:
            self.assertRaises(exception.ImageUnacceptable,
                              self.driver.parse_url, loc)
            self.assertFalse(self.driver.is_cloneable({'url': loc},
                                                      image_meta))

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_rbddriver(self, mock_client):
        client = mock_client.return_value
        client.__enter__.return_value = client
        client.cluster.get_fsid.side_effect = lambda: b'abc'
        self.assertEqual('abc', self.driver.get_fsid())

    @mock.patch.object(rbd_utils.RBDDriver, 'get_fsid')
    def test_cloneable(self, mock_get_fsid):
        mock_get_fsid.return_value = 'abc'
        location = {'url': 'rbd://abc/pool/image/snap'}
        image_meta = {'disk_format': 'raw'}
        self.assertTrue(self.driver.is_cloneable(location, image_meta))
        self.assertTrue(mock_get_fsid.called)

    @mock.patch.object(rbd_utils.RBDDriver, 'get_fsid')
    def test_uncloneable_different_fsid(self, mock_get_fsid):
        mock_get_fsid.return_value = 'abc'
        location = {'url': 'rbd://def/pool/image/snap'}
        image_meta = {'disk_format': 'raw'}
        self.assertFalse(
            self.driver.is_cloneable(location, image_meta))
        self.assertTrue(mock_get_fsid.called)

    @mock.patch.object(rbd_utils.RBDDriver, 'get_fsid')
    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_uncloneable_unreadable(self, mock_proxy,
                                    mock_get_fsid):
        mock_get_fsid.return_value = 'abc'
        location = {'url': 'rbd://abc/pool/image/snap'}

        mock_proxy.side_effect = self.mock_rbd.Error
        image_meta = {'disk_format': 'raw'}

        self.assertFalse(
            self.driver.is_cloneable(location, image_meta))
        mock_proxy.assert_called_once_with(self.driver, 'image', pool='pool',
                                           snapshot='snap', read_only=True)
        self.assertTrue(mock_get_fsid.called)

    @mock.patch.object(rbd_utils.RBDDriver, 'get_fsid')
    def test_uncloneable_bad_format(self, mock_get_fsid):
        mock_get_fsid.return_value = 'abc'
        location = {'url': 'rbd://abc/pool/image/snap'}
        formats = ['qcow2', 'vmdk', 'vdi']
        for f in formats:
            image_meta = {'disk_format': f}
            self.assertFalse(
                self.driver.is_cloneable(location, image_meta))
        self.assertTrue(mock_get_fsid.called)

    @mock.patch.object(rbd_utils.RBDDriver, 'get_fsid')
    def test_uncloneable_missing_format(self, mock_get_fsid):
        mock_get_fsid.return_value = 'abc'
        location = {'url': 'rbd://abc/pool/image/snap'}
        image_meta = {}
        self.assertFalse(
            self.driver.is_cloneable(location, image_meta))
        self.assertTrue(mock_get_fsid.called)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_get_mon_addrs(self, mock_execute):
        mock_execute.return_value = (CEPH_MON_DUMP, '')
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.assertEqual((hosts, ports), self.driver.get_mon_addrs())

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_get_mon_addrs_with_brackets(self, mock_execute):
        mock_execute.return_value = (CEPH_MON_DUMP, '')
        hosts = ['[::1]', '[::1]', '[::1]', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']
        self.assertEqual((hosts, ports),
                         self.driver.get_mon_addrs(strip_brackets=False))

    @mock.patch.object(rbd_utils.RBDDriver, '_connect_to_rados')
    def test_rbd_conf_features(self, mock_connect):
        self.mock_rbd.RBD_FEATURE_LAYERING = 1
        mock_cluster = mock.Mock()
        mock_cluster.conf_get = mock.Mock()
        mock_cluster.conf_get.return_value = None
        mock_connect.return_value = (mock_cluster, None)
        client = rbd_utils.RADOSClient(self.driver)
        self.assertEqual(1, client.features)

        mock_cluster.conf_get.return_value = '2'
        self.assertEqual(2, client.features)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_clone(self, mock_client):
        pool = u'images'
        image = u'image-name'
        snap = u'snapshot-name'
        location = {'url': u'rbd://fsid/%s/%s/%s' % (pool, image, snap)}

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        rbd = self.mock_rbd.RBD.return_value

        self.driver.clone(location, self.volume_name)

        args = [client_stack[0].ioctx, image, snap,
                client_stack[1].ioctx, str(self.volume_name)]
        kwargs = {'features': client.features}
        rbd.clone.assert_called_once_with(*args, **kwargs)
        self.assertEqual(2, client.__enter__.call_count)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_clone_eperm(self, mock_client):
        pool = u'images'
        image = u'image-name'
        snap = u'snapshot-name'
        location = {'url': u'rbd://fsid/%s/%s/%s' % (pool, image, snap)}

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        setattr(self.mock_rbd, 'PermissionError', test.TestingException)
        rbd = self.mock_rbd.RBD.return_value
        rbd.clone.side_effect = test.TestingException
        self.assertRaises(exception.Forbidden,
                          self.driver.clone, location, self.volume_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_resize(self, mock_proxy):
        size = 1024
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.driver.resize(self.volume_name, size)
        proxy.resize.assert_called_once_with(size)

    @mock.patch.object(rbd_utils.RBDDriver, '_disconnect_from_rados')
    @mock.patch.object(rbd_utils.RBDDriver, '_connect_to_rados')
    def test_rbd_volume_proxy_init(self, mock_connect_from_rados,
                                   mock_disconnect_from_rados):
        mock_connect_from_rados.return_value = (None, None)
        mock_disconnect_from_rados.return_value = (None, None)

        with rbd_utils.RBDVolumeProxy(self.driver, self.volume_name):
            mock_connect_from_rados.assert_called_once_with(None)
            self.assertFalse(mock_disconnect_from_rados.called)

        mock_disconnect_from_rados.assert_called_once_with(None, None)

    def test_connect_to_rados_default(self):
        ret = self.driver._connect_to_rados()
        self.mock_rados.Rados.connect.assert_called_once_with(
                timeout=self.rbd_connect_timeout)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(self.mock_rados.Rados.ioctx, ret[1])
        self.mock_rados.Rados.open_ioctx.assert_called_with(self.rbd_pool)

    def test_connect_to_rados_different_pool(self):
        ret = self.driver._connect_to_rados('alt_pool')
        self.mock_rados.Rados.connect.assert_called_once_with(
                timeout=self.rbd_connect_timeout)
        self.assertTrue(self.mock_rados.Rados.open_ioctx.called)
        self.assertIsInstance(ret[0], self.mock_rados.Rados)
        self.assertEqual(self.mock_rados.Rados.ioctx, ret[1])
        self.mock_rados.Rados.open_ioctx.assert_called_with('alt_pool')

    def test_connect_to_rados_error(self):
        self.mock_rados.Rados.open_ioctx.side_effect = self.mock_rados.Error
        self.assertRaises(self.mock_rados.Error,
                          self.driver._connect_to_rados)
        self.mock_rados.Rados.open_ioctx.assert_called_once_with(
            self.rbd_pool)
        self.mock_rados.Rados.shutdown.assert_called_once_with()

    def test_connect_to_rados_unicode_arg(self):
        self.driver._connect_to_rados(u'unicode_pool')
        self.mock_rados.Rados.open_ioctx.assert_called_with(
            test.MatchType(str))

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

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_exists(self, mock_proxy):
        snapshot = 'snap'
        proxy = mock_proxy.return_value
        self.assertTrue(self.driver.exists(self.volume_name,
                                           self.rbd_pool,
                                           snapshot))
        proxy.__enter__.assert_called_once_with()
        proxy.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_cleanup_volumes(self, mock_client):
        instance = objects.Instance(id=1, uuid=uuids.instance,
                                    task_state=None)
        # this is duplicated from nova/virt/libvirt/driver.py
        filter_fn = lambda disk: disk.startswith(instance.uuid)

        rbd = self.mock_rbd.RBD.return_value
        rbd.list.return_value = ['%s_test' % uuids.instance, '111_test']

        client = mock_client.return_value
        self.driver.cleanup_volumes(filter_fn)

        rbd.remove.assert_called_once_with(
            client.__enter__.return_value.ioctx,
            '%s_test' % uuids.instance)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def _test_cleanup_exception(self, exception_name, mock_client):
        instance = objects.Instance(id=1, uuid=uuids.instance,
                                    task_state=None)
        # this is duplicated from nova/virt/libvirt/driver.py
        filter_fn = lambda disk: disk.startswith(instance.uuid)

        setattr(self.mock_rbd, exception_name, test.TestingException)
        rbd = self.mock_rbd.RBD.return_value
        rbd.remove.side_effect = test.TestingException
        rbd.list.return_value = ['%s_test' % uuids.instance, '111_test']
        self.mock_rbd.Image.return_value.list_snaps.return_value = [{}]

        client = mock_client.return_value
        with mock.patch('eventlet.greenthread.sleep'):
            self.driver.cleanup_volumes(filter_fn)
        rbd.remove.assert_any_call(client.__enter__.return_value.ioctx,
                                   '%s_test' % uuids.instance)
        # NOTE(danms): 10 retries + 1 final attempt to propagate = 11
        self.assertEqual(11, len(rbd.remove.call_args_list))

    def test_cleanup_volumes_fail_not_found(self):
        self._test_cleanup_exception('ImageBusy')

    def test_cleanup_volumes_fail_snapshots(self):
        self._test_cleanup_exception('ImageHasSnapshots')

    def test_cleanup_volumes_fail_other(self):
        self.assertRaises(test.TestingException,
                          self._test_cleanup_exception, 'DoesNotExist')

    @mock.patch.object(rbd_utils, 'RADOSClient')
    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_cleanup_volumes_pending_resize(self, mock_proxy, mock_client):
        self.mock_rbd.ImageBusy = FakeException
        self.mock_rbd.ImageHasSnapshots = FakeException
        instance = objects.Instance(id=1, uuid=uuids.instance,
                                    task_state=None)
        # this is duplicated from nova/virt/libvirt/driver.py
        filter_fn = lambda disk: disk.startswith(instance.uuid)

        setattr(self.mock_rbd, 'ImageHasSnapshots', test.TestingException)
        rbd = self.mock_rbd.RBD.return_value
        rbd.remove.side_effect = [test.TestingException, None]
        rbd.list.return_value = ['%s_test' % uuids.instance, '111_test']
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.list_snaps.return_value = [
            {'name': libvirt_utils.RESIZE_SNAPSHOT_NAME}]
        client = mock_client.return_value
        self.driver.cleanup_volumes(filter_fn)

        remove_call = mock.call(client.__enter__.return_value.ioctx,
                                '%s_test' % uuids.instance)
        rbd.remove.assert_has_calls([remove_call, remove_call])
        proxy.remove_snap.assert_called_once_with(
                libvirt_utils.RESIZE_SNAPSHOT_NAME)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_cleanup_volumes_reverting_resize(self, mock_client):
        instance = objects.Instance(id=1, uuid=uuids.instance,
                                    task_state=task_states.RESIZE_REVERTING)
        # this is duplicated from nova/virt/libvirt/driver.py
        filter_fn = lambda disk: (disk.startswith(instance.uuid) and
                                  disk.endswith('disk.local'))

        rbd = self.mock_rbd.RBD.return_value
        rbd.list.return_value = ['%s_test' % uuids.instance, '111_test',
                                 '%s_test_disk.local' % uuids.instance]

        client = mock_client.return_value
        self.driver.cleanup_volumes(filter_fn)
        rbd.remove.assert_called_once_with(
            client.__enter__.return_value.ioctx,
            '%s_test_disk.local' % uuids.instance)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_destroy_volume(self, mock_client):
        rbd = self.mock_rbd.RBD.return_value
        vol = '12345_test'
        client = mock_client.return_value
        self.driver.destroy_volume(vol)
        rbd.remove.assert_called_once_with(
            client.__enter__.return_value.ioctx, vol)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RADOSClient')
    def test_remove_image(self, mock_client):
        name = '12345_disk.config.rescue'

        rbd = self.mock_rbd.RBD.return_value

        client = mock_client.return_value
        self.driver.remove_image(name)
        rbd.remove.assert_called_once_with(
            client.__enter__.return_value.ioctx, name)
        # Make sure that we entered and exited the RADOSClient
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_create_snap(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.driver.create_snap(self.volume_name, self.snap_name)
        proxy.create_snap.assert_called_once_with(self.snap_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_create_protected_snap(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.is_protected_snap.return_value = False
        self.driver.create_snap(self.volume_name, self.snap_name, protect=True)
        proxy.create_snap.assert_called_once_with(self.snap_name)
        proxy.is_protected_snap.assert_called_once_with(self.snap_name)
        proxy.protect_snap.assert_called_once_with(self.snap_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_remove_snap(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.list_snaps.return_value = [{'name': self.snap_name}]
        proxy.is_protected_snap.return_value = False
        self.driver.remove_snap(self.volume_name, self.snap_name)
        proxy.remove_snap.assert_called_once_with(self.snap_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_remove_snap_force(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.is_protected_snap.return_value = True
        proxy.list_snaps.return_value = [{'name': self.snap_name}]
        self.driver.remove_snap(self.volume_name, self.snap_name, force=True)
        proxy.is_protected_snap.assert_called_once_with(self.snap_name)
        proxy.unprotect_snap.assert_called_once_with(self.snap_name)
        proxy.remove_snap.assert_called_once_with(self.snap_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_remove_snap_does_nothing_when_no_snapshot(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.list_snaps.return_value = [{'name': 'some-other-snaphot'}]
        self.driver.remove_snap(self.volume_name, self.snap_name)
        self.assertFalse(proxy.remove_snap.called)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_remove_snap_does_nothing_when_protected(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.is_protected_snap.return_value = True
        proxy.list_snaps.return_value = [{'name': self.snap_name}]
        self.driver.remove_snap(self.volume_name, self.snap_name)
        self.assertFalse(proxy.remove_snap.called)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_remove_snap_protected_ignore_errors(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.is_protected_snap.return_value = True
        proxy.list_snaps.return_value = [{'name': self.snap_name}]
        self.driver.remove_snap(self.volume_name, self.snap_name,
                                ignore_errors=True)
        proxy.remove_snap.assert_called_once_with(self.snap_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_parent_info(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.driver.parent_info(self.volume_name)
        proxy.parent_info.assert_called_once_with()

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_parent_info_throws_exception_on_error(self, mock_proxy):
        setattr(self.mock_rbd, 'ImageNotFound', test.TestingException)
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.parent_info.side_effect = test.TestingException
        self.assertRaises(exception.ImageUnacceptable,
                          self.driver.parent_info, self.volume_name)

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_flatten(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.driver.flatten(self.volume_name)
        proxy.flatten.assert_called_once_with()

    @mock.patch.object(rbd_utils, 'RBDVolumeProxy')
    def test_rollback_to_snap(self, mock_proxy):
        proxy = mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.rollback_to_snap,
                          self.volume_name, self.snap_name)

        proxy.list_snaps.return_value = [{'name': self.snap_name}, ]
        self.driver.rollback_to_snap(self.volume_name, self.snap_name)
        proxy.rollback_to_snap.assert_called_once_with(self.snap_name)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_get_pool_info(self, mock_execute):
        mock_execute.return_value = (CEPH_DF, '')
        ceph_df_json = jsonutils.loads(CEPH_DF)
        expected = {'total': ceph_df_json['stats']['total_bytes'],
                    'free': ceph_df_json['pools'][1]['stats']['max_avail'],
                    'used': ceph_df_json['pools'][1]['stats']['bytes_used']}
        self.assertDictEqual(expected, self.driver.get_pool_info())

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_get_pool_info_not_found(self, mock_execute):
        # Make the pool something other than self.rbd_pool so it won't be found
        ceph_df_not_found = CEPH_DF.replace('rbd', 'vms')
        mock_execute.return_value = (ceph_df_not_found, '')
        self.assertRaises(exception.NotFound, self.driver.get_pool_info)
