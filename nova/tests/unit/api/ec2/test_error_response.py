#
# Copyright 2013 - Red Hat, Inc.
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
#

"""
Unit tests for EC2 error responses.
"""

from lxml import etree

from nova.api import ec2
from nova import context
from nova import test
from nova import wsgi


class TestClientExceptionEC2(Exception):
    ec2_code = 'ClientException.Test'
    message = "Test Client Exception."
    code = 400


class TestServerExceptionEC2(Exception):
    ec2_code = 'ServerException.Test'
    message = "Test Server Exception."
    code = 500


class Ec2ErrorResponseTestCase(test.NoDBTestCase):
    """Test EC2 error responses.

    This deals mostly with api/ec2/__init__.py code, especially
    the ec2_error_ex helper.
    """
    def setUp(self):
        super(Ec2ErrorResponseTestCase, self).setUp()
        self.context = context.RequestContext('test_user_id',
                'test_project_id')
        self.req = wsgi.Request.blank('/test')
        self.req.environ['nova.context'] = self.context

    def _validate_ec2_error(self, response, http_status, ec2_code, msg=None,
                            unknown_msg=False):
        self.assertEqual(response.status_code, http_status,
                         'Expected HTTP status %s' % http_status)
        root_e = etree.XML(response.body)
        self.assertEqual(root_e.tag, 'Response',
                         "Top element must be Response.")
        errors_e = root_e.find('Errors')
        self.assertEqual(len(errors_e), 1,
                         "Expected exactly one Error element in Errors.")
        error_e = errors_e[0]
        self.assertEqual(error_e.tag, 'Error',
                         "Expected Error element.")
        # Code
        code_e = error_e.find('Code')
        self.assertIsNotNone(code_e, "Code element must be present.")
        self.assertEqual(code_e.text, ec2_code)
        # Message
        if msg or unknown_msg:
            message_e = error_e.find('Message')
            self.assertIsNotNone(code_e, "Message element must be present.")
            if msg:
                self.assertEqual(message_e.text, msg)
            elif unknown_msg:
                self.assertEqual(message_e.text, "Unknown error occurred.",
                                 "Error message should be anonymous.")
        # RequestID
        requestid_e = root_e.find('RequestID')
        self.assertIsNotNone(requestid_e,
                             'RequestID element should be present.')
        self.assertEqual(requestid_e.text, self.context.request_id)

    def test_exception_ec2_4xx(self):
        """Test response to EC2 exception with code = 400."""
        msg = "Test client failure."
        err = ec2.ec2_error_ex(TestClientExceptionEC2(msg), self.req)
        self._validate_ec2_error(err, TestClientExceptionEC2.code,
                                 TestClientExceptionEC2.ec2_code, msg)

    def test_exception_ec2_5xx(self):
        """Test response to EC2 exception with code = 500.

        Expected errors are treated as client ones even with 5xx code.
        """
        msg = "Test client failure with 5xx error code."
        err = ec2.ec2_error_ex(TestServerExceptionEC2(msg), self.req)
        self._validate_ec2_error(err, 400, TestServerExceptionEC2.ec2_code,
                                 msg)

    def test_unexpected_exception_ec2_4xx(self):
        """Test response to unexpected EC2 exception with code = 400."""
        msg = "Test unexpected client failure."
        err = ec2.ec2_error_ex(TestClientExceptionEC2(msg), self.req,
                           unexpected=True)
        self._validate_ec2_error(err, TestClientExceptionEC2.code,
                                 TestClientExceptionEC2.ec2_code, msg)

    def test_unexpected_exception_ec2_5xx(self):
        """Test response to unexpected EC2 exception with code = 500.

        Server exception messages (with code >= 500 or without code) should
        be filtered as they might contain sensitive information.
        """
        msg = "Test server failure."
        err = ec2.ec2_error_ex(TestServerExceptionEC2(msg), self.req,
                           unexpected=True)
        self._validate_ec2_error(err, TestServerExceptionEC2.code,
                                 TestServerExceptionEC2.ec2_code,
                                 unknown_msg=True)

    def test_unexpected_exception_builtin(self):
        """Test response to builtin unexpected exception.

        Server exception messages (with code >= 500 or without code) should
        be filtered as they might contain sensitive information.
        """
        msg = "Test server failure."
        err = ec2.ec2_error_ex(RuntimeError(msg), self.req, unexpected=True)
        self._validate_ec2_error(err, 500, 'RuntimeError', unknown_msg=True)
