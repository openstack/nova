# All Rights Reserved.
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
import logging

from keystoneauth1 import adapter
import mock
from neutronclient.common import exceptions as neutron_exception
import os_resource_classes as orc
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import instance_actions
from nova.compute import manager as compute_manager
from nova import context
from nova import exception
from nova.network import constants
from nova.network import neutron as neutronapi
from nova import objects
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova.scheduler import utils
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import NeutronFixture
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_requests
from nova.virt import fake

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class ResourceRequestNeutronFixture(NeutronFixture):
    port_with_sriov_resource_request = {
        'id': '7059503b-a648-40fd-a561-5ca769304bee',
        'name': '',
        'description': '',
        'network_id': NeutronFixture.network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c5',
        # Do neutron really adds fixed_ips to an direct vnic_type port?
        'fixed_ips': [
            {
                'ip_address': '192.168.13.3',
                'subnet_id': NeutronFixture.subnet_2['id']
            }
        ],
        'tenant_id': NeutronFixture.tenant_id,
        'project_id': NeutronFixture.tenant_id,
        'device_id': '',
        'resource_request': {
            "resources": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: 10000,
                orc.NET_BW_EGR_KILOBIT_PER_SEC: 10000},
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_DIRECT"]
        },
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'direct',
        'port_security_enabled': False,
    }
    port_macvtap_with_resource_request = {
        'id': 'cbb9707f-3559-4675-a973-4ea89c747f02',
        'name': '',
        'description': '',
        'network_id': NeutronFixture.network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c6',
        # Do neutron really adds fixed_ips to an direct vnic_type port?
        'fixed_ips': [
            {
                'ip_address': '192.168.13.4',
                'subnet_id': NeutronFixture.subnet_2['id']
            }
        ],
        'tenant_id': NeutronFixture.tenant_id,
        'project_id': NeutronFixture.tenant_id,
        'device_id': '',
        'resource_request': {
            "resources": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: 10000,
                orc.NET_BW_EGR_KILOBIT_PER_SEC: 10000},
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_MACVTAP"]
        },
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'hw_veb',
        'binding:vnic_type': 'macvtap',
        'port_security_enabled': False,
    }

    def __init__(self, test):
        super().__init__(test)
        # add extra ports and the related network to the neutron fixture
        # specifically for resource_request tests. It cannot be added globally
        # in the base fixture init as it adds a second network that makes auto
        # allocation based test to fail due to ambiguous networks.
        self._ports[
            self.port_with_sriov_resource_request['id']] = \
            copy.deepcopy(self.port_with_sriov_resource_request)
        self._ports[self.sriov_port['id']] = \
            copy.deepcopy(self.sriov_port)
        self._networks[
            self.network_2['id']] = self.network_2
        self._subnets[
            self.subnet_2['id']] = self.subnet_2
        macvtap = self.port_macvtap_with_resource_request
        self._ports[macvtap['id']] = copy.deepcopy(macvtap)


class ExtendedResourceRequestNeutronFixture(ResourceRequestNeutronFixture):
    @classmethod
    def create_with_existing_neutron_state(cls, existing_fixture):
        """Creates a new fixture but initialize it from an existing neutron
        fixture to carry over the state from it.
        """
        fixture = cls(existing_fixture.test)
        fixture._ports = existing_fixture._ports
        fixture._networks = existing_fixture._networks
        fixture._subnets = existing_fixture._subnets
        return fixture

    def list_extensions(self, *args, **kwargs):
        extensions = super().list_extensions(*args, **kwargs)
        extensions['extensions'].append(
            # As defined in neutron_lib/api/definitions/
            # port_resource_request_groups.py
            {
                "updated": "2021-08-02T10:00:00-00:00",
                "name": constants.RESOURCE_REQUEST_GROUPS_EXTENSION,
                "links": [],
                "alias": "port-resource-request-groups",
                "description":
                    "Support requesting multiple groups of resources and "
                    "traits from the same RP subtree in resource_request"
            }
        )
        return extensions

    def _translate_port_to_new_resource_request(self, port):
        """Translates the old resource request definition to the new format in
        place.
        """
        # NOTE(gibi): Neutron sends the new format if
        # port-resource-request-groups API extension is enabled.
        # TODO(gibi): make this the default definition format after nova
        # not need to support the old format any more which will happen after
        # Neutron does not support the old format any more.
        # old format:
        #
        # 'resource_request': {
        #     "resources": {
        #             orc.NET_BW_IGR_KILOBIT_PER_SEC: 1000,
        #             orc.NET_BW_EGR_KILOBIT_PER_SEC: 1000},
        #     "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_NORMAL"]
        # },
        #
        # new format:
        #
        # 'resource_request': {
        #    "request_groups":
        #    [
        #        {
        #            "id": "group1",
        #            "required": [<CUSTOM_VNIC_TYPE traits>],
        #            "resources":
        #            {
        #                NET_KILOPACKET_PER_SEC:
        #                <amount requested via the QoS policy>
        #            }
        #        },
        #        {
        #            "id": "group2",
        #            "required": [<CUSTOM_PHYSNET_ traits>,
        #                         <CUSTOM_VNIC_TYPE traits>],
        #            "resources":
        #            {
        #                <NET_BW_[E|I]GR_KILOBIT_PER_SEC resource class name>:
        #                <requested bandwidth amount from the QoS policy>
        #            }
        #        },
        #    ],
        #    "same_subtree": ["group1", "group2"]
        # }
        groups = []
        same_subtree = []
        # NOTE(gibi): in case of the old format Neutron sends None in the
        # resource_request if the port has no QoS policy implicating
        # resource request.
        res_req = port.get('resource_request') or {}
        if 'request_groups' in res_req:
            # this is already a port with new resource_request format no
            # translation is needed
            return
        # So we have the old format, translate it
        old_rr = res_req
        # NOTE(gibi): In the new format Neutron also sends None if the port
        # has no QoS policy implicating resource request
        new_rr = None
        if old_rr:
            # use the port id as group id as we know that in the old format
            # we can have only one group per port
            old_rr['id'] = port['id']
            # nest the old request as one of the groups in the new format
            groups.append(old_rr)
            # Neutron might generate an empty list if only one group is
            # requested, but it is equally correct to list that single group
            # as well. We do the later as that allows some testing already with
            # a single group
            same_subtree = [old_rr['id']]

            new_rr = {
                "request_groups": groups,
                "same_subtree": same_subtree
            }

        port['resource_request'] = new_rr

    def show_port(self, port_id, **_params):
        port_dict = super().show_port(port_id, **_params)
        # this is an in place transformation but it is OK as the base class
        # returns a deep copy of the port
        self._translate_port_to_new_resource_request(port_dict['port'])
        return port_dict

    def list_ports(self, is_admin, retrieve_all=True, **_params):
        ports_dict = super().list_ports(is_admin, retrieve_all=True, **_params)
        for port in ports_dict['ports']:
            # this is an in place transformation but it is OK as the base class
            # returns a deep copy of the port
            self._translate_port_to_new_resource_request(port)
        return ports_dict


class MultiGroupResourceRequestNeutronFixture(
        ExtendedResourceRequestNeutronFixture):
    # NOTE(gibi): We redefine the port_with_resource_request from the base
    # NeutronFixture to have both bw and pps resource requests
    port_with_resource_request = {
        'id': '2f2613ce-95a9-490a-b3c4-5f1c28c1f886',
        'name': '',
        'description': '',
        'network_id': NeutronFixture.network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c3',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.42',
                'subnet_id': NeutronFixture.subnet_1['id']
            }
        ],
        'tenant_id': NeutronFixture.tenant_id,
        'project_id': NeutronFixture.tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vif_details': {},
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
        'resource_request': {
            "request_groups": [
                {
                    "id": "a1ffd1f7-8e17-4254-bdf2-f07fd9220e4b",
                    "resources": {
                        orc.NET_BW_IGR_KILOBIT_PER_SEC: 1000,
                        orc.NET_BW_EGR_KILOBIT_PER_SEC: 1000},
                    "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_NORMAL"]
                },
                {
                    "id": "a2ffa7b3-a623-4922-946c-25476efdec97",
                    "resources": {
                        orc.NET_PACKET_RATE_KILOPACKET_PER_SEC: 1000
                    },
                    "required": ["CUSTOM_VNIC_TYPE_NORMAL"]
                }
            ],
            "same_subtree": [
                "a1ffd1f7-8e17-4254-bdf2-f07fd9220e4b",
                "a2ffa7b3-a623-4922-946c-25476efdec97"
            ],
        },
        'port_security_enabled': True,
        'security_groups': [
            NeutronFixture.security_group['id'],
        ],
    }


class PortResourceRequestBasedSchedulingTestBase(
        integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.FakeDriverWithPciResources'

    CUSTOM_VNIC_TYPE_NORMAL = 'CUSTOM_VNIC_TYPE_NORMAL'
    CUSTOM_VNIC_TYPE_DIRECT = 'CUSTOM_VNIC_TYPE_DIRECT'
    CUSTOM_VNIC_TYPE_MACVTAP = 'CUSTOM_VNIC_TYPE_MACVTAP'
    CUSTOM_PHYSNET1 = 'CUSTOM_PHYSNET1'
    CUSTOM_PHYSNET2 = 'CUSTOM_PHYSNET2'
    CUSTOM_PHYSNET3 = 'CUSTOM_PHYSNET3'
    PF1 = 'pf1'
    PF2 = 'pf2'
    PF3 = 'pf3'

    def setUp(self):
        # enable PciPassthroughFilter to support SRIOV before the base class
        # starts the scheduler
        if 'PciPassthroughFilter' not in CONF.filter_scheduler.enabled_filters:
            self.flags(
                enabled_filters=CONF.filter_scheduler.enabled_filters +
                                ['PciPassthroughFilter'],
                group='filter_scheduler')

        self.useFixture(
            fake.FakeDriverWithPciResources.
                FakeDriverWithPciResourcesConfigFixture())

        super(PortResourceRequestBasedSchedulingTestBase, self).setUp()
        # override the default neutron fixture by mocking over it
        self.neutron = self.useFixture(
            ResourceRequestNeutronFixture(self))
        # Make ComputeManager._allocate_network_async synchronous to detect
        # errors in tests that involve rescheduling.
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())
        self.compute1 = self._start_compute('host1')
        self.compute1_rp_uuid = self._get_provider_uuid_by_host('host1')
        self.compute1_service_id = self.admin_api.get_services(
            host='host1', binary='nova-compute')[0]['id']
        self.ovs_agent_rp_per_host = {}
        self.ovs_bridge_rp_per_host = {}
        self.sriov_dev_rp_per_host = {}
        self.flavor = self.api.get_flavors()[0]
        self.flavor_with_group_policy = self.api.get_flavors()[1]

        # Setting group policy for placement. This is mandatory when more than
        # one request group is included in the allocation candidate request and
        # we have tests with two ports both having resource request modelled as
        # two separate request groups.
        self.admin_api.post_extra_spec(
            self.flavor_with_group_policy['id'],
            {'extra_specs': {'group_policy': 'isolate'}})

        self._create_networking_rp_tree('host1', self.compute1_rp_uuid)

    def assertComputeAllocationMatchesFlavor(
            self, allocations, compute_rp_uuid, flavor):
        compute_allocations = allocations[compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

    def _create_server(self, flavor, networks, host=None):
        server_req = self._build_server(
            image_uuid='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            flavor_id=flavor['id'],
            networks=networks,
            host=host)
        return self.api.post_server({'server': server_req})

    def _set_provider_inventories(self, rp_uuid, inventories):
        rp = self.placement.get(
            '/resource_providers/%s' % rp_uuid).body
        inventories['resource_provider_generation'] = rp['generation']
        return self._update_inventory(rp_uuid, inventories)

    def _create_ovs_networking_rp_tree(self, compute_rp_uuid):
        # we need uuid sentinel for the test to make pep8 happy but we need a
        # unique one per compute so here is some ugliness
        ovs_agent_rp_uuid = getattr(uuids, compute_rp_uuid + 'ovs agent')
        agent_rp_req = {
            "name": ovs_agent_rp_uuid,
            "uuid": ovs_agent_rp_uuid,
            "parent_provider_uuid": compute_rp_uuid
        }
        self.placement.post(
            '/resource_providers', body=agent_rp_req, version='1.20')
        self.ovs_agent_rp_per_host[compute_rp_uuid] = ovs_agent_rp_uuid
        ovs_bridge_rp_uuid = getattr(uuids, ovs_agent_rp_uuid + 'ovs br')
        ovs_bridge_req = {
            "name": ovs_bridge_rp_uuid,
            "uuid": ovs_bridge_rp_uuid,
            "parent_provider_uuid": ovs_agent_rp_uuid
        }
        self.placement.post(
            '/resource_providers', body=ovs_bridge_req, version='1.20')
        self.ovs_bridge_rp_per_host[compute_rp_uuid] = ovs_bridge_rp_uuid

        self._set_provider_inventories(
            ovs_agent_rp_uuid,
            {"inventories": {
                orc.NET_PACKET_RATE_KILOPACKET_PER_SEC: {"total": 10000},
            }})

        self._set_provider_inventories(
            ovs_bridge_rp_uuid,
            {"inventories": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 10000},
                orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 10000},
            }})

        self._create_trait(self.CUSTOM_VNIC_TYPE_NORMAL)
        self._create_trait(self.CUSTOM_PHYSNET2)

        self._set_provider_traits(
            ovs_agent_rp_uuid, [self.CUSTOM_VNIC_TYPE_NORMAL])

        self._set_provider_traits(
            ovs_bridge_rp_uuid,
            [self.CUSTOM_VNIC_TYPE_NORMAL, self.CUSTOM_PHYSNET2])

    def _create_pf_device_rp(
            self, device_rp_uuid, parent_rp_uuid, inventories, traits,
            device_rp_name=None):
        """Create a RP in placement for a physical function network device with
        traits and inventories.
        """

        if not device_rp_name:
            device_rp_name = device_rp_uuid

        sriov_pf_req = {
            "name": device_rp_name,
            "uuid": device_rp_uuid,
            "parent_provider_uuid": parent_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=sriov_pf_req,
                                version='1.20')

        self._set_provider_inventories(
            device_rp_uuid,
            {"inventories": inventories})

        for trait in traits:
            self._create_trait(trait)

        self._set_provider_traits(
            device_rp_uuid,
            traits)

    def _create_sriov_networking_rp_tree(self, hostname, compute_rp_uuid):
        # Create a matching RP tree in placement for the PCI devices added to
        # the passthrough_whitelist config during setUp() and PCI devices
        # present in the FakeDriverWithPciResources virt driver.
        #
        # * PF1 represents the PCI device 0000:01:00, it will be mapped to
        # physnet1 and it will have bandwidth inventory.
        # * PF2 represents the PCI device 0000:02:00, it will be mapped to
        # physnet2 it will have bandwidth inventory.
        # * PF3 represents the PCI device 0000:03:00 and, it will be mapped to
        # physnet2 but it will not have bandwidth inventory.
        self.sriov_dev_rp_per_host[compute_rp_uuid] = {}

        sriov_agent_rp_uuid = getattr(uuids, compute_rp_uuid + 'sriov agent')
        agent_rp_req = {
            "name": "%s:NIC Switch agent" % hostname,
            "uuid": sriov_agent_rp_uuid,
            "parent_provider_uuid": compute_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=agent_rp_req,
                                version='1.20')
        dev_rp_name_prefix = ("%s:NIC Switch agent:" % hostname)

        sriov_pf1_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF1')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF1] = sriov_pf1_rp_uuid

        inventories = {
            orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 100000},
            orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 100000},
        }
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_PHYSNET1]
        self._create_pf_device_rp(
            sriov_pf1_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens1" % hostname)

        sriov_pf2_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF2')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF2] = sriov_pf2_rp_uuid
        inventories = {
            orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 100000},
            orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 100000},
        }
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_VNIC_TYPE_MACVTAP,
                  self.CUSTOM_PHYSNET2]
        self._create_pf_device_rp(
            sriov_pf2_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens2" % hostname)

        sriov_pf3_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF3')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF3] = sriov_pf3_rp_uuid
        inventories = {}
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_PHYSNET2]
        self._create_pf_device_rp(
            sriov_pf3_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens3" % hostname)

    def _create_networking_rp_tree(self, hostname, compute_rp_uuid):
        # let's simulate what the neutron would do
        self._create_ovs_networking_rp_tree(compute_rp_uuid)
        self._create_sriov_networking_rp_tree(hostname, compute_rp_uuid)

    def assertPortMatchesAllocation(self, port, allocations, compute_rp_uuid):
        # The goal here is to grab the part of the allocation that is due to
        # the port. We assume that all the normal ports are handled by OVS
        # while the rest is handled by SRIOV agent. This is true in our func
        # test setup, see the RP tree structure created in
        # _create_networking_rp_tree(), so it safe to assume here. So we select
        # the OVS / SRIOV part of the allocation.
        if port['binding:vnic_type'] == 'normal':
            bw_allocations = allocations[
                self.ovs_bridge_rp_per_host[compute_rp_uuid]]['resources']
        else:
            bw_allocations = allocations[
                self.sriov_dev_rp_per_host[
                    compute_rp_uuid][self.PF2]]['resources']

        port_request = port[constants.RESOURCE_REQUEST]['resources']
        # So now we have what is requested via port_request, and what was
        # allocated due to the port in bw_allocations. So we just need to see
        # the they are matching.
        for rc, amount in bw_allocations.items():
            self.assertEqual(port_request[rc], amount,
                             'port %s requested %d %s '
                             'resources but got allocation %d' %
                             (port['id'], port_request[rc], rc,
                              amount))

    def _create_server_with_ports(self, *ports):
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': port['id']} for port in ports],
            host='host1')
        return self._wait_for_state_change(server, 'ACTIVE')

    def _check_allocation(
            self, server, compute_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, flavor, migration_uuid=None,
            source_compute_rp_uuid=None, new_flavor=None):

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # if there is new_flavor then we either have an in progress resize or
        # a confirmed resize. In both cases the instance allocation should be
        # according to the new_flavor
        current_flavor = (new_flavor if new_flavor else flavor)

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the ports having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_non_qos_port,
                updated_qos_port,
                updated_qos_sriov_port
            ),
            len(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, compute_rp_uuid, current_flavor)
        self.assertPortMatchesAllocation(
            updated_qos_port, allocations, compute_rp_uuid)
        self.assertPortMatchesAllocation(
            updated_qos_sriov_port, allocations, compute_rp_uuid)

        self._assert_port_binding_profile_allocation(
            updated_qos_port, compute_rp_uuid)
        self._assert_port_binding_profile_allocation(
            updated_qos_sriov_port, compute_rp_uuid)
        self._assert_port_binding_profile_allocation(
            updated_non_qos_port, compute_rp_uuid)

        if migration_uuid:
            migration_allocations = self.placement.get(
                '/allocations/%s' % migration_uuid).body['allocations']

            # We expect one set of allocations for the compute resources on the
            # compute rp plus the allocations due to the ports having resource
            # requests
            self.assertEqual(
                1 + self._get_number_of_expected_allocations_for_ports(
                    updated_non_qos_port,
                    updated_qos_port,
                    updated_qos_sriov_port
                ),
                len(allocations))
            self.assertComputeAllocationMatchesFlavor(
                migration_allocations, source_compute_rp_uuid, flavor)
            self.assertPortMatchesAllocation(
                updated_qos_port,
                migration_allocations,
                source_compute_rp_uuid
            )
            self.assertPortMatchesAllocation(
                updated_qos_sriov_port,
                migration_allocations,
                source_compute_rp_uuid
            )

    def _delete_server_and_check_allocations(
            self, server, qos_port, qos_sriov_port):
        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding of the
        # ports that got allocation during the bind
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        binding_profile = updated_qos_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']
        binding_profile = updated_qos_sriov_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def _create_server_with_ports_and_check_allocation(
            self, non_qos_normal_port, qos_normal_port, qos_sriov_port):
        server = self._create_server_with_ports(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)
        # check that the server allocates from the current host properly
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)
        return server

    def _assert_pci_request_pf_device_name(self, server, device_name):
        ctxt = context.get_admin_context()
        pci_requests = objects.InstancePCIRequests.get_by_instance_uuid(
            ctxt, server['id'])
        self.assertEqual(1, len(pci_requests.requests))
        self.assertEqual(1, len(pci_requests.requests[0].spec))
        self.assertEqual(
            device_name,
            pci_requests.requests[0].spec[0]['parent_ifname'])

    def _assert_port_binding_profile_allocation(self, port, compute_rp_uuid):
        if port.get('resource_request', {}):
            if port['binding:vnic_type'] == "normal":
                # Normal ports are expected to have allocation on the OVS RP
                expected_allocation = self.ovs_bridge_rp_per_host[
                    compute_rp_uuid]
            else:
                # SRIOV ports are expected to have allocation on the PF2 RP
                # see _create_sriov_networking_rp_tree() for details.
                expected_allocation = self.sriov_dev_rp_per_host[
                    compute_rp_uuid][self.PF2]
            self.assertEqual(
                expected_allocation,
                port['binding:profile']['allocation'])
        else:
            # if no resource request then we expect no allocation key in the
            # binding profile
            self.assertNotIn(
                'allocation', port['binding:profile'])

    def _get_number_of_expected_allocations_for_ports(self, *ports):
        # we expect one for each port that has resource request
        return len(
            [port for port in ports if port.get('resource_request')]
        )


class UnsupportedPortResourceRequestBasedSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Tests for handling servers with ports having resource requests """

    def _add_resource_request_to_a_bound_port(self, port_id):
        # NOTE(gibi): self.neutron._ports contains a copy of each neutron port
        # defined on class level in the fixture. So modifying what is in the
        # _ports list is safe as it is re-created for each Neutron fixture
        # instance therefore for each individual test using that fixture.
        bound_port = self.neutron._ports[port_id]
        bound_port[constants.RESOURCE_REQUEST] = (
            self.neutron.port_with_resource_request[
                constants.RESOURCE_REQUEST])

    def test_interface_attach_with_resource_request_old_compute(self):
        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # simulate that the compute the instance is running on is older than
        # when support is added for attach, older than service version 55
        orig_get_service = objects.Service.get_by_host_and_binary

        def fake_get_service(context, host, binary):
            service = orig_get_service(context, host, binary)
            service.version = 54
            return service

        with mock.patch(
            'nova.objects.Service.get_by_host_and_binary',
            side_effect=fake_get_service
        ):
            # try to add a port with resource request
            post = {
                'interfaceAttachment': {
                    'port_id': self.neutron.port_with_resource_request['id']
                }}
            ex = self.assertRaises(
                client.OpenStackApiException, self.api.attach_interface,
                server['id'], post)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Attaching interfaces with QoS policy is '
                      'not supported for instance',
                      str(ex))

    @mock.patch('nova.tests.fixtures.NeutronFixture.create_port')
    def test_interface_attach_with_network_create_port_has_resource_request(
            self, mock_neutron_create_port):
        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # the interfaceAttach operation below will result in a new port being
        # created in the network that is attached. Make sure that neutron
        # returns a port that has resource request.
        mock_neutron_create_port.return_value = (
            {'port': copy.deepcopy(self.neutron.port_with_resource_request)})

        # try to attach a network
        post = {
            'interfaceAttachment': {
                'net_id': self.neutron.network_1['id']
        }}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.attach_interface,
                               server['id'], post)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Using networks with QoS policy is not supported for '
                      'instance',
                      str(ex))

    @mock.patch('nova.tests.fixtures.NeutronFixture.create_port')
    def test_create_server_with_network_create_port_has_resource_request(
            self, mock_neutron_create_port):
        # the server create operation below will result in a new port being
        # created in the network. Make sure that neutron returns a port that
        # has resource request.
        mock_neutron_create_port.return_value = (
            {'port': copy.deepcopy(self.neutron.port_with_resource_request)})

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'uuid': self.neutron.network_1['id']}])
        server = self._wait_for_state_change(server, 'ERROR')

        self.assertEqual(500, server['fault']['code'])
        self.assertIn('Failed to allocate the network',
                      server['fault']['message'])

    def test_create_server_with_port_resource_request_old_microversion(self):

        # NOTE(gibi): 2.71 is the last microversion where nova does not support
        # this kind of create server
        self.api.microversion = '2.71'
        ex = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_with_resource_request['id']}])

        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "Creating servers with ports having resource requests, like a "
            "port with a QoS minimum bandwidth policy, is not supported "
            "until microversion 2.72.",
            str(ex))


class NonAdminUnsupportedPortResourceRequestBasedSchedulingTest(
        UnsupportedPortResourceRequestBasedSchedulingTest):

    def setUp(self):
        super(
            NonAdminUnsupportedPortResourceRequestBasedSchedulingTest,
            self).setUp()
        # switch to non admin api
        self.api = self.api_fixture.api
        self.api.microversion = self.microversion

        # allow non-admin to call the operations
        self.policy.set_rules({
            'os_compute_api:servers:create': '@',
            'os_compute_api:servers:create:attach_network': '@',
            'os_compute_api:servers:show': '@',
            'os_compute_api:os-attach-interfaces': '@',
            'os_compute_api:os-attach-interfaces:create': '@',
            'os_compute_api:os-shelve:shelve': '@',
            'os_compute_api:os-shelve:unshelve': '@',
            'os_compute_api:os-migrate-server:migrate_live': '@',
            'os_compute_api:os-evacuate': '@',
        })


class PortResourceRequestBasedSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Tests creating a server with a pre-existing port that has a resource
    request for a QoS minimum bandwidth policy.
    """

    def test_boot_server_with_two_ports_one_having_resource_request(self):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': non_qos_port['id']},
                      {'port': qos_port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')
        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the ports having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_qos_port, updated_non_qos_port),
            len(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            updated_qos_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            updated_qos_port, self.compute1_rp_uuid)

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding of the
        # port that got allocation during the bind
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        binding_profile = updated_qos_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_one_ovs_one_sriov_port(self):
        ovs_port = self.neutron.port_with_resource_request
        sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server(flavor=self.flavor_with_group_policy,
                                     networks=[{'port': ovs_port['id']},
                                               {'port': sriov_port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        ovs_port = self.neutron.show_port(ovs_port['id'])['port']
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the ports having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                ovs_port, sriov_port),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor_with_group_policy)

        self.assertPortMatchesAllocation(
            ovs_port, allocations, self.compute1_rp_uuid)
        self.assertPortMatchesAllocation(
            sriov_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            ovs_port, self.compute1_rp_uuid)
        self._assert_port_binding_profile_allocation(
            sriov_port, self.compute1_rp_uuid)

    def test_interface_attach_with_resource_request(self):
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # start a second compute to show that resources are only allocated from
        # the compute the instance currently runs on
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # attach an OVS port with resource request
        ovs_port = self.neutron.port_with_resource_request
        post = {
            'interfaceAttachment': {
                'port_id': ovs_port['id']
        }}
        self.api.attach_interface(server['id'], post)

        ovs_port = self.neutron.show_port(ovs_port['id'])['port']
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the port having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                ovs_port),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            ovs_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            ovs_port, self.compute1_rp_uuid)

        # now attach an SRIOV port
        sriov_port = self.neutron.port_with_sriov_resource_request
        post = {
            'interfaceAttachment': {
                'port_id': sriov_port['id']
        }}
        self.api.attach_interface(server['id'], post)

        ovs_port = self.neutron.show_port(ovs_port['id'])['port']
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the ports having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                ovs_port, sriov_port),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            ovs_port, allocations, self.compute1_rp_uuid)
        self.assertPortMatchesAllocation(
            sriov_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            ovs_port, self.compute1_rp_uuid)
        self._assert_port_binding_profile_allocation(
            sriov_port, self.compute1_rp_uuid)

    def test_interface_attach_with_resource_request_no_candidates(self):
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # decrease the resource inventory so that the OVS port will not fit
        self._set_provider_inventories(
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
            {"inventories": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 10},
                orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 10},
            }})

        # try to attach an OVS port with too big resource request
        ovs_port = self.neutron.port_with_resource_request

        post = {
            'interfaceAttachment': {
                'port_id': ovs_port['id']
        }}
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.attach_interface,
            server['id'], post)

        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Failed to allocate additional resources', str(ex))
        self.assertNotIn(
            'Failed to retrieve allocation candidates from placement API',
            self.stdlog.logger.output)

    def test_interface_attach_with_resource_request_pci_claim_fails(self):
        # boot a server with a single SRIOV port that has no resource request
        sriov_port = self.neutron.sriov_port
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': sriov_port['id']}])

        self._wait_for_state_change(server, 'ACTIVE')
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']
        sriov_binding = sriov_port['binding:profile']

        # We expect that this consume the last available VF from the PF2
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            sriov_binding['pci_slot'])

        # Now attach a second port to this server that has resource request
        # At this point PF2 has available bandwidth but no available VF
        # and PF3 has available VF but no available bandwidth so we expect
        # the attach to fail.
        sriov_port_with_res_req = self.neutron.port_with_sriov_resource_request
        post = {
            'interfaceAttachment': {
                'port_id': sriov_port_with_res_req['id']
        }}
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.attach_interface,
            server['id'], post)

        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Failed to claim PCI device', str(ex))

        sriov_port_with_res_req = self.neutron.show_port(
            sriov_port_with_res_req['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect only one allocations that is on the compute RP as the
        # allocation made towards the PF2 RP has been rolled back when the PCI
        # claim failed
        self.assertEqual([self.compute1_rp_uuid], list(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        # We expect that the port binding is not updated with any RP uuid as
        # the attach failed.
        sriov_binding = sriov_port_with_res_req['binding:profile']
        self.assertNotIn('allocation', sriov_binding)

    def test_interface_attach_sriov_with_qos_pci_update_fails(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the sriov interface is attached.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute1_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        sriov_port = self.neutron.port_with_sriov_resource_request
        post = {
            'interfaceAttachment': {
                'port_id': sriov_port['id']
        }}
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.attach_interface,
            server['id'], post)

        self.assertEqual(500, ex.response.status_code)
        self.assertIn('UnexpectedResourceProviderNameForPCIRequest', str(ex))

        sriov_port = self.neutron.show_port(sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect only one allocations that is on the compute RP as the
        # allocation made towards the PF2 RP has been rolled back when the PCI
        # update failed
        self.assertEqual([self.compute1_rp_uuid], list(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        # We expect that the port binding is not updated with any RP uuid as
        # the attach failed.
        sriov_binding = sriov_port['binding:profile']
        self.assertNotIn('allocation', sriov_binding)

    def test_interface_attach_sriov_with_qos_pci_update_fails_cleanup_fails(
        self
    ):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the sriov interface is attached.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute1_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        sriov_port = self.neutron.port_with_sriov_resource_request
        post = {
            'interfaceAttachment': {
                'port_id': sriov_port['id']
        }}

        orig_put = adapter.Adapter.put

        conflict_rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        self.adapter_put_call_count = 0

        def fake_put(_self, url, **kwargs):
            self.adapter_put_call_count += 1
            if self.adapter_put_call_count == 1:
                # allocation update to add the port resource request
                return orig_put(_self, url, **kwargs)
            else:
                # cleanup calls to remove the port resource allocation
                return conflict_rsp

        # this mock makes sure that the placement cleanup will fail with
        # conflict
        with mock.patch('keystoneauth1.adapter.Adapter.put', new=fake_put):
            ex = self.assertRaises(
                client.OpenStackApiException, self.api.attach_interface,
                server['id'], post)

            self.assertEqual(500, ex.response.status_code)
            self.assertIn('AllocationUpdateFailed', str(ex))
            # we have a proper log about the leak
            PF_rp_uuid = self.sriov_dev_rp_per_host[
                self.compute1_rp_uuid][self.PF2]
            self.assertIn(
                "nova.exception.AllocationUpdateFailed: Failed to update "
                "allocations for consumer %s. Error: Cannot remove "
                "resources {'%s': "
                "{'resources': {'NET_BW_EGR_KILOBIT_PER_SEC': 10000, "
                "'NET_BW_IGR_KILOBIT_PER_SEC': 10000}}} from the allocation "
                "due to multiple successive generation conflicts in "
                "placement." % (server['id'], PF_rp_uuid),
                self.stdlog.logger.output)

            # assert that we retried the cleanup multiple times
            self.assertEqual(5, self.adapter_put_call_count)

        sriov_port = self.neutron.show_port(sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # As the cleanup failed we leaked allocation in placement
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                sriov_port),
            len(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        # this is the leaked allocation in placement
        self.assertPortMatchesAllocation(
            sriov_port, allocations, self.compute1_rp_uuid)

        sriov_dev_rp = self.sriov_dev_rp_per_host[
            self.compute1_rp_uuid][self.PF2]
        allocations[sriov_dev_rp].pop('generation')
        leaked_allocation = {sriov_dev_rp: allocations[sriov_dev_rp]}
        self.assertIn(
            f'Failed to update allocations for consumer {server["id"]}. '
            f'Error: Cannot remove resources {leaked_allocation} from the '
            f'allocation due to multiple successive generation conflicts in '
            f'placement. To clean up the leaked resource allocation you can '
            f'use nova-manage placement audit.',
            self.stdlog.logger.output)

        # We expect that the port binding is not updated with any RP uuid as
        # the attach failed.
        sriov_binding = sriov_port['binding:profile']
        self.assertNotIn('allocation', sriov_binding)

    def test_interface_detach_with_port_with_bandwidth_request(self):
        port = self.neutron.port_with_resource_request

        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        updated_port = self.neutron.show_port(port['id'])['port']
        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the port having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_port),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            updated_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            updated_port, self.compute1_rp_uuid)

        self.api.detach_interface(
            server['id'], self.neutron.port_with_resource_request['id'])

        self.notifier.wait_for_versioned_notifications(
            'instance.interface_detach.end')

        updated_port = self.neutron.show_port(
            self.neutron.port_with_resource_request['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect that the port related resource allocations are removed
        self.assertEqual(1, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        # We expect that the allocation is removed from the port too
        binding_profile = updated_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_delete_bound_port_in_neutron_with_resource_request(self):
        """Neutron sends a network-vif-deleted os-server-external-events
        notification to nova when a bound port is deleted. Nova detaches the
        vif from the server. If the port had a resource allocation then that
        allocation is leaked. This test makes sure that 1) an ERROR is logged
        when the leak happens. 2) the leaked resource is reclaimed when the
        server is deleted.
        """
        port = self.neutron.port_with_resource_request

        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        updated_port = self.neutron.show_port(port['id'])['port']
        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the port having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_port),
            len(allocations))

        compute_allocations = allocations[self.compute1_rp_uuid]['resources']
        self.assertEqual(self._resources_from_flavor(self.flavor),
                         compute_allocations)
        self.assertPortMatchesAllocation(
            updated_port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            updated_port, self.compute1_rp_uuid)

        # neutron is faked in the functional test so this test just sends in
        # a os-server-external-events notification to trigger the
        # detach + ERROR log.
        events = {
            "events": [
                {
                    "name": "network-vif-deleted",
                    "server_uuid": server['id'],
                    "tag": port['id'],
                }
            ]
        }
        response = self.api.api_post('/os-server-external-events', events).body
        self.assertEqual(200, response['events'][0]['code'])

        # 1) Nova logs an ERROR about the leak
        self._wait_for_log(
            'The bound port %(port_id)s is deleted in Neutron but the '
            'resource allocation on the resource providers .* are leaked '
            'until the server %(server_uuid)s is deleted.'
            % {'port_id': port['id'],
               'server_uuid': server['id']})

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # Nova leaks the port allocation so the server still has the same
        # allocation before the port delete.
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_port),
            len(allocations))

        compute_allocations = allocations[self.compute1_rp_uuid]['resources']

        self.assertEqual(self._resources_from_flavor(self.flavor),
                         compute_allocations)
        self.assertPortMatchesAllocation(
            updated_port, allocations, self.compute1_rp_uuid)

        # 2) Also nova will reclaim the leaked resource during the server
        # delete
        self._delete_and_check_allocations(server)

    def test_two_sriov_ports_one_with_request_two_available_pfs(self):
        """Verify that the port's bandwidth allocated from the same PF as
        the allocated VF.

        One compute host:
        * PF1 (0000:01:00) is configured for physnet1
        * PF2 (0000:02:00) is configured for physnet2, with 1 VF and bandwidth
          inventory
        * PF3 (0000:03:00) is configured for physnet2, with 1 VF but without
          bandwidth inventory

        One instance will be booted with two neutron ports, both ports
        requested to be connected to physnet2. One port has resource request
        the other does not have resource request. The port having the resource
        request cannot be allocated to PF3 and PF1 while the other port that
        does not have resource request can be allocated to PF2 or PF3.

        For the detailed compute host config see the FakeDriverWithPciResources
        class. For the necessary passthrough_whitelist config see the setUp of
        the PortResourceRequestBasedSchedulingTestBase class.
        """

        sriov_port = self.neutron.sriov_port
        sriov_port_with_res_req = self.neutron.port_with_sriov_resource_request
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[
                {'port': sriov_port_with_res_req['id']},
                {'port': sriov_port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        sriov_port = self.neutron.show_port(sriov_port['id'])['port']
        sriov_port_with_res_req = self.neutron.show_port(
            sriov_port_with_res_req['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the port having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                sriov_port, sriov_port_with_res_req),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor_with_group_policy)
        self.assertPortMatchesAllocation(
            sriov_port_with_res_req, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            sriov_port_with_res_req, self.compute1_rp_uuid)
        self._assert_port_binding_profile_allocation(
            sriov_port, self.compute1_rp_uuid)

        # We expect that the selected PCI device matches with the RP from
        # where the bandwidth is allocated from. The bandwidth is allocated
        # from 0000:02:00 (PF2) so the PCI device should be a VF of that PF
        sriov_with_req_binding = sriov_port_with_res_req['binding:profile']
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            sriov_with_req_binding['pci_slot'])
        # But also the port that has no resource request still gets a pci slot
        # allocated. The 0000:02:00 has no more VF available but 0000:03:00 has
        # one VF available and that PF is also on physnet2
        sriov_binding = sriov_port['binding:profile']
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF3_VF1,
            sriov_binding['pci_slot'])

    def test_one_sriov_port_no_vf_and_bandwidth_available_on_the_same_pf(self):
        """Verify that if there is no PF that both provides bandwidth and VFs
        then the boot will fail.
        """

        # boot a server with a single sriov port that has no resource request
        sriov_port = self.neutron.sriov_port
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': sriov_port['id']}])

        self._wait_for_state_change(server, 'ACTIVE')
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']
        sriov_binding = sriov_port['binding:profile']

        # We expect that this consume the last available VF from the PF2
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            sriov_binding['pci_slot'])

        # Now boot a second server with a port that has resource request
        # At this point PF2 has available bandwidth but no available VF
        # and PF3 has available VF but no available bandwidth so we expect
        # the boot to fail.

        sriov_port_with_res_req = self.neutron.port_with_sriov_resource_request
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': sriov_port_with_res_req['id']}])

        # NOTE(gibi): It should be NoValidHost in an ideal world but that would
        # require the scheduler to detect the situation instead of the pci
        # claim. However that is pretty hard as the scheduler does not know
        # anything about allocation candidates (e.g. that the only candidate
        # for the port in this case is PF2) it see the whole host as a
        # candidate and in our host there is available VF for the request even
        # if that is on the wrong PF.
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIn(
            'Exceeded maximum number of retries. Exhausted all hosts '
            'available for retrying build failures for instance',
            server['fault']['message'])

    def test_sriov_macvtap_port_with_resource_request(self):
        """Verify that vnic type macvtap is also supported"""

        port = self.neutron.port_macvtap_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        port = self.neutron.show_port(port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the port having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(port),
            len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            port, allocations, self.compute1_rp_uuid)

        self._assert_port_binding_profile_allocation(
            port, self.compute1_rp_uuid)

        # We expect that the selected PCI device matches with the RP from
        # where the bandwidth is allocated from. The bandwidth is allocated
        # from 0000:02:00 (PF2) so the PCI device should be a VF of that PF
        port_binding = port['binding:profile']
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            port_binding['pci_slot'])


class ExtendedPortResourceRequestBasedSchedulingTestBase(
        PortResourceRequestBasedSchedulingTestBase):
    """A base class for tests with neutron extended resource request."""

    # NOTE(gibi): we overwrite this from the base class to assert the new
    # format in the binding profile as the extended resource request extension
    # is enabled in the neutron fixture
    def _assert_port_binding_profile_allocation(self, port, compute_rp_uuid):
        groups = (port.get('resource_request') or {}).get('request_groups', [])
        if groups:
            if port['binding:vnic_type'] == "normal":
                expected_allocation = {}
                # Normal ports can have both bandwidth and packet rate requests
                for group in groups:
                    requested_rcs = group['resources'].keys()
                    if {
                        orc.NET_BW_IGR_KILOBIT_PER_SEC,
                        orc.NET_BW_EGR_KILOBIT_PER_SEC,
                    }.intersection(requested_rcs):
                        # Normal ports are expected to have bandwidth
                        # allocation on the OVS bridge RP
                        expected_allocation[group['id']] = (
                            self.ovs_bridge_rp_per_host[compute_rp_uuid])
                    else:  # assumed that this is the packet rate request
                        # the packet rate is expected to allocated from the
                        # OVS agent RP
                        expected_allocation[group['id']] = (
                            self.ovs_agent_rp_per_host[compute_rp_uuid])
            else:
                # SRIOV port can only have bandwidth requests no packet rate.
                group_id = groups[0]['id']
                # SRIOV ports are expected to have allocation on the PF2 RP
                # see _create_sriov_networking_rp_tree() for details.
                expected_allocation = {
                    group_id: self.sriov_dev_rp_per_host[
                        compute_rp_uuid][self.PF2]
                }

            self.assertEqual(
                expected_allocation,
                port['binding:profile']['allocation'])
        else:
            # if no resource request then we expect no allocation key in the
            # binding profile
            self.assertNotIn(
                'allocation', port['binding:profile'])

    # NOTE(gibi): we overwrite this from the base class as with the new neutron
    # extension enabled a port might have allocation from more than one RP
    def _get_number_of_expected_allocations_for_ports(self, *ports):
        # we expect one for each request group in each port's resource request
        return sum(
            len((port.get("resource_request") or {}).get("request_groups", []))
            for port in ports
        )

    def _assert_port_res_req_grp_matches_allocation(
        self, port_id, group, allocations
    ):
        for rc, amount in allocations.items():
            self.assertEqual(
                group[rc], amount,
                'port %s requested %d %s resources but got allocation %d' %
                (port_id, group[rc], rc, amount))

    # NOTE(gibi): we overwrite this from the base class as with the new neutron
    # extension enabled a port might requests both packet rate and bandwidth
    # resources and therefore has allocation from more than on RP.
    def assertPortMatchesAllocation(self, port, allocations, compute_rp_uuid):
        # The goal here is to grab the part of the allocation that is due to
        # the port having bandwidth request. We assume that all the normal
        # ports are handled by OVS while the rest is handled by SRIOV agent.
        # This is true in our func test setup, see the RP tree structure
        # created in _create_networking_rp_tree(), so it safe to assume here.
        # So we select the OVS / SRIOV part of the allocation based on the
        # vnic_type.
        if port['binding:vnic_type'] == 'normal':
            bw_allocations = allocations[
                self.ovs_bridge_rp_per_host[compute_rp_uuid]]['resources']
        else:
            bw_allocations = allocations[
                self.sriov_dev_rp_per_host[
                    compute_rp_uuid][self.PF2]]['resources']

        resource_request = port[constants.RESOURCE_REQUEST]
        # in the new format we have request groups in the resource request
        for group in resource_request["request_groups"]:
            group_req = group['resources']
            if (orc.NET_BW_IGR_KILOBIT_PER_SEC in group_req.keys() or
                    orc.NET_BW_IGR_KILOBIT_PER_SEC in group_req.keys()):
                # we match the bandwidth request group with the bandwidth
                # request we grabbed above
                self._assert_port_res_req_grp_matches_allocation(
                    port['id'], group_req, bw_allocations)
            else:
                # We assume that the other request group can only be about
                # packet rate. Also we know that the packet rate is allocated
                # always from the OVS agent RP.
                pps_allocations = allocations[
                    self.ovs_agent_rp_per_host[
                        compute_rp_uuid]]['resources']
                self._assert_port_res_req_grp_matches_allocation(
                    port['id'], group_req, pps_allocations)


class MultiGroupResourceRequestBasedSchedulingTest(
    ExtendedPortResourceRequestBasedSchedulingTestBase,
    PortResourceRequestBasedSchedulingTest,
):
    """The same tests as in PortResourceRequestBasedSchedulingTest but the
    the neutron.port_with_resource_request now changed to have both bandwidth
    and packet rate resource requests. This also means that the neutron fixture
    simulates the new resource_request format for all ports.
    """
    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(
            MultiGroupResourceRequestNeutronFixture(self))


class ServerMoveWithPortResourceRequestTest(
        PortResourceRequestBasedSchedulingTestBase):

    def setUp(self):
        # Use our custom weigher defined above to make sure that we have
        # a predictable host order in the alternate list returned by the
        # scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(ServerMoveWithPortResourceRequestTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # create a bigger flavor to use in resize test
        self.flavor_with_group_policy_bigger = self.admin_api.post_flavor(
            {'flavor': {
                'ram': self.flavor_with_group_policy['ram'],
                'vcpus': self.flavor_with_group_policy['vcpus'],
                'name': self.flavor_with_group_policy['name'] + '+',
                'disk': self.flavor_with_group_policy['disk'] + 1,
            }})
        self.admin_api.post_extra_spec(
            self.flavor_with_group_policy_bigger['id'],
            {'extra_specs': {'group_policy': 'isolate'}})

    def _test_resize_or_migrate_server_with_qos_ports(self, new_flavor=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        if new_flavor:
            self.api_fixture.api.post_server_action(
                server['id'], {'resize': {"flavorRef": new_flavor['id']}})
        else:
            self.api.post_server_action(server['id'], {'migrate': None})

        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the new host properly
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy,
            migration_uuid, source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._confirm_resize(server)

        # check that allocation is still OK
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy,
            new_flavor=new_flavor)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_migrate_server_with_qos_ports(self):
        self._test_resize_or_migrate_server_with_qos_ports()

    def test_resize_server_with_qos_ports(self):
        self._test_resize_or_migrate_server_with_qos_ports(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_revert_with_qos_ports(self, new_flavor=None):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        if new_flavor:
            self.api_fixture.api.post_server_action(
                server['id'], {'resize': {"flavorRef": new_flavor['id']}})
        else:
            self.api.post_server_action(server['id'], {'migrate': None})

        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the new host properly
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy, migration_uuid,
            source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self.api.post_server_action(server['id'], {'revertResize': None})
        self._wait_for_state_change(server, 'ACTIVE')

        # check that allocation is moved back to the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

        # check that the target host allocation is cleaned up.
        self.assertRequestMatchesUsage(
            {'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0,
             'NET_BW_IGR_KILOBIT_PER_SEC': 0, 'NET_BW_EGR_KILOBIT_PER_SEC': 0},
            self.compute2_rp_uuid)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_port, qos_sriov_port)

    def test_migrate_revert_with_qos_ports(self):
        self._test_resize_or_migrate_revert_with_qos_ports()

    def test_resize_revert_with_qos_ports(self):
        self._test_resize_or_migrate_revert_with_qos_ports(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_server_with_qos_port_reschedule_success(
            self, new_flavor=None):
        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # Yes this isn't great in a functional test, but it's simple.
        original_prep_resize = compute_manager.ComputeManager._prep_resize

        prep_resize_calls = []

        def fake_prep_resize(_self, *args, **kwargs):
            # Make the first prep_resize fail and the rest passing through
            # the original _prep_resize call
            if not prep_resize_calls:
                prep_resize_calls.append(_self.host)
                raise test.TestingException('Simulated prep_resize failure.')
            prep_resize_calls.append(_self.host)
            original_prep_resize(_self, *args, **kwargs)

        # The patched compute manager will raise from _prep_resize on the
        # first host of the migration. Then the migration
        # is reschedule on the other host where it will succeed
        with mock.patch.object(
                compute_manager.ComputeManager, '_prep_resize',
                new=fake_prep_resize):
            if new_flavor:
                self.api_fixture.api.post_server_action(
                    server['id'], {'resize': {"flavorRef": new_flavor['id']}})
            else:
                self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # ensure that resize is tried on two hosts, so we had a re-schedule
        self.assertEqual(['host2', 'host3'], prep_resize_calls)

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the final host properly while
        # the migration holds the allocation on the source host
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_port, qos_port, qos_sriov_port,
            self.flavor_with_group_policy, migration_uuid,
            source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self._assert_pci_request_pf_device_name(server, 'host3-ens2')

        self._confirm_resize(server)

        # check that allocation is still OK
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_port, qos_port, qos_sriov_port,
            self.flavor_with_group_policy, new_flavor=new_flavor)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_port, qos_sriov_port)

    def test_migrate_server_with_qos_port_reschedule_success(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_success()

    def test_resize_server_with_qos_port_reschedule_success(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_success(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_server_with_qos_port_reschedule_failure(
            self, new_flavor=None):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # The patched compute manager on host2 will raise from _prep_resize.
        # Then the migration is reschedule but there is no other host to
        # choose from.
        with mock.patch.object(
                compute_manager.ComputeManager, '_prep_resize',
                side_effect=test.TestingException(
                    'Simulated prep_resize failure.')):
            if new_flavor:
                self.api_fixture.api.post_server_action(
                    server['id'], {'resize': {"flavorRef": new_flavor['id']}})
            else:
                self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_server_parameter(server,
                {'OS-EXT-SRV-ATTR:host': 'host1',
                 'status': 'ERROR'})
            self._wait_for_migration_status(server, ['error'])

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # as the migration is failed we expect that the migration allocation
        # is deleted
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def test_migrate_server_with_qos_port_reschedule_failure(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_failure()

    def test_resize_server_with_qos_port_reschedule_failure(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_failure(
            new_flavor=self.flavor_with_group_policy_bigger)

    def test_migrate_server_with_qos_port_pci_update_fail_not_reschedule(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is migrated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # The compute manager on host2 will raise from
        # update_pci_request_spec_with_allocated_interface_name which will
        # intentionally not trigger a re-schedule even if there is host3 as an
        # alternate.
        self.api.post_server_action(server['id'], {'migrate': None})
        server = self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             # Note that we have to wait for the task_state to be reverted
             # to None since that happens after the fault is recorded.
             'OS-EXT-STS:task_state': None,
             'status': 'ERROR'})
        self._wait_for_migration_status(server, ['error'])

        self.assertIn(
            'Build of instance %s aborted' % server['id'],
            server['fault']['message'])

        self._wait_for_action_fail_completion(
            server, instance_actions.MIGRATE, 'compute_prep_resize')

        self.notifier.wait_for_versioned_notifications(
            'instance.resize_prep.end')
        self.notifier.wait_for_versioned_notifications(
            'compute.exception')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # as the migration is failed we expect that the migration allocation
        # is deleted
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def _check_allocation_during_evacuate(
            self, server, flavor, source_compute_rp_uuid, dest_compute_rp_uuid,
            non_qos_port, qos_port, qos_sriov_port):
        # evacuate is the only case when the same consumer has allocation from
        # two different RP trees so we need special checks

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # Evacuation duplicate the resource allocation. So we expect two sets
        # of allocations. One set for the source compute and one set for the
        # dest compute. Each set we expect one allocation for the compute
        # resource according to the flavor and allocations due to the ports
        # having resource requests
        self.assertEqual(
            2 * (
                1 + self._get_number_of_expected_allocations_for_ports(
                    updated_non_qos_port,
                    updated_qos_port,
                    updated_qos_sriov_port
                )
            ),
            len(allocations))

        # 1. source compute allocation
        compute_allocations = allocations[source_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 2. source ovs allocation
        self.assertPortMatchesAllocation(
            updated_qos_port, allocations, source_compute_rp_uuid)

        # 3. source sriov allocation
        self.assertPortMatchesAllocation(
            updated_qos_sriov_port, allocations, source_compute_rp_uuid)

        # 4. dest compute allocation
        compute_allocations = allocations[dest_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 5. dest ovs allocation
        self.assertPortMatchesAllocation(
            updated_qos_port, allocations, dest_compute_rp_uuid)

        # 6. dest SRIOV allocation
        self.assertPortMatchesAllocation(
            updated_qos_sriov_port, allocations, dest_compute_rp_uuid)

        # the qos ports should have their binding pointing to the RPs in the
        # dest compute RP tree
        self._assert_port_binding_profile_allocation(
            updated_qos_port, dest_compute_rp_uuid)
        self._assert_port_binding_profile_allocation(
            updated_qos_sriov_port, dest_compute_rp_uuid)

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

    def _check_allocation_after_evacuation_source_recovered(
            self, server, flavor, dest_compute_rp_uuid, non_qos_port,
            qos_port, qos_sriov_port):
        # check that source allocation is cleaned up and the dest allocation
        # and the port bindings are not touched.

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp plus the allocations due to the ports having resource
        # requests
        self.assertEqual(
            1 + self._get_number_of_expected_allocations_for_ports(
                updated_non_qos_port,
                updated_qos_port,
                updated_qos_sriov_port
            ),
            len(allocations))

        # 1. dest compute allocation
        compute_allocations = allocations[dest_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 2. dest ovs allocation
        self.assertPortMatchesAllocation(
            updated_qos_port, allocations, dest_compute_rp_uuid)

        # 3. dest SRIOV allocation
        self.assertPortMatchesAllocation(
            updated_qos_sriov_port, allocations, dest_compute_rp_uuid)

        # the qos ports should have their binding pointing to the RPs in the
        # dest compute RP tree
        self._assert_port_binding_profile_allocation(
            updated_qos_port, dest_compute_rp_uuid)

        self._assert_port_binding_profile_allocation(
            updated_qos_sriov_port, dest_compute_rp_uuid)

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

    def test_evacuate_with_qos_port(self, host=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        self._evacuate_server(
            server, {'host': host} if host else {}, expected_host='host2')

        self._check_allocation_during_evacuate(
            server, self.flavor_with_group_policy, self.compute1_rp_uuid,
            self.compute2_rp_uuid, non_qos_normal_port, qos_normal_port,
            qos_sriov_port)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        # recover source compute
        self.compute1 = self.restart_compute_service(self.compute1)
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'false'})

        # check that source allocation is cleaned up and the dest allocation
        # and the port bindings are not touched.
        self._check_allocation_after_evacuation_source_recovered(
            server, self.flavor_with_group_policy, self.compute2_rp_uuid,
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_evacuate_with_target_host_with_qos_port(self):
        self.test_evacuate_with_qos_port(host='host2')

    def test_evacuate_with_qos_port_fails_recover_source_compute(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        with mock.patch(
                'nova.compute.resource_tracker.ResourceTracker.rebuild_claim',
                side_effect=exception.ComputeResourcesUnavailable(
                    reason='test evacuate failure')):
            # Evacuate does not have reschedule loop so evacuate expected to
            # simply fail and the server remains on the source host
            server = self._evacuate_server(
                server, expected_host='host1', expected_task_state=None,
                expected_migration_status='failed')

        # As evacuation failed the resource allocation should be untouched
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # recover source compute
        self.compute1 = self.restart_compute_service(self.compute1)
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'false'})

        # check again that even after source host recovery the source
        # allocation is intact
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_evacuate_with_qos_port_pci_update_fail(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is evacuated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        # The compute manager on host2 will raise from
        # update_pci_request_spec_with_allocated_interface_name
        server = self._evacuate_server(
            server, expected_host='host1', expected_state='ERROR',
            expected_task_state=None, expected_migration_status='failed')

        self.assertIn(
            'does not have a properly formatted name',
            server['fault']['message'])

        self._wait_for_action_fail_completion(
            server, instance_actions.EVACUATE, 'compute_rebuild_instance')

        self.notifier.wait_for_versioned_notifications(
            'instance.rebuild.error')
        self.notifier.wait_for_versioned_notifications(
            'compute.exception')

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def test_live_migrate_with_qos_port(self, host=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': host,
                    'block_migration': 'auto'
                }
            }
        )

        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host2',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_with_target_host(self):
        self.test_live_migrate_with_qos_port(host='host2')

    def test_live_migrate_with_qos_port_reschedule_success(self):
        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_check = fake.FakeDriver.check_can_live_migrate_destination

        def fake_check_can_live_migrate_destination(
                context, instance, src_compute_info, dst_compute_info,
                block_migration=False, disk_over_commit=False):
            if dst_compute_info['host'] == 'host2':
                raise exception.MigrationPreCheckError(
                    reason='test_live_migrate_pre_check_fails')
            else:
                return orig_check(
                    context, instance, src_compute_info, dst_compute_info,
                    block_migration, disk_over_commit)

        with mock.patch('nova.virt.fake.FakeDriver.'
                        'check_can_live_migrate_destination',
                        side_effect=fake_check_can_live_migrate_destination):
            self.api.post_server_action(
                server['id'],
                {
                    'os-migrateLive': {
                        'host': None,
                        'block_migration': 'auto'
                    }
                }
            )
            # The first migration attempt was to host2. So we expect that the
            # instance lands on host3.
            self._wait_for_server_parameter(
                server,
                {'OS-EXT-SRV-ATTR:host': 'host3',
                 'status': 'ACTIVE'})

        self._check_allocation(
            server, compute3_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host3-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_reschedule_fails(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        with mock.patch(
                'nova.virt.fake.FakeDriver.check_can_live_migrate_destination',
                side_effect=exception.MigrationPreCheckError(
                    reason='test_live_migrate_pre_check_fails')):
            self.api.post_server_action(
                server['id'],
                {
                    'os-migrateLive': {
                        'host': None,
                        'block_migration': 'auto'
                    }
                }
            )
            # The every migration target host will fail the pre check so
            # the conductor will run out of target host and the migration will
            # fail
            self._wait_for_migration_status(server, ['error'])

        # the server will remain on host1
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests also rolled back to point to
        # host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_pci_update_fails(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is live migrated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': None,
                    'block_migration': 'auto'
                }
            }
        )

        # pci update will fail after scheduling to host2
        self._wait_for_migration_status(server, ['error'])
        server = self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ERROR'})
        self.assertIn(
            'does not have a properly formatted name',
            server['fault']['message'])

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests still point to host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_not_offloaded_server_with_port_resource_request(
            self):
        """If the server is not offloaded then unshelving does not cause a new
        resource allocation therefore having port resource request is
        irrelevant. Still this test asserts that such unshelve request works.
        """
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # avoid automatic shelve offloading
        self.flags(shelved_offload_time=-1)
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(server, {'status': 'SHELVED'})
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(server, 'ACTIVE')
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        # shelve offload again and then make host1 unusable so the subsequent
        # unshelve needs to select host2
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self.admin_api.put_service(
            self.compute1_service_id, {"status": "disabled"})

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host2',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port_pci_update_fails(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is unshelved to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        # make host1 unusable so the subsequent unshelve needs to select host2
        self.admin_api.put_service(
            self.compute1_service_id, {"status": "disabled"})

        self.api.post_server_action(server['id'], {'unshelve': None})

        # Unshelve fails on host2 due to
        # update_pci_request_spec_with_allocated_interface_name fails so the
        # instance goes back to shelve offloaded state
        self.notifier.wait_for_versioned_notifications(
            'instance.unshelve.start')
        error_notification = self.notifier.wait_for_versioned_notifications(
            'compute.exception')[0]
        self.assertEqual(
            'UnexpectedResourceProviderNameForPCIRequest',
            error_notification['payload']['nova_object.data']['exception'])
        server = self._wait_for_server_parameter(
            server,
            {'OS-EXT-STS:task_state': None,
             'status': 'SHELVED_OFFLOADED'})

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port_fails_due_to_neutron(
            self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        # Simulate that port update fails during unshelve due to neutron is
        # unavailable
        with mock.patch(
                'nova.tests.fixtures.NeutronFixture.'
                'update_port') as mock_update_port:
            mock_update_port.side_effect = neutron_exception.ConnectionFailed(
                reason='test')
            req = {'unshelve': None}
            self.api.post_server_action(server['id'], req)
            self.notifier.wait_for_versioned_notifications(
                'instance.unshelve.start')
            self._wait_for_server_parameter(
                server,
                {'status': 'SHELVED_OFFLOADED',
                 'OS-EXT-STS:task_state': None})

        # As the instance went back to offloaded state we expect no allocation
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)


class ServerMoveWithMultiGroupResourceRequestBasedSchedulingTest(
    ExtendedPortResourceRequestBasedSchedulingTestBase,
    ServerMoveWithPortResourceRequestTest,
):
    """The same tests as in ServerMoveWithPortResourceRequestTest but the
    the neutron.port_with_resource_request now changed to have both bandwidth
    and packet rate resource requests. This also means that the neutron
    fixture simulates the new resource_request format for all ports.
    """

    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(
            MultiGroupResourceRequestNeutronFixture(self))


class LiveMigrateAbortWithPortResourceRequestTest(
        PortResourceRequestBasedSchedulingTestBase):

    compute_driver = "fake.FakeLiveMigrateDriverWithPciResources"

    def setUp(self):
        # Use a custom weigher to make sure that we have a predictable host
        # order in the alternate list returned by the scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(LiveMigrateAbortWithPortResourceRequestTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

    def test_live_migrate_with_qos_port_abort_migration(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # The special virt driver will keep the live migration running until it
        # is aborted.
        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': None,
                    'block_migration': 'auto'
                }
            }
        )

        # wait for the migration to start
        migration = self._wait_for_migration_status(server, ['running'])

        # delete the migration to abort it
        self.api.delete_migration(server['id'], migration['id'])

        self._wait_for_migration_status(server, ['cancelled'])
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests rolled back to point to host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)


class PortResourceRequestReSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Similar to PortResourceRequestBasedSchedulingTest
    except this test uses FakeRescheduleDriver which will test reschedules
    during server create work as expected, i.e. that the resource request
    allocations are moved from the initially selected compute to the
    alternative compute.
    """

    compute_driver = 'fake.FakeRescheduleDriver'

    def setUp(self):
        super(PortResourceRequestReSchedulingTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)

    def _create_networking_rp_tree(self, hostname, compute_rp_uuid):
        # let's simulate what the neutron would do
        self._create_ovs_networking_rp_tree(compute_rp_uuid)

    def test_boot_reschedule_success(self):
        port = self.neutron.port_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')
        updated_port = self.neutron.show_port(port['id'])['port']

        dest_hostname = server['OS-EXT-SRV-ATTR:host']
        dest_compute_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        failed_compute_rp = (self.compute1_rp_uuid
                             if dest_compute_rp_uuid == self.compute2_rp_uuid
                             else self.compute2_rp_uuid)

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, dest_compute_rp_uuid, self.flavor)
        self.assertPortMatchesAllocation(
            port, allocations, dest_compute_rp_uuid)

        # assert that the allocations against the host where the spawn
        # failed are cleaned up properly
        self.assertEqual(
            {'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0},
            self._get_provider_usages(failed_compute_rp))
        self.assertEqual(
            {'NET_BW_EGR_KILOBIT_PER_SEC': 0, 'NET_BW_IGR_KILOBIT_PER_SEC': 0},
            self._get_provider_usages(
                self.ovs_bridge_rp_per_host[failed_compute_rp]))

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding
        binding_profile = updated_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[dest_compute_rp_uuid],
                         binding_profile['allocation'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = updated_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_boot_reschedule_fill_provider_mapping_raises(self):
        """Verify that if the  _fill_provider_mapping raises during re-schedule
        then the instance is properly put into ERROR state.
        """

        port = self.neutron.port_with_resource_request

        # First call is during boot, we want that to succeed normally. Then the
        # fake virt driver triggers a re-schedule. During that re-schedule the
        # fill is called again, and we simulate that call raises.
        original_fill = utils.fill_provider_mapping

        def stub_fill_provider_mapping(*args, **kwargs):
            if not mock_fill.called:
                return original_fill(*args, **kwargs)
            raise exception.ResourceProviderTraitRetrievalFailed(
                uuid=uuids.rp1)

        with mock.patch(
                'nova.scheduler.utils.fill_provider_mapping',
                side_effect=stub_fill_provider_mapping) as mock_fill:
            server = self._create_server(
                flavor=self.flavor,
                networks=[{'port': port['id']}])
            server = self._wait_for_state_change(server, 'ERROR')

        self.assertIn(
            'Failed to get traits for resource provider',
            server['fault']['message'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = neutronapi.get_binding_profile(updated_port)
        self.assertNotIn('allocation', binding_profile)


class CrossCellResizeWithQoSPort(PortResourceRequestBasedSchedulingTestBase):
    NUMBER_OF_CELLS = 2

    def setUp(self):
        # Use our custom weigher defined above to make sure that we have
        # a predictable host order in the alternate list returned by the
        # scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(CrossCellResizeWithQoSPort, self).setUp()
        # start compute2 in cell2, compute1 is started in cell1 by default
        self.compute2 = self._start_compute('host2', cell_name='cell2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # Enable cross-cell resize policy since it defaults to not allow
        # anyone to perform that type of operation. For these tests we'll
        # just allow admins to perform cross-cell resize.
        self.policy.set_rules({
            servers_policies.CROSS_CELL_RESIZE:
                base_policies.RULE_ADMIN_API},
            overwrite=False)

    def test_cross_cell_migrate_server_with_qos_ports(self):
        """Test that cross cell migration is not supported with qos ports and
        nova therefore falls back to do a same cell migration instead.
        To test this properly we first make sure that there is no valid host
        in the same cell but there is valid host in another cell and observe
        that the migration fails with NoValidHost. Then we start a new compute
        in the same cell the instance is in and retry the migration that is now
        expected to pass.
        """

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_create_binding = self.neutron.create_port_binding

        hosts = {
            'host1': self.compute1_rp_uuid, 'host2': self.compute2_rp_uuid,
        }

        # Add an extra check to our neutron fixture. This check makes sure that
        # the RP sent in the binding corresponds to host of the binding. In a
        # real deployment this is checked by the Neutron server. As bug
        # 1907522 showed we fail this check for cross cell migration with qos
        # ports in a real deployment. So to reproduce that bug we need to have
        # the same check in our test env too.
        def spy_on_create_binding(port_id, data):
            host_rp_uuid = hosts[data['binding']['host']]
            device_rp_uuid = data['binding']['profile'].get('allocation')
            if port_id == qos_normal_port['id']:
                if device_rp_uuid != self.ovs_bridge_rp_per_host[host_rp_uuid]:
                    raise exception.PortBindingFailed(port_id=port_id)
            elif port_id == qos_sriov_port['id']:
                if (
                    device_rp_uuid not in
                    self.sriov_dev_rp_per_host[host_rp_uuid].values()
                ):
                    raise exception.PortBindingFailed(port_id=port_id)

            return orig_create_binding(port_id, data)

        with mock.patch(
            'nova.tests.fixtures.NeutronFixture.create_port_binding',
            side_effect=spy_on_create_binding, autospec=True
        ):
            # We expect the migration to fail as the only available target
            # host is in a different cell and while cross cell migration is
            # enabled it is not supported for neutron ports with resource
            # request.
            self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_server_parameter(
                server,
                {'status': 'ACTIVE', 'OS-EXT-SRV-ATTR:host': 'host1'})
            event = self._wait_for_action_fail_completion(
                server, 'migrate', 'conductor_migrate_server')
            self.assertIn(
                'exception.NoValidHost', event['traceback'])
            self.assertIn(
                'Request is allowed by policy to perform cross-cell resize '
                'but the instance has ports with resource request and '
                'cross-cell resize is not supported with such ports.',
                self.stdlog.logger.output)
            self.assertNotIn(
                'nova.exception.PortBindingFailed: Binding failed for port',
                self.stdlog.logger.output)

        # Now start a new compute in the same cell as the instance and retry
        # the migration.
        self._start_compute('host3', cell_name='cell1')
        self.compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', self.compute3_rp_uuid)

        with mock.patch(
            'nova.tests.fixtures.NeutronFixture.create_port_binding',
            side_effect=spy_on_create_binding, autospec=True
        ):
            server = self._migrate_server(server)
            self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)


class ExtendedResourceRequestOldCompute(
        PortResourceRequestBasedSchedulingTestBase):
    """Tests that simulate that there are compute services in the system that
    hasn't been upgraded to a version that support extended resource request.
    So nova rejects the operations due to the old compute.
    """
    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(
            ExtendedResourceRequestNeutronFixture(self))

    @mock.patch.object(
        objects.service, 'get_minimum_version_all_cells',
        new=mock.Mock(return_value=57)
    )
    def test_boot(self):
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._create_server,
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_with_resource_request['id']}],
        )
        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            'The port-resource-request-groups neutron API extension is not '
            'supported by old nova compute service. Upgrade your compute '
            'services to Xena (24.0.0) or later.',
            str(ex)
        )

    @mock.patch.object(
        objects.service, 'get_minimum_version_all_cells',
        new=mock.Mock(return_value=58)
    )
    def _test_operation(self, op_callable):
        # boot a server, service version 58 already supports that
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_with_resource_request['id']}],
        )
        self._wait_for_state_change(server, 'ACTIVE')

        # still the move operations require service version 58 so they will
        # fail
        ex = self.assertRaises(
            client.OpenStackApiException,
            op_callable,
            server,
        )
        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            'The port-resource-request-groups neutron API extension is not '
            'supported by old nova compute service. Upgrade your compute '
            'services to Xena (24.0.0) or later.',
            str(ex)
        )

    def test_resize(self):
        self._test_operation(
            lambda server: self._resize_server(
                server, self.flavor_with_group_policy['id']
            )
        )

    def test_migrate(self):
        self._test_operation(
            lambda server: self._migrate_server(server),
        )

    def test_live_migrate(self):
        self._test_operation(
            lambda server: self._live_migrate(server),
        )

    def test_evacuate(self):
        self._test_operation(
            lambda server: self._evacuate_server(server),
        )

    def test_unshelve_after_shelve_offload(self):
        def shelve_offload_then_unshelve(server):
            self._shelve_server(server, expected_state='SHELVED_OFFLOADED')
            self._unshelve_server(server)
        self._test_operation(
            lambda server: shelve_offload_then_unshelve(server),
        )

    @mock.patch('nova.objects.service.Service.get_by_host_and_binary')
    def test_interface_attach(self, mock_get_service):
        # service version 59 allows booting
        mock_get_service.return_value.version = 59
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}],
        )
        self._wait_for_state_change(server, "ACTIVE")
        # for interface attach service version 60 would be needed
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._attach_interface,
            server,
            self.neutron.port_with_sriov_resource_request['id'],
        )
        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            'The port-resource-request-groups neutron API extension is not '
            'supported by old nova compute service. Upgrade your compute '
            'services to Xena (24.0.0) or later.',
            str(ex)
        )
