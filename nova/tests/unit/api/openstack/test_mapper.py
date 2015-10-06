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

import webob

from nova.api import openstack as openstack_api
from nova import test
from nova.tests.unit.api.openstack import fakes


class MapperTest(test.NoDBTestCase):
    def test_resource_project_prefix(self):
        class Controller(object):
            def index(self, req):
                return 'foo'

        app = fakes.TestRouter(Controller(),
                               openstack_api.ProjectMapper())
        req = webob.Request.blank('/1234/tests')
        resp = req.get_response(app)
        self.assertEqual(b'foo', resp.body)
        self.assertEqual(resp.status_int, 200)

    def test_resource_no_project_prefix(self):
        class Controller(object):
            def index(self, req):
                return 'foo'

        app = fakes.TestRouter(Controller(),
                               openstack_api.PlainMapper())
        req = webob.Request.blank('/tests')
        resp = req.get_response(app)
        self.assertEqual(b'foo', resp.body)
        self.assertEqual(resp.status_int, 200)
