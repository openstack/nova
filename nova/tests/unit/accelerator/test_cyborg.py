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

import itertools
import mock

from keystoneauth1 import exceptions as ks_exc
from requests.models import Response

from oslo_serialization import jsonutils

from nova.accelerator import cyborg
from nova import context
from nova import exception
from nova.objects import request_spec
from nova import test
from nova.tests.unit import fake_requests


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

    def _get_arqs_and_request_groups(self):
        arq_common = {
            # All ARQs for an instance have same device profile name.
            "device_profile_name": "noprog-dp",
            "device_rp_uuid": "",
            "hostname": "",
            "instance_uuid": "",
            "state": "Initial",
        }
        arq_variants = [
            {"device_profile_group_id": 0,
             "uuid": "edbba496-3cc8-4256-94ca-dfe3413348eb"},
            {"device_profile_group_id": 1,
             "uuid": "20125bcb-9f55-4e13-8e8c-3fee30e54cca"},
        ]
        arqs = [dict(arq_common, **variant) for variant in arq_variants]
        rg_rp_map = {
            'device_profile_0': ['c532cf11-02ed-4b03-9dd8-3e9a454131dc'],
            'device_profile_1': ['2c332d7b-daaf-4726-a80d-ecf5212da4b8'],
        }
        return arqs, rg_rp_map

    def _get_bound_arqs(self):
        arqs, rg_rp_map = self._get_arqs_and_request_groups()
        common = {
            'host_name': 'myhost',
            'instance_uuid': '15d3acf8-df76-400b-bfc9-484a5208daa1',
        }
        bindings = {
           arqs[0]['uuid']: dict(
               common, device_rp_uuid=rg_rp_map['device_profile_0'][0]),
           arqs[1]['uuid']: dict(
               common, device_rp_uuid=rg_rp_map['device_profile_1'][0]),
        }
        bound_arq_common = {
            "attach_handle_info": {
                "bus": "01",
                "device": "00",
                "domain": "0000",
                "function": "0"  # will vary function ID later
            },
            "attach_handle_type": "PCI",
            "state": "Bound",
            # Devic eprofile name is common to all bound ARQs
            "device_profile_name": arqs[0]["device_profile_name"],
            **common
        }
        bound_arqs = [
            {'uuid': arq['uuid'],
             'device_profile_group_id': arq['device_profile_group_id'],
             'device_rp_uuid': bindings[arq['uuid']]['device_rp_uuid'],
             **bound_arq_common} for arq in arqs]
        for index, bound_arq in enumerate(bound_arqs):
            bound_arq['attach_handle_info']['function'] = index  # fix func ID
        return bindings, bound_arqs

    @mock.patch('keystoneauth1.adapter.Adapter.post')
    def test_create_arqs_failure(self, mock_cyborg_post):
        # If Cyborg returns invalid response, raise exception.
        mock_cyborg_post.return_value = None
        self.assertRaises(exception.AcceleratorRequestOpFailed,
                          self.client._create_arqs,
                          dp_name='mydp')

    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                '_create_arqs')
    def test_create_arq_and_match_rps(self, mock_create_arqs):
        # Happy path
        arqs, rg_rp_map = self._get_arqs_and_request_groups()
        dp_name = arqs[0]["device_profile_name"]

        mock_create_arqs.return_value = arqs

        ret_arqs = self.client.create_arqs_and_match_resource_providers(
            dp_name, rg_rp_map)

        # Each value in rg_rp_map is a list. We merge them into a single list.
        expected_rp_uuids = sorted(list(
            itertools.chain.from_iterable(rg_rp_map.values())))
        ret_rp_uuids = sorted([arq['device_rp_uuid'] for arq in ret_arqs])
        self.assertEqual(expected_rp_uuids, ret_rp_uuids)

    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                '_create_arqs')
    def test_create_arq_and_match_rps_exception(self, mock_create_arqs):
        # If Cyborg response does not contain ARQs, raise
        arqs, rg_rp_map = self._get_arqs_and_request_groups()
        dp_name = arqs[0]["device_profile_name"]

        mock_create_arqs.return_value = None
        self.assertRaises(
            exception.AcceleratorRequestOpFailed,
            self.client.create_arqs_and_match_resource_providers,
            dp_name, rg_rp_map)

    @mock.patch('keystoneauth1.adapter.Adapter.patch')
    def test_bind_arqs(self, mock_cyborg_patch):
        bindings, bound_arqs = self._get_bound_arqs()
        arq_uuid = bound_arqs[0]['uuid']

        patch_list = {}
        for arq_uuid, binding in bindings.items():
            patch = [{"path": "/" + field,
                      "op": "add",
                      "value": value
                     } for field, value in binding.items()]
            patch_list[arq_uuid] = patch

        self.client.bind_arqs(bindings)

        mock_cyborg_patch.assert_called_once_with(
            self.client.ARQ_URL, json=mock.ANY)
        called_params = mock_cyborg_patch.call_args.kwargs['json']
        self.assertEqual(sorted(called_params), sorted(patch_list))

    @mock.patch('nova.accelerator.cyborg._CyborgClient._call_cyborg')
    def test_bind_arqs_exception(self, mock_call_cyborg):
        # If Cyborg returns invalid response, raise exception.
        bindings, _ = self._get_bound_arqs()
        mock_call_cyborg.return_value = None, 'Some error'
        self.assertRaises(exception.AcceleratorRequestOpFailed,
            self.client.bind_arqs, bindings=bindings)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_get_arqs_for_instance(self, mock_cyborg_get):
        # Happy path, without only_resolved=True
        _, bound_arqs = self._get_bound_arqs()
        instance_uuid = bound_arqs[0]['instance_uuid']

        query = {"instance": instance_uuid}
        content = jsonutils.dumps({'arqs': bound_arqs})
        resp = fake_requests.FakeResponse(200, content)
        mock_cyborg_get.return_value = resp

        ret_arqs = self.client.get_arqs_for_instance(instance_uuid)

        mock_cyborg_get.assert_called_once_with(
            self.client.ARQ_URL, params=query)

        bound_arqs.sort(key=lambda x: x['uuid'])
        ret_arqs.sort(key=lambda x: x['uuid'])
        for ret_arq, bound_arq in zip(ret_arqs, bound_arqs):
            self.assertDictEqual(ret_arq, bound_arq)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_get_arqs_for_instance_exception(self, mock_cyborg_get):
        # If Cyborg returns an error code, raise exception
        _, bound_arqs = self._get_bound_arqs()
        instance_uuid = bound_arqs[0]['instance_uuid']

        resp = fake_requests.FakeResponse(404, content='')
        mock_cyborg_get.return_value = resp
        self.assertRaises(
            exception.AcceleratorRequestOpFailed,
            self.client.get_arqs_for_instance, instance_uuid)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_get_arqs_for_instance_exception_no_resp(self, mock_cyborg_get):
        # If Cyborg returns an error code, raise exception
        _, bound_arqs = self._get_bound_arqs()
        instance_uuid = bound_arqs[0]['instance_uuid']

        content = jsonutils.dumps({'noarqs': 'oops'})
        resp = fake_requests.FakeResponse(200, content)
        mock_cyborg_get.return_value = resp
        self.assertRaisesRegex(
            exception.AcceleratorRequestOpFailed,
            'Cyborg returned no accelerator requests for ',
            self.client.get_arqs_for_instance, instance_uuid)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_get_arqs_for_instance_all_resolved(self, mock_cyborg_get):
        # If all ARQs are resolved, return full list
        _, bound_arqs = self._get_bound_arqs()
        instance_uuid = bound_arqs[0]['instance_uuid']

        query = {"instance": instance_uuid}
        content = jsonutils.dumps({'arqs': bound_arqs})
        resp = fake_requests.FakeResponse(200, content)
        mock_cyborg_get.return_value = resp

        ret_arqs = self.client.get_arqs_for_instance(
            instance_uuid, only_resolved=True)

        mock_cyborg_get.assert_called_once_with(
            self.client.ARQ_URL, params=query)

        bound_arqs.sort(key=lambda x: x['uuid'])
        ret_arqs.sort(key=lambda x: x['uuid'])
        for ret_arq, bound_arq in zip(ret_arqs, bound_arqs):
            self.assertDictEqual(ret_arq, bound_arq)

    @mock.patch('keystoneauth1.adapter.Adapter.get')
    def test_get_arqs_for_instance_some_resolved(self, mock_cyborg_get):
        # If only some ARQs are resolved, return just the resolved ones
        unbound_arqs, _ = self._get_arqs_and_request_groups()
        _, bound_arqs = self._get_bound_arqs()
        # Create a amixture of unbound and bound ARQs
        arqs = [unbound_arqs[0], bound_arqs[0]]
        instance_uuid = bound_arqs[0]['instance_uuid']

        query = {"instance": instance_uuid}
        content = jsonutils.dumps({'arqs': arqs})
        resp = fake_requests.FakeResponse(200, content)
        mock_cyborg_get.return_value = resp

        ret_arqs = self.client.get_arqs_for_instance(
            instance_uuid, only_resolved=True)

        mock_cyborg_get.assert_called_once_with(
            self.client.ARQ_URL, params=query)
        self.assertEqual(ret_arqs, [bound_arqs[0]])

    @mock.patch('nova.accelerator.cyborg._CyborgClient._call_cyborg')
    def test_delete_arqs_for_instance(self, mock_call_cyborg):
        # Happy path
        mock_call_cyborg.return_value = ('Some Value', None)
        instance_uuid = 'edbba496-3cc8-4256-94ca-dfe3413348eb'
        self.client.delete_arqs_for_instance(instance_uuid)
        mock_call_cyborg.assert_called_once_with(mock.ANY,
            self.client.ARQ_URL, params={'instance': instance_uuid})

    @mock.patch('nova.accelerator.cyborg._CyborgClient._call_cyborg')
    def test_delete_arqs_for_instance_exception(self, mock_call_cyborg):
        # If Cyborg returns invalid response, raise exception.
        err_msg = 'Some error'
        mock_call_cyborg.return_value = (None, err_msg)
        instance_uuid = 'edbba496-3cc8-4256-94ca-dfe3413348eb'
        exc = self.assertRaises(exception.AcceleratorRequestOpFailed,
            self.client.delete_arqs_for_instance, instance_uuid)
        expected_msg = ('Failed to delete accelerator requests: ' +
                        err_msg + ' Instance ' + instance_uuid)
        self.assertEqual(expected_msg, exc.format_message())
