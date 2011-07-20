# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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

"""VMRC Console Manager."""

from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils
from nova.virt import vmwareapi_conn


LOG = logging.getLogger("nova.console.vmrc_manager")


FLAGS = flags.FLAGS
flags.DEFINE_string('console_public_hostname', '',
                    'Publicly visible name for this console host')
flags.DEFINE_string('console_driver', 'nova.console.vmrc.VMRCConsole',
                    'Driver to use for the console')


class ConsoleVMRCManager(manager.Manager):
    """Manager to handle VMRC connections for accessing instance consoles."""

    def __init__(self, console_driver=None, *args, **kwargs):
        self.driver = utils.import_object(FLAGS.console_driver)
        super(ConsoleVMRCManager, self).__init__(*args, **kwargs)

    def init_host(self):
        self.sessions = {}
        self.driver.init_host()

    def _get_vim_session(self, pool):
        """Get VIM session for the pool specified."""
        vim_session = None
        if pool['id'] not in self.sessions.keys():
            vim_session = vmwareapi_conn.VMWareAPISession(
                    pool['address'],
                    pool['username'],
                    pool['password'],
                    FLAGS.console_vmrc_error_retries)
            self.sessions[pool['id']] = vim_session
        return self.sessions[pool['id']]

    def _generate_console(self, context, pool, name, instance_id, instance):
        """Sets up console for the instance."""
        LOG.debug(_('Adding console'))

        password = self.driver.generate_password(
                        self._get_vim_session(pool),
                        pool,
                        instance.name)

        console_data = {'instance_name': name,
                        'instance_id': instance_id,
                        'password': password,
                        'pool_id': pool['id']}
        console_data['port'] = self.driver.get_port(context)
        console = self.db.console_create(context, console_data)
        self.driver.setup_console(context, console)
        return console

    @exception.wrap_exception()
    def add_console(self, context, instance_id, password=None,
                    port=None, **kwargs):
        """Adds a console for the instance.

        If it is one time password, then we generate new console credentials.

        """
        instance = self.db.instance_get(context, instance_id)
        host = instance['host']
        name = instance['name']
        pool = self.get_pool_for_instance_host(context, host)
        try:
            console = self.db.console_get_by_pool_instance(context,
                                                      pool['id'],
                                                      instance_id)
            if self.driver.is_otp():
                console = self._generate_console(context,
                                                 pool,
                                                 name,
                                                 instance_id,
                                                 instance)
        except exception.NotFound:
            console = self._generate_console(context,
                                             pool,
                                             name,
                                             instance_id,
                                             instance)
        return console['id']

    @exception.wrap_exception()
    def remove_console(self, context, console_id, **_kwargs):
        """Removes a console entry."""
        try:
            console = self.db.console_get(context, console_id)
        except exception.NotFound:
            LOG.debug(_('Tried to remove non-existent console '
                        '%(console_id)s.') % {'console_id': console_id})
            return
        LOG.debug(_('Removing console '
                    '%(console_id)s.') % {'console_id': console_id})
        self.db.console_delete(context, console_id)
        self.driver.teardown_console(context, console)

    def get_pool_for_instance_host(self, context, instance_host):
        """Gets console pool info for the instance."""
        context = context.elevated()
        console_type = self.driver.console_type
        try:
            pool = self.db.console_pool_get_by_host_type(context,
                                                         instance_host,
                                                         self.host,
                                                         console_type)
        except exception.NotFound:
            pool_info = rpc.call(context,
                                 self.db.queue_get_for(context,
                                                       FLAGS.compute_topic,
                                                       instance_host),
                                 {'method': 'get_console_pool_info',
                                  'args': {'console_type': console_type}})
            pool_info['password'] = self.driver.fix_pool_password(
                                                    pool_info['password'])
            pool_info['host'] = self.host
            # ESX Address or Proxy Address
            public_host_name = pool_info['address']
            if FLAGS.console_public_hostname:
                public_host_name = FLAGS.console_public_hostname
            pool_info['public_hostname'] = public_host_name
            pool_info['console_type'] = console_type
            pool_info['compute_host'] = instance_host
            pool = self.db.console_pool_create(context, pool_info)
        return pool
