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


class ExtensionInfoAllSamplesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "extension-info"

    def test_list_extensions(self):
        response = self._do_get('extensions')
        # The full extension list is one of the places that things are
        # different between the API versions and the legacy vs. new
        # stack. We default to the v2.1 case.
        template = 'extensions-list-resp'
        if self.api_major_version == 'v2':
            template = 'extensions-list-resp-v21-compatible'

        self._verify_response(template, {}, response, 200)


class ExtensionInfoSamplesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "extension-info"

    def test_get_extensions(self):
        response = self._do_get('extensions/os-agents')
        self._verify_response('extensions-get-resp', {}, response, 200)
