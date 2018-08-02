# Copyright 2016 IBM Corp.
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

from nova.tests.functional.api import client
from nova.tests.functional import test_servers


class InstanceActionsTestV2(test_servers.ServersTestBase):
    """Tests Instance Actions API"""

    def _create_server(self):
        """Creates a minimal test server via the compute API

        Ensures the server is created and can be retrieved from the compute API
        and waits for it to be ACTIVE.

        :returns: created server (dict)
        """

        # Create a server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({'server': server})
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')
        # It should be available...
        self.assertEqual('ACTIVE', found_server['status'])
        return found_server

    def test_get_instance_actions(self):
        server = self._create_server()
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual('create', actions[0]['action'])

    def test_get_instance_actions_deleted(self):
        server = self._create_server()
        self._delete_server(server['id'])
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.get_instance_actions,
                          server['id'])


class InstanceActionsTestV21(InstanceActionsTestV2):
    api_major_version = 'v2.1'


class InstanceActionsTestV221(InstanceActionsTestV21):
    microversion = '2.21'

    def setUp(self):
        super(InstanceActionsTestV221, self).setUp()
        self.api.microversion = self.microversion

    def test_get_instance_actions_deleted(self):
        server = self._create_server()
        self._delete_server(server['id'])
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual('delete', actions[0]['action'])
        self.assertEqual('create', actions[1]['action'])
