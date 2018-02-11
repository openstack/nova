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

from oslo_utils import fixture as utils_fixture

from nova import exception
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack.compute import test_services
from nova.tests.unit.objects import test_compute_node
from nova.tests.unit.objects import test_host_mapping


class ServicesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-services"
    microversion = None

    def setUp(self):
        super(ServicesJsonTest, self).setUp()
        self.api.microversion = self.microversion
        self.stub_out("nova.db.api.service_get_all",
                      test_services.fake_db_api_service_get_all)
        self.stub_out("nova.db.api.service_get_by_host_and_binary",
                      test_services.fake_service_get_by_host_binary)
        self.stub_out("nova.db.api.service_update",
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
        self.assertEqual("", response.text)


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


class ServicesV253JsonTest(ServicesV211JsonTest):
    microversion = '2.53'
    scenarios = [('v2_53', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServicesV253JsonTest, self).setUp()

        def db_service_get_by_uuid(ctxt, service_uuid):
            for svc in test_services.fake_services_list:
                if svc['uuid'] == service_uuid:
                    return svc
            raise exception.ServiceNotFound(service_id=service_uuid)

        def fake_cn_get_all_by_host(context, host):
            cn = test_compute_node.fake_compute_node
            cn['uuid'] = test_services.FAKE_UUID_COMPUTE_HOST1
            cn['host'] = host
            return [cn]

        def fake_hm_get_by_host(context, host):
            hm = test_host_mapping.get_db_mapping()
            hm['host'] = host
            return hm

        def fake_hm_destroy(context, host):
            return 1

        self.stub_out('nova.db.api.service_get_by_uuid',
                      db_service_get_by_uuid)
        self.stub_out('nova.db.api.compute_node_get_all_by_host',
            fake_cn_get_all_by_host)
        self.stub_out(
            'nova.objects.host_mapping.HostMapping._get_by_host_from_db',
                fake_hm_get_by_host)
        self.stub_out('nova.objects.host_mapping.HostMapping._destroy_in_db',
            fake_hm_destroy)

    def test_service_enable(self):
        """Enable an existing service."""
        response = self._do_put(
            'os-services/%s' % test_services.FAKE_UUID_COMPUTE_HOST1,
            'service-enable-put-req', subs={})
        self._verify_response('service-enable-put-resp', {}, response, 200)

    def test_service_disable(self):
        """Disable an existing service."""
        response = self._do_put(
            'os-services/%s' % test_services.FAKE_UUID_COMPUTE_HOST1,
            'service-disable-put-req', subs={})
        self._verify_response('service-disable-put-resp', {}, response, 200)

    def test_service_disable_log_reason(self):
        """Disable an existing service and log the reason."""
        subs = {'disabled_reason': 'maintenance'}
        response = self._do_put(
            'os-services/%s' % test_services.FAKE_UUID_COMPUTE_HOST1,
            'service-disable-log-put-req', subs)
        self._verify_response('service-disable-log-put-resp',
                              subs, response, 200)

    def test_service_delete(self):
        """Delete an existing service."""
        response = self._do_delete(
            'os-services/%s' % test_services.FAKE_UUID_COMPUTE_HOST1)
        self.assertEqual(204, response.status_code)
        self.assertEqual("", response.text)

    def test_force_down(self):
        """Set forced_down flag"""
        subs = {'forced_down': 'true'}
        response = self._do_put(
            'os-services/%s' % test_services.FAKE_UUID_COMPUTE_HOST1,
            'service-force-down-put-req', subs)
        self._verify_response('service-force-down-put-resp', subs,
                              response, 200)
