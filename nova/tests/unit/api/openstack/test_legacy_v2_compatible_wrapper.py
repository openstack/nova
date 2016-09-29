# Copyright 2015 Intel Corporation
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

from jsonschema import exceptions as jsonschema_exc
import webob
import webob.dec

import nova.api.openstack
from nova.api.openstack import wsgi
from nova.api.validation import validators
from nova import test


class TestLegacyV2CompatibleWrapper(test.NoDBTestCase):

    def test_filter_out_microversions_request_header(self):
        req = webob.Request.blank('/')
        req.headers[wsgi.API_VERSION_REQUEST_HEADER] = '2.2'

        @webob.dec.wsgify
        def fake_app(req, *args, **kwargs):
            self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, req)
            resp = webob.Response()
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        req.get_response(wrapper)

    def test_filter_out_microversions_response_header(self):
        req = webob.Request.blank('/')

        @webob.dec.wsgify
        def fake_app(req, *args, **kwargs):
            resp = webob.Response()
            resp.status_int = 204
            resp.headers[wsgi.API_VERSION_REQUEST_HEADER] = '2.3'
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        response = req.get_response(wrapper)
        self.assertNotIn(wsgi.API_VERSION_REQUEST_HEADER, response.headers)

    def test_filter_out_microversions_vary_header(self):
        req = webob.Request.blank('/')

        @webob.dec.wsgify
        def fake_app(req, *args, **kwargs):
            resp = webob.Response()
            resp.status_int = 204
            resp.headers['Vary'] = wsgi.API_VERSION_REQUEST_HEADER
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        response = req.get_response(wrapper)
        self.assertNotIn('Vary', response.headers)

    def test_filter_out_microversions_vary_header_with_multi_fields(self):
        req = webob.Request.blank('/')

        @webob.dec.wsgify
        def fake_app(req, *args, **kwargs):
            resp = webob.Response()
            resp.status_int = 204
            resp.headers['Vary'] = '%s, %s, %s' % (
                wsgi.API_VERSION_REQUEST_HEADER, 'FAKE_HEADER1',
                'FAKE_HEADER2')
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        response = req.get_response(wrapper)
        self.assertEqual('FAKE_HEADER1,FAKE_HEADER2',
                         response.headers['Vary'])

    def test_filter_out_microversions_no_vary_header(self):
        req = webob.Request.blank('/')

        @webob.dec.wsgify
        def fake_app(req, *args, **kwargs):
            resp = webob.Response()
            resp.status_int = 204
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        response = req.get_response(wrapper)
        self.assertNotIn('Vary', response.headers)

    def test_legacy_env_variable(self):
        req = webob.Request.blank('/')

        @webob.dec.wsgify(RequestClass=wsgi.Request)
        def fake_app(req, *args, **kwargs):
            self.assertTrue(req.is_legacy_v2())
            resp = webob.Response()
            resp.status_int = 204
            return resp

        wrapper = nova.api.openstack.LegacyV2CompatibleWrapper(fake_app)
        req.get_response(wrapper)


class TestSoftAdditionalPropertiesValidation(test.NoDBTestCase):

    def setUp(self):
        super(TestSoftAdditionalPropertiesValidation, self).setUp()
        self.schema = {
            'type': 'object',
            'properties': {
                'foo': {'type': 'string'},
                'bar': {'type': 'string'}
             },
            'additionalProperties': False}
        self.schema_allow = {
            'type': 'object',
            'properties': {
                'foo': {'type': 'string'},
                'bar': {'type': 'string'}
             },
            'additionalProperties': True}
        self.schema_with_pattern = {
            'type': 'object',
            'patternProperties': {
                '^[a-zA-Z0-9-_:. ]{1,255}$': {'type': 'string'}
            },
            'additionalProperties': False}
        self.schema_allow_with_pattern = {
            'type': 'object',
            'patternProperties': {
                '^[a-zA-Z0-9-_:. ]{1,255}$': {'type': 'string'}
            },
            'additionalProperties': True}

    def test_strip_extra_properties_out_without_extra_props(self):
        validator = validators._SchemaValidator(self.schema).validator
        instance = {'foo': '1'}
        gen = validators._soft_validate_additional_properties(
            validator, False, instance, self.schema)
        self.assertRaises(StopIteration, next, gen)
        self.assertEqual({'foo': '1'}, instance)

    def test_strip_extra_properties_out_with_extra_props(self):
        validator = validators._SchemaValidator(self.schema).validator
        instance = {'foo': '1', 'extra_foo': 'extra'}
        gen = validators._soft_validate_additional_properties(
            validator, False, instance, self.schema)
        self.assertRaises(StopIteration, next, gen)
        self.assertEqual({'foo': '1'}, instance)

    def test_not_strip_extra_properties_out_with_allow_extra_props(self):
        validator = validators._SchemaValidator(self.schema_allow).validator
        instance = {'foo': '1', 'extra_foo': 'extra'}
        gen = validators._soft_validate_additional_properties(
            validator, True, instance, self.schema_allow)
        self.assertRaises(StopIteration, next, gen)
        self.assertEqual({'foo': '1', 'extra_foo': 'extra'}, instance)

    def test_pattern_properties_with_invalid_property_and_allow_extra_props(
            self):
        validator = validators._SchemaValidator(
            self.schema_with_pattern).validator
        instance = {'foo': '1', 'b' * 300: 'extra'}
        gen = validators._soft_validate_additional_properties(
            validator, True, instance, self.schema_with_pattern)
        self.assertRaises(StopIteration, next, gen)

    def test_pattern_properties(self):
        validator = validators._SchemaValidator(
            self.schema_with_pattern).validator
        instance = {'foo': '1'}
        gen = validators._soft_validate_additional_properties(
            validator, False, instance, self.schema_with_pattern)
        self.assertRaises(StopIteration, next, gen)

    def test_pattern_properties_with_invalid_property(self):
        validator = validators._SchemaValidator(
            self.schema_with_pattern).validator
        instance = {'foo': '1', 'b' * 300: 'extra'}
        gen = validators._soft_validate_additional_properties(
            validator, False, instance, self.schema_with_pattern)
        exc = next(gen)
        self.assertIsInstance(exc,
                              jsonschema_exc.ValidationError)
        self.assertIn('was', exc.message)

    def test_pattern_properties_with_multiple_invalid_properties(self):
        validator = validators._SchemaValidator(
            self.schema_with_pattern).validator
        instance = {'foo': '1', 'b' * 300: 'extra', 'c' * 300: 'extra'}
        gen = validators._soft_validate_additional_properties(
            validator, False, instance, self.schema_with_pattern)
        exc = next(gen)
        self.assertIsInstance(exc,
                              jsonschema_exc.ValidationError)
        self.assertIn('were', exc.message)
