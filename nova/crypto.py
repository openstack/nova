# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import hashlib
import os
import shutil
import string
import tempfile

import Crypto.Cipher.AES

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
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
               default='$state_path/keys',
               help=_('Where we keep our keys')),
    cfg.StrOpt('ca_path',
               default='$state_path/CA',
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

FLAGS = flags.FLAGS
FLAGS.register_opts(crypto_opts)


def ca_folder(project_id=None):
    if FLAGS.use_project_ca and project_id:
        return os.path.join(FLAGS.ca_path, 'projects', project_id)
    return FLAGS.ca_path


def ca_path(project_id=None):
    return os.path.join(ca_folder(project_id), FLAGS.ca_file)


def key_path(project_id=None):
    return os.path.join(ca_folder(project_id), FLAGS.key_file)


def crl_path(project_id=None):
    return os.path.join(ca_folder(project_id), FLAGS.crl_file)


def fetch_ca(project_id=None):
    if not FLAGS.use_project_ca:
        project_id = None
    with open(ca_path(project_id), 'r') as cafile:
        return cafile.read()


def ensure_ca_filesystem():
    """Ensure the CA filesystem exists."""
    ca_dir = ca_folder()
    if not os.path.exists(ca_path()):
        genrootca_sh_path = os.path.join(os.path.dirname(__file__),
                                         'CA',
                                         'genrootca.sh')

        start = os.getcwd()
        if not os.path.exists(ca_dir):
            os.makedirs(ca_dir)
        os.chdir(ca_dir)
        utils.execute("sh", genrootca_sh_path)
        os.chdir(start)


def _generate_fingerprint(public_key_file):
    (out, err) = utils.execute('ssh-keygen', '-q', '-l', '-f', public_key_file)
    fingerprint = out.split(' ')[1]
    return fingerprint


def generate_fingerprint(public_key):
    tmpdir = tempfile.mkdtemp()
    try:
        pubfile = os.path.join(tmpdir, 'temp.pub')
        with open(pubfile, 'w') as f:
            f.write(public_key)
        return _generate_fingerprint(pubfile)
    except exception.ProcessExecutionError:
        raise exception.InvalidKeypair()
    finally:
        shutil.rmtree(tmpdir)


def generate_key_pair(bits=1024):
    # what is the magic 65537?

    tmpdir = tempfile.mkdtemp()
    keyfile = os.path.join(tmpdir, 'temp')
    utils.execute('ssh-keygen', '-q', '-b', bits, '-N', '',
                  '-t', 'rsa', '-f', keyfile)
    fingerprint = _generate_fingerprint('%s.pub' % (keyfile))
    private_key = open(keyfile).read()
    public_key = open(keyfile + '.pub').read()

    shutil.rmtree(tmpdir)

    return (private_key, public_key, fingerprint)


def fetch_crl(project_id):
    """Get crl file for project."""
    if not FLAGS.use_project_ca:
        project_id = None
    with open(crl_path(project_id), 'r') as crlfile:
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
    except exception.ProcessExecutionError:
        raise exception.DecryptionFailure()


def revoke_cert(project_id, file_name):
    """Revoke a cert by file name."""
    start = os.getcwd()
    os.chdir(ca_folder(project_id))
    # NOTE(vish): potential race condition here
    utils.execute('openssl', 'ca', '-config', './openssl.cnf', '-revoke',
                  file_name)
    utils.execute('openssl', 'ca', '-gencrl', '-config', './openssl.cnf',
                  '-out', FLAGS.crl_file)
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
    return FLAGS.project_cert_subject % (project_id, utils.isotime())


def _user_cert_subject(user_id, project_id):
    """Helper to generate user cert subject."""
    return FLAGS.user_cert_subject % (project_id, user_id, utils.isotime())


def generate_x509_cert(user_id, project_id, bits=1024):
    """Generate and sign a cert for user in project."""
    subject = _user_cert_subject(user_id, project_id)
    tmpdir = tempfile.mkdtemp()
    keyfile = os.path.abspath(os.path.join(tmpdir, 'temp.key'))
    csrfile = os.path.join(tmpdir, 'temp.csr')
    utils.execute('openssl', 'genrsa', '-out', keyfile, str(bits))
    utils.execute('openssl', 'req', '-new', '-key', keyfile, '-out', csrfile,
                  '-batch', '-subj', subject)
    private_key = open(keyfile).read()
    csr = open(csrfile).read()
    shutil.rmtree(tmpdir)
    (serial, signed_csr) = sign_csr(csr, project_id)
    fname = os.path.join(ca_folder(project_id), 'newcerts/%s.pem' % serial)
    cert = {'user_id': user_id,
            'project_id': project_id,
            'file_name': fname}
    db.certificate_create(context.get_admin_context(), cert)
    return (private_key, signed_csr)


def _ensure_project_folder(project_id):
    if not os.path.exists(ca_path(project_id)):
        geninter_sh_path = os.path.join(os.path.dirname(__file__),
                                        'CA',
                                        'geninter.sh')
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
    with open(key_fn, 'f') as keyfile:
        keyfile.write(key)
    with open(crt_fn, 'w') as crtfile:
        crtfile.write(csr)


def sign_csr(csr_text, project_id=None):
    if not FLAGS.use_project_ca:
        project_id = None
    if not project_id:
        return _sign_csr(csr_text, ca_folder())
    _ensure_project_folder(project_id)
    project_folder = ca_folder(project_id)
    return _sign_csr(csr_text, ca_folder(project_id))


def _sign_csr(csr_text, ca_folder):
    tmpfolder = tempfile.mkdtemp()
    inbound = os.path.join(tmpfolder, 'inbound.csr')
    outbound = os.path.join(tmpfolder, 'outbound.csr')
    csrfile = open(inbound, 'w')
    csrfile.write(csr_text)
    csrfile.close()
    LOG.debug(_('Flags path: %s'), ca_folder)
    start = os.getcwd()
    # Change working dir to CA
    if not os.path.exists(ca_folder):
        os.makedirs(ca_folder)
    os.chdir(ca_folder)
    utils.execute('openssl', 'ca', '-batch', '-out', outbound, '-config',
                  './openssl.cnf', '-infiles', inbound)
    out, _err = utils.execute('openssl', 'x509', '-in', outbound,
                              '-serial', '-noout')
    serial = string.strip(out.rpartition('=')[2])
    os.chdir(start)
    with open(outbound, 'r') as crtfile:
        return (serial, crtfile.read())


def _build_cipher(key, iv):
    """Make a 128bit AES CBC encode/decode Cipher object.
       Padding is handled internally."""
    return Crypto.Cipher.AES.new(key, IV=iv)


def encryptor(key):
    """Simple symmetric key encryption."""
    key = base64.b64decode(key)
    iv = '\0' * 16

    def encrypt(data):
        cipher = _build_cipher(key, iv)
        # Must pad string to multiple of 16 chars
        padding = (16 - len(data) % 16) * " "
        v = cipher.encrypt(data + padding)
        del cipher
        v = base64.b64encode(v)
        return v

    return encrypt


def decryptor(key):
    """Simple symmetric key decryption."""
    key = base64.b64decode(key)
    iv = '\0' * 16

    def decrypt(data):
        data = base64.b64decode(data)
        cipher = _build_cipher(key, iv)
        v = cipher.decrypt(data).rstrip()
        del cipher
        return v

    return decrypt


# Copyright (c) 2006-2009 Mitch Garnaat http://garnaat.org/
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
# http://code.google.com/p/boto

def compute_md5(fp):
    """Compute an md5 hash.

    :type fp: file
    :param fp: File pointer to the file to MD5 hash.  The file pointer will be
               reset to the beginning of the file before the method returns.

    :rtype: tuple
    :returns: the hex digest version of the MD5 hash

    """
    m = hashlib.md5()
    fp.seek(0)
    s = fp.read(8192)
    while s:
        m.update(s)
        s = fp.read(8192)
    hex_md5 = m.hexdigest()
    # size = fp.tell()
    fp.seek(0)
    return hex_md5
