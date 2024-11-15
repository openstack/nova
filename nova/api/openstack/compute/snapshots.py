# Copyright 2011 Justin Santa Barbara
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

"""The volume snapshots extension."""

from oslo_utils import strutils
from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import snapshots as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.policies import volumes as vol_policies
from nova.volume import cinder


def _translate_snapshot_detail_view(context, vol):
    """Maps keys for snapshots details view."""
    return _translate_snapshot_summary_view(context, vol)


def _translate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot['id']
    d['volumeId'] = snapshot['volume_id']
    d['status'] = snapshot['status']
    # NOTE(gagupta): We map volume_size as the snapshot size
    d['size'] = snapshot['volume_size']
    d['createdAt'] = snapshot['created_at']
    d['displayName'] = snapshot['display_name']
    d['displayDescription'] = snapshot['display_description']
    return d


@validation.validated
class SnapshotController(wsgi.Controller):
    """The Snapshots API controller for the OpenStack API."""

    def __init__(self):
        super().__init__()
        self.volume_api = cinder.API()

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    @validation.query_schema(schema.show_query)
    @validation.response_body_schema(schema.show_response)
    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'snapshots:show',
            target={'project_id': context.project_id})

        try:
            vol = self.volume_api.get_snapshot(context, id)
        except exception.SnapshotNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'snapshot': _translate_snapshot_detail_view(context, vol)}

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors(404)
    @validation.response_body_schema(schema.delete_response)
    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'snapshots:delete',
            target={'project_id': context.project_id})

        try:
            self.volume_api.delete_snapshot(context, id)
        except exception.SnapshotNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(schema.index_query)
    @validation.response_body_schema(schema.index_response)
    def index(self, req):
        """Returns a summary list of snapshots."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'snapshots:list',
            target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(schema.detail_query)
    @validation.response_body_schema(schema.detail_response)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'snapshots:detail',
            target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['nova.context']

        snapshots = self.volume_api.get_all_snapshots(context)
        limited_list = common.limited(snapshots, req)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403))
    @validation.schema(schema.create)
    @validation.response_body_schema(schema.create_response)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'snapshots:create',
            target={'project_id': context.project_id})

        snapshot = body['snapshot']
        volume_id = snapshot['volume_id']

        force = snapshot.get('force', False)
        force = strutils.bool_from_string(force, strict=True)
        if force:
            create_func = self.volume_api.create_snapshot_force
        else:
            create_func = self.volume_api.create_snapshot

        try:
            new_snapshot = create_func(
                context, volume_id,
                snapshot.get('display_name'),
                snapshot.get('display_description'))
        except exception.OverQuota as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        retval = _translate_snapshot_detail_view(context, new_snapshot)
        return {'snapshot': retval}
