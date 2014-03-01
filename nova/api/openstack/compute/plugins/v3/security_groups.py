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

import json

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import api as compute_api
from nova import exception
from nova.network.security_group import neutron_driver
from nova.network.security_group import openstack_driver


ALIAS = 'os-security-groups'
ATTRIBUTE_NAME = '%s:security_groups' % ALIAS
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)
softauth = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


def _authorize_context(req):
    context = req.environ['nova.context']
    authorize(context)
    return context


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
                    server[ATTRIBUTE_NAME] = [{"name": group["name"]}
                                              for group in groups]
        else:
            # If method is a POST we get the security groups intended for an
            # instance from the request. The reason for this is if using
            # neutron security groups the requested security groups for the
            # instance are not in the db and have not been sent to neutron yet.
            if req.method != 'POST':
                sg_instance_bindings = (
                    self.security_group_api
                    .get_instances_security_groups_bindings(context,
                                                                servers))
                for server in servers:
                    groups = sg_instance_bindings.get(server['id'])
                    if groups:
                        server[ATTRIBUTE_NAME] = groups

            # In this section of code len(servers) == 1 as you can only POST
            # one server in an API request.
            else:
                # try converting to json
                req_obj = json.loads(req.body)
                # Add security group to server, if no security group was in
                # request add default since that is the group it is part of
                servers[0][ATTRIBUTE_NAME] = req_obj['server'].get(
                    ATTRIBUTE_NAME, [{'name': 'default'}])

    def _show(self, req, resp_obj):
        if not softauth(req.environ['nova.context']):
            return
        if 'server' in resp_obj.obj:
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
        self._extend_servers(req, list(resp_obj.obj['servers']))


class SecurityGroups(extensions.V3APIExtensionBase):
    """Security group support."""
    name = "SecurityGroups"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = SecurityGroupsOutputController()
        output = extensions.ControllerExtension(self, 'servers', controller)
        return [output]

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        security_groups = server_dict.get(ATTRIBUTE_NAME)
        if security_groups is not None:
            create_kwargs['security_group'] = [
                sg['name'] for sg in security_groups if sg.get('name')]
            create_kwargs['security_group'] = list(
                set(create_kwargs['security_group']))


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
