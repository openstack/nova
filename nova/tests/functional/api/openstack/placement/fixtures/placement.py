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

import fixtures
from oslo_config import cfg
from oslo_utils import uuidutils
from wsgi_intercept import interceptor

from nova.api.openstack.placement import deploy


CONF = cfg.CONF


class ConfPatcher(fixtures.Fixture):
    """Fixture to patch and restore global CONF.

    This also resets overrides for everything that is patched during
    its teardown.
    """
    # TODO(cdent): This is intentionally duplicated from nova's fixtures.
    # This comment becomes redundant once placement is extracted.

    def __init__(self, **kwargs):
        """Constructor

        :params group: if specified all config options apply to that group.

        :params **kwargs: the rest of the kwargs are processed as a
        set of key/value pairs to be set as configuration override.

        """
        super(ConfPatcher, self).__init__()
        self.group = kwargs.pop('group', None)
        self.args = kwargs

    def setUp(self):
        super(ConfPatcher, self).setUp()
        for k, v in self.args.items():
            self.addCleanup(CONF.clear_override, k, self.group)
            CONF.set_override(k, v, self.group)


class PlacementFixture(fixtures.Fixture):
    """A fixture to placement operations.

    Runs a local WSGI server bound on a free port and having the Placement
    application with NoAuth middleware.
    This fixture also prevents calling the ServiceCatalog for getting the
    endpoint.

    It's possible to ask for a specific token when running the fixtures so
    all calls would be passing this token.
    """
    def __init__(self, token='admin'):
        self.token = token

    def setUp(self):
        super(PlacementFixture, self).setUp()

        self.useFixture(ConfPatcher(group='api', auth_strategy='noauth2'))
        loader = deploy.loadapp(CONF)
        app = lambda: loader
        self.endpoint = 'http://%s/placement' % uuidutils.generate_uuid()
        intercept = interceptor.RequestsInterceptor(app, url=self.endpoint)
        intercept.install_intercept()
        self.addCleanup(intercept.uninstall_intercept)
