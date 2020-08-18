# Copyright (C) 2018 Red Hat, Inc
# All Rights Reserved.
#
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

import copy
import io

import fixtures
import mock
from oslo_utils import units

from nova import conf
from nova.objects import fields as obj_fields
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = conf.CONF


class ServersTestBase(integrated_helpers._IntegratedTestBase):
    """A libvirt-specific variant of the integrated test base."""

    ADDITIONAL_FILTERS = []

    def setUp(self):
        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)

        self.computes = {}
        self.compute_rp_uuids = {}

        super(ServersTestBase, self).setUp()

        # Replace libvirt with fakelibvirt
        self.useFixture(fake_imagebackend.ImageBackendFixture())
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

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._create_image',
            return_value=(False, False)))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_local_gb_info',
            return_value={'total': 128, 'used': 44, 'free': 84}))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.libvirt_utils.is_valid_hostname',
            return_value=True))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.libvirt_utils.file_open',
            side_effect=lambda *a, **k: io.BytesIO(b'')))
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.utils.supports_direct_io',
            return_value=True))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host.get_online_cpus',
            return_value=set(range(16))))

        # Mock the 'get_connection' function, as we're going to need to provide
        # custom capabilities for each test
        _p = mock.patch('nova.virt.libvirt.host.Host.get_connection')
        self.mock_conn = _p.start()
        self.addCleanup(_p.stop)

        # Mock the 'get_arch' function as we may need to provide different host
        # architectures during some tests. We default to x86_64
        _a = mock.patch('nova.virt.libvirt.utils.get_arch')
        self.mock_arch = _a.start()
        self.mock_arch.return_value = obj_fields.Architecture.X86_64
        self.addCleanup(_a.stop)

    def _setup_compute_service(self):
        # NOTE(stephenfin): We don't start the compute service here as we wish
        # to configure the host capabilities first. We instead start the
        # service in the test
        self.flags(compute_driver='libvirt.LibvirtDriver')

    def _setup_scheduler_service(self):
        enabled_filters = CONF.filter_scheduler.enabled_filters
        enabled_filters += self.ADDITIONAL_FILTERS

        self.flags(driver='filter_scheduler', group='scheduler')
        self.flags(enabled_filters=enabled_filters, group='filter_scheduler')

        return self.start_service('scheduler')

    def _get_connection(
        self, host_info=None, pci_info=None, mdev_info=None,
        libvirt_version=None, qemu_version=None, hostname=None,
    ):
        if not host_info:
            host_info = fakelibvirt.HostInfo(
                cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
                kB_mem=(16 * units.Gi) // units.Ki,
            )

        # sanity check
        self.assertGreater(16, host_info.cpus,
            "Host.get_online_cpus is only accounting for 16 CPUs but you're "
            "requesting %d; change the mock or your test" % host_info.cpus)

        libvirt_version = libvirt_version or fakelibvirt.FAKE_LIBVIRT_VERSION
        qemu_version = qemu_version or fakelibvirt.FAKE_QEMU_VERSION

        fake_connection = fakelibvirt.Connection(
            'qemu:///system',
            version=libvirt_version,
            hv_version=qemu_version,
            host_info=host_info,
            pci_info=pci_info,
            mdev_info=mdev_info,
            hostname=hostname)
        return fake_connection

    def start_compute(
        self, hostname='compute1', host_info=None, pci_info=None,
        mdev_info=None, libvirt_version=None, qemu_version=None,
    ):
        """Start a compute service.

        The started service will be saved in self.computes, keyed by hostname.

        :param hostname: A hostname.
        :param host_info: A fakelibvirt.HostInfo object for the host. Defaults
            to a HostInfo with 2 NUMA nodes, 2 cores per node, 2 threads per
            core, and 16GB of RAM.
        :returns: The hostname of the created service, which can be used to
            lookup the created service and UUID of the assocaited resource
            provider.
        """

        def _start_compute(hostname, host_info):
            fake_connection = self._get_connection(
                host_info, pci_info, mdev_info, libvirt_version, qemu_version,
                hostname,
            )
            # This is fun. Firstly we need to do a global'ish mock so we can
            # actually start the service.
            with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                            return_value=fake_connection):
                compute = self.start_service('compute', host=hostname)
                # Once that's done, we need to tweak the compute "service" to
                # make sure it returns unique objects. We do this inside the
                # mock context to avoid a small window between the end of the
                # context and the tweaking where get_connection would revert to
                # being an autospec mock.
                compute.driver._host.get_connection = lambda: fake_connection
            return compute

        # ensure we haven't already registered services with these hostnames
        self.assertNotIn(hostname, self.computes)
        self.assertNotIn(hostname, self.compute_rp_uuids)

        self.computes[hostname] = _start_compute(hostname, host_info)

        self.compute_rp_uuids[hostname] = self.placement.get(
            '/resource_providers?name=%s' % hostname).body[
            'resource_providers'][0]['uuid']

        return hostname


class LibvirtNeutronFixture(nova_fixtures.NeutronFixture):
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
    network_4 = network_1.copy()
    network_4.update({
        'id': '1b70879f-fd00-411e-8ea9-143e7820e61d',
        'name': 'private-network',
        'shared': False,
        'provider:physical_network': 'physnet4',
        "provider:network_type": "vlan",
        'provider:segmentation_id': 42,
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
    subnet_4 = nova_fixtures.NeutronFixture.subnet_1.copy()
    subnet_4.update({
        'id': '7cb343ec-6637-494c-89a1-8890eab7788e',
        'name': 'physical-subnet-bar',
        'network_id': network_4['id'],
    })
    network_1['subnets'] = [subnet_1]
    network_2['subnets'] = [subnet_2]
    network_3['subnets'] = [subnet_3]
    network_4['subnets'] = [subnet_4]

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
        'binding:vif_details': {},
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
        'binding:vif_details': {},
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
        'binding:vif_details': {},
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
        'binding:vif_details': {},
        'binding:vif_type': 'ovs',
        'binding:vnic_type': 'normal',
    }
    network_4_port_1 = {
        'id': 'b4cd0b93-2ac8-40a7-9fa4-2cd680ccdf3e',
        'network_id': network_4['id'],
        'status': 'ACTIVE',
        'mac_address': 'b5:bc:2e:e7:51:ee',
        'fixed_ips': [
            {
                'ip_address': '192.168.4.6',
                'subnet_id': subnet_4['id']
            }
        ],
        'binding:vif_type': 'hw_veb',
        'binding:vif_details': {'vlan': 42},
        'binding:vnic_type': 'direct',
    }

    def __init__(self, test):
        super(LibvirtNeutronFixture, self).__init__(test)
        self._networks = {
            self.network_1['id']: self.network_1,
            self.network_2['id']: self.network_2,
            self.network_3['id']: self.network_3,
            self.network_4['id']: self.network_4,
        }
        self._net1_ports = [self.network_1_port_2, self.network_1_port_3]

    def create_port(self, body=None):
        network_id = body['port']['network_id']
        assert network_id in self._networks, ('Network %s not in fixture' %
                                              network_id)

        if network_id == self.network_1['id']:
            port = self._net1_ports.pop(0)
        elif network_id == self.network_2['id']:
            port = self.network_2_port_1
        elif network_id == self.network_3['id']:
            port = self.network_3_port_1
        elif network_id == self.network_4['id']:
            port = self.network_4_port_1

        # this copy is here to avoid modifying class variables like
        # network_2_port_1 below at the update call
        port = copy.deepcopy(port)
        port.update(body['port'])

        # the tenant ID is normally extracted from credentials in the request
        # and is not present in the body
        if 'tenant_id' not in port:
            port['tenant_id'] = nova_fixtures.NeutronFixture.tenant_id

        # similarly, these attributes are set by neutron itself
        port['admin_state_up'] = True

        self._ports[port['id']] = port
        # this copy is here as nova sometimes modifies the returned port
        # locally and we want to avoid that nova modifies the fixture internals
        return {'port': copy.deepcopy(port)}
