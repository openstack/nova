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
        exc = cinder_exceptions.Forbidden('')
        cinder_client.volumes.create.side_effect = exc

        volume = {'display_name': 'vol1', 'size': 3}
        e = self.assertRaises(client.OpenStackApiException,
                              self.api.post_volume, {'volume': volume})
        self.assertEqual(403, e.response.status_code)
