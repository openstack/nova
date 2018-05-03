# Copyright 2016 IBM Corp.
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

import time

import fixtures
import mock

import nova
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import cast_as_call
from nova.tests.unit import policy_fixture
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import guest as libvirt_guest


class TestSerialConsoleLiveMigrate(test.TestCase):
    REQUIRES_LOCKING = True

    def setUp(self):
        super(TestSerialConsoleLiveMigrate, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
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

        self.admin_api = api_fixture.admin_api
        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)
        nova.tests.unit.fake_network.set_stub_network_methods(self)

        self.flags(compute_driver='libvirt.LibvirtDriver')
        self.flags(enabled=True, group="serial_console")
        self.flags(enabled=False, group="vnc")
        self.flags(enabled=False, group="spice")
        self.flags(use_usb_tablet=False, group="libvirt")

        self.start_service('conductor')
        self.start_service('scheduler')
        self.compute = self.start_service('compute', host='test_compute1')
        self.consoleauth = self.start_service('consoleauth')

        self.useFixture(cast_as_call.CastAsCall(self))
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    @mock.patch('nova.virt.libvirt.LibvirtDriver.get_volume_connector')
    @mock.patch('nova.virt.libvirt.guest.Guest.get_job_info')
    @mock.patch.object(fakelibvirt.Domain, 'migrateToURI3')
    @mock.patch('nova.virt.libvirt.host.Host.get_connection')
    @mock.patch('nova.virt.disk.api.get_disk_size', return_value=1024)
    @mock.patch('os.path.getsize', return_value=1024)
    @mock.patch('nova.conductor.tasks.live_migrate.LiveMigrationTask.'
                '_check_destination_is_not_source', return_value=False)
    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image')
    def test_serial_console_live_migrate(self, mock_create_image,
                                         mock_conductor_source_check,
                                         mock_path_get_size,
                                         mock_get_disk_size,
                                         mock_host_get_connection,
                                         mock_migrate_to_uri,
                                         mock_get_job_info,
                                         mock_get_volume_connector):
        """Regression test for bug #1595962.

        If the graphical consoles VNC and SPICE are disabled, the
        live-migration of an instance will result in an ERROR state.
        VNC and SPICE are usually disabled on IBM z systems platforms
        where graphical consoles are not available. The serial console
        is then enabled and VNC + SPICE are disabled.

        The error will be raised at
            https://github.com/openstack/nova/blob/
            4f33047d07f5a11b208c344fe206aba01cd8e6fe/
            nova/virt/libvirt/driver.py#L5842-L5852
        """
        mock_get_job_info.return_value = libvirt_guest.JobInfo(
                    type=fakelibvirt.VIR_DOMAIN_JOB_COMPLETED)
        fake_connection = fakelibvirt.Connection('qemu:///system',
                                version=fakelibvirt.FAKE_LIBVIRT_VERSION,
                                hv_version=fakelibvirt.FAKE_QEMU_VERSION)
        mock_host_get_connection.return_value = fake_connection

        server_attr = dict(name='server1',
                           imageRef=self.image_id,
                           flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server_attr})
        server_id = server['id']
        self.wait_till_active_or_timeout(server_id)

        post = {"os-migrateLive": {
                    "block_migration": False,
                    "disk_over_commit": False,
                    "host": "test_compute1"
                }}

        try:
            # This should succeed
            self.admin_api.post_server_action(server_id, post)
            self.wait_till_active_or_timeout(server_id)
        except Exception as ex:
            self.fail(ex.response.content)

    def wait_till_active_or_timeout(self, server_id):
        timeout = 0.0
        server = self.api.get_server(server_id)
        while server['status'] != "ACTIVE" and timeout < 10.0:
            time.sleep(.1)
            timeout += .1
            server = self.api.get_server(server_id)
        if server['status'] != "ACTIVE":
            self.fail("The server is not active after the timeout.")
