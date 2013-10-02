# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from xml.dom import minidom

import mock
import webob
import webob.dec
import webob.exc

import nova.api.openstack
from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova import exception
from nova.openstack.common import gettextutils
from nova.openstack.common import jsonutils
from nova import test


class TestFaultWrapper(test.NoDBTestCase):
    """Tests covering `nova.api.openstack:FaultWrapper` class."""

    @mock.patch('nova.openstack.common.gettextutils.get_localized_message')
    def test_safe_exception_translated(self, mock_get_localized):
        msg = gettextutils.Message('Should be translated.', 'nova')
        safe_exception = exception.NotFound()
        safe_exception.msg_fmt = msg
        safe_exception.safe = True
        safe_exception.code = 404

        req = webob.Request.blank('/')

        def fake_translate(mesg, locale):
            if str(mesg) == "Should be translated.":
                return "I've been translated!"
            return mesg

        mock_get_localized.side_effect = fake_translate

        def raiser(*args, **kwargs):
            raise safe_exception

        wrapper = nova.api.openstack.FaultWrapper(raiser)
        response = req.get_response(wrapper)

        self.assertIn("I've been translated!", unicode(response.body))
        mock_get_localized.assert_any_call(
                u'Should be translated.', None)


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

    def test_raise(self):
        # Ensure the ability to raise :class:`Fault` in WSGI-ified methods.
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 404)
        self.assertTrue('whut?' in resp.body)

    def test_raise_403(self):
        # Ensure the ability to raise :class:`Fault` in WSGI-ified methods.
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPForbidden(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 403)
        self.assertTrue('resizeNotAllowed' not in resp.body)
        self.assertTrue('forbidden' in resp.body)

    def test_raise_localize_explanation(self):
        msgid = "String with params: %s"
        params = ('blah', )
        lazy_gettext = gettextutils._
        expl = lazy_gettext(msgid) % params

        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation=expl))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 404)
        self.assertTrue((msgid % params) in resp.body)

    def test_fault_has_status_int(self):
        # Ensure the status_int is set correctly on faults.
        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='what?'))
        self.assertEqual(fault.status_int, 400)

    def test_xml_serializer(self):
        # Ensure that a v1.1 request responds with a v1.1 xmlns.
        request = webob.Request.blank('/v1.1',
                                      headers={"Accept": "application/xml"})

        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
        response = request.get_response(fault)

        self.assertTrue(common.XML_NS_V11 in response.body)
        self.assertEqual(response.content_type, "application/xml")
        self.assertEqual(response.status_int, 400)


class FaultsXMLSerializationTestV11(test.NoDBTestCase):
    """Tests covering `nova.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault(self):
        metadata = {'attributes': {"badRequest": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V11)

        fixture = {
            "badRequest": {
                "message": "scram",
                "code": 400,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <badRequest code="400" xmlns="%s">
                    <message>scram</message>
                </badRequest>
            """) % common.XML_NS_V11)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_413_fault(self):
        metadata = {'attributes': {"overLimit": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V11)

        fixture = {
            "overLimit": {
                "message": "sorry",
                "code": 413,
                "retryAfter": 4,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <overLimit code="413" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """) % common.XML_NS_V11)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_429_fault(self):
        metadata = {'attributes': {"overLimit": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V11)

        fixture = {
            "overLimit": {
                "message": "sorry",
                "code": 429,
                "retryAfter": 4,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <overLimit code="429" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """) % common.XML_NS_V11)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_404_fault(self):
        metadata = {'attributes': {"itemNotFound": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V11)

        fixture = {
            "itemNotFound": {
                "message": "sorry",
                "code": 404,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <itemNotFound code="404" xmlns="%s">
                    <message>sorry</message>
                </itemNotFound>
            """) % common.XML_NS_V11)

        self.assertEqual(expected.toxml(), actual.toxml())
