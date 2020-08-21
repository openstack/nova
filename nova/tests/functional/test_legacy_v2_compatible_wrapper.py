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
from nova.api.openstack import wsgi
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class LegacyV2CompatibleTestBase(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'

    def setUp(self):
        super(LegacyV2CompatibleTestBase, self).setUp()
        self._check_api_endpoint()

    def _check_api_endpoint(self):
        app = self.api_fixture.app().get((None, '/v2'))

        while getattr(app, 'application', False):
            if isinstance(
                app.application, openstack.LegacyV2CompatibleWrapper,
            ):
                break
            app = app.application
        else:
            raise Exception(
                'The LegacyV2CompatibleWrapper middleware is not configured.'
            )

    def test_request_with_microversion_headers(self):
        self.api.microversion = '2.100'
        response = self.api.api_post('os-keypairs',
            {"keypair": {"name": "test"}})
        self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, response.headers)
        self.assertNotIn(wsgi.LEGACY_API_VERSION_REQUEST_HEADER,
                         response.headers)
        self.assertNotIn('Vary', response.headers)
        self.assertNotIn('type', response.body["keypair"])

    def test_request_without_additional_properties_check(self):
        self.api.microversion = '2.100'
        response = self.api.api_post('os-keypairs',
            {"keypair": {"name": "test", "foooooo": "barrrrrr"}})
        self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, response.headers)
        self.assertNotIn(wsgi.LEGACY_API_VERSION_REQUEST_HEADER,
                         response.headers)
        self.assertNotIn('Vary', response.headers)
        self.assertNotIn('type', response.body["keypair"])

    def test_request_with_pattern_properties_check(self):
        server = self._build_server()
        post = {'server': server}
        created_server = self.api.post_server(post)
        self._wait_for_state_change(created_server, 'ACTIVE')
        response = self.api.post_server_metadata(created_server['id'],
                                                 {'a': 'b'})
        self.assertEqual(response, {'a': 'b'})

    def test_request_with_pattern_properties_with_avoid_metadata(self):
        server = self._build_server()
        post = {'server': server}
        created_server = self.api.post_server(post)
        exc = self.assertRaises(client.OpenStackApiException,
                                self.api.post_server_metadata,
                                created_server['id'],
                                {'a': 'b',
                                 'x' * 300: 'y',
                                 'h' * 300: 'i'})
        self.assertEqual(exc.response.status_code, 400)
