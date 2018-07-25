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
import testtools

from nova.api.openstack.placement.objects import resource_provider
from nova import config
from nova import context
from nova.tests import fixtures
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
        conf_fixture.conf.set_default(
            'connection', "sqlite://", group='placement_database')
        conf_fixture.conf.set_default(
            'sqlite_synchronous', False, group='placement_database')
        config.parse_args([], default_config_files=[], configure_db=False,
            init_rpc=False)

        self.useFixture(policy_fixture.PlacementPolicyFixture())
        self.placement_db = self.useFixture(
            fixtures.Database(database='placement'))
        self._reset_traits_synced()
        self.context = context.get_admin_context()
        self.addCleanup(self._reset_traits_synced)

    @staticmethod
    def _reset_traits_synced():
        """Reset the _TRAITS_SYNCED boolean to base state."""
        resource_provider._TRAITS_SYNCED = False
