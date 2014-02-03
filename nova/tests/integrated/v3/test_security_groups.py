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

from nova.network.security_group import neutron_driver
from nova.tests.integrated.v3 import test_servers


def fake_get(*args, **kwargs):
    nova_group = {}
    nova_group['id'] = 'fake'
    nova_group['description'] = ''
    nova_group['name'] = 'test'
    nova_group['project_id'] = 'fake'
    nova_group['rules'] = []
    return nova_group


def fake_get_instances_security_groups_bindings(self, context, servers):
    result = {}
    for s in servers:
        result[s.get('id')] = [{'name': 'test'}]
    return result


class SecurityGroupsJsonTest(test_servers.ServersSampleBase):
    extension_name = 'os-security-groups'

    def setUp(self):
        self.flags(security_group_api=('neutron'))
        super(SecurityGroupsJsonTest, self).setUp()
        self.stubs.Set(neutron_driver.SecurityGroupAPI, 'get', fake_get)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'get_instances_security_groups_bindings',
                       fake_get_instances_security_groups_bindings)

    def test_server_create(self):
        self._post_server()

    def test_server_get(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_server_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)
