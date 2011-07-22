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
from nova.vsa import drive_types
from nova import exception
from nova import context
from nova import test
from nova import log as logging
from nova.tests.api.openstack import fakes

from nova.api.openstack.contrib.drive_types import _drive_type_view

LOG = logging.getLogger('nova.tests.api.openstack.drive_types')

last_param = {}


def _get_default_drive_type():
    param = {
        'name': 'Test drive type',
        'type': 'SATA',
        'size_gb': 123,
        'rpm': '7200',
        'capabilities': '',
        'visible': True
        }
    return param


def _create(context, **param):
    global last_param
    LOG.debug(_("_create: %s"), param)
    param['id'] = 123
    last_param = param
    return param


def _delete(context, id):
    global last_param
    last_param = dict(id=id)

    LOG.debug(_("_delete: %s"), locals())


def _get(context, id):
    global last_param
    last_param = dict(id=id)

    LOG.debug(_("_get: %s"), locals())
    if id != '123':
        raise exception.NotFound

    dtype = _get_default_drive_type()
    dtype['id'] = id
    return dtype


def _get_all(context, visible=True):
    LOG.debug(_("_get_all: %s"), locals())
    dtype = _get_default_drive_type()
    dtype['id'] = 123
    return [dtype]


class DriveTypesApiTest(test.TestCase):
    def setUp(self):
        super(DriveTypesApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(drive_types, "create", _create)
        self.stubs.Set(drive_types, "delete", _delete)
        self.stubs.Set(drive_types, "get", _get)
        self.stubs.Set(drive_types, "get_all", _get_all)

        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(DriveTypesApiTest, self).tearDown()

    def test_drive_types_api_create(self):
        global last_param
        last_param = {}

        dtype = _get_default_drive_type()
        dtype['id'] = 123

        body = dict(drive_type=_drive_type_view(dtype))
        req = webob.Request.blank('/v1.1/zadr-drive_types')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        # Compare if parameters were correctly passed to stub
        for k, v in last_param.iteritems():
            self.assertEqual(last_param[k], dtype[k])

        resp_dict = json.loads(resp.body)

        # Compare response
        self.assertTrue('drive_type' in resp_dict)
        resp_dtype = resp_dict['drive_type']
        self.assertEqual(resp_dtype, _drive_type_view(dtype))

    def test_drive_types_api_delete(self):
        global last_param
        last_param = {}

        dtype_id = 123
        req = webob.Request.blank('/v1.1/zadr-drive_types/%d' % dtype_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['id']), str(dtype_id))

    def test_drive_types_show(self):
        global last_param
        last_param = {}

        dtype_id = 123
        req = webob.Request.blank('/v1.1/zadr-drive_types/%d' % dtype_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['id']), str(dtype_id))

        resp_dict = json.loads(resp.body)

        # Compare response
        self.assertTrue('drive_type' in resp_dict)
        resp_dtype = resp_dict['drive_type']
        exp_dtype = _get_default_drive_type()
        exp_dtype['id'] = dtype_id
        exp_dtype_view = _drive_type_view(exp_dtype)
        for k, v in exp_dtype_view.iteritems():
            self.assertEqual(str(resp_dtype[k]), str(exp_dtype_view[k]))

    def test_drive_types_show_invalid_id(self):
        global last_param
        last_param = {}

        dtype_id = 234
        req = webob.Request.blank('/v1.1/zadr-drive_types/%d' % dtype_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['id']), str(dtype_id))

    def test_drive_types_index(self):

        req = webob.Request.blank('/v1.1/zadr-drive_types')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('drive_types' in resp_dict)
        resp_dtypes = resp_dict['drive_types']
        self.assertEqual(len(resp_dtypes), 1)

        resp_dtype = resp_dtypes.pop()
        exp_dtype = _get_default_drive_type()
        exp_dtype['id'] = 123
        exp_dtype_view = _drive_type_view(exp_dtype)
        for k, v in exp_dtype_view.iteritems():
            self.assertEqual(str(resp_dtype[k]), str(exp_dtype_view[k]))
