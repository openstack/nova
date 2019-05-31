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

import functools

from oslo_utils import uuidutils

from nova import cache_utils
from nova.db import api as db
from nova import exception
from nova.objects import base
from nova.objects import fields


# NOTE(vish): cache mapping for one week
_CACHE_TIME = 7 * 24 * 60 * 60
_CACHE = None


def memoize(func):
    @functools.wraps(func)
    def memoizer(context, reqid):
        global _CACHE
        if not _CACHE:
            _CACHE = cache_utils.get_client(expiration_time=_CACHE_TIME)
        key = "%s:%s" % (func.__name__, reqid)
        key = str(key)
        value = _CACHE.get(key)
        if value is None:
            value = func(context, reqid)
            _CACHE.set(key, value)
        return value
    return memoizer


def id_to_ec2_id(instance_id, template='i-%08x'):
    """Convert an instance ID (int) to an ec2 ID (i-[base 16 number])."""
    return template % int(instance_id)


def id_to_ec2_inst_id(context, instance_id):
    """Get or create an ec2 instance ID (i-[base 16 number]) from uuid."""
    if instance_id is None:
        return None
    elif uuidutils.is_uuid_like(instance_id):
        int_id = get_int_id_from_instance_uuid(context, instance_id)
        return id_to_ec2_id(int_id)
    else:
        return id_to_ec2_id(instance_id)


@memoize
def get_int_id_from_instance_uuid(context, instance_uuid):
    if instance_uuid is None:
        return
    try:
        imap = EC2InstanceMapping.get_by_uuid(context, instance_uuid)
        return imap.id
    except exception.NotFound:
        imap = EC2InstanceMapping(context)
        imap.uuid = instance_uuid
        imap.create()
        return imap.id


def glance_id_to_ec2_id(context, glance_id, image_type='ami'):
    image_id = glance_id_to_id(context, glance_id)
    if image_id is None:
        return

    template = image_type + '-%08x'
    return id_to_ec2_id(image_id, template=template)


@memoize
def glance_id_to_id(context, glance_id):
    """Convert a glance id to an internal (db) id."""
    if not glance_id:
        return

    try:
        return S3ImageMapping.get_by_uuid(context, glance_id).id
    except exception.NotFound:
        s3imap = S3ImageMapping(context, uuid=glance_id)
        s3imap.create()
        return s3imap.id


def glance_type_to_ec2_type(image_type):
    """Converts to a three letter image type.

    aki, kernel => aki
    ari, ramdisk => ari
    anything else => ami

    """
    if image_type == 'kernel':
        return 'aki'
    if image_type == 'ramdisk':
        return 'ari'
    if image_type not in ['aki', 'ari']:
        return 'ami'
    return image_type


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

        ec2_ids['instance_id'] = id_to_ec2_inst_id(context, instance.uuid)
        ec2_ids['ami_id'] = glance_id_to_ec2_id(context, instance.image_ref)
        for image_type in ['kernel', 'ramdisk']:
            image_id = getattr(instance, '%s_id' % image_type)
            ec2_id = None
            if image_id is not None:
                ec2_image_type = glance_type_to_ec2_type(image_type)
                ec2_id = glance_id_to_ec2_id(context, image_id, ec2_image_type)
            ec2_ids['%s_id' % image_type] = ec2_id

        return ec2_ids

    @base.remotable_classmethod
    def get_by_instance(cls, context, instance):
        ec2_ids = cls._get_ec2_ids(context, instance)
        return cls._from_dict(cls(context), ec2_ids)
