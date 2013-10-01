# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
A connection to the VMware ESX/vCenter platform.
"""

import re
import time

from eventlet import event
from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.virt import driver
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import host
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import volumeops


LOG = logging.getLogger(__name__)

vmwareapi_opts = [
    cfg.StrOpt('host_ip',
               deprecated_name='vmwareapi_host_ip',
               deprecated_group='DEFAULT',
               help='URL for connection to VMware ESX/VC host. Required if '
                    'compute_driver is vmwareapi.VMwareESXDriver or '
                    'vmwareapi.VMwareVCDriver.'),
    cfg.StrOpt('host_username',
               deprecated_name='vmwareapi_host_username',
               deprecated_group='DEFAULT',
               help='Username for connection to VMware ESX/VC host. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.'),
    cfg.StrOpt('host_password',
               deprecated_name='vmwareapi_host_password',
               deprecated_group='DEFAULT',
               help='Password for connection to VMware ESX/VC host. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.',
               secret=True),
    cfg.MultiStrOpt('cluster_name',
               deprecated_name='vmwareapi_cluster_name',
               deprecated_group='DEFAULT',
               help='Name of a VMware Cluster ComputeResource. Used only if '
                    'compute_driver is vmwareapi.VMwareVCDriver.'),
    cfg.StrOpt('datastore_regex',
               help='Regex to match the name of a datastore. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareVCDriver.'),
    cfg.FloatOpt('task_poll_interval',
                 default=5.0,
                 deprecated_name='vmwareapi_task_poll_interval',
                 deprecated_group='DEFAULT',
                 help='The interval used for polling of remote tasks. '
                       'Used only if compute_driver is '
                       'vmwareapi.VMwareESXDriver or '
                       'vmwareapi.VMwareVCDriver.'),
    cfg.IntOpt('api_retry_count',
               default=10,
               deprecated_name='vmwareapi_api_retry_count',
               deprecated_group='DEFAULT',
               help='The number of times we retry on failures, e.g., '
                    'socket error, etc. '
                    'Used only if compute_driver is '
                    'vmwareapi.VMwareESXDriver or vmwareapi.VMwareVCDriver.'),
    cfg.IntOpt('vnc_port',
               default=5900,
               deprecated_name='vnc_port',
               deprecated_group='DEFAULT',
               help='VNC starting port'),
    cfg.IntOpt('vnc_port_total',
               default=10000,
               deprecated_name='vnc_port_total',
               deprecated_group='DEFAULT',
               help='Total number of VNC ports'),
    # Deprecated, remove in Icehouse
    cfg.StrOpt('vnc_password',
               deprecated_name='vnc_password',
               deprecated_group='DEFAULT',
               help='DEPRECATED. VNC password. The password-based access to '
                    'VNC consoles will be removed in the next release. The '
                    'default value will disable password protection on the '
                    'VNC console.',
               secret=True),
    cfg.BoolOpt('use_linked_clone',
                default=True,
                deprecated_name='use_linked_clone',
                deprecated_group='DEFAULT',
                help='Whether to use linked clone'),
    ]

CONF = cfg.CONF
CONF.register_opts(vmwareapi_opts, 'vmware')

TIME_BETWEEN_API_CALL_RETRIES = 2.0


class Failure(Exception):
    """Base Exception class for handling task failures."""

    def __init__(self, details):
        self.details = details

    def __str__(self):
        return str(self.details)


class VMwareESXDriver(driver.ComputeDriver):
    """The ESX host connection object."""

    # VMwareAPI has both ESXi and vCenter API sets.
    # The ESXi API are a proper sub-set of the vCenter API.
    # That is to say, nearly all valid ESXi calls are
    # valid vCenter calls. There are some small edge-case
    # exceptions regarding VNC, CIM, User management & SSO.

    def __init__(self, virtapi, read_only=False, scheme="https"):
        super(VMwareESXDriver, self).__init__(virtapi)

        self._host_ip = CONF.vmware.host_ip
        if not (self._host_ip or CONF.vmware.host_username is None or
                        CONF.vmware.host_password is None):
            raise Exception(_("Must specify host_ip, "
                              "host_username "
                              "and host_password to use "
                              "compute_driver=vmwareapi.VMwareESXDriver or "
                              "vmwareapi.VMwareVCDriver"))

        self._session = VMwareAPISession(scheme=scheme)
        self._volumeops = volumeops.VMwareVolumeOps(self._session)
        self._vmops = vmops.VMwareVMOps(self._session, self.virtapi,
                                        self._volumeops)
        self._host = host.Host(self._session)
        self._host_state = None

        #TODO(hartsocks): back-off into a configuration test module.
        if CONF.vmware.use_linked_clone is None:
            raise error_util.UseLinkedCloneConfigurationFault()

    @property
    def host_state(self):
        if not self._host_state:
            self._host_state = host.HostState(self._session,
                                              self._host_ip)
        return self._host_state

    def init_host(self, host):
        """Do the initialization that needs to be done."""
        # FIXME(sateesh): implement this
        pass

    def list_instances(self):
        """List VM instances."""
        return self._vmops.list_instances()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Create VM instance."""
        self._vmops.spawn(context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info)

    def snapshot(self, context, instance, name, update_task_state):
        """Create snapshot from a running VM instance."""
        self._vmops.snapshot(context, instance, name, update_task_state)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot VM instance."""
        self._vmops.reboot(instance, network_info)

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True, context=None):
        """Destroy VM instance."""
        self._vmops.destroy(instance, network_info, destroy_disks)

    def pause(self, instance):
        """Pause VM instance."""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        self._vmops.unpause(instance)

    def suspend(self, instance):
        """Suspend the specified instance."""
        self._vmops.suspend(instance)

    def resume(self, instance, network_info, block_device_info=None):
        """Resume the suspended VM instance."""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance."""
        self._vmops.rescue(context, instance, network_info, image_meta)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance."""
        self._vmops.unrescue(instance)

    def power_off(self, instance):
        """Power off the specified instance."""
        self._vmops.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        self._vmops._power_on(instance)

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        # Check if the instance is running already and avoid doing
        # anything if it is.
        instances = self.list_instances()
        if instance['uuid'] not in instances:
            LOG.warn(_('Instance cannot be found in host, or in an unknown'
                'state.'), instance=instance)
        else:
            state = vm_util.get_vm_state_from_name(self._session,
                instance['uuid'])
            ignored_states = ['poweredon', 'suspended']

            if state.lower() in ignored_states:
                return
        # Instance is not up and could be in an unknown state.
        # Be as absolute as possible about getting it back into
        # a known and running state.
        self.reboot(context, instance, network_info, 'hard',
            block_device_info)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        self._vmops.poll_rebooting_instances(timeout, instances)

    def get_info(self, instance):
        """Return info about the VM instance."""
        return self._vmops.get_info(instance)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        return self._vmops.get_info(instance)

    def get_console_output(self, instance):
        """Return snapshot of console."""
        # The method self._vmops.get_console_output(instance) returns
        # a PNG format. The vCenter and ESX do not provide a way
        # to get the text based console format.
        return _("Currently there is no log available for "
                 "instance %s") % instance['uuid']

    def get_vnc_console(self, instance):
        """Return link to instance's VNC console."""
        return self._vmops.get_vnc_console(instance)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        return self._volumeops.get_volume_connector(instance)

    def get_host_ip_addr(self):
        """Retrieves the IP address of the ESX host."""
        return self._host_ip

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Attach volume storage to VM instance."""
        return self._volumeops.attach_volume(connection_info,
                                             instance,
                                             mountpoint)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach volume storage to VM instance."""
        return self._volumeops.detach_volume(connection_info,
                                             instance,
                                             mountpoint)

    def get_console_pool_info(self, console_type):
        """Get info about the host on which the VM resides."""
        return {'address': CONF.vmware.host_ip,
                'username': CONF.vmware.host_username,
                'password': CONF.vmware.host_password}

    def _get_available_resources(self, host_stats):
        return {'vcpus': host_stats['vcpus'],
               'memory_mb': host_stats['host_memory_total'],
               'local_gb': host_stats['disk_total'],
               'vcpus_used': 0,
               'memory_mb_used': host_stats['host_memory_total'] -
                                 host_stats['host_memory_free'],
               'local_gb_used': host_stats['disk_used'],
               'hypervisor_type': host_stats['hypervisor_type'],
               'hypervisor_version': host_stats['hypervisor_version'],
               'hypervisor_hostname': host_stats['hypervisor_hostname'],
               'cpu_info': jsonutils.dumps(host_stats['cpu_info']),
               'supported_instances': jsonutils.dumps(
                   host_stats['supported_instances']),
               }

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :returns: dictionary describing resources

        """
        host_stats = self.get_host_stats(refresh=True)

        # Updating host information
        return self._get_available_resources(host_stats)

    def update_host_status(self):
        """Update the status info of the host, and return those values
           to the calling program.
        """
        return self.host_state.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host.

           If 'refresh' is True, run the update first.
        """
        return self.host_state.get_host_stats(refresh=refresh)

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        return self._host.host_power_action(host, action)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
           guest VMs evacuation.
        """
        return self._host.host_maintenance_mode(host, mode)

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self._host.set_host_enabled(host, enabled)

    def get_host_uptime(self, host):
        return 'Please refer to %s for the uptime' % CONF.vmware.host_ip

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        self._vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        self._vmops.plug_vifs(instance, network_info)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        self._vmops.unplug_vifs(instance, network_info)


class VMwareVCDriver(VMwareESXDriver):
    """The ESX host connection object."""

    # The vCenter driver includes several additional VMware vSphere
    # capabilities that include API that act on hosts or groups of
    # hosts in clusters or non-cluster logical-groupings.
    #
    # vCenter is not a hypervisor itself, it works with multiple
    # hypervisor host machines and their guests. This fact can
    # subtly alter how vSphere and OpenStack interoperate.

    def __init__(self, virtapi, read_only=False, scheme="https"):
        super(VMwareVCDriver, self).__init__(virtapi)

        # Get the list of clusters to be used
        self._cluster_names = CONF.vmware.cluster_name
        self.dict_mors = vm_util.get_all_cluster_refs_by_name(self._session,
                                          self._cluster_names)
        if not self.dict_mors:
            raise exception.NotFound(_("All clusters specified %s were not"
                                       " found in the vCenter")
                                     % self._cluster_names)

        # Check if there are any clusters that were specified in the nova.conf
        # but are not in the vCenter, for missing clusters log a warning.
        clusters_found = [v.get('name') for k, v in self.dict_mors.iteritems()]
        missing_clusters = set(self._cluster_names) - set(clusters_found)
        if missing_clusters:
            LOG.warn(_("The following clusters could not be found in the"
                " vCenter %s") % list(missing_clusters))

        self._datastore_regex = None
        if CONF.vmware.datastore_regex:
            try:
                self._datastore_regex = re.compile(CONF.vmware.datastore_regex)
            except re.error:
                raise exception.InvalidInput(reason=
                _("Invalid Regular Expression %s")
                % CONF.vmware.datastore_regex)
        # The _resources is used to maintain the vmops, volumeops and vcstate
        # objects per cluster
        self._resources = {}
        self._resource_keys = set()
        self._virtapi = virtapi
        self._update_resources()

        # The following initialization is necessary since the base class does
        # not use VC state.
        first_cluster = self._resources.keys()[0]
        self._vmops = self._resources.get(first_cluster).get('vmops')
        self._volumeops = self._resources.get(first_cluster).get('volumeops')
        self._vc_state = self._resources.get(first_cluster).get('vcstate')

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info,
                                   block_device_info=None):
        """
        Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        return self._vmops.migrate_disk_and_power_off(context, instance,
                                                      dest, instance_type)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, instance, network_info,
                                block_device_info=None, power_on=True):
        """Finish reverting a resize, powering back on the instance."""
        self._vmops.finish_revert_migration(instance, network_info,
                                            block_device_info, power_on)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance,
                                     block_device_info, power_on)

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Live migration of an instance to another host."""
        self._vmops.live_migration(context, instance_ref, dest,
                                   post_method, recover_method,
                                   block_migration)

    def get_vnc_console(self, instance):
        """Return link to instance's VNC console using vCenter logic."""
        # In this situation, ESXi and vCenter require different
        # API logic to create a valid VNC console connection object.
        # In specific, vCenter does not actually run the VNC service
        # itself. You must talk to the VNC host underneath vCenter.
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        return _vmops.get_vnc_console_vcenter(instance)

    def _update_resources(self):
        """This method creates a dictionary of VMOps, VolumeOps and VCState.

        The VMwareVMOps, VMwareVolumeOps and VCState object is for each
        cluster/rp. The dictionary is of the form
        {
            domain-1000 : {'vmops': vmops_obj,
                          'volumeops': volumeops_obj,
                          'vcstate': vcstate_obj,
                          'name': MyCluster},
            resgroup-1000 : {'vmops': vmops_obj,
                              'volumeops': volumeops_obj,
                              'vcstate': vcstate_obj,
                              'name': MyRP},
        }
        """
        added_nodes = set(self.dict_mors.keys()) - set(self._resource_keys)
        for node in added_nodes:
            _volumeops = volumeops.VMwareVolumeOps(self._session,
                                        self.dict_mors[node]['cluster_mor'],
                                        vc_support=True)
            _vmops = vmops.VMwareVCVMOps(self._session, self._virtapi,
                                       _volumeops,
                                       self.dict_mors[node]['cluster_mor'],
                                       datastore_regex=self._datastore_regex)
            name = self.dict_mors.get(node)['name']
            nodename = self._create_nodename(node, name)
            _vc_state = host.VCState(self._session, nodename,
                                     self.dict_mors.get(node)['cluster_mor'])
            self._resources[nodename] = {'vmops': _vmops,
                                         'volumeops': _volumeops,
                                         'vcstate': _vc_state,
                                         'name': name,
                                     }
            self._resource_keys.add(node)

        deleted_nodes = (set(self._resource_keys) -
                            set(self.dict_mors.keys()))
        for node in deleted_nodes:
            name = self.dict_mors.get(node)['name']
            nodename = self._create_nodename(node, name)
            del self._resources[nodename]
            self._resource_keys.discard(node)

    def _create_nodename(self, mo_id, display_name):
        """Creates the name that is stored in hypervisor_hostname column.

        The name will be of the form similar to
        domain-1000(MyCluster)
        resgroup-1000(MyResourcePool)
        """
        return mo_id + '(' + display_name + ')'

    def _get_resource_for_node(self, nodename):
        """Gets the resource information for the specific node."""
        resource = self._resources.get(nodename)
        if not resource:
            msg = _("The resource %s does not exist") % nodename
            raise exception.NotFound(msg)
        return resource

    def _get_vmops_for_compute_node(self, nodename):
        """Retrieve vmops object from mo_id stored in the node name.

        Node name is of the form domain-1000(MyCluster)
        """
        resource = self._get_resource_for_node(nodename)
        return resource['vmops']

    def _get_volumeops_for_compute_node(self, nodename):
        """Retrieve vmops object from mo_id stored in the node name.

        Node name is of the form domain-1000(MyCluster)
        """
        resource = self._get_resource_for_node(nodename)
        return resource['volumeops']

    def _get_vc_state_for_compute_node(self, nodename):
        """Retrieve VCState object from mo_id stored in the node name.

        Node name is of the form domain-1000(MyCluster)
        """
        resource = self._get_resource_for_node(nodename)
        return resource['vcstate']

    def get_available_resource(self, nodename):
        """Retrieve resource info.

        This method is called when nova-compute launches, and
        as part of a periodic task.

        :returns: dictionary describing resources

        """
        stats_dict = {}
        vc_state = self._get_vc_state_for_compute_node(nodename)
        if vc_state:
            host_stats = vc_state.get_host_stats(refresh=True)

            # Updating host information
            stats_dict = self._get_available_resources(host_stats)

        else:
            LOG.info(_("Invalid cluster or resource pool"
                       " name : %s") % nodename)

        return stats_dict

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This method is for multi compute-nodes support. If a driver supports
        multi compute-nodes, this method returns a list of nodenames managed
        by the service. Otherwise, this method should return
        [hypervisor_hostname].
        """
        self.dict_mors = vm_util.get_all_cluster_refs_by_name(
                                self._session,
                                CONF.vmware.cluster_name)
        nodes = self.dict_mors.keys()
        node_list = []
        self._update_resources()
        for node in self.dict_mors.keys():
            nodename = self._create_nodename(node,
                                          self.dict_mors.get(node)['name'])
            node_list.append(nodename)
        LOG.debug(_("The available nodes are: %s") % node_list)
        return node_list

    def get_host_stats(self, refresh=True):
        """Return currently known host stats."""
        stats_list = []
        nodes = self.get_available_nodes()
        for node in nodes:
            stats_list.append(self.get_available_resource(node))
        return stats_list

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Create VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.spawn(context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Attach volume storage to VM instance."""
        _volumeops = self._get_volumeops_for_compute_node(instance['node'])
        return _volumeops.attach_volume(connection_info,
                                             instance,
                                             mountpoint)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach volume storage to VM instance."""
        _volumeops = self._get_volumeops_for_compute_node(instance['node'])
        return _volumeops.detach_volume(connection_info,
                                             instance,
                                             mountpoint)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        _volumeops = self._get_volumeops_for_compute_node(instance['node'])
        return _volumeops.get_volume_connector(instance)

    def snapshot(self, context, instance, name, update_task_state):
        """Create snapshot from a running VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.snapshot(context, instance, name, update_task_state)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.reboot(instance, network_info)

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True, context=None):
        """Destroy VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.destroy(instance, network_info, destroy_disks)

    def pause(self, instance):
        """Pause VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.unpause(instance)

    def suspend(self, instance):
        """Suspend the specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.suspend(instance)

    def resume(self, instance, network_info, block_device_info=None):
        """Resume the suspended VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.rescue(context, instance, network_info, image_meta)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.unrescue(instance)

    def power_off(self, instance):
        """Power off the specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops._power_on(instance)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        for instance in instances:
            _vmops = self._get_vmops_for_compute_node(instance['node'])
            _vmops.poll_rebooting_instances(timeout, [instance])

    def get_info(self, instance):
        """Return info about the VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        return _vmops.get_info(instance)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        return _vmops.get_info(instance)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.plug_vifs(instance, network_info)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.unplug_vifs(instance, network_info)


class VMwareAPISession(object):
    """
    Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """

    def __init__(self, host_ip=CONF.vmware.host_ip,
                 username=CONF.vmware.host_username,
                 password=CONF.vmware.host_password,
                 retry_count=CONF.vmware.api_retry_count,
                 scheme="https"):
        self._host_ip = host_ip
        self._host_username = username
        self._host_password = password
        self._api_retry_count = retry_count
        self._scheme = scheme
        self._session_id = None
        self.vim = None
        self._create_session()

    def _get_vim_object(self):
        """Create the VIM Object instance."""
        return vim.Vim(protocol=self._scheme, host=self._host_ip)

    def _create_session(self):
        """Creates a session with the VC/ESX host."""

        delay = 1

        while True:
            try:
                # Login and setup the session with the host for making
                # API calls
                self.vim = self._get_vim_object()
                session = self.vim.Login(
                               self.vim.get_service_content().sessionManager,
                               userName=self._host_username,
                               password=self._host_password)
                # Terminate the earlier session, if possible ( For the sake of
                # preserving sessions as there is a limit to the number of
                # sessions we can have )
                if self._session_id:
                    try:
                        self.vim.TerminateSession(
                                self.vim.get_service_content().sessionManager,
                                sessionId=[self._session_id])
                    except Exception as excep:
                        # This exception is something we can live with. It is
                        # just an extra caution on our side. The session may
                        # have been cleared. We could have made a call to
                        # SessionIsActive, but that is an overhead because we
                        # anyway would have to call TerminateSession.
                        LOG.debug(excep)
                self._session_id = session.key
                return
            except Exception as excep:
                LOG.critical(_("Unable to connect to server at %(server)s, "
                    "sleeping for %(seconds)s seconds"),
                    {'server': self._host_ip, 'seconds': delay})
                time.sleep(delay)
                delay = min(2 * delay, 60)

    def __del__(self):
        """Logs-out the session."""
        # Logout to avoid un-necessary increase in session count at the
        # ESX host
        try:
            # May not have been able to connect to VC, so vim is still None
            if self.vim:
                self.vim.Logout(self.vim.get_service_content().sessionManager)
        except Exception as excep:
            # It is just cautionary on our part to do a logout in del just
            # to ensure that the session is not left active.
            LOG.debug(excep)

    def _is_vim_object(self, module):
        """Check if the module is a VIM Object instance."""
        return isinstance(module, vim.Vim)

    def _call_method(self, module, method, *args, **kwargs):
        """
        Calls a method within the module specified with
        args provided.
        """
        args = list(args)
        retry_count = 0
        exc = None
        last_fault_list = []
        while True:
            try:
                if not self._is_vim_object(module):
                    # If it is not the first try, then get the latest
                    # vim object
                    if retry_count > 0:
                        args = args[1:]
                    args = [self.vim] + args
                retry_count += 1
                temp_module = module

                for method_elem in method.split("."):
                    temp_module = getattr(temp_module, method_elem)

                return temp_module(*args, **kwargs)
            except error_util.VimFaultException as excep:
                # If it is a Session Fault Exception, it may point
                # to a session gone bad. So we try re-creating a session
                # and then proceeding ahead with the call.
                exc = excep
                if error_util.FAULT_NOT_AUTHENTICATED in excep.fault_list:
                    # Because of the idle session returning an empty
                    # RetrievePropertiesResponse and also the same is returned
                    # when there is say empty answer to the query for
                    # VMs on the host ( as in no VMs on the host), we have no
                    # way to differentiate.
                    # So if the previous response was also am empty response
                    # and after creating a new session, we get the same empty
                    # response, then we are sure of the response being supposed
                    # to be empty.
                    if error_util.FAULT_NOT_AUTHENTICATED in last_fault_list:
                        return []
                    last_fault_list = excep.fault_list
                    self._create_session()
                else:
                    # No re-trying for errors for API call has gone through
                    # and is the caller's fault. Caller should handle these
                    # errors. e.g, InvalidArgument fault.
                    break
            except error_util.SessionOverLoadException as excep:
                # For exceptions which may come because of session overload,
                # we retry
                exc = excep
            except Exception as excep:
                # If it is a proper exception, say not having furnished
                # proper data in the SOAP call or the retry limit having
                # exceeded, we raise the exception
                exc = excep
                break
            # If retry count has been reached then break and
            # raise the exception
            if retry_count > self._api_retry_count:
                break
            time.sleep(TIME_BETWEEN_API_CALL_RETRIES)

        LOG.critical(_("In vmwareapi:_call_method, "
                     "got this exception: %s") % exc)
        raise

    def _get_vim(self):
        """Gets the VIM object reference."""
        if self.vim is None:
            self._create_session()
        return self.vim

    def _wait_for_task(self, instance_uuid, task_ref):
        """
        Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        done = event.Event()
        loop = loopingcall.FixedIntervalLoopingCall(self._poll_task,
                                                    instance_uuid,
                                                    task_ref, done)
        loop.start(CONF.vmware.task_poll_interval)
        ret_val = done.wait()
        loop.stop()
        return ret_val

    def _poll_task(self, instance_uuid, task_ref, done):
        """
        Poll the given task, and fires the given Deferred if we
        get a result.
        """
        try:
            task_info = self._call_method(vim_util, "get_dynamic_property",
                            task_ref, "Task", "info")
            task_name = task_info.name
            if task_info.state in ['queued', 'running']:
                return
            elif task_info.state == 'success':
                LOG.debug(_("Task [%(task_name)s] %(task_ref)s "
                            "status: success"),
                          {'task_name': task_name, 'task_ref': task_ref})
                done.send("success")
            else:
                error_info = str(task_info.error.localizedMessage)
                LOG.warn(_("Task [%(task_name)s] %(task_ref)s "
                          "status: error %(error_info)s"),
                         {'task_name': task_name, 'task_ref': task_ref,
                          'error_info': error_info})
                done.send_exception(exception.NovaException(error_info))
        except Exception as excep:
            LOG.warn(_("In vmwareapi:_poll_task, Got this error %s") % excep)
            done.send_exception(excep)
