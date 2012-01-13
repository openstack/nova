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

import datetime
import json
import stubout

from lxml import etree
import webob

from nova.api.openstack.volume import snapshots
from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import volume
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.api.openstack.snapshot')

_last_param = {}


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
    global _last_param
    snapshot = _get_default_snapshot_param()
    snapshot['volume_id'] = volume_id
    snapshot['display_name'] = name
    snapshot['display_description'] = description

    LOG.debug(_("_create: %s"), snapshot)
    _last_param = snapshot
    return snapshot


def stub_snapshot_delete(self, context, snapshot_id):
    global _last_param
    _last_param = dict(snapshot_id=snapshot_id)

    LOG.debug(_("_delete: %s"), locals())
    if snapshot_id != '123':
        raise exception.NotFound


def stub_snapshot_get(self, context, snapshot_id):
    global _last_param
    _last_param = dict(snapshot_id=snapshot_id)

    LOG.debug(_("_get: %s"), locals())
    if snapshot_id != '123':
        raise exception.NotFound

    param = _get_default_snapshot_param()
    param['id'] = snapshot_id
    return param


def stub_snapshot_get_all(self, context):
    LOG.debug(_("_get_all: %s"), locals())
    param = _get_default_snapshot_param()
    param['id'] = 123
    return [param]


class SnapshotApiTest(test.TestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(volume.api.API, "create_snapshot", stub_snapshot_create)
        self.stubs.Set(volume.api.API, "create_snapshot_force",
            stub_snapshot_create)
        self.stubs.Set(volume.api.API, "delete_snapshot", stub_snapshot_delete)
        self.stubs.Set(volume.api.API, "get_snapshot", stub_snapshot_get)
        self.stubs.Set(volume.api.API, "get_all_snapshots",
            stub_snapshot_get_all)

        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(SnapshotApiTest, self).tearDown()

    def test_snapshot_create(self):
        global _last_param
        _last_param = {}

        snapshot = {"volume_id": 12,
                "force": False,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = webob.Request.blank('/v1.1/fake/os-snapshots')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        LOG.debug(_("test_snapshot_create: param=%s"), _last_param)
        self.assertEqual(resp.status_int, 200)

        # Compare if parameters were correctly passed to stub
        self.assertEqual(_last_param['display_name'], "Snapshot Test Name")
        self.assertEqual(_last_param['display_description'],
            "Snapshot Test Desc")

        resp_dict = json.loads(resp.body)
        LOG.debug(_("test_snapshot_create: resp_dict=%s"), resp_dict)
        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['displayName'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['displayDescription'],
                        snapshot['display_description'])

    def test_snapshot_create_force(self):
        global _last_param
        _last_param = {}

        snapshot = {"volume_id": 12,
                "force": True,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc"}
        body = dict(snapshot=snapshot)
        req = webob.Request.blank('/v1.1/fake/os-snapshots')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        LOG.debug(_("test_snapshot_create_force: param=%s"), _last_param)
        self.assertEqual(resp.status_int, 200)

        # Compare if parameters were correctly passed to stub
        self.assertEqual(_last_param['display_name'], "Snapshot Test Name")
        self.assertEqual(_last_param['display_description'],
            "Snapshot Test Desc")

        resp_dict = json.loads(resp.body)
        LOG.debug(_("test_snapshot_create_force: resp_dict=%s"), resp_dict)
        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['displayName'],
                        snapshot['display_name'])
        self.assertEqual(resp_dict['snapshot']['displayDescription'],
                        snapshot['display_description'])

    def test_snapshot_delete(self):
        global _last_param
        _last_param = {}

        snapshot_id = 123
        req = webob.Request.blank('/v1.1/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(str(_last_param['snapshot_id']), str(snapshot_id))

    def test_snapshot_delete_invalid_id(self):
        global _last_param
        _last_param = {}

        snapshot_id = 234
        req = webob.Request.blank('/v1.1/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(_last_param['snapshot_id']), str(snapshot_id))

    def test_snapshot_show(self):
        global _last_param
        _last_param = {}

        snapshot_id = 123
        req = webob.Request.blank('/v1.1/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())

        LOG.debug(_("test_snapshot_show: resp=%s"), resp)
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(_last_param['snapshot_id']), str(snapshot_id))

        resp_dict = json.loads(resp.body)
        self.assertTrue('snapshot' in resp_dict)
        self.assertEqual(resp_dict['snapshot']['id'], str(snapshot_id))

    def test_snapshot_show_invalid_id(self):
        global _last_param
        _last_param = {}

        snapshot_id = 234
        req = webob.Request.blank('/v1.1/fake/os-snapshots/%d' % snapshot_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(_last_param['snapshot_id']), str(snapshot_id))

    def test_snapshot_detail(self):
        req = webob.Request.blank('/v1.1/fake/os-snapshots/detail')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)
        LOG.debug(_("test_snapshot_detail: resp_dict=%s"), resp_dict)
        self.assertTrue('snapshots' in resp_dict)
        resp_snapshots = resp_dict['snapshots']
        self.assertEqual(len(resp_snapshots), 1)

        resp_snapshot = resp_snapshots.pop()
        self.assertEqual(resp_snapshot['id'], 123)


class SnapshotSerializerTest(test.TestCase):
    def _verify_snapshot(self, snap, tree):
        self.assertEqual(tree.tag, 'snapshot')

        for attr in ('id', 'status', 'size', 'createdAt',
                     'displayName', 'displayDescription', 'volumeId'):
            self.assertEqual(str(snap[attr]), tree.get(attr))

    def test_snapshot_show_create_serializer(self):
        serializer = snapshots.SnapshotSerializer()
        raw_snapshot = dict(
            id='snap_id',
            status='snap_status',
            size=1024,
            createdAt=datetime.datetime.now(),
            displayName='snap_name',
            displayDescription='snap_desc',
            volumeId='vol_id',
            )
        text = serializer.serialize(dict(snapshot=raw_snapshot), 'show')

        print text
        tree = etree.fromstring(text)

        self._verify_snapshot(raw_snapshot, tree)

    def test_snapshot_index_detail_serializer(self):
        serializer = snapshots.SnapshotSerializer()
        raw_snapshots = [dict(
                id='snap1_id',
                status='snap1_status',
                size=1024,
                createdAt=datetime.datetime.now(),
                displayName='snap1_name',
                displayDescription='snap1_desc',
                volumeId='vol1_id',
                ),
                       dict(
                id='snap2_id',
                status='snap2_status',
                size=1024,
                createdAt=datetime.datetime.now(),
                displayName='snap2_name',
                displayDescription='snap2_desc',
                volumeId='vol2_id',
                )]
        text = serializer.serialize(dict(snapshots=raw_snapshots), 'index')

        print text
        tree = etree.fromstring(text)

        self.assertEqual('snapshots', tree.tag)
        self.assertEqual(len(raw_snapshots), len(tree))
        for idx, child in enumerate(tree):
            self._verify_snapshot(raw_snapshots[idx], child)
