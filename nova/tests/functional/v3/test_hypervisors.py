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

from nova.compute import api as compute_api
from nova.tests.functional.v3 import api_sample_base


class HypervisorsSampleJsonTests(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-hypervisors"

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_search(self):
        response = self._do_get('os-hypervisors/fake/search')
        self._verify_response('hypervisors-search-resp', {}, response, 200)

    def test_hypervisors_servers(self):
        response = self._do_get('os-hypervisors/fake/servers')
        self._verify_response('hypervisors-servers-resp', {}, response, 200)

    def test_hypervisors_detail(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/detail')
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-detail-resp', subs, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-resp', subs, response, 200)

    def test_hypervisors_statistics(self):
        response = self._do_get('os-hypervisors/statistics')
        self._verify_response('hypervisors-statistics-resp', {}, response, 200)

    def test_hypervisors_uptime(self):
        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        self.stubs.Set(compute_api.HostAPI,
                       'get_host_uptime', fake_get_host_uptime)
        hypervisor_id = 1
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)
