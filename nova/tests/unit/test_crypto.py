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
import uuid

from cryptography.hazmat import backends
from cryptography.hazmat.primitives import serialization
import mock
from oslo_concurrency import processutils
import paramiko
import six

from nova import crypto
from nova import exception
from nova import test
from nova import utils


class X509Test(test.NoDBTestCase):
    @mock.patch('nova.db.certificate_create')
    def test_can_generate_x509(self, mock_create):
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
            process_input = text.encode("ascii") if six.PY3 else text
            enc, _err = utils.execute('openssl',
                                     'rsautl',
                                     '-certin',
                                     '-encrypt',
                                     '-inkey', '%s' % public_key,
                                     process_input=process_input,
                                     binary=True)

            dec = crypto.decrypt_text(project_id, enc)
            self.assertIsInstance(dec, bytes)
            if six.PY3:
                dec = dec.decode('ascii')
            self.assertEqual(text, dec)

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError)
    def test_ensure_ca_filesystem_chdir(self, *args, **kargs):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
            start = os.getcwd()
            self.assertRaises(processutils.ProcessExecutionError,
                              crypto.ensure_ca_filesystem)
            self.assertEqual(start, os.getcwd())


class RevokeCertsTest(test.NoDBTestCase):

    @mock.patch('nova.crypto.revoke_cert')
    def test_revoke_certs_by_user_and_project(self, mock_revoke):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_user_and_project(context,
                                                         user_id,
                                                         project_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stub_out('nova.db.certificate_get_all_by_user_and_project',
                      mock_certificate_get_all_by_user_and_project)

        crypto.revoke_certs_by_user_and_project(user_id, project_id)

        mock_revoke.assert_called_once_with(project_id, file_name)

    @mock.patch('nova.crypto.revoke_cert')
    def test_revoke_certs_by_user(self, mock_revoke):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_user(context, user_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stub_out('nova.db.certificate_get_all_by_user',
                      mock_certificate_get_all_by_user)

        crypto.revoke_certs_by_user(user_id)
        mock_revoke.assert_called_once_with(project_id, mock.ANY)

    @mock.patch('nova.crypto.revoke_cert')
    def test_revoke_certs_by_project(self, mock_revoke):
        user_id = 'test_user'
        project_id = 2
        file_name = 'test_file'

        def mock_certificate_get_all_by_project(context, project_id):

            return [{"user_id": user_id, "project_id": project_id,
                                          "file_name": file_name}]

        self.stub_out('nova.db.certificate_get_all_by_project',
                      mock_certificate_get_all_by_project)

        crypto.revoke_certs_by_project(project_id)
        mock_revoke.assert_called_once_with(project_id, mock.ANY)

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError)
    @mock.patch.object(os, 'chdir', return_value=None)
    def test_revoke_cert_process_execution_error(self, *args, **kargs):
        self.assertRaises(exception.RevokeCertFailure, crypto.revoke_cert,
                          2, 'test_file')

    def test_revoke_cert_project_not_found_chdir_fails(self, *args, **kargs):
        self.flags(use_project_ca=True)
        self.assertRaises(exception.ProjectNotFound, crypto.revoke_cert,
                          str(uuid.uuid4()), 'test_file')


class CertExceptionTests(test.NoDBTestCase):
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


class EncryptionTests(test.NoDBTestCase):
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
                                          process_input=text,
                                          binary=True)
                return dec
            except processutils.ProcessExecutionError as exc:
                raise exception.DecryptionFailure(reason=exc.stderr)

    def test_ssh_encrypt_decrypt_text(self):
        self._test_ssh_encrypt_decrypt_text(self.pubkey)
        key_with_spaces_in_comment = self.pubkey.replace('test@test',
                                                         'Generated by Nova')
        self._test_ssh_encrypt_decrypt_text(key_with_spaces_in_comment)

    def _test_ssh_encrypt_decrypt_text(self, key):
        enc = crypto.ssh_encrypt_text(self.pubkey, self.text)
        self.assertIsInstance(enc, bytes)
        # Comparison between bytes and str raises a TypeError
        # when using python3 -bb
        if six.PY2:
            self.assertNotEqual(enc, self.text)
        result = self._ssh_decrypt_text(self.prikey, enc)
        self.assertIsInstance(result, bytes)
        if six.PY3:
            result = result.decode('utf-8')
        self.assertEqual(result, self.text)

    def test_ssh_encrypt_failure(self):
        self.assertRaises(exception.EncryptionFailure,
                          crypto.ssh_encrypt_text, '', self.text)


class KeyPairTest(test.NoDBTestCase):
    rsa_prv = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA5G44D6lEgMj6cRwCPydsMl1VRN2B9DVyV5lmwssGeJClywZM\n"
        "WcKlSZBaWPbwbt20/r74eMGZPlqtEi9Ro+EHj4/n5+3A2Mh11h0PGSt53PSPfWwo\n"
        "ZhEg9hQ1w1ZxfBMCx7eG2YdGFQocMgR0zQasJGjjt8hruCnWRB3pNH9DhEwKhgET\n"
        "H0/CFzxSh0eZWs/O4GSf4upwmRG/1Yu90vnVZq3AanwvvW5UBk6g4uWb6FTES867\n"
        "kAy4b5EcH6WR3lLE09omuG/NqtH+qkgIdQconDkmkuK3xf5go6GSwEod0erM1G1v\n"
        "e+C4w/MD98KZ4Zlon9hy7oE2rcqHXf58gZtOTQIDAQABAoIBAQCnkeM2Oemyv7xY\n"
        "dT+ArJ7GY4lFt2i5iOuUL0ge5Wid0R6OTNR9lDhEOszMLno6GhHIPrdvfjW4dDQ5\n"
        "/tRY757oRZzNmq+5V3R52V9WC3qeCBmq3EjWdwJDAphd72/YoOmNMKiPsphKntwI\n"
        "JRS5wodNPlSuYSwEMUypM3f7ttAEn5CASgYgribBDapm7EqkVa2AqSvpFzNvN3/e\n"
        "Sc36/XlxJin7AkKVOnRksuVOOj504VUQfXgVWZkfTeZqAROgA1FSnjUAffcubJmq\n"
        "pDL/JSgOqN4S+sJkkTrb19MuM9M/IdXteloynF+GUKZx6FdVQQc8xCiXgeupeeSD\n"
        "fNMAP7DRAoGBAP0JRFm3fCAavBREKVOyZm20DpeR6zMrVP7ht0SykkT/bw/kiRG+\n"
        "FH1tNioj9uyixt5SiKhH3ZVAunjsKvrwET8i3uz1M2Gk+ovWdLXurBogYNNWafjQ\n"
        "hRhFHpyExoZYRsn58bvYvjFXTO6JxuNS2b59DGBRkQ5mpsOhxarfbZnXAoGBAOcb\n"
        "K+qoPDeDicnQZ8+ygYYHxY3fy1nvm1F19jBiWd26bAUOHeZNPPKGvTSlrGWJgEyA\n"
        "FjZIlHJOY2s0dhukiytOiXzdA5iqK1NvlF+QTUI4tCeNMVejWC+n6sKR9ADZkX8D\n"
        "NOHaLkDzc/ukus59aKyjxP53I6SV6y6m5NeyvDx7AoGAaUji1MXA8wbMvU4DOB0h\n"
        "+4GRFMYVbEwaaJd4jzASJn12M9GuquBBXFMF15DxXFL6lmUXEZYdf83YCRqTY6hi\n"
        "NLgIs+XuxDFGQssv8sdletWAFE9/dpUk3A1eiFfC1wGCKuZCDBxKPvOJQjO3uryt\n"
        "d1JGxQkLZ0eVGg+E1O10iC8CgYB4w2QRfNPqllu8D6EPkVHJfeonltgmKOTajm+V\n"
        "HO+kw7OKeLP7EkVU3j+kcSZC8LUQRKZWu1qG2Jtu+7zz+OmYObPygXNNpS56rQW1\n"
        "Yixc/FB3knpEN2DvlilAfxAoGYjD/CL4GhCtdAoZZx0Opc262OEpr4v6hzSb7i4K\n"
        "4KUoXQKBgHfbiaSilxx9guUqvSaexpHmtiUwx05a05fD6tu8Cofl6AM9wGpw3xOT\n"
        "tfo4ehvS13tTz2RDE2xKuetMmkya7UgifcxUmBzqkOlgr0oOi2rp+eDKXnzUUqsH\n"
        "V7E96Dj36K8q2+gZIXcNqjN7PzfkF8pA0G+E1veTi8j5dnvIsy1x\n"
        "-----END RSA PRIVATE KEY-----\n"
    )

    rsa_pub = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDkbjgPqUSAyPpxHAI/J2wyXVVE"
        "3YH0NXJXmWbCywZ4kKXLBkxZwqVJkFpY9vBu3bT+vvh4wZk+Wq0SL1Gj4QePj+fn"
        "7cDYyHXWHQ8ZK3nc9I99bChmESD2FDXDVnF8EwLHt4bZh0YVChwyBHTNBqwkaOO3"
        "yGu4KdZEHek0f0OETAqGARMfT8IXPFKHR5laz87gZJ/i6nCZEb/Vi73S+dVmrcBq"
        "fC+9blQGTqDi5ZvoVMRLzruQDLhvkRwfpZHeUsTT2ia4b82q0f6qSAh1ByicOSaS"
        "4rfF/mCjoZLASh3R6szUbW974LjD8wP3wpnhmWif2HLugTatyodd/nyBm05N Gen"
        "erated-by-Nova"
    )

    rsa_fp = "e7:66:a1:2c:4f:90:6e:11:19:da:ac:c2:69:e1:ad:89"

    dss_pub = (
        "ssh-dss AAAAB3NzaC1kc3MAAACBAKWFW2++pDxJWObkADbSXw8KfZ4VupkRKEXF"
        "SPN2kV0v+FgdnBEcrEJPExaOTMhmxIuc82ktTv76wHSEpbbsLuI7IDbB6KJJwHs2"
        "y356yB28Q9rin7X0VMYKkPxvAcbIUSrEbQtyPMihlOaaQ2dGSsEQGQSpjm3f3RU6"
        "OWux0w/NAAAAFQCgzWF2zxQmi/Obd11z9Im6gY02gwAAAIAHCDLjipVwMLXIqNKO"
        "MktiPex+ewRQxBi80dzZ3mJzARqzLPYI9hJFUU0LiMtLuypV/djpUWN0cQpmgTQf"
        "TfuZx9ipC6Mtiz66NQqjkQuoihzdk+9KlOTo03UsX5uBGwuZ09Dnf1VTF8ZsW5Hg"
        "HyOk6qD71QBajkcFJAKOT3rFfgAAAIAy8trIzqEps9/n37Nli1TvNPLbFQAXl1LN"
        "wUFmFDwBCGTLl8puVZv7VSu1FG8ko+mzqNebqcN4RMC26NxJqe+RRubn5KtmLoIa"
        "7tRe74hvQ1HTLLuGxugwa4CewNbwzzEDEs8U79WDhGKzDkJR4nLPVimj5WLAWV70"
        "RNnRX7zj5w== Generated-by-Nova"
    )

    dss_fp = "b9:dc:ac:57:df:2a:2b:cf:65:a8:c3:4e:9d:4a:82:3c"

    ecdsa_pub = (
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAy"
        "NTYAAABBBG1r4wzPTIjSo78POCq+u/czb8gYK0KvqlmCvcRPrnDWxgLw7y6BX51t"
        "uYREz7iLRCP7BwUt8R+ZWzFZDeOLIWU= Generated-by-Nova"
    )

    ecdsa_pub_with_spaces = (
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAy"
        "NTYAAABBBG1r4wzPTIjSo78POCq+u/czb8gYK0KvqlmCvcRPrnDWxgLw7y6BX51t"
        "uYREz7iLRCP7BwUt8R+ZWzFZDeOLIWU= Generated by Nova"
    )

    ecdsa_fp = "16:6a:c9:ec:80:4d:17:3e:d5:3b:6f:c0:d7:15:04:40"

    def test_generate_fingerprint(self):
        fingerprint = crypto.generate_fingerprint(self.rsa_pub)
        self.assertEqual(self.rsa_fp, fingerprint)

        fingerprint = crypto.generate_fingerprint(self.dss_pub)
        self.assertEqual(self.dss_fp, fingerprint)

        fingerprint = crypto.generate_fingerprint(self.ecdsa_pub)
        self.assertEqual(self.ecdsa_fp, fingerprint)

        fingerprint = crypto.generate_fingerprint(self.ecdsa_pub_with_spaces)
        self.assertEqual(self.ecdsa_fp, fingerprint)

    def test_generate_key_pair_2048_bits(self):
        (private_key, public_key, fingerprint) = crypto.generate_key_pair()
        pub_bytes = public_key.encode('utf-8')
        pkey = serialization.load_ssh_public_key(
            pub_bytes, backends.default_backend())
        self.assertEqual(2048, pkey.key_size)

    def test_generate_key_pair_1024_bits(self):
        bits = 1024
        (private_key, public_key, fingerprint) = crypto.generate_key_pair(bits)
        pub_bytes = public_key.encode('utf-8')
        pkey = serialization.load_ssh_public_key(
            pub_bytes, backends.default_backend())
        self.assertEqual(bits, pkey.key_size)

    def test_generate_key_pair_mocked_private_key(self):
        keyin = six.StringIO()
        keyin.write(self.rsa_prv)
        keyin.seek(0)
        key = paramiko.RSAKey.from_private_key(keyin)

        with mock.patch.object(crypto, 'generate_key') as mock_generate:
            mock_generate.return_value = key
            (private_key, public_key, fingerprint) = crypto.generate_key_pair()
            self.assertEqual(self.rsa_pub, public_key)
            self.assertEqual(self.rsa_fp, fingerprint)
