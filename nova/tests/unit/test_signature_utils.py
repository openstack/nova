# Copyright (c) The Johns Hopkins University/Applied Physics Laboratory
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

import base64
import datetime
import mock

from castellan.common.exception import KeyManagerError
import cryptography.exceptions as crypto_exceptions
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import dsa
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
from oslo_utils import timeutils

from nova import exception
from nova import signature_utils
from nova import test

TEST_RSA_PRIVATE_KEY = rsa.generate_private_key(public_exponent=3,
                                                key_size=1024,
                                                backend=default_backend())

# secp521r1 is assumed to be available on all supported platforms
TEST_ECC_PRIVATE_KEY = ec.generate_private_key(ec.SECP521R1(),
                                               default_backend())

TEST_DSA_PRIVATE_KEY = dsa.generate_private_key(key_size=3072,
                                                backend=default_backend())


class FakeKeyManager(object):

    def __init__(self):
        self.certs = {'invalid_format_cert':
                      FakeCastellanCertificate('A' * 256, 'BLAH'),
                      'valid_format_cert':
                      FakeCastellanCertificate('A' * 256, 'X.509')}

    def get(self, context, cert_uuid):
        cert = self.certs.get(cert_uuid)

        if cert is None:
            raise KeyManagerError("No matching certificate found.")

        return cert


class FakeCastellanCertificate(object):

    def __init__(self, data, cert_format):
        self.data = data
        self.cert_format = cert_format

    @property
    def format(self):
        return self.cert_format

    def get_encoded(self):
        return self.data


class FakeCryptoCertificate(object):

    def __init__(self, pub_key=TEST_RSA_PRIVATE_KEY.public_key(),
                 not_valid_before=(timeutils.utcnow() -
                                   datetime.timedelta(hours=1)),
                 not_valid_after=(timeutils.utcnow() +
                                  datetime.timedelta(hours=1))):
        self.pub_key = pub_key
        self.cert_not_valid_before = not_valid_before
        self.cert_not_valid_after = not_valid_after

    def public_key(self):
        return self.pub_key

    @property
    def not_valid_before(self):
        return self.cert_not_valid_before

    @property
    def not_valid_after(self):
        return self.cert_not_valid_after


class BadPublicKey(object):

    def verifier(self, signature, padding, hash_method):
        return None


class TestSignatureUtils(test.NoDBTestCase):
    """Test methods of signature_utils"""

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_PSS(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        mock_get_pub_key.return_value = TEST_RSA_PRIVATE_KEY.public_key()
        for hash_name, hash_alg in signature_utils.HASH_METHODS.items():
            signer = TEST_RSA_PRIVATE_KEY.signer(
                padding.PSS(
                    mgf=padding.MGF1(hash_alg),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hash_alg
            )
            signer.update(data)
            signature = base64.b64encode(signer.finalize())
            img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
            verifier = signature_utils.get_verifier(None, img_sig_cert_uuid,
                                                    hash_name, signature,
                                                    signature_utils.RSA_PSS)
            verifier.update(data)
            verifier.verify()

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_ECC(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        # test every ECC curve
        for curve in signature_utils.ECC_CURVES:
            key_type_name = 'ECC_' + curve.name.upper()
            try:
                signature_utils.SignatureKeyType.lookup(key_type_name)
            except exception.SignatureVerificationError:
                import warnings
                warnings.warn("ECC curve '%s' not supported" % curve.name)
                continue

            # Create a private key to use
            private_key = ec.generate_private_key(curve,
                                                  default_backend())
            mock_get_pub_key.return_value = private_key.public_key()
            for hash_name, hash_alg in signature_utils.HASH_METHODS.items():
                signer = private_key.signer(
                    ec.ECDSA(hash_alg)
                )
                signer.update(data)
                signature = base64.b64encode(signer.finalize())
                img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
                verifier = signature_utils.get_verifier(None,
                                                        img_sig_cert_uuid,
                                                        hash_name, signature,
                                                        key_type_name)
                verifier.update(data)
                verifier.verify()

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_DSA(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        mock_get_pub_key.return_value = TEST_DSA_PRIVATE_KEY.public_key()
        for hash_name, hash_alg in signature_utils.HASH_METHODS.items():
            signer = TEST_DSA_PRIVATE_KEY.signer(
                hash_alg
            )
            signer.update(data)
            signature = base64.b64encode(signer.finalize())
            img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
            verifier = signature_utils.get_verifier(None, img_sig_cert_uuid,
                                                    hash_name, signature,
                                                    signature_utils.DSA)
            verifier.update(data)
            verifier.verify()

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_bad_signature(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        mock_get_pub_key.return_value = TEST_RSA_PRIVATE_KEY.public_key()
        img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
        verifier = signature_utils.get_verifier(None, img_sig_cert_uuid,
                                                'SHA-256', 'BLAH',
                                                signature_utils.RSA_PSS)
        verifier.update(data)
        self.assertRaises(crypto_exceptions.InvalidSignature,
                          verifier.verify)

    def test_get_verifier_invalid_image_props(self):
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Required image properties for signature'
                               ' verification do not exist. Cannot verify'
                               ' signature. Missing property: .*',
                               signature_utils.get_verifier,
                               None, None, 'SHA-256', 'BLAH',
                               signature_utils.RSA_PSS)

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_bad_sig_key_type(self, mock_get_pub_key):
        mock_get_pub_key.return_value = TEST_RSA_PRIVATE_KEY.public_key()
        img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid signature key type: .*',
                               signature_utils.get_verifier,
                               None, img_sig_cert_uuid, 'SHA-256',
                               'BLAH', 'BLAH')

    @mock.patch('nova.signature_utils.get_public_key')
    def test_get_verifier_none(self, mock_get_pub_key):
        mock_get_pub_key.return_value = BadPublicKey()
        img_sig_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0693'
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Error occurred while creating'
                               ' the verifier',
                               signature_utils.get_verifier,
                               None, img_sig_cert_uuid, 'SHA-256',
                               'BLAH', signature_utils.RSA_PSS)

    def test_get_signature(self):
        signature = b'A' * 256
        data = base64.b64encode(signature)
        self.assertEqual(signature,
                         signature_utils.get_signature(data))

    def test_get_signature_fail(self):
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'The signature data was not properly'
                               ' encoded using base64',
                               signature_utils.get_signature, '///')

    def test_get_hash_method(self):
        hash_dict = signature_utils.HASH_METHODS
        for hash_name in hash_dict.keys():
            hash_class = signature_utils.get_hash_method(hash_name).__class__
            self.assertIsInstance(hash_dict[hash_name], hash_class)

    def test_get_hash_method_fail(self):
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid signature hash method: .*',
                               signature_utils.get_hash_method, 'SHA-2')

    def test_signature_key_type_lookup(self):
        for sig_format in [signature_utils.RSA_PSS, signature_utils.DSA]:
            sig_key_type = signature_utils.SignatureKeyType.lookup(sig_format)
            self.assertIsInstance(sig_key_type,
                                  signature_utils.SignatureKeyType)
            self.assertEqual(sig_format, sig_key_type.name)

    def test_signature_key_type_lookup_fail(self):
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid signature key type: .*',
                               signature_utils.SignatureKeyType.lookup,
                               'RSB-PSS')

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_rsa(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate()
        mock_get_cert.return_value = fake_cert
        sig_key_type = signature_utils.SignatureKeyType.lookup(
                           signature_utils.RSA_PSS
                       )
        result_pub_key = signature_utils.get_public_key(None, None,
                                                        sig_key_type)
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_ecc(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate(TEST_ECC_PRIVATE_KEY.public_key())
        mock_get_cert.return_value = fake_cert
        sig_key_type = signature_utils.SignatureKeyType.lookup('ECC_SECP521R1')
        result_pub_key = signature_utils.get_public_key(None, None,
                                                        sig_key_type)
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_dsa(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate(TEST_DSA_PRIVATE_KEY.public_key())
        mock_get_cert.return_value = fake_cert
        sig_key_type = signature_utils.SignatureKeyType.lookup(
                           signature_utils.DSA
                       )
        result_pub_key = signature_utils.get_public_key(None, None,
                                                        sig_key_type)
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_invalid_key(self, mock_get_certificate):
        bad_pub_key = 'A' * 256
        mock_get_certificate.return_value = FakeCryptoCertificate(bad_pub_key)
        sig_key_type = signature_utils.SignatureKeyType.lookup(
                           signature_utils.RSA_PSS
                       )
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid public key type for '
                               'signature key type: .*',
                               signature_utils.get_public_key, None,
                               None, sig_key_type)

    @mock.patch('cryptography.x509.load_der_x509_certificate')
    @mock.patch('castellan.key_manager.API', return_value=FakeKeyManager())
    def test_get_certificate(self, mock_key_manager_API, mock_load_cert):
        cert_uuid = 'valid_format_cert'
        x509_cert = FakeCryptoCertificate()
        mock_load_cert.return_value = x509_cert
        self.assertEqual(x509_cert,
                         signature_utils.get_certificate(None, cert_uuid))

    @mock.patch('cryptography.x509.load_der_x509_certificate')
    @mock.patch('castellan.key_manager.API', return_value=FakeKeyManager())
    def test_get_expired_certificate(self, mock_key_manager_API,
                                     mock_load_cert):
        cert_uuid = 'valid_format_cert'
        x509_cert = FakeCryptoCertificate(
            not_valid_after=timeutils.utcnow() -
            datetime.timedelta(hours=1))
        mock_load_cert.return_value = x509_cert
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Certificate is not valid after: .*',
                               signature_utils.get_certificate, None,
                               cert_uuid)

    @mock.patch('cryptography.x509.load_der_x509_certificate')
    @mock.patch('castellan.key_manager.API', return_value=FakeKeyManager())
    def test_get_not_yet_valid_certificate(self, mock_key_manager_API,
                                           mock_load_cert):
        cert_uuid = 'valid_format_cert'
        x509_cert = FakeCryptoCertificate(
            not_valid_before=timeutils.utcnow() +
            datetime.timedelta(hours=1))
        mock_load_cert.return_value = x509_cert
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Certificate is not valid before: .*',
                               signature_utils.get_certificate, None,
                               cert_uuid)

    @mock.patch('castellan.key_manager.API', return_value=FakeKeyManager())
    def test_get_certificate_key_manager_fail(self, mock_key_manager_API):
        bad_cert_uuid = 'fea14bc2-d75f-4ba5-bccc-b5c924ad0695'
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Unable to retrieve certificate with ID: .*',
                               signature_utils.get_certificate, None,
                               bad_cert_uuid)

    @mock.patch('castellan.key_manager.API', return_value=FakeKeyManager())
    def test_get_certificate_invalid_format(self, mock_API):
        cert_uuid = 'invalid_format_cert'
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid certificate format: .*',
                               signature_utils.get_certificate, None,
                               cert_uuid)
