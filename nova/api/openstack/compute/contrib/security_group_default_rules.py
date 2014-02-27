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

import webob
from webob import exc

from nova.api.openstack.compute.contrib import security_groups as sg
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova.network.security_group import openstack_driver
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import xmlutils


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute',
                                            'security_group_default_rules')

sg_nsmap = {None: wsgi.XMLNS_V11}


def make_default_rule(elem):
    elem.set('id')

    proto = xmlutil.SubTemplateElement(elem, 'ip_protocol')
    proto.text = 'ip_protocol'

    from_port = xmlutil.SubTemplateElement(elem, 'from_port')
    from_port.text = 'from_port'

    to_port = xmlutil.SubTemplateElement(elem, 'to_port')
    to_port.text = 'to_port'

    ip_range = xmlutil.SubTemplateElement(elem, 'ip_range',
        selector='ip_range')
    cidr = xmlutil.SubTemplateElement(ip_range, 'cidr')
    cidr.text = 'cidr'


class SecurityGroupDefaultRulesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('security_group_default_rules')
        elem = xmlutil.SubTemplateElement(root, 'security_group_default_rule',
                                    selector='security_group_default_rules')

        make_default_rule(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=sg_nsmap)


class SecurityGroupDefaultRuleTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('security_group_default_rule',
            selector='security_group_default_rule')
        make_default_rule(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=sg_nsmap)


class SecurityGroupDefaultRulesXMLDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = xmlutils.safe_minidom_parse_string(string)
        security_group_rule = self._extract_security_group_default_rule(dom)
        return {'body': {'security_group_default_rule': security_group_rule}}

    def _extract_security_group_default_rule(self, node):
        sg_rule = {}
        sg_rule_node = self.find_first_child_named(node,
            'security_group_default_rule')
        if sg_rule_node is not None:
            ip_protocol_node = self.find_first_child_named(sg_rule_node,
                "ip_protocol")
            if ip_protocol_node is not None:
                sg_rule['ip_protocol'] = self.extract_text(ip_protocol_node)

            from_port_node = self.find_first_child_named(sg_rule_node,
                "from_port")
            if from_port_node is not None:
                sg_rule['from_port'] = self.extract_text(from_port_node)

            to_port_node = self.find_first_child_named(sg_rule_node, "to_port")
            if to_port_node is not None:
                sg_rule['to_port'] = self.extract_text(to_port_node)

            cidr_node = self.find_first_child_named(sg_rule_node, "cidr")
            if cidr_node is not None:
                sg_rule['cidr'] = self.extract_text(cidr_node)

        return sg_rule


class SecurityGroupDefaultRulesController(sg.SecurityGroupControllerBase):

    def __init__(self):
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())

    @wsgi.serializers(xml=SecurityGroupDefaultRuleTemplate)
    @wsgi.deserializers(xml=SecurityGroupDefaultRulesXMLDeserializer)
    def create(self, req, body):
        context = sg._authorize_context(req)
        authorize(context)

        sg_rule = self._from_body(body, 'security_group_default_rule')

        try:
            values = self._rule_args_to_dict(to_port=sg_rule.get('to_port'),
                from_port=sg_rule.get('from_port'),
                ip_protocol=sg_rule.get('ip_protocol'),
                cidr=sg_rule.get('cidr'))
        except Exception as exp:
            raise exc.HTTPBadRequest(explanation=unicode(exp))

        if values is None:
            msg = _('Not enough parameters to build a valid rule.')
            raise exc.HTTPBadRequest(explanation=msg)

        if self.security_group_api.default_rule_exists(context, values):
            msg = _('This default rule already exists.')
            raise exc.HTTPBadRequest(explanation=msg)
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

    @wsgi.serializers(xml=SecurityGroupDefaultRuleTemplate)
    def show(self, req, id):
        context = sg._authorize_context(req)
        authorize(context)

        id = self.security_group_api.validate_id(id)

        LOG.debug(_("Showing security_group_default_rule with id %s") % id)
        try:
            rule = self.security_group_api.get_default_rule(context, id)
        except exception.SecurityGroupDefaultRuleNotFound:
            msg = _("security group default rule not found")
            raise exc.HTTPNotFound(explanation=msg)

        fmt_rule = self._format_security_group_default_rule(rule)
        return {"security_group_default_rule": fmt_rule}

    def delete(self, req, id):
        context = sg._authorize_context(req)
        authorize(context)

        id = self.security_group_api.validate_id(id)

        rule = self.security_group_api.get_default_rule(context, id)

        self.security_group_api.remove_default_rules(context, [rule['id']])

        return webob.Response(status_int=204)

    @wsgi.serializers(xml=SecurityGroupDefaultRulesTemplate)
    def index(self, req):

        context = sg._authorize_context(req)
        authorize(context)

        ret = {'security_group_default_rules': []}
        for rule in self.security_group_api.get_all_default_rules(context):
            rule_fmt = self._format_security_group_default_rule(rule)
            ret['security_group_default_rules'].append(rule_fmt)

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


class Security_group_default_rules(extensions.ExtensionDescriptor):
    """Default rules for security group support."""
    name = "SecurityGroupDefaultRules"
    alias = "os-security-group-default-rules"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "securitygroupdefaultrules/api/v1.1")
    updated = "2013-02-05T00:00:00+00:00"

    def get_resources(self):
        resources = [
            extensions.ResourceExtension('os-security-group-default-rules',
                SecurityGroupDefaultRulesController(),
                collection_actions={'create': 'POST',
                                    'delete': 'DELETE',
                                    'index': 'GET'},
                member_actions={'show': 'GET'})]

        return resources
