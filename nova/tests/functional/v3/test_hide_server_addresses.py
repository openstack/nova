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

from oslo_config import cfg

from nova.compute import vm_states
from nova.tests.functional.v3 import test_servers

CONF = cfg.CONF
CONF.import_opt('osapi_hide_server_address_states',
                'nova.api.openstack.compute.plugins.v3.hide_server_addresses')


class ServersSampleHideAddressesJsonTest(test_servers.ServersSampleJsonTest):
    extension_name = 'os-hide-server-addresses'
    # Override the sample dirname because
    # test_servers.ServersSampleJsonTest does and so it won't default
    # to the extension name
    sample_dir = extension_name

    def setUp(self):
        # We override osapi_hide_server_address_states in order
        # to have an example of in the json samples of the
        # addresses being hidden
        CONF.set_override("osapi_hide_server_address_states",
                          [vm_states.ACTIVE])
        super(ServersSampleHideAddressesJsonTest, self).setUp()
