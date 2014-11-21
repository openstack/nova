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

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import utils

KEYPAIR_TYPE_SSH = 'ssh'


# TODO(berrange): Remove NovaObjectDictCompat
class KeyPair(base.NovaPersistentObject, base.NovaObject,
              base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Added keypair type
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'fingerprint': fields.StringField(nullable=True),
        'public_key': fields.StringField(nullable=True),
        'type': fields.StringField(nullable=False),
        }

    def obj_make_compatible(self, primitive, target_version):
        super(KeyPair, self).obj_make_compatible(primitive, target_version)
        target_version = utils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'type' in primitive:
            del primitive['type']

    @staticmethod
    def _from_db_object(context, keypair, db_keypair):
        for key in keypair.fields:
            keypair[key] = db_keypair[key]
        keypair._context = context
        keypair.obj_reset_changes()
        return keypair

    @base.remotable_classmethod
    def get_by_name(cls, context, user_id, name):
        db_keypair = db.key_pair_get(context, user_id, name)
        return cls._from_db_object(context, cls(), db_keypair)

    @base.remotable_classmethod
    def destroy_by_name(cls, context, user_id, name):
        db.key_pair_destroy(context, user_id, name)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_keypair = db.key_pair_create(context, updates)
        self._from_db_object(context, self, db_keypair)

    @base.remotable
    def destroy(self, context):
        db.key_pair_destroy(context, self.user_id, self.name)


class KeyPairList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              KeyPair <= version 1.1
    # Version 1.1: KeyPair <= version 1.2
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('KeyPair'),
        }
    child_versions = {
        '1.0': '1.1',
        # NOTE(danms): KeyPair was at 1.1 before we added this
        '1.1': '1.2',
        }

    @base.remotable_classmethod
    def get_by_user(cls, context, user_id):
        db_keypairs = db.key_pair_get_all_by_user(context, user_id)
        return base.obj_make_list(context, cls(context), objects.KeyPair,
                                  db_keypairs)

    @base.remotable_classmethod
    def get_count_by_user(cls, context, user_id):
        return db.key_pair_count_by_user(context, user_id)
