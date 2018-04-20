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

import mock

from nova.cells import utils as cells_utils
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base


class HypervisorsSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-hypervisors"

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_search(self):
        response = self._do_get('os-hypervisors/fake/search')
        self._verify_response('hypervisors-search-resp', {}, response, 200)

    def test_hypervisors_without_servers(self):
        response = self._do_get('os-hypervisors/fake/servers')
        self._verify_response('hypervisors-without-servers-resp',
                              {}, response, 200)

    @mock.patch("nova.compute.api.HostAPI.instance_get_all_by_host")
    def test_hypervisors_with_servers(self, mock_instance_get):
        instance = [
            {
                "deleted": None,
                "name": "test_server1",
                "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            },
            {
                "deleted": None,
                "name": "test_server2",
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            }]

        mock_instance_get.return_value = instance
        response = self._do_get('os-hypervisors/fake/servers')
        self._verify_response('hypervisors-with-servers-resp', {},
                              response, 200)

    def test_hypervisors_detail(self):
        hypervisor_id = '1'
        subs = {
            'hypervisor_id': hypervisor_id,
            'service_id': '[0-9]+',
        }
        response = self._do_get('os-hypervisors/detail')
        self._verify_response('hypervisors-detail-resp', subs, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = '1'
        subs = {
            'hypervisor_id': hypervisor_id,
            'service_id': '[0-9]+',
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        self._verify_response('hypervisors-show-resp', subs, response, 200)

    def test_hypervisors_statistics(self):
        response = self._do_get('os-hypervisors/statistics')
        self._verify_response('hypervisors-statistics-resp', {}, response, 200)

    def test_hypervisors_uptime(self):
        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        self.stub_out('nova.compute.api.HostAPI.get_host_uptime',
                      fake_get_host_uptime)
        hypervisor_id = '1'
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


@mock.patch("nova.servicegroup.API.service_is_up", return_value=True)
class HypervisorsCellsSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-hypervisors"

    def setUp(self):
        self.flags(enable=True, cell_type='api', group='cells')
        super(HypervisorsCellsSampleJsonTests, self).setUp()

    def test_hypervisor_uptime(self, mocks):
        fake_hypervisor = objects.ComputeNode(id=1, host='fake-mini',
                                              hypervisor_hostname='fake-mini')

        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        def fake_compute_node_get(self, context, hyp):
            return fake_hypervisor

        def fake_service_get_by_compute_host(self, context, host):
            return cells_utils.ServiceProxy(
                objects.Service(id=1, host='fake-mini', disabled=False,
                                disabled_reason=None),
                'cell1')

        self.stub_out(
            'nova.compute.cells_api.HostAPI.compute_node_get',
            fake_compute_node_get)
        self.stub_out(
            'nova.compute.cells_api.HostAPI.service_get_by_compute_host',
            fake_service_get_by_compute_host)
        self.stub_out(
            'nova.compute.cells_api.HostAPI.get_host_uptime',
            fake_get_host_uptime)

        hypervisor_id = fake_hypervisor.id
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {'hypervisor_id': str(hypervisor_id)}
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


class HypervisorsSampleJson228Tests(HypervisorsSampleJsonTests):
    microversion = '2.28'
    scenarios = [('v2_28', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(HypervisorsSampleJson228Tests, self).setUp()
        self.api.microversion = self.microversion


class HypervisorsSampleJson233Tests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-hypervisors"
    microversion = '2.33'
    scenarios = [('v2_33', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(HypervisorsSampleJson233Tests, self).setUp()
        self.api.microversion = self.microversion
        # Start a new compute service to fake a record with hypervisor id=2
        # for pagination test.
        self.start_service('compute', host='host1')

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors?limit=1&marker=1')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_detail(self):
        subs = {
            'hypervisor_id': '2',
            'host': 'host1',
            'host_name': 'host1'
        }
        response = self._do_get('os-hypervisors/detail?limit=1&marker=1')
        self._verify_response('hypervisors-detail-resp', subs, response, 200)
