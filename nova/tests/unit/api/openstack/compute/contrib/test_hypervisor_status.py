# Copyright 2014 Intel Corp.
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

from nova.api.openstack.compute.contrib import hypervisors as hypervisors_v2
from nova.api.openstack.compute.plugins.v3 import hypervisors \
    as hypervisors_v21
from nova.api.openstack import extensions
from nova import test
from nova.tests.unit.api.openstack.compute.contrib import test_hypervisors

TEST_HYPER = dict(test_hypervisors.TEST_HYPERS[0],
                  service=dict(id=1,
                      host="compute1",
                      binary="nova-compute",
                      topic="compute_topic",
                      report_count=5,
                      disabled=False,
                      disabled_reason=None,
                      availability_zone="nova"),
                  )


class HypervisorStatusTestV21(test.NoDBTestCase):
    def _prepare_extension(self):
        self.controller = hypervisors_v21.HypervisorsController()
        self.controller.servicegroup_api.service_is_up = mock.MagicMock(
            return_value=True)

    def test_view_hypervisor_service_status(self):
        self._prepare_extension()
        result = self.controller._view_hypervisor(
            TEST_HYPER, False)
        self.assertEqual('enabled', result['status'])
        self.assertEqual('up', result['state'])
        self.assertEqual('enabled', result['status'])

        self.controller.servicegroup_api.service_is_up.return_value = False
        result = self.controller._view_hypervisor(
            TEST_HYPER, False)
        self.assertEqual('down', result['state'])

        hyper = copy.deepcopy(TEST_HYPER)
        hyper['service']['disabled'] = True
        result = self.controller._view_hypervisor(hyper, False)
        self.assertEqual('disabled', result['status'])

    def test_view_hypervisor_detail_status(self):
        self._prepare_extension()

        result = self.controller._view_hypervisor(
            TEST_HYPER, True)

        self.assertEqual('enabled', result['status'])
        self.assertEqual('up', result['state'])
        self.assertIsNone(result['service']['disabled_reason'])

        self.controller.servicegroup_api.service_is_up.return_value = False
        result = self.controller._view_hypervisor(
            TEST_HYPER, True)
        self.assertEqual('down', result['state'])

        hyper = copy.deepcopy(TEST_HYPER)
        hyper['service']['disabled'] = True
        hyper['service']['disabled_reason'] = "fake"
        result = self.controller._view_hypervisor(hyper, True)
        self.assertEqual('disabled', result['status'],)
        self.assertEqual('fake', result['service']['disabled_reason'])


class HypervisorStatusTestV2(HypervisorStatusTestV21):
    def _prepare_extension(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {}
        ext_mgr.extensions['os-hypervisor-status'] = True
        self.controller = hypervisors_v2.HypervisorsController(ext_mgr)
        self.controller.servicegroup_api.service_is_up = mock.MagicMock(
            return_value=True)
