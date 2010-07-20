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

"""
Auth driver for ldap

It should be easy to create a replacement for this driver supporting
other backends by creating another class that exposes the same
public methods.
"""

import logging

from nova import exception
from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_string('ldap_url', 'ldap://localhost',
                    'Point this at your ldap server')
flags.DEFINE_string('ldap_password',  'changeme', 'LDAP password')
flags.DEFINE_string('ldap_user_dn', 'cn=Manager,dc=example,dc=com',
                    'DN of admin user')
flags.DEFINE_string('ldap_user_unit', 'Users', 'OID for Users')
flags.DEFINE_string('ldap_user_subtree', 'ou=Users,dc=example,dc=com',
                    'OU for Users')
flags.DEFINE_string('ldap_project_subtree', 'ou=Groups,dc=example,dc=com',
                    'OU for Projects')
flags.DEFINE_string('role_project_subtree', 'ou=Groups,dc=example,dc=com',
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


class LdapDriver(object):
    """Ldap Auth driver

    Defines enter and exit and therefore supports the with/as syntax.
    """
    def __enter__(self):
        """Creates the connection to LDAP"""
        global ldap
        if FLAGS.fake_users:
            from nova.auth import fakeldap as ldap
        else:
            import ldap
        self.conn = ldap.initialize(FLAGS.ldap_url)
        self.conn.simple_bind_s(FLAGS.ldap_user_dn, FLAGS.ldap_password)
        return self

    def __exit__(self, type, value, traceback):
        """Destroys the connection to LDAP"""
        self.conn.unbind_s()
        return False

    def get_user(self, uid):
        """Retrieve user by id"""
        attr = self.__find_object(self.__uid_to_dn(uid),
                                '(objectclass=novaUser)')
        return self.__to_user(attr)

    def get_user_from_access_key(self, access):
        """Retrieve user by access key"""
        query = '(accessKey=%s)' % access
        dn = FLAGS.ldap_user_subtree
        return self.__to_user(self.__find_object(dn, query))

    def get_key_pair(self, uid, key_name):
        """Retrieve key pair by uid and key name"""
        dn = 'cn=%s,%s' % (key_name,
                           self.__uid_to_dn(uid))
        attr = self.__find_object(dn, '(objectclass=novaKeyPair)')
        return self.__to_key_pair(uid, attr)

    def get_project(self, pid):
        """Retrieve project by id"""
        dn = 'cn=%s,%s' % (pid,
                           FLAGS.ldap_project_subtree)
        attr = self.__find_object(dn, '(objectclass=novaProject)')
        return self.__to_project(attr)

    def get_users(self):
        """Retrieve list of users"""
        attrs = self.__find_objects(FLAGS.ldap_user_subtree,
                                  '(objectclass=novaUser)')
        return [self.__to_user(attr) for attr in attrs]

    def get_key_pairs(self, uid):
        """Retrieve list of key pairs"""
        attrs = self.__find_objects(self.__uid_to_dn(uid),
                                  '(objectclass=novaKeyPair)')
        return [self.__to_key_pair(uid, attr) for attr in attrs]

    def get_projects(self):
        """Retrieve list of projects"""
        attrs = self.__find_objects(FLAGS.ldap_project_subtree,
                                  '(objectclass=novaProject)')
        return [self.__to_project(attr) for attr in attrs]

    def create_user(self, name, access_key, secret_key, is_admin):
        """Create a user"""
        if self.__user_exists(name):
            raise exception.Duplicate("LDAP user %s already exists" % name)
        attr = [
            ('objectclass', ['person',
                             'organizationalPerson',
                             'inetOrgPerson',
                             'novaUser']),
            ('ou', [FLAGS.ldap_user_unit]),
            ('uid', [name]),
            ('sn', [name]),
            ('cn', [name]),
            ('secretKey', [secret_key]),
            ('accessKey', [access_key]),
            ('isAdmin', [str(is_admin).upper()]),
        ]
        self.conn.add_s(self.__uid_to_dn(name), attr)
        return self.__to_user(dict(attr))

    def create_key_pair(self, uid, key_name, public_key, fingerprint):
        """Create a key pair"""
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

    def create_project(self, name, manager_uid,
                       description=None, member_uids=None):
        """Create a project"""
        if self.__project_exists(name):
            raise exception.Duplicate("Project can't be created because "
                                      "project %s already exists" % name)
        if not self.__user_exists(manager_uid):
            raise exception.NotFound("Project can't be created because "
                                     "manager %s doesn't exist" % manager_uid)
        manager_dn = self.__uid_to_dn(manager_uid)
        # description is a required attribute
        if description is None:
            description = name
        members = []
        if member_uids != None:
            for member_uid in member_uids:
                if not self.__user_exists(member_uid):
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
        self.conn.add_s('cn=%s,%s' % (name, FLAGS.ldap_project_subtree), attr)
        return self.__to_project(dict(attr))

    def add_to_project(self, uid, project_id):
        """Add user to project"""
        dn = 'cn=%s,%s' % (project_id, FLAGS.ldap_project_subtree)
        return self.__add_to_group(uid, dn)

    def remove_from_project(self, uid, project_id):
        """Remove user from project"""
        dn = 'cn=%s,%s' % (project_id, FLAGS.ldap_project_subtree)
        return self.__remove_from_group(uid, dn)

    def is_in_project(self, uid, project_id):
        """Check if user is in project"""
        dn = 'cn=%s,%s' % (project_id, FLAGS.ldap_project_subtree)
        return self.__is_in_group(uid, dn)

    def has_role(self, uid, role, project_id=None):
        """Check if user has role

        If project is specified, it checks for local role, otherwise it
        checks for global role
        """
        role_dn = self.__role_to_dn(role, project_id)
        return self.__is_in_group(uid, role_dn)

    def add_role(self, uid, role, project_id=None):
        """Add role for user (or user and project)"""
        role_dn = self.__role_to_dn(role, project_id)
        if not self.__group_exists(role_dn):
            # create the role if it doesn't exist
            description = '%s role for %s' % (role, project_id)
            self.__create_group(role_dn, role, uid, description)
        else:
            return self.__add_to_group(uid, role_dn)

    def remove_role(self, uid, role, project_id=None):
        """Remove role for user (or user and project)"""
        role_dn = self.__role_to_dn(role, project_id)
        return self.__remove_from_group(uid, role_dn)

    def delete_user(self, uid):
        """Delete a user"""
        if not self.__user_exists(uid):
            raise exception.NotFound("User %s doesn't exist" % uid)
        self.__delete_key_pairs(uid)
        self.__remove_from_all(uid)
        self.conn.delete_s('uid=%s,%s' % (uid,
                                          FLAGS.ldap_user_subtree))

    def delete_key_pair(self, uid, key_name):
        """Delete a key pair"""
        if not self.__key_pair_exists(uid, key_name):
            raise exception.NotFound("Key Pair %s doesn't exist for user %s" %
                            (key_name, uid))
        self.conn.delete_s('cn=%s,uid=%s,%s' % (key_name, uid,
                                          FLAGS.ldap_user_subtree))

    def delete_project(self, name):
        """Delete a project"""
        project_dn = 'cn=%s,%s' % (name, FLAGS.ldap_project_subtree)
        self.__delete_roles(project_dn)
        self.__delete_group(project_dn)

    def __user_exists(self, name):
        """Check if user exists"""
        return self.get_user(name) != None

    def __key_pair_exists(self, uid, key_name):
        """Check if key pair exists"""
        return self.get_user(uid) != None
        return self.get_key_pair(uid, key_name) != None

    def __project_exists(self, name):
        """Check if project exists"""
        return self.get_project(name) != None

    def __find_object(self, dn, query = None):
        """Find an object by dn and query"""
        objects = self.__find_objects(dn, query)
        if len(objects) == 0:
            return None
        return objects[0]

    def __find_dns(self, dn, query=None):
        """Find dns by query"""
        try:
            res = self.conn.search_s(dn, ldap.SCOPE_SUBTREE, query)
        except ldap.NO_SUCH_OBJECT:
            return []
        # just return the DNs
        return [dn for dn, attributes in res]

    def __find_objects(self, dn, query = None):
        """Find objects by query"""
        try:
            res = self.conn.search_s(dn, ldap.SCOPE_SUBTREE, query)
        except ldap.NO_SUCH_OBJECT:
            return []
        # just return the attributes
        return [attributes for dn, attributes in res]

    def __find_role_dns(self, tree):
        """Find dns of role objects in given tree"""
        return self.__find_dns(tree,
                '(&(objectclass=groupOfNames)(!(objectclass=novaProject)))')

    def __find_group_dns_with_member(self, tree, uid):
        """Find dns of group objects in a given tree that contain member"""
        dns = self.__find_dns(tree,
                            '(&(objectclass=groupOfNames)(member=%s))' %
                            self.__uid_to_dn(uid))
        return dns

    def __group_exists(self, dn):
        """Check if group exists"""
        return self.__find_object(dn, '(objectclass=groupOfNames)') != None

    def __delete_key_pairs(self, uid):
        """Delete all key pairs for user"""
        keys = self.get_key_pairs(uid)
        if keys != None:
            for key in keys:
                self.delete_key_pair(uid, key['name'])

    def __role_to_dn(self, role, project_id=None):
        """Convert role to corresponding dn"""
        if project_id == None:
            return FLAGS.__getitem__("ldap_%s" % role).value
        else:
            return 'cn=%s,cn=%s,%s' % (role,
                                       project_id,
                                       FLAGS.ldap_project_subtree)

    def __create_group(self, group_dn, name, uid,
                       description, member_uids = None):
        """Create a group"""
        if self.__group_exists(group_dn):
            raise exception.Duplicate("Group can't be created because "
                                      "group %s already exists" % name)
        members = []
        if member_uids != None:
            for member_uid in member_uids:
                if not self.__user_exists(member_uid):
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

    def __is_in_group(self, uid, group_dn):
        """Check if user is in group"""
        if not self.__user_exists(uid):
            raise exception.NotFound("User %s can't be searched in group "
                    "becuase the user doesn't exist" % (uid,))
        if not self.__group_exists(group_dn):
            return False
        res = self.__find_object(group_dn,
                               '(member=%s)' % self.__uid_to_dn(uid))
        return res != None

    def __add_to_group(self, uid, group_dn):
        """Add user to group"""
        if not self.__user_exists(uid):
            raise exception.NotFound("User %s can't be added to the group "
                    "becuase the user doesn't exist" % (uid,))
        if not self.__group_exists(group_dn):
            raise exception.NotFound("The group at dn %s doesn't exist" %
                                     (group_dn,))
        if self.__is_in_group(uid, group_dn):
            raise exception.Duplicate("User %s is already a member of "
                                      "the group %s" % (uid, group_dn))
        attr = [
            (ldap.MOD_ADD, 'member', self.__uid_to_dn(uid))
        ]
        self.conn.modify_s(group_dn, attr)

    def __remove_from_group(self, uid, group_dn):
        """Remove user from group"""
        if not self.__group_exists(group_dn):
            raise exception.NotFound("The group at dn %s doesn't exist" %
                                     (group_dn,))
        if not self.__user_exists(uid):
            raise exception.NotFound("User %s can't be removed from the "
                    "group because the user doesn't exist" % (uid,))
        if not self.__is_in_group(uid, group_dn):
            raise exception.NotFound("User %s is not a member of the group" %
                                     (uid,))
        self.__safe_remove_from_group(uid, group_dn)

    def __safe_remove_from_group(self, uid, group_dn):
        """Remove user from group, deleting group if user is last member"""
        # FIXME(vish): what if deleted user is a project manager?
        attr = [(ldap.MOD_DELETE, 'member', self.__uid_to_dn(uid))]
        try:
            self.conn.modify_s(group_dn, attr)
        except ldap.OBJECT_CLASS_VIOLATION:
            logging.debug("Attempted to remove the last member of a group. "
                          "Deleting the group at %s instead." % group_dn )
            self.__delete_group(group_dn)

    def __remove_from_all(self, uid):
        """Remove user from all roles and projects"""
        if not self.__user_exists(uid):
            raise exception.NotFound("User %s can't be removed from all "
                    "because the user doesn't exist" % (uid,))
        dn = self.__uid_to_dn(uid)
        role_dns = self.__find_group_dns_with_member(
                FLAGS.role_project_subtree, uid)
        for role_dn in role_dns:
            self.__safe_remove_from_group(uid, role_dn)
        project_dns = self.__find_group_dns_with_member(
                FLAGS.ldap_project_subtree, uid)
        for project_dn in project_dns:
            self.__safe_remove_from_group(uid, role_dn)

    def __delete_group(self, group_dn):
        """Delete Group"""
        if not self.__group_exists(group_dn):
            raise exception.NotFound("Group at dn %s doesn't exist" % group_dn)
        self.conn.delete_s(group_dn)

    def __delete_roles(self, project_dn):
        """Delete all roles for project"""
        for role_dn in self.__find_role_dns(project_dn):
            self.__delete_group(role_dn)

    def __to_user(self, attr):
        """Convert ldap attributes to User object"""
        if attr == None:
            return None
        return {
            'id': attr['uid'][0],
            'name': attr['cn'][0],
            'access': attr['accessKey'][0],
            'secret': attr['secretKey'][0],
            'admin': (attr['isAdmin'][0] == 'TRUE')
        }

    def __to_key_pair(self, owner, attr):
        """Convert ldap attributes to KeyPair object"""
        if attr == None:
            return None
        return {
            'id': attr['cn'][0],
            'name': attr['cn'][0],
            'owner_id': owner,
            'public_key': attr['sshPublicKey'][0],
            'fingerprint': attr['keyFingerprint'][0],
        }

    def __to_project(self, attr):
        """Convert ldap attributes to Project object"""
        if attr == None:
            return None
        member_dns = attr.get('member', [])
        return {
            'id': attr['cn'][0],
            'name': attr['cn'][0],
            'project_manager_id': self.__dn_to_uid(attr['projectManager'][0]),
            'description': attr.get('description', [None])[0],
            'member_ids': [self.__dn_to_uid(x) for x in member_dns]
        }

    def __dn_to_uid(self, dn):
        """Convert user dn to uid"""
        return dn.split(',')[0].split('=')[1]

    def __uid_to_dn(self, dn):
        """Convert uid to dn"""
        return 'uid=%s,%s' % (dn, FLAGS.ldap_user_subtree)

