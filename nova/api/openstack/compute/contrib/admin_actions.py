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
import traceback

from oslo_utils import strutils
import six
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import vm_states
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

# States usable in resetState action
state_map = dict(active=vm_states.ACTIVE, error=vm_states.ERROR)


def authorize(context, action_name):
    action = 'admin_actions:%s' % action_name
    extensions.extension_authorizer('compute', action)(context)


class AdminActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(AdminActionsController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    # TODO(bcwaldon): These action names should be prefixed with 'os-'

    @wsgi.action('pause')
    def _pause(self, req, id, body):
        """Permit Admins to pause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, 'pause')
        server = common.get_instance(self.compute_api, ctxt, id,
                                     want_objects=True)
        try:
            self.compute_api.pause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'pause', id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::pause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('unpause')
    def _unpause(self, req, id, body):
        """Permit Admins to unpause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, 'unpause')
        server = common.get_instance(self.compute_api, ctxt, id,
                                     want_objects=True)
        try:
            self.compute_api.unpause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'unpause', id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::unpause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('suspend')
    def _suspend(self, req, id, body):
        """Permit admins to suspend the server."""
        context = req.environ['nova.context']
        authorize(context, 'suspend')
        server = common.get_instance(self.compute_api, context, id,
                                     want_objects=True)
        try:
            self.compute_api.suspend(context, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'suspend', id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("compute.api::suspend %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('resume')
    def _resume(self, req, id, body):
        """Permit admins to resume the server from suspend."""
        context = req.environ['nova.context']
        authorize(context, 'resume')
        server = common.get_instance(self.compute_api, context, id,
                                     want_objects=True)
        try:
            self.compute_api.resume(context, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resume', id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("compute.api::resume %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('migrate')
    def _migrate(self, req, id, body):
        """Permit admins to migrate a server to a new host."""
        context = req.environ['nova.context']
        authorize(context, 'migrate')
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.resize(req.environ['nova.context'], instance)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.NoValidHost as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except Exception as e:
            LOG.exception(_LE("Error in migrate %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    @wsgi.action('resetNetwork')
    def _reset_network(self, req, id, body):
        """Permit admins to reset networking on a server."""
        context = req.environ['nova.context']
        authorize(context, 'resetNetwork')
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.reset_network(context, instance)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::reset_network %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('injectNetworkInfo')
    def _inject_network_info(self, req, id, body):
        """Permit admins to inject network info into a server."""
        context = req.environ['nova.context']
        authorize(context, 'injectNetworkInfo')
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.inject_network_info(context, instance)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::inject_network_info %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('lock')
    def _lock(self, req, id, body):
        """Lock a server instance."""
        context = req.environ['nova.context']
        authorize(context, 'lock')
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.lock(context, instance)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('unlock')
    def _unlock(self, req, id, body):
        """Unlock a server instance."""
        context = req.environ['nova.context']
        authorize(context, 'unlock')
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.unlock(context, instance)
        except exception.PolicyNotAuthorized as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::unlock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @wsgi.action('createBackup')
    def _create_backup(self, req, id, body):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        context = req.environ["nova.context"]
        authorize(context, 'createBackup')
        entity = body["createBackup"]

        try:
            image_name = entity["name"]
            backup_type = entity["backup_type"]
            rotation = entity["rotation"]

        except KeyError as missing_key:
            msg = _("createBackup entity requires %s attribute") % missing_key
            raise exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createBackup entity")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            rotation = int(rotation)
        except ValueError:
            msg = _("createBackup attribute 'rotation' must be an integer")
            raise exc.HTTPBadRequest(explanation=msg)
        if rotation < 0:
            msg = _("createBackup attribute 'rotation' must be greater "
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

    @wsgi.action('os-migrateLive')
    def _migrate_live(self, req, id, body):
        """Permit admins to (live) migrate a server to a new host."""
        context = req.environ["nova.context"]
        authorize(context, 'migrateLive')

        try:
            block_migration = body["os-migrateLive"]["block_migration"]
            disk_over_commit = body["os-migrateLive"]["disk_over_commit"]
            host = body["os-migrateLive"]["host"]
        except (TypeError, KeyError):
            msg = _("host, block_migration and disk_over_commit must "
                    "be specified for live migration.")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            block_migration = strutils.bool_from_string(block_migration,
                                                        strict=True)
            disk_over_commit = strutils.bool_from_string(disk_over_commit,
                                                         strict=True)
        except ValueError as err:
            raise exc.HTTPBadRequest(explanation=six.text_type(err))

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.live_migrate(context, instance, block_migration,
                                          disk_over_commit, host)
        except (exception.NoValidHost,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.InstanceNotRunning,
                exception.MigrationPreCheckError,
                exception.LiveMigrationWithOldNovaNotSafe) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'os-migrateLive', id)
        except Exception:
            if host is None:
                msg = _("Live migration of instance %s to another host "
                        "failed") % id
            else:
                msg = _("Live migration of instance %(id)s to host %(host)s "
                        "failed") % {'id': id, 'host': host}
            LOG.exception(msg)
            # Return messages from scheduler
            raise exc.HTTPInternalServerError(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.action('os-resetState')
    def _reset_state(self, req, id, body):
        """Permit admins to reset the state of a server."""
        context = req.environ["nova.context"]
        authorize(context, 'resetState')

        # Identify the desired state from the body
        try:
            state = state_map[body["os-resetState"]["state"]]
        except (TypeError, KeyError):
            msg = _("Desired state must be specified.  Valid states "
                    "are: %s") % ', '.join(sorted(state_map.keys()))
            raise exc.HTTPBadRequest(explanation=msg)

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            instance.vm_state = state
            instance.task_state = None
            instance.save(admin_state_reset=True)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(explanation=msg)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_LE("Compute.api::resetState %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin-only server actions

    Actions include: pause, unpause, suspend, resume, migrate,
    resetNetwork, injectNetworkInfo, lock, unlock, createBackup
    """

    name = "AdminActions"
    alias = "os-admin-actions"
    namespace = "http://docs.openstack.org/compute/ext/admin-actions/api/v1.1"
    updated = "2011-09-20T00:00:00Z"

    def get_controller_extensions(self):
        controller = AdminActionsController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
