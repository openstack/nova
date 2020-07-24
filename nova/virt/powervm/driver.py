# Copyright 2014, 2018 IBM Corp.
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
"""Connection to PowerVM hypervisor through NovaLink."""

import os_resource_classes as orc
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from pypowervm import adapter as pvm_apt
from pypowervm import const as pvm_const
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as log_hlp
from pypowervm.helpers import vios_busy as vio_hlp
from pypowervm.tasks import partition as pvm_par
from pypowervm.tasks import storage as pvm_stor
from pypowervm.tasks import vterm as pvm_vterm
from pypowervm.wrappers import managed_system as pvm_ms
import six
from taskflow.patterns import linear_flow as tf_lf

from nova.compute import task_states
from nova import conf as cfg
from nova.console import type as console_type
from nova import exception as exc
from nova.i18n import _
from nova.image import glance
from nova.virt import configdrive
from nova.virt import driver
from nova.virt.powervm import host as pvm_host
from nova.virt.powervm.tasks import base as tf_base
from nova.virt.powervm.tasks import image as tf_img
from nova.virt.powervm.tasks import network as tf_net
from nova.virt.powervm.tasks import storage as tf_stg
from nova.virt.powervm.tasks import vm as tf_vm
from nova.virt.powervm import vm
from nova.virt.powervm import volume
from nova.virt.powervm.volume import fcvscsi

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

DISK_ADPT_NS = 'nova.virt.powervm.disk'
DISK_ADPT_MAPPINGS = {
    'localdisk': 'localdisk.LocalStorage',
    'ssp': 'ssp.SSPDiskAdapter'
}


class PowerVMDriver(driver.ComputeDriver):
    """PowerVM NovaLink Implementation of Compute Driver.

    https://wiki.openstack.org/wiki/PowerVM
    """

    def __init__(self, virtapi):
        # NOTE(edmondsw) some of these will be dynamic in future, so putting
        # capabilities on the instance rather than on the class.
        self.capabilities = {
            'has_imagecache': False,
            'supports_bfv_rescue': False,
            'supports_evacuate': False,
            'supports_migrate_to_same_host': False,
            'supports_attach_interface': True,
            'supports_device_tagging': False,
            'supports_tagged_attach_interface': False,
            'supports_tagged_attach_volume': False,
            'supports_extend_volume': True,
            'supports_multiattach': False,
            'supports_trusted_certs': False,
            'supports_pcpus': False,
            'supports_accelerators': False,
            'supports_vtpm': False,

            # Supported image types
            "supports_image_type_aki": False,
            "supports_image_type_ami": False,
            "supports_image_type_ari": False,
            "supports_image_type_iso": False,
            "supports_image_type_qcow2": False,
            "supports_image_type_raw": True,
            "supports_image_type_vdi": False,
            "supports_image_type_vhd": False,
            "supports_image_type_vhdx": False,
            "supports_image_type_vmdk": False,
            "supports_image_type_ploop": False,
        }
        super(PowerVMDriver, self).__init__(virtapi)

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function.

        Includes catching up with currently running VMs on the given host.
        """
        # Build the adapter. May need to attempt the connection multiple times
        # in case the PowerVM management API service is starting.
        # TODO(efried): Implement async compute service enable/disable like
        # I73a34eb6e0ca32d03e54d12a5e066b2ed4f19a61
        self.adapter = pvm_apt.Adapter(
            pvm_apt.Session(conn_tries=60),
            helpers=[log_hlp.log_helper, vio_hlp.vios_busy_retry_helper])
        # Make sure the Virtual I/O Server(s) are available.
        pvm_par.validate_vios_ready(self.adapter)
        self.host_wrapper = pvm_ms.System.get(self.adapter)[0]

        # Do a scrub of the I/O plane to make sure the system is in good shape
        LOG.info("Clearing stale I/O connections on driver init.")
        pvm_stor.ComprehensiveScrub(self.adapter).execute()

        # Initialize the disk adapter
        self.disk_dvr = importutils.import_object_ns(
            DISK_ADPT_NS, DISK_ADPT_MAPPINGS[CONF.powervm.disk_driver.lower()],
            self.adapter, self.host_wrapper.uuid)
        self.image_api = glance.API()

        LOG.info("The PowerVM compute driver has been initialized.")

    @staticmethod
    def _log_operation(op, instance):
        """Log entry point of driver operations."""
        LOG.info('Operation: %(op)s. Virtual machine display name: '
                 '%(display_name)s, name: %(name)s',
                 {'op': op, 'display_name': instance.display_name,
                  'name': instance.name}, instance=instance)

    def get_info(self, instance, use_cache=True):
        """Get the current status of an instance.

        :param instance: nova.objects.instance.Instance object
        :param use_cache: unused in this driver
        :returns: An InstanceInfo object.
        """
        return vm.get_vm_info(self.adapter, instance)

    def list_instances(self):
        """Return the names of all the instances known to the virt host.

        :return: VM Names as a list.
        """
        return vm.get_lpar_names(self.adapter)

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This method is for multi compute-nodes support. If a driver supports
        multi compute-nodes, this method returns a list of nodenames managed
        by the service. Otherwise, this method should return
        [hypervisor_hostname].
        """

        return [CONF.host]

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and as part of a
        periodic task.

        :param nodename: Node from which the caller wants to get resources.
                         A driver that manages only one node can safely ignore
                         this.
        :return: Dictionary describing resources.
        """
        # Do this here so it refreshes each time this method is called.
        self.host_wrapper = pvm_ms.System.get(self.adapter)[0]
        return self._get_available_resource()

    def _get_available_resource(self):
        # Get host information
        data = pvm_host.build_host_resource_from_ms(self.host_wrapper)

        # Add the disk information
        data["local_gb"] = self.disk_dvr.capacity
        data["local_gb_used"] = self.disk_dvr.capacity_used

        return data

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update a ProviderTree with current provider and inventory data.

        :param nova.compute.provider_tree.ProviderTree provider_tree:
            A nova.compute.provider_tree.ProviderTree object representing all
            the providers in the tree associated with the compute node, and any
            sharing providers (those with the ``MISC_SHARES_VIA_AGGREGATE``
            trait) associated via aggregate with any of those providers (but
            not *their* tree- or aggregate-associated providers), as currently
            known by placement.
        :param nodename:
            String name of the compute node (i.e.
            ComputeNode.hypervisor_hostname) for which the caller is requesting
            updated provider information.
        :param allocations: Currently ignored by this driver.
        """
        # Get (legacy) resource information. Same as get_available_resource,
        # but we don't need to refresh self.host_wrapper as it was *just*
        # refreshed by get_available_resource in the resource tracker's
        # update_available_resource flow.
        data = self._get_available_resource()

        # NOTE(yikun): If the inv record does not exists, the allocation_ratio
        # will use the CONF.xxx_allocation_ratio value if xxx_allocation_ratio
        # is set, and fallback to use the initial_xxx_allocation_ratio
        # otherwise.
        inv = provider_tree.data(nodename).inventory
        ratios = self._get_allocation_ratios(inv)
        # TODO(efried): Fix these to reflect something like reality
        cpu_reserved = CONF.reserved_host_cpus
        mem_reserved = CONF.reserved_host_memory_mb
        disk_reserved = self._get_reserved_host_disk_gb_from_config()

        inventory = {
            orc.VCPU: {
                'total': data['vcpus'],
                'max_unit': data['vcpus'],
                'allocation_ratio': ratios[orc.VCPU],
                'reserved': cpu_reserved,
            },
            orc.MEMORY_MB: {
                'total': data['memory_mb'],
                'max_unit': data['memory_mb'],
                'allocation_ratio': ratios[orc.MEMORY_MB],
                'reserved': mem_reserved,
            },
            orc.DISK_GB: {
                # TODO(efried): Proper DISK_GB sharing when SSP driver in play
                'total': int(data['local_gb']),
                'max_unit': int(data['local_gb']),
                'allocation_ratio': ratios[orc.DISK_GB],
                'reserved': disk_reserved,
            },
        }
        provider_tree.update_inventory(nodename, inventory)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        """Create a new instance/VM/domain on the virtualization platform.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING).

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
        """
        self._log_operation('spawn', instance)
        # Define the flow
        flow_spawn = tf_lf.Flow("spawn")

        # This FeedTask accumulates VIOS storage connection operations to be
        # run in parallel. Include both SCSI and fibre channel mappings for
        # the scrubber.
        stg_ftsk = pvm_par.build_active_vio_feed_task(
            self.adapter, xag={pvm_const.XAG.VIO_SMAP, pvm_const.XAG.VIO_FMAP})

        flow_spawn.add(tf_vm.Create(
            self.adapter, self.host_wrapper, instance, stg_ftsk))

        # Create a flow for the IO
        flow_spawn.add(tf_net.PlugVifs(
            self.virtapi, self.adapter, instance, network_info))
        flow_spawn.add(tf_net.PlugMgmtVif(
            self.adapter, instance))

        # Create the boot image.
        flow_spawn.add(tf_stg.CreateDiskForImg(
            self.disk_dvr, context, instance, image_meta))
        # Connects up the disk to the LPAR
        flow_spawn.add(tf_stg.AttachDisk(
            self.disk_dvr, instance, stg_ftsk=stg_ftsk))

        # Extract the block devices.
        bdms = driver.block_device_info_get_mapping(block_device_info)

        # Determine if there are volumes to connect.  If so, add a connection
        # for each type.
        for bdm, vol_drv in self._vol_drv_iter(context, instance, bdms,
                                               stg_ftsk=stg_ftsk):
            # Connect the volume.  This will update the connection_info.
            flow_spawn.add(tf_stg.AttachVolume(vol_drv))

        # If the config drive is needed, add those steps.  Should be done
        # after all the other I/O.
        if configdrive.required_by(instance):
            flow_spawn.add(tf_stg.CreateAndConnectCfgDrive(
                self.adapter, instance, injected_files, network_info,
                stg_ftsk, admin_pass=admin_password))

        # Add the transaction manager flow at the end of the 'I/O
        # connection' tasks. This will run all the connections in parallel.
        flow_spawn.add(stg_ftsk)

        # Last step is to power on the system.
        flow_spawn.add(tf_vm.PowerOn(self.adapter, instance))

        # Run the flow.
        tf_base.run(flow_spawn, instance=instance)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy the specified instance from the Hypervisor.

        If the instance is not found (for example if networking failed), this
        function should still succeed. It's probably a good idea to log a
        warning in that case.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices that should
                                  be detached from the instance.
        :param destroy_disks: Indicates if disks should be destroyed
        """
        # TODO(thorst, efried) Add resize checks for destroy

        self._log_operation('destroy', instance)

        def _setup_flow_and_run():
            # Define the flow
            flow = tf_lf.Flow("destroy")

            # Power Off the LPAR. If its disks are about to be deleted, issue a
            # hard shutdown.
            flow.add(tf_vm.PowerOff(self.adapter, instance,
                                    force_immediate=destroy_disks))

            # The FeedTask accumulates storage disconnection tasks to be run in
            # parallel.
            stg_ftsk = pvm_par.build_active_vio_feed_task(
                self.adapter, xag=[pvm_const.XAG.VIO_SMAP])

            # Call the unplug VIFs task.  While CNAs get removed from the LPAR
            # directly on the destroy, this clears up the I/O Host side.
            flow.add(tf_net.UnplugVifs(self.adapter, instance, network_info))

            # Add the disconnect/deletion of the vOpt to the transaction
            # manager.
            if configdrive.required_by(instance):
                flow.add(tf_stg.DeleteVOpt(
                    self.adapter, instance, stg_ftsk=stg_ftsk))

            # Extract the block devices.
            bdms = driver.block_device_info_get_mapping(block_device_info)

            # Determine if there are volumes to detach.  If so, remove each
            # volume (within the transaction manager)
            for bdm, vol_drv in self._vol_drv_iter(
                     context, instance, bdms, stg_ftsk=stg_ftsk):
                flow.add(tf_stg.DetachVolume(vol_drv))

            # Detach the disk storage adapters
            flow.add(tf_stg.DetachDisk(self.disk_dvr, instance))

            # Accumulated storage disconnection tasks next
            flow.add(stg_ftsk)

            # Delete the storage disks
            if destroy_disks:
                flow.add(tf_stg.DeleteDisk(self.disk_dvr))

            # TODO(thorst, efried) Add LPAR id based scsi map clean up task
            flow.add(tf_vm.Delete(self.adapter, instance))

            # Build the engine & run!
            tf_base.run(flow, instance=instance)

        try:
            _setup_flow_and_run()
        except exc.InstanceNotFound:
            LOG.debug('VM was not found during destroy operation.',
                      instance=instance)
            return
        except pvm_exc.Error as e:
            LOG.exception("PowerVM error during destroy.", instance=instance)
            # Convert to a Nova exception
            raise exc.InstanceTerminationFailure(reason=six.text_type(e))

    def snapshot(self, context, instance, image_id, update_task_state):
        """Snapshots the specified instance.

        :param context: security context
        :param instance: nova.objects.instance.Instance
        :param image_id: Reference to a pre-created image that will hold the
                         snapshot.
        :param update_task_state: Callback function to update the task_state
            on the instance while the snapshot operation progresses. The
            function takes a task_state argument and an optional
            expected_task_state kwarg which defaults to
            nova.compute.task_states.IMAGE_SNAPSHOT. See
            nova.objects.instance.Instance.save for expected_task_state usage.
        """

        if not self.disk_dvr.capabilities.get('snapshot'):
            raise exc.NotSupportedWithOption(
                message=_("The snapshot operation is not supported in "
                          "conjunction with a [powervm]/disk_driver setting "
                          "of %s.") % CONF.powervm.disk_driver)

        self._log_operation('snapshot', instance)

        # Define the flow.
        flow = tf_lf.Flow("snapshot")

        # Notify that we're starting the process.
        flow.add(tf_img.UpdateTaskState(update_task_state,
                                        task_states.IMAGE_PENDING_UPLOAD))

        # Connect the instance's boot disk to the management partition, and
        # scan the scsi bus and bring the device into the management partition.
        flow.add(tf_stg.InstanceDiskToMgmt(self.disk_dvr, instance))

        # Notify that the upload is in progress.
        flow.add(tf_img.UpdateTaskState(
            update_task_state, task_states.IMAGE_UPLOADING,
            expected_state=task_states.IMAGE_PENDING_UPLOAD))

        # Stream the disk to glance.
        flow.add(tf_img.StreamToGlance(context, self.image_api, image_id,
                                       instance))

        # Disconnect the boot disk from the management partition and delete the
        # device.
        flow.add(tf_stg.RemoveInstanceDiskFromMgmt(self.disk_dvr, instance))

        # Run the flow.
        tf_base.run(flow, instance=instance)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance.

        :param instance: nova.objects.instance.Instance
        :param timeout: time to wait for GuestOS to shutdown
        :param retry_interval: How often to signal guest while
                               waiting for it to shutdown
        """
        self._log_operation('power_off', instance)
        force_immediate = (timeout == 0)
        timeout = timeout or None
        vm.power_off(self.adapter, instance, force_immediate=force_immediate,
                     timeout=timeout)

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        """Power on the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        self._log_operation('power_on', instance)
        vm.power_on(self.adapter, instance)

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
        :param network_info: `nova.network.models.NetworkInfo` object
            describing the network metadata.
        :param reboot_type: Either a HARD or SOFT reboot
        :param block_device_info: Info pertaining to attached volumes
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered
        :param accel_info: List of accelerator request dicts. The exact
            data struct is doc'd in nova/virt/driver.py::spawn().
        """
        self._log_operation(reboot_type + ' reboot', instance)
        vm.reboot(self.adapter, instance, reboot_type == 'HARD')
        # pypowervm exceptions are sufficient to indicate real failure.
        # Otherwise, pypowervm thinks the instance is up.

    def attach_interface(self, context, instance, image_meta, vif):
        """Attach an interface to the instance."""
        self.plug_vifs(instance, [vif])

    def detach_interface(self, context, instance, vif):
        """Detach an interface from the instance."""
        self.unplug_vifs(instance, [vif])

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        self._log_operation('plug_vifs', instance)

        # Define the flow
        flow = tf_lf.Flow("plug_vifs")

        # Get the LPAR Wrapper
        flow.add(tf_vm.Get(self.adapter, instance))

        # Run the attach
        flow.add(tf_net.PlugVifs(self.virtapi, self.adapter, instance,
                                 network_info))

        # Run the flow
        try:
            tf_base.run(flow, instance=instance)
        except exc.InstanceNotFound:
            raise exc.VirtualInterfacePlugException(
                _("Plug vif failed because instance %s was not found.")
                % instance.name)
        except Exception:
            LOG.exception("PowerVM error plugging vifs.", instance=instance)
            raise exc.VirtualInterfacePlugException(
                _("Plug vif failed because of an unexpected error."))

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        self._log_operation('unplug_vifs', instance)

        # Define the flow
        flow = tf_lf.Flow("unplug_vifs")

        # Run the detach
        flow.add(tf_net.UnplugVifs(self.adapter, instance, network_info))

        # Run the flow
        try:
            tf_base.run(flow, instance=instance)
        except exc.InstanceNotFound:
            LOG.warning('VM was not found during unplug operation as it is '
                        'already possibly deleted.', instance=instance)
        except Exception:
            LOG.exception("PowerVM error trying to unplug vifs.",
                          instance=instance)
            raise exc.InterfaceDetachFailed(instance_uuid=instance.uuid)

    def get_vnc_console(self, context, instance):
        """Get connection info for a vnc console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :return: An instance of console.type.ConsoleVNC
        """
        self._log_operation('get_vnc_console', instance)
        lpar_uuid = vm.get_pvm_uuid(instance)

        # Build the connection to the VNC.
        host = CONF.vnc.server_proxyclient_address
        # TODO(thorst, efried) Add the x509 certificate support when it lands

        try:
            # Open up a remote vterm
            port = pvm_vterm.open_remotable_vnc_vterm(
                self.adapter, lpar_uuid, host, vnc_path=lpar_uuid)
            # Note that the VNC viewer will wrap the internal_access_path with
            # the HTTP content.
            return console_type.ConsoleVNC(host=host, port=port,
                                           internal_access_path=lpar_uuid)
        except pvm_exc.HttpError as e:
            with excutils.save_and_reraise_exception(logger=LOG) as sare:
                # If the LPAR was not found, raise a more descriptive error
                if e.response.status == 404:
                    sare.reraise = False
                    raise exc.InstanceNotFound(instance_id=instance.uuid)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the volume to the instance using the connection_info.

        :param context: security context
        :param connection_info: Volume connection information from the block
                                device mapping
        :param instance: nova.objects.instance.Instance
        :param mountpoint: Unused
        :param disk_bus: Unused
        :param device_type: Unused
        :param encryption: Unused
        """
        self._log_operation('attach_volume', instance)

        # Define the flow
        flow = tf_lf.Flow("attach_volume")

        # Build the driver
        vol_drv = volume.build_volume_driver(self.adapter, instance,
                                             connection_info)

        # Add the volume attach to the flow.
        flow.add(tf_stg.AttachVolume(vol_drv))

        # Run the flow
        tf_base.run(flow, instance=instance)

        # The volume connector may have updated the system metadata.  Save
        # the instance to persist the data.  Spawn/destroy auto saves instance,
        # but the attach does not.  Detach does not need this save - as the
        # detach flows do not (currently) modify system metadata.  May need
        # to revise in the future as volume connectors evolve.
        instance.save()

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the volume attached to the instance.

        :param context: security context
        :param connection_info: Volume connection information from the block
                                device mapping
        :param instance: nova.objects.instance.Instance
        :param mountpoint: Unused
        :param encryption: Unused
        """
        self._log_operation('detach_volume', instance)

        # Define the flow
        flow = tf_lf.Flow("detach_volume")

        # Get a volume adapter for this volume
        vol_drv = volume.build_volume_driver(self.adapter, instance,
                                             connection_info)

        # Add a task to detach the volume
        flow.add(tf_stg.DetachVolume(vol_drv))

        # Run the flow
        tf_base.run(flow, instance=instance)

    def extend_volume(self, context, connection_info, instance,
                      requested_size):
        """Extend the disk attached to the instance.

        :param context: security context
        :param dict connection_info: The connection for the extended volume.
        :param nova.objects.instance.Instance instance:
            The instance whose volume gets extended.
        :param int requested_size: The requested new volume size in bytes.
        :return: None
        """

        vol_drv = volume.build_volume_driver(
            self.adapter, instance, connection_info)
        vol_drv.extend_volume()

    def _vol_drv_iter(self, context, instance, bdms, stg_ftsk=None):
        """Yields a bdm and volume driver.

        :param context: security context
        :param instance: nova.objects.instance.Instance
        :param bdms: block device mappings
        :param stg_ftsk: storage FeedTask
        """
        # Get a volume driver for each volume
        for bdm in bdms or []:
            conn_info = bdm.get('connection_info')
            vol_drv = volume.build_volume_driver(self.adapter, instance,
                                                 conn_info, stg_ftsk=stg_ftsk)
            yield bdm, vol_drv

    def get_volume_connector(self, instance):
        """Get connector information for the instance for attaching to volumes.

        Connector information is a dictionary representing information about
        the system that will be making the connection.

        :param instance: nova.objects.instance.Instance
        """
        # Put the values in the connector
        connector = {}
        wwpn_list = fcvscsi.wwpns(self.adapter)

        if wwpn_list is not None:
            connector["wwpns"] = wwpn_list
        connector["multipath"] = False
        connector['host'] = CONF.host
        connector['initiator'] = None

        return connector
