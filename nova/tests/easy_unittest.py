# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for Easy API."""

import json
import logging

import webob

from nova import context
from nova import exception
from nova import test
from nova import utils
from nova.api import easy
from nova.compute import api as compute_api
from nova.tests import cloud_unittest


class FakeService(object):
    def echo(self, context, data):
        return {'data': data}

    def context(self, context):
        return {'user': context.user_id,
                'project': context.project_id}


class EasyTestCase(test.TestCase):
    def setUp(self):
        super(EasyTestCase, self).setUp()
        easy.register_service('fake', FakeService())
        self.router = easy.ReqParamsMiddleware(
                easy.JsonParamsMiddleware(
                        easy.SundayMorning()))
        self.auth_router = easy.DelegatedAuthMiddleware(self.router)
        self.context = context.RequestContext('user1', 'proj1')

    def tearDown(self):
        easy.EASY_ROUTES = {}

    def test_delegated_auth(self):
        req = webob.Request.blank('/fake/context')
        req.headers['X-OpenStack-User'] = 'user1'
        req.headers['X-OpenStack-Project'] = 'proj1'
        resp = req.get_response(self.auth_router)
        data = json.loads(resp.body)
        self.assertEqual(data['user'], 'user1')
        self.assertEqual(data['project'], 'proj1')

    def test_json_params(self):
        req = webob.Request.blank('/fake/echo')
        req.environ['openstack.context'] = self.context
        req.method = 'POST'
        req.body = 'json=%s' % json.dumps({'data': 'foo'})
        resp = req.get_response(self.router)
        resp_parsed = json.loads(resp.body)
        self.assertEqual(resp_parsed['data'], 'foo')

    def test_req_params(self):
        req = webob.Request.blank('/fake/echo')
        req.environ['openstack.context'] = self.context
        req.method = 'POST'
        req.body = 'data=foo'
        resp = req.get_response(self.router)
        resp_parsed = json.loads(resp.body)
        self.assertEqual(resp_parsed['data'], 'foo')

    def test_proxy(self):
        proxy = easy.Proxy(self.router)
        rv = proxy.fake.echo(self.context, data='baz')
        self.assertEqual(rv['data'], 'baz')


class EasyCloudTestCase(cloud_unittest.CloudTestCase):
    def setUp(self):
        super(EasyCloudTestCase, self).setUp()
        compute_handle = compute_api.ComputeAPI(self.cloud.network_manager,
                                                self.cloud.image_service)
        easy.register_service('compute', compute_handle)
        self.router = easy.JsonParamsMiddleware(easy.SundayMorning())
        proxy = easy.Proxy(self.router)
        self.cloud.compute_api = proxy.compute

    def tearDown(self):
        super(EasyCloudTestCase, self).tearDown()
        easy.EASY_ROUTES = {}
