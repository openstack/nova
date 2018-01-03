#    Copyright 2010 OpenStack Foundation
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

import sys
import time

import fixtures
from lxml import etree

from nova.objects import fields as obj_fields
from nova.tests import uuidsentinel as uuids
from nova.virt.libvirt import config as vconfig

# Allow passing None to the various connect methods
# (i.e. allow the client to rely on default URLs)
allow_default_uri_connection = True

# Has libvirt connection been used at least once
connection_used = False


def _reset():
    global allow_default_uri_connection
    allow_default_uri_connection = True

# virDomainState
VIR_DOMAIN_NOSTATE = 0
VIR_DOMAIN_RUNNING = 1
VIR_DOMAIN_BLOCKED = 2
VIR_DOMAIN_PAUSED = 3
VIR_DOMAIN_SHUTDOWN = 4
VIR_DOMAIN_SHUTOFF = 5
VIR_DOMAIN_CRASHED = 6

# NOTE(mriedem): These values come from include/libvirt/libvirt-domain.h
VIR_DOMAIN_XML_SECURE = 1
VIR_DOMAIN_XML_INACTIVE = 2
VIR_DOMAIN_XML_UPDATE_CPU = 4
VIR_DOMAIN_XML_MIGRATABLE = 8

VIR_DOMAIN_BLOCK_REBASE_SHALLOW = 1
VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT = 2
VIR_DOMAIN_BLOCK_REBASE_COPY = 8
VIR_DOMAIN_BLOCK_REBASE_COPY_DEV = 32

VIR_DOMAIN_BLOCK_JOB_ABORT_ASYNC = 1
VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT = 2

VIR_DOMAIN_EVENT_ID_LIFECYCLE = 0

VIR_DOMAIN_EVENT_DEFINED = 0
VIR_DOMAIN_EVENT_UNDEFINED = 1
VIR_DOMAIN_EVENT_STARTED = 2
VIR_DOMAIN_EVENT_SUSPENDED = 3
VIR_DOMAIN_EVENT_RESUMED = 4
VIR_DOMAIN_EVENT_STOPPED = 5
VIR_DOMAIN_EVENT_SHUTDOWN = 6
VIR_DOMAIN_EVENT_PMSUSPENDED = 7

VIR_DOMAIN_UNDEFINE_MANAGED_SAVE = 1
VIR_DOMAIN_UNDEFINE_NVRAM = 4

VIR_DOMAIN_AFFECT_CURRENT = 0
VIR_DOMAIN_AFFECT_LIVE = 1
VIR_DOMAIN_AFFECT_CONFIG = 2

VIR_CPU_COMPARE_ERROR = -1
VIR_CPU_COMPARE_INCOMPATIBLE = 0
VIR_CPU_COMPARE_IDENTICAL = 1
VIR_CPU_COMPARE_SUPERSET = 2

VIR_CRED_USERNAME = 1
VIR_CRED_AUTHNAME = 2
VIR_CRED_LANGUAGE = 3
VIR_CRED_CNONCE = 4
VIR_CRED_PASSPHRASE = 5
VIR_CRED_ECHOPROMPT = 6
VIR_CRED_NOECHOPROMPT = 7
VIR_CRED_REALM = 8
VIR_CRED_EXTERNAL = 9

VIR_MIGRATE_LIVE = 1
VIR_MIGRATE_PEER2PEER = 2
VIR_MIGRATE_TUNNELLED = 4
VIR_MIGRATE_PERSIST_DEST = 8
VIR_MIGRATE_UNDEFINE_SOURCE = 16
VIR_MIGRATE_NON_SHARED_INC = 128
VIR_MIGRATE_AUTO_CONVERGE = 8192
VIR_MIGRATE_POSTCOPY = 32768

VIR_NODE_CPU_STATS_ALL_CPUS = -1

VIR_DOMAIN_START_PAUSED = 1

# libvirtError enums
# (Intentionally different from what's in libvirt. We do this to check,
#  that consumers of the library are using the symbolic names rather than
#  hardcoding the numerical values)
VIR_FROM_QEMU = 100
VIR_FROM_DOMAIN = 200
VIR_FROM_NWFILTER = 330
VIR_FROM_REMOTE = 340
VIR_FROM_RPC = 345
VIR_FROM_NODEDEV = 666
VIR_ERR_INVALID_ARG = 8
VIR_ERR_NO_SUPPORT = 3
VIR_ERR_XML_DETAIL = 350
VIR_ERR_NO_DOMAIN = 420
VIR_ERR_OPERATION_FAILED = 510
VIR_ERR_OPERATION_INVALID = 55
VIR_ERR_OPERATION_TIMEOUT = 68
VIR_ERR_NO_NWFILTER = 620
VIR_ERR_SYSTEM_ERROR = 900
VIR_ERR_INTERNAL_ERROR = 950
VIR_ERR_CONFIG_UNSUPPORTED = 951
VIR_ERR_NO_NODE_DEVICE = 667
VIR_ERR_NO_SECRET = 66
VIR_ERR_AGENT_UNRESPONSIVE = 86
VIR_ERR_ARGUMENT_UNSUPPORTED = 74
# Readonly
VIR_CONNECT_RO = 1

# virConnectBaselineCPU flags
VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES = 1

# snapshotCreateXML flags
VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA = 4
VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY = 16
VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT = 32
VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE = 64

# blockCommit flags
VIR_DOMAIN_BLOCK_COMMIT_RELATIVE = 4
# blockRebase flags
VIR_DOMAIN_BLOCK_REBASE_RELATIVE = 8


VIR_CONNECT_LIST_DOMAINS_ACTIVE = 1
VIR_CONNECT_LIST_DOMAINS_INACTIVE = 2

# secret type
VIR_SECRET_USAGE_TYPE_NONE = 0
VIR_SECRET_USAGE_TYPE_VOLUME = 1
VIR_SECRET_USAGE_TYPE_CEPH = 2
VIR_SECRET_USAGE_TYPE_ISCSI = 3

# Libvirt version to match MIN_LIBVIRT_VERSION in driver.py
FAKE_LIBVIRT_VERSION = 1002009
# Libvirt version to match MIN_QEMU_VERSION in driver.py
FAKE_QEMU_VERSION = 2001000

PF_CAP_TYPE = 'virt_functions'
VF_CAP_TYPE = 'phys_function'
PF_PROD_NAME = 'Ethernet Controller 10-Gigabit X540-AT2'
VF_PROD_NAME = 'X540 Ethernet Controller Virtual Function'
PF_DRIVER_NAME = 'ixgbe'
VF_DRIVER_NAME = 'ixgbevf'
VF_SLOT = '10'
PF_SLOT = '00'


class FakePciDevice(object):
    pci_dev_template = """<device>
  <name>pci_0000_81_%(slot)02x_%(dev)d</name>
  <path>/sys/devices/pci0000:80/0000:80:01.0/0000:81:%(slot)02x.%(dev)d</path>
  <parent>pci_0000_80_01_0</parent>
  <driver>
    <name>%(driver)s</name>
  </driver>
  <capability type='pci'>
    <domain>0</domain>
    <bus>129</bus>
    <slot>%(slot)d</slot>
    <function>%(dev)d</function>
    <product id='0x%(prod)d'>%(prod_name)s</product>
    <vendor id='0x8086'>Intel Corporation</vendor>
    <capability type='%(cap_type)s'>
    %(functions)s
    </capability>
    <iommuGroup number='%(group_id)d'>
 <address domain='0x0000' bus='0x81' slot='%(slot)#02x' function='0x%(dev)d'/>
    </iommuGroup>
    <numa node='%(numa_node)s'/>
    <pci-express>
      <link validity='cap' port='0' speed='5' width='8'/>
      <link validity='sta' speed='5' width='8'/>
    </pci-express>
  </capability>
</device>"""

    def __init__(self, dev_type, vf_ratio, group, dev, product_id, numa_node):
        """Populate pci devices

        :param dev_type: (string) Indicates the type of the device (PF, VF)
        :param vf_ratio: (int) Ratio of Virtual Functions on Physical
        :param group: (int) iommu group id
        :param dev: (int) function number of the device
        :param product_id: (int) Device product ID
        :param numa_node: (int) NUMA node of the device
        """
        addr_templ = ("  <address domain='0x0000' bus='0x81' slot='0x%(slot)s'"
                      " function='0x%(dev)d'/>")
        self.pci_dev = None

        if dev_type == 'PF':
            pf_caps = [addr_templ % {'dev': x, 'slot': VF_SLOT}
                                     for x in range(dev * vf_ratio,
                                                    (dev + 1) * vf_ratio)]
            slot = int(str(PF_SLOT), 16)
            self.pci_dev = self.pci_dev_template % {'dev': dev,
                         'prod': product_id, 'group_id': group,
                         'functions': '\n'.join(pf_caps), 'slot': slot,
                         'cap_type': PF_CAP_TYPE, 'prod_name': PF_PROD_NAME,
                         'driver': PF_DRIVER_NAME, 'numa_node': numa_node}
        elif dev_type == 'VF':
            vf_caps = [addr_templ % {'dev': int(dev / vf_ratio),
                                     'slot': PF_SLOT}]
            slot = int(str(VF_SLOT), 16)
            self.pci_dev = self.pci_dev_template % {'dev': dev,
                         'prod': product_id, 'group_id': group,
                         'functions': '\n'.join(vf_caps), 'slot': slot,
                         'cap_type': VF_CAP_TYPE, 'prod_name': VF_PROD_NAME,
                         'driver': VF_DRIVER_NAME, 'numa_node': numa_node}

    def XMLDesc(self, flags):
        return self.pci_dev


class HostPciSRIOVDevicesInfo(object):
    """Represent a pool of host SR-IOV devices."""

    def __init__(self, vf_product_id=1515, pf_product_id=1528, num_pfs=2,
                 num_vfs=8, group=47, numa_node=None, total_numa_nodes=2):
        """Create a new HostPciSRIOVDevicesInfo object.

        :param vf_product_id: (int) Product ID of the Virtual Functions
        :param pf_product_id=1528: (int) Product ID of the Physical Functions
        :param num_pfs: (int) The number of the Physical Functions
        :param num_vfs: (int) The number of the Virtual Functions
        :param group: (int) Initial group id
        :param numa_node: (int) NUMA node of the device, if set all of the
                          device will be created in the provided node
        :param total_numa_nodes: (int) total number of NUMA nodes
        """
        def _calc_numa_node(dev):
            return dev % total_numa_nodes if numa_node is None else numa_node

        self.devices = {}
        if num_vfs and not num_pfs:
            raise ValueError('Cannot create VFs without PFs')

        vf_ratio = num_vfs // num_pfs if num_pfs else 0

        # Generate PFs
        for dev in range(num_pfs):
            dev_group = group + dev + 1
            pci_dev_name = 'pci_0000_81_%(slot)s_%(dev)d' % {'slot': PF_SLOT,
                                                             'dev': dev}
            self.devices[pci_dev_name] = FakePciDevice('PF', vf_ratio,
                                                       dev_group, dev,
                                                       pf_product_id,
                                                       _calc_numa_node(dev))

        # Generate VFs
        for dev in range(num_vfs):
            dev_group = group + dev + 1
            pci_dev_name = 'pci_0000_81_%(slot)s_%(dev)d' % {'slot': VF_SLOT,
                                                             'dev': dev}
            self.devices[pci_dev_name] = FakePciDevice('VF', vf_ratio,
                                                       dev_group, dev,
                                                       vf_product_id,
                                                       _calc_numa_node(dev))

    def get_all_devices(self):
        return self.devices.keys()

    def get_device_by_name(self, device_name):
        pci_dev = self.devices.get(device_name)
        return pci_dev


class HostInfo(object):

    def __init__(self, arch=obj_fields.Architecture.X86_64, kB_mem=4096,
                 cpus=2, cpu_mhz=800, cpu_nodes=1,
                 cpu_sockets=1, cpu_cores=2,
                 cpu_threads=1, cpu_model="Penryn",
                 cpu_vendor="Intel", numa_topology='',
                 cpu_disabled=None):
        """Create a new Host Info object

        :param arch: (string) indicating the CPU arch
                     (eg 'i686' or whatever else uname -m might return)
        :param kB_mem: (int) memory size in KBytes
        :param cpus: (int) the number of active CPUs
        :param cpu_mhz: (int) expected CPU frequency
        :param cpu_nodes: (int) the number of NUMA cell, 1 for unusual
                          NUMA topologies or uniform
        :param cpu_sockets: (int) number of CPU sockets per node if nodes > 1,
                            total number of CPU sockets otherwise
        :param cpu_cores: (int) number of cores per socket
        :param cpu_threads: (int) number of threads per core
        :param cpu_model: CPU model
        :param cpu_vendor: CPU vendor
        :param numa_topology: Numa topology
        :param cpu_disabled: List of disabled cpus
        """

        self.arch = arch
        self.kB_mem = kB_mem
        self.cpus = cpus
        self.cpu_mhz = cpu_mhz
        self.cpu_nodes = cpu_nodes
        self.cpu_cores = cpu_cores
        self.cpu_threads = cpu_threads
        self.cpu_sockets = cpu_sockets
        self.cpu_model = cpu_model
        self.cpu_vendor = cpu_vendor
        self.numa_topology = numa_topology
        self.disabled_cpus_list = cpu_disabled or []


class NUMAHostInfo(HostInfo):
    """A NUMA-by-default variant of HostInfo."""

    def __init__(self, **kwargs):
        super(NUMAHostInfo, self).__init__(**kwargs)

        if not self.numa_topology:
            topology = NUMATopology(self.cpu_nodes, self.cpu_sockets,
                                    self.cpu_cores, self.cpu_threads,
                                    self.kB_mem)
            self.numa_topology = topology

            # update number of active cpus
            cpu_count = len(topology.cells) * len(topology.cells[0].cpus)
            self.cpus = cpu_count - len(self.disabled_cpus_list)


class NUMATopology(vconfig.LibvirtConfigCapsNUMATopology):
    """A batteries-included variant of LibvirtConfigCapsNUMATopology.

    Provides sane defaults for LibvirtConfigCapsNUMATopology that can be used
    in tests as is, or overridden where necessary.
    """

    def __init__(self, cpu_nodes=4, cpu_sockets=1, cpu_cores=1, cpu_threads=2,
                 kb_mem=1048576, mempages=None, **kwargs):

        super(NUMATopology, self).__init__(**kwargs)

        cpu_count = 0
        for cell_count in range(cpu_nodes):
            cell = vconfig.LibvirtConfigCapsNUMACell()
            cell.id = cell_count
            cell.memory = kb_mem // cpu_nodes
            for socket_count in range(cpu_sockets):
                for cpu_num in range(cpu_cores * cpu_threads):
                    cpu = vconfig.LibvirtConfigCapsNUMACPU()
                    cpu.id = cpu_count
                    cpu.socket_id = cell_count
                    cpu.core_id = cpu_num // cpu_threads
                    cpu.siblings = set([cpu_threads *
                                       (cpu_count // cpu_threads) + thread
                                        for thread in range(cpu_threads)])
                    cell.cpus.append(cpu)

                    cpu_count += 1

            # If no mempages are provided, use only the default 4K pages
            if mempages:
                cell.mempages = mempages[cell_count]
            else:
                cell.mempages = create_mempages([(4, cell.memory // 4)])

            self.cells.append(cell)


def create_mempages(mappings):
    """Generate a list of LibvirtConfigCapsNUMAPages objects.

    :param mappings: (dict) A mapping of page size to quantity of
        said pages.
    :returns: [LibvirtConfigCapsNUMAPages, ...]
    """
    mempages = []

    for page_size, page_qty in mappings:
        mempage = vconfig.LibvirtConfigCapsNUMAPages()
        mempage.size = page_size
        mempage.total = page_qty
        mempages.append(mempage)

    return mempages


VIR_DOMAIN_JOB_NONE = 0
VIR_DOMAIN_JOB_BOUNDED = 1
VIR_DOMAIN_JOB_UNBOUNDED = 2
VIR_DOMAIN_JOB_COMPLETED = 3
VIR_DOMAIN_JOB_FAILED = 4
VIR_DOMAIN_JOB_CANCELLED = 5


def _parse_disk_info(element):
    disk_info = {}
    disk_info['type'] = element.get('type', 'file')
    disk_info['device'] = element.get('device', 'disk')

    driver = element.find('./driver')
    if driver is not None:
        disk_info['driver_name'] = driver.get('name')
        disk_info['driver_type'] = driver.get('type')

    source = element.find('./source')
    if source is not None:
        disk_info['source'] = source.get('file')
        if not disk_info['source']:
            disk_info['source'] = source.get('dev')

        if not disk_info['source']:
            disk_info['source'] = source.get('path')

    target = element.find('./target')
    if target is not None:
        disk_info['target_dev'] = target.get('dev')
        disk_info['target_bus'] = target.get('bus')

    return disk_info


def disable_event_thread(self):
    """Disable nova libvirt driver event thread.

    The Nova libvirt driver includes a native thread which monitors
    the libvirt event channel. In a testing environment this becomes
    problematic because it means we've got a floating thread calling
    sleep(1) over the life of the unit test. Seems harmless? It's not,
    because we sometimes want to test things like retry loops that
    should have specific sleep paterns. An unlucky firing of the
    libvirt thread will cause a test failure.

    """
    # because we are patching a method in a class MonkeyPatch doesn't
    # auto import correctly. Import explicitly otherwise the patching
    # may silently fail.
    import nova.virt.libvirt.host  # noqa

    def evloop(*args, **kwargs):
        pass

    self.useFixture(fixtures.MonkeyPatch(
        'nova.virt.libvirt.host.Host._init_events',
        evloop))


class libvirtError(Exception):
    """This class was copied and slightly modified from
    `libvirt-python:libvirt-override.py`.

    Since a test environment will use the real `libvirt-python` version of
    `libvirtError` if it's installed and not this fake, we need to maintain
    strict compatibility with the original class, including `__init__` args
    and instance-attributes.

    To create a libvirtError instance you should:

        # Create an unsupported error exception
        exc = libvirtError('my message')
        exc.err = (libvirt.VIR_ERR_NO_SUPPORT,)

    self.err is a tuple of form:
        (error_code, error_domain, error_message, error_level, str1, str2,
         str3, int1, int2)

    Alternatively, you can use the `make_libvirtError` convenience function to
    allow you to specify these attributes in one shot.
    """
    def __init__(self, defmsg, conn=None, dom=None, net=None, pool=None,
                 vol=None):
        Exception.__init__(self, defmsg)
        self.err = None

    def get_error_code(self):
        if self.err is None:
            return None
        return self.err[0]

    def get_error_domain(self):
        if self.err is None:
            return None
        return self.err[1]

    def get_error_message(self):
        if self.err is None:
            return None
        return self.err[2]

    def get_error_level(self):
        if self.err is None:
            return None
        return self.err[3]

    def get_str1(self):
        if self.err is None:
            return None
        return self.err[4]

    def get_str2(self):
        if self.err is None:
            return None
        return self.err[5]

    def get_str3(self):
        if self.err is None:
            return None
        return self.err[6]

    def get_int1(self):
        if self.err is None:
            return None
        return self.err[7]

    def get_int2(self):
        if self.err is None:
            return None
        return self.err[8]


class NWFilter(object):
    def __init__(self, connection, xml):
        self._connection = connection

        self._xml = xml
        self._parse_xml(xml)

    def _parse_xml(self, xml):
        tree = etree.fromstring(xml)
        root = tree.find('.')
        self._name = root.get('name')

    def undefine(self):
        self._connection._remove_filter(self)


class NodeDevice(object):

    def __init__(self, connection, xml=None):
        self._connection = connection

        self._xml = xml
        if xml is not None:
            self._parse_xml(xml)

    def _parse_xml(self, xml):
        tree = etree.fromstring(xml)
        root = tree.find('.')
        self._name = root.get('name')

    def attach(self):
        pass

    def dettach(self):
        pass

    def reset(self):
        pass


class Domain(object):
    def __init__(self, connection, xml, running=False, transient=False):
        self._connection = connection
        if running:
            connection._mark_running(self)

        self._state = running and VIR_DOMAIN_RUNNING or VIR_DOMAIN_SHUTOFF
        self._transient = transient
        self._def = self._parse_definition(xml)
        self._has_saved_state = False
        self._snapshots = {}
        self._id = self._connection._id_counter

    def _parse_definition(self, xml):
        try:
            tree = etree.fromstring(xml)
        except etree.ParseError:
            raise make_libvirtError(
                    libvirtError, "Invalid XML.",
                    error_code=VIR_ERR_XML_DETAIL,
                    error_domain=VIR_FROM_DOMAIN)

        definition = {}

        name = tree.find('./name')
        if name is not None:
            definition['name'] = name.text

        uuid_elem = tree.find('./uuid')
        if uuid_elem is not None:
            definition['uuid'] = uuid_elem.text
        else:
            definition['uuid'] = uuids.fake

        vcpu = tree.find('./vcpu')
        if vcpu is not None:
            definition['vcpu'] = int(vcpu.text)

        memory = tree.find('./memory')
        if memory is not None:
            definition['memory'] = int(memory.text)

        os = {}
        os_type = tree.find('./os/type')
        if os_type is not None:
            os['type'] = os_type.text
            os['arch'] = os_type.get('arch', self._connection.host_info.arch)

        os_kernel = tree.find('./os/kernel')
        if os_kernel is not None:
            os['kernel'] = os_kernel.text

        os_initrd = tree.find('./os/initrd')
        if os_initrd is not None:
            os['initrd'] = os_initrd.text

        os_cmdline = tree.find('./os/cmdline')
        if os_cmdline is not None:
            os['cmdline'] = os_cmdline.text

        os_boot = tree.find('./os/boot')
        if os_boot is not None:
            os['boot_dev'] = os_boot.get('dev')

        definition['os'] = os

        features = {}

        acpi = tree.find('./features/acpi')
        if acpi is not None:
            features['acpi'] = True

        definition['features'] = features

        devices = {}

        device_nodes = tree.find('./devices')
        if device_nodes is not None:
            disks_info = []
            disks = device_nodes.findall('./disk')
            for disk in disks:
                disks_info += [_parse_disk_info(disk)]
            devices['disks'] = disks_info

            nics_info = []
            nics = device_nodes.findall('./interface')
            for nic in nics:
                nic_info = {}
                nic_info['type'] = nic.get('type')

                mac = nic.find('./mac')
                if mac is not None:
                    nic_info['mac'] = mac.get('address')

                source = nic.find('./source')
                if source is not None:
                    if nic_info['type'] == 'network':
                        nic_info['source'] = source.get('network')
                    elif nic_info['type'] == 'bridge':
                        nic_info['source'] = source.get('bridge')

                nics_info += [nic_info]

            devices['nics'] = nics_info

        definition['devices'] = devices

        return definition

    def create(self):
        self.createWithFlags(0)

    def createWithFlags(self, flags):
        # FIXME: Not handling flags at the moment
        self._state = VIR_DOMAIN_RUNNING
        self._connection._mark_running(self)
        self._has_saved_state = False

    def isActive(self):
        return int(self._state == VIR_DOMAIN_RUNNING)

    def undefine(self):
        self._connection._undefine(self)

    def isPersistent(self):
        return True

    def undefineFlags(self, flags):
        self.undefine()
        if flags & VIR_DOMAIN_UNDEFINE_MANAGED_SAVE:
            if self.hasManagedSaveImage(0):
                self.managedSaveRemove()

    def destroy(self):
        self._state = VIR_DOMAIN_SHUTOFF
        self._connection._mark_not_running(self)

    def ID(self):
        return self._id

    def name(self):
        return self._def['name']

    def UUIDString(self):
        return self._def['uuid']

    def interfaceStats(self, device):
        return [10000242400, 1234, 0, 2, 213412343233, 34214234, 23, 3]

    def blockStats(self, device):
        return [2, 10000242400, 234, 2343424234, 34]

    def setTime(self, time=None, flags=0):
        pass

    def suspend(self):
        self._state = VIR_DOMAIN_PAUSED

    def shutdown(self):
        self._state = VIR_DOMAIN_SHUTDOWN
        self._connection._mark_not_running(self)

    def reset(self, flags):
        # FIXME: Not handling flags at the moment
        self._state = VIR_DOMAIN_RUNNING
        self._connection._mark_running(self)

    def info(self):
        return [self._state,
                int(self._def['memory']),
                int(self._def['memory']),
                self._def['vcpu'],
                123456789]

    def migrateToURI(self, desturi, flags, dname, bandwidth):
        raise make_libvirtError(
                libvirtError,
                "Migration always fails for fake libvirt!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)

    def migrateToURI2(self, dconnuri, miguri, dxml, flags, dname, bandwidth):
        raise make_libvirtError(
                libvirtError,
                "Migration always fails for fake libvirt!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)

    def migrateToURI3(self, dconnuri, params, logical_sum):
        raise make_libvirtError(
                libvirtError,
                "Migration always fails for fake libvirt!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)

    def migrateSetMaxDowntime(self, downtime):
        pass

    def migrateSetMaxSpeed(self, bandwidth):
        pass

    def attachDevice(self, xml):
        disk_info = _parse_disk_info(etree.fromstring(xml))
        disk_info['_attached'] = True
        self._def['devices']['disks'] += [disk_info]
        return True

    def attachDeviceFlags(self, xml, flags):
        if (flags & VIR_DOMAIN_AFFECT_LIVE and
                self._state != VIR_DOMAIN_RUNNING):
            raise make_libvirtError(
                libvirtError,
                "AFFECT_LIVE only allowed for running domains!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)
        self.attachDevice(xml)

    def detachDevice(self, xml):
        disk_info = _parse_disk_info(etree.fromstring(xml))
        disk_info['_attached'] = True
        return disk_info in self._def['devices']['disks']

    def detachDeviceFlags(self, xml, flags):
        self.detachDevice(xml)

    def setUserPassword(self, user, password, flags=0):
        pass

    def XMLDesc(self, flags):
        disks = ''
        for disk in self._def['devices']['disks']:
            if disk['type'] == 'file':
                source_attr = 'file'
            else:
                source_attr = 'dev'

            disks += '''<disk type='%(type)s' device='%(device)s'>
      <driver name='%(driver_name)s' type='%(driver_type)s'/>
      <source %(source_attr)s='%(source)s'/>
      <target dev='%(target_dev)s' bus='%(target_bus)s'/>
      <address type='drive' controller='0' bus='0' unit='0'/>
    </disk>''' % dict(source_attr=source_attr, **disk)

        nics = ''
        for nic in self._def['devices']['nics']:
            nics += '''<interface type='%(type)s'>
      <mac address='%(mac)s'/>
      <source %(type)s='%(source)s'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x03'
               function='0x0'/>
    </interface>''' % nic

        return '''<domain type='kvm'>
  <name>%(name)s</name>
  <uuid>%(uuid)s</uuid>
  <memory>%(memory)s</memory>
  <currentMemory>%(memory)s</currentMemory>
  <vcpu>%(vcpu)s</vcpu>
  <os>
    <type arch='%(arch)s' machine='pc-0.12'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <clock offset='localtime'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <emulator>/usr/bin/kvm</emulator>
    %(disks)s
    <controller type='ide' index='0'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x01'
               function='0x1'/>
    </controller>
    %(nics)s
    <serial type='file'>
      <source path='dummy.log'/>
      <target port='0'/>
    </serial>
    <serial type='pty'>
      <source pty='/dev/pts/27'/>
      <target port='1'/>
    </serial>
    <serial type='tcp'>
      <source host="-1" service="-1" mode="bind"/>
    </serial>
    <console type='file'>
      <source path='dummy.log'/>
      <target port='0'/>
    </console>
    <input type='tablet' bus='usb'/>
    <input type='mouse' bus='ps2'/>
    <graphics type='vnc' port='-1' autoport='yes'/>
    <graphics type='spice' port='-1' autoport='yes'/>
    <video>
      <model type='cirrus' vram='9216' heads='1'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x02'
               function='0x0'/>
    </video>
    <memballoon model='virtio'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
               function='0x0'/>
    </memballoon>
  </devices>
</domain>''' % {'name': self._def['name'],
                'uuid': self._def['uuid'],
                'memory': self._def['memory'],
                'vcpu': self._def['vcpu'],
                'arch': self._def['os']['arch'],
                'disks': disks,
                'nics': nics}

    def managedSave(self, flags):
        self._connection._mark_not_running(self)
        self._has_saved_state = True

    def managedSaveRemove(self, flags):
        self._has_saved_state = False

    def hasManagedSaveImage(self, flags):
        return int(self._has_saved_state)

    def resume(self):
        self._state = VIR_DOMAIN_RUNNING

    def snapshotCreateXML(self, xml, flags):
        tree = etree.fromstring(xml)
        name = tree.find('./name').text
        snapshot = DomainSnapshot(name, self)
        self._snapshots[name] = snapshot
        return snapshot

    def vcpus(self):
        vcpus = ([], [])
        for i in range(0, self._def['vcpu']):
            vcpus[0].append((i, 1, 120405, i))
            vcpus[1].append((True, True, True, True))
        return vcpus

    def memoryStats(self):
        return {}

    def maxMemory(self):
        return self._def['memory']

    def blockJobInfo(self, disk, flags):
        return {}

    def blockJobAbort(self, disk, flags):
        pass

    def blockResize(self, disk, size):
        pass

    def blockRebase(self, disk, base, bandwidth=0, flags=0):
        if (not base) and (flags and VIR_DOMAIN_BLOCK_REBASE_RELATIVE):
            raise make_libvirtError(
                    libvirtError,
                    'flag VIR_DOMAIN_BLOCK_REBASE_RELATIVE is '
                    'valid only with non-null base',
                    error_code=VIR_ERR_INVALID_ARG,
                    error_domain=VIR_FROM_QEMU)
        return 0

    def blockCommit(self, disk, base, top, flags):
        return 0

    def jobInfo(self):
        # NOTE(danms): This is an array of 12 integers, so just report
        # something to avoid an IndexError if we look at this
        return [0] * 12

    def jobStats(self, flags=0):
        return {}

    def injectNMI(self, flags=0):
        return 0

    def abortJob(self):
        pass

    def fsFreeze(self):
        pass

    def fsThaw(self):
        pass


class DomainSnapshot(object):
    def __init__(self, name, domain):
        self._name = name
        self._domain = domain

    def delete(self, flags):
        del self._domain._snapshots[self._name]


class Connection(object):
    def __init__(self, uri=None, readonly=False, version=FAKE_LIBVIRT_VERSION,
                 hv_version=FAKE_QEMU_VERSION, host_info=None, pci_info=None):
        if not uri or uri == '':
            if allow_default_uri_connection:
                uri = 'qemu:///session'
            else:
                raise ValueError("URI was None, but fake libvirt is "
                                 "configured to not accept this.")

        uri_whitelist = ['qemu:///system',
                         'qemu:///session',
                         'lxc:///',     # from LibvirtDriver._uri()
                         'xen:///',     # from LibvirtDriver._uri()
                         'uml:///system',
                         'test:///default',
                         'parallels:///system']

        if uri not in uri_whitelist:
            raise make_libvirtError(
                    libvirtError,
                   "libvirt error: no connection driver "
                   "available for No connection for URI %s" % uri,
                   error_code=5, error_domain=0)

        self.readonly = readonly
        self._uri = uri
        self._vms = {}
        self._running_vms = {}
        self._id_counter = 1  # libvirt reserves 0 for the hypervisor.
        self._nwfilters = {}
        self._nodedevs = {}
        self._event_callbacks = {}
        self.fakeLibVersion = version
        self.fakeVersion = hv_version
        self.host_info = host_info or HostInfo()
        self.pci_info = pci_info or HostPciSRIOVDevicesInfo(num_pfs=0,
                                                            num_vfs=0)

    def _add_filter(self, nwfilter):
        self._nwfilters[nwfilter._name] = nwfilter

    def _remove_filter(self, nwfilter):
        del self._nwfilters[nwfilter._name]

    def _add_nodedev(self, nodedev):
        self._nodedevs[nodedev._name] = nodedev

    def _remove_nodedev(self, nodedev):
        del self._nodedevs[nodedev._name]

    def _mark_running(self, dom):
        self._running_vms[self._id_counter] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STARTED, 0)
        self._id_counter += 1

    def _mark_not_running(self, dom):
        if dom._transient:
            self._undefine(dom)

        dom._id = -1

        for (k, v) in self._running_vms.items():
            if v == dom:
                del self._running_vms[k]
                self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STOPPED, 0)
                return

    def _undefine(self, dom):
        del self._vms[dom.name()]
        if not dom._transient:
            self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_UNDEFINED, 0)

    def getInfo(self):
        return [self.host_info.arch,
                self.host_info.kB_mem,
                self.host_info.cpus,
                self.host_info.cpu_mhz,
                self.host_info.cpu_nodes,
                self.host_info.cpu_sockets,
                self.host_info.cpu_cores,
                self.host_info.cpu_threads]

    def lookupByUUIDString(self, uuid):
        for vm in self._vms.values():
            if vm.UUIDString() == uuid:
                return vm
        raise make_libvirtError(
                libvirtError,
                'Domain not found: no domain with matching uuid "%s"' % uuid,
                error_code=VIR_ERR_NO_DOMAIN,
                error_domain=VIR_FROM_QEMU)

    def listAllDomains(self, flags=None):
        vms = []
        for vm in self._vms.values():
            if flags & VIR_CONNECT_LIST_DOMAINS_ACTIVE:
                if vm._state != VIR_DOMAIN_SHUTOFF:
                    vms.append(vm)
            if flags & VIR_CONNECT_LIST_DOMAINS_INACTIVE:
                if vm._state == VIR_DOMAIN_SHUTOFF:
                    vms.append(vm)
        return vms

    def _emit_lifecycle(self, dom, event, detail):
        if VIR_DOMAIN_EVENT_ID_LIFECYCLE not in self._event_callbacks:
            return

        cbinfo = self._event_callbacks[VIR_DOMAIN_EVENT_ID_LIFECYCLE]
        callback = cbinfo[0]
        opaque = cbinfo[1]
        callback(self, dom, event, detail, opaque)

    def defineXML(self, xml):
        dom = Domain(connection=self, running=False, transient=False, xml=xml)
        self._vms[dom.name()] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_DEFINED, 0)
        return dom

    def createXML(self, xml, flags):
        dom = Domain(connection=self, running=True, transient=True, xml=xml)
        self._vms[dom.name()] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STARTED, 0)
        return dom

    def getType(self):
        if self._uri == 'qemu:///system':
            return 'QEMU'

    def getLibVersion(self):
        return self.fakeLibVersion

    def getVersion(self):
        return self.fakeVersion

    def getHostname(self):
        return 'compute1'

    def domainEventRegisterAny(self, dom, eventid, callback, opaque):
        self._event_callbacks[eventid] = [callback, opaque]

    def registerCloseCallback(self, cb, opaque):
        pass

    def getCPUMap(self):
        """Return calculated CPU map from HostInfo, by default showing 2
           online CPUs.
        """
        active_cpus = self.host_info.cpus
        total_cpus = active_cpus + len(self.host_info.disabled_cpus_list)
        cpu_map = [True if cpu_num not in self.host_info.disabled_cpus_list
                   else False for cpu_num in range(total_cpus)]
        return (total_cpus, cpu_map, active_cpus)

    def getCapabilities(self):
        """Return spoofed capabilities."""
        numa_topology = self.host_info.numa_topology
        if isinstance(numa_topology, vconfig.LibvirtConfigCapsNUMATopology):
            numa_topology = numa_topology.to_xml()

        return '''<capabilities>
  <host>
    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
    <cpu>
      <arch>x86_64</arch>
      <model>Penryn</model>
      <vendor>Intel</vendor>
      <topology sockets='%(sockets)s' cores='%(cores)s' threads='%(threads)s'/>
      <feature name='xtpr'/>
      <feature name='tm2'/>
      <feature name='est'/>
      <feature name='vmx'/>
      <feature name='ds_cpl'/>
      <feature name='monitor'/>
      <feature name='pbe'/>
      <feature name='tm'/>
      <feature name='ht'/>
      <feature name='ss'/>
      <feature name='acpi'/>
      <feature name='ds'/>
      <feature name='vme'/>
    </cpu>
    <migration_features>
      <live/>
      <uri_transports>
        <uri_transport>tcp</uri_transport>
      </uri_transports>
    </migration_features>
    %(topology)s
    <secmodel>
      <model>apparmor</model>
      <doi>0</doi>
    </secmodel>
  </host>

  <guest>
    <os_type>hvm</os_type>
    <arch name='i686'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu</emulator>
      <machine>pc-0.14</machine>
      <machine canonical='pc-0.14'>pc</machine>
      <machine>pc-0.13</machine>
      <machine>pc-0.12</machine>
      <machine>pc-0.11</machine>
      <machine>pc-0.10</machine>
      <machine>isapc</machine>
      <domain type='qemu'>
      </domain>
      <domain type='kvm'>
        <emulator>/usr/bin/kvm</emulator>
        <machine>pc-0.14</machine>
        <machine canonical='pc-0.14'>pc</machine>
        <machine>pc-0.13</machine>
        <machine>pc-0.12</machine>
        <machine>pc-0.11</machine>
        <machine>pc-0.10</machine>
        <machine>isapc</machine>
      </domain>
    </arch>
    <features>
      <cpuselection/>
      <deviceboot/>
      <pae/>
      <nonpae/>
      <acpi default='on' toggle='yes'/>
      <apic default='on' toggle='no'/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='x86_64'>
      <wordsize>64</wordsize>
      <emulator>/usr/bin/qemu-system-x86_64</emulator>
      <machine>pc-0.14</machine>
      <machine canonical='pc-0.14'>pc</machine>
      <machine>pc-0.13</machine>
      <machine>pc-0.12</machine>
      <machine>pc-0.11</machine>
      <machine>pc-0.10</machine>
      <machine>isapc</machine>
      <domain type='qemu'>
      </domain>
      <domain type='kvm'>
        <emulator>/usr/bin/kvm</emulator>
        <machine>pc-0.14</machine>
        <machine canonical='pc-0.14'>pc</machine>
        <machine>pc-0.13</machine>
        <machine>pc-0.12</machine>
        <machine>pc-0.11</machine>
        <machine>pc-0.10</machine>
        <machine>isapc</machine>
      </domain>
    </arch>
    <features>
      <cpuselection/>
      <deviceboot/>
      <acpi default='on' toggle='yes'/>
      <apic default='on' toggle='no'/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='armv7l'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-arm</emulator>
      <machine>integratorcp</machine>
      <machine>vexpress-a9</machine>
      <machine>syborg</machine>
      <machine>musicpal</machine>
      <machine>mainstone</machine>
      <machine>n800</machine>
      <machine>n810</machine>
      <machine>n900</machine>
      <machine>cheetah</machine>
      <machine>sx1</machine>
      <machine>sx1-v1</machine>
      <machine>beagle</machine>
      <machine>beaglexm</machine>
      <machine>tosa</machine>
      <machine>akita</machine>
      <machine>spitz</machine>
      <machine>borzoi</machine>
      <machine>terrier</machine>
      <machine>connex</machine>
      <machine>verdex</machine>
      <machine>lm3s811evb</machine>
      <machine>lm3s6965evb</machine>
      <machine>realview-eb</machine>
      <machine>realview-eb-mpcore</machine>
      <machine>realview-pb-a8</machine>
      <machine>realview-pbx-a9</machine>
      <machine>versatilepb</machine>
      <machine>versatileab</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='mips'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-mips</emulator>
      <machine>malta</machine>
      <machine>mipssim</machine>
      <machine>magnum</machine>
      <machine>pica61</machine>
      <machine>mips</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='mipsel'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-mipsel</emulator>
      <machine>malta</machine>
      <machine>mipssim</machine>
      <machine>magnum</machine>
      <machine>pica61</machine>
      <machine>mips</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='sparc'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-sparc</emulator>
      <machine>SS-5</machine>
      <machine>leon3_generic</machine>
      <machine>SS-10</machine>
      <machine>SS-600MP</machine>
      <machine>SS-20</machine>
      <machine>Voyager</machine>
      <machine>LX</machine>
      <machine>SS-4</machine>
      <machine>SPARCClassic</machine>
      <machine>SPARCbook</machine>
      <machine>SS-1000</machine>
      <machine>SS-2000</machine>
      <machine>SS-2</machine>
      <domain type='qemu'>
      </domain>
    </arch>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='ppc'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-ppc</emulator>
      <machine>g3beige</machine>
      <machine>virtex-ml507</machine>
      <machine>mpc8544ds</machine>
      <machine canonical='bamboo-0.13'>bamboo</machine>
      <machine>bamboo-0.13</machine>
      <machine>bamboo-0.12</machine>
      <machine>ref405ep</machine>
      <machine>taihu</machine>
      <machine>mac99</machine>
      <machine>prep</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

</capabilities>''' % {'sockets': self.host_info.cpu_sockets,
                      'cores': self.host_info.cpu_cores,
                      'threads': self.host_info.cpu_threads,
                      'topology': numa_topology}

    def compareCPU(self, xml, flags):
        tree = etree.fromstring(xml)

        arch_node = tree.find('./arch')
        if arch_node is not None:
            if arch_node.text not in [obj_fields.Architecture.X86_64,
                                      obj_fields.Architecture.I686]:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        model_node = tree.find('./model')
        if model_node is not None:
            if model_node.text != self.host_info.cpu_model:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        vendor_node = tree.find('./vendor')
        if vendor_node is not None:
            if vendor_node.text != self.host_info.cpu_vendor:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        # The rest of the stuff libvirt implements is rather complicated
        # and I don't think it adds much value to replicate it here.

        return VIR_CPU_COMPARE_IDENTICAL

    def getCPUStats(self, cpuNum, flag):
        if cpuNum < 2:
            return {'kernel': 5664160000000,
                    'idle': 1592705190000000,
                    'user': 26728850000000,
                    'iowait': 6121490000000}
        else:
            raise make_libvirtError(
                    libvirtError,
                    "invalid argument: Invalid cpu number",
                    error_code=VIR_ERR_INTERNAL_ERROR,
                    error_domain=VIR_FROM_QEMU)

    def nwfilterLookupByName(self, name):
        try:
            return self._nwfilters[name]
        except KeyError:
            raise make_libvirtError(
                    libvirtError,
                    "no nwfilter with matching name %s" % name,
                    error_code=VIR_ERR_NO_NWFILTER,
                    error_domain=VIR_FROM_NWFILTER)

    def nwfilterDefineXML(self, xml):
        nwfilter = NWFilter(self, xml)
        self._add_filter(nwfilter)

    def device_lookup_by_name(self, dev_name):
        return self.pci_info.get_device_by_name(dev_name)

    def nodeDeviceLookupByName(self, name):
        pci_dev = self.pci_info.get_device_by_name(name)
        if pci_dev:
            return pci_dev
        try:
            return self._nodedevs[name]
        except KeyError:
            raise make_libvirtError(
                    libvirtError,
                    "no nodedev with matching name %s" % name,
                    error_code=VIR_ERR_NO_NODE_DEVICE,
                    error_domain=VIR_FROM_NODEDEV)

    def listDevices(self, cap, flags):
        return self.pci_info.get_all_devices()

    def baselineCPU(self, cpu, flag):
        """Add new libvirt API."""
        return """<cpu mode='custom' match='exact'>
                    <model>Penryn</model>
                    <vendor>Intel</vendor>
                    <feature name='xtpr'/>
                    <feature name='tm2'/>
                    <feature name='est'/>
                    <feature name='vmx'/>
                    <feature name='ds_cpl'/>
                    <feature name='monitor'/>
                    <feature name='pbe'/>
                    <feature name='tm'/>
                    <feature name='ht'/>
                    <feature name='ss'/>
                    <feature name='acpi'/>
                    <feature name='ds'/>
                    <feature name='vme'/>
                    <feature policy='require' name='aes'/>
                  </cpu>"""

    def secretLookupByUsage(self, usage_type_obj, usage_id):
        pass

    def secretDefineXML(self, xml):
        pass


def openAuth(uri, auth, flags=0):

    if type(auth) != list:
        raise Exception("Expected a list for 'auth' parameter")

    if type(auth[0]) != list:
        raise Exception("Expected a function in 'auth[0]' parameter")

    if not callable(auth[1]):
        raise Exception("Expected a function in 'auth[1]' parameter")

    return Connection(uri, (flags == VIR_CONNECT_RO))


def virEventRunDefaultImpl():
    time.sleep(1)


def virEventRegisterDefaultImpl():
    if connection_used:
        raise Exception("virEventRegisterDefaultImpl() must be "
                        "called before connection is used.")


def registerErrorHandler(handler, ctxt):
    pass


def make_libvirtError(error_class, msg, error_code=None,
                       error_domain=None, error_message=None,
                       error_level=None, str1=None, str2=None, str3=None,
                       int1=None, int2=None):
    """Convenience function for creating `libvirtError` exceptions which
    allow you to specify arguments in constructor without having to manipulate
    the `err` tuple directly.

    We need to pass in `error_class` to this function because it may be
    `libvirt.libvirtError` or `fakelibvirt.libvirtError` depending on whether
    `libvirt-python` is installed.
    """
    exc = error_class(msg)
    exc.err = (error_code, error_domain, error_message, error_level,
               str1, str2, str3, int1, int2)
    return exc


virDomain = Domain
virNodeDevice = NodeDevice

virConnect = Connection


class FakeLibvirtFixture(fixtures.Fixture):
    """Performs global setup/stubbing for all libvirt tests.
    """
    def __init__(self, stub_os_vif=True):
        self.stub_os_vif = stub_os_vif

    def setUp(self):
        super(FakeLibvirtFixture, self).setUp()

        # Some modules load the libvirt library in a strange way
        for module in ('driver', 'host', 'guest', 'firewall', 'migration'):
            i = 'nova.virt.libvirt.{module}.libvirt'.format(module=module)
            # NOTE(mdbooth): The strange incantation below means 'this module'
            self.useFixture(fixtures.MonkeyPatch(i, sys.modules[__name__]))

        disable_event_thread(self)

        if self.stub_os_vif:
            # Make sure to never try and actually plug VIFs in os-vif unless
            # we're explicitly testing that code and the test itself will
            # handle the appropriate mocking.
            self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.libvirt.vif.LibvirtGenericVIFDriver._plug_os_vif',
                lambda *a, **kw: None))
