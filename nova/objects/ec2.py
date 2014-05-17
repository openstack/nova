# Copyright 2014 Red Hat Inc.
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


class EC2InstanceMapping(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, imap, db_imap):
        for field in imap.fields:
            imap[field] = db_imap[field]
        imap._context = context
        imap.obj_reset_changes()
        return imap

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_imap = db.ec2_instance_create(context, self.uuid)
        self._from_db_object(context, self, db_imap)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, instance_uuid):
        db_imap = db.ec2_instance_get_by_uuid(context, instance_uuid)
        if db_imap:
            return cls._from_db_object(context, cls(), db_imap)

    @base.remotable_classmethod
    def get_by_id(cls, context, ec2_id):
        db_imap = db.ec2_instance_get_by_id(context, ec2_id)
        if db_imap:
            return cls._from_db_object(context, cls(), db_imap)


class EC2VolumeMapping(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, vmap, db_vmap):
        for field in vmap.fields:
            vmap[field] = db_vmap[field]
        vmap._context = context
        vmap.obj_reset_changes()
        return vmap

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_vmap = db.ec2_volume_create(context, self.uuid)
        self._from_db_object(context, self, db_vmap)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, volume_uuid):
        db_vmap = db.ec2_volume_get_by_uuid(context, volume_uuid)
        if db_vmap:
            return cls._from_db_object(context, cls(context), db_vmap)

    @base.remotable_classmethod
    def get_by_id(cls, context, ec2_id):
        db_vmap = db.ec2_volume_get_by_id(context, ec2_id)
        if db_vmap:
            return cls._from_db_object(context, cls(context), db_vmap)
