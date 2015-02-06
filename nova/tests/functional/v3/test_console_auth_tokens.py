# Copyright 2013 Cloudbase Solutions Srl
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

import re

from oslo_serialization import jsonutils

from nova.tests.functional.v3 import test_servers


class ConsoleAuthTokensSampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-console-auth-tokens"
    extra_extensions_to_load = ["os-remote-consoles"]

    def _get_console_url(self, data):
        return jsonutils.loads(data)["console"]["url"]

    def _get_console_token(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                 {'action': 'os-getRDPConsole'})

        url = self._get_console_url(response.content)
        return re.match('.+?token=([^&]+)', url).groups()[0]

    def test_get_console_connect_info(self):
        self.flags(enabled=True, group='rdp')

        uuid = self._post_server()
        token = self._get_console_token(uuid)

        response = self._do_get('os-console-auth-tokens/%s' % token)

        subs = self._get_regexes()
        subs["uuid"] = uuid
        subs["host"] = r"[\w\.\-]+"
        subs["port"] = "[0-9]+"
        subs["internal_access_path"] = ".*"
        self._verify_response('get-console-connect-info-get-resp', subs,
                              response, 200)
