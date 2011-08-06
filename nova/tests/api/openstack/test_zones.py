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


import stubout
import webob
import json

import nova.db
from nova import context
from nova import crypto
from nova import flags
from nova import test
from nova.api.openstack import zones
from nova.tests.api.openstack import fakes
from nova.scheduler import api


FLAGS = flags.FLAGS


def zone_get(context, zone_id):
    return dict(id=1, api_url='http://example.com', username='bob',
                password='xxx', weight_scale=1.0, weight_offset=0.0)


def zone_create(context, values):
    zone = dict(id=1)
    zone.update(values)
    return zone


def zone_update(context, zone_id, values):
    zone = dict(id=zone_id, api_url='http://example.com', username='bob',
                password='xxx')
    zone.update(values)
    return zone


def zone_delete(context, zone_id):
    pass


def zone_get_all_scheduler(*args):
    return [
        dict(id=1, api_url='http://example.com', username='bob',
                 password='xxx', weight_scale=1.0, weight_offset=0.0),
        dict(id=2, api_url='http://example.org', username='alice',
                 password='qwerty', weight_scale=1.0, weight_offset=0.0),
    ]


def zone_get_all_scheduler_empty(*args):
    return []


def zone_get_all_db(context):
    return [
        dict(id=1, api_url='http://example.com', username='bob',
                 password='xxx', weight_scale=1.0, weight_offset=0.0),
        dict(id=2, api_url='http://example.org', username='alice',
                 password='qwerty', weight_scale=1.0, weight_offset=0.0),
    ]


def zone_capabilities(method, context):
    return dict()


GLOBAL_BUILD_PLAN = [
        dict(name='host1', weight=10, ip='10.0.0.1', zone='zone1'),
        dict(name='host2', weight=9, ip='10.0.0.2', zone='zone2'),
        dict(name='host3', weight=8, ip='10.0.0.3', zone='zone3'),
        dict(name='host4', weight=7, ip='10.0.0.4', zone='zone4'),
     ]


def zone_select(context, specs):
    return GLOBAL_BUILD_PLAN


class ZonesTest(test.TestCase):
    def setUp(self):
        super(ZonesTest, self).setUp()
        self.flags(verbose=True, allow_admin_api=True)
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)

        self.stubs.Set(nova.db, 'zone_get', zone_get)
        self.stubs.Set(nova.db, 'zone_update', zone_update)
        self.stubs.Set(nova.db, 'zone_create', zone_create)
        self.stubs.Set(nova.db, 'zone_delete', zone_delete)

    def test_get_zone_list_scheduler(self):
        self.stubs.Set(api, '_call_scheduler', zone_get_all_scheduler)
        req = webob.Request.blank('/v1.0/zones')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['zones']), 2)

    def test_get_zone_list_db(self):
        self.stubs.Set(api, '_call_scheduler', zone_get_all_scheduler_empty)
        self.stubs.Set(nova.db, 'zone_get_all', zone_get_all_db)
        req = webob.Request.blank('/v1.0/zones')
        req.headers["Content-Type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(len(res_dict['zones']), 2)

    def test_get_zone_by_id(self):
        req = webob.Request.blank('/v1.0/zones/1')
        req.headers["Content-Type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['zone']['id'], 1)
        self.assertEqual(res_dict['zone']['api_url'], 'http://example.com')
        self.assertFalse('password' in res_dict['zone'])

    def test_zone_delete(self):
        req = webob.Request.blank('/v1.0/zones/1')
        req.headers["Content-Type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)

    def test_zone_create(self):
        body = dict(zone=dict(api_url='http://example.com', username='fred',
                        password='fubar'))
        req = webob.Request.blank('/v1.0/zones')
        req.headers["Content-Type"] = "application/json"
        req.method = 'POST'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['zone']['id'], 1)
        self.assertEqual(res_dict['zone']['api_url'], 'http://example.com')
        self.assertFalse('username' in res_dict['zone'])

    def test_zone_update(self):
        body = dict(zone=dict(username='zeb', password='sneaky'))
        req = webob.Request.blank('/v1.0/zones/1')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['zone']['id'], 1)
        self.assertEqual(res_dict['zone']['api_url'], 'http://example.com')
        self.assertFalse('username' in res_dict['zone'])

    def test_zone_info(self):
        caps = ['cap1=a;b', 'cap2=c;d']
        self.flags(zone_name='darksecret', zone_capabilities=caps)
        self.stubs.Set(api, '_call_scheduler', zone_capabilities)

        body = dict(zone=dict(username='zeb', password='sneaky'))
        req = webob.Request.blank('/v1.0/zones/info')

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['zone']['name'], 'darksecret')
        self.assertEqual(res_dict['zone']['cap1'], 'a;b')
        self.assertEqual(res_dict['zone']['cap2'], 'c;d')

    def test_zone_select(self):
        key = 'c286696d887c9aa0611bbb3e2025a45a'
        self.flags(build_plan_encryption_key=key)
        self.stubs.Set(api, 'select', zone_select)

        req = webob.Request.blank('/v1.0/zones/select')
        req.method = 'POST'
        req.headers["Content-Type"] = "application/json"
        # Select queries end up being JSON encoded twice.
        # Once to a string and again as an HTTP POST Body
        req.body = json.dumps(json.dumps({}))

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 200)

        self.assertTrue('weights' in res_dict)

        for item in res_dict['weights']:
            blob = item['blob']
            decrypt = crypto.decryptor(FLAGS.build_plan_encryption_key)
            secret_item = json.loads(decrypt(blob))
            found = False
            for original_item in GLOBAL_BUILD_PLAN:
                if original_item['name'] != secret_item['name']:
                    continue
                found = True
                for key in ('weight', 'ip', 'zone'):
                    self.assertEqual(secret_item[key], original_item[key])

            self.assertTrue(found)
            self.assertEqual(len(item), 2)
            self.assertTrue('weight' in item)
