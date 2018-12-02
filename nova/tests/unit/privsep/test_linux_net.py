# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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

import nova.privsep.linux_net
from nova import test


class LinuxNetTestCase(test.NoDBTestCase):
    """Test networking helpers."""

    def _create_veth_pair(self, calls):
        with mock.patch('oslo_concurrency.processutils.execute',
                        return_value=('', '')) as ex:
            nova.privsep.linux_net._create_veth_pair_inner(
                'fake-dev1', 'fake-dev2')
            ex.assert_has_calls(calls)

    def test_create_veth_pair(self):
        calls = [
            mock.call('ip', 'link', 'add', 'fake-dev1', 'type', 'veth',
                      'peer', 'name', 'fake-dev2'),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'up'),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'promisc', 'on'),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'up'),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'promisc', 'on')
        ]
        self._create_veth_pair(calls)

    @mock.patch('oslo_concurrency.processutils.execute',
                return_value=('', ''))
    def test_set_device_mtu_default(self, mock_exec):
        calls = []
        nova.privsep.linux_net._set_device_mtu_inner('fake-dev', None)
        mock_exec.assert_has_calls(calls)
