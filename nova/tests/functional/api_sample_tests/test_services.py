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

from oslo_config import cfg
from oslo_utils import fixture as utils_fixture

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack.compute import test_services


CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ServicesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "os-services"
    microversion = None

    def _get_flags(self):
        f = super(ServicesJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.services.Services')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.extended_services_delete.'
                      'Extended_services_delete')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.extended_services.Extended_services')
        return f

    def setUp(self):
        super(ServicesJsonTest, self).setUp()
        self.api.microversion = self.microversion
        self.stub_out("nova.db.service_get_all",
                      test_services.fake_db_api_service_get_all)
        self.stub_out("nova.db.service_get_by_host_and_binary",
                      test_services.fake_service_get_by_host_binary)
        self.stub_out("nova.db.service_update",
                      test_services.fake_service_update)
        self.useFixture(utils_fixture.TimeFixture(test_services.fake_utcnow()))

    def test_services_list(self):
        """Return a list of all agent builds."""
        response = self._do_get('os-services')
        subs = {'binary': 'nova-compute',
                'host': 'host1',
                'zone': 'nova',
                'status': 'disabled',
                'state': 'up'}
        self._verify_response('services-list-get-resp', subs, response, 200)

    def test_service_enable(self):
        """Enable an existing agent build."""
        subs = {"host": "host1",
                'binary': 'nova-compute'}
        response = self._do_put('os-services/enable',
                                'service-enable-put-req', subs)
        self._verify_response('service-enable-put-resp', subs, response, 200)

    def test_service_disable(self):
        """Disable an existing agent build."""
        subs = {"host": "host1",
                'binary': 'nova-compute'}
        response = self._do_put('os-services/disable',
                                'service-disable-put-req', subs)
        self._verify_response('service-disable-put-resp', subs, response, 200)

    def test_service_disable_log_reason(self):
        """Disable an existing service and log the reason."""
        subs = {"host": "host1",
                'binary': 'nova-compute',
                'disabled_reason': 'test2'}
        response = self._do_put('os-services/disable-log-reason',
                                'service-disable-log-put-req', subs)
        self._verify_response('service-disable-log-put-resp',
                              subs, response, 200)

    def test_service_delete(self):
        """Delete an existing service."""
        response = self._do_delete('os-services/1')
        self.assertEqual(204, response.status_code)
        self.assertEqual("", response.content)


class ServicesV211JsonTest(ServicesJsonTest):
    microversion = '2.11'
    # NOTE(gryf): There is no need to run those tests on v2 API. Only
    # scenarios for v2_11 will be run.
    scenarios = [('v2_11', {'api_major_version': 'v2.1'})]

    def test_services_list(self):
        """Return a list of all agent builds."""
        response = self._do_get('os-services')
        subs = {'binary': 'nova-compute',
                'host': 'host1',
                'zone': 'nova',
                'forced_down': 'false',
                'status': 'disabled',
                'state': 'up'}
        self._verify_response('services-list-get-resp', subs, response, 200)

    def test_force_down(self):
        """Set forced_down flag"""
        subs = {"host": 'host1',
                'binary': 'nova-compute',
                'forced_down': 'true'}
        response = self._do_put('os-services/force-down',
                                'service-force-down-put-req', subs)
        self._verify_response('service-force-down-put-resp', subs,
                              response, 200)
