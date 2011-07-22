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
import webob

#from nova import compute
from nova import vsa
from nova import exception
from nova import context
from nova import test
from nova import log as logging
from nova.tests.api.openstack import fakes

from nova.api.openstack.contrib.virtual_storage_arrays import _vsa_view

LOG = logging.getLogger('nova.tests.api.openstack.vsa')

last_param = {}


def _get_default_vsa_param():
    return {
        'display_name': 'Test_VSA_name',
        'display_description': 'Test_VSA_description',
        'vc_count': 1,
        'instance_type': 'm1.small',
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

    def test_vsa_api_create(self):
        global last_param
        last_param = {}

        vsa = {"displayName": "VSA Test Name",
               "displayDescription": "VSA Test Desc"}
        body = dict(vsa=vsa)
        req = webob.Request.blank('/v1.1/zadr-vsa')
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

    def test_vsa_api_create_no_body(self):
        req = webob.Request.blank('/v1.1/zadr-vsa')
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 422)

    def test_vsa_api_delete(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v1.1/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_api_delete_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v1.1/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_api_show(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v1.1/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

        resp_dict = json.loads(resp.body)
        self.assertTrue('vsa' in resp_dict)
        self.assertEqual(resp_dict['vsa']['id'], str(vsa_id))

    def test_vsa_api_show_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v1.1/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_api_index(self):
        req = webob.Request.blank('/v1.1/zadr-vsa')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)

    def test_vsa_api_detail(self):
        req = webob.Request.blank('/v1.1/zadr-vsa/detail')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)


class VSAVolumeDriveApiTest(test.TestCase):
    def setUp(self):
        super(VSAVolumeDriveApiTest, self).setUp()
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
        super(VSAVolumeDriveApiTest, self).tearDown()
