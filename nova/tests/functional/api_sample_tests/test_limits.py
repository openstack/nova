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

from nova.tests.functional.api_sample_tests import api_sample_base


class LimitsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "limits"

    def setUp(self):
        super(LimitsSampleJsonTest, self).setUp()
        # NOTE(gmann): We have to separate the template files between V2
        # and V2.1 as the response are different.
        self.template = 'limit-get-resp'

    def test_limits_get(self):
        response = self._do_get('limits')
        self._verify_response(self.template, {}, response, 200)


class LimitsV236Test(api_sample_base.ApiSampleTestBaseV21):
    """Test limits don't return network resources after 2.36.

    We dropped the network API in 2.36, which also means that we
    shouldn't be returning any limits related to network resources
    either. This tests a different limits template after that point
    which does not have these.

    """
    sample_dir = "limits"
    microversion = '2.36'
    scenarios = [('v2_36', {'api_major_version': 'v2.1'})]

    def test_limits_get(self):
        self.api.microversion = self.microversion
        response = self._do_get('limits')
        self._verify_response('limit-get-resp', {}, response, 200)


class LimitsV239Test(api_sample_base.ApiSampleTestBaseV21):
    """Test limits don't return 'maxImageMeta' field after 2.39.

    We dropped the image-metadata proxy API in 2.39, which also means that we
    shouldn't be returning 'maxImageMeta' field in 'os-limits' response.

    """
    sample_dir = "limits"
    microversion = '2.39'
    scenarios = [('v2_39', {'api_major_version': 'v2.1'})]

    def test_limits_get(self):
        self.api.microversion = self.microversion
        response = self._do_get('limits')
        self._verify_response('limit-get-resp', {}, response, 200)
