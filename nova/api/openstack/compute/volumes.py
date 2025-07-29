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

"""The volumes extension."""

from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import volumes as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.policies import volumes as vol_policies
from nova.volume import cinder


def _translate_volume_detail_view(context, vol):
    """Maps keys for volumes details view."""
    return _translate_volume_summary_view(context, vol)


def _translate_volume_summary_view(context, vol):
    """Maps keys for volumes summary view."""
    d = {}

    d['id'] = vol['id']
    d['status'] = vol['status']
    d['size'] = vol['size']
    d['availabilityZone'] = vol['availability_zone']
    d['createdAt'] = vol['created_at']

    if vol['attach_status'] == 'attached':
        # NOTE(ildikov): The attachments field in the volume info that
        # Cinder sends is converted to an OrderedDict with the
        # instance_uuid as key to make it easier for the multiattach
        # feature to check the required information. Multiattach will
        # be enable in the Nova API in Newton.
        # The format looks like the following:
        # attachments = {'instance_uuid': {
        #                   'attachment_id': 'attachment_uuid',
        #                   'mountpoint': '/dev/sda/
        #                    }
        #                }
        attachment = list(vol['attachments'].items())[0]
        d['attachments'] = [
            {
                'id': vol['id'],
                'volumeId': vol['id'],
                'serverId': attachment[0],
            }
        ]

        mountpoint = attachment[1].get('mountpoint')
        if mountpoint:
            d['attachments'][0]['device'] = mountpoint

    else:
        d['attachments'] = [{}]

    d['displayName'] = vol['display_name']
    d['displayDescription'] = vol['display_description']

    if vol['volume_type_id'] and vol.get('volume_type'):
        d['volumeType'] = vol['volume_type']['name']
    else:
        d['volumeType'] = vol['volume_type_id']

    d['snapshotId'] = vol['snapshot_id']

    if vol.get('volume_metadata'):
        d['metadata'] = vol.get('volume_metadata')
    else:
        d['metadata'] = {}

    return d


class VolumeController(wsgi.Controller):
    """The Volumes API controller for the OpenStack API."""

    def __init__(self):
        super().__init__()
        self.volume_api = cinder.API()

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    @validation.query_schema(schema.show_query)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'show',
            target={'project_id': context.project_id})

        try:
            vol = self.volume_api.get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'volume': _translate_volume_detail_view(context, vol)}

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404))
    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'delete',
            target={'project_id': context.project_id})

        try:
            self.volume_api.delete(context, id)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(schema.index_query)
    def index(self, req):
        """Returns a summary list of volumes."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'list',
            target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_volume_summary_view)

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(schema.detail_query)
    def detail(self, req):
        """Returns a detailed list of volumes."""
        context = req.environ['nova.context']
        context.can(
            vol_policies.POLICY_NAME % 'detail',
            target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_volume_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""
        context = req.environ['nova.context']

        volumes = self.volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(schema.create)
    def create(self, req, body):
        """Creates a new volume."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'create',
                    target={'project_id': context.project_id})

        vol = body['volume']

        vol_type = vol.get('volume_type')
        metadata = vol.get('metadata')
        snapshot_id = vol.get('snapshot_id', None)

        if snapshot_id is not None:
            try:
                snapshot = self.volume_api.get_snapshot(context, snapshot_id)
            except exception.SnapshotNotFound as e:
                raise exc.HTTPNotFound(explanation=e.format_message())
        else:
            snapshot = None

        size = vol.get('size', None)
        if size is None and snapshot is not None:
            size = snapshot['volume_size']

        availability_zone = vol.get('availability_zone')

        try:
            new_volume = self.volume_api.create(
                context,
                size,
                vol.get('display_name'),
                vol.get('display_description'),
                snapshot=snapshot,
                volume_type=vol_type,
                metadata=metadata,
                availability_zone=availability_zone)
        except exception.InvalidInput as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        except exception.OverQuota as err:
            raise exc.HTTPForbidden(explanation=err.format_message())

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        retval = _translate_volume_detail_view(context, dict(new_volume))
        result = {'volume': retval}

        location = '%s/%s' % (req.url, new_volume['id'])

        return wsgi.ResponseObject(result, headers=dict(location=location))
