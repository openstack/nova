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
A connection to the VMware vCenter platform.
"""

import re

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_vmware import api
from oslo_vmware import exceptions as vexc
from oslo_vmware import pbm
from oslo_vmware import vim
from oslo_vmware import vim_util

from nova import exception
from nova.i18n import _, _LI, _LW
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import host
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import volumeops

LOG = logging.getLogger(__name__)

vmwareapi_opts = [
    cfg.StrOpt('host_ip',
               help='Hostname or IP address for connection to VMware VC '
                    'host.'),
    cfg.IntOpt('host_port',
               default=443,
               help='Port for connection to VMware VC host.'),
    cfg.StrOpt('host_username',
               help='Username for connection to VMware VC host.'),
    cfg.StrOpt('host_password',
               help='Password for connection to VMware VC host.',
               secret=True),
    cfg.MultiStrOpt('cluster_name',
                    help='Name of a VMware Cluster ComputeResource.'),
    cfg.StrOpt('datastore_regex',
               help='Regex to match the name of a datastore.'),
    cfg.FloatOpt('task_poll_interval',
                 default=0.5,
                 help='The interval used for polling of remote tasks.'),
    cfg.IntOpt('api_retry_count',
               default=10,
               help='The number of times we retry on failures, e.g., '
                    'socket error, etc.'),
    cfg.IntOpt('vnc_port',
               default=5900,
               help='VNC starting port'),
    cfg.IntOpt('vnc_port_total',
               default=10000,
               help='Total number of VNC ports'),
    cfg.BoolOpt('use_linked_clone',
                default=True,
                help='Whether to use linked clone'),
    cfg.StrOpt('wsdl_location',
               help='Optional VIM Service WSDL Location '
                    'e.g http://<server>/vimService.wsdl. '
                    'Optional over-ride to default location for bug '
                    'work-arounds')
    ]

spbm_opts = [
    cfg.BoolOpt('pbm_enabled',
                default=False,
                help='The PBM status.'),
    cfg.StrOpt('pbm_wsdl_location',
               help='PBM service WSDL file location URL. '
                    'e.g. file:///opt/SDK/spbm/wsdl/pbmService.wsdl '
                    'Not setting this will disable storage policy based '
                    'placement of instances.'),
    cfg.StrOpt('pbm_default_policy',
               help='The PBM default policy. If pbm_wsdl_location is set and '
                    'there is no defined storage policy for the specific '
                    'request then this policy will be used.'),
    ]

CONF = cfg.CONF
CONF.register_opts(vmwareapi_opts, 'vmware')
CONF.register_opts(spbm_opts, 'vmware')

TIME_BETWEEN_API_CALL_RETRIES = 1.0


class VMwareVCDriver(driver.ComputeDriver):
    """The VC host connection object."""

    capabilities = {
        "has_imagecache": True,
        "supports_recreate": False,
        }

    # The vCenter driver includes API that acts on ESX hosts or groups
    # of ESX hosts in clusters or non-cluster logical-groupings.
    #
    # vCenter is not a hypervisor itself, it works with multiple
    # hypervisor host machines and their guests. This fact can
    # subtly alter how vSphere and OpenStack interoperate.

    def __init__(self, virtapi, scheme="https"):
        super(VMwareVCDriver, self).__init__(virtapi)

        if (CONF.vmware.host_ip is None or
            CONF.vmware.host_username is None or
            CONF.vmware.host_password is None):
            raise Exception(_("Must specify host_ip, host_username and "
                              "host_password to use vmwareapi.VMwareVCDriver"))

        self._datastore_regex = None
        if CONF.vmware.datastore_regex:
            try:
                self._datastore_regex = re.compile(CONF.vmware.datastore_regex)
            except re.error:
                raise exception.InvalidInput(reason=
                    _("Invalid Regular Expression %s")
                    % CONF.vmware.datastore_regex)

        self._session = VMwareAPISession(scheme=scheme)

        # Update the PBM location if necessary
        if CONF.vmware.pbm_enabled:
            self._update_pbm_location()

        self._validate_configuration()

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
            LOG.warning(_LW("The following clusters could not be found in the "
                            "vCenter %s"), list(missing_clusters))

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

        # Register the OpenStack extension
        self._register_openstack_extension()

    @property
    def need_legacy_block_device_info(self):
        return False

    def _update_pbm_location(self):
        if CONF.vmware.pbm_wsdl_location:
            pbm_wsdl_loc = CONF.vmware.pbm_wsdl_location
        else:
            version = vim_util.get_vc_version(self._session)
            pbm_wsdl_loc = pbm.get_pbm_wsdl_location(version)
        self._session.pbm_wsdl_loc_set(pbm_wsdl_loc)

    def _validate_configuration(self):
        if CONF.vmware.use_linked_clone is None:
            raise vexc.UseLinkedCloneConfigurationFault()

        if CONF.vmware.pbm_enabled:
            if not CONF.vmware.pbm_default_policy:
                raise error_util.PbmDefaultPolicyUnspecified()
            if not pbm.get_profile_id_by_name(
                            self._session,
                            CONF.vmware.pbm_default_policy):
                raise error_util.PbmDefaultPolicyDoesNotExist()
            if CONF.vmware.datastore_regex:
                LOG.warning(_LW(
                    "datastore_regex is ignored when PBM is enabled"))
                self._datastore_regex = None

    def init_host(self, host):
        vim = self._session.vim
        if vim is None:
            self._session._create_session()

    def cleanup_host(self, host):
        self._session.logout()

    def _register_openstack_extension(self):
        # Register an 'OpenStack' extension in vCenter
        LOG.debug('Registering extension %s with vCenter',
                  constants.EXTENSION_KEY)
        os_extension = self._session._call_method(vim_util, 'find_extension',
                                                  constants.EXTENSION_KEY)
        if os_extension is None:
            LOG.debug('Extension does not exist. Registering type %s.',
                      constants.EXTENSION_TYPE_INSTANCE)
            self._session._call_method(vim_util, 'register_extension',
                                       constants.EXTENSION_KEY,
                                       constants.EXTENSION_TYPE_INSTANCE)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        """Cleanup after instance being destroyed by Hypervisor."""
        pass

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        # Check if the instance is running already and avoid doing
        # anything if it is.
        state = vm_util.get_vm_state(self._session, instance)
        ignored_states = ['poweredon', 'suspended']
        if state.lower() in ignored_states:
            return
        # Instance is not up and could be in an unknown state.
        # Be as absolute as possible about getting it back into
        # a known and running state.
        self.reboot(context, instance, network_info, 'hard',
                    block_device_info)

    def list_instance_uuids(self):
        """List VM instance UUIDs."""
        return self._vmops.list_instances()

    def list_instances(self):
        """List VM instances from all nodes."""
        instances = []
        nodes = self.get_available_nodes()
        for node in nodes:
            vmops = self._get_vmops_for_compute_node(node)
            instances.extend(vmops.list_instances())
        return instances

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        """Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        # TODO(PhilDay): Add support for timeout (clean shutdown)
        return self._vmops.migrate_disk_and_power_off(context, instance,
                                                      dest, flavor)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        """Finish reverting a resize, powering back on the instance."""
        self._vmops.finish_revert_migration(context, instance, network_info,
                                            block_device_info, power_on)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance,
                                     block_device_info, power_on)

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Live migration of an instance to another host."""
        self._vmops.live_migration(context, instance, dest,
                                   post_method, recover_method,
                                   block_migration)

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        """Clean up destination node after a failed live migration."""
        self.destroy(context, instance, network_info, block_device_info)

    def get_instance_disk_info(self, instance, block_device_info=None):
        pass

    def get_vnc_console(self, context, instance):
        """Return link to instance's VNC console using vCenter logic."""
        # vCenter does not actually run the VNC service
        # itself. You must talk to the VNC host underneath vCenter.
        return self._vmops.get_vnc_console(instance)

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
                                        self.dict_mors[node]['cluster_mor'])
            _vmops = vmops.VMwareVMOps(self._session, self._virtapi,
                                       _volumeops,
                                       self.dict_mors[node]['cluster_mor'],
                                       datastore_regex=self._datastore_regex)
            name = self.dict_mors.get(node)['name']
            nodename = self._create_nodename(node, name)
            _vc_state = host.VCState(self._session, nodename,
                                     self.dict_mors.get(node)['cluster_mor'],
                                     self._datastore_regex)
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
                # The VMWare driver manages multiple hosts, so there are
                # likely many different CPU models in use. As such it is
                # impossible to provide any meaningful info on the CPU
                # model of the "host"
               'cpu_info': None,
               'supported_instances': jsonutils.dumps(
                   host_stats['supported_instances']),
               'numa_topology': None,
               }

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
            LOG.info(_LI("Invalid cluster or resource pool"
                         " name : %s"), nodename)

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
        node_list = []
        self._update_resources()
        for node in self.dict_mors.keys():
            nodename = self._create_nodename(node,
                                          self.dict_mors.get(node)['name'])
            node_list.append(nodename)
        LOG.debug("The available nodes are: %s", node_list)
        return node_list

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              flavor=None):
        """Create VM instance."""
        _vmops = self._get_vmops_for_compute_node(instance['node'])
        _vmops.spawn(context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info,
              flavor=flavor)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach volume storage to VM instance."""
        _volumeops = self._get_volumeops_for_compute_node(instance['node'])
        return _volumeops.attach_volume(connection_info,
                                        instance)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach volume storage to VM instance."""
        _volumeops = self._get_volumeops_for_compute_node(instance['node'])
        return _volumeops.detach_volume(connection_info,
                                        instance)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        return self._volumeops.get_volume_connector(instance)

    def get_host_ip_addr(self):
        """Returns the IP address of the vCenter host."""
        return CONF.vmware.host_ip

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance."""
        self._vmops.snapshot(context, instance, image_id, update_task_state)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot VM instance."""
        self._vmops.reboot(instance, network_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        """Destroy VM instance."""

        # Destroy gets triggered when Resource Claim in resource_tracker
        # is not successful. When resource claim is not successful,
        # node is not set in instance. Perform destroy only if node is set
        if not instance['node']:
            return

        self._vmops.destroy(instance, destroy_disks)

    def pause(self, instance):
        """Pause VM instance."""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        self._vmops.unpause(instance)

    def suspend(self, instance):
        """Suspend the specified instance."""
        self._vmops.suspend(instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        """Resume the suspended VM instance."""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance."""
        self._vmops.rescue(context, instance, network_info, image_meta)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance."""
        self._vmops.unrescue(instance)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance."""
        # TODO(PhilDay): Add support for timeout (clean shutdown)
        self._vmops.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        self._vmops.power_on(instance)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        self._vmops.poll_rebooting_instances(timeout, instances)

    def get_info(self, instance):
        """Return info about the VM instance."""
        return self._vmops.get_info(instance)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        return self._vmops.get_diagnostics(instance)

    def get_instance_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        return self._vmops.get_instance_diagnostics(instance)

    def host_power_action(self, action):
        """Host operations not supported by VC driver.

        This needs to override the ESX driver implementation.
        """
        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        """Host operations not supported by VC driver.

        This needs to override the ESX driver implementation.
        """
        raise NotImplementedError()

    def set_host_enabled(self, enabled):
        """Host operations not supported by VC driver.

        This needs to override the ESX driver implementation.
        """
        raise NotImplementedError()

    def get_host_uptime(self):
        """Host uptime operation not supported by VC driver."""

        msg = _("Multiple hosts may be managed by the VMWare "
                "vCenter driver; therefore we do not return "
                "uptime for just one host.")
        raise NotImplementedError(msg)

    def inject_network_info(self, instance, nw_info):
        """inject network info for specified instance."""
        self._vmops.inject_network_info(instance, nw_info)

    def manage_image_cache(self, context, all_instances):
        """Manage the local cache of images."""

        # Running instances per cluster
        cluster_instances = {}
        for instance in all_instances:
            instances = cluster_instances.get(instance['node'])
            if instances:
                instances.append(instance)
            else:
                instances = [instance]
            cluster_instances[instance['node']] = instances

        # Invoke the image aging per cluster
        for resource in self._resources.keys():
            instances = cluster_instances.get(resource, [])
            _vmops = self._get_vmops_for_compute_node(resource)
            _vmops.manage_image_cache(context, instances)

    def instance_exists(self, instance):
        """Efficient override of base instance_exists method."""
        return self._vmops.instance_exists(instance)

    def attach_interface(self, instance, image_meta, vif):
        """Attach an interface to the instance."""
        self._vmops.attach_interface(instance, image_meta, vif)

    def detach_interface(self, instance, vif):
        """Detach an interface from the instance."""
        self._vmops.detach_interface(instance, vif)


class VMwareAPISession(api.VMwareAPISession):
    """Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """
    def __init__(self, host_ip=CONF.vmware.host_ip,
                 host_port=CONF.vmware.host_port,
                 username=CONF.vmware.host_username,
                 password=CONF.vmware.host_password,
                 retry_count=CONF.vmware.api_retry_count,
                 scheme="https"):
        super(VMwareAPISession, self).__init__(
                host=host_ip,
                port=host_port,
                server_username=username,
                server_password=password,
                api_retry_count=retry_count,
                task_poll_interval=CONF.vmware.task_poll_interval,
                scheme=scheme,
                create_session=True,
                wsdl_loc=CONF.vmware.wsdl_location
                )

    def _is_vim_object(self, module):
        """Check if the module is a VIM Object instance."""
        return isinstance(module, vim.Vim)

    def _call_method(self, module, method, *args, **kwargs):
        """Calls a method within the module specified with
        args provided.
        """
        if not self._is_vim_object(module):
            return self.invoke_api(module, method, self.vim, *args, **kwargs)
        else:
            return self.invoke_api(module, method, *args, **kwargs)

    def _wait_for_task(self, task_ref):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        return self.wait_for_task(task_ref)
