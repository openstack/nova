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

from nova.tests.functional.api import client
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


class RealTimeServersTest(ServersTestBase):

    def setUp(self):
        super(RealTimeServersTest, self).setUp()

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
        self.flags(compute_driver='nova.virt.libvirt.LibvirtDriver')

    def test_no_dedicated_cpu(self):
        flavor = self._create_flavor(extra_spec={'hw:cpu_realtime': 'yes'})
        server = self._build_server(flavor)

        # Cannot set realtime policy in a non dedicated cpu pinning policy
        self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server, {'server': server})

    def test_no_realtime_mask(self):
        flavor = self._create_flavor(extra_spec={
            'hw:cpu_realtime': 'yes', 'hw:cpu_policy': 'dedicated'})
        server = self._build_server(flavor)

        # Cannot set realtime policy if not vcpus mask defined
        self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server, {'server': server})

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_invalid_libvirt_version(self, img_mock):
        host_info = NumaHostInfo(cpu_nodes=2, cpu_sockets=1, cpu_cores=2,
                                 cpu_threads=2, kB_mem=15740000)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                                 version=1002007,
                                                 hv_version=2001000,
                                                 host_info=host_info)
        with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                        return_value=fake_connection):
            self.compute = self.start_service('compute', host='test_compute0')
            fake_network.set_stub_network_methods(self)

            flavor = self._create_flavor(extra_spec={
                'hw:cpu_realtime': 'yes', 'hw:cpu_policy': 'dedicated',
                'hw:cpu_realtime_mask': '^1'})
            server = self._build_server(flavor)
            created = self.api.post_server({'server': server})

            instance = self.api.get_server(created['id'])
            instance = self._wait_for_state_change(instance, 'BUILD')

            # Realtime policy not supported by hypervisor
            self.assertEqual('ERROR', instance['status'])
            self._delete_server(instance['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_success(self, img_mock):
        host_info = NumaHostInfo(cpu_nodes=2, cpu_sockets=1, cpu_cores=2,
                                 cpu_threads=2, kB_mem=15740000)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                                 version=1002013,
                                                 hv_version=2001000,
                                                 host_info=host_info)
        with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                        return_value=fake_connection):
            self.compute = self.start_service('compute', host='test_compute0')
            fake_network.set_stub_network_methods(self)

            flavor = self._create_flavor(extra_spec={
                'hw:cpu_realtime': 'yes',
                'hw:cpu_policy': 'dedicated',
                'hw:cpu_realtime_mask': '^1'})
            server = self._build_server(flavor)
            created = self.api.post_server({'server': server})

            instance = self.api.get_server(created['id'])
            instance = self._wait_for_state_change(instance, 'BUILD')

            self.assertEqual('ACTIVE', instance['status'])
            self._delete_server(instance['id'])
