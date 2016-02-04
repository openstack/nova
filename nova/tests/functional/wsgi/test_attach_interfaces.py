# Copyright 2016 NTT Corporation.
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

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture
from nova.tests import uuidsentinel as uuids


def create_request_body():
    return {
               "interfaceAttachment": {
                   "port_id": uuids.port,
                   "net_id": uuids.net,
                   "fixed_ips": [
                       {
                           "ip_address": "192.168.1.3",
                           "subnet_id": uuids.subnet
                       }
                   ]
               }
           }


class InterfaceFullstack(integrated_helpers._IntegratedTestBase):
    """Tests for port interfaces command.

    Extension: os-interface

    os-interface adds a set of functions to the port interfaces
    for the creation and deletion of port interfaces.

    POST /v2.1/{tenant_id}/servers/{server_id}/os-interface
    DELETE /v2.1/{tenant_id}/servers/{server_id}/os-interface/{attachment_id}

    Functional Test Scope:

    This test starts the wsgi stack for the nova api services, uses an
    in memory database to ensure the path through the wsgi layer to
    the database.

    """
    api_major_version = 'v2.1'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    def setUp(self):
        super(InterfaceFullstack, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture())

        self.api = api_fixture.api

    def test_interface_func_negative(self):
        """Test port interface edge conditions.

        - Bogus body is a 400
        """
        # Create a server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        # Test for API failure conditions
        # bad body is 400
        os_interface_url = '/servers/%s/os-interface' % created_server_id

        # Check in the case that both net_id and port_id are specified.
        body = create_request_body()
        del body['interfaceAttachment']['fixed_ips']
        resp = self.api.api_post(os_interface_url, body,
                                 check_response_status=False)
        self.assertEqual(400, resp.status)

        # Check in the case that fixed_ips is specified,
        # but net_id is not specifed.
        body = create_request_body()
        del body['interfaceAttachment']['port_id']
        del body['interfaceAttachment']['net_id']
        resp = self.api.api_post(os_interface_url, body,
                                 check_response_status=False)
        self.assertEqual(400, resp.status)
