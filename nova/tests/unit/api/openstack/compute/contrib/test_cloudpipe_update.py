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

from nova.api.openstack.compute.contrib import cloudpipe_update as clup_v2
from nova.api.openstack.compute.plugins.v3 import cloudpipe as clup_v21
from nova import db
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network


fake_networks = [fake_network.fake_network(1),
                 fake_network.fake_network(2)]


def fake_project_get_networks(context, project_id, associate=True):
    return fake_networks


def fake_network_update(context, network_id, values):
    for network in fake_networks:
        if network['id'] == network_id:
            for key in values:
                network[key] = values[key]


class CloudpipeUpdateTestV21(test.NoDBTestCase):
    bad_request = exception.ValidationError

    def setUp(self):
        super(CloudpipeUpdateTestV21, self).setUp()
        self.stubs.Set(db, "project_get_networks", fake_project_get_networks)
        self.stubs.Set(db, "network_update", fake_network_update)
        self._setup()

    def _setup(self):
        self.controller = clup_v21.CloudpipeController()

    def _check_status(self, expected_status, res, controller_methord):
        self.assertEqual(expected_status, controller_methord.wsgi_code)

    def test_cloudpipe_configure_project(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"configure_project": {"vpn_ip": "1.2.3.4", "vpn_port": 222}}
        result = self.controller.update(req, 'configure-project',
                                               body=body)
        self._check_status(202, result, self.controller.update)
        self.assertEqual(fake_networks[0]['vpn_public_address'], "1.2.3.4")
        self.assertEqual(fake_networks[0]['vpn_public_port'], 222)

    def test_cloudpipe_configure_project_bad_url(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-projectx')
        body = {"configure_project": {"vpn_ip": "1.2.3.4", "vpn_port": 222}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req,
                          'configure-projectx', body=body)

    def test_cloudpipe_configure_project_bad_data(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"configure_project": {"vpn_ipxx": "1.2.3.4", "vpn_port": 222}}
        self.assertRaises(self.bad_request,
                          self.controller.update, req,
                          'configure-project', body=body)

    def test_cloudpipe_configure_project_bad_vpn_port(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"configure_project": {"vpn_ipxx": "1.2.3.4",
                                      "vpn_port": "foo"}}
        self.assertRaises(self.bad_request,
                          self.controller.update, req,
                          'configure-project', body=body)

    def test_cloudpipe_configure_project_vpn_port_with_empty_string(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-cloudpipe/configure-project')
        body = {"configure_project": {"vpn_ipxx": "1.2.3.4",
                                      "vpn_port": ""}}
        self.assertRaises(self.bad_request,
                          self.controller.update, req,
                          'configure-project', body=body)


class CloudpipeUpdateTestV2(CloudpipeUpdateTestV21):
    bad_request = webob.exc.HTTPBadRequest

    def _setup(self):
        self.controller = clup_v2.CloudpipeUpdateController()

    def _check_status(self, expected_status, res, controller_methord):
        self.assertEqual(expected_status, res.status_int)
