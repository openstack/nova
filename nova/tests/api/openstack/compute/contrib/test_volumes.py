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

from lxml import etree
import mock
from oslo.config import cfg
import webob
from webob import exc

from nova.api.openstack.compute.contrib import assisted_volume_snapshots as \
        assisted_snaps
from nova.api.openstack.compute.contrib import volumes
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_block_device
from nova.tests import fake_instance
from nova.volume import cinder

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUID_A = '00000000-aaaa-aaaa-aaaa-000000000000'
FAKE_UUID_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
FAKE_UUID_C = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
FAKE_UUID_D = 'dddddddd-dddd-dddd-dddd-dddddddddddd'

IMAGE_UUID = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'


def fake_get_instance(self, context, instance_id, want_objects=False):
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
                      'instance_type': dict(inst_type),
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
                        volume_id=1,
                        device_name='/dev/vda',
                        virtual='root',
                        delete_on_termination=False,
                        )]
                ))
        req = webob.Request.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            init_only=('os-volumes_boot', 'servers')))
        self.assertEqual(res.status_int, 202)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(len(self._block_device_mapping_seen), 1)
        self.assertTrue(self._legacy_bdm_seen)
        self.assertEqual(self._block_device_mapping_seen[0]['volume_id'], 1)
        self.assertEqual(self._block_device_mapping_seen[0]['device_name'],
                '/dev/vda')

    def test_create_root_volume_bdm_v2(self):
        body = dict(server=dict(
                name='test_server', imageRef=IMAGE_UUID,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping_v2=[dict(
                        source_type='volume',
                        uuid=1,
                        device_name='/dev/vda',
                        boot_index=0,
                        delete_on_termination=False,
                        )]
                ))
        req = webob.Request.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            init_only=('os-volumes_boot', 'servers')))
        self.assertEqual(res.status_int, 202)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(len(self._block_device_mapping_seen), 1)
        self.assertFalse(self._legacy_bdm_seen)
        self.assertEqual(self._block_device_mapping_seen[0]['volume_id'], 1)
        self.assertEqual(self._block_device_mapping_seen[0]['boot_index'],
                         0)
        self.assertEqual(self._block_device_mapping_seen[0]['device_name'],
                '/dev/vda')


class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
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
        self.app = fakes.wsgi_app(init_only=('os-volumes',))

    def test_volume_create(self):
        self.stubs.Set(cinder.API, "create", fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = webob.Request.blank('/v2/fake/os-volumes')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(self.app)

        self.assertEqual(resp.status_int, 200)

        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('volume', resp_dict)
        self.assertEqual(resp_dict['volume']['size'],
                         vol['size'])
        self.assertEqual(resp_dict['volume']['displayName'],
                         vol['display_name'])
        self.assertEqual(resp_dict['volume']['displayDescription'],
                         vol['display_description'])
        self.assertEqual(resp_dict['volume']['availabilityZone'],
                         vol['availability_zone'])

    def test_volume_create_bad(self):
        def fake_volume_create(self, context, size, name, description,
                               snapshot, **param):
            raise exception.InvalidInput(reason="bad request data")

        self.stubs.Set(cinder.API, "create", fake_volume_create)

        vol = {"size": '#$?',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}

        req = fakes.HTTPRequest.blank('/v2/fake/os-volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          volumes.VolumeController().create, req, body)

    def test_volume_index(self):
        req = webob.Request.blank('/v2/fake/os-volumes')
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)

    def test_volume_detail(self):
        req = webob.Request.blank('/v2/fake/os-volumes/detail')
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)

    def test_volume_show(self):
        req = webob.Request.blank('/v2/fake/os-volumes/123')
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)

    def test_volume_show_no_volume(self):
        self.stubs.Set(cinder.API, "get", fakes.stub_volume_notfound)

        req = webob.Request.blank('/v2/fake/os-volumes/456')
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 404)

    def test_volume_delete(self):
        req = webob.Request.blank('/v2/fake/os-volumes/123')
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(cinder.API, "delete", fakes.stub_volume_notfound)

        req = webob.Request.blank('/v2/fake/os-volumes/456')
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 404)


class VolumeAttachTests(test.TestCase):
    def setUp(self):
        super(VolumeAttachTests, self).setUp()
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
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.attachments = volumes.VolumeAttachmentController(self.ext_mgr)

    def test_show(self):
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = self.attachments.show(req, FAKE_UUID, FAKE_UUID_A)
        self.assertEqual(self.expected_show, result)

    def test_detach(self):
        self.stubs.Set(compute_api.API,
                       'detach_volume',
                       fake_detach_volume)
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = self.attachments.delete(req, FAKE_UUID, FAKE_UUID_A)
        self.assertEqual('202 Accepted', result.status)

    def test_detach_vol_not_found(self):
        self.stubs.Set(compute_api.API,
                       'detach_volume',
                       fake_detach_volume)
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.delete,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_C)

    @mock.patch('nova.objects.block_device.BlockDeviceMapping.is_root',
                 new_callable=mock.PropertyMock)
    def test_detach_vol_root(self, mock_isroot):
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
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
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
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
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = self.attachments.create(req, FAKE_UUID, body)
        self.assertEqual(result['volumeAttachment']['id'],
            '00000000-aaaa-aaaa-aaaa-000000000000')

    def test_attach_volume_to_locked_server(self):
        def fake_attach_volume_to_locked_server(self, context, instance,
                                                volume_id, device=None):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume_to_locked_server)
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        req = webob.Request.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(webob.exc.HTTPConflict, self.attachments.create,
                          req, FAKE_UUID, body)

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

        req = webob.Request.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(webob.exc.HTTPBadRequest, self.attachments.create,
                          req, FAKE_UUID, body)

    def test_attach_volume_without_volumeId(self):
        self.stubs.Set(compute_api.API,
                       'attach_volume',
                       fake_attach_volume)

        body = {
            'volumeAttachment': {
                'device': None
            }
        }

        req = webob.Request.blank('/v2/servers/id/os-volume_attachments')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(webob.exc.HTTPBadRequest, self.attachments.create,
                          req, FAKE_UUID, body)

    def _test_swap(self, uuid=FAKE_UUID_A, fake_func=None, body=None):
        fake_func = fake_func or fake_swap_volume
        self.stubs.Set(compute_api.API,
                       'swap_volume',
                       fake_func)
        body = body or {'volumeAttachment': {'volumeId': FAKE_UUID_B,
                                             'device': '/dev/fake'}}

        req = webob.Request.blank('/v2/servers/id/os-volume_attachments/uuid')
        req.method = 'PUT'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        return self.attachments.update(req, FAKE_UUID, uuid, body)

    def test_swap_volume_for_locked_server(self):
        self.ext_mgr.extensions['os-volume-attachment-update'] = True

        def fake_swap_volume_for_locked_server(self, context, instance,
                                                old_volume, new_volume):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.ext_mgr.extensions['os-volume-attachment-update'] = True
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap,
                          fake_func=fake_swap_volume_for_locked_server)

    def test_swap_volume_no_extension(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_swap)

    def test_swap_volume(self):
        self.ext_mgr.extensions['os-volume-attachment-update'] = True
        result = self._test_swap()
        self.assertEqual('202 Accepted', result.status)

    def test_swap_volume_no_attachment(self):
        self.ext_mgr.extensions['os-volume-attachment-update'] = True

        self.assertRaises(exc.HTTPNotFound, self._test_swap, FAKE_UUID_C)

    def test_swap_volume_without_volumeId(self):
        self.ext_mgr.extensions['os-volume-attachment-update'] = True
        body = {'volumeAttachment': {'device': '/dev/fake'}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_swap,
                          body=body)


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volumeId', 'serverId', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(tree.tag, 'volume')

        for attr in ('id', 'status', 'size', 'availabilityZone', 'createdAt',
                     'displayName', 'displayDescription', 'volumeType',
                     'snapshotId'):
            self.assertEqual(str(vol[attr]), tree.get(attr))

        for child in tree:
            self.assertIn(child.tag, ('attachments', 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_volume_attachment(vol['attachments'][0], child[0])
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertIn(gr_child.get("key"), not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.get("key")]),
                                     gr_child.text)
                    not_seen.remove(gr_child.get("key"))
                self.assertEqual(0, len(not_seen))

    def test_attach_show_create_serializer(self):
        serializer = volumes.VolumeAttachmentTemplate()
        raw_attach = dict(
            id='vol_id',
            volumeId='vol_id',
            serverId='instance_uuid',
            device='/foo')
        text = serializer.serialize(dict(volumeAttachment=raw_attach))

        tree = etree.fromstring(text)

        self.assertEqual('volumeAttachment', tree.tag)
        self._verify_volume_attachment(raw_attach, tree)

    def test_attach_index_serializer(self):
        serializer = volumes.VolumeAttachmentsTemplate()
        raw_attaches = [dict(
                id='vol_id1',
                volumeId='vol_id1',
                serverId='instance1_uuid',
                device='/foo1'),
                        dict(
                id='vol_id2',
                volumeId='vol_id2',
                serverId='instance2_uuid',
                device='/foo2')]
        text = serializer.serialize(dict(volumeAttachments=raw_attaches))

        tree = etree.fromstring(text)

        self.assertEqual('volumeAttachments', tree.tag)
        self.assertEqual(len(raw_attaches), len(tree))
        for idx, child in enumerate(tree):
            self.assertEqual('volumeAttachment', child.tag)
            self._verify_volume_attachment(raw_attaches[idx], child)

    def test_volume_show_create_serializer(self):
        serializer = volumes.VolumeTemplate()
        raw_volume = dict(
            id='vol_id',
            status='vol_status',
            size=1024,
            availabilityZone='vol_availability',
            createdAt=timeutils.utcnow(),
            attachments=[dict(
                    id='vol_id',
                    volumeId='vol_id',
                    serverId='instance_uuid',
                    device='/foo')],
            displayName='vol_name',
            displayDescription='vol_desc',
            volumeType='vol_type',
            snapshotId='snap_id',
            metadata=dict(
                foo='bar',
                baz='quux',
                ),
            )
        text = serializer.serialize(dict(volume=raw_volume))

        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumesTemplate()
        raw_volumes = [dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availabilityZone='vol1_availability',
                createdAt=timeutils.utcnow(),
                attachments=[dict(
                        id='vol1_id',
                        volumeId='vol1_id',
                        serverId='instance_uuid',
                        device='/foo1')],
                displayName='vol1_name',
                displayDescription='vol1_desc',
                volumeType='vol1_type',
                snapshotId='snap1_id',
                metadata=dict(
                    foo='vol1_foo',
                    bar='vol1_bar',
                    ),
                ),
                       dict(
                id='vol2_id',
                status='vol2_status',
                size=1024,
                availabilityZone='vol2_availability',
                createdAt=timeutils.utcnow(),
                attachments=[dict(
                        id='vol2_id',
                        volumeId='vol2_id',
                        serverId='instance_uuid',
                        device='/foo2')],
                displayName='vol2_name',
                displayDescription='vol2_desc',
                volumeType='vol2_type',
                snapshotId='snap2_id',
                metadata=dict(
                    foo='vol2_foo',
                    bar='vol2_bar',
                    ),
                )]
        text = serializer.serialize(dict(volumes=raw_volumes))

        tree = etree.fromstring(text)

        self.assertEqual('volumes', tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_volume(raw_volumes[idx], child)


class TestVolumeCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestVolumeCreateRequestXMLDeserializer, self).setUp()
        self.deserializer = volumes.CreateDeserializer()

    def test_minimal_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_display_name(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_display_description(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_volume_type(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "display_name": "Volume-xml",
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_availability_zone(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_metadata(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        display_name="Volume-xml"
        size="1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "display_name": "Volume-xml",
                "size": "1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEqual(request['body'], expected)

    def test_full_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.maxDiff = None
        self.assertEqual(request['body'], expected)


class CommonUnprocessableEntityTestCase(object):

    resource = None
    entity_name = None
    controller_cls = None
    kwargs = {}

    """
    Tests of places we throw 422 Unprocessable Entity from
    """

    def setUp(self):
        super(CommonUnprocessableEntityTestCase, self).setUp()
        self.controller = self.controller_cls()

    def _unprocessable_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/' + self.resource)
        req.method = 'POST'

        kwargs = self.kwargs.copy()
        kwargs['body'] = body
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, **kwargs)

    def test_create_no_body(self):
        self._unprocessable_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_create(body=body)

    def test_create_malformed_entity(self):
        body = {self.entity_name: 'string'}
        self._unprocessable_create(body=body)


class UnprocessableVolumeTestCase(CommonUnprocessableEntityTestCase,
                                  test.TestCase):

    resource = 'os-volumes'
    entity_name = 'volume'
    controller_cls = volumes.VolumeController


class UnprocessableAttachmentTestCase(CommonUnprocessableEntityTestCase,
                                      test.TestCase):

    resource = 'servers/' + FAKE_UUID + '/os-volume_attachments'
    entity_name = 'volumeAttachment'
    controller_cls = volumes.VolumeAttachmentController
    kwargs = {'server_id': FAKE_UUID}


class UnprocessableSnapshotTestCase(CommonUnprocessableEntityTestCase,
                                    test.TestCase):

    resource = 'os-snapshots'
    entity_name = 'snapshot'
    controller_cls = volumes.SnapshotController


class ShowSnapshotTestCase(test.TestCase):
    def setUp(self):
        super(ShowSnapshotTestCase, self).setUp()
        self.controller = volumes.SnapshotController()
        self.req = fakes.HTTPRequest.blank('/v2/fake/os-snapshots')
        self.req.method = 'GET'

    def test_show_snapshot_not_exist(self):
        def fake_get_snapshot(self, context, id):
            raise exception.SnapshotNotFound(snapshot_id=id)
        self.stubs.Set(cinder.API, 'get_snapshot', fake_get_snapshot)
        self.assertRaises(exc.HTTPNotFound,
                          self.controller.show, self.req, FAKE_UUID_A)


class CreateSnapshotTestCase(test.TestCase):
    def setUp(self):
        super(CreateSnapshotTestCase, self).setUp()
        self.controller = volumes.SnapshotController()
        self.stubs.Set(cinder.API, 'get', fake_get_volume)
        self.stubs.Set(cinder.API, 'create_snapshot_force',
                       fake_create_snapshot)
        self.stubs.Set(cinder.API, 'create_snapshot', fake_create_snapshot)
        self.req = fakes.HTTPRequest.blank('/v2/fake/os-snapshots')
        self.req.method = 'POST'
        self.body = {'snapshot': {'volume_id': 1}}

    def test_force_true(self):
        self.body['snapshot']['force'] = 'True'
        self.controller.create(self.req, body=self.body)

    def test_force_false(self):
        self.body['snapshot']['force'] = 'f'
        self.controller.create(self.req, body=self.body)

    def test_force_invalid(self):
        self.body['snapshot']['force'] = 'foo'
        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.create, self.req, body=self.body)


class DeleteSnapshotTestCase(test.TestCase):
    def setUp(self):
        super(DeleteSnapshotTestCase, self).setUp()
        self.controller = volumes.SnapshotController()
        self.stubs.Set(cinder.API, 'get', fake_get_volume)
        self.stubs.Set(cinder.API, 'create_snapshot_force',
                       fake_create_snapshot)
        self.stubs.Set(cinder.API, 'create_snapshot', fake_create_snapshot)
        self.stubs.Set(cinder.API, 'delete_snapshot', fake_delete_snapshot)
        self.req = fakes.HTTPRequest.blank('/v2/fake/os-snapshots')

    def test_normal_delete(self):
        self.req.method = 'POST'
        self.body = {'snapshot': {'volume_id': 1}}
        result = self.controller.create(self.req, body=self.body)

        self.req.method = 'DELETE'
        result = self.controller.delete(self.req, result['snapshot']['id'])
        self.assertEqual(result.status_int, 202)

    def test_delete_snapshot_not_exists(self):
        def fake_delete_snapshot_not_exist(self, context, snapshot_id):
            raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

        self.stubs.Set(cinder.API, 'delete_snapshot',
            fake_delete_snapshot_not_exist)
        self.req.method = 'POST'
        self.body = {'snapshot': {'volume_id': 1}}
        result = self.controller.create(self.req, body=self.body)

        self.req.method = 'DELETE'
        self.assertRaises(exc.HTTPNotFound, self.controller.delete,
                self.req, result['snapshot']['id'])


class AssistedSnapshotCreateTestCase(test.TestCase):
    def setUp(self):
        super(AssistedSnapshotCreateTestCase, self).setUp()

        self.controller = assisted_snaps.AssistedVolumeSnapshotsController()
        self.stubs.Set(compute_api.API, 'volume_snapshot_create',
                       fake_compute_volume_snapshot_create)

    def test_assisted_create(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot': {'volume_id': 1, 'create_info': {}}}
        req.method = 'POST'
        self.controller.create(req, body=body)

    def test_assisted_create_missing_create_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot': {'volume_id': 1}}
        req.method = 'POST'
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                req, body=body)


class AssistedSnapshotDeleteTestCase(test.TestCase):
    def setUp(self):
        super(AssistedSnapshotDeleteTestCase, self).setUp()

        self.controller = assisted_snaps.AssistedVolumeSnapshotsController()
        self.stubs.Set(compute_api.API, 'volume_snapshot_delete',
                       fake_compute_volume_snapshot_delete)

    def test_assisted_delete(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': 1}),
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                '&'.join(['%s=%s' % (k, v) for k, v in params.iteritems()]))
        req.method = 'DELETE'
        result = self.controller.delete(req, '5')
        self.assertEqual(result.status_int, 204)

    def test_assisted_delete_missing_delete_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                req, '5')
