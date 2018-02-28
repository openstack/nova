# Copyright 2014 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from oslo_utils import versionutils
import six

from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import utils
from nova.virt import hardware


NULLABLE_STRING_FIELDS = ['name', 'checksum', 'owner',
                          'container_format', 'disk_format']
NULLABLE_INTEGER_FIELDS = ['size', 'virtual_size']


@base.NovaObjectRegistry.register
class ImageMeta(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: updated ImageMetaProps
    # Version 1.2: ImageMetaProps version 1.2
    # Version 1.3: ImageMetaProps version 1.3
    # Version 1.4: ImageMetaProps version 1.4
    # Version 1.5: ImageMetaProps version 1.5
    # Version 1.6: ImageMetaProps version 1.6
    # Version 1.7: ImageMetaProps version 1.7
    # Version 1.8: ImageMetaProps version 1.8
    VERSION = '1.8'

    # These are driven by what the image client API returns
    # to Nova from Glance. This is defined in the glance
    # code glance/api/v2/images.py get_base_properties()
    # method. A few things are currently left out:
    # self, file, schema - Nova does not appear to ever use
    # these field; locations - modelling the arbitrary
    # data in the 'metadata' subfield is non-trivial as
    # there's no clear spec.
    #
    # TODO(ft): In version 2.0, these fields should be nullable:
    # name, checksum, owner, size, virtual_size, container_format, disk_format
    #
    fields = {
        'id': fields.UUIDField(),
        'name': fields.StringField(),
        'status': fields.StringField(),
        'visibility': fields.StringField(),
        'protected': fields.FlexibleBooleanField(),
        'checksum': fields.StringField(),
        'owner': fields.StringField(),
        'size': fields.IntegerField(),
        'virtual_size': fields.IntegerField(),
        'container_format': fields.StringField(),
        'disk_format': fields.StringField(),
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'tags': fields.ListOfStringsField(),
        'direct_url': fields.StringField(),
        'min_ram': fields.IntegerField(),
        'min_disk': fields.IntegerField(),
        'properties': fields.ObjectField('ImageMetaProps'),
    }

    @classmethod
    def from_dict(cls, image_meta):
        """Create instance from image metadata dict

        :param image_meta: image metadata dictionary

        Creates a new object instance, initializing from the
        properties associated with the image metadata instance

        :returns: an ImageMeta instance
        """
        if image_meta is None:
            image_meta = {}

        # We must turn 'properties' key dict into an object
        # so copy image_meta to avoid changing original
        image_meta = copy.deepcopy(image_meta)
        image_meta["properties"] = \
            objects.ImageMetaProps.from_dict(
                image_meta.get("properties", {}))

        # Some fields are nullable in Glance DB schema, but was not marked that
        # in ImageMeta initially by mistake. To keep compatibility with compute
        # nodes which are run with previous versions these fields are still
        # not nullable in ImageMeta, but the code below converts None to
        # appropriate empty values.
        for fld in NULLABLE_STRING_FIELDS:
            if fld in image_meta and image_meta[fld] is None:
                image_meta[fld] = ''
        for fld in NULLABLE_INTEGER_FIELDS:
            if fld in image_meta and image_meta[fld] is None:
                image_meta[fld] = 0

        return cls(**image_meta)

    @classmethod
    def from_instance(cls, instance):
        """Create instance from instance system metadata

        :param instance: Instance object

        Creates a new object instance, initializing from the
        system metadata "image_*" properties associated with
        instance

        :returns: an ImageMeta instance
        """
        sysmeta = utils.instance_sys_meta(instance)
        image_meta = utils.get_image_from_system_metadata(sysmeta)
        return cls.from_dict(image_meta)

    @classmethod
    def from_image_ref(cls, context, image_api, image_ref):
        """Create instance from glance image

        :param context: the request context
        :param image_api: the glance client API
        :param image_ref: the glance image identifier

        Creates a new object instance, initializing from the
        properties associated with a glance image

        :returns: an ImageMeta instance
        """

        image_meta = image_api.get(context, image_ref)
        image = cls.from_dict(image_meta)
        setattr(image, "id", image_ref)
        return image


@base.NovaObjectRegistry.register
class ImageMetaProps(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: added os_require_quiesce field
    # Version 1.2: added img_hv_type and img_hv_requested_version fields
    # Version 1.3: HVSpec version 1.1
    # Version 1.4: added hw_vif_multiqueue_enabled field
    # Version 1.5: added os_admin_user field
    # Version 1.6: Added 'lxc' and 'uml' enum types to DiskBusField
    # Version 1.7: added img_config_drive field
    # Version 1.8: Added 'lxd' to hypervisor types
    # Version 1.9: added hw_cpu_thread_policy field
    # Version 1.10: added hw_cpu_realtime_mask field
    # Version 1.11: Added hw_firmware_type field
    # Version 1.12: Added properties for image signature verification
    # Version 1.13: added os_secure_boot field
    # Version 1.14: Added 'hw_pointer_model' field
    # Version 1.15: Added hw_rescue_bus and hw_rescue_device.
    # Version 1.16: WatchdogActionField supports 'disabled' enum.
    # Version 1.17: Add lan9118 as valid nic for hw_vif_model property for qemu
    # Version 1.18: Pull signature properties from cursive library
    # Version 1.19: Added 'img_hide_hypervisor_id' type field
    # Version 1.20: Added 'traits_required' list field
    VERSION = '1.20'

    def obj_make_compatible(self, primitive, target_version):
        super(ImageMetaProps, self).obj_make_compatible(primitive,
                                                        target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 20):
            primitive.pop('traits_required', None)
        if target_version < (1, 19):
            primitive.pop('img_hide_hypervisor_id', None)
        if target_version < (1, 16) and 'hw_watchdog_action' in primitive:
            # Check to see if hw_watchdog_action was set to 'disabled' and if
            # so, remove it since not specifying it is the same behavior.
            if primitive['hw_watchdog_action'] == \
                    fields.WatchdogAction.DISABLED:
                primitive.pop('hw_watchdog_action')
        if target_version < (1, 15):
            primitive.pop('hw_rescue_bus', None)
            primitive.pop('hw_rescue_device', None)
        if target_version < (1, 14):
            primitive.pop('hw_pointer_model', None)
        if target_version < (1, 13):
            primitive.pop('os_secure_boot', None)
        if target_version < (1, 11):
            primitive.pop('hw_firmware_type', None)
        if target_version < (1, 10):
            primitive.pop('hw_cpu_realtime_mask', None)
        if target_version < (1, 9):
            primitive.pop('hw_cpu_thread_policy', None)
        if target_version < (1, 7):
            primitive.pop('img_config_drive', None)
        if target_version < (1, 5):
            primitive.pop('os_admin_user', None)
        if target_version < (1, 4):
            primitive.pop('hw_vif_multiqueue_enabled', None)
        if target_version < (1, 2):
            primitive.pop('img_hv_type', None)
            primitive.pop('img_hv_requested_version', None)
        if target_version < (1, 1):
            primitive.pop('os_require_quiesce', None)

        if target_version < (1, 6):
            bus = primitive.get('hw_disk_bus', None)
            if bus in ('lxc', 'uml'):
                raise exception.ObjectActionError(
                    action='obj_make_compatible',
                    reason='hw_disk_bus=%s not supported in version %s' % (
                        bus, target_version))

    # Maximum number of NUMA nodes permitted for the guest topology
    NUMA_NODES_MAX = 128

    # 'hw_' - settings affecting the guest virtual machine hardware
    # 'img_' - settings affecting the use of images by the compute node
    # 'os_' - settings affecting the guest operating system setup
    # 'traits_required' - The required traits associated with the image

    fields = {
        # name of guest hardware architecture eg i686, x86_64, ppc64
        'hw_architecture': fields.ArchitectureField(),

        # used to decide to expand root disk partition and fs to full size of
        # root disk
        'hw_auto_disk_config': fields.StringField(),

        # whether to display BIOS boot device menu
        'hw_boot_menu': fields.FlexibleBooleanField(),

        # name of the CDROM bus to use eg virtio, scsi, ide
        'hw_cdrom_bus': fields.DiskBusField(),

        # preferred number of CPU cores per socket
        'hw_cpu_cores': fields.IntegerField(),

        # preferred number of CPU sockets
        'hw_cpu_sockets': fields.IntegerField(),

        # maximum number of CPU cores per socket
        'hw_cpu_max_cores': fields.IntegerField(),

        # maximum number of CPU sockets
        'hw_cpu_max_sockets': fields.IntegerField(),

        # maximum number of CPU threads per core
        'hw_cpu_max_threads': fields.IntegerField(),

        # CPU allocation policy
        'hw_cpu_policy': fields.CPUAllocationPolicyField(),

        # CPU thread allocation policy
        'hw_cpu_thread_policy': fields.CPUThreadAllocationPolicyField(),

        # CPU mask indicates which vCPUs will have realtime enable,
        # example ^0-1 means that all vCPUs except 0 and 1 will have a
        # realtime policy.
        'hw_cpu_realtime_mask': fields.StringField(),

        # preferred number of CPU threads per core
        'hw_cpu_threads': fields.IntegerField(),

        # guest ABI version for guest xentools either 1 or 2 (or 3 - depends on
        # Citrix PV tools version installed in image)
        'hw_device_id': fields.IntegerField(),

        # name of the hard disk bus to use eg virtio, scsi, ide
        'hw_disk_bus': fields.DiskBusField(),

        # allocation mode eg 'preallocated'
        'hw_disk_type': fields.StringField(),

        # name of the floppy disk bus to use eg fd, scsi, ide
        'hw_floppy_bus': fields.DiskBusField(),

        # This indicates the guest needs UEFI firmware
        'hw_firmware_type': fields.FirmwareTypeField(),

        # boolean - used to trigger code to inject networking when booting a CD
        # image with a network boot image
        'hw_ipxe_boot': fields.FlexibleBooleanField(),

        # There are sooooooooooo many possible machine types in
        # QEMU - several new ones with each new release - that it
        # is not practical to enumerate them all. So we use a free
        # form string
        'hw_machine_type': fields.StringField(),

        # One of the magic strings 'small', 'any', 'large'
        # or an explicit page size in KB (eg 4, 2048, ...)
        'hw_mem_page_size': fields.StringField(),

        # Number of guest NUMA nodes
        'hw_numa_nodes': fields.IntegerField(),

        # Each list entry corresponds to a guest NUMA node and the
        # set members indicate CPUs for that node
        'hw_numa_cpus': fields.ListOfSetsOfIntegersField(),

        # Each list entry corresponds to a guest NUMA node and the
        # list value indicates the memory size of that node.
        'hw_numa_mem': fields.ListOfIntegersField(),

        # Generic property to specify the pointer model type.
        'hw_pointer_model': fields.PointerModelField(),

        # boolean 'yes' or 'no' to enable QEMU guest agent
        'hw_qemu_guest_agent': fields.FlexibleBooleanField(),

        # name of the rescue bus to use with the associated rescue device.
        'hw_rescue_bus': fields.DiskBusField(),

        # name of rescue device to use.
        'hw_rescue_device': fields.BlockDeviceTypeField(),

        # name of the RNG device type eg virtio
        'hw_rng_model': fields.RNGModelField(),

        # number of serial ports to create
        'hw_serial_port_count': fields.IntegerField(),

        # name of the SCSI bus controller eg 'virtio-scsi', 'lsilogic', etc
        'hw_scsi_model': fields.SCSIModelField(),

        # name of the video adapter model to use, eg cirrus, vga, xen, qxl
        'hw_video_model': fields.VideoModelField(),

        # MB of video RAM to provide eg 64
        'hw_video_ram': fields.IntegerField(),

        # name of a NIC device model eg virtio, e1000, rtl8139
        'hw_vif_model': fields.VIFModelField(),

        # "xen" vs "hvm"
        'hw_vm_mode': fields.VMModeField(),

        # action to take when watchdog device fires eg reset, poweroff, pause,
        # none
        'hw_watchdog_action': fields.WatchdogActionField(),

        # boolean - If true, this will enable the virtio-multiqueue feature
        'hw_vif_multiqueue_enabled': fields.FlexibleBooleanField(),

        # if true download using bittorrent
        'img_bittorrent': fields.FlexibleBooleanField(),

        # Which data format the 'img_block_device_mapping' field is
        # using to represent the block device mapping
        'img_bdm_v2': fields.FlexibleBooleanField(),

        # Block device mapping - the may can be in one or two completely
        # different formats. The 'img_bdm_v2' field determines whether
        # it is in legacy format, or the new current format. Ideally
        # we would have a formal data type for this field instead of a
        # dict, but with 2 different formats to represent this is hard.
        # See nova/block_device.py from_legacy_mapping() for the complex
        # conversion code. So for now leave it as a dict and continue
        # to use existing code that is able to convert dict into the
        # desired internal BDM formats
        'img_block_device_mapping':
            fields.ListOfDictOfNullableStringsField(),

        # boolean - if True, and image cache set to "some" decides if image
        # should be cached on host when server is booted on that host
        'img_cache_in_nova': fields.FlexibleBooleanField(),

        # Compression level for images. (1-9)
        'img_compression_level': fields.IntegerField(),

        # hypervisor supported version, eg. '>=2.6'
        'img_hv_requested_version': fields.VersionPredicateField(),

        # type of the hypervisor, eg kvm, ironic, xen
        'img_hv_type': fields.HVTypeField(),

        # Whether the image needs/expected config drive
        'img_config_drive': fields.ConfigDrivePolicyField(),

        # boolean flag to set space-saving or performance behavior on the
        # Datastore
        'img_linked_clone': fields.FlexibleBooleanField(),

        # Image mappings - related to Block device mapping data - mapping
        # of virtual image names to device names. This could be represented
        # as a formal data type, but is left as dict for same reason as
        # img_block_device_mapping field. It would arguably make sense for
        # the two to be combined into a single field and data type in the
        # future.
        'img_mappings': fields.ListOfDictOfNullableStringsField(),

        # image project id (set on upload)
        'img_owner_id': fields.StringField(),

        # root device name, used in snapshotting eg /dev/<blah>
        'img_root_device_name': fields.StringField(),

        # boolean - if false don't talk to nova agent
        'img_use_agent': fields.FlexibleBooleanField(),

        # integer value 1
        'img_version': fields.IntegerField(),

        # base64 of encoding of image signature
        'img_signature': fields.StringField(),

        # string indicating hash method used to compute image signature
        'img_signature_hash_method': fields.ImageSignatureHashTypeField(),

        # string indicating Castellan uuid of certificate
        # used to compute the image's signature
        'img_signature_certificate_uuid': fields.UUIDField(),

        # string indicating type of key used to compute image signature
        'img_signature_key_type': fields.ImageSignatureKeyTypeField(),

        # boolean - hide hypervisor signature on instance
        'img_hide_hypervisor_id': fields.FlexibleBooleanField(),

        # string of username with admin privileges
        'os_admin_user': fields.StringField(),

        # string of boot time command line arguments for the guest kernel
        'os_command_line': fields.StringField(),

        # the name of the specific guest operating system distro. This
        # is not done as an Enum since the list of operating systems is
        # growing incredibly fast, and valid values can be arbitrarily
        # user defined. Nova has no real need for strict validation so
        # leave it freeform
        'os_distro': fields.StringField(),

        # boolean - if true, then guest must support disk quiesce
        # or snapshot operation will be denied
        'os_require_quiesce': fields.FlexibleBooleanField(),

        # Secure Boot feature will be enabled by setting the "os_secure_boot"
        # image property to "required". Other options can be: "disabled" or
        # "optional".
        # "os:secure_boot" flavor extra spec value overrides the image property
        # value.
        'os_secure_boot': fields.SecureBootField(),

        # boolean - if using agent don't inject files, assume someone else is
        # doing that (cloud-init)
        'os_skip_agent_inject_files_at_boot': fields.FlexibleBooleanField(),

        # boolean - if using agent don't try inject ssh key, assume someone
        # else is doing that (cloud-init)
        'os_skip_agent_inject_ssh': fields.FlexibleBooleanField(),

        # The guest operating system family such as 'linux', 'windows' - this
        # is a fairly generic type. For a detailed type consider os_distro
        # instead
        'os_type': fields.OSTypeField(),

        # The required traits associated with the image. Traits are expected to
        # be defined as starting with `trait:` like below:
        # trait:HW_CPU_X86_AVX2=required
        # for trait in image_meta.traits_required:
        # will yield trait strings such as 'HW_CPU_X86_AVX2'
        'traits_required': fields.ListOfStringsField(),
    }

    # The keys are the legacy property names and
    # the values are the current preferred names
    _legacy_property_map = {
        'architecture': 'hw_architecture',
        'owner_id': 'img_owner_id',
        'vmware_disktype': 'hw_disk_type',
        'vmware_image_version': 'img_version',
        'vmware_ostype': 'os_distro',
        'auto_disk_config': 'hw_auto_disk_config',
        'ipxe_boot': 'hw_ipxe_boot',
        'xenapi_device_id': 'hw_device_id',
        'xenapi_image_compression_level': 'img_compression_level',
        'vmware_linked_clone': 'img_linked_clone',
        'xenapi_use_agent': 'img_use_agent',
        'xenapi_skip_agent_inject_ssh': 'os_skip_agent_inject_ssh',
        'xenapi_skip_agent_inject_files_at_boot':
            'os_skip_agent_inject_files_at_boot',
        'cache_in_nova': 'img_cache_in_nova',
        'vm_mode': 'hw_vm_mode',
        'bittorrent': 'img_bittorrent',
        'mappings': 'img_mappings',
        'block_device_mapping': 'img_block_device_mapping',
        'bdm_v2': 'img_bdm_v2',
        'root_device_name': 'img_root_device_name',
        'hypervisor_version_requires': 'img_hv_requested_version',
        'hypervisor_type': 'img_hv_type',
    }

    # TODO(berrange): Need to run this from a data migration
    # at some point so we can eventually kill off the compat
    def _set_attr_from_legacy_names(self, image_props):
        for legacy_key in self._legacy_property_map:
            new_key = self._legacy_property_map[legacy_key]

            if legacy_key not in image_props:
                continue

            setattr(self, new_key, image_props[legacy_key])

        vmware_adaptertype = image_props.get("vmware_adaptertype")
        if vmware_adaptertype == "ide":
            setattr(self, "hw_disk_bus", "ide")
        elif vmware_adaptertype:
            setattr(self, "hw_disk_bus", "scsi")
            setattr(self, "hw_scsi_model", vmware_adaptertype)

    def _set_numa_mem(self, image_props):
        hw_numa_mem = []
        hw_numa_mem_set = False
        for cellid in range(ImageMetaProps.NUMA_NODES_MAX):
            memprop = "hw_numa_mem.%d" % cellid
            if memprop not in image_props:
                break
            hw_numa_mem.append(int(image_props[memprop]))
            hw_numa_mem_set = True
            del image_props[memprop]

        if hw_numa_mem_set:
            self.hw_numa_mem = hw_numa_mem

    def _set_numa_cpus(self, image_props):
        hw_numa_cpus = []
        hw_numa_cpus_set = False
        for cellid in range(ImageMetaProps.NUMA_NODES_MAX):
            cpuprop = "hw_numa_cpus.%d" % cellid
            if cpuprop not in image_props:
                break
            hw_numa_cpus.append(
                hardware.parse_cpu_spec(image_props[cpuprop]))
            hw_numa_cpus_set = True
            del image_props[cpuprop]

        if hw_numa_cpus_set:
            self.hw_numa_cpus = hw_numa_cpus

    def _set_attr_from_current_names(self, image_props):
        for key in self.fields:
            # The two NUMA fields need special handling to
            # un-stringify them correctly
            if key == "hw_numa_mem":
                self._set_numa_mem(image_props)
            elif key == "hw_numa_cpus":
                self._set_numa_cpus(image_props)
            else:
                # traits_required will be populated by
                # _set_attr_from_trait_names
                if key not in image_props or key == "traits_required":
                    continue

                setattr(self, key, image_props[key])

    def _set_attr_from_trait_names(self, image_props):
        for trait in [six.text_type(k[6:]) for k, v in image_props.items()
                      if six.text_type(k).startswith("trait:")
                      and six.text_type(v) == six.text_type('required')]:
            if 'traits_required' not in self:
                self.traits_required = []
            self.traits_required.append(trait)

    @classmethod
    def from_dict(cls, image_props):
        """Create instance from image properties dict

        :param image_props: dictionary of image metadata properties

        Creates a new object instance, initializing from a
        dictionary of image metadata properties

        :returns: an ImageMetaProps instance
        """
        obj = cls()
        # We look to see if the dict has entries for any
        # of the legacy property names first. Then we use
        # the current property names. That way if both the
        # current and legacy names are set, the value
        # associated with the current name takes priority
        obj._set_attr_from_legacy_names(image_props)
        obj._set_attr_from_current_names(image_props)
        obj._set_attr_from_trait_names(image_props)

        return obj

    def get(self, name, defvalue=None):
        """Get the value of an attribute
        :param name: the attribute to request
        :param defvalue: the default value if not set

        This returns the value of an attribute if it is currently
        set, otherwise it will return None.

        This differs from accessing props.attrname, because that
        will raise an exception if the attribute has no value set.

        So instead of

          if image_meta.properties.obj_attr_is_set("some_attr"):
             val = image_meta.properties.some_attr
          else
             val = None

        Callers can rely on unconditional access

             val = image_meta.properties.get("some_attr")

        :returns: the attribute value or None
        """

        if not self.obj_attr_is_set(name):
            return defvalue

        return getattr(self, name)
