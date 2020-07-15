# Copyright 2017 NTT Corporation.
#
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class InterfaceFullstack(integrated_helpers._IntegratedTestBase):
    """Tests for port interfaces command.

    Functional Test Scope:

    os-interface API specifies a port ID created by Neutron.
    """
    api_major_version = 'v2.1'

    def test_detach_interface_negative_invalid_state(self):
        # Create server with network
        server = self._create_server(
            networks=[{'uuid': '3cb9bc59-5699-4588-a4b1-b87f96708bc6'}])
        self.addCleanup(self._delete_server, server)

        post = {
            'interfaceAttachment': {
                'net_id': "3cb9bc59-5699-4588-a4b1-b87f96708bc6"
            }
        }
        self.api.attach_interface(server['id'], post)

        ports = self.api.get_port_interfaces(server['id'])

        # Change status from ACTIVE to SUSPENDED for negative test
        server = self._suspend_server(server)

        # Detach port interface in SUSPENDED (not ACTIVE, etc.)
        ex = self.assertRaises(
            client.OpenStackApiException,
            self.api.detach_interface,
            server['id'], ports[0]['port_id'])
        self.assertEqual(409, ex.response.status_code)
