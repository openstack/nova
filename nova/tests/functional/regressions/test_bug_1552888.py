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


from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import policy_fixture


class TestAggregateCreation(test.TestCase):

    def setUp(self):
        super(TestAggregateCreation, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.admin_api = api_fixture.admin_api

    def test_name_validation(self):
        """Regression test for bug #1552888.

        The current aggregate accepts a null param for availability zone,
        change to the validation might affect some command like
        'nova aggregate create foo'
        This test ensure those kind of change won't affect validation
        """
        body = {"aggregate": {"name": "foo", "availability_zone": None}}
        # This should success
        self.admin_api.api_post('/os-aggregates', body)
