#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Auth Components for Consoles."""

import time

from nova.common import memorycache
from nova import manager
from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)

consoleauth_opts = [
    cfg.IntOpt('console_token_ttl',
               default=600,
               help='How many seconds before deleting tokens'),
    cfg.StrOpt('consoleauth_manager',
               default='nova.consoleauth.manager.ConsoleAuthManager',
               help='Manager for console auth'),
    ]

CONF = cfg.CONF
CONF.register_opts(consoleauth_opts)


class ConsoleAuthManager(manager.Manager):
    """Manages token based authentication."""

    RPC_API_VERSION = '1.1'

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        super(ConsoleAuthManager, self).__init__(*args, **kwargs)
        self.mc = memorycache.get_client()

    def authorize_console(self, context, token, console_type, host, port,
                          internal_access_path):
        token_dict = {'token': token,
                      'console_type': console_type,
                      'host': host,
                      'port': port,
                      'internal_access_path': internal_access_path,
                      'last_activity_at': time.time()}
        data = jsonutils.dumps(token_dict)
        self.mc.set(token.encode('UTF-8'), data, CONF.console_token_ttl)
        LOG.audit(_("Received Token: %(token)s, %(token_dict)s)"), locals())

    def check_token(self, context, token):
        token_str = self.mc.get(token.encode('UTF-8'))
        token_valid = (token_str is not None)
        LOG.audit(_("Checking Token: %(token)s, %(token_valid)s)"), locals())
        if token_valid:
            return jsonutils.loads(token_str)

    def get_backdoor_port(self, context):
        return self.backdoor_port
