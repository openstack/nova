# Copyright 2014 OpenStack Foundation
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

import uuid

from nova import exception
from nova import test
from nova import utils

from nova.tests import utils as test_utils

from nova.openstack.common import processutils
from nova.virt.docker import network

import mock


class NetworkTestCase(test.NoDBTestCase):
    @mock.patch.object(utils, 'execute')
    def test_teardown_delete_network(self, utils_mock):
        id = "second-id"
        utils_mock.return_value = ("first-id\nsecond-id\nthird-id\n", None)
        network.teardown_network(id)
        utils_mock.assert_called_with('ip', 'netns', 'delete', id,
                              run_as_root=True)

    @mock.patch.object(utils, 'execute')
    def test_teardown_network_not_in_list(self, utils_mock):
        utils_mock.return_value = ("first-id\nsecond-id\nthird-id\n", None)
        network.teardown_network("not-in-list")
        utils_mock.assert_called_with('ip', '-o', 'netns', 'list')

    @mock.patch.object(network, 'LOG')
    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError)
    def test_teardown_network_fails(self, utils_mock, log_mock):
        # Call fails but method should not fail.
        # Error will be caught and logged.
        utils_mock.return_value = ("first-id\nsecond-id\nthird-id\n", None)
        id = "third-id"
        network.teardown_network(id)
        log_mock.warning.assert_called_with(mock.ANY, id)

    def test_find_gateway(self):
        instance = {'uuid': uuid.uuid4()}
        network_info = test_utils.get_test_network_info()
        first_net = network_info[0]['network']
        first_net['subnets'][0]['gateway']['address'] = '10.0.0.1'
        self.assertEqual('10.0.0.1', network.find_gateway(instance, first_net))

    def test_cannot_find_gateway(self):
        instance = {'uuid': uuid.uuid4()}
        network_info = test_utils.get_test_network_info()
        first_net = network_info[0]['network']
        first_net['subnets'] = []
        self.assertRaises(exception.InstanceDeployFailure,
                          network.find_gateway, instance, first_net)

    def test_find_fixed_ip(self):
        instance = {'uuid': uuid.uuid4()}
        network_info = test_utils.get_test_network_info()
        first_net = network_info[0]['network']
        first_net['subnets'][0]['cidr'] = '10.0.0.0/24'
        first_net['subnets'][0]['ips'][0]['type'] = 'fixed'
        first_net['subnets'][0]['ips'][0]['address'] = '10.0.1.13'
        self.assertEqual('10.0.1.13/24', network.find_fixed_ip(instance,
                                                               first_net))

    def test_cannot_find_fixed_ip(self):
        instance = {'uuid': uuid.uuid4()}
        network_info = test_utils.get_test_network_info()
        first_net = network_info[0]['network']
        first_net['subnets'] = []
        self.assertRaises(exception.InstanceDeployFailure,
                          network.find_fixed_ip, instance, first_net)
