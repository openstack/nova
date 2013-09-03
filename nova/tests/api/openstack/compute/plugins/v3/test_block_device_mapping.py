# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

import mox
from oslo.config import cfg
from webob import exc

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import block_device_mapping
from nova.api.openstack.compute.plugins.v3 import servers
from nova import block_device
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.image import fake
from nova.tests import matchers

CONF = cfg.CONF


class BlockDeviceMappingTest(test.TestCase):
    def setUp(self):
        super(BlockDeviceMappingTest, self).setUp()

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)

        CONF.set_override('extensions_blacklist', 'os-block-device-mapping',
                          'osapi_v3')
        self.no_volumes_controller = servers.ServersController(
            extension_info=ext_info)
        CONF.set_override('extensions_blacklist', '', 'osapi_v3')

        fake.stub_out_image_service(self.stubs)

        self.bdm = [{
            'no_device': None,
            'source_type': 'volume',
            'destination_type': 'volume',
            'uuid': 'fake',
            'device_name': 'vda',
            'delete_on_termination': False,
        }]

    def _test_create(self, params, no_image=False, override_controller=None):
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'image_ref': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                'flavor_ref': 'http://localhost/123/flavors/3',
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        'path': '/etc/banner.txt',
                        'contents': 'MQ==',
                    },
                ],
            },
        }

        if no_image:
            body['server']['image_ref'] = ''

        body['server'].update(params)

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        req.body = jsonutils.dumps(body)

        if override_controller:
            override_controller.create(req, body).obj['server']
        else:
            self.controller.create(req, body).obj['server']

    def test_create_instance_with_block_device_mapping_disabled(self):
        bdm = [{'device_name': 'foo'}]

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('block_device_mapping', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: bdm}
        self._test_create(params,
                          override_controller=self.no_volumes_controller)

    def test_create_instance_with_volumes_enabled_no_image(self):
        """
        Test that the create will fail if there is no image
        and no bdms supplied in the request
        """
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('image_ref', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        self.assertRaises(exc.HTTPBadRequest,
                          self._test_create, {}, no_image=True)

    def test_create_instance_with_bdms_and_no_image(self):
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertThat(
                block_device.BlockDeviceDict(self.bdm[0]),
                matchers.DictMatches(kwargs['block_device_mapping'][0])
            )
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        self.mox.StubOutWithMock(compute_api.API, '_validate_bdm')
        self.mox.StubOutWithMock(compute_api.API, '_get_bdm_image_metadata')

        compute_api.API._validate_bdm(
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
            mox.IgnoreArg()).AndReturn(True)
        compute_api.API._get_bdm_image_metadata(
            mox.IgnoreArg(), mox.IgnoreArg(), False).AndReturn({})
        self.mox.ReplayAll()

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self._test_create(params, no_image=True)

    def test_create_instance_with_device_name_not_string(self):
        self.bdm[0]['device_name'] = 123
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)

    def test_create_instance_with_device_name_empty(self):
        self.bdm[0]['device_name'] = ''

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)

    def test_create_instance_with_device_name_too_long(self):
        self.bdm[0]['device_name'] = 'a' * 256

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)

    def test_create_instance_with_space_in_device_name(self):
        self.bdm[0]['device_name'] = 'v da'

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertTrue(kwargs['legacy_bdm'])
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)

    def test_create_instance_with_invalid_size(self):
        self.bdm[0]['volume_size'] = 'hello world'

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)

    def test_create_instance_bdm(self):
        bdm = [{
            'source_type': 'volume',
            'device_name': 'fake_dev',
            'uuid': 'fake_vol'
        }]
        bdm_expected = [{
            'source_type': 'volume',
            'device_name': 'fake_dev',
            'volume_id': 'fake_vol'
        }]

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertFalse(kwargs['legacy_bdm'])
            for expected, received in zip(bdm_expected,
                                          kwargs['block_device_mapping']):
                self.assertThat(block_device.BlockDeviceDict(expected),
                                matchers.DictMatches(received))
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)

        params = {block_device_mapping.ATTRIBUTE_NAME: bdm}
        self._test_create(params)

    def test_create_instance_bdm_missing_device_name(self):
        del self.bdm[0]['device_name']

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertFalse(kwargs['legacy_bdm'])
            self.assertNotIn(None,
                             kwargs['block_device_mapping'][0]['device_name'])
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self._test_create(params)

    def test_create_instance_bdm_validation_error(self):
        def _validate(*args, **kwargs):
            raise exception.InvalidBDMFormat(details='Wrong BDM')

        self.stubs.Set(block_device.BlockDeviceDict,
                      '_validate', _validate)

        params = {block_device_mapping.ATTRIBUTE_NAME: self.bdm}
        self.assertRaises(exc.HTTPBadRequest, self._test_create, params)


class TestServerCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerCreateRequestXMLDeserializer, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        servers_controller = servers.ServersController(extension_info=ext_info)
        self.deserializer = servers.CreateDeserializer(servers_controller)

    def test_request_with_block_device_mapping(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v3"
            xmlns:%(alias)s="%(namespace)s"
            name="new-server-test" image_ref="1" flavor_ref="1">
       <%(alias)s:block_device_mapping>
         <mapping uuid="7329b667-50c7-46a6-b913-cb2a09dfeee0"
                  device_name="/dev/vda" source_type="volume"
                  destination_type="volume" delete_on_termination="False" />
         <mapping uuid="f31efb24-34d2-43e1-8b44-316052956a39"
                  device_name="/dev/vdb" source_type="snapshot"
                  destination_type="volume" delete_on_termination="False" />
         <mapping device_name="/dev/vdc" source_type="blank"
                  destination_type="local" />
       </%(alias)s:block_device_mapping>
    </server>""" % {
           'alias': block_device_mapping.ALIAS,
           'namespace': block_device_mapping.BlockDeviceMapping.namespace}

        request = self.deserializer.deserialize(serial_request)

        expected = {'server': {
                'name': 'new-server-test',
                'image_ref': '1',
                'flavor_ref': '1',
                block_device_mapping.ATTRIBUTE_NAME: [
                    {
                        'uuid': '7329b667-50c7-46a6-b913-cb2a09dfeee0',
                        'device_name': '/dev/vda',
                        'source_type': 'volume',
                        'destination_type': 'volume',
                        'delete_on_termination': 'False',
                    },
                    {
                        'uuid': 'f31efb24-34d2-43e1-8b44-316052956a39',
                        'device_name': '/dev/vdb',
                        'source_type': 'snapshot',
                        'destination_type': 'volume',
                        'delete_on_termination': 'False',
                    },
                    {
                        'device_name': '/dev/vdc',
                        'source_type': 'blank',
                        'destination_type': 'local',
                    },
                ]
                }}
        self.assertEquals(expected, request['body'])
