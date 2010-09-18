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
Admin API controller, exposed through http via the api worker.
"""

import base64
import uuid
import subprocess
import random

from nova import db
from nova import exception
from nova.auth import manager
from utils import novadir


def user_dict(user, base64_file=None):
    """Convert the user object to a result dict"""
    if user:
        return {
            'username': user.id,
            'accesskey': user.access,
            'secretkey': user.secret,
            'file': base64_file}
    else:
        return {}


def project_dict(project):
    """Convert the project object to a result dict"""
    if project:
        return {
            'projectname': project.id,
            'project_manager_id': project.project_manager_id,
            'description': project.description}
    else:
        return {}


def host_dict(host):
    """Convert a host model object to a result dict"""
    if host:
        # FIXME(vish)
        return host.state
    else:
        return {}


def admin_only(target):
    """Decorator for admin-only API calls"""
    def wrapper(*args, **kwargs):
        """Internal wrapper method for admin-only API calls"""
        context = args[1]
        if context.user.is_admin():
            return target(*args, **kwargs)
        else:
            return {}

    return wrapper


class AdminController(object):
    """
    API Controller for users, hosts, nodes, and workers.
    Trivial admin_only wrapper will be replaced with RBAC,
    allowing project managers to administer project users.
    """

    def __str__(self):
        return 'AdminController'

    @admin_only
    def describe_user(self, _context, name, **_kwargs):
        """Returns user data, including access and secret keys."""
        return user_dict(manager.AuthManager().get_user(name))

    @admin_only
    def describe_users(self, _context, **_kwargs):
        """Returns all users - should be changed to deal with a list."""
        return {'userSet':
            [user_dict(u) for u in manager.AuthManager().get_users()] }

    @admin_only
    def register_user(self, _context, name, **_kwargs):
        """Creates a new user, and returns generated credentials."""
        return user_dict(manager.AuthManager().create_user(name))

    @admin_only
    def deregister_user(self, _context, name, **_kwargs):
        """Deletes a single user (NOT undoable.)
           Should throw an exception if the user has instances,
           volumes, or buckets remaining.
        """
        manager.AuthManager().delete_user(name)

        return True

    @admin_only
    def describe_roles(self, context, project_roles=True, **kwargs):
        """Returns a list of allowed roles."""
        roles = manager.AuthManager().get_roles(project_roles)
        return { 'roles': [{'role': r} for r in roles]}

    @admin_only
    def describe_user_roles(self, context, user, project=None, **kwargs):
        """Returns a list of roles for the given user.
           Omitting project will return any global roles that the user has.
           Specifying project will return only project specific roles.
        """
        roles = manager.AuthManager().get_user_roles(user, project=project)
        return { 'roles': [{'role': r} for r in roles]}

    @admin_only
    def modify_user_role(self, context, user, role, project=None,
                         operation='add', **kwargs):
        """Add or remove a role for a user and project."""
        if operation == 'add':
            manager.AuthManager().add_role(user, role, project)
        elif operation == 'remove':
            manager.AuthManager().remove_role(user, role, project)
        else:
            raise exception.ApiError('operation must be add or remove')

        return True

    @admin_only
    def generate_x509_for_user(self, _context, name, project=None, **kwargs):
        """Generates and returns an x509 certificate for a single user.
           Is usually called from a client that will wrap this with
           access and secret key info, and return a zip file.
        """
        if project is None:
            project = name
        project = manager.AuthManager().get_project(project)
        user = manager.AuthManager().get_user(name)
        return user_dict(user, base64.b64encode(project.get_credentials(user)))

    @admin_only
    def describe_project(self, context, name, **kwargs):
        """Returns project data, including member ids."""
        return project_dict(manager.AuthManager().get_project(name))

    @admin_only
    def describe_projects(self, context, user=None, **kwargs):
        """Returns all projects - should be changed to deal with a list."""
        return {'projectSet':
            [project_dict(u) for u in
            manager.AuthManager().get_projects(user=user)]}

    @admin_only
    def register_project(self, context, name, manager_user, description=None,
                         member_users=None, **kwargs):
        """Creates a new project"""
        return project_dict(
            manager.AuthManager().create_project(
                name,
                manager_user,
                description=None,
                member_users=None))

    @admin_only
    def deregister_project(self, context, name):
        """Permanently deletes a project."""
        manager.AuthManager().delete_project(name)
        return True

    @admin_only
    def describe_project_members(self, context, name, **kwargs):
        project = manager.AuthManager().get_project(name)
        result = {
            'members': [{'member': m} for m in project.member_ids]}
        return result

    @admin_only
    def modify_project_member(self, context, user, project, operation, **kwargs):
        """Add or remove a user from a project."""
        if operation =='add':
            manager.AuthManager().add_to_project(user, project)
        elif operation == 'remove':
            manager.AuthManager().remove_from_project(user, project)
        else:
            raise exception.ApiError('operation must be add or remove')
        return True

    @admin_only
    def describe_hosts(self, _context, **_kwargs):
        """Returns status info for all nodes. Includes:
            * Disk Space
            * Instance List
            * RAM used
            * CPU used
            * DHCP servers running
            * Iptables / bridges
        """
        return {'hostSet': [host_dict(h) for h in db.host_get_all()]}

    @admin_only
    def describe_host(self, _context, name, **_kwargs):
        """Returns status info for single node."""
        return host_dict(db.host_get(name))

    @admin_only
    def create_console(self, _context, kind, instance_id, **_kwargs):
        """Create a Console"""
        #instance = db.instance_get(_context, instance_id)
        host = '127.0.0.1'

        def get_port():
            for i in range(0,100): # don't loop forever
                port = int(random.uniform(10000, 12000))
                cmd = "netcat 0.0.0.0 " + str(port) + " -w 2  < /dev/null"
                # this Popen  will exit with 0 only if the port is in use, 
                # so a nonzero return value implies it is unused
                port_is_unused = subprocess.Popen(cmd, shell=True).wait()
                if port_is_unused:
                    return port
            raise 'Unable to find an open port'

        port = str(get_port())
        token = str(uuid.uuid4())
        cmd = novadir() + "tools/ajaxterm//ajaxterm.py --command 'ssh root@" + host + "' -t " \
                + token + " -p " + port
        port_is_unused = subprocess.Popen(cmd, shell=True)
        return {'url': 'http://tonbuntu:' + port + '/?token=' + token }

