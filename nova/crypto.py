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

from cryptography import exceptions
from cryptography.hazmat import backends
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils
import paramiko
import six

import nova.conf
from nova import context
from nova import db
from nova import exception
from nova.i18n import _, _LE
from nova import utils


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


def ca_folder(project_id=None):
    if CONF.crypto.use_project_ca and project_id:
        return os.path.join(CONF.crypto.ca_path, 'projects', project_id)
    return CONF.crypto.ca_path


def ca_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.crypto.ca_file)


def key_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.crypto.key_file)


def crl_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.crypto.crl_file)


def fetch_ca(project_id=None):
    if not CONF.crypto.use_project_ca:
        project_id = None
    ca_file_path = ca_path(project_id)
    if not os.path.exists(ca_file_path):
        raise exception.CryptoCAFileNotFound(project=project_id)
    with open(ca_file_path, 'r') as cafile:
        return cafile.read()


def ensure_ca_filesystem():
    """Ensure the CA filesystem exists."""
    ca_dir = ca_folder()
    if not os.path.exists(ca_path()):
        genrootca_sh_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), 'CA', 'genrootca.sh'))

        fileutils.ensure_tree(ca_dir)
        utils.execute("sh", genrootca_sh_path, cwd=ca_dir)


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


def fetch_crl(project_id):
    """Get crl file for project."""
    if not CONF.crypto.use_project_ca:
        project_id = None
    crl_file_path = crl_path(project_id)
    if not os.path.exists(crl_file_path):
        raise exception.CryptoCRLFileNotFound(project=project_id)
    with open(crl_file_path, 'r') as crlfile:
        return crlfile.read()


def decrypt_text(project_id, text):
    private_key_file = key_path(project_id)
    if not os.path.exists(private_key_file):
        raise exception.ProjectNotFound(project_id=project_id)
    with open(private_key_file, 'rb') as f:
        data = f.read()
    try:
        priv_key = serialization.load_pem_private_key(
            data, None, backends.default_backend())
        return priv_key.decrypt(text, padding.PKCS1v15())
    except (ValueError, TypeError, exceptions.UnsupportedAlgorithm) as exc:
        raise exception.DecryptionFailure(reason=six.text_type(exc))


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


def revoke_cert(project_id, file_name):
    """Revoke a cert by file name."""
    try:
        # NOTE(vish): potential race condition here
        utils.execute('openssl', 'ca', '-config', './openssl.cnf', '-revoke',
                      file_name, cwd=ca_folder(project_id))
        utils.execute('openssl', 'ca', '-gencrl', '-config', './openssl.cnf',
                      '-out', CONF.crypto.crl_file, cwd=ca_folder(project_id))
    except OSError:
        raise exception.ProjectNotFound(project_id=project_id)
    except processutils.ProcessExecutionError:
        raise exception.RevokeCertFailure(project_id=project_id)


def revoke_certs_by_user(user_id):
    """Revoke all user certs."""
    admin = context.get_admin_context()
    for cert in db.certificate_get_all_by_user(admin, user_id):
        revoke_cert(cert['project_id'], cert['file_name'])


def revoke_certs_by_project(project_id):
    """Revoke all project certs."""
    # NOTE(vish): This is somewhat useless because we can just shut down
    #             the vpn.
    admin = context.get_admin_context()
    for cert in db.certificate_get_all_by_project(admin, project_id):
        revoke_cert(cert['project_id'], cert['file_name'])


def revoke_certs_by_user_and_project(user_id, project_id):
    """Revoke certs for user in project."""
    admin = context.get_admin_context()
    for cert in db.certificate_get_all_by_user_and_project(admin,
                                            user_id, project_id):
        revoke_cert(cert['project_id'], cert['file_name'])


def _project_cert_subject(project_id):
    """Helper to generate user cert subject."""
    return CONF.crypto.project_cert_subject % (project_id, utils.isotime())


def _user_cert_subject(user_id, project_id):
    """Helper to generate user cert subject."""
    return CONF.crypto.user_cert_subject % (project_id, user_id,
                                            utils.isotime())


def generate_x509_cert(user_id, project_id, bits=2048):
    """Generate and sign a cert for user in project."""
    subject = _user_cert_subject(user_id, project_id)

    with utils.tempdir() as tmpdir:
        keyfile = os.path.abspath(os.path.join(tmpdir, 'temp.key'))
        csrfile = os.path.abspath(os.path.join(tmpdir, 'temp.csr'))
        utils.execute('openssl', 'genrsa', '-out', keyfile, str(bits))
        utils.execute('openssl', 'req', '-new', '-key', keyfile, '-out',
                      csrfile, '-batch', '-subj', subject)
        with open(keyfile) as f:
            private_key = f.read()
        with open(csrfile) as f:
            csr = f.read()

    (serial, signed_csr) = sign_csr(csr, project_id)
    fname = os.path.join(ca_folder(project_id), 'newcerts/%s.pem' % serial)
    cert = {'user_id': user_id,
            'project_id': project_id,
            'file_name': fname}
    db.certificate_create(context.get_admin_context(), cert)
    return (private_key, signed_csr)


def generate_winrm_x509_cert(user_id, bits=2048):
    """Generate a cert for passwordless auth for user in project."""
    subject = '/CN=%s' % user_id
    upn = '%s@localhost' % user_id

    with utils.tempdir() as tmpdir:
        keyfile = os.path.abspath(os.path.join(tmpdir, 'temp.key'))
        conffile = os.path.abspath(os.path.join(tmpdir, 'temp.conf'))

        _create_x509_openssl_config(conffile, upn)

        (certificate, _err) = utils.execute(
             'openssl', 'req', '-x509', '-nodes', '-days', '3650',
             '-config', conffile, '-newkey', 'rsa:%s' % bits,
             '-outform', 'PEM', '-keyout', keyfile, '-subj', subject,
             '-extensions', 'v3_req_client',
             binary=True)

        (out, _err) = utils.execute('openssl', 'pkcs12', '-export',
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


def _ensure_project_folder(project_id):
    if not os.path.exists(ca_path(project_id)):
        geninter_sh_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), 'CA', 'geninter.sh'))
        utils.execute('sh', geninter_sh_path, project_id,
                      _project_cert_subject(project_id), cwd=ca_folder())


def generate_vpn_files(project_id):
    project_folder = ca_folder(project_id)
    key_fn = os.path.join(project_folder, 'server.key')
    crt_fn = os.path.join(project_folder, 'server.crt')

    if os.path.exists(crt_fn):
        return
    # NOTE(vish): The 2048 is to maintain compatibility with the old script.
    #             We are using "project-vpn" as the user_id for the cert
    #             even though that user may not really exist. Ultimately
    #             this will be changed to be launched by a real user.  At
    #             that point we will can delete this helper method.
    key, csr = generate_x509_cert('project-vpn', project_id, 2048)
    with open(key_fn, 'w') as keyfile:
        keyfile.write(key)
    with open(crt_fn, 'w') as crtfile:
        crtfile.write(csr)


def sign_csr(csr_text, project_id=None):
    if not CONF.crypto.use_project_ca:
        project_id = None
    if not project_id:
        return _sign_csr(csr_text, ca_folder())
    _ensure_project_folder(project_id)
    return _sign_csr(csr_text, ca_folder(project_id))


def _sign_csr(csr_text, ca_folder):
    with utils.tempdir() as tmpdir:
        inbound = os.path.join(tmpdir, 'inbound.csr')
        outbound = os.path.join(tmpdir, 'outbound.csr')

        try:
            with open(inbound, 'w') as csrfile:
                csrfile.write(csr_text)
        except IOError:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Failed to write inbound.csr'))

        LOG.debug('Flags path: %s', ca_folder)

        # Change working dir to CA
        fileutils.ensure_tree(ca_folder)
        utils.execute('openssl', 'ca', '-batch', '-out', outbound, '-config',
                      './openssl.cnf', '-infiles', inbound, cwd=ca_folder)
        out, _err = utils.execute('openssl', 'x509', '-in', outbound,
                                  '-serial', '-noout', cwd=ca_folder)
        serial = out.rpartition('=')[2].strip()

        with open(outbound, 'r') as crtfile:
            return (serial, crtfile.read())
