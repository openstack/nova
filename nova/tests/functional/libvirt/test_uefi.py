# Copyright (C) 2021 Red Hat, Inc.
# All Rights Reserved.
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

import datetime

from lxml import etree
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

import nova.conf
from nova import context as nova_context
from nova import objects
from nova.tests.functional.libvirt import base

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class UEFIServersTest(base.ServersTestBase):

    def assertInstanceHasUEFI(self, server):
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertIn('image_hw_machine_type', instance.system_metadata)
        self.assertEqual(
            'q35', instance.system_metadata['image_hw_machine_type'])
        self.assertIn('image_hw_firmware_type', instance.system_metadata)
        self.assertEqual(
            'uefi', instance.system_metadata['image_hw_firmware_type'])
        self.assertIn('image_os_secure_boot', instance.system_metadata)
        self.assertEqual(
            'required', instance.system_metadata['image_os_secure_boot'])

    def test_create_server(self):
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os>
                  <type machine='q35'>hvm</type>
                  <loader type='pflash' readonly='yes'
                    secure='yes'>/usr/share/OVMF/OVMF_CODE.secboot.fd</loader>
                  <nvram template='/usr/share/OVMF/OVMF_VARS.secboot.fd'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,  # noqa: E501
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute()

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(2021, 1, 2, 3, 4, 5)
        uefi_image = {
            'id': uuids.uefi_image,
            'name': 'uefi_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': '74185822',
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
                'os_secure_boot': 'required',
            }
        }
        self.glance.create(None, uefi_image)

        server = self._create_server(image_uuid=uuids.uefi_image)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasUEFI(server)
