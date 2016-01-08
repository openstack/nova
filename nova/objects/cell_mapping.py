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

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class CellMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'transport_url': fields.StringField(),
        'database_connection': fields.StringField(),
        }

    @staticmethod
    def _from_db_object(context, cell_mapping, db_cell_mapping):
        for key in cell_mapping.fields:
            setattr(cell_mapping, key, db_cell_mapping[key])
        cell_mapping.obj_reset_changes()
        cell_mapping._context = context
        return cell_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_uuid_from_db(context, uuid):

        db_mapping = context.session.query(api_models.CellMapping).filter_by(
                uuid=uuid).first()
        if not db_mapping:
            raise exception.CellMappingNotFound(uuid=uuid)

        return db_mapping

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        db_mapping = cls._get_by_uuid_from_db(context, uuid)

        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):

        db_mapping = api_models.CellMapping()
        db_mapping.update(updates)
        db_mapping.save(context.session)
        return db_mapping

    @base.remotable
    def create(self):
        db_mapping = self._create_in_db(self._context, self.obj_get_changes())
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, uuid, updates):

        db_mapping = context.session.query(
                api_models.CellMapping).filter_by(uuid=uuid).first()
        if not db_mapping:
            raise exception.CellMappingNotFound(uuid=uuid)

        db_mapping.update(updates)
        context.session.add(db_mapping)
        return db_mapping

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        db_mapping = self._save_in_db(self._context, self.uuid, changes)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, uuid):

        result = context.session.query(api_models.CellMapping).filter_by(
                uuid=uuid).delete()
        if not result:
            raise exception.CellMappingNotFound(uuid=uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.uuid)
