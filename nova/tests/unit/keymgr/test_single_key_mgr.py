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
Test cases for the single key manager.
"""

import array

from nova import exception
from nova.keymgr import key
from nova.keymgr import single_key_mgr
from nova.tests.unit.keymgr import test_mock_key_mgr


class SingleKeyManagerTestCase(test_mock_key_mgr.MockKeyManagerTestCase):

    def _create_key_manager(self):
        return single_key_mgr.SingleKeyManager()

    def setUp(self):
        super(SingleKeyManagerTestCase, self).setUp()

        self.key_id = '00000000-0000-0000-0000-000000000000'
        encoded = array.array('B', ('0' * 64).decode('hex')).tolist()
        self.key = key.SymmetricKey('AES', encoded)

    def test___init__(self):
        self.assertEqual(self.key,
                         self.key_mgr.get_key(self.ctxt, self.key_id))

    def test_create_key(self):
        key_id_1 = self.key_mgr.create_key(self.ctxt)
        key_id_2 = self.key_mgr.create_key(self.ctxt)
        # ensure that the UUIDs are the same
        self.assertEqual(key_id_1, key_id_2)

    def test_create_key_with_length(self):
        pass

    def test_store_null_context(self):
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.store_key, None, self.key)

    def test_copy_key(self):
        key_id = self.key_mgr.create_key(self.ctxt)
        key = self.key_mgr.get_key(self.ctxt, key_id)

        copied_key_id = self.key_mgr.copy_key(self.ctxt, key_id)
        copied_key = self.key_mgr.get_key(self.ctxt, copied_key_id)

        self.assertEqual(key_id, copied_key_id)
        self.assertEqual(key, copied_key)

    def test_delete_key(self):
        pass

    def test_delete_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.delete_key, self.ctxt, None)
