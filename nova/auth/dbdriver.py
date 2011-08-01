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
Auth driver using the DB as its backend.
"""

import sys

from nova import context
from nova import exception
from nova import db


class DbDriver(object):
    """DB Auth driver

    Defines enter and exit and therefore supports the with/as syntax.
    """

    def __init__(self):
        """Imports the LDAP module"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def get_user(self, uid):
        """Retrieve user by id"""
        user = db.user_get(context.get_admin_context(), uid)
        return self._db_user_to_auth_user(user)

    def get_user_from_access_key(self, access):
        """Retrieve user by access key"""
        user = db.user_get_by_access_key(context.get_admin_context(), access)
        return self._db_user_to_auth_user(user)

    def get_project(self, pid):
        """Retrieve project by id"""
        project = db.project_get(context.get_admin_context(), pid)
        return self._db_project_to_auth_projectuser(project)

    def get_users(self):
        """Retrieve list of users"""
        return [self._db_user_to_auth_user(user)
                for user in db.user_get_all(context.get_admin_context())]

    def get_projects(self, uid=None):
        """Retrieve list of projects"""
        if uid:
            result = db.project_get_by_user(context.get_admin_context(), uid)
        else:
            result = db.project_get_all(context.get_admin_context())
        return [self._db_project_to_auth_projectuser(proj) for proj in result]

    def create_user(self, name, access_key, secret_key, is_admin):
        """Create a user"""
        values = {'id': name,
                  'access_key': access_key,
                  'secret_key': secret_key,
                  'is_admin': is_admin}
        try:
            user_ref = db.user_create(context.get_admin_context(), values)
            return self._db_user_to_auth_user(user_ref)
        except exception.Duplicate, e:
            raise exception.UserExists(user=name)

    def _db_user_to_auth_user(self, user_ref):
        return {'id': user_ref['id'],
                'name': user_ref['id'],
                'access': user_ref['access_key'],
                'secret': user_ref['secret_key'],
                'admin': user_ref['is_admin']}

    def _db_project_to_auth_projectuser(self, project_ref):
        member_ids = [member['id'] for member in project_ref['members']]
        return {'id': project_ref['id'],
                'name': project_ref['name'],
                'project_manager_id': project_ref['project_manager'],
                'description': project_ref['description'],
                'member_ids': member_ids}

    def create_project(self, name, manager_uid,
                       description=None, member_uids=None):
        """Create a project"""
        manager = db.user_get(context.get_admin_context(), manager_uid)
        if not manager:
            raise exception.UserNotFound(user_id=manager_uid)

        # description is a required attribute
        if description is None:
            description = name

        # First, we ensure that all the given users exist before we go
        # on to create the project. This way we won't have to destroy
        # the project again because a user turns out to be invalid.
        members = set([manager])
        if member_uids is not None:
            for member_uid in member_uids:
                member = db.user_get(context.get_admin_context(), member_uid)
                if not member:
                    raise exception.UserNotFound(user_id=member_uid)
                members.add(member)

        values = {'id': name,
                  'name': name,
                  'project_manager': manager['id'],
                  'description': description}

        try:
            project = db.project_create(context.get_admin_context(), values)
        except exception.DBError:
            raise exception.ProjectExists(project=name)

        for member in members:
            db.project_add_member(context.get_admin_context(),
                                  project['id'],
                                  member['id'])

        # This looks silly, but ensures that the members element has been
        # correctly populated
        project_ref = db.project_get(context.get_admin_context(),
                                     project['id'])
        return self._db_project_to_auth_projectuser(project_ref)

    def modify_project(self, project_id, manager_uid=None, description=None):
        """Modify an existing project"""
        if not manager_uid and not description:
            return
        values = {}
        if manager_uid:
            manager = db.user_get(context.get_admin_context(), manager_uid)
            if not manager:
                raise exception.UserNotFound(user_id=manager_uid)
            values['project_manager'] = manager['id']
        if description:
            values['description'] = description

        db.project_update(context.get_admin_context(), project_id, values)
        if not self.is_in_project(manager_uid, project_id):
            self.add_to_project(manager_uid, project_id)

    def add_to_project(self, uid, project_id):
        """Add user to project"""
        user, project = self._validate_user_and_project(uid, project_id)
        db.project_add_member(context.get_admin_context(),
                              project['id'],
                              user['id'])

    def remove_from_project(self, uid, project_id):
        """Remove user from project"""
        user, project = self._validate_user_and_project(uid, project_id)
        db.project_remove_member(context.get_admin_context(),
                                 project['id'],
                                 user['id'])

    def is_in_project(self, uid, project_id):
        """Check if user is in project"""
        user, project = self._validate_user_and_project(uid, project_id)
        return user in project.members

    def has_role(self, uid, role, project_id=None):
        """Check if user has role

        If project is specified, it checks for local role, otherwise it
        checks for global role
        """

        return role in self.get_user_roles(uid, project_id)

    def add_role(self, uid, role, project_id=None):
        """Add role for user (or user and project)"""
        if not project_id:
            db.user_add_role(context.get_admin_context(), uid, role)
            return
        db.user_add_project_role(context.get_admin_context(),
                                 uid, project_id, role)

    def remove_role(self, uid, role, project_id=None):
        """Remove role for user (or user and project)"""
        if not project_id:
            db.user_remove_role(context.get_admin_context(), uid, role)
            return
        db.user_remove_project_role(context.get_admin_context(),
                                    uid, project_id, role)

    def get_user_roles(self, uid, project_id=None):
        """Retrieve list of roles for user (or user and project)"""
        if project_id is None:
            roles = db.user_get_roles(context.get_admin_context(), uid)
            return roles
        else:
            roles = db.user_get_roles_for_project(context.get_admin_context(),
                                                  uid, project_id)
            return roles

    def delete_user(self, id):
        """Delete a user"""
        user = db.user_get(context.get_admin_context(), id)
        db.user_delete(context.get_admin_context(), user['id'])

    def delete_project(self, project_id):
        """Delete a project"""
        db.project_delete(context.get_admin_context(), project_id)

    def modify_user(self, uid, access_key=None, secret_key=None, admin=None):
        """Modify an existing user"""
        if not access_key and not secret_key and admin is None:
            return
        values = {}
        if access_key:
            values['access_key'] = access_key
        if secret_key:
            values['secret_key'] = secret_key
        if admin is not None:
            values['is_admin'] = admin
        db.user_update(context.get_admin_context(), uid, values)

    def _validate_user_and_project(self, user_id, project_id):
        user = db.user_get(context.get_admin_context(), user_id)
        if not user:
            raise exception.UserNotFound(user_id=user_id)
        project = db.project_get(context.get_admin_context(), project_id)
        if not project:
            raise exception.ProjectNotFound(project_id=project_id)
        return user, project
