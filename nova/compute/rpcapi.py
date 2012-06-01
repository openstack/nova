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
from nova import rpc
import nova.rpc.proxy


FLAGS = flags.FLAGS


class ComputeAPI(nova.rpc.proxy.RpcProxy):
    '''Client side of the compute rpc API.

    API version history:

        1.0 - Initial version.
    '''

    RPC_API_VERSION = '1.0'

    def __init__(self):
        super(ComputeAPI, self).__init__(topic=FLAGS.compute_topic,
                                         default_version=self.RPC_API_VERSION)

    def _compute_topic(self, ctxt, host, instance):
        '''Get the topic to use for a message.

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
        return rpc.queue_get_for(ctxt, self.topic, host)

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
                topic=self._compute_topic(ctxt, host, None))

    def add_fixed_ip_to_instance(self, ctxt, instance, network_id):
        self.cast(ctxt, self.make_msg('add_fixed_ip_to_instance',
                instance_uuid=instance['uuid'], network_id=network_id),
                topic=self._compute_topic(ctxt, None, instance))

    def attach_volume(self, ctxt, instance, volume_id, mountpoint):
        self.cast(ctxt, self.make_msg('attach_volume',
                instance_uuid=instance['uuid'], volume_id=volume_id,
                mountpoint=mountpoint),
                topic=self._compute_topic(ctxt, None, instance))

    def confirm_resize(self, ctxt, instance, migration_id, host,
            cast=True):
        rpc_method = self.cast if cast else self.call
        return rpc_method(ctxt, self.make_msg('confirm_resize',
                instance_uuid=instance['uuid'], migration_id=migration_id),
                topic=self._compute_topic(ctxt, host, instance))

    def detach_volume(self, ctxt, instance, volume_id):
        self.cast(ctxt, self.make_msg('detach_volume',
                instance_uuid=instance['uuid'], volume_id=volume_id),
                topic=self._compute_topic(ctxt, None, instance))

    def get_console_output(self, ctxt, instance, tail_length):
        return self.call(ctxt, self.make_msg('get_console_output',
                instance_uuid=instance['uuid'], tail_length=tail_length),
                topic=self._compute_topic(ctxt, None, instance))

    def get_console_pool_info(self, ctxt, console_type, host):
        return self.call(ctxt, self.make_msg('get_console_pool_info',
                console_type=console_type),
                topic=self._compute_topic(ctxt, host, None))

    def get_diagnostics(self, ctxt, instance):
        return self.call(ctxt, self.make_msg('get_diagnostics',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def get_vnc_console(self, ctxt, instance, console_type):
        return self.call(ctxt, self.make_msg('get_vnc_console',
                instance_uuid=instance['uuid'], console_type=console_type),
                topic=self._compute_topic(ctxt, None, instance))

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
                topic=self._compute_topic(ctxt, host, None))

    def host_power_action(self, ctxt, action, host):
        return self.call(ctxt, self.make_msg('host_power_action',
                action=action), topic=self._compute_topic(ctxt, host, None))

    def inject_file(self, ctxt, instance, path, file_contents):
        self.cast(ctxt, self.make_msg('inject_file',
                instance_uuid=instance['uuid'], path=path,
                file_contents=file_contents),
                topic=self._compute_topic(ctxt, None, instance))

    def inject_network_info(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('inject_network_info',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def lock_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('lock_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def pause_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('pause_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def power_off_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('power_off_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def power_on_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('power_on_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def reboot_instance(self, ctxt, instance, reboot_type):
        self.cast(ctxt, self.make_msg('reboot_instance',
                instance_uuid=instance['uuid'], reboot_type=reboot_type),
                topic=self._compute_topic(ctxt, None, instance))

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref):
        self.cast(ctxt, self.make_msg('rebuild_instance',
                instance_uuid=instance['uuid'], new_pass=new_pass,
                injected_files=injected_files, image_ref=image_ref,
                orig_image_ref=orig_image_ref),
                topic=self._compute_topic(ctxt, None, instance))

    def refresh_security_group_rules(self, ctxt, security_group_id, host):
        self.cast(ctxt, self.make_msg('refresh_security_group_rules',
                security_group_id=security_group_id),
                topic=self._compute_topic(ctxt, host, None))

    def refresh_security_group_members(self, ctxt, security_group_id,
            host):
        self.cast(ctxt, self.make_msg('refresh_security_group_members',
                security_group_id=security_group_id),
                topic=self._compute_topic(ctxt, host, None))

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
                topic=self._compute_topic(ctxt, host, None))

    def remove_fixed_ip_from_instance(self, ctxt, instance, address):
        self.cast(ctxt, self.make_msg('remove_fixed_ip_from_instance',
                instance_uuid=instance['uuid'], address=address),
                topic=self._compute_topic(ctxt, None, instance))

    def rescue_instance(self, ctxt, instance, rescue_password):
        self.cast(ctxt, self.make_msg('rescue_instance',
                instance_uuid=instance['uuid'],
                rescue_password=rescue_password),
                topic=self._compute_topic(ctxt, None, instance))

    def reset_network(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('reset_network',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def resume_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('resume_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def revert_resize(self, ctxt, instance, migration_id, host):
        self.cast(ctxt, self.make_msg('revert_resize',
                instance_uuid=instance['uuid'], migration_id=migration_id),
                topic=self._compute_topic(ctxt, host, instance))

    def set_admin_password(self, ctxt, instance, new_pass):
        self.cast(ctxt, self.make_msg('set_admin_password',
                instance_uuid=instance['uuid'], new_pass=new_pass),
                topic=self._compute_topic(ctxt, None, instance))

    def set_host_enabled(self, ctxt, enabled, host):
        return self.call(ctxt, self.make_msg('set_host_enabled',
                enabled=enabled), topic=self._compute_topic(ctxt, host, None))

    def snapshot_instance(self, ctxt, instance, image_id, image_type,
            backup_type, rotation):
        self.cast(ctxt, self.make_msg('snapshot_instance',
                instance_uuid=instance['uuid'], image_id=image_id,
                image_type=image_type, backup_type=backup_type,
                rotation=rotation),
                topic=self._compute_topic(ctxt, None, instance))

    def start_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('start_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def stop_instance(self, ctxt, instance, cast=True):
        rpc_method = self.cast if cast else self.call
        return rpc_method(ctxt, self.make_msg('stop_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def suspend_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('suspend_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def terminate_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('terminate_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def unlock_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('unlock_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def unpause_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('unpause_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))

    def unrescue_instance(self, ctxt, instance):
        self.cast(ctxt, self.make_msg('unrescue_instance',
                instance_uuid=instance['uuid']),
                topic=self._compute_topic(ctxt, None, instance))
