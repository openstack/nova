#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

"""
Nova users and user management, including RBAC hooks.
"""

import datetime
import logging
import os
import shutil
import string
from string import Template
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
from nova.compute import model

from nova import objectstore # for flags

FLAGS = flags.FLAGS

flags.DEFINE_string('ldap_url', 'ldap://localhost',
                    'Point this at your ldap server')
flags.DEFINE_string('ldap_password',  'changeme', 'LDAP password')
flags.DEFINE_string('user_dn', 'cn=Manager,dc=example,dc=com',
                    'DN of admin user')
flags.DEFINE_string('user_unit', 'Users', 'OID for Users')
flags.DEFINE_string('user_ldap_subtree', 'ou=Users,dc=example,dc=com',
                    'OU for Users')
flags.DEFINE_string('project_ldap_subtree', 'ou=Groups,dc=example,dc=com',
                    'OU for Projects')
flags.DEFINE_string('role_ldap_subtree', 'ou=Groups,dc=example,dc=com',
                    'OU for Roles')

# NOTE(vish): mapping with these flags is necessary because we're going
#             to tie in to an existing ldap schema
flags.DEFINE_string('ldap_cloudadmin',
    'cn=cloudadmins,ou=Groups,dc=example,dc=com', 'cn for Cloud Admins')
flags.DEFINE_string('ldap_itsec',
    'cn=itsec,ou=Groups,dc=example,dc=com', 'cn for ItSec')
flags.DEFINE_string('ldap_sysadmin',
    'cn=sysadmins,ou=Groups,dc=example,dc=com', 'cn for Sysadmins')
flags.DEFINE_string('ldap_netadmin',
    'cn=netadmins,ou=Groups,dc=example,dc=com', 'cn for NetAdmins')
flags.DEFINE_string('ldap_developer',
    'cn=developers,ou=Groups,dc=example,dc=com', 'cn for Developers')

# NOTE(vish): a user with one of these roles will be a superuser and
#             have access to all api commands
flags.DEFINE_list('superuser_roles', ['cloudadmin'],
                  'roles that ignore rbac checking completely')

# NOTE(vish): a user with one of these roles will have it for every
#             project, even if he or she is not a member of the project
flags.DEFINE_list('global_roles', ['cloudadmin', 'itsec'],
                  'roles that apply to all projects')

flags.DEFINE_string('credentials_template',
                    utils.abspath('auth/novarc.template'),
                    'Template for creating users rc file')
flags.DEFINE_string('vpn_client_template',
                    utils.abspath('cloudpipe/client.ovpn.template'),
                    'Template for creating users vpn file')
flags.DEFINE_string('credential_key_file', 'pk.pem',
                    'Filename of private key in credentials zip')
flags.DEFINE_string('credential_cert_file', 'cert.pem',
                    'Filename of certificate in credentials zip')
flags.DEFINE_string('credential_rc_file', 'novarc',
                    'Filename of rc in credentials zip')
flags.DEFINE_integer('vpn_start_port', 8000,
                    'Start port for the cloudpipe VPN servers')
flags.DEFINE_integer('vpn_end_port', 9999,
                    'End port for the cloudpipe VPN servers')
flags.DEFINE_string('vpn_ip', '127.0.0.1',
                    'Public IP for the cloudpipe VPN servers')


class AuthBase(object):
    @classmethod
    def safe_id(cls, obj):
        """Safe get object id.

        This method will return the id of the object if the object
        is of this class, otherwise it will return the original object.
        This allows methods to accept objects or ids as paramaters.

        """
        if isinstance(obj, cls):
            return obj.id
        else:
            return obj


class User(AuthBase):
    """id and name are currently the same"""
    def __init__(self, id, name, access, secret, admin):
        self.id = id
        self.name = name
        self.access = access
        self.secret = secret
        self.admin = admin

    def is_superuser(self):
        """allows user to bypass rbac completely"""
        if self.admin:
            return True
        for role in FLAGS.superuser_roles:
            if self.has_role(role):
                return True

    def is_admin(self):
        """allows user to see objects from all projects"""
        if self.is_superuser():
            return True
        for role in FLAGS.global_roles:
            if self.has_role(role):
                return True

    def has_role(self, role):
        return UserManager.instance().has_role(self, role)

    def add_role(self, role):
        return UserManager.instance().add_role(self, role)

    def remove_role(self, role):
        return UserManager.instance().remove_role(self, role)

    def is_project_member(self, project):
        return UserManager.instance().is_project_member(self, project)

    def is_project_manager(self, project):
        return UserManager.instance().is_project_manager(self, project)

    def generate_rc(self, project=None):
        if project is None:
            project = self.id
        rc = open(FLAGS.credentials_template).read()
        rc = rc % { 'access': self.access,
                    'project': project,
                    'secret': self.secret,
                    'ec2': FLAGS.ec2_url,
                    's3': 'http://%s:%s' % (FLAGS.s3_host, FLAGS.s3_port),
                    'nova': FLAGS.ca_file,
                    'cert': FLAGS.credential_cert_file,
                    'key': FLAGS.credential_key_file,
            }
        return rc

    def generate_key_pair(self, name):
        return UserManager.instance().generate_key_pair(self.id, name)

    def create_key_pair(self, name, public_key, fingerprint):
        return UserManager.instance().create_key_pair(self.id,
                                            name,
                                            public_key,
                                            fingerprint)

    def get_key_pair(self, name):
        return UserManager.instance().get_key_pair(self.id, name)

    def delete_key_pair(self, name):
        return UserManager.instance().delete_key_pair(self.id, name)

    def get_key_pairs(self):
        return UserManager.instance().get_key_pairs(self.id)

    def __repr__(self):
        return "User('%s', '%s', '%s', '%s', %s)" % (
                self.id, self.name, self.access, self.secret, self.admin)


class KeyPair(AuthBase):
    def __init__(self, id, owner_id, public_key, fingerprint):
        self.id = id
        self.name = id
        self.owner_id = owner_id
        self.public_key = public_key
        self.fingerprint = fingerprint

    def delete(self):
        return UserManager.instance().delete_key_pair(self.owner, self.name)

    def __repr__(self):
        return "KeyPair('%s', '%s', '%s', '%s')" % (
                self.id, self.owner_id, self.public_key, self.fingerprint)


class Group(AuthBase):
    """id and name are currently the same"""
    def __init__(self, id, description = None, member_ids = None):
        self.id = id
        self.name = id
        self.description = description
        self.member_ids = member_ids

    def has_member(self, user):
        return User.safe_id(user) in self.member_ids

    def __repr__(self):
        return "Group('%s', '%s', %s)" % (
                self.id, self.description, self.member_ids)


class Project(Group):
    def __init__(self, id, project_manager_id, description, member_ids):
        self.project_manager_id = project_manager_id
        super(Project, self).__init__(id, description, member_ids)
        self.keeper = datastore.Keeper(prefix="project-")

    @property
    def project_manager(self):
        return UserManager.instance().get_user(self.project_manager_id)

    def has_manager(self, user):
        return User.safe_id(user) == self.project_manager_id

    def add_role(self, user, role):
        return UserManager.instance().add_role(user, role, self)

    def remove_role(self, user, role):
        return UserManager.instance().remove_role(user, role, self)

    def has_role(self, user, role):
        return UserManager.instance().has_role(user, role, self)

    @property
    def vpn_ip(self):
        return Vpn(self.id).ip

    @property
    def vpn_port(self):
        return Vpn(self.id).port

    def get_credentials(self, user):
        if not isinstance(user, User):
            user = UserManager.instance().get_user(user)
        rc = user.generate_rc(self.id)
        private_key, signed_cert = self.generate_x509_cert(user)

        configfile = open(FLAGS.vpn_client_template,"r")
        s = string.Template(configfile.read())
        configfile.close()
        config = s.substitute(keyfile=FLAGS.credential_key_file,
                              certfile=FLAGS.credential_cert_file,
                              ip=self.vpn_ip,
                              port=self.vpn_port)

        tmpdir = tempfile.mkdtemp()
        zf = os.path.join(tmpdir, "temp.zip")
        zippy = zipfile.ZipFile(zf, 'w')
        zippy.writestr(FLAGS.credential_rc_file, rc)
        zippy.writestr(FLAGS.credential_key_file, private_key)
        zippy.writestr(FLAGS.credential_cert_file, signed_cert)
        zippy.writestr("nebula-client.conf", config)
        zippy.writestr(FLAGS.ca_file, crypto.fetch_ca(self.id))
        zippy.close()
        with open(zf, 'rb') as f:
            buffer = f.read()

        shutil.rmtree(tmpdir)
        return buffer

    def generate_x509_cert(self, user):
        return UserManager.instance().generate_x509_cert(user, self)

    def __repr__(self):
        return "Project('%s', '%s', '%s', %s)" % (
                self.id, self.project_manager_id,
                self.description, self.member_ids)


class NoMorePorts(exception.Error):
    pass


class Vpn(model.BasicModel):
    def __init__(self, project_id):
        self.project_id = project_id
        super(Vpn, self).__init__()

    @property
    def identifier(self):
        return self.project_id

    @classmethod
    def create(cls, project_id):
        # TODO (vish): get list of vpn ips from redis
        for ip in [FLAGS.vpn_ip]:
            try:
                port = cls.find_free_port_for_ip(ip)
                vpn = cls(project_id)
                # save ip for project
                vpn['project'] = project_id
                vpn['ip'] = ip
                vpn['port'] = port
                vpn.save()
                return vpn
            except NoMorePorts:
                pass
        raise NoMorePorts()

    @classmethod
    def find_free_port_for_ip(cls, ip):
        # TODO(vish): the redis access should be refactored into a
        #             base class
        redis = datastore.Redis.instance()
        key = 'ip:%s:ports'
        # TODO(vish): these ports should be allocated through an admin
        #             command instead of a flag
        if (not redis.exists(key) and
            not redis.exists(cls._redis_association_name('ip', ip))):
            for i in range(FLAGS.vpn_start_port, FLAGS.vpn_end_port + 1):
                redis.sadd(key, i)

        port = datastore.Redis.instance().spop(key)
        if not port:
            raise NoMorePorts()
        return port

    @classmethod
    def num_ports_for_ip(cls, ip):
        return datastore.Redis.instance().scard('ip:%s:ports')

    @property
    def ip(self):
        return self['ip']

    @property
    def port(self):
        return int(self['port'])

    def save(self):
        self.associate_with('ip', self.ip)
        super(Vpn, self).save()

    def destroy(self):
        self.unassociate_with('ip', self.ip)
        datastore.Redis.instance().sadd('ip:%s:ports' % self.ip, self.port)
        super(Vpn, self).destroy()


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

    def authenticate(self, access, signature, params, verb='GET',
                     server_string='127.0.0.1:8773', path='/',
                     verify_signature=True):
        # TODO: Check for valid timestamp
        (access_key, sep, project_name) = access.partition(':')

        user = self.get_user_from_access_key(access_key)
        if user == None:
            raise exception.NotFound('No user found for access key %s' %
                                     access_key)
        if project_name is '':
            project_name = user.name

        project = self.get_project(project_name)
        if project == None:
            raise exception.NotFound('No project called %s could be found' %
                                     project_name)
        if not user.is_admin() and not project.has_member(user):
            raise exception.NotFound('User %s is not a member of project %s' %
                                     (user.id, project.id))
        if verify_signature:
            # NOTE(vish): hmac can't handle unicode, so encode ensures that
            #             secret isn't unicode
            expected_signature = signer.Signer(user.secret.encode()).generate(
                    params, verb, server_string, path)
            logging.debug('user.secret: %s', user.secret)
            logging.debug('expected_signature: %s', expected_signature)
            logging.debug('signature: %s', signature)
            if signature != expected_signature:
                raise exception.NotAuthorized('Signature does not match')
        return (user, project)

    def has_role(self, user, role, project=None):
        with LDAPWrapper() as conn:
            if role == 'projectmanager':
                if not project:
                    raise exception.Error("Must specify project")
                return self.is_project_manager(user, project)

            global_role = conn.has_role(User.safe_id(user),
                                        role,
                                        None)
            if not global_role:
                return global_role

            if not project or role in FLAGS.global_roles:
                return global_role

            return conn.has_role(User.safe_id(user),
                                 role,
                                 Project.safe_id(project))

    def add_role(self, user, role, project=None):
        with LDAPWrapper() as conn:
            return conn.add_role(User.safe_id(user), role,
                                 Project.safe_id(project))

    def remove_role(self, user, role, project=None):
        with LDAPWrapper() as conn:
            return conn.remove_role(User.safe_id(user), role,
                                    Project.safe_id(project))

    def create_project(self, name, manager_user,
                       description=None, member_users=None):
        if member_users:
            member_users = [User.safe_id(u) for u in member_users]
        with LDAPWrapper() as conn:
            # NOTE(vish): try to associate a vpn ip and port first because
            #             if it throws an exception, we save having to
            #             create and destroy a project
            Vpn.create(name)
            return conn.create_project(name,
                    User.safe_id(manager_user), description, member_users)


    def get_projects(self):
        with LDAPWrapper() as conn:
            return conn.find_projects()


    def get_project(self, project):
        with LDAPWrapper() as conn:
            return conn.find_project(Project.safe_id(project))

    def add_to_project(self, user, project):
        with LDAPWrapper() as conn:
            return conn.add_to_project(User.safe_id(user),
                                       Project.safe_id(project))

    def is_project_manager(self, user, project):
        if not isinstance(project, Project):
            project = self.get_project(project)
        return project.has_manager(user)

    def is_project_member(self, user, project):
        if isinstance(project, Project):
            return project.has_member(user)
        else:
            with LDAPWrapper() as conn:
                return conn.is_in_project(User.safe_id(user), project)

    def remove_from_project(self, user, project):
        with LDAPWrapper() as conn:
            return conn.remove_from_project(User.safe_id(user),
                                            Project.safe_id(project))

    def delete_project(self, project):
        with LDAPWrapper() as conn:
            return conn.delete_project(Project.safe_id(project))

    def get_user(self, uid):
        with LDAPWrapper() as conn:
            return conn.find_user(uid)

    def get_user_from_access_key(self, access_key):
        with LDAPWrapper() as conn:
            return conn.find_user_by_access_key(access_key)

    def get_users(self):
        with LDAPWrapper() as conn:
            return conn.find_users()

    def create_user(self, user, access=None, secret=None,
                    admin=False, create_project=True):
        if access == None: access = str(uuid.uuid4())
        if secret == None: secret = str(uuid.uuid4())
        with LDAPWrapper() as conn:
            user = User.safe_id(user)
            result = conn.create_user(user, access, secret, admin)
            if create_project:
                # NOTE(vish): if the project creation fails, we delete
                #             the user and return an exception
                try:
                    conn.create_project(user, user, user)
                except Exception:
                    conn.delete_user(user)
                    raise
            return result

    def delete_user(self, user, delete_project=True):
        with LDAPWrapper() as conn:
            user = User.safe_id(user)
            if delete_project:
                try:
                    conn.delete_project(user)
                except exception.NotFound:
                    pass
            conn.delete_user(user)

    def generate_key_pair(self, user, key_name):
        # generating key pair is slow so delay generation
        # until after check
        user = User.safe_id(user)
        with LDAPWrapper() as conn:
            if not conn.user_exists(user):
                raise exception.NotFound("User %s doesn't exist" % user)
            if conn.key_pair_exists(user, key_name):
                raise exception.Duplicate("The keypair %s already exists"
                                          % key_name)
        private_key, public_key, fingerprint = crypto.generate_key_pair()
        self.create_key_pair(User.safe_id(user), key_name,
                             public_key, fingerprint)
        return private_key, fingerprint

    def create_key_pair(self, user, key_name, public_key, fingerprint):
        with LDAPWrapper() as conn:
            return conn.create_key_pair(User.safe_id(user), key_name,
                                        public_key, fingerprint)

    def get_key_pair(self, user, key_name):
        with LDAPWrapper() as conn:
            return conn.find_key_pair(User.safe_id(user), key_name)

    def get_key_pairs(self, user):
        with LDAPWrapper() as conn:
            return conn.find_key_pairs(User.safe_id(user))

    def delete_key_pair(self, user, key_name):
        with LDAPWrapper() as conn:
            conn.delete_key_pair(User.safe_id(user), key_name)

    def generate_x509_cert(self, user, project):
        (private_key, csr) = crypto.generate_x509_cert(
                self.__cert_subject(User.safe_id(user)))
        # TODO - This should be async call back to the cloud controller
        signed_cert = crypto.sign_csr(csr, Project.safe_id(project))
        return (private_key, signed_cert)

    def __cert_subject(self, uid):
        # FIXME(ja) - this should be pulled from a global configuration
        return "/C=US/ST=California/L=MountainView/O=AnsoLabs/OU=NovaDev/CN=%s-%s" % (uid, str(datetime.datetime.utcnow().isoformat()))


class LDAPWrapper(object):
    def __init__(self):
        self.user = FLAGS.user_dn
        self.passwd = FLAGS.ldap_password

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, type, value, traceback):
        self.conn.unbind_s()
        return False

    def connect(self):
        """ connect to ldap as admin user """
        if FLAGS.fake_users:
            self.NO_SUCH_OBJECT = fakeldap.NO_SUCH_OBJECT
            self.OBJECT_CLASS_VIOLATION = fakeldap.OBJECT_CLASS_VIOLATION
            self.conn = fakeldap.initialize(FLAGS.ldap_url)
        else:
            self.NO_SUCH_OBJECT = ldap.NO_SUCH_OBJECT
            self.OBJECT_CLASS_VIOLATION = ldap.OBJECT_CLASS_VIOLATION
            self.conn = ldap.initialize(FLAGS.ldap_url)
        self.conn.simple_bind_s(self.user, self.passwd)

    def find_object(self, dn, query = None):
        objects = self.find_objects(dn, query)
        if len(objects) == 0:
            return None
        return objects[0]

    def find_dns(self, dn, query=None):
        try:
            res = self.conn.search_s(dn, ldap.SCOPE_SUBTREE, query)
        except self.NO_SUCH_OBJECT:
            return []
        # just return the DNs
        return [dn for dn, attributes in res]

    def find_objects(self, dn, query = None):
        try:
            res = self.conn.search_s(dn, ldap.SCOPE_SUBTREE, query)
        except self.NO_SUCH_OBJECT:
            return []
        # just return the attributes
        return [attributes for dn, attributes in res]

    def find_users(self):
        attrs = self.find_objects(FLAGS.user_ldap_subtree,
                                  '(objectclass=novaUser)')
        return [self.__to_user(attr) for attr in attrs]

    def find_key_pairs(self, uid):
        attrs = self.find_objects(self.__uid_to_dn(uid),
                                  '(objectclass=novaKeyPair)')
        return [self.__to_key_pair(uid, attr) for attr in attrs]

    def find_projects(self):
        attrs = self.find_objects(FLAGS.project_ldap_subtree,
                                  '(objectclass=novaProject)')
        return [self.__to_project(attr) for attr in attrs]

    def find_roles(self, tree):
        attrs = self.find_objects(tree,
                '(&(objectclass=groupOfNames)(!(objectclass=novaProject)))')
        return [self.__to_group(attr) for attr in attrs]

    def find_group_dns_with_member(self, tree, uid):
        dns = self.find_dns(tree,
                            '(&(objectclass=groupOfNames)(member=%s))' %
                            self.__uid_to_dn(uid))
        return dns

    def find_user(self, uid):
        attr = self.find_object(self.__uid_to_dn(uid),
                                '(objectclass=novaUser)')
        return self.__to_user(attr)

    def find_key_pair(self, uid, key_name):
        dn = 'cn=%s,%s' % (key_name,
                           self.__uid_to_dn(uid))
        attr = self.find_object(dn, '(objectclass=novaKeyPair)')
        return self.__to_key_pair(uid, attr)

    def find_group(self, dn):
        """uses dn directly instead of custructing it from name"""
        attr = self.find_object(dn, '(objectclass=groupOfNames)')
        return self.__to_group(attr)

    def find_project(self, name):
        dn = 'cn=%s,%s' % (name,
                           FLAGS.project_ldap_subtree)
        attr = self.find_object(dn, '(objectclass=novaProject)')
        return self.__to_project(attr)

    def user_exists(self, name):
        return self.find_user(name) != None

    def key_pair_exists(self, uid, key_name):
        return self.find_key_pair(uid, key_name) != None

    def project_exists(self, name):
        return self.find_project(name) != None

    def group_exists(self, dn):
        return self.find_group(dn) != None

    def delete_key_pairs(self, uid):
        keys = self.find_key_pairs(uid)
        if keys != None:
            for key in keys:
                self.delete_key_pair(uid, key.name)

    def create_user(self, name, access_key, secret_key, is_admin):
        if self.user_exists(name):
            raise exception.Duplicate("LDAP user %s already exists" % name)
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
        self.conn.add_s(self.__uid_to_dn(name), attr)
        return self.__to_user(dict(attr))

    def create_project(self, name, manager_uid,
                       description=None, member_uids=None):
        if self.project_exists(name):
            raise exception.Duplicate("Project can't be created because "
                                      "project %s already exists" % name)
        if not self.user_exists(manager_uid):
            raise exception.NotFound("Project can't be created because "
                                     "manager %s doesn't exist" % manager_uid)
        manager_dn = self.__uid_to_dn(manager_uid)
        # description is a required attribute
        if description is None:
            description = name
        members = []
        if member_uids != None:
            for member_uid in member_uids:
                if not self.user_exists(member_uid):
                    raise exception.NotFound("Project can't be created "
                            "because user %s doesn't exist" % member_uid)
                members.append(self.__uid_to_dn(member_uid))
        # always add the manager as a member because members is required
        if not manager_dn in members:
            members.append(manager_dn)
        attr = [
            ('objectclass', ['novaProject']),
            ('cn', [name]),
            ('description', [description]),
            ('projectManager', [manager_dn]),
            ('member', members)
        ]
        self.conn.add_s('cn=%s,%s' % (name, FLAGS.project_ldap_subtree), attr)
        return self.__to_project(dict(attr))

    def add_to_project(self, uid, project_id):
        dn = 'cn=%s,%s' % (project_id, FLAGS.project_ldap_subtree)
        return self.add_to_group(uid, dn)

    def remove_from_project(self, uid, project_id):
        dn = 'cn=%s,%s' % (project_id, FLAGS.project_ldap_subtree)
        return self.remove_from_group(uid, dn)

    def is_in_project(self, uid, project_id):
        dn = 'cn=%s,%s' % (project_id, FLAGS.project_ldap_subtree)
        return self.is_in_group(uid, dn)

    def __role_to_dn(self, role, project_id=None):
        if project_id == None:
            return FLAGS.__getitem__("ldap_%s" % role).value
        else:
            return 'cn=%s,cn=%s,%s' % (role,
                                       project_id,
                                       FLAGS.project_ldap_subtree)

    def __create_group(self, group_dn, name, uid,
                       description, member_uids = None):
        if self.group_exists(name):
            raise exception.Duplicate("Group can't be created because "
                                      "group %s already exists" % name)
        members = []
        if member_uids != None:
            for member_uid in member_uids:
                if not self.user_exists(member_uid):
                    raise exception.NotFound("Group can't be created "
                            "because user %s doesn't exist" % member_uid)
                members.append(self.__uid_to_dn(member_uid))
        dn = self.__uid_to_dn(uid)
        if not dn in members:
            members.append(dn)
        attr = [
            ('objectclass', ['groupOfNames']),
            ('cn', [name]),
            ('description', [description]),
            ('member', members)
        ]
        self.conn.add_s(group_dn, attr)
        return self.__to_group(dict(attr))

    def has_role(self, uid, role, project_id=None):
        role_dn = self.__role_to_dn(role, project_id)
        return self.is_in_group(uid, role_dn)

    def add_role(self, uid, role, project_id=None):
        role_dn = self.__role_to_dn(role, project_id)
        if not self.group_exists(role_dn):
            # create the role if it doesn't exist
            description = '%s role for %s' % (role, project_id)
            self.__create_group(role_dn, role, uid, description)
        else:
            return self.add_to_group(uid, role_dn)

    def remove_role(self, uid, role, project_id=None):
        role_dn = self.__role_to_dn(role, project_id)
        return self.remove_from_group(uid, role_dn)

    def is_in_group(self, uid, group_dn):
        if not self.user_exists(uid):
            raise exception.NotFound("User %s can't be searched in group "
                    "becuase the user doesn't exist" % (uid,))
        if not self.group_exists(group_dn):
            return False
        res = self.find_object(group_dn,
                               '(member=%s)' % self.__uid_to_dn(uid))
        return res != None

    def add_to_group(self, uid, group_dn):
        if not self.user_exists(uid):
            raise exception.NotFound("User %s can't be added to the group "
                    "becuase the user doesn't exist" % (uid,))
        if not self.group_exists(group_dn):
            raise exception.NotFound("The group at dn %s doesn't exist" %
                                     (group_dn,))
        if self.is_in_group(uid, group_dn):
            raise exception.Duplicate("User %s is already a member of "
                                      "the group %s" % (uid, group_dn))
        attr = [
            (ldap.MOD_ADD, 'member', self.__uid_to_dn(uid))
        ]
        self.conn.modify_s(group_dn, attr)

    def remove_from_group(self, uid, group_dn):
        if not self.group_exists(group_dn):
            raise exception.NotFound("The group at dn %s doesn't exist" %
                                     (group_dn,))
        if not self.user_exists(uid):
            raise exception.NotFound("User %s can't be removed from the "
                    "group because the user doesn't exist" % (uid,))
        if not self.is_in_group(uid, group_dn):
            raise exception.NotFound("User %s is not a member of the group" %
                                     (uid,))
        self._safe_remove_from_group(group_dn, uid)

    def _safe_remove_from_group(self, group_dn, uid):
        # FIXME(vish): what if deleted user is a project manager?
        attr = [(ldap.MOD_DELETE, 'member', self.__uid_to_dn(uid))]
        try:
            self.conn.modify_s(group_dn, attr)
        except self.OBJECT_CLASS_VIOLATION:
            logging.debug("Attempted to remove the last member of a group. "
                          "Deleting the group at %s instead." % group_dn )
            self.delete_group(group_dn)

    def remove_from_all(self, uid):
        if not self.user_exists(uid):
            raise exception.NotFound("User %s can't be removed from all "
                    "because the user doesn't exist" % (uid,))
        dn = self.__uid_to_dn(uid)
        role_dns = self.find_group_dns_with_member(
                FLAGS.role_ldap_subtree, uid)
        for role_dn in role_dns:
            self._safe_remove_from_group(role_dn, uid)
        project_dns = self.find_group_dns_with_member(
                FLAGS.project_ldap_subtree, uid)
        for project_dn in project_dns:
            self._safe_remove_from_group(project_dn, uid)

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
        self.conn.add_s('cn=%s,%s' % (key_name,
                                      self.__uid_to_dn(uid)),
                                      attr)
        return self.__to_key_pair(uid, dict(attr))

    def find_user_by_access_key(self, access):
        query = '(accessKey=%s)' % access
        dn = FLAGS.user_ldap_subtree
        return self.__to_user(self.find_object(dn, query))

    def delete_user(self, uid):
        if not self.user_exists(uid):
            raise exception.NotFound("User %s doesn't exist" % uid)
        self.delete_key_pairs(uid)
        self.remove_from_all(uid)
        self.conn.delete_s('uid=%s,%s' % (uid,
                                          FLAGS.user_ldap_subtree))

    def delete_key_pair(self, uid, key_name):
        if not self.key_pair_exists(uid, key_name):
            raise exception.NotFound("Key Pair %s doesn't exist for user %s" %
                            (key_name, uid))
        self.conn.delete_s('cn=%s,uid=%s,%s' % (key_name, uid,
                                          FLAGS.user_ldap_subtree))

    def delete_group(self, group_dn):
        if not self.group_exists(group_dn):
            raise exception.NotFound("Group at dn %s doesn't exist" % group_dn)
        self.conn.delete_s(group_dn)

    def delete_roles(self, project_dn):
        roles = self.find_roles(project_dn)
        for role in roles:
            self.delete_group('cn=%s,%s' % (role.id, project_dn))

    def delete_project(self, name):
        project_dn = 'cn=%s,%s' % (name, FLAGS.project_ldap_subtree)
        self.delete_roles(project_dn)
        self.delete_group(project_dn)

    def __to_user(self, attr):
        if attr == None:
            return None
        return User(
            id = attr['uid'][0],
            name = attr['cn'][0],
            access = attr['accessKey'][0],
            secret = attr['secretKey'][0],
            admin = (attr['isAdmin'][0] == 'TRUE')
        )

    def __to_key_pair(self, owner, attr):
        if attr == None:
            return None
        return KeyPair(
            id = attr['cn'][0],
            owner_id = owner,
            public_key = attr['sshPublicKey'][0],
            fingerprint = attr['keyFingerprint'][0],
        )

    def __to_group(self, attr):
        if attr == None:
            return None
        member_dns = attr.get('member', [])
        return Group(
            id = attr['cn'][0],
            description = attr.get('description', [None])[0],
            member_ids = [self.__dn_to_uid(x) for x in member_dns]
        )

    def __to_project(self, attr):
        if attr == None:
            return None
        member_dns = attr.get('member', [])
        return Project(
            id = attr['cn'][0],
            project_manager_id = self.__dn_to_uid(attr['projectManager'][0]),
            description = attr.get('description', [None])[0],
            member_ids = [self.__dn_to_uid(x) for x in member_dns]
        )

    def __dn_to_uid(self, dn):
        return dn.split(',')[0].split('=')[1]

    def __uid_to_dn(self, dn):
        return 'uid=%s,%s' % (dn, FLAGS.user_ldap_subtree)
