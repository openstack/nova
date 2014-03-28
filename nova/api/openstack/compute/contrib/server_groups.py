# Copyright (c) 2014 Cisco Systems, Inc.
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

"""The Server Group API Extension."""

import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
import nova.exception
from nova.objects import instance as instance_obj
from nova.objects import instance_group as instance_group_obj
from nova.openstack.common.gettextutils import _
from nova import utils

# NOTE(russellb) There is one other policy, 'legacy', but we don't allow that
# being set via the API.  It's only used when a group gets automatically
# created to support the legacy behavior of the 'group' scheduler hint.
SUPPORTED_POLICIES = ['anti-affinity', 'affinity']

authorize = extensions.extension_authorizer('compute', 'server_groups')


def make_policy(elem):
    elem.text = str


def make_member(elem):
    elem.text = str


def make_group(elem):
    elem.set('name')
    elem.set('id')
    policies = xmlutil.SubTemplateElement(elem, 'policies')
    policy = xmlutil.SubTemplateElement(policies, 'policy',
                                        selector='policies')
    make_policy(policy)
    members = xmlutil.SubTemplateElement(elem, 'members')
    member = xmlutil.SubTemplateElement(members, 'member',
                                        selector='members')
    make_member(member)
    elem.append(common.MetadataTemplate())


server_group_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


def _authorize_context(req):
    context = req.environ['nova.context']
    authorize(context)
    return context


class ServerGroupTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server_group',
                                       selector='server_group')
        make_group(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=server_group_nsmap)


class ServerGroupsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server_groups')
        elem = xmlutil.SubTemplateElement(root, 'server_group',
                                          selector='server_groups')
        # Note: listing server groups only shows name and uuid
        make_group(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=server_group_nsmap)


class ServerGroupXMLDeserializer(wsgi.MetadataXMLDeserializer):
    """Deserializer to handle xml-formatted server group requests."""

    metadata_deserializer = common.MetadataXMLDeserializer()

    def default(self, string):
        """Deserialize an xml-formatted server group create request."""
        dom = xmlutil.safe_minidom_parse_string(string)
        server_group = self._extract_server_group(dom)
        return {'body': {'server_group': server_group}}

    def _extract_server_group(self, node):
        """Marshal the instance attribute of a parsed request."""
        server_group = {}
        sg_node = self.find_first_child_named(node, 'server_group')
        if sg_node is not None:
            if sg_node.hasAttribute('name'):
                server_group['name'] = sg_node.getAttribute('name')

            if sg_node.hasAttribute('id'):
                server_group['id'] = sg_node.getAttribute('id')

            policies = self._extract_policies(sg_node)
            server_group['policies'] = policies or []

        return server_group

    def _extract_policies(self, server_group_node):
        """Marshal the server group policies element of a parsed request."""
        policies_node = self.find_first_child_named(server_group_node,
                                                    'policies')
        if policies_node is not None:
            policy_nodes = self.find_children_named(policies_node,
                                                    'policy')
            policies = []
            if policy_nodes is not None:
                for node in policy_nodes:
                    policies.append(node.firstChild.nodeValue)
            return policies

    def _extract_members(self, server_group_node):
        """Marshal the server group members element of a parsed request."""
        members_node = self.find_first_child_named(server_group_node,
                                                   'members')
        if members_node is not None:
            member_nodes = self.find_children_named(members_node,
                                                    'member')

            members = []
            if member_nodes is not None:
                for node in member_nodes:
                    members.append(node.firstChild.nodeValue)
            return members


class ServerGroupController(wsgi.Controller):
    """The Server group API controller for the OpenStack API."""

    def _format_server_group(self, context, group):
        # the id field has its value as the uuid of the server group
        # There is no 'uuid' key in server_group seen by clients.
        # In addition, clients see policies as a ["policy-name"] list;
        # and they see members as a ["server-id"] list.
        server_group = {}
        server_group['id'] = group.uuid
        server_group['name'] = group.name
        server_group['policies'] = group.policies or []
        server_group['metadata'] = group.metadetails or {}
        members = []
        if group.members:
            # Display the instances that are not deleted.
            filters = {'uuid': group.members, 'deleted_at': None}
            instances = instance_obj.InstanceList.get_by_filters(
                context, filters=filters)
            members = [instance.uuid for instance in instances]
        server_group['members'] = members
        return server_group

    def _validate_policies(self, policies):
        """Validate the policies.

        Validates that there are no contradicting policies, for example
        'anti-affinity' and 'affinity' in the same group.
        Validates that the defined policies are supported.
        :param policies:     the given policies of the server_group
        """
        if ('anti-affinity' in policies and
            'affinity' in policies):
            msg = _("Conflicting policies configured!")
            raise nova.exception.InvalidInput(reason=msg)
        not_supported = [policy for policy in policies
                         if policy not in SUPPORTED_POLICIES]
        if not_supported:
            msg = _("Invalid policies: %s") % ', '.join(not_supported)
            raise nova.exception.InvalidInput(reason=msg)

    def _validate_input_body(self, body, entity_name):
        if not self.is_valid_body(body, entity_name):
            msg = _("the body is invalid.")
            raise nova.exception.InvalidInput(reason=msg)

        subbody = dict(body[entity_name])

        expected_fields = ['name', 'policies']
        for field in expected_fields:
            value = subbody.pop(field, None)
            if not value:
                msg = _("'%s' is either missing or empty.") % field
                raise nova.exception.InvalidInput(reason=msg)
            if field == 'name':
                utils.check_string_length(value, field,
                                          min_length=1, max_length=255)
                if not common.VALID_NAME_REGEX.search(value):
                    msg = _("Invalid format for name: '%s'") % value
                    raise nova.exception.InvalidInput(reason=msg)
            elif field == 'policies':
                if isinstance(value, list):
                    [utils.check_string_length(v, field,
                        min_length=1, max_length=255) for v in value]
                    self._validate_policies(value)
                else:
                    msg = _("'%s' is not a list") % value
                    raise nova.exception.InvalidInput(reason=msg)

        if subbody:
            msg = _("unsupported fields: %s") % subbody.keys()
            raise nova.exception.InvalidInput(reason=msg)

    @wsgi.serializers(xml=ServerGroupTemplate)
    def show(self, req, id):
        """Return data about the given server group."""
        context = _authorize_context(req)
        try:
            sg = instance_group_obj.InstanceGroup.get_by_uuid(context, id)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return {'server_group': self._format_server_group(context, sg)}

    def delete(self, req, id):
        """Delete an server group."""
        context = _authorize_context(req)
        try:
            sg = instance_group_obj.InstanceGroup.get_by_uuid(context, id)
            sg.destroy(context)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=204)

    @wsgi.serializers(xml=ServerGroupsTemplate)
    def index(self, req):
        """Returns a list of server groups."""
        context = _authorize_context(req)
        project_id = context.project_id
        if 'all_projects' in req.GET and context.is_admin:
            sgs = instance_group_obj.InstanceGroupList.get_all(context)
        else:
            sgs = instance_group_obj.InstanceGroupList.get_by_project_id(
                    context, project_id)
        limited_list = common.limited(sgs.objects, req)
        result = [self._format_server_group(context, group)
                  for group in limited_list]
        return {'server_groups': result}

    @wsgi.serializers(xml=ServerGroupTemplate)
    @wsgi.deserializers(xml=ServerGroupXMLDeserializer)
    def create(self, req, body):
        """Creates a new server group."""
        context = _authorize_context(req)

        try:
            self._validate_input_body(body, 'server_group')
        except nova.exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        vals = body['server_group']
        sg = instance_group_obj.InstanceGroup()
        sg.project_id = context.project_id
        sg.user_id = context.user_id
        try:
            sg.name = vals.get('name')
            sg.policies = vals.get('policies')
            sg.create(context)
        except ValueError as e:
            raise exc.HTTPBadRequest(explanation=e)

        return {'server_group': self._format_server_group(context, sg)}


class ServerGroupsTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return "server_groups" in datum


class Server_groups(extensions.ExtensionDescriptor):
    """Server group support."""
    name = "ServerGroups"
    alias = "os-server-groups"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "servergroups/api/v2")
    updated = "2013-06-20T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-server-groups',
            controller=ServerGroupController(),
            member_actions={"action": "POST", })

        resources.append(res)

        return resources
