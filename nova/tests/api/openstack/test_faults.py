# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import json

import webob
import webob.dec
import webob.exc

from nova import test
from nova.api.openstack import common
from nova.api.openstack import faults


class TestFaults(test.TestCase):
    """Tests covering `nova.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        """Remove characters from string which hinder XML equality testing."""
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault_xml(self):
        """Test fault serialized to XML via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.xml'),
            webob.Request.blank('/', headers={"Accept": "application/xml"}),
        ]

        for request in requests:
            fault = faults.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
            response = request.get_response(fault)

            expected = self._prepare_xml("""
                <badRequest code="400" xmlns="%s">
                    <message>scram</message>
                </badRequest>
            """ % common.XML_NS_V10)
            actual = self._prepare_xml(response.body)

            self.assertEqual(response.content_type, "application/xml")
            self.assertEqual(expected, actual)

    def test_400_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            fault = faults.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
            response = request.get_response(fault)

            expected = {
                "badRequest": {
                    "message": "scram",
                    "code": 400,
                },
            }
            actual = json.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_413_fault_xml(self):
        requests = [
            webob.Request.blank('/.xml'),
            webob.Request.blank('/', headers={"Accept": "application/xml"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPRequestEntityTooLarge
            fault = faults.Fault(exc(explanation='sorry',
                        headers={'Retry-After': 4}))
            response = request.get_response(fault)

            expected = self._prepare_xml("""
                <overLimit code="413" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """ % common.XML_NS_V10)
            actual = self._prepare_xml(response.body)

            self.assertEqual(expected, actual)
            self.assertEqual(response.content_type, "application/xml")
            self.assertEqual(response.headers['Retry-After'], 4)

    def test_413_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPRequestEntityTooLarge
            fault = faults.Fault(exc(explanation='sorry',
                        headers={'Retry-After': 4}))
            response = request.get_response(fault)

            expected = {
                "overLimit": {
                    "message": "sorry",
                    "code": 413,
                    "retryAfter": 4,
                },
            }
            actual = json.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_raise(self):
        """Ensure the ability to raise `Fault`s in WSGI-ified methods."""
        @webob.dec.wsgify
        def raiser(req):
            raise faults.Fault(webob.exc.HTTPNotFound(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 404)
        self.assertTrue('whut?' in resp.body)
