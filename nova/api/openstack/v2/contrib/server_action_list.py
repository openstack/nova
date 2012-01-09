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

from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception


sa_nsmap = {None: wsgi.XMLNS_V11}


class ServerActionsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('actions')
        elem = xmlutil.SubTemplateElement(root, 'action', selector='actions')
        elem.set('created_at')
        elem.set('action')
        elem.set('error')
        return xmlutil.MasterTemplate(root, 1, nsmap=sa_nsmap)


class ServerActionListController(object):
    @wsgi.serializers(xml=ServerActionsTemplate)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        compute_api = compute.API()

        try:
            instance = compute_api.get(context, server_id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound(_("Instance not found"))

        items = compute_api.get_actions(context, instance)

        def _format_item(item):
            return {
                'created_at': str(item['created_at']),
                'action': item['action'],
                'error': item['error'],
            }

        return {'actions': [_format_item(item) for item in items]}


class Server_action_list(extensions.ExtensionDescriptor):
    """Allow Admins to view pending server actions"""

    name = "ServerActionList"
    alias = "os-server-action-list"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "server-actions-list/api/v1.1"
    updated = "2011-12-21T00:00:00+00:00"
    admin_only = True

    def get_resources(self):
        parent_def = {'member_name': 'server', 'collection_name': 'servers'}
        #NOTE(bcwaldon): This should be prefixed with 'os-'
        ext = extensions.ResourceExtension('actions',
                                           ServerActionListController(),
                                           parent=parent_def)
        return [ext]
