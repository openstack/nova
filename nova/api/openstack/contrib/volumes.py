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
import webob

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import volume
from nova.volume import volume_types
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack import servers


LOG = logging.getLogger("nova.api.volumes")


FLAGS = flags.FLAGS


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
        d['attachments'] = [_translate_attachment_detail_view(context, vol)]
    else:
        d['attachments'] = [{}]

    d['displayName'] = vol['display_name']
    d['displayDescription'] = vol['display_description']

    if vol['volume_type_id'] and vol.get('volume_type'):
        d['volumeType'] = vol['volume_type']['name']
    else:
        d['volumeType'] = vol['volume_type_id']

    LOG.audit(_("vol=%s"), vol, context=context)

    if vol.get('volume_metadata'):
        meta_dict = {}
        for i in vol['volume_metadata']:
            meta_dict[i['key']] = i['value']
        d['metadata'] = meta_dict
    else:
        d['metadata'] = {}

    return d


class VolumeController(object):
    """The Volumes API controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "volume": [
                    "id",
                    "status",
                    "size",
                    "availabilityZone",
                    "createdAt",
                    "displayName",
                    "displayDescription",
                    "volumeType",
                    "metadata",
                    ]}}}

    def __init__(self):
        self.volume_api = volume.API()
        super(VolumeController, self).__init__()

    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        return {'volume': _translate_volume_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            self.volume_api.delete(context, volume_id=id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return webob.Response(status_int=202)

    def index(self, req):
        """Returns a summary list of volumes."""
        return self._items(req, entity_maker=_translate_volume_summary_view)

    def detail(self, req):
        """Returns a detailed list of volumes."""
        return self._items(req, entity_maker=_translate_volume_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""
        context = req.environ['nova.context']

        volumes = self.volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    def create(self, req, body):
        """Creates a new volume."""
        context = req.environ['nova.context']

        if not body:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        vol = body['volume']
        size = vol['size']
        LOG.audit(_("Create volume of %s GB"), size, context=context)

        vol_type = vol.get('volume_type', None)
        if vol_type:
            try:
                vol_type = volume_types.get_volume_type_by_name(context,
                                                                vol_type)
            except exception.NotFound:
                return faults.Fault(exc.HTTPNotFound())

        metadata = vol.get('metadata', None)

        new_volume = self.volume_api.create(context, size, None,
                                            vol.get('display_name'),
                                            vol.get('display_description'),
                                            volume_type=vol_type,
                                            metadata=metadata)

        # Work around problem that instance is lazy-loaded...
        new_volume = self.volume_api.get(context, new_volume['id'])

        retval = _translate_volume_detail_view(context, new_volume)

        return {'volume': retval}


def _translate_attachment_detail_view(_context, vol):
    """Maps keys for attachment details view."""

    d = _translate_attachment_summary_view(_context, vol)

    # No additional data / lookups at the moment

    return d


def _translate_attachment_summary_view(_context, vol):
    """Maps keys for attachment summary view."""
    d = {}

    volume_id = vol['id']

    # NOTE(justinsb): We use the volume id as the id of the attachment object
    d['id'] = volume_id

    d['volumeId'] = volume_id
    if vol.get('instance_id'):
        d['serverId'] = vol['instance_id']
    if vol.get('mountpoint'):
        d['device'] = vol['mountpoint']

    return d


class VolumeAttachmentController(object):
    """The volume attachment API controller for the Openstack API.

    A child resource of the server.  Note that we use the volume id
    as the ID of the attachment (though this is not guaranteed externally)

    """

    _serialization_metadata = {
        'application/xml': {
            'attributes': {
                'volumeAttachment': ['id',
                                     'serverId',
                                     'volumeId',
                                     'device']}}}

    def __init__(self):
        self.compute_api = compute.API()
        self.volume_api = volume.API()
        super(VolumeAttachmentController, self).__init__()

    def index(self, req, server_id):
        """Returns the list of volume attachments for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_attachment_summary_view)

    def show(self, req, server_id, id):
        """Return data about the given volume attachment."""
        context = req.environ['nova.context']

        volume_id = id
        try:
            vol = self.volume_api.get(context, volume_id)
        except exception.NotFound:
            LOG.debug("volume_id not found")
            return faults.Fault(exc.HTTPNotFound())

        if str(vol['instance_id']) != server_id:
            LOG.debug("instance_id != server_id")
            return faults.Fault(exc.HTTPNotFound())

        return {'volumeAttachment': _translate_attachment_detail_view(context,
                                                                      vol)}

    def create(self, req, server_id, body):
        """Attach a volume to an instance."""
        context = req.environ['nova.context']

        if not body:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        instance_id = server_id
        volume_id = body['volumeAttachment']['volumeId']
        device = body['volumeAttachment']['device']

        msg = _("Attach volume %(volume_id)s to instance %(server_id)s"
                " at %(device)s") % locals()
        LOG.audit(msg, context=context)

        try:
            self.compute_api.attach_volume(context,
                                           instance_id=instance_id,
                                           volume_id=volume_id,
                                           device=device)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        # The attach is async
        attachment = {}
        attachment['id'] = volume_id
        attachment['volumeId'] = volume_id

        # NOTE(justinsb): And now, we have a problem...
        # The attach is async, so there's a window in which we don't see
        # the attachment (until the attachment completes).  We could also
        # get problems with concurrent requests.  I think we need an
        # attachment state, and to write to the DB here, but that's a bigger
        # change.
        # For now, we'll probably have to rely on libraries being smart

        # TODO(justinsb): How do I return "accepted" here?
        return {'volumeAttachment': attachment}

    def update(self, req, server_id, id, body):
        """Update a volume attachment.  We don't currently support this."""
        return faults.Fault(exc.HTTPBadRequest())

    def delete(self, req, server_id, id):
        """Detach a volume from an instance."""
        context = req.environ['nova.context']

        volume_id = id
        LOG.audit(_("Detach volume %s"), volume_id, context=context)

        try:
            vol = self.volume_api.get(context, volume_id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        if str(vol['instance_id']) != server_id:
            LOG.debug("instance_id != server_id")
            return faults.Fault(exc.HTTPNotFound())

        self.compute_api.detach_volume(context,
                                       volume_id=volume_id)

        return webob.Response(status_int=202)

    def _items(self, req, server_id, entity_maker):
        """Returns a list of attachments, transformed through entity_maker."""
        context = req.environ['nova.context']

        try:
            instance = self.compute_api.get(context, server_id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        volumes = instance['volumes']
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumeAttachments': res}


class BootFromVolumeController(servers.ControllerV11):
    """The boot from volume API controller for the Openstack API."""

    def _create_instance(self, context, instance_type, image_href, **kwargs):
        try:
            return self.compute_api.create(context, instance_type,
                                           image_href, **kwargs)
        except quota.QuotaError as error:
            self.helper._handle_quota_error(error)
        except exception.ImageNotFound as error:
            msg = _("Can not find requested image")
            raise faults.Fault(exc.HTTPBadRequest(explanation=msg))

    def create(self, req, body):
        """ Creates a new server for a given user """
        extra_values = None
        try:

            def get_kwargs(context, instance_type, image_href, **kwargs):
                kwargs['context'] = context
                kwargs['instance_type'] = instance_type
                kwargs['image_href'] = image_href
                return kwargs

            extra_values, kwargs = self.helper.create_instance(req, body,
                                                               get_kwargs)

            block_device_mapping = body['server'].get('block_device_mapping')
            kwargs['block_device_mapping'] = block_device_mapping

            instances = self._create_instance(**kwargs)
        except faults.Fault, f:
            return f

        # We can only return 1 instance via the API, if we happen to
        # build more than one...  instances is a list, so we'll just
        # use the first one..
        inst = instances[0]
        for key in ['instance_type', 'image_ref']:
            inst[key] = extra_values[key]

        server = self._build_view(req, inst, is_detail=True)
        server['server']['adminPass'] = extra_values['password']
        return server


class Volumes(extensions.ExtensionDescriptor):
    def get_name(self):
        return "Volumes"

    def get_alias(self):
        return "os-volumes"

    def get_description(self):
        return "Volumes support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/volumes/api/v1.1"

    def get_updated(self):
        return "2011-03-25T00:00:00+00:00"

    def get_resources(self):
        resources = []

        # NOTE(justinsb): No way to provide singular name ('volume')
        # Does this matter?
        res = extensions.ResourceExtension('os-volumes',
                                        VolumeController(),
                                        collection_actions={'detail': 'GET'})
        resources.append(res)

        res = extensions.ResourceExtension('os-volume_attachments',
                                           VolumeAttachmentController(),
                                           parent=dict(
                                                member_name='server',
                                                collection_name='servers'))
        resources.append(res)

        res = extensions.ResourceExtension('os-volumes_boot',
                                           BootFromVolumeController())
        resources.append(res)

        return resources
