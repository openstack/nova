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
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova import objects
from nova import test
from nova.tests import uuidsentinel


class TestCheckAccept(test.NoDBTestCase):
    """Confirm behavior of util.check_accept."""

    @staticmethod
    @util.check_accept('application/json', 'application/vnd.openstack')
    def handler(req):
        """Fake handler to test decorator."""
        return True

    def test_fail_no_match(self):
        req = webob.Request.blank('/')
        req.accept = 'text/plain'

        error = self.assertRaises(webob.exc.HTTPNotAcceptable,
                                  self.handler, req)
        self.assertEqual(
            'Only application/json, application/vnd.openstack is provided',
            str(error))

    def test_fail_complex_no_match(self):
        req = webob.Request.blank('/')
        req.accept = 'text/html;q=0.9,text/plain,application/vnd.aws;q=0.8'

        error = self.assertRaises(webob.exc.HTTPNotAcceptable,
                                  self.handler, req)
        self.assertEqual(
            'Only application/json, application/vnd.openstack is provided',
            str(error))

    def test_success_no_accept(self):
        req = webob.Request.blank('/')
        self.assertTrue(self.handler(req))

    def test_success_simple_match(self):
        req = webob.Request.blank('/')
        req.accept = 'application/json'
        self.assertTrue(self.handler(req))

    def test_success_complex_any_match(self):
        req = webob.Request.blank('/')
        req.accept = 'application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        self.assertTrue(self.handler(req))

    def test_success_complex_lower_quality_match(self):
        req = webob.Request.blank('/')
        req.accept = 'application/xml;q=0.9,application/vnd.openstack;q=0.8'
        self.assertTrue(self.handler(req))


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


class TestRequireContent(test.NoDBTestCase):
    """Confirm behavior of util.require_accept."""

    @staticmethod
    @util.require_content('application/json')
    def handler(req):
        """Fake handler to test decorator."""
        return True

    def test_fail_no_content_type(self):
        req = webob.Request.blank('/')

        error = self.assertRaises(webob.exc.HTTPUnsupportedMediaType,
                                  self.handler, req)
        self.assertEqual(
            'The media type None is not supported, use application/json',
            str(error))

    def test_fail_wrong_content_type(self):
        req = webob.Request.blank('/')
        req.content_type = 'text/plain'

        error = self.assertRaises(webob.exc.HTTPUnsupportedMediaType,
                                  self.handler, req)
        self.assertEqual(
            'The media type text/plain is not supported, use application/json',
            str(error))

    def test_success_content_type(self):
        req = webob.Request.blank('/')
        req.content_type = 'application/json'
        self.assertTrue(self.handler(req))


class TestPlacementURLs(test.NoDBTestCase):

    def setUp(self):
        super(TestPlacementURLs, self).setUp()
        self.resource_provider = objects.ResourceProvider(
            name=uuidsentinel.rp_name,
            uuid=uuidsentinel.rp_uuid)

    def test_resource_provider_url(self):
        environ = {}
        expected_url = '/resource_providers/%s' % uuidsentinel.rp_uuid
        self.assertEqual(expected_url, util.resource_provider_url(
            environ, self.resource_provider))

    def test_resource_provider_url_prefix(self):
        # SCRIPT_NAME represents the mount point of a WSGI
        # application when it is hosted at a path/prefix.
        environ = {'SCRIPT_NAME': '/placement'}
        expected_url = ('/placement/resource_providers/%s'
                        % uuidsentinel.rp_uuid)
        self.assertEqual(expected_url, util.resource_provider_url(
            environ, self.resource_provider))
