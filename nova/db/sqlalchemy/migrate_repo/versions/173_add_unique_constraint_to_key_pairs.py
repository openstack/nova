# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import Index, MetaData, Table

from nova.db.sqlalchemy import utils


OLD_IDX_NAME = 'key_pair_user_id_name_idx'
UC_NAME = 'key_pairs_uniq_name_and_user_id'
TABLE_NAME = 'key_pairs'
UC_COLUMNS = ['user_id', 'name', 'deleted']


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    key_pairs = Table(TABLE_NAME, meta, autoload=True)
    utils.drop_old_duplicate_entries_from_table(migrate_engine,
                                                TABLE_NAME, True,
                                                *UC_COLUMNS)
    old_idx = None
    #Drop old index because the new UniqueConstraint can be used instead.
    for index in key_pairs.indexes:
        if index.name == OLD_IDX_NAME:
            index.drop()
            old_idx = index

    #index.drop() in SQLAlchemy-migrate will issue a DROP INDEX statement to
    #the DB but WILL NOT update the table metadata to remove the `Index`
    #object. This can cause subsequent calls like drop or create constraint
    #on that table to fail.The solution is to update the table metadata to
    #reflect the now dropped column.
    if old_idx:
        key_pairs.indexes.remove(old_idx)
    uc = UniqueConstraint(*(UC_COLUMNS), table=key_pairs, name=UC_NAME)
    uc.create()


def downgrade(migrate_engine):
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME,
                                 *(UC_COLUMNS))
    meta = MetaData(bind=migrate_engine)
    key_pairs = Table(TABLE_NAME, meta, autoload=True)
    Index(OLD_IDX_NAME, key_pairs.c.user_id,
          key_pairs.c.name).create(migrate_engine)
