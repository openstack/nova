# Copyright 2013 Red Hat, Inc.
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
Client side of the compute RPC API.
"""

from oslo_concurrency import lockutils
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import excutils

import nova.conf
from nova import context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as objects_base
from nova.objects import service as service_obj
from nova import profiler
from nova import rpc

CONF = nova.conf.CONF
RPC_TOPIC = "compute"

LOG = logging.getLogger(__name__)
LAST_VERSION = None
NO_COMPUTES_WARNING = False
# Global for ComputeAPI.router.
_ROUTER = None


def reset_globals():
    global NO_COMPUTES_WARNING
    global LAST_VERSION
    global _ROUTER

    NO_COMPUTES_WARNING = False
    LAST_VERSION = None
    _ROUTER = None


def _compute_host(host, instance):
    '''Get the destination host for a message.

    :param host: explicit host to send the message to.
    :param instance: If an explicit host was not specified, use
                     instance['host']

    :returns: A host
    '''
    if host:
        return host
    if not instance:
        raise exception.NovaException(_('No compute host specified'))
    if not instance.host:
        raise exception.NovaException(_('Unable to find host for '
                                        'Instance %s') % instance.uuid)
    return instance.host


@profiler.trace_cls("rpc")
class ComputeAPI(object):
    '''Client side of the compute rpc API.

    API version history:

        * 1.0 - Initial version.
        * 1.1 - Adds get_host_uptime()
        * 1.2 - Adds check_can_live_migrate_[destination|source]
        * 1.3 - Adds change_instance_metadata()
        * 1.4 - Remove instance_uuid, add instance argument to
                reboot_instance()
        * 1.5 - Remove instance_uuid, add instance argument to
                pause_instance(), unpause_instance()
        * 1.6 - Remove instance_uuid, add instance argument to
                suspend_instance()
        * 1.7 - Remove instance_uuid, add instance argument to
                get_console_output()
        * 1.8 - Remove instance_uuid, add instance argument to
                add_fixed_ip_to_instance()
        * 1.9 - Remove instance_uuid, add instance argument to attach_volume()
        * 1.10 - Remove instance_id, add instance argument to
                 check_can_live_migrate_destination()
        * 1.11 - Remove instance_id, add instance argument to
                 check_can_live_migrate_source()
        * 1.12 - Remove instance_uuid, add instance argument to
                 confirm_resize()
        * 1.13 - Remove instance_uuid, add instance argument to detach_volume()
        * 1.14 - Remove instance_uuid, add instance argument to finish_resize()
        * 1.15 - Remove instance_uuid, add instance argument to
                 finish_revert_resize()
        * 1.16 - Remove instance_uuid, add instance argument to
                 get_diagnostics()
        * 1.17 - Remove instance_uuid, add instance argument to
                 get_vnc_console()
        * 1.18 - Remove instance_uuid, add instance argument to inject_file()
        * 1.19 - Remove instance_uuid, add instance argument to
                 inject_network_info()
        * 1.20 - Remove instance_id, add instance argument to
                 post_live_migration_at_destination()
        * 1.21 - Remove instance_uuid, add instance argument to
                 power_off_instance() and stop_instance()
        * 1.22 - Remove instance_uuid, add instance argument to
                 power_on_instance() and start_instance()
        * 1.23 - Remove instance_id, add instance argument to
                 pre_live_migration()
        * 1.24 - Remove instance_uuid, add instance argument to
                 rebuild_instance()
        * 1.25 - Remove instance_uuid, add instance argument to
                 remove_fixed_ip_from_instance()
        * 1.26 - Remove instance_id, add instance argument to
                 remove_volume_connection()
        * 1.27 - Remove instance_uuid, add instance argument to
                 rescue_instance()
        * 1.28 - Remove instance_uuid, add instance argument to reset_network()
        * 1.29 - Remove instance_uuid, add instance argument to
                 resize_instance()
        * 1.30 - Remove instance_uuid, add instance argument to
                 resume_instance()
        * 1.31 - Remove instance_uuid, add instance argument to revert_resize()
        * 1.32 - Remove instance_id, add instance argument to
                 rollback_live_migration_at_destination()
        * 1.33 - Remove instance_uuid, add instance argument to
                 set_admin_password()
        * 1.34 - Remove instance_uuid, add instance argument to
                 snapshot_instance()
        * 1.35 - Remove instance_uuid, add instance argument to
                 unrescue_instance()
        * 1.36 - Remove instance_uuid, add instance argument to
                 change_instance_metadata()
        * 1.37 - Remove instance_uuid, add instance argument to
                 terminate_instance()
        * 1.38 - Changes to prep_resize():
            * remove instance_uuid, add instance
            * remove instance_type_id, add instance_type
            * remove topic, it was unused
        * 1.39 - Remove instance_uuid, add instance argument to run_instance()
        * 1.40 - Remove instance_id, add instance argument to live_migration()
        * 1.41 - Adds refresh_instance_security_rules()
        * 1.42 - Add reservations arg to prep_resize(), resize_instance(),
                 finish_resize(), confirm_resize(), revert_resize() and
                 finish_revert_resize()
        * 1.43 - Add migrate_data to live_migration()
        * 1.44 - Adds reserve_block_device_name()

        * 2.0 - Remove 1.x backwards compat
        * 2.1 - Adds orig_sys_metadata to rebuild_instance()
        * 2.2 - Adds slave_info parameter to add_aggregate_host() and
                remove_aggregate_host()
        * 2.3 - Adds volume_id to reserve_block_device_name()
        * 2.4 - Add bdms to terminate_instance
        * 2.5 - Add block device and network info to reboot_instance
        * 2.6 - Remove migration_id, add migration to resize_instance
        * 2.7 - Remove migration_id, add migration to confirm_resize
        * 2.8 - Remove migration_id, add migration to finish_resize
        * 2.9 - Add publish_service_capabilities()
        * 2.10 - Adds filter_properties and request_spec to prep_resize()
        * 2.11 - Adds soft_delete_instance() and restore_instance()
        * 2.12 - Remove migration_id, add migration to revert_resize
        * 2.13 - Remove migration_id, add migration to finish_revert_resize
        * 2.14 - Remove aggregate_id, add aggregate to add_aggregate_host
        * 2.15 - Remove aggregate_id, add aggregate to remove_aggregate_host
        * 2.16 - Add instance_type to resize_instance
        * 2.17 - Add get_backdoor_port()
        * 2.18 - Add bdms to rebuild_instance
        * 2.19 - Add node to run_instance
        * 2.20 - Add node to prep_resize
        * 2.21 - Add migrate_data dict param to pre_live_migration()
        * 2.22 - Add recreate, on_shared_storage and host arguments to
                 rebuild_instance()
        * 2.23 - Remove network_info from reboot_instance
        * 2.24 - Added get_spice_console method
        * 2.25 - Add attach_interface() and detach_interface()
        * 2.26 - Add validate_console_port to ensure the service connects to
                 vnc on the correct port
        * 2.27 - Adds 'reservations' to terminate_instance() and
                 soft_delete_instance()

        ... Grizzly supports message version 2.27.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 2.27.

        * 2.28 - Adds check_instance_shared_storage()
        * 2.29 - Made start_instance() and stop_instance() take new-world
                 instance objects
        * 2.30 - Adds live_snapshot_instance()
        * 2.31 - Adds shelve_instance(), shelve_offload_instance, and
                 unshelve_instance()
        * 2.32 - Make reboot_instance take a new world instance object
        * 2.33 - Made suspend_instance() and resume_instance() take new-world
                 instance objects
        * 2.34 - Added swap_volume()
        * 2.35 - Made terminate_instance() and soft_delete_instance() take
                 new-world instance objects
        * 2.36 - Made pause_instance() and unpause_instance() take new-world
                 instance objects
        * 2.37 - Added the legacy_bdm_in_spec parameter to run_instance
        * 2.38 - Made check_can_live_migrate_[destination|source] take
                 new-world instance objects
        * 2.39 - Made revert_resize() and confirm_resize() take new-world
                 instance objects
        * 2.40 - Made reset_network() take new-world instance object
        * 2.41 - Make inject_network_info take new-world instance object
        * 2.42 - Splits snapshot_instance() into snapshot_instance() and
                 backup_instance() and makes them take new-world instance
                 objects.
        * 2.43 - Made prep_resize() take new-world instance object
        * 2.44 - Add volume_snapshot_create(), volume_snapshot_delete()
        * 2.45 - Made resize_instance() take new-world objects
        * 2.46 - Made finish_resize() take new-world objects
        * 2.47 - Made finish_revert_resize() take new-world objects

        ... Havana supports message version 2.47.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 2.47.

        * 2.48 - Make add_aggregate_host() and remove_aggregate_host() take
          new-world objects
        * ... - Remove live_snapshot() that was never actually used

        * 3.0 - Remove 2.x compatibility
        * 3.1 - Update get_spice_console() to take an instance object
        * 3.2 - Update get_vnc_console() to take an instance object
        * 3.3 - Update validate_console_port() to take an instance object
        * 3.4 - Update rebuild_instance() to take an instance object
        * 3.5 - Pass preserve_ephemeral flag to rebuild_instance()
        * 3.6 - Make volume_snapshot_{create,delete} use new-world objects
        * 3.7 - Update change_instance_metadata() to take an instance object
        * 3.8 - Update set_admin_password() to take an instance object
        * 3.9 - Update rescue_instance() to take an instance object
        * 3.10 - Added get_rdp_console method
        * 3.11 - Update unrescue_instance() to take an object
        * 3.12 - Update add_fixed_ip_to_instance() to take an object
        * 3.13 - Update remove_fixed_ip_from_instance() to take an object
        * 3.14 - Update post_live_migration_at_destination() to take an object
        * 3.15 - Adds filter_properties and node to unshelve_instance()
        * 3.16 - Make reserve_block_device_name and attach_volume use new-world
                 objects, and add disk_bus and device_type params to
                 reserve_block_device_name, and bdm param to attach_volume
        * 3.17 - Update attach_interface and detach_interface to take an object
        * 3.18 - Update get_diagnostics() to take an instance object
            * Removed inject_file(), as it was unused.
        * 3.19 - Update pre_live_migration to take instance object
        * 3.20 - Make restore_instance take an instance object
        * 3.21 - Made rebuild take new-world BDM objects
        * 3.22 - Made terminate_instance take new-world BDM objects
        * 3.23 - Added external_instance_event()
            * build_and_run_instance was added in Havana and not used or
              documented.

        ... Icehouse supports message version 3.23.  So, any changes to
        existing methods in 3.x after that point should be done such that they
        can handle the version_cap being set to 3.23.

        * 3.24 - Update rescue_instance() to take optional rescue_image_ref
        * 3.25 - Make detach_volume take an object
        * 3.26 - Make live_migration() and
          rollback_live_migration_at_destination() take an object
        * ... Removed run_instance()
        * 3.27 - Make run_instance() accept a new-world object
        * 3.28 - Update get_console_output() to accept a new-world object
        * 3.29 - Make check_instance_shared_storage accept a new-world object
        * 3.30 - Make remove_volume_connection() accept a new-world object
        * 3.31 - Add get_instance_diagnostics
        * 3.32 - Add destroy_disks and migrate_data optional parameters to
                 rollback_live_migration_at_destination()
        * 3.33 - Make build_and_run_instance() take a NetworkRequestList object
        * 3.34 - Add get_serial_console method
        * 3.35 - Make reserve_block_device_name return a BDM object

        ... Juno supports message version 3.35.  So, any changes to
        existing methods in 3.x after that point should be done such that they
        can handle the version_cap being set to 3.35.

        * 3.36 - Make build_and_run_instance() send a Flavor object
        * 3.37 - Add clean_shutdown to stop, resize, rescue, shelve, and
                 shelve_offload
        * 3.38 - Add clean_shutdown to prep_resize
        * 3.39 - Add quiesce_instance and unquiesce_instance methods
        * 3.40 - Make build_and_run_instance() take a new-world topology
                 limits object

        ... Kilo supports messaging version 3.40. So, any changes to
        existing methods in 3.x after that point should be done so that they
        can handle the version_cap being set to 3.40

        ... Version 4.0 is equivalent to 3.40. Kilo sends version 4.0 by
        default, can accept 3.x calls from Juno nodes, and can be pinned to
        3.x for Juno compatibility. All new changes should go against 4.x.

        * 4.0  - Remove 3.x compatibility
        * 4.1  - Make prep_resize() and resize_instance() send Flavor object
        * 4.2  - Add migration argument to live_migration()
        * 4.3  - Added get_mks_console method
        * 4.4  - Make refresh_instance_security_rules send an instance object
        * 4.5  - Add migration, scheduler_node and limits arguments to
                 rebuild_instance()

        ... Liberty supports messaging version 4.5. So, any changes to
        existing methods in 4.x after that point should be done so that they
        can handle the version_cap being set to 4.5

        * ...  - Remove refresh_security_group_members()
        * ...  - Remove refresh_security_group_rules()
        * 4.6  - Add trigger_crash_dump()
        * 4.7  - Add attachment_id argument to detach_volume()
        * 4.8  - Send migrate_data in object format for live_migration,
                 rollback_live_migration_at_destination, and
                 pre_live_migration.
        * ...  - Remove refresh_provider_fw_rules()
        * 4.9  - Add live_migration_force_complete()
        * 4.10  - Add live_migration_abort()
        * 4.11 - Allow block_migration and disk_over_commit be None

        ... Mitaka supports messaging version 4.11. So, any changes to
        existing methods in 4.x after that point should be done so that they
        can handle the version_cap being set to 4.11

        * 4.12 - Remove migration_id from live_migration_force_complete
        * 4.13 - Make get_instance_diagnostics send an instance object

        ... Newton and Ocata support messaging version 4.13. So, any changes to
        existing methods in 4.x after that point should be done so that they
        can handle the version_cap being set to 4.13

        * 4.14 - Make get_instance_diagnostics return a diagnostics object
                 instead of dictionary. Strictly speaking we don't need to bump
                 the version because this method was unused before. The version
                 was bumped to signal the availability of the corrected RPC API
        * 4.15 - Add tag argument to reserve_block_device_name()
        * 4.16 - Add tag argument to attach_interface()
        * 4.17 - Add new_attachment_id to swap_volume.

        ... Pike supports messaging version 4.17. So any changes to existing
        methods in 4.x after that point should be done so that they can handle
        the version_cap being set to 4.17.

        * 4.18 - Add migration to prep_resize()
        * 4.19 - build_and_run_instance() now gets a 'host_list' parameter
                 representing potential alternate hosts for retries within a
                 cell.
        * 4.20 - Add multiattach argument to reserve_block_device_name().
        * 4.21 - prep_resize() now gets a 'host_list' parameter representing
                 potential alternate hosts for retries within a cell.
        * 4.22 - Add request_spec to rebuild_instance()

        ... Version 5.0 is functionally equivalent to 4.22, aside from
        removing deprecated parameters. Queens sends 5.0 by default,
        can accept 4.x calls from Pike nodes, and can be pinned to 4.x
        for Pike compatibility. All new changes should go against 5.x.

        * 5.0 - Remove 4.x compatibility
        * 5.1 - Make prep_resize() take a RequestSpec object rather than a
                legacy dict.
        * 5.2 - Add request_spec parameter for the following: resize_instance,
                finish_resize, revert_resize, finish_revert_resize,
                unshelve_instance
        * 5.3 - Add migration and limits parameters to
                check_can_live_migrate_destination(), and a new
                drop_move_claim_at_destination() method
        * 5.4 - Add cache_images() support
        * 5.5 - Add prep_snapshot_based_resize_at_dest()
        * 5.6 - Add prep_snapshot_based_resize_at_source()
        * 5.7 - Add finish_snapshot_based_resize_at_dest()
        * 5.8 - Add confirm_snapshot_based_resize_at_source()
        * 5.9 - Add revert_snapshot_based_resize_at_dest()
        * 5.10 - Add finish_revert_snapshot_based_resize_at_source()
        * 5.11 - Add accel_uuids (accelerator requests) parameter to
                 build_and_run_instance()
    '''

    VERSION_ALIASES = {
        'icehouse': '3.23',
        'juno': '3.35',
        'kilo': '4.0',
        'liberty': '4.5',
        'mitaka': '4.11',
        'newton': '4.13',
        'ocata': '4.13',
        'pike': '4.17',
        'queens': '5.0',
        'rocky': '5.0',
        'stein': '5.1',
        'train': '5.3',
        'ussuri': '5.11',
    }

    @property
    def router(self):
        """Provides singleton access to nova.rpc.ClientRouter for this API

        The ClientRouter is constructed and accessed as a singleton to avoid
        querying all cells for a minimum nova-compute service version when
        [upgrade_levels]/compute=auto and we have access to the API DB.
        """
        global _ROUTER
        if _ROUTER is None:
            with lockutils.lock('compute-rpcapi-router'):
                if _ROUTER is None:
                    target = messaging.Target(topic=RPC_TOPIC, version='5.0')
                    upgrade_level = CONF.upgrade_levels.compute
                    if upgrade_level == 'auto':
                        version_cap = self._determine_version_cap(target)
                    else:
                        version_cap = self.VERSION_ALIASES.get(upgrade_level,
                                                               upgrade_level)
                    serializer = objects_base.NovaObjectSerializer()

                    # NOTE(danms): We need to poke this path to register CONF
                    # options that we use in self.get_client()
                    rpc.get_client(target, version_cap, serializer)

                    default_client = self.get_client(target, version_cap,
                                                     serializer)
                    _ROUTER = rpc.ClientRouter(default_client)
        return _ROUTER

    @staticmethod
    def _determine_version_cap(target):
        global LAST_VERSION
        global NO_COMPUTES_WARNING
        if LAST_VERSION:
            return LAST_VERSION

        # NOTE(danms): If we have a connection to the api database,
        # we should iterate all cells. If not, we must only look locally.
        if CONF.api_database.connection:
            try:
                service_version = service_obj.get_minimum_version_all_cells(
                    context.get_admin_context(), ['nova-compute'])
            except exception.DBNotAllowed:
                # This most likely means we are in a nova-compute service
                # configured with [upgrade_levels]/compute=auto and a
                # connection to the API database. We should not be attempting
                # to "get out" of our cell to look at the minimum versions of
                # nova-compute services in other cells, so DBNotAllowed was
                # raised. Log a user-friendly message and re-raise the error.
                with excutils.save_and_reraise_exception():
                    LOG.error('This service is configured for access to the '
                              'API database but is not allowed to directly '
                              'access the database. You should run this '
                              'service without the [api_database]/connection '
                              'config option.')
        else:
            service_version = objects.Service.get_minimum_version(
                context.get_admin_context(), 'nova-compute')

        history = service_obj.SERVICE_VERSION_HISTORY

        # NOTE(johngarbutt) when there are no nova-compute services running we
        # get service_version == 0. In that case we do not want to cache
        # this result, because we will get a better answer next time.
        # As a sane default, return the current version.
        if service_version == 0:
            if not NO_COMPUTES_WARNING:
                # NOTE(danms): Only show this warning once
                LOG.debug("Not caching compute RPC version_cap, because min "
                          "service_version is 0. Please ensure a nova-compute "
                          "service has been started. Defaulting to current "
                          "version.")
                NO_COMPUTES_WARNING = True
            return history[service_obj.SERVICE_VERSION]['compute_rpc']

        try:
            version_cap = history[service_version]['compute_rpc']
        except IndexError:
            LOG.error('Failed to extract compute RPC version from '
                      'service history because I am too '
                      'old (minimum version is now %(version)i)',
                      {'version': service_version})
            raise exception.ServiceTooOld(thisver=service_obj.SERVICE_VERSION,
                                          minver=service_version)
        except KeyError:
            LOG.error('Failed to extract compute RPC version from '
                      'service history for version %(version)i',
                      {'version': service_version})
            return target.version
        LAST_VERSION = version_cap
        LOG.info('Automatically selected compute RPC version %(rpc)s '
                 'from minimum service version %(service)i',
                 {'rpc': version_cap,
                  'service': service_version})
        return version_cap

    def get_client(self, target, version_cap, serializer):
        if CONF.rpc_response_timeout > rpc.HEARTBEAT_THRESHOLD:
            # NOTE(danms): If the operator has overridden RPC timeout
            # to be longer than rpc.HEARTBEAT_THRESHOLD then configure
            # the call monitor timeout to be the threshold to keep the
            # failure timing characteristics that our code likely
            # expects (from history) while allowing healthy calls
            # to run longer.
            cmt = rpc.HEARTBEAT_THRESHOLD
        else:
            cmt = None
        return rpc.get_client(target,
                              version_cap=version_cap,
                              serializer=serializer,
                              call_monitor_timeout=cmt)

    def add_aggregate_host(self, ctxt, host, aggregate, host_param,
                           slave_info=None):
        '''Add aggregate host.

        :param ctxt: request context
        :param aggregate:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        cctxt.cast(ctxt, 'add_aggregate_host',
                   aggregate=aggregate, host=host_param,
                   slave_info=slave_info)

    def add_fixed_ip_to_instance(self, ctxt, instance, network_id):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'add_fixed_ip_to_instance',
                   instance=instance, network_id=network_id)

    def attach_interface(self, ctxt, instance, network_id, port_id,
                         requested_ip, tag=None):
        kw = {'instance': instance, 'network_id': network_id,
              'port_id': port_id, 'requested_ip': requested_ip,
              'tag': tag}
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                               version=version)
        return cctxt.call(ctxt, 'attach_interface', **kw)

    def attach_volume(self, ctxt, instance, bdm):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'attach_volume', instance=instance, bdm=bdm)

    def change_instance_metadata(self, ctxt, instance, diff):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'change_instance_metadata',
                   instance=instance, diff=diff)

    def check_can_live_migrate_destination(self, ctxt, instance, destination,
                                           block_migration, disk_over_commit,
                                           migration, limits):
        client = self.router.client(ctxt)
        version = '5.3'
        kwargs = {
            'instance': instance,
            'block_migration': block_migration,
            'disk_over_commit': disk_over_commit,
            'migration': migration,
            'limits': limits
        }
        if not client.can_send_version(version):
            kwargs.pop('migration')
            kwargs.pop('limits')
            version = '5.0'
        cctxt = client.prepare(server=destination, version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'check_can_live_migrate_destination', **kwargs)

    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        version = '5.0'
        client = self.router.client(ctxt)
        source = _compute_host(None, instance)
        cctxt = client.prepare(server=source, version=version)
        return cctxt.call(ctxt, 'check_can_live_migrate_source',
                          instance=instance,
                          dest_check_data=dest_check_data)

    def check_instance_shared_storage(self, ctxt, instance, data, host=None):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(host, instance), version=version)
        return cctxt.call(ctxt, 'check_instance_shared_storage',
                          instance=instance,
                          data=data)

    def confirm_resize(self, ctxt, instance, migration, host,
            cast=True):
        client = self.router.client(ctxt)
        version = '5.0'
        cctxt = client.prepare(
                server=_compute_host(host, instance), version=version)
        rpc_method = cctxt.cast if cast else cctxt.call
        return rpc_method(ctxt, 'confirm_resize',
                          instance=instance, migration=migration)

    def confirm_snapshot_based_resize_at_source(
            self, ctxt, instance, migration):
        """Confirms a snapshot-based resize on the source host.

        Cleans the guest from the source hypervisor including disks and drops
        the MoveClaim which will free up "old_flavor" usage from the
        ResourceTracker.

        Deletes the allocations held by the migration consumer against the
        source compute node resource provider.

        This is a synchronous RPC call using the ``long_rpc_timeout``
        configuration option.

        :param ctxt: nova auth request context targeted at the source cell
        :param instance: Instance object being resized which should have the
            "old_flavor" attribute set
        :param migration: Migration object for the resize operation
        :raises: nova.exception.MigrationError if the source compute is too
            old to perform the operation
        :raises: oslo_messaging.exceptions.MessagingTimeout if the RPC call
            times out
        """
        version = '5.8'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.MigrationError(reason=_('Compute too old'))
        cctxt = client.prepare(server=migration.source_compute,
                               version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(
            ctxt, 'confirm_snapshot_based_resize_at_source',
            instance=instance, migration=migration)

    def detach_interface(self, ctxt, instance, port_id):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'detach_interface',
                   instance=instance, port_id=port_id)

    def detach_volume(self, ctxt, instance, volume_id, attachment_id=None):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'detach_volume',
                   instance=instance, volume_id=volume_id,
                   attachment_id=attachment_id)

    def finish_resize(self, ctxt, instance, migration, image, disk_info, host,
                      request_spec):
        msg_args = {
            'instance': instance,
            'migration': migration,
            'image': image,
            'disk_info': disk_info,
            'request_spec': request_spec,
        }

        client = self.router.client(ctxt)
        version = '5.2'

        if not client.can_send_version(version):
            msg_args.pop('request_spec')
            version = '5.0'

        cctxt = client.prepare(
                server=host, version=version)
        cctxt.cast(ctxt, 'finish_resize', **msg_args)

    def finish_revert_resize(self, ctxt, instance, migration, host,
                             request_spec):
        msg_args = {
            'instance': instance,
            'migration': migration,
            'request_spec': request_spec,
        }

        client = self.router.client(ctxt)
        version = '5.2'

        if not client.can_send_version(version):
            msg_args.pop('request_spec')
            version = '5.0'

        cctxt = client.prepare(
                server=host, version=version)
        cctxt.cast(ctxt, 'finish_revert_resize', **msg_args)

    def finish_snapshot_based_resize_at_dest(
            self, ctxt, instance, migration, snapshot_id, request_spec):
        """Finishes the snapshot-based resize at the destination compute.

        Sets up block devices and networking on the destination compute and
        spawns the guest.

        This is a synchronous RPC call using the ``long_rpc_timeout``
        configuration option.

        :param ctxt: nova auth request context targeted at the target cell DB
        :param instance: The Instance object being resized with the
            ``migration_context`` field set. Upon successful completion of this
            method the vm_state should be "resized", the task_state should be
            None, and migration context, host/node and flavor-related fields
            should be set on the instance.
        :param migration: The Migration object for this resize operation. Upon
            successful completion of this method the migration status should
            be "finished".
        :param snapshot_id: ID of the image snapshot created for a
            non-volume-backed instance, else None.
        :param request_spec: nova.objects.RequestSpec object for the operation
        :raises: nova.exception.MigrationError if the destination compute
            service is too old for this method
        :raises: oslo_messaging.exceptions.MessagingTimeout if the pre-check
            RPC call times out
        """
        client = self.router.client(ctxt)
        version = '5.7'
        if not client.can_send_version(version):
            raise exception.MigrationError(reason=_('Compute too old'))
        cctxt = client.prepare(
            server=migration.dest_compute, version=version,
            call_monitor_timeout=CONF.rpc_response_timeout,
            timeout=CONF.long_rpc_timeout)
        return cctxt.call(
            ctxt, 'finish_snapshot_based_resize_at_dest',
            instance=instance, migration=migration, snapshot_id=snapshot_id,
            request_spec=request_spec)

    def finish_revert_snapshot_based_resize_at_source(
            self, ctxt, instance, migration):
        """Reverts a snapshot-based resize at the source host.

        Spawn the guest and re-connect volumes/VIFs on the source host and
        revert the instance to use the old_flavor for resource usage reporting.

        Updates allocations in the placement service to move the source node
        allocations, held by the migration record, to the instance and drop
        the allocations held by the instance on the destination node.

        This is a synchronous RPC call using the ``long_rpc_timeout``
        configuration option.

        :param ctxt: nova auth request context targeted at the source cell
        :param instance: Instance object whose vm_state is "resized" and
            task_state is "resize_reverting".
        :param migration: Migration object whose status is "reverting".
        :raises: nova.exception.MigrationError if the source compute is too
            old to perform the operation
        :raises: oslo_messaging.exceptions.MessagingTimeout if the RPC call
            times out
        """
        version = '5.10'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.MigrationError(reason=_('Compute too old'))
        cctxt = client.prepare(server=migration.source_compute,
                               version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(
            ctxt, 'finish_revert_snapshot_based_resize_at_source',
            instance=instance, migration=migration)

    def get_console_output(self, ctxt, instance, tail_length):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_console_output',
                          instance=instance, tail_length=tail_length)

    def get_console_pool_info(self, ctxt, host, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'get_console_pool_info',
                          console_type=console_type)

    # TODO(stephenfin): This is no longer used and can be removed in v6.0
    def get_console_topic(self, ctxt, host):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'get_console_topic')

    def get_diagnostics(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_diagnostics', instance=instance)

    def get_instance_diagnostics(self, ctxt, instance):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                               version=version)
        return cctxt.call(ctxt, 'get_instance_diagnostics', instance=instance)

    def get_vnc_console(self, ctxt, instance, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_vnc_console',
                          instance=instance, console_type=console_type)

    def get_spice_console(self, ctxt, instance, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_spice_console',
                          instance=instance, console_type=console_type)

    def get_rdp_console(self, ctxt, instance, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_rdp_console',
                          instance=instance, console_type=console_type)

    def get_mks_console(self, ctxt, instance, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_mks_console',
                          instance=instance, console_type=console_type)

    def get_serial_console(self, ctxt, instance, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'get_serial_console',
                          instance=instance, console_type=console_type)

    def validate_console_port(self, ctxt, instance, port, console_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'validate_console_port',
                          instance=instance, port=port,
                          console_type=console_type)

    def host_maintenance_mode(self, ctxt, host, host_param, mode):
        '''Set host maintenance mode

        :param ctxt: request context
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param mode:
        :param host: This is the host to send the message to.
        '''
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'host_maintenance_mode',
                          host=host_param, mode=mode)

    def host_power_action(self, ctxt, host, action):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'host_power_action', action=action)

    def inject_network_info(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'inject_network_info', instance=instance)

    def live_migration(self, ctxt, instance, dest, block_migration, host,
                       migration, migrate_data=None):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'live_migration', instance=instance,
                   dest=dest, block_migration=block_migration,
                   migrate_data=migrate_data, migration=migration)

    def live_migration_force_complete(self, ctxt, instance, migration):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(
                server=_compute_host(migration.source_compute, instance),
                version=version)
        cctxt.cast(ctxt, 'live_migration_force_complete', instance=instance)

    def live_migration_abort(self, ctxt, instance, migration_id):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'live_migration_abort', instance=instance,
                migration_id=migration_id)

    def pause_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'pause_instance', instance=instance)

    def post_live_migration_at_destination(self, ctxt, instance,
            block_migration, host):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version,
                call_monitor_timeout=CONF.rpc_response_timeout,
                timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'post_live_migration_at_destination',
            instance=instance, block_migration=block_migration)

    # TODO(mriedem): Remove the unused block_migration argument in v6.0 of
    # the compute RPC API.
    def pre_live_migration(self, ctxt, instance, block_migration, disk,
            host, migrate_data):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=host, version=version,
                               timeout=CONF.long_rpc_timeout,
                               call_monitor_timeout=CONF.rpc_response_timeout)
        return cctxt.call(ctxt, 'pre_live_migration',
                          instance=instance,
                          block_migration=block_migration,
                          disk=disk, migrate_data=migrate_data)

    def supports_resize_with_qos_port(self, ctxt):
        """Returns whether we can send 5.2, needed for migrating and resizing
        servers with ports having resource request.
        """
        client = self.router.client(ctxt)
        return client.can_send_version('5.2')

    # TODO(mriedem): Drop compat for request_spec being a legacy dict in v6.0.
    def prep_resize(self, ctxt, instance, image, instance_type, host,
                    migration, request_spec, filter_properties, node,
                    clean_shutdown, host_list):
        # TODO(mriedem): We should pass the ImageMeta object through to the
        # compute but that also requires plumbing changes through the resize
        # flow for other methods like resize_instance and finish_resize.
        image_p = objects_base.obj_to_primitive(image)
        msg_args = {'instance': instance,
                    'instance_type': instance_type,
                    'image': image_p,
                    'request_spec': request_spec,
                    'filter_properties': filter_properties,
                    'node': node,
                    'migration': migration,
                    'clean_shutdown': clean_shutdown,
                    'host_list': host_list}
        client = self.router.client(ctxt)
        version = '5.1'
        if not client.can_send_version(version):
            msg_args['request_spec'] = (
                request_spec.to_legacy_request_spec_dict())
            version = '5.0'
        cctxt = client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'prep_resize', **msg_args)

    def prep_snapshot_based_resize_at_dest(
            self, ctxt, instance, flavor, nodename, migration, limits,
            request_spec, destination):
        """Performs pre-cross-cell resize resource claim on the dest host.

        This runs on the destination host in a cross-cell resize operation
        before the resize is actually started.

        Performs a resize_claim for resources that are not claimed in placement
        like PCI devices and NUMA topology.

        Note that this is different from same-cell prep_resize in that this:

        * Does not RPC cast to the source compute, that is orchestrated from
          conductor.
        * This does not reschedule on failure, conductor handles that since
          conductor is synchronously RPC calling this method.

        :param ctxt: user auth request context
        :param instance: the instance being resized
        :param flavor: the flavor being resized to (unchanged for cold migrate)
        :param nodename: Name of the target compute node
        :param migration: nova.objects.Migration object for the operation
        :param limits: nova.objects.SchedulerLimits object of resource limits
        :param request_spec: nova.objects.RequestSpec object for the operation
        :param destination: possible target host for the cross-cell resize
        :returns: nova.objects.MigrationContext; the migration context created
            on the destination host during the resize_claim.
        :raises: nova.exception.MigrationPreCheckError if the pre-check
            validation fails for the given host selection or the destination
            compute service is too old for this method
        :raises: oslo_messaging.exceptions.MessagingTimeout if the pre-check
            RPC call times out
        """
        version = '5.5'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.MigrationPreCheckError(reason=_('Compute too old'))
        cctxt = client.prepare(server=destination, version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'prep_snapshot_based_resize_at_dest',
                          instance=instance, flavor=flavor, nodename=nodename,
                          migration=migration, limits=limits,
                          request_spec=request_spec)

    def prep_snapshot_based_resize_at_source(
            self, ctxt, instance, migration, snapshot_id=None):
        """Prepares the instance at the source host for cross-cell resize

        Performs actions like powering off the guest, upload snapshot data if
        the instance is not volume-backed, disconnecting volumes, unplugging
        VIFs and activating the destination host port bindings.

        :param ctxt: user auth request context targeted at source cell
        :param instance: nova.objects.Instance; the instance being resized.
            The expected instance.task_state is "resize_migrating" when calling
            this method, and the expected task_state upon successful completion
            is "resize_migrated".
        :param migration: nova.objects.Migration object for the operation.
            The expected migration.status is "pre-migrating" when calling this
            method and the expected status upon successful completion is
            "post-migrating".
        :param snapshot_id: ID of the image snapshot to upload if not a
            volume-backed instance
        :raises: nova.exception.InstancePowerOffFailure if stopping the
            instance fails
        :raises: nova.exception.MigrationError if the source compute is too
            old to perform the operation
        :raises: oslo_messaging.exceptions.MessagingTimeout if the RPC call
            times out
        """
        version = '5.6'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.MigrationError(reason=_('Compute too old'))
        cctxt = client.prepare(server=_compute_host(None, instance),
                               version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(
            ctxt, 'prep_snapshot_based_resize_at_source',
            instance=instance, migration=migration, snapshot_id=snapshot_id)

    def reboot_instance(self, ctxt, instance, block_device_info,
                        reboot_type):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'reboot_instance',
                   instance=instance,
                   block_device_info=block_device_info,
                   reboot_type=reboot_type)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref, orig_sys_metadata, bdms,
            recreate, on_shared_storage, host, node,
            preserve_ephemeral, migration, limits, request_spec):
        # NOTE(edleafe): compute nodes can only use the dict form of limits.
        if isinstance(limits, objects.SchedulerLimits):
            limits = limits.to_dict()
        msg_args = {'preserve_ephemeral': preserve_ephemeral,
                    'migration': migration,
                    'scheduled_node': node,
                    'limits': limits,
                    'request_spec': request_spec}
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(host, instance),
                version=version)
        cctxt.cast(ctxt, 'rebuild_instance',
                   instance=instance, new_pass=new_pass,
                   injected_files=injected_files, image_ref=image_ref,
                   orig_image_ref=orig_image_ref,
                   orig_sys_metadata=orig_sys_metadata, bdms=bdms,
                   recreate=recreate, on_shared_storage=on_shared_storage,
                   **msg_args)

    def remove_aggregate_host(self, ctxt, host, aggregate, host_param,
                              slave_info=None):
        '''Remove aggregate host.

        :param ctxt: request context
        :param aggregate:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        cctxt.cast(ctxt, 'remove_aggregate_host',
                   aggregate=aggregate, host=host_param,
                   slave_info=slave_info)

    def remove_fixed_ip_from_instance(self, ctxt, instance, address):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'remove_fixed_ip_from_instance',
                   instance=instance, address=address)

    def remove_volume_connection(self, ctxt, instance, volume_id, host):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'remove_volume_connection',
                          instance=instance, volume_id=volume_id)

    def rescue_instance(self, ctxt, instance, rescue_password,
                        rescue_image_ref=None, clean_shutdown=True):
        version = '5.0'
        msg_args = {'rescue_password': rescue_password,
                    'clean_shutdown': clean_shutdown,
                    'rescue_image_ref': rescue_image_ref,
                    'instance': instance,
        }
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'rescue_instance', **msg_args)

    # Remove as it only supports nova network
    def reset_network(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'reset_network', instance=instance)

    def resize_instance(self, ctxt, instance, migration, image, instance_type,
                        request_spec, clean_shutdown=True):
        msg_args = {'instance': instance, 'migration': migration,
                    'image': image,
                    'instance_type': instance_type,
                    'clean_shutdown': clean_shutdown,
                    'request_spec': request_spec,
        }
        version = '5.2'
        client = self.router.client(ctxt)

        if not client.can_send_version(version):
            msg_args.pop('request_spec')
            version = '5.0'

        cctxt = client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'resize_instance', **msg_args)

    def resume_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'resume_instance', instance=instance)

    def revert_resize(self, ctxt, instance, migration, host, request_spec):

        msg_args = {
            'instance': instance,
            'migration': migration,
            'request_spec': request_spec,
        }

        client = self.router.client(ctxt)
        version = '5.2'

        if not client.can_send_version(version):
            msg_args.pop('request_spec')
            version = '5.0'

        cctxt = client.prepare(
                server=_compute_host(host, instance), version=version)
        cctxt.cast(ctxt, 'revert_resize', **msg_args)

    def revert_snapshot_based_resize_at_dest(self, ctxt, instance, migration):
        """Reverts a snapshot-based resize at the destination host.

        Cleans the guest from the destination compute service host hypervisor
        and related resources (ports, volumes) and frees resource usage from
        the compute service on that host.

        This is a synchronous RPC call using the ``long_rpc_timeout``
        configuration option.

        :param ctxt: nova auth request context targeted at the target cell
        :param instance: Instance object whose vm_state is "resized" and
            task_state is "resize_reverting".
        :param migration: Migration object whose status is "reverting".
        :raises: nova.exception.MigrationError if the destination compute
            service is too old to perform the operation
        :raises: oslo_messaging.exceptions.MessagingTimeout if the RPC call
            times out
        """
        version = '5.9'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.MigrationError(reason=_('Compute too old'))
        cctxt = client.prepare(server=migration.dest_compute,
                               version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(
            ctxt, 'revert_snapshot_based_resize_at_dest',
            instance=instance, migration=migration)

    def rollback_live_migration_at_destination(self, ctxt, instance, host,
                                               destroy_disks,
                                               migrate_data):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'rollback_live_migration_at_destination',
                   instance=instance, destroy_disks=destroy_disks,
                   migrate_data=migrate_data)

    def supports_numa_live_migration(self, ctxt):
        """Returns whether we can send 5.3, needed for NUMA live migration.
        """
        client = self.router.client(ctxt)
        return client.can_send_version('5.3')

    def drop_move_claim_at_destination(self, ctxt, instance, host):
        """Called by the source of a live migration that's being rolled back.
        This is a call not because we care about the return value, but because
        dropping the move claim depends on instance.migration_context being
        set, and we drop the migration context on the source. Thus, to avoid
        races, we call the destination synchronously to make sure it's done
        dropping the move claim before we drop the migration context from the
        instance.
        """
        version = '5.3'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=host, version=version)
        cctxt.call(ctxt, 'drop_move_claim_at_destination', instance=instance)

    def set_admin_password(self, ctxt, instance, new_pass):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'set_admin_password',
                          instance=instance, new_pass=new_pass)

    def set_host_enabled(self, ctxt, host, enabled):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version,
                call_monitor_timeout=CONF.rpc_response_timeout,
                timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'set_host_enabled', enabled=enabled)

    def swap_volume(self, ctxt, instance, old_volume_id, new_volume_id,
                    new_attachment_id):
        version = '5.0'
        client = self.router.client(ctxt)
        kwargs = dict(instance=instance,
                      old_volume_id=old_volume_id,
                      new_volume_id=new_volume_id,
                      new_attachment_id=new_attachment_id)
        cctxt = client.prepare(
            server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'swap_volume', **kwargs)

    def get_host_uptime(self, ctxt, host):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=host, version=version)
        return cctxt.call(ctxt, 'get_host_uptime')

    def reserve_block_device_name(self, ctxt, instance, device, volume_id,
                                  disk_bus, device_type, tag,
                                  multiattach):
        kw = {'instance': instance, 'device': device,
              'volume_id': volume_id, 'disk_bus': disk_bus,
              'device_type': device_type, 'tag': tag,
              'multiattach': multiattach}
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                               version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'reserve_block_device_name', **kw)

    def backup_instance(self, ctxt, instance, image_id, backup_type,
                        rotation):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'backup_instance',
                   instance=instance,
                   image_id=image_id,
                   backup_type=backup_type,
                   rotation=rotation)

    def snapshot_instance(self, ctxt, instance, image_id):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'snapshot_instance',
                   instance=instance,
                   image_id=image_id)

    def start_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'start_instance', instance=instance)

    def stop_instance(self, ctxt, instance, do_cast=True, clean_shutdown=True):
        msg_args = {'instance': instance,
                    'clean_shutdown': clean_shutdown}
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        rpc_method = cctxt.cast if do_cast else cctxt.call
        return rpc_method(ctxt, 'stop_instance', **msg_args)

    def suspend_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'suspend_instance', instance=instance)

    def terminate_instance(self, ctxt, instance, bdms):
        client = self.router.client(ctxt)
        version = '5.0'
        cctxt = client.prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'terminate_instance', instance=instance, bdms=bdms)

    def unpause_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'unpause_instance', instance=instance)

    def unrescue_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'unrescue_instance', instance=instance)

    def soft_delete_instance(self, ctxt, instance):
        client = self.router.client(ctxt)
        version = '5.0'
        cctxt = client.prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'soft_delete_instance', instance=instance)

    def restore_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'restore_instance', instance=instance)

    def shelve_instance(self, ctxt, instance, image_id=None,
                        clean_shutdown=True):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'shelve_instance', instance=instance,
                   image_id=image_id, clean_shutdown=clean_shutdown)

    def shelve_offload_instance(self, ctxt, instance,
                                clean_shutdown=True):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'shelve_offload_instance', instance=instance,
                   clean_shutdown=clean_shutdown)

    def unshelve_instance(self, ctxt, instance, host, request_spec, image=None,
                          filter_properties=None, node=None):
        version = '5.2'
        msg_kwargs = {
            'instance': instance,
            'image': image,
            'filter_properties': filter_properties,
            'node': node,
            'request_spec': request_spec,
        }

        client = self.router.client(ctxt)

        if not client.can_send_version(version):
            msg_kwargs.pop('request_spec')
            version = '5.0'

        cctxt = client.prepare(
                server=host, version=version)
        cctxt.cast(ctxt, 'unshelve_instance', **msg_kwargs)

    def volume_snapshot_create(self, ctxt, instance, volume_id,
                               create_info):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'volume_snapshot_create', instance=instance,
                   volume_id=volume_id, create_info=create_info)

    def volume_snapshot_delete(self, ctxt, instance, volume_id, snapshot_id,
                               delete_info):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'volume_snapshot_delete', instance=instance,
                   volume_id=volume_id, snapshot_id=snapshot_id,
                   delete_info=delete_info)

    def external_instance_event(self, ctxt, instances, events, host=None):
        instance = instances[0]
        cctxt = self.router.client(ctxt).prepare(
            server=_compute_host(host, instance),
            version='5.0')
        cctxt.cast(ctxt, 'external_instance_event', instances=instances,
                   events=events)

    def build_and_run_instance(self, ctxt, instance, host, image, request_spec,
            filter_properties, admin_password=None, injected_files=None,
            requested_networks=None, security_groups=None,
            block_device_mapping=None, node=None, limits=None,
            host_list=None, accel_uuids=None):
        # NOTE(edleafe): compute nodes can only use the dict form of limits.
        if isinstance(limits, objects.SchedulerLimits):
            limits = limits.to_dict()
        kwargs = {"instance": instance,
                  "image": image,
                  "request_spec": request_spec,
                  "filter_properties": filter_properties,
                  "admin_password": admin_password,
                  "injected_files": injected_files,
                  "requested_networks": requested_networks,
                  "security_groups": security_groups,
                  "block_device_mapping": block_device_mapping,
                  "node": node,
                  "limits": limits,
                  "host_list": host_list,
                  "accel_uuids": accel_uuids,
                 }
        client = self.router.client(ctxt)
        version = '5.11'
        if not client.can_send_version(version):
            kwargs.pop('accel_uuids')
            version = '5.0'
        cctxt = client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'build_and_run_instance', **kwargs)

    def quiesce_instance(self, ctxt, instance):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        return cctxt.call(ctxt, 'quiesce_instance', instance=instance)

    def unquiesce_instance(self, ctxt, instance, mapping=None):
        version = '5.0'
        cctxt = self.router.client(ctxt).prepare(
                server=_compute_host(None, instance), version=version)
        cctxt.cast(ctxt, 'unquiesce_instance', instance=instance,
                   mapping=mapping)

    # TODO(stephenfin): Remove this as it's nova-network only
    def refresh_instance_security_rules(self, ctxt, instance, host):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'refresh_instance_security_rules',
                   instance=instance)

    def trigger_crash_dump(self, ctxt, instance):
        version = '5.0'
        client = self.router.client(ctxt)
        cctxt = client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.cast(ctxt, "trigger_crash_dump", instance=instance)

    def cache_images(self, ctxt, host, image_ids):
        version = '5.4'
        client = self.router.client(ctxt)
        if not client.can_send_version(version):
            raise exception.NovaException('Compute RPC version pin does not '
                                          'allow cache_images() to be called')
        # This is a potentially very long-running call, so we provide the
        # two timeout values which enables the call monitor in oslo.messaging
        # so that this can run for extended periods.
        cctxt = client.prepare(server=host, version=version,
                               call_monitor_timeout=CONF.rpc_response_timeout,
                               timeout=CONF.long_rpc_timeout)
        return cctxt.call(ctxt, 'cache_images', image_ids=image_ids)
