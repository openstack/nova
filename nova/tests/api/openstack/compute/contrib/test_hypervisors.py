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

from lxml import etree
from webob import exc

from nova.api.openstack.compute.contrib import hypervisors
from nova import context
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
         disk_available_least=100),
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
         disk_available_least=100)]
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
        self.context = context.get_admin_context()
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
                service=dict(id=1, host='compute1')))

    def test_view_hypervisor_servers(self):
        result = self.controller._view_hypervisor(TEST_HYPERS[0], False,
                                                  TEST_SERVERS)

        self.assertEqual(result, dict(
                id=1,
                hypervisor_hostname="hyper1",
                servers=[
                    dict(name="inst1", uuid="uuid1"),
                    dict(name="inst2", uuid="uuid2"),
                    dict(name="inst3", uuid="uuid3"),
                    dict(name="inst4", uuid="uuid4")]))

    def test_index(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors',
                                      use_admin_context=True)
        result = self.controller.index(req)

        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1, hypervisor_hostname="hyper1"),
                    dict(id=2, hypervisor_hostname="hyper2")]))

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
                         disk_available_least=100),
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
                         disk_available_least=100)]))

    def test_show_noid(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/3')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '3')

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
                    disk_available_least=100)))

    def test_uptime_noid(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/3')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '3')

    def test_uptime_notimplemented(self):
        def fake_get_host_uptime(context, hyp):
            raise exc.HTTPNotImplemented()

        self.stubs.Set(self.controller.host_api, 'get_host_uptime',
                       fake_get_host_uptime)

        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/1')
        self.assertRaises(exc.HTTPNotImplemented,
                          self.controller.uptime, req, '1')

    def test_uptime_implemented(self):
        def fake_get_host_uptime(context, hyp):
            return "fake uptime"

        self.stubs.Set(self.controller.host_api, 'get_host_uptime',
                       fake_get_host_uptime)

        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/1')
        result = self.controller.uptime(req, '1')

        self.assertEqual(result, dict(hypervisor=dict(
                    id=1,
                    hypervisor_hostname="hyper1",
                    uptime="fake uptime")))

    def test_search(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/hyper/search')
        result = self.controller.search(req, 'hyper')

        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1, hypervisor_hostname="hyper1"),
                    dict(id=2, hypervisor_hostname="hyper2")]))

    def test_servers(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/hyper/servers')
        result = self.controller.servers(req, 'hyper')

        self.assertEqual(result, dict(hypervisors=[
                    dict(id=1,
                         hypervisor_hostname="hyper1",
                         servers=[
                            dict(name="inst1", uuid="uuid1"),
                            dict(name="inst3", uuid="uuid3")]),
                    dict(id=2,
                         hypervisor_hostname="hyper2",
                         servers=[
                            dict(name="inst2", uuid="uuid2"),
                            dict(name="inst4", uuid="uuid4")])]))

    def test_statistics(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-hypervisors/statistics')
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


class HypervisorsSerializersTest(test.NoDBTestCase):
    def compare_to_exemplar(self, exemplar, hyper):
        # Check attributes
        for key, value in exemplar.items():
            if key in ('service', 'servers'):
                # These turn into child elements and get tested
                # separately below...
                continue

            self.assertEqual(str(value), hyper.get(key))

        # Check child elements
        required_children = set([child for child in ('service', 'servers')
                                 if child in exemplar])
        for child in hyper:
            self.assertIn(child.tag, required_children)
            required_children.remove(child.tag)

            # Check the node...
            if child.tag == 'service':
                for key, value in exemplar['service'].items():
                    self.assertEqual(str(value), child.get(key))
            elif child.tag == 'servers':
                for idx, grandchild in enumerate(child):
                    self.assertEqual('server', grandchild.tag)
                    for key, value in exemplar['servers'][idx].items():
                        self.assertEqual(str(value), grandchild.get(key))

        # Are they all accounted for?
        self.assertEqual(len(required_children), 0)

    def test_index_serializer(self):
        serializer = hypervisors.HypervisorIndexTemplate()
        exemplar = dict(hypervisors=[
                dict(hypervisor_hostname="hyper1",
                     id=1),
                dict(hypervisor_hostname="hyper2",
                     id=2)])
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisors', tree.tag)
        self.assertEqual(len(exemplar['hypervisors']), len(tree))
        for idx, hyper in enumerate(tree):
            self.assertEqual('hypervisor', hyper.tag)
            self.compare_to_exemplar(exemplar['hypervisors'][idx], hyper)

    def test_detail_serializer(self):
        serializer = hypervisors.HypervisorDetailTemplate()
        exemplar = dict(hypervisors=[
                dict(hypervisor_hostname="hyper1",
                     id=1,
                     vcpus=4,
                     memory_mb=10 * 1024,
                     local_gb=500,
                     vcpus_used=2,
                     memory_mb_used=5 * 1024,
                     local_gb_used=250,
                     hypervisor_type='xen',
                     hypervisor_version=3,
                     free_ram_mb=5 * 1024,
                     free_disk_gb=250,
                     current_workload=2,
                     running_vms=2,
                     cpu_info="json data",
                     disk_available_least=100,
                     service=dict(id=1, host="compute1")),
                dict(hypervisor_hostname="hyper2",
                     id=2,
                     vcpus=4,
                     memory_mb=10 * 1024,
                     local_gb=500,
                     vcpus_used=2,
                     memory_mb_used=5 * 1024,
                     local_gb_used=250,
                     hypervisor_type='xen',
                     hypervisor_version=3,
                     free_ram_mb=5 * 1024,
                     free_disk_gb=250,
                     current_workload=2,
                     running_vms=2,
                     cpu_info="json data",
                     disk_available_least=100,
                     service=dict(id=2, host="compute2"))])
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisors', tree.tag)
        self.assertEqual(len(exemplar['hypervisors']), len(tree))
        for idx, hyper in enumerate(tree):
            self.assertEqual('hypervisor', hyper.tag)
            self.compare_to_exemplar(exemplar['hypervisors'][idx], hyper)

    def test_show_serializer(self):
        serializer = hypervisors.HypervisorTemplate()
        exemplar = dict(hypervisor=dict(
                hypervisor_hostname="hyper1",
                id=1,
                vcpus=4,
                memory_mb=10 * 1024,
                local_gb=500,
                vcpus_used=2,
                memory_mb_used=5 * 1024,
                local_gb_used=250,
                hypervisor_type='xen',
                hypervisor_version=3,
                free_ram_mb=5 * 1024,
                free_disk_gb=250,
                current_workload=2,
                running_vms=2,
                cpu_info="json data",
                disk_available_least=100,
                service=dict(id=1, host="compute1")))
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisor', tree.tag)
        self.compare_to_exemplar(exemplar['hypervisor'], tree)

    def test_uptime_serializer(self):
        serializer = hypervisors.HypervisorUptimeTemplate()
        exemplar = dict(hypervisor=dict(
                hypervisor_hostname="hyper1",
                id=1,
                uptime='fake uptime'))
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisor', tree.tag)
        self.compare_to_exemplar(exemplar['hypervisor'], tree)

    def test_servers_serializer(self):
        serializer = hypervisors.HypervisorServersTemplate()
        exemplar = dict(hypervisors=[
                dict(hypervisor_hostname="hyper1",
                     id=1,
                     servers=[
                        dict(name="inst1",
                             uuid="uuid1"),
                        dict(name="inst2",
                             uuid="uuid2")]),
                dict(hypervisor_hostname="hyper2",
                     id=2,
                     servers=[
                        dict(name="inst3",
                             uuid="uuid3"),
                        dict(name="inst4",
                             uuid="uuid4")])])
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisors', tree.tag)
        self.assertEqual(len(exemplar['hypervisors']), len(tree))
        for idx, hyper in enumerate(tree):
            self.assertEqual('hypervisor', hyper.tag)
            self.compare_to_exemplar(exemplar['hypervisors'][idx], hyper)

    def test_statistics_serializer(self):
        serializer = hypervisors.HypervisorStatisticsTemplate()
        exemplar = dict(hypervisor_statistics=dict(
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
                disk_available_least=200))
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)

        self.assertEqual('hypervisor_statistics', tree.tag)
        self.compare_to_exemplar(exemplar['hypervisor_statistics'], tree)
