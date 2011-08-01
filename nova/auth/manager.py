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
WARNING: This code is deprecated and will be removed.
Keystone is the recommended solution for auth management.

Nova authentication management
"""

import os
import shutil
import string  # pylint: disable=W0402
import tempfile
import uuid
import zipfile

from nova import context
from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.auth import signer


FLAGS = flags.FLAGS
flags.DEFINE_bool('use_deprecated_auth',
                  False,
                  'This flag must be set to use old style auth')

flags.DEFINE_list('allowed_roles',
                  ['cloudadmin', 'itsec', 'sysadmin', 'netadmin', 'developer'],
                  'Allowed roles for project')
# NOTE(vish): a user with one of these roles will be a superuser and
#             have access to all api commands
flags.DEFINE_list('superuser_roles', ['cloudadmin'],
                  'Roles that ignore authorization checking completely')

# NOTE(vish): a user with one of these roles will have it for every
#             project, even if he or she is not a member of the project
flags.DEFINE_list('global_roles', ['cloudadmin', 'itsec'],
                  'Roles that apply to all projects')

flags.DEFINE_string('credentials_template',
                    utils.abspath('auth/novarc.template'),
                    'Template for creating users rc file')
flags.DEFINE_string('vpn_client_template',
                    utils.abspath('cloudpipe/client.ovpn.template'),
                    'Template for creating users vpn file')
flags.DEFINE_string('credential_vpn_file', 'nova-vpn.conf',
                    'Filename of certificate in credentials zip')
flags.DEFINE_string('credential_key_file', 'pk.pem',
                    'Filename of private key in credentials zip')
flags.DEFINE_string('credential_cert_file', 'cert.pem',
                    'Filename of certificate in credentials zip')
flags.DEFINE_string('credential_rc_file', '%src',
                    'Filename of rc in credentials zip, %s will be '
                    'replaced by name of the region (nova by default)')
flags.DEFINE_string('auth_driver', 'nova.auth.dbdriver.DbDriver',
                    'Driver that auth manager uses')

LOG = logging.getLogger('nova.auth.manager')


if FLAGS.memcached_servers:
    import memcache
else:
    from nova import fakememcache as memcache


class AuthBase(object):
    """Base class for objects relating to auth

    Objects derived from this class should be stupid data objects with
    an id member. They may optionally contain methods that delegate to
    AuthManager, but should not implement logic themselves.
    """

    @classmethod
    def safe_id(cls, obj):
        """Safely get object id.

        This method will return the id of the object if the object
        is of this class, otherwise it will return the original object.
        This allows methods to accept objects or ids as paramaters.
        """
        if isinstance(obj, cls):
            return obj.id
        else:
            return obj


class User(AuthBase):
    """Object representing a user

    The following attributes are defined:
    :id:       A system identifier for the user.  A string (for LDAP)
    :name:     The user name, potentially in some more friendly format
    :access:   The 'username' for EC2 authentication
    :secret:   The 'password' for EC2 authenticatoin
    :admin:    ???
    """

    def __init__(self, id, name, access, secret, admin):
        AuthBase.__init__(self)
        assert isinstance(id, basestring)
        self.id = id
        self.name = name
        self.access = access
        self.secret = secret
        self.admin = admin

    def is_superuser(self):
        return AuthManager().is_superuser(self)

    def is_admin(self):
        return AuthManager().is_admin(self)

    def has_role(self, role):
        return AuthManager().has_role(self, role)

    def add_role(self, role):
        return AuthManager().add_role(self, role)

    def remove_role(self, role):
        return AuthManager().remove_role(self, role)

    def is_project_member(self, project):
        return AuthManager().is_project_member(self, project)

    def is_project_manager(self, project):
        return AuthManager().is_project_manager(self, project)

    def __repr__(self):
        return "User('%s', '%s')" % (self.id, self.name)


class Project(AuthBase):
    """Represents a Project returned from the datastore"""

    def __init__(self, id, name, project_manager_id, description, member_ids):
        AuthBase.__init__(self)
        self.id = id
        self.name = name
        self.project_manager_id = project_manager_id
        self.description = description
        self.member_ids = member_ids

    @property
    def project_manager(self):
        return AuthManager().get_user(self.project_manager_id)

    @property
    def vpn_ip(self):
        ip, _port = AuthManager().get_project_vpn_data(self)
        return ip

    @property
    def vpn_port(self):
        _ip, port = AuthManager().get_project_vpn_data(self)
        return port

    def has_manager(self, user):
        return AuthManager().is_project_manager(user, self)

    def has_member(self, user):
        return AuthManager().is_project_member(user, self)

    def add_role(self, user, role):
        return AuthManager().add_role(user, role, self)

    def remove_role(self, user, role):
        return AuthManager().remove_role(user, role, self)

    def has_role(self, user, role):
        return AuthManager().has_role(user, role, self)

    def get_credentials(self, user):
        return AuthManager().get_credentials(user, self)

    def __repr__(self):
        return "Project('%s', '%s')" % (self.id, self.name)


class AuthManager(object):
    """Manager Singleton for dealing with Users, Projects, and Keypairs

    Methods accept objects or ids.

    AuthManager uses a driver object to make requests to the data backend.
    See ldapdriver for reference.

    AuthManager also manages associated data related to Auth objects that
    need to be more accessible, such as vpn ips and ports.
    """

    _instance = None
    mc = None

    def __new__(cls, *args, **kwargs):
        """Returns the AuthManager singleton"""
        if not cls._instance or ('new' in kwargs and kwargs['new']):
            cls._instance = super(AuthManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, driver=None, *args, **kwargs):
        """Inits the driver from parameter or flag

        __init__ is run every time AuthManager() is called, so we only
        reset the driver if it is not set or a new driver is specified.
        """
        self.network_manager = utils.import_object(FLAGS.network_manager)
        if driver or not getattr(self, 'driver', None):
            self.driver = utils.import_class(driver or FLAGS.auth_driver)
        if AuthManager.mc is None:
            AuthManager.mc = memcache.Client(FLAGS.memcached_servers, debug=0)

    def authenticate(self, access, signature, params, verb='GET',
                     server_string='127.0.0.1:8773', path='/',
                     check_type='ec2', headers=None):
        """Authenticates AWS request using access key and signature

        If the project is not specified, attempts to authenticate to
        a project with the same name as the user. This way, older tools
        that have no project knowledge will still work.

        @type access: str
        @param access: Access key for user in the form "access:project".

        @type signature: str
        @param signature: Signature of the request.

        @type params: list of str
        @param params: Web paramaters used for the signature.

        @type verb: str
        @param verb: Web request verb ('GET' or 'POST').

        @type server_string: str
        @param server_string: Web request server string.

        @type path: str
        @param path: Web request path.

        @type check_type: str
        @param check_type: Type of signature to check. 'ec2' for EC2, 's3' for
                           S3. Any other value will cause signature not to be
                           checked.

        @type headers: list
        @param headers: HTTP headers passed with the request (only needed for
                        s3 signature checks)

        @rtype: tuple (User, Project)
        @return: User and project that the request represents.
        """
        # TODO(vish): check for valid timestamp
        (access_key, _sep, project_id) = access.partition(':')

        LOG.debug(_('Looking up user: %r'), access_key)
        user = self.get_user_from_access_key(access_key)
        LOG.debug('user: %r', user)
        if user is None:
            LOG.audit(_("Failed authorization for access key %s"), access_key)
            raise exception.AccessKeyNotFound(access_key=access_key)

        # NOTE(vish): if we stop using project name as id we need better
        #             logic to find a default project for user
        if project_id == '':
            LOG.debug(_("Using project name = user name (%s)"), user.name)
            project_id = user.name

        project = self.get_project(project_id)
        if project is None:
            pjid = project_id
            uname = user.name
            LOG.audit(_("failed authorization: no project named %(pjid)s"
                    " (user=%(uname)s)") % locals())
            raise exception.ProjectNotFound(project_id=project_id)
        if not self.is_admin(user) and not self.is_project_member(user,
                                                                  project):
            uname = user.name
            uid = user.id
            pjname = project.name
            pjid = project.id
            LOG.audit(_("Failed authorization: user %(uname)s not admin"
                    " and not member of project %(pjname)s") % locals())
            raise exception.ProjectMembershipNotFound(project_id=pjid,
                                                      user_id=uid)
        if check_type == 's3':
            sign = signer.Signer(user.secret.encode())
            expected_signature = sign.s3_authorization(headers, verb, path)
            LOG.debug(_('user.secret: %s'), user.secret)
            LOG.debug(_('expected_signature: %s'), expected_signature)
            LOG.debug(_('signature: %s'), signature)
            if signature != expected_signature:
                LOG.audit(_("Invalid signature for user %s"), user.name)
                raise exception.InvalidSignature(signature=signature,
                                                 user=user)
        elif check_type == 'ec2':
            # NOTE(vish): hmac can't handle unicode, so encode ensures that
            #             secret isn't unicode
            expected_signature = signer.Signer(user.secret.encode()).generate(
                    params, verb, server_string, path)
            LOG.debug(_('user.secret: %s'), user.secret)
            LOG.debug(_('expected_signature: %s'), expected_signature)
            LOG.debug(_('signature: %s'), signature)
            if signature != expected_signature:
                (addr_str, port_str) = utils.parse_server_string(server_string)
                # If the given server_string contains port num, try without it.
                if port_str != '':
                    host_only_signature = signer.Signer(
                        user.secret.encode()).generate(params, verb,
                                                       addr_str, path)
                    LOG.debug(_('host_only_signature: %s'),
                              host_only_signature)
                    if signature == host_only_signature:
                        return (user, project)
                LOG.audit(_("Invalid signature for user %s"), user.name)
                raise exception.InvalidSignature(signature=signature,
                                                 user=user)
        return (user, project)

    def get_access_key(self, user, project):
        """Get an access key that includes user and project"""
        if not isinstance(user, User):
            user = self.get_user(user)
        return "%s:%s" % (user.access, Project.safe_id(project))

    def is_superuser(self, user):
        """Checks for superuser status, allowing user to bypass authorization

        @type user: User or uid
        @param user: User to check.

        @rtype: bool
        @return: True for superuser.
        """
        if not isinstance(user, User):
            user = self.get_user(user)
        # NOTE(vish): admin flag on user represents superuser
        if user.admin:
            return True
        for role in FLAGS.superuser_roles:
            if self.has_role(user, role):
                return True

    def is_admin(self, user):
        """Checks for admin status, allowing user to access all projects

        @type user: User or uid
        @param user: User to check.

        @rtype: bool
        @return: True for admin.
        """
        if not isinstance(user, User):
            user = self.get_user(user)
        if self.is_superuser(user):
            return True
        for role in FLAGS.global_roles:
            if self.has_role(user, role):
                return True

    def _build_mc_key(self, user, role, project=None):
        key_parts = ['rolecache', User.safe_id(user), str(role)]
        if project:
            key_parts.append(Project.safe_id(project))
        return '-'.join(key_parts)

    def _clear_mc_key(self, user, role, project=None):
        # NOTE(anthony): it would be better to delete the key
        self.mc.set(self._build_mc_key(user, role, project), None)

    def _has_role(self, user, role, project=None):
        mc_key = self._build_mc_key(user, role, project)
        rslt = self.mc.get(mc_key)
        if rslt is None:
            with self.driver() as drv:
                rslt = drv.has_role(user, role, project)
                self.mc.set(mc_key, rslt)
                return rslt
        else:
            return rslt

    def has_role(self, user, role, project=None):
        """Checks existence of role for user

        If project is not specified, checks for a global role. If project
        is specified, checks for the union of the global role and the
        project role.

        Role 'projectmanager' only works for projects and simply checks to
        see if the user is the project_manager of the specified project. It
        is the same as calling is_project_manager(user, project).

        @type user: User or uid
        @param user: User to check.

        @type role: str
        @param role: Role to check.

        @type project: Project or project_id
        @param project: Project in which to look for local role.

        @rtype: bool
        @return: True if the user has the role.
        """
        if role == 'projectmanager':
            if not project:
                raise exception.Error(_("Must specify project"))
            return self.is_project_manager(user, project)

        global_role = self._has_role(User.safe_id(user),
                                     role,
                                     None)

        if not global_role:
            return global_role

        if not project or role in FLAGS.global_roles:
            return global_role

        return self._has_role(User.safe_id(user),
                              role,
                              Project.safe_id(project))

    def add_role(self, user, role, project=None):
        """Adds role for user

        If project is not specified, adds a global role. If project
        is specified, adds a local role.

        The 'projectmanager' role is special and can't be added or removed.

        @type user: User or uid
        @param user: User to which to add role.

        @type role: str
        @param role: Role to add.

        @type project: Project or project_id
        @param project: Project in which to add local role.
        """
        if role not in FLAGS.allowed_roles:
            raise exception.UserRoleNotFound(role_id=role)
        if project is not None and role in FLAGS.global_roles:
            raise exception.GlobalRoleNotAllowed(role_id=role)
        uid = User.safe_id(user)
        pid = Project.safe_id(project)
        if project:
            LOG.audit(_("Adding role %(role)s to user %(uid)s"
                    " in project %(pid)s") % locals())
        else:
            LOG.audit(_("Adding sitewide role %(role)s to user %(uid)s")
                    % locals())
        with self.driver() as drv:
            self._clear_mc_key(uid, role, pid)
            drv.add_role(uid, role, pid)

    def remove_role(self, user, role, project=None):
        """Removes role for user

        If project is not specified, removes a global role. If project
        is specified, removes a local role.

        The 'projectmanager' role is special and can't be added or removed.

        @type user: User or uid
        @param user: User from which to remove role.

        @type role: str
        @param role: Role to remove.

        @type project: Project or project_id
        @param project: Project in which to remove local role.
        """
        uid = User.safe_id(user)
        pid = Project.safe_id(project)
        if project:
            LOG.audit(_("Removing role %(role)s from user %(uid)s"
                    " on project %(pid)s") % locals())
        else:
            LOG.audit(_("Removing sitewide role %(role)s"
                    " from user %(uid)s") % locals())
        with self.driver() as drv:
            self._clear_mc_key(uid, role, pid)
            drv.remove_role(uid, role, pid)

    @staticmethod
    def get_roles(project_roles=True):
        """Get list of allowed roles"""
        if project_roles:
            return list(set(FLAGS.allowed_roles) - set(FLAGS.global_roles))
        else:
            return FLAGS.allowed_roles

    def get_user_roles(self, user, project=None):
        """Get user global or per-project roles"""
        with self.driver() as drv:
            return drv.get_user_roles(User.safe_id(user),
                                      Project.safe_id(project))

    def get_active_roles(self, user, project=None):
        """Get all active roles for context"""
        if project:
            roles = FLAGS.allowed_roles + ['projectmanager']
        else:
            roles = FLAGS.global_roles
        return [role for role in roles if self.has_role(user, role, project)]

    def get_project(self, pid):
        """Get project object by id"""
        with self.driver() as drv:
            project_dict = drv.get_project(pid)
            if project_dict:
                return Project(**project_dict)

    def get_projects(self, user=None):
        """Retrieves list of projects, optionally filtered by user"""
        with self.driver() as drv:
            project_list = drv.get_projects(User.safe_id(user))
            if not project_list:
                return []
            return [Project(**project_dict) for project_dict in project_list]

    def create_project(self, name, manager_user, description=None,
                       member_users=None):
        """Create a project

        @type name: str
        @param name: Name of the project to create. The name will also be
        used as the project id.

        @type manager_user: User or uid
        @param manager_user: This user will be the project manager.

        @type description: str
        @param project: Description of the project. If no description is
        specified, the name of the project will be used.

        @type member_users: list of User or uid
        @param: Initial project members. The project manager will always be
        added as a member, even if he isn't specified in this list.

        @rtype: Project
        @return: The new project.
        """
        if member_users:
            member_users = [User.safe_id(u) for u in member_users]
        with self.driver() as drv:
            project_dict = drv.create_project(name,
                                              User.safe_id(manager_user),
                                              description,
                                              member_users)
            if project_dict:
                LOG.audit(_("Created project %(name)s with"
                        " manager %(manager_user)s") % locals())
                project = Project(**project_dict)
                return project

    def modify_project(self, project, manager_user=None, description=None):
        """Modify a project

        @type name: Project or project_id
        @param project: The project to modify.

        @type manager_user: User or uid
        @param manager_user: This user will be the new project manager.

        @type description: str
        @param project: This will be the new description of the project.

        """
        LOG.audit(_("modifying project %s"), Project.safe_id(project))
        if manager_user:
            manager_user = User.safe_id(manager_user)
        with self.driver() as drv:
            drv.modify_project(Project.safe_id(project),
                               manager_user,
                               description)

    def add_to_project(self, user, project):
        """Add user to project"""
        uid = User.safe_id(user)
        pid = Project.safe_id(project)
        LOG.audit(_("Adding user %(uid)s to project %(pid)s") % locals())
        with self.driver() as drv:
            return drv.add_to_project(User.safe_id(user),
                                      Project.safe_id(project))

    def is_project_manager(self, user, project):
        """Checks if user is project manager"""
        if not isinstance(project, Project):
            project = self.get_project(project)
        return User.safe_id(user) == project.project_manager_id

    def is_project_member(self, user, project):
        """Checks to see if user is a member of project"""
        if not isinstance(project, Project):
            project = self.get_project(project)
        return User.safe_id(user) in project.member_ids

    def remove_from_project(self, user, project):
        """Removes a user from a project"""
        uid = User.safe_id(user)
        pid = Project.safe_id(project)
        LOG.audit(_("Remove user %(uid)s from project %(pid)s") % locals())
        with self.driver() as drv:
            return drv.remove_from_project(uid, pid)

    @staticmethod
    def get_project_vpn_data(project):
        """Gets vpn ip and port for project

        @type project: Project or project_id
        @param project: Project from which to get associated vpn data

        @rvalue: tuple of (str, str)
        @return: A tuple containing (ip, port) or None, None if vpn has
        not been allocated for user.
        """

        networks = db.project_get_networks(context.get_admin_context(),
                                           Project.safe_id(project), False)
        if not networks:
            return (None, None)

        # TODO(tr3buchet): not sure what you guys plan on doing with this
        # but it's possible for a project to have multiple sets of vpn data
        # for now I'm just returning the first one
        network = networks[0]
        return (network['vpn_public_address'],
                network['vpn_public_port'])

    def delete_project(self, project):
        """Deletes a project"""
        LOG.audit(_("Deleting project %s"), Project.safe_id(project))
        with self.driver() as drv:
            drv.delete_project(Project.safe_id(project))

    def get_user(self, uid):
        """Retrieves a user by id"""
        with self.driver() as drv:
            user_dict = drv.get_user(uid)
            if user_dict:
                return User(**user_dict)

    def get_user_from_access_key(self, access_key):
        """Retrieves a user by access key"""
        with self.driver() as drv:
            user_dict = drv.get_user_from_access_key(access_key)
            if user_dict:
                return User(**user_dict)

    def get_users(self):
        """Retrieves a list of all users"""
        with self.driver() as drv:
            user_list = drv.get_users()
            if not user_list:
                return []
            return [User(**user_dict) for user_dict in user_list]

    def create_user(self, name, access=None, secret=None, admin=False):
        """Creates a user

        @type name: str
        @param name: Name of the user to create.

        @type access: str
        @param access: Access Key (defaults to a random uuid)

        @type secret: str
        @param secret: Secret Key (defaults to a random uuid)

        @type admin: bool
        @param admin: Whether to set the admin flag. The admin flag gives
        superuser status regardless of roles specifed for the user.

        @type create_project: bool
        @param: Whether to create a project for the user with the same name.

        @rtype: User
        @return: The new user.
        """
        if access is None:
            access = str(uuid.uuid4())
        if secret is None:
            secret = str(uuid.uuid4())
        with self.driver() as drv:
            user_dict = drv.create_user(name, access, secret, admin)
            if user_dict:
                rv = User(**user_dict)
                rvname = rv.name
                rvadmin = rv.admin
                LOG.audit(_("Created user %(rvname)s"
                        " (admin: %(rvadmin)r)") % locals())
                return rv

    def delete_user(self, user):
        """Deletes a user

        Additionally deletes all users key_pairs"""
        uid = User.safe_id(user)
        LOG.audit(_("Deleting user %s"), uid)
        db.key_pair_destroy_all_by_user(context.get_admin_context(),
                                        uid)
        with self.driver() as drv:
            drv.delete_user(uid)

    def modify_user(self, user, access_key=None, secret_key=None, admin=None):
        """Modify credentials for a user"""
        uid = User.safe_id(user)
        if access_key:
            LOG.audit(_("Access Key change for user %s"), uid)
        if secret_key:
            LOG.audit(_("Secret Key change for user %s"), uid)
        if admin is not None:
            LOG.audit(_("Admin status set to %(admin)r"
                    " for user %(uid)s") % locals())
        with self.driver() as drv:
            drv.modify_user(uid, access_key, secret_key, admin)

    def get_credentials(self, user, project=None, use_dmz=True):
        """Get credential zip for user in project"""
        if not isinstance(user, User):
            user = self.get_user(user)
        if project is None:
            project = user.id
        pid = Project.safe_id(project)
        private_key, signed_cert = crypto.generate_x509_cert(user.id, pid)

        tmpdir = tempfile.mkdtemp()
        zf = os.path.join(tmpdir, "temp.zip")
        zippy = zipfile.ZipFile(zf, 'w')
        if use_dmz and FLAGS.region_list:
            regions = {}
            for item in FLAGS.region_list:
                region, _sep, region_host = item.partition("=")
                regions[region] = region_host
        else:
            regions = {'nova': FLAGS.ec2_host}
        for region, host in regions.iteritems():
            rc = self.__generate_rc(user,
                                    pid,
                                    use_dmz,
                                    host)
            zippy.writestr(FLAGS.credential_rc_file % region, rc)

        zippy.writestr(FLAGS.credential_key_file, private_key)
        zippy.writestr(FLAGS.credential_cert_file, signed_cert)

        (vpn_ip, vpn_port) = self.get_project_vpn_data(project)
        if vpn_ip:
            configfile = open(FLAGS.vpn_client_template, "r")
            s = string.Template(configfile.read())
            configfile.close()
            config = s.substitute(keyfile=FLAGS.credential_key_file,
                                  certfile=FLAGS.credential_cert_file,
                                  ip=vpn_ip,
                                  port=vpn_port)
            zippy.writestr(FLAGS.credential_vpn_file, config)
        else:
            LOG.warn(_("No vpn data for project %s"), pid)

        zippy.writestr(FLAGS.ca_file, crypto.fetch_ca(pid))
        zippy.close()
        with open(zf, 'rb') as f:
            read_buffer = f.read()

        shutil.rmtree(tmpdir)
        return read_buffer

    def get_environment_rc(self, user, project=None, use_dmz=True):
        """Get environment rc for user in project"""
        if not isinstance(user, User):
            user = self.get_user(user)
        if project is None:
            project = user.id
        pid = Project.safe_id(project)
        return self.__generate_rc(user, pid, use_dmz)

    @staticmethod
    def __generate_rc(user, pid, use_dmz=True, host=None):
        """Generate rc file for user"""
        if use_dmz:
            ec2_host = FLAGS.ec2_dmz_host
        else:
            ec2_host = FLAGS.ec2_host
        # NOTE(vish): Always use the dmz since it is used from inside the
        #             instance
        s3_host = FLAGS.s3_dmz
        if host:
            s3_host = host
            ec2_host = host
        rc = open(FLAGS.credentials_template).read()
        # NOTE(vish): Deprecated auth uses an access key, no auth uses a
        #             the user_id in place of it.
        if FLAGS.use_deprecated_auth:
            access = user.access
        else:
            access = user.id
        rc = rc % {'access': access,
                   'project': pid,
                   'secret': user.secret,
                   'ec2': '%s://%s:%s%s' % (FLAGS.ec2_scheme,
                                            ec2_host,
                                            FLAGS.ec2_port,
                                            FLAGS.ec2_path),
                   's3': 'http://%s:%s' % (s3_host, FLAGS.s3_port),
                   'os': '%s://%s:%s%s' % (FLAGS.osapi_scheme,
                                            ec2_host,
                                            FLAGS.osapi_port,
                                            FLAGS.osapi_path),
                   'user': user.name,
                   'nova': FLAGS.ca_file,
                   'cert': FLAGS.credential_cert_file,
                   'key': FLAGS.credential_key_file}
        return rc
