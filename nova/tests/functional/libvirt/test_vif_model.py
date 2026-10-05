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

        timestamp = datetime.datetime(
            2011, 1, 1, 1, 2, 3, tzinfo=datetime.timezone.utc
        )
        self.glance.create(
            None,
            {
                'id': uuids.image_vif_model_igb,
                'name': 'image-with-igb',
                'created_at': timestamp,
                'updated_at': timestamp,
                'deleted_at': None,
                'deleted': False,
                'status': 'active',
                'is_public': False,
                'container_format': 'bare',
                'disk_format': 'qcow2',
                'size': 74185822,
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
        )

        self._create_server(image_uuid=uuids.image_vif_model_igb)
        self.assertIn('<model type="igb"/>', self.xml)
