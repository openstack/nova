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
import nova.exception
from nova.i18n import _
from nova.i18n import _LE
from nova import objects
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


SUPPORTED_POLICIES = ['anti-affinity', 'affinity']

authorize = extensions.extension_authorizer('compute', 'server_groups')


def _authorize_context(req):
    context = req.environ['nova.context']
    authorize(context)
    return context


class ServerGroupController(wsgi.Controller):
    """The Server group API controller for the OpenStack API."""

    def __init__(self, ext_mgr):
        self.ext_mgr = ext_mgr

    def _format_server_group(self, context, group):
        # the id field has its value as the uuid of the server group
        # There is no 'uuid' key in server_group seen by clients.
        # In addition, clients see policies as a ["policy-name"] list;
        # and they see members as a ["server-id"] list.
        server_group = {}
        server_group['id'] = group.uuid
        server_group['name'] = group.name
        server_group['policies'] = group.policies or []
        # NOTE(danms): This has been exposed to the user, but never used.
        # Since we can't remove it, just make sure it's always empty.
        server_group['metadata'] = {}
        members = []
        if group.members:
            # Display the instances that are not deleted.
            filters = {'uuid': group.members, 'deleted': False}
            instances = objects.InstanceList.get_by_filters(
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

        # Note(wingwj): It doesn't make sense to store duplicate policies.
        if sorted(set(policies)) != sorted(policies):
            msg = _("Duplicate policies configured!")
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

    def show(self, req, id):
        """Return data about the given server group."""
        context = _authorize_context(req)
        try:
            sg = objects.InstanceGroup.get_by_uuid(context, id)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return {'server_group': self._format_server_group(context, sg)}

    def delete(self, req, id):
        """Delete an server group."""
        context = _authorize_context(req)
        try:
            sg = objects.InstanceGroup.get_by_uuid(context, id)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        quotas = None
        if self.ext_mgr.is_loaded('os-server-group-quotas'):
            quotas = objects.Quotas()
            project_id, user_id = objects.quotas.ids_from_server_group(context,
                                                                       sg)
            try:
                # We have to add the quota back to the user that created
                # the server group
                quotas.reserve(context, project_id=project_id,
                               user_id=user_id, server_groups=-1)
            except Exception:
                quotas = None
                LOG.exception(_LE("Failed to update usages deallocating "
                                  "server group"))

        try:
            sg.destroy()
        except nova.exception.InstanceGroupNotFound as e:
            if quotas:
                quotas.rollback()
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        if quotas:
            quotas.commit()

        return webob.Response(status_int=204)

    def index(self, req):
        """Returns a list of server groups."""
        context = _authorize_context(req)
        project_id = context.project_id
        if 'all_projects' in req.GET and context.is_admin:
            sgs = objects.InstanceGroupList.get_all(context)
        else:
            sgs = objects.InstanceGroupList.get_by_project_id(
                    context, project_id)
        limited_list = common.limited(sgs.objects, req)
        result = [self._format_server_group(context, group)
                  for group in limited_list]
        return {'server_groups': result}

    def create(self, req, body):
        """Creates a new server group."""
        context = _authorize_context(req)

        try:
            self._validate_input_body(body, 'server_group')
        except nova.exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        quotas = None
        if self.ext_mgr.is_loaded('os-server-group-quotas'):
            quotas = objects.Quotas()
            try:
                quotas.reserve(context, project_id=context.project_id,
                               user_id=context.user_id, server_groups=1)
            except nova.exception.OverQuota:
                msg = _("Quota exceeded, too many server groups.")
                raise exc.HTTPForbidden(explanation=msg)

        vals = body['server_group']
        sg = objects.InstanceGroup(context)
        sg.project_id = context.project_id
        sg.user_id = context.user_id
        try:
            sg.name = vals.get('name')
            sg.policies = vals.get('policies')
            sg.create()
        except ValueError as e:
            if quotas:
                quotas.rollback()
            raise exc.HTTPBadRequest(explanation=e)

        if quotas:
            quotas.commit()

        return {'server_group': self._format_server_group(context, sg)}


class Server_groups(extensions.ExtensionDescriptor):
    """Server group support."""
    name = "ServerGroups"
    alias = "os-server-groups"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "servergroups/api/v2")
    updated = "2013-06-20T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-server-groups',
            controller=ServerGroupController(self.ext_mgr),
            member_actions={"action": "POST", })

        resources.append(res)

        return resources
