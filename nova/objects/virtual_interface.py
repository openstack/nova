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

from oslo_utils import versionutils

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


VIF_OPTIONAL_FIELDS = ['network_id']


@base.NovaObjectRegistry.register
class VirtualInterface(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add tag field
    # Version 1.2: Adding a save method
    # Version 1.3: Added destroy() method
    VERSION = '1.3'

    fields = {
        'id': fields.IntegerField(),
        # This is a MAC address.
        'address': fields.StringField(nullable=True),
        'network_id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'uuid': fields.UUIDField(),
        'tag': fields.StringField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'tag' in primitive:
            del primitive['tag']

    @staticmethod
    def _from_db_object(context, vif, db_vif):
        for field in vif.fields:
            if not db_vif[field] and field in VIF_OPTIONAL_FIELDS:
                continue
            else:
                setattr(vif, field, db_vif[field])
        # NOTE(danms): The neutronv2 module namespaces mac addresses
        # with port id to avoid uniqueness constraints currently on
        # our table. Strip that out here so nobody else needs to care.
        if 'address' in vif and '/' in vif.address:
            vif.address, _ = vif.address.split('/', 1)
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
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_vif = db.virtual_interface_create(self._context, updates)
        self._from_db_object(self._context, self, db_vif)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        if 'address' in updates:
            raise exception.ObjectActionError(action='save',
                                              reason='address is not mutable')
        db_vif = db.virtual_interface_update(self._context, self.address,
                                             updates)
        return self._from_db_object(self._context, self, db_vif)

    @base.remotable_classmethod
    def delete_by_instance_uuid(cls, context, instance_uuid):
        db.virtual_interface_delete_by_instance(context, instance_uuid)

    @base.remotable
    def destroy(self):
        db.virtual_interface_delete(self._context, self.id)


@base.NovaObjectRegistry.register
class VirtualInterfaceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('VirtualInterface'),
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        db_vifs = db.virtual_interface_get_all(context)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)

    @staticmethod
    @db.select_db_reader_mode
    def _db_virtual_interface_get_by_instance(context, instance_uuid,
                                              use_slave=False):
        return db.virtual_interface_get_by_instance(context, instance_uuid)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid, use_slave=False):
        db_vifs = cls._db_virtual_interface_get_by_instance(
            context, instance_uuid, use_slave=use_slave)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)
