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

import os

from gabbi import fixture
from oslo_utils import uuidutils

from nova.api.openstack.placement import deploy
from nova import conf
from nova import config
from nova.tests import fixtures


CONF = conf.CONF


def setup_app():
    return deploy.loadapp(CONF)


class APIFixture(fixture.GabbiFixture):
    """Setup the required backend fixtures for a basic placement service."""

    def __init__(self):
        self.conf = None

    def start_fixture(self):
        self.conf = CONF
        self.conf.set_override('auth_strategy', 'noauth2')
        # Be explicit about all three database connections to avoid
        # potential conflicts with config on disk.
        self.conf.set_override('connection', "sqlite://", group='database')
        self.conf.set_override('connection', "sqlite://",
                               group='api_database')
        self.conf.set_override('connection', "sqlite://",
                               group='placement_database')
        config.parse_args([], default_config_files=None, configure_db=False,
                          init_rpc=False)

        self.placement_db_fixture = fixtures.Database('placement')
        # NOTE(cdent): api and main database are not used but we still need
        # to manage them to make the fixtures work correctly and not cause
        # conflicts with other tests in the same process.
        self.api_db_fixture = fixtures.Database('api')
        self.main_db_fixture = fixtures.Database('main')
        self.placement_db_fixture.reset()
        self.api_db_fixture.reset()
        self.main_db_fixture.reset()

        os.environ['RP_UUID'] = uuidutils.generate_uuid()
        os.environ['RP_NAME'] = uuidutils.generate_uuid()

    def stop_fixture(self):
        self.placement_db_fixture.cleanup()
        self.api_db_fixture.cleanup()
        self.main_db_fixture.cleanup()
        if self.conf:
            self.conf.reset()
