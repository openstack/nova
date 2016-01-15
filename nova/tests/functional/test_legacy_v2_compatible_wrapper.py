# Copyright 2015 Intel Corporation.
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

from nova.api import openstack
from nova.api.openstack import compute
from nova.api.openstack import wsgi
from nova.tests.functional.api import client
from nova.tests.functional import test_servers
from nova.tests.unit import fake_network


class LegacyV2CompatibleTestBase(test_servers.ServersTestBase):
    api_major_version = 'v2'

    def setUp(self):
        super(LegacyV2CompatibleTestBase, self).setUp()
        self._check_api_endpoint('/v2', [compute.APIRouterV21,
                                         openstack.LegacyV2CompatibleWrapper])

    def test_request_with_microversion_headers(self):
        response = self.api.api_post('os-keypairs',
            {"keypair": {"name": "test"}},
            headers={wsgi.API_VERSION_REQUEST_HEADER: '2.100'})
        self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, response.headers)
        self.assertNotIn('Vary', response.headers)
        self.assertNotIn('type', response.body["keypair"])

    def test_request_without_addtional_properties_check(self):
        response = self.api.api_post('os-keypairs',
            {"keypair": {"name": "test", "foooooo": "barrrrrr"}},
            headers={wsgi.API_VERSION_REQUEST_HEADER: '2.100'})
        self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, response.headers)
        self.assertNotIn('Vary', response.headers)
        self.assertNotIn('type', response.body["keypair"])

    def test_request_with_pattern_properties_check(self):
        fake_network.set_stub_network_methods(self)
        server = self._build_minimal_create_server_request()
        post = {'server': server}
        created_server = self.api.post_server(post)
        self._wait_for_state_change(created_server, 'BUILD')
        response = self.api.post_server_metadata(created_server['id'],
                                                 {'a': 'b'})
        self.assertEqual(response, {'a': 'b'})

    def test_request_with_pattern_properties_with_avoid_metadata(self):
        fake_network.set_stub_network_methods(self)
        server = self._build_minimal_create_server_request()
        post = {'server': server}
        created_server = self.api.post_server(post)
        exc = self.assertRaises(client.OpenStackApiException,
                                self.api.post_server_metadata,
                                created_server['id'],
                                {'a': 'b',
                                 'x' * 300: 'y',
                                 'h' * 300: 'i'})
        self.assertEqual(exc.response.status_code, 400)
