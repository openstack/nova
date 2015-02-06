# Copyright 2013 Red Hat, Inc.
# Copyright 2014 IBM Corp.
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

"""The Assisted volume snapshots extension."""

from oslo_serialization import jsonutils
import six
from webob import exc

from nova.api.openstack.compute.schemas.v3 import assisted_volume_snapshots
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)
ALIAS = 'os-assisted-volume-snapshots'
authorize = extensions.extension_authorizer('compute',
                                            'v3:' + ALIAS)


class AssistedVolumeSnapshotsController(wsgi.Controller):
    """The Assisted volume snapshots API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        super(AssistedVolumeSnapshotsController, self).__init__()

    @extensions.expected_errors(400)
    @validation.schema(assisted_volume_snapshots.snapshots_create)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        authorize(context, action='create')

        snapshot = body['snapshot']
        create_info = snapshot['create_info']
        volume_id = snapshot['volume_id']

        LOG.audit(_("Create assisted snapshot from volume %s"), volume_id,
                  context=context)
        try:
            return self.compute_api.volume_snapshot_create(context, volume_id,
                                                           create_info)
        except (exception.VolumeBDMNotFound,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

    @wsgi.response(204)
    @extensions.expected_errors((400, 404))
    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        authorize(context, action='delete')

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        delete_metadata = {}
        delete_metadata.update(req.GET)

        try:
            delete_info = jsonutils.loads(delete_metadata['delete_info'])
            volume_id = delete_info['volume_id']
        except (KeyError, ValueError) as e:
            raise exc.HTTPBadRequest(explanation=six.text_type(e))

        try:
            self.compute_api.volume_snapshot_delete(context, volume_id,
                    id, delete_info)
        except (exception.VolumeBDMNotFound,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except exception.NotFound as e:
            return exc.HTTPNotFound(explanation=e.format_message())


class AssistedVolumeSnapshots(extensions.V3APIExtensionBase):
    """Assisted volume snapshots."""

    name = "AssistedVolumeSnapshots"
    alias = ALIAS
    version = 1

    def get_resources(self):
        res = [extensions.ResourceExtension(ALIAS,
                                    AssistedVolumeSnapshotsController())]
        return res

    def get_controller_extensions(self):
        """It's an abstract function V3APIExtensionBase and the extension
        will not be loaded without it.
        """
        return []
