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

from nova.api.ec2 import ec2utils
from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
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
            setattr(imap, field, db_imap[field])
        imap._context = context
        imap.obj_reset_changes()
        return imap

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_imap = db.ec2_instance_create(self._context, self.uuid)
        self._from_db_object(self._context, self, db_imap)

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


@base.NovaObjectRegistry.register
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
            setattr(vmap, field, db_vmap[field])
        vmap._context = context
        vmap.obj_reset_changes()
        return vmap

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_vmap = db.ec2_volume_create(self._context, self.uuid)
        self._from_db_object(self._context, self, db_vmap)

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


@base.NovaObjectRegistry.register
class EC2SnapshotMapping(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, smap, db_smap):
        for field in smap.fields:
            setattr(smap, field, db_smap[field])
        smap._context = context
        smap.obj_reset_changes()
        return smap

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_smap = db.ec2_snapshot_create(self._context, self.uuid)
        self._from_db_object(self._context, self, db_smap)

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


@base.NovaObjectRegistry.register
class S3ImageMapping(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
    }

    @staticmethod
    def _from_db_object(context, s3imap, db_s3imap):
        for field in s3imap.fields:
            setattr(s3imap, field, db_s3imap[field])
        s3imap._context = context
        s3imap.obj_reset_changes()
        return s3imap

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_s3imap = db.s3_image_create(self._context, self.uuid)
        self._from_db_object(self._context, self, db_s3imap)

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


@base.NovaObjectRegistry.register
class EC2Ids(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'instance_id': fields.StringField(read_only=True),
        'ami_id': fields.StringField(nullable=True, read_only=True),
        'kernel_id': fields.StringField(nullable=True, read_only=True),
        'ramdisk_id': fields.StringField(nullable=True, read_only=True),
    }

    @staticmethod
    def _from_dict(ec2ids, dict_ec2ids):
        for field in ec2ids.fields:
            setattr(ec2ids, field, dict_ec2ids[field])
        return ec2ids

    @staticmethod
    def _get_ec2_ids(context, instance):
        ec2_ids = {}

        ec2_ids['instance_id'] = ec2utils.id_to_ec2_inst_id(instance.uuid)
        ec2_ids['ami_id'] = ec2utils.glance_id_to_ec2_id(context,
                                                         instance.image_ref)
        for image_type in ['kernel', 'ramdisk']:
            image_id = getattr(instance, '%s_id' % image_type)
            ec2_id = None
            if image_id is not None:
                ec2_image_type = ec2utils.image_type(image_type)
                ec2_id = ec2utils.glance_id_to_ec2_id(context, image_id,
                                                      ec2_image_type)
            ec2_ids['%s_id' % image_type] = ec2_id

        return ec2_ids

    @base.remotable_classmethod
    def get_by_instance(cls, context, instance):
        ec2_ids = cls._get_ec2_ids(context, instance)
        return cls._from_dict(cls(context), ec2_ids)
