# vim: tabstop=4 shiftwidth=4 softtabstop=4
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
A mock implementation of a key manager. This module should NOT be used for
anything but integration testing.
"""

import array
import uuid

from nova import exception
from nova.keymgr import key
from nova.keymgr import key_mgr
from nova.openstack.common import log as logging
from nova import utils


LOG = logging.getLogger(__name__)


class MockKeyManager(key_mgr.KeyManager):
    """
    This mock key manager implementation supports all the methods specified
    by the key manager interface. This implementation creates a single key in
    response to all invocations of create_key. Side effects (e.g., raising
    exceptions) for each method are handled as specified by the key manager
    interface.

    This class should NOT be used for anything but integration testing because
    the same key is created for all invocations of create_key and keys are not
    stored persistently.
    """
    def __init__(self):
        self.keys = {}

    def create_key(self, ctxt, **kwargs):
        """Creates a key.

        This implementation returns a UUID for the created key. A
        NotAuthorized exception is raised if the specified context is None.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        # generate the key
        key_length = kwargs.get('key_length', 256)
        # hex digit => 4 bits
        hex_string = utils.generate_password(length=key_length / 4,
                                             symbolgroups='0123456789ABCDEF')

        _bytes = array.array('B', hex_string.decode('hex')).tolist()
        _key = key.SymmetricKey('AES', _bytes)

        return self.store_key(ctxt, _key)

    def store_key(self, ctxt, key, **kwargs):
        """Stores (i.e., registers) a key with the key manager.

        This implementation does nothing -- i.e., the specified key is
        discarded.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        # generate UUID and ensure that it isn't in use
        key_id = uuid.uuid4()
        while key_id in self.keys:
            key_id = uuid.uuid4()

        self.keys[key_id] = key

        return key_id

    def get_key(self, ctxt, key_id, **kwargs):
        """Retrieves the key identified by the specified id.

        This implementation returns a fixed key that is associated with the
        UUID returned by the create_key method. A NotAuthorized exception is
        raised if the specified context is None; a KeyError is raised if the
        UUID is invalid.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        return self.keys[key_id]

    def delete_key(self, ctxt, key_id, **kwargs):
        """Deletes the key identified by the specified id.

        This implementation intentionally does nothing except raise a
        NotAuthorized exception is the context is None or a KeyError if the
        UUID is invalid.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        del self.keys[key_id]
