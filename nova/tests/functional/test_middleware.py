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
"""
Tests to assert that various incorporated middleware works as expected.
"""

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import api_sample_base


class TestCORSMiddleware(api_sample_base.ApiSampleTestBaseV21):
    '''Provide a basic smoke test to ensure CORS middleware is active.

    The tests below provide minimal confirmation that the CORS middleware
    is active, and may be configured. For comprehensive tests, please consult
    the test suite in oslo_middleware.
    '''

    def setUp(self):
        # Here we monkeypatch GroupAttr.__getattr__, necessary because the
        # paste.ini method of initializing this middleware creates its own
        # ConfigOpts instance, bypassing the regular config fixture.
        # Mocking also does not work, as accessing an attribute on a mock
        # object will return a MagicMock instance, which will fail
        # configuration type checks.
        def _mock_getattr(instance, key):
            if key != 'allowed_origin':
                return self._original_call_method(instance, key)
            return "http://valid.example.com"

        self._original_call_method = cfg.ConfigOpts.GroupAttr.__getattr__
        cfg.ConfigOpts.GroupAttr.__getattr__ = _mock_getattr

        # With the project_id in the URL, we get the 300 'multiple choices'
        # response from nova.api.openstack.compute.versions.Versions.
        self.exp_version_status = 300 if self.USE_PROJECT_ID else 200

        # Initialize the application after all the config overrides are in
        # place.
        super(TestCORSMiddleware, self).setUp()

    def tearDown(self):
        super(TestCORSMiddleware, self).tearDown()

        # Reset the configuration overrides.
        cfg.ConfigOpts.GroupAttr.__getattr__ = self._original_call_method

    def test_valid_cors_options_request(self):
        response = self._do_options('servers',
                                    headers={
                                        'Origin': 'http://valid.example.com',
                                        'Access-Control-Request-Method': 'GET'
                                    })

        self.assertEqual(response.status_code, 200)
        self.assertIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual('http://valid.example.com',
                         response.headers['Access-Control-Allow-Origin'])

    def test_invalid_cors_options_request(self):
        response = self._do_options('servers',
                                    headers={
                                        'Origin': 'http://invalid.example.com',
                                        'Access-Control-Request-Method': 'GET'
                                    })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_valid_cors_get_request(self):
        response = self._do_get('servers',
                                headers={
                                    'Origin': 'http://valid.example.com',
                                    'Access-Control-Request-Method': 'GET'
                                })

        self.assertEqual(response.status_code, 200)
        self.assertIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual('http://valid.example.com',
                         response.headers['Access-Control-Allow-Origin'])

    def test_invalid_cors_get_request(self):
        response = self._do_get('servers',
                                headers={
                                    'Origin': 'http://invalid.example.com',
                                    'Access-Control-Request-Method': 'GET'
                                })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_valid_cors_get_versions_request(self):
        response = self._do_get('',
                                strip_version=True,
                                headers={
                                    'Origin': 'http://valid.example.com',
                                    'Access-Control-Request-Method': 'GET'
                                })

        self.assertEqual(response.status_code, self.exp_version_status)
        self.assertIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual('http://valid.example.com',
                         response.headers['Access-Control-Allow-Origin'])

    def test_invalid_cors_get_versions_request(self):
        response = self._do_get('',
                                strip_version=True,
                                headers={
                                    'Origin': 'http://invalid.example.com',
                                    'Access-Control-Request-Method': 'GET'
                                })

        self.assertEqual(response.status_code, self.exp_version_status)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
