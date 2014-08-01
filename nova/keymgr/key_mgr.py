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
Key manager API
"""

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class KeyManager(object):
    """Base Key Manager Interface

    A Key Manager is responsible for managing encryption keys for volumes. A
    Key Manager is responsible for creating, reading, and deleting keys.
    """

    @abc.abstractmethod
    def create_key(self, ctxt, algorithm='AES', length=256, expiration=None,
                   **kwargs):
        """Creates a key.

        This method creates a key and returns the key's UUID. If the specified
        context does not permit the creation of keys, then a NotAuthorized
        exception should be raised.
        """
        pass

    @abc.abstractmethod
    def store_key(self, ctxt, key, expiration=None, **kwargs):
        """Stores (i.e., registers) a key with the key manager.

        This method stores the specified key and returns its UUID that
        identifies it within the key manager. If the specified context does
        not permit the creation of keys, then a NotAuthorized exception should
        be raised.
        """
        pass

    @abc.abstractmethod
    def copy_key(self, ctxt, key_id, **kwargs):
        """Copies (i.e., clones) a key stored by the key manager.

        This method copies the specified key and returns the copy's UUID. If
        the specified context does not permit copying keys, then a
        NotAuthorized error should be raised.

        Implementation note: This method should behave identically to::

            store_key(context, get_key(context, <encryption key UUID>))

        although it is preferable to perform this operation within the key
        manager to avoid unnecessary handling of the key material.
        """
        pass

    @abc.abstractmethod
    def get_key(self, ctxt, key_id, **kwargs):
        """Retrieves the specified key.

        Implementations should verify that the caller has permissions to
        retrieve the key by checking the context object passed in as ctxt. If
        the user lacks permission then a NotAuthorized exception is raised.

        If the specified key does not exist, then a KeyError should be raised.
        Implementations should preclude users from discerning the UUIDs of
        keys that belong to other users by repeatedly calling this method.
        That is, keys that belong to other users should be considered "non-
        existent" and completely invisible.
        """
        pass

    @abc.abstractmethod
    def delete_key(self, ctxt, key_id, **kwargs):
        """Deletes the specified key.

        Implementations should verify that the caller has permission to delete
        the key by checking the context object (ctxt). A NotAuthorized
        exception should be raised if the caller lacks permission.

        If the specified key does not exist, then a KeyError should be raised.
        Implementations should preclude users from discerning the UUIDs of
        keys that belong to other users by repeatedly calling this method.
        That is, keys that belong to other users should be considered "non-
        existent" and completely invisible.
        """
        pass
