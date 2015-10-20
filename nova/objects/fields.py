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

from oslo_versionedobjects import fields
import re
import six

# TODO(berrange) Temporary import for Arch class
from nova.compute import arch
# TODO(berrange) Temporary import for CPU* classes
from nova.compute import cpumodel
# TODO(berrange) Temporary import for HVType class
from nova.compute import hv_type
# TODO(berrange) Temporary import for VMMode class
from nova.compute import vm_mode
from nova import exception
from nova.i18n import _
from nova.network import model as network_model


# Import field errors from oslo.versionedobjects
KeyTypeError = fields.KeyTypeError
ElementTypeError = fields.ElementTypeError


# Import fields from oslo.versionedobjects
BooleanField = fields.BooleanField
UnspecifiedDefault = fields.UnspecifiedDefault
IntegerField = fields.IntegerField
UUIDField = fields.UUIDField
FloatField = fields.FloatField
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
IPNetworkField = fields.IPNetworkField
IPV4NetworkField = fields.IPV4NetworkField
IPV6NetworkField = fields.IPV6NetworkField
AutoTypedField = fields.AutoTypedField
BaseEnumField = fields.BaseEnumField
MACAddressField = fields.MACAddressField


# NOTE(danms): These are things we need to import for some of our
# own implementations below, our tests, or other transitional
# bits of code. These should be removable after we finish our
# conversion
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


class Architecture(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.arch'
    # into fields on this class
    def __init__(self, **kwargs):
        super(Architecture, self).__init__(
            valid_values=arch.ALL, **kwargs)

    def coerce(self, obj, attr, value):
        try:
            value = arch.canonicalize(value)
        except exception.InvalidArchitectureName:
            msg = _("Architecture name '%s' is not valid") % value
            raise ValueError(msg)
        return super(Architecture, self).coerce(obj, attr, value)


class BlockDeviceDestinationType(Enum):
    """Represents possible destination_type values for a BlockDeviceMapping."""

    LOCAL = 'local'
    VOLUME = 'volume'

    ALL = (LOCAL, VOLUME)

    def __init__(self):
        super(BlockDeviceDestinationType, self).__init__(
            valid_values=BlockDeviceDestinationType.ALL)


class BlockDeviceSourceType(Enum):
    """Represents the possible source_type values for a BlockDeviceMapping."""

    BLANK = 'blank'
    IMAGE = 'image'
    SNAPSHOT = 'snapshot'
    VOLUME = 'volume'

    ALL = (BLANK, IMAGE, SNAPSHOT, VOLUME)

    def __init__(self):
        super(BlockDeviceSourceType, self).__init__(
            valid_values=BlockDeviceSourceType.ALL)


class BlockDeviceType(Enum):
    """Represents possible device_type values for a BlockDeviceMapping."""

    CDROM = 'cdrom'
    DISK = 'disk'
    FLOPPY = 'floppy'
    FS = 'fs'
    LUN = 'lun'

    ALL = (CDROM, DISK, FLOPPY, FS, LUN)

    def __init__(self):
        super(BlockDeviceType, self).__init__(
            valid_values=BlockDeviceType.ALL)


class ConfigDrivePolicy(Enum):
    OPTIONAL = "optional"
    MANDATORY = "mandatory"

    ALL = (OPTIONAL, MANDATORY)

    def __init__(self):
        super(ConfigDrivePolicy, self).__init__(
            valid_values=ConfigDrivePolicy.ALL)


class CPUAllocationPolicy(Enum):

    DEDICATED = "dedicated"
    SHARED = "shared"

    ALL = (DEDICATED, SHARED)

    def __init__(self):
        super(CPUAllocationPolicy, self).__init__(
            valid_values=CPUAllocationPolicy.ALL)


class CPUThreadAllocationPolicy(Enum):

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

    def __init__(self):
        super(CPUThreadAllocationPolicy, self).__init__(
            valid_values=CPUThreadAllocationPolicy.ALL)


class CPUMode(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUMode, self).__init__(
            valid_values=cpumodel.ALL_CPUMODES, **kwargs)


class CPUMatch(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUMatch, self).__init__(
            valid_values=cpumodel.ALL_MATCHES, **kwargs)


class CPUFeaturePolicy(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.cpumodel'
    # into fields on this class
    def __init__(self, **kwargs):
        super(CPUFeaturePolicy, self).__init__(
            valid_values=cpumodel.ALL_POLICIES, **kwargs)


class DiskBus(Enum):

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

    def __init__(self):
        super(DiskBus, self).__init__(
            valid_values=DiskBus.ALL)


class FirmwareType(Enum):

    UEFI = "uefi"
    BIOS = "bios"

    ALL = (UEFI, BIOS)

    def __init__(self):
        super(FirmwareType, self).__init__(
            valid_values=FirmwareType.ALL)


class HVType(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.hv_type'
    # into fields on this class
    def __init__(self):
        super(HVType, self).__init__(
            valid_values=hv_type.ALL)

    def coerce(self, obj, attr, value):
        try:
            value = hv_type.canonicalize(value)
        except exception.InvalidHypervisorVirtType:
            msg = _("Hypervisor virt type '%s' is not valid") % value
            raise ValueError(msg)
        return super(HVType, self).coerce(obj, attr, value)


class ImageSignatureHashType(Enum):
    # Represents the possible hash methods used for image signing
    def __init__(self):
        self.hashes = ('SHA-224', 'SHA-256', 'SHA-384', 'SHA-512')
        super(ImageSignatureHashType, self).__init__(
            valid_values=self.hashes
        )


class ImageSignatureKeyType(Enum):
    # Represents the possible keypair types used for image signing
    def __init__(self):
        self.key_types = (
            'DSA', 'ECC_SECT571K1', 'ECC_SECT409K1', 'ECC_SECT571R1',
            'ECC_SECT409R1', 'ECC_SECP521R1', 'ECC_SECP384R1', 'RSA-PSS'
        )
        super(ImageSignatureKeyType, self).__init__(
            valid_values=self.key_types
        )


class OSType(Enum):

    LINUX = "linux"
    WINDOWS = "windows"

    ALL = (LINUX, WINDOWS)

    def __init__(self):
        super(OSType, self).__init__(
            valid_values=OSType.ALL)

    def coerce(self, obj, attr, value):
        # Some code/docs use upper case or initial caps
        # so canonicalize to all lower case
        value = value.lower()
        return super(OSType, self).coerce(obj, attr, value)


class ResourceClass(Enum):
    """Classes of resources provided to consumers."""

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

    # The ordering here is relevant. If you must add a value, only
    # append.
    ALL = (VCPU, MEMORY_MB, DISK_GB, PCI_DEVICE, SRIOV_NET_VF, NUMA_SOCKET,
           NUMA_CORE, NUMA_THREAD, NUMA_MEMORY_MB, IPV4_ADDRESS)

    def __init__(self):
        super(ResourceClass, self).__init__(
            valid_values=ResourceClass.ALL)

    @classmethod
    def index(cls, value):
        """Return an index into the Enum given a value."""
        return cls.ALL.index(value)

    @classmethod
    def from_index(cls, index):
        """Return the Enum value at a given index."""
        return cls.ALL[index]


class RNGModel(Enum):

    VIRTIO = "virtio"

    ALL = (VIRTIO,)

    def __init__(self):
        super(RNGModel, self).__init__(
            valid_values=RNGModel.ALL)


class SCSIModel(Enum):

    BUSLOGIC = "buslogic"
    IBMVSCSI = "ibmvscsi"
    LSILOGIC = "lsilogic"
    LSISAS1068 = "lsisas1068"
    LSISAS1078 = "lsisas1078"
    VIRTIO_SCSI = "virtio-scsi"
    VMPVSCSI = "vmpvscsi"

    ALL = (BUSLOGIC, IBMVSCSI, LSILOGIC, LSISAS1068,
           LSISAS1078, VIRTIO_SCSI, VMPVSCSI)

    def __init__(self):
        super(SCSIModel, self).__init__(
            valid_values=SCSIModel.ALL)

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # vmware_adaptertype image property
        value = value.lower()
        if value == "lsilogicsas":
            value = SCSIModel.LSISAS1068
        elif value == "paravirtual":
            value = SCSIModel.VMPVSCSI

        return super(SCSIModel, self).coerce(obj, attr, value)


class SecureBoot(Enum):

    REQUIRED = "required"
    DISABLED = "disabled"
    OPTIONAL = "optional"

    ALL = (REQUIRED, DISABLED, OPTIONAL)

    def __init__(self):
        super(SecureBoot, self).__init__(valid_values=SecureBoot.ALL)


class VideoModel(Enum):

    CIRRUS = "cirrus"
    QXL = "qxl"
    VGA = "vga"
    VMVGA = "vmvga"
    XEN = "xen"

    ALL = (CIRRUS, QXL, VGA, VMVGA, XEN)

    def __init__(self):
        super(VideoModel, self).__init__(
            valid_values=VideoModel.ALL)


class VIFModel(Enum):

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

    def __init__(self):
        super(VIFModel, self).__init__(
            valid_values=network_model.VIF_MODEL_ALL)

    def _get_legacy(self, value):
        return value

    def coerce(self, obj, attr, value):
        # Some compat for strings we'd see in the legacy
        # hw_vif_model image property
        value = value.lower()
        value = VIFModel.LEGACY_VALUES.get(value, value)
        return super(VIFModel, self).coerce(obj, attr, value)


class VMMode(Enum):
    # TODO(berrange): move all constants out of 'nova.compute.vm_mode'
    # into fields on this class
    def __init__(self):
        super(VMMode, self).__init__(
            valid_values=vm_mode.ALL)

    def coerce(self, obj, attr, value):
        try:
            value = vm_mode.canonicalize(value)
        except exception.InvalidVirtualMachineMode:
            msg = _("Virtual machine mode '%s' is not valid") % value
            raise ValueError(msg)
        return super(VMMode, self).coerce(obj, attr, value)


class WatchdogAction(Enum):

    NONE = "none"
    PAUSE = "pause"
    POWEROFF = "poweroff"
    RESET = "reset"

    ALL = (NONE, PAUSE, POWEROFF, RESET)

    def __init__(self):
        super(WatchdogAction, self).__init__(
            valid_values=WatchdogAction.ALL)


class MonitorMetricType(Enum):

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

    def __init__(self):
        super(MonitorMetricType, self).__init__(
            valid_values=MonitorMetricType.ALL)


class HostStatus(Enum):

    UP = "UP"  # The nova-compute is up.
    DOWN = "DOWN"  # The nova-compute is forced_down.
    MAINTENANCE = "MAINTENANCE"  # The nova-compute is disabled.
    UNKNOWN = "UNKNOWN"  # The nova-compute has not reported.
    NONE = ""  # No host or nova-compute.

    ALL = (UP, DOWN, MAINTENANCE, UNKNOWN, NONE)

    def __init__(self):
        super(HostStatus, self).__init__(
            valid_values=HostStatus.ALL)


class PciDeviceStatus(Enum):

    AVAILABLE = "available"
    CLAIMED = "claimed"
    ALLOCATED = "allocated"
    REMOVED = "removed"  # The device has been hot-removed and not yet deleted
    DELETED = "deleted"  # The device is marked not available/deleted.
    UNCLAIMABLE = "unclaimable"
    UNAVAILABLE = "unavailable"

    ALL = (AVAILABLE, CLAIMED, ALLOCATED, REMOVED, DELETED, UNAVAILABLE,
           UNCLAIMABLE)

    def __init__(self):
        super(PciDeviceStatus, self).__init__(
            valid_values=PciDeviceStatus.ALL)


class PciDeviceType(Enum):

    # NOTE(jaypipes): It's silly that the word "type-" is in these constants,
    # but alas, these were the original constant strings used...
    STANDARD = "type-PCI"
    SRIOV_PF = "type-PF"
    SRIOV_VF = "type-VF"

    ALL = (STANDARD, SRIOV_PF, SRIOV_VF)

    def __init__(self):
        super(PciDeviceType, self).__init__(
            valid_values=PciDeviceType.ALL)


class DiskFormat(Enum):
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

    def __init__(self):
        super(DiskFormat, self).__init__(
            valid_values=DiskFormat.ALL)


class NotificationPriority(Enum):
    AUDIT = 'audit'
    CRITICAL = 'critical'
    DEBUG = 'debug'
    INFO = 'info'
    ERROR = 'error'
    SAMPLE = 'sample'
    WARN = 'warn'

    ALL = (AUDIT, CRITICAL, DEBUG, INFO, ERROR, SAMPLE, WARN)

    def __init__(self):
        super(NotificationPriority, self).__init__(
            valid_values=NotificationPriority.ALL)


class NotificationPhase(Enum):
    START = 'start'
    END = 'end'
    ERROR = 'error'

    ALL = (START, END, ERROR)

    def __init__(self):
        super(NotificationPhase, self).__init__(
            valid_values=NotificationPhase.ALL)


class NotificationAction(Enum):
    UPDATE = 'update'

    ALL = (UPDATE,)

    def __init__(self):
        super(NotificationAction, self).__init__(
            valid_values=NotificationAction.ALL)


class IPV4AndV6Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 4 and result.version != 6:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


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


class NonNegativeFloat(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        v = float(value)
        if v < 0:
            raise ValueError(_('Value must be >= 0 for field %s') % attr)
        return v


class NonNegativeInteger(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        v = int(value)
        if v < 0:
            raise ValueError(_('Value must be >= 0 for field %s') % attr)
        return v


class AddressBase(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if re.match(obj.PATTERN, str(value)):
            return str(value)
        else:
            raise ValueError(_('Value must match %s') % obj.PATTERN)


class PCIAddress(AddressBase):
    PATTERN = '[a-f0-9]{4}:[a-f0-9]{2}:[a-f0-9]{2}.[a-f0-9]'

    @staticmethod
    def coerce(obj, attr, value):
        return AddressBase.coerce(PCIAddress, attr, value)


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


class PCIAddressField(AutoTypedField):
    AUTO_TYPE = PCIAddress()


class USBAddressField(AutoTypedField):
    AUTO_TYPE = USBAddress()


class SCSIAddressField(AutoTypedField):
    AUTO_TYPE = SCSIAddress()


class IDEAddressField(AutoTypedField):
    AUTO_TYPE = IDEAddress()


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


class CPUModeField(BaseEnumField):
    AUTO_TYPE = CPUMode()


class CPUMatchField(BaseEnumField):
    AUTO_TYPE = CPUMatch()


class CPUFeaturePolicyField(BaseEnumField):
    AUTO_TYPE = CPUFeaturePolicy()


class DiskBusField(BaseEnumField):
    AUTO_TYPE = DiskBus()


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


class ResourceClassField(BaseEnumField):
    AUTO_TYPE = ResourceClass()

    def index(self, value):
        """Return an index into the Enum given a value."""
        return self._type.index(value)

    def from_index(self, index):
        """Return the Enum value at a given index."""
        return self._type.from_index(index)


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


class DiskFormatField(BaseEnumField):
    AUTO_TYPE = DiskFormat()


class NotificationPriorityField(BaseEnumField):
    AUTO_TYPE = NotificationPriority()


class NotificationPhaseField(BaseEnumField):
    AUTO_TYPE = NotificationPhase()


class NotificationActionField(BaseEnumField):
    AUTO_TYPE = NotificationAction()


class IPV4AndV6AddressField(AutoTypedField):
    AUTO_TYPE = IPV4AndV6Address()


class ListOfIntegersField(AutoTypedField):
    AUTO_TYPE = List(fields.Integer())


class NonNegativeFloatField(AutoTypedField):
    AUTO_TYPE = NonNegativeFloat()


class NonNegativeIntegerField(AutoTypedField):
    AUTO_TYPE = NonNegativeInteger()
