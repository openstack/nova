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
        host = 'host1'
        self.start_service('compute', host=host)

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors?limit=1&marker=1')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_detail(self):
        subs = {
            'hypervisor_id': '2',
            'host': 'host1',
            'host_name': 'host1',
            'service_id': '[0-9]+',
        }
        response = self._do_get('os-hypervisors/detail?limit=1&marker=1')
        self._verify_response('hypervisors-detail-resp', subs, response, 200)


class HypervisorsSampleJson253Tests(HypervisorsSampleJson228Tests):
    microversion = '2.53'
    scenarios = [('v2_53', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(HypervisorsSampleJson253Tests, self).setUp()
        self.compute_node_1 = self.compute.service_ref.compute_node

    def generalize_subs(self, subs, vanilla_regexes):
        """Give the test a chance to modify subs after the server response
        was verified, and before the on-disk doc/api_samples file is checked.
        """
        # When comparing the template to the sample we just care that the
        # hypervisor id and service id are UUIDs.
        subs['hypervisor_id'] = vanilla_regexes['uuid']
        subs['service_id'] = vanilla_regexes['uuid']
        return subs

    def test_hypervisors_list(self):
        # Start another compute service to get a 2nd compute for paging tests.
        compute_node_2 = self.start_service(
            'compute', host='host2').service_ref.compute_node
        marker = self.compute_node_1.uuid
        response = self._do_get('os-hypervisors?limit=1&marker=%s' % marker)
        subs = {'hypervisor_id': compute_node_2.uuid}
        self._verify_response('hypervisors-list-resp', subs, response, 200)

    def test_hypervisors_detail(self):
        # Start another compute service to get a 2nd compute for paging tests.
        host = 'host2'
        service_2 = self.start_service('compute', host=host).service_ref
        compute_node_2 = service_2.compute_node
        marker = self.compute_node_1.uuid
        subs = {
            'hypervisor_id': compute_node_2.uuid,
            'service_id': service_2.uuid
        }
        response = self._do_get('os-hypervisors/detail?limit=1&marker=%s' %
                                marker)
        self._verify_response('hypervisors-detail-resp', subs, response, 200)

    @mock.patch("nova.compute.api.HostAPI.instance_get_all_by_host")
    def test_hypervisors_detail_with_servers(self, instance_get_all_by_host):
        """List hypervisors with details and with hosted servers."""
        instances = [
            {
                "name": "test_server1",
                "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            },
            {
                "name": "test_server2",
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            }]
        instance_get_all_by_host.return_value = instances
        response = self._do_get('os-hypervisors/detail?with_servers=1')
        subs = {
            'hypervisor_id': self.compute_node_1.uuid,
            'service_id': self.compute.service_ref.uuid,
        }
        self._verify_response('hypervisors-detail-with-servers-resp',
                              subs, response, 200)

    def test_hypervisors_search(self):
        """The search route is deprecated in 2.53 and is now a query parameter
        on the GET /os-hypervisors API.
        """
        response = self._do_get(
            'os-hypervisors?hypervisor_hostname_pattern=fake')
        subs = {'hypervisor_id': self.compute_node_1.uuid}
        self._verify_response('hypervisors-search-resp', subs, response, 200)

    @mock.patch("nova.compute.api.HostAPI.instance_get_all_by_host")
    def test_hypervisors_with_servers(self, instance_get_all_by_host):
        """The servers route is deprecated in 2.53 and is now a query parameter
        on the GET /os-hypervisors API.
        """
        instances = [
            {
                "name": "test_server1",
                "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            },
            {
                "name": "test_server2",
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            }]
        instance_get_all_by_host.return_value = instances
        response = self._do_get('os-hypervisors?with_servers=true')
        subs = {'hypervisor_id': self.compute_node_1.uuid}
        self._verify_response('hypervisors-with-servers-resp', subs,
                              response, 200)

    def test_hypervisors_without_servers(self):
        # This is the same as GET /os-hypervisors in 2.53 which is covered by
        # test_hypervisors_list already.
        pass

    def test_hypervisors_uptime(self):
        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        self.stub_out('nova.compute.api.HostAPI.get_host_uptime',
                      fake_get_host_uptime)
        hypervisor_id = self.compute_node_1.uuid
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = self.compute_node_1.uuid
        subs = {
            'hypervisor_id': hypervisor_id,
            'service_id': self.compute.service_ref.uuid,
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        self._verify_response('hypervisors-show-resp', subs, response, 200)

    @mock.patch("nova.compute.api.HostAPI.instance_get_all_by_host")
    def test_hypervisors_show_with_servers(self, instance_get_all_by_host):
        """Tests getting details for a specific hypervisor and including the
        hosted servers in the response.
        """
        instances = [
            {
                "name": "test_server1",
                "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            },
            {
                "name": "test_server2",
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            }]
        instance_get_all_by_host.return_value = instances
        hypervisor_id = self.compute_node_1.uuid
        subs = {
            'hypervisor_id': hypervisor_id,
            'service_id': self.compute.service_ref.uuid,
        }
        response = self._do_get('os-hypervisors/%s?with_servers=1' %
                                hypervisor_id)
        self._verify_response('hypervisors-show-with-servers-resp', subs,
                              response, 200)
