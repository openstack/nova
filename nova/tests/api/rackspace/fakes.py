# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
import random
import string

import webob
import webob.dec

from nova import auth
from nova import utils
from nova import flags
from nova import exception as exc
import nova.api.rackspace.auth
from nova.image import service
from nova.wsgi import Router


FLAGS = flags.FLAGS


class Context(object): 
    pass


class FakeRouter(Router):
    def __init__(self):
        pass

    @webob.dec.wsgify
    def __call__(self, req):
        res = webob.Response()
        res.status = '200'
        res.headers['X-Test-Success'] = 'True'
        return res


def fake_auth_init(self):
    self.db = FakeAuthDatabase()
    self.context = Context()
    self.auth = FakeAuthManager()
    self.host = 'foo'


@webob.dec.wsgify
def fake_wsgi(self, req):
    req.environ['nova.context'] = dict(user=dict(id=1))
    if req.body:
        req.environ['inst_dict'] = json.loads(req.body)
    return self.application


def stub_out_key_pair_funcs(stubs):
    def key_pair(context, user_id):
        return [dict(name='key', public_key='public_key')]
    stubs.Set(nova.db.api, 'key_pair_get_all_by_user',
        key_pair)


def stub_out_image_service(stubs):
    def fake_image_show(meh, id):
        return dict(kernelId=1, ramdiskId=1)

    stubs.Set(nova.image.service.LocalImageService, 'show', fake_image_show)

def stub_out_auth(stubs):
    def fake_auth_init(self, app):
        self.application = app
    
    stubs.Set(nova.api.rackspace.AuthMiddleware, 
        '__init__', fake_auth_init) 
    stubs.Set(nova.api.rackspace.AuthMiddleware, 
        '__call__', fake_wsgi) 


def stub_out_rate_limiting(stubs):
    def fake_rate_init(self, app):
        super(nova.api.rackspace.RateLimitingMiddleware, self).__init__(app)
        self.application = app

    stubs.Set(nova.api.rackspace.RateLimitingMiddleware,
        '__init__', fake_rate_init)

    stubs.Set(nova.api.rackspace.RateLimitingMiddleware,
        '__call__', fake_wsgi)


def stub_out_networking(stubs):
    def get_my_ip():
        return '127.0.0.1' 
    stubs.Set(nova.utils, 'get_my_ip', get_my_ip)
    FLAGS.FAKE_subdomain = 'rs'


def stub_out_glance(stubs):

    class FakeParallaxClient:

        def __init__(self):
            self.fixtures = {}

        def fake_get_images(self):
            return self.fixtures

        def fake_get_image_metadata(self, image_id):
            for k, f in self.fixtures.iteritems():
                if k == image_id:
                    return f
            return None

        def fake_add_image_metadata(self, image_data):
            id = ''.join(random.choice(string.letters) for _ in range(20))
            image_data['id'] = id
            self.fixtures[id] = image_data
            return id

        def fake_update_image_metadata(self, image_id, image_data):
            
            if image_id not in self.fixtures.keys():
                raise exc.NotFound

            self.fixtures[image_id].update(image_data)

        def fake_delete_image_metadata(self, image_id):
            
            if image_id not in self.fixtures.keys():
                raise exc.NotFound

            del self.fixtures[image_id]

        def fake_delete_all(self):
            self.fixtures = {}

    fake_parallax_client = FakeParallaxClient()
    stubs.Set(nova.image.service.ParallaxClient, 'get_images',
              fake_parallax_client.fake_get_images)
    stubs.Set(nova.image.service.ParallaxClient, 'get_image_metadata',
              fake_parallax_client.fake_get_image_metadata)
    stubs.Set(nova.image.service.ParallaxClient, 'add_image_metadata',
              fake_parallax_client.fake_add_image_metadata)
    stubs.Set(nova.image.service.ParallaxClient, 'update_image_metadata',
              fake_parallax_client.fake_update_image_metadata)
    stubs.Set(nova.image.service.ParallaxClient, 'delete_image_metadata',
              fake_parallax_client.fake_delete_image_metadata)
    stubs.Set(nova.image.service.GlanceImageService, 'delete_all',
              fake_parallax_client.fake_delete_all)


class FakeAuthDatabase(object):
    data = {}

    @staticmethod
    def auth_get_token(context, token_hash):
        return FakeAuthDatabase.data.get(token_hash, None)

    @staticmethod
    def auth_create_token(context, token):
        token['created_at'] = datetime.datetime.now()
        FakeAuthDatabase.data[token['token_hash']] = token

    @staticmethod
    def auth_destroy_token(context, token):
        if FakeAuthDatabase.data.has_key(token['token_hash']):
            del FakeAuthDatabase.data['token_hash']


class FakeAuthManager(object):
    auth_data = {}

    def add_user(self, key, user):        
        FakeAuthManager.auth_data[key] = user

    def get_user(self, uid):
        for k, v in FakeAuthManager.auth_data.iteritems():
            if v['uid'] == uid:
                return v
        return None

    def get_user_from_access_key(self, key):
        return FakeAuthManager.auth_data.get(key, None)


class FakeRateLimiter(object):
    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        return self.application
