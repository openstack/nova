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

import copy

import mock
import netaddr
from oslo_serialization import jsonutils
import six
from webob import exc

from nova.api.openstack.compute import hypervisors \
        as hypervisors_v21
from nova.cells import utils as cells_utils
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids

CPU_INFO = """
{"arch": "x86_64",
"vendor": "fake",
"topology": {"cores": 1, "threads": 1, "sockets": 1},
"features": [],
"model": ""}"""

TEST_HYPERS = [
    dict(id=1,
         uuid=uuids.hyper1,
         service_id=1,
         host="compute1",
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
         cpu_info=CPU_INFO,
         disk_available_least=100,
         host_ip=netaddr.IPAddress('1.1.1.1')),
    dict(id=2,
         uuid=uuids.hyper2,
         service_id=2,
         host="compute2",
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
         cpu_info=CPU_INFO,
         disk_available_least=100,
         host_ip=netaddr.IPAddress('2.2.2.2'))]


TEST_SERVICES = [
    objects.Service(id=1,
                    uuid=uuids.service1,
                    host="compute1",
                    binary="nova-compute",
                    topic="compute_topic",
                    report_count=5,
                    disabled=False,
                    disabled_reason=None,
                    availability_zone="nova"),
    objects.Service(id=2,
                    uuid=uuids.service2,
                    host="compute2",
                    binary="nova-compute",
                    topic="compute_topic",
                    report_count=5,
                    disabled=False,
                    disabled_reason=None,
                    availability_zone="nova"),
]

TEST_HYPERS_OBJ = [objects.ComputeNode(**hyper_dct)
                   for hyper_dct in TEST_HYPERS]

TEST_HYPERS[0].update({'service': TEST_SERVICES[0]})
TEST_HYPERS[1].update({'service': TEST_SERVICES[1]})

TEST_SERVERS = [dict(name="inst1", uuid=uuids.instance_1, host="compute1"),
                dict(name="inst2", uuid=uuids.instance_2, host="compute2"),
                dict(name="inst3", uuid=uuids.instance_3, host="compute1"),
                dict(name="inst4", uuid=uuids.instance_4, host="compute2")]


def fake_compute_node_get_all(context, limit=None, marker=None):
    if marker in ['99999', uuids.invalid_marker]:
        raise exception.MarkerNotFound(marker)
    marker_found = True if marker is None else False
    output = []
    for hyper in TEST_HYPERS_OBJ:
        # Starting with the 2.53 microversion, the marker is a uuid.
        if not marker_found and marker in (str(hyper.id), hyper.uuid):
            marker_found = True
        elif marker_found:
            if limit is None or len(output) < int(limit):
                output.append(hyper)
    return output


def fake_compute_node_search_by_hypervisor(context, hypervisor_re):
    return TEST_HYPERS_OBJ


def fake_compute_node_get(context, compute_id):
    for hyper in TEST_HYPERS_OBJ:
        if hyper.uuid == compute_id or hyper.id == int(compute_id):
            return hyper
    raise exception.ComputeHostNotFound(host=compute_id)


def fake_service_get_by_compute_host(context, host):
    for service in TEST_SERVICES:
        if service.host == host:
            return service


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

    for hyper in TEST_HYPERS_OBJ:
        for key in result:
            if key == 'count':
                result[key] += 1
            else:
                result[key] += getattr(hyper, key)

    return result


def fake_instance_get_all_by_host(context, host):
    results = []
    for inst in TEST_SERVERS:
        if inst['host'] == host:
            inst_obj = fake_instance.fake_instance_obj(context, **inst)
            results.append(inst_obj)
    return results


class HypervisorsTestV21(test.NoDBTestCase):
    api_version = '2.1'
    # Allow subclasses to override if the id value in the response is the
    # compute node primary key integer id or the uuid.
    expect_uuid_for_id = False

    # copying the objects locally so the cells testcases can provide their own
    TEST_HYPERS_OBJ = copy.deepcopy(TEST_HYPERS_OBJ)
    TEST_SERVICES = copy.deepcopy(TEST_SERVICES)
    TEST_SERVERS = copy.deepcopy(TEST_SERVERS)

    DETAIL_HYPERS_DICTS = copy.deepcopy(TEST_HYPERS)
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
    INDEX_HYPER_DICTS = [
        dict(id=1, hypervisor_hostname="hyper1",
             state='up', status='enabled'),
        dict(id=2, hypervisor_hostname="hyper2",
             state='up', status='enabled')]
    DETAIL_NULL_CPUINFO_DICT = {'': '', None: None}

    def _get_request(self, use_admin_context, url=''):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.api_version)

    def _set_up_controller(self):
        self.controller = hypervisors_v21.HypervisorsController()
        self.controller.servicegroup_api.service_is_up = mock.MagicMock(
            return_value=True)

    def _get_hyper_id(self):
        """Helper function to get the proper hypervisor id for a request

        :returns: The first hypervisor's uuid for microversions that expect a
            uuid for the id, otherwise the hypervisor's id primary key
        """
        return (self.TEST_HYPERS_OBJ[0].uuid if self.expect_uuid_for_id
                else self.TEST_HYPERS_OBJ[0].id)

    def setUp(self):
        super(HypervisorsTestV21, self).setUp()
        self._set_up_controller()
        self.rule_hyp_show = "os_compute_api:os-hypervisors"

        host_api = self.controller.host_api
        host_api.compute_node_get_all = mock.MagicMock(
            side_effect=fake_compute_node_get_all)
        host_api.service_get_by_compute_host = mock.MagicMock(
            side_effect=fake_service_get_by_compute_host)
        host_api.compute_node_search_by_hypervisor = mock.MagicMock(
            side_effect=fake_compute_node_search_by_hypervisor)
        host_api.compute_node_get = mock.MagicMock(
            side_effect=fake_compute_node_get)

        self.stub_out('nova.db.api.compute_node_statistics',
                      fake_compute_node_statistics)

    def test_view_hypervisor_nodetail_noservers(self):
        req = self._get_request(True)
        result = self.controller._view_hypervisor(
            self.TEST_HYPERS_OBJ[0], self.TEST_SERVICES[0], False, req)

        self.assertEqual(self.INDEX_HYPER_DICTS[0], result)

    def test_view_hypervisor_detail_noservers(self):
        req = self._get_request(True)
        result = self.controller._view_hypervisor(
            self.TEST_HYPERS_OBJ[0], self.TEST_SERVICES[0], True, req)

        self.assertEqual(self.DETAIL_HYPERS_DICTS[0], result)

    def test_view_hypervisor_servers(self):
        req = self._get_request(True)
        result = self.controller._view_hypervisor(self.TEST_HYPERS_OBJ[0],
                                                  self.TEST_SERVICES[0],
                                                  False, req,
                                                  self.TEST_SERVERS)
        expected_dict = copy.deepcopy(self.INDEX_HYPER_DICTS[0])
        expected_dict.update({'servers': [
                                  dict(name="inst1", uuid=uuids.instance_1),
                                  dict(name="inst2", uuid=uuids.instance_2),
                                  dict(name="inst3", uuid=uuids.instance_3),
                                  dict(name="inst4", uuid=uuids.instance_4)]})

        self.assertEqual(expected_dict, result)

    def _test_view_hypervisor_detail_cpuinfo_null(self, cpu_info):
        req = self._get_request(True)

        test_hypervisor_obj = copy.deepcopy(self.TEST_HYPERS_OBJ[0])
        test_hypervisor_obj.cpu_info = cpu_info
        result = self.controller._view_hypervisor(test_hypervisor_obj,
                                                  self.TEST_SERVICES[0],
                                                  True, req)

        expected_dict = copy.deepcopy(self.DETAIL_HYPERS_DICTS[0])
        expected_dict.update({'cpu_info':
                              self.DETAIL_NULL_CPUINFO_DICT[cpu_info]})
        self.assertEqual(result, expected_dict)

    def test_view_hypervisor_detail_cpuinfo_empty_string(self):
        self._test_view_hypervisor_detail_cpuinfo_null('')

    def test_view_hypervisor_detail_cpuinfo_none(self):
        self._test_view_hypervisor_detail_cpuinfo_null(None)

    def test_index(self):
        req = self._get_request(True)
        result = self.controller.index(req)

        self.assertEqual(dict(hypervisors=self.INDEX_HYPER_DICTS), result)

    def test_index_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_index_compute_host_not_found(self):
        """Tests that if a service is deleted but the compute node is not we
        don't fail when listing hypervisors.
        """

        # two computes, a matching service only exists for the first one
        compute_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(**TEST_HYPERS[0]),
            objects.ComputeNode(**TEST_HYPERS[1])
        ])

        def fake_service_get_by_compute_host(context, host):
            if host == TEST_HYPERS[0]['host']:
                return TEST_SERVICES[0]
            raise exception.ComputeHostNotFound(host=host)

        @mock.patch.object(self.controller.host_api, 'compute_node_get_all',
                           return_value=compute_nodes)
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host',
                           fake_service_get_by_compute_host)
        def _test(self, compute_node_get_all):
            req = self._get_request(True)
            result = self.controller.index(req)
            self.assertEqual(1, len(result['hypervisors']))
            expected = {
                'id': compute_nodes[0].uuid if self.expect_uuid_for_id
                                            else compute_nodes[0].id,
                'hypervisor_hostname': compute_nodes[0].hypervisor_hostname,
                'state': 'up',
                'status': 'enabled',
            }
            self.assertDictEqual(expected, result['hypervisors'][0])

        _test(self)

    def test_index_compute_host_not_mapped(self):
        """Tests that we don't fail index if a host is not mapped."""

        # two computes, a matching service only exists for the first one
        compute_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(**TEST_HYPERS[0]),
            objects.ComputeNode(**TEST_HYPERS[1])
        ])

        def fake_service_get_by_compute_host(context, host):
            if host == TEST_HYPERS[0]['host']:
                return TEST_SERVICES[0]
            raise exception.HostMappingNotFound(name=host)

        @mock.patch.object(self.controller.host_api, 'compute_node_get_all',
                           return_value=compute_nodes)
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host',
                           fake_service_get_by_compute_host)
        def _test(self, compute_node_get_all):
            req = self._get_request(True)
            result = self.controller.index(req)
            self.assertEqual(1, len(result['hypervisors']))
            expected = {
                'id': compute_nodes[0].uuid if self.expect_uuid_for_id
                                            else compute_nodes[0].id,
                'hypervisor_hostname': compute_nodes[0].hypervisor_hostname,
                'state': 'up',
                'status': 'enabled',
            }
            self.assertDictEqual(expected, result['hypervisors'][0])

        _test(self)

    def test_detail(self):
        req = self._get_request(True)
        result = self.controller.detail(req)

        self.assertEqual(dict(hypervisors=self.DETAIL_HYPERS_DICTS), result)

    def test_detail_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.detail, req)

    def test_detail_compute_host_not_found(self):
        """Tests that if a service is deleted but the compute node is not we
        don't fail when listing hypervisors.
        """

        # two computes, a matching service only exists for the first one
        compute_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(**TEST_HYPERS[0]),
            objects.ComputeNode(**TEST_HYPERS[1])
        ])

        def fake_service_get_by_compute_host(context, host):
            if host == TEST_HYPERS[0]['host']:
                return TEST_SERVICES[0]
            raise exception.ComputeHostNotFound(host=host)

        @mock.patch.object(self.controller.host_api, 'compute_node_get_all',
                           return_value=compute_nodes)
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host',
                           fake_service_get_by_compute_host)
        def _test(self, compute_node_get_all):
            req = self._get_request(True)
            result = self.controller.detail(req)
            self.assertEqual(1, len(result['hypervisors']))
            expected = {
                'id': compute_nodes[0].id,
                'hypervisor_hostname': compute_nodes[0].hypervisor_hostname,
                'state': 'up',
                'status': 'enabled',
            }
            # we don't care about all of the details, just make sure we get
            # the subset we care about and there are more keys than what index
            # would return
            hypervisor = result['hypervisors'][0]
            self.assertTrue(
                set(expected.keys()).issubset(set(hypervisor.keys())))
            self.assertGreater(len(hypervisor.keys()), len(expected.keys()))
            self.assertEqual(compute_nodes[0].hypervisor_hostname,
                             hypervisor['hypervisor_hostname'])

        _test(self)

    def test_detail_compute_host_not_mapped(self):
        """Tests that if a service is deleted but the compute node is not we
        don't fail when listing hypervisors.
        """

        # two computes, a matching service only exists for the first one
        compute_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(**TEST_HYPERS[0]),
            objects.ComputeNode(**TEST_HYPERS[1])
        ])

        def fake_service_get_by_compute_host(context, host):
            if host == TEST_HYPERS[0]['host']:
                return TEST_SERVICES[0]
            raise exception.HostMappingNotFound(name=host)

        @mock.patch.object(self.controller.host_api, 'compute_node_get_all',
                           return_value=compute_nodes)
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host',
                           fake_service_get_by_compute_host)
        def _test(self, compute_node_get_all):
            req = self._get_request(True)
            result = self.controller.detail(req)
            self.assertEqual(1, len(result['hypervisors']))
            expected = {
                'id': compute_nodes[0].id,
                'hypervisor_hostname': compute_nodes[0].hypervisor_hostname,
                'state': 'up',
                'status': 'enabled',
            }
            # we don't care about all of the details, just make sure we get
            # the subset we care about and there are more keys than what index
            # would return
            hypervisor = result['hypervisors'][0]
            self.assertTrue(
                set(expected.keys()).issubset(set(hypervisor.keys())))
            self.assertGreater(len(hypervisor.keys()), len(expected.keys()))
            self.assertEqual(compute_nodes[0].hypervisor_hostname,
                             hypervisor['hypervisor_hostname'])

        _test(self)

    def test_show_compute_host_not_mapped(self):
        """Tests that if a service is deleted but the compute node is not we
        don't fail when listing hypervisors.
        """

        @mock.patch.object(self.controller.host_api, 'compute_node_get',
                           return_value=self.TEST_HYPERS_OBJ[0])
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host')
        def _test(self, mock_service, mock_compute_node_get):
            req = self._get_request(True)
            mock_service.side_effect = exception.HostMappingNotFound(
                name='foo')
            hyper_id = self._get_hyper_id()
            self.assertRaises(exc.HTTPNotFound, self.controller.show,
                              req, hyper_id)
            self.assertTrue(mock_service.called)
            mock_compute_node_get.assert_called_once_with(mock.ANY, hyper_id)
        _test(self)

    def test_show_noid(self):
        req = self._get_request(True)
        hyperid = uuids.hyper3 if self.expect_uuid_for_id else '3'
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, hyperid)

    def test_show_non_integer_id(self):
        req = self._get_request(True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, 'abc')

    def test_show_withid(self):
        req = self._get_request(True)
        hyper_id = self._get_hyper_id()
        result = self.controller.show(req, hyper_id)

        self.assertEqual(dict(hypervisor=self.DETAIL_HYPERS_DICTS[0]), result)

    def test_show_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show, req,
                          self._get_hyper_id())

    def test_uptime_noid(self):
        req = self._get_request(True)
        hyper_id = uuids.hyper3 if self.expect_uuid_for_id else '3'
        self.assertRaises(exc.HTTPNotFound, self.controller.uptime, req,
                          hyper_id)

    def test_uptime_notimplemented(self):
        with mock.patch.object(self.controller.host_api, 'get_host_uptime',
                               side_effect=exc.HTTPNotImplemented()
                               ) as mock_get_uptime:
            req = self._get_request(True)
            hyper_id = self._get_hyper_id()
            self.assertRaises(exc.HTTPNotImplemented,
                              self.controller.uptime, req, hyper_id)
            self.assertEqual(1, mock_get_uptime.call_count)

    def test_uptime_implemented(self):
        with mock.patch.object(self.controller.host_api, 'get_host_uptime',
                               return_value="fake uptime"
                               ) as mock_get_uptime:
            req = self._get_request(True)
            hyper_id = self._get_hyper_id()
            result = self.controller.uptime(req, hyper_id)

            expected_dict = copy.deepcopy(self.INDEX_HYPER_DICTS[0])
            expected_dict.update({'uptime': "fake uptime"})
            self.assertEqual(dict(hypervisor=expected_dict), result)
            self.assertEqual(1, mock_get_uptime.call_count)

    def test_uptime_non_integer_id(self):
        req = self._get_request(True)
        self.assertRaises(exc.HTTPNotFound, self.controller.uptime, req, 'abc')

    def test_uptime_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.uptime, req,
                          self.TEST_HYPERS_OBJ[0].id)

    def test_uptime_hypervisor_down(self):
        with mock.patch.object(self.controller.host_api, 'get_host_uptime',
                side_effect=exception.ComputeServiceUnavailable(host='dummy')
                ) as mock_get_uptime:
            req = self._get_request(True)
            hyper_id = self._get_hyper_id()
            self.assertRaises(exc.HTTPBadRequest,
                              self.controller.uptime, req, hyper_id)
            mock_get_uptime.assert_called_once_with(
                mock.ANY, self.TEST_HYPERS_OBJ[0].host)

    def test_uptime_hypervisor_not_mapped_service_get(self):
        @mock.patch.object(self.controller.host_api, 'compute_node_get')
        @mock.patch.object(self.controller.host_api, 'get_host_uptime')
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host',
                           side_effect=exception.HostMappingNotFound(
                               name='dummy'))
        def _test(mock_get, _, __):
            req = self._get_request(True)
            hyper_id = self._get_hyper_id()
            self.assertRaises(exc.HTTPNotFound,
                              self.controller.uptime, req, hyper_id)
            self.assertTrue(mock_get.called)

        _test()

    def test_uptime_hypervisor_not_mapped(self):
        with mock.patch.object(self.controller.host_api, 'get_host_uptime',
                side_effect=exception.HostMappingNotFound(name='dummy')
                ) as mock_get_uptime:
            req = self._get_request(True)
            hyper_id = self._get_hyper_id()
            self.assertRaises(exc.HTTPNotFound,
                              self.controller.uptime, req, hyper_id)
            mock_get_uptime.assert_called_once_with(
                mock.ANY, self.TEST_HYPERS_OBJ[0].host)

    def test_search(self):
        req = self._get_request(True)
        result = self.controller.search(req, 'hyper')

        self.assertEqual(dict(hypervisors=self.INDEX_HYPER_DICTS), result)

    def test_search_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.search, req,
                          self.TEST_HYPERS_OBJ[0].id)

    def test_search_non_exist(self):
        with mock.patch.object(self.controller.host_api,
                               'compute_node_search_by_hypervisor',
                               return_value=[]) as mock_node_search:
            req = self._get_request(True)
            self.assertRaises(exc.HTTPNotFound, self.controller.search,
                              req, 'a')
            self.assertEqual(1, mock_node_search.call_count)

    def test_search_unmapped(self):

        @mock.patch.object(self.controller.host_api,
                           'compute_node_search_by_hypervisor')
        @mock.patch.object(self.controller.host_api,
                           'service_get_by_compute_host')
        def _test(mock_service, mock_search):
            mock_search.return_value = [mock.MagicMock()]
            mock_service.side_effect = exception.HostMappingNotFound(
                name='foo')
            req = self._get_request(True)
            self.assertRaises(exc.HTTPNotFound, self.controller.search,
                              req, 'a')
            self.assertTrue(mock_service.called)

        _test()

    @mock.patch.object(objects.InstanceList, 'get_by_host',
                       side_effect=fake_instance_get_all_by_host)
    def test_servers(self, mock_get):
        req = self._get_request(True)
        result = self.controller.servers(req, 'hyper')

        expected_dict = copy.deepcopy(self.INDEX_HYPER_DICTS)
        expected_dict[0].update({'servers': [
                                     dict(uuid=uuids.instance_1),
                                     dict(uuid=uuids.instance_3)]})
        expected_dict[1].update({'servers': [
                                     dict(uuid=uuids.instance_2),
                                     dict(uuid=uuids.instance_4)]})

        for output in result['hypervisors']:
            servers = output['servers']
            for server in servers:
                del server['name']
        self.assertEqual(dict(hypervisors=expected_dict), result)

    def test_servers_not_mapped(self):
        req = self._get_request(True)
        with mock.patch.object(self.controller.host_api,
                               'instance_get_all_by_host') as m:
            m.side_effect = exception.HostMappingNotFound(name='something')
            self.assertRaises(exc.HTTPNotFound,
                              self.controller.servers, req, 'hyper')

    def test_servers_non_id(self):
        with mock.patch.object(self.controller.host_api,
                               'compute_node_search_by_hypervisor',
                               return_value=[]) as mock_node_search:
            req = self._get_request(True)
            self.assertRaises(exc.HTTPNotFound,
                              self.controller.servers,
                              req, '115')
            self.assertEqual(1, mock_node_search.call_count)

    def test_servers_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.servers, req,
                          self.TEST_HYPERS_OBJ[0].id)

    def test_servers_with_non_integer_hypervisor_id(self):
        with mock.patch.object(self.controller.host_api,
                               'compute_node_search_by_hypervisor',
                               return_value=[]) as mock_node_search:

            req = self._get_request(True)
            self.assertRaises(exc.HTTPNotFound,
                              self.controller.servers, req, 'abc')
            self.assertEqual(1, mock_node_search.call_count)

    def test_servers_with_no_server(self):
        with mock.patch.object(self.controller.host_api,
                               'instance_get_all_by_host',
                               return_value=[]) as mock_inst_get_all:
            req = self._get_request(True)
            result = self.controller.servers(req, self.TEST_HYPERS_OBJ[0].id)
            self.assertEqual(dict(hypervisors=self.INDEX_HYPER_DICTS), result)
            self.assertTrue(mock_inst_get_all.called)

    def test_statistics(self):
        req = self._get_request(True)
        result = self.controller.statistics(req)

        self.assertEqual(dict(hypervisor_statistics=dict(
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
                    disk_available_least=200)), result)

    def test_statistics_non_admin(self):
        req = self._get_request(False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.statistics, req)


_CELL_PATH = 'cell1'


class CellHypervisorsTestV21(HypervisorsTestV21):
    TEST_HYPERS_OBJ = [cells_utils.ComputeNodeProxy(obj, _CELL_PATH)
                       for obj in TEST_HYPERS_OBJ]
    TEST_SERVICES = [cells_utils.ServiceProxy(obj, _CELL_PATH)
                     for obj in TEST_SERVICES]

    TEST_SERVERS = [dict(server,
                         host=cells_utils.cell_with_item(_CELL_PATH,
                                                         server['host']))
                    for server in TEST_SERVERS]

    DETAIL_HYPERS_DICTS = copy.deepcopy(HypervisorsTestV21.DETAIL_HYPERS_DICTS)
    DETAIL_HYPERS_DICTS = [dict(hyp, id=cells_utils.cell_with_item(_CELL_PATH,
                                                                   hyp['id']),
                                service=dict(hyp['service'],
                                             id=cells_utils.cell_with_item(
                                                 _CELL_PATH,
                                                 hyp['service']['id']),
                                             host=cells_utils.cell_with_item(
                                                 _CELL_PATH,
                                                 hyp['service']['host'])))
                           for hyp in DETAIL_HYPERS_DICTS]

    INDEX_HYPER_DICTS = copy.deepcopy(HypervisorsTestV21.INDEX_HYPER_DICTS)
    INDEX_HYPER_DICTS = [dict(hyp, id=cells_utils.cell_with_item(_CELL_PATH,
                                                                 hyp['id']))
                         for hyp in INDEX_HYPER_DICTS]

    # __deepcopy__ is added for copying an object locally in
    # _test_view_hypervisor_detail_cpuinfo_null
    cells_utils.ComputeNodeProxy.__deepcopy__ = (lambda self, memo:
        cells_utils.ComputeNodeProxy(copy.deepcopy(self._obj, memo),
                                     self._cell_path))

    @classmethod
    def fake_compute_node_get_all(cls, context, limit=None, marker=None):
        return cls.TEST_HYPERS_OBJ

    @classmethod
    def fake_compute_node_search_by_hypervisor(cls, context, hypervisor_re):
        return cls.TEST_HYPERS_OBJ

    @classmethod
    def fake_compute_node_get(cls, context, compute_id):
        for hyper in cls.TEST_HYPERS_OBJ:
            if hyper.id == compute_id:
                return hyper
        raise exception.ComputeHostNotFound(host=compute_id)

    @classmethod
    def fake_service_get_by_compute_host(cls, context, host):
        for service in cls.TEST_SERVICES:
            if service.host == host:
                return service

    @classmethod
    def fake_instance_get_all_by_host(cls, context, host):
        results = []
        for inst in cls.TEST_SERVERS:
            if inst['host'] == host:
                results.append(inst)
        return results

    def setUp(self):

        self.flags(enable=True, cell_type='api', group='cells')

        super(CellHypervisorsTestV21, self).setUp()

        host_api = self.controller.host_api
        host_api.compute_node_get_all = mock.MagicMock(
            side_effect=self.fake_compute_node_get_all)
        host_api.service_get_by_compute_host = mock.MagicMock(
            side_effect=self.fake_service_get_by_compute_host)
        host_api.compute_node_search_by_hypervisor = mock.MagicMock(
            side_effect=self.fake_compute_node_search_by_hypervisor)
        host_api.compute_node_get = mock.MagicMock(
            side_effect=self.fake_compute_node_get)
        host_api.compute_node_statistics = mock.MagicMock(
            side_effect=fake_compute_node_statistics)
        host_api.instance_get_all_by_host = mock.MagicMock(
            side_effect=self.fake_instance_get_all_by_host)


class HypervisorsTestV228(HypervisorsTestV21):
    api_version = '2.28'

    DETAIL_HYPERS_DICTS = copy.deepcopy(HypervisorsTestV21.DETAIL_HYPERS_DICTS)
    DETAIL_HYPERS_DICTS[0]['cpu_info'] = jsonutils.loads(CPU_INFO)
    DETAIL_HYPERS_DICTS[1]['cpu_info'] = jsonutils.loads(CPU_INFO)
    DETAIL_NULL_CPUINFO_DICT = {'': {}, None: {}}


class HypervisorsTestV233(HypervisorsTestV228):
    api_version = '2.33'

    def test_index_pagination(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors?limit=1&marker=1')
        result = self.controller.index(req)
        expected = {
            'hypervisors': [
                {'hypervisor_hostname': 'hyper2',
                 'id': 2,
                 'state': 'up',
                 'status': 'enabled'}
            ],
            'hypervisors_links': [
                {'href': 'http://localhost/v2/hypervisors?limit=1&marker=2',
                 'rel': 'next'}
            ]
        }

        self.assertEqual(expected, result)

    def test_index_pagination_with_invalid_marker(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors?marker=99999')
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_index_pagination_with_invalid_non_int_limit(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors?limit=-9')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_pagination_with_invalid_string_limit(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors?limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_duplicate_query_parameters_with_invalid_string_limit(self):
        req = self._get_request(
            True,
            '/v2/1234/os-hypervisors/?limit=1&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_duplicate_query_parameters_validation(self):
        expected = [{
           'hypervisor_hostname': 'hyper2',
           'id': 2,
           'state': 'up',
           'status': 'enabled'}
        ]
        params = {
            'limit': 1,
            'marker': 1,
        }

        for param, value in params.items():
            req = self._get_request(
                use_admin_context=True,
                url='/os-hypervisors?marker=1&%s=%s&%s=%s' %
                    (param, value, param, value))
            result = self.controller.index(req)
            self.assertEqual(expected, result['hypervisors'])

    def test_index_pagination_with_additional_filter(self):
        expected = {
            'hypervisors': [
                {'hypervisor_hostname': 'hyper2',
                 'id': 2,
                 'state': 'up',
                 'status': 'enabled'}
            ],
            'hypervisors_links': [
                {'href': 'http://localhost/v2/hypervisors?limit=1&marker=2',
                 'rel': 'next'}
            ]
        }
        req = self._get_request(
            True, '/v2/1234/os-hypervisors?limit=1&marker=1&additional=3')
        result = self.controller.index(req)
        self.assertEqual(expected, result)

    def test_detail_pagination(self):
        req = self._get_request(
            True, '/v2/1234/os-hypervisors/detail?limit=1&marker=1')
        result = self.controller.detail(req)
        link = 'http://localhost/v2/hypervisors/detail?limit=1&marker=2'
        expected = {
            'hypervisors': [
                {'cpu_info': {'arch': 'x86_64',
                              'features': [],
                              'model': '',
                              'topology': {'cores': 1,
                                           'sockets': 1,
                                           'threads': 1},
                              'vendor': 'fake'},
                'current_workload': 2,
                'disk_available_least': 100,
                'free_disk_gb': 125,
                'free_ram_mb': 5120,
                'host_ip': netaddr.IPAddress('2.2.2.2'),
                'hypervisor_hostname': 'hyper2',
                'hypervisor_type': 'xen',
                'hypervisor_version': 3,
                'id': 2,
                'local_gb': 250,
                'local_gb_used': 125,
                'memory_mb': 10240,
                'memory_mb_used': 5120,
                'running_vms': 2,
                'service': {'disabled_reason': None,
                            'host': 'compute2',
                            'id': 2},
                'state': 'up',
                'status': 'enabled',
                'vcpus': 4,
                'vcpus_used': 2}
            ],
            'hypervisors_links': [{'href': link, 'rel': 'next'}]
        }

        self.assertEqual(expected, result)

    def test_detail_pagination_with_invalid_marker(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors/detail?marker=99999')
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_detail_pagination_with_invalid_string_limit(self):
        req = self._get_request(True,
                                '/v2/1234/os-hypervisors/detail?limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.detail, req)

    def test_detail_duplicate_query_parameters_with_invalid_string_limit(self):
        req = self._get_request(
            True,
            '/v2/1234/os-hypervisors/detail?limit=1&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.detail, req)

    def test_detail_duplicate_query_parameters_validation(self):
        expected = [
                {'cpu_info': {'arch': 'x86_64',
                              'features': [],
                              'model': '',
                              'topology': {'cores': 1,
                                           'sockets': 1,
                                           'threads': 1},
                              'vendor': 'fake'},
                'current_workload': 2,
                'disk_available_least': 100,
                'free_disk_gb': 125,
                'free_ram_mb': 5120,
                'host_ip': netaddr.IPAddress('2.2.2.2'),
                'hypervisor_hostname': 'hyper2',
                'hypervisor_type': 'xen',
                'hypervisor_version': 3,
                'id': 2,
                'local_gb': 250,
                'local_gb_used': 125,
                'memory_mb': 10240,
                'memory_mb_used': 5120,
                'running_vms': 2,
                'service': {'disabled_reason': None,
                            'host': 'compute2',
                            'id': 2},
                'state': 'up',
                'status': 'enabled',
                'vcpus': 4,
                'vcpus_used': 2}
        ]

        params = {
            'limit': 1,
            'marker': 1,
        }

        for param, value in params.items():
            req = self._get_request(
                use_admin_context=True,
                url='/os-hypervisors/detail?marker=1&%s=%s&%s=%s' %
                    (param, value, param, value))
            result = self.controller.detail(req)
            self.assertEqual(expected, result['hypervisors'])

    def test_detail_pagination_with_additional_filter(self):
        link = 'http://localhost/v2/hypervisors/detail?limit=1&marker=2'
        expected = {
            'hypervisors': [
                {'cpu_info': {'arch': 'x86_64',
                              'features': [],
                              'model': '',
                              'topology': {'cores': 1,
                                           'sockets': 1,
                                           'threads': 1},
                              'vendor': 'fake'},
                'current_workload': 2,
                'disk_available_least': 100,
                'free_disk_gb': 125,
                'free_ram_mb': 5120,
                'host_ip': netaddr.IPAddress('2.2.2.2'),
                'hypervisor_hostname': 'hyper2',
                'hypervisor_type': 'xen',
                'hypervisor_version': 3,
                'id': 2,
                'local_gb': 250,
                'local_gb_used': 125,
                'memory_mb': 10240,
                'memory_mb_used': 5120,
                'running_vms': 2,
                'service': {'disabled_reason': None,
                            'host': 'compute2',
                            'id': 2},
                'state': 'up',
                'status': 'enabled',
                'vcpus': 4,
                'vcpus_used': 2}
            ],
            'hypervisors_links': [{
                'href': link,
                'rel': 'next'}]
        }
        req = self._get_request(
            True, '/v2/1234/os-hypervisors/detail?limit=1&marker=1&unknown=2')
        result = self.controller.detail(req)
        self.assertEqual(expected, result)


class HypervisorsTestV252(HypervisorsTestV233):
    """This is a boundary test to make sure 2.52 works like 2.33."""
    api_version = '2.52'


class HypervisorsTestV253(HypervisorsTestV252):
    api_version = hypervisors_v21.UUID_FOR_ID_MIN_VERSION
    expect_uuid_for_id = True

    # This is an expected response for index().
    INDEX_HYPER_DICTS = [
        dict(id=uuids.hyper1, hypervisor_hostname="hyper1",
             state='up', status='enabled'),
        dict(id=uuids.hyper2, hypervisor_hostname="hyper2",
             state='up', status='enabled')]

    def setUp(self):
        super(HypervisorsTestV253, self).setUp()
        # This is an expected response for detail().
        for index, detail_hyper_dict in enumerate(self.DETAIL_HYPERS_DICTS):
            detail_hyper_dict['id'] = TEST_HYPERS[index]['uuid']
            detail_hyper_dict['service']['id'] = TEST_SERVICES[index].uuid

    def test_servers(self):
        """Asserts that calling the servers route after 2.52 fails."""
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.servers,
                          self._get_request(True), 'hyper')

    def test_servers_with_no_server(self):
        """Tests GET /os-hypervisors?with_servers=1 when there are no
        instances on the given host.
        """
        with mock.patch.object(self.controller.host_api,
                               'instance_get_all_by_host',
                               return_value=[]) as mock_inst_get_all:
            req = self._get_request(use_admin_context=True,
                                    url='/os-hypervisors?with_servers=1')
            result = self.controller.index(req)
        self.assertEqual(dict(hypervisors=self.INDEX_HYPER_DICTS), result)
        # instance_get_all_by_host is called for each hypervisor
        self.assertEqual(2, mock_inst_get_all.call_count)
        mock_inst_get_all.assert_has_calls((
            mock.call(req.environ['nova.context'], TEST_HYPERS_OBJ[0].host),
            mock.call(req.environ['nova.context'], TEST_HYPERS_OBJ[1].host)))

    def test_servers_not_mapped(self):
        """Tests that instance_get_all_by_host fails with HostMappingNotFound.
        """
        req = self._get_request(use_admin_context=True,
                                url='/os-hypervisors?with_servers=1')
        with mock.patch.object(
                self.controller.host_api, 'instance_get_all_by_host',
                side_effect=exception.HostMappingNotFound(name='something')):
            result = self.controller.index(req)
            self.assertEqual(dict(hypervisors=[]), result)

    def test_list_with_servers(self):
        """Tests GET /os-hypervisors?with_servers=True"""
        instances = [
            objects.InstanceList(objects=[objects.Instance(
                id=1, uuid=uuids.hyper1_instance1)]),
            objects.InstanceList(objects=[objects.Instance(
                id=2, uuid=uuids.hyper2_instance1)])]
        with mock.patch.object(self.controller.host_api,
                               'instance_get_all_by_host',
                               side_effect=instances) as mock_inst_get_all:
            req = self._get_request(use_admin_context=True,
                                    url='/os-hypervisors?with_servers=True')
            result = self.controller.index(req)
        index_with_servers = copy.deepcopy(self.INDEX_HYPER_DICTS)
        index_with_servers[0]['servers'] = [
            {'name': 'instance-00000001', 'uuid': uuids.hyper1_instance1}]
        index_with_servers[1]['servers'] = [
            {'name': 'instance-00000002', 'uuid': uuids.hyper2_instance1}]
        self.assertEqual(dict(hypervisors=index_with_servers), result)
        # instance_get_all_by_host is called for each hypervisor
        self.assertEqual(2, mock_inst_get_all.call_count)
        mock_inst_get_all.assert_has_calls((
            mock.call(req.environ['nova.context'], TEST_HYPERS_OBJ[0].host),
            mock.call(req.environ['nova.context'], TEST_HYPERS_OBJ[1].host)))

    def test_list_with_servers_invalid_parameter(self):
        """Tests using an invalid with_servers query parameter."""
        req = self._get_request(use_admin_context=True,
                                url='/os-hypervisors?with_servers=invalid')
        self.assertRaises(
            exception.ValidationError, self.controller.index, req)

    def test_list_with_hostname_pattern_and_paging_parameters(self):
        """This is a negative test to validate that trying to list hypervisors
        with a hostname pattern and paging parameters results in a 400 error.
        """
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?hypervisor_hostname_pattern=foo&'
                'limit=1&marker=%s' % uuids.marker)
        ex = self.assertRaises(exc.HTTPBadRequest, self.controller.index, req)
        self.assertIn('Paging over hypervisors with the '
                      'hypervisor_hostname_pattern query parameter is not '
                      'supported.', six.text_type(ex))

    def test_servers_with_non_integer_hypervisor_id(self):
        """This is a poorly named test, it's really checking the 404 case where
        there is no match for the hostname pattern.
        """
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?with_servers=yes&'
                'hypervisor_hostname_pattern=shenzhen')
        with mock.patch.object(self.controller.host_api,
                               'compute_node_search_by_hypervisor',
                               return_value=objects.ComputeNodeList()) as s:
            self.assertRaises(exc.HTTPNotFound, self.controller.index, req)
            s.assert_called_once_with(req.environ['nova.context'], 'shenzhen')

    def test_servers_non_admin(self):
        """There is no reason to test this for 2.53 since the
        /os-hypervisors/servers route is deprecated.
        """
        pass

    def test_servers_non_id(self):
        """There is no reason to test this for 2.53 since the
        /os-hypervisors/servers route is deprecated.
        """
        pass

    def test_search_old_route(self):
        """Asserts that calling the search route after 2.52 fails."""
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.search,
                          self._get_request(True), 'hyper')

    def test_search(self):
        """Test listing hypervisors with details and using the
        hypervisor_hostname_pattern query string.
        """
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?hypervisor_hostname_pattern=shenzhen')
        with mock.patch.object(self.controller.host_api,
                               'compute_node_search_by_hypervisor',
                               return_value=objects.ComputeNodeList(
                                   objects=[TEST_HYPERS_OBJ[0]])) as s:
            result = self.controller.detail(req)
            s.assert_called_once_with(req.environ['nova.context'], 'shenzhen')

        expected = {
            'hypervisors': [
                {'cpu_info': {'arch': 'x86_64',
                              'features': [],
                              'model': '',
                              'topology': {'cores': 1,
                                           'sockets': 1,
                                           'threads': 1},
                              'vendor': 'fake'},
                'current_workload': 2,
                'disk_available_least': 100,
                'free_disk_gb': 125,
                'free_ram_mb': 5120,
                'host_ip': netaddr.IPAddress('1.1.1.1'),
                'hypervisor_hostname': 'hyper1',
                'hypervisor_type': 'xen',
                'hypervisor_version': 3,
                'id': TEST_HYPERS_OBJ[0].uuid,
                'local_gb': 250,
                'local_gb_used': 125,
                'memory_mb': 10240,
                'memory_mb_used': 5120,
                'running_vms': 2,
                'service': {'disabled_reason': None,
                            'host': 'compute1',
                            'id': TEST_SERVICES[0].uuid},
                'state': 'up',
                'status': 'enabled',
                'vcpus': 4,
                'vcpus_used': 2}
            ]
        }
        # There are no links when using the hypervisor_hostname_pattern
        # query string since we can't page using a pattern matcher.
        self.assertNotIn('hypervisors_links', result)
        self.assertDictEqual(expected, result)

    def test_search_invalid_hostname_pattern_parameter(self):
        """Tests passing an invalid hypervisor_hostname_pattern query
        parameter.
        """
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?hypervisor_hostname_pattern=invalid~host')
        self.assertRaises(
            exception.ValidationError, self.controller.detail, req)

    def test_search_non_exist(self):
        """This is a duplicate of test_servers_with_non_integer_hypervisor_id.
        """
        pass

    def test_search_non_admin(self):
        """There is no reason to test this for 2.53 since the
        /os-hypervisors/search route is deprecated.
        """
        pass

    def test_search_unmapped(self):
        """This is already tested with test_index_compute_host_not_mapped."""
        pass

    def test_show_non_integer_id(self):
        """There is no reason to test this for 2.53 since 2.53 requires a
        non-integer id (requires a uuid).
        """
        pass

    def test_show_integer_id(self):
        """Tests that we get a 400 if passed a hypervisor integer id to show().
        """
        req = self._get_request(True)
        ex = self.assertRaises(exc.HTTPBadRequest,
                               self.controller.show, req, '1')
        self.assertIn('Invalid uuid 1', six.text_type(ex))

    def test_show_with_servers_invalid_parameter(self):
        """Tests passing an invalid value for the with_servers query parameter
        to the show() method to make sure the query parameter is validated.
        """
        hyper_id = self._get_hyper_id()
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/%s?with_servers=invalid' % hyper_id)
        ex = self.assertRaises(
            exception.ValidationError, self.controller.show, req, hyper_id)
        self.assertIn('with_servers', six.text_type(ex))

    def test_show_with_servers_host_mapping_not_found(self):
        """Tests that a 404 is returned if instance_get_all_by_host raises
        HostMappingNotFound.
        """
        hyper_id = self._get_hyper_id()
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/%s?with_servers=true' % hyper_id)
        with mock.patch.object(
                self.controller.host_api, 'instance_get_all_by_host',
                side_effect=exception.HostMappingNotFound(name=hyper_id)):
            self.assertRaises(exc.HTTPNotFound, self.controller.show,
                              req, hyper_id)

    def test_show_with_servers(self):
        """Tests the show() result when servers are included in the output."""
        instances = objects.InstanceList(objects=[objects.Instance(
            id=1, uuid=uuids.hyper1_instance1)])
        hyper_id = self._get_hyper_id()
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/%s?with_servers=on' % hyper_id)
        with mock.patch.object(self.controller.host_api,
                               'instance_get_all_by_host',
                               return_value=instances) as mock_inst_get_all:
            result = self.controller.show(req, hyper_id)
        show_with_servers = copy.deepcopy(self.DETAIL_HYPERS_DICTS[0])
        show_with_servers['servers'] = [
            {'name': 'instance-00000001', 'uuid': uuids.hyper1_instance1}]
        self.assertDictEqual(dict(hypervisor=show_with_servers), result)
        # instance_get_all_by_host is called
        mock_inst_get_all.assert_called_once_with(
            req.environ['nova.context'], TEST_HYPERS_OBJ[0].host)

    def test_uptime_non_integer_id(self):
        """There is no reason to test this for 2.53 since 2.53 requires a
        non-integer id (requires a uuid).
        """
        pass

    def test_uptime_integer_id(self):
        """Tests that we get a 400 if passed a hypervisor integer id to
        uptime().
        """
        req = self._get_request(True)
        ex = self.assertRaises(exc.HTTPBadRequest,
                               self.controller.uptime, req, '1')
        self.assertIn('Invalid uuid 1', six.text_type(ex))

    def test_detail_pagination(self):
        """Tests details paging with uuid markers."""
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/detail?limit=1&marker=%s' %
                TEST_HYPERS_OBJ[0].uuid)
        result = self.controller.detail(req)
        link = ('http://localhost/v2/hypervisors/detail?limit=1&marker=%s' %
                TEST_HYPERS_OBJ[1].uuid)
        expected = {
            'hypervisors': [
                {'cpu_info': {'arch': 'x86_64',
                              'features': [],
                              'model': '',
                              'topology': {'cores': 1,
                                           'sockets': 1,
                                           'threads': 1},
                              'vendor': 'fake'},
                'current_workload': 2,
                'disk_available_least': 100,
                'free_disk_gb': 125,
                'free_ram_mb': 5120,
                'host_ip': netaddr.IPAddress('2.2.2.2'),
                'hypervisor_hostname': 'hyper2',
                'hypervisor_type': 'xen',
                'hypervisor_version': 3,
                'id': TEST_HYPERS_OBJ[1].uuid,
                'local_gb': 250,
                'local_gb_used': 125,
                'memory_mb': 10240,
                'memory_mb_used': 5120,
                'running_vms': 2,
                'service': {'disabled_reason': None,
                            'host': 'compute2',
                            'id': TEST_SERVICES[1].uuid},
                'state': 'up',
                'status': 'enabled',
                'vcpus': 4,
                'vcpus_used': 2}
            ],
            'hypervisors_links': [{'href': link, 'rel': 'next'}]
        }
        self.assertEqual(expected, result)

    def test_detail_pagination_with_invalid_marker(self):
        """Tests detail paging with an invalid marker (not found)."""
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/detail?marker=%s' % uuids.invalid_marker)
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_detail_pagination_with_additional_filter(self):
        req = self._get_request(
            True, '/v2/1234/os-hypervisors/detail?limit=1&marker=9&unknown=2')
        self.assertRaises(exception.ValidationError,
                          self.controller.detail, req)

    def test_detail_duplicate_query_parameters_validation(self):
        """Tests that the list Detail query parameter schema enforces only a
        single entry for any query parameter.
        """
        params = {
            'limit': 1,
            'marker': uuids.marker,
            'hypervisor_hostname_pattern': 'foo',
            'with_servers': 'true'
        }
        for param, value in params.items():
            req = self._get_request(
                use_admin_context=True,
                url='/os-hypervisors/detail?%s=%s&%s=%s' %
                    (param, value, param, value))
            self.assertRaises(exception.ValidationError,
                              self.controller.detail, req)

    def test_index_pagination(self):
        """Tests index paging with uuid markers."""
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?limit=1&marker=%s' %
                TEST_HYPERS_OBJ[0].uuid)
        result = self.controller.index(req)
        link = ('http://localhost/v2/hypervisors?limit=1&marker=%s' %
                TEST_HYPERS_OBJ[1].uuid)
        expected = {
            'hypervisors': [{
                'hypervisor_hostname': 'hyper2',
                'id': TEST_HYPERS_OBJ[1].uuid,
                'state': 'up',
                'status': 'enabled'
            }],
            'hypervisors_links': [{'href': link, 'rel': 'next'}]
        }
        self.assertEqual(expected, result)

    def test_index_pagination_with_invalid_marker(self):
        """Tests index paging with an invalid marker (not found)."""
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors?marker=%s' % uuids.invalid_marker)
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_index_pagination_with_additional_filter(self):
        req = self._get_request(
            True, '/v2/1234/os-hypervisors/?limit=1&marker=9&unknown=2')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_duplicate_query_parameters_validation(self):
        """Tests that the list query parameter schema enforces only a single
        entry for any query parameter.
        """
        params = {
            'limit': 1,
            'marker': uuids.marker,
            'hypervisor_hostname_pattern': 'foo',
            'with_servers': 'true'
        }
        for param, value in params.items():
            req = self._get_request(
                use_admin_context=True,
                url='/os-hypervisors?%s=%s&%s=%s' %
                    (param, value, param, value))
            self.assertRaises(exception.ValidationError,
                              self.controller.index, req)

    def test_show_duplicate_query_parameters_validation(self):
        """Tests that the show query parameter schema enforces only a single
        entry for any query parameter.
        """
        req = self._get_request(
            use_admin_context=True,
            url='/os-hypervisors/%s?with_servers=1&with_servers=1' %
                uuids.hyper1)
        self.assertRaises(exception.ValidationError,
                          self.controller.show, req, uuids.hyper1)
