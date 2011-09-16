# Copyright 2011 Josh Durgin
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

import nova
from nova import context
from nova import test
from nova.api.openstack.contrib.volumes import BootFromVolumeController
from nova.compute import instance_types
from nova.tests.api.openstack import fakes
from nova.tests.api.openstack.test_servers import fake_gen_uuid


def fake_compute_api_create(cls, context, instance_type, image_href, **kwargs):
    inst_type = instance_types.get_instance_type_by_flavor_id(2)
    return [{'id': 1,
             'display_name': 'test_server',
             'uuid': fake_gen_uuid(),
             'instance_type': dict(inst_type),
             'access_ip_v4': '1.2.3.4',
             'access_ip_v6': 'fead::1234',
             'image_ref': 3,
             'user_id': 'fake',
             'project_id': 'fake',
             'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
             'updated_at': datetime.datetime(2010, 11, 11, 11, 0, 0),
             }]


class BootFromVolumeTest(test.TestCase):

    def setUp(self):
        super(BootFromVolumeTest, self).setUp()
        self.stubs.Set(nova.compute.API, 'create', fake_compute_api_create)

    def test_create_root_volume(self):
        body = dict(server=dict(
                name='test_server', imageRef=3,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping=[dict(
                        volume_id=1,
                        device_name='/dev/vda',
                        virtual='root',
                        delete_on_termination=False,
                        )]
                ))
        req = webob.Request.blank('/v1.1/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        server = json.loads(res.body)['server']
        self.assertEqual(1, server['id'])
        self.assertEqual(2, int(server['flavor']['id']))
        self.assertEqual(u'test_server', server['name'])
        self.assertEqual(3, int(server['image']['id']))
        self.assertEqual(16, len(server['adminPass']))
