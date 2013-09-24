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

from nova.api.openstack.compute.contrib import cloudpipe_update
from nova import db
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_network


fake_networks = [fake_network.fake_network(1),
                 fake_network.fake_network(2)]


def fake_project_get_networks(context, project_id, associate=True):
    return fake_networks


def fake_network_update(context, network_id, values):
    for network in fake_networks:
        if network['id'] == network_id:
            for key in values:
                network[key] = values[key]


class CloudpipeUpdateTest(test.NoDBTestCase):

    def setUp(self):
        super(CloudpipeUpdateTest, self).setUp()
        self.controller = cloudpipe_update.CloudpipeUpdateController()
        self.stubs.Set(db, "project_get_networks", fake_project_get_networks)
        self.stubs.Set(db, "network_update", fake_network_update)

    def test_cloudpipe_configure_project(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"configure_project": {"vpn_ip": "1.2.3.4", "vpn_port": 222}}
        result = self.controller.update(req, 'configure-project',
                                               body=body)
        self.assertEqual('202 Accepted', result.status)
        self.assertEqual(fake_networks[0]['vpn_public_address'], "1.2.3.4")
        self.assertEqual(fake_networks[0]['vpn_public_port'], 222)

    def test_cloudpipe_configure_project_bad_url(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-projectx')
        body = {"vpn_ip": "1.2.3.4", "vpn_port": 222}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req,
                          'configure-projectx', body)

    def test_cloudpipe_configure_project_bad_data(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"vpn_ipxx": "1.2.3.4", "vpn_port": 222}
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update, req,
                          'configure-project', body)
