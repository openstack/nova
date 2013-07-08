#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack Foundation
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

from oslo.config import cfg

from nova.cells import rpcapi as cells_rpcapi
from nova.compute import rpcapi as compute_rpcapi
from nova import manager
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import memorycache


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
CONF.import_opt('enable', 'nova.cells.opts', group='cells')


class ConsoleAuthManager(manager.Manager):
    """Manages token based authentication."""

    RPC_API_VERSION = '1.2'

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        super(ConsoleAuthManager, self).__init__(service_name='consoleauth',
                                                 *args, **kwargs)
        self.mc = memorycache.get_client()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _get_tokens_for_instance(self, instance_uuid):
        tokens_str = self.mc.get(instance_uuid.encode('UTF-8'))
        if not tokens_str:
            tokens = []
        else:
            tokens = jsonutils.loads(tokens_str)
        return tokens

    def authorize_console(self, context, token, console_type, host, port,
                          internal_access_path, instance_uuid=None):

        token_dict = {'token': token,
                      'instance_uuid': instance_uuid,
                      'console_type': console_type,
                      'host': host,
                      'port': port,
                      'internal_access_path': internal_access_path,
                      'last_activity_at': time.time()}
        data = jsonutils.dumps(token_dict)
        self.mc.set(token.encode('UTF-8'), data, CONF.console_token_ttl)
        if instance_uuid is not None:
            tokens = self._get_tokens_for_instance(instance_uuid)
            tokens.append(token)
            self.mc.set(instance_uuid.encode('UTF-8'),
                        jsonutils.dumps(tokens))

        LOG.audit(_("Received Token: %(token)s, %(token_dict)s)"), locals())

    def _validate_token(self, context, token):
        instance_uuid = token['instance_uuid']
        if instance_uuid is None:
            return False

        # NOTE(comstud): consoleauth was meant to run in API cells.  So,
        # if cells is enabled, we must call down to the child cell for
        # the instance.
        if CONF.cells.enable:
            return self.cells_rpcapi.validate_console_port(context,
                    instance_uuid, token['port'], token['console_type'])

        instance = self.db.instance_get_by_uuid(context, instance_uuid)

        return self.compute_rpcapi.validate_console_port(context,
                                            instance,
                                            token['port'],
                                            token['console_type'])

    def check_token(self, context, token):
        token_str = self.mc.get(token.encode('UTF-8'))
        token_valid = (token_str is not None)
        LOG.audit(_("Checking Token: %(token)s, %(token_valid)s)"), locals())
        if token_valid:
            token = jsonutils.loads(token_str)
            if self._validate_token(context, token):
                return token

    def delete_tokens_for_instance(self, context, instance_uuid):
        tokens = self._get_tokens_for_instance(instance_uuid)
        for token in tokens:
            self.mc.delete(token.encode('UTF-8'))
        self.mc.delete(instance_uuid.encode('UTF-8'))

    # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def get_backdoor_port(self, context):
        return self.backdoor_port
