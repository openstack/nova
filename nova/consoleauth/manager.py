#!/usr/bin/env python
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

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils

from nova import cache_utils
from nova.cells import rpcapi as cells_rpcapi
from nova.compute import rpcapi as compute_rpcapi
import nova.conf
from nova.i18n import _LI, _LW
from nova import manager
from nova import objects


LOG = logging.getLogger(__name__)

consoleauth_opts = [
    cfg.IntOpt('console_token_ttl',
               default=600,
               help='How many seconds before deleting tokens')
    ]

CONF = nova.conf.CONF
CONF.register_opts(consoleauth_opts)


class ConsoleAuthManager(manager.Manager):
    """Manages token based authentication."""

    target = messaging.Target(version='2.1')

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        super(ConsoleAuthManager, self).__init__(service_name='consoleauth',
                                                 *args, **kwargs)
        self._mc = None
        self._mc_instance = None
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    @property
    def mc(self):
        if self._mc is None:
            self._mc = cache_utils.get_client(CONF.console_token_ttl)
        return self._mc

    @property
    def mc_instance(self):
        if self._mc_instance is None:
            self._mc_instance = cache_utils.get_client()
        return self._mc_instance

    def reset(self):
        LOG.info(_LI('Reloading compute RPC API'))
        compute_rpcapi.LAST_VERSION = None
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def _get_tokens_for_instance(self, instance_uuid):
        tokens_str = self.mc_instance.get(instance_uuid.encode('UTF-8'))
        if not tokens_str:
            tokens = []
        else:
            tokens = jsonutils.loads(tokens_str)
        return tokens

    def authorize_console(self, context, token, console_type, host, port,
                          internal_access_path, instance_uuid,
                          access_url=None):

        token_dict = {'token': token,
                      'instance_uuid': instance_uuid,
                      'console_type': console_type,
                      'host': host,
                      'port': port,
                      'internal_access_path': internal_access_path,
                      'access_url': access_url,
                      'last_activity_at': time.time()}
        data = jsonutils.dumps(token_dict)

        # We need to log the warning message if the token is not cached
        # successfully, because the failure will cause the console for
        # instance to not be usable.
        if not self.mc.set(token.encode('UTF-8'), data):
            LOG.warning(_LW("Token: %(token)s failed to save into memcached."),
                        {'token': token})
        tokens = self._get_tokens_for_instance(instance_uuid)

        # Remove the expired tokens from cache.
        token_values = self.mc.get_multi(
            [tok.encode('UTF-8') for tok in tokens])
        tokens = [name for name, value in zip(tokens, token_values)
                  if value is not None]
        tokens.append(token)

        if not self.mc_instance.set(instance_uuid.encode('UTF-8'),
                           jsonutils.dumps(tokens)):
            LOG.warning(_LW("Instance: %(instance_uuid)s failed to save "
                            "into memcached"),
                        {'instance_uuid': instance_uuid})

        LOG.info(_LI("Received Token: %(token)s, %(token_dict)s"),
                  {'token': token, 'token_dict': token_dict})

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

        instance = objects.Instance.get_by_uuid(context, instance_uuid)

        return self.compute_rpcapi.validate_console_port(context,
                                            instance,
                                            token['port'],
                                            token['console_type'])

    def check_token(self, context, token):
        token_str = self.mc.get(token.encode('UTF-8'))
        token_valid = (token_str is not None)
        LOG.info(_LI("Checking Token: %(token)s, %(token_valid)s"),
                  {'token': token, 'token_valid': token_valid})
        if token_valid:
            token = jsonutils.loads(token_str)
            if self._validate_token(context, token):
                return token

    def delete_tokens_for_instance(self, context, instance_uuid):
        tokens = self._get_tokens_for_instance(instance_uuid)
        self.mc.delete_multi(
                [tok.encode('UTF-8') for tok in tokens])
        self.mc_instance.delete(instance_uuid.encode('UTF-8'))
