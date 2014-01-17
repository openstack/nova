# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack Foundation
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
A driver for XenServer or Xen Cloud Platform.

**Related Flags**

:connection_url:  URL for connection to XenServer/Xen Cloud Platform.
:connection_username:  Username for connection to XenServer/Xen Cloud
                       Platform (default: root).
:connection_password:  Password for connection to XenServer/Xen Cloud
                       Platform.
:target_host:                the iSCSI Target Host IP address, i.e. the IP
                             address for the nova-volume host
:target_port:                iSCSI Target Port, 3260 Default
:iqn_prefix:                 IQN Prefix, e.g. 'iqn.2010-10.org.openstack'

**Variable Naming Scheme**

- suffix "_ref" for opaque references
- suffix "_uuid" for UUIDs
- suffix "_rec" for record objects
"""

import math
import urlparse

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import unit
from nova import utils
from nova.virt import driver
from nova.virt.xenapi.client import session
from nova.virt.xenapi import host
from nova.virt.xenapi import pool
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volumeops

LOG = logging.getLogger(__name__)

xenapi_opts = [
    cfg.StrOpt('connection_url',
               deprecated_name='xenapi_connection_url',
               deprecated_group='DEFAULT',
               help='URL for connection to XenServer/Xen Cloud Platform. '
                    'A special value of unix://local can be used to connect '
                    'to the local unix socket.  '
                    'Required if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('connection_username',
               default='root',
               deprecated_name='xenapi_connection_username',
               deprecated_group='DEFAULT',
               help='Username for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('connection_password',
               deprecated_name='xenapi_connection_password',
               deprecated_group='DEFAULT',
               help='Password for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver',
               secret=True),
    cfg.FloatOpt('vhd_coalesce_poll_interval',
                 default=5.0,
                 deprecated_name='xenapi_vhd_coalesce_poll_interval',
                 deprecated_group='DEFAULT',
                 help='The interval used for polling of coalescing vhds. '
                      'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.BoolOpt('check_host',
                default=True,
                deprecated_name='xenapi_check_host',
                deprecated_group='DEFAULT',
                help='Ensure compute service is running on host XenAPI '
                     'connects to.'),
    cfg.IntOpt('vhd_coalesce_max_attempts',
               default=5,
               deprecated_name='xenapi_vhd_coalesce_max_attempts',
               deprecated_group='DEFAULT',
               help='Max number of times to poll for VHD to coalesce. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('sr_base_path',
               default='/var/run/sr-mount',
               deprecated_name='xenapi_sr_base_path',
               deprecated_group='DEFAULT',
               help='Base path to the storage repository'),
    cfg.StrOpt('target_host',
               deprecated_name='target_host',
               deprecated_group='DEFAULT',
               help='iSCSI Target Host'),
    cfg.StrOpt('target_port',
               default='3260',
               deprecated_name='target_port',
               deprecated_group='DEFAULT',
               help='iSCSI Target Port, 3260 Default'),
    cfg.StrOpt('iqn_prefix',
               default='iqn.2010-10.org.openstack',
               deprecated_name='iqn_prefix',
               deprecated_group='DEFAULT',
               help='IQN Prefix'),
    # NOTE(sirp): This is a work-around for a bug in Ubuntu Maverick,
    # when we pull support for it, we should remove this
    cfg.BoolOpt('remap_vbd_dev',
                default=False,
                deprecated_name='xenapi_remap_vbd_dev',
                deprecated_group='DEFAULT',
                help='Used to enable the remapping of VBD dev '
                     '(Works around an issue in Ubuntu Maverick)'),
    cfg.StrOpt('remap_vbd_dev_prefix',
               default='sd',
               deprecated_name='xenapi_remap_vbd_dev_prefix',
               deprecated_group='DEFAULT',
               help='Specify prefix to remap VBD dev to '
                    '(ex. /dev/xvdb -> /dev/sdb)'),
    ]

CONF = cfg.CONF
# xenapi options in the DEFAULT group were deprecated in Icehouse
CONF.register_opts(xenapi_opts, 'xenserver')
CONF.import_opt('host', 'nova.netconf')

OVERHEAD_BASE = 3
OVERHEAD_PER_MB = 0.00781
OVERHEAD_PER_VCPU = 1.5


class XenAPIDriver(driver.ComputeDriver):
    """A connection to XenServer or Xen Cloud Platform."""

    def __init__(self, virtapi, read_only=False):
        super(XenAPIDriver, self).__init__(virtapi)

        url = CONF.xenserver.connection_url
        username = CONF.xenserver.connection_username
        password = CONF.xenserver.connection_password
        if not url or password is None:
            raise Exception(_('Must specify connection_url, '
                              'connection_username (optionally), and '
                              'connection_password to use '
                              'compute_driver=xenapi.XenAPIDriver'))

        self._session = session.XenAPISession(url, username, password)
        self._volumeops = volumeops.VolumeOps(self._session)
        self._host_state = None
        self._host = host.Host(self._session, self.virtapi)
        self._vmops = vmops.VMOps(self._session, self.virtapi)
        self._initiator = None
        self._hypervisor_hostname = None
        self._pool = pool.ResourcePool(self._session, self.virtapi)

    @property
    def host_state(self):
        if not self._host_state:
            self._host_state = host.HostState(self._session)
        return self._host_state

    def init_host(self, host):
        if CONF.xenserver.check_host:
            vm_utils.ensure_correct_host(self._session)

        try:
            vm_utils.cleanup_attached_vdis(self._session)
        except Exception:
            LOG.exception(_('Failure while cleaning up attached VDIs'))

    def instance_exists(self, instance_name):
        """Checks existence of an instance on the host.

        :param instance_name: The name of the instance to lookup

        Returns True if an instance with the supplied name exists on
        the host, False otherwise.

        NOTE(belliott): This is an override of the base method for
        efficiency.
        """
        return self._vmops.instance_exists(instance_name)

    def estimate_instance_overhead(self, instance_info):
        """Get virtualization overhead required to build an instance of the
        given flavor.

        :param instance_info: Instance/flavor to calculate overhead for.
        :returns: Overhead memory in MB.
        """

        # XenServer memory overhead is proportional to the size of the
        # VM.  Larger flavor VMs become more efficient with respect to
        # overhead.

        # interpolated formula to predict overhead required per vm.
        # based on data from:
        # https://wiki.openstack.org/wiki/XenServer/Overhead
        # Some padding is done to each value to fit all available VM data
        memory_mb = instance_info['memory_mb']
        vcpus = instance_info.get('vcpus', 1)
        overhead = ((memory_mb * OVERHEAD_PER_MB) + (vcpus * OVERHEAD_PER_VCPU)
                        + OVERHEAD_BASE)
        overhead = math.ceil(overhead)
        return {'memory_mb': overhead}

    def list_instances(self):
        """List VM instances."""
        return self._vmops.list_instances()

    def list_instance_uuids(self):
        """Get the list of nova instance uuids for VMs found on the
        hypervisor.
        """
        return self._vmops.list_instance_uuids()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Create VM instance."""
        self._vmops.spawn(context, instance, image_meta, injected_files,
                          admin_password, network_info, block_device_info)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        # TODO(Vek): Need to pass context in for access to auth_token
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        """Finish reverting a resize."""
        # NOTE(vish): Xen currently does not use network info.
        self._vmops.finish_revert_migration(context, instance,
                                            block_device_info,
                                            power_on)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance."""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance,
                                     block_device_info, power_on)

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance."""
        self._vmops.snapshot(context, instance, image_id, update_task_state)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot VM instance."""
        self._vmops.reboot(instance, reboot_type,
                           bad_volumes_callback=bad_volumes_callback)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance."""
        self._vmops.set_admin_password(instance, new_pass)

    def inject_file(self, instance, b64_path, b64_contents):
        """Create a file on the VM instance. The file path and contents
        should be base64-encoded.
        """
        self._vmops.inject_file(instance, b64_path, b64_contents)

    def change_instance_metadata(self, context, instance, diff):
        """Apply a diff to the instance metadata."""
        self._vmops.change_instance_metadata(instance, diff)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy VM instance."""
        self._vmops.destroy(instance, network_info, block_device_info,
                            destroy_disks)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Cleanup after instance being destroyed by Hypervisor."""
        pass

    def pause(self, instance):
        """Pause VM instance."""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        self._vmops.unpause(instance)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None):
        """Transfers the VHD of a running instance to another host, then shuts
        off the instance copies over the COW disk
        """
        # NOTE(vish): Xen currently does not use network info.
        return self._vmops.migrate_disk_and_power_off(context, instance,
                    dest, flavor, block_device_info)

    def suspend(self, instance):
        """suspend the specified instance."""
        self._vmops.suspend(instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance."""
        self._vmops.rescue(context, instance, network_info, image_meta,
                           rescue_password)

    def set_bootable(self, instance, is_bootable):
        """Set the ability to power on/off an instance."""
        self._vmops.set_bootable(instance, is_bootable)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance."""
        self._vmops.unrescue(instance)

    def power_off(self, instance):
        """Power off the specified instance."""
        self._vmops.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        self._vmops.power_on(instance)

    def soft_delete(self, instance):
        """Soft delete the specified instance."""
        self._vmops.soft_delete(instance)

    def restore(self, instance):
        """Restore the specified instance."""
        self._vmops.restore(instance)

    def poll_rebooting_instances(self, timeout, instances):
        """Poll for rebooting instances."""
        self._vmops.poll_rebooting_instances(timeout, instances)

    def reset_network(self, instance):
        """reset networking for specified instance."""
        self._vmops.reset_network(instance)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance."""
        self._vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance_ref, network_info):
        """Plug VIFs into networks."""
        self._vmops.plug_vifs(instance_ref, network_info)

    def unplug_vifs(self, instance_ref, network_info):
        """Unplug VIFs from networks."""
        self._vmops.unplug_vifs(instance_ref, network_info)

    def get_info(self, instance):
        """Return data about VM instance."""
        return self._vmops.get_info(instance)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        return self._vmops.get_diagnostics(instance)

    def get_all_bw_counters(self, instances):
        """Return bandwidth usage counters for each interface on each
           running VM.
        """

        # we only care about VMs that correspond to a nova-managed
        # instance:
        imap = dict([(inst['name'], inst['uuid']) for inst in instances])
        bwcounters = []

        # get a dictionary of instance names.  values are dictionaries
        # of mac addresses with values that are the bw counters:
        # e.g. {'instance-001' : { 12:34:56:78:90:12 : {'bw_in': 0, ....}}
        all_counters = self._vmops.get_all_bw_counters()
        for instance_name, counters in all_counters.iteritems():
            if instance_name in imap:
                # yes these are stats for a nova-managed vm
                # correlate the stats with the nova instance uuid:
                for vif_counter in counters.values():
                    vif_counter['uuid'] = imap[instance_name]
                    bwcounters.append(vif_counter)
        return bwcounters

    def get_console_output(self, context, instance):
        """Return snapshot of console."""
        return self._vmops.get_console_output(instance)

    def get_vnc_console(self, context, instance):
        """Return link to instance's VNC console."""
        return self._vmops.get_vnc_console(instance)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        if not self._initiator or not self._hypervisor_hostname:
            stats = self.get_host_stats(refresh=True)
            try:
                self._initiator = stats['host_other-config']['iscsi_iqn']
                self._hypervisor_hostname = stats['host_hostname']
            except (TypeError, KeyError) as err:
                LOG.warn(_('Could not determine key: %s') % err,
                         instance=instance)
                self._initiator = None
        return {
            'ip': self.get_host_ip_addr(),
            'initiator': self._initiator,
            'host': self._hypervisor_hostname
        }

    @staticmethod
    def get_host_ip_addr():
        xs_url = urlparse.urlparse(CONF.xenserver.connection_url)
        return xs_url.netloc

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Attach volume storage to VM instance."""
        return self._volumeops.attach_volume(connection_info,
                                             instance['name'],
                                             mountpoint)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach volume storage from VM instance."""
        return self._volumeops.detach_volume(connection_info,
                                             instance['name'],
                                             mountpoint)

    def get_console_pool_info(self, console_type):
        xs_url = urlparse.urlparse(CONF.xenserver.connection_url)
        return {'address': xs_url.netloc,
                'username': CONF.xenserver.connection_username,
                'password': CONF.xenserver.connection_password}

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename: ignored in this driver
        :returns: dictionary describing resources

        """
        host_stats = self.get_host_stats(refresh=True)

        # Updating host information
        total_ram_mb = host_stats['host_memory_total'] / unit.Mi
        # NOTE(belliott) memory-free-computed is a value provided by XenServer
        # for gauging free memory more conservatively than memory-free.
        free_ram_mb = host_stats['host_memory_free_computed'] / unit.Mi
        total_disk_gb = host_stats['disk_total'] / unit.Gi
        used_disk_gb = host_stats['disk_used'] / unit.Gi
        hyper_ver = utils.convert_version_to_int(self._session.product_version)
        dic = {'vcpus': 0,
               'memory_mb': total_ram_mb,
               'local_gb': total_disk_gb,
               'vcpus_used': 0,
               'memory_mb_used': total_ram_mb - free_ram_mb,
               'local_gb_used': used_disk_gb,
               'hypervisor_type': 'xen',
               'hypervisor_version': hyper_ver,
               'hypervisor_hostname': host_stats['host_hostname'],
               'cpu_info': host_stats['host_cpu_info']['cpu_count'],
               'supported_instances': jsonutils.dumps(
                   host_stats['supported_instances'])}

        return dic

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        # NOTE(salvatore-orlando): it enforces security groups on
        # host initialization and live migration.
        # In XenAPI we do not assume instances running upon host initialization
        return

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                src_compute_info, dst_compute_info,
                block_migration=False, disk_over_commit=False):
        """Check if it is possible to execute live migration.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit

        """
        return self._vmops.check_can_live_migrate_destination(ctxt,
                                                              instance_ref,
                                                              block_migration,
                                                              disk_over_commit)

    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param ctxt: security context
        :param disk_over_commit: if true, allow disk over commit
        """
        pass

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
                                includes the block_migration flag
        """
        return self._vmops.check_can_live_migrate_source(ctxt, instance_ref,
                                                         dest_check_data)

    def get_instance_disk_info(self, instance_name):
        """Used by libvirt for live migration. We rely on xenapi
        checks to do this for us.
        """
        pass

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Performs the live migration of the specified instance.

        :param ctxt: security context
        :param instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param dest: destination host
        :param post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :param recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.
        :param block_migration: if true, migrate VM disk.
        :param migrate_data: implementation specific params
        """
        self._vmops.live_migrate(ctxt, instance_ref, dest, post_method,
                                 recover_method, block_migration, migrate_data)

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info):
        # NOTE(johngarbutt) Destroying the VM is not appropriate here
        # and in the cases where it might make sense,
        # XenServer has already done it.
        # TODO(johngarbutt) investigate if any cleanup is required here
        pass

    def pre_live_migration(self, context, instance_ref, block_device_info,
                           network_info, data, migrate_data=None):
        """Preparation live migration.

        :param block_device_info:
            It must be the result of _get_instance_volume_bdms()
            at compute manager.
        """
        # TODO(JohnGarbutt) look again when boot-from-volume hits trunk
        pre_live_migration_result = {}
        pre_live_migration_result['sr_uuid_map'] = \
                 self._vmops.attach_block_device_volumes(block_device_info)
        return pre_live_migration_result

    def post_live_migration(self, ctxt, instance_ref, block_device_info,
                            migrate_data=None):
        """Post operation of live migration at source host.

        :param ctxt: security context
        :instance_ref: instance object that was migrated
        :block_device_info: instance block device information
        :param migrate_data: if not None, it is a dict which has data
        """
        self._vmops.post_live_migration(ctxt, instance_ref, migrate_data)

    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info, block_migration,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :param ctxt: security context
        :param instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param network_info: instance network information
        :param : block_migration: if true, post operation of block_migration.
        """
        self._vmops.post_live_migration_at_destination(ctxt, instance_ref,
                network_info, block_device_info, block_device_info)

    def unfilter_instance(self, instance_ref, network_info):
        """Removes security groups configured for an instance."""
        return self._vmops.unfilter_instance(instance_ref, network_info)

    def refresh_security_group_rules(self, security_group_id):
        """Updates security group rules for all instances associated with a
        given security group.

        Invoked when security group rules are updated.
        """
        return self._vmops.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        """Updates security group rules for all instances associated with a
        given security group.

        Invoked when instances are added/removed to a security group.
        """
        return self._vmops.refresh_security_group_members(security_group_id)

    def refresh_instance_security_rules(self, instance):
        """Updates security group rules for specified instance.

        Invoked when instances are added/removed to a security group
        or when a rule is added/removed to a security group.
        """
        return self._vmops.refresh_instance_security_rules(instance)

    def refresh_provider_fw_rules(self):
        return self._vmops.refresh_provider_fw_rules()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host.

           If 'refresh' is True, run the update first.
         """
        return self.host_state.get_host_stats(refresh=refresh)

    def host_power_action(self, host, action):
        """The only valid values for 'action' on XenServer are 'reboot' or
        'shutdown', even though the API also accepts 'startup'. As this is
        not technically possible on XenServer, since the host is the same
        physical machine as the hypervisor, if this is requested, we need to
        raise an exception.
        """
        if action in ("reboot", "shutdown"):
            return self._host.host_power_action(host, action)
        else:
            msg = _("Host startup on XenServer is not supported.")
            raise NotImplementedError(msg)

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self._host.set_host_enabled(host, enabled)

    def get_host_uptime(self, host):
        """Returns the result of calling "uptime" on the target host."""
        return self._host.get_host_uptime(host)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        return self._host.host_maintenance_mode(host, mode)

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        """Add a compute host to an aggregate."""
        return self._pool.add_to_aggregate(context, aggregate, host, **kwargs)

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        """Remove a compute host from an aggregate."""
        return self._pool.remove_from_aggregate(context,
                                                aggregate, host, **kwargs)

    def undo_aggregate_operation(self, context, op, aggregate,
                                  host, set_error=True):
        """Undo aggregate operation when pool error raised."""
        return self._pool.undo_aggregate_operation(context, op,
                aggregate, host, set_error)

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        self._vmops.power_on(instance)

    def get_per_instance_usage(self):
        """Get information about instance resource usage.

        :returns: dict of  nova uuid => dict of usage
        info
        """
        return self._vmops.get_per_instance_usage()
