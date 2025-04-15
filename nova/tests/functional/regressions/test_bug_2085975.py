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
import threading

from oslo_log import log as logging

from nova.tests.functional.libvirt import base


LOG = logging.getLogger(__name__)


class TestComputeStartupInProgressEvacuation(
    base.ServersTestBase
):
    """Regression test for bug 2085975. """
    CAST_AS_CALL = False
    ADMIN_API = True
    microversion = 'latest'

    def test_compute_startup_evacuation_in_progress(self):
        """Test that when the source compute started up while an instance
        evacuation from that compute is still in progress on the destination
        then the source compute properly sends the shared storage check RPC
        call to the dest compute based on the in progress migration and not
        based on the instance.host.

        To be able to test it we need a bit of setup:
        * we need to ensure check_instance_shared_storage_local passes in
          the functional env instead of returning None and triggering skip of
          the remote check
        * we need to hook the check_instance_shared_storage RPC call to be
          able to assert its success / failure
        * we need to stop the evacuation on the dest compute at the right time
          when the migration record is already in progress and the
          instance.host is not yet set to the dest. We hook the libvirt
          driver's rebuild method to wait.

        """
        # we are expecting to hit RPC timeout so set it to low value to speed
        # the test up
        self.flags(rpc_response_timeout=1)

        self.start_compute('compute1')
        self.start_compute('compute2')

        # this call does not work in the functional env as it always returns
        # None due to the instance directory does not exist locally.
        # This means the shared storage check is skipped in functional env.
        # But we need that to happen in this test case so we mock the function
        # to return success on the local check so that the RPC call to the
        # remote end is triggered.
        # Also, we need to mock globally not just in compute1 as the compute1
        # restart will instantiate a new driver.
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver.'
            'check_instance_shared_storage_local',
            return_value={"filename": "foo"}))

        # To be able to assert that shared storage check failed due to RPC
        # timeout we need to hook check_instance_shared_storage RPC call
        compute1_rpc = self.computes['compute1'].compute_rpcapi
        origi_check_shared_storage = compute1_rpc.check_instance_shared_storage
        rpc_exception = None
        rpc_target_host = None

        def wrapped_check_shared_storage(ctxt, data, instance, host=None):
            try:
                nonlocal rpc_target_host
                rpc_target_host = host
                return origi_check_shared_storage(ctxt, data, instance, host)
            except Exception as e:
                nonlocal rpc_exception
                rpc_exception = e

        self.useFixture(fixtures.MockPatch(
            'nova.compute.rpcapi.ComputeAPI.check_instance_shared_storage',
            side_effect=wrapped_check_shared_storage))

        # need to make sure the evac is stopped at target compute. This
        # simulates that the evac is slow due to e.g. a lot of volume connects
        # needs to be re-attached.
        sleeping = threading.Event()
        contd = threading.Event()

        def slow_evac(*args, **kwargs):
            sleeping.set()
            contd.wait()
            # this will trigger the normal rebuild path for the libvirt driver
            # that does not implement any specific rebuild call.
            raise NotImplementedError()

        self.useFixture(fixtures.MockPatchObject(
            self.computes['compute2'].driver, 'rebuild',
            side_effect=slow_evac))

        # Create a test server on the first compute
        server = self._create_server(host='compute1', networks='none')

        # stop the compute hosting our instance and force it down to allow
        # evacuation
        self.computes['compute1'].stop()
        service_id = self.admin_api.get_services(
            host='compute1', binary='nova-compute')[0]['id']
        self.admin_api.put_service_force_down(service_id, True)

        # request the evacuation but do not wait until it succeeds
        self.api.post_server_action(server['id'], {'evacuate': {}})
        # wait until the evac hits compute2
        sleeping.wait()

        # start up the source compute while the evacuation is still running
        self.restart_compute_service('compute1')

        # allow the rebuild to continue to ensure the test case cleanly
        # finishes
        contd.set()

        self.assertIsNone(rpc_exception)
        self.assertEqual('compute2', rpc_target_host)
