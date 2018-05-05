#    Copyright 2013 Red Hat, Inc.
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

import os
import re

from cursive import signature_utils
from oslo_versionedobjects import fields
import six

from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova.virt import arch


# Import field errors from oslo.versionedobjects
KeyTypeError = fields.KeyTypeError
ElementTypeError = fields.ElementTypeError


# Import fields from oslo.versionedobjects
BooleanField = fields.BooleanField
UnspecifiedDefault = fields.UnspecifiedDefault
IntegerField = fields.IntegerField
NonNegativeIntegerField = fields.NonNegativeIntegerField
UUIDField = fields.UUIDField
FloatField = fields.FloatField
NonNegativeFloatField = fields.NonNegativeFloatField
StringField = fields.StringField
SensitiveStringField = fields.SensitiveStringField
EnumField = fields.EnumField
DateTimeField = fields.DateTimeField
DictOfStringsField = fields.DictOfStringsField
DictOfNullableStringsField = fields.DictOfNullableStringsField
DictOfIntegersField = fields.DictOfIntegersField
ListOfStringsField = fields.ListOfStringsField
SetOfIntegersField = fields.SetOfIntegersField
ListOfSetsOfIntegersField = fields.ListOfSetsOfIntegersField
ListOfDictOfNullableStringsField = fields.ListOfDictOfNullableStringsField
DictProxyField = fields.DictProxyField
ObjectField = fields.ObjectField
ListOfObjectsField = fields.ListOfObjectsField
VersionPredicateField = fields.VersionPredicateField
FlexibleBooleanField = fields.FlexibleBooleanField
DictOfListOfStringsField = fields.DictOfListOfStringsField
IPAddressField = fields.IPAddressField
IPV4AddressField = fields.IPV4AddressField
IPV6AddressField = fields.IPV6AddressField
IPV4AndV6AddressField = fields.IPV4AndV6AddressField
IPNetworkField = fields.IPNetworkField
IPV4NetworkField = fields.IPV4NetworkField
IPV6NetworkField = fields.IPV6NetworkField
AutoTypedField = fields.AutoTypedField
BaseEnumField = fields.BaseEnumField
MACAddressField = fields.MACAddressField
ListOfIntegersField = fields.ListOfIntegersField
PCIAddressField = fields.PCIAddressField


# NOTE(danms): These are things we need to import for some of our
# own implementations below, our tests, or other transitional
# bits of code. These should be removable after we finish our
# conversion. So do not use these nova fields directly in any new code;
# instead, use the oslo.versionedobjects fields.
Enum = fields.Enum
Field = fields.Field
FieldType = fields.FieldType
Set = fields.Set
Dict = fields.Dict
List = fields.List
Object = fields.Object
IPAddress = fields.IPAddress
IPV4Address = fields.IPV4Address
IPV6Address = fields.IPV6Address
IPNetwork = fields.IPNetwork
IPV4Network = fields.IPV4Network
IPV6Network = fields.IPV6Network


class BaseNovaEnum(Enum):
    def __init__(self, **kwargs):
        super(BaseNovaEnum, self).__init__(valid_values=self.__class__.ALL)


class Architecture(BaseNovaEnum):
    """Represents CPU architectures.

    Provides the standard names for all known processor architectures.
    Many have multiple variants to deal with big-endian vs little-endian
    modes, as well as 32 vs 64 bit word sizes. These names are chosen to
    be identical to the architecture names expected by libvirt, so if
    ever adding new ones then ensure it matches libvirt's expectation.
    """

    ALPHA = arch.ALPHA
    ARMV6 = arch.ARMV6
    ARMV7 = arch.ARMV7
    ARMV7B = arch.ARMV7B

    AARCH64 = arch.AARCH64
    CRIS = arch.CRIS
    I686 = arch.I686
    IA64 = arch.IA64
    LM32 = arch.LM32

    M68K = arch.M68K
    MICROBLAZE = arch.MICROBLAZE
    MICROBLAZEEL = arch.MICROBLAZEEL
    MIPS = arch.MIPS
    MIPSEL = arch.MIPSEL

    MIPS64 = arch.MIPS64
    MIPS64EL = arch.MIPS64EL
    OPENRISC = arch.OPENRISC
    PARISC = arch.PARISC
    PARISC64 = arch.PARISC64

    PPC = arch.PPC
    PPCLE = arch.PPCLE
    PPC64 = arch.PPC64
    PPC64LE = arch.PPC64LE
    PPCEMB = arch.PPCEMB

    S390 = arch.S390
    S390X = arch.S390X
    SH4 = arch.SH4
    SH4EB = arch.SH4EB
    SPARC = arch.SPARC

    SPARC64 = arch.SPARC64
    UNICORE32 = arch.UNICORE32
    X86_64 = arch.X86_64
    XTENSA = arch.XTENSA
    XTENSAEB = arch.XTENSAEB

    ALL = arch.ALL

    @classmethod
    def from_host(cls):
        """Get the architecture of the host OS

        :returns: the canonicalized host architecture
        """

        return cls.canonicalize(os.uname()[4])

    @classmethod
    def is_valid(cls, name):
        """Check if a string is a valid architecture

        :param name: architecture name to validate

        :returns: True if @name is valid
        """

        return name in cls.ALL

    @classmethod
    def canonicalize(cls, name):
        """Canonicalize the architecture name

        :param name: architecture name to canonicalize

        :returns: a canonical architecture name
        """

        if name is None:
            return None

        newname = name.lower()

        if newname in ("i386", "i486", "i586"):
            newname = cls.I686

        # Xen mistake from Icehouse or earlier
        if newname in ("x86_32", "x86_32p"):
            newname = cls.I686

        if newname == "amd64":
            newname = cls.X86_64

        if not cls.is_valid(newname):
            raise exception.InvalidArchitectureName(arch=name)

        return newname

    def coerce(self, obj, attr, value):
        try:
            value = self.canonicalize(value)
        except exception.InvalidArchitectureName:
            msg = _("Architecture name '%s' is not valid") % value
            raise ValueError(msg)
        return super(Architecture, self).coerce(obj, attr, value)


class BlockDeviceDestinationType(BaseNovaEnum):
    """Represents possible destination_type values for a BlockDeviceMapping."""

    LOCAL = 'local'
    VOLUME = 'volume'

    ALL = (LOCAL, VOLUME)


class BlockDeviceSourceType(BaseNovaEnum):
    """Represents the possible source_type values for a BlockDeviceMapping."""

    BLANK = 'blank'
    IMAGE = 'image'
    SNAPSHOT = 'snapshot'
    VOLUME = 'volume'

    ALL = (BLANK, IMAGE, SNAPSHOT, VOLUME)


class BlockDeviceType(BaseNovaEnum):
    """Represents possible device_type values for a BlockDeviceMapping."""

    CDROM = 'cdrom'
    DISK = 'disk'
    FLOPPY = 'floppy'
    FS = 'fs'
    LUN = 'lun'

    ALL = (CDROM, DISK, FLOPPY, FS, LUN)


class ConfigDrivePolicy(BaseNovaEnum):
    OPTIONAL = "optional"
    MANDATORY = "mandatory"

    ALL = (OPTIONAL, MANDATORY)


class CPUAllocationPolicy(BaseNovaEnum):

    DEDICATED = "dedicated"
    SHARED = "shared"

    ALL = (DEDICATED, SHARED)


class CPUThreadAllocationPolicy(BaseNovaEnum):

    # prefer (default): The host may or may not have hyperthreads. This
    #  retains the legacy behavior, whereby siblings are preferred when
    #  available. This is the default if no policy is specified.
    PREFER = "prefer"
    # isolate: The host may or many not have hyperthreads. If hyperthreads are
    #  present, each vCPU will be placed on a different core and no vCPUs from
    #  other guests will be able to be placed on the same core, i.e. one
    #  thread sibling is guaranteed to always be unused. If hyperthreads are
    #  not present, each vCPU will still be placed on a different core and
    #  there are no thread siblings to be concerned with.
    ISOLATE = "isolate"
    # require: The host must have hyperthreads. Each vCPU will be allocated on
    #   thread siblings.
    REQUIRE = "require"

    ALL = (PREFER, ISOLATE, REQUIRE)


class CPUEmulatorThreadsPolicy(BaseNovaEnum):

    # share (default): Emulator threads float across the pCPUs
    # associated to the guest.
    SHARE = "share"
    # isolate: Emulator threads are isolated on a single pCPU.
    ISOLATE = "isolate"

    ALL = (SHARE, ISOLATE)


class CPUMode(BaseNovaEnum):

    CUSTOM = 'custom'
    HOST_MODEL = 'host-model'
    HOST_PASSTHROUGH = 'host-passthrough'

    ALL = (CUSTOM, HOST_MODEL, HOST_PASSTHROUGH)


class CPUMatch(BaseNovaEnum):

    MINIMUM = 'minimum'
    EXACT = 'exact'
    STRICT = 'strict'

    ALL = (MINIMUM, EXACT, STRICT)


class CPUFeaturePolicy(BaseNovaEnum):

    FORCE = 'force'
    REQUIRE = 'require'
    OPTIONAL = 'optional'
    DISABLE = 'disable'
    FORBID = 'forbid'

    ALL = (FORCE, REQUIRE, OPTIONAL, DISABLE, FORBID)


class DiskBus(BaseNovaEnum):

    FDC = "fdc"
    IDE = "ide"
    SATA = "sata"
    SCSI = "scsi"
    USB = "usb"
    VIRTIO = "virtio"
    XEN = "xen"
    LXC = "lxc"
    UML = "uml"

    ALL = (FDC, IDE, SATA, SCSI, USB, VIRTIO, XEN, LXC, UML)


class DiskConfig(BaseNovaEnum):

    MANUAL = "MANUAL"
    AUTO = "AUTO"

    ALL = (MANUAL, AUTO)

    def coerce(self, obj, attr, value):
        enum_value = DiskConfig.AUTO if value else DiskConfig.MANUAL
        return super(DiskConfig, self).coerce(obj, attr, enum_value)


class FirmwareType(BaseNovaEnum):

    UEFI = "uefi"
    BIOS = "bios"

    ALL = (UEFI, BIOS)


class HVType(BaseNovaEnum):
    """Represents virtualization types.

    Provide the standard names for all known guest virtualization
    types. This is not to be confused with the Nova hypervisor driver
    types, since one driver may support multiple virtualization types
    and one virtualization type (eg 'xen') may be supported by multiple
    drivers ('XenAPI' or  'Libvirt-Xen').
    """

    BAREMETAL = 'baremetal'
    BHYVE = 'bhyve'
    DOCKER = 'docker'
    FAKE = 'fake'
    HYPERV = 'hyperv'
    IRONIC = 'ironic'
    KQEMU = 'kqemu'
    KVM = 'kvm'
    LXC = 'lxc'
    LXD = 'lxd'
    OPENVZ = 'openvz'
    PARALLELS = 'parallels'
    VIRTUOZZO = 'vz'
    PHYP = 'phyp'
    QEMU = 'qemu'
    TEST = 'test'
    UML = 'uml'
    VBOX = 'vbox'
    VMWARE = 'vmware'
    XEN = 'xen'
    ZVM = 'zvm'
    PRSM = 'prsm'

    ALL = (BAREMETAL, BHYVE, DOCKER, FAKE, HYPERV, IRONIC, KQEMU, KVM, LXC,
           LXD, OPENVZ, PARALLELS, PHYP, QEMU, TEST, UML, VBOX, VIRTUOZZO,
           VMWARE, XEN, ZVM, PRSM)

    def coerce(self, obj, attr, value):
        try:
            value = self.canonicalize(value)
        except exception.InvalidHypervisorVirtType:
            msg = _("Hypervisor virt type '%s' is not valid") % value
            raise ValueError(msg)

        return super(HVType, self).coerce(obj, attr, value)

    @classmethod
    def is_valid(cls, name):
        """Check if a string is a valid hypervisor type

        :param name: hypervisor type name to validate

        :returns: True if @name is valid
        """
        return name in cls.ALL

    @classmethod
    def canonicalize(cls, name):
        """Canonicalize the hypervisor type name

        :param name: hypervisor type name to canonicalize

        :returns: a canonical hypervisor type name
        """
        if name is None:
            return None

        newname = name.lower()

        if newname == 'xapi':
            newname = cls.XEN

        if not cls.is_valid(newname):
            raise exception.InvalidHypervisorVirtType(hv_type=name)

        return newname


class ImageSignatureHashType(BaseNovaEnum):
    # Represents the possible hash methods used for image signing
    ALL = tuple(sorted(signature_utils.HASH_METHODS.keys()))


class ImageSignatureKeyType(BaseNovaEnum):
    # Represents the possible keypair types used for image signing
    ALL = (
        'DSA', 'ECC_SECP384R1', 'ECC_SECP521R1', 'ECC_SECT409K1',
        'ECC_SECT409R1', 'ECC_SECT571K1', 'ECC_SECT571R1', 'RSA-PSS'
    )


class OSType(BaseNovaEnum):

    LINUX = "linux"
    WINDOWS = "windows"

    ALL = (LINUX, WINDOWS)

    def coerce(self, obj, attr, value):
        # Some code/docs use upper case or initial caps
        # so canonicalize to all lower case
        value = value.lower()
        return super(OSType, self).coerce(obj, attr, value)


class ResourceClass(StringField):
    """Classes of resources provided to consumers."""

    CUSTOM_NAMESPACE = 'CUSTOM_'
    """All non-standard resource classes must begin with this string."""

    VCPU = 'VCPU'
    MEMORY_MB = 'MEMORY_MB'
    DISK_GB = 'DISK_GB'
    PCI_DEVICE = 'PCI_DEVICE'
    SRIOV_NET_VF = 'SRIOV_NET_VF'
    NUMA_SOCKET = 'NUMA_SOCKET'
    NUMA_CORE = 'NUMA_CORE'
    NUMA_THREAD = 'NUMA_THREAD'
    NUMA_MEMORY_MB = 'NUMA_MEMORY_MB'
    IPV4_ADDRESS = 'IPV4_ADDRESS'
    VGPU = 'VGPU'
    VGPU_DISPLAY_HEAD = 'VGPU_DISPLAY_HEAD'

    # The ordering here is relevant. If you must add a value, only
    # append.
    STANDARD = (VCPU, MEMORY_MB, DISK_GB, PCI_DEVICE, SRIOV_NET_VF,
                NUMA_SOCKET, NUMA_CORE, NUMA_THREAD, NUMA_MEMORY_MB,
                IPV4_ADDRESS, VGPU, VGPU_DISPLAY_HEAD)

    # This is the set of standard resource classes that existed before
    # we opened up for custom resource classes in version 1.1 of various
    # objects in nova/objects/resource_provider.py
    V1_0 = (VCPU, MEMORY_MB, DISK_GB, PCI_DEVICE, SRIOV_NET_VF, NUMA_SOCKET,
            NUMA_CORE, NUMA_THREAD, NUMA_MEMORY_MB, IPV4_ADDRESS)

    @classmethod
    def normalize_name(cls, rc_name):
        if rc_name is None:
            return None
        norm_name = rc_name.upper()
        cust_prefix = cls.CUSTOM_NAMESPACE
        norm_name = cust_prefix + norm_name
        # Replace some punctuation characters with underscores
        norm_name = re.sub('[^0-9A-Z]+', '_', norm_name)
        return norm_name


class RNGModel(BaseNovaEnum):

    VIRTIO = "virtio"

    ALL = (VIRTIO,)


class SCSIModel(BaseNovaEnum):

    BUSLOGIC = "buslogic"
    IBMVSCSI = "ibmvscsi"
    LSILOGIC = "lsilogic"
    LSISAS1068 = "lsisas1068"
    LSISAS1078 = "lsisas1078"
    VIRTIO_SCSI = "virtio-scsi"
    VMPVSCSI = "vmpvscsi"

    ALL = (BUSLOGIC, IBMVSCSI, LSILOGIC, LSISAS1068,
           LSISAS1078, VIRTIO_SCSI, VMPVSCSI)

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # vmware_adaptertype image property
        value = value.lower()
        if value == "lsilogicsas":
            value = SCSIModel.LSISAS1068
        elif value == "paravirtual":
            value = SCSIModel.VMPVSCSI

        return super(SCSIModel, self).coerce(obj, attr, value)


class SecureBoot(BaseNovaEnum):

    REQUIRED = "required"
    DISABLED = "disabled"
    OPTIONAL = "optional"

    ALL = (REQUIRED, DISABLED, OPTIONAL)


class VideoModel(BaseNovaEnum):

    CIRRUS = "cirrus"
    QXL = "qxl"
    VGA = "vga"
    VMVGA = "vmvga"
    XEN = "xen"

    ALL = (CIRRUS, QXL, VGA, VMVGA, XEN)


class VIFModel(BaseNovaEnum):

    LEGACY_VALUES = {"virtuale1000":
                     network_model.VIF_MODEL_E1000,
                     "virtuale1000e":
                     network_model.VIF_MODEL_E1000E,
                     "virtualpcnet32":
                     network_model.VIF_MODEL_PCNET,
                     "virtualsriovethernetcard":
                     network_model.VIF_MODEL_SRIOV,
                     "virtualvmxnet":
                     network_model.VIF_MODEL_VMXNET,
                     "virtualvmxnet3":
                     network_model.VIF_MODEL_VMXNET3,
                    }

    ALL = network_model.VIF_MODEL_ALL

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # hw_vif_model image property
        value = value.lower()
        value = VIFModel.LEGACY_VALUES.get(value, value)
        return super(VIFModel, self).coerce(obj, attr, value)


class VMMode(BaseNovaEnum):
    """Represents possible vm modes for instances.

    Compute instance VM modes represent the host/guest ABI used for the
    virtual machine or container. Individual hypervisors may support
    multiple different vm modes per host. Available VM modes for a
    hypervisor driver may also vary according to the architecture it is
    running on.
    """
    HVM = 'hvm'  # Native ABI (aka fully virtualized)
    XEN = 'xen'  # Xen 3.0 paravirtualized
    UML = 'uml'  # User Mode Linux paravirtualized
    EXE = 'exe'  # Executables in containers

    ALL = (HVM, XEN, UML, EXE)

    def coerce(self, obj, attr, value):
        try:
            value = self.canonicalize(value)
        except exception.InvalidVirtualMachineMode:
            msg = _("Virtual machine mode '%s' is not valid") % value
            raise ValueError(msg)

        return super(VMMode, self).coerce(obj, attr, value)

    @classmethod
    def get_from_instance(cls, instance):
        """Get the vm mode for an instance

        :param instance: instance object to query

        :returns: canonicalized vm mode for the instance
        """
        mode = instance.vm_mode

        return cls.canonicalize(mode)

    @classmethod
    def is_valid(cls, name):
        """Check if a string is a valid vm mode

        :param name: vm mode name to validate

        :returns: True if @name is valid
        """
        return name in cls.ALL

    @classmethod
    def canonicalize(cls, mode):
        """Canonicalize the vm mode

        :param name: vm mode name to canonicalize

        :returns: a canonical vm mode name
        """
        if mode is None:
            return None

        mode = mode.lower()

        # For compatibility with pre-Folsom deployments
        if mode == 'pv':
            mode = cls.XEN

        if mode == 'hv':
            mode = cls.HVM

        if mode == 'baremetal':
            mode = cls.HVM

        if not cls.is_valid(mode):
            raise exception.InvalidVirtualMachineMode(vmmode=mode)

        return mode


class WatchdogAction(BaseNovaEnum):

    NONE = "none"
    PAUSE = "pause"
    POWEROFF = "poweroff"
    RESET = "reset"
    DISABLED = "disabled"

    ALL = (NONE, PAUSE, POWEROFF, RESET, DISABLED)


class MonitorMetricType(BaseNovaEnum):

    CPU_FREQUENCY = "cpu.frequency"
    CPU_USER_TIME = "cpu.user.time"
    CPU_KERNEL_TIME = "cpu.kernel.time"
    CPU_IDLE_TIME = "cpu.idle.time"
    CPU_IOWAIT_TIME = "cpu.iowait.time"
    CPU_USER_PERCENT = "cpu.user.percent"
    CPU_KERNEL_PERCENT = "cpu.kernel.percent"
    CPU_IDLE_PERCENT = "cpu.idle.percent"
    CPU_IOWAIT_PERCENT = "cpu.iowait.percent"
    CPU_PERCENT = "cpu.percent"
    NUMA_MEM_BW_MAX = "numa.membw.max"
    NUMA_MEM_BW_CURRENT = "numa.membw.current"

    ALL = (
        CPU_FREQUENCY,
        CPU_USER_TIME,
        CPU_KERNEL_TIME,
        CPU_IDLE_TIME,
        CPU_IOWAIT_TIME,
        CPU_USER_PERCENT,
        CPU_KERNEL_PERCENT,
        CPU_IDLE_PERCENT,
        CPU_IOWAIT_PERCENT,
        CPU_PERCENT,
        NUMA_MEM_BW_MAX,
        NUMA_MEM_BW_CURRENT,
    )


class HostStatus(BaseNovaEnum):

    UP = "UP"  # The nova-compute is up.
    DOWN = "DOWN"  # The nova-compute is forced_down.
    MAINTENANCE = "MAINTENANCE"  # The nova-compute is disabled.
    UNKNOWN = "UNKNOWN"  # The nova-compute has not reported.
    NONE = ""  # No host or nova-compute.

    ALL = (UP, DOWN, MAINTENANCE, UNKNOWN, NONE)


class PciDeviceStatus(BaseNovaEnum):

    AVAILABLE = "available"
    CLAIMED = "claimed"
    ALLOCATED = "allocated"
    REMOVED = "removed"  # The device has been hot-removed and not yet deleted
    DELETED = "deleted"  # The device is marked not available/deleted.
    UNCLAIMABLE = "unclaimable"
    UNAVAILABLE = "unavailable"

    ALL = (AVAILABLE, CLAIMED, ALLOCATED, REMOVED, DELETED, UNAVAILABLE,
           UNCLAIMABLE)


class PciDeviceType(BaseNovaEnum):

    # NOTE(jaypipes): It's silly that the word "type-" is in these constants,
    # but alas, these were the original constant strings used...
    STANDARD = "type-PCI"
    SRIOV_PF = "type-PF"
    SRIOV_VF = "type-VF"

    ALL = (STANDARD, SRIOV_PF, SRIOV_VF)


class PCINUMAAffinityPolicy(BaseNovaEnum):

    REQUIRED = "required"
    LEGACY = "legacy"
    PREFERRED = "preferred"

    ALL = (REQUIRED, LEGACY, PREFERRED)


class DiskFormat(BaseNovaEnum):
    RBD = "rbd"
    LVM = "lvm"
    QCOW2 = "qcow2"
    RAW = "raw"
    PLOOP = "ploop"
    VHD = "vhd"
    VMDK = "vmdk"
    VDI = "vdi"
    ISO = "iso"

    ALL = (RBD, LVM, QCOW2, RAW, PLOOP, VHD, VMDK, VDI, ISO)


class HypervisorDriver(BaseNovaEnum):
    LIBVIRT = "libvirt"
    XENAPI = "xenapi"
    VMWAREAPI = "vmwareapi"
    IRONIC = "ironic"
    HYPERV = "hyperv"

    ALL = (LIBVIRT, XENAPI, VMWAREAPI, IRONIC, HYPERV)


class PointerModelType(BaseNovaEnum):

    USBTABLET = "usbtablet"

    ALL = (USBTABLET)


class NotificationPriority(BaseNovaEnum):
    AUDIT = 'audit'
    CRITICAL = 'critical'
    DEBUG = 'debug'
    INFO = 'info'
    ERROR = 'error'
    SAMPLE = 'sample'
    WARN = 'warn'

    ALL = (AUDIT, CRITICAL, DEBUG, INFO, ERROR, SAMPLE, WARN)


class NotificationPhase(BaseNovaEnum):
    START = 'start'
    END = 'end'
    ERROR = 'error'

    ALL = (START, END, ERROR)


class NotificationSource(BaseNovaEnum):
    """Represents possible nova binary service names in notification envelope.

    The publisher_id field of the nova notifications consists of the name of
    the host and the name of the service binary that emits the notification.
    The below values are the ones that is used in every notification. Please
    note that on the REST API the nova-api service binary is called
    nova-osapi_compute. This is not reflected here as notifications always used
    the name nova-api instead.
    """

    COMPUTE = 'nova-compute'
    API = 'nova-api'
    CONDUCTOR = 'nova-conductor'
    SCHEDULER = 'nova-scheduler'
    NETWORK = 'nova-network'
    CONSOLEAUTH = 'nova-consoleauth'
    CELLS = 'nova-cells'
    CONSOLE = 'nova-console'
    METADATA = 'nova-metadata'

    ALL = (API, COMPUTE, CONDUCTOR, SCHEDULER,
           NETWORK, CONSOLEAUTH, CELLS, CONSOLE, METADATA)

    @staticmethod
    def get_source_by_binary(binary):
        # nova-osapi_compute binary name needs to be translated to nova-api
        # notification source enum value.
        return "nova-api" if binary == "nova-osapi_compute" else binary


class NotificationAction(BaseNovaEnum):
    UPDATE = 'update'
    EXCEPTION = 'exception'
    DELETE = 'delete'
    PAUSE = 'pause'
    UNPAUSE = 'unpause'
    RESIZE = 'resize'
    VOLUME_SWAP = 'volume_swap'
    SUSPEND = 'suspend'
    POWER_ON = 'power_on'
    POWER_OFF = 'power_off'
    REBOOT = 'reboot'
    SHUTDOWN = 'shutdown'
    SNAPSHOT = 'snapshot'
    INTERFACE_ATTACH = 'interface_attach'
    SHELVE = 'shelve'
    RESUME = 'resume'
    RESTORE = 'restore'
    EXISTS = 'exists'
    RESCUE = 'rescue'
    VOLUME_ATTACH = 'volume_attach'
    VOLUME_DETACH = 'volume_detach'
    CREATE = 'create'
    IMPORT = 'import'
    EVACUATE = 'evacuate'
    RESIZE_FINISH = 'resize_finish'
    LIVE_MIGRATION_ABORT = 'live_migration_abort'
    LIVE_MIGRATION_POST_DEST = 'live_migration_post_dest'
    LIVE_MIGRATION_POST = 'live_migration_post'
    LIVE_MIGRATION_PRE = 'live_migration_pre'
    LIVE_MIGRATION_ROLLBACK_DEST = 'live_migration_rollback_dest'
    LIVE_MIGRATION_ROLLBACK = 'live_migration_rollback'
    REBUILD = 'rebuild'
    INTERFACE_DETACH = 'interface_detach'
    RESIZE_CONFIRM = 'resize_confirm'
    RESIZE_PREP = 'resize_prep'
    RESIZE_REVERT = 'resize_revert'
    SHELVE_OFFLOAD = 'shelve_offload'
    SOFT_DELETE = 'soft_delete'
    TRIGGER_CRASH_DUMP = 'trigger_crash_dump'
    UNRESCUE = 'unrescue'
    UNSHELVE = 'unshelve'
    ADD_HOST = 'add_host'
    REMOVE_HOST = 'remove_host'

    ALL = (UPDATE, EXCEPTION, DELETE, PAUSE, UNPAUSE, RESIZE, VOLUME_SWAP,
           SUSPEND, POWER_ON, REBOOT, SHUTDOWN, SNAPSHOT, INTERFACE_ATTACH,
           POWER_OFF, SHELVE, RESUME, RESTORE, EXISTS, RESCUE, VOLUME_ATTACH,
           VOLUME_DETACH, CREATE, IMPORT, EVACUATE, RESIZE_FINISH,
           LIVE_MIGRATION_ABORT, LIVE_MIGRATION_POST_DEST, LIVE_MIGRATION_POST,
           LIVE_MIGRATION_PRE, LIVE_MIGRATION_ROLLBACK,
           LIVE_MIGRATION_ROLLBACK_DEST, REBUILD, INTERFACE_DETACH,
           RESIZE_CONFIRM, RESIZE_PREP, RESIZE_REVERT, SHELVE_OFFLOAD,
           SOFT_DELETE, TRIGGER_CRASH_DUMP, UNRESCUE, UNSHELVE, ADD_HOST,
           REMOVE_HOST)


# TODO(rlrossit): These should be changed over to be a StateMachine enum from
# oslo.versionedobjects using the valid state transitions described in
# nova.compute.vm_states
class InstanceState(BaseNovaEnum):
    ACTIVE = 'active'
    BUILDING = 'building'
    PAUSED = 'paused'
    SUSPENDED = 'suspended'
    STOPPED = 'stopped'
    RESCUED = 'rescued'
    RESIZED = 'resized'
    SOFT_DELETED = 'soft-delete'
    DELETED = 'deleted'
    ERROR = 'error'
    SHELVED = 'shelved'
    SHELVED_OFFLOADED = 'shelved_offloaded'

    ALL = (ACTIVE, BUILDING, PAUSED, SUSPENDED, STOPPED, RESCUED, RESIZED,
           SOFT_DELETED, DELETED, ERROR, SHELVED, SHELVED_OFFLOADED)


# TODO(rlrossit): These should be changed over to be a StateMachine enum from
# oslo.versionedobjects using the valid state transitions described in
# nova.compute.task_states
class InstanceTaskState(BaseNovaEnum):
    SCHEDULING = 'scheduling'
    BLOCK_DEVICE_MAPPING = 'block_device_mapping'
    NETWORKING = 'networking'
    SPAWNING = 'spawning'
    IMAGE_SNAPSHOT = 'image_snapshot'
    IMAGE_SNAPSHOT_PENDING = 'image_snapshot_pending'
    IMAGE_PENDING_UPLOAD = 'image_pending_upload'
    IMAGE_UPLOADING = 'image_uploading'
    IMAGE_BACKUP = 'image_backup'
    UPDATING_PASSWORD = 'updating_password'
    RESIZE_PREP = 'resize_prep'
    RESIZE_MIGRATING = 'resize_migrating'
    RESIZE_MIGRATED = 'resize_migrated'
    RESIZE_FINISH = 'resize_finish'
    RESIZE_REVERTING = 'resize_reverting'
    RESIZE_CONFIRMING = 'resize_confirming'
    REBOOTING = 'rebooting'
    REBOOT_PENDING = 'reboot_pending'
    REBOOT_STARTED = 'reboot_started'
    REBOOTING_HARD = 'rebooting_hard'
    REBOOT_PENDING_HARD = 'reboot_pending_hard'
    REBOOT_STARTED_HARD = 'reboot_started_hard'
    PAUSING = 'pausing'
    UNPAUSING = 'unpausing'
    SUSPENDING = 'suspending'
    RESUMING = 'resuming'
    POWERING_OFF = 'powering-off'
    POWERING_ON = 'powering-on'
    RESCUING = 'rescuing'
    UNRESCUING = 'unrescuing'
    REBUILDING = 'rebuilding'
    REBUILD_BLOCK_DEVICE_MAPPING = "rebuild_block_device_mapping"
    REBUILD_SPAWNING = 'rebuild_spawning'
    MIGRATING = "migrating"
    DELETING = 'deleting'
    SOFT_DELETING = 'soft-deleting'
    RESTORING = 'restoring'
    SHELVING = 'shelving'
    SHELVING_IMAGE_PENDING_UPLOAD = 'shelving_image_pending_upload'
    SHELVING_IMAGE_UPLOADING = 'shelving_image_uploading'
    SHELVING_OFFLOADING = 'shelving_offloading'
    UNSHELVING = 'unshelving'

    ALL = (SCHEDULING, BLOCK_DEVICE_MAPPING, NETWORKING, SPAWNING,
           IMAGE_SNAPSHOT, IMAGE_SNAPSHOT_PENDING, IMAGE_PENDING_UPLOAD,
           IMAGE_UPLOADING, IMAGE_BACKUP, UPDATING_PASSWORD, RESIZE_PREP,
           RESIZE_MIGRATING, RESIZE_MIGRATED, RESIZE_FINISH, RESIZE_REVERTING,
           RESIZE_CONFIRMING, REBOOTING, REBOOT_PENDING, REBOOT_STARTED,
           REBOOTING_HARD, REBOOT_PENDING_HARD, REBOOT_STARTED_HARD, PAUSING,
           UNPAUSING, SUSPENDING, RESUMING, POWERING_OFF, POWERING_ON,
           RESCUING, UNRESCUING, REBUILDING, REBUILD_BLOCK_DEVICE_MAPPING,
           REBUILD_SPAWNING, MIGRATING, DELETING, SOFT_DELETING, RESTORING,
           SHELVING, SHELVING_IMAGE_PENDING_UPLOAD, SHELVING_IMAGE_UPLOADING,
           SHELVING_OFFLOADING, UNSHELVING)


class InstancePowerState(Enum):
    _UNUSED = '_unused'
    NOSTATE = 'pending'
    RUNNING = 'running'
    PAUSED = 'paused'
    SHUTDOWN = 'shutdown'
    CRASHED = 'crashed'
    SUSPENDED = 'suspended'
    # The order is important here. If you make changes, only *append*
    # values to the end of the list.
    ALL = (
        NOSTATE,
        RUNNING,
        _UNUSED,
        PAUSED,
        SHUTDOWN,
        _UNUSED,
        CRASHED,
        SUSPENDED,
    )

    def __init__(self):
        super(InstancePowerState, self).__init__(
            valid_values=InstancePowerState.ALL)

    def coerce(self, obj, attr, value):
        try:
            value = int(value)
            value = self.from_index(value)
        except (ValueError, KeyError):
            pass
        return super(InstancePowerState, self).coerce(obj, attr, value)

    @classmethod
    def index(cls, value):
        """Return an index into the Enum given a value."""
        return cls.ALL.index(value)

    @classmethod
    def from_index(cls, index):
        """Return the Enum value at a given index."""
        return cls.ALL[index]


class NetworkModel(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, network_model.NetworkInfo):
            return value
        elif isinstance(value, six.string_types):
            # Hmm, do we need this?
            return network_model.NetworkInfo.hydrate(value)
        else:
            raise ValueError(_('A NetworkModel is required in field %s') %
                             attr)

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.json()

    @staticmethod
    def from_primitive(obj, attr, value):
        return network_model.NetworkInfo.hydrate(value)

    def stringify(self, value):
        return 'NetworkModel(%s)' % (
            ','.join([str(vif['id']) for vif in value]))

    def get_schema(self):
        return {'type': ['string']}


class AddressBase(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if re.match(obj.PATTERN, str(value)):
            return str(value)
        else:
            raise ValueError(_('Value must match %s') % obj.PATTERN)

    def get_schema(self):
        return {'type': ['string'], 'pattern': self.PATTERN}


class USBAddress(AddressBase):
    PATTERN = '[a-f0-9]+:[a-f0-9]+'

    @staticmethod
    def coerce(obj, attr, value):
        return AddressBase.coerce(USBAddress, attr, value)


class SCSIAddress(AddressBase):
    PATTERN = '[a-f0-9]+:[a-f0-9]+:[a-f0-9]+:[a-f0-9]+'

    @staticmethod
    def coerce(obj, attr, value):
        return AddressBase.coerce(SCSIAddress, attr, value)


class IDEAddress(AddressBase):
    PATTERN = '[0-1]:[0-1]'

    @staticmethod
    def coerce(obj, attr, value):
        return AddressBase.coerce(IDEAddress, attr, value)


class XenAddress(AddressBase):
    PATTERN = '(00[0-9]{2}00)|[1-9][0-9]+'

    @staticmethod
    def coerce(obj, attr, value):
        return AddressBase.coerce(XenAddress, attr, value)


class USBAddressField(AutoTypedField):
    AUTO_TYPE = USBAddress()


class SCSIAddressField(AutoTypedField):
    AUTO_TYPE = SCSIAddress()


class IDEAddressField(AutoTypedField):
    AUTO_TYPE = IDEAddress()


class XenAddressField(AutoTypedField):
    AUTO_TYPE = XenAddress()


class ArchitectureField(BaseEnumField):
    AUTO_TYPE = Architecture()


class BlockDeviceDestinationTypeField(BaseEnumField):
    AUTO_TYPE = BlockDeviceDestinationType()


class BlockDeviceSourceTypeField(BaseEnumField):
    AUTO_TYPE = BlockDeviceSourceType()


class BlockDeviceTypeField(BaseEnumField):
    AUTO_TYPE = BlockDeviceType()


class ConfigDrivePolicyField(BaseEnumField):
    AUTO_TYPE = ConfigDrivePolicy()


class CPUAllocationPolicyField(BaseEnumField):
    AUTO_TYPE = CPUAllocationPolicy()


class CPUThreadAllocationPolicyField(BaseEnumField):
    AUTO_TYPE = CPUThreadAllocationPolicy()


class CPUEmulatorThreadsPolicyField(BaseEnumField):
    AUTO_TYPE = CPUEmulatorThreadsPolicy()


class CPUModeField(BaseEnumField):
    AUTO_TYPE = CPUMode()


class CPUMatchField(BaseEnumField):
    AUTO_TYPE = CPUMatch()


class CPUFeaturePolicyField(BaseEnumField):
    AUTO_TYPE = CPUFeaturePolicy()


class DiskBusField(BaseEnumField):
    AUTO_TYPE = DiskBus()


class DiskConfigField(BaseEnumField):
    AUTO_TYPE = DiskConfig()


class FirmwareTypeField(BaseEnumField):
    AUTO_TYPE = FirmwareType()


class HVTypeField(BaseEnumField):
    AUTO_TYPE = HVType()


class ImageSignatureHashTypeField(BaseEnumField):
    AUTO_TYPE = ImageSignatureHashType()


class ImageSignatureKeyTypeField(BaseEnumField):
    AUTO_TYPE = ImageSignatureKeyType()


class OSTypeField(BaseEnumField):
    AUTO_TYPE = OSType()


class ResourceClassField(AutoTypedField):
    AUTO_TYPE = ResourceClass()


class RNGModelField(BaseEnumField):
    AUTO_TYPE = RNGModel()


class SCSIModelField(BaseEnumField):
    AUTO_TYPE = SCSIModel()


class SecureBootField(BaseEnumField):
    AUTO_TYPE = SecureBoot()


class VideoModelField(BaseEnumField):
    AUTO_TYPE = VideoModel()


class VIFModelField(BaseEnumField):
    AUTO_TYPE = VIFModel()


class VMModeField(BaseEnumField):
    AUTO_TYPE = VMMode()


class WatchdogActionField(BaseEnumField):
    AUTO_TYPE = WatchdogAction()


class MonitorMetricTypeField(BaseEnumField):
    AUTO_TYPE = MonitorMetricType()


class PciDeviceStatusField(BaseEnumField):
    AUTO_TYPE = PciDeviceStatus()


class PciDeviceTypeField(BaseEnumField):
    AUTO_TYPE = PciDeviceType()


class PCINUMAAffinityPolicyField(BaseEnumField):
    AUTO_TYPE = PCINUMAAffinityPolicy()


class DiskFormatField(BaseEnumField):
    AUTO_TYPE = DiskFormat()


class HypervisorDriverField(BaseEnumField):
    AUTO_TYPE = HypervisorDriver()


class PointerModelField(BaseEnumField):
    AUTO_TYPE = PointerModelType()


class NotificationPriorityField(BaseEnumField):
    AUTO_TYPE = NotificationPriority()


class NotificationPhaseField(BaseEnumField):
    AUTO_TYPE = NotificationPhase()


class NotificationActionField(BaseEnumField):
    AUTO_TYPE = NotificationAction()


class NotificationSourceField(BaseEnumField):
    AUTO_TYPE = NotificationSource()


class InstanceStateField(BaseEnumField):
    AUTO_TYPE = InstanceState()


class InstanceTaskStateField(BaseEnumField):
    AUTO_TYPE = InstanceTaskState()


class InstancePowerStateField(BaseEnumField):
    AUTO_TYPE = InstancePowerState()
