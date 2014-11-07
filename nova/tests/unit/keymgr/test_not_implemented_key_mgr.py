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
Test cases for the not implemented key manager.
"""

from nova.keymgr import not_implemented_key_mgr
from nova.tests.unit.keymgr import test_key_mgr


class NotImplementedKeyManagerTestCase(test_key_mgr.KeyManagerTestCase):

    def _create_key_manager(self):
        return not_implemented_key_mgr.NotImplementedKeyManager()

    def test_create_key(self):
        self.assertRaises(NotImplementedError,
                          self.key_mgr.create_key, None)

    def test_store_key(self):
        self.assertRaises(NotImplementedError,
                          self.key_mgr.store_key, None, None)

    def test_copy_key(self):
        self.assertRaises(NotImplementedError,
                          self.key_mgr.copy_key, None, None)

    def test_get_key(self):
        self.assertRaises(NotImplementedError,
                          self.key_mgr.get_key, None, None)

    def test_delete_key(self):
        self.assertRaises(NotImplementedError,
                          self.key_mgr.delete_key, None, None)
