# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import copy
import random

import fixtures
from neutronclient.common import exceptions as neutron_client_exc
import os_resource_classes as orc
from oslo_utils import uuidutils

from nova import exception
from nova.network import constants as neutron_constants
from nova.network import model as network_model
from nova.tests.fixtures import nova as nova_fixtures


class _FakeNeutronClient:
    """Class representing a Neutron client which wraps a NeutronFixture.

    This wrapper class stores an instance of a NeutronFixture and whether the
    Neutron client is an admin client.

    For supported methods, (example: list_ports), this class will call the
    NeutronFixture's class method with an additional 'is_admin' keyword
    argument indicating whether the client is an admin client and the
    NeutronFixture method handles it accordingly.

    For all other methods, this wrapper class simply calls through to the
    corresponding NeutronFixture class method without any modifications.
    """

    def __init__(self, fixture, is_admin):
        self.fixture = fixture
        self.is_admin = is_admin

    def __getattr__(self, name):
        return getattr(self.fixture, name)

    def list_ports(self, retrieve_all=True, **_params):
        return self.fixture.list_ports(
            self.is_admin, retrieve_all=retrieve_all, **_params,
        )

    def show_port(self, port_id, **_params):
        return self.fixture.show_port(
            port_id, is_admin=self.is_admin, **_params,
        )


# TODO(stephenfin): We should split out the stubs of neutronclient from the
# stubs of 'nova.network.neutron' to simplify matters
class NeutronFixture(fixtures.Fixture):
    """A fixture to boot instances with neutron ports"""

    # the default project_id in OsaAPIFixtures
    tenant_id = nova_fixtures.PROJECT_ID

    network_1 = {
        'id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
        'name': 'private',
        'description': '',
        'status': 'ACTIVE',
        'subnets': [],
        'admin_state_up': True,
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'shared': False,
        'mtu': 1450,
        'router:external': False,
        'availability_zone_hints': [],
        'availability_zones': [
            'nova'
        ],
        'port_security_enabled': True,
        'ipv4_address_scope': None,
        'ipv6_address_scope': None,
        'provider:network_type': 'vxlan',
        'provider:physical_network': None,
        'provider:segmentation_id': 24,
    }

    security_group = {
        'id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'name': 'default',
        'description': 'Default security group',
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'security_group_rules': [],  # setup later
    }
    security_group_rule_ip4_ingress = {
        'id': 'e62268aa-1a17-4ff4-ae77-ab348bfe13a7',
        'description': None,
        'direction': 'ingress',
        'ethertype': 'IPv4',
        'protocol': None,
        'port_range_min': None,
        'port_range_max': None,
        'remote_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'remote_ip_prefix': None,
        'security_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'tenant_id': tenant_id,
        'project_id': tenant_id,
    }
    security_group_rule_ip4_egress = {
        'id': 'adf54daf-2ff9-4462-a0b0-f226abd1db28',
        'description': None,
        'direction': 'egress',
        'ethertype': 'IPv4',
        'protocol': None,
        'port_range_min': None,
        'port_range_max': None,
        'remote_group_id': None,
        'remote_ip_prefix': None,
        'security_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'tenant_id': tenant_id,
        'project_id': tenant_id,
    }
    security_group_rule_ip6_ingress = {
        'id': 'c4194b5c-3b50-4d35-9247-7850766aee2b',
        'description': None,
        'direction': 'ingress',
        'ethertype': 'IPv6',
        'protocol': None,
        'port_range_min': None,
        'port_range_max': None,
        'remote_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'remote_ip_prefix': None,
        'security_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'tenant_id': tenant_id,
        'project_id': tenant_id,
    }
    security_group_rule_ip6_egress = {
        'id': '16ce6a83-a1db-4d66-a10d-9481d493b072',
        'description': None,
        'direction': 'egress',
        'ethertype': 'IPv6',
        'protocol': None,
        'port_range_min': None,
        'port_range_max': None,
        'remote_group_id': None,
        'remote_ip_prefix': None,
        'security_group_id': 'aec9df91-db1f-4e04-8ac6-e761d8461c53',
        'tenant_id': tenant_id,
        'project_id': tenant_id,
    }
    security_group['security_group_rules'] = [
        security_group_rule_ip4_ingress['id'],
        security_group_rule_ip4_egress['id'],
        security_group_rule_ip6_ingress['id'],
        security_group_rule_ip6_egress['id'],
    ]

    subnet_1 = {
        'id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef',
        'name': 'private-subnet',
        'description': '',
        'ip_version': 4,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': True,
        'network_id': network_1['id'],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'dns_nameservers': [],
        'gateway_ip': '192.168.1.1',
        'allocation_pools': [
            {
                'start': '192.168.1.1',
                'end': '192.168.1.254'
            }
        ],
        'host_routes': [],
        'cidr': '192.168.1.1/24',
    }
    subnet_ipv6_1 = {
        'id': 'f8fa37b7-c10a-44b8-a5fe-d2e65d40b403',
        'name': 'ipv6-private-subnet',
        'description': '',
        'ip_version': 6,
        'ipv6_address_mode': 'slaac',
        'ipv6_ra_mode': 'slaac',
        'enable_dhcp': True,
        'network_id': network_1['id'],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'dns_nameservers': [],
        'gateway_ip': 'fd37:44e8:ad06::1',
        'allocation_pools': [
            {
                'start': 'fd37:44e8:ad06::2',
                'end': 'fd37:44e8:ad06:0:ffff:ffff:ffff:ffff'
            }
        ],
        'host_routes': [],
        'cidr': 'fd37:44e8:ad06::/64',
    }
    network_1['subnets'] = [subnet_1['id'], subnet_ipv6_1['id']]

    port_1 = {
        'id': 'ce531f90-199f-48c0-816c-13e38010b442',
        'name': '',  # yes, this what the neutron API returns
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:30',
        'fixed_ips': [
            {
                # The IP on this port must be a prefix of the IP on port_2 to
                # test listing servers with an ip filter regex.
                'ip_address': '192.168.1.3',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
        'port_security_enabled': True,
        'security_groups': [
            security_group['id'],
        ],
    }

    port_2 = {
        'id': '88dae9fa-0dc6-49e3-8c29-3abc41e99ac9',
        'name': '',
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '00:0c:29:0d:11:74',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.30',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
        'port_security_enabled': True,
        'security_groups': [
            security_group['id'],
        ],
    }

    port_with_resource_request = {
        'id': '2f2613ce-95a9-490a-b3c4-5f1c28c1f886',
        'name': '',
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c3',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.42',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
        'resource_request': {
            "resources": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: 1000,
                orc.NET_BW_EGR_KILOBIT_PER_SEC: 1000,
            },
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_NORMAL"]
        },
        'port_security_enabled': True,
        'security_groups': [
            security_group['id'],
        ],
    }

    # Fixtures inheriting from NeutronFixture can redefine the default port
    # that create_port() is duplicating for creating a new port by using this
    # variable
    default_port = copy.deepcopy(port_2)

    # network_2 does not have security groups enabled - that's okay since most
    # of these ports are SR-IOV'y anyway
    network_2 = {
        'id': '1b70879f-fd00-411e-8ea9-143e7820e61d',
        # TODO(stephenfin): This would be more useful name due to things like
        # https://bugs.launchpad.net/nova/+bug/1708316
        'name': 'private',
        'description': '',
        'status': 'ACTIVE',
        'subnets': [],
        'admin_state_up': True,
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'shared': False,
        'mtu': 1450,
        'router:external': False,
        'availability_zone_hints': [],
        'availability_zones': [
            'nova'
        ],
        'port_security_enabled': False,
        'ipv4_address_scope': None,
        'ipv6_address_scope': None,
        'provider:network_type': 'vlan',
        'provider:physical_network': 'physnet2',
        'provider:segmentation_id': 24,
    }

    subnet_2 = {
        'id': 'c7ca1baf-f536-4849-89fe-9671318375ff',
        'name': '',
        'description': '',
        'ip_version': 4,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': True,
        'network_id': network_2['id'],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'dns_nameservers': [],
        'gateway_ip': '192.168.1.1',
        'allocation_pools': [
            {
                'start': '192.168.13.1',
                'end': '192.168.1.254'
            }
        ],
        'host_routes': [],
        'cidr': '192.168.1.1/24',
    }
    network_2['subnets'] = [subnet_2['id']]

    sriov_port = {
        'id': '5460ee0c-ffbb-4e45-8d58-37bfceabd084',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c4',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.2',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'resource_request': {},
        'binding:profile': {},
        'binding:vif_details': {'vlan': 100},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'direct',
        'port_security_enabled': False,
    }

    sriov_port2 = {
        'id': '3f675f19-8b2d-479d-9d42-054644a95a04',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c5',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.2',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'resource_request': {},
        'binding:profile': {},
        'binding:vnic_type': 'direct',
        'binding:vif_type': 'hw_veb',
        'binding:vif_details': {'vlan': 100},
        'port_security_enabled': False,
    }

    sriov_pf_port = {
        'id': 'ce2a6ff9-573d-493e-9498-8100953e6f00',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c6',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.2',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'resource_request': {},
        'binding:profile': {},
        'binding:vnic_type': 'direct-physical',
        'binding:vif_type': 'hostdev_physical',
        'binding:vif_details': {'vlan': 100},
        'port_security_enabled': False,
    }

    sriov_pf_port2 = {
        'id': 'ad2fd6c2-2c55-4c46-abdc-a8ec0d5f6a29',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c7',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.2',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'resource_request': {},
        'binding:profile': {},
        'binding:vnic_type': 'direct-physical',
        'binding:vif_type': 'hostdev_physical',
        'binding:vif_details': {'vlan': 100},
        'port_security_enabled': False,
    }

    macvtap_port = {
        'id': '6eada1f1-6311-428c-a7a5-52b35cabc8fd',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c8',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.4',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vnic_type': 'macvtap',
        'binding:vif_type': 'hw_veb',
        'binding:vif_details': {'vlan': 100},
        'port_security_enabled': False,
    }

    macvtap_port2 = {
        'id': 'fc79cc0c-93e9-4613-9f78-34c828d92e9f',
        'name': '',
        'description': '',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c9',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.4',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vnic_type': 'macvtap',
        'binding:vif_type': 'hw_veb',
        'binding:vif_details': {'vlan': 100},
        'port_security_enabled': False,
    }

    ports_with_accelerator = [
        {
        'id': '7970ec1f-7ce0-4293-a2a3-92cbce8048b4',
        'name': '',
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c3',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.43',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'device_profile': 'fakedev-dp-port',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'accelerator-direct',
        'resource_request': {},
        'port_security_enabled': True,
        'security_groups': [],
        },
        {
        'id': '7e95fbcc-1d5f-4a99-9f43-c6aa592bcf81',
        'name': '',
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c4',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.44',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'device_profile': 'fakedev-dp-port',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'accelerator-direct',
        'resource_request': {},
        'port_security_enabled': True,
        'security_groups': [],
        }
    ]

    ports_with_multi_accelerators = [
        {
        'id': '19fb99fd-0b64-4f06-af1a-68eeb2bca95a',
        'name': '',
        'description': '',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c3',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.43',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'device_profile': 'fakedev-dp-multi',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'accelerator-direct',
        'resource_request': {},
        'port_security_enabled': True,
        'security_groups': [],
        },
    ]

    nw_info = [{
        "profile": {},
        "ovs_interfaceid": "b71f1699-42be-4515-930a-f3ef01f94aa7",
        "preserve_on_delete": False,
        "network": {
            "bridge": "br-int",
            "subnets": [{
                "ips": [{
                    "meta": {},
                    "version": 4,
                    "type": "fixed",
                    "floating_ips": [],
                    "address": "10.0.0.4"
                }],
                "version": 4,
                "meta": {},
                "dns": [],
                "routes": [],
                "cidr": "10.0.0.0/26",
                "gateway": {
                    "meta": {},
                    "version": 4,
                    "type": "gateway",
                    "address": "10.0.0.1"
                }
            }],
            "meta": {
                "injected": False,
                "tenant_id": tenant_id,
                "mtu": 1500
            },
            "id": "e1882e38-38c2-4239-ade7-35d644cb963a",
            "label": "public"
        },
        "devname": "tapb71f1699-42",
        "vnic_type": "normal",
        "qbh_params": None,
        "meta": {},
        "details": {
            "port_filter": True,
            "ovs_hybrid_plug": True
        },
        "address": "fa:16:3e:47:94:4a",
        "active": True,
        "type": "ovs",
        "id": "b71f1699-42be-4515-930a-f3ef01f94aa7",
        "qbg_params": None
    }]

    def __init__(self, test):
        super().__init__()
        self.test = test

        # TODO(stephenfin): This should probably happen in setUp

        # The fixture allows port update so we need to deepcopy the class
        # variables to avoid test case interference.
        self._ports = {
            # NOTE(gibi)The port_with_sriov_resource_request cannot be added
            # globally in this fixture as it adds a second network that makes
            # auto allocation based test to fail due to ambiguous networks.
            self.port_1['id']: copy.deepcopy(self.port_1),
            self.port_with_resource_request['id']:
                copy.deepcopy(self.port_with_resource_request)
        }
        # Store multiple port bindings per port in a dict keyed by the host.
        # At startup we assume that none of the ports are bound.
        # {<port_id>: {<hostname>: <binding>}}
        self._port_bindings = collections.defaultdict(dict)

        # The fixture does not allow network, subnet or security group updates
        # so we don't have to deepcopy here
        self._networks = {
            self.network_1['id']: self.network_1
        }
        self._subnets = {
            self.subnet_1['id']: self.subnet_1,
            self.subnet_ipv6_1['id']: self.subnet_ipv6_1,
        }
        self._security_groups = {
            self.security_group['id']: self.security_group,
        }

    def setUp(self):
        super().setUp()

        # NOTE(gibi): This is the simplest way to unblock nova during live
        # migration. A nicer way would be to actually send network-vif-plugged
        # events to the nova-api from NeutronFixture when the port is bound but
        # calling nova API from this fixture needs a big surgery and sending
        # event right at the binding request means that such event will arrive
        # to nova earlier than the compute manager starts waiting for it.
        self.test.flags(vif_plugging_timeout=0)

        self.test.stub_out(
            'nova.network.neutron.API.add_fixed_ip_to_instance',
            lambda *args, **kwargs: network_model.NetworkInfo.hydrate(
                self.nw_info))
        self.test.stub_out(
            'nova.network.neutron.API.remove_fixed_ip_from_instance',
            lambda *args, **kwargs: network_model.NetworkInfo.hydrate(
                self.nw_info))

        self.test.stub_out(
            'nova.network.neutron.get_client', self._get_client)

    def _get_client(self, context, admin=False):
        # This logic is copied from nova.network.neutron._get_auth_plugin
        admin = admin or context.is_admin and not context.auth_token
        return _FakeNeutronClient(self, admin)

    def create_port_binding(self, port_id, body):
        if port_id not in self._ports:
            raise neutron_client_exc.NeutronClientException(status_code=404)

        port = self._ports[port_id]
        binding = copy.deepcopy(body['binding'])

        # NOTE(stephenfin): We don't allow changing of backend
        binding['vif_type'] = port['binding:vif_type']
        binding['vif_details'] = port['binding:vif_details']
        binding['vnic_type'] = port['binding:vnic_type']

        # the first binding is active by default
        if not self._port_bindings[port_id]:
            binding['status'] = 'ACTIVE'
        else:
            binding['status'] = 'INACTIVE'

        self._port_bindings[port_id][binding['host']] = binding

        return {'binding': binding}

    def _validate_port_binding(self, port_id, host_id):
        if port_id not in self._ports:
            raise neutron_client_exc.NeutronClientException(status_code=404)

        if host_id not in self._port_bindings[port_id]:
            raise neutron_client_exc.NeutronClientException(status_code=404)

    def delete_port_binding(self, port_id, host_id):
        self._validate_port_binding(port_id, host_id)
        del self._port_bindings[port_id][host_id]

    def _activate_port_binding(self, port_id, host_id, modify_port=False):
        # It makes sure that only one binding is active for a port
        for host, binding in self._port_bindings[port_id].items():
            if host == host_id:
                # NOTE(gibi): neutron returns 409 if this binding is already
                # active but nova does not depend on this behaviour yet.
                binding['status'] = 'ACTIVE'
                if modify_port:
                    # We need to ensure that port's binding:host_id is valid
                    self._merge_in_active_binding(self._ports[port_id])
            else:
                binding['status'] = 'INACTIVE'

    def activate_port_binding(self, port_id, host_id):
        self._validate_port_binding(port_id, host_id)
        self._activate_port_binding(port_id, host_id, modify_port=True)

    def show_port_binding(self, port_id, host_id):
        self._validate_port_binding(port_id, host_id)
        return {'binding': self._port_bindings[port_id][host_id]}

    def _list_resource(self, resources, retrieve_all, **_params):
        # If 'fields' is passed we need to strip that out since it will mess
        # up the filtering as 'fields' is not a filter parameter.
        _params.pop('fields', None)
        result = []
        for resource in resources.values():
            for key, val in _params.items():
                # params can be strings or lists/tuples and these need to be
                # handled differently
                if isinstance(val, list) or isinstance(val, tuple):
                    if not any(resource.get(key) == v for v in val):
                        break
                else:
                    if resource.get(key) != val:
                        break
            else:  # triggers if we didn't hit a break above
                result.append(copy.deepcopy(resource))
        return result

    def list_extensions(self, *args, **kwargs):
        return {
            'extensions': [
                {
                    # Copied from neutron-lib portbindings_extended.py
                    "updated": "2017-07-17T10:00:00-00:00",
                    "name": neutron_constants.PORT_BINDING_EXTENDED,
                    "links": [],
                    "alias": "binding-extended",
                    "description": "Expose port bindings of a virtual port to "
                                   "external application"
                }
            ]
        }

    def _get_active_binding(self, port_id):
        for host, binding in self._port_bindings[port_id].items():
            if binding['status'] == 'ACTIVE':
                return host, copy.deepcopy(binding)

        return None, {}

    def _merge_in_active_binding(self, port):
        """Update the port dict with the currently active port binding"""
        if port['id'] not in self._port_bindings:
            return

        _, binding = self._get_active_binding(port['id'])
        for key, value in binding.items():
            # keys in the binding is like 'vnic_type' but in the port response
            # they are like 'binding:vnic_type'. Except for the host_id that
            # is called 'host' in the binding but 'binding:host_id' in the
            # port response.
            if key != 'host':
                port['binding:' + key] = value
            else:
                port['binding:host_id'] = binding['host']

    def show_port(self, port_id, **_params):
        if port_id not in self._ports:
            raise exception.PortNotFound(port_id=port_id)

        port = copy.deepcopy(self._ports[port_id])
        self._merge_in_active_binding(port)

        # port.resource_request is admin only, if the client is not an admin
        # client then remove the content of the field from the response to
        # properly simulate neutron's behavior
        if not _params.get('is_admin', True):
            if 'resource_request' in port:
                port['resource_request'] = None

        return {'port': port}

    def delete_port(self, port_id, **_params):
        if port_id in self._ports:
            del self._ports[port_id]
            # Not all flow use explicit binding creation by calling
            # neutronv2.api.API.bind_ports_to_host(). Non live migration flows
            # simply update the port to bind it. So we need to delete bindings
            # conditionally
            if port_id in self._port_bindings:
                del self._port_bindings[port_id]

    def list_ports(self, is_admin, retrieve_all=True, **_params):
        ports = self._list_resource(self._ports, retrieve_all, **_params)
        for port in ports:
            self._merge_in_active_binding(port)
            # Neutron returns None instead of the real resource_request if
            # the ports are queried by a non-admin. So simulate this behavior
            # here
            if not is_admin:
                if 'resource_request' in port:
                    port['resource_request'] = None

        return {'ports': ports}

    def show_network(self, network_id, **_params):
        if network_id not in self._networks:
            raise neutron_client_exc.NetworkNotFoundClient()
        return {'network': copy.deepcopy(self._networks[network_id])}

    def list_networks(self, retrieve_all=True, **_params):
        return {
            'networks': self._list_resource(
                self._networks, retrieve_all, **_params,
            ),
        }

    def show_subnet(self, subnet_id, **_params):
        if subnet_id not in self._subnets:
            raise neutron_client_exc.NeutronClientException()
        return {'subnet': copy.deepcopy(self._subnets[subnet_id])}

    def list_subnets(self, retrieve_all=True, **_params):
        # NOTE(gibi): The fixture does not support filtering for subnets
        return {'subnets': copy.deepcopy(list(self._subnets.values()))}

    def list_floatingips(self, retrieve_all=True, **_params):
        return {'floatingips': []}

    def list_security_groups(self, retrieve_all=True, **_params):
        return {
            'security_groups': self._list_resource(
                self._security_groups, retrieve_all, **_params,
            ),
        }

    def create_port(self, body=None):
        body = body or {'port': {}}
        # Note(gibi): Some of the test expects that a pre-defined port is
        # created. This is port_2. So if that port is not created yet then
        # that is the one created here.
        new_port = copy.deepcopy(body['port'])
        new_port.update(copy.deepcopy(self.default_port))
        if self.default_port['id'] in self._ports:
            # If the port is already created then create a new port based on
            # the request body, the default port as a template, and assign new
            # port_id and mac_address for the new port
            # we need truly random uuids instead of named sentinels as some
            # tests needs more than 3 ports
            new_port.update({
                'id': str(uuidutils.generate_uuid()),
                'mac_address': '00:' + ':'.join(
                    ['%02x' % random.randint(0, 255) for _ in range(5)]),
            })
        self._ports[new_port['id']] = new_port
        # we need to copy again what we return as nova might modify the
        # returned port locally and we don't want that it effects the port in
        # the self._ports dict.
        return {'port': copy.deepcopy(new_port)}

    def update_port(self, port_id, body=None):
        port = self._ports[port_id]
        # We need to deepcopy here as well as the body can have a nested dict
        # which can be modified by the caller after this update_port call
        port.update(copy.deepcopy(body['port']))

        # update port binding

        if (
            'binding:host_id' in body['port'] and
            body['port']['binding:host_id'] is None
        ):
            # if the host_id is explicitly set to None, delete the binding
            host, _ = self._get_active_binding(port_id)
            del self._port_bindings[port_id][host]
        else:
            # else it's an update
            if 'binding:host_id' in body['port']:
                # if the host ID is present, update that specific binding
                host = body['port']['binding:host_id']
            else:
                # else update the active one
                host, _ = self._get_active_binding(port_id)

            update = {
                'host': host,
                'status': 'ACTIVE',
                'vif_type': port['binding:vif_type'],
                'vnic_type': port['binding:vnic_type'],
            }
            if body['port'].get('binding:profile'):
                update['profile'] = copy.deepcopy(
                    body['port']['binding:profile'])
            if body['port'].get('binding:vif_details'):
                update['vif_details'] = copy.deepcopy(
                    body['port']['binding:vif_details'])
            self._port_bindings[port_id][host] = update

            # mark any other active bindings as inactive
            self._activate_port_binding(port_id, host)

        return {'port': copy.deepcopy(port)}

    def show_quota(self, project_id):
        # unlimited quota
        return {'quota': {'port': -1}}

    def validate_auto_allocated_topology_requirements(self, project_id):
        # from https://github.com/openstack/python-neutronclient/blob/6.14.0/
        #  neutronclient/v2_0/client.py#L2009-L2011
        return self.get_auto_allocated_topology(project_id, fields=['dry-run'])

    def get_auto_allocated_topology(self, project_id, **_params):
        # from https://github.com/openstack/neutron/blob/14.0.0/
        #  neutron/services/auto_allocate/db.py#L134-L162
        if _params == {'fields': ['dry-run']}:
            return {'id': 'dry-run=pass', 'tenant_id': project_id}

        return {
            'auto_allocated_topology': {
                'id': self.network_1['id'],
                'tenant_id': project_id,
            }
        }
