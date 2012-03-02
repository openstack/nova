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

from lxml import etree
import webob

from nova.api.openstack.volume import volumes
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova.volume import api as volume_api


FLAGS = flags.FLAGS


class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.controller = volumes.VolumeController()

        self.stubs.Set(volume_api.API, 'get_all', fakes.stub_volume_get_all)
        self.stubs.Set(volume_api.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(volume_api.API, 'delete', fakes.stub_volume_delete)

    def test_volume_create(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.create(req, body)
        expected = {'volume': {'status': 'fakestatus',
                               'displayDescription': 'Volume Test Desc',
                               'availabilityZone': 'zone1:host1',
                               'displayName': 'Volume Test Name',
                               'attachments': [{'device': '/',
                                                'serverId': 'fakeuuid',
                                                'id': '1',
                                                'volumeId': '1'}],
                               'volumeType': 'vol_type_name',
                               'snapshotId': None,
                               'metadata': {},
                               'id': '1',
                               'createdAt': datetime.datetime(1, 1, 1,
                                                              1, 1, 1),
                               'size': 100}}
        self.assertEqual(res_dict, expected)

    def test_volume_create_no_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create,
                          req,
                          body)

    def test_volume_list(self):
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'displayDescription': 'displaydesc',
                                 'availabilityZone': 'fakeaz',
                                 'displayName': 'displayname',
                                 'attachments': [{'device': '/',
                                                  'serverId': 'fakeuuid',
                                                  'id': '1',
                                                  'volumeId': '1'}],
                                 'volumeType': 'vol_type_name',
                                 'snapshotId': None,
                                 'metadata': {},
                                 'id': '1',
                                 'createdAt': datetime.datetime(1, 1, 1,
                                                                1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(res_dict, expected)

    def test_volume_list_detail(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'displayDescription': 'displaydesc',
                                 'availabilityZone': 'fakeaz',
                                 'displayName': 'displayname',
                                 'attachments': [{'device': '/',
                                                  'serverId': 'fakeuuid',
                                                  'id': '1',
                                                  'volumeId': '1'}],
                                 'volumeType': 'vol_type_name',
                                 'snapshotId': None,
                                 'metadata': {},
                                 'id': '1',
                                 'createdAt': datetime.datetime(1, 1, 1,
                                                                1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(res_dict, expected)

    def test_volume_show(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, 1)
        expected = {'volume': {'status': 'fakestatus',
                               'displayDescription': 'displaydesc',
                               'availabilityZone': 'fakeaz',
                               'displayName': 'displayname',
                               'attachments': [{'device': '/',
                                                'serverId': 'fakeuuid',
                                                'id': '1',
                                                'volumeId': '1'}],
                               'volumeType': 'vol_type_name',
                               'snapshotId': None,
                               'metadata': {},
                               'id': '1',
                               'createdAt': datetime.datetime(1, 1, 1,
                                                              1, 1, 1),
                               'size': 1}}
        self.assertEqual(res_dict, expected)

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id):
            return fakes.stub_volume(volume_id, attach_status='detached')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, 1)
        expected = {'volume': {'status': 'fakestatus',
                               'displayDescription': 'displaydesc',
                               'availabilityZone': 'fakeaz',
                               'displayName': 'displayname',
                               'attachments': [],
                               'volumeType': 'vol_type_name',
                               'snapshotId': None,
                               'metadata': {},
                               'id': '1',
                               'createdAt': datetime.datetime(1, 1, 1,
                                                              1, 1, 1),
                               'size': 1}}
        self.assertEqual(res_dict, expected)

    def test_volume_show_no_volume(self):
        self.stubs.Set(volume_api.API, "get", fakes.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req,
                          1)

    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        resp = self.controller.delete(req, 1)
        self.assertEqual(resp.status_int, 202)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(volume_api.API, "get", fakes.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req,
                          1)


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
