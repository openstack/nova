#   Copyright 2011 OpenStack Foundation
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
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import vm_states
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
ALIAS = "os-admin-actions"

# States usable in resetState action
state_map = dict(active=vm_states.ACTIVE, error=vm_states.ERROR)


def authorize(context, action_name):
    action = 'v3:%s:%s' % (ALIAS, action_name)
    extensions.extension_authorizer('compute', action)(context)


class AdminActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(AdminActionsController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @extensions.expected_errors((404, 409))
    @wsgi.action('pause')
    def _pause(self, req, id, body):
        """Permit Admins to pause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, 'pause')
        try:
            server = self.compute_api.get(ctxt, id, want_objects=True)
            self.compute_api.pause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'pause')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('unpause')
    def _unpause(self, req, id, body):
        """Permit Admins to unpause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, 'unpause')
        try:
            server = self.compute_api.get(ctxt, id, want_objects=True)
            self.compute_api.unpause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'unpause')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('suspend')
    def _suspend(self, req, id, body):
        """Permit admins to suspend the server."""
        context = req.environ['nova.context']
        authorize(context, 'suspend')
        try:
            server = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.suspend(context, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'suspend')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('resume')
    def _resume(self, req, id, body):
        """Permit admins to resume the server from suspend."""
        context = req.environ['nova.context']
        authorize(context, 'resume')
        try:
            server = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.resume(context, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resume')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((400, 404, 409, 413))
    @wsgi.action('migrate')
    def _migrate(self, req, id, body):
        """Permit admins to migrate a server to a new host."""
        context = req.environ['nova.context']
        authorize(context, 'migrate')
        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.resize(req.environ['nova.context'], instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.CannotResizeToSameFlavor as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.TooManyInstances as e:
            raise exc.HTTPRequestEntityTooLarge(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('reset_network')
    def _reset_network(self, req, id, body):
        """Permit admins to reset networking on a server."""
        context = req.environ['nova.context']
        authorize(context, 'reset_network')
        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.reset_network(context, instance)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('inject_network_info')
    def _inject_network_info(self, req, id, body):
        """Permit admins to inject network info into a server."""
        context = req.environ['nova.context']
        authorize(context, 'inject_network_info')
        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.inject_network_info(context, instance)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors(404)
    @wsgi.action('lock')
    def _lock(self, req, id, body):
        """Lock a server instance."""
        context = req.environ['nova.context']
        authorize(context, 'lock')
        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.lock(context, instance)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors(404)
    @wsgi.action('unlock')
    def _unlock(self, req, id, body):
        """Unlock a server instance."""
        context = req.environ['nova.context']
        authorize(context, 'unlock')
        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.unlock(context, instance)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((400, 404, 409, 413))
    @wsgi.action('create_backup')
    def _create_backup(self, req, id, body):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        context = req.environ["nova.context"]
        authorize(context, 'create_backup')

        try:
            entity = body["create_backup"]
        except (KeyError, TypeError):
            raise exc.HTTPBadRequest(_("Malformed request body"))

        try:
            image_name = entity["name"]
            backup_type = entity["backup_type"]
            rotation = entity["rotation"]

        except KeyError as missing_key:
            msg = _("create_backup entity requires %s attribute") % missing_key
            raise exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed create_backup entity")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            rotation = int(rotation)
        except ValueError:
            msg = _("create_backup attribute 'rotation' must be an integer")
            raise exc.HTTPBadRequest(explanation=msg)
        if rotation < 0:
            msg = _("create_backup attribute 'rotation' must be greater "
                    "than or equal to zero")
            raise exc.HTTPBadRequest(explanation=msg)

        props = {}
        metadata = entity.get('metadata', {})
        common.check_img_metadata_properties_quota(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            instance = self.compute_api.get(context, id, want_objects=True)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        try:
            image = self.compute_api.backup(context, instance, image_name,
                    backup_type, rotation, extra_properties=props)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'create_backup')

        resp = webob.Response(status_int=202)

        # build location of newly-created image entity if rotation is not zero
        if rotation > 0:
            image_id = str(image['id'])
            image_ref = os.path.join(req.application_url, 'images', image_id)
            resp.headers['Location'] = image_ref

        return resp

    @extensions.expected_errors((400, 404, 409))
    @wsgi.action('migrate_live')
    def _migrate_live(self, req, id, body):
        """Permit admins to (live) migrate a server to a new host."""
        context = req.environ["nova.context"]
        authorize(context, 'migrate_live')

        try:
            block_migration = body["migrate_live"]["block_migration"]
            disk_over_commit = body["migrate_live"]["disk_over_commit"]
            host = body["migrate_live"]["host"]
        except (TypeError, KeyError):
            msg = _("host, block_migration and disk_over_commit must "
                    "be specified for live migration.")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            self.compute_api.live_migrate(context, instance, block_migration,
                                          disk_over_commit, host)
        except (exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.NoValidHost,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.MigrationPreCheckError) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate_live')
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((400, 404))
    @wsgi.action('reset_state')
    def _reset_state(self, req, id, body):
        """Permit admins to reset the state of a server."""
        context = req.environ["nova.context"]
        authorize(context, 'reset_state')

        # Identify the desired state from the body
        try:
            state = state_map[body["reset_state"]["state"]]
        except (TypeError, KeyError):
            msg = _("Desired state must be specified.  Valid states "
                    "are: %s") % ', '.join(sorted(state_map.keys()))
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            instance.vm_state = state
            instance.task_state = None
            instance.save(admin_state_reset=True)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)


class AdminActions(extensions.V3APIExtensionBase):
    """Enable admin-only server actions

    Actions include: pause, unpause, suspend, resume, migrate,
    reset_network, inject_network_info, lock, unlock, create_backup
    """

    name = "AdminActions"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/%s/api/v3" % ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = AdminActionsController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
