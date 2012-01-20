# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from nova.api.openstack  import compute
from nova.api.openstack.compute import extensions
from nova.api.openstack import wsgi
import nova.db.api
import nova.rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


UUID = fakes.FAKE_UUID


class SchedulerHintsTestCase(test.TestCase):

    def setUp(self):
        super(SchedulerHintsTestCase, self).setUp()

        self.fake_instance = fakes.stub_instance(1, uuid=UUID)

        app = compute.APIRouter()
        app = extensions.ExtensionMiddleware(app)
        app = wsgi.LazySerializationMiddleware(app)
        self.app = app

    def test_create_server_without_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
               }}

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_with_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {'a': 'b'})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': {'a': 'b'},
        }

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_bad_hints(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': 'here',
        }

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)
