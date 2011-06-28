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

import mox
import stubout

from nova import crypto
from nova import db
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


class RevokeCertsTest(test.TestCase):

    def setUp(self):
        super(RevokeCertsTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(RevokeCertsTest, self).tearDown()

    def test_revoke_certs_by_user_and_project(self):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_user_and_project(context,
                                                         user_id,
                                                         project_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stubs.Set(db, 'certificate_get_all_by_user_and_project',
                           mock_certificate_get_all_by_user_and_project)

        self.mox.StubOutWithMock(crypto, 'revoke_cert')
        crypto.revoke_cert(project_id, file_name)

        self.mox.ReplayAll()

        crypto.revoke_certs_by_user_and_project(user_id, project_id)

        self.mox.VerifyAll()

    def test_revoke_certs_by_user(self):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_user(context, user_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stubs.Set(db, 'certificate_get_all_by_user',
                                    mock_certificate_get_all_by_user)

        self.mox.StubOutWithMock(crypto, 'revoke_cert')
        crypto.revoke_cert(project_id, mox.IgnoreArg())

        self.mox.ReplayAll()

        crypto.revoke_certs_by_user(user_id)

        self.mox.VerifyAll()

    def test_revoke_certs_by_project(self):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_project(context, project_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stubs.Set(db, 'certificate_get_all_by_project',
                                    mock_certificate_get_all_by_project)

        self.mox.StubOutWithMock(crypto, 'revoke_cert')
        crypto.revoke_cert(project_id, mox.IgnoreArg())

        self.mox.ReplayAll()

        crypto.revoke_certs_by_project(project_id)

        self.mox.VerifyAll()
