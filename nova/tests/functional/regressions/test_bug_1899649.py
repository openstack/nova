# Copyright 2020, Red Hat, Inc. All Rights Reserved.
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

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt


class TestVolAttachmentsAfterFailureToScheduleOrBuild(base.ServersTestBase):
    """Regression test for bug .

    This regression test aims to ensure a volume attachment remains in place
    after a failure to either schedule a server or when building a server
    directly on a compute after skipping the scheduler.

    A volume attachment is required to remain after such failures to ensure the
    volume itself remains marked as reserved.

    To ensure this is as accurate as possible the tests use the libvirt
    functional base class to mimic a real world example with NUMA nodes being
    requested via flavor extra specs. The underlying compute being unable to
    meet this request ensuring a failure.
    """

    microversion = 'latest'

    def setUp(self):
        super().setUp()

        # Launch a single libvirt based compute service with a single NUMA node
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=1, cpu_cores=2, kB_mem=15740000)
        self.start_compute(host_info=host_info, hostname='compute1')

        # Use a flavor requesting 2 NUMA nodes that we know will always fail
        self.flavor_id = self._create_flavor(extra_spec={'hw:numa_nodes': '2'})

        # Craft a common bfv server request for use within each test
        self.volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        self.server = {
            'name': 'test',
            'flavorRef': self.flavor_id,
            'imageRef': '',
            'networks': 'none',
            'block_device_mapping_v2': [{
                'source_type': 'volume',
                'destination_type': 'volume',
                'boot_index': 0,
                'uuid': self.volume_id}]
        }

    def _assert_failure_and_volume_attachments(self, server):
        # Assert that the server is in an ERROR state
        self._wait_for_state_change(server, 'ERROR')

        # Assert that the volume is in a reserved state. As this isn't modelled
        # by the CinderFixture we just assert that a single volume attachment
        # remains after the failure and that it is referenced by the server.
        attachments = self.cinder.volume_to_attachment.get(self.volume_id)
        self.assertEqual(1, len(attachments))
        self.assertIn(
            self.volume_id, self.cinder.volume_ids_for_instance(server['id']))

    def test_failure_to_schedule(self):
        # Assert that a volume attachment remains after a failure to schedule
        server = self.api.post_server({'server': self.server})
        self._assert_failure_and_volume_attachments(server)

    def test_failure_to_schedule_with_az(self):
        # Assert that a volume attachment remains after a failure to schedule
        # with the addition of an availability_zone in the request
        self.server['availability_zone'] = 'nova'
        server = self.api.post_server({'server': self.server})
        self._assert_failure_and_volume_attachments(server)

    def test_failure_to_schedule_with_host(self):
        # Assert that a volume attachment remains after a failure to schedule
        # using the optional host parameter introduced in microversion 2.74
        self.server['host'] = 'compute1'
        server = self.admin_api.post_server({'server': self.server})
        self._assert_failure_and_volume_attachments(server)

    def test_failure_to_build_with_az_and_host(self):
        # Assert that a volume attachments remain after a failure to
        # build and reschedule by providing an availability_zone *and* host,
        # skipping the scheduler. This is bug #1899649.
        self.server['availability_zone'] = 'nova:compute1'
        server = self.admin_api.post_server({'server': self.server})
        self._assert_failure_and_volume_attachments(server)
