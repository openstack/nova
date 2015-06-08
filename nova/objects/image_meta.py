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

from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import utils
from nova.virt import hardware


@base.NovaObjectRegistry.register
class ImageMeta(base.NovaObject):
    VERSION = '1.0'

    # These are driven by what the image client API returns
    # to Nova from Glance. This is defined in the glance
    # code glance/api/v2/images.py get_base_properties()
    # method. A few things are currently left out:
    # self, file, schema - Nova does not appear to ever use
    # these field; locations - modelling the arbitrary
    # data in the 'metadata' subfield is non-trivial as
    # there's no clear spec
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

    obj_relationships = {
        'properties': [('1.0', '1.0')],
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

        return cls(**image_meta)

    @classmethod
    def from_instance(cls, instance):
        """Create instance from instance system metadata

        :param instance: Instance object

        Creates a new object instance, initializing from the
        system metadata "image_" properties associated with
        instance

        :returns: an ImageMeta instance
        """
        sysmeta = utils.instance_sys_meta(instance)
        image_meta = utils.get_image_from_system_metadata(sysmeta)
        return cls.from_dict(image_meta)


@base.NovaObjectRegistry.register
class ImageMetaProps(base.NovaObject):
    VERSION = ImageMeta.VERSION

    # 'hw_' - settings affecting the guest virtual machine hardware
    # 'img_' - settings affecting the use of images by the compute node
    # 'os_' - settings affecting the guest operating system setup

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

        # CPU thread allocation policy
        'hw_cpu_policy': fields.CPUAllocationPolicyField(),

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

        # boolean 'yes' or 'no' to enable QEMU guest agent
        'hw_qemu_guest_agent': fields.FlexibleBooleanField(),

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

        # boolean flag to set space-saving or performance behavior on the
        # Datastore
        'img_linked_clone': fields.FlexibleBooleanField(),

        # Image mappings - related to Block device mapping data - mapping
        # of virtual image names to device names. This could be represented
        # as a formatl data type, but is left as dict for same reason as
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

        # string of boot time command line arguments for the guest kernel
        'os_command_line': fields.StringField(),

        # the name of the specific guest operating system distro. This
        # is not done as an Enum since the list of operating systems is
        # growing incredibly fast, and valid values can be arbitrarily
        # user defined. Nova has no real need for strict validation so
        # leave it freeform
        'os_distro': fields.StringField(),

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
    }

    # The keys are the legacy property names and
    # the values are the current preferred names
    _legacy_property_map = {
        'architecture': 'hw_architecture',
        'owner_id': 'img_owner_id',
        'vmware_adaptertype': 'hw_scsi_model',
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
    }

    # TODO(berrange): Need to run this from a data migration
    # at some point so we can eventually kill off the compat
    def _set_attr_from_legacy_names(self, image_props):
        for legacy_key in self._legacy_property_map:
            new_key = self._legacy_property_map[legacy_key]

            if legacy_key not in image_props:
                continue

            setattr(self, new_key, image_props[legacy_key])

    def _set_numa_mem(self, image_props):
        nodes = int(image_props.get("hw_numa_nodes", "1"))
        hw_numa_mem = [None for i in range(nodes)]
        hw_numa_mem_set = False
        for cellid in range(nodes):
            memprop = "hw_numa_mem.%d" % cellid
            if memprop in image_props:
                hw_numa_mem[cellid] = int(image_props[memprop])
                hw_numa_mem_set = True
                del image_props[memprop]

        if hw_numa_mem_set:
            self.hw_numa_mem = hw_numa_mem

    def _set_numa_cpus(self, image_props):
        nodes = int(image_props.get("hw_numa_nodes", "1"))
        hw_numa_cpus = [None for i in range(nodes)]
        hw_numa_cpus_set = False
        for cellid in range(nodes):
            cpuprop = "hw_numa_cpus.%d" % cellid
            if cpuprop in image_props:
                hw_numa_cpus[cellid] = \
                    hardware.parse_cpu_spec(image_props[cpuprop])
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
                if key not in image_props:
                    continue

                setattr(self, key, image_props[key])

    @classmethod
    def from_dict(cls, image_props):
        """Create instance from image properties dict

        :param image_props: dictionary of image metdata properties

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
