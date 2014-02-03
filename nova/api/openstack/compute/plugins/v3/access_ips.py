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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import utils

ALIAS = "os-access-ips"
LOG = logging.getLogger(__name__)
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


class AccessIPsController(wsgi.Controller):
    def _extend_server(self, req, server):
            db_instance = req.get_db_instance(server['id'])
            ip_v4 = db_instance.get('access_ip_v4')
            ip_v6 = db_instance.get('access_ip_v6')
            server['%s:access_ip_v4' % ALIAS] = (
                str(ip_v4) if ip_v4 is not None else '')
            server['%s:access_ip_v6' % ALIAS] = (
                str(ip_v6) if ip_v6 is not None else '')

    @wsgi.extends
    def create(self, req, resp_obj, body):
        context = req.environ['nova.context']
        if authorize(context) and 'server' in resp_obj.obj:
            server = resp_obj.obj['server']
            self._extend_server(req, server)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            self._extend_server(req, server)

    @wsgi.extends
    def update(self, req, resp_obj, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            self._extend_server(req, server)

    @wsgi.extends(action='rebuild')
    def rebuild(self, req, resp_obj, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            self._extend_server(req, server)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = resp_obj.obj['servers']
            for server in servers:
                self._extend_server(req, server)


class AccessIPs(extensions.V3APIExtensionBase):
    """Access IPs support."""

    name = "AccessIPs"
    alias = ALIAS
    version = 1
    v4_key = '%s:access_ip_v4' % ALIAS
    v6_key = '%s:access_ip_v6' % ALIAS

    def get_controller_extensions(self):
        controller = AccessIPsController()
        extension = extensions.ControllerExtension(self, 'servers',
                                                   controller)
        return [extension]

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        if AccessIPs.v4_key in server_dict:
            access_ip_v4 = server_dict.get(AccessIPs.v4_key)
            if access_ip_v4:
                self._validate_access_ipv4(access_ip_v4)
                create_kwargs['access_ip_v4'] = access_ip_v4
            else:
                create_kwargs['access_ip_v4'] = None
        if AccessIPs.v6_key in server_dict:
            access_ip_v6 = server_dict.get(AccessIPs.v6_key)
            if access_ip_v6:
                self._validate_access_ipv6(access_ip_v6)
                create_kwargs['access_ip_v6'] = access_ip_v6
            else:
                create_kwargs['access_ip_v6'] = None

    server_update = server_create

    server_rebuild = server_create

    def _validate_access_ipv4(self, address):
        if not utils.is_valid_ipv4(address):
            expl = _('access_ip_v4 is not proper IPv4 format')
            raise exc.HTTPBadRequest(explanation=expl)

    def _validate_access_ipv6(self, address):
        if not utils.is_valid_ipv6(address):
            expl = _('access_ip_v6 is not proper IPv6 format')
            raise exc.HTTPBadRequest(explanation=expl)
