# Copyright (C) 2015 Red Hat, Inc
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

from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt


class RealTimeServersTest(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        super(RealTimeServersTest, self).setUp()
        self.flags(sysinfo_serial='none', group='libvirt')

    def test_no_dedicated_cpu(self):
        flavor_id = self._create_flavor(extra_spec={'hw:cpu_realtime': 'yes'})
        server = self._build_server(flavor_id=flavor_id)

        # Cannot set realtime policy in a non dedicated cpu pinning policy
        self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server, {'server': server})

    def test_no_realtime_mask(self):
        flavor_id = self._create_flavor(extra_spec={
            'hw:cpu_realtime': 'yes', 'hw:cpu_policy': 'dedicated'})
        server = self._build_server(flavor_id=flavor_id)

        # Cannot set realtime policy if not vcpus mask defined
        self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server, {'server': server})

    def test_success(self):
        self.flags(cpu_dedicated_set='0-7', group='compute')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        fake_connection = self._get_connection(host_info=host_info)
        self.mock_conn.return_value = fake_connection

        self.compute = self.start_service('compute', host='test_compute0')

        flavor_id = self._create_flavor(extra_spec={
            'hw:cpu_realtime': 'yes',
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_realtime_mask': '^1'})
        server = self._create_server(flavor_id=flavor_id)

        self._delete_server(server)
