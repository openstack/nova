# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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
import ddt
import fixtures
import webob

from nova.api.openstack import api_version_request as avr
from nova.tests.functional.api_sample_tests import api_sample_base


@ddt.ddt
class VersionsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    """Validate that proper version documents can be fetched without auth."""

    # Here we want to avoid stubbing keystone middleware. That will cause
    # "real" keystone middleware to run (and fail) if it's in the pipeline.
    # (The point of this test is to prove we do version discovery through
    # pipelines that *don't* authenticate.)
    STUB_KEYSTONE = False

    USE_PROJECT_ID = False

    sample_dir = 'versions'
    # NOTE(gmann): Setting empty scenario for 'version' API testing
    # as those does not send request on particular endpoint and running
    # its tests alone is enough.
    scenarios = []
    max_api_version = {'max_api_version': avr.max_api_version().get_string()}

    def setUp(self):
        super(VersionsSampleJsonTest, self).setUp()
        # Version documents are supposed to be available without auth, so make
        # the auth middleware "fail" authentication.
        self.useFixture(fixtures.MockPatch(
            # [api]auth_strategy is set to noauth2 by the ConfFixture
            'nova.api.openstack.auth.NoAuthMiddlewareBase.base_call',
            return_value=webob.Response(status=401)))

    def _get(self, url):
        return self._do_get(
            url,
            # Since we're explicitly getting discovery endpoints, strip the
            # automatic /v2[.1] added by the fixture.
            strip_version=True)

    @ddt.data('', '/')
    def test_versions_get_base(self, url):
        response = self._get(url)
        self._verify_response('versions-get-resp', self.max_api_version,
                              response, 200, update_links=False)

    @ddt.data(('/v2', 'v2-version-get-resp', {}),
              ('/v2/', 'v2-version-get-resp', {}),
              ('/v2.1', 'v21-version-get-resp', max_api_version),
              ('/v2.1/', 'v21-version-get-resp', max_api_version))
    @ddt.unpack
    def test_versions_get_versioned(self, url, tplname, subs):
        response = self._get(url)
        self._verify_response(tplname, subs, response, 200, update_links=False)
