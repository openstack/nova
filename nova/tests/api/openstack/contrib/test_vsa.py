# Copyright 2011 OpenStack LLC.
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

import json
import stubout
import unittest
import webob

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import volume
from nova import vsa
from nova.api import openstack
from nova.tests.api.openstack import fakes
import nova.wsgi

from nova.api.openstack.contrib.virtual_storage_arrays import _vsa_view

FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.api.openstack.vsa')

last_param = {}


def _get_default_vsa_param():
    return {
        'display_name': 'Test_VSA_name',
        'display_description': 'Test_VSA_description',
        'vc_count': 1,
        'instance_type': 'm1.small',
        'instance_type_id': 5,
        'image_name': None,
        'availability_zone': None,
        'storage': [],
        'shared': False
        }


def stub_vsa_create(self, context, **param):
    global last_param
    LOG.debug(_("_create: param=%s"), param)
    param['id'] = 123
    param['name'] = 'Test name'
    param['instance_type_id'] = 5
    last_param = param
    return param


def stub_vsa_delete(self, context, vsa_id):
    global last_param
    last_param = dict(vsa_id=vsa_id)

    LOG.debug(_("_delete: %s"), locals())
    if vsa_id != '123':
        raise exception.NotFound


def stub_vsa_get(self, context, vsa_id):
    global last_param
    last_param = dict(vsa_id=vsa_id)

    LOG.debug(_("_get: %s"), locals())
    if vsa_id != '123':
        raise exception.NotFound

    param = _get_default_vsa_param()
    param['id'] = vsa_id
    return param


def stub_vsa_get_all(self, context):
    LOG.debug(_("_get_all: %s"), locals())
    param = _get_default_vsa_param()
    param['id'] = 123
    return [param]


class VSAApiTest(test.TestCase):
    def setUp(self):
        super(VSAApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(vsa.api.API, "create", stub_vsa_create)
        self.stubs.Set(vsa.api.API, "delete", stub_vsa_delete)
        self.stubs.Set(vsa.api.API, "get", stub_vsa_get)
        self.stubs.Set(vsa.api.API, "get_all", stub_vsa_get_all)

        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSAApiTest, self).tearDown()

    def test_vsa_create(self):
        global last_param
        last_param = {}

        vsa = {"displayName": "VSA Test Name",
               "displayDescription": "VSA Test Desc"}
        body = dict(vsa=vsa)
        req = webob.Request.blank('/v1.1/777/zadr-vsa')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        # Compare if parameters were correctly passed to stub
        self.assertEqual(last_param['display_name'], "VSA Test Name")
        self.assertEqual(last_param['display_description'], "VSA Test Desc")

        resp_dict = json.loads(resp.body)
        self.assertTrue('vsa' in resp_dict)
        self.assertEqual(resp_dict['vsa']['displayName'], vsa['displayName'])
        self.assertEqual(resp_dict['vsa']['displayDescription'],
                         vsa['displayDescription'])

    def test_vsa_create_no_body(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa')
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 422)

    def test_vsa_delete(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v1.1/777/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_delete_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v1.1/777/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_show(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v1.1/777/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

        resp_dict = json.loads(resp.body)
        self.assertTrue('vsa' in resp_dict)
        self.assertEqual(resp_dict['vsa']['id'], str(vsa_id))

    def test_vsa_show_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v1.1/777/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_index(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)

    def test_vsa_detail(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/detail')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)


def _get_default_volume_param():
    return {
        'id': 123,
        'status': 'available',
        'size': 100,
        'availability_zone': 'nova',
        'created_at': None,
        'attach_status': 'detached',
        'name': 'vol name',
        'display_name': 'Default vol name',
        'display_description': 'Default vol description',
        'volume_type_id': 1,
        'volume_metadata': [],
        }


def stub_get_vsa_volume_type(self, context):
    return {'id': 1,
            'name': 'VSA volume type',
            'extra_specs': {'type': 'vsa_volume'}}


def stub_volume_create(self, context, size, snapshot_id, name, description,
                       **param):
    LOG.debug(_("_create: param=%s"), size)
    vol = _get_default_volume_param()
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    return vol


def stub_volume_update(self, context, **param):
    LOG.debug(_("_volume_update: param=%s"), param)
    pass


def stub_volume_delete(self, context, **param):
    LOG.debug(_("_volume_delete: param=%s"), param)
    pass


def stub_volume_get(self, context, volume_id):
    LOG.debug(_("_volume_get: volume_id=%s"), volume_id)
    vol = _get_default_volume_param()
    vol['id'] = volume_id
    meta = {'key': 'from_vsa_id', 'value': '123'}
    if volume_id == '345':
        meta = {'key': 'to_vsa_id', 'value': '123'}
    vol['volume_metadata'].append(meta)
    return vol


def stub_volume_get_notfound(self, context, volume_id):
    raise exception.NotFound


def stub_volume_get_all(self, context, search_opts):
    vol = stub_volume_get(self, context, '123')
    vol['metadata'] = search_opts['metadata']
    return [vol]


def return_vsa(context, vsa_id):
    return {'id': vsa_id}


class VSAVolumeApiTest(test.TestCase):

    def setUp(self, test_obj=None, test_objs=None):
        super(VSAVolumeApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db.api, 'vsa_get', return_vsa)
        self.stubs.Set(vsa.api.API, "get_vsa_volume_type",
                        stub_get_vsa_volume_type)

        self.stubs.Set(volume.api.API, "update", stub_volume_update)
        self.stubs.Set(volume.api.API, "delete", stub_volume_delete)
        self.stubs.Set(volume.api.API, "get", stub_volume_get)
        self.stubs.Set(volume.api.API, "get_all", stub_volume_get_all)

        self.context = context.get_admin_context()
        self.test_obj = test_obj if test_obj else "volume"
        self.test_objs = test_objs if test_objs else "volumes"

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSAVolumeApiTest, self).tearDown()

    def test_vsa_volume_create(self):
        self.stubs.Set(volume.api.API, "create", stub_volume_create)

        vol = {"size": 100,
               "displayName": "VSA Volume Test Name",
               "displayDescription": "VSA Volume Test Desc"}
        body = {self.test_obj: vol}
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s' % self.test_objs)
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
                             vol['displayName'])
            self.assertEqual(resp_dict[self.test_obj]['displayDescription'],
                             vol['displayDescription'])
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_create_no_body(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s' % self.test_objs)
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 422)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_index(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s' % self.test_objs)
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_detail(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/detail' % \
                self.test_objs)
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_show(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_show_no_vsa_assignment(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/4/%s/333' % \
                (self.test_objs))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_show_no_volume(self):
        self.stubs.Set(volume.api.API, "get", stub_volume_get_notfound)

        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/333' % \
                (self.test_objs))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)

    def test_vsa_volume_update(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        update = {"status": "available",
                  "displayName": "Test Display name"}
        body = {self.test_obj: update}
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        req.method = 'PUT'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 202)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 202)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete_no_vsa_assignment(self):
        req = webob.Request.blank('/v1.1/777/zadr-vsa/4/%s/333' % \
                (self.test_objs))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete_no_volume(self):
        self.stubs.Set(volume.api.API, "get", stub_volume_get_notfound)

        req = webob.Request.blank('/v1.1/777/zadr-vsa/123/%s/333' % \
                (self.test_objs))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 404)
        else:
            self.assertEqual(resp.status_int, 400)


class VSADriveApiTest(VSAVolumeApiTest):
    def setUp(self):
        super(VSADriveApiTest, self).setUp(test_obj="drive",
                                           test_objs="drives")

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSADriveApiTest, self).tearDown()
