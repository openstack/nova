# Copyright (c) 2015 The Johns Hopkins University/Applied Physics Laboratory
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
Test cases for the barbican key manager.
"""

import array
import binascii

import mock

from nova import exception
from nova.keymgr import barbican
from nova.keymgr import key as keymgr_key
from nova.tests.unit.keymgr import test_key_mgr


class BarbicanKeyManagerTestCase(test_key_mgr.KeyManagerTestCase):

    def _create_key_manager(self):
        return barbican.BarbicanKeyManager()

    def setUp(self):
        super(BarbicanKeyManagerTestCase, self).setUp()

        # Create fake auth_token
        self.ctxt = mock.Mock()
        self.ctxt.auth_token = "fake_token"

        # Create mock barbican client
        self._build_mock_barbican()

        # Create a key_id, secret_ref, pre_hex, and hex to use
        self.key_id = "d152fa13-2b41-42ca-a934-6c21566c0f40"
        self.secret_ref = ("http://host:9311/v1/secrets/" + self.key_id)
        self.pre_hex = "AIDxQp2++uAbKaTVDMXFYIu8PIugJGqkK0JLqkU0rhY="
        self.hex = ("0080f1429dbefae01b29a4d50cc5c5608bbc3c8ba0246aa42b424baa4"
                    "534ae16")
        self.key_mgr._base_url = "http://host:9311/v1"
        self.addCleanup(self._restore)

    def _restore(self):
        if hasattr(self, 'original_key'):
            keymgr_key.SymmetricKey = self.original_key

    def _build_mock_barbican(self):
        self.mock_barbican = mock.MagicMock(name='mock_barbican')

        # Set commonly used methods
        self.get = self.mock_barbican.secrets.get
        self.delete = self.mock_barbican.secrets.delete
        self.store = self.mock_barbican.secrets.store
        self.create = self.mock_barbican.secrets.create

        self.key_mgr._barbican_client = self.mock_barbican

    def _build_mock_symKey(self):
        self.mock_symKey = mock.Mock()

        def fake_sym_key(alg, key):
            self.mock_symKey.get_encoded.return_value = key
            self.mock_symKey.get_algorithm.return_value = alg
            return self.mock_symKey
        self.original_key = keymgr_key.SymmetricKey
        keymgr_key.SymmetricKey = fake_sym_key

    def test_copy_key(self):
        # Create metadata for original secret
        original_secret_metadata = mock.Mock()
        original_secret_metadata.algorithm = mock.sentinel.alg
        original_secret_metadata.bit_length = mock.sentinel.bit
        original_secret_metadata.name = mock.sentinel.name
        original_secret_metadata.expiration = mock.sentinel.expiration
        original_secret_metadata.mode = mock.sentinel.mode
        content_types = {'default': 'fake_type'}
        original_secret_metadata.content_types = content_types
        original_secret_data = mock.Mock()
        original_secret_metadata.payload = original_secret_data

        # Create href for copied secret
        copied_secret = mock.Mock()
        copied_secret.store.return_value = 'http://test/uuid'

        # Set get and create return values
        self.get.return_value = original_secret_metadata
        self.create.return_value = copied_secret

        # Create the mock key
        self._build_mock_symKey()

        # Copy the original
        self.key_mgr.copy_key(self.ctxt, self.key_id)

        # Assert proper methods were called
        self.get.assert_called_once_with(self.secret_ref)
        self.create.assert_called_once_with(
            mock.sentinel.name,
            self.mock_symKey.get_encoded(),
            content_types['default'],
            'base64',
            mock.sentinel.alg,
            mock.sentinel.bit,
            mock.sentinel.mode,
            mock.sentinel.expiration)
        copied_secret.store.assert_called_once_with()

    def test_copy_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.copy_key, None, self.key_id)

    def test_create_key(self):
        # Create order_ref_url and assign return value
        order_ref_url = ("http://localhost:9311/v1/None/orders/"
                         "4fe939b7-72bc-49aa-bd1e-e979589858af")
        key_order = mock.Mock()
        self.mock_barbican.orders.create_key.return_value = key_order
        key_order.submit.return_value = order_ref_url

        # Create order and assign return value
        order = mock.Mock()
        order.secret_ref = self.secret_ref
        self.mock_barbican.orders.get.return_value = order

        # Create the key, get the UUID
        returned_uuid = self.key_mgr.create_key(self.ctxt)

        self.mock_barbican.orders.get.assert_called_once_with(order_ref_url)
        self.assertEqual(returned_uuid, self.key_id)

    def test_create_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.create_key, None)

    def test_delete_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.delete_key, None, self.key_id)

    def test_delete_key(self):
        self.key_mgr.delete_key(self.ctxt, self.key_id)
        self.delete.assert_called_once_with(self.secret_ref)

    def test_delete_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.delete_key, self.ctxt, None)

    @mock.patch('base64.b64encode')
    def test_get_key(self, b64_mock):
        b64_mock.return_value = self.pre_hex
        content_type = 'application/octet-stream'

        key = self.key_mgr.get_key(self.ctxt, self.key_id, content_type)

        self.get.assert_called_once_with(self.secret_ref)
        encoded = array.array('B', binascii.unhexlify(self.hex)).tolist()
        self.assertEqual(key.get_encoded(), encoded)

    def test_get_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.get_key, None, self.key_id)

    def test_get_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.get_key, self.ctxt, None)

    def test_store_key_base64(self):
        # Create Key to store
        secret_key = array.array('B', [0x01, 0x02, 0xA0, 0xB3]).tolist()
        _key = keymgr_key.SymmetricKey('AES', secret_key)

        # Define the return values
        secret = mock.Mock()
        self.create.return_value = secret
        secret.store.return_value = self.secret_ref

        # Store the Key
        returned_uuid = self.key_mgr.store_key(self.ctxt, _key, bit_length=32)

        self.create.assert_called_once_with('Nova Compute Key',
                                            'AQKgsw==',
                                            'application/octet-stream',
                                            'base64',
                                            'AES', 32, 'CBC',
                                            None)
        self.assertEqual(returned_uuid, self.key_id)

    def test_store_key_plaintext(self):
        # Create the plaintext key
        secret_key_text = "This is a test text key."
        _key = keymgr_key.SymmetricKey('AES', secret_key_text)

        # Store the Key
        self.key_mgr.store_key(self.ctxt, _key,
                               payload_content_type='text/plain',
                               payload_content_encoding=None)
        self.create.assert_called_once_with('Nova Compute Key',
                                            secret_key_text,
                                            'text/plain',
                                            None,
                                            'AES', 256, 'CBC',
                                            None)
        self.assertEqual(self.store.call_count, 0)

    def test_store_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.Forbidden,
                          self.key_mgr.store_key, None, None)
