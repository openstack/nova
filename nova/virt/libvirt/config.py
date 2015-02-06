# Copyright (C) 2012-2013 Red Hat, Inc.
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

"""
Configuration for libvirt objects.

Classes to represent the configuration of various libvirt objects
and support conversion to/from XML. These classes are solely concerned
by providing direct Object <-> XML document conversions. No policy or
operational decisions should be made by code in these classes. Such
policy belongs in the 'designer.py' module which provides simplified
helpers for populating up config object instances.
"""

import time

from lxml import etree
from oslo_utils import units
import six

from nova import exception
from nova.openstack.common import log as logging
from nova.pci import utils as pci_utils
from nova.virt import hardware


LOG = logging.getLogger(__name__)

# Namespace to use for Nova specific metadata items in XML
NOVA_NS = "http://openstack.org/xmlns/libvirt/nova/1.0"


class LibvirtConfigObject(object):

    def __init__(self, **kwargs):
        super(LibvirtConfigObject, self).__init__()

        self.root_name = kwargs.get("root_name")
        self.ns_prefix = kwargs.get('ns_prefix')
        self.ns_uri = kwargs.get('ns_uri')

    def _new_node(self, name, **kwargs):
        if self.ns_uri is None:
            return etree.Element(name, **kwargs)
        else:
            return etree.Element("{" + self.ns_uri + "}" + name,
                                 nsmap={self.ns_prefix: self.ns_uri},
                                 **kwargs)

    def _text_node(self, name, value, **kwargs):
        child = self._new_node(name, **kwargs)
        child.text = six.text_type(value)
        return child

    def format_dom(self):
        return self._new_node(self.root_name)

    def parse_str(self, xmlstr):
        self.parse_dom(etree.fromstring(xmlstr))

    def parse_dom(self, xmldoc):
        if self.root_name != xmldoc.tag:
            raise exception.InvalidInput(
                "Root element name should be '%s' not '%s'"
                % (self.root_name, xmldoc.tag))

    def to_xml(self, pretty_print=True):
        root = self.format_dom()
        xml_str = etree.tostring(root, pretty_print=pretty_print)
        LOG.debug("Generated XML %s ", (xml_str,))
        return xml_str


class LibvirtConfigCaps(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCaps, self).__init__(root_name="capabilities",
                                                **kwargs)
        self.host = None
        self.guests = []

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCaps, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "host":
                host = LibvirtConfigCapsHost()
                host.parse_dom(c)
                self.host = host
            elif c.tag == "guest":
                guest = LibvirtConfigCapsGuest()
                guest.parse_dom(c)
                self.guests.append(guest)

    def format_dom(self):
        caps = super(LibvirtConfigCaps, self).format_dom()

        if self.host:
            caps.append(self.host.format_dom())
        for g in self.guests:
            caps.append(g.format_dom())

        return caps


class LibvirtConfigCapsNUMATopology(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsNUMATopology, self).__init__(
            root_name="topology",
            **kwargs)

        self.cells = []

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsNUMATopology, self).parse_dom(xmldoc)

        xmlcells = xmldoc.getchildren()[0]
        for xmlcell in xmlcells.getchildren():
            cell = LibvirtConfigCapsNUMACell()
            cell.parse_dom(xmlcell)
            self.cells.append(cell)

    def format_dom(self):
        topo = super(LibvirtConfigCapsNUMATopology, self).format_dom()

        cells = etree.Element("cells")
        cells.set("num", str(len(self.cells)))
        topo.append(cells)

        for cell in self.cells:
            cells.append(cell.format_dom())

        return topo


class LibvirtConfigCapsNUMACell(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsNUMACell, self).__init__(root_name="cell",
                                                        **kwargs)

        self.id = None
        self.memory = None
        self.mempages = []
        self.cpus = []

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsNUMACell, self).parse_dom(xmldoc)

        self.id = int(xmldoc.get("id"))
        for c in xmldoc.getchildren():
            if c.tag == "memory":
                self.memory = int(c.text)
            elif c.tag == "pages":
                pages = LibvirtConfigCapsNUMAPages()
                pages.parse_dom(c)
                self.mempages.append(pages)
            elif c.tag == "cpus":
                for c2 in c.getchildren():
                    cpu = LibvirtConfigCapsNUMACPU()
                    cpu.parse_dom(c2)
                    self.cpus.append(cpu)

    def format_dom(self):
        cell = super(LibvirtConfigCapsNUMACell, self).format_dom()

        cell.set("id", str(self.id))

        mem = etree.Element("memory")
        mem.set("unit", "KiB")
        mem.text = str(self.memory)
        cell.append(mem)

        for pages in self.mempages:
            cell.append(pages.format_dom())

        cpus = etree.Element("cpus")
        cpus.set("num", str(len(self.cpus)))
        for cpu in self.cpus:
            cpus.append(cpu.format_dom())
        cell.append(cpus)

        return cell


class LibvirtConfigCapsNUMACPU(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsNUMACPU, self).__init__(root_name="cpu",
                                                       **kwargs)

        self.id = None
        self.socket_id = None
        self.core_id = None
        self.siblings = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsNUMACPU, self).parse_dom(xmldoc)

        self.id = int(xmldoc.get("id"))
        if xmldoc.get("socket_id") is not None:
            self.socket_id = int(xmldoc.get("socket_id"))
        if xmldoc.get("core_id") is not None:
            self.core_id = int(xmldoc.get("core_id"))

        if xmldoc.get("siblings") is not None:
            self.siblings = hardware.parse_cpu_spec(
                xmldoc.get("siblings"))

    def format_dom(self):
        cpu = super(LibvirtConfigCapsNUMACPU, self).format_dom()

        cpu.set("id", str(self.id))
        if self.socket_id is not None:
            cpu.set("socket_id", str(self.socket_id))
        if self.core_id is not None:
            cpu.set("core_id", str(self.core_id))
        if self.siblings is not None:
            cpu.set("siblings",
                    hardware.format_cpu_spec(self.siblings))

        return cpu


class LibvirtConfigCapsNUMAPages(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsNUMAPages, self).__init__(
            root_name="pages", **kwargs)

        self.size = None
        self.total = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsNUMAPages, self).parse_dom(xmldoc)

        self.size = int(xmldoc.get("size"))
        self.total = int(xmldoc.text)

    def format_dom(self):
        pages = super(LibvirtConfigCapsNUMAPages, self).format_dom()

        pages.text = str(self.total)
        pages.set("size", str(self.size))
        pages.set("unit", "KiB")

        return pages


class LibvirtConfigCapsHost(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsHost, self).__init__(root_name="host",
                                                    **kwargs)

        self.cpu = None
        self.uuid = None
        self.topology = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsHost, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "cpu":
                cpu = LibvirtConfigCPU()
                cpu.parse_dom(c)
                self.cpu = cpu
            elif c.tag == "uuid":
                self.uuid = c.text
            elif c.tag == "topology":
                self.topology = LibvirtConfigCapsNUMATopology()
                self.topology.parse_dom(c)

    def format_dom(self):
        caps = super(LibvirtConfigCapsHost, self).format_dom()

        if self.uuid:
            caps.append(self._text_node("uuid", self.uuid))
        if self.cpu:
            caps.append(self.cpu.format_dom())
        if self.topology:
            caps.append(self.topology.format_dom())

        return caps


class LibvirtConfigCapsGuest(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsGuest, self).__init__(root_name="guest",
                                                     **kwargs)

        self.arch = None
        self.ostype = None
        self.domtype = list()

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsGuest, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "os_type":
                self.ostype = c.text
            elif c.tag == "arch":
                self.arch = c.get("name")
                for sc in c.getchildren():
                    if sc.tag == "domain":
                        self.domtype.append(sc.get("type"))

    def format_dom(self):
        caps = super(LibvirtConfigCapsGuest, self).format_dom()

        if self.ostype is not None:
            caps.append(self._text_node("os_type", self.ostype))
        if self.arch:
            arch = etree.Element("arch", name=self.arch)
            for dt in self.domtype:
                dte = etree.Element("domain")
                dte.set("type", dt)
                arch.append(dte)
            caps.append(arch)

        return caps


class LibvirtConfigGuestTimer(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestTimer, self).__init__(root_name="timer",
                                                      **kwargs)

        self.name = "platform"
        self.track = None
        self.tickpolicy = None
        self.present = None

    def format_dom(self):
        tm = super(LibvirtConfigGuestTimer, self).format_dom()

        tm.set("name", self.name)
        if self.track is not None:
            tm.set("track", self.track)
        if self.tickpolicy is not None:
            tm.set("tickpolicy", self.tickpolicy)
        if self.present is not None:
            if self.present:
                tm.set("present", "yes")
            else:
                tm.set("present", "no")

        return tm


class LibvirtConfigGuestClock(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestClock, self).__init__(root_name="clock",
                                                      **kwargs)

        self.offset = "utc"
        self.adjustment = None
        self.timezone = None
        self.timers = []

    def format_dom(self):
        clk = super(LibvirtConfigGuestClock, self).format_dom()

        clk.set("offset", self.offset)
        if self.adjustment:
            clk.set("adjustment", self.adjustment)
        elif self.timezone:
            clk.set("timezone", self.timezone)

        for tm in self.timers:
            clk.append(tm.format_dom())

        return clk

    def add_timer(self, tm):
        self.timers.append(tm)


class LibvirtConfigCPUFeature(LibvirtConfigObject):

    def __init__(self, name=None, **kwargs):
        super(LibvirtConfigCPUFeature, self).__init__(root_name='feature',
                                                      **kwargs)

        self.name = name

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCPUFeature, self).parse_dom(xmldoc)

        self.name = xmldoc.get("name")

    def format_dom(self):
        ft = super(LibvirtConfigCPUFeature, self).format_dom()

        ft.set("name", self.name)

        return ft

    def __eq__(self, obj):
        return obj.name == self.name

    def __ne__(self, obj):
        return obj.name != self.name

    def __hash__(self):
        return hash(self.name)


class LibvirtConfigCPU(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCPU, self).__init__(root_name='cpu',
                                               **kwargs)

        self.arch = None
        self.vendor = None
        self.model = None

        self.sockets = None
        self.cores = None
        self.threads = None

        self.features = set()

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCPU, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "arch":
                self.arch = c.text
            elif c.tag == "model":
                self.model = c.text
            elif c.tag == "vendor":
                self.vendor = c.text
            elif c.tag == "topology":
                self.sockets = int(c.get("sockets"))
                self.cores = int(c.get("cores"))
                self.threads = int(c.get("threads"))
            elif c.tag == "feature":
                f = LibvirtConfigCPUFeature()
                f.parse_dom(c)
                self.add_feature(f)

    def format_dom(self):
        cpu = super(LibvirtConfigCPU, self).format_dom()

        if self.arch is not None:
            cpu.append(self._text_node("arch", self.arch))
        if self.model is not None:
            cpu.append(self._text_node("model", self.model))
        if self.vendor is not None:
            cpu.append(self._text_node("vendor", self.vendor))

        if (self.sockets is not None and
            self.cores is not None and
                self.threads is not None):
            top = etree.Element("topology")
            top.set("sockets", str(self.sockets))
            top.set("cores", str(self.cores))
            top.set("threads", str(self.threads))
            cpu.append(top)

        # sorting the features to allow more predictable tests
        for f in sorted(self.features, key=lambda x: x.name):
            cpu.append(f.format_dom())

        return cpu

    def add_feature(self, feat):
        self.features.add(feat)


class LibvirtConfigGuestCPUFeature(LibvirtConfigCPUFeature):

    def __init__(self, name=None, **kwargs):
        super(LibvirtConfigGuestCPUFeature, self).__init__(name, **kwargs)

        self.policy = "require"

    def format_dom(self):
        ft = super(LibvirtConfigGuestCPUFeature, self).format_dom()

        ft.set("policy", self.policy)

        return ft


class LibvirtConfigGuestCPUNUMACell(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPUNUMACell, self).__init__(root_name="cell",
                                                            **kwargs)
        self.id = None
        self.cpus = None
        self.memory = None

    def parse_dom(self, xmldoc):
        if xmldoc.get("id") is not None:
            self.id = int(xmldoc.get("id"))
        if xmldoc.get("memory") is not None:
            self.memory = int(xmldoc.get("memory"))
        if xmldoc.get("cpus") is not None:
            self.cpus = hardware.parse_cpu_spec(xmldoc.get("cpus"))

    def format_dom(self):
        cell = super(LibvirtConfigGuestCPUNUMACell, self).format_dom()

        if self.id is not None:
            cell.set("id", str(self.id))
        if self.cpus is not None:
            cell.set("cpus",
                     hardware.format_cpu_spec(self.cpus))
        if self.memory is not None:
            cell.set("memory", str(self.memory))

        return cell


class LibvirtConfigGuestCPUNUMA(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPUNUMA, self).__init__(root_name="numa",
                                                        **kwargs)

        self.cells = []

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestCPUNUMA, self).parse_dom(xmldoc)

        for child in xmldoc.getchildren():
            if child.tag == "cell":
                cell = LibvirtConfigGuestCPUNUMACell()
                cell.parse_dom(child)
                self.cells.append(cell)

    def format_dom(self):
        numa = super(LibvirtConfigGuestCPUNUMA, self).format_dom()

        for cell in self.cells:
            numa.append(cell.format_dom())

        return numa


class LibvirtConfigGuestCPU(LibvirtConfigCPU):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPU, self).__init__(**kwargs)

        self.mode = None
        self.match = "exact"
        self.numa = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestCPU, self).parse_dom(xmldoc)
        self.mode = xmldoc.get('mode')
        self.match = xmldoc.get('match')
        for child in xmldoc.getchildren():
            if child.tag == "numa":
                numa = LibvirtConfigGuestCPUNUMA()
                numa.parse_dom(child)
                self.numa = numa

    def format_dom(self):
        cpu = super(LibvirtConfigGuestCPU, self).format_dom()

        if self.mode:
            cpu.set("mode", self.mode)
        cpu.set("match", self.match)
        if self.numa is not None:
            cpu.append(self.numa.format_dom())

        return cpu


class LibvirtConfigGuestSMBIOS(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSMBIOS, self).__init__(root_name="smbios",
                                                       **kwargs)

        self.mode = "sysinfo"

    def format_dom(self):
        smbios = super(LibvirtConfigGuestSMBIOS, self).format_dom()
        smbios.set("mode", self.mode)

        return smbios


class LibvirtConfigGuestSysinfo(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSysinfo, self).__init__(root_name="sysinfo",
                                                        **kwargs)

        self.type = "smbios"
        self.bios_vendor = None
        self.bios_version = None
        self.system_manufacturer = None
        self.system_product = None
        self.system_version = None
        self.system_serial = None
        self.system_uuid = None

    def format_dom(self):
        sysinfo = super(LibvirtConfigGuestSysinfo, self).format_dom()

        sysinfo.set("type", self.type)

        bios = None
        system = None

        if self.bios_vendor is not None:
            if bios is None:
                bios = etree.Element("bios")
            info = etree.Element("entry", name="vendor")
            info.text = self.bios_vendor
            bios.append(info)

        if self.bios_version is not None:
            if bios is None:
                bios = etree.Element("bios")
            info = etree.Element("entry", name="version")
            info.text = self.bios_version
            bios.append(info)

        if self.system_manufacturer is not None:
            if system is None:
                system = etree.Element("system")
            info = etree.Element("entry", name="manufacturer")
            info.text = self.system_manufacturer
            system.append(info)

        if self.system_product is not None:
            if system is None:
                system = etree.Element("system")
            info = etree.Element("entry", name="product")
            info.text = self.system_product
            system.append(info)

        if self.system_version is not None:
            if system is None:
                system = etree.Element("system")
            info = etree.Element("entry", name="version")
            info.text = self.system_version
            system.append(info)

        if self.system_serial is not None:
            if system is None:
                system = etree.Element("system")
            info = etree.Element("entry", name="serial")
            info.text = self.system_serial
            system.append(info)

        if self.system_uuid is not None:
            if system is None:
                system = etree.Element("system")
            info = etree.Element("entry", name="uuid")
            info.text = self.system_uuid
            system.append(info)

        if bios is not None:
            sysinfo.append(bios)
        if system is not None:
            sysinfo.append(system)

        return sysinfo


class LibvirtConfigGuestDevice(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestDevice, self).__init__(**kwargs)


class LibvirtConfigGuestDisk(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestDisk, self).__init__(root_name="disk",
                                                     **kwargs)

        self.source_type = "file"
        self.source_device = "disk"
        self.driver_name = None
        self.driver_format = None
        self.driver_cache = None
        self.driver_discard = None
        self.source_path = None
        self.source_protocol = None
        self.source_name = None
        self.source_hosts = []
        self.source_ports = []
        self.target_dev = None
        self.target_path = None
        self.target_bus = None
        self.auth_username = None
        self.auth_secret_type = None
        self.auth_secret_uuid = None
        self.serial = None
        self.disk_read_bytes_sec = None
        self.disk_read_iops_sec = None
        self.disk_write_bytes_sec = None
        self.disk_write_iops_sec = None
        self.disk_total_bytes_sec = None
        self.disk_total_iops_sec = None
        self.logical_block_size = None
        self.physical_block_size = None
        self.readonly = False
        self.snapshot = None
        self.backing_store = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestDisk, self).format_dom()

        dev.set("type", self.source_type)
        dev.set("device", self.source_device)
        if (self.driver_name is not None or
            self.driver_format is not None or
            self.driver_cache is not None or
                self.driver_discard is not None):
            drv = etree.Element("driver")
            if self.driver_name is not None:
                drv.set("name", self.driver_name)
            if self.driver_format is not None:
                drv.set("type", self.driver_format)
            if self.driver_cache is not None:
                drv.set("cache", self.driver_cache)
            if self.driver_discard is not None:
                drv.set("discard", self.driver_discard)
            dev.append(drv)

        if self.source_type == "file":
            dev.append(etree.Element("source", file=self.source_path))
        elif self.source_type == "block":
            dev.append(etree.Element("source", dev=self.source_path))
        elif self.source_type == "mount":
            dev.append(etree.Element("source", dir=self.source_path))
        elif self.source_type == "network":
            source = etree.Element("source", protocol=self.source_protocol)
            if self.source_name is not None:
                source.set('name', self.source_name)
            hosts_info = zip(self.source_hosts, self.source_ports)
            for name, port in hosts_info:
                host = etree.Element('host', name=name)
                if port is not None:
                    host.set('port', port)
                source.append(host)
            dev.append(source)

        if self.auth_secret_type is not None:
            auth = etree.Element("auth")
            auth.set("username", self.auth_username)
            auth.append(etree.Element("secret", type=self.auth_secret_type,
                                      uuid=self.auth_secret_uuid))
            dev.append(auth)

        if self.source_type == "mount":
            dev.append(etree.Element("target", dir=self.target_path))
        else:
            dev.append(etree.Element("target", dev=self.target_dev,
                                     bus=self.target_bus))

        if self.serial is not None:
            dev.append(self._text_node("serial", self.serial))

        iotune = etree.Element("iotune")

        if self.disk_read_bytes_sec is not None:
            iotune.append(self._text_node("read_bytes_sec",
                self.disk_read_bytes_sec))

        if self.disk_read_iops_sec is not None:
            iotune.append(self._text_node("read_iops_sec",
                self.disk_read_iops_sec))

        if self.disk_write_bytes_sec is not None:
            iotune.append(self._text_node("write_bytes_sec",
                self.disk_write_bytes_sec))

        if self.disk_write_iops_sec is not None:
            iotune.append(self._text_node("write_iops_sec",
                self.disk_write_iops_sec))

        if self.disk_total_bytes_sec is not None:
            iotune.append(self._text_node("total_bytes_sec",
                self.disk_total_bytes_sec))

        if self.disk_total_iops_sec is not None:
            iotune.append(self._text_node("total_iops_sec",
                self.disk_total_iops_sec))

        if len(iotune) > 0:
            dev.append(iotune)

        # Block size tuning
        if (self.logical_block_size is not None or
                self.physical_block_size is not None):

            blockio = etree.Element("blockio")
            if self.logical_block_size is not None:
                blockio.set('logical_block_size', self.logical_block_size)

            if self.physical_block_size is not None:
                blockio.set('physical_block_size', self.physical_block_size)

            dev.append(blockio)

        if self.readonly:
            dev.append(etree.Element("readonly"))

        return dev

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestDisk, self).parse_dom(xmldoc)

        self.source_type = xmldoc.get('type')
        self.snapshot = xmldoc.get('snapshot')

        for c in xmldoc.getchildren():
            if c.tag == 'driver':
                self.driver_name = c.get('name')
                self.driver_format = c.get('type')
                self.driver_cache = c.get('cache')
                self.driver_discard = c.get('discard')
            elif c.tag == 'source':
                if self.source_type == 'file':
                    self.source_path = c.get('file')
                elif self.source_type == 'block':
                    self.source_path = c.get('dev')
                elif self.source_type == 'mount':
                    self.source_path = c.get('dir')
                elif self.source_type == 'network':
                    self.source_protocol = c.get('protocol')
                    self.source_name = c.get('name')
                    for sub in c.getchildren():
                        if sub.tag == 'host':
                            self.source_hosts.append(sub.get('name'))
                            self.source_ports.append(sub.get('port'))

            elif c.tag == 'serial':
                self.serial = c.text
            elif c.tag == 'target':
                if self.source_type == 'mount':
                    self.target_path = c.get('dir')
                else:
                    self.target_dev = c.get('dev')

                self.target_bus = c.get('bus', None)
            elif c.tag == 'backingStore':
                b = LibvirtConfigGuestDiskBackingStore()
                b.parse_dom(c)
                self.backing_store = b


class LibvirtConfigGuestDiskBackingStore(LibvirtConfigObject):
    def __init__(self, **kwargs):
        super(LibvirtConfigGuestDiskBackingStore, self).__init__(
            root_name="backingStore", **kwargs)

        self.index = None
        self.source_type = None
        self.source_file = None
        self.source_protocol = None
        self.source_name = None
        self.source_hosts = []
        self.source_ports = []
        self.driver_name = None
        self.driver_format = None
        self.backing_store = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestDiskBackingStore, self).parse_dom(xmldoc)

        self.source_type = xmldoc.get('type')
        self.index = xmldoc.get('index')

        for c in xmldoc.getchildren():
            if c.tag == 'driver':
                self.driver_name = c.get('name')
                self.driver_format = c.get('type')
            elif c.tag == 'source':
                self.source_file = c.get('file')
                self.source_protocol = c.get('protocol')
                self.source_name = c.get('name')
                for d in c.getchildren():
                    if d.tag == 'host':
                        self.source_hosts.append(d.get('name'))
                        self.source_ports.append(d.get('port'))
            elif c.tag == 'backingStore':
                if c.getchildren():
                    self.backing_store = LibvirtConfigGuestDiskBackingStore()
                    self.backing_store.parse_dom(c)


class LibvirtConfigGuestSnapshotDisk(LibvirtConfigObject):
    """Disk class for handling disk information in snapshots.

    Similar to LibvirtConfigGuestDisk, but used to represent
    disk entities in <domainsnapshot> structures rather than
    real devices.  These typically have fewer members, and
    different expectations for which fields are required.
    """

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSnapshotDisk, self).__init__(root_name="disk",
                                                             **kwargs)

        self.source_type = None
        self.source_device = None
        self.name = None
        self.snapshot = None
        self.driver_name = None
        self.driver_format = None
        self.driver_cache = None
        self.source_path = None
        self.source_protocol = None
        self.source_name = None
        self.source_hosts = []
        self.source_ports = []
        self.target_dev = None
        self.target_path = None
        self.target_bus = None
        self.auth_username = None
        self.auth_secret_type = None
        self.auth_secret_uuid = None
        self.serial = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestSnapshotDisk, self).format_dom()

        if self.name:
            dev.attrib['name'] = self.name
        if self.snapshot:
            dev.attrib['snapshot'] = self.snapshot

        if self.source_type:
            dev.set("type", self.source_type)

        if self.source_device:
            dev.set("device", self.source_device)
            if (self.driver_name is not None or
                self.driver_format is not None or
                    self.driver_cache is not None):
                drv = etree.Element("driver")
                if self.driver_name is not None:
                    drv.set("name", self.driver_name)
                if self.driver_format is not None:
                    drv.set("type", self.driver_format)
                if self.driver_cache is not None:
                    drv.set("cache", self.driver_cache)
                dev.append(drv)

        if self.source_type == "file":
            dev.append(etree.Element("source", file=self.source_path))
        elif self.source_type == "block":
            dev.append(etree.Element("source", dev=self.source_path))
        elif self.source_type == "mount":
            dev.append(etree.Element("source", dir=self.source_path))
        elif self.source_type == "network":
            source = etree.Element("source", protocol=self.source_protocol)
            if self.source_name is not None:
                source.set('name', self.source_name)
            hosts_info = zip(self.source_hosts, self.source_ports)
            for name, port in hosts_info:
                host = etree.Element('host', name=name)
                if port is not None:
                    host.set('port', port)
                source.append(host)
            dev.append(source)

        if self.auth_secret_type is not None:
            auth = etree.Element("auth")
            auth.set("username", self.auth_username)
            auth.append(etree.Element("secret", type=self.auth_secret_type,
                                      uuid=self.auth_secret_uuid))
            dev.append(auth)

        if self.source_type == "mount":
            dev.append(etree.Element("target", dir=self.target_path))
        else:
            if self.target_bus and self.target_dev:
                dev.append(etree.Element("target", dev=self.target_dev,
                                         bus=self.target_bus))

        return dev

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestSnapshotDisk, self).parse_dom(xmldoc)

        self.source_type = xmldoc.get('type')
        self.snapshot = xmldoc.get('snapshot')

        for c in xmldoc.getchildren():
            if c.tag == 'driver':
                self.driver_name = c.get('name')
                self.driver_format = c.get('type')
                self.driver_cache = c.get('cache')
            elif c.tag == 'source':
                if self.source_type == 'file':
                    self.source_path = c.get('file')
                elif self.source_type == 'block':
                    self.source_path = c.get('dev')
                elif self.source_type == 'mount':
                    self.source_path = c.get('dir')
                elif self.source_type == 'network':
                    self.source_protocol = c.get('protocol')
                    self.source_name = c.get('name')
                    for sub in c.getchildren():
                        if sub.tag == 'host':
                            self.source_hosts.append(sub.get('name'))
                            self.source_ports.append(sub.get('port'))

            elif c.tag == 'serial':
                self.serial = c.text

        for c in xmldoc.getchildren():
            if c.tag == 'target':
                if self.source_type == 'mount':
                    self.target_path = c.get('dir')
                else:
                    self.target_dev = c.get('dev')

                self.target_bus = c.get('bus', None)


class LibvirtConfigGuestFilesys(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestFilesys, self).__init__(root_name="filesystem",
                                                        **kwargs)

        self.source_type = "mount"
        self.source_dir = None
        self.source_file = None
        self.source_dev = None
        self.target_dir = "/"
        self.driver_type = "loop"
        self.driver_format = "raw"

    def format_dom(self):
        dev = super(LibvirtConfigGuestFilesys, self).format_dom()

        dev.set("type", self.source_type)

        if self.source_type == "file":
            dev.append(etree.Element("driver", type = self.driver_type,
                                     format = self.driver_format))
            dev.append(etree.Element("source", file=self.source_file))
        elif self.source_type == "block":
            dev.append(etree.Element("source", dev=self.source_dev))
        else:
            dev.append(etree.Element("source", dir=self.source_dir))
        dev.append(etree.Element("target", dir=self.target_dir))

        return dev


class LibvirtConfigGuestIDMap(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestIDMap, self).__init__(**kwargs)
        self.start = 0
        self.target = 0
        self.count = 10000

    def parse_dom(self, xmldoc):
        self.start = int(xmldoc.get('start'))
        self.target = int(xmldoc.get('target'))
        self.count = int(xmldoc.get('count'))

    def format_dom(self):
        obj = super(LibvirtConfigGuestIDMap, self).format_dom()

        obj.set("start", str(self.start))
        obj.set("target", str(self.target))
        obj.set("count", str(self.count))

        return obj


class LibvirtConfigGuestUIDMap(LibvirtConfigGuestIDMap):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestUIDMap, self).__init__(root_name="uid",
                                                       **kwargs)


class LibvirtConfigGuestGIDMap(LibvirtConfigGuestIDMap):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestGIDMap, self).__init__(root_name="gid",
                                                       **kwargs)


class LibvirtConfigGuestInterface(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestInterface, self).__init__(
            root_name="interface",
            **kwargs)

        self.net_type = None
        self.target_dev = None
        self.model = None
        self.mac_addr = None
        self.script = None
        self.source_dev = None
        self.source_mode = "private"
        self.vporttype = None
        self.vportparams = []
        self.filtername = None
        self.filterparams = []
        self.driver_name = None
        self.vif_inbound_peak = None
        self.vif_inbound_burst = None
        self.vif_inbound_average = None
        self.vif_outbound_peak = None
        self.vif_outbound_burst = None
        self.vif_outbound_average = None
        self.vlan = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestInterface, self).format_dom()

        dev.set("type", self.net_type)
        if self.net_type == "hostdev":
            dev.set("managed", "yes")
        dev.append(etree.Element("mac", address=self.mac_addr))
        if self.model:
            dev.append(etree.Element("model", type=self.model))

        if self.driver_name:
            dev.append(etree.Element("driver", name=self.driver_name))

        if self.net_type == "ethernet":
            if self.script is not None:
                dev.append(etree.Element("script", path=self.script))
        elif self.net_type == "direct":
            dev.append(etree.Element("source", dev=self.source_dev,
                                     mode=self.source_mode))
        elif self.net_type == "hostdev":
            source_elem = etree.Element("source")
            domain, bus, slot, func = \
                pci_utils.get_pci_address_fields(self.source_dev)
            addr_elem = etree.Element("address", type='pci')
            addr_elem.set("domain", "0x%s" % (domain))
            addr_elem.set("bus", "0x%s" % (bus))
            addr_elem.set("slot", "0x%s" % (slot))
            addr_elem.set("function", "0x%s" % (func))
            source_elem.append(addr_elem)
            dev.append(source_elem)
        else:
            dev.append(etree.Element("source", bridge=self.source_dev))

        if self.vlan and self.net_type in ("direct", "hostdev"):
            vlan_elem = etree.Element("vlan")
            tag_elem = etree.Element("tag", id=self.vlan)
            vlan_elem.append(tag_elem)
            dev.append(vlan_elem)

        if self.target_dev is not None:
            dev.append(etree.Element("target", dev=self.target_dev))

        if self.vporttype is not None:
            vport = etree.Element("virtualport", type=self.vporttype)
            for p in self.vportparams:
                param = etree.Element("parameters")
                param.set(p['key'], p['value'])
                vport.append(param)
            dev.append(vport)

        if self.filtername is not None:
            filter = etree.Element("filterref", filter=self.filtername)
            for p in self.filterparams:
                filter.append(etree.Element("parameter",
                                            name=p['key'],
                                            value=p['value']))
            dev.append(filter)

        if self.vif_inbound_average or self.vif_outbound_average:
            bandwidth = etree.Element("bandwidth")
            if self.vif_inbound_average is not None:
                vif_inbound = etree.Element("inbound",
                average=str(self.vif_inbound_average))
                if self.vif_inbound_peak is not None:
                    vif_inbound.set("peak", str(self.vif_inbound_peak))
                if self.vif_inbound_burst is not None:
                    vif_inbound.set("burst", str(self.vif_inbound_burst))
                bandwidth.append(vif_inbound)

            if self.vif_outbound_average is not None:
                vif_outbound = etree.Element("outbound",
                average=str(self.vif_outbound_average))
                if self.vif_outbound_peak is not None:
                    vif_outbound.set("peak", str(self.vif_outbound_peak))
                if self.vif_outbound_burst is not None:
                    vif_outbound.set("burst", str(self.vif_outbound_burst))
                bandwidth.append(vif_outbound)
            dev.append(bandwidth)

        return dev

    def add_filter_param(self, key, value):
        self.filterparams.append({'key': key, 'value': value})

    def add_vport_param(self, key, value):
        self.vportparams.append({'key': key, 'value': value})


class LibvirtConfigGuestInput(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestInput, self).__init__(root_name="input",
                                                      **kwargs)

        self.type = "tablet"
        self.bus = "usb"

    def format_dom(self):
        dev = super(LibvirtConfigGuestInput, self).format_dom()

        dev.set("type", self.type)
        dev.set("bus", self.bus)

        return dev


class LibvirtConfigGuestGraphics(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestGraphics, self).__init__(root_name="graphics",
                                                         **kwargs)

        self.type = "vnc"
        self.autoport = True
        self.keymap = None
        self.listen = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestGraphics, self).format_dom()

        dev.set("type", self.type)
        if self.autoport:
            dev.set("autoport", "yes")
        else:
            dev.set("autoport", "no")
        if self.keymap:
            dev.set("keymap", self.keymap)
        if self.listen:
            dev.set("listen", self.listen)

        return dev


class LibvirtConfigSeclabel(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigSeclabel, self).__init__(root_name="seclabel",
                                                      **kwargs)
        self.type = 'dynamic'
        self.baselabel = None

    def format_dom(self):
        seclabel = super(LibvirtConfigSeclabel, self).format_dom()

        seclabel.set('type', self.type)
        if self.baselabel:
            seclabel.append(self._text_node("baselabel", self.baselabel))

        return seclabel


class LibvirtConfigGuestVideo(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestVideo, self).__init__(root_name="video",
                                                      **kwargs)

        self.type = 'cirrus'
        self.vram = None
        self.heads = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestVideo, self).format_dom()

        model = etree.Element("model")
        model.set("type", self.type)

        if self.vram:
            model.set("vram", str(self.vram))

        if self.heads:
            model.set("heads", str(self.heads))

        dev.append(model)

        return dev


class LibvirtConfigMemoryBalloon(LibvirtConfigGuestDevice):
    def __init__(self, **kwargs):
        super(LibvirtConfigMemoryBalloon, self).__init__(
            root_name='memballoon',
            **kwargs)
        self.model = None
        self.period = None

    def format_dom(self):
        dev = super(LibvirtConfigMemoryBalloon, self).format_dom()
        dev.set('model', str(self.model))
        if self.period is not None:
            dev.append(etree.Element('stats', period=str(self.period)))
        return dev


class LibvirtConfigGuestController(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestController,
              self).__init__(root_name="controller", **kwargs)

        self.type = None
        self.index = None
        self.model = None

    def format_dom(self):
        controller = super(LibvirtConfigGuestController, self).format_dom()
        controller.set("type", self.type)

        if self.index is not None:
            controller.set("index", str(self.index))

        if self.model:
            controller.set("model", str(self.model))

        return controller


class LibvirtConfigGuestHostdev(LibvirtConfigGuestDevice):
    def __init__(self, **kwargs):
        super(LibvirtConfigGuestHostdev, self).\
                __init__(root_name="hostdev", **kwargs)
        self.mode = kwargs.get('mode')
        self.type = kwargs.get('type')
        self.managed = 'yes'

    def format_dom(self):
        dev = super(LibvirtConfigGuestHostdev, self).format_dom()
        dev.set("mode", self.mode)
        dev.set("type", self.type)
        dev.set("managed", self.managed)
        return dev

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestHostdev, self).parse_dom(xmldoc)
        self.mode = xmldoc.get('mode')
        self.type = xmldoc.get('type')
        self.managed = xmldoc.get('managed')
        return xmldoc.getchildren()


class LibvirtConfigGuestHostdevPCI(LibvirtConfigGuestHostdev):
    def __init__(self, **kwargs):
        super(LibvirtConfigGuestHostdevPCI, self).\
                __init__(mode='subsystem', type='pci',
                         **kwargs)
        self.domain = None
        self.bus = None
        self.slot = None
        self.function = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestHostdevPCI, self).format_dom()

        address = etree.Element("address",
                                domain='0x' + self.domain,
                                bus='0x' + self.bus,
                                slot='0x' + self.slot,
                                function='0x' + self.function)
        source = etree.Element("source")
        source.append(address)
        dev.append(source)
        return dev

    def parse_dom(self, xmldoc):
        childs = super(LibvirtConfigGuestHostdevPCI, self).parse_dom(xmldoc)
        for c in childs:
            if c.tag == "source":
                for sub in c.getchildren():
                    if sub.tag == 'address':
                        self.domain = sub.get('domain')
                        self.bus = sub.get('bus')
                        self.slot = sub.get('slot')
                        self.function = sub.get('function')


class LibvirtConfigGuestCharBase(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCharBase, self).__init__(**kwargs)

        self.type = "pty"
        self.source_path = None
        self.listen_port = None
        self.listen_host = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestCharBase, self).format_dom()

        dev.set("type", self.type)

        if self.type == "file":
            dev.append(etree.Element("source", path=self.source_path))
        elif self.type == "unix":
            dev.append(etree.Element("source", mode="bind",
                                    path=self.source_path))
        elif self.type == "tcp":
            dev.append(etree.Element("source", mode="bind",
                                     host=self.listen_host,
                                     service=str(self.listen_port)))

        return dev


class LibvirtConfigGuestChar(LibvirtConfigGuestCharBase):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestChar, self).__init__(**kwargs)

        self.target_port = None
        self.target_type = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestChar, self).format_dom()

        if self.target_port is not None or self.target_type is not None:
            target = etree.Element("target")
            if self.target_port is not None:
                target.set("port", str(self.target_port))
            if self.target_type is not None:
                target.set("type", self.target_type)
            dev.append(target)

        return dev


class LibvirtConfigGuestSerial(LibvirtConfigGuestChar):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSerial, self).__init__(root_name="serial",
                                                       **kwargs)


class LibvirtConfigGuestConsole(LibvirtConfigGuestChar):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestConsole, self).__init__(root_name="console",
                                                        **kwargs)


class LibvirtConfigGuestChannel(LibvirtConfigGuestCharBase):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestChannel, self).__init__(root_name="channel",
                                                        **kwargs)

        self.target_type = "virtio"
        self.target_name = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestChannel, self).format_dom()

        target = etree.Element("target", type=self.target_type)
        if self.target_name is not None:
            target.set("name", self.target_name)
        dev.append(target)

        return dev


class LibvirtConfigGuestWatchdog(LibvirtConfigGuestDevice):
    def __init__(self, **kwargs):
        super(LibvirtConfigGuestWatchdog, self).__init__(root_name="watchdog",
                                                         **kwargs)

        self.model = 'i6300esb'
        self.action = 'reset'

    def format_dom(self):
        dev = super(LibvirtConfigGuestWatchdog, self).format_dom()

        dev.set('model', self.model)
        dev.set('action', self.action)

        return dev


class LibvirtConfigGuestCPUTuneVCPUPin(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPUTuneVCPUPin, self).__init__(
            root_name="vcpupin",
            **kwargs)

        self.id = None
        self.cpuset = None

    def format_dom(self):
        root = super(LibvirtConfigGuestCPUTuneVCPUPin, self).format_dom()

        root.set("vcpu", str(self.id))
        if self.cpuset is not None:
            root.set("cpuset",
                     hardware.format_cpu_spec(self.cpuset))

        return root


class LibvirtConfigGuestCPUTuneEmulatorPin(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPUTuneEmulatorPin, self).__init__(
            root_name="emulatorpin",
            **kwargs)

        self.cpuset = None

    def format_dom(self):
        root = super(LibvirtConfigGuestCPUTuneEmulatorPin, self).format_dom()

        if self.cpuset is not None:
            root.set("cpuset",
                     hardware.format_cpu_spec(self.cpuset))

        return root


class LibvirtConfigGuestCPUTune(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPUTune, self).__init__(root_name="cputune",
                                                        **kwargs)
        self.shares = None
        self.quota = None
        self.period = None
        self.vcpupin = []
        self.emulatorpin = None

    def format_dom(self):
        root = super(LibvirtConfigGuestCPUTune, self).format_dom()

        if self.shares is not None:
            root.append(self._text_node("shares", str(self.shares)))
        if self.quota is not None:
            root.append(self._text_node("quota", str(self.quota)))
        if self.period is not None:
            root.append(self._text_node("period", str(self.period)))

        if self.emulatorpin is not None:
            root.append(self.emulatorpin.format_dom())
        for vcpu in self.vcpupin:
            root.append(vcpu.format_dom())

        return root


class LibvirtConfigGuestMemoryBacking(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestMemoryBacking, self).__init__(
            root_name="memoryBacking", **kwargs)

        self.hugepages = []
        self.sharedpages = True
        self.locked = False

    def format_dom(self):
        root = super(LibvirtConfigGuestMemoryBacking, self).format_dom()

        if self.hugepages:
            hugepages = etree.Element("hugepages")
            for item in self.hugepages:
                hugepages.append(item.format_dom())
            root.append(hugepages)
        if not self.sharedpages:
            root.append(etree.Element("nosharedpages"))
        if self.locked:
            root.append(etree.Element("locked"))

        return root


class LibvirtConfigGuestMemoryBackingPage(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestMemoryBackingPage, self).__init__(
            root_name="page", **kwargs)

        self.size_kb = None
        self.nodeset = None

    def format_dom(self):
        page = super(LibvirtConfigGuestMemoryBackingPage, self).format_dom()

        page.set("size", str(self.size_kb))
        page.set("nodeset", hardware.format_cpu_spec(self.nodeset))
        page.set("unit", "KiB")

        return page


class LibvirtConfigGuestMemoryTune(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestMemoryTune, self).__init__(
            root_name="memtune", **kwargs)

        self.hard_limit = None
        self.soft_limit = None
        self.swap_hard_limit = None
        self.min_guarantee = None

    def format_dom(self):
        root = super(LibvirtConfigGuestMemoryTune, self).format_dom()

        if self.hard_limit is not None:
            root.append(self._text_node("hard_limit",
                                        str(self.hard_limit),
                                        units="K"))
        if self.soft_limit is not None:
            root.append(self._text_node("soft_limit",
                                        str(self.soft_limit),
                                        units="K"))
        if self.swap_hard_limit is not None:
            root.append(self._text_node("swap_hard_limit",
                                        str(self.swap_hard_limit),
                                        units="K"))
        if self.min_guarantee is not None:
            root.append(self._text_node("min_guarantee",
                                        str(self.min_guarantee),
                                        units="K"))

        return root


class LibvirtConfigGuestNUMATuneMemory(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestNUMATuneMemory, self).__init__(
            root_name="memory", **kwargs)

        self.mode = "strict"
        self.nodeset = []

    def format_dom(self):
        root = super(LibvirtConfigGuestNUMATuneMemory, self).format_dom()

        root.set("mode", self.mode)
        root.set("nodeset", hardware.format_cpu_spec(self.nodeset))

        return root


class LibvirtConfigGuestNUMATuneMemNode(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestNUMATuneMemNode, self).__init__(
            root_name="memnode", **kwargs)

        self.cellid = 0
        self.mode = "strict"
        self.nodeset = []

    def format_dom(self):
        root = super(LibvirtConfigGuestNUMATuneMemNode, self).format_dom()

        root.set("cellid", str(self.cellid))
        root.set("mode", self.mode)
        root.set("nodeset", hardware.format_cpu_spec(self.nodeset))

        return root


class LibvirtConfigGuestNUMATune(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestNUMATune, self).__init__(
            root_name="numatune", **kwargs)

        self.memory = None
        self.memnodes = []

    def format_dom(self):
        root = super(LibvirtConfigGuestNUMATune, self).format_dom()

        if self.memory is not None:
            root.append(self.memory.format_dom())
        for node in self.memnodes:
            root.append(node.format_dom())

        return root


class LibvirtConfigGuestFeature(LibvirtConfigObject):

    def __init__(self, name, **kwargs):
        super(LibvirtConfigGuestFeature, self).__init__(root_name=name,
                                                        **kwargs)


class LibvirtConfigGuestFeatureACPI(LibvirtConfigGuestFeature):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestFeatureACPI, self).__init__("acpi",
                                                            **kwargs)


class LibvirtConfigGuestFeatureAPIC(LibvirtConfigGuestFeature):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestFeatureAPIC, self).__init__("apic",
                                                            **kwargs)


class LibvirtConfigGuestFeaturePAE(LibvirtConfigGuestFeature):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestFeaturePAE, self).__init__("pae",
                                                           **kwargs)


class LibvirtConfigGuestFeatureHyperV(LibvirtConfigGuestFeature):

    # QEMU requires at least this value to be set
    MIN_SPINLOCK_RETRIES = 4095

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestFeatureHyperV, self).__init__("hyperv",
                                                              **kwargs)

        self.relaxed = False
        self.vapic = False
        self.spinlocks = False
        self.spinlock_retries = self.MIN_SPINLOCK_RETRIES

    def format_dom(self):
        root = super(LibvirtConfigGuestFeatureHyperV, self).format_dom()

        if self.relaxed:
            root.append(etree.Element("relaxed", state="on"))
        if self.vapic:
            root.append(etree.Element("vapic", state="on"))
        if self.spinlocks:
            root.append(etree.Element("spinlocks", state="on",
                                      retries=str(self.spinlock_retries)))

        return root


class LibvirtConfigGuest(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuest, self).__init__(root_name="domain",
                                                 **kwargs)

        self.virt_type = None
        self.uuid = None
        self.name = None
        self.memory = 500 * units.Mi
        self.membacking = None
        self.memtune = None
        self.numatune = None
        self.vcpus = 1
        self.cpuset = None
        self.cpu = None
        self.cputune = None
        self.features = []
        self.clock = None
        self.sysinfo = None
        self.os_type = None
        self.os_loader = None
        self.os_kernel = None
        self.os_initrd = None
        self.os_cmdline = None
        self.os_root = None
        self.os_init_path = None
        self.os_boot_dev = []
        self.os_smbios = None
        self.os_mach_type = None
        self.os_bootmenu = False
        self.devices = []
        self.metadata = []
        self.idmaps = []

    def _format_basic_props(self, root):
        root.append(self._text_node("uuid", self.uuid))
        root.append(self._text_node("name", self.name))
        root.append(self._text_node("memory", self.memory))
        if self.membacking is not None:
            root.append(self.membacking.format_dom())
        if self.memtune is not None:
            root.append(self.memtune.format_dom())
        if self.numatune is not None:
            root.append(self.numatune.format_dom())
        if self.cpuset is not None:
            vcpu = self._text_node("vcpu", self.vcpus)
            vcpu.set("cpuset", hardware.format_cpu_spec(self.cpuset))
            root.append(vcpu)
        else:
            root.append(self._text_node("vcpu", self.vcpus))

        if len(self.metadata) > 0:
            metadata = etree.Element("metadata")
            for m in self.metadata:
                metadata.append(m.format_dom())
            root.append(metadata)

    def _format_os(self, root):
        os = etree.Element("os")
        type_node = self._text_node("type", self.os_type)
        if self.os_mach_type is not None:
            type_node.set("machine", self.os_mach_type)
        os.append(type_node)
        if self.os_kernel is not None:
            os.append(self._text_node("kernel", self.os_kernel))
        if self.os_loader is not None:
            os.append(self._text_node("loader", self.os_loader))
        if self.os_initrd is not None:
            os.append(self._text_node("initrd", self.os_initrd))
        if self.os_cmdline is not None:
            os.append(self._text_node("cmdline", self.os_cmdline))
        if self.os_root is not None:
            os.append(self._text_node("root", self.os_root))
        if self.os_init_path is not None:
            os.append(self._text_node("init", self.os_init_path))

        for boot_dev in self.os_boot_dev:
            os.append(etree.Element("boot", dev=boot_dev))

        if self.os_smbios is not None:
            os.append(self.os_smbios.format_dom())

        if self.os_bootmenu:
            os.append(etree.Element("bootmenu", enable="yes"))
        root.append(os)

    def _format_features(self, root):
        if len(self.features) > 0:
            features = etree.Element("features")
            for feat in self.features:
                features.append(feat.format_dom())
            root.append(features)

    def _format_devices(self, root):
        if len(self.devices) == 0:
            return
        devices = etree.Element("devices")
        for dev in self.devices:
            devices.append(dev.format_dom())
        root.append(devices)

    def _format_idmaps(self, root):
        if len(self.idmaps) == 0:
            return
        idmaps = etree.Element("idmap")
        for idmap in self.idmaps:
            idmaps.append(idmap.format_dom())
        root.append(idmaps)

    def format_dom(self):
        root = super(LibvirtConfigGuest, self).format_dom()

        root.set("type", self.virt_type)

        self._format_basic_props(root)

        if self.sysinfo is not None:
            root.append(self.sysinfo.format_dom())

        self._format_os(root)
        self._format_features(root)

        if self.cputune is not None:
            root.append(self.cputune.format_dom())

        if self.clock is not None:
            root.append(self.clock.format_dom())

        if self.cpu is not None:
            root.append(self.cpu.format_dom())

        self._format_devices(root)

        self._format_idmaps(root)

        return root

    def parse_dom(self, xmldoc):
        # Note: This cover only for: LibvirtConfigGuestDisks
        #                            LibvirtConfigGuestHostdevPCI
        #                            LibvirtConfigGuestUidMap
        #                            LibvirtConfigGuestGidMap
        #                            LibvirtConfigGuestCPU
        for c in xmldoc.getchildren():
            if c.tag == 'devices':
                for d in c.getchildren():
                    if d.tag == 'disk':
                        obj = LibvirtConfigGuestDisk()
                        obj.parse_dom(d)
                        self.devices.append(obj)
                    elif d.tag == 'hostdev' and d.get('type') == 'pci':
                        obj = LibvirtConfigGuestHostdevPCI()
                        obj.parse_dom(d)
                        self.devices.append(obj)
            if c.tag == 'idmap':
                for map in c.getchildren():
                    obj = None
                    if map.tag == 'uid':
                        obj = LibvirtConfigGuestUIDMap()
                    elif map.tag == 'gid':
                        obj = LibvirtConfigGuestGIDMap()

                    if obj:
                        obj.parse_dom(map)
                        self.idmaps.append(obj)
            elif c.tag == 'cpu':
                obj = LibvirtConfigGuestCPU()
                obj.parse_dom(c)
                self.cpu = obj

    def add_device(self, dev):
        self.devices.append(dev)

    def set_clock(self, clk):
        self.clock = clk


class LibvirtConfigGuestSnapshot(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSnapshot, self).__init__(
            root_name="domainsnapshot",
            **kwargs)

        self.name = None
        self.disks = []

    def format_dom(self):
        ss = super(LibvirtConfigGuestSnapshot, self).format_dom()

        if self.name:
            ss.append(self._text_node("name", self.name))

        disks = etree.Element('disks')

        for disk in self.disks:
            disks.append(disk.format_dom())

        ss.append(disks)

        return ss

    def add_disk(self, disk):
        self.disks.append(disk)


class LibvirtConfigNodeDevice(LibvirtConfigObject):
    """Libvirt Node Devices parser."""

    def __init__(self, **kwargs):
        super(LibvirtConfigNodeDevice, self).__init__(root_name="device",
                                                **kwargs)
        self.name = None
        self.parent = None
        self.driver = None
        self.pci_capability = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigNodeDevice, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "name":
                self.name = c.text
            elif c.tag == "parent":
                self.parent = c.text
            elif c.tag == "capability" and c.get("type") == 'pci':
                pcicap = LibvirtConfigNodeDevicePciCap()
                pcicap.parse_dom(c)
                self.pci_capability = pcicap


class LibvirtConfigNodeDevicePciCap(LibvirtConfigObject):
    """Libvirt Node Devices pci capability parser."""

    def __init__(self, **kwargs):
        super(LibvirtConfigNodeDevicePciCap, self).__init__(
            root_name="capability", **kwargs)
        self.domain = None
        self.bus = None
        self.slot = None
        self.function = None
        self.product = None
        self.product_id = None
        self.vendor = None
        self.vendor_id = None
        self.numa_node = None
        self.fun_capability = list()

    def parse_dom(self, xmldoc):
        super(LibvirtConfigNodeDevicePciCap, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "domain":
                self.domain = int(c.text)
            elif c.tag == "slot":
                self.slot = int(c.text)
            elif c.tag == "bus":
                self.bus = int(c.text)
            elif c.tag == "function":
                self.function = int(c.text)
            elif c.tag == "product":
                self.product = c.text
                self.product_id = int(c.get('id'), 16)
            elif c.tag == "vendor":
                self.vendor = c.text
                self.vendor_id = int(c.get('id'), 16)
            elif c.tag == "numa":
                self.numa_node = int(c.get('node'))
            elif c.tag == "capability" and c.get('type') in \
                            ('virt_functions', 'phys_function'):
                funcap = LibvirtConfigNodeDevicePciSubFunctionCap()
                funcap.parse_dom(c)
                self.fun_capability.append(funcap)


class LibvirtConfigNodeDevicePciSubFunctionCap(LibvirtConfigObject):
    def __init__(self, **kwargs):
        super(LibvirtConfigNodeDevicePciSubFunctionCap, self).__init__(
                                        root_name="capability", **kwargs)
        self.type = None
        self.device_addrs = list()  # list of tuple (domain,bus,slot,function)

    def parse_dom(self, xmldoc):
        super(LibvirtConfigNodeDevicePciSubFunctionCap, self).parse_dom(xmldoc)
        self.type = xmldoc.get("type")
        for c in xmldoc.getchildren():
            if c.tag == "address":
                self.device_addrs.append((int(c.get('domain'), 16),
                                          int(c.get('bus'), 16),
                                          int(c.get('slot'), 16),
                                          int(c.get('function'), 16)))


class LibvirtConfigGuestRng(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestRng, self).__init__(root_name="rng",
                                                      **kwargs)

        self.model = 'random'
        self.backend = None
        self.rate_period = None
        self.rate_bytes = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestRng, self).format_dom()
        dev.set('model', 'virtio')

        backend = etree.Element("backend")
        backend.set("model", self.model)
        backend.text = self.backend

        if self.rate_period and self.rate_bytes:
            rate = etree.Element("rate")
            rate.set("period", str(self.rate_period))
            rate.set("bytes", str(self.rate_bytes))
            dev.append(rate)

        dev.append(backend)

        return dev


class LibvirtConfigGuestMetaNovaInstance(LibvirtConfigObject):

    def __init__(self):
        super(LibvirtConfigGuestMetaNovaInstance,
              self).__init__(root_name="instance",
                             ns_prefix="nova",
                             ns_uri=NOVA_NS)

        self.package = None
        self.flavor = None
        self.name = None
        self.creationTime = None
        self.owner = None
        self.roottype = None
        self.rootid = None

    def format_dom(self):
        meta = super(LibvirtConfigGuestMetaNovaInstance, self).format_dom()

        pkg = self._new_node("package")
        pkg.set("version", self.package)
        meta.append(pkg)
        if self.name is not None:
            meta.append(self._text_node("name", self.name))
        if self.creationTime is not None:
            timestr = time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.gmtime(self.creationTime))
            meta.append(self._text_node("creationTime", timestr))
        if self.flavor is not None:
            meta.append(self.flavor.format_dom())
        if self.owner is not None:
            meta.append(self.owner.format_dom())

        if self.roottype is not None and self.rootid is not None:
            root = self._new_node("root")
            root.set("type", self.roottype)
            root.set("uuid", str(self.rootid))
            meta.append(root)

        return meta


class LibvirtConfigGuestMetaNovaFlavor(LibvirtConfigObject):

    def __init__(self):
        super(LibvirtConfigGuestMetaNovaFlavor,
              self).__init__(root_name="flavor",
                             ns_prefix="nova",
                             ns_uri=NOVA_NS)

        self.name = None
        self.memory = None
        self.disk = None
        self.swap = None
        self.ephemeral = None
        self.vcpus = None

    def format_dom(self):
        meta = super(LibvirtConfigGuestMetaNovaFlavor, self).format_dom()
        meta.set("name", self.name)
        if self.memory is not None:
            meta.append(self._text_node("memory", str(self.memory)))
        if self.disk is not None:
            meta.append(self._text_node("disk", str(self.disk)))
        if self.swap is not None:
            meta.append(self._text_node("swap", str(self.swap)))
        if self.ephemeral is not None:
            meta.append(self._text_node("ephemeral", str(self.ephemeral)))
        if self.vcpus is not None:
            meta.append(self._text_node("vcpus", str(self.vcpus)))
        return meta


class LibvirtConfigGuestMetaNovaOwner(LibvirtConfigObject):

    def __init__(self):
        super(LibvirtConfigGuestMetaNovaOwner,
              self).__init__(root_name="owner",
                             ns_prefix="nova",
                             ns_uri=NOVA_NS)

        self.userid = None
        self.username = None
        self.projectid = None
        self.projectname = None

    def format_dom(self):
        meta = super(LibvirtConfigGuestMetaNovaOwner, self).format_dom()
        if self.userid is not None and self.username is not None:
            user = self._text_node("user", self.username)
            user.set("uuid", self.userid)
            meta.append(user)
        if self.projectid is not None and self.projectname is not None:
            project = self._text_node("project", self.projectname)
            project.set("uuid", self.projectid)
            meta.append(project)
        return meta


class LibvirtConfigSecret(LibvirtConfigObject):

    def __init__(self):
        super(LibvirtConfigSecret,
              self).__init__(root_name="secret")
        self.ephemeral = False
        self.private = False
        self.description = None
        self.uuid = None
        self.usage_type = None
        self.usage_id = None

    def get_yes_no_str(self, value):
        if value:
            return 'yes'
        return 'no'

    def format_dom(self):
        root = super(LibvirtConfigSecret, self).format_dom()
        root.set("ephemeral", self.get_yes_no_str(self.ephemeral))
        root.set("private", self.get_yes_no_str(self.private))
        if self.description is not None:
            root.append(self._text_node("description", str(self.description)))
        if self.uuid is not None:
            root.append(self._text_node("uuid", str(self.uuid)))
        usage = self._new_node("usage")
        usage.set("type", self.usage_type)
        if self.usage_type == 'ceph':
            usage.append(self._text_node('name', str(self.usage_id)))
        elif self.usage_type == 'iscsi':
            usage.append(self._text_node('target', str(self.usage_id)))
        elif self.usage_type == 'volume':
            usage.append(self._text_node('volume', str(self.usage_id)))
        root.append(usage)
        return root
