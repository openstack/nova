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


import nova.conf
from nova.tests.functional.api_sample_tests import test_servers

CONF = nova.conf.CONF


class ShelveJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-shelve"

    def setUp(self):
        super(ShelveJsonTest, self).setUp()
        # Don't offload instance, so we can test the offload call.
        CONF.set_override('shelved_offload_time', -1)

    def _test_server_action(self, uuid, template, action):
        response = self._do_post('servers/%s/action' % uuid,
                                 template, {'action': action})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_shelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')

    def test_shelve_offload(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-shelve-offload', 'shelveOffload')

    def test_unshelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-unshelve', 'unshelve')


class UnshelveJson277Test(test_servers.ServersSampleBase):
    sample_dir = "os-shelve"
    microversion = '2.77'
    scenarios = [('v2_77', {'api_major_version': 'v2.1'})]
    USE_NEUTRON = True

    def _test_server_action(self, uuid, template, action, subs=None):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 template, subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_unshelve_with_az(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-unshelve', 'unshelve',
                                 subs={"availability_zone": "us-west"})

    def test_unshelve_no_az(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-unshelve-null', 'unshelve')
