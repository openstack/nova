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
        pattern = "'^(?! )[a-zA-Z0-9. _-]+(?<! )$'"
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
