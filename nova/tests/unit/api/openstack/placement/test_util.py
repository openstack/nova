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
"""Unit tests for the utility functions used by the placement API."""


from oslo_middleware import request_id

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova import test


class TestJSONErrorFormatter(test.NoDBTestCase):

    def setUp(self):
        super(TestJSONErrorFormatter, self).setUp()
        self.environ = {}

    def test_status_to_int_code(self):
        body = ''
        status = '404 Not Found'
        title = ''

        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertEqual(404, result['errors'][0]['status'])

    def test_strip_body_tags(self):
        body = '<h1>Big Error!</h1>'
        status = '400 Bad Request'
        title = ''

        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertEqual('Big Error!', result['errors'][0]['detail'])

    def test_request_id_presence(self):
        body = ''
        status = '400 Bad Request'
        title = ''

        # no request id in environ, none in error
        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertNotIn('request_id', result['errors'][0])

        # request id in environ, request id in error
        self.environ[request_id.ENV_REQUEST_ID] = 'stub-id'

        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertEqual('stub-id', result['errors'][0]['request_id'])

    def test_microversion_406_handling(self):
        body = ''
        status = '400 Bad Request'
        title = ''

        # Not a 406, no version info required.
        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertNotIn('max_version', result['errors'][0])
        self.assertNotIn('min_version', result['errors'][0])

        # A 406 but not because of microversions (microversion
        # parsing was successful), no version info
        # required.
        status = '406 Not Acceptable'
        version_obj = microversion.parse_version_string('2.3')
        self.environ[microversion.MICROVERSION_ENVIRON] = version_obj

        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertNotIn('max_version', result['errors'][0])
        self.assertNotIn('min_version', result['errors'][0])

        # Microversion parsing failed, status is 406, send version info.
        del self.environ[microversion.MICROVERSION_ENVIRON]

        result = util.json_error_formatter(
            body, status, title, self.environ)
        self.assertEqual(microversion.max_version_string(),
                         result['errors'][0]['max_version'])
        self.assertEqual(microversion.min_version_string(),
                         result['errors'][0]['min_version'])
