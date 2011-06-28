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
Auth driver for ldap.  Includes FakeLdapDriver.

It should be easy to create a replacement for this driver supporting
other backends by creating another class that exposes the same
public methods.
"""

import functools
import sys

from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
flags.DEFINE_integer('ldap_schema_version', 2,
                     'Current version of the LDAP schema')
flags.DEFINE_string('ldap_url', 'ldap://localhost',
                    'Point this at your ldap server')
flags.DEFINE_string('ldap_password', 'changeme', 'LDAP password')
flags.DEFINE_string('ldap_user_dn', 'cn=Manager,dc=example,dc=com',
                    'DN of admin user')
flags.DEFINE_string('ldap_user_id_attribute', 'uid', 'Attribute to use as id')
flags.DEFINE_string('ldap_user_name_attribute', 'cn',
                    'Attribute to use as name')
flags.DEFINE_string('ldap_user_unit', 'Users', 'OID for Users')
flags.DEFINE_string('ldap_user_subtree', 'ou=Users,dc=example,dc=com',
                    'OU for Users')
flags.DEFINE_boolean('ldap_user_modify_only', False,
                    'Modify attributes for users instead of creating/deleting')
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

LOG = logging.getLogger("nova.ldapdriver")


if FLAGS.memcached_servers:
    import memcache
else:
    from nova import fakememcache as memcache


# TODO(vish): make an abstract base class with the same public methods
#             to define a set interface for AuthDrivers. I'm delaying
#             creating this now because I'm expecting an auth refactor
#             in which we may want to change the interface a bit more.


def _clean(attr):
    """Clean attr for insertion into ldap"""
    if attr is None:
        return None
    if type(attr) is unicode:
        return str(attr)
    return attr


def sanitize(fn):
    """Decorator to sanitize all args"""
    @functools.wraps(fn)
    def _wrapped(self, *args, **kwargs):
        args = [_clean(x) for x in args]
        kwargs = dict((k, _clean(v)) for (k, v) in kwargs)
        return fn(self, *args, **kwargs)
    _wrapped.func_name = fn.func_name
    return _wrapped


class LDAPWrapper(object):
    def __init__(self, ldap, url, user, password):
        self.ldap = ldap
        self.url = url
        self.user = user
        self.password = password
        self.conn = None

    def __wrap_reconnect(f):
        def inner(self, *args, **kwargs):
            if self.conn is None:
                self.connect()
                return f(self.conn)(*args, **kwargs)
            else:
                try:
                    return f(self.conn)(*args, **kwargs)
                except self.ldap.SERVER_DOWN:
                    self.connect()
                    return f(self.conn)(*args, **kwargs)
        return inner

    def connect(self):
        try:
            self.conn = self.ldap.initialize(self.url)
            self.conn.simple_bind_s(self.user, self.password)
        except self.ldap.SERVER_DOWN:
            self.conn = None
            raise

    search_s = __wrap_reconnect(lambda conn: conn.search_s)
    add_s = __wrap_reconnect(lambda conn: conn.add_s)
    delete_s = __wrap_reconnect(lambda conn: conn.delete_s)
    modify_s = __wrap_reconnect(lambda conn: conn.modify_s)


class LdapDriver(object):
    """Ldap Auth driver

    Defines enter and exit and therefore supports the with/as syntax.
    """

    project_pattern = '(owner=*)'
    isadmin_attribute = 'isNovaAdmin'
    project_attribute = 'owner'
    project_objectclass = 'groupOfNames'
    conn = None
    mc = None

    def __init__(self):
        """Imports the LDAP module"""
        self.ldap = __import__('ldap')
        if FLAGS.ldap_schema_version == 1:
            LdapDriver.project_pattern = '(objectclass=novaProject)'
            LdapDriver.isadmin_attribute = 'isAdmin'
            LdapDriver.project_attribute = 'projectManager'
            LdapDriver.project_objectclass = 'novaProject'
        self.__cache = None
        if LdapDriver.conn is None:
            LdapDriver.conn = LDAPWrapper(self.ldap, FLAGS.ldap_url,
                                          FLAGS.ldap_user_dn,
                                          FLAGS.ldap_password)
        if LdapDriver.mc is None:
            LdapDriver.mc = memcache.Client(FLAGS.memcached_servers, debug=0)

    def __enter__(self):
        # TODO(yorik-sar): Should be per-request cache, not per-driver-request
        self.__cache = {}
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__cache = None
        return False

    def __local_cache(key_fmt):  # pylint: disable=E0213
        """Wrap function to cache it's result in self.__cache.
        Works only with functions with one fixed argument.
        """
        def do_wrap(fn):
            @functools.wraps(fn)
            def inner(self, arg, **kwargs):
                cache_key = key_fmt % (arg,)
                try:
                    res = self.__cache[cache_key]
                    LOG.debug('Local cache hit for %s by key %s' %
                              (fn.__name__, cache_key))
                    return res
                except KeyError:
                    res = fn(self, arg, **kwargs)
                    self.__cache[cache_key] = res
                    return res
            return inner
        return do_wrap

    @sanitize
    @__local_cache('uid_user-%s')
    def get_user(self, uid):
        """Retrieve user by id"""
        attr = self.__get_ldap_user(uid)
        return self.__to_user(attr)

    @sanitize
    def get_user_from_access_key(self, access):
        """Retrieve user by access key"""
        cache_key = 'uak_dn_%s' % (access,)
        user_dn = self.mc.get(cache_key)
        if user_dn:
            user = self.__to_user(
                self.__find_object(user_dn, scope=self.ldap.SCOPE_BASE))
            if user:
                if user['access'] == access:
                    return user
                else:
                    self.mc.set(cache_key, None)
        query = '(accessKey=%s)' % access
        dn = FLAGS.ldap_user_subtree
        user_obj = self.__find_object(dn, query)
        user = self.__to_user(user_obj)
        if user:
            self.mc.set(cache_key, user_obj['dn'][0])
        return user

    @sanitize
    @__local_cache('pid_project-%s')
    def get_project(self, pid):
        """Retrieve project by id"""
        dn = self.__project_to_dn(pid, search=False)
        attr = self.__find_object(dn, LdapDriver.project_pattern,
                                  scope=self.ldap.SCOPE_BASE)
        return self.__to_project(attr)

    @sanitize
    def get_users(self):
        """Retrieve list of users"""
        attrs = self.__find_objects(FLAGS.ldap_user_subtree,
                                    '(objectclass=novaUser)')
        users = []
        for attr in attrs:
            user = self.__to_user(attr)
            if user is not None:
                users.append(user)
        return users

    @sanitize
    def get_projects(self, uid=None):
        """Retrieve list of projects"""
        pattern = LdapDriver.project_pattern
        if uid:
            pattern = "(&%s(member=%s))" % (pattern, self.__uid_to_dn(uid))
        attrs = self.__find_objects(FLAGS.ldap_project_subtree,
                                    pattern)
        return [self.__to_project(attr) for attr in attrs]

    @sanitize
    def create_user(self, name, access_key, secret_key, is_admin):
        """Create a user"""
        if self.__user_exists(name):
            raise exception.LDAPUserExists(user=name)
        if FLAGS.ldap_user_modify_only:
            if self.__ldap_user_exists(name):
                # Retrieve user by name
                user = self.__get_ldap_user(name)
                # Entry could be malformed, test for missing attrs.
                # Malformed entries are useless, replace attributes found.
                attr = []
                if 'secretKey' in user.keys():
                    attr.append((self.ldap.MOD_REPLACE, 'secretKey',
                                 [secret_key]))
                else:
                    attr.append((self.ldap.MOD_ADD, 'secretKey',
                                 [secret_key]))
                if 'accessKey' in user.keys():
                    attr.append((self.ldap.MOD_REPLACE, 'accessKey',
                                 [access_key]))
                else:
                    attr.append((self.ldap.MOD_ADD, 'accessKey',
                                 [access_key]))
                if LdapDriver.isadmin_attribute in user.keys():
                    attr.append((self.ldap.MOD_REPLACE,
                                 LdapDriver.isadmin_attribute,
                                 [str(is_admin).upper()]))
                else:
                    attr.append((self.ldap.MOD_ADD,
                                 LdapDriver.isadmin_attribute,
                                 [str(is_admin).upper()]))
                self.conn.modify_s(self.__uid_to_dn(name), attr)
                return self.get_user(name)
            else:
                raise exception.LDAPUserNotFound(user_id=name)
        else:
            attr = [
                ('objectclass', ['person',
                                 'organizationalPerson',
                                 'inetOrgPerson',
                                 'novaUser']),
                ('ou', [FLAGS.ldap_user_unit]),
                (FLAGS.ldap_user_id_attribute, [name]),
                ('sn', [name]),
                (FLAGS.ldap_user_name_attribute, [name]),
                ('secretKey', [secret_key]),
                ('accessKey', [access_key]),
                (LdapDriver.isadmin_attribute, [str(is_admin).upper()]),
            ]
            self.conn.add_s(self.__uid_to_dn(name), attr)
            return self.__to_user(dict(attr))

    @sanitize
    def create_project(self, name, manager_uid,
                       description=None, member_uids=None):
        """Create a project"""
        if self.__project_exists(name):
            raise exception.ProjectExists(project=name)
        if not self.__user_exists(manager_uid):
            raise exception.LDAPUserNotFound(user_id=manager_uid)
        manager_dn = self.__uid_to_dn(manager_uid)
        # description is a required attribute
        if description is None:
            description = name
        members = []
        if member_uids is not None:
            for member_uid in member_uids:
                if not self.__user_exists(member_uid):
                    raise exception.LDAPUserNotFound(user_id=member_uid)
                members.append(self.__uid_to_dn(member_uid))
        # always add the manager as a member because members is required
        if not manager_dn in members:
            members.append(manager_dn)
        attr = [
            ('objectclass', [LdapDriver.project_objectclass]),
            ('cn', [name]),
            ('description', [description]),
            (LdapDriver.project_attribute, [manager_dn]),
            ('member', members)]
        dn = self.__project_to_dn(name, search=False)
        self.conn.add_s(dn, attr)
        return self.__to_project(dict(attr))

    @sanitize
    def modify_project(self, project_id, manager_uid=None, description=None):
        """Modify an existing project"""
        if not manager_uid and not description:
            return
        attr = []
        if manager_uid:
            if not self.__user_exists(manager_uid):
                raise exception.LDAPUserNotFound(user_id=manager_uid)
            manager_dn = self.__uid_to_dn(manager_uid)
            attr.append((self.ldap.MOD_REPLACE, LdapDriver.project_attribute,
                         manager_dn))
        if description:
            attr.append((self.ldap.MOD_REPLACE, 'description', description))
        dn = self.__project_to_dn(project_id)
        self.conn.modify_s(dn, attr)
        if not self.is_in_project(manager_uid, project_id):
            self.add_to_project(manager_uid, project_id)

    @sanitize
    def add_to_project(self, uid, project_id):
        """Add user to project"""
        dn = self.__project_to_dn(project_id)
        return self.__add_to_group(uid, dn)

    @sanitize
    def remove_from_project(self, uid, project_id):
        """Remove user from project"""
        dn = self.__project_to_dn(project_id)
        return self.__remove_from_group(uid, dn)

    @sanitize
    def is_in_project(self, uid, project_id):
        """Check if user is in project"""
        dn = self.__project_to_dn(project_id)
        return self.__is_in_group(uid, dn)

    @sanitize
    def has_role(self, uid, role, project_id=None):
        """Check if user has role

        If project is specified, it checks for local role, otherwise it
        checks for global role
        """
        role_dn = self.__role_to_dn(role, project_id)
        return self.__is_in_group(uid, role_dn)

    @sanitize
    def add_role(self, uid, role, project_id=None):
        """Add role for user (or user and project)"""
        role_dn = self.__role_to_dn(role, project_id)
        if not self.__group_exists(role_dn):
            # create the role if it doesn't exist
            description = '%s role for %s' % (role, project_id)
            self.__create_group(role_dn, role, uid, description)
        else:
            return self.__add_to_group(uid, role_dn)

    @sanitize
    def remove_role(self, uid, role, project_id=None):
        """Remove role for user (or user and project)"""
        role_dn = self.__role_to_dn(role, project_id)
        return self.__remove_from_group(uid, role_dn)

    @sanitize
    def get_user_roles(self, uid, project_id=None):
        """Retrieve list of roles for user (or user and project)"""
        if project_id is None:
            # NOTE(vish): This is unneccesarily slow, but since we can't
            #             guarantee that the global roles are located
            #             together in the ldap tree, we're doing this version.
            roles = []
            for role in FLAGS.allowed_roles:
                role_dn = self.__role_to_dn(role)
                if self.__is_in_group(uid, role_dn):
                    roles.append(role)
            return roles
        else:
            project_dn = self.__project_to_dn(project_id)
            query = ('(&(&(objectclass=groupOfNames)(!%s))(member=%s))' %
                     (LdapDriver.project_pattern, self.__uid_to_dn(uid)))
            roles = self.__find_objects(project_dn, query)
            return [role['cn'][0] for role in roles]

    @sanitize
    def delete_user(self, uid):
        """Delete a user"""
        if not self.__user_exists(uid):
            raise exception.LDAPUserNotFound(user_id=uid)
        self.__remove_from_all(uid)
        if FLAGS.ldap_user_modify_only:
            # Delete attributes
            attr = []
            # Retrieve user by name
            user = self.__get_ldap_user(uid)
            if 'secretKey' in user.keys():
                attr.append((self.ldap.MOD_DELETE, 'secretKey',
                             user['secretKey']))
            if 'accessKey' in user.keys():
                attr.append((self.ldap.MOD_DELETE, 'accessKey',
                             user['accessKey']))
            if LdapDriver.isadmin_attribute in user.keys():
                attr.append((self.ldap.MOD_DELETE,
                             LdapDriver.isadmin_attribute,
                             user[LdapDriver.isadmin_attribute]))
            self.conn.modify_s(self.__uid_to_dn(uid), attr)
        else:
            # Delete entry
            self.conn.delete_s(self.__uid_to_dn(uid))

    @sanitize
    def delete_project(self, project_id):
        """Delete a project"""
        project_dn = self.__project_to_dn(project_id)
        self.__delete_roles(project_dn)
        self.__delete_group(project_dn)

    @sanitize
    def modify_user(self, uid, access_key=None, secret_key=None, admin=None):
        """Modify an existing user"""
        if not access_key and not secret_key and admin is None:
            return
        attr = []
        if access_key:
            attr.append((self.ldap.MOD_REPLACE, 'accessKey', access_key))
        if secret_key:
            attr.append((self.ldap.MOD_REPLACE, 'secretKey', secret_key))
        if admin is not None:
            attr.append((self.ldap.MOD_REPLACE, LdapDriver.isadmin_attribute,
                         str(admin).upper()))
        self.conn.modify_s(self.__uid_to_dn(uid), attr)

    def __user_exists(self, uid):
        """Check if user exists"""
        return self.get_user(uid) is not None

    def __ldap_user_exists(self, uid):
        """Check if the user exists in ldap"""
        return self.__get_ldap_user(uid) is not None

    def __project_exists(self, project_id):
        """Check if project exists"""
        return self.get_project(project_id) is not None

    @__local_cache('uid_attrs-%s')
    def __get_ldap_user(self, uid):
        """Retrieve LDAP user entry by id"""
        dn = FLAGS.ldap_user_subtree
        query = ('(&(%s=%s)(objectclass=novaUser))' %
                 (FLAGS.ldap_user_id_attribute, uid))
        return self.__find_object(dn, query)

    def __find_object(self, dn, query=None, scope=None):
        """Find an object by dn and query"""
        objects = self.__find_objects(dn, query, scope)
        if len(objects) == 0:
            return None
        return objects[0]

    def __find_dns(self, dn, query=None, scope=None):
        """Find dns by query"""
        if scope is None:
            # One of the flags is 0!
            scope = self.ldap.SCOPE_SUBTREE
        try:
            res = self.conn.search_s(dn, scope, query)
        except self.ldap.NO_SUCH_OBJECT:
            return []
        # Just return the DNs
        return [dn for dn, _attributes in res]

    def __find_objects(self, dn, query=None, scope=None):
        """Find objects by query"""
        if scope is None:
            # One of the flags is 0!
            scope = self.ldap.SCOPE_SUBTREE
        if query is None:
            query = "(objectClass=*)"
        try:
            res = self.conn.search_s(dn, scope, query)
        except self.ldap.NO_SUCH_OBJECT:
            return []
        # Just return the attributes
        # FIXME(yorik-sar): Whole driver should be refactored to
        #                   prevent this hack
        res1 = []
        for dn, attrs in res:
            attrs['dn'] = [dn]
            res1.append(attrs)
        return res1

    def __find_role_dns(self, tree):
        """Find dns of role objects in given tree"""
        query = ('(&(objectclass=groupOfNames)(!%s))' %
                 LdapDriver.project_pattern)
        return self.__find_dns(tree, query)

    def __find_group_dns_with_member(self, tree, uid):
        """Find dns of group objects in a given tree that contain member"""
        query = ('(&(objectclass=groupOfNames)(member=%s))' %
                 self.__uid_to_dn(uid))
        dns = self.__find_dns(tree, query)
        return dns

    def __group_exists(self, dn):
        """Check if group exists"""
        query = '(objectclass=groupOfNames)'
        return self.__find_object(dn, query) is not None

    def __role_to_dn(self, role, project_id=None):
        """Convert role to corresponding dn"""
        if project_id is None:
            return FLAGS.__getitem__("ldap_%s" % role).value
        else:
            project_dn = self.__project_to_dn(project_id)
            return 'cn=%s,%s' % (role, project_dn)

    def __create_group(self, group_dn, name, uid,
                       description, member_uids=None):
        """Create a group"""
        if self.__group_exists(group_dn):
            raise exception.LDAPGroupExists(group=name)
        members = []
        if member_uids is not None:
            for member_uid in member_uids:
                if not self.__user_exists(member_uid):
                    raise exception.LDAPUserNotFound(user_id=member_uid)
                members.append(self.__uid_to_dn(member_uid))
        dn = self.__uid_to_dn(uid)
        if not dn in members:
            members.append(dn)
        attr = [
            ('objectclass', ['groupOfNames']),
            ('cn', [name]),
            ('description', [description]),
            ('member', members)]
        self.conn.add_s(group_dn, attr)

    def __is_in_group(self, uid, group_dn):
        """Check if user is in group"""
        if not self.__user_exists(uid):
            raise exception.LDAPUserNotFound(user_id=uid)
        if not self.__group_exists(group_dn):
            return False
        res = self.__find_object(group_dn,
                                 '(member=%s)' % self.__uid_to_dn(uid),
                                 self.ldap.SCOPE_BASE)
        return res is not None

    def __add_to_group(self, uid, group_dn):
        """Add user to group"""
        if not self.__user_exists(uid):
            raise exception.LDAPUserNotFound(user_id=uid)
        if not self.__group_exists(group_dn):
            raise exception.LDAPGroupNotFound(group_id=group_dn)
        if self.__is_in_group(uid, group_dn):
            raise exception.LDAPMembershipExists(uid=uid, group_dn=group_dn)
        attr = [(self.ldap.MOD_ADD, 'member', self.__uid_to_dn(uid))]
        self.conn.modify_s(group_dn, attr)

    def __remove_from_group(self, uid, group_dn):
        """Remove user from group"""
        if not self.__group_exists(group_dn):
            raise exception.LDAPGroupNotFound(group_id=group_dn)
        if not self.__user_exists(uid):
            raise exception.LDAPUserNotFound(user_id=uid)
        if not self.__is_in_group(uid, group_dn):
            raise exception.LDAPGroupMembershipNotFound(user_id=uid,
                                                        group_id=group_dn)
        # NOTE(vish): remove user from group and any sub_groups
        sub_dns = self.__find_group_dns_with_member(group_dn, uid)
        for sub_dn in sub_dns:
            self.__safe_remove_from_group(uid, sub_dn)

    def __safe_remove_from_group(self, uid, group_dn):
        """Remove user from group, deleting group if user is last member"""
        # FIXME(vish): what if deleted user is a project manager?
        attr = [(self.ldap.MOD_DELETE, 'member', self.__uid_to_dn(uid))]
        try:
            self.conn.modify_s(group_dn, attr)
        except self.ldap.OBJECT_CLASS_VIOLATION:
            LOG.debug(_("Attempted to remove the last member of a group. "
                        "Deleting the group at %s instead."), group_dn)
            self.__delete_group(group_dn)

    def __remove_from_all(self, uid):
        """Remove user from all roles and projects"""
        if not self.__user_exists(uid):
            raise exception.LDAPUserNotFound(user_id=uid)
        role_dns = self.__find_group_dns_with_member(
                FLAGS.role_project_subtree, uid)
        for role_dn in role_dns:
            self.__safe_remove_from_group(uid, role_dn)
        project_dns = self.__find_group_dns_with_member(
                FLAGS.ldap_project_subtree, uid)
        for project_dn in project_dns:
            self.__safe_remove_from_group(uid, project_dn)

    def __delete_group(self, group_dn):
        """Delete Group"""
        if not self.__group_exists(group_dn):
            raise exception.LDAPGroupNotFound(group_id=group_dn)
        self.conn.delete_s(group_dn)

    def __delete_roles(self, project_dn):
        """Delete all roles for project"""
        for role_dn in self.__find_role_dns(project_dn):
            self.__delete_group(role_dn)

    def __to_project(self, attr):
        """Convert ldap attributes to Project object"""
        if attr is None:
            return None
        member_dns = attr.get('member', [])
        return {
            'id': attr['cn'][0],
            'name': attr['cn'][0],
            'project_manager_id':
                self.__dn_to_uid(attr[LdapDriver.project_attribute][0]),
            'description': attr.get('description', [None])[0],
            'member_ids': [self.__dn_to_uid(x) for x in member_dns]}

    @__local_cache('uid_dn-%s')
    def __uid_to_dn(self, uid, search=True):
        """Convert uid to dn"""
        # By default return a generated DN
        userdn = (FLAGS.ldap_user_id_attribute + '=%s,%s'
                  % (uid, FLAGS.ldap_user_subtree))
        if search:
            query = ('%s=%s' % (FLAGS.ldap_user_id_attribute, uid))
            user = self.__find_dns(FLAGS.ldap_user_subtree, query)
            if len(user) > 0:
                userdn = user[0]
        return userdn

    @__local_cache('pid_dn-%s')
    def __project_to_dn(self, pid, search=True):
        """Convert pid to dn"""
        # By default return a generated DN
        projectdn = ('cn=%s,%s' % (pid, FLAGS.ldap_project_subtree))
        if search:
            query = ('(&(cn=%s)%s)' % (pid, LdapDriver.project_pattern))
            project = self.__find_dns(FLAGS.ldap_project_subtree, query)
            if len(project) > 0:
                projectdn = project[0]
        return projectdn

    @staticmethod
    def __to_user(attr):
        """Convert ldap attributes to User object"""
        if attr is None:
            return None
        if ('accessKey' in attr.keys() and 'secretKey' in attr.keys() \
            and LdapDriver.isadmin_attribute in attr.keys()):
            return {
                'id': attr[FLAGS.ldap_user_id_attribute][0],
                'name': attr[FLAGS.ldap_user_name_attribute][0],
                'access': attr['accessKey'][0],
                'secret': attr['secretKey'][0],
                'admin': (attr[LdapDriver.isadmin_attribute][0] == 'TRUE')}
        else:
            return None

    @__local_cache('dn_uid-%s')
    def __dn_to_uid(self, dn):
        """Convert user dn to uid"""
        query = '(objectclass=novaUser)'
        user = self.__find_object(dn, query, scope=self.ldap.SCOPE_BASE)
        return user[FLAGS.ldap_user_id_attribute][0]


class FakeLdapDriver(LdapDriver):
    """Fake Ldap Auth driver"""

    def __init__(self):
        import nova.auth.fakeldap
        sys.modules['ldap'] = nova.auth.fakeldap
        super(FakeLdapDriver, self).__init__()
