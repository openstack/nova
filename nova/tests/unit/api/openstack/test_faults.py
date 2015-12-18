# Copyright 2013 IBM Corp.
# Copyright 2010 OpenStack Foundation
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

import mock
from oslo_serialization import jsonutils
import webob
import webob.dec
import webob.exc

import nova.api.openstack
from nova.api.openstack import wsgi
from nova import exception
from nova import test


class TestFaultWrapper(test.NoDBTestCase):
    """Tests covering `nova.api.openstack:FaultWrapper` class."""

    @mock.patch('oslo_i18n.translate')
    @mock.patch('nova.i18n.get_available_languages')
    def test_safe_exception_translated(self, mock_languages, mock_translate):
        def fake_translate(value, locale):
            return "I've been translated!"

        mock_translate.side_effect = fake_translate

        # Create an exception, passing a translatable message with a
        # known value we can test for later.
        safe_exception = exception.NotFound('Should be translated.')
        safe_exception.safe = True
        safe_exception.code = 404

        req = webob.Request.blank('/')

        def raiser(*args, **kwargs):
            raise safe_exception

        wrapper = nova.api.openstack.FaultWrapper(raiser)
        response = req.get_response(wrapper)

        # The text of the exception's message attribute (replaced
        # above with a non-default value) should be passed to
        # translate().
        mock_translate.assert_any_call(u'Should be translated.', None)
        # The return value from translate() should appear in the response.
        self.assertIn("I've been translated!", response.body.decode("UTF-8"))


class TestFaults(test.NoDBTestCase):
    """Tests covering `nova.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        """Remove characters from string which hinder XML equality testing."""
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault_json(self):
        # Test fault serialized to JSON via file-extension and/or header.
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
            response = request.get_response(fault)

            expected = {
                "badRequest": {
                    "message": "scram",
                    "code": 400,
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_413_fault_json(self):
        # Test fault serialized to JSON via file-extension and/or header.
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPRequestEntityTooLarge
            # NOTE(aloga): we intentionally pass an integer for the
            # 'Retry-After' header. It should be then converted to a str
            fault = wsgi.Fault(exc(explanation='sorry',
                        headers={'Retry-After': 4}))
            response = request.get_response(fault)

            expected = {
                "overLimit": {
                    "message": "sorry",
                    "code": 413,
                    "retryAfter": "4",
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_429_fault_json(self):
        # Test fault serialized to JSON via file-extension and/or header.
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPTooManyRequests
            # NOTE(aloga): we intentionally pass an integer for the
            # 'Retry-After' header. It should be then converted to a str
            fault = wsgi.Fault(exc(explanation='sorry',
                        headers={'Retry-After': 4}))
            response = request.get_response(fault)

            expected = {
                "overLimit": {
                    "message": "sorry",
                    "code": 429,
                    "retryAfter": "4",
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_fault_has_status_int(self):
        # Ensure the status_int is set correctly on faults.
        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='what?'))
        self.assertEqual(fault.status_int, 400)
