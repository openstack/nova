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
from keystoneclient import exceptions as keystone_exception
import mock
from oslo_utils import timeutils

import nova.conf
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.fake_instance import fake_instance_obj
from nova.tests import uuidsentinel as uuids
from nova.volume import cinder

CONF = nova.conf.CONF


class FakeVolume(object):

    def __init__(self, volume_id, size=1, attachments=None, multiattach=False):
        self.id = volume_id
        self.name = 'volume_name'
        self.description = 'volume_description'
        self.status = 'available'
        self.created_at = timeutils.utcnow()
        self.size = size
        self.availability_zone = 'nova'
        self.attachments = attachments or []
        self.volume_type = 99
        self.bootable = False
        self.snapshot_id = 'snap_id_1'
        self.metadata = {}
        self.multiattach = multiattach

    def get(self, volume_id):
        return self.volume_id


class FakeSnapshot(object):

    def __init__(self, snapshot_id, volume_id, size=1):
        self.id = snapshot_id
        self.name = 'snapshot_name'
        self.description = 'snapshot_description'
        self.status = 'available'
        self.size = size
        self.created_at = timeutils.utcnow()
        self.progress = '99%'
        self.volume_id = volume_id
        self.project_id = 'fake_project'


class CinderApiTestCase(test.NoDBTestCase):
    def setUp(self):
        super(CinderApiTestCase, self).setUp()

        self.api = cinder.API()
        self.ctx = context.get_admin_context()

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get(self, mock_cinderclient):
        volume_id = 'volume_id1'
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.get(self.ctx, volume_id)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.get.assert_called_once_with(volume_id)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_failed_notfound(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.get.side_effect = (
            cinder_exception.NotFound(404, '404'))

        self.assertRaises(exception.VolumeNotFound,
                  self.api.get, self.ctx, 'id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_failed_badrequest(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.get.side_effect = (
            cinder_exception.BadRequest(400, '400'))

        self.assertRaises(exception.InvalidInput,
                  self.api.get, self.ctx, 'id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_failed_connection_failed(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.get.side_effect = (
            cinder_exception.ConnectionError(''))

        self.assertRaises(exception.CinderConnectionFailed,
                  self.api.get, self.ctx, 'id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create(self, mock_cinderclient):
        volume = FakeVolume('id1')
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)
        mock_volumes.create.return_value = volume

        created_volume = self.api.create(self.ctx, 1, '', '')
        self.assertEqual('id1', created_volume['id'])
        self.assertEqual(1, created_volume['size'])

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.create.assert_called_once_with(1, availability_zone=None,
                                                    description='',
                                                    imageRef=None,
                                                    metadata=None, name='',
                                                    project_id=None,
                                                    snapshot_id=None,
                                                    user_id=None,
                                                    volume_type=None)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create_failed(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.create.side_effect = (
            cinder_exception.BadRequest(400, '400'))

        self.assertRaises(exception.InvalidInput,
                          self.api.create, self.ctx, 1, '', '')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create_over_quota_failed(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.create.side_effect = (
            cinder_exception.OverLimit(413))
        self.assertRaises(exception.OverQuota, self.api.create, self.ctx,
                          1, '', '')
        mock_cinderclient.return_value.volumes.create.assert_called_once_with(
            1, user_id=None, imageRef=None, availability_zone=None,
            volume_type=None, description='', snapshot_id=None, name='',
            project_id=None, metadata=None)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_all(self, mock_cinderclient):
        volume1 = FakeVolume('id1')
        volume2 = FakeVolume('id2')

        volume_list = [volume1, volume2]
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)
        mock_volumes.list.return_value = volume_list

        volumes = self.api.get_all(self.ctx)
        self.assertEqual(2, len(volumes))
        self.assertEqual(['id1', 'id2'], [vol['id'] for vol in volumes])

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.list.assert_called_once_with(detailed=True,
                                                  search_opts={})

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_all_with_search(self, mock_cinderclient):
        volume1 = FakeVolume('id1')

        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)
        mock_volumes.list.return_value = [volume1]

        volumes = self.api.get_all(self.ctx, search_opts={'id': 'id1'})
        self.assertEqual(1, len(volumes))
        self.assertEqual('id1', volumes[0]['id'])

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.list.assert_called_once_with(detailed=True,
                                                  search_opts={'id': 'id1'})

    @mock.patch.object(cinder.az, 'get_instance_availability_zone',
                       return_value='zone1')
    def test_check_availability_zone_differs(self, mock_get_instance_az):
        self.flags(cross_az_attach=False, group='cinder')
        volume = {'id': uuids.volume_id,
                  'status': 'available',
                  'attach_status': 'detached',
                  'availability_zone': 'zone2'}
        instance = fake_instance_obj(self.ctx)
        # Simulate _provision_instances in the compute API; the instance is not
        # created in the API so the instance will not have an id attribute set.
        delattr(instance, 'id')

        self.assertRaises(exception.InvalidVolume,
                          self.api.check_availability_zone,
                          self.ctx, volume, instance)
        mock_get_instance_az.assert_called_once_with(self.ctx, instance)

    def test_check_detach(self):
        volume = {'id': 'fake', 'status': 'in-use',
                  'attach_status': 'attached',
                  'attachments': {uuids.instance: {
                                    'attachment_id': uuids.attachment}}
                  }
        self.assertIsNone(self.api.check_detach(self.ctx, volume))
        instance = fake_instance_obj(self.ctx)
        instance.uuid = uuids.instance
        self.assertIsNone(self.api.check_detach(self.ctx, volume, instance))
        instance.uuid = uuids.instance2
        self.assertRaises(exception.VolumeUnattached,
                          self.api.check_detach, self.ctx, volume, instance)
        volume['attachments'] = {}
        self.assertRaises(exception.VolumeUnattached,
                          self.api.check_detach, self.ctx, volume, instance)
        volume['status'] = 'available'
        self.assertRaises(exception.InvalidVolume,
                          self.api.check_detach, self.ctx, volume)
        volume['attach_status'] = 'detached'
        self.assertRaises(exception.InvalidVolume,
                          self.api.check_detach, self.ctx, volume)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_reserve_volume(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.reserve_volume(self.ctx, 'id1')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.reserve.assert_called_once_with('id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_unreserve_volume(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.unreserve_volume(self.ctx, 'id1')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.unreserve.assert_called_once_with('id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_begin_detaching(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.begin_detaching(self.ctx, 'id1')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.begin_detaching.assert_called_once_with('id1')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_roll_detaching(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.roll_detaching(self.ctx, 'id1')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.roll_detaching.assert_called_once_with('id1')

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

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_attachment_delete(self, mock_cinderclient):
        mock_attachments = mock.MagicMock()
        mock_cinderclient.return_value = \
            mock.MagicMock(attachments=mock_attachments)

        attachment_id = uuids.attachment
        self.api.attachment_delete(self.ctx, attachment_id)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_attachments.delete.assert_called_once_with(attachment_id)

    @mock.patch('nova.volume.cinder.LOG')
    @mock.patch('nova.volume.cinder.cinderclient')
    def test_attachment_delete_failed(self, mock_cinderclient, mock_log):
        mock_cinderclient.return_value.attachments.delete.side_effect = (
                cinder_exception.NotFound(404, '404'))

        attachment_id = uuids.attachment
        ex = self.assertRaises(exception.VolumeAttachmentNotFound,
                               self.api.attachment_delete,
                               self.ctx,
                               attachment_id)

        self.assertEqual(404, ex.code)
        self.assertIn(attachment_id, ex.message)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_detach(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(version='2',
                                                        volumes=mock_volumes)

        self.api.detach(self.ctx, 'id1', instance_uuid='fake_uuid',
                        attachment_id='fakeid')

        mock_cinderclient.assert_called_with(self.ctx)
        mock_volumes.detach.assert_called_once_with('id1', 'fakeid')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_detach_no_attachment_id(self, mock_cinderclient):
        attachment = {'server_id': 'fake_uuid',
                      'attachment_id': 'fakeid'
                     }

        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(version='2',
                                                        volumes=mock_volumes)
        mock_cinderclient.return_value.volumes.get.return_value = \
            FakeVolume('id1', attachments=[attachment])

        self.api.detach(self.ctx, 'id1', instance_uuid='fake_uuid')

        mock_cinderclient.assert_called_with(self.ctx)
        mock_volumes.detach.assert_called_once_with('id1', None)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_detach_no_attachment_id_multiattach(self, mock_cinderclient):
        attachment = {'server_id': 'fake_uuid',
                      'attachment_id': 'fakeid'
                     }

        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(version='2',
                                                        volumes=mock_volumes)
        mock_cinderclient.return_value.volumes.get.return_value = \
            FakeVolume('id1', attachments=[attachment], multiattach=True)

        self.api.detach(self.ctx, 'id1', instance_uuid='fake_uuid')

        mock_cinderclient.assert_called_with(self.ctx)
        mock_volumes.detach.assert_called_once_with('id1', 'fakeid')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_initialize_connection(self, mock_cinderclient):
        connection_info = {'foo': 'bar'}
        mock_cinderclient.return_value.volumes. \
            initialize_connection.return_value = connection_info

        volume_id = 'fake_vid'
        connector = {'host': 'fakehost1'}
        actual = self.api.initialize_connection(self.ctx, volume_id, connector)

        expected = connection_info
        expected['connector'] = connector
        self.assertEqual(expected, actual)

        mock_cinderclient.return_value.volumes. \
            initialize_connection.assert_called_once_with(volume_id, connector)

    @mock.patch('nova.volume.cinder.LOG')
    @mock.patch('nova.volume.cinder.cinderclient')
    def test_initialize_connection_exception_no_code(
                                self, mock_cinderclient, mock_log):
        mock_cinderclient.return_value.volumes. \
            initialize_connection.side_effect = (
                cinder_exception.ClientException(500, "500"))
        mock_cinderclient.return_value.volumes. \
            terminate_connection.side_effect = (
                test.TestingException)

        connector = {'host': 'fakehost1'}
        self.assertRaises(cinder_exception.ClientException,
                          self.api.initialize_connection,
                          self.ctx,
                          'id1',
                          connector)
        self.assertIsNone(mock_log.error.call_args_list[1][0][1]['code'])

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_initialize_connection_rollback(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.\
            initialize_connection.side_effect = (
                cinder_exception.ClientException(500, "500"))

        connector = {'host': 'host1'}
        ex = self.assertRaises(cinder_exception.ClientException,
                               self.api.initialize_connection,
                               self.ctx,
                               'id1',
                               connector)
        self.assertEqual(500, ex.code)
        mock_cinderclient.return_value.volumes.\
            terminate_connection.assert_called_once_with('id1', connector)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_initialize_connection_no_rollback(self, mock_cinderclient):
        mock_cinderclient.return_value.volumes.\
            initialize_connection.side_effect = test.TestingException

        connector = {'host': 'host1'}
        self.assertRaises(test.TestingException,
                          self.api.initialize_connection,
                          self.ctx,
                          'id1',
                          connector)
        self.assertFalse(mock_cinderclient.return_value.volumes.
            terminate_connection.called)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_terminate_connection(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.terminate_connection(self.ctx, 'id1', 'connector')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.terminate_connection.assert_called_once_with('id1',
                                                                  'connector')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_delete(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.delete(self.ctx, 'id1')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.delete.assert_called_once_with('id1')

    def test_update(self):
        self.assertRaises(NotImplementedError,
                          self.api.update, self.ctx, '', '')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_snapshot(self, mock_cinderclient):
        snapshot_id = 'snapshot_id'
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)

        self.api.get_snapshot(self.ctx, snapshot_id)

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.get.assert_called_once_with(snapshot_id)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_snapshot_failed_notfound(self, mock_cinderclient):
        mock_cinderclient.return_value.volume_snapshots.get.side_effect = (
            cinder_exception.NotFound(404, '404'))

        self.assertRaises(exception.SnapshotNotFound,
                          self.api.get_snapshot, self.ctx, 'snapshot_id')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_snapshot_connection_failed(self, mock_cinderclient):
        mock_cinderclient.return_value.volume_snapshots.get.side_effect = (
            cinder_exception.ConnectionError(''))

        self.assertRaises(exception.CinderConnectionFailed,
                          self.api.get_snapshot, self.ctx, 'snapshot_id')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_all_snapshots(self, mock_cinderclient):
        snapshot1 = FakeSnapshot('snapshot_id1', 'id1')
        snapshot2 = FakeSnapshot('snapshot_id2', 'id2')

        snapshot_list = [snapshot1, snapshot2]
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)
        mock_volume_snapshots.list.return_value = snapshot_list

        snapshots = self.api.get_all_snapshots(self.ctx)
        self.assertEqual(2, len(snapshots))
        self.assertEqual(['snapshot_id1', 'snapshot_id2'],
                         [snap['id'] for snap in snapshots])
        self.assertEqual(['id1', 'id2'],
                         [snap['volume_id'] for snap in snapshots])

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.list.assert_called_once_with(detailed=True)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create_snapshot(self, mock_cinderclient):
        snapshot = FakeSnapshot('snapshot_id1', 'id1')
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)
        mock_volume_snapshots.create.return_value = snapshot

        created_snapshot = self.api.create_snapshot(self.ctx,
                                                    'id1',
                                                    'name',
                                                    'description')

        self.assertEqual('snapshot_id1', created_snapshot['id'])
        self.assertEqual('id1', created_snapshot['volume_id'])
        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.create.assert_called_once_with('id1', False,
                                                             'name',
                                                             'description')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_create_force(self, mock_cinderclient):
        snapshot = FakeSnapshot('snapshot_id1', 'id1')
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)
        mock_volume_snapshots.create.return_value = snapshot

        created_snapshot = self.api.create_snapshot_force(self.ctx,
                                                          'id1',
                                                          'name',
                                                          'description')

        self.assertEqual('snapshot_id1', created_snapshot['id'])
        self.assertEqual('id1', created_snapshot['volume_id'])
        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.create.assert_called_once_with('id1', True,
                                                             'name',
                                                             'description')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_delete_snapshot(self, mock_cinderclient):
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)

        self.api.delete_snapshot(self.ctx, 'snapshot_id')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.delete.assert_called_once_with('snapshot_id')

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_update_snapshot_status(self, mock_cinderclient):
        mock_volume_snapshots = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(
            volume_snapshots=mock_volume_snapshots)

        self.api.update_snapshot_status(self.ctx, 'snapshot_id', 'error')

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volume_snapshots.update_snapshot_status.assert_called_once_with(
            'snapshot_id', {'status': 'error', 'progress': '90%'})

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_get_volume_encryption_metadata(self, mock_cinderclient):
        mock_volumes = mock.MagicMock()
        mock_cinderclient.return_value = mock.MagicMock(volumes=mock_volumes)

        self.api.get_volume_encryption_metadata(self.ctx,
                                                {'encryption_key_id':
                                                 'fake_key'})

        mock_cinderclient.assert_called_once_with(self.ctx)
        mock_volumes.get_encryption_metadata.assert_called_once_with(
            {'encryption_key_id': 'fake_key'})

    def test_translate_cinder_exception_no_error(self):
        my_func = mock.Mock()
        my_func.__name__ = 'my_func'
        my_func.return_value = 'foo'

        res = cinder.translate_cinder_exception(my_func)('fizzbuzz',
                                                         'bar', 'baz')

        self.assertEqual('foo', res)
        my_func.assert_called_once_with('fizzbuzz', 'bar', 'baz')

    def test_translate_cinder_exception_cinder_connection_error(self):
        self._do_translate_cinder_exception_test(
            cinder_exception.ConnectionError,
            exception.CinderConnectionFailed)

    def test_translate_cinder_exception_keystone_connection_error(self):
        self._do_translate_cinder_exception_test(
            keystone_exception.ConnectionError,
            exception.CinderConnectionFailed)

    def test_translate_cinder_exception_cinder_bad_request(self):
        self._do_translate_cinder_exception_test(
            cinder_exception.BadRequest(400, '400'),
            exception.InvalidInput)

    def test_translate_cinder_exception_keystone_bad_request(self):
        self._do_translate_cinder_exception_test(
            keystone_exception.BadRequest,
            exception.InvalidInput)

    def test_translate_cinder_exception_cinder_forbidden(self):
        self._do_translate_cinder_exception_test(
            cinder_exception.Forbidden(403, '403'),
            exception.Forbidden)

    def test_translate_cinder_exception_keystone_forbidden(self):
        self._do_translate_cinder_exception_test(
            keystone_exception.Forbidden,
            exception.Forbidden)

    def test_translate_mixed_exception_over_limit(self):
        self._do_translate_mixed_exception_test(
            cinder_exception.OverLimit(''),
            exception.OverQuota)

    def test_translate_mixed_exception_volume_not_found(self):
        self._do_translate_mixed_exception_test(
            cinder_exception.NotFound(''),
            exception.VolumeNotFound)

    def test_translate_mixed_exception_keystone_not_found(self):
        self._do_translate_mixed_exception_test(
            keystone_exception.NotFound,
            exception.VolumeNotFound)

    def _do_translate_cinder_exception_test(self, raised_exc, expected_exc):
        self._do_translate_exception_test(raised_exc, expected_exc,
                                          cinder.translate_cinder_exception)

    def _do_translate_mixed_exception_test(self, raised_exc, expected_exc):
        self._do_translate_exception_test(raised_exc, expected_exc,
                                          cinder.translate_mixed_exceptions)

    def _do_translate_exception_test(self, raised_exc, expected_exc, wrapper):
        my_func = mock.Mock()
        my_func.__name__ = 'my_func'
        my_func.side_effect = raised_exc

        self.assertRaises(expected_exc, wrapper(my_func), 'foo', 'bar', 'baz')
