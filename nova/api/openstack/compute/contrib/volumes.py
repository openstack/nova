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

import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova import utils
from nova import volume
from nova.volume import volume_types


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
authorize = extensions.extension_authorizer('compute', 'volumes')


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
        d['attachments'] = [_translate_attachment_detail_view(vol['id'],
            vol['instance_uuid'],
            vol['mountpoint'])]
    else:
        d['attachments'] = [{}]

    d['displayName'] = vol['display_name']
    d['displayDescription'] = vol['display_description']

    if vol['volume_type_id'] and vol.get('volume_type'):
        d['volumeType'] = vol['volume_type']['name']
    else:
        d['volumeType'] = vol['volume_type_id']

    d['snapshotId'] = vol['snapshot_id']
    LOG.audit(_("vol=%s"), vol, context=context)

    if vol.get('volume_metadata'):
        metadata = vol.get('volume_metadata')
        d['metadata'] = dict((item['key'], item['value']) for item in metadata)
    else:
        d['metadata'] = {}

    return d


def make_volume(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('availabilityZone')
    elem.set('createdAt')
    elem.set('displayName')
    elem.set('displayDescription')
    elem.set('volumeType')
    elem.set('snapshotId')

    attachments = xmlutil.SubTemplateElement(elem, 'attachments')
    attachment = xmlutil.SubTemplateElement(attachments, 'attachment',
                                            selector='attachments')
    make_attachment(attachment)

    # Attach metadata node
    elem.append(common.MetadataTemplate())


class VolumeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        return xmlutil.MasterTemplate(root, 1)


class VolumesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        return xmlutil.MasterTemplate(root, 1)


class CommonDeserializer(wsgi.MetadataXMLDeserializer):
    """Common deserializer to handle xml-formatted volume requests.

       Handles standard volume attributes as well as the optional metadata
       attribute
    """

    metadata_deserializer = common.MetadataXMLDeserializer()

    def _extract_volume(self, node):
        """Marshal the volume attribute of a parsed request."""
        volume = {}
        volume_node = self.find_first_child_named(node, 'volume')

        attributes = ['display_name', 'display_description', 'size',
                      'volume_type', 'availability_zone']
        for attr in attributes:
            if volume_node.getAttribute(attr):
                volume[attr] = volume_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(volume_node, 'metadata')
        if metadata_node is not None:
            volume['metadata'] = self.extract_metadata(metadata_node)

        return volume


class CreateDeserializer(CommonDeserializer):
    """Deserializer to handle xml-formatted create volume requests.

       Handles standard volume attributes as well as the optional metadata
       attribute
    """

    def default(self, string):
        """Deserialize an xml-formatted volume create request."""
        dom = utils.safe_minidom_parse_string(string)
        volume = self._extract_volume(dom)
        return {'body': {'volume': volume}}


class VolumeController(wsgi.Controller):
    """The Volumes API controller for the OpenStack API."""

    def __init__(self):
        self.volume_api = volume.API()
        super(VolumeController, self).__init__()

    @wsgi.serializers(xml=VolumeTemplate)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'volume': _translate_volume_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['nova.context']
        authorize(context)

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.delete(context, volume)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=VolumesTemplate)
    def index(self, req):
        """Returns a summary list of volumes."""
        return self._items(req, entity_maker=_translate_volume_summary_view)

    @wsgi.serializers(xml=VolumesTemplate)
    def detail(self, req):
        """Returns a detailed list of volumes."""
        return self._items(req, entity_maker=_translate_volume_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""
        context = req.environ['nova.context']
        authorize(context)

        volumes = self.volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    @wsgi.serializers(xml=VolumeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Creates a new volume."""
        context = req.environ['nova.context']
        authorize(context)

        if not self.is_valid_body(body, 'volume'):
            raise exc.HTTPUnprocessableEntity()

        vol = body['volume']

        vol_type = vol.get('volume_type', None)
        if vol_type:
            try:
                vol_type = volume_types.get_volume_type_by_name(context,
                                                                vol_type)
            except exception.NotFound:
                raise exc.HTTPNotFound()

        metadata = vol.get('metadata', None)

        snapshot_id = vol.get('snapshot_id')

        if snapshot_id is not None:
            snapshot = self.volume_api.get_snapshot(context, snapshot_id)
        else:
            snapshot = None

        size = vol.get('size', None)
        if size is None and snapshot is not None:
            size = snapshot['volume_size']

        LOG.audit(_("Create volume of %s GB"), size, context=context)

        availability_zone = vol.get('availability_zone', None)

        new_volume = self.volume_api.create(context,
                                            size,
                                            vol.get('display_name'),
                                            vol.get('display_description'),
                                            snapshot=snapshot,
                                            volume_type=vol_type,
                                            metadata=metadata,
                                            availability_zone=availability_zone
                                           )

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        retval = _translate_volume_detail_view(context, dict(new_volume))
        result = {'volume': retval}

        location = '%s/%s' % (req.url, new_volume['id'])

        return wsgi.ResponseObject(result, headers=dict(location=location))


def _translate_attachment_detail_view(volume_id, instance_uuid, mountpoint):
    """Maps keys for attachment details view."""

    d = _translate_attachment_summary_view(volume_id,
            instance_uuid,
            mountpoint)

    # No additional data / lookups at the moment
    return d


def _translate_attachment_summary_view(volume_id, instance_uuid, mountpoint):
    """Maps keys for attachment summary view."""
    d = {}

    # NOTE(justinsb): We use the volume id as the id of the attachment object
    d['id'] = volume_id

    d['volumeId'] = volume_id

    d['serverId'] = instance_uuid
    if mountpoint:
        d['device'] = mountpoint

    return d


def make_attachment(elem):
    elem.set('id')
    elem.set('serverId')
    elem.set('volumeId')
    elem.set('device')


class VolumeAttachmentTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumeAttachment',
                                       selector='volumeAttachment')
        make_attachment(root)
        return xmlutil.MasterTemplate(root, 1)


class VolumeAttachmentsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumeAttachments')
        elem = xmlutil.SubTemplateElement(root, 'volumeAttachment',
                                          selector='volumeAttachments')
        make_attachment(elem)
        return xmlutil.MasterTemplate(root, 1)


class VolumeAttachmentController(wsgi.Controller):
    """The volume attachment API controller for the OpenStack API.

    A child resource of the server.  Note that we use the volume id
    as the ID of the attachment (though this is not guaranteed externally)

    """

    def __init__(self):
        self.compute_api = compute.API()
        super(VolumeAttachmentController, self).__init__()

    @wsgi.serializers(xml=VolumeAttachmentsTemplate)
    def index(self, req, server_id):
        """Returns the list of volume attachments for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_attachment_summary_view)

    @wsgi.serializers(xml=VolumeAttachmentTemplate)
    def show(self, req, server_id, id):
        """Return data about the given volume attachment."""
        context = req.environ['nova.context']
        authorize(context)

        volume_id = id
        try:
            instance = self.compute_api.get(context, server_id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        bdms = self.compute_api.get_instance_bdms(context, instance)

        if not bdms:
            LOG.debug(_("Instance %s is not attached."), server_id)
            raise exc.HTTPNotFound()

        assigned_mountpoint = None

        for bdm in bdms:
            if bdm['volume_id'] == volume_id:
                assigned_mountpoint = bdm['device_name']
                break

        if assigned_mountpoint is None:
            LOG.debug("volume_id not found")
            raise exc.HTTPNotFound()

        return {'volumeAttachment': _translate_attachment_detail_view(
            volume_id,
            instance['uuid'],
            assigned_mountpoint)}

    @wsgi.serializers(xml=VolumeAttachmentTemplate)
    def create(self, req, server_id, body):
        """Attach a volume to an instance."""
        context = req.environ['nova.context']
        authorize(context)

        if not self.is_valid_body(body, 'volumeAttachment'):
            raise exc.HTTPUnprocessableEntity()

        volume_id = body['volumeAttachment']['volumeId']
        device = body['volumeAttachment'].get('device')

        msg = _("Attach volume %(volume_id)s to instance %(server_id)s"
                " at %(device)s") % locals()
        LOG.audit(msg, context=context)

        try:
            instance = self.compute_api.get(context, server_id)
            device = self.compute_api.attach_volume(context, instance,
                                                    volume_id, device)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        # The attach is async
        attachment = {}
        attachment['id'] = volume_id
        attachment['serverId'] = server_id
        attachment['volumeId'] = volume_id
        attachment['device'] = device

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
        raise exc.HTTPBadRequest()

    def delete(self, req, server_id, id):
        """Detach a volume from an instance."""
        context = req.environ['nova.context']
        authorize(context)

        volume_id = id
        LOG.audit(_("Detach volume %s"), volume_id, context=context)

        try:
            instance = self.compute_api.get(context, server_id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        bdms = self.compute_api.get_instance_bdms(context, instance)

        if not bdms:
            LOG.debug(_("Instance %s is not attached."), server_id)
            raise exc.HTTPNotFound()

        found = False
        for bdm in bdms:
            if bdm['volume_id'] == volume_id:
                self.compute_api.detach_volume(context,
                    volume_id=volume_id)
                found = True
                break

        if not found:
            raise exc.HTTPNotFound()
        else:
            return webob.Response(status_int=202)

    def _items(self, req, server_id, entity_maker):
        """Returns a list of attachments, transformed through entity_maker."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            instance = self.compute_api.get(context, server_id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        bdms = self.compute_api.get_instance_bdms(context, instance)
        limited_list = common.limited(bdms, req)
        results = []

        for bdm in limited_list:
            if bdm['volume_id']:
                results.append(entity_maker(bdm['volume_id'],
                        bdm['instance_uuid'],
                        bdm['device_name']))

        return {'volumeAttachments': results}


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


def make_snapshot(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('createdAt')
    elem.set('displayName')
    elem.set('displayDescription')
    elem.set('volumeId')


class SnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotController(wsgi.Controller):
    """The Volumes API controller for the OpenStack API."""

    def __init__(self):
        self.volume_api = volume.API()
        super(SnapshotController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            vol = self.volume_api.get_snapshot(context, id)
        except exception.NotFound:
            return exc.HTTPNotFound()

        return {'snapshot': _translate_snapshot_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        authorize(context)

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            self.volume_api.delete_snapshot(context, snapshot)
        except exception.NotFound:
            return exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['nova.context']
        authorize(context)

        snapshots = self.volume_api.get_all_snapshots(context)
        limited_list = common.limited(snapshots, req)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    @wsgi.serializers(xml=SnapshotTemplate)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        authorize(context)

        if not self.is_valid_body(body, 'snapshot'):
            raise exc.HTTPUnprocessableEntity()

        snapshot = body['snapshot']
        volume_id = snapshot['volume_id']
        volume = self.volume_api.get(context, volume_id)

        force = snapshot.get('force', False)
        LOG.audit(_("Create snapshot from volume %s"), volume_id,
                context=context)

        if not utils.is_valid_boolstr(force):
            msg = _("Invalid value '%s' for force. ") % force
            raise exception.InvalidParameterValue(err=msg)

        if utils.bool_from_str(force):
            new_snapshot = self.volume_api.create_snapshot_force(context,
                                        volume,
                                        snapshot.get('display_name'),
                                        snapshot.get('display_description'))
        else:
            new_snapshot = self.volume_api.create_snapshot(context,
                                        volume,
                                        snapshot.get('display_name'),
                                        snapshot.get('display_description'))

        retval = _translate_snapshot_detail_view(context, new_snapshot)

        return {'snapshot': retval}


class Volumes(extensions.ExtensionDescriptor):
    """Volumes support"""

    name = "Volumes"
    alias = "os-volumes"
    namespace = "http://docs.openstack.org/compute/ext/volumes/api/v1.1"
    updated = "2011-03-25T00:00:00+00:00"

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
                                           inherits='servers')
        resources.append(res)

        res = extensions.ResourceExtension('os-snapshots',
                                        SnapshotController(),
                                        collection_actions={'detail': 'GET'})
        resources.append(res)

        return resources
