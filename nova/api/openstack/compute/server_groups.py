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

import collections

from oslo_log import log as logging
import webob
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_groups as schema
from nova.api.openstack import wsgi
from nova.api import validation
import nova.conf
from nova import context as nova_context
import nova.exception
from nova.i18n import _
from nova import objects
from nova.objects import service
from nova.policies import server_groups as sg_policies

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


GROUP_POLICY_OBJ_MICROVERSION = "2.64"


def _authorize_context(req, action):
    context = req.environ['nova.context']
    context.can(sg_policies.POLICY_ROOT % action)
    return context


def _get_not_deleted(context, uuids):
    mappings = objects.InstanceMappingList.get_by_instance_uuids(
        context, uuids)
    inst_by_cell = collections.defaultdict(list)
    cell_mappings = {}
    found_inst_uuids = []

    # Get a master list of cell mappings, and a list of instance
    # uuids organized by cell
    for im in mappings:
        if not im.cell_mapping:
            # Not scheduled yet, so just throw it in the final list
            # and move on
            found_inst_uuids.append(im.instance_uuid)
            continue
        if im.cell_mapping.uuid not in cell_mappings:
            cell_mappings[im.cell_mapping.uuid] = im.cell_mapping
        inst_by_cell[im.cell_mapping.uuid].append(im.instance_uuid)

    # Query each cell for the instances that are inside, building
    # a list of non-deleted instance uuids.
    for cell_uuid, cell_mapping in cell_mappings.items():
        inst_uuids = inst_by_cell[cell_uuid]
        LOG.debug('Querying cell %(cell)s for %(num)i instances',
                  {'cell': cell_mapping.identity, 'num': len(uuids)})
        filters = {'uuid': inst_uuids, 'deleted': False}
        with nova_context.target_cell(context, cell_mapping) as ctx:
            found_inst_uuids.extend([
                inst.uuid for inst in objects.InstanceList.get_by_filters(
                    ctx, filters=filters)])

    return found_inst_uuids


def _should_enable_custom_max_server_rules(context, rules):
    if rules and int(rules.get('max_server_per_host', 1)) > 1:
        minver = service.get_minimum_version_all_cells(
            context, ['nova-compute'])
        if minver < 33:
            return False
    return True


class ServerGroupController(wsgi.Controller):
    """The Server group API controller for the OpenStack API."""

    def _format_server_group(self, context, group, req):
        # the id field has its value as the uuid of the server group
        # There is no 'uuid' key in server_group seen by clients.
        # In addition, clients see policies as a ["policy-name"] list;
        # and they see members as a ["server-id"] list.
        server_group = {}
        server_group['id'] = group.uuid
        server_group['name'] = group.name
        if api_version_request.is_supported(
                req, min_version=GROUP_POLICY_OBJ_MICROVERSION):
            server_group['policy'] = group.policy
            server_group['rules'] = group.rules
        else:
            server_group['policies'] = group.policies or []
            # NOTE(yikun): Before v2.64, a empty metadata is exposed to the
            # user, and it is removed since v2.64.
            server_group['metadata'] = {}
        members = []
        if group.members:
            # Display the instances that are not deleted.
            members = _get_not_deleted(context, group.members)
        server_group['members'] = members
        # Add project id information to the response data for
        # API version v2.13
        if api_version_request.is_supported(req, min_version="2.13"):
            server_group['project_id'] = group.project_id
            server_group['user_id'] = group.user_id
        return server_group

    @wsgi.expected_errors(404)
    def show(self, req, id):
        """Return data about the given server group."""
        context = _authorize_context(req, 'show')
        try:
            sg = objects.InstanceGroup.get_by_uuid(context, id)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return {'server_group': self._format_server_group(context, sg, req)}

    @wsgi.response(204)
    @wsgi.expected_errors(404)
    def delete(self, req, id):
        """Delete a server group."""
        context = _authorize_context(req, 'delete')
        try:
            sg = objects.InstanceGroup.get_by_uuid(context, id)
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        try:
            sg.destroy()
        except nova.exception.InstanceGroupNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.expected_errors(())
    @validation.query_schema(schema.server_groups_query_param_275, '2.75')
    @validation.query_schema(schema.server_groups_query_param, '2.0', '2.74')
    def index(self, req):
        """Returns a list of server groups."""
        context = _authorize_context(req, 'index')
        project_id = context.project_id
        if 'all_projects' in req.GET and context.is_admin:
            sgs = objects.InstanceGroupList.get_all(context)
        else:
            sgs = objects.InstanceGroupList.get_by_project_id(
                    context, project_id)
        limited_list = common.limited(sgs.objects, req)
        result = [self._format_server_group(context, group, req)
                  for group in limited_list]
        return {'server_groups': result}

    @wsgi.Controller.api_version("2.1")
    @wsgi.expected_errors((400, 403, 409))
    @validation.schema(schema.create, "2.0", "2.14")
    @validation.schema(schema.create_v215, "2.15", "2.63")
    @validation.schema(schema.create_v264, GROUP_POLICY_OBJ_MICROVERSION)
    def create(self, req, body):
        """Creates a new server group."""
        context = _authorize_context(req, 'create')

        try:
            objects.Quotas.check_deltas(context, {'server_groups': 1},
                                        context.project_id, context.user_id)
        except nova.exception.OverQuota:
            msg = _("Quota exceeded, too many server groups.")
            raise exc.HTTPForbidden(explanation=msg)

        vals = body['server_group']

        if api_version_request.is_supported(
                req, GROUP_POLICY_OBJ_MICROVERSION):
            policy = vals['policy']
            rules = vals.get('rules', {})
            if policy != 'anti-affinity' and rules:
                msg = _("Only anti-affinity policy supports rules.")
                raise exc.HTTPBadRequest(explanation=msg)
            # NOTE(yikun): This should be removed in Stein version.
            if not _should_enable_custom_max_server_rules(context, rules):
                msg = _("Creating an anti-affinity group with rule "
                        "max_server_per_host > 1 is not yet supported.")
                raise exc.HTTPConflict(explanation=msg)
            sg = objects.InstanceGroup(context, policy=policy,
                                       rules=rules)
        else:
            policies = vals.get('policies')
            sg = objects.InstanceGroup(context, policy=policies[0])
        try:
            sg.name = vals.get('name')
            sg.project_id = context.project_id
            sg.user_id = context.user_id
            sg.create()
        except ValueError as e:
            raise exc.HTTPBadRequest(explanation=e)

        # NOTE(melwitt): We recheck the quota after creating the object to
        # prevent users from allocating more resources than their allowed quota
        # in the event of a race. This is configurable because it can be
        # expensive if strict quota limits are not required in a deployment.
        if CONF.quota.recheck_quota:
            try:
                objects.Quotas.check_deltas(context, {'server_groups': 0},
                                            context.project_id,
                                            context.user_id)
            except nova.exception.OverQuota:
                sg.destroy()
                msg = _("Quota exceeded, too many server groups.")
                raise exc.HTTPForbidden(explanation=msg)

        return {'server_group': self._format_server_group(context, sg, req)}
