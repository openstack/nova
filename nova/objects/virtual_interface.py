# Copyright (C) 2014, Red Hat, Inc.
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
from nova import objects
from nova.objects import base
from nova.objects import fields


# TODO(berrange): Remove NovaObjectDictCompat
class VirtualInterface(base.NovaPersistentObject, base.NovaObject,
                       base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'address': fields.StringField(nullable=True),
        'network_id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, vif, db_vif):
        for field in vif.fields:
            vif[field] = db_vif[field]
        vif._context = context
        vif.obj_reset_changes()
        return vif

    @base.remotable_classmethod
    def get_by_id(cls, context, vif_id):
        db_vif = db.virtual_interface_get(context, vif_id)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, vif_uuid):
        db_vif = db.virtual_interface_get_by_uuid(context, vif_uuid)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_address(cls, context, address):
        db_vif = db.virtual_interface_get_by_address(context, address)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_instance_and_network(cls, context, instance_uuid, network_id):
        db_vif = db.virtual_interface_get_by_instance_and_network(context,
                instance_uuid, network_id)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_vif = db.virtual_interface_create(context, updates)
        self._from_db_object(context, self, db_vif)

    @base.remotable_classmethod
    def delete_by_instance_uuid(cls, context, instance_uuid):
        db.virtual_interface_delete_by_instance(context, instance_uuid)


class VirtualInterfaceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('VirtualInterface'),
    }
    child_versions = {
        '1.0': '1.0',
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        db_vifs = db.virtual_interface_get_all(context)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid, use_slave=False):
        db_vifs = db.virtual_interface_get_by_instance(context, instance_uuid,
                use_slave=use_slave)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)
