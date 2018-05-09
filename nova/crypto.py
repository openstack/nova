# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Wrappers around standard crypto data elements.

Includes root and intermediate CAs, SSH key_pairs and x509 certificates.
"""

from __future__ import absolute_import

import base64
import binascii
import os

from cryptography.hazmat import backends
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from oslo_concurrency import processutils
from oslo_log import log as logging
import paramiko
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


def generate_fingerprint(public_key):
    try:
        pub_bytes = public_key.encode('utf-8')
        # Test that the given public_key string is a proper ssh key. The
        # returned object is unused since pyca/cryptography does not have a
        # fingerprint method.
        serialization.load_ssh_public_key(
            pub_bytes, backends.default_backend())
        pub_data = base64.b64decode(public_key.split(' ')[1])
        digest = hashes.Hash(hashes.MD5(), backends.default_backend())
        digest.update(pub_data)
        md5hash = digest.finalize()
        raw_fp = binascii.hexlify(md5hash)
        if six.PY3:
            raw_fp = raw_fp.decode('ascii')
        return ':'.join(a + b for a, b in zip(raw_fp[::2], raw_fp[1::2]))
    except Exception:
        raise exception.InvalidKeypair(
            reason=_('failed to generate fingerprint'))


def generate_x509_fingerprint(pem_key):
    try:
        if isinstance(pem_key, six.text_type):
            pem_key = pem_key.encode('utf-8')
        cert = x509.load_pem_x509_certificate(
            pem_key, backends.default_backend())
        raw_fp = binascii.hexlify(cert.fingerprint(hashes.SHA1()))
        if six.PY3:
            raw_fp = raw_fp.decode('ascii')
        return ':'.join(a + b for a, b in zip(raw_fp[::2], raw_fp[1::2]))
    except (ValueError, TypeError, binascii.Error) as ex:
        raise exception.InvalidKeypair(
            reason=_('failed to generate X509 fingerprint. '
                     'Error message: %s') % ex)


def generate_key_pair(bits=2048):
    key = paramiko.RSAKey.generate(bits)
    keyout = six.StringIO()
    key.write_private_key(keyout)
    private_key = keyout.getvalue()
    public_key = '%s %s Generated-by-Nova' % (key.get_name(), key.get_base64())
    fingerprint = generate_fingerprint(public_key)
    return (private_key, public_key, fingerprint)


def ssh_encrypt_text(ssh_public_key, text):
    """Encrypt text with an ssh public key.

    If text is a Unicode string, encode it to UTF-8.
    """
    if isinstance(text, six.text_type):
        text = text.encode('utf-8')
    try:
        pub_bytes = ssh_public_key.encode('utf-8')
        pub_key = serialization.load_ssh_public_key(
            pub_bytes, backends.default_backend())
        return pub_key.encrypt(text, padding.PKCS1v15())
    except Exception as exc:
        raise exception.EncryptionFailure(reason=six.text_type(exc))


def generate_winrm_x509_cert(user_id, bits=2048):
    """Generate a cert for passwordless auth for user in project."""
    subject = '/CN=%s' % user_id
    upn = '%s@localhost' % user_id

    with utils.tempdir() as tmpdir:
        keyfile = os.path.abspath(os.path.join(tmpdir, 'temp.key'))
        conffile = os.path.abspath(os.path.join(tmpdir, 'temp.conf'))

        _create_x509_openssl_config(conffile, upn)

        (certificate, _err) = processutils.execute(
             'openssl', 'req', '-x509', '-nodes', '-days', '3650',
             '-config', conffile, '-newkey', 'rsa:%s' % bits,
             '-outform', 'PEM', '-keyout', keyfile, '-subj', subject,
             '-extensions', 'v3_req_client',
             binary=True)

        (out, _err) = processutils.execute('openssl', 'pkcs12', '-export',
                                    '-inkey', keyfile, '-password', 'pass:',
                                    process_input=certificate,
                                    binary=True)

        private_key = base64.b64encode(out)
        fingerprint = generate_x509_fingerprint(certificate)
        if six.PY3:
            private_key = private_key.decode('ascii')
            certificate = certificate.decode('utf-8')

    return (private_key, certificate, fingerprint)


def _create_x509_openssl_config(conffile, upn):
    content = ("distinguished_name  = req_distinguished_name\n"
               "[req_distinguished_name]\n"
               "[v3_req_client]\n"
               "extendedKeyUsage = clientAuth\n"
               "subjectAltName = otherName:""1.3.6.1.4.1.311.20.2.3;UTF8:%s\n")

    with open(conffile, 'w') as file:
        file.write(content % upn)
