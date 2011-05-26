# Copyright 2011 OpenStack LLC.
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
Tests for Crypto module.
"""

from nova import crypto
from nova import test


class SymmetricKeyTestCase(test.TestCase):
    """Test case for Encrypt/Decrypt"""
    def test_encrypt_decrypt(self):
        key = 'c286696d887c9aa0611bbb3e2025a45a'
        plain_text = "The quick brown fox jumped over the lazy dog."

        # No IV supplied (all 0's)
        encrypt = crypto.encryptor(key)
        cipher_text = encrypt(plain_text)
        self.assertNotEquals(plain_text, cipher_text)

        decrypt = crypto.decryptor(key)
        plain = decrypt(cipher_text)

        self.assertEquals(plain_text, plain)

        # IV supplied ...
        iv = '562e17996d093d28ddb3ba695a2e6f58'
        encrypt = crypto.encryptor(key, iv)
        cipher_text = encrypt(plain_text)
        self.assertNotEquals(plain_text, cipher_text)

        decrypt = crypto.decryptor(key, iv)
        plain = decrypt(cipher_text)

        self.assertEquals(plain_text, plain)
