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
from nova.tests.functional import test_servers


class InterfaceFullstack(test_servers.ServersTestBase):
    """Tests for port interfaces command.

    Functional Test Scope:

    os-interface API specifies a port ID created by Neutron.
    """
    api_major_version = 'v2.1'

    def test_detach_interface_negative_invalid_state(self):
        # Create server with network
        created_server = self._create_server(
            networks=[{'uuid': '3cb9bc59-5699-4588-a4b1-b87f96708bc6'}])
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        post = {
            'interfaceAttachment': {
                'net_id': "3cb9bc59-5699-4588-a4b1-b87f96708bc6"
            }
        }
        self.api.attach_interface(created_server_id, post)

        response = self.api.get_port_interfaces(created_server_id)[0]
        port_id = response['port_id']

        # Change status from ACTIVE to SUSPENDED for negative test
        post = {'suspend': {}}
        self.api.post_server_action(created_server_id, post)
        found_server = self._wait_for_state_change(found_server, 'SUSPENDED')

        # Detach port interface in SUSPENDED (not ACTIVE, etc.)
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.detach_interface,
                               created_server_id, port_id)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('SUSPENDED', found_server['status'])

        # Cleanup
        self._delete_server(found_server)
