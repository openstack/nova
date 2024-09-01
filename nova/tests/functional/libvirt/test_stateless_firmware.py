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
import fixtures
from unittest import mock

from lxml import etree
from oslo_utils.fixture import uuidsentinel
from oslo_utils import versionutils

from nova import conf
from nova import context as nova_context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import migration as libvirt_migration

CONF = conf.CONF


class LibvirtStatelessFirmwareTest(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
):

    # many move operations are admin-only
    ADMIN_API = True

    microversion = 'latest'

    def setUp(self):
        super().setUp()
        self.context = nova_context.get_admin_context()
        # Add the stateless firmware image to the glance fixture
        hw_fw_stateless_image = copy.deepcopy(self.glance.image1)
        hw_fw_stateless_image['id'] = uuidsentinel.fw_stateless_image_id
        hw_fw_stateless_image['properties']['hw_machine_type'] = 'q35'
        hw_fw_stateless_image['properties']['hw_firmware_type'] = 'uefi'
        hw_fw_stateless_image['properties']['hw_firmware_stateless'] = True
        self.glance.create(self.context, hw_fw_stateless_image)

        self._start_compute()

        self.guest_configs = {}
        orig_get_config = self.computes['compute1'].driver._get_guest_config

        def _get_guest_config(_self, *args, **kwargs):
            guest_config = orig_get_config(*args, **kwargs)
            instance = args[0]
            self.guest_configs[instance.uuid] = guest_config
            return self.guest_configs[instance.uuid]

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.LibvirtDriver._get_guest_config',
            _get_guest_config))

        # disk.rescue image_create ignoring privsep
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.imagebackend._update_utime_ignore_eacces'))

        # dir to create 'unrescue.xml'
        def fake_path(_self, *args, **kwargs):
            return CONF.instances_path

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.utils.get_instance_path', fake_path))

    def _start_compute(self, hostname='compute1'):
        self.start_compute(
            hostname,
            libvirt_version=versionutils.convert_version_to_int(
                libvirt_driver.MIN_LIBVIRT_STATELESS_FIRMWARE
            ))
        caps = self.computes[hostname].driver.capabilities
        self.assertTrue(caps['supports_stateless_firmware'])

    def _create_server_with_stateless_firmware(self):
        server = self._create_server(
            image_uuid=uuidsentinel.fw_stateless_image_id,
            networks='none',
        )
        self.addCleanup(self._delete_server, server)
        return server

    def _create_server_without_stateless_firmware(self):
        server = self._create_server(
            image_uuid=self.glance.image1['id'],
            networks='none',
        )
        self.addCleanup(self._delete_server, server)
        return server

    def _assert_server_has_stateless_firmware(self, server_id):
        instance = objects.Instance.get_by_uuid(self.context, server_id)
        self.assertTrue(
            instance.image_meta.properties.hw_firmware_stateless
        )
        self.assertTrue(
            self.guest_configs[server_id].os_loader_stateless
        )
        del self.guest_configs[server_id]

    def _assert_server_has_no_stateless_firmware(self, server_id):
        instance = objects.Instance.get_by_uuid(self.context, server_id)
        self.assertIsNone(
            instance.image_meta.properties.get('hw_firmware_stateless')
        )
        self.assertIsNone(
            self.guest_configs[server_id].os_loader_stateless
        )
        del self.guest_configs[server_id]

    def test_create_server(self):
        """Assert new instance is created with stateless firmware only when
           the image has the required properties
        """
        server_with = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server_with['id'])

        server_without = self._create_server_without_stateless_firmware()
        self._assert_server_has_no_stateless_firmware(server_without['id'])

    def test_live_migrate_server(self):
        # create a server with stateless firmware
        self.server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(self.server['id'])

        self._start_compute('compute2')
        self.src = self.computes['compute1']
        self.dest = self.computes['compute2']

        self.migration_xml = None
        orig_get_updated_guest_xml = libvirt_migration.get_updated_guest_xml

        def migration_xml_wrapper(*args, **kwargs):
            self.migration_xml = orig_get_updated_guest_xml(*args, **kwargs)
            return self.migration_xml

        with mock.patch(
            'nova.virt.libvirt.migration.get_updated_guest_xml',
            side_effect=migration_xml_wrapper
        ) as fake_get_updated_guest_xml:
            self._live_migrate(self.server)

        fake_get_updated_guest_xml.assert_called_once()
        server = etree.fromstring(self.migration_xml)
        self.assertEqual('yes', server.find('./os/loader').get('stateless'))

    def test_migrate_server(self):
        self._start_compute('compute2')

        # create a server with stateless firmware
        server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server['id'])

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # cold migrate the server
            self._migrate_server(server)

        self._assert_server_has_stateless_firmware(server['id'])

        server = self._confirm_resize(server)

    def test_migrate_server_revert(self):
        self._start_compute('compute2')

        # create a server with stateless firmware
        server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server['id'])

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # cold migrate the server
            self._migrate_server(server)

        self._assert_server_has_stateless_firmware(server['id'])

        server = self._revert_resize(server)
        self._assert_server_has_stateless_firmware(server['id'])

    def test_shelve_and_unshelve_to_same_host(self):
        # create a server with stateless firmware
        server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server['id'])

        # shelve the server
        server = self._shelve_server(server)

        # uneshelve the server. the server is started at the same compute
        server = self._unshelve_server(server)
        self._assert_server_has_stateless_firmware(server['id'])

    def test_shelve_and_unshelve_to_different_host(self):
        # create a server with stateless firmware
        server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server['id'])

        # shelve the server
        server = self._shelve_server(server)

        # force down the compute node
        source_compute_id = self.admin_api.get_services(
            host='compute1', binary='nova-compute')[0]['id']
        self.computes['compute1'].stop()
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # start a new compute node and unshelve the server
        self._start_compute('compute2')
        server = self._unshelve_server(server)
        self.assertEqual(
            'compute2', server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        self._assert_server_has_stateless_firmware(server['id'])

    def test_evacuate_server(self):
        # create a server with stateless firmware
        server = self._create_server_with_stateless_firmware()
        self.assertEqual(
            'compute1', server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        self._assert_server_has_stateless_firmware(server['id'])

        # force down the compute node
        source_compute_id = self.admin_api.get_services(
            host='compute1', binary='nova-compute')[0]['id']
        self.computes['compute1'].stop()
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # start a new compute node and evecuate the server
        self._start_compute('compute2')
        server = self._evacuate_server(server, expected_host='compute2')
        self.assertEqual(
            'compute2', server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        self._assert_server_has_stateless_firmware(server['id'])

    def test_rescue_unrescue_server(self):
        # create a server without stateless firmware
        server = self._create_server_with_stateless_firmware()
        self._assert_server_has_stateless_firmware(server['id'])

        self.api.post_server_action(server['id'], {
            "rescue": {
                "rescue_image_ref": self.glance.image1['id']
            }
        })
        server = self._wait_for_state_change(server, 'RESCUE')

        # The instance object should still expect stateless firmware
        instance = objects.Instance.get_by_uuid(self.context, server['id'])
        self.assertTrue(
            instance.image_meta.properties.hw_firmware_stateless
        )

        # but the actual xml config should not
        self.assertIsNone(
            self.guest_configs[server['id']].os_loader_stateless
        )
        del self.guest_configs[server['id']]

        self.api.post_server_action(server['id'], {
            "unrescue": None
        })
        server = self._wait_for_state_change(server, 'ACTIVE')
        # NOTE(tkajinam): Unrescue restores the original xml file so skip
        #                 asserting its content.

    def test_rebuild_server(self):
        # create a server without stateless firmware
        server = self._create_server_without_stateless_firmware()
        self._assert_server_has_no_stateless_firmware(server['id'])

        # rebuild using the image with stateless firmware
        server = self._rebuild_server(
            server, uuidsentinel.fw_stateless_image_id)
        self._assert_server_has_stateless_firmware(server['id'])

        # rebuild using the image without stateless firmware
        server = self._rebuild_server(server, self.glance.image1['id'])
        self._assert_server_has_no_stateless_firmware(server['id'])
