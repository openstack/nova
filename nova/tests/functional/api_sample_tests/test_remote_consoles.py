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

from nova.tests.functional.api_sample_tests import test_servers

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ConsolesSampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-remote-consoles"

    def _get_flags(self):
        f = super(ConsolesSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.consoles.Consoles')
        return f

    def setUp(self):
        super(ConsolesSampleJsonTests, self).setUp()
        self.flags(enabled=True, group='vnc')
        self.flags(enabled=True, group='spice')
        self.flags(enabled=True, group='rdp')
        self.flags(enabled=True, group='serial_console')

    def test_get_vnc_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-vnc-console-post-req',
                                {'action': 'os-getVNCConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-vnc-console-post-resp', subs, response, 200)

    def test_get_spice_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-spice-console-post-req',
                                {'action': 'os-getSPICEConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-spice-console-post-resp', subs,
                              response, 200)

    def test_get_rdp_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                {'action': 'os-getRDPConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-rdp-console-post-resp', subs,
                              response, 200)

    def test_get_serial_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-serial-console-post-req',
                                {'action': 'os-getSerialConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((ws?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-serial-console-post-resp', subs,
                              response, 200)


class ConsolesV26SampleJsonTests(test_servers.ServersSampleBase):
    microversion = '2.6'
    extension_name = "os-remote-consoles"
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.6 which will run the original tests
    # by appending '(v2_6)' in test_id.
    scenarios = [('v2_6', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ConsolesV26SampleJsonTests, self).setUp()
        self.http_regex = "(https?://)([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*"

    def test_create_console(self):
        uuid = self._post_server()

        body = {'protocol': 'vnc', 'type': 'novnc'}
        response = self._do_post('servers/%s/remote-consoles' % uuid,
                                 'create-vnc-console-req', body,
                                 api_version='2.6')
        subs = self._get_regexes()
        subs["url"] = self.http_regex
        self._verify_response('create-vnc-console-resp', subs, response, 200)


class ConsolesV28SampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-remote-consoles"
    microversion = '2.8'
    scenarios = [('v2_8', {'api_major_version': 'v2.1'})]
    api_major_version = 'v2'

    def setUp(self):
        super(ConsolesV28SampleJsonTests, self).setUp()
        self.http_regex = "(https?://)([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*"
        self.flags(enabled=True, group='mks')

    def test_create_mks_console(self):
        uuid = self._post_server()

        body = {'protocol': 'mks', 'type': 'webmks'}
        response = self._do_post('servers/%s/remote-consoles' % uuid,
                                 'create-mks-console-req', body,
                                 api_version='2.8')
        subs = self._get_regexes()
        subs["url"] = self.http_regex
        self._verify_response('create-mks-console-resp', subs, response, 200)
