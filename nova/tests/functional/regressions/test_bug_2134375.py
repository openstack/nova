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

import nova.conf

from unittest import mock

from nova import context
from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers

CONF = nova.conf.CONF


class TestPortErrorDuringCreateServer(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Regression test for bug 2134375"""

    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.placement = self.useFixture(func_fixtures.PlacementFixture()).api

        self.api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.admin_api = self.api_fixture.admin_api
        self.admin_api.microversion = 'latest'
        self.api = self.admin_api

        self.start_service('conductor')
        self.start_service('scheduler')

        self.compute = self._start_compute('host1')

        self.neutron._networks[
            self.neutron.network_1['id']] = self.neutron.network_1
        self.neutron._subnets[
            self.neutron.subnet_1['id']] = self.neutron.subnet_1

        self.neutron._networks[
            self.neutron.network_2['id']] = self.neutron.network_2
        self.neutron._subnets[
            self.neutron.subnet_2['id']] = self.neutron.subnet_2

        self.ctxt = context.get_admin_context()

    @mock.patch('nova.network.neutron.API._update_port',
                # fails on the 1st call and triggers the cleanup
                side_effect=exception.PortNotFound(
                    '00000000-0000-0000-0000-000000000000'))
    def test_update_ports_for_instance_fails_delete_all_created_ports(
        self, mock_update_port):
        self.flags(max_attempts=1, group='scheduler')

        # There already two port
        self.assertEqual(2, len(self.neutron.list_ports(
            is_admin=True)['ports']))

        self._create_server(name= 'test01',
            networks=[{'uuid': self.neutron.network_1['id']},
                      {'uuid': self.neutron.network_2['id']}],
            expected_state='ERROR')

        # FIXME should delete all created ports
        self.assertEqual(3, len(self.neutron.list_ports(
            is_admin=True)['ports']))
