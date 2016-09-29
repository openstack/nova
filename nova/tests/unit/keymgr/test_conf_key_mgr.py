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
Test cases for the conf key manager.
"""

import binascii
import codecs

from castellan.common.objects import symmetric_key as key

import nova.conf
from nova import context
from nova import exception
from nova.keymgr import conf_key_mgr
from nova import test


CONF = nova.conf.CONF
decode_hex = codecs.getdecoder("hex_codec")


class ConfKeyManagerTestCase(test.NoDBTestCase):
    def __init__(self, *args, **kwargs):
        super(ConfKeyManagerTestCase, self).__init__(*args, **kwargs)

        self._hex_key = '0' * 64

    def _create_key_manager(self):
        CONF.set_default('fixed_key', default=self._hex_key,
                         group='key_manager')
        return conf_key_mgr.ConfKeyManager(CONF)

    def setUp(self):
        super(ConfKeyManagerTestCase, self).setUp()

        self.ctxt = context.RequestContext('fake', 'fake')
        self.key_mgr = self._create_key_manager()
        encoded_key = bytes(binascii.unhexlify(self._hex_key))
        self.key = key.SymmetricKey('AES', len(encoded_key) * 8, encoded_key)
        self.key_id = self.key_mgr.key_id

    def test_init(self):
        key_manager = self._create_key_manager()
        self.assertEqual(self._hex_key, key_manager._hex_key)

    def test_init_value_error(self):
        CONF.set_default('fixed_key', default=None, group='key_manager')
        self.assertRaises(ValueError, conf_key_mgr.ConfKeyManager, CONF)

    def test_create_key(self):
        key_id_1 = self.key_mgr.create_key(self.ctxt, 'AES', 256)
        key_id_2 = self.key_mgr.create_key(self.ctxt, 'AES', 256)
        # ensure that the UUIDs are the same
        self.assertEqual(key_id_1, key_id_2)

    def test_create_null_context(self):
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.create_key, None, 'AES', 256)

    def test_store_key(self):
        key_bytes = bytes(binascii.unhexlify('0' * 64))
        _key = key.SymmetricKey('AES', len(key_bytes) * 8, key_bytes)
        key_id = self.key_mgr.store(self.ctxt, _key)

        actual_key = self.key_mgr.get(self.ctxt, key_id)
        self.assertEqual(_key, actual_key)

    def test_store_null_context(self):
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.store, None, self.key)

    def test_get_null_context(self):
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.get, None, None)

    def test_get_unknown_key(self):
        self.assertRaises(KeyError, self.key_mgr.get, self.ctxt, None)

    def test_get(self):
        self.assertEqual(self.key,
                         self.key_mgr.get(self.ctxt, self.key_id))

    def test_delete_key(self):
        key_id = self.key_mgr.create_key(self.ctxt, 'AES', 256)
        self.key_mgr.delete(self.ctxt, key_id)

        # key won't actually be deleted
        self.assertEqual(self.key,
                         self.key_mgr.get(self.ctxt, key_id))

    def test_delete_null_context(self):
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.delete, None, None)

    def test_delete_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.delete, self.ctxt, None)
