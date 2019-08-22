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

import testscenarios

import nova.conf
from nova import test
from nova.tests import fixtures
from nova.tests.functional import api_paste_fixture
from nova.tests.functional import api_samples_test_base
from nova.tests.unit import fake_network

CONF = nova.conf.CONF

# API samples heavily uses testscenarios. This allows us to use the
# same tests, with slight variations in configuration to ensure our
# various ways of calling the API are compatible. Testscenarios works
# through the class level ``scenarios`` variable. It is an array of
# tuples where the first value in each tuple is an arbitrary name for
# the scenario (should be unique), and the second item is a dictionary
# of attributes to change in the class for the test.
#
# By default we're running scenarios for 2 situations
#
# - Hitting the default /v2 endpoint with the v2.1 Compatibility stack
#
# - Hitting the default /v2.1 endpoint
#
# Things we need to set:
#
# - api_major_version - what version of the API we should be hitting
#
# - microversion - what API microversion should be used
#
# - _additional_fixtures - any additional fixtures need
#
# NOTE(sdague): if you want to build a test that only tests specific
# microversions, then replace the ``scenarios`` class variable in that
# test class with something like:
#
# [("v2_11", {'api_major_version': 'v2.1', 'microversion': '2.11'})]


class ApiSampleTestBaseV21(testscenarios.WithScenarios,
                          api_samples_test_base.ApiSampleTestBase):
    SUPPORTS_CELLS = False

    api_major_version = 'v2'
    # any additional fixtures needed for this scenario
    _additional_fixtures = []
    sample_dir = None
    _use_project_id = True
    # Availability zones for the API samples tests. Can be overridden by
    # sub-classes. If set, the AvailabilityZoneFilter is not used.
    availability_zones = ['us-west']

    scenarios = [
        # test v2 with the v2.1 compatibility stack
        ('v2', {
            'api_major_version': 'v2'}),
        # test v2.1 base microversion
        ('v2_1', {
            'api_major_version': 'v2.1'}),
        # test v2.18 code without project id
        ('v2_1_noproject_id', {
            'api_major_version': 'v2.1',
            '_use_project_id': False,
            '_additional_fixtures': [
                api_paste_fixture.ApiPasteNoProjectId]})
    ]

    def setUp(self):
        self.flags(use_ipv6=False)
        self.flags(glance_link_prefix=self._get_glance_host(),
                   compute_link_prefix=self._get_host(),
                   group='api')

        # load any additional fixtures specified by the scenario
        for fix in self._additional_fixtures:
            self.useFixture(fix())

        if not self.SUPPORTS_CELLS:
            # NOTE(danms): Disable base automatic DB (and cells) config
            self.USES_DB = False
            self.USES_DB_SELF = True
        # This is to enable the network quota which is being registered
        # based on CONF.enable_network_quota. Need this to test the
        # network quota in quota sample tests.
        self.flags(enable_network_quota=True)
        self.useFixture(fixtures.RegisterNetworkQuota())

        # super class call is delayed here so that we have the right
        # paste and conf before loading all the services, as we can't
        # change these later.
        super(ApiSampleTestBaseV21, self).setUp()

        if not self.SUPPORTS_CELLS:
            self.useFixture(fixtures.Database())
            self.useFixture(fixtures.Database(database='api'))
            self.useFixture(fixtures.DefaultFlavorsFixture())
            self.useFixture(fixtures.SingleCellSimple())

        super(ApiSampleTestBaseV21, self)._setup_services()

        if not self.USE_NEUTRON:
            # self.network is only setup if USE_NEUTRON=False
            self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self)
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        # this is used to generate sample docs
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None

        # NOTE(mikal): this is used to stub away privsep helpers
        def fake_noop(*args, **kwargs):
            return '', ''

        def fake_true(*args, **kwargs):
            return True

        self.stub_out('nova.privsep.linux_net.add_bridge', fake_noop)
        self.stub_out('nova.privsep.linux_net.set_device_mtu', fake_noop)
        self.stub_out('nova.privsep.linux_net.set_device_enabled', fake_noop)
        self.stub_out('nova.privsep.linux_net.set_device_macaddr', fake_noop)
        self.stub_out('nova.privsep.linux_net.routes_show', fake_noop)
        self.stub_out('nova.privsep.linux_net.lookup_ip', fake_noop)
        self.stub_out('nova.privsep.linux_net.change_ip', fake_noop)
        self.stub_out('nova.privsep.linux_net.address_command_deprecated',
                      fake_noop)
        self.stub_out('nova.privsep.linux_net.ipv4_forwarding_check',
                      fake_true)
        self.stub_out('nova.privsep.linux_net._enable_ipv4_forwarding_inner',
                      fake_noop)
        self.stub_out('nova.privsep.linux_net.add_vlan', fake_noop)
        self.stub_out('nova.privsep.linux_net.bridge_setfd', fake_noop)
        self.stub_out('nova.privsep.linux_net.bridge_disable_stp', fake_noop)
        self.stub_out('nova.privsep.linux_net.bridge_add_interface', fake_noop)

        if self.availability_zones:
            self.useFixture(
                fixtures.AvailabilityZoneFixture(self.availability_zones))

    def _setup_services(self):
        pass

    def _setup_scheduler_service(self):
        """Overrides _IntegratedTestBase._setup_scheduler_service to filter
        out the AvailabilityZoneFilter prior to starting the scheduler.
        """
        if self.availability_zones:
            # The test is using fake zones so disable the
            # AvailabilityZoneFilter which is otherwise enabled by default.
            enabled_filters = CONF.filter_scheduler.enabled_filters
            if 'AvailabilityZoneFilter' in enabled_filters:
                enabled_filters.remove('AvailabilityZoneFilter')
                self.flags(enabled_filters=enabled_filters,
                           group='filter_scheduler')
        return super(ApiSampleTestBaseV21, self)._setup_scheduler_service()
