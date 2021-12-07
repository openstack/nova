# Copyright 2021, Canonical, Inc. All Rights Reserved.
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

import mock

from nova import exception as nova_exceptions
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestRollbackWithHWOffloadedOVS(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug LP#1944619

    Assert the behaviour observed in bug LP#1944619 caused by the live
    migration cleanup code being used to cleanup pre-live migration failures.
    When SRIOV devices are in use on a VM, that will cause the source host to
    try to re-attach a VIF not actually de-attached causing a failure.

    The exception mocked in pre_live_migration reproduce an arbitrary error
    that might cause the pre-live migration process to fail and
    rollback_live_migration_at_source reproduce the device re-attach failure.
    """

    api_major_version = 'v2.1'
    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()

        self.start_compute(
            hostname='src',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.start_compute(
            hostname='dest',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))

        self.src = self.computes['src']
        self.dest = self.computes['dest']

    def test_rollback_pre_live_migration(self):
        self.server = self._create_server(host='src', networks='none')

        lib_path = "nova.virt.libvirt.driver.LibvirtDriver"
        funtion_path = "pre_live_migration"
        mock_lib_path_prelive = "%s.%s" % (lib_path, funtion_path)
        with mock.patch(mock_lib_path_prelive,
                        side_effect=nova_exceptions.DestinationDiskExists(
                            path='/var/non/existent')) as mlpp:
            funtion_path = "rollback_live_migration_at_source"
            mock_lib_path_rollback = "%s.%s" % (lib_path, funtion_path)
            with mock.patch(mock_lib_path_rollback) as mlpr:
                # Live migrate the instance to another host
                self._live_migrate(self.server,
                                   migration_expected_state='failed',
                                   server_expected_state='MIGRATING')
        mlpr.assert_not_called()
        mlpp.assert_called_once()
