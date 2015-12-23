# Copyright 2013 Josh Durgin
# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
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

import datetime

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
from six.moves import urllib
import webob
from webob import exc

from nova.api.openstack.compute import assisted_volume_snapshots \
        as assisted_snaps_v21
from nova.api.openstack.compute.legacy_v2.contrib import \
        assisted_volume_snapshots as assisted_snaps_v2
from nova.api.openstack.compute.legacy_v2.contrib import volumes
from nova.api.openstack.compute import volumes as volumes_v21
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.volume import cinder

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUID_A = '00000000-aaaa-aaaa-aaaa-000000000000'
FAKE_UUID_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
FAKE_UUID_C = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
FAKE_UUID_D = 'dddddddd-dddd-dddd-dddd-dddddddddddd'

IMAGE_UUID = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'


def fake_get_instance(self, context, instance_id, want_objects=False,
                      expected_attrs=None):
    return fake_instance.fake_instance_obj(context, **{'uuid': instance_id})


def fake_get_volume(self, context, id):
    return {'id': 'woot'}


def fake_attach_volume(self, context, instance, volume_id, device):
    pass


def fake_detach_volume(self, context, instance, volume):
    pass


def fake_swap_volume(self, context, instance,
                     old_volume_id, new_volume_id):
    pass


def fake_create_snapshot(self, context, volume, name, description):
    return {'id': 123,
            'volume_id': 'fakeVolId',
            'status': 'available',
            'volume_size': 123,
            'created_at': '2013-01-01 00:00:01',
            'display_name': 'myVolumeName',
            'display_description': 'myVolumeDescription'}


def fake_delete_snapshot(self, context, snapshot_id):
    pass


def fake_compute_volume_snapshot_delete(self, context, volume_id, snapshot_id,
                                        delete_info):
    pass


def fake_compute_volume_snapshot_create(self, context, volume_id,
                                        create_info):
    pass


def fake_bdms_get_all_by_instance(context, instance_uuid, use_slave=False):
    return [fake_block_device.FakeDbBlockDeviceDict(
            {'id': 1,
             'instance_uuid': instance_uuid,
             'device_name': '/dev/fake0',
             'delete_on_termination': 'False',
             'source_type': 'volume',
             'destination_type': 'volume',
             'snapshot_id': None,
             'volume_id': FAKE_UUID_A,
             'volume_size': 1}),
            fake_block_device.FakeDbBlockDeviceDict(
            {'id': 2,
             'instance_uuid': instance_uuid,
             'device_name': '/dev/fake1',
             'delete_on_termination': 'False',
             'source_type': 'volume',
             'destination_type': 'volume',
             'snapshot_id': None,
             'volume_id': FAKE_UUID_B,
             'volume_size': 1})]


class BootFromVolumeTest(test.TestCase):

    def setUp(self):
        super(BootFromVolumeTest, self).setUp()
        self.stubs.Set(compute_api.API, 'create',
                       self._get_fake_compute_api_create())
        fakes.stub_out_nw_api(self.stubs)
        self._block_device_mapping_seen = None
        self._legacy_bdm_seen = True
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Volumes', 'Block_device_mapping_v2_boot'])

    def _get_fake_compute_api_create(self):
        def _fake_compute_api_create(cls, context, instance_type,
                                    image_href, **kwargs):
            self._block_device_mapping_seen = kwargs.get(
                'block_device_mapping')
            self._legacy_bdm_seen = kwargs.get('legacy_bdm')

            inst_type = flavors.get_flavor_by_flavor_id(2)
            resv_id = None
            return ([{'id': 1,
                      'display_name': 'test_server',
                      'uuid': FAKE_UUID,
                      'instance_type': inst_type,
                      'access_ip_v4': '1.2.3.4',
                      'access_ip_v6': 'fead::1234',
                      'image_ref': IMAGE_UUID,
                      'user_id': 'fake',
                      'project_id': 'fake',
                      'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                      'updated_at': datetime.datetime(2010, 11, 11, 11, 0, 0),
                      'progress': 0,
                      'fixed_ips': []
                      }], resv_id)
        return _fake_compute_api_create

    def test_create_root_volume(self):
        body = dict(server=dict(
                name='test_server', imageRef=IMAGE_UUID,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping=[dict(
                        volume_id='1',
                        device_name='/dev/vda',
                        virtual='root',
                        delete_on_termination=False,
                        )]
                ))
        req = fakes.HTTPRequest.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            init_only=('os-volumes_boot', 'servers')))
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertTrue(self._legacy_bdm_seen)
        self.assertEqual('1', self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])

    def test_create_root_volume_bdm_v2(self):
        body = dict(server=dict(
                name='test_server', imageRef=IMAGE_UUID,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping_v2=[dict(
                        source_type='volume',
                        uuid='1',
                        device_name='/dev/vda',
                        boot_index=0,
                        delete_on_termination=False,
                        )]
                ))
        req = fakes.HTTPRequest.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            init_only=('os-volumes_boot', 'servers')))
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertFalse(self._legacy_bdm_seen)
        self.assertEqual('1', self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual(0, self._block_device_mapping_seen[0]['boot_index'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])


class VolumeApiTestV21(test.NoDBTestCase):
    url_prefix = '/v2/fake'

    def setUp(self):
        super(VolumeApiTestV21, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)

        self.stubs.Set(cinder.API, "delete", fakes.stub_volume_delete)
        self.stubs.Set(cinder.API, "get", fakes.stub_volume_get)
        self.stubs.Set(cinder.API, "get_all", fakes.stub_volume_get_all)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Volumes'])

        self.context = context.get_admin_context()
        self.app = self._get_app()

    def _get_app(self):
        return fakes.wsgi_app_v21()

    def test_volume_create(self):
        self.stubs.Set(cinder.API, "create", fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(self.app)

        self.assertEqual(200, resp.status_int)

        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('volume', resp_dict)
        self.assertEqual(vol['size'], resp_dict['volume']['size'])
        self.assertEqual(vol['display_name'],
                         resp_dict['volume']['displayName'])
        self.assertEqual(vol['display_description'],
                         resp_dict['volume']['displayDescription'])
        self.assertEqual(vol['availability_zone'],
                         resp_dict['volume']['availabilityZone'])

    def _test_volume_create_bad(self, cinder_exc, api_exc):
        def fake_volume_create(self, context, size, name, description,
                               snapshot, **param):
            raise cinder_exc

        self.stubs.Set(cinder.API, "create", fake_volume_create)

        vol = {"size": '#$?',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        self.assertRaises(api_exc,
                          volumes.VolumeController().create, req, body=body)

    @mock.patch.object(cinder.API, 'get_snapshot')
    @mock.patch.object(cinder.API, 'create')
    def test_volume_create_bad_snapshot_id(self, mock_create, mock_get):
        vol = {"snapshot_id": '1'}
        body = {"volume": vol}
        mock_get.side_effect = exception.SnapshotNotFound(snapshot_id='1')

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        self.assertRaises(webob.exc.HTTPNotFound,
                          volumes.VolumeController().create, req, body=body)

    def test_volume_create_bad_input(self):
        self._test_volume_create_bad(exception.InvalidInput(reason='fake'),
                                     webob.exc.HTTPBadRequest)

    def test_volume_create_bad_quota(self):
        self._test_volume_create_bad(exception.OverQuota(overs='fake'),
                                     webob.exc.HTTPForbidden)

    def test_volume_index(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_volume_detail(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/detail')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_volume_show(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/123')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_volume_show_no_volume(self):
        self.stubs.Set(cinder.API, "get", fakes.stub_volume_notfound)

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/456')
        resp = req.get_response(self.app)
        self.assertEqual(404, resp.status_int)
        self.assertIn('Volume 456 could not be found.', resp.body)

    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/123')
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(cinder.API, "delete", fakes.stub_volume_notfound)

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/456')
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(404, resp.status_int)
        self.assertIn('Volume 456 could not be found.', resp.body)


class VolumeApiTestV2(VolumeApiTestV21):

    def setUp(self):
        super(VolumeApiTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Volumes'])

        self.context = context.get_admin_context()
        self.app = self._get_app()

    def _get_app(self):
        return fakes.wsgi_app()


class VolumeAttachTestsV21(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(VolumeAttachTestsV21, self).setUp()
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)
        self.stubs.Set(compute_api.API, 'get', fake_get_instance)
        self.stubs.Set(cinder.API, 'get', fake_get_volume)
        self.context = context.get_admin_context()
        self.expected_show = {'volumeAttachment':
            {'device': '/dev/fake0',
             'serverId': FAKE_UUID,
             'id': FAKE_UUID_A,
             'volumeId': FAKE_UUID_A
            }}
        self._set_up_controller()

    def _set_up_controller(self):
        self.attachments = volumes_v21.VolumeAttachmentController()

    def test_show(self):
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = self.attachments.show(req, FAKE_UUID, FAKE_UUID_A)
        self.assertEqual(self.expected_show, result)

    @mock.patch.object(compute_api.API, 'get',
        side_effect=exception.InstanceNotFound(instance_id=FAKE_UUID))
    def test_show_no_instance(self, mock_mr):
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'get_by_instance_uuid', return_value=None)
    def test_show_no_bdms(self, mock_mr):
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    def test_show_bdms_no_mountpoint(self):
        FAKE_UUID_NOTEXIST = '00000000-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_NOTEXIST)

    def test_detach(self):
        self.stubs.Set(compute_api.API,
                       'detach_volume',
                       fake_detach_volume)
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = self.attachments.delete(req, FAKE_UUID, FAKE_UUID_A)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.attachments,
                      volumes_v21.VolumeAttachmentController):
            status_int = self.attachments.delete.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

    def test_detach_vol_not_found(self):
        self.stubs.Set(compute_api.API,
                       'detach_volume',
                       fake_detach_volume)
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.delete,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_C)

    @mock.patch('nova.objects.BlockDeviceMapping.is_root',
                 new_callable=mock.PropertyMock)
    def test_detach_vol_root(self, mock_isroot):
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        mock_isroot.return_value = True
        self.assertRaises(exc.HTTPForbidden,
                          self.attachments.delete,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    def test_detach_volume_from_locked_server(self):
        def fake_detach_volume_from_locked_server(self, context,
                                                  instance, volume):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute_api.API,
                       'detach_volume',
                       fake_detach_volume_from_locked_server)
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(webob.exc.HTTPConflict, self.attachments.delete,
                          req, FAKE_UUID, FAKE_UUID_A)

    def test_attach_volume(self):
        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume)
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])

    @mock.patch.object(compute_api.API, 'attach_volume',
                       return_value='/dev/myfake')
    def test_attach_volume_with_auto_device(self, mock_attach):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': None}}
        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])
        self.assertEqual('/dev/myfake', result['volumeAttachment']['device'])

    def test_attach_volume_to_locked_server(self):
        def fake_attach_volume_to_locked_server(self, context, instance,
                                                volume_id, device=None):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume_to_locked_server)
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(webob.exc.HTTPConflict, self.attachments.create,
                          req, FAKE_UUID, body=body)

    def test_attach_volume_bad_id(self):
        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume)

        body = {
            'volumeAttachment': {
                'device': None,
                'volumeId': 'TESTVOLUME',
            }
        }

        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(self.validation_error, self.attachments.create,
                          req, FAKE_UUID, body=body)

    def test_attach_volume_without_volumeId(self):
        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume)

        body = {
            'volumeAttachment': {
                'device': None
            }
        }

        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(self.validation_error, self.attachments.create,
                          req, FAKE_UUID, body=body)

    def test_attach_volume_with_extra_arg(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake',
                                    'extra': 'extra_arg'}}

        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(self.validation_error, self.attachments.create,
                          req, FAKE_UUID, body=body)

    def _test_swap(self, attachments, uuid=FAKE_UUID_A,
                   fake_func=None, body=None):
        fake_func = fake_func or fake_swap_volume
        self.stubs.Set(compute_api.API,
                       'swap_volume',
                       fake_func)
        body = body or {'volumeAttachment': {'volumeId': FAKE_UUID_B}}

        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        return attachments.update(req, FAKE_UUID, uuid, body=body)

    def test_swap_volume_for_locked_server(self):

        def fake_swap_volume_for_locked_server(self, context, instance,
                                                old_volume, new_volume):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.assertRaises(webob.exc.HTTPConflict, self._test_swap,
                          self.attachments,
                          fake_func=fake_swap_volume_for_locked_server)

    def test_swap_volume(self):
        result = self._test_swap(self.attachments)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.attachments,
                      volumes_v21.VolumeAttachmentController):
            status_int = self.attachments.update.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

    def test_swap_volume_no_attachment(self):
        self.assertRaises(exc.HTTPNotFound, self._test_swap,
                          self.attachments, FAKE_UUID_C)

    def test_swap_volume_without_volumeId(self):
        body = {'volumeAttachment': {'device': '/dev/fake'}}
        self.assertRaises(self.validation_error,
                          self._test_swap,
                          self.attachments,
                          body=body)

    def test_swap_volume_with_extra_arg(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}

        self.assertRaises(self.validation_error,
                          self._test_swap,
                          self.attachments,
                          body=body)


class VolumeAttachTestsV2(VolumeAttachTestsV21):
    validation_error = webob.exc.HTTPBadRequest

    def _set_up_controller(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {'os-volume-attachment-update'}
        self.attachments = volumes.VolumeAttachmentController(ext_mgr)
        ext_mgr_no_update = extensions.ExtensionManager()
        ext_mgr_no_update.extensions = {}
        self.attachments_no_update = volumes.VolumeAttachmentController(
                                                 ext_mgr_no_update)

    def test_swap_volume_no_extension(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_swap,
                          self.attachments_no_update)

    @mock.patch.object(compute_api.API, 'attach_volume',
                       return_value=[])
    def test_attach_volume_with_extra_arg(self, mock_attach):
        # NOTE(gmann): V2 does not perform strong input validation
        # so volume is attached successfully even with extra arg in
        # request body.
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake',
                                    'extra': 'extra_arg'}}
        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])

    def test_swap_volume_with_extra_arg(self):
        # NOTE(gmann): V2 does not perform strong input validation.
        # Volume is swapped successfully even with extra arg in
        # request body. So 'pass' this test for V2.
        pass


class CommonBadRequestTestCase(object):

    resource = None
    entity_name = None
    controller_cls = None
    kwargs = {}
    bad_request = exc.HTTPBadRequest

    """
    Tests of places we throw 400 Bad Request from
    """

    def setUp(self):
        super(CommonBadRequestTestCase, self).setUp()
        self.controller = self.controller_cls()

    def _bad_request_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/' + self.resource)
        req.method = 'POST'

        kwargs = self.kwargs.copy()
        kwargs['body'] = body
        self.assertRaises(self.bad_request,
                          self.controller.create, req, **kwargs)

    def test_create_no_body(self):
        self._bad_request_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._bad_request_create(body=body)

    def test_create_malformed_entity(self):
        body = {self.entity_name: 'string'}
        self._bad_request_create(body=body)


class BadRequestVolumeTestCaseV21(CommonBadRequestTestCase,
                                  test.NoDBTestCase):

    resource = 'os-volumes'
    entity_name = 'volume'
    controller_cls = volumes_v21.VolumeController
    bad_request = exception.ValidationError


class BadRequestVolumeTestCaseV2(BadRequestVolumeTestCaseV21):
    controller_cls = volumes.VolumeController
    bad_request = exc.HTTPBadRequest


class BadRequestAttachmentTestCase(CommonBadRequestTestCase,
                                   test.NoDBTestCase):
    resource = 'servers/' + FAKE_UUID + '/os-volume_attachments'
    entity_name = 'volumeAttachment'
    controller_cls = volumes.VolumeAttachmentController
    kwargs = {'server_id': FAKE_UUID}


class BadRequestSnapshotTestCaseV21(CommonBadRequestTestCase,
                                    test.NoDBTestCase):

    resource = 'os-snapshots'
    entity_name = 'snapshot'
    controller_cls = volumes_v21.SnapshotController
    bad_request = exception.ValidationError


class BadRequestSnapshotTestCaseV2(BadRequestSnapshotTestCaseV21):
    controller_cls = volumes.SnapshotController
    bad_request = exc.HTTPBadRequest


class AssistedSnapshotCreateTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21
    bad_request = exception.ValidationError

    def setUp(self):
        super(AssistedSnapshotCreateTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()
        self.stubs.Set(compute_api.API, 'volume_snapshot_create',
                       fake_compute_volume_snapshot_create)

    def test_assisted_create(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        req.method = 'POST'
        self.controller.create(req, body=body)

    def test_assisted_create_missing_create_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot': {'volume_id': '1'}}
        req.method = 'POST'
        self.assertRaises(self.bad_request, self.controller.create,
                req, body=body)


class AssistedSnapshotCreateTestCaseV2(AssistedSnapshotCreateTestCaseV21):
    assisted_snaps = assisted_snaps_v2
    bad_request = webob.exc.HTTPBadRequest


class AssistedSnapshotDeleteTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def setUp(self):
        super(AssistedSnapshotDeleteTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()
        self.stubs.Set(compute_api.API, 'volume_snapshot_delete',
                       fake_compute_volume_snapshot_delete)

    def test_assisted_delete(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params))
        req.method = 'DELETE'
        result = self.controller.delete(req, '5')
        self._check_status(204, result, self.controller.delete)

    def test_assisted_delete_missing_delete_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                req, '5')


class AssistedSnapshotDeleteTestCaseV2(AssistedSnapshotDeleteTestCaseV21):
    assisted_snaps = assisted_snaps_v2

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, res.status_int)


class TestAssistedVolumeSnapshotsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(TestAssistedVolumeSnapshotsPolicyEnforcementV21, self).setUp()
        self.controller = (
            assisted_snaps_v21.AssistedVolumeSnapshotsController())
        self.req = fakes.HTTPRequest.blank('')

    def test_create_assisted_volumes_snapshots_policy_failed(self):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:create"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.create, self.req, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_assisted_volumes_snapshots_policy_failed(self):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:delete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, '5')

        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class TestVolumeAttachPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(TestVolumeAttachPolicyEnforcementV21, self).setUp()
        self.controller = volumes_v21.VolumeAttachmentController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, rules, rule_name, func, *arg, **kwarg):
        self.policy.set_rules(rules)
        exc = self.assertRaises(
             exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:index"
        rules = {rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name,
                                  self.controller.index, self.req, FAKE_UUID)

    def test_show_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes"
        rules = {"os_compute_api:os-volumes-attachments:show": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.show,
                                  self.req, FAKE_UUID, FAKE_UUID_A)

        rule_name = "os_compute_api:os-volumes-attachments:show"
        rules = {"os_compute_api:os-volumes": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.show,
                                  self.req, FAKE_UUID, FAKE_UUID_A)

    def test_create_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes"
        rules = {"os_compute_api:os-volumes-attachments:create": "@",
                 rule_name: "project:non_fake"}
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        self._common_policy_check(rules, rule_name, self.controller.create,
                                  self.req, FAKE_UUID, body=body)

        rule_name = "os_compute_api:os-volumes-attachments:create"
        rules = {"os_compute_api:os-volumes": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.create,
                                  self.req, FAKE_UUID, body=body)

    def test_update_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes"
        rules = {"os_compute_api:os-volumes-attachments:update": "@",
                 rule_name: "project:non_fake"}
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B}}
        self._common_policy_check(rules, rule_name, self.controller.update,
                                  self.req, FAKE_UUID, FAKE_UUID_A, body=body)

        rule_name = "os_compute_api:os-volumes-attachments:update"
        rules = {"os_compute_api:os-volumes": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.update,
                                  self.req, FAKE_UUID, FAKE_UUID_A, body=body)

    def test_delete_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes"
        rules = {"os_compute_api:os-volumes-attachments:delete": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.delete,
                                  self.req, FAKE_UUID, FAKE_UUID_A)

        rule_name = "os_compute_api:os-volumes-attachments:delete"
        rules = {"os_compute_api:os-volumes": "@",
                 rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.delete,
                                  self.req, FAKE_UUID, FAKE_UUID_A)
