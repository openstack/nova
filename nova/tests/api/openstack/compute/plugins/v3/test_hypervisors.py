# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
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

from webob import exc

from nova.api.openstack.compute.plugins.v3 import hypervisors
from nova import db
from nova.db.sqlalchemy import api as db_api
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


TEST_HYPERS = [
    dict(id=1,
         service_id=1,
         service=dict(id=1,
                      host="compute1",
                      binary="nova-compute",
                      topic="compute_topic",
                      report_count=5,
                      disabled=False,
                      availability_zone="nova"),
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
         service_id=2,
         service=dict(id=2,
                      host="compute2",
                      binary="nova-compute",
                      topic="compute_topic",
                      report_count=5,
                      disabled=False,
                      availability_zone="nova"),
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
         host_ip='2.2.2.2')]
TEST_SERVERS = [dict(name="inst1", uuid="uuid1", host="compute1"),
                dict(name="inst2", uuid="uuid2", host="compute2"),
                dict(name="inst3", uuid="uuid3", host="compute1"),
                dict(name="inst4", uuid="uuid4", host="compute2")]


@db_api.require_admin_context
def fake_compute_node_get_all(context):
    return TEST_HYPERS


def fake_compute_node_search_by_hypervisor(context, hypervisor_re):
    return TEST_HYPERS


def fake_compute_node_get(context, compute_id):
    for hyper in TEST_HYPERS:
        if hyper['id'] == compute_id:
            return hyper
    raise exception.ComputeHostNotFound(host=compute_id)


def fake_compute_node_statistics(context):
    result = dict(
        count=0,
        vcpus=0,
        memory_mb=0,
        local_gb=0,
        vcpus_used=0,
        memory_mb_used=0,
        local_gb_used=0,
        free_ram_mb=0,
        free_disk_gb=0,
        current_workload=0,
        running_vms=0,
        disk_available_least=0,
        )

    for hyper in TEST_HYPERS:
        for key in result:
            if key == 'count':
                result[key] += 1
            else:
                result[key] += hyper[key]

    return result


def fake_instance_get_all_by_host(context, host):
    results = []
    for inst in TEST_SERVERS:
        if inst['host'] == host:
            results.append(inst)
    return results


class HypervisorsTest(test.NoDBTestCase):
    def setUp(self):
        super(HypervisorsTest, self).setUp()
        self.controller = hypervisors.HypervisorsController()

        self.stubs.Set(db, 'compute_node_get_all', fake_compute_node_get_all)
        self.stubs.Set(db, 'compute_node_search_by_hypervisor',
                       fake_compute_node_search_by_hypervisor)
        self.stubs.Set(db, 'compute_node_get',
                       fake_compute_node_get)
        self.stubs.Set(db, 'compute_node_statistics',
                       fake_compute_node_statistics)
        self.stubs.Set(db, 'instance_get_all_by_host',
                       fake_instance_get_all_by_host)

    def test_view_hypervisor_nodetail_noservers(self):
        result = self.controller._view_hypervisor(TEST_HYPERS[0], False)

        self.assertEqual(result, dict(id=1, hypervisor_hostname="hyper1"))

    def test_view_hypervisor_detail_noservers(self):
        result = self.controller._view_hypervisor(TEST_HYPERS[0], True)

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

    def test_view_hypervisor_servers(self):
        result = self.controller._view_hypervisor(TEST_HYPERS[0], False,
                                                  TEST_SERVERS)

        self.assertEqual(result, dict(
                id=1,
                hypervisor_hostname="hyper1",
                servers=[
                    dict(name="inst1", id="uuid1"),
                    dict(name="inst2", id="uuid2"),
                    dict(name="inst3", id="uuid3"),
                    dict(name="inst4", id="uuid4")]))

    def test_index(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors',
                                        use_admin_context=True)
        result = self.controller.index(req)

        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1, hypervisor_hostname="hyper1"),
                    dict(id=2, hypervisor_hostname="hyper2")]))

    def test_index_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_detail(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/detail',
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

    def test_detail_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/detail')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.detail, req)

    def test_show_noid(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/3',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '3')

    def test_show_non_integer_id(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/abc',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, 'abc')

    def test_show_withid(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1',
                                        use_admin_context=True)
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

    def test_show_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show, req, '1')

    def test_uptime_noid(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/3',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '3')

    def test_uptime_notimplemented(self):
        def fake_get_host_uptime(context, hyp):
            raise exc.HTTPNotImplemented()

        self.stubs.Set(self.controller.host_api, 'get_host_uptime',
                       fake_get_host_uptime)

        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotImplemented,
                          self.controller.uptime, req, '1')

    def test_uptime_implemented(self):
        def fake_get_host_uptime(context, hyp):
            return "fake uptime"

        self.stubs.Set(self.controller.host_api, 'get_host_uptime',
                       fake_get_host_uptime)

        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1',
                                        use_admin_context=True)
        result = self.controller.uptime(req, '1')

        self.assertEqual(result, dict(hypervisor=dict(
                    id=1,
                    hypervisor_hostname="hyper1",
                    uptime="fake uptime")))

    def test_uptime_non_integer_id(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/abc/uptime',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.uptime, req, 'abc')

    def test_uptime_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1/uptime')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.uptime, req, '1')

    def test_search(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/search?query=hyper',
                                        use_admin_context=True)
        result = self.controller.search(req)
        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1, hypervisor_hostname="hyper1"),
                    dict(id=2, hypervisor_hostname="hyper2")]))

    def test_search_non_exist(self):
        def fake_compute_node_search_by_hypervisor_return_empty(context,
                                                                hypervisor_re):
            return []
        self.stubs.Set(db, 'compute_node_search_by_hypervisor',
                       fake_compute_node_search_by_hypervisor_return_empty)
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/search?query=a',
                                        use_admin_context=True)
        result = self.controller.search(req)
        self.assertEqual(result, dict(hypervisors=[]))

    def test_search_without_query(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/search',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest, self.controller.search, req)

    def test_servers(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1/servers',
                                        use_admin_context=True)
        result = self.controller.servers(req, '1')
        self.assertEqual(result, dict(hypervisor=
                    dict(id=1,
                         hypervisor_hostname="hyper1",
                         servers=[
                            dict(name="inst1", id="uuid1"),
                            dict(name="inst3", id="uuid3")])))

    def test_servers_non_id(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/3/servers',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.servers, req, '3')

    def test_servers_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1/servers')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.servers, req, '1')

    def test_servers_return_empty(self):
        def fake_instance_get_all_by_host_return_empty(context, hypervisor_re):
            return []
        self.stubs.Set(db, 'instance_get_all_by_host',
                       fake_instance_get_all_by_host_return_empty)
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1/servers',
                                        use_admin_context=True)
        result = self.controller.servers(req, '1')
        self.assertEqual(result, dict(hypervisor=
                    dict(id=1,
                         hypervisor_hostname="hyper1",
                         servers=[])))

    def test_servers_with_non_integer_hypervisor_id(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/abc/servers',
                                        use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound,
                          self.controller.servers, req, 'abc')

    def test_statistics(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/statistics',
                                        use_admin_context=True)
        result = self.controller.statistics(req)

        self.assertEqual(result, dict(hypervisor_statistics=dict(
                    count=2,
                    vcpus=8,
                    memory_mb=20 * 1024,
                    local_gb=500,
                    vcpus_used=4,
                    memory_mb_used=10 * 1024,
                    local_gb_used=250,
                    free_ram_mb=10 * 1024,
                    free_disk_gb=250,
                    current_workload=4,
                    running_vms=4,
                    disk_available_least=200)))

    def test_statistics_non_admin(self):
        req = fakes.HTTPRequestV3.blank('/os-hypervisors/statistics')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.statistics, req)
