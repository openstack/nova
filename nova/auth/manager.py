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
Nova authentication management
"""

import logging
import os
import shutil
import string # pylint: disable-msg=W0402
import tempfile
import uuid
import zipfile

from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import utils
from nova.auth import signer


FLAGS = flags.FLAGS
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
flags.DEFINE_string('credential_rc_file', 'novarc',
                    'Filename of rc in credentials zip')
flags.DEFINE_string('credential_cert_subject',
                    '/C=US/ST=California/L=MountainView/O=AnsoLabs/'
                    'OU=NovaDev/CN=%s-%s',
                    'Subject for certificate for users')
flags.DEFINE_string('auth_driver', 'nova.auth.ldapdriver.FakeLdapDriver',
                    'Driver that auth manager uses')


class AuthBase(object):
    """Base class for objects relating to auth

    Objects derived from this class should be stupid data objects with
    an id member. They may optionally contain methods that delegate to
    AuthManager, but should not implement logic themselves.
    """

    @classmethod
    def safe_id(cls, obj):
        """Safe get object id

        This method will return the id of the object if the object
        is of this class, otherwise it will return the original object.
        This allows methods to accept objects or ids as paramaters.

        """
        if isinstance(obj, cls):
            return obj.id
        else:
            return obj


class User(AuthBase):
    """Object representing a user"""

    def __init__(self, id, name, access, secret, admin):
        AuthBase.__init__(self)
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
        return "User('%s', '%s', '%s', '%s', %s)" % (self.id,
                                                     self.name,
                                                     self.access,
                                                     self.secret,
                                                     self.admin)


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
        return "Project('%s', '%s', '%s', '%s', %s)" % \
            (self.id, self.name, self.project_manager_id, self.description,
             self.member_ids)


class AuthManager(object):
    """Manager Singleton for dealing with Users, Projects, and Keypairs

    Methods accept objects or ids.

    AuthManager uses a driver object to make requests to the data backend.
    See ldapdriver for reference.

    AuthManager also manages associated data related to Auth objects that
    need to be more accessible, such as vpn ips and ports.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Returns the AuthManager singleton"""
        if not cls._instance:
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

        logging.info('Looking up user: %r', access_key)
        user = self.get_user_from_access_key(access_key)
        logging.info('user: %r', user)
        if user == None:
            raise exception.NotFound('No user found for access key %s' %
                                     access_key)

        # NOTE(vish): if we stop using project name as id we need better
        #             logic to find a default project for user
        if project_id is '':
            project_id = user.name

        project = self.get_project(project_id)
        if project == None:
            raise exception.NotFound('No project called %s could be found' %
                                     project_id)
        if not self.is_admin(user) and not self.is_project_member(user,
                                                                  project):
            raise exception.NotFound('User %s is not a member of project %s' %
                                     (user.id, project.id))
        if check_type == 's3':
            sign = signer.Signer(user.secret.encode())
            expected_signature = sign.s3_authorization(headers, verb, path)
            logging.debug('user.secret: %s', user.secret)
            logging.debug('expected_signature: %s', expected_signature)
            logging.debug('signature: %s', signature)
            if signature != expected_signature:
                raise exception.NotAuthorized('Signature does not match')
        elif check_type == 'ec2':
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
        with self.driver() as drv:
            if role == 'projectmanager':
                if not project:
                    raise exception.Error("Must specify project")
                return self.is_project_manager(user, project)

            global_role = drv.has_role(User.safe_id(user),
                                        role,
                                        None)
            if not global_role:
                return global_role

            if not project or role in FLAGS.global_roles:
                return global_role

            return drv.has_role(User.safe_id(user),
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
            raise exception.NotFound("The %s role can not be found" % role)
        if project is not None and role in FLAGS.global_roles:
            raise exception.NotFound("The %s role is global only" % role)
        with self.driver() as drv:
            drv.add_role(User.safe_id(user), role, Project.safe_id(project))

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
        with self.driver() as drv:
            drv.remove_role(User.safe_id(user), role, Project.safe_id(project))

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
                       member_users=None, context=None):
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
                project = Project(**project_dict)
                try:
                    self.network_manager.allocate_network(context,
                                                          project.id)
                except:
                    drv.delete_project(project.id)
                    raise
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
        if manager_user:
            manager_user = User.safe_id(manager_user)
        with self.driver() as drv:
            drv.modify_project(Project.safe_id(project),
                               manager_user,
                               description)

    def add_to_project(self, user, project):
        """Add user to project"""
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
        with self.driver() as drv:
            return drv.remove_from_project(User.safe_id(user),
                                            Project.safe_id(project))

    @staticmethod
    def get_project_vpn_data(project, context=None):
        """Gets vpn ip and port for project

        @type project: Project or project_id
        @param project: Project from which to get associated vpn data

        @rvalue: tuple of (str, str)
        @return: A tuple containing (ip, port) or None, None if vpn has
        not been allocated for user.
        """

        network_ref = db.project_get_network(context,
                                             Project.safe_id(project))

        if not network_ref['vpn_public_port']:
            raise exception.NotFound('project network data has not been set')
        return (network_ref['vpn_public_address'],
                network_ref['vpn_public_port'])

    def delete_project(self, project, context=None):
        """Deletes a project"""
        try:
            network_ref = db.project_get_network(context,
                                                 Project.safe_id(project))
            db.network_destroy(context, network_ref['id'])
        except:
            logging.exception('Could not destroy network for %s',
                              project)
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
        if access == None:
            access = str(uuid.uuid4())
        if secret == None:
            secret = str(uuid.uuid4())
        with self.driver() as drv:
            user_dict = drv.create_user(name, access, secret, admin)
            if user_dict:
                return User(**user_dict)

    def delete_user(self, user):
        """Deletes a user

        Additionally deletes all users key_pairs"""
        uid = User.safe_id(user)
        db.key_pair_destroy_all_by_user(None, uid)
        with self.driver() as drv:
            drv.delete_user(uid)

    def get_credentials(self, user, project=None):
        """Get credential zip for user in project"""
        if not isinstance(user, User):
            user = self.get_user(user)
        if project is None:
            project = user.id
        pid = Project.safe_id(project)
        rc = self.__generate_rc(user.access, user.secret, pid)
        private_key, signed_cert = self._generate_x509_cert(user.id, pid)

        tmpdir = tempfile.mkdtemp()
        zf = os.path.join(tmpdir, "temp.zip")
        zippy = zipfile.ZipFile(zf, 'w')
        zippy.writestr(FLAGS.credential_rc_file, rc)
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
            logging.warn("No vpn data for project %s" %
                                  pid)

        zippy.writestr(FLAGS.ca_file, crypto.fetch_ca(user.id))
        zippy.close()
        with open(zf, 'rb') as f:
            read_buffer = f.read()

        shutil.rmtree(tmpdir)
        return read_buffer

    def get_environment_rc(self, user, project=None):
        """Get credential zip for user in project"""
        if not isinstance(user, User):
            user = self.get_user(user)
        if project is None:
            project = user.id
        pid = Project.safe_id(project)
        return self.__generate_rc(user.access, user.secret, pid)

    @staticmethod
    def __generate_rc(access, secret, pid):
        """Generate rc file for user"""
        rc = open(FLAGS.credentials_template).read()
        rc = rc % {'access': access,
                   'project': pid,
                   'secret': secret,
                   'ec2': FLAGS.ec2_url,
                   's3': 'http://%s:%s' % (FLAGS.s3_host, FLAGS.s3_port),
                   'nova': FLAGS.ca_file,
                   'cert': FLAGS.credential_cert_file,
                   'key': FLAGS.credential_key_file}
        return rc

    def _generate_x509_cert(self, uid, pid):
        """Generate x509 cert for user"""
        (private_key, csr) = crypto.generate_x509_cert(
                self.__cert_subject(uid))
        # TODO(joshua): This should be async call back to the cloud controller
        signed_cert = crypto.sign_csr(csr, pid)
        return (private_key, signed_cert)

    @staticmethod
    def __cert_subject(uid):
        """Helper to generate cert subject"""
        return FLAGS.credential_cert_subject % (uid, utils.isotime())
