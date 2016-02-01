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

import fixtures
from oslo_config import cfg
from oslo_log import log as logging

from nova import test
from nova.tests.functional.test_servers import ServersTestBase
from nova.tests.unit import fake_network
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class NumaHostInfo(fakelibvirt.HostInfo):
    def __init__(self, **kwargs):
        super(NumaHostInfo, self).__init__(**kwargs)
        self.numa_mempages_list = []

    def get_numa_topology(self):
        if self.numa_topology:
            return self.numa_topology

        topology = self._gen_numa_topology(self.cpu_nodes, self.cpu_sockets,
                                           self.cpu_cores, self.cpu_threads,
                                           self.kB_mem)
        self.numa_topology = topology

        # update number of active cpus
        cpu_count = len(topology.cells) * len(topology.cells[0].cpus)
        self.cpus = cpu_count - len(self.disabled_cpus_list)
        return topology

    def set_custom_numa_toplogy(self, topology):
        self.numa_topology = topology


class NUMAServersTest(ServersTestBase):

    def setUp(self):
        super(NUMAServersTest, self).setUp()

        # Replace libvirt with fakelibvirt
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
        pass

    def _setup_scheduler_service(self):
        self.flags(compute_driver='nova.virt.libvirt.LibvirtDriver')

        self.flags(scheduler_driver='filter_scheduler')
        self.flags(scheduler_default_filters=CONF.scheduler_default_filters
                   + ['NUMATopologyFilter'])
        return self.start_service('scheduler')

    def _run_build_test(self, flavor_id, filter_mock, end_status='ACTIVE'):

        self.compute = self.start_service('compute', host='test_compute0')
        fake_network.set_stub_network_methods(self)

        # Create server
        good_server = self._build_server(flavor_id)

        post = {'server': good_server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s" % created_server)
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
        self._delete_server(created_server_id)

    def _get_topology_filter_spy(self):
        host_manager = self.scheduler.manager.driver.host_manager
        numa_filter_class = host_manager.filter_cls_map['NUMATopologyFilter']
        host_pass_mock = mock.Mock(wraps=numa_filter_class().host_passes)
        return host_pass_mock

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_numa_topology(self, img_mock):

        host_info = NumaHostInfo(cpu_nodes=2, cpu_sockets=1, cpu_cores=2,
                                 cpu_threads=2, kB_mem=15740000)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                                 version=1002007,
                                                 hv_version=2001000,
                                                 host_info=host_info)

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

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_numa_fails(self, img_mock):

        host_info = NumaHostInfo(cpu_nodes=1, cpu_sockets=1, cpu_cores=2,
                                 kB_mem=15740000)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                                 version=1002007,
                                                 host_info=host_info)

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
