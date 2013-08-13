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
from nova.objects import base
from nova.objects import utils


class KeyPair(base.NovaObject):
    fields = {
        'id': int,
        'name': utils.str_or_none,
        'user_id': utils.str_or_none,
        'fingerprint': utils.str_or_none,
        'public_key': utils.str_or_none,
        }

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
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
        db_keypair = db.key_pair_create(context, updates)
        self._from_db_object(context, self, db_keypair)

    @base.remotable
    def destroy(self, context):
        db.key_pair_destroy(context, self.user_id, self.name)


def _make_list(context, list_obj, item_cls, db_list):
    list_obj.objects = []
    for db_item in db_list:
        item = item_cls._from_db_object(context, item_cls(), db_item)
        list_obj.objects.append(item)
    list_obj.obj_reset_changes()
    return list_obj


class KeyPairList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_user(cls, context, user_id):
        db_keypairs = db.key_pair_get_all_by_user(context, user_id)
        return _make_list(context, KeyPairList(), KeyPair, db_keypairs)

    @base.remotable_classmethod
    def get_count_by_user(cls, context, user_id):
        return db.key_pair_count_by_user(context, user_id)
