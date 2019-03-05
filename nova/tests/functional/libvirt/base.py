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

import fixtures
import mock

from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import test_servers as base
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt


class ServersTestBase(base.ServersTestBase):

    def setUp(self):
        super(ServersTestBase, self).setUp()

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
        self.useFixture(func_fixtures.PlacementFixture())

        # Mock the 'get_connection' function, as we're going to need to provide
        # custom capabilities for each test
        _p = mock.patch('nova.virt.libvirt.host.Host.get_connection')
        self.mock_conn = _p.start()
        self.addCleanup(_p.stop)

    def _setup_compute_service(self):
        # NOTE(stephenfin): We don't start the compute service here as we wish
        # to configure the host capabilities first. We instead start the
        # service in the test
        self.flags(compute_driver='libvirt.LibvirtDriver')

    def _get_connection(self, host_info, pci_info=None,
                        libvirt_version=fakelibvirt.FAKE_LIBVIRT_VERSION,
                        mdev_info=None):
        fake_connection = fakelibvirt.Connection(
            'qemu:///system',
            version=libvirt_version,
            hv_version=fakelibvirt.FAKE_QEMU_VERSION,
            host_info=host_info,
            pci_info=pci_info,
            mdev_info=mdev_info)
        return fake_connection
