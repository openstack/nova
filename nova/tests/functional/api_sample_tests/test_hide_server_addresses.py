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

from nova.compute import vm_states
import nova.conf
from nova.tests.functional.api_sample_tests import test_servers

CONF = nova.conf.CONF


class ServersSampleHideAddressesJsonTest(test_servers.ServersSampleJsonTest):
    sample_dir = 'os-hide-server-addresses'

    def setUp(self):
        # We override hide_server_address_states in order
        # to have an example of in the json samples of the
        # addresses being hidden
        CONF.set_override("hide_server_address_states",
                          [vm_states.ACTIVE], group='api')
        super(ServersSampleHideAddressesJsonTest, self).setUp()
