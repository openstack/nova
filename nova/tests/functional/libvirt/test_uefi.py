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
import os
import re
import textwrap
from unittest import mock

import ddt
import fixtures
from lxml import etree
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

import nova.conf
from nova import context as nova_context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.virt import hardware as hw

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


@ddt.ddt
class UEFIServersTest(base.ServersTestBase):

    def assertInstanceHasUEFI(
        self, server, secure_boot=False, stateless=False
    ):
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertIn('image_hw_machine_type', instance.system_metadata)
        self.assertEqual(
            'q35', instance.system_metadata['image_hw_machine_type'])
        self.assertIn('image_hw_firmware_type', instance.system_metadata)
        self.assertEqual(
            'uefi', instance.system_metadata['image_hw_firmware_type'])

        if secure_boot:
            self.assertIn('image_os_secure_boot', instance.system_metadata)
            self.assertEqual(
                'required', instance.system_metadata['image_os_secure_boot'])
        else:
            self.assertNotIn('image_os_secure_boot', instance.system_metadata)

        if stateless:
            self.assertIn('image_hw_firmware_stateless',
                          instance.system_metadata)
            self.assertTrue(
                instance.system_metadata['image_hw_firmware_stateless'])
        else:
            self.assertNotIn('image_hw_firmware_stateless',
                             instance.system_metadata)

    def test_create_server(self):
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='no'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute()

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
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
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
            }
        }
        self.glance.create(None, uefi_image)

        server = self._create_server(image_uuid=uuids.uefi_image)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasUEFI(server)

    def test_create_server_secure_boot(self):
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='yes'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='yes'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute()

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
        sb_image = {
            'id': uuids.sb_image,
            'name': 'sb_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': 74185822,
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
        self.glance.create(None, sb_image)

        server = self._create_server(image_uuid=uuids.sb_image)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasUEFI(server, secure_boot=True)

    def test_create_server_stateless(self):
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='no' stateless='yes'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute(libvirt_version=8006000)

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_STATELESS_FIRMWARE', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
        stateless_image = {
            'id': uuids.stateless_image,
            'name': 'stateless_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
                'hw_firmware_stateless': True,
            }
        }
        self.glance.create(None, stateless_image)

        server = self._create_server(image_uuid=uuids.stateless_image)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasUEFI(server, stateless=True)

    def test_create_server_secure_boot_stateless(self):
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='yes'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='yes' stateless='yes'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,  # noqa: E501
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute(libvirt_version=8006000)

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)
        self.assertIn('COMPUTE_SECURITY_STATELESS_FIRMWARE', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
        sb_image = {
            'id': uuids.sb_image,
            'name': 'sb_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
                'os_secure_boot': 'required',
                'hw_firmware_stateless': True,
            }
        }
        self.glance.create(None, sb_image)

        server = self._create_server(image_uuid=uuids.sb_image)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasUEFI(server, secure_boot=True, stateless=True)

    @ddt.unpack
    @ddt.data(
        (None, True),
        (None, False),
        ('bios', True),
        ('bios', False),
    )
    @mock.patch.object(hw, 'LOG')
    def test_create_server_bios_boot_stateless(
            self, firmware_type, stateless, mock_log
    ):
        """hw_firmware_stateless is ignored when an instance uses bios boot

        See https://bugs.launchpad.net/nova/+bug/2158967 for details.
        """
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os>
                  <type machine='q35'>hvm</type>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute(libvirt_version=8006000)

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_STATELESS_FIRMWARE', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
        stateless_image = {
            'id': uuids.stateless_image,
            'name': 'stateless_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_stateless': stateless,
            }
        }
        if firmware_type is not None:
            stateless_image['properties']['hw_firmware_type'] = firmware_type
        self.glance.create(None, stateless_image)

        server = self._create_server(image_uuid=uuids.stateless_image)

        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertIn('image_hw_machine_type', instance.system_metadata)
        self.assertEqual(
            'q35', instance.system_metadata['image_hw_machine_type'])
        if firmware_type:
            self.assertIn('image_hw_firmware_type', instance.system_metadata)
            self.assertEqual(
                'bios', instance.system_metadata['image_hw_firmware_type'])
        else:
            self.assertNotIn('image_hw_firmware_type',
                             instance.system_metadata)
        self.assertIn('image_hw_firmware_stateless', instance.system_metadata)
        self.assertEqual(
            str(stateless),
            instance.system_metadata['image_hw_firmware_stateless'])
        mock_log.warning.assert_has_calls([
            mock.call("The image property 'hw_firmware_stateless' is set for "
                      "non UEFI firmware type. This property is ignored."),
        ])


class UEFIServersFirmwareTest(base.ServersTestBase):

    def test_hard_reboot(self):
        orig_path_exists = os.path.exists

        code_exists = True
        nvram_template_exists = True

        def fake_path_exists(path):
            if path == '/usr/share/OVMF/OVMF_CODE.fd':
                return code_exists
            elif path == '/usr/share/OVMF/OVMF_VARS.fd':
                return nvram_template_exists
            else:
                return orig_path_exists(path)

        self.useFixture(fixtures.MonkeyPatch(
            'os.path.exists', fake_path_exists))

        orig_create = nova.virt.libvirt.guest.Guest.create

        auto_select = True
        secure = 'yes'

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            if not auto_select:
                self.assertXmlEqual(
                    """
                    <os>
                      <type machine='q35'>hvm</type>
                      <loader type='pflash' readonly='yes' secure='%s'>/usr/share/OVMF/OVMF_CODE.fd</loader>
                      <nvram template='/usr/share/OVMF/OVMF_VARS.fd'>/path/to/nvram</nvram>
                      <boot dev='hd'/>
                      <smbios mode='sysinfo'/>
                    </os>
                    """ % secure,  # noqa: E501
                    etree.tostring(tree.find('./os'), encoding='unicode'))
            else:
                self.assertXmlEqual(
                    """
                    <os firmware='efi'>
                      <firmware>
                        <feature name='secure-boot' enabled='%s'/>
                      </firmware>
                      <type machine='q35'>hvm</type>
                      <loader secure='%s'/>
                      <boot dev='hd'/>
                      <smbios mode='sysinfo'/>
                    </os>
                    """ % (secure, secure),
                    etree.tostring(tree.find('./os'), encoding='unicode'))
                # NOTE(tkajinam): Simulate edit by libvirt
                tree.replace(tree.find('./os'), etree.fromstring(
                    textwrap.dedent("""
                    <os>
                      <firmware>
                        <feature name='secure-boot' enabled='%s'/>
                      </firmware>
                      <type machine='q35'>hvm</type>
                      <loader type='pflash' readonly='yes' secure='%s'>/usr/share/OVMF/OVMF_CODE.fd</loader>
                      <nvram template='/usr/share/OVMF/OVMF_VARS.fd'>/path/to/nvram</nvram>
                      <boot dev='hd'/>
                      <smbios mode='sysinfo'/>
                    </os>
                    """ % (secure, secure),  # noqa: E501
                )))
                xml = etree.tostring(tree, encoding='unicode',
                                     pretty_print=True)

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute()

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)

        # create a server with UEFI and secure boot
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
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
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
                'os_secure_boot': 'optional',
            }
        }
        self.glance.create(None, uefi_image)

        # Initial creation
        server = self._create_server(image_uuid=uuids.uefi_image)
        self._stop_server(server)

        # if the domain exists, use the loaders which were already selected
        auto_select = False
        self._start_server(server)
        self._stop_server(server)

        # if code file does not exist, ignore the existing loader
        code_exists = False
        auto_select = True
        self._start_server(server)
        self._stop_server(server)
        code_exists = True

        # if nvram template file does not exist, ignore the existing loader
        nvram_template_exists = False
        auto_select = True
        self._start_server(server)
        self._stop_server(server)
        nvram_template_exists = True

        # the host lost secure boot support and the secure flag has been
        # changed from true to false.
        self.computes[compute].driver._host._supports_secure_boot = False
        secure = 'no'
        # if secure boot flag is changed, ignore the existing loader
        auto_select = True
        self._start_server(server)
        self._stop_server(server)

        # if the domain exists, use the loaders which were already selected
        auto_select = False
        self._start_server(server)
        self._stop_server(server)

        # the host regain secure boot support and the secure flag has been
        # changed from false to true.
        self.computes[compute].driver._host._supports_secure_boot = True
        secure = 'yes'
        # if secure boot flag is changed, ignore the existing loader
        auto_select = True
        self._start_server(server)

    def test_rebuild(self):
        orig_path_exists = os.path.exists

        def fake_path_exists(path):
            if path == '/usr/share/OVMF/OVMF_CODE.fd':
                return True
            elif path == '/usr/share/OVMF/OVMF_VARS.fd':
                return True
            else:
                return orig_path_exists(path)

        self.useFixture(fixtures.MonkeyPatch(
            'os.path.exists', fake_path_exists))

        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='no'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))
            # NOTE(tkajinam): Simulate edit by libvirt
            tree.replace(tree.find('./os'), etree.fromstring(
                textwrap.dedent("""
                <os>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader type='pflash' readonly='yes' secure='no'>/usr/share/OVMF/OVMF_CODE.fd</loader>
                  <nvram template='/usr/share/OVMF/OVMF_VARS.fd'>/path/to/nvram</nvram>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,  # noqa: E501
            )))
            xml = etree.tostring(tree, encoding='unicode', pretty_print=True)

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        compute = self.start_compute()

        # ensure we are reporting the correct trait
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_UEFI_SECURE_BOOT', traits)

        # create a server with UEFI
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
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
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
            }
        }
        self.glance.create(None, uefi_image)

        # Initial creation
        server = self._create_server(image_uuid=uuids.uefi_image)

        # In rebuild, the previous xml is destroyed thus firmware is again
        # auto-selected.
        self._rebuild_server(server, uuids.uefi_image)

    def test_resize(self):
        orig_path_exists = os.path.exists

        def fake_path_exists(path):
            if path == '/usr/share/OVMF/OVMF_CODE.fd':
                return True
            elif path == '/usr/share/OVMF/OVMF_VARS.fd':
                return True
            else:
                return orig_path_exists(path)

        self.useFixture(fixtures.MonkeyPatch(
            'os.path.exists', fake_path_exists))

        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            xml = re.sub('type arch.*machine',
                'type machine', xml)
            tree = etree.fromstring(xml)
            self.assertXmlEqual(
                """
                <os firmware='efi'>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader secure='no'/>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,
                etree.tostring(tree.find('./os'), encoding='unicode'))
            # NOTE(tkajinam): Simulate edit by libvirt
            tree.replace(tree.find('./os'), etree.fromstring(
                textwrap.dedent("""
                <os>
                  <firmware>
                    <feature name='secure-boot' enabled='no'/>
                  </firmware>
                  <type machine='q35'>hvm</type>
                  <loader type='pflash' readonly='yes' secure='no'>/usr/share/OVMF/OVMF_CODE.fd</loader>
                  <nvram template='/usr/share/OVMF/OVMF_VARS.fd'>/path/to/nvram</nvram>
                  <boot dev='hd'/>
                  <smbios mode='sysinfo'/>
                </os>
                """,  # noqa: E501
            )))
            xml = etree.tostring(tree, encoding='unicode', pretty_print=True)

            return orig_create(xml, host)

        self.stub_out('nova.virt.libvirt.guest.Guest.create', fake_create)

        self.start_compute('host1')
        self.start_compute('host2')

        # create a server with UEFI
        timestamp = datetime.datetime(
            2021, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
        )
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
            'size': 74185822,
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'hw_machine_type': 'q35',
                'hw_firmware_type': 'uefi',
            }
        }
        self.glance.create(None, uefi_image)

        # Initial creation
        server = self._create_server(image_uuid=uuids.uefi_image)

        # In cold-migration, the previous xml is destroyed so firmware should
        # be auto-selected.
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            self._resize_server(server, self.api.get_flavors()[1]['id'])
