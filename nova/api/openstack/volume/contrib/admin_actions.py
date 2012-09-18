#   Copyright 2012 OpenStack, LLC.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import webob
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova import volume


LOG = logging.getLogger(__name__)


class AdminController(wsgi.Controller):
    """Abstract base class for AdminControllers."""

    collection = None  # api collection to extend

    # FIXME(clayg): this will be hard to keep up-to-date
    # Concrete classes can expand or over-ride
    valid_status = set([
        'creating',
        'available',
        'deleting',
        'error',
        'error_deleting',
    ])

    def __init__(self, *args, **kwargs):
        super(AdminController, self).__init__(*args, **kwargs)
        # singular name of the resource
        self.resource_name = self.collection.rstrip('s')
        self.volume_api = volume.API()

    def _update(self, *args, **kwargs):
        raise NotImplementedError()

    def _validate_status(self, status):
        if status not in self.valid_status:
            raise exc.HTTPBadRequest("Must specify a valid status")

    def authorize(self, context, action_name):
        # e.g. "snapshot_admin_actions:reset_status"
        action = '%s_admin_actions:%s' % (self.resource_name, action_name)
        extensions.extension_authorizer('volume', action)(context)

    @wsgi.action('os-reset_status')
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""
        context = req.environ['nova.context']
        self.authorize(context, 'reset_status')
        try:
            new_status = body['os-reset_status']['status']
        except (TypeError, KeyError):
            raise exc.HTTPBadRequest("Must specify 'status'")
        self._validate_status(new_status)
        msg = _("Updating status of %(resource)s '%(id)s' to '%(status)s'")
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'status': new_status})
        try:
            self._update(context, id, {'status': new_status})
        except exception.NotFound, e:
            raise exc.HTTPNotFound(e)
        return webob.Response(status_int=202)


class VolumeAdminController(AdminController):
    """AdminController for Volumes."""

    collection = 'volumes'
    valid_status = AdminController.valid_status.union(
        set(['attaching', 'in-use', 'detaching']))

    def _update(self, *args, **kwargs):
        db.volume_update(*args, **kwargs)

    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a resource, bypassing the check that it must be available."""
        context = req.environ['nova.context']
        self.authorize(context, 'force_delete')
        try:
            volume = self.volume_api.get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        self.volume_api.delete(context, volume, force=True)
        return webob.Response(status_int=202)


class SnapshotAdminController(AdminController):
    """AdminController for Snapshots."""

    collection = 'snapshots'

    def _update(self, *args, **kwargs):
        db.snapshot_update(*args, **kwargs)


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "AdminActions"
    alias = "os-admin-actions"
    namespace = "http://docs.openstack.org/volume/ext/admin-actions/api/v1.1"
    updated = "2012-08-25T00:00:00+00:00"

    def get_controller_extensions(self):
        exts = []
        for class_ in (VolumeAdminController, SnapshotAdminController):
            controller = class_()
            extension = extensions.ControllerExtension(
                self, class_.collection, controller)
            exts.append(extension)
        return exts
