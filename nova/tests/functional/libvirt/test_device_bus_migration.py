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

import datetime
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver as libvirt_driver


class LibvirtDeviceBusMigration(base.ServersTestBase):

    microversion = 'latest'
    # needed for move operations
    ADMIN_API = True

    def setUp(self):
        super().setUp()
        self.context = nova_context.get_admin_context()
        self.compute_hostname = self.start_compute()
        self.compute = self.computes[self.compute_hostname]

    def _unset_stashed_image_properties(self, server_id, properties):
        instance = objects.Instance.get_by_uuid(self.context, server_id)
        for p in properties:
            instance.system_metadata.pop(f'image_{p}')
        instance.save()

    def _assert_stashed_image_properties(self, server_id, properties):
        instance = objects.Instance.get_by_uuid(self.context, server_id)
        for p, value in properties.items():
            self.assertEqual(instance.system_metadata.get(f'image_{p}'), value)

    def _assert_stashed_image_properties_persist(self, server, properties):
        # Assert the stashed properties persist across a host reboot
        self.restart_compute_service(self.compute)
        self._assert_stashed_image_properties(server['id'], properties)

        # Assert the stashed properties persist across a guest reboot
        self._reboot_server(server, hard=True)
        self._assert_stashed_image_properties(server['id'], properties)

        # Assert the stashed properties persist across a migration
        if 'other_compute' not in self.computes:
            self.start_compute('other_compute')
        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            self._migrate_server(server)
        self._confirm_resize(server)
        self._assert_stashed_image_properties(server['id'], properties)

    def test_default_image_property_registration(self):
        """Assert that the defaults for various hw image properties don't
        change over the lifecycle of an instance.
        """
        default_image_properties = {
            'hw_machine_type': 'pc',
            'hw_cdrom_bus': 'ide',
            'hw_disk_bus': 'virtio',
            'hw_input_bus': 'usb',
            'hw_pointer_model': 'usbtablet',
            'hw_video_model': 'virtio',
            'hw_vif_model': 'virtio',
        }

        server = self._create_server(networks='none')
        self._assert_stashed_image_properties(
            server['id'], default_image_properties)

        # Unset the defaults here to ensure that init_host resets them
        # when the compute restarts the libvirt driver
        self._unset_stashed_image_properties(
            server['id'], libvirt_driver.REGISTER_IMAGE_PROPERTY_DEFAULTS)

        # Assert the defaults persist across a host reboot, guest reboot, and
        # guest migration
        self._assert_stashed_image_properties_persist(
            server, default_image_properties)

    def test_non_default_image_property_registration(self):
        """Assert that non-default values for various hw image properties
        don't change over the lifecycle of an instance.
        """
        non_default_image_properties = {
            'hw_machine_type': 'q35',
            'hw_cdrom_bus': 'sata',
            'hw_disk_bus': 'sata',
            'hw_input_bus': 'virtio',
            'hw_video_model': 'qxl',
            'hw_vif_model': 'e1000',
        }
        self.glance.create(
            None,
            {
                'id': uuids.hw_bus_model_image_uuid,
                'name': 'hw_bus_model_image',
                'created_at': datetime.datetime(2011, 1, 1, 1, 2, 3),
                'updated_at': datetime.datetime(2011, 1, 1, 1, 2, 3),
                'deleted_at': None,
                'deleted': False,
                'status': 'active',
                'is_public': False,
                'container_format': 'bare',
                'disk_format': 'qcow2',
                'size': '74185822',
                'min_ram': 0,
                'min_disk': 0,
                'protected': False,
                'visibility': 'public',
                'tags': [],
                'properties': non_default_image_properties,
            }
        )
        server = self._create_server(
            networks='none', image_uuid=uuids.hw_bus_model_image_uuid)
        self._assert_stashed_image_properties(
            server['id'], non_default_image_properties)

        # Assert the non defaults persist across a host reboot, guest reboot,
        # and guest migration
        self._assert_stashed_image_properties_persist(
            server, non_default_image_properties)

    def test_default_image_property_persists_across_osinfo_changes(self):
        # Create a server with default image properties
        default_image_properties = {
            'hw_vif_model': 'virtio',
            'hw_disk_bus': 'virtio',
        }
        server = self._create_server(networks='none')
        self._assert_stashed_image_properties(
            server['id'], default_image_properties)

        with test.nested(
            mock.patch('nova.virt.osinfo.HardwareProperties.network_model',
                new=mock.PropertyMock()),
            mock.patch('nova.virt.osinfo.HardwareProperties.disk_model',
                new=mock.PropertyMock())
        ) as (mock_nw_model, mock_disk_model):
            # osinfo returning new things
            mock_nw_model.return_value = 'e1000'
            mock_disk_model.return_value = 'sata'

            # Assert the defaults persist across a host reboot, guest reboot,
            # and guest migration
            self._assert_stashed_image_properties_persist(
                server, default_image_properties)

    def test_default_image_property_persists_across_host_flag_changes(self):
        # Set the default to ps2 via host flag
        self.flags(pointer_model='ps2mouse')
        # Restart compute to pick up ps2 setting, which means the guest will
        # not get a prescribed pointer device
        self.restart_compute_service(self.compute)

        # Create a server with default image properties
        default_image_properties1 = {
            'hw_pointer_model': None,
            'hw_input_bus': None,
        }
        server1 = self._create_server(networks='none')
        self._assert_stashed_image_properties(
            server1['id'], default_image_properties1)

        # Assert the defaults persist across a host flag change
        self.flags(pointer_model='usbtablet')
        # Restart compute to pick up usb setting
        self.restart_compute_service(self.compute)
        self._assert_stashed_image_properties(
            server1['id'], default_image_properties1)

        # Assert the defaults persist across a host reboot, guest reboot, and
        # guest migration
        self._assert_stashed_image_properties_persist(
            server1, default_image_properties1)

        # Create a server with new default image properties since the host flag
        # change
        default_image_properties2 = {
            'hw_pointer_model': 'usbtablet',
            'hw_input_bus': 'usb',
        }
        server2 = self._create_server(networks='none')
        self._assert_stashed_image_properties(
            server2['id'], default_image_properties2)

        # Assert the defaults persist across a host reboot, guest reboot, and
        # guest migration
        self._assert_stashed_image_properties_persist(
            server2, default_image_properties2)

        # Finally, try changing the host flag again to None. Note that it is
        # not possible for a user to specify None for this option:
        # https://bugs.launchpad.net/nova/+bug/1866106
        self.flags(pointer_model=None)
        # Restart compute to pick up None setting
        self.restart_compute_service(self.compute)
        self._assert_stashed_image_properties(
            server1['id'], default_image_properties1)
        self._assert_stashed_image_properties(
            server2['id'], default_image_properties2)

        # Create a server since the host flag change to None. The defaults
        # should be the same as for ps2mouse
        server3 = self._create_server(networks='none')
        self._assert_stashed_image_properties(
            server3['id'], default_image_properties1)

        # Assert the defaults persist across a host reboot, guest reboot, and
        # guest migration for server1, server2, and server3
        self._assert_stashed_image_properties_persist(
            server1, default_image_properties1)
        self._assert_stashed_image_properties_persist(
            server2, default_image_properties2)
        self._assert_stashed_image_properties_persist(
            server3, default_image_properties1)
