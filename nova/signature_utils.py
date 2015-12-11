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

"""Support signature verification."""

import binascii

from castellan.common.exception import KeyManagerError
from castellan import key_manager
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import dsa
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography import x509
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_utils import encodeutils
from oslo_utils import timeutils

from nova import exception
from nova.i18n import _, _LE

LOG = logging.getLogger(__name__)


HASH_METHODS = {
    'SHA-224': hashes.SHA224(),
    'SHA-256': hashes.SHA256(),
    'SHA-384': hashes.SHA384(),
    'SHA-512': hashes.SHA512(),
}

# Currently supported signature key types
# RSA Options
RSA_PSS = 'RSA-PSS'
# ECC Options -- note that only those with key sizes >=384 are included
ECC_SECT571K1 = 'ECC_SECT571K1'
ECC_SECT409K1 = 'ECC_SECT409K1'
ECC_SECT571R1 = 'ECC_SECT571R1'
ECC_SECT409R1 = 'ECC_SECT409R1'
ECC_SECP521R1 = 'ECC_SECP521R1'
ECC_SECP384R1 = 'ECC_SECP384R1'
# DSA Options
DSA = 'DSA'

# This includes the supported public key type for the signature key type
SIGNATURE_KEY_TYPES = {
    RSA_PSS: rsa.RSAPublicKey,
    ECC_SECT571K1: ec.EllipticCurvePublicKey,
    ECC_SECT409K1: ec.EllipticCurvePublicKey,
    ECC_SECT571R1: ec.EllipticCurvePublicKey,
    ECC_SECT409R1: ec.EllipticCurvePublicKey,
    ECC_SECP521R1: ec.EllipticCurvePublicKey,
    ECC_SECP384R1: ec.EllipticCurvePublicKey,
    DSA: dsa.DSAPublicKey,
}

# These are the currently supported certificate formats
X_509 = 'X.509'

CERTIFICATE_FORMATS = {
    X_509,
}

# These are the currently supported MGF formats, used for RSA-PSS signatures
MASK_GEN_ALGORITHMS = {
    'MGF1': padding.MGF1,
}

# Required image property names
SIGNATURE = 'img_signature'
HASH_METHOD = 'img_signature_hash_method'
KEY_TYPE = 'img_signature_key_type'
CERT_UUID = 'img_signature_certificate_uuid'


# each key type will require its own verifier
def create_verifier_for_pss(signature, hash_method, public_key,
                            image_properties):
    """Create the verifier to use when the key type is RSA-PSS.

    :param signature: the decoded signature to use
    :param hash_method: the hash method to use, as a cryptography object
    :param public_key: the public key to use, as a cryptography object
    :param image_properties: the key-value properties about the image
    :returns: the verifier to use to verify the signature for RSA-PSS
    :raises: SignatureVerificationError if the RSA-PSS specific properties
                                        are invalid
    """
    # default to MGF1
    mgf = padding.MGF1(hash_method)

    # default to max salt length
    salt_length = padding.PSS.MAX_LENGTH

    # return the verifier
    return public_key.verifier(
        signature,
        padding.PSS(mgf=mgf, salt_length=salt_length),
        hash_method
    )


def create_verifier_for_ecc(signature, hash_method, public_key,
                            image_properties):
    """Create the verifier to use when the key type is ECC_*.

    :param signature: the decoded signature to use
    :param hash_method: the hash method to use, as a cryptography object
    :param public_key: the public key to use, as a cryptography object
    :param image_properties: the key-value properties about the image
    :returns: the verifier to use to verify the signature for ECC_*.
    """
    # return the verifier
    return public_key.verifier(
        signature,
        ec.ECDSA(hash_method)
    )


def create_verifier_for_dsa(signature, hash_method, public_key,
                            image_properties):
    """Create the verifier to use when the key type is DSA

    :param signature: the decoded signature to use
    :param hash_method: the hash method to use, as a cryptography object
    :param public_key: the public key to use, as a cryptography object
    :param image_properties: the key-value properties about the image
    :returns: the verifier to use to verify the signature for DSA
    """
    # return the verifier
    return public_key.verifier(
        signature,
        hash_method
    )

# map the key type to the verifier function to use
KEY_TYPE_METHODS = {
    RSA_PSS: create_verifier_for_pss,
    ECC_SECT571K1: create_verifier_for_ecc,
    ECC_SECT409K1: create_verifier_for_ecc,
    ECC_SECT571R1: create_verifier_for_ecc,
    ECC_SECT409R1: create_verifier_for_ecc,
    ECC_SECP521R1: create_verifier_for_ecc,
    ECC_SECP384R1: create_verifier_for_ecc,
    DSA: create_verifier_for_dsa,
}


def should_verify_signature(image_properties):
    """Determine whether a signature should be verified.

    Using the image properties, determine whether existing properties indicate
    that signature verification should be done.

    :param image_properties: the key-value properties about the image
    :returns: True, if signature metadata properties exist, False otherwise
    """
    return (image_properties is not None and
            CERT_UUID in image_properties and
            HASH_METHOD in image_properties and
            SIGNATURE in image_properties and
            KEY_TYPE in image_properties)


def get_verifier(context, image_properties):
    """Retrieve the image properties and use them to create a verifier.

    :param context: the user context for authentication
    :param image_properties: the key-value properties about the image
    :returns: instance of
    cryptography.hazmat.primitives.asymmetric.AsymmetricVerificationContext
    :raises: SignatureVerificationError if we fail to build the verifier
    """
    if not should_verify_signature(image_properties):
        raise exception.SignatureVerificationError(
            reason=_('Required image properties for signature verification'
                     ' do not exist. Cannot verify signature.'))

    signature = get_signature(image_properties[SIGNATURE])
    hash_method = get_hash_method(image_properties[HASH_METHOD])
    signature_key_type = get_signature_key_type(
        image_properties[KEY_TYPE])
    public_key = get_public_key(context,
                                image_properties[CERT_UUID],
                                signature_key_type)

    # create the verifier based on the signature key type
    verifier = KEY_TYPE_METHODS[signature_key_type](signature,
                                                    hash_method,
                                                    public_key,
                                                    image_properties)

    if verifier:
        return verifier
    else:
        # Error creating the verifier
        raise exception.SignatureVerificationError(
            reason=_('Error occurred while creating the verifier'))


def get_signature(signature_data):
    """Decode the signature data and returns the signature.

    :param siganture_data: the base64-encoded signature data
    :returns: the decoded signature
    :raises: SignatureVerificationError if the signature data is malformatted
    """
    try:
        signature = base64.decode_as_bytes(signature_data)
    except (TypeError, binascii.Error):
        raise exception.SignatureVerificationError(
            reason=_('The signature data was not properly '
                     'encoded using base64'))

    return signature


def get_hash_method(hash_method_name):
    """Verify the hash method name and create the hash method.

    :param hash_method_name: the name of the hash method to retrieve
    :returns: the hash method, a cryptography object
    :raises: SignatureVerificationError if the hash method name is invalid
    """
    if hash_method_name not in HASH_METHODS:
        raise exception.SignatureVerificationError(
            reason=_('Invalid signature hash method: %s') % hash_method_name)

    return HASH_METHODS[hash_method_name]


def get_signature_key_type(signature_key_type):
    """Verify the signature key type.

    :param signature_key_type: the key type of the signature
    :returns: the validated signature key type
    :raises: SignatureVerificationError if the signature key type is invalid
    """
    if signature_key_type not in SIGNATURE_KEY_TYPES:
        raise exception.SignatureVerificationError(
            reason=_('Invalid signature key type: %s') % signature_key_type)

    return signature_key_type


def get_public_key(context, signature_certificate_uuid, signature_key_type):
    """Create the public key object from a retrieved certificate.

    :param context: the user context for authentication
    :param signature_certificate_uuid: the uuid to use to retrieve the
                                       certificate
    :param signature_key_type: the key type of the signature
    :returns: the public key cryptography object
    :raises: SignatureVerificationError if public key format is invalid
    """
    certificate = get_certificate(context, signature_certificate_uuid)

    # Note that this public key could either be
    # RSAPublicKey, DSAPublicKey, or EllipticCurvePublicKey
    public_key = certificate.public_key()

    # Confirm the type is of the type expected based on the signature key type
    if not isinstance(public_key, SIGNATURE_KEY_TYPES[signature_key_type]):
        raise exception.SignatureVerificationError(
            reason=_('Invalid public key type for signature key type: %s')
            % signature_key_type)

    return public_key


def get_certificate(context, signature_certificate_uuid):
    """Create the certificate object from the retrieved certificate data.

    :param context: the user context for authentication
    :param signature_certificate_uuid: the uuid to use to retrieve the
                                       certificate
    :returns: the certificate cryptography object
    :raises: SignatureVerificationError if the retrieval fails or the format
             is invalid
    """
    keymgr_api = key_manager.API()

    try:
        # The certificate retrieved here is a castellan certificate object
        cert = keymgr_api.get(context, signature_certificate_uuid)
    except KeyManagerError as e:
        # The problem encountered may be backend-specific, since castellan
        # can use different backends.  Rather than importing all possible
        # backends here, the generic "Exception" is used.
        msg = (_LE("Unable to retrieve certificate with ID %(id)s: %(e)s")
               % {'id': signature_certificate_uuid,
                  'e': encodeutils.exception_to_unicode(e)})
        LOG.error(msg)
        raise exception.SignatureVerificationError(
            reason=_('Unable to retrieve certificate with ID: %s')
            % signature_certificate_uuid)

    if cert.format not in CERTIFICATE_FORMATS:
        raise exception.SignatureVerificationError(
            reason=_('Invalid certificate format: %s') % cert.format)

    if cert.format == X_509:
        # castellan always encodes certificates in DER format
        cert_data = cert.get_encoded()
        certificate = x509.load_der_x509_certificate(cert_data,
                                                     default_backend())

    # verify the certificate
    verify_certificate(certificate)

    return certificate


def verify_certificate(certificate):
    """Verify that the certificate has not expired.

    :param certificate: the cryptography certificate object
    :raises: SignatureVerificationError if the certificate valid time range
             does not include now
    """
    # Get now in UTC, since certificate returns times in UTC
    now = timeutils.utcnow()

    # Confirm the certificate valid time range includes now
    if now < certificate.not_valid_before:
        raise exception.SignatureVerificationError(
            reason=_('Certificate is not valid before: %s UTC')
            % certificate.not_valid_before)
    elif now > certificate.not_valid_after:
        raise exception.SignatureVerificationError(
            reason=_('Certificate is not valid after: %s UTC')
            % certificate.not_valid_after)
