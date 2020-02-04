# Copyright 2014 IBM Corp.
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

import copy

import nova.conf
from nova.network import constants
from nova.tests import fixtures
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = nova.conf.CONF


# TODO(stephenfin): Merge this back into the main class. We have to be careful
# with how we do this since if we register two networks we'll have ambiguous
# networks breaking auto-allocation
class NeutronFixture(fixtures.NeutronFixture):

    network_1 = {
        'id': fixtures.NeutronFixture.network_1['id'],
        'name': 'public',
        'description': '',
        'status': 'ACTIVE',
        'subnets': [
            # NOTE(stephenfin): We set this below
        ],
        'admin_state_up': True,
        'tenant_id': fixtures.NeutronFixture.tenant_id,
        'project_id': fixtures.NeutronFixture.tenant_id,
        'shared': False,
        'mtu': 1500,
        'router:external': True,
        'availability_zone_hints': [],
        'availability_zones': [
            'nova'
        ],
        'port_security_enabled': True,
        'ipv4_address_scope': None,
        'ipv6_address_scope': None,
        'is_default': True,
    }

    subnet_1 = {
        'id': '6b0b19d2-22b8-45f9-bf32-06d0b89f2d47',
        'name': 'public-subnet',
        'description': '',
        'ip_version': 4,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': False,
        'network_id': network_1['id'],
        'tenant_id': fixtures.NeutronFixture.tenant_id,
        'project_id': fixtures.NeutronFixture.tenant_id,
        'dns_nameservers': [],
        'gateway_ip': '172.24.4.1',
        'allocation_pools': [
            {
                'start': '172.24.4.2',
                'end': '172.24.4.254'
            }
        ],
        'host_routes': [],
        'cidr': '172.24.4.0/24',
    }
    subnet_2 = {
        'id': '503505c5-0dd2-4756-b355-4056aa0b6338',
        'name': 'ipv6-public-subnet',
        'description': '',
        'ip_version': 6,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': False,
        'network_id': network_1['id'],
        'tenant_id': fixtures.NeutronFixture.tenant_id,
        'project_id': fixtures.NeutronFixture.tenant_id,
        'dns_nameservers': [],
        'gateway_ip': '2001:db8::2',
        'allocation_pools': [
            {'start': '2001:db8::1', 'end': '2001:db8::1'},
            {'start': '2001:db8::3', 'end': '2001:db8::ffff:ffff:ffff:ffff'},
        ],
        'host_routes': [],
        'cidr': '2001:db8::/64',
    }
    network_1['subnets'] = [subnet_1['id'], subnet_2['id']]

    floatingip_1 = {
        'id': '8baeddb4-45e2-4c36-8cb7-d79439a5f67c',
        'description': '',
        'status': 'DOWN',
        'floating_ip_address': '172.24.4.17',
        'fixed_ip_address': None,
        'router_id': None,
        'tenant_id': fixtures.NeutronFixture.tenant_id,
        'project_id': fixtures.NeutronFixture.tenant_id,
        'floating_network_id': network_1['id'],
        'port_details': None,
        'port_id': None,
    }
    floatingip_2 = {
        'id': '05ef7490-745a-4af9-98e5-610dc97493c4',
        'description': '',
        'status': 'DOWN',
        'floating_ip_address': '172.24.4.78',
        'fixed_ip_address': None,
        'router_id': None,
        'tenant_id': fixtures.NeutronFixture.tenant_id,
        'project_id': fixtures.NeutronFixture.tenant_id,
        'floating_network_id': network_1['id'],
        'port_details': None,
        'port_id': None,
    }

    def __init__(self, test):
        super(NeutronFixture, self).__init__(test)

        self._ports = {}
        self._networks = {
            self.network_1['id']: copy.deepcopy(self.network_1),
        }
        self._floatingips = {}
        self._subnets = {
            self.subnet_1['id']: copy.deepcopy(self.subnet_1),
            self.subnet_2['id']: copy.deepcopy(self.subnet_2),
        }

    def create_floatingip(self, body=None):
        for floatingip in [self.floatingip_1, self.floatingip_2]:
            if floatingip['id'] not in self._floatingips:
                self._floatingips[floatingip['id']] = copy.deepcopy(floatingip)
                break
        else:
            # we can extend this later, if necessary
            raise Exception('We only support adding a max of two floating IPs')

        return {'floatingip': floatingip}

    def delete_floatingip(self, floatingip):
        if floatingip not in self._floatingips:
            raise Exception('This floating IP has not been added yet')

        del self._floatingips[floatingip]

    def show_floatingip(self, floatingip, **_params):
        if floatingip not in self._floatingips:
            raise Exception('This floating IP has not been added yet')

        return {'floatingip': copy.deepcopy(self._floatingips[floatingip])}

    def list_floatingips(self, retrieve_all=True, **_params):
        return {'floatingips': copy.deepcopy(list(self._floatingips.values()))}

    def list_extensions(self, *args, **kwargs):
        extensions = super().list_extensions(*args, **kwargs)
        extensions['extensions'].append(
            {
                # Copied from neutron-lib fip_port_details.py
                'updated': '2018-04-09T10:00:00-00:00',
                'name': constants.FIP_PORT_DETAILS,
                'links': [],
                'alias': 'fip-port-details',
                'description': 'Add port_details attribute to Floating IP '
                               'resource',
            },
        )
        return extensions


class FloatingIpsTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "os-floating-ips"

    def setUp(self):
        super(FloatingIpsTest, self).setUp()

        # we use a custom NeutronFixture that mocks out floating IP stuff
        self.neutron = self.useFixture(NeutronFixture(self))

        # we also use a more useful default floating pool value
        self.flags(default_floating_pool='public', group='neutron')

    def test_floating_ips_list_empty(self):
        response = self._do_get('os-floating-ips')

        self._verify_response('floating-ips-list-empty-resp',
                              {}, response, 200)

    def test_floating_ips_list(self):
        self._do_post('os-floating-ips')
        self._do_post('os-floating-ips')

        response = self._do_get('os-floating-ips')
        self._verify_response('floating-ips-list-resp',
                              {}, response, 200)

    def test_floating_ips_create_nopool(self):
        response = self._do_post('os-floating-ips')
        self._verify_response('floating-ips-create-resp',
                              {}, response, 200)

    def test_floating_ips_create(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-req',
                                 {'pool': 'public'})
        self._verify_response('floating-ips-create-resp', {}, response, 200)
        return response

    def test_floating_ips_get(self):
        floatingip = self.test_floating_ips_create().json()['floating_ip']
        response = self._do_get('os-floating-ips/%s' % floatingip['id'])
        self._verify_response('floating-ips-get-resp', {}, response, 200)

    def test_floating_ips_delete(self):
        floatingip = self.test_floating_ips_create().json()['floating_ip']
        response = self._do_delete('os-floating-ips/%s' % floatingip['id'])
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)
