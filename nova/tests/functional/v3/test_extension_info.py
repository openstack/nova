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

import re

import mock
from oslo.serialization import jsonutils

from nova.api.openstack import extensions as api_extensions
from nova.tests.functional.v3 import api_sample_base


def fake_soft_extension_authorizer(api_name, extension_name):
    def authorize(context, action=None):
        return True
    return authorize


class ExtensionInfoAllSamplesJsonTest(api_sample_base.ApiSampleTestBaseV3):
    all_extensions = True

    @mock.patch.object(api_extensions, 'soft_extension_authorizer')
    def test_list_extensions(self, soft_auth):
        soft_auth.side_effect = fake_soft_extension_authorizer
        response = self._do_get('extensions')
        subs = self._get_regexes()
        self._verify_response('extensions-list-resp', subs, response, 200)


class ExtensionInfoSamplesJsonTest(api_sample_base.ApiSampleTestBaseV3):
    sample_dir = "extension-info"
    extra_extensions_to_load = ["os-create-backup"]

    @mock.patch.object(api_extensions, 'soft_extension_authorizer')
    def test_get_extensions(self, soft_auth):
        soft_auth.side_effect = fake_soft_extension_authorizer
        response = self._do_get('extensions/os-create-backup')
        subs = self._get_regexes()
        self._verify_response('extensions-get-resp', subs, response, 200)


class ExtensionInfoFormatTest(api_sample_base.ApiSampleTestBaseV3):
    # NOTE: To check all extension formats, here makes authorize() return True
    # always instead of fake_policy.py because most extensions are not set as
    # "discoverable" in fake_policy.py.
    all_extensions = True

    def _test_list_extensions(self, key, pattern):
        with mock.patch.object(api_extensions,
                               'soft_extension_authorizer') as api_mock:
            def fake_soft_extension_authorizer(api_name, extension_name):
                def authorize(context, action=None):
                    return True
                return authorize

            api_mock.side_effect = fake_soft_extension_authorizer
            response = self._do_get('extensions')
            response = jsonutils.loads(response.content)
            extensions = response['extensions']
            pattern_comp = re.compile(pattern)
            for ext in extensions:
                self.assertIsNotNone(pattern_comp.match(ext[key]),
                                 '%s does not match with %s' % (ext[key],
                                                                pattern))

    def test_list_extensions_name_format(self):
        # name should be CamelCase.
        pattern = '^[A-Z]{1}[a-z]{1}[a-zA-Z]*$'
        self._test_list_extensions('name', pattern)
