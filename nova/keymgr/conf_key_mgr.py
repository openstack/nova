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
An implementation of a key manager that reads its key from the project's
configuration options.

This key manager implementation provides limited security, assuming that the
key remains secret. Using the volume encryption feature as an example,
encryption provides protection against a lost or stolen disk, assuming that
the configuration file that contains the key is not stored on the disk.
Encryption also protects the confidentiality of data as it is transmitted via
iSCSI from the compute host to the storage host (again assuming that an
attacker who intercepts the data does not know the secret key).

Because this implementation uses a single, fixed key, it proffers no
protection once that key is compromised. In particular, different volumes
encrypted with a key provided by this key manager actually share the same
encryption key so *any* volume can be decrypted once the fixed key is known.
"""

import binascii

from castellan.common.objects import symmetric_key as key
from castellan.key_manager import key_manager
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.i18n import _


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class ConfKeyManager(key_manager.KeyManager):
    """This key manager implementation supports all the methods specified by
    the key manager interface. This implementation creates a single key in
    response to all invocations of create_key. Side effects
    (e.g., raising exceptions) for each method are handled
    as specified by the key manager interface.
    """

    def __init__(self, configuration):
        LOG.warning('This key manager is insecure and is not recommended '
                    'for production deployments')
        super(ConfKeyManager, self).__init__(configuration)

        self.key_id = '00000000-0000-0000-0000-000000000000'

        self.conf = CONF if configuration is None else configuration

        if CONF.key_manager.fixed_key is None:
            raise ValueError(_('keymgr.fixed_key not defined'))
        self._hex_key = CONF.key_manager.fixed_key
        super(ConfKeyManager, self).__init__(configuration)

    def _get_key(self):
        key_bytes = bytes(binascii.unhexlify(self._hex_key))
        return key.SymmetricKey('AES', len(key_bytes) * 8, key_bytes)

    def create_key(self, context, algorithm, length, **kwargs):
        """Creates a symmetric key.

        This implementation returns a UUID for the key read from the
        configuration file. A Forbidden exception is raised if the
        specified context is None.
        """
        if context is None:
            raise exception.Forbidden()

        return self.key_id

    def create_key_pair(self, context, **kwargs):
        raise NotImplementedError(
            "ConfKeyManager does not support asymmetric keys")

    def store(self, context, managed_object, **kwargs):
        """Stores (i.e., registers) a key with the key manager."""
        if context is None:
            raise exception.Forbidden()

        if managed_object != self._get_key():
            raise exception.KeyManagerError(
                reason="cannot store arbitrary keys")

        return self.key_id

    def get(self, context, managed_object_id):
        """Retrieves the key identified by the specified id.

        This implementation returns the key that is associated with the
        specified UUID. A Forbidden exception is raised if the specified
        context is None; a KeyError is raised if the UUID is invalid.
        """
        if context is None:
            raise exception.Forbidden()

        if managed_object_id != self.key_id:
            raise KeyError(str(managed_object_id) + " != " + str(self.key_id))

        return self._get_key()

    def delete(self, context, managed_object_id):
        """Represents deleting the key.

        Because the ConfKeyManager has only one key, which is read from the
        configuration file, the key is not actually deleted when this is
        called.
        """
        if context is None:
            raise exception.Forbidden()

        if managed_object_id != self.key_id:
            raise exception.KeyManagerError(
                reason="cannot delete non-existent key")

        LOG.warning("Not deleting key %s", managed_object_id)
