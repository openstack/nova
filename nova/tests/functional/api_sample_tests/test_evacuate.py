# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from nova import objects
from nova.tests.functional.api_sample_tests import test_servers


class EvacuateJsonTest(test_servers.ServersSampleBase):
    ADMIN_API = True
    sample_dir = "os-evacuate"
    USE_NEUTRON = True

    def _test_evacuate(self, req_subs, server_req, server_resp,
                       expected_resp_code):
        self.uuid = self._post_server()

        def fake_service_is_up(self, service):
            """Simulate validation of instance host is down."""
            return False

        def fake_service_get_by_compute_host(self, context, host):
            """Simulate that given host is a valid host."""
            return {
                    'host_name': host,
                    'service': 'compute',
                    'zone': 'nova'
                    }

        def fake_check_instance_exists(self, context, instance):
            """Simulate validation of instance does not exist."""
            return False

        self.stub_out(
            'nova.servicegroup.api.API.service_is_up',
            fake_service_is_up)
        self.stub_out(
            'nova.compute.api.HostAPI.service_get_by_compute_host',
            fake_service_get_by_compute_host)
        self.stub_out(
            'nova.compute.manager.ComputeManager._check_instance_exists',
            fake_check_instance_exists)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 server_req, req_subs)
        if server_resp:
            self._verify_response(server_resp, {}, response,
                                  expected_resp_code)
        else:
            # NOTE(gibi): no server_resp means we expect empty body as
            # a response
            self.assertEqual(expected_resp_code, response.status_code)
            self.assertEqual('', response.text)

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    def test_server_evacuate(self, rebuild_mock):
        # Note (wingwj): The host can't be the same one
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
            "onSharedStorage": 'False'
        }
        self._test_evacuate(req_subs, 'server-evacuate-req',
                            'server-evacuate-resp', 200)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=False, preserve_ephemeral=mock.ANY,
                host='testHost', request_spec=mock.ANY)

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    def test_server_evacuate_find_host(self, rebuild_mock):
        req_subs = {
            "adminPass": "MySecretPass",
            "onSharedStorage": 'False'
        }
        self._test_evacuate(req_subs, 'server-evacuate-find-host-req',
                            'server-evacuate-find-host-resp', 200)

        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=False, preserve_ephemeral=mock.ANY,
                host=None, request_spec=mock.ANY)


class EvacuateJsonTestV214(EvacuateJsonTest):
    microversion = '2.14'
    scenarios = [('v2_14', {'api_major_version': 'v2.1'})]

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    def test_server_evacuate(self, rebuild_mock):
        # Note (wingwj): The host can't be the same one
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
        }
        self._test_evacuate(req_subs, 'server-evacuate-req',
                            server_resp=None, expected_resp_code=200)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=None, preserve_ephemeral=mock.ANY,
                host='testHost', request_spec=mock.ANY)

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    def test_server_evacuate_find_host(self, rebuild_mock):
        req_subs = {
            "adminPass": "MySecretPass",
        }
        self._test_evacuate(req_subs, 'server-evacuate-find-host-req',
                            server_resp=None, expected_resp_code=200)

        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=None, preserve_ephemeral=mock.ANY,
                host=None, request_spec=mock.ANY)


class EvacuateJsonTestV229(EvacuateJsonTestV214):
    microversion = '2.29'
    scenarios = [('v2_29', {'api_major_version': 'v2.1'})]

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_server_evacuate(self, compute_node_get_all_by_host, rebuild_mock):
        # Note (wingwj): The host can't be the same one
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
            "force": "false",
        }
        fake_computes = objects.ComputeNodeList(
            objects=[objects.ComputeNode(host='testHost',
                                         hypervisor_hostname='host')])
        compute_node_get_all_by_host.return_value = fake_computes
        self._test_evacuate(req_subs, 'server-evacuate-req',
                            server_resp=None, expected_resp_code=200)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=None, preserve_ephemeral=mock.ANY,
                host=None, request_spec=mock.ANY)

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_server_evacuate_with_force(self, compute_node_get_all_by_host,
                                        rebuild_mock):
        # Note (wingwj): The host can't be the same one
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
            "force": "True",
        }
        self._test_evacuate(req_subs, 'server-evacuate-req',
                            server_resp=None, expected_resp_code=200)
        self.assertEqual(0, compute_node_get_all_by_host.call_count)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=None, preserve_ephemeral=mock.ANY,
                host='testHost', request_spec=mock.ANY)


class EvacuateJsonTestV268(EvacuateJsonTestV229):
    microversion = '2.68'
    scenarios = [('v2_68', {'api_major_version': 'v2.1'})]

    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_server_evacuate(self, compute_node_get_all_by_host, rebuild_mock):
        # Note (wingwj): The host can't be the same one
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
        }
        fake_computes = objects.ComputeNodeList(
            objects=[objects.ComputeNode(host='testHost',
                                         hypervisor_hostname='host')])
        compute_node_get_all_by_host.return_value = fake_computes
        self._test_evacuate(req_subs, 'server-evacuate-req',
                            server_resp=None, expected_resp_code=200)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=None, preserve_ephemeral=mock.ANY,
                host=None, request_spec=mock.ANY)

    def test_server_evacuate_with_force(self):
        # doesn't apply to v2.68+, which removed the ability to force migrate
        pass
