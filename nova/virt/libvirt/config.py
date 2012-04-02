# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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
and support conversion to/from XML
"""

from nova import log as logging

from lxml import etree


LOG = logging.getLogger(__name__)


class LibvirtConfigObject(object):

    def __init__(self, **kwargs):
        super(LibvirtConfigObject, self).__init__()

        self.root_name = kwargs.get("root_name")
        self.ns_prefix = kwargs.get('ns_prefix')
        self.ns_uri = kwargs.get('ns_uri')

        if "xml_str" in kwargs:
            self.parse_dom(kwargs.get("xml_str"))

    def _text_node(self, name, value):
        child = etree.Element(name)
        child.text = str(value)
        return child

    def format_dom(self):
        if self.ns_uri is None:
            return etree.Element(self.root_name)
        else:
            return etree.Element("{" + self.ns_uri + "}" + self.root_name,
                                 nsmap={self.ns_prefix: self.ns_uri})

    def parse_dom(xmldoc):
        raise NotImplementedError()

    def to_xml(self, pretty_print=True):
        root = self.format_dom()
        xml_str = etree.tostring(root, pretty_print=pretty_print)
        LOG.debug("Generated XML %s " % (xml_str,))
        return xml_str


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
        self.source_host = None
        self.target_dev = None
        self.target_path = None
        self.target_bus = None
        self.auth_username = None
        self.auth_secret_type = None
        self.auth_secret_uuid = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestDisk, self).format_dom()

        dev.set("type", self.source_type)
        dev.set("device", self.source_device)
        if self.driver_name is not None or \
                self.driver_format is not None or \
                self.driver_cache is not None:
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
            dev.append(etree.Element("source", protocol=self.source_protocol,
                                      name=self.source_host))

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

        return dev


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
        self.vporttype = None
        self.vportparams = []
        self.filtername = None
        self.filterparams = []

    def format_dom(self):
        dev = super(LibvirtConfigGuestInterface, self).format_dom()

        dev.set("type", self.net_type)
        dev.append(etree.Element("mac", address=self.mac_addr))
        if self.model:
            dev.append(etree.Element("model", type=self.model))
        if self.net_type == "ethernet":
            if self.script is not None:
                dev.append(etree.Element("script", path=self.script))
            dev.append(etree.Element("target", dev=self.target_dev))
        elif self.net_type == "direct":
            dev.append(etree.Element("source", dev=self.source_dev,
                                     mode="private"))
        else:
            dev.append(etree.Element("source", bridge=self.source_dev))

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


class LibvirtConfigGuestChar(LibvirtConfigGuestDevice):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestChar, self).__init__(**kwargs)

        self.type = "pty"
        self.source_path = None
        self.target_port = None

    def format_dom(self):
        dev = super(LibvirtConfigGuestChar, self).format_dom()

        dev.set("type", self.type)
        if self.type == "file":
            dev.append(etree.Element("source", path=self.source_path))
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


class LibvirtConfigGuest(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuest, self).__init__(root_name="domain",
                                                 **kwargs)

        self.virt_type = None
        self.uuid = None
        self.name = None
        self.memory = 1024 * 1024 * 500
        self.vcpus = 1
        self.acpi = False
        self.os_type = None
        self.os_kernel = None
        self.os_initrd = None
        self.os_cmdline = None
        self.os_root = None
        self.os_init_path = None
        self.os_boot_dev = None
        self.devices = []

    def _format_basic_props(self, root):
        root.append(self._text_node("uuid", self.uuid))
        root.append(self._text_node("name", self.name))
        root.append(self._text_node("memory", self.memory))
        root.append(self._text_node("vcpu", self.vcpus))

    def _format_os(self, root):
        os = etree.Element("os")
        os.append(self._text_node("type", self.os_type))
        if self.os_kernel is not None:
            os.append(self._text_node("kernel", self.os_kernel))
        if self.os_initrd is not None:
            os.append(self._text_node("initrd", self.os_initrd))
        if self.os_cmdline is not None:
            os.append(self._text_node("cmdline", self.os_cmdline))
        if self.os_root is not None:
            os.append(self._text_node("root", self.os_root))
        if self.os_init_path is not None:
            os.append(self._text_node("init", self.os_init_path))
        if self.os_boot_dev is not None:
            os.append(etree.Element("boot", dev=self.os_boot_dev))
        root.append(os)

    def _format_features(self, root):
        if self.acpi:
            features = etree.Element("features")
            features.append(etree.Element("acpi"))
            root.append(features)

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
        self._format_os(root)
        self._format_features(root)
        self._format_devices(root)

        return root

    def add_device(self, dev):
        self.devices.append(dev)


class LibvirtConfigCPU(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigCPU, self).__init__(root_name="cpu",
                                               **kwargs)

        self.arch = None
        self.model = None
        self.vendor = None
        self.sockets = None
        self.cores = None
        self.threads = None
        self.features = []

    def add_feature(self, name):
        self.features.append(name)

    def format_dom(self):
        cpu = super(LibvirtConfigCPU, self).format_dom()
        if self.arch:
            cpu.append(self._text_node("arch", self.arch))
        if self.model:
            cpu.append(self._text_node("model", self.model))
        if self.vendor:
            cpu.append(self._text_node("vendor", self.vendor))
        if (self.sockets is not None and
            self.cores is not None and
            self.threads is not None):
            cpu.append(etree.Element("topology",
                                     sockets=str(self.sockets),
                                     cores=str(self.cores),
                                     threads=str(self.threads)))

        for f in self.features:
            cpu.append(etree.Element("feature",
                                     name=f))

        return cpu


class LibvirtConfigGuestSnapshot(LibvirtConfigObject):

    def __init__(self, **kwargs):
        super(LibvirtConfigGuestSnapshot, self).__init__(
            root_name="domainsnapshot",
            **kwargs)

        self.name = None

    def format_dom(self):
        ss = super(LibvirtConfigGuestSnapshot, self).format_dom()
        ss.append(self._text_node("name", self.name))
        return ss
