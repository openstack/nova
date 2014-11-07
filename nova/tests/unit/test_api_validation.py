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

import re

from nova.api import validation
from nova.api.validation import parameter_types
from nova import exception
from nova import test


class APIValidationTestCase(test.TestCase):

    def check_validation_error(self, method, body, expected_detail):
        try:
            method(body=body)
        except exception.ValidationError as ex:
            self.assertEqual(400, ex.kwargs['code'])
            if not re.match(expected_detail, ex.kwargs['detail']):
                self.assertEqual(expected_detail, ex.kwargs['detail'],
                                 'Exception details did not match expected')
        except Exception as ex:
            self.fail('An unexpected exception happens: %s' % ex)
        else:
            self.fail('Any exception does not happen.')


class RequiredDisableTestCase(APIValidationTestCase):

    def setUp(self):
        super(RequiredDisableTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_required_disable(self):
        self.assertEqual(self.post(body={'foo': 1}), 'Validation succeeded.')
        self.assertEqual(self.post(body={'abc': 1}), 'Validation succeeded.')


class RequiredEnableTestCase(APIValidationTestCase):

    def setUp(self):
        super(RequiredEnableTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo']
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_required_enable(self):
        self.assertEqual(self.post(body={'foo': 1}), 'Validation succeeded.')

    def test_validate_required_enable_fails(self):
        detail = "'foo' is a required property"
        self.check_validation_error(self.post, body={'abc': 1},
                                    expected_detail=detail)


class AdditionalPropertiesEnableTestCase(APIValidationTestCase):

    def setUp(self):
        super(AdditionalPropertiesEnableTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo'],
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_additionalProperties_enable(self):
        self.assertEqual(self.post(body={'foo': 1}), 'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': 1, 'ext': 1}),
                         'Validation succeeded.')


class AdditionalPropertiesDisableTestCase(APIValidationTestCase):

    def setUp(self):
        super(AdditionalPropertiesDisableTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo'],
            'additionalProperties': False,
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_additionalProperties_disable(self):
        self.assertEqual(self.post(body={'foo': 1}), 'Validation succeeded.')

    def test_validate_additionalProperties_disable_fails(self):
        detail = "Additional properties are not allowed ('ext' was unexpected)"
        self.check_validation_error(self.post, body={'foo': 1, 'ext': 1},
                                    expected_detail=detail)


class PatternPropertiesTestCase(APIValidationTestCase):

    def setUp(self):
        super(PatternPropertiesTestCase, self).setUp()
        schema = {
            'patternProperties': {
                '^[a-zA-Z0-9]{1,10}$': {
                    'type': 'string'
                },
            },
            'additionalProperties': False,
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_patternProperties(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'bar'}))

    def test_validate_patternProperties_fails(self):
        detail = "Additional properties are not allowed ('__' was unexpected)"
        self.check_validation_error(self.post, body={'__': 'bar'},
                                    expected_detail=detail)

        detail = "Additional properties are not allowed ('' was unexpected)"
        self.check_validation_error(self.post, body={'': 'bar'},
                                    expected_detail=detail)

        detail = ("Additional properties are not allowed ('0123456789a' was"
                  " unexpected)")
        self.check_validation_error(self.post, body={'0123456789a': 'bar'},
                                    expected_detail=detail)

        detail = "expected string or buffer"
        self.check_validation_error(self.post, body={None: 'bar'},
                                    expected_detail=detail)


class StringTestCase(APIValidationTestCase):

    def setUp(self):
        super(StringTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_string(self):
        self.assertEqual(self.post(body={'foo': 'abc'}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0'}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': ''}),
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

    def setUp(self):
        super(StringLengthTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'minLength': 1,
                    'maxLength': 10,
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_string_length(self):
        self.assertEqual(self.post(body={'foo': '0'}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0123456789'}),
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

    def setUp(self):
        super(IntegerTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]+$',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_integer(self):
        self.assertEqual(self.post(body={'foo': 1}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '1'}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '0123456789'}),
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

    def setUp(self):
        super(IntegerRangeTestCase, self).setUp()
        schema = {
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

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_integer_range(self):
        self.assertEqual(self.post(body={'foo': 1}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': 10}),
                         'Validation succeeded.')
        self.assertEqual(self.post(body={'foo': '1'}),
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

    def setUp(self):
        super(BooleanTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.boolean,
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_boolean(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': True}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': False}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'True'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'False'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0'}))

    def test_validate_boolean_fails(self):
        enum_boolean = ("[True, 'True', 'TRUE', 'true', '1',"
                        " False, 'False', 'FALSE', 'false', '0']")

        detail = ("Invalid input for field/attribute foo. Value: bar."
                  " 'bar' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': 'bar'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 2."
                  " '2' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': '2'},
                                    expected_detail=detail)


class HostnameTestCase(APIValidationTestCase):

    def setUp(self):
        super(HostnameTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.hostname,
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_hostname(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost.localdomain.com'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my-host'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my_host'}))

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

    def setUp(self):
        super(HostnameIPaddressTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.hostname_or_ip_address,
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_hostname_or_ip_address(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'localhost.localdomain.com'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my-host'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my_host'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '192.168.10.100'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '2001:db8::9abc'}))

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


class NameTestCase(APIValidationTestCase):

    def setUp(self):
        super(NameTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.name,
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'm1.small'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'my server'}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'a'}))

    def test_validate_name_fails(self):
        pattern = "'^(?! )[a-zA-Z0-9. _-]*(?<! )$'"
        detail = ("Invalid input for field/attribute foo. Value:  ."
                  " ' ' does not match %s") % pattern
        self.check_validation_error(self.post, body={'foo': ' '},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value:  server."
                  " ' server' does not match %s") % pattern
        self.check_validation_error(self.post, body={'foo': ' server'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: server ."
                  " 'server ' does not match %s") % pattern
        self.check_validation_error(self.post, body={'foo': 'server '},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value:  a."
                  " ' a' does not match %s") % pattern
        self.check_validation_error(self.post, body={'foo': ' a'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: a ."
                  " 'a ' does not match %s") % pattern
        self.check_validation_error(self.post, body={'foo': 'a '},
                                    expected_detail=detail)


class TcpUdpPortTestCase(APIValidationTestCase):

    def setUp(self):
        super(TcpUdpPortTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.tcp_udp_port,
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_tcp_udp_port(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1024}))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1024'}))

    def test_validate_tcp_udp_port_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 65536."
                  " 65536(.0)? is greater than the maximum of 65535")
        self.check_validation_error(self.post, body={'foo': 65536},
                                    expected_detail=detail)


class DatetimeTestCase(APIValidationTestCase):

    def setUp(self):
        super(DatetimeTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'date-time',
                },
            },
        }

        @validation.schema(schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_datetime(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '2014-01-14T01:00:00Z'}
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

    def setUp(self):
        super(UuidTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'uuid',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_uuid(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '70a599e0-31e7-49b7-b260-868f441e862b'}
                         ))

    def test_validate_uuid_fails(self):
        detail = ("Invalid input for field/attribute foo."
                  " Value: 70a599e031e749b7b260868f441e862b."
                  " '70a599e031e749b7b260868f441e862b' is not a 'uuid'")
        self.check_validation_error(self.post,
            body={'foo': '70a599e031e749b7b260868f441e862b'},
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

    def setUp(self):
        super(UriTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'uri',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_uri(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': 'http://localhost:8774/v2/servers'}
                         ))
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': 'http://[::1]:8774/v2/servers'}
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

    def setUp(self):
        super(Ipv4TestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'ipv4',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_ipv4(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '192.168.0.100'}
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

    def setUp(self):
        super(Ipv6TestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'ipv6',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_ipv6(self):
        self.assertEqual('Validation succeeded.',
                         self.post(
                         body={'foo': '2001:db8::1234:0:0:9abc'}
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

    def setUp(self):
        super(APIValidationTestCase, self).setUp()
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'base64',
                },
            },
        }

        @validation.schema(request_body_schema=schema)
        def post(body):
            return 'Validation succeeded.'

        self.post = post

    def test_validate_base64(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'aGVsbG8gd29ybGQ='}))
        # 'aGVsbG8gd29ybGQ=' is the base64 code of 'hello world'

    def test_validate_base64_fails(self):
        value = 'A random string'
        detail = ("Invalid input for field/attribute foo. "
                  "Value: %s. '%s' is not a 'base64'") % (value, value)
        self.check_validation_error(self.post, body={'foo': value},
                                    expected_detail=detail)
