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

"""The security groups extension."""

import urllib
from xml.dom import minidom

from webob import exc
import webob

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger("nova.api.openstack.compute.contrib.security_groups")
FLAGS = flags.FLAGS


def make_rule(elem):
    elem.set('id')
    elem.set('parent_group_id')

    proto = xmlutil.SubTemplateElement(elem, 'ip_protocol')
    proto.text = 'ip_protocol'

    from_port = xmlutil.SubTemplateElement(elem, 'from_port')
    from_port.text = 'from_port'

    to_port = xmlutil.SubTemplateElement(elem, 'to_port')
    to_port.text = 'to_port'

    group = xmlutil.SubTemplateElement(elem, 'group', selector='group')
    name = xmlutil.SubTemplateElement(group, 'name')
    name.text = 'name'
    tenant_id = xmlutil.SubTemplateElement(group, 'tenant_id')
    tenant_id.text = 'tenant_id'

    ip_range = xmlutil.SubTemplateElement(elem, 'ip_range',
                                          selector='ip_range')
    cidr = xmlutil.SubTemplateElement(ip_range, 'cidr')
    cidr.text = 'cidr'


def make_sg(elem):
    elem.set('id')
    elem.set('tenant_id')
    elem.set('name')

    desc = xmlutil.SubTemplateElement(elem, 'description')
    desc.text = 'description'

    rules = xmlutil.SubTemplateElement(elem, 'rules')
    rule = xmlutil.SubTemplateElement(rules, 'rule', selector='rules')
    make_rule(rule)


sg_nsmap = {None: wsgi.XMLNS_V11}


class SecurityGroupRuleTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('security_group_rule',
                                       selector='security_group_rule')
        make_rule(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=sg_nsmap)


class SecurityGroupTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('security_group',
                                       selector='security_group')
        make_sg(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=sg_nsmap)


class SecurityGroupsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('security_groups')
        elem = xmlutil.SubTemplateElement(root, 'security_group',
                                          selector='security_groups')
        make_sg(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=sg_nsmap)


class SecurityGroupXMLDeserializer(wsgi.MetadataXMLDeserializer):
    """
    Deserializer to handle xml-formatted security group requests.
    """
    def default(self, string):
        """Deserialize an xml-formatted security group create request"""
        dom = minidom.parseString(string)
        security_group = {}
        sg_node = self.find_first_child_named(dom,
                                               'security_group')
        if sg_node is not None:
            if sg_node.hasAttribute('name'):
                security_group['name'] = sg_node.getAttribute('name')
            desc_node = self.find_first_child_named(sg_node,
                                                     "description")
            if desc_node:
                security_group['description'] = self.extract_text(desc_node)
        return {'body': {'security_group': security_group}}


class SecurityGroupRulesXMLDeserializer(wsgi.MetadataXMLDeserializer):
    """
    Deserializer to handle xml-formatted security group requests.
    """

    def default(self, string):
        """Deserialize an xml-formatted security group create request"""
        dom = minidom.parseString(string)
        security_group_rule = self._extract_security_group_rule(dom)
        return {'body': {'security_group_rule': security_group_rule}}

    def _extract_security_group_rule(self, node):
        """Marshal the security group rule attribute of a parsed request"""
        sg_rule = {}
        sg_rule_node = self.find_first_child_named(node,
                                                   'security_group_rule')
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

            parent_group_id_node = self.find_first_child_named(sg_rule_node,
                                                            "parent_group_id")
            if parent_group_id_node is not None:
                sg_rule['parent_group_id'] = self.extract_text(
                                                         parent_group_id_node)

            group_id_node = self.find_first_child_named(sg_rule_node,
                                                        "group_id")
            if group_id_node is not None:
                sg_rule['group_id'] = self.extract_text(group_id_node)

            cidr_node = self.find_first_child_named(sg_rule_node, "cidr")
            if cidr_node is not None:
                sg_rule['cidr'] = self.extract_text(cidr_node)

        return sg_rule


class SecurityGroupController(object):
    """The Security group API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        super(SecurityGroupController, self).__init__()

    def _format_security_group_rule(self, context, rule):
        sg_rule = {}
        sg_rule['id'] = rule.id
        sg_rule['parent_group_id'] = rule.parent_group_id
        sg_rule['ip_protocol'] = rule.protocol
        sg_rule['from_port'] = rule.from_port
        sg_rule['to_port'] = rule.to_port
        sg_rule['group'] = {}
        sg_rule['ip_range'] = {}
        if rule.group_id:
            source_group = db.security_group_get(context, rule.group_id)
            sg_rule['group'] = {'name': source_group.name,
                             'tenant_id': source_group.project_id}
        else:
            sg_rule['ip_range'] = {'cidr': rule.cidr}
        return sg_rule

    def _format_security_group(self, context, group):
        security_group = {}
        security_group['id'] = group.id
        security_group['description'] = group.description
        security_group['name'] = group.name
        security_group['tenant_id'] = group.project_id
        security_group['rules'] = []
        for rule in group.rules:
            security_group['rules'] += [self._format_security_group_rule(
                    context, rule)]
        return security_group

    def _get_security_group(self, context, id):
        try:
            id = int(id)
            security_group = db.security_group_get(context, id)
        except ValueError:
            msg = _("Security group id should be integer")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.NotFound as exp:
            raise exc.HTTPNotFound(explanation=unicode(exp))
        return security_group

    @wsgi.serializers(xml=SecurityGroupTemplate)
    def show(self, req, id):
        """Return data about the given security group."""
        context = req.environ['nova.context']
        security_group = self._get_security_group(context, id)
        return {'security_group': self._format_security_group(context,
                                                              security_group)}

    def delete(self, req, id):
        """Delete a security group."""
        context = req.environ['nova.context']
        security_group = self._get_security_group(context, id)
        LOG.audit(_("Delete security group %s"), id, context=context)
        db.security_group_destroy(context, security_group.id)

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SecurityGroupsTemplate)
    def index(self, req):
        """Returns a list of security groups"""
        context = req.environ['nova.context']

        self.compute_api.ensure_default_security_group(context)
        groups = db.security_group_get_by_project(context,
                                                  context.project_id)
        limited_list = common.limited(groups, req)
        result = [self._format_security_group(context, group)
                     for group in limited_list]

        return {'security_groups':
                list(sorted(result,
                            key=lambda k: (k['tenant_id'], k['name'])))}

    @wsgi.serializers(xml=SecurityGroupTemplate)
    @wsgi.deserializers(xml=SecurityGroupXMLDeserializer)
    def create(self, req, body):
        """Creates a new security group."""
        context = req.environ['nova.context']
        if not body:
            raise exc.HTTPUnprocessableEntity()

        security_group = body.get('security_group', None)

        if security_group is None:
            raise exc.HTTPUnprocessableEntity()

        group_name = security_group.get('name', None)
        group_description = security_group.get('description', None)

        self._validate_security_group_property(group_name, "name")
        self._validate_security_group_property(group_description,
                                               "description")
        group_name = group_name.strip()
        group_description = group_description.strip()

        LOG.audit(_("Create Security Group %s"), group_name, context=context)
        self.compute_api.ensure_default_security_group(context)
        if db.security_group_exists(context, context.project_id, group_name):
            msg = _('Security group %s already exists') % group_name
            raise exc.HTTPBadRequest(explanation=msg)

        group = {'user_id': context.user_id,
                 'project_id': context.project_id,
                 'name': group_name,
                 'description': group_description}
        group_ref = db.security_group_create(context, group)

        return {'security_group': self._format_security_group(context,
                                                                 group_ref)}

    def _validate_security_group_property(self, value, typ):
        """ typ will be either 'name' or 'description',
            depending on the caller
        """
        try:
            val = value.strip()
        except AttributeError:
            msg = _("Security group %s is not a string or unicode") % typ
            raise exc.HTTPBadRequest(explanation=msg)
        if not val:
            msg = _("Security group %s cannot be empty.") % typ
            raise exc.HTTPBadRequest(explanation=msg)
        if len(val) > 255:
            msg = _("Security group %s should not be greater "
                            "than 255 characters.") % typ
            raise exc.HTTPBadRequest(explanation=msg)


class SecurityGroupRulesController(SecurityGroupController):

    @wsgi.serializers(xml=SecurityGroupRuleTemplate)
    @wsgi.deserializers(xml=SecurityGroupRulesXMLDeserializer)
    def create(self, req, body):
        context = req.environ['nova.context']

        if not body:
            raise exc.HTTPUnprocessableEntity()

        if not 'security_group_rule' in body:
            raise exc.HTTPUnprocessableEntity()

        self.compute_api.ensure_default_security_group(context)

        sg_rule = body['security_group_rule']
        parent_group_id = sg_rule.get('parent_group_id', None)
        try:
            parent_group_id = int(parent_group_id)
            security_group = db.security_group_get(context, parent_group_id)
        except ValueError:
            msg = _("Parent group id is not integer")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.NotFound as exp:
            msg = _("Security group (%s) not found") % parent_group_id
            raise exc.HTTPNotFound(explanation=msg)

        msg = _("Authorize security group ingress %s")
        LOG.audit(msg, security_group['name'], context=context)

        try:
            values = self._rule_args_to_dict(context,
                              to_port=sg_rule.get('to_port'),
                              from_port=sg_rule.get('from_port'),
                              parent_group_id=sg_rule.get('parent_group_id'),
                              ip_protocol=sg_rule.get('ip_protocol'),
                              cidr=sg_rule.get('cidr'),
                              group_id=sg_rule.get('group_id'))
        except Exception as exp:
            raise exc.HTTPBadRequest(explanation=unicode(exp))

        if values is None:
            msg = _("Not enough parameters to build a "
                                       "valid rule.")
            raise exc.HTTPBadRequest(explanation=msg)

        values['parent_group_id'] = security_group.id

        if self._security_group_rule_exists(security_group, values):
            msg = _('This rule already exists in group %s') % parent_group_id
            raise exc.HTTPBadRequest(explanation=msg)

        security_group_rule = db.security_group_rule_create(context, values)

        self.compute_api.trigger_security_group_rules_refresh(context,
                                    security_group_id=security_group['id'])

        return {"security_group_rule": self._format_security_group_rule(
                                                        context,
                                                        security_group_rule)}

    def _security_group_rule_exists(self, security_group, values):
        """Indicates whether the specified rule values are already
           defined in the given security group.
        """
        for rule in security_group.rules:
            if 'group_id' in values:
                if rule['group_id'] == values['group_id']:
                    return True
            else:
                is_duplicate = True
                for key in ('cidr', 'from_port', 'to_port', 'protocol'):
                    if rule[key] != values[key]:
                        is_duplicate = False
                        break
                if is_duplicate:
                    return True
        return False

    def _rule_args_to_dict(self, context, to_port=None, from_port=None,
                                  parent_group_id=None, ip_protocol=None,
                                  cidr=None, group_id=None):
        values = {}

        if group_id is not None:
            try:
                parent_group_id = int(parent_group_id)
                group_id = int(group_id)
            except ValueError:
                msg = _("Parent or group id is not integer")
                raise exception.InvalidInput(reason=msg)

            if parent_group_id == group_id:
                msg = _("Parent group id and group id cannot be same")
                raise exception.InvalidInput(reason=msg)

            values['group_id'] = group_id
            #check if groupId exists
            db.security_group_get(context, group_id)
        elif cidr:
            # If this fails, it throws an exception. This is what we want.
            try:
                cidr = urllib.unquote(cidr).decode()
            except Exception:
                raise exception.InvalidCidr(cidr=cidr)

            if not utils.is_valid_cidr(cidr):
                # Raise exception for non-valid address
                raise exception.InvalidCidr(cidr=cidr)

            values['cidr'] = cidr
        else:
            values['cidr'] = '0.0.0.0/0'

        if ip_protocol and from_port and to_port:

            ip_protocol = str(ip_protocol)
            try:
                from_port = int(from_port)
                to_port = int(to_port)
            except ValueError:
                if ip_protocol.upper() == 'ICMP':
                    raise exception.InvalidInput(reason="Type and"
                         " Code must be integers for ICMP protocol type")
                else:
                    raise exception.InvalidInput(reason="To and From ports "
                          "must be integers")

            if ip_protocol.upper() not in ['TCP', 'UDP', 'ICMP']:
                raise exception.InvalidIpProtocol(protocol=ip_protocol)

            # Verify that from_port must always be less than
            # or equal to to_port
            if from_port > to_port:
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Former value cannot"
                                            " be greater than the later")

            # Verify valid TCP, UDP port ranges
            if (ip_protocol.upper() in ['TCP', 'UDP'] and
                (from_port < 1 or to_port > 65535)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Valid TCP ports should"
                                           " be between 1-65535")

            # Verify ICMP type and code
            if (ip_protocol.upper() == "ICMP" and
                (from_port < -1 or to_port > 255)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="For ICMP, the"
                                           " type:code must be valid")

            values['protocol'] = ip_protocol
            values['from_port'] = from_port
            values['to_port'] = to_port
        else:
            # If cidr based filtering, protocol and ports are mandatory
            if 'cidr' in values:
                return None

        return values

    def delete(self, req, id):
        context = req.environ['nova.context']

        self.compute_api.ensure_default_security_group(context)
        try:
            id = int(id)
            rule = db.security_group_rule_get(context, id)
        except ValueError:
            msg = _("Rule id is not integer")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.NotFound as exp:
            msg = _("Rule (%s) not found") % id
            raise exc.HTTPNotFound(explanation=msg)

        group_id = rule.parent_group_id
        self.compute_api.ensure_default_security_group(context)
        security_group = db.security_group_get(context, group_id)

        msg = _("Revoke security group ingress %s")
        LOG.audit(msg, security_group['name'], context=context)

        db.security_group_rule_destroy(context, rule['id'])
        self.compute_api.trigger_security_group_rules_refresh(context,
                                    security_group_id=security_group['id'])

        return webob.Response(status_int=202)


class SecurityGroupActionController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SecurityGroupActionController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.action('addSecurityGroup')
    def _addSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']

        try:
            body = body['addSecurityGroup']
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

        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.add_security_group(context, instance, group_name)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=unicode(exp))
        except exception.InstanceNotFound as exp:
            raise exc.HTTPNotFound(explanation=unicode(exp))
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=unicode(exp))

        return webob.Response(status_int=202)

    @wsgi.action('removeSecurityGroup')
    def _removeSecurityGroup(self, req, id, body):
        context = req.environ['nova.context']

        try:
            body = body['removeSecurityGroup']
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

        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.remove_security_group(context, instance,
                                                   group_name)
        except exception.SecurityGroupNotFound as exp:
            raise exc.HTTPNotFound(explanation=unicode(exp))
        except exception.InstanceNotFound as exp:
            raise exc.HTTPNotFound(explanation=unicode(exp))
        except exception.Invalid as exp:
            raise exc.HTTPBadRequest(explanation=unicode(exp))

        return webob.Response(status_int=202)


class Security_groups(extensions.ExtensionDescriptor):
    """Security group support"""

    name = "SecurityGroups"
    alias = "security_groups"
    namespace = "http://docs.openstack.org/compute/ext/securitygroups/api/v1.1"
    updated = "2011-07-21T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = SecurityGroupActionController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-security-groups',
                                controller=SecurityGroupController())

        resources.append(res)

        res = extensions.ResourceExtension('os-security-group-rules',
                                controller=SecurityGroupRulesController())
        resources.append(res)
        return resources
