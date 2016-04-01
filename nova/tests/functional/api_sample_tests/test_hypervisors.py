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
from oslo_config import cfg

from nova.cells import utils as cells_utils
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class HypervisorsSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "os-hypervisors"

    def _get_flags(self):
        f = super(HypervisorsSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.hypervisors.Hypervisors')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_hypervisors.'
            'Extended_hypervisors')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.hypervisor_status.'
            'Hypervisor_status')
        return f

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
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/detail')
        self._verify_response('hypervisors-detail-resp', subs, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = '1'
        subs = {
            'hypervisor_id': hypervisor_id
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
    extension_name = "os-hypervisors"

    def _get_flags(self):
        f = super(HypervisorsCellsSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.hypervisors.Hypervisors')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.hypervisor_status.'
            'Hypervisor_status')
        return f

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
