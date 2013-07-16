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
Test cases for the mock key manager.
"""

import array

from nova import context
from nova import exception
from nova.keymgr import key
from nova.tests.keymgr import mock_key_mgr
from nova.tests.keymgr import test_key_mgr


class MockKeyManagerTestCase(test_key_mgr.KeyManagerTestCase):

    def _create_key_manager(self):
        return mock_key_mgr.MockKeyManager()

    def setUp(self):
        super(MockKeyManagerTestCase, self).setUp()

        self.ctxt = context.RequestContext('fake', 'fake')

    def test_create_key(self):
        key_id_1 = self.key_mgr.create_key(self.ctxt)
        key_id_2 = self.key_mgr.create_key(self.ctxt)
        # ensure that the UUIDs are unique
        self.assertNotEqual(key_id_1, key_id_2)

    def test_create_key_with_length(self):
        for length in [64, 128, 256]:
            key_id = self.key_mgr.create_key(self.ctxt, key_length=length)
            key = self.key_mgr.get_key(self.ctxt, key_id)
            self.assertEqual(length / 8, len(key.get_encoded()))

    def test_create_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.create_key, None)

    def test_store_key(self):
        _key = key.SymmetricKey('AES',
                        array.array('B', ('0' * 64).decode('hex')).tolist())
        key_id = self.key_mgr.store_key(self.ctxt, _key)

        actual_key = self.key_mgr.get_key(self.ctxt, key_id)
        self.assertEqual(_key, actual_key)

    def test_store_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.store_key, None, None)

    def test_get_key(self):
        pass

    def test_get_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.get_key, None, None)

    def test_get_unknown_key(self):
        self.assertRaises(KeyError, self.key_mgr.get_key, self.ctxt, None)

    def test_delete_key(self):
        key_id = self.key_mgr.create_key(self.ctxt)
        self.key_mgr.delete_key(self.ctxt, key_id)

        self.assertRaises(KeyError, self.key_mgr.get_key, self.ctxt, key_id)

    def test_delete_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.delete_key, None, None)

    def test_delete_unknown_key(self):
        self.assertRaises(KeyError, self.key_mgr.delete_key, self.ctxt, None)
