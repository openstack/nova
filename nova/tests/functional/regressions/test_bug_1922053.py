
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

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class ForceUpWithDoneEvacuations(integrated_helpers._IntegratedTestBase):
    """Regression test for bug 1922053.

    This regression test aims to assert the behaviour of n-api when forcing a
    compute service up when it is associated with evacuation migration
    records still marked as `done`. This suggests that the compute service
    was not correctly fenced when the evacuation was requested and has not
    restarted since allowing the evacuation migration records to move to a
    state of `completed`.
    """

    ADMIN_API = True
    microversion = 'latest'
    expected_state = 'SHUTOFF'

    def _create_test_server(self, compute_host):
        return self._create_server(host=compute_host, networks='none')

    def _force_down_compute(self, hostname):
        compute_id = self.api.get_services(
            host=hostname, binary='nova-compute')[0]['id']
        self.api.put_service(compute_id, {'forced_down': 'true'})

    def _force_up_compute(self, hostname):
        compute_id = self.api.get_services(
            host=hostname, binary='nova-compute')[0]['id']
        self.api.put_service(compute_id, {'forced_down': 'false'})

    def test_force_up_with_done_evacuation_records(self):
        # Launch a second compute to host the evacuated instance
        self._start_compute('compute2')

        # Create a test server to evacuate
        server = self._create_test_server('compute')

        # Assert we've landed on the first compute
        self.assertEqual('compute', server['OS-EXT-SRV-ATTR:host'])

        # Force down the first compute to allow the evacuation
        self._force_down_compute('compute')

        # Evacuate then assert the instance moves to compute2 and that the
        # migration record is moved to done
        server = self._evacuate_server(
            server,
            expected_host='compute2',
            expected_migration_status='done',
            expected_state=self.expected_state
        )

        # Assert that the request to force up the host is rejected
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._force_up_compute,
            'compute',
        )
        self.assertEqual(400, ex.response.status_code)

        # Assert that the evacuation migration record remains `done`
        self._wait_for_migration_status(server, ["done"])

        # Restart the source compute to move the migration record along
        self.computes['compute'].stop()
        self.computes['compute'].start()

        # Assert that the evacuation migration record is now `completed`
        self._wait_for_migration_status(server, ["completed"])

        # Assert that we can now force up the host
        self._force_up_compute('compute')


class ForceUpWithDoneEvacuationsv252(ForceUpWithDoneEvacuations):

    """Regression test for bug 1922053 using microversion 2.52.

    Required as the PUT /os-services/force-down API used by this test via
    self.api.force_down_service is superseded by PUT /os-services/{service_id}
    API used by our parent ForceUpWithDoneEvacuations class from >=2.53.

    This test also uses the 'availability_zone' parameter to force the server
    to spawn on the first compute as 'host' is only available from 2.74.
    """

    microversion = '2.52'
    expected_state = 'ACTIVE'

    def _create_test_server(self, compute_host):
        return self._create_server(az='nova:compute', networks='none')

    def _force_down_compute(self, hostname):
        self.api.force_down_service(hostname, 'nova-compute', forced_down=True)

    def _force_up_compute(self, hostname):
        self.api.force_down_service(
            hostname, 'nova-compute', forced_down=False)
