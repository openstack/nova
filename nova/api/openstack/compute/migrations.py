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

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.objects import base as obj_base
from nova.policies import migrations as migrations_policies


class MigrationsController(wsgi.Controller):
    """Controller for accessing migrations in OpenStack API."""

    _view_builder_class = common.ViewBuilder
    _collection_name = "servers/%s/migrations"

    def __init__(self):
        super(MigrationsController, self).__init__()
        self.compute_api = compute.API()

    def _output(self, req, migrations_obj, add_link=False):
        """Returns the desired output of the API from an object.

        From a MigrationsList's object this method returns a list of
        primitive objects with the only necessary fields.
        """
        detail_keys = ['memory_total', 'memory_processed', 'memory_remaining',
                       'disk_total', 'disk_processed', 'disk_remaining']

        # TODO(Shaohe Feng) we should share the in-progress list.
        live_migration_in_progress = ['queued', 'preparing',
                                      'running', 'post-migrating']

        # Note(Shaohe Feng): We need to leverage the oslo.versionedobjects.
        # Then we can pass the target version to it's obj_to_primitive.
        objects = obj_base.obj_to_primitive(migrations_obj)
        objects = [x for x in objects if not x['hidden']]
        for obj in objects:
            del obj['deleted']
            del obj['deleted_at']
            del obj['hidden']
            if 'memory_total' in obj:
                for key in detail_keys:
                    del obj[key]
            # NOTE(Shaohe Feng) above version 2.23, add migration_type for all
            # kinds of migration, but we only add links just for in-progress
            # live-migration.
            if add_link and obj['migration_type'] == "live-migration" and (
                    obj["status"] in live_migration_in_progress):
                obj["links"] = self._view_builder._get_links(
                    req, obj["id"],
                    self._collection_name % obj['instance_uuid'])
            elif add_link is False:
                del obj['migration_type']

        return objects

    @extensions.expected_errors(())
    def index(self, req):
        """Return all migrations in progress."""
        context = req.environ['nova.context']
        context.can(migrations_policies.POLICY_ROOT % 'index')
        migrations = self.compute_api.get_migrations(context, req.GET)

        if api_version_request.is_supported(req, min_version='2.23'):
            return {'migrations': self._output(req, migrations, True)}

        return {'migrations': self._output(req, migrations)}
