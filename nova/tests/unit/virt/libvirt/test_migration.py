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

from collections import deque
import copy
import textwrap

from lxml import etree
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units
import six

from nova.compute import power_state
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host
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
        self.assertIsNone(addrs)

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

    @mock.patch('lxml.etree.tostring')
    @mock.patch.object(migration, '_update_memory_backing_xml')
    @mock.patch.object(migration, '_update_perf_events_xml')
    @mock.patch.object(migration, '_update_graphics_xml')
    @mock.patch.object(migration, '_update_serial_xml')
    @mock.patch.object(migration, '_update_volume_xml')
    def test_get_updated_guest_xml(
            self, mock_volume, mock_serial, mock_graphics,
            mock_perf_events_xml, mock_memory_backing, mock_tostring):
        data = objects.LibvirtLiveMigrateData()
        mock_guest = mock.Mock(spec=libvirt_guest.Guest)
        get_volume_config = mock.MagicMock()
        mock_guest.get_xml_desc.return_value = '<domain></domain>'

        migration.get_updated_guest_xml(mock_guest, data, get_volume_config)
        mock_graphics.assert_called_once_with(mock.ANY, data)
        mock_serial.assert_called_once_with(mock.ANY, data)
        mock_volume.assert_called_once_with(mock.ANY, data, get_volume_config)
        mock_perf_events_xml.assert_called_once_with(mock.ANY, data)
        mock_memory_backing.assert_called_once_with(mock.ANY, data)
        self.assertEqual(1, mock_tostring.called)

    def test_update_device_resources_xml_vpmem(self):
        # original xml for vpmems, /dev/dax0.1 and /dev/dax0.2 here
        # are vpmem device path on source host
        old_xml = textwrap.dedent("""
            <domain>
                <devices>
                    <memory model='nvdimm'>
                        <source>
                            <path>/dev/dax0.1</path>
                            <alignsize>2048</alignsize>
                            <pmem>on</pmem>
                        </source>
                        <target>
                            <size>4192256</size>
                            <label>
                                <size>2048</size>
                            </label>
                            <node>0</node>
                        </target>
                    </memory>
                    <memory model='nvdimm'>
                        <source>
                            <path>/dev/dax0.2</path>
                            <alignsize>2048</alignsize>
                            <pmem>on</pmem>
                        </source>
                        <target>
                            <size>4192256</size>
                            <label>
                                <size>2048</size>
                            </label>
                            <node>0</node>
                        </target>
                    </memory>
                </devices>
            </domain>""")
        doc = etree.fromstring(old_xml)
        vpmem_resource_0 = objects.Resource(
            provider_uuid=uuids.rp_uuid,
            resource_class="CUSTOM_PMEM_NAMESPACE_4GB",
            identifier='ns_0',
            metadata= objects.LibvirtVPMEMDevice(
                label='4GB', name='ns_0', devpath='/dev/dax1.0',
                size=4292870144, align=2097152))
        vpmem_resource_1 = objects.Resource(
            provider_uuid=uuids.rp_uuid,
            resource_class="CUSTOM_PMEM_NAMESPACE_4GB",
            identifier='ns_0',
            metadata= objects.LibvirtVPMEMDevice(
                label='4GB', name='ns_1', devpath='/dev/dax2.0',
                size=4292870144, align=2097152))
        # new_resources contains vpmems claimed on destination,
        # /dev/dax1.0 and /dev/dax2.0 are where vpmem data is migrated to
        new_resources = objects.ResourceList(
                objects=[vpmem_resource_0, vpmem_resource_1])
        res = etree.tostring(migration._update_device_resources_xml(
                                copy.deepcopy(doc), new_resources),
                             encoding='unicode')
        # we expect vpmem info will be updated in xml after invoking
        # _update_device_resources_xml
        new_xml = old_xml.replace("/dev/dax0.1", "/dev/dax1.0")
        new_xml = new_xml.replace("/dev/dax0.2", "/dev/dax2.0")
        self.assertXmlEqual(res, new_xml)

    def test_update_numa_xml(self):
        doc = etree.fromstring("""
            <domain>
              <cputune>
                <vcpupin vcpu="0" cpuset="0,1,2,^2"/>
                <vcpupin vcpu="1" cpuset="2-4,^4"/>
                <emulatorpin cpuset="8-10,^8"/>
                <vcpusched vcpus="10" priority="13" scheduler="fifo"/>
                <vcpusched vcpus="11" priority="13" scheduler="fifo"/>
              </cputune>
              <numatune>
                <memory nodeset="4,5,6,7"/>
                <memnode cellid="2" nodeset="4-6,^6"/>
                <memnode cellid="3" nodeset="6-8,^8"/>
              </numatune>
            </domain>""")
        data = objects.LibvirtLiveMigrateData(
            dst_numa_info=objects.LibvirtLiveMigrateNUMAInfo(
                cpu_pins={'0': set([10, 11]), '1': set([12, 13])},
                cell_pins={'2': set([14, 15]), '3': set([16, 17])},
                emulator_pins=set([18, 19]),
                sched_vcpus=set([20, 21]),
                sched_priority=22))

        result = etree.tostring(
            migration._update_numa_xml(copy.deepcopy(doc), data),
            encoding='unicode')

        expected = textwrap.dedent("""
            <domain>
              <cputune>
                <vcpupin vcpu="0" cpuset="10-11"/>
                <vcpupin vcpu="1" cpuset="12-13"/>
                <emulatorpin cpuset="18-19"/>
                <vcpusched vcpus="20-21" priority="22" scheduler="fifo"/>
              </cputune>
              <numatune>
                <memory nodeset="14-17"/>
                <memnode cellid="2" nodeset="14-15"/>
                <memnode cellid="3" nodeset="16-17"/>
              </numatune>
            </domain>""")

        self.assertXmlEqual(expected, result)

    def test_update_numa_xml_no_updates(self):
        xml = textwrap.dedent("""
            <domain>
                <cputune>
                    <vcpupin vcpu="0" cpuset="0,1,2,^2"/>
                    <vcpupin vcpu="1" cpuset="2-4,^4"/>
                    <emulatorpin cpuset="8-10,^8"/>
                </cputune>
                <numatune>
                    <memnode cellid="2" nodeset="4-6,^6"/>
                    <memnode cellid="3" nodeset="6-8,^8"/>
                </numatune>
                <memoryBacking>
                    <hugepages>
                        <page nodeset="8,9,10,^10"/>
                    </hugepages>
                </memoryBacking>
            </domain>""")
        doc = etree.fromstring(xml)
        data = objects.LibvirtLiveMigrateData(
            dst_numa_info=objects.LibvirtLiveMigrateNUMAInfo())
        res = etree.tostring(migration._update_numa_xml(copy.deepcopy(doc),
                                                        data),
                             encoding='unicode')
        self.assertXmlEqual(res, etree.tostring(doc, encoding='unicode'))

    def test_update_serial_xml_serial(self):
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.100',
            serial_listen_ports=[2001])
        xml = """<domain>
  <devices>
    <serial type="tcp">
      <source host="127.0.0.1" service="2000"/>
      <target type="serial" port="0"/>
    </serial>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_serial_xml(doc, data),
                             encoding='unicode')
        new_xml = xml.replace("127.0.0.1", "127.0.0.100").replace(
            "2000", "2001")
        self.assertXmlEqual(res, new_xml)

    def test_update_serial_xml_console(self):
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.100',
            serial_listen_ports=[299, 300])
        xml = """<domain>
  <devices>
    <console type="tcp">
      <source host="127.0.0.1" service="2001"/>
      <target type="serial" port="0"/>
    </console>
    <console type="tcp">
      <source host="127.0.0.1" service="2002"/>
      <target type="serial" port="1"/>
    </console>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_serial_xml(doc, data),
                             encoding='unicode')
        new_xml = xml.replace("127.0.0.1", "127.0.0.100").replace(
            "2001", "299").replace("2002", "300")

        self.assertXmlEqual(res, new_xml)

    def test_update_serial_xml_without_ports(self):
        # This test is for backwards compatibility when we don't
        # get the serial ports from the target node.
        data = objects.LibvirtLiveMigrateData(
            serial_listen_addr='127.0.0.100',
            serial_listen_ports=[])
        xml = """<domain>
  <devices>
    <console type="tcp">
      <source host="127.0.0.1" service="2001"/>
      <target type="serial" port="0"/>
    </console>
    <console type="tcp">
      <source host="127.0.0.1" service="2002"/>
      <target type="serial" port="1"/>
    </console>
  </devices>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_serial_xml(doc, data),
                             encoding='unicode')
        new_xml = xml.replace("127.0.0.1", "127.0.0.100")
        self.assertXmlEqual(res, new_xml)

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
        res = etree.tostring(migration._update_graphics_xml(doc, data),
                             encoding='unicode')
        new_xml = xml.replace("127.0.0.1", "127.0.0.100")
        new_xml = new_xml.replace("127.0.0.2", "127.0.0.200")
        self.assertXmlEqual(res, new_xml)

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
            doc, data, get_volume_config), encoding='unicode')
        new_xml = xml.replace('ip-1.2.3.4:3260-iqn.abc.12345.opst-lun-X',
                              'ip-1.2.3.4:3260-iqn.cde.67890.opst-lun-Z')
        self.assertXmlEqual(res, new_xml)

    def test_update_volume_xml_keeps_address(self):
        # Now test to make sure address isn't altered for virtio-scsi and rbd
        connection_info = {
            'driver_volume_type': 'rbd',
            'serial': 'd299a078-f0db-4993-bf03-f10fe44fd192',
            'data': {
                'access_mode': 'rw',
                'secret_type': 'ceph',
                'name': 'cinder-volumes/volume-d299a078',
                'encrypted': False,
                'discard': True,
                'cluster_name': 'ceph',
                'secret_uuid': '1a790a26-dd49-4825-8d16-3dd627cf05a9',
                'qos_specs': None,
                'auth_enabled': True,
                'volume_id': 'd299a078-f0db-4993-bf03-f10fe44fd192',
                'hosts': ['172.16.128.101', '172.16.128.121'],
                'auth_username': 'cinder',
                'ports': ['6789', '6789', '6789']}}
        bdm = objects.LibvirtLiveMigrateBDMInfo(
            serial='d299a078-f0db-4993-bf03-f10fe44fd192',
            bus='scsi', type='disk', dev='sdc',
            connection_info=connection_info)
        data = objects.LibvirtLiveMigrateData(
            target_connect_addr=None,
            bdms=[bdm],
            block_migration=False)
        xml = """<domain>
 <devices>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw' cache='writeback' discard='unmap'/>
      <auth username='cinder'>
        <secret type='ceph' uuid='1a790a26-dd49-4825-8d16-3dd627cf05a9'/>
      </auth>
      <source protocol='rbd' name='cinder-volumes/volume-d299a078'>
        <host name='172.16.128.101' port='6789'/>
        <host name='172.16.128.121' port='6789'/>
      </source>
      <backingStore/>
      <target dev='sdb' bus='scsi'/>
      <serial>d299a078-f0db-4993-bf03-f10fe44fd192</serial>
      <alias name='scsi0-0-0-1'/>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
 </devices>
</domain>"""
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_device = bdm.type
        conf.driver_name = "qemu"
        conf.driver_format = "raw"
        conf.driver_cache = "writeback"
        conf.target_dev = bdm.dev
        conf.target_bus = bdm.bus
        conf.serial = bdm.connection_info.get('serial')
        conf.source_type = "network"
        conf.driver_discard = 'unmap'
        conf.device_addr = vconfig.LibvirtConfigGuestDeviceAddressDrive()
        conf.device_addr.controller = 0

        get_volume_config = mock.MagicMock(return_value=conf)
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_volume_xml(
            doc, data, get_volume_config), encoding='unicode')
        new_xml = xml.replace('sdb',
                              'sdc')
        self.assertXmlEqual(res, new_xml)

    def test_update_volume_xml_add_encryption(self):
        connection_info = {
            'driver_volume_type': 'rbd',
            'serial': 'd299a078-f0db-4993-bf03-f10fe44fd192',
            'data': {
                'access_mode': 'rw',
                'secret_type': 'ceph',
                'name': 'cinder-volumes/volume-d299a078',
                'encrypted': False,
                'discard': True,
                'cluster_name': 'ceph',
                'secret_uuid': '1a790a26-dd49-4825-8d16-3dd627cf05a9',
                'qos_specs': None,
                'auth_enabled': True,
                'volume_id': 'd299a078-f0db-4993-bf03-f10fe44fd192',
                'hosts': ['172.16.128.101', '172.16.128.121'],
                'auth_username': 'cinder',
                'ports': ['6789', '6789', '6789']}}
        bdm = objects.LibvirtLiveMigrateBDMInfo(
            serial='d299a078-f0db-4993-bf03-f10fe44fd192',
            bus='scsi', type='disk', dev='sdb',
            connection_info=connection_info,
            encryption_secret_uuid=uuids.encryption_secret_uuid)
        data = objects.LibvirtLiveMigrateData(
            target_connect_addr=None,
            bdms=[bdm],
            block_migration=False)
        xml = """<domain>
 <devices>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw' cache='writeback' discard='unmap'/>
      <auth username='cinder'>
        <secret type='ceph' uuid='1a790a26-dd49-4825-8d16-3dd627cf05a9'/>
      </auth>
      <source protocol='rbd' name='cinder-volumes/volume-d299a078'>
        <host name='172.16.128.101' port='6789'/>
        <host name='172.16.128.121' port='6789'/>
      </source>
      <backingStore/>
      <target dev='sdb' bus='scsi'/>
      <serial>d299a078-f0db-4993-bf03-f10fe44fd192</serial>
      <alias name='scsi0-0-0-1'/>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
 </devices>
</domain>"""
        new_xml = """<domain>
 <devices>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw' cache='writeback' discard='unmap'/>
      <auth username='cinder'>
        <secret type='ceph' uuid='1a790a26-dd49-4825-8d16-3dd627cf05a9'/>
      </auth>
      <source protocol='rbd' name='cinder-volumes/volume-d299a078'>
        <host name='172.16.128.101' port='6789'/>
        <host name='172.16.128.121' port='6789'/>
      </source>
      <backingStore/>
      <target dev='sdb' bus='scsi'/>
      <serial>d299a078-f0db-4993-bf03-f10fe44fd192</serial>
      <alias name='scsi0-0-0-1'/>
      <encryption format='luks'>
        <secret type='passphrase' uuid='%(encryption_secret_uuid)s'/>
      </encryption>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
 </devices>
</domain>""" % {'encryption_secret_uuid': uuids.encryption_secret_uuid}
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_device = bdm.type
        conf.driver_name = "qemu"
        conf.driver_format = "raw"
        conf.driver_cache = "writeback"
        conf.target_dev = bdm.dev
        conf.target_bus = bdm.bus
        conf.serial = bdm.connection_info.get('serial')
        conf.source_type = "network"
        conf.driver_discard = 'unmap'
        conf.device_addr = vconfig.LibvirtConfigGuestDeviceAddressDrive()
        conf.device_addr.controller = 0

        get_volume_config = mock.MagicMock(return_value=conf)
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_volume_xml(
            doc, data, get_volume_config), encoding='unicode')
        self.assertXmlEqual(res, new_xml)

    def test_update_volume_xml_update_encryption(self):
        connection_info = {
            'driver_volume_type': 'rbd',
            'serial': 'd299a078-f0db-4993-bf03-f10fe44fd192',
            'data': {
                'access_mode': 'rw',
                'secret_type': 'ceph',
                'name': 'cinder-volumes/volume-d299a078',
                'encrypted': False,
                'discard': True,
                'cluster_name': 'ceph',
                'secret_uuid': '1a790a26-dd49-4825-8d16-3dd627cf05a9',
                'qos_specs': None,
                'auth_enabled': True,
                'volume_id': 'd299a078-f0db-4993-bf03-f10fe44fd192',
                'hosts': ['172.16.128.101', '172.16.128.121'],
                'auth_username': 'cinder',
                'ports': ['6789', '6789', '6789']}}
        bdm = objects.LibvirtLiveMigrateBDMInfo(
            serial='d299a078-f0db-4993-bf03-f10fe44fd192',
            bus='scsi', type='disk', dev='sdb',
            connection_info=connection_info,
            encryption_secret_uuid=uuids.encryption_secret_uuid_new)
        data = objects.LibvirtLiveMigrateData(
            target_connect_addr=None,
            bdms=[bdm],
            block_migration=False)
        xml = """<domain>
 <devices>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw' cache='writeback' discard='unmap'/>
      <auth username='cinder'>
        <secret type='ceph' uuid='1a790a26-dd49-4825-8d16-3dd627cf05a9'/>
      </auth>
      <source protocol='rbd' name='cinder-volumes/volume-d299a078'>
        <host name='172.16.128.101' port='6789'/>
        <host name='172.16.128.121' port='6789'/>
      </source>
      <backingStore/>
      <target dev='sdb' bus='scsi'/>
      <serial>d299a078-f0db-4993-bf03-f10fe44fd192</serial>
      <alias name='scsi0-0-0-1'/>
      <encryption format='luks'>
        <secret type='passphrase' uuid='%(encryption_secret_uuid)s'/>
      </encryption>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
 </devices>
</domain>""" % {'encryption_secret_uuid': uuids.encryption_secret_uuid_old}
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.source_device = bdm.type
        conf.driver_name = "qemu"
        conf.driver_format = "raw"
        conf.driver_cache = "writeback"
        conf.target_dev = bdm.dev
        conf.target_bus = bdm.bus
        conf.serial = bdm.connection_info.get('serial')
        conf.source_type = "network"
        conf.driver_discard = 'unmap'
        conf.device_addr = vconfig.LibvirtConfigGuestDeviceAddressDrive()
        conf.device_addr.controller = 0

        get_volume_config = mock.MagicMock(return_value=conf)
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_volume_xml(
            doc, data, get_volume_config), encoding='unicode')
        new_xml = xml.replace(uuids.encryption_secret_uuid_old,
                              uuids.encryption_secret_uuid_new)
        self.assertXmlEqual(res, new_xml)

    def test_update_perf_events_xml(self):
        data = objects.LibvirtLiveMigrateData(
            supported_perf_events=['cmt'])
        xml = """<domain>
  <perf>
    <event enabled="yes" name="cmt"/>
    <event enabled="yes" name="mbml"/>
  </perf>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_perf_events_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <perf>
    <event enabled="yes" name="cmt"/></perf>
</domain>""")

    def test_update_perf_events_xml_add_new_events(self):
        data = objects.LibvirtLiveMigrateData(
            supported_perf_events=['cmt'])
        xml = """<domain>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_perf_events_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
<perf><event enabled="yes" name="cmt"/></perf></domain>""")

    def test_update_perf_events_xml_add_new_events1(self):
        data = objects.LibvirtLiveMigrateData(
            supported_perf_events=['cmt', 'mbml'])
        xml = """<domain>
  <perf>
    <event enabled="yes" name="cmt"/>
  </perf>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_perf_events_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <perf>
    <event enabled="yes" name="cmt"/><event enabled="yes" name="mbml"/></perf>
</domain>""")

    def test_update_perf_events_xml_remove_all_events(self):
        data = objects.LibvirtLiveMigrateData(
            supported_perf_events=[])
        xml = """<domain>
  <perf>
    <event enabled="yes" name="cmt"/>
  </perf>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_perf_events_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <perf>
    </perf>
</domain>""")

    def test_update_memory_backing_xml_remove(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=False)
        xml = """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking/>
</domain>""")

    def test_update_memory_backing_xml_add(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=True)
        xml = """<domain/>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>""")

    def test_update_memory_backing_xml_keep(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=True)

        xml = """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>""")

    def test_update_memory_backing_discard_add(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=True, file_backed_memory_discard=True)

        xml = """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
    <discard />
  </memoryBacking>
</domain>""")

    def test_update_memory_backing_discard_remove(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=True,
            file_backed_memory_discard=False)

        xml = """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
    <discard />
  </memoryBacking>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
  </memoryBacking>
</domain>""")

    def test_update_memory_backing_discard_keep(self):
        data = objects.LibvirtLiveMigrateData(
            dst_wants_file_backed_memory=True, file_backed_memory_discard=True)

        xml = """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
    <discard />
  </memoryBacking>
</domain>"""
        doc = etree.fromstring(xml)
        res = etree.tostring(migration._update_memory_backing_xml(doc, data),
                             encoding='unicode')

        self.assertXmlEqual(res, """<domain>
  <memoryBacking>
    <source type="file"/>
    <access mode="shared"/>
    <allocation mode="immediate"/>
    <discard />
  </memoryBacking>
</domain>""")

    def _test_update_vif_xml(self, conf, original_xml, expected_xml):
        """Simulates updating the guest xml for live migrating from a host
        using OVS to a host using vhostuser as the networking backend.
        """
        vif_ovs = network_model.VIF(id=uuids.vif,
                                    address='DE:AD:BE:EF:CA:FE',
                                    details={'port_filter': False},
                                    devname='tap-xxx-yyy-zzz',
                                    ovs_interfaceid=uuids.ovs)
        source_vif = vif_ovs
        migrate_vifs = [
            objects.VIFMigrateData(
                port_id=uuids.port_id,
                vnic_type=network_model.VNIC_TYPE_NORMAL,
                vif_type=network_model.VIF_TYPE_VHOSTUSER,
                vif_details={
                    'vhostuser_socket': '/vhost-user/test.sock'
                },
                profile={},
                host='dest.host',
                source_vif=source_vif)
        ]
        data = objects.LibvirtLiveMigrateData(vifs=migrate_vifs)

        get_vif_config = mock.MagicMock(return_value=conf)
        doc = etree.fromstring(original_xml)
        updated_xml = etree.tostring(
            migration._update_vif_xml(doc, data, get_vif_config),
            encoding='unicode')
        self.assertXmlEqual(updated_xml, expected_xml)

    def test_update_vif_xml_to_vhostuser(self):
        conf = vconfig.LibvirtConfigGuestInterface()
        conf.net_type = "vhostuser"
        conf.vhostuser_type = "unix"
        conf.vhostuser_mode = "server"
        conf.mac_addr = "DE:AD:BE:EF:CA:FE"
        conf.vhostuser_path = "/vhost-user/test.sock"
        conf.model = "virtio"

        original_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="bridge">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source bridge="qbra188171c-ea"/>
        <target dev="tapa188171c-ea"/>
        <virtualport type="openvswitch">
            <parameters interfaceid="%s"/>
        </virtualport>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>""" % uuids.ovs
        # Note that <target> and <virtualport> are dropped from the ovs source
        # interface xml since they aren't applicable to the vhostuser
        # destination interface xml. The type attribute value changes and the
        # hardware address element is retained.
        expected_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="vhostuser">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source mode="server" path="/vhost-user/test.sock" type="unix"/>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>"""
        self._test_update_vif_xml(conf, original_xml, expected_xml)

    def test_update_vif_xml_to_bridge_without_mtu(self):
        """This test validates _update_vif_xml to make sure it does not add
        MTU to the interface if it does not exist in the source XML.
        """
        conf = vconfig.LibvirtConfigGuestInterface()
        conf.net_type = "bridge"
        conf.source_dev = "qbra188171c-ea"
        conf.target_dev = "tapa188171c-ea"
        conf.mac_addr = "DE:AD:BE:EF:CA:FE"
        conf.vhostuser_path = "/vhost-user/test.sock"
        conf.model = "virtio"
        conf.mtu = 9000

        original_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="bridge">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source bridge="qbra188171c-ea"/>
        <target dev="tapa188171c-ea"/>
        <virtualport type="openvswitch">
            <parameters interfaceid="%s"/>
        </virtualport>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>""" % uuids.ovs
        expected_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="bridge">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source bridge="qbra188171c-ea"/>
        <target dev="tapa188171c-ea"/>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>"""
        self._test_update_vif_xml(conf, original_xml, expected_xml)

    def test_update_vif_xml_to_bridge_with_mtu(self):
        """This test validates _update_vif_xml to make sure it maintains the
        interface MTU if it exists in the source XML
        """
        conf = vconfig.LibvirtConfigGuestInterface()
        conf.net_type = "bridge"
        conf.source_dev = "qbra188171c-ea"
        conf.target_dev = "tapa188171c-ea"
        conf.mac_addr = "DE:AD:BE:EF:CA:FE"
        conf.vhostuser_path = "/vhost-user/test.sock"
        conf.model = "virtio"
        conf.mtu = 9000

        original_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="bridge">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source bridge="qbra188171c-ea"/>
        <target dev="tapa188171c-ea"/>
        <mtu size="9000"/>
        <virtualport type="openvswitch">
            <parameters interfaceid="%s"/>
        </virtualport>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>""" % uuids.ovs
        expected_xml = """<domain>
 <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
 <devices>
    <interface type="bridge">
        <mac address="DE:AD:BE:EF:CA:FE"/>
        <model type="virtio"/>
        <source bridge="qbra188171c-ea"/>
        <mtu size="9000"/>
        <target dev="tapa188171c-ea"/>
        <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                 function='0x0'/>
    </interface>
 </devices>
</domain>"""
        self._test_update_vif_xml(conf, original_xml, expected_xml)

    def test_update_vif_xml_no_mac_address_in_xml(self):
        """Tests that the <mac address> is not found in the <interface> XML
        which results in an error.
        """
        data = objects.LibvirtLiveMigrateData(vifs=[
            objects.VIFMigrateData(source_vif=network_model.VIF(
                address="DE:AD:BE:EF:CA:FE"))])
        original_xml = """<domain>
         <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
         <devices>
            <interface type='direct'>
                <source dev='eth0' mode='private'/>
                <virtualport type='802.1Qbh'>
                  <parameters profileid='finance'/>
                </virtualport>
            </interface>
         </devices>
        </domain>"""
        get_vif_config = mock.MagicMock(new_callable=mock.NonCallableMock)
        doc = etree.fromstring(original_xml)
        ex = self.assertRaises(exception.NovaException,
                               migration._update_vif_xml,
                               doc, data, get_vif_config)
        self.assertIn('Unable to find MAC address in interface XML',
                      six.text_type(ex))

    def test_update_vif_xml_no_matching_vif(self):
        """Tests that the vif in the migrate data is not found in the existing
        guest interfaces.
        """
        data = objects.LibvirtLiveMigrateData(vifs=[
            objects.VIFMigrateData(source_vif=network_model.VIF(
                address="DE:AD:BE:EF:CA:FE"))])
        original_xml = """<domain>
         <uuid>3de6550a-8596-4937-8046-9d862036bca5</uuid>
         <devices>
            <interface type="bridge">
                <mac address="CA:FE:DE:AD:BE:EF"/>
                <model type="virtio"/>
                <source bridge="qbra188171c-ea"/>
                <target dev="tapa188171c-ea"/>
            </interface>
         </devices>
        </domain>"""
        get_vif_config = mock.MagicMock(new_callable=mock.NonCallableMock)
        doc = etree.fromstring(original_xml)
        ex = self.assertRaises(KeyError, migration._update_vif_xml,
                               doc, data, get_vif_config)
        self.assertIn("CA:FE:DE:AD:BE:EF", six.text_type(ex))


class MigrationMonitorTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MigrationMonitorTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())

        flavor = objects.Flavor(memory_mb=2048,
                                swap=0,
                                vcpu_weight=None,
                                root_gb=1,
                                id=2,
                                name=u'm1.small',
                                ephemeral_gb=0,
                                rxtx_factor=1.0,
                                flavorid=u'1',
                                vcpus=1,
                                extra_specs={})

        instance = {
            'id': 1,
            'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
            'memory_kb': '1024000',
            'basepath': '/some/path',
            'bridge_name': 'br100',
            'display_name': "Acme webserver",
            'vcpus': 2,
            'project_id': 'fake',
            'bridge': 'br101',
            'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
            'root_gb': 10,
            'ephemeral_gb': 20,
            'instance_type_id': '5',  # m1.small
            'extra_specs': {},
            'system_metadata': {
                'image_disk_format': 'raw',
            },
            'flavor': flavor,
            'new_flavor': None,
            'old_flavor': None,
            'pci_devices': objects.PciDeviceList(),
            'numa_topology': None,
            'config_drive': None,
            'vm_mode': None,
            'kernel_id': None,
            'ramdisk_id': None,
            'os_type': 'linux',
            'user_id': '838a72b0-0d54-4827-8fd6-fb1227633ceb',
            'ephemeral_key_uuid': None,
            'vcpu_model': None,
            'host': 'fake-host',
            'task_state': None,
        }
        self.instance = objects.Instance(**instance)
        self.conn = fakelibvirt.Connection("qemu:///system")
        self.dom = fakelibvirt.Domain(self.conn, "<domain/>", True)
        self.host = host.Host("qemu:///system")
        self.guest = libvirt_guest.Guest(self.dom)

    @mock.patch.object(libvirt_guest.Guest, "is_active", return_value=True)
    def test_live_migration_find_type_active(self, mock_active):
        self.assertEqual(migration.find_job_type(self.guest, self.instance),
                         fakelibvirt.VIR_DOMAIN_JOB_FAILED)

    @mock.patch.object(libvirt_guest.Guest, "is_active", return_value=False)
    def test_live_migration_find_type_inactive(self, mock_active):
        self.assertEqual(migration.find_job_type(self.guest, self.instance),
                         fakelibvirt.VIR_DOMAIN_JOB_COMPLETED)

    @mock.patch.object(libvirt_guest.Guest, "is_active")
    def test_live_migration_find_type_no_domain(self, mock_active):
        mock_active.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "No domain with ID",
            error_code=fakelibvirt.VIR_ERR_NO_DOMAIN)

        self.assertEqual(migration.find_job_type(self.guest, self.instance),
                         fakelibvirt.VIR_DOMAIN_JOB_COMPLETED)

    @mock.patch.object(libvirt_guest.Guest, "is_active")
    def test_live_migration_find_type_bad_err(self, mock_active):
        mock_active.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "Something weird happened",
            error_code=fakelibvirt.VIR_ERR_INTERNAL_ERROR)

        self.assertEqual(migration.find_job_type(self.guest, self.instance),
                         fakelibvirt.VIR_DOMAIN_JOB_FAILED)

    @mock.patch('nova.virt.libvirt.migration.LOG',
                new_callable=mock.NonCallableMock)  # asserts not called
    @mock.patch('nova.virt.libvirt.guest.Guest.is_active', return_value=True)
    def test_live_migration_find_type_no_logging(self, mock_active, _mock_log):
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_FAILED,
                         migration.find_job_type(self.guest, self.instance,
                                                 logging_ok=False))

    def test_live_migration_abort_too_long(self):
        # Elapsed time is over completion timeout
        self.assertTrue(migration.should_trigger_timeout_action(
            self.instance, 4500, 2000, "running"))

    def test_live_migration_abort_no_comp_timeout(self):
        # Completion timeout is disabled
        self.assertFalse(migration.should_trigger_timeout_action(
            self.instance, 4500, 0, "running"))

    def test_live_migration_abort_still_working(self):
        # Elapsed time is less than completion timeout
        self.assertFalse(migration.should_trigger_timeout_action(
            self.instance, 4500, 9000, "running"))

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_no_steps(self, mock_dt):
        steps = []
        newdt = migration.update_downtime(self.guest, self.instance,
                                          None, steps, 5000)

        self.assertIsNone(newdt)
        self.assertFalse(mock_dt.called)

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_too_early(self, mock_dt):
        steps = [
            (9000, 50),
            (18000, 200),
        ]
        # We shouldn't change downtime since haven't hit first time
        newdt = migration.update_downtime(self.guest, self.instance,
                                          None, steps, 5000)

        self.assertIsNone(newdt)
        self.assertFalse(mock_dt.called)

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_step1(self, mock_dt):
        steps = [
            (9000, 50),
            (18000, 200),
        ]
        # We should pick the first downtime entry
        newdt = migration.update_downtime(self.guest, self.instance,
                                          None, steps, 11000)

        self.assertEqual(newdt, 50)
        mock_dt.assert_called_once_with(50)

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_nostep1(self, mock_dt):
        steps = [
            (9000, 50),
            (18000, 200),
        ]
        # We shouldn't change downtime, since its already set
        newdt = migration.update_downtime(self.guest, self.instance,
                                          50, steps, 11000)

        self.assertEqual(newdt, 50)
        self.assertFalse(mock_dt.called)

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_step2(self, mock_dt):
        steps = [
            (9000, 50),
            (18000, 200),
        ]
        newdt = migration.update_downtime(self.guest, self.instance,
                                          50, steps, 22000)

        self.assertEqual(newdt, 200)
        mock_dt.assert_called_once_with(200)

    @mock.patch.object(libvirt_guest.Guest,
                       "migrate_configure_max_downtime")
    def test_live_migration_update_downtime_err(self, mock_dt):
        steps = [
            (9000, 50),
            (18000, 200),
        ]
        mock_dt.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "Failed to set downtime",
            error_code=fakelibvirt.VIR_ERR_INTERNAL_ERROR)

        newdt = migration.update_downtime(self.guest, self.instance,
                                          50, steps, 22000)

        self.assertEqual(newdt, 200)
        mock_dt.assert_called_once_with(200)

    @mock.patch.object(objects.Instance, "save")
    @mock.patch.object(objects.Migration, "save")
    def test_live_migration_save_stats(self, mock_isave, mock_msave):
        mig = objects.Migration()

        info = libvirt_guest.JobInfo(
            memory_total=1 * units.Gi,
            memory_processed=5 * units.Gi,
            memory_remaining=500 * units.Mi,
            disk_total=15 * units.Gi,
            disk_processed=10 * units.Gi,
            disk_remaining=14 * units.Gi)

        migration.save_stats(self.instance, mig, info, 75)

        self.assertEqual(mig.memory_total, 1 * units.Gi)
        self.assertEqual(mig.memory_processed, 5 * units.Gi)
        self.assertEqual(mig.memory_remaining, 500 * units.Mi)
        self.assertEqual(mig.disk_total, 15 * units.Gi)
        self.assertEqual(mig.disk_processed, 10 * units.Gi)
        self.assertEqual(mig.disk_remaining, 14 * units.Gi)

        self.assertEqual(self.instance.progress, 25)

        mock_msave.assert_called_once_with()
        mock_isave.assert_called_once_with()

    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_empty_tasks(self, mock_pause,
                                                  mock_postcopy):
        tasks = deque()
        active_migrations = {self.instance.uuid: tasks}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, False)

        self.assertFalse(mock_pause.called)
        self.assertFalse(mock_postcopy.called)
        self.assertEqual(len(on_migration_failure), 0)

    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_no_tasks(self, mock_pause,
                                               mock_postcopy):
        active_migrations = {}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, False)

        self.assertFalse(mock_pause.called)
        self.assertFalse(mock_postcopy.called)
        self.assertEqual(len(on_migration_failure), 0)

    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_no_force_complete(self, mock_pause,
                                                        mock_postcopy):
        tasks = deque()
        # Test to ensure unknown tasks are ignored
        tasks.append("wibble")
        active_migrations = {self.instance.uuid: tasks}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, False)

        self.assertFalse(mock_pause.called)
        self.assertFalse(mock_postcopy.called)
        self.assertEqual(len(on_migration_failure), 0)

    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_force_complete(self, mock_pause,
                                                     mock_postcopy):
        tasks = deque()
        tasks.append("force-complete")
        active_migrations = {self.instance.uuid: tasks}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, False)

        mock_pause.assert_called_once_with()
        self.assertFalse(mock_postcopy.called)
        self.assertEqual(len(on_migration_failure), 1)
        self.assertEqual(on_migration_failure.pop(), "unpause")

    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_force_complete_postcopy_running(self,
        mock_pause, mock_postcopy):
        tasks = deque()
        tasks.append("force-complete")
        active_migrations = {self.instance.uuid: tasks}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running (post-copy)")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, True)

        self.assertFalse(mock_pause.called)
        self.assertFalse(mock_postcopy.called)
        self.assertEqual(len(on_migration_failure), 0)

    @mock.patch.object(objects.Migration, "save")
    @mock.patch.object(libvirt_guest.Guest, "migrate_start_postcopy")
    @mock.patch.object(libvirt_guest.Guest, "pause")
    def test_live_migration_run_tasks_force_complete_postcopy(self,
        mock_pause, mock_postcopy, mock_msave):
        tasks = deque()
        tasks.append("force-complete")
        active_migrations = {self.instance.uuid: tasks}
        on_migration_failure = deque()

        mig = objects.Migration(id=1, status="running")

        migration.run_tasks(self.guest, self.instance,
                            active_migrations, on_migration_failure,
                            mig, True)

        mock_postcopy.assert_called_once_with()
        self.assertFalse(mock_pause.called)
        self.assertEqual(len(on_migration_failure), 0)

    @mock.patch.object(libvirt_guest.Guest, "resume")
    @mock.patch.object(libvirt_guest.Guest, "get_power_state",
                       return_value=power_state.PAUSED)
    def test_live_migration_recover_tasks_resume(self, mock_ps, mock_resume):
        tasks = deque()
        tasks.append("unpause")

        migration.run_recover_tasks(self.host, self.guest,
                                    self.instance, tasks)

        mock_resume.assert_called_once_with()

    @mock.patch.object(libvirt_guest.Guest, "resume")
    @mock.patch.object(libvirt_guest.Guest, "get_power_state",
                       return_value=power_state.RUNNING)
    def test_live_migration_recover_tasks_no_resume(self, mock_ps,
                                                    mock_resume):
        tasks = deque()
        tasks.append("unpause")

        migration.run_recover_tasks(self.host, self.guest,
                                    self.instance, tasks)

        self.assertFalse(mock_resume.called)

    @mock.patch.object(libvirt_guest.Guest, "resume")
    def test_live_migration_recover_tasks_empty_tasks(self, mock_resume):
        tasks = deque()

        migration.run_recover_tasks(self.host, self.guest,
                                    self.instance, tasks)

        self.assertFalse(mock_resume.called)

    @mock.patch.object(libvirt_guest.Guest, "resume")
    def test_live_migration_recover_tasks_no_pause(self, mock_resume):
        tasks = deque()
        # Test to ensure unknown tasks are ignored
        tasks.append("wibble")

        migration.run_recover_tasks(self.host, self.guest,
                                    self.instance, tasks)

        self.assertFalse(mock_resume.called)

    def test_live_migration_downtime_steps(self):
        self.flags(live_migration_downtime=400, group='libvirt')
        self.flags(live_migration_downtime_steps=10, group='libvirt')
        self.flags(live_migration_downtime_delay=30, group='libvirt')

        steps = migration.downtime_steps(3.0)

        self.assertEqual([
            (0, 40),
            (90, 76),
            (180, 112),
            (270, 148),
            (360, 184),
            (450, 220),
            (540, 256),
            (630, 292),
            (720, 328),
            (810, 364),
            (900, 400),
        ], list(steps))
