# Copyright 2019 OpenStack Foundation
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

from keystoneauth1 import exceptions as ks_exc
from requests.models import Response

from nova.accelerator import cyborg
from nova import context
from nova import exception
from nova.objects import request_spec
from nova import test


class CyborgTestCase(test.NoDBTestCase):
    def setUp(self):
        super(CyborgTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.client = cyborg.get_client(self.context)

    def test_get_client(self):
        # Set up some ksa conf options
        region = 'MyRegion'
        endpoint = 'http://example.com:1234'
        self.flags(group='cyborg',
                   region_name=region,
                   endpoint_override=endpoint)
        ctxt = context.get_admin_context()
        client = cyborg.get_client(ctxt)

        # Dig into the ksa adapter a bit to ensure the conf options got through
        # We don't bother with a thorough test of get_ksa_adapter - that's done
        # elsewhere - this is just sanity-checking that we spelled things right
        # in the conf setup.
        self.assertEqual('accelerator', client._client.service_type)
        self.assertEqual(region, client._client.region_name)
        self.assertEqual(endpoint, client._client.endpoint_override)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_call_cyborg(self, mock_ksa_get):
        mock_ksa_get.return_value = 1  # dummy value
        resp, err_msg = self.client._call_cyborg(
            self.client._client.get, self.client.DEVICE_PROFILE_URL)
        self.assertEqual(resp, 1)
        self.assertIsNone(err_msg)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_call_cyborg_keystone_error(self, mock_ksa_get):
        mock_ksa_get.side_effect = ks_exc.ClientException
        resp, err_msg = self.client._call_cyborg(
            self.client._client.get, self.client.DEVICE_PROFILE_URL)

        self.assertIsNone(resp)
        expected_err = 'Could not communicate with Cyborg.'
        self.assertIn(expected_err, err_msg)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_call_cyborg_bad_response(self, mock_ksa_get):
        mock_ksa_get.return_value = None
        resp, err_msg = self.client._call_cyborg(
            self.client._client.get, self.client.DEVICE_PROFILE_URL)

        self.assertIsNone(resp)
        expected_err = 'Invalid response from Cyborg:'
        self.assertIn(expected_err, err_msg)

    @mock.patch('nova.accelerator.cyborg._CyborgClient._call_cyborg')
    @mock.patch.object(Response, 'json')
    def test_get_device_profile_list(self, mock_resp_json, mock_call_cyborg):
        mock_call_cyborg.return_value = Response(), None
        mock_resp_json.return_value = {'device_profiles': 1}  # dummy value
        ret = self.client._get_device_profile_list(dp_name='mydp')
        self.assertEqual(ret, 1)

    @mock.patch('nova.accelerator.cyborg._CyborgClient._call_cyborg')
    def test_get_device_profile_list_bad_response(self, mock_call_cyborg):
        "If Cyborg cannot be reached or returns bad response, raise exception."
        mock_call_cyborg.return_value = (None, 'Some error')
        self.assertRaises(exception.DeviceProfileError,
                          self.client._get_device_profile_list,
                          dp_name='mydp')

    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                '_get_device_profile_list')
    def test_get_device_profile_groups(self, mock_get_dp_list):
        mock_get_dp_list.return_value = [{
            "groups": [{
                    "resources:FPGA": "1",
                    "trait:CUSTOM_FPGA_CARD": "required"
            }],
            "name": "mydp",
            "uuid": "307076c2-5aed-4f72-81e8-1b42f9aa2ec6"
        }]
        rg = request_spec.RequestGroup(requester_id='device_profile_0')
        rg.add_resource(rclass='FPGA', amount='1')
        rg.add_trait(trait_name='CUSTOM_FPGA_CARD', trait_type='required')
        expected_groups = [rg]

        actual_groups = self.client.get_device_profile_groups('mydp')
        self.assertEqual(len(expected_groups), len(actual_groups))
        self.assertEqual(expected_groups[0].__dict__,
                         actual_groups[0].__dict__)

    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                '_get_device_profile_list')
    def test_get_device_profile_groups_no_dp(self, mock_get_dp_list):
        # If the return value has no device profiles, raise exception
        mock_get_dp_list.return_value = None
        self.assertRaises(exception.DeviceProfileError,
                          self.client.get_device_profile_groups,
                          dp_name='mydp')

    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                '_get_device_profile_list')
    def test_get_device_profile_groups_many_dp(self, mock_get_dp_list):
        # If the returned list has more than one dp, raise exception
        mock_get_dp_list.return_value = [1, 2]
        self.assertRaises(exception.DeviceProfileError,
                          self.client.get_device_profile_groups,
                          dp_name='mydp')
