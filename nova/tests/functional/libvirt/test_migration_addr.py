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

from unittest import mock

from oslo_config import cfg

from nova.tests.functional.libvirt import base

CONF = cfg.CONF


class LibvirtMigrationAddrTest(base.ServersTestBase):
    ADMIN_API = True

    def setUp(self):
        super().setUp()

    def _test_move_op(self, move_op, migration_inbound_addr=None):
        if migration_inbound_addr:
            CONF.set_default(
                "migration_inbound_addr", migration_inbound_addr,
                group="libvirt")

        self.start_compute(hostname='compute1')
        self.start_compute(hostname='compute2')

        server = self._create_server(host='compute1', networks="none")

        move_op(server)

        migration = self._wait_for_migration_status(
            server, ["finished", "done"])

        if migration_inbound_addr:
            self.assertEqual(migration['dest_host'], "compute2")
        else:
            self.assertEqual(migration['dest_host'], CONF.my_ip)

    def _cold_migrate(self, server):
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver' +
            '.migrate_disk_and_power_off',
            return_value='{}'
        ):
            self._migrate_server(server)

    def _resize(self, server):
        flavors = self.api.get_flavors()

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver' +
            '.migrate_disk_and_power_off',
            return_value='{}'
        ):
            self._resize_server(server, flavors[1]['id'])

    def _evacuate(self, server):
        service_id = self.admin_api.get_services(
            host="compute1", binary='nova-compute')[0]['id']
        self.admin_api.put_service_force_down(service_id, True)
        self._evacuate_server(server, expected_state='ACTIVE')

    def test_cold_migrate_with_ip(self):
        self._test_move_op(self._cold_migrate, migration_inbound_addr=None)

    def test_cold_migrate_with_hostname(self):
        self._test_move_op(self._cold_migrate, migration_inbound_addr="%s")

    def test_resize_with_ip(self):
        self._test_move_op(self._resize, migration_inbound_addr=None)

    def test_resize_with_hostname(self):
        self._test_move_op(self._resize, migration_inbound_addr="%s")

    def test_evacuate_with_ip(self):
        self._test_move_op(self._evacuate, migration_inbound_addr=None)

    def test_evacuate_with_hostname(self):
        self._test_move_op(self._evacuate, migration_inbound_addr="%s")
