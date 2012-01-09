# Copyright 2011 OpenStack LLC.
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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.auth import manager
from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack.users')


def make_user(elem):
    elem.set('id')
    elem.set('name')
    elem.set('access')
    elem.set('secret')
    elem.set('admin')


class UserTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('user', selector='user')
        make_user(root)
        return xmlutil.MasterTemplate(root, 1)


class UsersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('users')
        elem = xmlutil.SubTemplateElement(root, 'user', selector='users')
        make_user(elem)
        return xmlutil.MasterTemplate(root, 1)


def _translate_keys(user):
    return dict(id=user.id,
                name=user.name,
                access=user.access,
                secret=user.secret,
                admin=user.admin)


class Controller(object):

    def __init__(self):
        self.manager = manager.AuthManager()

    def _check_admin(self, context):
        """We cannot depend on the db layer to check for admin access
           for the auth manager, so we do it here"""
        if not context.is_admin:
            raise exception.AdminRequired()

    @wsgi.serializers(xml=UsersTemplate)
    def index(self, req):
        """Return all users in brief"""
        users = self.manager.get_users()
        users = common.limited(users, req)
        users = [_translate_keys(user) for user in users]
        return dict(users=users)

    @wsgi.serializers(xml=UsersTemplate)
    def detail(self, req):
        """Return all users in detail"""
        return self.index(req)

    @wsgi.serializers(xml=UserTemplate)
    def show(self, req, id):
        """Return data about the given user id"""

        #NOTE(justinsb): The drivers are a little inconsistent in how they
        #  deal with "NotFound" - some throw, some return None.
        try:
            user = self.manager.get_user(id)
        except exception.NotFound:
            user = None

        if user is None:
            raise exc.HTTPNotFound()

        return dict(user=_translate_keys(user))

    def delete(self, req, id):
        self._check_admin(req.environ['nova.context'])
        self.manager.delete_user(id)
        return {}

    @wsgi.serializers(xml=UserTemplate)
    def create(self, req, body):
        self._check_admin(req.environ['nova.context'])
        is_admin = body['user'].get('admin') in ('T', 'True', True)
        name = body['user'].get('name')
        access = body['user'].get('access')
        secret = body['user'].get('secret')
        user = self.manager.create_user(name, access, secret, is_admin)
        return dict(user=_translate_keys(user))

    @wsgi.serializers(xml=UserTemplate)
    def update(self, req, id, body):
        self._check_admin(req.environ['nova.context'])
        is_admin = body['user'].get('admin')
        if is_admin is not None:
            is_admin = is_admin in ('T', 'True', True)
        access = body['user'].get('access')
        secret = body['user'].get('secret')
        self.manager.modify_user(id, access, secret, is_admin)
        return dict(user=_translate_keys(self.manager.get_user(id)))


class Users(extensions.ExtensionDescriptor):
    """Allow admins to acces user information"""

    name = "Users"
    alias = "os-users"
    namespace = "http://docs.openstack.org/compute/ext/users/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"
    admin_only = True

    def get_resources(self):
        coll_actions = {'detail': 'GET'}
        res = extensions.ResourceExtension('users',
                                           Controller(),
                                           collection_actions=coll_actions)

        return [res]
