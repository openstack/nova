# Copyright 2016 OpenStack Foundation
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

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_migrations
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.policies import servers_migrations as sm_policies


def output(migration, include_uuid=False, include_user_project=False):
    """Returns the desired output of the API from an object.

    From a Migrations's object this method returns the primitive
    object with the only necessary and expected fields.
    """
    result = {
        "created_at": migration.created_at,
        "dest_compute": migration.dest_compute,
        "dest_host": migration.dest_host,
        "dest_node": migration.dest_node,
        "disk_processed_bytes": migration.disk_processed,
        "disk_remaining_bytes": migration.disk_remaining,
        "disk_total_bytes": migration.disk_total,
        "id": migration.id,
        "memory_processed_bytes": migration.memory_processed,
        "memory_remaining_bytes": migration.memory_remaining,
        "memory_total_bytes": migration.memory_total,
        "server_uuid": migration.instance_uuid,
        "source_compute": migration.source_compute,
        "source_node": migration.source_node,
        "status": migration.status,
        "updated_at": migration.updated_at
    }
    if include_uuid:
        result['uuid'] = migration.uuid
    if include_user_project:
        result['user_id'] = migration.user_id
        result['project_id'] = migration.project_id
    return result


class ServerMigrationsController(wsgi.Controller):
    """The server migrations API controller for the OpenStack API."""

    def __init__(self):
        super(ServerMigrationsController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.Controller.api_version("2.22")
    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('force_complete')
    @validation.schema(server_migrations.force_complete)
    def _force_complete(self, req, id, server_id, body):
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(sm_policies.POLICY_ROOT % 'force_complete',
                    target={'project_id': instance.project_id})

        try:
            self.compute_api.live_migrate_force_complete(context, instance, id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.MigrationNotFoundByStatus,
                exception.InvalidMigrationState,
                exception.MigrationNotFoundForInstance) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'force_complete', server_id)

    @wsgi.Controller.api_version("2.23")
    @wsgi.expected_errors(404)
    def index(self, req, server_id):
        """Return all migrations of an instance in progress."""
        context = req.environ['nova.context']
        # NOTE(Shaohe Feng) just check the instance is available. To keep
        # consistency with other API, check it before get migrations.
        instance = common.get_instance(self.compute_api, context, server_id)

        context.can(sm_policies.POLICY_ROOT % 'index',
                    target={'project_id': instance.project_id})

        migrations = self.compute_api.get_migrations_in_progress_by_instance(
                context, server_id, 'live-migration')

        include_uuid = api_version_request.is_supported(req, '2.59')

        include_user_project = api_version_request.is_supported(req, '2.80')
        return {'migrations': [
            output(migration, include_uuid, include_user_project)
            for migration in migrations]}

    @wsgi.Controller.api_version("2.23")
    @wsgi.expected_errors(404)
    def show(self, req, server_id, id):
        """Return the migration of an instance in progress by id."""
        context = req.environ['nova.context']
        # NOTE(Shaohe Feng) just check the instance is available. To keep
        # consistency with other API, check it before get migrations.
        instance = common.get_instance(self.compute_api, context, server_id)

        context.can(sm_policies.POLICY_ROOT % 'show',
                    target={'project_id': instance.project_id})

        try:
            migration = self.compute_api.get_migration_by_id_and_instance(
                    context, id, server_id)
        except exception.MigrationNotFoundForInstance:
            msg = _("In-progress live migration %(id)s is not found for"
                    " server %(uuid)s.") % {"id": id, "uuid": server_id}
            raise exc.HTTPNotFound(explanation=msg)

        if not migration.is_live_migration:
            msg = _("Migration %(id)s for server %(uuid)s is not"
                    " live-migration.") % {"id": id, "uuid": server_id}
            raise exc.HTTPNotFound(explanation=msg)

        # TODO(Shaohe Feng) we should share the in-progress list.
        in_progress = ['queued', 'preparing', 'running', 'post-migrating']
        if migration.get("status") not in in_progress:
            msg = _("Live migration %(id)s for server %(uuid)s is not in"
                    " progress.") % {"id": id, "uuid": server_id}
            raise exc.HTTPNotFound(explanation=msg)

        include_uuid = api_version_request.is_supported(req, '2.59')

        include_user_project = api_version_request.is_supported(req, '2.80')
        return {'migration': output(migration, include_uuid,
                                    include_user_project)}

    @wsgi.Controller.api_version("2.24")
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    def delete(self, req, server_id, id):
        """Abort an in progress migration of an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(sm_policies.POLICY_ROOT % 'delete',
                    target={'project_id': instance.project_id})

        support_abort_in_queue = api_version_request.is_supported(req, '2.65')

        try:
            self.compute_api.live_migrate_abort(
                context, instance, id,
                support_abort_in_queue=support_abort_in_queue)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                    state_error, "abort live migration", server_id)
        except exception.MigrationNotFoundForInstance as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InvalidMigrationState as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
