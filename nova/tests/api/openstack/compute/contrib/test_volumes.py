# Copyright 2013 Josh Durgin
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
import json

from lxml import etree
import webob

import nova
from nova.api.openstack.compute.contrib import volumes
from nova.compute import instance_types
from nova import context
import nova.db
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import volume


FLAGS = flags.FLAGS

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
IMAGE_UUID = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'


def fake_compute_api_create(cls, context, instance_type, image_href, **kwargs):
    global _block_device_mapping_seen
    _block_device_mapping_seen = kwargs.get('block_device_mapping')

    inst_type = instance_types.get_instance_type_by_flavor_id(2)
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


class BootFromVolumeTest(test.TestCase):

    def setUp(self):
        super(BootFromVolumeTest, self).setUp()
        self.stubs.Set(nova.compute.API, 'create', fake_compute_api_create)
        fakes.stub_out_nw_api(self.stubs)

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
        global _block_device_mapping_seen
        _block_device_mapping_seen = None
        req = webob.Request.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(FLAGS.password_length, len(server['adminPass']))
        self.assertEqual(len(_block_device_mapping_seen), 1)
        self.assertEqual(_block_device_mapping_seen[0]['volume_id'], 1)
        self.assertEqual(_block_device_mapping_seen[0]['device_name'],
                '/dev/vda')


def return_volume(context, volume_id):
    return {'id': volume_id}


class VolumeApiTest(test.TestCase):

    def setUp(self, test_obj=None):
        super(VolumeApiTest, self).setUp()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db, 'volume_get', return_volume)

        self.stubs.Set(volume.api.API, "delete", fakes.stub_volume_delete)
        self.stubs.Set(volume.api.API, "get", fakes.stub_volume_get)
        self.stubs.Set(volume.api.API, "get_all", fakes.stub_volume_get_all)

        self.context = context.get_admin_context()
        self.test_obj = test_obj if test_obj else "volume"

    def test_volume_create(self):
        self.stubs.Set(volume.api.API, "create", fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {self.test_obj: vol}
        req = webob.Request.blank('/v2/fake/os-volumes')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(fakes.wsgi_app())

        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 200)

            resp_dict = json.loads(resp.body)
            self.assertTrue(self.test_obj in resp_dict)
            self.assertEqual(resp_dict[self.test_obj]['size'],
                             vol['size'])
            self.assertEqual(resp_dict[self.test_obj]['displayName'],
                             vol['display_name'])
            self.assertEqual(resp_dict[self.test_obj]['displayDescription'],
                             vol['display_description'])
            self.assertEqual(resp_dict[self.test_obj]['availabilityZone'],
                             vol['availability_zone'])
        else:
            self.assertEqual(resp.status_int, 400)

    def test_volume_create_no_body(self):
        req = webob.Request.blank('/v2/fake/os-volumes')
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 422)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_volume_index(self):
        req = webob.Request.blank('/v2/fake/os-volumes')
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_volume_detail(self):
        req = webob.Request.blank('/v2/fake/os-volumes/detail')
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_volume_show(self):
        req = webob.Request.blank('/v2/fake/os-volumes/123')
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_volume_show_no_volume(self):
        self.stubs.Set(volume.api.API, "get", fakes.stub_volume_get_notfound)

        req = webob.Request.blank('/v2/fake/os-volumes/456')
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)

    def test_volume_delete(self):
        req = webob.Request.blank('/v2/fake/os-volumes/123')
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 202)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(volume.api.API, "get", fakes.stub_volume_get_notfound)

        req = webob.Request.blank('/v2/fake/os-volumes/456')
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 404)
        else:
            self.assertEqual(resp.status_int, 400)


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
            self.assertTrue(child.tag in ('attachments', 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_volume_attachment(vol['attachments'][0], child[0])
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertTrue(gr_child.tag in not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.tag]),
                                     gr_child.text)
                    not_seen.remove(gr_child.tag)
                self.assertEqual(0, len(not_seen))

    def test_attach_show_create_serializer(self):
        serializer = volumes.VolumeAttachmentTemplate()
        raw_attach = dict(
            id='vol_id',
            volumeId='vol_id',
            serverId='instance_uuid',
            device='/foo')
        text = serializer.serialize(dict(volumeAttachment=raw_attach))

        print text
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

        print text
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
            createdAt=datetime.datetime.now(),
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

        print text
        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumesTemplate()
        raw_volumes = [dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availabilityZone='vol1_availability',
                createdAt=datetime.datetime.now(),
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
                createdAt=datetime.datetime.now(),
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

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volumes', tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_volume(raw_volumes[idx], child)
