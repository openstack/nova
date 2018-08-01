#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import output
import testtools

from nova.api.openstack.placement import context
from nova.api.openstack.placement import deploy
from nova.api.openstack.placement.objects import resource_provider
from nova.tests import fixtures
from nova.tests.functional.api.openstack.placement.fixtures import capture
from nova.tests.unit import policy_fixture


CONF = cfg.CONF


class TestCase(testtools.TestCase):
    """A base test case for placement functional tests.

    Sets up minimum configuration for database and policy handling
    and establishes the placement database.
    """

    def setUp(self):
        super(TestCase, self).setUp()

        # Manage required configuration
        conf_fixture = self.useFixture(config_fixture.Config(CONF))
        # The Database fixture will get confused if only one of the databases
        # is configured.
        for group in ('placement_database', 'api_database', 'database'):
            conf_fixture.config(
                group=group,
                connection='sqlite://',
                sqlite_synchronous=False)
        CONF([], default_config_files=[])

        self.useFixture(policy_fixture.PlacementPolicyFixture())

        self.useFixture(capture.Logging())
        self.useFixture(output.CaptureOutput())
        # Filter ignorable warnings during test runs.
        self.useFixture(capture.WarningsFixture())

        self.placement_db = self.useFixture(
            fixtures.Database(database='placement'))
        self._reset_database()
        self.context = context.RequestContext()
        # Do database syncs, such as traits sync.
        deploy.update_database()
        self.addCleanup(self._reset_database)

    @staticmethod
    def _reset_database():
        """Reset database sync flags to base state."""
        resource_provider._TRAITS_SYNCED = False
        resource_provider._RC_CACHE = None
