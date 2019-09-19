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

import os
import re

import os_resource_classes as orc
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
from oslo_utils import versionutils as v_utils
from oslo_vmware import api
from oslo_vmware import exceptions as vexc
from oslo_vmware import pbm
from oslo_vmware import vim
from oslo_vmware import vim_util

from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
import nova.privsep.path
from nova.virt import driver
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import host
from nova.virt.vmwareapi import vim_util as nova_vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import volumeops

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

TIME_BETWEEN_API_CALL_RETRIES = 1.0
MAX_CONSOLE_BYTES = 100 * units.Ki


class VMwareVCDriver(driver.ComputeDriver):
    """The VC host connection object."""

    capabilities = {
        "has_imagecache": True,
        "supports_evacuate": False,
        "supports_migrate_to_same_host": True,
        "supports_attach_interface": True,
        "supports_multiattach": False,
        "supports_trusted_certs": False,
        "supports_pcpus": False,

        # Image type support flags
        "supports_image_type_aki": False,
        "supports_image_type_ami": False,
        "supports_image_type_ari": False,
        "supports_image_type_iso": True,
        "supports_image_type_qcow2": False,
        "supports_image_type_raw": False,
        "supports_image_type_vdi": False,
        "supports_image_type_vhd": False,
        "supports_image_type_vhdx": False,
        "supports_image_type_vmdk": True,
    }

    # Legacy nodename is of the form: <mo id>(<cluster name>)
    # e.g. domain-26(TestCluster)
    # We assume <mo id> consists of alphanumeric, _ and -.
    # We assume cluster name is everything between the first ( and the last ).
    # We pull out <mo id> for re-use.
    LEGACY_NODENAME = re.compile(r'([\w-]+)\(.+\)')

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

        if CONF.vnc.keymap:
            LOG.warning('The option "[vnc] keymap" has been deprecated in '
                        'favor of the VMWare-specific "[vmware] vnc_keymap" '
                        'option. Please update nova.conf to address this '
                        'change')

        self._datastore_regex = None
        if CONF.vmware.datastore_regex:
            try:
                self._datastore_regex = re.compile(CONF.vmware.datastore_regex)
            except re.error:
                raise exception.InvalidInput(reason=
                    _("Invalid Regular Expression %s")
                    % CONF.vmware.datastore_regex)

        self._session = VMwareAPISession(scheme=scheme)

        self._check_min_version()

        # Update the PBM location if necessary
        if CONF.vmware.pbm_enabled:
            self._update_pbm_location()

        self._validate_configuration()
        self._cluster_name = CONF.vmware.cluster_name
        self._cluster_ref = vm_util.get_cluster_ref_by_name(self._session,
                                                            self._cluster_name)
        if self._cluster_ref is None:
            raise exception.NotFound(_("The specified cluster '%s' was not "
                                       "found in vCenter")
                                     % self._cluster_name)
        self._vcenter_uuid = self._get_vcenter_uuid()
        self._nodename = self._create_nodename(self._cluster_ref.value)
        self._volumeops = volumeops.VMwareVolumeOps(self._session,
                                                    self._cluster_ref)
        self._vmops = vmops.VMwareVMOps(self._session,
                                        virtapi,
                                        self._volumeops,
                                        self._cluster_ref,
                                        datastore_regex=self._datastore_regex)
        self._vc_state = host.VCState(self._session,
                                      self._nodename,
                                      self._cluster_ref,
                                      self._datastore_regex)

        # Register the OpenStack extension
        self._register_openstack_extension()

    def _check_min_version(self):
        min_version = v_utils.convert_version_to_int(constants.MIN_VC_VERSION)
        next_min_ver = v_utils.convert_version_to_int(
            constants.NEXT_MIN_VC_VERSION)
        vc_version = vim_util.get_vc_version(self._session)
        LOG.info("VMware vCenter version: %s", vc_version)
        if v_utils.convert_version_to_int(vc_version) < min_version:
            raise exception.NovaException(
                _('Detected vCenter version %(version)s. Nova requires VMware '
                  'vCenter version %(min_version)s or greater.') % {
                      'version': vc_version,
                      'min_version': constants.MIN_VC_VERSION})
        elif v_utils.convert_version_to_int(vc_version) < next_min_ver:
            LOG.warning('Running Nova with a VMware vCenter version less '
                        'than %(version)s is deprecated. The required '
                        'minimum version of vCenter will be raised to '
                        '%(version)s in the 16.0.0 release.',
                        {'version': constants.NEXT_MIN_VC_VERSION})

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
        if CONF.vmware.pbm_enabled:
            if not CONF.vmware.pbm_default_policy:
                raise error_util.PbmDefaultPolicyUnspecified()
            if not pbm.get_profile_id_by_name(
                            self._session,
                            CONF.vmware.pbm_default_policy):
                raise error_util.PbmDefaultPolicyDoesNotExist()
            if CONF.vmware.datastore_regex:
                LOG.warning("datastore_regex is ignored when PBM is enabled")
                self._datastore_regex = None

    def init_host(self, host):
        vim = self._session.vim
        if vim is None:
            self._session._create_session()

    def cleanup_host(self, host):
        self._session.logout()

    def _register_openstack_extension(self):
        # Register an 'OpenStack' extension in vCenter
        os_extension = self._session._call_method(vim_util, 'find_extension',
                                                  constants.EXTENSION_KEY)
        if os_extension is None:
            try:
                self._session._call_method(vim_util, 'register_extension',
                                           constants.EXTENSION_KEY,
                                           constants.EXTENSION_TYPE_INSTANCE)
                LOG.info('Registered extension %s with vCenter',
                         constants.EXTENSION_KEY)
            except vexc.VimFaultException as e:
                with excutils.save_and_reraise_exception() as ctx:
                    if 'InvalidArgument' in e.fault_list:
                        LOG.debug('Extension %s already exists.',
                                  constants.EXTENSION_KEY)
                        ctx.reraise = False
        else:
            LOG.debug('Extension %s already exists.', constants.EXTENSION_KEY)

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
        ignored_states = [power_state.RUNNING, power_state.SUSPENDED]
        if state in ignored_states:
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
        """List VM instances from the single compute node."""
        return self._vmops.list_instances()

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

    def confirm_migration(self, context, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                migration, block_device_info=None,
                                power_on=True):
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

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        pass

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        return migrate_data

    def post_live_migration_at_source(self, context, instance, network_info):
        pass

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        pass

    def cleanup_live_migration_destination_check(self, context,
                                                 dest_check_data):
        pass

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Live migration of an instance to another host."""
        self._vmops.live_migration(context, instance, dest, post_method,
                                   recover_method, block_migration,
                                   migrate_data)

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        cluster_name = dest_check_data.cluster_name
        cluster_ref = vm_util.get_cluster_ref_by_name(self._session,
                                                      cluster_name)
        if cluster_ref is None:
            msg = (_("Cannot find destination cluster %s for live migration") %
                   cluster_name)
            raise exception.MigrationPreCheckError(reason=msg)
        res_pool_ref = vm_util.get_res_pool_ref(self._session, cluster_ref)
        if res_pool_ref is None:
            msg = _("Cannot find destination resource pool for live migration")
            raise exception.MigrationPreCheckError(reason=msg)
        return dest_check_data

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        # the information that we need for the destination compute node
        # is the name of its cluster and datastore regex
        data = objects.VMwareLiveMigrateData()
        data.cluster_name = CONF.vmware.cluster_name
        data.datastore_regex = CONF.vmware.datastore_regex
        return data

    def unfilter_instance(self, instance, network_info):
        pass

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

    def get_mks_console(self, context, instance):
        return self._vmops.get_mks_console(instance)

    def get_console_output(self, context, instance):
        if not CONF.vmware.serial_log_dir:
            LOG.error("The 'serial_log_dir' config option is not set!")
            return
        fname = instance.uuid.replace('-', '')
        path = os.path.join(CONF.vmware.serial_log_dir, fname)
        if not os.path.exists(path):
            LOG.warning('The console log is missing. Check your VSPC '
                        'configuration', instance=instance)
            return b""
        read_log_data, remaining = nova.privsep.path.last_bytes(
            path, MAX_CONSOLE_BYTES)
        return read_log_data

    def _get_vcenter_uuid(self):
        """Retrieves the vCenter UUID."""

        about = self._session._call_method(nova_vim_util, 'get_about_info')
        return about.instanceUuid

    def _create_nodename(self, mo_id):
        """Return a nodename which uniquely describes a cluster.

        The name will be of the form:
          <mo id>.<vcenter uuid>
        e.g.
          domain-26.9d51f082-58a4-4449-beed-6fd205a5726b
        """

        return '%s.%s' % (mo_id, self._vcenter_uuid)

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
               'supported_instances': host_stats['supported_instances'],
               'numa_topology': None,
               }

    def get_available_resource(self, nodename):
        """Retrieve resource info.

        This method is called when nova-compute launches, and
        as part of a periodic task.

        :returns: dictionary describing resources

        """
        host_stats = self._vc_state.get_host_stats(refresh=True)
        stats_dict = self._get_available_resources(host_stats)
        return stats_dict

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This driver supports only one compute node.
        """
        return [self._nodename]

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update a ProviderTree object with current resource provider,
        inventory information and CPU traits.

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
            allocations.
        :raises ReshapeNeeded: If allocations is None and any inventory needs
            to be moved from one provider to another and/or to a different
            resource class. At this time the VMware driver does not reshape.
        :raises: ReshapeFailed if the requested tree reshape fails for
            whatever reason.
        """
        # NOTE(cdent): This is a side-effecty method, we are changing the
        # the provider tree in place (on purpose).
        inv = provider_tree.data(nodename).inventory
        ratios = self._get_allocation_ratios(inv)
        stats = vm_util.get_stats_from_cluster(self._session,
                                               self._cluster_ref)
        datastores = ds_util.get_available_datastores(self._session,
                                                      self._cluster_ref,
                                                      self._datastore_regex)
        total_disk_capacity = sum([ds.capacity for ds in datastores])
        max_free_space = max([ds.freespace for ds in datastores])
        reserved_disk_gb = compute_utils.convert_mb_to_ceil_gb(
            CONF.reserved_host_disk_mb)
        result = {
            orc.VCPU: {
                'total': stats['cpu']['vcpus'],
                'reserved': CONF.reserved_host_cpus,
                'min_unit': 1,
                'max_unit': stats['cpu']['max_vcpus_per_host'],
                'step_size': 1,
                'allocation_ratio': ratios[orc.VCPU],
            },
            orc.MEMORY_MB: {
                'total': stats['mem']['total'],
                'reserved': CONF.reserved_host_memory_mb,
                'min_unit': 1,
                'max_unit': stats['mem']['max_mem_mb_per_host'],
                'step_size': 1,
                'allocation_ratio': ratios[orc.MEMORY_MB],
            },
        }

        # If a sharing DISK_GB provider exists in the provider tree, then our
        # storage is shared, and we should not report the DISK_GB inventory in
        # the compute node provider.
        # TODO(cdent): We don't do this yet, in part because of the issues
        # in bug #1784020, but also because we can represent all datastores
        # as shared providers and should do once update_provider_tree is
        # working well.
        if provider_tree.has_sharing_provider(orc.DISK_GB):
            LOG.debug('Ignoring sharing provider - see bug #1784020')
        result[orc.DISK_GB] = {
            'total': total_disk_capacity // units.Gi,
            'reserved': reserved_disk_gb,
            'min_unit': 1,
            'max_unit': max_free_space // units.Gi,
            'step_size': 1,
            'allocation_ratio': ratios[orc.DISK_GB],
        }

        provider_tree.update_inventory(nodename, result)

        # TODO(cdent): Here is where additional functionality would be added.
        # In the libvirt driver this is where nested GPUs are reported and
        # where cpu traits are added. In the vmware world, this is where we
        # would add nested providers representing tenant VDC and similar.

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True):
        """Create VM instance."""
        self._vmops.spawn(context, instance, image_meta, injected_files,
                          admin_password, network_info, block_device_info)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach volume storage to VM instance."""
        return self._volumeops.attach_volume(connection_info, instance)

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach volume storage to VM instance."""
        # NOTE(claudiub): if context parameter is to be used in the future,
        # the _detach_instance_volumes method will have to be updated as well.
        return self._volumeops.detach_volume(connection_info, instance)

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
        self._vmops.reboot(instance, network_info, reboot_type)

    def _detach_instance_volumes(self, instance, block_device_info):
        # We need to detach attached volumes
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        if block_device_mapping:
            # Certain disk types, for example 'IDE' do not support hot
            # plugging. Hence we need to power off the instance and update
            # the instance state.
            self._vmops.power_off(instance)
            for disk in block_device_mapping:
                connection_info = disk['connection_info']
                try:
                    # NOTE(claudiub): Passing None as the context, as it is
                    # not currently used.
                    self.detach_volume(None, connection_info, instance,
                                       disk.get('device_name'))
                except exception.DiskNotFound:
                    LOG.warning('The volume %s does not exist!',
                                disk.get('device_name'),
                                instance=instance)
                except Exception as e:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Failed to detach %(device_name)s. "
                                  "Exception: %(exc)s",
                                  {'device_name': disk.get('device_name'),
                                   'exc': e},
                                  instance=instance)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy VM instance."""

        # Destroy gets triggered when Resource Claim in resource_tracker
        # is not successful. When resource claim is not successful,
        # node is not set in instance. Perform destroy only if node is set
        if not instance.node:
            return

        # A resize uses the same instance on the VC. We do not delete that
        # VM in the event of a revert
        if instance.task_state == task_states.RESIZE_REVERTING:
            return

        # We need to detach attached volumes
        if block_device_info is not None:
            try:
                self._detach_instance_volumes(instance, block_device_info)
            except vexc.ManagedObjectNotFoundException:
                LOG.warning('Instance does not exists. Proceeding to '
                            'delete instance properties on datastore',
                            instance=instance)
        self._vmops.destroy(instance, destroy_disks)

    def pause(self, instance):
        """Pause VM instance."""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        self._vmops.unpause(instance)

    def suspend(self, context, instance):
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
        self._vmops.power_off(instance, timeout, retry_interval)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        self._vmops.power_on(instance)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        self._vmops.poll_rebooting_instances(timeout, instances)

    def get_info(self, instance, use_cache=True):
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
        self._vmops.manage_image_cache(context, all_instances)

    def instance_exists(self, instance):
        """Efficient override of base instance_exists method."""
        return self._vmops.instance_exists(instance)

    def attach_interface(self, context, instance, image_meta, vif):
        """Attach an interface to the instance."""
        self._vmops.attach_interface(context, instance, image_meta, vif)

    def detach_interface(self, context, instance, vif):
        """Detach an interface from the instance."""
        self._vmops.detach_interface(context, instance, vif)


class VMwareAPISession(api.VMwareAPISession):
    """Sets up a session with the VC/ESX host and handles all
    the calls made to the host.
    """
    def __init__(self, host_ip=CONF.vmware.host_ip,
                 host_port=CONF.vmware.host_port,
                 username=CONF.vmware.host_username,
                 password=CONF.vmware.host_password,
                 retry_count=CONF.vmware.api_retry_count,
                 scheme="https",
                 cacert=CONF.vmware.ca_file,
                 insecure=CONF.vmware.insecure,
                 pool_size=CONF.vmware.connection_pool_size):
        super(VMwareAPISession, self).__init__(
                host=host_ip,
                port=host_port,
                server_username=username,
                server_password=password,
                api_retry_count=retry_count,
                task_poll_interval=CONF.vmware.task_poll_interval,
                scheme=scheme,
                create_session=True,
                cacert=cacert,
                insecure=insecure,
                pool_size=pool_size)

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
