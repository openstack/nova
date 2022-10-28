# Copyright (C) 2023 Red Hat, Inc
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
from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils import units

from nova.objects import fields
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class Bug1995153RegressionTest(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter', 'PciPassthroughFilter']

    ALIAS_NAME = 'a1'
    PCI_DEVICE_SPEC = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
        }
    )]
    # we set the numa_affinity policy to required to ensure strict affinity
    # between pci devices and the guest cpu and memory will be enforced.
    PCI_ALIAS = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
            'name': ALIAS_NAME,
            'device_type': fields.PciDeviceType.STANDARD,
            'numa_policy': fields.PCINUMAAffinityPolicy.REQUIRED,
        }
    )]

    def setUp(self):
        super(Bug1995153RegressionTest, self).setUp()
        self.flags(
            device_spec=self.PCI_DEVICE_SPEC,
            alias=self.PCI_ALIAS,
            group='pci'
        )
        host_manager = self.scheduler.manager.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        self.mock_filter = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.filters.pci_passthrough_filter'
            '.PciPassthroughFilter.host_passes',
            side_effect=host_pass_mock)).mock

    def test_socket_policy_bug_1995153(self):
        """The numa_usage_from_instance_numa() method in hardware.py saves the
        host NUMAToplogy object with NUMACells that have no `socket` set. This
        was an omission in the original implementation of the `socket` PCI NUMA
        affinity policy. The consequence is that any code path that calls into
        numa_usage_from_instance_numa() will clobber the host NUMA topology in
        the database with a socket-less version. Booting an instance with NUMA
        toplogy will do that, for example. If then a second instance is booted
        with the `socket` PCI NUMA affinity policy, it will read the
        socket-less host NUMATopology from the database, and error out with a
        NotImplementedError. This is bug 1995153.
        """
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
            kB_mem=(16 * units.Gi) // units.Ki)
        self.flags(cpu_dedicated_set='0-3', group='compute')
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)

        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': 'socket'
        }
        # Boot a first instance with a guest NUMA topology to run the buggy
        # code in numa_usage_from_instance_numa() and save the socket-less host
        # NUMATopology to the database.
        self._create_server(
            flavor_id=self._create_flavor(
                extra_spec={'hw:cpu_policy': 'dedicated'}))

        # FIXME(artom) Attempt to boot an instance with the `socket` PCI NUMA
        # affinity policy and observe the fireworks.
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id,
                                     expected_state='ERROR')
        self.assertIn('fault', server)
        self.assertIn('NotImplementedError', server['fault']['message'])
        self.assertTrue(self.mock_filter.called)
