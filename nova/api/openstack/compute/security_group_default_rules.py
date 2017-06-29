# Copyright 2013 Metacloud Inc.
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

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack.compute import security_groups as sg
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova.i18n import _
from nova.network.security_group import openstack_driver
from nova.policies import security_group_default_rules as sgdr_policies


class SecurityGroupDefaultRulesController(sg.SecurityGroupControllerBase,
                                          wsgi.Controller):

    def __init__(self):
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 409, 501))
    def create(self, req, body):
        context = req.environ['nova.context']
        context.can(sgdr_policies.BASE_POLICY_NAME)

        sg_rule = self._from_body(body, 'security_group_default_rule')

        try:
            values = self._rule_args_to_dict(to_port=sg_rule.get('to_port'),
                from_port=sg_rule.get('from_port'),
                ip_protocol=sg_rule.get('ip_protocol'),
                cidr=sg_rule.get('cidr'))
        except (exception.InvalidCidr,
                exception.InvalidInput,
                exception.InvalidIpProtocol,
                exception.InvalidPortRange) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())

        if values is None:
            msg = _('Not enough parameters to build a valid rule.')
            raise exc.HTTPBadRequest(explanation=msg)

        if self.security_group_api.default_rule_exists(context, values):
            msg = _('This default rule already exists.')
            raise exc.HTTPConflict(explanation=msg)
        security_group_rule = self.security_group_api.add_default_rules(
            context, [values])[0]
        fmt_rule = self._format_security_group_default_rule(
                                                        security_group_rule)
        return {'security_group_default_rule': fmt_rule}

    def _rule_args_to_dict(self, to_port=None, from_port=None,
                           ip_protocol=None, cidr=None):
        cidr = self.security_group_api.parse_cidr(cidr)
        return self.security_group_api.new_cidr_ingress_rule(
            cidr, ip_protocol, from_port, to_port)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 404, 501))
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(sgdr_policies.BASE_POLICY_NAME)

        try:
            id = self.security_group_api.validate_id(id)
        except exception.Invalid as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())

        try:
            rule = self.security_group_api.get_default_rule(context, id)
        except exception.SecurityGroupDefaultRuleNotFound as ex:
            raise exc.HTTPNotFound(explanation=ex.format_message())

        fmt_rule = self._format_security_group_default_rule(rule)
        return {"security_group_default_rule": fmt_rule}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 404, 501))
    @wsgi.response(204)
    def delete(self, req, id):
        context = req.environ['nova.context']
        context.can(sgdr_policies.BASE_POLICY_NAME)

        try:
            id = self.security_group_api.validate_id(id)
        except exception.Invalid as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())

        try:
            rule = self.security_group_api.get_default_rule(context, id)
            self.security_group_api.remove_default_rules(context, [rule['id']])
        except exception.SecurityGroupDefaultRuleNotFound as ex:
            raise exc.HTTPNotFound(explanation=ex.format_message())

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    def index(self, req):
        context = req.environ['nova.context']
        context.can(sgdr_policies.BASE_POLICY_NAME)

        ret = {'security_group_default_rules': []}
        try:
            for rule in self.security_group_api.get_all_default_rules(context):
                rule_fmt = self._format_security_group_default_rule(rule)
                ret['security_group_default_rules'].append(rule_fmt)
        except exception.SecurityGroupDefaultRuleNotFound as ex:
            raise exc.HTTPNotFound(explanation=ex.format_message())

        return ret

    def _format_security_group_default_rule(self, rule):
        sg_rule = {}
        sg_rule['id'] = rule['id']
        sg_rule['ip_protocol'] = rule['protocol']
        sg_rule['from_port'] = rule['from_port']
        sg_rule['to_port'] = rule['to_port']
        sg_rule['ip_range'] = {}
        sg_rule['ip_range'] = {'cidr': rule['cidr']}
        return sg_rule
