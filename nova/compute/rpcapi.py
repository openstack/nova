# Copyright 2013 Red Hat, Inc.
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
Client side of the compute RPC API.
"""

from oslo.config import cfg
from oslo import messaging
from oslo.serialization import jsonutils

from nova import exception
from nova.i18n import _, _LW
from nova import objects
from nova.objects import base as objects_base
from nova.openstack.common import log as logging
from nova import rpc

rpcapi_opts = [
    cfg.StrOpt('compute_topic',
               default='compute',
               help='The topic compute nodes listen on'),
]

CONF = cfg.CONF
CONF.register_opts(rpcapi_opts)

rpcapi_cap_opt = cfg.StrOpt('compute',
        help='Set a version cap for messages sent to compute services. If you '
             'plan to do a live upgrade from havana to icehouse, you should '
             'set this option to "icehouse-compat" before beginning the live '
             'upgrade procedure.')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')

LOG = logging.getLogger(__name__)


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
    if not instance['host']:
        raise exception.NovaException(_('Unable to find host for '
                                        'Instance %s') % instance['uuid'])
    return instance['host']


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
    '''

    VERSION_ALIASES = {
        'icehouse': '3.23',
        'juno': '3.35',
    }

    def __init__(self):
        super(ComputeAPI, self).__init__()
        target = messaging.Target(topic=CONF.compute_topic, version='3.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.compute,
                                               CONF.upgrade_levels.compute)
        serializer = objects_base.NovaObjectSerializer()
        self.client = self.get_client(target, version_cap, serializer)

    # Cells overrides this
    def get_client(self, target, version_cap, serializer):
        return rpc.get_client(target,
                              version_cap=version_cap,
                              serializer=serializer)

    def add_aggregate_host(self, ctxt, aggregate, host_param, host,
                           slave_info=None):
        '''Add aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'add_aggregate_host',
                   aggregate=aggregate, host=host_param,
                   slave_info=slave_info)

    def add_fixed_ip_to_instance(self, ctxt, instance, network_id):
        version = '3.12'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'add_fixed_ip_to_instance',
                   instance=instance, network_id=network_id)

    def attach_interface(self, ctxt, instance, network_id, port_id,
                         requested_ip):
        version = '3.17'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'attach_interface',
                          instance=instance, network_id=network_id,
                          port_id=port_id, requested_ip=requested_ip)

    def attach_volume(self, ctxt, instance, volume_id, mountpoint, bdm=None):
        # NOTE(ndipanov): Remove volume_id and mountpoint on the next major
        # version bump - they are not needed when using bdm objects.
        version = '3.16'
        kw = {'instance': instance, 'volume_id': volume_id,
              'mountpoint': mountpoint, 'bdm': bdm}
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'attach_volume', **kw)

    def change_instance_metadata(self, ctxt, instance, diff):
        version = '3.7'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'change_instance_metadata',
                   instance=instance, diff=diff)

    def _warn_buggy_live_migrations(self, data=None):
        # NOTE(danms): We know that libvirt live migration with shared block
        # storage was buggy (potential loss of data) before version 3.32.
        # Since we need to support live migration with older clients, we need
        # to warn the operator of this possibility. The logic below tries to
        # decide if a warning should be emitted, assuming the positive if
        # not sure. This can be removed when we bump to RPC API version 4.0.
        if data:
            if data.get('is_shared_block_storage') is not False:
                # Shared block storage, or unknown
                should_warn = True
            else:
                # Specifically not shared block storage
                should_warn = False
        else:
            # Unknown, so warn to be safe
            should_warn = True

        if should_warn:
            LOG.warning(_LW('Live migration with clients before RPC version '
                            '3.32 is known to be buggy with shared block '
                            'storage. See '
                            'https://bugs.launchpad.net/nova/+bug/1250751 for '
                            'more information!'))

    def check_can_live_migrate_destination(self, ctxt, instance, destination,
                                           block_migration, disk_over_commit):
        if self.client.can_send_version('3.32'):
            version = '3.32'
        else:
            version = '3.0'
            self._warn_buggy_live_migrations()
        cctxt = self.client.prepare(server=destination, version=version)
        return cctxt.call(ctxt, 'check_can_live_migrate_destination',
                          instance=instance,
                          block_migration=block_migration,
                          disk_over_commit=disk_over_commit)

    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        if self.client.can_send_version('3.32'):
            version = '3.32'
        else:
            version = '3.0'
            self._warn_buggy_live_migrations()
        source = _compute_host(None, instance)
        cctxt = self.client.prepare(server=source, version=version)
        return cctxt.call(ctxt, 'check_can_live_migrate_source',
                          instance=instance,
                          dest_check_data=dest_check_data)

    def check_instance_shared_storage(self, ctxt, instance, data):
        if self.client.can_send_version('3.29'):
            version = '3.29'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'check_instance_shared_storage',
                          instance=instance,
                          data=data)

    def confirm_resize(self, ctxt, instance, migration, host,
            reservations=None, cast=True):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(host, instance),
                version=version)
        rpc_method = cctxt.cast if cast else cctxt.call
        return rpc_method(ctxt, 'confirm_resize',
                          instance=instance, migration=migration,
                          reservations=reservations)

    def detach_interface(self, ctxt, instance, port_id):
        version = '3.17'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'detach_interface',
                   instance=instance, port_id=port_id)

    def detach_volume(self, ctxt, instance, volume_id):
        if self.client.can_send_version('3.25'):
            version = '3.25'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'detach_volume',
                   instance=instance, volume_id=volume_id)

    def finish_resize(self, ctxt, instance, migration, image, disk_info,
            host, reservations=None):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'finish_resize',
                   instance=instance, migration=migration,
                   image=image, disk_info=disk_info, reservations=reservations)

    def finish_revert_resize(self, ctxt, instance, migration, host,
                             reservations=None):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'finish_revert_resize',
                   instance=instance, migration=migration,
                   reservations=reservations)

    def get_console_output(self, ctxt, instance, tail_length):
        if self.client.can_send_version('3.28'):
            version = '3.28'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_console_output',
                          instance=instance, tail_length=tail_length)

    def get_console_pool_info(self, ctxt, console_type, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'get_console_pool_info',
                          console_type=console_type)

    def get_console_topic(self, ctxt, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'get_console_topic')

    def get_diagnostics(self, ctxt, instance):
        version = '3.18'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_diagnostics', instance=instance)

    def get_instance_diagnostics(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        kwargs = {'instance': instance_p}
        version = '3.31'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_instance_diagnostics', **kwargs)

    def get_vnc_console(self, ctxt, instance, console_type):
        version = '3.2'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_vnc_console',
                          instance=instance, console_type=console_type)

    def get_spice_console(self, ctxt, instance, console_type):
        version = '3.1'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_spice_console',
                          instance=instance, console_type=console_type)

    def get_rdp_console(self, ctxt, instance, console_type):
        version = '3.10'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'get_rdp_console',
                          instance=instance, console_type=console_type)

    def get_serial_console(self, ctxt, instance, console_type):
        version = '3.34'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                                    version=version)
        return cctxt.call(ctxt, 'get_serial_console',
                          instance=instance, console_type=console_type)

    def validate_console_port(self, ctxt, instance, port, console_type):
        version = '3.3'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'validate_console_port',
                          instance=instance, port=port,
                          console_type=console_type)

    def host_maintenance_mode(self, ctxt, host_param, mode, host):
        '''Set host maintenance mode

        :param ctxt: request context
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param mode:
        :param host: This is the host to send the message to.
        '''
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'host_maintenance_mode',
                          host=host_param, mode=mode)

    def host_power_action(self, ctxt, action, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'host_power_action', action=action)

    def inject_network_info(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'inject_network_info', instance=instance)

    def live_migration(self, ctxt, instance, dest, block_migration, host,
                       migrate_data=None):
        if self.client.can_send_version('3.26'):
            version = '3.26'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'live_migration', instance=instance,
                   dest=dest, block_migration=block_migration,
                   migrate_data=migrate_data)

    def pause_instance(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'pause_instance', instance=instance)

    def post_live_migration_at_destination(self, ctxt, instance,
            block_migration, host):
        version = '3.14'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'post_live_migration_at_destination',
            instance=instance, block_migration=block_migration)

    def pre_live_migration(self, ctxt, instance, block_migration, disk,
            host, migrate_data=None):
        version = '3.19'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'pre_live_migration',
                          instance=instance,
                          block_migration=block_migration,
                          disk=disk, migrate_data=migrate_data)

    def prep_resize(self, ctxt, image, instance, instance_type, host,
                    reservations=None, request_spec=None,
                    filter_properties=None, node=None):
        version = '3.0'
        instance_type_p = jsonutils.to_primitive(instance_type)
        image_p = jsonutils.to_primitive(image)
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'prep_resize',
                   instance=instance,
                   instance_type=instance_type_p,
                   image=image_p, reservations=reservations,
                   request_spec=request_spec,
                   filter_properties=filter_properties,
                   node=node)

    def reboot_instance(self, ctxt, instance, block_device_info,
                        reboot_type):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'reboot_instance',
                   instance=instance,
                   block_device_info=block_device_info,
                   reboot_type=reboot_type)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref, orig_sys_metadata, bdms,
            recreate=False, on_shared_storage=False, host=None,
            preserve_ephemeral=False, kwargs=None):
        # NOTE(danms): kwargs is only here for cells compatibility, don't
        # actually send it to compute
        extra = {'preserve_ephemeral': preserve_ephemeral}
        version = '3.21'
        cctxt = self.client.prepare(server=_compute_host(host, instance),
                version=version)
        cctxt.cast(ctxt, 'rebuild_instance',
                   instance=instance, new_pass=new_pass,
                   injected_files=injected_files, image_ref=image_ref,
                   orig_image_ref=orig_image_ref,
                   orig_sys_metadata=orig_sys_metadata, bdms=bdms,
                   recreate=recreate, on_shared_storage=on_shared_storage,
                   **extra)

    def refresh_provider_fw_rules(self, ctxt, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'refresh_provider_fw_rules')

    def remove_aggregate_host(self, ctxt, aggregate, host_param, host,
                              slave_info=None):
        '''Remove aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'remove_aggregate_host',
                   aggregate=aggregate, host=host_param,
                   slave_info=slave_info)

    def remove_fixed_ip_from_instance(self, ctxt, instance, address):
        version = '3.13'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'remove_fixed_ip_from_instance',
                   instance=instance, address=address)

    def remove_volume_connection(self, ctxt, instance, volume_id, host):
        if self.client.can_send_version('3.30'):
            version = '3.30'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'remove_volume_connection',
                          instance=instance, volume_id=volume_id)

    def rescue_instance(self, ctxt, instance, rescue_password,
                        rescue_image_ref=None, clean_shutdown=True):
        msg_args = {'rescue_password': rescue_password}
        if self.client.can_send_version('3.37'):
            version = '3.37'
            msg_args['clean_shutdown'] = clean_shutdown
            msg_args['rescue_image_ref'] = rescue_image_ref
        elif self.client.can_send_version('3.24'):
            version = '3.24'
            msg_args['rescue_image_ref'] = rescue_image_ref
        else:
            version = '3.9'
        msg_args['instance'] = instance
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'rescue_instance', **msg_args)

    def reset_network(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'reset_network', instance=instance)

    def resize_instance(self, ctxt, instance, migration, image, instance_type,
                        reservations=None, clean_shutdown=True):
        instance_type_p = jsonutils.to_primitive(instance_type)
        msg_args = {'instance': instance, 'migration': migration,
                    'image': image, 'reservations': reservations,
                    'instance_type': instance_type_p}
        if self.client.can_send_version('3.37'):
            version = '3.37'
            msg_args['clean_shutdown'] = clean_shutdown
        else:
            version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'resize_instance', **msg_args)

    def resume_instance(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'resume_instance', instance=instance)

    def revert_resize(self, ctxt, instance, migration, host,
                      reservations=None):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(host, instance),
                version=version)
        cctxt.cast(ctxt, 'revert_resize',
                   instance=instance, migration=migration,
                   reservations=reservations)

    def rollback_live_migration_at_destination(self, ctxt, instance, host,
                                               destroy_disks=True,
                                               migrate_data=None):
        if self.client.can_send_version('3.32'):
            version = '3.32'
            extra = {'destroy_disks': destroy_disks,
                     'migrate_data': migrate_data,
                 }
        else:
            version = '3.0'
            extra = {}
            self._warn_buggy_live_migrations(migrate_data)
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'rollback_live_migration_at_destination',
                   instance=instance, **extra)

    # NOTE(alaski): Remove this method when the scheduler rpc interface is
    # bumped to 4.x as the only callers of this method will be removed.
    def run_instance(self, ctxt, instance, host, request_spec,
                     filter_properties, requested_networks,
                     injected_files, admin_password,
                     is_first_time, node=None, legacy_bdm_in_spec=True):
        if self.client.can_send_version('3.27'):
            version = '3.27'
        else:
            version = '3.0'
            instance = jsonutils.to_primitive(instance)
        msg_kwargs = {'instance': instance, 'request_spec': request_spec,
                      'filter_properties': filter_properties,
                      'requested_networks': requested_networks,
                      'injected_files': injected_files,
                      'admin_password': admin_password,
                      'is_first_time': is_first_time, 'node': node,
                      'legacy_bdm_in_spec': legacy_bdm_in_spec}

        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'run_instance', **msg_kwargs)

    def set_admin_password(self, ctxt, instance, new_pass):
        version = '3.8'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        return cctxt.call(ctxt, 'set_admin_password',
                          instance=instance, new_pass=new_pass)

    def set_host_enabled(self, ctxt, enabled, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'set_host_enabled', enabled=enabled)

    def swap_volume(self, ctxt, instance, old_volume_id, new_volume_id):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'swap_volume',
                   instance=instance, old_volume_id=old_volume_id,
                   new_volume_id=new_volume_id)

    def get_host_uptime(self, ctxt, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'get_host_uptime')

    def reserve_block_device_name(self, ctxt, instance, device, volume_id,
                                  disk_bus=None, device_type=None):
        kw = {'instance': instance, 'device': device,
              'volume_id': volume_id, 'disk_bus': disk_bus,
              'device_type': device_type, 'return_bdm_object': True}
        if self.client.can_send_version('3.35'):
            version = '3.35'
        else:
            del kw['return_bdm_object']
            version = '3.16'

        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        volume_bdm = cctxt.call(ctxt, 'reserve_block_device_name', **kw)
        if not isinstance(volume_bdm, objects.BlockDeviceMapping):
            volume_bdm = objects.BlockDeviceMapping.get_by_volume_id(
                ctxt, volume_id)
        return volume_bdm

    def backup_instance(self, ctxt, instance, image_id, backup_type,
                        rotation):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'backup_instance',
                   instance=instance,
                   image_id=image_id,
                   backup_type=backup_type,
                   rotation=rotation)

    def snapshot_instance(self, ctxt, instance, image_id):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'snapshot_instance',
                   instance=instance,
                   image_id=image_id)

    def start_instance(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'start_instance', instance=instance)

    def stop_instance(self, ctxt, instance, do_cast=True, clean_shutdown=True):
        msg_args = {'instance': instance}
        if self.client.can_send_version('3.37'):
            version = '3.37'
            msg_args['clean_shutdown'] = clean_shutdown
        else:
            version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        rpc_method = cctxt.cast if do_cast else cctxt.call
        return rpc_method(ctxt, 'stop_instance', **msg_args)

    def suspend_instance(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'suspend_instance', instance=instance)

    def terminate_instance(self, ctxt, instance, bdms, reservations=None):
        version = '3.22'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'terminate_instance',
                   instance=instance, bdms=bdms,
                   reservations=reservations)

    def unpause_instance(self, ctxt, instance):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'unpause_instance', instance=instance)

    def unrescue_instance(self, ctxt, instance):
        version = '3.11'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'unrescue_instance', instance=instance)

    def soft_delete_instance(self, ctxt, instance, reservations=None):
        version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'soft_delete_instance',
                   instance=instance, reservations=reservations)

    def restore_instance(self, ctxt, instance):
        version = '3.20'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'restore_instance', instance=instance)

    def shelve_instance(self, ctxt, instance, image_id=None,
                        clean_shutdown=True):
        msg_args = {'instance': instance, 'image_id': image_id}
        if self.client.can_send_version('3.37'):
            version = '3.37'
            msg_args['clean_shutdown'] = clean_shutdown
        else:
            version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'shelve_instance', **msg_args)

    def shelve_offload_instance(self, ctxt, instance,
                                clean_shutdown=True):
        msg_args = {'instance': instance}
        if self.client.can_send_version('3.37'):
            version = '3.37'
            msg_args['clean_shutdown'] = clean_shutdown
        else:
            version = '3.0'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'shelve_offload_instance', **msg_args)

    def unshelve_instance(self, ctxt, instance, host, image=None,
                          filter_properties=None, node=None):
        version = '3.15'
        msg_kwargs = {
            'instance': instance,
            'image': image,
            'filter_properties': filter_properties,
            'node': node,
        }
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'unshelve_instance', **msg_kwargs)

    def volume_snapshot_create(self, ctxt, instance, volume_id,
                               create_info):
        version = '3.6'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'volume_snapshot_create', instance=instance,
                   volume_id=volume_id, create_info=create_info)

    def volume_snapshot_delete(self, ctxt, instance, volume_id, snapshot_id,
                               delete_info):
        version = '3.6'
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'volume_snapshot_delete', instance=instance,
                   volume_id=volume_id, snapshot_id=snapshot_id,
                   delete_info=delete_info)

    def external_instance_event(self, ctxt, instances, events):
        cctxt = self.client.prepare(
            server=_compute_host(None, instances[0]),
            version='3.23')
        cctxt.cast(ctxt, 'external_instance_event', instances=instances,
                   events=events)

    def build_and_run_instance(self, ctxt, instance, host, image, request_spec,
            filter_properties, admin_password=None, injected_files=None,
            requested_networks=None, security_groups=None,
            block_device_mapping=None, node=None, limits=None):
        version = '3.36'
        if not self.client.can_send_version(version):
            version = '3.33'
            if 'instance_type' in filter_properties:
                flavor = filter_properties['instance_type']
                flavor_p = objects_base.obj_to_primitive(flavor)
                filter_properties = dict(filter_properties,
                                         instance_type=flavor_p)
        if not self.client.can_send_version(version):
            version = '3.23'
            if requested_networks is not None:
                requested_networks = [(network_id, address, port_id)
                    for (network_id, address, port_id, _) in
                        requested_networks.as_tuples()]

        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'build_and_run_instance', instance=instance,
                image=image, request_spec=request_spec,
                filter_properties=filter_properties,
                admin_password=admin_password,
                injected_files=injected_files,
                requested_networks=requested_networks,
                security_groups=security_groups,
                block_device_mapping=block_device_mapping, node=node,
                limits=limits)


class SecurityGroupAPI(object):
    '''Client side of the security group rpc API.

    API version history:

        1.0 - Initial version.
        1.41 - Adds refresh_instance_security_rules()

        2.0 - Remove 1.x backwards compat

        3.0 - Identical to 2.x, but has to be bumped at the same time as the
              compute API since it's all together on the server side.
    '''

    def __init__(self):
        super(SecurityGroupAPI, self).__init__()
        target = messaging.Target(topic=CONF.compute_topic, version='3.0')
        version_cap = ComputeAPI.VERSION_ALIASES.get(
                CONF.upgrade_levels.compute, CONF.upgrade_levels.compute)
        self.client = rpc.get_client(target, version_cap)

    def refresh_security_group_rules(self, ctxt, security_group_id, host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'refresh_security_group_rules',
                   security_group_id=security_group_id)

    def refresh_security_group_members(self, ctxt, security_group_id,
            host):
        version = '3.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'refresh_security_group_members',
                   security_group_id=security_group_id)

    def refresh_instance_security_rules(self, ctxt, host, instance):
        version = '3.0'
        instance_p = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(server=_compute_host(None, instance),
                version=version)
        cctxt.cast(ctxt, 'refresh_instance_security_rules',
                   instance=instance_p)
