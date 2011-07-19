# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
# All Rights Reserved.
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

"""Console Proxy Service."""

import functools
import socket

from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('console_driver',
                    'nova.console.xvp.XVPConsoleProxy',
                    'Driver to use for the console proxy')
flags.DEFINE_boolean('stub_compute', False,
                     'Stub calls to compute worker for tests')
flags.DEFINE_string('console_public_hostname',
                    socket.gethostname(),
                    'Publicly visable name for this console host')


class ConsoleProxyManager(manager.Manager):
    """Sets up and tears down any console proxy connections.

    Needed for accessing instance consoles securely.

    """

    def __init__(self, console_driver=None, *args, **kwargs):
        if not console_driver:
            console_driver = FLAGS.console_driver
        self.driver = utils.import_object(console_driver)
        super(ConsoleProxyManager, self).__init__(*args, **kwargs)
        self.driver.host = self.host

    def init_host(self):
        self.driver.init_host()

    @exception.wrap_exception()
    def add_console(self, context, instance_id, password=None,
                    port=None, **kwargs):
        instance = self.db.instance_get(context, instance_id)
        host = instance['host']
        name = instance['name']
        pool = self.get_pool_for_instance_host(context, host)
        try:
            console = self.db.console_get_by_pool_instance(context,
                                                      pool['id'],
                                                      instance_id)
        except exception.NotFound:
            logging.debug(_('Adding console'))
            if not password:
                password = utils.generate_password(8)
            if not port:
                port = self.driver.get_port(context)
            console_data = {'instance_name': name,
                            'instance_id': instance_id,
                            'password': password,
                            'pool_id': pool['id']}
            if port:
                console_data['port'] = port
            console = self.db.console_create(context, console_data)
            self.driver.setup_console(context, console)
        return console['id']

    @exception.wrap_exception()
    def remove_console(self, context, console_id, **_kwargs):
        try:
            console = self.db.console_get(context, console_id)
        except exception.NotFound:
            logging.debug(_('Tried to remove non-existant console '
                            '%(console_id)s.') %
                            {'console_id': console_id})
            return
        self.db.console_delete(context, console_id)
        self.driver.teardown_console(context, console)

    def get_pool_for_instance_host(self, context, instance_host):
        context = context.elevated()
        console_type = self.driver.console_type
        try:
            pool = self.db.console_pool_get_by_host_type(context,
                                                         instance_host,
                                                         self.host,
                                                         console_type)
        except exception.NotFound:
            #NOTE(mdragon): Right now, the only place this info exists is the
            #               compute worker's flagfile, at least for
            #               xenserver. Thus we ned to ask.
            if FLAGS.stub_compute:
                pool_info = {'address': '127.0.0.1',
                             'username': 'test',
                             'password': '1234pass'}
            else:
                pool_info = rpc.call(context,
                                 self.db.queue_get_for(context,
                                                   FLAGS.compute_topic,
                                                   instance_host),
                       {'method': 'get_console_pool_info',
                        'args': {'console_type': console_type}})
            pool_info['password'] = self.driver.fix_pool_password(
                                                    pool_info['password'])
            pool_info['host'] = self.host
            pool_info['public_hostname'] = FLAGS.console_public_hostname
            pool_info['console_type'] = self.driver.console_type
            pool_info['compute_host'] = instance_host
            pool = self.db.console_pool_create(context, pool_info)
        return pool
