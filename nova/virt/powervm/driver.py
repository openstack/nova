# Copyright 2014, 2017 IBM Corp.
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

from oslo_log import log as logging
from oslo_utils import excutils
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

from nova import conf as cfg
from nova.console import type as console_type
from nova import exception as exc
from nova import image
from nova.virt import driver
from nova.virt.powervm.disk import ssp
from nova.virt.powervm import host as pvm_host
from nova.virt.powervm.tasks import base as tf_base
from nova.virt.powervm.tasks import storage as tf_stg
from nova.virt.powervm.tasks import vm as tf_vm
from nova.virt.powervm import vm

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class PowerVMDriver(driver.ComputeDriver):
    """PowerVM NovaLink Implementation of Compute Driver.

    https://wiki.openstack.org/wiki/PowerVM
    """

    def __init__(self, virtapi):
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
        # TODO(efried): Other disk adapters (localdisk), by conf selection.
        self.disk_dvr = ssp.SSPDiskAdapter(self.adapter,
                                           self.host_wrapper.uuid)
        self.image_api = image.API()

        LOG.info("The PowerVM compute driver has been initialized.")

    @staticmethod
    def _log_operation(op, instance):
        """Log entry point of driver operations."""
        LOG.info('Operation: %(op)s. Virtual machine display name: '
                 '%(display_name)s, name: %(name)s',
                 {'op': op, 'display_name': instance.display_name,
                  'name': instance.name}, instance=instance)

    def get_info(self, instance):
        """Get the current status of an instance.

        :param instance: nova.objects.instance.Instance object
        :returns: An InstanceInfo object containing:

        :state:           the running state, one of the power_state codes
        :max_mem_kb:      (int) the maximum memory in KBytes allowed
        :mem_kb:          (int) the memory in KBytes used by the domain
        :num_cpu:         (int) the number of virtual CPUs for the domain
        :cpu_time_ns:     (int) the CPU time used in nanoseconds
        :id:              a unique ID for the instance
        """
        return vm.InstanceInfo(self.adapter, instance)

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
        # TODO(efried): Switch to get_inventory, per blueprint
        #               custom-resource-classes-pike
        # Do this here so it refreshes each time this method is called.
        self.host_wrapper = pvm_ms.System.get(self.adapter)[0]
        # Get host information
        data = pvm_host.build_host_resource_from_ms(self.host_wrapper)

        # Add the disk information
        data["local_gb"] = self.disk_dvr.capacity
        data["local_gb_used"] = self.disk_dvr.capacity_used

        return data

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
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
        :param network_info: instance network information
        :param block_device_info: Information about block devices to be
                                  attached to the instance.
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

        # TODO(thorst, efried) Plug the VIFs

        # Create the boot image.
        flow_spawn.add(tf_stg.CreateDiskForImg(
            self.disk_dvr, context, instance, image_meta))
        # Connects up the disk to the LPAR
        flow_spawn.add(tf_stg.AttachDisk(
            self.disk_dvr, instance, stg_ftsk=stg_ftsk))

        # TODO(thorst, efried) Add the config drive

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
            # TODO(thorst, efried) Add unplug vifs task
            # TODO(thorst, efried) Add config drive tasks
            # TODO(thorst, efried) Add volume disconnect tasks

            # Detach the disk storage adapters
            flow.add(tf_stg.DetachDisk(self.disk_dvr, instance))

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
                 block_device_info=None):
        """Power on the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        self._log_operation('power_on', instance)
        vm.power_on(self.adapter, instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot the specified instance.

        After this is called successfully, the instance's state
        goes back to power_state.RUNNING. The virtualization
        platform should ensure that the reboot action has completed
        successfully even in cases in which the underlying domain/vm
        is paused or halted/stopped.

        :param instance: nova.objects.instance.Instance
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param reboot_type: Either a HARD or SOFT reboot
        :param block_device_info: Info pertaining to attached volumes
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered
        """
        self._log_operation(reboot_type + ' reboot', instance)
        vm.reboot(self.adapter, instance, reboot_type == 'HARD')
        # pypowervm exceptions are sufficient to indicate real failure.
        # Otherwise, pypowervm thinks the instance is up.

    def get_vnc_console(self, context, instance):
        """Get connection info for a vnc console.

        :param context: security context
        :param instance: nova.objects.instance.Instance

        :return: An instance of console.type.ConsoleVNC
        """
        self._log_operation('get_vnc_console', instance)
        lpar_uuid = vm.get_pvm_uuid(instance)

        # Build the connection to the VNC.
        host = CONF.vnc.vncserver_proxyclient_address
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
