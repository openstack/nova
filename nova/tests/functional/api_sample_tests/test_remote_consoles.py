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

HTTP_RE = r'(https?://)([\w\d:#@%/;$()~_?\+-=\\.&](#!)?)*'


class ConsolesSampleJsonTests(test_servers.ServersSampleBase):
    microversion = None
    sample_dir = "os-remote-consoles"

    def setUp(self):
        super(ConsolesSampleJsonTests, self).setUp()
        self.api.microversion = self.microversion
        self.flags(enabled=True, group='vnc')
        self.flags(enabled=True, group='spice')
        self.flags(enabled=True, group='rdp')
        self.flags(enabled=True, group='serial_console')

    def test_get_vnc_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-vnc-console-post-req',
                                {'action': 'os-getVNCConsole'})
        self._verify_response('get-vnc-console-post-resp', {'url': HTTP_RE},
                              response, 200)

    def test_get_spice_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-spice-console-post-req',
                                {'action': 'os-getSPICEConsole'})
        self._verify_response('get-spice-console-post-resp', {'url': HTTP_RE},
                              response, 200)

    def test_get_rdp_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                {'action': 'os-getRDPConsole'})
        self._verify_response('get-rdp-console-post-resp', {'url': HTTP_RE},
                              response, 200)

    def test_get_serial_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-serial-console-post-req',
                                {'action': 'os-getSerialConsole'})
        self._verify_response('get-serial-console-post-resp', {'url': HTTP_RE},
                              response, 200)


class ConsolesV26SampleJsonTests(test_servers.ServersSampleBase):
    microversion = '2.6'
    sample_dir = "os-remote-consoles"
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.6 which will run the original tests
    # by appending '(v2_6)' in test_id.
    scenarios = [('v2_6', {'api_major_version': 'v2.1'})]

    def test_create_console(self):
        uuid = self._post_server()

        body = {'protocol': 'vnc', 'type': 'novnc'}
        response = self._do_post('servers/%s/remote-consoles' % uuid,
                                 'create-vnc-console-req', body)
        self._verify_response('create-vnc-console-resp', {'url': HTTP_RE},
                              response, 200)


class ConsolesV28SampleJsonTests(test_servers.ServersSampleBase):
    sample_dir = "os-remote-consoles"
    microversion = '2.8'
    scenarios = [('v2_8', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ConsolesV28SampleJsonTests, self).setUp()
        self.flags(enabled=True, group='mks')

    def test_create_mks_console(self):
        uuid = self._post_server()

        body = {'protocol': 'mks', 'type': 'webmks'}
        response = self._do_post('servers/%s/remote-consoles' % uuid,
                                 'create-mks-console-req', body)
        self._verify_response('create-mks-console-resp', {'url': HTTP_RE},
                              response, 200)
