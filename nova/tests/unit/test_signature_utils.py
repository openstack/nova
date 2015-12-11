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

TEST_ECC_PRIVATE_KEY = ec.generate_private_key(ec.SECP521R1(),
                                               default_backend())

TEST_DSA_PRIVATE_KEY = dsa.generate_private_key(key_size=3072,
                                                backend=default_backend())

# ECC curves, for generating private keys
ECC_CURVE_METHODS = {
    signature_utils.ECC_SECT571K1: ec.SECT571K1(),
    signature_utils.ECC_SECT409K1: ec.SECT409K1(),
    signature_utils.ECC_SECT571R1: ec.SECT571R1(),
    signature_utils.ECC_SECT409R1: ec.SECT409R1(),
    signature_utils.ECC_SECP521R1: ec.SECP521R1(),
    signature_utils.ECC_SECP384R1: ec.SECP384R1(),
}

# Required image property names
SIGNATURE = signature_utils.SIGNATURE
HASH_METHOD = signature_utils.HASH_METHOD
KEY_TYPE = signature_utils.KEY_TYPE
CERT_UUID = signature_utils.CERT_UUID


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

    def test_should_verify_signature(self):
        image_props = {CERT_UUID: 'CERT_UUID',
                       HASH_METHOD: 'HASH_METHOD',
                       SIGNATURE: 'SIGNATURE',
                       KEY_TYPE: 'SIG_KEY_TYPE'}
        self.assertTrue(signature_utils.should_verify_signature(image_props))

    def test_should_verify_signature_fail(self):
        bad_image_properties = [{CERT_UUID: 'CERT_UUID',
                                 HASH_METHOD: 'HASH_METHOD',
                                 SIGNATURE: 'SIGNATURE'},
                                {CERT_UUID: 'CERT_UUID',
                                 HASH_METHOD: 'HASH_METHOD',
                                 KEY_TYPE: 'SIG_KEY_TYPE'},
                                {CERT_UUID: 'CERT_UUID',
                                 SIGNATURE: 'SIGNATURE',
                                 KEY_TYPE: 'SIG_KEY_TYPE'},
                                {HASH_METHOD: 'HASH_METHOD',
                                 SIGNATURE: 'SIGNATURE',
                                 KEY_TYPE: 'SIG_KEY_TYPE'}]

        for bad_props in bad_image_properties:
            result = signature_utils.should_verify_signature(bad_props)
            self.assertFalse(result)

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
            image_props = {CERT_UUID:
                           'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                           HASH_METHOD: hash_name,
                           KEY_TYPE: 'RSA-PSS',
                           SIGNATURE: signature}
            verifier = signature_utils.get_verifier(None, image_props)
            verifier.update(data)
            verifier.verify()

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_ECC(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        # test every ECC curve
        for curve_name, curve_method in ECC_CURVE_METHODS.items():
            # Create a private key to use
            private_key = ec.generate_private_key(curve_method,
                                                  default_backend())
            mock_get_pub_key.return_value = private_key.public_key()
            for hash_name, hash_alg in signature_utils.HASH_METHODS.items():
                signer = private_key.signer(
                    ec.ECDSA(hash_alg)
                )
                signer.update(data)
                signature = base64.b64encode(signer.finalize())
                image_props = {CERT_UUID:
                               'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                               HASH_METHOD: hash_name,
                               KEY_TYPE: curve_name,
                               SIGNATURE: signature}
                verifier = signature_utils.get_verifier(None, image_props)
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
            image_props = {CERT_UUID:
                           'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                           HASH_METHOD: hash_name,
                           KEY_TYPE: 'DSA',
                           SIGNATURE: signature}
            verifier = signature_utils.get_verifier(None, image_props)
            verifier.update(data)
            verifier.verify()

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_bad_signature(self, mock_get_pub_key):
        data = b'224626ae19824466f2a7f39ab7b80f7f'
        mock_get_pub_key.return_value = TEST_RSA_PRIVATE_KEY.public_key()
        image_properties = {CERT_UUID:
                            'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                            HASH_METHOD: 'SHA-256',
                            KEY_TYPE: 'RSA-PSS',
                            SIGNATURE: 'BLAH'}
        verifier = signature_utils.get_verifier(None, image_properties)
        verifier.update(data)
        self.assertRaises(crypto_exceptions.InvalidSignature,
                          verifier.verify)

    @mock.patch('nova.signature_utils.should_verify_signature')
    def test_get_verifier_invalid_image_props(self, mock_should):
        mock_should.return_value = False
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Required image properties for signature'
                               ' verification do not exist. Cannot verify'
                               ' signature.',
                               signature_utils.get_verifier,
                               None, None)

    @mock.patch('nova.signature_utils.get_public_key')
    def test_verify_signature_bad_sig_key_type(self, mock_get_pub_key):
        mock_get_pub_key.return_value = TEST_RSA_PRIVATE_KEY.public_key()
        image_properties = {CERT_UUID:
                            'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                            HASH_METHOD: 'SHA-256',
                            KEY_TYPE: 'BLAH',
                            SIGNATURE: 'BLAH'}
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid signature key type: .*',
                               signature_utils.get_verifier,
                               None, image_properties)

    @mock.patch('nova.signature_utils.get_public_key')
    def test_get_verifier_none(self, mock_get_pub_key):
        mock_get_pub_key.return_value = BadPublicKey()
        image_properties = {CERT_UUID:
                            'fea14bc2-d75f-4ba5-bccc-b5c924ad0693',
                            HASH_METHOD: 'SHA-256',
                            KEY_TYPE: 'RSA-PSS',
                            SIGNATURE: 'BLAH'}
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Error occurred while creating'
                               ' the verifier',
                               signature_utils.get_verifier,
                               None, image_properties)

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

    def test_get_signature_key_type(self):
        for sig_format in signature_utils.SIGNATURE_KEY_TYPES:
            result = signature_utils.get_signature_key_type(sig_format)
            self.assertEqual(sig_format, result)

    def test_get_signature_key_type_fail(self):
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid signature key type: .*',
                               signature_utils.get_signature_key_type,
                               'RSB-PSS')

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_rsa(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate()
        mock_get_cert.return_value = fake_cert
        result_pub_key = signature_utils.get_public_key(None, None, 'RSA-PSS')
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_ecc(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate(TEST_ECC_PRIVATE_KEY.public_key())
        mock_get_cert.return_value = fake_cert
        result_pub_key = signature_utils.get_public_key(None, None,
                                                        'ECC_SECP521R1')
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_dsa(self, mock_get_cert):
        fake_cert = FakeCryptoCertificate(TEST_DSA_PRIVATE_KEY.public_key())
        mock_get_cert.return_value = fake_cert
        result_pub_key = signature_utils.get_public_key(None, None, 'DSA')
        self.assertEqual(fake_cert.public_key(), result_pub_key)

    @mock.patch('nova.signature_utils.get_certificate')
    def test_get_public_key_invalid_key(self, mock_get_certificate):
        bad_pub_key = 'A' * 256
        mock_get_certificate.return_value = FakeCryptoCertificate(bad_pub_key)
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Invalid public key type for '
                               'signature key type: .*',
                               signature_utils.get_public_key, None,
                               None, 'RSA-PSS')

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
