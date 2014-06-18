# Copyright 2013 Mirantis, Inc.
# Copyright 2013 OpenStack Foundation
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

from cinderclient import exceptions as cinder_exception
import mock

from nova import context
from nova import exception
from nova import test
from nova.volume import cinder


class FakeCinderClient(object):
    class Volumes(object):
        def get(self, volume_id):
            return {'id': volume_id}

        def list(self, detailed):
            return [{'id': 'id1'}, {'id': 'id2'}]

        def create(self, *args, **kwargs):
            return {'id': 'created_id'}

        def __getattr__(self, item):
            return None

    def __init__(self):
        self.volumes = self.Volumes()
        self.volume_snapshots = self.volumes


class FakeVolume(object):
    def __init__(self, dict=dict()):
        self.id = dict.get('id') or '1234'
        self.status = dict.get('status') or 'available'
        self.size = dict.get('size') or 1
        self.availability_zone = dict.get('availability_zone') or 'cinder'
        self.created_at = dict.get('created_at')
        self.attach_time = dict.get('attach_time')
        self.mountpoint = dict.get('mountpoint')
        self.display_name = dict.get('display_name') or 'volume-' + self.id
        self.display_description = dict.get('display_description') or 'fake'
        self.volume_type_id = dict.get('volume_type_id')
        self.snapshot_id = dict.get('snapshot_id')
        self.metadata = dict.get('volume_metadata') or {}


class CinderApiTestCase(test.NoDBTestCase):
    def setUp(self):
        super(CinderApiTestCase, self).setUp()

        self.api = cinder.API()
        self.cinderclient = FakeCinderClient()
        self.ctx = context.get_admin_context()
        self.mox.StubOutWithMock(cinder, 'cinderclient')
        self.mox.StubOutWithMock(cinder, '_untranslate_volume_summary_view')
        self.mox.StubOutWithMock(cinder, '_untranslate_snapshot_summary_view')
        self.mox.StubOutWithMock(cinder, 'get_cinder_client_version')

    def test_get(self):
        volume_id = 'volume_id1'
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_volume_summary_view(self.ctx, {'id': 'volume_id1'})
        self.mox.ReplayAll()

        self.api.get(self.ctx, volume_id)

    def test_get_failed(self):
        volume_id = 'volume_id'
        cinder.cinderclient(self.ctx).AndRaise(cinder_exception.NotFound(''))
        cinder.cinderclient(self.ctx).AndRaise(cinder_exception.BadRequest(''))
        cinder.cinderclient(self.ctx).AndRaise(
                                        cinder_exception.ConnectionError(''))
        self.mox.ReplayAll()

        self.assertRaises(exception.VolumeNotFound,
                          self.api.get, self.ctx, volume_id)
        self.assertRaises(exception.InvalidInput,
                          self.api.get, self.ctx, volume_id)
        self.assertRaises(exception.CinderConnectionFailed,
                          self.api.get, self.ctx, volume_id)

    def test_create(self):
        cinder.get_cinder_client_version(self.ctx).AndReturn('2')
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_volume_summary_view(self.ctx, {'id': 'created_id'})
        self.mox.ReplayAll()

        self.api.create(self.ctx, 1, '', '')

    def test_create_failed(self):
        cinder.get_cinder_client_version(self.ctx).AndReturn('2')
        cinder.cinderclient(self.ctx).AndRaise(cinder_exception.BadRequest(''))
        self.mox.ReplayAll()

        self.assertRaises(exception.InvalidInput,
                          self.api.create, self.ctx, 1, '', '')

    @mock.patch('nova.volume.cinder.get_cinder_client_version')
    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create_over_quota_failed(self, mock_cinderclient,
                                      mock_get_version):
        mock_get_version.return_value = '2'
        mock_cinderclient.return_value.volumes.create.side_effect = (
            cinder_exception.OverLimit(413))
        self.assertRaises(exception.OverQuota, self.api.create, self.ctx,
                          1, '', '')
        mock_cinderclient.return_value.volumes.create.assert_called_once_with(
            1, user_id=None, imageRef=None, availability_zone=None,
            volume_type=None, description='', snapshot_id=None, name='',
            project_id=None, metadata=None)

    def test_get_all(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_volume_summary_view(self.ctx,
                                                {'id': 'id1'}).AndReturn('id1')
        cinder._untranslate_volume_summary_view(self.ctx,
                                                {'id': 'id2'}).AndReturn('id2')
        self.mox.ReplayAll()

        self.assertEqual(['id1', 'id2'], self.api.get_all(self.ctx))

    def test_check_attach_volume_status_error(self):
        volume = {'status': 'error'}
        self.assertRaises(exception.InvalidVolume,
                          self.api.check_attach, self.ctx, volume)

    def test_check_attach_volume_already_attached(self):
        volume = {'status': 'available'}
        volume['attach_status'] = "attached"
        self.assertRaises(exception.InvalidVolume,
                          self.api.check_attach, self.ctx, volume)

    def test_check_attach_availability_zone_differs(self):
        volume = {'status': 'available'}
        volume['attach_status'] = "detached"
        instance = {'availability_zone': 'zone1', 'host': 'fakehost'}

        with mock.patch.object(cinder.az, 'get_instance_availability_zone',
                               side_effect=lambda context,
                               instance: 'zone1') as mock_get_instance_az:

            cinder.CONF.set_override('cross_az_attach', False, group='cinder')
            volume['availability_zone'] = 'zone1'
            self.assertIsNone(self.api.check_attach(self.ctx,
                                                    volume, instance))
            mock_get_instance_az.assert_called_once_with(self.ctx, instance)
            mock_get_instance_az.reset_mock()
            volume['availability_zone'] = 'zone2'
            self.assertRaises(exception.InvalidVolume,
                            self.api.check_attach, self.ctx, volume, instance)
            mock_get_instance_az.assert_called_once_with(self.ctx, instance)
            mock_get_instance_az.reset_mock()
            del instance['host']
            volume['availability_zone'] = 'zone1'
            self.assertIsNone(self.api.check_attach(
                self.ctx, volume, instance))
            self.assertFalse(mock_get_instance_az.called)
            volume['availability_zone'] = 'zone2'
            self.assertRaises(exception.InvalidVolume,
                            self.api.check_attach, self.ctx, volume, instance)
            self.assertFalse(mock_get_instance_az.called)
            cinder.CONF.reset()

    def test_check_attach(self):
        volume = {'status': 'available'}
        volume['attach_status'] = "detached"
        volume['availability_zone'] = 'zone1'
        instance = {'availability_zone': 'zone1', 'host': 'fakehost'}
        cinder.CONF.set_override('cross_az_attach', False, group='cinder')

        with mock.patch.object(cinder.az, 'get_instance_availability_zone',
                               side_effect=lambda context, instance: 'zone1'):
            self.assertIsNone(self.api.check_attach(
                self.ctx, volume, instance))

        cinder.CONF.reset()

    def test_check_detach(self):
        volume = {'status': 'available'}
        self.assertRaises(exception.InvalidVolume,
                          self.api.check_detach, self.ctx, volume)
        volume['status'] = 'non-available'
        self.assertIsNone(self.api.check_detach(self.ctx, volume))

    def test_reserve_volume(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'reserve')
        self.cinderclient.volumes.reserve('id1')
        self.mox.ReplayAll()

        self.api.reserve_volume(self.ctx, 'id1')

    def test_unreserve_volume(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'unreserve')
        self.cinderclient.volumes.unreserve('id1')
        self.mox.ReplayAll()

        self.api.unreserve_volume(self.ctx, 'id1')

    def test_begin_detaching(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'begin_detaching')
        self.cinderclient.volumes.begin_detaching('id1')
        self.mox.ReplayAll()

        self.api.begin_detaching(self.ctx, 'id1')

    def test_roll_detaching(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'roll_detaching')
        self.cinderclient.volumes.roll_detaching('id1')
        self.mox.ReplayAll()

        self.api.roll_detaching(self.ctx, 'id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_attach(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.attach(self.ctx, 'id1', 'uuid', 'point')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.attach.assert_called_once_with('id1', 'uuid', 'point',
                                                    mode='rw')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_attach_with_mode(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.attach(self.ctx, 'id1', 'uuid', 'point', mode='ro')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.attach.assert_called_once_with('id1', 'uuid', 'point',
                                                    mode='ro')

    def test_detach(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'detach')
        self.cinderclient.volumes.detach('id1')
        self.mox.ReplayAll()

        self.api.detach(self.ctx, 'id1')

    def test_initialize_connection(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'initialize_connection')
        self.cinderclient.volumes.initialize_connection('id1', 'connector')
        self.mox.ReplayAll()

        self.api.initialize_connection(self.ctx, 'id1', 'connector')

    def test_terminate_connection(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'terminate_connection')
        self.cinderclient.volumes.terminate_connection('id1', 'connector')
        self.mox.ReplayAll()

        self.api.terminate_connection(self.ctx, 'id1', 'connector')

    def test_delete(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'delete')
        self.cinderclient.volumes.delete('id1')
        self.mox.ReplayAll()

        self.api.delete(self.ctx, 'id1')

    def test_update(self):
        self.assertRaises(NotImplementedError,
                          self.api.update, self.ctx, '', '')

    def test_get_snapshot(self):
        snapshot_id = 'snapshot_id'
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_snapshot_summary_view(self.ctx,
                                                  {'id': snapshot_id})
        self.mox.ReplayAll()

        self.api.get_snapshot(self.ctx, snapshot_id)

    def test_get_snapshot_failed(self):
        snapshot_id = 'snapshot_id'
        cinder.cinderclient(self.ctx).AndRaise(cinder_exception.NotFound(''))
        cinder.cinderclient(self.ctx).AndRaise(
                                        cinder_exception.ConnectionError(''))
        self.mox.ReplayAll()

        self.assertRaises(exception.SnapshotNotFound,
                          self.api.get_snapshot, self.ctx, snapshot_id)
        self.assertRaises(exception.CinderConnectionFailed,
                          self.api.get_snapshot, self.ctx, snapshot_id)

    def test_get_all_snapshots(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_snapshot_summary_view(self.ctx,
                                                {'id': 'id1'}).AndReturn('id1')
        cinder._untranslate_snapshot_summary_view(self.ctx,
                                                {'id': 'id2'}).AndReturn('id2')
        self.mox.ReplayAll()

        self.assertEqual(['id1', 'id2'], self.api.get_all_snapshots(self.ctx))

    def test_create_snapshot(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_snapshot_summary_view(self.ctx,
                                                  {'id': 'created_id'})
        self.mox.ReplayAll()

        self.api.create_snapshot(self.ctx, {'id': 'id1'}, '', '')

    def test_create_force(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        cinder._untranslate_snapshot_summary_view(self.ctx,
                                                  {'id': 'created_id'})
        self.mox.ReplayAll()

        self.api.create_snapshot_force(self.ctx, {'id': 'id1'}, '', '')

    def test_delete_snapshot(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volume_snapshots,
                                 'delete')
        self.cinderclient.volume_snapshots.delete('id1')
        self.mox.ReplayAll()

        self.api.delete_snapshot(self.ctx, 'id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_volume_metadata(self, mock_cinderclient):
        volume_id = 'id1'
        metadata = {'key1': 'value1', 'key2': 'value2'}
        volume = FakeVolume({'id': volume_id, 'volume_metadata': metadata})

        mock_volumes = mock.MagicMock()
        mock_volumes.get.return_value = volume
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        results = self.api.get_volume_metadata(self.ctx, volume_id)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.get.assert_called_once_with(volume_id)
        self.assertEqual(results, metadata)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_volume_metadata_value(self, mock_cinderclient):
        volume_id = 'id1'
        metadata = {'key1': 'value1'}
        volume = FakeVolume({'id': volume_id, 'volume_metadata': metadata})

        mock_volumes = mock.MagicMock()
        mock_volumes.get.return_value = volume
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        results = self.api.get_volume_metadata_value(self.ctx, volume_id,
                                                     'key1')
        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.get.assert_called_once_with(volume_id)
        self.assertEqual(results, 'value1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_delete_volume_metadata(self, mock_cinderclient):
        volume_id = 'id1'
        keys = ['key1', 'key2', 'key3']

        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.delete_volume_metadata(self.ctx, volume_id, keys)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.delete_metadata.assert_called_once_with(volume_id, keys)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_update_volume_metadata(self, mock_cinderclient):
        volume_id = 'id1'
        metadata = {'key1': 'value1'}

        mock_volumes = mock.MagicMock()
        mock_volumes.set_metadata.return_value = metadata
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        updated_meta = self.api.update_volume_metadata(self.ctx, volume_id,
                                                       metadata)

        mock_cinderclient.assert_called_once_with(self.ctx)
        self.assertFalse(mock_volumes.update_all_metadata.called)
        mock_volumes.set_metadata.assert_called_once_with(volume_id, metadata)
        self.assertEqual(metadata, updated_meta)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_update_volume_metadata_delete(self, mock_cinderclient):
        volume_id = 'id1'
        metadata = {'key1': 'value1', 'key2': 'value2'}

        mock_volumes = mock.MagicMock()
        mock_volumes.update_all_metadata.return_value = metadata
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        updated_meta = self.api.update_volume_metadata(self.ctx, volume_id,
                                                       metadata, delete=True)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.update_all_metadata.assert_called_once_with(volume_id,
                                                                 metadata)
        self.assertFalse(mock_volumes.set_metadata.called)
        self.assertEqual(metadata, updated_meta)

    def test_update_snapshot_status(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volume_snapshots,
                                 'update_snapshot_status')
        self.cinderclient.volume_snapshots.update_snapshot_status(
            'id1', {'status': 'error', 'progress': '90%'})
        self.mox.ReplayAll()
        self.api.update_snapshot_status(self.ctx, 'id1', 'error')

    def test_get_volume_encryption_metadata(self):
        cinder.cinderclient(self.ctx).AndReturn(self.cinderclient)
        self.mox.StubOutWithMock(self.cinderclient.volumes,
                                 'get_encryption_metadata')
        self.cinderclient.volumes.\
            get_encryption_metadata({'encryption_key_id': 'fake_key'})
        self.mox.ReplayAll()

        self.api.get_volume_encryption_metadata(self.ctx,
                                                {'encryption_key_id':
                                                 'fake_key'})
