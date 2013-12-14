#    Copyright 2013 Red Hat, Inc
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

from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields


OPTIONAL_FIELDS = ['extra_specs', 'projects']


class Flavor(base.NovaPersistentObject, base.NovaObject):
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=True),
        'memory_mb': fields.IntegerField(),
        'vcpus': fields.IntegerField(),
        'root_gb': fields.IntegerField(),
        'ephemeral_gb': fields.IntegerField(),
        'flavorid': fields.StringField(),
        'swap': fields.IntegerField(),
        'rxtx_factor': fields.FloatField(nullable=True, default=1.0),
        'vcpu_weight': fields.IntegerField(nullable=True),
        'disabled': fields.BooleanField(),
        'is_public': fields.BooleanField(),
        'extra_specs': fields.DictOfStringsField(),
        'projects': fields.ListOfStringsField(),
        }

    @staticmethod
    def _from_db_object(context, flavor, db_flavor, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in flavor.fields.items():
            if name in OPTIONAL_FIELDS:
                continue
            value = db_flavor[name]
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            flavor[name] = value

        if 'extra_specs' in expected_attrs:
            flavor.extra_specs = db_flavor['extra_specs']

        if 'projects' in expected_attrs:
            flavor._load_projects(context)

        flavor._context = context
        flavor.obj_reset_changes()
        return flavor

    @base.remotable
    def _load_projects(self, context):
        self.projects = [x['project_id'] for x in
                         db.flavor_access_get_by_flavor_id(context,
                                                           self.flavorid)]
        self.obj_reset_changes('projects')

    def obj_load_attr(self, attrname):
        # NOTE(danms): Only projects could be lazy-loaded right now
        if attrname != 'projects':
            raise exception.ObjectActionError(
                action='obj_load_attr', reason='unable to load %s' % attrname)

        self._load_projects()

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_flavor = db.flavor_get(context, id)
        return cls._from_db_object(context, cls(), db_flavor,
                                   expected_attrs=['extra_specs'])

    @base.remotable_classmethod
    def get_by_name(cls, context, name):
        db_flavor = db.flavor_get_by_name(context, name)
        return cls._from_db_object(context, cls(), db_flavor,
                                   expected_attrs=['extra_specs'])

    @base.remotable_classmethod
    def get_by_flavor_id(cls, context, flavor_id, read_deleted=None):
        db_flavor = db.flavor_get_by_flavor_id(context, flavor_id,
                                               read_deleted)
        return cls._from_db_object(context, cls(), db_flavor,
                                   expected_attrs=['extra_specs'])

    @base.remotable
    def add_access(self, context, project_id):
        if 'projects' in self.obj_what_changed():
            raise exception.ObjectActionError(action='add_access',
                                              reason='projects modified')
        db.flavor_access_add(context, self.flavorid, project_id)
        self._load_projects(context)

    @base.remotable
    def remove_access(self, context, project_id):
        if 'projects' in self.obj_what_changed():
            raise exception.ObjectActionError(action='remove_access',
                                              reason='projects modified')
        db.flavor_access_remove(context, self.flavorid, project_id)
        self._load_projects(context)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        expected_attrs = []
        for attr in OPTIONAL_FIELDS:
            if attr in updates:
                expected_attrs.append(attr)
        projects = updates.pop('projects', [])
        db_flavor = db.flavor_create(context, updates, projects=projects)
        self._from_db_object(context, self, db_flavor,
                             expected_attrs=expected_attrs)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        projects = updates.pop('projects', None)
        extra_specs = updates.pop('extra_specs', None)
        if updates:
            raise exception.ObjectActionError(
                action='save', reason='read-only fields were changed')

        if extra_specs:
            db.flavor_extra_specs_update_or_create(context, self.flavorid,
                                                   extra_specs)

        # NOTE(danms): This could be much simpler and more efficient
        # with a smarter flavor_access_update() method in db_api.
        if projects is not None:
            current_projects = [x['project_id']
                                for x in db.flavor_access_get_by_flavor_id(
                                    context, self.flavorid)]
            for project_id in projects:
                if project_id not in current_projects:
                    db.flavor_access_add(context, self.flavorid, project_id)
                else:
                    current_projects.remove(project_id)
            for condemned_project_id in current_projects:
                db.flavor_access_remove(context, self.flavorid,
                                        condemned_project_id)
        self.obj_reset_changes()

    @base.remotable
    def destroy(self, context):
        db.flavor_destroy(context, self.name)


class FlavorList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Flavor'),
        }
    child_versions = {
        '1.0': '1.0',
        }

    @base.remotable_classmethod
    def get_all(cls, context, inactive=False, filters=None,
                sort_key='flavorid', sort_dir='asc', limit=None, marker=None):
        db_flavors = db.flavor_get_all(context, inactive=inactive,
                                       filters=filters, sort_key=sort_key,
                                       sort_dir=sort_dir, limit=limit,
                                       marker=marker)
        return base.obj_make_list(context, cls(), Flavor, db_flavors,
                                  expected_attrs=['extra_specs'])
