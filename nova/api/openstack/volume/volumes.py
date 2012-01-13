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

"""The volumes api."""

from webob import exc
import webob

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova import flags
from nova import log as logging
from nova import volume
from nova.volume import volume_types


LOG = logging.getLogger("nova.api.openstack.volume.volumes")


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

    d['snapshotId'] = vol['snapshot_id']
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

    def __init__(self):
        self.volume_api = volume.API()
        super(VolumeController, self).__init__()

    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'volume': _translate_volume_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.delete(context, volume)
        except exception.NotFound:
            raise exc.HTTPNotFound()
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
            raise exc.HTTPUnprocessableEntity()

        volume = body['volume']
        size = volume['size']
        LOG.audit(_("Create volume of %s GB"), size, context=context)

        kwargs = {}

        req_volume_type = volume.get('volume_type', None)
        if req_volume_type:
            try:
                kwargs['volume_type'] = volume_types.get_volume_type_by_name(
                        context, req_volume_type)
            except exception.NotFound:
                raise exc.HTTPNotFound()

        kwargs['metadata'] = volume.get('metadata', None)

        snapshot_id = volume.get('snapshot_id')
        if snapshot_id is not None:
            snapshot = self.volume_api.get_snapshot(context, snapshot_id)
        else:
            snapshot = None

        new_volume = self.volume_api.create(context,
                                            size,
                                            snapshot,
                                            volume.get('display_name'),
                                            volume.get('display_description'),
                                            **kwargs)

        # Work around problem that instance is lazy-loaded...
        new_volume = self.volume_api.get(context, new_volume['id'])

        retval = _translate_volume_detail_view(context, new_volume)

        return {'volume': retval}


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


class VolumeAttachmentSerializer(xmlutil.XMLTemplateSerializer):
    def default(self):
        return VolumeAttachmentTemplate()

    def index(self):
        return VolumeAttachmentsTemplate()


def make_attachment(elem):
    elem.set('id')
    elem.set('serverId')
    elem.set('volumeId')
    elem.set('device')


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

    metadata = xmlutil.make_flat_dict('metadata')
    elem.append(metadata)


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


class VolumeSerializer(xmlutil.XMLTemplateSerializer):
    def default(self):
        return VolumeTemplate()

    def index(self):
        return VolumesTemplate()

    def detail(self):
        return VolumesTemplate()


def create_resource():
    body_serializers = {
        'application/xml': VolumeSerializer(),
        }
    serializer = wsgi.ResponseSerializer(body_serializers)

    deserializer = wsgi.RequestDeserializer()

    return wsgi.Resource(VolumeController(), serializer=serializer)
