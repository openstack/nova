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
from xml.dom import minidom

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _
from nova.network.security_group import openstack_driver
from nova.virt import netutils


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'security_groups')
softauth = extensions.soft_extension_authorizer('compute', 'security_groups')


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
        raise exc.HTTPForbidden(explanation=msg)
    except exception.NoUniqueMatch as exp:
        msg = exp.format_message()
        raise exc.HTTPConflict(explanation=msg)


class SecurityGroupControllerBase(object):
    """Base class for Security Group controllers."""

    def __init__(self):
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())
        self.compute_api = compute.API(
                                   security_group_api=self.security_group_api)

    def _format_security_group_rule(self, context, rule, group_rule_data=None):
        """Return a security group rule in desired API response format.

        If group_rule_data is passed in that is used rather than querying
        for it.
        """
        sg_rule = {}
        sg_rule['id'] = rule['id']
        sg_rule['parent_group_id'] = rule['parent_group_id']
        sg_rule['ip_protocol'] = rule['protocol']
        sg_rule['from_port'] = rule['from_port']
        sg_rule['to_port'] = rule['to_port']
        sg_rule['group'] = {}
        sg_rule['ip_range'] = {}
        if rule['group_id']:
            with translate_exceptions():
                try:
                    source_group = self.security_group_api.get(
                        context, id=rule['group_id'])
                except exception.SecurityGroupNotFound:
                    # NOTE(arosen): There is a possible race condition that can
                    # occur here if two api calls occur concurrently: one that
                    # lists the security groups and another one that deletes a
                    # security group rule that has a group_id before the
                    # group_id is fetched. To handle this if
                    # SecurityGroupNotFound is raised we return None instead
                    # of the rule and the caller should ignore the rule.
                    LOG.debug("Security Group ID %s does not exist",
                              rule['group_id'])
                    return
            sg_rule['group'] = {'name': source_group.get('name'),
                                'tenant_id': source_group.get('project_id')}
        elif group_rule_data:
            sg_rule['group'] = group_rule_data
        else:
            sg_rule['ip_range'] = {'cidr': rule['cidr']}
        return sg_rule

    def _format_security_group(self, context, group):
        security_group = {}
        security_group['id'] = group['id']
        security_group['description'] = group['description']
        security_group['name'] = group['name']
        security_group['tenant_id'] = group['project_id']
        security_group['rules'] = []
        for rule in group['rules']:
            formatted_rule = self._format_security_group_rule(context, rule)
            if formatted_rule:
                security_group['rules'] += [formatted_rule]
        return security_group

    def _from_body(self, body, key):
        if not body:
            raise exc.HTTPBadRequest(
                explanation=_("The request body can't be empty"))
        value = body.get(key, None)
        if value is None:
            raise exc.HTTPBadRequest(
                explanation=_("Missing parameter %s") % key)
        return value


class SecurityGroupController(SecurityGroupControllerBase):
    """The Security group API controller for the OpenStack API."""

    def show(self, req, id):
        """Return data about the given security group."""
        context = _authorize_context(req)

        with translate_exceptions():
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)

        return {'security_group': self._format_security_group(context,
                                                              security_group)}

    def delete(self, req, id):
        """Delete a security group."""
        context = _authorize_context(req)

        with translate_exceptions():
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)
            self.security_group_api.destroy(context, security_group)

        return webob.Response(status_int=202)

    def index(self, req):
        """Returns a list of security groups."""
        context = _authorize_context(req)

        search_opts = {}
        search_opts.update(req.GET)

        with translate_exceptions():
            project_id = context.project_id
            raw_groups = self.security_group_api.list(context,
                                                      project=project_id,
                                                      search_opts=search_opts)

        limited_list = common.limited(raw_groups, req)
        result = [self._format_security_group(context, group)
                    for group in limited_list]

        return {'security_groups':
                list(sorted(result,
                            key=lambda k: (k['tenant_id'], k['name'])))}

    def create(self, req, body):
        """Creates a new security group."""
        context = _authorize_context(req)

        security_group = self._from_body(body, 'security_group')

        group_name = security_group.get('name', None)
        group_description = security_group.get('description', None)

        with translate_exceptions():
            self.security_group_api.validate_property(group_name, 'name', None)
            self.security_group_api.validate_property(group_description,
                                                      'description', None)
            group_ref = self.security_group_api.create_security_group(
                context, group_name, group_description)

        return {'security_group': self._format_security_group(context,
                                                              group_ref)}

    def update(self, req, id, body):
        """Update a security group."""
        context = _authorize_context(req)

        with translate_exceptions():
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)

        security_group_data = self._from_body(body, 'security_group')
        group_name = security_group_data.get('name', None)
        group_description = security_group_data.get('description', None)

        with translate_exceptions():
            self.security_group_api.validate_property(group_name, 'name', None)
            self.security_group_api.validate_property(group_description,
                                                      'description', None)
            group_ref = self.security_group_api.update_security_group(
                context, security_group, group_name, group_description)

        return {'security_group': self._format_security_group(context,
                                                              group_ref)}


class SecurityGroupRulesController(SecurityGroupControllerBase):

    def create(self, req, body):
        context = _authorize_context(req)

        sg_rule = self._from_body(body, 'security_group_rule')

        with translate_exceptions():
            parent_group_id = self.security_group_api.validate_id(
                sg_rule.get('parent_group_id', None))
            security_group = self.security_group_api.get(context, None,
                                                         parent_group_id,
                                                         map_exception=True)
        try:
            new_rule = self._rule_args_to_dict(context,
                              to_port=sg_rule.get('to_port'),
                              from_port=sg_rule.get('from_port'),
                              ip_protocol=sg_rule.get('ip_protocol'),
                              cidr=sg_rule.get('cidr'),
                              group_id=sg_rule.get('group_id'))
        except exception.SecurityGroupNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except Exception as exp:
            raise exc.HTTPBadRequest(explanation=six.text_type(exp))

        if new_rule is None:
            msg = _("Not enough parameters to build a valid rule.")
            raise exc.HTTPBadRequest(explanation=msg)

        new_rule['parent_group_id'] = security_group['id']

        if 'cidr' in new_rule:
            net, prefixlen = netutils.get_net_and_prefixlen(new_rule['cidr'])
            if net not in ('0.0.0.0', '::') and prefixlen == '0':
                msg = _("Bad prefix for network in cidr %s") % new_rule['cidr']
                raise exc.HTTPBadRequest(explanation=msg)

        group_rule_data = None
        with translate_exceptions():
            if sg_rule.get('group_id'):
                source_group = self.security_group_api.get(
                            context, id=sg_rule['group_id'])
                group_rule_data = {'name': source_group.get('name'),
                                   'tenant_id': source_group.get('project_id')}

            security_group_rule = (
                self.security_group_api.create_security_group_rule(
                    context, security_group, new_rule))

        formatted_rule = self._format_security_group_rule(context,
                                                          security_group_rule,
                                                          group_rule_data)
        return {"security_group_rule": formatted_rule}

    def _rule_args_to_dict(self, context, to_port=None, from_port=None,
                           ip_protocol=None, cidr=None, group_id=None):

        if group_id is not None:
            group_id = self.security_group_api.validate_id(group_id)

            # check if groupId exists
            self.security_group_api.get(context, id=group_id)
            return self.security_group_api.new_group_ingress_rule(
                                    group_id, ip_protocol, from_port, to_port)
        else:
            cidr = self.security_group_api.parse_cidr(cidr)
            return self.security_group_api.new_cidr_ingress_rule(
                                        cidr, ip_protocol, from_port, to_port)

    def delete(self, req, id):
        context = _authorize_context(req)

        with translate_exceptions():
            id = self.security_group_api.validate_id(id)
            rule = self.security_group_api.get_rule(context, id)
            group_id = rule['parent_group_id']
            security_group = self.security_group_api.get(context, None,
                                                         group_id,
                                                         map_exception=True)
            self.security_group_api.remove_rules(context, security_group,
                                                 [rule['id']])

        return webob.Response(status_int=202)


class ServerSecurityGroupController(SecurityGroupControllerBase):

    def index(self, req, server_id):
        """Returns a list of security groups for the given instance."""
        context = _authorize_context(req)

        self.security_group_api.ensure_default(context)

        with translate_exceptions():
            instance = common.get_instance(self.compute_api, context,
                                           server_id)
            groups = self.security_group_api.get_instance_security_groups(
                context, instance, True)

        result = [self._format_security_group(context, group)
                    for group in groups]

        return {'security_groups':
                list(sorted(result,
                            key=lambda k: (k['tenant_id'], k['name'])))}


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
            instance = common.get_instance(self.compute_api, context, id)
            method(context, instance, group_name)

        return webob.Response(status_int=202)

    @wsgi.action('addSecurityGroup')
    def _addSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        group_name = self._parse(body, 'addSecurityGroup')

        return self._invoke(self.security_group_api.add_to_instance,
                            context, id, group_name)

    @wsgi.action('removeSecurityGroup')
    def _removeSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        group_name = self._parse(body, 'removeSecurityGroup')

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
                sg_instance_bindings = (
                        self.security_group_api
                        .get_instances_security_groups_bindings(context,
                                                                servers))
                for server in servers:
                    groups = sg_instance_bindings.get(server['id'])
                    if groups:
                        server[key] = groups

            # In this section of code len(servers) == 1 as you can only POST
            # one server in an API request.
            else:
                try:
                    # try converting to json
                    req_obj = jsonutils.loads(req.body)
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


class Security_groups(extensions.ExtensionDescriptor):
    """Security group support."""
    name = "SecurityGroups"
    alias = "os-security-groups"
    namespace = "http://docs.openstack.org/compute/ext/securitygroups/api/v1.1"
    updated = "2013-05-28T00:00:00Z"

    def get_controller_extensions(self):
        controller = SecurityGroupActionController()
        actions = extensions.ControllerExtension(self, 'servers', controller)
        controller = SecurityGroupsOutputController()
        output = extensions.ControllerExtension(self, 'servers', controller)
        return [actions, output]

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-security-groups',
                                controller=SecurityGroupController())

        resources.append(res)

        res = extensions.ResourceExtension('os-security-group-rules',
                                controller=SecurityGroupRulesController())
        resources.append(res)

        res = extensions.ResourceExtension(
            'os-security-groups',
            controller=ServerSecurityGroupController(),
            parent=dict(member_name='server', collection_name='servers'))
        resources.append(res)

        return resources
