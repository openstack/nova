# Copyright (c) 2025, STACKIT GmbH & Co. KG.
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
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base
import threading


class TestDeleteInstanceWhileSchedulingWithBDM(
    base.ServersTestBase, integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 2088066

    This test ensures that when an instance is being booted from an volume
    and the instance is deleted while still in the scheduling
    phase, the associated Cinder volume attachments are properly cleaned up.
    """

    microversion = "latest"
    CAST_AS_CALL = False

    def setUp(self):
        super(TestDeleteInstanceWhileSchedulingWithBDM, self).setUp()
        self.start_compute()
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))
        self.flavor_id = self.api.get_flavors()[0]["id"]

    def test_delete_instance_while_scheduling_with_bdm(self):
        sleeping = threading.Event()
        contd = threading.Event()

        # server booted from volume
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server_request = self._build_server(networks=[])
        server_request.pop("imageRef")  # boot from volume
        server_request["block_device_mapping_v2"] = [
            {
                "boot_index": 0,
                "uuid": volume_id,
                "source_type": "volume",
                "destination_type": "volume",
            }
        ]

        # block build_and_run_instance to simulate scheduling delay
        # so that we can delete the instance while scheduling/building
        # is in progress
        def block_build_and_run_instance(*args, **kwargs):
            sleeping.set()
            contd.wait()
            raise NotImplementedError()

        self.useFixture(
            fixtures.MockPatch(
                "nova.compute.rpcapi.ComputeAPI.build_and_run_instance",
                side_effect=block_build_and_run_instance,
            )
        )

        # create server (this will block in build_and_run_instance)
        server = self.api.post_server({"server": server_request})
        server_id = server["id"]
        # wait until we are in build_and_run_instance
        sleeping.wait()

        # now we should have a volume attachment on cinder side
        cinder_attachments = list(
            self.cinder.volume_ids_for_instance(server_id)
        )
        self.assertNotEqual(
            [], cinder_attachments, "Should have volume attachments"
        )

        # delete server and wait for it
        self._delete_server(server)

        # now check that cinder volume attachments are gone
        final_attachments = list(
            self.cinder.volume_ids_for_instance(server_id)
        )

        self.assertEqual(
            [], final_attachments, "Volume attachments should be cleaned up"
        )

        # allow build_and_run_instance to continue for clean up (also if this
        # fails)
        contd.set()
