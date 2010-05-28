#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Nova users and user management, including RBAC hooks.
"""

import datetime
import logging
import os
import shutil
import tempfile
import uuid
import zipfile

try:
    import ldap
except Exception, e:
    import fakeldap as ldap

import fakeldap
from nova import datastore

# TODO(termie): clean up these imports
import signer
from nova import exception
from nova import flags
from nova import crypto
from nova import utils
import access as simplerbac

from nova import objectstore # for flags

FLAGS = flags.FLAGS

flags.DEFINE_string('ldap_url', 'ldap://localhost', 'Point this at your ldap server')
flags.DEFINE_string('ldap_password',  'changeme', 'LDAP password')
flags.DEFINE_string('user_dn', 'cn=Manager,dc=example,dc=com', 'DN of admin user')
flags.DEFINE_string('user_unit', 'Users', 'OID for Users')
flags.DEFINE_string('ldap_subtree', 'ou=Users,dc=example,dc=com', 'OU for Users')

flags.DEFINE_string('ldap_sysadmin',
    'cn=sysadmins,ou=Groups,dc=example,dc=com', 'OU for Sysadmins')
flags.DEFINE_string('ldap_netadmin',
    'cn=netadmins,ou=Groups,dc=example,dc=com', 'OU for NetAdmins')
flags.DEFINE_string('ldap_cloudadmin',
    'cn=cloudadmins,ou=Groups,dc=example,dc=com', 'OU for Cloud Admins')
flags.DEFINE_string('ldap_itsec',
    'cn=itsec,ou=Groups,dc=example,dc=com', 'OU for ItSec')

flags.DEFINE_string('credentials_template',
                    utils.abspath('auth/novarc.template'),
                    'Template for creating users rc file')
flags.DEFINE_string('credential_key_file', 'pk.pem',
                    'Filename of private key in credentials zip')
flags.DEFINE_string('credential_cert_file', 'cert.pem',
                    'Filename of certificate in credentials zip')
flags.DEFINE_string('credential_rc_file', 'novarc',
                    'Filename of rc in credentials zip')

_log = logging.getLogger('auth')
_log.setLevel(logging.WARN)



class UserError(exception.ApiError):
    pass

class InvalidKeyPair(exception.ApiError):
    pass

class User(object):
    def __init__(self, id, name, access, secret, admin):
        self.manager = UserManager.instance()
        self.id = id
        self.name = name
        self.access = access
        self.secret = secret
        self.admin = admin
        self.keeper = datastore.Keeper(prefix="user")


    def is_admin(self):
        return self.admin

    def has_role(self, role_type):
        return self.manager.has_role(self.id, role_type)

    def is_authorized(self, owner_id, action=None):
        if self.is_admin() or owner_id == self.id:
            return True
        if action == None:
            return False
        project = None #(Fixme)
        target_object = None # (Fixme, should be passed in)
        return simplerbac.is_allowed(action, self, project, target_object)

    def get_credentials(self):
        rc = self.generate_rc()
        private_key, signed_cert = self.generate_x509_cert()

        tmpdir = tempfile.mkdtemp()
        zf = os.path.join(tmpdir, "temp.zip")
        zippy = zipfile.ZipFile(zf, 'w')
        zippy.writestr(FLAGS.credential_rc_file, rc)
        zippy.writestr(FLAGS.credential_key_file, private_key)
        zippy.writestr(FLAGS.credential_cert_file, signed_cert)
        zippy.writestr(FLAGS.ca_file, crypto.fetch_ca(self.id))
        zippy.close()
        with open(zf, 'rb') as f:
            buffer = f.read()

        shutil.rmtree(tmpdir)
        return buffer


    def generate_rc(self):
        rc = open(FLAGS.credentials_template).read()
        rc = rc % { 'access': self.access,
                    'secret': self.secret,
                    'ec2': FLAGS.ec2_url,
                    's3': 'http://%s:%s' % (FLAGS.s3_host, FLAGS.s3_port),
                    'nova': FLAGS.ca_file,
                    'cert': FLAGS.credential_cert_file,
                    'key': FLAGS.credential_key_file,
            }
        return rc

    def generate_key_pair(self, name):
        return self.manager.generate_key_pair(self.id, name)

    def generate_x509_cert(self):
        return self.manager.generate_x509_cert(self.id)

    def create_key_pair(self, name, public_key, fingerprint):
        return self.manager.create_key_pair(self.id,
                                            name,
                                            public_key,
                                            fingerprint)

    def get_key_pair(self, name):
        return self.manager.get_key_pair(self.id, name)

    def delete_key_pair(self, name):
        return self.manager.delete_key_pair(self.id, name)

    def get_key_pairs(self):
        return self.manager.get_key_pairs(self.id)

class KeyPair(object):
    def __init__(self, name, owner, public_key, fingerprint):
        self.manager = UserManager.instance()
        self.owner = owner
        self.name = name
        self.public_key = public_key
        self.fingerprint = fingerprint

    def delete(self):
        return self.manager.delete_key_pair(self.owner, self.name)

class UserManager(object):
    def __init__(self):
        if hasattr(self.__class__, '_instance'):
            raise Exception('Attempted to instantiate singleton')

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            inst = UserManager()
            cls._instance = inst
            if FLAGS.fake_users:
                try:
                    inst.create_user('fake', 'fake', 'fake')
                except: pass
                try:
                    inst.create_user('user', 'user', 'user')
                except: pass
                try:
                    inst.create_user('admin', 'admin', 'admin', True)
                except: pass
        return cls._instance

    def authenticate(self, params, signature, verb='GET', server_string='127.0.0.1:8773', path='/'):
        # TODO: Check for valid timestamp
        access_key = params['AWSAccessKeyId']
        user = self.get_user_from_access_key(access_key)
        if user == None:
            return None
        # hmac can't handle unicode, so encode ensures that secret isn't unicode
        expected_signature = signer.Signer(user.secret.encode()).generate(params, verb, server_string, path)
        _log.debug('user.secret: %s', user.secret)
        _log.debug('expected_signature: %s', expected_signature)
        _log.debug('signature: %s', signature)
        if signature == expected_signature:
            return user

    def has_role(self, user, role, project=None):
        # Map role to ldap group
        group = FLAGS.__getitem__("ldap_%s" % role)
        with LDAPWrapper() as conn:
            return conn.is_member_of(user, group)

    def add_role(self, user, role, project=None):
        # TODO: Project-specific roles
        group = FLAGS.__getitem__("ldap_%s" % role)
        with LDAPWrapper() as conn:
            return conn.add_to_group(user, group)

    def get_user(self, uid):
        with LDAPWrapper() as conn:
            return conn.find_user(uid)

    def get_user_from_access_key(self, access_key):
        with LDAPWrapper() as conn:
            return conn.find_user_by_access_key(access_key)

    def get_users(self):
        with LDAPWrapper() as conn:
            return conn.find_users()

    def create_user(self, uid, access=None, secret=None, admin=False):
        if access == None: access = str(uuid.uuid4())
        if secret == None: secret = str(uuid.uuid4())
        with LDAPWrapper() as conn:
            u = conn.create_user(uid, access, secret, admin)
        return u

    def delete_user(self, uid):
        with LDAPWrapper() as conn:
            conn.delete_user(uid)

    def generate_key_pair(self, uid, key_name):
        # generating key pair is slow so delay generation
        # until after check
        with LDAPWrapper() as conn:
            if not conn.user_exists(uid):
                raise UserError("User " + uid + " doesn't exist")
            if conn.key_pair_exists(uid, key_name):
                raise InvalidKeyPair("The keypair '" +
                            key_name +
                            "' already exists.",
                            "Duplicate")
        private_key, public_key, fingerprint = crypto.generate_key_pair()
        self.create_key_pair(uid, key_name, public_key, fingerprint)
        return private_key, fingerprint

    def create_key_pair(self, uid, key_name, public_key, fingerprint):
        with LDAPWrapper() as conn:
            return conn.create_key_pair(uid, key_name, public_key, fingerprint)

    def get_key_pair(self, uid, key_name):
        with LDAPWrapper() as conn:
            return conn.find_key_pair(uid, key_name)

    def get_key_pairs(self, uid):
        with LDAPWrapper() as conn:
            return conn.find_key_pairs(uid)

    def delete_key_pair(self, uid, key_name):
        with LDAPWrapper() as conn:
            conn.delete_key_pair(uid, key_name)

    def get_signed_zip(self, uid):
        user = self.get_user(uid)
        return user.get_credentials()

    def generate_x509_cert(self, uid):
        (private_key, csr) = crypto.generate_x509_cert(self.__cert_subject(uid))
        # TODO - This should be async call back to the cloud controller
        signed_cert = crypto.sign_csr(csr, uid)
        return (private_key, signed_cert)

    def sign_cert(self, csr, uid):
        return crypto.sign_csr(csr, uid)

    def __cert_subject(self, uid):
        return "/C=US/ST=California/L=The_Mission/O=AnsoLabs/OU=Nova/CN=%s-%s" % (uid, str(datetime.datetime.utcnow().isoformat()))


class LDAPWrapper(object):
    def __init__(self):
        self.user = FLAGS.user_dn
        self.passwd = FLAGS.ldap_password

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, type, value, traceback):
        #logging.info('type, value, traceback: %s, %s, %s', type, value, traceback)
        self.conn.unbind_s()
        return False

    def connect(self):
        """ connect to ldap as admin user """
        if FLAGS.fake_users:
            self.conn = fakeldap.initialize(FLAGS.ldap_url)
        else:
            assert(ldap.__name__ != 'fakeldap')
            self.conn = ldap.initialize(FLAGS.ldap_url)
        self.conn.simple_bind_s(self.user, self.passwd)

    def find_object(self, dn, query = None):
        objects = self.find_objects(dn, query)
        if len(objects) == 0:
            return None
        return objects[0]

    def find_objects(self, dn, query = None):
        try:
            res = self.conn.search_s(dn, ldap.SCOPE_SUBTREE, query)
        except Exception:
            return []
        # just return the attributes
        return [x[1] for x in res]

    def find_users(self):
        attrs = self.find_objects(FLAGS.ldap_subtree, '(objectclass=novaUser)')
        return [self.__to_user(attr) for attr in attrs]

    def find_key_pairs(self, uid):
        dn = 'uid=%s,%s' % (uid, FLAGS.ldap_subtree)
        attrs = self.find_objects(dn, '(objectclass=novaKeyPair)')
        return [self.__to_key_pair(uid, attr) for attr in attrs]

    def find_user(self, name):
        dn = 'uid=%s,%s' % (name, FLAGS.ldap_subtree)
        attr = self.find_object(dn, '(objectclass=novaUser)')
        return self.__to_user(attr)

    def user_exists(self, name):
        return self.find_user(name) != None

    def find_key_pair(self, uid, key_name):
        dn = 'cn=%s,uid=%s,%s' % (key_name,
                                   uid,
                                   FLAGS.ldap_subtree)
        attr = self.find_object(dn, '(objectclass=novaKeyPair)')
        return self.__to_key_pair(uid, attr)

    def delete_key_pairs(self, uid):
        keys = self.find_key_pairs(uid)
        if keys != None:
            for key in keys:
                self.delete_key_pair(uid, key.name)

    def key_pair_exists(self, uid, key_name):
        return self.find_key_pair(uid, key_name) != None

    def create_user(self, name, access_key, secret_key, is_admin):
        if self.user_exists(name):
            raise UserError("LDAP user " + name + " already exists")
        attr = [
            ('objectclass', ['person',
                             'organizationalPerson',
                             'inetOrgPerson',
                             'novaUser']),
            ('ou', [FLAGS.user_unit]),
            ('uid', [name]),
            ('sn', [name]),
            ('cn', [name]),
            ('secretKey', [secret_key]),
            ('accessKey', [access_key]),
            ('isAdmin', [str(is_admin).upper()]),
        ]
        self.conn.add_s('uid=%s,%s' % (name, FLAGS.ldap_subtree),
                        attr)
        return self.__to_user(dict(attr))

    def create_project(self, name, project_manager):
        # PM can be user object or string containing DN
        pass

    def is_member_of(self, name, group):
        return True

    def add_to_group(self, name, group):
        pass

    def remove_from_group(self, name, group):
        pass

    def create_key_pair(self, uid, key_name, public_key, fingerprint):
        """create's a public key in the directory underneath the user"""
        # TODO(vish): possibly refactor this to store keys in their own ou
        #   and put dn reference in the user object
        attr = [
            ('objectclass', ['novaKeyPair']),
            ('cn', [key_name]),
            ('sshPublicKey', [public_key]),
            ('keyFingerprint', [fingerprint]),
        ]
        self.conn.add_s('cn=%s,uid=%s,%s' % (key_name,
                                             uid,
                                             FLAGS.ldap_subtree),
                                             attr)
        return self.__to_key_pair(uid, dict(attr))

    def find_user_by_access_key(self, access):
        query = '(' + 'accessKey' + '=' + access + ')'
        dn = FLAGS.ldap_subtree
        return self.__to_user(self.find_object(dn, query))

    def delete_key_pair(self, uid, key_name):
        if not self.key_pair_exists(uid, key_name):
            raise UserError("Key Pair " +
                                    key_name +
                                    " doesn't exist for user " +
                                    uid)
        self.conn.delete_s('cn=%s,uid=%s,%s' % (key_name, uid,
                                          FLAGS.ldap_subtree))

    def delete_user(self, name):
        if not self.user_exists(name):
            raise UserError("User " +
                                    name +
                                    " doesn't exist")
        self.delete_key_pairs(name)
        self.conn.delete_s('uid=%s,%s' % (name,
                                          FLAGS.ldap_subtree))

    def __to_user(self, attr):
        if attr == None:
            return None
        return User(
            id = attr['uid'][0],
            name = attr['uid'][0],
            access = attr['accessKey'][0],
            secret = attr['secretKey'][0],
            admin = (attr['isAdmin'][0] == 'TRUE')
        )

    def __to_key_pair(self, owner, attr):
        if attr == None:
            return None
        return KeyPair(
            owner = owner,
            name = attr['cn'][0],
            public_key = attr['sshPublicKey'][0],
            fingerprint = attr['keyFingerprint'][0],
        )
