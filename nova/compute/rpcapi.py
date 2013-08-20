# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

from nova import exception
from nova.objects import base as objects_base
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
import nova.openstack.common.rpc
import nova.openstack.common.rpc.proxy

rpcapi_opts = [
    cfg.StrOpt('compute_topic',
               default='compute',
               help='the topic compute nodes listen on'),
]

CONF = cfg.CONF
CONF.register_opts(rpcapi_opts)

rpcapi_cap_opt = cfg.StrOpt('compute',
        help='Set a version cap for messages sent to compute services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


def _compute_topic(topic, ctxt, host, instance):
    '''Get the topic to use for a message.

    :param topic: the base topic
    :param ctxt: request context
    :param host: explicit host to send the message to.
    :param instance: If an explicit host was not specified, use
                     instance['host']

    :returns: A topic string
    '''
    if not host:
        if not instance:
            raise exception.NovaException(_('No compute host specified'))
        host = instance['host']
        if not host:
            raise exception.NovaException(_('Unable to find host for '
                                          'Instance %s') % instance['uuid'])
    return rpc.queue_get_for(ctxt, topic, host)


class ComputeAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the compute rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Adds get_host_uptime()
        1.2 - Adds check_can_live_migrate_[destination|source]
        1.3 - Adds change_instance_metadata()
        1.4 - Remove instance_uuid, add instance argument to reboot_instance()
        1.5 - Remove instance_uuid, add instance argument to pause_instance(),
              unpause_instance()
        1.6 - Remove instance_uuid, add instance argument to suspend_instance()
        1.7 - Remove instance_uuid, add instance argument to
              get_console_output()
        1.8 - Remove instance_uuid, add instance argument to
              add_fixed_ip_to_instance()
        1.9 - Remove instance_uuid, add instance argument to attach_volume()
        1.10 - Remove instance_id, add instance argument to
               check_can_live_migrate_destination()
        1.11 - Remove instance_id, add instance argument to
               check_can_live_migrate_source()
        1.12 - Remove instance_uuid, add instance argument to confirm_resize()
        1.13 - Remove instance_uuid, add instance argument to detach_volume()
        1.14 - Remove instance_uuid, add instance argument to finish_resize()
        1.15 - Remove instance_uuid, add instance argument to
               finish_revert_resize()
        1.16 - Remove instance_uuid, add instance argument to get_diagnostics()
        1.17 - Remove instance_uuid, add instance argument to get_vnc_console()
        1.18 - Remove instance_uuid, add instance argument to inject_file()
        1.19 - Remove instance_uuid, add instance argument to
               inject_network_info()
        1.20 - Remove instance_id, add instance argument to
               post_live_migration_at_destination()
        1.21 - Remove instance_uuid, add instance argument to
               power_off_instance() and stop_instance()
        1.22 - Remove instance_uuid, add instance argument to
               power_on_instance() and start_instance()
        1.23 - Remove instance_id, add instance argument to
               pre_live_migration()
        1.24 - Remove instance_uuid, add instance argument to
               rebuild_instance()
        1.25 - Remove instance_uuid, add instance argument to
               remove_fixed_ip_from_instance()
        1.26 - Remove instance_id, add instance argument to
               remove_volume_connection()
        1.27 - Remove instance_uuid, add instance argument to
               rescue_instance()
        1.28 - Remove instance_uuid, add instance argument to reset_network()
        1.29 - Remove instance_uuid, add instance argument to resize_instance()
        1.30 - Remove instance_uuid, add instance argument to resume_instance()
        1.31 - Remove instance_uuid, add instance argument to revert_resize()
        1.32 - Remove instance_id, add instance argument to
               rollback_live_migration_at_destination()
        1.33 - Remove instance_uuid, add instance argument to
               set_admin_password()
        1.34 - Remove instance_uuid, add instance argument to
               snapshot_instance()
        1.35 - Remove instance_uuid, add instance argument to
               unrescue_instance()
        1.36 - Remove instance_uuid, add instance argument to
               change_instance_metadata()
        1.37 - Remove instance_uuid, add instance argument to
               terminate_instance()
        1.38 - Changes to prep_resize():
                - remove instance_uuid, add instance
                - remove instance_type_id, add instance_type
                - remove topic, it was unused
        1.39 - Remove instance_uuid, add instance argument to run_instance()
        1.40 - Remove instance_id, add instance argument to live_migration()
        1.41 - Adds refresh_instance_security_rules()
        1.42 - Add reservations arg to prep_resize(), resize_instance(),
               finish_resize(), confirm_resize(), revert_resize() and
               finish_revert_resize()
        1.43 - Add migrate_data to live_migration()
        1.44 - Adds reserve_block_device_name()

        2.0 - Remove 1.x backwards compat
        2.1 - Adds orig_sys_metadata to rebuild_instance()
        2.2 - Adds slave_info parameter to add_aggregate_host() and
              remove_aggregate_host()
        2.3 - Adds volume_id to reserve_block_device_name()
        2.4 - Add bdms to terminate_instance
        2.5 - Add block device and network info to reboot_instance
        2.6 - Remove migration_id, add migration to resize_instance
        2.7 - Remove migration_id, add migration to confirm_resize
        2.8 - Remove migration_id, add migration to finish_resize
        2.9 - Add publish_service_capabilities()
        2.10 - Adds filter_properties and request_spec to prep_resize()
        2.11 - Adds soft_delete_instance() and restore_instance()
        2.12 - Remove migration_id, add migration to revert_resize
        2.13 - Remove migration_id, add migration to finish_revert_resize
        2.14 - Remove aggregate_id, add aggregate to add_aggregate_host
        2.15 - Remove aggregate_id, add aggregate to remove_aggregate_host
        2.16 - Add instance_type to resize_instance
        2.17 - Add get_backdoor_port()
        2.18 - Add bdms to rebuild_instance
        2.19 - Add node to run_instance
        2.20 - Add node to prep_resize
        2.21 - Add migrate_data dict param to pre_live_migration()
        2.22 - Add recreate, on_shared_storage and host arguments to
               rebuild_instance()
        2.23 - Remove network_info from reboot_instance
        2.24 - Added get_spice_console method
        2.25 - Add attach_interface() and detach_interface()
        2.26 - Add validate_console_port to ensure the service connects to
               vnc on the correct port
        2.27 - Adds 'reservations' to terminate_instance() and
               soft_delete_instance()

        ... Grizzly supports message version 2.27.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 2.27.

        2.28 - Adds check_instance_shared_storage()
        2.29 - Made start_instance() and stop_instance() take new-world
               instance objects
        2.30 - Adds live_snapshot_instance()
        2.31 - Adds shelve_instance(), shelve_offload_instance, and
               unshelve_instance()
        2.32 - Make reboot_instance take a new world instance object
        2.33 - Made suspend_instance() and resume_instance() take new-world
               instance objects
        2.34 - Added swap_volume()
        2.35 - Made terminate_instance() and soft_delete_instance() take
               new-world instance objects
        2.36 - Made pause_instance() and unpause_instance() take new-world
               instance objects
        2.37 - Added the leagacy_bdm_in_spec parameter to run_instance
    '''

    #
    # NOTE(russellb): This is the default minimum version that the server
    # (manager) side must implement unless otherwise specified using a version
    # argument to self.call()/cast()/etc. here.  It should be left as X.0 where
    # X is the current major API version (1.0, 2.0, ...).  For more information
    # about rpc API versioning, see the docs in
    # openstack/common/rpc/dispatcher.py.
    #
    BASE_RPC_API_VERSION = '2.0'

    VERSION_ALIASES = {
        'grizzly': '2.27',
    }

    def __init__(self):
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.compute,
                                               CONF.upgrade_levels.compute)
        super(ComputeAPI, self).__init__(
                topic=CONF.compute_topic,
                default_version=self.BASE_RPC_API_VERSION,
                serializer=objects_base.NovaObjectSerializer(),
                version_cap=version_cap)

    def add_aggregate_host(self, ctxt, aggregate, host_param, host,
                           slave_info=None):
        '''Add aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''

        aggregate_p = jsonutils.to_primitive(aggregate)
        self.cast(ctxt, self.make_msg('add_aggregate_host',
                aggregate=aggregate_p, host=host_param,
                slave_info=slave_info),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='2.14')

    def add_fixed_ip_to_instance(self, ctxt, instance, network_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('add_fixed_ip_to_instance',
                instance=instance_p, network_id=network_id),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def attach_interface(self, ctxt, instance, network_id, port_id,
                         requested_ip):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('attach_interface',
                 instance=instance_p, network_id=network_id,
                 port_id=port_id, requested_ip=requested_ip),
                 topic=_compute_topic(self.topic, ctxt, None, instance),
                 version='2.25')

    def attach_volume(self, ctxt, instance, volume_id, mountpoint):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('attach_volume',
                instance=instance_p, volume_id=volume_id,
                mountpoint=mountpoint),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def change_instance_metadata(self, ctxt, instance, diff):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('change_instance_metadata',
                  instance=instance_p, diff=diff),
                  topic=_compute_topic(self.topic, ctxt, None, instance))

    def check_can_live_migrate_destination(self, ctxt, instance, destination,
                                           block_migration, disk_over_commit):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt,
                         self.make_msg('check_can_live_migrate_destination',
                                       instance=instance_p,
                                       block_migration=block_migration,
                                       disk_over_commit=disk_over_commit),
                         topic=_compute_topic(self.topic,
                                              ctxt, destination, None))

    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('check_can_live_migrate_source',
                                             instance=instance_p,
                                             dest_check_data=dest_check_data),
                         topic=_compute_topic(self.topic, ctxt, None,
                                              instance))

    def check_instance_shared_storage(self, ctxt, instance, data):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('check_instance_shared_storage',
                                             instance=instance_p,
                                             data=data),
                         topic=_compute_topic(self.topic, ctxt, None,
                                              instance),
                         version='2.28')

    def confirm_resize(self, ctxt, instance, migration, host,
            reservations=None, cast=True):
        rpc_method = self.cast if cast else self.call
        instance_p = jsonutils.to_primitive(instance)
        migration_p = jsonutils.to_primitive(migration)
        return rpc_method(ctxt, self.make_msg('confirm_resize',
                instance=instance_p, migration=migration_p,
                reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, host, instance),
                version='2.7')

    def detach_interface(self, ctxt, instance, port_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('detach_interface',
                 instance=instance_p, port_id=port_id),
                 topic=_compute_topic(self.topic, ctxt, None, instance),
                 version='2.25')

    def detach_volume(self, ctxt, instance, volume_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('detach_volume',
                instance=instance_p, volume_id=volume_id),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def finish_resize(self, ctxt, instance, migration, image, disk_info,
            host, reservations=None):
        instance_p = jsonutils.to_primitive(instance)
        migration_p = jsonutils.to_primitive(migration)
        self.cast(ctxt, self.make_msg('finish_resize',
                instance=instance_p, migration=migration_p,
                image=image, disk_info=disk_info, reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='2.8')

    def finish_revert_resize(self, ctxt, instance, migration, host,
                             reservations=None):
        instance_p = jsonutils.to_primitive(instance)
        migration_p = jsonutils.to_primitive(migration)
        self.cast(ctxt, self.make_msg('finish_revert_resize',
                instance=instance_p, migration=migration_p,
                reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='2.13')

    def get_console_output(self, ctxt, instance, tail_length):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_console_output',
                instance=instance_p, tail_length=tail_length),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def get_console_pool_info(self, ctxt, console_type, host):
        return self.call(ctxt, self.make_msg('get_console_pool_info',
                console_type=console_type),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def get_console_topic(self, ctxt, host):
        return self.call(ctxt, self.make_msg('get_console_topic'),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def get_diagnostics(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_diagnostics',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def get_vnc_console(self, ctxt, instance, console_type):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_vnc_console',
                instance=instance_p, console_type=console_type),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def get_spice_console(self, ctxt, instance, console_type):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_spice_console',
                instance=instance_p, console_type=console_type),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                         version='2.24')

    def validate_console_port(self, ctxt, instance, port, console_type):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('validate_console_port',
                instance=instance_p, port=port, console_type=console_type),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.26')

    def host_maintenance_mode(self, ctxt, host_param, mode, host):
        '''Set host maintenance mode

        :param ctxt: request context
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param mode:
        :param host: This is the host to send the message to.
        '''
        return self.call(ctxt, self.make_msg('host_maintenance_mode',
                host=host_param, mode=mode),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def host_power_action(self, ctxt, action, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('host_power_action',
                action=action), topic)

    def inject_file(self, ctxt, instance, path, file_contents):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('inject_file',
                instance=instance_p, path=path,
                file_contents=file_contents),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def inject_network_info(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('inject_network_info',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def live_migration(self, ctxt, instance, dest, block_migration, host,
                       migrate_data=None):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('live_migration', instance=instance_p,
                dest=dest, block_migration=block_migration,
                migrate_data=migrate_data),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def pause_instance(self, ctxt, instance):
        if self.can_send_version('2.36'):
            version = '2.36'
        else:
            version = '2.0'
            instance = jsonutils.to_primitive(
                    objects_base.obj_to_primitive(instance))
        self.cast(ctxt, self.make_msg('pause_instance',
                instance=instance),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version=version)

    def post_live_migration_at_destination(self, ctxt, instance,
            block_migration, host):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt,
                self.make_msg('post_live_migration_at_destination',
                instance=instance_p, block_migration=block_migration),
                _compute_topic(self.topic, ctxt, host, None))

    def power_off_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('power_off_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def power_on_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('power_on_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def pre_live_migration(self, ctxt, instance, block_migration, disk,
            host, migrate_data=None):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('pre_live_migration',
                        instance=instance_p,
                        block_migration=block_migration,
                        disk=disk, migrate_data=migrate_data),
                        _compute_topic(self.topic, ctxt, host, None),
                        version='2.21')

    def prep_resize(self, ctxt, image, instance, instance_type, host,
                    reservations=None, request_spec=None,
                    filter_properties=None, node=None):
        instance_p = jsonutils.to_primitive(instance)
        instance_type_p = jsonutils.to_primitive(instance_type)
        image_p = jsonutils.to_primitive(image)
        self.cast(ctxt, self.make_msg('prep_resize',
                instance=instance_p, instance_type=instance_type_p,
                image=image_p, reservations=reservations,
                request_spec=request_spec,
                filter_properties=filter_properties,
                node=node),
                _compute_topic(self.topic, ctxt, host, None),
                version='2.20')

    def reboot_instance(self, ctxt, instance, block_device_info,
                        reboot_type):
        if not self.can_send_version('2.32'):
            version = '2.23'
            instance = jsonutils.to_primitive(
                objects_base.obj_to_primitive(instance))
        else:
            version = '2.32'
        self.cast(ctxt, self.make_msg('reboot_instance',
                instance=instance,
                block_device_info=block_device_info,
                reboot_type=reboot_type),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version=version)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref, orig_sys_metadata, bdms,
            recreate=False, on_shared_storage=False, host=None):
        instance_p = jsonutils.to_primitive(instance)
        bdms_p = jsonutils.to_primitive(bdms)
        self.cast(ctxt, self.make_msg('rebuild_instance',
                instance=instance_p, new_pass=new_pass,
                injected_files=injected_files, image_ref=image_ref,
                orig_image_ref=orig_image_ref,
                orig_sys_metadata=orig_sys_metadata, bdms=bdms_p,
                recreate=recreate, on_shared_storage=on_shared_storage),
                topic=_compute_topic(self.topic, ctxt, host, instance),
                version='2.22')

    def refresh_provider_fw_rules(self, ctxt, host):
        self.cast(ctxt, self.make_msg('refresh_provider_fw_rules'),
                _compute_topic(self.topic, ctxt, host, None))

    def remove_aggregate_host(self, ctxt, aggregate, host_param, host,
                              slave_info=None):
        '''Remove aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''

        aggregate_p = jsonutils.to_primitive(aggregate)
        self.cast(ctxt, self.make_msg('remove_aggregate_host',
                aggregate=aggregate_p, host=host_param,
                slave_info=slave_info),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='2.15')

    def remove_fixed_ip_from_instance(self, ctxt, instance, address):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('remove_fixed_ip_from_instance',
                instance=instance_p, address=address),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def remove_volume_connection(self, ctxt, instance, volume_id, host):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('remove_volume_connection',
                instance=instance_p, volume_id=volume_id),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def rescue_instance(self, ctxt, instance, rescue_password):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('rescue_instance',
                instance=instance_p,
                rescue_password=rescue_password),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def reset_network(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('reset_network',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def resize_instance(self, ctxt, instance, migration, image, instance_type,
                        reservations=None):
        topic = _compute_topic(self.topic, ctxt, None, instance)
        instance_p = jsonutils.to_primitive(instance)
        migration_p = jsonutils.to_primitive(migration)
        instance_type_p = jsonutils.to_primitive(instance_type)
        self.cast(ctxt, self.make_msg('resize_instance',
                instance=instance_p, migration=migration_p,
                image=image, reservations=reservations,
                instance_type=instance_type_p), topic,
                version='2.16')

    def resume_instance(self, ctxt, instance):
        if self.can_send_version('2.33'):
            version = '2.33'
        else:
            version = '2.0'
            instance = jsonutils.to_primitive(
                    objects_base.obj_to_primitive(instance))
        self.cast(ctxt, self.make_msg('resume_instance',
                                      instance=instance),
                  topic=_compute_topic(self.topic, ctxt, None, instance),
                  version=version)

    def revert_resize(self, ctxt, instance, migration, host,
                      reservations=None):
        instance_p = jsonutils.to_primitive(instance)
        migration_p = jsonutils.to_primitive(migration)
        self.cast(ctxt, self.make_msg('revert_resize',
                instance=instance_p, migration=migration_p,
                reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, host, instance),
                version='2.12')

    def rollback_live_migration_at_destination(self, ctxt, instance, host):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('rollback_live_migration_at_destination',
            instance=instance_p),
            topic=_compute_topic(self.topic, ctxt, host, None))

    def run_instance(self, ctxt, instance, host, request_spec,
                     filter_properties, requested_networks,
                     injected_files, admin_password,
                     is_first_time, node=None, legacy_bdm_in_spec=True):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('run_instance', instance=instance_p,
                request_spec=request_spec, filter_properties=filter_properties,
                requested_networks=requested_networks,
                injected_files=injected_files, admin_password=admin_password,
                is_first_time=is_first_time, node=node,
                legacy_bdm_in_spec=legacy_bdm_in_spec),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='2.37')

    def set_admin_password(self, ctxt, instance, new_pass):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('set_admin_password',
                instance=instance_p, new_pass=new_pass),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def set_host_enabled(self, ctxt, enabled, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('set_host_enabled',
                enabled=enabled), topic)

    def swap_volume(self, ctxt, instance, old_volume_id, new_volume_id):
        self.cast(ctxt, self.make_msg('swap_volume',
                instance=instance, old_volume_id=old_volume_id,
                new_volume_id=new_volume_id),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.34')

    def get_host_uptime(self, ctxt, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('get_host_uptime'), topic)

    def reserve_block_device_name(self, ctxt, instance, device, volume_id):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('reserve_block_device_name',
                instance=instance_p, device=device, volume_id=volume_id),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.3')

    def live_snapshot_instance(self, ctxt, instance, image_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('live_snapshot_instance',
                instance=instance_p, image_id=image_id),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.30')

    def snapshot_instance(self, ctxt, instance, image_id, image_type,
            backup_type=None, rotation=None):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('snapshot_instance',
                instance=instance_p, image_id=image_id,
                image_type=image_type, backup_type=backup_type,
                rotation=rotation),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def start_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('start_instance',
                instance=instance),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.29')

    def stop_instance(self, ctxt, instance, do_cast=True):
        rpc_method = self.cast if do_cast else self.call
        return rpc_method(ctxt, self.make_msg('stop_instance',
                instance=instance),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='2.29')

    def suspend_instance(self, ctxt, instance):
        if self.can_send_version('2.33'):
            version = '2.33'
        else:
            version = '2.0'
            instance = jsonutils.to_primitive(
                    objects_base.obj_to_primitive(instance))
        self.cast(ctxt, self.make_msg('suspend_instance',
                                      instance=instance),
                  topic=_compute_topic(self.topic, ctxt, None, instance),
                  version=version)

    def terminate_instance(self, ctxt, instance, bdms, reservations=None):
        if self.can_send_version('2.35'):
            version = '2.35'
        else:
            version = '2.27'
            instance = jsonutils.to_primitive(instance)
        bdms_p = jsonutils.to_primitive(bdms)
        self.cast(ctxt, self.make_msg('terminate_instance',
                instance=instance, bdms=bdms_p,
                reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version=version)

    def unpause_instance(self, ctxt, instance):
        if self.can_send_version('2.36'):
            version = '2.36'
        else:
            version = '2.0'
            instance = jsonutils.to_primitive(
                    objects_base.obj_to_primitive(instance))
        self.cast(ctxt, self.make_msg('unpause_instance',
                instance=instance),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version=version)

    def unrescue_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('unrescue_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def publish_service_capabilities(self, ctxt):
        self.fanout_cast(ctxt, self.make_msg('publish_service_capabilities'))

    def soft_delete_instance(self, ctxt, instance, reservations=None):
        if self.can_send_version('2.35'):
            version = '2.35'
        else:
            version = '2.27'
            instance = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('soft_delete_instance',
                instance=instance, reservations=reservations),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version=version)

    def restore_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('restore_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance))

    def shelve_instance(self, ctxt, instance, image_id=None):
        self.cast(ctxt, self.make_msg('shelve_instance',
            instance=instance, image_id=image_id),
            topic=_compute_topic(self.topic, ctxt, None, instance),
            version='2.31')

    def shelve_offload_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('shelve_offload_instance',
            instance=instance),
            topic=_compute_topic(self.topic, ctxt, None, instance),
            version='2.31')

    def unshelve_instance(self, ctxt, instance, host, image=None):
        self.cast(ctxt, self.make_msg('unshelve_instance',
            instance=instance, image=image),
            topic=_compute_topic(self.topic, ctxt, host, None),
            version='2.31')


class SecurityGroupAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the security group rpc API.

    API version history:

        1.0 - Initial version.
        1.41 - Adds refresh_instance_security_rules()

        2.0 - Remove 1.x backwards compat
    '''

    #
    # NOTE(russellb): This is the default minimum version that the server
    # (manager) side must implement unless otherwise specified using a version
    # argument to self.call()/cast()/etc. here.  It should be left as X.0 where
    # X is the current major API version (1.0, 2.0, ...).  For more information
    # about rpc API versioning, see the docs in
    # openstack/common/rpc/dispatcher.py.
    #
    BASE_RPC_API_VERSION = '2.0'

    def __init__(self):
        super(SecurityGroupAPI, self).__init__(
                topic=CONF.compute_topic,
                default_version=self.BASE_RPC_API_VERSION)

    def refresh_security_group_rules(self, ctxt, security_group_id, host):
        self.cast(ctxt, self.make_msg('refresh_security_group_rules',
                security_group_id=security_group_id),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def refresh_security_group_members(self, ctxt, security_group_id,
            host):
        self.cast(ctxt, self.make_msg('refresh_security_group_members',
                security_group_id=security_group_id),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def refresh_instance_security_rules(self, ctxt, host, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('refresh_instance_security_rules',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, instance['host'],
                instance))
