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
Admin API controller, exposed through http via the api worker.
"""

import base64

def user_dict(user, base64_file=None):
    """ Convert the user object to a result dict """
    if user:
        return {
            'username': user.id,
            'accesskey': user.access,
            'secretkey': user.secret,
            'file': base64_file,
        }
    else:
        return {}

def host_dict(host):
    """ Convert a host model object to a result dict """
    if host:
        return host.state
    else:
        return {}

def admin_only(target):
    """ Decorator for admin-only API calls """
    def wrapper(*args, **kwargs):
        """ Internal wrapper method for admin-only API calls """
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

    def __init__(self, user_manager, host_manager):
        self.user_manager = user_manager
        self.host_manager = host_manager

    def __str__(self):
        return 'AdminController'

    @admin_only
    def describe_user(self, _context, name, **_kwargs):
        """ Returns user data, including access and secret keys. """
        return user_dict(self.user_manager.get_user(name))

    @admin_only
    def describe_users(self, _context, **_kwargs):
        """ Returns all users - should be changed to deal with a list. """
        return {'userSet':
            [user_dict(u) for u in self.user_manager.get_users()] }

    @admin_only
    def register_user(self, _context, name, **_kwargs):
        """ Creates a new user, and returns generated credentials.
        """
        return user_dict(self.user_manager.create_user(name))

    @admin_only
    def deregister_user(self, _context, name, **_kwargs):
        """Deletes a single user (NOT undoable.)
           Should throw an exception if the user has instances,
           volumes, or buckets remaining.
        """
        self.user_manager.delete_user(name)

        return True

    @admin_only
    def generate_x509_for_user(self, _context, name, project=None, **kwargs):
        """Generates and returns an x509 certificate for a single user.
           Is usually called from a client that will wrap this with
           access and secret key info, and return a zip file.
        """
        if project is None:
            project = name
        project = self.user_manager.get_project(project)
        user = self.user_manager.get_user(name)
        return user_dict(user, base64.b64encode(project.get_credentials(user)))

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
        return {'hostSet':
            [host_dict(h) for h in self.host_manager.all()] }

    @admin_only
    def describe_host(self, _context, name, **_kwargs):
        """Returns status info for single node.
        """
        return host_dict(self.host_manager.lookup(name))
