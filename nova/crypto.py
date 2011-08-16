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

import base64
import gettext
import hashlib
import os
import shutil
import string
import struct
import tempfile
import time
import utils

import M2Crypto

gettext.install('nova', unicode=1)

from nova import context
from nova import db
from nova import flags
from nova import log as logging


LOG = logging.getLogger("nova.crypto")


FLAGS = flags.FLAGS
flags.DEFINE_string('ca_file', 'cacert.pem', _('Filename of root CA'))
flags.DEFINE_string('key_file',
                    os.path.join('private', 'cakey.pem'),
                    _('Filename of private key'))
flags.DEFINE_string('crl_file', 'crl.pem',
                    _('Filename of root Certificate Revokation List'))
flags.DEFINE_string('keys_path', '$state_path/keys',
                    _('Where we keep our keys'))
flags.DEFINE_string('ca_path', '$state_path/CA',
                    _('Where we keep our root CA'))
flags.DEFINE_boolean('use_project_ca', False,
                     _('Should we use a CA for each project?'))
flags.DEFINE_string('user_cert_subject',
                    '/C=US/ST=California/L=MountainView/O=AnsoLabs/'
                    'OU=NovaDev/CN=%s-%s-%s',
                    _('Subject for certificate for users, '
                    '%s for project, user, timestamp'))
flags.DEFINE_string('project_cert_subject',
                    '/C=US/ST=California/L=MountainView/O=AnsoLabs/'
                    'OU=NovaDev/CN=project-ca-%s-%s',
                    _('Subject for certificate for projects, '
                    '%s for project, timestamp'))
flags.DEFINE_string('vpn_cert_subject',
                    '/C=US/ST=California/L=MountainView/O=AnsoLabs/'
                    'OU=NovaDev/CN=project-vpn-%s-%s',
                    _('Subject for certificate for vpns, '
                    '%s for project, timestamp'))


def ca_folder(project_id=None):
    if FLAGS.use_project_ca and project_id:
        return os.path.join(FLAGS.ca_path, 'projects', project_id)
    return FLAGS.ca_path


def ca_path(project_id=None):
    return os.path.join(ca_folder(project_id), FLAGS.ca_file)


def key_path(project_id=None):
    return os.path.join(ca_folder(project_id), FLAGS.key_file)


def fetch_ca(project_id=None, chain=True):
    if not FLAGS.use_project_ca:
        project_id = None
    buffer = ''
    if project_id:
        with open(ca_path(project_id), 'r') as cafile:
            buffer += cafile.read()
        if not chain:
            return buffer
    with open(ca_path(None), 'r') as cafile:
        buffer += cafile.read()
    return buffer


def generate_fingerprint(public_key):
    (out, err) = utils.execute('ssh-keygen', '-q', '-l', '-f', public_key)
    fingerprint = out.split(' ')[1]
    return fingerprint


def generate_key_pair(bits=1024):
    # what is the magic 65537?

    tmpdir = tempfile.mkdtemp()
    keyfile = os.path.join(tmpdir, 'temp')
    utils.execute('ssh-keygen', '-q', '-b', bits, '-N', '',
                  '-f', keyfile)
    fingerprint = generate_fingerprint('%s.pub' % (keyfile))
    private_key = open(keyfile).read()
    public_key = open(keyfile + '.pub').read()

    shutil.rmtree(tmpdir)
    # code below returns public key in pem format
    # key = M2Crypto.RSA.gen_key(bits, 65537, callback=lambda: None)
    # private_key = key.as_pem(cipher=None)
    # bio = M2Crypto.BIO.MemoryBuffer()
    # key.save_pub_key_bio(bio)
    # public_key = bio.read()
    # public_key, err = execute('ssh-keygen', '-y', '-f',
    #                           '/dev/stdin', private_key)

    return (private_key, public_key, fingerprint)


def ssl_pub_to_ssh_pub(ssl_public_key, name='root', suffix='nova'):
    buf = M2Crypto.BIO.MemoryBuffer(ssl_public_key)
    rsa_key = M2Crypto.RSA.load_pub_key_bio(buf)
    e, n = rsa_key.pub()

    key_type = 'ssh-rsa'

    key_data = struct.pack('>I', len(key_type))
    key_data += key_type
    key_data += '%s%s' % (e, n)

    b64_blob = base64.b64encode(key_data)
    return '%s %s %s@%s\n' % (key_type, b64_blob, name, suffix)


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


def _vpn_cert_subject(project_id):
    """Helper to generate user cert subject."""
    return FLAGS.vpn_cert_subject % (project_id, utils.isotime())


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
    csr_fn = os.path.join(project_folder, 'server.csr')
    crt_fn = os.path.join(project_folder, 'server.crt')

    genvpn_sh_path = os.path.join(os.path.dirname(__file__),
                                  'CA',
                                  'genvpn.sh')
    if os.path.exists(crt_fn):
        return
    _ensure_project_folder(project_id)
    start = os.getcwd()
    os.chdir(ca_folder())
    # TODO(vish): the shell scripts could all be done in python
    utils.execute('sh', genvpn_sh_path,
                  project_id, _vpn_cert_subject(project_id))
    with open(csr_fn, 'r') as csrfile:
        csr_text = csrfile.read()
    (serial, signed_csr) = sign_csr(csr_text, project_id)
    with open(crt_fn, 'w') as crtfile:
        crtfile.write(signed_csr)
    os.chdir(start)


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


def mkreq(bits, subject='foo', ca=0):
    pk = M2Crypto.EVP.PKey()
    req = M2Crypto.X509.Request()
    rsa = M2Crypto.RSA.gen_key(bits, 65537, callback=lambda: None)
    pk.assign_rsa(rsa)
    rsa = None  # should not be freed here
    req.set_pubkey(pk)
    req.set_subject(subject)
    req.sign(pk, 'sha512')
    assert req.verify(pk)
    pk2 = req.get_pubkey()
    assert req.verify(pk2)
    return req, pk


def mkcacert(subject='nova', years=1):
    req, pk = mkreq(2048, subject, ca=1)
    pkey = req.get_pubkey()
    sub = req.get_subject()
    cert = M2Crypto.X509.X509()
    cert.set_serial_number(1)
    cert.set_version(2)
    # FIXME subject is not set in mkreq yet
    cert.set_subject(sub)
    t = long(time.time()) + time.timezone
    now = M2Crypto.ASN1.ASN1_UTCTIME()
    now.set_time(t)
    nowPlusYear = M2Crypto.ASN1.ASN1_UTCTIME()
    nowPlusYear.set_time(t + (years * 60 * 60 * 24 * 365))
    cert.set_not_before(now)
    cert.set_not_after(nowPlusYear)
    issuer = M2Crypto.X509.X509_Name()
    issuer.C = 'US'
    issuer.CN = subject
    cert.set_issuer(issuer)
    cert.set_pubkey(pkey)
    ext = M2Crypto.X509.new_extension('basicConstraints', 'CA:TRUE')
    cert.add_ext(ext)
    cert.sign(pk, 'sha512')

    # print 'cert', dir(cert)
    print cert.as_pem()
    print pk.get_rsa().as_pem()

    return cert, pk, pkey


def _build_cipher(key, iv, encode=True):
    """Make a 128bit AES CBC encode/decode Cipher object.
       Padding is handled internally."""
    operation = 1 if encode else 0
    return M2Crypto.EVP.Cipher(alg='aes_128_cbc', key=key, iv=iv, op=operation)


def encryptor(key, iv=None):
    """Simple symmetric key encryption."""
    key = base64.b64decode(key)
    if iv is None:
        iv = '\0' * 16
    else:
        iv = base64.b64decode(iv)

    def encrypt(data):
        cipher = _build_cipher(key, iv, encode=True)
        v = cipher.update(data)
        v = v + cipher.final()
        del cipher
        v = base64.b64encode(v)
        return v

    return encrypt


def decryptor(key, iv=None):
    """Simple symmetric key decryption."""
    key = base64.b64decode(key)
    if iv is None:
        iv = '\0' * 16
    else:
        iv = base64.b64decode(iv)

    def decrypt(data):
        data = base64.b64decode(data)
        cipher = _build_cipher(key, iv, encode=False)
        v = cipher.update(data)
        v = v + cipher.final()
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
