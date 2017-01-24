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

import fixtures

from nova.console import manager as console_manager  # noqa - only for cfg
from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit import fake_xvp_console_proxy


class ConsolesSamplesJsonTest(test_servers.ServersSampleBase):
    sample_dir = "consoles"

    def setUp(self):
        super(ConsolesSamplesJsonTest, self).setUp()
        self.flags(console_public_hostname='fake', group='xenserver')
        self.flags(console_host='fake')
        self.useFixture(fixtures.MonkeyPatch(
            'nova.console.manager.xvp.XVPConsoleProxy',
            fake_xvp_console_proxy.FakeConsoleProxy))
        self.console = self.start_service('console', host='fake')

    def _create_consoles(self, server_uuid):
        response = self._do_post('servers/%s/consoles' % server_uuid,
                                 'consoles-create-req', {})
        self.assertEqual(response.status_code, 200)

    def test_create_consoles(self):
        uuid = self._post_server()
        self._create_consoles(uuid)

    def test_list_consoles(self):
        uuid = self._post_server()
        self._create_consoles(uuid)
        response = self._do_get('servers/%s/consoles' % uuid)
        self._verify_response('consoles-list-get-resp', {}, response, 200)

    def test_console_get(self):
        uuid = self._post_server()
        self._create_consoles(uuid)
        response = self._do_get('servers/%s/consoles/1' % uuid)
        self._verify_response('consoles-get-resp', {}, response, 200)

    def test_console_delete(self):
        uuid = self._post_server()
        self._create_consoles(uuid)
        response = self._do_delete('servers/%s/consoles/1' % uuid)
        self.assertEqual(202, response.status_code)
