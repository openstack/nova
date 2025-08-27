# Copyright 2013 Josh Durgin
# Copyright 2013 Red Hat, Inc.
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

import datetime
from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import volumes as volumes_v21
from nova.compute import flavors
import nova.conf
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.volume import cinder

CONF = nova.conf.CONF


class BootFromVolumeTest(test.TestCase):

    def setUp(self):
        super().setUp()
        self.stub_out('nova.compute.api.API.create',
                      self._get_fake_compute_api_create())
        fakes.stub_out_nw_api(self)
        self._block_device_mapping_seen = None
        self._legacy_bdm_seen = True

    def _get_fake_compute_api_create(self):
        def _fake_compute_api_create(cls, context, flavor,
                                    image_href, **kwargs):
            self._block_device_mapping_seen = kwargs.get(
                'block_device_mapping')
            self._legacy_bdm_seen = kwargs.get('legacy_bdm')

            flavor = flavors.get_flavor_by_flavor_id(2)
            resv_id = None
            return ([{'id': 1,
                      'display_name': 'test_server',
                      'uuid': uuids.server,
                      'flavor': flavor,
                      'access_ip_v4': '1.2.3.4',
                      'access_ip_v6': 'fead::1234',
                      'image_ref': uuids.image,
                      'user_id': 'fake',
                      'project_id': fakes.FAKE_PROJECT_ID,
                      'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                      'updated_at': datetime.datetime(2010, 11, 11, 11, 0, 0),
                      'progress': 0,
                      'fixed_ips': []
                      }], resv_id)
        return _fake_compute_api_create

    def test_create_root_volume(self):
        body = dict(server=dict(
                name='test_server', imageRef=uuids.image,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping=[dict(
                        volume_id='ca9fe3f5-cede-43cb-8050-1672acabe348',
                        device_name='/dev/vda',
                        delete_on_termination=False,
                        )]
                ))
        # FIXME(stephenfin): Use /servers instead?
        req = fakes.HTTPRequest.blank('/v2.1/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(uuids.server, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertTrue(self._legacy_bdm_seen)
        self.assertEqual('ca9fe3f5-cede-43cb-8050-1672acabe348',
                         self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])

    def test_create_root_volume_bdm_v2(self):
        body = dict(server=dict(
                name='test_server', imageRef=uuids.image,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping_v2=[dict(
                        source_type='volume',
                        uuid='1',
                        device_name='/dev/vda',
                        boot_index=0,
                        delete_on_termination=False,
                        )]
                ))
        # FIXME(stephenfin): Use /servers instead?
        req = fakes.HTTPRequest.blank('/v2.1/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(uuids.server, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertFalse(self._legacy_bdm_seen)
        self.assertEqual('1', self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual(0, self._block_device_mapping_seen[0]['boot_index'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])


class VolumeApiTestV21(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        fakes.stub_out_networking(self)

        self.stub_out(
            'nova.volume.cinder.API.create', fakes.stub_volume_create)
        self.stub_out(
            'nova.volume.cinder.API.delete', fakes.stub_volume_delete)
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        self.stub_out(
            'nova.volume.cinder.API.get_all', fakes.stub_volume_get_all)

        self.controller = volumes_v21.VolumeController()
        self.req = fakes.HTTPRequest.blank('')

    def test_volume_create(self):
        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "dublin"}
        body = {"volume": vol}
        resp = self.controller.create(self.req, body=body).obj

        self.assertIn('volume', resp)
        self.assertEqual(vol['size'], resp['volume']['size'])
        self.assertEqual(vol['display_name'], resp['volume']['displayName'])
        self.assertEqual(
            vol['display_description'], resp['volume']['displayDescription'])
        self.assertEqual(
            vol['availability_zone'], resp['volume']['availabilityZone'])

    @mock.patch.object(cinder.API, 'create')
    def _test_volume_translate_exception(self, cinder_exc, api_exc,
                                         mock_create):
        """Tests that cinder exceptions are correctly translated"""
        mock_create.side_effect = cinder_exc

        vol = {"size": '10',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "dublin"}
        body = {"volume": vol}

        self.assertRaises(api_exc,
                          self.controller.create, self.req,
                          body=body)
        mock_create.assert_called_once_with(
            mock.ANY, '10', 'Volume Test Name',
            'Volume Test Desc', availability_zone='dublin',
            metadata=None, snapshot=None, volume_type=None)

    @mock.patch.object(cinder.API, 'get_snapshot')
    @mock.patch.object(cinder.API, 'create')
    def test_volume_create_bad_snapshot_id(self, mock_create, mock_get):
        vol = {"snapshot_id": '1', "size": 10}
        body = {"volume": vol}
        mock_get.side_effect = exception.SnapshotNotFound(snapshot_id='1')

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, self.req,
                          body=body)

    def test_volume_create_bad_input(self):
        self._test_volume_translate_exception(
            exception.InvalidInput(reason='fake'), webob.exc.HTTPBadRequest)

    def test_volume_create_bad_quota(self):
        self._test_volume_translate_exception(
            exception.OverQuota(overs='fake'), webob.exc.HTTPForbidden)

    def _bad_request_create(self, body):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/os-volumes' % (fakes.FAKE_PROJECT_ID))
        req.method = 'POST'

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_volume_create_no_body(self):
        self._bad_request_create(body=None)

    def test_volume_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._bad_request_create(body=body)

    def test_volume_create_malformed_entity(self):
        body = {'volume': 'string'}
        self._bad_request_create(body=body)

    def test_volume_index(self):
        self.controller.index(self.req)

    def test_volume_detail(self):
        self.controller.detail(self.req)

    def test_volume_show(self):
        self.controller.show(self.req, uuids.volume)

    @mock.patch.object(cinder.API, 'get',
                       side_effect=exception.VolumeNotFound(
                           volume_id=uuids.volume))
    def test_volume_show_no_volume(self, mock_get):
        exc = self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.show,
            self.req, uuids.volume)
        self.assertIn('Volume %s could not be found.' % uuids.volume, str(exc))
        mock_get.assert_called_once()

    def test_volume_delete(self):
        self.controller.delete(self.req, uuids.volume)

    @mock.patch.object(cinder.API, 'delete',
                       side_effect=exception.VolumeNotFound(
                           volume_id=uuids.volume))
    def test_volume_delete_no_volume(self, mock_delete):
        exc = self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.delete,
            self.req, uuids.volume)
        self.assertIn('Volume %s could not be found.' % uuids.volume, str(exc))
        mock_delete.assert_called_once()

    def _test_list_with_invalid_filter(self, url):
        req = fakes.HTTPRequest.blank('/os-volumes' + url)
        self.assertRaises(
            exception.ValidationError, self.controller.index, req)

    def test_list_with_invalid_non_int_limit(self):
        self._test_list_with_invalid_filter('?limit=-9')

    def test_list_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('?limit=abc')

    def test_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('?limit=1&limit=abc')

    def test_list_with_invalid_non_int_offset(self):
        self._test_list_with_invalid_filter('?offset=-9')

    def test_list_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('?offset=abc')

    def test_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('?offset=1&offset=abc')

    def _test_list_detail_with_invalid_filter(self, url):
        req = fakes.HTTPRequest.blank('/os-volumes/detail' + url)
        self.assertRaises(
            exception.ValidationError, self.controller.detail, req)

    def test_detail_list_with_invalid_non_int_limit(self):
        self._test_list_detail_with_invalid_filter('?limit=-9')

    def test_detail_list_with_invalid_string_limit(self):
        self._test_list_detail_with_invalid_filter('?limit=abc')

    def test_detail_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_detail_with_invalid_filter('?limit=1&limit=abc')

    def test_detail_list_with_invalid_non_int_offset(self):
        self._test_list_detail_with_invalid_filter('?offset=-9')

    def test_detail_list_with_invalid_string_offset(self):
        self._test_list_detail_with_invalid_filter('?offset=abc')

    def test_detail_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_detail_with_invalid_filter('?offset=1&offset=abc')

    def _test_list_duplicate_query_parameters_validation(self, url):
        params = {'limit': 1, 'offset': 1}
        for param, value in params.items():
            req = fakes.HTTPRequest.blank(
                url + '?%s=%s&%s=%s' % (param, value, param, value))
            self.controller.index(req)

    def test_list_duplicate_query_parameters_validation(self):
        params = {'limit': 1, 'offset': 1}
        for p, v in params.items():
            req = fakes.HTTPRequest.blank(f'/os-volumes?{p}={v}&{p}={v}')
            self.controller.index(req)

    def test_detail_list_duplicate_query_parameters_validation(self):
        params = {'limit': 1, 'offset': 1}
        for p, v in params.items():
            req = fakes.HTTPRequest.blank(
                f'/os-volumes/detail?{p}={v}&{p}={v}')
            self.controller.detail(req)

    def test_list_with_additional_filter(self):
        req = fakes.HTTPRequest.blank(
            '/os-volumes?limit=1&offset=1&additional=something')
        self.controller.index(req)

    def test_detail_list_with_additional_filter(self):
        req = fakes.HTTPRequest.blank(
            '/os-volumes/detail?limit=1&offset=1&additional=something')
        self.controller.index(req)


class TestVolumesAPIDeprecation(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.controller = volumes_v21.VolumeController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, uuids.volume)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, uuids.volume)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.detail, self.req)
