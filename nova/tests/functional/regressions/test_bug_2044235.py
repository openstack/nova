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


from unittest import mock

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestMessagingTimeoutDuringLiveMigrationCheck(
    integrated_helpers._IntegratedTestBase
):
    """Reproducer for bug #2044235

    This regression test demonstrates that nova-condutor puts instances in
    error state for any raised error in check_can_live_migrate_source function
    during check_can_live_migrate_destination step.
    """

    # Default self.api to the self.admin_api as live migration is admin only
    ADMIN_API = True
    microversion = "latest"

    def setUp(self):
        super(TestMessagingTimeoutDuringLiveMigrationCheck, self).setUp()

    def _setup_compute_service(self):
        self._start_compute("compute-1")
        self._start_compute("compute-2")

    def test_source_error_during_pre_live_migration(self):
        # Create an instance on compute-1
        server = self._create_server(host="compute-1", networks="none")
        self._wait_for_state_change(server, "ACTIVE")

        with mock.patch.object(
            self.computes["compute-2"].compute_rpcapi,
            "check_can_live_migrate_source",
            side_effect=Exception,
        ):
            # Migrate the instance and wait until the migration errors out
            # thanks to our mocked version of check_can_live_migrate_source
            self.assertRaises(
                client.OpenStackApiException,
                self._live_migrate, server, "failed"
            )

        self._wait_for_state_change(server, "ACTIVE")
