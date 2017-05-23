#    Copyright 2013 IBM Corp.
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

from oslo_log import log as logging

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class InstanceInfoCache(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Converted network_info to store the model.
    # Version 1.2: Added new() and update_cells kwarg to save().
    # Version 1.3: Added delete()
    # Version 1.4: String attributes updated to support unicode
    # Version 1.5: Actually set the deleted, created_at, updated_at, and
    #              deleted_at attributes
    VERSION = '1.5'

    fields = {
        'instance_uuid': fields.UUIDField(),
        'network_info': fields.Field(fields.NetworkModel(), nullable=True),
        }

    @staticmethod
    def _from_db_object(context, info_cache, db_obj):
        for field in info_cache.fields:
            setattr(info_cache, field, db_obj[field])
        info_cache.obj_reset_changes()
        info_cache._context = context
        return info_cache

    @classmethod
    def new(cls, context, instance_uuid):
        """Create an InfoCache object that can be used to create the DB
        entry for the first time.

        When save()ing this object, the info_cache_update() DB call
        will properly handle creating it if it doesn't exist already.
        """
        info_cache = cls()
        info_cache.instance_uuid = instance_uuid
        info_cache.network_info = None
        info_cache._context = context
        # Leave the fields dirty
        return info_cache

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_obj = db.instance_info_cache_get(context, instance_uuid)
        if not db_obj:
            raise exception.InstanceInfoCacheNotFound(
                    instance_uuid=instance_uuid)
        return cls._from_db_object(context, cls(context), db_obj)

    @staticmethod
    def _info_cache_cells_update(ctxt, info_cache):
        cell_type = cells_opts.get_cell_type()
        if cell_type != 'compute':
            return
        cells_api = cells_rpcapi.CellsAPI()
        try:
            cells_api.instance_info_cache_update_at_top(ctxt, info_cache)
        except Exception:
            LOG.exception("Failed to notify cells of instance info "
                          "cache update")

    @base.remotable
    def save(self, update_cells=True):
        if 'network_info' in self.obj_what_changed():
            if update_cells:
                stale_instance = self.obj_clone()
            nw_info_json = self.fields['network_info'].to_primitive(
                self, 'network_info', self.network_info)
            rv = db.instance_info_cache_update(self._context,
                                               self.instance_uuid,
                                               {'network_info': nw_info_json})
            self._from_db_object(self._context, self, rv)
            if update_cells:
                # Send a copy of ourselves before updates are applied so
                # that cells can tell what changed.
                self._info_cache_cells_update(self._context, stale_instance)
        self.obj_reset_changes()

    @base.remotable
    def delete(self):
        db.instance_info_cache_delete(self._context, self.instance_uuid)

    @base.remotable
    def refresh(self):
        current = self.__class__.get_by_instance_uuid(self._context,
                                                      self.instance_uuid)
        current._context = None

        for field in self.fields:
            if (self.obj_attr_is_set(field) and
                    getattr(self, field) != getattr(current, field)):
                setattr(self, field, getattr(current, field))

        self.obj_reset_changes()
