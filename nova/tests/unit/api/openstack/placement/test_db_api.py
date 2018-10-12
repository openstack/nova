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


import mock
import testtools

from oslo_config import cfg
from oslo_config import fixture as config_fixture

from nova.api.openstack.placement import db_api


CONF = cfg.CONF


class DbApiTests(testtools.TestCase):

    def setUp(self):
        super(DbApiTests, self).setUp()
        self.conf_fixture = self.useFixture(config_fixture.Config(CONF))
        db_api.configure.reset()

    @mock.patch.object(db_api.placement_context_manager, "configure")
    def test_can_call_configure_twice(self, configure_mock):
        """This test asserts that configure can be safely called twice
        which may happen if placement is run under mod_wsgi and the
        wsgi application is reloaded.
        """
        db_api.configure(self.conf_fixture.conf)
        configure_mock.assert_called_once()

        # a second invocation of configure on a transaction context
        # should raise an exception so mock this and assert its not
        # called on a second invocation of db_api's configure function
        configure_mock.side_effect = TypeError()

        db_api.configure(self.conf_fixture.conf)
        # Note we have not reset the mock so it should
        # have been called once from the first invocation of
        # db_api.configure and the second invocation should not
        # have called it again
        configure_mock.assert_called_once()
