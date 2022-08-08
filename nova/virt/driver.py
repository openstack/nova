# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
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
Driver base-classes:

    (Beginning of) the contract that compute drivers must follow, and shared
    types that support that contract
"""

import sys

import os_resource_classes as orc
import os_traits
from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova import context as nova_context
from nova.i18n import _
from nova import objects
from nova.virt import event as virtevent

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def get_block_device_info(instance, block_device_mapping):
    """Converts block device mappings for an instance to driver format.

    Virt drivers expect block device mapping to be presented in the format
    of a dict containing the following keys:

    - root_device_name: device name of the root disk
    - ephemerals: a (potentially empty) list of DriverEphemeralBlockDevice
                  instances
    - swap: An instance of DriverSwapBlockDevice or None
    - block_device_mapping: a (potentially empty) list of
                            DriverVolumeBlockDevice or any of it's more
                            specialized subclasses.
    """
    from nova.virt import block_device as virt_block_device

    block_device_info = {
        'root_device_name': instance.root_device_name,
        'ephemerals': virt_block_device.convert_ephemerals(
            block_device_mapping),
        'block_device_mapping':
            virt_block_device.convert_all_volumes(*block_device_mapping)
    }
    swap_list = virt_block_device.convert_swap(block_device_mapping)
    block_device_info['swap'] = virt_block_device.get_swap(swap_list)

    return block_device_info


def block_device_info_get_root_device(block_device_info):
    block_device_info = block_device_info or {}
    return block_device_info.get('root_device_name')


def block_device_info_get_swap(block_device_info):
    block_device_info = block_device_info or {}
    return block_device_info.get('swap') or {'device_name': None,
                                             'swap_size': 0}


def swap_is_usable(swap):
    return swap and swap['device_name'] and swap['swap_size'] > 0


def block_device_info_get_ephemerals(block_device_info):
    block_device_info = block_device_info or {}
    ephemerals = block_device_info.get('ephemerals') or []
    return ephemerals


def block_device_info_get_mapping(block_device_info):
    block_device_info = block_device_info or {}
    block_device_mapping = block_device_info.get('block_device_mapping') or []
    return block_device_mapping


# NOTE(aspiers): When adding new capabilities, ensure they are
# mirrored in ComputeDriver.capabilities, and that the corresponding
# values should always be standard traits in os_traits.  If something
# isn't a standard trait, it doesn't need to be a compute node
# capability trait; and if it needs to be a compute node capability
# trait, it needs to be (made) standard, and must be prefixed with
# "COMPUTE_".
CAPABILITY_TRAITS_MAP = {
    "supports_attach_interface": os_traits.COMPUTE_NET_ATTACH_INTERFACE,
    "supports_device_tagging": os_traits.COMPUTE_DEVICE_TAGGING,
    "supports_tagged_attach_interface":
        os_traits.COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG,
    "supports_tagged_attach_volume": os_traits.COMPUTE_VOLUME_ATTACH_WITH_TAG,
    "supports_extend_volume": os_traits.COMPUTE_VOLUME_EXTEND,
    "supports_multiattach": os_traits.COMPUTE_VOLUME_MULTI_ATTACH,
    "supports_trusted_certs": os_traits.COMPUTE_TRUSTED_CERTS,
    "supports_accelerators": os_traits.COMPUTE_ACCELERATORS,
    "supports_image_type_aki": os_traits.COMPUTE_IMAGE_TYPE_AKI,
    "supports_image_type_ami": os_traits.COMPUTE_IMAGE_TYPE_AMI,
    "supports_image_type_ari": os_traits.COMPUTE_IMAGE_TYPE_ARI,
    "supports_image_type_iso": os_traits.COMPUTE_IMAGE_TYPE_ISO,
    "supports_image_type_qcow2": os_traits.COMPUTE_IMAGE_TYPE_QCOW2,
    "supports_image_type_raw": os_traits.COMPUTE_IMAGE_TYPE_RAW,
    "supports_image_type_vdi": os_traits.COMPUTE_IMAGE_TYPE_VDI,
    "supports_image_type_vhd": os_traits.COMPUTE_IMAGE_TYPE_VHD,
    "supports_image_type_vhdx": os_traits.COMPUTE_IMAGE_TYPE_VHDX,
    "supports_image_type_vmdk": os_traits.COMPUTE_IMAGE_TYPE_VMDK,
    "supports_image_type_ploop": os_traits.COMPUTE_IMAGE_TYPE_PLOOP,
    "supports_migrate_to_same_host": os_traits.COMPUTE_SAME_HOST_COLD_MIGRATE,
    "supports_bfv_rescue": os_traits.COMPUTE_RESCUE_BFV,
    "supports_secure_boot": os_traits.COMPUTE_SECURITY_UEFI_SECURE_BOOT,
    "supports_socket_pci_numa_affinity":
        os_traits.COMPUTE_SOCKET_PCI_NUMA_AFFINITY,
}


def _check_image_type_exclude_list(capability, supported):
    """Enforce the exclusion list on image_type capabilites.

    :param capability: The supports_image_type_foo capability being checked
    :param supported: The flag indicating whether the virt driver *can*
                      support the given image type.
    :returns: True if the virt driver *can* support the image type and
              if it is not listed in the config to be excluded.
    """
    image_type = capability.replace('supports_image_type_', '')
    return (supported and
            image_type not in CONF.compute.image_type_exclude_list)


class ComputeDriver(object):
    """Base class for compute drivers.

    The interface to this class talks in terms of 'instances' (Amazon EC2 and
    internal Nova terminology), by which we mean 'running virtual machine' or
    domain (libvirt terminology).

    An instance has an ID, which is the identifier chosen by Nova to represent
    the instance further up the stack.  This is unfortunately also called a
    'name' elsewhere.  As far as this layer is concerned, 'instance ID' and
    'instance name' are synonyms.

    Note that the instance ID or name is not human-readable or
    customer-controlled -- it's an internal ID chosen by Nova.  At the
    nova.virt layer, instances do not have human-readable names at all -- such
    things are only known higher up the stack.

    Most virtualization platforms will also have their own identity schemes,
    to uniquely identify a VM or domain.  These IDs must stay internal to the
    platform-specific layer, and never escape the connection interface.  The
    platform-specific layer is responsible for keeping track of which instance
    ID maps to which platform-specific ID, and vice versa.

    Some methods here take an instance of nova.compute.service.Instance.  This
    is the data structure used by nova.compute to store details regarding an
    instance, and pass them into this layer.  This layer is responsible for
    translating that generic data structure into terms that are specific to the
    virtualization platform.

    """

    # NOTE(mriedem): When adding new capabilities, consider whether they
    # should also be added to CAPABILITY_TRAITS_MAP; if so, any new traits
    # must also be added to the os-traits library.
    capabilities = {
        "has_imagecache": False,
        "supports_evacuate": False,
        "supports_migrate_to_same_host": False,
        "resource_scheduling": False,
        "supports_attach_interface": False,
        "supports_device_tagging": False,
        "supports_tagged_attach_interface": False,
        "supports_tagged_attach_volume": False,
        "supports_extend_volume": False,
        "supports_multiattach": False,
        "supports_trusted_certs": False,
        "supports_pcpus": False,
        "supports_accelerators": False,
        "supports_bfv_rescue": False,
        "supports_vtpm": False,
        "supports_secure_boot": False,
        "supports_socket_pci_numa_affinity": False,

        # Image type support flags
        "supports_image_type_aki": False,
        "supports_image_type_ami": False,
        "supports_image_type_ari": False,
        "supports_image_type_iso": False,
        "supports_image_type_qcow2": False,
        "supports_image_type_raw": False,
        "supports_image_type_vdi": False,
        "supports_image_type_vhd": False,
        "supports_image_type_vhdx": False,
        "supports_image_type_vmdk": False,
        "supports_image_type_ploop": False,
    }

    # Indicates if this driver will rebalance nodes among compute service
    # hosts. This is really here for ironic and should not be used by any
    # other driver.
    rebalances_nodes = False

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self._compute_event_callback = None

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function,
        including catching up with currently running VM's on the given host.
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def cleanup_host(self, host):
        """Clean up anything that is necessary for the driver gracefully stop,
        including ending remote sessions. This is optional.
        """
        pass

    def get_info(self, instance, use_cache=True):
        """Get the current status of an instance.

        :param instance: nova.objects.instance.Instance object
        :param use_cache: boolean to indicate if the driver should be allowed
                          to use cached data to return instance status.
                          This only applies to drivers which cache instance
                          state information. For drivers that do not use a
                          cache, this parameter can be ignored.
        :returns: An InstanceInfo object
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def get_num_instances(self):
        """Return the total number of virtual machines.

        Return the number of virtual machines that the hypervisor knows
        about.

        .. note::

            This implementation works for all drivers, but it is
            not particularly efficient. Maintainers of the virt drivers are
            encouraged to override this method with something more
            efficient.
        """
        return len(self.list_instances())

    def instance_exists(self, instance):
        """Checks existence of an instance on the host.

        :param instance: The instance to lookup

        Returns True if an instance with the supplied ID exists on
        the host, False otherwise.

        .. note::

            This implementation works for all drivers, but it is
            not particularly efficient. Maintainers of the virt drivers are
            encouraged to override this method with something more
            efficient.
        """
        try:
            return instance.uuid in self.list_instance_uuids()
        except NotImplementedError:
            return instance.name in self.list_instances()

    def list_instances(self):
        """Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def list_instance_uuids(self):
        """Return the UUIDS of all the instances known to the virtualization
        layer, as a list.
        """
        raise NotImplementedError()

    def rebuild(self, context, instance, image_meta, injected_files,
                admin_password, allocations, bdms, detach_block_devices,
                attach_block_devices, network_info=None,
                evacuate=False, block_device_info=None,
                preserve_ephemeral=False, accel_uuids=None):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        This base class method shuts down the VM, detaches all block devices,
        then spins up the new VM afterwards. It may be overridden by
        hypervisors that need to - e.g. for optimisations, or when the 'VM'
        is actually proxied and needs to be held across the shutdown + spin
        up steps.

        :param context: security context
        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in instance.
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
        :param bdms: block-device-mappings to use for rebuild
        :param detach_block_devices: function to detach block devices. See
            nova.compute.manager.ComputeManager:_rebuild_default_impl for
            usage.
        :param attach_block_devices: function to attach block devices. See
            nova.compute.manager.ComputeManager:_rebuild_default_impl for
            usage.
        :param network_info: instance network information
        :param evacuate: True if the instance is being recreated on a new
            hypervisor - all the cleanup of old state is skipped.
        :param block_device_info: Information about block devices to be
                                  attached to the instance.
        :param preserve_ephemeral: True if the default ephemeral storage
                                   partition must be preserved on rebuild
        :param accel_uuids: Accelerator UUIDs.
        """
        raise NotImplementedError()

    def prepare_for_spawn(self, instance):
        """Prepare to spawn instance.

        Perform any pre-flight checks, tagging, etc. that the virt driver
        must perform before executing the spawn process for a new instance.

        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.
        """
        pass

    def failed_spawn_cleanup(self, instance):
        """Cleanup from the instance spawn.

        Perform any hypervisor clean-up required should the spawn operation
        fail, such as the removal of tags that were added during the
        prepare_for_spawn method.

        This method should be idempotent.

        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.

        """
        pass

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        """Create a new instance/VM/domain on the virtualization platform.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING) if ``power_on`` is True, else the
        instance should be stopped (power_state.SHUTDOWN).

        If this fails, any partial instance should be completely
        cleaned up, and the virtualization platform should be in the state
        that it was before this call began.

        :param context: security context
        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in instance.
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices to be
                                  attached to the instance.
        :param power_on: True if the instance should be powered on, False
                         otherwise
        :param arqs: List of bound accelerator requests for this instance.
            [
             {'uuid': $arq_uuid,
              'device_profile_name': $dp_name,
              'device_profile_group_id': $dp_request_group_index,
              'state': 'Bound',
              'device_rp_uuid': $resource_provider_uuid,
              'hostname': $host_nodename,
              'instance_uuid': $instance_uuid,
              'attach_handle_info': {  # PCI bdf
                'bus': '0c', 'device': '0', 'domain': '0000', 'function': '0'},
              'attach_handle_type': 'PCI'
                   # or 'TEST_PCI' for Cyborg fake driver
             }
            ]
            Also doc'd in nova/accelerator/cyborg.py::get_arqs_for_instance()
        """
        raise NotImplementedError()

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, destroy_secrets=True):
        """Destroy the specified instance from the Hypervisor.

        If the instance is not found (for example if networking failed), this
        function should still succeed.  It's probably a good idea to log a
        warning in that case.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices that should
                                  be detached from the instance.
        :param destroy_disks: Indicates if disks should be destroyed
        :param destroy_secrets: Indicates if secrets should be destroyed
        """
        raise NotImplementedError()

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True,
                destroy_secrets=True):
        """Cleanup the instance resources .

        Instance should have been destroyed from the Hypervisor before calling
        this method.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices that should
                                  be detached from the instance.
        :param destroy_disks: Indicates if disks should be destroyed
        :param migrate_data: implementation specific params
        :param destroy_vifs: Indicates if vifs should be unplugged
        :param destroy_secrets: Indicates if secrets should be destroyed
        """
        raise NotImplementedError()

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):
        """Reboot the specified instance.

        After this is called successfully, the instance's state
        goes back to power_state.RUNNING. The virtualization
        platform should ensure that the reboot action has completed
        successfully even in cases in which the underlying domain/vm
        is paused or halted/stopped.

        :param instance: nova.objects.instance.Instance
        :param network_info: instance network information
        :param reboot_type: Either a HARD or SOFT reboot
        :param block_device_info: Info pertaining to attached volumes
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered
        :param accel_info: List of accelerator request dicts. The exact
            data struct is doc'd in nova/virt/driver.py::spawn().
        """
        raise NotImplementedError()

    def get_console_output(self, context, instance):
        """Get console output for an instance

        :param context: security context
        :param instance: nova.objects.instance.Instance
        """
        raise NotImplementedError()

    def get_vnc_console(self, context, instance):
        """Get connection info for a vnc console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :returns: an instance of console.type.ConsoleVNC
        """
        raise NotImplementedError()

    def get_spice_console(self, context, instance):
        """Get connection info for a spice console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :returns: an instance of console.type.ConsoleSpice
        """
        raise NotImplementedError()

    def get_rdp_console(self, context, instance):
        """Get connection info for a rdp console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :returns: an instance of console.type.ConsoleRDP
        """
        raise NotImplementedError()

    def get_serial_console(self, context, instance):
        """Get connection info for a serial console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :returns: an instance of console.type.ConsoleSerial
        """
        raise NotImplementedError()

    def get_mks_console(self, context, instance):
        """Get connection info for a MKS console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :returns an instance of console.type.ConsoleMKS
        """
        raise NotImplementedError()

    def get_diagnostics(self, instance):
        """Return diagnostics data about the given instance.

        :param nova.objects.instance.Instance instance:
            The instance to which the diagnostic data should be returned.

        :return: Has a big overlap to the return value of the newer interface
            :func:`get_instance_diagnostics`
        :rtype: dict
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def get_instance_diagnostics(self, instance):
        """Return diagnostics data about the given instance.

        :param nova.objects.instance.Instance instance:
            The instance to which the diagnostic data should be returned.

        :return: Has a big overlap to the return value of the older interface
            :func:`get_diagnostics`
        :rtype: nova.virt.diagnostics.Diagnostics
        """
        raise NotImplementedError()

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.-
        """
        raise NotImplementedError()

    def get_host_ip_addr(self):
        """Retrieves the IP address of the host running compute service
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info.

        :raises TooManyDiskDevices: if the maxmimum allowed devices to attach
                                    to a single instance is exceeded.
        """
        raise NotImplementedError()

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
        raise NotImplementedError()

    def swap_volume(self, context, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Replace the volume attached to the given `instance`.

        :param context: The request context.
        :param dict old_connection_info:
            The volume for this connection gets detached from the given
            `instance`.
        :param dict new_connection_info:
            The volume for this connection gets attached to the given
            'instance'.
        :param nova.objects.instance.Instance instance:
            The instance whose volume gets replaced by another one.
        :param str mountpoint:
            The mountpoint in the instance where the volume for
            `old_connection_info` is attached to.
        :param int resize_to:
            If the new volume is larger than the old volume, it gets resized
            to the given size (in Gigabyte) of `resize_to`.

        :return: None
        """
        raise NotImplementedError()

    def extend_volume(self, context, connection_info, instance,
                      requested_size):
        """Extend the disk attached to the instance.

        :param context: The request context.
        :param dict connection_info:
            The connection for the extended volume.
        :param nova.objects.instance.Instance instance:
            The instance whose volume gets extended.
        :param int requested_size
            The requested new size of the volume in bytes

        :return: None
        """
        raise NotImplementedError()

    def prepare_networks_before_block_device_mapping(self, instance,
                                                     network_info):
        """Prepare networks before the block devices are mapped to instance.

        Drivers who need network information for block device preparation can
        do some network preparation necessary for block device preparation.

        :param nova.objects.instance.Instance instance:
            The instance whose networks are prepared.
        :param nova.network.model.NetworkInfoAsyncWrapper network_info:
            The network information of the given `instance`.
        """
        pass

    def clean_networks_preparation(self, instance, network_info):
        """Clean networks preparation when block device mapping is failed.

        Drivers who need network information for block device preparaion should
        clean the preparation when block device mapping is failed.

        :param nova.objects.instance.Instance instance:
            The instance whose networks are prepared.
        :param nova.network.model.NetworkInfoAsyncWrapper network_info:
            The network information of the given `instance`.
        """
        pass

    def attach_interface(self, context, instance, image_meta, vif):
        """Use hotplug to add a network interface to a running instance.

        The counter action to this is :func:`detach_interface`.

        :param context: The request context.
        :param nova.objects.instance.Instance instance:
            The instance which will get an additional network interface.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to attach.

        :raise nova.exception.NovaException: If the attach fails.

        :return: None
        """
        raise NotImplementedError()

    def detach_interface(self, context, instance, vif):
        """Use hotunplug to remove a network interface from a running instance.

        The counter action to this is :func:`attach_interface`.

        :param context: The request context.
        :param nova.objects.instance.Instance instance:
            The instance which gets a network interface removed.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to detach.

        :raise nova.exception.NovaException: If the detach fails.

        :return: None
        """
        raise NotImplementedError()

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        """Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.

        :param nova.objects.instance.Instance instance:
            The instance whose disk should be migrated.
        :param str dest:
            The IP address of the destination host.
        :param nova.objects.flavor.Flavor flavor:
            The flavor of the instance whose disk get migrated.
        :param nova.network.model.NetworkInfo network_info:
            The network information of the given `instance`.
        :param dict block_device_info:
            Information about the block devices.
        :param int timeout:
            The time in seconds to wait for the guest OS to shutdown.
        :param int retry_interval:
            How often to signal guest while waiting for it to shutdown.

        :return: A list of disk information dicts in JSON format.
        :rtype: str
        """
        raise NotImplementedError()

    def snapshot(self, context, instance, image_id, update_task_state):
        """Snapshots the specified instance.

        :param context: security context
        :param instance: nova.objects.instance.Instance
        :param image_id: Reference to a pre-created image that will
                         hold the snapshot.
        :param update_task_state: Callback function to update the task_state
            on the instance while the snapshot operation progresses. The
            function takes a task_state argument and an optional
            expected_task_state kwarg which defaults to
            nova.compute.task_states.IMAGE_SNAPSHOT. See
            nova.objects.instance.Instance.save for expected_task_state usage.
        """
        raise NotImplementedError()

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         allocations, block_device_info=None, power_on=True):
        """Completes a resize/migration.

        :param context: the context for the migration/resize
        :param migration: the migrate/resize information
        :param instance: nova.objects.instance.Instance being migrated/resized
        :param disk_info: the newly transferred disk information
        :param network_info: instance network information
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param resize_instance: True if the instance is being resized,
                                False otherwise
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocs_for_consumer.
        :param block_device_info: instance volume block device info
        :param power_on: True if the instance should be powered on, False
                         otherwise
        """
        raise NotImplementedError()

    def confirm_migration(self, context, migration, instance, network_info):
        """Confirms a resize/migration, destroying the source VM.

        :param instance: nova.objects.instance.Instance
        """
        raise NotImplementedError()

    def finish_revert_migration(self, context, instance, network_info,
                                migration, block_device_info=None,
                                power_on=True):
        """Finish reverting a resize/migration.

        :param context: the context for the finish_revert_migration
        :param instance: nova.objects.instance.Instance being migrated/resized
        :param network_info: instance network information
        :param migration: nova.objects.Migration for the migration
        :param block_device_info: instance volume block device info
        :param power_on: True if the instance should be powered on, False
                         otherwise
        """
        raise NotImplementedError()

    def pause(self, instance):
        """Pause the given instance.

        A paused instance doesn't use CPU cycles of the host anymore. The
        state of the VM could be stored in the memory or storage space of the
        host, depending on the underlying hypervisor technology.
        A "stronger" version of `pause` is :func:'suspend'.
        The counter action for `pause` is :func:`unpause`.

        :param nova.objects.instance.Instance instance:
            The instance which should be paused.

        :return: None
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def unpause(self, instance):
        """Unpause the given paused instance.

        The paused instance gets unpaused and will use CPU cycles of the
        host again. The counter action for 'unpause' is :func:`pause`.
        Depending on the underlying hypervisor technology, the guest has the
        same state as before the 'pause'.

        :param nova.objects.instance.Instance instance:
            The instance which should be unpaused.

        :return: None
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def suspend(self, context, instance):
        """Suspend the specified instance.

        A suspended instance doesn't use CPU cycles or memory of the host
        anymore. The state of the instance could be persisted on the host
        and allocate storage space this way. A "softer" way of `suspend`
        is :func:`pause`. The counter action for `suspend` is :func:`resume`.

        :param nova.context.RequestContext context:
            The context for the suspend.
        :param nova.objects.instance.Instance instance:
            The instance to suspend.

        :return: None
        """
        raise NotImplementedError()

    def resume(self, context, instance, network_info, block_device_info=None):
        """resume the specified suspended instance.

        The suspended instance gets resumed and will use CPU cycles and memory
        of the host again. The counter action for 'resume' is :func:`suspend`.
        Depending on the underlying hypervisor technology, the guest has the
        same state as before the 'suspend'.

        :param nova.context.RequestContext context:
            The context for the resume.
        :param nova.objects.instance.Instance instance:
            The suspended instance to resume.
        :param nova.network.model.NetworkInfo network_info:
            Necessary network information for the resume.
        :param dict block_device_info:
            Instance volume block device info.

        :return: None
        """
        raise NotImplementedError()

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted.

        :param instance: nova.objects.instance.Instance
        """
        raise NotImplementedError()

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password, block_device_info):
        """Rescue the specified instance.

        :param nova.context.RequestContext context:
            The context for the rescue.
        :param nova.objects.instance.Instance instance:
            The instance being rescued.
        :param nova.network.model.NetworkInfo network_info:
            Necessary network information for the resume.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param rescue_password: new root password to set for rescue.
        :param dict block_device_info:
            The block device mapping of the instance.
        """
        raise NotImplementedError()

    def unrescue(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ):
        """Unrescue the specified instance.

        :param context: security context
        :param instance: nova.objects.instance.Instance
        """
        raise NotImplementedError()

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance.

        :param instance: nova.objects.instance.Instance
        :param timeout: time to wait for GuestOS to shutdown
        :param retry_interval: How often to signal guest while
                               waiting for it to shutdown
        """
        raise NotImplementedError()

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        """Power on the specified instance.

        :param instance: nova.objects.instance.Instance
        :param network_info: instance network information
        :param block_device_info: instance volume block device info
        :param accel_info: List of accelerator request dicts. The exact
            data struct is doc'd in nova/virt/driver.py::spawn().
        """
        raise NotImplementedError()

    def power_update_event(self, instance, target_power_state):
        """Update power, vm and task states of the specified instance.

        Note that the driver is expected to set the task_state of the
        instance back to None.

        :param instance: nova.objects.instance.Instance
        :param target_power_state: The desired target power state for the
                                   instance; possible values are "POWER_ON"
                                   and "POWER_OFF".
        """
        raise NotImplementedError()

    def trigger_crash_dump(self, instance):
        """Trigger crash dump mechanism on the given instance.

        Stalling instances can be triggered to dump the crash data. How the
        guest OS reacts in details, depends on the configuration of it.

        :param nova.objects.instance.Instance instance:
            The instance where the crash dump should be triggered.

        :return: None
        """
        raise NotImplementedError()

    def soft_delete(self, instance):
        """Soft delete the specified instance.

        A soft-deleted instance doesn't allocate any resources anymore, but is
        still available as a database entry. The counter action :func:`restore`
        uses the database entry to create a new instance based on that.

        :param nova.objects.instance.Instance instance:
            The instance to soft-delete.

        :return: None
        """
        raise NotImplementedError()

    def restore(self, instance):
        """Restore the specified soft-deleted instance.

        The restored instance will be automatically booted. The counter action
        for `restore` is :func:`soft_delete`.

        :param nova.objects.instance.Instance instance:
            The soft-deleted instance which should be restored from the
            soft-deleted data.

        :return: None
        """
        raise NotImplementedError()

    @staticmethod
    def _get_reserved_host_disk_gb_from_config():
        import nova.compute.utils as compute_utils  # avoid circular import
        return compute_utils.convert_mb_to_ceil_gb(CONF.reserved_host_disk_mb)

    @staticmethod
    def _get_allocation_ratios(inventory):
        """Get the cpu/ram/disk allocation ratios for the given inventory.

        This utility method is used to get the inventory allocation ratio
        for VCPU, MEMORY_MB and DISK_GB resource classes based on the following
        precedence:

        * Use ``[DEFAULT]/*_allocation_ratio`` if set - this overrides
          everything including externally set allocation ratios on the
          inventory via the placement API
        * Use ``[DEFAULT]/initial_*_allocation_ratio`` if a value does not
          exist for a given resource class in the ``inventory`` dict
        * Use what is already in the ``inventory`` dict for the allocation
          ratio if the above conditions are false

        :param inventory: dict, keyed by resource class, of inventory
                          information.
        :returns: Return a dict, keyed by resource class, of allocation ratio
        """
        keys = {'cpu': orc.VCPU,
                'ram': orc.MEMORY_MB,
                'disk': orc.DISK_GB}
        result = {}
        for res, rc in keys.items():
            attr = '%s_allocation_ratio' % res
            conf_ratio = getattr(CONF, attr)
            if conf_ratio:
                result[rc] = conf_ratio
            elif rc not in inventory:
                result[rc] = getattr(CONF, 'initial_%s' % attr)
            else:
                result[rc] = inventory[rc]['allocation_ratio']
        return result

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update a ProviderTree object with current resource provider and
        inventory information.

        When this method returns, provider_tree should represent the correct
        hierarchy of nested resource providers associated with this compute
        node, as well as the inventory, aggregates, and traits associated with
        those resource providers.

        Implementors of this interface are expected to set ``allocation_ratio``
        and ``reserved`` values for inventory records, which may be based on
        configuration options, e.g. ``[DEFAULT]/cpu_allocation_ratio``,
        depending on the driver and resource class. If not provided, allocation
        ratio defaults to 1.0 and reserved defaults to 0 in placement.

        :note: Renaming the root provider (by deleting it from provider_tree
        and re-adding it with a different name) is not supported at this time.

        See the developer reference documentation for more details:

        https://docs.openstack.org/nova/latest/reference/update-provider-tree.html   # noqa

        :param nova.compute.provider_tree.ProviderTree provider_tree:
            A nova.compute.provider_tree.ProviderTree object representing all
            the providers in the tree associated with the compute node, and any
            sharing providers (those with the ``MISC_SHARES_VIA_AGGREGATE``
            trait) associated via aggregate with any of those providers (but
            not *their* tree- or aggregate-associated providers), as currently
            known by placement. This object is fully owned by the
            update_provider_tree method, and can therefore be modified without
            locking/concurrency considerations. In other words, the parameter
            is passed *by reference* with the expectation that the virt driver
            will modify the object. Note, however, that it may contain
            providers not directly owned/controlled by the compute host. Care
            must be taken not to remove or modify such providers inadvertently.
            In addition, providers may be associated with traits and/or
            aggregates maintained by outside agents. The
            `update_provider_tree`` method must therefore also be careful only
            to add/remove traits/aggregates it explicitly controls.
        :param nodename:
            String name of the compute node (i.e.
            ComputeNode.hypervisor_hostname) for which the caller is requesting
            updated provider information. Drivers may use this to help identify
            the compute node provider in the ProviderTree. Drivers managing
            more than one node (e.g. ironic) may also use it as a cue to
            indicate which node is being processed by the caller.
        :param allocations:
            Dict of allocation data of the form:
              { $CONSUMER_UUID: {
                    # The shape of each "allocations" dict below is identical
                    # to the return from GET /allocations/{consumer_uuid}
                    "allocations": {
                        $RP_UUID: {
                            "generation": $RP_GEN,
                            "resources": {
                                $RESOURCE_CLASS: $AMOUNT,
                                ...
                            },
                        },
                        ...
                    },
                    "project_id": $PROJ_ID,
                    "user_id": $USER_ID,
                    "consumer_generation": $CONSUMER_GEN,
                },
                ...
              }
            If None, and the method determines that any inventory needs to be
            moved (from one provider to another and/or to a different resource
            class), the ReshapeNeeded exception must be raised. Otherwise, this
            dict must be edited in place to indicate the desired final state of
            allocations. Drivers should *only* edit allocation records for
            providers whose inventories are being affected by the reshape
            operation.
        :raises ReshapeNeeded: If allocations is None and any inventory needs
            to be moved from one provider to another and/or to a different
            resource class.
        :raises: ReshapeFailed if the requested tree reshape fails for
            whatever reason.
        """
        raise NotImplementedError()

    def capabilities_as_traits(self):
        """Returns this driver's capabilities dict where the keys are traits

        Traits can only be standard compute capabilities traits from
        the os-traits library.

        :returns: dict, keyed by trait, of this driver's capabilities where the
            values are booleans indicating if the driver supports the trait

        """
        traits = {}
        for capability, supported in self.capabilities.items():
            if capability.startswith('supports_image_type_'):
                supported = _check_image_type_exclude_list(capability,
                                                           supported)

            if capability in CAPABILITY_TRAITS_MAP:
                traits[CAPABILITY_TRAITS_MAP[capability]] = supported

        return traits

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename:
            node which the caller want to get resources from
            a driver that manages only one node can safely ignore this
        :returns: Dictionary describing resources
        """
        raise NotImplementedError()

    def get_cluster_metrics(self):
        """Retrieve cluster metrics information.
        :return: Dictionary describing the cluster information.
        """
        raise NotImplementedError()

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        """Prepare an instance for live migration

        :param context: security context
        :param instance: nova.objects.instance.Instance object
        :param block_device_info: instance block device information
        :param network_info: instance network information
        :param disk_info: instance disk information
        :param migrate_data: a LiveMigrateData object
        :returns: migrate_data modified by the driver
        :raises TooManyDiskDevices: if the maxmimum allowed devices to attach
                                    to a single instance is exceeded.
        """
        raise NotImplementedError()

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Live migration of an instance to another host.

        :param context: security context
        :param instance:
            nova.db.main.models.Instance object
            instance object that is migrated.
        :param dest: destination host
        :param post_method:
            post operation method.
            expected nova.compute.manager._post_live_migration.
        :param recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager._rollback_live_migration.
        :param block_migration: if true, migrate VM disk.
        :param migrate_data: a LiveMigrateData object

        """
        raise NotImplementedError()

    def live_migration_force_complete(self, instance):
        """Force live migration to complete

        :param instance: Instance being live migrated

        """
        raise NotImplementedError()

    def live_migration_abort(self, instance):
        """Abort an in-progress live migration.

        :param instance: instance that is live migrating

        """
        raise NotImplementedError()

    def rollback_live_migration_at_source(self, context, instance,
                                          migrate_data):
        """Clean up source node after a failed live migration.

        :param context: security context
        :param instance: instance object that was being migrated
        :param migrate_data: a LiveMigrateData object
        """
        pass

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        """Clean up destination node after a failed live migration.

        :param context: security context
        :param instance: instance object that was being migrated
        :param network_info: instance network information
        :param block_device_info: instance block device information
        :param destroy_disks:
            if true, destroy disks at destination during cleanup
        :param migrate_data: a LiveMigrateData object

        """
        raise NotImplementedError()

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        """Post operation of live migration at source host.

        :param context: security context
        :instance: instance object that was migrated
        :block_device_info: instance block device information
        :param migrate_data: a LiveMigrateData object
        """
        pass

    def post_live_migration_at_source(self, context, instance, network_info):
        """Unplug VIFs from networks at source.

        :param context: security context
        :param instance: instance object reference
        :param network_info: instance network information
        """
        raise NotImplementedError(_("Hypervisor driver does not support "
                                    "post_live_migration_at_source method"))

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :param context: security context
        :param instance: instance object that is migrated
        :param network_info: instance network information
        :param block_migration: if true, post operation of block_migration.
        """
        raise NotImplementedError()

    def check_instance_shared_storage_local(self, context, instance):
        """Check if instance files located on shared storage.

        This runs check on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: nova.objects.instance.Instance object
        """
        raise NotImplementedError()

    def check_instance_shared_storage_remote(self, context, data):
        """Check if instance files located on shared storage.

        :param context: security context
        :param data: result of check_instance_shared_storage_local
        """
        raise NotImplementedError()

    def check_instance_shared_storage_cleanup(self, context, data):
        """Do cleanup on host after check_instance_shared_storage calls

        :param context: security context
        :param data: result of check_instance_shared_storage_local
        """
        pass

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: nova.db.main.models.Instance
        :param src_compute_info: Info about the sending machine
        :param dst_compute_info: Info about the receiving machine
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit
        :returns: a LiveMigrateData object (hypervisor-dependent)
        """
        raise NotImplementedError()

    def post_claim_migrate_data(self, context, instance, migrate_data, claim):
        """Returns migrate_data augmented with any information obtained from
        the claim. Intended to run on the destination of a live-migration
        operation, after resources have been claimed on it.

        :param context: The request context.
        :param instance: The instance being live-migrated.
        :param migrate_data: The existing LiveMigrateData object for this live
                             migration.
        :param claim: The MoveClaim that was made on the destination for this
                      live migration.
        :returns: A LiveMigrateData object augmented with information obtained
                  from the Claim.
        """
        return migrate_data

    def cleanup_live_migration_destination_check(self, context,
                                                 dest_check_data):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param context: security context
        :param dest_check_data: result of check_can_live_migrate_destination
        """
        raise NotImplementedError()

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance: nova.db.main.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
        :param block_device_info: result of _get_instance_block_device_info
        :returns: a LiveMigrateData object
        """
        raise NotImplementedError()

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        """Retrieve information about actual disk sizes of an instance.

        :param instance: nova.objects.Instance
        :param block_device_info:
            Optional; Can be used to filter out devices which are
            actually volumes.
        :return:
            json strings with below format::

                "[{'path':'disk',
                   'type':'raw',
                   'virt_disk_size':'10737418240',
                   'backing_file':'backing_file',
                   'disk_size':'83886080'
                   'over_committed_disk_size':'10737418240'},
                   ...]"
        """
        raise NotImplementedError()

    def set_admin_password(self, instance, new_pass):
        """Set the root password on the specified instance.

        :param instance: nova.objects.instance.Instance
        :param new_pass: the new password
        """
        raise NotImplementedError()

    def inject_network_info(self, instance, nw_info):
        """inject network info for specified instance."""
        # TODO(Vek): Need to pass context in for access to auth_token
        pass

    def poll_rebooting_instances(self, timeout, instances):
        """Perform a reboot on all given 'instances'.

        Reboots the given `instances` which are longer in the rebooting state
        than `timeout` seconds.

        :param int timeout:
            The timeout (in seconds) for considering rebooting instances
            to be stuck.
        :param list instances:
            A list of nova.objects.instance.Instance objects that have been
            in rebooting state longer than the configured timeout.

        :return: None
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def host_power_action(self, action):
        """Reboots, shuts down or powers up the host.

        :param str action:
            The action the host should perform. The valid actions are:
            ""startup", "shutdown" and "reboot".

        :return: The result of the power action
        :rtype: str
        """

        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window.

        On start, it triggers the migration of all instances to other hosts.
        Consider the combination with :func:`set_host_enabled`.

        :param str host:
            The name of the host whose maintenance mode should be changed.
        :param bool mode:
            If `True`, go into maintenance mode. If `False`, leave the
            maintenance mode.

        :return: "on_maintenance" if switched to maintenance mode or
                 "off_maintenance" if maintenance mode got left.
        :rtype: str
        """

        raise NotImplementedError()

    def set_host_enabled(self, enabled):
        """Sets the ability of this host to accept new instances.

        :param bool enabled:
            If this is `True`, the host will accept new instances. If it is
            `False`, the host won't accept new instances.

        :return: If the host can accept further instances, return "enabled",
                 if further instances shouldn't be scheduled to this host,
                 return "disabled".
        :rtype: str
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def get_host_uptime(self):
        """Returns the result of the time since start up of this hypervisor.

        :return: A text which contains the uptime of this host since the
                 last boot.
        :rtype: str
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def plug_vifs(self, instance, network_info):
        """Plug virtual interfaces (VIFs) into the given `instance` at
        instance boot time.

        The counter action is :func:`unplug_vifs`.

        :param nova.objects.instance.Instance instance:
            The instance which gets VIFs plugged.
        :param nova.network.model.NetworkInfo network_info:
            The object which contains information about the VIFs to plug.

        :return: None
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def unplug_vifs(self, instance, network_info):
        """Unplug virtual interfaces (VIFs) from networks.

        The counter action is :func:`plug_vifs`.

        :param nova.objects.instance.Instance instance:
            The instance which gets VIFs unplugged.
        :param nova.network.model.NetworkInfo network_info:
            The object which contains information about the VIFs to unplug.

        :return: None
        """
        raise NotImplementedError()

    def get_host_cpu_stats(self):
        """Get the currently known host CPU stats.

        :returns: a dict containing the CPU stat info, eg:

            | {'kernel': kern,
            |  'idle': idle,
            |  'user': user,
            |  'iowait': wait,
            |   'frequency': freq},

                  where kern and user indicate the cumulative CPU time
                  (nanoseconds) spent by kernel and user processes
                  respectively, idle indicates the cumulative idle CPU time
                  (nanoseconds), wait indicates the cumulative I/O wait CPU
                  time (nanoseconds), since the host is booting up; freq
                  indicates the current CPU frequency (MHz). All values are
                  long integers.

        """
        raise NotImplementedError()

    def block_stats(self, instance, disk_id):
        """Return performance counters associated with the given disk_id on the
        given instance.  These are returned as [rd_req, rd_bytes, wr_req,
        wr_bytes, errs], where rd indicates read, wr indicates write, req is
        the total number of I/O requests made, bytes is the total number of
        bytes transferred, and errs is the number of requests held up due to a
        full pipeline.

        All counters are long integers.

        This method is optional.  On some platforms performance statistics can
        be retrieved directly in aggregate form, without Nova having to do the
        aggregation.  On those platforms, this method is unused.

        Note that this function takes an instance ID.

        :param instance: nova.objects.Instance to get block storage statistics
        :param disk_id: mountpoint name, e.g. "vda"
        :returns: None if block statistics could not be retrieved, otherwise a
            list of the form: [rd_req, rd_bytes, wr_req, wr_bytes, errs]
        :raises: NotImplementedError if the driver does not implement this
            method
        """
        raise NotImplementedError()

    def manage_image_cache(self, context, all_instances):
        """Manage the driver's local image cache.

        Some drivers chose to cache images for instances on disk. This method
        is an opportunity to do management of that cache which isn't directly
        related to other calls into the driver. The prime example is to clean
        the cache and remove images which are no longer of interest.

        :param all_instances: nova.objects.instance.InstanceList
        """
        pass

    def cache_image(self, context, image_id):
        """Download an image into the cache.

        Used by the compute manager in response to a request to pre-cache
        an image on the compute node. If the driver implements an image cache,
        it should implement this method as well and perform the same action
        as it does during an on-demand base image fetch in response to a
        spawn.

        :returns: A boolean indicating whether or not the image was fetched.
                  True if it was fetched, or False if it already exists in
                  the cache.
        :raises: An Exception on error
        """
        raise NotImplementedError()

    def get_volume_connector(self, instance):
        """Get connector information for the instance for attaching to volumes.

        Connector information is a dictionary representing the ip of the
        machine that will be making the connection, the name of the iscsi
        initiator and the hostname of the machine as follows::

            {
                'ip': ip,
                'initiator': initiator,
                'host': hostname
            }

        """
        raise NotImplementedError()

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This method is for multi compute-nodes support. If a driver supports
        multi compute-nodes, this method returns a list of nodenames managed
        by the service. Otherwise, this method should return
        [hypervisor_hostname].
        """
        raise NotImplementedError()

    def node_is_available(self, nodename):
        """Return whether this compute service manages a particular node."""
        if nodename in self.get_available_nodes():
            return True
        # Refresh and check again.
        return nodename in self.get_available_nodes(refresh=True)

    def instance_on_disk(self, instance):
        """Checks access of instance files on the host.

        :param instance: nova.objects.instance.Instance to lookup

        Returns True if files of an instance with the supplied ID accessible on
        the host, False otherwise.

        .. note::
            Used in rebuild for HA implementation and required for validation
            of access to instance shared disk files
        """
        return False

    def register_event_listener(self, callback):
        """Register a callback to receive events.

        Register a callback to receive asynchronous event
        notifications from hypervisors. The callback will
        be invoked with a single parameter, which will be
        an instance of the nova.virt.event.Event class.
        """

        self._compute_event_callback = callback

    def emit_event(self, event):
        """Dispatches an event to the compute manager.

        Invokes the event callback registered by the
        compute manager to dispatch the event. This
        must only be invoked from a green thread.
        """

        if not self._compute_event_callback:
            LOG.debug("Discarding event %s", str(event))
            return

        if not isinstance(event, virtevent.Event):
            raise ValueError(
                _("Event must be an instance of nova.virt.event.Event"))

        try:
            LOG.debug("Emitting event %s", str(event))
            self._compute_event_callback(event)
        except Exception as ex:
            LOG.error("Exception dispatching event %(event)s: %(ex)s",
                      {'event': event, 'ex': ex})

    def delete_instance_files(self, instance):
        """Delete any lingering instance files for an instance.

        :param instance: nova.objects.instance.Instance
        :returns: True if the instance was deleted from disk, False otherwise.
        """
        return True

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        """Snapshots volumes attached to a specified instance.

        The counter action to this is :func:`volume_snapshot_delete`

        :param nova.context.RequestContext context:
            The security context.
        :param nova.objects.instance.Instance  instance:
            The instance that has the volume attached
        :param uuid volume_id:
            Volume to be snapshotted
        :param create_info: The data needed for nova to be able to attach
               to the volume.  This is the same data format returned by
               Cinder's initialize_connection() API call.  In the case of
               doing a snapshot, it is the image file Cinder expects to be
               used as the active disk after the snapshot operation has
               completed.  There may be other data included as well that is
               needed for creating the snapshot.
        """
        raise NotImplementedError()

    def volume_snapshot_delete(self, context, instance, volume_id,
                               snapshot_id, delete_info):
        """Deletes a snapshot of a volume attached to a specified instance.

        The counter action to this is :func:`volume_snapshot_create`

        :param nova.context.RequestContext context:
            The security context.
        :param nova.objects.instance.Instance instance:
            The instance that has the volume attached.
        :param uuid volume_id:
            Attached volume associated with the snapshot
        :param uuid snapshot_id:
            The snapshot to delete.
        :param dict delete_info:
            Volume backend technology specific data needed to be able to
            complete the snapshot.  For example, in the case of qcow2 backed
            snapshots, this would include the file being merged, and the file
            being merged into (if appropriate).

        :return: None
        """
        raise NotImplementedError()

    def default_root_device_name(self, instance, image_meta, root_bdm):
        """Provide a default root device name for the driver.

        :param nova.objects.instance.Instance instance:
            The instance to get the root device for.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param nova.objects.BlockDeviceMapping root_bdm:
            The description of the root device.
        :raises TooManyDiskDevices: if the maxmimum allowed devices to attach
                                    to a single instance is exceeded.
        """
        raise NotImplementedError()

    def default_device_names_for_instance(self, instance, root_device_name,
                                          *block_device_lists):
        """Default the missing device names in the block device mapping.

        :raises TooManyDiskDevices: if the maxmimum allowed devices to attach
                                    to a single instance is exceeded.
        """
        raise NotImplementedError()

    def get_device_name_for_instance(self, instance,
                                     bdms, block_device_obj):
        """Get the next device name based on the block device mapping.

        :param instance: nova.objects.instance.Instance that volume is
                         requesting a device name
        :param bdms: a nova.objects.BlockDeviceMappingList for the instance
        :param block_device_obj: A nova.objects.BlockDeviceMapping instance
                                 with all info about the requested block
                                 device. device_name does not need to be set,
                                 and should be decided by the driver
                                 implementation if not set.

        :returns: The chosen device name.
        :raises TooManyDiskDevices: if the maxmimum allowed devices to attach
                                    to a single instance is exceeded.
        """
        raise NotImplementedError()

    def is_supported_fs_format(self, fs_type):
        """Check whether the file format is supported by this driver

        :param fs_type: the file system type to be checked,
                        the validate values are defined at disk API module.
        """
        # NOTE(jichenjc): Return False here so that every hypervisor
        #                 need to define their supported file system
        #                 type and implement this function at their
        #                 virt layer.
        return False

    def quiesce(self, context, instance, image_meta):
        """Quiesce the specified instance to prepare for snapshots.

        If the specified instance doesn't support quiescing,
        InstanceQuiesceNotSupported is raised. When it fails to quiesce by
        other errors (e.g. agent timeout), NovaException is raised.

        :param context:  request context
        :param instance: nova.objects.instance.Instance to be quiesced
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        """
        raise NotImplementedError()

    def unquiesce(self, context, instance, image_meta):
        """Unquiesce the specified instance after snapshots.

        If the specified instance doesn't support quiescing,
        InstanceQuiesceNotSupported is raised. When it fails to quiesce by
        other errors (e.g. agent timeout), NovaException is raised.

        :param context:  request context
        :param instance: nova.objects.instance.Instance to be unquiesced
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        """
        raise NotImplementedError()

    def network_binding_host_id(self, context, instance):
        """Get host ID to associate with network ports.

        :param context:  request context
        :param instance: nova.objects.instance.Instance that the network
                         ports will be associated with
        :returns: a string representing the host ID
        """
        return instance.get('host')

    def manages_network_binding_host_id(self):
        """Compute driver manages port bindings.

        Used to indicate whether or not the compute driver is responsible
        for managing port binding details, such as the host_id.
        By default the ComputeManager will manage port bindings and the
        host_id associated with a binding using the network API.
        However, some backends, like Ironic, will manage the port binding
        host_id out-of-band and the compute service should not override what
        is set by the backing hypervisor.
        """
        return False

    def cleanup_lingering_instance_resources(self, instance):
        """Cleanup resources occupied by lingering instance.

        For example, cleanup other specific resources or whatever we
        add in the future.

        :param instance: nova.objects.instance.Instance
        :returns: True if the cleanup is successful, else false.
        """
        return True

    def sync_server_group(self, context, sg_uuid):
        """Sync that specific server-group into the backend

        If the driver manages multiple HVs in a cluster, this method will be
        called if a customer changed a server-group for this host via API.
        """


def load_compute_driver(virtapi, compute_driver=None):
    """Load a compute driver module.

    Load the compute driver module specified by the compute_driver
    configuration option or, if supplied, the driver name supplied as an
    argument.

    Compute drivers constructors take a VirtAPI object as their first object
    and this must be supplied.

    :param virtapi: a VirtAPI instance
    :param compute_driver: a compute driver name to override the config opt
    :returns: a ComputeDriver instance
    """
    if not compute_driver:
        compute_driver = CONF.compute_driver

    if not compute_driver:
        LOG.error("Compute driver option required, but not specified")
        sys.exit(1)

    LOG.info("Loading compute driver '%s'", compute_driver)
    try:
        driver = importutils.import_object(
            'nova.virt.%s' % compute_driver,
            virtapi)
        if isinstance(driver, ComputeDriver):
            return driver
        raise ValueError()
    except ImportError:
        LOG.exception("Unable to load the virtualization driver")
        sys.exit(1)
    except ValueError:
        LOG.exception("Compute driver '%s' from 'nova.virt' is not of type "
                      "'%s'", compute_driver, str(ComputeDriver))
        sys.exit(1)
