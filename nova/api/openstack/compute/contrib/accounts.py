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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.auth import manager
from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack.compute.contrib.accounts')


class AccountTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('account', selector='account')
        root.set('id', 'id')
        root.set('name', 'name')
        root.set('description', 'description')
        root.set('manager', 'manager')

        return xmlutil.MasterTemplate(root, 1)


def _translate_keys(account):
    return dict(id=account.id,
                name=account.name,
                description=account.description,
                manager=account.project_manager_id)


class Controller(object):

    def __init__(self):
        self.manager = manager.AuthManager()

    def _check_admin(self, context):
        """We cannot depend on the db layer to check for admin access
           for the auth manager, so we do it here"""
        if not context.is_admin:
            raise exception.AdminRequired()

    def index(self, req):
        raise webob.exc.HTTPNotImplemented()

    @wsgi.serializers(xml=AccountTemplate)
    def show(self, req, id):
        """Return data about the given account id"""
        account = self.manager.get_project(id)
        return dict(account=_translate_keys(account))

    def delete(self, req, id):
        self._check_admin(req.environ['nova.context'])
        self.manager.delete_project(id)
        return {}

    def create(self, req, body):
        """We use update with create-or-update semantics
           because the id comes from an external source"""
        raise webob.exc.HTTPNotImplemented()

    @wsgi.serializers(xml=AccountTemplate)
    def update(self, req, id, body):
        """This is really create or update."""
        self._check_admin(req.environ['nova.context'])
        description = body['account'].get('description')
        manager = body['account'].get('manager')
        try:
            account = self.manager.get_project(id)
            self.manager.modify_project(id, manager, description)
        except exception.NotFound:
            account = self.manager.create_project(id, manager, description)
        return dict(account=_translate_keys(account))


class Accounts(extensions.ExtensionDescriptor):
    """Admin-only access to accounts"""

    name = "Accounts"
    alias = "os-accounts"
    namespace = "http://docs.openstack.org/compute/ext/accounts/api/v1.1"
    updated = "2011-12-23T00:00:00+00:00"
    admin_only = True

    def get_resources(self):
        #TODO(bcwaldon): This should be prefixed with 'os-'
        res = extensions.ResourceExtension('accounts',
                                           Controller())

        return [res]
