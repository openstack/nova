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

import fixtures
import mock

from nova.tests.functional.api import client
from nova.tests.functional.test_servers import ServersTestBase
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt


class RealTimeServersTest(ServersTestBase):

    def setUp(self):
        super(RealTimeServersTest, self).setUp()

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
        self.flags(sysinfo_serial='none', group='libvirt')

    def _setup_compute_service(self):
        self.flags(compute_driver='libvirt.LibvirtDriver')

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

    def test_success(self):
        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                version=fakelibvirt.FAKE_LIBVIRT_VERSION,
                                hv_version=fakelibvirt.FAKE_QEMU_VERSION,
                                host_info=host_info)
        with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                        return_value=fake_connection):
            self.compute = self.start_service('compute', host='test_compute0')

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
