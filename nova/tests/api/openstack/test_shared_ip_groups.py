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

import webob

from nova import test
from nova.tests.api.openstack import fakes


class SharedIpGroupsTest(test.TestCase):
    def test_get_shared_ip_groups(self):
        req = webob.Request.blank('/v1.0/shared_ip_groups')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_create_shared_ip_group(self):
        req = webob.Request.blank('/v1.0/shared_ip_groups')
        req.method = 'POST'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_update_shared_ip_group(self):
        req = webob.Request.blank('/v1.0/shared_ip_groups/12')
        req.method = 'PUT'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_delete_shared_ip_group(self):
        req = webob.Request.blank('/v1.0/shared_ip_groups/12')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_deprecated_v11(self):
        req = webob.Request.blank('/v1.1/shared_ip_groups')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)
