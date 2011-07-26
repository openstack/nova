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

from nova import exception
from nova import flags
from nova import log as logging

from nova.auth import manager
from nova.api.openstack import faults
from nova.api.openstack import wsgi


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack')


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

    def detail(self, req):
        raise webob.exc.HTTPNotImplemented()

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


def create_resource():
    metadata = {
        "attributes": {
            "account": ["id", "name", "description", "manager"],
        },
    }

    body_serializers = {
        'application/xml': wsgi.XMLDictSerializer(metadata=metadata),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)
    return wsgi.Resource(Controller(), serializer=serializer)
