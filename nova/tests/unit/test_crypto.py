# Copyright 2011 OpenStack Foundation
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

import mock
from mox3 import mox
from oslo_concurrency import processutils

from nova import crypto
from nova import db
from nova import exception
from nova import test
from nova import utils


class X509Test(test.TestCase):
    def test_can_generate_x509(self):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
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

    def test_encrypt_decrypt_x509(self):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
            project_id = "fake"
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

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError)
    @mock.patch.object(os, 'chdir', return_value=None)
    def test_revoke_cert_process_execution_error(self, *args, **kargs):
        self.assertRaises(exception.RevokeCertFailure, crypto.revoke_cert,
                          2, 'test_file')

    @mock.patch.object(os, 'chdir', mock.Mock(side_effect=OSError))
    def test_revoke_cert_project_not_found_chdir_fails(self, *args, **kargs):
        self.assertRaises(exception.ProjectNotFound, crypto.revoke_cert,
                          2, 'test_file')


class CertExceptionTests(test.TestCase):
    def test_fetch_ca_file_not_found(self):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
            self.flags(use_project_ca=True)

            self.assertRaises(exception.CryptoCAFileNotFound, crypto.fetch_ca,
                              project_id='fake')

    def test_fetch_crl_file_not_found(self):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
            self.flags(use_project_ca=True)

            self.assertRaises(exception.CryptoCRLFileNotFound,
                              crypto.fetch_crl, project_id='fake')


class EncryptionTests(test.TestCase):
    pubkey = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDArtgrfBu/g2o28o+H2ng/crv"
              "zgES91i/NNPPFTOutXelrJ9QiPTPTm+B8yspLsXifmbsmXztNOlBQgQXs6usxb4"
              "fnJKNUZ84Vkp5esbqK/L7eyRqwPvqo7btKBMoAMVX/kUyojMpxb7Ssh6M6Y8cpi"
              "goi+MSDPD7+5yRJ9z4mH9h7MCY6Ejv8KTcNYmVHvRhsFUcVhWcIISlNWUGiG7rf"
              "oki060F5myQN3AXcL8gHG5/Qb1RVkQFUKZ5geQ39/wSyYA1Q65QTba/5G2QNbl2"
              "0eAIBTyKZhN6g88ak+yARa6BLLDkrlP7L4WctHQMLsuXHohQsUO9AcOlVMARgrg"
              "uF test@test")
    prikey = """-----BEGIN RSA PRIVATE KEY-----
MIIEpQIBAAKCAQEAwK7YK3wbv4NqNvKPh9p4P3K784BEvdYvzTTzxUzrrV3payfU
Ij0z05vgfMrKS7F4n5m7Jl87TTpQUIEF7OrrMW+H5ySjVGfOFZKeXrG6ivy+3ska
sD76qO27SgTKADFV/5FMqIzKcW+0rIejOmPHKYoKIvjEgzw+/uckSfc+Jh/YezAm
OhI7/Ck3DWJlR70YbBVHFYVnCCEpTVlBohu636JItOtBeZskDdwF3C/IBxuf0G9U
VZEBVCmeYHkN/f8EsmANUOuUE22v+RtkDW5dtHgCAU8imYTeoPPGpPsgEWugSyw5
K5T+y+FnLR0DC7Llx6IULFDvQHDpVTAEYK4LhQIDAQABAoIBAF9ibrrgHnBpItx+
qVUMbriiGK8LUXxUmqdQTljeolDZi6KzPc2RVKWtpazBSvG7skX3+XCediHd+0JP
DNri1HlNiA6B0aUIGjoNsf6YpwsE4YwyK9cR5k5YGX4j7se3pKX2jOdngxQyw1Mh
dkmCeWZz4l67nbSFz32qeQlwrsB56THJjgHB7elDoGCXTX/9VJyjFlCbfxVCsIng
inrNgT0uMSYMNpAjTNOjguJt/DtXpwzei5eVpsERe0TRRVH23ycS0fuq/ancYwI/
MDr9KSB8r+OVGeVGj3popCxECxYLBxhqS1dAQyJjhQXKwajJdHFzidjXO09hLBBz
FiutpYUCgYEA6OFikTrPlCMGMJjSj+R9woDAOPfvCDbVZWfNo8iupiECvei88W28
RYFnvUQRjSC0pHe//mfUSmiEaE+SjkNCdnNR+vsq9q+htfrADm84jl1mfeWatg/g
zuGz2hAcZnux3kQMI7ufOwZNNpM2bf5B4yKamvG8tZRRxSkkAL1NV48CgYEA08/Z
Ty9g9XPKoLnUWStDh1zwG+c0q14l2giegxzaUAG5DOgOXbXcw0VQ++uOWD5ARELG
g9wZcbBsXxJrRpUqx+GAlv2Y1bkgiPQS1JIyhsWEUtwfAC/G+uZhCX53aI3Pbsjh
QmkPCSp5DuOuW2PybMaw+wVe+CaI/gwAWMYDAasCgYEA4Fzkvc7PVoU33XIeywr0
LoQkrb4QyPUrOvt7H6SkvuFm5thn0KJMlRpLfAksb69m2l2U1+HooZd4mZawN+eN
DNmlzgxWJDypq83dYwq8jkxmBj1DhMxfZnIE+L403nelseIVYAfPLOqxUTcbZXVk
vRQFp+nmSXqQHUe5rAy1ivkCgYEAqLu7cclchCxqDv/6mc5NTVhMLu5QlvO5U6fq
HqitgW7d69oxF5X499YQXZ+ZFdMBf19ypTiBTIAu1M3nh6LtIa4SsjXzus5vjKpj
FdQhTBus/hU83Pkymk1MoDOPDEtsI+UDDdSDldmv9pyKGWPVi7H86vusXCLWnwsQ
e6fCXWECgYEAqgpGvva5kJ1ISgNwnJbwiNw0sOT9BMOsdNZBElf0kJIIy6FMPvap
6S1ziw+XWfdQ83VIUOCL5DrwmcYzLIogS0agmnx/monfDx0Nl9+OZRxy6+AI9vkK
86A1+DXdo+IgX3grFK1l1gPhAZPRWJZ+anrEkyR4iLq6ZoPZ3BQn97U=
-----END RSA PRIVATE KEY-----"""
    text = "Some text! %$*"

    def _ssh_decrypt_text(self, ssh_private_key, text):
        with utils.tempdir() as tmpdir:
            sshkey = os.path.abspath(os.path.join(tmpdir, 'ssh.key'))
            with open(sshkey, 'w') as f:
                f.write(ssh_private_key)
            try:
                dec, _err = utils.execute('openssl',
                                          'rsautl',
                                          '-decrypt',
                                          '-inkey', sshkey,
                                          process_input=text)
                return dec
            except processutils.ProcessExecutionError as exc:
                raise exception.DecryptionFailure(reason=exc.stderr)

    def test_ssh_encrypt_decrypt_text(self):
        enc = crypto.ssh_encrypt_text(self.pubkey, self.text)
        self.assertNotEqual(enc, self.text)
        result = self._ssh_decrypt_text(self.prikey, enc)
        self.assertEqual(result, self.text)

    def test_ssh_encrypt_failure(self):
        self.assertRaises(exception.EncryptionFailure,
                          crypto.ssh_encrypt_text, '', self.text)


class ConversionTests(test.TestCase):
    k1 = ("ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA4CqmrxfU7x4sJrubpMNxeglul+d"
          "ByrsicnvQcHDEjPzdvoz+BaoAG9bjCA5mCeTBIISsVTVXz/hxNeiuBV6LH/UR/c"
          "27yl53ypN+821ImoexQZcKItdnjJ3gVZlDob1f9+1qDVy63NJ1c+TstkrCTRVeo"
          "9VyE7RpdSS4UCiBe8Xwk3RkedioFxePrI0Ktc2uASw2G0G2Rl7RN7KZOJbCivfF"
          "LQMAOu6e+7fYvuE1gxGHHj7dxaBY/ioGOm1W4JmQ1V7AKt19zTBlZKduN8FQMSF"
          "r35CDlvoWs0+OP8nwlebKNCi/5sdL8qiSLrAcPB4LqdkAf/blNSVA2Yl83/c4lQ"
          "== test@test")

    k2 = ("-----BEGIN PUBLIC KEY-----\n"
          "MIIBIDANBgkqhkiG9w0BAQEFAAOCAQ0AMIIBCAKCAQEA4CqmrxfU7x4sJrubpMNx\n"
          "eglul+dByrsicnvQcHDEjPzdvoz+BaoAG9bjCA5mCeTBIISsVTVXz/hxNeiuBV6L\n"
          "H/UR/c27yl53ypN+821ImoexQZcKItdnjJ3gVZlDob1f9+1qDVy63NJ1c+TstkrC\n"
          "TRVeo9VyE7RpdSS4UCiBe8Xwk3RkedioFxePrI0Ktc2uASw2G0G2Rl7RN7KZOJbC\n"
          "ivfFLQMAOu6e+7fYvuE1gxGHHj7dxaBY/ioGOm1W4JmQ1V7AKt19zTBlZKduN8FQ\n"
          "MSFr35CDlvoWs0+OP8nwlebKNCi/5sdL8qiSLrAcPB4LqdkAf/blNSVA2Yl83/c4\n"
          "lQIBIw==\n"
          "-----END PUBLIC KEY-----\n")

    def test_convert_keys(self):
        result = crypto.convert_from_sshrsa_to_pkcs8(self.k1)
        self.assertEqual(result, self.k2)

    def test_convert_failure(self):
        self.assertRaises(exception.EncryptionFailure,
                          crypto.convert_from_sshrsa_to_pkcs8, '')
