# Copyright 2017 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import time

import nova.scheduler.utils
import nova.servicegroup
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestListServersIpFilter(test.TestCase):

    def setUp(self):
        super(TestListServersIpFilter, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.neutron = self.useFixture(
            nova_fixtures.NeutronFixture(self, multiple_ports=True))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.useFixture(nova_fixtures.PlacementFixture())

        self.start_service('conductor')
        # Use the chance scheduler to bypass filtering and just pick the single
        # compute host that we have.
        self.flags(driver='chance_scheduler', group='scheduler')
        self.start_service('scheduler')
        self.start_service('compute')
        self.start_service('consoleauth')

        self.useFixture(cast_as_call.CastAsCall(self))

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def wait_until_active_or_timeout(self, server_id):
        timeout = 0.0
        server = self.api.get_server(server_id)
        while server['status'] != "ACTIVE" and timeout < 10.0:
            time.sleep(.1)
            timeout += .1
            server = self.api.get_server(server_id)
        if server['status'] != "ACTIVE":
            self.fail(
                'Timed out waiting for server %s to be ACTIVE.' % server_id)
        return server

    def test_list_servers_with_ip_filters_regex(self):
        """Tests listing servers with IP filter regex.

        The compute API will perform a regex match on the ip filter and include
        all servers that have fixed IPs which match the filter.

        For example, consider we have two servers. The first server has IP
        10.1.1.1 and the second server has IP 10.1.1.10. If we list servers
        with filter ip=10.1.1.1 we should get back both servers because
        10.1.1.1 is a prefix of 10.1.1.10. If we list servers with filter
        ip=10.1.1.10 then we should only get back the second server.
        """

        # We're going to create two servers with unique ports, but the IPs on
        # the ports are close enough that one matches the regex for the other.
        # The ports used in this test are defined in the NeutronFixture.
        for port_id in (self.neutron.port_1['id'], self.neutron.port_2['id']):
            server = dict(
                name=port_id, imageRef=self.image_id, flavorRef=self.flavor_id,
                networks=[{'port': port_id}])
            server = self.api.post_server({'server': server})
            self.addCleanup(self.api.delete_server, server['id'])
            self.wait_until_active_or_timeout(server['id'])

        # Now list servers and filter on the IP of the first server.
        servers = self.api.get_servers(
            search_opts={
                'ip': self.neutron.port_1['fixed_ips'][0]['ip_address']})

        # We should get both servers back because the IP on the first server is
        # a prefix of the IP on the second server.
        self.assertEqual(2, len(servers),
                         'Unexpected number of servers returned when '
                         'filtering by ip=%s: %s' % (
                             self.neutron.port_1['fixed_ips'][0]['ip_address'],
                             servers))

        # Now list servers and filter on the IP of the second server.
        servers = self.api.get_servers(
            search_opts={
                'ip': self.neutron.port_2['fixed_ips'][0]['ip_address']})

        # We should get one server back because the IP on the second server is
        # unique between both servers.
        self.assertEqual(1, len(servers),
                         'Unexpected number of servers returned when '
                         'filtering by ip=%s: %s' % (
                             self.neutron.port_2['fixed_ips'][0]['ip_address'],
                             servers))
        self.assertEqual(self.neutron.port_2['fixed_ips'][0]['ip_address'],
                         servers[0]['addresses']['private-network'][0]['addr'])
