# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

"""
An implementation of a key manager that returns a single key in response to
all invocations of get_key.
"""

from oslo_log import log as logging

from nova import exception
from nova.i18n import _, _LW
from nova.keymgr import mock_key_mgr


LOG = logging.getLogger(__name__)


class SingleKeyManager(mock_key_mgr.MockKeyManager):
    """This key manager implementation supports all the methods specified by
    the key manager interface. This implementation creates a single key in
    response to all invocations of create_key. Side effects
    (e.g., raising exceptions) for each method are handled as specified by
    the key manager interface.
    """

    def __init__(self):
        LOG.warning(_LW('This key manager is insecure and is not recommended '
                        'for production deployments'))
        super(SingleKeyManager, self).__init__()

        self.key_id = '00000000-0000-0000-0000-000000000000'
        self.key = self._generate_key(key_length=256)

        # key should exist by default
        self.keys[self.key_id] = self.key

    def _generate_hex_key(self, **kwargs):
        key_length = kwargs.get('key_length', 256)
        return '0' * (key_length / 4)  # hex digit => 4 bits

    def _generate_key_id(self):
        return self.key_id

    def store_key(self, ctxt, key, **kwargs):
        if key != self.key:
            raise exception.KeyManagerError(
                        reason=_("cannot store arbitrary keys"))

        return super(SingleKeyManager, self).store_key(ctxt, key, **kwargs)

    def delete_key(self, ctxt, key_id, **kwargs):
        if ctxt is None:
            raise exception.Forbidden()

        if key_id != self.key_id:
            raise exception.KeyManagerError(
                        reason=_("cannot delete non-existent key"))

        LOG.warning(_LW("Not deleting key %s"), key_id)
