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

from nova.compute import power_state as compute_power_state
from nova import context
from nova import exception
from nova import test
from nova.tests.unit import fake_instance
from nova.virt import fake
from nova.virt.zvm import driver
from nova.virt.zvm import guest


class TestZVMGuestOp(test.NoDBTestCase):
    def setUp(self):
        super(TestZVMGuestOp, self).setUp()
        self.flags(cloud_connector_url='https://1.1.1.1:1111',
                   image_tmp_path='/test/image',
                   reachable_timeout=300, group='zvm')
        self.flags(my_ip='192.168.1.1',
                   instance_name_template='test%04x')
        with test.nested(
            mock.patch('nova.virt.zvm.utils.ConnectorClient.call'),
            mock.patch('pwd.getpwuid'),
        ) as (mcall, getpwuid):
            getpwuid.return_value = mock.Mock(pw_name='test')
            mcall.return_value = {'hypervisor_hostname': 'TESTHOST',
                                  'ipl_time': 'TESTTIME'}
            self._driver = driver.ZVMDriver(fake.FakeVirtAPI())
            self._hypervisor = self._driver._hypervisor

        self._context = context.RequestContext('fake_user', 'fake_project')
        self._instance = fake_instance.fake_instance_obj(
                                self._context)
        self._guest = guest.Guest(self._hypervisor, self._instance,
                                  self._driver.virtapi)

    def test_private_mapping_power_state(self):
        status = self._guest._mapping_power_state('on')
        self.assertEqual(compute_power_state.RUNNING, status)
        status = self._guest._mapping_power_state('off')
        self.assertEqual(compute_power_state.SHUTDOWN, status)
        status = self._guest._mapping_power_state('bad')
        self.assertEqual(compute_power_state.NOSTATE, status)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_info_err_instance_not_found(self, call):
        res = {'overallRC': 404, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(results=res)
        self.assertRaises(exception.InstanceNotFound, self._guest.get_info)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_info_err_general(self, call):
        res = {'overallRC': 500, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(res)
        self.assertRaises(exception.ZVMConnectorError, self._guest.get_info)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_info(self, call):
        call.return_value = 'on'
        info = self._guest.get_info()
        call.assert_called_once_with('guest_get_power_state',
                                     self._instance['name'])
        self.assertEqual(info.state, compute_power_state.RUNNING)
