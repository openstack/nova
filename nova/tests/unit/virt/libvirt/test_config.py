#    Copyright (C) 2012 Red Hat, Inc.
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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units

from nova import exception
from nova.objects import fields as obj_fields
from nova import test
from nova.tests.fixtures import libvirt_data as fake_libvirt_data
from nova.virt import hardware
from nova.virt.libvirt import config


class LibvirtConfigBaseTest(test.NoDBTestCase):
    pass


class LibvirtConfigTest(LibvirtConfigBaseTest):

    def test_config_plain(self):
        obj = config.LibvirtConfigObject(root_name="demo")
        xml = obj.to_xml()

        self.assertXmlEqual(xml, "<demo/>")

    def test_config_ns(self):
        obj = config.LibvirtConfigObject(root_name="demo", ns_prefix="foo",
                                         ns_uri="http://example.com/foo")
        xml = obj.to_xml()

        self.assertXmlEqual(xml, """
            <foo:demo xmlns:foo="http://example.com/foo"/>""")

    def test_config_text(self):
        obj = config.LibvirtConfigObject(root_name="demo")
        root = obj.format_dom()
        root.append(obj._text_node("foo", "bar"))

        xml = etree.tostring(root, encoding='unicode')
        self.assertXmlEqual(xml, "<demo><foo>bar</foo></demo>")

    def test_config_text_unicode(self):
        obj = config.LibvirtConfigObject(root_name='demo')
        root = obj.format_dom()
        root.append(obj._text_node('foo', u'\xF0\x9F\x92\xA9'))
        self.assertXmlEqual('<demo><foo>&#240;&#159;&#146;&#169;</foo></demo>',
                            etree.tostring(root, encoding='unicode'))

    def test_config_text_node_name_attr(self):
        obj = config.LibvirtConfigObject(root_name='demo')
        root = obj.format_dom()
        root.append(obj._text_node('foo', 'bar', name='foobar'))
        self.assertXmlEqual('<demo><foo name="foobar">bar</foo></demo>',
                            etree.tostring(root, encoding='unicode'))

    def test_config_parse(self):
        inxml = "<demo><foo/></demo>"
        obj = config.LibvirtConfigObject(root_name="demo")
        obj.parse_str(inxml)

    def test_parse_on_off_str(self):
        obj = config.LibvirtConfigObject(root_name="demo")
        self.assertTrue(obj.parse_on_off_str('on'))
        self.assertFalse(obj.parse_on_off_str('off'))
        self.assertFalse(obj.parse_on_off_str(None))
        self.assertRaises(exception.InvalidInput, obj.parse_on_off_str, 'foo')

    def test_get_yes_no_str(self):
        obj = config.LibvirtConfigObject(root_name="demo")
        self.assertEqual('yes', obj.get_yes_no_str(True))
        self.assertEqual('no', obj.get_yes_no_str(False))

    def test_get_on_off_str(self):
        obj = config.LibvirtConfigObject(root_name="demo")
        self.assertEqual('on', obj.get_on_off_str(True))
        self.assertEqual('off', obj.get_on_off_str(False))


class LibvirtConfigCapsTest(LibvirtConfigBaseTest):

    def test_config_host(self):
        xmlin = """
        <capabilities>
          <host>
            <uuid>c7a5fdbd-edaf-9455-926a-d65c16db1809</uuid>
            <cpu>
              <arch>x86_64</arch>
              <model>Opteron_G3</model>
              <vendor>AMD</vendor>
              <topology sockets='1' cores='4' threads='1'/>
              <feature name='ibs'/>
              <feature name='osvw'/>
            </cpu>
            <topology>
              <cells num='2'>
                <cell id='0'>
                  <memory unit='KiB'>4048280</memory>
                  <pages unit='KiB' size='4'>1011941</pages>
                  <pages unit='KiB' size='2048'>0</pages>
                  <cpus num='4'>
                    <cpu id='0' socket_id='0' core_id='0' siblings='0'/>
                    <cpu id='1' socket_id='0' core_id='1' siblings='1'/>
                    <cpu id='2' socket_id='0' core_id='2' siblings='2'/>
                    <cpu id='3' socket_id='0' core_id='3' siblings='3'/>
                  </cpus>
                </cell>
                <cell id='1'>
                  <memory unit='KiB'>4127684</memory>
                  <pages unit='KiB' size='4'>1031921</pages>
                  <pages unit='KiB' size='2048'>0</pages>
                  <cpus num='4'>
                    <cpu id='4' socket_id='1' core_id='0' siblings='4'/>
                    <cpu id='5' socket_id='1' core_id='1' siblings='5'/>
                    <cpu id='6' socket_id='1' core_id='2' siblings='6'/>
                    <cpu id='7' socket_id='1' core_id='3' siblings='7'/>
                  </cpus>
                </cell>
              </cells>
            </topology>
          </host>
        </capabilities>"""

        obj = config.LibvirtConfigCaps()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.host, config.LibvirtConfigCapsHost)
        self.assertEqual(obj.host.uuid, "c7a5fdbd-edaf-9455-926a-d65c16db1809")

        xmlout = obj.to_xml()

        self.assertXmlEqual(xmlin, xmlout)

    def test_config_host_numa_cell_no_memory_caps(self):
        xmlin = """
          <cell id='0'>
            <cpus num='1'>
              <cpu id='0' socket_id='0' core_id='0' siblings='0'/>
            </cpus>
          </cell>"""
        obj = config.LibvirtConfigCapsNUMACell()
        obj.parse_str(xmlin)
        self.assertEqual(0, obj.memory)
        self.assertEqual(1, len(obj.cpus))

    def test_config_host_numa_cell_no_cpus_caps(self):
        xmlin = """
          <cell id='0'>
            <memory unit='KiB'>128</memory>
          </cell>"""
        obj = config.LibvirtConfigCapsNUMACell()
        obj.parse_str(xmlin)
        self.assertEqual(128, obj.memory)
        self.assertEqual(0, len(obj.cpus))

    def test_config_guest(self):
        xmlin = """
        <capabilities>
          <guest>
            <os_type>hvm</os_type>
            <arch name='x86_64'>
              <emulator>/usr/bin/qemu-system-x86_64</emulator>
              <machine maxCpus='255'>pc-i440fx-2.11</machine>
              <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
              <machine maxCpus='1'>isapc</machine>
              <machine maxCpus='255'>pc-1.1</machine>
              <machine maxCpus='255'>pc-i440fx-2.0</machine>
              <machine maxCpus='288'>pc-q35-2.11</machine>
              <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
              <machine maxCpus='1'>xenpv</machine>
              <machine maxCpus='288'>pc-q35-2.10</machine>
              <domain type="qemu" />
              <domain type="kvm">
                <emulator>/usr/bin/qemu-kvm</emulator>
                <machine maxCpus='255'>pc-i440fx-2.11</machine>
                <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
                <machine maxCpus='1'>isapc</machine>
                <machine maxCpus='255'>pc-1.1</machine>
                <machine maxCpus='255'>pc-i440fx-2.0</machine>
                <machine maxCpus='288'>pc-q35-2.11</machine>
                <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
                <machine maxCpus='1'>xenpv</machine>
                <machine maxCpus='288'>pc-q35-2.10</machine>
              </domain>
            </arch>
          </guest>
          <guest>
            <os_type>hvm</os_type>
            <arch name='i686'>
              <emulator>/usr/bin/qemu-system-i386</emulator>
              <machine maxCpus='255'>pc-i440fx-2.11</machine>
              <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
              <machine maxCpus='1'>isapc</machine>
              <machine maxCpus='255'>pc-1.1</machine>
              <machine maxCpus='255'>pc-i440fx-2.0</machine>
              <machine maxCpus='288'>pc-q35-2.11</machine>
              <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
              <machine maxCpus='1'>xenpv</machine>
              <machine maxCpus='288'>pc-q35-2.10</machine>
              <domain type="qemu" />
              <domain type="kvm">
                <emulator>/usr/bin/qemu-kvm</emulator>
                <machine maxCpus='255'>pc-i440fx-2.11</machine>
                <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
                <machine maxCpus='1'>isapc</machine>
                <machine maxCpus='255'>pc-1.1</machine>
                <machine maxCpus='255'>pc-i440fx-2.0</machine>
                <machine maxCpus='288'>pc-q35-2.11</machine>
                <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
                <machine maxCpus='1'>xenpv</machine>
                <machine maxCpus='288'>pc-q35-2.10</machine>
              </domain>
            </arch>
          </guest>
        </capabilities>"""
        obj = config.LibvirtConfigCaps()
        obj.parse_str(xmlin)

        self.assertEqual(2, len(obj.guests))
        for guest in obj.guests:
            self.assertIsInstance(guest, config.LibvirtConfigCapsGuest)
            self.assertEqual('hvm', guest.ostype)

        self.assertEqual('x86_64', obj.guests[0].arch)
        self.assertEqual('i686', obj.guests[1].arch)

        guest = obj.guests[0]
        self.assertIn('qemu', guest.domains)
        self.assertIn('kvm', guest.domains)
        self.assertEqual('qemu', guest.default_domain.domtype)
        self.assertEqual('/usr/bin/qemu-system-x86_64',
                         guest.default_domain.emulator)
        self.assertEqual(guest.default_domain, guest.domains['qemu'])
        for domtype, domain in guest.domains.items():
            self.assertEqual(7, len(domain.machines))
            self.assertIn('pc-i440fx-2.0', domain.machines)
            self.assertIn('xenpv', domain.machines)
            self.assertEqual(2, len(domain.aliases))
            self.assertIn('pc', domain.aliases)
            self.assertIn('q35', domain.aliases)

        xmlout = obj.to_xml()
        self.assertXmlEqual(xmlin, xmlout, allow_mixed_nodes=True)


class LibvirtConfigGuestTimerTest(LibvirtConfigBaseTest):
    def test_config_platform(self):
        obj = config.LibvirtConfigGuestTimer()
        obj.track = "host"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <timer name="platform" track="host"/>
        """)

    def test_config_pit(self):
        obj = config.LibvirtConfigGuestTimer()
        obj.name = "pit"
        obj.tickpolicy = "discard"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <timer name="pit" tickpolicy="discard"/>
        """)

    def test_config_hpet(self):
        obj = config.LibvirtConfigGuestTimer()
        obj.name = "hpet"
        obj.present = False

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <timer name="hpet" present="no"/>
        """)


class LibvirtConfigGuestClockTest(LibvirtConfigBaseTest):
    def test_config_utc(self):
        obj = config.LibvirtConfigGuestClock()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <clock offset="utc"/>
        """)

    def test_config_localtime(self):
        obj = config.LibvirtConfigGuestClock()
        obj.offset = "localtime"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <clock offset="localtime"/>
        """)

    def test_config_timezone(self):
        obj = config.LibvirtConfigGuestClock()
        obj.offset = "timezone"
        obj.timezone = "EDT"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <clock offset="timezone" timezone="EDT"/>
        """)

    def test_config_variable(self):
        obj = config.LibvirtConfigGuestClock()
        obj.offset = "variable"
        obj.adjustment = "123456"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <clock offset="variable" adjustment="123456"/>
        """)

    def test_config_timers(self):
        obj = config.LibvirtConfigGuestClock()

        tmpit = config.LibvirtConfigGuestTimer()
        tmpit.name = "pit"
        tmpit.tickpolicy = "discard"

        tmrtc = config.LibvirtConfigGuestTimer()
        tmrtc.name = "rtc"
        tmrtc.tickpolicy = "merge"

        obj.add_timer(tmpit)
        obj.add_timer(tmrtc)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <clock offset="utc">
               <timer name="pit" tickpolicy="discard"/>
               <timer name="rtc" tickpolicy="merge"/>
            </clock>
        """)


class LibvirtConfigCPUFeatureTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigCPUFeature("mtrr")

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <feature name="mtrr"/>
        """)

    def test_config_parse_require(self):
        xml = """
            <feature name="mtrr" policy="require"/>
        """
        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigCPUFeature()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.policy, "require")

    def test_config_parse_disable(self):
        xml = """
            <feature name="mtrr" policy="disable"/>
        """
        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigCPUFeature()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.policy, "disable")


class LibvirtConfigGuestCPUFeatureTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigGuestCPUFeature("mtrr")
        obj.policy = "force"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <feature name="mtrr" policy="force"/>
        """)

    def test_config_simple_pcid(self):
        obj = config.LibvirtConfigGuestCPUFeature("pcid")
        obj.policy = "require"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <feature name="pcid" policy="require"/>
        """)


class LibvirtConfigGuestCPUNUMATest(LibvirtConfigBaseTest):

    def test_parse_dom(self):
        xml = """
            <numa>
              <cell id="0" cpus="0-1" memory="1000000"/>
              <cell id="1" cpus="2-3" memory="1500000"/>
            </numa>
        """
        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigGuestCPUNUMA()
        obj.parse_dom(xmldoc)

        self.assertEqual(2, len(obj.cells))

    def test_config_simple(self):
        obj = config.LibvirtConfigGuestCPUNUMA()

        cell = config.LibvirtConfigGuestCPUNUMACell()
        cell.id = 0
        cell.cpus = set([0, 1])
        cell.memory = 1000000
        cell.memAccess = "shared"

        obj.cells.append(cell)

        cell = config.LibvirtConfigGuestCPUNUMACell()
        cell.id = 1
        cell.cpus = set([2, 3])
        cell.memory = 1500000
        cell.memAccess = "private"

        obj.cells.append(cell)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <numa>
              <cell id="0" cpus="0-1" memory="1000000" memAccess="shared"/>
              <cell id="1" cpus="2-3" memory="1500000" memAccess="private"/>
            </numa>
        """)


class LibvirtConfigCPUTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigCPU()
        obj.model = "Penryn"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu>
              <model>Penryn</model>
            </cpu>
        """)

    def test_config_complex(self):
        obj = config.LibvirtConfigCPU()
        obj.model = "Penryn"
        obj.vendor = "Intel"
        obj.arch = obj_fields.Architecture.X86_64

        obj.add_feature(config.LibvirtConfigCPUFeature("mtrr"))
        obj.add_feature(config.LibvirtConfigCPUFeature("apic"))

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu>
              <arch>x86_64</arch>
              <model>Penryn</model>
              <vendor>Intel</vendor>
              <feature name="apic"/>
              <feature name="mtrr"/>
            </cpu>
        """)

    def test_only_uniq_cpu_featues(self):
        obj = config.LibvirtConfigCPU()
        obj.model = "Penryn"
        obj.vendor = "Intel"
        obj.arch = obj_fields.Architecture.X86_64

        obj.add_feature(config.LibvirtConfigCPUFeature("mtrr"))
        obj.add_feature(config.LibvirtConfigCPUFeature("apic"))
        obj.add_feature(config.LibvirtConfigCPUFeature("apic"))
        obj.add_feature(config.LibvirtConfigCPUFeature("mtrr"))

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu>
              <arch>x86_64</arch>
              <model>Penryn</model>
              <vendor>Intel</vendor>
              <feature name="apic"/>
              <feature name="mtrr"/>
            </cpu>
        """)

    def test_config_topology(self):
        obj = config.LibvirtConfigCPU()
        obj.model = "Penryn"
        obj.sockets = 4
        obj.cores = 4
        obj.threads = 2

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu>
              <model>Penryn</model>
              <topology sockets="4" cores="4" threads="2"/>
            </cpu>
        """)


class LibvirtConfigGuestCPUTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigGuestCPU()
        obj.model = "Penryn"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu match="exact">
              <model>Penryn</model>
            </cpu>
        """)

    def test_config_complex(self):
        obj = config.LibvirtConfigGuestCPU()
        obj.model = "Penryn"
        obj.vendor = "Intel"
        obj.arch = obj_fields.Architecture.X86_64
        obj.mode = "custom"

        obj.add_feature(config.LibvirtConfigGuestCPUFeature("mtrr"))
        obj.add_feature(config.LibvirtConfigGuestCPUFeature("apic"))

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu mode="custom" match="exact">
              <arch>x86_64</arch>
              <model>Penryn</model>
              <vendor>Intel</vendor>
              <feature name="apic" policy="require"/>
              <feature name="mtrr" policy="require"/>
            </cpu>
        """)

    def test_config_host(self):
        obj = config.LibvirtConfigGuestCPU()
        obj.mode = "host-model"
        obj.match = "exact"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu mode="host-model" match="exact"/>
        """)

    def test_config_host_with_numa(self):
        obj = config.LibvirtConfigGuestCPU()
        obj.mode = "host-model"
        obj.match = "exact"

        numa = config.LibvirtConfigGuestCPUNUMA()

        cell = config.LibvirtConfigGuestCPUNUMACell()
        cell.id = 0
        cell.cpus = set([0, 1])
        cell.memory = 1000000
        cell.memAccess = "private"

        numa.cells.append(cell)

        cell = config.LibvirtConfigGuestCPUNUMACell()
        cell.id = 1
        cell.cpus = set([2, 3])
        cell.memory = 1500000

        numa.cells.append(cell)

        obj.numa = numa

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <cpu mode="host-model" match="exact">
              <numa>
                <cell id="0" cpus="0-1" memory="1000000" memAccess="private"/>
                <cell id="1" cpus="2-3" memory="1500000"/>
              </numa>
            </cpu>
        """)


class LibvirtConfigGuestSMBIOSTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigGuestSMBIOS()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <smbios mode="sysinfo"/>
        """)


class LibvirtConfigGuestSysinfoTest(LibvirtConfigBaseTest):

    def test_config_simple(self):
        obj = config.LibvirtConfigGuestSysinfo()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <sysinfo type="smbios"/>
        """)

    def test_config_bios(self):
        obj = config.LibvirtConfigGuestSysinfo()
        obj.bios_vendor = "Acme"
        obj.bios_version = "6.6.6"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <sysinfo type="smbios">
              <bios>
                <entry name="vendor">Acme</entry>
                <entry name="version">6.6.6</entry>
              </bios>
            </sysinfo>
        """)

    def test_config_system(self):
        obj = config.LibvirtConfigGuestSysinfo()
        obj.system_manufacturer = "Acme"
        obj.system_product = "Wile Coyote"
        obj.system_version = "6.6.6"
        obj.system_serial = "123456"
        obj.system_uuid = "c7a5fdbd-edaf-9455-926a-d65c16db1809"
        obj.system_family = "Anvils"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <sysinfo type="smbios">
              <system>
                <entry name="manufacturer">Acme</entry>
                <entry name="product">Wile Coyote</entry>
                <entry name="version">6.6.6</entry>
                <entry name="serial">123456</entry>
                <entry name="uuid">c7a5fdbd-edaf-9455-926a-d65c16db1809</entry>
                <entry name="family">Anvils</entry>
              </system>
            </sysinfo>
        """)

    def test_config_mixed(self):
        obj = config.LibvirtConfigGuestSysinfo()
        obj.bios_vendor = "Acme"
        obj.system_manufacturer = "Acme"
        obj.system_product = "Wile Coyote"
        obj.system_uuid = "c7a5fdbd-edaf-9455-926a-d65c16db1809"
        obj.system_family = "Anvils"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <sysinfo type="smbios">
              <bios>
                <entry name="vendor">Acme</entry>
              </bios>
              <system>
                <entry name="manufacturer">Acme</entry>
                <entry name="product">Wile Coyote</entry>
                <entry name="uuid">c7a5fdbd-edaf-9455-926a-d65c16db1809</entry>
                <entry name="family">Anvils</entry>
              </system>
            </sysinfo>
        """)


class LibvirtConfigGuestDiskTest(LibvirtConfigBaseTest):

    def test_config_file(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
            </disk>""")

    def test_config_file_parse(self):
        xml = """<disk type="file" device="disk">
                   <source file="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hda"/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.source_path, '/tmp/hello')
        self.assertEqual(obj.target_dev, '/dev/hda')
        self.assertEqual(obj.target_bus, 'ide')
        self.assertFalse(obj.readonly)
        self.assertFalse(obj.shareable)

    def test_config_file_readonly(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.readonly = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
              <readonly/>
            </disk>""")

    def test_config_file_parse_readonly(self):
        xml = """<disk type="file" device="disk">
                   <source file="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hda"/>
                   <readonly/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.source_path, '/tmp/hello')
        self.assertEqual(obj.target_dev, '/dev/hda')
        self.assertEqual(obj.target_bus, 'ide')
        self.assertTrue(obj.readonly)
        self.assertFalse(obj.shareable)

    def test_config_file_shareable(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.shareable = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
              <shareable/>
            </disk>""")

    def test_config_file_parse_shareable(self):
        xml = """<disk type="file" device="disk">
                   <source file="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hda"/>
                   <shareable/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.source_path, '/tmp/hello')
        self.assertEqual(obj.target_dev, '/dev/hda')
        self.assertEqual(obj.target_bus, 'ide')
        self.assertFalse(obj.readonly)
        self.assertTrue(obj.shareable)

    def test_config_file_serial(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.serial = "7a97c4a3-6f59-41d4-bf47-191d7f97f8e9"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>""")

    def test_config_file_serial_parse(self):
        xml = """<disk type="file" device="disk">
                   <source file="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hda"/>
                   <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.serial, '7a97c4a3-6f59-41d4-bf47-191d7f97f8e9')

    def test_config_file_discard(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.driver_name = "qemu"
        obj.driver_format = "qcow2"
        obj.driver_cache = "none"
        obj.driver_discard = "unmap"
        obj.source_type = "file"
        obj.source_path = "/tmp/hello.qcow2"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.serial = "7a97c4a3-6f59-41d4-bf47-191d7f97f8e9"

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" discard="unmap"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>""", xml)

    def test_config_file_discard_parse(self):
        xml = """
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" discard="unmap"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual('unmap', obj.driver_discard)

    def test_config_file_io(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.driver_name = "qemu"
        obj.driver_format = "qcow2"
        obj.driver_cache = "none"
        obj.driver_io = "native"
        obj.source_type = "file"
        obj.source_path = "/tmp/hello.qcow2"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.serial = "7a97c4a3-6f59-41d4-bf47-191d7f97f8e9"

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" io="native"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>""", xml)

    def test_config_file_io_parse(self):
        xml = """
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" io="native"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual('native', obj.driver_io)

    def test_config_boot_order(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.driver_name = "qemu"
        obj.driver_format = "qcow2"
        obj.driver_cache = "none"
        obj.driver_io = "native"
        obj.source_type = "file"
        obj.source_path = "/tmp/hello.qcow2"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.serial = "7a97c4a3-6f59-41d4-bf47-191d7f97f8e9"
        obj.boot_order = "1"

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" io="native"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
              <boot order="1"/>
            </disk>""", xml)

    def test_config_mirror_parse(self):
        xml = """
<disk type="file" device="disk">
  <driver name="qemu" type="qcow2" cache="none" discard="unmap"/>
  <source file="/tmp/hello.qcow2"/>
  <target bus="ide" dev="/dev/hda"/>
  <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
  <mirror type='file' file='/tmp/new.img' format='raw' job='copy' ready='yes'>
    <format type='raw'/>
    <source file='/tmp/new.img'/>
  </mirror>
  <boot order="1"/>
</disk>"""
        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)
        self.assertEqual(obj.mirror.ready, "yes")

    def test_config_disk_encryption_format(self):
        d = config.LibvirtConfigGuestDisk()
        e = config.LibvirtConfigGuestDiskEncryption()
        s = config.LibvirtConfigGuestDiskEncryptionSecret()

        d.driver_name = "qemu"
        d.driver_format = "qcow2"
        d.driver_cache = "none"
        d.driver_io = "native"
        d.source_type = "file"
        d.source_path = "/tmp/hello.qcow2"
        d.target_dev = "/dev/hda"
        d.target_bus = "ide"
        d.serial = uuids.serial
        d.boot_order = "1"
        e.format = "luks"
        s.type = "passphrase"
        s.uuid = uuids.secret
        e.secret = s
        d.encryption = e

        xml = d.to_xml()
        expected_xml = """
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" io="native"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>%s</serial>
              <boot order="1"/>
              <encryption format='luks'>
                <secret type='passphrase' uuid='%s'/>
              </encryption>
            </disk>""" % (uuids.serial, uuids.secret)
        self.assertXmlEqual(expected_xml, xml)

    def test_config_disk_encryption_parse(self):
        xml = """
<disk type="file" device="disk">
  <driver name="qemu" type="qcow2" cache="none" io="native"/>
  <source file="/tmp/hello.qcow2"/>
  <target bus="ide" dev="/dev/hda"/>
  <serial>%s</serial>
  <boot order="1"/>
  <encryption format='luks'>
    <secret type='passphrase' uuid='%s'/>
  </encryption>
</disk>""" % (uuids.serial, uuids.secret)

        xmldoc = etree.fromstring(xml)
        d = config.LibvirtConfigGuestDisk()
        d.parse_dom(xmldoc)

        self.assertEqual(d.encryption.format, "luks")
        self.assertEqual(d.encryption.secret.type, "passphrase")
        self.assertEqual(d.encryption.secret.uuid, uuids.secret)

    def test_config_boot_order_parse(self):
        xml = """
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2" cache="none" discard="unmap"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="ide" dev="/dev/hda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
              <boot order="1"/>
            </disk>"""
        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)
        self.assertEqual(obj.boot_order, "1")

    def test_config_block(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "block"
        obj.source_path = "/tmp/hello"
        obj.source_device = "cdrom"
        obj.driver_name = "qemu"
        obj.target_dev = "/dev/hdc"
        obj.target_bus = "ide"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="block" device="cdrom">
              <driver name="qemu"/>
              <source dev="/tmp/hello"/>
              <target bus="ide" dev="/dev/hdc"/>
            </disk>""")

    def test_config_block_parse(self):
        xml = """<disk type="block" device="cdrom">
                   <driver name="qemu"/>
                   <source dev="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hdc"/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'block')
        self.assertEqual(obj.source_path, '/tmp/hello')
        self.assertEqual(obj.target_dev, '/dev/hdc')
        self.assertEqual(obj.target_bus, 'ide')

    def test_config_network(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "network"
        obj.source_protocol = "iscsi"
        obj.source_name = "foo.bar.com"
        obj.driver_name = "qemu"
        obj.driver_format = "qcow2"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="network" device="disk">
              <driver name="qemu" type="qcow2"/>
              <source name="foo.bar.com" protocol="iscsi"/>
              <target bus="ide" dev="/dev/hda"/>
            </disk>""")

    def test_config_network_parse(self):
        xml = """<disk type="network" device="disk">
                   <driver name="qemu" type="qcow2"/>
                   <source name="foo.bar.com" protocol="iscsi"/>
                   <target bus="ide" dev="/dev/hda"/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'network')
        self.assertEqual(obj.source_protocol, 'iscsi')
        self.assertEqual(obj.source_name, 'foo.bar.com')
        self.assertEqual(obj.driver_name, 'qemu')
        self.assertEqual(obj.driver_format, 'qcow2')
        self.assertEqual(obj.target_dev, '/dev/hda')
        self.assertEqual(obj.target_bus, 'ide')

    def test_config_network_no_name(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = 'network'
        obj.source_protocol = 'nbd'
        obj.source_hosts = ['foo.bar.com']
        obj.source_ports = [None]
        obj.driver_name = 'qemu'
        obj.driver_format = 'raw'
        obj.target_dev = '/dev/vda'
        obj.target_bus = 'virtio'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="network" device="disk">
              <driver name="qemu" type="raw"/>
              <source protocol="nbd">
                <host name="foo.bar.com"/>
              </source>
              <target bus="virtio" dev="/dev/vda"/>
            </disk>""")

    def test_config_network_multihost(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = 'network'
        obj.source_protocol = 'rbd'
        obj.source_name = 'pool/image'
        obj.source_hosts = ['foo.bar.com', '::1', '1.2.3.4']
        obj.source_ports = [None, '123', '456']
        obj.driver_name = 'qemu'
        obj.driver_format = 'raw'
        obj.target_dev = '/dev/vda'
        obj.target_bus = 'virtio'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="network" device="disk">
              <driver name="qemu" type="raw"/>
              <source name="pool/image" protocol="rbd">
                <host name="foo.bar.com"/>
                <host name="::1" port="123"/>
                <host name="1.2.3.4" port="456"/>
              </source>
              <target bus="virtio" dev="/dev/vda"/>
            </disk>""")

    def test_config_network_auth(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "network"
        obj.source_protocol = "rbd"
        obj.source_name = "pool/image"
        obj.driver_name = "qemu"
        obj.driver_format = "raw"
        obj.target_dev = "/dev/vda"
        obj.target_bus = "virtio"
        obj.auth_username = "foo"
        obj.auth_secret_type = "ceph"
        obj.auth_secret_uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0147"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="network" device="disk">
              <driver name="qemu" type="raw"/>
              <source name="pool/image" protocol="rbd"/>
              <auth username="foo">
                <secret type="ceph"
                uuid="b38a3f43-4be2-4046-897f-b67c2f5e0147"/>
              </auth>
              <target bus="virtio" dev="/dev/vda"/>
            </disk>""")

    def test_config_iotune(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        # Note that read/write iops/bytes values cannot be used with
        # total values. These are only here for illustrative purposes.
        obj.disk_read_bytes_sec = 1024000
        obj.disk_read_iops_sec = 1000
        obj.disk_total_bytes_sec = 2048000
        obj.disk_write_bytes_sec = 1024000
        obj.disk_write_iops_sec = 1000
        obj.disk_total_iops_sec = 2000
        obj.disk_write_bytes_sec_max = 1536000
        obj.disk_write_iops_sec_max = 1500
        obj.disk_total_iops_sec_max = 3072000
        obj.disk_read_bytes_sec_max = 1536000
        obj.disk_read_iops_sec_max = 1500
        obj.disk_total_iops_sec_max = 2000
        obj.disk_total_bytes_sec_max = 3072000
        obj.disk_size_iops_sec = 16

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
              <iotune>
                <read_bytes_sec>1024000</read_bytes_sec>
                <read_iops_sec>1000</read_iops_sec>
                <write_bytes_sec>1024000</write_bytes_sec>
                <write_iops_sec>1000</write_iops_sec>
                <total_bytes_sec>2048000</total_bytes_sec>
                <total_iops_sec>2000</total_iops_sec>
                <read_bytes_sec_max>1536000</read_bytes_sec_max>
                <write_bytes_sec_max>1536000</write_bytes_sec_max>
                <total_bytes_sec_max>3072000</total_bytes_sec_max>
                <read_iops_sec_max>1500</read_iops_sec_max>
                <write_iops_sec_max>1500</write_iops_sec_max>
                <total_iops_sec_max>2000</total_iops_sec_max>
                <size_iops_sec>16</size_iops_sec>
              </iotune>
            </disk>""")

    def test_config_blockio(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"
        obj.logical_block_size = "4096"
        obj.physical_block_size = "4096"

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
              <blockio logical_block_size="4096" physical_block_size="4096"/>
            </disk>""", xml)

    def test_config_disk_device_address(self):
        xml = """
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='/var/lib/libvirt/images/centos.qcow2'/>
              <target dev='vda' bus='virtio'/>
              <address type='pci' domain='0x0000' bus='0x00' slot='0x09'
                       function='0x0'/>
            </disk>"""

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_str(xml)

        self.assertIsInstance(obj.device_addr,
                              config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertEqual('0000:00:09.0', obj.device_addr.format_address())

    def test_config_disk_device_address_no_format(self):
        xml = """
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='/var/lib/libvirt/images/generic.qcow2'/>
              <target dev='sda' bus='scsi'/>
              <address type='drive' controller='0' bus='0'
                       target='0' unit='1'/>
            </disk>"""

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_str(xml)

        self.assertIsInstance(obj.device_addr,
                              config.LibvirtConfigGuestDeviceAddressDrive)
        self.assertEqual(('0', '0', '0', '1'), (obj.device_addr.controller,
                                                obj.device_addr.bus,
                                                obj.device_addr.target,
                                                obj.device_addr.unit))
        self.assertIsNone(obj.device_addr.format_address())

    def test_config_disk_device_address_drive(self):
        obj = config.LibvirtConfigGuestDeviceAddressDrive()
        obj.controller = 1
        obj.bus = 2
        obj.target = 3
        obj.unit = 4

        xml = """
        <address type="drive" controller="1" bus="2" target="3" unit="4"/>
        """
        self.assertXmlEqual(xml, obj.to_xml())

    def test_config_disk_device_address_drive_added(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "scsi"
        obj.device_addr = config.LibvirtConfigGuestDeviceAddressDrive()
        obj.device_addr.controller = 1
        obj.device_addr.bus = 2
        obj.device_addr.target = 3
        obj.device_addr.unit = 4

        self.assertXmlEqual("""
        <disk type="file" device="disk">
          <source file="/tmp/hello"/>
          <target bus="scsi" dev="/dev/hda"/>
          <address type="drive" controller="1" bus="2" target="3" unit="4"/>
        </disk>""", obj.to_xml())

    def test_config_disk_device_address_pci(self):
        obj = config.LibvirtConfigGuestDeviceAddressPCI()
        obj.domain = 1
        obj.bus = 2
        obj.slot = 3
        obj.function = 4

        xml = """
        <address type="pci" domain="1" bus="2" slot="3" function="4"/>
        """
        self.assertXmlEqual(xml, obj.to_xml())

    def test_config_disk_device_address_pci_added(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "network"
        obj.source_name = "volumes/volume-0"
        obj.source_protocol = "rbd"
        obj.source_hosts = ["192.168.1.1"]
        obj.source_ports = ["1234"]
        obj.target_dev = "hdb"
        obj.target_bus = "virtio"
        obj.device_addr = config.LibvirtConfigGuestDeviceAddressPCI()
        obj.device_addr.domain = 1
        obj.device_addr.bus = 2
        obj.device_addr.slot = 3
        obj.device_addr.function = 4

        self.assertXmlEqual("""
        <disk type="network" device="disk">
          <source protocol="rbd" name="volumes/volume-0">
            <host name="192.168.1.1" port="1234"/>
          </source>
          <target bus="virtio" dev="hdb"/>
          <address type="pci" domain="1" bus="2" slot="3" function="4"/>
        </disk>""", obj.to_xml())

    def test_config_disk_device_address_type_virtio_mmio(self):
        xml = """
            <disk type='file' device='disk'>
                <driver name='qemu' type='qcow2' cache='none'/>
                <source file='/var/lib/libvirt/images/generic.qcow2'/>
                <target dev='vda' bus='virtio'/>
                <address type='virtio-mmio'/>
            </disk>"""

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_str(xml)

        self.assertNotIsInstance(obj.device_addr,
                                 config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertNotIsInstance(obj.device_addr,
                             config.LibvirtConfigGuestDeviceAddressDrive)

    def test_config_disk_device_address_type_ccw(self):
        xml = """
            <disk type='file' device='disk'>
                <driver name='qemu' type='qcow2'/>
                <source file='/var/lib/libvirt/images/test.qcow2'/>
                <backingStore/>
                <target dev='vda' bus='virtio'/>
                <alias name='virtio-disk0'/>
                <address type='ccw' cssid='0xfe' ssid='0x0' devno='0x0000'/>
            </disk>"""

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_str(xml)

        self.assertNotIsInstance(obj.device_addr,
                                 config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertNotIsInstance(obj.device_addr,
                                 config.LibvirtConfigGuestDeviceAddressDrive)


class LibvirtConfigGuestSnapshotDiskTest(LibvirtConfigBaseTest):

    def test_config_file(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.source_type = "file"
        obj.source_path = "/tmp/hello"
        obj.target_dev = "/dev/hda"
        obj.target_bus = "ide"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <disk type="file" device="disk">
              <source file="/tmp/hello"/>
              <target bus="ide" dev="/dev/hda"/>
            </disk>""")

    def test_config_file_parse(self):
        xml = """<disk type="file" device="disk">
                   <source file="/tmp/hello"/>
                   <target bus="ide" dev="/dev/hda"/>
                 </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.source_path, '/tmp/hello')
        self.assertEqual(obj.target_dev, '/dev/hda')
        self.assertEqual(obj.target_bus, 'ide')


class LibvirtConfigGuestDiskBackingStoreTest(LibvirtConfigBaseTest):

    def test_config_file_parse(self):
        xml = """<backingStore type='file'>
                   <driver name='qemu' type='qcow2'/>
                   <source file='/var/lib/libvirt/images/mid.qcow2'/>
                   <backingStore type='file'>
                     <driver name='qemu' type='qcow2'/>
                     <source file='/var/lib/libvirt/images/base.qcow2'/>
                     <backingStore/>
                   </backingStore>
                 </backingStore>
              """
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDiskBackingStore()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.driver_name, 'qemu')
        self.assertEqual(obj.driver_format, 'qcow2')
        self.assertEqual(obj.source_type, 'file')
        self.assertEqual(obj.source_file, '/var/lib/libvirt/images/mid.qcow2')
        self.assertEqual(obj.backing_store.driver_name, 'qemu')
        self.assertEqual(obj.backing_store.source_type, 'file')
        self.assertEqual(obj.backing_store.source_file,
                         '/var/lib/libvirt/images/base.qcow2')
        self.assertIsNone(obj.backing_store.backing_store)

    def test_config_network_parse(self):
        xml = """<backingStore type='network' index='1'>
                   <format type='qcow2'/>
                   <source protocol='netfs' name='volume1/img1'>
                     <host name='host1' port='24007'/>
                   </source>
                   <backingStore type='network' index='2'>
                     <format type='qcow2'/>
                     <source protocol='netfs' name='volume1/img2'>
                       <host name='host1' port='24007'/>
                     </source>
                     <backingStore/>
                   </backingStore>
                 </backingStore>
              """
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDiskBackingStore()
        obj.parse_dom(xmldoc)

        self.assertEqual(obj.source_type, 'network')
        self.assertEqual(obj.source_protocol, 'netfs')
        self.assertEqual(obj.source_name, 'volume1/img1')
        self.assertEqual(obj.source_hosts[0], 'host1')
        self.assertEqual(obj.source_ports[0], '24007')
        self.assertEqual(obj.index, '1')
        self.assertEqual(obj.backing_store.source_name, 'volume1/img2')
        self.assertEqual(obj.backing_store.index, '2')
        self.assertEqual(obj.backing_store.source_hosts[0], 'host1')
        self.assertEqual(obj.backing_store.source_ports[0], '24007')
        self.assertIsNone(obj.backing_store.backing_store)


class LibvirtConfigGuestFilesysTest(LibvirtConfigBaseTest):

    def test_config_mount(self):
        obj = config.LibvirtConfigGuestFilesys()
        obj.source_type = "mount"
        obj.source_dir = "/tmp/hello"
        obj.target_dir = "/mnt"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <filesystem type="mount">
              <source dir="/tmp/hello"/>
              <target dir="/mnt"/>
            </filesystem>""")

    def test_config_block(self):
        obj = config.LibvirtConfigGuestFilesys()
        obj.source_type = "block"
        obj.source_dev = "/dev/sdb"
        obj.target_dir = "/mnt"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <filesystem type="block">
              <source dev="/dev/sdb"/>
              <target dir="/mnt"/>
            </filesystem>""")

    def test_config_file(self):
        obj = config.LibvirtConfigGuestFilesys()
        obj.source_type = "file"
        obj.source_file = "/data/myimage.qcow2"
        obj.driver_type = "nbd"
        obj.driver_format = "qcow2"
        obj.target_dir = "/mnt"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <filesystem type="file">
              <driver format="qcow2" type="nbd"/>
              <source file="/data/myimage.qcow2"/>
              <target dir="/mnt"/>
            </filesystem>""")

    def test_parse_mount(self):
        xmldoc = """
          <filesystem type="mount">
            <source dir="/tmp/hello"/>
            <target dir="/mnt"/>
          </filesystem>
        """
        obj = config.LibvirtConfigGuestFilesys()
        obj.parse_str(xmldoc)
        self.assertEqual('mount', obj.source_type)
        self.assertEqual('/tmp/hello', obj.source_dir)
        self.assertEqual('/mnt', obj.target_dir)

    def test_parse_block(self):
        xmldoc = """
          <filesystem type="block">
            <source dev="/dev/sdb"/>
            <target dir="/mnt"/>
          </filesystem>
        """
        obj = config.LibvirtConfigGuestFilesys()
        obj.parse_str(xmldoc)
        self.assertEqual('block', obj.source_type)
        self.assertEqual('/dev/sdb', obj.source_dev)
        self.assertEqual('/mnt', obj.target_dir)

    def test_parse_file(self):
        xmldoc = """
          <filesystem type="file">
            <driver format="qcow2" type="nbd"/>
            <source file="/data/myimage.qcow2"/>
            <target dir="/mnt"/>
          </filesystem>
        """
        obj = config.LibvirtConfigGuestFilesys()
        obj.parse_str(xmldoc)
        self.assertEqual('file', obj.source_type)
        self.assertEqual('qcow2', obj.driver_format)
        self.assertEqual('nbd', obj.driver_type)
        self.assertEqual('/data/myimage.qcow2', obj.source_file)
        self.assertEqual('/mnt', obj.target_dir)


class LibvirtConfigGuestInputTest(LibvirtConfigBaseTest):

    def test_config_tablet(self):
        obj = config.LibvirtConfigGuestInput()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <input type="tablet" bus="usb"/>""")

    def test_config_input(self):
        obj = config.LibvirtConfigGuestInput()
        obj.type = "mouse"
        obj.bus = "virtio"
        obj.driver_iommu = True

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <input type="mouse" bus="virtio">
              <driver iommu="on" />
            </input>""", xml)


class LibvirtConfigGuestGraphicsTest(LibvirtConfigBaseTest):

    def test_config_graphics_vnc(self):
        obj = config.LibvirtConfigGuestGraphics()
        obj.type = "vnc"
        obj.autoport = True
        obj.keymap = "en_US"
        obj.listen = "127.0.0.1"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
  <graphics type="vnc" autoport="yes" keymap="en_US" listen="127.0.0.1"/>
                            """)

    def test_config_graphics_spice(self):
        obj = config.LibvirtConfigGuestGraphics()
        obj.type = "spice"
        obj.autoport = False
        obj.keymap = "en_US"
        obj.listen = "127.0.0.1"

        obj.image_compression = "auto_glz"
        obj.jpeg_compression = "auto"
        obj.zlib_compression = "always"
        obj.playback_compression = True
        obj.streaming_mode = "filter"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
  <graphics type="spice" autoport="no" keymap="en_US" listen="127.0.0.1">
    <image compression="auto_glz"/>
    <jpeg compression="auto"/>
    <zlib compression="always"/>
    <playback compression="on"/>
    <streaming mode="filter"/>
  </graphics>
                            """)


class LibvirtConfigGuestHostdev(LibvirtConfigBaseTest):

    def test_config_pci_guest_host_dev(self):
        obj = config.LibvirtConfigGuestHostdev()
        obj.mode = 'subsystem'
        obj.type = 'pci'

        xml = obj.to_xml()
        expected = """
            <hostdev mode="subsystem" type="pci" managed="yes"/>
            """
        self.assertXmlEqual(xml, expected)

    def test_parse_GuestHostdev(self):
        xmldoc = """<hostdev mode="subsystem" type="pci" managed="yes"/>"""
        obj = config.LibvirtConfigGuestHostdev()
        obj.parse_str(xmldoc)
        self.assertEqual(obj.mode, 'subsystem')
        self.assertEqual(obj.type, 'pci')
        self.assertEqual(obj.managed, 'yes')

    def test_parse_GuestHostdev_non_pci(self):
        xmldoc = """<hostdev mode="subsystem" type="usb" managed="no"/>"""
        obj = config.LibvirtConfigGuestHostdev()
        obj.parse_str(xmldoc)
        self.assertEqual(obj.mode, 'subsystem')
        self.assertEqual(obj.type, 'usb')
        self.assertEqual(obj.managed, 'no')


class LibvirtConfigGuestHostdevPCI(LibvirtConfigBaseTest):

    expected = """
            <hostdev mode="subsystem" type="pci" managed="yes">
                <source>
                    <address bus="0x11" domain="0x1234" function="0x3"
                             slot="0x22" />
                </source>
            </hostdev>
            """

    def test_config_guest_hostdev_pci(self):
        hostdev = config.LibvirtConfigGuestHostdevPCI()
        hostdev.domain = "1234"
        hostdev.bus = "11"
        hostdev.slot = "22"
        hostdev.function = "3"
        xml = hostdev.to_xml()
        self.assertXmlEqual(self.expected, xml)

    def test_parse_guest_hostdev_pci(self):
        xmldoc = self.expected
        obj = config.LibvirtConfigGuestHostdevPCI()
        obj.parse_str(xmldoc)
        self.assertEqual(obj.mode, 'subsystem')
        self.assertEqual(obj.type, 'pci')
        self.assertEqual(obj.managed, 'yes')
        self.assertEqual(obj.domain, '0x1234')
        self.assertEqual(obj.bus, '0x11')
        self.assertEqual(obj.slot, '0x22')
        self.assertEqual(obj.function, '0x3')

    def test_parse_guest_hostdev_usb(self):
        xmldoc = """<hostdev mode='subsystem' type='usb'>
                      <source startupPolicy='optional'>
                          <vendor id='0x1234'/>
                          <product id='0xbeef'/>
                      </source>
                      <boot order='2'/>
                    </hostdev>"""
        obj = config.LibvirtConfigGuestHostdevPCI()
        obj.parse_str(xmldoc)
        self.assertEqual(obj.mode, 'subsystem')
        self.assertEqual(obj.type, 'usb')

    def test_config_alias_parse(self):
        xml = """
            <hostdev mode='subsystem' type='pci' managed='yes'>
                <driver name='vfio'/>
                <source>
                    <address domain='0x0000' bus='0x81' slot='0x00'
                             function='0x1'/>
                </source>
                <alias name='hostdev1'/>
                <address type='pci' domain='0x0000' bus='0x00' slot='0x05'
                         function='0x0'/>
            </hostdev>"""

        xmldoc = etree.fromstring(xml)
        obj = config.LibvirtConfigGuestHostdevPCI()
        obj.parse_dom(xmldoc)
        self.assertEqual('hostdev1', obj.alias)


class LibvirtConfigGuestHostdevMDEV(LibvirtConfigBaseTest):

    expected = """
            <hostdev mode='subsystem' type='mdev' model='vfio-pci'
             managed='no'>
                <source>
                    <address uuid="b38a3f43-4be2-4046-897f-b67c2f5e0140" />
                </source>
            </hostdev>
            """

    def test_config_guest_hostdev_mdev(self):
        hostdev = config.LibvirtConfigGuestHostdevMDEV()
        hostdev.uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0140"
        xml = hostdev.to_xml()
        self.assertXmlEqual(self.expected, xml)

    def test_parse_guest_hostdev_mdev(self):
        xmldoc = self.expected
        obj = config.LibvirtConfigGuestHostdevMDEV()
        obj.parse_str(xmldoc)
        self.assertEqual(obj.mode, 'subsystem')
        self.assertEqual(obj.type, 'mdev')
        self.assertEqual(obj.managed, 'no')
        self.assertEqual(obj.model, 'vfio-pci')
        self.assertEqual(obj.uuid, 'b38a3f43-4be2-4046-897f-b67c2f5e0140')


class LibvirtConfigGuestCharDeviceLog(LibvirtConfigBaseTest):

    def test_config_log(self):
        obj = config.LibvirtConfigGuestCharDeviceLog()
        obj.file = "/tmp/guestname-logd.log"
        obj.append = "on"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <log file="/tmp/guestname-logd.log" append="on"/>""")

        # create a new object from the XML and check it again
        obj2 = config.LibvirtConfigGuestCharDeviceLog()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())


class LibvirtConfigGuestSerialTest(LibvirtConfigBaseTest):

    def test_config_file(self):
        obj = config.LibvirtConfigGuestSerial()
        obj.type = "file"
        obj.source_path = "/tmp/vm.log"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <serial type="file">
              <source path="/tmp/vm.log"/>
            </serial>""")

    def test_config_serial_port(self):
        obj = config.LibvirtConfigGuestSerial()
        obj.type = "tcp"
        obj.listen_port = 11111
        obj.listen_host = "0.0.0.0"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <serial type="tcp">
              <source host="0.0.0.0" service="11111" mode="bind"/>
            </serial>""")

    def test_config_log(self):
        log = config.LibvirtConfigGuestCharDeviceLog()
        log.file = "/tmp/guestname-logd.log"
        log.append = "off"

        device = config.LibvirtConfigGuestSerial()
        device.type = "tcp"
        device.listen_port = 11111
        device.listen_host = "0.0.0.0"
        device.log = log

        xml = device.to_xml()
        self.assertXmlEqual(xml, """
            <serial type="tcp">
              <source host="0.0.0.0" service="11111" mode="bind"/>
              <log file="/tmp/guestname-logd.log" append="off"/>
            </serial>""")


class LibvirtConfigGuestConsoleTest(LibvirtConfigBaseTest):
    def test_config_pty(self):
        obj = config.LibvirtConfigGuestConsole()
        obj.type = "pty"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <console type="pty"/>""")

    def test_config_target_type(self):
        obj = config.LibvirtConfigGuestConsole()
        obj.type = "pty"
        obj.target_type = "sclp"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <console type="pty">
                <target type="sclp"/>
            </console>
            """)

    def test_config_target_port(self):
        obj = config.LibvirtConfigGuestConsole()
        obj.target_port = 0

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <console type="pty">
                <target port="0"/>
            </console>
            """)

    def test_config_log(self):
        log = config.LibvirtConfigGuestCharDeviceLog()
        log.file = "/tmp/guestname-logd.log"
        log.append = "off"

        device = config.LibvirtConfigGuestConsole()
        device.type = "tcp"
        device.listen_port = 11111
        device.listen_host = "0.0.0.0"
        device.log = log

        xml = device.to_xml()
        self.assertXmlEqual(xml, """
            <console type="tcp">
              <source host="0.0.0.0" service="11111" mode="bind"/>
              <log file="/tmp/guestname-logd.log" append="off"/>
            </console>""")


class LibvirtConfigGuestChannelTest(LibvirtConfigBaseTest):
    def test_config_spice_minimal(self):
        obj = config.LibvirtConfigGuestChannel()
        obj.type = "spicevmc"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <channel type="spicevmc">
              <target type='virtio'/>
            </channel>""")

    def test_config_spice_full(self):
        obj = config.LibvirtConfigGuestChannel()
        obj.type = "spicevmc"
        obj.target_name = "com.redhat.spice.0"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <channel type="spicevmc">
              <target type='virtio' name='com.redhat.spice.0'/>
            </channel>""")

    def test_config_qga_full(self):
        obj = config.LibvirtConfigGuestChannel()
        obj.type = "unix"
        obj.target_name = "org.qemu.guest_agent.0"
        obj.source_path = "/var/lib/libvirt/qemu/%s.%s.sock" % (
                            obj.target_name, "instance-name")

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <channel type="unix">
              <source path="%s" mode="bind"/>
              <target type="virtio" name="org.qemu.guest_agent.0"/>
            </channel>""" % obj.source_path)


class LibvirtConfigGuestInterfaceTest(LibvirtConfigBaseTest):
    def test_config_ethernet(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "ethernet"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "vnet0"
        obj.driver_name = "vhost"
        obj.vif_inbound_average = 16384
        obj.vif_inbound_peak = 32768
        obj.vif_inbound_burst = 3276
        obj.vif_outbound_average = 32768
        obj.vif_outbound_peak = 65536
        obj.vif_outbound_burst = 6553

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="ethernet">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver name="vhost"/>
              <target dev="vnet0"/>
              <bandwidth>
                <inbound average="16384" peak="32768" burst="3276"/>
                <outbound average="32768" peak="65536" burst="6553"/>
              </bandwidth>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_ethernet_with_mtu(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "ethernet"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "vnet0"
        obj.driver_name = "vhost"
        obj.vif_inbound_average = 16384
        obj.vif_inbound_peak = 32768
        obj.vif_inbound_burst = 3276
        obj.vif_outbound_average = 32768
        obj.vif_outbound_peak = 65536
        obj.vif_outbound_burst = 6553
        obj.mtu = 9000

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="ethernet">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver name="vhost"/>
              <mtu size="9000"/>
              <target dev="vnet0"/>
              <bandwidth>
                <inbound average="16384" peak="32768" burst="3276"/>
                <outbound average="32768" peak="65536" burst="6553"/>
              </bandwidth>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def _get_virtio_interface(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "ethernet"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "vnet0"
        self.assertTrue(obj.uses_virtio)
        return obj

    def test_config_driver_packed_options(self):
        obj = self._get_virtio_interface()
        obj.driver_name = "vhost"
        obj.driver_packed = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="ethernet">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver name="vhost" packed="on"/>
              <target dev="vnet0"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_driver_options(self):
        obj = self._get_virtio_interface()
        obj.driver_name = "vhost"
        obj.vhost_queues = 4
        obj.driver_iommu = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="ethernet">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver name="vhost" queues="4" iommu="on"/>
              <target dev="vnet0"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_driver_iommu_option(self):
        obj = self._get_virtio_interface()
        # Check that the <driver> element is included even when there is
        # no driver name or queues
        obj.driver_iommu = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="ethernet">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver iommu="on"/>
              <target dev="vnet0"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_bridge(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "bridge"
        obj.source_dev = "br0"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "tap12345678"
        obj.filtername = "clean-traffic"
        obj.filterparams.append({"key": "IP", "value": "192.168.122.1"})
        obj.vif_inbound_average = 16384
        obj.vif_inbound_peak = 32768
        obj.vif_inbound_burst = 3276
        obj.vif_outbound_average = 32768
        obj.vif_outbound_peak = 65536
        obj.vif_outbound_burst = 6553

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="bridge">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source bridge="br0"/>
              <target dev="tap12345678"/>
              <filterref filter="clean-traffic">
                <parameter name="IP" value="192.168.122.1"/>
              </filterref>
              <bandwidth>
                <inbound average="16384" peak="32768" burst="3276"/>
                <outbound average="32768" peak="65536" burst="6553"/>
              </bandwidth>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_bridge_with_mtu(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "bridge"
        obj.source_dev = "br0"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "tap12345678"
        obj.filtername = "clean-traffic"
        obj.filterparams.append({"key": "IP", "value": "192.168.122.1"})
        obj.vif_inbound_average = 16384
        obj.vif_inbound_peak = 32768
        obj.vif_inbound_burst = 3276
        obj.vif_outbound_average = 32768
        obj.vif_outbound_peak = 65536
        obj.vif_outbound_burst = 6553
        obj.mtu = 9000

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="bridge">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source bridge="br0"/>
              <mtu size="9000"/>
              <target dev="tap12345678"/>
              <filterref filter="clean-traffic">
                <parameter name="IP" value="192.168.122.1"/>
              </filterref>
              <bandwidth>
                <inbound average="16384" peak="32768" burst="3276"/>
                <outbound average="32768" peak="65536" burst="6553"/>
              </bandwidth>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_bridge_ovs(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "bridge"
        obj.source_dev = "br0"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "tap12345678"
        obj.vporttype = "openvswitch"
        obj.vportparams.append({"key": "instanceid", "value": "foobar"})

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="bridge">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source bridge="br0"/>
              <target dev="tap12345678"/>
              <virtualport type="openvswitch">
                <parameters instanceid="foobar"/>
              </virtualport>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_bridge_ovs_with_mtu(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "bridge"
        obj.source_dev = "br0"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "tap12345678"
        obj.vporttype = "openvswitch"
        obj.vportparams.append({"key": "instanceid", "value": "foobar"})
        obj.mtu = 9000

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="bridge">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source bridge="br0"/>
              <mtu size="9000"/>
              <target dev="tap12345678"/>
              <virtualport type="openvswitch">
                <parameters instanceid="foobar"/>
              </virtualport>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_8021Qbh(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "direct"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.target_dev = "tap12345678"
        obj.source_dev = "eth0"
        obj.vporttype = "802.1Qbh"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="direct">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source dev="eth0" mode="private"/>
              <target dev="tap12345678"/>
              <virtualport type="802.1Qbh"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_direct(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "direct"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.model = "virtio"
        obj.source_dev = "eth0"
        obj.source_mode = "passthrough"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="direct">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source dev="eth0" mode="passthrough"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_8021Qbh_hostdev(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "hostdev"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.source_dev = "0000:0a:00.1"
        obj.vporttype = "802.1Qbh"
        obj.add_vport_param("profileid", "MyPortProfile")

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="hostdev" managed="yes">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <source>
                <address type="pci" domain="0x0000"
                   bus="0x0a" slot="0x00" function="0x1"/>
              </source>
              <virtualport type="802.1Qbh">
                <parameters profileid="MyPortProfile"/>
              </virtualport>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_hw_veb_hostdev(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "hostdev"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.source_dev = "0000:0a:00.1"
        obj.vlan = "100"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="hostdev" managed="yes">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <source>
                <address type="pci" domain="0x0000"
                   bus="0x0a" slot="0x00" function="0x1"/>
              </source>
              <vlan>
               <tag id="100"/>
              </vlan>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_vhostuser(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "vhostuser"
        obj.vhostuser_type = "unix"
        obj.vhostuser_mode = "server"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.vhostuser_path = "/vhost-user/test.sock"
        obj.model = "virtio"
        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="vhostuser">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source type="unix" mode="server" path="/vhost-user/test.sock"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_vhostuser_ensure_driver_never_set(self):
        obj = config.LibvirtConfigGuestInterface()
        # Even if 'driver_name' attribute is set we should never set
        # it in the domain XML for vhostuser interface.
        obj.driver_name = "vhost-user"

        obj.net_type = "vhostuser"
        obj.vhostuser_type = "unix"
        obj.vhostuser_mode = "server"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.vhostuser_path = "/vhost-user/test.sock"
        obj.model = "virtio"
        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="vhostuser">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <source type="unix" mode="server" path="/vhost-user/test.sock"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_vhostuser_queue_size(self):
        obj = config.LibvirtConfigGuestInterface()
        obj.net_type = "vhostuser"
        obj.vhostuser_type = "unix"
        obj.vhostuser_mode = "server"
        obj.mac_addr = "DE:AD:BE:EF:CA:FE"
        obj.vhostuser_path = "/vhost-user/test.sock"
        obj.vhost_rx_queue_size = 512
        obj.vhost_tx_queue_size = 1024
        obj.model = "virtio"
        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <interface type="vhostuser">
              <mac address="DE:AD:BE:EF:CA:FE"/>
              <model type="virtio"/>
              <driver rx_queue_size="512" tx_queue_size="1024"/>
              <source type="unix" mode="server" path="/vhost-user/test.sock"/>
            </interface>""")

        # parse the xml from the first object into a new object and make sure
        # they are the same
        obj2 = config.LibvirtConfigGuestInterface()
        obj2.parse_str(xml)
        self.assertXmlEqual(xml, obj2.to_xml())

    def test_config_interface_address(self):
        xml = """
            <interface type='network'>
              <mac address='52:54:00:f6:35:8f'/>
              <source network='default'/>
              <model type='virtio'/>
              <address type='pci' domain='0x0000' bus='0x00'
               slot='0x03' function='0x0'/>
            </interface>"""

        obj = config.LibvirtConfigGuestInterface()
        obj.parse_str(xml)

        self.assertIsInstance(obj.device_addr,
                              config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertEqual('0000:00:03.0', obj.device_addr.format_address())

    def test_config_interface_address_type_virtio_mmio(self):
        xml = """
            <interface type='network'>
              <mac address='fa:16:3e:d1:28:e4'/>
              <source network='default'/>
              <model type='virtio'/>
              <address type='virtio-mmio'/>
            </interface>"""

        obj = config.LibvirtConfigGuestInterface()
        obj.parse_str(xml)

        self.assertNotIsInstance(obj.device_addr,
                                 config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertNotIsInstance(obj.device_addr,
                             config.LibvirtConfigGuestDeviceAddressDrive)

    def test_config_interface_address_type_ccw(self):
        xml = """
            <interface type='network'>
                <mac address='52:54:00:14:6f:50'/>
                <source network='default' bridge='virbr0'/>
                <target dev='vnet0'/>
                <model type='virtio'/>
                <alias name='net0'/>
                <address type='ccw' cssid='0xfe' ssid='0x0' devno='0x0001'/>
            </interface>"""

        obj = config.LibvirtConfigGuestInterface()
        obj.parse_str(xml)

        self.assertNotIsInstance(obj.device_addr,
                                 config.LibvirtConfigGuestDeviceAddressPCI)
        self.assertNotIsInstance(obj.device_addr,
                             config.LibvirtConfigGuestDeviceAddressDrive)

    def test_config_interface_alias(self):
        xml = """
            <interface type='network'>
                <mac address='52:54:00:14:6f:50'/>
                <source network='default' bridge='virbr0'/>
                <target dev='vnet0'/>
                <model type='virtio'/>
                <alias name='net0'/>
            </interface>"""

        obj = config.LibvirtConfigGuestInterface()
        obj.parse_str(xml)

        self.assertEqual('net0', obj.alias)


class LibvirtConfigGuestFeatureTest(LibvirtConfigBaseTest):

    def test_feature_hyperv_relaxed(self):

        obj = config.LibvirtConfigGuestFeatureHyperV()
        obj.relaxed = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
          <hyperv>
            <relaxed state="on"/>
          </hyperv>""")

    def test_feature_hyperv_all(self):

        obj = config.LibvirtConfigGuestFeatureHyperV()
        obj.relaxed = True
        obj.vapic = True
        obj.spinlocks = True
        obj.vendorid_spoof = True
        obj.vpindex = True
        obj.runtime = True
        obj.synic = True
        obj.reset = True
        obj.frequencies = True
        obj.reenlightenment = True
        obj.tlbflush = True
        obj.ipi = True
        obj.evmcs = True

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
          <hyperv>
            <relaxed state="on"/>
            <vapic state="on"/>
            <spinlocks state="on" retries="4095"/>
            <vendor_id state="on" value="1234567890ab"/>
            <vpindex state='on'/>
            <runtime state='on'/>
            <synic state='on'/>
            <reset state='on'/>
            <frequencies state='on'/>
            <reenlightenment state='on'/>
            <tlbflush state='on'/>
            <ipi state='on'/>
            <evmcs state='on'/>
          </hyperv>""")

    def test_feature_pmu(self):
        # NOTE(sean-k-moonmey): LibvirtConfigGuestFeaturePMU uses
        # bool_from_string internally so assert that boolean and
        # string inputs work. This does not need to be exhaustive
        # as bool_from_string is tested in oslo so we just try
        # some common values.

        for val in ("true", "on", "1", "yes", True):
            obj = config.LibvirtConfigGuestFeaturePMU(val)
            xml = obj.to_xml()
            self.assertXmlEqual(xml, "<pmu state='on'/>")
        for val in ("false", "off", "0", "no", False):
            obj = config.LibvirtConfigGuestFeaturePMU(val)
            xml = obj.to_xml()
            self.assertXmlEqual(xml, "<pmu state='off'/>")

    def test_feature_ioapic(self):
        obj = config.LibvirtConfigGuestFeatureIOAPIC()
        obj.driver = "libvirt"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<ioapic driver='libvirt'/>")

    def test_feature_tcg(self):
        obj = config.LibvirtConfigGuestFeatureTCG(10)
        obj.driver = "libvirt"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, '<tcg><tb-cache unit="MiB">10'
                '</tb-cache></tcg>')


class LibvirtConfigGuestTest(LibvirtConfigBaseTest):

    def test_launch_security(self):
        # test that sev-specific bits are added to the xml

        obj = config.LibvirtConfigGuestSEVLaunchSecurity()
        obj.cbitpos = 47
        obj.reduced_phys_bits = 1

        xml = obj.to_xml()
        launch_security_expected = """
            <launchSecurity type="sev">
              <policy>0x0033</policy>
              <cbitpos>47</cbitpos>
              <reducedPhysBits>1</reducedPhysBits>
            </launchSecurity>"""

        self.assertXmlEqual(launch_security_expected, xml)

    def test_config_lxc(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "lxc"
        obj.memory = 100 * units.Mi
        obj.vcpus = 2
        obj.cpuset = set([0, 1, 3, 4, 5])
        obj.name = "demo"
        obj.uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0147"
        obj.os_type = "exe"
        obj.os_init_path = "/sbin/init"
        obj.os_init_env["foo"] = "bar"

        fs = config.LibvirtConfigGuestFilesys()
        fs.source_dir = "/root/lxc"
        fs.target_dir = "/"

        obj.add_device(fs)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <domain type="lxc">
              <uuid>b38a3f43-4be2-4046-897f-b67c2f5e0147</uuid>
              <name>demo</name>
              <memory>104857600</memory>
              <vcpu cpuset="0-1,3-5">2</vcpu>
              <os>
                <type>exe</type>
                <init>/sbin/init</init>
                <initenv name="foo">bar</initenv>
              </os>
              <devices>
                <filesystem type="mount">
                  <source dir="/root/lxc"/>
                  <target dir="/"/>
                </filesystem>
              </devices>
            </domain>""")

    def test_config_lxc_with_idmap(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "lxc"
        obj.memory = 100 * units.Mi
        obj.vcpus = 2
        obj.cpuset = set([0, 1, 3, 4, 5])
        obj.name = "demo"
        obj.uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0147"
        obj.os_type = "exe"
        obj.os_init_path = "/sbin/init"

        uidmap = config.LibvirtConfigGuestUIDMap()
        uidmap.target = "10000"
        uidmap.count = "1"
        obj.idmaps.append(uidmap)
        gidmap = config.LibvirtConfigGuestGIDMap()
        gidmap.target = "10000"
        gidmap.count = "1"
        obj.idmaps.append(gidmap)

        fs = config.LibvirtConfigGuestFilesys()
        fs.source_dir = "/root/lxc"
        fs.target_dir = "/"

        obj.add_device(fs)

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <domain type="lxc">
              <uuid>b38a3f43-4be2-4046-897f-b67c2f5e0147</uuid>
              <name>demo</name>
              <memory>104857600</memory>
              <vcpu cpuset="0-1,3-5">2</vcpu>
              <os>
                <type>exe</type>
                <init>/sbin/init</init>
              </os>
              <devices>
                <filesystem type="mount">
                  <source dir="/root/lxc"/>
                  <target dir="/"/>
                </filesystem>
              </devices>
              <idmap>
                <uid start="0" target="10000" count="1"/>
                <gid start="0" target="10000" count="1"/>
              </idmap>
            </domain>""", xml)

    def test_config_kvm(self):
        obj = fake_libvirt_data.fake_kvm_guest()

        launch_security = config.LibvirtConfigGuestSEVLaunchSecurity()
        launch_security.cbitpos = 47
        launch_security.reduced_phys_bits = 1
        obj.launch_security = launch_security

        xml = obj.to_xml()
        self.assertXmlEqual(fake_libvirt_data.FAKE_KVM_GUEST, xml)

    def test_config_uefi(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "kvm"
        obj.memory = 100 * units.Mi
        obj.vcpus = 1
        obj.name = "uefi"
        obj.uuid = "f01cf68d-515c-4daf-b85f-ef1424d93bfc"
        obj.os_type = "hvm"
        obj.os_mach_type = "pc-q35-5.1"
        obj.os_loader = '/tmp/OVMF_CODE.secboot.fd'
        obj.os_loader_type = 'pflash'
        obj.os_loader_secure = True
        xml = obj.to_xml()

        self.assertXmlEqual(
            """
            <domain type="kvm">
              <uuid>f01cf68d-515c-4daf-b85f-ef1424d93bfc</uuid>
              <name>uefi</name>
              <memory>104857600</memory>
              <vcpu>1</vcpu>
              <os>
                <type machine="pc-q35-5.1">hvm</type>
                <loader secure='yes' readonly='yes' type='pflash'>/tmp/OVMF_CODE.secboot.fd</loader>
              </os>
            </domain>""",  # noqa: E501
            xml,
        )

    def _test_config_uefi_autoconfigure(self, secure):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "kvm"
        obj.memory = 100 * units.Mi
        obj.vcpus = 1
        obj.name = "uefi"
        obj.uuid = "f01cf68d-515c-4daf-b85f-ef1424d93bfc"
        obj.os_type = "hvm"
        obj.os_firmware = "efi"
        obj.os_mach_type = "pc-q35-5.1"
        obj.os_loader_secure = secure
        return obj.to_xml()

    def test_config_uefi_autoconfigure(self):
        xml = self._test_config_uefi_autoconfigure(secure=False)

        self.assertXmlEqual(
            xml,
            """
            <domain type="kvm">
              <uuid>f01cf68d-515c-4daf-b85f-ef1424d93bfc</uuid>
              <name>uefi</name>
              <memory>104857600</memory>
              <vcpu>1</vcpu>
              <os firmware="efi">
                <type machine="pc-q35-5.1">hvm</type>
                <loader secure="no"/>
              </os>
            </domain>""",
        )

    def test_config_uefi_autoconfigure_secure(self):
        xml = self._test_config_uefi_autoconfigure(secure=True)

        self.assertXmlEqual(
            xml,
            """
            <domain type="kvm">
              <uuid>f01cf68d-515c-4daf-b85f-ef1424d93bfc</uuid>
              <name>uefi</name>
              <memory>104857600</memory>
              <vcpu>1</vcpu>
              <os firmware="efi">
                <type machine="pc-q35-5.1">hvm</type>
                <loader secure="yes"/>
              </os>
            </domain>""",
        )

    def test_config_boot_menu(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "kvm"
        obj.memory = 100 * units.Mi
        obj.vcpus = 2
        obj.name = "bootmenu"
        obj.uuid = "f01cf68d-515c-4daf-b85f-ef1424d93bfc"
        obj.os_type = "hvm"
        obj.os_bootmenu = True
        xml = obj.to_xml()

        self.assertXmlEqual(xml, """
            <domain type="kvm">
              <uuid>f01cf68d-515c-4daf-b85f-ef1424d93bfc</uuid>
              <name>bootmenu</name>
              <memory>104857600</memory>
              <vcpu>2</vcpu>
              <os>
                <type>hvm</type>
                <bootmenu enable="yes"/>
              </os>
            </domain>""")

    def test_config_perf(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "kvm"
        obj.memory = 100 * units.Mi
        obj.vcpus = 2
        obj.name = "perf"
        obj.uuid = "f01cf68d-515c-4daf-b85f-ef1424d93bfc"
        obj.os_type = "hvm"
        obj.perf_events = ['cmt', 'mbml']
        xml = obj.to_xml()

        self.assertXmlEqual(xml, """
            <domain type="kvm">
              <uuid>f01cf68d-515c-4daf-b85f-ef1424d93bfc</uuid>
              <name>perf</name>
              <memory>104857600</memory>
              <vcpu>2</vcpu>
              <os>
                <type>hvm</type>
              </os>
              <perf>
                <event enabled="yes" name="cmt"/>
                <event enabled="yes" name="mbml"/>
              </perf>
            </domain>""")

    def test_config_machine_type(self):
        obj = config.LibvirtConfigGuest()
        obj.virt_type = "kvm"
        obj.memory = 100 * units.Mi
        obj.vcpus = 2
        obj.name = "demo"
        obj.uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0147"
        obj.os_type = "hvm"
        obj.os_mach_type = "fake_machine_type"
        xml = obj.to_xml()

        self.assertXmlEqual(xml, """
            <domain type="kvm">
              <uuid>b38a3f43-4be2-4046-897f-b67c2f5e0147</uuid>
              <name>demo</name>
              <memory>104857600</memory>
              <vcpu>2</vcpu>
              <os>
                <type machine="fake_machine_type">hvm</type>
              </os>
            </domain>""")

    def test_ConfigGuest_parse_devices(self):
        xmldoc = """ <domain type="kvm">
                      <devices>
                        <hostdev mode="subsystem" type="pci" managed="no">
                        </hostdev>
                        <filesystem type="mount">
                        </filesystem>
                      </devices>
                     </domain>
                 """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)
        self.assertEqual('kvm', obj.virt_type)
        self.assertEqual(len(obj.devices), 2)
        self.assertIsInstance(obj.devices[0],
                              config.LibvirtConfigGuestHostdevPCI)
        self.assertEqual(obj.devices[0].mode, 'subsystem')
        self.assertEqual(obj.devices[0].managed, 'no')
        self.assertIsInstance(obj.devices[1],
                              config.LibvirtConfigGuestFilesys)
        self.assertEqual('mount', obj.devices[1].source_type)

    def test_ConfigGuest_parse_devices_wrong_type(self):
        xmldoc = """ <domain type="kvm">
                      <devices>
                        <hostdev mode="subsystem" type="xxxx" managed="no">
                        </hostdev>
                      </devices>
                     </domain>
                 """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)
        self.assertEqual(len(obj.devices), 0)

    def test_ConfigGuest_parse_cpu(self):
        xmldoc = """ <domain>
                       <cpu mode='custom' match='exact'>
                         <model>kvm64</model>
                       </cpu>
                     </domain>
                """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertEqual(obj.cpu.mode, 'custom')
        self.assertEqual(obj.cpu.match, 'exact')
        self.assertEqual(obj.cpu.model, 'kvm64')

    def test_ConfigGuest_parse_perf(self):
        xmldoc = """ <domain>
             <perf>
               <event enabled="yes" name="cmt"/>
               <event enabled="no" name="mbml"/>
             </perf>
                    </domain>
               """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertEqual(['cmt'], obj.perf_events)

    def test_ConfigGuest_parse_os(self):
        xmldoc = """
          <domain type="kvm">
            <os>
              <type machine="fake_machine_type">hvm</type>
              <kernel>/tmp/vmlinuz</kernel>
              <loader>/usr/lib/xen/boot/hvmloader</loader>
              <initrd>/tmp/ramdisk</initrd>
              <cmdline>console=xvc0</cmdline>
              <root>root=xvda</root>
              <init>/sbin/init</init>
              <boot dev="hd"/>
              <boot dev="cdrom"/>
              <boot dev="fd"/>
              <bootmenu enable="yes"/>
              <smbios mode="sysinfo"/>
              <initenv name="foo">bar</initenv>
            </os>
          </domain>
        """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertEqual('kvm', obj.virt_type)
        self.assertEqual('hvm', obj.os_type)
        self.assertEqual('fake_machine_type', obj.os_mach_type)
        self.assertEqual('/tmp/vmlinuz', obj.os_kernel)
        self.assertEqual('/usr/lib/xen/boot/hvmloader', obj.os_loader)
        self.assertIsNone(obj.os_loader_type)
        self.assertEqual('/tmp/ramdisk', obj.os_initrd)
        self.assertEqual('console=xvc0', obj.os_cmdline)
        self.assertEqual('root=xvda', obj.os_root)
        self.assertEqual('/sbin/init', obj.os_init_path)
        self.assertEqual('bar', obj.os_init_env['foo'])
        self.assertEqual(['hd', 'cdrom', 'fd'], obj.os_boot_dev)
        self.assertTrue(obj.os_bootmenu)
        self.assertIsNone(obj.os_smbios)

        xmldoc = """
          <domain>
            <os>
              <type>hvm</type>
              <loader readonly='yes' type='pflash'>/tmp/OVMF_CODE.fd</loader>
            </os>
          </domain>
        """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertIsNone(obj.virt_type)
        self.assertEqual('hvm', obj.os_type)
        self.assertIsNone(obj.os_mach_type)
        self.assertIsNone(obj.os_kernel)
        self.assertEqual('/tmp/OVMF_CODE.fd', obj.os_loader)
        self.assertEqual('pflash', obj.os_loader_type)
        self.assertIsNone(obj.os_initrd)
        self.assertIsNone(obj.os_cmdline)
        self.assertIsNone(obj.os_root)
        self.assertIsNone(obj.os_init_path)
        self.assertEqual([], obj.os_boot_dev)
        self.assertFalse(obj.os_bootmenu)
        self.assertIsNone(obj.os_smbios)

    def test_ConfigGuest_parse_basic_props(self):
        xmldoc = """
          <domain>
            <uuid>b38a3f43-4be2-4046-897f-b67c2f5e0147</uuid>
            <name>demo</name>
            <memory>104857600</memory>
            <vcpu cpuset="0-1,3-5">2</vcpu>
          </domain>
        """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertEqual('b38a3f43-4be2-4046-897f-b67c2f5e0147', obj.uuid)
        self.assertEqual('demo', obj.name)
        self.assertEqual(100 * units.Mi, obj.memory)
        self.assertEqual(2, obj.vcpus)
        self.assertEqual(set([0, 1, 3, 4, 5]), obj.cpuset)

        xmldoc = """
          <domain>
            <vcpu>3</vcpu>
          </domain>
        """
        obj = config.LibvirtConfigGuest()
        obj.parse_str(xmldoc)

        self.assertIsNone(obj.uuid)
        self.assertIsNone(obj.name)
        self.assertEqual(500 * units.Mi, obj.memory)  # default value
        self.assertEqual(3, obj.vcpus)
        self.assertIsNone(obj.cpuset)


class LibvirtConfigGuestSnapshotTest(LibvirtConfigBaseTest):

    def test_config_snapshot(self):
        obj = config.LibvirtConfigGuestSnapshot()
        obj.name = "Demo"

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <domainsnapshot>
              <name>Demo</name>
              <disks/>
            </domainsnapshot>""")

    def test_config_snapshot_with_disks(self):
        obj = config.LibvirtConfigGuestSnapshot()
        obj.name = "Demo"

        disk = config.LibvirtConfigGuestSnapshotDisk()
        disk.name = 'vda'
        disk.source_path = 'source-path'
        disk.source_type = 'file'
        disk.snapshot = 'external'
        disk.driver_name = 'qcow2'
        obj.add_disk(disk)

        disk2 = config.LibvirtConfigGuestSnapshotDisk()
        disk2.name = 'vdb'
        disk2.snapshot = 'no'
        obj.add_disk(disk2)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <domainsnapshot>
              <name>Demo</name>
              <disks>
               <disk name='vda' snapshot='external' type='file'>
                <source file='source-path'/>
               </disk>
               <disk name='vdb' snapshot='no'/>
              </disks>
            </domainsnapshot>""")

    def test_config_snapshot_with_network_disks(self):
        obj = config.LibvirtConfigGuestSnapshot()
        obj.name = "Demo"

        disk = config.LibvirtConfigGuestSnapshotDisk()
        disk.name = 'vda'
        disk.source_name = 'source-file'
        disk.source_type = 'network'
        disk.source_hosts = ['host1']
        disk.source_ports = ['12345']
        disk.source_protocol = 'netfs'
        disk.snapshot = 'external'
        disk.driver_name = 'qcow2'
        obj.add_disk(disk)

        disk2 = config.LibvirtConfigGuestSnapshotDisk()
        disk2.name = 'vdb'
        disk2.snapshot = 'no'
        obj.add_disk(disk2)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <domainsnapshot>
              <name>Demo</name>
              <disks>
               <disk name='vda' snapshot='external' type='network'>
                <source protocol='netfs' name='source-file'>
                 <host name='host1' port='12345'/>
                </source>
               </disk>
               <disk name='vdb' snapshot='no'/>
              </disks>
            </domainsnapshot>""")

    def test_config_file_iommu(self):
        obj = config.LibvirtConfigGuestDisk()
        obj.driver_iommu = True
        obj.source_type = "file"
        obj.source_path = "/tmp/hello.qcow2"
        obj.target_dev = "/dev/sda"
        obj.target_bus = "virtio"
        obj.serial = "7a97c4a3-6f59-41d4-bf47-191d7f97f8e9"

        self.assertTrue(obj.uses_virtio)

        xml = obj.to_xml()
        self.assertXmlEqual("""
            <disk type="file" device="disk">
              <driver iommu="on"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="virtio" dev="/dev/sda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>""", xml)

    def test_config_file_iommu_parse(self):
        xml = """
            <disk type="file" device="disk">
              <driver iommu="on"/>
              <source file="/tmp/hello.qcow2"/>
              <target bus="virtio" dev="/dev/sda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
            </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertTrue(obj.driver_iommu)

    def test_config_alias_parse(self):
        xml = """
            <disk type="file" device="disk">
              <source file="/tmp/hello.qcow2"/>
              <target bus="virtio" dev="/dev/sda"/>
              <serial>7a97c4a3-6f59-41d4-bf47-191d7f97f8e9</serial>
               <alias name='virtio-disk0'/>
            </disk>"""
        xmldoc = etree.fromstring(xml)

        obj = config.LibvirtConfigGuestDisk()
        obj.parse_dom(xmldoc)

        self.assertEqual('virtio-disk0', obj.alias)


class LibvirtConfigNodeDeviceTest(LibvirtConfigBaseTest):

    def test_config_virt_usb_device(self):
        xmlin = """
        <device>
          <name>usb_0000_09_00_0</name>
          <parent>pci_0000_00_1c_0</parent>
          <driver>
          <name>vxge</name>
          </driver>
          <capability type="usb">
            <domain>0</domain>
             <capability type="fake_usb">
             <address fake_usb="fake"/>
            </capability>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsNone(obj.pci_capability)

    def test_config_virt_device(self):
        xmlin = """
        <device>
          <name>pci_0000_09_00_0</name>
          <parent>pci_0000_00_1c_0</parent>
          <driver>
          <name>vxge</name>
          </driver>
          <capability type="pci">
            <domain>0</domain>
            <bus>9</bus>
            <slot>0</slot>
            <function>0</function>
        <product id="0x5833">X3100 Series 10 Gigabit Ethernet PCIe</product>
            <vendor id="0x17d5">Neterion Inc.</vendor>
            <capability type="virt_functions">
             <address domain="0x0000" bus="0x0a" slot="0x00" function="0x1"/>
             <address domain="0x0000" bus="0x0a" slot="0x00" function="0x2"/>
             <address domain="0x0000" bus="0x0a" slot="0x00" function="0x3"/>
            </capability>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertIsInstance(obj.pci_capability.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)
        self.assertEqual(obj.pci_capability.fun_capability[0].type,
                          "virt_functions")
        self.assertEqual(len(obj.pci_capability.fun_capability[0].
                             device_addrs),
                          3)
        self.assertEqual(obj.pci_capability.bus, 9)

    def test_config_phy_device(self):
        xmlin = """
        <device>
          <name>pci_0000_33_00_0</name>
          <parent>pci_0000_22_1c_0</parent>
          <driver>
          <name>vxx</name>
          </driver>
          <capability type="pci">
            <domain>0</domain>
            <bus>9</bus>
            <slot>0</slot>
            <function>0</function>
           <product id="0x5833">X3100 Series 10 Gigabit Ethernet PCIe</product>
            <vendor id="0x17d5">Neterion Inc.</vendor>
            <capability type="phys_function">
            <address domain='0x0000' bus='0x09' slot='0x00' function='0x0'/>
            </capability>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertIsInstance(obj.pci_capability.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)
        self.assertEqual(obj.pci_capability.fun_capability[0].type,
                          "phys_function")
        self.assertEqual(len(obj.pci_capability.fun_capability[0].
                             device_addrs),
                         1)

    def test_config_non_device(self):
        xmlin = """
        <device>
          <name>pci_0000_33_00_0</name>
          <parent>pci_0000_22_1c_0</parent>
          <driver>
          <name>vxx</name>
          </driver>
          <capability type="pci">
            <domain>0</domain>
            <bus>9</bus>
            <slot>0</slot>
            <function>0</function>
          <product id="0x5833">X3100 Series 10 Gigabit Ethernet PCIe</product>
             <vendor id="0x17d5">Neterion Inc.</vendor>
             <capability type="virt_functions"/>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertIsInstance(obj.pci_capability.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)
        self.assertEqual(obj.pci_capability.fun_capability[0].type,
                          "virt_functions")

    def test_config_fail_device(self):
        xmlin = """
        <device>
          <name>pci_0000_33_00_0</name>
          <parent>pci_0000_22_1c_0</parent>
          <driver>
          <name>vxx</name>
          </driver>
          <capability type="pci">
            <domain>0</domain>
            <bus>9</bus>
            <slot>0</slot>
            <function>0</function>
         <product id="0x5833">X3100 Series 10 Gigabit Ethernet PCIe</product>
            <vendor id="0x17d5">Neterion Inc.</vendor>
            <capability type="virt_functions">
            </capability>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertIsInstance(obj.pci_capability.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)
        self.assertEqual(obj.pci_capability.fun_capability[0].type,
                          "virt_functions")

    def test_config_2cap_device(self):
        xmlin = """
        <device>
          <name>pci_0000_04_10_7</name>
          <parent>pci_0000_00_01_1</parent>
          <driver>
            <name>igbvf</name>
          </driver>
          <capability type='pci'>
            <domain>0</domain>
            <bus>4</bus>
            <slot>16</slot>
            <function>7</function>
            <product id='0x1520'>I350 Ethernet Controller Virtual</product>
            <vendor id='0x8086'>Intel Corporation</vendor>
            <capability type='phys_function'>
              <address domain='0x0000' bus='0x04' slot='0x00' function='0x3'/>
            </capability>
            <capability type='virt_functions'>
              <address domain='0x0000' bus='0x04' slot='0x00' function='0x3'/>
            </capability>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertIsInstance(obj.pci_capability.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)
        self.assertEqual(obj.pci_capability.fun_capability[0].type,
                          "phys_function")
        self.assertEqual(obj.pci_capability.fun_capability[1].type,
                          "virt_functions")

    def test_config_net_device(self):
        xmlin = """
        <device>
          <name>net_enp2s2_02_9a_a1_37_be_54</name>
          <path>/sys/devices/pci0000:00/0000:00:02.0/net/enp2s2</path>
          <parent>pci_0000_00_02_0</parent>
          <capability type='net'>
            <interface>enp2s2</interface>
            <address>02:9a:a1:37:be:54</address>
            <link state='down'/>
            <feature name='rx'/>
            <feature name='tx'/>
            <feature name='sg'/>
            <feature name='tso'/>
            <feature name='gso'/>
            <feature name='gro'/>
            <feature name='rxvlan'/>
            <feature name='txvlan'/>
            <capability type='80203'/>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)

        self.assertIsInstance(obj.pci_capability,
                              config.LibvirtConfigNodeDevicePciCap)
        self.assertEqual(obj.pci_capability.interface, "enp2s2")
        self.assertEqual(obj.pci_capability.address, "02:9a:a1:37:be:54")
        self.assertEqual(obj.pci_capability.link_state, "down")
        self.assertEqual(obj.pci_capability.features,
                         ['rx', 'tx', 'sg', 'tso', 'gso', 'gro', 'rxvlan',
                          'txvlan'])

    def test_config_mdev_device(self):
        xmlin = """
        <device>
          <name>mdev_4b20d080_1b54_4048_85b3_a6a62d165c01</name>
          <parent>pci_0000_06_00_0</parent>
          <capability type='mdev'>
            <type id='nvidia-11'/>
            <iommuGroup number='12'/>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)
        self.assertIsInstance(obj.mdev_information,
                              config.LibvirtConfigNodeDeviceMdevInformation)
        self.assertEqual("nvidia-11", obj.mdev_information.type)
        self.assertEqual(12, obj.mdev_information.iommu_group)
        self.assertIsNone(obj.mdev_information.uuid)

    def test_config_mdev_device_uuid(self):
        xmlin = """
        <device>
          <name>mdev_b2107403_110c_45b0_af87_32cc91597b8a_0000_41_00_0</name>
          <path>/sys/devices/pci0000:40/0000:40:03.1/0000:41:00.0/b2107403-110c-45b0-af87-32cc91597b8a</path>
          <parent>pci_0000_41_00_0</parent>
          <driver>
            <name>vfio_mdev</name>
          </driver>
          <capability type='mdev'>
            <type id='nvidia-442'/>
            <uuid>b2107403-110c-45b0-af87-32cc91597b8a</uuid>
            <iommuGroup number='57'/>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)
        self.assertIsInstance(obj.mdev_information,
                              config.LibvirtConfigNodeDeviceMdevInformation)
        self.assertEqual("nvidia-442", obj.mdev_information.type)
        self.assertEqual(57, obj.mdev_information.iommu_group)
        self.assertEqual("b2107403-110c-45b0-af87-32cc91597b8a",
                         obj.mdev_information.uuid)

    def test_config_vdpa_device(self):
        xmlin = """
        <device>
          <name>vdpa_vdpa0</name>
          <path>/sys/devices/pci0000:00/0000:00:02.2/0000:06:00.2/vdpa0</path>
          <parent>pci_0000_06_00_2</parent>
          <driver>
            <name>vhost_vdpa</name>
          </driver>
          <capability type='vdpa'>
            <chardev>/dev/vhost-vdpa-0</chardev>
          </capability>
        </device>"""

        obj = config.LibvirtConfigNodeDevice()
        obj.parse_str(xmlin)
        self.assertIsInstance(
            obj.vdpa_capability, config.LibvirtConfigNodeDeviceVDPACap)
        self.assertEqual("/dev/vhost-vdpa-0", obj.vdpa_capability.dev_path)


class LibvirtConfigNodeDevicePciCapTest(LibvirtConfigBaseTest):

    def test_config_device_pci_cap(self):
        xmlin = """
            <capability type="pci">
              <domain>0</domain>
              <bus>10</bus>
              <slot>1</slot>
              <function>5</function>
              <product id="0x10bd">Intel 10 Gigabit Ethernet</product>
              <vendor id="0x8086">Intel Inc.</vendor>
              <capability type="virt_functions">
               <address domain="0000" bus="0x0a" slot="0x1" function="0x1"/>
               <address domain="0001" bus="0x0a" slot="0x02" function="0x03"/>
              </capability>
            </capability>"""
        obj = config.LibvirtConfigNodeDevicePciCap()
        obj.parse_str(xmlin)

        self.assertEqual(obj.domain, 0)
        self.assertEqual(obj.bus, 10)
        self.assertEqual(obj.slot, 1)
        self.assertEqual(obj.function, 5)
        self.assertEqual(obj.product, "Intel 10 Gigabit Ethernet")
        self.assertEqual(obj.product_id, 0x10bd)
        self.assertEqual(obj.vendor, "Intel Inc.")
        self.assertEqual(obj.vendor_id, 0x8086)
        self.assertIsNone(obj.numa_node)
        self.assertIsInstance(obj.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)

        self.assertEqual(obj.fun_capability[0].type, 'virt_functions')
        self.assertEqual(obj.fun_capability[0].device_addrs,
                         [(0, 10, 1, 1),
                          (1, 10, 2, 3), ])

    def test_config_device_pci_2cap(self):
        xmlin = """
            <capability type="pci">
              <domain>0</domain>
              <bus>10</bus>
              <slot>1</slot>
              <function>5</function>
              <product id="0x10bd">Intel 10 Gigabit Ethernet</product>
              <vendor id="0x8086">Intel Inc.</vendor>
              <numa node='0'/>
              <capability type="virt_functions">
               <address domain="0000" bus="0x0a" slot="0x1" function="0x1"/>
               <address domain="0001" bus="0x0a" slot="0x02" function="0x03"/>
              </capability>
              <capability type="phys_function">
               <address domain="0000" bus="0x0a" slot="0x1" function="0x1"/>
              </capability>
            </capability>"""
        obj = config.LibvirtConfigNodeDevicePciCap()
        obj.parse_str(xmlin)

        self.assertEqual(obj.domain, 0)
        self.assertEqual(obj.bus, 10)
        self.assertEqual(obj.slot, 1)
        self.assertEqual(obj.function, 5)
        self.assertEqual(obj.product, "Intel 10 Gigabit Ethernet")
        self.assertEqual(obj.product_id, 0x10bd)
        self.assertEqual(obj.vendor, "Intel Inc.")
        self.assertEqual(obj.vendor_id, 0x8086)
        self.assertEqual(0, obj.numa_node)
        self.assertIsInstance(obj.fun_capability[0],
                              config.LibvirtConfigNodeDevicePciSubFunctionCap)

        self.assertEqual(obj.fun_capability[0].type, 'virt_functions')
        self.assertEqual(obj.fun_capability[0].device_addrs,
                         [(0, 10, 1, 1),
                          (1, 10, 2, 3), ])
        self.assertEqual(obj.fun_capability[1].type, 'phys_function')
        self.assertEqual(obj.fun_capability[1].device_addrs,
                         [(0, 10, 1, 1), ])

    def test_config_device_pci_mdev_capable(self):
        xmlin = """
            <capability type="pci">
              <domain>0</domain>
              <bus>10</bus>
              <slot>1</slot>
              <function>5</function>
              <product id="0x0FFE">GRID M60-0B</product>
              <vendor id="0x10DE">Nvidia</vendor>
              <capability type='mdev_types'>
                <type id='nvidia-11'>
                  <name>GRID M60-0B</name>
                  <deviceAPI>vfio-pci</deviceAPI>
                  <availableInstances>16</availableInstances>
                </type>
              </capability>
            </capability>"""
        obj = config.LibvirtConfigNodeDevicePciCap()
        obj.parse_str(xmlin)

        self.assertEqual(0, obj.domain)
        self.assertEqual(10, obj.bus)
        self.assertEqual(1, obj.slot)
        self.assertEqual(5, obj.function)
        self.assertEqual("GRID M60-0B", obj.product)
        self.assertEqual(0x0FFE, obj.product_id)
        self.assertEqual("Nvidia", obj.vendor)
        self.assertEqual(0x10DE, obj.vendor_id)
        self.assertIsNone(obj.numa_node)
        self.assertIsInstance(
            obj.mdev_capability[0],
            config.LibvirtConfigNodeDeviceMdevCapableSubFunctionCap)

        self.assertEqual([{
            'availableInstances': 16,
            'deviceAPI': 'vfio-pci',
            'name': 'GRID M60-0B',
            'type': 'nvidia-11'}], obj.mdev_capability[0].mdev_types)

    def test_config_device_pci_vpd(self):
        xmlin = """
    <capability type='pci'>
      <class>0x020000</class>
      <domain>0</domain>
      <bus>130</bus>
      <slot>0</slot>
      <function>1</function>
      <product id='0xa2d6'>MT42822 BlueField-2</product>
      <vendor id='0x15b3'>Mellanox Technologies</vendor>
      <capability type='virt_functions' maxCount='16'/>
      <capability type='vpd'>
        <name>BlueField-2 DPU 25GbE</name>
        <fields access='readonly'>
          <change_level>B1</change_level>
          <manufacture_id>foobar</manufacture_id>
          <part_number>MBF2H332A-AEEOT</part_number>
          <serial_number>MT2113X00000</serial_number>
          <vendor_field index='0'>PCIeGen4 x8</vendor_field>
          <vendor_field index='2'>MBF2H332A-AEEOT</vendor_field>
          <vendor_field index='3'>3c53d07eec484d8aab34dabd24fe575aa</vendor_field>
          <vendor_field index='A'>MLX:MN=MLNX:CSKU=V2:UUID=V3:PCI=V0:MODL=BF2H332A</vendor_field>
        </fields>
        <fields access='readwrite'>
          <asset_tag>fooasset</asset_tag>
          <vendor_field index='0'>vendorfield0</vendor_field>
          <vendor_field index='2'>vendorfield2</vendor_field>
          <vendor_field index='A'>vendorfieldA</vendor_field>
          <system_field index='B'>systemfieldB</system_field>
          <system_field index='0'>systemfield0</system_field>
        </fields>
      </capability>
      <iommuGroup number='66'>
        <address domain='0x0000' bus='0x82' slot='0x00' function='0x1'/>
      </iommuGroup>
      <numa node='1'/>
      <pci-express>
        <link validity='cap' port='0' speed='16' width='8'/>
        <link validity='sta' speed='8' width='8'/>
      </pci-express>
    </capability>"""  # noqa: E501
        obj = config.LibvirtConfigNodeDevicePciCap()
        obj.parse_str(xmlin)

        # Asserting common PCI attribute parsing.
        self.assertEqual(0, obj.domain)
        self.assertEqual(130, obj.bus)
        self.assertEqual(0, obj.slot)
        self.assertEqual(1, obj.function)
        # Asserting vpd capability parsing.
        self.assertEqual("MT42822 BlueField-2", obj.product)
        self.assertEqual(0xA2D6, obj.product_id)
        self.assertEqual("Mellanox Technologies", obj.vendor)
        self.assertEqual(0x15B3, obj.vendor_id)
        self.assertEqual(obj.numa_node, 1)
        self.assertIsInstance(obj.vpd_capability,
                              config.LibvirtConfigNodeDeviceVpdCap)
        self.assertEqual(obj.vpd_capability.card_name, 'BlueField-2 DPU 25GbE')

        self.assertEqual(obj.vpd_capability.change_level, 'B1')
        self.assertEqual(obj.vpd_capability.manufacture_id, 'foobar')
        self.assertEqual(obj.vpd_capability.part_number, 'MBF2H332A-AEEOT')
        self.assertEqual(obj.vpd_capability.card_serial_number, 'MT2113X00000')
        self.assertEqual(obj.vpd_capability.asset_tag, 'fooasset')
        self.assertEqual(obj.vpd_capability.ro_vendor_fields, {
            '0': 'PCIeGen4 x8',
            '2': 'MBF2H332A-AEEOT',
            '3': '3c53d07eec484d8aab34dabd24fe575aa',
            'A': 'MLX:MN=MLNX:CSKU=V2:UUID=V3:PCI=V0:MODL=BF2H332A',
        })
        self.assertEqual(obj.vpd_capability.rw_vendor_fields, {
            '0': 'vendorfield0',
            '2': 'vendorfield2',
            'A': 'vendorfieldA',
        })
        self.assertEqual(obj.vpd_capability.rw_system_fields, {
            '0': 'systemfield0',
            'B': 'systemfieldB',
        })


class LibvirtConfigNodeDevicePciSubFunctionCap(LibvirtConfigBaseTest):

    def test_config_device_pci_subfunction(self):
        xmlin = """
        <capability type="virt_functions">
            <address domain="0000" bus="0x0a" slot="0x1" function="0x1"/>
            <address domain="0001" bus="0x0a" slot="0x02" function="0x03"/>
        </capability>"""
        fun_capability = config.LibvirtConfigNodeDevicePciSubFunctionCap()
        fun_capability.parse_str(xmlin)
        self.assertEqual('virt_functions', fun_capability.type)
        self.assertEqual([(0, 10, 1, 1),
                          (1, 10, 2, 3)],
                         fun_capability.device_addrs)


class LibvirtConfigGuestVideoTest(LibvirtConfigBaseTest):

    def test_config_video_driver(self):
        obj = config.LibvirtConfigGuestVideo()
        obj.type = 'qxl'

        self.assertFalse(obj.uses_virtio)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
                <video>
                    <model type='qxl'/>
                </video>""")

    def test_config_video_driver_virtio(self):
        obj = config.LibvirtConfigGuestVideo()
        obj.type = 'virtio'

        self.assertTrue(obj.uses_virtio)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
                <video>
                    <model type='virtio'/>
                </video>""")

    def test_config_video_driver_vram_heads(self):
        obj = config.LibvirtConfigGuestVideo()
        obj.type = 'qxl'
        obj.vram = '9216'
        obj.heads = '1'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
                <video>
                    <model type='qxl' vram='9216' heads='1'/>
                </video>""")


class LibvirtConfigGuestSeclabel(LibvirtConfigBaseTest):

    def test_config_seclabel_config(self):
        obj = config.LibvirtConfigSeclabel()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
              <seclabel type='dynamic'/>""")

    def test_config_seclabel_baselabel(self):
        obj = config.LibvirtConfigSeclabel()
        obj.type = 'dynamic'
        obj.baselabel = 'system_u:system_r:my_svirt_t:s0'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
              <seclabel type='dynamic'>
                <baselabel>system_u:system_r:my_svirt_t:s0</baselabel>
              </seclabel>""")


class LibvirtConfigGuestRngTest(LibvirtConfigBaseTest):

    def test_config_rng_driver(self):
        obj = config.LibvirtConfigGuestRng()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
<rng model='virtio'>
    <backend model='random'/>
</rng>""")

    def test_config_rng_driver_with_rate(self):
        obj = config.LibvirtConfigGuestRng()
        obj.backend = '/dev/urandom'
        obj.rate_period = '12'
        obj.rate_bytes = '34'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
<rng model='virtio'>
    <rate period='12' bytes='34'/>
    <backend model='random'>/dev/urandom</backend>
</rng>""")

    def test_config_rng_driver_iommu(self):
        obj = config.LibvirtConfigGuestRng()
        obj.driver_iommu = True

        self.assertTrue(obj.uses_virtio)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <rng model='virtio'>
                <backend model='random'/>
                <driver iommu="on"/>
            </rng>""")


class LibvirtConfigGuestControllerTest(LibvirtConfigBaseTest):

    def test_config_guest_contoller(self):
        obj = config.LibvirtConfigGuestController()
        obj.type = 'scsi'
        obj.index = 0
        obj.model = 'virtio-scsi'
        obj.driver_iommu = True

        self.assertTrue(obj.uses_virtio)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <controller type='scsi' index='0' model='virtio-scsi'>
              <driver iommu="on" />
            </controller>""")

    def test_config_guest_usb_host_controller(self):
        obj = config.LibvirtConfigGuestUSBHostController()
        obj.type = 'usb'
        obj.index = 0

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<controller type='usb' index='0'/>")


class LibvirtConfigGuestWatchdogTest(LibvirtConfigBaseTest):
    def test_config_watchdog(self):
        obj = config.LibvirtConfigGuestWatchdog()
        obj.action = 'none'

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<watchdog model='i6300esb' action='none'/>")

    def test_config_watchdog_default_action(self):
        obj = config.LibvirtConfigGuestWatchdog()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<watchdog model='i6300esb' action='reset'/>")


class LibvirtConfigGuestCPUTuneTest(LibvirtConfigBaseTest):

    def test_config_cputune_timeslice(self):
        cputune = config.LibvirtConfigGuestCPUTune()
        cputune.shares = 100
        cputune.quota = 50000
        cputune.period = 25000

        xml = cputune.to_xml()
        self.assertXmlEqual(xml, """
          <cputune>
            <shares>100</shares>
            <quota>50000</quota>
            <period>25000</period>
          </cputune>""")

    def test_config_cputune_vcpus(self):
        cputune = config.LibvirtConfigGuestCPUTune()

        vcpu0 = config.LibvirtConfigGuestCPUTuneVCPUPin()
        vcpu0.id = 0
        vcpu0.cpuset = set([0, 1])
        vcpu1 = config.LibvirtConfigGuestCPUTuneVCPUPin()
        vcpu1.id = 1
        vcpu1.cpuset = set([2, 3])
        vcpu2 = config.LibvirtConfigGuestCPUTuneVCPUPin()
        vcpu2.id = 2
        vcpu2.cpuset = set([4, 5])
        vcpu3 = config.LibvirtConfigGuestCPUTuneVCPUPin()
        vcpu3.id = 3
        vcpu3.cpuset = set([6, 7])
        cputune.vcpupin.extend([vcpu0, vcpu1, vcpu2, vcpu3])

        emu = config.LibvirtConfigGuestCPUTuneEmulatorPin()
        emu.cpuset = set([0, 1, 2, 3, 4, 5, 6, 7])
        cputune.emulatorpin = emu

        sch0 = config.LibvirtConfigGuestCPUTuneVCPUSched()
        sch0.vcpus = set([0, 1, 2, 3])
        sch0.scheduler = "fifo"
        sch0.priority = 1
        sch1 = config.LibvirtConfigGuestCPUTuneVCPUSched()
        sch1.vcpus = set([4, 5, 6, 7])
        sch1.scheduler = "fifo"
        sch1.priority = 99
        cputune.vcpusched.extend([sch0, sch1])

        xml = cputune.to_xml()
        self.assertXmlEqual(xml, """
          <cputune>
            <emulatorpin cpuset="0-7"/>
            <vcpupin vcpu="0" cpuset="0-1"/>
            <vcpupin vcpu="1" cpuset="2-3"/>
            <vcpupin vcpu="2" cpuset="4-5"/>
            <vcpupin vcpu="3" cpuset="6-7"/>
            <vcpusched vcpus="0-3" scheduler="fifo" priority="1"/>
            <vcpusched vcpus="4-7" scheduler="fifo" priority="99"/>
          </cputune>""")


class LibvirtConfigGuestMemoryBackingTest(LibvirtConfigBaseTest):
    def test_config_memory_backing_none(self):
        obj = config.LibvirtConfigGuestMemoryBacking()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<memoryBacking/>")

    def test_config_memory_backing_all(self):
        obj = config.LibvirtConfigGuestMemoryBacking()
        obj.locked = True
        obj.sharedpages = False
        page = config.LibvirtConfigGuestMemoryBackingPage()
        page.size_kb = 2048
        page.nodeset = [2, 3]
        obj.hugepages.append(page)

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
          <memoryBacking>
            <hugepages>
              <page size="2048" unit="KiB" nodeset="2-3"/>
            </hugepages>
            <nosharepages/>
            <locked/>
          </memoryBacking>""")

    def test_config_memory_backing_source_all(self):
        obj = config.LibvirtConfigGuestMemoryBacking()
        obj.sharedaccess = True
        obj.allocateimmediate = True
        obj.filesource = True
        obj.discard = True
        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
            <memoryBacking>
              <source type="file"/>
              <access mode="shared"/>
              <allocation mode="immediate"/>
              <discard />
            </memoryBacking>""")


class LibvirtConfigGuestMemoryTuneTest(LibvirtConfigBaseTest):
    def test_config_memory_backing_none(self):
        obj = config.LibvirtConfigGuestMemoryTune()

        xml = obj.to_xml()
        self.assertXmlEqual(xml, "<memtune/>")

    def test_config_memory_backing_all(self):
        obj = config.LibvirtConfigGuestMemoryTune()
        obj.soft_limit = 6
        obj.hard_limit = 28
        obj.swap_hard_limit = 140
        obj.min_guarantee = 270

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
          <memtune>
            <hard_limit unit="KiB">28</hard_limit>
            <soft_limit unit="KiB">6</soft_limit>
            <swap_hard_limit unit="KiB">140</swap_hard_limit>
            <min_guarantee unit="KiB">270</min_guarantee>
          </memtune>""")


class LibvirtConfigGuestNUMATuneTest(LibvirtConfigBaseTest):
    def test_config_numa_tune_none(self):
        obj = config.LibvirtConfigGuestNUMATune()

        xml = obj.to_xml()
        self.assertXmlEqual("<numatune/>", xml)

    def test_config_numa_tune_memory(self):
        obj = config.LibvirtConfigGuestNUMATune()

        numamemory = config.LibvirtConfigGuestNUMATuneMemory()
        numamemory.nodeset = [0, 1, 2, 3, 8]

        obj.memory = numamemory

        xml = obj.to_xml()
        self.assertXmlEqual("""
          <numatune>
            <memory mode="strict" nodeset="0-3,8"/>
          </numatune>""", xml)

    def test_config_numa_tune_memnodes(self):
        obj = config.LibvirtConfigGuestNUMATune()

        numamemnode0 = config.LibvirtConfigGuestNUMATuneMemNode()
        numamemnode0.cellid = 0
        numamemnode0.nodeset = [0, 1]

        numamemnode1 = config.LibvirtConfigGuestNUMATuneMemNode()
        numamemnode1.cellid = 1
        numamemnode1.nodeset = [2, 3]

        numamemnode2 = config.LibvirtConfigGuestNUMATuneMemNode()
        numamemnode2.cellid = 2
        numamemnode2.nodeset = [8]

        obj.memnodes.extend([numamemnode0,
                             numamemnode1,
                             numamemnode2])

        xml = obj.to_xml()
        self.assertXmlEqual("""
          <numatune>
            <memnode cellid="0" mode="strict" nodeset="0-1"/>
            <memnode cellid="1" mode="strict" nodeset="2-3"/>
            <memnode cellid="2" mode="strict" nodeset="8"/>
          </numatune>""", xml)


class LibvirtConfigGuestMetadataNovaTest(LibvirtConfigBaseTest):

    def test_config_metadata(self):
        meta = config.LibvirtConfigGuestMetaNovaInstance()
        meta.package = "2014.2.3"
        meta.name = "moonbuggy"
        meta.creationTime = 1234567890
        meta.roottype = "image"
        meta.rootid = "fe55c69a-8b2e-4bbc-811a-9ad2023a0426"

        owner = config.LibvirtConfigGuestMetaNovaOwner()
        owner.userid = "3472c2a6-de91-4fb5-b618-42bc781ef670"
        owner.username = "buzz"
        owner.projectid = "f241e906-010e-4917-ae81-53f4fb8aa021"
        owner.projectname = "moonshot"

        meta.owner = owner

        flavor = config.LibvirtConfigGuestMetaNovaFlavor()
        flavor.name = "m1.lowgravity"
        flavor.vcpus = 8
        flavor.memory = 2048
        flavor.swap = 10
        flavor.disk = 50
        flavor.ephemeral = 10

        meta.flavor = flavor

        meta.ports = config.LibvirtConfigGuestMetaNovaPorts(
            ports=[
                config.LibvirtConfigGuestMetaNovaPort(
                    '567a4527-b0e4-4d0a-bcc2-71fda37897f7',
                    ips=[
                        config.LibvirtConfigGuestMetaNovaIp(
                            'fixed', '192.168.1.1', '4'),
                        config.LibvirtConfigGuestMetaNovaIp(
                            'fixed', 'fe80::f95c:b030:7094', '6'),
                        config.LibvirtConfigGuestMetaNovaIp(
                            'floating', '11.22.33.44', '4')]),
                config.LibvirtConfigGuestMetaNovaPort(
                    'a3ca97e2-0cf9-4159-9bfc-afd55bc13ead',
                    ips=[
                        config.LibvirtConfigGuestMetaNovaIp(
                            'fixed', '10.0.0.1', '4'),
                        config.LibvirtConfigGuestMetaNovaIp(
                            'fixed', 'fdf8:f53b:82e4::52', '6'),
                        config.LibvirtConfigGuestMetaNovaIp(
                            'floating', '1.2.3.4', '4')])])

        xml = meta.to_xml()
        self.assertXmlEqual(xml, """
    <nova:instance xmlns:nova='http://openstack.org/xmlns/libvirt/nova/1.1'>
      <nova:package version="2014.2.3"/>
      <nova:name>moonbuggy</nova:name>
      <nova:creationTime>2009-02-13 23:31:30</nova:creationTime>
      <nova:flavor name="m1.lowgravity">
        <nova:memory>2048</nova:memory>
        <nova:disk>50</nova:disk>
        <nova:swap>10</nova:swap>
        <nova:ephemeral>10</nova:ephemeral>
        <nova:vcpus>8</nova:vcpus>
      </nova:flavor>
      <nova:owner>
        <nova:user
         uuid="3472c2a6-de91-4fb5-b618-42bc781ef670">buzz</nova:user>
        <nova:project
         uuid="f241e906-010e-4917-ae81-53f4fb8aa021">moonshot</nova:project>
      </nova:owner>
      <nova:root type="image" uuid="fe55c69a-8b2e-4bbc-811a-9ad2023a0426"/>
      <nova:ports>
        <nova:port uuid="567a4527-b0e4-4d0a-bcc2-71fda37897f7">
          <nova:ip type="fixed" address="192.168.1.1" ipVersion="4"/>
          <nova:ip type="fixed" address="fe80::f95c:b030:7094" ipVersion="6"/>
          <nova:ip type="floating" address="11.22.33.44" ipVersion="4"/>
        </nova:port>
        <nova:port uuid="a3ca97e2-0cf9-4159-9bfc-afd55bc13ead">
          <nova:ip type="fixed" address="10.0.0.1" ipVersion="4"/>
          <nova:ip type="fixed" address="fdf8:f53b:82e4::52" ipVersion="6"/>
          <nova:ip type="floating" address="1.2.3.4" ipVersion="4"/>
        </nova:port>
      </nova:ports>
    </nova:instance>
        """)


class LibvirtConfigGuestIDMap(LibvirtConfigBaseTest):
    def test_config_id_map_parse_start_not_int(self):
        xmlin = "<uid start='a' target='20000' count='5'/>"
        obj = config.LibvirtConfigGuestIDMap()

        self.assertRaises(ValueError, obj.parse_str, xmlin)

    def test_config_id_map_parse_target_not_int(self):
        xmlin = "<uid start='2' target='a' count='5'/>"
        obj = config.LibvirtConfigGuestIDMap()

        self.assertRaises(ValueError, obj.parse_str, xmlin)

    def test_config_id_map_parse_count_not_int(self):
        xmlin = "<uid start='2' target='20000' count='a'/>"
        obj = config.LibvirtConfigGuestIDMap()

        self.assertRaises(ValueError, obj.parse_str, xmlin)

    def test_config_uid_map(self):
        obj = config.LibvirtConfigGuestUIDMap()
        obj.start = 1
        obj.target = 10000
        obj.count = 2

        xml = obj.to_xml()
        self.assertXmlEqual("<uid start='1' target='10000' count='2'/>", xml)

    def test_config_uid_map_parse(self):
        xmlin = "<uid start='2' target='20000' count='5'/>"
        obj = config.LibvirtConfigGuestUIDMap()
        obj.parse_str(xmlin)

        self.assertEqual(2, obj.start)
        self.assertEqual(20000, obj.target)
        self.assertEqual(5, obj.count)

    def test_config_gid_map(self):
        obj = config.LibvirtConfigGuestGIDMap()
        obj.start = 1
        obj.target = 10000
        obj.count = 2

        xml = obj.to_xml()
        self.assertXmlEqual("<gid start='1' target='10000' count='2'/>", xml)

    def test_config_gid_map_parse(self):
        xmlin = "<gid start='2' target='20000' count='5'/>"
        obj = config.LibvirtConfigGuestGIDMap()
        obj.parse_str(xmlin)

        self.assertEqual(2, obj.start)
        self.assertEqual(20000, obj.target)
        self.assertEqual(5, obj.count)


class LibvirtConfigMemoryBalloonTest(LibvirtConfigBaseTest):

    def test_config_memory_balloon_period(self):
        balloon = config.LibvirtConfigMemoryBalloon()
        balloon.model = 'virtio'
        balloon.period = 11

        xml = balloon.to_xml()
        expected_xml = """
        <memballoon model='virtio'>
            <stats period='11'/>
        </memballoon>"""

        self.assertXmlEqual(expected_xml, xml)

    def test_config_memory_balloon_no_period(self):
        balloon = config.LibvirtConfigMemoryBalloon()
        balloon.model = 'virtio'

        xml = balloon.to_xml()
        expected_xml = """
        <memballoon model='virtio' />"""

        self.assertXmlEqual(expected_xml, xml)

    def test_config_memory_balloon_driver_iommu(self):
        balloon = config.LibvirtConfigMemoryBalloon()
        balloon.model = 'virtio'
        balloon.driver_iommu = True

        self.assertTrue(balloon.uses_virtio)

        xml = balloon.to_xml()
        expected_xml = """
            <memballoon model='virtio'>
              <driver iommu="on" />
            </memballoon>"""

        self.assertXmlEqual(expected_xml, xml)


class LibvirtConfigSecretTest(LibvirtConfigBaseTest):

    def test_config_secret_volume(self):
        secret = config.LibvirtConfigSecret()
        secret.ephemeral = False
        secret.private = False
        secret.description = 'sample desc'
        secret.uuid = 'c7a5fdbd-edaf-9455-926a-d65c16db1809'
        secret.usage_type = 'volume'
        secret.usage_id = 'sample_volume'

        xml = secret.to_xml()
        expected_xml = """
        <secret ephemeral="no" private="no">
          <description>sample desc</description>
          <uuid>c7a5fdbd-edaf-9455-926a-d65c16db1809</uuid>
          <usage type="volume">
            <volume>sample_volume</volume>
          </usage>
        </secret>"""

        self.assertXmlEqual(expected_xml, xml)

    def test_config_secret_ceph(self):
        secret = config.LibvirtConfigSecret()
        secret.ephemeral = False
        secret.private = False
        secret.description = 'sample desc'
        secret.usage_type = 'ceph'
        secret.usage_id = 'sample_name'

        xml = secret.to_xml()
        expected_xml = """
        <secret ephemeral="no" private="no">
          <description>sample desc</description>
          <usage type="ceph">
            <name>sample_name</name>
          </usage>
        </secret>"""

        self.assertXmlEqual(expected_xml, xml)

    def test_config_secret_vtpm(self):
        secret = config.LibvirtConfigSecret()
        secret.ephemeral = True
        secret.private = True
        secret.usage_type = 'vtpm'
        secret.usage_id = 'sample_name'
        secret.uuid = uuids.vtpm

        xml = secret.to_xml()
        expected_xml = f"""
        <secret ephemeral="yes" private="yes">
          <uuid>{uuids.vtpm}</uuid>
          <usage type="vtpm">
            <name>sample_name</name>
          </usage>
        </secret>"""

        self.assertXmlEqual(expected_xml, xml)

    def test_config_secret_iscsi(self):
        secret = config.LibvirtConfigSecret()
        secret.ephemeral = False
        secret.private = False
        secret.description = 'sample desc'
        secret.usage_type = 'iscsi'
        secret.usage_id = 'sample_target'

        xml = secret.to_xml()
        expected_xml = """
        <secret ephemeral="no" private="no">
          <description>sample desc</description>
          <usage type="iscsi">
            <target>sample_target</target>
          </usage>
        </secret>"""

        self.assertXmlEqual(expected_xml, xml)


class LibvirtConfigGuestVPMEMTest(LibvirtConfigBaseTest):
    def test_config_vpmem(self):
        obj = config.LibvirtConfigGuestVPMEM()
        obj.source_path = '/dev/dax0.0'
        obj.target_size = 4096 * units.Ki
        obj.align_size = 2048

        xml = obj.to_xml()
        self.assertXmlEqual(xml, """
          <memory model='nvdimm' access="shared">
            <source>
                <path>/dev/dax0.0</path>
                <alignsize>2048</alignsize>
                <pmem/>
            </source>
            <target>
                <size>4194304</size>
                <node>0</node>
                <label>
                    <size>2048</size>
                </label>
            </target>
          </memory>""")


class LibvirtConfigGuestIOMMUTest(LibvirtConfigBaseTest):

    def test_config_iommu(self):
        obj = config.LibvirtConfigGuestIOMMU()
        obj.model = "intel"
        obj.interrupt_remapping = True
        obj.caching_mode = True
        obj.aw_bits = 48
        obj.eim = True
        obj.iotlb = True

        xml = obj.to_xml()
        self.assertXmlEqual(
            xml,
            """
<iommu model='intel'>
  <driver intremap='on' caching_mode='on' aw_bits='48' eim='on' iotlb='on'/>
</iommu>
            """,
        )


class LibvirtConfigDomainCapsVideoModelsTests(LibvirtConfigBaseTest):

    def test_parse_video_model(self):

        xml = """
        <video supported='yes'>
          <enum name='modelType'>
            <value>vga</value>
            <value>cirrus</value>
            <value>vmvga</value>
            <value>qxl</value>
            <value>virtio</value>
          </enum>
        </video>
        """
        obj = config.LibvirtConfigDomainCapsVideoModels()
        obj.parse_str(xml)
        expected_models = ('vga', 'cirrus', 'vmvga', 'qxl', 'virtio')
        self.assertTrue(obj.supported)
        for model in expected_models:
            self.assertIn(model, obj.models)
        self.assertNotIn('gop', obj.models)


class LibvirtConfigDomainCapsDiskBusesTests(LibvirtConfigBaseTest):

    def test_parse_disk_buses(self):

        xml = """
        <disk supported='yes'>
          <enum name='diskDevice'>
            <value>disk</value>
            <value>cdrom</value>
            <value>floppy</value>
            <value>lun</value>
          </enum>
          <enum name='bus'>
            <value>ide</value>
            <value>scsi</value>
            <value>virtio</value>
            <value>usb</value>
            <value>sata</value>
          </enum>
        </disk>
        """
        obj = config.LibvirtConfigDomainCapsDiskBuses()
        obj.parse_str(xml)
        expected_buses = ('ide', 'scsi', 'virtio', 'usb', 'sata')
        self.assertTrue(obj.supported)
        for bus in expected_buses:
            self.assertIn(bus, obj.buses)
        self.assertNotIn('fdc', obj.buses)


class LibvirtConfigDomainCapsDevicesTests(LibvirtConfigBaseTest):

    def test_parse_domain_caps_devices(self):

        xml = """
        <devices>
          <disk supported='yes'>
            <enum name='diskDevice'>
              <value>disk</value>
              <value>cdrom</value>
              <value>floppy</value>
              <value>lun</value>
            </enum>
            <enum name='bus'>
              <value>ide</value>
              <value>fdc</value>
              <value>scsi</value>
              <value>virtio</value>
              <value>usb</value>
              <value>sata</value>
            </enum>
          </disk>
          <graphics supported='yes'>
            <enum name='type'>
              <value>sdl</value>
              <value>vnc</value>
              <value>spice</value>
            </enum>
          </graphics>
          <video supported='yes'>
            <enum name='modelType'>
              <value>vga</value>
              <value>cirrus</value>
              <value>vmvga</value>
              <value>qxl</value>
              <value>virtio</value>
            </enum>
          </video>
          <hostdev supported='yes'>
            <enum name='mode'>
              <value>subsystem</value>
            </enum>
            <enum name='startupPolicy'>
              <value>default</value>
              <value>mandatory</value>
              <value>requisite</value>
              <value>optional</value>
            </enum>
            <enum name='subsysType'>
              <value>usb</value>
              <value>pci</value>
              <value>scsi</value>
            </enum>
            <enum name='capsType'/>
            <enum name='pciBackend'/>
          </hostdev>
        </devices>
        """
        obj = config.LibvirtConfigDomainCapsDevices()
        obj.parse_str(xml)
        # we only use the video and disk devices today.
        device_types = [config.LibvirtConfigDomainCapsDiskBuses,
                        config.LibvirtConfigDomainCapsVideoModels,
                        ]
        # so we assert there are only two device types parsed
        self.assertEqual(2, len(obj.devices))
        # we then assert that the parsed devices are of the correct type
        for dev in obj.devices:
            self.assertIn(type(dev), device_types)
        # and that the sub-devices are accessible directly via properties.
        self.assertIsInstance(
            obj.disk, config.LibvirtConfigDomainCapsDiskBuses)
        self.assertIsInstance(
            obj.video, config.LibvirtConfigDomainCapsVideoModels)


class LibvirtConfigDomainCapsOSTests(LibvirtConfigBaseTest):

    def test_parse_domain_caps_os(self):
        xml = """
        <os supported="yes">
          <enum name="firmware">
            <value>efi</value>
          </enum>
          <loader supported="yes">
            <value>/usr/share/edk2/ovmf/OVMF_CODE.fd</value>
            <value>/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd</value>
            <enum name="type">
              <value>rom</value>
              <value>pflash</value>
            </enum>
            <enum name="readonly">
              <value>yes</value>
              <value>no</value>
            </enum>
            <enum name="secure">
              <value>no</value>
              <value>yes</value>
            </enum>
          </loader>
        </os>
        """

        obj = config.LibvirtConfigDomainCapsOS()
        obj.parse_str(xml)

        self.assertTrue(obj.supported)
        self.assertTrue(obj.loader_supported)
        self.assertTrue(obj.uefi_autoconfig_supported)
        self.assertEqual(
            [
                '/usr/share/edk2/ovmf/OVMF_CODE.fd',
                '/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd',
            ],
            obj.loader_paths,
        )
        self.assertTrue(obj.uefi_supported)
        self.assertTrue(obj.secure_boot_supported)


class LibvirtConfigTPMTest(LibvirtConfigBaseTest):

    def test_config_tpm_tis_1_2(self):
        vtpm_config = hardware.VTPMConfig('1.2', 'tpm-tis')
        vtpm_secret_uuid = 'b028130c-bdcb-4d5f-9bca-b9175ca6c28c'
        expected_xml = """
        <tpm model='tpm-tis'>
          <backend type='emulator' version='1.2'>
            <encryption secret='b028130c-bdcb-4d5f-9bca-b9175ca6c28c'/>
          </backend>
        </tpm>"""

        tpm = config.LibvirtConfigGuestVTPM(vtpm_config, vtpm_secret_uuid)
        xml = tpm.to_xml()

        self.assertXmlEqual(expected_xml, xml)

    def test_config_tpm_tis_2_0(self):
        vtpm_config = hardware.VTPMConfig('2.0', 'tpm-tis')
        vtpm_secret_uuid = 'b028130c-bdcb-4d5f-9bca-b9175ca6c28c'
        expected_xml = """
        <tpm model='tpm-tis'>
          <backend type='emulator' version='2.0'>
            <encryption secret='b028130c-bdcb-4d5f-9bca-b9175ca6c28c'/>
          </backend>
        </tpm>"""

        tpm = config.LibvirtConfigGuestVTPM(vtpm_config, vtpm_secret_uuid)
        xml = tpm.to_xml()

        self.assertXmlEqual(expected_xml, xml)

    def test_config_tpm_crb_2_0(self):
        vtpm_config = hardware.VTPMConfig('2.0', 'tpm-crb')
        vtpm_secret_uuid = 'b028130c-bdcb-4d5f-9bca-b9175ca6c28c'
        expected_xml = """
        <tpm model='tpm-crb'>
          <backend type='emulator' version='2.0'>
            <encryption secret='b028130c-bdcb-4d5f-9bca-b9175ca6c28c'/>
          </backend>
        </tpm>"""

        tpm = config.LibvirtConfigGuestVTPM(vtpm_config, vtpm_secret_uuid)
        xml = tpm.to_xml()

        self.assertXmlEqual(expected_xml, xml)
