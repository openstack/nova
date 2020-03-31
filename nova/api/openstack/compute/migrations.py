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

from oslo_utils import timeutils
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import migrations as schema_migrations
from nova.api.openstack.compute.views import migrations as migrations_view
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.objects import base as obj_base
from nova.policies import migrations as migrations_policies


class MigrationsController(wsgi.Controller):
    """Controller for accessing migrations in OpenStack API."""

    _view_builder_class = migrations_view.ViewBuilder
    _collection_name = "servers/%s/migrations"

    def __init__(self):
        super(MigrationsController, self).__init__()
        self.compute_api = compute.API()

    def _output(self, req, migrations_obj, add_link=False,
                add_uuid=False, add_user_project=False):
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
            del obj['cross_cell_move']
            if not add_uuid:
                del obj['uuid']
            if 'memory_total' in obj:
                for key in detail_keys:
                    del obj[key]
            if not add_user_project:
                if 'user_id' in obj:
                    del obj['user_id']
                if 'project_id' in obj:
                    del obj['project_id']
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

    def _index(self, req, add_link=False, next_link=False, add_uuid=False,
               sort_dirs=None, sort_keys=None, limit=None, marker=None,
               allow_changes_since=False, allow_changes_before=False):
        context = req.environ['nova.context']
        context.can(migrations_policies.POLICY_ROOT % 'index', target={})
        search_opts = {}
        search_opts.update(req.GET)
        if 'changes-since' in search_opts:
            if allow_changes_since:
                search_opts['changes-since'] = timeutils.parse_isotime(
                    search_opts['changes-since'])
            else:
                # Before microversion 2.59, the changes-since filter was not
                # supported in the DB API. However, the schema allowed
                # additionalProperties=True, so a user could pass it before
                # 2.59 and filter by the updated_at field if we don't remove
                # it from search_opts.
                del search_opts['changes-since']

        if 'changes-before' in search_opts:
            if allow_changes_before:
                search_opts['changes-before'] = timeutils.parse_isotime(
                    search_opts['changes-before'])
                changes_since = search_opts.get('changes-since')
                if (changes_since and search_opts['changes-before'] <
                        search_opts['changes-since']):
                    msg = _('The value of changes-since must be less than '
                            'or equal to changes-before.')
                    raise exc.HTTPBadRequest(explanation=msg)
            else:
                # Before microversion 2.59 the schema allowed
                # additionalProperties=True, so a user could pass
                # changes-before before 2.59 and filter by the updated_at
                # field if we don't remove it from search_opts.
                del search_opts['changes-before']

        if sort_keys:
            try:
                migrations = self.compute_api.get_migrations_sorted(
                    context, search_opts,
                    sort_dirs=sort_dirs, sort_keys=sort_keys,
                    limit=limit, marker=marker)
            except exception.MarkerNotFound as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())
        else:
            migrations = self.compute_api.get_migrations(
                context, search_opts)

        add_user_project = api_version_request.is_supported(req, '2.80')
        migrations = self._output(req, migrations, add_link,
                                  add_uuid, add_user_project)
        migrations_dict = {'migrations': migrations}

        if next_link:
            migrations_links = self._view_builder.get_links(req, migrations)
            if migrations_links:
                migrations_dict['migrations_links'] = migrations_links
        return migrations_dict

    @wsgi.Controller.api_version("2.1", "2.22")  # noqa
    @wsgi.expected_errors(())
    @validation.query_schema(schema_migrations.list_query_schema_v20,
                             "2.0", "2.22")
    def index(self, req):
        """Return all migrations using the query parameters as filters."""
        return self._index(req)

    @wsgi.Controller.api_version("2.23", "2.58")  # noqa
    @wsgi.expected_errors(())
    @validation.query_schema(schema_migrations.list_query_schema_v20,
                             "2.23", "2.58")
    def index(self, req):
        """Return all migrations using the query parameters as filters."""
        return self._index(req, add_link=True)

    @wsgi.Controller.api_version("2.59", "2.65")  # noqa
    @wsgi.expected_errors(400)
    @validation.query_schema(schema_migrations.list_query_params_v259,
                             "2.59", "2.65")
    def index(self, req):
        """Return all migrations using the query parameters as filters."""
        limit, marker = common.get_limit_and_marker(req)
        return self._index(req, add_link=True, next_link=True, add_uuid=True,
                           sort_keys=['created_at', 'id'],
                           sort_dirs=['desc', 'desc'],
                           limit=limit, marker=marker,
                           allow_changes_since=True)

    @wsgi.Controller.api_version("2.66")  # noqa
    @wsgi.expected_errors(400)
    @validation.query_schema(schema_migrations.list_query_params_v266,
                             "2.66", "2.79")
    @validation.query_schema(schema_migrations.list_query_params_v280,
                             "2.80")
    def index(self, req):
        """Return all migrations using the query parameters as filters."""
        limit, marker = common.get_limit_and_marker(req)
        return self._index(req, add_link=True, next_link=True, add_uuid=True,
                           sort_keys=['created_at', 'id'],
                           sort_dirs=['desc', 'desc'],
                           limit=limit, marker=marker,
                           allow_changes_since=True,
                           allow_changes_before=True)
