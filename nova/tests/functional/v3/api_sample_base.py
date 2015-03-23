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

import os

from oslo_config import cfg
import testscenarios
import testtools

from nova.api.openstack import API_V3_CORE_EXTENSIONS  # noqa
from nova import test
from nova.tests.functional import api_samples_test_base
from nova.tests.functional.v3 import api_paste_fixture
from nova.tests.unit import fake_network
from nova.tests.unit import fake_utils

CONF = cfg.CONF


class ApiSampleTestBaseV3(testscenarios.WithScenarios,
                          api_samples_test_base.ApiSampleTestBase):
    _api_version = 'v3'
    sample_dir = None
    extra_extensions_to_load = None
    scenarios = [('v2', {'_test': 'v2'}),
                 ('v2_1', {'_test': 'v2.1'})]

    def setUp(self):
        # TODO(gmann): Below condition is to skip the tests which running
        # for 'v2' and have not been merged yet. Once all tests are merged
        # this condition needs to be removed.
        if ((self._test == 'v2') and (self._api_version == 'v3')):
            raise testtools.TestCase.skipException('tests are not merged yet')
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host(),
                   osapi_glance_link_prefix=self._get_glance_host(),
                   osapi_compute_extension=[])
        if not self.all_extensions:
            # Set the whitelist to ensure only the extensions we are
            # interested in are loaded so the api samples don't include
            # data from extensions we are not interested in
            whitelist = API_V3_CORE_EXTENSIONS.copy()
            if self.extension_name:
                whitelist.add(self.extension_name)
            if self.extra_extensions_to_load:
                whitelist.update(set(self.extra_extensions_to_load))

            CONF.set_override('extensions_whitelist', whitelist,
                              'osapi_v3')
        # TODO(gmann): Currently redirecting only merged tests
        # after merging all tests, second condition needs to be removed.
        if ((self._test == 'v2.1') and (self._api_version == 'v2')):
            # NOTE(gmann)For v2.1 API testing, override /v2 endpoint with v2.1
            self.useFixture(api_paste_fixture.ApiPasteFixture())
        super(ApiSampleTestBaseV3, self).setUp()
        self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self.stubs)
        fake_utils.stub_out_utils_spawn_n(self.stubs)
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None

    @classmethod
    def _get_sample_path(cls, name, dirname, suffix='', api_version=None):
        parts = [dirname]
        parts.append('api_samples')
        if cls.all_extensions:
            parts.append('all_extensions')
        # Note(gmann): if _use_common_server_api_samples is set to True
        # then common server sample files present in 'servers' directory
        # will be used.
        elif cls._use_common_server_api_samples:
            parts.append('servers')
        elif cls.sample_dir:
            parts.append(cls.sample_dir)
        elif cls.extension_name:
            parts.append(cls.extension_name)
        if api_version:
            parts.append('v' + api_version)
        parts.append(name + "." + cls.ctype + suffix)
        return os.path.join(*parts)

    @classmethod
    def _get_sample(cls, name, api_version=None):
        dirname = os.path.dirname(os.path.abspath(__file__))
        dirname = os.path.normpath(os.path.join(dirname,
                                                "../../../../doc/v3"))
        return cls._get_sample_path(name, dirname, api_version=api_version)

    @classmethod
    def _get_template(cls, name, api_version=None):
        dirname = os.path.dirname(os.path.abspath(__file__))
        return cls._get_sample_path(name, dirname, suffix='.tpl',
                                    api_version=api_version)
