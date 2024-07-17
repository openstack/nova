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

from oslo_serialization import jsonutils
from oslo_utils import strutils
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import volumes as volumes_schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.compute import vm_states
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import volumes as vol_policies
from nova.policies import volumes_attachments as va_policies
from nova.volume import cinder


def _translate_volume_detail_view(context, vol):
    """Maps keys for volumes details view."""

    d = _translate_volume_summary_view(context, vol)

    # No additional data / lookups at the moment

    return d


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
        super(VolumeController, self).__init__()
        self.volume_api = cinder.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'show',
                    target={'project_id': context.project_id})

        try:
            vol = self.volume_api.get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'volume': _translate_volume_detail_view(context, vol)}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404))
    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'delete',
                    target={'project_id': context.project_id})

        try:
            self.volume_api.delete(context, id)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(volumes_schema.index_query)
    @wsgi.expected_errors(())
    def index(self, req):
        """Returns a summary list of volumes."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'list',
                    target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_volume_summary_view)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(volumes_schema.detail_query)
    @wsgi.expected_errors(())
    def detail(self, req):
        """Returns a detailed list of volumes."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'detail',
                    target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_volume_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""
        context = req.environ['nova.context']

        volumes = self.volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(volumes_schema.create)
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
                availability_zone=availability_zone
                )
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


def _translate_attachment_detail_view(
    bdm,
    show_tag=False,
    show_delete_on_termination=False,
    show_attachment_id_bdm_uuid=False,
):
    """Maps keys for attachment details view.

    :param bdm: BlockDeviceMapping object for an attached volume
    :param show_tag: True if the "tag" field should be in the response, False
        to exclude the "tag" field from the response
    :param show_delete_on_termination: True if the "delete_on_termination"
        field should be in the response, False to exclude the
        "delete_on_termination" field from the response
    :param show_attachment_id_bdm_uuid: True if the "attachment_id" and
        "bdm_uuid" fields should be in the response. Also controls when the
        "id" field is included.
    """

    d = {}

    if not show_attachment_id_bdm_uuid:
        d['id'] = bdm.volume_id

    d['volumeId'] = bdm.volume_id

    d['serverId'] = bdm.instance_uuid

    if bdm.device_name:
        d['device'] = bdm.device_name

    if show_tag:
        d['tag'] = bdm.tag

    if show_delete_on_termination:
        d['delete_on_termination'] = bdm.delete_on_termination

    if show_attachment_id_bdm_uuid:
        d['attachment_id'] = bdm.attachment_id
        d['bdm_uuid'] = bdm.uuid

    return d


def _check_request_version(req, min_version, method, server_id, server_state):
    if not api_version_request.is_supported(req, min_version=min_version):
        exc_inv = exception.InstanceInvalidState(
                attr='vm_state',
                instance_uuid=server_id,
                state=server_state,
                method=method)
        common.raise_http_conflict_for_instance_invalid_state(
                exc_inv,
                method,
                server_id)


class VolumeAttachmentController(wsgi.Controller):
    """The volume attachment API controller for the OpenStack API.

    A child resource of the server.  Note that we use the volume id
    as the ID of the attachment (though this is not guaranteed externally)

    """

    def __init__(self):
        self.compute_api = compute.API()
        self.volume_api = cinder.API()
        super(VolumeAttachmentController, self).__init__()

    @wsgi.expected_errors(404)
    @validation.query_schema(volumes_schema.index_query_275, '2.75')
    @validation.query_schema(volumes_schema.index_query, '2.0', '2.74')
    def index(self, req, server_id):
        """Returns the list of volume attachments for a given instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(va_policies.POLICY_ROOT % 'index',
                    target={'project_id': instance.project_id})

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        limited_list = common.limited(bdms, req)

        results = []
        show_tag = api_version_request.is_supported(req, '2.70')
        show_delete_on_termination = api_version_request.is_supported(
            req, '2.79')
        show_attachment_id_bdm_uuid = api_version_request.is_supported(
            req, '2.89')
        for bdm in limited_list:
            if bdm.volume_id:
                va = _translate_attachment_detail_view(
                    bdm,
                    show_tag=show_tag,
                    show_delete_on_termination=show_delete_on_termination,
                    show_attachment_id_bdm_uuid=show_attachment_id_bdm_uuid,
                )
                results.append(va)

        return {'volumeAttachments': results}

    @wsgi.expected_errors(404)
    def show(self, req, server_id, id):
        """Return data about the given volume attachment."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(va_policies.POLICY_ROOT % 'show',
                    target={'project_id': instance.project_id})

        volume_id = id

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, volume_id, instance.uuid)
        except exception.VolumeBDMNotFound:
            msg = (_("Instance %(instance)s is not attached "
                     "to volume %(volume)s") %
                   {'instance': server_id, 'volume': volume_id})
            raise exc.HTTPNotFound(explanation=msg)

        show_tag = api_version_request.is_supported(req, '2.70')
        show_delete_on_termination = api_version_request.is_supported(
            req, '2.79')
        show_attachment_id_bdm_uuid = api_version_request.is_supported(
            req, '2.89')
        return {
            'volumeAttachment': _translate_attachment_detail_view(
                bdm,
                show_tag=show_tag,
                show_delete_on_termination=show_delete_on_termination,
                show_attachment_id_bdm_uuid=show_attachment_id_bdm_uuid,
            )
        }

    # TODO(mriedem): This API should return a 202 instead of a 200 response.
    @wsgi.expected_errors((400, 403, 404, 409))
    @validation.schema(volumes_schema.create_volume_attachment, '2.0', '2.48')
    @validation.schema(volumes_schema.create_volume_attachment_v249, '2.49',
                       '2.78')
    @validation.schema(volumes_schema.create_volume_attachment_v279, '2.79')
    def create(self, req, server_id, body):
        """Attach a volume to an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(va_policies.POLICY_ROOT % 'create',
                    target={'project_id': instance.project_id})

        volume_id = body['volumeAttachment']['volumeId']
        device = body['volumeAttachment'].get('device')
        tag = body['volumeAttachment'].get('tag')
        delete_on_termination = body['volumeAttachment'].get(
            'delete_on_termination', False)

        if instance.vm_state in (vm_states.SHELVED,
                                 vm_states.SHELVED_OFFLOADED):
            _check_request_version(req, '2.20', 'attach_volume',
                                   server_id, instance.vm_state)

        try:
            supports_multiattach = common.supports_multiattach_volume(req)
            device = self.compute_api.attach_volume(
                context, instance, volume_id, device, tag=tag,
                supports_multiattach=supports_multiattach,
                delete_on_termination=delete_on_termination)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.InstanceIsLocked,
                exception.DevicePathInUse) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'attach_volume', server_id)
        except (exception.InvalidVolume,
                exception.InvalidDevicePath,
                exception.InvalidInput,
                exception.VolumeTaggedAttachNotSupported,
                exception.MultiattachNotSupportedOldMicroversion,
                exception.MultiattachToShelvedNotSupported) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.TooManyDiskDevices as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        # The attach is async
        # NOTE(mriedem): It would be nice to use
        # _translate_attachment_summary_view here but that does not include
        # the 'device' key if device is None or the empty string which would
        # be a backward incompatible change.
        attachment = {}
        attachment['id'] = volume_id
        attachment['serverId'] = server_id
        attachment['volumeId'] = volume_id
        attachment['device'] = device
        if api_version_request.is_supported(req, '2.70'):
            attachment['tag'] = tag
        if api_version_request.is_supported(req, '2.79'):
            attachment['delete_on_termination'] = delete_on_termination
        return {'volumeAttachment': attachment}

    def _update_volume_swap(self, req, instance, id, body):
        context = req.environ['nova.context']
        old_volume_id = id
        try:
            old_volume = self.volume_api.get(context, old_volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        new_volume_id = body['volumeAttachment']['volumeId']
        try:
            new_volume = self.volume_api.get(context, new_volume_id)
        except exception.VolumeNotFound as e:
            # NOTE: This BadRequest is different from the above NotFound even
            # though the same VolumeNotFound exception. This is intentional
            # because new_volume_id is specified in a request body and if a
            # nonexistent resource in the body (not URI) the code should be
            # 400 Bad Request as API-WG guideline. On the other hand,
            # old_volume_id is specified with URI. So it is valid to return
            # NotFound response if that is not existent.
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            self.compute_api.swap_volume(context, instance, old_volume,
                                         new_volume)
        except exception.VolumeBDMNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.InvalidVolume,
                exception.MultiattachSwapVolumeNotSupported) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'swap_volume', instance.uuid)

    def _update_volume_regular(self, req, instance, id, body):
        context = req.environ['nova.context']
        att = body['volumeAttachment']
        # NOTE(danms): We may be doing an update of regular parameters in
        # the midst of a swap operation, so to find the original BDM, we need
        # to use the old volume ID, which is the one in the path.
        volume_id = id

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, volume_id, instance.uuid)

            # NOTE(danms): The attachment id is just the (current) volume id
            if 'id' in att and att['id'] != volume_id:
                raise exc.HTTPBadRequest(explanation='The id property is '
                                         'not mutable')
            if 'serverId' in att and att['serverId'] != instance.uuid:
                raise exc.HTTPBadRequest(explanation='The serverId property '
                                         'is not mutable')
            if 'device' in att and att['device'] != bdm.device_name:
                raise exc.HTTPBadRequest(explanation='The device property is '
                                         'not mutable')
            if 'tag' in att and att['tag'] != bdm.tag:
                raise exc.HTTPBadRequest(explanation='The tag property is '
                                         'not mutable')
            if 'delete_on_termination' in att:
                bdm.delete_on_termination = strutils.bool_from_string(
                        att['delete_on_termination'], strict=True)
            attachment_ref = self.volume_api.attachment_get(context,
                                                            bdm.attachment_id)
            new_connection_info = attachment_ref.get('connection_info', {})
            if 'serial' not in new_connection_info:
                new_connection_info['serial'] = volume_id
            bdm.connection_info = jsonutils.dumps(new_connection_info)
            bdm.save()
        except exception.VolumeBDMNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(volumes_schema.update_volume_attachment, '2.0', '2.84')
    @validation.schema(volumes_schema.update_volume_attachment_v285,
                       min_version='2.85')
    def update(self, req, server_id, id, body):
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        attachment = body['volumeAttachment']
        volume_id = attachment['volumeId']
        only_swap = not api_version_request.is_supported(req, '2.85')

        # NOTE(brinzhang): If the 'volumeId' requested by the user is
        # different from the 'id' in the url path, or only swap is allowed by
        # the microversion, we should check the swap volume policy.
        # otherwise, check the volume update policy.
        if only_swap or id != volume_id:
            context.can(va_policies.POLICY_ROOT % 'swap', target={})
        else:
            context.can(va_policies.POLICY_ROOT % 'update',
                        target={'project_id': instance.project_id})

        if only_swap:
            # NOTE(danms): Original behavior is always call swap on PUT
            self._update_volume_swap(req, instance, id, body)
        else:
            # NOTE(danms): New behavior is update any supported attachment
            # properties first, and then call swap if volumeId differs
            self._update_volume_regular(req, instance, id, body)
            if id != volume_id:
                self._update_volume_swap(req, instance, id, body)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    def delete(self, req, server_id, id):
        """Detach a volume from an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id,
                                       expected_attrs=['device_metadata'])
        context.can(va_policies.POLICY_ROOT % 'delete',
                    target={'project_id': instance.project_id})

        volume_id = id

        if instance.vm_state in (vm_states.SHELVED,
                                 vm_states.SHELVED_OFFLOADED):
            _check_request_version(req, '2.20', 'detach_volume',
                                   server_id, instance.vm_state)
        try:
            volume = self.volume_api.get(context, volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, volume_id, instance.uuid)
        except exception.VolumeBDMNotFound:
            msg = (_("Instance %(instance)s is not attached "
                     "to volume %(volume)s") %
                   {'instance': server_id, 'volume': volume_id})
            raise exc.HTTPNotFound(explanation=msg)

        if bdm.is_root:
            msg = _("Cannot detach a root device volume")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            self.compute_api.detach_volume(context, instance, volume)
        except exception.InvalidVolume as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except (exception.InstanceIsLocked, exception.ServiceUnavailable) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'detach_volume', server_id)


def _translate_snapshot_detail_view(context, vol):
    """Maps keys for snapshots details view."""

    d = _translate_snapshot_summary_view(context, vol)

    # NOTE(gagupta): No additional data / lookups at the moment
    return d


def _translate_snapshot_summary_view(context, vol):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = vol['id']
    d['volumeId'] = vol['volume_id']
    d['status'] = vol['status']
    # NOTE(gagupta): We map volume_size as the snapshot size
    d['size'] = vol['volume_size']
    d['createdAt'] = vol['created_at']
    d['displayName'] = vol['display_name']
    d['displayDescription'] = vol['display_description']
    return d


class SnapshotController(wsgi.Controller):
    """The Snapshots API controller for the OpenStack API."""

    def __init__(self):
        self.volume_api = cinder.API()
        super(SnapshotController, self).__init__()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'snapshots:show',
                    target={'project_id': context.project_id})

        try:
            vol = self.volume_api.get_snapshot(context, id)
        except exception.SnapshotNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'snapshot': _translate_snapshot_detail_view(context, vol)}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors(404)
    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'snapshots:delete',
                    target={'project_id': context.project_id})

        try:
            self.volume_api.delete_snapshot(context, id)
        except exception.SnapshotNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(volumes_schema.index_query)
    @wsgi.expected_errors(())
    def index(self, req):
        """Returns a summary list of snapshots."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'snapshots:list',
                    target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(volumes_schema.detail_query)
    @wsgi.expected_errors(())
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'snapshots:detail',
                    target={'project_id': context.project_id})
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['nova.context']

        snapshots = self.volume_api.get_all_snapshots(context)
        limited_list = common.limited(snapshots, req)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403))
    @validation.schema(volumes_schema.snapshot_create)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        context.can(vol_policies.POLICY_NAME % 'snapshots:create',
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
            new_snapshot = create_func(context, volume_id,
                                       snapshot.get('display_name'),
                                       snapshot.get('display_description'))
        except exception.OverQuota as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        retval = _translate_snapshot_detail_view(context, new_snapshot)
        return {'snapshot': retval}
