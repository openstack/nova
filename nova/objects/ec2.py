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


# TODO(berrange): Remove NovaObjectDictCompat
class EC2InstanceMapping(base.NovaPersistentObject, base.NovaObject,
                         base.NovaObjectDictCompat):
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


# TODO(berrange): Remove NovaObjectDictCompat
class EC2VolumeMapping(base.NovaPersistentObject, base.NovaObject,
                       base.NovaObjectDictCompat):
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


# TODO(berrange): Remove NovaObjectDictCompat
class EC2SnapshotMapping(base.NovaPersistentObject, base.NovaObject,
                         base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, smap, db_smap):
        for field in smap.fields:
            smap[field] = db_smap[field]
        smap._context = context
        smap.obj_reset_changes()
        return smap

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_smap = db.ec2_snapshot_create(context, self.uuid)
        self._from_db_object(context, self, db_smap)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, snapshot_uuid):
        db_smap = db.ec2_snapshot_get_by_uuid(context, snapshot_uuid)
        if db_smap:
            return cls._from_db_object(context, cls(context), db_smap)

    @base.remotable_classmethod
    def get_by_id(cls, context, ec2_id):
        db_smap = db.ec2_snapshot_get_by_ec2_id(context, ec2_id)
        if db_smap:
            return cls._from_db_object(context, cls(context), db_smap)


# TODO(berrange): Remove NovaObjectDictCompat
class S3ImageMapping(base.NovaPersistentObject, base.NovaObject,
                     base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, s3imap, db_s3imap):
        for field in s3imap.fields:
            s3imap[field] = db_s3imap[field]
        s3imap._context = context
        s3imap.obj_reset_changes()
        return s3imap

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_s3imap = db.s3_image_create(context, self.uuid)
        self._from_db_object(context, self, db_s3imap)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, s3_image_uuid):
        db_s3imap = db.s3_image_get_by_uuid(context, s3_image_uuid)
        if db_s3imap:
            return cls._from_db_object(context, cls(context), db_s3imap)

    @base.remotable_classmethod
    def get_by_id(cls, context, s3_id):
        db_s3imap = db.s3_image_get(context, s3_id)
        if db_s3imap:
            return cls._from_db_object(context, cls(context), db_s3imap)
