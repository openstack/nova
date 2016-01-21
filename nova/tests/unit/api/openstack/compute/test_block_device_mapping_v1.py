# Copyright (c) 2014 IBM Corp.
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
from oslo_config import cfg
from oslo_serialization import jsonutils
from webob import exc

from nova.api.openstack.compute import servers as servers_v21
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake
from nova.tests import uuidsentinel as uuids

CONF = cfg.CONF


class BlockDeviceMappingTestV21(test.TestCase):
    validation_error = exception.ValidationError

    def _setup_controller(self):
        self.controller = servers_v21.ServersController()

    def setUp(self):
        super(BlockDeviceMappingTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        self._setup_controller()
        fake.stub_out_image_service(self)
        self.volume_id = fakes.FAKE_UUID
        self.bdm = [{
            'no_device': None,
            'virtual_name': 'root',
            'volume_id': self.volume_id,
            'device_name': 'vda',
            'delete_on_termination': False
        }]

    def _get_servers_body(self, no_image=False):
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                'flavorRef': 'http://localhost/123/flavors/3',
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }
        if no_image:
            del body['server']['imageRef']
        return body

    @mock.patch.object(compute_api.API, '_validate_bdm')
    def _test_create(self, params, mock_validate_bdm, no_image=False):
        body = self._get_servers_body(no_image)
        body['server'].update(params)

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        req.body = jsonutils.dump_as_bytes(body)

        self.controller.create(req, body=body).obj['server']
        mock_validate_bdm.assert_called_once_with(
            test.MatchType(fakes.FakeRequestContext),
            test.MatchType(objects.Instance),
            test.MatchType(objects.Flavor),
            test.MatchType(objects.BlockDeviceMappingList),
            False)

    def test_create_instance_with_volumes_enabled(self):
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create(params)

    @mock.patch.object(compute_api.API, '_get_bdm_image_metadata')
    def test_create_instance_with_volumes_enabled_and_bdms_no_image(
        self, mock_get_bdm_image_metadata):
        """Test that the create works if there is no image supplied but
        os-volumes extension is enabled and bdms are supplied
        """
        volume = {
            'id': uuids.volume_id,
            'status': 'active',
            'volume_image_metadata':
                {'test_key': 'test_value'}
        }
        mock_get_bdm_image_metadata.return_value = volume
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create(params, no_image=True)
        mock_get_bdm_image_metadata.assert_called_once_with(
            mock.ANY, self.bdm, True)

    @mock.patch.object(compute_api.API, '_get_bdm_image_metadata')
    def test_create_instance_with_imageRef_as_empty_string(
        self, mock_bdm_image_metadata):
        volume = {
            'id': uuids.volume_id,
            'status': 'active',
            'volume_image_metadata':
                {'test_key': 'test_value'}
        }
        mock_bdm_image_metadata.return_value = volume
        params = {'block_device_mapping': self.bdm,
                  'imageRef': ''}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create(params)

    def test_create_instance_with_imageRef_as_full_url(self):
        bdm = [{
            'volume_id': self.volume_id,
            'device_name': 'vda'
        }]
        image_href = ('http://localhost/v2/fake/images/'
                      '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')
        params = {'block_device_mapping': bdm,
                  'imageRef': image_href}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    def test_create_instance_with_non_uuid_imageRef(self):
        bdm = [{
            'volume_id': self.volume_id,
            'device_name': 'vda'
        }]
        params = {'block_device_mapping': bdm,
                  'imageRef': 'bad-format'}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    @mock.patch('nova.compute.api.API._get_bdm_image_metadata')
    def test_create_instance_non_bootable_volume_fails(self, fake_bdm_meta):
        bdm = [{
            'volume_id': self.volume_id,
            'device_name': 'vda'
        }]
        params = {'block_device_mapping': bdm}
        fake_bdm_meta.side_effect = exception.InvalidBDMVolumeNotBootable(id=1)
        self.assertRaises(exc.HTTPBadRequest,
                          self._test_create, params, no_image=True)

    def test_create_instance_with_device_name_not_string(self):
        self.bdm[0]['device_name'] = 123
        old_create = compute_api.API.create
        self.params = {'block_device_mapping': self.bdm}

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, self.params)

    def test_create_instance_with_snapshot_volume_id_none(self):
        old_create = compute_api.API.create
        bdm = [{
            'no_device': None,
            'snapshot_id': None,
            'volume_id': None,
            'device_name': 'vda',
            'delete_on_termination': False
        }]
        self.params = {'block_device_mapping': bdm}

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, self.params)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_bdm_param_not_list(self, mock_create):
        self.params = {'block_device_mapping': '/dev/vdb'}
        self.assertRaises(self.validation_error,
                          self._test_create, self.params)

    def test_create_instance_with_device_name_empty(self):
        self.bdm[0]['device_name'] = ''
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, params)

    def test_create_instance_with_device_name_too_long(self):
        self.bdm[0]['device_name'] = 'a' * 256,
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, params)

    def test_create_instance_with_space_in_device_name(self):
        self.bdm[0]['device_name'] = 'vd a',
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertTrue(kwargs['legacy_bdm'])
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, params)

    def _test_create_instance_with_size_error(self, size):
        bdm = [{'delete_on_termination': True,
                'device_name': 'vda',
                'volume_size': size,
                'volume_id': '11111111-1111-1111-1111-111111111111'}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(self.validation_error,
                          self._test_create, params)

    def test_create_instance_with_invalid_size(self):
        self._test_create_instance_with_size_error("hello world")

    def test_create_instance_with_size_empty_string(self):
        self._test_create_instance_with_size_error('')

    def test_create_instance_with_size_zero(self):
        self._test_create_instance_with_size_error("0")

    def test_create_instance_with_size_greater_than_limit(self):
        self._test_create_instance_with_size_error(db.MAX_INT + 1)

    def test_create_instance_with_bdm_delete_on_termination(self):
        bdm = [{'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'True'},
               {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': True},
               {'device_name': 'foo3', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'False'},
               {'device_name': 'foo4', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': False},
               {'device_name': 'foo5', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': False}]
        expected_bdm = [
            {'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': True},
            {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': True},
            {'device_name': 'foo3', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False},
            {'device_name': 'foo4', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False},
            {'device_name': 'foo5', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(expected_bdm, kwargs['block_device_mapping'])
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create(params)

    def test_create_instance_with_bdm_delete_on_termination_invalid_2nd(self):
        bdm = [{'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'True'},
               {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'invalid'}]

        params = {'block_device_mapping': bdm}
        self.assertRaises(self.validation_error,
                          self._test_create, params)

    def test_create_instance_decide_format_legacy(self):
        bdm = [{'device_name': 'foo1',
                'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': True}]

        expected_legacy_flag = True

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            legacy_bdm = kwargs.get('legacy_bdm', True)
            self.assertEqual(legacy_bdm, expected_legacy_flag)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        self._test_create({})

        params = {'block_device_mapping': bdm}
        self._test_create(params)

    def test_create_instance_both_bdm_formats(self):
        bdm = [{'device_name': 'foo'}]
        bdm_v2 = [{'source_type': 'volume',
                   'uuid': 'fake_vol'}]
        params = {'block_device_mapping': bdm,
                  'block_device_mapping_v2': bdm_v2}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)
