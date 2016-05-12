# Copyright (c) 2016 Red Hat, Inc
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

from lxml import etree
import mock

import six

from nova import objects
from nova import test
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import migration


class UtilityMigrationTestCase(test.NoDBTestCase):

    def test_graphics_listen_addrs(self):
        data = objects.LibvirtLiveMigrateData(
            graphics_listen_addr_vnc='127.0.0.1',
            graphics_listen_addr_spice='127.0.0.2')
        addrs = migration.graphics_listen_addrs(data)
        self.assertEqual({
            'vnc': '127.0.0.1',
            'spice': '127.0.0.2'}, addrs)

    def test_graphics_listen_addrs_empty(self):
        data = objects.LibvirtLiveMigrateData()
        addrs = migration.graphics_listen_addrs(data)
        self.assertIsNone(None, addrs)

    def test_graphics_listen_addrs_spice(self):
        data = objects.LibvirtLiveMigrateData(
            graphics_listen_addr_spice='127.0.0.2')
        addrs = migration.graphics_listen_addrs(data)
        self.assertEqual({
            'vnc': None,
            'spice': '127.0.0.2'}, addrs)

    def test_graphics_listen_addrs_vnc(self):
        data = objects.LibvirtLiveMigrateData(
            graphics_listen_addr_vnc='127.0.0.1')
        addrs = migration.graphics_listen_addrs(data)
        self.assertEqual({
            'vnc': '127.0.0.1',
            'spice': None}, addrs)

    def test_serial_listen_addr(self):
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.1')
        addr = migration.serial_listen_addr(data)
        self.assertEqual('127.0.0.1', addr)

    def test_serial_listen_addr_emtpy(self):
        data = objects.LibvirtLiveMigrateData()
        addr = migration.serial_listen_addr(data)
        self.assertIsNone(addr)

    @mock.patch('lxml.etree.tostring')
    @mock.patch.object(migration, '_update_graphics_xml')
    @mock.patch.object(migration, '_update_serial_xml')
    @mock.patch.object(migration, '_update_volume_xml')
    def test_get_updated_guest_xml(
            self, mock_volume, mock_serial, mock_graphics,
            mock_tostring):
        data = objects.LibvirtLiveMigrateData()
        mock_guest = mock.Mock(spec=libvirt_guest.Guest)
        get_volume_config = mock.MagicMock()
        mock_guest.get_xml_desc.return_value = '<domain></domain>'

        migration.get_updated_guest_xml(mock_guest, data, get_volume_config)
        mock_graphics.assert_called_once_with(mock.ANY, data)
        mock_serial.assert_called_once_with(mock.ANY, data)
        mock_volume.assert_called_once_with(mock.ANY, data, get_volume_config)
        self.assertEqual(1, mock_tostring.called)

    def test_update_serial_xml_serial(self):
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.100')
        xml = """<domain>
  <devices>
    <serial type="tcp">
      <source host="127.0.0.1"/>
    </serial>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_serial_xml(doc, data))
        self.assertIn('127.0.0.100', six.text_type(res))

    def test_update_serial_xml_console(self):
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.100')
        xml = """<domain>
  <devices>
    <console type="tcp">
      <source host="127.0.0.1"/>
    </console>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_serial_xml(doc, data))
        self.assertIn('127.0.0.100', six.text_type(res))

    def test_update_graphics(self):
        data = objects.LibvirtLiveMigrateData(
            graphics_listen_addr_vnc='127.0.0.100',
            graphics_listen_addr_spice='127.0.0.200')
        xml = """<domain>
  <devices>
    <graphics type="vnc">
      <listen type="address" address="127.0.0.1"/>
    </graphics>
    <graphics type="spice">
      <listen type="address" address="127.0.0.2"/>
    </graphics>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_graphics_xml(doc, data))
        self.assertIn('127.0.0.100', six.text_type(res))
        self.assertIn('127.0.0.200', six.text_type(res))

    def test_update_volume_xml(self):
        connection_info = {
            'driver_volume_type': 'iscsi',
            'serial': '58a84f6d-3f0c-4e19-a0af-eb657b790657',
            'data': {
                'access_mode': 'rw',
                'target_discovered': False,
                'target_iqn': 'ip-1.2.3.4:3260-iqn.cde.67890.opst-lun-Z',
                'volume_id': '58a84f6d-3f0c-4e19-a0af-eb657b790657',
                'device_path':
                '/dev/disk/by-path/ip-1.2.3.4:3260-iqn.cde.67890.opst-lun-Z'}}
        bdm = objects.LibvirtLiveMigrateBDMInfo(
            serial='58a84f6d-3f0c-4e19-a0af-eb657b790657',
            bus='virtio', type='disk', dev='vdb',
            connection_info=connection_info)
        data = objects.LibvirtLiveMigrateData(
            target_connect_addr='127.0.0.1',
            bdms=[bdm],
            block_migration=False)
        xml = """<domain>
 <devices>
   <disk type='block' device='disk'>
     <driver name='qemu' type='raw' cache='none'/>
     <source dev='/dev/disk/by-path/ip-1.2.3.4:3260-iqn.abc.12345.opst-lun-X'/>
     <target bus='virtio' dev='vdb'/>
     <serial>58a84f6d-3f0c-4e19-a0af-eb657b790657</serial>
     <address type='pci' domain='0x0' bus='0x0' slot='0x04' function='0x0'/>
   </disk>
 </devices>
</domain>"""
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_device = bdm.type
        conf.driver_name = "qemu"
        conf.driver_format = "raw"
        conf.driver_cache = "none"
        conf.target_dev = bdm.dev
        conf.target_bus = bdm.bus
        conf.serial = bdm.connection_info.get('serial')
        conf.source_type = "block"
        conf.source_path = bdm.connection_info['data'].get('device_path')

        get_volume_config = mock.MagicMock(return_value=conf)
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_volume_xml(
            doc, data, get_volume_config))
        self.assertIn('ip-1.2.3.4:3260-iqn.cde.67890.opst-lun-Z',
                      six.text_type(res))
