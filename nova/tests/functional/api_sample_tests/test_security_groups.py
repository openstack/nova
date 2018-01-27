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
import nova.tests.functional.api_samples_test_base as astb


def fake_get(*args, **kwargs):
    nova_group = {}
    nova_group['id'] = 1
    nova_group['description'] = 'default'
    nova_group['name'] = 'default'
    nova_group['project_id'] = astb.PROJECT_ID
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


def fake_create_security_group_rule(self, context, security_group, new_rule):
    return {
        'from_port': 22,
        'to_port': 22,
        'cidr': '10.0.0.0/24',
        'id': '00000000-0000-0000-0000-000000000000',
        'parent_group_id': '11111111-1111-1111-1111-111111111111',
        'protocol': 'tcp',
        'group_id': None
    }


def fake_remove_rules(self, context, security_group, rule_ids):
    pass


def fake_get_rule(self, context, id):
    return {
        'id': id,
        'parent_group_id': '11111111-1111-1111-1111-111111111111'
    }


class SecurityGroupsJsonTest(test_servers.ServersSampleBase):
    sample_dir = 'os-security-groups'
    USE_NEUTRON = True

    def setUp(self):
        super(SecurityGroupsJsonTest, self).setUp()
        path = 'nova.network.security_group.neutron_driver.SecurityGroupAPI.'
        self.stub_out(path + 'get', fake_get)
        self.stub_out(path + 'get_instances_security_groups_bindings',
                      fake_get_instances_security_groups_bindings)
        self.stub_out(path + 'add_to_instance', fake_add_to_instance)
        self.stub_out(path + 'remove_from_instance', fake_remove_from_instance)
        self.stub_out(path + 'list', fake_list)
        self.stub_out(path + 'get_instance_security_groups',
                      fake_get_instance_security_groups)
        self.stub_out(path + 'create_security_group',
                      fake_create_security_group)
        self.stub_out(path + 'create_security_group_rule',
                      fake_create_security_group_rule)
        self.stub_out(path + 'remove_rules',
                      fake_remove_rules)
        self.stub_out(path + 'get_rule',
                      fake_get_rule)

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
        self._verify_response('security-groups-list-get-resp',
                              {}, response, 200)

    def test_security_groups_get(self):
        # Get api sample of security groups get request.
        security_group_id = '11111111-1111-1111-1111-111111111111'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        self._verify_response('security-groups-get-resp', {}, response, 200)

    def test_security_groups_list_server(self):
        # Get api sample of security groups for a specific server.
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        self._verify_response('server-security-groups-list-resp',
                              {}, response, 200)

    def test_security_groups_add(self):
        self._create_security_group()
        uuid = self._post_server()
        response = self._add_group(uuid)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    def test_security_groups_remove(self):
        self._create_security_group()
        uuid = self._post_server()
        self._add_group(uuid)
        subs = {
                'group_name': 'test'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'security-group-remove-post-req', subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    def test_security_group_rules_create(self):
        response = self._do_post('os-security-group-rules',
                                 'security-group-rules-post-req', {})
        self._verify_response('security-group-rules-post-resp', {}, response,
                              200)

    def test_security_group_rules_remove(self):
        response = self._do_delete(
            'os-security-group-rules/00000000-0000-0000-0000-000000000000')
        self.assertEqual(202, response.status_code)
