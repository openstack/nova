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

from gabbi import fixture

from nova.api.openstack.placement import deploy
from nova import conf
from nova import config


CONF = conf.CONF


def setup_app():
    return deploy.loadapp(CONF)


class APIFixture(fixture.GabbiFixture):
    """Setup the required backend fixtures for a basic placement service."""

    def __init__(self):
        self.conf = None

    def start_fixture(self):
        self.conf = CONF
        config.parse_args([], default_config_files=None, configure_db=False,
                          init_rpc=False)
        self.conf.set_override('auth_strategy', 'noauth2')

    def stop_fixture(self):
        if self.conf:
            self.conf.reset()
