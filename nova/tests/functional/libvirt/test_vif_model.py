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

import datetime

from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids

import nova
from nova.tests.functional.libvirt import base

CONF = cfg.CONF


class LibvirtVifModelTest(base.ServersTestBase):
    ADMIN_API = True

    def setUp(self):
        CONF.set_default("image_metadata_prefilter", True, group='scheduler')
        super().setUp()

        self.glance.create(
            None,
            {
                'id': uuids.image_vif_model_igb,
                'name': 'image-with-igb',
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
                'properties': {
                    'hw_vif_model': 'igb',
                },
            }
        )

    def test_boot_with_vif_model_igb(self):
        orig_create = nova.virt.libvirt.guest.Guest.create
        self.xml = ""

        def fake_create(cls, xml, host):
            self.xml = xml
            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        self.start_compute(
            hostname='compute1',
            libvirt_version=9003000,
            qemu_version=8000000,
        )

        self._create_server(image_uuid=uuids.image_vif_model_igb)
        self.assertIn('<model type="igb"/>', self.xml)

    def _test_boot_with_vif_model_igb_old_hypervisor(
        self, libvirt_version, qemu_version
    ):
        self.start_compute(
            hostname='compute1',
            libvirt_version=libvirt_version,
            qemu_version=qemu_version,
        )

        server = self._create_server(
            image_uuid=uuids.image_vif_model_igb, expected_state='ERROR')
        self.assertEqual(
            "No valid host was found. ", server['fault']['message'])

    def test_boot_with_vif_model_igb_old_qemu(self):
        self._test_boot_with_vif_model_igb_old_hypervisor(
            libvirt_version=9003000, qemu_version=7000000)

    def test_boot_with_vif_model_igb_old_libvirt(self):
        self._test_boot_with_vif_model_igb_old_hypervisor(
            libvirt_version=9002000, qemu_version=8000000)
