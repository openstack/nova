# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


ALIAS = "os-admin-password"
authorize = extensions.extension_authorizer('compute', 'v3:%s' % ALIAS)


class ChangePasswordDeserializer(wsgi.XMLDeserializer):
    def default(self, string):
        dom = xmlutil.safe_minidom_parse_string(string)
        action_node = dom.childNodes[0]
        action_name = action_node.tagName
        action_data = None
        if action_node.hasAttribute("admin_password"):
            action_data = {'admin_password':
                           action_node.getAttribute("admin_password")}
        return {'body': {action_name: action_data}}


class AdminPasswordController(wsgi.Controller):

    def __init__(self, *args, **kwargs):
        super(AdminPasswordController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.action('change_password')
    @wsgi.response(204)
    @extensions.expected_errors((400, 404, 409, 501))
    @wsgi.deserializers(xml=ChangePasswordDeserializer)
    def change_password(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        if 'admin_password' not in body['change_password']:
            msg = _("No admin_password was specified")
            raise exc.HTTPBadRequest(explanation=msg)
        password = body['change_password']['admin_password']
        if not isinstance(password, basestring):
            msg = _("Invalid admin password")
            raise exc.HTTPBadRequest(explanation=msg)
        try:
            instance = self.compute_api.get(context, id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        try:
            self.compute_api.set_admin_password(context, instance, password)
        except exception.InstancePasswordSetFailed as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as e:
            raise common.raise_http_conflict_for_instance_invalid_state(
                e, 'change_password')
        except NotImplementedError:
            msg = _("Unable to set password on instance")
            raise exc.HTTPNotImplemented(explanation=msg)


class AdminPassword(extensions.V3APIExtensionBase):
    """Admin password management support."""

    name = "AdminPassword"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "os-admin-password/api/v3")
    version = 1

    def get_resources(self):
        return []

    def get_controller_extensions(self):
        controller = AdminPasswordController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
