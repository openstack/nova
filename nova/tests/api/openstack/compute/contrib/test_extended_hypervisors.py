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

from nova.api.openstack.compute.contrib import hypervisors
from nova.tests.api.openstack.compute.contrib import test_hypervisors
from nova.tests.api.openstack import fakes


class ExtendedHypervisorsTest(test_hypervisors.HypervisorsTest):
    def setUp(self):
        super(ExtendedHypervisorsTest, self).setUp()
        self.ext_mgr.extensions['os-extended-hypervisors'] = True
        self.controller = hypervisors.HypervisorsController(self.ext_mgr)

    def test_view_hypervisor_detail_noservers(self):
        result = self.controller._view_hypervisor(
                                   test_hypervisors.TEST_HYPERS[0], True)

        self.assertEqual(result, dict(
                id=1,
                hypervisor_hostname="hyper1",
                vcpus=4,
                memory_mb=10 * 1024,
                local_gb=250,
                vcpus_used=2,
                memory_mb_used=5 * 1024,
                local_gb_used=125,
                hypervisor_type="xen",
                hypervisor_version=3,
                free_ram_mb=5 * 1024,
                free_disk_gb=125,
                current_workload=2,
                running_vms=2,
                cpu_info='cpu_info',
                disk_available_least=100,
                host_ip='1.1.1.1',
                service=dict(id=1, host='compute1')))

    def test_detail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/detail',
                                      use_admin_context=True)
        result = self.controller.detail(req)

        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1,
                         service=dict(id=1, host="compute1"),
                         vcpus=4,
                         memory_mb=10 * 1024,
                         local_gb=250,
                         vcpus_used=2,
                         memory_mb_used=5 * 1024,
                         local_gb_used=125,
                         hypervisor_type="xen",
                         hypervisor_version=3,
                         hypervisor_hostname="hyper1",
                         free_ram_mb=5 * 1024,
                         free_disk_gb=125,
                         current_workload=2,
                         running_vms=2,
                         cpu_info='cpu_info',
                         disk_available_least=100,
                         host_ip='1.1.1.1'),
                    dict(id=2,
                         service=dict(id=2, host="compute2"),
                         vcpus=4,
                         memory_mb=10 * 1024,
                         local_gb=250,
                         vcpus_used=2,
                         memory_mb_used=5 * 1024,
                         local_gb_used=125,
                         hypervisor_type="xen",
                         hypervisor_version=3,
                         hypervisor_hostname="hyper2",
                         free_ram_mb=5 * 1024,
                         free_disk_gb=125,
                         current_workload=2,
                         running_vms=2,
                         cpu_info='cpu_info',
                         disk_available_least=100,
                         host_ip='2.2.2.2')]))

    def test_show_withid(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/1')
        result = self.controller.show(req, '1')

        self.assertEqual(result, dict(hypervisor=dict(
                    id=1,
                    service=dict(id=1, host="compute1"),
                    vcpus=4,
                    memory_mb=10 * 1024,
                    local_gb=250,
                    vcpus_used=2,
                    memory_mb_used=5 * 1024,
                    local_gb_used=125,
                    hypervisor_type="xen",
                    hypervisor_version=3,
                    hypervisor_hostname="hyper1",
                    free_ram_mb=5 * 1024,
                    free_disk_gb=125,
                    current_workload=2,
                    running_vms=2,
                    cpu_info='cpu_info',
                    disk_available_least=100,
                    host_ip='1.1.1.1')))
