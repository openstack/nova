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

import collections
import os
import sys
import textwrap
import time
import typing as ty

import fixtures
from lxml import etree
import mock
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import versionutils

from nova import conf
from nova.objects import fields as obj_fields
from nova.tests.fixtures import libvirt_data as fake_libvirt_data
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import driver as libvirt_driver


# Allow passing None to the various connect methods
# (i.e. allow the client to rely on default URLs)
allow_default_uri_connection = True

# Has libvirt connection been used at least once
connection_used = False


def _reset():
    global allow_default_uri_connection
    allow_default_uri_connection = True


LOG = logging.getLogger(__name__)
CONF = conf.CONF

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

VIR_DOMAIN_BLOCK_COPY_SHALLOW = 1
VIR_DOMAIN_BLOCK_COPY_REUSE_EXT = 2
VIR_DOMAIN_BLOCK_COPY_TRANSIENT_JOB = 4

VIR_DOMAIN_BLOCK_REBASE_SHALLOW = 1
VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT = 2
VIR_DOMAIN_BLOCK_REBASE_COPY = 8
VIR_DOMAIN_BLOCK_REBASE_RELATIVE = 16
VIR_DOMAIN_BLOCK_REBASE_COPY_DEV = 32

# virDomainBlockResize
VIR_DOMAIN_BLOCK_RESIZE_BYTES = 1

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

VIR_DOMAIN_EVENT_ID_DEVICE_REMOVED = 15
VIR_DOMAIN_EVENT_ID_DEVICE_REMOVAL_FAILED = 22

VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED = 1
VIR_DOMAIN_EVENT_SUSPENDED_POSTCOPY = 7

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
VIR_MIGRATE_TLS = 65536

VIR_NODE_CPU_STATS_ALL_CPUS = -1

VIR_DOMAIN_START_PAUSED = 1

# libvirtError enums
# (Intentionally different from what's in libvirt. We do this to check,
#  that consumers of the library are using the symbolic names rather than
#  hardcoding the numerical values)
VIR_FROM_QEMU = 100
VIR_FROM_DOMAIN = 200
VIR_FROM_SECRET = 300
VIR_FROM_NWFILTER = 330
VIR_FROM_REMOTE = 340
VIR_FROM_RPC = 345
VIR_FROM_NODEDEV = 666

VIR_ERR_INVALID_ARG = 8
VIR_ERR_NO_SUPPORT = 3
VIR_ERR_XML_ERROR = 27
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
VIR_ERR_INVALID_SECRET = 65
VIR_ERR_NO_SECRET = 66
VIR_ERR_AGENT_UNRESPONSIVE = 86
VIR_ERR_ARGUMENT_UNSUPPORTED = 74
VIR_ERR_OPERATION_UNSUPPORTED = 84
VIR_ERR_DEVICE_MISSING = 99
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


VIR_CONNECT_LIST_DOMAINS_ACTIVE = 1
VIR_CONNECT_LIST_DOMAINS_INACTIVE = 2

# virConnectListAllNodeDevices flags
VIR_CONNECT_LIST_NODE_DEVICES_CAP_PCI_DEV = 2
VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET = 1 << 4
VIR_CONNECT_LIST_NODE_DEVICES_CAP_VDPA = 1 << 17

# secret type
VIR_SECRET_USAGE_TYPE_NONE = 0
VIR_SECRET_USAGE_TYPE_VOLUME = 1
VIR_SECRET_USAGE_TYPE_CEPH = 2
VIR_SECRET_USAGE_TYPE_ISCSI = 3

# metadata types
VIR_DOMAIN_METADATA_DESCRIPTION = 0
VIR_DOMAIN_METADATA_TITLE = 1
VIR_DOMAIN_METADATA_ELEMENT = 2

# Libvirt version to match MIN_LIBVIRT_VERSION in driver.py
FAKE_LIBVIRT_VERSION = versionutils.convert_version_to_int(
    libvirt_driver.MIN_LIBVIRT_VERSION)
# Libvirt version to match MIN_QEMU_VERSION in driver.py
FAKE_QEMU_VERSION = versionutils.convert_version_to_int(
    libvirt_driver.MIN_QEMU_VERSION)

PCI_VEND_ID = '8086'
PCI_VEND_NAME = 'Intel Corporation'

PCI_PROD_ID = '1533'
PCI_PROD_NAME = 'I210 Gigabit Network Connection'
PCI_DRIVER_NAME = 'igb'

PF_PROD_ID = '1528'
PF_PROD_NAME = 'Ethernet Controller 10-Gigabit X540-AT2'
PF_DRIVER_NAME = 'ixgbe'
PF_CAP_TYPE = 'virt_functions'

VF_PROD_ID = '1515'
VF_PROD_NAME = 'X540 Ethernet Controller Virtual Function'
VF_DRIVER_NAME = 'ixgbevf'
VF_CAP_TYPE = 'phys_function'

MDEV_CAPABLE_VEND_ID = '10DE'
MDEV_CAPABLE_VEND_NAME = 'Nvidia'
MDEV_CAPABLE_PROD_ID = '0FFE'
MDEV_CAPABLE_PROD_NAME = 'GRID M60-0B'
MDEV_CAPABLE_DRIVER_NAME = 'nvidia'
MDEV_CAPABLE_CAP_TYPE = 'mdev_types'

NVIDIA_11_VGPU_TYPE = 'nvidia-11'
NVIDIA_12_VGPU_TYPE = 'nvidia-12'
MLX5_CORE_TYPE = 'mlx5_core'
MDEVCAP_DEV1_PCI_ADDR = 'pci_0000_81_00_0'
MDEVCAP_DEV2_PCI_ADDR = 'pci_0000_81_01_0'
MDEVCAP_DEV3_PCI_ADDR = 'pci_0000_81_02_0'

os_uname = collections.namedtuple(
    'uname_result', ['sysname', 'nodename', 'release', 'version', 'machine'],
)


def _get_libvirt_nodedev_name(bus, slot, function):
    """Convert an address to a libvirt device name string."""
    return f'pci_0000_{bus:02x}_{slot:02x}_{function:d}'


class FakePCIDevice(object):
    """Generate a fake PCI device.

    Generate a fake PCI devices corresponding to one of the following
    real-world PCI devices.

    - I210 Gigabit Network Connection (8086:1533)
    - Ethernet Controller 10-Gigabit X540-AT2 (8086:1528)
    - X540 Ethernet Controller Virtual Function (8086:1515)
    """

    pci_default_parent = "pci_0000_80_01_0"
    pci_device_template = textwrap.dedent("""
        <device>
          <name>pci_0000_%(bus)02x_%(slot)02x_%(function)d</name>
          <path>/sys/devices/pci0000:80/0000:80:01.0/0000:%(bus)02x:%(slot)02x.%(function)d</path>
          <parent>%(parent)s</parent>
          <driver>
            <name>%(driver)s</name>
          </driver>
          <capability type='pci'>
            <domain>0</domain>
            <bus>%(bus)d</bus>
            <slot>%(slot)d</slot>
            <function>%(function)d</function>
            <product id='0x%(prod_id)s'>%(prod_name)s</product>
            <vendor id='0x%(vend_id)s'>%(vend_name)s</vendor>
        %(capability)s
            <iommuGroup number='%(iommu_group)d'>
              <address domain='0x0000' bus='%(bus)#02x' slot='%(slot)#02x' function='0x%(function)d'/>
            </iommuGroup>
            <numa node='%(numa_node)s'/>
            <pci-express>
              <link validity='cap' port='0' speed='5' width='8'/>
              <link validity='sta' speed='5' width='8'/>
            </pci-express>
          </capability>
        </device>""".strip())  # noqa
    cap_templ = "<capability type='%(cap_type)s'>%(addresses)s</capability>"
    addr_templ = "<address domain='0x0000' bus='%(bus)#02x' slot='%(slot)#02x' function='%(function)#02x'/>"  # noqa
    mdevtypes_templ = textwrap.dedent("""
        <type id='%(type_id)s'>
        <name>GRID M60-0B</name><deviceAPI>vfio-pci</deviceAPI>
        <availableInstances>%(instances)s</availableInstances>
        </type>""".strip())  # noqa

    is_capable_of_mdevs = False

    def __init__(
        self, dev_type, bus, slot, function, iommu_group, numa_node, *,
        vf_ratio=None, multiple_gpu_types=False, generic_types=False,
        parent=None, vend_id=None, vend_name=None, prod_id=None,
        prod_name=None, driver_name=None,
    ):
        """Populate pci devices

        :param dev_type: (str) Indicates the type of the device (PCI, PF, VF,
            MDEV_TYPES).
        :param bus: (int) Bus number of the device.
        :param slot: (int) Slot number of the device.
        :param function: (int) Function number of the device.
        :param iommu_group: (int) IOMMU group ID.
        :param numa_node: (int) NUMA node of the device.
        :param vf_ratio: (int) Ratio of Virtual Functions on Physical. Only
            applicable if ``dev_type`` is one of: ``PF``, ``VF``.
        :param multiple_gpu_types: (bool) Supports different vGPU types.
        :param generic_types: (bool) Support both mlx5 and nvidia-12 types.
        :param parent: (int, int, int) A tuple of bus, slot and function
            corresponding to the parent.
        :param vend_id: (str) The vendor ID.
        :param vend_name: (str) The vendor name.
        :param prod_id: (str) The product ID.
        :param prod_name: (str) The product name.
        :param driver_name: (str) The driver name.
        """

        self.dev_type = dev_type
        self.bus = bus
        self.slot = slot
        self.function = function
        self.iommu_group = iommu_group
        self.numa_node = numa_node
        self.vf_ratio = vf_ratio
        self.multiple_gpu_types = multiple_gpu_types
        self.generic_types = generic_types
        self.parent = parent

        self.vend_id = vend_id
        self.vend_name = vend_name
        self.prod_id = prod_id
        self.prod_name = prod_name
        self.driver_name = driver_name

        self.generate_xml()

    def generate_xml(self, skip_capability=False):

        # initial validation
        assert self.dev_type in ('PCI', 'VF', 'PF', 'MDEV_TYPES'), (
            f'got invalid dev_type {self.dev_type}')

        if self.dev_type == 'PCI':
            assert not self.vf_ratio, 'vf_ratio does not apply for PCI devices'

        if self.dev_type in ('PF', 'VF'):
            assert self.vf_ratio, 'require vf_ratio for PFs and VFs'

        if self.dev_type == 'VF':
            assert self.parent, 'require parent for VFs'
            assert isinstance(self.parent, tuple), 'parent must be an address'
            assert len(self.parent) == 3, 'parent must be an address'

        vend_id = self.vend_id or PCI_VEND_ID
        vend_name = self.vend_name or PCI_VEND_NAME
        capability = ''
        if self.dev_type == 'PCI':
            prod_id = self.prod_id or PCI_PROD_ID
            prod_name = self.prod_name or PCI_PROD_NAME
            driver = self.driver_name or PCI_DRIVER_NAME
        elif self.dev_type == 'PF':
            prod_id = self.prod_id or PF_PROD_ID
            prod_name = self.prod_name or PF_PROD_NAME
            driver = self.driver_name or PF_DRIVER_NAME
            if not skip_capability:
                capability = self.cap_templ % {
                    'cap_type': PF_CAP_TYPE,
                    'addresses': '\n'.join([
                        self.addr_templ % {
                            'bus': self.bus,
                            # these are the slot, function values of the child
                            # VFs, we can only assign 8 functions to a slot
                            # (0-7) so bump the slot each time we exceed this
                            'slot': self.slot + (x // 8),
                            # ...and wrap the function value
                            'function': x % 8,
                        # the offset is because the PF is occupying function 0
                        } for x in range(1, self.vf_ratio + 1)])
                }
        elif self.dev_type == 'VF':
            prod_id = self.prod_id or VF_PROD_ID
            prod_name = self.prod_name or VF_PROD_NAME
            driver = self.driver_name or VF_DRIVER_NAME
            if not skip_capability:
                capability = self.cap_templ % {
                    'cap_type': VF_CAP_TYPE,
                    'addresses': self.addr_templ % {
                        'bus': self.bus,
                        # this is the slot, function value of the parent PF
                        # if we're e.g. device 8, we'll have a different slot
                        # to our parent so reverse this
                        'slot': self.slot - ((self.vf_ratio + 1) // 8),
                        # the parent PF is always function 0
                        'function': 0,
                    }
                }
        elif self.dev_type == 'MDEV_TYPES':
            prod_id = self.prod_id or MDEV_CAPABLE_PROD_ID
            prod_name = self.prod_name or MDEV_CAPABLE_PROD_NAME
            driver = self.driver_name or MDEV_CAPABLE_DRIVER_NAME
            vend_id = self.vend_id or MDEV_CAPABLE_VEND_ID
            vend_name = self.vend_name or MDEV_CAPABLE_VEND_NAME
            types = [self.mdevtypes_templ % {
                'type_id': NVIDIA_11_VGPU_TYPE,
                'instances': 16,
            }]
            if self.multiple_gpu_types:
                types.append(self.mdevtypes_templ % {
                    'type_id': NVIDIA_12_VGPU_TYPE,
                    'instances': 8,
                })
            if self.generic_types:
                types = [self.mdevtypes_templ % {
                    'type_id': MLX5_CORE_TYPE,
                    'instances': 16,
                }]
                types.append(self.mdevtypes_templ % {
                    'type_id': NVIDIA_12_VGPU_TYPE,
                    'instances': 8,
                })
            if not skip_capability:
                capability = self.cap_templ % {
                    'cap_type': MDEV_CAPABLE_CAP_TYPE,
                    'addresses': '\n'.join(types)
                }
            self.is_capable_of_mdevs = True

        parent = self.pci_default_parent
        if self.parent:
            parent = _get_libvirt_nodedev_name(*self.parent)

        self.pci_device = self.pci_device_template % {
            'bus': self.bus,
            'slot': self.slot,
            'function': self.function,
            'vend_id': vend_id,
            'vend_name': vend_name,
            'prod_id': prod_id,
            'prod_name': prod_name,
            'driver': driver,
            'capability': capability,
            'iommu_group': self.iommu_group,
            'numa_node': self.numa_node,
            'parent': parent,
        }
        # -1 is the sentinel set in /sys/bus/pci/devices/*/numa_node
        # for no NUMA affinity. When the numa_node is set to -1 on a device
        # Libvirt omits the NUMA element so we remove it.
        if self.numa_node == -1:
            self.pci_device = self.pci_device.replace("<numa node='-1'/>", "")

    def XMLDesc(self, flags):
        return self.pci_device


# TODO(stephenfin): Remove all of these HostFooDevicesInfo objects in favour of
# a unified devices object
class HostPCIDevicesInfo(object):
    """Represent a pool of host PCI devices."""

    TOTAL_NUMA_NODES = 2

    def __init__(self, num_pci=0, num_pfs=2, num_vfs=8, num_mdevcap=0,
                 numa_node=None, multiple_gpu_types=False,
                 generic_types=False):
        """Create a new HostPCIDevicesInfo object.

        :param num_pci: (int) The number of (non-SR-IOV) and (non-MDEV capable)
            PCI devices.
        :param num_pfs: (int) The number of PCI SR-IOV Physical Functions.
        :param num_vfs: (int) The number of PCI SR-IOV Virtual Functions.
        :param num_mdevcap: (int) The number of PCI devices capable of creating
            mediated devices.
        :param numa_node: (int) NUMA node of the device; if set all of the
            devices will be assigned to the specified node else they will be
            split between ``$TOTAL_NUMA_NODES`` nodes.
        :param multiple_gpu_types: (bool) Supports different vGPU types
        :param generic_types: (bool) Supports both nvidia-12 and mlx5 types
        """
        self.devices = {}

        if not (num_vfs or num_pfs) and not num_mdevcap:
            return

        if num_vfs and not num_pfs:
            raise ValueError('Cannot create VFs without PFs')

        if num_pfs and num_vfs % num_pfs:
            raise ValueError('num_vfs must be a factor of num_pfs')

        bus = 0x81
        slot = 0x0
        function = 0
        iommu_group = 40  # totally arbitrary number

        # Generate PCI devs
        for dev in range(num_pci):
            self.add_device(
                dev_type='PCI',
                bus=bus,
                slot=slot,
                function=function,
                iommu_group=iommu_group,
                numa_node=self._calc_numa_node(dev, numa_node))

            slot += 1
            iommu_group += 1

        # Generate MDEV capable devs
        for dev in range(num_mdevcap):
            self.add_device(
                dev_type='MDEV_TYPES',
                bus=bus,
                slot=slot,
                function=function,
                iommu_group=iommu_group,
                numa_node=self._calc_numa_node(dev, numa_node),
                multiple_gpu_types=multiple_gpu_types,
                generic_types=generic_types)

            slot += 1
            iommu_group += 1

        vf_ratio = num_vfs // num_pfs if num_pfs else 0

        # Generate PFs
        for dev in range(num_pfs):
            function = 0
            numa_node_pf = self._calc_numa_node(dev, numa_node)

            self.add_device(
                dev_type='PF',
                bus=bus,
                slot=slot,
                function=function,
                iommu_group=iommu_group,
                numa_node=numa_node_pf,
                vf_ratio=vf_ratio)

            parent = (bus, slot, function)
            # Generate VFs
            for _ in range(vf_ratio):
                function += 1
                iommu_group += 1

                if function % 8 == 0:
                    # functions must be 0-7
                    slot += 1
                    function = 0

                self.add_device(
                    dev_type='VF',
                    bus=bus,
                    slot=slot,
                    function=function,
                    iommu_group=iommu_group,
                    numa_node=numa_node_pf,
                    vf_ratio=vf_ratio,
                    parent=parent)

            slot += 1

    def add_device(
        self, dev_type, bus, slot, function, iommu_group, numa_node,
        vf_ratio=None, multiple_gpu_types=False, generic_types=False,
        parent=None, vend_id=None, vend_name=None, prod_id=None,
        prod_name=None, driver_name=None,
    ):
        pci_dev_name = _get_libvirt_nodedev_name(bus, slot, function)

        LOG.info('Generating %s device %r', dev_type, pci_dev_name)

        dev = FakePCIDevice(
            dev_type=dev_type,
            bus=bus,
            slot=slot,
            function=function,
            iommu_group=iommu_group,
            numa_node=numa_node,
            vf_ratio=vf_ratio,
            multiple_gpu_types=multiple_gpu_types,
            generic_types=generic_types,
            parent=parent,
            vend_id=vend_id,
            vend_name=vend_name,
            prod_id=prod_id,
            prod_name=prod_name,
            driver_name=driver_name)
        self.devices[pci_dev_name] = dev
        return dev

    @classmethod
    def _calc_numa_node(cls, dev, numa_node):
        return dev % cls.TOTAL_NUMA_NODES if numa_node is None else numa_node

    def get_all_devices(self):
        return self.devices.keys()

    def get_device_by_name(self, device_name):
        pci_dev = self.devices.get(device_name)
        return pci_dev

    def get_all_mdev_capable_devices(self):
        return [dev for dev in self.devices
                if self.devices[dev].is_capable_of_mdevs]


class FakeMdevDevice(object):
    template = """
    <device>
      <name>%(dev_name)s</name>
      <path>/sys/devices/pci0000:00/0000:00:02.0/%(path)s</path>
      <parent>%(parent)s</parent>
      <driver>
        <name>vfio_mdev</name>
      </driver>
      <capability type='mdev'>
        <type id='%(type_id)s'/>
        <iommuGroup number='12'/>
      </capability>
    </device>
    """

    def __init__(self, dev_name, type_id, parent):
        self.xml = self.template % {
            'dev_name': dev_name, 'type_id': type_id,
            'path': dev_name[len('mdev_'):],
            'parent': parent}

    def XMLDesc(self, flags):
        return self.xml


class HostMdevDevicesInfo(object):
    def __init__(self, devices=None):
        if devices is not None:
            self.devices = devices
        else:
            self.devices = {}

    def get_all_devices(self):
        return self.devices.keys()

    def get_device_by_name(self, device_name):
        dev = self.devices[device_name]
        return dev


class FakeVDPADevice:

    template = textwrap.dedent("""
        <device>
          <name>%(name)s</name>
          <path>%(path)s</path>
          <parent>%(parent)s</parent>
          <driver>
            <name>vhost_vdpa</name>
          </driver>
          <capability type='vdpa'>
            <chardev>/dev/vhost-vdpa-%(idx)d</chardev>
          </capability>
        </device>""".strip())

    def __init__(self, name, idx, parent):
        assert isinstance(parent, FakePCIDevice)
        assert parent.dev_type == 'VF'

        self.name = name
        self.idx = idx
        self.parent = parent
        self.generate_xml()

    def generate_xml(self):
        pf_pci = self.parent.parent
        vf_pci = (self.parent.bus, self.parent.slot, self.parent.function)
        pf_addr = '0000:%02x:%02x.%d' % pf_pci
        vf_addr = '0000:%02x:%02x.%d' % vf_pci
        parent = _get_libvirt_nodedev_name(*vf_pci)
        path = f'/sys/devices/pci0000:00/{pf_addr}/{vf_addr}/vdpa{self.idx}'
        self.xml = self.template % {
            'name': self.name,
            'idx': self.idx,
            'path': path,
            'parent': parent,
        }

    def XMLDesc(self, flags):
        return self.xml


class HostVDPADevicesInfo:

    def __init__(self):
        self.devices = {}

    def get_all_devices(self):
        return self.devices.keys()

    def get_device_by_name(self, device_name):
        dev = self.devices[device_name]
        return dev

    def add_device(self, name, idx, parent):
        LOG.info('Generating vDPA device %r', name)

        dev = FakeVDPADevice(name=name, idx=idx, parent=parent)
        self.devices[name] = dev
        return dev


class HostInfo(object):

    def __init__(self, cpu_nodes=1, cpu_sockets=1, cpu_cores=2, cpu_threads=1,
                 kB_mem=16780000, mempages=None):
        """Create a new Host Info object

        :param cpu_nodes: (int) the number of NUMA cell, 1 for unusual
                          NUMA topologies or uniform
        :param cpu_sockets: (int) number of CPU sockets per node if nodes > 1,
                            total number of CPU sockets otherwise
        :param cpu_cores: (int) number of cores per socket
        :param cpu_threads: (int) number of threads per core
        :param kB_mem: (int) memory size in KBytes
        """

        self.arch = obj_fields.Architecture.X86_64
        self.kB_mem = kB_mem
        self.cpus = cpu_nodes * cpu_sockets * cpu_cores * cpu_threads
        self.cpu_mhz = 800
        self.cpu_nodes = cpu_nodes
        self.cpu_cores = cpu_cores
        self.cpu_threads = cpu_threads
        self.cpu_sockets = cpu_sockets
        self.cpu_model = "Penryn"
        self.cpu_vendor = "Intel"
        self.numa_topology = NUMATopology(self.cpu_nodes, self.cpu_sockets,
                                          self.cpu_cores, self.cpu_threads,
                                          self.kB_mem, mempages)


class NUMATopology(vconfig.LibvirtConfigCapsNUMATopology):
    """A batteries-included variant of LibvirtConfigCapsNUMATopology.

    Provides sane defaults for LibvirtConfigCapsNUMATopology that can be used
    in tests as is, or overridden where necessary.
    """

    def __init__(self, cpu_nodes=4, cpu_sockets=1, cpu_cores=1, cpu_threads=2,
                 kb_mem=1048576, mempages=None, **kwargs):

        super(NUMATopology, self).__init__(**kwargs)

        cpu_count = 0
        cell_count = 0
        for socket_count in range(cpu_sockets):
            for cell_num in range(cpu_nodes):
                cell = vconfig.LibvirtConfigCapsNUMACell()
                cell.id = cell_count
                cell.memory = kb_mem // (cpu_nodes * cpu_sockets)
                for cpu_num in range(cpu_cores * cpu_threads):
                    cpu = vconfig.LibvirtConfigCapsNUMACPU()
                    cpu.id = cpu_count
                    cpu.socket_id = socket_count
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

                cell_count += 1


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


def _parse_nic_info(element):
    nic_info = {}
    nic_info['type'] = element.get('type', 'bridge')

    driver = element.find('./mac')
    if driver is not None:
        nic_info['mac'] = driver.get('address')

    source = element.find('./source')
    if source is not None:
        nic_info['source'] = source.get('bridge')

    target = element.find('./target')
    if target is not None:
        nic_info['target_dev'] = target.get('dev')

    return nic_info


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

    self.useFixture(fixtures.MockPatch(
        'nova.virt.libvirt.host.Host._init_events',
        side_effect=evloop))


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


class NodeDevice(object):

    def __init__(self, connection, xml=None):
        self._connection = connection

        self._xml = xml
        if xml is not None:
            self._parse_xml(xml)

    def _parse_xml(self, xml):
        tree = etree.fromstring(xml)
        root = tree.find('.')
        self._name = root.find('name').text
        self._parent = root.find('parent').text

    def attach(self):
        pass

    def dettach(self):
        pass

    def reset(self):
        pass

    def XMLDesc(self, flags: int) -> str:
        return self._xml

    def parent(self) -> str:
        return self._parent

    def name(self) -> str:
        return self._name

    def listCaps(self) -> ty.List[str]:
        return [self.name().split('_')[0]]


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
        self._job_type = VIR_DOMAIN_JOB_UNBOUNDED

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

        cpu_pins = {}

        pins = tree.findall('./cputune/vcpupin')
        for pin in pins:
            cpu_pins[pin.get('vcpu')] = pin.get('cpuset')

        definition['cpu_pins'] = cpu_pins

        emulator_pin = tree.find('./cputune/emulatorpin')
        if emulator_pin is not None:
            definition['emulator_pin'] = emulator_pin.get('cpuset')

        memnodes = {}

        for node in tree.findall('./numatune/memnode'):
            memnodes[node.get('cellid')] = node.get('nodeset')

        definition['memnodes'] = memnodes

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
                    elif nic_info['type'] == 'hostdev':
                        # <interface type='hostdev'> is for VF when vnic_type
                        # is direct. Add sriov vf pci information in nic_info
                        address = source.find('./address')
                        pci_type = address.get('type')
                        pci_domain = address.get('domain').replace('0x', '')
                        pci_bus = address.get('bus').replace('0x', '')
                        pci_slot = address.get('slot').replace('0x', '')
                        pci_function = address.get('function').replace(
                            '0x', '')
                        pci_device = "%s_%s_%s_%s_%s" % (pci_type, pci_domain,
                                                         pci_bus, pci_slot,
                                                         pci_function)
                        nic_info['source'] = pci_device
                    elif nic_info['type'] == 'vdpa':
                        nic_info['source'] = source.get('dev')

                nics_info += [nic_info]

            devices['nics'] = nics_info

            hostdev_info = []
            hostdevs = device_nodes.findall('./hostdev')
            for hostdev in hostdevs:
                address = hostdev.find('./source/address')
                # NOTE(gibi): only handle mdevs as pci is complicated
                dev_type = hostdev.get('type')
                if dev_type == 'mdev':
                    hostdev_info.append({
                        'type': dev_type,
                        'model': hostdev.get('model'),
                        'address_uuid': address.get('uuid')
                    })
            devices['hostdevs'] = hostdev_info

            vpmem_info = []
            vpmems = device_nodes.findall('./memory')
            for vpmem in vpmems:
                model = vpmem.get('model')
                if model == 'nvdimm':
                    source = vpmem.find('./source')
                    target = vpmem.find('./target')
                    path = source.find('./path').text
                    alignsize = source.find('./alignsize').text
                    size = target.find('./size').text
                    node = target.find('./node').text
                    vpmem_info.append({
                        'path': path,
                        'size': size,
                        'alignsize': alignsize,
                        'node': node})
            devices['vpmems'] = vpmem_info

        definition['devices'] = devices

        return definition

    def verify_hostdevs_interface_are_vfs(self):
        """Verify for interface type hostdev if the pci device is VF or not.
        """

        error_message = ("Interface type hostdev is currently supported on "
                         "SR-IOV Virtual Functions only")

        nics = self._def['devices'].get('nics', [])
        for nic in nics:
            if nic['type'] == 'hostdev':
                pci_device = nic['source']
                pci_info_from_connection = self._connection.pci_info.devices[
                    pci_device]
                if 'phys_function' not in pci_info_from_connection.pci_device:
                    raise make_libvirtError(
                        libvirtError,
                        error_message,
                        error_code=VIR_ERR_CONFIG_UNSUPPORTED,
                        error_domain=VIR_FROM_DOMAIN)

    def create(self):
        self.createWithFlags(0)

    def createWithFlags(self, flags):
        # FIXME: Not handling flags at the moment
        self.verify_hostdevs_interface_are_vfs()
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

    def migrateToURI3(self, dconnuri, params, flags):
        raise make_libvirtError(
                libvirtError,
                "Migration always fails for fake libvirt!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)

    def migrateSetMaxDowntime(self, downtime):
        pass

    def attachDevice(self, xml):
        result = False
        if xml.startswith("<disk"):
            disk_info = _parse_disk_info(etree.fromstring(xml))
            disk_info['_attached'] = True
            self._def['devices']['disks'] += [disk_info]
            result = True
        elif xml.startswith("<interface"):
            nic_info = _parse_nic_info(etree.fromstring(xml))
            nic_info['_attached'] = True
            self._def['devices']['nics'] += [nic_info]
            result = True
        else:
            # FIXME(sean-k-mooney): We don't currently handle attaching
            # or detaching hostdevs but we have tests that assume we do so
            # this is an error not an exception. This affects PCI passthough,
            # vGPUs and PF neutron ports.
            LOG.error(
                "Trying to attach an unsupported device type."
                "The fakelibvirt implementation is incomplete "
                "and should be extended to support %s: %s",
                xml, self._def['devices'])

        return result

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
        # detachDevice is a common function used for all devices types
        # so we need to handle each separately
        if xml.startswith("<disk"):
            disk_info = _parse_disk_info(etree.fromstring(xml))
            attached_disk_info = None
            for attached_disk in self._def['devices']['disks']:
                if attached_disk['target_dev'] == disk_info.get('target_dev'):
                    attached_disk_info = attached_disk
                    break

            if attached_disk_info:
                self._def['devices']['disks'].remove(attached_disk_info)

            return attached_disk_info is not None

        if xml.startswith("<interface"):
            nic_info = _parse_nic_info(etree.fromstring(xml))
            attached_nic_info = None
            for attached_nic in self._def['devices']['nics']:
                if attached_nic['mac'] == nic_info['mac']:
                    attached_nic_info = attached_nic
                    break

            if attached_nic_info:
                self._def['devices']['nics'].remove(attached_nic_info)

            return attached_nic_info is not None

        # FIXME(sean-k-mooney): We don't currently handle attaching or
        # detaching hostdevs but we have tests that assume we do so this is
        # an error not an exception. This affects PCI passthough, vGPUs and
        # PF neutron ports
        LOG.error(
            "Trying to detach an unsupported device type."
            "The fakelibvirt implementation is incomplete "
            "and should be extended to support %s: %s",
            xml, self._def['devices'])

        return False

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
        for func, nic in enumerate(self._def['devices']['nics']):
            if func > 7:
                # this should never be raised but is just present to highlight
                # the limitations of the current fake when writing new tests.
                # if you see this raised when add a new test you will need
                # to extend this fake to use both functions and slots.
                # the pci function is limited to 3 bits or 0-7.
                raise RuntimeError(
                    'Test attempts to add more than 8 PCI devices. This is '
                    'not supported by the fake libvirt implementation.')
            nic['func'] = func
            # this branch covers most interface types with a source
            # such as linux bridge interfaces.
            if 'source' in nic:
                nics += '''<interface type='%(type)s'>
          <mac address='%(mac)s'/>
          <source %(type)s='%(source)s'/>
          <target dev='tap274487d1-6%(func)s'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x03'
                   function='0x%(func)s'/>
        </interface>''' % nic
            elif nic['type'] in ('ethernet',):
                # this branch covers kernel ovs interfaces
                nics += '''<interface type='%(type)s'>
          <mac address='%(mac)s'/>
          <target dev='tap274487d1-6%(func)s'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x03'
                   function='0x%(func)s'/>
        </interface>''' % nic
            else:
                # This branch covers the macvtap vnic-type.
                # This is incomplete as the source dev should be unique
                # and map to the VF netdev name but due to the mocking in
                # the fixture we hard code it.
                nics += '''<interface type='%(type)s'>
          <mac address='%(mac)s'/>
          <source dev='fake_pf_interface_name' mode='passthrough'>
              <address type='pci' domain='0x0000' bus='0x81' slot='0x00'
                   function='0x%(func)s'/>
          </source>
        </interface>''' % nic

        hostdevs = ''
        for hostdev in self._def['devices']['hostdevs']:
            hostdevs += '''<hostdev mode='subsystem' type='%(type)s' model='%(model)s'>
    <source>
      <address uuid='%(address_uuid)s'/>
    </source>
    </hostdev>
            ''' % hostdev  # noqa

        vpmems = ''
        for vpmem in self._def['devices']['vpmems']:
            vpmems += '''
    <memory model='nvdimm' access='shared'>
      <source>
        <path>%(path)s</path>
        <alignsize>%(alignsize)s</alignsize>
        <pmem/>
      </source>
      <target>
        <size>%(size)s</size>
        <node>%(node)s</node>
        <label>
          <size>2097152</size>
        </label>
      </target>
    </memory>
            ''' % vpmem
        cputune = ''
        for vcpu, cpuset in self._def['cpu_pins'].items():
            cputune += '<vcpupin vcpu="%d" cpuset="%s"/>' % (int(vcpu), cpuset)
        emulatorpin = None
        if 'emulator_pin' in self._def:
            emulatorpin = ('<emulatorpin cpuset="%s"/>' %
                           self._def['emulator_pin'])
        if cputune or emulatorpin:
            cputune = '<cputune>%s%s</cputune>' % (emulatorpin, cputune)

        numatune = ''
        for cellid, nodeset in self._def['memnodes'].items():
            numatune += '<memnode cellid="%d" nodeset="%s"/>' % (int(cellid),
                                                                 nodeset)
            numatune += '<memory nodeset="%s"/>' % ','.join(
                self._def['memnodes'].values())
        if numatune:
            numatune = '<numatune>%s</numatune>' % numatune

        serial_console = ''
        if CONF.serial_console.enabled:
            serial_console = """<serial type="tcp">
                <source host="-1" service="-1" mode="bind"/>
                </serial>"""

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
  %(cputune)s
  %(numatune)s
  <devices>
    <emulator>/usr/bin/kvm</emulator>
    %(disks)s
    <controller type='ide' index='0'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x01'
               function='0x1'/>
    </controller>
    %(nics)s
    %(serial_console)s
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
    %(hostdevs)s
    %(vpmems)s
  </devices>
</domain>''' % {'name': self._def['name'],
                'uuid': self._def['uuid'],
                'memory': self._def['memory'],
                'vcpu': self._def['vcpu'],
                'arch': self._def['os']['arch'],
                'disks': disks,
                'nics': nics,
                'hostdevs': hostdevs,
                'vpmems': vpmems,
                'serial_console': serial_console,
                'cputune': cputune,
                'numatune': numatune}

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

    def blockResize(self, disk, size, flags):
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

    def blockCopy(self, disk, base, flags=0):
        return 0

    def blockCommit(self, disk, base, top, flags):
        return 0

    def jobInfo(self):
        # NOTE(danms): This is an array of 12 integers, so just report
        # something to avoid an IndexError if we look at this
        return [0] * 12

    def jobStats(self, flags=0):
        # NOTE(artom) By returning VIR_DOMAIN_JOB_UNBOUNDED, we're pretending a
        # job is constantly running. Tests are expected to call the
        # complete_job or fail_job methods when they're ready for jobs (read:
        # live migrations) to "complete".
        return {'type': self._job_type}

    def complete_job(self):
        self._job_type = VIR_DOMAIN_JOB_COMPLETED

    def fail_job(self):
        self._job_type = VIR_DOMAIN_JOB_FAILED

    def injectNMI(self, flags=0):
        return 0

    def abortJob(self):
        pass

    def fsFreeze(self):
        pass

    def fsThaw(self):
        pass

    def setMetadata(self, metadata_type, metadata, key, uri, flags=0):
        pass


class DomainSnapshot(object):
    def __init__(self, name, domain):
        self._name = name
        self._domain = domain

    def delete(self, flags):
        del self._domain._snapshots[self._name]


class Secret(object):
    def __init__(self, connection, xml):
        self._connection = connection
        self._xml = xml
        self._parse_xml(xml)
        self._value = None

    def _parse_xml(self, xml):
        tree = etree.fromstring(xml)
        self._uuid = tree.find('./uuid').text
        self._private = tree.get('private') == 'yes'

    def setValue(self, value, flags=0):
        self._value = value
        return 0

    def value(self, flags=0):
        if self._value is None:
            raise make_libvirtError(
                libvirtError,
                "secret '%s' does not have a value" % self._uuid,
                error_code=VIR_ERR_NO_SECRET,
                error_domain=VIR_FROM_SECRET)
            pass

        if self._private:
            raise make_libvirtError(
                libvirtError,
                'secret is private',
                error_code=VIR_ERR_INVALID_SECRET,
                error_domain=VIR_FROM_SECRET)

        return self._value

    def undefine(self):
        self._connection._remove_secret(self)


class Connection(object):
    def __init__(
        self, uri=None, readonly=False, version=FAKE_LIBVIRT_VERSION,
        hv_version=FAKE_QEMU_VERSION, hostname=None,
        host_info=None, pci_info=None, mdev_info=None, vdpa_info=None,
    ):
        if not uri or uri == '':
            if allow_default_uri_connection:
                uri = 'qemu:///session'
            else:
                raise ValueError("URI was None, but fake libvirt is "
                                 "configured to not accept this.")

        uri_whitelist = [
            'qemu:///system',
            'qemu:///session',
            'lxc:///',     # from LibvirtDriver._uri()
            'test:///default',
            'parallels:///system',
        ]

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
        self._nodedevs = {}
        self._secrets = {}
        self._event_callbacks = {}
        self.fakeLibVersion = version
        self.fakeVersion = hv_version
        self.host_info = host_info or HostInfo()
        self.pci_info = pci_info or HostPCIDevicesInfo(num_pci=0,
                                                       num_pfs=0,
                                                       num_vfs=0)
        self.mdev_info = mdev_info or HostMdevDevicesInfo(devices={})
        self.vdpa_info = vdpa_info or HostVDPADevicesInfo()
        self.hostname = hostname or 'compute1'

    def _add_nodedev(self, nodedev):
        self._nodedevs[nodedev._name] = nodedev

    def _remove_nodedev(self, nodedev):
        del self._nodedevs[nodedev._name]

    def _add_secret(self, secret):
        self._secrets[secret._uuid] = secret

    def _remove_secret(self, secret):
        del self._secrets[secret._uuid]

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
        return self.hostname

    def domainEventRegisterAny(self, dom, eventid, callback, opaque):
        self._event_callbacks[eventid] = [callback, opaque]

    def registerCloseCallback(self, cb, opaque):
        pass

    def getCPUMap(self):
        """Return calculated CPU map from HostInfo, by default showing 2
           online CPUs.
        """
        total_cpus = self.host_info.cpus
        cpu_map = [True for cpu_num in range(total_cpus)]
        return (total_cpus, cpu_map, total_cpus)

    def getDomainCapabilities(
        self, emulatorbin, arch, machine_type, virt_type, flags,
    ):
        """Return spoofed domain capabilities."""
        if arch in fake_libvirt_data.STATIC_DOMCAPABILITIES:
            xml = fake_libvirt_data.STATIC_DOMCAPABILITIES[arch]
            if machine_type:
                # if we request a specific machine type, we should get
                # information on that and not something else
                tree = etree.fromstring(xml)
                if machine_type not in tree.find('./machine').text:
                    raise Exception(
                        'Expected machine type of ~%s but got %s' % (
                            machine_type, tree.find('./machine').text,
                        ))
            return xml

        if arch == 'x86_64':
            aliases = {'pc': 'pc-i440fx-2.11', 'q35': 'pc-q35-2.11'}
            return fake_libvirt_data.DOMCAPABILITIES_X86_64_TEMPLATE % \
                {'features': self._domain_capability_features,
                 'mtype': aliases.get(machine_type, machine_type)}

        raise Exception("fakelibvirt doesn't support getDomainCapabilities "
                        "for %s architecture" % arch)

    def getCPUModelNames(self, arch):
        mapping = {
            'x86_64': [
                '486',
                'pentium',
                'pentium2',
                'pentium3',
                'pentiumpro',
                'coreduo',
                'n270',
                'core2duo',
                'qemu32',
                'kvm32',
                'cpu64-rhel5',
                'cpu64-rhel6',
                'qemu64',
                'kvm64',
                'Conroe',
                'Penryn',
                'Nehalem',
                'Nehalem-IBRS',
                'Westmere',
                'Westmere-IBRS',
                'SandyBridge',
                'SandyBridge-IBRS',
                'IvyBridge',
                'IvyBridge-IBRS',
                'Haswell-noTSX',
                'Haswell-noTSX-IBRS',
                'Haswell',
                'Haswell-IBRS',
                'Broadwell-noTSX',
                'Broadwell-noTSX-IBRS',
                'Broadwell',
                'Broadwell-IBRS',
                'Skylake-Client',
                'Skylake-Client-IBRS',
                'Skylake-Server',
                'Skylake-Server-IBRS',
                'Cascadelake-Server',
                'Icelake-Client',
                'Icelake-Server',
                'athlon',
                'phenom',
                'Opteron_G1',
                'Opteron_G2',
                'Opteron_G3',
                'Opteron_G4',
                'Opteron_G5',
                'EPYC',
                'EPYC-IBPB'],
            'ppc64': [
                'POWER6',
                'POWER7',
                'POWER8',
                'POWER9',
                'POWERPC_e5500',
                'POWERPC_e6500']
        }
        return mapping.get(arch, [])

    # Features are kept separately so that the tests can patch this
    # class variable with alternate values.
    _domain_capability_features = '''  <features>
    <gic supported='no'/>
  </features>'''

    _domain_capability_features_with_SEV = '''  <features>
    <gic supported='no'/>
    <sev supported='yes'>
      <cbitpos>47</cbitpos>
      <reducedPhysBits>1</reducedPhysBits>
    </sev>
  </features>'''

    _domain_capability_features_with_SEV_unsupported = \
        _domain_capability_features_with_SEV.replace('yes', 'no')

    def getCapabilities(self):
        """Return spoofed capabilities."""
        numa_topology = self.host_info.numa_topology
        if isinstance(numa_topology, vconfig.LibvirtConfigCapsNUMATopology):
            numa_topology = numa_topology.to_xml()

        # we rely on os.uname() having been mocked already to ensure we have
        # the correct "host" architecture
        _capabilities = [
            '<capabilities>\n',
            fake_libvirt_data.CAPABILITIES_HOST_TEMPLATES[os.uname().machine],
        ] + list(fake_libvirt_data.CAPABILITIES_GUEST.values()) + [
            '</capabilities>',
        ]

        return ''.join(_capabilities) % {
            'sockets': self.host_info.cpu_sockets,
            'cores': self.host_info.cpu_cores,
            'threads': self.host_info.cpu_threads,
            'topology': numa_topology,
        }

    def compareCPU(self, xml, flags):
        tree = etree.fromstring(xml)

        arch_node = tree.find('./arch')
        if arch_node is not None:
            if arch_node.text not in [obj_fields.Architecture.X86_64,
                                      obj_fields.Architecture.I686]:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        model_node = tree.find('./model')
        if model_node is not None:
            # arch_node may not present, therefore query all cpu models.
            if model_node.text not in self.getCPUModelNames('x86_64') and \
                model_node.text not in self.getCPUModelNames('ppc64'):
                raise make_libvirtError(
                    libvirtError,
                    "internal error: Unknown CPU model %s" % model_node.text,
                    error_code = VIR_ERR_INTERNAL_ERROR,
                    error_domain=VIR_FROM_QEMU)
            if model_node.text != self.host_info.cpu_model:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        vendor_node = tree.find('./vendor')
        if vendor_node is not None:
            if vendor_node.text != self.host_info.cpu_vendor:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        # The rest of the stuff libvirt implements is rather complicated
        # and I don't think it adds much value to replicate it here.

        return VIR_CPU_COMPARE_IDENTICAL

    def compareHypervisorCPU(
        self, emulator, arch, machine, virttype,
        xml, flags
    ):
        return self.compareCPU(xml, flags)

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

    def device_lookup_by_name(self, dev_name):
        return self.pci_info.get_device_by_name(dev_name)

    def nodeDeviceLookupByName(self, name):
        if name.startswith('mdev'):
            return self.mdev_info.get_device_by_name(name)

        if name.startswith('vdpa'):
            return self.vdpa_info.get_device_by_name(name)

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
        if cap == 'pci':
            return self.pci_info.get_all_devices()
        if cap == 'mdev':
            return self.mdev_info.get_all_devices()
        if cap == 'mdev_types':
            return self.pci_info.get_all_mdev_capable_devices()
        if cap == 'vdpa':
            return self.vdpa_info.get_all_devices()
        else:
            raise ValueError('Capability "%s" is not supported' % cap)

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
        secret = Secret(self, xml)
        self._add_secret(secret)
        return secret

    def listAllDevices(self, flags):
        devices = []
        if flags & VIR_CONNECT_LIST_NODE_DEVICES_CAP_PCI_DEV:
            devices.extend(
                NodeDevice(self, xml=dev.XMLDesc(0))
                for dev in self.pci_info.devices.values()
            )
        if flags & VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET:
            # TODO(stephenfin): Implement fake netdevs so we can test the
            # capability reporting
            pass
        if flags & VIR_CONNECT_LIST_NODE_DEVICES_CAP_VDPA:
            devices.extend(
                NodeDevice(self, xml=dev.XMLDesc(0))
                for dev in self.vdpa_info.devices.values()
            )
        return devices


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
virSecret = Secret


# A private libvirt-python class and global only provided here for testing to
# ensure it's not returned by libvirt.host.Host.get_libvirt_proxy_classes.
class FakeHandler(object):
    def __init__(self):
        pass


_EventAddHandleFunc = FakeHandler


class LibvirtFixture(fixtures.Fixture):
    """Performs global setup/stubbing for all libvirt tests.
    """
    def __init__(self, stub_os_vif=True):
        self.stub_os_vif = stub_os_vif

    def setUp(self):
        super().setUp()

        # Some modules load the libvirt library in a strange way
        for module in ('driver', 'host', 'guest', 'migration'):
            i = 'nova.virt.libvirt.{module}.libvirt'.format(module=module)
            # NOTE(mdbooth): The strange incantation below means 'this module'
            self.useFixture(fixtures.MonkeyPatch(i, sys.modules[__name__]))

        self.useFixture(
            fixtures.MockPatch('nova.virt.libvirt.utils.get_fs_info'))
        self.useFixture(
            fixtures.MockPatch('nova.compute.utils.get_machine_ips'))

        # libvirt driver needs to call out to the filesystem to get the
        # parent_ifname for the SRIOV VFs.
        self.useFixture(fixtures.MockPatch(
            'nova.pci.utils.get_ifname_by_pci_address',
            return_value='fake_pf_interface_name'))

        # libvirt calls out to sysfs to get the vfs ID during macvtap plug
        self.useFixture(fixtures.MockPatch(
            'nova.pci.utils.get_vf_num_by_pci_address', return_value=1))

        # libvirt calls out to privsep to set the mac and vlan of a macvtap
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.linux_net.set_device_macaddr_and_vlan'))

        # libvirt calls out to privsep to set the port state during macvtap
        # plug
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.linux_net.set_device_macaddr'))

        # Don't assume that the system running tests has a valid machine-id
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '._get_host_sysinfo_serial_os', return_value=uuids.machine_id))

        # Stub out _log_host_capabilities since it logs a giant string at INFO
        # and we don't want that to blow up the subunit parser in test runs.
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._log_host_capabilities'))

        # Ensure tests perform the same on all host architectures
        fake_uname = os_uname(
            'Linux', '', '5.4.0-0-generic', '', obj_fields.Architecture.X86_64)
        self.useFixture(
            fixtures.MockPatch('os.uname', return_value=fake_uname))

        # ...and on all machine types
        fake_loaders = [
            {
                'description': 'UEFI firmware for x86_64',
                'interface-types': ['uefi'],
                'mapping': {
                    'device': 'flash',
                    'executable': {
                        'filename': '/usr/share/OVMF/OVMF_CODE.fd',
                        'format': 'raw',
                    },
                    'nvram-template': {
                        'filename': '/usr/share/OVMF/OVMF_VARS.fd',
                        'format': 'raw',
                    },
                },
                'targets': [
                    {
                        'architecture': 'x86_64',
                        'machines': ['pc-i440fx-*', 'pc-q35-*'],
                    },
                ],
                'features': ['acpi-s3', 'amd-sev', 'verbose-dynamic'],
                'tags': [],
            },
            {
                'description': 'UEFI firmware for x86_64, with SB+SMM',
                'interface-types': ['uefi'],
                'mapping': {
                    'device': 'flash',
                    'executable': {
                        'filename': '/usr/share/OVMF/OVMF_CODE.secboot.fd',
                        'format': 'raw',
                    },
                    'nvram-template': {
                        'filename': '/usr/share/OVMF/OVMF_VARS.secboot.fd',
                        'format': 'raw',
                    },
                },
                'targets': [
                    {
                        'architecture': 'x86_64',
                        'machines': ['pc-q35-*'],
                    },
                ],
                'features': [
                    'acpi-s3',
                    'amd-sev',
                    'enrolled-keys',
                    'requires-smm',
                    'secure-boot',
                    'verbose-dynamic',
                ],
                'tags': [],
            },
            {
                'description': 'UEFI firmware for aarch64',
                'interface-types': ['uefi'],
                'mapping': {
                    'device': 'flash',
                    'executable': {
                        'filename': '/usr/share/AAVMF/AAVMF_CODE.fd',
                        'format': 'raw',
                    },
                    'nvram-template': {
                        'filename': '/usr/share/AAVMF/AAVMF_VARS.fd',
                        'format': 'raw',
                    }
                },
                'targets': [
                    {
                        'architecture': 'aarch64',
                        'machines': ['virt-*'],
                    }
                ],
                'features': ['verbose-static'],
                "tags": [],
            },
        ]
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.host.Host.loaders',
                new_callable=mock.PropertyMock,
                return_value=fake_loaders))

        disable_event_thread(self)

        if self.stub_os_vif:
            # Make sure to never try and actually plug/unplug VIFs in os-vif
            # unless we're explicitly testing that code and the test itself
            # will handle the appropriate mocking.
            self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.libvirt.vif.LibvirtGenericVIFDriver._plug_os_vif',
                lambda *a, **kw: None))
            self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.libvirt.vif.LibvirtGenericVIFDriver._unplug_os_vif',
                lambda *a, **kw: None))

        # os_vif.initialize is typically done in nova-compute startup
        # even if we are not planning to plug anything with os_vif in the test
        # we still need the object model initialized to be able to generate
        # guest config xml properly
        import os_vif
        os_vif.initialize()
