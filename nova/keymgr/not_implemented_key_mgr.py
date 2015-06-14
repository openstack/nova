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
Key manager implementation that raises NotImplementedError
"""

from nova.keymgr import key_mgr


class NotImplementedKeyManager(key_mgr.KeyManager):
    """Key Manager Interface that raises NotImplementedError for all operations
    """

    def create_key(self, ctxt, algorithm='AES', length=256, expiration=None,
                   **kwargs):
        raise NotImplementedError()

    def store_key(self, ctxt, key, expiration=None, **kwargs):
        raise NotImplementedError()

    def copy_key(self, ctxt, key_id, **kwargs):
        raise NotImplementedError()

    def get_key(self, ctxt, key_id, **kwargs):
        raise NotImplementedError()

    def delete_key(self, ctxt, key_id, **kwargs):
        raise NotImplementedError()
