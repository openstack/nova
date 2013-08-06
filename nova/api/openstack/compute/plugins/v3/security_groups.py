# Copyright 2011 OpenStack Foundation
# Copyright 2012 Justin Santa Barbara
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

"""The security groups extension."""

import contextlib
import json
import webob
from webob import exc
from xml.dom import minidom

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.compute import api as compute_api
from nova import exception
from nova.network.security_group import neutron_driver
from nova.network.security_group import openstack_driver
from nova.openstack.common.gettextutils import _


ALIAS = 'os-security-groups'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)
softauth = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


def _authorize_context(req):
    context = req.environ['nova.context']
    authorize(context)
    return context


@contextlib.contextmanager
def translate_exceptions():
    """Translate nova exceptions to http exceptions."""
    try:
        yield
    except exception.Invalid as exp:
        msg = exp.format_message()
        raise exc.HTTPBadRequest(explanation=msg)
    except exception.SecurityGroupNotFound as exp:
        msg = exp.format_message()
        raise exc.HTTPNotFound(explanation=msg)
    except exception.InstanceNotFound as exp:
        msg = exp.format_message()
        raise exc.HTTPNotFound(explanation=msg)
    except exception.SecurityGroupLimitExceeded as exp:
        msg = exp.format_message()
        raise exc.HTTPRequestEntityTooLarge(explanation=msg)


class SecurityGroupActionController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SecurityGroupActionController, self).__init__(*args, **kwargs)
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())
        self.compute_api = compute.API(
                                   security_group_api=self.security_group_api)

    def _parse(self, body, action):
        try:
            body = body[action]
            group_name = body['name']
        except TypeError:
            msg = _("Missing parameter dict")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Security group not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if not group_name or group_name.strip() == '':
            msg = _("Security group name cannot be empty")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return group_name

    def _invoke(self, method, context, id, group_name):
        with translate_exceptions():
            instance = self.compute_api.get(context, id)
            method(context, instance, group_name)

        return webob.Response(status_int=202)

    @wsgi.action('add_security_group')
    def _add_security_group(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        group_name = self._parse(body, 'add_security_group')

        return self._invoke(self.security_group_api.add_to_instance,
                            context, id, group_name)

    @wsgi.action('remove_security_group')
    def _remove_security_group(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        group_name = self._parse(body, 'remove_security_group')

        return self._invoke(self.security_group_api.remove_from_instance,
                            context, id, group_name)


class SecurityGroupsOutputController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SecurityGroupsOutputController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())

    def _extend_servers(self, req, servers):
        # TODO(arosen) this function should be refactored to reduce duplicate
        # code and use get_instance_security_groups instead of get_db_instance.
        if not len(servers):
            return
        key = "security_groups"
        context = _authorize_context(req)
        if not openstack_driver.is_neutron_security_groups():
            for server in servers:
                instance = req.get_db_instance(server['id'])
                groups = instance.get(key)
                if groups:
                    server[key] = [{"name": group["name"]} for group in groups]
        else:
            # If method is a POST we get the security groups intended for an
            # instance from the request. The reason for this is if using
            # neutron security groups the requested security groups for the
            # instance are not in the db and have not been sent to neutron yet.
            if req.method != 'POST':
                if len(servers) == 1:
                    group = (self.security_group_api
                             .get_instance_security_groups(context,
                                                           servers[0]['id']))
                    if group:
                        servers[0][key] = group
                else:
                    sg_instance_bindings = (
                        self.security_group_api
                        .get_instances_security_groups_bindings(context))
                    for server in servers:
                        groups = sg_instance_bindings.get(server['id'])
                        if groups:
                            server[key] = groups
            # In this section of code len(servers) == 1 as you can only POST
            # one server in an API request.
            else:
                try:
                    # try converting to json
                    req_obj = json.loads(req.body)
                    # Add security group to server, if no security group was in
                    # request add default since that is the group it is part of
                    servers[0][key] = req_obj['server'].get(
                        key, [{'name': 'default'}])
                except ValueError:
                    root = minidom.parseString(req.body)
                    sg_root = root.getElementsByTagName(key)
                    groups = []
                    if sg_root:
                        security_groups = sg_root[0].getElementsByTagName(
                            'security_group')
                        for security_group in security_groups:
                            groups.append(
                                {'name': security_group.getAttribute('name')})
                    if not groups:
                        groups = [{'name': 'default'}]

                    servers[0][key] = groups

    def _show(self, req, resp_obj):
        if not softauth(req.environ['nova.context']):
            return
        if 'server' in resp_obj.obj:
            resp_obj.attach(xml=SecurityGroupServerTemplate())
            self._extend_servers(req, [resp_obj.obj['server']])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        return self._show(req, resp_obj)

    @wsgi.extends
    def create(self, req, resp_obj, body):
        return self._show(req, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        if not softauth(req.environ['nova.context']):
            return
        resp_obj.attach(xml=SecurityGroupServersTemplate())
        self._extend_servers(req, list(resp_obj.obj['servers']))


class SecurityGroupsTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return "security_groups" in datum


def make_server(elem):
    secgrps = SecurityGroupsTemplateElement('security_groups')
    elem.append(secgrps)
    secgrp = xmlutil.SubTemplateElement(secgrps, 'security_group',
                                        selector="security_groups")
    secgrp.set('name')


class SecurityGroupServerTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1)


class SecurityGroupServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1)


class SecurityGroups(extensions.V3APIExtensionBase):
    """Security group support."""
    name = "SecurityGroups"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/securitygroups/api/v3"
    version = 1

    def get_controller_extensions(self):
        controller = SecurityGroupActionController()
        actions = extensions.ControllerExtension(self, 'servers', controller)
        controller = SecurityGroupsOutputController()
        output = extensions.ControllerExtension(self, 'servers', controller)
        return [actions, output]

    def get_resources(self):
        return []


class NativeSecurityGroupExceptions(object):
    @staticmethod
    def raise_invalid_property(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_group_already_exists(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_invalid_group(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_invalid_cidr(cidr, decoding_exception=None):
        raise exception.InvalidCidr(cidr=cidr)

    @staticmethod
    def raise_over_quota(msg):
        raise exception.SecurityGroupLimitExceeded(msg)

    @staticmethod
    def raise_not_found(msg):
        raise exception.SecurityGroupNotFound(msg)


class NativeNovaSecurityGroupAPI(NativeSecurityGroupExceptions,
                                 compute_api.SecurityGroupAPI):
    pass


class NativeNeutronSecurityGroupAPI(NativeSecurityGroupExceptions,
                                    neutron_driver.SecurityGroupAPI):
    pass
