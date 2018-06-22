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
"""Call any URI in the placement service directly without real HTTP.

This is useful for those cases where processes wish to manipulate the
Placement datastore but do not want to run Placement as a long running
service. A PlacementDirect context manager is provided. Within that
HTTP requests may be made as normal but they will not actually traverse
a real socket.
"""

from keystoneauth1 import adapter
from keystoneauth1 import session
import mock
from oslo_utils import uuidutils
import requests
from wsgi_intercept import interceptor

from nova.api.openstack.placement import deploy


class PlacementDirect(interceptor.RequestsInterceptor):
    """Provide access to the placement service without real HTTP.

    wsgi-intercept is used to provide a keystoneauth1 Adapter that has access
    to an in-process placement service. This provides access to making changes
    to the placement database without requiring HTTP over the network - it
    remains in-process.

    Authentication to the service is turned off; admin access is assumed.

    Access is provided via a context manager which is responsible for
    turning the wsgi-intercept on and off, and setting and removing
    mocks required to keystoneauth1 to work around endpoint discovery.

    Example::

      with PlacementDirect(cfg.CONF, latest_microversion=True) as client:
          allocations = client.get('/allocations/%s' % consumer)

    :param conf: An oslo config with the options used to configure
                 the placement service (notably database connection
                 string).
    :param latest_microversion: If True, API requests will use the latest
                                microversion if not otherwise specified.  If
                                False (the default), the base microversion is
                                the default.
    """

    def __init__(self, conf, latest_microversion=False):
        conf.set_override('auth_strategy', 'noauth2', group='api')
        app = lambda: deploy.loadapp(conf)
        self.url = 'http://%s/placement' % str(uuidutils.generate_uuid())
        # Supply our own session so the wsgi-intercept can intercept
        # the right thing.
        request_session = requests.Session()
        headers = {
            'x-auth-token': 'admin',
        }
        # TODO(efried): See below
        if latest_microversion:
            headers['OpenStack-API-Version'] = 'placement latest'
        self.adapter = adapter.Adapter(
            session.Session(auth=None, session=request_session,
                            additional_headers=headers),
            service_type='placement', raise_exc=False)
        # TODO(efried): Figure out why this isn't working:
        #   default_microversion='latest' if latest_microversion else None)
        self._mocked_endpoint = mock.patch(
                'keystoneauth1.session.Session.get_endpoint',
                new=mock.Mock(return_value=self.url))
        super(PlacementDirect, self).__init__(app, url=self.url)

    def __enter__(self):
        """Start the wsgi-intercept interceptor and keystone endpoint mock.

        A no auth ksa Adapter is provided to the context being managed.
        """
        super(PlacementDirect, self).__enter__()
        self._mocked_endpoint.start()
        return self.adapter

    def __exit__(self, *exc):
        self._mocked_endpoint.stop()
        return super(PlacementDirect, self).__exit__(*exc)
