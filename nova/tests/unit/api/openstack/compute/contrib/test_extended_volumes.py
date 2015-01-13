# Copyright 2013 OpenStack Foundation
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

from oslo.serialization import jsonutils
import webob

from nova import compute
from nova import db
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID1)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_all(*args, **kwargs):
    db_list = [fakes.stub_instance(1), fakes.stub_instance(2)]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


def fake_bdms_get_all_by_instance(*args, **kwargs):
    return [fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': UUID1, 'source_type': 'volume',
             'destination_type': 'volume', 'id': 1}),
            fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': UUID2, 'source_type': 'volume',
             'destination_type': 'volume', 'id': 2})]


class ExtendedVolumesTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-extended-volumes:'

    def setUp(self):
        super(ExtendedVolumesTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Extended_volumes'])
        return_server = fakes.fake_instance_get()
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=('servers',)))
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID1
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        actual = server.get('%svolumes_attached' % self.prefix)
        self.assertEqual(exp_volumes, actual)

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        for i, server in enumerate(self._get_servers(res.body)):
            actual = server.get('%svolumes_attached' % self.prefix)
            self.assertEqual(exp_volumes, actual)
