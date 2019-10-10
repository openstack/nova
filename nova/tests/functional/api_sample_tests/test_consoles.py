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

from nova.tests.functional.api_sample_tests import test_servers

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class ConsolesSamplesJsonTest(test_servers.ServersSampleBase):

    def test_create_consoles(self):
        self.api.api_post('servers/%s/consoles' % FAKE_UUID, {},
                          check_response_status=[410])

    def test_list_consoles(self):
        self.api.api_get('servers/%s/consoles' % FAKE_UUID,
                         check_response_status=[410])

    def test_console_get(self):
        self.api.api_get('servers/%s/consoles/1' % FAKE_UUID,
                         check_response_status=[410])

    def test_console_delete(self):
        self.api.api_delete('servers/%s/consoles/1' % FAKE_UUID,
                            check_response_status=[410])
