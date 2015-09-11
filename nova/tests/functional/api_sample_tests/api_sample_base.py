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

from nova.api import openstack
from nova.api.openstack import API_V21_CORE_EXTENSIONS  # noqa
from nova.api.openstack import compute
from nova import test
from nova.tests.functional import api_paste_fixture
from nova.tests.functional import api_samples_test_base
from nova.tests.unit import fake_network
from nova.tests.unit import fake_utils

CONF = cfg.CONF


class ApiSampleTestBaseV21(testscenarios.WithScenarios,
                          api_samples_test_base.ApiSampleTestBase):
    _api_version = 'v2'
    sample_dir = None
    extra_extensions_to_load = None
    scenarios = [('v2', {'_test': 'v2'}),
                 ('v2_1', {'_test': 'v2.1'}),
                 ('v2_1_compatible', {'_test': 'v2.1_compatible'})]

    def setUp(self):
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host(),
                   osapi_glance_link_prefix=self._get_glance_host())
        if not self.all_extensions:
            self.flags(osapi_compute_extension=[])
            # Set the whitelist to ensure only the extensions we are
            # interested in are loaded so the api samples don't include
            # data from extensions we are not interested in
            whitelist = API_V21_CORE_EXTENSIONS.copy()
            if self.extension_name:
                whitelist.add(self.extension_name)
            if self.extra_extensions_to_load:
                whitelist.update(set(self.extra_extensions_to_load))

            CONF.set_override('extensions_whitelist', whitelist,
                              'osapi_v21')
        expected_middleware = []
        if (not hasattr(self, '_test') or (self._test == 'v2.1')):
            # NOTE(gmann): we should run v21 tests on /v2.1 but then we need
            # two sets of sample files as api version (v2 or v2.1) is being
            # added in response's link/namespace etc
            # override /v2 in compatibility mode with v2.1
            self.useFixture(api_paste_fixture.ApiPasteV21Fixture())
            expected_middleware = [compute.APIRouterV21]
        elif self._test == 'v2.1_compatible':
            expected_middleware = [openstack.LegacyV2CompatibleWrapper,
                                   compute.APIRouterV21]
        elif (self._test == 'v2' and self._api_version == 'v2'):
            # override /v2 in compatibility mode with v2 legacy
            self.useFixture(api_paste_fixture.ApiPasteLegacyV2Fixture())
        super(ApiSampleTestBaseV21, self).setUp()
        self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self.stubs)
        fake_utils.stub_out_utils_spawn_n(self.stubs)
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None
        if expected_middleware:
            self._check_api_endpoint('/v2', expected_middleware)
