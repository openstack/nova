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

from oslo_utils import strutils
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import migrate_server
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception

ALIAS = "os-migrate-server"


authorize = extensions.os_compute_authorizer(ALIAS)


class MigrateServerController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(MigrateServerController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API(skip_policy_check=True)

    @wsgi.response(202)
    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.action('migrate')
    def _migrate(self, req, id, body):
        """Permit admins to migrate a server to a new host."""
        context = req.environ['nova.context']
        authorize(context, action='migrate')

        instance = common.get_instance(self.compute_api, context, id)
        try:
            self.compute_api.resize(req.environ['nova.context'], instance)
        except (exception.TooManyInstances, exception.QuotaError) as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.NoValidHost as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.response(202)
    @extensions.expected_errors((400, 404, 409))
    @wsgi.action('os-migrateLive')
    @validation.schema(migrate_server.migrate_live, "2.1", "2.24")
    @validation.schema(migrate_server.migrate_live_v2_25, "2.25")
    def _migrate_live(self, req, id, body):
        """Permit admins to (live) migrate a server to a new host."""
        context = req.environ["nova.context"]
        authorize(context, action='migrate_live')

        host = body["os-migrateLive"]["host"]
        block_migration = body["os-migrateLive"]["block_migration"]

        if api_version_request.is_supported(req, min_version='2.25'):
            if block_migration == 'auto':
                block_migration = None
            else:
                block_migration = strutils.bool_from_string(block_migration,
                                                            strict=True)
            disk_over_commit = None
        else:
            disk_over_commit = body["os-migrateLive"]["disk_over_commit"]

            block_migration = strutils.bool_from_string(block_migration,
                                                        strict=True)
            disk_over_commit = strutils.bool_from_string(disk_over_commit,
                                                         strict=True)

        try:
            instance = common.get_instance(self.compute_api, context, id)
            self.compute_api.live_migrate(context, instance, block_migration,
                                          disk_over_commit, host)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.NoValidHost,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.MigrationPreCheckError,
                exception.LiveMigrationWithOldNovaNotSupported) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'os-migrateLive', id)


class MigrateServer(extensions.V21APIExtensionBase):
    """Enable migrate and live-migrate server actions."""

    name = "MigrateServer"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = MigrateServerController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
