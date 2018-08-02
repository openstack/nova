# Copyright (C) 2016 Red Hat, Inc
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

import fixtures
import mock
from oslo_config import cfg
from oslo_log import log as logging

from nova.objects import fields
from nova import test
from nova.tests.functional.test_servers import ServersTestBase
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SRIOVServersTest(ServersTestBase):
    vfs_alias_name = 'vfs'
    pfs_alias_name = 'pfs'

    def setUp(self):

        white_list = ['{"vendor_id":"8086","product_id":"1528"}',
                      '{"vendor_id":"8086","product_id":"1515"}']
        self.flags(passthrough_whitelist=white_list, group='pci')

        # PFs will be removed from pools, unless these has been specifically
        # requested. This is especially needed in cases where PFs and VFs have
        # the same vendor/product id
        pci_alias = ['{"vendor_id":"8086", "product_id":"1528", "name":"%s",'
                     ' "device_type":"%s"}' % (self.pfs_alias_name,
                                               fields.PciDeviceType.SRIOV_PF),
                     '{"vendor_id":"8086", "product_id":"1515", "name":"%s"}' %
                     self.vfs_alias_name]
        self.flags(alias=pci_alias, group='pci')
        super(SRIOVServersTest, self).setUp()

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

        self.compute_started = False

    def _setup_compute_service(self):
        pass

    def _setup_scheduler_service(self):
        self.flags(compute_driver='libvirt.LibvirtDriver')

        self.flags(driver='filter_scheduler', group='scheduler')
        self.flags(enabled_filters=CONF.filter_scheduler.enabled_filters
                   + ['NUMATopologyFilter', 'PciPassthroughFilter'],
                   group='filter_scheduler')
        return self.start_service('scheduler')

    def _get_connection(self, host_info, pci_info):
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                version=fakelibvirt.FAKE_LIBVIRT_VERSION,
                                hv_version=fakelibvirt.FAKE_QEMU_VERSION,
                                host_info=host_info,
                                pci_info=pci_info)
        return fake_connection

    def _run_build_test(self, flavor_id, filter_mock, end_status='ACTIVE'):

        if not self.compute_started:
            self.compute = self.start_service('compute', host='test_compute0')
            self.compute_started = True

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

        # Validate that PciPassthroughFilter has been called
        self.assertTrue(filter_mock.called)

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual(end_status, found_server['status'])
        return created_server

    def _get_pci_passthrough_filter_spy(self):
        host_manager = self.scheduler.manager.driver.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        return host_pass_mock

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_VF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.vfs_alias_name}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            server = self._run_build_test(flavor_id, filter_mock)
        self._delete_server(server['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_PF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.pfs_alias_name}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            server = self._run_build_test(flavor_id, filter_mock)
        self._delete_server(server['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_PF_no_VF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo(num_pfs=1, num_vfs=4)
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.pfs_alias_name}
        extra_spec_vfs = {"pci_passthrough:alias": "%s:1" %
                          self.vfs_alias_name}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            pf_server = self._run_build_test(flavor_id, filter_mock)
            vf_server = self._run_build_test(flavor_id_vfs, filter_mock,
                                             end_status='ERROR')

        self._delete_server(pf_server['id'])
        self._delete_server(vf_server['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_VF_no_PF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo(num_pfs=1, num_vfs=4)
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.pfs_alias_name}
        extra_spec_vfs = {"pci_passthrough:alias": "%s:1" %
                          self.vfs_alias_name}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            vf_server = self._run_build_test(flavor_id_vfs, filter_mock)
            pf_server = self._run_build_test(flavor_id, filter_mock,
                                             end_status='ERROR')

        self._delete_server(pf_server['id'])
        self._delete_server(vf_server['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_pci_dev_and_numa(self, img_mock):
        """Verifies that an instance can be booted with cpu pinning and with an
           assigned pci device.
        """

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo(num_pfs=1, numa_node=1)
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.pfs_alias_name,
                      'hw:numa_nodes': '1',
                      'hw:cpu_policy': 'dedicated',
                      'hw:cpu_thread_policy': 'prefer'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                       filter_mock):
            pf_server = self._run_build_test(flavor_id, filter_mock)
        self._delete_server(pf_server['id'])

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_create_server_with_pci_dev_and_numa_fails(self, img_mock):
        """This test ensures that it is not possible to allocated CPU and
           memory resources from one NUMA node and a PCI device from another.
        """

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPciSRIOVDevicesInfo(num_pfs=1, numa_node=0)
        fake_connection = self._get_connection(host_info, pci_info)

        # Create a flavor
        extra_spec_vm = {'hw:cpu_policy': 'dedicated',
                         'hw:numa_node': '1'}
        extra_spec = {'pci_passthrough:alias': '%s:1' % self.pfs_alias_name,
                      'hw:numa_nodes': '1',
                      'hw:cpu_policy': 'dedicated',
                      'hw:cpu_thread_policy': 'prefer'}
        vm_flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec_vm)
        pf_flavor_id = self._create_flavor(extra_spec=extra_spec)
        host_pass_mock = self._get_pci_passthrough_filter_spy()
        with test.nested(
            mock.patch('nova.virt.libvirt.host.Host.get_connection',
                       return_value=fake_connection),
            mock.patch('nova.scheduler.filters'
                       '.pci_passthrough_filter.PciPassthroughFilter'
                       '.host_passes',
                       side_effect=host_pass_mock)) as (conn_mock,
                                                        filter_mock):
            vm_server = self._run_build_test(vm_flavor_id, filter_mock)
            pf_server = self._run_build_test(pf_flavor_id, filter_mock,
                                             end_status='ERROR')
        self._delete_server(vm_server['id'])
        self._delete_server(pf_server['id'])
