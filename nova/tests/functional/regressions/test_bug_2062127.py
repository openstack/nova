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

"""Regression test for bug 2062127.

When rebuilding a volume-backed server with a snapshot image (size=0 in
Glance), the reimage timeout is calculated as 0 seconds, causing
immediate failure. The snapshot image is a zero-sized metadata reference
in Glance that points to a Cinder volume snapshot. The fix looks up the
real volume size from the image's block_device_mapping property when the
image size is 0.
"""

from unittest import mock

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class TestRebuildWithSnapshotImage(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 2062127.

    When rebuilding a BFV server with a snapshot image (size=0 in
    Glance), the reimage timeout is calculated as 0 seconds, causing
    immediate failure.
    """

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))
        self.useFixture(nova_fixtures.CastAsCallFixture(self))

        self.start_service('conductor')
        self.start_service('scheduler')

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.api.microversion = '2.93'

        self.compute = self._start_compute(host='compute1')

    def test_rebuild_bfv_with_snapshot_image(self):
        """Test that rebuilding a BFV server with a zero-size snapshot
        image computes the correct reimage timeout.

        A BFV snapshot creates a zero-sized metadata reference in Glance
        pointing to a volume snapshot in Cinder. Without the fix, the
        timeout is 0 because image_size is 0.
        """
        # 1. Create BFV server
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'test-bfv-rebuild-snapshot',
                'networks': [],
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid':
                        nova_fixtures.CinderFixture.IMAGE_BACKED_VOL,
                    'source_type': 'volume',
                    'destination_type': 'volume',
                }],
            }
        })
        server = self._wait_for_state_change(server, 'ACTIVE')

        # 2. Create zero-size snapshot image simulating a BFV snapshot.
        # When Glance creates a snapshot of a BFV server, the image has
        # size=0 and includes block_device_mapping in its properties
        # pointing to the Cinder volume snapshot.
        snapshot_img_id = '1e62c411-9999-0000-aaaa-000000000000'
        self.glance.create(None, {
            'id': snapshot_img_id,
            'name': 'bfv-snapshot',
            'status': 'active',
            'container_format': 'bare',
            'disk_format': 'raw',
            'size': 0,
            'properties': {
                'block_device_mapping': [{
                    'source_type': 'snapshot',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'snapshot_id':
                        '2cc6e0cb-aaaa-bbbb-cccc-000000000000',
                    'volume_size': 1,
                }],
            },
        })

        # 3. Rebuild with the snapshot image, mocking
        # wait_for_instance_event to capture the timeout argument
        with mock.patch.object(
                self.compute.manager.virtapi,
                'wait_for_instance_event') as mock_wait:
            self.api.api_post(
                '/servers/%s/action' % server['id'],
                {'rebuild': {'imageRef': snapshot_img_id}},
                check_response_status=[202])

        # 4. Assert the timeout passed to wait_for_instance_event
        mock_wait.assert_called_once()
        _, kwargs = mock_wait.call_args

        # BUG 2062127: timeout is 0 because image size is 0
        self.assertEqual(0, kwargs['timeout'])
