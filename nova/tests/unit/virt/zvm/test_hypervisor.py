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

from nova import context
from nova import exception
from nova import test
from nova.tests.unit import fake_instance
from nova.virt.zvm import driver as zvmdriver


class TestZVMHypervisor(test.NoDBTestCase):

    def setUp(self):
        super(TestZVMHypervisor, self).setUp()
        self.flags(instance_name_template='abc%5d')
        self.flags(cloud_connector_url='https://1.1.1.1:1111', group='zvm')
        with mock.patch('nova.virt.zvm.utils.'
                        'ConnectorClient.call') as mcall:
            mcall.return_value = {'hypervisor_hostname': 'TESTHOST',
                                  'ipl_time': 'IPL at 11/14/17 10:47:44 EST'}
            driver = zvmdriver.ZVMDriver('virtapi')
            self._hypervisor = driver._hypervisor

        self._context = context.RequestContext('fake_user', 'fake_project')

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

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_host_uptime(self, call):
        host_info = {'disk_available': 1144,
                     'ipl_time': 'IPL at 11/14/17 10:47:44 EST',
                     'memory_mb_used': 8192.0}
        call.return_value = host_info

        time = self._hypervisor.get_host_uptime()
        self.assertEqual('IPL at 11/14/17 10:47:44 EST', time)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.list_names')
    def test_private_guest_exists_true(self, list_names):
        instance = fake_instance.fake_instance_obj(self._context)
        list_names.return_value = [instance.name.upper(), 'TEST0002']
        res = self._hypervisor.guest_exists(instance)
        self.assertTrue(res)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.list_names')
    def test_private_guest_exists_false(self, list_names):
        list_names.return_value = ['dummy1', 'dummy2']
        instance = fake_instance.fake_instance_obj(self._context)
        res = self._hypervisor.guest_exists(instance)
        self.assertFalse(res)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_capture(self, mcall):
        self._hypervisor.guest_capture('n1', 'image-id')
        mcall.assert_called_once_with('guest_capture', 'n1', 'image-id')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_image_export(self, mcall):
        self._hypervisor.image_export('image-id', 'path')
        mcall.assert_called_once_with('image_export', 'image-id', 'path',
                                      remote_host=self._hypervisor._rhost)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_image_delete(self, mcall):
        self._hypervisor.image_delete('image-id')
        mcall.assert_called_once_with('image_delete', 'image-id')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_softstop(self, mcall):
        self._hypervisor.guest_softstop('guest')
        mcall.assert_called_once_with('guest_softstop', 'guest',
                                      poll_interval=0, timeout=0)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_pause(self, mcall):
        self._hypervisor.guest_pause('guest')
        mcall.assert_called_once_with('guest_pause', 'guest')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_unpause(self, mcall):
        self._hypervisor.guest_unpause('guest')
        mcall.assert_called_once_with('guest_unpause', 'guest')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_reboot(self, mcall):
        self._hypervisor.guest_reboot('guest')
        mcall.assert_called_once_with('guest_reboot', 'guest')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_reset(self, mcall):
        self._hypervisor.guest_reset('guest')
        mcall.assert_called_once_with('guest_reset', 'guest')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_guest_get_console_output(self, mcall):
        self._hypervisor.guest_get_console_output('guest')
        mcall.assert_called_once_with('guest_get_console_output', 'guest')
