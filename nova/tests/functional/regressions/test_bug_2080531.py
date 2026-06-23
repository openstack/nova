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

import copy
from unittest import mock

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class InterfaceAttachMtuRegressionTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression tests for bug 2080531.

    Attaching an interface from a network that is not already attached to the
    instance causes the existing VIFs in the info cache to lose their network
    MTU metadata. Live migration then consumes that stale info cache and can
    fail because the generated destination interface XML no longer matches the
    source guest interface MTU.
    """

    def setUp(self):
        super().setUp()

        self.useFixture(func_fixtures.PlacementFixture())
        self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.notifier = self.useFixture(
            nova_fixtures.NotificationFixture(self))

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.api.microversion = 'latest'

        self.start_service('conductor')
        self.start_service('scheduler')
        self.src = self._start_compute('src')
        self.dest = self._start_compute('dest')

        self.neutron._networks[
            self.neutron.network_2['id']] = self.neutron.network_2
        self.neutron._subnets[
            self.neutron.subnet_2['id']] = self.neutron.subnet_2

        self.attached_port = copy.deepcopy(self.neutron.port_2)
        self.attached_port.update({
            'id': '8b8f9f00-2d0d-4d43-a860-1a3a2a89f9d6',
            'mac_address': '00:0c:29:0d:11:75',
            'network_id': self.neutron.network_2['id'],
            'fixed_ips': [{
                'ip_address': '192.168.13.30',
                'subnet_id': self.neutron.subnet_2['id'],
            }],
            'port_security_enabled': False,
            'security_groups': [],
        })
        self.neutron._ports[self.attached_port['id']] = self.attached_port

        self.ctxt = context.get_admin_context()

    def _create_server_and_attach_interface_from_new_network(self):
        server = self._create_server(
            name='test-server-for-bug-2080531',
            networks=[{'port': self.neutron.port_1['id']}],
            host='src')

        nw_info = self._get_network_info_by_port(server['id'])
        self.assertEqual(
            1450,
            nw_info[self.neutron.port_1['id']]['network']['meta']['mtu'])

        self._attach_interface(server, self.attached_port['id'])
        return server

    def _get_network_info_by_port(self, instance_uuid):
        instance = objects.Instance.get_by_uuid(self.ctxt, instance_uuid)
        nw_info = instance.get_network_info()
        return {vif['id']: vif for vif in nw_info}

    def test_attach_interface_from_new_network_drops_existing_mtu(self):
        server = self._create_server_and_attach_interface_from_new_network()

        nw_info = self._get_network_info_by_port(server['id'])
        self.assertEqual(
            {self.neutron.port_1['id'], self.attached_port['id']},
            set(nw_info))
        self.assertEqual(
            1450,
            nw_info[self.attached_port['id']]['network']['meta']['mtu'])

        # FIXME bug 2080531: once fixed, this should be:
        # self.assertEqual(
        #     1450,
        #     nw_info[self.neutron.port_1['id']]['network']['meta']['mtu'])
        self.assertNotEqual(
            1450,
            nw_info[self.neutron.port_1['id']]['network']['meta'].get('mtu'))

    def test_live_migration_fails_after_interface_attach_drops_mtu(self):
        server = self._create_server_and_attach_interface_from_new_network()

        def fake_live_migration(
                ctxt, instance, dest, post_method, recover_method,
                block_migration=False, migrate_data=None):
            nw_info = {
                vif.port_id: vif.source_vif for vif in migrate_data.vifs}
            if nw_info[self.neutron.port_1['id']]['network']['meta'].get(
                    'mtu') != 1450:
                recover_method(ctxt, instance, dest, migrate_data)
                raise test.TestingException(
                    'Target network card MTU 0 does not match source 1450')
            post_method(ctxt, instance, dest, block_migration, migrate_data)

        with mock.patch.object(
                self.src.driver, 'live_migration',
                side_effect=fake_live_migration):
            # FIXME bug 2080531: once fixed, the migration should complete and
            # the server should move to dest.
            server = self._live_migrate(
                server, 'error', server_expected_state='ERROR')

        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])
