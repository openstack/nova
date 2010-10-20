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
import nova.api.openstack.auth
from nova.image import service
from nova.image.services import glance
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
    
    stubs.Set(nova.api.openstack.AuthMiddleware, 
        '__init__', fake_auth_init) 
    stubs.Set(nova.api.openstack.AuthMiddleware, 
        '__call__', fake_wsgi) 


def stub_out_rate_limiting(stubs):
    def fake_rate_init(self, app):
        super(nova.api.openstack.RateLimitingMiddleware, self).__init__(app)
        self.application = app

    stubs.Set(nova.api.openstack.RateLimitingMiddleware,
        '__init__', fake_rate_init)

    stubs.Set(nova.api.openstack.RateLimitingMiddleware,
        '__call__', fake_wsgi)


def stub_out_networking(stubs):
    def get_my_ip():
        return '127.0.0.1' 
    stubs.Set(nova.utils, 'get_my_ip', get_my_ip)
    FLAGS.FAKE_subdomain = 'api'


def stub_out_glance(stubs, initial_fixtures=[]):

    class FakeParallaxClient:

        def __init__(self, initial_fixtures):
            self.fixtures = initial_fixtures

        def fake_get_image_index(self):
            return [dict(id=f['id'], name=f['name'])
                    for f in self.fixtures]

        def fake_get_image_details(self):
            return self.fixtures

        def fake_get_image_metadata(self, image_id):
            for f in self.fixtures:
                if f['id'] == image_id:
                    return f
            return None

        def fake_add_image_metadata(self, image_data):
            id = ''.join(random.choice(string.letters) for _ in range(20))
            image_data['id'] = id
            self.fixtures.append(image_data)
            return id

        def fake_update_image_metadata(self, image_id, image_data):
            
            f = self.fake_get_image_metadata(image_id)
            if not f:
                raise exc.NotFound

            f.update(image_data)

        def fake_delete_image_metadata(self, image_id):
            
            f = self.fake_get_image_metadata(image_id)
            if not f:
                raise exc.NotFound

            self.fixtures.remove(f)

        def fake_delete_all(self):
            self.fixtures = []

    fake_parallax_client = FakeParallaxClient(initial_fixtures)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'get_image_index',
              fake_parallax_client.fake_get_image_index)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'get_image_details',
              fake_parallax_client.fake_get_image_details)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'get_image_metadata',
              fake_parallax_client.fake_get_image_metadata)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'add_image_metadata',
              fake_parallax_client.fake_add_image_metadata)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'update_image_metadata',
              fake_parallax_client.fake_update_image_metadata)
    stubs.Set(nova.image.services.glance.ParallaxClient, 'delete_image_metadata',
              fake_parallax_client.fake_delete_image_metadata)
    stubs.Set(nova.image.services.glance.GlanceImageService, 'delete_all',
              fake_parallax_client.fake_delete_all)


class FakeToken(object):
    def __init__(self, **kwargs):
        for k,v in kwargs.iteritems():
            setattr(self, k, v)


class FakeAuthDatabase(object):
    data = {}

    @staticmethod
    def auth_get_token(context, token_hash):
        return FakeAuthDatabase.data.get(token_hash, None)

    @staticmethod
    def auth_create_token(context, token):
        fake_token = FakeToken(created_at=datetime.datetime.now(), **token)
        FakeAuthDatabase.data[fake_token.token_hash] = fake_token
        return fake_token

    @staticmethod
    def auth_destroy_token(context, token):
        if token.token_hash in FakeAuthDatabase.data:
            del FakeAuthDatabase.data['token_hash']


class FakeAuthManager(object):
    auth_data = {}

    def add_user(self, key, user):        
        FakeAuthManager.auth_data[key] = user

    def get_user(self, uid):
        for k, v in FakeAuthManager.auth_data.iteritems():
            if v.id == uid:
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
