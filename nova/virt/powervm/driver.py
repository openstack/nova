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
from pypowervm import adapter as pvm_apt
from pypowervm.helpers import log_helper as log_hlp
from pypowervm.helpers import vios_busy as vio_hlp
from pypowervm.tasks import partition as pvm_par
from pypowervm.wrappers import managed_system as pvm_ms

from nova.compute import power_state
from nova.virt import driver
from nova.virt import hardware
from nova.virt.powervm import host

LOG = logging.getLogger(__name__)


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
        # Build the adapter.  May need to attempt the connection multiple times
        # in case the PowerVM management API service is starting.
        # TODO(efried): Implement async compute service enable/disable like
        # I73a34eb6e0ca32d03e54d12a5e066b2ed4f19a61
        self.adapter = pvm_apt.Adapter(
            pvm_apt.Session(conn_tries=60),
            helpers=[log_hlp.log_helper, vio_hlp.vios_busy_retry_helper])
        # Make sure the Virtual I/O Server(s) are available.
        pvm_par.validate_vios_ready(self.adapter)
        self.host_wrapper = pvm_ms.System.get(self.adapter)[0]
        LOG.info("The PowerVM compute driver has been initialized.")

    @staticmethod
    def _log_operation(op, instance):
        """Log entry point of driver operations."""
        LOG.info('Operation: %(op)s. Virtual machine display name: '
                 '%(display_name)s, name: %(name)s',
                 {'op': op, 'display_name': instance.display_name,
                  'name': instance.name}, instance=instance)

    def get_info(self, instance):
        """Get the current status of an instance, by name (not ID!)

        :param instance: nova.objects.instance.Instance object

        Returns a InstanceInfo object containing:

        :state:           the running state, one of the power_state codes
        :max_mem_kb:      (int) the maximum memory in KBytes allowed
        :mem_kb:          (int) the memory in KBytes used by the domain
        :num_cpu:         (int) the number of virtual CPUs for the domain
        :cpu_time_ns:     (int) the CPU time used in nanoseconds
        :id:              a unique ID for the instance
        """
        # TODO(efried): Implement
        return hardware.InstanceInfo(state=power_state.NOSTATE)

    def list_instances(self):
        """Return the names of all the instances known to the virt host.

        :return: VM Names as a list.
        """
        # TODO(efried): Get the LPAR names
        return []

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This method is for multi compute-nodes support. If a driver supports
        multi compute-nodes, this method returns a list of nodenames managed
        by the service. Otherwise, this method should return
        [hypervisor_hostname].
        """

        return [self.host_wrapper.mtms.mtms_str]

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
        data = host.build_host_resource_from_ms(self.host_wrapper)
        # Add the disk information
        # TODO(efried): Get real stats when disk support is added.
        data["local_gb"] = 100000
        data["local_gb_used"] = 10
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
        # TODO(efried): Take flavor extra specs into account
        # TODO(efried): Use TaskFlow
        # TODO(efried): Create the LPAR
        # TODO(thorst, efried) Plug the VIFs
        # TODO(thorst, efried) Create/Connect the disk
        # TODO(thorst, efried) Add the config drive
        # Last step is to power on the system.
        # TODO(efried): Power on the LPAR

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
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
        :param migrate_data: implementation specific params
        """
        # TODO(thorst, efried) Add resize checks for destroy
        self._log_operation('destroy', instance)
        # TODO(efried): Use TaskFlow
        # TODO(efried): Power off the LPAR
        # TODO(thorst, efried) Add unplug vifs task
        # TODO(thorst, efried) Add config drive tasks
        # TODO(thorst, efried) Add volume disconnect tasks
        # TODO(thorst, efried) Add disk disconnect/destroy tasks
        # TODO(thorst, efried) Add LPAR id based scsi map clean up task
        # TODO(efried): Delete the LPAR
