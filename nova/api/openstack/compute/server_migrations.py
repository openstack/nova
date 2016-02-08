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

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_migrations
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception

ALIAS = 'servers:migrations'
authorize = extensions.os_compute_authorizer(ALIAS)


class ServerMigrationsController(wsgi.Controller):
    """The server migrations API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API(skip_policy_check=True)
        super(ServerMigrationsController, self).__init__()

    @wsgi.Controller.api_version("2.22")
    @wsgi.response(202)
    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.action('force_complete')
    @validation.schema(server_migrations.force_complete)
    def _force_complete(self, req, id, server_id, body):
        context = req.environ['nova.context']
        authorize(context, action='force_complete')

        instance = common.get_instance(self.compute_api, context, server_id)
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


class ServerMigrations(extensions.V21APIExtensionBase):
    """Server Migrations API."""
    name = "ServerMigrations"
    alias = 'server-migrations'
    version = 1

    def get_resources(self):
        parent = {'member_name': 'server',
                  'collection_name': 'servers'}
        member_actions = {'action': 'POST'}
        resources = [extensions.ResourceExtension(
            'migrations', ServerMigrationsController(),
            parent=parent, member_actions=member_actions)]
        return resources

    def get_controller_extensions(self):
        return []
