# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from webob import exc

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import volume
from nova import wsgi
from nova.api.openstack import common
from nova.api.openstack import faults


LOG = logging.getLogger("nova.api.volumes")


FLAGS = flags.FLAGS


def _translate_detail_view(context, volume):
    """Maps keys for details view."""

    d = _translate_summary_view(context, volume)

    # No additional data / lookups at the moment

    return d


def _translate_summary_view(context, vol):
    """Maps keys for summary view."""
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


class Controller(wsgi.Controller):
    """The volume attachment API controller for the Openstack API.

    A child resource of the server.  Note that we use the volume id
    as the ID of the attachment (though this is not guaranteed externally)"""

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
        super(Controller, self).__init__()

    def index(self, req, server_id):
        """Returns the list of volume attachments for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_summary_view)

    def show(self, req, server_id, id):
        """Return data about the given volume."""
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

        return {'volumeAttachment': _translate_detail_view(context, vol)}

    def create(self, req, server_id):
        """Attach a volume to an instance."""
        context = req.environ['nova.context']

        env = self._deserialize(req.body, req.get_content_type())
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        instance_id = server_id
        volume_id = env['volumeAttachment']['volumeId']
        device = env['volumeAttachment']['device']

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

    def update(self, _req, _server_id, _id):
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

        return exc.HTTPAccepted()

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
