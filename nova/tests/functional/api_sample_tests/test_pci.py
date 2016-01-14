# Copyright 2013 Intel.
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

import collections

import mock
from oslo_serialization import jsonutils
import testtools

from nova import objects
from nova.objects import fields
from nova.objects import pci_device_pool
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.functional.api_sample_tests import test_servers

skip_msg = "Bug 1426241"

fake_db_dev_1 = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'compute_node_id': 1,
    'address': '0000:04:10.0',
    'vendor_id': '8086',
    'numa_node': 0,
    'product_id': '1520',
    'dev_type': fields.PciDeviceType.SRIOV_VF,
    'status': 'available',
    'dev_id': 'pci_0000_04_10_0',
    'label': 'label_8086_1520',
    'instance_uuid': '69ba1044-0766-4ec0-b60d-09595de034a1',
    'request_id': None,
    'extra_info': '{"key1": "value1", "key2": "value2"}'
    }

fake_db_dev_2 = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 2,
    'compute_node_id': 1,
    'address': '0000:04:10.1',
    'vendor_id': '8086',
    'numa_node': 1,
    'product_id': '1520',
    'dev_type': fields.PciDeviceType.SRIOV_VF,
    'status': 'available',
    'dev_id': 'pci_0000_04_10_1',
    'label': 'label_8086_1520',
    'instance_uuid': 'd5b446a6-a1b4-4d01-b4f0-eac37b3a62fc',
    'request_id': None,
    'extra_info': '{"key3": "value3", "key4": "value4"}'
    }


class ExtendedServerPciSampleJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-pci"

    def setUp(self):
        raise testtools.TestCase.skipException(skip_msg)

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = {'hostid': '[a-f0-9]+'}
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = {'hostid': '[a-f0-9]+'}
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedHyervisorPciSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extra_extensions_to_load = ['os-hypervisors']
    extension_name = 'os-pci'

    def setUp(self):
        raise testtools.TestCase.skipException(skip_msg)
        super(ExtendedHyervisorPciSampleJsonTest, self).setUp()
        cpu_info = collections.OrderedDict([
            ('arch', 'x86_64'),
            ('model', 'Nehalem'),
            ('vendor', 'Intel'),
            ('features', ['pge', 'clflush']),
            ('topology', {
                'cores': 1,
                'threads': 1,
                'sockets': 4,
                }),
            ])
        self.fake_compute_node = objects.ComputeNode(
            cpu_info=jsonutils.dumps(cpu_info),
            current_workload=0,
            disk_available_least=0,
            host_ip="1.1.1.1",
            state="up",
            status="enabled",
            free_disk_gb=1028,
            free_ram_mb=7680,
            hypervisor_hostname="fake-mini",
            hypervisor_type="fake",
            hypervisor_version=1000,
            id=1,
            local_gb=1028,
            local_gb_used=0,
            memory_mb=8192,
            memory_mb_used=512,
            running_vms=0,
            vcpus=1,
            vcpus_used=0,
            service_id=2,
            host='043b3cacf6f34c90a7245151fc8ebcda',
            pci_device_pools=pci_device_pool.from_pci_stats(
                                      {"count": 5,
                                       "vendor_id": "8086",
                                       "product_id": "1520",
                                       "keya": "valuea",
                                       "key1": "value1",
                                       "numa_node": 1}),)
        self.fake_service = objects.Service(
            id=2,
            host='043b3cacf6f34c90a7245151fc8ebcda',
            disabled=False,
            disabled_reason=None)

    @mock.patch("nova.servicegroup.API.service_is_up", return_value=True)
    @mock.patch("nova.objects.Service.get_by_compute_host")
    @mock.patch("nova.objects.ComputeNode.get_by_id")
    def test_pci_show(self, mock_obj, mock_svc_get, mock_service):
        mock_obj.return_value = self.fake_compute_node
        mock_svc_get.return_value = self.fake_service
        hypervisor_id = 1
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-pci-show-resp',
                              subs, response, 200)

    @mock.patch("nova.servicegroup.API.service_is_up", return_value=True)
    @mock.patch("nova.objects.Service.get_by_compute_host")
    @mock.patch("nova.objects.ComputeNodeList.get_all")
    def test_pci_detail(self, mock_obj, mock_svc_get, mock_service):
        mock_obj.return_value = [self.fake_compute_node]
        mock_svc_get.return_value = self.fake_service
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/detail')

        self._verify_response('hypervisors-pci-detail-resp',
                              subs, response, 200)


class PciSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "os-pci"

    def setUp(self):
        raise testtools.TestCase.skipException(skip_msg)

    def _fake_pci_device_get_by_id(self, context, id):
        return fake_db_dev_1

    def _fake_pci_device_get_all_by_node(self, context, id):
        return [fake_db_dev_1, fake_db_dev_2]

    def test_pci_show(self):
        self.stub_out('nova.db.pci_device_get_by_id',
                      self._fake_pci_device_get_by_id)
        response = self._do_get('os-pci/1')
        self._verify_response('pci-show-resp', {}, response, 200)

    def test_pci_index(self):
        self.stub_out('nova.db.pci_device_get_all_by_node',
                      self._fake_pci_device_get_all_by_node)
        response = self._do_get('os-pci')
        self._verify_response('pci-index-resp', {}, response, 200)

    def test_pci_detail(self):
        self.stub_out('nova.db.pci_device_get_all_by_node',
                      self._fake_pci_device_get_all_by_node)
        response = self._do_get('os-pci/detail')
        self._verify_response('pci-detail-resp', {}, response, 200)
