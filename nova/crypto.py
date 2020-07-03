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

import base64
import binascii
import io
import os
import typing as ty

from castellan.common import exception as castellan_exception
from castellan.common.objects import passphrase
from castellan import key_manager
from cryptography.hazmat import backends
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from oslo_concurrency import processutils
from oslo_log import log as logging
import paramiko

import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova import utils


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

_KEYMGR = None

_VTPM_SECRET_BYTE_LENGTH = 384


def _get_key_manager():
    global _KEYMGR
    if _KEYMGR is None:
        _KEYMGR = key_manager.API(configuration=CONF)
    return _KEYMGR


def generate_fingerprint(public_key: str) -> str:
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
        raw_fp = binascii.hexlify(md5hash).decode('ascii')
        return ':'.join(a + b for a, b in zip(raw_fp[::2], raw_fp[1::2]))
    except Exception:
        raise exception.InvalidKeypair(
            reason=_('failed to generate fingerprint'))


def generate_x509_fingerprint(pem_key: ty.Union[bytes, str]) -> str:
    try:
        if isinstance(pem_key, str):
            pem_key = pem_key.encode('utf-8')
        cert = x509.load_pem_x509_certificate(
            pem_key, backends.default_backend())
        raw_fp = binascii.hexlify(
            cert.fingerprint(hashes.SHA1())
        ).decode('ascii')
        return ':'.join(a + b for a, b in zip(raw_fp[::2], raw_fp[1::2]))
    except (ValueError, TypeError, binascii.Error) as ex:
        raise exception.InvalidKeypair(
            reason=_('failed to generate X509 fingerprint. '
                     'Error message: %s') % ex)


def generate_key_pair(bits: int = 2048) -> ty.Tuple[str, str, str]:
    key = paramiko.RSAKey.generate(bits)
    keyout = io.StringIO()
    key.write_private_key(keyout)
    private_key = keyout.getvalue()
    public_key = '%s %s Generated-by-Nova' % (key.get_name(), key.get_base64())
    fingerprint = generate_fingerprint(public_key)
    return (private_key, public_key, fingerprint)


def ssh_encrypt_text(ssh_public_key: str, text: ty.Union[str, bytes]) -> bytes:
    """Encrypt text with an ssh public key.

    If text is a Unicode string, encode it to UTF-8.
    """
    if isinstance(text, str):
        text = text.encode('utf-8')
    try:
        pub_bytes = ssh_public_key.encode('utf-8')
        pub_key = serialization.load_ssh_public_key(
            pub_bytes, backends.default_backend())
        return pub_key.encrypt(text, padding.PKCS1v15())
    except Exception as exc:
        raise exception.EncryptionFailure(reason=str(exc))


def generate_winrm_x509_cert(
    user_id: str,
    bits: int = 2048
) -> ty.Tuple[str, str, str]:
    """Generate a cert for passwordless auth for user in project."""
    subject = '/CN=%s' % user_id
    upn = '%s@localhost' % user_id

    with utils.tempdir() as tmpdir:
        keyfile = os.path.abspath(os.path.join(tmpdir, 'temp.key'))
        conffile = os.path.abspath(os.path.join(tmpdir, 'temp.conf'))

        _create_x509_openssl_config(conffile, upn)

        out, _ = processutils.execute(
            'openssl', 'req', '-x509', '-nodes', '-days', '3650',
            '-config', conffile, '-newkey', 'rsa:%s' % bits,
            '-outform', 'PEM', '-keyout', keyfile, '-subj', subject,
            '-extensions', 'v3_req_client',
            binary=True)

        certificate = out.decode('utf-8')

        out, _ = processutils.execute(
            'openssl', 'pkcs12', '-export', '-inkey', keyfile, '-password',
            'pass:', process_input=out, binary=True)

        private_key = base64.b64encode(out).decode('ascii')
        fingerprint = generate_x509_fingerprint(certificate)

    return (private_key, certificate, fingerprint)


def _create_x509_openssl_config(conffile: str, upn: str):
    content = ("distinguished_name  = req_distinguished_name\n"
               "[req_distinguished_name]\n"
               "[v3_req_client]\n"
               "extendedKeyUsage = clientAuth\n"
               "subjectAltName = otherName:""1.3.6.1.4.1.311.20.2.3;UTF8:%s\n")

    with open(conffile, 'w') as file:
        file.write(content % upn)


def ensure_vtpm_secret(
    context: nova_context.RequestContext,
    instance: 'objects.Instance',
) -> ty.Tuple[str, str]:
    """Communicates with the key manager service to retrieve or create a secret
    for an instance's emulated TPM.

    When creating a secret, its UUID is saved to the instance's system_metadata
    as ``vtpm_secret_uuid``.

    :param context: Nova auth context.
    :param instance: Instance object.
    :return: A tuple comprising (secret_uuid, passphrase).
    :raise: castellan_exception.ManagedObjectNotFoundError if communication
        with the key manager API fails, or if a vtpm_secret_uuid was present in
        the instance's system metadata but could not be found in the key
        manager service.
    """
    key_mgr = _get_key_manager()

    secret_uuid = instance.system_metadata.get('vtpm_secret_uuid')
    if secret_uuid is not None:
        # Try to retrieve the secret from the key manager
        try:
            secret = key_mgr.get(context, secret_uuid)
            # assert secret_uuid == secret.id ?
            LOG.debug(
                "Found existing vTPM secret with UUID %s.",
                secret_uuid, instance=instance)
            return secret.id, secret.get_encoded()
        except castellan_exception.ManagedObjectNotFoundError:
            LOG.warning(
                "Despite being set on the instance, failed to find a vTPM "
                "secret with UUID %s. This should only happen if the secret "
                "was manually deleted from the key manager service. Your vTPM "
                "is likely to be unrecoverable.",
                secret_uuid, instance=instance)
            raise

    # If we get here, the instance has no vtpm_secret_uuid. Create a new one
    # and register it with the key manager.
    secret = base64.b64encode(os.urandom(_VTPM_SECRET_BYTE_LENGTH))
    # Castellan ManagedObject
    cmo = passphrase.Passphrase(
        secret, name="vTPM secret for instance %s" % instance.uuid)
    secret_uuid = key_mgr.store(context, cmo)
    LOG.debug("Created vTPM secret with UUID %s",
              secret_uuid, instance=instance)

    instance.system_metadata['vtpm_secret_uuid'] = secret_uuid
    instance.save()
    return secret_uuid, secret


def delete_vtpm_secret(
    context: nova_context.RequestContext,
    instance: 'objects.Instance',
):
    """Communicates with the key manager service to destroy the secret for an
    instance's emulated TPM.

    This operation is idempotent: if the instance never had a vTPM secret, OR
    if the secret has already been deleted, it is a no-op.

    The ``vtpm_secret_uuid`` member of the instance's system_metadata is
    cleared as a side effect of this method.

    :param context: Nova auth context.
    :param instance: Instance object.
    :return: None
    :raise: castellan_exception.ManagedObjectNotFoundError if communication
        with the key manager API.
    """
    secret_uuid = instance.system_metadata.get('vtpm_secret_uuid')
    if not secret_uuid:
        return

    key_mgr = _get_key_manager()
    try:
        key_mgr.delete(context, secret_uuid)
        LOG.debug("Deleted vTPM secret with UUID %s",
                  secret_uuid, instance=instance)
    except castellan_exception.ManagedObjectNotFoundError:
        LOG.debug("vTPM secret with UUID %s already deleted or never existed.",
                  secret_uuid, instance=instance)

    del instance.system_metadata['vtpm_secret_uuid']
    instance.save()
