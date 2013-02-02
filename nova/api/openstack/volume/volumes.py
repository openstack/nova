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

import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova import utils
from nova import volume
from nova.volume import volume_types


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


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

    d['volume_id'] = volume_id
    d['server_id'] = vol['instance_uuid']
    if vol.get('mountpoint'):
        d['device'] = vol['mountpoint']

    return d


def _translate_volume_detail_view(context, vol, image_id=None):
    """Maps keys for volumes details view."""

    d = _translate_volume_summary_view(context, vol, image_id)

    # No additional data / lookups at the moment

    return d


def _translate_volume_summary_view(context, vol, image_id=None):
    """Maps keys for volumes summary view."""
    d = {}

    d['id'] = vol['id']
    d['status'] = vol['status']
    d['size'] = vol['size']
    d['availability_zone'] = vol['availability_zone']
    d['created_at'] = vol['created_at']

    d['attachments'] = []
    if vol['attach_status'] == 'attached':
        attachment = _translate_attachment_detail_view(context, vol)
        d['attachments'].append(attachment)

    d['display_name'] = vol['display_name']
    d['display_description'] = vol['display_description']

    if vol['volume_type_id'] and vol.get('volume_type'):
        d['volume_type'] = vol['volume_type']['name']
    else:
        # TODO(bcwaldon): remove str cast once we use uuids
        d['volume_type'] = str(vol['volume_type_id'])

    d['snapshot_id'] = vol['snapshot_id']

    if image_id:
        d['image_id'] = image_id

    LOG.audit(_("vol=%s"), vol, context=context)

    if vol.get('volume_metadata'):
        metadata = vol.get('volume_metadata')
        d['metadata'] = dict((item['key'], item['value']) for item in metadata)
    else:
        d['metadata'] = {}

    return d


def make_attachment(elem):
    elem.set('id')
    elem.set('server_id')
    elem.set('volume_id')
    elem.set('device')


def make_volume(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('display_name')
    elem.set('display_description')
    elem.set('volume_type')
    elem.set('snapshot_id')

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

    def __init__(self, ext_mgr):
        self.volume_api = volume.API()
        self.ext_mgr = ext_mgr
        super(VolumeController, self).__init__()

    @wsgi.serializers(xml=VolumeTemplate)
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

        search_opts = {}
        search_opts.update(req.GET)

        context = req.environ['nova.context']
        remove_invalid_options(context,
                               search_opts, self._get_volume_search_options())

        volumes = self.volume_api.get_all(context, search_opts=search_opts)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    def _image_uuid_from_href(self, image_href):
        # If the image href was generated by nova api, strip image_href
        # down to an id.
        try:
            image_uuid = image_href.split('/').pop()
        except (TypeError, AttributeError):
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        if not utils.is_uuid_like(image_uuid):
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        return image_uuid

    @wsgi.serializers(xml=VolumeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Creates a new volume."""
        if not self.is_valid_body(body, 'volume'):
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        volume = body['volume']

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
            kwargs['snapshot'] = self.volume_api.get_snapshot(context,
                                                              snapshot_id)
        else:
            kwargs['snapshot'] = None

        size = volume.get('size', None)
        if size is None and kwargs['snapshot'] is not None:
            size = kwargs['snapshot']['volume_size']

        LOG.audit(_("Create volume of %s GB"), size, context=context)

        image_href = None
        image_uuid = None
        if self.ext_mgr.is_loaded('os-image-create'):
            image_href = volume.get('imageRef')
            if snapshot_id and image_href:
                msg = _("Snapshot and image cannot be specified together.")
                raise exc.HTTPBadRequest(explanation=msg)
            if image_href:
                image_uuid = self._image_uuid_from_href(image_href)
                kwargs['image_id'] = image_uuid

        kwargs['availability_zone'] = volume.get('availability_zone', None)

        new_volume = self.volume_api.create(context,
                                            size,
                                            volume.get('display_name'),
                                            volume.get('display_description'),
                                            **kwargs)

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        retval = _translate_volume_detail_view(context, dict(new_volume),
                                               image_uuid)

        result = {'volume': retval}

        location = '%s/%s' % (req.url, new_volume['id'])

        return wsgi.ResponseObject(result, headers=dict(location=location))

    def _get_volume_search_options(self):
        """Return volume search options allowed by non-admin."""
        return ('name', 'status')


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
            if opt not in allowed_search_options]
    bad_options = ", ".join(unknown_options)
    log_msg = _("Removing options '%(bad_options)s' from query") % locals()
    LOG.debug(log_msg)
    for opt in unknown_options:
        search_options.pop(opt, None)
