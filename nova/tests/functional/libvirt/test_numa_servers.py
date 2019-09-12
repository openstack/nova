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

import mock
from oslo_config import cfg
from oslo_log import log as logging

from nova.conf import neutron as neutron_conf
from nova import context as nova_context
from nova import objects
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class NUMAServersTestBase(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        super(NUMAServersTestBase, self).setUp()

        # Mock the 'NUMATopologyFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.driver.host_manager
        numa_filter_class = host_manager.filter_cls_map['NUMATopologyFilter']
        host_pass_mock = mock.Mock(wraps=numa_filter_class().host_passes)
        _p = mock.patch('nova.scheduler.filters'
                        '.numa_topology_filter.NUMATopologyFilter.host_passes',
                        side_effect=host_pass_mock)
        self.mock_filter = _p.start()
        self.addCleanup(_p.stop)


class NUMAServersTest(NUMAServersTestBase):

    def _run_build_test(self, flavor_id, end_status='ACTIVE',
                        expected_usage=None):

        # NOTE(bhagyashris): Always use host as 'compute1' so that it's
        # possible to get resource provider information for verifying
        # compute usages. This host name 'compute1' is hard coded in
        # Connection class in fakelibvirt.py.
        # TODO(stephenfin): Remove the hardcoded limit, possibly overridding
        # 'start_service' to make sure there isn't a mismatch
        self.compute = self.start_service('compute', host='compute1')

        compute_rp_uuid = self.placement_api.get(
            '/resource_providers?name=compute1').body[
            'resource_providers'][0]['uuid']

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
        self.assertTrue(self.mock_filter.called)

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        if expected_usage:
            compute_usage = self.placement_api.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)

        self.assertEqual(end_status, found_server['status'])
        self.addCleanup(self._delete_server, created_server_id)
        return created_server

    def test_create_server_with_numa_topology(self):
        """Create a server with two NUMA nodes.

        This should pass and result in a guest NUMA topology with two NUMA
        nodes.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)
        self.mock_conn.return_value = fake_connection

        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2}

        server = self._run_build_test(flavor_id, expected_usage=expected_usage)

        ctx = nova_context.get_admin_context()
        inst = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertEqual(2, len(inst.numa_topology.cells))
        self.assertNotIn('cpu_topology', inst.numa_topology.cells[0])
        self.assertNotIn('cpu_topology', inst.numa_topology.cells[1])

    def test_create_server_with_numa_fails(self):
        """Create a two NUMA node instance on a host with only one node.

        This should fail because each guest NUMA node must be placed on a
        separate host NUMA node.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=2, kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)
        self.mock_conn.return_value = fake_connection

        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR')

    def test_create_server_with_pinning(self):
        """Create a server using the legacy 'hw:cpu_policy' extra spec.

        This should pass and result in a guest NUMA topology with pinned CPUs.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2,
                                         kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        flavor_id = self._create_flavor(vcpu=5, extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 5}

        server = self._run_build_test(flavor_id, expected_usage=expected_usage)

        ctx = nova_context.get_admin_context()
        inst = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertEqual(1, len(inst.numa_topology.cells))
        self.assertEqual(5, inst.numa_topology.cells[0].cpu_topology.cores)

    def test_resize_unpinned_to_pinned(self):
        """Create an unpinned instance and resize it to a flavor with pinning.

        This should pass and result in a guest NUMA topology with pinned CPUs.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)

        # Start services
        self.computes = {}
        self.compute_rp_uuids = {}
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

            # and save the UUIDs for the corresponding resource providers
            self.compute_rp_uuids[host] = self.placement_api.get(
                '/resource_providers?name=%s' % host).body[
                'resource_providers'][0]['uuid']

        # Create server
        flavor_a_id = self._create_flavor(extra_spec={})
        good_server = self._build_server(flavor_a_id)

        post = {'server': good_server}

        created_server = self.api.post_server(post)
        server = self._wait_for_state_change(created_server, 'BUILD')

        self.assertEqual('ACTIVE', server['status'])

        original_host = server['OS-EXT-SRV-ATTR:host']

        for host, compute_rp_uuid in self.compute_rp_uuids.items():
            # TODO(stephenfin): Both of these should report PCPU when we
            # support that
            if host == original_host:  # the host with the instance
                expected_usage = {'VCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}
            else:  # the other host
                expected_usage = {'VCPU': 0, 'DISK_GB': 0,
                                  'MEMORY_MB': 0}

            compute_usage = self.placement_api.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)

        # We reset mock_filter because we want to ensure it's called as part of
        # the *migration*
        self.mock_filter.reset_mock()
        self.assertEqual(0, len(self.mock_filter.call_args_list))

        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_b_id = self._create_flavor(extra_spec=extra_spec)

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            post = {'resize': {'flavorRef': flavor_b_id}}
            self.api.post_server_action(server['id'], post)

        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')

        new_host = server['OS-EXT-SRV-ATTR:host']
        self.assertNotEqual(original_host, new_host)

        # We don't confirm the resize yet as we expect this to have landed and
        # all we want to know is whether the filter was correct and the
        # resource usage has been updated

        for host, compute_rp_uuid in self.compute_rp_uuids.items():
            # TODO(stephenfin): This should use PCPU when we support those
            if host == original_host:
                # the host that had the instance should still have allocations
                # since the resize hasn't been confirmed
                expected_usage = {'VCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}
            else:
                # the other host should have the new allocations replete with
                # PCPUs
                expected_usage = {'VCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}

            compute_usage = self.placement_api.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)

        self.assertEqual(1, len(self.mock_filter.call_args_list))
        args, kwargs = self.mock_filter.call_args_list[0]
        self.assertEqual(2, len(args))
        self.assertEqual({}, kwargs)

        # Now confirm the resize and ensure our inventories update

        post = {'confirmResize': None}
        self.api.post_server_action(server['id'], post)

        server = self._wait_for_state_change(server, 'ACTIVE')

        for host, compute_rp_uuid in self.compute_rp_uuids.items():
            # TODO(stephenfin): This should use PCPU when we support those
            if host == original_host:
                # the host that had the instance should no longer have
                # alocations since the resize has been confirmed
                expected_usage = {'VCPU': 0, 'DISK_GB': 0,
                                  'MEMORY_MB': 0}
            else:
                # the other host should still have the new allocations replete
                # with PCPUs
                expected_usage = {'VCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}

            compute_usage = self.placement_api.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)


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
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))

    def _test_create_server_with_networks(self, flavor_id, networks):
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        status = self._test_create_server_with_networks(
            flavor_id, networks)['status']

        self.assertTrue(self.mock_filter.called)
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
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
            {'uuid': base.LibvirtNeutronFixture.network_2['id']},
        ]

        status = self._test_create_server_with_networks(
            flavor_id, networks)['status']

        self.assertTrue(self.mock_filter.called)
        self.assertEqual('ACTIVE', status)

    def test_create_server_with_multiple_physnets_fail(self):
        """Test multiple networks split across host NUMA nodes.

        This should fail because we've requested a single-node instance but the
        networks requested are split across multiple host NUMA nodes.
        """
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
            {'uuid': base.LibvirtNeutronFixture.network_2['id']},
        ]

        status = self._test_create_server_with_networks(
            flavor_id, networks)['status']

        self.assertTrue(self.mock_filter.called)
        self.assertEqual('ERROR', status)

    def test_create_server_with_physnet_and_tunneled_net(self):
        """Test combination of physnet and tunneled network.

        This should pass because we've requested a single-node instance and the
        requested networks share at least one NUMA node.
        """
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
            {'uuid': base.LibvirtNeutronFixture.network_3['id']},
        ]

        status = self._test_create_server_with_networks(
            flavor_id, networks)['status']

        self.assertTrue(self.mock_filter.called)
        self.assertEqual('ACTIVE', status)

    def test_rebuild_server_with_network_affinity(self):
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        server = self._test_create_server_with_networks(flavor_id, networks)

        self.assertEqual('ACTIVE', server['status'])

        # attach an interface from the **same** network
        post = {
            'interfaceAttachment': {
                'net_id': base.LibvirtNeutronFixture.network_1['id'],
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
                'net_id': base.LibvirtNeutronFixture.network_2['id'],
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
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        good_server = self._build_server(flavor_id)
        good_server['networks'] = networks
        post = {'server': good_server}

        created_server = self.api.post_server(post)
        server = self._wait_for_state_change(created_server, 'BUILD')

        self.assertEqual('ACTIVE', server['status'])
        original_host = server['OS-EXT-SRV-ATTR:host']

        # We reset mock_filter because we want to ensure it's called as part of
        # the *migration*
        self.mock_filter.reset_mock()
        self.assertEqual(0, len(self.mock_filter.call_args_list))

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            self.api.post_server_action(server['id'], {'migrate': None})

        server = self._wait_for_state_change(created_server, 'VERIFY_RESIZE')

        # We don't bother confirming the resize as we expect this to have
        # landed and all we want to know is whether the filter was correct
        self.assertNotEqual(original_host, server['OS-EXT-SRV-ATTR:host'])

        self.assertEqual(1, len(self.mock_filter.call_args_list))
        args, kwargs = self.mock_filter.call_args_list[0]
        self.assertEqual(2, len(args))
        self.assertEqual({}, kwargs)
        network_metadata = args[1].network_metadata
        self.assertIsNotNone(network_metadata)
        self.assertEqual(set(['foo']), network_metadata.physnets)

    def test_cold_migrate_with_physnet_fails(self):
        host_infos = [
            # host 1 has room on both nodes
            fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                 cpu_cores=2, cpu_threads=2,
                                 kB_mem=15740000),
            # host 2 has no second node, where the desired physnet is
            # reported to be attached
            fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
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
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
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
