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

import os
import shutil
import tempfile

import mox

from nova import crypto
from nova import db
from nova import flags
from nova import test
from nova import utils

FLAGS = flags.FLAGS


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


class X509Test(test.TestCase):
    def test_can_generate_x509(self):
        tmpdir = tempfile.mkdtemp()
        self.flags(ca_path=tmpdir)
        try:
            crypto.ensure_ca_filesystem()
            _key, cert_str = crypto.generate_x509_cert('fake', 'fake')

            project_cert = crypto.fetch_ca(project_id='fake')

            signed_cert_file = os.path.join(tmpdir, "signed")
            with open(signed_cert_file, 'w') as keyfile:
                keyfile.write(cert_str)

            project_cert_file = os.path.join(tmpdir, "project")
            with open(project_cert_file, 'w') as keyfile:
                keyfile.write(project_cert)

            enc, err = utils.execute('openssl', 'verify', '-CAfile',
                    project_cert_file, '-verbose', signed_cert_file)
            self.assertFalse(err)

        finally:
            shutil.rmtree(tmpdir)

    def test_encrypt_decrypt_x509(self):
        tmpdir = tempfile.mkdtemp()
        self.flags(ca_path=tmpdir)
        project_id = "fake"
        try:
            crypto.ensure_ca_filesystem()
            cert = crypto.fetch_ca(project_id)
            public_key = os.path.join(tmpdir, "public.pem")
            with open(public_key, 'w') as keyfile:
                keyfile.write(cert)
            text = "some @#!%^* test text"
            enc, _err = utils.execute('openssl',
                                     'rsautl',
                                     '-certin',
                                     '-encrypt',
                                     '-inkey', '%s' % public_key,
                                     process_input=text)
            dec = crypto.decrypt_text(project_id, enc)
            self.assertEqual(text, dec)
        finally:
            shutil.rmtree(tmpdir)


class RevokeCertsTest(test.TestCase):

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
