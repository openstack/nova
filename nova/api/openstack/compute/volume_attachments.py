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

"""The volume attachments extension."""

from oslo_utils import strutils
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import volume_attachments as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.compute import vm_states
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import volumes_attachments as va_policies
from nova.volume import cinder


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
    if api_version_request.is_supported(req, min_version):
        return

    exc_inv = exception.InstanceInvalidState(
        attr='vm_state',
        instance_uuid=server_id,
        state=server_state,
        method=method)
    common.raise_http_conflict_for_instance_invalid_state(
        exc_inv, method, server_id)


class VolumeAttachmentController(wsgi.Controller):
    """The volume attachment API controller for the OpenStack API.

    A child resource of the server.  Note that we use the volume id
    as the ID of the attachment (though this is not guaranteed externally)

    """

    def __init__(self):
        super().__init__()
        self.compute_api = compute.API()
        self.volume_api = cinder.API()

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.index_query, '2.0', '2.74')
    @validation.query_schema(schema.index_query_v275, '2.75')
    def index(self, req, server_id):
        """Returns the list of volume attachments for a given instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(
            va_policies.POLICY_ROOT % 'index',
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
    @validation.query_schema(schema.show_query)
    def show(self, req, server_id, id):
        """Return data about the given volume attachment."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(
            va_policies.POLICY_ROOT % 'show',
            target={'project_id': instance.project_id})

        volume_id = id

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, volume_id, instance.uuid)
        except exception.VolumeBDMNotFound:
            msg = _(
                "Instance %(instance)s is not attached "
                "to volume %(volume)s"
            ) % {'instance': server_id, 'volume': volume_id}
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
    @validation.schema(schema.create, '2.0', '2.48')
    @validation.schema(schema.create_v249, '2.49', '2.78')
    @validation.schema(schema.create_v279, '2.79')
    def create(self, req, server_id, body):
        """Attach a volume to an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(
            va_policies.POLICY_ROOT % 'create',
            target={'project_id': instance.project_id})

        volume_id = body['volumeAttachment']['volumeId']
        device = body['volumeAttachment'].get('device')
        tag = body['volumeAttachment'].get('tag')
        delete_on_termination = body['volumeAttachment'].get(
            'delete_on_termination', False)

        if instance.vm_state in (
            vm_states.SHELVED, vm_states.SHELVED_OFFLOADED,
        ):
            _check_request_version(
                req, '2.20', 'attach_volume', server_id, instance.vm_state)

        try:
            supports_multiattach = common.supports_multiattach_volume(req)
            device = self.compute_api.attach_volume(
                context, instance, volume_id, device, tag=tag,
                supports_multiattach=supports_multiattach,
                delete_on_termination=delete_on_termination)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.InstanceIsLocked, exception.DevicePathInUse) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'attach_volume', server_id)
        except (
            exception.InvalidVolume,
            exception.InvalidDevicePath,
            exception.InvalidInput,
            exception.VolumeTaggedAttachNotSupported,
            exception.MultiattachNotSupportedOldMicroversion,
            exception.MultiattachToShelvedNotSupported,
        ) as e:
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

        if (
            'migration_status' not in old_volume or
            old_volume['migration_status'] in (None, '')
        ):
            message = (
                f"volume {old_volume_id} is not migrating; this API "
                f"should only be called by Cinder")
            raise exc.HTTPConflict(explanation=message)

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
            self.compute_api.swap_volume(
                context, instance, old_volume, new_volume)
        except exception.VolumeBDMNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (
            exception.InvalidVolume,
            exception.MultiattachSwapVolumeNotSupported,
        ) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'swap_volume', instance.uuid)

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
                raise exc.HTTPBadRequest(
                    explanation='The id property is not mutable')
            if 'serverId' in att and att['serverId'] != instance.uuid:
                raise exc.HTTPBadRequest(
                    explanation='The serverId property is not mutable')
            if 'device' in att and att['device'] != bdm.device_name:
                raise exc.HTTPBadRequest(
                    explanation='The device property is not mutable')
            if 'tag' in att and att['tag'] != bdm.tag:
                raise exc.HTTPBadRequest(
                    explanation='The tag property is not mutable')
            if 'delete_on_termination' in att:
                bdm.delete_on_termination = strutils.bool_from_string(
                    att['delete_on_termination'], strict=True)
            bdm.save()
        except exception.VolumeBDMNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(schema.update, '2.0', '2.84')
    @validation.schema(schema.update_v285, '2.85')
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
        # NOTE(gmann) We pass empty target to policy enforcement. This API
        # is called by cinder which does not have correct project_id where
        # server belongs to. By passing the empty target, we make sure that
        # we do not check the requester project_id and allow users with
        # allowed role to perform the swap volume.
        if only_swap or id != volume_id:
            context.can(va_policies.POLICY_ROOT % 'swap', target={})
        else:
            context.can(
                va_policies.POLICY_ROOT % 'update',
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
        instance = common.get_instance(
            self.compute_api, context, server_id,
            expected_attrs=['device_metadata'])
        context.can(
            va_policies.POLICY_ROOT % 'delete',
            target={'project_id': instance.project_id})

        volume_id = id

        if instance.vm_state in (
            vm_states.SHELVED, vm_states.SHELVED_OFFLOADED
        ):
            _check_request_version(
                req, '2.20', 'detach_volume', server_id, instance.vm_state)
        try:
            volume = self.volume_api.get(context, volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, volume_id, instance.uuid)
        except exception.VolumeBDMNotFound:
            msg = _(
                "Instance %(instance)s is not attached "
                "to volume %(volume)s"
            ) % {'instance': server_id, 'volume': volume_id}
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
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'detach_volume', server_id)
