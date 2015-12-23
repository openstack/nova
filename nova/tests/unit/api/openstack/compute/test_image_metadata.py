# Copyright 2011 OpenStack Foundation
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

import copy

import mock
from oslo_serialization import jsonutils
import webob

from nova.api.openstack.compute import image_metadata as image_metadata_v21
from nova.api.openstack.compute.legacy_v2 import image_metadata
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import image_fixtures

IMAGE_FIXTURES = image_fixtures.get_image_fixtures()
CHK_QUOTA_STR = 'nova.api.openstack.common.check_img_metadata_properties_quota'


def get_image_123():
    return copy.deepcopy(IMAGE_FIXTURES)[0]


class ImageMetaDataTestV21(test.NoDBTestCase):
    controller_class = image_metadata_v21.ImageMetadataController
    invalid_request = exception.ValidationError

    def setUp(self):
        super(ImageMetaDataTestV21, self).setUp()
        self.controller = self.controller_class()

    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_index(self, get_all_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        res_dict = self.controller.index(req, '123')
        expected = {'metadata': {'key1': 'value1'}}
        self.assertEqual(res_dict, expected)
        get_all_mocked.assert_called_once_with(mock.ANY, '123')

    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_show(self, get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        res_dict = self.controller.show(req, '123', 'key1')
        self.assertIn('meta', res_dict)
        self.assertEqual(len(res_dict['meta']), 1)
        self.assertEqual('value1', res_dict['meta']['key1'])
        get_mocked.assert_called_once_with(mock.ANY, '123')

    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_show_not_found(self, _get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key9')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, '123', 'key9')

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id='100'))
    def test_show_image_not_found(self, _get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, '100', 'key9')

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_create(self, get_mocked, update_mocked, quota_mocked):
        mock_result = copy.deepcopy(get_image_123())
        mock_result['properties']['key7'] = 'value7'
        update_mocked.return_value = mock_result
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'POST'
        body = {"metadata": {"key7": "value7"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, '123', body=body)
        get_mocked.assert_called_once_with(mock.ANY, '123')
        expected = copy.deepcopy(get_image_123())
        expected['properties'] = {
            'key1': 'value1',  # existing meta
            'key7': 'value7'  # new meta
        }
        quota_mocked.assert_called_once_with(mock.ANY, expected["properties"])
        update_mocked.assert_called_once_with(mock.ANY, '123', expected,
                                              data=None, purge_props=True)

        expected_output = {'metadata': {'key1': 'value1', 'key7': 'value7'}}
        self.assertEqual(expected_output, res)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id='100'))
    def test_create_image_not_found(self, _get_mocked, update_mocked,
                                    quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata')
        req.method = 'POST'
        body = {"metadata": {"key7": "value7"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, req, '100', body=body)
        self.assertFalse(quota_mocked.called)
        self.assertFalse(update_mocked.called)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_update_all(self, get_mocked, update_mocked, quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'PUT'
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.update_all(req, '123', body=body)
        get_mocked.assert_called_once_with(mock.ANY, '123')
        expected = copy.deepcopy(get_image_123())
        expected['properties'] = {
            'key9': 'value9'  # replace meta
        }
        quota_mocked.assert_called_once_with(mock.ANY, expected["properties"])
        update_mocked.assert_called_once_with(mock.ANY, '123', expected,
                                              data=None, purge_props=True)

        expected_output = {'metadata': {'key9': 'value9'}}
        self.assertEqual(expected_output, res)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id='100'))
    def test_update_all_image_not_found(self, _get_mocked, quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata')
        req.method = 'PUT'
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update_all, req, '100', body=body)
        self.assertFalse(quota_mocked.called)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_update_item(self, _get_mocked, update_mocked, quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "zz"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.update(req, '123', 'key1', body=body)
        expected = copy.deepcopy(get_image_123())
        expected['properties'] = {
            'key1': 'zz'  # changed meta
        }
        quota_mocked.assert_called_once_with(mock.ANY, expected["properties"])
        update_mocked.assert_called_once_with(mock.ANY, '123', expected,
                                              data=None, purge_props=True)

        expected_output = {'meta': {'key1': 'zz'}}
        self.assertEqual(res, expected_output)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id='100'))
    def test_update_item_image_not_found(self, _get_mocked, quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "zz"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update, req, '100', 'key1',
                          body=body)
        self.assertFalse(quota_mocked.called)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get')
    def test_update_item_bad_body(self, get_mocked, update_mocked,
                                  quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"key1": "zz"}
        req.body = b''
        req.headers["content-type"] = "application/json"

        self.assertRaises(self.invalid_request,
                          self.controller.update, req, '123', 'key1',
                          body=body)
        self.assertFalse(get_mocked.called)
        self.assertFalse(quota_mocked.called)
        self.assertFalse(update_mocked.called)

    @mock.patch(CHK_QUOTA_STR,
                side_effect=webob.exc.HTTPBadRequest())
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get')
    def test_update_item_too_many_keys(self, get_mocked, update_mocked,
                                       _quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"foo": "bar"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '123', 'key1',
                          body=body)
        self.assertFalse(get_mocked.called)
        self.assertFalse(update_mocked.called)

    @mock.patch(CHK_QUOTA_STR)
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_update_item_body_uri_mismatch(self, _get_mocked, update_mocked,
                                           quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '123', 'bad',
                          body=body)
        self.assertFalse(quota_mocked.called)
        self.assertFalse(update_mocked.called)

    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_delete(self, _get_mocked, update_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'DELETE'
        res = self.controller.delete(req, '123', 'key1')
        expected = copy.deepcopy(get_image_123())
        expected['properties'] = {}
        update_mocked.assert_called_once_with(mock.ANY, '123', expected,
                                             data=None, purge_props=True)

        self.assertIsNone(res)

    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_delete_not_found(self, _get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/blah')
        req.method = 'DELETE'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, '123', 'blah')

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id='100'))
    def test_delete_image_not_found(self, _get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        req.method = 'DELETE'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, '100', 'key1')

    @mock.patch(CHK_QUOTA_STR,
                side_effect=webob.exc.HTTPForbidden(explanation=''))
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_too_many_metadata_items_on_create(self, _get_mocked,
                                               update_mocked, _quota_mocked):
        body = {"metadata": {"foo": "bar"}}
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create, req, '123', body=body)
        self.assertFalse(update_mocked.called)

    @mock.patch(CHK_QUOTA_STR,
                side_effect=webob.exc.HTTPForbidden(explanation=''))
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_too_many_metadata_items_on_put(self, _get_mocked,
                                            update_mocked, _quota_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/blah')
        req.method = 'PUT'
        body = {"meta": {"blah": "blah", "blah1": "blah1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(self.invalid_request,
                          self.controller.update, req, '123', 'blah',
                          body=body)
        self.assertFalse(update_mocked.called)

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotAuthorized(image_id='123'))
    def test_image_not_authorized_update(self, _get_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, req, '123', 'key1',
                          body=body)

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotAuthorized(image_id='123'))
    def test_image_not_authorized_update_all(self, _get_mocked):
        image_id = 131
        # see nova.tests.unit.api.openstack.fakes:_make_image_fixtures

        req = fakes.HTTPRequest.blank('/v2/fake/images/%s/metadata/key1'
                                      % image_id)
        req.method = 'PUT'
        body = {"metadata": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update_all, req, image_id,
                          body=body)

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotAuthorized(image_id='123'))
    def test_image_not_authorized_create(self, _get_mocked):
        image_id = 131
        # see nova.tests.unit.api.openstack.fakes:_make_image_fixtures

        req = fakes.HTTPRequest.blank('/v2/fake/images/%s/metadata/key1'
                                      % image_id)
        req.method = 'POST'
        body = {"metadata": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create, req, image_id,
                          body=body)


class ImageMetaDataTestV2(ImageMetaDataTestV21):
    controller_class = image_metadata.Controller
    invalid_request = webob.exc.HTTPBadRequest

    # NOTE(cyeoh): This duplicate unittest is necessary for a race condition
    # with the V21 unittests. It's mock issue.
    @mock.patch('nova.image.api.API.update')
    @mock.patch('nova.image.api.API.get', return_value=get_image_123())
    def test_delete(self, _get_mocked, update_mocked):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'DELETE'
        res = self.controller.delete(req, '123', 'key1')
        expected = copy.deepcopy(get_image_123())
        expected['properties'] = {}
        update_mocked.assert_called_once_with(mock.ANY, '123', expected,
                                             data=None, purge_props=True)

        self.assertIsNone(res)
