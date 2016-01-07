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

    def _get_flags(self):
        f = super(SecurityGroupsJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.security_groups.'
            'Security_groups')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.keypairs.Keypairs')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips.Extended_ips')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips_mac.'
            'Extended_ips_mac')
        return f

    def setUp(self):
        self.flags(security_group_api=('neutron'))
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

    def test_server_create(self):
        self._post_server(use_common_server_api_samples=False)

    def test_server_get(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_server_detail(self):
        self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/detail')
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
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
        self._verify_response('security-groups-list-get-resp',
                              {}, response, 200)

    def test_security_groups_get(self):
        # Get api sample of security groups get request.
        security_group_id = '11111111-1111-1111-1111-111111111111'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        self._verify_response('security-groups-get-resp', {}, response, 200)

    def test_security_groups_list_server(self):
        # Get api sample of security groups for a specific server.
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        self._verify_response('server-security-groups-list-resp',
                              {}, response, 200)

    def test_security_groups_add(self):
        self._create_security_group()
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._add_group(uuid)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.content)

    def test_security_groups_remove(self):
        self._create_security_group()
        uuid = self._post_server(use_common_server_api_samples=False)
        self._add_group(uuid)
        subs = {
                'group_name': 'test'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'security-group-remove-post-req', subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.content)
