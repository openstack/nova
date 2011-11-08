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

import datetime
import json
import webob

from nova import compute
from nova import exception
from nova import flags
from nova import image
from nova import test
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS
FLAGS.verbose = True

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

FAKE_NETWORKS = [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12'),
                 ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '10.0.2.12')]

DUPLICATE_NETWORKS = [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12'),
                      ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12')]

INVALID_NETWORKS = [('invalid', 'invalid-ip-address')]

INSTANCE = {
             "id": 1,
             "name": "fake",
             "display_name": "test_server",
             "uuid": FAKE_UUID,
             "user_id": 'fake_user_id',
             "task_state": "kayaking",
             "vm_state": "slightly crunchy",
             "power_state": "empowered",
             "tenant_id": 'fake_tenant_id',
             "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
             "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
             "security_groups": [{"id": 1, "name": "test"}],
             "progress": 0,
             "image_ref": 'http://foo.com/123',
             "fixed_ips": [],
             "instance_type": {"flavorid": '124'},
        }


class ExtendedStatusTest(test.TestCase):

    def setUp(self):
        super(ExtendedStatusTest, self).setUp()
        self.uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
        self.url = '/v1.1/openstack/servers/%s' % self.uuid
        fakes.stub_out_nw_api(self.stubs)

    def test_extended_status_with_admin(self):
        def fake_compute_get(*args, **kwargs):
            return INSTANCE

        self.flags(allow_admin_api=True)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        body = json.loads(res.body)
        self.assertEqual(body['server']['OS-EXT-STS:vm_state'],
                'slightly crunchy')
        self.assertEqual(body['server']['OS-EXT-STS:power_state'], 'empowered')
        self.assertEqual(body['server']['OS-EXT-STS:task_state'], 'kayaking')

    def test_extended_status_no_admin(self):
        def fake_compute_get(*args, **kwargs):
            return INSTANCE

        self.flags(allow_admin_api=False)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        body = json.loads(res.body)
        self.assertEqual(body['server'].get('OS-EXT-STS:vm_state'), None)
        self.assertEqual(body['server'].get('OS-EXT-STS:power_state'), None)
        self.assertEqual(body['server'].get('OS-EXT-STS:task_state'), None)

    def test_extended_status_no_instance_fails(self):
        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound()

        self.flags(allow_admin_api=True)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)
