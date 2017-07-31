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


import fixtures
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


class TestExtractJSON(test.NoDBTestCase):

    # Although the intent of this test class is not to test that
    # schemas work, we may as well use a real one to ensure that
    # behaviors are what we expect.
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "uuid": {"type": "string", "format": "uuid"}
        },
        "required": ["name"],
        "additionalProperties": False
    }

    def test_not_json(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  'I am a string',
                                  self.schema)
        self.assertIn('Malformed JSON', str(error))

    def test_malformed_json(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  '{"my bytes got left behind":}',
                                  self.schema)
        self.assertIn('Malformed JSON', str(error))

    def test_schema_mismatch(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  '{"a": "b"}',
                                  self.schema)
        self.assertIn('JSON does not validate', str(error))

    def test_type_invalid(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  '{"name": 1}',
                                  self.schema)
        self.assertIn('JSON does not validate', str(error))

    def test_format_checker(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  '{"name": "hello", "uuid": "not a uuid"}',
                                  self.schema)
        self.assertIn('JSON does not validate', str(error))

    def test_no_additional_properties(self):
        error = self.assertRaises(webob.exc.HTTPBadRequest,
                                  util.extract_json,
                                  '{"name": "hello", "cow": "moo"}',
                                  self.schema)
        self.assertIn('JSON does not validate', str(error))

    def test_valid(self):
        data = util.extract_json(
            '{"name": "cow", '
            '"uuid": "%s"}' % uuidsentinel.rp_uuid,
            self.schema)
        self.assertEqual('cow', data['name'])
        self.assertEqual(uuidsentinel.rp_uuid, data['uuid'])


class TestJSONErrorFormatter(test.NoDBTestCase):

    def setUp(self):
        super(TestJSONErrorFormatter, self).setUp()
        self.environ = {}
        # TODO(jaypipes): Remove this when we get more than a single version
        # in the placement API. The fact that we only had a single version was
        # masking a bug in the utils code.
        _versions = [
            '1.0',
            '1.1',
        ]
        mod_str = 'nova.api.openstack.placement.microversion.VERSIONS'
        self.useFixture(fixtures.MonkeyPatch(mod_str, _versions))

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
        self.resource_class = objects.ResourceClass(
            name='CUSTOM_BAREMETAL_GOLD',
            id=1000)

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

    def test_inventories_url(self):
        environ = {}
        expected_url = ('/resource_providers/%s/inventories'
                        % uuidsentinel.rp_uuid)
        self.assertEqual(expected_url, util.inventory_url(
            environ, self.resource_provider))

    def test_inventory_url(self):
        resource_class = 'DISK_GB'
        environ = {}
        expected_url = ('/resource_providers/%s/inventories/%s'
                        % (uuidsentinel.rp_uuid, resource_class))
        self.assertEqual(expected_url, util.inventory_url(
            environ, self.resource_provider, resource_class))

    def test_resource_class_url(self):
        environ = {}
        expected_url = '/resource_classes/CUSTOM_BAREMETAL_GOLD'
        self.assertEqual(expected_url, util.resource_class_url(
            environ, self.resource_class))

    def test_resource_class_url_prefix(self):
        # SCRIPT_NAME represents the mount point of a WSGI
        # application when it is hosted at a path/prefix.
        environ = {'SCRIPT_NAME': '/placement'}
        expected_url = '/placement/resource_classes/CUSTOM_BAREMETAL_GOLD'
        self.assertEqual(expected_url, util.resource_class_url(
            environ, self.resource_class))


class TestNormalizeResourceQsParam(test.NoDBTestCase):

    def test_success(self):
        qs = "VCPU:1"
        resources = util.normalize_resources_qs_param(qs)
        expected = {
            'VCPU': 1,
        }
        self.assertEqual(expected, resources)

        qs = "VCPU:1,MEMORY_MB:1024,DISK_GB:100"
        resources = util.normalize_resources_qs_param(qs)
        expected = {
            'VCPU': 1,
            'MEMORY_MB': 1024,
            'DISK_GB': 100,
        }
        self.assertEqual(expected, resources)

    def test_400_empty_string(self):
        qs = ""
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            util.normalize_resources_qs_param,
            qs,
        )

    def test_400_bad_int(self):
        qs = "VCPU:foo"
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            util.normalize_resources_qs_param,
            qs,
        )

    def test_400_no_amount(self):
        qs = "VCPU"
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            util.normalize_resources_qs_param,
            qs,
        )

    def test_400_zero_amount(self):
        qs = "VCPU:0"
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            util.normalize_resources_qs_param,
            qs,
        )
