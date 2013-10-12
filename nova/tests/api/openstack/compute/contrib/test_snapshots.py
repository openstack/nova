# Copyright 2011 Denali Systems, Inc.
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

from lxml import etree
import webob

from nova.api.openstack.compute.contrib import volumes
from nova import context
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.volume import cinder


class SnapshotApiTest(test.NoDBTestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(cinder.API, "create_snapshot",
                       fakes.stub_snapshot_create)
        self.stubs.Set(cinder.API, "create_snapshot_force",
                       fakes.stub_snapshot_create)
        self.stubs.Set(cinder.API, "delete_snapshot",
                       fakes.stub_snapshot_delete)
        self.stubs.Set(cinder.API, "get_snapshot", fakes.stub_snapshot_get)
        self.stubs.Set(cinder.API, "get_all_snapshots",
                       fakes.stub_snapshot_get_all)
        self.stubs.Set(cinder.API, "get", fakes.stub_volume_get)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Volumes'])

        self.context = context.get_admin_context()
        self.app = fakes.wsgi_app(init_only=('os-snapshots',))

    def test_snapshot_create(self):
        snapshot = {"volume_id": 12,
                "force": False,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = webob.Request.blank('/v2/fake/os-snapshots')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)
        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('snapshot', resp_dict)
        self.assertEqual(resp_dict['snapshot']['displayName'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['displayDescription'],
                        snapshot['display_description'])
        self.assertEqual(resp_dict['snapshot']['volumeId'],
                         snapshot['volume_id'])

    def test_snapshot_create_force(self):
        snapshot = {"volume_id": 12,
                "force": True,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = webob.Request.blank('/v2/fake/os-snapshots')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)

        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('snapshot', resp_dict)
        self.assertEqual(resp_dict['snapshot']['displayName'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['displayDescription'],
                        snapshot['display_description'])
        self.assertEqual(resp_dict['snapshot']['volumeId'],
                         snapshot['volume_id'])

        # Test invalid force paramter
        snapshot = {"volume_id": 12,
                "force": '**&&^^%%$$##@@'}
        body = dict(snapshot=snapshot)
        req = webob.Request.blank('/v2/fake/os-snapshots')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 400)

    def test_snapshot_delete(self):
        snapshot_id = 123
        req = webob.Request.blank('/v2/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'DELETE'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)

    def test_snapshot_delete_invalid_id(self):
        snapshot_id = -1
        req = webob.Request.blank('/v2/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'DELETE'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 404)

    def test_snapshot_show(self):
        snapshot_id = 123
        req = webob.Request.blank('/v2/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'GET'
        resp = req.get_response(self.app)

        self.assertEqual(resp.status_int, 200)
        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('snapshot', resp_dict)
        self.assertEqual(resp_dict['snapshot']['id'], str(snapshot_id))

    def test_snapshot_show_invalid_id(self):
        snapshot_id = -1
        req = webob.Request.blank('/v2/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'GET'
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 404)

    def test_snapshot_detail(self):
        req = webob.Request.blank('/v2/fake/os-snapshots/detail')
        req.method = 'GET'
        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)

        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('snapshots', resp_dict)
        resp_snapshots = resp_dict['snapshots']
        self.assertEqual(len(resp_snapshots), 3)

        resp_snapshot = resp_snapshots.pop()
        self.assertEqual(resp_snapshot['id'], 102)


class SnapshotSerializerTest(test.NoDBTestCase):
    def _verify_snapshot(self, snap, tree):
        self.assertEqual(tree.tag, 'snapshot')

        for attr in ('id', 'status', 'size', 'createdAt',
                     'displayName', 'displayDescription', 'volumeId'):
            self.assertEqual(str(snap[attr]), tree.get(attr))

    def test_snapshot_show_create_serializer(self):
        serializer = volumes.SnapshotTemplate()
        raw_snapshot = dict(
            id='snap_id',
            status='snap_status',
            size=1024,
            createdAt=timeutils.utcnow(),
            displayName='snap_name',
            displayDescription='snap_desc',
            volumeId='vol_id',
            )
        text = serializer.serialize(dict(snapshot=raw_snapshot))

        tree = etree.fromstring(text)

        self._verify_snapshot(raw_snapshot, tree)

    def test_snapshot_index_detail_serializer(self):
        serializer = volumes.SnapshotsTemplate()
        raw_snapshots = [dict(
                id='snap1_id',
                status='snap1_status',
                size=1024,
                createdAt=timeutils.utcnow(),
                displayName='snap1_name',
                displayDescription='snap1_desc',
                volumeId='vol1_id',
                ),
                       dict(
                id='snap2_id',
                status='snap2_status',
                size=1024,
                createdAt=timeutils.utcnow(),
                displayName='snap2_name',
                displayDescription='snap2_desc',
                volumeId='vol2_id',
                )]
        text = serializer.serialize(dict(snapshots=raw_snapshots))

        tree = etree.fromstring(text)

        self.assertEqual('snapshots', tree.tag)
        self.assertEqual(len(raw_snapshots), len(tree))
        for idx, child in enumerate(tree):
            self._verify_snapshot(raw_snapshots[idx], child)
