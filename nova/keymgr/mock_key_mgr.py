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
A mock implementation of a key manager that stores keys in a dictionary.

This key manager implementation is primarily intended for testing. In
particular, it does not store keys persistently. Lack of a centralized key
store also makes this implementation unsuitable for use among different
services.

Note: Instantiating this class multiple times will create separate key stores.
Keys created in one instance will not be accessible from other instances of
this class.
"""

import array

from oslo_log import log as logging
from oslo_utils import uuidutils

from nova import exception
from nova.i18n import _LW
from nova.keymgr import key
from nova.keymgr import key_mgr
from nova import utils


LOG = logging.getLogger(__name__)


class MockKeyManager(key_mgr.KeyManager):
    """This mock key manager implementation supports all the methods specified
    by the key manager interface. This implementation stores keys within a
    dictionary, and as a result, it is not acceptable for use across different
    services. Side effects (e.g., raising exceptions) for each method are
    handled as specified by the key manager interface.

    This key manager is not suitable for use in production deployments.
    """

    def __init__(self):
        LOG.warning(_LW('This key manager is not suitable for use in '
                        'production deployments'))

        self.keys = {}

    def _generate_hex_key(self, **kwargs):
        key_length = kwargs.get('key_length', 256)
        # hex digit => 4 bits
        hex_encoded = utils.generate_password(length=key_length / 4,
                                              symbolgroups='0123456789ABCDEF')
        return hex_encoded

    def _generate_key(self, **kwargs):
        _hex = self._generate_hex_key(**kwargs)
        return key.SymmetricKey('AES',
                                array.array('B', _hex.decode('hex')).tolist())

    def create_key(self, ctxt, **kwargs):
        """Creates a key.

        This implementation returns a UUID for the created key. A
        Forbidden exception is raised if the specified context is None.
        """
        if ctxt is None:
            raise exception.Forbidden()

        key = self._generate_key(**kwargs)
        return self.store_key(ctxt, key)

    def _generate_key_id(self):
        key_id = uuidutils.generate_uuid()
        while key_id in self.keys:
            key_id = uuidutils.generate_uuid()

        return key_id

    def store_key(self, ctxt, key, **kwargs):
        """Stores (i.e., registers) a key with the key manager."""
        if ctxt is None:
            raise exception.Forbidden()

        key_id = self._generate_key_id()
        self.keys[key_id] = key

        return key_id

    def copy_key(self, ctxt, key_id, **kwargs):
        if ctxt is None:
            raise exception.Forbidden()

        copied_key_id = self._generate_key_id()
        self.keys[copied_key_id] = self.keys[key_id]

        return copied_key_id

    def get_key(self, ctxt, key_id, **kwargs):
        """Retrieves the key identified by the specified id.

        This implementation returns the key that is associated with the
        specified UUID. A Forbidden exception is raised if the specified
        context is None; a KeyError is raised if the UUID is invalid.
        """
        if ctxt is None:
            raise exception.Forbidden()

        return self.keys[key_id]

    def delete_key(self, ctxt, key_id, **kwargs):
        """Deletes the key identified by the specified id.

        A Forbidden exception is raised if the context is None and a
        KeyError is raised if the UUID is invalid.
        """
        if ctxt is None:
            raise exception.Forbidden()

        del self.keys[key_id]
