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

"""Tests for Direct API."""

import json

import webob

from nova import compute
from nova import context
from nova import exception
from nova import network
from nova import test
from nova import volume
from nova import utils
from nova.api import direct
from nova.tests import test_cloud


class ArbitraryObject(object):
    pass


class FakeService(object):
    def echo(self, context, data):
        return {'data': data}

    def context(self, context):
        return {'user': context.user_id,
                'project': context.project_id}

    def invalid_return(self, context):
        return ArbitraryObject()


class DirectTestCase(test.TestCase):
    def setUp(self):
        super(DirectTestCase, self).setUp()
        direct.register_service('fake', FakeService())
        self.router = direct.PostParamsMiddleware(
                direct.JsonParamsMiddleware(
                        direct.Router()))
        self.auth_router = direct.DelegatedAuthMiddleware(self.router)
        self.context = context.RequestContext('user1', 'proj1')

    def tearDown(self):
        direct.ROUTES = {}
        super(DirectTestCase, self).tearDown()

    def test_delegated_auth(self):
        req = webob.Request.blank('/fake/context')
        req.headers['X-OpenStack-User'] = 'user1'
        req.headers['X-OpenStack-Project'] = 'proj1'
        resp = req.get_response(self.auth_router)
        self.assertEqual(resp.status_int, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['user'], 'user1')
        self.assertEqual(data['project'], 'proj1')

    def test_json_params(self):
        req = webob.Request.blank('/fake/echo')
        req.environ['openstack.context'] = self.context
        req.method = 'POST'
        req.body = 'json=%s' % json.dumps({'data': 'foo'})
        resp = req.get_response(self.router)
        self.assertEqual(resp.status_int, 200)
        resp_parsed = json.loads(resp.body)
        self.assertEqual(resp_parsed['data'], 'foo')

    def test_post_params(self):
        req = webob.Request.blank('/fake/echo')
        req.environ['openstack.context'] = self.context
        req.method = 'POST'
        req.body = 'data=foo'
        resp = req.get_response(self.router)
        self.assertEqual(resp.status_int, 200)
        resp_parsed = json.loads(resp.body)
        self.assertEqual(resp_parsed['data'], 'foo')

    def test_invalid(self):
        req = webob.Request.blank('/fake/invalid_return')
        req.environ['openstack.context'] = self.context
        req.method = 'POST'
        self.assertRaises(exception.Error, req.get_response, self.router)

    def test_proxy(self):
        proxy = direct.Proxy(self.router)
        rv = proxy.fake.echo(self.context, data='baz')
        self.assertEqual(rv['data'], 'baz')


# NOTE(jkoelker): This fails using the EC2 api
#class DirectCloudTestCase(test_cloud.CloudTestCase):
#    def setUp(self):
#        super(DirectCloudTestCase, self).setUp()
#        compute_handle = compute.API(image_service=self.cloud.image_service)
#        volume_handle = volume.API()
#        network_handle = network.API()
#        direct.register_service('compute', compute_handle)
#        direct.register_service('volume', volume_handle)
#        direct.register_service('network', network_handle)
#
#        self.router = direct.JsonParamsMiddleware(direct.Router())
#        proxy = direct.Proxy(self.router)
#        self.cloud.compute_api = proxy.compute
#        self.cloud.volume_api = proxy.volume
#        self.cloud.network_api = proxy.network
#        compute_handle.volume_api = proxy.volume
#        compute_handle.network_api = proxy.network
#
#    def tearDown(self):
#        super(DirectCloudTestCase, self).tearDown()
#        direct.ROUTES = {}
