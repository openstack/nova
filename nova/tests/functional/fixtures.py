#
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
"""Fixtures solely for functional tests."""
import fixtures
from keystoneauth1 import adapter as ka
from keystoneauth1 import session as ks
from placement.tests.functional.fixtures import placement as placement_fixtures
from requests import adapters

from nova.tests.functional.api import client


class PlacementApiClient(object):
    def __init__(self, placement_fixture):
        self.fixture = placement_fixture

    def get(self, url, **kwargs):
        return client.APIResponse(
            self.fixture._fake_get(None, url, **kwargs))

    def put(self, url, body, **kwargs):
        return client.APIResponse(
            self.fixture._fake_put(None, url, body, **kwargs))

    def post(self, url, body, **kwargs):
        return client.APIResponse(
            self.fixture._fake_post(None, url, body, **kwargs))

    def delete(self, url, **kwargs):
        return client.APIResponse(
            self.fixture._fake_delete(None, url, **kwargs))


class PlacementFixture(placement_fixtures.PlacementFixture):
    """A fixture to placement operations.

    Runs a local WSGI server bound on a free port and having the Placement
    application with NoAuth middleware.
    This fixture also prevents calling the ServiceCatalog for getting the
    endpoint.

    It's possible to ask for a specific token when running the fixtures so
    all calls would be passing this token.

    Most of the time users of this fixture will also want the placement
    database fixture to be called first, so that is done automatically. If
    that is not desired pass ``db=False`` when initializing the fixture
    and establish the database yourself with:

        self.useFixture(placement_fixtures.Database(set_config=True))
    """

    def setUp(self):
        super(PlacementFixture, self).setUp()

        # Turn off manipulation of socket_options in TCPKeepAliveAdapter
        # to keep wsgi-intercept happy. Replace it with the method
        # from its superclass.
        self.useFixture(fixtures.MonkeyPatch(
            'keystoneauth1.session.TCPKeepAliveAdapter.init_poolmanager',
            adapters.HTTPAdapter.init_poolmanager))

        self._client = ka.Adapter(ks.Session(auth=None), raise_exc=False)
        # NOTE(sbauza): We need to mock the scheduler report client because
        # we need to fake Keystone by directly calling the endpoint instead
        # of looking up the service catalog, like we did for the OSAPIFixture.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.scheduler.client.report.SchedulerReportClient.get',
            self._fake_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.scheduler.client.report.SchedulerReportClient.post',
            self._fake_post))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.scheduler.client.report.SchedulerReportClient.put',
            self._fake_put))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.scheduler.client.report.SchedulerReportClient.delete',
            self._fake_delete))

        self.api = PlacementApiClient(self)

    @staticmethod
    def _update_headers_with_version(headers, version):
        if version is not None:
            # TODO(mriedem): Perform some version discovery at some point.
            headers.update({
                'OpenStack-API-Version': 'placement %s' % version
            })

    def _fake_get(self, client, url, version=None, global_request_id=None):
        # TODO(sbauza): The current placement NoAuthMiddleware returns a 401
        # in case a token is not provided. We should change that by creating
        # a fake token so we could remove adding the header below.
        headers = {'x-auth-token': self.token}
        self._update_headers_with_version(headers, version)
        return self._client.get(
            url,
            endpoint_override=self.endpoint,
            headers=headers)

    def _fake_post(
        self, client, url, data, version=None, global_request_id=None
    ):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        # TODO(sbauza): The current placement NoAuthMiddleware returns a 401
        # in case a token is not provided. We should change that by creating
        # a fake token so we could remove adding the header below.
        headers = {'x-auth-token': self.token}
        self._update_headers_with_version(headers, version)
        return self._client.post(
            url, json=data,
            endpoint_override=self.endpoint,
            headers=headers)

    def _fake_put(
        self, client, url, data, version=None, global_request_id=None
    ):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        # TODO(sbauza): The current placement NoAuthMiddleware returns a 401
        # in case a token is not provided. We should change that by creating
        # a fake token so we could remove adding the header below.
        headers = {'x-auth-token': self.token}
        self._update_headers_with_version(headers, version)
        return self._client.put(
            url, json=data,
            endpoint_override=self.endpoint,
            headers=headers)

    def _fake_delete(
        self, client, url, version=None, global_request_id=None
    ):
        # TODO(sbauza): The current placement NoAuthMiddleware returns a 401
        # in case a token is not provided. We should change that by creating
        # a fake token so we could remove adding the header below.
        headers = {'x-auth-token': self.token}
        self._update_headers_with_version(headers, version)
        return self._client.delete(
            url,
            endpoint_override=self.endpoint,
            headers=headers)
