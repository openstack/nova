# Copyright 2011 OpenStack Foundation
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

from oslo_config import cfg
from oslo_serialization import jsonutils

from nova.api.openstack import compute
from nova import test
from nova.tests.unit.api.openstack import fakes


UUID = fakes.FAKE_UUID


CONF = cfg.CONF


class SchedulerHintsTestCaseV21(test.TestCase):

    def setUp(self):
        super(SchedulerHintsTestCaseV21, self).setUp()
        self.fake_instance = fakes.stub_instance_obj(None, id=1, uuid=UUID)
        self._set_up_router()

    def _set_up_router(self):
        self.app = compute.APIRouterV21()

    def _get_request(self):
        return fakes.HTTPRequest.blank('/fake/servers')

    def test_create_server_without_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {})
            return ([self.fake_instance], '')

        self.stub_out('nova.compute.api.API.create', fake_create)

        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def _test_create_server_with_hint(self, hint):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], hint)
            return ([self.fake_instance], '')

        self.stub_out('nova.compute.api.API.create', fake_create)

        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': hint,
        }

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_with_group_hint(self):
        self._test_create_server_with_hint({'group': UUID})

    def test_create_server_with_non_uuid_group_hint(self):
        self._create_server_with_scheduler_hints_bad_request(
                {'group': 'non-uuid'})

    def test_create_server_with_different_host_hint(self):
        self._test_create_server_with_hint(
            {'different_host': '9c47bf55-e9d8-42da-94ab-7f9e80cd1857'})

        self._test_create_server_with_hint(
            {'different_host': ['9c47bf55-e9d8-42da-94ab-7f9e80cd1857',
                                '82412fa6-0365-43a9-95e4-d8b20e00c0de']})

    def _create_server_with_scheduler_hints_bad_request(self, param):
        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': param,
        }
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)

    def test_create_server_bad_hints_non_dict(self):
        self._create_server_with_scheduler_hints_bad_request('non-dict')

    def test_create_server_bad_hints_long_group(self):
        param = {'group': 'a' * 256}
        self._create_server_with_scheduler_hints_bad_request(param)

    def test_create_server_with_bad_different_host_hint(self):
        param = {'different_host': 'non-server-id'}
        self._create_server_with_scheduler_hints_bad_request(param)

        param = {'different_host': ['non-server-id01', 'non-server-id02']}
        self._create_server_with_scheduler_hints_bad_request(param)
