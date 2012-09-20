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

from nova.api.openstack.volume import snapshots
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova import volume

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


def _get_default_snapshot_param():
    return {
        'id': 123,
        'volume_id': 12,
        'status': 'available',
        'volume_size': 100,
        'created_at': None,
        'display_name': 'Default name',
        'display_description': 'Default description',
        }


def stub_snapshot_create(self, context, volume_id, name, description):
    snapshot = _get_default_snapshot_param()
    snapshot['volume_id'] = volume_id
    snapshot['display_name'] = name
    snapshot['display_description'] = description
    return snapshot


def stub_snapshot_delete(self, context, snapshot):
    if snapshot['id'] != 123:
        raise exception.NotFound


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id != 123:
        raise exception.NotFound

    param = _get_default_snapshot_param()
    return param


def stub_snapshot_get_all(self, context, search_opts=None):
    param = _get_default_snapshot_param()
    return [param]


class SnapshotApiTest(test.TestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        self.controller = snapshots.SnapshotsController()

        self.stubs.Set(db, 'snapshot_get_all_by_project',
                       fakes.stub_snapshot_get_all_by_project)
        self.stubs.Set(db, 'snapshot_get_all',
                      fakes.stub_snapshot_get_all)

    def test_snapshot_create(self):
        self.stubs.Set(volume.api.API, "create_snapshot", stub_snapshot_create)
        self.stubs.Set(volume.api.API, 'get', fakes.stub_volume_get)
        snapshot = {"volume_id": '12',
                "force": False,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        resp_dict = self.controller.create(req, body)

        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['display_name'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['display_description'],
                        snapshot['display_description'])

    def test_snapshot_create_force(self):
        self.stubs.Set(volume.api.API, "create_snapshot_force",
            stub_snapshot_create)
        self.stubs.Set(volume.api.API, 'get', fakes.stub_volume_get)
        snapshot = {"volume_id": '12',
                "force": True,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        resp_dict = self.controller.create(req, body)

        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['display_name'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['display_description'],
                        snapshot['display_description'])

        # Test invalid force paramter
        snapshot = {"volume_id": 12,
                "force": '**&&^^%%$$##@@'}
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.create,
                          req,
                          body)

    def test_snapshot_create_nonexistent_volume_id(self):
        self.stubs.Set(volume.api.API, 'get', fakes.stub_volume_get_notfound)

        snapshot = {"volume_id": 13,
                "force": False,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create,
                          req,
                          body)

    def test_snapshot_delete(self):
        self.stubs.Set(volume.api.API, "get_snapshot", stub_snapshot_get)
        self.stubs.Set(volume.api.API, "delete_snapshot", stub_snapshot_delete)

        snapshot_id = 123
        req = fakes.HTTPRequest.blank('/v1/snapshots/%d' % snapshot_id)
        resp = self.controller.delete(req, snapshot_id)
        self.assertEqual(resp.status_int, 202)

    def test_snapshot_delete_invalid_id(self):
        self.stubs.Set(volume.api.API, "delete_snapshot", stub_snapshot_delete)
        snapshot_id = 234
        req = fakes.HTTPRequest.blank('/v1/snapshots/%d' % snapshot_id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req,
                          snapshot_id)

    def test_snapshot_show(self):
        self.stubs.Set(volume.api.API, "get_snapshot", stub_snapshot_get)
        req = fakes.HTTPRequest.blank('/v1/snapshots/123')
        resp_dict = self.controller.show(req, 123)

        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['id'], '123')

    def test_snapshot_show_invalid_id(self):
        snapshot_id = 234
        req = fakes.HTTPRequest.blank('/v1/snapshots/%d' % snapshot_id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req,
                          snapshot_id)

    def test_snapshot_detail(self):
        self.stubs.Set(volume.api.API, "get_all_snapshots",
                      stub_snapshot_get_all)
        req = fakes.HTTPRequest.blank('/v1/snapshots/detail')
        resp_dict = self.controller.detail(req)

        self.assertTrue('snapshots' in resp_dict)
        resp_snapshots = resp_dict['snapshots']
        self.assertEqual(len(resp_snapshots), 1)

        resp_snapshot = resp_snapshots.pop()
        self.assertEqual(resp_snapshot['id'], '123')

    def test_admin_list_snapshots_limited_to_project(self):
        req = fakes.HTTPRequest.blank('/v1/fake/snapshots',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertTrue('snapshots' in res)
        self.assertEqual(1, len(res['snapshots']))

    def test_admin_list_snapshots_all_tenants(self):
        req = fakes.HTTPRequest.blank('/v1/fake/snapshots?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertTrue('snapshots' in res)
        self.assertEqual(3, len(res['snapshots']))

    def test_all_tenants_non_admin_gets_all_tenants(self):
        req = fakes.HTTPRequest.blank('/v1/fake/snapshots?all_tenants=1')
        res = self.controller.index(req)
        self.assertTrue('snapshots' in res)
        self.assertEqual(1, len(res['snapshots']))

    def test_non_admin_get_by_project(self):
        req = fakes.HTTPRequest.blank('/v1/fake/snapshots')
        res = self.controller.index(req)
        self.assertTrue('snapshots' in res)
        self.assertEqual(1, len(res['snapshots']))


class SnapshotSerializerTest(test.TestCase):
    def _verify_snapshot(self, snap, tree):
        self.assertEqual(tree.tag, 'snapshot')

        for attr in ('id', 'status', 'size', 'created_at',
                     'display_name', 'display_description', 'volume_id'):
            self.assertEqual(str(snap[attr]), tree.get(attr))

    def test_snapshot_show_create_serializer(self):
        serializer = snapshots.SnapshotTemplate()
        raw_snapshot = dict(
            id='snap_id',
            status='snap_status',
            size=1024,
            created_at=timeutils.utcnow(),
            display_name='snap_name',
            display_description='snap_desc',
            volume_id='vol_id',
            )
        text = serializer.serialize(dict(snapshot=raw_snapshot))

        print text
        tree = etree.fromstring(text)

        self._verify_snapshot(raw_snapshot, tree)

    def test_snapshot_index_detail_serializer(self):
        serializer = snapshots.SnapshotsTemplate()
        raw_snapshots = [dict(
                id='snap1_id',
                status='snap1_status',
                size=1024,
                created_at=timeutils.utcnow(),
                display_name='snap1_name',
                display_description='snap1_desc',
                volume_id='vol1_id',
                ),
                       dict(
                id='snap2_id',
                status='snap2_status',
                size=1024,
                created_at=timeutils.utcnow(),
                display_name='snap2_name',
                display_description='snap2_desc',
                volume_id='vol2_id',
                )]
        text = serializer.serialize(dict(snapshots=raw_snapshots))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('snapshots', tree.tag)
        self.assertEqual(len(raw_snapshots), len(tree))
        for idx, child in enumerate(tree):
            self._verify_snapshot(raw_snapshots[idx], child)


class SnapshotsUnprocessableEntityTestCase(test.TestCase):

    """
    Tests of places we throw 422 Unprocessable Entity from
    """

    def setUp(self):
        super(SnapshotsUnprocessableEntityTestCase, self).setUp()
        self.controller = snapshots.SnapshotsController()

    def _unprocessable_snapshot_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/snapshots')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, body)

    def test_create_no_body(self):
        self._unprocessable_snapshot_create(body=None)

    def test_create_missing_snapshot(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_snapshot_create(body=body)

    def test_create_malformed_entity(self):
        body = {'snapshot': 'string'}
        self._unprocessable_snapshot_create(body=body)
