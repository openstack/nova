# Copyright 2012 IBM Corp.
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

from nova.api.openstack.compute import cloudpipe as clup_v21
from nova import test
from nova.tests.unit.api.openstack import fakes


class CloudpipeUpdateTestV21(test.NoDBTestCase):

    def setUp(self):
        super(CloudpipeUpdateTestV21, self).setUp()
        self.controller = clup_v21.CloudpipeController()
        self.req = fakes.HTTPRequest.blank('')

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def test_cloudpipe_configure_project(self):
        body = {"configure_project": {"vpn_ip": "1.2.3.4", "vpn_port": 222}}
        self.assertRaises(webob.exc.HTTPGone, self.controller.update,
                          self.req, 'configure-project', body=body)
