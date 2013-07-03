# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

:xenapi_connection_url:  URL for connection to XenServer/Xen Cloud Platform.
:xenapi_connection_username:  Username for connection to XenServer/Xen Cloud
                              Platform (default: root).
:xenapi_connection_password:  Password for connection to XenServer/Xen Cloud
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

import contextlib
import cPickle as pickle
import urlparse
import xmlrpclib

from eventlet import queue
from eventlet import timeout
from oslo.config import cfg

from nova import context
from nova import exception
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.xenapi import host
from nova.virt.xenapi import pool
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volumeops

LOG = logging.getLogger(__name__)

xenapi_opts = [
    cfg.StrOpt('xenapi_connection_url',
               default=None,
               help='URL for connection to XenServer/Xen Cloud Platform. '
                    'Required if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('xenapi_connection_username',
               default='root',
               help='Username for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('xenapi_connection_password',
               default=None,
               help='Password for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver',
               secret=True),
    cfg.IntOpt('xenapi_connection_concurrent',
               default=5,
               help='Maximum number of concurrent XenAPI connections. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.FloatOpt('xenapi_vhd_coalesce_poll_interval',
                 default=5.0,
                 help='The interval used for polling of coalescing vhds. '
                      'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.BoolOpt('xenapi_check_host',
                default=True,
                help='Ensure compute service is running on host XenAPI '
                     'connects to.'),
    cfg.IntOpt('xenapi_vhd_coalesce_max_attempts',
               default=5,
               help='Max number of times to poll for VHD to coalesce. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('xenapi_sr_base_path',
               default='/var/run/sr-mount',
               help='Base path to the storage repository'),
    cfg.StrOpt('target_host',
               default=None,
               help='iSCSI Target Host'),
    cfg.StrOpt('target_port',
               default='3260',
               help='iSCSI Target Port, 3260 Default'),
    cfg.StrOpt('iqn_prefix',
               default='iqn.2010-10.org.openstack',
               help='IQN Prefix'),
    # NOTE(sirp): This is a work-around for a bug in Ubuntu Maverick,
    # when we pull support for it, we should remove this
    cfg.BoolOpt('xenapi_remap_vbd_dev',
                default=False,
                help='Used to enable the remapping of VBD dev '
                     '(Works around an issue in Ubuntu Maverick)'),
    cfg.StrOpt('xenapi_remap_vbd_dev_prefix',
               default='sd',
               help='Specify prefix to remap VBD dev to '
                    '(ex. /dev/xvdb -> /dev/sdb)'),
    cfg.IntOpt('xenapi_login_timeout',
               default=10,
               help='Timeout in seconds for XenAPI login.'),
    ]

CONF = cfg.CONF
CONF.register_opts(xenapi_opts)
CONF.import_opt('host', 'nova.netconf')


class XenAPIDriver(driver.ComputeDriver):
    """A connection to XenServer or Xen Cloud Platform."""

    def __init__(self, virtapi, read_only=False):
        super(XenAPIDriver, self).__init__(virtapi)

        url = CONF.xenapi_connection_url
        username = CONF.xenapi_connection_username
        password = CONF.xenapi_connection_password
        if not url or password is None:
            raise Exception(_('Must specify xenapi_connection_url, '
                              'xenapi_connection_username (optionally), and '
                              'xenapi_connection_password to use '
                              'compute_driver=xenapi.XenAPIDriver'))

        self._session = XenAPISession(url, username, password, self.virtapi)
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
        if CONF.xenapi_check_host:
            vm_utils.ensure_correct_host(self._session)

        try:
            vm_utils.cleanup_attached_vdis(self._session)
        except Exception:
            LOG.exception(_('Failure while cleaning up attached VDIs'))

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

    def finish_revert_migration(self, instance, network_info,
                                block_device_info=None):
        """Finish reverting a resize, powering back on the instance."""
        # NOTE(vish): Xen currently does not use network info.
        self._vmops.finish_revert_migration(instance, block_device_info)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None):
        """Completes a resize, turning on the migrated instance."""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance,
                                     block_device_info)

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

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy VM instance."""
        self._vmops.destroy(instance, network_info, block_device_info,
                            destroy_disks)

    def pause(self, instance):
        """Pause VM instance."""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        self._vmops.unpause(instance)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info,
                                   block_device_info=None):
        """Transfers the VHD of a running instance to another host, then shuts
        off the instance copies over the COW disk"""
        # NOTE(vish): Xen currently does not use network info.
        rv = self._vmops.migrate_disk_and_power_off(context, instance,
                                                    dest, instance_type)
        block_device_mapping = driver.block_device_info_get_mapping(
                block_device_info)
        name_label = self._vmops._get_orig_vm_name_label(instance)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            mount_device = vol['mount_device'].rpartition("/")[2]
            self._volumeops.detach_volume(connection_info,
                    name_label, mount_device)
        return rv

    def suspend(self, instance):
        """suspend the specified instance."""
        self._vmops.suspend(instance)

    def resume(self, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue the specified instance."""
        self._vmops.rescue(context, instance, network_info, image_meta,
                           rescue_password)

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
           running VM"""

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

    def get_console_output(self, instance):
        """Return snapshot of console."""
        return self._vmops.get_console_output(instance)

    def get_vnc_console(self, instance):
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
        xs_url = urlparse.urlparse(CONF.xenapi_connection_url)
        return xs_url.netloc

    def attach_volume(self, connection_info, instance, mountpoint):
        """Attach volume storage to VM instance."""
        return self._volumeops.attach_volume(connection_info,
                                             instance['name'],
                                             mountpoint)

    def detach_volume(self, connection_info, instance, mountpoint):
        """Detach volume storage to VM instance."""
        return self._volumeops.detach_volume(connection_info,
                                             instance['name'],
                                             mountpoint)

    def get_console_pool_info(self, console_type):
        xs_url = urlparse.urlparse(CONF.xenapi_connection_url)
        return {'address': xs_url.netloc,
                'username': CONF.xenapi_connection_username,
                'password': CONF.xenapi_connection_password}

    def get_available_resource(self, nodename):
        """Retrieve resource info.

        This method is called when nova-compute launches, and
        as part of a periodic task.

        :param nodename: ignored in this driver
        :returns: dictionary describing resources

        """
        host_stats = self.get_host_stats(refresh=True)

        # Updating host information
        total_ram_mb = host_stats['host_memory_total'] / (1024 * 1024)
        # NOTE(belliott) memory-free-computed is a value provided by XenServer
        # for gauging free memory more conservatively than memory-free.
        free_ram_mb = host_stats['host_memory_free_computed'] / (1024 * 1024)
        total_disk_gb = host_stats['disk_total'] / (1024 * 1024 * 1024)
        used_disk_gb = host_stats['disk_used'] / (1024 * 1024 * 1024)

        dic = {'vcpus': 0,
               'memory_mb': total_ram_mb,
               'local_gb': total_disk_gb,
               'vcpus_used': 0,
               'memory_mb_used': total_ram_mb - free_ram_mb,
               'local_gb_used': used_disk_gb,
               'hypervisor_type': 'xen',
               'hypervisor_version': 0,
               'hypervisor_hostname': host_stats['host_hostname'],
               'cpu_info': host_stats['host_cpu_info']['cpu_count']}

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
        checks to do this for us."""
        pass

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Performs the live migration of the specified instance.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.
        :params block_migration: if true, migrate VM disk.
        :params migrate_data: implementation specific params
        """
        self._vmops.live_migrate(ctxt, instance_ref, dest, post_method,
                                 recover_method, block_migration, migrate_data)

    def pre_live_migration(self, context, instance_ref, block_device_info,
                           network_info, data, migrate_data=None):
        """Preparation live migration.

        :params block_device_info:
            It must be the result of _get_instance_volume_bdms()
            at compute manager.
        """
        # TODO(JohnGarbutt) look again when boot-from-volume hits trunk
        pass

    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info, block_migration,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params network_info: instance network information
        :params : block_migration: if true, post operation of block_migraiton.
        """
        # TODO(JohnGarbutt) look at moving/downloading ramdisk and kernel
        pass

    def unfilter_instance(self, instance_ref, network_info):
        """Removes security groups configured for an instance."""
        return self._vmops.unfilter_instance(instance_ref, network_info)

    def refresh_security_group_rules(self, security_group_id):
        """Updates security group rules for all instances associated with a
        given security group.

        Invoked when security group rules are updated."""
        return self._vmops.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        """Updates security group rules for all instances associated with a
        given security group.

        Invoked when instances are added/removed to a security group."""
        return self._vmops.refresh_security_group_members(security_group_id)

    def refresh_instance_security_rules(self, instance):
        """Updates security group rules for specified instance.

        Invoked when instances are added/removed to a security group
        or when a rule is added/removed to a security group."""
        return self._vmops.refresh_instance_security_rules(instance)

    def refresh_provider_fw_rules(self):
        return self._vmops.refresh_provider_fw_rules()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
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
        guest VMs evacuation."""
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

    def legacy_nwinfo(self):
        """
        Indicate if the driver requires the legacy network_info format.
        """
        # TODO(tr3buchet): remove this function once all virts return false
        return False

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


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls."""

    def __init__(self, url, user, pw, virtapi):
        import XenAPI
        self.XenAPI = XenAPI
        self._sessions = queue.Queue()
        self.is_slave = False
        exception = self.XenAPI.Failure(_("Unable to log in to XenAPI "
                                          "(is the Dom0 disk full?)"))
        url = self._create_first_session(url, user, pw, exception)
        self._populate_session_pool(url, user, pw, exception)
        self.host_uuid = self._get_host_uuid()
        self.product_version, self.product_brand = \
            self._get_product_version_and_brand()
        self._virtapi = virtapi

    def _create_first_session(self, url, user, pw, exception):
        try:
            session = self._create_session(url)
            with timeout.Timeout(CONF.xenapi_login_timeout, exception):
                session.login_with_password(user, pw)
        except self.XenAPI.Failure, e:
            # if user and pw of the master are different, we're doomed!
            if e.details[0] == 'HOST_IS_SLAVE':
                master = e.details[1]
                url = pool.swap_xapi_host(url, master)
                session = self.XenAPI.Session(url)
                session.login_with_password(user, pw)
                self.is_slave = True
            else:
                raise
        self._sessions.put(session)
        return url

    def _populate_session_pool(self, url, user, pw, exception):
        for i in xrange(CONF.xenapi_connection_concurrent - 1):
            session = self._create_session(url)
            with timeout.Timeout(CONF.xenapi_login_timeout, exception):
                session.login_with_password(user, pw)
            self._sessions.put(session)

    def _get_host_uuid(self):
        if self.is_slave:
            aggr = self._virtapi.aggregate_get_by_host(
                context.get_admin_context(),
                CONF.host, key=pool_states.POOL_FLAG)[0]
            if not aggr:
                LOG.error(_('Host is member of a pool, but DB '
                                'says otherwise'))
                raise exception.AggregateHostNotFound()
            return aggr.metadetails[CONF.host]
        else:
            with self._get_session() as session:
                host_ref = session.xenapi.session.get_this_host(session.handle)
                return session.xenapi.host.get_uuid(host_ref)

    def _get_product_version_and_brand(self):
        """Return a tuple of (major, minor, rev) for the host version and
        a string of the product brand"""
        software_version = self._get_software_version()

        product_version_str = software_version.get('product_version')
        product_brand = software_version.get('product_brand')

        if None in (product_version_str, product_brand):
            return (None, None)

        product_version = tuple(int(part) for part in
                                product_version_str.split('.'))

        return product_version, product_brand

    def _get_software_version(self):
        host = self.get_xenapi_host()
        return self.call_xenapi('host.get_software_version', host)

    def get_session_id(self):
        """Return a string session_id.  Used for vnc consoles."""
        with self._get_session() as session:
            return str(session._session)

    @contextlib.contextmanager
    def _get_session(self):
        """Return exclusive session for scope of with statement."""
        session = self._sessions.get()
        try:
            yield session
        finally:
            self._sessions.put(session)

    def get_xenapi_host(self):
        """Return the xenapi host on which nova-compute runs on."""
        with self._get_session() as session:
            return session.xenapi.host.get_by_uuid(self.host_uuid)

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread."""
        with self._get_session() as session:
            return session.xenapi_request(method, args)

    def call_plugin(self, plugin, fn, args):
        """Call host.call_plugin on a background thread."""
        # NOTE(johannes): Fetch host before we acquire a session. Since
        # get_xenapi_host() acquires a session too, it can result in a
        # deadlock if multiple greenthreads race with each other. See
        # bug 924918
        host = self.get_xenapi_host()

        # NOTE(armando): pass the host uuid along with the args so that
        # the plugin gets executed on the right host when using XS pools
        args['host_uuid'] = self.host_uuid

        with self._get_session() as session:
            return self._unwrap_plugin_exceptions(
                                 session.xenapi.host.call_plugin,
                                 host, plugin, fn, args)

    def call_plugin_serialized(self, plugin, fn, *args, **kwargs):
        params = {'params': pickle.dumps(dict(args=args, kwargs=kwargs))}
        rv = self.call_plugin(plugin, fn, params)
        return pickle.loads(rv)

    def _create_session(self, url):
        """Stubout point. This can be replaced with a mock session."""
        return self.XenAPI.Session(url)

    def _unwrap_plugin_exceptions(self, func, *args, **kwargs):
        """Parse exception details."""
        try:
            return func(*args, **kwargs)
        except self.XenAPI.Failure, exc:
            LOG.debug(_("Got exception: %s"), exc)
            if (len(exc.details) == 4 and
                exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
                exc.details[2] == 'Failure'):
                params = None
                try:
                    # FIXME(comstud): eval is evil.
                    params = eval(exc.details[3])
                except Exception:
                    raise exc
                raise self.XenAPI.Failure(params)
            else:
                raise
        except xmlrpclib.ProtocolError, exc:
            LOG.debug(_("Got exception: %s"), exc)
            raise

    def get_rec(self, record_type, ref):
        try:
            return self.call_xenapi('%s.get_record' % record_type, ref)
        except self.XenAPI.Failure, e:
            if e.details[0] != 'HANDLE_INVALID':
                raise

        return None

    def get_all_refs_and_recs(self, record_type):
        """Retrieve all refs and recs for a Xen record type.

        Handles race-conditions where the record may be deleted between
        the `get_all` call and the `get_record` call.
        """

        for ref in self.call_xenapi('%s.get_all' % record_type):
            rec = self.get_rec(record_type, ref)
            # Check to make sure the record still exists. It may have
            # been deleted between the get_all call and get_record call
            if rec:
                yield ref, rec
