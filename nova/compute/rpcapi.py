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

from nova import exception
from nova import flags
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
import nova.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


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
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(ComputeAPI, self).__init__(
                topic=FLAGS.compute_topic,
                default_version=self.BASE_RPC_API_VERSION)

    def add_aggregate_host(self, ctxt, aggregate_id, host_param, host):
        '''Add aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        self.cast(ctxt, self.make_msg('add_aggregate_host',
                aggregate_id=aggregate_id, host=host_param),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def add_fixed_ip_to_instance(self, ctxt, instance, network_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('add_fixed_ip_to_instance',
                instance=instance_p, network_id=network_id),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.8')

    def attach_volume(self, ctxt, instance, volume_id, mountpoint):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('attach_volume',
                instance=instance_p, volume_id=volume_id,
                mountpoint=mountpoint),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.9')

    def change_instance_metadata(self, ctxt, instance, diff):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('change_instance_metadata',
                  instance=instance_p, diff=diff),
                  topic=_compute_topic(self.topic, ctxt, None, instance),
                  version='1.36')

    def check_can_live_migrate_destination(self, ctxt, instance, destination,
            block_migration, disk_over_commit):
        instance_p = jsonutils.to_primitive(instance)
        self.call(ctxt, self.make_msg('check_can_live_migrate_destination',
                           instance=instance_p,
                           block_migration=block_migration,
                           disk_over_commit=disk_over_commit),
                  topic=_compute_topic(self.topic, ctxt, destination, None),
                  version='1.10')

    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        instance_p = jsonutils.to_primitive(instance)
        self.call(ctxt, self.make_msg('check_can_live_migrate_source',
                           instance=instance_p,
                           dest_check_data=dest_check_data),
                  topic=_compute_topic(self.topic, ctxt, None, instance),
                  version='1.11')

    def confirm_resize(self, ctxt, instance, migration_id, host,
            cast=True):
        rpc_method = self.cast if cast else self.call
        instance_p = jsonutils.to_primitive(instance)
        return rpc_method(ctxt, self.make_msg('confirm_resize',
                instance=instance_p, migration_id=migration_id),
                topic=_compute_topic(self.topic, ctxt, host, instance),
                version='1.12')

    def detach_volume(self, ctxt, instance, volume_id):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('detach_volume',
                instance=instance_p, volume_id=volume_id),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.13')

    def finish_resize(self, ctxt, instance, migration_id, image, disk_info,
            host):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('finish_resize',
                instance=instance_p, migration_id=migration_id,
                image=image, disk_info=disk_info),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='1.14')

    def finish_revert_resize(self, ctxt, instance, migration_id, host):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('finish_revert_resize',
                instance=instance_p, migration_id=migration_id),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='1.15')

    def get_console_output(self, ctxt, instance, tail_length):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_console_output',
                instance=instance_p, tail_length=tail_length),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.7')

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
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.16')

    def get_vnc_console(self, ctxt, instance, console_type):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('get_vnc_console',
                instance=instance_p, console_type=console_type),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.17')

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
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.18')

    def inject_network_info(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('inject_network_info',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.19')

    def pause_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('pause_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.5')

    def post_live_migration_at_destination(self, ctxt, instance,
            block_migration, host):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt,
                self.make_msg('post_live_migration_at_destination',
                instance=instance_p, block_migration=block_migration),
                _compute_topic(self.topic, ctxt, host, None),
                version='1.20')

    def power_off_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('power_off_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.21')

    def power_on_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('power_on_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.22')

    def pre_live_migration(self, ctxt, instance, block_migration, disk,
            host):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('pre_live_migration',
                instance=instance_p, block_migration=block_migration,
                disk=disk), _compute_topic(self.topic, ctxt, host, None),
                version='1.23')

    def prep_resize(self, ctxt, image, instance, instance_type, host):
        instance_p = jsonutils.to_primitive(instance)
        instance_type_p = jsonutils.to_primitive(instance_type)
        self.cast(ctxt, self.make_msg('prep_resize',
                instance=instance_p, instance_type=instance_type_p,
                image=image), _compute_topic(self.topic, ctxt, host, None),
                version='1.38')

    def reboot_instance(self, ctxt, instance, reboot_type):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('reboot_instance',
                instance=instance_p, reboot_type=reboot_type),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.4')

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('rebuild_instance',
                instance=instance_p, new_pass=new_pass,
                injected_files=injected_files, image_ref=image_ref,
                orig_image_ref=orig_image_ref),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.24')

    def refresh_provider_fw_rules(self, ctxt, host):
        self.cast(ctxt, self.make_msg('refresh_provider_fw_rules'),
                _compute_topic(self.topic, ctxt, host, None))

    def refresh_security_group_rules(self, ctxt, security_group_id, host):
        self.cast(ctxt, self.make_msg('refresh_security_group_rules',
                security_group_id=security_group_id),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def refresh_security_group_members(self, ctxt, security_group_id,
            host):
        self.cast(ctxt, self.make_msg('refresh_security_group_members',
                security_group_id=security_group_id),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def remove_aggregate_host(self, ctxt, aggregate_id, host_param, host):
        '''Remove aggregate host.

        :param ctxt: request context
        :param aggregate_id:
        :param host_param: This value is placed in the message to be the 'host'
                           parameter for the remote method.
        :param host: This is the host to send the message to.
        '''
        self.cast(ctxt, self.make_msg('remove_aggregate_host',
                aggregate_id=aggregate_id, host=host_param),
                topic=_compute_topic(self.topic, ctxt, host, None))

    def remove_fixed_ip_from_instance(self, ctxt, instance, address):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('remove_fixed_ip_from_instance',
                instance=instance_p, address=address),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.25')

    def remove_volume_connection(self, ctxt, instance, volume_id, host):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('remove_volume_connection',
                instance=instance_p, volume_id=volume_id),
                topic=_compute_topic(self.topic, ctxt, host, None),
                version='1.26')

    def rescue_instance(self, ctxt, instance, rescue_password):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('rescue_instance',
                instance=instance_p,
                rescue_password=rescue_password),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.27')

    def reset_network(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('reset_network',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.28')

    def resize_instance(self, ctxt, instance, migration_id, image):
        topic = _compute_topic(self.topic, ctxt, None, instance)
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('resize_instance',
                instance=instance_p, migration_id=migration_id,
                image=image), topic, version='1.29')

    def resume_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('resume_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.30')

    def revert_resize(self, ctxt, instance, migration_id, host):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('revert_resize',
                instance=instance_p, migration_id=migration_id),
                topic=_compute_topic(self.topic, ctxt, host, instance),
                version='1.31')

    def rollback_live_migration_at_destination(self, ctxt, instance, host):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('rollback_live_migration_at_destination',
            instance=instance_p),
            topic=_compute_topic(self.topic, ctxt, host, None),
            version='1.32')

    def set_admin_password(self, ctxt, instance, new_pass):
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('set_admin_password',
                instance=instance_p, new_pass=new_pass),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.33')

    def set_host_enabled(self, ctxt, enabled, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('set_host_enabled',
                enabled=enabled), topic)

    def get_host_uptime(self, ctxt, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('get_host_uptime'), topic,
                version='1.1')

    def snapshot_instance(self, ctxt, instance, image_id, image_type,
            backup_type, rotation):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('snapshot_instance',
                instance=instance_p, image_id=image_id,
                image_type=image_type, backup_type=backup_type,
                rotation=rotation),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.34')

    def start_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('start_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.22')

    def stop_instance(self, ctxt, instance, cast=True):
        rpc_method = self.cast if cast else self.call
        instance_p = jsonutils.to_primitive(instance)
        return rpc_method(ctxt, self.make_msg('stop_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.21')

    def suspend_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('suspend_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.6')

    def terminate_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('terminate_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.37')

    def unpause_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('unpause_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.5')

    def unrescue_instance(self, ctxt, instance):
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('unrescue_instance',
                instance=instance_p),
                topic=_compute_topic(self.topic, ctxt, None, instance),
                version='1.35')


class SecurityGroupAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the security group rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(SecurityGroupAPI, self).__init__(
                topic=FLAGS.compute_topic,
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
