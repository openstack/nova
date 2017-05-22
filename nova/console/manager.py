# Copyright (c) 2010 OpenStack Foundation
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

from oslo_log import log as logging
import oslo_messaging as messaging

from nova.compute import rpcapi as compute_rpcapi
import nova.conf
from nova.console import xvp
from nova import exception
from nova import manager
from nova import objects
from nova import utils


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class ConsoleProxyManager(manager.Manager):
    """Sets up and tears down any console proxy connections.

    Needed for accessing instance consoles securely.

    """

    target = messaging.Target(version='2.0')

    def __init__(self, *args, **kwargs):
        self.driver = xvp.XVPConsoleProxy()
        super(ConsoleProxyManager, self).__init__(service_name='console',
                                                  *args, **kwargs)
        self.driver.host = self.host
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def reset(self):
        LOG.info('Reloading compute RPC API')
        compute_rpcapi.LAST_VERSION = None
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def init_host(self):
        self.driver.init_host()

    def add_console(self, context, instance_id):
        instance = objects.Instance.get_by_id(context, instance_id)
        host = instance.host
        name = instance.name
        pool = self._get_pool_for_instance_host(context, host)
        try:
            console = self.db.console_get_by_pool_instance(context,
                                                           pool['id'],
                                                           instance.uuid)
        except exception.NotFound:
            LOG.debug('Adding console', instance=instance)
            password = utils.generate_password(8)
            port = self.driver.get_port(context)
            console_data = {'instance_name': name,
                            'instance_uuid': instance.uuid,
                            'password': password,
                            'pool_id': pool['id']}
            if port:
                console_data['port'] = port
            console = self.db.console_create(context, console_data)
            self.driver.setup_console(context, console)

        return console['id']

    def remove_console(self, context, console_id):
        try:
            console = self.db.console_get(context, console_id)
        except exception.NotFound:
            LOG.debug('Tried to remove non-existent console '
                      '%(console_id)s.',
                      {'console_id': console_id})
            return
        self.db.console_delete(context, console_id)
        self.driver.teardown_console(context, console)

    def _get_pool_for_instance_host(self, context, instance_host):
        context = context.elevated()
        console_type = self.driver.console_type
        try:
            pool = self.db.console_pool_get_by_host_type(context,
                                                         instance_host,
                                                         self.host,
                                                         console_type)
        except exception.NotFound:
            # NOTE(mdragon): Right now, the only place this info exists is the
            #                compute worker's flagfile, at least for
            #                xenserver. Thus we ned to ask.
            pool_info = self.compute_rpcapi.get_console_pool_info(context,
                        instance_host, console_type)
            pool_info['password'] = self.driver.fix_pool_password(
                                                    pool_info['password'])
            pool_info['host'] = self.host
            pool_info['public_hostname'] = \
                CONF.xenserver.console_public_hostname
            pool_info['console_type'] = self.driver.console_type
            pool_info['compute_host'] = instance_host
            pool = self.db.console_pool_create(context, pool_info)
        return pool
