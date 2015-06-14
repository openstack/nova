# Copyright 2013 Red Hat, Inc.
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

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _LI


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute',
        'os-assisted-volume-snapshots')


class AssistedVolumeSnapshotsController(wsgi.Controller):

    def __init__(self):
        self.compute_api = compute.API()
        super(AssistedVolumeSnapshotsController, self).__init__()

    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        authorize(context, action='create')

        if not self.is_valid_body(body, 'snapshot'):
            raise webob.exc.HTTPBadRequest()

        try:
            snapshot = body['snapshot']
            create_info = snapshot['create_info']
            volume_id = snapshot['volume_id']
        except KeyError:
            raise webob.exc.HTTPBadRequest()

        LOG.info(_LI("Create assisted snapshot from volume %s"), volume_id,
                  context=context)

        return self.compute_api.volume_snapshot_create(context, volume_id,
                                                       create_info)

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        authorize(context, action='delete')

        LOG.info(_LI("Delete snapshot with id: %s"), id, context=context)

        delete_metadata = {}
        delete_metadata.update(req.GET)

        try:
            delete_info = jsonutils.loads(delete_metadata['delete_info'])
            volume_id = delete_info['volume_id']
        except (KeyError, ValueError) as e:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(e))

        try:
            self.compute_api.volume_snapshot_delete(context, volume_id,
                    id, delete_info)
        except exception.NotFound:
            return webob.exc.HTTPNotFound()

        return webob.Response(status_int=204)


class Assisted_volume_snapshots(extensions.ExtensionDescriptor):
    """Assisted volume snapshots."""

    name = "AssistedVolumeSnapshots"
    alias = "os-assisted-volume-snapshots"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "assisted-volume-snapshots/api/v2")
    updated = "2013-08-29T00:00:00Z"

    def get_resources(self):
        resource = extensions.ResourceExtension('os-assisted-volume-snapshots',
                AssistedVolumeSnapshotsController())

        return [resource]
