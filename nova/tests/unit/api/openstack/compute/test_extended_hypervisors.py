# Copyright 2014 IBM Corp.
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

import copy

import mock

from nova.api.openstack.compute import hypervisors \
        as hypervisors_v21
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack.compute import test_hypervisors
from nova.tests.unit.api.openstack import fakes


def fake_compute_node_get(context, compute_id):
    for hyper in test_hypervisors.TEST_HYPERS_OBJ:
        if hyper.id == int(compute_id):
            return hyper
    raise exception.ComputeHostNotFound(host=compute_id)


def fake_compute_node_get_all(context, limit=None, marker=None):
    return test_hypervisors.TEST_HYPERS_OBJ


def fake_service_get_by_compute_host(context, host):
    for service in test_hypervisors.TEST_SERVICES:
        if service.host == host:
            return service


class ExtendedHypervisorsTestV21(test.NoDBTestCase):
    DETAIL_HYPERS_DICTS = copy.deepcopy(test_hypervisors.TEST_HYPERS)
    del DETAIL_HYPERS_DICTS[0]['service_id']
    del DETAIL_HYPERS_DICTS[1]['service_id']
    del DETAIL_HYPERS_DICTS[0]['host']
    del DETAIL_HYPERS_DICTS[1]['host']
    del DETAIL_HYPERS_DICTS[0]['uuid']
    del DETAIL_HYPERS_DICTS[1]['uuid']
    DETAIL_HYPERS_DICTS[0].update({'state': 'up',
                           'status': 'enabled',
                           'service': dict(id=1, host='compute1',
                                        disabled_reason=None)})
    DETAIL_HYPERS_DICTS[1].update({'state': 'up',
                           'status': 'enabled',
                           'service': dict(id=2, host='compute2',
                                        disabled_reason=None)})

    def _set_up_controller(self):
        self.controller = hypervisors_v21.HypervisorsController()

    def _get_request(self):
        return fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/detail',
                                       use_admin_context=True)

    def setUp(self):
        super(ExtendedHypervisorsTestV21, self).setUp()
        self._set_up_controller()

    def test_view_hypervisor_detail_noservers(self):
        with mock.patch.object(self.controller.servicegroup_api,
                               'service_is_up',
                               return_value=True) as mock_service_is_up:
            req = self._get_request()
            result = self.controller._view_hypervisor(
                test_hypervisors.TEST_HYPERS_OBJ[0],
                test_hypervisors.TEST_SERVICES[0], True, req)

            self.assertEqual(self.DETAIL_HYPERS_DICTS[0], result)
            self.assertTrue(mock_service_is_up.called)

    @mock.patch.object(objects.Service, 'get_by_compute_host',
                       side_effect=fake_service_get_by_compute_host)
    def test_detail(self, mock_get_by_host):
        with test.nested(
            mock.patch.object(self.controller.host_api, 'compute_node_get_all',
                              side_effect=fake_compute_node_get_all),
            mock.patch.object(self.controller.servicegroup_api,
                              'service_is_up', return_value=True),
        ) as (mock_node_get_all, mock_service_is_up):
            req = self._get_request()
            result = self.controller.detail(req)

            self.assertEqual(dict(hypervisors=self.DETAIL_HYPERS_DICTS),
                             result)
            self.assertTrue(mock_service_is_up.called)
            self.assertTrue(mock_get_by_host.called)
            self.assertTrue(mock_node_get_all.called)

    @mock.patch.object(objects.Service, 'get_by_compute_host',
                       side_effect=fake_service_get_by_compute_host)
    def test_show_withid(self, mock_get_by_host):
        with test.nested(
            mock.patch.object(self.controller.host_api, 'compute_node_get',
                              side_effect=fake_compute_node_get),
            mock.patch.object(self.controller.servicegroup_api,
                              'service_is_up', return_value=True),
        ) as (mock_node_get, mock_service_is_up):
            req = self._get_request()
            result = self.controller.show(req, '1')

            self.assertEqual(dict(hypervisor=self.DETAIL_HYPERS_DICTS[0]),
                             result)
            self.assertTrue(mock_service_is_up.called)
            self.assertTrue(mock_get_by_host.called)
            self.assertTrue(mock_node_get.called)
