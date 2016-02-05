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

from nova.api.openstack import api_version_request as avr
from nova.tests.functional.api_sample_tests import api_sample_base


class VersionsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = 'versions'
    # NOTE(gmann): Setting empty scenario for 'version' API testing
    # as those does not send request on particular endpoint and running
    # its tests alone is enough.
    scenarios = []
    max_api_version = avr.max_api_version().get_string()

    def test_versions_get(self):
        response = self._do_get('', strip_version=True)
        self._verify_response('versions-get-resp',
                              {'max_api_version': self.max_api_version},
                              response, 200, update_links=False)

    def test_versions_get_v2(self):
        response = self._do_get('/v2', strip_version=True)
        self._verify_response('v2-version-get-resp', {},
                              response, 200, update_links=False)

    def test_versions_get_v21(self):
        response = self._do_get('/v2.1', strip_version=True)
        self._verify_response('v21-version-get-resp',
                              {'max_api_version': self.max_api_version},
                              response, 200, update_links=False)
