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
from oslo_log import log as logging
from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import security_groups as \
                                                  schema_security_groups
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.network.security_group import openstack_driver
from nova.policies import security_groups as sg_policies
from nova.virt import netutils


LOG = logging.getLogger(__name__)
SG_NOT_FOUND = object()


def _authorize_context(req):
    context = req.environ['nova.context']
    context.can(sg_policies.BASE_POLICY_NAME)
    return context


class SecurityGroupControllerBase(object):
    """Base class for Security Group controllers."""

    def __init__(self):
        super(SecurityGroupControllerBase, self).__init__()
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
        if group_rule_data:
            sg_rule['group'] = group_rule_data
        elif rule['group_id']:
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
        else:
            sg_rule['ip_range'] = {'cidr': rule['cidr']}
        return sg_rule

    def _format_security_group(self, context, group,
                               group_rule_data_by_rule_group_id=None):
        security_group = {}
        security_group['id'] = group['id']
        security_group['description'] = group['description']
        security_group['name'] = group['name']
        security_group['tenant_id'] = group['project_id']
        security_group['rules'] = []
        for rule in group['rules']:
            group_rule_data = None
            if rule['group_id'] and group_rule_data_by_rule_group_id:
                group_rule_data = (
                    group_rule_data_by_rule_group_id.get(rule['group_id']))
                if group_rule_data == SG_NOT_FOUND:
                    # The security group for the rule was not found so skip it.
                    continue
            formatted_rule = self._format_security_group_rule(
                context, rule, group_rule_data)
            if formatted_rule:
                security_group['rules'] += [formatted_rule]
        return security_group

    def _get_group_rule_data_by_rule_group_id(self, context, groups):
        group_rule_data_by_rule_group_id = {}
        # Pre-populate with the group information itself in case any of the
        # rule group IDs are the in-scope groups.
        for group in groups:
            group_rule_data_by_rule_group_id[group['id']] = {
                'name': group.get('name'),
                'tenant_id': group.get('project_id')}

        for group in groups:
            for rule in group['rules']:
                rule_group_id = rule['group_id']
                if (rule_group_id and
                        rule_group_id not in group_rule_data_by_rule_group_id):
                    try:
                        source_group = self.security_group_api.get(
                            context, id=rule['group_id'])
                        group_rule_data_by_rule_group_id[rule_group_id] = {
                            'name': source_group.get('name'),
                            'tenant_id': source_group.get('project_id')}
                    except exception.SecurityGroupNotFound:
                        LOG.debug("Security Group %s does not exist",
                                  rule_group_id)
                        # Use a sentinel so we don't process this group again.
                        group_rule_data_by_rule_group_id[rule_group_id] = (
                            SG_NOT_FOUND)
        return group_rule_data_by_rule_group_id

    def _from_body(self, body, key):
        if not body:
            raise exc.HTTPBadRequest(
                explanation=_("The request body can't be empty"))
        value = body.get(key, None)
        if value is None:
            raise exc.HTTPBadRequest(
                explanation=_("Missing parameter %s") % key)
        return value


class SecurityGroupController(SecurityGroupControllerBase, wsgi.Controller):
    """The Security group API controller for the OpenStack API."""

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404))
    def show(self, req, id):
        """Return data about the given security group."""
        context = _authorize_context(req)

        try:
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())

        return {'security_group': self._format_security_group(context,
                                                              security_group)}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404))
    @wsgi.response(202)
    def delete(self, req, id):
        """Delete a security group."""
        context = _authorize_context(req)

        try:
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)
            self.security_group_api.destroy(context, security_group)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(schema_security_groups.index_query)
    @wsgi.expected_errors(404)
    def index(self, req):
        """Returns a list of security groups."""
        context = _authorize_context(req)

        search_opts = {}
        search_opts.update(req.GET)

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

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403))
    def create(self, req, body):
        """Creates a new security group."""
        context = _authorize_context(req)

        security_group = self._from_body(body, 'security_group')

        group_name = security_group.get('name', None)
        group_description = security_group.get('description', None)

        try:
            self.security_group_api.validate_property(group_name, 'name', None)
            self.security_group_api.validate_property(group_description,
                                                      'description', None)
            group_ref = self.security_group_api.create_security_group(
                context, group_name, group_description)
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())
        except exception.SecurityGroupLimitExceeded as exp:
            raise exc.HTTPForbidden(explanation=exp.format_message())

        return {'security_group': self._format_security_group(context,
                                                              group_ref)}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404))
    def update(self, req, id, body):
        """Update a security group."""
        context = _authorize_context(req)

        try:
            id = self.security_group_api.validate_id(id)
            security_group = self.security_group_api.get(context, None, id,
                                                         map_exception=True)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())

        security_group_data = self._from_body(body, 'security_group')
        group_name = security_group_data.get('name', None)
        group_description = security_group_data.get('description', None)

        try:
            self.security_group_api.validate_property(group_name, 'name', None)
            self.security_group_api.validate_property(group_description,
                                                      'description', None)
            group_ref = self.security_group_api.update_security_group(
                context, security_group, group_name, group_description)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())

        return {'security_group': self._format_security_group(context,
                                                              group_ref)}


class SecurityGroupRulesController(SecurityGroupControllerBase,
                                   wsgi.Controller):

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    def create(self, req, body):
        context = _authorize_context(req)

        sg_rule = self._from_body(body, 'security_group_rule')
        group_id = sg_rule.get('group_id')
        source_group = {}

        try:
            parent_group_id = self.security_group_api.validate_id(
                sg_rule.get('parent_group_id'))
            security_group = self.security_group_api.get(context, None,
                                                         parent_group_id,
                                                         map_exception=True)
            if group_id is not None:
                group_id = self.security_group_api.validate_id(group_id)

                source_group = self.security_group_api.get(
                    context, id=group_id)
            new_rule = self._rule_args_to_dict(context,
                              to_port=sg_rule.get('to_port'),
                              from_port=sg_rule.get('from_port'),
                              ip_protocol=sg_rule.get('ip_protocol'),
                              cidr=sg_rule.get('cidr'),
                              group_id=group_id)
        except (exception.Invalid, exception.InvalidCidr) as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())

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
        try:
            if group_id:
                group_rule_data = {'name': source_group.get('name'),
                                   'tenant_id': source_group.get('project_id')}

            security_group_rule = (
                self.security_group_api.create_security_group_rule(
                    context, security_group, new_rule))
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.SecurityGroupLimitExceeded as exp:
            raise exc.HTTPForbidden(explanation=exp.format_message())

        formatted_rule = self._format_security_group_rule(context,
                                                          security_group_rule,
                                                          group_rule_data)
        return {"security_group_rule": formatted_rule}

    def _rule_args_to_dict(self, context, to_port=None, from_port=None,
                           ip_protocol=None, cidr=None, group_id=None):

        if group_id is not None:
            return self.security_group_api.new_group_ingress_rule(
                                    group_id, ip_protocol, from_port, to_port)
        else:
            cidr = self.security_group_api.parse_cidr(cidr)
            return self.security_group_api.new_cidr_ingress_rule(
                                        cidr, ip_protocol, from_port, to_port)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.response(202)
    def delete(self, req, id):
        context = _authorize_context(req)

        try:
            id = self.security_group_api.validate_id(id)
            rule = self.security_group_api.get_rule(context, id)
            group_id = rule['parent_group_id']
            security_group = self.security_group_api.get(context, None,
                                                         group_id,
                                                         map_exception=True)
            self.security_group_api.remove_rules(context, security_group,
                                                 [rule['id']])
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.NoUniqueMatch as exp:
            raise exc.HTTPConflict(explanation=exp.format_message())
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())


class ServerSecurityGroupController(SecurityGroupControllerBase):

    @wsgi.expected_errors(404)
    def index(self, req, server_id):
        """Returns a list of security groups for the given instance."""
        context = _authorize_context(req)

        self.security_group_api.ensure_default(context)

        instance = common.get_instance(self.compute_api, context, server_id)
        try:
            groups = self.security_group_api.get_instance_security_groups(
                context, instance, True)
        except (exception.SecurityGroupNotFound,
                exception.InstanceNotFound) as exp:
            msg = exp.format_message()
            raise exc.HTTPNotFound(explanation=msg)

        # Optimize performance here by loading up the group_rule_data per
        # rule['group_id'] ahead of time so we're not doing redundant
        # security group lookups for each rule.
        group_rule_data_by_rule_group_id = (
            self._get_group_rule_data_by_rule_group_id(context, groups))

        result = [self._format_security_group(context, group,
                                              group_rule_data_by_rule_group_id)
                  for group in groups]

        return {'security_groups':
                list(sorted(result,
                            key=lambda k: (k['tenant_id'], k['name'])))}


class SecurityGroupActionController(wsgi.Controller):
    def __init__(self):
        super(SecurityGroupActionController, self).__init__()
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
            raise exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Security group not specified")
            raise exc.HTTPBadRequest(explanation=msg)

        if not group_name or group_name.strip() == '':
            msg = _("Security group name cannot be empty")
            raise exc.HTTPBadRequest(explanation=msg)

        return group_name

    def _invoke(self, method, context, id, group_name):
        instance = common.get_instance(self.compute_api, context, id)
        method(context, instance, group_name)

    @wsgi.expected_errors((400, 404, 409))
    @wsgi.response(202)
    @wsgi.action('addSecurityGroup')
    def _addSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']
        context.can(sg_policies.BASE_POLICY_NAME)

        group_name = self._parse(body, 'addSecurityGroup')
        try:
            return self._invoke(self.security_group_api.add_to_instance,
                                context, id, group_name)
        except (exception.SecurityGroupNotFound,
                exception.InstanceNotFound) as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.NoUniqueMatch as exp:
            raise exc.HTTPConflict(explanation=exp.format_message())
        except (exception.SecurityGroupCannotBeApplied,
                exception.SecurityGroupExistsForInstance) as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())

    @wsgi.expected_errors((400, 404, 409))
    @wsgi.response(202)
    @wsgi.action('removeSecurityGroup')
    def _removeSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']
        context.can(sg_policies.BASE_POLICY_NAME)

        group_name = self._parse(body, 'removeSecurityGroup')

        try:
            return self._invoke(self.security_group_api.remove_from_instance,
                                context, id, group_name)
        except (exception.SecurityGroupNotFound,
                exception.InstanceNotFound) as exp:
            raise exc.HTTPNotFound(explanation=exp.format_message())
        except exception.NoUniqueMatch as exp:
            raise exc.HTTPConflict(explanation=exp.format_message())
        except exception.SecurityGroupNotExistsForInstance as exp:
            raise exc.HTTPBadRequest(explanation=exp.format_message())
