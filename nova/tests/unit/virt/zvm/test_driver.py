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


class TestZVMDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestZVMDriver, self).setUp()
        self.flags(cloud_connector_url='https://1.1.1.1:1111', group='zvm')
        with mock.patch('nova.virt.zvm.utils.'
                        'ConnectorClient.call') as mcall:
            mcall.return_value = {'hypervisor_hostname': 'TESTHOST'}
            self._driver = zvmdriver.ZVMDriver('virtapi')

    def test_driver_init_no_url(self):
        self.flags(cloud_connector_url=None, group='zvm')
        self.assertRaises(exception.ZVMDriverException,
                          zvmdriver.ZVMDriver, 'virtapi')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_available_resource_err_case(self, call):
        res = {'overallRC': 1, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(res)
        results = self._driver.get_available_resource()
        self.assertEqual(0, results['vcpus'])
        self.assertEqual(0, results['memory_mb_used'])
        self.assertEqual(0, results['disk_available_least'])
        self.assertEqual('TESTHOST', results['hypervisor_hostname'])
