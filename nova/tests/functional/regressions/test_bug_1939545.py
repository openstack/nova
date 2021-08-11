# Copyright 2021, Red Hat, Inc. All Rights Reserved.
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

from oslo_serialization import jsonutils

from nova import context
from nova import objects
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fake_os_brick_connector
from nova.tests.unit.virt.libvirt import fakelibvirt


class TestLiveMigrateUpdateDevicePath(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 1939545

    Assert the behaviour of the libvirt driver during pre_live_migration with
    instances that have block based volumes attached.

    Bug #1939545 covering the case where the returned path from os-brick
    isn't being saved into the connection_info of the associated bdm in Nova.
    """

    api_major_version = 'v2.1'
    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.connector',
            fake_os_brick_connector))

        # TODO(lyarwood): Move into base.ServersTestBase to allow live
        # migrations to pass without changes by the test classes.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.tests.unit.virt.libvirt.fakelibvirt.Domain.migrateToURI3',
            self._migrate_stub))

        self.start_compute(
            hostname='src',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.start_compute(
            hostname='dest',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))

    def _migrate_stub(self, domain, destination, params, flags):
        dest = self.computes['dest']
        dest.driver._host.get_connection().createXML(
            params['destination_xml'],
            'fake-createXML-doesnt-care-about-flags')
        source = self.computes['src']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dom.complete_job()

    # TODO(lyarwood): Move this into the os-brick fixture and repeat for all
    # provided connectors at runtime.
    @mock.patch(
        'os_brick.initiator.connectors.iscsi.ISCSIConnector.connect_volume')
    @mock.patch(
        'os_brick.initiator.connectors.iscsi.ISCSIConnector.disconnect_volume')
    def test_live_migrate_update_device_path(
        self, mock_disconnect_volume, mock_connect_volume
    ):
        self.server = self._create_server(host='src', networks='none')
        volume_id = self.cinder.ISCSI_BACKED_VOL

        # TODO(lyarwood): As above, move this into the os-brick fixture.
        mock_connect_volume.return_value = {'path': '/dev/sda'}

        self.api.post_server_volume(
            self.server['id'], {'volumeAttachment': {'volumeId': volume_id}})

        # Get the volume bdm and assert that the connection_info is set with
        # device_path from the volume driver.
        ctxt = context.get_admin_context()
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            ctxt, volume_id, self.server['id'])
        connection_info = jsonutils.loads(bdm.connection_info)
        self.assertIn('device_path', connection_info.get('data'))

        # Live migrate the instance to another host
        self._live_migrate(self.server)

        # Again get the volume bdm and assert that the saved connection_info
        # contains device_path.
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            ctxt, volume_id, self.server['id'])
        connection_info = jsonutils.loads(bdm.connection_info)
        self.assertIn('device_path', connection_info.get('data'))
