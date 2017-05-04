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
from cinderclient import exceptions as cinder_exceptions
import mock

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.unit import policy_fixture


class TestCinderForbidden(test.TestCase):
    def setUp(self):
        super(TestCinderForbidden, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_forbidden_cinder_operation_returns_403(self, mock_cinder):
        """Regression test for bug #1554631.

        When the Cinder client returns a 403 Forbidden on any operation,
        the Nova API should forward on the 403 instead of returning 500.
        """
        cinder_client = mock.Mock()
        mock_cinder.return_value = cinder_client
        exc = cinder_exceptions.Forbidden(403)
        cinder_client.volumes.create.side_effect = exc

        volume = {'display_name': 'vol1', 'size': 3}
        e = self.assertRaises(client.OpenStackApiException,
                              self.api.post_volume, {'volume': volume})
        self.assertEqual(403, e.response.status_code)


class TestCinderOverLimit(test.TestCase):
    def setUp(self):
        super(TestCinderOverLimit, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_over_limit_volumes_with_message(self, mock_cinder):
        """Regression test for bug #1680457.

        When the Cinder client returns OverLimit when trying to create
        a volume, an OverQuota exception should be raised.
        """
        cinder_client = mock.Mock()
        mock_cinder.return_value = cinder_client
        msg = ("VolumeSizeExceedsLimit: Requested volume size XG is larger"
               " than maximum allowed limit YG.")
        exc = cinder_exceptions.OverLimit(413, message=msg)
        cinder_client.volumes.create.side_effect = exc

        volume = {'display_name': 'vol1', 'size': 3}
        e = self.assertRaises(client.OpenStackApiException,
                              self.api.post_volume, {'volume': volume})
        self.assertEqual(403, e.response.status_code)
        # Make sure we went over on volumes
        self.assertIn('VolumeSizeExceedsLimit', e.response.text)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_over_limit_snapshots(self, mock_cinder):
        """Regression test for bug #1554631.

        When the Cinder client returns OverLimit when trying to create a
        snapshot, an OverQuota exception should be raised with the value being
        snapshots.
        """
        self._do_snapshot_over_test(mock_cinder)

    @mock.patch('nova.volume.cinder.cinderclient')
    def test_over_limit_snapshots_force(self, mock_cinder):
        """Regression test for bug #1554631.

        When the Cinder client returns OverLimit when trying to create a
        snapshot, an OverQuota exception should be raised with the value being
        snapshots. (create_snapshot_force version)
        """
        self._do_snapshot_over_test(mock_cinder, force=True)

    def _do_snapshot_over_test(self, mock_cinder, force=False):
        cinder_client = mock.Mock()
        mock_cinder.return_value = cinder_client
        exc = cinder_exceptions.OverLimit(413)
        cinder_client.volume_snapshots.create.side_effect = exc

        snap = {'display_name': 'snap1',
                'volume_id': '521752a6-acf6-4b2d-bc7a-119f9148cd8c',
                'force': force}
        e = self.assertRaises(client.OpenStackApiException,
                              self.api.post_snapshot, {'snapshot': snap})
        self.assertEqual(403, e.response.status_code)
        # Make sure we went over on snapshots
        self.assertIn('snapshots', e.response.text)
