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

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import sqlalchemy as sa

from nova.api.openstack.placement import db_api
from nova.api.openstack.placement import exception
from nova.db.sqlalchemy import api_models as models

CONF = cfg.CONF
PROJECT_TBL = models.Project.__table__


@db_api.placement_context_manager.writer
def ensure_incomplete_project(ctx):
    """Ensures that a project record is created for the "incomplete consumer
    project". Returns the internal ID of that record.
    """
    incomplete_id = CONF.placement.incomplete_consumer_project_id
    sel = sa.select([PROJECT_TBL.c.id]).where(
        PROJECT_TBL.c.external_id == incomplete_id)
    res = ctx.session.execute(sel).fetchone()
    if res:
        return res[0]
    ins = PROJECT_TBL.insert().values(external_id=incomplete_id)
    res = ctx.session.execute(ins)
    return res.inserted_primary_key[0]


@db_api.placement_context_manager.reader
def _get_project_by_external_id(ctx, external_id):
    projects = sa.alias(PROJECT_TBL, name="p")
    cols = [
        projects.c.id,
        projects.c.external_id,
        projects.c.updated_at,
        projects.c.created_at
    ]
    sel = sa.select(cols)
    sel = sel.where(projects.c.external_id == external_id)
    res = ctx.session.execute(sel).fetchone()
    if not res:
        raise exception.ProjectNotFound(external_id=external_id)

    return dict(res)


@base.VersionedObjectRegistry.register_if(False)
class Project(base.VersionedObject):

    fields = {
        'id': fields.IntegerField(read_only=True),
        'external_id': fields.StringField(nullable=False),
    }

    @staticmethod
    def _from_db_object(ctx, target, source):
        for field in target.fields:
            setattr(target, field, source[field])

        target._context = ctx
        target.obj_reset_changes()
        return target

    @classmethod
    def get_by_external_id(cls, ctx, external_id):
        res = _get_project_by_external_id(ctx, external_id)
        return cls._from_db_object(ctx, cls(ctx), res)

    def create(self):
        @db_api.placement_context_manager.writer
        def _create_in_db(ctx):
            db_obj = models.Project(external_id=self.external_id)
            try:
                db_obj.save(ctx.session)
            except db_exc.DBDuplicateEntry:
                raise exception.ProjectExists(external_id=self.external_id)
            self._from_db_object(ctx, self, db_obj)
        _create_in_db(self._context)
