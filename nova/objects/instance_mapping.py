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

from sqlalchemy.orm import joinedload

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import cell_mapping
from nova.objects import fields


@base.NovaObjectRegistry.register
class InstanceMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'instance_uuid': fields.UUIDField(),
        'cell_mapping': fields.ObjectField('CellMapping', nullable=True),
        'project_id': fields.StringField(),
        }

    def _update_with_cell_id(self, updates):
        cell_mapping_obj = updates.pop("cell_mapping", None)
        if cell_mapping_obj:
            updates["cell_id"] = cell_mapping_obj.id
        return updates

    @staticmethod
    def _from_db_object(context, instance_mapping, db_instance_mapping):
        for key in instance_mapping.fields:
            db_value = db_instance_mapping.get(key)
            if key == 'cell_mapping':
                # cell_mapping can be None indicating that the instance has
                # not been scheduled yet.
                if db_value:
                    db_value = cell_mapping.CellMapping._from_db_object(
                        context, cell_mapping.CellMapping(), db_value)
            setattr(instance_mapping, key, db_value)
        instance_mapping.obj_reset_changes()
        instance_mapping._context = context
        return instance_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        db_mapping = (context.session.query(api_models.InstanceMapping)
                        .options(joinedload('cell_mapping'))
                        .filter(
                            api_models.InstanceMapping.instance_uuid
                            == instance_uuid)).first()
        if not db_mapping:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

        return db_mapping

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_mapping = cls._get_by_instance_uuid_from_db(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_mapping = api_models.InstanceMapping()
        db_mapping.update(updates)
        db_mapping.save(context.session)
        # NOTE: This is done because a later access will trigger a lazy load
        # outside of the db session so it will fail. We don't lazy load
        # cell_mapping on the object later because we never need an
        # InstanceMapping without the CellMapping.
        db_mapping.cell_mapping
        return db_mapping

    @base.remotable
    def create(self):
        changes = self.obj_get_changes()
        changes = self._update_with_cell_id(changes)
        db_mapping = self._create_in_db(self._context, changes)
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, instance_uuid, updates):
        db_mapping = context.session.query(
                api_models.InstanceMapping).filter_by(
                        instance_uuid=instance_uuid).first()
        if not db_mapping:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

        db_mapping.update(updates)
        # NOTE: This is done because a later access will trigger a lazy load
        # outside of the db session so it will fail. We don't lazy load
        # cell_mapping on the object later because we never need an
        # InstanceMapping without the CellMapping.
        db_mapping.cell_mapping
        context.session.add(db_mapping)
        return db_mapping

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        changes = self._update_with_cell_id(changes)
        db_mapping = self._save_in_db(self._context, self.instance_uuid,
                changes)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, instance_uuid):
        result = context.session.query(api_models.InstanceMapping).filter_by(
                instance_uuid=instance_uuid).delete()
        if not result:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.instance_uuid)


@base.NovaObjectRegistry.register
class InstanceMappingList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added get_by_cell_id method.
    # Version 1.2: Added get_by_instance_uuids method
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceMapping'),
        }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_project_id_from_db(context, project_id):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(
                    api_models.InstanceMapping.project_id == project_id)).all()

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        db_mappings = cls._get_by_project_id_from_db(context, project_id)

        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_cell_id_from_db(context, cell_id):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(api_models.InstanceMapping.cell_id == cell_id)).all()

    @base.remotable_classmethod
    def get_by_cell_id(cls, context, cell_id):
        db_mappings = cls._get_by_cell_id_from_db(context, cell_id)
        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_instance_uuids_from_db(context, uuids):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(api_models.InstanceMapping.instance_uuid.in_(uuids))
                .all())

    @base.remotable_classmethod
    def get_by_instance_uuids(cls, context, uuids):
        db_mappings = cls._get_by_instance_uuids_from_db(context, uuids)
        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_bulk_in_db(context, instance_uuids):
        return context.session.query(api_models.InstanceMapping).filter(
                api_models.InstanceMapping.instance_uuid.in_(instance_uuids)).\
                delete(synchronize_session=False)

    @classmethod
    def destroy_bulk(cls, context, instance_uuids):
        return cls._destroy_bulk_in_db(context, instance_uuids)
