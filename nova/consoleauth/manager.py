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

import os
import sys
import time

from nova import flags
from nova import log as logging
from nova import manager
from nova.openstack.common import cfg
from nova import utils
from nova import exception
from nova import compute


LOG = logging.getLogger(__name__)

consoleauth_opts = [
    cfg.IntOpt('console_token_ttl',
               default=600,
               help='How many seconds before deleting tokens'),
    cfg.StrOpt('consoleauth_manager',
               default='nova.consoleauth.manager.ConsoleAuthManager',
               help='Manager for console auth'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(consoleauth_opts)


class ConsoleAuthManager(manager.Manager):
    """Manages token based authentication."""

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        super(ConsoleAuthManager, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.tokens = {}
        utils.LoopingCall(self._delete_expired_tokens).start(1)

    def _delete_expired_tokens(self):
        now = time.time()
        to_delete = []
        for k, v in self.tokens.items():
            if now - v['last_activity_at'] > FLAGS.console_token_ttl:
                to_delete.append(k)

        for k in to_delete:
            LOG.audit(_("Deleting Expired Token: (%s)"), k)
            del self.tokens[k]

    def authorize_console(self, context, token, console_type, host, port,
                          instance_id, internal_access_path):
        self.tokens[token] = {'token': token,
                              'console_type': console_type,
                              'host': host,
                              'port': port,
                              'instance_id': instance_id,
                              'internal_access_path': internal_access_path,
                              'last_activity_at': time.time()}
        token_dict = self.tokens[token]
        if instance_id is not None:
            tokens = self.tokens[instance_id]
            tokens.append(token)
            self.tokens[instance_id] = tokens

        LOG.audit(_("Received Token: %(token)s, %(token_dict)s)"), locals())

    def _validate_console(self, context, token):
        console_valid = False
        token_dict = self.tokens[token]
        try:
            console_valid = self.compute_api.validate_vnc_console(context,
                                                token_dict['instance_id'],
                                                token_dict['host'],
                                                token_dict['port'])
        except exception.InstanceNotFound:
            pass
        return console_valid

    def check_token(self, context, token):
        token_valid = token in self.tokens
        LOG.audit(_("Checking Token: %(token)s, %(token_valid)s)"), locals())
        if token_valid and _validate_console(token):
            return self.tokens[token]

    def delete_tokens_for_instance(self, context, instance_id):
        for token in self.tokens[instance_id]:
            token_dict = self.tokens[token]
            token_dict['last_activity_at'] = 0
            self.tokens[token] = token_dict
        del self.tokens[instance_id]
