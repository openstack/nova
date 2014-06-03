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

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import units

from lxml import etree


LOG = logging.getLogger(__name__)


class LibvirtConfigObject(object):

    def __init__(self, **kwargs):
        super(LibvirtConfigObject, self).__init__()

        self.root_name = kwargs.get("root_name")
        self.ns_prefix = kwargs.get('ns_prefix')
        self.ns_uri = kwargs.get('ns_uri')

    @staticmethod
    def _text_node(name, value):
        child = etree.Element(name)
        child.text = str(value)
        return child

    def format_dom(self):
        if self.ns_uri is None:
            return etree.Element(self.root_name)
        else:
            return etree.Element("{" + self.ns_uri + "}" + self.root_name,
                                 nsmap={self.ns_prefix: self.ns_uri})

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
        LOG.debug(_("Generated XML %s "), (xml_str,))
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


class LibvirtConfigCapsHost(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCapsHost, self).__init__(root_name="host",
                                                    **kwargs)

        self.cpu = None
        self.uuid = None

    def parse_dom(self, xmldoc):
        super(LibvirtConfigCapsHost, self).parse_dom(xmldoc)

        for c in xmldoc.getchildren():
            if c.tag == "cpu":
                cpu = LibvirtConfigCPU()
                cpu.parse_dom(c)
                self.cpu = cpu
            elif c.tag == "uuid":
                self.uuid = c.text

    def format_dom(self):
        caps = super(LibvirtConfigCapsHost, self).format_dom()

        if self.uuid:
            caps.append(self._text_node("uuid", self.uuid))
        if self.cpu:
            caps.append(self.cpu.format_dom())

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


class LibvirtConfigGuestCPU(LibvirtConfigCPU):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestCPU, self).__init__(**kwargs)

        self.mode = None
        self.match = "exact"

    def parse_dom(self, xmldoc):
        super(LibvirtConfigGuestCPU, self).parse_dom(xmldoc)
        self.mode = xmldoc.get('mode')
        self.match = xmldoc.get('match')

    def format_dom(self):
        cpu = super(LibvirtConfigGuestCPU, self).format_dom()

        if self.mode:
            cpu.set("mode", self.mode)
        cpu.set("match", self.match)

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

    def format_dom(self):
        dev = super(LibvirtConfigGuestDisk, self).format_dom()

        dev.set("type", self.source_type)
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
            elif c.tag == 'serial':
                self.serial = c.text

        for c in xmldoc.getchildren():
            if c.tag == 'target':
                if self.source_type == 'mount':
                    self.target_path = c.get('dir')
                else:
                    self.target_dev = c.get('dev')

                self.target_bus = c.get('bus', None)


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
        self.target_dir = "/"

    def format_dom(self):
        dev = super(LibvirtConfigGuestFilesys, self).format_dom()

        dev.set("type", self.source_type)

        dev.append(etree.Element("source", dir=self.source_dir))
        dev.append(etree.Element("target", dir=self.target_dir))

        return dev


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

    def format_dom(self):
        dev = super(LibvirtConfigGuestInterface, self).format_dom()

        dev.set("type", self.net_type)
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
        else:
            dev.append(etree.Element("source", bridge=self.source_dev))

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

    def format_dom(self):
        dev = super(LibvirtConfigGuestCharBase, self).format_dom()

        dev.set("type", self.type)
        if self.type == "file":
            dev.append(etree.Element("source", path=self.source_path))
        elif self.type == "unix":
            dev.append(etree.Element("source", mode="bind",
                                    path=self.source_path))

        return dev


class LibvirtConfigGuestChar(LibvirtConfigGuestCharBase):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestChar, self).__init__(**kwargs)

        self.target_port = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestChar, self).format_dom()

        if self.target_port is not None:
            dev.append(etree.Element("target", port=str(self.target_port)))

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


class LibvirtConfigGuest(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuest, self).__init__(root_name="domain",
                                                 **kwargs)

        self.virt_type = None
        self.uuid = None
        self.name = None
        self.memory = 500 * units.Mi
        self.vcpus = 1
        self.cpuset = None
        self.cpu = None
        self.cpu_shares = None
        self.cpu_quota = None
        self.cpu_period = None
        self.acpi = False
        self.apic = False
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
        self.devices = []

    def _format_basic_props(self, root):
        root.append(self._text_node("uuid", self.uuid))
        root.append(self._text_node("name", self.name))
        root.append(self._text_node("memory", self.memory))
        if self.cpuset is not None:
            vcpu = self._text_node("vcpu", self.vcpus)
            vcpu.set("cpuset", self.cpuset)
            root.append(vcpu)
        else:
            root.append(self._text_node("vcpu", self.vcpus))

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
        root.append(os)

    def _format_features(self, root):
        if self.acpi or self.apic:
            features = etree.Element("features")
            if self.acpi:
                features.append(etree.Element("acpi"))
            if self.apic:
                features.append(etree.Element("apic"))
            root.append(features)

    def _format_cputune(self, root):
        cputune = etree.Element("cputune")
        if self.cpu_shares is not None:
            cputune.append(self._text_node("shares", self.cpu_shares))
        if self.cpu_quota is not None:
            cputune.append(self._text_node("quota", self.cpu_quota))
        if self.cpu_period is not None:
            cputune.append(self._text_node("period", self.cpu_period))
        if len(cputune) > 0:
            root.append(cputune)

    def _format_devices(self, root):
        if len(self.devices) == 0:
            return
        devices = etree.Element("devices")
        for dev in self.devices:
            devices.append(dev.format_dom())
        root.append(devices)

    def format_dom(self):
        root = super(LibvirtConfigGuest, self).format_dom()

        root.set("type", self.virt_type)

        self._format_basic_props(root)

        if self.sysinfo is not None:
            root.append(self.sysinfo.format_dom())

        self._format_os(root)
        self._format_features(root)
        self._format_cputune(root)

        if self.clock is not None:
            root.append(self.clock.format_dom())

        if self.cpu is not None:
            root.append(self.cpu.format_dom())

        self._format_devices(root)

        return root

    def parse_dom(self, xmldoc):
        # Note: This cover only for: LibvirtConfigGuestDisks
        #                            LibvirtConfigGuestHostdevPCI
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
    """Libvirt Node Devices parser"""

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
    """Libvirt Node Devices pci capability parser"""

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
                self.product_id = c.get('id')
            elif c.tag == "vendor":
                self.vendor = c.text
                self.vendor_id = c.get('id')
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
                self.device_addrs.append((c.get('domain'),
                                          c.get('bus'),
                                          c.get('slot'),
                                          c.get('function')))


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
