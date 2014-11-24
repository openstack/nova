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
from nova.tests.functional.v3 import test_servers


def fake_get(*args, **kwargs):
    nova_group = {}
    nova_group['id'] = 1
    nova_group['description'] = 'default'
    nova_group['name'] = 'default'
    nova_group['project_id'] = 'openstack'
    nova_group['rules'] = []
    return nova_group


def fake_get_instances_security_groups_bindings(self, context, servers,
                                                detailed=False):
    result = {}
    for s in servers:
        result[s.get('id')] = [{'name': 'test'}]
    return result


def fake_add_to_instance(self, context, instance, security_group_name):
    pass


def fake_remove_from_instance(self, context, instance, security_group_name):
    pass


def fake_list(self, context, names=None, ids=None, project=None,
             search_opts=None):
    return [fake_get()]


def fake_get_instance_security_groups(self, context, instance_uuid,
                                      detailed=False):
    return [fake_get()]


def fake_create_security_group(self, context, name, description):
    return fake_get()


class SecurityGroupsJsonTest(test_servers.ServersSampleBase):
    extension_name = 'os-security-groups'

    def setUp(self):
        self.flags(security_group_api=('neutron'))
        super(SecurityGroupsJsonTest, self).setUp()
        self.stubs.Set(neutron_driver.SecurityGroupAPI, 'get', fake_get)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'get_instances_security_groups_bindings',
                       fake_get_instances_security_groups_bindings)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'add_to_instance',
                       fake_add_to_instance)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'remove_from_instance',
                       fake_remove_from_instance)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'list',
                       fake_list)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'get_instance_security_groups',
                       fake_get_instance_security_groups)
        self.stubs.Set(neutron_driver.SecurityGroupAPI,
                       'create_security_group',
                       fake_create_security_group)

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

    def _get_create_subs(self):
        return {
                'group_name': 'default',
                "description": "default",
        }

    def _create_security_group(self):
        subs = self._get_create_subs()
        return self._do_post('os-security-groups',
                             'security-group-post-req', subs)

    def _add_group(self, uuid):
        subs = {
                'group_name': 'test'
        }
        return self._do_post('servers/%s/action' % uuid,
                             'security-group-add-post-req', subs)

    def test_security_group_create(self):
        response = self._create_security_group()
        subs = self._get_create_subs()
        self._verify_response('security-groups-create-resp', subs,
                              response, 200)

    def test_security_groups_list(self):
        # Get api sample of security groups get list request.
        response = self._do_get('os-security-groups')
        subs = self._get_regexes()
        self._verify_response('security-groups-list-get-resp',
                              subs, response, 200)

    def test_security_groups_get(self):
        # Get api sample of security groups get request.
        security_group_id = '11111111-1111-1111-1111-111111111111'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        subs = self._get_regexes()
        self._verify_response('security-groups-get-resp', subs, response, 200)

    def test_security_groups_list_server(self):
        # Get api sample of security groups for a specific server.
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-security-groups-list-resp',
                              subs, response, 200)

    def test_security_groups_add(self):
        self._create_security_group()
        uuid = self._post_server()
        response = self._add_group(uuid)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_security_groups_remove(self):
        self._create_security_group()
        uuid = self._post_server()
        self._add_group(uuid)
        subs = {
                'group_name': 'test'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'security-group-remove-post-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')
