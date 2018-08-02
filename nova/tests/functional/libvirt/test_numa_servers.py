# Copyright (C) 2015 Red Hat, Inc
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

import six

import fixtures
import mock
from oslo_config import cfg
from oslo_log import log as logging

from nova.conf import neutron as neutron_conf
from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional.test_servers import ServersTestBase
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class NUMAServersTestBase(ServersTestBase):

    def setUp(self):
        super(NUMAServersTestBase, self).setUp()

        # Replace libvirt with fakelibvirt
        self.useFixture(fake_imagebackend.ImageBackendFixture())
        self.useFixture(fixtures.MonkeyPatch(
           'nova.virt.libvirt.driver.libvirt_utils',
           fake_libvirt_utils))
        self.useFixture(fixtures.MonkeyPatch(
           'nova.virt.libvirt.driver.libvirt',
           fakelibvirt))
        self.useFixture(fixtures.MonkeyPatch(
           'nova.virt.libvirt.host.libvirt',
           fakelibvirt))
        self.useFixture(fixtures.MonkeyPatch(
           'nova.virt.libvirt.guest.libvirt',
           fakelibvirt))
        self.useFixture(fakelibvirt.FakeLibvirtFixture())

    def _setup_compute_service(self):
        # we need to mock some libvirt stuff so we start this service in the
        # test instead
        pass

    def _setup_scheduler_service(self):
        self.flags(compute_driver='libvirt.LibvirtDriver')

        self.flags(driver='filter_scheduler', group='scheduler')
        self.flags(enabled_filters=CONF.filter_scheduler.enabled_filters
                                   + ['NUMATopologyFilter'],
                   group='filter_scheduler')
        return self.start_service('scheduler')

    def _get_connection(self, host_info):
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                version=fakelibvirt.FAKE_LIBVIRT_VERSION,
                                hv_version=fakelibvirt.FAKE_QEMU_VERSION,
                                host_info=host_info)
        return fake_connection

    def _get_topology_filter_spy(self):
        host_manager = self.scheduler.manager.driver.host_manager
        numa_filter_class = host_manager.filter_cls_map['NUMATopologyFilter']
        host_pass_mock = mock.Mock(wraps=numa_filter_class().host_passes)
        return host_pass_mock


class NUMAServersTest(NUMAServersTestBase):

    def _run_build_test(self, flavor_id, filter_mock, end_status='ACTIVE'):

        self.compute = self.start_service('compute', host='test_compute0')

        # Create server
        good_server = self._build_server(flavor_id)

        post = {'server': good_server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Validate that the server has been created
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        # It should also be in the all-servers list
        servers = self.api.get_servers()
        server_ids = [s['id'] for s in servers]
        self.assertIn(created_server_id, server_ids)

        # Validate that NUMATopologyFilter has been called
        self.assertTrue(filter_mock.called)

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual(end_status, found_server['status'])
        self.addCleanup(self._delete_server, created_server_id)
        return created_server

    def test_create_server_with_numa_topology(self):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)

        # Create a flavor
        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        host_pass_mock = self._get_topology_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            self._run_build_test(flavor_id, filter_mock)

    def test_create_server_with_pinning(self):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=1, cpu_sockets=1,
                                             cpu_cores=5, cpu_threads=2,
                                             kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)

        # Create a flavor
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }

        flavor_id = self._create_flavor(vcpu=5, extra_spec=extra_spec)
        host_pass_mock = self._get_topology_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            server = self._run_build_test(flavor_id, filter_mock)
            ctx = nova_context.get_admin_context()
            inst = objects.Instance.get_by_uuid(ctx, server['id'])
            self.assertEqual(1, len(inst.numa_topology.cells))
            self.assertEqual(5, inst.numa_topology.cells[0].cpu_topology.cores)

    def test_create_server_with_numa_fails(self):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=1, cpu_sockets=1,
                                             cpu_cores=2, kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)

        # Create a flavor
        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        host_pass_mock = self._get_topology_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            self._run_build_test(flavor_id, filter_mock, end_status='ERROR')


class NUMAAffinityNeutronFixture(nova_fixtures.NeutronFixture):
    """A custom variant of the stock neutron fixture with more networks.

    There are three networks available: two l2 networks (one flat and one VLAN)
    and one l3 network (VXLAN).
    """
    network_1 = {
        'id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
        'status': 'ACTIVE',
        'subnets': [],
        'name': 'physical-network-foo',
        'admin_state_up': True,
        'tenant_id': nova_fixtures.NeutronFixture.tenant_id,
        'provider:physical_network': 'foo',
        'provider:network_type': 'flat',
        'provider:segmentation_id': None,
    }
    network_2 = network_1.copy()
    network_2.update({
        'id': 'a252b8cd-2d99-4e82-9a97-ec1217c496f5',
        'name': 'physical-network-bar',
        'provider:physical_network': 'bar',
        'provider:network_type': 'vlan',
        'provider:segmentation_id': 123,
    })
    network_3 = network_1.copy()
    network_3.update({
        'id': '877a79cc-295b-4b80-9606-092bf132931e',
        'name': 'tunneled-network',
        'provider:physical_network': None,
        'provider:network_type': 'vxlan',
        'provider:segmentation_id': 69,
    })

    subnet_1 = nova_fixtures.NeutronFixture.subnet_1.copy()
    subnet_1.update({
        'name': 'physical-subnet-foo',
    })
    subnet_2 = nova_fixtures.NeutronFixture.subnet_1.copy()
    subnet_2.update({
        'id': 'b4c13749-c002-47ed-bf42-8b1d44fa9ff2',
        'name': 'physical-subnet-bar',
        'network_id': network_2['id'],
    })
    subnet_3 = nova_fixtures.NeutronFixture.subnet_1.copy()
    subnet_3.update({
        'id': '4dacb20b-917f-4275-aa75-825894553442',
        'name': 'tunneled-subnet',
        'network_id': network_3['id'],
    })
    network_1['subnets'] = [subnet_1]
    network_2['subnets'] = [subnet_2]
    network_3['subnets'] = [subnet_3]

    network_1_port_2 = {
        'id': 'f32582b5-8694-4be8-9a52-c5732f601c9d',
        'network_id': network_1['id'],
        'status': 'ACTIVE',
        'mac_address': '71:ce:c7:8b:cd:dc',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.10',
                'subnet_id': subnet_1['id']
            }
        ],
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
    }
    network_1_port_3 = {
        'id': '9c7580a0-8b01-41f3-ba07-a114709a4b74',
        'network_id': network_1['id'],
        'status': 'ACTIVE',
        'mac_address': '71:ce:c7:2b:cd:dc',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.11',
                'subnet_id': subnet_1['id']
            }
        ],
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
    }
    network_2_port_1 = {
        'id': '67d36444-6353-40f5-9e92-59346cf0dfda',
        'network_id': network_2['id'],
        'status': 'ACTIVE',
        'mac_address': 'd2:0b:fd:d7:89:9b',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.6',
                'subnet_id': subnet_2['id']
            }
        ],
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
    }
    network_3_port_1 = {
        'id': '4bfa1dc4-4354-4840-b0b4-f06196fa1344',
        'network_id': network_3['id'],
        'status': 'ACTIVE',
        'mac_address': 'd2:0b:fd:99:89:9b',
        'fixed_ips': [
            {
                'ip_address': '192.168.2.6',
                'subnet_id': subnet_3['id']
            }
        ],
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
    }

    def __init__(self, test):
        super(NUMAAffinityNeutronFixture, self).__init__(test)
        self._networks = [self.network_1, self.network_2, self.network_3]
        self._net1_ports = [self.network_1_port_2, self.network_1_port_3]

    def create_port(self, body=None):
        if not body:
            # even though 'body' is apparently nullable, body will always be
            # set here
            assert('Body should not be None')

        network_id = body['port']['network_id']
        assert network_id in ([n['id'] for n in self._networks]), (
                'Network %s not in fixture' % network_id)

        if network_id == self.network_1['id']:
            port = self._net1_ports.pop(0)
        elif network_id == self.network_2['id']:
            port = self.network_2_port_1
        elif network_id == self.network_3['id']:
            port = self.network_3_port_1

        port = port.copy()
        port.update(body['port'])
        self._ports.append(port)
        return {'port': port}


class NUMAServersWithNetworksTest(NUMAServersTestBase):

    def setUp(self):
        # We need to enable neutron in this one
        self.flags(physnets=['foo', 'bar'], group='neutron')
        neutron_conf.register_dynamic_opts(CONF)
        self.flags(numa_nodes=[1], group='neutron_physnet_foo')
        self.flags(numa_nodes=[0], group='neutron_physnet_bar')
        self.flags(numa_nodes=[0, 1], group='neutron_tunnel')

        super(NUMAServersWithNetworksTest, self).setUp()

        # The ultimate base class _IntegratedTestBase uses NeutronFixture but
        # we need a bit more intelligent neutron for these tests. Applying the
        # new fixture here means that we re-stub what the previous neutron
        # fixture already stubbed.
        self.neutron = self.useFixture(NUMAAffinityNeutronFixture(self))

        _p = mock.patch('nova.virt.libvirt.host.Host.get_connection')
        self.mock_conn = _p.start()
        self.addCleanup(_p.stop)

    def _test_create_server_with_networks(self, flavor_id, networks):
        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)
        self.mock_conn.return_value = fake_connection

        self.compute = self.start_service('compute', host='test_compute0')

        # Create server
        good_server = self._build_server(flavor_id)
        good_server['networks'] = networks
        post = {'server': good_server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)

        found_server = self.api.get_server(created_server['id'])

        return self._wait_for_state_change(found_server, 'BUILD')

    def test_create_server_with_single_physnet(self):
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
        ]

        host_pass_mock = self._get_topology_filter_spy()
        with mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock) as filter_mock:
            status = self._test_create_server_with_networks(
                flavor_id, networks)['status']

        self.assertTrue(filter_mock.called)
        self.assertEqual('ACTIVE', status)

    def test_create_server_with_multiple_physnets(self):
        """Test multiple networks split across host NUMA nodes.

        This should pass because the networks requested are split across
        multiple host NUMA nodes but the guest explicitly allows multiple NUMA
        nodes.
        """
        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
            {'uuid': NUMAAffinityNeutronFixture.network_2['id']},
        ]

        host_pass_mock = self._get_topology_filter_spy()
        with mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock) as filter_mock:
            status = self._test_create_server_with_networks(
                flavor_id, networks)['status']

        self.assertTrue(filter_mock.called)
        self.assertEqual('ACTIVE', status)

    def test_create_server_with_multiple_physnets_fail(self):
        """Test multiple networks split across host NUMA nodes.

        This should fail because we've requested a single-node instance but the
        networks requested are split across multiple host NUMA nodes.
        """
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
            {'uuid': NUMAAffinityNeutronFixture.network_2['id']},
        ]

        host_pass_mock = self._get_topology_filter_spy()
        with mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock) as filter_mock:
            status = self._test_create_server_with_networks(
                flavor_id, networks)['status']

        self.assertTrue(filter_mock.called)
        self.assertEqual('ERROR', status)

    def test_create_server_with_physnet_and_tunneled_net(self):
        """Test combination of physnet and tunneled network.

        This should pass because we've requested a single-node instance and the
        requested networks share at least one NUMA node.
        """
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
            {'uuid': NUMAAffinityNeutronFixture.network_3['id']},
        ]

        host_pass_mock = self._get_topology_filter_spy()
        with mock.patch('nova.scheduler.filters'
                       '.numa_topology_filter.NUMATopologyFilter.host_passes',
                       side_effect=host_pass_mock) as filter_mock:
            status = self._test_create_server_with_networks(
                flavor_id, networks)['status']

        self.assertTrue(filter_mock.called)
        self.assertEqual('ACTIVE', status)

    def test_rebuild_server_with_network_affinity(self):
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
        ]

        server = self._test_create_server_with_networks(flavor_id, networks)

        self.assertEqual('ACTIVE', server['status'])

        # attach an interface from the **same** network
        post = {
            'interfaceAttachment': {
                'net_id': NUMAAffinityNeutronFixture.network_1['id'],
            }
        }
        self.api.attach_interface(server['id'], post)

        post = {'rebuild': {
            'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
        }}

        # This should succeed since we haven't changed the NUMA affinity
        # requirements
        self.api.post_server_action(server['id'], post)
        found_server = self._wait_for_state_change(server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # attach an interface from a **different** network
        post = {
            'interfaceAttachment': {
                'net_id': NUMAAffinityNeutronFixture.network_2['id'],
            }
        }
        self.api.attach_interface(server['id'], post)
        post = {'rebuild': {
            'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
        }}
        # Now this should fail because we've violated the NUMA requirements
        # with the latest attachment
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action, server['id'], post)
        # NOTE(danms): This wouldn't happen in a real deployment since rebuild
        # is a cast, but since we are using CastAsCall this will bubble to the
        # API.
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', six.text_type(ex))

    def test_cold_migrate_with_physnet(self):
        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)

        # Start services
        self.computes = {}
        for host in ['test_compute0', 'test_compute1']:
            fake_connection = self._get_connection(host_info=host_info)
            fake_connection.getHostname = lambda: host

            # This is fun. Firstly we need to do a global'ish mock so we can
            # actually start the service.
            with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                            return_value=fake_connection):
                compute = self.start_service('compute', host=host)

            # Once that's done, we need to do some tweaks to each individual
            # compute "service" to make sure they return unique objects
            compute.driver._host.get_connection = lambda: fake_connection
            self.computes[host] = compute

        # Create server
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
        ]

        good_server = self._build_server(flavor_id)
        good_server['networks'] = networks
        post = {'server': good_server}

        created_server = self.api.post_server(post)
        server = self._wait_for_state_change(created_server, 'BUILD')

        self.assertEqual('ACTIVE', server['status'])
        original_host = server['OS-EXT-SRV-ATTR:host']

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        host_pass_mock = self._get_topology_filter_spy()
        with mock.patch('nova.scheduler.filters'
                        '.numa_topology_filter.NUMATopologyFilter.host_passes',
                        side_effect=host_pass_mock) as filter_mock, \
                mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                          '.migrate_disk_and_power_off', return_value='{}'):
            self.api.post_server_action(server['id'], {'migrate': None})

        server = self._wait_for_state_change(created_server, 'VERIFY_RESIZE')

        # We don't bother confirming the resize as we expect this to have
        # landed and all we want to know is whether the filter was correct
        self.assertNotEqual(original_host, server['OS-EXT-SRV-ATTR:host'])

        self.assertEqual(1, len(filter_mock.call_args_list))
        args, kwargs = filter_mock.call_args_list[0]
        self.assertEqual(2, len(args))
        self.assertEqual({}, kwargs)
        network_metadata = args[1].network_metadata
        self.assertIsNotNone(network_metadata)
        self.assertEqual(set(['foo']), network_metadata.physnets)

    def test_cold_migrate_with_physnet_fails(self):
        host_infos = [
            # host 1 has room on both nodes
            fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                     cpu_cores=2, cpu_threads=2,
                                     kB_mem=15740000),
            # host 2 has no second node, where the desired physnet is
            # reported to be attached
            fakelibvirt.NUMAHostInfo(cpu_nodes=1, cpu_sockets=1,
                                     cpu_cores=1, cpu_threads=1,
                                     kB_mem=15740000),
        ]

        # Start services
        self.computes = {}
        for host in ['test_compute0', 'test_compute1']:
            host_info = host_infos.pop(0)
            fake_connection = self._get_connection(host_info=host_info)
            fake_connection.getHostname = lambda: host

            # This is fun. Firstly we need to do a global'ish mock so we can
            # actually start the service.
            with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                            return_value=fake_connection):
                compute = self.start_service('compute', host=host)

            # Once that's done, we need to do some tweaks to each individual
            # compute "service" to make sure they return unique objects
            compute.driver._host.get_connection = lambda: fake_connection
            self.computes[host] = compute

        # Create server
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': NUMAAffinityNeutronFixture.network_1['id']},
        ]

        good_server = self._build_server(flavor_id)
        good_server['networks'] = networks
        post = {'server': good_server}

        created_server = self.api.post_server(post)
        server = self._wait_for_state_change(created_server, 'BUILD')

        self.assertEqual('ACTIVE', server['status'])

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            ex = self.assertRaises(client.OpenStackApiException,
                                   self.api.post_server_action,
                                   server['id'], {'migrate': None})
            self.assertEqual(400, ex.response.status_code)
            self.assertIn('No valid host', six.text_type(ex))
