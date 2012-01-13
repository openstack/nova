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

"""The volumes snapshots api."""

from webob import exc
import webob

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova import flags
from nova import log as logging
from nova import volume


LOG = logging.getLogger("nova.api.openstack.volume.snapshots")


FLAGS = flags.FLAGS


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


class SnapshotsController(object):
    """The Volumes API controller for the OpenStack API."""

    def __init__(self):
        self.volume_api = volume.API()
        super(SnapshotsController, self).__init__()

    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['nova.context']

        try:
            vol = self.volume_api.get_snapshot(context, id)
        except exception.NotFound:
            return exc.HTTPNotFound()

        return {'snapshot': _translate_snapshot_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            self.volume_api.delete_snapshot(context, snapshot)
        except exception.NotFound:
            return exc.HTTPNotFound()
        return webob.Response(status_int=202)

    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['nova.context']

        snapshots = self.volume_api.get_all_snapshots(context)
        limited_list = common.limited(snapshots, req)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']

        if not body:
            return exc.HTTPUnprocessableEntity()

        snapshot = body['snapshot']
        volume_id = snapshot['volume_id']
        volume = self.volume_api.get(context, volume_id)
        force = snapshot.get('force', False)
        msg = _("Create snapshot from volume %s")
        LOG.audit(msg, volume_id, context=context)

        if force:
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


class SnapshotSerializer(xmlutil.XMLTemplateSerializer):
    def default(self):
        return SnapshotTemplate()

    def index(self):
        return SnapshotsTemplate()

    def detail(self):
        return SnapshotsTemplate()


def create_resource():
    body_serializers = {
        'application/xml': SnapshotSerializer(),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)

    return wsgi.Resource(SnapshotsController(), serializer=serializer)
