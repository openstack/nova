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
import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova.network import constants
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class NeutronRoutedNetworksFixture(nova_fixtures.NeutronFixture):
    tenant_id = nova_fixtures.NeutronFixture.tenant_id

    network_multisegment = {
        'id': uuids.network_multisegment,
        'name': 'net-multisegment',
        'description': '',
        'status': 'ACTIVE',
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
        'segments': [
            {
                "provider:network_type": "flat",
                "provider:physical_network": "default",
                "provider:segmentation_id": 0
            },
            {
                "provider:network_type": "vlan",
                "provider:physical_network": "public",
                "provider:segmentation_id": 2
            },
        ],
    }

    segment_id_0 = {
            "name": "",
            "network_id": network_multisegment['id'],
            "segmentation_id": 0,
            "network_type": "flat",
            "physical_network": "default",
            "revision_number": 1,
            "id": uuids.segment_id_0,
            "created_at": "2018-03-19T19:16:56Z",
            "updated_at": "2018-03-19T19:16:56Z",
            "description": "",
    }
    segment_id_2 = {
            "name": "",
            "network_id": network_multisegment['id'],
            "segmentation_id": 2,
            "network_type": "vlan",
            "physical_network": "public",
            "revision_number": 3,
            "id": uuids.segment_id_2,
            "created_at": "2018-03-19T19:16:56Z",
            "updated_at": "2018-03-19T19:16:56Z",
            "description": "",
    }
    segments = [segment_id_0, segment_id_2]

    subnet_for_segment_id_0 = {
        'id': uuids.subnet_for_segment_id_0,
        'name': 'public-subnet',
        'description': '',
        'ip_version': 4,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': True,
        'network_id': network_multisegment['id'],
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
        'segment_id': segment_id_0['id'],
    }

    subnet_for_segment_id_2 = {
        'id': uuids.subnet_for_segment_id_2,
        'name': 'vlan-subnet',
        'description': '',
        'ip_version': 4,
        'ipv6_address_mode': None,
        'ipv6_ra_mode': None,
        'enable_dhcp': True,
        'network_id': network_multisegment['id'],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'dns_nameservers': [],
        'gateway_ip': '192.168.2.1',
        'allocation_pools': [
            {
                'start': '192.168.2.1',
                'end': '192.168.2.254'
            }
        ],
        'host_routes': [],
        'cidr': '192.168.2.1/24',
        'segment_id': segment_id_2['id'],
    }

    network_multisegment['subnets'] = [subnet_for_segment_id_0['id'],
                                       subnet_for_segment_id_2['id']]

    # Use this port only if you want a unbound port.
    port_with_deferred_ip_allocation = {
        'id': uuids.port_with_deferred_ip_allocation,
        'name': '',
        'description': '',
        'network_id': network_multisegment['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:12',
        # The allocation is deferred, so fixed_ips should be null *before*
        # the port is binding.
        # NOTE(sbauza): Make sure you modify the value if you look at the port
        # after it's bound.
        'fixed_ips': [],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vnic_type': 'normal',
        'binding:vif_type': 'ovs',
        'ip_allocation': "deferred",
    }

    # Use this port if you want to fake the port being already bound
    port_with_deferred_ip_allocation_bound_to_segment_0 = \
        copy.deepcopy(port_with_deferred_ip_allocation)
    port_with_deferred_ip_allocation_bound_to_segment_0.update({
            'fixed_ips': [{
                'ip_address': '192.168.1.4',
                'subnet_id': subnet_for_segment_id_0['id']
            }],
        })

    port_on_segment_id_0 = {
        'id': uuids.port_on_segment_id_0,
        'name': '',
        'description': '',
        'network_id': network_multisegment['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:13',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.3',
                'subnet_id': subnet_for_segment_id_0['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vnic_type': 'normal',
        'binding:vif_type': 'ovs',
        'ip_allocation': "immediate",
    }

    port_on_segment_id_2 = {
        'id': uuids.port_on_segment_id_2,
        'name': '',
        'description': '',
        'network_id': network_multisegment['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:13',
        'fixed_ips': [
            {
                'ip_address': '192.168.2.4',
                'subnet_id': subnet_for_segment_id_2['id']
            }
        ],
        'tenant_id': tenant_id,
        'project_id': tenant_id,
        'device_id': '',
        'binding:profile': {},
        'binding:vnic_type': 'normal',
        'binding:vif_type': 'ovs',
        'ip_allocation': "immediate",
    }

    def __init__(self, test):
        super().__init__(test)
        # add extra ports and the related network to the neutron fixture
        # specifically for these tests.
        self._networks[
            self.network_multisegment['id']
        ] = self.network_multisegment
        self._ports[
            self.port_with_deferred_ip_allocation['id']
        ] = copy.deepcopy(self.port_with_deferred_ip_allocation)
        self._ports[
            self.port_on_segment_id_0['id']
        ] = copy.deepcopy(self.port_on_segment_id_0)
        self._ports[
            self.port_on_segment_id_2['id']
        ] = copy.deepcopy(self.port_on_segment_id_2)
        self._subnets[
            self.subnet_for_segment_id_0['id']
        ] = copy.deepcopy(self.subnet_for_segment_id_0)
        self._subnets[
            self.subnet_for_segment_id_2['id']
        ] = copy.deepcopy(self.subnet_for_segment_id_2)

    def list_extensions(self, *args, **kwargs):
        return {
            'extensions': [
                {
                    # Copied from neutron-lib segment.py
                    "updated": "2016-02-24T17:00:00-00:00",
                    "name": constants.SEGMENT,
                    "links": [],
                    "alias": "segment",
                    "description": "Segments extension."
                }
            ]
        }

    def list_subnets(self, retrieve_all=True, **_params):
        if 'network_id' in _params:
            network_id = _params['network_id']
            assert network_id in self._networks, ('Network %s not in fixture' %
                                                  network_id)
            filtered_subnets = []
            for subnet in list(self._subnets.values()):
                if subnet['network_id'] == network_id:
                    filtered_subnets.append(copy.deepcopy(subnet))
            return {'subnets': filtered_subnets}
        else:
            return super().list_subnets(retrieve_all, **_params)

    def create_port(self, body=None):
        body = body or {'port': {}}
        network_id = body['port'].get('network_id')
        assert network_id in self._networks, ('Network %s not in fixture' %
                                              network_id)

        # Redefine the default port template to use for creating a new one to
        # be the port already allocated on segment #0.
        # NOTE(sbauza): Segment #0 is always used when booting an instance
        # without a provided port as the first supported host is related to it.
        # FIXME(sbauza): Do something here to not blindly set the segment
        # without verifying which compute service is used by the instance.
        self.default_port = (
            self.port_with_deferred_ip_allocation_bound_to_segment_0
        )
        return super().create_port(body)


class RoutedNetworkTests(integrated_helpers._IntegratedTestBase):
    compute_driver = 'fake.MediumFakeDriver'
    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        self.flags(
            query_placement_for_routed_network_aggregates=True,
            group='scheduler')

        # We will create 5 hosts, let's make sure we order them by their index.
        weights = {'host1': 500, 'host2': 400, 'host3': 300, 'host4': 200,
                   'host5': 100}
        self.useFixture(nova_fixtures.HostNameWeigherFixture(weights=weights))
        super().setUp()

        # Amend the usual neutron fixture with specific routed networks
        self.neutron = self.useFixture(NeutronRoutedNetworksFixture(self))

        # let's create 5 computes with their respective records
        for i in range(1, 6):
            setattr(self, 'compute%s' % i, self._start_compute('host%s' % i))
            setattr(self, 'compute%s_rp_uuid' % i,
                    self._get_provider_uuid_by_host('host%s' % i))
            setattr(self, 'compute%s_service_id' % i,
                    self.admin_api.get_services(host='host%s' % i,
                                                binary='nova-compute')[0]['id']
                    )

        # Simulate the placement setup neutron does for multi segment networks
        segment_ids = [segment["id"] for segment in self.neutron.segments]
        self.assertEqual(2, len(segment_ids))

        # We have 5 computes and the network has two segments. Let's create a
        # setup where the network has segments on host2 to host5 but not on
        # host1. The HostNameWeigherFixture prefers host1 over host2 over host3
        # over host4 over host5. So this way we can check if the scheduler
        # selects host with available network segment.
        # The segments are for this net :
        #  * segment 0 is for host2, host4 and host5
        #  * segment 2 is for host3 and host5
        self.segment_id_to_compute_rp_uuid = {
            segment_ids[0]: [self.compute2_rp_uuid, self.compute4_rp_uuid,
                             self.compute5_rp_uuid],
            segment_ids[1]: [self.compute3_rp_uuid, self.compute5_rp_uuid],
        }

        self._create_multisegment_placement_setup(
            self.segment_id_to_compute_rp_uuid)

    def _create_multisegment_placement_setup(self, segment_to_compute_rp):
        self.segment_id_to_aggregate_id = {}
        # map each segment to one compute
        for segment_id, compute_rp_uuids in segment_to_compute_rp.items():
            # create segment RP
            segment_rp_req = {
                "name": segment_id,
                "uuid": segment_id,
                "parent_provider_uuid": None,
            }
            self.placement.post(
                "/resource_providers", body=segment_rp_req, version="1.20"
            )

            # create aggregate around the segment RP and the compute RP
            aggregate_uuid = getattr(uuids, segment_id)
            self.segment_id_to_aggregate_id[segment_id] = aggregate_uuid

            # as we created the segment RP above we assume that it does not
            # have any aggregate and its generation is 0
            self.assertEqual(
                200,
                self.placement.put(
                    "/resource_providers/%s/aggregates" % segment_id,
                    body={
                        "aggregates": [aggregate_uuid],
                        "resource_provider_generation": 0,
                    },
                    version="1.20",
                ).status,
            )

            # get compute RPs and append the new aggregate to it
            for compute_rp_uuid in compute_rp_uuids:
                resp = self.placement.get(
                    "/resource_providers/%s/aggregates" % compute_rp_uuid,
                    version="1.20",
                ).body
                resp["aggregates"].append(aggregate_uuid)
                self.assertEqual(
                    200,
                    self.placement.put(
                        "/resource_providers/%s/aggregates" % compute_rp_uuid,
                        body=resp,
                        version="1.20",
                    ).status,
                )

    def test_boot_with_deferred_port(self):
        # Neutron only assigns the deferred port to a segment when the port is
        # bound to a host. So the scheduler can select any host that has
        # a segment for the network.
        port = self.neutron.port_with_deferred_ip_allocation
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'port': port['id']}])

        # HostNameWeigherFixture prefers host1 but the port is in a network
        # that has only segments on host2 to host5.
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

    def test_boot_with_immediate_port(self):
        # Immediate port should be assigned to a network segment by neutron
        # during port create. So the scheduler should only select a host that
        # is connected to that network segment
        port = self.neutron.port_on_segment_id_2
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'port': port['id']}])

        # Since the port is on the segment ID 2, only host3 and host5 are
        # accepted, so host3 always wins because of the weigher.
        self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])

    def test_boot_with_network(self):
        # Port is created _after_ scheduling to a host so the scheduler can
        # select either host2 to host5 initially based on the segment
        # availability of the network. But then nova needs to create
        # the port in deferred mode so that the already selected host could
        # not conflict with the neutron segment assignment at port create.
        net = self.neutron.network_multisegment
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'uuid': net['id']}])

        # host2 always wins over host3 to host5 because of the weigher.
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        # Verify that we used a port with a deferred ip allocation
        ip_addr = server['addresses'][net['name']][0][
            'addr']
        self.assertEqual(
            self.neutron.port_with_deferred_ip_allocation_bound_to_segment_0[
                'fixed_ips'][0]['ip_address'],
            ip_addr)

    def test_boot_with_two_nics(self):
        # Test a scenario with a user trying to have two different NICs within
        # two different segments not intertwined.
        port0 = self.neutron.port_on_segment_id_0
        port1 = self.neutron.port_on_segment_id_2
        # Here we ask for a server with one NIC on each segment.
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'port': port0['id']}, {'port': port1['id']}])

        # host2 should win with the weigher but as we asked for both segments,
        # only host5 supports them.
        self.assertEqual('host5', server['OS-EXT-SRV-ATTR:host'])

    def test_migrate(self):
        net = self.neutron.network_multisegment
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'uuid': net['id']}])
        # Make sure we landed on host2 since both segments were accepted
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        server = self._migrate_server(server)
        # HostNameWeigherFixture prefers host1 but the port is in a network
        # that has only segments on the other hosts.
        # host2 is avoided as the source and only host4 is left on this
        # segment.
        self.assertEqual('host4', server['OS-EXT-SRV-ATTR:host'])

    def test_live_migrate(self):
        net = self.neutron.network_multisegment
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'uuid': net['id']}])
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        self._live_migrate(server)
        server = self.api.get_server(server['id'])
        # HostNameWeigherFixture prefers host1 but the port is in a network
        # that has only segments on the other hosts.
        # host2 is avoided as the source and only host4 is left on this
        # segment.
        self.assertEqual('host4', server['OS-EXT-SRV-ATTR:host'])

    def test_evacuate(self):
        net = self.neutron.network_multisegment
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'uuid': net['id']}])

        # The instance landed on host2 as the segment was related.
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        self.admin_api.put_service_force_down(self.compute2_service_id, True)
        server = self._evacuate_server(server)
        # HostNameWeigherFixture prefers host1 but the port is in a network
        # that has only segments on the other hosts.
        # host2 is avoided as the source and only host4 is left on this
        # segment.
        self.assertEqual('host4', server['OS-EXT-SRV-ATTR:host'])

    def test_unshelve_after_shelve(self):
        net = self.neutron.network_multisegment
        server = self._create_server(
            name='server-with-routed-net',
            networks=[{'uuid': net['id']}])
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        # Shelve does offload the instance so unshelve will ask the scheduler
        # again.
        server = self._shelve_server(server)
        server = self._unshelve_server(server)
        # HostNameWeigherFixture prefers host1 but the port is in a network
        # that has only segments on the others. Since the instance was
        # offloaded, we can now again support host2.
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

    def test_boot_with_immediate_port_fails_due_to_config(self):
        # We will fake the fact that somehow the segment has no related
        # aggregate (maybe because Neutron got a exception when trying to
        # create the aggregate by calling the Nova API)
        port = self.neutron.port_on_segment_id_2
        with mock.patch(
            'nova.scheduler.client.report.SchedulerReportClient.'
            '_get_provider_aggregates',
            return_value=None
        ) as mock_get_aggregates:
            server = self._create_server(
                name='server-with-routed-net',
                networks=[{'port': port['id']}],
                expected_state='ERROR')

        # Make sure we correctly looked up at which aggregates were related to
        # the segment ID #2
        expected_subnet_id = self.neutron.subnet_for_segment_id_2['id']
        expected_segment_id = self.neutron.segment_id_2['id']
        mock_get_aggregates.assert_called_once_with(
            mock.ANY, expected_segment_id)

        self.assertIn('No valid host', server['fault']['message'])
        self.assertIn(
            'Aggregates not found for the subnet %s' % expected_subnet_id,
            server['fault']['message'])
