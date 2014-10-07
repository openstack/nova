# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

import os.path

import webob

from nova.api.openstack import common
from nova.api.openstack.compute.schemas.v3 import create_backup
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception

ALIAS = "os-create-backup"
authorize = extensions.extension_authorizer('compute', "v3:" + ALIAS)


class CreateBackupController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(CreateBackupController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.action('createBackup')
    @validation.schema(create_backup.create_backup)
    def _create_backup(self, req, id, body):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        context = req.environ["nova.context"]
        authorize(context)
        entity = body["createBackup"]

        image_name = entity["name"]
        backup_type = entity["backup_type"]
        rotation = int(entity["rotation"])

        props = {}
        metadata = entity.get('metadata', {})
        common.check_img_metadata_properties_quota(context, metadata)
        props.update(metadata)

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)

        try:
            image = self.compute_api.backup(context, instance, image_name,
                    backup_type, rotation, extra_properties=props)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'createBackup', id)

        resp = webob.Response(status_int=202)

        # build location of newly-created image entity if rotation is not zero
        if rotation > 0:
            image_id = str(image['id'])
            image_ref = os.path.join(req.application_url, 'images', image_id)
            resp.headers['Location'] = image_ref

        return resp


class CreateBackup(extensions.V3APIExtensionBase):
    """Create a backup of a server."""

    name = "CreateBackup"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = CreateBackupController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
