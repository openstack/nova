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

from nova.compute import api as compute_api
from nova.compute import rpcapi as compute_rpcapi
from nova.servicegroup import api as service_group_api
from nova.tests.integrated.v3 import test_servers


class EvacuateJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-evacuate"

    def test_server_evacuate(self):
        uuid = self._post_server()

        # Note (wingwj): The host can't be the same one.
        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
            "onSharedStorage": 'False'
        }

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

        def fake_rebuild_instance(_self, ctxt, instance, new_pass,
                                  injected_files, image_ref, orig_image_ref,
                                  orig_sys_metadata, bdms, recreate=False,
                                  on_shared_storage=False, host=None,
                                  preserve_ephemeral=False, kwargs=None):
            """Simulate that given parameters are correct."""
            self.assertEqual(uuid, instance["uuid"])
            self.assertEqual(new_pass, "MySecretPass")
            self.assertEqual(host, "testHost")

        self.stubs.Set(service_group_api.API, 'service_is_up',
                       fake_service_is_up)
        self.stubs.Set(compute_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'rebuild_instance',
                       fake_rebuild_instance)

        response = self._do_post('servers/%s/action' % uuid,
                                 'server-evacuate-req', req_subs)
        subs = self._get_regexes()
        self._verify_response('server-evacuate-resp', subs, response, 202)
