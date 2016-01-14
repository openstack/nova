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

from nova.api.openstack import API_V21_CORE_EXTENSIONS  # noqa
from nova import test
from nova.tests.functional import api_paste_fixture
from nova.tests.functional import api_samples_test_base
from nova.tests.unit import fake_network
from nova.tests.unit import fake_utils

CONF = cfg.CONF

# API samples heavily uses testscenarios. This allows us to use the
# same tests, with slight variations in configuration to ensure our
# various ways of calling the API are compatible. Testscenarios works
# through the class level ``scenarios`` variable. It is an array of
# tuples where the first value in each tuple is an arbitrary name for
# the scenario (should be unique), and the second item is a dictionary
# of attributes to change in the class for the test.
#
# By default we're running scenarios for 3 situations
#
# - Hitting the default /v2 endpoint
#
# - Hitting the default /v2.1 endpoint
#
# - Hitting the /v2 but fixing the paste pipeline so that it uses the
#   legacy v2 code. This requires a fixture.
#
# Things we need to set:
#
# - api_major_version - what version of the API we should be hitting
#
# - microversion - what API microversion should be used
#
# - _additional_fixtures - any additional fixtures need
#
# - _legacy_v2_code - True/False if we are using the legacy v2 code
#   stack. Sadly, a few tests really care about this.
#
# NOTE(sdague): if you want to build a test that only tests specific
# microversions, then replace the ``scenarios`` class variable in that
# test class with something like:
#
# [("v2_11", {'api_major_version': 'v2.1', 'microversion': '2.11'})]


class ApiSampleTestBaseV21(testscenarios.WithScenarios,
                          api_samples_test_base.ApiSampleTestBase):
    api_major_version = 'v2'
    # any additional fixtures needed for this scenario
    _additional_fixtures = []
    sample_dir = None
    extra_extensions_to_load = None
    _legacy_v2_code = False

    scenarios = [
        # test v2 with the v2.1 compatibility stack
        ('v2', {
            'api_major_version': 'v2'}),
        # test v2.1 base microversion
        ('v2_1', {
            'api_major_version': 'v2.1'}),
        # test v2 with the v2 legacy code
        ('v2legacy', {
            'api_major_version': 'v2',
            '_legacy_v2_code': True,
            '_additional_fixtures': [
                api_paste_fixture.ApiPasteLegacyV2Fixture]})
    ]

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

        # load any additional fixtures specified by the scenario
        for fix in self._additional_fixtures:
            self.useFixture(fix())

        # super class call is delayed here so that we have the right
        # paste and conf before loading all the services, as we can't
        # change these later.
        super(ApiSampleTestBaseV21, self).setUp()

        self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self.stubs)
        fake_utils.stub_out_utils_spawn_n(self.stubs)

        # this is used to generate sample docs
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None
