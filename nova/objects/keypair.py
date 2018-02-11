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

from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import utils as sqlalchemyutils
from oslo_log import log as logging
from oslo_utils import versionutils

from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import models as main_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

KEYPAIR_TYPE_SSH = 'ssh'
KEYPAIR_TYPE_X509 = 'x509'
LOG = logging.getLogger(__name__)


@db_api.api_context_manager.reader
def _get_from_db(context, user_id, name=None, limit=None, marker=None):
    query = context.session.query(api_models.KeyPair).\
            filter(api_models.KeyPair.user_id == user_id)
    if name is not None:
        db_keypair = query.filter(api_models.KeyPair.name == name).\
                     first()
        if not db_keypair:
            raise exception.KeypairNotFound(user_id=user_id, name=name)
        return db_keypair

    marker_row = None
    if marker is not None:
        marker_row = context.session.query(api_models.KeyPair).\
            filter(api_models.KeyPair.name == marker).\
            filter(api_models.KeyPair.user_id == user_id).first()
        if not marker_row:
            raise exception.MarkerNotFound(marker=marker)

    query = sqlalchemyutils.paginate_query(
        query, api_models.KeyPair, limit, ['name'], marker=marker_row)

    return query.all()


@db_api.api_context_manager.reader
def _get_count_from_db(context, user_id):
    return context.session.query(api_models.KeyPair).\
        filter(api_models.KeyPair.user_id == user_id).\
        count()


@db_api.api_context_manager.writer
def _create_in_db(context, values):
    kp = api_models.KeyPair()
    kp.update(values)
    try:
        kp.save(context.session)
    except db_exc.DBDuplicateEntry:
        raise exception.KeyPairExists(key_name=values['name'])
    return kp


@db_api.api_context_manager.writer
def _destroy_in_db(context, user_id, name):
    result = context.session.query(api_models.KeyPair).\
             filter_by(user_id=user_id).\
             filter_by(name=name).\
             delete()
    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class KeyPair(base.NovaPersistentObject, base.NovaObject,
              base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Added keypair type
    # Version 1.3: Name field is non-null
    # Version 1.4: Add localonly flag to get_by_name()
    VERSION = '1.4'

    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=False),
        'user_id': fields.StringField(nullable=True),
        'fingerprint': fields.StringField(nullable=True),
        'public_key': fields.StringField(nullable=True),
        'type': fields.StringField(nullable=False),
        }

    def obj_make_compatible(self, primitive, target_version):
        super(KeyPair, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'type' in primitive:
            del primitive['type']

    @staticmethod
    def _from_db_object(context, keypair, db_keypair):
        ignore = {'deleted': False,
                  'deleted_at': None}
        for key in keypair.fields:
            if key in ignore and not hasattr(db_keypair, key):
                keypair[key] = ignore[key]
            else:
                keypair[key] = db_keypair[key]
        keypair._context = context
        keypair.obj_reset_changes()
        return keypair

    @staticmethod
    def _get_from_db(context, user_id, name):
        return _get_from_db(context, user_id, name=name)

    @staticmethod
    def _destroy_in_db(context, user_id, name):
        return _destroy_in_db(context, user_id, name)

    @staticmethod
    def _create_in_db(context, values):
        return _create_in_db(context, values)

    @base.remotable_classmethod
    def get_by_name(cls, context, user_id, name,
                    localonly=False):
        db_keypair = None
        if not localonly:
            try:
                db_keypair = cls._get_from_db(context, user_id, name)
            except exception.KeypairNotFound:
                pass
        if db_keypair is None:
            db_keypair = db.key_pair_get(context, user_id, name)
        return cls._from_db_object(context, cls(), db_keypair)

    @base.remotable_classmethod
    def destroy_by_name(cls, context, user_id, name):
        try:
            cls._destroy_in_db(context, user_id, name)
        except exception.KeypairNotFound:
            db.key_pair_destroy(context, user_id, name)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        # NOTE(danms): Check to see if it exists in the old DB before
        # letting them create in the API DB, since we won't get protection
        # from the UC.
        try:
            db.key_pair_get(self._context, self.user_id, self.name)
            raise exception.KeyPairExists(key_name=self.name)
        except exception.KeypairNotFound:
            pass

        self._create()

    def _create(self):
        updates = self.obj_get_changes()
        db_keypair = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_keypair)

    @base.remotable
    def destroy(self):
        try:
            self._destroy_in_db(self._context, self.user_id, self.name)
        except exception.KeypairNotFound:
            db.key_pair_destroy(self._context, self.user_id, self.name)


@base.NovaObjectRegistry.register
class KeyPairList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              KeyPair <= version 1.1
    # Version 1.1: KeyPair <= version 1.2
    # Version 1.2: KeyPair <= version 1.3
    # Version 1.3: Add new parameters 'limit' and 'marker' to get_by_user()
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('KeyPair'),
        }

    @staticmethod
    def _get_from_db(context, user_id, limit, marker):
        return _get_from_db(context, user_id, limit=limit, marker=marker)

    @staticmethod
    def _get_count_from_db(context, user_id):
        return _get_count_from_db(context, user_id)

    @base.remotable_classmethod
    def get_by_user(cls, context, user_id, limit=None, marker=None):
        try:
            api_db_keypairs = cls._get_from_db(
                context, user_id, limit=limit, marker=marker)
            # NOTE(pkholkin): If we were asked for a marker and found it in
            # results from the API DB, we must continue our pagination with
            # just the limit (if any) to the main DB.
            marker = None
        except exception.MarkerNotFound:
            api_db_keypairs = []

        if limit is not None:
            limit_more = limit - len(api_db_keypairs)
        else:
            limit_more = None

        if limit_more is None or limit_more > 0:
            main_db_keypairs = db.key_pair_get_all_by_user(
                context, user_id, limit=limit_more, marker=marker)
        else:
            main_db_keypairs = []

        return base.obj_make_list(context, cls(context), objects.KeyPair,
                                  api_db_keypairs + main_db_keypairs)

    @base.remotable_classmethod
    def get_count_by_user(cls, context, user_id):
        return (cls._get_count_from_db(context, user_id) +
                db.key_pair_count_by_user(context, user_id))


@db_api.pick_context_manager_reader
def _count_unmigrated_instances(context):
    return context.session.query(main_models.InstanceExtra).\
        filter_by(keypairs=None).\
        filter_by(deleted=0).\
        count()


@db_api.pick_context_manager_reader
def _get_main_keypairs(context, limit):
    return context.session.query(main_models.KeyPair).\
        filter_by(deleted=0).\
        limit(limit).\
        all()


def migrate_keypairs_to_api_db(context, count):
    bad_instances = _count_unmigrated_instances(context)
    if bad_instances:
        LOG.error('Some instances are still missing keypair '
                  'information. Unable to run keypair migration '
                  'at this time.')
        return 0, 0

    main_keypairs = _get_main_keypairs(context, count)
    done = 0
    for db_keypair in main_keypairs:
        kp = objects.KeyPair(context=context,
                             user_id=db_keypair.user_id,
                             name=db_keypair.name,
                             fingerprint=db_keypair.fingerprint,
                             public_key=db_keypair.public_key,
                             type=db_keypair.type)
        try:
            kp._create()
        except exception.KeyPairExists:
            # NOTE(danms): If this got created somehow in the API DB,
            # then it's newer and we just continue on to destroy the
            # old one in the cell DB.
            pass
        db_api.key_pair_destroy(context, db_keypair.user_id, db_keypair.name)
        done += 1

    return len(main_keypairs), done
