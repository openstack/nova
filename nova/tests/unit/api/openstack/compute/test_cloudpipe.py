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

import uuid as uuid_lib

from webob import exc

from nova.api.openstack.compute import cloudpipe as cloudpipe_v21
from nova import test
from nova.tests.unit.api.openstack import fakes


project_id = str(uuid_lib.uuid4().hex)


class CloudpipeTestV21(test.NoDBTestCase):
    cloudpipe = cloudpipe_v21
    url = '/v2/fake/os-cloudpipe'

    def setUp(self):
        super(CloudpipeTestV21, self).setUp()
        self.controller = self.cloudpipe.CloudpipeController()
        self.req = fakes.HTTPRequest.blank('')

    def test_cloudpipe_list(self):
        self.assertRaises(exc.HTTPGone, self.controller.index, self.req)

    def test_cloudpipe_create(self):
        body = {'cloudpipe': {'project_id': project_id}}
        self.assertRaises(exc.HTTPGone, self.controller.create,
                          self.req, body=body)

    def test_cloudpipe_configure_project(self):
        body = {"configure_project": {"vpn_ip": "1.2.3.4", "vpn_port": 222}}
        self.assertRaises(exc.HTTPGone, self.controller.update,
                          self.req, 'configure-project', body=body)
