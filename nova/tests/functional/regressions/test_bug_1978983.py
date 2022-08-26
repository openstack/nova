# Copyright 2022 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class EvacuateServerWithTaskState(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Regression test for bug 1978983
    If instance task state is powering-off or not None
    instance should be allowed to evacuate.
    """

    def setUp(self):
        super().setUp()
        # Stub out external dependencies.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        # Start nova controller services.
        self.start_service('conductor')
        self.start_service('scheduler')

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.api.microversion = 'latest'

        self.src = self._start_compute(host='host1')
        self.dest = self._start_compute(host='host2')

    def test_evacuate_instance(self):
        """Evacuating a server
        """
        server = self._create_server(networks=[])

        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(self.src.host, server['OS-EXT-SRV-ATTR:host'])

        # stop host1 compute service
        self.src.stop()
        self.api.put_service_force_down(self.src.service_ref.uuid, True)

        # poweroff instance
        self._stop_server(server, wait_for_stop=False)
        server = self._wait_for_server_parameter(
            server, {'OS-EXT-STS:task_state': 'powering-off'})

        # evacuate instance
        server = self._evacuate_server(
            server, expected_host=self.dest.host
        )
        self.assertEqual(self.dest.host, server['OS-EXT-SRV-ATTR:host'])
