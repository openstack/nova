# Copyright 2013 NEC Corporation.  All rights reserved.
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

import copy
import re
import sys

import fixtures
from jsonschema import exceptions as jsonschema_exc
import six

from nova.api.openstack import api_version_request as api_version
from nova.api import validation
from nova.api.validation import parameter_types
from nova.api.validation import validators
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


query_schema = {
    'type': 'object',
    'properties': {
        'foo': parameter_types.single_param({'type': 'string',
                                             'format': 'uuid'}),
        'foos': parameter_types.multi_params({'type': 'string'})
    },
    'patternProperties': {
        "^_": parameter_types.multi_params({'type': 'string'})},
    'additionalProperties': True
}


class FakeQueryParametersController(object):

    @validation.query_schema(query_schema, '2.3')
    def get(self, req):
        return list(set(req.GET.keys()))


class RegexFormatFakeController(object):

    schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'format': 'regex',
            },
        },
    }

    @validation.schema(request_body_schema=schema)
    def post(self, req, body):
        return 'Validation succeeded.'


class FakeRequest(object):
    api_version_request = api_version.APIVersionRequest("2.1")
    environ = {}
    legacy_v2 = False

    def is_legacy_v2(self):
        return self.legacy_v2


class ValidationRegex(test.NoDBTestCase):
    def test_cell_names(self):
        cellre = re.compile(parameter_types.valid_cell_name_regex.regex)
        self.assertTrue(cellre.search('foo'))
        self.assertFalse(cellre.search('foo.bar'))
        self.assertFalse(cellre.search('foo@bar'))
        self.assertFalse(cellre.search('foo!bar'))
        self.assertFalse(cellre.search(' foo!bar'))
        self.assertFalse(cellre.search('\nfoo!bar'))

    def test_build_regex_range(self):
        # this is much easier to think about if we only use the ascii
        # subset because it's a printable range we can think
        # about. The algorithm works for all ranges.
        def _get_all_chars():
            for i in range(0x7F):
                yield six.unichr(i)

        self.useFixture(fixtures.MonkeyPatch(
            'nova.api.validation.parameter_types._get_all_chars',
            _get_all_chars))

        r = parameter_types._build_regex_range(ws=False)
        self.assertEqual(r, re.escape('!') + '-' + re.escape('~'))

        # if we allow whitespace the range starts earlier
        r = parameter_types._build_regex_range(ws=True)
        self.assertEqual(r, re.escape(' ') + '-' + re.escape('~'))

        # excluding a character will give us 2 ranges
        r = parameter_types._build_regex_range(ws=True, exclude=['A'])
        self.assertEqual(r,
                         re.escape(' ') + '-' + re.escape('@') +
                         'B' + '-' + re.escape('~'))

        # inverting which gives us all the initial unprintable characters.
        r = parameter_types._build_regex_range(ws=False, invert=True)
        self.assertEqual(r,
                         re.escape('\x00') + '-' + re.escape(' '))

        # excluding characters that create a singleton. Naively this would be:
        # ' -@B-BD-~' which seems to work, but ' -@BD-~' is more natural.
        r = parameter_types._build_regex_range(ws=True, exclude=['A', 'C'])
        self.assertEqual(r,
                         re.escape(' ') + '-' + re.escape('@') +
                         'B' + 'D' + '-' + re.escape('~'))

        # ws=True means the positive regex has printable whitespaces,
        # so the inverse will not. The inverse will include things we
        # exclude.
        r = parameter_types._build_regex_range(
            ws=True, exclude=['A', 'B', 'C', 'Z'], invert=True)
        self.assertEqual(r,
                         re.escape('\x00') + '-' + re.escape('\x1f') + 'A-CZ')


class APIValidationTestCase(test.NoDBTestCase):

    post_schema = None

    def setUp(self):
        super(APIValidationTestCase, self).setUp()
        self.post = None

        if self.post_schema is not None:
            @validation.schema(request_body_schema=self.post_schema)
            def post(req, body):
                return 'Validation succeeded.'

            self.post = post

    def check_validation_error(self, method, body, expected_detail, req=None):
        if not req:
            req = FakeRequest()
        try:
            method(body=body, req=req)
        except exception.ValidationError as ex:
            self.assertEqual(400, ex.kwargs['code'])
            if isinstance(expected_detail, list):
                self.assertIn(ex.kwargs['detail'], expected_detail,
                              'Exception details did not match expected')
            elif not re.match(expected_detail, ex.kwargs['detail']):
                self.assertEqual(expected_detail, ex.kwargs['detail'],
                                 'Exception details did not match expected')
        except Exception as ex:
            self.fail('An unexpected exception happens: %s' % ex)
        else:
            self.fail('Any exception does not happen.')


class FormatCheckerTestCase(test.NoDBTestCase):

    def _format_checker(self, format, value, error_message):
        format_checker = validators.FormatChecker()
        exc = self.assertRaises(jsonschema_exc.FormatError,
                                format_checker.check, value, format)
        self.assertIsInstance(exc.cause, exception.InvalidName)
        self.assertEqual(error_message,
                         exc.cause.format_message())

    def test_format_checker_failed_with_non_string_name(self):
        error_message = ("An invalid 'name' value was provided. The name must "
                         "be: printable characters. "
                         "Can not start or end with whitespace.")
        self._format_checker("name", "   ", error_message)
        self._format_checker("name", None, error_message)

    def test_format_checker_failed_with_non_string_cell_name(self):
        error_message = ("An invalid 'name' value was provided. "
                         "The name must be: printable characters except "
                         "!, ., @. Can not start or end with whitespace.")
        self._format_checker("cell_name", None, error_message)

    def test_format_checker_failed_name_with_leading_trailing_spaces(self):
        error_message = ("An invalid 'name' value was provided. "
                         "The name must be: printable characters with at "
                         "least one non space character")
        self._format_checker("name_with_leading_trailing_spaces",
                             None, error_message)

    def test_format_checker_failed_cell_name_with_leading_trailing_spaces(
            self):
        error_message = ("An invalid 'name' value was provided. "
                         "The name must be: printable characters except"
                         " !, ., @, with at least one non space character")
        self._format_checker("cell_name_with_leading_trailing_spaces",
                             None, error_message)


class MicroversionsSchemaTestCase(APIValidationTestCase):

    def setUp(self):
        super(MicroversionsSchemaTestCase, self).setUp()
        schema_v21_int = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                }
            }
        }
        schema_v20_str = copy.deepcopy(schema_v21_int)
        schema_v20_str['properties']['foo'] = {'type': 'string'}

        @validation.schema(schema_v20_str, '2.0', '2.0')
        @validation.schema(schema_v21_int, '2.1')
        def post(req, body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_v2compatible_request(self):
        req = FakeRequest()
        req.legacy_v2 = True
        self.assertEqual(self.post(body={'foo': 'bar'}, req=req),
                         'Validation succeeded.')
        detail = ("Invalid input for field/attribute foo. Value: 1. "
                  "1 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1},
                                    expected_detail=detail, req=req)

    def test_validate_v21_request(self):
        req = FakeRequest()
        self.assertEqual(self.post(body={'foo': 1}, req=req),
                         'Validation succeeded.')
        detail = ("Invalid input for field/attribute foo. Value: bar. "
                  "'bar' is not of type 'integer'")
        self.check_validation_error(self.post, body={'foo': 'bar'},
                                    expected_detail=detail, req=req)

    def test_validate_v2compatible_request_with_none_min_version(self):
        schema_none = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer'
                }
            }
        }

        @validation.schema(schema_none)
        def post(req, body):
            return 'Validation succeeded.'

        req = FakeRequest()
        req.legacy_v2 = True
        self.assertEqual('Validation succeeded.',
                         post(body={'foo': 1}, req=req))
        detail = ("Invalid input for field/attribute foo. Value: bar. "
                  "'bar' is not of type 'integer'")
        self.check_validation_error(post, body={'foo': 'bar'},
                                    expected_detail=detail, req=req)


class QueryParamsSchemaTestCase(test.NoDBTestCase):

    def setUp(self):
        super(QueryParamsSchemaTestCase, self).setUp()
        self.controller = FakeQueryParametersController()

    def test_validate_request(self):
        req = fakes.HTTPRequest.blank("/tests?foo=%s" % fakes.FAKE_UUID)
        req.api_version_request = api_version.APIVersionRequest("2.3")
        self.assertEqual(['foo'], self.controller.get(req))

    def test_validate_request_failed(self):
        # parameter 'foo' expect a UUID
        req = fakes.HTTPRequest.blank("/tests?foo=abc")
        req.api_version_request = api_version.APIVersionRequest("2.3")
        ex = self.assertRaises(exception.ValidationError, self.controller.get,
                               req)
        if six.PY3:
            self.assertEqual("Invalid input for query parameters foo. Value: "
                             "abc. 'abc' is not a 'uuid'", six.text_type(ex))
        else:
            self.assertEqual("Invalid input for query parameters foo. Value: "
                             "abc. u'abc' is not a 'uuid'", six.text_type(ex))

    def test_validate_request_with_multiple_values(self):
        req = fakes.HTTPRequest.blank("/tests?foos=abc")
        req.api_version_request = api_version.APIVersionRequest("2.3")
        self.assertEqual(['foos'], self.controller.get(req))
        req = fakes.HTTPRequest.blank("/tests?foos=abc&foos=def")
        self.assertEqual(['foos'], self.controller.get(req))

    def test_validate_request_with_multiple_values_fails(self):
        req = fakes.HTTPRequest.blank(
            "/tests?foo=%s&foo=%s" % (fakes.FAKE_UUID, fakes.FAKE_UUID))
        req.api_version_request = api_version.APIVersionRequest("2.3")
        self.assertRaises(exception.ValidationError, self.controller.get, req)

    def test_validate_request_unicode_decode_failure(self):
        req = fakes.HTTPRequest.blank("/tests?foo=%88")
        req.api_version_request = api_version.APIVersionRequest("2.1")
        ex = self.assertRaises(
            exception.ValidationError, self.controller.get, req)
        self.assertIn("Query string is not UTF-8 encoded", six.text_type(ex))

    def test_strip_out_additional_properties(self):
        req = fakes.HTTPRequest.blank(
            "/tests?foos=abc&foo=%s&bar=123&-bar=456" % fakes.FAKE_UUID)
        req.api_version_request = api_version.APIVersionRequest("2.3")
        res = self.controller.get(req)
        res.sort()
        self.assertEqual(['foo', 'foos'], res)

    def test_no_strip_out_additional_properties_when_not_match_version(self):
        req = fakes.HTTPRequest.blank(
            "/tests?foos=abc&foo=%s&bar=123&bar=456" % fakes.FAKE_UUID)
        # The JSON-schema matches to the API version 2.3 and above. Request
        # with version 2.1 to ensure there isn't no strip out for additional
        # parameters when schema didn't match the request version.
        req.api_version_request = api_version.APIVersionRequest("2.1")
        res = self.controller.get(req)
        res.sort()
        self.assertEqual(['bar', 'foo', 'foos'], res)

    def test_strip_out_correct_pattern_retained(self):
        req = fakes.HTTPRequest.blank(
            "/tests?foos=abc&foo=%s&bar=123&_foo_=456" % fakes.FAKE_UUID)
        req.api_version_request = api_version.APIVersionRequest("2.3")
        res = self.controller.get(req)
        res.sort()
        self.assertEqual(['_foo_', 'foo', 'foos'], res)


class RequiredDisableTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'integer',
            },
        },
    }

    def test_validate_required_disable(self):
        self.assertEqual(self.post(body={'foo': 1}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'abc': 1}, req=FakeRequest()),
                         'Validation succeeded.')


class RequiredEnableTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'integer',
            },
        },
        'required': ['foo']
    }

    def test_validate_required_enable(self):
        self.assertEqual(self.post(body={'foo': 1},
                                   req=FakeRequest()), 'Validation succeeded.')

    def test_validate_required_enable_fails(self):
        detail = "'foo' is a required property"
        self.check_validation_error(self.post, body={'abc': 1},
                                    expected_detail=detail)


class AdditionalPropertiesEnableTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'integer',
            },
        },
        'required': ['foo'],
    }

    def test_validate_additionalProperties_enable(self):
        self.assertEqual(self.post(body={'foo': 1}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': 1, 'ext': 1},
                                   req=FakeRequest()),
                         'Validation succeeded.')


class AdditionalPropertiesDisableTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'integer',
            },
        },
        'required': ['foo'],
        'additionalProperties': False,
    }

    def test_validate_additionalProperties_disable(self):
        self.assertEqual(self.post(body={'foo': 1}, req=FakeRequest()),
                         'Validation succeeded.')

    def test_validate_additionalProperties_disable_fails(self):
        detail = "Additional properties are not allowed ('ext' was unexpected)"
        self.check_validation_error(self.post, body={'foo': 1, 'ext': 1},
                                    expected_detail=detail)


class PatternPropertiesTestCase(APIValidationTestCase):

    post_schema = {
        'patternProperties': {
            '^[a-zA-Z0-9]{1,10}$': {
                'type': 'string'
            },
        },
        'additionalProperties': False,
    }

    def test_validate_patternProperties(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'bar'}, req=FakeRequest()))

    def test_validate_patternProperties_fails(self):
        details = [
            "Additional properties are not allowed ('__' was unexpected)",
            "'__' does not match any of the regexes: '^[a-zA-Z0-9]{1,10}$'"
        ]
        self.check_validation_error(self.post, body={'__': 'bar'},
                                    expected_detail=details)

        details = [
            "'' does not match any of the regexes: '^[a-zA-Z0-9]{1,10}$'",
            "Additional properties are not allowed ('' was unexpected)"
        ]
        self.check_validation_error(self.post, body={'': 'bar'},
                                    expected_detail=details)

        details = [
            ("'0123456789a' does not match any of the regexes: "
                  "'^[a-zA-Z0-9]{1,10}$'"),
            ("Additional properties are not allowed ('0123456789a' was"
             " unexpected)")
        ]
        self.check_validation_error(self.post, body={'0123456789a': 'bar'},
                                    expected_detail=details)

        # Note(jrosenboom): This is referencing an internal python error
        # string, which is no stable interface. We need a patch in the
        # jsonschema library in order to fix this properly.
        if sys.version[:3] in ['3.5', '3.6']:
            detail = "expected string or bytes-like object"
        else:
            detail = "expected string or buffer"
        self.check_validation_error(self.post, body={None: 'bar'},
                                    expected_detail=detail)


class StringTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
            },
        },
    }

    def test_validate_string(self):
        self.assertEqual(self.post(body={'foo': 'abc'}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0'}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': ''}, req=FakeRequest()),
                         'Validation succeeded.')

    def test_validate_string_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " 1 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.5."
                  " 1.5 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1.5},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)


class StringLengthTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'minLength': 1,
                'maxLength': 10,
            },
        },
    }

    def test_validate_string_length(self):
        self.assertEqual(self.post(body={'foo': '0'}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0123456789'},
                                   req=FakeRequest()),
                         'Validation succeeded.')

    def test_validate_string_length_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: ."
                  " '' is too short")
        self.check_validation_error(self.post, body={'foo': ''},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0123456789a."
                  " '0123456789a' is too long")
        self.check_validation_error(self.post, body={'foo': '0123456789a'},
                                    expected_detail=detail)


class IntegerTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': ['integer', 'string'],
                'pattern': '^[0-9]+$',
            },
        },
    }

    def test_validate_integer(self):
        self.assertEqual(self.post(body={'foo': 1}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '1'}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0123456789'},
                                   req=FakeRequest()),
                         'Validation succeeded.')

    def test_validate_integer_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: abc."
                  " 'abc' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': 'abc'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0xffff."
                  " '0xffff' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': '0xffff'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.0."
                  " 1.0 is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': 1.0},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.0."
                  " '1.0' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': '1.0'},
                                    expected_detail=detail)


class IntegerRangeTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': ['integer', 'string'],
                'pattern': '^[0-9]+$',
                'minimum': 1,
                'maximum': 10,
            },
        },
    }

    def test_validate_integer_range(self):
        self.assertEqual(self.post(body={'foo': 1}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': 10}, req=FakeRequest()),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '1'}, req=FakeRequest()),
                         'Validation succeeded.')

    def test_validate_integer_range_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: 0."
                  " 0(.0)? is less than the minimum of 1")
        self.check_validation_error(self.post, body={'foo': 0},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 11."
                  " 11(.0)? is greater than the maximum of 10")
        self.check_validation_error(self.post, body={'foo': 11},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0."
                  " 0(.0)? is less than the minimum of 1")
        self.check_validation_error(self.post, body={'foo': '0'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 11."
                  " 11(.0)? is greater than the maximum of 10")
        self.check_validation_error(self.post, body={'foo': '11'},
                                    expected_detail=detail)


class BooleanTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.boolean,
        },
    }

    def test_validate_boolean(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': True}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': False}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'True'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'False'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0'}, req=FakeRequest()))

    def test_validate_boolean_fails(self):
        enum_boolean = ("[True, 'True', 'TRUE', 'true', '1', 'ON', 'On',"
                        " 'on', 'YES', 'Yes', 'yes',"
                        " False, 'False', 'FALSE', 'false', '0', 'OFF', 'Off',"
                        " 'off', 'NO', 'No', 'no']")

        detail = ("Invalid input for field/attribute foo. Value: bar."
                  " 'bar' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': 'bar'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 2."
                  " '2' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': '2'},
                                    expected_detail=detail)


class HostnameTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.hostname,
        },
    }

    def test_validate_hostname(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost.localdomain.com'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my-host'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my_host'}, req=FakeRequest()))

    def test_validate_hostname_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " 1 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: my$host."
                  " 'my$host' does not match '^[a-zA-Z0-9-._]*$'")
        self.check_validation_error(self.post, body={'foo': 'my$host'},
                                    expected_detail=detail)


class HostnameIPaddressTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.hostname_or_ip_address,
        },
    }

    def test_validate_hostname_or_ip_address(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost.localdomain.com'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my-host'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my_host'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '192.168.10.100'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '2001:db8::9abc'},
                                   req=FakeRequest()))

    def test_validate_hostname_or_ip_address_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " 1 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: my$host."
                  " 'my$host' does not match '^[a-zA-Z0-9-_.:]*$'")
        self.check_validation_error(self.post, body={'foo': 'my$host'},
                                    expected_detail=detail)


class CellNameTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.cell_name,
        },
    }

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'abc'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434\u2006\ufffd'},
                                   req=FakeRequest()))

    def test_validate_name_fails(self):
        error = ("An invalid 'name' value was provided. The name must be: "
                 "printable characters except !, ., @. "
                 "Can not start or end with whitespace.")

        should_fail = (' ',
                       ' server',
                       'server ',
                       u'a\xa0',  # trailing unicode space
                       u'\uffff',  # non-printable unicode
                       'abc!def',
                       'abc.def',
                       'abc@def')

        for item in should_fail:
            self.check_validation_error(self.post, body={'foo': item},
                                    expected_detail=error)

        # four-byte unicode, if supported by this python build
        try:
            self.check_validation_error(self.post, body={'foo': u'\U00010000'},
                                        expected_detail=error)
        except ValueError:
            pass


class CellNameLeadingTrailingSpacesTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.cell_name_leading_trailing_spaces,
        },
    }

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'abc'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434\u2006\ufffd'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '  my server'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server  '},
                                   req=FakeRequest()))

    def test_validate_name_fails(self):
        error = ("An invalid 'name' value was provided. The name must be: "
                 "printable characters except !, ., @, "
                 "with at least one non space character")

        should_fail = (
            ' ',
            u'\uffff',  # non-printable unicode
            'abc!def',
            'abc.def',
            'abc@def')

        for item in should_fail:
            self.check_validation_error(self.post, body={'foo': item},
                                    expected_detail=error)

        # four-byte unicode, if supported by this python build
        try:
            self.check_validation_error(self.post, body={'foo': u'\U00010000'},
                                        expected_detail=error)
        except ValueError:
            pass


class NameTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.name,
        },
    }

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'm1.small'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'a'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434\u2006\ufffd'},
                                   req=FakeRequest()))

    def test_validate_name_fails(self):
        error = ("An invalid 'name' value was provided. The name must be: "
                 "printable characters. "
                 "Can not start or end with whitespace.")

        should_fail = (' ',
                       ' server',
                       'server ',
                       u'a\xa0',  # trailing unicode space
                       u'\uffff',  # non-printable unicode
                       )

        for item in should_fail:
            self.check_validation_error(self.post, body={'foo': item},
                                    expected_detail=error)

        # four-byte unicode, if supported by this python build
        try:
            self.check_validation_error(self.post, body={'foo': u'\U00010000'},
                                        expected_detail=error)
        except ValueError:
            pass


class NameWithLeadingTrailingSpacesTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.name_with_leading_trailing_spaces,
        },
    }

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'm1.small'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'a'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434\u2006\ufffd'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '  abc  '},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'abc  abc  abc'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '  abc  abc  abc  '},
                                   req=FakeRequest()))
        # leading unicode space
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '\xa0abc'},
                                   req=FakeRequest()))

    def test_validate_name_fails(self):
        error = ("An invalid 'name' value was provided. The name must be: "
                 "printable characters with at least one non space character")

        should_fail = (
            ' ',
            u'\xa0',  # unicode space
            u'\uffff',  # non-printable unicode
        )

        for item in should_fail:
            self.check_validation_error(self.post, body={'foo': item},
                                    expected_detail=error)

        # four-byte unicode, if supported by this python build
        try:
            self.check_validation_error(self.post, body={'foo': u'\U00010000'},
                                        expected_detail=error)
        except ValueError:
            pass


class NoneTypeTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.none
        }
    }

    def test_validate_none(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'None'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': None},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': {}},
                                   req=FakeRequest()))

    def test_validate_none_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: ."
                  " '' is not one of ['None', None, {}]")
        self.check_validation_error(self.post, body={'foo': ''},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: "
                  "{'key': 'val'}. {'key': 'val'} is not one of "
                  "['None', None, {}]")
        self.check_validation_error(self.post, body={'foo': {'key': 'val'}},
                                    expected_detail=detail)


class NameOrNoneTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.name_or_none
        }
    }

    def test_valid(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': None},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'},
                                   req=FakeRequest()))

    def test_validate_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: 1234. 1234 "
                  "is not valid under any of the given schemas")
        self.check_validation_error(self.post, body={'foo': 1234},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: . '' "
                  "is not valid under any of the given schemas")
        self.check_validation_error(self.post, body={'foo': ''},
                                    expected_detail=detail)

        too_long_name = 256 * "k"
        detail = ("Invalid input for field/attribute foo. Value: %s. "
                  "'%s' is not valid under any of the "
                  "given schemas") % (too_long_name, too_long_name)
        self.check_validation_error(self.post,
                                    body={'foo': too_long_name},
                                    expected_detail=detail)


class TcpUdpPortTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': parameter_types.tcp_udp_port,
        },
    }

    def test_validate_tcp_udp_port(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1024}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1024'}, req=FakeRequest()))

    def test_validate_tcp_udp_port_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 65536."
                  " 65536(.0)? is greater than the maximum of 65535")
        self.check_validation_error(self.post, body={'foo': 65536},
                                    expected_detail=detail)


class CidrFormatTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'cidr',
            },
        },
    }

    def test_validate_cidr(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '192.168.10.0/24'},
                         req=FakeRequest()
                         ))

    def test_validate_cidr_fails(self):
        detail = ("Invalid input for field/attribute foo."
                  " Value: bar."
                  " 'bar' is not a 'cidr'")
        self.check_validation_error(self.post,
                                    body={'foo': 'bar'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: . '' is not a 'cidr'")
        self.check_validation_error(self.post, body={'foo': ''},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: 192.168.1.0. '192.168.1.0' is not a 'cidr'")
        self.check_validation_error(self.post, body={'foo': '192.168.1.0'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: 192.168.1.0 /24."
                  " '192.168.1.0 /24' is not a 'cidr'")
        self.check_validation_error(self.post, body={'foo': '192.168.1.0 /24'},
                                    expected_detail=detail)


class DatetimeTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'date-time',
            },
        },
    }

    def test_validate_datetime(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                            body={'foo': '2014-01-14T01:00:00Z'},
                            req=FakeRequest()
                         ))

    def test_validate_datetime_fails(self):
        detail = ("Invalid input for field/attribute foo."
                  " Value: 2014-13-14T01:00:00Z."
                  " '2014-13-14T01:00:00Z' is not a 'date-time'")
        self.check_validation_error(self.post,
                                    body={'foo': '2014-13-14T01:00:00Z'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: bar. 'bar' is not a 'date-time'")
        self.check_validation_error(self.post, body={'foo': 'bar'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " '1' is not a 'date-time'")
        self.check_validation_error(self.post, body={'foo': '1'},
                                    expected_detail=detail)


class UuidTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'uuid',
            },
        },
    }

    def test_validate_uuid(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '70a599e0-31e7-49b7-b260-868f441e862b'},
                             req=FakeRequest()
                         ))

    def test_validate_uuid_fails(self):
        detail = ("Invalid input for field/attribute foo."
                  " Value: 70a599e031e749b7b260868f441e862."
                  " '70a599e031e749b7b260868f441e862' is not a 'uuid'")
        self.check_validation_error(self.post,
            body={'foo': '70a599e031e749b7b260868f441e862'},
            expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " '1' is not a 'uuid'")
        self.check_validation_error(self.post, body={'foo': '1'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: abc."
                  " 'abc' is not a 'uuid'")
        self.check_validation_error(self.post, body={'foo': 'abc'},
                                    expected_detail=detail)


class UriTestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'uri',
            },
        },
    }

    def test_validate_uri(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': 'http://localhost:8774/v2/servers'},
                         req=FakeRequest()
                         ))
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': 'http://[::1]:8774/v2/servers'},
                         req=FakeRequest()
                         ))

    def test_validate_uri_fails(self):
        base_detail = ("Invalid input for field/attribute foo. Value: {0}. "
                       "'{0}' is not a 'uri'")
        invalid_uri = 'http://localhost:8774/v2/servers##'
        self.check_validation_error(self.post,
                                    body={'foo': invalid_uri},
                                    expected_detail=base_detail.format(
                                        invalid_uri))

        invalid_uri = 'http://[fdf8:01]:8774/v2/servers'
        self.check_validation_error(self.post,
                                    body={'foo': invalid_uri},
                                    expected_detail=base_detail.format(
                                        invalid_uri))

        invalid_uri = '1'
        self.check_validation_error(self.post,
                                    body={'foo': invalid_uri},
                                    expected_detail=base_detail.format(
                                        invalid_uri))

        invalid_uri = 'abc'
        self.check_validation_error(self.post,
                                    body={'foo': invalid_uri},
                                    expected_detail=base_detail.format(
                                        invalid_uri))


class Ipv4TestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'ipv4',
            },
        },
    }

    def test_validate_ipv4(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '192.168.0.100'},
                         req=FakeRequest()
                         ))

    def test_validate_ipv4_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: abc."
                  " 'abc' is not a 'ipv4'")
        self.check_validation_error(self.post, body={'foo': 'abc'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: localhost."
                  " 'localhost' is not a 'ipv4'")
        self.check_validation_error(self.post, body={'foo': 'localhost'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: 2001:db8::1234:0:0:9abc."
                  " '2001:db8::1234:0:0:9abc' is not a 'ipv4'")
        self.check_validation_error(self.post,
                                    body={'foo': '2001:db8::1234:0:0:9abc'},
                                    expected_detail=detail)


class Ipv6TestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
                'type': 'string',
                'format': 'ipv6',
            },
        },
    }

    def test_validate_ipv6(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '2001:db8::1234:0:0:9abc'},
                         req=FakeRequest()
                         ))

    def test_validate_ipv6_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: abc."
                  " 'abc' is not a 'ipv6'")
        self.check_validation_error(self.post, body={'foo': 'abc'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: localhost."
                  " 'localhost' is not a 'ipv6'")
        self.check_validation_error(self.post, body={'foo': 'localhost'},
                                        expected_detail=detail)

        detail = ("Invalid input for field/attribute foo."
                  " Value: 192.168.0.100. '192.168.0.100' is not a 'ipv6'")
        self.check_validation_error(self.post, body={'foo': '192.168.0.100'},
                                    expected_detail=detail)


class Base64TestCase(APIValidationTestCase):

    post_schema = {
        'type': 'object',
        'properties': {
            'foo': {
               'type': 'string',
                'format': 'base64',
            },
        },
    }

    def test_validate_base64(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'aGVsbG8gd29ybGQ='},
                                   req=FakeRequest()))
        # 'aGVsbG8gd29ybGQ=' is the base64 code of 'hello world'

    def test_validate_base64_fails(self):
        value = 'A random string'
        detail = ("Invalid input for field/attribute foo. "
                  "Value: %s. '%s' is not a 'base64'") % (value, value)
        self.check_validation_error(self.post, body={'foo': value},
                                    expected_detail=detail)


class RegexFormatTestCase(APIValidationTestCase):

    def setUp(self):
        super(RegexFormatTestCase, self).setUp()
        self.controller = RegexFormatFakeController()

    def test_validate_regex(self):
        req = fakes.HTTPRequest.blank("")
        self.assertEqual('Validation succeeded.',
                         self.controller.post(req, body={'foo': u'Myserver'}))

    def test_validate_regex_fails(self):
        value = 1
        req = fakes.HTTPRequest.blank("")
        detail = ("Invalid input for field/attribute foo. "
                  "Value: %s. %s is not a 'regex'") % (value, value)
        self.check_validation_error(self.controller.post, req=req,
                                    body={'foo': value},
                                    expected_detail=detail)
