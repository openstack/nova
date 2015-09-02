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
CONF.import_opt('shelved_offload_time', 'nova.compute.manager')
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ShelveJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-shelve"

    def _get_flags(self):
        f = super(ShelveJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.shelve.Shelve')
        return f

    def setUp(self):
        super(ShelveJsonTest, self).setUp()
        # Don't offload instance, so we can test the offload call.
        CONF.set_override('shelved_offload_time', -1)

    def _test_server_action(self, uuid, template, action):
        response = self._do_post('servers/%s/action' % uuid,
                                 template, {'action': action})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)

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
