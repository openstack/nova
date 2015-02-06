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
import os
import re
import string
import struct

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import timeutils
from pyasn1.codec.der import encoder as der_encoder
from pyasn1.type import univ

from nova import context
from nova import db
from nova import exception
from nova.i18n import _, _LE
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import paths
from nova import utils


LOG = logging.getLogger(__name__)

crypto_opts = [
    cfg.StrOpt('ca_file',
               default='cacert.pem',
               help=_('Filename of root CA')),
    cfg.StrOpt('key_file',
               default=os.path.join('private', 'cakey.pem'),
               help=_('Filename of private key')),
    cfg.StrOpt('crl_file',
               default='crl.pem',
               help=_('Filename of root Certificate Revocation List')),
    cfg.StrOpt('keys_path',
               default=paths.state_path_def('keys'),
               help=_('Where we keep our keys')),
    cfg.StrOpt('ca_path',
               default=paths.state_path_def('CA'),
               help=_('Where we keep our root CA')),
    cfg.BoolOpt('use_project_ca',
                default=False,
                help=_('Should we use a CA for each project?')),
    cfg.StrOpt('user_cert_subject',
               default='/C=US/ST=California/O=OpenStack/'
                       'OU=NovaDev/CN=%.16s-%.16s-%s',
               help=_('Subject for certificate for users, %s for '
                      'project, user, timestamp')),
    cfg.StrOpt('project_cert_subject',
               default='/C=US/ST=California/O=OpenStack/'
                       'OU=NovaDev/CN=project-ca-%.16s-%s',
               help=_('Subject for certificate for projects, %s for '
                      'project, timestamp')),
    ]

CONF = cfg.CONF
CONF.register_opts(crypto_opts)


def ca_folder(project_id=None):
    if CONF.use_project_ca and project_id:
        return os.path.join(CONF.ca_path, 'projects', project_id)
    return CONF.ca_path


def ca_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.ca_file)


def key_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.key_file)


def crl_path(project_id=None):
    return os.path.join(ca_folder(project_id), CONF.crl_file)


def fetch_ca(project_id=None):
    if not CONF.use_project_ca:
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

        start = os.getcwd()
        fileutils.ensure_tree(ca_dir)
        os.chdir(ca_dir)
        utils.execute("sh", genrootca_sh_path)
        os.chdir(start)


def _generate_fingerprint(public_key_file):
    (out, err) = utils.execute('ssh-keygen', '-q', '-l', '-f', public_key_file)
    fingerprint = out.split(' ')[1]
    return fingerprint


def generate_fingerprint(public_key):
    with utils.tempdir() as tmpdir:
        try:
            pubfile = os.path.join(tmpdir, 'temp.pub')
            with open(pubfile, 'w') as f:
                f.write(public_key)
            return _generate_fingerprint(pubfile)
        except processutils.ProcessExecutionError:
            raise exception.InvalidKeypair(
                reason=_('failed to generate fingerprint'))


def generate_key_pair(bits=None):
    with utils.tempdir() as tmpdir:
        keyfile = os.path.join(tmpdir, 'temp')
        args = ['ssh-keygen', '-q', '-N', '', '-t', 'rsa',
                '-f', keyfile, '-C', 'Generated-by-Nova']
        if bits is not None:
            args.extend(['-b', bits])
        utils.execute(*args)
        fingerprint = _generate_fingerprint('%s.pub' % (keyfile))
        if not os.path.exists(keyfile):
            raise exception.FileNotFound(keyfile)
        with open(keyfile) as f:
            private_key = f.read()
        public_key_path = keyfile + '.pub'
        if not os.path.exists(public_key_path):
            raise exception.FileNotFound(public_key_path)
        with open(public_key_path) as f:
            public_key = f.read()

    return (private_key, public_key, fingerprint)


def fetch_crl(project_id):
    """Get crl file for project."""
    if not CONF.use_project_ca:
        project_id = None
    crl_file_path = crl_path(project_id)
    if not os.path.exists(crl_file_path):
        raise exception.CryptoCRLFileNotFound(project=project_id)
    with open(crl_file_path, 'r') as crlfile:
        return crlfile.read()


def decrypt_text(project_id, text):
    private_key = key_path(project_id)
    if not os.path.exists(private_key):
        raise exception.ProjectNotFound(project_id=project_id)
    try:
        dec, _err = utils.execute('openssl',
                                  'rsautl',
                                  '-decrypt',
                                  '-inkey', '%s' % private_key,
                                  process_input=text)
        return dec
    except processutils.ProcessExecutionError as exc:
        raise exception.DecryptionFailure(reason=exc.stderr)


_RSA_OID = univ.ObjectIdentifier('1.2.840.113549.1.1.1')


def _to_sequence(*vals):
    seq = univ.Sequence()
    for i in range(len(vals)):
        seq.setComponentByPosition(i, vals[i])
    return seq


def convert_from_sshrsa_to_pkcs8(pubkey):
    """Convert a ssh public key to openssl format
       Equivalent to the ssh-keygen's -m option
    """
    # get the second field from the public key file.
    try:
        keydata = base64.b64decode(pubkey.split(None)[1])
    except IndexError:
        msg = _("Unable to find the key")
        raise exception.EncryptionFailure(reason=msg)

    # decode the parts of the key
    parts = []
    while keydata:
        dlen = struct.unpack('>I', keydata[:4])[0]
        data = keydata[4:dlen + 4]
        keydata = keydata[4 + dlen:]
        parts.append(data)

    # Use asn to build the openssl key structure
    #
    #  SEQUENCE(2 elem)
    #    +- SEQUENCE(2 elem)
    #    |    +- OBJECT IDENTIFIER (1.2.840.113549.1.1.1)
    #    |    +- NULL
    #    +- BIT STRING(1 elem)
    #         +- SEQUENCE(2 elem)
    #              +- INTEGER(2048 bit)
    #              +- INTEGER 65537

    # Build the sequence for the bit string
    n_val = int(
        ''.join(['%02X' % struct.unpack('B', x)[0] for x in parts[2]]), 16)
    e_val = int(
        ''.join(['%02X' % struct.unpack('B', x)[0] for x in parts[1]]), 16)
    pkinfo = _to_sequence(univ.Integer(n_val), univ.Integer(e_val))

    # Convert the sequence into a bit string
    pklong = long(der_encoder.encode(pkinfo).encode('hex'), 16)
    pkbitstring = univ.BitString("'00%s'B" % bin(pklong)[2:])

    # Build the key data structure
    oid = _to_sequence(_RSA_OID, univ.Null())
    pkcs1_seq = _to_sequence(oid, pkbitstring)
    pkcs8 = base64.encodestring(der_encoder.encode(pkcs1_seq))

    # Remove the embedded new line and format the key, each line
    # should be 64 characters long
    return ('-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----\n' %
            re.sub("(.{64})", "\\1\n", pkcs8.replace('\n', ''), re.DOTALL))


def ssh_encrypt_text(ssh_public_key, text):
    """Encrypt text with an ssh public key.
    """
    with utils.tempdir() as tmpdir:
        sslkey = os.path.abspath(os.path.join(tmpdir, 'ssl.key'))
        try:
            out = convert_from_sshrsa_to_pkcs8(ssh_public_key)
            with open(sslkey, 'w') as f:
                f.write(out)
            enc, _err = utils.execute('openssl',
                                      'rsautl',
                                      '-encrypt',
                                      '-pubin',
                                      '-inkey', sslkey,
                                      '-keyform', 'PEM',
                                      process_input=text)
            return enc
        except processutils.ProcessExecutionError as exc:
            raise exception.EncryptionFailure(reason=exc.stderr)


def revoke_cert(project_id, file_name):
    """Revoke a cert by file name."""
    start = os.getcwd()
    try:
        os.chdir(ca_folder(project_id))
    except OSError:
        raise exception.ProjectNotFound(project_id=project_id)
    try:
        # NOTE(vish): potential race condition here
        utils.execute('openssl', 'ca', '-config', './openssl.cnf', '-revoke',
                      file_name)
        utils.execute('openssl', 'ca', '-gencrl', '-config', './openssl.cnf',
                      '-out', CONF.crl_file)
    except processutils.ProcessExecutionError:
        raise exception.RevokeCertFailure(project_id=project_id)
    finally:
        os.chdir(start)


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
    return CONF.project_cert_subject % (project_id, timeutils.isotime())


def _user_cert_subject(user_id, project_id):
    """Helper to generate user cert subject."""
    return CONF.user_cert_subject % (project_id, user_id, timeutils.isotime())


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


def _ensure_project_folder(project_id):
    if not os.path.exists(ca_path(project_id)):
        geninter_sh_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), 'CA', 'geninter.sh'))
        start = os.getcwd()
        os.chdir(ca_folder())
        utils.execute('sh', geninter_sh_path, project_id,
                      _project_cert_subject(project_id))
        os.chdir(start)


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
    if not CONF.use_project_ca:
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
        start = os.getcwd()

        # Change working dir to CA
        fileutils.ensure_tree(ca_folder)
        os.chdir(ca_folder)
        utils.execute('openssl', 'ca', '-batch', '-out', outbound, '-config',
                      './openssl.cnf', '-infiles', inbound)
        out, _err = utils.execute('openssl', 'x509', '-in', outbound,
                                  '-serial', '-noout')
        serial = string.strip(out.rpartition('=')[2])
        os.chdir(start)

        with open(outbound, 'r') as crtfile:
            return (serial, crtfile.read())
