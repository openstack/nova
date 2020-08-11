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

import mock
import six
import testtools

from oslo_config import cfg
from oslo_log import log as logging

import nova
from nova.conf import neutron as neutron_conf
from nova import context as nova_context
from nova import objects
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.tests.unit import fake_notifier
from nova.tests.unit.virt.libvirt import fakelibvirt

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class NUMAServersTestBase(base.ServersTestBase):
    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        super(NUMAServersTestBase, self).setUp()

        self.ctxt = nova_context.get_admin_context()

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
                        filter_called_on_error=True,
                        expected_usage=None):

        compute_rp_uuid = self.placement.get(
            '/resource_providers?name=compute1').body[
            'resource_providers'][0]['uuid']

        # Create server
        created_server = self._create_server(
            flavor_id=flavor_id,
            expected_state=end_status)

        # Validate the quota usage
        if filter_called_on_error and end_status == 'ACTIVE':
            quota_details = self.api.get_quota_detail()
            expected_core_usages = expected_usage.get(
                'VCPU', expected_usage.get('PCPU', 0))
            self.assertEqual(expected_core_usages,
                             quota_details['cores']['in_use'])

        # Validate that NUMATopologyFilter has been called or not called,
        # depending on whether this is expected to make it past placement or
        # not (hint: if it's a lack of VCPU/PCPU resources, it won't)
        if filter_called_on_error:
            self.assertTrue(self.mock_filter.called)
        else:
            self.assertFalse(self.mock_filter.called)

        if expected_usage:
            compute_usage = self.placement.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)

        self.addCleanup(self._delete_server, created_server)
        return created_server

    def test_create_server_with_numa_topology(self):
        """Create a server with two NUMA nodes.

        This should pass and result in a guest NUMA topology with two NUMA
        nodes.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

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
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {'hw:numa_nodes': '2'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR')

    def test_create_server_with_hugepages(self):
        """Create a server with huge pages.

        Configuring huge pages against a server also necessitates configuring a
        NUMA topology.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=2,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=(1024 * 1024 * 16))  # GB
        # create 1024 * 2 MB huge pages, and allocate the rest of the 16 GB as
        # small pages
        for cell in host_info.numa_topology.cells:
            huge_pages = 1024
            small_pages = (host_info.kB_mem - (2048 * huge_pages)) // 4
            cell.mempages = fakelibvirt.create_mempages([
                (4, small_pages),
                (2048, huge_pages),
            ])
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {'hw:mem_page_size': 'large'}
        flavor_id = self._create_flavor(memory_mb=2048, extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2}

        server = self._run_build_test(flavor_id, expected_usage=expected_usage)

        ctx = nova_context.get_admin_context()
        inst = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertEqual(1, len(inst.numa_topology.cells))
        self.assertEqual(2048, inst.numa_topology.cells[0].pagesize)  # kB
        self.assertEqual(2048, inst.numa_topology.cells[0].memory)  # MB

    def test_create_server_with_hugepages_fails(self):
        """Create a server with huge pages on a host that doesn't support them.

        This should fail because there are hugepages but not enough of them.
        """

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=2,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=(1024 * 1024 * 16))  # GB
        self.start_compute(host_info=host_info, hostname='compute1')

        # create 512 * 2 MB huge pages, and allocate the rest of the 16 GB as
        # small pages
        for cell in host_info.numa_topology.cells:
            huge_pages = 512
            small_pages = (host_info.kB_mem - (2048 * huge_pages)) // 4
            cell.mempages = fakelibvirt.create_mempages([
                (4, small_pages),
                (2048, huge_pages),
            ])

        extra_spec = {'hw:mem_page_size': 'large'}
        flavor_id = self._create_flavor(memory_mb=2048, extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR')

    def test_create_server_with_legacy_pinning_policy(self):
        """Create a server using the legacy 'hw:cpu_policy' extra spec.

        This should pass and result in a guest NUMA topology with pinned CPUs.
        """

        self.flags(cpu_dedicated_set='0-9', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        flavor_id = self._create_flavor(vcpu=5, extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'PCPU': 5}

        server = self._run_build_test(flavor_id, expected_usage=expected_usage)

        inst = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        self.assertEqual(1, len(inst.numa_topology.cells))
        self.assertEqual(5, inst.numa_topology.cells[0].cpu_topology.cores)

    def test_create_server_with_legacy_pinning_policy_old_configuration(self):
        """Create a server using the legacy extra spec and configuration.

        This should pass and result in a guest NUMA topology with pinned CPUs,
        though we'll still be consuming VCPUs (which would in theory be fixed
        during a later reshape).
        """

        self.flags(cpu_dedicated_set=None, cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set='0-7')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2}

        self._run_build_test(flavor_id, expected_usage=expected_usage)

    def test_create_server_with_isolate_thread_policy_old_configuration(self):
        """Create a server with the legacy 'hw:cpu_thread_policy=isolate' extra
        spec and configuration.

        This should pass and result in an instance consuming $flavor.vcpu host
        cores plus the thread sibling(s) of each of these cores. We also be
        consuming VCPUs since we're on legacy configuration here, though that
        would in theory be fixed during a later reshape.
        """
        self.flags(
            cpu_dedicated_set=None, cpu_shared_set=None, group='compute')
        self.flags(vcpu_pin_set='0-3')

        # host has hyperthreads, which means we're going to end up consuming
        # $flavor.vcpu hosts cores plus the thread sibling(s) for each core
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
            kB_mem=(1024 * 1024 * 16),  # GB
        )
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'isolate',
        }
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2}
        self._run_build_test(flavor_id, expected_usage=expected_usage)

        # verify that we have consumed two cores plus the thread sibling of
        # each core, totalling four cores since the HostInfo indicates each
        # core should have two threads
        ctxt = nova_context.get_admin_context()
        host_numa = objects.NUMATopology.obj_from_db_obj(
            objects.ComputeNode.get_by_nodename(ctxt, 'compute1').numa_topology
        )
        self.assertEqual({0, 1, 2, 3}, host_numa.cells[0].pinned_cpus)

    def test_create_server_with_legacy_pinning_policy_fails(self):
        """Create a pinned instance on a host with no PCPUs.

        This should fail because we're translating the extra spec and the host
        isn't reporting the PCPUs we need.
        """

        self.flags(cpu_shared_set='0-9', cpu_dedicated_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        flavor_id = self._create_flavor(vcpu=5, extra_spec=extra_spec)
        self._run_build_test(flavor_id, end_status='ERROR')

    def test_create_server_with_legacy_pinning_policy_quota_fails(self):
        """Create a pinned instance on a host with PCPUs but not enough quota.

        This should fail because the quota request should fail.
        """
        self.flags(cpu_dedicated_set='0-7', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        # Update the core quota less than we requested
        self.admin_api.update_quota({'cores': 1})

        post = {'server': self._build_server(flavor_id=flavor_id)}

        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server, post)
        self.assertEqual(403, ex.response.status_code)

    def test_create_server_with_isolate_thread_policy_fails(self):
        """Create a server with the legacy 'hw:cpu_thread_policy=isolate' extra
        spec.

        This should fail on a host with hyperthreading.
        """
        self.flags(
            cpu_dedicated_set='0-3', cpu_shared_set='4-7', group='compute')
        self.flags(vcpu_pin_set=None)

        # host has hyperthreads, which means it should be rejected
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
            kB_mem=(1024 * 1024 * 16),  # GB
        )
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'isolate',
        }
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR')

    def test_create_server_with_pcpu(self):
        """Create a server using an explicit 'resources:PCPU' request.

        This should pass and result in a guest NUMA topology with pinned CPUs.
        """

        self.flags(cpu_dedicated_set='0-7', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {'resources:PCPU': '2'}
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)
        expected_usage = {'DISK_GB': 20, 'MEMORY_MB': 2048, 'PCPU': 2}

        server = self._run_build_test(flavor_id, expected_usage=expected_usage)

        ctx = nova_context.get_admin_context()
        inst = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertEqual(1, len(inst.numa_topology.cells))
        self.assertEqual(1, inst.numa_topology.cells[0].cpu_topology.cores)
        self.assertEqual(2, inst.numa_topology.cells[0].cpu_topology.threads)

    def test_create_server_with_pcpu_fails(self):
        """Create a pinned instance on a host with no PCPUs.

        This should fail because we're explicitly requesting PCPUs and the host
        isn't reporting them.
        """

        self.flags(cpu_shared_set='0-9', cpu_dedicated_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {'resources:PCPU': 2}
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR',
                             filter_called_on_error=False)

    def test_create_server_with_pcpu_quota_fails(self):
        """Create a pinned instance on a host with PCPUs but not enough quota.

        This should fail because the quota request should fail.
        """
        self.flags(cpu_dedicated_set='0-7', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        extra_spec = {'resources:PCPU': '2'}
        flavor_id = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        # Update the core quota less than we requested
        self.admin_api.update_quota({'cores': 1})

        post = {'server': self._build_server(flavor_id=flavor_id)}

        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server, post)
        self.assertEqual(403, ex.response.status_code)

    def _inspect_filter_numa_topology(self, cell_count):
        """Helper function used by test_resize_server_with_numa* tests."""
        args, kwargs = self.mock_filter.call_args_list[0]
        self.assertEqual(2, len(args))
        self.assertEqual({}, kwargs)
        numa_topology = args[1].numa_topology
        self.assertEqual(cell_count, len(numa_topology.cells), args)

        # We always reset mock_filter because we don't want these result
        # fudging later tests
        self.mock_filter.reset_mock()
        self.assertEqual(0, len(self.mock_filter.call_args_list))

    def _inspect_request_spec(self, server, cell_count):
        """Helper function used by test_resize_server_with_numa* tests."""
        req_spec = objects.RequestSpec.get_by_instance_uuid(
            self.ctxt, server['id'])
        self.assertEqual(cell_count, len(req_spec.numa_topology.cells))

    def test_resize_revert_server_with_numa(self):
        """Create a single-node instance and resize it to a flavor with two
        nodes, then revert to the old flavor rather than confirm.

        Nothing too complicated going on here. We create an instance with a one
        NUMA node guest topology and then attempt to resize this to use a
        topology with two nodes. Once done, we revert this resize to ensure the
        instance reverts to using the old NUMA topology as expected.
        """
        # don't bother waiting for neutron events since we don't actually have
        # neutron
        self.flags(vif_plugging_timeout=0)

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)

        # Start services
        self.start_compute(host_info=host_info, hostname='test_compute0')
        self.start_compute(host_info=host_info, hostname='test_compute1')

        # STEP ONE

        # Create server
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_a_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)

        server = self._create_server(flavor_id=flavor_a_id)

        # Ensure the filter saw the 'numa_topology' field and the request spec
        # is as expected
        self._inspect_filter_numa_topology(cell_count=1)
        self._inspect_request_spec(server, cell_count=1)

        # STEP TWO

        # Create a new flavor with a different but still valid number of NUMA
        # nodes
        extra_spec = {'hw:numa_nodes': '2'}
        flavor_b_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            post = {'resize': {'flavorRef': flavor_b_id}}
            self.api.post_server_action(server['id'], post)

        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # Ensure the filter saw 'hw:numa_nodes=2' from flavor_b and the request
        # spec has been updated
        self._inspect_filter_numa_topology(cell_count=2)
        self._inspect_request_spec(server, cell_count=2)

        # STEP THREE

        # Revert the instance rather than confirming it, and ensure we see the
        # old NUMA topology

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            post = {'revertResize': {}}
            self.api.post_server_action(server['id'], post)

        server = self._wait_for_state_change(server, 'ACTIVE')

        # We don't have a filter call to check, but we can check that the
        # request spec changes were reverted
        self._inspect_request_spec(server, cell_count=1)

    def test_resize_vcpu_to_pcpu(self):
        """Create an unpinned instance and resize it to a flavor with pinning.

        This should pass and result in a guest NUMA topology with pinned CPUs.
        """

        self.flags(cpu_dedicated_set='0-3', cpu_shared_set='4-7',
                   group='compute')
        self.flags(vcpu_pin_set=None)

        # Start services
        for hostname in ('test_compute0', 'test_compute1'):
            self.start_compute(hostname=hostname)

        # Create server
        flavor_a_id = self._create_flavor(extra_spec={})
        server = self._create_server(flavor_id=flavor_a_id)

        original_host = server['OS-EXT-SRV-ATTR:host']

        for host, compute_rp_uuid in self.compute_rp_uuids.items():
            if host == original_host:  # the host with the instance
                expected_usage = {'VCPU': 2, 'PCPU': 0, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}
            else:  # the other host
                expected_usage = {'VCPU': 0, 'PCPU': 0, 'DISK_GB': 0,
                                  'MEMORY_MB': 0}

            compute_usage = self.placement.get(
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
            if host == original_host:
                # the host that had the instance should still have allocations
                # since the resize hasn't been confirmed
                expected_usage = {'VCPU': 2, 'PCPU': 0, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}
            else:
                # the other host should have the new allocations replete with
                # PCPUs
                expected_usage = {'VCPU': 0, 'PCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}

            compute_usage = self.placement.get(
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
            if host == original_host:
                # the host that had the instance should no longer have
                # alocations since the resize has been confirmed
                expected_usage = {'VCPU': 0, 'PCPU': 0, 'DISK_GB': 0,
                                  'MEMORY_MB': 0}
            else:
                # the other host should still have the new allocations replete
                # with PCPUs
                expected_usage = {'VCPU': 0, 'PCPU': 2, 'DISK_GB': 20,
                                  'MEMORY_MB': 2048}

            compute_usage = self.placement.get(
                '/resource_providers/%s/usages' % compute_rp_uuid).body[
                    'usages']
            self.assertEqual(expected_usage, compute_usage)

    def test_resize_bug_1879878(self):
        """Resize a instance with a NUMA topology when confirm takes time.

        Bug 1879878 describes a race between the periodic tasks of the resource
        tracker and the libvirt virt driver. The virt driver expects to be the
        one doing the unpinning of instances, however, the resource tracker is
        stepping on the virt driver's toes.
        """
        self.flags(
            cpu_dedicated_set='0-3', cpu_shared_set='4-7', group='compute')
        self.flags(vcpu_pin_set=None)

        orig_confirm = nova.virt.libvirt.driver.LibvirtDriver.confirm_migration

        def fake_confirm_migration(*args, **kwargs):
            # run periodics before finally running the confirm_resize routine,
            # simulating a race between the resource tracker and the virt
            # driver
            self._run_periodics()

            # then inspect the ComputeNode objects for our two hosts
            src_numa_topology = objects.NUMATopology.obj_from_db_obj(
                objects.ComputeNode.get_by_nodename(
                    self.ctxt, src_host,
                ).numa_topology,
            )
            dst_numa_topology = objects.NUMATopology.obj_from_db_obj(
                objects.ComputeNode.get_by_nodename(
                    self.ctxt, dst_host,
                ).numa_topology,
            )
            self.assertEqual(2, len(src_numa_topology.cells[0].pinned_cpus))
            self.assertEqual(2, len(dst_numa_topology.cells[0].pinned_cpus))

            # before continuing with the actualy confirm process
            return orig_confirm(*args, **kwargs)

        self.stub_out(
            'nova.virt.libvirt.driver.LibvirtDriver.confirm_migration',
            fake_confirm_migration,
        )

        # start services
        self.start_compute(hostname='test_compute0')
        self.start_compute(hostname='test_compute1')

        # create server
        flavor_a_id = self._create_flavor(
            vcpu=2, extra_spec={'hw:cpu_policy': 'dedicated'})
        server = self._create_server(flavor_id=flavor_a_id)

        src_host = server['OS-EXT-SRV-ATTR:host']

        # we don't really care what the new flavor is, so long as the old
        # flavor is using pinning. We use a similar flavor for simplicity.
        flavor_b_id = self._create_flavor(
            vcpu=2, extra_spec={'hw:cpu_policy': 'dedicated'})

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # TODO(stephenfin): Replace with a helper
            post = {'resize': {'flavorRef': flavor_b_id}}
            self.api.post_server_action(server['id'], post)
            server = self._wait_for_state_change(server, 'VERIFY_RESIZE')

        dst_host = server['OS-EXT-SRV-ATTR:host']

        # Now confirm the resize

        post = {'confirmResize': None}
        self.api.post_server_action(server['id'], post)

        server = self._wait_for_state_change(server, 'ACTIVE')


class NUMAServerTestWithCountingQuotaFromPlacement(NUMAServersTest):

    def setUp(self):
        self.flags(count_usage_from_placement=True, group='quota')
        super(NUMAServersTest, self).setUp()


class ReshapeForPCPUsTest(NUMAServersTestBase):

    api_major_version = 'v2.1'

    # TODO(stephenfin): We're using this because we want to be able to force
    # the host during scheduling. We should instead look at overriding policy
    ADMIN_API = True

    def test_vcpu_to_pcpu_reshape(self):
        """Verify that VCPU to PCPU reshape works.

        This rather complex test checks that everything is wired up properly
        by the reshape operation.

        1) create two pinned servers with an old tree where the compute
           provider is reporting VCPUs and the servers are consuming the same
        2) start a migration of one of these servers to another host but don't
           confirm it
        3) trigger a reshape
        4) check that the allocations of both the servers and the migration
           record on the host are updated
        5) create another server now against the new tree
        """

        # we need to use the 'host' parameter when creating servers
        self.api.microversion = '2.74'

        # we need to configure the legacy 'vcpu_pin_set' config option, rather
        # than the new ones, to ensure the reshape doesn't happen yet

        self.flags(cpu_dedicated_set=None, cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set='0-7')

        # start services
        self.start_compute(hostname='test_compute0')
        self.start_compute(hostname='test_compute1')

        # ensure there is no PCPU inventory being reported

        for host, compute_rp_uuid in self.compute_rp_uuids.items():
            compute_inventory = self.placement.get(
                '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                    'inventories']
            self.assertEqual(8, compute_inventory['VCPU']['total'])
            self.assertNotIn('PCPU', compute_inventory)

        # now we boot two servers with pinning, which should boot even without
        # PCPUs since we're not doing the translation yet

        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        server_req = self._build_server(flavor_id=flavor_id)
        server_req['host'] = 'test_compute0'
        server_req['networks'] = 'auto'

        created_server1 = self.api.post_server({'server': server_req})
        server1 = self._wait_for_state_change(created_server1, 'ACTIVE')

        created_server2 = self.api.post_server({'server': server_req})
        server2 = self._wait_for_state_change(created_server2, 'ACTIVE')

        # sanity check usages

        compute_rp_uuid = self.compute_rp_uuids['test_compute0']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(4, compute_usages['VCPU'])

        compute_rp_uuid = self.compute_rp_uuids['test_compute1']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(0, compute_usages['VCPU'])

        # now initiate the migration process for one of the servers

        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            post = {'migrate': None}
            self.api.post_server_action(server2['id'], post)

        server2 = self._wait_for_state_change(server2, 'VERIFY_RESIZE')

        # verify that the inventory, usages and allocation are correct before
        # the reshape. Note that the value of 8 VCPUs is derived from
        # fakelibvirt.HostInfo with our overridden values

        # first, check 'test_compute0', which should have the allocations for
        # server1 (the one that hasn't been migrated) and for the migration
        # record of server2 (the one that has been migrated)

        compute_rp_uuid = self.compute_rp_uuids['test_compute0']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        self.assertEqual(8, compute_inventory['VCPU']['total'])
        self.assertNotIn('PCPU', compute_inventory)
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(4, compute_usages['VCPU'])
        self.assertNotIn('PCPU', compute_usages)

        allocations = self.placement.get(
            '/allocations/%s' % server1['id']).body['allocations']
        # the flavor has disk=10 and ephemeral=10
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2},
            allocations[compute_rp_uuid]['resources'])

        # then check 'test_compute1', which should have the allocations for
        # server2 (the one that has been migrated)

        compute_rp_uuid = self.compute_rp_uuids['test_compute1']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        self.assertEqual(8, compute_inventory['VCPU']['total'])
        self.assertNotIn('PCPU', compute_inventory)
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(2, compute_usages['VCPU'])
        self.assertNotIn('PCPU', compute_usages)

        allocations = self.placement.get(
            '/allocations/%s' % server2['id']).body['allocations']
        # the flavor has disk=10 and ephemeral=10
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2},
            allocations[compute_rp_uuid]['resources'])

        # set the new config options on the compute services and restart them,
        # meaning the compute services will now report PCPUs and reshape
        # existing inventory to use them

        self.flags(cpu_dedicated_set='0-7', group='compute')
        self.flags(vcpu_pin_set=None)

        computes = {}
        for host, compute in self.computes.items():
            computes[host] = self.restart_compute_service(compute)
        self.computes = computes

        # verify that the inventory, usages and allocation are correct after
        # the reshape

        # first, check 'test_compute0', which should have the allocations for
        # server1 (the one that hasn't been migrated) and for the migration
        # record of server2 (the one that has been migrated)

        compute_rp_uuid = self.compute_rp_uuids['test_compute0']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        self.assertEqual(8, compute_inventory['PCPU']['total'])
        self.assertNotIn('VCPU', compute_inventory)
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(4, compute_usages['PCPU'])
        self.assertNotIn('VCPU', compute_usages)

        allocations = self.placement.get(
            '/allocations/%s' % server1['id']).body['allocations']
        # the flavor has disk=10 and ephemeral=10
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'PCPU': 2},
            allocations[compute_rp_uuid]['resources'])

        # then check 'test_compute1', which should have the allocations for
        # server2 (the one that has been migrated)

        compute_rp_uuid = self.compute_rp_uuids['test_compute1']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        self.assertEqual(8, compute_inventory['PCPU']['total'])
        self.assertNotIn('VCPU', compute_inventory)
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(2, compute_usages['PCPU'])
        self.assertNotIn('VCPU', compute_usages)

        allocations = self.placement.get(
            '/allocations/%s' % server2['id']).body['allocations']
        # the flavor has disk=10 and ephemeral=10
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'PCPU': 2},
            allocations[compute_rp_uuid]['resources'])

        # now create one more instance with pinned instances against the
        # reshaped tree which should result in PCPU allocations

        created_server = self.api.post_server({'server': server_req})
        server3 = self._wait_for_state_change(created_server, 'ACTIVE')

        compute_rp_uuid = self.compute_rp_uuids['test_compute0']

        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
                'inventories']
        self.assertEqual(8, compute_inventory['PCPU']['total'])
        self.assertNotIn('VCPU', compute_inventory)
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
                'usages']
        self.assertEqual(6, compute_usages['PCPU'])
        self.assertNotIn('VCPU', compute_usages)

        # check the allocations for this server specifically

        allocations = self.placement.get(
            '/allocations/%s' % server3['id']).body[
                'allocations']
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'PCPU': 2},
            allocations[compute_rp_uuid]['resources'])

        self._delete_server(server1)
        self._delete_server(server2)
        self._delete_server(server3)


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

    def _test_create_server_with_networks(self, flavor_id, networks,
                                          end_status='ACTIVE'):
        self.start_compute()

        # Create server
        return self._create_server(
            flavor_id=flavor_id,
            networks=networks,
            expected_state=end_status)

    def test_create_server_with_single_physnet(self):
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        self._test_create_server_with_networks(flavor_id, networks)

        self.assertTrue(self.mock_filter.called)

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

        self._test_create_server_with_networks(flavor_id, networks)

        self.assertTrue(self.mock_filter.called)

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

        self._test_create_server_with_networks(flavor_id, networks,
                                               end_status='ERROR')

        self.assertTrue(self.mock_filter.called)

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

        self._test_create_server_with_networks(flavor_id, networks)

        self.assertTrue(self.mock_filter.called)

    # FIXME(sean-k-mooney): The logic of this test is incorrect.
    # The test was written to assert that we failed to rebuild
    # because the NUMA constraints were violated due to the attachment
    # of an interface from a second host NUMA node to an instance with
    # a NUMA topology of 1 that is affined to a different NUMA node.
    # Nova should reject the interface attachment if the NUMA constraints
    # would be violated and it should fail at that point not when the
    # instance is rebuilt. This is a latent bug which will be addressed
    # in a separate patch.
    @testtools.skip("bug 1855332")
    def test_attach_interface_with_network_affinity_violation(self):
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        server = self._test_create_server_with_networks(flavor_id, networks)

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
        self._wait_for_state_change(server, 'ACTIVE')

        # attach an interface from a **different** network
        post = {
            'interfaceAttachment': {
                'net_id': base.LibvirtNeutronFixture.network_2['id'],
            }
        }
        # FIXME(sean-k-mooney): This should raise an exception as this
        # interface attachment would violate the NUMA constraints.
        self.api.attach_interface(server['id'], post)
        post = {'rebuild': {
            'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
        }}
        # NOTE(sean-k-mooney): the rest of the test is incorrect but
        # is left to show the currently broken behavior.

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

        # Start services
        self.start_compute(hostname='test_compute0')
        self.start_compute(hostname='test_compute1')

        # Create server
        extra_spec = {'hw:numa_nodes': '1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        networks = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
        ]

        server = self._create_server(
            flavor_id=flavor_id,
            networks=networks)

        original_host = server['OS-EXT-SRV-ATTR:host']

        # We reset mock_filter because we want to ensure it's called as part of
        # the *migration*
        self.mock_filter.reset_mock()
        self.assertEqual(0, len(self.mock_filter.call_args_list))

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            self.admin_api.post_server_action(server['id'], {'migrate': None})

        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')

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


class NUMAServersRebuildTests(NUMAServersTestBase):

    def setUp(self):
        super().setUp()
        images = self.api.get_images()
        # save references to first two images for server create and rebuild
        self.image_ref_0 = images[0]['id']
        self.image_ref_1 = images[1]['id']

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

    def _create_active_server(self, server_args=None):
        basic_server = {
            'flavorRef': 1,
            'name': 'numa_server',
            'networks': [{
                'uuid': nova_fixtures.NeutronFixture.network_1['id']
            }],
            'imageRef': self.image_ref_0
        }
        if server_args:
            basic_server.update(server_args)
        server = self.api.post_server({'server': basic_server})
        return self._wait_for_state_change(server, 'ACTIVE')

    def test_rebuild_server_with_numa(self):
        """Create a NUMA instance and ensure it can be rebuilt.
        """

        # Create a flavor consuming 2 pinned cpus with an implicit
        # numa topology of 1 virtual numa node.
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        # Create a host with 4 physical cpus to allow rebuild leveraging
        # the free space to ensure the numa topology filter does not
        # eliminate the host.
        host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=4, kB_mem=15740000)
        self.start_compute(host_info=host_info)

        server = self._create_active_server(
            server_args={"flavorRef": flavor_id})

        # this should succeed as the NUMA topology has not changed
        # and we have enough resources on the host. We rebuild with
        # a different image to force the rebuild to query the scheduler
        # to validate the host.
        self._rebuild_server(server, self.image_ref_1)

    def test_rebuild_server_with_numa_inplace_fails(self):
        """Create a NUMA instance and ensure in place rebuild fails.
        """

        # Create a flavor consuming 2 pinned cpus with an implicit
        # numa topology of 1 virtual numa node.
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        # cpu_cores is set to 2 to ensure that we have enough space
        # to boot the vm but not enough space to rebuild
        # by doubling the resource use during scheduling.
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=1, cpu_cores=2, kB_mem=15740000)
        self.start_compute(host_info=host_info)

        server = self._create_active_server(
            server_args={"flavorRef": flavor_id})

        # This should succeed as the numa constraints do not change.
        self._rebuild_server(server, self.image_ref_1)

    def test_rebuild_server_with_different_numa_topology_fails(self):
        """Create a NUMA instance and ensure inplace rebuild fails.
        """

        # Create a flavor consuming 2 pinned cpus with an implicit
        # numa topology of 1 virtual numa node.
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=1, cpu_cores=4, kB_mem=15740000)
        self.start_compute(host_info=host_info)

        server = self._create_active_server(
            server_args={"flavorRef": flavor_id})

        # The original vm had an implicit numa topology of 1 virtual numa node
        # so we alter the requested numa topology in image_ref_1 to request
        # 2 virtual numa nodes.
        ctx = nova_context.get_admin_context()
        image_meta = {'properties': {'hw_numa_nodes': 2}}
        self.glance.update(ctx, self.image_ref_1, image_meta)

        # NOTE(sean-k-mooney): this should fail because rebuild uses noop
        # claims therefore it is not allowed for the NUMA topology or resource
        # usage to change during a rebuild.
        ex = self.assertRaises(
            client.OpenStackApiException, self._rebuild_server,
            server, self.image_ref_1)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn("An instance's NUMA topology cannot be changed",
                      six.text_type(ex))
