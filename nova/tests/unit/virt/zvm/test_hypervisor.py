# Copyright 2017,2018 IBM Corp.
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

from nova import exception
from nova import test
from nova.virt.zvm import driver as zvmdriver


class TestZVMHypervisor(test.NoDBTestCase):

    def setUp(self):
        super(TestZVMHypervisor, self).setUp()
        self.flags(cloud_connector_url='https://1.1.1.1:1111', group='zvm')
        with mock.patch('nova.virt.zvm.utils.'
                        'ConnectorClient.call') as mcall:
            mcall.return_value = {'hypervisor_hostname': 'TESTHOST'}
            driver = zvmdriver.ZVMDriver('virtapi')
            self._hypervisor = driver._hypervisor

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_available_resource(self, call):
        host_info = {'disk_available': 1144,
                     'ipl_time': 'IPL at 11/14/17 10:47:44 EST',
                     'vcpus_used': 4,
                     'hypervisor_type': 'zvm',
                     'disk_total': 2000,
                     'zvm_host': 'TESTHOST',
                     'memory_mb': 78192,
                     'cpu_info': {'cec_model': '2827',
                                  'architecture': 's390x'},
                     'vcpus': 84,
                     'hypervisor_hostname': 'TESTHOST',
                     'hypervisor_version': 640,
                     'disk_used': 856,
                     'memory_mb_used': 8192}
        call.return_value = host_info
        results = self._hypervisor.get_available_resource()
        self.assertEqual(host_info, results)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_available_resource_err_case(self, call):
        res = {'overallRC': 1, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(res)
        results = self._hypervisor.get_available_resource()
        # Should return an empty dict
        self.assertFalse(results)

    def test_get_available_nodes(self):
        nodes = self._hypervisor.get_available_nodes()
        self.assertEqual(['TESTHOST'], nodes)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_list_names(self, call):
        call.return_value = ['vm1', 'vm2']
        inst_list = self._hypervisor.list_names()
        self.assertEqual(['vm1', 'vm2'], inst_list)
