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

from oslo_versionedobjects import base as ovo

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.objects import base
from nova.objects import cell_mapping
from nova.objects import fields


def _cell_id_in_updates(updates):
    cell_mapping_obj = updates.pop("cell_mapping", None)
    if cell_mapping_obj:
        updates["cell_id"] = cell_mapping_obj.id


# NOTE(danms): Maintain Dict compatibility because of ovo bug 1474952
@base.NovaObjectRegistry.register
class HostMapping(base.NovaTimestampObject, base.NovaObject,
                  ovo.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'host': fields.StringField(),
        'cell_mapping': fields.ObjectField('CellMapping'),
        }

    def _get_cell_mapping(self):
        with db_api.api_context_manager.reader.using(self._context) as session:
            cell_map = (session.query(api_models.CellMapping)
                        .join(api_models.HostMapping)
                        .filter(api_models.HostMapping.host == self.host)
                        .first())
            if cell_map is not None:
                return cell_mapping.CellMapping._from_db_object(
                    self._context, cell_mapping.CellMapping(), cell_map)

    def _load_cell_mapping(self):
        self.cell_mapping = self._get_cell_mapping()

    def obj_load_attr(self, attrname):
        if attrname == 'cell_mapping':
            self._load_cell_mapping()

    @staticmethod
    def _from_db_object(context, host_mapping, db_host_mapping):
        for key in host_mapping.fields:
            db_value = db_host_mapping.get(key)
            if key == "cell_mapping":
                # NOTE(dheeraj): If cell_mapping is stashed in db object
                # we load it here. Otherwise, lazy loading will happen
                # when .cell_mapping is accessd later
                if not db_value:
                    continue
                db_value = cell_mapping.CellMapping._from_db_object(
                    host_mapping._context, cell_mapping.CellMapping(),
                    db_value)
            setattr(host_mapping, key, db_value)
        host_mapping.obj_reset_changes()
        host_mapping._context = context
        return host_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_host_from_db(context, host):
        db_mapping = (context.session.query(api_models.HostMapping)
                      .join(api_models.CellMapping)
                      .with_entities(api_models.HostMapping,
                                     api_models.CellMapping)
                      .filter(api_models.HostMapping.host == host)).first()
        if not db_mapping:
            raise exception.HostMappingNotFound(name=host)
        host_mapping = db_mapping[0]
        host_mapping["cell_mapping"] = db_mapping[1]
        return host_mapping

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_mapping = cls._get_by_host_from_db(context, host)
        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_mapping = api_models.HostMapping()
        db_mapping.update(updates)
        db_mapping.save(context.session)
        return db_mapping

    @base.remotable
    def create(self):
        changes = self.obj_get_changes()
        # cell_mapping must be mapped to cell_id for create
        _cell_id_in_updates(changes)
        db_mapping = self._create_in_db(self._context, changes)
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, obj, updates):
        db_mapping = context.session.query(api_models.HostMapping).filter_by(
            id=obj.id).first()
        if not db_mapping:
            raise exception.HostMappingNotFound(name=obj.host)

        db_mapping.update(updates)
        return db_mapping

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        # cell_mapping must be mapped to cell_id for updates
        _cell_id_in_updates(changes)
        db_mapping = self._save_in_db(self._context, self.host, changes)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, host):
        result = context.session.query(api_models.HostMapping).filter_by(
                host=host).delete()
        if not result:
            raise exception.HostMappingNotFound(name=host)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.host)
