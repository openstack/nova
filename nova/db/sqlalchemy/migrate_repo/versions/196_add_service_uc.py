# Copyright 2013 Mirantis Inc.
# All Rights Reserved
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table

from nova.db.sqlalchemy import utils


UC_NAME_1 = 'uniq_services0host0topic0deleted'
COLUMNS_1 = ('host', 'topic', 'deleted')
UC_NAME_2 = 'uniq_services0host0binary0deleted'
COLUMNS_2 = ('host', 'binary', 'deleted')
TABLE_NAME = 'services'


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    t = Table(TABLE_NAME, meta, autoload=True)

    utils.drop_old_duplicate_entries_from_table(migrate_engine, TABLE_NAME,
                                                True, *COLUMNS_1)
    uc1 = UniqueConstraint(*COLUMNS_1, table=t, name=UC_NAME_1)
    uc1.create()
    utils.drop_old_duplicate_entries_from_table(migrate_engine, TABLE_NAME,
                                                True, *COLUMNS_2)
    uc2 = UniqueConstraint(*COLUMNS_2, table=t, name=UC_NAME_2)
    uc2.create()


def downgrade(migrate_engine):
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME_1,
                                *COLUMNS_1)
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME_2,
                                *COLUMNS_2)
